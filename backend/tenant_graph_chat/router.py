from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from graph.factory import create_graph_repository_from_env
from multi_org.registry import validate_tenant_id

from .models import TenantGraphChatRequest, TenantGraphContextRequest
from .service import TenantGraphChatService


def _tenant_id(request: Request) -> str:
    value = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Organization-ID")
        or os.getenv("STEP9_TENANT_ID", "ORGANIZATION-001")
    )
    return validate_tenant_id(str(value))


def create_tenant_graph_chat_router(
    service: TenantGraphChatService | None = None,
) -> APIRouter:
    active = service or TenantGraphChatService(
        repository=create_graph_repository_from_env(verify_connectivity=False)
    )
    router = APIRouter(prefix="/tenant-graph/api", tags=["Tenant Graph Chat"])

    @router.get("/status")
    def status(request: Request):
        tenant = _tenant_id(request)
        try:
            return {
                "status": "ok",
                "tenant_id": tenant,
                "runtime_source": "canonical_knowledge_graph",
                "tenant_isolation": True,
                "node_count": active.repository.count_nodes(tenant),
                "relationship_count": active.repository.count_relationships(tenant),
                "tenant_header": "X-Organization-ID",
            }
        except Exception as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @router.post("/context")
    def context(payload: TenantGraphContextRequest, request: Request):
        tenant = _tenant_id(request)
        try:
            return active.build_context(
                tenant_id=tenant,
                message=payload.message,
                max_nodes=payload.max_nodes,
            ).model_dump(mode="json")
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @router.post("/chat")
    def chat(payload: TenantGraphChatRequest, request: Request):
        tenant = _tenant_id(request)
        try:
            return active.answer(
                tenant_id=tenant,
                message=payload.message,
                thread_id=payload.thread_id,
                max_nodes=payload.max_nodes,
            )
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    return router
