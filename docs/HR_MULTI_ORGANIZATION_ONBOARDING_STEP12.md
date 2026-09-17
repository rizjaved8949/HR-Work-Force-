# HR Workforce Intelligence — Roadmap Step 12
## Multi-Organization Onboarding

### Purpose

Step 12 turns the single-organization ontology/knowledge-graph implementation into a tenant-safe onboarding workflow for additional organizations without weakening the existing Organization-001 runtime.

The implemented flow is:

```text
Organization registration
        ↓
Tenant membership / access
        ↓
Source snapshot registration
        ↓
Schema profiling
        ↓
Ontology mapping suggestions
        ↓
Human-reviewed MappingPlan
        ↓
Validation + explicit approval
        ↓
Canonical dry run (no graph write)
        ↓
Tenant-scoped two-pass graph load
        ↓
Readiness verification
        ↓
Organization activation
```

The workflow reuses the contracts already built in Steps 2–11. It does not create a second ontology, a second feature model, or organization-specific AI code.

---

## 1. Tenant identity and isolation

Each organization has one stable `tenant_id`, for example:

```text
ORGANIZATION-001
ACME-HR-001
PARTNER-B-001
```

Graph identifiers were already tenant-scoped in Step 4. Step 12 now makes that isolation operational during onboarding:

- organization registry entries are keyed by tenant;
- staged source snapshots are stored under a tenant namespace;
- mapping plans are stored under a tenant namespace;
- every MappingPlan must have the same tenant as the organization being loaded;
- canonical graph IDs include the tenant;
- graph repository reads/writes use the tenant;
- cross-tenant relationships remain rejected by the graph validator.

The same employee business ID may therefore exist in two organizations without graph-ID collision.

---

## 2. Existing organization remains non-breaking

At application startup the existing Step-9 tenant is bootstrapped into the Step-12 registry if it does not already exist.

Default environment:

```env
STEP9_TENANT_ID=ORGANIZATION-001
STEP12_DEFAULT_ORGANIZATION_NAME=Current Organization
STEP12_DEFAULT_TENANT_OPEN_ACCESS=true
```

This preserves the current application while secondary organizations use the new explicit onboarding lifecycle.

`STEP12_DEFAULT_TENANT_OPEN_ACCESS=true` is a migration compatibility setting for the already-running default organization. Step 13 should normally harden membership policy before production rollout.

---

## 3. Organization lifecycle

Secondary organizations move through explicit states:

```text
draft
  ↓
mapping_review
  ↓
ready_to_load
  ↓
loading
  ↓
active
```

An organization can also be `suspended` or `failed`.

Activation is blocked until:

- datasets have approved mapping plans;
- datasets have completed a successful graph load;
- tenant-scoped graph nodes exist.

A graph with no relationships is allowed for a very small/minimal tenant, but readiness returns a warning because semantic navigation will be limited.

---

## 4. Supported source onboarding

The Step-6 ingestion adapters remain authoritative.

The Step-12 service supports:

- API/database rows through `RegisterRecordsDatasetRequest` / `RecordsSource`;
- CSV through the CLI file importer;
- JSON array files through the CLI file importer;
- XLSX/XLSM through the CLI file importer.

The local workspace stores an immutable normalized row snapshot so profiling, mapping validation, dry-run and graph load all operate on the same data snapshot.

Step 12 does **not** store external database passwords, Supabase keys, Neo4j passwords, API tokens or other connector credentials in the organization registry.

---

## 5. Mapping policy

Unknown-organization mappings stay human-governed:

```text
Profiler
  ↓
OntologyMappingSuggester
  ↓
recommendations only
  ↓
human submits MappingPlan
  ↓
validator
  ↓
explicit approval
```

Even an exact source-column match is not auto-approved.

The plan is bound to all of the following:

- tenant ID;
- source system;
- source object;
- source format;
- ontology version;
- mapping version.

Pending ontology semantics still require an explicit semantic override reason, exactly as in Step 6.

---

## 6. Graph loading

Step 12 aggregates approved organization datasets before writing.

```text
all approved canonical entities
        ↓
dedupe
        ↓
all approved canonical relationships
        ↓
dedupe
        ↓
validate endpoints within tenant
        ↓
write ALL nodes
        ↓
write ALL relationships
```

This preserves the Step-7 two-pass rule and lets relationships resolve across different source datasets loaded in the same organization batch.

A canonical `Organization` root node is also produced from organization metadata using only values supplied during onboarding. No organization attributes are invented.

Neo4j `MERGE`/deterministic graph IDs keep re-runs idempotent.

---

## 7. Existing UI and organization switching

The Step-11 browser client now supports an optional organization resolver:

```javascript
const client = new HRWorkforceClient({
  getAccessToken: () => auth.accessToken,
  getOrganizationId: () => selectedOrganizationId,
});
```

When present, the client sends:

```http
X-Organization-ID: ACME-HR-001
```

Step-12 middleware validates that organization before the request reaches graph-native services and places the tenant in a request-scoped ContextVar.

The Step-9 graph employee and attrition adapters now resolve their tenant from this validated request context, falling back to `STEP9_TENANT_ID` when no organization header is supplied.

---

## 8. Important safety boundary for hybrid services

Not every Step-9 service is fully graph-native yet.

For the current default tenant, existing compatibility services remain available exactly as before.

For a secondary tenant, Step 12 allows the graph-native paths:

- employee search/profile;
- attrition pipeline/model input through the graph feature resolver.

It intentionally blocks secondary-tenant access to routes that still rely on the original organization’s CSV/hybrid datasets, including current performance, headcount, replacement, scenario, decision-case, attrition-dashboard and chat surfaces.

The response code is `409` with:

```json
{
  "code": "service_not_multi_tenant_safe"
}
```

Blocking is intentional. Returning Organization-001 legacy data under another tenant would be a cross-tenant data leak.

Step 13 can cut over/harden additional services only after their tenant-safe data contracts are production-ready.

---

## 9. Admin/reference UI

Open:

```text
http://127.0.0.1:8000/organization-onboarding
```

The reference onboarding console supports:

- organization registry;
- organization creation;
- JSON-row dataset registration;
- profiling;
- mapping suggestions;
- draft mapping-plan submission;
- validation;
- approval;
- dry-run;
- graph load;
- activation/readiness.

The existing UI integration console also exposes an Organizations navigation item for admin users.

---

## 10. Main APIs

```text
GET  /organization-onboarding/api/bootstrap
GET  /organization-onboarding/api/organizations
POST /organization-onboarding/api/organizations
GET  /organization-onboarding/api/organizations/{tenant_id}
POST /organization-onboarding/api/organizations/{tenant_id}/members

POST /organization-onboarding/api/organizations/{tenant_id}/datasets/records
GET  /organization-onboarding/api/organizations/{tenant_id}/datasets/{dataset_id}/profile
GET  /organization-onboarding/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-suggestions
POST /organization-onboarding/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-plan
GET  /organization-onboarding/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-plan/validate
POST /organization-onboarding/api/organizations/{tenant_id}/datasets/{dataset_id}/mapping-plan/approve
GET  /organization-onboarding/api/organizations/{tenant_id}/datasets/{dataset_id}/dry-run

POST /organization-onboarding/api/organizations/{tenant_id}/load
GET  /organization-onboarding/api/organizations/{tenant_id}/readiness
POST /organization-onboarding/api/organizations/{tenant_id}/activate
POST /organization-onboarding/api/organizations/{tenant_id}/suspend
```

---

## 11. Linux CLI examples

List organizations:

```bash
python -m multi_org.cli list
```

Create an organization:

```bash
python -m multi_org.cli create \
  --tenant-id ACME-HR-001 \
  --name "Acme Ltd" \
  --country Pakistan \
  --currency PKR
```

Register a file:

```bash
python -m multi_org.cli register-file \
  --tenant-id ACME-HR-001 \
  --path /path/to/employees.csv
```

Profile it after reading the returned `dataset_id`:

```bash
python -m multi_org.cli profile \
  --tenant-id ACME-HR-001 \
  --dataset-id ds-xxxxxxxxxxxxxxxx
```

Readiness:

```bash
python -m multi_org.cli readiness \
  --tenant-id ACME-HR-001
```

Mapping-plan creation/approval is intentionally handled through the reviewed API/UI workflow rather than auto-generated by the CLI.

---

## 12. Workspace persistence

Step 12 uses:

```text
backend/multi_org/workspace/organizations.json
backend/multi_org/workspace/sources/<tenant>/<dataset>.json
backend/multi_org/workspace/plans/<tenant>/<plan>.json
```

This is a safe development/onboarding control-plane store. It is not presented as the final production persistence layer.

Step 13 will cover production persistence, migration/version controls, deployment validation, observability, backup/recovery and security hardening.
