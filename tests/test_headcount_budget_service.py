"""Tests for deterministic Headcount budget analysis."""

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(
    __file__
).resolve().parents[1]

BACKEND_DIR = (
    PROJECT_ROOT / "backend"
)

sys.path.insert(
    0,
    str(BACKEND_DIR),
)


import paths
from headcount.repository import (
    HeadcountRepository,
)
from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountResultStatus,
    HeadcountScope,
)
from headcount.service import (
    HeadcountService,
)


@pytest.fixture
def service() -> HeadcountService:
    repository = HeadcountRepository(
        paths.data_dir()
    )

    return HeadcountService(
        repository
    )


def metric_values(
    result,
) -> dict[str, object]:
    return {
        metric.metric_name: metric.value
        for metric in result.metrics
    }


def test_current_organization_budget(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the current organization "
                "people budget."
            ),
            metrics=[
                "total_approved_people_budget",
                "total_actual_people_cost",
                "remaining_people_budget",
                "budget_utilization_percentage",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert (
        values[
            "total_approved_people_budget"
        ]
        == 185365289
    )

    assert (
        values[
            "total_actual_people_cost"
        ]
        == 161213624
    )

    assert (
        values[
            "remaining_people_budget"
        ]
        == 24151665
    )

    assert (
        values[
            "budget_utilization_percentage"
        ]
        == 86.97
    )


def test_current_cost_components(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show salary, benefits and "
                "overtime costs."
            ),
            metrics=[
                "actual_salary_cost",
                "actual_benefits_cost",
                "actual_overtime_cost",
            ],
        )
    )

    values = metric_values(result)

    assert (
        values["actual_salary_cost"]
        == 131146113
    )

    assert (
        values["actual_benefits_cost"]
        == 26229217
    )

    assert (
        values["actual_overtime_cost"]
        == 2866364
    )


def test_highest_department_budget_utilization(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which department has the highest "
                "budget utilization?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 1

    record = result.records[0]

    assert (
        record["department"]
        == "Legal & Compliance"
    )

    assert (
        record[
            "budget_utilization_percentage"
        ]
        == 97.22
    )


def test_engineering_budget_scope(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Engineering's current "
                "people budget."
            ),
            metrics=[
                "total_approved_people_budget",
                "total_actual_people_cost",
                "remaining_people_budget",
                "budget_utilization_percentage",
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

    assert (
        values[
            "total_approved_people_budget"
        ]
        == 12331483
    )

    assert (
        values[
            "total_actual_people_cost"
        ]
        == 10174061
    )

    assert (
        values[
            "remaining_people_budget"
        ]
        == 2157422
    )

    assert (
        values[
            "budget_utilization_percentage"
        ]
        == 82.5
    )


def test_business_unit_budget_breakdown(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show approved people budget "
                "by business unit."
            ),
            metrics=[
                "total_approved_people_budget",
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

    total_budget = sum(
        int(
            record[
                "total_approved_people_budget"
            ]
        )
        for record in result.records
    )

    assert total_budget == 185365289


def test_unknown_budget_department(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the budget for an unknown "
                "department."
            ),
            metrics=[
                "total_approved_people_budget",
            ],
            scope=HeadcountScope(
                department="Unknown Department",
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.NOT_FOUND
    )