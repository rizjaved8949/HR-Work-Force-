"""Tests for Headcount exceptions, definitions, and rules."""

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
    HeadcountAnalysisType,
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


def test_exception_summary(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the current Headcount "
                "exception summary."
            ),
            metrics=[
                "open_exception_count",
                "critical_exception_count",
                "warning_exception_count",
            ],
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["open_exception_count"] == 30

    assert (
        values["critical_exception_count"]
        == 15
    )

    assert (
        values["warning_exception_count"]
        == 15
    )


def test_engineering_exceptions(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Engineering Headcount exceptions."
            ),
            analysis_type=(
                HeadcountAnalysisType.EXCEPTION
            ),
            metrics=[
                "open_exception_count",
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

    assert values["open_exception_count"] == 2
    assert len(result.records) == 2

    exception_types = {
        record["exception_type"]
        for record in result.records
    }

    assert exception_types == {
        "Long-Open Vacancies",
        "Understaffing",
    }


def test_department_with_most_exceptions(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which department has the most "
                "open Headcount exceptions?"
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

    assert record["open_exception_count"] == 4


def test_vacancy_rate_definition(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "How is the vacancy rate calculated?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 1

    definition = result.records[0]

    assert (
        definition["canonical_metric_name"]
        == "vacancy_rate_percentage"
    )

    assert (
        "Vacant Approved Position Count"
        in definition["calculation_logic"]
    )

    assert (
        "Approved Position Count"
        in definition["calculation_logic"]
    )


def test_engineering_applicable_rules(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "What Headcount rules apply "
                "to Engineering?"
            ),
            scope=HeadcountScope(
                department="Engineering",
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["active_rule_count"] == 7
    assert len(result.records) == 7

    rule_ids = {
        record["rule_id"]
        for record in result.records
    }

    assert "RULE-001" in rule_ids
    assert "RULE-010" in rule_ids


def test_critical_rules(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show all critical Headcount rules."
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    values = metric_values(result)

    assert values["active_rule_count"] == 7
    assert len(result.records) == 7

    assert all(
        record["severity"] == "Critical"
        for record in result.records
    )