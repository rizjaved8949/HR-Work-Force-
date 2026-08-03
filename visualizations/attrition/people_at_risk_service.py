"""People-at-risk analytics for the attrition dashboard.

This module deliberately contains no frontend rendering and no LLM calls.
It reuses the saved CatBoost model for batch attrition predictions, the
existing replacement tool for successor recommendations, and the shared CSV
files resolved through ``backend/paths.py``.
"""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
from threading import RLock
from typing import Any, Optional

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool

EXPECTED_FEATURES = [
    "Tenure_Months",
    "Monthly_Salary_PKR",
    "Salary_vs_Market_pct",
    "Last_Increment_pct",
    "Months_Since_Last_Promotion",
    "KPI_Achievement_pct",
    "Performance_Trend_6M",
    "Overtime_Hours_Last_30D",
    "Engagement_Score",
    "Job_Satisfaction_Score",
    "Work_Life_Balance_Score",
    "Manager_Relationship_Score",
    "Career_Growth_Score",
    "Pay_Concern_Raised_Last_6M",
]
CATEGORICAL_FEATURES = ["Pay_Concern_Raised_Last_6M"]


ATTRITION_FILE = "Final_Attrition_Dataset_200_Employees.csv"
PROFILE_FILE = "Employee_Profile.csv"
POSITION_FILE = "Position_Master.csv"

FEATURE_LABELS: dict[str, str] = {
    "Tenure_Months": "Employee tenure",
    "Monthly_Salary_PKR": "Current salary level",
    "Salary_vs_Market_pct": "Salary competitiveness against the market",
    "Last_Increment_pct": "Recent salary increment",
    "Months_Since_Last_Promotion": "Time since the last promotion",
    "KPI_Achievement_pct": "KPI achievement pattern",
    "Performance_Trend_6M": "Recent performance trend",
    "Overtime_Hours_Last_30D": "Recent overtime workload",
    "Engagement_Score": "Employee engagement",
    "Job_Satisfaction_Score": "Job satisfaction",
    "Work_Life_Balance_Score": "Work-life balance",
    "Manager_Relationship_Score": "Relationship with the manager",
    "Career_Growth_Score": "Career-growth opportunities",
    "Pay_Concern_Raised_Last_6M": "Recently raised pay concern",
}

FEATURE_UNITS: dict[str, str] = {
    "Tenure_Months": "months",
    "Monthly_Salary_PKR": "PKR",
    "Salary_vs_Market_pct": "percent",
    "Last_Increment_pct": "percent",
    "Months_Since_Last_Promotion": "months",
    "KPI_Achievement_pct": "percent",
    "Performance_Trend_6M": "score",
    "Overtime_Hours_Last_30D": "hours",
    "Engagement_Score": "score",
    "Job_Satisfaction_Score": "score",
    "Work_Life_Balance_Score": "score",
    "Manager_Relationship_Score": "score",
    "Career_Growth_Score": "score",
    "Pay_Concern_Raised_Last_6M": "yes_no",
}


def _clean_employee_id(value: Any) -> str:
    return str(value or "").strip().upper()


def _json_value(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe Python values."""

    if value is None:
        return None

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)

    if isinstance(value, (np.bool_,)):
        return bool(value)

    if pd.isna(value):
        return None

    return value


def _display_value(feature: str, value: Any) -> str:
    clean = _json_value(value)
    if clean is None:
        return "Not available"

    unit = FEATURE_UNITS.get(feature)

    if unit == "PKR":
        try:
            return f"PKR {float(clean):,.0f}"
        except (TypeError, ValueError):
            return str(clean)

    if unit == "percent":
        try:
            return f"{float(clean):.1f}%"
        except (TypeError, ValueError):
            return str(clean)

    if unit in {"months", "hours"}:
        try:
            number = float(clean)
            rendered = str(int(number)) if number.is_integer() else f"{number:.1f}"
            return f"{rendered} {unit}"
        except (TypeError, ValueError):
            return str(clean)

    if unit == "score":
        try:
            return f"{float(clean):.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(clean)

    return str(clean)


class PeopleAtRiskService:
    """Build and serve the shared employee-level attrition risk table."""

    def __init__(
        self,
        data_dir: str | Path,
        model_path: str | Path,
        replacement_tool: Optional[Any] = None,
        risk_threshold: Optional[float] = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.model_path = Path(model_path).resolve()
        self.replacement_tool = replacement_tool
        self.risk_threshold = (
            float(risk_threshold)
            if risk_threshold is not None
            else float(os.getenv("DASHBOARD_ATTRITION_THRESHOLD", "0.5"))
        )

        if not 0 <= self.risk_threshold <= 1:
            raise ValueError("DASHBOARD_ATTRITION_THRESHOLD must be between 0 and 1.")

        if not self.data_dir.is_dir():
            raise FileNotFoundError(
                f"Dashboard data folder was not found: {self.data_dir}"
            )

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Dashboard CatBoost model was not found: {self.model_path}"
            )

        self.attrition_file = self.data_dir / ATTRITION_FILE
        self.profile_file = self.data_dir / PROFILE_FILE
        self.position_file = self.data_dir / POSITION_FILE

        for required_file in (
            self.attrition_file,
            self.profile_file,
            self.position_file,
        ):
            if not required_file.is_file():
                raise FileNotFoundError(
                    f"Required dashboard file was not found: {required_file}"
                )

        # Use the exact same saved CatBoost model and feature schema as the
        # existing attrition tool. The dashboard loads it once for efficient
        # batch prediction across all employees.
        self.model = CatBoostClassifier()
        self.model.load_model(str(self.model_path))
        stored_features = list(getattr(self.model, "feature_names_", []) or [])
        self.feature_order = stored_features or EXPECTED_FEATURES.copy()
        missing_features = [
            feature for feature in EXPECTED_FEATURES
            if feature not in self.feature_order
        ]
        if missing_features:
            raise ValueError(
                "Saved CatBoost model is missing dashboard features: "
                f"{missing_features}"
            )
        self._lock = RLock()
        self._source_signature: tuple[tuple[str, int, int], ...] = ()
        self._risk_table = pd.DataFrame()
        self._profiles = pd.DataFrame()
        self._positions = pd.DataFrame()

        self.refresh(force=True)

    # ------------------------------------------------------------------
    # Data loading and automatic refresh
    # ------------------------------------------------------------------

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        files = (
            self.attrition_file,
            self.profile_file,
            self.position_file,
            self.model_path,
        )
        return tuple(
            (
                str(path),
                path.stat().st_mtime_ns,
                path.stat().st_size,
            )
            for path in files
        )

    def _ensure_fresh(self) -> None:
        # When a CSV is updated locally, the next API request automatically
        # rebuilds the card and employee list. On Render, a Git deployment
        # restarts the service and therefore builds from the new files.
        if self._current_signature() != self._source_signature:
            self.refresh(force=True)

    @staticmethod
    def _validate_columns(
        dataframe: pd.DataFrame,
        required_columns: set[str],
        file_name: str,
    ) -> None:
        missing = sorted(required_columns - set(dataframe.columns))
        if missing:
            raise ValueError(
                f"{file_name} is missing required columns: {missing}"
            )

    def _prepare_feature_frame(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        prepared: dict[str, pd.Series] = {}

        for feature in self.feature_order:
            if feature not in dataframe.columns:
                if feature in CATEGORICAL_FEATURES:
                    prepared[feature] = pd.Series(
                        ["Missing"] * len(dataframe),
                        index=dataframe.index,
                    )
                else:
                    prepared[feature] = pd.Series(
                        [np.nan] * len(dataframe),
                        index=dataframe.index,
                    )
                continue

            source = dataframe[feature]

            if feature in CATEGORICAL_FEATURES:
                normalized = (
                    source.fillna("")
                    .astype(str)
                    .str.strip()
                    .str.casefold()
                    .map({
                        "yes": "Yes",
                        "y": "Yes",
                        "1": "Yes",
                        "true": "Yes",
                        "no": "No",
                        "n": "No",
                        "0": "No",
                        "false": "No",
                    })
                )
                prepared[feature] = normalized.fillna("Missing")
            else:
                prepared[feature] = pd.to_numeric(
                    source.astype(str).str.replace(",", "", regex=False),
                    errors="coerce",
                )

        return pd.DataFrame(
            prepared,
            columns=self.feature_order,
            index=dataframe.index,
        )

    def _build_risk_table(
        self,
        attrition_data: pd.DataFrame,
        profile_data: pd.DataFrame,
        position_data: pd.DataFrame,
    ) -> pd.DataFrame:
        feature_frame = self._prepare_feature_frame(attrition_data)
        pool = Pool(
            data=feature_frame,
            cat_features=CATEGORICAL_FEATURES,
            feature_names=self.feature_order,
        )

        probabilities = np.asarray(
            self.model.predict_proba(pool)
        )[:, 1]

        shap_values = np.asarray(
            self.model.get_feature_importance(
                data=pool,
                type="ShapValues",
            )
        )

        feature_contributions = (
            shap_values[:, :-1]
            if shap_values.ndim == 2
            else np.zeros((len(attrition_data), len(self.feature_order)))
        )

        prediction_rows: list[dict[str, Any]] = []

        for row_number, (_, source_row) in enumerate(attrition_data.iterrows()):
            probability = float(probabilities[row_number])
            positive_features = [
                (feature, float(contribution))
                for feature, contribution in zip(
                    self.feature_order,
                    feature_contributions[row_number],
                )
                if float(contribution) > 0
            ]
            positive_features.sort(key=lambda item: item[1], reverse=True)

            prediction_row: dict[str, Any] = {
                "Employee_ID": _clean_employee_id(source_row.get("Employee_ID")),
                "Source_Employee_Name": source_row.get("Employee_Name"),
                "Source_Department": source_row.get("Department"),
                "Source_Job_Level": source_row.get("Job_Level"),
                "risk_probability": probability,
                "risk_score_percent": round(probability * 100, 2),
                "at_risk": probability >= self.risk_threshold,
                "attrition_status": (
                    "At Risk" if probability >= self.risk_threshold else "Not At Risk"
                ),
                "top_reason_keys": [
                    feature for feature, _ in positive_features[:3]
                ],
            }

            for feature in EXPECTED_FEATURES:
                prediction_row[feature] = source_row.get(feature)

            prediction_rows.append(prediction_row)

        predictions = pd.DataFrame(prediction_rows)

        profiles = profile_data.copy()
        profiles["Employee_ID"] = profiles["Employee_ID"].map(_clean_employee_id)

        positions = position_data.copy()
        positions["Position_ID"] = positions["Position_ID"].astype(str).str.strip()
        position_lookup = positions[
            ["Position_ID", "Position_Criticality"]
        ].drop_duplicates(subset=["Position_ID"], keep="first")

        risk_table = predictions.merge(
            profiles,
            on="Employee_ID",
            how="left",
        )
        risk_table = risk_table.merge(
            position_lookup,
            on="Position_ID",
            how="left",
            suffixes=("", "_position"),
        )

        risk_table["Employee_Name"] = risk_table["Employee_Name"].fillna(
            risk_table["Source_Employee_Name"]
        )
        risk_table["Department"] = risk_table["Department"].fillna(
            risk_table["Source_Department"]
        )
        risk_table["Job_Level"] = risk_table["Job_Level"].fillna(
            risk_table["Source_Job_Level"]
        )
        risk_table["Position_Criticality"] = risk_table[
            "Position_Criticality"
        ].fillna("Not available")

        return risk_table.sort_values(
            ["at_risk", "risk_probability", "Employee_ID"],
            ascending=[False, False, True],
        ).reset_index(drop=True)

    def refresh(self, force: bool = False) -> dict[str, Any]:
        """Reload CSVs and rebuild all model predictions."""

        with self._lock:
            signature = self._current_signature()
            if not force and signature == self._source_signature:
                return self.get_summary(_skip_refresh=True)

            attrition_data = pd.read_csv(self.attrition_file)
            profile_data = pd.read_csv(self.profile_file)
            position_data = pd.read_csv(self.position_file)

            self._validate_columns(
                attrition_data,
                {"Employee_ID", *EXPECTED_FEATURES},
                self.attrition_file.name,
            )
            self._validate_columns(
                profile_data,
                {
                    "Employee_ID",
                    "Employee_Name",
                    "Position_ID",
                    "Position_Title",
                },
                self.profile_file.name,
            )
            self._validate_columns(
                position_data,
                {"Position_ID", "Position_Criticality"},
                self.position_file.name,
            )

            attrition_data["Employee_ID"] = attrition_data[
                "Employee_ID"
            ].map(_clean_employee_id)

            if attrition_data["Employee_ID"].duplicated().any():
                duplicates = sorted(
                    attrition_data.loc[
                        attrition_data["Employee_ID"].duplicated(keep=False),
                        "Employee_ID",
                    ].unique()
                )
                raise ValueError(
                    "The attrition dataset must contain one row per employee. "
                    f"Duplicate Employee_ID values: {duplicates[:10]}"
                )

            profile_data["Employee_ID"] = profile_data[
                "Employee_ID"
            ].map(_clean_employee_id)

            if profile_data["Employee_ID"].duplicated().any():
                duplicates = sorted(
                    profile_data.loc[
                        profile_data["Employee_ID"].duplicated(keep=False),
                        "Employee_ID",
                    ].unique()
                )
                raise ValueError(
                    "Employee_Profile.csv must contain one row per employee. "
                    f"Duplicate Employee_ID values: {duplicates[:10]}"
                )

            self._profiles = profile_data
            self._positions = position_data
            self._risk_table = self._build_risk_table(
                attrition_data=attrition_data,
                profile_data=profile_data,
                position_data=position_data,
            )
            self._source_signature = signature

            return self.get_summary(_skip_refresh=True)

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------

    def _factor_objects(self, row: pd.Series) -> list[dict[str, Any]]:
        factors: list[dict[str, Any]] = []

        for rank, feature in enumerate(row.get("top_reason_keys", []) or [], start=1):
            raw_value = row.get(feature)
            factors.append({
                "rank": rank,
                "feature_key": feature,
                "label": FEATURE_LABELS.get(feature, feature),
                "value": _json_value(raw_value),
                "display_value": _display_value(feature, raw_value),
            })

        return factors

    @staticmethod
    def _profile_url(employee_id: str) -> str:
        return (
            "/api/v1/dashboard/attrition/employees/"
            f"{employee_id}/profile"
        )

    @staticmethod
    def _detail_url(employee_id: str) -> str:
        return (
            "/api/v1/dashboard/attrition/people-at-risk/"
            f"{employee_id}"
        )

    def _list_item(self, row: pd.Series) -> dict[str, Any]:
        employee_id = _clean_employee_id(row.get("Employee_ID"))
        factors = self._factor_objects(row)

        return {
            "employee_id": employee_id,
            "employee_name": _json_value(row.get("Employee_Name")),
            "department": _json_value(row.get("Department")),
            "position_id": _json_value(row.get("Position_ID")),
            "position_title": _json_value(row.get("Position_Title")),
            "designation": _json_value(row.get("Designation")),
            "job_level": _json_value(row.get("Job_Level")),
            "position_criticality": _json_value(
                row.get("Position_Criticality")
            ),
            "attrition_status": "At Risk",
            "risk_score_percent": float(row.get("risk_score_percent", 0.0)),
            "attrition_factors": [factor["label"] for factor in factors],
            "detail_endpoint": self._detail_url(employee_id),
            "profile_endpoint": self._profile_url(employee_id),
        }

    def get_summary(self, _skip_refresh: bool = False) -> dict[str, Any]:
        if not _skip_refresh:
            self._ensure_fresh()

        total = int(len(self._risk_table))
        people_at_risk = int(self._risk_table["at_risk"].sum())
        not_at_risk = total - people_at_risk
        risk_rate = round(
            (people_at_risk / total * 100) if total else 0.0,
            2,
        )

        return {
            "status": "success",
            "visual": "people_at_risk",
            "prediction_window": "next_6_months",
            "risk_threshold": self.risk_threshold,
            "total_employees": total,
            "people_at_risk": people_at_risk,
            "people_not_at_risk": not_at_risk,
            "attrition_risk_rate_percent": risk_rate,
            "people_at_risk_endpoint": (
                "/api/v1/dashboard/attrition/people-at-risk"
            ),
            "department_risk_endpoint": (
                "/api/v1/dashboard/attrition/department-risk"
            ),
            "top_risk_drivers_endpoint": (
                "/api/v1/dashboard/attrition/top-risk-drivers"
            ),
        }

    def get_department_risk(self) -> dict[str, Any]:
        """Return attrition-risk counts grouped by department.

        The chart uses ``people_at_risk`` as the bar value. The response also
        includes each department's workforce total and risk percentage for
        tooltips or supporting labels. All values come from the same cached
        employee-level prediction table used by the People at Risk card.
        """

        self._ensure_fresh()

        department_data = self._risk_table.copy()
        department_data["Department"] = (
            department_data["Department"]
            .fillna("Not available")
            .astype(str)
            .str.strip()
            .replace("", "Not available")
        )

        grouped = (
            department_data
            .groupby("Department", dropna=False)
            .agg(
                total_employees=("Employee_ID", "count"),
                people_at_risk=("at_risk", "sum"),
            )
            .reset_index()
        )

        grouped["people_at_risk"] = grouped["people_at_risk"].astype(int)
        grouped["total_employees"] = grouped["total_employees"].astype(int)
        grouped["risk_rate_percent"] = np.where(
            grouped["total_employees"] > 0,
            grouped["people_at_risk"] / grouped["total_employees"] * 100,
            0.0,
        )
        grouped["risk_rate_percent"] = grouped[
            "risk_rate_percent"
        ].round(2)

        grouped = grouped.sort_values(
            ["people_at_risk", "risk_rate_percent", "Department"],
            ascending=[False, False, True],
        ).reset_index(drop=True)

        departments: list[dict[str, Any]] = []
        for rank, row in grouped.iterrows():
            department = str(row["Department"])
            departments.append({
                "rank": rank + 1,
                "department": department,
                "people_at_risk": int(row["people_at_risk"]),
                "total_employees": int(row["total_employees"]),
                "risk_rate_percent": float(row["risk_rate_percent"]),
                "people_at_risk_endpoint": (
                    "/api/v1/dashboard/attrition/people-at-risk"
                    f"?department={department}"
                ),
            })

        highest_risk_department = departments[0] if departments else None

        return {
            "status": "success",
            "visual": "attrition_risk_by_department",
            "metric": "people_at_risk",
            "total_departments": len(departments),
            "total_people_at_risk": int(
                self._risk_table["at_risk"].sum()
            ),
            "highest_risk_department": highest_risk_department,
            "departments": departments,
        }

    def get_top_risk_drivers(self, limit: int = 3) -> dict[str, Any]:
        """Aggregate the model's top positive risk drivers for at-risk staff.

        Each at-risk employee contributes up to three SHAP-derived feature
        names from the same batch prediction table used by the other dashboard
        endpoints. The percentages therefore represent the share of model
        risk-driver mentions, not confirmed resignation or exit-interview
        reasons.
        """

        self._ensure_fresh()

        if limit < 1:
            raise ValueError("limit must be at least 1")

        at_risk = self._risk_table[self._risk_table["at_risk"]]
        mention_counter: Counter[str] = Counter()

        for reason_keys in at_risk["top_reason_keys"]:
            for feature in (reason_keys or []):
                if feature:
                    mention_counter[str(feature)] += 1

        total_mentions = int(sum(mention_counter.values()))
        people_at_risk = int(len(at_risk))

        ranked = sorted(
            mention_counter.items(),
            key=lambda item: (
                -item[1],
                FEATURE_LABELS.get(item[0], item[0]).casefold(),
            ),
        )

        drivers: list[dict[str, Any]] = []
        for rank, (feature, mention_count) in enumerate(
            ranked[:limit],
            start=1,
        ):
            drivers.append({
                "rank": rank,
                "feature_key": feature,
                "label": FEATURE_LABELS.get(feature, feature),
                "mention_count": int(mention_count),
                "share_percent": round(
                    mention_count / total_mentions * 100
                    if total_mentions
                    else 0.0,
                    2,
                ),
                "employee_share_percent": round(
                    mention_count / people_at_risk * 100
                    if people_at_risk
                    else 0.0,
                    2,
                ),
            })

        top_mentions = sum(item["mention_count"] for item in drivers)
        other_mentions = max(total_mentions - top_mentions, 0)

        chart_segments = [
            {
                "label": item["label"],
                "value": item["mention_count"],
                "share_percent": item["share_percent"],
            }
            for item in drivers
        ]
        if other_mentions:
            chart_segments.append({
                "label": "Other model risk drivers",
                "value": other_mentions,
                "share_percent": round(
                    other_mentions / total_mentions * 100,
                    2,
                ),
            })

        return {
            "status": "success",
            "visual": "top_attrition_risk_drivers",
            "title": "Top Attrition Risk Drivers",
            "basis": "model_top_features_for_at_risk_employees",
            "interpretation_note": (
                "Percentages are shares of model risk-driver mentions, "
                "not confirmed exit reasons."
            ),
            "people_at_risk": people_at_risk,
            "reasons_per_employee_maximum": 3,
            "total_reason_mentions": total_mentions,
            "top_driver": drivers[0] if drivers else None,
            "drivers": drivers,
            "other_reason_mentions": other_mentions,
            "chart_segments": chart_segments,
        }

    def get_people_at_risk(
        self,
        offset: int = 0,
        limit: int = 50,
        department: Optional[str] = None,
        position_criticality: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        self._ensure_fresh()

        filtered = self._risk_table[self._risk_table["at_risk"]].copy()

        if department:
            filtered = filtered[
                filtered["Department"].fillna("").astype(str).str.casefold()
                == department.strip().casefold()
            ]

        if position_criticality:
            filtered = filtered[
                filtered["Position_Criticality"]
                .fillna("")
                .astype(str)
                .str.casefold()
                == position_criticality.strip().casefold()
            ]

        if search:
            needle = search.strip().casefold()
            haystack = (
                filtered["Employee_ID"].fillna("").astype(str)
                + " "
                + filtered["Employee_Name"].fillna("").astype(str)
                + " "
                + filtered["Position_Title"].fillna("").astype(str)
                + " "
                + filtered["Department"].fillna("").astype(str)
            ).str.casefold()
            filtered = filtered[haystack.str.contains(needle, regex=False)]

        filtered = filtered.sort_values(
            ["risk_probability", "Employee_ID"],
            ascending=[False, True],
        )

        total_matching = int(len(filtered))
        page = filtered.iloc[offset : offset + limit]

        return {
            "status": "success",
            "visual": "people_at_risk_list",
            "total_matching": total_matching,
            "offset": offset,
            "limit": limit,
            "employees": [
                self._list_item(row)
                for _, row in page.iterrows()
            ],
        }

    def _find_risk_row(self, employee_id: str) -> pd.Series:
        normalized_id = _clean_employee_id(employee_id)
        matches = self._risk_table[
            self._risk_table["Employee_ID"] == normalized_id
        ]

        if matches.empty:
            raise KeyError(normalized_id)

        return matches.iloc[0]

    def _recommended_replacements(
        self,
        employee_id: str,
    ) -> tuple[str, list[dict[str, Any]], Optional[str]]:
        if self.replacement_tool is None:
            return "unavailable", [], None

        result = self.replacement_tool.invoke({
            "employee_id": employee_id,
        })
        status = str(result.get("status", "error"))
        recommendations: list[dict[str, Any]] = []

        for candidate in result.get("recommended_successors", []) or []:
            candidate_id = _clean_employee_id(candidate.get("employee_id"))
            profile_matches = self._profiles[
                self._profiles["Employee_ID"] == candidate_id
            ]

            profile_row = (
                profile_matches.iloc[0]
                if not profile_matches.empty
                else None
            )
            position_criticality = None
            position_title = candidate.get("current_position")

            if profile_row is not None:
                position_title = profile_row.get(
                    "Position_Title",
                    position_title,
                )
                position_id = str(profile_row.get("Position_ID", "")).strip()
                position_match = self._positions[
                    self._positions["Position_ID"].astype(str).str.strip()
                    == position_id
                ]
                if not position_match.empty:
                    position_criticality = _json_value(
                        position_match.iloc[0].get("Position_Criticality")
                    )

            recommendations.append({
                "rank": _json_value(candidate.get("rank")),
                "employee_id": candidate_id,
                "employee_name": _json_value(candidate.get("employee_name")),
                "current_position": _json_value(position_title),
                "position_criticality": position_criticality,
                "final_score": _json_value(candidate.get("final_score")),
                "qualification_status": _json_value(
                    candidate.get("qualification_status")
                ),
                "readiness": _json_value(candidate.get("readiness")),
                "reasons": [
                    str(reason)
                    for reason in candidate.get("reasons", [])
                ],
                "profile_endpoint": self._profile_url(candidate_id),
            })

        return status, recommendations, result.get("disclaimer")

    def get_employee_detail(self, employee_id: str) -> dict[str, Any]:
        self._ensure_fresh()
        row = self._find_risk_row(employee_id)

        if not bool(row.get("at_risk")):
            raise ValueError(
                f"Employee {_clean_employee_id(employee_id)} is not currently "
                "classified as At Risk at the configured threshold."
            )

        normalized_id = _clean_employee_id(employee_id)
        replacement_status, replacements, disclaimer = (
            self._recommended_replacements(normalized_id)
        )

        employee = self._list_item(row)
        employee.pop("detail_endpoint", None)
        employee["profile_endpoint"] = self._profile_url(normalized_id)

        return {
            "status": "success",
            "employee": employee,
            "attrition": {
                "prediction_window": "next_6_months",
                "status": "At Risk",
                "risk_score_percent": float(
                    row.get("risk_score_percent", 0.0)
                ),
                "factors": self._factor_objects(row),
            },
            "replacement_status": replacement_status,
            "recommended_replacements": replacements,
            "decision_support_disclaimer": disclaimer,
        }

    def get_employee_profile(self, employee_id: str) -> dict[str, Any]:
        self._ensure_fresh()
        normalized_id = _clean_employee_id(employee_id)
        matches = self._profiles[
            self._profiles["Employee_ID"] == normalized_id
        ]

        if matches.empty:
            raise KeyError(normalized_id)

        profile_row = matches.iloc[0]
        profile = {
            str(column): _json_value(profile_row.get(column))
            for column in self._profiles.columns
        }

        position_id = str(profile_row.get("Position_ID", "")).strip()
        position_match = self._positions[
            self._positions["Position_ID"].astype(str).str.strip()
            == position_id
        ]
        position_criticality = (
            _json_value(position_match.iloc[0].get("Position_Criticality"))
            if not position_match.empty
            else None
        )

        risk_matches = self._risk_table[
            self._risk_table["Employee_ID"] == normalized_id
        ]
        attrition_context = None
        if not risk_matches.empty:
            risk_row = risk_matches.iloc[0]
            attrition_context = {
                "status": risk_row.get("attrition_status"),
                "risk_score_percent": float(
                    risk_row.get("risk_score_percent", 0.0)
                ),
                "prediction_window": "next_6_months",
            }

        return {
            "status": "success",
            "employee_profile": profile,
            "position_criticality": position_criticality,
            "attrition_context": attrition_context,
        }
