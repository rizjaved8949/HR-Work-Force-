"""Deterministic Employee Promotion what-if simulation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..config import (
    JOB_LEVEL_ORDER,
    PROMOTION_FINAL_WEIGHTS,
    READINESS_BANDS,
    SIMULATION_ENGINE_VERSION,
)
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationDataError, SimulationValidationError
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _readiness_band(score: float) -> str:
    for threshold, label in READINESS_BANDS:
        if score >= threshold:
            return label
    return "not_ready"


def _target_skill_fit(
    employee_skills: pd.DataFrame,
    requirements: pd.DataFrame,
) -> dict:
    if requirements.empty:
        return {
            "target_skill_match_pct": 100.0,
            "mandatory_skill_coverage_pct": 100.0,
            "missing_skill_count": 0,
            "missing_mandatory_skill_count": 0,
            "missing_skills": [],
            "missing_mandatory_skills": [],
        }

    skill_map = {
        str(row["Skill_ID"]): row
        for _, row in employee_skills.iterrows()
    }

    total_weight = 0.0
    earned_weight = 0.0
    mandatory_total = 0
    mandatory_met = 0
    missing_skills: list[str] = []
    missing_mandatory: list[str] = []

    for _, req in requirements.iterrows():
        skill_id = str(req["Skill_ID"])
        skill_name = str(req.get("Skill_Name", skill_id))
        min_prof = max(_number(req.get("Minimum_Proficiency_Level"), 1.0), 1.0)
        min_score = max(_number(req.get("Minimum_Skill_Score"), 1.0), 1.0)
        weight = max(_number(req.get("Skill_Weight_pct"), 0.0), 0.0)
        mandatory = str(req.get("Mandatory_Flag", "No")).strip().lower() == "yes"

        current = skill_map.get(skill_id)
        if current is None:
            proficiency = 0.0
            skill_score = 0.0
        else:
            proficiency = _number(current.get("Proficiency_Level"), 0.0)
            skill_score = _number(current.get("Skill_Score"), 0.0)

        proficiency_ratio = min(proficiency / min_prof, 1.0)
        score_ratio = min(skill_score / min_score, 1.0)
        requirement_fit = min(proficiency_ratio, score_ratio)

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

    target_skill_match = (
        100.0 if total_weight <= 0 else (earned_weight / total_weight) * 100.0
    )
    mandatory_coverage = (
        100.0 if mandatory_total == 0 else (mandatory_met / mandatory_total) * 100.0
    )

    return {
        "target_skill_match_pct": round(target_skill_match, 2),
        "mandatory_skill_coverage_pct": round(mandatory_coverage, 2),
        "missing_skill_count": len(missing_skills),
        "missing_mandatory_skill_count": len(missing_mandatory),
        "missing_skills": missing_skills,
        "missing_mandatory_skills": missing_mandatory,
    }


class EmployeePromotionEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.EMPLOYEE_PROMOTION:
            raise SimulationValidationError("EmployeePromotionEngine received the wrong scenario type.")
        if not request.employee_id:
            raise SimulationValidationError("employee_id is required for employee_promotion.")
        if not request.target_position_id:
            raise SimulationValidationError("target_position_id is required for employee_promotion.")

        context = self.context_builder.employee_promotion(
            request.employee_id,
            request.target_position_id,
        )

        employee = context["employee"]
        current_position = context["position"]
        target_position = context["target_position"]
        features = context["simulation_features"] or {}
        department_business = context["department_business"] or {}
        target_business = context["target_position_business"] or {}
        headcount = context["headcount"] or {}

        current_level = str(employee.get("Job_Level", ""))
        target_level = str(target_position.get("Job_Level", ""))
        if current_level not in JOB_LEVEL_ORDER or target_level not in JOB_LEVEL_ORDER:
            raise SimulationValidationError(
                f"Unsupported job-level mapping: current={current_level!r}, target={target_level!r}."
            )
        if JOB_LEVEL_ORDER[target_level] <= JOB_LEVEL_ORDER[current_level]:
            raise SimulationValidationError(
                "employee_promotion requires a target position at a higher Job_Level."
            )

        current_department = str(employee.get("Department_ID"))
        target_department = str(target_position.get("Department_ID"))
        if target_department != current_department:
            raise SimulationValidationError(
                "Cross-department movement belongs to employee_transfer. "
                "For employee_promotion, choose a higher-level position in the employee's current department."
            )

        fit = _target_skill_fit(
            context["employee_skills"],
            context["target_skill_requirements"],
        )

        base_readiness = _number(features.get("Promotion_Base_Readiness_Score_pct"))
        final_readiness = (
            base_readiness * PROMOTION_FINAL_WEIGHTS["base_readiness"]
            + fit["target_skill_match_pct"] * PROMOTION_FINAL_WEIGHTS["target_skill_match"]
            + fit["mandatory_skill_coverage_pct"]
            * PROMOTION_FINAL_WEIGHTS["mandatory_skill_coverage"]
        )
        final_readiness = round(min(max(final_readiness, 0.0), 100.0), 2)

        current_budget = context.get("position_budget") or {}
        target_budget = context.get("target_position_budget") or {}
        current_annual_cost = _number(current_budget.get("Total_Annual_Position_Cost_Budget"))
        target_annual_cost = _number(target_budget.get("Total_Annual_Position_Cost_Budget"))
        annual_cost_change = round(target_annual_cost - current_annual_cost, 2)

        promotion_admin_cost = _number(
            department_business.get("Promotion_Admin_Cost_PKR")
        )
        ramp_up_days = int(
            round(
                _number(
                    target_business.get("Promotion_Ramp_Up_Days"),
                    _number(department_business.get("Average_Promotion_Ramp_Up_Days")),
                )
            )
        )

        target_status = str(target_position.get("Position_Status", "Unknown"))
        target_available = target_status.strip().lower() == "vacant"
        source_position_becomes_vacant = True

        current_hc = int(_number(headcount.get("Actual_Employee_Count")))
        current_vacancies = int(_number(headcount.get("Vacant_Approved_Position_Count")))
        simulated_vacancies = current_vacancies
        if target_available:
            # Filling one vacancy and opening the employee's former position offsets.
            simulated_vacancies = current_vacancies
        else:
            # Planning-only promotion into an occupied target cannot be executed as-is.
            simulated_vacancies = current_vacancies + 1

        warnings: list[str] = []
        if not target_available:
            warnings.append(
                "Target position is currently filled. The role-fit and cost analysis is valid, "
                "but the move is planning-only until a vacancy/new position exists."
            )
        if fit["missing_mandatory_skill_count"] > 0:
            warnings.append(
                "Employee has mandatory skill gaps for the target role."
            )

        if fit["missing_mandatory_skill_count"] > 0:
            skill_gap_risk = "high"
        elif fit["target_skill_match_pct"] < 75:
            skill_gap_risk = "medium"
        else:
            skill_gap_risk = "low"

        business_impact_score = _number(target_business.get("Business_Impact_Score_1_5"))
        readiness_band = _readiness_band(final_readiness)

        baseline = {
            "employee_id": employee["Employee_ID"],
            "employee_name": employee.get("Employee_Name"),
            "department_id": current_department,
            "department": employee.get("Department"),
            "current_position_id": current_position.get("Position_ID"),
            "current_position_title": current_position.get("Position_Title"),
            "current_job_level": current_level,
            "promotion_base_readiness_score_pct": round(base_readiness, 2),
            "current_role_skill_coverage_pct": _number(
                features.get("Current_Role_Skill_Coverage_pct")
            ),
            "department_headcount": current_hc,
            "department_vacancies": current_vacancies,
            "current_annual_position_cost_budget_pkr": current_annual_cost,
        }

        simulated_state = {
            "target_position_id": target_position.get("Position_ID"),
            "target_position_title": target_position.get("Position_Title"),
            "target_job_level": target_level,
            "target_position_status": target_status,
            "target_position_available": target_available,
            "target_role_skill_match_pct": fit["target_skill_match_pct"],
            "mandatory_skill_coverage_pct": fit["mandatory_skill_coverage_pct"],
            "missing_skill_count": fit["missing_skill_count"],
            "missing_mandatory_skill_count": fit["missing_mandatory_skill_count"],
            "missing_skills": fit["missing_skills"],
            "missing_mandatory_skills": fit["missing_mandatory_skills"],
            "promotion_ramp_up_days": ramp_up_days,
            "promotion_admin_cost_pkr": promotion_admin_cost,
            "target_annual_position_cost_budget_pkr": target_annual_cost,
            "annual_position_cost_change_pkr": annual_cost_change,
            "source_position_becomes_vacant": source_position_becomes_vacant,
            "simulated_department_headcount": current_hc,
            "simulated_department_vacancies": simulated_vacancies,
        }

        impact = {
            "promotion_readiness_score_pct": final_readiness,
            "promotion_readiness_band": readiness_band,
            "skill_gap_risk": skill_gap_risk,
            "business_impact_score_1_5": business_impact_score,
            "budget_direction": (
                "increase" if annual_cost_change > 0 else "decrease" if annual_cost_change < 0 else "neutral"
            ),
            "execution_feasibility": "feasible" if target_available else "planning_only",
        }

        assumptions = {
            "engine_version": SIMULATION_ENGINE_VERSION,
            "calculation_type": "deterministic_what_if",
            "mutates_source_data": False,
            "promotion_score_weights": PROMOTION_FINAL_WEIGHTS,
            "source_of_truth": "existing Data/*.csv plus Data/Simulation business assumptions",
            "note": (
                "The simulation does not change Employee_Profile, Position_Master, budget, headcount, "
                "or any existing pipeline. It calculates a hypothetical state only."
            ),
        }

        return SimulationResponse(
            scenario_type=ScenarioType.EMPLOYEE_PROMOTION,
            status="completed",
            baseline=baseline,
            simulated_state=simulated_state,
            impact=impact,
            assumptions=assumptions,
            warnings=warnings,
        )
