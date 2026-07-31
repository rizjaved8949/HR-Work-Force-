from __future__ import annotations

from successor_service.repositories.csv_store import CSVDataStore


class EmployeeEvidenceTool:
    name = "employee_evidence_tool"

    def __init__(self, store: CSVDataStore) -> None:
        self.store = store

    def run(self, employee_id: str) -> dict:
        return {
            "experience": self.store.one(
                "employee_experience",
                "Employee_ID",
                employee_id,
                "Employee experience",
            ),
            "performance": self.store.one(
                "employee_performance",
                "Employee_ID",
                employee_id,
                "Employee performance",
            ),
            "attendance": self.store.one(
                "employee_attendance",
                "Employee_ID",
                employee_id,
                "Employee attendance",
            ),
            "skills": self.store.many(
                "employee_skills",
                "Employee_ID",
                employee_id,
            ),
        }
