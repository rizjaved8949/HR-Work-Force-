from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.mapper import DEFAULT_MAPPING_SUGGESTER
from ingestion.models import (
    EntityIngestionRule,
    MappingPlan,
    PropertyMapping,
    RelationshipMapping,
)
from ingestion.profiler import profile_source
from ingestion.registry import MappingPlanRegistry
from ingestion.service import DataIngestionService
from ingestion.sources import RecordsSource
from ingestion.transformers import transform_value
from ontology.registry import DEFAULT_REGISTRY


def _source(rows=None):
    return RecordsSource(
        rows
        or [
            {
                "staff_id": "E001",
                "full_name": "Ali",
                "monthly_pay": "150000",
                "pay_currency": "PKR",
                "effective_date": "2026-09-01",
            },
            {
                "staff_id": "E002",
                "full_name": "Sara",
                "monthly_pay": "170000",
                "pay_currency": "PKR",
                "effective_date": "2026-09-01",
            },
        ],
        source_system="partner_hrms",
        source_object="workers",
    )


def _draft_plan() -> MappingPlan:
    return MappingPlan(
        plan_id="partner-workers-v1",
        version="1.0.0",
        tenant_id="ORG-001",
        source_system="partner_hrms",
        source_object="workers",
        source_format="records",
        ontology_version=DEFAULT_REGISTRY.load().version,
        property_mappings=[
            PropertyMapping(source_column="staff_id", ontology_path="Employee.employeeId"),
            PropertyMapping(source_column="full_name", ontology_path="Employee.name"),
            PropertyMapping(source_column="monthly_pay", ontology_path="CompensationRecord.monthlyAmount"),
            PropertyMapping(source_column="pay_currency", ontology_path="CompensationRecord.currency"),
        ],
        entity_rules=[
            EntityIngestionRule(
                entity_type="CompensationRecord",
                record_key_columns=["staff_id", "effective_date"],
                valid_from_column="effective_date",
            )
        ],
        relationship_mappings=[
            RelationshipMapping(
                relation_type="HAS_COMPENSATION",
                source_entity_type="Employee",
                target_entity_type="CompensationRecord",
                target_mode="same_row_entity",
            )
        ],
    )


def test_profile_source_infers_basic_types():
    profile = profile_source(_source())
    by_name = {item.name: item for item in profile.columns}
    assert profile.row_count == 2
    assert by_name["monthly_pay"].observed_type == "integer"
    assert by_name["effective_date"].observed_type == "date_like"


def test_mapping_suggestions_never_auto_approve_even_exact_alias():
    proposal = DEFAULT_MAPPING_SUGGESTER.propose_column("Employee_ID", "string")
    assert proposal.recommended_ontology_path == "Employee.employeeId"
    assert proposal.recommendation_confidence >= 0.98
    assert proposal.review_required is True


def test_unknown_schema_column_is_only_suggested_not_declared_truth():
    proposal = DEFAULT_MAPPING_SUGGESTER.propose_column("basic_pay", "decimal")
    assert proposal.review_required is True
    # A fuzzy recommendation may or may not exist; Step 6 never turns it into an approved mapping.
    assert all(item.confidence <= 1.0 for item in proposal.candidates)


def test_plan_must_be_approved_before_canonicalization():
    service = DataIngestionService()
    batch = service.canonicalize(_source(), _draft_plan())
    assert batch.error_count >= 1
    assert any(item.code == "mapping_plan_not_approved" for item in batch.issues)
    assert batch.entities == []


def test_approved_plan_produces_canonical_entities_and_relationships():
    service = DataIngestionService()
    plan = service.approve_plan(_draft_plan(), approved_by="test-admin")
    batch = service.canonicalize(_source(), plan)
    assert batch.error_count == 0
    assert len(batch.entities) == 4
    assert len(batch.relationships) == 2
    employees = [item for item in batch.entities if item.entity_type == "Employee"]
    compensation = [item for item in batch.entities if item.entity_type == "CompensationRecord"]
    assert employees[0].properties["employeeId"] == "E001"
    assert compensation[0].properties["monthlyAmount"] == 150000.0
    assert compensation[0].valid_from is not None
    assert batch.relationships[0].relation_type == "HAS_COMPENSATION"


def test_source_record_entities_require_explicit_record_keys():
    plan = _draft_plan().model_copy(update={"entity_rules": []})
    report = DataIngestionService().validate_plan(plan, _source())
    assert report["valid"] is False
    assert any(item["code"] == "source_record_key_rule_missing" for item in report["issues"])


def test_pending_semantic_property_requires_explicit_override():
    plan = MappingPlan(
        plan_id="trend-v1",
        version="1",
        tenant_id="ORG-001",
        source_system="partner_hrms",
        source_object="performance",
        source_format="records",
        ontology_version=DEFAULT_REGISTRY.load().version,
        property_mappings=[
            PropertyMapping(source_column="trend", ontology_path="PerformanceRecord.performanceTrend6M")
        ],
        entity_rules=[
            EntityIngestionRule(
                entity_type="PerformanceRecord",
                record_key_columns=["staff_id", "period"],
            )
        ],
    )
    report = DataIngestionService().validate_plan(plan)
    assert report["valid"] is False
    assert any(item["code"] == "pending_semantic_requires_override" for item in report["issues"])


def test_explicit_numeric_unit_conversion_is_supported_and_not_automatic():
    prop = DEFAULT_REGISTRY.get_property("CompensationRecord.monthlyAmount")
    mapping = PropertyMapping(
        source_column="annual_pay",
        ontology_path="CompensationRecord.monthlyAmount",
        numeric_divisor=12,
    )
    assert transform_value("1200000", prop, mapping) == 100000.0


def test_ambiguous_date_rejected_without_explicit_source_format():
    prop = DEFAULT_REGISTRY.get_property("Employment.hireDate")
    mapping = PropertyMapping(source_column="hire", ontology_path="Employment.hireDate")
    with pytest.raises(ValueError):
        transform_value("01/02/2026", prop, mapping)
    explicit = mapping.model_copy(update={"date_format": "%d/%m/%Y"})
    assert str(transform_value("01/02/2026", prop, explicit)) == "2026-02-01"


def test_service_coverage_reports_availability_not_feature_resolution():
    report = DataIngestionService().coverage(_draft_plan())
    attrition = report["services"]["attrition"]
    assert attrition["required_path_count"] == 14
    assert 0 < attrition["covered_path_count"] < 14
    assert "CompensationRecord.monthlyAmount" in attrition["covered_paths"]


def test_mapping_plan_registry_round_trip(tmp_path: Path):
    registry = MappingPlanRegistry(tmp_path)
    service = DataIngestionService(plan_registry=registry)
    plan = service.approve_plan(_draft_plan(), approved_by="admin")
    path = service.save_plan(plan)
    assert path.is_file()
    loaded = registry.load(plan.plan_id)
    assert loaded.status == "approved"
    assert loaded.approved_by == "admin"


def test_dry_run_has_no_graph_write_side_effect():
    service = DataIngestionService()
    plan = service.approve_plan(_draft_plan(), approved_by="admin")
    report = service.dry_run(_source(), plan)
    assert report["mode"] == "canonical_dry_run_no_graph_write"
    assert report["batch_summary"]["entity_count"] == 4
    assert report["batch_summary"]["relationship_count"] == 2


def test_mapping_plan_is_bound_to_exact_source_object_and_format():
    service = DataIngestionService()
    plan = service.approve_plan(_draft_plan(), approved_by="admin")
    wrong = RecordsSource(
        [{"staff_id": "E001"}],
        source_system="partner_hrms",
        source_object="different_table",
        source_format="records",
    )
    with pytest.raises(ValueError):
        service.canonicalize(wrong, plan)
