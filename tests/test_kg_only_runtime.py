from __future__ import annotations

import csv
from pathlib import Path

from kg_runtime.bootstrap import bootstrap_directory
from kg_runtime.config import KGRuntimeConfig
from kg_runtime.materializer import GraphRuntimeMaterializer
from kg_runtime.store import MemoryRuntimeGraphStore
from service_refactor.config import Step9RuntimeConfig
from service_refactor.models import RuntimeMode


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["id"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_bootstrap_and_materialize_preserve_exact_tabular_shape(tmp_path: Path) -> None:
    source = tmp_path / "Data"
    _write_csv(source / "Employee_Profile.csv", [
        {"Employee_ID": "EMP001", "Employee_Name": "Ali", "Department_ID": "D1"},
        {"Employee_ID": "EMP002", "Employee_Name": "Sara", "Department_ID": "D2"},
    ])
    _write_csv(source / "Simulation" / "Simulation_Scenario_Catalog.csv", [
        {"Scenario_Code": "employee_promotion", "Scenario_Name": "Employee Promotion"},
    ])

    store = MemoryRuntimeGraphStore()
    report = bootstrap_directory(source_dir=source, tenant_id="ORG-1", store=store)
    assert report["dataset_count"] == 2
    assert report["row_count"] == 3

    config = KGRuntimeConfig(
        data_source="knowledge_graph",
        enforce_llm_graph_only=True,
        tenant_id="ORG-1",
        cache_dir=tmp_path / "cache",
        source_dir=source,
    )
    materializer = GraphRuntimeMaterializer(config=config, store=store)
    out = materializer.materialize()

    with (out / "Employee_Profile.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {"Employee_ID": "EMP001", "Employee_Name": "Ali", "Department_ID": "D1"},
        {"Employee_ID": "EMP002", "Employee_Name": "Sara", "Department_ID": "D2"},
    ]
    assert (out / "Simulation" / "Simulation_Scenario_Catalog.csv").is_file()

    status = materializer.status()
    assert status["runtime_data_source"] == "knowledge_graph"
    assert status["legacy_source_read_at_runtime"] is False
    assert status["dataset_count"] == 2
    assert status["row_count"] == 3


def test_materializer_refuses_partial_runtime_dataset(tmp_path: Path) -> None:
    source = tmp_path / "Data"
    _write_csv(source / "Employee_Profile.csv", [
        {"Employee_ID": "EMP001", "Employee_Name": "Ali"},
    ])
    store = MemoryRuntimeGraphStore()
    bootstrap_directory(source_dir=source, tenant_id="ORG-1", store=store)
    dataset = store.list_datasets(tenant_id="ORG-1")[0]
    store.rows[("ORG-1", dataset.dataset_hash)] = []

    config = KGRuntimeConfig(
        data_source="knowledge_graph",
        enforce_llm_graph_only=True,
        tenant_id="ORG-1",
        cache_dir=tmp_path / "cache",
        source_dir=source,
    )
    materializer = GraphRuntimeMaterializer(config=config, store=store)

    try:
        materializer.materialize()
    except RuntimeError as exc:
        assert "Refusing partial materialization" in str(exc)
    else:
        raise AssertionError("partial KG runtime data must not be accepted")


def test_kg_llm_graph_only_forces_step9_graph_only(monkeypatch) -> None:
    monkeypatch.setenv("STEP9_RUNTIME_MODE", "legacy")
    monkeypatch.setenv("STEP9_ALLOW_LEGACY_FALLBACK", "true")
    monkeypatch.setenv("KG_RUNTIME_DATA_SOURCE", "knowledge_graph")
    monkeypatch.setenv("KG_LLM_GRAPH_ONLY", "true")
    monkeypatch.setenv("STEP9_TENANT_ID", "ORG-1")

    config = Step9RuntimeConfig.from_env()
    assert config.mode == RuntimeMode.GRAPH_ONLY
    assert config.allow_legacy_fallback is False
    assert config.tenant_id == "ORG-1"
