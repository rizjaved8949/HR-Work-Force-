"""One-time source migration into the reserved Knowledge Graph runtime mirror."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from .store import RuntimeDataset, RuntimeGraphStore


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_hash(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:24]


def read_csv_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        rows = [
            {str(k): "" if v is None else str(v) for k, v in row.items()}
            for row in reader
        ]
    return columns, rows


def bootstrap_directory(
    *,
    source_dir: str | Path,
    tenant_id: str,
    store: RuntimeGraphStore,
) -> dict:
    root = Path(source_dir).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"KG runtime bootstrap source directory was not found: {root}")

    files = sorted(path for path in root.rglob("*.csv") if path.is_file())
    if not files:
        raise RuntimeError(f"No CSV files were found under {root}")

    total_rows = 0
    datasets: list[dict] = []
    for path in files:
        source_path = path.relative_to(root).as_posix()
        columns, rows = read_csv_rows(path)
        dataset = RuntimeDataset(
            source_path=source_path,
            columns=columns,
            row_count=len(rows),
            content_sha256=_sha256_file(path),
            dataset_hash=_dataset_hash(source_path),
        )
        store.replace_dataset(tenant_id=tenant_id, dataset=dataset, rows=rows)
        total_rows += len(rows)
        datasets.append({
            "source_path": source_path,
            "row_count": len(rows),
            "column_count": len(columns),
            "dataset_hash": dataset.dataset_hash,
        })

    return {
        "status": "synced",
        "tenant_id": tenant_id,
        "dataset_count": len(datasets),
        "row_count": total_rows,
        "source_dir": str(root),
        "datasets": datasets,
    }
