"""Read-only registry for HR Ontology v1 and AI service contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import OntologyDefinition, OntologyEntity, OntologyProperty


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_ONTOLOGY_FILE = PACKAGE_DIR / "hr_ontology_v1.json"
SERVICE_CONTRACT_DIR = PACKAGE_DIR / "service_contracts"


class OntologyRegistryError(RuntimeError):
    """Raised when ontology metadata cannot be loaded or resolved."""


class OntologyRegistry:
    """Load and query ontology metadata without touching runtime HR services."""

    def __init__(self, ontology_file: str | Path = DEFAULT_ONTOLOGY_FILE) -> None:
        self.ontology_file = Path(ontology_file).resolve()

    @lru_cache(maxsize=1)
    def load(self) -> OntologyDefinition:
        try:
            payload = json.loads(self.ontology_file.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise OntologyRegistryError(
                f"Ontology definition not found: {self.ontology_file}"
            ) from error
        except json.JSONDecodeError as error:
            raise OntologyRegistryError(
                f"Ontology definition is invalid JSON: {self.ontology_file}: {error}"
            ) from error

        try:
            return OntologyDefinition.model_validate(payload)
        except Exception as error:  # pydantic gives detailed nested errors
            raise OntologyRegistryError(
                f"Ontology definition failed schema validation: {error}"
            ) from error

    def refresh(self) -> None:
        self.load.cache_clear()

    def list_entities(self) -> list[OntologyEntity]:
        return list(self.load().entities)

    def get_entity(self, entity_name: str) -> OntologyEntity:
        for entity in self.load().entities:
            if entity.name == entity_name:
                return entity
        raise KeyError(f"Unknown ontology entity: {entity_name!r}")

    def get_property(self, ontology_path: str) -> OntologyProperty:
        if "." not in ontology_path:
            raise KeyError(
                f"Ontology property path must be Entity.property; found {ontology_path!r}"
            )
        entity_name, property_name = ontology_path.split(".", 1)
        entity = self.get_entity(entity_name)
        for item in entity.properties:
            if item.name == property_name:
                return item
        raise KeyError(f"Unknown ontology property: {ontology_path!r}")

    def ontology_path_exists(self, ontology_path: str) -> bool:
        try:
            self.get_property(ontology_path)
            return True
        except KeyError:
            return False

    def relationships_for(self, entity_name: str) -> list[dict]:
        self.get_entity(entity_name)  # fail early on typo
        return [
            relationship.model_dump()
            for relationship in self.load().relationships
            if relationship.source == entity_name or relationship.target == entity_name
        ]

    def list_service_contracts(self) -> list[str]:
        if not SERVICE_CONTRACT_DIR.is_dir():
            return []
        return sorted(path.stem for path in SERVICE_CONTRACT_DIR.glob("*.json"))

    @lru_cache(maxsize=32)
    def get_service_contract(self, service_name: str) -> dict:
        path = SERVICE_CONTRACT_DIR / f"{service_name}.json"
        if not path.is_file():
            raise KeyError(f"Unknown ontology service contract: {service_name!r}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise OntologyRegistryError(
                f"Service contract is invalid JSON: {path}: {error}"
            ) from error


DEFAULT_REGISTRY = OntologyRegistry()
