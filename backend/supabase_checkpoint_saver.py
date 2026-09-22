"""Supabase-backed checkpoint saver for LangGraph conversation memory.

This keeps the agent's persisted state in the same Supabase project already used
by the application, while leaving the rest of the HR business logic untouched.
The saver is intentionally minimal: it persists the checkpoint payload and the
thread metadata required by the existing LangGraph conversation flow.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Sequence
from time import perf_counter
from typing import Any, Callable

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.memory import InMemorySaver

from auth.supabase_client import get_supabase_admin_client


logger = logging.getLogger(__name__)
checkpoint_timing_logger = logging.getLogger("hr_workforce.checkpoint_timing")


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _log_checkpoint_timing(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        **{key: value for key, value in fields.items() if value is not None},
    }
    checkpoint_timing_logger.info(
        "checkpoint_timing %s",
        json.dumps(payload, ensure_ascii=False, default=str),
    )


class SupabaseCheckpointSaver(BaseCheckpointSaver[str]):
    """Persist LangGraph checkpoints to Supabase tables.

    The implementation intentionally stores only the data needed for the app's
    existing thread-based conversational memory. Other graph memory features can
    be layered in later without changing the HR agent code.
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
        checkpoints_table: str = "agent_checkpoints",
        writes_table: str = "agent_checkpoint_writes",
        serde: Any | None = None,
    ) -> None:
        super().__init__(serde=serde)
        self.client_factory = client_factory or get_supabase_admin_client
        self.checkpoints_table = checkpoints_table
        self.writes_table = writes_table

    def _client(self) -> Any:
        return self.client_factory()

    def _table(self, table_name: str) -> Any:
        return self._client().table(table_name)

    def _row_to_checkpoint(self, row: dict[str, Any]) -> Checkpoint:
        checkpoint = row.get("checkpoint")
        if isinstance(checkpoint, str):
            checkpoint = json.loads(checkpoint)
        checkpoint = dict(checkpoint)

        channel_values = checkpoint.get("channel_values", {})
        if not isinstance(channel_values, dict):
            channel_values = {}
        checkpoint["channel_values"] = channel_values
        return checkpoint

    def _row_to_metadata(self, row: dict[str, Any]) -> CheckpointMetadata:
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return dict(metadata or {})

    def _latest_checkpoint_query(self, thread_id: str, checkpoint_ns: str = ""):
        query = (
            self._table(self.checkpoints_table)
            .select("*")
            .eq("thread_id", thread_id)
            .eq("checkpoint_ns", checkpoint_ns)
            .order("created_at", desc=True)
            .limit(1)
        )
        return query

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return None

        started = perf_counter()
        status = "hit"
        error_type: str | None = None
        row_count = 0
        pending_write_count = 0
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id")

        try:
            query = self._table(self.checkpoints_table).select("*")
            if checkpoint_id:
                query = query.eq("checkpoint_id", checkpoint_id)
            else:
                query = query.order("created_at", desc=True).limit(1)

            response = (
                query.eq("thread_id", thread_id)
                .eq("checkpoint_ns", checkpoint_ns)
                .execute()
            )

            rows = list(response.data or [])
            row_count = len(rows)
            if not rows:
                status = "miss"
                return None

            row = rows[0]
            checkpoint = self._row_to_checkpoint(row)
            metadata = self._row_to_metadata(row)

            parent_checkpoint_id = row.get("parent_checkpoint_id")
            pending_writes = self._load_pending_writes(thread_id, checkpoint_ns, checkpoint["id"])
            pending_write_count = len(pending_writes)

            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint["id"],
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=(
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": parent_checkpoint_id,
                        }
                    }
                    if parent_checkpoint_id
                    else None
                ),
                pending_writes=pending_writes,
            )
        except Exception as error:
            status = "error"
            error_type = type(error).__name__
            raise
        finally:
            _log_checkpoint_timing(
                "checkpoint_get_tuple",
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                elapsed_ms=_elapsed_ms(started),
                status=status,
                row_count=row_count,
                pending_write_count=pending_write_count,
                error_type=error_type,
            )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        base = self._table(self.checkpoints_table).select("*")
        if config:
            configurable = config.get("configurable", {})
            thread_id = configurable.get("thread_id")
            if thread_id:
                base = base.eq("thread_id", thread_id)
            checkpoint_ns = configurable.get("checkpoint_ns")
            if checkpoint_ns is not None:
                base = base.eq("checkpoint_ns", checkpoint_ns)

        response = base.order("created_at", desc=True).execute()
        rows = list(response.data or [])

        if filter:
            rows = [
                row for row in rows if all(row.get(key) == value for key, value in filter.items())
            ]

        if limit is not None:
            rows = rows[:limit]

        for row in rows:
            checkpoint = self._row_to_checkpoint(row)
            metadata = self._row_to_metadata(row)
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": row["thread_id"],
                        "checkpoint_ns": row["checkpoint_ns"],
                        "checkpoint_id": checkpoint["id"],
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=(
                    {
                        "configurable": {
                            "thread_id": row["thread_id"],
                            "checkpoint_ns": row["checkpoint_ns"],
                            "checkpoint_id": row.get("parent_checkpoint_id"),
                        }
                    }
                    if row.get("parent_checkpoint_id")
                    else None
                ),
                pending_writes=self._load_pending_writes(
                    row["thread_id"],
                    row["checkpoint_ns"],
                    checkpoint["id"],
                ),
            )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        configurable = config.get("configurable", {})
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        parent_checkpoint_id = configurable.get("checkpoint_id")
        started = perf_counter()
        status = "ok"
        error_type: str | None = None

        payload = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint["id"],
            "parent_checkpoint_id": parent_checkpoint_id,
            "checkpoint": json.dumps(checkpoint, default=str),
            "metadata": json.dumps(metadata, default=str),
            "created_at": checkpoint.get("ts"),
        }

        try:
            self._table(self.checkpoints_table).upsert(
                payload,
                on_conflict="thread_id,checkpoint_ns,checkpoint_id",
            ).execute()
        except Exception as error:
            status = "error"
            error_type = type(error).__name__
            raise
        finally:
            _log_checkpoint_timing(
                "checkpoint_put",
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint["id"],
                parent_checkpoint_id=parent_checkpoint_id,
                elapsed_ms=_elapsed_ms(started),
                status=status,
                error_type=error_type,
            )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config.get("configurable", {})
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable["checkpoint_id"]
        started = perf_counter()
        status = "ok"
        error_type: str | None = None

        try:
            rows = [
                {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "write_idx": write_idx,
                    "channel": channel,
                    "value": json.dumps(value, default=str),
                    "task_path": task_path,
                }
                for write_idx, (channel, value) in enumerate(writes)
            ]
            if rows:
                self._table(self.writes_table).upsert(
                    rows,
                    on_conflict="thread_id,checkpoint_ns,checkpoint_id,task_id,write_idx",
                ).execute()
        except Exception as error:
            status = "error"
            error_type = type(error).__name__
            raise
        finally:
            _log_checkpoint_timing(
                "checkpoint_put_writes",
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                task_id=task_id,
                write_count=len(writes),
                elapsed_ms=_elapsed_ms(started),
                status=status,
                error_type=error_type,
            )

    def _load_pending_writes(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[tuple[str, str, Any]]:
        started = perf_counter()
        status = "ok"
        error_type: str | None = None
        items: list[tuple[str, str, Any]] = []

        try:
            response = (
                self._table(self.writes_table)
                .select("*")
                .eq("thread_id", thread_id)
                .eq("checkpoint_ns", checkpoint_ns)
                .eq("checkpoint_id", checkpoint_id)
                .order("write_idx", desc=False)
                .execute()
            )

            for row in response.data or []:
                value = row.get("value")
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                items.append((row.get("task_id", ""), row.get("channel", ""), value))
            return items
        except Exception as error:
            status = "error"
            error_type = type(error).__name__
            raise
        finally:
            _log_checkpoint_timing(
                "checkpoint_pending_writes_loaded",
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                elapsed_ms=_elapsed_ms(started),
                status=status,
                write_count=len(items),
                error_type=error_type,
            )

    def delete_thread(self, thread_id: str) -> None:
        self._table(self.writes_table).delete().eq("thread_id", thread_id).execute()
        self._table(self.checkpoints_table).delete().eq("thread_id", thread_id).execute()

    def delete_for_runs(self, run_ids: Sequence[str]) -> None:
        for run_id in run_ids:
            self._table(self.checkpoints_table).delete().eq("run_id", run_id).execute()

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        source_rows = (
            self._table(self.checkpoints_table)
            .select("*")
            .eq("thread_id", source_thread_id)
            .execute()
        )
        for row in source_rows.data or []:
            payload = dict(row)
            payload["thread_id"] = target_thread_id
            payload.pop("id", None)
            self._table(self.checkpoints_table).upsert(
                payload,
                on_conflict="thread_id,checkpoint_ns,checkpoint_id",
            ).execute()


def create_agent_checkpointer() -> BaseCheckpointSaver[str] | InMemorySaver:
    """Create a durable checkpoint saver when Supabase is available.

    If the persistent store is unavailable, return an in-memory saver to keep the
    application running without changing the agent's runtime behavior.
    """

    enabled = os.getenv("USE_AGENT_SUPABASE_MEMORY", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if not enabled:
        logger.warning(
            "Agent Supabase memory is disabled; using InMemorySaver."
        )
        return InMemorySaver()

    try:
        saver = SupabaseCheckpointSaver(client_factory=get_supabase_admin_client)
        saver._table(saver.checkpoints_table).select("thread_id").limit(1).execute()
        logger.info(
            "Agent Supabase memory is active; using table %s.",
            saver.checkpoints_table,
        )
        return saver
    except Exception as error:
        require_persistent_memory = (
            os.getenv("REQUIRE_AGENT_SUPABASE_MEMORY", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        if require_persistent_memory:
            raise RuntimeError(
                "Supabase agent memory is required but could not be initialized. "
                "Check the agent memory tables and Supabase credentials."
            ) from error

        logger.exception(
            "Supabase agent memory unavailable; falling back to InMemorySaver."
        )
        return InMemorySaver()
