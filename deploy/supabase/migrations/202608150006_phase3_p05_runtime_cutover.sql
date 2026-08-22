begin;

-- Phase 3 retires P05 from the active activity runtime.  Historical review
-- snapshots remain nullable and readable; the active deterministic gate gets
-- its own independently queryable snapshot.
alter table public.blueprints
  add column preflight jsonb;

commit;
