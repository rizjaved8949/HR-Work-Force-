# Scenario Simulation — Step 2

This step adds the reusable deterministic scenario-engine layer and implements
**Employee Promotion** as the first of the seven locked scenarios.

Existing application routes, attrition, replacement, performance, headcount,
authentication and HR-agent code are not modified.

## New flow

`SimulationRequest -> SimulationService -> ContextBuilder -> PromotionEngine -> SimulationResponse`

The engine reads current HR truth from `Data/*.csv` and simulation-only features
and business assumptions from `Data/Simulation/*.csv`. It never writes to those
files.

## Promotion request

```python
SimulationRequest(
    scenario_type="employee_promotion",
    employee_id="EMP002",
    target_position_id="POS-710",
)
```

The engine calculates target-role skill fit, mandatory-skill coverage, final
promotion readiness, ramp-up time, position-budget delta, vacancy implications,
and feasibility. It does not call an LLM and does not mutate workforce data.

## Test

```bash
PYTHONPATH=backend pytest -q \
  tests/test_simulation_data_layer.py \
  tests/test_employee_promotion_simulation.py
```
