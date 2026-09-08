from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "Data"


def _load_headcount_repository_class():
    """Load repository.py without importing headcount.__init__.

    The repository itself has no LangChain dependency.  This keeps the storage
    compatibility test runnable even in lightweight CI environments that have
    not installed the optional agent stack yet.
    """

    path = PROJECT_ROOT / "backend" / "headcount" / "repository.py"
    spec = importlib.util.spec_from_file_location("_hc_repo_overlay_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.HeadcountRepository


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_overlay_is_identical_before_new_operational_changes() -> None:
    Repository = _load_headcount_repository_class()
    plain = Repository(DATA_DIR, use_action_center_overlay=False)
    overlay = Repository(DATA_DIR, use_action_center_overlay=True)

    pairs = {
        "employees": ["Employee_ID", "Department_ID", "Position_ID", "Employee_Status"],
        "assignments": ["Employee_ID", "Position_ID", "Department_ID", "Assignment_Status"],
        "positions": ["Position_ID", "Position_Status", "Current_Employee_ID"],
        "departments": ["Department_ID", "Current_Employee_Count"],
        # Current_Headcount_Summary intentionally remains legacy/static.  The
        # deterministic current Headcount service uses assignments + positions.
        "current_summary": ["Department_ID", "Actual_Employee_Count"],
    }
    for table, columns in pairs.items():
        left = plain.get_table(table)[columns].astype(str).reset_index(drop=True)
        right = overlay.get_table(table)[columns].astype(str).reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)


def test_exit_overlay_changes_current_headcount_without_mutating_core_csvs(tmp_path: Path) -> None:
    Repository = _load_headcount_repository_class()
    data = tmp_path / "Data"
    shutil.copytree(DATA_DIR, data)

    protected = [
        "Employee_Profile.csv",
        "Employee_Assignment_History.csv",
        "Position_Master.csv",
        "Department_Master.csv",
    ]
    before_hash = {name: _sha256(data / name) for name in protected}

    state_path = data / "Employee_HR_Operational_State.csv"
    state = pd.read_csv(state_path, encoding="utf-8-sig", keep_default_na=False)
    employee_id = str(state.iloc[0]["Employee_ID"])
    state.loc[state["Employee_ID"] == employee_id, "Employee_Status_Operational"] = "Left"
    state.loc[state["Employee_ID"] == employee_id, "Operational_State_Updated_At"] = (
        "2026-09-08T16:30:00+00:00"
    )
    state.to_csv(state_path, index=False, encoding="utf-8-sig")

    repository = Repository(data, use_action_center_overlay=True)
    assignments = repository.get_table("assignments")
    positions = repository.get_table("positions")
    employees = repository.get_table("employees")

    current_assignments = (
        assignments["Assignment_Status"].astype(str).str.casefold().eq("current").sum()
    )
    open_positions = (
        positions["Position_Status"].astype(str).str.casefold().isin({"vacant", "frozen"}).sum()
    )

    assert len(employees) == 719
    assert int(current_assignments) == 719
    assert int(open_positions) == 81
    assert all(_sha256(data / name) == before_hash[name] for name in protected)
