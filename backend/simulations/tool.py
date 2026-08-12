"""High-level Scenario Simulation tool for the HR reasoning agent.

This adapter performs deterministic lookup/normalization and delegates every
calculation to the shared SimulationService used by the REST API.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool as stateful_tool
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from .errors import SimulationDataError, SimulationValidationError
from .lookup_service import SimulationLookupService
from .schemas import ScenarioType, SimulationRequest
from .service import SimulationService


SCENARIO_SIMULATION_TOOL_NAME: Final[str] = "scenario_simulation"
SCENARIO_SIMULATION_TOOL_DESCRIPTION: Final[str] = (
    "Run deterministic HR what-if simulations for employee promotion, employee "
    "transfer, headcount reduction, workforce expansion/hiring, budget change, "
    "skill reskilling, and business-demand/workload change. Use this only for "
    "hypothetical future-state questions."
)


class ScenarioSimulationToolInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario_type: ScenarioType
    employee_id: str | None = None
    employee_name: str | None = None
    department_id: str | None = None
    department: str | None = None
    target_position_id: str | None = None
    target_position: str | None = None
    target_department_id: str | None = None
    target_department: str | None = None
    course_id: str | None = None
    course: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _needs_clarification(
    scenario_type: ScenarioType,
    message: str,
    *,
    missing_fields: list[str] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "scenario_type": scenario_type.value,
        "status": "needs_clarification",
        "message": message,
        "missing_fields": missing_fields or [],
        "candidates": candidates or [],
    }


def _pick_employee(
    lookup: SimulationLookupService,
    employee_id: str | None,
    employee_name: str | None,
    scenario_type: ScenarioType,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    query = employee_id or employee_name
    if not query:
        return None, None

    results = lookup.search_employees(query, limit=20)
    if not results:
        return None, _needs_clarification(
            scenario_type,
            f"No employee matched {query!r}. Please provide a valid employee ID or full name.",
            missing_fields=["employee_id"],
        )

    q = _norm(query)
    exact = [
        item for item in results
        if _norm(item.get("employee_id")) == q
        or _norm(item.get("employee_name")) == q
    ]
    pool = exact if exact else results
    if len(pool) == 1:
        return pool[0], None

    return None, _needs_clarification(
        scenario_type,
        f"More than one employee matched {query!r}. Please choose one employee.",
        candidates=pool[:6],
    )


def _pick_department(
    lookup: SimulationLookupService,
    department_id: str | None,
    department: str | None,
    scenario_type: ScenarioType,
    *,
    label: str = "department",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    query = department_id or department
    if not query:
        return None, None

    results = lookup.list_departments(query=query, limit=30)
    if not results:
        return None, _needs_clarification(
            scenario_type,
            f"No {label} matched {query!r}. Please provide a valid department.",
            missing_fields=[f"{label}_id"],
        )

    q = _norm(query)
    exact = [
        item for item in results
        if _norm(item.get("department_id")) == q
        or _norm(item.get("department_name")) == q
    ]
    pool = exact if exact else results
    if len(pool) == 1:
        return pool[0], None

    return None, _needs_clarification(
        scenario_type,
        f"More than one {label} matched {query!r}. Please choose one.",
        candidates=pool[:10],
    )


def _pick_named_option(
    items: list[dict[str, Any]],
    query: str,
    fields: tuple[str, ...],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    q = _norm(query)
    exact = [
        item for item in items
        if any(_norm(item.get(field)) == q for field in fields)
    ]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    contains = [
        item for item in items
        if any(q and q in _norm(item.get(field)) for field in fields)
    ]
    if len(contains) == 1:
        return contains[0], []
    return None, contains[:10]


def run_scenario_simulation_tool(
    payload: ScenarioSimulationToolInput | Mapping[str, Any],
    *,
    service: SimulationService,
) -> dict[str, Any]:
    validated = (
        payload
        if isinstance(payload, ScenarioSimulationToolInput)
        else ScenarioSimulationToolInput.model_validate(dict(payload))
    )
    scenario = validated.scenario_type
    lookup = SimulationLookupService(service.repository)
    params = dict(validated.parameters or {})

    resolved_employee = None
    if validated.employee_id or validated.employee_name:
        resolved_employee, clarification = _pick_employee(
            lookup, validated.employee_id, validated.employee_name, scenario
        )
        if clarification:
            return clarification

    resolved_department = None
    if validated.department_id or validated.department:
        resolved_department, clarification = _pick_department(
            lookup, validated.department_id, validated.department, scenario
        )
        if clarification:
            return clarification

    resolved_target_department = None
    if validated.target_department_id or validated.target_department:
        resolved_target_department, clarification = _pick_department(
            lookup,
            validated.target_department_id,
            validated.target_department,
            scenario,
            label="target_department",
        )
        if clarification:
            return clarification

    employee_id = resolved_employee.get("employee_id") if resolved_employee else validated.employee_id
    department_id = resolved_department.get("department_id") if resolved_department else validated.department_id
    target_department_id = (
        resolved_target_department.get("department_id")
        if resolved_target_department else validated.target_department_id
    )
    target_position_id = validated.target_position_id

    if validated.target_position and not target_position_id:
        if scenario == ScenarioType.EMPLOYEE_PROMOTION:
            if not employee_id:
                return _needs_clarification(
                    scenario,
                    "Employee is required before a promotion target position can be resolved.",
                    missing_fields=["employee_id"],
                )
            options = lookup.scenario_options(scenario, employee_id=employee_id)
        elif scenario == ScenarioType.EMPLOYEE_TRANSFER:
            if not employee_id or not target_department_id:
                return _needs_clarification(
                    scenario,
                    "Employee and target department are required before a transfer position can be resolved.",
                    missing_fields=["employee_id", "target_department_id"],
                )
            options = lookup.scenario_options(
                scenario,
                employee_id=employee_id,
                target_department_id=target_department_id,
            )
        else:
            options = {"target_positions": []}

        selected, candidates = _pick_named_option(
            options.get("target_positions", []),
            validated.target_position,
            ("position_id", "position_title", "designation"),
        )
        if selected:
            target_position_id = selected.get("position_id")
        else:
            return _needs_clarification(
                scenario,
                f"Target position {validated.target_position!r} could not be resolved uniquely.",
                missing_fields=["target_position_id"],
                candidates=candidates,
            )

    if scenario == ScenarioType.SKILL_RESKILLING:
        course_id = validated.course_id or params.get("course_id")
        if validated.course and not course_id:
            options = lookup.scenario_options(
                scenario,
                employee_id=employee_id,
                query=validated.course,
            )
            selected, candidates = _pick_named_option(
                options.get("courses", []),
                validated.course,
                ("course_id", "course_name", "skill_id", "skill_name"),
            )
            if selected:
                course_id = selected.get("course_id")
            else:
                return _needs_clarification(
                    scenario,
                    f"Course or skill {validated.course!r} could not be resolved uniquely.",
                    missing_fields=["course_id"],
                    candidates=candidates,
                )
        if course_id:
            params["course_id"] = course_id

    required_missing: list[str] = []
    if scenario == ScenarioType.EMPLOYEE_PROMOTION:
        if not employee_id:
            required_missing.append("employee_id")
        if not target_position_id:
            required_missing.append("target_position_id")
    elif scenario == ScenarioType.EMPLOYEE_TRANSFER:
        if not employee_id:
            required_missing.append("employee_id")
        if not target_department_id:
            required_missing.append("target_department_id")
        if not target_position_id:
            required_missing.append("target_position_id")
    elif scenario == ScenarioType.HEADCOUNT_REDUCTION:
        if not department_id:
            required_missing.append("department_id")
        if "reduce_by" not in params and "reduction_percentage" not in params:
            required_missing.append("parameters.reduce_by_or_reduction_percentage")
    elif scenario == ScenarioType.WORKFORCE_EXPANSION:
        if not department_id:
            required_missing.append("department_id")
        if "add_headcount" not in params:
            required_missing.append("parameters.add_headcount")
    elif scenario == ScenarioType.BUDGET_CHANGE:
        if not department_id:
            required_missing.append("department_id")
        if "change_percentage" not in params:
            required_missing.append("parameters.change_percentage")
    elif scenario == ScenarioType.SKILL_RESKILLING:
        if not employee_id:
            required_missing.append("employee_id")
        if "course_id" not in params:
            required_missing.append("parameters.course_id")
    elif scenario == ScenarioType.BUSINESS_DEMAND_CHANGE:
        if not department_id:
            required_missing.append("department_id")
        if "demand_change_percentage" not in params:
            required_missing.append("parameters.demand_change_percentage")

    if required_missing:
        return _needs_clarification(
            scenario,
            "More information is required before this what-if scenario can be run.",
            missing_fields=required_missing,
        )

    request = SimulationRequest(
        scenario_type=scenario,
        employee_id=employee_id,
        department_id=department_id,
        target_position_id=target_position_id,
        target_department_id=target_department_id,
        parameters=params,
    )

    try:
        response = service.run(request)
    except (SimulationDataError, SimulationValidationError, ValueError) as error:
        return {
            "scenario_type": scenario.value,
            "status": "invalid_request",
            "message": str(error),
            "resolved_inputs": {
                "employee_id": employee_id,
                "department_id": department_id,
                "target_department_id": target_department_id,
                "target_position_id": target_position_id,
            },
        }

    result = response.model_dump(mode="json", exclude_none=True)
    result["resolved_inputs"] = {
        "employee_id": employee_id,
        "employee_name": resolved_employee.get("employee_name") if resolved_employee else None,
        "department_id": department_id,
        "department": resolved_department.get("department_name") if resolved_department else None,
        "target_department_id": target_department_id,
        "target_department": (
            resolved_target_department.get("department_name")
            if resolved_target_department else None
        ),
        "target_position_id": target_position_id,
        "course_id": params.get("course_id"),
    }
    return result


def create_scenario_simulation_tool(service: SimulationService) -> BaseTool:
    @tool(SCENARIO_SIMULATION_TOOL_NAME, args_schema=ScenarioSimulationToolInput)
    def scenario_simulation_tool(**kwargs: Any) -> dict[str, Any]:
        """Run a deterministic HR what-if scenario using the shared simulation core."""
        return run_scenario_simulation_tool(kwargs, service=service)

    return scenario_simulation_tool


def create_stateful_scenario_simulation_tool(service: SimulationService) -> BaseTool:
    base_tool = create_scenario_simulation_tool(service)

    @stateful_tool(
        SCENARIO_SIMULATION_TOOL_NAME,
        args_schema=ScenarioSimulationToolInput,
    )
    def scenario_simulation_tool(
        runtime: ToolRuntime | None = None,
        **kwargs: Any,
    ) -> Command | dict[str, Any]:
        """Run Scenario Simulation and preserve its structured result in agent state."""

        result = base_tool.invoke(kwargs)

        # Safe fallback when ToolRuntime is not injected.
        if runtime is None:
            return result

        resolved = result.get("resolved_inputs") or {}

        update: dict[str, Any] = {
            "last_user_intent": "scenario_simulation",
            "last_simulation_request": kwargs,
            "last_simulation_result": result,
            "last_tool_status": result.get("status"),
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        result,
                        ensure_ascii=False,
                        default=str,
                    ),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }

        if resolved.get("employee_id"):
            update["selected_employee_id"] = resolved.get("employee_id")

        if resolved.get("employee_name"):
            update["selected_employee_name"] = resolved.get("employee_name")

        if resolved.get("department"):
            update["selected_department"] = resolved.get("department")

        return Command(update=update)

    return scenario_simulation_tool