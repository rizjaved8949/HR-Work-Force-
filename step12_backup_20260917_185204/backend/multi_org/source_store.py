"""Tenant-scoped staging store for organization source rows.

Step 12 stages normalized row dictionaries locally so profiling, mapping review,
dry-run and graph load all operate on the exact same immutable dataset snapshot.
Production object storage/database persistence is a Step-13 concern.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ingestion.sources import CSVSource, JSONArraySource, RecordsSource, XLSXSource

from .registry import validate_safe_id, validate_tenant_id


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = PACKAGE_DIR / "workspace" / "sources"


class OrganizationSourceStore:
    def __init__(self, root: str | Path = DEFAULT_SOURCE_DIR) -> None:
        self.root = Path(root)

    def _path(self, tenant_id: str, dataset_id: str) -> Path:
        tenant = validate_tenant_id(tenant_id)
        dataset = validate_safe_id(dataset_id, name="dataset_id")
        return self.root / tenant / f"{dataset}.json"

    def save_rows(
        self,
        *,
        tenant_id: str,
        dataset_id: str,
        source_system: str,
        source_object: str,
        source_format: str,
        rows: list[dict[str, Any]],
    ) -> str:
        path = self._path(tenant_id, dataset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "source_system": str(source_system).strip(),
            "source_object": str(source_object).strip(),
            "source_format": str(source_format).strip(),
            "rows": [dict(row) for row in rows],
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return str(path.relative_to(self.root))

    def load_source(self, *, tenant_id: str, dataset_id: str) -> RecordsSource:
        path = self._path(tenant_id, dataset_id)
        if not path.is_file():
            raise KeyError(f"Source snapshot not found for dataset {dataset_id!r}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("tenant_id") != tenant_id or payload.get("dataset_id") != dataset_id:
            raise ValueError("Tenant/dataset metadata mismatch in staged source snapshot")
        rows = payload.get("rows") or []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Staged source rows are invalid")
        return RecordsSource(
            rows,
            source_system=str(payload["source_system"]),
            source_object=str(payload["source_object"]),
            source_format=str(payload["source_format"]),
        )

    def import_file(
        self,
        path: str | Path,
        *,
        tenant_id: str,
        dataset_id: str,
        source_system: str | None = None,
        source_object: str | None = None,
        sheet_name: str | None = None,
    ) -> tuple[str, int, str, str, str]:
        source_path = Path(path)
        suffix = source_path.suffix.lower()
        if suffix == ".csv":
            source = CSVSource(
                source_path,
                source_system=source_system or "csv",
                source_object=source_object or source_path.name,
            )
        elif suffix == ".json":
            source = JSONArraySource(
                source_path,
                source_system=source_system or "json",
                source_object=source_object or source_path.name,
            )
        elif suffix in {".xlsx", ".xlsm"}:
            source = XLSXSource(
                source_path,
                sheet_name=sheet_name,
                source_system=source_system or "xlsx",
                source_object=source_object or (
                    f"{source_path.name}#{sheet_name}" if sheet_name else source_path.name
                ),
            )
        else:
            raise ValueError("Supported onboarding file types are CSV, JSON, XLSX and XLSM")
        rows = source.rows()
        storage_key = self.save_rows(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            source_system=source.source_system,
            source_object=source.source_object,
            source_format=source.source_format,
            rows=rows,
        )
        return storage_key, len(rows), source.source_system, source.source_object, source.source_format


DEFAULT_SOURCE_STORE = OrganizationSourceStore()
