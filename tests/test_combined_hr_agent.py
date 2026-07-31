"""Test the merged HR agent with attrition and local replacement workflows."""

import sys
from pathlib import Path

# Make the backend package importable when this test is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import json
import time
from typing import Any

from employee_record_tool import create_employee_record_tool
from attrition_prediction_tool import create_attrition_prediction_tool
from hr_agent import create_hr_reasoning_agent


# ============================================================
# PROJECT PATHS
# ============================================================

from paths import data_dir, model_path

DATA_PATH = data_dir()

MODEL_PATH = model_path()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def extract_last_assistant_message(
    result: dict[str, Any],
) -> str:
    """Return the latest assistant message from agent state."""

    messages = result.get("messages", [])

    # The last message is not always the answer: an assistant message may
    # carry only tool calls, or null content. Scan backwards for the most
    # recent assistant message that actually contains text.
    for message in reversed(messages):
        if getattr(message, "type", "") != "ai":
            continue

        content = getattr(message, "content", "")

        if isinstance(content, str):
            if content.strip():
                return content
            continue

        if isinstance(content, list):
            text = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if text.strip():
                return text

    return "No assistant response was returned."


def show_agent_state(
    agent: Any,
    config: dict[str, Any],
    heading: str,
) -> dict[str, Any]:
    """Display important structured memory fields."""

    snapshot = agent.get_state(config)
    state = dict(snapshot.values)

    selected_state = {
        "selected_employee_id": state.get(
            "selected_employee_id"
        ),
        "selected_employee_name": state.get(
            "selected_employee_name"
        ),
        "selected_department": state.get(
            "selected_department"
        ),
        "last_user_intent": state.get(
            "last_user_intent"
        ),
        "last_attrition_result": state.get(
            "last_attrition_result"
        ),
        "replacement_offer_pending": state.get(
            "replacement_offer_pending"
        ),
        "replacement_tool_available": state.get(
            "replacement_tool_available"
        ),
        "last_tool_status": state.get(
            "last_tool_status"
        ),
        "last_replacement_result": state.get(
            "last_replacement_result"
        ),
        "last_error_message": state.get(
            "last_error_message"
        ),
    }

    print("\n" + heading)

    print(
        json.dumps(
            selected_state,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    return state


# ============================================================
# LOAD LOCAL ATTRITION TOOLS
# ============================================================

print("Loading employee records...")

employee_search_tool = create_employee_record_tool(
    DATA_PATH
)

print("Loading CatBoost attrition model...")

attrition_prediction_tool = (
    create_attrition_prediction_tool(
        MODEL_PATH
    )
)


# ============================================================
# CREATE MERGED MAIN HR AGENT
# ============================================================

print("Creating merged HR reasoning agent...")

hr_agent = create_hr_reasoning_agent(
    employee_search_tool=employee_search_tool,
    attrition_prediction_tool=attrition_prediction_tool,
    data_path=DATA_PATH,
)

# ============================================================
# SAME SESSION FOR BOTH TURNS
# ============================================================

config = {
    "configurable": {
        "thread_id": "MERGED-EMP004-TEST-001"
    }
}


# ============================================================
# TURN 1 — ATTRITION REQUEST
# ============================================================

print("\n" + "=" * 70)
print("TURN 1 — ATTRITION FOR EMP004")
print("=" * 70)

turn_1_start = time.perf_counter()

first_result = hr_agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "EMP004 ka attrition risk check karo."
                ),
            }
        ]
    },
    config=config,
)

turn_1_time = time.perf_counter() - turn_1_start

print("\nAssistant response:\n")
print(
    extract_last_assistant_message(
        first_result
    )
)

print(f"\nTurn 1 response time: {turn_1_time:.2f} seconds")

show_agent_state(
    agent=hr_agent,
    config=config,
    heading="State after Turn 1:",
)


# ============================================================
# TURN 2 — REPLACEMENT FOLLOW-UP
# ============================================================

print("\n" + "=" * 70)
print("TURN 2 — LOCAL REPLACEMENT FOR SAME EMPLOYEE")
print("=" * 70)

turn_2_start = time.perf_counter()

second_result = hr_agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Haan, isi employee ke top replacement "
                    "candidates batao."
                ),
            }
        ]
    },
    config=config,
)

turn_2_time = time.perf_counter() - turn_2_start

print("\nAssistant response:\n")
print(
    extract_last_assistant_message(
        second_result
    )
)

print(f"\nTurn 2 response time: {turn_2_time:.2f} seconds")

final_state = show_agent_state(
    agent=hr_agent,
    config=config,
    heading="State after Turn 2:",
)


# ============================================================
# FINAL VALIDATION
# ============================================================

selected_employee_id = final_state.get(
    "selected_employee_id"
)

replacement_result = final_state.get(
    "last_replacement_result"
)

if selected_employee_id != "EMP004":
    raise RuntimeError(
        "Employee memory test failed. "
        f"Expected EMP004, received {selected_employee_id}."
    )

if not replacement_result:
    raise RuntimeError(
        "Replacement result was not saved in agent memory."
    )

if replacement_result.get("status") != "completed":
    raise RuntimeError(
        "Replacement workflow did not complete successfully. "
        f"Status: {replacement_result.get('status')}"
    )

candidates = replacement_result.get(
    "recommended_successors",
    [],
)

if not candidates:
    raise RuntimeError(
        "No replacement candidates were returned."
    )


print("\n" + "=" * 70)
print("MERGED COMBINED AGENT TEST PASSED")
print("=" * 70)

print("Remembered employee:", selected_employee_id)
print("Replacement candidates:", len(candidates))
print(f"Attrition turn time: {turn_1_time:.2f} seconds")
print(f"Replacement turn time: {turn_2_time:.2f} seconds")