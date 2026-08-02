from __future__ import annotations

import asyncio
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from pydantic import ValidationError

from comprehension_verification.web import worker
from comprehension_verification.web.app import create_app
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import JobRow, Repository
from comprehension_verification.web.settings import Settings
from comprehension_verification.web.workflows import Stage1Service


def _cloud_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": "cloud",
        "database_url": (
            "postgresql+psycopg://stage1:database-password-do-not-log@"
            "db.example.test:5432/stage1"
        ),
        "auth_mode": "supabase",
        "object_store_mode": "r2",
        "job_runner_mode": "cloud_run",
        "model_mode": "mock",
        "session_secret": "managed-cloud-session-secret-with-32-bytes",
        "supabase_jwt_issuer": "https://project.supabase.co/auth/v1",
        "supabase_jwks_url": (
            "https://project.supabase.co/auth/v1/.well-known/jwks.json"
        ),
        "r2_endpoint_url": "https://account.r2.cloudflarestorage.com",
        "r2_bucket": "private-stage1",
        "r2_access_key_id": "scoped-access-key",
        "r2_secret_access_key": "scoped-secret-key",
        "gcp_project_id": "project-stage1",
        "gcp_region": "us-central1",
        "cloud_run_job_name": "cva-worker",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"database_url": "sqlite+pysqlite:///cloud.db"}, "PostgreSQL psycopg"),
        (
            {"database_url": "postgresql://stage1:secret@db.example.test/stage1"},
            "PostgreSQL psycopg",
        ),
        ({"database_url": ""}, r"postgresql\+psycopg database URL"),
        ({"auth_mode": "local"}, "Supabase authentication"),
        ({"object_store_mode": "memory"}, "private R2"),
        ({"job_runner_mode": "inline"}, "Cloud Run Jobs"),
        ({"model_mode": "real"}, "mock model gateway"),
        (
            {"session_secret": "local-development-secret-change-me"},
            "managed session secret",
        ),
        ({"supabase_jwks_url": None}, "issuer and JWKS URL"),
        ({"r2_secret_access_key": None}, "scoped credentials"),
        ({"gcp_region": None}, "project, region and job name"),
    ],
)
def test_cloud_configuration_fails_closed(
    overrides: dict[str, object], expected: str
) -> None:
    with pytest.raises(ValidationError, match=expected) as caught:
        Settings(**_cloud_settings(**overrides))
    assert "database-password-do-not-log" not in str(caught.value)


def test_cloud_accepts_only_complete_explicit_psycopg_configuration() -> None:
    settings = Settings(**_cloud_settings())
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.model_mode == "mock"
    assert settings.p10_enabled is False


def test_upload_and_download_capabilities_use_separate_bounded_ttls() -> None:
    store = MemoryObjectStore(
        secret="signed-url-test-secret-with-at-least-32-bytes",
        upload_ttl_seconds=1200,
        download_ttl_seconds=180,
    )
    upload = store.sign_put("raw/example", "text/plain", 4)
    download = store.sign_get("raw/example")

    upload_claims = jwt.decode(
        upload.url.rsplit("/", 1)[-1],
        options={"verify_signature": False},
        algorithms=["HS256"],
    )
    download_claims = jwt.decode(
        download.url.rsplit("/", 1)[-1],
        options={"verify_signature": False},
        algorithms=["HS256"],
    )
    assert upload_claims["exp"] - upload_claims["iat"] == 1200
    assert download_claims["exp"] - download_claims["iat"] == 180


def _test_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        session_secret="readiness-test-session-secret-with-32-bytes",
    )


def test_health_is_lightweight_and_readiness_checks_the_schema(monkeypatch) -> None:
    repository = Repository("sqlite+pysqlite://")
    app = create_app(_test_settings(), repository=repository)

    def unavailable() -> None:
        raise RuntimeError("database details must never be returned")

    monkeypatch.setattr(repository, "check_readiness", unavailable)
    with TestClient(app) as client:
        health = client.get("/api/health")
        readiness = client.get("/api/readiness")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert readiness.status_code == 503
    assert readiness.json() == {"status": "not_ready"}
    assert "database" not in readiness.text


def test_readiness_fails_when_the_expected_migration_surface_is_missing() -> None:
    repository = Repository("sqlite+pysqlite://")
    app = create_app(_test_settings(), repository=repository)
    with repository.engine.begin() as connection:
        connection.execute(text("drop table idempotency_keys"))

    with TestClient(app) as client:
        response = client.get("/api/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_readiness_succeeds_with_the_expected_schema() -> None:
    app = create_app(_test_settings())
    with TestClient(app) as client:
        response = client.get("/api/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_worker_execution_claims_at_most_one_job_and_persists_failure(
    monkeypatch,
) -> None:
    repository = Repository("sqlite+pysqlite://")
    repository.add(
        JobRow(
            id="job_first",
            tenant_id="tnt_worker",
            kind="UNKNOWN",
            aggregate_id="aggregate_first",
            stage="QUEUED",
            status="QUEUED",
        )
    )
    repository.add(
        JobRow(
            id="job_second",
            tenant_id="tnt_worker",
            kind="UNKNOWN",
            aggregate_id="aggregate_second",
            stage="QUEUED",
            status="QUEUED",
        )
    )
    service = Stage1Service(
        settings=_test_settings(),
        repository=repository,
        object_store=MemoryObjectStore(
            secret="worker-test-object-secret-with-at-least-32-bytes"
        ),
    )
    runtime = SimpleNamespace(repository=repository, service=service)
    monkeypatch.setattr(worker, "get_settings", lambda: object())
    monkeypatch.setattr(worker, "build_runtime", lambda _settings: runtime)

    assert asyncio.run(worker.run_once()) == 1
    failed = repository.job_status("job_first", "tnt_worker")
    assert failed.status == "FAILED"
    assert [item.code for item in failed.diagnostics] == ["JOB_KIND_INVALID"]
    untouched = repository.job_status("job_second", "tnt_worker")
    assert untouched.status == "QUEUED"
    assert untouched.attempt == 0
