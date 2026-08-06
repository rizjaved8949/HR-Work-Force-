"""Tests for Headcount history and workforce movement analysis."""

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
    HeadcountAnalysisType,
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


def test_six_month_headcount_trend(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the Headcount trend for "
                "the last six months."
            ),
            metrics=[
                "actual_employee_count",
            ],
            date_range=HeadcountDateRange(
                start_date=date(2026, 3, 1),
                end_date=date(2026, 8, 1),
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 6

    assert (
        result.records[-1][
            "actual_employee_count"
        ]
        == 720
    )


def test_latest_historical_vacancy_rate(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the vacancy-rate trend."
            ),
            metrics=[
                "vacancy_rate_percentage",
            ],
            date_range=HeadcountDateRange(
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
            ),
        )
    )

    values = metric_values(result)

    assert (
        values["vacancy_rate_percentage"]
        == 10.04
    )


def test_movement_counts_for_six_months(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show workforce movements during "
                "the last six months."
            ),
            analysis_type=(
                HeadcountAnalysisType.MOVEMENT
            ),
            metrics=[
                "joiner_count",
                "leaver_count",
                "promotion_count",
                "transfer_count",
            ],
            date_range=HeadcountDateRange(
                start_date=date(2026, 3, 1),
                end_date=date(2026, 8, 1),
            ),
        )
    )

    values = metric_values(result)

    assert values["joiner_count"] == 160
    assert values["leaver_count"] == 129
    assert values["promotion_count"] == 131
    assert values["transfer_count"] == 26


def test_engineering_joiners(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "How many employees joined Engineering "
                "during the last six months?"
            ),
            analysis_type=(
                HeadcountAnalysisType.MOVEMENT
            ),
            metrics=[
                "joiner_count",
            ],
            scope=HeadcountScope(
                department="Engineering",
            ),
            date_range=HeadcountDateRange(
                start_date=date(2026, 3, 1),
                end_date=date(2026, 8, 1),
            ),
        )
    )

    values = metric_values(result)

    assert values["joiner_count"] == 10


def test_future_movements_are_excluded(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "How many employees have joined?"
            ),
            analysis_type=(
                HeadcountAnalysisType.MOVEMENT
            ),
            metrics=[
                "joiner_count",
            ],
        )
    )

    values = metric_values(result)

    assert values["joiner_count"] == 679