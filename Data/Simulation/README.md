# Scenario Simulation Data

This folder is additive. Existing `Data/*.csv` files are not modified.

## Employee rule

`Employee_Profile.csv` remains the employee master. `Simulation_Employee_Features.csv`
contains the exact same current `Employee_ID` population and only simulation-specific
new/derived columns. The backend joins them by `Employee_ID` at runtime.

## Files

- `Simulation_Employee_Features.csv` — 720 employees; derived scenario features only.
- `Simulation_Department_Business_Evaluation.csv` — new business assumptions for department-level what-if analysis.
- `Simulation_Position_Business_Evaluation.csv` — new business assumptions for position-level impact analysis.
- `Simulation_Learning_Business_Evaluation.csv` — new training/reskilling business assumptions.
- `Simulation_Scenario_Catalog.csv` — locked seven scenario types.

## Locked seven scenarios

1. Employee Promotion
2. Employee Transfer
3. Headcount Reduction
4. Workforce Expansion / Hiring
5. Budget Change
6. Skill Gap / Reskilling
7. Business Demand / Workload Change

Attrition prediction and replacement/successor are existing system features and are not duplicated as new scenarios.
