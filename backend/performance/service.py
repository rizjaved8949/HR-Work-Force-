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
    NUMBER_WORDS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20,
    }
    MONTH_NUMBERS = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4,
        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    DEPARTMENT_ALIASES = {
        "human resources": "HR",
        "human resource": "HR",
        "information technology": "IT",
        "r&d": "Research & Development",
        "research and development": "Research & Development",
        "qa": "Quality Assurance",
        "customer service": "Customer Support",
        "supply chain": "Procurement & Supply Chain",
        "manufacturing": "Production & Manufacturing",
        "admin": "Administration & Facilities",
    }

    def __init__(self, repository: PerformanceRepository) -> None:
        self.repository = repository
        self.dashboard = PerformanceDashboardService(repository)
        self.learning = PerformanceLearningService(repository)

    def analyze(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        """Route a natural-language question to deterministic Performance logic.

        The request is enriched from the user's wording before routing so common
        paraphrases (for example "top five departments", "best people in HR",
        "compare Finance with Sales", or "over the last six months") resolve to
        the same deterministic calculations.
        """

        request = self._enrich_request(request)
        employee_id = request.employee_id or self._extract_employee_id(request.question)
        employee_name = request.employee_name or self._extract_employee_name(request.question)
        analysis_type = request.analysis_type or self._infer_analysis_type(
            request.question,
            has_employee=bool(employee_id or employee_name),
        )
        department_mentions = self._extract_departments(request.question)
        if (
            request.analysis_type is None
            and analysis_type == PerformanceAnalysisType.OVERVIEW
            and len(department_mentions) > 1
            and self._requests_department_comparison(request.question)
        ):
            analysis_type = PerformanceAnalysisType.DEPARTMENT_RANKING

        try:
            if analysis_type == PerformanceAnalysisType.OVERVIEW:
                return self._overview_result(request)
            if analysis_type == PerformanceAnalysisType.DEPARTMENT_RANKING:
                return self._department_ranking_result(request)
            if analysis_type == PerformanceAnalysisType.EMPLOYEE_RANKING:
                return self._employee_ranking_result(request)
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
                    employee_name=employee_name,
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
                    return self._records_result(
                        request,
                        analysis_type,
                        records,
                        "Employee performance trend calculated.",
                        employee,
                    )

                if analysis_type == PerformanceAnalysisType.KPI_BREAKDOWN:
                    records = self.employee_kpi_breakdown(resolved_id, month=request.month)
                    return self._records_result(
                        request,
                        analysis_type,
                        records,
                        "Employee KPI breakdown calculated.",
                        employee,
                    )

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
                        employee=self._compact_employee_record(employee),
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
                        employee=self._compact_employee_record(employee),
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
                        employee=self._compact_employee_record(employee),
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
        """Return a compact employee answer unless a full evaluation was requested.

        Previously every employee Performance question returned twelve months of
        trend data, a full KPI breakdown, learning history, and recommendations.
        That made simple score/band questions unnecessarily expensive for the LLM
        to read. Detailed evidence is still returned when the user explicitly asks
        for a complete/full/detailed evaluation.
        """

        metrics = [
            MetricValue(metric_name="latest_performance_score", display_name="Latest Performance Score", value=float(employee["Latest_Performance_Score"]), unit="score / 100"),
            MetricValue(metric_name="latest_performance_band", display_name="Latest Performance Band", value=str(employee["Latest_Performance_Band"])),
            MetricValue(metric_name="average_12m_performance_score", display_name="12-Month Average", value=float(employee["Average_12M_Performance_Score"]), unit="score / 100"),
            MetricValue(metric_name="three_month_change_points", display_name="Three-Month Change", value=float(employee["Three_Month_Change_Points"]), unit="points"),
            MetricValue(metric_name="performance_trend", display_name="Performance Trend", value=str(employee["Performance_Trend"])),
        ]

        detailed = self._requests_full_evaluation(request.question)
        records: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        limitations: list[str] = []

        if detailed:
            employee_id = str(employee["Employee_ID"])
            records = [
                {
                    "section": "monthly_trend",
                    "data": self.employee_trend(employee_id, months=request.months),
                },
                {
                    "section": "kpi_breakdown",
                    "data": self.employee_kpi_breakdown(employee_id, month=request.month),
                },
            ]
            if request.include_learning:
                recommendations = self.learning.employee_recommendations(employee_id)
                history = self.learning.employee_learning_history(employee_id)
                if not self.repository.has_dataset("development_recommendations"):
                    limitations.append(
                        "Learning recommendation files have not yet been copied into the shared Data folder."
                    )

        return PerformanceToolResult(
            status=PerformanceResultStatus.SUCCESS,
            analysis_type=PerformanceAnalysisType.EMPLOYEE,
            question=request.question,
            message=(
                "Complete employee performance evaluation retrieved successfully."
                if detailed
                else "Employee performance summary retrieved successfully."
            ),
            metrics=metrics,
            employee=self._compact_employee_record(employee),
            records=records,
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
        metrics = [
            MetricValue(metric_name=k, display_name=k.replace("_", " ").title(), value=v)
            for k, v in data.items()
        ]

        records: list[dict[str, Any]] = []
        if self._requests_trend(request.question) or self._requests_overview_detail(request.question):
            records = self.dashboard.organization_trend(
                months=request.months,
                department=request.department,
                role_band=request.role_band,
            )

        return PerformanceToolResult(
            status=PerformanceResultStatus.SUCCESS,
            analysis_type=PerformanceAnalysisType.OVERVIEW,
            question=request.question,
            message="Performance overview calculated successfully.",
            metrics=metrics,
            records=records,
            data_as_of_date=self.repository.data_as_of_date(),
        )

    def _department_ranking_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        departments = self._extract_departments(request.question)
        compare_requested = self._requests_department_comparison(request.question)
        selected_departments = departments if (len(departments) > 1 or compare_requested) else None
        if len(departments) == 1 and self._asks_for_rank_of_named_department(request.question):
            selected_departments = departments

        rows = self.dashboard.department_ranking(
            month=request.month,
            limit=request.limit,
            ascending=self._asks_for_lowest(request.question),
            departments=selected_departments,
        )
        result = self._records_result(
            request,
            PerformanceAnalysisType.DEPARTMENT_RANKING,
            rows,
            "Department performance ranking calculated.",
        )
        result.calculation_notes.append(
            "Departments are ranked by the official monthly Average Performance Score."
        )
        return result

    def _employee_ranking_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        rows = self.dashboard.employee_ranking(
            month=request.month,
            department=request.department,
            role_band=request.role_band,
            limit=request.limit,
            ascending=self._asks_for_lowest(request.question),
        )
        result = self._records_result(
            request,
            PerformanceAnalysisType.EMPLOYEE_RANKING,
            rows,
            "Employee performance ranking calculated.",
        )
        result.calculation_notes.append(
            "Employees are ranked by the official normalized Final Performance Score for the selected month and scope."
        )
        return result

    def _distribution_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        rows = self.dashboard.distribution(
            month=request.month,
            department=request.department,
            role_band=request.role_band,
        )
        return self._records_result(
            request,
            PerformanceAnalysisType.DISTRIBUTION,
            rows,
            "Performance-band distribution calculated.",
        )

    def _attention_result(self, request: AnalyzePerformanceInput) -> PerformanceToolResult:
        rows = self.dashboard.attention(
            department=request.department,
            limit=request.limit,
        )
        return self._records_result(
            request,
            PerformanceAnalysisType.ATTENTION,
            rows,
            "Employees requiring performance attention identified.",
        )

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
            employee=self._compact_employee_record(employee) if employee else None,
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

    def _extract_employee_name(self, question: str) -> str | None:
        """Resolve a full employee name directly from wording when present.

        The LLM is still allowed to pass ``employee_name`` explicitly, but this
        deterministic fallback makes phrasing such as "How is Sonia Hassan doing?"
        work even when the tool call only carries the complete question.
        """

        text = (question or "").casefold()
        if not text:
            return None
        summary = self.repository.get("performance_summary")
        names = sorted(
            {str(value).strip() for value in summary["Employee_Name"].dropna()},
            key=len,
            reverse=True,
        )
        for name in names:
            if name.casefold() in text:
                return name
        return None

    def _enrich_request(self, request: AnalyzePerformanceInput) -> AnalyzePerformanceInput:
        """Fill deterministic scope/time/list hints that are present in wording."""

        departments = self._extract_departments(request.question)
        department = request.department
        if not department and len(departments) == 1:
            department = departments[0]

        month = request.month or self._extract_month(request.question)
        months = self._extract_month_count(request.question) or request.months
        ranking_limit = self._extract_ranking_limit(request.question)
        limit = ranking_limit or request.limit

        if ranking_limit is None and self._asks_for_single_result(request.question):
            limit = 1

        return request.model_copy(
            update={
                "department": department,
                "month": month,
                "months": max(1, min(int(months), 24)),
                "limit": max(1, min(int(limit), 100)),
            }
        )

    def _extract_departments(self, question: str) -> list[str]:
        text = (question or "").casefold()
        if not text:
            return []

        summary = self.repository.get("performance_summary")
        official = sorted(
            {str(value).strip() for value in summary["Department"].dropna()},
            key=len,
            reverse=True,
        )

        found: list[tuple[int, str]] = []
        raw_question = question or ""
        for name in official:
            # "it" is a common English pronoun, so only treat IT as a
            # department when the user writes the acronym explicitly.
            if name == "IT":
                match = re.search(r"(?<!\w)IT(?!\w)", raw_question)
            else:
                key = name.casefold()
                match = re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text)
            if match:
                found.append((match.start(), name))

        for alias, target in self.DEPARTMENT_ALIASES.items():
            match = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
            if match and target in official:
                found.append((match.start(), target))

        # Short official names such as HR and IT need word boundaries and may
        # already have been found above; de-duplicate while preserving mention order.
        ordered: list[str] = []
        for _, name in sorted(found, key=lambda item: item[0]):
            if name not in ordered:
                ordered.append(name)
        return ordered

    def _extract_month(self, question: str) -> pd.Timestamp | None:
        text = (question or "").casefold()
        latest = self.dashboard.latest_month()

        if re.search(r"\b(?:last|previous)\s+month\b", text):
            return (latest - pd.offsets.MonthBegin(1)).to_period("M").to_timestamp()
        if re.search(r"\b(?:current|latest|this)\s+month\b", text):
            return latest.to_period("M").to_timestamp()

        month_pattern = "|".join(sorted(self.MONTH_NUMBERS, key=len, reverse=True))
        match = re.search(
            rf"\b({month_pattern})\b(?:[\s,/-]+(20\d{{2}}))?",
            text,
        )
        if not match:
            return None

        month_number = self.MONTH_NUMBERS[match.group(1)]
        year = int(match.group(2)) if match.group(2) else latest.year
        if match.group(2) is None and month_number > latest.month:
            year -= 1
        return pd.Timestamp(year=year, month=month_number, day=1)

    @classmethod
    def _parse_small_number(cls, token: str) -> int | None:
        token = token.casefold().strip()
        if token.isdigit():
            return int(token)
        return cls.NUMBER_WORDS.get(token)

    @classmethod
    def _extract_month_count(cls, question: str) -> int | None:
        text = (question or "").casefold()
        number_token = r"(?:\d{1,2}|" + "|".join(cls.NUMBER_WORDS) + r")"
        match = re.search(
            rf"\b(?:last|past|previous|over|for)\s+({number_token})\s+months?\b",
            text,
        )
        return cls._parse_small_number(match.group(1)) if match else None

    @classmethod
    def _extract_ranking_limit(cls, question: str) -> int | None:
        text = (question or "").casefold()
        number_token = r"(?:\d{1,3}|" + "|".join(cls.NUMBER_WORDS) + r")"
        patterns = [
            rf"\b(?:top|bottom|best|worst|highest|lowest|leading)\s+({number_token})\b",
            rf"\b({number_token})\s+(?:top|bottom|best|worst|highest|lowest)\b",
            rf"\b({number_token})\s+(?:departments?|employees?|performers?|people)\b.*?\b(?:top|bottom|best|worst|highest|lowest)\b",
            rf"\b(?:top|bottom|best|worst|highest|lowest)\b.*?\b({number_token})\s+(?:departments?|employees?|performers?|people)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return cls._parse_small_number(match.group(1))
        return None

    @staticmethod
    def _requests_full_evaluation(question: str) -> bool:
        text = (question or "").casefold()
        return any(
            phrase in text
            for phrase in [
                "complete performance",
                "full performance",
                "detailed performance",
                "complete evaluation",
                "full evaluation",
                "detailed evaluation",
                "complete review",
                "full review",
            ]
        )

    @staticmethod
    def _requests_trend(question: str) -> bool:
        text = (question or "").casefold()
        return any(
            term in text
            for term in [
                "trend", "over time", "history", "historical", "month by month",
                "monthly", "improved", "improving", "declined", "declining",
                "change over", "progress",
            ]
        ) or bool(re.search(r"\b(?:last|past|previous|over)\s+(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+months?\b", text))

    @staticmethod
    def _requests_overview_detail(question: str) -> bool:
        text = (question or "").casefold()
        return any(term in text for term in ["overview", "summary", "dashboard", "overall performance"])

    @staticmethod
    def _requests_department_comparison(question: str) -> bool:
        text = (question or "").casefold()
        return any(term in text for term in ["compare", "comparison", "versus", " vs ", "against"])

    @staticmethod
    def _asks_for_rank_of_named_department(question: str) -> bool:
        text = (question or "").casefold()
        return any(term in text for term in ["rank", "ranking", "where does", "position among departments"])

    @staticmethod
    def _asks_for_lowest(question: str) -> bool:
        text = (question or "").casefold()
        return any(
            term in text
            for term in [
                "bottom", "worst", "lowest", "least performing", "weakest",
                "low performing", "lowest-performing", "worst-performing",
            ]
        )

    @staticmethod
    def _asks_for_single_result(question: str) -> bool:
        text = (question or "").casefold()
        if re.search(r"\b(?:top|bottom|best|worst|highest|lowest)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", text):
            return False
        if any(word in text for word in ["departments", "performers", "employees", "people", "staff members"]):
            return False
        return any(
            phrase in text
            for phrase in [
                "best department", "worst department", "highest performing department",
                "lowest performing department", "top department", "bottom department",
                "best performer", "worst performer", "top performer", "lowest performer",
                "highest performer",
            ]
        ) or bool(re.search(r"\bwhich\s+(?:department|employee|person).*(?:highest|lowest|best|worst)\b", text))

    @staticmethod
    def _infer_analysis_type(
        question: str,
        *,
        has_employee: bool = False,
    ) -> PerformanceAnalysisType:
        text = (question or "").casefold()

        if any(term in text for term in ["course", "training", "recommend", "development plan", "upskill", "learning recommendation"]):
            return PerformanceAnalysisType.RECOMMENDATIONS
        if any(term in text for term in ["learning history", "completed course", "completed training", "training history"]):
            return PerformanceAnalysisType.LEARNING
        if any(term in text for term in ["recalculate", "calculate again", "re-compute", "recompute", "verify calculation"]):
            return PerformanceAnalysisType.RECALCULATE

        if any(
            term in text
            for term in [
                "kpi", "why is", "why has", "driver", "drivers", "strength",
                "weakness", "development area", "target vs", "target versus",
                "actual vs", "actual versus", "target and actual", "score breakdown",
            ]
        ):
            return PerformanceAnalysisType.KPI_BREAKDOWN

        if has_employee and PerformanceService._requests_trend(text):
            return PerformanceAnalysisType.EMPLOYEE_TREND

        ranking_terms = ["top", "bottom", "best", "worst", "highest", "lowest", "rank", "ranking", "leading", "weakest"]
        employee_terms = ["performer", "performers", "employee", "employees", "people", "staff", "person"]
        if any(term in text for term in ranking_terms) and any(term in text for term in employee_terms):
            return PerformanceAnalysisType.EMPLOYEE_RANKING

        if "department" in text and (
            any(term in text for term in ranking_terms)
            or any(term in text for term in ["compare", "comparison", "versus", " vs ", "against"])
        ):
            return PerformanceAnalysisType.DEPARTMENT_RANKING
        if any(term in text for term in ["department ranking", "best department", "worst department", "compare departments", "department comparison"]):
            return PerformanceAnalysisType.DEPARTMENT_RANKING

        attention_requested = any(
            term in text
            for term in [
                "underperforming", "performance concern", "performance concerns",
                "improvement required", "needs improvement", "need improvement",
                "low performer", "low performers",
            ]
        ) or bool(
            re.search(r"\b(?:need|needs|require|requires|requiring)\b.*\battention\b", text)
        ) or bool(
            re.search(r"\b(?:employee|employees|people|staff|who)\b.*\bdeclin(?:e|ed|ing)\b", text)
        )
        if attention_requested:
            return PerformanceAnalysisType.ATTENTION

        band_terms = [
            "exceptional", "strong", "meets expectations",
            "partially meets", "improvement required",
        ]
        distribution_requested = any(
            term in text
            for term in [
                "distribution", "performance band", "band breakdown", "band distribution",
            ]
        ) or (
            any(term in text for term in band_terms)
            and any(term in text for term in ["how many", "count", "percentage", "percent", "%", "proportion", "breakdown"])
        )
        if distribution_requested:
            return PerformanceAnalysisType.DISTRIBUTION

        if has_employee or re.search(r"\bemp\d{3,}\b", text):
            return PerformanceAnalysisType.EMPLOYEE
        if any(term in text for term in ["employee performance", "performance of employee"]):
            return PerformanceAnalysisType.EMPLOYEE
        return PerformanceAnalysisType.OVERVIEW

    @staticmethod
    def _compact_employee_record(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        fields = [
            "Employee_ID",
            "Employee_Name",
            "Department",
            "Business_Unit",
            "Position_Title",
            "Designation",
            "Job_Level",
            "Role_Band",
            "Latest_Performance_Month",
            "Latest_Performance_Score",
            "Latest_Performance_Band",
            "Average_12M_Performance_Score",
            "Three_Month_Change_Points",
            "Performance_Trend",
            "Review_Status",
            "Data_As_Of_Date",
        ]
        compact = {key: row.get(key) for key in fields if key in row}
        return PerformanceService._clean_record(compact)

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
