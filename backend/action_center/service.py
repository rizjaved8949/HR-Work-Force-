"""Deterministic business logic for the HR Action Center.

The LLM never changes HR data directly. It calls this service, which validates
identity, process rules and fields, then writes the operational CSVs and an
append-only audit event.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Callable

import pandas as pd

from .config import ActionCenterSettings, get_action_center_settings
from .errors import (
    ActionCenterAuthorizationError,
    ActionCenterConflictError,
    ActionCenterDataError,
    ActionCenterNotFoundError,
    ActionCenterValidationError,
)
from .repository import ActionCenterRepository
from .schemas import ActionActor, ActionCenterQueryInput


ACTIVE_STATUSES = {"active", "probation", "acting", "seconded"}
SEPARATION_PROCESS_CODES = {
    "RESIGNATION",
    "RETIREMENT",
    "TERMINATION",
    "CONTRACT_END",
}
JOB_LEVEL_ORDER = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead/manager": 4,
    "lead": 4,
    "manager": 4,
    "executive": 5,
}

PROCESS_ALIASES = {
    "PROBATION CONFIRMATION": "PROB_CONFIRM",
    "CONFIRM PROBATION": "PROB_CONFIRM",
    "PROBATION EXTENSION": "PROB_EXTEND",
    "EXTEND PROBATION": "PROB_EXTEND",
    "CONTRACT RENEWAL": "CONTRACT_RENEW",
    "CONTRACT EXTENSION": "CONTRACT_RENEW",
    "REJOIN": "REHIRE",
    "REJOINING": "REHIRE",
    "REHIRE": "REHIRE",
    "CONTRACT END": "CONTRACT_END",
    "NON-RENEWAL": "CONTRACT_END",
    "RESIGN": "RESIGNATION",
    "RESIGNATION": "RESIGNATION",
    "WITHDRAW RESIGNATION": "RESIGN_WITHDRAW",
    "RESIGNATION WITHDRAWAL": "RESIGN_WITHDRAW",
    "RETIRE": "RETIREMENT",
    "RETIREMENT": "RETIREMENT",
    "TERMINATE": "TERMINATION",
    "TERMINATION": "TERMINATION",
    "FINAL SETTLEMENT": "FINAL_SETTLEMENT",
    "PROMOTE": "PROMOTION",
    "PROMOTION": "PROMOTION",
    "TRANSFER": "TRANSFER",
    "EMPLOYEE TRANSFER": "TRANSFER",
    "ACTING CHARGE": "ACTING_CHARGE",
    "ADDITIONAL CHARGE": "ACTING_CHARGE",
    "DEMOTE": "DEMOTION",
    "DEMOTION": "DEMOTION",
    "DEPUTATION": "SECONDMENT",
    "SECONDMENT": "SECONDMENT",
}


class ActionCenterService:
    def __init__(
        self,
        repository: ActionCenterRepository,
        settings: ActionCenterSettings | None = None,
        *,
        post_commit_callbacks: list[Callable[[], None]] | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or get_action_center_settings()
        # Optional callbacks let existing read-only analytics repositories
        # invalidate their caches after an operational write.  They are kept
        # outside the Action Center repository so storage remains isolated.
        self.post_commit_callbacks = list(post_commit_callbacks or [])

    def _notify_post_commit(self) -> None:
        """Best-effort cache invalidation after a successful write.

        A callback failure must never roll back an already-persisted HR action;
        callers will simply reload from disk on their next normal refresh.
        """

        for callback in self.post_commit_callbacks:
            try:
                callback()
            except Exception:
                continue

    # ------------------------------------------------------------------
    # READS
    # ------------------------------------------------------------------

    def supported_process_codes(self) -> list[str]:
        catalog = self.repository.process_catalog()
        return [str(value).strip().upper() for value in catalog["Process_Code"]]

    def normalize_process_code(self, value: str) -> str:
        if not value or not str(value).strip():
            raise ActionCenterValidationError("A process code is required.")

        raw = str(value).strip().upper().replace("-", "_")
        if raw in self.supported_process_codes():
            return raw

        alias = PROCESS_ALIASES.get(str(value).strip().upper())
        if alias:
            return alias

        catalog = self.repository.process_catalog()
        names = catalog["Process_Name"].astype(str)
        exact = catalog[names.str.upper() == str(value).strip().upper()]
        if len(exact) == 1:
            return str(exact.iloc[0]["Process_Code"]).strip().upper()

        raise ActionCenterNotFoundError(
            f"Action Center process {value!r} is not supported in the current 15-process scope."
        )

    def process_detail(self, process_code: str) -> dict[str, Any]:
        code = self.normalize_process_code(process_code)
        catalog = self.repository.process_catalog()
        row = catalog[
            catalog["Process_Code"].astype(str).str.upper() == code
        ]
        if row.empty:
            raise ActionCenterNotFoundError(f"Process {code} was not found.")
        process = self.repository._clean_record(row.iloc[0].to_dict())

        fields = self.repository.process_fields()
        fields = fields[
            fields["Process_Code"].astype(str).str.upper() == code
        ].sort_values("Field_Order")
        process["fields"] = [
            self.repository._clean_record(item)
            for item in fields.to_dict(orient="records")
        ]
        process["statistics"] = self.process_statistics(code)
        return process

    def process_statistics(self, process_code: str) -> dict[str, Any]:
        """Return the deterministic process counters shown by Action Center UI."""

        code = self.normalize_process_code(process_code)
        records = self.repository.records()
        frame = records[
            records["Process_Code"].astype(str).str.upper() == code
        ].copy()
        if frame.empty:
            return {
                "recorded_all_time": 0,
                "recorded_last_30_days": 0,
                "last_performed_at": None,
                "last_performed_by": None,
                "status_counts": {},
            }

        recorded = pd.to_datetime(frame["Recorded_DateTime"], errors="coerce", utc=True)
        now = pd.Timestamp.now(tz="UTC")
        recent = recorded >= (now - pd.Timedelta(days=30))
        ordered = frame.assign(_recorded=recorded).sort_values(
            "_recorded",
            ascending=False,
        )
        last = ordered.iloc[0]
        status_counts = (
            frame["Record_Status"].astype(str).str.upper().value_counts().to_dict()
        )
        last_at = last.get("Recorded_DateTime")
        return {
            "recorded_all_time": int(len(frame)),
            "recorded_last_30_days": int(recent.fillna(False).sum()),
            "last_performed_at": self._clean_scalar(last_at),
            "last_performed_by": self._clean_scalar(last.get("Performed_By_Name")),
            "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        }

    def summary(self) -> dict[str, Any]:
        records = self.repository.records()
        state = self.repository.operational_state()

        statuses = records["Record_Status"].astype(str).str.upper()
        operational_statuses = state["Employee_Status_Operational"].astype(str).str.casefold()

        by_process = (
            records.groupby(["Process_Code", "Process_Name"], dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        by_group = (
            records.groupby("Process_Group", dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )

        return {
            "status": "success",
            "total_action_records": int(len(records)),
            "applied": int((statuses == "APPLIED").sum()),
            "scheduled": int((statuses == "SCHEDULED").sum()),
            "withdrawn": int((statuses == "WITHDRAWN").sum()),
            "active_operational_employees": int(
                operational_statuses.isin(ACTIVE_STATUSES).sum()
            ),
            "inactive_operational_employees": int(
                (~operational_statuses.isin(ACTIVE_STATUSES)).sum()
            ),
            "process_count": int(self.repository.process_catalog().shape[0]),
            "by_process": by_process.to_dict(orient="records"),
            "by_group": by_group.to_dict(orient="records"),
        }

    def query(self, request: ActionCenterQueryInput | dict[str, Any]) -> dict[str, Any]:
        q = (
            request
            if isinstance(request, ActionCenterQueryInput)
            else ActionCenterQueryInput.model_validate(request)
        )

        if q.mode == "summary":
            return self.summary()

        if q.mode == "process_detail":
            if not q.process_code:
                raise ActionCenterValidationError(
                    "process_code is required for process_detail."
                )
            return {
                "status": "success",
                "process": self.process_detail(q.process_code),
            }

        if q.mode == "process_options":
            if not q.process_code:
                raise ActionCenterValidationError(
                    "process_code is required for process_options."
                )
            return self.process_options(
                q.process_code,
                employee_id=q.employee_id,
                employee_name=q.employee_name,
                limit=q.limit,
            )

        if q.mode == "processes":
            catalog = self.repository.process_catalog().sort_values("Sort_Order")
            if q.process_code:
                code = self.normalize_process_code(q.process_code)
                catalog = catalog[
                    catalog["Process_Code"].astype(str).str.upper() == code
                ]
            compact = self.repository.compact_records(
                catalog,
                columns=[
                    "Process_Code",
                    "Process_Name",
                    "Process_Group",
                    "Purpose",
                    "Execution_Mode",
                    "Core_Impact",
                    "Form_Field_Count",
                ],
                limit=q.limit,
            )
            for item in compact:
                item["statistics"] = self.process_statistics(str(item["Process_Code"]))
            return {
                "status": "success",
                "count": int(len(catalog)),
                "records": compact,
            }

        employee = None
        if q.employee_id or q.employee_name:
            employee = self.repository.resolve_employee(
                employee_id=q.employee_id,
                employee_name=q.employee_name,
            )

        if q.mode == "employee_state":
            if not employee:
                raise ActionCenterValidationError(
                    "Employee ID or name is required for employee_state."
                )
            return {
                "status": "success",
                "employee": self._compact_employee_state(employee),
            }

        if q.mode in {"records", "employee_history"}:
            frame = self.repository.records()
            if q.process_code:
                code = self.normalize_process_code(q.process_code)
                frame = frame[
                    frame["Process_Code"].astype(str).str.upper() == code
                ]
            if employee:
                frame = frame[
                    frame["Employee_ID"].astype(str).str.upper()
                    == str(employee["Employee_ID"]).upper()
                ]
            elif q.mode == "employee_history":
                raise ActionCenterValidationError(
                    "Employee ID or name is required for employee_history."
                )
            if q.status:
                frame = frame[
                    frame["Record_Status"].astype(str).str.upper()
                    == q.status.strip().upper()
                ]
            frame = self._filter_dates(
                frame,
                column="Recorded_DateTime",
                start_date=q.start_date,
                end_date=q.end_date,
            )
            frame = frame.sort_values("Recorded_DateTime", ascending=False)
            return {
                "status": "success",
                "count": int(len(frame)),
                "employee": self._compact_employee_state(employee) if employee else None,
                "records": self.repository.compact_records(
                    frame,
                    columns=[
                        "Action_Record_ID",
                        "Process_Code",
                        "Process_Name",
                        "Employee_ID",
                        "Employee_Name",
                        "Department_Name",
                        "Recorded_DateTime",
                        "Effective_Date",
                        "Record_Status",
                        "Performed_By_Name",
                        "Reason_Category",
                        "Reason_Details",
                        "Target_Department_Name",
                        "Target_Position_Title",
                        "Action_Data_JSON",
                    ],
                    limit=q.limit,
                ),
            }

        if q.mode == "activity":
            frame = self.repository.events()
            if q.process_code:
                code = self.normalize_process_code(q.process_code)
                frame = frame[
                    frame["Process_Code"].astype(str).str.upper() == code
                ]
            if employee:
                frame = frame[
                    frame["Employee_ID"].astype(str).str.upper()
                    == str(employee["Employee_ID"]).upper()
                ]
            frame = self._filter_dates(
                frame,
                column="Event_DateTime",
                start_date=q.start_date,
                end_date=q.end_date,
            )
            frame = frame.sort_values("Event_DateTime", ascending=False)
            return {
                "status": "success",
                "count": int(len(frame)),
                "records": self.repository.compact_records(
                    frame,
                    columns=[
                        "Event_ID",
                        "Action_Record_ID",
                        "Process_Code",
                        "Employee_ID",
                        "Event_Type",
                        "Event_DateTime",
                        "Performed_By_Name",
                        "Previous_Status",
                        "New_Status",
                        "Effect",
                        "Note",
                    ],
                    limit=q.limit,
                ),
            }

        raise ActionCenterValidationError(f"Unsupported query mode: {q.mode}")

    def process_options(
        self,
        process_code: str,
        *,
        employee_id: str | None = None,
        employee_name: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        code = self.normalize_process_code(process_code)
        employee = None
        if employee_id or employee_name:
            employee = self.repository.resolve_employee(
                employee_id=employee_id,
                employee_name=employee_name,
            )

        departments = self.repository.departments()
        departments = departments[
            departments["Active_Status"].astype(str).str.casefold() == "active"
        ]

        positions = self.repository.positions().copy()
        positions = positions[
            positions["Approved_Position"].astype(str).str.casefold() == "yes"
        ]
        # Position_Master uses Position_Status=Frozen and, in this dataset,
        # Position_Freeze_Status=Budget Freeze.  Exclude either representation.
        position_status = positions["Position_Status"].astype(str).str.casefold()
        freeze_status = positions["Position_Freeze_Status"].astype(str).str.casefold()
        positions = positions[
            ~position_status.eq("frozen")
            & ~freeze_status.str.contains("freeze", regex=False)
        ]

        if code in {"PROMOTION", "TRANSFER", "DEMOTION", "REHIRE", "ACTING_CHARGE", "SECONDMENT"}:
            # Compute occupancy once.  The earlier per-position lookup repeatedly
            # re-read the operational CSV and was too slow for a live Action
            # Center form with hundreds of positions.
            occupants = self.repository.active_operational_occupants()
            current_employee_id = (
                str(employee["Employee_ID"]).strip().upper()
                if employee
                else None
            )
            available_mask = []
            for _, row in positions.iterrows():
                pos_id = str(row.get("Position_ID", "")).strip().upper()
                occupant = occupants.get(pos_id)
                available_mask.append(
                    not occupant
                    or bool(current_employee_id and occupant == current_employee_id)
                )
            positions = positions.loc[available_mask].copy()

        if employee:
            current_dept = str(
                employee.get("Operational_Department_ID")
                or employee.get("Department_ID")
                or ""
            )
            current_level = self._job_level_rank(
                employee.get("Operational_Job_Level") or employee.get("Job_Level")
            )

            if code in {"TRANSFER", "SECONDMENT"}:
                departments = departments[
                    departments["Department_ID"].astype(str).str.upper() != current_dept.upper()
                ]
                positions = positions[
                    positions["Department_ID"].astype(str).str.upper() != current_dept.upper()
                ]
            if code == "PROMOTION":
                positions = positions[
                    positions["Job_Level"].map(self._job_level_rank) > current_level
                ]
            elif code == "DEMOTION":
                positions = positions[
                    positions["Job_Level"].map(self._job_level_rank) < current_level
                ]

        return {
            "status": "success",
            "process_code": code,
            "employee": self._compact_employee_state(employee) if employee else None,
            "departments": self.repository.compact_records(
                departments,
                columns=["Department_ID", "Department_Name", "Business_Unit_Name"],
                limit=limit,
            ),
            "positions": self.repository.compact_records(
                positions,
                columns=[
                    "Position_ID",
                    "Position_Title",
                    "Designation",
                    "Department_ID",
                    "Department",
                    "Job_Level",
                    "Position_Status",
                    "Budgeted_Position",
                    "Position_Criticality",
                ],
                limit=limit,
            ),
        }

    # ------------------------------------------------------------------
    # PREVIEW / EXECUTION
    # ------------------------------------------------------------------

    def preview_action(
        self,
        *,
        process_code: str,
        employee_id: str | None,
        employee_name: str | None,
        fields: dict[str, Any] | None,
        actor: ActionActor | None = None,
    ) -> dict[str, Any]:
        code = self.normalize_process_code(process_code)
        process = self.process_detail(code)
        employee = self.repository.resolve_employee(
            employee_id=employee_id,
            employee_name=employee_name,
        )
        normalized_fields = dict(fields or {})
        normalized_fields["employee_id"] = employee["Employee_ID"]

        self._validate_actor(actor, write=False)
        self._validate_required_fields(process, normalized_fields)
        context = self._validate_business_rules(
            code=code,
            employee=employee,
            fields=normalized_fields,
        )

        effective_date = normalized_fields.get("effective_date")
        record_status = self._record_status_for_effective_date(effective_date)

        return {
            "status": "ready",
            "confirmation_required": True,
            "process": {
                "process_code": code,
                "process_name": process["Process_Name"],
                "process_group": process["Process_Group"],
                "core_impact": process["Core_Impact"],
                "execution_mode": process["Execution_Mode"],
            },
            "employee": self._compact_employee_state(employee),
            "normalized_fields": normalized_fields,
            "resolved": context,
            "resulting_record_status": record_status,
            "message": (
                "The action is valid and ready. Confirm before it is written to the Action Center."
            ),
        }

    def execute_action(
        self,
        *,
        process_code: str,
        employee_id: str | None,
        employee_name: str | None,
        fields: dict[str, Any] | None,
        actor: ActionActor | None,
    ) -> dict[str, Any]:
        self._validate_actor(actor, write=True)
        preview = self.preview_action(
            process_code=process_code,
            employee_id=employee_id,
            employee_name=employee_name,
            fields=fields,
            actor=actor,
        )

        code = preview["process"]["process_code"]
        employee = self.repository.resolve_employee(
            employee_id=(preview["employee"].get("Employee_ID") or preview["employee"].get("employee_id"))
        )
        normalized_fields = dict(preview["normalized_fields"])
        resolved = dict(preview.get("resolved") or {})

        state = self.repository.operational_state()
        records = self.repository.records()
        events = self.repository.events()

        now = datetime.now(timezone.utc)
        today = now.date()
        action_record_id = self.repository.next_id(
            "records", "HRACT-", "Action_Record_ID", 5
        )
        record_status = preview["resulting_record_status"]

        # A withdrawal only cancels its source resignation once the withdrawal
        # itself is effective.  Future-dated withdrawals remain SCHEDULED and
        # can be applied by the apply-due endpoint on/after their effective date.
        if code == "RESIGN_WITHDRAW" and record_status == "APPLIED":
            source_id = str(normalized_fields["resignation_action_record_id"])
            mask = records["Action_Record_ID"].astype(str).str.upper() == source_id.upper()
            source_status = str(records.loc[mask, "Record_Status"].iloc[0])
            records.loc[mask, "Record_Status"] = "WITHDRAWN"
            events = self._append_event(
                events,
                action_record_id=source_id,
                process_code="RESIGNATION",
                employee_id=str(employee["Employee_ID"]),
                event_type="WITHDRAWN",
                actor=actor,
                previous_status=source_status,
                new_status="WITHDRAWN",
                effect="Scheduled resignation cancelled; employee remains in service.",
                note=str(normalized_fields.get("note") or normalized_fields.get("withdrawal_reason") or ""),
                now=now,
            )

        record = self._build_record(
            action_record_id=action_record_id,
            code=code,
            employee=employee,
            fields=normalized_fields,
            resolved=resolved,
            actor=actor,
            record_status=record_status,
            now=now,
        )
        records = pd.concat([records, pd.DataFrame([record])], ignore_index=True)

        events = self._append_event(
            events,
            action_record_id=action_record_id,
            process_code=code,
            employee_id=str(employee["Employee_ID"]),
            event_type="RECORDED",
            actor=actor,
            previous_status="",
            new_status=record_status,
            effect="Action Center record created and validated.",
            note=str(normalized_fields.get("note") or ""),
            now=now,
        )

        # Current-state impact is applied immediately only when the effective
        # date is today/past. Future actions remain SCHEDULED and are visible in
        # the queue/history without prematurely changing current operational state.
        if record_status == "APPLIED":
            state, effect = self._apply_operational_impact(
                state=state,
                code=code,
                employee_id=str(employee["Employee_ID"]),
                fields=normalized_fields,
                resolved=resolved,
                action_record_id=action_record_id,
                now=now,
            )
            events = self._append_event(
                events,
                action_record_id=action_record_id,
                process_code=code,
                employee_id=str(employee["Employee_ID"]),
                event_type="APPLIED",
                actor=actor,
                previous_status="SCHEDULED",
                new_status="APPLIED",
                effect=effect,
                note="Operational Action Center state updated. Existing analytics CSVs were not modified.",
                now=now,
            )
        else:
            state = self._record_scheduled_state(
                state=state,
                code=code,
                employee_id=str(employee["Employee_ID"]),
                fields=normalized_fields,
                action_record_id=action_record_id,
                now=now,
            )

        self.repository.persist_action_transaction(
            operational_state=state,
            records=records,
            events=events,
        )
        self._notify_post_commit()

        updated_employee = self.repository.resolve_employee(
            employee_id=str(employee["Employee_ID"])
        )
        return {
            "status": "completed",
            "action_record_id": action_record_id,
            "process_code": code,
            "process_name": preview["process"]["process_name"],
            "record_status": record_status,
            "employee": self._compact_employee_state(updated_employee),
            "core_analytics_files_modified": False,
            "message": (
                "Action recorded and applied to the Action Center operational state."
                if record_status == "APPLIED"
                else "Action recorded as scheduled; current operational state will not change until it is applied."
            ),
        }

    def update_action_record(
        self,
        *,
        action_record_id: str,
        updates: dict[str, Any],
        actor: ActionActor | None,
    ) -> dict[str, Any]:
        self._validate_actor(actor, write=True)
        if not updates:
            raise ActionCenterValidationError("At least one update is required.")

        allowed = {
            "Effective_Date",
            "Reason_Category",
            "Reason_Details",
            "Action_Data_JSON",
        }
        unknown = sorted(set(updates) - allowed)
        if unknown:
            raise ActionCenterValidationError(
                "Only scheduled-record fields may be updated. Unsupported: "
                + ", ".join(unknown)
            )

        records = self.repository.records()
        events = self.repository.events()
        mask = (
            records["Action_Record_ID"].astype(str).str.upper()
            == action_record_id.strip().upper()
        )
        if not mask.any():
            raise ActionCenterNotFoundError(
                f"Action record {action_record_id!r} was not found."
            )
        current = records.loc[mask].iloc[0]
        current_status = str(current.get("Record_Status", "")).upper()
        if current_status != "SCHEDULED":
            raise ActionCenterConflictError(
                "Only SCHEDULED Action Center records can be edited. "
                f"This record is {current_status or 'unknown'}."
            )

        before: dict[str, Any] = {}
        for column, value in updates.items():
            before[column] = current.get(column)
            if column == "Action_Data_JSON" and isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False, default=str)
            records.loc[mask, column] = value

        now = datetime.now(timezone.utc)
        events = self._append_event(
            events,
            action_record_id=str(current["Action_Record_ID"]),
            process_code=str(current["Process_Code"]),
            employee_id=str(current["Employee_ID"]),
            event_type="UPDATED",
            actor=actor,
            previous_status="SCHEDULED",
            new_status="SCHEDULED",
            effect="Scheduled Action Center record fields updated.",
            note=json.dumps({"before": before, "after": updates}, ensure_ascii=False, default=str),
            now=now,
        )
        self.repository.persist_records_and_events(records=records, events=events)
        self._notify_post_commit()
        return {
            "status": "completed",
            "action_record_id": str(current["Action_Record_ID"]),
            "updated_fields": updates,
            "message": "Scheduled Action Center record updated and audited.",
        }

    def apply_due_actions(
        self,
        *,
        actor: ActionActor | None,
        record_ids: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Apply due SCHEDULED records without creating duplicate action records.

        This is intended for a small scheduler/cron call after migration to
        Supabase, and is also useful during the CSV demo.  It remains explicit:
        nothing runs in the background merely because the API process started.
        """

        self._validate_actor(actor, write=True)
        records = self.repository.records()
        today = datetime.now(timezone.utc).date()
        statuses = records["Record_Status"].astype(str).str.upper()
        effective = pd.to_datetime(records["Effective_Date"], errors="coerce").dt.date
        mask = statuses.eq("SCHEDULED") & effective.notna() & effective.le(today)
        if record_ids:
            wanted = {str(value).strip().upper() for value in record_ids if str(value).strip()}
            mask &= records["Action_Record_ID"].astype(str).str.upper().isin(wanted)
        due_ids = (
            records.loc[mask]
            .sort_values(["Effective_Date", "Recorded_DateTime"])
            .head(limit)["Action_Record_ID"]
            .astype(str)
            .tolist()
        )

        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for record_id in due_ids:
            try:
                applied.append(
                    self._apply_existing_scheduled_record(
                        record_id=record_id,
                        actor=actor,
                    )
                )
            except (ActionCenterValidationError, ActionCenterConflictError, ActionCenterNotFoundError) as exc:
                failed.append({"action_record_id": record_id, "message": str(exc)})

        return {
            "status": "success" if not failed else "partial_success",
            "due_found": len(due_ids),
            "applied_count": len(applied),
            "failed_count": len(failed),
            "applied": applied,
            "failed": failed,
        }

    def _apply_existing_scheduled_record(
        self,
        *,
        record_id: str,
        actor: ActionActor | None,
    ) -> dict[str, Any]:
        records = self.repository.records()
        mask = (
            records["Action_Record_ID"].astype(str).str.upper()
            == str(record_id).strip().upper()
        )
        if not mask.any():
            raise ActionCenterNotFoundError(f"Action record {record_id!r} was not found.")
        row = self.repository._clean_record(records.loc[mask].iloc[0].to_dict())
        if str(row.get("Record_Status", "")).upper() != "SCHEDULED":
            raise ActionCenterConflictError(
                f"Action record {record_id} is not SCHEDULED."
            )
        effective_date = self._parse_date(row.get("Effective_Date"), "Effective_Date")
        if effective_date > datetime.now(timezone.utc).date():
            raise ActionCenterConflictError(
                f"Action record {record_id} is not due until {effective_date.isoformat()}."
            )

        code = self.normalize_process_code(str(row["Process_Code"]))
        employee = self.repository.resolve_employee(employee_id=str(row["Employee_ID"]))
        fields: dict[str, Any] = {"employee_id": str(row["Employee_ID"]), "effective_date": effective_date.isoformat()}
        raw_json = row.get("Action_Data_JSON")
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    fields.update(parsed)
            except json.JSONDecodeError as exc:
                raise ActionCenterDataError(
                    f"Scheduled record {record_id} has invalid Action_Data_JSON."
                ) from exc
        if row.get("Target_Department_ID"):
            fields["target_department_id"] = row["Target_Department_ID"]
        if row.get("Target_Position_ID"):
            fields["target_position_id"] = row["Target_Position_ID"]
        if row.get("Source_Record_ID"):
            if code == "FINAL_SETTLEMENT":
                fields["separation_action_record_id"] = row["Source_Record_ID"]
            elif code == "RESIGN_WITHDRAW":
                fields["resignation_action_record_id"] = row["Source_Record_ID"]
        # Reason_Details is not needed for most impact handlers, but termination
        # requires it during revalidation.
        if row.get("Reason_Details") and not fields.get("reason_details"):
            fields["reason_details"] = row["Reason_Details"]

        process = self.process_detail(code)
        self._validate_required_fields(process, fields)
        resolved = self._validate_business_rules(
            code=code,
            employee=employee,
            fields=fields,
        )

        state = self.repository.operational_state()
        events = self.repository.events()
        now = datetime.now(timezone.utc)

        if code == "RESIGN_WITHDRAW":
            source_id = str(fields["resignation_action_record_id"])
            source_mask = (
                records["Action_Record_ID"].astype(str).str.upper()
                == source_id.upper()
            )
            if not source_mask.any():
                raise ActionCenterNotFoundError(
                    f"Source resignation {source_id} was not found."
                )
            source_status = str(records.loc[source_mask, "Record_Status"].iloc[0])
            records.loc[source_mask, "Record_Status"] = "WITHDRAWN"
            events = self._append_event(
                events,
                action_record_id=source_id,
                process_code="RESIGNATION",
                employee_id=str(employee["Employee_ID"]),
                event_type="WITHDRAWN",
                actor=actor,
                previous_status=source_status,
                new_status="WITHDRAWN",
                effect="Scheduled resignation cancelled; employee remains in service.",
                note=str(fields.get("withdrawal_reason") or ""),
                now=now,
            )

        state, effect = self._apply_operational_impact(
            state=state,
            code=code,
            employee_id=str(employee["Employee_ID"]),
            fields=fields,
            resolved=resolved,
            action_record_id=str(row["Action_Record_ID"]),
            now=now,
        )
        records.loc[mask, "Record_Status"] = "APPLIED"
        events = self._append_event(
            events,
            action_record_id=str(row["Action_Record_ID"]),
            process_code=code,
            employee_id=str(employee["Employee_ID"]),
            event_type="APPLIED",
            actor=actor,
            previous_status="SCHEDULED",
            new_status="APPLIED",
            effect=effect,
            note="Scheduled Action Center action became effective.",
            now=now,
        )
        self.repository.persist_action_transaction(
            operational_state=state,
            records=records,
            events=events,
        )
        self._notify_post_commit()
        return {
            "action_record_id": str(row["Action_Record_ID"]),
            "process_code": code,
            "employee_id": str(employee["Employee_ID"]),
            "record_status": "APPLIED",
            "effect": effect,
        }

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------

    def _validate_actor(self, actor: ActionActor | None, *, write: bool) -> None:
        if not write:
            return
        if actor is None:
            if self.settings.allow_local_actor:
                return
            raise ActionCenterAuthorizationError(
                "An authenticated HR actor is required for Action Center writes."
            )
        if self.settings.enforce_hr_role:
            role = (actor.role or "").strip().casefold()
            if role not in self.settings.allowed_roles:
                raise ActionCenterAuthorizationError(
                    f"Role {actor.role!r} is not allowed to perform HR Action Center writes."
                )

    def _validate_required_fields(
        self,
        process: dict[str, Any],
        fields: dict[str, Any],
    ) -> None:
        missing = []
        for field in process.get("fields", []):
            required = str(field.get("Required", "")).strip().casefold() == "yes"
            key = str(field.get("Field_Key", "")).strip()
            if required and self._is_empty(fields.get(key)):
                missing.append(key)
        if missing:
            raise ActionCenterValidationError(
                "Missing required Action Center fields: " + ", ".join(missing)
            )

    def _validate_business_rules(
        self,
        *,
        code: str,
        employee: dict[str, Any],
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(
            employee.get("Employee_Status_Operational")
            or employee.get("Employee_Status_Source")
            or ""
        ).casefold()
        employment_type = str(
            employee.get("Operational_Employment_Type")
            or employee.get("Employment_Type")
            or ""
        ).casefold()
        context: dict[str, Any] = {}

        effective = fields.get("effective_date")
        if effective:
            self._parse_date(effective, "effective_date")

        if code in {
            "RESIGNATION",
            "RETIREMENT",
            "TERMINATION",
            "PROMOTION",
            "TRANSFER",
            "ACTING_CHARGE",
            "DEMOTION",
            "SECONDMENT",
        } and status not in ACTIVE_STATUSES:
            raise ActionCenterConflictError(
                f"{code} requires an active/probation employee. Current operational status is {status or 'unknown'}."
            )

        if code in {"PROB_CONFIRM", "PROB_EXTEND"}:
            probation_status = str(
                employee.get("Probation_Operational_Status") or ""
            ).casefold()
            if status != "probation" and probation_status not in {
                "active",
                "due",
                "extended",
                "pending",
            }:
                raise ActionCenterConflictError(
                    "This employee is not in an operational probation state."
                )

        if code in {"CONTRACT_RENEW", "CONTRACT_END"} and employment_type != "contract":
            raise ActionCenterConflictError(
                f"{code} can only be used for Contract employees."
            )

        if code == "REHIRE" and status in ACTIVE_STATUSES:
            raise ActionCenterConflictError(
                "Rejoining/Rehire requires an employee who is not currently active."
            )

        if code == "RESIGNATION":
            notice = self._parse_date(fields["notice_date"], "notice_date")
            eff = self._parse_date(fields["effective_date"], "effective_date")
            if notice > eff:
                raise ActionCenterValidationError(
                    "notice_date must be on or before effective_date."
                )

        if code == "RESIGN_WITHDRAW":
            source = self.repository.get_action_record(
                str(fields["resignation_action_record_id"])
            )
            if str(source.get("Process_Code", "")).upper() != "RESIGNATION":
                raise ActionCenterValidationError(
                    "resignation_action_record_id must reference a RESIGNATION record."
                )
            if str(source.get("Employee_ID", "")).upper() != str(employee["Employee_ID"]).upper():
                raise ActionCenterValidationError(
                    "The resignation record belongs to a different employee."
                )
            if str(source.get("Record_Status", "")).upper() != "SCHEDULED":
                raise ActionCenterConflictError(
                    "Only an active SCHEDULED resignation can be withdrawn."
                )
            withdrawal_date = self._parse_date(fields["effective_date"], "effective_date")
            resignation_date = self._parse_date(source["Effective_Date"], "resignation effective date")
            if withdrawal_date >= resignation_date:
                raise ActionCenterValidationError(
                    "Resignation withdrawal must be effective before the resignation effective date."
                )
            context["source_action_record"] = source

        if code == "FINAL_SETTLEMENT":
            source = self.repository.get_action_record(
                str(fields["separation_action_record_id"])
            )
            if str(source.get("Process_Code", "")).upper() not in SEPARATION_PROCESS_CODES:
                raise ActionCenterValidationError(
                    "Final settlement must reference resignation, retirement, termination, or contract end."
                )
            if str(source.get("Employee_ID", "")).upper() != str(employee["Employee_ID"]).upper():
                raise ActionCenterValidationError(
                    "The separation record belongs to a different employee."
                )
            if str(source.get("Record_Status", "")).upper() == "WITHDRAWN":
                raise ActionCenterConflictError(
                    "Final settlement cannot be recorded for a withdrawn separation."
                )
            settlement_date = self._parse_date(fields["effective_date"], "effective_date")
            separation_date = self._parse_date(source["Effective_Date"], "separation effective date")
            if settlement_date < separation_date:
                raise ActionCenterValidationError(
                    "Final settlement effective_date cannot be before separation effective date."
                )
            context["source_action_record"] = source

        if code == "PROB_CONFIRM":
            eff = self._parse_date(fields["effective_date"], "effective_date")
            hire = self._coerce_date_value(employee.get("Hire_Date"))
            if hire and eff < hire:
                raise ActionCenterValidationError(
                    "Probation confirmation effective_date cannot be before Hire_Date."
                )

        if code == "PROB_EXTEND":
            months = int(fields["extension_months"])
            if months not in {1, 2, 3}:
                raise ActionCenterValidationError("extension_months must be 1, 2, or 3.")
            eff = self._parse_date(fields["effective_date"], "effective_date")
            original_end = self._coerce_date_value(
                employee.get("Probation_Original_End_Date")
            )
            if original_end and eff < original_end:
                raise ActionCenterValidationError(
                    "Probation extension effective_date cannot be before the original probation end date."
                )

        if code == "CONTRACT_RENEW":
            eff = self._parse_date(fields["effective_date"], "effective_date")
            current_end = self._coerce_date_value(
                employee.get("Contract_Current_End_Date")
            )
            if current_end and eff < current_end:
                raise ActionCenterValidationError(
                    "Contract renewal effective_date must be on or after the current contract end date."
                )
            end = self._parse_date(fields["new_end_date"], "new_end_date")
            if end <= eff:
                raise ActionCenterValidationError("new_end_date must be after effective_date.")
            term = int(fields["renewal_term_months"])
            if term not in {6, 12, 24}:
                raise ActionCenterValidationError(
                    "renewal_term_months must be 6, 12, or 24."
                )

        if code in {"ACTING_CHARGE", "SECONDMENT"}:
            end_key = "end_date" if code == "ACTING_CHARGE" else "expected_return_date"
            eff = self._parse_date(fields["effective_date"], "effective_date")
            end = self._parse_date(fields[end_key], end_key)
            if end <= eff:
                raise ActionCenterValidationError(
                    f"{end_key} must be after effective_date."
                )

        if code in {
            "PROMOTION",
            "TRANSFER",
            "DEMOTION",
            "REHIRE",
            "ACTING_CHARGE",
            "SECONDMENT",
        }:
            target_position = self.repository.get_position(
                str(fields["target_position_id"])
            )
            current_employee_id = str(employee["Employee_ID"])
            if str(target_position.get("Approved_Position", "")).casefold() != "yes":
                raise ActionCenterConflictError("Target position is not approved.")
            target_position_status = str(
                target_position.get("Position_Status", "")
            ).casefold()
            target_freeze_status = str(
                target_position.get("Position_Freeze_Status", "")
            ).casefold()
            if (
                target_position_status == "frozen"
                or "freeze" in target_freeze_status
            ):
                raise ActionCenterConflictError("Target position is frozen.")
            if code in {"PROMOTION", "TRANSFER", "DEMOTION", "REHIRE"} and not self.repository.position_is_available(
                str(target_position["Position_ID"]),
                current_employee_id=current_employee_id,
            ):
                raise ActionCenterConflictError(
                    "Target position is already occupied in the current Action Center operational state."
                )
            context["target_position"] = target_position

            current_level = self._job_level_rank(
                employee.get("Operational_Job_Level") or employee.get("Job_Level")
            )
            target_level = self._job_level_rank(target_position.get("Job_Level"))
            if code == "PROMOTION" and target_level <= current_level:
                raise ActionCenterValidationError(
                    "Promotion target must be at a higher job level."
                )
            if code == "DEMOTION" and target_level >= current_level:
                raise ActionCenterValidationError(
                    "Demotion target must be at a lower job level."
                )
            if code == "DEMOTION" and str(target_position.get("Budgeted_Position", "")).casefold() != "yes":
                raise ActionCenterConflictError("Demotion target position must be budgeted.")

        if code in {"TRANSFER", "SECONDMENT", "REHIRE"}:
            target_dept_id = str(fields["target_department_id"]).strip().upper()
            target_department = self.repository.get_department(target_dept_id)
            if str(target_department.get("Active_Status", "")).casefold() != "active":
                raise ActionCenterConflictError("Target department is not active.")
            current_dept = str(
                employee.get("Operational_Department_ID")
                or employee.get("Department_ID")
                or ""
            ).upper()
            if code in {"TRANSFER", "SECONDMENT"} and target_dept_id == current_dept:
                raise ActionCenterValidationError(
                    "Target department must be different from the employee's current department."
                )
            if "target_position" in context:
                pos_dept = str(context["target_position"].get("Department_ID", "")).upper()
                if pos_dept and pos_dept != target_dept_id:
                    raise ActionCenterValidationError(
                        "Target position does not belong to target_department_id."
                    )
            context["target_department"] = target_department

        return context

    # ------------------------------------------------------------------
    # RECORD BUILD / IMPACT
    # ------------------------------------------------------------------

    def _build_record(
        self,
        *,
        action_record_id: str,
        code: str,
        employee: dict[str, Any],
        fields: dict[str, Any],
        resolved: dict[str, Any],
        actor: ActionActor | None,
        record_status: str,
        now: datetime,
    ) -> dict[str, Any]:
        process = self.process_detail(code)
        target_position = resolved.get("target_position") or {}
        target_department = resolved.get("target_department") or {}
        actor_id = actor.user_id if actor else "local-hr-demo"
        actor_name = (
            actor.name or actor.email or actor.user_id
            if actor
            else "Local HR Demo User"
        )

        current_department_id = employee.get("Operational_Department_ID") or employee.get("Department_ID")
        current_department_name = employee.get("Operational_Department_Name") or employee.get("Department_Name")
        current_position_id = employee.get("Operational_Position_ID") or employee.get("Position_ID")
        current_position_title = employee.get("Operational_Position_Title") or employee.get("Position_Title")
        current_job_level = employee.get("Operational_Job_Level") or employee.get("Job_Level")

        action_data = {
            key: value
            for key, value in fields.items()
            if key not in {
                "employee_id",
                "effective_date",
                "notice_date",
                "note",
                "target_department_id",
                "target_position_id",
            }
        }
        if fields.get("notice_date"):
            action_data["notice_date"] = fields["notice_date"]
        if actor and actor.role:
            action_data["actor_role"] = actor.role

        reason_category = self._first_value(
            fields,
            [
                "resignation_reason",
                "termination_category",
                "retirement_type",
                "promotion_reason",
                "transfer_reason",
                "extension_reason",
                "rehire_reason",
                "end_reason",
                "demotion_reason",
                "secondment_reason",
                "withdrawal_reason",
                "charge_type",
                "decision",
                "settlement_status",
            ],
        )
        reason_details = (
            fields.get("reason_details")
            or fields.get("note")
            or ""
        )

        return {
            "Action_Record_ID": action_record_id,
            "Process_Code": code,
            "Process_Name": process["Process_Name"],
            "Process_Group": process["Process_Group"],
            "Employee_ID": employee["Employee_ID"],
            "Employee_Name": employee["Employee_Name"],
            "Department_ID": current_department_id,
            "Department_Name": current_department_name,
            "Business_Unit": employee.get("Operational_Business_Unit") or employee.get("Business_Unit"),
            "Organizational_Unit_ID": employee.get("Operational_Organizational_Unit_ID") or employee.get("Organizational_Unit_ID"),
            "Work_Location_ID": employee.get("Operational_Work_Location_ID") or employee.get("Work_Location_ID"),
            "Current_Position_ID": current_position_id,
            "Current_Position_Title": current_position_title,
            "Current_Job_Level": current_job_level,
            "Recorded_DateTime": now.isoformat(),
            "Effective_Date": fields.get("effective_date") or now.date().isoformat(),
            "Record_Status": record_status,
            "Effect_Mode": process["Execution_Mode"],
            "Performed_By_Employee_ID": actor_id,
            "Performed_By_Name": actor_name,
            "Reason_Category": reason_category or "",
            "Reason_Details": reason_details,
            "Target_Department_ID": target_department.get("Department_ID") or fields.get("target_department_id") or "",
            "Target_Department_Name": target_department.get("Department_Name") or "",
            "Target_Position_ID": target_position.get("Position_ID") or fields.get("target_position_id") or "",
            "Target_Position_Title": target_position.get("Position_Title") or "",
            "Target_Job_Level": target_position.get("Job_Level") or "",
            "Action_Data_JSON": json.dumps(action_data, ensure_ascii=False, default=str),
            "Source_Basis": "Action Center API/LLM deterministic execution",
            "Source_Record_ID": fields.get("separation_action_record_id") or fields.get("resignation_action_record_id") or "",
            "Data_As_Of_Date": now.date().isoformat(),
        }

    def _apply_operational_impact(
        self,
        *,
        state: pd.DataFrame,
        code: str,
        employee_id: str,
        fields: dict[str, Any],
        resolved: dict[str, Any],
        action_record_id: str,
        now: datetime,
    ) -> tuple[pd.DataFrame, str]:
        mask = state["Employee_ID"].astype(str).str.upper() == employee_id.upper()
        if not mask.any():
            raise ActionCenterNotFoundError(f"Employee {employee_id} is missing from operational state.")

        effect = "Operational state updated."
        target_position = resolved.get("target_position") or {}
        target_department = resolved.get("target_department") or {}

        if code == "PROB_CONFIRM":
            state.loc[mask, "Employee_Status_Operational"] = "Active"
            state.loc[mask, "Probation_Operational_Status"] = "CONFIRMED"
            state.loc[mask, "Probation_Confirmation_Date"] = fields["effective_date"]
            effect = "Probation confirmed; operational employee status is Active."

        elif code == "PROB_EXTEND":
            current_end = self._coerce_date_value(
                state.loc[mask, "Probation_Current_End_Date"].iloc[0]
            ) or self._parse_date(fields["effective_date"], "effective_date")
            months = int(fields["extension_months"])
            new_end = pd.Timestamp(current_end) + pd.DateOffset(months=months)
            state.loc[mask, "Employee_Status_Operational"] = "Probation"
            state.loc[mask, "Probation_Current_End_Date"] = new_end.date().isoformat()
            state.loc[mask, "Probation_Operational_Status"] = "EXTENDED"
            current_count = pd.to_numeric(
                state.loc[mask, "Probation_Extension_Count"], errors="coerce"
            ).fillna(0).astype(int)
            state.loc[mask, "Probation_Extension_Count"] = current_count + 1
            effect = f"Probation extended by {months} month(s) to {new_end.date().isoformat()}."

        elif code == "CONTRACT_RENEW":
            state.loc[mask, "Contract_Current_End_Date"] = fields["new_end_date"]
            state.loc[mask, "Contract_Operational_Status"] = "RENEWED"
            current_count = pd.to_numeric(
                state.loc[mask, "Contract_Renewal_Count"], errors="coerce"
            ).fillna(0).astype(int)
            state.loc[mask, "Contract_Renewal_Count"] = current_count + 1
            effect = f"Contract renewed through {fields['new_end_date']}."

        elif code == "REHIRE":
            self._set_operational_position(state, mask, target_position)
            if target_department:
                self._set_operational_department(state, mask, target_department)
            state.loc[mask, "Employee_Status_Operational"] = "Active"
            state.loc[mask, "Rehire_Count"] = pd.to_numeric(
                state.loc[mask, "Rehire_Count"], errors="coerce"
            ).fillna(0).astype(int) + 1
            state.loc[mask, "Last_Rehire_Date"] = fields["effective_date"]
            state.loc[mask, "Rehire_Last_Reason"] = fields.get("rehire_reason", "")
            effect = "Employee rejoined active service in the selected operational position."

        elif code in {"CONTRACT_END", "RESIGNATION", "RETIREMENT", "TERMINATION"}:
            status_map = {
                "CONTRACT_END": "Contract Ended",
                "RESIGNATION": "Left",
                "RETIREMENT": "Retired",
                "TERMINATION": "Terminated",
            }
            state.loc[mask, "Employee_Status_Operational"] = status_map[code]
            if code == "CONTRACT_END":
                state.loc[mask, "Contract_End_Decision"] = "NON_RENEWAL"
                state.loc[mask, "Contract_End_Effective_Date"] = fields["effective_date"]
                state.loc[mask, "Contract_Operational_Status"] = "ENDED"
            state.loc[mask, "Current_Notice_Type"] = code
            state.loc[mask, "Current_Notice_Effective_Date"] = fields["effective_date"]
            effect = (
                f"Operational employee status changed to {status_map[code]}; "
                "the employee no longer counts as active in Action Center operational views."
            )

        elif code == "RESIGN_WITHDRAW":
            source_status = str(
                state.loc[mask, "Employee_Status_Source"].iloc[0]
            ) or "Active"
            current = str(
                state.loc[mask, "Employee_Status_Operational"].iloc[0]
            )
            if current.casefold() not in ACTIVE_STATUSES:
                state.loc[mask, "Employee_Status_Operational"] = source_status
            state.loc[mask, "Current_Notice_Type"] = "NONE"
            state.loc[mask, "Current_Notice_Effective_Date"] = ""
            state.loc[mask, "Resignation_Withdrawal_Count"] = pd.to_numeric(
                state.loc[mask, "Resignation_Withdrawal_Count"], errors="coerce"
            ).fillna(0).astype(int) + 1
            state.loc[mask, "Last_Resignation_Withdrawal_Date"] = fields["effective_date"]
            effect = "Scheduled resignation withdrawn; employee remains in service."

        elif code == "FINAL_SETTLEMENT":
            state.loc[mask, "Final_Settlement_Status"] = fields["settlement_status"]
            state.loc[mask, "Final_Settlement_Due_Date"] = fields["effective_date"]
            state.loc[mask, "Final_Settlement_Action_Record_ID"] = action_record_id
            effect = (
                f"Final settlement operational status set to {fields['settlement_status']} "
                f"with clearance {fields['clearance_status']}."
            )

        elif code in {"PROMOTION", "DEMOTION"}:
            self._set_operational_position(state, mask, target_position)
            target_dept_id = target_position.get("Department_ID")
            if target_dept_id:
                target_dept = self.repository.get_department(str(target_dept_id))
                self._set_operational_department(state, mask, target_dept)
            effect = (
                f"Operational assignment moved to {target_position.get('Position_Title')} "
                f"({target_position.get('Job_Level')})."
            )

        elif code == "TRANSFER":
            self._set_operational_position(state, mask, target_position)
            self._set_operational_department(state, mask, target_department)
            effect = (
                f"Operational assignment transferred to {target_department.get('Department_Name')} / "
                f"{target_position.get('Position_Title')}; organization total headcount is unchanged."
            )

        elif code == "ACTING_CHARGE":
            state.loc[mask, "Acting_Charge_Status"] = fields.get("charge_type", "ACTING")
            state.loc[mask, "Acting_Target_Position_ID"] = fields["target_position_id"]
            state.loc[mask, "Acting_Charge_End_Date"] = fields["end_date"]
            effect = "Temporary acting/additional charge recorded; primary position and headcount remain unchanged."

        elif code == "SECONDMENT":
            state.loc[mask, "Secondment_Status"] = "ACTIVE"
            state.loc[mask, "Secondment_To_Department_ID"] = fields["target_department_id"]
            state.loc[mask, "Secondment_Target_Position_ID"] = fields["target_position_id"]
            state.loc[mask, "Secondment_Expected_Return_Date"] = fields["expected_return_date"]
            effect = "Secondment recorded while retaining the home operational assignment."

        state.loc[mask, "Operational_State_Updated_At"] = now.isoformat()
        state.loc[mask, "Last_Action_Record_ID"] = action_record_id
        state.loc[mask, "Last_Action_Process_Code"] = code
        return state, effect

    def _record_scheduled_state(
        self,
        *,
        state: pd.DataFrame,
        code: str,
        employee_id: str,
        fields: dict[str, Any],
        action_record_id: str,
        now: datetime,
    ) -> pd.DataFrame:
        mask = state["Employee_ID"].astype(str).str.upper() == employee_id.upper()
        if code in {"RESIGNATION", "RETIREMENT", "TERMINATION", "CONTRACT_END"}:
            state.loc[mask, "Current_Notice_Type"] = code
            state.loc[mask, "Current_Notice_Effective_Date"] = fields.get("effective_date", "")
        if code == "CONTRACT_END":
            state.loc[mask, "Contract_End_Decision"] = "NON_RENEWAL"
            state.loc[mask, "Contract_End_Effective_Date"] = fields.get("effective_date", "")
        state.loc[mask, "Operational_State_Updated_At"] = now.isoformat()
        state.loc[mask, "Last_Action_Record_ID"] = action_record_id
        state.loc[mask, "Last_Action_Process_Code"] = code
        return state

    def _append_event(
        self,
        events: pd.DataFrame,
        *,
        action_record_id: str,
        process_code: str,
        employee_id: str,
        event_type: str,
        actor: ActionActor | None,
        previous_status: str,
        new_status: str,
        effect: str,
        note: str,
        now: datetime,
    ) -> pd.DataFrame:
        event_id = self.repository.next_id(
            "events", "HREVT-", "Event_ID", 6
        )
        # If multiple events are appended before disk persistence, next_id sees
        # the old file. Offset from the in-memory frame as needed.
        existing = set(events["Event_ID"].astype(str)) if "Event_ID" in events.columns else set()
        if event_id in existing:
            max_num = 0
            for value in existing:
                text = value.upper().replace("HREVT-", "")
                if text.isdigit():
                    max_num = max(max_num, int(text))
            event_id = f"HREVT-{max_num + 1:06d}"

        actor_id = actor.user_id if actor else "local-hr-demo"
        actor_name = (
            actor.name or actor.email or actor.user_id
            if actor
            else "Local HR Demo User"
        )
        row = {
            "Event_ID": event_id,
            "Action_Record_ID": action_record_id,
            "Process_Code": process_code,
            "Employee_ID": employee_id,
            "Event_Type": event_type,
            "Event_DateTime": now.isoformat(),
            "Performed_By_Employee_ID": actor_id,
            "Performed_By_Name": actor_name,
            "Previous_Status": previous_status,
            "New_Status": new_status,
            "Effect": effect,
            "Note": note,
            "Data_As_Of_Date": now.date().isoformat(),
        }
        return pd.concat([events, pd.DataFrame([row])], ignore_index=True)

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _compact_employee_state(employee: dict[str, Any] | None) -> dict[str, Any] | None:
        if not employee:
            return None
        keys = [
            "Employee_ID",
            "Employee_Name",
            "Employee_Status_Operational",
            "Operational_Department_ID",
            "Operational_Department_Name",
            "Operational_Position_ID",
            "Operational_Position_Title",
            "Operational_Job_Level",
            "Operational_Employment_Type",
            "Manager_Employee_ID",
            "Probation_Operational_Status",
            "Probation_Current_End_Date",
            "Contract_Current_End_Date",
            "Contract_Operational_Status",
            "Current_Notice_Type",
            "Current_Notice_Effective_Date",
            "Final_Settlement_Status",
            "Acting_Charge_Status",
            "Secondment_Status",
            "Last_Action_Record_ID",
            "Last_Action_Process_Code",
            "Operational_State_Updated_At",
        ]
        return {key: employee.get(key) for key in keys if key in employee}

    @staticmethod
    def _clean_scalar(value: Any) -> Any:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        return value

    @staticmethod
    def _is_empty(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    @staticmethod
    def _parse_date(value: Any, label: str) -> date:
        try:
            ts = pd.to_datetime(value, errors="raise")
            return ts.date()
        except Exception as exc:
            raise ActionCenterValidationError(
                f"{label} must be a valid date (YYYY-MM-DD)."
            ) from exc

    @staticmethod
    def _coerce_date_value(value: Any) -> date | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return pd.to_datetime(value, errors="raise").date()
        except Exception:
            return None

    @staticmethod
    def _record_status_for_effective_date(value: Any) -> str:
        if not value:
            return "APPLIED"
        effective = pd.to_datetime(value, errors="coerce")
        if pd.isna(effective):
            raise ActionCenterValidationError("effective_date must be a valid date.")
        return "APPLIED" if effective.date() <= date.today() else "SCHEDULED"

    @staticmethod
    def _job_level_rank(value: Any) -> int:
        return JOB_LEVEL_ORDER.get(str(value or "").strip().casefold(), -1)

    @staticmethod
    def _first_value(fields: dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            value = fields.get(key)
            if value not in (None, ""):
                return value
        return ""

    @staticmethod
    def _set_operational_position(
        state: pd.DataFrame,
        mask: pd.Series,
        position: dict[str, Any],
    ) -> None:
        state.loc[mask, "Operational_Position_ID"] = position.get("Position_ID", "")
        state.loc[mask, "Operational_Position_Title"] = position.get("Position_Title", "")
        state.loc[mask, "Operational_Job_Level"] = position.get("Job_Level", "")
        if position.get("Employment_Type"):
            state.loc[mask, "Operational_Employment_Type"] = position.get("Employment_Type")
        if position.get("Organizational_Unit_ID"):
            state.loc[mask, "Operational_Organizational_Unit_ID"] = position.get("Organizational_Unit_ID")
        if position.get("Work_Location_ID"):
            state.loc[mask, "Operational_Work_Location_ID"] = position.get("Work_Location_ID")

    @staticmethod
    def _set_operational_department(
        state: pd.DataFrame,
        mask: pd.Series,
        department: dict[str, Any],
    ) -> None:
        state.loc[mask, "Operational_Department_ID"] = department.get("Department_ID", "")
        state.loc[mask, "Operational_Department_Name"] = department.get("Department_Name", "")
        if department.get("Business_Unit_Name"):
            state.loc[mask, "Operational_Business_Unit"] = department.get("Business_Unit_Name")
        if department.get("Primary_Work_Location_ID"):
            state.loc[mask, "Operational_Work_Location_ID"] = department.get("Primary_Work_Location_ID")

    @staticmethod
    def _filter_dates(
        frame: pd.DataFrame,
        *,
        column: str,
        start_date: str | None,
        end_date: str | None,
    ) -> pd.DataFrame:
        if column not in frame.columns or (not start_date and not end_date):
            return frame
        dates = pd.to_datetime(frame[column], errors="coerce")
        mask = pd.Series(True, index=frame.index)
        if start_date:
            start = pd.to_datetime(start_date, errors="raise")
            mask &= dates >= start
        if end_date:
            end = pd.to_datetime(end_date, errors="raise") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            mask &= dates <= end
        return frame[mask]
