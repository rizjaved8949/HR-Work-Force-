# Step 11 — Existing HR Application UI Integration

## Purpose

Step 11 connects the already-built HR application UI to the architecture from
Steps 5–10 without moving business logic into the browser and without changing
existing employee/analytics endpoint contracts.

The backend bundle does not contain the external React/Vite/Next application
source. Therefore Step 11 implements the integration contract the existing UI
can consume directly: tenant context, permissions, navigation metadata,
runtime-source badges, a stable endpoint registry and a drop-in browser client.
It also exposes a reference integration console for live verification.

## Architecture

```text
Existing HR UI
    |
    +--> GET /ui-integration/bootstrap
    |       tenant + user role + feature flags + nav + source badges
    |
    +--> existing business APIs (unchanged)
    |       /tools/employee-search
    |       /pipeline/attrition
    |       /pipeline/performance
    |       /pipeline/headcount
    |       /pipeline/replacement
    |       /api/v1/simulations/*
    |       /api/v1/decision-cases/*
    |       /chat /chat/stream
    |
    +--> /ontology-studio (admin navigation)
```

The browser never connects to Neo4j and never receives Neo4j credentials.

## New Step-11 endpoints

- `GET /ui-integration/bootstrap`
- `GET /ui-integration/navigation`
- `GET /ui-integration/runtime`
- `GET /ui-integration/api-contract`
- `GET /ui-integration/assets/hr-ui-client.js`
- `GET /ui-integration` — reference integration console

## Bootstrap contract

`/ui-integration/bootstrap` is the recommended first call after login/session
restore. It returns:

- `tenant_id` from the current Step-9 runtime
- whether Supabase auth is enabled
- current authenticated user and admin visibility
- `graph_available`
- `ui_api_contract_preserved`
- visible navigation modules
- feature flags
- Step-9 runtime source/status per service
- endpoint groups
- migration warnings

## Tenant behavior

Step 11 intentionally uses the configured `STEP9_TENANT_ID`. It does not add a
fake organization switcher. True multi-organization membership, organization
selection and tenant onboarding belong to Step 12.

## Navigation / permissions

Normal users receive HR application modules. Ontology Studio is included only
for an approved admin role when authentication is enabled. With local auth
disabled, it remains visible for development.

Default Step-11 admin roles:

`admin,owner,hr_admin,super_admin`

Configure through:

```env
STEP11_ADMIN_ROLES=admin,owner,hr_admin,super_admin
```

Step 10 still independently enforces Ontology Studio write authorization.
Hiding a nav item is not treated as backend security.

## Drop-in browser client

The browser SDK is served at:

`/ui-integration/assets/hr-ui-client.js`

Example:

```js
import { HRWorkforceClient } from "http://127.0.0.1:8000/ui-integration/assets/hr-ui-client.js";

const api = new HRWorkforceClient({
  baseUrl: "http://127.0.0.1:8000",
  getAccessToken: () => authSession?.access_token,
});

const bootstrap = await api.bootstrap();
const employee = await api.searchEmployee({ employee_id: "EMP001" });
const risk = await api.attrition({ employee_id: "EMP001" });
```

The SDK does not decide where tokens are stored. It accepts the existing UI's
session/token provider and forwards `Authorization: Bearer ...` only when a
token is available.

## Existing UI route ownership

Step 11 deliberately returns logical `route_key` values (`employees`,
`attrition`, `performance`, etc.) instead of inventing React/Next/Vite page URLs
that are not present in this backend repository. The existing frontend maps
those route keys to its own components/routes.

## Environment

```env
STEP11_APP_NAME=HR Workforce Intelligence
STEP11_ONTOLOGY_STUDIO_NAV=true
STEP11_REFERENCE_CONSOLE=true
STEP11_ADMIN_ROLES=admin,owner,hr_admin,super_admin
```

## Safety rules

1. Existing business API paths remain unchanged.
2. Browser does not query Neo4j or execute Cypher.
3. Neo4j/Supabase secret keys are never returned in bootstrap.
4. Runtime-source labels come from Step 9 rather than duplicate UI logic.
5. Ontology management writes remain protected by Step 10.
6. Step 11 does not invent multi-org membership; that is Step 12.
7. Existing hybrid/legacy service boundaries remain visible rather than being
   presented as graph-native when they are not.

## Verification

```bash
python -m pytest tests/test_existing_hr_ui_integration_step11.py -v
```

Reference console:

`http://127.0.0.1:8000/ui-integration`

Bootstrap:

`http://127.0.0.1:8000/ui-integration/bootstrap`
