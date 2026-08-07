from __future__ import annotations

import asyncio
import base64
from io import BytesIO

from fastapi import Response

from comprehension_verification.web.auth import AuthService
from comprehension_verification.web.jobs import CloudRunJobRunner
from comprehension_verification.web.object_store import R2ObjectStore
from comprehension_verification.web.repository import Repository
from comprehension_verification.web.settings import Settings


def _secret() -> str:
    return "adapter-test-session-secret-with-32-bytes"


def test_r2_adapter_uses_bounded_private_signed_operations(monkeypatch) -> None:
    class FakeR2Client:
        presigned: list[tuple[str, dict, int]] = []
        puts: list[dict] = []

        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            self.presigned.append((operation, Params, ExpiresIn))
            return f"https://private-r2.invalid/{operation}"

        def head_object(self, **_kwargs):
            return {"ContentLength": 4, "ContentType": "text/plain"}

        def get_object(self, **_kwargs):
            return {"Body": BytesIO(b"data")}

        def put_object(self, **kwargs):
            self.puts.append(kwargs)
            return {}

    fake = FakeR2Client()
    monkeypatch.setattr(
        "comprehension_verification.web.object_store.boto3.client",
        lambda *_args, **_kwargs: fake,
    )
    settings = Settings(
        environment="test",
        session_secret=_secret(),
        object_store_mode="r2",
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_bucket="private-stage1",
        r2_access_key_id="scoped-key",
        r2_secret_access_key="scoped-secret",
        upload_url_ttl_seconds=1200,
        download_url_ttl_seconds=180,
    )
    store = R2ObjectStore(settings)
    upload = store.sign_put("raw/tnt/art/upload", "text/plain", 4)
    download = store.sign_get("raw/tnt/art/sealed/hash")
    assert upload.url.startswith("https://private-r2.invalid/")
    assert download.url.startswith("https://private-r2.invalid/")
    assert fake.presigned[0][0] == "put_object"
    assert fake.presigned[0][1] == {
        "Bucket": "private-stage1",
        "Key": "raw/tnt/art/upload",
        "ContentType": "text/plain",
        "ContentLength": 4,
    }
    # Browsers calculate Content-Length themselves; the signed S3 params bind
    # it without asking frontend JavaScript to set a forbidden header.
    assert upload.headers == {"Content-Type": "text/plain"}
    assert fake.presigned[0][2] == 1200
    assert fake.presigned[1][0] == "get_object"
    assert fake.presigned[1][2] == 180
    assert store.get_bytes("raw/tnt/art/sealed/hash", max_bytes=4) == b"data"
    store.put_immutable("raw/tnt/art/sealed/hash", b"data", "text/plain")
    assert fake.puts[0]["IfNoneMatch"] == "*"
    assert fake.puts[0]["Metadata"]["cva-sha256"]
    assert base64.b64decode(fake.puts[0]["ChecksumSHA256"])


def test_cloud_run_dispatch_sends_no_job_or_subject_override(monkeypatch) -> None:
    calls: list[tuple[str, dict, int]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"name": "operations/fake-execution"}

    class FakeSession:
        def __init__(self, _credentials) -> None:
            pass

        def post(self, url: str, *, json: dict, timeout: int) -> FakeResponse:
            calls.append((url, json, timeout))
            return FakeResponse()

    monkeypatch.setattr(
        "comprehension_verification.web.jobs.google.auth.default",
        lambda **_kwargs: (object(), "project-test"),
    )
    monkeypatch.setattr(
        "comprehension_verification.web.jobs.AuthorizedSession", FakeSession
    )
    settings = Settings(
        environment="test",
        session_secret=_secret(),
        job_runner_mode="cloud_run",
        gcp_project_id="project-test",
        gcp_region="us-central1",
        cloud_run_job_name="cva-worker",
    )
    result = asyncio.run(CloudRunJobRunner(settings).dispatch("job-secret-subject"))
    assert result == "operations/fake-execution"
    assert calls == [
        (
            "https://run.googleapis.com/v2/projects/project-test/locations/"
            "us-central1/jobs/cva-worker:run",
            {},
            20,
        )
    ]


def test_supabase_exchange_accepts_only_a_persisted_invited_membership(
    monkeypatch,
) -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.seed_workspace(
        "tnt_supabase",
        [("00000000-0000-4000-8000-000000000001", "teacher@example.test", "TEACHER")],
    )
    settings = Settings(
        environment="test",
        session_secret=_secret(),
        auth_mode="supabase",
        supabase_jwt_issuer="https://project.supabase.co/auth/v1",
        supabase_jwks_url="https://project.supabase.co/auth/v1/.well-known/jwks.json",
    )

    class SigningKey:
        key = "verified-public-key"

    class FakeJwks:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_signing_key_from_jwt(self, token: str) -> SigningKey:
            assert token == "supabase-access-token"
            return SigningKey()

    monkeypatch.setattr(
        "comprehension_verification.web.auth.jwt.PyJWKClient", FakeJwks
    )

    def verified_decode(token, key, **kwargs):
        assert token == "supabase-access-token"
        assert key == "verified-public-key"
        assert kwargs["issuer"] == settings.supabase_jwt_issuer
        assert kwargs["audience"] == "authenticated"
        return {
            "sub": "00000000-0000-4000-8000-000000000001",
            "email": "teacher@example.test",
            "iat": 1,
            "exp": 9_999_999_999,
        }

    monkeypatch.setattr(
        "comprehension_verification.web.auth.jwt.decode", verified_decode
    )
    response = Response()
    actor = AuthService(settings, repo).exchange_supabase_token(
        "supabase-access-token", response
    )
    assert actor.workspace_id == "tnt_supabase"
    assert actor.role == "TEACHER"
    assert actor.can_approve_assessments is True
    assert "cva_session=" in response.headers.get("set-cookie", "")
