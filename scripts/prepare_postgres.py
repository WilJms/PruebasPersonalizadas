#!/usr/bin/env python3
"""Apply and verify the ordered Stage 1 -> Stage 2 migrations locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from comprehension_verification.web.repository import (
    Base,
    IDEMPOTENCY_CAPABILITY_CONSTRAINT,
    STAGE2_JOB_CONTROL_CONSTRAINT,
    STAGE2_SUBMISSION_CONSTRAINT,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "deploy/supabase/migrations"
MIGRATIONS = tuple(sorted(MIGRATION_DIR.glob("*.sql")))
PRIMARY_MIGRATION = MIGRATION_DIR / "202607310001_stage1.sql"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

BOOTSTRAP_SQL = """
do $$ begin
  create role anon nologin;
exception when duplicate_object then null;
end $$;
do $$ begin
  create role authenticated nologin;
exception when duplicate_object then null;
end $$;
do $$ begin
  create role service_role nologin bypassrls;
exception when duplicate_object then null;
end $$;
create schema if not exists auth;
create or replace function auth.uid()
returns uuid
language sql
stable
as $$ select null::uuid $$;
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare an empty loopback PostgreSQL database for Stage 2 tests."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CVA_TEST_POSTGRES_URL"),
        help="Loopback PostgreSQL URL; defaults to CVA_TEST_POSTGRES_URL.",
    )
    return parser.parse_args()


def _database_schema(conn: psycopg.Connection[object]) -> dict[str, set[str]]:
    rows = conn.execute(
        """
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'public'
        order by table_name, ordinal_position
        """
    ).fetchall()
    result: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        result.setdefault(str(table_name), set()).add(str(column_name))
    return result


def main() -> int:
    args = _arguments()
    if not args.database_url:
        raise SystemExit("--database-url or CVA_TEST_POSTGRES_URL is required")
    parsed = urlparse(args.database_url)
    if parsed.scheme not in {"postgresql", "postgres"} or parsed.hostname not in LOCAL_HOSTS:
        raise SystemExit("refusing to mutate a non-loopback or non-PostgreSQL database")

    if not MIGRATIONS or MIGRATIONS[0] != PRIMARY_MIGRATION:
        raise SystemExit("the ordered Stage 1/2 migration set is incomplete")
    migration_sql = [
        (path, path.read_text(encoding="utf-8")) for path in MIGRATIONS
    ]
    expected = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        existing = {
            str(row[0])
            for row in conn.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'public' and table_type = 'BASE TABLE'
                """
            ).fetchall()
        }
        if existing:
            raise SystemExit(
                "refusing to apply the migration to a non-empty public schema: "
                + ", ".join(sorted(existing))
            )

        conn.execute(BOOTSTRAP_SQL, prepare=False)
        _, first_sql = migration_sql[0]
        conn.execute(first_sql, prepare=False)
        conn.execute(
            """
            insert into public.idempotency_keys
              (id, tenant_id, key, fingerprint, response)
            values
              (
                'idem_migration_probe_json_null',
                'tnt_migration_probe',
                'migration-probe-json-null',
                'sha256:' || repeat('a', 64),
                'null'::jsonb
              ),
              (
                'idem_migration_probe_capability',
                'tnt_migration_probe',
                'migration-probe-capability',
                'sha256:' || repeat('b', 64),
                jsonb_build_object(
                  'kind', 'json',
                  'body', jsonb_build_object(
                    'view_url',
                    'https://synthetic.invalid/object?X-Amz-Signature=synthetic'
                  )
                )
              )
            """
        )
        conn.execute(
            """
            insert into public.activities
              (id, tenant_id, status, config, blueprint_policy, created_by)
            values
              (
                'act_stage2_upgrade_probe',
                'tnt_stage2_upgrade_probe',
                'BLUEPRINT_APPROVED',
                '{}'::jsonb,
                '{}'::jsonb,
                'usr_stage2_upgrade_probe'
              );
            insert into public.submissions
              (id, tenant_id, activity_id, subject_ref, state)
            values
              (
                'sub_stage2_upgrade_probe_e1',
                'tnt_stage2_upgrade_probe',
                'act_stage2_upgrade_probe',
                'subject_e1',
                '{}'::jsonb
              )
            """,
            prepare=False,
        )
        for _, sql in migration_sql[1:]:
            conn.execute(sql, prepare=False)

        preserved_upgrade_rows = int(
            conn.execute(
                """
                select count(*) from public.submissions
                where id = 'sub_stage2_upgrade_probe_e1'
                  and tenant_id = 'tnt_stage2_upgrade_probe'
                  and activity_id = 'act_stage2_upgrade_probe'
                  and subject_ref = 'subject_e1'
                """
            ).fetchone()[0]
        )
        if preserved_upgrade_rows != 1:
            raise SystemExit("E1 submission was not preserved by the Stage 2 upgrade")
        conn.execute(
            """
            insert into public.submissions
              (id, tenant_id, activity_id, subject_ref, state)
            values
              (
                'sub_stage2_upgrade_probe_e2',
                'tnt_stage2_upgrade_probe',
                'act_stage2_upgrade_probe',
                'subject_e2',
                '{}'::jsonb
              )
            """
        )
        try:
            conn.execute(
                """
                insert into public.submissions
                  (id, tenant_id, activity_id, subject_ref, state)
                values
                  (
                    'sub_stage2_upgrade_probe_duplicate',
                    'tnt_stage2_upgrade_probe',
                    'act_stage2_upgrade_probe',
                    'subject_e2',
                    '{}'::jsonb
                  )
                """
            )
        except psycopg.errors.UniqueViolation:
            duplicate_subject_blocked = True
        else:
            duplicate_subject_blocked = False
        if not duplicate_subject_blocked:
            raise SystemExit("Stage 2 submission subject uniqueness is not enforced")

        legacy_probe_count = int(
            conn.execute(
                """
                select count(*)
                from public.idempotency_keys
                where tenant_id = 'tnt_migration_probe'
                """
            ).fetchone()[0]
        )
        if legacy_probe_count != 0:
            raise SystemExit("idempotency capability hygiene did not remove probes")

        capability_constraint = bool(
            conn.execute(
                """
                select exists (
                  select 1
                  from pg_constraint
                  where conrelid = 'public.idempotency_keys'::regclass
                    and conname = %s
                )
                """,
                (IDEMPOTENCY_CAPABILITY_CONSTRAINT,),
            ).fetchone()[0]
        )
        if not capability_constraint:
            raise SystemExit("idempotency capability constraint is missing")

        stage2_constraints = {
            str(row[0])
            for row in conn.execute(
                """
                select conname
                from pg_constraint
                where conname = any(%s)
                """,
                (
                    [
                        STAGE2_SUBMISSION_CONSTRAINT,
                        STAGE2_JOB_CONTROL_CONSTRAINT,
                    ],
                ),
            ).fetchall()
        }
        if stage2_constraints != {
            STAGE2_SUBMISSION_CONSTRAINT,
            STAGE2_JOB_CONTROL_CONSTRAINT,
        }:
            raise SystemExit("Stage 2 migration constraints are incomplete")

        actual = _database_schema(conn)
        if actual != expected:
            missing_tables = sorted(set(expected) - set(actual))
            extra_tables = sorted(set(actual) - set(expected))
            column_drift = sorted(
                table
                for table in set(expected).intersection(actual)
                if expected[table] != actual[table]
            )
            raise SystemExit(
                "migration/ORM drift: "
                + json.dumps(
                    {
                        "column_drift": column_drift,
                        "extra_tables": extra_tables,
                        "missing_tables": missing_tables,
                    },
                    sort_keys=True,
                )
            )

        rls_tables = {
            str(row[0])
            for row in conn.execute(
                """
                select c.relname
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
                """
            ).fetchall()
        }
        if rls_tables != set(expected):
            raise SystemExit("RLS is not enabled on every migrated application table")

        append_only_triggers = {
            str(row[0])
            for row in conn.execute(
                """
                select trigger_name
                from information_schema.triggers
                where trigger_schema = 'public'
                  and trigger_name in (
                    'model_calls_are_append_only',
                    'audit_events_are_append_only',
                    'job_control_records_are_append_only',
                    'question_review_actions_are_append_only',
                    'feedback_events_are_append_only',
                    'bulk_approval_requests_are_append_only',
                    'bulk_approval_records_are_append_only'
                  )
                """
            ).fetchall()
        }
        if append_only_triggers != {
            "model_calls_are_append_only",
            "audit_events_are_append_only",
            "job_control_records_are_append_only",
            "question_review_actions_are_append_only",
            "feedback_events_are_append_only",
            "bulk_approval_requests_are_append_only",
            "bulk_approval_records_are_append_only",
        }:
            raise SystemExit("append-only audit triggers are incomplete")

        conn.execute(
            """
            delete from public.submissions
            where tenant_id = 'tnt_stage2_upgrade_probe';
            delete from public.activities
            where tenant_id = 'tnt_stage2_upgrade_probe'
            """,
            prepare=False,
        )

    print(
        json.dumps(
            {
                "append_only_triggers": sorted(append_only_triggers),
                "idempotency_capability_constraint": capability_constraint,
                "idempotency_legacy_probe_count": legacy_probe_count,
                "stage2_constraints": sorted(stage2_constraints),
                "stage2_duplicate_subject_blocked": duplicate_subject_blocked,
                "stage2_preserved_upgrade_rows": preserved_upgrade_rows,
                "migrations": [
                    str(path.relative_to(ROOT)) for path in MIGRATIONS
                ],
                "migration_sha256": {
                    str(path.relative_to(ROOT)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in MIGRATIONS
                },
                "rls_table_count": len(rls_tables),
                "schema_checks": "tables_columns_rls_append_only_triggers",
                "status": "PASS",
                "table_count": len(actual),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
