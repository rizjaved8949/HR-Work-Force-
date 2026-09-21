"""Runtime source metadata shared by HTTP responses and status APIs."""
from __future__ import annotations

from typing import Any

from graph.factory import graph_backend_name

from .config import KGRuntimeConfig
from .materializer import GraphRuntimeMaterializer
from .store import SupabaseRuntimeGraphStore


def runtime_source_metadata(config: KGRuntimeConfig | None = None) -> dict[str, Any]:
    cfg = config or KGRuntimeConfig.from_env()
    if cfg.enabled:
        source = "knowledge_graph"
        compatibility = "knowledge_graph_runtime_projection"
    else:
        source = "legacy"
        compatibility = "legacy_csv"
    return {
        "data_source": source,
        "graph_backend": graph_backend_name(),
        "tenant_id": cfg.tenant_id,
        "llm_graph_only": bool(cfg.enforce_llm_graph_only and cfg.enabled),
        "compatibility_source": compatibility,
    }


def runtime_status(config: KGRuntimeConfig | None = None) -> dict[str, Any]:
    cfg = config or KGRuntimeConfig.from_env()
    payload = runtime_source_metadata(cfg)
    payload["mode"] = "graph_only" if cfg.enforce_llm_graph_only and cfg.enabled else cfg.data_source
    if not cfg.enabled:
        payload.update({
            "mirror_tenant_id": None,
            "mirror_dataset_count": 0,
            "mirror_row_count": 0,
            "legacy_source_read_at_runtime": True,
        })
        return payload

    store = SupabaseRuntimeGraphStore.from_env(cfg)
    materializer = GraphRuntimeMaterializer(config=cfg, store=store)
    mirror = materializer.status()
    payload.update({
        "mirror_tenant_id": mirror["mirror_tenant_id"],
        "mirror_dataset_count": mirror["dataset_count"],
        "mirror_row_count": mirror["row_count"],
        "legacy_source_read_at_runtime": mirror["legacy_source_read_at_runtime"],
        "cache_dir": mirror["cache_dir"],
        "secondary_tenant_full_chat_safe": False,
        "secondary_tenant_note": (
            "Step-12 safety block remains in place for full chat on secondary tenants until "
            "the deterministic compatibility services become request-tenant scoped."
        ),
        "service_sources": {
            "employee_record_retrieval": "canonical_knowledge_graph",
            "attrition_prediction": "canonical_knowledge_graph",
            "employee_performance": "knowledge_graph_runtime_projection",
            "headcount_management": "knowledge_graph_runtime_projection",
            "scenario_simulation": "knowledge_graph_runtime_projection",
            "successor_replacement": "knowledge_graph_runtime_projection",
            "decision_cases": "knowledge_graph_runtime_projection_plus_workflow_state",
        },
    })
    return payload
