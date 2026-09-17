"""Step 13 liveness, readiness, and production release gates."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Any

from mapping.service import CURRENT_MAPPING_SERVICE
from ontology.registry import DEFAULT_REGISTRY
from ontology.validator import validate_registry

from .config import ProductionSettings
from .models import LivenessReport, ProductionCheck, ReadinessReport, ReleaseGateReport
from .versioning import current_version_info


def _check(code: str, ok: bool, success: str, failure: str, *, warning: bool = False, **details) -> ProductionCheck:
    severity = "pass" if ok else ("warning" if warning else "error")
    return ProductionCheck(code=code, severity=severity, message=success if ok else failure, details=details)


class ProductionReadinessService:
    def __init__(
        self,
        *,
        project_root: str | Path,
        repository: Any | None = None,
        settings: ProductionSettings | None = None,
        supabase_check: Callable[[], bool] | None = None,
        mapping_validation: Callable[[], dict] | None = None,
        ontology_validation: Callable[[], list] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.repository = repository
        self.settings = settings or ProductionSettings.from_env()
        self.supabase_check = supabase_check
        self.mapping_validation = mapping_validation or CURRENT_MAPPING_SERVICE.validation_report
        self.ontology_validation = ontology_validation or (lambda: validate_registry(DEFAULT_REGISTRY))

    @property
    def version(self):
        return current_version_info(root=self.project_root, settings=self.settings)

    def liveness(self) -> LivenessReport:
        return LivenessReport(release_version=self.version.release_version)

    def _resolve_path(self, env_name: str, default: str) -> Path:
        value = os.getenv(env_name, default).strip() or default
        path = Path(value)
        return path if path.is_absolute() else (self.project_root / path).resolve()

    def _static_readiness_checks(self) -> list[ProductionCheck]:
        checks: list[ProductionCheck] = []
        data_dir = self._resolve_path("DATA_DIR", "Data")
        model_path = self._resolve_path("MODEL_PATH", "models/catboost_attrition_model.cbm")
        checks.append(_check(
            "data_directory",
            data_dir.is_dir(),
            "HR data directory is present.",
            "HR data directory is missing.",
            path=str(data_dir),
        ))
        checks.append(_check(
            "catboost_model",
            model_path.is_file(),
            "CatBoost model artifact is present.",
            "CatBoost model artifact is missing.",
            path=str(model_path),
        ))

        ontology_issues = self.ontology_validation()
        ontology_errors = [item for item in ontology_issues if getattr(item, "severity", None) == "error"]
        ontology_warnings = [item for item in ontology_issues if getattr(item, "severity", None) == "warning"]
        checks.append(_check(
            "ontology_validation",
            not ontology_errors,
            "Ontology has no structural errors.",
            f"Ontology has {len(ontology_errors)} structural error(s).",
            error_count=len(ontology_errors),
            warning_count=len(ontology_warnings),
        ))
        if ontology_warnings:
            checks.append(ProductionCheck(
                code="ontology_semantic_warnings",
                severity="warning",
                message=f"Ontology has {len(ontology_warnings)} intentionally unresolved semantic warning(s).",
                details={"warning_count": len(ontology_warnings)},
            ))

        mapping = self.mapping_validation()
        mapping_errors = int(mapping.get("error_count", 0))
        mapping_warnings = int(mapping.get("warning_count", 0))
        checks.append(_check(
            "mapping_validation",
            mapping_errors == 0,
            "Current source-to-ontology mapping validates cleanly.",
            f"Current mapping has {mapping_errors} validation error(s).",
            error_count=mapping_errors,
            warning_count=mapping_warnings,
        ))
        return checks

    def _graph_checks(self, tenant_id: str) -> list[ProductionCheck]:
        if self.repository is None:
            return [ProductionCheck(
                code="neo4j_repository",
                severity="error",
                message="Neo4j repository is not configured for readiness checks.",
            )]
        checks: list[ProductionCheck] = []
        try:
            verify = getattr(self.repository, "verify_connectivity", None)
            if callable(verify):
                verify()
            checks.append(ProductionCheck(
                code="neo4j_connectivity",
                severity="pass",
                message="Neo4j connectivity is available.",
            ))
            nodes = int(self.repository.count_nodes(tenant_id))
            relationships = int(self.repository.count_relationships(tenant_id))
            nonempty = nodes > 0 and relationships > 0
            checks.append(_check(
                "tenant_graph_data",
                nonempty or not self.settings.require_nonempty_graph,
                "Tenant graph contains nodes and relationships." if nonempty else "Empty graph is allowed by current Step-13 policy.",
                "Tenant graph is empty; graph-backed runtime is not release-ready.",
                tenant_id=tenant_id,
                node_count=nodes,
                relationship_count=relationships,
            ))
        except Exception as exc:
            checks.append(ProductionCheck(
                code="neo4j_connectivity",
                severity="error",
                message="Neo4j connectivity check failed.",
                details={"error_type": type(exc).__name__},
            ))
        return checks

    def _supabase_checks(self) -> list[ProductionCheck]:
        if not self.settings.require_supabase:
            return [ProductionCheck(
                code="supabase_connectivity",
                severity="pass",
                message="Supabase external check is disabled by policy.",
            )]
        if self.supabase_check is None:
            return [ProductionCheck(
                code="supabase_connectivity",
                severity="error",
                message="Supabase readiness check is required but not configured.",
            )]
        try:
            ok = bool(self.supabase_check())
            return [_check(
                "supabase_connectivity",
                ok,
                "Supabase connectivity is available.",
                "Supabase connectivity check did not succeed.",
            )]
        except Exception as exc:
            return [ProductionCheck(
                code="supabase_connectivity",
                severity="error",
                message="Supabase connectivity check failed.",
                details={"error_type": type(exc).__name__},
            )]

    def readiness(self, tenant_id: str) -> ReadinessReport:
        checks = self._static_readiness_checks() + self._graph_checks(tenant_id) + self._supabase_checks()
        errors = sum(item.severity == "error" for item in checks)
        warnings = sum(item.severity == "warning" for item in checks)
        return ReadinessReport(
            status="ready" if errors == 0 else "not_ready",
            tenant_id=tenant_id,
            release_version=self.version.release_version,
            error_count=errors,
            warning_count=warnings,
            checks=checks,
        )

    def _production_policy_checks(self, *, require_production: bool) -> list[ProductionCheck]:
        s = self.settings
        checks: list[ProductionCheck] = []
        if require_production:
            checks.append(_check(
                "production_environment",
                s.is_production,
                "APP_ENV is production.",
                "APP_ENV must be production for a production release.",
                app_env=s.app_env,
            ))
        else:
            checks.append(ProductionCheck(
                code="production_environment",
                severity="pass" if s.is_production else "warning",
                message="APP_ENV is production." if s.is_production else f"Release gate is running in {s.app_env!r} mode.",
                details={"app_env": s.app_env},
            ))

        origins = set(s.allowed_origins)
        cors_safe = bool(origins) and "*" not in origins
        checks.append(_check(
            "cors_policy",
            cors_safe if (s.is_production or require_production) else True,
            "CORS origins are explicitly allow-listed." if cors_safe else "Development mode permits wildcard CORS.",
            "Production CORS must not use wildcard '*'.",
            allowed_origin_count=len(origins),
        ))
        checks.append(_check(
            "authentication_enabled",
            s.auth_enabled if (s.is_production or require_production) else True,
            "Authentication is enabled." if s.auth_enabled else "Authentication is disabled only for non-production mode.",
            "AUTH_ENABLED must be true in production.",
        ))
        checks.append(_check(
            "default_tenant_access",
            (not s.step12_default_tenant_open_access) if (s.is_production or require_production) else True,
            "Default tenant does not permit legacy open access." if not s.step12_default_tenant_open_access else "Legacy open access is permitted only outside production.",
            "STEP12_DEFAULT_TENANT_OPEN_ACCESS must be false in production.",
        ))
        graph_mode_ok = s.step9_runtime_mode in {"graph_first", "graph_only"}
        checks.append(_check(
            "runtime_source_policy",
            graph_mode_ok,
            f"Step-9 runtime mode is {s.step9_runtime_mode}.",
            "Production runtime must use graph_first or graph_only mode.",
            mode=s.step9_runtime_mode,
        ))
        if s.step9_allow_legacy_fallback:
            checks.append(ProductionCheck(
                code="legacy_fallback",
                severity="warning",
                message="Legacy fallback remains enabled for compatibility; monitor until all hybrid services reach graph parity.",
            ))
        return checks

    def release_gate(self, tenant_id: str, *, require_production: bool = False) -> ReleaseGateReport:
        readiness = self.readiness(tenant_id)
        checks = self._production_policy_checks(require_production=require_production) + readiness.checks
        errors = sum(item.severity == "error" for item in checks)
        warnings = sum(item.severity == "warning" for item in checks)
        return ReleaseGateReport(
            status="pass" if errors == 0 else "fail",
            tenant_id=tenant_id,
            release_version=self.version.release_version,
            production_mode_required=require_production,
            error_count=errors,
            warning_count=warnings,
            checks=checks,
        )
