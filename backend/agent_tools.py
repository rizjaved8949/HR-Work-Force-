"""High-level tools exposed to the main HR reasoning agent."""

from typing import Any, Optional

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
import json

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool as stateful_tool
from langgraph.types import Command


# ============================================================
# INPUT SCHEMA
# ============================================================

class CheckEmployeeAttritionInput(BaseModel):
    """Input accepted by the high-level attrition tool."""

    employee_id: Optional[str] = Field(
        default=None,
        description=(
            "Unique employee ID, such as EMP004. "
            "Use this whenever the user provides an employee ID."
        ),
    )

    employee_name: Optional[str] = Field(
        default=None,
        description=(
            "Employee name, such as Ali Masood. "
            "Use this when employee ID is not available."
        ),
    )

    department: Optional[str] = Field(
        default=None,
        description=(
            "Optional department used to distinguish employees "
            "with the same or similar name."
        ),
    )


# ============================================================
# INTERNAL HELPER FUNCTIONS
# ============================================================

def _normalize_text(value: Optional[str]) -> str:
    """Normalize text for safe identity comparison."""

    if not value:
        return ""

    return " ".join(
        str(value).strip().lower().split()
    )


def _loosely_matches(
    requested_value: Optional[str],
    available_values: list[Optional[str]],
) -> bool:
    """
    Check whether the user's supplied value reasonably matches
    the resolved employee information.
    """

    requested = _normalize_text(requested_value)

    if not requested:
        return True

    for value in available_values:
        normalized_value = _normalize_text(value)

        if not normalized_value:
            continue

        if (
            requested == normalized_value
            or requested in normalized_value
            or normalized_value in requested
        ):
            return True

    return False


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Keep only the information required by the agent
    to ask an employee clarification question.
    """

    return {
        "employee_id": candidate.get("employee_id"),
        "employee_name": candidate.get("employee_name"),
        "department": candidate.get("department"),
        "designation": candidate.get("designation"),
        "office": candidate.get("office"),
    }


# ============================================================
# TOOL FACTORY
# ============================================================

def create_check_employee_attrition_tool(
    employee_search_tool: BaseTool,
    attrition_prediction_tool: BaseTool,
) -> BaseTool:
    """
    Create one high-level attrition tool using the existing
    employee-search and CatBoost prediction tools.

    The existing tools are passed into this function so the
    model and employee data are not loaded a second time.
    """

    @tool(
        "check_employee_attrition",
        args_schema=CheckEmployeeAttritionInput,
    )
    def check_employee_attrition(
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Check attrition risk for one employee.

        Use employee_id whenever available. When only a name is
        available, employee_name may be used with an optional
        department.

        This tool resolves the employee, requests clarification
        when multiple employees match, and runs the CatBoost
        attrition model only after one employee has been resolved.

        It returns a compact result suitable for the HR reasoning
        agent and never exposes the complete employee record.
        """

        # At least one employee identity field is required.
        if not employee_id and not employee_name:
            return {
                "status": "invalid_request",
                "message": (
                    "An employee ID or employee name is required "
                    "before attrition can be checked."
                ),
            }

        # ----------------------------------------------------
        # STEP 1: Resolve the employee using the existing tool
        # ----------------------------------------------------

        employee_record = employee_search_tool.invoke({
            "employee_id": employee_id,
            "employee_name": employee_name,
            "department": department,
        })

        search_status = employee_record.get("status")

        # ----------------------------------------------------
        # MULTIPLE OR APPROXIMATE EMPLOYEE MATCHES
        # ----------------------------------------------------

        if search_status == "needs_clarification":
            candidates = employee_record.get("candidates", [])

            return {
                "status": "needs_clarification",
                "message": (
                    "Multiple or approximate employee matches "
                    "were found. Ask the user to select the "
                    "correct employee."
                ),
                "candidates": [
                    _compact_candidate(candidate)
                    for candidate in candidates
                ],
            }

        # ----------------------------------------------------
        # EMPLOYEE NOT FOUND
        # ----------------------------------------------------

        if search_status == "not_found":
            return {
                "status": "not_found",
                "message": employee_record.get(
                    "message",
                    "No matching employee was found.",
                ),
            }

        # ----------------------------------------------------
        # INVALID OR UNEXPECTED SEARCH RESULT
        # ----------------------------------------------------

        if search_status != "found":
            return {
                "status": "error",
                "message": (
                    "The employee could not be resolved from "
                    "the available records."
                ),
            }

        # ----------------------------------------------------
        # VALIDATE SUPPLIED NAME AND DEPARTMENT AGAINST ID
        # ----------------------------------------------------

        resolved_employee = employee_record.get(
            "employee",
            {},
        )

        resolved_name = resolved_employee.get(
            "employee_name"
        )

        name_aliases = resolved_employee.get(
            "name_aliases",
            [],
        )

        resolved_department = resolved_employee.get(
            "department"
        )

        # Prevent prediction when the supplied employee ID
        # resolves to a conflicting employee name.
        if employee_name and not _loosely_matches(
            employee_name,
            [resolved_name, *name_aliases],
        ):
            return {
                "status": "identity_conflict",
                "message": (
                    "The supplied employee ID and employee name "
                    "refer to different employee records. Ask "
                    "the user to confirm the correct employee."
                ),
                "requested_identity": {
                    "employee_id": employee_id,
                    "employee_name": employee_name,
                    "department": department,
                },
                "resolved_employee": {
                    "employee_id": resolved_employee.get(
                        "employee_id"
                    ),
                    "employee_name": resolved_name,
                    "department": resolved_department,
                    "designation": resolved_employee.get(
                        "designation"
                    ),
                },
            }

        # Prevent prediction when the supplied ID resolves to
        # a conflicting department.
        if department and not _loosely_matches(
            department,
            [resolved_department],
        ):
            return {
                "status": "identity_conflict",
                "message": (
                    "The supplied employee ID and department "
                    "do not match the same employee record. Ask "
                    "the user to confirm the correct employee."
                ),
                "requested_identity": {
                    "employee_id": employee_id,
                    "employee_name": employee_name,
                    "department": department,
                },
                "resolved_employee": {
                    "employee_id": resolved_employee.get(
                        "employee_id"
                    ),
                    "employee_name": resolved_name,
                    "department": resolved_department,
                    "designation": resolved_employee.get(
                        "designation"
                    ),
                },
            }

        # ----------------------------------------------------
        # STEP 2: RUN THE EXISTING CATBOOST TOOL
        # ----------------------------------------------------

        prediction = attrition_prediction_tool.invoke({
            "employee_record": employee_record,
        })

        # ----------------------------------------------------
        # RETURN ONLY COMPACT AGENT-FACING INFORMATION
        # ----------------------------------------------------

        return {
            "status": "completed",
            "employee": {
                "employee_id": resolved_employee.get(
                    "employee_id"
                ),
                "employee_name": resolved_name,
                "department": resolved_department,
                "designation": resolved_employee.get(
                    "designation"
                ),
            },
            "attrition": prediction.get("attrition"),
            "top_reasons": prediction.get(
                "top_reasons",
                [],
            ),
        }

    return check_employee_attrition

# ============================================================
# STATE-AWARE TOOL FACTORY FOR THE MAIN HR AGENT
# ============================================================

def create_stateful_check_employee_attrition_tool(
    employee_search_tool: BaseTool,
    attrition_prediction_tool: BaseTool,
) -> BaseTool:
    """
    Create the attrition tool used by the main HR reasoning agent.

    This wrapper reuses the already tested high-level attrition
    workflow and also writes the confirmed employee identity,
    prediction result, clarification status, and other workflow
    information into LangGraph conversation state.
    """

    # Reuse the previously tested high-level tool.
    base_attrition_tool = create_check_employee_attrition_tool(
        employee_search_tool=employee_search_tool,
        attrition_prediction_tool=attrition_prediction_tool,
    )

    @stateful_tool(
        "check_employee_attrition",
        args_schema=CheckEmployeeAttritionInput,
    )
    def check_employee_attrition(
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
        runtime: ToolRuntime = None,
    ) -> Command:
        """
        Check attrition risk for one employee and preserve the
        resolved employee context in the current chat session.

        Use employee_id whenever available. Use employee_name
        when the user provides only a name. Include department
        when it helps distinguish employees with similar names.

        Never guess between multiple employees. When more than
        one employee matches, return clarification candidates.
        """

        # ----------------------------------------------------
        # RUN THE EXISTING TESTED ATTRITION WORKFLOW
        # ----------------------------------------------------

        result = base_attrition_tool.invoke({
            "employee_id": employee_id,
            "employee_name": employee_name,
            "department": department,
        })

        status = result.get("status", "error")

        # Common state values written after every tool call.
        state_update: dict[str, Any] = {
            "last_tool_status": status,
            "last_error_message": None,
        }

        # ----------------------------------------------------
        # SUCCESSFUL ATTRITION RESULT
        # ----------------------------------------------------

        if status == "completed":
            employee = result.get("employee", {})
            attrition_result = result.get("attrition")
            top_reasons = result.get("top_reasons", [])

            state_update.update({
                "selected_employee_id": employee.get(
                    "employee_id"
                ),
                "selected_employee_name": employee.get(
                    "employee_name"
                ),
                "selected_department": employee.get(
                    "department"
                ),
                "selected_designation": employee.get(
                    "designation"
                ),
                "last_user_intent": "attrition",
                "last_attrition_result": {
                    "attrition": attrition_result,
                    "top_reasons": top_reasons,
                },
                "last_attrition_reasons": top_reasons,
                "replacement_offer_pending": (
                    attrition_result == "Yes"
                ),
                "pending_clarification": False,
                "pending_candidates": [],
                "pending_original_request": None,
            })

        # ----------------------------------------------------
        # MULTIPLE EMPLOYEES REQUIRE CLARIFICATION
        # ----------------------------------------------------

        elif status == "needs_clarification":
            candidates = result.get("candidates", [])

            state_update.update({
                # Clear the old employee context so the agent
                # does not accidentally use a previous employee.
                "selected_employee_id": None,
                "selected_employee_name": None,
                "selected_department": None,
                "selected_designation": None,

                "last_user_intent": "clarification",
                "pending_clarification": True,
                "pending_candidates": candidates,
                "pending_original_request": {
                    "intent": "attrition",
                    "employee_id": employee_id,
                    "employee_name": employee_name,
                    "department": department,
                },
                "replacement_offer_pending": False,
            })

        # ----------------------------------------------------
        # EMPLOYEE ID, NAME OR DEPARTMENT CONFLICT
        # ----------------------------------------------------

        elif status == "identity_conflict":
            resolved_employee = result.get(
                "resolved_employee",
                {},
            )

            state_update.update({
                "selected_employee_id": None,
                "selected_employee_name": None,
                "selected_department": None,
                "selected_designation": None,

                "last_user_intent": "clarification",
                "pending_clarification": True,
                "pending_candidates": [
                    resolved_employee
                ],
                "pending_original_request": {
                    "intent": "attrition",
                    "employee_id": employee_id,
                    "employee_name": employee_name,
                    "department": department,
                },
                "replacement_offer_pending": False,
                "last_error_message": result.get(
                    "message"
                ),
            })

        # ----------------------------------------------------
        # EMPLOYEE NOT FOUND OR INVALID REQUEST
        # ----------------------------------------------------

        elif status in {
            "not_found",
            "invalid_request",
        }:
            state_update.update({
                "selected_employee_id": None,
                "selected_employee_name": None,
                "selected_department": None,
                "selected_designation": None,

                "last_user_intent": "attrition",
                "pending_clarification": False,
                "pending_candidates": [],
                "pending_original_request": None,
                "replacement_offer_pending": False,
                "last_error_message": result.get(
                    "message"
                ),
            })

        # ----------------------------------------------------
        # UNEXPECTED TOOL ERROR
        # ----------------------------------------------------

        else:
            # Do not clear the existing employee here.
            # Keeping the employee context allows the same
            # request to be retried after a temporary failure.
            state_update.update({
                "last_error_message": result.get(
                    "message",
                    "The attrition workflow could not be completed.",
                ),
            })

        # ----------------------------------------------------
        # RETURN TOOL RESULT AND STATE UPDATE
        # ----------------------------------------------------

        # A ToolMessage is required so the LLM receives the
        # compact tool result after LangGraph updates state.
        # The runtime is absent when the tool is invoked directly
        # from a test rather than from the agent loop.
        tool_call_id = (
            runtime.tool_call_id
            if runtime is not None
            else "local-call"
        )

        state_update["messages"] = [
            ToolMessage(
                content=json.dumps(
                    result,
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call_id,
            )
        ]

        return Command(
            update=state_update
        )

    return check_employee_attrition