"""Neo4j implementation of the storage-neutral HR graph repository.

The Neo4j driver is imported lazily so the existing application does not gain a
startup dependency on Neo4j unless this repository is explicitly instantiated.
Step 5 adds typed reads/query operations used by the Semantic HR Service.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .models import GraphNode, GraphProvenance, GraphRelationship
from .repository import Direction
from .schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from .validator import DEFAULT_GRAPH_VALIDATOR, GraphModelValidator


_SAFE_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NODE_META = {
    "kg_graph_id",
    "kg_tenant_id",
    "kg_entity_type",
    "kg_ontology_version",
    "kg_provenance_json",
    "kg_valid_from",
    "kg_valid_to",
    "kg_created_at",
    "kg_updated_at",
}
_EDGE_META = {
    "kg_graph_id",
    "kg_tenant_id",
    "kg_ontology_version",
    "kg_provenance_json",
    "kg_valid_from",
    "kg_valid_to",
    "kg_created_at",
    "kg_updated_at",
}


def _safe_token(value: str, kind: str) -> str:
    if not _SAFE_TOKEN.fullmatch(value):
        raise ValueError(f"Unsafe {kind}: {value!r}")
    return value


def _serialize_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


def _decode_provenance(raw: Any) -> list[GraphProvenance]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [GraphProvenance.model_validate(item) for item in raw]


def _node_properties(node: GraphNode) -> dict:
    result = {key: _serialize_value(value) for key, value in node.properties.items()}
    result.update(
        {
            "kg_graph_id": node.graph_id,
            "kg_tenant_id": node.tenant_id,
            "kg_entity_type": node.entity_type,
            "kg_ontology_version": node.ontology_version,
            "kg_provenance_json": json.dumps(
                [item.model_dump(mode="json") for item in node.provenance]
            ),
            "kg_valid_from": _serialize_value(node.valid_from),
            "kg_valid_to": _serialize_value(node.valid_to),
            "kg_created_at": _serialize_value(node.created_at),
            "kg_updated_at": _serialize_value(node.updated_at),
        }
    )
    return result


def _relationship_properties(edge: GraphRelationship) -> dict:
    result = {key: _serialize_value(value) for key, value in edge.properties.items()}
    result.update(
        {
            "kg_graph_id": edge.graph_id,
            "kg_tenant_id": edge.tenant_id,
            "kg_ontology_version": edge.ontology_version,
            "kg_provenance_json": json.dumps(
                [item.model_dump(mode="json") for item in edge.provenance]
            ),
            "kg_valid_from": _serialize_value(edge.valid_from),
            "kg_valid_to": _serialize_value(edge.valid_to),
            "kg_created_at": _serialize_value(edge.created_at),
            "kg_updated_at": _serialize_value(edge.updated_at),
        }
    )
    return result


def _graph_node_from_mapping(raw: Any) -> GraphNode:
    data = dict(raw)
    properties = {key: value for key, value in data.items() if key not in _NODE_META}
    return GraphNode(
        graph_id=str(data.get("kg_graph_id", "")),
        tenant_id=str(data.get("kg_tenant_id", "")),
        entity_type=str(data.get("kg_entity_type", "")),
        ontology_version=str(data.get("kg_ontology_version", "")),
        properties=properties,
        provenance=_decode_provenance(data.get("kg_provenance_json")),
        valid_from=data.get("kg_valid_from"),
        valid_to=data.get("kg_valid_to"),
        created_at=data.get("kg_created_at"),
        updated_at=data.get("kg_updated_at"),
    )


def _graph_relationship_from_record(record: Any) -> GraphRelationship:
    props = dict(record["properties"] or {})
    relationship_properties = {
        key: value for key, value in props.items() if key not in _EDGE_META
    }
    return GraphRelationship(
        graph_id=str(props.get("kg_graph_id", "")),
        tenant_id=str(props.get("kg_tenant_id", "")),
        relation_type=str(record["relation_type"]),
        source_graph_id=str(record["source_graph_id"]),
        source_entity_type=str(record["source_entity_type"]),
        target_graph_id=str(record["target_graph_id"]),
        target_entity_type=str(record["target_entity_type"]),
        ontology_version=str(props.get("kg_ontology_version", "")),
        properties=relationship_properties,
        provenance=_decode_provenance(props.get("kg_provenance_json")),
        valid_from=props.get("kg_valid_from"),
        valid_to=props.get("kg_valid_to"),
        created_at=props.get("kg_created_at"),
        updated_at=props.get("kg_updated_at"),
    )


class Neo4jGraphRepository:
    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
        schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
        validator: GraphModelValidator = DEFAULT_GRAPH_VALIDATOR,
    ) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as error:
            raise RuntimeError(
                "Neo4j driver is not installed. Run: python -m pip install neo4j"
            ) from error

        self.schema = schema
        self.validator = validator
        self.database = database
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    @classmethod
    def from_env(cls) -> "Neo4jGraphRepository":
        import os

        required = {
            "NEO4J_URI": os.getenv("NEO4J_URI"),
            "NEO4J_USERNAME": os.getenv("NEO4J_USERNAME"),
            "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing Neo4j environment variables: {', '.join(missing)}")
        return cls(
            uri=str(required["NEO4J_URI"]),
            username=str(required["NEO4J_USERNAME"]),
            password=str(required["NEO4J_PASSWORD"]),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return min(limit, 10_000)

    def verify_connectivity(self) -> None:
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    def install_schema(self) -> None:
        with self.driver.session(database=self.database) as session:
            for statement in self.schema.neo4j_schema_statements():
                session.run(statement).consume()

    def upsert_node(self, node: GraphNode) -> None:
        errors = [item for item in self.validator.validate_node(node) if item.severity == "error"]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))
        label = _safe_token(node.entity_type, "node label")
        query = (
            f"MERGE (n:KGNode:{label} {{kg_graph_id: $graph_id}}) "
            "SET n += $properties"
        )
        with self.driver.session(database=self.database) as session:
            session.run(
                query,
                graph_id=node.graph_id,
                properties=_node_properties(node),
            ).consume()


    def upsert_nodes_bulk(self, nodes: list[GraphNode], *, batch_size: int = 1000) -> int:
        """Efficient idempotent node upserts grouped by entity label."""
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        grouped: dict[str, list[GraphNode]] = {}
        for node in nodes:
            errors = [item for item in self.validator.validate_node(node) if item.severity == "error"]
            if errors:
                raise ValueError("; ".join(item.message for item in errors))
            grouped.setdefault(node.entity_type, []).append(node)
        written = 0
        with self.driver.session(database=self.database) as session:
            for entity_type, items in grouped.items():
                label = _safe_token(entity_type, "node label")
                query = (
                    f"UNWIND $rows AS row "
                    f"MERGE (n:KGNode:{label} {{kg_graph_id: row.graph_id}}) "
                    "SET n += row.properties"
                )
                for start in range(0, len(items), batch_size):
                    chunk = items[start:start + batch_size]
                    rows = [
                        {"graph_id": item.graph_id, "properties": _node_properties(item)}
                        for item in chunk
                    ]
                    session.run(query, rows=rows).consume()
                    written += len(chunk)
        return written

    def upsert_relationships_bulk(
        self, relationships: list[GraphRelationship], *, batch_size: int = 1000
    ) -> int:
        """Efficient idempotent relationship upserts grouped by relationship type."""
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        grouped: dict[str, list[GraphRelationship]] = {}
        for edge in relationships:
            errors = [
                item for item in self.validator.validate_relationship(edge)
                if item.severity == "error"
            ]
            if errors:
                raise ValueError("; ".join(item.message for item in errors))
            grouped.setdefault(edge.relation_type, []).append(edge)
        written = 0
        with self.driver.session(database=self.database) as session:
            for relation_type, items in grouped.items():
                relation = _safe_token(relation_type, "relationship type")
                query = (
                    "UNWIND $rows AS row "
                    "MATCH (a:KGNode {kg_graph_id: row.source_graph_id, kg_tenant_id: row.tenant_id}) "
                    "MATCH (b:KGNode {kg_graph_id: row.target_graph_id, kg_tenant_id: row.tenant_id}) "
                    f"MERGE (a)-[r:{relation} {{kg_graph_id: row.graph_id}}]->(b) "
                    "SET r += row.properties"
                )
                for start in range(0, len(items), batch_size):
                    chunk = items[start:start + batch_size]
                    rows = [
                        {
                            "graph_id": item.graph_id,
                            "source_graph_id": item.source_graph_id,
                            "target_graph_id": item.target_graph_id,
                            "tenant_id": item.tenant_id,
                            "properties": _relationship_properties(item),
                        }
                        for item in chunk
                    ]
                    summary = session.run(query, rows=rows).consume()
                    # Endpoint integrity is preflight-validated; a missing endpoint at this
                    # stage indicates concurrent mutation or an unexpected DB state.
                    written += len(chunk)
        return written

    def get_node(self, graph_id: str, tenant_id: str) -> GraphNode | None:
        query = (
            "MATCH (n:KGNode {kg_graph_id: $graph_id, kg_tenant_id: $tenant_id}) "
            "RETURN n LIMIT 1"
        )
        with self.driver.session(database=self.database) as session:
            record = session.run(query, graph_id=graph_id, tenant_id=tenant_id).single()
            return _graph_node_from_mapping(record["n"]) if record else None

    def find_nodes(
        self,
        *,
        tenant_id: str,
        entity_type: str | None = None,
        property_filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[GraphNode]:
        limit = self._validate_limit(limit)
        label_suffix = ""
        if entity_type is not None:
            self.schema.ontology_registry.get_entity(entity_type)
            label_suffix = ":" + _safe_token(entity_type, "node label")

        clauses = ["n.kg_tenant_id = $tenant_id"]
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        for index, (key, value) in enumerate((property_filters or {}).items()):
            property_name = _safe_token(key, "property name")
            param_name = f"filter_{index}"
            if value is None:
                clauses.append(f"n.{property_name} IS NULL")
            else:
                clauses.append(f"n.{property_name} = ${param_name}")
                params[param_name] = _serialize_value(value)

        query = (
            f"MATCH (n:KGNode{label_suffix}) "
            f"WHERE {' AND '.join(clauses)} "
            "RETURN n ORDER BY n.kg_graph_id LIMIT $limit"
        )
        with self.driver.session(database=self.database) as session:
            return [
                _graph_node_from_mapping(record["n"])
                for record in session.run(query, **params)
            ]

    def upsert_relationship(self, relationship: GraphRelationship) -> None:
        errors = [
            item
            for item in self.validator.validate_relationship(relationship)
            if item.severity == "error"
        ]
        if errors:
            raise ValueError("; ".join(item.message for item in errors))
        relation = _safe_token(relationship.relation_type, "relationship type")
        query = (
            "MATCH (a:KGNode {kg_graph_id: $source_graph_id, kg_tenant_id: $tenant_id}) "
            "MATCH (b:KGNode {kg_graph_id: $target_graph_id, kg_tenant_id: $tenant_id}) "
            f"MERGE (a)-[r:{relation} {{kg_graph_id: $edge_graph_id}}]->(b) "
            "SET r += $properties"
        )
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                source_graph_id=relationship.source_graph_id,
                target_graph_id=relationship.target_graph_id,
                tenant_id=relationship.tenant_id,
                edge_graph_id=relationship.graph_id,
                properties=_relationship_properties(relationship),
            )
            summary = result.consume()
            if summary.counters.relationships_created == 0 and summary.counters.properties_set == 0:
                raise ValueError("Relationship endpoints were not found for this tenant")

    def get_relationship(self, graph_id: str, tenant_id: str) -> GraphRelationship | None:
        query = (
            "MATCH (a:KGNode)-[r]->(b:KGNode) "
            "WHERE r.kg_graph_id = $graph_id AND r.kg_tenant_id = $tenant_id "
            "RETURN properties(r) AS properties, type(r) AS relation_type, "
            "a.kg_graph_id AS source_graph_id, a.kg_entity_type AS source_entity_type, "
            "b.kg_graph_id AS target_graph_id, b.kg_entity_type AS target_entity_type "
            "LIMIT 1"
        )
        with self.driver.session(database=self.database) as session:
            record = session.run(query, graph_id=graph_id, tenant_id=tenant_id).single()
            return _graph_relationship_from_record(record) if record else None

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
        relation_suffix = ""
        if relation_type is not None:
            relation_suffix = ":" + _safe_token(relation_type, "relationship type")
        clauses = ["r.kg_tenant_id = $tenant_id"]
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        if source_graph_id is not None:
            clauses.append("a.kg_graph_id = $source_graph_id")
            params["source_graph_id"] = source_graph_id
        if target_graph_id is not None:
            clauses.append("b.kg_graph_id = $target_graph_id")
            params["target_graph_id"] = target_graph_id
        query = (
            f"MATCH (a:KGNode)-[r{relation_suffix}]->(b:KGNode) "
            f"WHERE {' AND '.join(clauses)} "
            "RETURN properties(r) AS properties, type(r) AS relation_type, "
            "a.kg_graph_id AS source_graph_id, a.kg_entity_type AS source_entity_type, "
            "b.kg_graph_id AS target_graph_id, b.kg_entity_type AS target_entity_type "
            "ORDER BY r.kg_graph_id LIMIT $limit"
        )
        with self.driver.session(database=self.database) as session:
            return [
                _graph_relationship_from_record(record)
                for record in session.run(query, **params)
            ]

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
        relation_suffix = ""
        if relation_type is not None:
            relation_suffix = ":" + _safe_token(relation_type, "relationship type")
        target_suffix = ""
        if entity_type is not None:
            self.schema.ontology_registry.get_entity(entity_type)
            target_suffix = ":" + _safe_token(entity_type, "node label")

        if direction == "out":
            pattern = f"(s:KGNode)-[r{relation_suffix}]->(n:KGNode{target_suffix})"
        elif direction == "in":
            pattern = f"(s:KGNode)<-[r{relation_suffix}]-(n:KGNode{target_suffix})"
        else:
            pattern = f"(s:KGNode)-[r{relation_suffix}]-(n:KGNode{target_suffix})"

        query = (
            f"MATCH {pattern} "
            "WHERE s.kg_graph_id = $graph_id AND s.kg_tenant_id = $tenant_id "
            "AND n.kg_tenant_id = $tenant_id AND r.kg_tenant_id = $tenant_id "
            "RETURN DISTINCT n ORDER BY n.kg_graph_id LIMIT $limit"
        )
        with self.driver.session(database=self.database) as session:
            return [
                _graph_node_from_mapping(record["n"])
                for record in session.run(
                    query, graph_id=graph_id, tenant_id=tenant_id, limit=limit
                )
            ]

    def count_nodes(self, tenant_id: str | None = None) -> int:
        query = "MATCH (n:KGNode)"
        params = {}
        if tenant_id is not None:
            query += " WHERE n.kg_tenant_id = $tenant_id"
            params["tenant_id"] = tenant_id
        query += " RETURN count(n) AS count"
        with self.driver.session(database=self.database) as session:
            record = session.run(query, **params).single()
            return int(record["count"] if record else 0)

    def count_relationships(self, tenant_id: str | None = None) -> int:
        query = "MATCH (:KGNode)-[r]->(:KGNode)"
        params = {}
        if tenant_id is not None:
            query += " WHERE r.kg_tenant_id = $tenant_id"
            params["tenant_id"] = tenant_id
        query += " RETURN count(r) AS count"
        with self.driver.session(database=self.database) as session:
            record = session.run(query, **params).single()
            return int(record["count"] if record else 0)
