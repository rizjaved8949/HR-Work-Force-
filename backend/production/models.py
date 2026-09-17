"""Typed Step-13 production-readiness contracts."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

Severity = Literal["pass", "warning", "error"]


class ProductionCheck(BaseModel):
    code: str
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class VersionInfo(BaseModel):
    roadmap_step: int = 13
    release_version: str
    api_version: str
    ontology_version: str
    mapping_version: str
    graph_model_version: str
    python_runtime: str
    release_commit: str | None = None
    build_time: str | None = None


class LivenessReport(BaseModel):
    status: Literal["alive"] = "alive"
    step: int = 13
    release_version: str


class ReadinessReport(BaseModel):
    status: Literal["ready", "not_ready"]
    tenant_id: str
    release_version: str
    error_count: int
    warning_count: int
    checks: list[ProductionCheck]

    @property
    def ready(self) -> bool:
        return self.error_count == 0


class ReleaseGateReport(BaseModel):
    status: Literal["pass", "fail"]
    tenant_id: str
    release_version: str
    production_mode_required: bool
    error_count: int
    warning_count: int
    checks: list[ProductionCheck]

    @property
    def passed(self) -> bool:
        return self.error_count == 0
