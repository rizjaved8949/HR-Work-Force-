"""Authorization helpers for Step 12 organization membership and admin actions."""
from __future__ import annotations

import os
from typing import Any

from .models import ActorContext, OrganizationRecord


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def auth_enabled() -> bool:
    return _truthy(os.getenv("AUTH_ENABLED", "false"))


def _csv_env(name: str, default: str) -> set[str]:
    return {item.strip().lower() for item in os.getenv(name, default).split(",") if item.strip()}


class OrganizationAccessService:
    def __init__(self) -> None:
        self.global_admin_roles = _csv_env(
            "STEP12_GLOBAL_ADMIN_ROLES", "super_admin,platform_admin"
        )
        self.create_org_roles = _csv_env(
            "STEP12_CREATE_ORG_ROLES", "super_admin,platform_admin,admin,owner,hr_admin"
        )
        self.organization_admin_roles = {"owner", "admin", "hr_admin"}
        self.default_open_access = _truthy(
            os.getenv("STEP12_DEFAULT_TENANT_OPEN_ACCESS", "true")
        )

    @staticmethod
    def _field(user: Any, name: str) -> Any:
        if user is None:
            return None
        if isinstance(user, dict):
            return user.get(name)
        return getattr(user, name, None)

    def actor(self, user: Any = None) -> ActorContext:
        if not auth_enabled():
            return ActorContext(
                authenticated=False,
                user_id="local-dev",
                role="local_dev",
                local_development=True,
            )
        role = str(self._field(user, "role") or "").strip().lower() or None
        user_id = str(self._field(user, "id") or "").strip() or None
        return ActorContext(
            authenticated=user is not None,
            user_id=user_id,
            role=role,
            local_development=False,
        )

    def is_global_admin(self, actor: ActorContext) -> bool:
        return actor.local_development or bool(actor.role and actor.role in self.global_admin_roles)

    def can_create_organization(self, actor: ActorContext) -> bool:
        if actor.local_development:
            return True
        return bool(actor.authenticated and actor.role in self.create_org_roles)

    @staticmethod
    def membership_role(org: OrganizationRecord, actor: ActorContext) -> str | None:
        if not actor.user_id:
            return None
        for member in org.members:
            if member.user_id == actor.user_id:
                return member.role
        return None

    def can_access(self, org: OrganizationRecord, actor: ActorContext) -> bool:
        if actor.local_development or self.is_global_admin(actor):
            return True
        if not actor.authenticated:
            return False
        if org.is_default and org.legacy_default_access and self.default_open_access:
            return True
        return self.membership_role(org, actor) is not None

    def can_administer(self, org: OrganizationRecord, actor: ActorContext) -> bool:
        if self.is_global_admin(actor):
            return True
        return self.membership_role(org, actor) in self.organization_admin_roles


DEFAULT_ORGANIZATION_ACCESS = OrganizationAccessService()
