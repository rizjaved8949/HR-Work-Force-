"""Deterministic one-screen Employee Performance dashboard calculations."""

from __future__ import annotations

from typing import Any

import pandas as pd

from performance.repository import PerformanceRepository


class PerformanceDashboardService:
    """Build fixed dashboard datasets without calling an LLM."""

    def __init__(self, repository: PerformanceRepository) -> None:
        self.repository = repository

    def latest_month(self) -> pd.Timestamp:
        frame = self.repository.get("performance_monthly")
        month = frame["Performance_Month"].dropna().max()
        return pd.Timestamp(month)

    def overview(
        self,
        *,
        month: str | pd.Timestamp | None = None,
        department: str | None = None,
        role_band: str | None = None,
    ) -> dict[str, Any]:
        frame = self._monthly_scope(month=month, department=department, role_band=role_band)
        if frame.empty:
            return {
                "employee_count": 0,
                "average_performance_score": None,
                "strong_or_exceptional_count": 0,
                "strong_or_exceptional_percentage": 0.0,
                "improving_count": 0,
                "declining_count": 0,
            }

        ids = set(frame["Employee_ID"].astype(str))
        summary = self.repository.get("performance_summary")
        summary = summary[summary["Employee_ID"].astype(str).isin(ids)]

        high_count = int(frame["Performance_Band"].isin(["Strong", "Exceptional"]).sum())
        count = int(frame["Employee_ID"].nunique())

        return {
            "employee_count": count,
            "average_performance_score": round(float(frame["Final_Performance_Score"].astype(float).mean()), 2),
            "strong_or_exceptional_count": high_count,
            "strong_or_exceptional_percentage": round(100.0 * high_count / count, 2) if count else 0.0,
            "improving_count": int((summary["Performance_Trend"] == "Improving").sum()),
            "declining_count": int((summary["Performance_Trend"] == "Declining").sum()),
        }

    def organization_trend(
        self,
        *,
        months: int = 12,
        department: str | None = None,
        role_band: str | None = None,
    ) -> list[dict[str, Any]]:
        frame = self.repository.get("performance_monthly")
        if department:
            frame = frame[frame["Department"].astype(str).str.casefold() == department.casefold()]
        if role_band:
            frame = frame[frame["Role_Band"].astype(str).str.casefold() == role_band.casefold()]
        if frame.empty:
            return []

        grouped = (
            frame.groupby("Performance_Month", as_index=False)
            .agg(
                employee_count=("Employee_ID", "nunique"),
                average_performance_score=("Final_Performance_Score", "mean"),
                average_evidence_quality=("Average_Evidence_Quality", "mean"),
            )
            .sort_values("Performance_Month")
            .tail(months)
        )
        grouped["average_performance_score"] = grouped["average_performance_score"].round(2)
        grouped["average_evidence_quality"] = grouped["average_evidence_quality"].round(4)
        return self._records(grouped)

    def department_ranking(
        self,
        *,
        month: str | pd.Timestamp | None = None,
        limit: int = 16,
    ) -> list[dict[str, Any]]:
        frame = self.repository.get("department_monthly")
        target_month = self._resolve_month(frame, month)
        rows = frame[frame["Performance_Month"] == target_month].copy()
        rows = rows.sort_values("Average_Performance_Score", ascending=False).head(limit)
        columns = [
            "Department_ID",
            "Department",
            "Business_Unit",
            "Employee_Count",
            "Average_Performance_Score",
            "Median_Performance_Score",
            "Exceptional_Count",
            "Strong_Count",
            "Meets_Expectations_Count",
            "Partially_Meets_Count",
            "Improvement_Required_Count",
            "Critical_KPI_Breach_Count",
            "Average_Evidence_Quality",
            "Performance_Month",
        ]
        return self._records(rows[columns])

    def distribution(
        self,
        *,
        month: str | pd.Timestamp | None = None,
        department: str | None = None,
        role_band: str | None = None,
    ) -> list[dict[str, Any]]:
        frame = self._monthly_scope(month=month, department=department, role_band=role_band)
        order = [
            "Exceptional",
            "Strong",
            "Meets Expectations",
            "Partially Meets Expectations",
            "Improvement Required",
        ]
        counts = frame["Performance_Band"].value_counts().to_dict()
        total = max(1, len(frame))
        return [
            {
                "performance_band": band,
                "employee_count": int(counts.get(band, 0)),
                "percentage": round(100.0 * int(counts.get(band, 0)) / total, 2),
            }
            for band in order
        ]

    def attention(
        self,
        *,
        department: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        frame = self.repository.get("performance_summary")
        if department:
            frame = frame[frame["Department"].astype(str).str.casefold() == department.casefold()]

        frame = frame.copy()
        frame["attention_priority"] = 0
        frame.loc[frame["Performance_Trend"] == "Declining", "attention_priority"] += 100
        frame.loc[frame["Latest_Performance_Score"].astype(float) < 70, "attention_priority"] += 50
        frame["attention_priority"] += (-frame["Three_Month_Change_Points"].astype(float)).clip(lower=0)

        rows = frame[
            (frame["Performance_Trend"] == "Declining")
            | (frame["Latest_Performance_Score"].astype(float) < 70)
        ].copy()
        rows = rows.sort_values(
            ["attention_priority", "Latest_Performance_Score"],
            ascending=[False, True],
        ).head(limit)

        columns = [
            "Employee_ID",
            "Employee_Name",
            "Department",
            "Position_Title",
            "Role_Band",
            "Latest_Performance_Score",
            "Latest_Performance_Band",
            "Three_Month_Change_Points",
            "Performance_Trend",
            "Development_KPI_1",
            "Development_KPI_1_Score",
            "Development_KPI_2",
            "Development_KPI_2_Score",
        ]
        return self._records(rows[columns])

    def _monthly_scope(
        self,
        *,
        month: str | pd.Timestamp | None,
        department: str | None,
        role_band: str | None,
    ) -> pd.DataFrame:
        frame = self.repository.get("performance_monthly")
        target_month = self._resolve_month(frame, month)
        rows = frame[frame["Performance_Month"] == target_month].copy()
        if department:
            rows = rows[rows["Department"].astype(str).str.casefold() == department.casefold()]
        if role_band:
            rows = rows[rows["Role_Band"].astype(str).str.casefold() == role_band.casefold()]
        return rows

    @staticmethod
    def _resolve_month(frame: pd.DataFrame, month: str | pd.Timestamp | None) -> pd.Timestamp:
        if month is None:
            return pd.Timestamp(frame["Performance_Month"].dropna().max())
        requested = pd.Timestamp(month)
        return requested.to_period("M").to_timestamp()

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        clean = frame.copy()
        for column in clean.select_dtypes(include=["datetime64[ns]"]).columns:
            clean[column] = clean[column].dt.strftime("%Y-%m-%d")
        clean = clean.where(pd.notna(clean), None)

        records: list[dict[str, Any]] = []
        for row in clean.to_dict(orient="records"):
            converted: dict[str, Any] = {}
            for key, value in row.items():
                key_str = str(key)
                if hasattr(value, "item"):
                    converted[key_str] = value.item()
                else:
                    converted[key_str] = value
            records.append(converted)
        return records
