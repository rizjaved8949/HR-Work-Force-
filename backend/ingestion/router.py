"""Optional Step-6 inspection API. Not mounted into the current app by default."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .models import MappingPlan
from .service import DEFAULT_INGESTION_SERVICE

router = APIRouter(prefix="/ingestion", tags=["ingestion-step6"])


@router.get("/plans")
def list_plans():
    return {"plans": DEFAULT_INGESTION_SERVICE.plan_registry.list_plan_ids()}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    try:
        return DEFAULT_INGESTION_SERVICE.plan_registry.load(plan_id).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/plans/validate")
def validate_plan(plan: MappingPlan):
    return DEFAULT_INGESTION_SERVICE.validate_plan(plan)


@router.post("/plans/coverage")
def plan_coverage(plan: MappingPlan):
    return DEFAULT_INGESTION_SERVICE.coverage(plan)
