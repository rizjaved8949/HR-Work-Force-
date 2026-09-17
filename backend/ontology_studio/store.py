"""Atomic local review store for Step-10 management workflows.

The store holds review metadata only. It never overwrites the active ontology
or mapping definitions. Production persistence can move to Supabase in Step 13
without changing the Ontology Studio service contract.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STORE_FILE = PACKAGE_DIR / "workspace" / "studio_reviews.json"


class StudioReviewStore:
    def __init__(self, path: str | Path = DEFAULT_STORE_FILE) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _empty() -> dict[str, list[dict[str, Any]]]:
        return {"mapping_reviews": [], "change_requests": []}

    def load(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            if not self.path.exists():
                return self._empty()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return self._empty()
            payload.setdefault("mapping_reviews", [])
            payload.setdefault("change_requests", [])
            return payload

    def save(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.path)

    def append(self, bucket: str, item: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload[bucket].append(item)
            self.save(payload)
            return item

    def update(self, bucket: str, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            for item in payload[bucket]:
                if item.get("id") == item_id:
                    item.update(updates)
                    self.save(payload)
                    return item
            raise KeyError(item_id)


DEFAULT_STUDIO_STORE = StudioReviewStore()
