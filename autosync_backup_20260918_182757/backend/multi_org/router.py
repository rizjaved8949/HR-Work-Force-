"""FastAPI management APIs and reference onboarding UI for Step 12."""
from __future__ import annotations

import base64
import binascii
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .access import DEFAULT_ORGANIZATION_ACCESS
from .models import (
    AddOrganizationMemberRequest,
    CreateOrganizationRequest,
    MappingPlanDraftRequest,
    RegisterRecordsDatasetRequest,
    UploadDatasetRequest,
)
from .service import MultiOrganizationOnboardingService


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _request_user(request: Request):
    return getattr(request.state, "user", None)


def _translate(error: Exception):
    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, KeyError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


def create_multi_org_router(service: MultiOrganizationOnboardingService) -> APIRouter:
    router = APIRouter(prefix="/organization-onboarding", tags=["Step 12 Multi-Organization Onboarding"])
    access = service.access

    @router.get("", include_in_schema=False)
    def onboarding_ui() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/assets/app.js", include_in_schema=False)
    def onboarding_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")

    @router.get("/assets/styles.css", include_in_schema=False)
    def onboarding_css() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")

    @router.get("/api/bootstrap")
    def bootstrap(request: Request):
        actor = access.actor(_request_user(request))
        organizations = service.list_organizations(actor=actor)
        selected = getattr(request.state, "tenant_id", None)
        return {
            "step": 12,
            "name": "Multi-Organization Onboarding",
            "tenant_header": "X-Organization-ID",
            "graph_backend": type(service.repository).__name__,
            "selected_tenant_id": selected,
            "organizations": [item.model_dump(mode="json") for item in organizations],
            "can_create_organization": access.can_create_organization(actor),
            "policies": {
                "mapping_suggestions_require_human_approval": True,
                "cross_tenant_relationships_forbidden": True,
                "secondary_tenant_legacy_services_blocked": True,
                "credentials_stored_in_registry": False,
            },
        }

    @router.get("/api/organizations")
    def organizations(request: Request):
        actor = access.actor(_request_user(request))
        return [item.model_dump(mode="json") for item in service.list_organizations(actor=actor)]

    @router.post("/api/organizations", status_code=201)
    def create_organization(payload: CreateOrganizationRequest, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.create_organization(payload, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.get("/api/organizations/{tenant_id}")
    def organization(tenant_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.tenant_summary(tenant_id, actor=actor)
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/members")
    def add_member(tenant_id: str, payload: AddOrganizationMemberRequest, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.add_member(
                tenant_id,
                user_id=payload.user_id,
                role=payload.role,
                actor=actor,
            ).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/datasets/records", status_code=201)
    def register_records(
        tenant_id: str,
        payload: RegisterRecordsDatasetRequest,
        request: Request,
    ):
        actor = access.actor(_request_user(request))
        try:
            return service.register_records_dataset(tenant_id, payload, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/datasets/upload", status_code=201)
    def upload_dataset(tenant_id: str, payload: UploadDatasetRequest, request: Request):
        """Register a CSV/JSON/XLSX/XLSM uploaded from the management UI.

        JSON/base64 is used deliberately so the standalone management service
        does not require python-multipart. Bytes are staged only long enough to
        reuse the existing audited file adapters, then the temporary file is
        deleted. The canonical tenant source snapshot remains the JSON staging
        record managed by OrganizationSourceStore.
        """
        actor = access.actor(_request_user(request))
        filename = Path(payload.filename).name
        suffix = Path(filename).suffix.lower()
        allowed = {".csv", ".json", ".xlsx", ".xlsm"}
        if suffix not in allowed:
            raise HTTPException(
                status_code=422,
                detail="Supported upload types are CSV, JSON, XLSX and XLSM.",
            )

        raw_text = payload.content_base64.strip()
        if raw_text.startswith("data:") and "," in raw_text:
            raw_text = raw_text.split(",", 1)[1]
        try:
            file_bytes = base64.b64decode(raw_text, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(status_code=422, detail="Uploaded file content is not valid base64.") from error

        max_mb = max(1, int(os.getenv("MULTI_ORG_MAX_UPLOAD_MB", "20")))
        if len(file_bytes) > max_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded file exceeds the {max_mb} MB onboarding limit.",
            )
        if not file_bytes:
            raise HTTPException(status_code=422, detail="Uploaded file is empty.")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="hr_onboarding_", suffix=suffix, delete=False) as handle:
                handle.write(file_bytes)
                temp_path = Path(handle.name)
            dataset = service.register_file_dataset(
                tenant_id,
                temp_path,
                actor=actor,
                source_system=(payload.source_system or "browser_upload").strip() or "browser_upload",
                source_object=(payload.source_object or filename).strip() or filename,
                sheet_name=(payload.sheet_name or "").strip() or None,
            )
            return dataset.model_dump(mode="json")
        except Exception as error:
            _translate(error)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @router.get("/api/organizations/{tenant_id}/datasets/{dataset_id}/profile")
    def profile(tenant_id: str, dataset_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.profile_dataset(tenant_id, dataset_id, actor=actor)
        except Exception as error:
            _translate(error)

    @router.get("/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-suggestions")
    def mapping_suggestions(tenant_id: str, dataset_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.suggest_mappings(tenant_id, dataset_id, actor=actor)
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-plan", status_code=201)
    def create_mapping_plan(
        tenant_id: str,
        dataset_id: str,
        payload: MappingPlanDraftRequest,
        request: Request,
    ):
        actor = access.actor(_request_user(request))
        try:
            return service.create_mapping_plan(tenant_id, dataset_id, payload, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.get("/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-plan/validate")
    def validate_mapping_plan(tenant_id: str, dataset_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.validate_mapping_plan(tenant_id, dataset_id, actor=actor)
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-plan/approve")
    def approve_mapping_plan(tenant_id: str, dataset_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.approve_mapping_plan(tenant_id, dataset_id, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.get("/api/organizations/{tenant_id}/datasets/{dataset_id}/dry-run")
    def dry_run(tenant_id: str, dataset_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.dry_run_dataset(tenant_id, dataset_id, actor=actor)
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/load")
    def load_organization(tenant_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.load_organization(tenant_id, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.get("/api/organizations/{tenant_id}/readiness")
    def readiness(tenant_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.readiness(tenant_id, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/activate")
    def activate(tenant_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.activate(tenant_id, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    @router.post("/api/organizations/{tenant_id}/suspend")
    def suspend(tenant_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            return service.suspend(tenant_id, actor=actor).model_dump(mode="json")
        except Exception as error:
            _translate(error)

    return router
