from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CasePriority = Literal["Critical", "High", "Medium", "Low"]
CaseStatus = Literal["Open", "Under Review", "In Progress", "Resolved", "Closed"]


class DecisionCaseDraft(BaseModel):
    """One deterministic case produced by the trigger engine."""

    case_key: str
    rule_id: str
    case_type: str
    subject_type: Literal["Employee", "Organization", "Department", "Position"]
    subject_id: str
    employee_id: str | None = None
    position_id: str | None = None
    department_id: str | None = None
    department: str | None = None
    priority: CasePriority
    display_rank: int = Field(default=100, ge=1)
    title: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str
    data_as_of: date | None = None


class DecisionCaseRecord(DecisionCaseDraft):
    id: str
    status: CaseStatus = "Open"
    is_trigger_active: bool = True
    detected_at: datetime
    last_evaluated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None


class DecisionCaseEvaluationResult(BaseModel):
    status: Literal["success"] = "success"
    evaluated_at: datetime
    detected_case_count: int
    actionable_case_count: int
    dashboard_case_count: int
    dashboard_limit: int
    cases: list[DecisionCaseRecord]
    note: str = (
        "Only the highest-priority active cases are returned for the HR dashboard. "
        "The engine is decision support only and does not change employee records."
    )


class DecisionCaseStatusUpdate(BaseModel):
    status: CaseStatus


class DecisionCaseQueryResult(BaseModel):
    status: Literal["success", "not_found", "unsupported", "error"]
    count: int = 0
    total_matching: int = 0
    cases: list[DecisionCaseRecord] = Field(default_factory=list)
    message: str | None = None
