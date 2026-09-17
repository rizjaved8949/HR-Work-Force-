from __future__ import annotations

from semantic.service import SemanticHRService


def verify_current_graph(*, tenant_id: str, employee_id: str | None = None) -> dict:
    service = SemanticHRService.from_env(verify_connectivity=True)
    try:
        result = {"health": service.health(tenant_id)}
        if employee_id:
            employee = service.get_employee(tenant_id=tenant_id, employee_id=employee_id)
            result["employee_found"] = employee is not None
            if employee is not None:
                context = service.get_employee_context(
                    tenant_id=tenant_id, employee_id=employee_id
                )
                result["employee_context"] = context.model_dump(mode="json")
        return result
    finally:
        service.close()
