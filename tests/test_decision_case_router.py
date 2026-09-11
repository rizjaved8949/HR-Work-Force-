from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from decision_cases.router import create_decision_case_router
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_decision_cases import _service


def test_router_returns_small_case_queue_and_updates_status() -> None:
    service = _service()
    app = FastAPI()
    app.include_router(create_decision_case_router(service))
    client = TestClient(app)

    evaluated = client.post("/api/v1/decision-cases/evaluate")
    assert evaluated.status_code == 200
    payload = evaluated.json()
    assert payload["dashboard_case_count"] == 4
    assert payload["dashboard_limit"] == 5

    listing = client.get("/api/v1/decision-cases?limit=5")
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 4
    assert body["total_matching"] == 4

    too_many = client.get("/api/v1/decision-cases?limit=10")
    assert too_many.status_code == 422

    case_id = body["cases"][0]["id"]
    changed = client.patch(
        f"/api/v1/decision-cases/{case_id}/status",
        json={"status": "Under Review"},
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "Under Review"
