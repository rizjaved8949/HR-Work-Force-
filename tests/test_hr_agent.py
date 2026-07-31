"""End-to-end test for the HR reasoning agent."""

import sys
from pathlib import Path

# Make the backend package importable when this test is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import json
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
# HELPER FUNCTION
# ============================================================

def extract_last_assistant_message(
    result: dict[str, Any],
) -> str:
    """
    Extract the latest assistant response from agent state.
    """

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


# ============================================================
# LOAD EXISTING HR TOOLS
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
# CREATE THE MAIN REASONING AGENT
# ============================================================

print("Creating HR reasoning agent...")

hr_agent = create_hr_reasoning_agent(
    employee_search_tool=employee_search_tool,
    attrition_prediction_tool=attrition_prediction_tool,
    data_path=DATA_PATH,
)


# ============================================================
# ONE SESSION / ONE CONVERSATION THREAD
# ============================================================

config = {
    "configurable": {
        "thread_id": "HR-AGENT-TEST-001"
    }
}


# ============================================================
# TURN 1 — ATTRITION REQUEST
# ============================================================

print("\n" + "=" * 70)
print("TURN 1")
print("=" * 70)

first_result = hr_agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "EMP004 ka attrition risk batao."
                ),
            }
        ]
    },
    config=config,
)

print("\nAssistant response:\n")
print(
    extract_last_assistant_message(
        first_result
    )
)


# ============================================================
# CHECK STRUCTURED MEMORY AFTER TURN 1
# ============================================================

first_snapshot = hr_agent.get_state(config)
first_state = first_snapshot.values

print("\nStored conversation state:\n")

print(
    json.dumps(
        {
            "selected_employee_id": first_state.get(
                "selected_employee_id"
            ),
            "selected_employee_name": first_state.get(
                "selected_employee_name"
            ),
            "selected_department": first_state.get(
                "selected_department"
            ),
            "selected_designation": first_state.get(
                "selected_designation"
            ),
            "last_user_intent": first_state.get(
                "last_user_intent"
            ),
            "last_attrition_result": first_state.get(
                "last_attrition_result"
            ),
            "replacement_offer_pending": first_state.get(
                "replacement_offer_pending"
            ),
            "last_tool_status": first_state.get(
                "last_tool_status"
            ),
        },
        indent=2,
        ensure_ascii=False,
        default=str,
    )
)


# ============================================================
# TURN 2 — MEMORY TEST
# ============================================================

print("\n" + "=" * 70)
print("TURN 2")
print("=" * 70)

second_result = hr_agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Ab batao hum kis employee ki "
                    "baat kar rahe hain?"
                ),
            }
        ]
    },
    config=config,
)

print("\nAssistant response:\n")
print(
    extract_last_assistant_message(
        second_result
    )
)


# ============================================================
# FINAL MEMORY CHECK
# ============================================================

final_snapshot = hr_agent.get_state(config)
final_state = final_snapshot.values

print("\nFinal selected employee:\n")

print(
    json.dumps(
        {
            "employee_id": final_state.get(
                "selected_employee_id"
            ),
            "employee_name": final_state.get(
                "selected_employee_name"
            ),
            "department": final_state.get(
                "selected_department"
            ),
        },
        indent=2,
        ensure_ascii=False,
        default=str,
    )
)