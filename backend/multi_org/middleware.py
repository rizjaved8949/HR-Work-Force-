"""Tenant-context middleware for existing Step-11 UI/API routes.

For the already-migrated graph-native employee/attrition paths, a selected
organization can be supplied through X-Organization-ID.  Legacy/hybrid routes
are explicitly blocked for secondary tenants so the application can never
silently return the default organization's CSV-backed facts to another tenant.
"""
from __future__ import annotations

import os
import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .access import DEFAULT_ORGANIZATION_ACCESS, OrganizationAccessService
from .context import reset_current_tenant, set_current_tenant
from .models import OrganizationStatus
from .registry import DEFAULT_ORGANIZATION_REGISTRY, OrganizationRegistry, validate_tenant_id


UNSAFE_SECONDARY_PREFIXES = (
    "/pipeline/performance",
    "/pipeline/headcount",
    "/pipeline/replacement",
    "/api/v1/dashboard/attrition",
    "/api/v1/dashboard/performance",
    "/api/v1/simulations",
    "/api/v1/decision-cases",
    "/chat",
)


class MultiOrganizationTenantMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        registry: OrganizationRegistry = DEFAULT_ORGANIZATION_REGISTRY,
        access: OrganizationAccessService = DEFAULT_ORGANIZATION_ACCESS,
        default_tenant_id: str | None = None,
    ) -> None:
        super().__init__(app)
        self.registry = registry
        self.access = access
        self.default_tenant_id = (
            default_tenant_id
            or os.getenv("STEP9_TENANT_ID", "ORGANIZATION-001")
        ).strip()

    @staticmethod
    def _auth_public_path(path: str) -> bool:
        # Keep the existing Supabase authentication public contract intact.
        # Auth middleware intentionally does not attach a user to these routes,
        # so Step 12 must not require organization membership for them.
        try:
            from auth.config import auth_settings
        except Exception:
            return False
        normalized = path.rstrip("/") or "/"
        if normalized in auth_settings.public_paths:
            return True
        return any(
            normalized == prefix.rstrip("/")
            or normalized.startswith(prefix.rstrip("/") + "/")
            for prefix in auth_settings.public_prefixes
        )

    @staticmethod
    def _onboarding_path(path: str) -> bool:
        return path == "/organization-onboarding" or path.startswith("/organization-onboarding/")

    @staticmethod
    def _unsafe_for_secondary(path: str) -> bool:
        return any(path == prefix or path.startswith(prefix + "/") for prefix in UNSAFE_SECONDARY_PREFIXES)

    async def dispatch(
        self,
        request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        raw_tenant = request.headers.get("X-Organization-ID", "").strip()
        tenant_id = raw_tenant or self.default_tenant_id
        try:
            tenant_id = validate_tenant_id(tenant_id)
        except ValueError as error:
            return JSONResponse(status_code=400, content={"detail": str(error), "code": "invalid_tenant_id"})

        route_match = re.match(
            r"^/organization-onboarding/api/organizations/([^/]+)(?:/|$)",
            request.url.path,
        )
        route_tenant = route_match.group(1) if route_match else None
        if raw_tenant and route_tenant and str(route_tenant).strip() != tenant_id:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "X-Organization-ID must match the organization in the request path.",
                    "code": "organization_context_mismatch",
                    "header_tenant_id": tenant_id,
                    "path_tenant_id": str(route_tenant).strip(),
                },
            )

        if self._auth_public_path(request.url.path):
            request.state.tenant_id = tenant_id
            token = set_current_tenant(tenant_id)
            try:
                response = await call_next(request)
            finally:
                reset_current_tenant(token)
            response.headers["X-Organization-ID"] = tenant_id
            return response

        try:
            org = self.registry.get(tenant_id)
        except KeyError:
            # Organization creation endpoint must be reachable before the new
            # organization exists. It operates under the current/default tenant.
            if self._onboarding_path(request.url.path) and not raw_tenant:
                org = None
            else:
                return JSONResponse(
                    status_code=404,
                    content={"detail": f"Unknown organization {tenant_id!r}", "code": "organization_not_found"},
                )

        if org is not None:
            user = getattr(request.state, "user", None)
            actor = self.access.actor(user)
            if not self.access.can_access(org, actor):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Current user does not have access to the selected organization.", "code": "organization_access_denied"},
                )
            if (
                tenant_id != self.default_tenant_id
                and not self._onboarding_path(request.url.path)
                and org.status != OrganizationStatus.ACTIVE
            ):
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Selected organization is not active yet.", "code": "organization_not_active"},
                )
            if tenant_id != self.default_tenant_id and self._unsafe_for_secondary(request.url.path):
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": (
                            "This service still uses a legacy/hybrid compatibility dataset and is intentionally blocked "
                            "for secondary organizations to prevent cross-tenant data leakage."
                        ),
                        "code": "service_not_multi_tenant_safe",
                        "tenant_id": tenant_id,
                    },
                )

        request.state.tenant_id = tenant_id
        token = set_current_tenant(tenant_id)
        try:
            response = await call_next(request)
        finally:
            reset_current_tenant(token)
        response.headers["X-Organization-ID"] = tenant_id
        return response


def install_multi_organization_tenant_context(
    app,
    *,
    registry: OrganizationRegistry = DEFAULT_ORGANIZATION_REGISTRY,
    access: OrganizationAccessService = DEFAULT_ORGANIZATION_ACCESS,
    default_tenant_id: str | None = None,
) -> None:
    app.add_middleware(
        MultiOrganizationTenantMiddleware,
        registry=registry,
        access=access,
        default_tenant_id=default_tenant_id,
    )
