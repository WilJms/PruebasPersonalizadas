"""Durable exactly-once authorization for billable synthetic evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .canonical import canonical_hash


LEDGER_SCHEMA_VERSION = "openai-eval-authorization-ledger/1.0.0"

# Budget for winning (or observing) the one-time WAL switch. Generous enough to
# outlast a slow CI writer, bounded so a genuinely stuck database still fails.
_WAL_SETUP_ATTEMPTS = 600
_WAL_SETUP_RETRY_SECONDS = 0.05


class EvaluationAuthorizationConsumed(RuntimeError):
    """The authorization was already reserved, including after a crash."""


class EvaluationAuthorizationMismatch(RuntimeError):
    """A completion attempt does not match the originally reserved boundary."""


@dataclass(frozen=True, slots=True)
class EvaluationReservation:
    execution_id: str
    authorization_hash: str
    boundary_hash: str
    reserved_at: str
    status: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _hash_label(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


class EvaluationAuthorizationLedger:
    """Reserve an entire transport plan atomically before its first request.

    Reservations never expire and are never reclaimed. A process crash after
    ``reserve`` therefore consumes the authorization instead of permitting an
    accidental second billable run.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        # ``busy_timeout`` and ``synchronous`` are per-connection and cheap.
        # ``journal_mode`` is deliberately absent: WAL is a persistent property
        # of the file, so it is established once in ``_initialize`` instead of
        # being re-asserted by every connection. See ``_ensure_wal_mode``.
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("pragma busy_timeout = 30000")
        connection.execute("pragma synchronous = full")
        return connection

    @staticmethod
    def _ensure_wal_mode(connection: sqlite3.Connection) -> None:
        """Put the database into WAL once, tolerating a concurrent switcher.

        Switching journal mode needs a brief exclusive lock, and unlike an
        ordinary statement the pragma does not go through the busy handler: a
        racing writer makes it fail immediately rather than wait out
        ``busy_timeout``. That is what made concurrent ledger construction flaky.

        Once any connection has made the switch the mode is persistent and the
        pragma becomes a no-op, so the loser of the race only has to look again.
        """

        for _attempt in range(_WAL_SETUP_ATTEMPTS):
            try:
                row = connection.execute("pragma journal_mode = wal").fetchone()
            except sqlite3.OperationalError:
                row = None
            if row is None:
                try:
                    row = connection.execute("pragma journal_mode").fetchone()
                except sqlite3.OperationalError:
                    row = None
            if row is not None and str(row[0]).casefold() == "wal":
                return
            time.sleep(_WAL_SETUP_RETRY_SECONDS)
        raise sqlite3.OperationalError(
            "evaluation authorization ledger could not enter WAL mode"
        )

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            self._ensure_wal_mode(connection)
            connection.execute(
                """
                create table if not exists evaluation_authorizations (
                    execution_id text primary key,
                    authorization_hash text not null unique,
                    boundary_hash text not null,
                    boundary_json text not null,
                    schema_version text not null,
                    status text not null check (
                        status in ('RESERVED', 'COMPLETED', 'FAILED')
                    ),
                    reserved_at text not null,
                    finished_at text,
                    report_hash text,
                    failure_code text
                ) strict
                """
            )
        finally:
            connection.close()

    def reserve(
        self,
        *,
        execution_id: str,
        authorization_id: str,
        boundary: dict[str, Any],
    ) -> EvaluationReservation:
        if not execution_id.strip() or not authorization_id.strip():
            raise ValueError("execution_id and authorization_id are required")
        boundary_hash = canonical_hash(boundary)
        authorization_hash = _hash_label(authorization_id)
        reserved_at = _utc_now()
        boundary_json = json.dumps(
            boundary,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        connection = self._connect()
        try:
            connection.execute("begin immediate")
            try:
                connection.execute(
                    """
                    insert into evaluation_authorizations (
                        execution_id,
                        authorization_hash,
                        boundary_hash,
                        boundary_json,
                        schema_version,
                        status,
                        reserved_at
                    ) values (?, ?, ?, ?, ?, 'RESERVED', ?)
                    """,
                    (
                        execution_id,
                        authorization_hash,
                        boundary_hash,
                        boundary_json,
                        LEDGER_SCHEMA_VERSION,
                        reserved_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise EvaluationAuthorizationConsumed(
                    "EVALUATION_AUTHORIZATION_ALREADY_CONSUMED"
                ) from exc
            connection.commit()
        finally:
            connection.close()
        return EvaluationReservation(
            execution_id=execution_id,
            authorization_hash=authorization_hash,
            boundary_hash=boundary_hash,
            reserved_at=reserved_at,
            status="RESERVED",
        )

    def finish(
        self,
        *,
        reservation: EvaluationReservation,
        status: str,
        report_hash: str | None,
        failure_code: str | None = None,
    ) -> None:
        if status not in {"COMPLETED", "FAILED"}:
            raise ValueError("terminal evaluation status is required")
        connection = self._connect()
        try:
            connection.execute("begin immediate")
            cursor = connection.execute(
                """
                update evaluation_authorizations
                set status = ?, finished_at = ?, report_hash = ?, failure_code = ?
                where execution_id = ?
                  and authorization_hash = ?
                  and boundary_hash = ?
                  and status = 'RESERVED'
                """,
                (
                    status,
                    _utc_now(),
                    report_hash,
                    failure_code,
                    reservation.execution_id,
                    reservation.authorization_hash,
                    reservation.boundary_hash,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise EvaluationAuthorizationMismatch(
                    "EVALUATION_RESERVATION_NOT_ACTIVE"
                )
            connection.commit()
        finally:
            connection.close()

    def record(self, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select execution_id, authorization_hash, boundary_hash,
                       schema_version, status, reserved_at, finished_at,
                       report_hash, failure_code
                from evaluation_authorizations
                where execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
        return dict(row) if row is not None else None
