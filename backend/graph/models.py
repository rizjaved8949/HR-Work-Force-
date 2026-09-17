"""Typed Knowledge Graph model objects for HR Ontology v1.

This module defines the storage-neutral contract for graph nodes, relationships,
and provenance. It does not connect to Neo4j and does not modify existing AI
services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GraphProvenance(BaseModel):
    """Where a graph fact came from."""

    model_config = ConfigDict(extra="forbid")

    source_system: str
    source_object: str
    source_record_key: str
    mapping_version: str | None = None
    source_observed_at: datetime | None = None
    ingested_at: datetime = Field(default_factory=utc_now)


class GraphNode(BaseModel):
    """Storage-neutral graph node instance."""

    model_config = ConfigDict(extra="forbid")

    graph_id: str
    tenant_id: str
    entity_type: str
    ontology_version: str
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphRelationship(BaseModel):
    """Storage-neutral graph edge instance."""

    model_config = ConfigDict(extra="forbid")

    graph_id: str
    tenant_id: str
    relation_type: str
    source_graph_id: str
    source_entity_type: str
    target_graph_id: str
    target_entity_type: str
    ontology_version: str
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphValidationIssue(BaseModel):
    severity: str
    code: str
    message: str
    location: str | None = None
