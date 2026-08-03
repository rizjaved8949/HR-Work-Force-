# Attrition Visualization Integration Notes

## Existing code preserved

The HR agent, employee-search tool, attrition tool, replacement tool, Dockerfile,
Render configuration, chatbot endpoints, and existing tests were not changed.

Only these changes were made:

1. Added the top-level `visualizations/` package.
2. Added one router import and one `app.include_router(...)` block to `app.py`.

## Paths

The visualization router receives:

```python
data_dir=DATA_PATH
model_path=MODEL_PATH
```

`DATA_PATH` and `MODEL_PATH` are still resolved by the existing
`backend/paths.py`, so the same code works in:

- a GitHub Desktop clone on Windows;
- the Docker image at `/app`;
- Render with `DATA_DIR=Data` and `MODEL_PATH=models/...`;
- CI tests from the repository root.

## Verification completed

- Python syntax compilation passed.
- Standalone People at Risk pipeline test passed.
- FastAPI router test passed for summary, list, detail, profile, and refresh.
- Current CatBoost result: 107 of 200 employees at risk at threshold 0.50.

## Local commands

```bat
cd <your-cloned-repository>
python visualizations\tests\test_people_at_risk_pipeline.py
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```
