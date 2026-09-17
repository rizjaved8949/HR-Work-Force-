"""Typed contracts for roadmap Step 8: Feature Resolution / Missing Feature Layer."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MissingPolicy(str, Enum):
    """What the resolver should do when a semantic feature is unavailable."""

    CRITICAL = "critical"
    OPTIONAL = "optional"
    MODEL_NATIVE = "model_native_missing"
    SAFE_DEFAULT = "safe_default"


class ResolutionMethod(str, Enum):
    DIRECT = "direct"
    DERIVED = "derived"
    DEFAULTED = "defaulted"
    MISSING = "missing"


class ResolutionStatus(str, Enum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    SUBJECT_NOT_FOUND = "subject_not_found"


class FeatureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int
    feature_name: str
    ontology_path: str
    model_type: str | None = None
    unit: str | None = None
    required: bool = True
    missing_policy: MissingPolicy = MissingPolicy.CRITICAL
    semantic_status: str = "confirmed"
    derivable: bool = False
    current_missing_behavior: str | None = None


class FeatureContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    contract_name: str
    source_contract: str
    version: str
    features: list[FeatureSpec]

    def ordered_features(self) -> list[FeatureSpec]:
        return sorted(self.features, key=lambda item: item.order)


class ResolvedFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int
    feature_name: str
    ontology_path: str
    model_type: str | None = None
    unit: str | None = None
    missing_policy: MissingPolicy
    semantic_status: str = "confirmed"
    method: ResolutionMethod
    value: Any = None
    source_reference_ids: list[str] = Field(default_factory=list)
    derivation_rule: str | None = None
    warning_codes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.method in {
            ResolutionMethod.DIRECT,
            ResolutionMethod.DERIVED,
            ResolutionMethod.DEFAULTED,
        }


class FeatureResolutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = 8
    name: str = "Feature Resolution / Missing Feature Layer"
    service: str
    contract_name: str
    tenant_id: str | None = None
    subject_id: str | None = None
    status: ResolutionStatus
    feature_count: int
    direct_count: int
    derived_count: int
    defaulted_count: int
    missing_count: int
    critical_missing_count: int
    optional_missing_count: int
    model_native_missing_count: int
    warning_count: int
    features: list[ResolvedFeature] = Field(default_factory=list)
    report_warnings: list[str] = Field(default_factory=list)

    @property
    def ready_for_service(self) -> bool:
        return self.status not in {
            ResolutionStatus.BLOCKED,
            ResolutionStatus.SUBJECT_NOT_FOUND,
        }

    def values_by_feature(self) -> dict[str, Any]:
        return {item.feature_name: item.value for item in self.features}


class ModelInputEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    service: str
    adapter: str
    ready: bool
    feature_order: list[str]
    values: dict[str, Any]
    unresolved_features: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
