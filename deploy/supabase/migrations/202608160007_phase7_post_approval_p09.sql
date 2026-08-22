begin;

-- Phase 7 retains pre-approval guides as readable history while making every
-- active guide selection exact to one durable human-approved assessment
-- version. Nullable columns are intentional for legacy rows.
alter table public.evaluation_guides
  add column assessment_version integer,
  add column assessment_etag varchar(80),
  add column assessment_snapshot_hash varchar(80),
  add column question_set_hash varchar(80),
  add column approval_event_id varchar(128),
  add column approval_snapshot_hash varchar(80),
  add column guide_policy_hash varchar(80),
  add column materializer_boundary_hash varchar(80),
  add column guide_job_id varchar(128),
  add column status varchar(32),
  add column created_at timestamptz;

create unique index uq_evaluation_guides_approved_version
  on public.evaluation_guides (tenant_id, assessment_id, assessment_version)
  where assessment_version is not null;
create index ix_evaluation_guides_guide_job_id
  on public.evaluation_guides (guide_job_id);
create index ix_evaluation_guides_status
  on public.evaluation_guides (status);

-- The durable job carries only a hash-bound, content-safe descriptor. The
-- worker reconstructs the canonical request from persisted domain rows and
-- rejects any mismatch before a provider adapter can be reached.
alter table public.jobs
  add column descriptor jsonb;

update public.evaluation_guides
set status = 'HISTORICAL_PREAPPROVAL'
where status is null;

commit;
