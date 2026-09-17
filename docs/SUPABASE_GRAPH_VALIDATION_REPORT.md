# Supabase Graph Portability Validation

Validation performed against the Step-13 project baseline after replacing hard-coded graph construction paths with the repository factory.

## Automated results

- Existing roadmap regression (Steps 2-13): 114 tests preserved.
- New Supabase graph / UI portability tests: 5 passed.
- Combined tested total: 119 passed.
- Python compile: required before packaging.

## New coverage

1. Tenant-scoped Supabase graph nodes and relationships.
2. Relationship traversal through `GraphRepository`.
3. Idempotent node upserts.
4. SQL DDL includes tenant PKs, endpoint FKs, JSONB indexes, and RLS.
5. Ontology graph includes three relationship colour families, arrows, and relationship labels.
6. Standalone management portal mounts only Ontology Studio and Organization Onboarding.

## Runtime acceptance still required on the user's Supabase project

The automated environment does not have the user's live Supabase credentials. Final acceptance requires running the SQL migration, rebuilding the projection from the live Supabase HR tables, and verifying non-zero node/relationship counts.
