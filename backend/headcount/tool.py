"""High-level deterministic Headcount tools for the HR reasoning agent.

The module preserves the plain Python adapter used by service tests and also
exposes LangChain tool factories that follow the same state-aware pattern as
the existing attrition and replacement tools.

No LLM is called here. Exact values are calculated by HeadcountService.
"""

import json
import logging
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any, Final

from langchain.messages import ToolMessage
from langchain.tools import (
    ToolRuntime,
    tool as stateful_tool,
)
from langchain_core.tools import (
    BaseTool,
    tool,
)
from langgraph.types import Command
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

import paths
from headcount.repository import HeadcountRepository
from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountToolResult,
)
from headcount.service import HeadcountService


logger = logging.getLogger(__name__)


ANALYZE_HEADCOUNT_TOOL_NAME: Final[str] = (
    "analyze_headcount"
)

ANALYZE_HEADCOUNT_TOOL_DESCRIPTION: Final[str] = (
    "Answer deterministic Headcount-management questions using "
    "the organization's HR data. Use it for current Headcount, "
    "positions, vacancies, workforce composition, people budget, "
    "daily availability, historical Headcount trends, workforce "
    "movements, employee or position lookup, management rules, "
    "exceptions, and Headcount metric definitions. Do not use it "
    "for employee attrition-risk prediction or successor selection."
)


class AnalyzeHeadcountToolInput(BaseModel):
    """Input contract exposed to the HR reasoning agent."""

    # `extra` must stay permissive. LangChain validates the tool's whole
    # call payload against this schema, and inside the agent loop that
    # payload also carries the injected ToolRuntime. With extra="forbid"
    # every agent call fails validation before the tool body ever runs.
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    question: str = Field(
        min_length=3,
        description=(
            "The user's complete natural-language "
            "Headcount-management question. Preserve important "
            "scope, date, ranking, grouping, and filter wording."
        ),
    )


class HeadcountToolAdapterError(RuntimeError):
    """Raised when the Headcount tool cannot process its input."""


@lru_cache(maxsize=1)
def get_default_headcount_service() -> HeadcountService:
    """Build and cache the default repository-backed service."""

    repository = HeadcountRepository(
        paths.data_dir()
    )

    return HeadcountService(
        repository
    )


def _normalize_tool_input(
    payload: AnalyzeHeadcountToolInput
    | Mapping[str, Any]
    | str,
) -> AnalyzeHeadcountToolInput:
    """Convert supported caller inputs to the validated schema."""

    if isinstance(
        payload,
        AnalyzeHeadcountToolInput,
    ):
        return payload

    if isinstance(payload, str):
        return AnalyzeHeadcountToolInput(
            question=payload
        )

    if isinstance(payload, Mapping):
        return AnalyzeHeadcountToolInput.model_validate(
            dict(payload)
        )

    raise HeadcountToolAdapterError(
        "The analyze_headcount tool requires either a "
        "question string, an AnalyzeHeadcountToolInput object, "
        "or a mapping containing a 'question' field."
    )


def _serialize_result(
    result: HeadcountToolResult,
) -> dict[str, Any]:
    """Return a JSON-safe result for the reasoning agent."""

    return result.model_dump(
        mode="json",
        exclude_none=True,
    )


def run_analyze_headcount_tool(
    payload: AnalyzeHeadcountToolInput
    | Mapping[str, Any]
    | str,
    *,
    service: HeadcountService | None = None,
) -> dict[str, Any]:
    """Execute one validated deterministic Headcount question."""

    validated = _normalize_tool_input(
        payload
    )

    active_service = (
        service
        if service is not None
        else get_default_headcount_service()
    )

    request = AnalyzeHeadcountInput(
        question=validated.question
    )

    result = active_service.analyze(
        request
    )

    return _serialize_result(
        result
    )


def analyze_headcount(
    question: str,
) -> dict[str, Any]:
    """Plain Python callable for non-agent integrations."""

    return run_analyze_headcount_tool(
        question
    )


def create_analyze_headcount_callable(
    service: HeadcountService | None = None,
) -> Callable[[str], dict[str, Any]]:
    """Create an injectable plain callable for tests."""

    def tool_callable(
        question: str,
    ) -> dict[str, Any]:
        return run_analyze_headcount_tool(
            question,
            service=service,
        )

    tool_callable.__name__ = (
        ANALYZE_HEADCOUNT_TOOL_NAME
    )

    tool_callable.__doc__ = (
        ANALYZE_HEADCOUNT_TOOL_DESCRIPTION
    )

    return tool_callable


def create_analyze_headcount_tool(
    service: HeadcountService | None = None,
) -> BaseTool:
    """Create the base LangChain Headcount tool."""

    active_service = (
        service
        if service is not None
        else get_default_headcount_service()
    )

    @tool(
        ANALYZE_HEADCOUNT_TOOL_NAME,
        args_schema=AnalyzeHeadcountToolInput,
    )
    def analyze_headcount_tool(
        question: str,
    ) -> dict[str, Any]:
        """Analyze a Headcount-management question using HR data.

        Use this tool for organization, business-unit, department,
        position, vacancy, budget, availability, historical movement,
        workforce-composition, rule, exception, definition, employee
        lookup, or position lookup questions. Pass the user's complete
        question without paraphrasing away dates, filters, or grouping.
        """

        return run_analyze_headcount_tool(
            question,
            service=active_service,
        )

    return analyze_headcount_tool


def create_stateful_analyze_headcount_tool(
    service: HeadcountService | None = None,
) -> BaseTool:
    """Create the conversation-state-aware Headcount tool."""

    base_headcount_tool = (
        create_analyze_headcount_tool(
            service=service,
        )
    )

    @stateful_tool(
        ANALYZE_HEADCOUNT_TOOL_NAME,
        args_schema=AnalyzeHeadcountToolInput,
    )
    def analyze_headcount_tool(
        question: str,
        # Must stay a bare `ToolRuntime`. LangChain matches this exact
        # annotation to inject the runtime, so `Optional[ToolRuntime]` (or
        # any stringized form under `from __future__ import annotations`)
        # silently leaves it None and the ToolMessage id stops matching.
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """Analyze Headcount and preserve the result in chat state.

        Pass the user's complete Headcount question. Do not use this
        tool for attrition prediction or replacement recommendations.
        """

        try:
            result = base_headcount_tool.invoke({
                "question": question,
            })
        except Exception:
            # Without this the real cause is replaced by a friendly
            # message and lost entirely, which is how a total headcount
            # outage can look like a working agent.
            logger.exception(
                "analyze_headcount failed for question: %r",
                question,
            )
            result = {
                "status": "error",
                "question": question,
                "message": (
                    "The Headcount analysis service could not "
                    "complete this request."
                ),
            }

        status = str(
            result.get(
                "status",
                "error",
            )
        )

        state_update: dict[str, Any] = {
            "last_user_intent": "headcount",
            "last_tool_status": status,
            "last_headcount_question": question,
            "last_error_message": None,
        }

        if status in {
            "success",
            "partial",
        }:
            state_update.update({
                "last_headcount_result": result,
            })
        else:
            state_update.update({
                "last_headcount_result": result,
                "last_error_message": result.get(
                    "message",
                    (
                        "The Headcount analysis could not "
                        "be completed."
                    ),
                ),
            })

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

    return analyze_headcount_tool
