"""Optional read-only FastAPI router for Ontology Studio.

IMPORTANT: Step 2 intentionally does not mount this router into the existing
application.  That preserves the current production API/runtime exactly.  A
later integration step can mount it after regression checks.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .service import ONTOLOGY_SERVICE


router = APIRouter(prefix="/ontology", tags=["ontology"])


@router.get("/summary")
def ontology_summary() -> dict:
    return ONTOLOGY_SERVICE.summary()


@router.get("/modules")
def ontology_modules() -> list[dict]:
    return ONTOLOGY_SERVICE.list_modules()


@router.get("/entities")
def ontology_entities() -> list[dict]:
    return ONTOLOGY_SERVICE.list_entities()


@router.get("/entities/{entity_name}")
def ontology_entity(entity_name: str) -> dict:
    try:
        return ONTOLOGY_SERVICE.get_entity(entity_name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/relationships")
def ontology_relationships() -> list[dict]:
    return ONTOLOGY_SERVICE.list_relationships()


@router.get("/service-contracts/{service_name}")
def ontology_service_contract(service_name: str) -> dict:
    try:
        return ONTOLOGY_SERVICE.get_service_contract(service_name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/validation")
def ontology_validation() -> dict:
    return ONTOLOGY_SERVICE.validation_report()
