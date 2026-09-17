"""Typed contracts for roadmap Step 12: Multi-Organization Onboarding.

Step 12 introduces an explicit tenant/onboarding control plane around the
already-built ontology, ingestion, graph and UI layers.  It never guesses a
mapping and never allows graph facts from one tenant to be reused by another.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ingestion.models import EntityIngestionRule, PropertyMapping, RelationshipMapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationStatus(str, Enum):
    DRAFT = "draft"
    MAPPING_REVIEW = "mapping_review"
    READY_TO_LOAD = "ready_to_load"
    LOADING = "loading"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    FAILED = "failed"


class DatasetStatus(str, Enum):
    REGISTERED = "registered"
    PROFILED = "profiled"
    MAPPING_REVIEW = "mapping_review"
    MAPPING_APPROVED = "mapping_approved"
    LOADED = "loaded"
    FAILED = "failed"


OrganizationMemberRole = Literal["owner", "admin", "hr_admin", "analyst", "viewer"]


class OrganizationMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: OrganizationMemberRole
    added_at: datetime = Field(default_factory=utc_now)
    added_by: str | None = None


class DatasetLoadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loaded_at: datetime = Field(default_factory=utc_now)
    node_upserts: int = 0
    relationship_upserts: int = 0
    graph_node_count_after: int = 0
    graph_relationship_count_after: int = 0
    mapping_plan_id: str | None = None
    mapping_version: str | None = None


class OrganizationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    tenant_id: str
    source_system: str
    source_object: str
    source_format: str
    storage_key: str
    status: DatasetStatus = DatasetStatus.REGISTERED
    row_count: int = 0
    column_count: int = 0
    mapping_plan_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_error: str | None = None
    load_result: DatasetLoadResult | None = None


class OrganizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    name: str
    status: OrganizationStatus = OrganizationStatus.DRAFT
    country: str | None = None
    currency: str | None = None
    organization_type: str | None = None
    is_default: bool = False
    legacy_default_access: bool = False
    created_by: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    activated_at: datetime | None = None
    members: list[OrganizationMember] = Field(default_factory=list)
    datasets: list[OrganizationDataset] = Field(default_factory=list)
    notes: str | None = None


class OrganizationRegistryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "1.0.0-step12"
    organizations: list[OrganizationRecord] = Field(default_factory=list)


class ActorContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool = False
    user_id: str | None = None
    role: str | None = None
    local_development: bool = False


class CreateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=3, max_length=64)
    name: str = Field(..., min_length=2, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, max_length=20)
    organization_type: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("tenant_id")
    @classmethod
    def tenant_id_trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def name_trim(cls, value: str) -> str:
        return " ".join(value.strip().split())


class AddOrganizationMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, max_length=200)
    role: OrganizationMemberRole


class RegisterRecordsDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(..., min_length=1, max_length=100)
    source_object: str = Field(..., min_length=1, max_length=255)
    source_format: str = Field(default="records", min_length=1, max_length=50)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class UploadDatasetRequest(BaseModel):
    """Browser-friendly file upload envelope without multipart dependency.

    The UI sends the selected file as base64. The router writes it to a
    short-lived temporary file and reuses the existing Step-12 file ingestion
    adapters (CSV / JSON / XLSX / XLSM).
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., min_length=1, max_length=255)
    content_base64: str = Field(..., min_length=1)
    source_system: str | None = Field(default=None, max_length=100)
    source_object: str | None = Field(default=None, max_length=255)
    sheet_name: str | None = Field(default=None, max_length=150)


class MappingPlanDraftRequest(BaseModel):
    """Human-reviewed mapping choices for one registered organization dataset.

    Suggestions are deliberately not accepted as implicit approvals.  The
    caller must explicitly submit the chosen property/entity/relationship
    mappings and then separately approve the resulting plan.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0.0"
    property_mappings: list[PropertyMapping] = Field(default_factory=list)
    entity_rules: list[EntityIngestionRule] = Field(default_factory=list)
    relationship_mappings: list[RelationshipMapping] = Field(default_factory=list)
    notes: str | None = None


class OnboardingIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["error", "warning"]
    code: str
    message: str
    dataset_id: str | None = None


class OrganizationLoadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = 12
    name: str = "Multi-Organization Onboarding"
    tenant_id: str
    dataset_count: int
    source_row_count: int
    canonical_entity_count: int
    canonical_relationship_count: int
    unique_node_count: int
    unique_relationship_count: int
    error_count: int
    warning_count: int
    graph_node_count_before: int
    graph_node_count_after: int
    graph_relationship_count_before: int
    graph_relationship_count_after: int
    idempotent_upsert: bool
    issues: list[OnboardingIssue] = Field(default_factory=list)


class OrganizationReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    status: OrganizationStatus
    dataset_count: int
    profiled_dataset_count: int
    approved_mapping_count: int
    loaded_dataset_count: int
    graph_node_count: int
    graph_relationship_count: int
    ready_to_activate: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
