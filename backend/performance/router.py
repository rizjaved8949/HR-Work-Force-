"""FastAPI routes for deterministic Employee Performance analytics."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from performance.schemas import AnalyzePerformanceInput, PerformanceToolResult
from performance.service import PerformanceService


def create_performance_router(service: PerformanceService) -> APIRouter:
    """Create the isolated Performance API router.

    Register this router in app.py only after the isolated Performance tests pass.
    """

    router = APIRouter(tags=["Employee Performance"])

    @router.post(
        "/pipeline/performance",
        response_model=PerformanceToolResult,
        summary="Analyze Employee Performance",
    )
    def analyze_performance(request: AnalyzePerformanceInput) -> PerformanceToolResult:
        return service.analyze(request)

    @router.get("/api/v1/dashboard/performance/overview")
    def performance_overview(
        month: date | None = None,
        department: str | None = None,
        role_band: str | None = None,
    ) -> dict:
        return service.dashboard.overview(
            month=month,
            department=department,
            role_band=role_band,
        )

    @router.get("/api/v1/dashboard/performance/trend")
    def performance_trend(
        months: int = Query(default=12, ge=1, le=24),
        department: str | None = None,
        role_band: str | None = None,
    ) -> list[dict]:
        return service.dashboard.organization_trend(
            months=months,
            department=department,
            role_band=role_band,
        )

    @router.get("/api/v1/dashboard/performance/departments")
    def performance_departments(
        month: date | None = None,
        limit: int = Query(default=16, ge=1, le=100),
    ) -> list[dict]:
        return service.dashboard.department_ranking(month=month, limit=limit)

    @router.get("/api/v1/dashboard/performance/distribution")
    def performance_distribution(
        month: date | None = None,
        department: str | None = None,
        role_band: str | None = None,
    ) -> list[dict]:
        return service.dashboard.distribution(
            month=month,
            department=department,
            role_band=role_band,
        )

    @router.get("/api/v1/dashboard/performance/attention")
    def performance_attention(
        department: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict]:
        return service.dashboard.attention(department=department, limit=limit)

    @router.get("/api/v1/dashboard/performance/employees/{employee_id}")
    def employee_evaluation(employee_id: str) -> PerformanceToolResult:
        return service.analyze(
            AnalyzePerformanceInput(
                question=f"Give me the complete performance evaluation for {employee_id}",
                employee_id=employee_id,
            )
        )

    @router.get("/api/v1/dashboard/performance/employees/{employee_id}/trend")
    def employee_trend(
        employee_id: str,
        months: int = Query(default=12, ge=1, le=24),
    ) -> list[dict]:
        return service.employee_trend(employee_id, months=months)

    @router.get("/api/v1/dashboard/performance/employees/{employee_id}/kpis")
    def employee_kpis(
        employee_id: str,
        month: date | None = None,
    ) -> list[dict]:
        return service.employee_kpi_breakdown(employee_id, month=month)

    @router.get("/api/v1/dashboard/performance/employees/{employee_id}/recommendations")
    def employee_recommendations(employee_id: str) -> list[dict]:
        return service.learning.employee_recommendations(employee_id)

    @router.get("/api/v1/dashboard/performance/employees/{employee_id}/learning-history")
    def employee_learning_history(employee_id: str) -> list[dict]:
        return service.learning.employee_learning_history(employee_id)

    return router
