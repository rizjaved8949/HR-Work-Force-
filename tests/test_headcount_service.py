"""Tests for the deterministic current Headcount service."""

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


import paths
from headcount.repository import HeadcountRepository
from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountAnalysisType,
    HeadcountResultStatus,
    HeadcountScope,
)
from headcount.service import HeadcountService


@pytest.fixture
def service() -> HeadcountService:
    repository = HeadcountRepository(
        paths.data_dir()
    )

    return HeadcountService(repository)


def metric_values(result) -> dict[str, object]:
    return {
        metric.metric_name: metric.value
        for metric in result.metrics
    }


def test_organization_current_headcount(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the current organization Headcount."
            ),
            metrics=[
                "actual_employee_count",
                "approved_position_count",
                "budgeted_position_count",
                "filled_position_count",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["actual_employee_count"] == 720
    assert values["approved_position_count"] == 797
    assert values["budgeted_position_count"] == 773
    assert values["filled_position_count"] == 720


def test_gross_vacancies_and_net_gaps_are_separate(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show open positions and net staffing gaps."
            ),
            metrics=[
                "vacant_approved_position_count",
                "funded_vacant_position_count",
                "unfunded_vacant_position_count",
                "net_approved_headcount_gap",
                "net_budgeted_headcount_gap",
                "overstaffed_employee_count",
            ],
        )
    )

    values = metric_values(result)

    assert (
        values["vacant_approved_position_count"]
        == 80
    )

    assert (
        values["funded_vacant_position_count"]
        == 56
    )

    assert (
        values["unfunded_vacant_position_count"]
        == 24
    )

    assert (
        values["net_approved_headcount_gap"]
        == 77
    )

    assert (
        values["net_budgeted_headcount_gap"]
        == 53
    )

    assert (
        values["overstaffed_employee_count"]
        == 3
    )


def test_organization_vacancy_rate(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "What is the organization vacancy rate?"
            ),
            metrics=[
                "vacancy_rate_percentage",
                "headcount_utilization_percentage",
            ],
        )
    )

    values = metric_values(result)

    assert values[
        "vacancy_rate_percentage"
    ] == 10.04

    assert values[
        "headcount_utilization_percentage"
    ] == 90.34


def test_highest_department_vacancy_rate(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which department has the highest "
                "vacancy rate?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 1

    top_record = result.records[0]

    assert (
        top_record["department"]
        == "Production & Manufacturing"
    )

    assert (
        top_record["vacancy_rate_percentage"]
        == 19.64
    )


def test_engineering_headcount_scope(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Engineering Headcount details."
            ),
            metrics=[
                "actual_employee_count",
                "approved_position_count",
                "budgeted_position_count",
                "vacant_approved_position_count",
                "funded_vacant_position_count",
                "vacancy_rate_percentage",
            ],
            scope=HeadcountScope(
                department="Engineering",
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["actual_employee_count"] == 45
    assert values["approved_position_count"] == 54
    assert values["budgeted_position_count"] == 51

    assert (
        values["vacant_approved_position_count"]
        == 9
    )

    assert (
        values["funded_vacant_position_count"]
        == 6
    )

    assert values[
        "vacancy_rate_percentage"
    ] == 16.67


def test_business_unit_breakdown(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show actual Headcount by business unit."
            ),
            metrics=[
                "actual_employee_count",
            ],
            group_by=[
                "business_unit",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 7

    total_actual = sum(
        int(record["actual_employee_count"])
        for record in result.records
    )

    assert total_actual == 720


def test_unknown_department_returns_not_found(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Headcount for an unknown department."
            ),
            metrics=[
                "actual_employee_count",
            ],
            scope=HeadcountScope(
                department="Unknown Department",
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.NOT_FOUND
    )


def test_budget_metric_is_supported(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "What is the current budget utilization?"
            ),
            analysis_type=HeadcountAnalysisType.BUDGET,
            metrics=[
                "budget_utilization_percentage",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert (
        values["budget_utilization_percentage"]
        == 86.97
    )