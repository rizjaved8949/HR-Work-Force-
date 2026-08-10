"""Read-only data repository for the Scenario Simulation layer."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from .errors import (
    SimulationDataError,
    SimulationEmployeeNotFoundError,
    SimulationPositionNotFoundError,
)


class SimulationRepository:
    """Loads existing HR truth plus isolated simulation data.

    Existing Data/*.csv files remain the source of truth. Simulation-only
    assumptions and derived employee features live under Data/Simulation/.
    The repository never writes to the existing HR datasets.
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
            self._frames[key] = self._read_csv(self.simulation_dir / filename, key)

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

    def _one(self, frame_key: str, column: str, value: str) -> dict | None:
        frame = self.get(frame_key)
        match = frame[frame[column].astype(str) == str(value)]
        return None if match.empty else match.iloc[0].to_dict()

    def resolve_employee(self, employee_id: str) -> dict:
        employee_id = str(employee_id).strip()
        result = self._one("employee_profile", "Employee_ID", employee_id)
        if result is None:
            raise SimulationEmployeeNotFoundError(
                f"Employee_ID {employee_id!r} was not found in Employee_Profile.csv."
            )
        return result

    def resolve_position(self, position_id: str) -> dict:
        position_id = str(position_id).strip()
        result = self._one("position_master", "Position_ID", position_id)
        if result is None:
            raise SimulationPositionNotFoundError(
                f"Position_ID {position_id!r} was not found in Position_Master.csv."
            )
        return result

    def resolve_department(self, department_id: str) -> dict:
        department_id = str(department_id).strip()
        result = self._one("headcount_summary", "Department_ID", department_id)
        if result is None:
            raise SimulationDataError(
                f"Department_ID {department_id!r} was not found in Current_Headcount_Summary.csv."
            )
        return result

    def employee_skills(self, employee_id: str) -> pd.DataFrame:
        frame = self.get("employee_skills")
        return frame[frame["Employee_ID"].astype(str) == str(employee_id)].copy()

    def position_skill_requirements(self, position_id: str) -> pd.DataFrame:
        frame = self.get("position_skills")
        return frame[frame["Position_ID"].astype(str) == str(position_id)].copy()

    def positions_for_department(self, department_id: str) -> pd.DataFrame:
        frame = self.get("position_master")
        return frame[frame["Department_ID"].astype(str) == str(department_id)].copy()

    def position_budget(self, position_id: str) -> dict | None:
        return self._one("position_budget", "Position_ID", position_id)

    def position_business(self, position_id: str) -> dict | None:
        return self._one("position_business", "Position_ID", position_id)

    def department_business(self, department_id: str) -> dict | None:
        return self._one("department_business", "Department_ID", department_id)

    def department_headcount(self, department_id: str) -> dict | None:
        return self._one("headcount_summary", "Department_ID", department_id)

    def latest_department_budget(self, department_id: str) -> dict | None:
        frame = self.get("department_budget")
        match = frame[frame["Department_ID"].astype(str) == str(department_id)].copy()
        if match.empty:
            return None
        match["_sort"] = pd.to_datetime(match["Budget_Month"], errors="coerce")
        return match.sort_values("_sort").iloc[-1].drop(labels=["_sort"]).to_dict()

    def latest_demand_driver(self, department_id: str) -> dict | None:
        frame = self.get("demand_drivers")
        match = frame[frame["Department_ID"].astype(str) == str(department_id)].copy()
        if match.empty:
            return None
        match["_sort"] = pd.to_datetime(match["Snapshot_Month"], errors="coerce")
        return match.sort_values("_sort").iloc[-1].drop(labels=["_sort"]).to_dict()

    def resolve_course(self, course_id: str) -> dict:
        result = self._one("learning_business", "Course_ID", str(course_id).strip())
        if result is None:
            raise SimulationDataError(
                f"Course_ID {course_id!r} was not found in Simulation_Learning_Business_Evaluation.csv."
            )
        return result

    def employee_context(self, employee_id: str) -> dict:
        employee = self.resolve_employee(employee_id)
        position_id = employee["Position_ID"]
        department_id = employee["Department_ID"]
        return {
            "employee": employee,
            "simulation_features": self._one("employee_features", "Employee_ID", employee_id),
            "performance": self._one("performance_summary", "Employee_ID", employee_id),
            "attendance": self._one("attendance", "Employee_ID", employee_id),
            "experience": self._one("experience", "Employee_ID", employee_id),
            "learning": self._one("learning_summary", "Employee_ID", employee_id),
            "position": self._one("position_master", "Position_ID", position_id),
            "position_business": self.position_business(position_id),
            "position_budget": self.position_budget(position_id),
            "headcount": self.department_headcount(department_id),
            "department_business": self.department_business(department_id),
            "department_budget": self.latest_department_budget(department_id),
            "demand_driver": self.latest_demand_driver(department_id),
        }

    def department_context(self, department_id: str) -> dict:
        headcount = self.resolve_department(department_id)
        return {
            "headcount": headcount,
            "department_business": self.department_business(department_id),
            "department_budget": self.latest_department_budget(department_id),
            "demand_driver": self.latest_demand_driver(department_id),
            "positions": self.positions_for_department(department_id),
        }
