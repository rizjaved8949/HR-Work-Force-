"""Typed status models for roadmap Step 9 service refactoring."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuntimeMode(str, Enum):
    LEGACY = "legacy"
    GRAPH_FIRST = "graph_first"
    GRAPH_ONLY = "graph_only"


class ServiceMigrationState(str, Enum):
    GRAPH_NATIVE = "graph_native"
    GRAPH_FIRST_WITH_LEGACY_FALLBACK = "graph_first_with_legacy_fallback"
    HYBRID = "hybrid"
    LEGACY_DELEGATED = "legacy_delegated"
    BLOCKED_BY_SOURCE_GAP = "blocked_by_source_gap"


class ServiceMigrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    state: ServiceMigrationState
    active_source: str
    graph_capable: bool
    fallback_enabled: bool = False
    notes: list[str] = Field(default_factory=list)


class Step9RuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = 9
    name: str = "Existing AI Services Refactor"
    mode: RuntimeMode
    tenant_id: str
    graph_available: bool
    ui_api_contract_preserved: bool = True
    services: list[ServiceMigrationStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RefactoredPredictionResult(BaseModel):
    """Internal typed representation; public API remains the legacy dict shape."""

    model_config = ConfigDict(extra="forbid")

    attrition: str | None
    top_reasons: list[str] = Field(default_factory=list)
    employee_id: str | None = None
    feature_status: str | None = None
    unresolved_features: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
