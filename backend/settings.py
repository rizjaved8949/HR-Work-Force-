"""LLM configuration from environment variables and the project .env.

LLM_PROVIDER=auto (the default) selects OpenRouter on Render and Ollama
elsewhere. Set LLM_PROVIDER=ollama or openrouter to select explicitly.
Real environment variables always take precedence over the project .env.
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
    """A required configuration value is absent, blank, or invalid."""


def require_env(variable_name: str) -> str:
    """Return a required environment value, or fail with an actionable message."""

    value = os.getenv(variable_name)

    if value is None or not value.strip():
        raise MissingConfigurationError(
            f"{variable_name} is missing or blank. Set it in the process "
            f"environment (Render: Environment) or in {ENV_FILE}."
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
    """Selected provider configuration for the main HR reasoning agent."""

    api_key: str
    model: str
    fallback_models: tuple[str, ...]
    base_url: str
    temperature: float
    max_tokens: int
    max_retries: int
    timeout_seconds: float
    reasoning: str
    # Keep the original constructor fields/order compatible with other callers.
    provider: str = "openrouter"

    def extra_body(self) -> dict:
        """Return OpenRouter options only for OpenRouter requests."""

        if self.provider != "openrouter":
            return {}

        body: dict = {}
        setting = self.reasoning.lower()

        if setting == "off":
            body["reasoning"] = {"enabled": False}
        elif setting in {"low", "medium", "high"}:
            body["reasoning"] = {"effort": setting}

        if self.fallback_models:
            body["models"] = list(self.fallback_models)

        return body


def get_llm_provider() -> str:
    """Resolve the provider for this backend process, without network probes."""

    provider = _env_str("LLM_PROVIDER", "auto").lower()

    if provider == "auto":
        # Render documents RENDER=true as its runtime detection flag.
        return (
            "openrouter"
            if _env_str("RENDER", "false").lower() == "true"
            else "ollama"
        )

    if provider not in {"ollama", "openrouter"}:
        raise MissingConfigurationError(
            "LLM_PROVIDER must be one of: auto, ollama, openrouter."
        )

    return provider


def get_llm_settings() -> LLMSettings:
    """Read only the selected provider's settings; never switch on failure."""

    provider = get_llm_provider()

    if provider == "openrouter":
        fallback_models = tuple(
            model
            for name in ("OPENROUTER_FALLBACK_MODEL_1", "OPENROUTER_FALLBACK_MODEL_2")
            if (model := _env_str(name, ""))
        )
        return LLMSettings(
            api_key=require_env("OPENROUTER_API_KEY"),
            model=require_env("OPENROUTER_MODEL"),
            fallback_models=fallback_models,
            base_url=_env_str(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ).rstrip("/"),
            temperature=_env_float("OPENROUTER_TEMPERATURE", 0.0),
            max_tokens=_env_int("OPENROUTER_MAX_TOKENS", 1200),
            max_retries=_env_int("OPENROUTER_MAX_RETRIES", 3),
            timeout_seconds=_env_float("OPENROUTER_TIMEOUT_SECONDS", 120),
            reasoning=_env_str("OPENROUTER_REASONING", "off"),
            provider=provider,
        )

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
        provider=provider,
    )
