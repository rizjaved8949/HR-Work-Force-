"""Tests for deterministic daily workforce availability."""

import sys
from datetime import date
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
    HeadcountDateRange,
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


def test_latest_organization_availability(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "How many employees are available today?"
            ),
            metrics=[
                "actual_employee_count",
                "employees_available_for_work",
                "employees_on_approved_leave",
                "employees_absent",
                "total_overtime_hours",
                "workforce_availability_percentage",
                "daily_open_position_count",
                "daily_critical_open_position_count",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["actual_employee_count"] == 720

    assert (
        values["employees_available_for_work"]
        == 624
    )

    assert (
        values["employees_on_approved_leave"]
        == 20
    )

    assert values["employees_absent"] == 76
    assert values["total_overtime_hours"] == 146

    assert (
        values[
            "workforce_availability_percentage"
        ]
        == 86.67
    )

    assert (
        values["daily_open_position_count"]
        == 80
    )

    assert (
        values[
            "daily_critical_open_position_count"
        ]
        == 37
    )


def test_lowest_department_availability(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which department has the lowest "
                "workforce availability?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 1

    record = result.records[0]

    assert record["department"] == "Operations"

    assert (
        record[
            "workforce_availability_percentage"
        ]
        == 82.22
    )


def test_engineering_daily_availability(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Engineering workforce "
                "availability today."
            ),
            metrics=[
                "actual_employee_count",
                "employees_available_for_work",
                "employees_absent",
                "total_overtime_hours",
                "workforce_availability_percentage",
            ],
            scope=HeadcountScope(
                department="Engineering",
            ),
        )
    )

    values = metric_values(result)

    assert values["actual_employee_count"] == 45

    assert (
        values["employees_available_for_work"]
        == 43
    )

    assert values["employees_absent"] == 2
    assert values["total_overtime_hours"] == 12

    assert (
        values[
            "workforce_availability_percentage"
        ]
        == 95.56
    )


def test_highest_department_overtime(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which department has the highest "
                "overtime hours today?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    record = result.records[0]

    assert (
        record["department"]
        == "Production & Manufacturing"
    )

    assert record["total_overtime_hours"] == 19


def test_seven_day_availability_trend(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show daily availability for the "
                "last seven days."
            ),
            metrics=[
                "employees_available_for_work",
                "workforce_availability_percentage",
            ],
            group_by=[
                "activity_date",
            ],
            date_range=HeadcountDateRange(
                start_date=date(2026, 7, 26),
                end_date=date(2026, 8, 1),
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 7

    assert (
        result.records[-1][
            "employees_available_for_work"
        ]
        == 624
    )

    assert (
        result.records[-1][
            "workforce_availability_percentage"
        ]
        == 86.67
    )


def test_unknown_daily_department(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show today's availability for an "
                "unknown department."
            ),
            metrics=[
                "workforce_availability_percentage",
            ],
            scope=HeadcountScope(
                department="Unknown Department",
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.NOT_FOUND
    )