"""Tests for Headcount integration with the HR agent tool pattern."""

import json
import sys
from pathlib import Path

import pytest
from langgraph.types import Command


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


import paths
from headcount.repository import HeadcountRepository
from headcount.service import HeadcountService
from headcount.tool import (
    ANALYZE_HEADCOUNT_TOOL_NAME,
    create_analyze_headcount_tool,
    create_stateful_analyze_headcount_tool,
)


@pytest.fixture
def service() -> HeadcountService:
    return HeadcountService(
        HeadcountRepository(paths.data_dir())
    )


def metric_values(result: dict[str, object]) -> dict[str, object]:
    metrics = result.get("metrics", [])
    assert isinstance(metrics, list)
    return {
        str(metric["metric_name"]): metric["value"]
        for metric in metrics
        if isinstance(metric, dict)
    }


def test_base_langchain_tool_returns_headcount(
    service: HeadcountService,
) -> None:
    tool = create_analyze_headcount_tool(service)

    assert tool.name == ANALYZE_HEADCOUNT_TOOL_NAME

    result = tool.invoke({
        "question": "What is our current employee headcount?",
    })

    assert result["status"] == "success"
    assert metric_values(result)["actual_employee_count"] == 720


def test_stateful_tool_updates_headcount_state(
    service: HeadcountService,
) -> None:
    tool = create_stateful_analyze_headcount_tool(service)

    command = tool.invoke({
        "question": "How is the vacancy rate calculated?",
    })

    assert isinstance(command, Command)

    update = command.update
    assert update["last_user_intent"] == "headcount"
    assert update["last_tool_status"] == "success"
    assert (
        update["last_headcount_question"]
        == "How is the vacancy rate calculated?"
    )
    assert update["last_headcount_result"]["status"] == "success"
    assert len(update["last_headcount_result"]["records"]) == 1


def test_stateful_tool_message_is_json(
    service: HeadcountService,
) -> None:
    tool = create_stateful_analyze_headcount_tool(service)

    command = tool.invoke({
        "question": "Show current workforce availability.",
    })

    messages = command.update["messages"]
    assert len(messages) == 1

    payload = json.loads(messages[0].content)
    assert payload["status"] == "success"


def test_headcount_call_does_not_clear_employee_context(
    service: HeadcountService,
) -> None:
    tool = create_stateful_analyze_headcount_tool(service)

    command = tool.invoke({
        "question": "Show Engineering headcount.",
    })

    update = command.update
    assert "selected_employee_id" not in update
    assert "last_attrition_result" not in update
    assert "last_replacement_result" not in update
