from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    non_empty: int
    empty: int
    observed_type: str


@dataclass(frozen=True)
class FileProfile:
    source_file: str
    row_count: int
    columns: tuple[ColumnProfile, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "row_count": self.row_count,
            "column_count": len(self.columns),
            "columns": [asdict(item) for item in self.columns],
        }


def _infer_type(values: list[str]) -> str:
    vals = [v.strip() for v in values if v is not None and str(v).strip() != ""]
    if not vals:
        return "empty"
    lowered = {v.casefold() for v in vals}
    if lowered <= {"yes", "no", "true", "false", "0", "1"}:
        return "boolean_like"
    try:
        ints = [int(v) for v in vals]
        if len(ints) == len(vals):
            return "integer"
    except Exception:
        pass
    try:
        nums = [float(v) for v in vals]
        if len(nums) == len(vals):
            return "decimal"
    except Exception:
        pass
    # ISO-like dates are the dominant date format in the supplied data.
    date_like = 0
    for v in vals:
        if len(v) >= 10 and v[4:5] == "-" and v[7:8] == "-":
            date_like += 1
    if date_like == len(vals):
        return "date_like"
    return "string"


def profile_csv(path: Path, relative_to: Path | None = None) -> FileProfile:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    cols: list[ColumnProfile] = []
    for field in fields:
        values = [row.get(field, "") for row in rows]
        non_empty = sum(1 for v in values if v is not None and str(v).strip() != "")
        cols.append(
            ColumnProfile(
                name=field,
                non_empty=non_empty,
                empty=len(values) - non_empty,
                observed_type=_infer_type(["" if v is None else str(v) for v in values]),
            )
        )
    source = str(path.relative_to(relative_to)) if relative_to else str(path)
    return FileProfile(source_file=source.replace("\\", "/"), row_count=len(rows), columns=tuple(cols))


def profile_data_directory(data_dir: Path) -> list[FileProfile]:
    return [profile_csv(path, data_dir) for path in sorted(data_dir.rglob("*.csv"))]
