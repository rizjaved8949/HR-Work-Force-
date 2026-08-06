"""Tests for the Headcount metric and dimension registry."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


from headcount.metric_registry import (
    DIMENSIONS,
    METRICS,
    get_dimension_definition,
    get_metric_definition,
    list_dimension_names,
    list_metric_names,
    resolve_dimension_name,
    resolve_metric_name,
)
from headcount.repository import TABLE_SPECIFICATIONS


def test_core_metrics_exist() -> None:
    expected_metrics = {
        "actual_employee_count",
        "approved_position_count",
        "budgeted_position_count",
        "vacant_approved_position_count",
        "funded_vacant_position_count",
        "vacancy_rate_percentage",
        "budget_utilization_percentage",
        "monthly_net_workforce_change",
        "workforce_availability_percentage",
    }

    assert expected_metrics.issubset(
        set(list_metric_names())
    )


def test_metric_alias_resolution() -> None:
    assert (
        resolve_metric_name("current headcount")
        == "actual_employee_count"
    )

    assert (
        resolve_metric_name("funded vacancies")
        == "funded_vacant_position_count"
    )

    assert (
        resolve_metric_name("budget usage")
        == "budget_utilization_percentage"
    )

    assert (
        resolve_metric_name("vacancy rate")
        == "vacancy_rate_percentage"
    )


def test_dimension_alias_resolution() -> None:
    assert (
        resolve_dimension_name("dept")
        == "department"
    )

    assert (
        resolve_dimension_name("office")
        == "work_location"
    )

    assert (
        resolve_dimension_name("hiring stage")
        == "recruitment_stage"
    )


def test_metric_definition_lookup() -> None:
    definition = get_metric_definition(
        "number of employees"
    )

    assert definition is not None
    assert definition.name == "actual_employee_count"
    assert definition.unit == "employees"
    assert definition.source_tables == ("assignments",)


def test_dimension_column_lookup() -> None:
    definition = get_dimension_definition(
        "department"
    )

    assert definition is not None

    assert (
        definition.column_for("positions")
        == "Department"
    )

    assert (
        definition.column_for("monthly_snapshots")
        == "Department_Name"
    )


def test_registry_source_tables_are_valid() -> None:
    repository_tables = set(
        TABLE_SPECIFICATIONS.keys()
    )

    invalid_sources: list[
        tuple[str, str]
    ] = []

    for metric_name, definition in METRICS.items():
        if definition.external_dependency:
            continue

        for table_name in definition.source_tables:
            if table_name not in repository_tables:
                invalid_sources.append(
                    (
                        metric_name,
                        table_name,
                    )
                )

        if (
            definition.historical_table is not None
            and definition.historical_table
            not in repository_tables
        ):
            invalid_sources.append(
                (
                    metric_name,
                    definition.historical_table,
                )
            )

    assert invalid_sources == []


def test_external_attrition_metric_is_marked() -> None:
    definition = get_metric_definition(
        "expected employee exits"
    )

    assert definition is not None
    assert definition.external_dependency is True
    assert definition.operation == "external"
    assert definition.source_tables == ()


def test_registry_names_are_unique() -> None:
    assert len(METRICS) == len(
        set(METRICS.keys())
    )

    assert len(DIMENSIONS) == len(
        set(DIMENSIONS.keys())
    )

    assert len(list_dimension_names()) == len(
        DIMENSIONS
    )