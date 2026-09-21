"""Configuration for the Knowledge-Graph-only runtime compatibility layer.

This layer is intentionally additive. Canonical employee/attrition reads still use
SemanticHRService directly. Deterministic services that currently expect tabular
files receive a transient tabular projection materialized *from* a reserved
Supabase graph mirror, never from the repository's Data directory at runtime.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_TRUE = {"1", "true", "yes", "y", "on"}


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


@dataclass(frozen=True)
class KGRuntimeConfig:
    data_source: str = "legacy"
    enforce_llm_graph_only: bool = False
    tenant_id: str = "ORGANIZATION-001"
    mirror_tenant_prefix: str = "__KG_RUNTIME__::"
    batch_size: int = 500
    cache_dir: Path = Path("/tmp/hr-workforce-kg-runtime")
    source_dir: Path = Path("Data")
    expose_source_metadata: bool = True

    @classmethod
    def from_env(cls) -> "KGRuntimeConfig":
        source = os.getenv("KG_RUNTIME_DATA_SOURCE", "legacy").strip().lower()
        if source not in {"legacy", "knowledge_graph"}:
            raise RuntimeError("KG_RUNTIME_DATA_SOURCE must be legacy or knowledge_graph")

        tenant_id = os.getenv("STEP9_TENANT_ID", "ORGANIZATION-001").strip()
        if not tenant_id:
            raise RuntimeError("STEP9_TENANT_ID cannot be empty")

        prefix = os.getenv("KG_RUNTIME_MIRROR_TENANT_PREFIX", "__KG_RUNTIME__::").strip()
        if not prefix:
            raise RuntimeError("KG_RUNTIME_MIRROR_TENANT_PREFIX cannot be empty")

        try:
            batch_size = int(os.getenv("KG_RUNTIME_BATCH_SIZE", "500"))
        except ValueError as exc:
            raise RuntimeError("KG_RUNTIME_BATCH_SIZE must be an integer") from exc
        if batch_size < 1:
            raise RuntimeError("KG_RUNTIME_BATCH_SIZE must be >= 1")

        cache_dir = Path(os.getenv("KG_RUNTIME_CACHE_DIR", "/tmp/hr-workforce-kg-runtime")).expanduser()
        source_dir = Path(os.getenv("KG_RUNTIME_BOOTSTRAP_SOURCE_DIR", "Data")).expanduser()

        return cls(
            data_source=source,
            enforce_llm_graph_only=_truthy("KG_LLM_GRAPH_ONLY", False),
            tenant_id=tenant_id,
            mirror_tenant_prefix=prefix,
            batch_size=batch_size,
            cache_dir=cache_dir,
            source_dir=source_dir,
            expose_source_metadata=_truthy("KG_EXPOSE_RUNTIME_SOURCE", True),
        )

    @property
    def enabled(self) -> bool:
        return self.data_source == "knowledge_graph"

    def mirror_tenant_id(self, tenant_id: str | None = None) -> str:
        target = str(tenant_id or self.tenant_id).strip()
        return f"{self.mirror_tenant_prefix}{target}"


DEFAULT_KG_RUNTIME_CONFIG = KGRuntimeConfig.from_env()
