"""State-aware employee profile lookup adapter for the main HR agent.

This module intentionally does not change employee retrieval logic. It wraps the
already-created ``get_employee_record`` tool so the reasoning agent can use the
same repository instance while preserving conversation state.

The adapter is additive: importing this module or creating the wrapper has no
impact on Attrition, Replacement, Headcount, Performance, authentication, or
existing API routes until the wrapper is explicitly registered in ``hr_agent.py``.
"""

import json
from typing import Any, Optional

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool as stateful_tool
from langchain_core.tools import BaseTool
from langgraph.types import Command

from employee_record_tool import EmployeeRecordSearchInput


EMPLOYEE_PROFILE_TOOL_NAME = "get_employee_record"


def create_stateful_employee_record_tool(
    employee_search_tool: BaseTool,
) -> BaseTool:
    """Wrap the existing employee search tool with LangGraph state updates.

    The supplied ``employee_search_tool`` is reused as-is. No second repository is
    created and no CSV file is reloaded by this adapter.
    """

    @stateful_tool(
        EMPLOYEE_PROFILE_TOOL_NAME,
        args_schema=EmployeeRecordSearchInput,
    )
    def get_employee_record(
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
        designation: Optional[str] = None,
        position_id: Optional[str] = None,
        office: Optional[str] = None,
        # Keep ToolRuntime as a bare annotation. LangChain uses this exact
        # annotation to inject thread state and the current tool_call_id.
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """Retrieve factual stored HR details for one employee.

        Use this for employee profile/details such as department, designation,
        job level, work mode, employment type, employee status, business unit,
        manager ID, location, experience, skills, attendance, or another field
        that is actually present in the employee record. Prefer employee_id when
        available and never guess between multiple name matches.
        """

        # ----------------------------------------------------
        # REUSE CONVERSATION CONTEXT WHEN THE USER USES A
        # FOLLOW-UP SUCH AS "his work mode" OR A CLARIFICATION.
        # Explicit identity supplied in this call always wins.
        # ----------------------------------------------------
        runtime_state = runtime.state if runtime is not None else {}

        effective_employee_id = employee_id
        effective_employee_name = employee_name
        effective_department = department
        effective_designation = designation
        effective_position_id = position_id
        effective_office = office

        has_explicit_identity = bool(employee_id or employee_name)

        if not has_explicit_identity:
            pending_request = runtime_state.get("pending_original_request")
            if (
                isinstance(pending_request, dict)
                and pending_request.get("intent") == "employee_profile"
            ):
                # Preserve the original unresolved name while accepting the
                # user's new disambiguation filter (for example "Finance wala").
                effective_employee_name = pending_request.get("employee_name")
                effective_department = (
                    department
                    if department is not None
                    else pending_request.get("department")
                )
                effective_designation = (
                    designation
                    if designation is not None
                    else pending_request.get("designation")
                )
                effective_position_id = (
                    position_id
                    if position_id is not None
                    else pending_request.get("position_id")
                )
                effective_office = (
                    office
                    if office is not None
                    else pending_request.get("office")
                )

            elif not any(
                [department, designation, position_id, office]
            ):
                stored_employee_id = runtime_state.get("selected_employee_id")
                if stored_employee_id:
                    effective_employee_id = str(stored_employee_id)

        query = {
            "employee_id": effective_employee_id,
            "employee_name": effective_employee_name,
            "department": effective_department,
            "designation": effective_designation,
            "position_id": effective_position_id,
            "office": effective_office,
        }

        # ----------------------------------------------------
        # CALL THE ALREADY-TESTED BASE EMPLOYEE LOOKUP TOOL.
        # ----------------------------------------------------
        result = employee_search_tool.invoke(query)
        status = result.get("status", "error")

        state_update: dict[str, Any] = {
            "last_tool_status": status,
            "last_employee_record_query": query,
            "last_employee_record_result": result,
            "last_error_message": None,
        }

        # ----------------------------------------------------
        # SUCCESSFUL EMPLOYEE PROFILE LOOKUP.
        # ----------------------------------------------------
        if status == "found":
            employee = result.get("employee", {})
            state_update.update({
                "selected_employee_id": employee.get("employee_id"),
                "selected_employee_name": employee.get("employee_name"),
                "selected_department": employee.get("department"),
                "selected_designation": employee.get("designation"),
                "last_user_intent": "employee_profile",
                "pending_clarification": False,
                "pending_candidates": [],
                "pending_original_request": None,
            })

        # ----------------------------------------------------
        # MULTIPLE / APPROXIMATE EMPLOYEE MATCHES.
        # ----------------------------------------------------
        elif status == "needs_clarification":
            candidates = result.get("candidates", [])
            state_update.update({
                # Avoid accidentally carrying a previously selected employee
                # into a new ambiguous profile lookup.
                "selected_employee_id": None,
                "selected_employee_name": None,
                "selected_department": None,
                "selected_designation": None,
                "last_user_intent": "clarification",
                "pending_clarification": True,
                "pending_candidates": candidates,
                "pending_original_request": {
                    "intent": "employee_profile",
                    "employee_id": effective_employee_id,
                    "employee_name": effective_employee_name,
                    "department": effective_department,
                    "designation": effective_designation,
                    "position_id": effective_position_id,
                    "office": effective_office,
                },
                "last_error_message": result.get("message"),
            })

        # ----------------------------------------------------
        # NOT FOUND / INVALID PROFILE REQUEST.
        # ----------------------------------------------------
        elif status in {"not_found", "invalid_request"}:
            state_update.update({
                "selected_employee_id": None,
                "selected_employee_name": None,
                "selected_department": None,
                "selected_designation": None,
                "last_user_intent": "employee_profile",
                "pending_clarification": False,
                "pending_candidates": [],
                "pending_original_request": None,
                "last_error_message": result.get("message"),
            })

        # ----------------------------------------------------
        # UNEXPECTED ERROR-LIKE RESULT.
        # Keep any existing employee context so a temporary problem does
        # not erase a valid prior selection.
        # ----------------------------------------------------
        else:
            state_update.update({
                "last_user_intent": "employee_profile",
                "last_error_message": result.get(
                    "message",
                    "The employee record lookup could not be completed.",
                ),
            })

        tool_call_id = (
            runtime.tool_call_id
            if runtime is not None
            else "employee-profile-local-call"
        )

        state_update["messages"] = [
            ToolMessage(
                content=json.dumps(
                    result,
                    ensure_ascii=False,
                    default=str,
                ),
                tool_call_id=tool_call_id,
            )
        ]

        return Command(update=state_update)

    return get_employee_record
