"""Tests for the deterministic Headcount FastAPI router."""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(
    __file__
).resolve().parents[1]

BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(
    0,
    str(BACKEND_DIR),
)


import paths
from headcount.repository import HeadcountRepository
from headcount.router import create_headcount_router
from headcount.service import HeadcountService


def build_client() -> TestClient:
    service = HeadcountService(
        HeadcountRepository(
            paths.data_dir()
        )
    )

    app = FastAPI()

    app.include_router(
        create_headcount_router(
            service
        )
    )

    return TestClient(
        app
    )


def metric_values(
    payload: dict[str, object],
) -> dict[str, object]:
    metrics = payload.get(
        "metrics",
        [],
    )

    assert isinstance(metrics, list)

    return {
        str(metric["metric_name"]):
            metric["value"]
        for metric in metrics
        if isinstance(metric, dict)
    }


def test_headcount_endpoint_returns_current_count() -> None:
    client = build_client()

    response = client.post(
        "/pipeline/headcount",
        json={
            "question": (
                "What is our current employee headcount?"
            ),
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "success"

    values = metric_values(
        payload
    )

    assert values["actual_employee_count"] == 720


def test_headcount_endpoint_supports_scope() -> None:
    client = build_client()

    response = client.post(
        "/pipeline/headcount",
        json={
            "question": (
                "Show Engineering headcount."
            ),
            "metrics": [
                "actual_employee_count",
            ],
            "scope": {
                "department": "Engineering",
            },
        },
    )

    assert response.status_code == 200

    values = metric_values(
        response.json()
    )

    assert values["actual_employee_count"] == 45


def test_headcount_endpoint_supports_definition() -> None:
    client = build_client()

    response = client.post(
        "/pipeline/headcount",
        json={
            "question": (
                "How is the vacancy rate calculated?"
            ),
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "success"
    assert len(payload["records"]) == 1


def test_headcount_endpoint_supports_combined_query() -> None:
    client = build_client()

    response = client.post(
        "/pipeline/headcount",
        json={
            "question": (
                "Show current headcount, budget utilization, "
                "and workforce availability."
            ),
            "metrics": [
                "actual_employee_count",
                "budget_utilization_percentage",
                "workforce_availability_percentage",
            ],
        },
    )

    assert response.status_code == 200

    values = metric_values(
        response.json()
    )

    assert values["actual_employee_count"] == 720

    assert (
        values["budget_utilization_percentage"]
        == 86.97
    )

    assert (
        values["workforce_availability_percentage"]
        == 86.67
    )


def test_headcount_endpoint_rejects_blank_question() -> None:
    client = build_client()

    response = client.post(
        "/pipeline/headcount",
        json={
            "question": "  ",
        },
    )

    assert response.status_code == 422
