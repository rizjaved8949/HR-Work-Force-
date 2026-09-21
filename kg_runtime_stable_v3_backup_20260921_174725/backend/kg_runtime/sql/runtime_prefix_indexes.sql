-- Optional but recommended for KG runtime compatibility mirror prefix lookups.
-- Safe: indexes only, no data mutation.
create index if not exists kg_nodes_tenant_graph_id_pattern_idx
  on public.kg_nodes (tenant_id, graph_id text_pattern_ops);

create index if not exists kg_relationships_tenant_graph_id_pattern_idx
  on public.kg_relationships (tenant_id, graph_id text_pattern_ops);
