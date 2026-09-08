"""Regression tests for the additive CSV-backed Action Center."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pandas as pd

from action_center.repository import ActionCenterRepository
from action_center.schemas import ActionActor
from action_center.service import ActionCenterService


ACTION_FILES = [
    "Employee_HR_Operational_State.csv",
    "HR_Action_Process_Catalog.csv",
    "HR_Action_Process_Fields.csv",
    "HR_Action_Records.csv",
    "HR_Action_Record_Events.csv",
]
REFERENCE_FILES = [
    "Employee_Profile.csv",
    "Position_Master.csv",
    "Department_Master.csv",
]


def _copy_data(source: Path, target: Path) -> None:
    target.mkdir()
    for name in ACTION_FILES + REFERENCE_FILES:
        shutil.copy2(source / name, target / name)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _service(tmp_path: Path) -> tuple[ActionCenterService, Path]:
    source = Path(__file__).resolve().parents[1] / "Data"
    data = tmp_path / "data"
    _copy_data(source, data)
    repo = ActionCenterRepository(data)
    return ActionCenterService(repo), data


def test_action_center_loads_same_720_employees_and_15_processes(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    state = service.repository.operational_state()
    assert len(state) == 720
    assert state["Employee_ID"].nunique() == 720
    assert len(service.supported_process_codes()) == 15


def test_summary_uses_seeded_action_data(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    summary = service.summary()
    assert summary["total_action_records"] == 313
    assert summary["process_count"] == 15
    assert summary["active_operational_employees"] == 720


def test_probation_extension_writes_only_action_center_files(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    core_before = {name: _sha256(data / name) for name in REFERENCE_FILES}
    records_before = len(service.repository.records())
    events_before = len(service.repository.events())

    actor = ActionActor(user_id="test-hr", name="Test HR", role="hr")
    preview = service.preview_action(
        process_code="PROB_EXTEND",
        employee_id="EMP036",
        employee_name=None,
        fields={
            "effective_date": "2026-09-08",
            "extension_months": 2,
            "extension_reason": "MANAGER_REVIEW",
            "note": "Additional manager review required.",
        },
        actor=actor,
    )
    assert preview["status"] == "ready"

    result = service.execute_action(
        process_code="PROB_EXTEND",
        employee_id="EMP036",
        employee_name=None,
        fields=preview["normalized_fields"],
        actor=actor,
    )
    assert result["status"] == "completed"
    assert result["core_analytics_files_modified"] is False
    assert len(service.repository.records()) == records_before + 1
    assert len(service.repository.events()) == events_before + 2

    employee = service.repository.resolve_employee(employee_id="EMP036")
    assert employee["Employee_Status_Operational"] == "Probation"
    assert employee["Probation_Operational_Status"] == "EXTENDED"

    core_after = {name: _sha256(data / name) for name in REFERENCE_FILES}
    assert core_before == core_after


def test_applied_record_is_immutable_to_record_patch(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    actor = ActionActor(user_id="test-hr", name="Test HR", role="hr")
    applied = service.repository.records()
    applied = applied[applied["Record_Status"] == "APPLIED"].iloc[0]

    try:
        service.update_action_record(
            action_record_id=str(applied["Action_Record_ID"]),
            updates={"Reason_Details": "should fail"},
            actor=actor,
        )
    except Exception as exc:
        assert "Only SCHEDULED" in str(exc)
    else:
        raise AssertionError("Applied Action Center record was unexpectedly editable")


def test_transfer_options_return_valid_reference_data(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    options = service.process_options("TRANSFER", employee_id="EMP004", limit=25)
    assert options["process_code"] == "TRANSFER"
    assert options["employee"]["Employee_ID"] == "EMP004"
    assert options["departments"]
    assert options["positions"]


def test_process_detail_contains_reference_style_statistics(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    detail = service.process_detail("TRANSFER")
    stats = detail["statistics"]
    assert stats["recorded_all_time"] == 10
    assert "recorded_last_30_days" in stats
    assert "status_counts" in stats


def test_apply_due_applies_existing_scheduled_record_without_duplicate(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    actor = ActionActor(user_id="test-hr", name="Test HR", role="hr")
    before = len(service.repository.records())
    result = service.apply_due_actions(
        actor=actor,
        record_ids=["HRACT-00221"],  # seeded due transfer
        limit=5,
    )
    assert result["applied_count"] == 1
    assert len(service.repository.records()) == before
    record = service.repository.get_action_record("HRACT-00221")
    assert record["Record_Status"] == "APPLIED"
