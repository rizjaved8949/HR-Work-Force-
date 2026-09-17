"""Read-only Step-4 graph-model endpoints. Router is not mounted automatically."""

from fastapi import APIRouter

from .service import GRAPH_MODEL_SERVICE


router = APIRouter(prefix="/graph-model", tags=["knowledge-graph-model"])


@router.get("/summary")
def graph_model_summary() -> dict:
    return GRAPH_MODEL_SERVICE.summary()


@router.get("/validation")
def graph_model_validation() -> dict:
    return GRAPH_MODEL_SERVICE.validation_report()


@router.get("/schema")
def graph_model_schema() -> dict:
    return GRAPH_MODEL_SERVICE.schema_manifest()


@router.get("/identity-rules")
def graph_identity_rules() -> dict:
    return GRAPH_MODEL_SERVICE.identity_rules()
