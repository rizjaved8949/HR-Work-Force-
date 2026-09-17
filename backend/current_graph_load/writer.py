"""Two-pass canonical batch writer: all nodes first, then all relationships."""
from __future__ import annotations

from graph.models import GraphNode, GraphProvenance, GraphRelationship
from graph.repository import GraphRepository
from ingestion.models import CanonicalEntityRecord, CanonicalRelationshipRecord


class GraphWriteConflict(RuntimeError):
    pass


def entity_to_node(item: CanonicalEntityRecord) -> GraphNode:
    return GraphNode(
        graph_id=item.graph_id,
        tenant_id=item.tenant_id,
        entity_type=item.entity_type,
        ontology_version=item.ontology_version,
        properties=item.properties,
        provenance=[GraphProvenance(
            source_system=item.source_system,
            source_object=item.source_object,
            source_record_key=item.source_record_key,
            mapping_version=item.mapping_version,
        )],
        valid_from=item.valid_from,
        valid_to=item.valid_to,
    )


def relationship_to_edge(item: CanonicalRelationshipRecord) -> GraphRelationship:
    return GraphRelationship(
        graph_id=item.graph_id,
        tenant_id=item.tenant_id,
        relation_type=item.relation_type,
        source_graph_id=item.source_graph_id,
        source_entity_type=item.source_entity_type,
        target_graph_id=item.target_graph_id,
        target_entity_type=item.target_entity_type,
        ontology_version=item.ontology_version,
        provenance=[GraphProvenance(
            source_system=item.source_system,
            source_object=item.source_object,
            source_record_key=item.source_record_key,
            mapping_version=item.mapping_version,
        )],
    )


class CanonicalGraphWriter:
    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository

    @staticmethod
    def dedupe_nodes(items: list[CanonicalEntityRecord]) -> dict[str, CanonicalEntityRecord]:
        result: dict[str, CanonicalEntityRecord] = {}
        for item in items:
            previous = result.get(item.graph_id)
            if previous is not None:
                if previous.entity_type != item.entity_type:
                    raise GraphWriteConflict(
                        f"Conflicting entity types for graph_id {item.graph_id}"
                    )
                if previous.properties == item.properties:
                    continue
                previous_is_subset = all(
                    key in item.properties and item.properties[key] == value
                    for key, value in previous.properties.items()
                )
                item_is_subset = all(
                    key in previous.properties and previous.properties[key] == value
                    for key, value in item.properties.items()
                )
                if previous_is_subset:
                    result[item.graph_id] = item
                    continue
                if item_is_subset:
                    continue
                raise GraphWriteConflict(
                    f"Conflicting canonical node payloads for graph_id {item.graph_id}"
                )
            result[item.graph_id] = item
        return result

    @staticmethod
    def dedupe_relationships(items: list[CanonicalRelationshipRecord]) -> dict[str, CanonicalRelationshipRecord]:
        result: dict[str, CanonicalRelationshipRecord] = {}
        for item in items:
            previous = result.get(item.graph_id)
            if previous is not None and (
                previous.source_graph_id != item.source_graph_id
                or previous.target_graph_id != item.target_graph_id
                or previous.relation_type != item.relation_type
            ):
                raise GraphWriteConflict(
                    f"Conflicting canonical relationship payloads for graph_id {item.graph_id}"
                )
            result[item.graph_id] = item
        return result

    def validate_endpoints(
        self,
        nodes: dict[str, CanonicalEntityRecord],
        relationships: dict[str, CanonicalRelationshipRecord],
        *,
        tenant_id: str,
    ) -> list[str]:
        planned = set(nodes)
        missing: set[str] = set()
        for edge in relationships.values():
            for graph_id in (edge.source_graph_id, edge.target_graph_id):
                if graph_id in planned:
                    continue
                if self.repository.get_node(graph_id, tenant_id) is None:
                    missing.add(graph_id)
        return sorted(missing)

    def write_nodes(self, nodes: dict[str, CanonicalEntityRecord]) -> int:
        payload = [entity_to_node(nodes[graph_id]) for graph_id in sorted(nodes)]
        bulk = getattr(self.repository, "upsert_nodes_bulk", None)
        if callable(bulk):
            return int(bulk(payload, batch_size=1000))
        for node in payload:
            self.repository.upsert_node(node)
        return len(payload)

    def write_relationships(self, relationships: dict[str, CanonicalRelationshipRecord]) -> int:
        payload = [relationship_to_edge(relationships[graph_id]) for graph_id in sorted(relationships)]
        bulk = getattr(self.repository, "upsert_relationships_bulk", None)
        if callable(bulk):
            return int(bulk(payload, batch_size=1000))
        for edge in payload:
            self.repository.upsert_relationship(edge)
        return len(payload)
