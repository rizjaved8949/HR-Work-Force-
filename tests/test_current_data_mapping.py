from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from mapping.registry import DEFAULT_MAPPING_REGISTRY
from mapping.service import CURRENT_MAPPING_SERVICE
from ontology.registry import DEFAULT_REGISTRY


def test_all_current_csv_columns_are_explicitly_classified() -> None:
    summary = CURRENT_MAPPING_SERVICE.summary()
    assert summary["source_dataset_count"] == 58
    assert summary["source_column_count"] == 975
    assert summary["validation_error_count"] == 0
    assert summary["validation_warning_count"] == 0


def test_mapping_validation_is_clean() -> None:
    report = CURRENT_MAPPING_SERVICE.validation_report()
    assert report["valid"] is True
    assert report["issues"] == []


def test_confirmed_service_contracts_are_fully_covered() -> None:
    coverage = CURRENT_MAPPING_SERVICE.service_coverage()
    for name in ["attrition", "performance", "successor", "employee_record", "people_at_risk"]:
        assert coverage[name]["coverage_percent"] == 100.0, (name, coverage[name])
    assert coverage["scenario"]["coverage_percent"] == 100.0
    assert coverage["headcount"]["coverage_percent"] == 100.0


def test_attrition_exact_14_semantic_inputs_are_available() -> None:
    contract = DEFAULT_REGISTRY.get_service_contract("attrition")
    mapped = DEFAULT_MAPPING_REGISTRY.mapped_paths()
    paths = [item["ontology_path"] for item in contract["features"]]
    assert len(paths) == 14
    assert all(path in mapped for path in paths)


def test_step3_confirmed_ontology_refinements_exist() -> None:
    assert DEFAULT_REGISTRY.ontology_path_exists("Employment.roleBand")
    assert DEFAULT_REGISTRY.ontology_path_exists("PerformanceEvidence.operationalTargetValue")
    assert DEFAULT_REGISTRY.ontology_path_exists("PerformanceEvidence.operationalActualValue")
    assert DEFAULT_REGISTRY.ontology_path_exists("PerformanceEvidence.operationalUnit")
    assert DEFAULT_REGISTRY.ontology_path_exists("ScenarioAssumption.assumptionStatus")


def test_relationship_rules_resolve_to_real_ontology_edges() -> None:
    ontology = DEFAULT_REGISTRY.load()
    actual = {(r.source, r.relation, r.target) for r in ontology.relationships}
    for rule in DEFAULT_MAPPING_REGISTRY.relationships()["rules"]:
        assert (rule["source_entity"], rule["relation"], rule["target_entity"]) in actual, rule


def test_mapping_does_not_guess_unknown_columns_into_properties() -> None:
    # These source facts exist but are not used by the saved 14-feature attrition model.
    dataset = DEFAULT_MAPPING_REGISTRY.dataset("Final_Attrition_Dataset_200_Employees.csv")
    by_name = {item["source_column"]: item for item in dataset["columns"]}
    assert by_name["Commute_Minutes_One_Way"]["disposition"] == "unused_source_fact"
    assert by_name["Manager_Changed_Last_6M"]["disposition"] == "unused_source_fact"


def test_bundled_supabase_schema_mapping_is_structurally_valid() -> None:
    summary = CURRENT_MAPPING_SERVICE.supabase_summary()
    assert summary["table_count"] == 54
    assert summary["validation_error_count"] == 0
    assert summary["matching_current_csv_table_count"] == 49
