"""Deterministic employee skill-gap / reskilling simulation."""

from __future__ import annotations

from ..config import SIMULATION_ENGINE_VERSION
from ..context_builder import SimulationContextBuilder
from ..errors import SimulationValidationError
from ..impact_engine import SimulationImpactEngine
from ..schemas import ScenarioType, SimulationRequest, SimulationResponse
from .base import BaseScenarioEngine
from .common import number


class SkillReskillingEngine(BaseScenarioEngine):
    def __init__(self, context_builder: SimulationContextBuilder):
        self.context_builder = context_builder

    def run(self, request: SimulationRequest) -> SimulationResponse:
        if request.scenario_type != ScenarioType.SKILL_RESKILLING:
            raise SimulationValidationError("SkillReskillingEngine received the wrong scenario type.")
        if not request.employee_id:
            raise SimulationValidationError("employee_id is required for skill_reskilling.")
        course_id = request.parameters.get("course_id")
        if not course_id:
            raise SimulationValidationError("parameters.course_id is required for skill_reskilling.")

        ctx = self.context_builder.reskilling(request.employee_id, str(course_id))
        employee = ctx["employee"]
        features = ctx.get("simulation_features") or {}
        course = ctx["course"]
        employee_skills = ctx["employee_skills"]

        skill_id = str(course.get("Skill_ID"))
        skill_rows = employee_skills[employee_skills["Skill_ID"].astype(str) == skill_id]
        if skill_rows.empty:
            current_proficiency = 0.0
            current_skill_score = 0.0
        else:
            row = skill_rows.iloc[0]
            current_proficiency = number(row.get("Proficiency_Level"))
            current_skill_score = number(row.get("Skill_Score"))

        expected_lift = number(course.get("Expected_Productivity_Lift_pct"))
        # Conservative what-if: use the course productivity-lift assumption as a
        # bounded improvement to skill score; never claim guaranteed proficiency.
        estimated_post_skill_score = round(min(100.0, current_skill_score + expected_lift), 2)
        readiness = number(features.get("Reskilling_Base_Readiness_Score_pct"))
        need = number(features.get("Reskilling_Need_Score_pct"))
        cost = number(course.get("Estimated_Training_Cost_PKR"))
        time_to_competency = int(round(number(course.get("Expected_Time_to_Competency_Days"))))
        adoption = number(course.get("Target_Application_Adoption_pct"))

        outcome_score = round(
            min(100.0, readiness * 0.55 + (100.0 - need) * 0.15 + adoption * 0.20 + min(expected_lift * 5.0, 100.0) * 0.10),
            2,
        )

        warnings: list[str] = []
        if need < 20:
            warnings.append("Employee has a low current reskilling-need score; verify that this course aligns with a real role or business requirement.")

        return SimulationResponse(
            scenario_type=ScenarioType.SKILL_RESKILLING,
            status="completed",
            baseline={
                "employee_id": employee.get("Employee_ID"),
                "employee_name": employee.get("Employee_Name"),
                "department_id": employee.get("Department_ID"),
                "position_id": employee.get("Position_ID"),
                "position_title": employee.get("Position_Title"),
                "reskilling_base_readiness_score_pct": round(readiness, 2),
                "reskilling_need_score_pct": round(need, 2),
                "skill_id": skill_id,
                "skill_name": course.get("Skill_Name"),
                "current_proficiency_level": current_proficiency,
                "current_skill_score": current_skill_score,
            },
            simulated_state={
                "course_id": course.get("Course_ID"),
                "course_name": course.get("Course_Name"),
                "course_level": course.get("Course_Level"),
                "estimated_training_cost_pkr": cost,
                "expected_productivity_lift_pct": expected_lift,
                "expected_time_to_competency_days": time_to_competency,
                "target_application_adoption_pct": adoption,
                "estimated_post_training_skill_score": estimated_post_skill_score,
            },
            impact={
                "reskilling_outcome_score_pct": outcome_score,
                "readiness_band": SimulationImpactEngine.readiness_band(outcome_score),
                "decision_score_pct": outcome_score,
                "decision_status": SimulationImpactEngine.decision_from_score(outcome_score),
            },
            assumptions={
                "engine_version": SIMULATION_ENGINE_VERSION,
                "calculation_type": "deterministic_what_if",
                "mutates_source_data": False,
                "causal_claim": False,
                "note": "Post-training values are scenario estimates from explicit business assumptions, not guaranteed performance outcomes.",
            },
            warnings=warnings,
        )
