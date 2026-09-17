"""Environment-backed Step 11 UI integration configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Step11UIConfig:
    app_name: str = "HR Workforce Intelligence"
    ontology_studio_nav_enabled: bool = True
    reference_console_enabled: bool = True
    admin_roles: tuple[str, ...] = ("admin", "owner", "hr_admin", "super_admin")

    @classmethod
    def from_env(cls) -> "Step11UIConfig":
        app_name = os.getenv("STEP11_APP_NAME", "HR Workforce Intelligence").strip()
        if not app_name:
            raise RuntimeError("STEP11_APP_NAME cannot be empty")
        return cls(
            app_name=app_name,
            ontology_studio_nav_enabled=_bool("STEP11_ONTOLOGY_STUDIO_NAV", "true"),
            reference_console_enabled=_bool("STEP11_REFERENCE_CONSOLE", "true"),
            admin_roles=_csv(
                os.getenv(
                    "STEP11_ADMIN_ROLES",
                    os.getenv("ONTOLOGY_STUDIO_ADMIN_ROLES", "admin,owner,hr_admin,super_admin"),
                )
            ),
        )
