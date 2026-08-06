"""Tests for the safe Headcount query planner."""

import sys
from datetime import date
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


from headcount.query_planner import (
    HeadcountPlanningError,
    create_headcount_query_plan,
)
from headcount.schemas import (
    AnalyzeHeadcountInput,
    FilterOperator,
    HeadcountAnalysisType,
    HeadcountDateRange,
    HeadcountFilter,
    HeadcountScope,
)


def test_current_headcount_question() -> None:
    request = AnalyzeHeadcountInput(
        question="What is our current headcount?"
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.METRIC
    )

    assert plan.metrics == [
        "actual_employee_count"
    ]

    assert "assignments" in (
        plan.requested_source_tables
    )


def test_default_overview_question() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Give me an overview of the current workforce."
        )
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.OVERVIEW
    )

    assert "actual_employee_count" in plan.metrics
    assert "approved_position_count" in plan.metrics
    assert "vacancy_rate_percentage" in plan.metrics


def test_department_vacancy_ranking() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Which department has the highest vacancy rate?"
        )
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.RANKING
    )

    assert plan.metrics == [
        "vacancy_rate_percentage"
    ]

    assert plan.group_by == ["department"]

    assert plan.sort_by == (
        "vacancy_rate_percentage"
    )

    assert plan.limit == 1


def test_structured_funded_vacancy_question() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Show the top five funded critical vacancies "
            "older than 90 days."
        ),
        analysis_type=HeadcountAnalysisType.VACANCY,
        metrics=[
            "funded vacancies",
            "vacancy age",
        ],
        group_by=["position"],
        filters=[
            HeadcountFilter(
                field="position criticality",
                operator=FilterOperator.IN,
                value=["High", "Critical"],
            ),
            HeadcountFilter(
                field="vacancy age",
                operator=FilterOperator.GREATER_THAN_OR_EQUAL,
                value=90,
            ),
        ],
        sort_by="vacancy age",
        top_n=5,
    )

    plan = create_headcount_query_plan(request)

    assert plan.metrics == [
        "funded_vacant_position_count",
        "vacancy_age_in_days",
    ]

    assert plan.group_by == ["position"]
    assert plan.limit == 5

    assert "vacancy_history" in (
        plan.requested_source_tables
    )


def test_employee_id_is_extracted() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Which position does EMP004 currently occupy?"
        )
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.EMPLOYEE_LOOKUP
    )

    assert plan.scope.employee_id == "EMP004"
    assert "employees" in plan.requested_source_tables


def test_explicit_employee_scope_is_preserved() -> None:
    request = AnalyzeHeadcountInput(
        question="Show the employee's headcount details.",
        scope=HeadcountScope(
            employee_id="EMP120"
        ),
    )

    plan = create_headcount_query_plan(request)

    assert plan.scope.employee_id == "EMP120"


def test_historical_question_uses_snapshot() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Show the headcount trend during the last six months."
        ),
        metrics=["actual headcount"],
        date_range=HeadcountDateRange(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 8, 1),
            period_label="last six months",
        ),
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.TREND
    )

    assert "monthly_snapshots" in (
        plan.requested_source_tables
    )

    assert "assignments" not in (
        plan.requested_source_tables
    )


def test_combined_budget_and_vacancy_question() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Which departments have high vacancy rates "
            "and high budget utilization?"
        ),
        metrics=[
            "vacancy rate",
            "budget utilization",
        ],
        group_by=["department"],
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.COMBINED
    )

    assert set(plan.metrics) == {
        "vacancy_rate_percentage",
        "budget_utilization_percentage",
    }


def test_unknown_metric_is_rejected() -> None:
    request = AnalyzeHeadcountInput(
        question="Calculate an unsupported workforce metric.",
        metrics=["imaginary workforce score"],
    )

    with pytest.raises(
        HeadcountPlanningError
    ):
        create_headcount_query_plan(request)


def test_unknown_filter_is_rejected() -> None:
    request = AnalyzeHeadcountInput(
        question="Filter the workforce.",
        filters=[
            HeadcountFilter(
                field="unknown_sensitive_field",
                operator=FilterOperator.EQUALS,
                value="Example",
            )
        ],
    )

    with pytest.raises(
        HeadcountPlanningError
    ):
        create_headcount_query_plan(request)

def test_rule_question_is_inferred() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "What Headcount rules apply to Engineering?"
        ),
        scope=HeadcountScope(
            department="Engineering",
        ),
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.RULE
    )

    assert plan.metrics == [
        "active_rule_count"
    ]

    assert "rules" in (
        plan.requested_source_tables
    )
def test_senior_employee_question_infers_count() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "How many Senior employees work "
            "in Engineering?"
        ),
    )

    plan = create_headcount_query_plan(request)

    assert plan.metrics == [
        "actual_employee_count"
    ]


def test_work_location_ranking_is_inferred() -> None:
    request = AnalyzeHeadcountInput(
        question=(
            "Which work location has the most employees?"
        ),
    )

    plan = create_headcount_query_plan(request)

    assert plan.analysis_type == (
        HeadcountAnalysisType.RANKING
    )

    assert plan.metrics == [
        "actual_employee_count"
    ]

    assert plan.group_by == [
        "work_location"
    ]

    assert plan.limit == 1