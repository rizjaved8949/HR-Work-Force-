"""Build simulation-specific employee features from existing HR data.

The source CSVs are read-only.  The output contains the same current Employee_ID
population and only new/derived simulation features, avoiding a second employee
master table.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import (
    ELIGIBILITY_SCORE,
    FEATURE_VERSION,
    MOBILITY_SCORE,
    PROMOTION_BASE_WEIGHTS,
    RESKILLING_BASE_WEIGHTS,
    TRANSFER_BASE_WEIGHTS,
)
from .errors import SimulationDataError


def _clip(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0).clip(0.0, 100.0)


def _engagement_to_pct(series: pd.Series) -> pd.Series:
    # Existing source uses a 1-5 scale.
    values = pd.to_numeric(series, errors="coerce").fillna(1.0)
    return (((values - 1.0) / 4.0) * 100.0).clip(0.0, 100.0)


def _current_role_skill_metrics(
    profile: pd.DataFrame,
    employee_skills: pd.DataFrame,
    requirements: pd.DataFrame,
) -> pd.DataFrame:
    required = profile[["Employee_ID", "Position_ID"]].merge(
        requirements[
            [
                "Position_ID",
                "Skill_ID",
                "Mandatory_Flag",
                "Minimum_Proficiency_Level",
                "Minimum_Skill_Score",
                "Skill_Weight_pct",
            ]
        ],
        on="Position_ID",
        how="left",
        validate="many_to_many",
    )

    skills = employee_skills[
        ["Employee_ID", "Skill_ID", "Proficiency_Level", "Skill_Score"]
    ].copy()

    joined = required.merge(
        skills,
        on=["Employee_ID", "Skill_ID"],
        how="left",
        validate="many_to_one",
    )

    joined["Proficiency_Level"] = pd.to_numeric(
        joined["Proficiency_Level"], errors="coerce"
    ).fillna(0.0)
    joined["Skill_Score"] = pd.to_numeric(
        joined["Skill_Score"], errors="coerce"
    ).fillna(0.0)
    joined["Minimum_Proficiency_Level"] = pd.to_numeric(
        joined["Minimum_Proficiency_Level"], errors="coerce"
    ).fillna(0.0)
    joined["Minimum_Skill_Score"] = pd.to_numeric(
        joined["Minimum_Skill_Score"], errors="coerce"
    ).fillna(0.0)
    joined["Skill_Weight_pct"] = pd.to_numeric(
        joined["Skill_Weight_pct"], errors="coerce"
    ).fillna(0.0)

    joined["Requirement_Met"] = (
        (joined["Proficiency_Level"] >= joined["Minimum_Proficiency_Level"])
        & (joined["Skill_Score"] >= joined["Minimum_Skill_Score"])
    )
    joined["Weighted_Met"] = (
        joined["Skill_Weight_pct"] * joined["Requirement_Met"].astype(float)
    )
    joined["Is_Mandatory"] = (
        joined["Mandatory_Flag"].astype(str).str.strip().str.lower().isin(
            {"yes", "y", "true", "1", "mandatory"}
        )
    )

    rows = []
    for employee_id, group in joined.groupby("Employee_ID", sort=False):
        total_weight = float(group["Skill_Weight_pct"].sum())
        met_weight = float(group["Weighted_Met"].sum())
        coverage = 100.0 if total_weight <= 0 else (met_weight / total_weight) * 100.0

        mandatory = group[group["Is_Mandatory"]]
        mandatory_total = len(mandatory)
        mandatory_met = int(mandatory["Requirement_Met"].sum())
        mandatory_coverage = (
            100.0
            if mandatory_total == 0
            else (mandatory_met / mandatory_total) * 100.0
        )

        rows.append(
            {
                "Employee_ID": employee_id,
                "Current_Role_Skill_Coverage_pct": round(coverage, 2),
                "Current_Role_Mandatory_Skill_Coverage_pct": round(
                    mandatory_coverage, 2
                ),
                "Current_Role_Skill_Gap_Count": int((~group["Requirement_Met"]).sum()),
                "Current_Role_Mandatory_Gap_Count": int(
                    (~mandatory["Requirement_Met"]).sum()
                ),
            }
        )

    return pd.DataFrame(rows)


def build_employee_simulation_features(data_dir: Path) -> pd.DataFrame:
    """Return one simulation-feature row for every current employee."""

    profile = pd.read_csv(data_dir / "Employee_Profile.csv")
    performance = pd.read_csv(data_dir / "Employee_Performance_Summary.csv")
    attendance = pd.read_csv(data_dir / "Employee_Attendance.csv")
    experience = pd.read_csv(data_dir / "Employee_Experience.csv")
    learning = pd.read_csv(data_dir / "Employee_Learning_Profile_Summary.csv")
    employee_skills = pd.read_csv(data_dir / "Employee_Skills.csv")
    skill_requirements = pd.read_csv(data_dir / "Position_Skill_Requirements.csv")

    if profile["Employee_ID"].duplicated().any():
        raise SimulationDataError("Employee_Profile.csv contains duplicate Employee_ID values.")

    base = profile[
        [
            "Employee_ID",
            "Internal_Mobility_Readiness",
            "Candidate_Base_Eligibility",
            "Engagement_Score",
            "Standard_Weekly_Hours",
            "Data_As_Of_Date",
        ]
    ].copy()

    base = base.merge(
        performance[["Employee_ID", "Latest_Performance_Score"]],
        on="Employee_ID",
        how="left",
        validate="one_to_one",
    )
    base = base.merge(
        attendance[
            [
                "Employee_ID",
                "Attendance_Percentage",
                "Attendance_Score",
                "Overtime_Hours_Last_30D",
            ]
        ],
        on="Employee_ID",
        how="left",
        validate="one_to_one",
    )
    base = base.merge(
        experience[
            [
                "Employee_ID",
                "Experience_Score",
                "Cross_Functional_Projects",
            ]
        ],
        on="Employee_ID",
        how="left",
        validate="one_to_one",
    )
    base = base.merge(
        learning[
            [
                "Employee_ID",
                "Completed_Course_Count",
                "Position_Skill_Gap_Count",
                "Mandatory_Skill_Gap_Count",
            ]
        ],
        on="Employee_ID",
        how="left",
        validate="one_to_one",
    )

    skill_metrics = _current_role_skill_metrics(
        profile,
        employee_skills,
        skill_requirements,
    )
    base = base.merge(
        skill_metrics,
        on="Employee_ID",
        how="left",
        validate="one_to_one",
    )

    performance_score = _clip(base["Latest_Performance_Score"])
    experience_score = _clip(base["Experience_Score"])
    attendance_score = _clip(base["Attendance_Score"])
    mobility_score = (
        base["Internal_Mobility_Readiness"].map(MOBILITY_SCORE).fillna(0.0)
    )
    eligibility_score = (
        base["Candidate_Base_Eligibility"].map(ELIGIBILITY_SCORE).fillna(0.0)
    )

    max_cross = max(float(base["Cross_Functional_Projects"].max()), 1.0)
    cross_exposure = (
        pd.to_numeric(base["Cross_Functional_Projects"], errors="coerce").fillna(0.0)
        / max_cross
        * 100.0
    ).clip(0.0, 100.0)

    max_courses = max(float(base["Completed_Course_Count"].max()), 1.0)
    learning_activity = (
        pd.to_numeric(base["Completed_Course_Count"], errors="coerce").fillna(0.0)
        / max_courses
        * 100.0
    ).clip(0.0, 100.0)

    engagement_pct = _engagement_to_pct(base["Engagement_Score"])

    promotion = (
        performance_score * PROMOTION_BASE_WEIGHTS["performance"]
        + experience_score * PROMOTION_BASE_WEIGHTS["experience"]
        + attendance_score * PROMOTION_BASE_WEIGHTS["attendance"]
        + mobility_score * PROMOTION_BASE_WEIGHTS["mobility"]
        + eligibility_score * PROMOTION_BASE_WEIGHTS["eligibility"]
    )

    transfer = (
        performance_score * TRANSFER_BASE_WEIGHTS["performance"]
        + attendance_score * TRANSFER_BASE_WEIGHTS["attendance"]
        + mobility_score * TRANSFER_BASE_WEIGHTS["mobility"]
        + cross_exposure * TRANSFER_BASE_WEIGHTS["cross_functional_exposure"]
        + eligibility_score * TRANSFER_BASE_WEIGHTS["eligibility"]
    )

    reskilling = (
        performance_score * RESKILLING_BASE_WEIGHTS["performance"]
        + attendance_score * RESKILLING_BASE_WEIGHTS["attendance"]
        + engagement_pct * RESKILLING_BASE_WEIGHTS["engagement"]
        + learning_activity * RESKILLING_BASE_WEIGHTS["learning_activity"]
        + mobility_score * RESKILLING_BASE_WEIGHTS["mobility"]
    )

    mandatory_gap = pd.to_numeric(
        base["Mandatory_Skill_Gap_Count"], errors="coerce"
    ).fillna(0.0)
    total_gap = pd.to_numeric(
        base["Position_Skill_Gap_Count"], errors="coerce"
    ).fillna(0.0)
    max_mandatory_gap = max(float(mandatory_gap.max()), 1.0)
    max_total_gap = max(float(total_gap.max()), 1.0)
    reskilling_need = (
        (mandatory_gap / max_mandatory_gap * 100.0) * 0.60
        + (total_gap / max_total_gap * 100.0) * 0.40
    ).clip(0.0, 100.0)

    weekly_hours = pd.to_numeric(
        base["Standard_Weekly_Hours"], errors="coerce"
    ).replace(0, pd.NA)
    monthly_standard_hours = weekly_hours * 4.33
    overtime_load = (
        pd.to_numeric(base["Overtime_Hours_Last_30D"], errors="coerce").fillna(0.0)
        / monthly_standard_hours
        * 100.0
    ).fillna(0.0).clip(lower=0.0)

    output = pd.DataFrame(
        {
            "Employee_ID": base["Employee_ID"],
            "Promotion_Base_Readiness_Score_pct": promotion.round(2),
            "Transfer_Base_Readiness_Score_pct": transfer.round(2),
            "Reskilling_Base_Readiness_Score_pct": reskilling.round(2),
            "Reskilling_Need_Score_pct": reskilling_need.round(2),
            "Current_Role_Skill_Coverage_pct": base[
                "Current_Role_Skill_Coverage_pct"
            ].round(2),
            "Current_Role_Mandatory_Skill_Coverage_pct": base[
                "Current_Role_Mandatory_Skill_Coverage_pct"
            ].round(2),
            "Current_Role_Skill_Gap_Count": base[
                "Current_Role_Skill_Gap_Count"
            ].fillna(0).astype(int),
            "Current_Role_Mandatory_Gap_Count": base[
                "Current_Role_Mandatory_Gap_Count"
            ].fillna(0).astype(int),
            "Cross_Functional_Exposure_Score_pct": cross_exposure.round(2),
            "Overtime_Load_pct": overtime_load.round(2),
            "Attendance_Availability_pct": pd.to_numeric(
                base["Attendance_Percentage"], errors="coerce"
            ).fillna(0.0).round(2),
            "Simulation_Feature_Version": FEATURE_VERSION,
            "Source_Data_As_Of_Date": base["Data_As_Of_Date"],
            "Feature_Source": "DERIVED_FROM_EXISTING_HR_DATA",
        }
    )

    if len(output) != len(profile):
        raise SimulationDataError(
            f"Expected {len(profile)} employee feature rows, built {len(output)}."
        )
    if output["Employee_ID"].duplicated().any():
        raise SimulationDataError("Derived simulation features contain duplicate Employee_ID values.")
    if set(output["Employee_ID"]) != set(profile["Employee_ID"]):
        raise SimulationDataError("Simulation feature Employee_ID set does not match Employee_Profile.csv.")

    return output


def write_employee_simulation_features(data_dir: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    features = build_employee_simulation_features(data_dir)
    features.to_csv(output_path, index=False)
    return output_path
