# HR Platform — Step 8 Feature Resolution / Missing Feature Layer

## Purpose

Step 8 converts ontology/graph facts into the exact feature contracts consumed by
AI/ML services. It is the policy boundary for direct values, approved derivations,
approved defaults, optional missing data, critical missing data, and existing
model-native missing behavior.

The runtime target is:

```text
AI Service (Step 9)
      ↓
Feature Resolution Service
      ↓
SemanticHRService
      ↓
Knowledge Graph
```

Step 8 does **not** refactor the existing AI services. That remains Step 9.

## Implemented package

```text
backend/feature_resolution/
├── __init__.py
├── models.py
├── providers.py
├── registry.py
├── derivations.py
├── resolver.py
├── adapters.py
├── service.py
├── router.py
├── cli.py
├── README.md
└── rules/
    └── feature_resolution_rules_v1.json
```

## Resolution policy

For every feature the resolver reports one of:

- `direct` — value came directly from a canonical semantic record.
- `derived` — value came from an explicitly approved derivation rule.
- `defaulted` — value came from an explicitly approved safe-default rule.
- `missing` — no valid value was established.

The overall report status is:

- `ready` — all features resolved and no semantic warnings.
- `ready_with_warnings` — all features resolved but an ontology semantic warning remains.
- `degraded` — only optional/model-native missing features remain.
- `blocked` — at least one critical feature is missing.
- `subject_not_found` — the requested employee/subject does not exist.

No arbitrary imputation is performed.

## Approved derivation in Step 8

`Employment.tenureMonths` is the only approved derivation currently required by
an audited model feature contract. HR Ontology v1 already marks it as derived from
`Employment.hireDate` and a reference/current date.

Resolution order:

1. Use `Employment.tenureMonths` directly when available.
2. Otherwise use `Employment.hireDate` and `Employment.dataAsOfDate`.
3. If no semantic data-as-of date exists, use an explicitly supplied request `as_of_date`.
4. Never silently use wall-clock time when neither reference is available.

`ExperienceProfile.monthsSinceLastPromotion` is **not** derived because the current
ontology does not mark it as derived. Step 8 does not invent a formula from career history.

## Attrition contract

The existing saved CatBoost feature names and order remain unchanged:

1. `Tenure_Months`
2. `Monthly_Salary_PKR`
3. `Salary_vs_Market_pct`
4. `Last_Increment_pct`
5. `Months_Since_Last_Promotion`
6. `KPI_Achievement_pct`
7. `Performance_Trend_6M`
8. `Overtime_Hours_Last_30D`
9. `Engagement_Score`
10. `Job_Satisfaction_Score`
11. `Work_Life_Balance_Score`
12. `Manager_Relationship_Score`
13. `Career_Growth_Score`
14. `Pay_Concern_Raised_Last_6M`

The adapter converts semantic boolean pay concern to `Yes` / `No` and preserves
the current audited model-native missing behavior:

- numeric missing → `NaN`
- categorical missing → `"Missing"`

The feature report still shows those values as unresolved/degraded; the adapter does
not pretend a semantic value exists.

`PerformanceRecord.performanceTrend6M` remains `pending_confirmation` in the
ontology. Its current graph value can pass through to the current model, but Step 8
will not create a cross-organization scale conversion or derivation.

## Performance recalculation contract

Step 8 also materializes the 7 audited recalculation inputs from the existing
performance service contract:

- 6 required inputs → missing is `critical` / blocked.
- `Evidence_Quality_Score` → optional / degraded when absent.

A generic `MappingValueProvider` accepts ontology paths (not raw database columns)
so Step 9 can bind performance-specific graph queries without changing missing policy.

## Safe defaults

`feature_resolution_rules_v1.json` contains an explicit `safe_defaults` registry.
It is intentionally empty today because no safe business defaults were confirmed in
the audited contracts. This prevents silent zero/default imputation.

## Linux verification

From project root:

```bash
source .venv/bin/activate
export PYTHONPATH="$PWD/backend"

python -m pytest tests/test_feature_resolution_step8.py -v
```

Expected:

```text
10 passed
```

Combined Steps 2–8:

```bash
python -m pytest \
  tests/test_ontology_v1.py \
  tests/test_current_data_mapping.py \
  tests/test_graph_model.py \
  tests/test_semantic_graph_service.py \
  tests/test_data_ingestion_step6.py \
  tests/test_current_supabase_graph_step7.py \
  tests/test_feature_resolution_step8.py -v
```

Expected:

```text
60 passed
```

## Live graph verification

Step 7 must have actually written nodes/relationships first.

```bash
set -a
source .env
set +a
export PYTHONPATH="$PWD/backend"

python -m feature_resolution.cli health --tenant-id ORGANIZATION-001
```

Then obtain a real employee ID from the graph and run:

```bash
python -m feature_resolution.cli attrition \
  --tenant-id ORGANIZATION-001 \
  --employee-id EMPLOYEE_ID
```

To see the exact model adapter payload:

```bash
python -m feature_resolution.cli attrition-model-input \
  --tenant-id ORGANIZATION-001 \
  --employee-id EMPLOYEE_ID
```

Strict mode is available when a caller wants every required attrition feature to
block instead of preserving the current CatBoost native-missing behavior:

```bash
python -m feature_resolution.cli attrition \
  --tenant-id ORGANIZATION-001 \
  --employee-id EMPLOYEE_ID \
  --strict-missing
```

## Step boundary

Step 8 is complete when the resolver and model adapters are validated. Existing AI
services still use their old runtime paths until Step 9. This keeps migration and
behavior-parity work isolated.
