from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from production.config import ProductionSettings
from production.middleware import install_production_hardening
from production.router import create_production_router
from production.service import ProductionReadinessService
from production.versioning import current_version_info

ROOT = Path(__file__).resolve().parents[1]


class FakeRepository:
    def __init__(self, nodes=10, relationships=20, fail=False):
        self.nodes = nodes
        self.relationships = relationships
        self.fail = fail

    def verify_connectivity(self):
        if self.fail:
            raise RuntimeError("offline")

    def count_nodes(self, tenant_id=None):
        return self.nodes

    def count_relationships(self, tenant_id=None):
        return self.relationships


def settings(**overrides):
    values = dict(
        app_env="development",
        allowed_origins=("*",),
        auth_enabled=False,
        step9_runtime_mode="graph_first",
        step9_allow_legacy_fallback=True,
        step12_default_tenant_open_access=True,
        expose_docs=True,
        force_https=False,
        trusted_hosts=(),
        release_commit=None,
        build_time=None,
        require_nonempty_graph=True,
        require_supabase=True,
    )
    values.update(overrides)
    return ProductionSettings(**values)


def service(*, repo=None, cfg=None, supabase=True, mapping_errors=0, ontology_issues=None):
    return ProductionReadinessService(
        project_root=ROOT,
        repository=repo or FakeRepository(),
        settings=cfg or settings(),
        supabase_check=(lambda: supabase),
        mapping_validation=lambda: {"error_count": mapping_errors, "warning_count": 0},
        ontology_validation=lambda: ontology_issues or [],
    )


def test_step13_version_manifest_is_bound_to_current_roadmap_versions():
    info = current_version_info(root=ROOT, settings=settings())
    assert info.roadmap_step == 13
    assert info.release_version == "2026.09-step13.1"
    assert info.ontology_version == "1.0.2-draft"
    assert info.mapping_version == "1.0.0-step3"
    assert info.graph_model_version == "1.0.0-step4"


def test_step13_liveness_does_not_depend_on_external_services():
    report = service(repo=FakeRepository(fail=True), supabase=False).liveness()
    assert report.status == "alive"
    assert report.step == 13


def test_step13_readiness_passes_when_artifacts_graph_and_supabase_are_available():
    report = service().readiness("ORGANIZATION-001")
    assert report.ready is True
    assert report.error_count == 0
    assert any(c.code == "tenant_graph_data" and c.severity == "pass" for c in report.checks)


def test_step13_readiness_blocks_empty_tenant_graph_when_required():
    report = service(repo=FakeRepository(nodes=0, relationships=0)).readiness("ORGANIZATION-001")
    assert report.ready is False
    assert any(c.code == "tenant_graph_data" and c.severity == "error" for c in report.checks)


def test_step13_readiness_reports_external_graph_failure_without_secret_leakage():
    report = service(repo=FakeRepository(fail=True)).readiness("ORGANIZATION-001")
    item = next(c for c in report.checks if c.code == "neo4j_connectivity")
    assert item.severity == "error"
    assert "password" not in item.message.lower()
    assert item.details["error_type"] == "RuntimeError"


def test_step13_readiness_blocks_mapping_errors():
    report = service(mapping_errors=2).readiness("ORGANIZATION-001")
    assert report.ready is False
    assert any(c.code == "mapping_validation" and c.severity == "error" for c in report.checks)


def test_step13_known_ontology_warning_remains_warning_not_fabricated_error():
    issues = [SimpleNamespace(severity="warning", code="pending_semantic_confirmation")]
    report = service(ontology_issues=issues).readiness("ORGANIZATION-001")
    assert report.ready is True
    item = next(c for c in report.checks if c.code == "ontology_semantic_warnings")
    assert item.severity == "warning"


def test_step13_production_release_gate_rejects_wildcard_cors():
    cfg = settings(
        app_env="production",
        auth_enabled=True,
        step12_default_tenant_open_access=False,
        allowed_origins=("*",),
    )
    report = service(cfg=cfg).release_gate("ORGANIZATION-001", require_production=True)
    assert report.passed is False
    assert any(c.code == "cors_policy" and c.severity == "error" for c in report.checks)


def test_step13_production_release_gate_requires_authentication():
    cfg = settings(
        app_env="production",
        auth_enabled=False,
        step12_default_tenant_open_access=False,
        allowed_origins=("https://hr.example.com",),
    )
    report = service(cfg=cfg).release_gate("ORGANIZATION-001", require_production=True)
    assert report.passed is False
    assert any(c.code == "authentication_enabled" and c.severity == "error" for c in report.checks)


def test_step13_production_release_gate_closes_legacy_open_tenant_access():
    cfg = settings(
        app_env="production",
        auth_enabled=True,
        step12_default_tenant_open_access=True,
        allowed_origins=("https://hr.example.com",),
    )
    report = service(cfg=cfg).release_gate("ORGANIZATION-001", require_production=True)
    assert report.passed is False
    assert any(c.code == "default_tenant_access" and c.severity == "error" for c in report.checks)


def test_step13_safe_production_policy_passes_with_legacy_fallback_visible_as_warning():
    cfg = settings(
        app_env="production",
        auth_enabled=True,
        step12_default_tenant_open_access=False,
        allowed_origins=("https://hr.example.com",),
        step9_runtime_mode="graph_first",
        step9_allow_legacy_fallback=True,
    )
    report = service(cfg=cfg).release_gate("ORGANIZATION-001", require_production=True)
    assert report.passed is True
    assert any(c.code == "legacy_fallback" and c.severity == "warning" for c in report.checks)


def test_step13_router_exposes_version_liveness_readiness_and_release_gate():
    app = FastAPI()
    app.include_router(create_production_router(service()))
    client = TestClient(app)
    assert client.get("/system/version").status_code == 200
    assert client.get("/system/liveness").json()["status"] == "alive"
    assert client.get("/system/readiness?tenant_id=ORGANIZATION-001").json()["status"] == "ready"
    assert client.get("/system/release-gate?tenant_id=ORGANIZATION-001").status_code == 200


def test_step13_security_headers_and_generated_request_id_are_added():
    app = FastAPI()
    install_production_hardening(app, settings())

    @app.get("/x")
    def x():
        return {"ok": True}

    response = TestClient(app).get("/x")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers.get("x-request-id")


def test_step13_existing_request_id_is_preserved_and_backup_restore_is_non_destructive():
    app = FastAPI()
    install_production_hardening(app, settings())

    @app.get("/x")
    def x():
        return {"ok": True}

    response = TestClient(app).get("/x", headers={"X-Request-ID": "trace-123"})
    assert response.headers["x-request-id"] == "trace-123"
    restore = (ROOT / "scripts" / "restore_neo4j_volume_to_new_volume.sh").read_text(encoding="utf-8")
    assert "Refusing to overwrite existing Docker volume" in restore
    assert ".env and secrets are intentionally NOT included" in (ROOT / "scripts" / "backup_app_state.sh").read_text(encoding="utf-8")
