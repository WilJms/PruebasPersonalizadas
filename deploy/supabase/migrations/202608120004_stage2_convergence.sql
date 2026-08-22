begin;

-- Idempotency records are bounded replay metadata, not an indefinite copy of
-- application responses. Existing completed and in-flight reservations get a
-- conservative initial window; the API refreshes the deadline when a replay
-- descriptor is completed.
alter table public.idempotency_keys
add column expires_at timestamptz;

update public.idempotency_keys
set expires_at = greatest(
  created_at + interval '24 hours',
  timezone('utc', now()) + interval '5 minutes'
);

alter table public.idempotency_keys
alter column expires_at set default (timezone('utc', now()) + interval '24 hours'),
alter column expires_at set not null;

create index ix_idempotency_keys_expires_at
on public.idempotency_keys (expires_at);

commit;
