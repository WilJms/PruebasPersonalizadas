begin;

-- Versions deployed before the Stage 1 replay descriptor allowlist could
-- persist a complete JSON response, including a short-lived capability URL.
-- Delete only reservations that cannot be replayed safely. JSON null was the
-- legacy representation of an abandoned reservation and is removed as well.
delete from public.idempotency_keys
where response = 'null'::jsonb
   or (
     response is not null
     and (
       response::text ~* '"[^"]*_url"[[:space:]]*:'
       or response::text ~* '/api/v1/(objects|object-uploads)/'
       or response::text ~* 'x-amz-(algorithm|credential|date|expires|signedheaders|signature|security-token)='
       or response::text ~* 'https?://[^"[:space:]/:]+:[^"[:space:]@]+@'
     )
   );

-- Keep the application guard as the first boundary and make the invariant
-- durable at PostgreSQL too. Completed descriptors are JSON objects; SQL NULL
-- is reserved exclusively for an in-flight first request.
alter table public.idempotency_keys
add constraint ck_idempotency_keys_safe_response
check (
  response is null
  or (
    jsonb_typeof(response) = 'object'
    and response::text !~* '"[^"]*_url"[[:space:]]*:'
    and response::text !~* '/api/v1/(objects|object-uploads)/'
    and response::text !~* 'x-amz-(algorithm|credential|date|expires|signedheaders|signature|security-token)='
    and response::text !~* 'https?://[^"[:space:]/:]+:[^"[:space:]@]+@'
  )
);

commit;
