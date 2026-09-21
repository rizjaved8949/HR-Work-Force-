"""Property-preserving graph repository proxy used only by optional merge uploads."""
from __future__ import annotations

from typing import Any

from graph.models import GraphNode, GraphProvenance, GraphRelationship


def _merge_provenance(existing: list[GraphProvenance], incoming: list[GraphProvenance]) -> list[GraphProvenance]:
    result: list[GraphProvenance] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for item in [*existing, *incoming]:
        key = (
            item.source_system,
            item.source_object,
            item.source_record_key,
            item.mapping_version,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


class MergePreservingGraphRepository:
    """Delegate to a GraphRepository while preserving properties on sparse updates.

    Normal onboarding keeps its original replacement/upsert semantics.  This proxy
    is created only for the explicit Merge/Add flow so a partial row for an
    existing business identity updates supplied properties without deleting
    previously known properties that were not present in the patch file.
    """

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def __getattr__(self, name: str):
        return getattr(self.repository, name)

    def _merged_node(self, node: GraphNode) -> GraphNode:
        existing = self.repository.get_node(node.graph_id, node.tenant_id)
        if existing is None:
            return node
        if existing.entity_type != node.entity_type:
            raise ValueError(
                f"Cannot merge graph node {node.graph_id}: entity type changed "
                f"from {existing.entity_type} to {node.entity_type}"
            )
        return node.model_copy(
            update={
                "properties": {**existing.properties, **node.properties},
                "provenance": _merge_provenance(existing.provenance, node.provenance),
                "valid_from": node.valid_from or existing.valid_from,
                "valid_to": node.valid_to if node.valid_to is not None else existing.valid_to,
                "created_at": existing.created_at,
            }
        )

    def upsert_node(self, node: GraphNode) -> None:
        self.repository.upsert_node(self._merged_node(node))

    def upsert_nodes_bulk(self, nodes: list[GraphNode], *, batch_size: int = 500) -> int:
        merged = [self._merged_node(node) for node in nodes]
        bulk = getattr(self.repository, "upsert_nodes_bulk", None)
        if callable(bulk):
            return int(bulk(merged, batch_size=batch_size))
        for node in merged:
            self.repository.upsert_node(node)
        return len(merged)

    def _merged_relationship(self, edge: GraphRelationship) -> GraphRelationship:
        existing = self.repository.get_relationship(edge.graph_id, edge.tenant_id)
        if existing is None:
            return edge
        if (
            existing.relation_type != edge.relation_type
            or existing.source_graph_id != edge.source_graph_id
            or existing.target_graph_id != edge.target_graph_id
        ):
            raise ValueError(f"Cannot merge relationship {edge.graph_id}: endpoints/type changed")
        return edge.model_copy(
            update={
                "properties": {**existing.properties, **edge.properties},
                "provenance": _merge_provenance(existing.provenance, edge.provenance),
                "valid_from": edge.valid_from or existing.valid_from,
                "valid_to": edge.valid_to if edge.valid_to is not None else existing.valid_to,
                "created_at": existing.created_at,
            }
        )

    def upsert_relationship(self, relationship: GraphRelationship) -> None:
        self.repository.upsert_relationship(self._merged_relationship(relationship))

    def upsert_relationships_bulk(
        self, relationships: list[GraphRelationship], *, batch_size: int = 500
    ) -> int:
        merged = [self._merged_relationship(edge) for edge in relationships]
        bulk = getattr(self.repository, "upsert_relationships_bulk", None)
        if callable(bulk):
            return int(bulk(merged, batch_size=batch_size))
        for edge in merged:
            self.repository.upsert_relationship(edge)
        return len(merged)
