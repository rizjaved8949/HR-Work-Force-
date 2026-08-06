"""FastAPI router for deterministic Headcount analysis.

The endpoint returns the same structured HeadcountToolResult used by the
agent tool. It does not call the LLM and does not modify Attrition routes.
"""

from __future__ import annotations

from fastapi import APIRouter

from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountToolResult,
)
from headcount.service import HeadcountService


def create_headcount_router(
    service: HeadcountService,
) -> APIRouter:
    """Create a router bound to one shared Headcount service."""

    router = APIRouter(
        prefix="/pipeline/headcount",
        tags=["Headcount"],
    )

    @router.post(
        "",
        response_model=HeadcountToolResult,
        summary="Analyze Headcount",
    )
    def analyze_headcount_endpoint(
        request: AnalyzeHeadcountInput,
    ) -> HeadcountToolResult:
        """Run deterministic Headcount analysis.

        The request may contain only a natural-language question,
        or may also provide explicit metrics, scope, grouping,
        filters, date range, sorting, and result limits.
        """

        return service.analyze(
            request
        )

    return router
