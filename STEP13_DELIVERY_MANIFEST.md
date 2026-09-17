# Step 13 Delivery Manifest

## Added
- `backend/production/`
- `tests/test_production_readiness_step13.py`
- `VERSION`
- `Dockerfile.production`
- `.github/workflows/step13-ci.yml`
- `deploy/production.env.example`
- `scripts/backup_app_state.sh`
- `scripts/backup_neo4j_volume.sh`
- `scripts/restore_neo4j_volume_to_new_volume.sh`
- Step 13 documentation

## Modified
- `app.py`: mounts Step-13 system router and production hardening middleware.
- `.env.example`: documents Step-13 environment policy.

## Non-breaking rule
No HR formula, CatBoost model feature order, ontology meaning, graph identity rule, or Step-12 tenant isolation rule is changed by Step 13.
