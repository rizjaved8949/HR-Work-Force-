"""Typed models for roadmap Step 7: Current Supabase -> Ontology -> Graph."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EndpointMode = Literal["business_id", "row_entity", "source_record_ref"]


class EndpointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: EndpointMode
    entity_type: str
    column: str | None = None
    source_object: str | None = None
    record_key_columns: list[str] = Field(default_factory=list)


class LinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: EndpointSpec
    relation: str
    target: EndpointSpec
    skip_if_empty: bool = True


class TableLoadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    matching_csv: str
    required: bool = True
    entity_types: list[str]
    record_keys: dict[str, list[str]] = Field(default_factory=dict)
    valid_from: dict[str, str] = Field(default_factory=dict)
    valid_to: dict[str, str] = Field(default_factory=dict)
    links: list[LinkSpec] = Field(default_factory=list)


class CurrentSupabaseLoadManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str
    ontology_version: str
    source_system: str
    description: str
    tables: list[TableLoadSpec]
    intentionally_not_loaded: list[dict[str, Any]] = Field(default_factory=list)
    bundled_schema_only_not_loaded: list[str] = Field(default_factory=list)
    known_supabase_snapshot_gaps: list[str] = Field(default_factory=list)


class Step7Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["error", "warning"]
    code: str
    message: str
    table: str | None = None
    row_number: int | None = None


class TablePreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    matching_csv: str
    row_count: int
    entity_count: int
    relationship_count: int
    error_count: int
    warning_count: int
    mapped_entity_types: list[str]


class Step7PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int = 7
    name: str = "Current Supabase Data -> Ontology -> Knowledge Graph"
    tenant_id: str
    manifest_version: str
    table_count: int
    source_row_count: int
    canonical_entity_count: int
    canonical_relationship_count: int
    unique_node_count: int
    unique_relationship_count: int
    error_count: int
    warning_count: int
    tables: list[TablePreflightReport]
    issues: list[Step7Issue]
    intentionally_not_loaded: list[dict[str, Any]] = Field(default_factory=list)
    known_supabase_snapshot_gaps: list[str] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.error_count == 0


class Step7LoadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int = 7
    name: str = "Current Supabase Data -> Ontology -> Knowledge Graph"
    tenant_id: str
    tables_loaded: int
    source_rows: int
    nodes_upserted: int
    relationships_upserted: int
    graph_node_count_before: int
    graph_node_count_after: int
    graph_relationship_count_before: int
    graph_relationship_count_after: int
    idempotent_upsert: bool = True
