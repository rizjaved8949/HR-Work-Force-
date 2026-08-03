"""FastAPI routes for the attrition dashboard pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from .people_at_risk_service import PeopleAtRiskService


def create_attrition_dashboard_router(
    data_dir: str | Path,
    model_path: str | Path,
    replacement_tool: Optional[Any] = None,
) -> APIRouter:
    """Create the dashboard router while reusing already-loaded app resources."""

    service = PeopleAtRiskService(
        data_dir=data_dir,
        model_path=model_path,
        replacement_tool=replacement_tool,
    )

    router = APIRouter(
        prefix="/api/v1/dashboard/attrition",
        tags=["Attrition Dashboard"],
    )

    @router.get("/summary")
    def get_people_at_risk_summary():
        """Return the People at Risk card totals."""

        return service.get_summary()

    @router.get("/department-risk")
    def get_department_risk():
        """Return ranked attrition-risk counts for every department."""

        return service.get_department_risk()

    @router.get("/top-risk-drivers")
    def get_top_risk_drivers(
        limit: int = Query(default=3, ge=1, le=10),
    ):
        """Return the most common model-derived drivers for at-risk staff."""

        return service.get_top_risk_drivers(limit=limit)

    @router.get("/people-at-risk")
    def get_people_at_risk(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        department: Optional[str] = None,
        position_criticality: Optional[str] = None,
        search: Optional[str] = None,
    ):
        """Return the ranked, filterable list behind the card."""

        return service.get_people_at_risk(
            offset=offset,
            limit=limit,
            department=department,
            position_criticality=position_criticality,
            search=search,
        )

    @router.get("/people-at-risk/{employee_id}")
    def get_people_at_risk_detail(employee_id: str):
        """Return factors plus successor recommendations for one at-risk employee."""

        try:
            return service.get_employee_detail(employee_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"Employee {employee_id.strip().upper()} was not found.",
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @router.get("/employees/{employee_id}/profile")
    def get_employee_profile(employee_id: str):
        """Return Employee_Profile.csv fields and position criticality."""

        try:
            return service.get_employee_profile(employee_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"Employee {employee_id.strip().upper()} was not found.",
            )

    @router.post("/refresh")
    def refresh_attrition_dashboard():
        """Force data reload after adding or changing employee rows."""

        return service.refresh(force=True)

    return router
