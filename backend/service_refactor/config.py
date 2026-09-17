"""Environment configuration for Step 9 graph-first runtime wiring."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .models import RuntimeMode


@dataclass(frozen=True)
class Step9RuntimeConfig:
    mode: RuntimeMode = RuntimeMode.LEGACY
    tenant_id: str = "ORGANIZATION-001"
    allow_legacy_fallback: bool = True
    verify_graph_connectivity: bool = True

    @classmethod
    def from_env(cls) -> "Step9RuntimeConfig":
        raw_mode = os.getenv("STEP9_RUNTIME_MODE", "legacy").strip().lower()
        try:
            mode = RuntimeMode(raw_mode)
        except ValueError as error:
            raise RuntimeError(
                "STEP9_RUNTIME_MODE must be one of: legacy, graph_first, graph_only"
            ) from error

        raw_fallback = os.getenv("STEP9_ALLOW_LEGACY_FALLBACK", "true").strip().lower()
        allow_fallback = raw_fallback in {"1", "true", "yes", "y", "on"}
        if mode == RuntimeMode.GRAPH_ONLY:
            allow_fallback = False

        raw_verify = os.getenv("STEP9_VERIFY_GRAPH_CONNECTIVITY", "true").strip().lower()
        verify = raw_verify in {"1", "true", "yes", "y", "on"}

        tenant_id = os.getenv("STEP9_TENANT_ID", "ORGANIZATION-001").strip()
        if not tenant_id:
            raise RuntimeError("STEP9_TENANT_ID cannot be empty")

        return cls(
            mode=mode,
            tenant_id=tenant_id,
            allow_legacy_fallback=allow_fallback,
            verify_graph_connectivity=verify,
        )
