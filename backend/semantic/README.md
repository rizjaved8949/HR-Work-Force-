# Semantic / Graph Service Layer — Step 5

This package is the storage-neutral HR read layer between future AI-service
adapters and the Knowledge Graph.

## Scope

Implemented in Step 5:

- tenant-scoped semantic entity lookup
- employee-centered semantic context
- current assignment -> department / position traversal
- manager and reporting-chain traversal
- compensation, performance, attendance, engagement and experience reads
- skill assessment -> canonical skill resolution
- histories for employment, assignments, performance, learning and career moves
- storage-neutral repository queries for in-memory and Neo4j repositories
- read-only FastAPI router (not mounted automatically)
- non-destructive Neo4j connectivity/health verifier

Not implemented in Step 5:

- source-data ingestion (Step 6/7)
- model feature resolution (Step 8)
- refactoring current AI services to use this layer (Step 9)
- frontend integration (Step 10/11)

## Important temporal rule

The service never treats ingestion/update time as business recency. When more
than one record exists, "latest" is selected only from a confirmed temporal
ontology property or `kg_valid_from`. If neither exists, the service raises a
`SemanticDataIntegrityError` instead of guessing.

## Environment

The Neo4j implementation uses:

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE` (optional; defaults to `neo4j`)

## Local verification

From repository root (CMD):

```cmd
set "PYTHONPATH=%CD%\backend"
python -m pytest tests\test_semantic_graph_service.py -v
python -m semantic.verify_neo4j
```

The second command is non-destructive. With an empty Step-4 graph, zero nodes
and relationships are expected until Step 7 ingests current HR data.
