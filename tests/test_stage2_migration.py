from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from scripts.prepare_postgres import BOOTSTRAP_SQL, MIGRATIONS
from comprehension_verification.web.repository import Base


ROOT = Path(__file__).resolve().parents[1]
FORWARD = (
    ROOT
    / "deploy/supabase/migrations/202608070003_stage2_experimental.sql"
)
CONVERGENCE = (
    ROOT
    / "deploy/supabase/migrations/202608120004_stage2_convergence.sql"
)
SYNTHETIC_PROVIDER_GATE = (
    ROOT
    / "deploy/supabase/migrations/202608120005_stage2_synthetic_provider_gate.sql"
)
P05_RUNTIME_CUTOVER = (
    ROOT
    / "deploy/supabase/migrations/202608150006_phase3_p05_runtime_cutover.sql"
)
PHASE7_POST_APPROVAL_P09 = (
    ROOT
    / "deploy/supabase/migrations/202608160007_phase7_post_approval_p09.sql"
)
RECOVERY = (
    ROOT
    / "deploy/supabase/rollbacks/202608070003_stage2_experimental_recovery.sql"
)
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@contextmanager
def _temporary_database() -> Iterator[str]:
    """Create and destroy one exact loopback-only database owned by this test."""

    base_url = os.environ["CVA_TEST_POSTGRES_URL"]
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in LOCAL_HOSTS:
        pytest.skip("recovery verification only mutates an explicit loopback database")
    database_name = f"cva_stage2_recovery_{uuid4().hex}"
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    test_url = urlunsplit(parsed._replace(path=f"/{database_name}"))
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("create database {}").format(sql.Identifier(database_name))
        )
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                """
                select pg_terminate_backend(pid)
                from pg_stat_activity
                where datname = %s and pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            connection.execute(
                sql.SQL("drop database {}").format(sql.Identifier(database_name))
            )


def _apply_all_migrations(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(BOOTSTRAP_SQL, prepare=False)
        for migration in MIGRATIONS:
            connection.execute(migration.read_text(encoding="utf-8"), prepare=False)


def _with_application_name(database_url: str, application_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["application_name"] = application_name
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _wait_for_database_wait(
    connection: psycopg.Connection[object],
    *,
    application_name: str,
    wait_event_type: str,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        waiting = connection.execute(
            """
            select exists (
              select 1
              from pg_stat_activity
              where datname = current_database()
                and application_name = %s
                and state = 'active'
                and wait_event_type = %s
            )
            """,
            (application_name, wait_event_type),
        ).fetchone()[0]
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError(
        f"{application_name} did not reach a {wait_event_type} wait"
    )


def _created_table_columns(sql: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    pattern = re.compile(
        r"create\s+table\s+public\.(?P<name>[a-z_]+)\s*\((?P<body>.*?)\n\);",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        columns: set[str] = set()
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.lower().startswith(
                ("constraint ", "primary key ", "unique ", "foreign key ", "check ")
            ):
                continue
            columns.add(line.split(maxsplit=1)[0].strip('"').lower())
        tables[match.group("name").lower()] = columns
    return tables


def test_stage2_forward_migration_is_additive_data_preserving_and_matches_orm() -> None:
    sql = FORWARD.read_text(encoding="utf-8")
    lowered = sql.lower()
    assert lowered.startswith("begin;")
    assert lowered.rstrip().endswith("commit;")
    assert "delete from" not in lowered
    assert "drop table" not in lowered
    assert "drop column" not in lowered
    assert "uq_submissions_tenant_activity_subject" in lowered
    assert "unique (tenant_id, activity_id, subject_ref)" in lowered
    assert "drop constraint submissions_activity_id_key" in lowered

    new_tables = {
        "job_control_records",
        "question_review_actions",
        "feedback_events",
        "bulk_approval_requests",
        "bulk_approval_records",
    }
    created = _created_table_columns(sql)
    expected = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
        if table.name in new_tables
    }
    assert created == expected
    for table_name in new_tables:
        assert f"alter table public.{table_name} enable row level security;" in lowered
        assert f"{table_name}_tenant_read" in lowered
        assert f"{table_name}_are_append_only" in lowered
        assert f"revoke all on public.{table_name} from anon, authenticated;" in lowered
        assert f"grant all on public.{table_name} to service_role;" in lowered


def test_stage2_job_stage_and_export_columns_are_explicit_and_fail_closed() -> None:
    sql = FORWARD.read_text(encoding="utf-8").lower()
    for column in {
        "control_state",
        "failure_class",
        "max_attempts",
        "next_attempt_at",
        "resume_from_stage",
        "cancel_requested_at",
        "cancel_requested_by",
        "cancelled_at",
    }:
        assert re.search(rf"add column\s+{column}\b", sql)

    assert "ck_jobs_cancelled_projection" in sql
    assert "ix_jobs_claim_eligible" in sql
    assert "max_attempts between 1 and 10" in sql
    assert "uq_job_control_records_source_attempt" in sql
    assert "unique (tenant_id, job_id, source_attempt)" in sql

    for column in {
        "component_version",
        "output_hash",
        "failure_class",
        "next_attempt_at",
        "resumed_from_stage_run_id",
    }:
        assert re.search(rf"add column\s+{column}\b", sql)
    assert "uq_stage_runs_job_key_attempt" in sql
    assert "uq_stage_runs_succeeded_stage_key" in sql
    assert "component_version is not null" in sql
    assert "output_hash is not null" in sql

    for column in {
        "activity_id",
        "assessment_version",
        "assessment_snapshot_hash",
        "renderer_version",
        "requested_by",
        "requested_kinds",
        "guide_snapshot_hash",
        "coverage_snapshot_hash",
        "completed_at",
        "data",
    }:
        assert re.search(rf"add column\s+{column}\b", sql)


def test_convergence_migration_bounds_idempotency_replay_retention() -> None:
    sql = CONVERGENCE.read_text(encoding="utf-8").lower()
    assert sql.startswith("begin;")
    assert sql.rstrip().endswith("commit;")
    assert "add column expires_at timestamptz" in sql
    assert "alter column expires_at set not null" in sql
    assert "interval '24 hours'" in sql
    assert "ix_idempotency_keys_expires_at" in sql
    assert "drop table" not in sql
    assert "drop column" not in sql


def test_synthetic_provider_gate_migration_matches_orm_and_is_append_only() -> None:
    sql = SYNTHETIC_PROVIDER_GATE.read_text(encoding="utf-8")
    lowered = sql.lower()
    assert lowered.startswith("begin;")
    assert lowered.rstrip().endswith("commit;")
    assert "drop table" not in lowered
    assert "drop column" not in lowered
    table_names = {
        "synthetic_provider_authorizations",
        "synthetic_provider_claims",
    }
    created = _created_table_columns(sql)
    expected = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
        if table.name in table_names
    }
    assert created == expected
    for table_name in table_names:
        assert f"alter table public.{table_name} enable row level security;" in lowered
        assert f"{table_name}_tenant_read" in lowered
        assert f"{table_name}_are_append_only" in lowered
        assert f"revoke all on public.{table_name} from anon, authenticated;" in lowered
        assert f"grant all on public.{table_name} to service_role;" in lowered


def test_p05_runtime_cutover_adds_only_the_deterministic_preflight_snapshot() -> None:
    lowered = P05_RUNTIME_CUTOVER.read_text(encoding="utf-8").lower()
    assert lowered.startswith("begin;")
    assert lowered.rstrip().endswith("commit;")
    assert "alter table public.blueprints" in lowered
    assert "add column preflight jsonb" in lowered
    assert "drop table" not in lowered
    assert "drop column" not in lowered


def test_phase7_post_approval_p09_migration_is_additive_and_preserves_history() -> None:
    lowered = PHASE7_POST_APPROVAL_P09.read_text(encoding="utf-8").lower()
    assert lowered.startswith("begin;")
    assert lowered.rstrip().endswith("commit;")
    assert "alter table public.evaluation_guides" in lowered
    for column in {
        "assessment_version",
        "assessment_etag",
        "assessment_snapshot_hash",
        "question_set_hash",
        "approval_event_id",
        "approval_snapshot_hash",
        "guide_policy_hash",
        "materializer_boundary_hash",
        "guide_job_id",
        "status",
        "created_at",
    }:
        assert re.search(rf"add column\s+{column}\b", lowered)
    assert "alter table public.jobs" in lowered
    assert "add column descriptor jsonb" in lowered
    assert "uq_evaluation_guides_approved_version" in lowered
    assert "where assessment_version is not null" in lowered
    assert "set status = 'historical_preapproval'" in lowered
    assert "delete from" not in lowered
    assert "drop table" not in lowered
    assert "drop column" not in lowered


def test_recovery_refuses_loss_before_restoring_e1_constraints() -> None:
    sql = RECOVERY.read_text(encoding="utf-8").lower()
    assert sql.startswith("begin;")
    assert sql.rstrip().endswith("commit;")
    guard = sql.index("do $$")
    first_drop = sql.index("drop table")
    assert guard < first_drop
    assert "having count(*) > 1" in sql
    assert "durable job control history would be lost" in sql
    assert "stage resume metadata would be lost" in sql
    assert "append-only e2 evidence must be retained" in sql
    assert "public.job_control_records," in sql
    assert "public.bulk_approval_records" in sql
    assert "public.synthetic_provider_authorizations" in sql
    assert "public.synthetic_provider_claims" in sql
    assert "in access exclusive mode;" in sql
    assert "add constraint submissions_activity_id_key unique (activity_id)" in sql
    assert "add constraint stage_runs_stage_key_key unique (stage_key)" in sql


@pytest.mark.skipif(
    not os.environ.get("CVA_TEST_POSTGRES_URL"),
    reason="CVA_TEST_POSTGRES_URL is not configured for local PG16/17 verification",
)
def test_real_postgres_upgrade_when_explicit_loopback_database_is_available() -> None:
    with _temporary_database() as database_url:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/prepare_postgres.py"),
                "--database-url",
                database_url,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    assert '"status": "PASS"' in result.stdout
    assert '"stage2_preserved_upgrade_rows": 1' in result.stdout
    assert '"stage2_duplicate_subject_blocked": true' in result.stdout
    assert '"phase7_legacy_guide_preserved": true' in result.stdout
    assert '"phase7_exact_version_unique": true' in result.stdout


@pytest.mark.skipif(
    not os.environ.get("CVA_TEST_POSTGRES_URL"),
    reason="CVA_TEST_POSTGRES_URL is not configured for local PG16/17 verification",
)
def test_real_postgres_recovery_is_reversible_fail_closed_and_writer_safe() -> None:
    recovery_sql = RECOVERY.read_text(encoding="utf-8")
    forward_sql = FORWARD.read_text(encoding="utf-8")
    provider_gate_sql = SYNTHETIC_PROVIDER_GATE.read_text(encoding="utf-8")
    with _temporary_database() as database_url:
        _apply_all_migrations(database_url)

        # An empty E2 surface can return to E1 without dropping an E1 fact, and
        # the forward migration remains re-applicable afterwards.
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(recovery_sql, prepare=False)
            assert connection.execute(
                "select to_regclass('public.feedback_events') is null"
            ).fetchone()[0]
            assert connection.execute(
                """
                select exists (
                  select 1 from pg_constraint
                  where conrelid = 'public.submissions'::regclass
                    and conname = 'submissions_activity_id_key'
                )
                """
            ).fetchone()[0]
            connection.execute(forward_sql, prepare=False)
            connection.execute(provider_gate_sql, prepare=False)
            assert connection.execute(
                "select to_regclass('public.feedback_events') is not null"
            ).fetchone()[0]

            # A durable E2 fact makes recovery fail before any DDL can discard it.
            connection.execute(
                """
                insert into public.feedback_events
                  (id, tenant_id, actor_id, activity_id, target_type, target_id,
                   rating, category, data)
                values
                  ('feedback_recovery_guard', 'tnt_recovery', 'usr_recovery',
                   'act_recovery', 'ACTIVITY', 'act_recovery', 'NEUTRAL',
                   'USABILITY', '{}'::jsonb)
                """
            )
            with pytest.raises(psycopg.errors.RaiseException, match="append-only E2"):
                connection.execute(recovery_sql, prepare=False)
            connection.rollback()
            assert connection.execute(
                """
                select count(*) = 1
                from public.feedback_events
                where id = 'feedback_recovery_guard'
                """
            ).fetchone()[0]
            connection.execute("truncate table public.feedback_events")

            # Pause the recovery at its first DROP after every E2 table has
            # already been locked ACCESS EXCLUSIVE. A new writer must block and
            # can never commit a fact behind the emptiness guard.
            advisory_key = 202608070003
            connection.execute(
                """
                create function public.cva_pause_recovery_drop()
                returns event_trigger
                language plpgsql
                as $$
                begin
                  perform pg_advisory_lock(202608070003);
                end;
                $$;
                create event trigger cva_pause_recovery_drop
                on ddl_command_start
                when tag in ('DROP TABLE')
                execute function public.cva_pause_recovery_drop();
                """,
                prepare=False,
            )
            connection.execute("select pg_advisory_lock(%s)", (advisory_key,))

            outcomes: dict[str, object] = {}

            def run_recovery() -> None:
                try:
                    dsn = _with_application_name(
                        database_url, "cva-recovery-race"
                    )
                    with psycopg.connect(dsn, autocommit=True) as recovery_connection:
                        recovery_connection.execute(recovery_sql, prepare=False)
                    outcomes["recovery"] = "committed"
                except Exception as exc:  # pragma: no cover - asserted below
                    outcomes["recovery"] = exc

            def run_writer() -> None:
                try:
                    dsn = _with_application_name(
                        database_url, "cva-recovery-writer"
                    )
                    with psycopg.connect(dsn, autocommit=True) as writer_connection:
                        writer_connection.execute("set statement_timeout = '10s'")
                        writer_connection.execute(
                            """
                            insert into public.feedback_events
                              (id, tenant_id, actor_id, activity_id, target_type,
                               target_id, rating, category, data)
                            values
                              ('feedback_racing_writer', 'tnt_recovery',
                               'usr_recovery', 'act_recovery', 'ACTIVITY',
                               'act_recovery', 'NEUTRAL', 'USABILITY', '{}'::jsonb)
                            """
                        )
                    outcomes["writer"] = "committed"
                except Exception as exc:
                    outcomes["writer"] = exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                recovery_future = executor.submit(run_recovery)
                _wait_for_database_wait(
                    connection,
                    application_name="cva-recovery-race",
                    wait_event_type="Lock",
                )
                writer_future = executor.submit(run_writer)
                _wait_for_database_wait(
                    connection,
                    application_name="cva-recovery-writer",
                    wait_event_type="Lock",
                )
                connection.execute(
                    "select pg_advisory_unlock(%s)", (advisory_key,)
                )
                recovery_future.result(timeout=15)
                writer_future.result(timeout=15)

            assert outcomes["recovery"] == "committed"
            assert isinstance(outcomes["writer"], psycopg.errors.UndefinedTable)
            assert connection.execute(
                "select to_regclass('public.feedback_events') is null"
            ).fetchone()[0]
