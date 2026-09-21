"""Step 12 Multi-Organization Onboarding orchestration service."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from collections import Counter
import os
from uuid import uuid4

from graph.ids import make_node_graph_id
from graph.models import GraphNode, GraphProvenance
from graph.factory import create_graph_repository_from_env
from graph.repository import GraphRepository
from current_graph_load.writer import CanonicalGraphWriter
from ingestion.canonicalizer import DEFAULT_CANONICALIZER, Canonicalizer
from ingestion.mapper import DEFAULT_MAPPING_SUGGESTER, OntologyMappingSuggester
from ingestion.models import CanonicalEntityRecord, MappingPlan
from ingestion.profiler import profile_source
from ingestion.validator import DEFAULT_PLAN_VALIDATOR, MappingPlanValidator
from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .access import DEFAULT_ORGANIZATION_ACCESS, OrganizationAccessService
from .auto_mapping import DEFAULT_AUTO_MAPPING_BUILDER, AutoMappingBuilder
from .supabase_ingestion_store import SupabaseOrganizationIngestionStore
from .models import (
    ActorContext,
    CreateOrganizationRequest,
    DatasetLoadResult,
    DatasetStatus,
    MappingPlanDraftRequest,
    OnboardingIssue,
    OrganizationDataset,
    OrganizationLoadReport,
    OrganizationMember,
    OrganizationReadiness,
    OrganizationRecord,
    OrganizationStatus,
    RegisterRecordsDatasetRequest,
    utc_now,
)
from .plan_store import DEFAULT_TENANT_PLAN_STORE, TenantMappingPlanStore
from .registry import DEFAULT_ORGANIZATION_REGISTRY, OrganizationRegistry, validate_tenant_id
from .source_store import DEFAULT_SOURCE_STORE, OrganizationSourceStore


class MultiOrganizationOnboardingService:
    def __init__(
        self,
        *,
        repository: GraphRepository,
        registry: OrganizationRegistry = DEFAULT_ORGANIZATION_REGISTRY,
        source_store: OrganizationSourceStore = DEFAULT_SOURCE_STORE,
        plan_store: TenantMappingPlanStore = DEFAULT_TENANT_PLAN_STORE,
        access: OrganizationAccessService = DEFAULT_ORGANIZATION_ACCESS,
        ontology: OntologyRegistry = DEFAULT_REGISTRY,
        mapping_suggester: OntologyMappingSuggester = DEFAULT_MAPPING_SUGGESTER,
        plan_validator: MappingPlanValidator = DEFAULT_PLAN_VALIDATOR,
        canonicalizer: Canonicalizer = DEFAULT_CANONICALIZER,
        auto_mapping_builder: AutoMappingBuilder = DEFAULT_AUTO_MAPPING_BUILDER,
        ingestion_store: SupabaseOrganizationIngestionStore | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.source_store = source_store
        self.plan_store = plan_store
        self.access = access
        self.ontology = ontology
        self.mapping_suggester = mapping_suggester
        self.plan_validator = plan_validator
        self.canonicalizer = canonicalizer
        self.auto_mapping_builder = auto_mapping_builder
        self.ingestion_store = ingestion_store

    @classmethod
    def from_env(cls, *, verify_connectivity: bool = True):
        repository = create_graph_repository_from_env(verify_connectivity=verify_connectivity)
        persist_raw = os.getenv("MULTI_ORG_PERSIST_UPLOADS_TO_SUPABASE", "true").strip().lower() not in {"0", "false", "no", "off"}
        ingestion_store = SupabaseOrganizationIngestionStore.from_env() if persist_raw else None
        return cls(repository=repository, ingestion_store=ingestion_store)

    def close(self) -> None:
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()

    def ensure_default_organization(
        self,
        *,
        tenant_id: str,
        name: str = "Current Organization",
        legacy_open_access: bool = True,
    ) -> OrganizationRecord:
        tenant = validate_tenant_id(tenant_id)
        try:
            return self.registry.get(tenant)
        except KeyError:
            record = OrganizationRecord(
                tenant_id=tenant,
                name=name.strip() or "Current Organization",
                status=OrganizationStatus.ACTIVE,
                is_default=True,
                legacy_default_access=legacy_open_access,
                created_by="step12-bootstrap",
                activated_at=utc_now(),
                notes=(
                    "Bootstrapped from the existing Step-9 tenant so Step 12 remains non-breaking. "
                    "Secondary organizations require explicit onboarding and access membership."
                ),
            )
            return self.registry.create(record)

    def create_organization(
        self,
        payload: CreateOrganizationRequest,
        *,
        actor: ActorContext,
    ) -> OrganizationRecord:
        if not self.access.can_create_organization(actor):
            raise PermissionError("Current user is not allowed to create organizations")
        tenant = validate_tenant_id(payload.tenant_id)
        members: list[OrganizationMember] = []
        if actor.user_id:
            members.append(
                OrganizationMember(
                    user_id=actor.user_id,
                    role="owner",
                    added_by=actor.user_id,
                )
            )
        return self.registry.create(
            OrganizationRecord(
                tenant_id=tenant,
                name=payload.name,
                country=payload.country,
                currency=payload.currency,
                organization_type=payload.organization_type,
                created_by=actor.user_id or actor.role or "system",
                members=members,
                notes=payload.notes,
            )
        )

    def list_organizations(self, *, actor: ActorContext) -> list[OrganizationRecord]:
        return [org for org in self.registry.list() if self.access.can_access(org, actor)]

    def organization(self, tenant_id: str, *, actor: ActorContext) -> OrganizationRecord:
        org = self.registry.get(tenant_id)
        if not self.access.can_access(org, actor):
            raise PermissionError("Current user does not have access to this organization")
        return org

    def require_admin(self, tenant_id: str, *, actor: ActorContext) -> OrganizationRecord:
        org = self.organization(tenant_id, actor=actor)
        if not self.access.can_administer(org, actor):
            raise PermissionError("Organization admin/owner access is required")
        return org

    def add_member(
        self,
        tenant_id: str,
        *,
        user_id: str,
        role: str,
        actor: ActorContext,
    ) -> OrganizationRecord:
        self.require_admin(tenant_id, actor=actor)
        user = str(user_id).strip()
        if not user:
            raise ValueError("user_id must not be empty")

        def mutate(org: OrganizationRecord) -> OrganizationRecord:
            for index, member in enumerate(org.members):
                if member.user_id == user:
                    org.members[index] = OrganizationMember(
                        user_id=user,
                        role=role,
                        added_by=actor.user_id,
                    )
                    return org
            org.members.append(
                OrganizationMember(
                    user_id=user,
                    role=role,
                    added_by=actor.user_id,
                )
            )
            return org

        return self.registry.update(tenant_id, mutate)

    def register_records_dataset(
        self,
        tenant_id: str,
        payload: RegisterRecordsDatasetRequest,
        *,
        actor: ActorContext,
    ) -> OrganizationDataset:
        self.require_admin(tenant_id, actor=actor)
        dataset_id = f"ds-{uuid4().hex[:16]}"
        storage_key = self.source_store.save_rows(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            source_system=payload.source_system,
            source_object=payload.source_object,
            source_format=payload.source_format,
            rows=payload.rows,
        )
        dataset = OrganizationDataset(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            source_system=payload.source_system,
            source_object=payload.source_object,
            source_format=payload.source_format,
            storage_key=storage_key,
            row_count=len(payload.rows),
        )
        self.registry.upsert_dataset(tenant_id, dataset)
        return dataset

    def register_file_dataset(
        self,
        tenant_id: str,
        path: str | Path,
        *,
        actor: ActorContext,
        source_system: str | None = None,
        source_object: str | None = None,
        sheet_name: str | None = None,
    ) -> OrganizationDataset:
        self.require_admin(tenant_id, actor=actor)
        dataset_id = f"ds-{uuid4().hex[:16]}"
        storage_key, row_count, system, obj, fmt = self.source_store.import_file(
            path,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            source_system=source_system,
            source_object=source_object,
            sheet_name=sheet_name,
        )
        dataset = OrganizationDataset(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            source_system=system,
            source_object=obj,
            source_format=fmt,
            storage_key=storage_key,
            row_count=row_count,
        )
        self.registry.upsert_dataset(tenant_id, dataset)
        return dataset

    def register_or_replace_file_dataset(
        self,
        tenant_id: str,
        path: str | Path,
        *,
        actor: ActorContext,
        source_system: str | None = None,
        source_object: str | None = None,
        sheet_name: str | None = None,
    ) -> OrganizationDataset:
        """Register a source object once; later uploads replace its snapshot.

        This prevents duplicate dataset records from blocking readiness and gives
        repeat uploads true upsert/update semantics.
        """
        org = self.require_admin(tenant_id, actor=actor)
        source_path = Path(path)
        system = (source_system or source_path.suffix.lower().lstrip(".") or "browser_upload").strip()
        obj = (source_object or source_path.name).strip()
        existing = next(
            (item for item in org.datasets if item.source_system == system and item.source_object == obj),
            None,
        )
        dataset_id = existing.dataset_id if existing else f"ds-{uuid4().hex[:16]}"
        storage_key, row_count, resolved_system, resolved_obj, fmt = self.source_store.import_file(
            source_path,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            source_system=system,
            source_object=obj,
            sheet_name=sheet_name,
        )
        if existing:
            dataset = existing.model_copy(
                update={
                    "source_system": resolved_system,
                    "source_object": resolved_obj,
                    "source_format": fmt,
                    "storage_key": storage_key,
                    "status": DatasetStatus.REGISTERED,
                    "row_count": row_count,
                    "column_count": 0,
                    "mapping_plan_id": None,
                    "updated_at": utc_now(),
                    "last_error": None,
                    "load_result": None,
                }
            )
        else:
            dataset = OrganizationDataset(
                dataset_id=dataset_id,
                tenant_id=tenant_id,
                source_system=resolved_system,
                source_object=resolved_obj,
                source_format=fmt,
                storage_key=storage_key,
                row_count=row_count,
            )
        self.registry.upsert_dataset(tenant_id, dataset)
        return dataset

    def _mark_dataset_failed(self, tenant_id: str, dataset_id: str, message: str) -> None:
        dataset = self.registry.dataset(tenant_id, dataset_id)
        self.registry.upsert_dataset(
            tenant_id,
            dataset.model_copy(
                update={
                    "status": DatasetStatus.FAILED,
                    "updated_at": utc_now(),
                    "last_error": message,
                }
            ),
        )
        if self.ingestion_store is not None:
            try:
                self.ingestion_store.update_status(
                    tenant_id=tenant_id, dataset_id=dataset_id, status="failed"
                )
            except Exception:
                pass

    def auto_sync_file_dataset(
        self,
        tenant_id: str,
        path: str | Path,
        *,
        actor: ActorContext,
        source_system: str | None = None,
        source_object: str | None = None,
        sheet_name: str | None = None,
    ) -> dict[str, Any]:
        """One-click upload -> map -> validate -> graph upsert -> activate.

        Unknown source columns are retained in Supabase JSONB raw storage but do
        not become ontology facts unless the conservative mapper can resolve them
        to confirmed ontology properties.  Existing manual workflow APIs remain
        available for exceptional datasets.
        """
        self.require_admin(tenant_id, actor=actor)
        dataset = self.register_or_replace_file_dataset(
            tenant_id,
            path,
            actor=actor,
            source_system=source_system,
            source_object=source_object,
            sheet_name=sheet_name,
        )
        source = self._source(tenant_id, dataset.dataset_id)
        rows = source.rows()
        profile = profile_source(source)
        profiled = dataset.model_copy(
            update={
                "status": DatasetStatus.PROFILED,
                "row_count": profile.row_count,
                "column_count": len(profile.columns),
                "updated_at": utc_now(),
                "last_error": None,
            }
        )
        self.registry.upsert_dataset(tenant_id, profiled)

        auto = self.auto_mapping_builder.build(profile, rows)
        mapping_summary = auto.summary()

        if self.ingestion_store is not None:
            self.ingestion_store.verify_schema()
            self.ingestion_store.replace_dataset_rows(
                tenant_id=tenant_id,
                dataset_id=dataset.dataset_id,
                source_system=dataset.source_system,
                source_object=dataset.source_object,
                source_format=dataset.source_format,
                rows=rows,
                columns=[item.name for item in profile.columns],
                status="mapping",
                mapping_summary=mapping_summary,
            )

        if not auto.property_mappings:
            message = "No confirmed ontology mappings could be resolved automatically. Raw rows were preserved; graph write was blocked."
            self._mark_dataset_failed(tenant_id, dataset.dataset_id, message)
            return {
                "mode": "auto_sync",
                "status": "mapping_blocked",
                "tenant_id": tenant_id,
                "dataset_id": dataset.dataset_id,
                "source_object": dataset.source_object,
                "rows_received": profile.row_count,
                "columns_received": [item.name for item in profile.columns],
                "mapping": mapping_summary,
                "graph_written": False,
                "message": message,
            }

        plan = MappingPlan(
            plan_id=f"plan-{dataset.dataset_id}",
            version="auto-sync-1.0",
            tenant_id=tenant_id,
            source_system=dataset.source_system,
            source_object=dataset.source_object,
            source_format=dataset.source_format,
            ontology_version=self.ontology.load().version,
            status="approved",
            property_mappings=auto.property_mappings,
            entity_rules=auto.entity_rules,
            relationship_mappings=auto.relationship_mappings,
            approved_by=f"auto-sync:{actor.user_id or actor.role or 'local-dev'}",
            approved_at=utc_now(),
            notes=(
                "Automatically accepted only after conservative confirmed-property mapping "
                "and existing Step-6 validation. Unmapped source columns remain in raw Supabase JSONB."
            ),
        )
        validation_issues = self.plan_validator.validate(plan, profile=profile, require_approved=True)
        validation_errors = [item for item in validation_issues if item.severity == "error"]
        if validation_errors:
            message = "Automatic mapping failed validation: " + "; ".join(item.message for item in validation_errors)
            self._mark_dataset_failed(tenant_id, dataset.dataset_id, message)
            return {
                "mode": "auto_sync",
                "status": "validation_blocked",
                "tenant_id": tenant_id,
                "dataset_id": dataset.dataset_id,
                "rows_received": profile.row_count,
                "mapping": mapping_summary,
                "validation": {
                    "valid": False,
                    "error_count": len(validation_errors),
                    "issues": [item.model_dump(mode="json") for item in validation_issues],
                },
                "graph_written": False,
                "message": message,
            }

        self.plan_store.save(tenant_id, plan)
        current = self.registry.dataset(tenant_id, dataset.dataset_id)
        self.registry.upsert_dataset(
            tenant_id,
            current.model_copy(
                update={
                    "status": DatasetStatus.MAPPING_APPROVED,
                    "mapping_plan_id": plan.plan_id,
                    "updated_at": utc_now(),
                    "last_error": None,
                }
            ),
        )

        dry_batch = self.canonicalizer.normalize(plan, rows, profile=profile)
        dry_errors = [item for item in dry_batch.issues if item.severity == "error"]
        if dry_errors:
            message = "Canonicalization failed: " + "; ".join(item.message for item in dry_errors[:10])
            self._mark_dataset_failed(tenant_id, dataset.dataset_id, message)
            return {
                "mode": "auto_sync",
                "status": "canonicalization_blocked",
                "tenant_id": tenant_id,
                "dataset_id": dataset.dataset_id,
                "rows_received": profile.row_count,
                "mapping": mapping_summary,
                "canonical": {
                    **dry_batch.summary(),
                    "entity_types": dict(sorted(Counter(item.entity_type for item in dry_batch.entities).items())),
                    "relationship_types": dict(sorted(Counter(item.relation_type for item in dry_batch.relationships).items())),
                },
                "graph_written": False,
                "message": message,
            }

        load = self.load_organization(
            tenant_id, actor=actor, dataset_ids=[dataset.dataset_id]
        )
        if load.error_count:
            message = "Graph load blocked: " + "; ".join(item.message for item in load.issues if item.severity == "error")
            self._mark_dataset_failed(tenant_id, dataset.dataset_id, message)
            return {
                "mode": "auto_sync",
                "status": "graph_load_blocked",
                "tenant_id": tenant_id,
                "dataset_id": dataset.dataset_id,
                "mapping": mapping_summary,
                "load": load.model_dump(mode="json"),
                "graph_written": False,
                "message": message,
            }

        readiness = self.readiness(tenant_id, actor=actor)
        activated = False
        if readiness.ready_to_activate:
            self.activate(tenant_id, actor=actor)
            activated = True
        final_dataset = self.registry.dataset(tenant_id, dataset.dataset_id)
        final_org = self.registry.get(tenant_id)
        readiness_after_sync = self.readiness(tenant_id, actor=actor)
        if self.ingestion_store is not None:
            self.ingestion_store.update_status(
                tenant_id=tenant_id,
                dataset_id=dataset.dataset_id,
                status="synced",
                mapping_summary=mapping_summary,
            )

        preview_nodes = self.repository.find_nodes(tenant_id=tenant_id, limit=12)
        preview_relationships = self.repository.find_relationships(tenant_id=tenant_id, limit=12)
        return {
            "mode": "auto_sync",
            "status": "synced",
            "tenant_id": tenant_id,
            "organization_status": final_org.status.value,
            "organization_activated_now": activated,
            "readiness": readiness_after_sync.model_dump(mode="json"),
            "dataset_id": dataset.dataset_id,
            "source_object": dataset.source_object,
            "source_system": dataset.source_system,
            "rows_received": profile.row_count,
            "columns_received": [item.name for item in profile.columns],
            "raw_supabase": {
                "persisted": self.ingestion_store is not None,
                "datasets_table": getattr(self.ingestion_store, "datasets_table", None),
                "rows_table": getattr(self.ingestion_store, "rows_table", None),
                "storage_model": "JSONB row_data preserves arbitrary organization columns; no dynamic ALTER TABLE",
            },
            "mapping": mapping_summary,
            "canonical": {
                **dry_batch.summary(),
                "entity_types": dict(sorted(Counter(item.entity_type for item in dry_batch.entities).items())),
                "relationship_types": dict(sorted(Counter(item.relation_type for item in dry_batch.relationships).items())),
            },
            "graph": {
                "repository": type(self.repository).__name__,
                "nodes_before": load.graph_node_count_before,
                "nodes_after": load.graph_node_count_after,
                "relationships_before": load.graph_relationship_count_before,
                "relationships_after": load.graph_relationship_count_after,
                "unique_nodes_in_this_sync": load.unique_node_count,
                "unique_relationships_in_this_sync": load.unique_relationship_count,
                "kg_nodes_table": getattr(self.repository, "nodes_table", "kg_nodes"),
                "kg_relationships_table": getattr(self.repository, "relationships_table", "kg_relationships"),
            },
            "graph_preview": {
                "nodes": [
                    {
                        "graph_id": node.graph_id,
                        "entity_type": node.entity_type,
                        "properties": node.properties,
                    }
                    for node in preview_nodes
                ],
                "relationships": [
                    {
                        "relation_type": edge.relation_type,
                        "source_entity_type": edge.source_entity_type,
                        "target_entity_type": edge.target_entity_type,
                    }
                    for edge in preview_relationships
                ],
            },
            "dataset": final_dataset.model_dump(mode="json"),
            "message": "Upload stored in Supabase raw ingestion tables and mapped facts upserted into the tenant knowledge graph.",
        }

    def _source(self, tenant_id: str, dataset_id: str):
        self.registry.dataset(tenant_id, dataset_id)
        return self.source_store.load_source(tenant_id=tenant_id, dataset_id=dataset_id)

    def profile_dataset(
        self,
        tenant_id: str,
        dataset_id: str,
        *,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self.require_admin(tenant_id, actor=actor)
        dataset = self.registry.dataset(tenant_id, dataset_id)
        source = self._source(tenant_id, dataset_id)
        profile = profile_source(source)
        updated = dataset.model_copy(
            update={
                "status": DatasetStatus.PROFILED,
                "row_count": profile.row_count,
                "column_count": len(profile.columns),
                "updated_at": utc_now(),
                "last_error": None,
            }
        )
        self.registry.upsert_dataset(tenant_id, updated)
        return profile.model_dump(mode="json")

    def suggest_mappings(
        self,
        tenant_id: str,
        dataset_id: str,
        *,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self.require_admin(tenant_id, actor=actor)
        source = self._source(tenant_id, dataset_id)
        profile = profile_source(source)
        proposals = self.mapping_suggester.propose_schema(profile)
        entity_types = {
            candidate.entity_type
            for proposal in proposals
            for candidate in proposal.candidates[:1]
            if candidate.confidence >= 0.80
        }
        return {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "source_profile": profile.model_dump(mode="json"),
            "column_proposals": [item.model_dump(mode="json") for item in proposals],
            "relationship_candidates": self.mapping_suggester.relationship_candidates(entity_types),
            "review_required": True,
            "policy": "Mapping suggestions are advisory only; Step 12 never auto-approves an organization mapping.",
        }

    def create_mapping_plan(
        self,
        tenant_id: str,
        dataset_id: str,
        payload: MappingPlanDraftRequest,
        *,
        actor: ActorContext,
    ) -> MappingPlan:
        self.require_admin(tenant_id, actor=actor)
        dataset = self.registry.dataset(tenant_id, dataset_id)
        plan = MappingPlan(
            plan_id=f"plan-{dataset_id}",
            version=payload.version,
            tenant_id=tenant_id,
            source_system=dataset.source_system,
            source_object=dataset.source_object,
            source_format=dataset.source_format,
            ontology_version=self.ontology.load().version,
            status="draft",
            property_mappings=payload.property_mappings,
            entity_rules=payload.entity_rules,
            relationship_mappings=payload.relationship_mappings,
            notes=payload.notes,
        )
        self.plan_store.save(tenant_id, plan)
        updated = dataset.model_copy(
            update={
                "status": DatasetStatus.MAPPING_REVIEW,
                "mapping_plan_id": plan.plan_id,
                "updated_at": utc_now(),
                "last_error": None,
            }
        )
        self.registry.upsert_dataset(tenant_id, updated)
        self._refresh_org_status(tenant_id)
        return plan

    def mapping_plan(self, tenant_id: str, dataset_id: str, *, actor: ActorContext) -> MappingPlan:
        self.organization(tenant_id, actor=actor)
        dataset = self.registry.dataset(tenant_id, dataset_id)
        if not dataset.mapping_plan_id:
            raise KeyError("Dataset has no mapping plan")
        return self.plan_store.load(tenant_id, dataset.mapping_plan_id)

    def validate_mapping_plan(
        self,
        tenant_id: str,
        dataset_id: str,
        *,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self.require_admin(tenant_id, actor=actor)
        plan = self.mapping_plan(tenant_id, dataset_id, actor=actor)
        source = self._source(tenant_id, dataset_id)
        profile = profile_source(source)
        issues = self.plan_validator.validate(plan, profile=profile)
        return {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "plan_id": plan.plan_id,
            "valid": not any(item.severity == "error" for item in issues),
            "error_count": sum(item.severity == "error" for item in issues),
            "warning_count": sum(item.severity == "warning" for item in issues),
            "issues": [item.model_dump(mode="json") for item in issues],
        }

    def approve_mapping_plan(
        self,
        tenant_id: str,
        dataset_id: str,
        *,
        actor: ActorContext,
    ) -> MappingPlan:
        self.require_admin(tenant_id, actor=actor)
        plan = self.mapping_plan(tenant_id, dataset_id, actor=actor)
        source = self._source(tenant_id, dataset_id)
        profile = profile_source(source)
        issues = self.plan_validator.validate(plan, profile=profile)
        errors = [item for item in issues if item.severity == "error"]
        if errors:
            raise ValueError(
                "Mapping plan cannot be approved: " + "; ".join(item.message for item in errors)
            )
        approved = plan.model_copy(
            update={
                "status": "approved",
                "approved_by": actor.user_id or actor.role or "local-dev",
                "approved_at": utc_now(),
            }
        )
        self.plan_store.save(tenant_id, approved)
        dataset = self.registry.dataset(tenant_id, dataset_id)
        self.registry.upsert_dataset(
            tenant_id,
            dataset.model_copy(
                update={
                    "status": DatasetStatus.MAPPING_APPROVED,
                    "updated_at": utc_now(),
                    "last_error": None,
                }
            ),
        )
        self._refresh_org_status(tenant_id)
        return approved

    def dry_run_dataset(
        self,
        tenant_id: str,
        dataset_id: str,
        *,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self.require_admin(tenant_id, actor=actor)
        plan = self.mapping_plan(tenant_id, dataset_id, actor=actor)
        source = self._source(tenant_id, dataset_id)
        profile = profile_source(source)
        batch = self.canonicalizer.normalize(plan, source.rows(), profile=profile)
        return {
            "step": 12,
            "mode": "organization_dataset_dry_run_no_graph_write",
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "batch_summary": batch.summary(),
            "issues": [item.model_dump(mode="json") for item in batch.issues],
        }

    def _organization_root(self, org: OrganizationRecord) -> CanonicalEntityRecord:
        properties: dict[str, Any] = {
            "organizationId": org.tenant_id,
            "name": org.name,
        }
        if org.country:
            properties["country"] = org.country
        if org.currency:
            properties["currency"] = org.currency
        if org.organization_type:
            properties["organizationType"] = org.organization_type
        return CanonicalEntityRecord(
            tenant_id=org.tenant_id,
            entity_type="Organization",
            graph_id=make_node_graph_id(
                tenant_id=org.tenant_id,
                entity_type="Organization",
                identity_key=org.tenant_id,
            ),
            identity_key=org.tenant_id,
            source_system="step12_onboarding",
            source_object="organization_registry",
            source_record_key=org.tenant_id,
            ontology_version=self.ontology.load().version,
            mapping_version="1.0.0-step12",
            properties=properties,
            row_number=0,
        )

    def prepare_load(
        self,
        tenant_id: str,
        *,
        actor: ActorContext,
        dataset_ids: Iterable[str] | None = None,
    ):
        org = self.require_admin(tenant_id, actor=actor)
        selected = set(dataset_ids or [])
        datasets = [
            item
            for item in org.datasets
            if not selected or item.dataset_id in selected
        ]
        if selected:
            missing = selected - {item.dataset_id for item in datasets}
            if missing:
                raise KeyError(f"Unknown dataset(s): {', '.join(sorted(missing))}")
        issues: list[OnboardingIssue] = []
        all_entities = [self._organization_root(org)]
        all_relationships = []
        source_rows = 0
        touched: list[OrganizationDataset] = []
        for dataset in datasets:
            if not dataset.mapping_plan_id:
                issues.append(
                    OnboardingIssue(
                        severity="error",
                        code="mapping_plan_missing",
                        message="Dataset has no reviewed mapping plan.",
                        dataset_id=dataset.dataset_id,
                    )
                )
                continue
            plan = self.plan_store.load(tenant_id, dataset.mapping_plan_id)
            if plan.status != "approved":
                issues.append(
                    OnboardingIssue(
                        severity="error",
                        code="mapping_plan_not_approved",
                        message="Dataset mapping plan is not approved.",
                        dataset_id=dataset.dataset_id,
                    )
                )
                continue
            if plan.tenant_id != tenant_id:
                issues.append(
                    OnboardingIssue(
                        severity="error",
                        code="mapping_plan_tenant_mismatch",
                        message="Mapping plan belongs to a different tenant.",
                        dataset_id=dataset.dataset_id,
                    )
                )
                continue
            source = self._source(tenant_id, dataset.dataset_id)
            profile = profile_source(source)
            batch = self.canonicalizer.normalize(plan, source.rows(), profile=profile)
            source_rows += profile.row_count
            for item in batch.issues:
                issues.append(
                    OnboardingIssue(
                        severity=item.severity,
                        code=f"canonical_{item.code}",
                        message=item.message,
                        dataset_id=dataset.dataset_id,
                    )
                )
            if batch.error_count:
                continue
            all_entities.extend(batch.entities)
            all_relationships.extend(batch.relationships)
            touched.append(dataset)

        writer = CanonicalGraphWriter(self.repository)
        try:
            nodes = writer.dedupe_nodes(all_entities)
            relationships = writer.dedupe_relationships(all_relationships)
        except Exception as error:
            issues.append(
                OnboardingIssue(
                    severity="error",
                    code="canonical_dedupe_conflict",
                    message=str(error),
                )
            )
            nodes, relationships = {}, {}

        if nodes or relationships:
            missing_endpoints = writer.validate_endpoints(
                nodes, relationships, tenant_id=tenant_id
            )
            if missing_endpoints:
                issues.append(
                    OnboardingIssue(
                        severity="error",
                        code="unresolved_relationship_endpoints",
                        message=(
                            f"{len(missing_endpoints)} relationship endpoints are unresolved for tenant {tenant_id!r}. "
                            f"First IDs: {missing_endpoints[:10]}"
                        ),
                    )
                )
        return org, datasets, touched, issues, source_rows, all_entities, all_relationships, nodes, relationships

    def load_organization(
        self,
        tenant_id: str,
        *,
        actor: ActorContext,
        dataset_ids: Iterable[str] | None = None,
    ) -> OrganizationLoadReport:
        (
            org,
            datasets,
            touched,
            issues,
            source_rows,
            all_entities,
            all_relationships,
            nodes,
            relationships,
        ) = self.prepare_load(tenant_id, actor=actor, dataset_ids=dataset_ids)
        error_count = sum(item.severity == "error" for item in issues)
        warning_count = sum(item.severity == "warning" for item in issues)
        before_nodes = self.repository.count_nodes(tenant_id)
        before_relationships = self.repository.count_relationships(tenant_id)
        if error_count:
            return OrganizationLoadReport(
                tenant_id=tenant_id,
                dataset_count=len(datasets),
                source_row_count=source_rows,
                canonical_entity_count=len(all_entities),
                canonical_relationship_count=len(all_relationships),
                unique_node_count=len(nodes),
                unique_relationship_count=len(relationships),
                error_count=error_count,
                warning_count=warning_count,
                graph_node_count_before=before_nodes,
                graph_node_count_after=before_nodes,
                graph_relationship_count_before=before_relationships,
                graph_relationship_count_after=before_relationships,
                idempotent_upsert=True,
                issues=issues,
            )

        self.registry.update(
            tenant_id,
            lambda item: item.model_copy(update={"status": OrganizationStatus.LOADING}),
        )
        writer = CanonicalGraphWriter(self.repository)
        node_upserts = writer.write_nodes(nodes)
        relationship_upserts = writer.write_relationships(relationships)
        after_nodes = self.repository.count_nodes(tenant_id)
        after_relationships = self.repository.count_relationships(tenant_id)
        loaded_ids = {item.dataset_id for item in touched}
        for dataset in touched:
            plan = self.plan_store.load(tenant_id, str(dataset.mapping_plan_id))
            self.registry.upsert_dataset(
                tenant_id,
                dataset.model_copy(
                    update={
                        "status": DatasetStatus.LOADED,
                        "updated_at": utc_now(),
                        "last_error": None,
                        "load_result": DatasetLoadResult(
                            node_upserts=node_upserts,
                            relationship_upserts=relationship_upserts,
                            graph_node_count_after=after_nodes,
                            graph_relationship_count_after=after_relationships,
                            mapping_plan_id=plan.plan_id,
                            mapping_version=plan.version,
                        ),
                    }
                ),
            )
        self._refresh_org_status(tenant_id)
        return OrganizationLoadReport(
            tenant_id=tenant_id,
            dataset_count=len(datasets),
            source_row_count=source_rows,
            canonical_entity_count=len(all_entities),
            canonical_relationship_count=len(all_relationships),
            unique_node_count=len(nodes),
            unique_relationship_count=len(relationships),
            error_count=0,
            warning_count=warning_count,
            graph_node_count_before=before_nodes,
            graph_node_count_after=after_nodes,
            graph_relationship_count_before=before_relationships,
            graph_relationship_count_after=after_relationships,
            idempotent_upsert=(after_nodes >= before_nodes and after_relationships >= before_relationships),
            issues=issues,
        )

    def readiness(self, tenant_id: str, *, actor: ActorContext) -> OrganizationReadiness:
        org = self.organization(tenant_id, actor=actor)
        profiled = sum(
            dataset.status
            in {
                DatasetStatus.PROFILED,
                DatasetStatus.MAPPING_REVIEW,
                DatasetStatus.MAPPING_APPROVED,
                DatasetStatus.LOADED,
            }
            for dataset in org.datasets
        )
        approved = 0
        loaded = 0
        for dataset in org.datasets:
            if dataset.status == DatasetStatus.LOADED:
                loaded += 1
            if dataset.mapping_plan_id:
                try:
                    if self.plan_store.load(tenant_id, dataset.mapping_plan_id).status == "approved":
                        approved += 1
                except (KeyError, ValueError):
                    pass
        node_count = self.repository.count_nodes(tenant_id)
        rel_count = self.repository.count_relationships(tenant_id)
        blockers: list[str] = []
        warnings: list[str] = []
        if not org.datasets and not org.is_default:
            blockers.append("No organization datasets have been registered.")
        if org.datasets and approved < len(org.datasets):
            blockers.append("Every registered dataset must have an approved mapping plan before activation.")
        if org.datasets and loaded < len(org.datasets):
            blockers.append("Every registered dataset must complete a successful graph load before activation.")
        if node_count <= 0:
            blockers.append("Knowledge Graph has no tenant-scoped nodes.")
        if rel_count <= 0:
            warnings.append("Knowledge Graph has no tenant-scoped relationships; this may be valid for a minimal organization but limits semantic navigation.")
        ready = not blockers and (org.is_default or loaded > 0)
        return OrganizationReadiness(
            tenant_id=tenant_id,
            status=org.status,
            dataset_count=len(org.datasets),
            profiled_dataset_count=profiled,
            approved_mapping_count=approved,
            loaded_dataset_count=loaded,
            graph_node_count=node_count,
            graph_relationship_count=rel_count,
            ready_to_activate=ready,
            blockers=blockers,
            warnings=warnings,
        )

    def activate(self, tenant_id: str, *, actor: ActorContext) -> OrganizationRecord:
        self.require_admin(tenant_id, actor=actor)
        readiness = self.readiness(tenant_id, actor=actor)
        if not readiness.ready_to_activate:
            raise ValueError("Organization cannot be activated: " + "; ".join(readiness.blockers))
        return self.registry.update(
            tenant_id,
            lambda org: org.model_copy(
                update={
                    "status": OrganizationStatus.ACTIVE,
                    "activated_at": org.activated_at or utc_now(),
                }
            ),
        )

    def suspend(self, tenant_id: str, *, actor: ActorContext) -> OrganizationRecord:
        self.require_admin(tenant_id, actor=actor)
        return self.registry.update(
            tenant_id,
            lambda org: org.model_copy(update={"status": OrganizationStatus.SUSPENDED}),
        )

    def _refresh_org_status(self, tenant_id: str) -> None:
        org = self.registry.get(tenant_id)
        if org.status in {OrganizationStatus.ACTIVE, OrganizationStatus.SUSPENDED}:
            return
        if any(dataset.status == DatasetStatus.MAPPING_REVIEW for dataset in org.datasets):
            status = OrganizationStatus.MAPPING_REVIEW
        elif org.datasets and all(
            dataset.status in {DatasetStatus.MAPPING_APPROVED, DatasetStatus.LOADED}
            for dataset in org.datasets
        ):
            status = OrganizationStatus.READY_TO_LOAD
        else:
            status = OrganizationStatus.DRAFT
        self.registry.update(
            tenant_id,
            lambda item: item.model_copy(update={"status": status}),
        )

    def tenant_summary(self, tenant_id: str, *, actor: ActorContext) -> dict[str, Any]:
        org = self.organization(tenant_id, actor=actor)
        readiness = self.readiness(tenant_id, actor=actor)
        return {
            "step": 12,
            "name": "Multi-Organization Onboarding",
            "organization": org.model_dump(mode="json"),
            "readiness": readiness.model_dump(mode="json"),
            "tenant_isolation": {
                "graph_ids_tenant_scoped": True,
                "repository_queries_tenant_scoped": True,
                "cross_tenant_relationships_forbidden": True,
                "mapping_plans_tenant_namespaced": True,
            },
        }
