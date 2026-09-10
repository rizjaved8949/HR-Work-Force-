"""Every language-model setting, read from the single project .env.

No model name, key, or tuning value is hardcoded anywhere in the codebase.
Changing `.env` is the only way to change which model the agent uses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from paths import ENV_FILE


# Loaded once, at import time. `override=False` means a value already
# exported in the real environment wins over the file, which is the normal
# expectation for containers and CI.
load_dotenv(ENV_FILE, override=False)


class MissingConfigurationError(RuntimeError):
    """A required .env value is absent or blank."""


def require_env(variable_name: str) -> str:
    """Return a required .env value, or fail with an actionable message."""

    value = os.getenv(variable_name)

    if value is None or not value.strip():
        raise MissingConfigurationError(
            f"{variable_name} is missing from {ENV_FILE}. "
            f"Add a line such as: {variable_name}=<value>"
        )

    return value.strip()


def _env_str(variable_name: str, default: str) -> str:
    value = os.getenv(variable_name)
    return value.strip() if value and value.strip() else default


def _env_float(variable_name: str, default: float) -> float:
    raw = os.getenv(variable_name)

    if raw is None or not raw.strip():
        return default

    try:
        return float(raw)
    except ValueError as error:
        raise MissingConfigurationError(
            f"{variable_name} must be a number; found {raw!r}."
        ) from error


def _env_int(variable_name: str, default: int) -> int:
    raw = os.getenv(variable_name)

    if raw is None or not raw.strip():
        return default

    try:
        return int(raw)
    except ValueError as error:
        raise MissingConfigurationError(
            f"{variable_name} must be a whole number; found {raw!r}."
        ) from error


@dataclass(frozen=True)
class LLMSettings:
    """OpenRouter configuration for the main HR reasoning agent."""

    api_key: str
    model: str
    fallback_models: tuple[str, ...]
    base_url: str
    temperature: float
    max_tokens: int
    max_retries: int
    timeout_seconds: float
    reasoning: str

    def extra_body(self) -> dict:
        """OpenRouter-specific request options."""

        body: dict = {}
        setting = self.reasoning.lower()

        if setting == "off":
            body["reasoning"] = {"enabled": False}
        elif setting in {"low", "medium", "high"}:
            body["reasoning"] = {"effort": setting}

        if self.fallback_models:
            body["models"] = list(self.fallback_models)

        return body


def get_llm_settings() -> LLMSettings:
    """Build the agent's model configuration from .env.

    `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are required so a typo or a
    missing line fails loudly at startup instead of silently falling back to
    some other model.
    """

    fallback_models = tuple(
        model.strip()
        for model in os.getenv("OPENROUTER_FALLBACK_MODELS", "").split(",")
        if model.strip()
    )

    return LLMSettings(
    api_key=require_env("OPENROUTER_API_KEY"),
    model=require_env("OPENROUTER_MODEL"),

    fallback_models=tuple(
        model
        for model in (
            _env_str("OPENROUTER_FALLBACK_MODEL_1", ""),
            _env_str("OPENROUTER_FALLBACK_MODEL_2", ""),
        )
        if model
    ),

    base_url=_env_str(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
    ).rstrip("/"),

    temperature=_env_float(
        "OPENROUTER_TEMPERATURE",
        0.0,
    ),

    max_tokens=_env_int(
        "OPENROUTER_MAX_TOKENS",
        600,
    ),

    max_retries=_env_int(
        "OPENROUTER_MAX_RETRIES",
        0,
    ),

    timeout_seconds=_env_float(
        "OPENROUTER_TIMEOUT_SECONDS",
        40.0,
    ),

    reasoning=_env_str(
        "OPENROUTER_REASONING",
        "off",
    ).lower(),
)
