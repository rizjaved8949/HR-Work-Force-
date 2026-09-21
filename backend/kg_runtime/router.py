from __future__ import annotations

from fastapi import APIRouter

from .status import runtime_status


router = APIRouter(prefix="/runtime/kg-source", tags=["Runtime Data Source"])


@router.get("/status")
def kg_runtime_status():
    return runtime_status()
