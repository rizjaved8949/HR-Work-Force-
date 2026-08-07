"""Learning and development support for Employee Performance."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from typing import Any

import pandas as pd

from performance.repository import PerformanceRepository


class PerformanceLearningService:
    """Read course history and data-driven development recommendations."""

    def __init__(self, repository: PerformanceRepository) -> None:
        self.repository = repository

    @property
    def available(self) -> bool:
        return self.repository.has_dataset("development_recommendations")

    def employee_learning_history(self, employee_id: str) -> list[dict[str, Any]]:
        frame = self.repository.get("learning_history", required=False)
        if frame.empty:
            return []
        rows = frame[frame["Employee_ID"].astype(str).str.upper() == employee_id.upper()].copy()
        if "Completion_Date" in rows.columns:
            rows = rows.sort_values("Completion_Date", ascending=False)
        return self._records(rows)

    def employee_recommendations(self, employee_id: str) -> list[dict[str, Any]]:
        frame = self.repository.get("development_recommendations", required=False)
        if frame.empty:
            return []
        rows = frame[frame["Employee_ID"].astype(str).str.upper() == employee_id.upper()].copy()
        sort_columns = [c for c in ["Recommendation_Rank", "Priority_Score"] if c in rows.columns]
        if sort_columns:
            ascending = [True if c == "Recommendation_Rank" else False for c in sort_columns]
            rows = rows.sort_values(sort_columns, ascending=ascending)
        return self._records(rows)

    def employee_learning_summary(self, employee_id: str) -> dict[str, Any] | None:
        frame = self.repository.get("learning_profile_summary", required=False)
        if frame.empty:
            return None
        rows = frame[frame["Employee_ID"].astype(str).str.upper() == employee_id.upper()]
        if rows.empty:
            return None
        return self._clean_record(rows.iloc[0].to_dict())

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            PerformanceLearningService._clean_record(row)
            for row in frame.to_dict(orient="records")
        ]

    @staticmethod
    def _clean_record(row: Mapping[Hashable, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in row.items():
            key_str = str(key)
            if pd.isna(value):
                clean[key_str] = None
            elif isinstance(value, pd.Timestamp):
                clean[key_str] = value.date().isoformat()
            elif hasattr(value, "item"):
                clean[key_str] = value.item()
            else:
                clean[key_str] = value
        return clean
