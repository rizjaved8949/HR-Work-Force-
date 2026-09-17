# Step 10 — Ontology Management UI / Ontology Studio

## Purpose

Step 10 turns the ontology, mapping and graph metadata produced in Steps 2–9
into a governed management surface. It is deliberately separate from the
employee-facing HR UI; Step 11 will integrate the required screens into the
existing HR application.

## Architecture

```text
Ontology Studio UI
      |
      +--> /ontology/*                 (Step-2 read-only metadata)
      +--> /mapping/*                  (Step-3 read-only mapping/coverage)
      +--> /ontology-studio/api/*      (Step-10 management plane)
                    |
                    +--> OntologyRegistry
                    +--> MappingRegistry
                    +--> Neo4j graph health/counts
                    +--> staged review store
```

The management plane never allows the browser to write Cypher and never lets a
review silently rewrite the active ontology JSON or the approved Step-3
mapping. Approve/reject means a governance decision has been recorded.

## Management screens

The standalone reference UI is served at:

`GET /ontology-studio`

It contains:

1. Overview — ontology version, entity/relationship counts, graph health,
   semantic attention items and review counts.
2. Ontology Graph — schema-level visualization of the 39 ontology entities and
   65 relationship types.
3. Entities & Properties — searchable entity/property catalog including
   semantic status and source-mapping counts.
4. Source Mappings — searchable dataset list and per-column classification,
   ontology path, transform/reason.
5. AI Service Coverage — current service-contract coverage produced by the
   verified Step-3 mapping service.
6. Mapping Reviews — create, approve or reject staged mapping proposals.
7. Change Requests — create, approve or reject staged ontology evolution
   requests.

## APIs

### Dashboard and inspection

- `GET /ontology-studio/api/dashboard?tenant_id=ORGANIZATION-001`
- `GET /ontology-studio/api/schema-graph`
- `GET /ontology-studio/api/entities`
- `GET /ontology-studio/api/datasets`
- `GET /ontology-studio/api/datasets/{source_file}`
- `GET /ontology-studio/api/attention`
- `GET /ontology-studio/api/service-contracts`
- `GET /ontology-studio/api/governance-snapshot`

### Mapping review workflow

- `GET /ontology-studio/api/mapping-reviews`
- `POST /ontology-studio/api/mapping-reviews`
- `PATCH /ontology-studio/api/mapping-reviews/{review_id}`

A proposed ontology path is rejected if it is not present in the active
ontology registry. Approval sets `applied_to_active_mapping=false`; this is
intentional.

### Ontology change workflow

- `GET /ontology-studio/api/change-requests`
- `POST /ontology-studio/api/change-requests`
- `PATCH /ontology-studio/api/change-requests/{request_id}`

Approval sets `applied_to_active_ontology=false`. Controlled application,
versioning, rollback and production release belong to the later production
boundary.

## Existing metadata APIs mounted in Step 10

The previously isolated read APIs are now intentionally mounted:

- `/ontology/summary`
- `/ontology/modules`
- `/ontology/entities`
- `/ontology/entities/{entity_name}`
- `/ontology/relationships`
- `/ontology/service-contracts/{service_name}`
- `/ontology/validation`
- `/mapping/summary`
- `/mapping/validation`
- `/mapping/service-coverage`
- `/mapping/supabase-summary`

## Authentication / authorization

The existing global Supabase authentication middleware still owns request
authentication. Step-10 mutating actions add an admin-role check when
`AUTH_ENABLED=true`.

Default allowed roles:

`admin,owner,hr_admin,super_admin`

Configure with:

`ONTOLOGY_STUDIO_ADMIN_ROLES=admin,owner,hr_admin,super_admin`

When `AUTH_ENABLED=false`, local development remains usable.

## Review persistence

The initial review workflow uses:

`backend/ontology_studio/workspace/studio_reviews.json`

This stores governance metadata only. It is not the active ontology. The store
can later move to Supabase without changing the UI/API contract.

## Safety decisions

- No automatic mapping approval from fuzzy/AI suggestions.
- Unknown ontology paths are rejected.
- `PerformanceRecord.performanceTrend6M` remains unresolved/pending; the UI
  surfaces it instead of inventing a semantic conversion.
- Reviews never mutate `hr_ontology_v1.json` or
  `current_data_mappings.json`.
- UI visualizes ontology schema, not tens of thousands of employee graph nodes.
- Frontend never executes Cypher directly.

## Step 11 boundary

Step 10 provides the complete management APIs and reference Ontology Studio.
Step 11 should integrate these routes into the already-built HR application UI
(nav, permissions, tenant context and shared component system) without
re-implementing ontology logic in the browser.
