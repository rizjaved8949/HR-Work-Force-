"""Validation for Step-6 human-approved mapping plans."""
from __future__ import annotations

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry
from graph.schema import DEFAULT_GRAPH_SCHEMA, GraphSchema

from .models import IngestionIssue, MappingPlan, SourceSchemaProfile


class MappingPlanValidator:
    def __init__(
        self,
        ontology: OntologyRegistry = DEFAULT_REGISTRY,
        graph_schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
    ) -> None:
        self.ontology = ontology
        self.graph_schema = graph_schema

    def validate(
        self,
        plan: MappingPlan,
        *,
        profile: SourceSchemaProfile | None = None,
        require_approved: bool = False,
    ) -> list[IngestionIssue]:
        issues: list[IngestionIssue] = []
        if require_approved and plan.status != "approved":
            issues.append(
                IngestionIssue(
                    severity="error",
                    code="mapping_plan_not_approved",
                    message="Transformation is allowed only for an approved mapping plan.",
                )
            )
        if plan.ontology_version != self.ontology.load().version:
            issues.append(
                IngestionIssue(
                    severity="error",
                    code="ontology_version_mismatch",
                    message=(
                        f"Plan ontology version {plan.ontology_version!r} does not match "
                        f"loaded ontology {self.ontology.load().version!r}."
                    ),
                )
            )

        if profile is not None:
            if profile.source_system != plan.source_system:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="source_system_mismatch",
                        message=f"Profile source_system {profile.source_system!r} does not match plan {plan.source_system!r}.",
                    )
                )
            if profile.source_object != plan.source_object:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="source_object_mismatch",
                        message=f"Profile source_object {profile.source_object!r} does not match plan {plan.source_object!r}.",
                    )
                )
            if profile.source_format != plan.source_format:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="source_format_mismatch",
                        message=f"Profile source_format {profile.source_format!r} does not match plan {plan.source_format!r}.",
                    )
                )

        source_columns = {item.name for item in profile.columns} if profile else None
        seen_sources: set[str] = set()
        seen_paths: set[str] = set()
        mapped_entities: set[str] = set()
        for mapping in plan.property_mappings:
            if mapping.source_column in seen_sources:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="duplicate_source_column_mapping",
                        source_column=mapping.source_column,
                        message="A source column may map to at most one ontology property within one plan.",
                    )
                )
            seen_sources.add(mapping.source_column)
            if mapping.ontology_path in seen_paths:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="duplicate_ontology_path_mapping",
                        ontology_path=mapping.ontology_path,
                        message="An ontology property may be populated by at most one source column within one plan.",
                    )
                )
            seen_paths.add(mapping.ontology_path)
            if source_columns is not None and mapping.source_column not in source_columns:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="source_column_missing",
                        source_column=mapping.source_column,
                        message="Approved mapping references a column not present in the profiled source.",
                    )
                )
            try:
                prop = self.ontology.get_property(mapping.ontology_path)
            except KeyError:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="unknown_ontology_path",
                        ontology_path=mapping.ontology_path,
                        message="Approved mapping references a property not defined in HR Ontology v1.",
                    )
                )
                continue
            entity_type = mapping.ontology_path.split(".", 1)[0]
            mapped_entities.add(entity_type)
            if prop.semantic_status != "confirmed" and not mapping.semantic_override_reason:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="pending_semantic_requires_override",
                        ontology_path=mapping.ontology_path,
                        message=(
                            "Ontology property is not semantically confirmed. An explicit "
                            "semantic_override_reason is required before ingestion."
                        ),
                    )
                )
            if mapping.numeric_divisor == 0:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="numeric_divisor_zero",
                        source_column=mapping.source_column,
                        message="numeric_divisor cannot be zero.",
                    )
                )

        rules = {rule.entity_type: rule for rule in plan.entity_rules}
        if len(rules) != len(plan.entity_rules):
            issues.append(
                IngestionIssue(
                    severity="error",
                    code="duplicate_entity_rule",
                    message="Each entity type may have only one EntityIngestionRule per plan.",
                )
            )

        for entity_type in mapped_entities:
            rule = self.graph_schema.identity_rule(entity_type)
            identity_mode = rule.get("mode", "source_record")
            if identity_mode == "ontology_property":
                identity_path = f"{entity_type}.{rule.get('property')}"
                if identity_path not in seen_paths:
                    issues.append(
                        IngestionIssue(
                            severity="error",
                            code="entity_identity_mapping_missing",
                            ontology_path=identity_path,
                            message=(
                                f"Mapped entity {entity_type} requires its stable identity property "
                                "to be mapped in the same source plan."
                            ),
                        )
                    )
            else:
                entity_rule = rules.get(entity_type)
                if entity_rule is None or not entity_rule.record_key_columns:
                    issues.append(
                        IngestionIssue(
                            severity="error",
                            code="source_record_key_rule_missing",
                            message=(
                                f"Entity {entity_type} has source-record identity and therefore "
                                "requires explicit record_key_columns."
                            ),
                        )
                    )
                elif source_columns is not None:
                    for column in entity_rule.record_key_columns:
                        if column not in source_columns:
                            issues.append(
                                IngestionIssue(
                                    severity="error",
                                    code="record_key_column_missing",
                                    source_column=column,
                                    message=f"Record-key column for {entity_type} is missing from source.",
                                )
                            )

        for entity_rule in plan.entity_rules:
            try:
                self.ontology.get_entity(entity_rule.entity_type)
            except KeyError:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="unknown_entity_rule",
                        message=f"Unknown entity type in ingestion rule: {entity_rule.entity_type}",
                    )
                )
            if source_columns is not None:
                for column in (
                    list(entity_rule.record_key_columns)
                    + ([entity_rule.valid_from_column] if entity_rule.valid_from_column else [])
                    + ([entity_rule.valid_to_column] if entity_rule.valid_to_column else [])
                ):
                    if column not in source_columns:
                        issues.append(
                            IngestionIssue(
                                severity="error",
                                code="entity_rule_column_missing",
                                source_column=column,
                                message=f"Entity rule references missing source column {column!r}.",
                            )
                        )

        for relationship in plan.relationship_mappings:
            if not self.graph_schema.allowed_relationship(
                relationship.source_entity_type,
                relationship.relation_type,
                relationship.target_entity_type,
            ):
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="relationship_not_in_ontology",
                        message=(
                            f"{relationship.source_entity_type}-{relationship.relation_type}->"
                            f"{relationship.target_entity_type} is not defined in HR Ontology v1."
                        ),
                    )
                )
            if relationship.source_entity_type not in mapped_entities:
                issues.append(
                    IngestionIssue(
                        severity="error",
                        code="relationship_source_not_mapped",
                        message=f"Relationship source entity {relationship.source_entity_type} is not produced by this plan.",
                    )
                )
            if relationship.target_mode == "same_row_entity":
                if relationship.target_entity_type not in mapped_entities:
                    issues.append(
                        IngestionIssue(
                            severity="error",
                            code="relationship_target_not_mapped",
                            message=f"same_row_entity target {relationship.target_entity_type} is not produced by this plan.",
                        )
                    )
            else:
                if not relationship.target_source_column:
                    issues.append(
                        IngestionIssue(
                            severity="error",
                            code="relationship_target_column_missing",
                            message="business_id_reference requires target_source_column.",
                        )
                    )
                elif source_columns is not None and relationship.target_source_column not in source_columns:
                    issues.append(
                        IngestionIssue(
                            severity="error",
                            code="relationship_target_source_column_missing",
                            source_column=relationship.target_source_column,
                            message="Relationship target reference column is absent from source.",
                        )
                    )
                target_rule = self.graph_schema.identity_rule(relationship.target_entity_type)
                if target_rule.get("mode") != "ontology_property":
                    issues.append(
                        IngestionIssue(
                            severity="error",
                            code="relationship_reference_target_not_business_identified",
                            message=(
                                "business_id_reference can only target an entity with a confirmed "
                                "ontology business-ID identity rule."
                            ),
                        )
                    )
        return issues

    def report(self, plan: MappingPlan, *, profile: SourceSchemaProfile | None = None) -> dict:
        issues = self.validate(plan, profile=profile)
        return {
            "valid": not any(item.severity == "error" for item in issues),
            "error_count": sum(item.severity == "error" for item in issues),
            "warning_count": sum(item.severity == "warning" for item in issues),
            "issues": [item.model_dump() for item in issues],
        }


DEFAULT_PLAN_VALIDATOR = MappingPlanValidator()
