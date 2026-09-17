from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from graph.ids import make_node_graph_id
from graph.memory_repository import InMemoryGraphRepository
from graph.models import GraphNode
from ingestion.models import PropertyMapping
from multi_org.access import OrganizationAccessService
from multi_org.context import reset_current_tenant, set_current_tenant, tenant_resolver
from multi_org.middleware import MultiOrganizationTenantMiddleware
from multi_org.models import (
    ActorContext,
    CreateOrganizationRequest,
    DatasetStatus,
    MappingPlanDraftRequest,
    OrganizationMember,
    OrganizationRecord,
    OrganizationStatus,
    RegisterRecordsDatasetRequest,
)
from multi_org.plan_store import TenantMappingPlanStore
from multi_org.registry import OrganizationRegistry
from multi_org.router import create_multi_org_router
from multi_org.service import MultiOrganizationOnboardingService
from multi_org.source_store import OrganizationSourceStore
from semantic.service import SemanticHRService
from service_refactor.employee import GraphEmployeeRecordService


ROOT = Path(__file__).resolve().parents[1]


def local_actor() -> ActorContext:
    return ActorContext(
        authenticated=False,
        user_id="local-dev",
        role="local_dev",
        local_development=True,
    )


def build_service(tmp_path: Path, monkeypatch) -> MultiOrganizationOnboardingService:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    return MultiOrganizationOnboardingService(
        repository=InMemoryGraphRepository(),
        registry=OrganizationRegistry(tmp_path / "organizations.json"),
        source_store=OrganizationSourceStore(tmp_path / "sources"),
        plan_store=TenantMappingPlanStore(tmp_path / "plans"),
        access=OrganizationAccessService(),
    )


def create_org(service, tenant_id="ORG-ACME", name="Acme Ltd"):
    return service.create_organization(
        CreateOrganizationRequest(tenant_id=tenant_id, name=name),
        actor=local_actor(),
    )


def register_employee_dataset(service, tenant_id: str, *, employee_name="Ali"):
    dataset = service.register_records_dataset(
        tenant_id,
        RegisterRecordsDatasetRequest(
            source_system="partner_hr",
            source_object="workers",
            source_format="records",
            rows=[{"emp_code": "E-1", "full_name": employee_name}],
        ),
        actor=local_actor(),
    )
    service.profile_dataset(tenant_id, dataset.dataset_id, actor=local_actor())
    plan = service.create_mapping_plan(
        tenant_id,
        dataset.dataset_id,
        MappingPlanDraftRequest(
            property_mappings=[
                PropertyMapping(
                    source_column="emp_code",
                    ontology_path="Employee.employeeId",
                ),
                PropertyMapping(
                    source_column="full_name",
                    ontology_path="Employee.name",
                ),
            ]
        ),
        actor=local_actor(),
    )
    approved = service.approve_mapping_plan(
        tenant_id, dataset.dataset_id, actor=local_actor()
    )
    return dataset, plan, approved


def test_step12_bootstraps_existing_step9_tenant_without_breaking_current_org(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    org = service.ensure_default_organization(
        tenant_id="ORGANIZATION-001",
        name="Current Organization",
    )
    assert org.tenant_id == "ORGANIZATION-001"
    assert org.status == OrganizationStatus.ACTIVE
    assert org.is_default is True
    assert org.legacy_default_access is True
    # Re-running bootstrap is idempotent.
    assert service.ensure_default_organization(
        tenant_id="ORGANIZATION-001", name="Changed Name"
    ).name == "Current Organization"


def test_step12_create_org_assigns_creator_owner_and_rejects_duplicate(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    org = create_org(service)
    assert org.status == OrganizationStatus.DRAFT
    assert org.members[0].user_id == "local-dev"
    assert org.members[0].role == "owner"
    with pytest.raises(ValueError):
        create_org(service)


def test_step12_membership_access_is_tenant_scoped_when_auth_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    access = OrganizationAccessService()
    org_a = OrganizationRecord(
        tenant_id="ORG-A",
        name="A",
        members=[OrganizationMember(user_id="u-a", role="analyst")],
    )
    org_b = OrganizationRecord(
        tenant_id="ORG-B",
        name="B",
        members=[OrganizationMember(user_id="u-b", role="analyst")],
    )
    actor_a = access.actor(SimpleNamespace(id="u-a", role="analyst"))
    assert access.can_access(org_a, actor_a) is True
    assert access.can_access(org_b, actor_a) is False
    assert access.can_administer(org_a, actor_a) is False


def test_step12_profile_and_mapping_suggestions_never_auto_approve(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    create_org(service)
    dataset = service.register_records_dataset(
        "ORG-ACME",
        RegisterRecordsDatasetRequest(
            source_system="partner_hr",
            source_object="workers",
            rows=[{"employeeId": "E-1", "name": "Ali"}],
        ),
        actor=local_actor(),
    )
    profile = service.profile_dataset("ORG-ACME", dataset.dataset_id, actor=local_actor())
    assert profile["row_count"] == 1
    assert {item["name"] for item in profile["columns"]} == {"employeeId", "name"}
    suggestions = service.suggest_mappings("ORG-ACME", dataset.dataset_id, actor=local_actor())
    assert suggestions["review_required"] is True
    assert suggestions["column_proposals"]
    assert all(item["review_required"] is True for item in suggestions["column_proposals"])
    refreshed = service.registry.dataset("ORG-ACME", dataset.dataset_id)
    assert refreshed.mapping_plan_id is None
    assert refreshed.status == DatasetStatus.PROFILED


def test_step12_mapping_plan_is_bound_to_exact_tenant_source_and_separate_approval(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    create_org(service)
    dataset, draft, approved = register_employee_dataset(service, "ORG-ACME")
    assert draft.tenant_id == "ORG-ACME"
    assert draft.source_object == "workers"
    assert draft.status == "draft"
    assert approved.status == "approved"
    assert approved.approved_by == "local-dev"
    validation = service.validate_mapping_plan("ORG-ACME", dataset.dataset_id, actor=local_actor())
    assert validation["valid"] is True
    assert validation["error_count"] == 0
    stored = service.plan_store.load("ORG-ACME", approved.plan_id)
    assert stored.tenant_id == "ORG-ACME"
    with pytest.raises(ValueError):
        service.plan_store.save("ORG-OTHER", stored)


def test_step12_dry_run_has_no_graph_write_side_effect(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    create_org(service)
    dataset, _, _ = register_employee_dataset(service, "ORG-ACME")
    before = service.repository.count_nodes("ORG-ACME")
    result = service.dry_run_dataset("ORG-ACME", dataset.dataset_id, actor=local_actor())
    assert result["mode"] == "organization_dataset_dry_run_no_graph_write"
    assert result["batch_summary"]["entity_count"] == 1
    assert result["batch_summary"]["error_count"] == 0
    assert service.repository.count_nodes("ORG-ACME") == before == 0


def test_step12_same_business_id_in_two_orgs_produces_different_graph_ids(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    create_org(service, "ORG-A", "Alpha")
    create_org(service, "ORG-B", "Beta")
    register_employee_dataset(service, "ORG-A", employee_name="Alice")
    register_employee_dataset(service, "ORG-B", employee_name="Bob")
    report_a = service.load_organization("ORG-A", actor=local_actor())
    report_b = service.load_organization("ORG-B", actor=local_actor())
    assert report_a.error_count == report_b.error_count == 0
    employee_a = service.repository.find_nodes(
        tenant_id="ORG-A", entity_type="Employee", property_filters={"employeeId": "E-1"}
    )[0]
    employee_b = service.repository.find_nodes(
        tenant_id="ORG-B", entity_type="Employee", property_filters={"employeeId": "E-1"}
    )[0]
    assert employee_a.graph_id != employee_b.graph_id
    assert service.repository.get_node(employee_a.graph_id, "ORG-B") is None
    assert service.repository.get_node(employee_b.graph_id, "ORG-A") is None


def test_step12_graph_load_is_two_pass_tenant_scoped_and_idempotent(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    create_org(service)
    dataset, _, _ = register_employee_dataset(service, "ORG-ACME")
    first = service.load_organization("ORG-ACME", actor=local_actor())
    assert first.error_count == 0
    assert first.graph_node_count_after == 2  # Organization root + Employee
    assert service.registry.dataset("ORG-ACME", dataset.dataset_id).status == DatasetStatus.LOADED
    second = service.load_organization("ORG-ACME", actor=local_actor())
    assert second.error_count == 0
    assert second.graph_node_count_before == second.graph_node_count_after == 2
    assert service.repository.count_nodes("ORG-ACME") == 2
    assert service.repository.count_nodes("OTHER") == 0


def test_step12_activation_is_blocked_until_mapped_data_is_loaded(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    create_org(service)
    dataset = service.register_records_dataset(
        "ORG-ACME",
        RegisterRecordsDatasetRequest(
            source_system="partner_hr",
            source_object="workers",
            rows=[{"emp_code": "E-1", "full_name": "Ali"}],
        ),
        actor=local_actor(),
    )
    readiness = service.readiness("ORG-ACME", actor=local_actor())
    assert readiness.ready_to_activate is False
    with pytest.raises(ValueError):
        service.activate("ORG-ACME", actor=local_actor())
    service.profile_dataset("ORG-ACME", dataset.dataset_id, actor=local_actor())
    service.create_mapping_plan(
        "ORG-ACME",
        dataset.dataset_id,
        MappingPlanDraftRequest(
            property_mappings=[
                PropertyMapping(source_column="emp_code", ontology_path="Employee.employeeId"),
                PropertyMapping(source_column="full_name", ontology_path="Employee.name"),
            ]
        ),
        actor=local_actor(),
    )
    service.approve_mapping_plan("ORG-ACME", dataset.dataset_id, actor=local_actor())
    service.load_organization("ORG-ACME", actor=local_actor())
    readiness = service.readiness("ORG-ACME", actor=local_actor())
    assert readiness.ready_to_activate is True
    assert service.activate("ORG-ACME", actor=local_actor()).status == OrganizationStatus.ACTIVE


def test_step12_middleware_sets_tenant_context_and_blocks_unsafe_hybrid_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    registry = OrganizationRegistry(tmp_path / "organizations.json")
    registry.create(
        OrganizationRecord(
            tenant_id="ORGANIZATION-001",
            name="Default",
            status=OrganizationStatus.ACTIVE,
            is_default=True,
            legacy_default_access=True,
        )
    )
    registry.create(
        OrganizationRecord(
            tenant_id="ORG-B",
            name="Beta",
            status=OrganizationStatus.ACTIVE,
        )
    )
    app = FastAPI()

    @app.get("/tools/employee-search")
    def safe(request: Request):
        return {"tenant_id": request.state.tenant_id}

    @app.get("/pipeline/headcount")
    def unsafe():
        return {"should_not": "run"}

    app.add_middleware(
        MultiOrganizationTenantMiddleware,
        registry=registry,
        access=OrganizationAccessService(),
        default_tenant_id="ORGANIZATION-001",
    )
    client = TestClient(app)
    response = client.get("/tools/employee-search", headers={"X-Organization-ID": "ORG-B"})
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "ORG-B"
    blocked = client.get("/pipeline/headcount", headers={"X-Organization-ID": "ORG-B"})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "service_not_multi_tenant_safe"


def test_step12_graph_employee_adapter_uses_request_scoped_tenant_not_fixed_default(tmp_path, monkeypatch):
    repo = InMemoryGraphRepository()
    for tenant_id, name in (("ORG-A", "Alice"), ("ORG-B", "Bob")):
        repo.upsert_node(
            GraphNode(
                graph_id=make_node_graph_id(
                    tenant_id=tenant_id,
                    entity_type="Employee",
                    identity_key="E-1",
                ),
                tenant_id=tenant_id,
                entity_type="Employee",
                ontology_version="1.0.2-draft",
                properties={"employeeId": "E-1", "name": name},
            )
        )
    semantic = SemanticHRService(repo)
    service = GraphEmployeeRecordService(
        semantic,
        tenant_id=tenant_resolver("ORG-A"),
    )
    assert service.get_by_employee_id("E-1")["employee"]["employee_name"] == "Alice"
    token = set_current_tenant("ORG-B")
    try:
        assert service.get_by_employee_id("E-1")["employee"]["employee_name"] == "Bob"
    finally:
        reset_current_tenant(token)


def test_step12_router_exposes_onboarding_control_plane_without_secrets(tmp_path, monkeypatch):
    service = build_service(tmp_path, monkeypatch)
    service.ensure_default_organization(tenant_id="ORGANIZATION-001", name="Default")
    app = FastAPI()
    app.include_router(create_multi_org_router(service))
    client = TestClient(app)
    assert client.get("/organization-onboarding").status_code == 200
    bootstrap = client.get("/organization-onboarding/api/bootstrap")
    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert payload["step"] == 12
    assert payload["tenant_header"] == "X-Organization-ID"
    text = bootstrap.text.lower()
    assert "neo4j_password" not in text
    assert "supabase_secret_key" not in text
    create = client.post(
        "/organization-onboarding/api/organizations",
        json={"tenant_id": "ORG-ROUTER", "name": "Router Org"},
    )
    assert create.status_code == 201
    summary = client.get("/organization-onboarding/api/organizations/ORG-ROUTER")
    assert summary.status_code == 200
    assert summary.json()["tenant_isolation"]["cross_tenant_relationships_forbidden"] is True
