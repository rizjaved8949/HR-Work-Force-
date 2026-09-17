from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFINITION_DIR = PACKAGE_DIR / "definitions"
DEFAULT_MAPPING_FILE = DEFINITION_DIR / "current_data_mappings.json"
DEFAULT_RELATIONSHIP_FILE = DEFINITION_DIR / "relationship_rules.json"


class MappingRegistry:
    def __init__(self, mapping_file: Path = DEFAULT_MAPPING_FILE, relationship_file: Path = DEFAULT_RELATIONSHIP_FILE):
        self.mapping_file = Path(mapping_file)
        self.relationship_file = Path(relationship_file)

    @lru_cache(maxsize=1)
    def load(self) -> dict:
        return json.loads(self.mapping_file.read_text(encoding="utf-8"))

    @lru_cache(maxsize=1)
    def relationships(self) -> dict:
        return json.loads(self.relationship_file.read_text(encoding="utf-8"))

    def dataset(self, source_file: str) -> dict:
        for item in self.load()["datasets"]:
            if item["source_file"] == source_file:
                return item
        raise KeyError(source_file)

    def mapped_paths(self) -> set[str]:
        result: set[str] = set()
        for dataset in self.load()["datasets"]:
            for item in dataset["columns"]:
                path = item.get("ontology_path")
                if path and item["disposition"] in {"direct_property", "context_property"}:
                    result.add(path)
        return result


DEFAULT_MAPPING_REGISTRY = MappingRegistry()
