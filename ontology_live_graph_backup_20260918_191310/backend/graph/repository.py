"""Storage abstraction for the HR Knowledge Graph.

Step 5 extends the Step-4 write/count contract with storage-neutral reads used
by the Semantic HR Service. Callers must always provide a tenant_id.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from .models import GraphNode, GraphRelationship


Direction = Literal["out", "in", "both"]


class GraphRepository(Protocol):
    def upsert_node(self, node: GraphNode) -> None: ...

    def get_node(self, graph_id: str, tenant_id: str) -> GraphNode | None: ...

    def find_nodes(
        self,
        *,
        tenant_id: str,
        entity_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[GraphNode]: ...

    def upsert_relationship(self, relationship: GraphRelationship) -> None: ...

    def get_relationship(
        self, graph_id: str, tenant_id: str
    ) -> GraphRelationship | None: ...

    def find_relationships(
        self,
        *,
        tenant_id: str,
        source_graph_id: str | None = None,
        target_graph_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[GraphRelationship]: ...

    def related_nodes(
        self,
        *,
        tenant_id: str,
        graph_id: str,
        relation_type: str | None = None,
        direction: Direction = "out",
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[GraphNode]: ...

    def count_nodes(self, tenant_id: str | None = None) -> int: ...

    def count_relationships(self, tenant_id: str | None = None) -> int: ...
