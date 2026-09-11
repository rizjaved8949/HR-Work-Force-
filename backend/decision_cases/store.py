from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from .exceptions import DecisionCaseStorageError
from .schemas import DecisionCaseDraft, DecisionCaseRecord


ACTIONABLE_STATUSES = {"Open", "Under Review", "In Progress"}
CSV_CASE_COLUMNS = [
    "id",
    "case_key",
    "rule_id",
    "case_type",
    "subject_type",
    "subject_id",
    "employee_id",
    "position_id",
    "department_id",
    "department",
    "priority",
    "display_rank",
    "title",
    "reason",
    "evidence_json",
    "suggested_action",
    "data_as_of",
    "status",
    "is_trigger_active",
    "detected_at",
    "last_evaluated_at",
    "resolved_at",
    "closed_at",
]


class DecisionCaseStore(Protocol):
    def sync(self, drafts: list[DecisionCaseDraft], evaluated_at: datetime) -> None: ...
    def list_records(self) -> list[DecisionCaseRecord]: ...
    def get(self, case_id: str) -> DecisionCaseRecord | None: ...
    def update_status(self, case_id: str, status: str) -> DecisionCaseRecord | None: ...


class InMemoryDecisionCaseStore:
    """Test-only store with the same sync semantics as CSV/Supabase."""

    def __init__(self) -> None:
        self._records: dict[str, DecisionCaseRecord] = {}

    def sync(self, drafts: list[DecisionCaseDraft], evaluated_at: datetime) -> None:
        active_keys = {draft.case_key for draft in drafts}

        for key, record in list(self._records.items()):
            if record.is_trigger_active and key not in active_keys:
                self._records[key] = record.model_copy(update={
                    "is_trigger_active": False,
                    "last_evaluated_at": evaluated_at,
                })

        for draft in drafts:
            existing = self._records.get(draft.case_key)
            if existing is None:
                record = DecisionCaseRecord(
                    **draft.model_dump(),
                    id=str(uuid4()),
                    status="Open",
                    is_trigger_active=True,
                    detected_at=evaluated_at,
                    last_evaluated_at=evaluated_at,
                )
            else:
                update: dict[str, Any] = {
                    **draft.model_dump(),
                    "is_trigger_active": True,
                    "last_evaluated_at": evaluated_at,
                }
                if not existing.is_trigger_active:
                    update.update({
                        "status": "Open",
                        "detected_at": evaluated_at,
                        "resolved_at": None,
                        "closed_at": None,
                    })
                record = existing.model_copy(update=update)
            self._records[draft.case_key] = record

    def list_records(self) -> list[DecisionCaseRecord]:
        return list(self._records.values())

    def get(self, case_id: str) -> DecisionCaseRecord | None:
        return next((record for record in self._records.values() if record.id == case_id), None)

    def update_status(self, case_id: str, status: str) -> DecisionCaseRecord | None:
        now = datetime.now(timezone.utc)
        for key, record in list(self._records.items()):
            if record.id != case_id:
                continue
            update: dict[str, Any] = {"status": status}
            if status == "Resolved":
                update.update({"resolved_at": now, "closed_at": None})
            elif status == "Closed":
                update.update({"closed_at": now})
            else:
                update.update({"resolved_at": None, "closed_at": None})
            self._records[key] = record.model_copy(update=update)
            return self._records[key]
        return None


class CsvDecisionCaseStore:
    """Persistent CSV workflow store used by the current project phase.

    HR source datasets remain read-only. Only this dedicated generated case-state
    file is written. Updates are atomic within the process: a temporary file is
    written and then replaced so a partial write cannot corrupt the case queue.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write_records([])

    @staticmethod
    def _bool(value: Any) -> bool:
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _none_if_blank(value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return None if not text else value

    @classmethod
    def _row_to_record(cls, row: dict[str, str]) -> DecisionCaseRecord:
        evidence_text = row.get("evidence_json", "") or "{}"
        try:
            evidence = json.loads(evidence_text)
        except json.JSONDecodeError as exc:
            raise DecisionCaseStorageError(
                f"Invalid evidence_json in {cls.__name__} case file."
            ) from exc

        payload: dict[str, Any] = {
            "id": row.get("id"),
            "case_key": row.get("case_key"),
            "rule_id": row.get("rule_id"),
            "case_type": row.get("case_type"),
            "subject_type": row.get("subject_type"),
            "subject_id": row.get("subject_id"),
            "employee_id": cls._none_if_blank(row.get("employee_id")),
            "position_id": cls._none_if_blank(row.get("position_id")),
            "department_id": cls._none_if_blank(row.get("department_id")),
            "department": cls._none_if_blank(row.get("department")),
            "priority": row.get("priority"),
            "display_rank": int(row.get("display_rank") or 100),
            "title": row.get("title"),
            "reason": row.get("reason"),
            "evidence": evidence,
            "suggested_action": row.get("suggested_action"),
            "data_as_of": cls._none_if_blank(row.get("data_as_of")),
            "status": row.get("status") or "Open",
            "is_trigger_active": cls._bool(row.get("is_trigger_active")),
            "detected_at": row.get("detected_at"),
            "last_evaluated_at": row.get("last_evaluated_at"),
            "resolved_at": cls._none_if_blank(row.get("resolved_at")),
            "closed_at": cls._none_if_blank(row.get("closed_at")),
        }
        return DecisionCaseRecord.model_validate(payload)

    @staticmethod
    def _record_to_row(record: DecisionCaseRecord) -> dict[str, str]:
        data = record.model_dump(mode="json")
        evidence = data.pop("evidence", {})
        row = {column: "" for column in CSV_CASE_COLUMNS}
        for key, value in data.items():
            if key in row:
                if isinstance(value, bool):
                    row[key] = "true" if value else "false"
                elif value is None:
                    row[key] = ""
                else:
                    row[key] = str(value)
        row["evidence_json"] = json.dumps(
            evidence,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return row

    def _read_records(self) -> list[DecisionCaseRecord]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    return []
                missing = set(CSV_CASE_COLUMNS) - set(reader.fieldnames)
                if missing:
                    raise DecisionCaseStorageError(
                        f"Decision case CSV is missing columns: {', '.join(sorted(missing))}"
                    )
                return [self._row_to_record(row) for row in reader]
        except DecisionCaseStorageError:
            raise
        except Exception as exc:
            raise DecisionCaseStorageError(
                f"Could not read decision cases from CSV: {self.path}"
            ) from exc

    def _write_records(self, records: list[DecisionCaseRecord]) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_CASE_COLUMNS)
                writer.writeheader()
                for record in records:
                    writer.writerow(self._record_to_row(record))
            os.replace(temp_path, self.path)
        except Exception as exc:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise DecisionCaseStorageError(
                f"Could not write decision cases to CSV: {self.path}"
            ) from exc

    def sync(self, drafts: list[DecisionCaseDraft], evaluated_at: datetime) -> None:
        with self._lock:
            records = {record.case_key: record for record in self._read_records()}
            active_keys = {draft.case_key for draft in drafts}

            for key, record in list(records.items()):
                if record.is_trigger_active and key not in active_keys:
                    records[key] = record.model_copy(update={
                        "is_trigger_active": False,
                        "last_evaluated_at": evaluated_at,
                    })

            for draft in drafts:
                existing = records.get(draft.case_key)
                if existing is None:
                    records[draft.case_key] = DecisionCaseRecord(
                        **draft.model_dump(),
                        id=f"CASE-{uuid4().hex[:12].upper()}",
                        status="Open",
                        is_trigger_active=True,
                        detected_at=evaluated_at,
                        last_evaluated_at=evaluated_at,
                    )
                    continue

                update: dict[str, Any] = {
                    **draft.model_dump(),
                    "is_trigger_active": True,
                    "last_evaluated_at": evaluated_at,
                }
                if not existing.is_trigger_active:
                    update.update({
                        "status": "Open",
                        "detected_at": evaluated_at,
                        "resolved_at": None,
                        "closed_at": None,
                    })
                records[draft.case_key] = existing.model_copy(update=update)

            priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            ordered = sorted(
                records.values(),
                key=lambda item: (
                    priority_order.get(item.priority, 99),
                    item.display_rank,
                    item.detected_at,
                    item.case_key,
                ),
            )
            self._write_records(ordered)

    def list_records(self) -> list[DecisionCaseRecord]:
        with self._lock:
            return self._read_records()

    def get(self, case_id: str) -> DecisionCaseRecord | None:
        with self._lock:
            return next(
                (record for record in self._read_records() if record.id == case_id),
                None,
            )

    def update_status(self, case_id: str, status: str) -> DecisionCaseRecord | None:
        with self._lock:
            records = self._read_records()
            now = datetime.now(timezone.utc)
            updated: DecisionCaseRecord | None = None
            output: list[DecisionCaseRecord] = []

            for record in records:
                if record.id != case_id:
                    output.append(record)
                    continue

                change: dict[str, Any] = {"status": status}
                if status == "Resolved":
                    change.update({"resolved_at": now, "closed_at": None})
                elif status == "Closed":
                    change.update({"closed_at": now})
                else:
                    change.update({"resolved_at": None, "closed_at": None})
                updated = record.model_copy(update=change)
                output.append(updated)

            if updated is not None:
                self._write_records(output)
            return updated


class SupabaseDecisionCaseStore:
    """Future persistent store using the same DecisionCaseStore interface."""

    def __init__(
        self,
        client_factory: Callable[[], Any],
        table_name: str = "hr_decision_cases",
    ) -> None:
        self.client_factory = client_factory
        self.table_name = table_name

    def _client(self) -> Any:
        try:
            return self.client_factory()
        except Exception as exc:
            raise DecisionCaseStorageError(
                "Decision-case Supabase storage is not configured correctly."
            ) from exc

    @staticmethod
    def _base_payload(draft: DecisionCaseDraft, evaluated_at: datetime) -> dict[str, Any]:
        payload = draft.model_dump(mode="json")
        payload.update({
            "is_trigger_active": True,
            "last_evaluated_at": evaluated_at.isoformat(),
            "updated_at": evaluated_at.isoformat(),
        })
        return payload

    def sync(self, drafts: list[DecisionCaseDraft], evaluated_at: datetime) -> None:
        client = self._client()
        active_keys = {draft.case_key for draft in drafts}
        try:
            current_rows = (
                client.table(self.table_name)
                .select("id,case_key,is_trigger_active,status,detected_at,resolved_at,closed_at")
                .execute()
                .data
                or []
            )
            current_by_key = {
                str(row.get("case_key")): row
                for row in current_rows
                if row.get("case_key")
            }

            for key, row in current_by_key.items():
                if row.get("is_trigger_active") and key not in active_keys:
                    (
                        client.table(self.table_name)
                        .update({
                            "is_trigger_active": False,
                            "last_evaluated_at": evaluated_at.isoformat(),
                            "updated_at": evaluated_at.isoformat(),
                        })
                        .eq("id", row.get("id"))
                        .execute()
                    )

            for draft in drafts:
                existing = current_by_key.get(draft.case_key)
                payload = self._base_payload(draft, evaluated_at)

                if existing is None:
                    payload.update({
                        "status": "Open",
                        "detected_at": evaluated_at.isoformat(),
                        "resolved_at": None,
                        "closed_at": None,
                    })
                    client.table(self.table_name).insert(payload).execute()
                    continue

                if not existing.get("is_trigger_active"):
                    payload.update({
                        "status": "Open",
                        "detected_at": evaluated_at.isoformat(),
                        "resolved_at": None,
                        "closed_at": None,
                    })

                (
                    client.table(self.table_name)
                    .update(payload)
                    .eq("id", existing.get("id"))
                    .execute()
                )
        except Exception as exc:
            raise DecisionCaseStorageError(
                "Could not sync decision cases to Supabase. Run database/decision_cases.sql "
                "and verify the backend Supabase secret key."
            ) from exc

    def list_records(self) -> list[DecisionCaseRecord]:
        client = self._client()
        try:
            rows = client.table(self.table_name).select("*").execute().data or []
            return [DecisionCaseRecord.model_validate(row) for row in rows]
        except Exception as exc:
            raise DecisionCaseStorageError(
                "Could not read decision cases from Supabase."
            ) from exc

    def get(self, case_id: str) -> DecisionCaseRecord | None:
        client = self._client()
        try:
            rows = (
                client.table(self.table_name)
                .select("*")
                .eq("id", case_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            return DecisionCaseRecord.model_validate(rows[0]) if rows else None
        except Exception as exc:
            raise DecisionCaseStorageError(
                "Could not read the requested decision case."
            ) from exc

    def update_status(self, case_id: str, status: str) -> DecisionCaseRecord | None:
        client = self._client()
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "status": status,
            "updated_at": now.isoformat(),
        }
        if status == "Resolved":
            payload.update({"resolved_at": now.isoformat(), "closed_at": None})
        elif status == "Closed":
            payload.update({"closed_at": now.isoformat()})
        else:
            payload.update({"resolved_at": None, "closed_at": None})
        try:
            rows = (
                client.table(self.table_name)
                .update(payload)
                .eq("id", case_id)
                .execute()
                .data
                or []
            )
            return DecisionCaseRecord.model_validate(rows[0]) if rows else None
        except Exception as exc:
            raise DecisionCaseStorageError(
                "Could not update decision-case status."
            ) from exc


def storage_mode() -> str:
    """Current default is CSV; switch to Supabase later with one env value."""

    return os.getenv("DECISION_CASE_STORAGE", "csv").strip().lower()


def csv_store_path(data_dir: str | Path) -> Path:
    raw = os.getenv("DECISION_CASE_CSV_FILE", "HR_Decision_Cases.csv").strip()
    path = Path(raw)
    return path if path.is_absolute() else Path(data_dir) / path
