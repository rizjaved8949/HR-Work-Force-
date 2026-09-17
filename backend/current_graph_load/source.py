"""Paginated read-only Supabase source adapter for Step 7."""
from __future__ import annotations

from typing import Any

from ingestion.sources import RecordsSource


class SupabaseReadError(RuntimeError):
    pass


class SupabaseTableReader:
    def __init__(self, client: Any, *, page_size: int = 1000) -> None:
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        self.client = client
        self.page_size = min(page_size, 10_000)

    def read_rows(self, table: str, *, max_rows: int | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        start = 0
        while True:
            end = start + self.page_size - 1
            try:
                response = self.client.table(table).select("*").range(start, end).execute()
            except Exception as error:  # pragma: no cover - network/provider specific
                raise SupabaseReadError(f"Failed reading Supabase table {table!r}: {error}") from error
            rows = list(getattr(response, "data", None) or [])
            if not all(isinstance(row, dict) for row in rows):
                raise SupabaseReadError(f"Supabase table {table!r} returned non-object rows")
            result.extend(dict(row) for row in rows)
            if max_rows is not None and len(result) >= max_rows:
                return result[:max_rows]
            if len(rows) < self.page_size:
                break
            start += self.page_size
        return result

    def source(self, table: str, *, max_rows: int | None = None) -> RecordsSource:
        return RecordsSource(
            self.read_rows(table, max_rows=max_rows),
            source_system="supabase",
            source_object=table,
            source_format="supabase",
        )
