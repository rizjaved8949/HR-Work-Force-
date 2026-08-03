# Apply Top Attrition Risk Drivers Patch

Extract this ZIP into the root of the existing `HR-Work-Force-` repository.
Allow these three files to be replaced:

- `visualizations/attrition/people_at_risk_service.py`
- `visualizations/attrition/router.py`
- `visualizations/tests/test_people_at_risk_pipeline.py`

No `app.py`, Dockerfile, Render, model, data, chatbot, or replacement workflow change is required.

## New endpoint

```http
GET /api/v1/dashboard/attrition/top-risk-drivers
```

Optional limit:

```http
GET /api/v1/dashboard/attrition/top-risk-drivers?limit=3
```

## Test

Run from the repository root:

```bat
python visualizations\tests\test_people_at_risk_pipeline.py
```

Expected current data result:

```text
PEOPLE AT RISK PIPELINE TEST PASSED
Top model risk driver: Job satisfaction (93 mentions, 28.97%)
```

## Interpretation

The endpoint aggregates the top positive SHAP/model features for employees predicted at risk. Percentages are shares of model risk-driver mentions. They are not confirmed resignation or exit-interview reasons.
