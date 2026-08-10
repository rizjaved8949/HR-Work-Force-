"""Scenario Simulation application services.

All seven locked what-if scenarios are deterministic. This service is the
single calculation entry point that will later be reused by both the dedicated
Scenario Simulator API and the HR-agent tool adapter.
"""

from __future__ import annotations

from .context_builder import SimulationContextBuilder
from .engines import (
    BudgetChangeEngine,
    BusinessDemandChangeEngine,
    EmployeePromotionEngine,
    EmployeeTransferEngine,
    HeadcountReductionEngine,
    SkillReskillingEngine,
    WorkforceExpansionEngine,
)
from .errors import SimulationScenarioNotImplementedError
from .repository import SimulationRepository
from .schemas import ScenarioType, SimulationRequest, SimulationResponse


class SimulationDataService:
    """Read-only helper used by tests and future UI lookup endpoints."""

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

    def get_department_context(self, department_id: str) -> dict:
        return self.repository.department_context(department_id)

    def list_scenarios(self) -> list[dict]:
        catalog = self.repository.get("scenario_catalog")
        return catalog.to_dict(orient="records")


class SimulationService:
    """Single deterministic calculation entry point for all seven scenarios."""

    def __init__(self, repository: SimulationRepository):
        self.repository = repository
        context_builder = SimulationContextBuilder(repository)
        self._engines = {
            ScenarioType.EMPLOYEE_PROMOTION: EmployeePromotionEngine(context_builder),
            ScenarioType.EMPLOYEE_TRANSFER: EmployeeTransferEngine(context_builder),
            ScenarioType.HEADCOUNT_REDUCTION: HeadcountReductionEngine(context_builder),
            ScenarioType.WORKFORCE_EXPANSION: WorkforceExpansionEngine(context_builder),
            ScenarioType.BUDGET_CHANGE: BudgetChangeEngine(context_builder),
            ScenarioType.SKILL_RESKILLING: SkillReskillingEngine(context_builder),
            ScenarioType.BUSINESS_DEMAND_CHANGE: BusinessDemandChangeEngine(context_builder),
        }

    def run(self, request: SimulationRequest) -> SimulationResponse:
        engine = self._engines.get(request.scenario_type)
        if engine is None:
            raise SimulationScenarioNotImplementedError(
                f"No engine is registered for scenario {request.scenario_type.value!r}."
            )
        return engine.run(request)
