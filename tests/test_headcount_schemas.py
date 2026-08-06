"""Tests for the isolated Headcount Pydantic schemas."""
from datetime import date
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


from headcount.schemas import (
    AnalyzeHeadcountInput,
    FilterOperator,
    HeadcountAnalysisType,
    HeadcountDateRange,
    HeadcountFilter,
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountScope,
    HeadcountToolResult,
    SortDirection,
)


def test_minimal_headcount_input() -> None:
    request = AnalyzeHeadcountInput(
        question="What is our current total headcount?"
    )

    assert request.question == (
        "What is our current total headcount?"
    )
    assert request.metrics == []
    assert request.group_by == []
    assert request.filters == []
    assert request.top_n == 10


def test_complex_headcount_input() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Show the five funded critical Engineering vacancies "
            "that have been open for at least 90 days."
        ),
        analysis_type=HeadcountAnalysisType.VACANCY,
        metrics=[
            "funded_vacancy_count",
            "vacancy_age_in_days",
        ],
        group_by=["position"],
        scope=HeadcountScope(
            department="Engineering",
            position_criticality="Critical",
            position_status="Vacant",
        ),
        filters=[
            HeadcountFilter(
                field="vacancy_age_in_days",
                operator=(
                    FilterOperator.GREATER_THAN_OR_EQUAL
                ),
                value=90,
            ),
            HeadcountFilter(
                field="budgeted_position",
                operator=FilterOperator.EQUALS,
                value="Yes",
            ),
        ],
        sort_by="vacancy_age_in_days",
        sort_direction=SortDirection.DESCENDING,
        top_n=5,
    )

    assert request.scope.department == "Engineering"
    assert request.top_n == 5
    assert len(request.filters) == 2


def test_between_filter_requires_two_values() -> None:
    with pytest.raises(ValidationError):
        HeadcountFilter(
            field="budget_utilization_percentage",
            operator=FilterOperator.BETWEEN,
            value=[80],
        )


def test_invalid_date_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        HeadcountDateRange(
    start_date=date(2026, 8, 1),
    end_date=date(2026, 1, 1),
)


def test_query_plan_creation() -> None:
    plan = HeadcountQueryPlan(
        question=(
            "Which department has the highest vacancy rate?"
        ),
        analysis_type=HeadcountAnalysisType.RANKING,
        metrics=["vacancy_rate_percentage"],
        group_by=["department"],
        sort_by="vacancy_rate_percentage",
        sort_direction=SortDirection.DESCENDING,
        limit=1,
        requested_source_tables=[
            "employees",
            "positions",
        ],
    )

    assert plan.analysis_type == (
        HeadcountAnalysisType.RANKING
    )
    assert plan.limit == 1


def test_successful_tool_result_serialization() -> None:
    result = HeadcountToolResult(
        status=HeadcountResultStatus.SUCCESS,
        question=(
            "Which department has the highest vacancy rate?"
        ),
        analysis_type=HeadcountAnalysisType.RANKING,
        resolved_scope={
            "organization": "All",
            "period": "Current",
        },
        metrics=[
            HeadcountMetricResult(
                metric_name="vacancy_rate_percentage",
                display_name="Vacancy Rate",
                value=16.67,
                unit="percentage",
                numerator=9,
                denominator=54,
            )
        ],
        records=[
            {
                "department": "Engineering",
                "actual_employee_count": 45,
                "approved_position_count": 54,
                "vacant_approved_position_count": 9,
                "vacancy_rate_percentage": 16.67,
            }
        ],
        evidence_sources=[
            "Employee_Profile.csv",
            "Position_Master.csv",
        ],
       data_as_of_date=date(2026, 8, 1),
        calculation_notes=[
            (
                "Vacancy rate equals vacant approved positions "
                "divided by approved positions."
            )
        ],
    )

    serialized = result.model_dump(mode="json")

    assert serialized["status"] == "success"
    assert serialized["data_as_of_date"] == "2026-08-01"
    assert serialized["metrics"][0]["value"] == 16.67