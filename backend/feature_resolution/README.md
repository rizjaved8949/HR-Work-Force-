# Step 8 — Feature Resolution / Missing Feature Layer

This package sits between future AI-service adapters and the Semantic HR Service.
It resolves audited ontology paths into service/model features without allowing
AI services to reach back into CSV or raw Supabase columns.

## Core behavior

- Direct semantic value: use it and retain graph reference provenance.
- Approved derivation: calculate only from a registered rule.
- Approved safe default: use only when an explicit safe-default rule exists.
- Missing critical feature: block the service/model input.
- Missing optional feature: return degraded status.
- Current CatBoost model-native missing behavior: report degraded status while
  preserving the audited `NaN` / `"Missing"` adapter behavior.
- Pending ontology semantics: pass through confirmed current values but emit a
  warning and never invent cross-organization normalization.

## Current audited contracts

- `attrition`: exact 14-feature CatBoost contract and order.
- `performance_recalculation`: 7 audited recalculation inputs (6 required, 1 optional).

Additional service-specific feature selection (successor candidate/position pairs,
scenario subjects, headcount aggregations) is wired during Step 9 because their
current contracts require service context rather than a single employee feature row.

## No runtime cutover in Step 8

`app.py`, the current attrition predictor, performance service, scenario service,
headcount services, and successor service are not modified here. Step 9 performs
that migration with parity tests.
