"""FastAPI router for the dedicated Scenario Simulator UI.

This router is additive and isolated. It receives shared service instances so
it does not reload data or duplicate simulation calculations.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .errors import (
    SimulationDataError,
    SimulationEmployeeNotFoundError,
    SimulationPositionNotFoundError,
    SimulationValidationError,
)
from .lookup_service import SimulationLookupService
from .schemas import ScenarioType, SimulationRequest, SimulationResponse
from .service import SimulationDataService, SimulationService


def create_simulation_router(
    simulation_service: SimulationService,
    data_service: SimulationDataService,
    lookup_service: SimulationLookupService,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/simulations",
        tags=["Scenario Simulation"],
    )

    @router.get("/health")
    def health() -> dict:
        return data_service.health()

    @router.get("/scenarios")
    def scenarios() -> dict:
        return {"scenarios": lookup_service.list_scenarios()}

    @router.get("/employees")
    def employees(
        query: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=50),
    ) -> dict:
        return {
            "query": query,
            "employees": lookup_service.search_employees(query=query, limit=limit),
        }

    @router.get("/employees/{employee_id}/context")
    def employee_context(employee_id: str) -> dict:
        try:
            return lookup_service.employee_context(employee_id)
        except SimulationEmployeeNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/departments")
    def departments(
        query: str = "",
        limit: int = Query(50, ge=1, le=100),
    ) -> dict:
        return {
            "departments": lookup_service.list_departments(query=query, limit=limit),
        }

    @router.get("/options")
    def options(
        scenario_type: ScenarioType,
        employee_id: str | None = None,
        department_id: str | None = None,
        target_department_id: str | None = None,
        query: str = "",
        limit: int = Query(100, ge=1, le=100),
    ) -> dict:
        try:
            return lookup_service.scenario_options(
                scenario_type=scenario_type,
                employee_id=employee_id,
                department_id=department_id,
                target_department_id=target_department_id,
                query=query,
                limit=limit,
            )
        except (SimulationDataError, SimulationValidationError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/run", response_model=SimulationResponse)
    def run_simulation(request: SimulationRequest) -> SimulationResponse:
        try:
            return simulation_service.run(request)
        except (SimulationEmployeeNotFoundError, SimulationPositionNotFoundError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (SimulationDataError, SimulationValidationError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router
