# Scenario Simulation API Layer — Step 4

This step exposes the already-tested deterministic Scenario Simulation core to
the dedicated Scenario Simulator frontend without changing the existing app,
HR agent, attrition, replacement, performance, headcount, or authentication
logic.

## Added files

- `backend/simulations/lookup_service.py`
- `backend/simulations/router.py`
- `tests/test_simulation_api_layer.py`

## Frontend endpoints

- `GET /api/v1/simulations/health`
- `GET /api/v1/simulations/scenarios`
- `GET /api/v1/simulations/employees?query=...`
- `GET /api/v1/simulations/employees/{employee_id}/context`
- `GET /api/v1/simulations/departments?query=...`
- `GET /api/v1/simulations/options?...`
- `POST /api/v1/simulations/run`

`POST /run` reuses the exact same `SimulationService` that will later be
exposed to the HR agent as one `scenario_simulation` tool.

Do not integrate `app.py` until the isolated API tests pass.
