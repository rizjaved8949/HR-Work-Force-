# Step 9 Validation Report

## Scope

Roadmap Step 9: Existing AI Services Refactor with existing UI/API compatibility.

## Automated validation

### Step 9 tests

- 8 tests passed.
- Graph employee record adapter returns the legacy UI/tool shape.
- Exact-name search contract is preserved.
- Graph-resolved attrition features produce the same CatBoost scoring result as the legacy feature extraction for the same values.
- Saved model feature order remains exactly 14 features.
- Graph-first runtime swaps only compatible public tools.
- Legacy mode remains non-breaking.
- Management status endpoint is exposed.
- Known source gaps are explicitly reported instead of guessed.

### Steps 2–9 combined regression

Result: **68 passed**.

### Compile validation

The following compile successfully:

- `app.py`
- `backend/attrition_prediction_tool.py`
- `backend/semantic/models.py`
- `backend/semantic/service.py`
- all `backend/service_refactor/*.py`

## Environment limitation of delivery workspace

A broader legacy suite could not be collected completely in the delivery container because that container does not have the project's LangChain dependency installed. One pre-existing performance test file also contains an unrelated malformed first line in the supplied project snapshot. These are not Step 9 failures.

The user's Linux virtual environment already showed the required project dependencies while running the 60-test Steps 2–8 suite, so the full app smoke/regression suite should be run there after applying the patch.

## Live validation still required on user machine

Step 9 graph-first acceptance depends on Step 7 live graph data. Verify:

```bash
python -m current_graph_load.cli verify --tenant-id ORGANIZATION-001
```

Then start with `STEP9_RUNTIME_MODE=graph_first` and confirm:

```text
/runtime/step9/status
```

shows graph availability and knowledge-graph source for employee retrieval and attrition.
