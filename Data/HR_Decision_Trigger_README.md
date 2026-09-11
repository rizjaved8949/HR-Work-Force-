# HR Decision Trigger Engine - CSV data

This folder is configured for CSV-first operation.

## Important
`HR_Decision_Cases.csv` is **generated runtime state/output**. It is not the source of truth for deciding who is critical, and employee IDs/cases are not hardcoded in the Decision Trigger Engine.

On evaluation, the backend reads the existing HR datasets, applies the enabled rules in `HR_Decision_Trigger_Rules.csv`, and synchronizes the resulting active cases into `HR_Decision_Cases.csv`.

## Files
- `HR_Decision_Trigger_Rules.csv` - the five focused trigger definitions/metadata.
- `HR_Decision_Trigger_Config.csv` - CSV-first defaults, dashboard limit, status policy, and safety settings.
- `HR_Decision_Data_Source_Map.csv` - maps each logical dataset to today's CSV file and a future Supabase table name.
- `HR_Decision_Cases.csv` - generated case state used by the dashboard/API/LLM. Do not use this file as trigger input.

## Current source mode
The default environment is:

```text
DECISION_CASE_DATA_SOURCE=csv
DECISION_CASE_STORAGE=csv
DECISION_CASE_DASHBOARD_LIMIT=5
```

`GET /api/v1/decision-cases` refreshes the deterministic rule evaluation by default before returning the dashboard queue. Use `refresh=false` only when the client deliberately wants the last generated state without a fresh evaluation.

## Future Supabase migration
The same trigger engine supports Supabase through the repository abstraction. When the source tables have been migrated and their names are confirmed in `HR_Decision_Data_Source_Map.csv`, switch the environment to:

```text
DECISION_CASE_DATA_SOURCE=supabase
DECISION_CASE_STORAGE=supabase
```

The detection rules, FastAPI routes, and LLM query tool do not need to be rewritten for that storage transition.
