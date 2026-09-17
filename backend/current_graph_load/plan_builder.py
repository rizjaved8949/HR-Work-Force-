"""Build approved Step-6 MappingPlans from the already-verified Step-3 current schema mapping."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from graph.schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from ingestion.models import EntityIngestionRule, MappingPlan, PropertyMapping
from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .manifest import DEFAULT_STEP7_MANIFEST, CurrentLoadManifestRegistry
from .models import TableLoadSpec


MAPPING_FILE = Path(__file__).resolve().parents[1] / "mapping" / "definitions" / "supabase_schema_mappings.json"


class CurrentSupabasePlanBuilder:
    def __init__(
        self,
        *,
        manifest: CurrentLoadManifestRegistry = DEFAULT_STEP7_MANIFEST,
        ontology: OntologyRegistry = DEFAULT_REGISTRY,
        graph_schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
        mapping_file: str | Path = MAPPING_FILE,
    ) -> None:
        self.manifest = manifest
        self.ontology = ontology
        self.graph_schema = graph_schema
        self.mapping_file = Path(mapping_file)
        self._mapping = json.loads(self.mapping_file.read_text(encoding="utf-8"))

    def _table_mapping(self, table_name: str) -> dict:
        for item in self._mapping["tables"]:
            if item["table"] == table_name:
                return item
        raise KeyError(table_name)

    def build(self, *, tenant_id: str, table_spec: TableLoadSpec) -> MappingPlan:
        table_mapping = self._table_mapping(table_spec.table)
        allowed_entities = set(table_spec.entity_types)
        property_mappings: list[PropertyMapping] = []
        for column in table_mapping.get("columns", []):
            path = column.get("ontology_path")
            if not path or column.get("disposition") not in {"direct_property", "context_property"}:
                continue
            entity_type = path.split(".", 1)[0]
            if entity_type not in allowed_entities:
                continue
            prop = self.ontology.get_property(path)
            override = None
            if prop.semantic_status != "confirmed":
                override = (
                    "Current-project Step-3 mapping is verified, but this ontology property's "
                    "semantic definition/scale remains intentionally pending. Step 7 preserves "
                    "the source value without normalization or reinterpretation."
                )
            property_mappings.append(
                PropertyMapping(
                    source_column=column["column"],
                    ontology_path=path,
                    transform=("month_name_to_number" if table_spec.table == "organization_master" and column["column"] == "Fiscal_Year_Start_Month" else "semantic_cast"),
                    null_values=["", "null", "none", "n/a", "na", "nan"],
                    semantic_override_reason=override,
                )
            )

        entity_rules: list[EntityIngestionRule] = []
        for entity_type in table_spec.entity_types:
            identity = self.graph_schema.identity_rule(entity_type)
            if identity.get("mode") == "ontology_property":
                continue
            entity_rules.append(
                EntityIngestionRule(
                    entity_type=entity_type,
                    record_key_columns=table_spec.record_keys.get(entity_type, ["id"]),
                    valid_from_column=table_spec.valid_from.get(entity_type),
                    valid_to_column=table_spec.valid_to.get(entity_type),
                )
            )

        return MappingPlan(
            plan_id=f"step7:{table_spec.table}",
            version="1.0.0-step7",
            tenant_id=tenant_id,
            source_system="supabase",
            source_object=table_spec.table,
            source_format="supabase",
            ontology_version=self.manifest.load().ontology_version,
            status="approved",
            property_mappings=property_mappings,
            entity_rules=entity_rules,
            relationship_mappings=[],
            approved_by="Step-3 verified current-project mapping",
            approved_at=datetime.now(timezone.utc),
            notes=(
                "Auto-built only from the audited Step-3 current Supabase mapping and the "
                "curated Step-7 authoritative-source manifest. No fuzzy mapping is used."
            ),
        )


DEFAULT_STEP7_PLAN_BUILDER = CurrentSupabasePlanBuilder()
