"""Pydantic contracts for the Scenario Simulation layer.

Step 2 keeps HTTP integration separate. These schemas are used by the
simulation service now and can later be reused directly by a FastAPI router.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ScenarioType(str, Enum):
    EMPLOYEE_PROMOTION = "employee_promotion"
    EMPLOYEE_TRANSFER = "employee_transfer"
    HEADCOUNT_REDUCTION = "headcount_reduction"
    WORKFORCE_EXPANSION = "workforce_expansion"
    BUDGET_CHANGE = "budget_change"
    SKILL_RESKILLING = "skill_reskilling"
    BUSINESS_DEMAND_CHANGE = "business_demand_change"


class SimulationRequest(BaseModel):
    scenario_type: ScenarioType
    employee_id: str | None = Field(default=None, min_length=1)
    department_id: str | None = Field(default=None, min_length=1)
    target_position_id: str | None = Field(default=None, min_length=1)
    target_department_id: str | None = Field(default=None, min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class SimulationResponse(BaseModel):
    scenario_type: ScenarioType
    status: str
    baseline: dict[str, Any]
    simulated_state: dict[str, Any]
    impact: dict[str, Any]
    assumptions: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
