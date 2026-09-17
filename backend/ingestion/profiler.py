"""Generic source profiler for Step 6."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .models import SourceColumnProfile, SourceSchemaProfile
from .sources import RecordSource


def _infer_type(values: list[Any]) -> str:
    vals = [value for value in values if value is not None and str(value).strip() != ""]
    if not vals:
        return "empty"
    if all(isinstance(v, bool) for v in vals):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "integer"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in vals):
        return "decimal"
    if all(isinstance(v, datetime) for v in vals):
        return "datetime"
    if all(isinstance(v, date) for v in vals):
        return "date"

    texts = [str(v).strip() for v in vals]
    lowered = {v.casefold() for v in texts}
    if lowered <= {"yes", "no", "true", "false", "0", "1", "y", "n"}:
        return "boolean_like"
    try:
        parsed = [int(v) for v in texts]
        if len(parsed) == len(texts):
            return "integer"
    except (TypeError, ValueError):
        pass
    try:
        parsed = [float(v) for v in texts]
        if len(parsed) == len(texts):
            return "decimal"
    except (TypeError, ValueError):
        pass
    iso_date_like = 0
    for text in texts:
        if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
            iso_date_like += 1
    if iso_date_like == len(texts):
        return "date_like"
    return "string"


def profile_source(source: RecordSource, *, sample_limit: int = 5) -> SourceSchemaProfile:
    rows = source.rows()
    ordered_columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            name = str(key)
            if name not in seen:
                seen.add(name)
                ordered_columns.append(name)

    columns: list[SourceColumnProfile] = []
    for name in ordered_columns:
        values = [row.get(name) for row in rows]
        present = [value for value in values if value is not None and str(value).strip() != ""]
        samples: list[str] = []
        for value in present:
            text = str(value)
            if text not in samples:
                samples.append(text)
            if len(samples) >= sample_limit:
                break
        columns.append(
            SourceColumnProfile(
                name=name,
                non_empty=len(present),
                empty=len(values) - len(present),
                observed_type=_infer_type(values),
                sample_values=samples,
            )
        )
    return SourceSchemaProfile(
        source_system=source.source_system,
        source_object=source.source_object,
        source_format=source.source_format,
        row_count=len(rows),
        columns=columns,
    )
