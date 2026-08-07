from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from pydantic import ValidationError

from comprehension_verification.web import worker
from comprehension_verification.web.app import create_app
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import JobRow, Repository
from comprehension_verification.web.settings import Settings, WorkerSettings
from comprehension_verification.web.workflows import Stage1Service


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


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


def test_spa_document_cannot_survive_a_rollout_in_browser_cache(tmp_path: Path) -> None:
    frontend = tmp_path / "dist"
    assets = frontend / "assets"
    assets.mkdir(parents=True)
    (frontend / "index.html").write_text("<main>current shell</main>", encoding="utf-8")
    (frontend / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    (assets / "app-deadbeef.js").write_text("export {};", encoding="utf-8")
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        session_secret="spa-cache-test-secret-with-sufficient-length",
        local_invited_emails="teacher@example.test",
        frontend_dist=str(frontend),
    )

    with TestClient(create_app(settings)) as client:
        for path in ("/", "/index.html", "/login", "/activities/example"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.text == "<main>current shell</main>"
            assert response.headers["cache-control"] == "no-store, max-age=0"

        manifest = client.get("/manifest.webmanifest")
        assert manifest.status_code == 200
        assert manifest.headers["cache-control"] == "no-cache"

        asset = client.get("/assets/app-deadbeef.js")
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )


def test_cloud_worker_settings_exclude_web_auth_and_session_secrets() -> None:
    settings = WorkerSettings(**_cloud_settings())

    assert settings.model_mode == "mock"
    assert "session_secret" not in WorkerSettings.model_fields
    assert "auth_mode" not in WorkerSettings.model_fields
    assert "supabase_jwt_issuer" not in WorkerSettings.model_fields
    assert "job_runner_mode" not in WorkerSettings.model_fields


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


def test_real_uvicorn_process_never_logs_valid_invalid_or_expired_capabilities(
    tmp_path: Path,
) -> None:
    port = _unused_local_port()
    session_secret = "process-log-session-secret-with-at-least-32-bytes"
    database = tmp_path / "process-log.db"
    repo_root = Path(__file__).resolve().parents[1]
    python_bin = Path(sys.executable).parent
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{python_bin}{os.pathsep}{environment.get('PATH', '')}",
            "PYTHONUNBUFFERED": "1",
            "PORT": str(port),
            "CVA_ENVIRONMENT": "test",
            "CVA_DATABASE_URL": f"sqlite+pysqlite:///{database}",
            "CVA_AUTH_MODE": "local",
            "CVA_OBJECT_STORE_MODE": "memory",
            "CVA_JOB_RUNNER_MODE": "inline",
            "CVA_MODEL_MODE": "mock",
            "CVA_P10_ENABLED": "false",
            "CVA_SESSION_SECRET": session_secret,
            "CVA_LOCAL_INVITED_EMAILS": "teacher@example.test",
        }
    )
    process = subprocess.Popen(
        [
            "sh",
            "deploy/docker-entrypoint.sh",
            "web",
            "--host",
            "127.0.0.1",
            "--log-level",
            "info",
        ],
        cwd=repo_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    sensitive_values: set[str] = set()
    output = ""
    try:
        base_url = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base_url, timeout=3.0) as client:
            deadline = time.monotonic() + 15
            while True:
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    startup_output = process.stdout.read() if process.stdout else ""
                    raise AssertionError(
                        f"Uvicorn exited before readiness with {process.returncode}: "
                        f"{startup_output}"
                    )
                if time.monotonic() >= deadline:
                    raise AssertionError("Uvicorn did not become ready")
                time.sleep(0.05)

            logged_in = client.post(
                "/api/v1/session/login", json={"email": "teacher@example.test"}
            )
            assert logged_in.status_code == 200
            csrf = client.cookies.get("cva_csrf")
            assert csrf
            mutation_headers = {
                "X-CSRF-Token": csrf,
                "Idempotency-Key": str(uuid4()),
            }
            created = client.post(
                "/api/v1/activities",
                headers=mutation_headers,
                json={
                    "title": "Synthetic capability log probe",
                    "output_language": "es-CL",
                    "assessment_modality": "WRITTEN",
                    "question_count": 1,
                    "target_total_minutes": 3,
                    "allowed_response_formats": ["OPEN_SHORT"],
                    "allowed_artifact_media_types": ["text/plain"],
                    "structured_justification_mode": "NOT_REQUIRED",
                },
            )
            assert created.status_code == 201, created.text
            activity_id = created.json()["activity"]["activity_id"]
            prepared = client.post(
                f"/api/v1/activities/{activity_id}/artifacts/uploads",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": str(uuid4()),
                },
                json={
                    "role": "ASSIGNMENT_PROMPT",
                    "filename": "synthetic.txt",
                    "media_type": "text/plain",
                    "byte_size": 4,
                },
            )
            assert prepared.status_code == 201, prepared.text
            upload_url = prepared.json()["upload"]["upload_url"]
            valid_capability = upload_url.rsplit("/", 1)[-1]
            sensitive_values.add(valid_capability)
            assert client.put(
                upload_url,
                headers={"Content-Type": "text/plain"},
                content=b"safe",
            ).status_code == 204

            now = datetime.now(UTC)
            expired_capability = jwt.encode(
                {
                    "iss": "cva-object-fake",
                    "aud": "cva-object-fake",
                    "key": "synthetic/expired",
                    "method": "GET",
                    "iat": now - timedelta(minutes=2),
                    "exp": now - timedelta(minutes=1),
                },
                session_secret,
                algorithm="HS256",
            )
            invalid_capability = f"invalid-capability-{uuid4()}"
            sensitive_values.update({expired_capability, invalid_capability})
            assert client.get(
                f"/api/v1/objects/{expired_capability}"
            ).status_code == 403
            assert client.get(
                f"/api/v1/objects/{invalid_capability}"
            ).status_code == 403
    finally:
        process.terminate()
        try:
            output = process.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate(timeout=5)[0]

    assert sensitive_values
    assert all(value not in output for value in sensitive_values)
    assert '"event":"http.request.completed"' in output
    assert '"route":"/api/v1/object-uploads/{token}"' in output
    assert '"route":"/api/v1/objects/{token}"' in output


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
    monkeypatch.setattr(worker, "get_worker_settings", lambda: object())
    monkeypatch.setattr(worker, "build_worker_runtime", lambda _settings: runtime)

    assert asyncio.run(worker.run_once()) == 1
    failed = repository.job_status("job_first", "tnt_worker")
    assert failed.status == "FAILED"
    assert [item.code for item in failed.diagnostics] == ["JOB_KIND_INVALID"]
    untouched = repository.job_status("job_second", "tnt_worker")
    assert untouched.status == "QUEUED"
    assert untouched.attempt == 0
