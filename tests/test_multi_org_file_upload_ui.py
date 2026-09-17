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


def build_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    service = MultiOrganizationOnboardingService(
        repository=InMemoryGraphRepository(),
        registry=OrganizationRegistry(tmp_path / "organizations.json"),
        source_store=OrganizationSourceStore(tmp_path / "sources"),
        plan_store=TenantMappingPlanStore(tmp_path / "plans"),
        access=OrganizationAccessService(),
    )
    app = FastAPI()
    app.include_router(create_multi_org_router(service))
    return TestClient(app), service


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


def test_onboarding_ui_exposes_real_file_upload_control(tmp_path, monkeypatch):
    client, _ = build_client(tmp_path, monkeypatch)
    html = client.get("/organization-onboarding").text
    assert 'id="upload-dataset"' in html
    assert 'id="dataset-file"' in html
    assert 'accept=".csv,.json,.xlsx,.xlsm"' in html
    assert "Upload & register dataset" in html


def test_csv_browser_upload_registers_tenant_dataset(tmp_path, monkeypatch):
    client, service = build_client(tmp_path, monkeypatch)
    create_org(client)
    csv_bytes = (
        "staff_no,worker_name,division,supervisor_staff_no\n"
        "NC001,Ayaan Malik,Executive,\n"
        "NC002,Sara Ahmed,Engineering,NC001\n"
    ).encode("utf-8")
    response = client.post(
        "/organization-onboarding/api/organizations/NEXACORE-HR-001/datasets/upload",
        json={
            "filename": "nexacore_employees.csv",
            "content_base64": base64.b64encode(csv_bytes).decode("ascii"),
            "source_system": "nexacore_hr",
            "source_object": "nexacore_employee_feed",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["tenant_id"] == "NEXACORE-HR-001"
    assert payload["source_system"] == "nexacore_hr"
    assert payload["source_object"] == "nexacore_employee_feed"
    assert payload["source_format"] == "csv"
    assert payload["row_count"] == 2

    profile = client.get(
        f"/organization-onboarding/api/organizations/NEXACORE-HR-001/datasets/{payload['dataset_id']}/profile"
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["row_count"] == 2
    assert {col["name"] for col in profile.json()["columns"]} == {
        "staff_no",
        "worker_name",
        "division",
        "supervisor_staff_no",
    }
    stored = service.source_store.load_source(
        tenant_id="NEXACORE-HR-001", dataset_id=payload["dataset_id"]
    )
    assert len(stored.rows()) == 2


def test_upload_rejects_unsupported_file_type(tmp_path, monkeypatch):
    client, _ = build_client(tmp_path, monkeypatch)
    create_org(client)
    response = client.post(
        "/organization-onboarding/api/organizations/NEXACORE-HR-001/datasets/upload",
        json={
            "filename": "employees.exe",
            "content_base64": base64.b64encode(b"not allowed").decode("ascii"),
        },
    )
    assert response.status_code == 422
    assert "Supported upload types" in response.json()["detail"]
