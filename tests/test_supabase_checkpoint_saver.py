import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from langgraph.checkpoint.base import Checkpoint

from supabase_checkpoint_saver import SupabaseCheckpointSaver


class FakeSupabaseClient:
    def __init__(self):
        self.tables = {}
        self.upsert_calls = []

    def table(self, name):
        return FakeTable(self, name)


class FakeTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self._query = {}

    def select(self, *_args, **_kwargs):
        self._query["select"] = True
        return self

    def eq(self, key, value):
        self._query.setdefault("filters", []).append((key, value))
        return self

    def order(self, key, desc=False):
        self._query["order"] = (key, desc)
        return self

    def limit(self, value):
        self._query["limit"] = value
        return self

    def maybe_single(self):
        self._query["single"] = True
        return self

    def upsert(self, payload, on_conflict=None):
        self.client.upsert_calls.append((self.name, payload, on_conflict))
        self._query["upsert"] = {"payload": payload, "on_conflict": on_conflict}
        table_rows = self.client.tables.setdefault(self.name, [])
        if isinstance(payload, list):
            table_rows.extend(payload)
            self._last_result = type("Resp", (), {"data": payload})()
            return self
        key = (payload["thread_id"], payload["checkpoint_ns"], payload["checkpoint_id"])
        for idx, row in enumerate(table_rows):
            if (
                row["thread_id"],
                row["checkpoint_ns"],
                row["checkpoint_id"],
            ) == key:
                table_rows[idx] = payload
                self._last_result = type("Resp", (), {"data": [payload]})()
                return self
        table_rows.append(payload)
        self._last_result = type("Resp", (), {"data": [payload]})()
        return self

    def execute(self):
        table_rows = self.client.tables.setdefault(self.name, [])
        rows = list(table_rows)
        filters = self._query.get("filters", [])
        for key, value in filters:
            rows = [r for r in rows if r.get(key) == value]
        if self._query.get("single"):
            data = rows[0] if rows else None
            self._last_result = type("Resp", (), {"data": data if data is not None else []})()
            return self
        if self._query.get("order"):
            key, desc = self._query["order"]
            rows = sorted(rows, key=lambda r: r.get(key, ""), reverse=desc)
        limit = self._query.get("limit")
        if limit is not None:
            rows = rows[:limit]
        self._last_result = type("Resp", (), {"data": rows})()
        return self

    @property
    def data(self):
        return getattr(self, "_last_result", type("Resp", (), {"data": []})()).data


def test_supabase_checkpoint_saver_persists_thread_state():
    client = FakeSupabaseClient()
    saver = SupabaseCheckpointSaver(client_factory=lambda: client)

    config = {"configurable": {"thread_id": "thread-123"}}
    checkpoint: Checkpoint = {
        "v": 1,
        "id": "cp-1",
        "ts": "2026-01-01T00:00:00Z",
        "channel_values": {"messages": ["hello"]},
        "channel_versions": {"messages": "v1"},
        "versions_seen": {},
        "updated_channels": ["messages"],
    }
    metadata = {"source": "input", "step": 0}

    stored_config = saver.put(config, checkpoint, metadata, {"messages": "v1"})
    roundtrip = saver.get_tuple(stored_config)

    assert roundtrip is not None
    assert roundtrip.checkpoint["channel_values"]["messages"] == ["hello"]
    assert roundtrip.metadata["source"] == "input"
    assert roundtrip.checkpoint["id"] == "cp-1"


def test_supabase_checkpoint_writes_use_one_batch_upsert():
    client = FakeSupabaseClient()
    saver = SupabaseCheckpointSaver(client_factory=lambda: client)
    config = {
        "configurable": {
            "thread_id": "thread-123",
            "checkpoint_ns": "",
            "checkpoint_id": "cp-1",
        }
    }

    saver.put_writes(
        config,
        [("messages", "first"), ("messages", "second")],
        task_id="task-1",
    )

    write_calls = [call for call in client.upsert_calls if call[0] == "agent_checkpoint_writes"]
    assert len(write_calls) == 1
    assert len(write_calls[0][1]) == 2
