"""Configuration for the CSV-backed HR Action Center.

The module is deliberately isolated from the existing analytics repositories.
It reads the same core employee/position reference data, but writes only to the
five Action Center CSVs unless a future persistence adapter is explicitly added.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import paths


ACTION_CENTER_FILE_NAMES = {
    "operational_state": "Employee_HR_Operational_State.csv",
    "process_catalog": "HR_Action_Process_Catalog.csv",
    "process_fields": "HR_Action_Process_Fields.csv",
    "records": "HR_Action_Records.csv",
    "events": "HR_Action_Record_Events.csv",
}

CORE_REFERENCE_FILE_NAMES = {
    "employee_profile": "Employee_Profile.csv",
    "position_master": "Position_Master.csv",
    "department_master": "Department_Master.csv",
}


@dataclass(frozen=True)
class ActionCenterSettings:
    data_dir: Path
    enforce_hr_role: bool
    allow_local_actor: bool
    allowed_roles: tuple[str, ...]


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def get_action_center_settings() -> ActionCenterSettings:
    raw_dir = os.getenv("ACTION_CENTER_DATA_DIR", "").strip()
    data_dir = (
        Path(raw_dir).expanduser()
        if raw_dir
        else paths.data_dir()
    )
    if not data_dir.is_absolute():
        data_dir = paths.REPO_ROOT / data_dir

    roles = tuple(
        role.strip().casefold()
        for role in os.getenv(
            "ACTION_CENTER_ALLOWED_ROLES",
            "hr,hr manager,hr_manager,admin,super_admin,administrator",
        ).split(",")
        if role.strip()
    )

    return ActionCenterSettings(
        data_dir=data_dir.resolve(),
        # Disabled by default so the new module cannot lock out an existing
        # demo whose Supabase user metadata does not yet contain HR roles.
        # Turn it on after role values are verified in the deployment.
        enforce_hr_role=_as_bool(
            os.getenv("ACTION_CENTER_ENFORCE_HR_ROLE"),
            False,
        ),
        allow_local_actor=_as_bool(
            os.getenv("ACTION_CENTER_ALLOW_LOCAL_ACTOR"),
            True,
        ),
        allowed_roles=roles,
    )
