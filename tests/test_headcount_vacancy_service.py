"""Tests for deterministic detailed vacancy analysis."""

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
    FilterOperator,
    HeadcountAnalysisType,
    HeadcountFilter,
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


def test_current_vacancy_summary(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the current detailed vacancy summary."
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "vacant_position_count",
                "frozen_position_count",
                "vacant_approved_position_count",
                "funded_vacant_position_count",
                "unfunded_vacant_position_count",
                "long_open_vacancy_count",
                "critical_open_position_count",
                "average_vacancy_age_in_days",
                "overdue_vacancy_count",
                "vacancy_rate_percentage",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["vacant_position_count"] == 74
    assert values["frozen_position_count"] == 6

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

    assert values["long_open_vacancy_count"] == 63

    assert (
        values["critical_open_position_count"]
        == 37
    )

    assert (
        values["average_vacancy_age_in_days"]
        == 263.01
    )

    assert values["overdue_vacancy_count"] == 58
    assert values["vacancy_rate_percentage"] == 10.04


def test_funded_high_priority_old_vacancies(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show funded high-priority vacancies "
                "open for at least 90 days."
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "vacant_approved_position_count",
            ],
            filters=[
                HeadcountFilter(
                    field="budgeted_position",
                    operator=FilterOperator.EQUALS,
                    value="Yes",
                ),
                HeadcountFilter(
                    field="position_criticality",
                    operator=FilterOperator.IN,
                    value=["High", "Critical"],
                ),
                HeadcountFilter(
                    field="vacancy_age_in_days",
                    operator=(
                        FilterOperator
                        .GREATER_THAN_OR_EQUAL
                    ),
                    value=90,
                ),
            ],
            top_n=30,
        )
    )

    values = metric_values(result)

    assert (
        values["vacant_approved_position_count"]
        == 23
    )

    assert len(result.records) == 23


def test_recruitment_stage_breakdown(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show open vacancies by recruitment stage."
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "vacant_approved_position_count",
            ],
            group_by=[
                "recruitment_stage",
            ],
            top_n=10,
        )
    )

    stage_counts = {
        record["recruitment_stage"]:
            record[
                "vacant_approved_position_count"
            ]
        for record in result.records
    }

    assert stage_counts == {
        "Offer Stage": 52,
        "Sourcing Candidates": 17,
        "Position Frozen": 6,
        "Interview Stage": 5,
    }


def test_department_with_most_open_positions(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which department has the most "
                "open positions?"
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "vacant_approved_position_count",
            ],
            group_by=[
                "department",
            ],
            sort_by=(
                "vacant_approved_position_count"
            ),
            top_n=1,
        )
    )

    assert len(result.records) == 1

    record = result.records[0]

    assert (
        record["department"]
        == "Production & Manufacturing"
    )

    assert (
        record["vacant_approved_position_count"]
        == 11
    )


def test_oldest_open_vacancy(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which position has been vacant longest?"
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "vacancy_age_in_days",
            ],
            group_by=[
                "position",
            ],
            sort_by="vacancy_age_in_days",
            top_n=1,
        )
    )

    assert len(result.records) == 1

    record = result.records[0]

    assert record["position_id"] == "POS-708"
    assert record["vacancy_age_in_days"] == 546


def test_average_completed_time_to_fill(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "What was the average time to fill "
                "completed vacancies?"
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "average_time_to_fill_in_days",
            ],
        )
    )

    values = metric_values(result)

    assert (
        values["average_time_to_fill_in_days"]
        == 96.01
    )


def test_engineering_vacancy_details(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Engineering vacancy details."
            ),
            analysis_type=HeadcountAnalysisType.VACANCY,
            metrics=[
                "vacant_approved_position_count",
                "funded_vacant_position_count",
                "long_open_vacancy_count",
                "critical_open_position_count",
            ],
            scope=HeadcountScope(
                department="Engineering",
            ),
        )
    )

    values = metric_values(result)

    assert (
        values["vacant_approved_position_count"]
        == 9
    )

    assert (
        values["funded_vacant_position_count"]
        == 6
    )

    assert values["long_open_vacancy_count"] == 6

    assert (
        values["critical_open_position_count"]
        == 3
    )
    