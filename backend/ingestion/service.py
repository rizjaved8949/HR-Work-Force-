"""Facade for roadmap Step 6: Data Mapping & Ingestion Layer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .canonicalizer import DEFAULT_CANONICALIZER, Canonicalizer
from .coverage import DEFAULT_COVERAGE_ANALYZER, ServiceCoverageAnalyzer
from .mapper import DEFAULT_MAPPING_SUGGESTER, OntologyMappingSuggester
from .models import MappingPlan, SourceSchemaProfile
from .profiler import profile_source
from .registry import DEFAULT_PLAN_REGISTRY, MappingPlanRegistry
from .sources import RecordSource
from .validator import DEFAULT_PLAN_VALIDATOR, MappingPlanValidator


class DataIngestionService:
    """Source-agnostic Step-6 workflow.

    No method in this class persists to the Knowledge Graph. That cutover is
    intentionally reserved for roadmap Step 7.
    """

    def __init__(
        self,
        *,
        ontology: OntologyRegistry = DEFAULT_REGISTRY,
        suggester: OntologyMappingSuggester = DEFAULT_MAPPING_SUGGESTER,
        validator: MappingPlanValidator = DEFAULT_PLAN_VALIDATOR,
        canonicalizer: Canonicalizer = DEFAULT_CANONICALIZER,
        coverage: ServiceCoverageAnalyzer = DEFAULT_COVERAGE_ANALYZER,
        plan_registry: MappingPlanRegistry = DEFAULT_PLAN_REGISTRY,
    ) -> None:
        self.ontology = ontology
        self.suggester = suggester
        self.validator = validator
        self.canonicalizer = canonicalizer
        self.coverage_analyzer = coverage
        self.plan_registry = plan_registry

    def profile(self, source: RecordSource) -> SourceSchemaProfile:
        return profile_source(source)

    def suggest_mappings(self, source: RecordSource) -> dict[str, Any]:
        profile = self.profile(source)
        proposals = self.suggester.propose_schema(profile)
        entity_types = {
            candidate.entity_type
            for proposal in proposals
            for candidate in proposal.candidates[:1]
            if candidate.confidence >= 0.80
        }
        return {
            "step": 6,
            "source_profile": profile.model_dump(mode="json"),
            "column_proposals": [item.model_dump(mode="json") for item in proposals],
            "relationship_candidates": self.suggester.relationship_candidates(entity_types),
            "policy": (
                "Suggestions are not approvals. Human-approved MappingPlan metadata is "
                "required before canonical transformation."
            ),
        }

    def validate_plan(self, plan: MappingPlan, source: RecordSource | None = None) -> dict:
        profile = self.profile(source) if source is not None else None
        issues = self.validator.validate(plan, profile=profile)
        return {
            "valid": not any(item.severity == "error" for item in issues),
            "error_count": sum(item.severity == "error" for item in issues),
            "warning_count": sum(item.severity == "warning" for item in issues),
            "issues": [item.model_dump(mode="json") for item in issues],
        }

    def approve_plan(self, plan: MappingPlan, *, approved_by: str) -> MappingPlan:
        if not approved_by.strip():
            raise ValueError("approved_by must not be empty")
        # Validate semantic structure before approval. Source-column presence can
        # be validated separately against a concrete source via validate_plan.
        issues = self.validator.validate(plan)
        errors = [item for item in issues if item.severity == "error"]
        if errors:
            raise ValueError("Mapping plan cannot be approved: " + "; ".join(item.message for item in errors))
        approved = plan.model_copy(
            update={
                "status": "approved",
                "approved_by": approved_by.strip(),
                "approved_at": datetime.now(timezone.utc),
            }
        )
        return approved

    def save_plan(self, plan: MappingPlan):
        return self.plan_registry.save(plan)

    def coverage(self, plan: MappingPlan) -> dict[str, Any]:
        return self.coverage_analyzer.report(plan)

    def canonicalize(self, source: RecordSource, plan: MappingPlan):
        if source.source_system != plan.source_system:
            raise ValueError(
                f"Source system {source.source_system!r} does not match plan {plan.source_system!r}"
            )
        if source.source_object != plan.source_object:
            raise ValueError(
                f"Source object {source.source_object!r} does not match plan {plan.source_object!r}"
            )
        if source.source_format != plan.source_format:
            raise ValueError(
                f"Source format {source.source_format!r} does not match plan {plan.source_format!r}"
            )
        profile = self.profile(source)
        return self.canonicalizer.normalize(plan, source.rows(), profile=profile)

    def dry_run(self, source: RecordSource, plan: MappingPlan) -> dict[str, Any]:
        batch = self.canonicalize(source, plan)
        return {
            "step": 6,
            "name": "Data Mapping & Ingestion Layer",
            "mode": "canonical_dry_run_no_graph_write",
            "source_profile": self.profile(source).model_dump(mode="json"),
            "batch_summary": batch.summary(),
            "issues": [item.model_dump(mode="json") for item in batch.issues],
            "service_coverage": self.coverage(plan),
        }


DEFAULT_INGESTION_SERVICE = DataIngestionService()
