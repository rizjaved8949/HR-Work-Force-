"""In-memory graph repository used for graph and semantic-layer unit tests."""

from __future__ import annotations

from typing import Any

from .models import GraphNode, GraphRelationship
from .repository import Direction
from .validator import DEFAULT_GRAPH_VALIDATOR, GraphModelValidator


class InMemoryGraphRepository:
    def __init__(self, validator: GraphModelValidator = DEFAULT_GRAPH_VALIDATOR) -> None:
        self.validator = validator
        self.nodes: dict[str, GraphNode] = {}
        self.relationships: dict[str, GraphRelationship] = {}

    @staticmethod
    def _raise_on_errors(issues) -> None:
        errors = [item for item in issues if item.severity == "error"]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return min(limit, 10_000)

    def upsert_node(self, node: GraphNode) -> None:
        self._raise_on_errors(self.validator.validate_node(node))
        existing = self.nodes.get(node.graph_id)
        if existing is not None and existing.tenant_id != node.tenant_id:
            raise ValueError("graph_id collision across tenants")
        self.nodes[node.graph_id] = node

    def get_node(self, graph_id: str, tenant_id: str) -> GraphNode | None:
        node = self.nodes.get(graph_id)
        if node is None or node.tenant_id != tenant_id:
            return None
        return node

    def find_nodes(
        self,
        *,
        tenant_id: str,
        entity_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[GraphNode]:
        limit = self._validate_limit(limit)
        filters = property_filters or {}
        result: list[GraphNode] = []
        for node in sorted(self.nodes.values(), key=lambda item: item.graph_id):
            if node.tenant_id != tenant_id:
                continue
            if entity_type is not None and node.entity_type != entity_type:
                continue
            if any(node.properties.get(key) != value for key, value in filters.items()):
                continue
            result.append(node)
            if len(result) >= limit:
                break
        return result

    def upsert_relationship(self, relationship: GraphRelationship) -> None:
        source = self.nodes.get(relationship.source_graph_id)
        target = self.nodes.get(relationship.target_graph_id)
        if source is None or target is None:
            raise ValueError("Both relationship endpoint nodes must exist")
        self._raise_on_errors(
            self.validator.validate_relationship(relationship, source, target)
        )
        self.relationships[relationship.graph_id] = relationship

    def get_relationship(
        self, graph_id: str, tenant_id: str
    ) -> GraphRelationship | None:
        edge = self.relationships.get(graph_id)
        if edge is None or edge.tenant_id != tenant_id:
            return None
        return edge

    def find_relationships(
        self,
        *,
        tenant_id: str,
        source_graph_id: str | None = None,
        target_graph_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[GraphRelationship]:
        limit = self._validate_limit(limit)
        result: list[GraphRelationship] = []
        for edge in sorted(self.relationships.values(), key=lambda item: item.graph_id):
            if edge.tenant_id != tenant_id:
                continue
            if source_graph_id is not None and edge.source_graph_id != source_graph_id:
                continue
            if target_graph_id is not None and edge.target_graph_id != target_graph_id:
                continue
            if relation_type is not None and edge.relation_type != relation_type:
                continue
            result.append(edge)
            if len(result) >= limit:
                break
        return result

    def related_nodes(
        self,
        *,
        tenant_id: str,
        graph_id: str,
        relation_type: str | None = None,
        direction: Direction = "out",
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[GraphNode]:
        limit = self._validate_limit(limit)
        if direction not in {"out", "in", "both"}:
            raise ValueError("direction must be one of: out, in, both")
        seen: set[str] = set()
        result: list[GraphNode] = []
        for edge in sorted(self.relationships.values(), key=lambda item: item.graph_id):
            if edge.tenant_id != tenant_id:
                continue
            if relation_type is not None and edge.relation_type != relation_type:
                continue
            other_id: str | None = None
            if direction in {"out", "both"} and edge.source_graph_id == graph_id:
                other_id = edge.target_graph_id
            elif direction in {"in", "both"} and edge.target_graph_id == graph_id:
                other_id = edge.source_graph_id
            if other_id is None or other_id in seen:
                continue
            node = self.get_node(other_id, tenant_id)
            if node is None:
                continue
            if entity_type is not None and node.entity_type != entity_type:
                continue
            seen.add(other_id)
            result.append(node)
            if len(result) >= limit:
                break
        return result

    def count_nodes(self, tenant_id: str | None = None) -> int:
        if tenant_id is None:
            return len(self.nodes)
        return sum(item.tenant_id == tenant_id for item in self.nodes.values())

    def count_relationships(self, tenant_id: str | None = None) -> int:
        if tenant_id is None:
            return len(self.relationships)
        return sum(
            item.tenant_id == tenant_id for item in self.relationships.values()
        )
