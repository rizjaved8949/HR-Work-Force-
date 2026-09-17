"""Step 13 system/release endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query
from .service import ProductionReadinessService


def create_production_router(service: ProductionReadinessService) -> APIRouter:
    router = APIRouter(prefix="/system", tags=["production-readiness"])

    @router.get("/version")
    def version():
        return service.version.model_dump(mode="json")

    @router.get("/liveness")
    def liveness():
        return service.liveness().model_dump(mode="json")

    @router.get("/readiness")
    def readiness(tenant_id: str = Query(default="ORGANIZATION-001")):
        return service.readiness(tenant_id).model_dump(mode="json")

    @router.get("/release-gate")
    def release_gate(
        tenant_id: str = Query(default="ORGANIZATION-001"),
        require_production: bool = Query(default=False),
    ):
        return service.release_gate(
            tenant_id,
            require_production=require_production,
        ).model_dump(mode="json")

    return router
