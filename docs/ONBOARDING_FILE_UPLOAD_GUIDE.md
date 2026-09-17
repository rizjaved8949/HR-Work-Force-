# Multi-Organization Onboarding — Browser File Upload

This patch adds a real browser file selector to `/organization-onboarding`.

Supported files:
- CSV
- JSON array
- XLSX
- XLSM

Flow:
1. Select/open organization.
2. Upload a file in **Dataset Upload**.
3. Backend registers an immutable tenant-scoped staged dataset.
4. Select the dataset in **Dataset Workflow**.
5. Profile → Suggest mappings → Save draft mapping plan → Validate → Approve → Dry run → Load organization graph → Activate.

Implementation notes:
- No `python-multipart` dependency is required.
- The browser sends file bytes as base64 JSON to the management API.
- Backend writes only a short-lived temp file to reuse existing audited CSV/JSON/XLSX ingestion adapters.
- The temp file is deleted immediately after staging.
- The persistent onboarding snapshot remains tenant-scoped JSON under the existing `OrganizationSourceStore`.
- Default upload limit is 20 MB and can be changed with `MULTI_ORG_MAX_UPLOAD_MB`.
