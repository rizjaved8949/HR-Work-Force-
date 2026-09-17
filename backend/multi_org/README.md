# Step 12 — Multi-Organization Onboarding

This package adds a tenant-safe onboarding control plane on top of Steps 2–11.

Flow:

`Organization -> Source Snapshot -> Profile -> Mapping Suggestions -> Human Mapping Plan -> Validation -> Approval -> Canonical Dry Run -> Tenant-Scoped Graph Load -> Activation`

Important rules:

- mappings are never auto-approved;
- every mapping plan is bound to one tenant and one immutable source snapshot;
- graph IDs are tenant-scoped;
- repository reads/writes remain tenant-scoped;
- cross-tenant relationships are rejected by the graph validator;
- the onboarding registry never stores connector passwords/API keys;
- secondary organizations cannot call legacy/hybrid endpoints that would risk returning the default organization's CSV-backed data;
- graph-native employee search and attrition can use `X-Organization-ID` after the organization is active.

The local JSON workspace is Step-12 metadata/staging persistence only. Step 13 moves operational persistence/secrets to production-grade stores and hardens deployment/versioning.
