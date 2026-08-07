from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from performance.repository import PerformanceRepository
from performance.router import create_performance_router
from performance.service import PerformanceService


def _client(data_dir: Path) -> TestClient:
    app = FastAPI()
    service = PerformanceService(PerformanceRepository(data_dir))
    app.include_router(create_performance_router(service))
    return TestClient(app)


def test_pipeline_performance(performance_data_dir: Path) -> None:
    response = _client(performance_data_dir).post(
        "/pipeline/performance",
        json={"question": "Give complete performance evaluation of EMP004"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["employee"]["Employee_ID"] == "EMP004"


def test_dashboard_overview(performance_data_dir: Path) -> None:
    response = _client(performance_data_dir).get(
        "/api/v1/dashboard/performance/overview"
    )
    assert response.status_code == 200
    assert response.json()["employee_count"] == 720


def test_employee_recommendations_route(performance_data_dir: Path) -> None:
    response = _client(performance_data_dir).get(
        "/api/v1/dashboard/performance/employees/EMP004/recommendations"
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
