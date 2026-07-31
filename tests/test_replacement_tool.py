"""Test the merged local successor LangGraph with EMP004."""

import sys
from pathlib import Path

# Make the backend package importable when this test is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import json
import time

from replacement_tool import create_replacement_recommendation_tool


from paths import data_dir

DATA_PATH = data_dir()

replacement_tool = create_replacement_recommendation_tool(
    data_dir=DATA_PATH,
)

print("Running local replacement workflow for EMP004...")
start_time = time.perf_counter()

result = replacement_tool.invoke({
    "employee_id": "EMP004",
})

elapsed = time.perf_counter() - start_time

print(json.dumps(result, indent=2, ensure_ascii=False))
print(f"\nResponse time: {elapsed:.2f} seconds")

if result.get("status") != "completed":
    raise RuntimeError(
        f"Local replacement test failed: {result}"
    )

print("Local replacement test passed successfully.")
