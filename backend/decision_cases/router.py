from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .exceptions import DecisionCaseStorageError
from .schemas import (
    DecisionCaseEvaluationResult,
    DecisionCaseQueryResult,
    DecisionCaseRecord,
    DecisionCaseStatusUpdate,
)
from .service import DecisionCaseService


def create_decision_case_router(service: DecisionCaseService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/decision-cases", tags=["Decision Trigger Engine"])

    @router.post(
        "/evaluate",
        response_model=DecisionCaseEvaluationResult,
        summary="Evaluate Decision Trigger Rules",
    )
    def evaluate_cases() -> DecisionCaseEvaluationResult:
        """Run the isolated deterministic trigger engine and persist current cases.

        This endpoint is safe to call from a daily scheduler. It never mutates the
        existing employee/workforce source CSVs or HR calculations.
        """
        try:
            return service.evaluate()
        except DecisionCaseStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get(
        "",
        response_model=DecisionCaseQueryResult,
        summary="Get Important HR Decision Cases",
    )
    def list_cases(
        priority: str | None = None,
        status: str | None = None,
        employee_id: str | None = None,
        department: str | None = None,
        rule_id: str | None = None,
        active_only: bool = True,
        refresh: bool = Query(
            default=True,
            description=(
                "Re-evaluate the five deterministic rules from the current data before returning cases. "
                "Set false for a read-only poll of the last generated case state."
            ),
        ),
        limit: int = Query(default=5, ge=1, le=5),
    ) -> DecisionCaseQueryResult:
        try:
            if refresh:
                service.evaluate()
            return service.list_cases(
                priority=priority,
                status=status,
                employee_id=employee_id,
                department=department,
                rule_id=rule_id,
                active_only=active_only,
                limit=limit,
            )
        except DecisionCaseStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get(
        "/{case_id}",
        response_model=DecisionCaseRecord,
        summary="Get One Decision Case",
    )
    def get_case(case_id: str) -> DecisionCaseRecord:
        try:
            record = service.get_case(case_id)
        except DecisionCaseStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="Decision case was not found.")
        return record

    @router.patch(
        "/{case_id}/status",
        response_model=DecisionCaseRecord,
        summary="Update Decision Case Status",
    )
    def update_case_status(case_id: str, request: DecisionCaseStatusUpdate) -> DecisionCaseRecord:
        try:
            record = service.update_status(case_id, request.status)
        except DecisionCaseStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="Decision case was not found.")
        return record

    return router
