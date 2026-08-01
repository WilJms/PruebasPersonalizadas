#!/usr/bin/env python3
"""Apply and verify the Stage 1 migration on an empty local PostgreSQL DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from comprehension_verification.web.repository import Base


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy/supabase/migrations/202607310001_stage1.sql"
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
        description="Prepare an empty loopback PostgreSQL database for Stage 1 tests."
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

    migration_sql = MIGRATION.read_text(encoding="utf-8")
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
        conn.execute(migration_sql, prepare=False)

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
                    'audit_events_are_append_only'
                  )
                """
            ).fetchall()
        }
        if append_only_triggers != {
            "model_calls_are_append_only",
            "audit_events_are_append_only",
        }:
            raise SystemExit("append-only audit triggers are incomplete")

    print(
        json.dumps(
            {
                "append_only_triggers": sorted(append_only_triggers),
                "migration": str(MIGRATION.relative_to(ROOT)),
                "migration_sha256": hashlib.sha256(
                    MIGRATION.read_bytes()
                ).hexdigest(),
                "rls_table_count": len(rls_tables),
                "status": "PASS",
                "table_count": len(actual),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
