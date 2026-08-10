from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from simulations.lookup_service import SimulationLookupService
from simulations.repository import SimulationRepository
from simulations.router import create_simulation_router
from simulations.service import SimulationDataService, SimulationService


DATA_DIR = Path(__file__).resolve().parents[1] / "Data"


def build_client() -> TestClient:
    repository = SimulationRepository(DATA_DIR)
    data_service = SimulationDataService(repository)
    simulation_service = SimulationService(repository)
    lookup_service = SimulationLookupService(repository)

    app = FastAPI()
    app.include_router(
        create_simulation_router(
            simulation_service=simulation_service,
            data_service=data_service,
            lookup_service=lookup_service,
        )
    )
    return TestClient(app)


def test_scenario_catalog_endpoint_returns_locked_seven():
    client = build_client()
    response = client.get("/api/v1/simulations/scenarios")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["scenarios"]) == 7
    codes = {item["code"] for item in payload["scenarios"]}
    assert codes == {
        "employee_promotion",
        "employee_transfer",
        "headcount_reduction",
        "workforce_expansion",
        "budget_change",
        "skill_reskilling",
        "business_demand_change",
    }


def test_employee_search_and_context():
    client = build_client()
    search = client.get("/api/v1/simulations/employees", params={"query": "EMP004"})
    assert search.status_code == 200
    employees = search.json()["employees"]
    assert employees
    assert employees[0]["employee_id"] == "EMP004"

    context = client.get("/api/v1/simulations/employees/EMP004/context")
    assert context.status_code == 200
    payload = context.json()
    assert payload["employee"]["employee_id"] == "EMP004"
    assert "simulation_features" in payload


def test_department_endpoint():
    client = build_client()
    response = client.get("/api/v1/simulations/departments", params={"query": "Finance"})
    assert response.status_code == 200
    departments = response.json()["departments"]
    assert any(item["department_name"] == "Finance" for item in departments)


def test_promotion_options_and_run():
    client = build_client()
    options = client.get(
        "/api/v1/simulations/options",
        params={"scenario_type": "employee_promotion", "employee_id": "EMP002"},
    )
    assert options.status_code == 200
    targets = options.json()["target_positions"]
    assert targets

    # Pick a higher-level position that the deterministic engine can evaluate.
    target = targets[0]["position_id"]
    run = client.post(
        "/api/v1/simulations/run",
        json={
            "scenario_type": "employee_promotion",
            "employee_id": "EMP002",
            "target_position_id": target,
            "parameters": {},
        },
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["scenario_type"] == "employee_promotion"
    assert payload["status"] == "completed"
    assert "baseline" in payload
    assert "simulated_state" in payload
    assert "impact" in payload
