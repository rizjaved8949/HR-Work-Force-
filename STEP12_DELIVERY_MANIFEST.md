# Step 12 Delivery Manifest

## Roadmap item

**12. Multi-Organization Onboarding**

## New package

`backend/multi_org/`

- `models.py` — organization/dataset/readiness/load contracts
- `registry.py` — atomic organization registry
- `source_store.py` — tenant-scoped staged source snapshots
- `plan_store.py` — tenant-namespaced MappingPlan store
- `access.py` — organization creation/membership/admin policy
- `context.py` — request-scoped tenant ContextVar
- `service.py` — onboarding/profile/map/approve/load/activate orchestration
- `middleware.py` — validated `X-Organization-ID` selection and hybrid-route safety gate
- `router.py` — onboarding management API + reference UI
- `cli.py` — Linux-friendly organization/file/profile/readiness commands
- `static/` — reference onboarding console
- `workspace/` — local Step-12 metadata/staging store

## Existing files intentionally changed

- `app.py` — mounts Step-12 service/router and tenant middleware
- `backend/service_refactor/employee.py` — graph employee service accepts request tenant resolver
- `backend/service_refactor/attrition.py` — graph attrition service accepts request tenant resolver
- `backend/service_refactor/runtime.py` — graph-native adapters use Step-12 tenant context with Step-9 default fallback
- `backend/ui_integration/service.py` — organization navigation + selected-tenant metadata
- `backend/ui_integration/router.py` — selected tenant returned in UI integration bootstrap/runtime
- `backend/ui_integration/static/hr-ui-client.js` — optional organization header support
- `backend/ui_integration/static/console.js` — reuses selected organization from local UI state
- `backend/ui_integration/static/index.html` — Organizations navigation link
- `.env.example` — non-secret Step-12 policy settings

## Tests

- `tests/test_multi_organization_onboarding_step12.py` — 12 dedicated tests
- selected Steps 2–12 regression — 100 tests

## Not changed

- HR Ontology v1 semantic definitions
- CatBoost model
- CatBoost exact feature order
- attrition threshold
- existing deterministic performance/headcount/simulation/successor formulas
- current Organization-001 graph IDs/data
- existing source credentials

## Deliberate boundary

Secondary organizations can use graph-native employee and attrition paths after activation. Existing legacy/hybrid services are blocked for secondary tenants until their source contracts become tenant-safe, preventing accidental cross-organization data exposure.
