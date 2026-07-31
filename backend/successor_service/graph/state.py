from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class SuccessorGraphState(TypedDict, total=False):
    # Request
    employee_id: str | None
    employee_name: str | None

    # Resolution and data
    resolution: dict[str, Any]
    target_profile: dict[str, Any]
    position_context: dict[str, Any]
    candidate_pool: list[dict[str, Any]]
    evaluated_candidates: list[dict[str, Any]]
    ranked_candidates: list[dict[str, Any]]
    selected_candidates: list[dict[str, Any]]
    skipped_candidates: list[dict[str, Any]]

    # Output
    candidate_reasons: dict[str, list[str]]
    response: dict[str, Any]
