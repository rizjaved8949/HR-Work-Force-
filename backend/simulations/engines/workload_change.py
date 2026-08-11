"""Deterministic business-demand / workload change simulation."""

from __future__ import annotations

import math

from ..config import SIMULATION_ENGINE_VERSION
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationValidationError
from ..impact_engine import SimulationImpactEngine
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine
from .common import integer, number


class BusinessDemandChangeEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.BUSINESS_DEMAND_CHANGE:
            raise SimulationValidationError("BusinessDemandChangeEngine received the wrong scenario type.")
        if not request.department_id:
            raise SimulationValidationError("department_id is required for business_demand_change.")

        change_pct = number(request.parameters.get("demand_change_percentage"), 0.0)
        if change_pct == 0:
            raise SimulationValidationError("parameters.demand_change_percentage must be non-zero.")
        if change_pct <= -100:
            raise SimulationValidationError("Demand decrease cannot be 100% or more.")

        ctx = self.context_builder.department(request.department_id)
        hc = ctx["headcount"] or {}
        demand = ctx.get("demand_driver") or {}
        business = ctx.get("department_business") or {}

        current_hc = integer(hc.get("Actual_Employee_Count"))
        current_demand = number(demand.get("Demand_Driver_Value"))
        current_staffing_need = integer(demand.get("Expected_Staffing_Need"), current_hc)
        new_demand = round(current_demand * (1.0 + change_pct / 100.0), 2)
        new_staffing_need = max(1, math.ceil(current_staffing_need * (1.0 + change_pct / 100.0)))
        headcount_gap = new_staffing_need - current_hc
        workload_index = round((new_staffing_need / max(current_hc, 1)) * 100.0, 2)
        threshold = number(business.get("Workload_Risk_Threshold_pct"), 90.0)
        max_sustainable = number(business.get("Maximum_Sustainable_Utilization_pct"), 95.0)
        overtime_capacity = number(business.get("Max_Overtime_Capacity_pct"), 0.0)

        if workload_index > max_sustainable + overtime_capacity:
            risk = "critical"
            risk_score = 90.0
        elif workload_index > max_sustainable:
            risk = "high"
            risk_score = 75.0
        elif workload_index > threshold:
            risk = "medium"
            risk_score = 55.0
        else:
            risk = "low"
            risk_score = 25.0

        additional_hc_needed = max(headcount_gap, 0)
        potential_surplus_hc = max(-headcount_gap, 0)
        monthly_salary_cost = number(hc.get("Monthly_Salary_Cost"))
        avg_monthly_cost = monthly_salary_cost / max(current_hc, 1)
        estimated_monthly_cost_for_gap = round(avg_monthly_cost * additional_hc_needed, 2)
        decision_score = max(0.0, 100.0 - risk_score)

        warnings: list[str] = []
        if additional_hc_needed > 0:
            warnings.append("Latest demand-adjusted staffing need exceeds current headcount.")

        return SimulationResponse(
            scenario_type=ScenarioType.BUSINESS_DEMAND_CHANGE,
            status="completed",
            baseline={
                "department_id": request.department_id,
                "department": hc.get("Department_Name"),
                "demand_driver_name": demand.get("Demand_Driver_Name"),
                "measurement_unit": demand.get("Measurement_Unit"),
                "current_demand": current_demand,
                "current_expected_staffing_need": current_staffing_need,
                "current_headcount": current_hc,
            },
            simulated_state={
                "demand_change_percentage": change_pct,
                "simulated_demand": new_demand,
                "simulated_expected_staffing_need": new_staffing_need,
                "headcount_gap": headcount_gap,
                "additional_headcount_needed": additional_hc_needed,
                "potential_surplus_headcount": potential_surplus_hc,
                "workload_index_pct": workload_index,
                "estimated_monthly_salary_cost_for_gap_pkr": estimated_monthly_cost_for_gap,
            },
            impact={
                "workload_risk": risk,
                "workload_risk_score_pct": risk_score,
                "capacity_direction": "pressure_increase" if change_pct > 0 else "pressure_decrease",
                "decision_score_pct": decision_score,
                "decision_status": SimulationImpactEngine.decision_from_score(decision_score),
            },
            assumptions={
                "engine_version": SIMULATION_ENGINE_VERSION,
                "calculation_type": "deterministic_what_if",
                "mutates_source_data": False,
                "staffing_need_method": "latest expected staffing need scaled proportionally with demand change",
            },
            warnings=warnings,
        )
