from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph.memory_repository import InMemoryGraphRepository
from multi_org.access import OrganizationAccessService
from multi_org.plan_store import TenantMappingPlanStore
from multi_org.registry import OrganizationRegistry
from multi_org.router import create_multi_org_router
from multi_org.service import MultiOrganizationOnboardingService
from multi_org.source_store import OrganizationSourceStore


class FakeRawSupabaseStore:
    datasets_table = "org_ingestion_datasets"
    rows_table = "org_ingestion_rows"

    def __init__(self) -> None:
        self.snapshots: list[dict] = []
        self.status_updates: list[dict] = []

    def verify_schema(self) -> None:
        return None

    def replace_dataset_rows(self, **kwargs) -> None:
        self.snapshots.append(kwargs)

    def update_status(self, **kwargs) -> None:
        self.status_updates.append(kwargs)


def build_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    raw_store = FakeRawSupabaseStore()
    repository = InMemoryGraphRepository()
    service = MultiOrganizationOnboardingService(
        repository=repository,
        registry=OrganizationRegistry(tmp_path / "organizations.json"),
        source_store=OrganizationSourceStore(tmp_path / "sources"),
        plan_store=TenantMappingPlanStore(tmp_path / "plans"),
        access=OrganizationAccessService(),
        ingestion_store=raw_store,
    )
    app = FastAPI()
    app.include_router(create_multi_org_router(service))
    return TestClient(app), service, raw_store, repository


def create_org(client: TestClient):
    response = client.post(
        "/organization-onboarding/api/organizations",
        json={
            "tenant_id": "NEXACORE-HR-001",
            "name": "NexaCore Technologies Pvt Ltd",
            "country": "Pakistan",
            "currency": "PKR",
        },
    )
    assert response.status_code == 201, response.text


def sample_csv() -> bytes:
    return (
        "org_code,company_name,staff_no,worker_name,business_unit,division,team,"
        "position_code,designation,supervisor_staff_no,joined_on,data_as_of,emp_status,"
        "currency,monthly_income_pkr,kpi_score_pct,overtime_last_30d,engagement_rating,"
        "primary_skill,skill_proficiency,perf_trend_6m,work_city\n"
        "NEXACORE-HR-001,NexaCore Technologies Pvt Ltd,NC001,Ayaan Malik,HQ,Executive,"
        "Leadership,POS-001,CEO,,2020-01-01,2026-09-17,Active,PKR,500000,95,2,4.8,"
        "Leadership,Expert,0.3,Lahore\n"
        "NEXACORE-HR-001,NexaCore Technologies Pvt Ltd,NC002,Sara Ahmed,Technology,"
        "Engineering,Platform,POS-002,Engineer,NC001,2023-01-01,2026-09-17,Active,PKR,"
        "250000,88,5,4.4,Python,Advanced,0.2,Lahore\n"
    ).encode("utf-8")


def sync(client: TestClient):
    return client.post(
        "/organization-onboarding/api/organizations/NEXACORE-HR-001/datasets/auto-sync",
        json={
            "filename": "nexacore.csv",
            "content_base64": base64.b64encode(sample_csv()).decode("ascii"),
            "source_system": "nexacore_hr",
            "source_object": "employees_current",
        },
    )


def test_one_click_upload_persists_raw_maps_and_writes_graph(tmp_path, monkeypatch):
    client, _, raw_store, repo = build_client(tmp_path, monkeypatch)
    create_org(client)

    response = sync(client)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["status"] == "synced"
    assert payload["organization_status"] == "active"
    assert payload["rows_received"] == 2
    assert payload["raw_supabase"]["persisted"] is True
    assert payload["raw_supabase"]["datasets_table"] == "org_ingestion_datasets"
    assert payload["raw_supabase"]["rows_table"] == "org_ingestion_rows"

    mapping = payload["mapping"]
    by_source = {
        item["source_column"]: item["ontology_path"]
        for item in mapping["property_mappings"]
    }
    assert by_source["staff_no"] == "Employee.employeeId"
    assert by_source["worker_name"] == "Employee.name"
    assert by_source["division"] == "Department.departmentId"
    assert "perf_trend_6m" in mapping["unmapped_columns"]
    assert "work_city" in mapping["unmapped_columns"]
    assert "perf_trend_6m" not in by_source

    assert payload["graph"]["nodes_after"] > 0
    assert payload["graph"]["relationships_after"] > 0
    assert repo.count_nodes("NEXACORE-HR-001") == payload["graph"]["nodes_after"]
    assert repo.count_relationships("NEXACORE-HR-001") == payload["graph"]["relationships_after"]
    assert raw_store.snapshots
    snapshot = raw_store.snapshots[-1]
    assert snapshot["tenant_id"] == "NEXACORE-HR-001"
    assert snapshot["rows"][0]["staff_no"] == "NC001"
    assert "perf_trend_6m" in snapshot["columns"]
    assert raw_store.status_updates[-1]["status"] == "synced"


def test_same_source_object_reupload_reuses_dataset_and_graph_ids(tmp_path, monkeypatch):
    client, _, _, _ = build_client(tmp_path, monkeypatch)
    create_org(client)

    first = sync(client)
    second = sync(client)
    assert first.status_code == 200 and second.status_code == 200
    a = first.json()
    b = second.json()

    assert a["dataset_id"] == b["dataset_id"]
    assert b["graph"]["nodes_before"] == b["graph"]["nodes_after"]
    assert b["graph"]["relationships_before"] == b["graph"]["relationships_after"]


def test_auto_sync_ui_removes_manual_lifecycle_and_shows_live_mapping(tmp_path, monkeypatch):
    client, _, _, _ = build_client(tmp_path, monkeypatch)
    html = client.get("/organization-onboarding").text
    js = client.get("/organization-onboarding/assets/app.js").text

    assert "Upload & Sync Now" in html
    assert "Profile → Map → Approve → Dry-run → Load" in html
    assert 'id="dataset-select"' not in html
    assert 'id="profile-dataset"' not in html
    assert 'id="approve-plan"' not in html
    assert 'id="dry-run"' not in html
    assert 'id="mapping-table"' in html
    assert 'id="graph-preview"' in html
    assert "/datasets/auto-sync" in js
    assert "property_mappings" in js
    assert "graph_preview" in js


def test_raw_ingestion_sql_uses_jsonb_tenant_keys_fk_indexes_and_rls():
    sql = Path("backend/multi_org/sql/organization_ingestion_schema.sql").read_text().lower()
    assert "create table if not exists public.org_ingestion_datasets" in sql
    assert "create table if not exists public.org_ingestion_rows" in sql
    assert "primary key (tenant_id, dataset_id)" in sql
    assert "foreign key (tenant_id, dataset_id)" in sql
    assert "row_data jsonb" in sql
    assert "column_names jsonb" in sql
    assert "using gin" in sql
    assert "enable row level security" in sql
