# Frontend Contract — People at Risk

Base prefix:

```text
/api/v1/dashboard/attrition
```

The frontend should render the JSON fields only. It must not calculate model
predictions, risk counts, attrition factors, or successor scores.

## 1. People at Risk card

```http
GET /api/v1/dashboard/attrition/summary
```

Current dataset/model example:

```json
{
  "status": "success",
  "visual": "people_at_risk",
  "prediction_window": "next_6_months",
  "risk_threshold": 0.5,
  "total_employees": 200,
  "people_at_risk": 107,
  "people_not_at_risk": 93,
  "attrition_risk_rate_percent": 53.5,
  "people_at_risk_endpoint": "/api/v1/dashboard/attrition/people-at-risk"
}
```

The numbers are recomputed from the saved CatBoost model. They are not hardcoded.

## 2. Card click — ranked at-risk employees

```http
GET /api/v1/dashboard/attrition/people-at-risk?offset=0&limit=50
```

Optional filters:

```text
department=Finance
position_criticality=High
search=Ali
```

Example item:

```json
{
  "employee_id": "EMP155",
  "employee_name": "Noman Malik",
  "department": "Customer Support",
  "position_id": "POS-155",
  "position_title": "Senior Support Executive",
  "designation": "Senior Support Executive",
  "job_level": "Mid",
  "position_criticality": "Medium",
  "attrition_status": "At Risk",
  "risk_score_percent": 95.15,
  "attrition_factors": [
    "Job satisfaction",
    "Salary competitiveness against the market",
    "Recent overtime workload"
  ],
  "detail_endpoint": "/api/v1/dashboard/attrition/people-at-risk/EMP155",
  "profile_endpoint": "/api/v1/dashboard/attrition/employees/EMP155/profile"
}
```

## 3. Leaving employee detail

```http
GET /api/v1/dashboard/attrition/people-at-risk/{employee_id}
```

The response contains:

- employee identity and position criticality;
- model risk score;
- top model-derived attrition factors and their dataset values;
- top replacement candidates from the existing replacement workflow;
- reasons supplied by the existing replacement workflow;
- profile endpoint for every clickable employee name.

No unsupported leaving date, industry average, pension signal, commute reason,
or HR action is generated.

## 4. Employee profile

Use the same endpoint for the leaving employee and recommended replacements:

```http
GET /api/v1/dashboard/attrition/employees/{employee_id}/profile
```

It returns every field present in `Employee_Profile.csv`, plus position
criticality and current attrition context where available.

## 5. Refresh after data changes

```http
POST /api/v1/dashboard/attrition/refresh
```

The service also checks the modification time and size of the source CSV files
on every request. If employee rows are added locally, the next dashboard request
rebuilds the predictions automatically. On Render, updating the repository data
causes a redeploy and a fresh startup calculation.
