# HR Ontology v1 — Step 2

This package is the **read-only semantic contract layer** for the HR platform.
It is intentionally isolated from the current AI runtime so adding Step 2 does
not change existing attrition, performance, successor, headcount, scenario, or
decision-case behavior.

## Files

- `hr_ontology_v1.json` — canonical draft ontology metadata.
- `service_contracts/*.json` — current AI-service input contracts mapped to
  ontology concepts. Existing service/model field names are preserved here.
- `models.py` — typed metadata models.
- `registry.py` — read-only loader/query registry.
- `validator.py` — structural and contract-path validation.
- `service.py` — read-only application service.
- `router.py` — optional Ontology Studio API router. **It is not mounted into
  the current app in Step 2.**

## Non-breaking rule

No existing service imports this package in Step 2. No existing API endpoint,
model artifact, CSV repository, Supabase path, feature order, formula, or
missing-value behavior is changed.

## What comes next

Step 3 maps the current CSV/Supabase schema to these ontology concepts. Only
after mapping and parity tests will AI services be migrated to a semantic
resolver/model-adapter path.
