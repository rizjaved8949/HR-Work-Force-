"""Step-1 Scenario Simulation data service.

No scenario is executed here yet.  This service is deliberately limited to
proving that the new layer can load and combine existing HR data with the new
simulation-only feature/assumption data without changing the old pipelines.
"""

from __future__ import annotations

from .repository import SimulationRepository


class SimulationDataService:
    def __init__(self, repository: SimulationRepository):
        self.repository = repository

    def health(self) -> dict:
        validation = self.repository.validate()
        return {
            "status": "ready",
            "layer": "scenario_simulation_data",
            "validation": validation,
        }

    def get_employee_context(self, employee_id: str) -> dict:
        return self.repository.employee_context(employee_id)

    def list_scenarios(self) -> list[dict]:
        catalog = self.repository.get("scenario_catalog")
        return catalog.to_dict(orient="records")
