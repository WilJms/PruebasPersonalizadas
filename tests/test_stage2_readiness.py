from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from comprehension_verification.web.repository import (
    Base,
    Repository,
    RepositoryError,
    _POSTGRES_POLICY_QUAL,
    _POSTGRES_REQUIRED_COLUMNS,
    _POSTGRES_REQUIRED_CONSTRAINTS,
    _POSTGRES_REQUIRED_INDEXES,
    _STAGE2_APPEND_ONLY_TABLES,
    _postgres_surface_is_ready,
)


def _valid_postgres_surface() -> dict[str, Any]:
    return {
        "relations": {table_name: True for table_name in _STAGE2_APPEND_ONLY_TABLES},
        "columns": set(_POSTGRES_REQUIRED_COLUMNS),
        "constraints": dict(_POSTGRES_REQUIRED_CONSTRAINTS),
        "indexes": {
            key: (must_be_unique, True, True)
            for key, must_be_unique in _POSTGRES_REQUIRED_INDEXES.items()
        },
        "triggers": {
            (table_name, f"{table_name}_are_append_only"): (
                "cva_reject_mutation",
                27,
                "O",
            )
            for table_name in _STAGE2_APPEND_ONLY_TABLES
        },
        "policies": {
            (table_name, f"{table_name}_tenant_read"): (
                "r",
                True,
                True,
                1,
                _POSTGRES_POLICY_QUAL,
            )
            for table_name in _STAGE2_APPEND_ONLY_TABLES
        },
    }


def test_postgres_readiness_accepts_the_complete_expected_surface() -> None:
    assert _postgres_surface_is_ready(**_valid_postgres_surface())


@pytest.mark.parametrize("table_name", _STAGE2_APPEND_ONLY_TABLES)
def test_postgres_readiness_rejects_missing_or_unprotected_append_table(
    table_name: str,
) -> None:
    missing = _valid_postgres_surface()
    missing["relations"].pop(table_name)
    assert not _postgres_surface_is_ready(**missing)

    rls_disabled = _valid_postgres_surface()
    rls_disabled["relations"][table_name] = False
    assert not _postgres_surface_is_ready(**rls_disabled)


@pytest.mark.parametrize("column", sorted(_POSTGRES_REQUIRED_COLUMNS))
def test_postgres_readiness_rejects_each_missing_critical_column(
    column: tuple[str, str],
) -> None:
    surface = _valid_postgres_surface()
    surface["columns"].remove(column)
    assert not _postgres_surface_is_ready(**surface)


@pytest.mark.parametrize("constraint", sorted(_POSTGRES_REQUIRED_CONSTRAINTS))
def test_postgres_readiness_rejects_each_missing_critical_constraint(
    constraint: tuple[str, str],
) -> None:
    surface = _valid_postgres_surface()
    surface["constraints"].pop(constraint)
    assert not _postgres_surface_is_ready(**surface)


@pytest.mark.parametrize("index", sorted(_POSTGRES_REQUIRED_INDEXES))
def test_postgres_readiness_rejects_each_missing_or_invalid_critical_index(
    index: tuple[str, str],
) -> None:
    missing = _valid_postgres_surface()
    missing["indexes"].pop(index)
    assert not _postgres_surface_is_ready(**missing)

    invalid = _valid_postgres_surface()
    is_unique, _, is_ready = invalid["indexes"][index]
    invalid["indexes"][index] = (is_unique, False, is_ready)
    assert not _postgres_surface_is_ready(**invalid)


@pytest.mark.parametrize("table_name", _STAGE2_APPEND_ONLY_TABLES)
def test_postgres_readiness_rejects_missing_or_disabled_append_trigger(
    table_name: str,
) -> None:
    key = (table_name, f"{table_name}_are_append_only")
    missing = _valid_postgres_surface()
    missing["triggers"].pop(key)
    assert not _postgres_surface_is_ready(**missing)

    disabled = _valid_postgres_surface()
    function_name, trigger_type, _ = disabled["triggers"][key]
    disabled["triggers"][key] = (function_name, trigger_type, "D")
    assert not _postgres_surface_is_ready(**disabled)


@pytest.mark.parametrize("table_name", _STAGE2_APPEND_ONLY_TABLES)
def test_postgres_readiness_rejects_missing_or_unscoped_tenant_policy(
    table_name: str,
) -> None:
    key = (table_name, f"{table_name}_tenant_read")
    missing = _valid_postgres_surface()
    missing["policies"].pop(key)
    assert not _postgres_surface_is_ready(**missing)

    unscoped = _valid_postgres_surface()
    command, permissive, authenticated, role_count, _ = unscoped["policies"][key]
    unscoped["policies"][key] = (
        command,
        permissive,
        authenticated,
        role_count,
        "true",
    )
    assert not _postgres_surface_is_ready(**unscoped)


def test_sqlite_readiness_accepts_every_orm_table() -> None:
    Repository("sqlite://").check_readiness()


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_sqlite_readiness_rejects_each_missing_orm_table(table_name: str) -> None:
    repository = Repository("sqlite://")
    with repository.engine.begin() as connection:
        connection.execute(text(f'drop table "{table_name}"'))
    with pytest.raises(RepositoryError, match="EXPECTED_MIGRATION_SURFACE_MISSING"):
        repository.check_readiness()


class _BoundConnectionEngine:
    """Expose one transactional connection to exercise catalog checks safely."""

    def __init__(self, engine: Engine, connection: Connection) -> None:
        self.dialect = engine.dialect
        self._connection = connection

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        yield self._connection


@pytest.mark.skipif(
    not os.environ.get("CVA_TEST_POSTGRES_URL"),
    reason="CVA_TEST_POSTGRES_URL is not configured for PostgreSQL verification",
)
@pytest.mark.parametrize(
    "mutation",
    (
        "drop table public.feedback_events",
        "alter table public.exports drop column data",
        "alter table public.jobs drop constraint ck_jobs_control_state",
        "drop index public.uq_stage_runs_succeeded_stage_key",
        "alter table public.feedback_events disable row level security",
        "alter table public.feedback_events "
        "disable trigger feedback_events_are_append_only",
        "drop policy feedback_events_tenant_read on public.feedback_events",
    ),
)
def test_real_postgres_readiness_rejects_each_incomplete_surface(
    mutation: str,
) -> None:
    database_url = os.environ["CVA_TEST_POSTGRES_URL"]
    sqlalchemy_url = database_url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    repository = Repository(sqlalchemy_url, create_schema=False)
    engine = repository.engine
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(mutation))
            bound_engine = _BoundConnectionEngine(engine, connection)
            repository.engine = bound_engine  # type: ignore[assignment]
            with pytest.raises(
                RepositoryError, match="EXPECTED_MIGRATION_SURFACE_MISSING"
            ):
                repository.check_readiness()
        finally:
            transaction.rollback()
            repository.engine = engine
    engine.dispose()
