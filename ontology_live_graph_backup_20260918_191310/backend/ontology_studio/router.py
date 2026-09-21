"""FastAPI router and standalone reference UI for Step 10 Ontology Studio."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .models import (
    ChangeRequestCreate,
    ChangeRequestDecision,
    MappingReviewCreate,
    MappingReviewDecision,
)
from .service import OntologyStudioService


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _allowed_admin_roles() -> set[str]:
    value = os.getenv(
        "ONTOLOGY_STUDIO_ADMIN_ROLES",
        "admin,owner,hr_admin,super_admin",
    )
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _require_admin(request: Request) -> None:
    # Local development with AUTH_ENABLED=false remains usable.
    if not _auth_enabled():
        return
    user = getattr(request.state, "user", None)
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role not in _allowed_admin_roles():
        raise HTTPException(
            status_code=403,
            detail="Ontology Studio write actions require an approved admin role.",
        )


def create_ontology_studio_router(
    service: OntologyStudioService | None = None,
) -> APIRouter:
    studio = service or OntologyStudioService()
    router = APIRouter(tags=["ontology-studio"])

    @router.get("/ontology-studio", include_in_schema=False)
    def studio_ui() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/ontology-studio/assets/app.js", include_in_schema=False)
    def studio_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")

    @router.get("/ontology-studio/assets/styles.css", include_in_schema=False)
    def studio_css() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")

    @router.get("/ontology-studio/api/dashboard")
    def dashboard(tenant_id: str | None = None):
        return studio.dashboard(tenant_id)

    @router.get("/ontology-studio/api/schema-graph")
    def schema_graph():
        return studio.schema_graph()

    @router.get("/ontology-studio/api/entities")
    def entities():
        return studio.entity_catalog()

    @router.get("/ontology-studio/api/datasets")
    def datasets():
        return studio.dataset_catalog()

    @router.get("/ontology-studio/api/datasets/{source_file}")
    def dataset(source_file: str):
        try:
            return studio.dataset_mapping(source_file)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/ontology-studio/api/attention")
    def attention():
        return studio.attention_queue()

    @router.get("/ontology-studio/api/service-contracts")
    def contracts():
        return studio.service_contracts()

    @router.get("/ontology-studio/api/mapping-reviews")
    def mapping_reviews(status: str | None = Query(default=None)):
        return studio.list_mapping_reviews(status)

    @router.post("/ontology-studio/api/mapping-reviews", status_code=201)
    def create_mapping_review(payload: MappingReviewCreate, request: Request):
        _require_admin(request)
        try:
            return studio.create_mapping_review(payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.patch("/ontology-studio/api/mapping-reviews/{review_id}")
    def decide_mapping_review(
        review_id: str,
        payload: MappingReviewDecision,
        request: Request,
    ):
        _require_admin(request)
        try:
            return studio.decide_mapping_review(review_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/ontology-studio/api/change-requests")
    def change_requests(status: str | None = Query(default=None)):
        return studio.list_change_requests(status)

    @router.post("/ontology-studio/api/change-requests", status_code=201)
    def create_change_request(payload: ChangeRequestCreate, request: Request):
        _require_admin(request)
        return studio.create_change_request(payload)

    @router.patch("/ontology-studio/api/change-requests/{request_id}")
    def decide_change_request(
        request_id: str,
        payload: ChangeRequestDecision,
        request: Request,
    ):
        _require_admin(request)
        try:
            return studio.decide_change_request(request_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/ontology-studio/api/governance-snapshot")
    def governance_snapshot():
        return studio.export_governance_snapshot()

    return router
