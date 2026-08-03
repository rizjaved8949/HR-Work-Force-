# Attrition Dashboard Pipeline

This folder is intentionally separate from the HR chatbot implementation.
It returns JSON for frontend visualizations and reuses the repository's shared
CSV data, CatBoost model, and replacement recommendation tool.

## Data policy

Responses are generated only from:

- `Data/Final_Attrition_Dataset_200_Employees.csv`
- `Data/Employee_Profile.csv`
- `Data/Position_Master.csv`
- `models/catboost_attrition_model.cbm`
- the existing local replacement workflow

No industry benchmark, exit timing window, commute explanation, pension signal,
or recommended HR action is invented.

## Endpoints

### People at Risk card

```http
GET /api/v1/dashboard/attrition/summary
```

### Ranked employee list

```http
GET /api/v1/dashboard/attrition/people-at-risk
```

Optional query parameters:

- `offset`
- `limit`
- `department`
- `position_criticality`
- `search`

### Employee risk detail and replacements

```http
GET /api/v1/dashboard/attrition/people-at-risk/{employee_id}
```

### Clickable employee profile

```http
GET /api/v1/dashboard/attrition/employees/{employee_id}/profile
```

### Force refresh after a CSV update

```http
POST /api/v1/dashboard/attrition/refresh
```

The service also checks CSV and model modification timestamps on every request.
When employee rows are added locally, the next request automatically rebuilds
all counts. On Render, committing updated data causes a redeploy and startup
rebuild.

## Local test

Run from the repository root:

```bash
python visualizations/tests/test_people_at_risk_pipeline.py
```

## Frontend flow

1. Call `/summary` for the card.
2. On card click, call `/people-at-risk`.
3. On employee click, call `/people-at-risk/{employee_id}`.
4. On any employee name click, call `/employees/{employee_id}/profile`.
