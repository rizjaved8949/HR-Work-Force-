"""Derive the Knowledge Graph schema from HR Ontology v1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry


PACKAGE_DIR = Path(__file__).resolve().parent
IDENTITY_RULES_FILE = PACKAGE_DIR / "identity_rules.json"


@dataclass(frozen=True)
class NodeSchema:
    label: str
    module: str
    property_names: tuple[str, ...]
    identity_mode: str
    identity_property: str | None


@dataclass(frozen=True)
class RelationshipSchema:
    source_label: str
    relation_type: str
    target_label: str
    cardinality: str


class GraphSchema:
    """Storage schema derived from ontology plus graph identity rules."""

    def __init__(
        self,
        ontology_registry: OntologyRegistry = DEFAULT_REGISTRY,
        identity_rules_file: str | Path = IDENTITY_RULES_FILE,
    ) -> None:
        self.ontology_registry = ontology_registry
        self.identity_rules_file = Path(identity_rules_file).resolve()
        self._identity_rules = self._load_identity_rules()

    def _load_identity_rules(self) -> dict:
        return json.loads(self.identity_rules_file.read_text(encoding="utf-8"))

    @property
    def ontology_version(self) -> str:
        return self.ontology_registry.load().version

    @property
    def identity_rules_version(self) -> str:
        return str(self._identity_rules.get("version", "unknown"))

    def identity_rule(self, entity_type: str) -> dict:
        self.ontology_registry.get_entity(entity_type)
        return self._identity_rules.get("entities", {}).get(
            entity_type,
            {"mode": self._identity_rules.get("default_mode", "source_record")},
        )

    def node_schemas(self) -> list[NodeSchema]:
        result: list[NodeSchema] = []
        for entity in self.ontology_registry.list_entities():
            rule = self.identity_rule(entity.name)
            result.append(
                NodeSchema(
                    label=entity.name,
                    module=entity.module,
                    property_names=tuple(item.name for item in entity.properties),
                    identity_mode=str(rule.get("mode", "source_record")),
                    identity_property=rule.get("property"),
                )
            )
        return result

    def relationship_schemas(self) -> list[RelationshipSchema]:
        return [
            RelationshipSchema(
                source_label=item.source,
                relation_type=item.relation,
                target_label=item.target,
                cardinality=item.cardinality,
            )
            for item in self.ontology_registry.load().relationships
        ]

    def allowed_relationship(
        self, source_label: str, relation_type: str, target_label: str
    ) -> bool:
        return any(
            item.source_label == source_label
            and item.relation_type == relation_type
            and item.target_label == target_label
            for item in self.relationship_schemas()
        )

    def manifest(self) -> dict:
        nodes = self.node_schemas()
        edges = self.relationship_schemas()
        return {
            "version": "1.0.0-step4",
            "ontology_version": self.ontology_version,
            "identity_rules_version": self.identity_rules_version,
            "storage_model": "property_graph",
            "base_node_label": "KGNode",
            "tenant_isolation": {
                "required": True,
                "tenant_property": "kg_tenant_id",
                "rule": "Every node and relationship is tenant-scoped; cross-tenant relationships are rejected.",
            },
            "node_metadata": [
                "kg_graph_id",
                "kg_tenant_id",
                "kg_entity_type",
                "kg_ontology_version",
                "kg_provenance_json",
                "kg_valid_from",
                "kg_valid_to",
                "kg_created_at",
                "kg_updated_at"
            ],
            "relationship_metadata": [
                "kg_graph_id",
                "kg_tenant_id",
                "kg_ontology_version",
                "kg_provenance_json",
                "kg_valid_from",
                "kg_valid_to",
                "kg_created_at",
                "kg_updated_at"
            ],
            "nodes": [
                {
                    "label": item.label,
                    "module": item.module,
                    "property_names": list(item.property_names),
                    "identity_mode": item.identity_mode,
                    "identity_property": item.identity_property,
                }
                for item in nodes
            ],
            "relationships": [
                {
                    "source_label": item.source_label,
                    "relation_type": item.relation_type,
                    "target_label": item.target_label,
                    "cardinality": item.cardinality,
                }
                for item in edges
            ],
        }

    def neo4j_schema_statements(self) -> list[str]:
        # Keep DB constraints deliberately minimal and Neo4j-community-friendly.
        # graph_id is globally deterministic and tenant-scoped by construction.
        return [
            "CREATE CONSTRAINT kg_node_graph_id IF NOT EXISTS FOR (n:KGNode) REQUIRE n.kg_graph_id IS UNIQUE",
            "CREATE INDEX kg_node_tenant IF NOT EXISTS FOR (n:KGNode) ON (n.kg_tenant_id)",
            "CREATE INDEX kg_node_entity_type IF NOT EXISTS FOR (n:KGNode) ON (n.kg_entity_type)",
        ]


DEFAULT_GRAPH_SCHEMA = GraphSchema()
