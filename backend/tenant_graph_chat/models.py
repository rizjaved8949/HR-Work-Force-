from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TenantGraphContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=5000)
    max_nodes: int = Field(default=50, ge=10, le=150)


class TenantGraphChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=5000)
    thread_id: str | None = Field(default=None, max_length=200)
    max_nodes: int = Field(default=50, ge=10, le=150)


class TenantGraphEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    node_count_total: int
    relationship_count_total: int
    retrieved_node_count: int
    retrieved_relationship_count: int
    entity_types: list[str] = Field(default_factory=list)
    matched_employee_id: str | None = None
    truncated: bool = False
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    employee_context: dict[str, Any] | None = None
