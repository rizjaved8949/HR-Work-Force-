from __future__ import annotations

from successor_service.repositories.csv_store import CSVDataStore


class PositionContextTool:
    name = "position_context_tool"

    def __init__(self, store: CSVDataStore) -> None:
        self.store = store

    def run(self, position_id: str) -> dict:
        return {
            "position": self.store.one(
                "position_master",
                "Position_ID",
                position_id,
                "Position",
            ),
            "requirements": self.store.one(
                "position_requirements",
                "Position_ID",
                position_id,
                "Position requirements",
            ),
            "required_skills": self.store.many(
                "position_skill_requirements",
                "Position_ID",
                position_id,
            ),
        }
