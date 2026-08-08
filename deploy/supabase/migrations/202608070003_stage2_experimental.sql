begin;

-- E2-01 removes only the Stage 1 cardinality constraint. Existing rows remain
-- untouched and already satisfy the new tenant/activity/subject uniqueness.
lock table public.submissions in share row exclusive mode;
alter table public.submissions
  drop constraint submissions_activity_id_key;
alter table public.submissions
  add constraint uq_submissions_tenant_activity_subject
  unique (tenant_id, activity_id, subject_ref);

-- E2-03 keeps the canonical v1.1 technical status projection while durable
-- control state carries cancellation and bounded retry scheduling.
alter table public.jobs
  add column control_state varchar(32) not null default 'ACTIVE',
  add column failure_class varchar(32),
  add column max_attempts integer not null default 3,
  add column next_attempt_at timestamptz,
  add column resume_from_stage varchar(128),
  add column cancel_requested_at timestamptz,
  add column cancel_requested_by varchar(128),
  add column cancelled_at timestamptz,
  add constraint ck_jobs_control_state
    check (control_state in ('ACTIVE', 'CANCEL_REQUESTED', 'CANCELLED')),
  add constraint ck_jobs_failure_class
    check (
      failure_class is null or failure_class in (
        'TRANSIENT', 'PERMANENT', 'SECURITY', 'VALIDATION',
        'PRECONDITION', 'PROVIDER', 'CANCELLATION'
      )
    ),
  add constraint ck_jobs_max_attempts check (max_attempts between 1 and 10),
  add constraint ck_jobs_cancelled_projection
    check (
      control_state <> 'CANCELLED'
      or (
        status = 'FAILED'
        and failure_class = 'CANCELLATION'
        and cancelled_at is not null
      )
    );

create index ix_jobs_claim_eligible
on public.jobs (status, control_state, next_attempt_at, created_at);

-- A logical stage key may have failed attempts, but only one verified success.
-- Legacy successful rows deliberately retain NULL component/output hashes and
-- are not reusable after upgrade because their omitted metadata is unknowable.
alter table public.stage_runs
  drop constraint stage_runs_stage_key_key;
alter table public.stage_runs
  add column component_version varchar(255),
  add column output_hash varchar(71),
  add column failure_class varchar(32),
  add column next_attempt_at timestamptz,
  add column resumed_from_stage_run_id varchar(128),
  add constraint uq_stage_runs_job_key_attempt
    unique (job_id, stage_key, attempt),
  add constraint ck_stage_runs_failure_class
    check (
      failure_class is null or failure_class in (
        'TRANSIENT', 'PERMANENT', 'SECURITY', 'VALIDATION',
        'PRECONDITION', 'PROVIDER', 'CANCELLATION'
      )
    );

create unique index uq_stage_runs_succeeded_stage_key
on public.stage_runs (stage_key)
where status = 'SUCCEEDED'
  and component_version is not null
  and output_hash is not null;

-- E1 export rows stay readable. New E2 rows can additionally persist the full
-- canonical ExportRecord without ever persisting a signed download capability.
alter table public.exports
  add column activity_id varchar(128),
  add column assessment_version integer,
  add column assessment_snapshot_hash varchar(71),
  add column renderer_version varchar(255),
  add column requested_by varchar(128),
  add column requested_kinds jsonb,
  add column guide_snapshot_hash varchar(71),
  add column coverage_snapshot_hash varchar(71),
  add column completed_at timestamptz,
  add column data jsonb;

create index ix_exports_activity_id on public.exports (activity_id);

create table public.job_control_records (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  job_id varchar(128) not null,
  resulting_job_id varchar(128),
  aggregate_id varchar(128) not null,
  actor_id varchar(128) not null,
  action varchar(32) not null,
  status varchar(32) not null,
  source_attempt integer not null,
  target_stage varchar(128),
  failure_class varchar(32),
  data jsonb not null,
  requested_at timestamptz not null,
  decided_at timestamptz,
  constraint uq_job_control_records_source_attempt
    unique (tenant_id, job_id, source_attempt)
);
create index ix_job_control_records_tenant_id
  on public.job_control_records (tenant_id);
create index ix_job_control_records_job_id
  on public.job_control_records (job_id);
create index ix_job_control_records_resulting_job_id
  on public.job_control_records (resulting_job_id);
create index ix_job_control_records_aggregate_id
  on public.job_control_records (aggregate_id);
create index ix_job_control_records_actor_id
  on public.job_control_records (actor_id);

create table public.question_review_actions (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  activity_id varchar(128) not null,
  assessment_id varchar(128) not null,
  assessment_version_before integer not null,
  assessment_version_after integer,
  submission_id varchar(128) not null,
  question_id varchar(128) not null,
  actor_id varchar(128) not null,
  action varchar(32) not null,
  status varchar(32) not null,
  revalidation_status varchar(32) not null,
  before_snapshot_hash varchar(71) not null,
  after_snapshot_hash varchar(71),
  data jsonb not null,
  occurred_at timestamptz not null
);
create index ix_question_review_actions_tenant_id
  on public.question_review_actions (tenant_id);
create index ix_question_review_actions_activity_id
  on public.question_review_actions (activity_id);
create index ix_question_review_actions_assessment_id
  on public.question_review_actions (assessment_id);
create index ix_question_review_actions_submission_id
  on public.question_review_actions (submission_id);
create index ix_question_review_actions_question_id
  on public.question_review_actions (question_id);
create index ix_question_review_actions_actor_id
  on public.question_review_actions (actor_id);

create table public.feedback_events (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  actor_id varchar(128) not null,
  activity_id varchar(128) not null,
  assessment_id varchar(128),
  assessment_version integer,
  question_id varchar(128),
  target_type varchar(32) not null,
  target_id varchar(128) not null,
  rating varchar(32) not null,
  category varchar(64) not null,
  data jsonb not null,
  occurred_at timestamptz not null default timezone('utc', now())
);
create index ix_feedback_events_tenant_id on public.feedback_events (tenant_id);
create index ix_feedback_events_actor_id on public.feedback_events (actor_id);
create index ix_feedback_events_activity_id on public.feedback_events (activity_id);
create index ix_feedback_events_assessment_id on public.feedback_events (assessment_id);
create index ix_feedback_events_question_id on public.feedback_events (question_id);
create index ix_feedback_events_target_id on public.feedback_events (target_id);

create table public.bulk_approval_requests (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  actor_id varchar(128) not null,
  target_count integer not null,
  data jsonb not null,
  requested_at timestamptz not null,
  constraint ck_bulk_request_count check (target_count between 1 and 500)
);
create index ix_bulk_approval_requests_tenant_id
  on public.bulk_approval_requests (tenant_id);
create index ix_bulk_approval_requests_actor_id
  on public.bulk_approval_requests (actor_id);

create table public.bulk_approval_records (
  id varchar(128) primary key,
  tenant_id varchar(128) not null,
  request_id varchar(128) not null,
  actor_id varchar(128) not null,
  approved_count integer not null,
  excluded_count integer not null,
  data jsonb not null,
  approved_at timestamptz not null,
  constraint uq_bulk_record_request unique (tenant_id, request_id),
  constraint ck_bulk_record_counts
    check (approved_count >= 0 and excluded_count >= 0)
);
create index ix_bulk_approval_records_tenant_id
  on public.bulk_approval_records (tenant_id);
create index ix_bulk_approval_records_request_id
  on public.bulk_approval_records (request_id);
create index ix_bulk_approval_records_actor_id
  on public.bulk_approval_records (actor_id);

-- Human decisions and experimental feedback are immutable evidence. Corrections
-- create another record/version; UPDATE and DELETE fail closed.
create trigger job_control_records_are_append_only
before update or delete on public.job_control_records
for each row execute function public.cva_reject_mutation();

create trigger question_review_actions_are_append_only
before update or delete on public.question_review_actions
for each row execute function public.cva_reject_mutation();

create trigger feedback_events_are_append_only
before update or delete on public.feedback_events
for each row execute function public.cva_reject_mutation();

create trigger bulk_approval_requests_are_append_only
before update or delete on public.bulk_approval_requests
for each row execute function public.cva_reject_mutation();

create trigger bulk_approval_records_are_append_only
before update or delete on public.bulk_approval_records
for each row execute function public.cva_reject_mutation();

alter table public.job_control_records enable row level security;
alter table public.question_review_actions enable row level security;
alter table public.feedback_events enable row level security;
alter table public.bulk_approval_requests enable row level security;
alter table public.bulk_approval_records enable row level security;

create policy job_control_records_tenant_read
on public.job_control_records for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

create policy question_review_actions_tenant_read
on public.question_review_actions for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

create policy feedback_events_tenant_read
on public.feedback_events for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

create policy bulk_approval_requests_tenant_read
on public.bulk_approval_requests for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

create policy bulk_approval_records_tenant_read
on public.bulk_approval_records for select to authenticated
using (public.cva_is_workspace_member(tenant_id));

revoke all on public.job_control_records from anon, authenticated;
revoke all on public.question_review_actions from anon, authenticated;
revoke all on public.feedback_events from anon, authenticated;
revoke all on public.bulk_approval_requests from anon, authenticated;
revoke all on public.bulk_approval_records from anon, authenticated;
grant all on public.job_control_records to service_role;
grant all on public.question_review_actions to service_role;
grant all on public.feedback_events to service_role;
grant all on public.bulk_approval_requests to service_role;
grant all on public.bulk_approval_records to service_role;

commit;
