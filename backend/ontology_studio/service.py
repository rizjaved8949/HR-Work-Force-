"""Application service for the Step-10 Ontology Studio management plane."""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from graph.factory import create_graph_repository_from_env, graph_backend_name
from mapping.registry import DEFAULT_MAPPING_REGISTRY, MappingRegistry
from mapping.service import CURRENT_MAPPING_SERVICE, CurrentMappingService
from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry
from ontology.service import ONTOLOGY_SERVICE, OntologyService

from .models import (
    ChangeRequestCreate,
    ChangeRequestDecision,
    MappingReview,
    MappingReviewCreate,
    MappingReviewDecision,
    OntologyChangeRequest,
    utc_now_iso,
)
from .store import DEFAULT_STUDIO_STORE, StudioReviewStore


ATTENTION_DISPOSITIONS = {
    "explicitly_unmodeled_nonblocking",
    "context_not_scalar",
}


class OntologyStudioService:
    def __init__(
        self,
        *,
        ontology_registry: OntologyRegistry = DEFAULT_REGISTRY,
        ontology_service: OntologyService = ONTOLOGY_SERVICE,
        mapping_registry: MappingRegistry = DEFAULT_MAPPING_REGISTRY,
        mapping_service: CurrentMappingService = CURRENT_MAPPING_SERVICE,
        store: StudioReviewStore = DEFAULT_STUDIO_STORE,
        graph_repository_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.ontology_registry = ontology_registry
        self.ontology_service = ontology_service
        self.mapping_registry = mapping_registry
        self.mapping_service = mapping_service
        self.store = store
        self.graph_repository_factory = (
            graph_repository_factory or create_graph_repository_from_env
        )

    def dashboard(self, tenant_id: str | None = None) -> dict[str, Any]:
        tenant = tenant_id or os.getenv("STEP9_TENANT_ID", "ORGANIZATION-001")
        ontology_summary = self.ontology_service.summary()
        mapping_summary = self.mapping_service.summary()
        supabase_summary = self.mapping_service.supabase_summary()
        reviews = self.store.load()
        graph_health = self.graph_health(tenant)
        pending_semantic = [
            item
            for item in self.ontology_registry.load().known_semantic_open_items
        ]
        return {
            "step": 10,
            "name": "Ontology Management UI / Ontology Studio",
            "tenant_id": tenant,
            "ontology": ontology_summary,
            "mapping": mapping_summary,
            "supabase": supabase_summary,
            "graph": graph_health,
            "service_coverage": self.mapping_service.service_coverage(),
            "pending_semantic_items": pending_semantic,
            "review_counts": {
                "mapping_pending": sum(
                    item.get("status") == "pending"
                    for item in reviews["mapping_reviews"]
                ),
                "change_pending": sum(
                    item.get("status") == "pending"
                    for item in reviews["change_requests"]
                ),
            },
            "safety": {
                "active_ontology_mutation_enabled": False,
                "active_mapping_mutation_enabled": False,
                "review_workflow": "staged_only",
                "note": (
                    "Step 10 approvals are governance decisions. They do not silently "
                    "rewrite active ontology/mapping files. Controlled apply/versioning "
                    "belongs to the production/versioning boundary."
                ),
            },
        }

    def graph_health(self, tenant_id: str) -> dict[str, Any]:
        repository = None
        try:
            repository = self.graph_repository_factory()
            repository.verify_connectivity()
            return {
                "available": True,
                "repository": type(repository).__name__,
                "backend": graph_backend_name(),
                "node_count": repository.count_nodes(tenant_id),
                "relationship_count": repository.count_relationships(tenant_id),
            }
        except Exception as error:
            return {
                "available": False,
                "repository": type(repository).__name__ if repository else None,
                "backend": graph_backend_name(),
                "node_count": None,
                "relationship_count": None,
                "error": f"{type(error).__name__}: {error}",
            }
        finally:
            if repository is not None:
                close = getattr(repository, "close", None)
                if callable(close):
                    close()

    def schema_graph(self) -> dict[str, Any]:
        ontology = self.ontology_registry.load()
        nodes = []
        for entity in ontology.entities:
            pending = sum(
                prop.semantic_status != "confirmed" for prop in entity.properties
            )
            nodes.append(
                {
                    "id": entity.name,
                    "label": entity.name,
                    "module": entity.module,
                    "property_count": len(entity.properties),
                    "pending_property_count": pending,
                    "description": entity.description,
                }
            )
        edges = [
            {
                "id": f"{item.source}:{item.relation}:{item.target}",
                "source": item.source,
                "target": item.target,
                "relation": item.relation,
                "cardinality": item.cardinality,
                "semantic_status": item.semantic_status,
                "description": item.description,
            }
            for item in ontology.relationships
        ]
        return {
            "ontology_version": ontology.version,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def entity_catalog(self) -> list[dict[str, Any]]:
        mapping_counts: Counter[str] = Counter()
        for dataset in self.mapping_registry.load()["datasets"]:
            for column in dataset["columns"]:
                path = column.get("ontology_path")
                if path and "." in path:
                    mapping_counts[path.split(".", 1)[0]] += 1

        result = []
        for entity in self.ontology_registry.load().entities:
            result.append(
                {
                    **entity.model_dump(),
                    "relationship_count": len(
                        self.ontology_registry.relationships_for(entity.name)
                    ),
                    "mapped_source_column_count": mapping_counts[entity.name],
                    "pending_property_count": sum(
                        prop.semantic_status != "confirmed"
                        for prop in entity.properties
                    ),
                }
            )
        return result

    def dataset_catalog(self) -> list[dict[str, Any]]:
        result = []
        for dataset in self.mapping_registry.load()["datasets"]:
            dispositions = Counter(
                column["disposition"] for column in dataset["columns"]
            )
            mapped = sum(
                bool(column.get("ontology_path")) for column in dataset["columns"]
            )
            attention = sum(
                column["disposition"] in ATTENTION_DISPOSITIONS
                for column in dataset["columns"]
            )
            result.append(
                {
                    "source_file": dataset["source_file"],
                    "row_count": dataset.get("row_count", 0),
                    "column_count": dataset.get(
                        "column_count", len(dataset["columns"])
                    ),
                    "ontology_path_count": mapped,
                    "attention_count": attention,
                    "dispositions": dict(sorted(dispositions.items())),
                }
            )
        return result

    def dataset_mapping(self, source_file: str) -> dict[str, Any]:
        dataset = self.mapping_registry.dataset(source_file)
        return {
            **dataset,
            "attention_columns": [
                item["source_column"]
                for item in dataset["columns"]
                if item["disposition"] in ATTENTION_DISPOSITIONS
            ],
        }

    def attention_queue(self) -> dict[str, Any]:
        mapping_items = []
        for dataset in self.mapping_registry.load()["datasets"]:
            for column in dataset["columns"]:
                if column["disposition"] in ATTENTION_DISPOSITIONS:
                    mapping_items.append(
                        {
                            "source_file": dataset["source_file"],
                            "source_column": column["source_column"],
                            "disposition": column["disposition"],
                            "reason": column.get("reason"),
                        }
                    )
        pending_properties = []
        for entity in self.ontology_registry.load().entities:
            for prop in entity.properties:
                if prop.semantic_status != "confirmed":
                    pending_properties.append(
                        {
                            "ontology_path": f"{entity.name}.{prop.name}",
                            "semantic_status": prop.semantic_status,
                            "notes": prop.notes,
                            "observed_current_data": prop.observed_current_data,
                        }
                    )
        return {
            "mapping_attention": mapping_items,
            "pending_semantic_properties": pending_properties,
            "known_semantic_open_items": self.ontology_registry.load().known_semantic_open_items,
        }

    def service_contracts(self) -> list[dict[str, Any]]:
        coverage = self.mapping_service.service_coverage()
        result = []
        for name in self.ontology_registry.list_service_contracts():
            contract = self.ontology_registry.get_service_contract(name)
            result.append(
                {
                    "name": name,
                    "contract": contract,
                    "coverage": coverage.get(name),
                }
            )
        return result

    def mapping_review_options(self) -> dict[str, Any]:
        """Return controlled values used by the Mapping Review form.

        The UI must not ask an admin to remember/copy ontology property paths or
        disposition strings. Options are generated from the active ontology and
        the current mapping registry, so the selectors stay aligned with the
        project's source of truth.
        """
        ontology_paths: list[dict[str, Any]] = []
        for entity in self.ontology_registry.load().entities:
            for prop in entity.properties:
                ontology_paths.append(
                    {
                        "value": f"{entity.name}.{prop.name}",
                        "entity": entity.name,
                        "property": prop.name,
                        "module": entity.module,
                        "data_type": prop.data_type,
                        "semantic_status": prop.semantic_status,
                    }
                )
        observed_dispositions = {
            column.get("disposition")
            for dataset in self.mapping_registry.load()["datasets"]
            for column in dataset.get("columns", [])
            if column.get("disposition")
        }
        preferred = [
            "direct_property",
            "context_specific_property",
            "relationship_reference",
            "relationship_rule",
            "scenario_assumption_value",
            "context_not_scalar",
            "explicitly_unmodeled_nonblocking",
        ]
        dispositions = [item for item in preferred if item in observed_dispositions]
        dispositions.extend(sorted(observed_dispositions - set(dispositions)))
        return {
            "ontology_paths": ontology_paths,
            "dispositions": dispositions,
            "transform_options": sorted(
                {
                    str(column.get("transform") or "identity")
                    for dataset in self.mapping_registry.load()["datasets"]
                    for column in dataset.get("columns", [])
                }
            ),
        }

    @staticmethod
    def _live_node_label(node: Any) -> str:
        properties = dict(getattr(node, "properties", {}) or {})
        preferred_keys = (
            "name",
            "fullName",
            "employeeName",
            "employeeId",
            "organizationId",
            "businessUnitId",
            "departmentId",
            "positionId",
            "organizationalUnitId",
            "assignmentId",
            "skillId",
            "kpiId",
            "courseId",
            "title",
            "designation",
        )
        for key in preferred_keys:
            value = properties.get(key)
            if value not in (None, ""):
                return str(value)
        graph_id = str(getattr(node, "graph_id", ""))
        if graph_id:
            tail = graph_id.rsplit(":", 1)[-1]
            return tail if tail and tail != graph_id else graph_id
        return str(getattr(node, "entity_type", "Node"))

    def _live_node_payload(self, node: Any, *, center: bool = False) -> dict[str, Any]:
        provenance = []
        for item in list(getattr(node, "provenance", []) or []):
            if hasattr(item, "model_dump"):
                provenance.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                provenance.append(dict(item))
        def iso(value: Any) -> Any:
            return value.isoformat() if hasattr(value, "isoformat") else value
        return {
            "graph_id": str(node.graph_id),
            "tenant_id": str(node.tenant_id),
            "entity_type": str(node.entity_type),
            "label": self._live_node_label(node),
            "ontology_version": str(node.ontology_version),
            "properties": dict(node.properties or {}),
            "provenance": provenance,
            "valid_from": iso(getattr(node, "valid_from", None)),
            "valid_to": iso(getattr(node, "valid_to", None)),
            "created_at": iso(getattr(node, "created_at", None)),
            "updated_at": iso(getattr(node, "updated_at", None)),
            "center": bool(center),
        }

    @staticmethod
    def _live_edge_payload(edge: Any) -> dict[str, Any]:
        return {
            "graph_id": str(edge.graph_id),
            "relation_type": str(edge.relation_type),
            "source_graph_id": str(edge.source_graph_id),
            "source_entity_type": str(edge.source_entity_type),
            "target_graph_id": str(edge.target_graph_id),
            "target_entity_type": str(edge.target_entity_type),
            "properties": dict(getattr(edge, "properties", {}) or {}),
        }

    @staticmethod
    def _matches_live_search(node: Any, query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return True
        haystack = " ".join(
            [
                str(getattr(node, "graph_id", "")),
                str(getattr(node, "entity_type", "")),
                json.dumps(dict(getattr(node, "properties", {}) or {}), default=str),
            ]
        ).lower()
        return q in haystack

    @staticmethod
    def _balanced_node_sample(nodes: list[Any], limit: int) -> list[Any]:
        """Round-robin entity types so one large type does not hide the others."""
        if len(nodes) <= limit:
            return list(nodes)
        groups: dict[str, list[Any]] = {}
        for node in nodes:
            groups.setdefault(str(node.entity_type), []).append(node)
        keys = sorted(groups)
        result: list[Any] = []
        offset = 0
        while len(result) < limit and keys:
            remaining: list[str] = []
            for key in keys:
                bucket = groups[key]
                if offset < len(bucket):
                    result.append(bucket[offset])
                    if len(result) >= limit:
                        break
                if offset + 1 < len(bucket):
                    remaining.append(key)
            keys = remaining
            offset += 1
        return result

    def live_graph(
        self,
        tenant_id: str,
        *,
        entity_type: str | None = None,
        search: str | None = None,
        limit: int = 140,
    ) -> dict[str, Any]:
        """Return a bounded, fresh tenant-data graph for interactive browsing.

        This is intentionally different from ``schema_graph``: schema_graph shows
        the 39 ontology entity *types*, while this method reads actual rows from
        kg_nodes/kg_relationships. It never tries to render tens of thousands of
        records at once.
        """
        tenant = (tenant_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id is required")
        limit = max(10, min(int(limit), 240))
        repository = self.graph_repository_factory()
        try:
            repository.verify_connectivity()
            scan_limit = min(max(limit * (14 if search else 7), 900), 10_000)
            pool = repository.find_nodes(
                tenant_id=tenant,
                entity_type=entity_type or None,
                limit=scan_limit,
            )
            if search:
                pool = [node for node in pool if self._matches_live_search(node, search)]
            selected = self._balanced_node_sample(pool, limit)
            node_ids = [node.graph_id for node in selected]
            edge_limit = min(max(limit * 6, 300), 1800)
            between = getattr(repository, "find_relationships_between_nodes", None)
            if callable(between):
                edges = between(
                    tenant_id=tenant,
                    graph_ids=node_ids,
                    limit=edge_limit,
                )
            else:
                edge_pool = repository.find_relationships(
                    tenant_id=tenant,
                    limit=min(max(edge_limit * 4, 1200), 10_000),
                )
                id_set = set(node_ids)
                edges = [
                    edge
                    for edge in edge_pool
                    if edge.source_graph_id in id_set and edge.target_graph_id in id_set
                ][:edge_limit]
            return {
                "mode": "live",
                "tenant_id": tenant,
                "node_count_total": repository.count_nodes(tenant),
                "relationship_count_total": repository.count_relationships(tenant),
                "displayed_node_count": len(selected),
                "displayed_relationship_count": len(edges),
                "nodes": [self._live_node_payload(node) for node in selected],
                "edges": [self._live_edge_payload(edge) for edge in edges],
                "entity_types": sorted({str(node.entity_type) for node in pool}),
                "search": search or "",
                "entity_type": entity_type or "",
                "truncated": len(pool) > len(selected),
                "note": (
                    "This view is a bounded live-data explorer. Click a node to load "
                    "its complete bounded 1-hop neighbourhood instead of rendering the "
                    "entire tenant graph at once."
                ),
            }
        finally:
            close = getattr(repository, "close", None)
            if callable(close):
                close()

    def live_node_neighborhood(
        self,
        tenant_id: str,
        graph_id: str,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        tenant = (tenant_id or "").strip()
        graph_id = (graph_id or "").strip()
        if not tenant or not graph_id:
            raise ValueError("tenant_id and graph_id are required")
        limit = max(10, min(int(limit), 180))
        repository = self.graph_repository_factory()
        try:
            repository.verify_connectivity()
            center = repository.get_node(graph_id, tenant)
            if center is None:
                raise KeyError(f"Graph node not found for tenant: {graph_id}")
            each_side = min(max(limit, 30), 180)
            outgoing = repository.find_relationships(
                tenant_id=tenant,
                source_graph_id=graph_id,
                limit=each_side,
            )
            incoming = repository.find_relationships(
                tenant_id=tenant,
                target_graph_id=graph_id,
                limit=each_side,
            )
            merged: dict[str, Any] = {}
            for edge in [*outgoing, *incoming]:
                merged[str(edge.graph_id)] = edge
            edges = list(merged.values())[:limit]
            neighbor_ids: list[str] = []
            for edge in edges:
                other = (
                    edge.target_graph_id
                    if edge.source_graph_id == graph_id
                    else edge.source_graph_id
                )
                if other != graph_id and other not in neighbor_ids:
                    neighbor_ids.append(other)
            fetch_many = getattr(repository, "find_nodes_by_ids", None)
            if callable(fetch_many):
                neighbors = fetch_many(
                    tenant_id=tenant,
                    graph_ids=neighbor_ids,
                    limit=len(neighbor_ids) or 1,
                )
            else:
                neighbors = []
                for neighbor_id in neighbor_ids:
                    node = repository.get_node(neighbor_id, tenant)
                    if node is not None:
                        neighbors.append(node)
            node_by_id = {node.graph_id: node for node in neighbors}
            ordered_neighbors = [
                node_by_id[item] for item in neighbor_ids if item in node_by_id
            ]
            return {
                "mode": "live_neighborhood",
                "tenant_id": tenant,
                "center_graph_id": graph_id,
                "nodes": [
                    self._live_node_payload(center, center=True),
                    *[self._live_node_payload(node) for node in ordered_neighbors],
                ],
                "edges": [self._live_edge_payload(edge) for edge in edges],
                "node_detail": self._live_node_payload(center, center=True),
                "outgoing_count": sum(edge.source_graph_id == graph_id for edge in edges),
                "incoming_count": sum(edge.target_graph_id == graph_id for edge in edges),
                "relationship_count": len(edges),
                "neighbor_count": len(ordered_neighbors),
                "truncated": len(merged) > len(edges),
            }
        finally:
            close = getattr(repository, "close", None)
            if callable(close):
                close()

    def _current_column_mapping(self, source_file: str, source_column: str) -> dict | None:
        dataset = self.mapping_registry.dataset(source_file)
        for item in dataset["columns"]:
            if item["source_column"] == source_column:
                return dict(item)
        raise KeyError(
            f"Unknown source column {source_column!r} in {source_file!r}"
        )

    def create_mapping_review(self, request: MappingReviewCreate) -> dict[str, Any]:
        current = self._current_column_mapping(
            request.source_file, request.source_column
        )
        if request.proposed_ontology_path:
            if not self.ontology_registry.ontology_path_exists(
                request.proposed_ontology_path
            ):
                raise ValueError(
                    f"Unknown ontology property: {request.proposed_ontology_path}"
                )
        review = MappingReview(
            **request.model_dump(),
            current_mapping=current,
        )
        return self.store.append("mapping_reviews", review.model_dump())

    def list_mapping_reviews(self, status: str | None = None) -> list[dict[str, Any]]:
        items = self.store.load()["mapping_reviews"]
        if status:
            return [item for item in items if item.get("status") == status]
        return items

    def decide_mapping_review(
        self, review_id: str, decision: MappingReviewDecision
    ) -> dict[str, Any]:
        return self.store.update(
            "mapping_reviews",
            review_id,
            {
                "status": decision.decision,
                "reviewed_by": decision.reviewer,
                "reviewed_at": utc_now_iso(),
                "review_comment": decision.comment,
                "applied_to_active_mapping": False,
            },
        )

    def create_change_request(self, request: ChangeRequestCreate) -> dict[str, Any]:
        change = OntologyChangeRequest(**request.model_dump())
        return self.store.append("change_requests", change.model_dump())

    def list_change_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        items = self.store.load()["change_requests"]
        if status:
            return [item for item in items if item.get("status") == status]
        return items

    def decide_change_request(
        self, request_id: str, decision: ChangeRequestDecision
    ) -> dict[str, Any]:
        return self.store.update(
            "change_requests",
            request_id,
            {
                "status": decision.decision,
                "reviewed_by": decision.reviewer,
                "reviewed_at": utc_now_iso(),
                "review_comment": decision.comment,
                "applied_to_active_ontology": False,
            },
        )

    def export_governance_snapshot(self) -> dict[str, Any]:
        ontology = self.ontology_registry.load()
        mapping = self.mapping_registry.load()
        reviews = self.store.load()
        return {
            "step": 10,
            "ontology": {
                "name": ontology.name,
                "version": ontology.version,
                "status": ontology.status,
                "validation": self.ontology_service.validation_report(),
            },
            "mapping": {
                "version": mapping["version"],
                "ontology_version": mapping["ontology_version"],
                "status": mapping["status"],
                "validation": self.mapping_service.validation_report(),
            },
            "reviews": reviews,
            "apply_policy": "review_only_no_silent_active_file_mutation",
        }
