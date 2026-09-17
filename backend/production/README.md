# Step 13 — Testing, Versioning & Production

This package is additive. It does not alter HR calculations or model behavior.

It provides:

- deterministic release/version metadata;
- liveness and readiness checks;
- a production release gate;
- request correlation IDs and security headers;
- explicit production policy checks (auth, CORS, tenant access, graph runtime);
- CLI checks suitable for CI/CD.

Warnings are visible but do not masquerade as errors. In particular, the known
`PerformanceRecord.performanceTrend6M` semantic warning remains visible and is
not automatically normalized.
