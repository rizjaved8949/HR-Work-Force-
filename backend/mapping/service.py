from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontology.registry import DEFAULT_REGISTRY
from .registry import DEFAULT_MAPPING_REGISTRY
from .schema_profiler import profile_data_directory
from .validator import validate_current_mapping
from .supabase_validator import validate_supabase_mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "Data"


class CurrentMappingService:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)

    def validation_report(self) -> dict[str, Any]:
        return validate_current_mapping(self.data_dir)

    def summary(self) -> dict[str, Any]:
        payload = DEFAULT_MAPPING_REGISTRY.load()
        columns = [c for d in payload["datasets"] for c in d["columns"]]
        dispositions: dict[str, int] = {}
        for item in columns:
            dispositions[item["disposition"]] = dispositions.get(item["disposition"], 0) + 1
        report = self.validation_report()
        return {
            "mapping_version": payload["version"],
            "source_dataset_count": len(payload["datasets"]),
            "source_column_count": len(columns),
            "dispositions": dict(sorted(dispositions.items())),
            "relationship_rule_count": len(DEFAULT_MAPPING_REGISTRY.relationships()["rules"]),
            "validation_error_count": report["error_count"],
            "validation_warning_count": report["warning_count"],
        }

    def service_coverage(self) -> dict[str, Any]:
        mapped = DEFAULT_MAPPING_REGISTRY.mapped_paths()
        results: dict[str, Any] = {}
        for name in DEFAULT_REGISTRY.list_service_contracts():
            contract = DEFAULT_REGISTRY.get_service_contract(name)
            paths = sorted(set(_collect_paths(contract)))
            if not paths:
                continue
            missing = [p for p in paths if p not in mapped]
            results[name] = {
                "explicit_ontology_paths": len(paths),
                "mapped_paths": len(paths) - len(missing),
                "coverage_percent": round(100 * (len(paths)-len(missing))/len(paths), 2),
                "missing_paths": missing,
            }
        # Contracts that expose current field names rather than ontology paths.
        by_column: dict[str, list[dict[str, Any]]] = {}
        for dataset in DEFAULT_MAPPING_REGISTRY.load()["datasets"]:
            for item in dataset["columns"]:
                by_column.setdefault(item["source_column"], []).append(item)

        scenario = DEFAULT_REGISTRY.get_service_contract("scenario")
        scenario_fields = scenario.get("important_current_fields", [])
        scenario_missing = [f for f in scenario_fields if not _field_semantically_available(by_column.get(f, []))]
        results["scenario"] = {
            "contract_fields": len(scenario_fields),
            "covered_fields": len(scenario_fields) - len(scenario_missing),
            "coverage_percent": round(100 * (len(scenario_fields)-len(scenario_missing))/len(scenario_fields), 2) if scenario_fields else 100.0,
            "missing_fields": scenario_missing,
            "coverage_basis": "important_current_fields from Step-2 scenario contract",
        }

        headcount = DEFAULT_REGISTRY.get_service_contract("headcount")
        headcount_fields: set[str] = set()
        for metric in headcount.get("metrics", {}).values():
            source_column = metric.get("source_column")
            if source_column:
                headcount_fields.add(source_column)
            for filter_item in metric.get("filters", []):
                if filter_item:
                    headcount_fields.add(filter_item[0])
        headcount_missing = [f for f in sorted(headcount_fields) if not _field_semantically_available(by_column.get(f, []))]
        results["headcount"] = {
            "metric_source_or_filter_fields": len(headcount_fields),
            "covered_fields": len(headcount_fields) - len(headcount_missing),
            "coverage_percent": round(100 * (len(headcount_fields)-len(headcount_missing))/len(headcount_fields), 2) if headcount_fields else 100.0,
            "missing_fields": headcount_missing,
            "coverage_basis": "source_column + filter fields from all 61 metric definitions; graph may join facts across entities instead of reproducing current table-local layout",
        }

        # Decision-case mapping is rule/config driven. Step 3 verifies that every
        # supplied column is classified and the core case properties/relations resolve.
        decision_file = DEFAULT_MAPPING_REGISTRY.dataset("HR_Decision_Cases.csv")
        unresolved = [c["source_column"] for c in decision_file["columns"] if c["disposition"] in {"explicitly_unmodeled_nonblocking", "context_not_scalar"}]
        results["decision_cases"] = {
            "source_columns": len(decision_file["columns"]),
            "classified_columns": len(decision_file["columns"]),
            "core_unmodeled_columns": unresolved,
            "coverage_basis": "current case store properties + explicit relationship rules; lifecycle/audit timestamps may remain store metadata",
        }
        return results

    def supabase_summary(self) -> dict[str, Any]:
        report = validate_supabase_mapping()
        payload = json.loads((PROJECT_ROOT / "backend" / "mapping" / "definitions" / "supabase_schema_mappings.json").read_text(encoding="utf-8"))
        sql_only = [t["table"] for t in payload["tables"] if t["source_basis"] == "bundled_sql_only"]
        mapped_csv = [t for t in payload["tables"] if t["source_basis"] == "matching_current_csv"]
        return {
            "schema_source": payload["schema_source"],
            "table_count": report["table_count"],
            "column_count": report["column_count"],
            "matching_current_csv_table_count": len(mapped_csv),
            "sql_only_table_count": len(sql_only),
            "sql_only_tables": sql_only,
            "validation_error_count": report["error_count"],
            "physical_type_note": payload["physical_type_note"],
        }

    def schema_profile(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in profile_data_directory(self.data_dir)]


def _collect_paths(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "ontology_path" and isinstance(child, str):
                yield child
            elif key == "ontology_identity_paths" and isinstance(child, list):
                for item in child:
                    if isinstance(item, str):
                        yield item
            elif key == "additional_ontology_paths" and isinstance(child, list):
                for item in child:
                    if isinstance(item, str):
                        yield item
            else:
                yield from _collect_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_paths(child)


CURRENT_MAPPING_SERVICE = CurrentMappingService()


def _field_semantically_available(items: list[dict[str, Any]]) -> bool:
    accepted = {
        "direct_property", "context_property", "relationship_reference",
        "derived_aggregate", "scenario_assumption_value",
        "scenario_assumption_metadata", "analytical_or_derived_output",
        "service_configuration", "training_or_reference_label",
        "descriptive_or_relationship_metadata", "denormalized_label",
        "archival_snapshot", "operational_metadata", "unused_source_fact",
    }
    return any(item.get("disposition") in accepted for item in items)
