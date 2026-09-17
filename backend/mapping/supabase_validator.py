from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontology.registry import DEFAULT_REGISTRY
from .supabase_schema import parse_tables_sql

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQL = ROOT / "database" / "tables.sql"
DEFAULT_MAPPING = ROOT / "backend" / "mapping" / "definitions" / "supabase_schema_mappings.json"


def validate_supabase_mapping(sql_file: Path = DEFAULT_SQL, mapping_file: Path = DEFAULT_MAPPING) -> dict[str, Any]:
    tables = parse_tables_sql(sql_file)
    payload = json.loads(mapping_file.read_text(encoding="utf-8"))
    issues: list[dict[str, str]] = []
    mapped_tables = {t["table"]: t for t in payload["tables"]}
    if set(mapped_tables) != set(tables):
        issues.append({"severity":"error","code":"supabase_table_set_mismatch","message":f"SQL={sorted(tables)} mapping={sorted(mapped_tables)}"})
    for table, columns in tables.items():
        mapped = mapped_tables.get(table)
        if not mapped:
            continue
        by_name = {c["column"]: c for c in mapped["columns"]}
        if set(by_name) != set(columns):
            issues.append({"severity":"error","code":"supabase_column_set_mismatch","message":table})
        for column, item in by_name.items():
            path = item.get("ontology_path")
            if path and not DEFAULT_REGISTRY.ontology_path_exists(path):
                issues.append({"severity":"error","code":"unknown_supabase_ontology_path","message":f"{table}.{column}->{path}"})
    errors=[x for x in issues if x['severity']=='error']
    return {"valid":not errors,"error_count":len(errors),"issues":issues,"table_count":len(tables),"column_count":sum(len(v) for v in tables.values())}
