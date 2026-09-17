"""Read-only Step-3 mapping API router.

Intentionally not wired into app.py during Step 3. It is available for the
future Ontology Studio once integration is explicitly approved.
"""
from fastapi import APIRouter
from .service import CURRENT_MAPPING_SERVICE

router = APIRouter(prefix="/mapping", tags=["ontology-mapping"])

@router.get("/summary")
def mapping_summary():
    return CURRENT_MAPPING_SERVICE.summary()

@router.get("/validation")
def mapping_validation():
    return CURRENT_MAPPING_SERVICE.validation_report()

@router.get("/service-coverage")
def mapping_service_coverage():
    return CURRENT_MAPPING_SERVICE.service_coverage()

@router.get("/supabase-summary")
def mapping_supabase_summary():
    return CURRENT_MAPPING_SERVICE.supabase_summary()
