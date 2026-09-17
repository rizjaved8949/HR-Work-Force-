from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontology_studio.models import (
    ChangeRequestCreate,
    ChangeRequestDecision,
    MappingReviewCreate,
    MappingReviewDecision,
)
from ontology_studio.router import create_ontology_studio_router
from ontology_studio.service import OntologyStudioService
from ontology_studio.store import StudioReviewStore


class FakeGraphRepository:
    def verify_connectivity(self):
        return None

    def count_nodes(self, tenant_id=None):
        return 41291 if tenant_id == "ORGANIZATION-001" else 0

    def count_relationships(self, tenant_id=None):
        return 62631 if tenant_id == "ORGANIZATION-001" else 0

    def close(self):
        return None


def make_service(tmp_path: Path) -> OntologyStudioService:
    return OntologyStudioService(
        store=StudioReviewStore(tmp_path / "reviews.json"),
        graph_repository_factory=FakeGraphRepository,
    )


def test_step10_dashboard_exposes_ontology_mapping_graph_and_safe_governance(tmp_path):
    service = make_service(tmp_path)
    payload = service.dashboard("ORGANIZATION-001")

    assert payload["step"] == 10
    assert payload["ontology"]["entity_count"] == 39
    assert payload["ontology"]["relationship_count"] == 65
    assert payload["graph"]["available"] is True
    assert payload["graph"]["node_count"] == 41291
    assert payload["graph"]["relationship_count"] == 62631
    assert payload["safety"]["active_ontology_mutation_enabled"] is False
    assert payload["safety"]["active_mapping_mutation_enabled"] is False


def test_schema_graph_is_visualization_ready_and_matches_ontology(tmp_path):
    payload = make_service(tmp_path).schema_graph()
    assert payload["node_count"] == 39
    assert payload["edge_count"] == 65
    assert {node["id"] for node in payload["nodes"]} >= {"Employee", "Department", "PerformanceRecord"}
    assert any(edge["source"] == "Employee" for edge in payload["edges"])


def test_entity_catalog_contains_properties_relationship_and_mapping_counts(tmp_path):
    items = make_service(tmp_path).entity_catalog()
    employee = next(item for item in items if item["name"] == "Employee")
    assert employee["properties"]
    assert employee["relationship_count"] > 0
    assert employee["mapped_source_column_count"] > 0


def test_source_mapping_catalog_and_detail_are_current_step3_truth(tmp_path):
    service = make_service(tmp_path)
    catalog = service.dataset_catalog()
    assert len(catalog) >= 50
    assert any(item["source_file"] == "Business_Unit_Master.csv" for item in catalog)

    detail = service.dataset_mapping("Business_Unit_Master.csv")
    by_name = {item["source_column"]: item for item in detail["columns"]}
    assert by_name["Business_Unit_ID"]["ontology_path"] == "BusinessUnit.businessUnitId"
    assert by_name["Business_Unit_Leader_Position_ID"]["disposition"] == "relationship_reference"


def test_attention_queue_preserves_pending_semantics_without_guessing(tmp_path):
    payload = make_service(tmp_path).attention_queue()
    concepts = {item["concept"] for item in payload["known_semantic_open_items"]}
    assert "PerformanceRecord.performanceTrend6M" in concepts
    assert payload["mapping_attention"]


def test_mapping_review_can_be_approved_but_never_mutates_active_mapping(tmp_path):
    service = make_service(tmp_path)
    mapping_file = service.mapping_registry.mapping_file
    before = mapping_file.read_text(encoding="utf-8")

    review = service.create_mapping_review(
        MappingReviewCreate(
            source_file="Business_Unit_Master.csv",
            source_column="Business_Unit_Name",
            proposed_ontology_path="BusinessUnit.name",
            proposed_disposition="direct_property",
            reason="Confirm the already-grounded business-unit name mapping.",
        )
    )
    approved = service.decide_mapping_review(
        review["id"],
        MappingReviewDecision(decision="approved", reviewer="test-admin"),
    )

    after = mapping_file.read_text(encoding="utf-8")
    assert approved["status"] == "approved"
    assert approved["applied_to_active_mapping"] is False
    assert before == after


def test_mapping_review_rejects_unknown_ontology_path(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(ValueError, match="Unknown ontology property"):
        service.create_mapping_review(
            MappingReviewCreate(
                source_file="Business_Unit_Master.csv",
                source_column="Business_Unit_Name",
                proposed_ontology_path="FakeEntity.fakeProperty",
                reason="This deliberately invalid path must be rejected.",
            )
        )


def test_change_request_approval_is_staged_and_does_not_edit_active_ontology(tmp_path):
    service = make_service(tmp_path)
    ontology_file = service.ontology_registry.ontology_file
    before = ontology_file.read_text(encoding="utf-8")

    request = service.create_change_request(
        ChangeRequestCreate(
            kind="property",
            target="PerformanceRecord.performanceTrend6M",
            title="Confirm trend semantics",
            description="Stage a future semantic definition after source-scale confirmation.",
        )
    )
    approved = service.decide_change_request(
        request["id"],
        ChangeRequestDecision(decision="approved", reviewer="test-admin"),
    )

    assert approved["status"] == "approved"
    assert approved["applied_to_active_ontology"] is False
    assert ontology_file.read_text(encoding="utf-8") == before


def test_governance_snapshot_binds_active_versions_to_reviews(tmp_path):
    payload = make_service(tmp_path).export_governance_snapshot()
    assert payload["step"] == 10
    assert payload["ontology"]["version"] == "1.0.2-draft"
    assert payload["mapping"]["ontology_version"] == "1.0.2-draft"
    assert payload["apply_policy"] == "review_only_no_silent_active_file_mutation"


def test_step10_router_serves_reference_ui_and_management_api(tmp_path):
    app = FastAPI()
    app.include_router(create_ontology_studio_router(make_service(tmp_path)))
    client = TestClient(app)

    assert client.get("/ontology-studio").status_code == 200
    graph = client.get("/ontology-studio/api/schema-graph")
    assert graph.status_code == 200
    assert graph.json()["node_count"] == 39

    created = client.post(
        "/ontology-studio/api/mapping-reviews",
        json={
            "source_file": "Business_Unit_Master.csv",
            "source_column": "Business_Unit_Name",
            "proposed_ontology_path": "BusinessUnit.name",
            "reason": "UI review test",
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
