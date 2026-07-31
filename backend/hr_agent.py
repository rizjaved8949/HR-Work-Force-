"""Create and configure the main HR reasoning agent."""

from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from resilient_model import ResilientChatOpenAI

from agent_prompts import HR_AGENT_SYSTEM_PROMPT
from agent_state import HRAgentState
from agent_tools import (
    create_stateful_check_employee_attrition_tool,
)
from replacement_tool import (
    create_replacement_recommendation_tool,
    create_stateful_replacement_recommendation_tool,
)
from settings import get_llm_settings


# ============================================================
# AGENT FACTORY
# ============================================================

def create_hr_reasoning_agent(
    employee_search_tool: BaseTool,
    attrition_prediction_tool: BaseTool,
    data_path: str | Path,
) -> Any:
    """
    Create the main multilingual HR reasoning agent.

    The existing employee-search and CatBoost tools are passed
    into this function from the FastAPI application. This keeps
    the model and CSV data loaded only once.

    The agent exposes two high-level tools, check_employee_attrition
    and recommend_replacement, and the local successor LangGraph uses
    the same CSV data folder as the attrition workflow.
    """

    # --------------------------------------------------------
    # LOAD OPENROUTER CONFIGURATION FROM .env
    # --------------------------------------------------------

    # Every value below comes from the single project .env. Nothing
    # about the model is hardcoded here, so switching models is a
    # one-line edit in .env with no code change.
    llm = get_llm_settings()

    # --------------------------------------------------------
    # CREATE THE OPENROUTER REASONING MODEL
    # --------------------------------------------------------

    # OpenRouter exposes an OpenAI-compatible API, so an OpenAI client is
    # pointed at the OpenRouter base URL. This avoids depending on a
    # separate OpenRouter integration package.
    #
    # The Resilient subclass additionally retries provider errors that
    # OpenRouter returns inside a 200 response, which the OpenAI SDK's own
    # max_retries never sees.
    model = ResilientChatOpenAI(
        model=llm.model,
        api_key=llm.api_key,
        base_url=llm.base_url,
        temperature=llm.temperature,
        max_tokens=llm.max_tokens,
        max_retries=llm.max_retries,
        timeout=llm.timeout_seconds,
        transient_max_attempts=llm.max_retries + 1,

        # Turns off the model's chain of thought when OPENROUTER_REASONING
        # is "off". Those tokens are pure latency for this workload.
        extra_body=llm.extra_body(),

        # OpenRouter uses these for attribution on its dashboard.
        default_headers={
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "HR Workforce Intelligence Backend",
        },
    )

    # --------------------------------------------------------
    # CREATE THE HIGH-LEVEL ATTRITION TOOL
    # --------------------------------------------------------

    check_employee_attrition_tool = (
        create_stateful_check_employee_attrition_tool(
            employee_search_tool=employee_search_tool,
            attrition_prediction_tool=(
                attrition_prediction_tool
            ),
        )
    )
    # --------------------------------------------------------
    # CREATE THE REPLACEMENT TOOL
    # --------------------------------------------------------

    # This base tool calls the local successor LangGraph directly.
    base_replacement_tool = (
        create_replacement_recommendation_tool(
            data_dir=data_path,
        )
    )

    # This state-aware wrapper can reuse the employee ID stored
    # in the current LangGraph conversation memory.
    recommend_replacement_tool = (
        create_stateful_replacement_recommendation_tool(
            replacement_tool=base_replacement_tool,
        )
    )
    # --------------------------------------------------------
    # CREATE DEVELOPMENT CONVERSATION MEMORY
    # --------------------------------------------------------

    # Memory is maintained separately for every thread_id.
    # It remains available while the FastAPI server is running.
    # It resets when the server is restarted.
    checkpointer = InMemorySaver()

    # --------------------------------------------------------
    # CREATE THE MAIN HR AGENT
    # --------------------------------------------------------

    hr_agent = create_agent(
        model=model,

        # Expose only the two tested high-level HR tools.
        # Internal employee search and CatBoost tools are not
        # directly exposed to the reasoning model.
        tools=[
            check_employee_attrition_tool,
            recommend_replacement_tool,
        ],

        # Detailed permanent instructions created in Task 5.
        system_prompt=HR_AGENT_SYSTEM_PROMPT,

        # Structured employee and workflow memory created
        # in Task 8.
        state_schema=HRAgentState,

        # Thread-based in-server conversation memory.
        checkpointer=checkpointer,
    )

    return hr_agent