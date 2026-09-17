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
