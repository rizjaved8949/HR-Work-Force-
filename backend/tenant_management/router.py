"""Tenant selector and optional merge-upload APIs.

The existing `/organization-onboarding/.../datasets/auto-sync` contract remains
unchanged.  The merge endpoint below creates a new source snapshot and then
reuses the already-audited auto-sync pipeline.  Because graph identities are
business-key based, new records are added and existing matching identities are
upserted inside the selected tenant without deleting the tenant's prior graph.
"""
from __future__ import annotations

import base64
import binascii
import os
import tempfile
from pathlib import Path
from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from multi_org.models import UploadDatasetRequest
from multi_org.service import MultiOrganizationOnboardingService

from .merge_repository import MergePreservingGraphRepository


def _request_user(request: Request):
    return getattr(request.state, "user", None)


def _translate(error: Exception):
    if isinstance(error, PermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, KeyError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, RuntimeError):
        raise HTTPException(status_code=500, detail=str(error)) from error
    raise error


def _decode_upload(payload: UploadDatasetRequest) -> tuple[str, bytes]:
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
        raise HTTPException(
            status_code=422,
            detail="Uploaded file content is not valid base64.",
        ) from error
    max_mb = max(1, int(os.getenv("MULTI_ORG_MAX_UPLOAD_MB", "20")))
    if len(file_bytes) > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds the {max_mb} MB onboarding limit.",
        )
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    return filename, file_bytes


def _default_merge_service_factory(service: MultiOrganizationOnboardingService) -> MultiOrganizationOnboardingService:
    return MultiOrganizationOnboardingService(
        repository=MergePreservingGraphRepository(service.repository),
        registry=service.registry,
        source_store=service.source_store,
        plan_store=service.plan_store,
        access=service.access,
        ontology=service.ontology,
        mapping_suggester=service.mapping_suggester,
        plan_validator=service.plan_validator,
        canonicalizer=service.canonicalizer,
        auto_mapping_builder=service.auto_mapping_builder,
        ingestion_store=service.ingestion_store,
    )


def create_tenant_management_router(
    service: MultiOrganizationOnboardingService,
    *,
    merge_service_factory: Callable[[MultiOrganizationOnboardingService], MultiOrganizationOnboardingService] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/tenant-management/api", tags=["Tenant Management"])
    access = service.access
    build_merge_service = merge_service_factory or _default_merge_service_factory

    @router.get("/tenants")
    def list_tenants(request: Request):
        actor = access.actor(_request_user(request))
        organizations = service.list_organizations(actor=actor)
        selected = getattr(request.state, "tenant_id", None) or os.getenv(
            "STEP9_TENANT_ID", "ORGANIZATION-001"
        )
        return {
            "selected_tenant_id": selected,
            "tenant_header": "X-Organization-ID",
            "tenants": [
                {
                    "tenant_id": org.tenant_id,
                    "name": org.name,
                    "status": org.status.value,
                    "is_default": org.is_default,
                    "dataset_count": len(org.datasets),
                    "loaded_dataset_count": sum(
                        str(dataset.status.value) == "loaded" for dataset in org.datasets
                    ),
                }
                for org in organizations
            ],
        }

    @router.get("/tenants/{tenant_id}/summary")
    def tenant_summary(tenant_id: str, request: Request):
        actor = access.actor(_request_user(request))
        try:
            summary = service.tenant_summary(tenant_id, actor=actor)
            return {
                "tenant_id": tenant_id,
                "organization": summary["organization"],
                "readiness": summary["readiness"],
                "graph_backend": type(service.repository).__name__,
            }
        except Exception as error:
            _translate(error)

    @router.post("/organizations/{tenant_id}/merge-sync")
    def merge_sync(
        tenant_id: str,
        payload: UploadDatasetRequest,
        request: Request,
    ):
        """Add/update rows in an existing tenant without replacing prior snapshots.

        This route is intentionally optional.  Normal auto-sync continues to use
        the existing endpoint and semantics.  Merge-sync gives each upload a new
        source-object identity, preserving earlier raw datasets while the graph
        writer still uses ontology business identities for idempotent node/edge
        upserts.
        """
        actor = access.actor(_request_user(request))
        filename, file_bytes = _decode_upload(payload)
        suffix = Path(filename).suffix.lower()
        original_object = (
            (payload.source_object or filename).strip() or filename
        )
        merge_token = uuid4().hex[:12]
        # Keep within the existing source-object model limit.
        merge_object = f"{original_object[:220]}__merge__{merge_token}"

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="hr_merge_sync_", suffix=suffix, delete=False
            ) as handle:
                handle.write(file_bytes)
                temp_path = Path(handle.name)
            merge_service = build_merge_service(service)
            result = merge_service.auto_sync_file_dataset(
                tenant_id,
                temp_path,
                actor=actor,
                source_system=(payload.source_system or "browser_upload").strip()
                or "browser_upload",
                source_object=merge_object,
                sheet_name=(payload.sheet_name or "").strip() or None,
            )
            result = dict(result)
            result["sync_mode"] = "merge_into_existing_tenant"
            result["merge"] = {
                "enabled": True,
                "target_tenant_id": tenant_id,
                "original_source_object": original_object,
                "stored_source_object": merge_object,
                "preserves_existing_datasets": True,
                "graph_write_semantics": "tenant-scoped property-preserving idempotent upsert",
                "preserves_unsupplied_existing_properties": True,
            }
            return result
        except Exception as error:
            _translate(error)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return router
