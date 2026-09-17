# Supabase Knowledge Graph + Separate Management Portal

## Goal

Replace the separately hosted Neo4j runtime with the existing Supabase/PostgreSQL project while preserving the HR ontology, deterministic graph IDs, relationships, tenant isolation, semantic service, feature resolution, and AI-service contracts.

The existing HR tables remain the authoritative source data. Two additional Postgres tables hold the ontology-shaped graph projection:

- `kg_nodes`
- `kg_relationships`

The two technical management UIs are deployed together as a separate management service:

- `/ontology-studio`
- `/organization-onboarding`

The existing business HR frontend can stay on Vercel and link to the management service URL.

## Target architecture

```text
Vercel HR Frontend
       |
       | normal HR APIs
       v
Render HR Backend ----------------------+
                                        |
Separate Render Management Portal       |
  /ontology-studio                      |
  /organization-onboarding              |
       |                                |
       +-------------+------------------+
                     v
               Supabase/Postgres
              /                 \
     Existing HR tables       kg_nodes
       source of truth        kg_relationships
                     \         /
                      Ontology Graph Projection
```

No Neo4j container, Bolt port, Docker volume, or Neo4j persistent disk is required when `GRAPH_BACKEND=supabase`.

## 1. Install the graph tables

Open Supabase -> SQL Editor and execute:

`backend/graph/sql/supabase_graph_schema.sql`

The migration creates composite tenant-scoped primary keys, endpoint foreign keys, JSONB properties/provenance, indexes, and RLS. It intentionally creates no browser/anon policies; the backend service-role client owns graph access.

Verify:

```bash
export PYTHONPATH="$PWD/backend"
python -m graph.install_schema
```

Expected:

```text
Supabase graph schema: OK
```

## 2. Select Supabase as the graph backend

`.env` / Render environment:

```env
GRAPH_BACKEND=supabase
SUPABASE_GRAPH_NODES_TABLE=kg_nodes
SUPABASE_GRAPH_RELATIONSHIPS_TABLE=kg_relationships
```

Keep the existing backend-only values:

```env
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
```

Never expose `SUPABASE_SECRET_KEY` to Vercel/browser code.

## 3. Rebuild graph projection from the HR tables

No Neo4j export is required because the authoritative HR data already lives in Supabase.

```bash
python -m current_graph_load.cli preflight --tenant-id ORGANIZATION-001
```

Proceed only when `error_count` is `0`.

```bash
python -m current_graph_load.cli load \
  --tenant-id ORGANIZATION-001 \
  --confirm-write LOAD-CURRENT-SUPABASE-INTO-GRAPH
```

Then:

```bash
python -m graph.verify_backend --tenant-id ORGANIZATION-001
python -m current_graph_load.cli verify --tenant-id ORGANIZATION-001
```

Both node and relationship counts must be greater than zero.

The same Step-12 onboarding writer uses the configured repository, so future organizations also write to `kg_nodes` and `kg_relationships` without Neo4j-specific code.

## 4. Repository portability

`backend/graph/factory.py` selects the repository.

```text
GRAPH_BACKEND=supabase -> SupabaseGraphRepository
GRAPH_BACKEND=neo4j   -> Neo4jGraphRepository
```

The semantic and ingestion layers continue to depend only on `GraphRepository`.

## 5. Ontology Studio graph readability

The ontology diagram remains a schema-level graph (39 entity types / 65 ontology relationships), not a rendering of tens of thousands of employee records.

Relationships use three high-contrast families:

- Cyan: organization / structure / reporting
- Violet: people / talent / performance
- Amber: planning / governance / risk

Every edge has an arrow. Relationship names appear when an edge is hovered/selected and when an entity is selected. Selecting an entity highlights its connected nodes/edges and the right-hand panel lists inbound and outbound relationships.

This keeps the diagram readable while the live graph projection can contain tens of thousands of tenant-scoped nodes.

## 6. Separate management deployment

Run locally:

```bash
uvicorn management_portal:app --reload
```

Open:

- `http://127.0.0.1:8000/ontology-studio`
- `http://127.0.0.1:8000/organization-onboarding`

The standalone app does not mount the rest of the HR dashboards.

For Render use `deploy/render-management.yaml` or create a Python Web Service with:

```text
Build: pip install -r requirements-management.txt
Start: uvicorn management_portal:app --host 0.0.0.0 --port $PORT
```

Required environment variables:

```env
GRAPH_BACKEND=supabase
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
SUPABASE_PUBLISHABLE_KEY=...
SUPABASE_GRAPH_NODES_TABLE=kg_nodes
SUPABASE_GRAPH_RELATIONSHIPS_TABLE=kg_relationships
STEP9_TENANT_ID=ORGANIZATION-001
MANAGEMENT_ALLOWED_ORIGINS=https://YOUR-HR-FRONTEND.vercel.app
```

Then add one external link in the existing Vercel HR frontend, for example:

```text
Ontology & Data Management -> https://YOUR-MANAGEMENT-SERVICE.onrender.com/ontology-studio
```

The onboarding page links back to Ontology Studio; no third management UI is mounted in this standalone service.

## 7. Neo4j rollback

Neo4j support is retained only as a reversible fallback. To use it again:

```env
GRAPH_BACKEND=neo4j
NEO4J_URI=...
NEO4J_USERNAME=...
NEO4J_PASSWORD=...
```

The old volume backup/restore scripts are irrelevant to normal Supabase-graph deployment and can be kept only for rollback/testing.

## 8. Acceptance checklist

- Supabase SQL migration runs successfully.
- `python -m graph.install_schema` reports OK.
- Step-7 preflight has zero errors.
- Step-7 load completes idempotently.
- `graph.verify_backend` reports `SupabaseGraphRepository`.
- Node count > 0.
- Relationship count > 0.
- Employee search + attrition graph paths still work.
- Ontology Studio graph shows cyan/violet/amber arrows.
- Selecting an entity displays inbound/outbound relationships.
- Organization onboarding writes tenant-scoped graph records.
- Separate management portal starts without Neo4j environment variables.
