"""Orchestrate the first real current Supabase -> HR Knowledge Graph load."""
from __future__ import annotations

from typing import Callable

from graph.factory import create_graph_repository_from_env
from graph.repository import GraphRepository
from ingestion.canonicalizer import DEFAULT_CANONICALIZER, Canonicalizer
from ingestion.profiler import profile_source
from ingestion.sources import RecordSource
from ingestion.validator import DEFAULT_PLAN_VALIDATOR, MappingPlanValidator

from .manifest import DEFAULT_STEP7_MANIFEST, CurrentLoadManifestRegistry
from .models import (
    Step7Issue,
    Step7LoadReport,
    Step7PreflightReport,
    TablePreflightReport,
)
from .plan_builder import DEFAULT_STEP7_PLAN_BUILDER, CurrentSupabasePlanBuilder
from .relationships import DEFAULT_CURRENT_RELATIONSHIP_BUILDER, CurrentRelationshipBuilder
from .source import SupabaseTableReader
from .writer import CanonicalGraphWriter


class CurrentSupabaseGraphLoadService:
    def __init__(
        self,
        *,
        repository: GraphRepository,
        source_factory: Callable[[str], RecordSource],
        manifest: CurrentLoadManifestRegistry = DEFAULT_STEP7_MANIFEST,
        plan_builder: CurrentSupabasePlanBuilder = DEFAULT_STEP7_PLAN_BUILDER,
        canonicalizer: Canonicalizer = DEFAULT_CANONICALIZER,
        plan_validator: MappingPlanValidator = DEFAULT_PLAN_VALIDATOR,
        relationship_builder: CurrentRelationshipBuilder = DEFAULT_CURRENT_RELATIONSHIP_BUILDER,
    ) -> None:
        self.repository = repository
        self.source_factory = source_factory
        self.manifest = manifest
        self.plan_builder = plan_builder
        self.canonicalizer = canonicalizer
        self.plan_validator = plan_validator
        self.relationship_builder = relationship_builder

    @classmethod
    def from_env(cls, *, page_size: int = 1000, verify_connections: bool = True):
        from auth.supabase_client import get_supabase_admin_client

        supabase = get_supabase_admin_client()
        reader = SupabaseTableReader(supabase, page_size=page_size)
        repository = create_graph_repository_from_env(verify_connectivity=verify_connections)
        return cls(repository=repository, source_factory=reader.source)

    def close(self) -> None:
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()

    def _selected_specs(self, tables: set[str] | None = None):
        specs = self.manifest.load().tables
        if tables is None:
            return specs

        known = {item.table for item in specs}
        unknown = sorted(tables - known)
        if unknown:
            raise ValueError("Unknown Step-7 table(s): " + ", ".join(unknown))

        return [item for item in specs if item.table in tables]

    def prepare(self, *, tenant_id: str, tables: set[str] | None = None):
        all_entities = []
        all_relationships = []
        issues: list[Step7Issue] = []
        table_reports: list[TablePreflightReport] = []
        source_rows = 0

        for spec in self._selected_specs(tables):
            try:
                source = self.source_factory(spec.table)
                rows = source.rows()
            except Exception as error:
                severity = "error" if spec.required else "warning"
                issues.append(
                    Step7Issue(
                        severity=severity,
                        code="supabase_table_read_failed",
                        message=str(error),
                        table=spec.table,
                    )
                )
                table_reports.append(
                    TablePreflightReport(
                        table=spec.table,
                        matching_csv=spec.matching_csv,
                        row_count=0,
                        entity_count=0,
                        relationship_count=0,
                        error_count=1 if severity == "error" else 0,
                        warning_count=1 if severity == "warning" else 0,
                        mapped_entity_types=spec.entity_types,
                    )
                )
                continue

            source_rows += len(rows)

            # A real Supabase table can legitimately exist with zero rows.
            # With no rows there is nothing to canonicalize, and a row-based
            # profiler cannot discover the table's columns. Treat this as a
            # warning rather than generating false "source column missing"
            # mapping errors.
            if not rows:
                issues.append(
                    Step7Issue(
                        severity="warning",
                        code="empty_source_table",
                        message=(
                            f"Supabase table {spec.table!r} exists but contains no rows; "
                            "mapping/canonicalization skipped for this table."
                        ),
                        table=spec.table,
                    )
                )
                table_reports.append(
                    TablePreflightReport(
                        table=spec.table,
                        matching_csv=spec.matching_csv,
                        row_count=0,
                        entity_count=0,
                        relationship_count=0,
                        error_count=0,
                        warning_count=1,
                        mapped_entity_types=spec.entity_types,
                    )
                )
                continue

            profile = profile_source(source)
            plan = self.plan_builder.build(tenant_id=tenant_id, table_spec=spec)
            plan_issues = self.plan_validator.validate(
                plan,
                profile=profile,
                require_approved=True,
            )
            local_issues = [
                Step7Issue(
                    severity=item.severity,
                    code=f"mapping_{item.code}",
                    message=item.message,
                    table=spec.table,
                    row_number=item.row_number,
                )
                for item in plan_issues
            ]

            if any(item.severity == "error" for item in local_issues):
                issues.extend(local_issues)
                table_reports.append(
                    TablePreflightReport(
                        table=spec.table,
                        matching_csv=spec.matching_csv,
                        row_count=len(rows),
                        entity_count=0,
                        relationship_count=0,
                        error_count=sum(
                            item.severity == "error" for item in local_issues
                        ),
                        warning_count=sum(
                            item.severity == "warning" for item in local_issues
                        ),
                        mapped_entity_types=spec.entity_types,
                    )
                )
                continue

            batch = self.canonicalizer.normalize(plan, rows, profile=profile)
            local_issues.extend(
                Step7Issue(
                    severity=item.severity,
                    code=f"canonical_{item.code}",
                    message=item.message,
                    table=spec.table,
                    row_number=item.row_number,
                )
                for item in batch.issues
            )

            relationships, relationship_issues = self.relationship_builder.build(
                table_spec=spec,
                rows=rows,
                batch=batch,
            )
            local_issues.extend(relationship_issues)
            issues.extend(local_issues)
            all_entities.extend(batch.entities)
            all_relationships.extend(relationships)

            table_reports.append(
                TablePreflightReport(
                    table=spec.table,
                    matching_csv=spec.matching_csv,
                    row_count=len(rows),
                    entity_count=len(batch.entities),
                    relationship_count=len(relationships),
                    error_count=sum(
                        item.severity == "error" for item in local_issues
                    ),
                    warning_count=sum(
                        item.severity == "warning" for item in local_issues
                    ),
                    mapped_entity_types=spec.entity_types,
                )
            )

        writer = CanonicalGraphWriter(self.repository)
        try:
            unique_nodes = writer.dedupe_nodes(all_entities)
            unique_relationships = writer.dedupe_relationships(all_relationships)
        except Exception as error:
            issues.append(
                Step7Issue(
                    severity="error",
                    code="canonical_dedupe_conflict",
                    message=str(error),
                )
            )
            unique_nodes = {}
            unique_relationships = {}

        if unique_nodes or unique_relationships:
            missing = writer.validate_endpoints(
                unique_nodes,
                unique_relationships,
                tenant_id=tenant_id,
            )
            if missing:
                issues.append(
                    Step7Issue(
                        severity="error",
                        code="unresolved_relationship_endpoints",
                        message=(
                            f"{len(missing)} relationship endpoint graph IDs are neither produced "
                            "by this load nor already present for the tenant. Fix source "
                            "referential integrity before load. "
                            f"First IDs: {missing[:10]}"
                        ),
                    )
                )

        report = Step7PreflightReport(
            tenant_id=tenant_id,
            manifest_version=self.manifest.load().version,
            table_count=len(self._selected_specs(tables)),
            source_row_count=source_rows,
            canonical_entity_count=len(all_entities),
            canonical_relationship_count=len(all_relationships),
            unique_node_count=len(unique_nodes),
            unique_relationship_count=len(unique_relationships),
            error_count=sum(item.severity == "error" for item in issues),
            warning_count=sum(item.severity == "warning" for item in issues),
            tables=table_reports,
            issues=issues,
            intentionally_not_loaded=self.manifest.load().intentionally_not_loaded,
            known_supabase_snapshot_gaps=self.manifest.load().known_supabase_snapshot_gaps,
        )
        return report, unique_nodes, unique_relationships

    def preflight(
        self,
        *,
        tenant_id: str,
        tables: set[str] | None = None,
    ) -> Step7PreflightReport:
        report, _, _ = self.prepare(tenant_id=tenant_id, tables=tables)
        return report

    def load(
        self,
        *,
        tenant_id: str,
        tables: set[str] | None = None,
    ) -> Step7LoadReport:
        report, nodes, relationships = self.prepare(
            tenant_id=tenant_id,
            tables=tables,
        )
        if not report.valid:
            raise RuntimeError(
                f"Step-7 preflight failed with {report.error_count} error(s); "
                "graph write blocked."
            )

        writer = CanonicalGraphWriter(self.repository)
        before_nodes = self.repository.count_nodes(tenant_id)
        before_relationships = self.repository.count_relationships(tenant_id)
        nodes_written = writer.write_nodes(nodes)
        relationships_written = writer.write_relationships(relationships)
        after_nodes = self.repository.count_nodes(tenant_id)
        after_relationships = self.repository.count_relationships(tenant_id)

        return Step7LoadReport(
            tenant_id=tenant_id,
            tables_loaded=report.table_count,
            source_rows=report.source_row_count,
            nodes_upserted=nodes_written,
            relationships_upserted=relationships_written,
            graph_node_count_before=before_nodes,
            graph_node_count_after=after_nodes,
            graph_relationship_count_before=before_relationships,
            graph_relationship_count_after=after_relationships,
        )
