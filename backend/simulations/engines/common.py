"""Shared numeric and skill-fit helpers for deterministic simulations."""

from __future__ import annotations

from typing import Any

import pandas as pd


def number(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    return int(round(number(value, float(default))))


def target_skill_fit(employee_skills: pd.DataFrame, requirements: pd.DataFrame) -> dict:
    if requirements.empty:
        return {
            "target_skill_match_pct": 100.0,
            "mandatory_skill_coverage_pct": 100.0,
            "missing_skill_count": 0,
            "missing_mandatory_skill_count": 0,
            "missing_skills": [],
            "missing_mandatory_skills": [],
        }

    skill_map = {str(row["Skill_ID"]): row for _, row in employee_skills.iterrows()}
    total_weight = 0.0
    earned_weight = 0.0
    mandatory_total = 0
    mandatory_met = 0
    missing_skills: list[str] = []
    missing_mandatory: list[str] = []

    for _, req in requirements.iterrows():
        skill_id = str(req["Skill_ID"])
        skill_name = str(req.get("Skill_Name", skill_id))
        min_prof = max(number(req.get("Minimum_Proficiency_Level"), 1.0), 1.0)
        min_score = max(number(req.get("Minimum_Skill_Score"), 1.0), 1.0)
        weight = max(number(req.get("Skill_Weight_pct"), 0.0), 0.0)
        mandatory = str(req.get("Mandatory_Flag", "No")).strip().lower() == "yes"

        current = skill_map.get(skill_id)
        proficiency = number(current.get("Proficiency_Level"), 0.0) if current is not None else 0.0
        skill_score = number(current.get("Skill_Score"), 0.0) if current is not None else 0.0

        requirement_fit = min(min(proficiency / min_prof, 1.0), min(skill_score / min_score, 1.0))
        total_weight += weight
        earned_weight += weight * requirement_fit

        met = proficiency >= min_prof and skill_score >= min_score
        if not met:
            missing_skills.append(skill_name)
        if mandatory:
            mandatory_total += 1
            if met:
                mandatory_met += 1
            else:
                missing_mandatory.append(skill_name)

    skill_match = 100.0 if total_weight <= 0 else (earned_weight / total_weight) * 100.0
    mandatory_coverage = 100.0 if mandatory_total == 0 else (mandatory_met / mandatory_total) * 100.0
    return {
        "target_skill_match_pct": round(skill_match, 2),
        "mandatory_skill_coverage_pct": round(mandatory_coverage, 2),
        "missing_skill_count": len(missing_skills),
        "missing_mandatory_skill_count": len(missing_mandatory),
        "missing_skills": missing_skills,
        "missing_mandatory_skills": missing_mandatory,
    }
