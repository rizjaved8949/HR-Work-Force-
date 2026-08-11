"""Isolated tests for the state-aware employee profile adapter."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("langchain")
pytest.importorskip("langgraph")

from langgraph.types import Command


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from employee_profile_tool import (
    EMPLOYEE_PROFILE_TOOL_NAME,
    create_stateful_employee_record_tool,
)
from employee_record_tool import create_employee_record_tool
import paths


@pytest.fixture(scope="module")
def profile_tool():
    base_tool = create_employee_record_tool(paths.data_dir())
    return create_stateful_employee_record_tool(base_tool)


def test_profile_tool_reuses_existing_employee_lookup(profile_tool) -> None:
    assert profile_tool.name == EMPLOYEE_PROFILE_TOOL_NAME

    command = profile_tool.invoke({"employee_id": "EMP004"})

    assert isinstance(command, Command)
    update = command.update
    assert update["last_tool_status"] == "found"
    assert update["last_user_intent"] == "employee_profile"
    assert update["selected_employee_id"] == "EMP004"
    assert update["selected_employee_name"] == "Ali Masood"
    assert update["selected_department"] == "Finance"
    assert update["selected_designation"] == "Financial Analyst"


def test_profile_tool_preserves_full_employee_record(profile_tool) -> None:
    command = profile_tool.invoke({"employee_id": "EMP004"})
    result = command.update["last_employee_record_result"]

    assert result["status"] == "found"
    profile = result["records"]["profile"]
    assert profile["Work_Mode"] == "Onsite"
    assert profile["Employment_Type"] == "Permanent"
    assert profile["Employee_Status"] == "Active"


def test_profile_tool_does_not_invent_missing_marital_status(profile_tool) -> None:
    command = profile_tool.invoke({"employee_id": "EMP004"})
    result = command.update["last_employee_record_result"]
    profile = result["records"]["profile"]

    normalized_keys = {
        str(key).casefold().replace("_", "")
        for key in profile
    }
    assert "maritalstatus" not in normalized_keys


def test_ambiguous_name_sets_clarification_without_guessing(profile_tool) -> None:
    command = profile_tool.invoke({"employee_name": "Ali"})
    update = command.update

    assert update["last_tool_status"] == "needs_clarification"
    assert update["last_user_intent"] == "clarification"
    assert update["pending_clarification"] is True
    assert len(update["pending_candidates"]) > 1
    assert update["selected_employee_id"] is None
    assert update["pending_original_request"]["intent"] == "employee_profile"


def test_tool_message_contains_valid_json(profile_tool) -> None:
    command = profile_tool.invoke({"employee_id": "EMP004"})
    messages = command.update["messages"]

    assert len(messages) == 1
    payload = json.loads(messages[0].content)
    assert payload["status"] == "found"
    assert payload["employee"]["employee_id"] == "EMP004"


def test_profile_lookup_does_not_modify_other_pipeline_state_fields(profile_tool) -> None:
    command = profile_tool.invoke({"employee_id": "EMP004"})
    update = command.update

    # The adapter must not clear, recalculate, or overwrite any analytical
    # workflow result. Those tools remain independent.
    assert "last_attrition_result" not in update
    assert "last_replacement_result" not in update
    assert "last_headcount_result" not in update
    assert "last_performance_result" not in update
