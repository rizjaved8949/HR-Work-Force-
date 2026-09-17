"""Typed Step-10 Ontology Studio models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


ReviewStatus = Literal["pending", "approved", "rejected"]
ChangeKind = Literal[
    "mapping",
    "entity",
    "property",
    "relationship",
    "service_contract",
    "other",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MappingReviewCreate(BaseModel):
    source_file: str = Field(..., min_length=1)
    source_column: str = Field(..., min_length=1)
    proposed_ontology_path: str | None = None
    proposed_disposition: str | None = None
    proposed_transform: str = "identity"
    reason: str = Field(..., min_length=3)
    submitted_by: str | None = None


class MappingReviewDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    reviewer: str | None = None
    comment: str | None = None


class MappingReview(BaseModel):
    id: str = Field(default_factory=lambda: f"maprev-{uuid4().hex[:12]}")
    source_file: str
    source_column: str
    current_mapping: dict | None = None
    proposed_ontology_path: str | None = None
    proposed_disposition: str | None = None
    proposed_transform: str = "identity"
    reason: str
    status: ReviewStatus = "pending"
    submitted_by: str | None = None
    submitted_at: str = Field(default_factory=utc_now_iso)
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None
    applied_to_active_mapping: bool = False


class ChangeRequestCreate(BaseModel):
    kind: ChangeKind
    target: str = Field(..., min_length=1)
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    proposed_change: dict = Field(default_factory=dict)
    submitted_by: str | None = None


class ChangeRequestDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    reviewer: str | None = None
    comment: str | None = None


class OntologyChangeRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"ontchg-{uuid4().hex[:12]}")
    kind: ChangeKind
    target: str
    title: str
    description: str
    proposed_change: dict = Field(default_factory=dict)
    status: ReviewStatus = "pending"
    submitted_by: str | None = None
    submitted_at: str = Field(default_factory=utc_now_iso)
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None
    applied_to_active_ontology: bool = False
