# Step 8 Delivery Manifest

## New package

- `backend/feature_resolution/__init__.py`
- `backend/feature_resolution/models.py`
- `backend/feature_resolution/providers.py`
- `backend/feature_resolution/registry.py`
- `backend/feature_resolution/derivations.py`
- `backend/feature_resolution/resolver.py`
- `backend/feature_resolution/adapters.py`
- `backend/feature_resolution/service.py`
- `backend/feature_resolution/router.py`
- `backend/feature_resolution/cli.py`
- `backend/feature_resolution/README.md`
- `backend/feature_resolution/rules/feature_resolution_rules_v1.json`

## New tests

- `tests/test_feature_resolution_step8.py`

## New docs

- `docs/HR_FEATURE_RESOLUTION_STEP8.md`
- `docs/STEP8_VALIDATION_REPORT.md`

## Existing production runtime files modified

None.

Step 8 deliberately does not change `app.py`, the current attrition predictor,
performance service, scenario simulator, successor service, headcount services, or
agent tools. Their migration belongs to Step 9.
