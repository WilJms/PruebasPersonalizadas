begin;

-- This migration keeps the Stage 1 table/column surface aligned with
-- comprehension_verification.web.repository.Base. PostgreSQL-only defaults,
-- checks, indexes, RLS and triggers are verified separately.

create or replace function public.cva_set_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create or replace function public.cva_reject_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
  raise exception 'append-only record cannot be updated or deleted';
end;
$$;

create table public.workspaces (
  id varchar(128) primary key,
  name varchar(300) not null,
  created_at timestamptz not null default timezone('utc', now())
);

create table public.users (
  id varchar(128) primary key,
  email varchar(320) not null unique,
  created_at timestamptz not null default timezone('utc', now())
);

create table public.workspace_roles (
  user_id varchar(128) not null references public.users(id),
  workspace_id varchar(128) not null references public.workspaces(id),
  role varchar(32) not null,
  can_approve_assessments boolean not null default false,
  primary key (user_id, workspace_id)
);

create table public.activities (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  status varchar(64) not null default 'DRAFT',
  config jsonb not null,
  blueprint_policy jsonb not null,
  created_by varchar(128) not null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);
create index ix_activities_tenant_id on public.activities (tenant_id);

create table public.artifacts (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  activity_id varchar(128) not null,
  submission_id varchar(128),
  scope_key varchar(256) not null,
  role varchar(64) not null,
  filename varchar(512) not null,
  object_key varchar(1024) not null unique,
  declared_media_type varchar(255) not null,
  expected_byte_size integer not null check (expected_byte_size > 0),
  media_type varchar(255),
  byte_size integer check (byte_size is null or byte_size >= 0),
  sha256 varchar(71) check (sha256 is null or sha256 ~ '^sha256:[0-9a-f]{64}$'),
  status varchar(32) not null default 'PENDING',
  upload_expires_at timestamptz not null,
  created_at timestamptz not null default timezone('utc', now()),
  constraint uq_artifacts_role_per_scope unique (tenant_id, activity_id, scope_key, role)
);
create index ix_artifacts_tenant_id on public.artifacts (tenant_id);
create index ix_artifacts_activity_id on public.artifacts (activity_id);
create index ix_artifacts_submission_id on public.artifacts (submission_id);

create table public.activity_specs (
  activity_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  data jsonb not null
);
create index ix_activity_specs_tenant_id on public.activity_specs (tenant_id);

create table public.rubric_specs (
  activity_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  data jsonb not null
);
create index ix_rubric_specs_tenant_id on public.rubric_specs (tenant_id);

create table public.ambiguity_reports (
  activity_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  data jsonb not null
);
create index ix_ambiguity_reports_tenant_id on public.ambiguity_reports (tenant_id);

create table public.policy_decisions (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  activity_id varchar(128) not null,
  issue_id varchar(128) not null,
  data jsonb not null,
  created_at timestamptz not null default timezone('utc', now()),
  constraint uq_policy_decision_issue unique (tenant_id, activity_id, issue_id)
);
create index ix_policy_decisions_tenant_id on public.policy_decisions (tenant_id);
create index ix_policy_decisions_activity_id on public.policy_decisions (activity_id);

create table public.blueprints (
  row_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  activity_id varchar(128) not null,
  blueprint_id varchar(128) not null,
  version integer not null,
  status varchar(64) not null,
  etag varchar(80) not null unique,
  data jsonb not null,
  review jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  unique (activity_id, version)
);
create index ix_blueprints_tenant_id on public.blueprints (tenant_id);
create index ix_blueprints_activity_id on public.blueprints (activity_id);
create index ix_blueprints_blueprint_id on public.blueprints (blueprint_id);

create table public.submissions (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  activity_id varchar(128) not null unique,
  subject_ref varchar(128) not null,
  blueprint_version integer,
  state jsonb not null,
  active_job_id varchar(128),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);
create index ix_submissions_tenant_id on public.submissions (tenant_id);
create index ix_submissions_activity_id on public.submissions (activity_id);

create table public.evidence_units (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  submission_id varchar(128) not null,
  artifact_id varchar(128) not null,
  data jsonb not null
);
create index ix_evidence_units_tenant_id on public.evidence_units (tenant_id);
create index ix_evidence_units_submission_id on public.evidence_units (submission_id);
create index ix_evidence_units_artifact_id on public.evidence_units (artifact_id);

create table public.evidence_maps (
  submission_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  data jsonb not null
);
create index ix_evidence_maps_tenant_id on public.evidence_maps (tenant_id);

create table public.assessment_plans (
  submission_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  data jsonb not null
);
create index ix_assessment_plans_tenant_id on public.assessment_plans (tenant_id);

create table public.generated_questions (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  submission_id varchar(128) not null,
  data jsonb not null
);
create index ix_generated_questions_tenant_id on public.generated_questions (tenant_id);
create index ix_generated_questions_submission_id on public.generated_questions (submission_id);

create table public.question_reviews (
  question_id varchar(128) primary key,
  tenant_id varchar(128) not null,
  submission_id varchar(128) not null,
  data jsonb not null
);
create index ix_question_reviews_tenant_id on public.question_reviews (tenant_id);
create index ix_question_reviews_submission_id on public.question_reviews (submission_id);

create table public.assessments (
  row_id varchar(128) primary key,
  assessment_id varchar(128) not null,
  tenant_id varchar(128) not null,
  submission_id varchar(128) not null,
  version integer not null default 1,
  status varchar(64) not null,
  etag varchar(80) not null unique,
  data jsonb not null,
  created_at timestamptz not null default timezone('utc', now()),
  unique (submission_id, version)
);
create index ix_assessments_assessment_id on public.assessments (assessment_id);
create index ix_assessments_tenant_id on public.assessments (tenant_id);
create index ix_assessments_submission_id on public.assessments (submission_id);

create table public.evaluation_guides (
  guide_id varchar(128) primary key,
  assessment_id varchar(128) not null,
  tenant_id varchar(128) not null,
  submission_id varchar(128) not null,
  data jsonb not null
);
create index ix_evaluation_guides_assessment_id on public.evaluation_guides (assessment_id);
create index ix_evaluation_guides_tenant_id on public.evaluation_guides (tenant_id);
create index ix_evaluation_guides_submission_id on public.evaluation_guides (submission_id);

create table public.jobs (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  kind varchar(32) not null,
  aggregate_id varchar(128) not null,
  stage varchar(128) not null,
  status varchar(32) not null,
  progress double precision not null default 0,
  attempt integer not null default 0,
  diagnostics jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  started_at timestamptz,
  finished_at timestamptz
);
create index ix_jobs_tenant_id on public.jobs (tenant_id);
create index ix_jobs_aggregate_id on public.jobs (aggregate_id);
create index ix_jobs_status on public.jobs (status);

create table public.stage_runs (
  id varchar(128) primary key,
  job_id varchar(128) not null,
  tenant_id varchar(128) not null,
  stage varchar(128) not null,
  stage_key varchar(71) not null unique,
  status varchar(32) not null,
  attempt integer not null default 1,
  input_hash varchar(71) not null,
  policy_hash varchar(71) not null,
  output jsonb,
  diagnostics jsonb not null default '[]'::jsonb,
  started_at timestamptz not null default timezone('utc', now()),
  finished_at timestamptz
);
create index ix_stage_runs_job_id on public.stage_runs (job_id);
create index ix_stage_runs_tenant_id on public.stage_runs (tenant_id);

create table public.model_calls (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  job_id varchar(128) not null,
  stage varchar(128) not null,
  data jsonb not null
);
create index ix_model_calls_tenant_id on public.model_calls (tenant_id);
create index ix_model_calls_job_id on public.model_calls (job_id);

create table public.exports (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  assessment_id varchar(128) not null,
  status varchar(32) not null,
  artifacts jsonb not null,
  created_at timestamptz not null default timezone('utc', now())
);
create index ix_exports_tenant_id on public.exports (tenant_id);
create index ix_exports_assessment_id on public.exports (assessment_id);

create table public.audit_events (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  event_type varchar(128) not null,
  aggregate_id varchar(128) not null,
  actor_id varchar(128) not null,
  payload jsonb not null,
  occurred_at timestamptz not null default timezone('utc', now())
);
create index ix_audit_events_tenant_id on public.audit_events (tenant_id);
create index ix_audit_events_aggregate_id on public.audit_events (aggregate_id);

create table public.idempotency_keys (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  key varchar(128) not null,
  fingerprint varchar(71) not null,
  response jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  unique (tenant_id, key)
);
create index ix_idempotency_keys_tenant_id on public.idempotency_keys (tenant_id);

create trigger activities_set_updated_at
before update on public.activities
for each row execute function public.cva_set_updated_at();

create trigger submissions_set_updated_at
before update on public.submissions
for each row execute function public.cva_set_updated_at();

create trigger model_calls_are_append_only
before update or delete on public.model_calls
for each row execute function public.cva_reject_mutation();

create trigger audit_events_are_append_only
before update or delete on public.audit_events
for each row execute function public.cva_reject_mutation();

create or replace function public.cva_is_workspace_member(target_tenant_id text)
returns boolean
language sql
stable
security definer
set search_path = pg_catalog
as $$
  select exists (
    select 1
    from public.workspace_roles wr
    where wr.workspace_id = target_tenant_id
      and wr.user_id = auth.uid()::text
  );
$$;

create or replace function public.cva_has_workspace_role(
  target_tenant_id text,
  allowed_roles text[]
)
returns boolean
language sql
stable
security definer
set search_path = pg_catalog
as $$
  select exists (
    select 1
    from public.workspace_roles wr
    where wr.workspace_id = target_tenant_id
      and wr.user_id = auth.uid()::text
      and wr.role = any(allowed_roles)
  );
$$;

revoke all on function public.cva_is_workspace_member(text) from public;
revoke all on function public.cva_has_workspace_role(text, text[]) from public;
grant execute on function public.cva_is_workspace_member(text) to authenticated, service_role;
grant execute on function public.cva_has_workspace_role(text, text[]) to authenticated, service_role;

alter table public.workspaces enable row level security;
alter table public.users enable row level security;
alter table public.workspace_roles enable row level security;
alter table public.activities enable row level security;
alter table public.artifacts enable row level security;
alter table public.activity_specs enable row level security;
alter table public.rubric_specs enable row level security;
alter table public.ambiguity_reports enable row level security;
alter table public.policy_decisions enable row level security;
alter table public.blueprints enable row level security;
alter table public.submissions enable row level security;
alter table public.evidence_units enable row level security;
alter table public.evidence_maps enable row level security;
alter table public.assessment_plans enable row level security;
alter table public.generated_questions enable row level security;
alter table public.question_reviews enable row level security;
alter table public.assessments enable row level security;
alter table public.evaluation_guides enable row level security;
alter table public.jobs enable row level security;
alter table public.stage_runs enable row level security;
alter table public.model_calls enable row level security;
alter table public.exports enable row level security;
alter table public.audit_events enable row level security;
alter table public.idempotency_keys enable row level security;

create policy workspaces_member_read
on public.workspaces for select to authenticated
using (public.cva_is_workspace_member(id));

create policy users_self_read
on public.users for select to authenticated
using (id = auth.uid()::text);

create policy workspace_roles_member_read
on public.workspace_roles for select to authenticated
using (public.cva_is_workspace_member(workspace_id));

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'activities',
    'artifacts',
    'activity_specs',
    'rubric_specs',
    'ambiguity_reports',
    'policy_decisions',
    'blueprints',
    'submissions',
    'evidence_units',
    'evidence_maps',
    'assessment_plans',
    'generated_questions',
    'question_reviews',
    'assessments',
    'evaluation_guides',
    'jobs',
    'stage_runs',
    'model_calls',
    'exports',
    'audit_events',
    'idempotency_keys'
  ]
  loop
    execute format(
      'create policy %I on public.%I for select to authenticated using (public.cva_is_workspace_member(tenant_id))',
      table_name || '_tenant_read',
      table_name
    );
  end loop;
end;
$$;

-- Stage 1 browser code uses Supabase only for authentication. All application
-- table access is through the tenant-scoped API and worker. RLS remains active
-- as defense in depth if grants are introduced in a later stage.
revoke all on all tables in schema public from anon, authenticated;
grant all on all tables in schema public to service_role;

commit;
