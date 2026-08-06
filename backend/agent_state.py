"""Custom conversation state for the HR reasoning agent."""

from typing import Any

from langchain.agents import AgentState
from typing_extensions import NotRequired


class HRAgentState(AgentState):
    """
    Thread-level state maintained for one HR chatbot session.

    The built-in AgentState already contains the conversation
    messages. The fields below store structured employee and
    workflow context separately from the message history.
    """

    # ========================================================
    # CURRENTLY SELECTED EMPLOYEE
    # ========================================================

    selected_employee_id: NotRequired[str | None]

    selected_employee_name: NotRequired[str | None]

    selected_department: NotRequired[str | None]

    selected_designation: NotRequired[str | None]

    # ========================================================
    # CURRENT OR PREVIOUS USER INTENT
    # ========================================================

    last_user_intent: NotRequired[str | None]

    # Expected values may include:
    # - attrition
    # - replacement
    # - headcount
    # - clarification
    # - general

    # ========================================================
    # ATTRITION RESULT
    # ========================================================

    last_attrition_result: NotRequired[dict[str, Any] | None]

    last_attrition_reasons: NotRequired[list[str]]

    replacement_offer_pending: NotRequired[bool]

    # ========================================================
    # REPLACEMENT RESULT
    # ========================================================

    last_replacement_result: NotRequired[dict[str, Any] | None]

    # The local successor graph is always connected, so this is True
    # after any replacement call. It exists so the agent can tell a
    # genuine tool failure apart from a missing capability.
    replacement_tool_available: NotRequired[bool]

    # ========================================================
    # HEADCOUNT RESULT
    # ========================================================

    last_headcount_question: NotRequired[str | None]

    last_headcount_result: NotRequired[dict[str, Any] | None]

    # ========================================================
    # EMPLOYEE CLARIFICATION
    # ========================================================

    pending_clarification: NotRequired[bool]

    pending_candidates: NotRequired[list[dict[str, Any]]]

    pending_original_request: NotRequired[dict[str, Any] | None]

    # Example pending_original_request:
    #
    # {
    #     "intent": "attrition",
    #     "employee_name": "Ali",
    #     "department": None
    # }

    # ========================================================
    # SERVICE AND WORKFLOW STATUS
    # ========================================================

    last_tool_status: NotRequired[str | None]

    last_error_message: NotRequired[str | None]