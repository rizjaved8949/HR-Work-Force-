"""Storage-neutral response models exposed by the Semantic HR Service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from graph.models import GraphNode, GraphProvenance


class SemanticRecord(BaseModel):
    """Business-facing graph record without Neo4j-specific objects or Cypher."""

    model_config = ConfigDict(extra="forbid")

    reference_id: str
    entity_type: str
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @classmethod
    def from_node(cls, node: GraphNode) -> "SemanticRecord":
        return cls(
            reference_id=node.graph_id,
            entity_type=node.entity_type,
            properties=dict(node.properties),
            provenance=list(node.provenance),
            valid_from=node.valid_from,
            valid_to=node.valid_to,
        )


class EmployeeSkillContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment: SemanticRecord
    skill: SemanticRecord | None = None


class EmployeeContext(BaseModel):
    """Canonical employee-centered semantic view built from ontology relations."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    employee: SemanticRecord
    employment: SemanticRecord | None = None
    current_assignment: SemanticRecord | None = None
    department: SemanticRecord | None = None
    position: SemanticRecord | None = None
    manager: SemanticRecord | None = None
    compensation: SemanticRecord | None = None
    performance: SemanticRecord | None = None
    performance_summary: SemanticRecord | None = None
    attendance: SemanticRecord | None = None
    engagement: SemanticRecord | None = None
    experience: SemanticRecord | None = None
    succession_readiness: SemanticRecord | None = None
    skills: list[EmployeeSkillContext] = Field(default_factory=list)
    employment_history: list[SemanticRecord] = Field(default_factory=list)
    assignment_history: list[SemanticRecord] = Field(default_factory=list)
    compensation_history: list[SemanticRecord] = Field(default_factory=list)
    performance_history: list[SemanticRecord] = Field(default_factory=list)
    performance_summary_history: list[SemanticRecord] = Field(default_factory=list)
    attendance_history: list[SemanticRecord] = Field(default_factory=list)
    engagement_history: list[SemanticRecord] = Field(default_factory=list)
    experience_history: list[SemanticRecord] = Field(default_factory=list)
    learning_history: list[SemanticRecord] = Field(default_factory=list)
    career_movements: list[SemanticRecord] = Field(default_factory=list)
    succession_readiness_history: list[SemanticRecord] = Field(default_factory=list)
