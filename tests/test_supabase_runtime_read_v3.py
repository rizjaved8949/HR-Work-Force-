from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from kg_runtime.config import KGRuntimeConfig
from kg_runtime.store import RUNTIME_ROW_ENTITY, SupabaseRuntimeGraphStore


class TimeoutError57014(Exception):
    code = "57014"


class Response:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows, fail_large_once):
        self.rows = rows
        self.filters = []
        self._limit = None
        self._order = None
        self.fail_large_once = fail_large_once
        self.range_called = False

    def select(self, *_args, **_kwargs): return self
    def eq(self, key, value): self.filters.append(("eq", key, value)); return self
    def like(self, key, value): self.filters.append(("like", key, value)); return self
    def gt(self, key, value): self.filters.append(("gt", key, value)); return self
    def order(self, key): self._order = key; return self
    def limit(self, value): self._limit = int(value); return self
    def range(self, *_args, **_kwargs):
        self.range_called = True
        raise AssertionError("OFFSET/range pagination must not be used")

    def execute(self):
        if self.fail_large_once[0] and (self._limit or 0) >= 500:
            self.fail_large_once[0] = False
            raise TimeoutError57014("canceling statement due to statement timeout")
        data = list(self.rows)
        for kind, key, value in self.filters:
            if kind == "eq":
                data = [r for r in data if r.get(key) == value]
            elif kind == "like":
                assert value.endswith("%")
                prefix = value[:-1]
                data = [r for r in data if str(r.get(key, "")).startswith(prefix)]
            elif kind == "gt":
                data = [r for r in data if str(r.get(key, "")) > value]
        if self._order:
            data.sort(key=lambda r: str(r.get(self._order, "")))
        if self._limit is not None:
            data = data[: self._limit]
        return Response(data)


class FakeTable:
    def __init__(self, rows, fail_large_once):
        self.rows = rows
        self.fail_large_once = fail_large_once
    def select(self, *args, **kwargs):
        return FakeQuery(self.rows, self.fail_large_once).select(*args, **kwargs)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.fail_large_once = [True]
    def table(self, _name):
        return FakeTable(self.rows, self.fail_large_once)


def test_read_rows_uses_prefix_keyset_and_timeout_backoff(monkeypatch):
    monkeypatch.setenv("KG_RUNTIME_READ_PAGE_SIZE", "500")
    tenant = "ORG-1"
    mirror = "__KG_RUNTIME__::ORG-1"
    dataset_hash = "abc123"
    prefix = f"runtime-row:{dataset_hash}:"
    rows = []
    for i in range(1, 761):
        rows.append({
            "tenant_id": mirror,
            "graph_id": prefix + f"{i:09d}",
            "entity_type": RUNTIME_ROW_ENTITY,
            "properties": {"rowData": {"id": str(i)}},
        })
    # Noise from another dataset/tenant must not leak into the result.
    rows.append({
        "tenant_id": mirror,
        "graph_id": "runtime-row:other:000000001",
        "entity_type": RUNTIME_ROW_ENTITY,
        "properties": {"rowData": {"id": "bad"}},
    })
    rows.append({
        "tenant_id": "__KG_RUNTIME__::OTHER",
        "graph_id": prefix + "000000001",
        "entity_type": RUNTIME_ROW_ENTITY,
        "properties": {"rowData": {"id": "bad2"}},
    })

    cfg = KGRuntimeConfig(data_source="knowledge_graph", tenant_id=tenant)
    store = SupabaseRuntimeGraphStore(client=FakeClient(rows), config=cfg)
    result = store.read_rows(tenant_id=tenant, dataset_hash=dataset_hash)

    assert len(result) == 760
    assert result[0]["id"] == "1"
    assert result[-1]["id"] == "760"
    assert store.client.fail_large_once[0] is False


def test_materializer_keeps_last_good_cache_on_partial_failure(tmp_path):
    from kg_runtime.materializer import GraphRuntimeMaterializer
    from kg_runtime.store import MemoryRuntimeGraphStore, RuntimeDataset

    cfg = KGRuntimeConfig(
        data_source="knowledge_graph",
        tenant_id="ORG-1",
        cache_dir=tmp_path / "cache",
    )
    store = MemoryRuntimeGraphStore()
    dataset = RuntimeDataset(
        source_path="Employee_Profile.csv",
        columns=("id",),
        row_count=1,
        content_sha256="sha1",
        dataset_hash="hash1",
    )
    store.replace_dataset(tenant_id="ORG-1", dataset=dataset, rows=[{"id": "1"}])
    materializer = GraphRuntimeMaterializer(config=cfg, store=store)
    out = materializer.materialize()
    original = (out / "Employee_Profile.csv").read_text(encoding="utf-8-sig")

    # Force a rebuild with metadata that expects two rows but only one row stored.
    broken = RuntimeDataset(
        source_path="Employee_Profile.csv",
        columns=("id",),
        row_count=2,
        content_sha256="sha2",
        dataset_hash="hash2",
    )
    store.datasets.clear()
    store.rows.clear()
    store.replace_dataset(tenant_id="ORG-1", dataset=broken, rows=[{"id": "1"}])

    try:
        materializer.materialize(force=True)
    except RuntimeError as exc:
        assert "Refusing partial materialization" in str(exc)
    else:
        raise AssertionError("partial rebuild should fail")

    assert (out / "Employee_Profile.csv").read_text(encoding="utf-8-sig") == original
    assert not out.with_name(out.name + ".building").exists()
