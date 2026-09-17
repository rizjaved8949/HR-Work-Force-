# Step 11 Frontend Handoff — Existing Main HR UI

Use this file when wiring the already-built frontend to the Step-11 backend.

## 1. Configure one API base URL

Vite example:

```env
VITE_API_URL=http://127.0.0.1:8000
```

Next example:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

## 2. Load the Step-11 bootstrap after session restore

```js
import { HRWorkforceClient } from `${API_URL}/ui-integration/assets/hr-ui-client.js`;

const api = new HRWorkforceClient({
  baseUrl: API_URL,
  getAccessToken: () => session?.access_token,
});

const ui = await api.bootstrap();
```

Use `ui.navigation` to decide which modules are visible and use
`ui.runtime_services` for source/status badges. Do not copy those migration
rules into frontend code.

## 3. Map route keys to the existing frontend pages

Step 11 intentionally returns logical route keys instead of guessing your
frontend URLs:

```js
const routeMap = {
  dashboard: "/",
  employees: "/employees",
  attrition: "/attrition",
  performance: "/performance",
  headcount: "/headcount",
  scenarios: "/scenario-simulator",
  decision_cases: "/decision-cases",
  assistant: "/assistant",
  ontology_studio: `${API_URL}/ontology-studio`,
};
```

Change only the routeMap values to match the already-built UI. Backend route
keys stay stable.

## 4. Existing business calls remain unchanged

Examples:

```js
await api.searchEmployee({ employee_id: "EMP001" });
await api.attrition({ employee_id: "EMP001" });
await api.headcount({ question: "Show current headcount by department" });
```

The same endpoints now benefit from Step-9 graph-first adapters where approved.

## 5. Auth

The client accepts `getAccessToken`. It does not assume localStorage/session
storage or any framework-specific auth implementation.

If `AUTH_ENABLED=true`, return the current Supabase `access_token` from the
existing session layer. If authentication is disabled locally, no bearer header
is sent.

## 6. Tenant

Display `ui.tenant_id` if needed, but do not add a fake organization switcher
in Step 11. Multi-organization membership and tenant switching are Step 12.

## 7. Admin management navigation

`ontology_studio` appears in `ui.navigation` only for configured admin roles
when authentication is enabled. Backend Step-10 authorization still protects
write operations even if a user manually enters the URL.

## 8. Runtime source badge example

```js
const sources = Object.fromEntries(
  ui.runtime_services.map(item => [item.service, item])
);

const attritionSource = sources.attrition_prediction.active_source;
// "knowledge_graph" in graph-first mode
```

Do not claim graph-native behavior for hybrid services. Render the exact state
returned by the backend.
