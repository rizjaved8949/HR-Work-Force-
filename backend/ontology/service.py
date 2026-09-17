"""Read-only application service for ontology metadata."""

from __future__ import annotations

from .registry import DEFAULT_REGISTRY, OntologyRegistry
from .validator import validate_registry


class OntologyService:
    def __init__(self, registry: OntologyRegistry = DEFAULT_REGISTRY) -> None:
        self.registry = registry

    def summary(self) -> dict:
        ontology = self.registry.load()
        validation = validate_registry(self.registry)
        return {
            "name": ontology.name,
            "version": ontology.version,
            "status": ontology.status,
            "compatibility_mode": ontology.compatibility_mode,
            "module_count": len(ontology.modules),
            "entity_count": len(ontology.entities),
            "relationship_count": len(ontology.relationships),
            "service_contracts": self.registry.list_service_contracts(),
            "validation_error_count": sum(
                issue.severity == "error" for issue in validation
            ),
            "validation_warning_count": sum(
                issue.severity == "warning" for issue in validation
            ),
        }

    def list_modules(self) -> list[dict]:
        return [module.model_dump() for module in self.registry.load().modules]

    def list_entities(self) -> list[dict]:
        return [entity.model_dump() for entity in self.registry.list_entities()]

    def get_entity(self, entity_name: str) -> dict:
        entity = self.registry.get_entity(entity_name)
        return {
            **entity.model_dump(),
            "relationships": self.registry.relationships_for(entity_name),
        }

    def list_relationships(self) -> list[dict]:
        return [item.model_dump() for item in self.registry.load().relationships]

    def get_service_contract(self, service_name: str) -> dict:
        return self.registry.get_service_contract(service_name)

    def validation_report(self) -> dict:
        issues = validate_registry(self.registry)
        return {
            "valid": not any(issue.severity == "error" for issue in issues),
            "issues": [issue.model_dump() for issue in issues],
        }


ONTOLOGY_SERVICE = OntologyService()
