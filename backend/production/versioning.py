"""Deterministic release/version metadata for Step 13."""
from __future__ import annotations

import json
import platform
from pathlib import Path

from .config import ProductionSettings
from .models import VersionInfo

ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def current_version_info(
    *,
    root: Path = ROOT,
    settings: ProductionSettings | None = None,
) -> VersionInfo:
    settings = settings or ProductionSettings.from_env()
    release_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    ontology = _json(root / "backend" / "ontology" / "hr_ontology_v1.json")
    mapping = _json(root / "backend" / "mapping" / "definitions" / "current_data_mappings.json")
    graph = _json(root / "backend" / "graph" / "graph_model_v1.json")
    return VersionInfo(
        release_version=release_version,
        api_version="3.0.0",
        ontology_version=str(ontology.get("version", "unknown")),
        mapping_version=str(mapping.get("version", "unknown")),
        graph_model_version=str(graph.get("version", "unknown")),
        python_runtime=platform.python_version(),
        release_commit=settings.release_commit,
        build_time=settings.build_time,
    )
