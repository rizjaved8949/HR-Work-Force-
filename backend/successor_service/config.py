from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from paths import ENV_FILE, REPO_ROOT, data_dir as default_data_dir


PACKAGE_ROOT = Path(__file__).resolve().parent

# The project has exactly one .env file, at the repository root.
load_dotenv(ENV_FILE)


def _resolve_path(value_name: str, default: str | Path) -> Path:
    raw_value = os.getenv(value_name)
    raw = Path(raw_value) if raw_value else Path(default)
    return raw if raw.is_absolute() else REPO_ROOT / raw


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    scoring_config_path: Path
    llm_enabled: bool
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    openrouter_timeout_seconds: float
    openrouter_max_tokens: int
    openrouter_http_referer: str
    openrouter_app_title: str


def get_settings(
    data_dir_override: str | Path | None = None,
) -> Settings:
    """Return local successor settings.

    data_dir_override is preferred so attrition and replacement can use
    exactly the same CSV folder from the main application.
    """

    if data_dir_override is not None:
        data_dir = Path(data_dir_override)
    else:
        data_dir = default_data_dir()

    scoring_config_path = _resolve_path(
        "SUCCESSOR_SCORING_CONFIG",
        PACKAGE_ROOT / "resources" / "scoring_config.json",
    )

    return Settings(
        data_dir=data_dir,
        scoring_config_path=scoring_config_path,
        # Disabled by default to avoid a second LLM call and reduce latency.
        llm_enabled=_env_bool("SUCCESSOR_LLM_ENABLED", False),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=os.getenv(
            "SUCCESSOR_OPENROUTER_BASE_URL",
            os.getenv(
                "OPENROUTER_BASE_URL",
                "https://openrouter.ai/api/v1",
            ),
        ).rstrip("/"),
        # The successor reasoning agent uses the same model as the main HR
        # agent unless .env overrides it. There is deliberately no hardcoded
        # model name: an empty value simply disables the LLM path and the
        # deterministic fallback reasons are used instead.
        openrouter_model=os.getenv(
            "SUCCESSOR_OPENROUTER_MODEL",
            os.getenv("OPENROUTER_MODEL", ""),
        ).strip(),
        openrouter_timeout_seconds=float(
            os.getenv("SUCCESSOR_OPENROUTER_TIMEOUT_SECONDS", "90")
        ),
        openrouter_max_tokens=int(
            os.getenv("SUCCESSOR_OPENROUTER_MAX_TOKENS", "900")
        ),
        openrouter_http_referer=os.getenv(
            "SUCCESSOR_OPENROUTER_HTTP_REFERER",
            "http://localhost:8000",
        ).strip(),
        openrouter_app_title=os.getenv(
            "SUCCESSOR_OPENROUTER_APP_TITLE",
            "Merged HR Workforce Intelligence Backend",
        ).strip(),
    )


def load_scoring_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    weights = config["weights"]
    total = sum(float(value) for value in weights.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            f"Scoring weights must total 1.0; found {total}"
        )

    return config
