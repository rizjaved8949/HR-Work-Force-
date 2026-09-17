"""Environment policy for Step 13 production hardening."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class ProductionSettings:
    app_env: str
    allowed_origins: tuple[str, ...]
    auth_enabled: bool
    step9_runtime_mode: str
    step9_allow_legacy_fallback: bool
    step12_default_tenant_open_access: bool
    expose_docs: bool
    force_https: bool
    trusted_hosts: tuple[str, ...]
    release_commit: str | None
    build_time: str | None
    require_nonempty_graph: bool
    require_supabase: bool

    @classmethod
    def from_env(cls) -> "ProductionSettings":
        return cls(
            app_env=os.getenv("APP_ENV", "development").strip().lower() or "development",
            allowed_origins=_csv("ALLOWED_ORIGINS", "*"),
            auth_enabled=_bool("AUTH_ENABLED", "false"),
            step9_runtime_mode=os.getenv("STEP9_RUNTIME_MODE", "legacy").strip().lower(),
            step9_allow_legacy_fallback=_bool("STEP9_ALLOW_LEGACY_FALLBACK", "true"),
            step12_default_tenant_open_access=_bool("STEP12_DEFAULT_TENANT_OPEN_ACCESS", "true"),
            expose_docs=_bool("STEP13_EXPOSE_DOCS", "true"),
            force_https=_bool("STEP13_FORCE_HTTPS", "false"),
            trusted_hosts=_csv("STEP13_TRUSTED_HOSTS", ""),
            release_commit=os.getenv("RELEASE_COMMIT", "").strip() or None,
            build_time=os.getenv("RELEASE_BUILD_TIME", "").strip() or None,
            require_nonempty_graph=_bool("STEP13_REQUIRE_NONEMPTY_GRAPH", "true"),
            require_supabase=_bool("STEP13_REQUIRE_SUPABASE", "true"),
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"
