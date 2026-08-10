"""Build immutable, scenario-specific context from current HR truth."""

from __future__ import annotations

from .errors import SimulationDataError
from .repository import SimulationRepository


class SimulationContextBuilder:
    def __init__(self, repository: SimulationRepository):
        self.repository = repository

    def employee_promotion(self, employee_id: str, target_position_id: str) -> dict:
        employee_context = self.repository.employee_context(employee_id)
        target_position = self.repository.resolve_position(target_position_id)
        target_budget = self.repository.position_budget(target_position_id)
        target_business = self.repository.position_business(target_position_id)

        if target_business is None:
            raise SimulationDataError(
                f"No simulation business evaluation exists for target position {target_position_id}."
            )

        return {
            **employee_context,
            "target_position": target_position,
            "target_position_budget": target_budget,
            "target_position_business": target_business,
            "employee_skills": self.repository.employee_skills(employee_id),
            "target_skill_requirements": self.repository.position_skill_requirements(
                target_position_id
            ),
        }
