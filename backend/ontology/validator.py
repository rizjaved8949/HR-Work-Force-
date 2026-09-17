"""Structural validation for HR Ontology v1.

The validator only validates metadata.  It does not read production HR data,
call models, or modify any existing service behavior.
"""

from __future__ import annotations

from .models import ValidationIssue
from .registry import OntologyRegistry


ALLOWED_DATA_TYPES = {
    "string",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "json",
}


def validate_registry(registry: OntologyRegistry) -> list[ValidationIssue]:
    ontology = registry.load()
    issues: list[ValidationIssue] = []

    module_ids = [module.id for module in ontology.modules]
    if len(module_ids) != len(set(module_ids)):
        issues.append(
            ValidationIssue(
                severity="error",
                code="duplicate_module",
                message="Ontology contains duplicate module IDs.",
            )
        )

    entity_names = [entity.name for entity in ontology.entities]
    entity_set = set(entity_names)
    if len(entity_names) != len(entity_set):
        issues.append(
            ValidationIssue(
                severity="error",
                code="duplicate_entity",
                message="Ontology contains duplicate entity names.",
            )
        )

    module_set = set(module_ids)
    for entity in ontology.entities:
        if entity.module not in module_set:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_module",
                    message=f"Entity {entity.name} references unknown module {entity.module}.",
                    location=entity.name,
                )
            )

        property_names = [item.name for item in entity.properties]
        if len(property_names) != len(set(property_names)):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_property",
                    message=f"Entity {entity.name} contains duplicate property names.",
                    location=entity.name,
                )
            )

        for item in entity.properties:
            if item.data_type not in ALLOWED_DATA_TYPES:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="unsupported_data_type",
                        message=(
                            f"{entity.name}.{item.name} uses unsupported semantic type "
                            f"{item.data_type!r}."
                        ),
                        location=f"{entity.name}.{item.name}",
                    )
                )
            if item.semantic_status == "pending_confirmation":
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="pending_semantic_confirmation",
                        message=(
                            f"{entity.name}.{item.name} is intentionally not frozen because "
                            "its exact semantic definition/scale is not confirmed."
                        ),
                        location=f"{entity.name}.{item.name}",
                    )
                )

    relationship_keys: set[tuple[str, str, str]] = set()
    for relationship in ontology.relationships:
        key = (relationship.source, relationship.relation, relationship.target)
        if key in relationship_keys:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_relationship",
                    message=f"Duplicate relationship {key}.",
                )
            )
        relationship_keys.add(key)

        if relationship.source not in entity_set:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_relationship_source",
                    message=(
                        f"Relationship {relationship.relation} has unknown source "
                        f"{relationship.source}."
                    ),
                )
            )
        if relationship.target not in entity_set:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_relationship_target",
                    message=(
                        f"Relationship {relationship.relation} has unknown target "
                        f"{relationship.target}."
                    ),
                )
            )

    # Validate ontology property paths in contracts when they are explicit.
    path_fields = {"ontology_path"}
    for contract_name in registry.list_service_contracts():
        contract = registry.get_service_contract(contract_name)
        for path, location in _walk_ontology_paths(contract, path_fields):
            if not registry.ontology_path_exists(path):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="unknown_contract_ontology_path",
                        message=(
                            f"Contract {contract_name} references unknown ontology path {path}."
                        ),
                        location=location,
                    )
                )

    return issues


def _walk_ontology_paths(value: object, path_fields: set[str], location: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key in path_fields and isinstance(child, str):
                yield child, child_location
            else:
                yield from _walk_ontology_paths(child, path_fields, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_ontology_paths(child, path_fields, f"{location}[{index}]")


def assert_valid(registry: OntologyRegistry) -> list[ValidationIssue]:
    issues = validate_registry(registry)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        detail = "\n".join(f"- [{issue.code}] {issue.message}" for issue in errors)
        raise RuntimeError(f"Ontology validation failed:\n{detail}")
    return issues
