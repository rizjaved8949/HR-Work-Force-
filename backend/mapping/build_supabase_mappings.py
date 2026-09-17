"""Build mapping metadata for the bundled Supabase/Postgres schema snapshot.

This does not connect to a live Supabase instance. The source of truth here is
`database/tables.sql` shipped with the project.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from mapping.supabase_schema import parse_tables_sql

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "database" / "tables.sql"
CSV_MAPPING = ROOT / "backend" / "mapping" / "definitions" / "current_data_mappings.json"
ONTOLOGY = ROOT / "backend" / "ontology" / "hr_ontology_v1.json"
OUT = ROOT / "backend" / "mapping" / "definitions" / "supabase_schema_mappings.json"


def clean_table_name(csv_file: str) -> str:
    return Path(csv_file).stem.lower().replace(" ", "_").replace("-", "_")


def main() -> None:
    tables = parse_tables_sql(SQL)
    csv_map = json.loads(CSV_MAPPING.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    by_table = {clean_table_name(d["source_file"]): d for d in csv_map["datasets"] if "/" not in d["source_file"]}
    field_paths: dict[str, list[str]] = defaultdict(list)
    for entity in ontology["entities"]:
        for prop in entity.get("properties", []):
            for field in prop.get("current_source_fields", []):
                field_paths[field].append(f"{entity['name']}.{prop['name']}")

    mapped_tables = []
    for table_name, columns in sorted(tables.items()):
        csv_def = by_table.get(table_name)
        csv_cols = {c["source_column"]: c for c in csv_def["columns"]} if csv_def else {}
        out_cols = []
        for column, sql_type in columns.items():
            if column == "id":
                out_cols.append({
                    "column": column,
                    "physical_type": sql_type,
                    "disposition": "database_surrogate_key",
                    "reason": "Postgres row identity; not an HR business identifier.",
                })
                continue
            if column in csv_cols:
                base = dict(csv_cols[column])
                base["column"] = base.pop("source_column")
                base["physical_type"] = sql_type
                out_cols.append(base)
                continue
            candidates = field_paths.get(column, [])
            if len(candidates) == 1:
                out_cols.append({
                    "column": column,
                    "physical_type": sql_type,
                    "disposition": "direct_property",
                    "ontology_path": candidates[0],
                    "transform": "semantic_cast_required",
                    "reason": "Supabase-only table column exactly matches one confirmed ontology source-field hint.",
                })
            else:
                out_cols.append({
                    "column": column,
                    "physical_type": sql_type,
                    "disposition": "supabase_only_operational_extension",
                    "reason": "Bundled SQL-only field is not consumed by the audited current AI services; no ontology meaning is guessed.",
                })
        mapped_tables.append({
            "table": table_name,
            "source_basis": "matching_current_csv" if csv_def else "bundled_sql_only",
            "matching_csv": csv_def["source_file"] if csv_def else None,
            "columns": out_cols,
        })

    payload = {
        "version": "1.0.0-step3",
        "schema_source": "database/tables.sql bundled with the uploaded project; live Supabase was not introspected",
        "physical_type_note": "The bundled SQL snapshot declares business columns as text. Ontology semantic datatypes/units remain authoritative and require casting/validation during ingestion.",
        "table_count": len(mapped_tables),
        "tables": mapped_tables,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
