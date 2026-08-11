"""Deterministic Employee Transfer what-if simulation."""

from __future__ import annotations

from ..config import SIMULATION_ENGINE_VERSION, TRANSFER_FINAL_WEIGHTS
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationValidationError
from ..impact_engine import SimulationImpactEngine
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine
from .common import integer, number, target_skill_fit


class EmployeeTransferEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.EMPLOYEE_TRANSFER:
            raise SimulationValidationError("EmployeeTransferEngine received the wrong scenario type.")
        if not request.employee_id:
            raise SimulationValidationError("employee_id is required for employee_transfer.")
        if not request.target_department_id:
            raise SimulationValidationError("target_department_id is required for employee_transfer.")
        if not request.target_position_id:
            raise SimulationValidationError("target_position_id is required for employee_transfer.")

        context = self.context_builder.employee_transfer(
            request.employee_id,
            request.target_department_id,
            request.target_position_id,
        )

        employee = context["employee"]
        source_department_id = str(employee.get("Department_ID"))
        target_department_id = str(request.target_department_id)
        if source_department_id == target_department_id:
            raise SimulationValidationError(
                "employee_transfer requires a different target department. Use employee_promotion for same-department progression."
            )

        target_position = context["target_position"]
        target_status = str(target_position.get("Position_Status", "Unknown"))
        target_available = target_status.strip().lower() == "vacant"
        fit = target_skill_fit(context["employee_skills"], context["target_skill_requirements"])

        features = context.get("simulation_features") or {}
        base_readiness = number(features.get("Transfer_Base_Readiness_Score_pct"))
        final_readiness = (
            base_readiness * TRANSFER_FINAL_WEIGHTS["base_readiness"]
            + fit["target_skill_match_pct"] * TRANSFER_FINAL_WEIGHTS["target_skill_match"]
            + fit["mandatory_skill_coverage_pct"] * TRANSFER_FINAL_WEIGHTS["mandatory_skill_coverage"]
        )
        final_readiness = round(max(0.0, min(final_readiness, 100.0)), 2)

        source_hc = context["source_department"]["headcount"] or {}
        target_hc = context["target_department"]["headcount"] or {}
        source_current = integer(source_hc.get("Actual_Employee_Count"))
        target_current = integer(target_hc.get("Actual_Employee_Count"))
        source_vacancies = integer(source_hc.get("Vacant_Approved_Position_Count"))
        target_vacancies = integer(target_hc.get("Vacant_Approved_Position_Count"))

        source_sim_hc = max(source_current - 1, 0)
        target_sim_hc = target_current + 1
        source_sim_vacancies = source_vacancies + 1
        target_sim_vacancies = max(target_vacancies - (1 if target_available else 0), 0)

        current_budget = context.get("position_budget") or {}
        target_budget = context.get("target_position_budget") or {}
        current_annual_cost = number(current_budget.get("Total_Annual_Position_Cost_Budget"))
        target_annual_cost = number(target_budget.get("Total_Annual_Position_Cost_Budget"))
        annual_cost_change = round(target_annual_cost - current_annual_cost, 2)

        target_business = context.get("target_position_business") or {}
        target_department_business = context["target_department"].get("department_business") or {}
        transfer_admin_cost = number(target_department_business.get("Transfer_Admin_Cost_PKR"))
        ramp_up_days = integer(
            target_business.get("Transfer_Ramp_Up_Days"),
            integer(target_department_business.get("Average_Transfer_Ramp_Up_Days"), 30),
        )

        warnings: list[str] = []
        if not target_available:
            warnings.append(
                "Target position is currently filled. The transfer can be evaluated, but execution is planning-only until a vacancy/new position exists."
            )
        if fit["missing_mandatory_skill_count"]:
            warnings.append("Employee has mandatory skill gaps for the target position.")

        source_min_hc = integer(
            (context["source_department"].get("department_business") or {}).get("Minimum_Operational_Headcount")
        )
        source_operational_risk = "high" if source_min_hc and source_sim_hc < source_min_hc else "low"
        skill_risk = (
            "high" if fit["missing_mandatory_skill_count"] > 0
            else "medium" if fit["target_skill_match_pct"] < 75
            else "low"
        )

        decision_score = final_readiness
        if not target_available:
            decision_score -= 10
        if source_operational_risk == "high":
            decision_score -= 10
        decision_score = round(max(0.0, min(decision_score, 100.0)), 2)

        return SimulationResponse(
            scenario_type=ScenarioType.EMPLOYEE_TRANSFER,
            status="completed",
            baseline={
                "employee_id": employee.get("Employee_ID"),
                "employee_name": employee.get("Employee_Name"),
                "source_department_id": source_department_id,
                "source_department": employee.get("Department"),
                "current_position_id": employee.get("Position_ID"),
                "current_position_title": employee.get("Position_Title"),
                "source_headcount": source_current,
                "source_vacancies": source_vacancies,
                "target_department_id": target_department_id,
                "target_headcount": target_current,
                "target_vacancies": target_vacancies,
                "transfer_base_readiness_score_pct": round(base_readiness, 2),
                "current_annual_position_cost_budget_pkr": current_annual_cost,
            },
            simulated_state={
                "target_position_id": target_position.get("Position_ID"),
                "target_position_title": target_position.get("Position_Title"),
                "target_position_status": target_status,
                "target_position_available": target_available,
                "source_headcount": source_sim_hc,
                "target_headcount": target_sim_hc,
                "source_vacancies": source_sim_vacancies,
                "target_vacancies": target_sim_vacancies,
                "organization_headcount_change": 0,
                "target_role_skill_match_pct": fit["target_skill_match_pct"],
                "mandatory_skill_coverage_pct": fit["mandatory_skill_coverage_pct"],
                "missing_skills": fit["missing_skills"],
                "missing_mandatory_skills": fit["missing_mandatory_skills"],
                "transfer_ramp_up_days": ramp_up_days,
                "transfer_admin_cost_pkr": transfer_admin_cost,
                "target_annual_position_cost_budget_pkr": target_annual_cost,
                "annual_position_cost_change_pkr": annual_cost_change,
            },
            impact={
                "transfer_readiness_score_pct": final_readiness,
                "transfer_readiness_band": SimulationImpactEngine.readiness_band(final_readiness),
                "skill_gap_risk": skill_risk,
                "source_operational_risk": source_operational_risk,
                "budget_direction": "increase" if annual_cost_change > 0 else "decrease" if annual_cost_change < 0 else "neutral",
                "execution_feasibility": "feasible" if target_available else "planning_only",
                "decision_score_pct": decision_score,
                "decision_status": SimulationImpactEngine.decision_from_score(decision_score),
            },
            assumptions={
                "engine_version": SIMULATION_ENGINE_VERSION,
                "calculation_type": "deterministic_what_if",
                "mutates_source_data": False,
                "transfer_score_weights": TRANSFER_FINAL_WEIGHTS,
            },
            warnings=warnings,
        )
