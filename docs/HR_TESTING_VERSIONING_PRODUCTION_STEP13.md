# Step 13 — Testing, Versioning & Production

## Purpose
Step 13 turns the roadmap implementation into a releaseable system without changing HR business logic.

## What is added
- `VERSION` + release manifest and `/system/version`.
- `/system/liveness`, `/system/readiness`, `/system/release-gate`.
- CLI release gate for CI/CD.
- Request IDs + standard security headers.
- Production policy validation for authentication, CORS, tenant access and graph runtime mode.
- CI workflow running the complete Steps 2–13 regression suite.
- Production Dockerfile that runs as a non-root user.
- Safe application-state and Neo4j-volume backup helpers.

## Release policy
A release gate **fails** on actual blockers (missing model/data, ontology/mapping structural errors, unavailable required graph/Supabase, unsafe production CORS/auth/tenant-open-access policy). Known semantic uncertainty such as `PerformanceRecord.performanceTrend6M` remains a visible warning and is never silently normalized.

## Local readiness
```bash
python -m production.cli readiness --tenant-id ORGANIZATION-001 --strict
```

## Production release gate
Set production environment values first, then run:
```bash
python -m production.cli release-gate \
  --tenant-id ORGANIZATION-001 \
  --production \
  --strict
```
Exit code `0` means no release blocker was detected. Exit code `1` means deployment must stop until the reported errors are resolved.

## Backups
Application metadata/state:
```bash
bash scripts/backup_app_state.sh
```

Neo4j Docker volume snapshot:
```bash
bash scripts/backup_neo4j_volume.sh
```
The Neo4j helper stops the named container while copying the data volume and restarts it afterwards. This is intentional for consistency.

Restore is intentionally non-destructive: it only restores into a **new** Docker volume:
```bash
bash scripts/restore_neo4j_volume_to_new_volume.sh backup.tar.gz hr_neo4j_restore_test
```

## Important production note
`STEP9_ALLOW_LEGACY_FALLBACK=true` remains a warning while hybrid services still need compatibility behavior. It is not hidden or represented as full graph parity.
