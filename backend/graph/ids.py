"""Deterministic graph identifier helpers.

IDs are tenant-scoped so identical source identifiers in two organizations do
not collide. UUID5 is used so repeated ingestion is idempotent.
"""

from __future__ import annotations

from uuid import UUID, uuid5


GRAPH_NAMESPACE = UUID("962b2aa9-7a6e-4d7a-a0dd-38a9b8df5e74")


def _required(value: str, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def make_node_graph_id(*, tenant_id: str, entity_type: str, identity_key: str) -> str:
    tenant = _required(tenant_id, "tenant_id")
    entity = _required(entity_type, "entity_type")
    key = _required(identity_key, "identity_key")
    return str(uuid5(GRAPH_NAMESPACE, f"node|{tenant}|{entity}|{key}"))


def make_source_record_identity(
    *, source_system: str, source_object: str, source_record_key: str
) -> str:
    system = _required(source_system, "source_system")
    obj = _required(source_object, "source_object")
    key = _required(source_record_key, "source_record_key")
    return f"source-record|{system}|{obj}|{key}"


def make_relationship_graph_id(
    *,
    tenant_id: str,
    source_graph_id: str,
    relation_type: str,
    target_graph_id: str,
) -> str:
    tenant = _required(tenant_id, "tenant_id")
    source = _required(source_graph_id, "source_graph_id")
    relation = _required(relation_type, "relation_type")
    target = _required(target_graph_id, "target_graph_id")
    return str(
        uuid5(
            GRAPH_NAMESPACE,
            f"edge|{tenant}|{source}|{relation}|{target}",
        )
    )
