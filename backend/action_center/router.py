"""FastAPI routes for the HR Action Center."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from .errors import (
    ActionCenterAuthorizationError,
    ActionCenterConflictError,
    ActionCenterDataError,
    ActionCenterNotFoundError,
    ActionCenterValidationError,
)
from .schemas import (
    ActionActor,
    ActionCenterQueryInput,
    ActionExecuteRequest,
    ApplyDueRequest,
    ActionPreviewRequest,
    ActionRecordUpdateRequest,
)
from .service import ActionCenterService


def _actor_from_request(request: Request) -> ActionActor | None:
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    return ActionActor(
        user_id=str(getattr(user, "id", "") or ""),
        name=getattr(user, "full_name", None),
        email=getattr(user, "email", None),
        role=getattr(user, "role", None),
    )


def _raise_http(error: Exception) -> None:
    if isinstance(error, ActionCenterAuthorizationError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, ActionCenterNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, (ActionCenterValidationError, ActionCenterConflictError)):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, ActionCenterDataError):
        raise HTTPException(status_code=500, detail=str(error)) from error
    raise error


def create_action_center_router(service: ActionCenterService) -> APIRouter:
    router = APIRouter(
        prefix="/api/action-center",
        tags=["HR Action Center"],
    )

    @router.get("/summary")
    def get_summary() -> dict[str, Any]:
        try:
            return service.summary()
        except Exception as error:
            _raise_http(error)

    @router.get("/processes")
    def get_processes(
        limit: int = Query(default=100, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return service.query({"mode": "processes", "limit": limit})
        except Exception as error:
            _raise_http(error)

    @router.get("/processes/{process_code}")
    def get_process(process_code: str) -> dict[str, Any]:
        try:
            return service.process_detail(process_code)
        except Exception as error:
            _raise_http(error)

    @router.get("/processes/{process_code}/options")
    def get_process_options(
        process_code: str,
        employee_id: str | None = None,
        employee_name: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return service.process_options(
                process_code,
                employee_id=employee_id,
                employee_name=employee_name,
                limit=limit,
            )
        except Exception as error:
            _raise_http(error)

    @router.get("/records")
    def get_records(
        process_code: str | None = None,
        employee_id: str | None = None,
        employee_name: str | None = None,
        status: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return service.query(
                ActionCenterQueryInput(
                    mode="records",
                    process_code=process_code,
                    employee_id=employee_id,
                    employee_name=employee_name,
                    status=status,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                )
            )
        except Exception as error:
            _raise_http(error)

    @router.get("/records/{action_record_id}")
    def get_record(action_record_id: str) -> dict[str, Any]:
        try:
            return {
                "status": "success",
                "record": service.repository.get_action_record(action_record_id),
            }
        except Exception as error:
            _raise_http(error)

    @router.post("/processes/{process_code}/preview")
    def preview_action(
        process_code: str,
        body: ActionPreviewRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return service.preview_action(
                process_code=process_code,
                employee_id=body.employee_id,
                employee_name=body.employee_name,
                fields=body.fields,
                actor=_actor_from_request(request),
            )
        except Exception as error:
            _raise_http(error)

    @router.post("/processes/{process_code}/execute")
    def execute_action(
        process_code: str,
        body: ActionExecuteRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return service.execute_action(
                process_code=process_code,
                employee_id=body.employee_id,
                employee_name=body.employee_name,
                fields=body.fields,
                actor=_actor_from_request(request),
            )
        except Exception as error:
            _raise_http(error)

    @router.patch("/records/{action_record_id}")
    def update_record(
        action_record_id: str,
        body: ActionRecordUpdateRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return service.update_action_record(
                action_record_id=action_record_id,
                updates=body.updates,
                actor=_actor_from_request(request),
            )
        except Exception as error:
            _raise_http(error)

    @router.post("/apply-due")
    def apply_due_actions(
        body: ApplyDueRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return service.apply_due_actions(
                actor=_actor_from_request(request),
                record_ids=body.record_ids,
                limit=body.limit,
            )
        except Exception as error:
            _raise_http(error)

    @router.get("/activity")
    def get_activity(
        process_code: str | None = None,
        employee_id: str | None = None,
        employee_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return service.query(
                ActionCenterQueryInput(
                    mode="activity",
                    process_code=process_code,
                    employee_id=employee_id,
                    employee_name=employee_name,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                )
            )
        except Exception as error:
            _raise_http(error)

    @router.get("/employees/{employee_id}/history")
    def get_employee_history(
        employee_id: str,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return service.query(
                ActionCenterQueryInput(
                    mode="employee_history",
                    employee_id=employee_id,
                    limit=limit,
                )
            )
        except Exception as error:
            _raise_http(error)

    @router.get("/employees/{employee_id}/state")
    def get_employee_state(employee_id: str) -> dict[str, Any]:
        try:
            return service.query(
                ActionCenterQueryInput(
                    mode="employee_state",
                    employee_id=employee_id,
                )
            )
        except Exception as error:
            _raise_http(error)

    return router
