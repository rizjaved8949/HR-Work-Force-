"""Local successor-recommendation tool for the main HR agent."""

import json
from pathlib import Path
from typing import Any, Optional

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool as stateful_tool
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import BaseModel, Field

from successor_service.bootstrap import build_graph


class ReplacementRecommendationInput(BaseModel):
    """Input for the local successor graph."""

    employee_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Confirmed employee ID whose replacement or successor "
            "recommendations are required, for example EMP004."
        ),
    )


class StatefulReplacementRecommendationInput(BaseModel):
    """Input used by the main HR reasoning agent."""

    employee_id: Optional[str] = Field(
        default=None,
        description=(
            "Confirmed employee ID. When omitted, use the selected "
            "employee ID already stored in conversation memory."
        ),
    )


def _normalize_employee_id(employee_id: str) -> str:
    return employee_id.strip().upper()


def _compact_successor(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "rank": candidate.get("rank"),
        "employee_id": candidate.get("employee_id"),
        "employee_name": candidate.get("employee_name"),
        "current_position": candidate.get("current_position"),
        "final_score": candidate.get("final_score"),
        "qualification_status": candidate.get(
            "qualification_status"
        ),
        "readiness": candidate.get("readiness"),
        "reasons": candidate.get("reasons", []),
    }


def create_replacement_recommendation_tool(
    data_dir: str | Path,
) -> BaseTool:
    """Create a local replacement tool using the merged LangGraph code.

    The graph is initialized once and reads the same CSV directory used by
    the attrition application. No HTTP request, remote IP, or port 8002 is
    used.
    """

    successor_graph = build_graph(data_dir)

    @tool(
        "recommend_replacement",
        args_schema=ReplacementRecommendationInput,
    )
    def recommend_replacement(
        employee_id: str,
    ) -> dict[str, Any]:
        """Recommend internal successors for a confirmed employee ID."""

        normalized_employee_id = _normalize_employee_id(employee_id)
        if not normalized_employee_id:
            return {
                "status": "invalid_request",
                "message": (
                    "A confirmed employee ID is required for "
                    "replacement recommendations."
                ),
            }

        try:
            response_data = successor_graph.invoke(
                employee_id=normalized_employee_id,
            )
        except FileNotFoundError as exc:
            return {
                "status": "data_error",
                "employee_id": normalized_employee_id,
                "message": str(exc),
            }
        except Exception as exc:
            return {
                "status": "error",
                "employee_id": normalized_employee_id,
                "message": (
                    "The local replacement workflow could not be "
                    f"completed: {exc}"
                ),
            }

        if response_data.get("status") == "needs_clarification":
            # The successor graph names this list "matches"; the HR agent
            # and the API both expect "candidates".
            return {
                "status": "needs_clarification",
                "employee_id": normalized_employee_id,

                # The graph distinguishes "no such employee" (not_found,
                # invalid_reference) from "several employees matched"
                # (ambiguous). Dropping it here left every failure looking
                # like an ambiguity with an empty candidate list, which a
                # caller cannot act on.
                "resolution_status": response_data.get(
                    "resolution_status"
                ),
                "message": response_data.get(
                    "message",
                    "The employee could not be uniquely resolved.",
                ),
                "candidates": response_data.get(
                    "matches",
                    response_data.get("candidates", []),
                ),
            }

        recommended_successors = response_data.get(
            "recommended_successors"
        )
        if not isinstance(recommended_successors, list):
            return {
                "status": "invalid_response",
                "employee_id": normalized_employee_id,
                "message": (
                    "The local replacement workflow did not return a "
                    "valid recommended_successors list."
                ),
            }

        top_candidates = [
            _compact_successor(candidate)
            for candidate in recommended_successors[:3]
            if isinstance(candidate, dict)
        ]

        if not top_candidates:
            return {
                "status": "no_candidates",
                "employee_id": normalized_employee_id,
                "recommended_successors": [],
                "message": (
                    "No suitable replacement candidates were returned "
                    "for this employee."
                ),
            }

        return {
            "status": "completed",
            "target_employee_id": normalized_employee_id,
            "recommended_successors": top_candidates,
            "disclaimer": (
                "These recommendations are decision support. The final "
                "succession decision remains with authorized HR or "
                "management."
            ),
        }

    return recommend_replacement


def create_stateful_replacement_recommendation_tool(
    replacement_tool: BaseTool,
) -> BaseTool:
    """Create the conversation-state-aware replacement tool."""

    @stateful_tool(
        "recommend_replacement",
        args_schema=StatefulReplacementRecommendationInput,
    )
    def recommend_replacement(
        employee_id: Optional[str] = None,
        # Must stay a bare `ToolRuntime` -- see agent_tools.py for why.
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """Recommend successors without re-running local attrition search."""

        stored_employee_id = None
        if runtime is not None:
            stored_employee_id = runtime.state.get(
                "selected_employee_id"
            )

        confirmed_employee_id = employee_id or stored_employee_id
        if confirmed_employee_id:
            confirmed_employee_id = str(
                confirmed_employee_id
            ).strip().upper()

        if not confirmed_employee_id:
            result = {
                "status": "invalid_request",
                "message": (
                    "A confirmed employee ID is required before "
                    "replacement recommendations can be generated."
                ),
            }
            state_update: dict[str, Any] = {
                "last_user_intent": "replacement",
                "last_tool_status": "invalid_request",
                "last_error_message": result["message"],
                "replacement_tool_available": True,
                "replacement_offer_pending": False,
            }
        else:
            result = replacement_tool.invoke({
                "employee_id": confirmed_employee_id,
            })
            status = result.get("status", "error")
            state_update = {
                "selected_employee_id": confirmed_employee_id,
                "last_user_intent": "replacement",
                "last_tool_status": status,
                "replacement_tool_available": True,
                "replacement_offer_pending": False,
                "last_error_message": None,
            }

            if status == "completed":
                state_update.update({
                    "last_replacement_result": result,
                    "pending_clarification": False,
                    "pending_candidates": [],
                    "pending_original_request": None,
                })
            elif status == "no_candidates":
                state_update.update({
                    "last_replacement_result": result,
                    "last_error_message": result.get("message"),
                })
            else:
                state_update.update({
                    "last_error_message": result.get(
                        "message",
                        "The replacement recommendation could not be "
                        "completed.",
                    ),
                })

        tool_call_id = (
            runtime.tool_call_id if runtime is not None else "local-call"
        )
        state_update["messages"] = [
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call_id,
            )
        ]
        return Command(update=state_update)

    return recommend_replacement
