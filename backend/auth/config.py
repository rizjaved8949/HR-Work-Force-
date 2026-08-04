"""Supabase authentication configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _split_csv(value: str) -> tuple[str, ...]:
    """Convert a comma-separated environment value into a tuple."""
    return tuple(
        item.strip()
        for item in value.split(",")
        if item.strip()
    )


@dataclass(frozen=True)
class AuthSettings:
    """Authentication settings loaded from environment variables."""

    enabled: bool
    supabase_url: str
    supabase_key: str
    public_paths: tuple[str, ...]
    public_prefixes: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        enabled = (
            os.getenv("AUTH_ENABLED", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )

        settings = cls(
            enabled=enabled,
            supabase_url=os.getenv(
                "SUPABASE_URL",
                "",
            ).strip(),
            supabase_key=os.getenv(
                "SUPABASE_PUBLISHABLE_KEY",
                "",
            ).strip(),
            public_paths=_split_csv(
                os.getenv(
                    "AUTH_PUBLIC_PATHS",
                    "/health,/openapi.json",
                )
            ),
            public_prefixes=_split_csv(
                os.getenv(
                    "AUTH_PUBLIC_PREFIXES",
                    "/docs,/redoc",
                )
            ),
        )

        if settings.enabled:
            settings.validate()

        return settings

    def validate(self) -> None:
        """Validate variables required when authentication is enabled."""
        missing_variables: list[str] = []

        if not self.supabase_url:
            missing_variables.append("SUPABASE_URL")

        if not self.supabase_key:
            missing_variables.append(
                "SUPABASE_PUBLISHABLE_KEY"
            )

        if missing_variables:
            missing_text = ", ".join(missing_variables)
            raise RuntimeError(
                "Missing authentication environment variables: "
                f"{missing_text}"
            )


auth_settings = AuthSettings.from_environment()