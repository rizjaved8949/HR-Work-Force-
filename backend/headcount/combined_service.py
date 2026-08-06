"""Combined deterministic Headcount analysis.

This service orchestrates the existing isolated Headcount services when one
question requests metrics from more than one Headcount domain, for example:

- current Headcount plus people budget;
- vacancy rate plus budget utilization by department;
- current Headcount plus daily availability;
- workforce composition plus budget by business unit.

It does not call an LLM. It only combines structured results returned by the
existing deterministic services.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Final

from headcount.budget_service import (
    BUDGET_METRICS,
    HeadcountBudgetService,
)
from headcount.daily_service import (
    DAILY_ACTIVITY_METRICS,
    DAILY_ONLY_METRICS,
    HeadcountDailyService,
)
from headcount.governance_service import (
    GOVERNANCE_METRICS,
    HeadcountGovernanceService,
)
from headcount.history_service import (
    HISTORY_METRICS,
    MOVEMENT_METRIC_TYPES,
    HeadcountHistoryService,
)
from headcount.schemas import (
    HeadcountAnalysisType,
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
    SortDirection,
)
from headcount.vacancy_service import (
    VACANCY_DETAIL_ONLY_METRICS,
    VACANCY_SERVICE_METRICS,
    HeadcountVacancyService,
)
from headcount.workforce_service import (
    WORKFORCE_COMPOSITION_METRICS,
    WORKFORCE_COMPOSITION_ONLY_METRICS,
    WORKFORCE_GROUPING_DIMENSIONS,
    HeadcountWorkforceService,
)


CurrentExecutor = Callable[
    [HeadcountQueryPlan],
    HeadcountToolResult,
]


CURRENT_COMBINABLE_METRICS: Final[set[str]] = {
    "actual_employee_count",
    "actual_full_time_equivalent",
    "approved_position_count",
    "budgeted_position_count",
    "filled_position_count",
    "vacant_position_count",
    "frozen_position_count",
    "vacant_approved_position_count",
    "funded_vacant_position_count",
    "unfunded_vacant_position_count",
    "headcount_variance",
    "net_approved_headcount_gap",
    "net_budgeted_headcount_gap",
    "vacancy_rate_percentage",
    "headcount_utilization_percentage",
    "overstaffed_employee_count",
}


SERVICE_ORDER: Final[tuple[str, ...]] = (
    "current",
    "workforce",
    "vacancy",
    "budget",
    "daily",
    "history",
    "governance",
)


GROUP_KEY_MAP: Final[dict[str, str]] = {
    "department": "department",
    "business_unit": "business_unit",
    "job_level": "job_level",
    "career_level": "career_level",
    "employment_type": "employment_type",
    "employee_status": "employee_status",
    "work_mode": "work_mode",
    "work_location": "work_location",
    "organizational_unit": "organizational_unit",
    "cost_center": "cost_center",
    "shift_type": "shift_type",
    "employee_category": "employee_category",
    "headcount_inclusion_category": (
        "headcount_inclusion_category"
    ),
    "included_in_approved_headcount": (
        "included_in_approved_headcount"
    ),
    "position": "position_id",
    "recruitment_stage": "recruitment_stage",
    "position_criticality": "position_criticality",
    "vacancy_status": "vacancy_status",
    "activity_date": "activity_date",
    "month": "snapshot_month",
    "severity": "severity",
    "exception_type": "exception_type",
}


class HeadcountCombinedError(RuntimeError):
    """Base error for combined Headcount analysis."""


class HeadcountCombinedService:
    """Coordinate multiple deterministic Headcount services."""

    def __init__(
        self,
        *,
        current_executor: CurrentExecutor,
        budget_service: HeadcountBudgetService,
        daily_service: HeadcountDailyService,
        governance_service: HeadcountGovernanceService,
        history_service: HeadcountHistoryService,
        vacancy_service: HeadcountVacancyService,
        workforce_service: HeadcountWorkforceService,
    ) -> None:
        self.current_executor = current_executor
        self.budget_service = budget_service
        self.daily_service = daily_service
        self.governance_service = governance_service
        self.history_service = history_service
        self.vacancy_service = vacancy_service
        self.workforce_service = workforce_service

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one multi-domain Headcount plan."""

        if not plan.metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.INVALID_REQUEST,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "A combined Headcount request must include "
                    "at least one supported metric."
                ),
            )

        metric_buckets, unsupported_metrics = (
            self._partition_metrics(plan)
        )

        results: list[HeadcountToolResult] = []

        for service_name in SERVICE_ORDER:
            metrics = metric_buckets.get(service_name, [])

            if not metrics:
                continue

            subplan = self._create_subplan(
                plan=plan,
                service_name=service_name,
                metrics=metrics,
            )

            results.append(
                self._execute_service(
                    service_name,
                    subplan,
                )
            )

        successful_results = [
            result
            for result in results
            if result.status
            == HeadcountResultStatus.SUCCESS
        ]

        if not successful_results:
            limitations = [
                limitation
                for result in results
                for limitation in result.limitations
            ]

            if unsupported_metrics:
                limitations.append(
                    "Unsupported combined metrics: "
                    + ", ".join(unsupported_metrics)
                )

            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "The combined Headcount request could not "
                    "be executed with the currently available "
                    "deterministic services."
                ),
                limitations=self._unique(limitations),
                data_as_of_date=self._latest_date(results),
            )

        metrics = self._merge_metrics(
            requested_metrics=plan.metrics,
            results=successful_results,
        )

        records = self._merge_records(
            plan=plan,
            results=successful_results,
        )

        has_incomplete_result = bool(
            unsupported_metrics
            or any(
                result.status
                != HeadcountResultStatus.SUCCESS
                for result in results
            )
        )

        limitations = [
            limitation
            for result in results
            for limitation in result.limitations
        ]

        if unsupported_metrics:
            limitations.append(
                "Metrics not yet available in combined "
                "Headcount analysis: "
                + ", ".join(unsupported_metrics)
            )

        resolved_scope: dict[str, Any] = {}

        for result in successful_results:
            resolved_scope.update(
                result.resolved_scope
            )

        resolved_scope["combined_services"] = [
            service_name
            for service_name in SERVICE_ORDER
            if metric_buckets.get(service_name)
        ]

        return HeadcountToolResult(
            status=(
                HeadcountResultStatus.PARTIAL
                if has_incomplete_result
                else HeadcountResultStatus.SUCCESS
            ),
            question=plan.question,
            analysis_type=plan.analysis_type,
            message=(
                "Combined Headcount analysis completed with "
                "partial coverage."
                if has_incomplete_result
                else (
                    "Combined Headcount analysis completed "
                    "successfully."
                )
            ),
            resolved_scope=resolved_scope,
            metrics=metrics,
            records=records,
            evidence_sources=self._unique(
                [
                    source
                    for result in successful_results
                    for source in result.evidence_sources
                ]
            ),
            data_as_of_date=self._latest_date(
                successful_results
            ),
            calculation_notes=self._unique(
                [
                    note
                    for result in successful_results
                    for note in result.calculation_notes
                ]
            ),
            limitations=self._unique(limitations),
        )

    # ========================================================
    # METRIC ROUTING
    # ========================================================

    def _partition_metrics(
        self,
        plan: HeadcountQueryPlan,
    ) -> tuple[dict[str, list[str]], list[str]]:
        buckets: dict[str, list[str]] = {
            service_name: []
            for service_name in SERVICE_ORDER
        }

        unsupported: list[str] = []

        group_dimension = (
            plan.group_by[0]
            if plan.group_by
            else None
        )

        for metric in plan.metrics:
            service_name = self._service_for_metric(
                metric=metric,
                group_dimension=group_dimension,
                has_date_range=(
                    plan.date_range is not None
                ),
            )

            if service_name is None:
                unsupported.append(metric)
                continue

            buckets[service_name].append(metric)

        return buckets, unsupported

    @staticmethod
    def _service_for_metric(
        *,
        metric: str,
        group_dimension: str | None,
        has_date_range: bool,
    ) -> str | None:
        if metric in GOVERNANCE_METRICS:
            return "governance"

        if metric in BUDGET_METRICS:
            return "budget"

        if metric in DAILY_ONLY_METRICS:
            return "daily"

        if (
            metric in MOVEMENT_METRIC_TYPES
            or (
                has_date_range
                and metric in HISTORY_METRICS
            )
            or (
                group_dimension == "month"
                and metric in HISTORY_METRICS
            )
        ):
            return "history"

        if metric in VACANCY_DETAIL_ONLY_METRICS:
            return "vacancy"

        if metric in WORKFORCE_COMPOSITION_ONLY_METRICS:
            return "workforce"

        if (
            group_dimension
            in WORKFORCE_GROUPING_DIMENSIONS
            and metric in WORKFORCE_COMPOSITION_METRICS
        ):
            return "workforce"

        if (
            group_dimension == "activity_date"
            and metric in DAILY_ACTIVITY_METRICS
        ):
            return "daily"

        if metric in CURRENT_COMBINABLE_METRICS:
            return "current"

        if metric in VACANCY_SERVICE_METRICS:
            return "vacancy"

        if metric in WORKFORCE_COMPOSITION_METRICS:
            return "workforce"

        if metric in DAILY_ACTIVITY_METRICS:
            return "daily"

        if metric in HISTORY_METRICS:
            return "history"

        return None

    # ========================================================
    # SUBPLANS AND SERVICE EXECUTION
    # ========================================================

    def _create_subplan(
        self,
        *,
        plan: HeadcountQueryPlan,
        service_name: str,
        metrics: list[str],
    ) -> HeadcountQueryPlan:
        analysis_type = self._analysis_type_for_service(
            plan=plan,
            service_name=service_name,
            metrics=metrics,
        )

        return plan.model_copy(
            update={
                "analysis_type": analysis_type,
                "metrics": metrics,
                "include_details": (
                    plan.include_details
                    or bool(plan.group_by)
                ),
                "requested_source_tables": [],
            }
        )

    @staticmethod
    def _analysis_type_for_service(
        *,
        plan: HeadcountQueryPlan,
        service_name: str,
        metrics: list[str],
    ) -> HeadcountAnalysisType:
        if service_name == "budget":
            return HeadcountAnalysisType.BUDGET

        if service_name == "daily":
            return HeadcountAnalysisType.AVAILABILITY

        if service_name == "history":
            if all(
                metric in MOVEMENT_METRIC_TYPES
                for metric in metrics
            ):
                return HeadcountAnalysisType.MOVEMENT

            return HeadcountAnalysisType.TREND

        if service_name == "vacancy":
            return HeadcountAnalysisType.VACANCY

        if service_name == "governance":
            if metrics == ["active_rule_count"]:
                return HeadcountAnalysisType.RULE

            return HeadcountAnalysisType.EXCEPTION

        if plan.group_by:
            if plan.sort_by is not None:
                return HeadcountAnalysisType.RANKING

            return HeadcountAnalysisType.BREAKDOWN

        return HeadcountAnalysisType.METRIC

    def _execute_service(
        self,
        service_name: str,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        if service_name == "current":
            return self.current_executor(plan)

        if service_name == "budget":
            return self.budget_service.execute(plan)

        if service_name == "daily":
            return self.daily_service.execute(plan)

        if service_name == "governance":
            return self.governance_service.execute(plan)

        if service_name == "history":
            return self.history_service.execute(plan)

        if service_name == "vacancy":
            return self.vacancy_service.execute(plan)

        if service_name == "workforce":
            return self.workforce_service.execute(plan)

        raise HeadcountCombinedError(
            f"Unknown combined service {service_name!r}."
        )

    # ========================================================
    # RESULT MERGING
    # ========================================================

    @staticmethod
    def _merge_metrics(
        *,
        requested_metrics: list[str],
        results: list[HeadcountToolResult],
    ) -> list[HeadcountMetricResult]:
        metric_map = {
            metric.metric_name: metric
            for result in results
            for metric in result.metrics
        }

        return [
            metric_map[metric_name]
            for metric_name in requested_metrics
            if metric_name in metric_map
        ]

    def _merge_records(
        self,
        *,
        plan: HeadcountQueryPlan,
        results: list[HeadcountToolResult],
    ) -> list[dict[str, Any]]:
        if not plan.include_details:
            return []

        if not plan.group_by:
            return []

        group_dimension = plan.group_by[0]
        key_column = GROUP_KEY_MAP.get(
            group_dimension,
            group_dimension,
        )

        merged: dict[str, dict[str, Any]] = {}

        for result in results:
            for record in result.records:
                key_value = record.get(key_column)

                if key_value is None:
                    continue

                key = str(key_value)

                if key not in merged:
                    merged[key] = {
                        key_column: key_value,
                    }

                merged[key].update(record)

        records = list(merged.values())

        sort_column = plan.sort_by

        if sort_column is None:
            sort_column = next(
                (
                    metric
                    for metric in plan.metrics
                    if any(
                        metric in record
                        for record in records
                    )
                ),
                None,
            )

        if sort_column is not None:
            records.sort(
                key=lambda record: self._sort_key(
                    record.get(sort_column)
                ),
                reverse=(
                    plan.sort_direction
                    == SortDirection.DESCENDING
                ),
            )

        return records[:plan.limit]

    @staticmethod
    def _sort_key(value: Any) -> tuple[int, Any]:
        if value is None:
            return (1, 0)

        return (0, value)

    # ========================================================
    # COMMON HELPERS
    # ========================================================

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _latest_date(
        results: list[HeadcountToolResult],
    ) -> date | None:
        dates = [
            result.data_as_of_date
            for result in results
            if result.data_as_of_date is not None
        ]

        if not dates:
            return None

        return max(dates)
