-- KG runtime v3 indexes for timeout-safe compatibility reads.
-- Safe: indexes/statistics only; no application data is modified.

create index if not exists kg_nodes_tenant_graph_id_pattern_idx
  on public.kg_nodes (tenant_id, graph_id text_pattern_ops);

create index if not exists kg_relationships_tenant_graph_id_pattern_idx
  on public.kg_relationships (tenant_id, graph_id text_pattern_ops);

-- Runtime rows use a reserved entity type. This partial index keeps the hot
-- compatibility path small while leaving canonical ontology rows untouched.
create index if not exists kg_nodes_runtime_row_prefix_idx
  on public.kg_nodes (tenant_id, graph_id text_pattern_ops)
  where entity_type = '__RuntimeRow';

-- Refresh planner statistics after the 100k+ compatibility mirror load so the
-- new prefix indexes are considered immediately.
analyze public.kg_nodes;
analyze public.kg_relationships;
