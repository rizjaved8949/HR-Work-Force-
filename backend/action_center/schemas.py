"""Pydantic contracts for Action Center REST APIs and agent tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ActionActor(BaseModel):
    user_id: str
    name: str | None = None
    email: str | None = None
    role: str | None = None


class ActionCenterQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mode: Literal[
        "summary",
        "processes",
        "process_detail",
        "process_options",
        "records",
        "activity",
        "employee_history",
        "employee_state",
    ] = "summary"
    process_code: str | None = None
    employee_id: str | None = None
    employee_name: str | None = None
    status: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ActionPreviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    employee_id: str | None = None
    employee_name: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class ActionExecuteRequest(ActionPreviewRequest):
    """REST write contract.

    The REST execute route is itself an explicit write action. The LLM tool has
    an additional conversational preview/confirmation gate in tools.py.
    """


class ActionRecordUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updates: dict[str, Any] = Field(default_factory=dict)


class ApplyDueRequest(BaseModel):
    record_ids: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class AgentPerformActionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    process_code: str | None = Field(
        default=None,
        description=(
            "One supported Action Center process code, for example TRANSFER, "
            "PROMOTION, PROB_CONFIRM, RESIGNATION, or FINAL_SETTLEMENT."
        ),
    )
    employee_id: str | None = None
    employee_name: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = Field(
        default=False,
        description=(
            "False creates a validated preview and stores it as the pending "
            "action. True executes the pending action after the HR user confirms."
        ),
    )


class AgentUpdateActionRecordInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    action_record_id: str | None = None
    updates: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
