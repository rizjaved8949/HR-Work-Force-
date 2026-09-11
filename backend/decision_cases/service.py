from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable

from .engine import DecisionTriggerEngine
from .schemas import (
    DecisionCaseEvaluationResult,
    DecisionCaseRecord,
    DecisionCaseQueryResult,
)
from .store import ACTIONABLE_STATUSES, DecisionCaseStore


PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


class DecisionCaseService:
    """Coordinates deterministic detection, persistence, and focused querying."""

    def __init__(
        self,
        *,
        engine: DecisionTriggerEngine,
        store: DecisionCaseStore,
        dashboard_limit: int | None = None,
    ) -> None:
        self.engine = engine
        self.store = store
        configured = dashboard_limit or int(
            os.getenv("DECISION_CASE_DASHBOARD_LIMIT", "5")
        )
        # Product requirement: the HR attention queue must stay intentionally
        # small even if many source records satisfy underlying rules.
        self.dashboard_limit = max(1, min(configured, 5))

    @staticmethod
    def _sort(records: Iterable[DecisionCaseRecord]) -> list[DecisionCaseRecord]:
        return sorted(
            records,
            key=lambda item: (
                PRIORITY_ORDER.get(item.priority, 99),
                item.display_rank,
                item.detected_at,
                item.case_key,
            ),
        )

    def _select_focused_queue(
        self,
        records: list[DecisionCaseRecord],
        limit: int,
    ) -> list[DecisionCaseRecord]:
        """Keep the queue important and broad, not five copies of one problem.

        First pass takes the highest-ranked case from each rule. If there are
        still free slots, the remaining highest-ranked cases fill them. This
        gives HR a quick picture of what is happening across different risk
        types while still preserving Critical-before-High ordering.
        """

        if not records or limit <= 0:
            return []

        sorted_records = self._sort(records)
        selected: list[DecisionCaseRecord] = []
        selected_ids: set[str] = set()
        seen_rules: set[str] = set()

        for record in sorted_records:
            if record.rule_id in seen_rules:
                continue
            selected.append(record)
            selected_ids.add(record.id)
            seen_rules.add(record.rule_id)
            if len(selected) >= limit:
                return selected

        for record in sorted_records:
            if record.id in selected_ids:
                continue
            selected.append(record)
            if len(selected) >= limit:
                break

        return selected

    def evaluate(self) -> DecisionCaseEvaluationResult:
        evaluated_at = datetime.now(timezone.utc)
        drafts = self.engine.detect()
        self.store.sync(drafts, evaluated_at)

        records = self._sort(self.store.list_records())
        actionable = [
            case
            for case in records
            if case.is_trigger_active and case.status in ACTIONABLE_STATUSES
        ]
        dashboard = self._select_focused_queue(
            actionable,
            self.dashboard_limit,
        )

        return DecisionCaseEvaluationResult(
            evaluated_at=evaluated_at,
            detected_case_count=len(drafts),
            actionable_case_count=len(actionable),
            dashboard_case_count=len(dashboard),
            dashboard_limit=self.dashboard_limit,
            cases=dashboard,
        )

    def list_cases(
        self,
        *,
        active_only: bool = True,
        priority: str | None = None,
        status: str | None = None,
        employee_id: str | None = None,
        department: str | None = None,
        rule_id: str | None = None,
        limit: int | None = None,
    ) -> DecisionCaseQueryResult:
        records = self._sort(self.store.list_records())

        if active_only:
            records = [record for record in records if record.is_trigger_active]
        if priority:
            records = [
                record
                for record in records
                if record.priority.casefold() == priority.casefold()
            ]
        if status:
            records = [
                record
                for record in records
                if record.status.casefold() == status.casefold()
            ]
        else:
            records = [
                record for record in records if record.status in ACTIONABLE_STATUSES
            ]
        if employee_id:
            normalized = employee_id.strip().upper()
            records = [
                record
                for record in records
                if (record.employee_id or "").upper() == normalized
            ]
        if department:
            normalized = department.strip().casefold()
            records = [
                record
                for record in records
                if normalized in (record.department or "").casefold()
                or normalized in str(record.evidence).casefold()
            ]
        if rule_id:
            normalized = rule_id.strip().upper()
            records = [
                record
                for record in records
                if record.rule_id.upper() == normalized
                or normalized
                in str(record.evidence.get("additional_triggers", "")).upper()
            ]

        total_matching = len(records)
        requested = limit if limit is not None else self.dashboard_limit
        safe_limit = max(1, min(int(requested), 5))
        selected = self._select_focused_queue(records, safe_limit)

        return DecisionCaseQueryResult(
            status="success" if selected else "not_found",
            count=len(selected),
            total_matching=total_matching,
            cases=selected,
            message=(
                None
                if selected
                else "No matching active decision-trigger cases were found."
            ),
        )

    def get_case(self, case_id: str) -> DecisionCaseRecord | None:
        return self.store.get(case_id)

    def update_status(self, case_id: str, status: str) -> DecisionCaseRecord | None:
        return self.store.update_status(case_id, status)
