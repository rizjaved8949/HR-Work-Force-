"""Small API-contract tests for the Action Center router."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from action_center.repository import ActionCenterRepository
from action_center.router import create_action_center_router
from action_center.service import ActionCenterService


FILES = [
    "Employee_HR_Operational_State.csv",
    "HR_Action_Process_Catalog.csv",
    "HR_Action_Process_Fields.csv",
    "HR_Action_Records.csv",
    "HR_Action_Record_Events.csv",
    "Employee_Profile.csv",
    "Position_Master.csv",
    "Department_Master.csv",
]


def test_action_center_read_routes(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "Data"
    data = tmp_path / "data"
    data.mkdir()
    for name in FILES:
        shutil.copy2(source / name, data / name)

    service = ActionCenterService(ActionCenterRepository(data))
    app = FastAPI()
    app.include_router(create_action_center_router(service))
    client = TestClient(app)

    summary = client.get("/api/action-center/summary")
    assert summary.status_code == 200
    assert summary.json()["process_count"] == 15

    process = client.get("/api/action-center/processes/TRANSFER")
    assert process.status_code == 200
    assert process.json()["Process_Name"] == "Employee Transfer"

    records = client.get("/api/action-center/records?process_code=TRANSFER&limit=2")
    assert records.status_code == 200
    assert records.json()["count"] == 10
    assert len(records.json()["records"]) == 2


def test_apply_due_route_exists(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "Data"
    data = tmp_path / "data"
    data.mkdir()
    for name in FILES:
        shutil.copy2(source / name, data / name)

    service = ActionCenterService(ActionCenterRepository(data))
    app = FastAPI()
    app.include_router(create_action_center_router(service))
    client = TestClient(app)

    response = client.post(
        "/api/action-center/apply-due",
        json={"record_ids": ["HRACT-00221"], "limit": 5},
    )
    assert response.status_code == 200
    assert response.json()["applied_count"] == 1
