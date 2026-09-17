"""Request-scoped organization/tenant context used by graph-native services."""
from __future__ import annotations

from contextvars import ContextVar, Token


_current_tenant: ContextVar[str | None] = ContextVar("hr_current_tenant", default=None)


def set_current_tenant(tenant_id: str) -> Token:
    return _current_tenant.set(str(tenant_id).strip())


def reset_current_tenant(token: Token) -> None:
    _current_tenant.reset(token)


def get_current_tenant(default: str | None = None) -> str | None:
    return _current_tenant.get() or default


def tenant_resolver(default_tenant_id: str):
    default = str(default_tenant_id).strip()

    def resolve() -> str:
        return str(get_current_tenant(default) or default)

    return resolve
