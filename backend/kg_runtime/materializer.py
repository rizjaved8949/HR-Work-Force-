"""Materialize exact legacy table shapes from the Knowledge Graph runtime mirror.

The resulting files are disposable compatibility artifacts. They are generated
from kg_nodes and are never treated as an authoritative source. This lets the
existing deterministic services remain byte-for-byte compatible while their
runtime data source becomes the Knowledge Graph.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from .config import KGRuntimeConfig
from .store import RuntimeGraphStore, SupabaseRuntimeGraphStore


class GraphRuntimeMaterializer:
    def __init__(self, *, config: KGRuntimeConfig, store: RuntimeGraphStore) -> None:
        self.config = config
        self.store = store

    def output_dir(self, tenant_id: str | None = None) -> Path:
        tenant = str(tenant_id or self.config.tenant_id).strip()
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tenant)
        return self.config.cache_dir / safe

    def materialize(self, *, tenant_id: str | None = None, force: bool = False) -> Path:
        tenant = str(tenant_id or self.config.tenant_id).strip()
        datasets = self.store.list_datasets(tenant_id=tenant)
        if not datasets:
            raise RuntimeError(
                "Knowledge Graph runtime mirror is empty for tenant "
                f"{tenant!r}. Run `python -m kg_runtime.cli bootstrap --tenant-id {tenant}` "
                "before enabling KG_RUNTIME_DATA_SOURCE=knowledge_graph."
            )

        out = self.output_dir(tenant)
        manifest_path = out / ".kg_runtime_manifest.json"
        expected = {item.source_path: item.content_sha256 for item in datasets}
        if not force and manifest_path.is_file():
            try:
                current = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
            if current.get("datasets") == expected:
                missing = [item.source_path for item in datasets if not (out / item.source_path).is_file()]
                if not missing:
                    return out

        # Build into a sibling staging directory. A failed/timeout read must never
        # destroy a previously complete compatibility projection used by the old
        # deterministic services. Only swap the cache after every dataset passes
        # row-count validation.
        staging = out.with_name(out.name + ".building")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        total_rows = 0
        try:
            for dataset in datasets:
                rows = self.store.read_rows(tenant_id=tenant, dataset_hash=dataset.dataset_hash)
                if len(rows) != dataset.row_count:
                    raise RuntimeError(
                        f"KG runtime dataset {dataset.source_path!r} expected {dataset.row_count} rows "
                        f"but read {len(rows)}. Refusing partial materialization."
                    )
                target = staging / dataset.source_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(dataset.columns), extrasaction="ignore")
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({column: row.get(column, "") for column in dataset.columns})
                total_rows += len(rows)

            manifest = {
                "runtime_data_source": "knowledge_graph",
                "tenant_id": tenant,
                "mirror_tenant_id": self.config.mirror_tenant_id(tenant),
                "dataset_count": len(datasets),
                "row_count": total_rows,
                "datasets": expected,
            }
            (staging / ".kg_runtime_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            if out.exists():
                shutil.rmtree(out)
            staging.replace(out)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

        return out

    def status(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tenant = str(tenant_id or self.config.tenant_id).strip()
        datasets = self.store.list_datasets(tenant_id=tenant)
        return {
            "runtime_data_source": "knowledge_graph" if self.config.enabled else "legacy",
            "tenant_id": tenant,
            "mirror_tenant_id": self.config.mirror_tenant_id(tenant),
            "dataset_count": len(datasets),
            "row_count": sum(item.row_count for item in datasets),
            "cache_dir": str(self.output_dir(tenant)),
            "legacy_source_read_at_runtime": False if self.config.enabled else True,
        }


def ensure_materialized_data_dir(
    *,
    config: KGRuntimeConfig | None = None,
    store: RuntimeGraphStore | None = None,
) -> Path:
    cfg = config or KGRuntimeConfig.from_env()
    if not cfg.enabled:
        raise RuntimeError("KG runtime materializer called while KG_RUNTIME_DATA_SOURCE is not knowledge_graph")
    actual_store = store or SupabaseRuntimeGraphStore.from_env(cfg)
    return GraphRuntimeMaterializer(config=cfg, store=actual_store).materialize()
