begin;

-- This recovery is intentionally fail-closed. It restores the exact E1 schema
-- only when no E2-only fact would be discarded. If a guard raises, keep the E2
-- schema, deploy the last known-good E2 image, and export/resolve the reported
-- rows before attempting recovery again.
lock table public.submissions, public.jobs, public.stage_runs, public.exports
in share row exclusive mode;
-- Quiesce every append-only E2 writer before checking emptiness.  Without this
-- lock an INSERT could commit after the guard and immediately before DROP,
-- making the recovery claim data-preserving while discarding that new fact.
lock table
  public.job_control_records,
  public.question_review_actions,
  public.feedback_events,
  public.bulk_approval_requests,
  public.bulk_approval_records
in access exclusive mode;

do $$
begin
  if exists (
    select 1
    from public.submissions
    group by activity_id
    having count(*) > 1
  ) then
    raise exception
      'E2 recovery refused: activities with multiple submissions require explicit archival';
  end if;

  if exists (
    select 1 from public.jobs
    where control_state <> 'ACTIVE'
       or failure_class is not null
       or max_attempts <> 3
       or next_attempt_at is not null
       or resume_from_stage is not null
       or cancel_requested_at is not null
       or cancel_requested_by is not null
       or cancelled_at is not null
  ) then
    raise exception
      'E2 recovery refused: durable job control history would be lost';
  end if;

  if exists (
    select 1 from public.stage_runs
    where component_version is not null
       or output_hash is not null
       or failure_class is not null
       or next_attempt_at is not null
       or resumed_from_stage_run_id is not null
  ) then
    raise exception
      'E2 recovery refused: stage resume metadata would be lost';
  end if;

  if exists (
    select 1
    from public.stage_runs
    group by stage_key
    having count(*) > 1
  ) then
    raise exception
      'E2 recovery refused: repeated stage attempts cannot fit the E1 key';
  end if;

  if exists (
    select 1 from public.exports
    where activity_id is not null
       or assessment_version is not null
       or assessment_snapshot_hash is not null
       or renderer_version is not null
       or requested_by is not null
       or requested_kinds is not null
       or guide_snapshot_hash is not null
       or coverage_snapshot_hash is not null
       or completed_at is not null
       or data is not null
  ) then
    raise exception
      'E2 recovery refused: canonical export snapshot metadata would be lost';
  end if;

  if exists (select 1 from public.job_control_records)
     or exists (select 1 from public.question_review_actions)
     or exists (select 1 from public.feedback_events)
     or exists (select 1 from public.bulk_approval_requests)
     or exists (select 1 from public.bulk_approval_records) then
    raise exception
      'E2 recovery refused: append-only E2 evidence must be retained';
  end if;
end;
$$;

drop table public.bulk_approval_records;
drop table public.bulk_approval_requests;
drop table public.feedback_events;
drop table public.question_review_actions;
drop table public.job_control_records;

drop index public.ix_exports_activity_id;
alter table public.exports
  drop column data,
  drop column completed_at,
  drop column coverage_snapshot_hash,
  drop column guide_snapshot_hash,
  drop column requested_kinds,
  drop column requested_by,
  drop column renderer_version,
  drop column assessment_snapshot_hash,
  drop column assessment_version,
  drop column activity_id;

drop index public.uq_stage_runs_succeeded_stage_key;
alter table public.stage_runs
  drop constraint ck_stage_runs_failure_class,
  drop constraint uq_stage_runs_job_key_attempt,
  drop column resumed_from_stage_run_id,
  drop column next_attempt_at,
  drop column failure_class,
  drop column output_hash,
  drop column component_version,
  add constraint stage_runs_stage_key_key unique (stage_key);

drop index public.ix_jobs_claim_eligible;
alter table public.jobs
  drop constraint ck_jobs_cancelled_projection,
  drop constraint ck_jobs_max_attempts,
  drop constraint ck_jobs_failure_class,
  drop constraint ck_jobs_control_state,
  drop column cancelled_at,
  drop column cancel_requested_by,
  drop column cancel_requested_at,
  drop column resume_from_stage,
  drop column next_attempt_at,
  drop column max_attempts,
  drop column failure_class,
  drop column control_state;

alter table public.submissions
  drop constraint uq_submissions_tenant_activity_subject,
  add constraint submissions_activity_id_key unique (activity_id);

commit;
