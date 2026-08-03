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

attrition_rate = service.get_attrition_rate_overview()
assert attrition_rate["status"] == "success"
assert attrition_rate["total_employees"] == summary["total_employees"]
assert attrition_rate["people_at_risk"] == summary["people_at_risk"]
assert attrition_rate["people_not_at_risk"] == summary["people_not_at_risk"]
assert (
    sum(segment["employee_count"] for segment in attrition_rate["chart"]["segments"])
    == summary["total_employees"]
)
assert round(
    sum(segment["percentage"] for segment in attrition_rate["chart"]["segments"]),
    2,
) == 100.0

department_risk = service.get_department_risk()
assert department_risk["status"] == "success"
assert department_risk["departments"]
assert (
    sum(item["people_at_risk"] for item in department_risk["departments"])
    == summary["people_at_risk"]
)
assert department_risk["highest_risk_department"] == department_risk["departments"][0]

top_drivers = service.get_top_risk_drivers(limit=3)
assert top_drivers["status"] == "success"
assert top_drivers["people_at_risk"] == summary["people_at_risk"]
assert 1 <= len(top_drivers["drivers"]) <= 3
assert top_drivers["top_driver"] == top_drivers["drivers"][0]
assert top_drivers["total_reason_mentions"] > 0
assert (
    sum(segment["value"] for segment in top_drivers["chart_segments"])
    == top_drivers["total_reason_mentions"]
)

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
    "Attrition Rate card: "
    f"{attrition_rate['attrition_rate_percent']}% "
    f"({attrition_rate['people_at_risk']} of "
    f"{attrition_rate['total_employees']} employees)"
)
print(
    "Highest-risk department by count: "
    f"{department_risk['highest_risk_department']['department']} "
    f"({department_risk['highest_risk_department']['people_at_risk']} people)"
)
print(
    "Top model risk driver: "
    f"{top_drivers['top_driver']['label']} "
    f"({top_drivers['top_driver']['mention_count']} mentions, "
    f"{top_drivers['top_driver']['share_percent']}%)"
)
print(f"Detail employee: {first_employee['employee_id']}")
print(f"Replacement candidates: {len(detail['recommended_replacements'])}")
