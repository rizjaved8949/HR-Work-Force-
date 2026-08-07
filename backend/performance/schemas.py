"""Pydantic contracts for deterministic Employee Performance analytics.

The Performance module is intentionally isolated from Attrition, Replacement,
and Headcount. It reads the shared Data folder but never modifies source files.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PerformanceBaseModel(BaseModel):
    """Shared strict model configuration."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class PerformanceAnalysisType(str, Enum):
    """Supported high-level analysis requests."""

    OVERVIEW = "overview"
    EMPLOYEE = "employee"
    EMPLOYEE_TREND = "employee_trend"
    KPI_BREAKDOWN = "kpi_breakdown"
    DEPARTMENT_RANKING = "department_ranking"
    DISTRIBUTION = "distribution"
    ATTENTION = "attention"
    LEARNING = "learning"
    RECOMMENDATIONS = "recommendations"
    RECALCULATE = "recalculate"


class PerformanceResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class PerformanceDateRange(PerformanceBaseModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_order(self) -> "PerformanceDateRange":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date cannot be later than end_date")
        return self


class AnalyzePerformanceInput(PerformanceBaseModel):
    """Input accepted by the direct Performance pipeline and agent adapter."""

    question: str = Field(
        min_length=3,
        description="Complete natural-language Employee Performance question.",
    )
    analysis_type: PerformanceAnalysisType | None = None
    employee_id: str | None = None
    employee_name: str | None = None
    department: str | None = None
    role_band: str | None = None
    month: date | None = None
    months: int = Field(default=12, ge=1, le=24)
    limit: int = Field(default=20, ge=1, le=100)
    include_learning: bool = True


class MetricValue(PerformanceBaseModel):
    metric_name: str
    display_name: str
    value: str | int | float | bool | None
    unit: str | None = None


class PerformanceToolResult(PerformanceBaseModel):
    """Common structured response for Performance analysis."""

    status: PerformanceResultStatus
    analysis_type: PerformanceAnalysisType
    question: str | None = None
    message: str
    metrics: list[MetricValue] = Field(default_factory=list)
    records: list[dict[str, Any]] = Field(default_factory=list)
    employee: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    learning_history: list[dict[str, Any]] = Field(default_factory=list)
    data_as_of_date: str | None = None
    limitations: list[str] = Field(default_factory=list)
    calculation_notes: list[str] = Field(default_factory=list)
