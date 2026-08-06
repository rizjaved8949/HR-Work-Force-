"""Tests for deterministic workforce-composition analysis."""

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
    HeadcountResultStatus,
    HeadcountScope,
)
from headcount.service import HeadcountService


@pytest.fixture
def service() -> HeadcountService:
    return HeadcountService(
        HeadcountRepository(paths.data_dir())
    )


def metric_values(result) -> dict[str, object]:
    return {
        metric.metric_name: metric.value
        for metric in result.metrics
    }


def test_workforce_inclusion_summary(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the approved Headcount inclusion summary."
            ),
            metrics=[
                "actual_employee_count",
                "included_in_approved_headcount_count",
                "excluded_from_approved_headcount_count",
                "approved_headcount_inclusion_percentage",
            ],
        )
    )

    assert result.status == HeadcountResultStatus.SUCCESS

    values = metric_values(result)

    assert values["actual_employee_count"] == 720
    assert (
        values["included_in_approved_headcount_count"]
        == 717
    )
    assert (
        values["excluded_from_approved_headcount_count"]
        == 3
    )
    assert (
        values["approved_headcount_inclusion_percentage"]
        == 99.58
    )


def test_headcount_by_job_level(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question="Show Headcount by job level.",
            metrics=["actual_employee_count"],
            group_by=["job_level"],
        )
    )

    counts = {
        record["job_level"]: record["actual_employee_count"]
        for record in result.records
    }

    assert counts == {
        "Mid": 219,
        "Junior": 218,
        "Senior": 128,
        "Lead/Manager": 91,
        "Intern": 48,
        "Executive": 16,
    }


def test_senior_engineering_employees(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "How many Senior employees work in Engineering?"
            ),
            metrics=["actual_employee_count"],
            scope=HeadcountScope(
                department="Engineering",
                job_level="Senior",
            ),
        )
    )

    assert result.status == HeadcountResultStatus.SUCCESS
    assert metric_values(result)["actual_employee_count"] == 8


def test_employment_type_breakdown(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question="Show Headcount by employment type.",
            metrics=["actual_employee_count"],
            group_by=["employment_type"],
        )
    )

    counts = {
        record["employment_type"]:
            record["actual_employee_count"]
        for record in result.records
    }

    assert counts == {
        "Permanent": 593,
        "Contract": 79,
        "Internship": 48,
    }


def test_work_mode_is_normalized(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question="Show employees by work mode.",
            metrics=["actual_employee_count"],
            group_by=["work_mode"],
        )
    )

    counts = {
        record["work_mode"]: record["actual_employee_count"]
        for record in result.records
    }

    assert counts == {
        "On-site": 492,
        "Hybrid": 198,
        "Remote": 30,
    }


def test_largest_work_location(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which work location has the most employees?"
            ),
            metrics=["actual_employee_count"],
            group_by=["work_location"],
            sort_by="actual_employee_count",
            top_n=1,
        )
    )

    assert len(result.records) == 1

    record = result.records[0]

    assert (
        record["work_location"]
        == "Corporate Headquarters"
    )
    assert record["actual_employee_count"] == 315


def test_two_dimension_composition(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show employees by department and employment type."
            ),
            metrics=["actual_employee_count"],
            group_by=[
                "department",
                "employment_type",
            ],
            top_n=100,
        )
    )

    engineering_permanent = next(
        record
        for record in result.records
        if (
            record["department"] == "Engineering"
            and record["employment_type"] == "Permanent"
        )
    )

    assert (
        engineering_permanent["actual_employee_count"]
        == 39
    )

    total = sum(
        int(record["actual_employee_count"])
        for record in result.records
    )

    assert total == 720


def test_unknown_work_location_returns_not_found(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question="Show employees at an unknown location.",
            metrics=["actual_employee_count"],
            scope=HeadcountScope(
                work_location="Unknown Location",
            ),
        )
    )

    assert result.status == HeadcountResultStatus.NOT_FOUND
