from __future__ import annotations

import base64
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tenant_management.router import create_tenant_management_router
from tenant_management.merge_repository import MergePreservingGraphRepository
from graph.memory_repository import InMemoryGraphRepository
from graph.models import GraphNode


class _Access:
    def actor(self, user):
        return SimpleNamespace(user_id="tester", role="admin")


class _Service:
    def __init__(self):
        self.access = _Access()
        self.repository = SimpleNamespace()
        self.last_sync = None
        loaded = SimpleNamespace(status=SimpleNamespace(value="loaded"))
        self.orgs = [
            SimpleNamespace(
                tenant_id="ORGANIZATION-001",
                name="Current Organization",
                status=SimpleNamespace(value="active"),
                is_default=True,
                datasets=[loaded],
            ),
            SimpleNamespace(
                tenant_id="NEXACORE-HR-001",
                name="NexaCore",
                status=SimpleNamespace(value="active"),
                is_default=False,
                datasets=[],
            ),
        ]

    def list_organizations(self, *, actor):
        return self.orgs

    def tenant_summary(self, tenant_id, *, actor):
        org = next(item for item in self.orgs if item.tenant_id == tenant_id)
        return {
            "organization": {"tenant_id": org.tenant_id, "name": org.name},
            "readiness": {"graph_node_count": 5, "graph_relationship_count": 2},
        }

    def auto_sync_file_dataset(self, tenant_id, path, *, actor, source_system, source_object, sheet_name):
        self.last_sync = {
            "tenant_id": tenant_id,
            "source_system": source_system,
            "source_object": source_object,
            "sheet_name": sheet_name,
        }
        return {
            "status": "synced",
            "tenant_id": tenant_id,
            "rows_received": 1,
            "graph": {"nodes_before": 5, "nodes_after": 6},
        }


def _client():
    service = _Service()
    app = FastAPI()
    app.include_router(create_tenant_management_router(service, merge_service_factory=lambda value: value))
    return TestClient(app), service


def test_tenant_catalog_exposes_switchable_organizations():
    client, _ = _client()
    response = client.get("/tenant-management/api/tenants")
    assert response.status_code == 200
    payload = response.json()
    assert [item["tenant_id"] for item in payload["tenants"]] == [
        "ORGANIZATION-001",
        "NEXACORE-HR-001",
    ]
    assert payload["tenant_header"] == "X-Organization-ID"


def test_merge_sync_is_additive_and_uses_unique_source_snapshot():
    client, service = _client()
    encoded = base64.b64encode(b"employeeId,name\nE999,New Person\n").decode()
    body = {
        "filename": "employee_patch.csv",
        "content_base64": encoded,
        "source_system": "partner_hr",
        "source_object": "employee_patch",
    }
    first = client.post(
        "/tenant-management/api/organizations/NEXACORE-HR-001/merge-sync",
        json=body,
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["sync_mode"] == "merge_into_existing_tenant"
    assert payload["merge"]["preserves_existing_datasets"] is True
    stored = service.last_sync["source_object"]
    assert stored.startswith("employee_patch__merge__")
    assert service.last_sync["tenant_id"] == "NEXACORE-HR-001"


def test_management_ui_contains_tenant_selector_and_optional_merge_control():
    studio_html = open("backend/ontology_studio/static/index.html", encoding="utf-8").read()
    studio_js = open("backend/ontology_studio/static/app.js", encoding="utf-8").read()
    onboarding_html = open("backend/multi_org/static/index.html", encoding="utf-8").read()
    onboarding_js = open("backend/multi_org/static/app.js", encoding="utf-8").read()
    assert '<select id="tenant-id">' in studio_html
    assert "/tenant-management/api/tenants" in studio_js
    assert 'name="merge_into_existing"' in onboarding_html
    assert "/tenant-management/api/organizations/" in onboarding_js
    assert "/merge-sync" in onboarding_js


def test_merge_repository_preserves_unsupplied_existing_properties():
    base = InMemoryGraphRepository()
    original = GraphNode(
        graph_id="organization-1", tenant_id="ORGANIZATION-001", entity_type="Organization",
        ontology_version="1", properties={"organizationId":"ORGANIZATION-001","name":"Old Name","country":"Pakistan"},
    )
    base.upsert_node(original)
    merge = MergePreservingGraphRepository(base)
    merge.upsert_node(GraphNode(
        graph_id="organization-1", tenant_id="ORGANIZATION-001", entity_type="Organization",
        ontology_version="1", properties={"organizationId":"ORGANIZATION-001","name":"New Name"},
    ))
    saved = base.get_node("organization-1", "ORGANIZATION-001")
    assert saved.properties["name"] == "New Name"
    assert saved.properties["country"] == "Pakistan"
