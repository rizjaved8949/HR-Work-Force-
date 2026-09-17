# Step 10 — Ontology Studio

Step 10 adds the management plane for the HR ontology without changing the
active ontology or source mappings silently.

## What it exposes

- ontology dashboard and validation status
- 39-entity / 65-relationship schema graph payload
- entity/property browser
- source dataset and column mapping browser
- service-contract coverage
- semantic attention queue
- staged mapping review workflow
- staged ontology change-request workflow
- tenant graph health/counts
- standalone reference UI at `/ontology-studio`

## Safety rule

Approval in Step 10 records a governance decision. It does **not** rewrite
`hr_ontology_v1.json` or `current_data_mappings.json`. Controlled application,
release versioning and rollback belong to the later production/versioning
boundary.

## App routes

The Step-2 `/ontology/*` and Step-3 `/mapping/*` read APIs are mounted in
Step 10. The management API is under `/ontology-studio/api/*`.

Write actions require one of `ONTOLOGY_STUDIO_ADMIN_ROLES` when
`AUTH_ENABLED=true`. With authentication disabled, local development remains
usable.
