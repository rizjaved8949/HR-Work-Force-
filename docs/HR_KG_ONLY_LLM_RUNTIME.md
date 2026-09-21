# HR Knowledge-Graph-Only LLM Runtime

## Goal

Keep every existing API/tool/calculation contract working while ensuring the LLM's runtime HR data comes from Supabase Knowledge Graph storage rather than the repository `Data/` CSV directory.

## Read paths

- Employee/profile search: canonical `kg_nodes` / `kg_relationships` via `SemanticHRService`.
- Attrition: canonical KG -> FeatureResolutionService -> unchanged CatBoost model.
- Performance, Headcount, Simulation, Successor/Replacement: unchanged deterministic services, but their required CSV-shaped inputs are generated into an ephemeral cache from a reserved runtime subgraph stored as reserved internal rows in `kg_nodes` (the canonical ontology graph continues to use both `kg_nodes` and `kg_relationships`).
- Decision trigger source facts: same KG-derived compatibility projection. Workflow state may remain in its configured dedicated store.

The repository `Data/` directory is used only by the one-time migration/bootstrap command. It is not read at runtime after `KG_RUNTIME_DATA_SOURCE=knowledge_graph` is enabled.

## Why the compatibility subgraph exists

Several mature deterministic services currently consume tabular files. Rewriting their calculations would risk changing scores/results. The compatibility projection changes only the data-access boundary: source rows are mirrored into the KG once and re-materialized as disposable runtime files. Existing calculation code remains unchanged.

The mirror uses a reserved tenant such as `__KG_RUNTIME__::ORGANIZATION-001`, so canonical tenant node/relationship counts and the 39-entity ontology schema stay unchanged. The compatibility mirror stores dataset and row nodes only; it does not duplicate one relationship per source row.

## Migration / activation

1. Keep `KG_RUNTIME_DATA_SOURCE=legacy` during bootstrap.
2. Run:

```bash
python -m kg_runtime.cli bootstrap --tenant-id ORGANIZATION-001 --source-dir Data
```

3. Verify:

```bash
python -m kg_runtime.cli status --tenant-id ORGANIZATION-001
```

4. Set:

```env
GRAPH_BACKEND=supabase
KG_RUNTIME_DATA_SOURCE=knowledge_graph
KG_LLM_GRAPH_ONLY=true
STEP9_RUNTIME_MODE=graph_only
STEP9_ALLOW_LEGACY_FALLBACK=false
```

5. Start the application. `paths.data_dir()` now resolves to `/tmp/hr-workforce-kg-runtime/...`, generated only from KG data.

## Proof endpoints

- `GET /runtime/step9/status`
- `GET /runtime/kg-source/status`
- `GET /health`

Every HTTP response also includes:

- `X-HR-Data-Source: knowledge_graph`
- `X-HR-Graph-Backend: supabase`
- `X-HR-LLM-Graph-Only: true`

`/chat` and `/chat/stream` additionally expose `runtime_source` in their JSON/SSE completion payloads.

## Multi-organization safety

The existing Step-12 secondary-tenant safety block remains unchanged for services that are not yet request-scoped. This prevents the default organization's compatibility projection from leaking into a secondary tenant. Canonical graph-native employee/attrition routes stay tenant-aware. Do not remove this guard until deterministic services are made request-tenant scoped.
