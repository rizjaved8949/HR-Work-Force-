from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry
from .registry import DEFAULT_MAPPING_REGISTRY, MappingRegistry


def _headers(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


def validate_current_mapping(
    data_dir: Path,
    mapping_registry: MappingRegistry = DEFAULT_MAPPING_REGISTRY,
    ontology_registry: OntologyRegistry = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    payload = mapping_registry.load()
    seen_files: set[str] = set()

    for dataset in payload["datasets"]:
        rel = dataset["source_file"]
        if rel in seen_files:
            issues.append({"severity":"error","code":"duplicate_dataset","location":rel,"message":"Duplicate mapping dataset."})
            continue
        seen_files.add(rel)
        path = data_dir / rel
        if not path.is_file():
            issues.append({"severity":"error","code":"missing_source_file","location":rel,"message":"Mapped source file does not exist."})
            continue
        headers = set(_headers(path))
        mapped_columns = {item["source_column"] for item in dataset["columns"]}
        missing_defs = sorted(headers - mapped_columns)
        extra_defs = sorted(mapped_columns - headers)
        if missing_defs:
            issues.append({"severity":"error","code":"unclassified_source_columns","location":rel,"message":f"Columns without Step-3 classification: {missing_defs}"})
        if extra_defs:
            issues.append({"severity":"error","code":"mapping_columns_not_in_source","location":rel,"message":f"Mapping refers to absent columns: {extra_defs}"})
        for item in dataset["columns"]:
            ontology_path = item.get("ontology_path")
            if ontology_path and not ontology_registry.ontology_path_exists(ontology_path):
                issues.append({"severity":"error","code":"unknown_ontology_path","location":f"{rel}:{item['source_column']}","message":ontology_path})
            if item["disposition"] == "unresolved_ontology_gap":
                issues.append({"severity":"warning","code":"ontology_gap","location":f"{rel}:{item['source_column']}","message":item.get("reason", "Unresolved ontology gap")})

    relationship_set = {
        (r.source, r.relation, r.target)
        for r in ontology_registry.load().relationships
    }
    for rule in mapping_registry.relationships()["rules"]:
        triple = (rule["source_entity"], rule["relation"], rule["target_entity"])
        if triple not in relationship_set:
            issues.append({"severity":"error","code":"unknown_relationship","location":rule["id"],"message":str(triple)})
        source = data_dir / rule["source_file"]
        if source.is_file():
            headers = set(_headers(source))
            for col in rule.get("required_columns", []):
                if col not in headers:
                    issues.append({"severity":"error","code":"relationship_column_missing","location":rule["id"],"message":col})

    errors = [x for x in issues if x["severity"] == "error"]
    warnings = [x for x in issues if x["severity"] == "warning"]
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(warnings), "issues": issues}
