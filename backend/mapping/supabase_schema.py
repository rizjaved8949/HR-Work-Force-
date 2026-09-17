from __future__ import annotations

import re
from pathlib import Path

_CREATE_RE = re.compile(
    r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+"?([^"(\s]+)"?\s*\((.*?)\);',
    re.IGNORECASE | re.DOTALL,
)
_COLUMN_RE = re.compile(r'"([^"]+)"\s+([A-Za-z0-9_ ]+?)(?=,|$)', re.DOTALL)


def parse_tables_sql(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, dict[str, str]] = {}
    for table, body in _CREATE_RE.findall(text):
        columns: dict[str, str] = {}
        for name, sql_type in _COLUMN_RE.findall(body):
            columns[name] = " ".join(sql_type.split()).lower()
        result[table] = columns
    return result
