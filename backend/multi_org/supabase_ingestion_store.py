"""Supabase persistence for raw multi-organization uploads.

Arbitrary partner schemas are stored as JSONB rows rather than creating or
ALTERing a physical table for every CSV.  This preserves every uploaded column
while keeping the relational schema stable and tenant-safe.  The ontology-shaped
projection is written separately to ``kg_nodes`` / ``kg_relationships``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseOrganizationIngestionStore:
    def __init__(
        self,
        *,
        client: Any,
        datasets_table: str = "org_ingestion_datasets",
        rows_table: str = "org_ingestion_rows",
        batch_size: int = 500,
    ) -> None:
        self.client = client
        self.datasets_table = datasets_table
        self.rows_table = rows_table
        self.batch_size = max(1, int(batch_size))

    @classmethod
    def from_env(cls) -> "SupabaseOrganizationIngestionStore":
        from auth.supabase_client import get_supabase_admin_client

        return cls(
            client=get_supabase_admin_client(),
            datasets_table=os.getenv("MULTI_ORG_DATASETS_TABLE", "org_ingestion_datasets"),
            rows_table=os.getenv("MULTI_ORG_ROWS_TABLE", "org_ingestion_rows"),
            batch_size=int(os.getenv("MULTI_ORG_SUPABASE_BATCH_SIZE", "500")),
        )

    def verify_schema(self) -> None:
        try:
            self.client.table(self.datasets_table).select("dataset_id").limit(1).execute()
            self.client.table(self.rows_table).select("dataset_id").limit(1).execute()
        except Exception as error:
            raise RuntimeError(
                "Organization ingestion tables are not installed in Supabase. "
                "Run backend/multi_org/sql/organization_ingestion_schema.sql in the Supabase SQL Editor."
            ) from error

    def replace_dataset_rows(
        self,
        *,
        tenant_id: str,
        dataset_id: str,
        source_system: str,
        source_object: str,
        source_format: str,
        rows: list[dict[str, Any]],
        columns: list[str],
        status: str = "staged",
        mapping_summary: dict[str, Any] | None = None,
    ) -> None:
        """Replace the raw snapshot for one stable tenant+dataset identity."""
        now = _now()
        dataset_row = {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "source_system": source_system,
            "source_object": source_object,
            "source_format": source_format,
            "row_count": len(rows),
            "column_names": list(columns),
            "mapping_summary": mapping_summary or {},
            "sync_status": status,
            "updated_at": now,
        }
        self.client.table(self.datasets_table).upsert(
            dataset_row, on_conflict="tenant_id,dataset_id"
        ).execute()
        # A re-upload is a new immutable snapshot for this dataset identity.  Raw
        # rows are replaced; graph writes remain idempotent upserts.
        (
            self.client.table(self.rows_table)
            .delete()
            .eq("tenant_id", tenant_id)
            .eq("dataset_id", dataset_id)
            .execute()
        )
        payload = [
            {
                "tenant_id": tenant_id,
                "dataset_id": dataset_id,
                "row_number": index,
                "row_data": dict(row),
                "created_at": now,
            }
            for index, row in enumerate(rows, start=1)
        ]
        for start in range(0, len(payload), self.batch_size):
            self.client.table(self.rows_table).insert(payload[start : start + self.batch_size]).execute()

    def update_status(
        self,
        *,
        tenant_id: str,
        dataset_id: str,
        status: str,
        mapping_summary: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"sync_status": status, "updated_at": _now()}
        if mapping_summary is not None:
            payload["mapping_summary"] = mapping_summary
        (
            self.client.table(self.datasets_table)
            .update(payload)
            .eq("tenant_id", tenant_id)
            .eq("dataset_id", dataset_id)
            .execute()
        )


DEFAULT_SUPABASE_INGESTION_STORE = None
