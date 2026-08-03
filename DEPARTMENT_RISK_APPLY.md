# Attrition Risk by Department Patch

Copy the `visualizations` folder into the root of the existing repository and allow the three existing files to be replaced.

## New endpoint

```http
GET /api/v1/dashboard/attrition/department-risk
```

The bar value is `people_at_risk`. The response also contains `total_employees` and `risk_rate_percent` for tooltip/detail use.

## Test

```bat
python visualizations\tests\test_people_at_risk_pipeline.py
```

Expected additional output:

```text
Highest-risk department by count: Customer Support (25 people)
```

## Run API

```bat
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open Swagger:

```text
http://127.0.0.1:8000/docs
```
