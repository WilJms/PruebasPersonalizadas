begin;

-- Real-provider capability is represented by two append-only, content-free
-- facts.  An operator creates one exact authorization before dispatch; the
-- worker inserts one claim only after it has atomically claimed that same job.
create table public.synthetic_provider_authorizations (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  job_id varchar(128) not null,
  job_kind varchar(32) not null,
  aggregate_id varchar(128) not null,
  expected_claim_attempt integer not null,
  artifact_hashes jsonb not null,
  candidate_sha varchar(40) not null,
  boundary_hash varchar(71) not null,
  route_profile varchar(128) not null,
  model varchar(128) not null,
  secret_version_resource varchar(512) not null,
  max_requests integer not null,
  max_cost_usd double precision not null,
  classification varchar(64) not null,
  schema_version varchar(128) not null,
  authorization_hash varchar(71) not null,
  created_by varchar(128) not null,
  created_at timestamptz not null,
  expires_at timestamptz not null,
  constraint uq_synthetic_provider_authorization_job unique (job_id),
  constraint uq_synthetic_provider_authorization_hash unique (authorization_hash),
  constraint ck_synthetic_provider_authorization_attempt
    check (expected_claim_attempt between 1 and 10),
  constraint ck_synthetic_provider_authorization_requests
    check (max_requests between 1 and 64),
  constraint ck_synthetic_provider_authorization_cost
    check (max_cost_usd between 0.01 and 10.0),
  constraint ck_synthetic_provider_authorization_classification
    check (classification = 'SYNTHETIC_ONLY_NO_STUDENT_DATA')
);
create index ix_synthetic_provider_authorizations_tenant_id
  on public.synthetic_provider_authorizations (tenant_id);
create index ix_synthetic_provider_authorizations_job_id
  on public.synthetic_provider_authorizations (job_id);
create index ix_synthetic_provider_authorizations_aggregate_id
  on public.synthetic_provider_authorizations (aggregate_id);

create table public.synthetic_provider_claims (
  id varchar(128) primary key,
  authorization_id varchar(128) not null,
  authorization_hash varchar(71) not null,
  tenant_id varchar(128) not null,
  job_id varchar(128) not null,
  claim_attempt integer not null,
  candidate_sha varchar(40) not null,
  boundary_hash varchar(71) not null,
  schema_version varchar(128) not null,
  claimed_at timestamptz not null,
  constraint uq_synthetic_provider_claim_authorization unique (authorization_id),
  constraint uq_synthetic_provider_claim_job unique (job_id),
  constraint ck_synthetic_provider_claim_attempt
    check (claim_attempt between 1 and 10)
);
create index ix_synthetic_provider_claims_authorization_id
  on public.synthetic_provider_claims (authorization_id);
create index ix_synthetic_provider_claims_tenant_id
  on public.synthetic_provider_claims (tenant_id);
create index ix_synthetic_provider_claims_job_id
  on public.synthetic_provider_claims (job_id);

create trigger synthetic_provider_authorizations_are_append_only
before update or delete on public.synthetic_provider_authorizations
for each row execute function public.cva_reject_mutation();

create trigger synthetic_provider_claims_are_append_only
before update or delete on public.synthetic_provider_claims
for each row execute function public.cva_reject_mutation();

alter table public.synthetic_provider_authorizations enable row level security;
alter table public.synthetic_provider_claims enable row level security;

create policy synthetic_provider_authorizations_tenant_read
on public.synthetic_provider_authorizations for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

create policy synthetic_provider_claims_tenant_read
on public.synthetic_provider_claims for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

revoke all on public.synthetic_provider_authorizations from anon, authenticated;
revoke all on public.synthetic_provider_claims from anon, authenticated;
grant all on public.synthetic_provider_authorizations to service_role;
grant all on public.synthetic_provider_claims to service_role;

commit;
