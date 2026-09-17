from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from ontology.registry import DEFAULT_REGISTRY
from ontology.service import ONTOLOGY_SERVICE
from ontology.validator import validate_registry


EXPECTED_ATTRITION_FEATURES = [
    "Tenure_Months",
    "Monthly_Salary_PKR",
    "Salary_vs_Market_pct",
    "Last_Increment_pct",
    "Months_Since_Last_Promotion",
    "KPI_Achievement_pct",
    "Performance_Trend_6M",
    "Overtime_Hours_Last_30D",
    "Engagement_Score",
    "Job_Satisfaction_Score",
    "Work_Life_Balance_Score",
    "Manager_Relationship_Score",
    "Career_Growth_Score",
    "Pay_Concern_Raised_Last_6M",
]


def test_ontology_v1_has_no_structural_errors() -> None:
    issues = validate_registry(DEFAULT_REGISTRY)
    errors = [issue for issue in issues if issue.severity == "error"]
    assert errors == []


def test_ontology_is_explicitly_non_breaking_step2_metadata() -> None:
    summary = ONTOLOGY_SERVICE.summary()
    assert summary["compatibility_mode"] == "non_breaking_read_only_metadata"
    assert summary["validation_error_count"] == 0


def test_attrition_contract_preserves_exact_14_model_features() -> None:
    contract = DEFAULT_REGISTRY.get_service_contract("attrition")
    actual = [item["current_feature"] for item in contract["features"]]
    assert actual == EXPECTED_ATTRITION_FEATURES
    assert contract["categorical_feature_indices"] == [13]
    assert contract["blocking_on_missing"] is False


def test_performance_trend_6m_is_not_falsely_frozen() -> None:
    item = DEFAULT_REGISTRY.get_property("PerformanceRecord.performanceTrend6M")
    assert item.semantic_status == "pending_confirmation"


def test_headcount_contract_preserves_current_registry_counts() -> None:
    contract = DEFAULT_REGISTRY.get_service_contract("headcount")
    assert contract["metric_count"] == 61
    assert contract["dimension_count"] == 25


def test_service_contract_ontology_paths_are_resolvable() -> None:
    for contract_name in DEFAULT_REGISTRY.list_service_contracts():
        contract = DEFAULT_REGISTRY.get_service_contract(contract_name)
        for path in _collect_paths(contract):
            assert DEFAULT_REGISTRY.ontology_path_exists(path), (
                contract_name,
                path,
            )


def _collect_paths(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "ontology_path" and isinstance(child, str):
                yield child
            else:
                yield from _collect_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_paths(child)
