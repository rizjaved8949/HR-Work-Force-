# Step 11 — Existing HR Application UI Integration

This package is the integration boundary between the already-built HR UI and
backend capabilities completed in Steps 1–10.

It does not duplicate HR business calculations in the browser. The existing
employee, attrition, performance, headcount, simulation, decision-case and chat
endpoints remain the authoritative business APIs.

## New integration endpoints

- `GET /ui-integration/bootstrap`
- `GET /ui-integration/navigation`
- `GET /ui-integration/runtime`
- `GET /ui-integration/api-contract`
- `GET /ui-integration/assets/hr-ui-client.js`
- `GET /ui-integration` — reference integration console

The bootstrap payload centralizes:

- current tenant (`STEP9_TENANT_ID`)
- authenticated user/role context
- admin-gated Ontology Studio navigation
- feature flags
- graph/legacy runtime source badges
- exact backend endpoint registry
- warnings and current migration mode

Multi-organization switching is intentionally not added in Step 11. That is
roadmap Step 12.
