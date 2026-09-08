"""CSV repository for the operational HR Action Center.

The repository is intentionally isolated from the read-only analytical
repositories already used by the project. Core employee, position and department
CSVs are reference-only. All writes are restricted to the Action Center CSVs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4

import pandas as pd

from .config import ACTION_CENTER_FILE_NAMES, CORE_REFERENCE_FILE_NAMES
from .errors import ActionCenterDataError, ActionCenterNotFoundError


OPERATIONAL_OVERLAY_DEFAULTS: dict[str, str] = {
    "Employee_Status_Operational": "Employee_Status_Source",
    "Operational_Department_ID": "Department_ID",
    "Operational_Department_Name": "Department_Name",
    "Operational_Business_Unit": "Business_Unit",
    "Operational_Organizational_Unit_ID": "Organizational_Unit_ID",
    "Operational_Work_Location_ID": "Work_Location_ID",
    "Operational_Position_ID": "Position_ID",
    "Operational_Position_Title": "Position_Title",
    "Operational_Job_Level": "Job_Level",
    "Operational_Employment_Type": "Employment_Type",
    "Operational_Manager_Employee_ID": "Manager_Employee_ID",
}

OPERATIONAL_EXTRA_COLUMNS: dict[str, Any] = {
    "Operational_State_Updated_At": "",
    "Last_Action_Record_ID": "",
    "Last_Action_Process_Code": "",
}


class ActionCenterRepository:
    """Read Action Center data and atomically persist operational changes."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self._lock = RLock()
        if not self.data_dir.is_dir():
            raise ActionCenterDataError(
                f"Action Center data directory was not found: {self.data_dir}"
            )
        self._validate_files()
        self.ensure_operational_overlay_columns()

    def path(self, key: str) -> Path:
        if key in ACTION_CENTER_FILE_NAMES:
            return self.data_dir / ACTION_CENTER_FILE_NAMES[key]
        if key in CORE_REFERENCE_FILE_NAMES:
            return self.data_dir / CORE_REFERENCE_FILE_NAMES[key]
        raise KeyError(f"Unknown Action Center dataset key: {key!r}")

    def _validate_files(self) -> None:
        missing = [
            name
            for name in (
                *ACTION_CENTER_FILE_NAMES.values(),
                *CORE_REFERENCE_FILE_NAMES.values(),
            )
            if not (self.data_dir / name).is_file()
        ]
        if missing:
            raise ActionCenterDataError(
                "Missing Action Center/reference CSV files: " + ", ".join(missing)
            )

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(
                path,
                encoding="utf-8-sig",
                keep_default_na=False,
                low_memory=False,
            )
        except Exception as exc:
            raise ActionCenterDataError(f"Could not read {path.name}: {exc}") from exc

    def get(self, key: str) -> pd.DataFrame:
        return self._read(self.path(key))

    def operational_state(self) -> pd.DataFrame:
        return self.get("operational_state")

    def process_catalog(self) -> pd.DataFrame:
        return self.get("process_catalog")

    def process_fields(self) -> pd.DataFrame:
        return self.get("process_fields")

    def records(self) -> pd.DataFrame:
        return self.get("records")

    def events(self) -> pd.DataFrame:
        return self.get("events")

    def employee_profile(self) -> pd.DataFrame:
        return self.get("employee_profile")

    def positions(self) -> pd.DataFrame:
        return self.get("position_master")

    def departments(self) -> pd.DataFrame:
        return self.get("department_master")

    def ensure_operational_overlay_columns(self) -> None:
        """Add only new Action Center columns when using a v2 CSV package.

        The source Employee_Profile.csv remains untouched. These overlay columns
        let actual HR actions change the Action Center's current operational view
        without risking existing analytics files.
        """

        with self._lock:
            frame = self.operational_state()
            changed = False

            for target, source in OPERATIONAL_OVERLAY_DEFAULTS.items():
                if target in frame.columns:
                    continue
                frame[target] = frame[source] if source in frame.columns else ""
                changed = True

            for column, default in OPERATIONAL_EXTRA_COLUMNS.items():
                if column in frame.columns:
                    continue
                frame[column] = default
                changed = True

            if changed:
                self._write_atomic(self.path("operational_state"), frame)

    def resolve_employee(
        self,
        *,
        employee_id: str | None = None,
        employee_name: str | None = None,
    ) -> dict[str, Any]:
        state = self.operational_state()
        if employee_id:
            target = str(employee_id).strip().upper()
            matches = state[
                state["Employee_ID"].astype(str).str.upper() == target
            ]
            if matches.empty:
                raise ActionCenterNotFoundError(
                    f"No employee matched employee ID {employee_id!r}."
                )
            return self._clean_record(matches.iloc[0].to_dict())

        if employee_name:
            target = str(employee_name).strip().casefold()
            names = state["Employee_Name"].astype(str)
            exact = state[names.str.casefold() == target]
            if len(exact) == 1:
                return self._clean_record(exact.iloc[0].to_dict())

            contains = state[
                names.str.casefold().str.contains(target, regex=False)
            ]
            if len(contains) == 1:
                return self._clean_record(contains.iloc[0].to_dict())
            if len(contains) > 1:
                candidates = [
                    {
                        "employee_id": row.get("Employee_ID"),
                        "employee_name": row.get("Employee_Name"),
                        "department": row.get("Operational_Department_Name")
                        or row.get("Department_Name"),
                        "position": row.get("Operational_Position_Title")
                        or row.get("Position_Title"),
                    }
                    for _, row in contains.head(8).iterrows()
                ]
                raise ActionCenterDataError(
                    "Employee name is ambiguous. Candidates: "
                    + json.dumps(candidates, ensure_ascii=False)
                )

        raise ActionCenterNotFoundError(
            "Provide employee_id or employee_name to resolve an employee."
        )

    def get_position(self, position_id: str) -> dict[str, Any]:
        positions = self.positions()
        target = str(position_id).strip().upper()
        matches = positions[
            positions["Position_ID"].astype(str).str.upper() == target
        ]
        if matches.empty:
            raise ActionCenterNotFoundError(
                f"No position matched {position_id!r}."
            )
        return self._clean_record(matches.iloc[0].to_dict())

    def get_department(self, department_id: str) -> dict[str, Any]:
        departments = self.departments()
        target = str(department_id).strip().upper()
        matches = departments[
            departments["Department_ID"].astype(str).str.upper() == target
        ]
        if matches.empty:
            raise ActionCenterNotFoundError(
                f"No department matched {department_id!r}."
            )
        return self._clean_record(matches.iloc[0].to_dict())

    def get_action_record(self, record_id: str) -> dict[str, Any]:
        records = self.records()
        target = str(record_id).strip().upper()
        matches = records[
            records["Action_Record_ID"].astype(str).str.upper() == target
        ]
        if matches.empty:
            raise ActionCenterNotFoundError(
                f"No Action Center record matched {record_id!r}."
            )
        return self._clean_record(matches.iloc[0].to_dict())

    def active_operational_occupants(self) -> dict[str, str]:
        """Map position -> employee using Action Center operational state."""

        state = self.operational_state()
        statuses = state["Employee_Status_Operational"].astype(str).str.casefold()
        active = state[
            statuses.isin({"active", "probation", "seconded", "acting"})
        ]
        occupants: dict[str, str] = {}
        for _, row in active.iterrows():
            position = str(row.get("Operational_Position_ID", "")).strip()
            employee = str(row.get("Employee_ID", "")).strip()
            if position and employee:
                occupants[position.upper()] = employee.upper()
        return occupants

    def position_is_available(
        self,
        position_id: str,
        *,
        current_employee_id: str | None = None,
    ) -> bool:
        occupants = self.active_operational_occupants()
        occupant = occupants.get(str(position_id).strip().upper())
        if not occupant:
            return True
        return bool(
            current_employee_id
            and occupant == str(current_employee_id).strip().upper()
        )

    def next_id(self, key: str, prefix: str, column: str, width: int) -> str:
        frame = self.get(key)
        max_value = 0
        for value in frame.get(column, pd.Series(dtype="string")):
            text = str(value).strip().upper()
            if not text.startswith(prefix.upper()):
                continue
            suffix = text[len(prefix):].replace("-", "")
            if suffix.isdigit():
                max_value = max(max_value, int(suffix))
        return f"{prefix}{max_value + 1:0{width}d}"

    def persist_action_transaction(
        self,
        *,
        operational_state: pd.DataFrame,
        records: pd.DataFrame,
        events: pd.DataFrame,
    ) -> None:
        """Persist the three mutable Action Center tables as one guarded unit."""

        with self._lock:
            paths_and_frames = {
                self.path("operational_state"): operational_state,
                self.path("records"): records,
                self.path("events"): events,
            }
            originals: dict[Path, bytes] = {
                path: path.read_bytes() for path in paths_and_frames
            }
            temp_paths: list[Path] = []
            try:
                for path, frame in paths_and_frames.items():
                    tmp = path.with_name(
                        f".{path.name}.{uuid4().hex}.tmp"
                    )
                    frame.to_csv(tmp, index=False, encoding="utf-8-sig")
                    temp_paths.append(tmp)

                for (path, _), tmp in zip(paths_and_frames.items(), temp_paths):
                    os.replace(tmp, path)

            except Exception as exc:
                for path, content in originals.items():
                    try:
                        path.write_bytes(content)
                    except Exception:
                        pass
                for tmp in temp_paths:
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
                raise ActionCenterDataError(
                    f"Action Center transaction could not be saved: {exc}"
                ) from exc

    def persist_records_and_events(
        self,
        *,
        records: pd.DataFrame,
        events: pd.DataFrame,
    ) -> None:
        with self._lock:
            state = self.operational_state()
            self.persist_action_transaction(
                operational_state=state,
                records=records,
                events=events,
            )

    @staticmethod
    def _write_atomic(path: Path, frame: pd.DataFrame) -> None:
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            frame.to_csv(tmp, index=False, encoding="utf-8-sig")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    @staticmethod
    def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if pd.isna(value):
                clean[str(key)] = None
            elif isinstance(value, pd.Timestamp):
                clean[str(key)] = value.isoformat()
            else:
                clean[str(key)] = value
        return clean

    @staticmethod
    def compact_records(
        frame: pd.DataFrame,
        *,
        columns: Iterable[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        available = [column for column in columns if column in frame.columns]
        if not available:
            return []
        subset = frame.loc[:, available].head(limit)
        return [
            ActionCenterRepository._clean_record(row)
            for row in subset.to_dict(orient="records")
        ]
