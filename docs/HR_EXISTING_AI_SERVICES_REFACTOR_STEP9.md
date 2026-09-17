# Roadmap Step 9 — Existing AI Services Refactor

## Goal

Move the existing HR AI runtime behind the ontology/knowledge-graph abstraction **without breaking the already-built UI or changing public API/tool contracts**.

The Step 9 runtime is deliberately migration-safe:

```text
Existing UI / Existing FastAPI routes / Existing HR agent
                         |
                         v
                  Step9RuntimeManager
                   /              \
          graph-capable path     compatibility path
                 |                     |
                 v                     v
       FeatureResolutionService   Existing deterministic
                 |                services / CSV inputs
                 v
          SemanticHRService
                 |
                 v
          HR Knowledge Graph
```

## What is graph-native in Step 9

### Employee record/search

The existing `get_employee_record` tool contract is preserved, but in `graph_first` / `graph_only` mode it is produced from `SemanticHRService` rather than direct CSV scans.

Compatibility output still contains the existing top-level structure:

```text
status
match_method
employee
records
  profile
  attendance
  performance
  experience
  skills
  attrition_features
  position
  position_requirements
  position_skill_requirements
  skill_catalog
data_quality
```

The adapter reconstructs current source-style column names only at the compatibility boundary. Core business meaning remains ontology-native internally.

### Attrition prediction

The CatBoost model is **not retrained and not rewritten**.

```text
Employee ID
   -> FeatureResolutionService
   -> exact 14-feature model contract
   -> AttritionCatBoostAdapter
   -> existing CatBoost model
   -> unchanged Yes/No + top reasons response
```

The saved model feature order, 0.50 threshold, numeric missing behavior (`NaN`), categorical missing behavior (`Missing`), and SHAP reason selection remain unchanged.

`Performance_Trend_6M` is passed through as the source/ontology value. Step 9 does not invent a scale conversion.

## Services intentionally kept hybrid

Step 9 does **not** falsely claim every existing deterministic service can become graph-only from the currently approved data.

### Performance

The Step 8 performance feature contract exists, but live Step 7 preflight showed `employee_performance_evidence_monthly` as an existing empty source. The current performance API therefore remains active as the compatibility calculation layer until evidence data is available in the graph.

### Headcount

Core graph facts are available (positions, snapshots, budgets, daily activities, demand drivers, exceptions and rules), but current summary/metric-definition inputs are intentionally derived/not loaded. Existing deterministic headcount calculations are retained to preserve dashboard parity.

### Scenario simulation

The five `Data/Simulation` datasets remain a documented Step 7/Supabase snapshot gap. Step 9 does not fabricate those assumptions as graph facts.

### Successor/replacement

Relevant employee, skill and performance facts exist in the graph, but the existing ranking pipeline is retained until score-by-score parity can be verified. No weights or formulas are changed in Step 9.

## Runtime modes

Configure with environment variables:

```env
STEP9_RUNTIME_MODE=legacy
STEP9_TENANT_ID=ORGANIZATION-001
STEP9_ALLOW_LEGACY_FALLBACK=true
STEP9_VERIFY_GRAPH_CONNECTIVITY=true
```

Modes:

- `legacy`: current runtime only; safest fallback and default behavior.
- `graph_first`: employee retrieval and attrition use the graph when the tenant graph is available; otherwise startup continues on legacy compatibility services when fallback is enabled.
- `graph_only`: graph initialization failure stops startup. Use only after live Step 7 load and parity checks are complete.

## Existing UI remains unchanged

No frontend rewrite is required for Step 9. Existing UI routes still call the same FastAPI handlers. The runtime swaps implementations behind those handlers.

An additive management API is available:

```text
GET /runtime/step9/status
GET /runtime/step9/feature-health
```

`/runtime/step9/status` reports, per service:

- migration state
- active source
- graph capability
- fallback status
- source-gap notes

This is the Step 9 backend hook that an existing admin/management UI can display. The Ontology Studio itself belongs to roadmap Step 10.

## Files added

```text
backend/service_refactor/
  __init__.py
  models.py
  config.py
  employee.py
  attrition.py
  runtime.py
  router.py
  cli.py
```

## Files extended

```text
app.py
backend/attrition_prediction_tool.py
backend/semantic/models.py
backend/semantic/service.py
.env.example
```

## Safety / non-breaking rules

1. Existing public endpoint/tool payloads are preserved.
2. The CatBoost model is reused unchanged.
3. No unconfirmed feature derivation is added.
4. No `Performance_Trend_6M` normalization is invented.
5. Hybrid services remain explicit rather than silently reading incomplete graph data.
6. `graph_first` can fall back to current services when graph startup fails.
7. `graph_only` is opt-in and intentionally strict.

## Local validation

Step 9 unit/compatibility tests:

```bash
python -m pytest tests/test_existing_ai_services_refactor_step9.py -v
```

Roadmap Steps 2–9 regression subset:

```bash
python -m pytest \
  tests/test_ontology_v1.py \
  tests/test_current_data_mapping.py \
  tests/test_graph_model.py \
  tests/test_semantic_graph_service.py \
  tests/test_data_ingestion_step6.py \
  tests/test_current_supabase_graph_step7.py \
  tests/test_feature_resolution_step8.py \
  tests/test_existing_ai_services_refactor_step9.py -v
```

Implementation validation result in the delivery workspace: **68 passed**.

## Live acceptance

Before enabling `graph_only`, live Neo4j must contain the Step 7 tenant data:

```bash
python -m current_graph_load.cli verify --tenant-id ORGANIZATION-001
```

Require:

```text
node_count > 0
relationship_count > 0
```

Then enable graph-first mode and start the API:

```env
STEP9_RUNTIME_MODE=graph_first
```

```bash
set -a
source .env
set +a
export PYTHONPATH="$PWD/backend"
uvicorn app:app --reload
```

Check:

```text
GET http://127.0.0.1:8000/runtime/step9/status
```

For a successfully loaded graph, `employee_record_retrieval` and `attrition_prediction` should report `active_source: knowledge_graph`.
