"""Convert approved source rows into validated canonical ontology records.

No repository writes happen here. Step 7 consumes these canonical records and
persists them to the Knowledge Graph.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from graph.ids import (
    make_node_graph_id,
    make_relationship_graph_id,
    make_source_record_identity,
)
from graph.models import GraphNode, GraphProvenance, GraphRelationship
from graph.schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from graph.validator import DEFAULT_GRAPH_VALIDATOR, GraphModelValidator
from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .models import (
    CanonicalBatch,
    CanonicalEntityRecord,
    CanonicalRelationshipRecord,
    EntityIngestionRule,
    IngestionIssue,
    MappingPlan,
)
from .transformers import transform_value
from .validator import DEFAULT_PLAN_VALIDATOR, MappingPlanValidator


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _record_key(row: dict[str, Any], columns: list[str]) -> str:
    pairs: list[str] = []
    for column in columns:
        value = _text(row.get(column))
        if not value:
            raise ValueError(f"Record-key value missing for source column {column!r}")
        pairs.append(f"{column}={value}")
    return "|".join(pairs)


def _parse_temporal(value: Any) -> datetime | None:
    if value is None or _text(value) == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed_date = date.fromisoformat(text)
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)


class Canonicalizer:
    def __init__(
        self,
        *,
        ontology: OntologyRegistry = DEFAULT_REGISTRY,
        graph_schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
        graph_validator: GraphModelValidator = DEFAULT_GRAPH_VALIDATOR,
        plan_validator: MappingPlanValidator = DEFAULT_PLAN_VALIDATOR,
    ) -> None:
        self.ontology = ontology
        self.graph_schema = graph_schema
        self.graph_validator = graph_validator
        self.plan_validator = plan_validator

    @staticmethod
    def _rule_map(plan: MappingPlan) -> dict[str, EntityIngestionRule]:
        return {item.entity_type: item for item in plan.entity_rules}

    def normalize(
        self,
        plan: MappingPlan,
        rows: list[dict[str, Any]],
        *,
        profile=None,
    ) -> CanonicalBatch:
        issues = self.plan_validator.validate(
            plan,
            profile=profile,
            require_approved=True,
        )
        batch = CanonicalBatch(
            tenant_id=plan.tenant_id,
            source_system=plan.source_system,
            source_object=plan.source_object,
            mapping_plan_id=plan.plan_id,
            mapping_version=plan.version,
            issues=list(issues),
        )
        if any(item.severity == "error" for item in issues):
            return batch

        mappings_by_entity: dict[str, list] = {}
        for mapping in plan.property_mappings:
            entity_type = mapping.ontology_path.split(".", 1)[0]
            mappings_by_entity.setdefault(entity_type, []).append(mapping)
        rule_map = self._rule_map(plan)

        for row_number, row in enumerate(rows, start=1):
            row_entities: dict[str, CanonicalEntityRecord] = {}
            for entity_type, mappings in mappings_by_entity.items():
                properties: dict[str, Any] = {}
                entity_errors: list[IngestionIssue] = []
                any_present = False
                for mapping in mappings:
                    raw = row.get(mapping.source_column)
                    if raw is not None and _text(raw) != "":
                        any_present = True
                    prop = self.ontology.get_property(mapping.ontology_path)
                    try:
                        value = transform_value(raw, prop, mapping)
                    except Exception as error:
                        entity_errors.append(
                            IngestionIssue(
                                severity="error",
                                code="value_transformation_failed",
                                message=str(error),
                                row_number=row_number,
                                source_column=mapping.source_column,
                                ontology_path=mapping.ontology_path,
                            )
                        )
                        continue
                    if value is not None:
                        properties[prop.name] = value

                if not any_present:
                    continue
                if entity_errors:
                    batch.issues.extend(entity_errors)
                    continue

                identity_rule = self.graph_schema.identity_rule(entity_type)
                entity_rule = rule_map.get(entity_type)
                try:
                    if identity_rule.get("mode") == "ontology_property":
                        identity_prop = str(identity_rule.get("property"))
                        identity_key = _text(properties.get(identity_prop))
                        if not identity_key:
                            raise ValueError(
                                f"Required business identity {entity_type}.{identity_prop} is empty"
                            )
                        source_record_key = (
                            _record_key(row, entity_rule.record_key_columns)
                            if entity_rule and entity_rule.record_key_columns
                            else identity_key
                        )
                    else:
                        if entity_rule is None or not entity_rule.record_key_columns:
                            raise ValueError(
                                f"Source-record entity {entity_type} requires explicit record_key_columns"
                            )
                        source_record_key = _record_key(row, entity_rule.record_key_columns)
                        identity_key = make_source_record_identity(
                            source_system=plan.source_system,
                            source_object=plan.source_object,
                            source_record_key=source_record_key,
                        )
                    graph_id = make_node_graph_id(
                        tenant_id=plan.tenant_id,
                        entity_type=entity_type,
                        identity_key=identity_key,
                    )
                    valid_from = (
                        _parse_temporal(row.get(entity_rule.valid_from_column))
                        if entity_rule and entity_rule.valid_from_column
                        else None
                    )
                    valid_to = (
                        _parse_temporal(row.get(entity_rule.valid_to_column))
                        if entity_rule and entity_rule.valid_to_column
                        else None
                    )
                except Exception as error:
                    batch.issues.append(
                        IngestionIssue(
                            severity="error",
                            code="entity_identity_or_temporal_error",
                            message=str(error),
                            row_number=row_number,
                        )
                    )
                    continue

                provenance = GraphProvenance(
                    source_system=plan.source_system,
                    source_object=plan.source_object,
                    source_record_key=source_record_key,
                    mapping_version=plan.version,
                )
                node = GraphNode(
                    graph_id=graph_id,
                    tenant_id=plan.tenant_id,
                    entity_type=entity_type,
                    ontology_version=plan.ontology_version,
                    properties=properties,
                    provenance=[provenance],
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
                node_issues = self.graph_validator.validate_node(node)
                errors = [item for item in node_issues if item.severity == "error"]
                if errors:
                    for item in errors:
                        batch.issues.append(
                            IngestionIssue(
                                severity="error",
                                code=f"graph_{item.code}",
                                message=item.message,
                                row_number=row_number,
                            )
                        )
                    continue
                record = CanonicalEntityRecord(
                    tenant_id=plan.tenant_id,
                    entity_type=entity_type,
                    graph_id=graph_id,
                    identity_key=identity_key,
                    source_system=plan.source_system,
                    source_object=plan.source_object,
                    source_record_key=source_record_key,
                    ontology_version=plan.ontology_version,
                    mapping_version=plan.version,
                    properties=properties,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    row_number=row_number,
                )
                batch.entities.append(record)
                row_entities[entity_type] = record

            for relation in plan.relationship_mappings:
                source = row_entities.get(relation.source_entity_type)
                if source is None:
                    if not relation.skip_if_empty:
                        batch.issues.append(
                            IngestionIssue(
                                severity="error",
                                code="relationship_source_missing",
                                message=f"Source entity {relation.source_entity_type} was not produced for row.",
                                row_number=row_number,
                            )
                        )
                    continue

                target: CanonicalEntityRecord | None = None
                target_graph_id: str | None = None
                target_identity_key: str | None = None
                if relation.target_mode == "same_row_entity":
                    target = row_entities.get(relation.target_entity_type)
                    if target is not None:
                        target_graph_id = target.graph_id
                        target_identity_key = target.identity_key
                else:
                    raw_target = row.get(str(relation.target_source_column))
                    target_identity_key = _text(raw_target)
                    if target_identity_key:
                        target_graph_id = make_node_graph_id(
                            tenant_id=plan.tenant_id,
                            entity_type=relation.target_entity_type,
                            identity_key=target_identity_key,
                        )

                if not target_graph_id:
                    if not relation.skip_if_empty:
                        batch.issues.append(
                            IngestionIssue(
                                severity="error",
                                code="relationship_target_missing",
                                message=(
                                    f"Target for {relation.source_entity_type}-{relation.relation_type}->"
                                    f"{relation.target_entity_type} is missing."
                                ),
                                row_number=row_number,
                                source_column=relation.target_source_column,
                            )
                        )
                    continue

                edge_id = make_relationship_graph_id(
                    tenant_id=plan.tenant_id,
                    source_graph_id=source.graph_id,
                    relation_type=relation.relation_type,
                    target_graph_id=target_graph_id,
                )
                provenance = GraphProvenance(
                    source_system=plan.source_system,
                    source_object=plan.source_object,
                    source_record_key=source.source_record_key,
                    mapping_version=plan.version,
                )
                edge = GraphRelationship(
                    graph_id=edge_id,
                    tenant_id=plan.tenant_id,
                    relation_type=relation.relation_type,
                    source_graph_id=source.graph_id,
                    source_entity_type=relation.source_entity_type,
                    target_graph_id=target_graph_id,
                    target_entity_type=relation.target_entity_type,
                    ontology_version=plan.ontology_version,
                    provenance=[provenance],
                )
                source_node = GraphNode(
                    graph_id=source.graph_id,
                    tenant_id=source.tenant_id,
                    entity_type=source.entity_type,
                    ontology_version=source.ontology_version,
                    properties=source.properties,
                )
                target_node = None
                if target is not None:
                    target_node = GraphNode(
                        graph_id=target.graph_id,
                        tenant_id=target.tenant_id,
                        entity_type=target.entity_type,
                        ontology_version=target.ontology_version,
                        properties=target.properties,
                    )
                edge_issues = self.graph_validator.validate_relationship(
                    edge, source_node, target_node
                )
                errors = [item for item in edge_issues if item.severity == "error"]
                if errors:
                    for item in errors:
                        batch.issues.append(
                            IngestionIssue(
                                severity="error",
                                code=f"graph_{item.code}",
                                message=item.message,
                                row_number=row_number,
                            )
                        )
                    continue
                batch.relationships.append(
                    CanonicalRelationshipRecord(
                        tenant_id=plan.tenant_id,
                        relation_type=relation.relation_type,
                        source_entity_type=relation.source_entity_type,
                        target_entity_type=relation.target_entity_type,
                        source_graph_id=source.graph_id,
                        target_graph_id=target_graph_id,
                        graph_id=edge_id,
                        source_system=plan.source_system,
                        source_object=plan.source_object,
                        source_record_key=source.source_record_key,
                        ontology_version=plan.ontology_version,
                        mapping_version=plan.version,
                        row_number=row_number,
                    )
                )
        return batch


DEFAULT_CANONICALIZER = Canonicalizer()
