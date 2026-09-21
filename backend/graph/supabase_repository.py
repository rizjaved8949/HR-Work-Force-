"""Supabase/PostgreSQL implementation of the storage-neutral HR graph repository.

The existing HR source tables remain the system of record. This repository stores
an ontology-shaped *graph projection* in two Postgres tables:

- ``kg_nodes``
- ``kg_relationships``

The implementation deliberately preserves the same ``GraphRepository`` contract
used by Neo4j so SemanticHRService, feature resolution, Step-7 ingestion, and
multi-organization onboarding do not need to know which graph storage engine is
active.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from .models import GraphNode, GraphProvenance, GraphRelationship
from .repository import Direction
from .schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from .validator import DEFAULT_GRAPH_VALIDATOR, GraphModelValidator


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _provenance_payload(items: Iterable[GraphProvenance]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def _decode_provenance(raw: Any) -> list[GraphProvenance]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [GraphProvenance.model_validate(item) for item in raw]
    return []


def _node_row(node: GraphNode) -> dict[str, Any]:
    return {
        "tenant_id": node.tenant_id,
        "graph_id": node.graph_id,
        "entity_type": node.entity_type,
        "ontology_version": node.ontology_version,
        "properties": _json_value(node.properties),
        "provenance": _provenance_payload(node.provenance),
        "valid_from": _json_value(node.valid_from),
        "valid_to": _json_value(node.valid_to),
        "created_at": _json_value(node.created_at),
        "updated_at": _json_value(node.updated_at),
    }


def _relationship_row(edge: GraphRelationship) -> dict[str, Any]:
    return {
        "tenant_id": edge.tenant_id,
        "graph_id": edge.graph_id,
        "relation_type": edge.relation_type,
        "source_graph_id": edge.source_graph_id,
        "source_entity_type": edge.source_entity_type,
        "target_graph_id": edge.target_graph_id,
        "target_entity_type": edge.target_entity_type,
        "ontology_version": edge.ontology_version,
        "properties": _json_value(edge.properties),
        "provenance": _provenance_payload(edge.provenance),
        "valid_from": _json_value(edge.valid_from),
        "valid_to": _json_value(edge.valid_to),
        "created_at": _json_value(edge.created_at),
        "updated_at": _json_value(edge.updated_at),
    }


def _node_from_row(row: dict[str, Any]) -> GraphNode:
    return GraphNode(
        graph_id=str(row["graph_id"]),
        tenant_id=str(row["tenant_id"]),
        entity_type=str(row["entity_type"]),
        ontology_version=str(row.get("ontology_version") or ""),
        properties=dict(row.get("properties") or {}),
        provenance=_decode_provenance(row.get("provenance")),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _relationship_from_row(row: dict[str, Any]) -> GraphRelationship:
    return GraphRelationship(
        graph_id=str(row["graph_id"]),
        tenant_id=str(row["tenant_id"]),
        relation_type=str(row["relation_type"]),
        source_graph_id=str(row["source_graph_id"]),
        source_entity_type=str(row["source_entity_type"]),
        target_graph_id=str(row["target_graph_id"]),
        target_entity_type=str(row["target_entity_type"]),
        ontology_version=str(row.get("ontology_version") or ""),
        properties=dict(row.get("properties") or {}),
        provenance=_decode_provenance(row.get("provenance")),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


class SupabaseGraphRepository:
    """GraphRepository backed by two Supabase Postgres tables.

    The backend must use the Supabase service-role/admin client. RLS can remain
    enabled because the service role performs trusted tenant-scoped server-side
    access. The secret key must never be exposed to the browser.
    """

    def __init__(
        self,
        *,
        client: Any,
        nodes_table: str = "kg_nodes",
        relationships_table: str = "kg_relationships",
        schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
        validator: GraphModelValidator = DEFAULT_GRAPH_VALIDATOR,
    ) -> None:
        self.client = client
        self.nodes_table = nodes_table
        self.relationships_table = relationships_table
        self.schema = schema
        self.validator = validator

    @classmethod
    def from_env(cls) -> "SupabaseGraphRepository":
        import os
        from auth.supabase_client import get_supabase_admin_client

        return cls(
            client=get_supabase_admin_client(),
            nodes_table=os.getenv("SUPABASE_GRAPH_NODES_TABLE", "kg_nodes"),
            relationships_table=os.getenv(
                "SUPABASE_GRAPH_RELATIONSHIPS_TABLE", "kg_relationships"
            ),
        )

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return min(limit, 10_000)

    def verify_connectivity(self) -> None:
        # The table read verifies both Supabase connectivity and graph schema.
        self.client.table(self.nodes_table).select("graph_id").limit(1).execute()
        self.client.table(self.relationships_table).select("graph_id").limit(1).execute()

    def close(self) -> None:
        # supabase-py does not require a repository-level close operation.
        return None

    def install_schema(self) -> None:
        raise RuntimeError(
            "Supabase graph DDL is installed with backend/graph/sql/"
            "supabase_graph_schema.sql via the Supabase SQL Editor or psql."
        )

    def upsert_node(self, node: GraphNode) -> None:
        errors = [item for item in self.validator.validate_node(node) if item.severity == "error"]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))
        self.client.table(self.nodes_table).upsert(
            _node_row(node), on_conflict="tenant_id,graph_id"
        ).execute()

    def upsert_nodes_bulk(self, nodes: list[GraphNode], *, batch_size: int = 500) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        for node in nodes:
            errors = [item for item in self.validator.validate_node(node) if item.severity == "error"]
            if errors:
                raise ValueError("; ".join(item.message for item in errors))
        total = 0
        for start in range(0, len(nodes), batch_size):
            chunk = nodes[start : start + batch_size]
            self.client.table(self.nodes_table).upsert(
                [_node_row(node) for node in chunk],
                on_conflict="tenant_id,graph_id",
            ).execute()
            total += len(chunk)
        return total

    def get_node(self, graph_id: str, tenant_id: str) -> GraphNode | None:
        response = (
            self.client.table(self.nodes_table)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("graph_id", graph_id)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
        return _node_from_row(rows[0]) if rows else None

    def find_nodes(
        self,
        *,
        tenant_id: str,
        entity_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[GraphNode]:
        limit = self._validate_limit(limit)
        query = self.client.table(self.nodes_table).select("*").eq("tenant_id", tenant_id)
        if entity_type:
            query = query.eq("entity_type", entity_type)
        if property_filters:
            # PostgREST JSONB containment -> properties @> {...}
            query = query.contains("properties", _json_value(property_filters))
        response = query.order("graph_id").limit(limit).execute()
        return [_node_from_row(row) for row in (response.data or [])]

    def upsert_relationship(self, relationship: GraphRelationship) -> None:
        source = self.get_node(relationship.source_graph_id, relationship.tenant_id)
        target = self.get_node(relationship.target_graph_id, relationship.tenant_id)
        if source is None or target is None:
            raise ValueError("Relationship endpoints must exist in the same tenant before edge upsert")
        errors = [
            item
            for item in self.validator.validate_relationship(relationship, source, target)
            if item.severity == "error"
        ]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))
        self.client.table(self.relationships_table).upsert(
            _relationship_row(relationship), on_conflict="tenant_id,graph_id"
        ).execute()

    def upsert_relationships_bulk(
        self, relationships: list[GraphRelationship], *, batch_size: int = 500
    ) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        for relationship in relationships:
            errors = [
                item
                for item in self.validator.validate_relationship(relationship)
                if item.severity == "error"
            ]
            if errors:
                raise ValueError("; ".join(item.message for item in errors))
        total = 0
        for start in range(0, len(relationships), batch_size):
            chunk = relationships[start : start + batch_size]
            self.client.table(self.relationships_table).upsert(
                [_relationship_row(edge) for edge in chunk],
                on_conflict="tenant_id,graph_id",
            ).execute()
            total += len(chunk)
        return total

    def get_relationship(self, graph_id: str, tenant_id: str) -> GraphRelationship | None:
        response = (
            self.client.table(self.relationships_table)
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("graph_id", graph_id)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
        return _relationship_from_row(rows[0]) if rows else None

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
        query = (
            self.client.table(self.relationships_table)
            .select("*")
            .eq("tenant_id", tenant_id)
        )
        if source_graph_id:
            query = query.eq("source_graph_id", source_graph_id)
        if target_graph_id:
            query = query.eq("target_graph_id", target_graph_id)
        if relation_type:
            query = query.eq("relation_type", relation_type)
        response = query.order("graph_id").limit(limit).execute()
        return [_relationship_from_row(row) for row in (response.data or [])]

    def _nodes_by_ids(
        self,
        *,
        tenant_id: str,
        graph_ids: list[str],
        entity_type: str | None,
        limit: int,
    ) -> list[GraphNode]:
        if not graph_ids:
            return []
        query = (
            self.client.table(self.nodes_table)
            .select("*")
            .eq("tenant_id", tenant_id)
            .in_("graph_id", graph_ids)
        )
        if entity_type:
            query = query.eq("entity_type", entity_type)
        response = query.limit(limit).execute()
        by_id = {str(row["graph_id"]): _node_from_row(row) for row in (response.data or [])}
        # Preserve relationship traversal order while de-duplicating.
        result: list[GraphNode] = []
        seen: set[str] = set()
        for graph_id in graph_ids:
            node = by_id.get(graph_id)
            if node is not None and graph_id not in seen:
                seen.add(graph_id)
                result.append(node)
                if len(result) >= limit:
                    break
        return result

    def find_nodes_by_ids(
        self,
        *,
        tenant_id: str,
        graph_ids: list[str],
        limit: int = 500,
    ) -> list[GraphNode]:
        """Fetch a tenant-scoped set of nodes in one/few PostgREST calls.

        This is used by the management graph explorer. IDs are chunked so a
        large neighbourhood cannot create an excessively long URL.
        """
        limit = self._validate_limit(limit)
        wanted = list(dict.fromkeys(str(item) for item in graph_ids if item))[:limit]
        if not wanted:
            return []
        rows: list[dict[str, Any]] = []
        for start in range(0, len(wanted), 80):
            chunk = wanted[start : start + 80]
            response = (
                self.client.table(self.nodes_table)
                .select("*")
                .eq("tenant_id", tenant_id)
                .in_("graph_id", chunk)
                .execute()
            )
            rows.extend(response.data or [])
        by_id = {str(row["graph_id"]): _node_from_row(row) for row in rows}
        return [by_id[item] for item in wanted if item in by_id]

    def find_relationships_between_nodes(
        self,
        *,
        tenant_id: str,
        graph_ids: list[str],
        limit: int = 1200,
    ) -> list[GraphRelationship]:
        """Return relationships whose source *and* target are in ``graph_ids``.

        Two endpoint-indexed queries are used per chunk and merged by graph_id.
        This keeps the Ontology Studio live-data view fast without scanning the
        tenant's complete edge table.
        """
        limit = self._validate_limit(limit)
        ids = list(dict.fromkeys(str(item) for item in graph_ids if item))
        if not ids:
            return []
        id_set = set(ids)
        found: dict[str, GraphRelationship] = {}
        for start in range(0, len(ids), 60):
            chunk = ids[start : start + 60]
            for endpoint in ("source_graph_id", "target_graph_id"):
                response = (
                    self.client.table(self.relationships_table)
                    .select("*")
                    .eq("tenant_id", tenant_id)
                    .in_(endpoint, chunk)
                    .limit(limit)
                    .execute()
                )
                for row in response.data or []:
                    if (
                        str(row.get("source_graph_id")) in id_set
                        and str(row.get("target_graph_id")) in id_set
                    ):
                        found[str(row["graph_id"])] = _relationship_from_row(row)
                        if len(found) >= limit:
                            return list(found.values())
        return list(found.values())

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
            raise ValueError("direction must be 'out', 'in', or 'both'")

        ids: list[str] = []
        # Fetch a little more than the requested node limit because duplicate
        # edges can resolve to the same node.
        edge_limit = min(limit * 4, 10_000)
        if direction in {"out", "both"}:
            edges = self.find_relationships(
                tenant_id=tenant_id,
                source_graph_id=graph_id,
                relation_type=relation_type,
                limit=edge_limit,
            )
            ids.extend(edge.target_graph_id for edge in edges)
        if direction in {"in", "both"}:
            edges = self.find_relationships(
                tenant_id=tenant_id,
                target_graph_id=graph_id,
                relation_type=relation_type,
                limit=edge_limit,
            )
            ids.extend(edge.source_graph_id for edge in edges)
        return self._nodes_by_ids(
            tenant_id=tenant_id,
            graph_ids=ids,
            entity_type=entity_type,
            limit=limit,
        )

    def _count(self, table: str, tenant_id: str | None) -> int:
        query = self.client.table(table).select("graph_id", count="exact")
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        response = query.limit(1).execute()
        count = getattr(response, "count", None)
        if count is not None:
            return int(count)
        # Fallback for lightweight/fake clients.
        return len(response.data or [])

    def count_nodes(self, tenant_id: str | None = None) -> int:
        return self._count(self.nodes_table, tenant_id)

    def count_relationships(self, tenant_id: str | None = None) -> int:
        return self._count(self.relationships_table, tenant_id)
