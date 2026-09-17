"""Typed models for roadmap Step 6: Data Mapping & Ingestion Layer.

Step 6 stops at validated canonical ontology records. It does not write to Neo4j;
that production load is Step 7.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MappingStatus = Literal["draft", "approved", "rejected"]
MappingDisposition = Literal["property", "ignored"]
RelationshipTargetMode = Literal["same_row_entity", "business_id_reference"]


class SourceColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    non_empty: int
    empty: int
    observed_type: str
    sample_values: list[str] = Field(default_factory=list)


class SourceSchemaProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_system: str
    source_object: str
    source_format: str
    row_count: int
    columns: list[SourceColumnProfile]


class MappingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ontology_path: str
    entity_type: str
    property_name: str
    match_strategy: str
    confidence: float
    semantic_status: str
    type_compatible: bool | None = None


class ColumnMappingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_column: str
    observed_type: str
    candidates: list[MappingCandidate] = Field(default_factory=list)
    recommended_ontology_path: str | None = None
    recommendation_confidence: float = 0.0
    review_required: bool = True


class PropertyMapping(BaseModel):
    """Human-approved source column -> ontology property mapping."""

    model_config = ConfigDict(extra="forbid")
    source_column: str
    ontology_path: str
    transform: str = "semantic_cast"
    null_values: list[str] = Field(default_factory=lambda: [""])
    date_format: str | None = None
    numeric_multiplier: float | None = None
    numeric_divisor: float | None = None
    semantic_override_reason: str | None = None


class EntityIngestionRule(BaseModel):
    """How to identify a node produced from a source row."""

    model_config = ConfigDict(extra="forbid")
    entity_type: str
    record_key_columns: list[str] = Field(default_factory=list)
    valid_from_column: str | None = None
    valid_to_column: str | None = None


class RelationshipMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_type: str
    source_entity_type: str
    target_entity_type: str
    target_mode: RelationshipTargetMode
    target_source_column: str | None = None
    skip_if_empty: bool = True


class MappingPlan(BaseModel):
    """Approved semantic mapping for one source object/table/file."""

    model_config = ConfigDict(extra="forbid")
    plan_id: str
    version: str
    tenant_id: str
    source_system: str
    source_object: str
    source_format: str
    ontology_version: str
    status: MappingStatus = "draft"
    property_mappings: list[PropertyMapping] = Field(default_factory=list)
    entity_rules: list[EntityIngestionRule] = Field(default_factory=list)
    relationship_mappings: list[RelationshipMapping] = Field(default_factory=list)
    approved_by: str | None = None
    approved_at: datetime | None = None
    notes: str | None = None


class IngestionIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["error", "warning"]
    code: str
    message: str
    row_number: int | None = None
    source_column: str | None = None
    ontology_path: str | None = None


class CanonicalEntityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    entity_type: str
    graph_id: str
    identity_key: str
    source_system: str
    source_object: str
    source_record_key: str
    ontology_version: str
    mapping_version: str
    properties: dict[str, Any]
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    row_number: int


class CanonicalRelationshipRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    relation_type: str
    source_entity_type: str
    target_entity_type: str
    source_graph_id: str
    target_graph_id: str
    graph_id: str
    source_system: str
    source_object: str
    source_record_key: str
    ontology_version: str
    mapping_version: str
    row_number: int


class CanonicalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    source_system: str
    source_object: str
    mapping_plan_id: str
    mapping_version: str
    entities: list[CanonicalEntityRecord] = Field(default_factory=list)
    relationships: list[CanonicalRelationshipRecord] = Field(default_factory=list)
    issues: list[IngestionIssue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.issues)

    def summary(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "source_system": self.source_system,
            "source_object": self.source_object,
            "mapping_plan_id": self.mapping_plan_id,
            "mapping_version": self.mapping_version,
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }
