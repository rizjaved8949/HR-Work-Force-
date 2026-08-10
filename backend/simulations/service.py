"""Scenario Simulation application service.

Step 2 activates the deterministic engine architecture and the first locked
scenario: Employee Promotion. The remaining six scenario codes remain locked
in the catalog and will be plugged into the same registry in later steps.
"""

from __future__ import annotations

from .context_builder import SimulationContextBuilder
from .engines import EmployeePromotionEngine
from .errors import SimulationScenarioNotImplementedError
from .repository import SimulationRepository
from .schemas import ScenarioType, SimulationRequest, SimulationResponse


class SimulationDataService:
    """Backwards-compatible Step-1 read-only data helper."""

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


class SimulationService:
    """Entry point used later by both API and chatbot adapters."""

    def __init__(self, repository: SimulationRepository):
        self.repository = repository
        context_builder = SimulationContextBuilder(repository)
        self._engines = {
            ScenarioType.EMPLOYEE_PROMOTION: EmployeePromotionEngine(context_builder),
        }

    def run(self, request: SimulationRequest) -> SimulationResponse:
        engine = self._engines.get(request.scenario_type)
        if engine is None:
            raise SimulationScenarioNotImplementedError(
                f"Scenario {request.scenario_type.value!r} is locked in the catalog "
                "but its engine is not implemented in Step 2 yet."
            )
        return engine.run(request)
