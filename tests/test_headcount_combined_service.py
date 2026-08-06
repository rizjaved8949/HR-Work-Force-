"""Tests for combined deterministic Headcount analysis."""

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(
    __file__
).resolve().parents[1]

BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(
    0,
    str(BACKEND_DIR),
)


import paths
from headcount.repository import HeadcountRepository
from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountResultStatus,
    HeadcountScope,
)
from headcount.service import HeadcountService


@pytest.fixture
def service() -> HeadcountService:
    return HeadcountService(
        HeadcountRepository(
            paths.data_dir()
        )
    )


def metric_values(result) -> dict[str, object]:
    return {
        metric.metric_name: metric.value
        for metric in result.metrics
    }


def test_combined_organization_metrics(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show current Headcount, budget utilization, "
                "and employees available today."
            ),
            metrics=[
                "actual_employee_count",
                "budget_utilization_percentage",
                "employees_available_for_work",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["actual_employee_count"] == 720

    assert (
        values["budget_utilization_percentage"]
        == 86.97
    )

    assert (
        values["employees_available_for_work"]
        == 624
    )


def test_engineering_combined_scope(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Engineering Headcount, budget utilization, "
                "and workforce availability."
            ),
            metrics=[
                "actual_employee_count",
                "budget_utilization_percentage",
                "workforce_availability_percentage",
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

    assert (
        values["budget_utilization_percentage"]
        == 82.5
    )

    assert (
        values[
            "workforce_availability_percentage"
        ]
        == 95.56
    )


def test_department_vacancy_and_budget_breakdown(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show vacancy rate and budget utilization "
                "by department."
            ),
            metrics=[
                "vacancy_rate_percentage",
                "budget_utilization_percentage",
            ],
            group_by=[
                "department",
            ],
            top_n=20,
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 16

    engineering = next(
        record
        for record in result.records
        if record["department"] == "Engineering"
    )

    assert (
        engineering["vacancy_rate_percentage"]
        == 16.67
    )

    assert (
        engineering[
            "budget_utilization_percentage"
        ]
        == 82.5
    )


def test_business_unit_headcount_and_budget(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show employee count and approved people budget "
                "by business unit."
            ),
            metrics=[
                "actual_employee_count",
                "total_approved_people_budget",
            ],
            group_by=[
                "business_unit",
            ],
            top_n=10,
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 7

    total_employees = sum(
        int(record["actual_employee_count"])
        for record in result.records
    )

    total_budget = sum(
        int(
            record[
                "total_approved_people_budget"
            ]
        )
        for record in result.records
    )

    assert total_employees == 720
    assert total_budget == 185365289


def test_external_attrition_metric_returns_partial(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show current Headcount and expected exits."
            ),
            metrics=[
                "actual_employee_count",
                "expected_employee_exits",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.PARTIAL
    )

    values = metric_values(result)

    assert values["actual_employee_count"] == 720

    assert "expected_employee_exits" not in values

    assert any(
        "expected_employee_exits" in limitation
        for limitation in result.limitations
    )
