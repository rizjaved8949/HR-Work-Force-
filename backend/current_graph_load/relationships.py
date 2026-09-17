"""Build Step-7 graph relationships from confirmed current-project references."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from graph.ids import make_node_graph_id, make_relationship_graph_id, make_source_record_identity
from graph.schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from ingestion.models import CanonicalBatch, CanonicalEntityRecord, CanonicalRelationshipRecord

from .models import EndpointSpec, LinkSpec, Step7Issue, TableLoadSpec


RELATIONSHIP_FILE = Path(__file__).resolve().parents[1] / "mapping" / "definitions" / "relationship_rules.json"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _record_key(row: dict[str, Any], columns: list[str]) -> str | None:
    parts: list[str] = []
    for column in columns:
        value = _text(row.get(column))
        if not value:
            return None
        parts.append(f"{column}={value}")
    return "|".join(parts)


class CurrentRelationshipBuilder:
    def __init__(
        self,
        *,
        relationship_file: str | Path = RELATIONSHIP_FILE,
        graph_schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
    ) -> None:
        self.relationship_file = Path(relationship_file)
        self.graph_schema = graph_schema
        self._rules = json.loads(self.relationship_file.read_text(encoding="utf-8"))["rules"]

    def step3_links_for(self, matching_csv: str) -> list[LinkSpec]:
        result: list[LinkSpec] = []
        for rule in self._rules:
            if rule.get("source_file") != matching_csv:
                continue
            required = list(rule.get("required_columns") or [])
            # Current Supabase Step-7 only auto-promotes rules with explicit source + target IDs.
            if len(required) != 2:
                continue
            source_rule = self.graph_schema.identity_rule(rule["source_entity"])
            target_rule = self.graph_schema.identity_rule(rule["target_entity"])
            if source_rule.get("mode") != "ontology_property" or target_rule.get("mode") != "ontology_property":
                continue
            result.append(
                LinkSpec.model_validate(
                    {
                        "source": {"mode": "business_id", "entity_type": rule["source_entity"], "column": required[0]},
                        "relation": rule["relation"],
                        "target": {"mode": "business_id", "entity_type": rule["target_entity"], "column": required[1]},
                        "skip_if_empty": True,
                    }
                )
            )
        return result

    @staticmethod
    def _row_entity(batch: CanonicalBatch, row_number: int, entity_type: str):
        matches = [
            item for item in batch.entities
            if item.row_number == row_number and item.entity_type == entity_type
        ]
        if len(matches) > 1:
            raise ValueError(f"Multiple {entity_type} records produced for row {row_number}")
        return matches[0] if matches else None

    def _endpoint_graph_id(
        self,
        *,
        endpoint: EndpointSpec,
        row: dict[str, Any],
        row_number: int,
        batch: CanonicalBatch,
        tenant_id: str,
        source_system: str,
        row_entity_index: dict[tuple[int, str], Any],
    ) -> str | None:
        if endpoint.mode == "row_entity":
            item = row_entity_index.get((row_number, endpoint.entity_type))
            return item.graph_id if item else None
        if endpoint.mode == "business_id":
            value = _text(row.get(str(endpoint.column)))
            if not value:
                return None
            return make_node_graph_id(
                tenant_id=tenant_id,
                entity_type=endpoint.entity_type,
                identity_key=value,
            )
        if endpoint.mode == "source_record_ref":
            key = _record_key(row, endpoint.record_key_columns)
            if not key:
                return None
            identity_key = make_source_record_identity(
                source_system=source_system,
                source_object=str(endpoint.source_object),
                source_record_key=key,
            )
            return make_node_graph_id(
                tenant_id=tenant_id,
                entity_type=endpoint.entity_type,
                identity_key=identity_key,
            )
        raise ValueError(f"Unsupported endpoint mode: {endpoint.mode}")

    def _append_business_reference_stub(
        self,
        *,
        endpoint: EndpointSpec,
        row: dict[str, Any],
        row_number: int,
        batch: CanonicalBatch,
        source_record_key: str,
    ) -> None:
        if endpoint.mode != "business_id":
            return
        value = _text(row.get(str(endpoint.column)))
        if not value:
            return
        rule = self.graph_schema.identity_rule(endpoint.entity_type)
        if rule.get("mode") != "ontology_property" or not rule.get("property"):
            return
        graph_id = make_node_graph_id(
            tenant_id=batch.tenant_id,
            entity_type=endpoint.entity_type,
            identity_key=value,
        )
        # Reference-only nodes contain no invented attributes: only the business ID
        # that was explicitly supplied by the referencing source row.
        batch.entities.append(
            CanonicalEntityRecord(
                tenant_id=batch.tenant_id,
                entity_type=endpoint.entity_type,
                graph_id=graph_id,
                identity_key=value,
                source_system=batch.source_system,
                source_object=batch.source_object,
                source_record_key=source_record_key,
                ontology_version=self.graph_schema.ontology_version,
                mapping_version=batch.mapping_version,
                properties={str(rule["property"]): value},
                row_number=row_number,
            )
        )

    def build(
        self,
        *,
        table_spec: TableLoadSpec,
        rows: list[dict[str, Any]],
        batch: CanonicalBatch,
    ) -> tuple[list[CanonicalRelationshipRecord], list[Step7Issue]]:
        links = self.step3_links_for(table_spec.matching_csv) + list(table_spec.links)
        relationships: list[CanonicalRelationshipRecord] = []
        issues: list[Step7Issue] = []
        # Validate each relationship triple once. Per-row pydantic GraphRelationship
        # construction is intentionally avoided because current evidence tables can
        # contain tens of thousands of rows. GraphRepository validates again on write.
        row_entity_index = {(item.row_number, item.entity_type): item for item in batch.entities}
        valid_links: list[LinkSpec] = []
        for link in links:
            if not self.graph_schema.allowed_relationship(
                link.source.entity_type, link.relation, link.target.entity_type
            ):
                issues.append(Step7Issue(
                    severity="error", code="relationship_not_in_ontology",
                    message=f"{link.source.entity_type}-{link.relation}->{link.target.entity_type} is not allowed",
                    table=table_spec.table,
                ))
            else:
                valid_links.append(link)
        for row_number, row in enumerate(rows, start=1):
            source_record_key = f"id={_text(row.get('id'))}" if _text(row.get("id")) else f"row={row_number}"
            for link in valid_links:
                self._append_business_reference_stub(
                    endpoint=link.source, row=row, row_number=row_number, batch=batch,
                    source_record_key=source_record_key,
                )
                self._append_business_reference_stub(
                    endpoint=link.target, row=row, row_number=row_number, batch=batch,
                    source_record_key=source_record_key,
                )
                try:
                    source_graph_id = self._endpoint_graph_id(
                        endpoint=link.source, row=row, row_number=row_number, batch=batch,
                        tenant_id=batch.tenant_id, source_system=batch.source_system,
                        row_entity_index=row_entity_index,
                    )
                    target_graph_id = self._endpoint_graph_id(
                        endpoint=link.target, row=row, row_number=row_number, batch=batch,
                        tenant_id=batch.tenant_id, source_system=batch.source_system,
                        row_entity_index=row_entity_index,
                    )
                except Exception as error:
                    issues.append(Step7Issue(
                        severity="error", code="relationship_endpoint_error", message=str(error),
                        table=table_spec.table, row_number=row_number,
                    ))
                    continue
                if not source_graph_id or not target_graph_id:
                    if not link.skip_if_empty:
                        issues.append(Step7Issue(
                            severity="error", code="relationship_endpoint_missing",
                            message=f"Missing endpoint for {link.source.entity_type}-{link.relation}->{link.target.entity_type}",
                            table=table_spec.table, row_number=row_number,
                        ))
                    continue

                graph_id = make_relationship_graph_id(
                    tenant_id=batch.tenant_id,
                    source_graph_id=source_graph_id,
                    relation_type=link.relation,
                    target_graph_id=target_graph_id,
                )
                relationships.append(
                    CanonicalRelationshipRecord(
                        tenant_id=batch.tenant_id,
                        relation_type=link.relation,
                        source_entity_type=link.source.entity_type,
                        target_entity_type=link.target.entity_type,
                        source_graph_id=source_graph_id,
                        target_graph_id=target_graph_id,
                        graph_id=graph_id,
                        source_system=batch.source_system,
                        source_object=batch.source_object,
                        source_record_key=source_record_key,
                        ontology_version=self.graph_schema.ontology_version,
                        mapping_version=batch.mapping_version,
                        row_number=row_number,
                    )
                )
        return relationships, issues


DEFAULT_CURRENT_RELATIONSHIP_BUILDER = CurrentRelationshipBuilder()
