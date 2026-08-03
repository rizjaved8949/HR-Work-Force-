"""Deterministic local test for the People at Risk dashboard pipeline."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

for path in (REPO_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("SUCCESSOR_LLM_ENABLED", "false")

import paths  # noqa: E402
from visualizations.attrition.people_at_risk_service import (  # noqa: E402
    PeopleAtRiskService,
)


data_dir = paths.data_dir()
model_path = paths.model_path()
service = PeopleAtRiskService(
    data_dir=data_dir,
    model_path=model_path,
    replacement_tool=None,
)

summary = service.get_summary()

assert summary["total_employees"] == 200
assert summary["people_at_risk"] > 0
assert (
    summary["people_at_risk"] + summary["people_not_at_risk"]
    == summary["total_employees"]
)

department_risk = service.get_department_risk()
assert department_risk["status"] == "success"
assert department_risk["departments"]
assert (
    sum(item["people_at_risk"] for item in department_risk["departments"])
    == summary["people_at_risk"]
)
assert department_risk["highest_risk_department"] == department_risk["departments"][0]

risk_list = service.get_people_at_risk(limit=5)
assert risk_list["total_matching"] == summary["people_at_risk"]
assert len(risk_list["employees"]) == 5

first_employee = risk_list["employees"][0]
assert first_employee["employee_id"]
assert first_employee["employee_name"]
assert first_employee["position_title"]
assert first_employee["position_criticality"]
assert first_employee["risk_score_percent"] >= 50

profile = service.get_employee_profile(first_employee["employee_id"])
assert profile["employee_profile"]["Employee_ID"] == first_employee["employee_id"]
assert "position_criticality" in profile

detail = service.get_employee_detail(first_employee["employee_id"])
assert detail["employee"]["employee_id"] == first_employee["employee_id"]
assert detail["attrition"]["factors"]
assert detail["replacement_status"] == "unavailable"
assert detail["recommended_replacements"] == []

print("=" * 70)
print("PEOPLE AT RISK PIPELINE TEST PASSED")
print("=" * 70)
print(f"Data directory: {data_dir}")
print(f"Model path: {model_path}")
print(f"Total employees: {summary['total_employees']}")
print(f"People at risk: {summary['people_at_risk']}")
print(f"Risk rate: {summary['attrition_risk_rate_percent']}%")
print(
    "Highest-risk department by count: "
    f"{department_risk['highest_risk_department']['department']} "
    f"({department_risk['highest_risk_department']['people_at_risk']} people)"
)
print(f"Detail employee: {first_employee['employee_id']}")
print(f"Replacement candidates: {len(detail['recommended_replacements'])}")
