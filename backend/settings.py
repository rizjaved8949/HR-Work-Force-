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
    """Build Ollama model configuration from .env."""

    return LLMSettings(
        api_key=require_env("OLLAMA_API_KEY"),

        model=require_env("OLLAMA_MODEL"),

        # Ollama does not support OpenRouter fallback models
        fallback_models=(),

        base_url=_env_str(
            "OLLAMA_BASE_URL",
            "http://localhost:11434/v1",
        ).rstrip("/"),

        temperature=_env_float(
            "OLLAMA_TEMPERATURE",
            0.2,
        ),

        max_tokens=_env_int(
            "OLLAMA_MAX_TOKENS",
            700,
        ),

        max_retries=_env_int(
            "OLLAMA_MAX_RETRIES",
            1,
        ),

        timeout_seconds=_env_float(
            "OLLAMA_TIMEOUT_SECONDS",
            120,
        ),

        # Ollama does not use OpenRouter reasoning parameter
        reasoning="off",
    )