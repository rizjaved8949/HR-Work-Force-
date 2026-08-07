"""Supabase authentication configuration."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(
    dotenv_path=ENV_FILE,
    override=True,
)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in value.split(",")
        if item.strip()
    )


def _read_boolean(
    name: str,
    default: str = "false",
) -> bool:
    return (
        os.getenv(name, default).strip().lower()
        in {"1", "true", "yes", "on"}
    )


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool

    supabase_url: str
    supabase_key: str
    supabase_secret_key: str

    public_paths: tuple[str, ...]
    public_prefixes: tuple[str, ...]

    email_verify_redirect_url: str
    password_reset_redirect_url: str

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        settings = cls(
            enabled=_read_boolean("AUTH_ENABLED"),

            supabase_url=os.getenv(
                "SUPABASE_URL",
                "",
            ).strip(),

            supabase_key=os.getenv(
                "SUPABASE_PUBLISHABLE_KEY",
                "",
            ).strip(),

            supabase_secret_key=os.getenv(
                "SUPABASE_SECRET_KEY",
                "",
            ).strip(),

            public_paths=_split_csv(
                os.getenv(
                    "AUTH_PUBLIC_PATHS",
                    (
                        "/health,"
                        "/openapi.json,"
                        "/auth/signup,"
                        "/auth/login,"
                        "/auth/resend-verification,"
                        "/auth/forgot-password"
                    ),
                )
            ),

            public_prefixes=_split_csv(
                os.getenv(
                    "AUTH_PUBLIC_PREFIXES",
                    "/docs,/redoc",
                )
            ),

            email_verify_redirect_url=os.getenv(
                "AUTH_EMAIL_VERIFY_REDIRECT_URL",
                "",
            ).strip(),

            password_reset_redirect_url=os.getenv(
                "AUTH_PASSWORD_RESET_REDIRECT_URL",
                "",
            ).strip(),
        )

        if settings.enabled:
            settings.validate()

        return settings

    def validate(self) -> None:
        missing: list[str] = []

        if not self.supabase_url:
            missing.append("SUPABASE_URL")

        if not self.supabase_key:
            missing.append(
                "SUPABASE_PUBLISHABLE_KEY"
            )

        if not self.supabase_secret_key:
            missing.append(
                "SUPABASE_SECRET_KEY"
            )

        if not self.email_verify_redirect_url:
            missing.append(
                "AUTH_EMAIL_VERIFY_REDIRECT_URL"
            )

        if not self.password_reset_redirect_url:
            missing.append(
                "AUTH_PASSWORD_RESET_REDIRECT_URL"
            )

        if missing:
            raise RuntimeError(
                "Missing authentication environment variables: "
                + ", ".join(missing)
            )


auth_settings = AuthSettings.from_environment()