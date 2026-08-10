"""Deterministic department people-budget change simulation."""

from __future__ import annotations

from ..config import SIMULATION_ENGINE_VERSION
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationValidationError
from ..impact_engine import SimulationImpactEngine
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine
from .common import integer, number


class BudgetChangeEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.BUDGET_CHANGE:
            raise SimulationValidationError("BudgetChangeEngine received the wrong scenario type.")
        if not request.department_id:
            raise SimulationValidationError("department_id is required for budget_change.")

        change_pct = number(request.parameters.get("change_percentage"), 0.0)
        if change_pct == 0:
            raise SimulationValidationError("parameters.change_percentage must be non-zero.")
        if change_pct <= -100:
            raise SimulationValidationError("Budget reduction cannot be 100% or more.")

        ctx = self.context_builder.department(request.department_id)
        hc = ctx["headcount"] or {}
        budget = ctx.get("department_budget") or {}

        current_budget = number(budget.get("Total_Approved_People_Budget"), number(hc.get("Total_Approved_People_Budget")))
        actual_cost = number(budget.get("Total_Actual_People_Cost"), number(hc.get("Total_Actual_People_Cost")))
        current_remaining = current_budget - actual_cost
        new_budget = round(current_budget * (1.0 + change_pct / 100.0), 2)
        new_remaining = round(new_budget - actual_cost, 2)
        utilization = round((actual_cost / new_budget) * 100.0, 2) if new_budget > 0 else 999.0

        current_hc = integer(hc.get("Actual_Employee_Count"))
        monthly_salary_cost = number(hc.get("Monthly_Salary_Cost"))
        avg_monthly_employee_cost = monthly_salary_cost / max(current_hc, 1)
        affordable_additional_hc = max(int(new_remaining // avg_monthly_employee_cost), 0) if avg_monthly_employee_cost > 0 else 0

        if utilization > 100:
            budget_risk = "critical"
            decision_score = 35.0
        elif utilization >= 90:
            budget_risk = "high"
            decision_score = 60.0
        else:
            budget_risk = "low"
            decision_score = 85.0

        warnings: list[str] = []
        if new_remaining < 0:
            warnings.append("Simulated budget is below the latest actual people cost; the department enters a budget deficit.")

        return SimulationResponse(
            scenario_type=ScenarioType.BUDGET_CHANGE,
            status="completed",
            baseline={
                "department_id": request.department_id,
                "department": hc.get("Department_Name"),
                "current_people_budget_pkr": round(current_budget, 2),
                "current_actual_people_cost_pkr": round(actual_cost, 2),
                "current_remaining_budget_pkr": round(current_remaining, 2),
                "current_budget_utilization_pct": round((actual_cost / current_budget) * 100.0, 2) if current_budget > 0 else 0.0,
                "current_headcount": current_hc,
            },
            simulated_state={
                "change_percentage": change_pct,
                "simulated_people_budget_pkr": new_budget,
                "simulated_remaining_budget_pkr": new_remaining,
                "simulated_budget_utilization_pct": utilization,
                "estimated_affordable_additional_headcount": affordable_additional_hc,
            },
            impact={
                "budget_direction": "increase" if change_pct > 0 else "decrease",
                "budget_risk": budget_risk,
                "decision_score_pct": decision_score,
                "decision_status": SimulationImpactEngine.decision_from_score(decision_score),
            },
            assumptions={
                "engine_version": SIMULATION_ENGINE_VERSION,
                "calculation_type": "deterministic_what_if",
                "mutates_source_data": False,
                "affordable_headcount_method": "remaining simulated people budget divided by current average monthly salary cost per employee",
            },
            warnings=warnings,
        )
