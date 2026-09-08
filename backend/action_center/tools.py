"""LangChain tools connecting the HR LLM agent to Action Center data/actions."""

from __future__ import annotations

import json
from typing import Any

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool as stateful_tool
from langchain_core.tools import BaseTool
from langgraph.types import Command

from .errors import ActionCenterError
from .schemas import (
    ActionActor,
    ActionCenterQueryInput,
    AgentPerformActionInput,
    AgentUpdateActionRecordInput,
)
from .service import ActionCenterService


QUERY_ACTION_CENTER_TOOL_NAME = "query_action_center"
PERFORM_HR_ACTION_TOOL_NAME = "perform_hr_action"
UPDATE_HR_ACTION_RECORD_TOOL_NAME = "update_hr_action_record"


def _actor_from_runtime(runtime: ToolRuntime | None) -> ActionActor | None:
    state = runtime.state if runtime is not None else {}
    user_id = state.get("actor_user_id")
    if not user_id:
        return None
    return ActionActor(
        user_id=str(user_id),
        name=state.get("actor_name"),
        email=state.get("actor_email"),
        role=state.get("actor_role"),
    )


def _message(result: dict[str, Any], runtime: ToolRuntime | None, fallback: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str),
        tool_call_id=(runtime.tool_call_id if runtime is not None else fallback),
    )


def create_stateful_action_center_query_tool(service: ActionCenterService) -> BaseTool:
    @stateful_tool(
        QUERY_ACTION_CENTER_TOOL_NAME,
        args_schema=ActionCenterQueryInput,
    )
    def query_action_center(
        mode: str = "summary",
        process_code: str | None = None,
        employee_id: str | None = None,
        employee_name: str | None = None,
        status: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """Read authoritative HR Action Center operational data.

        Use for supported process lists, process_detail (required form fields),
        process_options (valid target departments/positions), action counts, action
        records, activity history, an employee's Action Center history, or the
        employee's current operational state. Exact counts and records come from
        deterministic CSV queries; never calculate them yourself.
        """

        runtime_state = runtime.state if runtime is not None else {}
        effective_employee_id = employee_id
        effective_employee_name = employee_name
        if not effective_employee_id and not effective_employee_name and mode in {
            "employee_history",
            "employee_state",
        }:
            selected = runtime_state.get("selected_employee_id")
            if selected:
                effective_employee_id = str(selected)

        payload = {
            "mode": mode,
            "process_code": process_code,
            "employee_id": effective_employee_id,
            "employee_name": effective_employee_name,
            "status": status,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        }
        try:
            result = service.query(payload)
            tool_status = result.get("status", "success")
        except ActionCenterError as exc:
            result = {"status": "error", "message": str(exc)}
            tool_status = "error"

        update: dict[str, Any] = {
            "last_user_intent": "action_center_query",
            "last_action_center_query": payload,
            "last_action_center_result": result,
            "last_tool_status": tool_status,
            "last_error_message": result.get("message") if tool_status == "error" else None,
            "messages": [_message(result, runtime, "action-center-query-local")],
        }

        employee = result.get("employee") if isinstance(result, dict) else None
        if isinstance(employee, dict):
            update.update({
                "selected_employee_id": employee.get("Employee_ID") or employee.get("employee_id"),
                "selected_employee_name": employee.get("Employee_Name") or employee.get("employee_name"),
                "selected_department": employee.get("Operational_Department_Name") or employee.get("department"),
                "selected_designation": employee.get("Operational_Position_Title") or employee.get("position"),
            })

        return Command(update=update)

    return query_action_center


def create_stateful_perform_hr_action_tool(service: ActionCenterService) -> BaseTool:
    @stateful_tool(
        PERFORM_HR_ACTION_TOOL_NAME,
        args_schema=AgentPerformActionInput,
    )
    def perform_hr_action(
        process_code: str | None = None,
        employee_id: str | None = None,
        employee_name: str | None = None,
        fields: dict[str, Any] | None = None,
        confirm: bool = False,
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """Preview or execute one of the 15 supported Action Center HR actions.

        First call with confirm=false. The tool validates the employee, required
        fields and business rules and stores a pending action. After the HR user
        explicitly confirms, call again with confirm=true; the pending action is
        executed and audited. Never use this tool for what-if simulation.
        """

        state = runtime.state if runtime is not None else {}
        actor = _actor_from_runtime(runtime)
        pending = state.get("pending_hr_action")

        try:
            if confirm:
                if not isinstance(pending, dict):
                    result = {
                        "status": "confirmation_missing",
                        "message": (
                            "There is no validated pending HR action in this chat. "
                            "Preview the requested action first."
                        ),
                    }
                else:
                    if process_code and str(process_code).strip().upper() != str(pending.get("process_code", "")).upper():
                        result = {
                            "status": "confirmation_conflict",
                            "message": (
                                "The confirmation refers to a different process than the pending HR action. "
                                "Preview the new action first."
                            ),
                        }
                    else:
                        result = service.execute_action(
                            process_code=str(pending["process_code"]),
                            employee_id=str(pending["employee_id"]),
                            employee_name=None,
                            fields=dict(pending.get("fields") or {}),
                            actor=actor,
                        )
            else:
                effective_employee_id = employee_id
                effective_employee_name = employee_name
                if not effective_employee_id and not effective_employee_name:
                    selected = state.get("selected_employee_id")
                    if selected:
                        effective_employee_id = str(selected)

                if not process_code:
                    result = {
                        "status": "invalid_request",
                        "message": "A supported Action Center process is required before an HR action can be previewed.",
                    }
                else:
                    result = service.preview_action(
                        process_code=process_code,
                        employee_id=effective_employee_id,
                        employee_name=effective_employee_name,
                        fields=dict(fields or {}),
                        actor=actor,
                    )

        except ActionCenterError as exc:
            result = {"status": "error", "message": str(exc)}

        status = result.get("status", "error")
        update: dict[str, Any] = {
            "last_user_intent": "action_center_write",
            "last_hr_action_result": result,
            "last_tool_status": status,
            "last_error_message": result.get("message") if status in {"error", "invalid_request"} else None,
        }

        if status == "ready":
            employee = result.get("employee") or {}
            pending_action = {
                "process_code": result["process"]["process_code"],
                "employee_id": employee.get("employee_id") or employee.get("Employee_ID"),
                "fields": result.get("normalized_fields") or {},
                "preview": result,
            }
            update["pending_hr_action"] = pending_action
            update["selected_employee_id"] = pending_action["employee_id"]
            update["selected_employee_name"] = employee.get("employee_name") or employee.get("Employee_Name")
            update["selected_department"] = employee.get("department") or employee.get("Operational_Department_Name")
            update["selected_designation"] = employee.get("position") or employee.get("Operational_Position_Title")

        elif status == "completed":
            update["pending_hr_action"] = None
            employee = result.get("employee") or {}
            update["selected_employee_id"] = employee.get("Employee_ID") or employee.get("employee_id")
            update["selected_employee_name"] = employee.get("Employee_Name") or employee.get("employee_name")
            update["selected_department"] = employee.get("Operational_Department_Name") or employee.get("department")
            update["selected_designation"] = employee.get("Operational_Position_Title") or employee.get("position")

        update["messages"] = [
            _message(result, runtime, "action-center-write-local")
        ]
        return Command(update=update)

    return perform_hr_action


def create_stateful_update_hr_action_record_tool(service: ActionCenterService) -> BaseTool:
    @stateful_tool(
        UPDATE_HR_ACTION_RECORD_TOOL_NAME,
        args_schema=AgentUpdateActionRecordInput,
    )
    def update_hr_action_record(
        action_record_id: str | None = None,
        updates: dict[str, Any] | None = None,
        confirm: bool = False,
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """Safely edit a SCHEDULED Action Center record with an audit event.

        Only Effective_Date, Reason_Category, Reason_Details and Action_Data_JSON
        are editable. Applied/withdrawn records are immutable. Preview first,
        then execute after explicit HR confirmation.
        """

        state = runtime.state if runtime is not None else {}
        actor = _actor_from_runtime(runtime)
        pending = state.get("pending_hr_record_update")

        try:
            if confirm:
                if not isinstance(pending, dict):
                    result = {
                        "status": "confirmation_missing",
                        "message": "There is no pending Action Center record update to confirm.",
                    }
                else:
                    result = service.update_action_record(
                        action_record_id=str(pending["action_record_id"]),
                        updates=dict(pending.get("updates") or {}),
                        actor=actor,
                    )
            else:
                if not action_record_id or not updates:
                    result = {
                        "status": "invalid_request",
                        "message": "action_record_id and updates are required to preview a record update.",
                    }
                else:
                    current = service.repository.get_action_record(action_record_id)
                    if str(current.get("Record_Status", "")).upper() != "SCHEDULED":
                        result = {
                            "status": "error",
                            "message": "Only SCHEDULED Action Center records can be edited.",
                        }
                    else:
                        allowed = {"Effective_Date", "Reason_Category", "Reason_Details", "Action_Data_JSON"}
                        unsupported = sorted(set(updates) - allowed)
                        if unsupported:
                            result = {
                                "status": "error",
                                "message": "Unsupported update fields: " + ", ".join(unsupported),
                            }
                        else:
                            result = {
                                "status": "ready",
                                "confirmation_required": True,
                                "action_record_id": action_record_id,
                                "current": current,
                                "updates": updates,
                                "message": "The scheduled record update is valid. Confirm before saving it.",
                            }
        except ActionCenterError as exc:
            result = {"status": "error", "message": str(exc)}

        status = result.get("status", "error")
        update: dict[str, Any] = {
            "last_user_intent": "action_center_record_update",
            "last_hr_action_result": result,
            "last_tool_status": status,
            "last_error_message": result.get("message") if status == "error" else None,
        }
        if status == "ready":
            update["pending_hr_record_update"] = {
                "action_record_id": result["action_record_id"],
                "updates": result["updates"],
            }
        elif status == "completed":
            update["pending_hr_record_update"] = None

        update["messages"] = [
            _message(result, runtime, "action-center-record-update-local")
        ]
        return Command(update=update)

    return update_hr_action_record
