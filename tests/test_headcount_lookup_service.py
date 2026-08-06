"""Tests for employee and position Headcount lookups."""

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


def test_employee_lookup_by_id(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Which position does EMP004 occupy?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert len(result.records) == 1

    employee = result.records[0]

    assert employee["employee_id"] == "EMP004"
    assert employee["employee_name"] == "Ali Masood"

    assert (
        employee["position_title"]
        == "Financial Analyst"
    )

    assert employee["department"] == "Finance"

    assert (
        employee["business_unit"]
        == "Corporate Services"
    )

    assert (
        employee["manager_employee_id"]
        == "EMP231"
    )

    assert employee["manager_name"] == "Ayesha Aziz"

    assert (
        employee["organizational_unit_name"]
        == "Finance Team 2"
    )

    assert (
        employee["work_location_name"]
        == "Corporate Headquarters"
    )

    assert (
        employee["included_in_approved_headcount"]
        == "Yes"
    )


def test_employee_lookup_by_name(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the Headcount details of Ali Masood."
            ),
            scope=HeadcountScope(
                employee_name="Ali Masood",
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    assert (
        result.records[0]["employee_id"]
        == "EMP004"
    )


def test_vacant_position_lookup(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show the details of position POS-705."
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    position = result.records[0]

    assert position["position_id"] == "POS-705"

    assert (
        position["position_title"]
        == "Accounts Assistant"
    )

    assert position["position_status"] == "Vacant"
    assert position["approved_position"] == "Yes"
    assert position["budgeted_position"] == "Yes"

    assert position["current_employee_id"] is None

    assert (
        position["vacancy_age_in_days"]
        == 334
    )


def test_filled_position_lookup(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Who currently occupies POS-004?"
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.SUCCESS
    )

    position = result.records[0]

    assert position["position_status"] == "Filled"

    assert (
        position["current_employee_id"]
        == "EMP004"
    )

    assert (
        position["current_employee_name"]
        == "Ali Masood"
    )


def test_unknown_employee_returns_not_found(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question=(
                "Show Headcount details for EMP9999."
            )
        )
    )

    assert result.status == (
        HeadcountResultStatus.NOT_FOUND
    )


def test_lookup_without_entity_is_invalid(
    service: HeadcountService,
) -> None:
    result = service.analyze(
        AnalyzeHeadcountInput(
            question="Show an employee lookup.",
            analysis_type=(
                HeadcountAnalysisType.EMPLOYEE_LOOKUP
            ),
        )
    )

    assert result.status == (
        HeadcountResultStatus.INVALID_REQUEST
    )