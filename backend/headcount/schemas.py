"""Pydantic schemas used by the Headcount reasoning pipeline.

These schemas define:

1. What the existing HR agent sends to the Headcount tool.
2. The safe calculation plan used by the Headcount service.
3. The structured evidence returned to the HR agent.

No Attrition or replacement schema is modified here.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


# ============================================================
# SHARED BASE MODEL
# ============================================================

class HeadcountBaseModel(BaseModel):
    """Base configuration for all Headcount schemas."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


# ============================================================
# ENUMS
# ============================================================

class HeadcountAnalysisType(str, Enum):
    """High-level type of Headcount analysis requested."""

    OVERVIEW = "overview"
    METRIC = "metric"
    BREAKDOWN = "breakdown"
    RANKING = "ranking"
    COMPARISON = "comparison"
    TREND = "trend"
    DETAIL_LIST = "detail_list"
    EMPLOYEE_LOOKUP = "employee_lookup"
    POSITION_LOOKUP = "position_lookup"
    VACANCY = "vacancy"
    BUDGET = "budget"
    MOVEMENT = "movement"
    AVAILABILITY = "availability"
    EXCEPTION = "exception"
    DEFINITION = "definition"
    RULE = "rule"
    COMBINED = "combined"
   


class FilterOperator(str, Enum):
    """Supported safe filtering operations."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    CONTAINS = "contains"
    BETWEEN = "between"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class SortDirection(str, Enum):
    """Supported result sorting directions."""

    ASCENDING = "ascending"
    DESCENDING = "descending"


class HeadcountResultStatus(str, Enum):
    """Possible Headcount tool execution outcomes."""

    SUCCESS = "success"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    INVALID_REQUEST = "invalid_request"
    ERROR = "error"


# ============================================================
# TYPE ALIASES
# ============================================================

ScalarValue = str | int | float | bool | date

FilterValue = (
    ScalarValue
    | list[ScalarValue]
    | None
)


# ============================================================
# FILTER AND DATE SCHEMAS
# ============================================================

class HeadcountFilter(HeadcountBaseModel):
    """One safe filter applied during Headcount analysis."""

    field: str = Field(
        min_length=1,
        description=(
            "Canonical Headcount field or dimension name, such as "
            "department, job_level, vacancy_age_in_days, "
            "position_criticality or budget_utilization_percentage."
        ),
    )

    operator: FilterOperator = Field(
        default=FilterOperator.EQUALS,
        description="Operation used to apply the filter.",
    )

    value: FilterValue = Field(
        default=None,
        description=(
            "Filter value. Use a list for in, not_in or between. "
            "For is_null and is_not_null, no value is required."
        ),
    )

    case_sensitive: bool = Field(
        default=False,
        description=(
            "Whether text comparison should be case-sensitive."
        ),
    )

    @model_validator(mode="after")
    def validate_operator_value(self) -> "HeadcountFilter":
        """Validate that operator and value are compatible."""

        no_value_operators = {
            FilterOperator.IS_NULL,
            FilterOperator.IS_NOT_NULL,
        }

        list_operators = {
            FilterOperator.IN,
            FilterOperator.NOT_IN,
        }

        if self.operator in no_value_operators:
            self.value = None
            return self

        if self.value is None:
            raise ValueError(
                f"A value is required for operator "
                f"{self.operator.value!r}."
            )

        if self.operator in list_operators:
            if not isinstance(self.value, list):
                raise ValueError(
                    f"Operator {self.operator.value!r} "
                    "requires a list value."
                )

            if not self.value:
                raise ValueError(
                    f"Operator {self.operator.value!r} "
                    "requires at least one value."
                )

        if self.operator == FilterOperator.BETWEEN:
            if (
                not isinstance(self.value, list)
                or len(self.value) != 2
            ):
                raise ValueError(
                    "The between operator requires exactly "
                    "two values."
                )

        if self.operator == FilterOperator.CONTAINS:
            if not isinstance(self.value, str):
                raise ValueError(
                    "The contains operator requires a text value."
                )

        return self


class HeadcountDateRange(HeadcountBaseModel):
    """Optional reporting period requested by the user."""

    start_date: date | None = Field(
        default=None,
        description="Beginning of the requested reporting period.",
    )

    end_date: date | None = Field(
        default=None,
        description="End of the requested reporting period.",
    )

    period_label: str | None = Field(
        default=None,
        description=(
            "Original period description, such as last six months, "
            "last quarter, current month or year to date."
        ),
    )

    @model_validator(mode="after")
    def validate_date_order(self) -> "HeadcountDateRange":
        """Ensure the start date does not follow the end date."""

        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError(
                "start_date cannot be later than end_date."
            )

        return self


# ============================================================
# OPTIONAL QUERY SCOPE
# ============================================================

class HeadcountScope(HeadcountBaseModel):
    """Entities explicitly mentioned in a Headcount question."""

    employee_id: str | None = Field(
        default=None,
        description="Employee ID, such as EMP004.",
    )
    employee_name: str | None = Field(
        default=None,
        description="Employee name, such as Ali Masood.",
    )
    position_id: str | None = Field(
        default=None,
        description="Position ID, such as POS-705.",
    )
    position_title: str | None = Field(
    default=None,
    description=(
        "Position title, such as Financial Analyst."
    ),
)

    department: str | None = Field(
        default=None,
        description="Department name or department ID.",
    )

    business_unit: str | None = Field(
        default=None,
        description="Business-unit name or ID.",
    )

    organizational_unit: str | None = Field(
        default=None,
        description="Team or organizational-unit name or ID.",
    )

    work_location: str | None = Field(
        default=None,
        description="Work-location name or ID.",
    )

    job_level: str | None = Field(
        default=None,
        description=(
            "Job level such as Intern, Junior, Mid, Senior, "
            "Lead/Manager or Executive."
        ),
    )

    employment_type: str | None = Field(
        default=None,
        description=(
            "Employment type such as Permanent, Contract "
            "or Internship."
        ),
    )

    employee_status: str | None = Field(
        default=None,
        description="Employee status such as Active or Probation.",
    )

    work_mode: str | None = Field(
        default=None,
        description="Work mode such as On-site, Hybrid or Remote.",
    )

    position_status: str | None = Field(
        default=None,
        description=(
            "Position status such as Filled, Vacant or Frozen."
        ),
    )
    career_level: str | None = Field(
        default=None,
        description=(
            "Career level such as Entry Level, Professional, "
            "Senior Professional, Management or Executive."
        ),
    )

    shift_type: str | None = Field(
        default=None,
        description=(
            "Employee shift such as Day, Night, Evening "
            "or Rotational."
        ),
    )

    cost_center: str | None = Field(
        default=None,
        description="Cost-center name or cost-center ID.",
    )

    employee_category: str | None = Field(
        default=None,
        description=(
            "Employee category such as Regular Employee, "
            "Contract Employee or Intern."
        ),
    )

    headcount_inclusion_category: str | None = Field(
        default=None,
        description=(
            "Headcount category such as Regular Headcount, "
            "Contract Headcount or Internship Headcount."
        ),
    )

    included_in_approved_headcount: str | None = Field(
        default=None,
        description=(
            "Whether the employee is included in approved "
            "Headcount: Yes or No."
        ),
    )

    position_criticality: str | None = Field(
        default=None,
        description=(
            "Position criticality such as Low, Medium, High "
            "or Critical."
        ),
    )


# ============================================================
# TOOL INPUT
# ============================================================

class AnalyzeHeadcountInput(HeadcountBaseModel):
    """Input accepted by the single Headcount analysis tool.

    Only question is mandatory. The existing reasoning LLM may add
    structured fields when the user's intent is clear.

    Keeping the original question allows combined and previously
    unseen Headcount questions to remain supported.
    """

    question: str = Field(
        min_length=3,
        description=(
            "The user's complete Headcount Management question. "
            "Preserve all requested filters, comparisons and periods."
        ),
    )

    analysis_type: HeadcountAnalysisType | None = Field(
        default=None,
        description=(
            "Optional analysis type inferred by the existing HR agent. "
            "Leave empty when uncertain."
        ),
    )

    metrics: list[str] = Field(
        default_factory=list,
        description=(
            "Requested Headcount metrics, such as "
            "actual_employee_count, vacancy_rate_percentage, "
            "funded_vacancy_count or budget_utilization_percentage."
        ),
    )

    group_by: list[str] = Field(
        default_factory=list,
        description=(
            "Requested grouping dimensions, such as department, "
            "business_unit, work_location or job_level."
        ),
    )

    filters: list[HeadcountFilter] = Field(
        default_factory=list,
        description=(
            "Optional structured filters extracted from the question."
        ),
    )

    date_range: HeadcountDateRange | None = Field(
        default=None,
        description="Optional historical or daily reporting period.",
    )

    scope: HeadcountScope = Field(
        default_factory=HeadcountScope,
        description=(
            "Employee, position, department or other entities "
            "explicitly mentioned in the question."
        ),
    )

    sort_by: str | None = Field(
        default=None,
        description=(
            "Metric or dimension used to sort the output."
        ),
    )

    sort_direction: SortDirection = Field(
        default=SortDirection.DESCENDING,
        description="Requested result sorting direction.",
    )

    top_n: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Maximum number of detailed or ranked records returned."
        ),
    )

    include_details: bool = Field(
        default=True,
        description=(
            "Whether supporting records should be returned with "
            "the calculated summary."
        ),
    )


# ============================================================
# INTERNAL SAFE QUERY PLAN
# ============================================================

class HeadcountQueryPlan(HeadcountBaseModel):
    """Validated internal plan executed by the Headcount service.

    This plan never contains Python code or SQL. It contains only
    approved analytical operations.
    """

    question: str = Field(
        min_length=3,
        description="Original user question.",
    )

    analysis_type: HeadcountAnalysisType = Field(
        description="Resolved analysis operation.",
    )

    metrics: list[str] = Field(
        default_factory=list,
        description="Canonical metrics to calculate.",
    )

    group_by: list[str] = Field(
        default_factory=list,
        description="Canonical dimensions used for aggregation.",
    )

    filters: list[HeadcountFilter] = Field(
        default_factory=list,
        description="Validated filters applied to source data.",
    )

    date_range: HeadcountDateRange | None = None

    scope: HeadcountScope = Field(
        default_factory=HeadcountScope,
    )

    sort_by: str | None = None

    sort_direction: SortDirection = (
        SortDirection.DESCENDING
    )

    limit: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    include_details: bool = True

    requested_source_tables: list[str] = Field(
        default_factory=list,
        description=(
            "Repository table names required to execute the plan."
        ),
    )


# ============================================================
# TOOL OUTPUT
# ============================================================

class HeadcountMetricResult(HeadcountBaseModel):
    """One exact metric calculated by the Headcount service."""

    metric_name: str = Field(
        min_length=1,
        description="Canonical metric name.",
    )

    display_name: str = Field(
        min_length=1,
        description="Human-readable metric name.",
    )

    value: ScalarValue | None = Field(
        default=None,
        description="Exact calculated value.",
    )

    unit: str | None = Field(
        default=None,
        description=(
            "Optional unit, such as employees, positions, "
            "percentage, PKR, days or hours."
        ),
    )

    numerator: float | int | None = Field(
        default=None,
        description=(
            "Optional numerator used in the calculation."
        ),
    )

    denominator: float | int | None = Field(
        default=None,
        description=(
            "Optional denominator used in the calculation."
        ),
    )


class HeadcountToolResult(HeadcountBaseModel):
    """Structured evidence returned to the existing HR agent."""

    status: HeadcountResultStatus

    question: str

    analysis_type: HeadcountAnalysisType | None = None

    message: str | None = Field(
        default=None,
        description=(
            "Short execution message, especially for unsupported, "
            "invalid or not-found requests."
        ),
    )

    resolved_scope: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Resolved department, employee, position, location "
            "or period used in the calculation."
        ),
    )

    metrics: list[HeadcountMetricResult] = Field(
        default_factory=list,
        description="Exact calculated Headcount metrics.",
    )

    records: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Supporting ranked, grouped or detailed records."
        ),
    )

    evidence_sources: list[str] = Field(
        default_factory=list,
        description=(
            "CSV files used to calculate the answer."
        ),
    )

    data_as_of_date: date | None = Field(
        default=None,
        description="Latest reporting date represented by the result.",
    )

    calculation_notes: list[str] = Field(
        default_factory=list,
        description=(
            "Short explanations of deterministic calculations."
        ),
    )

    limitations: list[str] = Field(
        default_factory=list,
        description=(
            "Data limitations or unsupported parts of the request."
        ),
    )