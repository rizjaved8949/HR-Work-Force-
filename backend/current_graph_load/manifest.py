from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import CurrentSupabaseLoadManifest, TableLoadSpec


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST_FILE = PACKAGE_DIR / "definitions" / "current_supabase_load_manifest.json"


class CurrentLoadManifestRegistry:
    def __init__(self, path: str | Path = DEFAULT_MANIFEST_FILE) -> None:
        self.path = Path(path)

    @lru_cache(maxsize=1)
    def load(self) -> CurrentSupabaseLoadManifest:
        return CurrentSupabaseLoadManifest.model_validate_json(
            self.path.read_text(encoding="utf-8")
        )

    def table(self, table_name: str) -> TableLoadSpec:
        for item in self.load().tables:
            if item.table == table_name:
                return item
        raise KeyError(table_name)


DEFAULT_STEP7_MANIFEST = CurrentLoadManifestRegistry()
