"""Deterministic workforce expansion / hiring simulation."""

from __future__ import annotations

from ..config import SIMULATION_ENGINE_VERSION
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationValidationError
from ..impact_engine import SimulationImpactEngine
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine
from .common import integer, number


class WorkforceExpansionEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.WORKFORCE_EXPANSION:
            raise SimulationValidationError("WorkforceExpansionEngine received the wrong scenario type.")
        if not request.department_id:
            raise SimulationValidationError("department_id is required for workforce_expansion.")

        add_headcount = integer(request.parameters.get("add_headcount"))
        if add_headcount <= 0:
            raise SimulationValidationError("parameters.add_headcount must be greater than zero.")

        ctx = self.context_builder.department(request.department_id)
        hc = ctx["headcount"] or {}
        business = ctx.get("department_business") or {}
        budget = ctx.get("department_budget") or {}
        demand = ctx.get("demand_driver") or {}

        current_hc = integer(hc.get("Actual_Employee_Count"))
        current_vacancies = integer(hc.get("Vacant_Approved_Position_Count"))
        funded_vacancies = integer(hc.get("Funded_Vacant_Position_Count"))
        approved_positions = integer(hc.get("Approved_Position_Count"))
        monthly_salary_cost = number(hc.get("Monthly_Salary_Cost"))
        avg_monthly_cost = monthly_salary_cost / max(current_hc, 1)

        hires_into_existing_vacancies = min(add_headcount, current_vacancies)
        new_positions_required = max(add_headcount - current_vacancies, 0)
        simulated_hc = current_hc + add_headcount
        simulated_vacancies = max(current_vacancies - hires_into_existing_vacancies, 0)
        simulated_approved_positions = approved_positions + new_positions_required

        onboarding_per_hire = number(business.get("Average_Onboarding_Cost_PKR"))
        onboarding_cost = round(onboarding_per_hire * add_headcount, 2)
        monthly_salary_increase = round(avg_monthly_cost * add_headcount, 2)
        simulated_monthly_salary_cost = round(monthly_salary_cost + monthly_salary_increase, 2)

        current_budget_total = number(budget.get("Total_Approved_People_Budget"), number(hc.get("Total_Approved_People_Budget")))
        current_actual_cost = number(budget.get("Total_Actual_People_Cost"), number(hc.get("Total_Actual_People_Cost")))
        monthly_budget_impact = monthly_salary_increase + onboarding_cost
        projected_cost = current_actual_cost + monthly_budget_impact
        projected_utilization = round((projected_cost / current_budget_total) * 100.0, 2) if current_budget_total > 0 else 0.0

        expected_staffing_need = integer(demand.get("Expected_Staffing_Need"), current_hc)
        baseline_gap = max(expected_staffing_need - current_hc, 0)
        simulated_gap = max(expected_staffing_need - simulated_hc, 0)
        demand_gap_improvement = baseline_gap - simulated_gap

        budget_risk = "critical" if projected_utilization > 100 else "high" if projected_utilization >= 90 else "low"
        decision_score = 80.0
        if new_positions_required > 0:
            decision_score -= 10.0
        if budget_risk == "high":
            decision_score -= 15.0
        elif budget_risk == "critical":
            decision_score -= 35.0
        if demand_gap_improvement > 0:
            decision_score += 10.0
        decision_score = max(0.0, min(decision_score, 100.0))

        warnings: list[str] = []
        if add_headcount > funded_vacancies:
            warnings.append("Requested hires exceed currently funded vacancies; additional establishment/budget approval may be required.")
        if projected_utilization > 100:
            warnings.append("Projected people cost exceeds the latest approved department people budget.")

        return SimulationResponse(
            scenario_type=ScenarioType.WORKFORCE_EXPANSION,
            status="completed",
            baseline={
                "department_id": request.department_id,
                "department": hc.get("Department_Name"),
                "current_headcount": current_hc,
                "approved_positions": approved_positions,
                "current_vacancies": current_vacancies,
                "funded_vacancies": funded_vacancies,
                "monthly_salary_cost_pkr": monthly_salary_cost,
                "expected_staffing_need": expected_staffing_need,
                "demand_gap_headcount": baseline_gap,
            },
            simulated_state={
                "add_headcount": add_headcount,
                "simulated_headcount": simulated_hc,
                "simulated_approved_positions": simulated_approved_positions,
                "simulated_vacancies": simulated_vacancies,
                "hires_into_existing_vacancies": hires_into_existing_vacancies,
                "new_positions_required": new_positions_required,
                "estimated_monthly_salary_increase_pkr": monthly_salary_increase,
                "estimated_onboarding_cost_pkr": onboarding_cost,
                "simulated_monthly_salary_cost_pkr": simulated_monthly_salary_cost,
                "projected_budget_utilization_pct": projected_utilization,
                "demand_gap_headcount": simulated_gap,
                "demand_gap_improvement_headcount": demand_gap_improvement,
            },
            impact={
                "budget_risk": budget_risk,
                "capacity_direction": "increase",
                "decision_score_pct": round(decision_score, 2),
                "decision_status": SimulationImpactEngine.decision_from_score(decision_score),
            },
            assumptions={
                "engine_version": SIMULATION_ENGINE_VERSION,
                "calculation_type": "deterministic_what_if",
                "mutates_source_data": False,
                "new_hire_salary_method": "current department average monthly salary cost per employee",
            },
            warnings=warnings,
        )
