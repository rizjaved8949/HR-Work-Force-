from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_refactor.models import (
    RuntimeMode,
    ServiceMigrationState,
    ServiceMigrationStatus,
    Step9RuntimeStatus,
)
from ui_integration.config import Step11UIConfig
from ui_integration.router import create_ui_integration_router
from ui_integration.service import ExistingHRUIIntegrationService


ROOT = Path(__file__).resolve().parents[1]


class FakeRuntime:
    def __init__(self, *, graph_available: bool = True):
        self.graph_available = graph_available
        self.config = SimpleNamespace(
            tenant_id="ORGANIZATION-001",
            allow_legacy_fallback=True,
        )

    def status(self):
        return Step9RuntimeStatus(
            mode=RuntimeMode.GRAPH_FIRST,
            tenant_id="ORGANIZATION-001",
            graph_available=self.graph_available,
            ui_api_contract_preserved=True,
            services=[
                ServiceMigrationStatus(
                    service="employee_record_retrieval",
                    state=ServiceMigrationState.GRAPH_FIRST_WITH_LEGACY_FALLBACK,
                    active_source="knowledge_graph",
                    graph_capable=True,
                    fallback_enabled=True,
                    notes=["UI shape preserved."],
                ),
                ServiceMigrationStatus(
                    service="attrition_prediction",
                    state=ServiceMigrationState.GRAPH_FIRST_WITH_LEGACY_FALLBACK,
                    active_source="knowledge_graph",
                    graph_capable=True,
                    fallback_enabled=True,
                    notes=["14-feature model contract preserved."],
                ),
                ServiceMigrationStatus(
                    service="employee_performance",
                    state=ServiceMigrationState.HYBRID,
                    active_source="legacy_deterministic_service_with_step8_contract",
                    graph_capable=True,
                    fallback_enabled=True,
                    notes=[],
                ),
            ],
            warnings=[],
        )


def _service(monkeypatch, *, auth_enabled=False, graph_available=True):
    monkeypatch.setenv("AUTH_ENABLED", "true" if auth_enabled else "false")
    config = Step11UIConfig(
        app_name="HR Workforce Intelligence",
        ontology_studio_nav_enabled=True,
        reference_console_enabled=True,
        admin_roles=("admin", "owner", "hr_admin", "super_admin"),
    )
    return ExistingHRUIIntegrationService(FakeRuntime(graph_available=graph_available), config=config)


def test_step11_bootstrap_centralizes_current_tenant_and_runtime(monkeypatch):
    service = _service(monkeypatch)
    payload = service.bootstrap()
    assert payload.step == 11
    assert payload.tenant_id == "ORGANIZATION-001"
    assert payload.graph_available is True
    assert payload.ui_api_contract_preserved is True
    assert payload.metadata["tenant_source"] == "STEP9_TENANT_ID"
    assert payload.metadata["multi_org_switching"] is False


def test_step11_navigation_exposes_existing_hr_modules_without_inventing_frontend_paths(monkeypatch):
    service = _service(monkeypatch)
    items = service.navigation()
    ids = {item.id for item in items}
    assert {
        "dashboard", "employees", "attrition", "performance", "headcount",
        "scenarios", "decision-cases", "assistant", "ontology-studio"
    }.issubset(ids)
    # The integration contract uses route keys; the current frontend owns its URL scheme.
    assert all(item.route_key for item in items)
    assert all(item.backend_surface for item in items)


def test_step11_hides_ontology_studio_from_non_admin_when_auth_enabled(monkeypatch):
    service = _service(monkeypatch, auth_enabled=True)
    user = SimpleNamespace(id="u1", full_name="Analyst", email="a@example.com", role="analyst")
    ids = {item.id for item in service.navigation(user)}
    assert "ontology-studio" not in ids
    assert service.feature_flags(user)["ontology_studio"] is False


def test_step11_shows_ontology_studio_to_admin_when_auth_enabled(monkeypatch):
    service = _service(monkeypatch, auth_enabled=True)
    user = SimpleNamespace(id="u1", full_name="Admin", email="a@example.com", role="hr_admin")
    ids = {item.id for item in service.navigation(user)}
    assert "ontology-studio" in ids
    assert service.feature_flags(user)["ontology_studio"] is True


def test_step11_contract_preserves_existing_business_endpoint_paths(monkeypatch):
    service = _service(monkeypatch)
    paths = {
        endpoint.path
        for group in service.endpoint_groups()
        for endpoint in group.endpoints
    }
    assert "/tools/employee-search" in paths
    assert "/pipeline/attrition" in paths
    assert "/pipeline/replacement" in paths
    assert "/pipeline/headcount" in paths
    assert "/pipeline/performance" in paths
    assert "/api/v1/simulations/run" in paths
    assert "/api/v1/decision-cases" in paths
    assert "/chat" in paths
    assert "/chat/stream" in paths
    assert "/ontology-studio/api/dashboard" in paths


def test_step11_runtime_badges_are_derived_from_step9_not_recalculated(monkeypatch):
    service = _service(monkeypatch)
    items = {item.service: item for item in service.runtime_services()}
    assert items["employee_record_retrieval"].active_source == "knowledge_graph"
    assert items["attrition_prediction"].state == "graph_first_with_legacy_fallback"
    assert items["employee_performance"].state == "hybrid"


def test_step11_graph_unavailable_is_visible_not_hidden(monkeypatch):
    service = _service(monkeypatch, graph_available=False)
    payload = service.bootstrap()
    assert payload.graph_available is False
    assert any("legacy fallback" in warning.lower() for warning in payload.warnings)


def test_step11_router_exposes_bootstrap_navigation_runtime_and_contract(monkeypatch):
    service = _service(monkeypatch)
    runtime = service.runtime
    app = FastAPI()
    app.include_router(create_ui_integration_router(runtime, service=service))
    client = TestClient(app)
    assert client.get("/ui-integration/bootstrap").status_code == 200
    assert client.get("/ui-integration/navigation").status_code == 200
    assert client.get("/ui-integration/runtime").status_code == 200
    response = client.get("/ui-integration/api-contract")
    assert response.status_code == 200
    assert response.json()["ui_api_contract_preserved"] is True
    assert client.get("/ui-integration").status_code == 200
    assert client.get("/ui-integration/assets/hr-ui-client.js").status_code == 200


def test_step11_drop_in_client_forwards_bearer_token_and_reuses_existing_routes():
    client_file = ROOT / "backend" / "ui_integration" / "static" / "hr-ui-client.js"
    text = client_file.read_text(encoding="utf-8")
    assert "Authorization" in text
    assert "Bearer ${token}" in text
    assert '"/tools/employee-search"' in text
    assert '"/pipeline/attrition"' in text
    assert '"/pipeline/headcount"' in text
    assert '"/api/v1/simulations/run"' in text
    assert '"/chat"' in text


def test_step11_frontend_never_receives_neo4j_credentials_or_cypher_contract(monkeypatch):
    service = _service(monkeypatch)
    payload = service.bootstrap().model_dump_json()
    lowered = payload.lower()
    assert "neo4j_password" not in lowered
    assert "bolt://" not in lowered
    assert "match (" not in lowered
