-- Raw multi-organization upload persistence for Supabase/PostgreSQL.
--
-- Different organizations can upload different columns.  We intentionally keep
-- arbitrary source columns in row_data JSONB instead of ALTER TABLE per upload.
-- The canonical ontology projection is stored separately in kg_nodes and
-- kg_relationships.

create table if not exists public.org_ingestion_datasets (
    tenant_id text not null,
    dataset_id text not null,
    source_system text not null,
    source_object text not null,
    source_format text not null,
    row_count bigint not null default 0,
    column_names jsonb not null default '[]'::jsonb,
    mapping_summary jsonb not null default '{}'::jsonb,
    sync_status text not null default 'staged',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, dataset_id)
);

create table if not exists public.org_ingestion_rows (
    tenant_id text not null,
    dataset_id text not null,
    row_number bigint not null,
    row_data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    primary key (tenant_id, dataset_id, row_number),
    constraint org_ingestion_rows_dataset_fk
        foreign key (tenant_id, dataset_id)
        references public.org_ingestion_datasets (tenant_id, dataset_id)
        on delete cascade
);

create index if not exists org_ingestion_datasets_tenant_source_idx
    on public.org_ingestion_datasets (tenant_id, source_system, source_object);
create index if not exists org_ingestion_rows_tenant_dataset_idx
    on public.org_ingestion_rows (tenant_id, dataset_id, row_number);
create index if not exists org_ingestion_rows_data_gin_idx
    on public.org_ingestion_rows using gin (row_data jsonb_path_ops);

alter table public.org_ingestion_datasets enable row level security;
alter table public.org_ingestion_rows enable row level security;

comment on table public.org_ingestion_datasets is
'Tenant-scoped metadata for arbitrary organization source uploads. Backend/service-role only.';
comment on table public.org_ingestion_rows is
'Raw tenant source rows preserved as JSONB so organization-specific columns do not require dynamic DDL.';
