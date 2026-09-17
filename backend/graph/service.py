"""Knowledge Graph model service.

Step 4 only: defines and validates graph instances. It does not ingest current
Supabase data and it does not refactor existing AI services.
"""

from __future__ import annotations

from pathlib import Path

from ontology.registry import DEFAULT_REGISTRY

from .ids import (
    make_node_graph_id,
    make_relationship_graph_id,
    make_source_record_identity,
)
from .models import GraphNode, GraphProvenance, GraphRelationship
from .schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from .validator import DEFAULT_GRAPH_VALIDATOR, GraphModelValidator


class KnowledgeGraphModelService:
    def __init__(
        self,
        schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
        validator: GraphModelValidator = DEFAULT_GRAPH_VALIDATOR,
    ) -> None:
        self.schema = schema
        self.validator = validator
        self.ontology = DEFAULT_REGISTRY

    def summary(self) -> dict:
        manifest = self.schema.manifest()
        validation = self.validator.report()
        return {
            "step": 4,
            "name": "HR Knowledge Graph Model",
            "version": manifest["version"],
            "ontology_version": manifest["ontology_version"],
            "storage_model": manifest["storage_model"],
            "node_type_count": len(manifest["nodes"]),
            "relationship_schema_count": len(manifest["relationships"]),
            "tenant_isolation": True,
            "provenance_model": True,
            "validation_error_count": validation["error_count"],
            "validation_warning_count": validation["warning_count"],
        }

    def validation_report(self) -> dict:
        return self.validator.report()

    def schema_manifest(self) -> dict:
        return self.schema.manifest()

    def identity_rules(self) -> dict:
        import json

        return json.loads(self.schema.identity_rules_file.read_text(encoding="utf-8"))

    def create_node(
        self,
        *,
        tenant_id: str,
        entity_type: str,
        properties: dict,
        source_system: str,
        source_object: str,
        source_record_key: str,
        mapping_version: str | None = None,
    ) -> GraphNode:
        rule = self.schema.identity_rule(entity_type)
        if rule.get("mode") == "ontology_property":
            prop = str(rule["property"])
            identity_key = str(properties.get(prop, "")).strip()
            if not identity_key:
                raise ValueError(
                    f"{entity_type} requires identity property {prop!r}"
                )
        else:
            identity_key = make_source_record_identity(
                source_system=source_system,
                source_object=source_object,
                source_record_key=source_record_key,
            )

        node = GraphNode(
            graph_id=make_node_graph_id(
                tenant_id=tenant_id,
                entity_type=entity_type,
                identity_key=identity_key,
            ),
            tenant_id=tenant_id,
            entity_type=entity_type,
            ontology_version=self.schema.ontology_version,
            properties=dict(properties),
            provenance=[
                GraphProvenance(
                    source_system=source_system,
                    source_object=source_object,
                    source_record_key=str(source_record_key),
                    mapping_version=mapping_version,
                )
            ],
        )
        errors = [
            item
            for item in self.validator.validate_node(node)
            if item.severity == "error"
        ]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))
        return node

    def create_relationship(
        self,
        *,
        tenant_id: str,
        relation_type: str,
        source_node: GraphNode,
        target_node: GraphNode,
        source_system: str,
        source_object: str,
        source_record_key: str,
        mapping_version: str | None = None,
        properties: dict | None = None,
    ) -> GraphRelationship:
        relationship = GraphRelationship(
            graph_id=make_relationship_graph_id(
                tenant_id=tenant_id,
                source_graph_id=source_node.graph_id,
                relation_type=relation_type,
                target_graph_id=target_node.graph_id,
            ),
            tenant_id=tenant_id,
            relation_type=relation_type,
            source_graph_id=source_node.graph_id,
            source_entity_type=source_node.entity_type,
            target_graph_id=target_node.graph_id,
            target_entity_type=target_node.entity_type,
            ontology_version=self.schema.ontology_version,
            properties=dict(properties or {}),
            provenance=[
                GraphProvenance(
                    source_system=source_system,
                    source_object=source_object,
                    source_record_key=str(source_record_key),
                    mapping_version=mapping_version,
                )
            ],
        )
        errors = [
            item
            for item in self.validator.validate_relationship(
                relationship, source_node, target_node
            )
            if item.severity == "error"
        ]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))
        return relationship

    def write_generated_files(self, root: str | Path | None = None) -> tuple[Path, Path]:
        import json

        package = Path(root).resolve() if root else Path(__file__).resolve().parent
        manifest_file = package / "graph_model_v1.json"
        cypher_file = package / "cypher" / "schema_v1.cypher"
        cypher_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(
            json.dumps(self.schema_manifest(), indent=2), encoding="utf-8"
        )
        cypher_file.write_text(
            "\n".join(statement + ";" for statement in self.schema.neo4j_schema_statements())
            + "\n",
            encoding="utf-8",
        )
        return manifest_file, cypher_file


GRAPH_MODEL_SERVICE = KnowledgeGraphModelService()
