"""Graph repository selection.

``GRAPH_BACKEND=supabase`` is the recommended deployment mode for the
Render + Supabase architecture. ``neo4j`` remains available as a reversible
compatibility option.
"""
from __future__ import annotations

import os
from typing import Any


def graph_backend_name() -> str:
    value = os.getenv("GRAPH_BACKEND", "supabase").strip().lower()
    aliases = {
        "postgres": "supabase",
        "postgresql": "supabase",
        "supabase_postgres": "supabase",
    }
    return aliases.get(value, value)


def create_graph_repository_from_env(*, verify_connectivity: bool = False) -> Any:
    backend = graph_backend_name()
    if backend == "supabase":
        from .supabase_repository import SupabaseGraphRepository

        repository = SupabaseGraphRepository.from_env()
    elif backend == "neo4j":
        from .neo4j_repository import Neo4jGraphRepository

        repository = Neo4jGraphRepository.from_env()
    else:
        raise RuntimeError(
            f"Unsupported GRAPH_BACKEND={backend!r}. Supported values: supabase, neo4j"
        )

    if verify_connectivity:
        verify = getattr(repository, "verify_connectivity", None)
        if callable(verify):
            verify()
    return repository
