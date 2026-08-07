"""Read-only CSV repository for Employee Performance analytics."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Final

import pandas as pd


class PerformanceRepositoryError(RuntimeError):
    """Raised when required Performance data is missing or invalid."""


class PerformanceRepository:
    """Load Performance datasets from the existing shared Data directory.

    The repository never writes to any source CSV. Frames are cached internally
    and copies are returned to callers to protect the shared cache.
    """

    REQUIRED_FILES: Final[dict[str, str]] = {
        "profile": "Employee_Profile.csv",
        "role_mapping": "Performance_Role_Mapping.csv",
        "kpi_catalog": "KPI_Catalog.csv",
        "role_template": "Role_KPI_Template.csv",
        "kpi_assignment": "Employee_KPI_Assignment.csv",
        "evidence_monthly": "Employee_Performance_Evidence_Monthly.csv",
        "performance_monthly": "Employee_Performance_Monthly.csv",
        "performance_summary": "Employee_Performance_Summary.csv",
        "department_monthly": "Department_Performance_Monthly.csv",
        "employee_skills": "Employee_Skills.csv",
        "skill_catalog": "Skill_Catalog.csv",
        "position_skill_requirements": "Position_Skill_Requirements.csv",
    }

    OPTIONAL_FILES: Final[dict[str, str]] = {
        "course_catalog": "Learning_Course_Catalog.csv",
        "kpi_skill_map": "KPI_Skill_Development_Map.csv",
        "skill_course_map": "Skill_Course_Mapping.csv",
        "learning_history": "Employee_Learning_History.csv",
        "development_recommendations": "Employee_Development_Recommendation.csv",
        "learning_profile_summary": "Employee_Learning_Profile_Summary.csv",
        "learning_quality_report": "Learning_Data_Quality_Report.csv",
    }

    DATE_COLUMNS: Final[set[str]] = {
        "Performance_Month",
        "Latest_Performance_Month",
        "Data_As_Of_Date",
        "Effective_Start_Date",
        "Effective_End_Date",
        "Completion_Date",
    }

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        if not self.data_dir.is_dir():
            raise PerformanceRepositoryError(
                f"Performance data directory was not found: {self.data_dir}"
            )
        self._cache: dict[str, pd.DataFrame] = {}
        self._validate_required_files()

    def _validate_required_files(self) -> None:
        missing = [
            filename
            for filename in self.REQUIRED_FILES.values()
            if not (self.data_dir / filename).is_file()
        ]
        if missing:
            raise PerformanceRepositoryError(
                "Missing required Performance data files: " + ", ".join(missing)
            )

    def has_dataset(self, key: str) -> bool:
        filename = self.REQUIRED_FILES.get(key) or self.OPTIONAL_FILES.get(key)
        if filename is None:
            return False
        return (self.data_dir / filename).is_file()

    def _filename_for(self, key: str) -> str:
        filename = self.REQUIRED_FILES.get(key) or self.OPTIONAL_FILES.get(key)
        if filename is None:
            raise KeyError(f"Unknown Performance dataset key: {key!r}")
        return filename

    def get(self, key: str, *, required: bool = True) -> pd.DataFrame:
        """Return a copy of one cached dataset."""

        if key in self._cache:
            return self._cache[key].copy()

        filename = self._filename_for(key)
        path = self.data_dir / filename
        if not path.is_file():
            if required:
                raise PerformanceRepositoryError(
                    f"Performance dataset is not available: {filename}"
                )
            return pd.DataFrame()

        frame = pd.read_csv(path)
        if frame.empty:
            raise PerformanceRepositoryError(
                f"Performance dataset is empty: {filename}"
            )

        for column in set(frame.columns) & self.DATE_COLUMNS:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")

        self._cache[key] = frame
        return frame.copy()

    def refresh(self) -> None:
        """Clear cached DataFrames so subsequent reads use current CSVs."""

        self._cache.clear()

    @staticmethod
    def _string_keyed_record(
        row: Mapping[Hashable, object],
    ) -> dict[str, object]:
        """Convert pandas record keys to strings for stable API typing."""

        return {str(key): value for key, value in row.items()}

    def data_as_of_date(self) -> str | None:
        summary = self.get("performance_summary")
        if "Data_As_Of_Date" not in summary.columns:
            return None
        dates = summary["Data_As_Of_Date"].dropna()
        if dates.empty:
            return None
        latest = pd.Timestamp(dates.max())
        return latest.date().isoformat()

    def resolve_employee(
        self,
        *,
        employee_id: str | None = None,
        employee_name: str | None = None,
    ) -> dict[str, object] | None:
        """Resolve one employee by ID or an unambiguous name match."""

        summary = self.get("performance_summary")

        if employee_id:
            target = employee_id.strip().upper()
            match = summary[
                summary["Employee_ID"].astype(str).str.upper() == target
            ]
            if match.empty:
                return None
            return self._string_keyed_record(match.iloc[0].to_dict())

        if employee_name:
            target = employee_name.strip().casefold()
            names = summary["Employee_Name"].astype(str)
            exact = summary[names.str.casefold() == target]
            if len(exact) == 1:
                return self._string_keyed_record(exact.iloc[0].to_dict())
            contains = summary[names.str.casefold().str.contains(target, regex=False)]
            if len(contains) == 1:
                return self._string_keyed_record(contains.iloc[0].to_dict())
            if len(contains) > 1:
                raise PerformanceRepositoryError(
                    f"Employee name is ambiguous: {employee_name!r}."
                )
        return None
