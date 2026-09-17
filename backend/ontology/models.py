"""Typed models for the read-only HR Ontology v1 metadata layer.

This package is intentionally isolated from the existing AI services.  It is
safe to import independently and does not change any production service path.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OntologyProperty(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    data_type: str
    description: str
    semantic_status: str = "confirmed"
    derived: bool = False
    unit: str | None = None
    current_source_fields: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    observed_current_data: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    notes: str | None = None


class OntologyEntity(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    module: str
    description: str
    properties: list[OntologyProperty] = Field(default_factory=list)


class OntologyModule(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str


class OntologyRelationship(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    relation: str
    target: str
    cardinality: str
    description: str
    semantic_status: str = "confirmed"


class OntologyDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    version: str
    status: str
    compatibility_mode: str
    design_principles: list[str] = Field(default_factory=list)
    modules: list[OntologyModule] = Field(default_factory=list)
    entities: list[OntologyEntity] = Field(default_factory=list)
    relationships: list[OntologyRelationship] = Field(default_factory=list)
    derived_concepts: list[dict] = Field(default_factory=list)
    known_semantic_open_items: list[dict] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: str
    code: str
    message: str
    location: str | None = None
