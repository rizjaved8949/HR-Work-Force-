"""Safe query planner for Headcount Management.

The planner converts AnalyzeHeadcountInput into a validated
HeadcountQueryPlan.

It does not:
- execute pandas calculations;
- generate Python or SQL;
- call a second LLM;
- modify Attrition or replacement pipelines.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from headcount.metric_registry import (
    DIMENSION_ALIAS_INDEX,
    DIMENSIONS,
    METRIC_ALIAS_INDEX,
    METRICS,
    normalize_registry_term,
    resolve_dimension_name,
    resolve_metric_name,
)
from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountAnalysisType,
    HeadcountFilter,
    HeadcountQueryPlan,
    HeadcountScope,
    SortDirection,
)


class HeadcountPlanningError(ValueError):
    """Raised when a safe Headcount plan cannot be created."""


# Special filter fields that are safe but are not always dimensions.
SAFE_FILTER_FIELDS: Final[set[str]] = {
    "approved_position",
    "budgeted_position",
    "included_in_approved_headcount",
    "assignment_status",
    "active_status",
    "vacancy_age_in_days",
    "vacancy_status",
    "recruitment_stage",
    "position_status",
    "position_criticality",
    "employee_status",
    "employment_type",
    "job_level",
    "work_mode",
    "movement_type",
    "exception_status",
    "exception_type",
    "severity",
    "activity_date",
    "snapshot_month",
    "budget_month",
    "data_as_of_date",
}


FILTER_FIELD_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "approved_position": ("positions",),
    "budgeted_position": (
        "positions",
        "vacancy_history",
        "position_budgets",
    ),
    "included_in_approved_headcount": ("employees",),
    "assignment_status": ("assignments",),
    "active_status": (
        "business_units",
        "departments",
        "work_locations",
        "cost_centers",
    ),
    "vacancy_age_in_days": ("vacancy_history",),
    "vacancy_status": ("vacancy_history",),
    "recruitment_stage": ("vacancy_history",),
    "position_status": (
        "positions",
        "position_budgets",
    ),
    "position_criticality": (
        "positions",
        "vacancy_history",
    ),
    "employee_status": ("employees",),
    "employment_type": (
        "employees",
        "assignments",
        "positions",
    ),
    "job_level": (
        "employees",
        "positions",
    ),
    "work_mode": (
        "employees",
        "positions",
    ),
    "movement_type": ("movements",),
    "exception_status": ("exceptions",),
    "exception_type": ("exceptions",),
    "severity": ("exceptions",),
    "activity_date": ("daily_activity",),
    "snapshot_month": ("monthly_snapshots",),
    "budget_month": ("department_budgets",),
    "data_as_of_date": (
        "employees",
        "assignments",
        "current_summary",
        "vacancy_history",
        "monthly_snapshots",
        "department_budgets",
    ),
}


ANALYSIS_DEFAULT_TABLES: Final[
    dict[HeadcountAnalysisType, tuple[str, ...]]
] = {
    HeadcountAnalysisType.EMPLOYEE_LOOKUP: ("employees",),
    HeadcountAnalysisType.POSITION_LOOKUP: ("positions",),
    HeadcountAnalysisType.VACANCY: (
        "positions",
        "vacancy_history",
    ),
    HeadcountAnalysisType.BUDGET: ("department_budgets",),
    HeadcountAnalysisType.MOVEMENT: ("movements",),
    HeadcountAnalysisType.AVAILABILITY: ("daily_activity",),
    HeadcountAnalysisType.EXCEPTION: ("exceptions",),
    HeadcountAnalysisType.DEFINITION: ("metric_definitions",),
}

RULE_TERMS: Final[tuple[str, ...]] = (
    "rule",
    "rules",
    "policy",
    "policies",
    "threshold",
    "thresholds",
    "staffing limit",
    "headcount limit",
    "workforce limit",
    "requirement",
    "requirements",
    "escalation rule",
)
OVERVIEW_METRICS: Final[tuple[str, ...]] = (
    "actual_employee_count",
    "approved_position_count",
    "budgeted_position_count",
    "vacant_position_count",
    "funded_vacant_position_count",
    "vacancy_rate_percentage",
)


RANKING_TERMS: Final[tuple[str, ...]] = (
    "highest",
    "lowest",
    "largest",
    "smallest",
    "most",
    "least",
    "top",
    "bottom",
    "rank",
    "ranking",
)


TREND_TERMS: Final[tuple[str, ...]] = (
    "trend",
    "over time",
    "history",
    "historical",
    "during the last",
    "in the last",
    "last month",
    "last quarter",
    "last year",
    "year to date",
    "month over month",
    "monthly change",
)


COMPARISON_TERMS: Final[tuple[str, ...]] = (
    "compare",
    "comparison",
    "versus",
    " vs ",
    "difference between",
)


DEFINITION_TERMS: Final[tuple[str, ...]] = (
    "define",
    "definition of",
    "what does",
    "what is meant by",
    "how is",
    "how do you calculate",
    "calculation formula",
)


# Broad workforce vocabulary. These are too generic to select a metric on
# their own, but their presence still means the question is about the
# workforce, so a plain "give me an overview" keeps working while an
# unrelated question or a typo does not silently get an overview.
GENERAL_HEADCOUNT_TERMS: Final[tuple[str, ...]] = (
    "headcount",
    "head count",
    "employee",
    "employees",
    "staff",
    "staffing",
    "workforce",
    "people",
    "position",
    "positions",
    "vacancy",
    "vacancies",
    "budget",
    "organization",
    "organisation",
    "department",
    "business unit",
    "overview",
    "summary",
    "snapshot",
    "hiring",
    "attrition",
    "exception",
    "movement",
    "joiner",
    "leaver",
    "availability",
    "available",
    "attendance",
    "present",
    "absent",
    "leave",
    "on duty",
    "roster",
    "shift",
    "vacant",
    "filled",
    "approved",
    "frozen",
    "recruitment",
    "rule",
    "policy",
)


def _unique(values: list[str]) -> list[str]:
    """Return values in their original order without duplicates."""

    return list(dict.fromkeys(values))


def _find_alias_matches(
    question: str,
    alias_index: dict[str, str],
) -> list[str]:
    """Find canonical terms mentioned inside a question."""

    normalized_question = (
        f"_{normalize_registry_term(question)}_"
    )

    matches: list[str] = []

    sorted_aliases = sorted(
        alias_index.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for normalized_alias, canonical_name in sorted_aliases:
        alias_pattern = f"_{normalized_alias}_"

        if alias_pattern in normalized_question:
            matches.append(canonical_name)

    return _unique(matches)


def _canonicalize_list(
    values: list[str],
    resolver: Callable[[str], str | None],
    label: str,
) -> list[str]:
    """Resolve names and reject unsupported values."""

    resolved_values: list[str] = []
    unsupported_values: list[str] = []

    for value in values:
        resolved = resolver(value)

        if resolved is None:
            unsupported_values.append(value)
        else:
            resolved_values.append(resolved)

    if unsupported_values:
        raise HeadcountPlanningError(
            f"Unsupported {label}: "
            f"{', '.join(unsupported_values)}"
        )

    return _unique(resolved_values)


def _canonicalize_filter(
    filter_item: HeadcountFilter,
) -> HeadcountFilter:
    """Resolve and validate one filter field."""

    metric_name = resolve_metric_name(
        filter_item.field
    )

    dimension_name = resolve_dimension_name(
        filter_item.field
    )

    normalized_field = normalize_registry_term(
        filter_item.field
    )

    canonical_field = (
        metric_name
        or dimension_name
        or normalized_field
    )

    if (
        canonical_field not in SAFE_FILTER_FIELDS
        and canonical_field not in METRICS
        and canonical_field not in DIMENSIONS
    ):
        raise HeadcountPlanningError(
            f"Unsupported filter field: "
            f"{filter_item.field!r}"
        )

    return filter_item.model_copy(
        update={"field": canonical_field}
    )


def _extract_identifiers(
    question: str,
    existing_scope: HeadcountScope,
) -> HeadcountScope:
    """Extract employee and position IDs from the question."""

    updates: dict[str, str] = {}

    if existing_scope.employee_id is None:
        employee_match = re.search(
            r"\bEMP[-_ ]?\d+\b",
            question,
            flags=re.IGNORECASE,
        )

        if employee_match:
            updates["employee_id"] = (
                employee_match.group(0)
                .upper()
                .replace("_", "-")
                .replace(" ", "-")
            )

    if existing_scope.position_id is None:
        position_match = re.search(
            r"\b(?:POS|POSITION)[-_ ]?\d+\b",
            question,
            flags=re.IGNORECASE,
        )

        if position_match:
            updates["position_id"] = (
                position_match.group(0)
                .upper()
                .replace("_", "-")
                .replace(" ", "-")
            )

    if not updates:
        return existing_scope

    return existing_scope.model_copy(update=updates)


def _infer_metrics(question: str) -> list[str]:
    """Infer supported metrics from aliases in the question."""

    normalized = normalize_registry_term(
        question
    )

    # These checks must run before normal alias matching because
    # the phrase "approved headcount" can otherwise be interpreted
    # as approved positions.
    excluded_phrases = (
        "excluded_from_approved_headcount",
        "not_included_in_approved_headcount",
        "outside_approved_headcount",
    )

    if any(
        phrase in normalized
        for phrase in excluded_phrases
    ):
        return [
            "excluded_from_approved_headcount_count"
        ]

    included_phrases = (
        "employees_included_in_approved_headcount",
        "included_in_approved_headcount",
        "inside_approved_headcount",
    )

    if any(
        phrase in normalized
        for phrase in included_phrases
    ):
        return [
            "included_in_approved_headcount_count"
        ]

    workforce_qualifiers = (
        "job_level",
        "career_level",
        "senior_employee",
        "junior_employee",
        "lead_manager",
        "executive_employee",
        "employment_type",
        "permanent_employee",
        "contract_employee",
        "internship_employee",
        "employee_status",
        "probation_employee",
        "work_mode",
        "remote_employee",
        "hybrid_employee",
        "onsite_employee",
        "on_site_employee",
        "shift",
        "work_location",
        "employee_category",
        "headcount_inclusion_category",
        "cost_center",
        "cost_centre",
        "organizational_unit",
    )

    employee_terms = (
        "employee",
        "employees",
        "staff",
        "people",
        "workforce",
        "headcount",
    )

    if (
        any(
            qualifier in normalized
            for qualifier in workforce_qualifiers
        )
        and any(
            employee_term in normalized
            for employee_term in employee_terms
        )
    ):
        return [
            "actual_employee_count"
        ]

    metrics = _find_alias_matches(
        question,
        METRIC_ALIAS_INDEX,
    )

    if not metrics and "headcount" in normalized:
        metrics.append(
            "actual_employee_count"
        )

    return _unique(metrics)


def _infer_dimensions(question: str) -> list[str]:
    """Infer grouping dimensions from the question.

    A dimension becomes a grouping dimension when the user asks:

    - by department
    - across locations
    - per business unit
    - which department has the highest...
    - which location has the lowest...
    """

    dimensions = _find_alias_matches(
        question,
        DIMENSION_ALIAS_INDEX,
    )

    normalized_question = question.lower()

    is_ranking_question = any(
        term in normalized_question
        for term in RANKING_TERMS
    )

    group_dimensions: list[str] = []

    for dimension in dimensions:
        definition = DIMENSIONS[dimension]

        candidate_terms = (
            dimension.replace("_", " "),
            definition.display_name.lower(),
            *definition.aliases,
        )

        explicit_grouping = any(
            (
                f"by {term.lower()}"
                in normalized_question
                or
                f"across {term.lower()}"
                in normalized_question
                or
                f"per {term.lower()}"
                in normalized_question
            )
            for term in candidate_terms
        )

        ranking_dimension = (
            is_ranking_question
            and any(
                (
                    f"which {term.lower()}"
                    in normalized_question
                    or
                    f"what {term.lower()}"
                    in normalized_question
                )
                for term in candidate_terms
            )
        )

        if explicit_grouping or ranking_dimension:
            group_dimensions.append(dimension)

    return _unique(group_dimensions)


def _metric_categories(
    metrics: list[str],
) -> set[str]:
    """Return categories represented by requested metrics."""

    return {
        METRICS[metric_name].category
        for metric_name in metrics
    }


def _infer_analysis_type(
    request: AnalyzeHeadcountInput,
    metrics: list[str],
    group_by: list[str],
    scope: HeadcountScope,
) -> HeadcountAnalysisType:
    """Infer a safe high-level analysis type."""

    if request.analysis_type is not None:
        return request.analysis_type

    question = request.question.lower()
    if any(
        term in question
        for term in RULE_TERMS
    ):
        return HeadcountAnalysisType.RULE
    if any(term in question for term in DEFINITION_TERMS):
        return HeadcountAnalysisType.DEFINITION

    if (
    scope.employee_id is not None
    or scope.employee_name is not None
):
          return HeadcountAnalysisType.EMPLOYEE_LOOKUP

    if (
    scope.position_id is not None
    or scope.position_title is not None
):
           return HeadcountAnalysisType.POSITION_LOOKUP

    categories = _metric_categories(metrics)

    if len(categories) > 1:
        return HeadcountAnalysisType.COMBINED

    if any(term in question for term in RANKING_TERMS):
        return HeadcountAnalysisType.RANKING

    if (
        request.date_range is not None
        or any(term in question for term in TREND_TERMS)
    ):
        return HeadcountAnalysisType.TREND

    if any(term in question for term in COMPARISON_TERMS):
        return HeadcountAnalysisType.COMPARISON

    if group_by:
        return HeadcountAnalysisType.BREAKDOWN

    if categories == {"vacancies"}:
        return HeadcountAnalysisType.VACANCY

    if categories == {"budget"}:
        return HeadcountAnalysisType.BUDGET

    if categories == {"movement"}:
        return HeadcountAnalysisType.MOVEMENT

    if categories == {"availability"}:
        return HeadcountAnalysisType.AVAILABILITY

    if categories == {"exceptions"}:
        return HeadcountAnalysisType.EXCEPTION

    if metrics:
        return HeadcountAnalysisType.METRIC

    return HeadcountAnalysisType.OVERVIEW


def _default_metrics(
    analysis_type: HeadcountAnalysisType,
) -> list[str]:
    """Return sensible metrics when none were provided."""

    defaults: dict[
        HeadcountAnalysisType,
        list[str],
    ] = {
        HeadcountAnalysisType.OVERVIEW: list(
            OVERVIEW_METRICS
        ),
        HeadcountAnalysisType.VACANCY: [
            "vacant_position_count",
            "funded_vacant_position_count",
            "vacancy_rate_percentage",
        ],
        HeadcountAnalysisType.BUDGET: [
            "total_approved_people_budget",
            "total_actual_people_cost",
            "remaining_people_budget",
            "budget_utilization_percentage",
        ],
        HeadcountAnalysisType.MOVEMENT: [
            "joiner_count",
            "leaver_count",
        ],
        HeadcountAnalysisType.AVAILABILITY: [
            "employees_available_for_work",
            "employees_on_approved_leave",
            "employees_absent",
            "workforce_availability_percentage",
        ],
        HeadcountAnalysisType.EXCEPTION: [
            "open_exception_count",
        ],
                HeadcountAnalysisType.RULE: [
            "active_rule_count",
        ],
    }

    return defaults.get(analysis_type, [])


def _source_tables_for_dimension(
    dimension_name: str,
) -> tuple[str, ...]:
    """Return tables containing one registered dimension."""

    definition = DIMENSIONS[dimension_name]

    return tuple(
        table_name
        for table_name, _ in definition.source_columns
    )


def _resolve_source_tables(
    analysis_type: HeadcountAnalysisType,
    metrics: list[str],
    group_by: list[str],
    filters: list[HeadcountFilter],
    use_historical_sources: bool,
) -> list[str]:
    """Determine repository tables required by the plan."""

    source_tables: list[str] = []

    for metric_name in metrics:
        definition = METRICS[metric_name]

        if definition.external_dependency:
            continue

        if (
            use_historical_sources
            and definition.historical_table is not None
        ):
            source_tables.append(
                definition.historical_table
            )
        else:
            source_tables.extend(
                definition.source_tables
            )

    source_tables.extend(
        ANALYSIS_DEFAULT_TABLES.get(
            analysis_type,
            (),
        )
    )

    for dimension_name in group_by:
        dimension_tables = (
            _source_tables_for_dimension(
                dimension_name
            )
        )

        if not any(
            table in source_tables
            for table in dimension_tables
        ):
            if dimension_tables:
                source_tables.append(
                    dimension_tables[0]
                )

    for filter_item in filters:
        if filter_item.field in DIMENSIONS:
            dimension_tables = (
                _source_tables_for_dimension(
                    filter_item.field
                )
            )

            if not any(
                table in source_tables
                for table in dimension_tables
            ):
                if dimension_tables:
                    source_tables.append(
                        dimension_tables[0]
                    )

        elif filter_item.field in METRICS:
            source_tables.extend(
                METRICS[
                    filter_item.field
                ].source_tables
            )

        else:
            source_tables.extend(
                FILTER_FIELD_TABLES.get(
                    filter_item.field,
                    (),
                )
            )

    return _unique(source_tables)


def create_headcount_query_plan(
    request: AnalyzeHeadcountInput,
) -> HeadcountQueryPlan:
    """Create a validated deterministic Headcount query plan."""

    scope = _extract_identifiers(
        request.question,
        request.scope,
    )

    if request.metrics:
        metrics = _canonicalize_list(
            request.metrics,
            resolve_metric_name,
            "metrics",
        )
    else:
        metrics = _infer_metrics(
            request.question
        )

    if request.group_by:
        group_by = _canonicalize_list(
            request.group_by,
            resolve_dimension_name,
            "grouping dimensions",
        )
    else:
        group_by = _infer_dimensions(
            request.question
        )

    filters = [
        _canonicalize_filter(filter_item)
        for filter_item in request.filters
    ]

    analysis_type = _infer_analysis_type(
        request=request,
        metrics=metrics,
        group_by=group_by,
        scope=scope,
    )

    if not metrics:
        metrics = _default_metrics(
            analysis_type
        )

    sort_by: str | None = None

    if request.sort_by:
        sort_by = (
            resolve_metric_name(request.sort_by)
            or resolve_dimension_name(request.sort_by)
        )

        if sort_by is None:
            raise HeadcountPlanningError(
                f"Unsupported sort field: "
                f"{request.sort_by!r}"
            )

    elif analysis_type == HeadcountAnalysisType.RANKING:
        if metrics:
            sort_by = metrics[0]
    sort_direction = request.sort_direction

    lowered_question = request.question.lower()

    if any(
        term in lowered_question
        for term in (
            "lowest",
            "smallest",
            "least",
            "bottom",
        )
    ):
        sort_direction = SortDirection.ASCENDING

    elif any(
        term in lowered_question
        for term in (
            "highest",
            "largest",
            "most",
            "top",
        )
    ):
        sort_direction = SortDirection.DESCENDING
    limit = request.top_n


    # A singular highest/lowest question should return one result
    # unless the user explicitly requested top or bottom N.
    lowered_question = request.question.lower()

    if (
        analysis_type == HeadcountAnalysisType.RANKING
        and any(
            term in lowered_question
            for term in (
                "highest",
                "lowest",
                "largest",
                "smallest",
                "most",
                "least",
            )
        )
        and "top " not in lowered_question
        and "bottom " not in lowered_question
    ):
        limit = 1

    use_historical_sources = (
        request.date_range is not None
        or analysis_type
        == HeadcountAnalysisType.TREND
    )

    source_tables = _resolve_source_tables(
        analysis_type=analysis_type,
        metrics=metrics,
        group_by=group_by,
        filters=filters,
        use_historical_sources=use_historical_sources,
    )

    return HeadcountQueryPlan(
        question=request.question,
        analysis_type=analysis_type,
        metrics=metrics,
        group_by=group_by,
        filters=filters,
        date_range=request.date_range,
        scope=scope,
        sort_by=sort_by,
        sort_direction=sort_direction,
        limit=limit,
        include_details=request.include_details,
        requested_source_tables=source_tables,
    )