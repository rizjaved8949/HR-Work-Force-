"""Operational API for Step 9 runtime/source visibility.

This router is additive. Existing UI routes stay unchanged; the management UI can
use this endpoint to display which backend source is active per service.
"""
from __future__ import annotations

from fastapi import APIRouter

from .runtime import Step9RuntimeManager


def create_step9_runtime_router(runtime: Step9RuntimeManager) -> APIRouter:
    router = APIRouter(prefix="/runtime/step9", tags=["step9-runtime"])

    @router.get("/status")
    def status():
        return runtime.status().model_dump(mode="json")

    @router.get("/feature-health")
    def feature_health():
        if runtime.feature_service is None or not runtime.graph_available:
            return {
                "step": 9,
                "graph_available": False,
                "tenant_id": runtime.config.tenant_id,
                "feature_resolution": None,
                "message": "Graph feature runtime is not active for this process.",
            }
        return {
            "step": 9,
            "graph_available": True,
            "tenant_id": runtime.config.tenant_id,
            "feature_resolution": runtime.feature_service.health(runtime.config.tenant_id),
        }

    return router
