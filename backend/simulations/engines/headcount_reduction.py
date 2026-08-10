"""Deterministic department headcount-reduction simulation."""

from __future__ import annotations

import math

from ..config import SIMULATION_ENGINE_VERSION
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationValidationError
from ..impact_engine import SimulationImpactEngine
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine
from .common import integer, number


class HeadcountReductionEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.HEADCOUNT_REDUCTION:
            raise SimulationValidationError("HeadcountReductionEngine received the wrong scenario type.")
        if not request.department_id:
            raise SimulationValidationError("department_id is required for headcount_reduction.")

        ctx = self.context_builder.department(request.department_id)
        hc = ctx["headcount"] or {}
        business = ctx.get("department_business") or {}
        demand = ctx.get("demand_driver") or {}

        current_hc = integer(hc.get("Actual_Employee_Count"))
        if current_hc <= 0:
            raise SimulationValidationError("Department has no current employees to reduce.")

        reduce_by = request.parameters.get("reduce_by")
        reduction_pct = request.parameters.get("reduction_percentage")
        if reduce_by is None and reduction_pct is None:
            raise SimulationValidationError("Provide parameters.reduce_by or parameters.reduction_percentage.")
        if reduce_by is None:
            reduce_by = math.ceil(current_hc * max(number(reduction_pct), 0.0) / 100.0)
        reduce_by = integer(reduce_by)
        if reduce_by <= 0 or reduce_by >= current_hc:
            raise SimulationValidationError("Headcount reduction must be greater than 0 and lower than current headcount.")

        simulated_hc = current_hc - reduce_by
        current_vacancies = integer(hc.get("Vacant_Approved_Position_Count"))
        simulated_vacancies = current_vacancies + reduce_by
        monthly_salary_cost = number(hc.get("Monthly_Salary_Cost"))
        avg_monthly_cost = monthly_salary_cost / current_hc
        monthly_saving = round(avg_monthly_cost * reduce_by, 2)
        simulated_monthly_cost = round(max(monthly_salary_cost - monthly_saving, 0.0), 2)

        expected_staffing_need = integer(demand.get("Expected_Staffing_Need"), current_hc)
        minimum_operational_hc = integer(business.get("Minimum_Operational_Headcount"))
        workload_index = round((expected_staffing_need / max(simulated_hc, 1)) * 100.0, 2)
        current_workload_index = round((expected_staffing_need / max(current_hc, 1)) * 100.0, 2)
        workload_increase = round(workload_index - current_workload_index, 2)

        capacity_gap = max(expected_staffing_need - simulated_hc, 0)
        below_minimum = bool(minimum_operational_hc and simulated_hc < minimum_operational_hc)
        risk_score = min(100.0, max(workload_index - 70.0, 0.0) + (25.0 if below_minimum else 0.0))
        risk_band = SimulationImpactEngine.risk_band(risk_score)

        warnings: list[str] = []
        if below_minimum:
            warnings.append("Simulated headcount falls below the department's minimum operational headcount assumption.")
        if capacity_gap > 0:
            warnings.append("Simulated headcount is below the latest expected staffing need.")

        decision_score = max(0.0, 100.0 - risk_score)

        return SimulationResponse(
            scenario_type=ScenarioType.HEADCOUNT_REDUCTION,
            status="completed",
            baseline={
                "department_id": request.department_id,
                "department": hc.get("Department_Name"),
                "current_headcount": current_hc,
                "current_vacancies": current_vacancies,
                "monthly_salary_cost_pkr": monthly_salary_cost,
                "expected_staffing_need": expected_staffing_need,
                "minimum_operational_headcount": minimum_operational_hc,
                "workload_index_pct": current_workload_index,
            },
            simulated_state={
                "reduce_by": reduce_by,
                "simulated_headcount": simulated_hc,
                "simulated_vacancies": simulated_vacancies,
                "simulated_monthly_salary_cost_pkr": simulated_monthly_cost,
                "estimated_monthly_salary_saving_pkr": monthly_saving,
                "workload_index_pct": workload_index,
                "workload_increase_points": workload_increase,
                "capacity_gap_headcount": capacity_gap,
                "below_minimum_operational_headcount": below_minimum,
            },
            impact={
                "operational_risk_score_pct": round(risk_score, 2),
                "operational_risk_band": risk_band,
                "financial_direction": "saving",
                "decision_score_pct": round(decision_score, 2),
                "decision_status": SimulationImpactEngine.decision_from_score(decision_score),
            },
            assumptions={
                "engine_version": SIMULATION_ENGINE_VERSION,
                "calculation_type": "deterministic_what_if",
                "mutates_source_data": False,
                "salary_saving_method": "current department average monthly salary cost multiplied by reduced headcount",
            },
            warnings=warnings,
        )
