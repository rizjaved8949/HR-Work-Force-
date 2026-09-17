"""Optional Step-8 API router.

It is intentionally not mounted in app.py during Step 8. Existing AI endpoint
migration belongs to Step 9 and application UI integration belongs to Step 11.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from .adapters import FeatureResolutionBlockedError
from .service import FeatureResolutionService


router = APIRouter(prefix="/feature-resolution", tags=["feature-resolution"])


def _service() -> FeatureResolutionService:
    return FeatureResolutionService.from_env()


@router.get("/health")
def feature_resolution_health(tenant_id: str | None = None) -> dict:
    service = _service()
    try:
        return service.health(tenant_id)
    finally:
        service.close()


@router.get("/{tenant_id}/employees/{employee_id}/attrition")
def resolve_attrition_features(
    tenant_id: str,
    employee_id: str,
    as_of_date: date | None = None,
    strict_missing: bool = False,
) -> dict:
    service = _service()
    try:
        report = service.resolve_attrition(
            tenant_id=tenant_id,
            employee_id=employee_id,
            as_of_date=as_of_date,
            strict_missing=strict_missing,
        )
        return report.model_dump(mode="json")
    finally:
        service.close()


@router.get("/{tenant_id}/employees/{employee_id}/attrition/model-input")
def resolve_attrition_model_input(
    tenant_id: str,
    employee_id: str,
    as_of_date: date | None = None,
    strict_missing: bool = False,
) -> dict:
    service = _service()
    try:
        try:
            result = service.attrition_model_input(
                tenant_id=tenant_id,
                employee_id=employee_id,
                as_of_date=as_of_date,
                strict_missing=strict_missing,
            )
        except FeatureResolutionBlockedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return result.model_dump(mode="json")
    finally:
        service.close()
