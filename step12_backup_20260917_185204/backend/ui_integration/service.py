"""Step 11 integration facade for the existing HR application UI.

The browser keeps using the already-existing business endpoints.  This service
adds one authoritative bootstrap/contract surface for tenant context,
permissions, navigation, runtime source badges and endpoint discovery.
"""
from __future__ import annotations

import os
from typing import Any
from service_refactor.runtime import Step9RuntimeManager

from .config import Step11UIConfig
from .models import (
    UIEndpoint,
    UIEndpointGroup,
    UIIntegrationBootstrap,
    UINavItem,
    UIServiceRuntime,
    UIUserContext,
)


def _auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


class ExistingHRUIIntegrationService:
    def __init__(
        self,
        runtime: Step9RuntimeManager,
        *,
        config: Step11UIConfig | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = config or Step11UIConfig.from_env()

    @staticmethod
    def _read_user_field(user: Any, name: str) -> Any:
        if user is None:
            return None
        if isinstance(user, dict):
            return user.get(name)
        return getattr(user, name, None)

    def user_context(self, user: Any = None) -> UIUserContext:
        if not _auth_enabled():
            # Local development deliberately remains usable.  Treat the local
            # developer as an admin only for navigation visibility; Step 10
            # independently enforces writes when auth is enabled.
            return UIUserContext(authenticated=False, is_admin=True, role="local_dev")

        role = str(self._read_user_field(user, "role") or "").strip().lower()
        return UIUserContext(
            authenticated=user is not None,
            user_id=str(self._read_user_field(user, "id") or "") or None,
            full_name=self._read_user_field(user, "full_name"),
            email=self._read_user_field(user, "email"),
            role=role or None,
            is_admin=role in set(self.config.admin_roles),
        )

    def navigation(self, user: Any = None) -> list[UINavItem]:
        context = self.user_context(user)
        items = [
            UINavItem(
                id="dashboard",
                label="Dashboard",
                route_key="dashboard",
                backend_surface="/health",
                description="Application overview and backend readiness.",
            ),
            UINavItem(
                id="employees",
                label="Employees",
                route_key="employees",
                backend_surface="/tools/employee-search",
                description="Employee search and profile workspace.",
            ),
            UINavItem(
                id="attrition",
                label="Attrition",
                route_key="attrition",
                backend_surface="/pipeline/attrition",
                description="Graph-first attrition prediction and dashboard.",
            ),
            UINavItem(
                id="performance",
                label="Performance",
                route_key="performance",
                backend_surface="/api/v1/dashboard/performance/overview",
                description="Performance intelligence and employee evaluation.",
            ),
            UINavItem(
                id="headcount",
                label="Headcount",
                route_key="headcount",
                backend_surface="/pipeline/headcount",
                description="Deterministic workforce and headcount analytics.",
            ),
            UINavItem(
                id="scenarios",
                label="Scenario Simulator",
                route_key="scenarios",
                backend_surface="/api/v1/simulations/scenarios",
                description="Read-only workforce what-if simulations.",
            ),
            UINavItem(
                id="decision-cases",
                label="Decision Cases",
                route_key="decision_cases",
                backend_surface="/api/v1/decision-cases",
                description="Priority HR decision-trigger queue.",
            ),
            UINavItem(
                id="assistant",
                label="AI Assistant",
                route_key="assistant",
                backend_surface="/chat/stream",
                description="Conversational HR intelligence.",
            ),
        ]
        if context.is_admin:
            items.append(
                UINavItem(
                    id="organization-onboarding",
                    label="Organizations",
                    route_key="organization_onboarding",
                    audience="admin",
                    backend_surface="/organization-onboarding",
                    description="Multi-organization onboarding, mapping and tenant activation.",
                )
            )
        if self.config.ontology_studio_nav_enabled and context.is_admin:
            items.append(
                UINavItem(
                    id="ontology-studio",
                    label="Ontology Studio",
                    route_key="ontology_studio",
                    audience="admin",
                    backend_surface="/ontology-studio",
                    description="Ontology, mapping, coverage and governance management.",
                )
            )
        return items

    @staticmethod
    def endpoint_groups() -> list[UIEndpointGroup]:
        return [
            UIEndpointGroup(
                module="employee",
                label="Employee",
                endpoints=[
                    UIEndpoint(id="employee-search", method="POST", path="/tools/employee-search", module="employee", purpose="Resolve an employee and profile context."),
                ],
            ),
            UIEndpointGroup(
                module="attrition",
                label="Attrition",
                endpoints=[
                    UIEndpoint(id="attrition-pipeline", method="POST", path="/pipeline/attrition", module="attrition", purpose="Resolve employee and run attrition prediction."),
                    UIEndpoint(id="attrition-summary", method="GET", path="/api/v1/dashboard/attrition/summary", module="attrition", purpose="Attrition dashboard summary."),
                    UIEndpoint(id="attrition-rate", method="GET", path="/api/v1/dashboard/attrition/attrition-rate", module="attrition", purpose="Attrition rate card."),
                    UIEndpoint(id="department-risk", method="GET", path="/api/v1/dashboard/attrition/department-risk", module="attrition", purpose="Department risk breakdown."),
                    UIEndpoint(id="top-risk-drivers", method="GET", path="/api/v1/dashboard/attrition/top-risk-drivers", module="attrition", purpose="Top model risk drivers."),
                    UIEndpoint(id="people-at-risk", method="GET", path="/api/v1/dashboard/attrition/people-at-risk", module="attrition", purpose="Filterable people-at-risk list."),
                ],
            ),
            UIEndpointGroup(
                module="performance",
                label="Performance",
                endpoints=[
                    UIEndpoint(id="performance-analyze", method="POST", path="/pipeline/performance", module="performance", purpose="Deterministic performance analysis."),
                    UIEndpoint(id="performance-overview", method="GET", path="/api/v1/dashboard/performance/overview", module="performance", purpose="Performance dashboard overview."),
                    UIEndpoint(id="performance-trend", method="GET", path="/api/v1/dashboard/performance/trend", module="performance", purpose="Organization performance trend."),
                    UIEndpoint(id="performance-attention", method="GET", path="/api/v1/dashboard/performance/attention", module="performance", purpose="Employees requiring attention."),
                ],
            ),
            UIEndpointGroup(
                module="headcount",
                label="Headcount",
                endpoints=[
                    UIEndpoint(id="headcount-analyze", method="POST", path="/pipeline/headcount", module="headcount", purpose="Deterministic headcount analysis."),
                ],
            ),
            UIEndpointGroup(
                module="replacement",
                label="Succession / Replacement",
                endpoints=[
                    UIEndpoint(id="replacement", method="POST", path="/pipeline/replacement", module="replacement", purpose="Rank internal successor candidates."),
                ],
            ),
            UIEndpointGroup(
                module="simulations",
                label="Scenario Simulation",
                endpoints=[
                    UIEndpoint(id="simulation-scenarios", method="GET", path="/api/v1/simulations/scenarios", module="simulations", purpose="List supported scenarios."),
                    UIEndpoint(id="simulation-options", method="GET", path="/api/v1/simulations/options", module="simulations", purpose="Resolve scenario form options."),
                    UIEndpoint(id="simulation-run", method="POST", path="/api/v1/simulations/run", module="simulations", purpose="Run a deterministic scenario simulation."),
                ],
            ),
            UIEndpointGroup(
                module="decision_cases",
                label="Decision Cases",
                endpoints=[
                    UIEndpoint(id="decision-list", method="GET", path="/api/v1/decision-cases", module="decision_cases", purpose="Read current important HR decision cases."),
                    UIEndpoint(id="decision-evaluate", method="POST", path="/api/v1/decision-cases/evaluate", module="decision_cases", purpose="Evaluate deterministic trigger rules."),
                    UIEndpoint(id="decision-status", method="PATCH", path="/api/v1/decision-cases/{case_id}/status", module="decision_cases", purpose="Update case workflow status."),
                ],
            ),
            UIEndpointGroup(
                module="assistant",
                label="AI Assistant",
                endpoints=[
                    UIEndpoint(id="chat", method="POST", path="/chat", module="assistant", purpose="Single HR assistant reply.", timeout_seconds=120),
                    UIEndpoint(id="chat-stream", method="POST", path="/chat/stream", module="assistant", purpose="Streaming HR assistant reply.", timeout_seconds=120, streaming=True),
                ],
            ),
            UIEndpointGroup(
                module="management",
                label="Management",
                endpoints=[
                    UIEndpoint(id="step9-status", method="GET", path="/runtime/step9/status", module="management", purpose="Current service migration/source status."),
                    UIEndpoint(id="ontology-dashboard", method="GET", path="/ontology-studio/api/dashboard", module="management", purpose="Ontology Studio dashboard."),
                    UIEndpoint(id="ontology-graph", method="GET", path="/ontology-studio/api/schema-graph", module="management", purpose="Ontology schema graph."),
                ],
            ),
        ]

    def runtime_services(self) -> list[UIServiceRuntime]:
        status = self.runtime.status()
        return [
            UIServiceRuntime(
                service=item.service,
                state=item.state.value if hasattr(item.state, "value") else str(item.state),
                active_source=item.active_source,
                graph_capable=item.graph_capable,
                fallback_enabled=item.fallback_enabled,
                notes=list(item.notes),
            )
            for item in status.services
        ]

    def feature_flags(self, user: Any = None) -> dict[str, bool]:
        context = self.user_context(user)
        return {
            "employee_search": True,
            "attrition": True,
            "performance": True,
            "headcount": True,
            "successor_replacement": True,
            "scenario_simulation": True,
            "decision_cases": True,
            "assistant": True,
            "ontology_studio": self.config.ontology_studio_nav_enabled and context.is_admin,
            "multi_organization": True,
            "organization_onboarding": context.is_admin,
            "graph_runtime": bool(self.runtime.graph_available),
            "legacy_fallback": bool(self.runtime.config.allow_legacy_fallback),
        }

    def bootstrap(
        self,
        user: Any = None,
        *,
        tenant_id: str | None = None,
    ) -> UIIntegrationBootstrap:
        runtime_status = self.runtime.status()
        context = self.user_context(user)
        selected_tenant = str(tenant_id or runtime_status.tenant_id).strip()
        warnings = list(runtime_status.warnings)
        graph_available = runtime_status.graph_available
        if selected_tenant != runtime_status.tenant_id:
            semantic = getattr(self.runtime, "semantic_service", None)
            if semantic is not None:
                try:
                    health = semantic.health(selected_tenant)
                    graph_available = int(health.get("node_count") or 0) > 0
                except Exception:
                    graph_available = False
            warnings.append(
                "A secondary organization is selected. Graph-native employee/attrition routes are tenant-aware; "
                "legacy/hybrid services are blocked by Step 12 until they are tenant-safe."
            )
        if not graph_available:
            warnings.append(
                "Knowledge Graph is not active for the selected organization; compatible UI routes may be unavailable or use legacy fallback only for the default tenant."
            )
        return UIIntegrationBootstrap(
            app_name=self.config.app_name,
            tenant_id=selected_tenant,
            auth_enabled=_auth_enabled(),
            graph_available=graph_available,
            ui_api_contract_preserved=runtime_status.ui_api_contract_preserved,
            user=context,
            navigation=self.navigation(user),
            endpoint_groups=self.endpoint_groups(),
            runtime_services=self.runtime_services(),
            feature_flags=self.feature_flags(user),
            warnings=warnings,
            metadata={
                "runtime_mode": runtime_status.mode.value if hasattr(runtime_status.mode, "value") else str(runtime_status.mode),
                "tenant_source": "STEP9_TENANT_ID",
                "tenant_selection_source": "X-Organization-ID with STEP9_TENANT_ID fallback",
                "multi_org_switching": selected_tenant != runtime_status.tenant_id,
                "multi_org_available": True,
                "tenant_header": "X-Organization-ID",
                "default_tenant_id": runtime_status.tenant_id,
                "multi_org_note": "Step 12 validates organization access and blocks non-tenant-safe legacy/hybrid routes for secondary tenants.",
                "organization_onboarding_href": "/organization-onboarding",
                "ontology_studio_href": "/ontology-studio",
                "client_sdk": "/ui-integration/assets/hr-ui-client.js",
            },
        )
