from __future__ import annotations

from pathlib import Path

import pandas as pd

from successor_service.exceptions import RecordNotFoundError
from successor_service.utils.serialization import clean_record


REQUIRED_FILES = {
    "employee_profile": "Employee_Profile.csv",
    "employee_experience": "Employee_Experience.csv",
    "employee_performance": "Employee_Performance.csv",
    "employee_attendance": "Employee_Attendance.csv",
    "employee_skills": "Employee_Skills.csv",
    "position_master": "Position_Master.csv",
    "position_requirements": "Position_Requirements.csv",
    "position_skill_requirements": "Position_Skill_Requirements.csv",
    "skill_catalog": "Skill_Catalog.csv",
}


class CSVDataStore:
    """Loads the prototype CSV tables once and exposes safe query helpers."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.tables: dict[str, pd.DataFrame] = {}
        self._load()

    def _load(self) -> None:
        missing = [
            filename
            for filename in REQUIRED_FILES.values()
            if not (self.data_dir / filename).exists()
        ]
        if missing:
            raise FileNotFoundError(
                "Missing required data files: " + ", ".join(missing)
            )

        for table_name, filename in REQUIRED_FILES.items():
            frame = pd.read_csv(self.data_dir / filename)
            for column in ("Employee_ID", "Position_ID", "Skill_ID"):
                if column in frame.columns:
                    frame[column] = frame[column].astype(str).str.strip()
            self.tables[table_name] = frame

    def table(self, name: str) -> pd.DataFrame:
        return self.tables[name]

    def one(
        self,
        table_name: str,
        column: str,
        value: str,
        label: str,
    ) -> dict:
        frame = self.tables[table_name]
        rows = frame[frame[column].astype(str) == str(value)]
        if rows.empty:
            raise RecordNotFoundError(f"{label} not found: {value}")
        return clean_record(rows.iloc[0].to_dict())

    def many(self, table_name: str, column: str, value: str) -> list[dict]:
        frame = self.tables[table_name]
        rows = frame[frame[column].astype(str) == str(value)]
        return [clean_record(item) for item in rows.to_dict("records")]
