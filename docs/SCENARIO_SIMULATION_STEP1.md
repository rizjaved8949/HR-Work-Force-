# Scenario Simulation — Step 1: Data Layer

## Objective

Add an isolated scenario-simulation data layer without changing any existing
attrition, replacement, performance, headcount, authentication, or chatbot flow.

## Data flow

```text
Existing Data/*.csv (read only)
        +
Data/Simulation/Simulation_Employee_Features.csv
        +
Data/Simulation/*_Business_Evaluation.csv
        |
        v
backend/simulations/SimulationRepository
        |
        v
SimulationDataService
```

`Employee_Profile.csv` stays the employee master. The simulation feature file
must contain the exact same Employee_ID set.

## Regenerate employee features

From repository root:

```bash
python -m backend.simulations.build_employee_features
```

## Verify Step 1

```bash
PYTHONPATH=backend pytest -q tests/test_simulation_data_layer.py
```

Expected validation:

- 720 employee master rows
- 720 simulation feature rows
- exact Employee_ID match
- zero duplicate Employee_IDs
- 7 locked scenarios

## Important

No router is connected to `app.py` in Step 1. That is deliberate. Once this
layer passes validation, Step 2 adds scenario request schemas and the first
`employee_promotion` engine without disturbing the existing application routes.
