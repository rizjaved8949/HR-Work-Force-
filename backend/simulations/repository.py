"""Read-only data repository for the Scenario Simulation layer."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from .errors import SimulationDataError, SimulationEmployeeNotFoundError


class SimulationRepository:
    """Loads existing HR truth plus isolated simulation data.

    Existing Data/*.csv files remain the source of truth.  Simulation-only
    assumptions and derived employee features live under Data/Simulation/.
    """

    EXISTING_FILES = {
        "employee_profile": "Employee_Profile.csv",
        "performance_summary": "Employee_Performance_Summary.csv",
        "attendance": "Employee_Attendance.csv",
        "experience": "Employee_Experience.csv",
        "learning_summary": "Employee_Learning_Profile_Summary.csv",
        "employee_skills": "Employee_Skills.csv",
        "position_skills": "Position_Skill_Requirements.csv",
        "position_master": "Position_Master.csv",
        "department_budget": "Department_Budget.csv",
        "headcount_summary": "Current_Headcount_Summary.csv",
        "demand_drivers": "Workforce_Demand_Drivers.csv",
        "position_budget": "Position_Budget.csv",
    }

    SIMULATION_FILES = {
        "employee_features": "Simulation_Employee_Features.csv",
        "department_business": "Simulation_Department_Business_Evaluation.csv",
        "position_business": "Simulation_Position_Business_Evaluation.csv",
        "learning_business": "Simulation_Learning_Business_Evaluation.csv",
        "scenario_catalog": "Simulation_Scenario_Catalog.csv",
    }

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.simulation_dir = self.data_dir / "Simulation"
        self._frames: Dict[str, pd.DataFrame] = {}
        self._load_all()
        self.validate()

    def _read_csv(self, path: Path, label: str) -> pd.DataFrame:
        if not path.is_file():
            raise SimulationDataError(f"Required {label} file is missing: {path}")
        return pd.read_csv(path)

    def _load_all(self) -> None:
        for key, filename in self.EXISTING_FILES.items():
            self._frames[key] = self._read_csv(self.data_dir / filename, key)

        for key, filename in self.SIMULATION_FILES.items():
            self._frames[key] = self._read_csv(
                self.simulation_dir / filename,
                key,
            )

    def get(self, key: str) -> pd.DataFrame:
        try:
            return self._frames[key]
        except KeyError as error:
            raise KeyError(f"Unknown simulation dataset key: {key}") from error

    def validate(self) -> dict:
        profile = self.get("employee_profile")
        features = self.get("employee_features")
        catalog = self.get("scenario_catalog")

        if profile["Employee_ID"].duplicated().any():
            raise SimulationDataError("Employee_Profile.csv has duplicate Employee_ID values.")
        if features["Employee_ID"].duplicated().any():
            raise SimulationDataError("Simulation_Employee_Features.csv has duplicate Employee_ID values.")

        master_ids = set(profile["Employee_ID"].astype(str))
        feature_ids = set(features["Employee_ID"].astype(str))
        if master_ids != feature_ids:
            missing = sorted(master_ids - feature_ids)[:10]
            extra = sorted(feature_ids - master_ids)[:10]
            raise SimulationDataError(
                "Simulation employee feature IDs must exactly match the current Employee_Profile IDs. "
                f"Missing={missing}, extra={extra}"
            )

        expected_scenarios = {
            "employee_promotion",
            "employee_transfer",
            "headcount_reduction",
            "workforce_expansion",
            "budget_change",
            "skill_reskilling",
            "business_demand_change",
        }
        actual_scenarios = set(catalog["Scenario_Code"].astype(str))
        if actual_scenarios != expected_scenarios:
            raise SimulationDataError(
                "Scenario catalog must contain exactly the locked seven scenarios. "
                f"Found: {sorted(actual_scenarios)}"
            )

        return {
            "employee_count": len(profile),
            "employee_feature_count": len(features),
            "employee_ids_exact_match": True,
            "department_count": self.get("headcount_summary")["Department_ID"].nunique(),
            "position_count": self.get("position_master")["Position_ID"].nunique(),
            "scenario_count": len(catalog),
        }

    def resolve_employee(self, employee_id: str) -> dict:
        employee_id = str(employee_id).strip()
        profile = self.get("employee_profile")
        match = profile[profile["Employee_ID"].astype(str) == employee_id]
        if match.empty:
            raise SimulationEmployeeNotFoundError(
                f"Employee_ID {employee_id!r} was not found in Employee_Profile.csv."
            )
        return match.iloc[0].to_dict()

    def employee_context(self, employee_id: str) -> dict:
        employee = self.resolve_employee(employee_id)
        position_id = employee["Position_ID"]
        department_id = employee["Department_ID"]

        def one(frame_key: str, column: str, value: str) -> dict | None:
            frame = self.get(frame_key)
            match = frame[frame[column].astype(str) == str(value)]
            return None if match.empty else match.iloc[0].to_dict()

        return {
            "employee": employee,
            "simulation_features": one(
                "employee_features", "Employee_ID", employee_id
            ),
            "performance": one(
                "performance_summary", "Employee_ID", employee_id
            ),
            "attendance": one("attendance", "Employee_ID", employee_id),
            "experience": one("experience", "Employee_ID", employee_id),
            "learning": one("learning_summary", "Employee_ID", employee_id),
            "position": one("position_master", "Position_ID", position_id),
            "position_business": one(
                "position_business", "Position_ID", position_id
            ),
            "headcount": one(
                "headcount_summary", "Department_ID", department_id
            ),
            "department_business": one(
                "department_business", "Department_ID", department_id
            ),
        }
