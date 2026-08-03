# Attrition Rate Card Pipeline

## New endpoint

`GET /api/v1/dashboard/attrition/attrition-rate`

The endpoint returns:
- predicted attrition rate percentage;
- people at risk;
- people not at risk;
- total employees;
- frontend card text;
- donut-chart segments;
- model threshold and interpretation note.

## Apply

Copy this patch into the repository root and allow the three existing files to be replaced.

## Test

```bash
python visualizations/tests/test_people_at_risk_pipeline.py
```

Expected additional output:

```text
Attrition Rate card: 53.5% (107 of 200 employees)
```

## API test

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` and execute:

`GET /api/v1/dashboard/attrition/attrition-rate`
