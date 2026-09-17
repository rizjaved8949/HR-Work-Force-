"""Knowledge Graph model validation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ontology.registry import DEFAULT_REGISTRY

from .models import GraphNode, GraphRelationship, GraphValidationIssue
from .schema import DEFAULT_GRAPH_SCHEMA, GraphSchema


class GraphModelValidator:
    def __init__(self, schema: GraphSchema = DEFAULT_GRAPH_SCHEMA) -> None:
        self.schema = schema
        self.ontology = schema.ontology_registry

    def validate_schema(self) -> list[GraphValidationIssue]:
        issues: list[GraphValidationIssue] = []
        definition = self.ontology.load()
        entity_names = {item.name for item in definition.entities}

        if self.schema.identity_rules_version == "unknown":
            issues.append(
                GraphValidationIssue(
                    severity="error",
                    code="identity_rules_version_missing",
                    message="Graph identity rules must have a version.",
                )
            )

        for entity in definition.entities:
            rule = self.schema.identity_rule(entity.name)
            mode = rule.get("mode", "source_record")
            if mode not in {"ontology_property", "source_record"}:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="invalid_identity_mode",
                        location=entity.name,
                        message=f"Unsupported identity mode: {mode!r}",
                    )
                )
            if mode == "ontology_property":
                prop = rule.get("property")
                if not prop or not self.ontology.ontology_path_exists(f"{entity.name}.{prop}"):
                    issues.append(
                        GraphValidationIssue(
                            severity="error",
                            code="identity_property_missing",
                            location=entity.name,
                            message=f"Identity property {prop!r} is not defined on {entity.name}.",
                        )
                    )

        for rel in definition.relationships:
            if rel.source not in entity_names or rel.target not in entity_names:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="relationship_unknown_entity",
                        location=f"{rel.source}-{rel.relation}->{rel.target}",
                        message="Relationship references an unknown ontology entity.",
                    )
                )

        return issues

    @staticmethod
    def _value_compatible(data_type: str, value: Any) -> bool:
        if value is None:
            return True
        if data_type == "string":
            return isinstance(value, str)
        if data_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if data_type == "decimal":
            return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
        if data_type == "boolean":
            return isinstance(value, bool)
        if data_type == "date":
            return isinstance(value, (date, str))
        if data_type in {"datetime", "timestamp"}:
            return isinstance(value, (datetime, str))
        if data_type in {"object", "json"}:
            return isinstance(value, (dict, list, str))
        return True

    def validate_node(self, node: GraphNode) -> list[GraphValidationIssue]:
        issues: list[GraphValidationIssue] = []
        try:
            entity = self.ontology.get_entity(node.entity_type)
        except KeyError:
            return [
                GraphValidationIssue(
                    severity="error",
                    code="unknown_entity_type",
                    location=node.entity_type,
                    message=f"Unknown ontology entity type: {node.entity_type}",
                )
            ]

        allowed = {item.name: item for item in entity.properties}
        for key, value in node.properties.items():
            prop = allowed.get(key)
            if prop is None:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="unknown_node_property",
                        location=f"{node.entity_type}.{key}",
                        message="Property is not defined in the ontology.",
                    )
                )
            elif not self._value_compatible(prop.data_type, value):
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="incompatible_property_type",
                        location=f"{node.entity_type}.{key}",
                        message=f"Expected semantic type {prop.data_type!r}; found {type(value).__name__}.",
                    )
                )

        rule = self.schema.identity_rule(node.entity_type)
        if rule.get("mode") == "ontology_property":
            prop_name = rule.get("property")
            if not str(node.properties.get(prop_name, "")).strip():
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="node_identity_value_missing",
                        location=f"{node.entity_type}.{prop_name}",
                        message="Stable business identity value is required for this node type.",
                    )
                )

        if node.entity_type == "Organization":
            organization_id = str(node.properties.get("organizationId", "")).strip()
            if organization_id and organization_id != node.tenant_id:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="organization_tenant_mismatch",
                        location="Organization.organizationId",
                        message="Organization.organizationId must equal tenant_id in the graph model.",
                    )
                )
        return issues

    def validate_relationship(
        self,
        relationship: GraphRelationship,
        source_node: GraphNode | None = None,
        target_node: GraphNode | None = None,
    ) -> list[GraphValidationIssue]:
        issues: list[GraphValidationIssue] = []
        if not self.schema.allowed_relationship(
            relationship.source_entity_type,
            relationship.relation_type,
            relationship.target_entity_type,
        ):
            issues.append(
                GraphValidationIssue(
                    severity="error",
                    code="relationship_not_in_ontology",
                    location=(
                        f"{relationship.source_entity_type}-"
                        f"{relationship.relation_type}->{relationship.target_entity_type}"
                    ),
                    message="Relationship triple is not defined in HR Ontology v1.",
                )
            )

        if source_node is not None:
            if source_node.graph_id != relationship.source_graph_id:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="source_graph_id_mismatch",
                        message="Source node does not match relationship source_graph_id.",
                    )
                )
            if source_node.tenant_id != relationship.tenant_id:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="cross_tenant_relationship",
                        message="Relationship and source node have different tenants.",
                    )
                )

        if target_node is not None:
            if target_node.graph_id != relationship.target_graph_id:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="target_graph_id_mismatch",
                        message="Target node does not match relationship target_graph_id.",
                    )
                )
            if target_node.tenant_id != relationship.tenant_id:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="cross_tenant_relationship",
                        message="Relationship and target node have different tenants.",
                    )
                )

        if source_node is not None and target_node is not None:
            if source_node.tenant_id != target_node.tenant_id:
                issues.append(
                    GraphValidationIssue(
                        severity="error",
                        code="cross_tenant_relationship",
                        message="Cross-tenant graph relationships are forbidden.",
                    )
                )
        return issues

    def report(self) -> dict:
        issues = self.validate_schema()
        return {
            "valid": not any(item.severity == "error" for item in issues),
            "error_count": sum(item.severity == "error" for item in issues),
            "warning_count": sum(item.severity == "warning" for item in issues),
            "issues": [item.model_dump() for item in issues],
        }


DEFAULT_GRAPH_VALIDATOR = GraphModelValidator()
