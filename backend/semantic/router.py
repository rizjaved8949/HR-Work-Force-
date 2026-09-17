"""Optional read-only Semantic HR API router.

The router is deliberately not mounted in app.py during Step 5. Mounting it is
an explicit application-integration decision and is not required by the current
AI runtime.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .service import SemanticHRService


router = APIRouter(prefix="/semantic", tags=["semantic-hr"])


def _service() -> SemanticHRService:
    return SemanticHRService.from_env()


@router.get("/health")
def semantic_health(tenant_id: str | None = None) -> dict:
    service = _service()
    try:
        return service.health(tenant_id)
    finally:
        service.close()


@router.get("/{tenant_id}/employees/{employee_id}")
def semantic_employee(tenant_id: str, employee_id: str) -> dict:
    service = _service()
    try:
        employee = service.get_employee(tenant_id=tenant_id, employee_id=employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="Employee not found")
        return employee.model_dump(mode="json")
    finally:
        service.close()


@router.get("/{tenant_id}/employees/{employee_id}/context")
def semantic_employee_context(tenant_id: str, employee_id: str) -> dict:
    service = _service()
    try:
        context = service.get_employee_context(
            tenant_id=tenant_id, employee_id=employee_id
        )
        if context is None:
            raise HTTPException(status_code=404, detail="Employee not found")
        return context.model_dump(mode="json")
    finally:
        service.close()


@router.get("/{tenant_id}/employees/{employee_id}/reporting-chain")
def semantic_reporting_chain(
    tenant_id: str, employee_id: str, max_depth: int = 20
) -> list[dict]:
    service = _service()
    try:
        return [
            item.model_dump(mode="json")
            for item in service.get_reporting_chain(
                tenant_id=tenant_id, employee_id=employee_id, max_depth=max_depth
            )
        ]
    finally:
        service.close()
