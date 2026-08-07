"""Deterministic Employee Performance analysis service."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from performance.dashboard_service import PerformanceDashboardService
from performance.learning_service import PerformanceLearningService
from performance.repository import PerformanceRepository, PerformanceRepositoryError
from performance.schemas import (
    AnalyzePerformanceInput,
    MetricValue,
    PerformanceAnalysisType,
    PerformanceResultStatus,
    PerformanceToolResult,
)
from performance.scoring import calculate_monthly_score


class PerformanceService:
    """Main read-only Performance application service.

    Stored results remain the reporting source of truth. `recalculate_employee_month`
    is a validation/calculation operation only and does not overwrite CSV files.
    """

    EMPLOYEE_ID_PATTERN = re.compile(r"\bEMP\d{3,}\b", re.IGNORECASE)

    def __init__(self, repository: PerformanceRepository) -> None:
        self.repository = repository
        self.dashboard = PerformanceDashboardService(repository)
        self.learning = PerformanceLearningService(repository)

    def analyze(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        """Route a natural-language question to deterministic Performance logic."""

        analysis_type = request.analysis_type or self._infer_analysis_type(request.question)
        employee_id = request.employee_id or self._extract_employee_id(request.question)

        try:
            if analysis_type == PerformanceAnalysisType.OVERVIEW:
                return self._overview_result(request)
            if analysis_type == PerformanceAnalysisType.DEPARTMENT_RANKING:
                return self._department_ranking_result(request)
            if analysis_type == PerformanceAnalysisType.DISTRIBUTION:
                return self._distribution_result(request)
            if analysis_type == PerformanceAnalysisType.ATTENTION:
                return self._attention_result(request)

            if analysis_type in {
                PerformanceAnalysisType.EMPLOYEE,
                PerformanceAnalysisType.EMPLOYEE_TREND,
                PerformanceAnalysisType.KPI_BREAKDOWN,
                PerformanceAnalysisType.LEARNING,
                PerformanceAnalysisType.RECOMMENDATIONS,
                PerformanceAnalysisType.RECALCULATE,
            }:
                employee = self._resolve_employee(
                    employee_id=employee_id,
                    employee_name=request.employee_name,
                )
                if employee is None:
                    return PerformanceToolResult(
                        status=PerformanceResultStatus.NOT_FOUND,
                        analysis_type=analysis_type,
                        question=request.question,
                        message="The requested employee was not found in Performance data.",
                        data_as_of_date=self.repository.data_as_of_date(),
                    )
                resolved_id = str(employee["Employee_ID"])

                if analysis_type == PerformanceAnalysisType.EMPLOYEE_TREND:
                    records = self.employee_trend(resolved_id, months=request.months)
                    return self._records_result(request, analysis_type, records, "Employee performance trend calculated.", employee)

                if analysis_type == PerformanceAnalysisType.KPI_BREAKDOWN:
                    records = self.employee_kpi_breakdown(resolved_id, month=request.month)
                    return self._records_result(request, analysis_type, records, "Employee KPI breakdown calculated.", employee)

                if analysis_type == PerformanceAnalysisType.LEARNING:
                    history = self.learning.employee_learning_history(resolved_id)
                    limitations = [] if self.repository.has_dataset("learning_history") else [
                        "Learning history is not available in the shared Data folder."
                    ]
                    return PerformanceToolResult(
                        status=PerformanceResultStatus.SUCCESS if history else PerformanceResultStatus.PARTIAL,
                        analysis_type=analysis_type,
                        question=request.question,
                        message="Employee learning history retrieved." if history else "No learning-history records are available for this employee.",
                        employee=self._clean_record(employee),
                        learning_history=history,
                        data_as_of_date=self.repository.data_as_of_date(),
                        limitations=limitations,
                    )

                if analysis_type == PerformanceAnalysisType.RECOMMENDATIONS:
                    recommendations = self.learning.employee_recommendations(resolved_id)
                    limitations = [] if self.repository.has_dataset("development_recommendations") else [
                        "Development recommendation data is not available in the shared Data folder."
                    ]
                    return PerformanceToolResult(
                        status=PerformanceResultStatus.SUCCESS if recommendations else PerformanceResultStatus.PARTIAL,
                        analysis_type=analysis_type,
                        question=request.question,
                        message="Employee development recommendations retrieved." if recommendations else "No immediate course recommendation is available for this employee.",
                        employee=self._clean_record(employee),
                        recommendations=recommendations,
                        data_as_of_date=self.repository.data_as_of_date(),
                        limitations=limitations,
                    )

                if analysis_type == PerformanceAnalysisType.RECALCULATE:
                    result = self.recalculate_employee_month(resolved_id, month=request.month)
                    return PerformanceToolResult(
                        status=PerformanceResultStatus.SUCCESS,
                        analysis_type=analysis_type,
                        question=request.question,
                        message="Employee-month score recalculated from KPI evidence without modifying source files.",
                        employee=self._clean_record(employee),
                        records=[result],
                        data_as_of_date=self.repository.data_as_of_date(),
                        calculation_notes=["This calculation is read-only and does not overwrite stored Performance CSV files."],
                    )

                return self.employee_evaluation_result(request, employee)

            return PerformanceToolResult(
                status=PerformanceResultStatus.UNSUPPORTED,
                analysis_type=analysis_type,
                question=request.question,
                message="This Performance analysis type is not supported.",
                data_as_of_date=self.repository.data_as_of_date(),
            )
        except PerformanceRepositoryError as exc:
            return PerformanceToolResult(
                status=PerformanceResultStatus.ERROR,
                analysis_type=analysis_type,
                question=request.question,
                message=str(exc),
                data_as_of_date=self.repository.data_as_of_date(),
            )

    def employee_evaluation_result(
        self,
        request: AnalyzePerformanceInput,
        employee: dict[str, Any],
    ) -> PerformanceToolResult:
        employee_id = str(employee["Employee_ID"])
        trend = self.employee_trend(employee_id, months=request.months)
        kpis = self.employee_kpi_breakdown(employee_id, month=request.month)
        recommendations = (
            self.learning.employee_recommendations(employee_id)
            if request.include_learning
            else []
        )
        history = (
            self.learning.employee_learning_history(employee_id)
            if request.include_learning
            else []
        )

        metrics = [
            MetricValue(metric_name="latest_performance_score", display_name="Latest Performance Score", value=float(employee["Latest_Performance_Score"]), unit="score / 100"),
            MetricValue(metric_name="average_12m_performance_score", display_name="12-Month Average", value=float(employee["Average_12M_Performance_Score"]), unit="score / 100"),
            MetricValue(metric_name="three_month_change_points", display_name="Three-Month Change", value=float(employee["Three_Month_Change_Points"]), unit="points"),
            MetricValue(metric_name="performance_trend", display_name="Performance Trend", value=str(employee["Performance_Trend"])),
        ]

        limitations: list[str] = []
        if request.include_learning and not self.repository.has_dataset("development_recommendations"):
            limitations.append(
                "Learning recommendation files have not yet been copied into the shared Data folder."
            )

        return PerformanceToolResult(
            status=PerformanceResultStatus.SUCCESS,
            analysis_type=PerformanceAnalysisType.EMPLOYEE,
            question=request.question,
            message="Employee performance evaluation retrieved successfully.",
            metrics=metrics,
            employee=self._clean_record(employee),
            records=[
                {"section": "monthly_trend", "data": trend},
                {"section": "kpi_breakdown", "data": kpis},
            ],
            recommendations=recommendations,
            learning_history=history,
            data_as_of_date=self.repository.data_as_of_date(),
            calculation_notes=[
                "Official scores are deterministic weighted KPI calculations.",
                "The LLM should explain these values but must not create or alter them.",
            ],
            limitations=limitations,
        )

    def employee_trend(self, employee_id: str, *, months: int = 12) -> list[dict[str, Any]]:
        frame = self.repository.get("performance_monthly")
        rows = frame[frame["Employee_ID"].astype(str).str.upper() == employee_id.upper()].copy()
        rows = rows.sort_values("Performance_Month").tail(months)
        columns = [
            "Performance_Month",
            "Final_Performance_Score",
            "Performance_Band",
            "Average_Evidence_Quality",
            "Critical_KPI_Breach_Flag",
        ]
        return self._records(rows[columns])

    def employee_kpi_breakdown(
        self,
        employee_id: str,
        *,
        month: object | None = None,
    ) -> list[dict[str, Any]]:
        frame = self.repository.get("evidence_monthly")
        rows = frame[frame["Employee_ID"].astype(str).str.upper() == employee_id.upper()].copy()
        if rows.empty:
            return []
        target_month = (
            pd.Timestamp(month).to_period("M").to_timestamp()
            if month is not None
            else pd.Timestamp(rows["Performance_Month"].max())
        )
        rows = rows[rows["Performance_Month"] == target_month].copy()
        rows = rows.sort_values("Weighted_Score", ascending=False)
        columns = [
            "KPI_ID",
            "KPI_Name",
            "KPI_Group",
            "Measurement_Scope",
            "Measurement_Unit",
            "Operational_Target_Value",
            "Operational_Actual_Value",
            "Operational_Unit",
            "Actual_KPI_Value",
            "Floor_Value",
            "Target_Value",
            "Stretch_Value",
            "Scoring_Direction",
            "Normalized_KPI_Score",
            "KPI_Weight_pct",
            "Weighted_Score",
            "Evidence_Source_Mode",
            "Production_Replacement_Source",
            "Evidence_Quality_Score",
            "Performance_Month",
        ]
        return self._records(rows[columns])

    def recalculate_employee_month(
        self,
        employee_id: str,
        *,
        month: object | None = None,
    ) -> dict[str, Any]:
        frame = self.repository.get("evidence_monthly")
        rows = frame[frame["Employee_ID"].astype(str).str.upper() == employee_id.upper()].copy()
        if rows.empty:
            raise PerformanceRepositoryError(f"No KPI evidence found for {employee_id}.")
        target_month = (
            pd.Timestamp(month).to_period("M").to_timestamp()
            if month is not None
            else pd.Timestamp(rows["Performance_Month"].max())
        )
        rows = rows[rows["Performance_Month"] == target_month].copy()
        if rows.empty:
            raise PerformanceRepositoryError(
                f"No KPI evidence found for {employee_id} in {target_month.date().isoformat()}."
            )
        calculated = calculate_monthly_score(rows)
        stored = self.repository.get("performance_monthly")
        stored_row = stored[
            (stored["Employee_ID"].astype(str).str.upper() == employee_id.upper())
            & (stored["Performance_Month"] == target_month)
        ]
        stored_score = float(stored_row.iloc[0]["Final_Performance_Score"]) if not stored_row.empty else None
        return {
            "employee_id": employee_id.upper(),
            "performance_month": target_month.date().isoformat(),
            **calculated,
            "stored_final_performance_score": stored_score,
            "difference_from_stored": (
                round(float(calculated["final_performance_score"]) - stored_score, 4)
                if stored_score is not None else None
            ),
        }

    def _overview_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        data = self.dashboard.overview(
            month=request.month,
            department=request.department,
            role_band=request.role_band,
        )
        trend = self.dashboard.organization_trend(
            months=request.months,
            department=request.department,
            role_band=request.role_band,
        )
        metrics = [
            MetricValue(metric_name=k, display_name=k.replace("_", " ").title(), value=v)
            for k, v in data.items()
        ]
        return PerformanceToolResult(
            status=PerformanceResultStatus.SUCCESS,
            analysis_type=PerformanceAnalysisType.OVERVIEW,
            question=request.question,
            message="Performance overview calculated successfully.",
            metrics=metrics,
            records=trend,
            data_as_of_date=self.repository.data_as_of_date(),
        )

    def _department_ranking_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        rows = self.dashboard.department_ranking(month=request.month, limit=request.limit)
        return self._records_result(request, PerformanceAnalysisType.DEPARTMENT_RANKING, rows, "Department performance ranking calculated.")

    def _distribution_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        rows = self.dashboard.distribution(month=request.month, department=request.department, role_band=request.role_band)
        return self._records_result(request, PerformanceAnalysisType.DISTRIBUTION, rows, "Performance-band distribution calculated.")

    def _attention_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        rows = self.dashboard.attention(department=request.department, limit=request.limit)
        return self._records_result(request, PerformanceAnalysisType.ATTENTION, rows, "Employees requiring performance attention identified.")

    def _records_result(
        self,
        request: AnalyzePerformanceInput,
        analysis_type: PerformanceAnalysisType,
        records: list[dict[str, Any]],
        message: str,
        employee: dict[str, Any] | None = None,
    ) -> PerformanceToolResult:
        return PerformanceToolResult(
            status=PerformanceResultStatus.SUCCESS if records else PerformanceResultStatus.NOT_FOUND,
            analysis_type=analysis_type,
            question=request.question,
            message=message if records else "No matching Performance records were found.",
            employee=self._clean_record(employee) if employee else None,
            records=records,
            data_as_of_date=self.repository.data_as_of_date(),
        )

    def _resolve_employee(
        self,
        *,
        employee_id: str | None,
        employee_name: str | None,
    ) -> dict[str, Any] | None:
        return self.repository.resolve_employee(
            employee_id=employee_id,
            employee_name=employee_name,
        )

    @classmethod
    def _extract_employee_id(cls, question: str) -> str | None:
        match = cls.EMPLOYEE_ID_PATTERN.search(question or "")
        return match.group(0).upper() if match else None

    @staticmethod
    def _infer_analysis_type(question: str) -> PerformanceAnalysisType:
        text = (question or "").casefold()
        if any(term in text for term in ["course", "training", "recommend", "development plan"]):
            return PerformanceAnalysisType.RECOMMENDATIONS
        if any(term in text for term in ["learning history", "completed course", "completed training"]):
            return PerformanceAnalysisType.LEARNING
        if "recalculate" in text or "calculate again" in text:
            return PerformanceAnalysisType.RECALCULATE
        if any(term in text for term in ["kpi breakdown", "kpi detail", "why is", "drivers", "development area"]):
            return PerformanceAnalysisType.KPI_BREAKDOWN
        if "trend" in text and re.search(r"\bemp\d{3,}\b", text):
            return PerformanceAnalysisType.EMPLOYEE_TREND
        if any(term in text for term in ["declining", "requiring attention", "needs attention", "low performer"]):
            return PerformanceAnalysisType.ATTENTION
        if any(term in text for term in ["distribution", "performance band", "exceptional", "strong employees"]):
            return PerformanceAnalysisType.DISTRIBUTION
        if any(term in text for term in ["department ranking", "department performance", "best department", "worst department"]):
            return PerformanceAnalysisType.DEPARTMENT_RANKING
        if re.search(r"\bemp\d{3,}\b", text) or "employee performance" in text or "performance of" in text:
            return PerformanceAnalysisType.EMPLOYEE
        return PerformanceAnalysisType.OVERVIEW

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        clean = frame.copy()
        for column in clean.select_dtypes(include=["datetime64[ns]"]).columns:
            clean[column] = clean[column].dt.strftime("%Y-%m-%d")
        clean = clean.where(pd.notna(clean), None)
        return [PerformanceService._clean_record(row) for row in clean.to_dict(orient="records")]

    @staticmethod
    def _clean_record(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        clean: dict[str, Any] = {}
        for key, value in row.items():
            if pd.isna(value):
                clean[key] = None
            elif isinstance(value, pd.Timestamp):
                clean[key] = value.date().isoformat()
            elif hasattr(value, "item"):
                clean[key] = value.item()
            else:
                clean[key] = value
        return clean
