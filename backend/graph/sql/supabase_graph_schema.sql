-- HR Knowledge Graph projection for Supabase/PostgreSQL
-- Existing HR tables remain the source of truth. These two tables are the
-- ontology-shaped node/relationship projection consumed by GraphRepository.

create table if not exists public.kg_nodes (
    tenant_id text not null,
    graph_id text not null,
    entity_type text not null,
    ontology_version text not null,
    properties jsonb not null default '{}'::jsonb,
    provenance jsonb not null default '[]'::jsonb,
    valid_from timestamptz null,
    valid_to timestamptz null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, graph_id)
);

create table if not exists public.kg_relationships (
    tenant_id text not null,
    graph_id text not null,
    relation_type text not null,
    source_graph_id text not null,
    source_entity_type text not null,
    target_graph_id text not null,
    target_entity_type text not null,
    ontology_version text not null,
    properties jsonb not null default '{}'::jsonb,
    provenance jsonb not null default '[]'::jsonb,
    valid_from timestamptz null,
    valid_to timestamptz null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, graph_id),
    constraint kg_relationships_source_fk
        foreign key (tenant_id, source_graph_id)
        references public.kg_nodes (tenant_id, graph_id)
        on delete cascade,
    constraint kg_relationships_target_fk
        foreign key (tenant_id, target_graph_id)
        references public.kg_nodes (tenant_id, graph_id)
        on delete cascade
);

create index if not exists kg_nodes_tenant_entity_idx
    on public.kg_nodes (tenant_id, entity_type);
create index if not exists kg_nodes_properties_gin_idx
    on public.kg_nodes using gin (properties jsonb_path_ops);
create index if not exists kg_relationships_tenant_type_idx
    on public.kg_relationships (tenant_id, relation_type);
create index if not exists kg_relationships_source_idx
    on public.kg_relationships (tenant_id, source_graph_id, relation_type);
create index if not exists kg_relationships_target_idx
    on public.kg_relationships (tenant_id, target_graph_id, relation_type);

alter table public.kg_nodes enable row level security;
alter table public.kg_relationships enable row level security;

-- Intentionally no browser/anon policies. The graph projection is a backend
-- resource accessed with the Supabase service-role key. Application APIs enforce
-- organization membership and tenant scoping before returning HR facts.

comment on table public.kg_nodes is
'Ontology-shaped HR Knowledge Graph node projection. Backend/service-role only.';
comment on table public.kg_relationships is
'Ontology-shaped HR Knowledge Graph relationship projection. Backend/service-role only.';
