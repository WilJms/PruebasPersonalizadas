from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import (
    LUNA_MODEL_ID,
    OPENAI_ROUTE_PROFILE_ID,
    build_mock_request,
)
from comprehension_verification.provider_authorization import (
    SyntheticProviderAuthorizationSpec,
    synthetic_provider_boundary_hash,
)
from comprehension_verification.web import worker
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import (
    ActivityRow,
    ArtifactRow,
    Conflict,
    JobRow,
    Repository,
    SyntheticProviderClaimRow,
)
from comprehension_verification.web.settings import WorkerSettings


CANDIDATE_SHA = "a" * 40
SECRET_RESOURCE = (
    "projects/project-stage1/secrets/cva-openai-api-key/versions/2"
)
ARTIFACT_HASH = "sha256:" + "b" * 64


def _settings(job_id: str, *, candidate_sha: str = CANDIDATE_SHA) -> WorkerSettings:
    return WorkerSettings(
        environment="test",
        database_url="sqlite+pysqlite://",
        model_mode="real",
        claim_job_id=job_id,
        openai_secret_version_resource=SECRET_RESOURCE,
        synthetic_evaluation_candidate_sha=candidate_sha,
        synthetic_evaluation_max_requests=4,
        max_job_cost_usd=0.25,
    )


def _seed_job(repository: Repository, job_id: str) -> JobRow:
    activity_id = "act_synthetic_gate"
    try:
        repository.get(ActivityRow, activity_id)
    except Exception:
        config = build_mock_request("P01_ACTIVITY_SPEC_V1").activity_config
        repository.add(
            ActivityRow(
                id=activity_id,
                tenant_id="tnt_synthetic_gate",
                status="DRAFT",
                config=config.model_dump(mode="json"),
                blueprint_policy={},
                created_by="operator_gate",
            )
        )
        repository.add(
            ArtifactRow(
                id="art_synthetic_gate",
                tenant_id="tnt_synthetic_gate",
                activity_id=activity_id,
                submission_id=None,
                scope_key=activity_id,
                role=m.ArtifactRole.ASSIGNMENT_PROMPT.value,
                filename="synthetic.md",
                object_key="synthetic/gate/sealed",
                declared_media_type="text/markdown",
                expected_byte_size=32,
                media_type="text/markdown",
                byte_size=32,
                sha256=ARTIFACT_HASH,
                status="COMPLETE",
                upload_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    row = JobRow(
        id=job_id,
        tenant_id="tnt_synthetic_gate",
        kind="ACTIVITY",
        aggregate_id=activity_id,
        stage="QUEUED",
        status="QUEUED",
        progress=0.0,
        attempt=0,
        diagnostics=[],
    )
    repository.add(row)
    return row


def _authorization(
    repository: Repository,
    job_id: str,
    *,
    candidate_sha: str = CANDIDATE_SHA,
) -> SyntheticProviderAuthorizationSpec:
    job = repository.get(JobRow, job_id)
    assert isinstance(job, JobRow)
    spec = SyntheticProviderAuthorizationSpec(
        authorization_id=f"authorization_{job_id}",
        tenant_id=job.tenant_id,
        job_id=job.id,
        job_kind=job.kind,
        aggregate_id=job.aggregate_id,
        expected_claim_attempt=1,
        artifact_hashes=repository.synthetic_artifact_hashes_for_job(job.id),
        candidate_sha=candidate_sha,
        boundary_hash=synthetic_provider_boundary_hash(),
        secret_version_resource=SECRET_RESOURCE,
        max_requests=4,
        max_cost_usd=0.25,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        created_by="operator_gate",
    )
    repository.authorize_synthetic_provider_job(spec)
    return spec


def _install_worker_fakes(
    monkeypatch: pytest.MonkeyPatch,
    repository: Repository,
    settings: WorkerSettings,
) -> dict[str, int]:
    counters = {"key_resolver": 0, "transport_construction": 0, "requests": 0}
    store = MemoryObjectStore(
        secret="synthetic-gate-object-store-secret-at-least-32-bytes"
    )
    monkeypatch.setattr(worker, "get_worker_settings", lambda: settings)
    monkeypatch.setattr(
        worker,
        "build_worker_bootstrap_runtime",
        lambda _settings: SimpleNamespace(
            repository=repository,
            object_store=store,
        ),
    )

    def forbidden_resolver(_resource: str) -> SecretStr:
        counters["key_resolver"] += 1
        raise AssertionError("credential resolver was reachable")

    def forbidden_transport(*_args: object, **_kwargs: object) -> object:
        counters["transport_construction"] += 1
        raise AssertionError("provider transport construction was reachable")

    monkeypatch.setattr(worker, "resolve_openai_api_key", forbidden_resolver)
    monkeypatch.setattr(worker, "build_worker_runtime", forbidden_transport)
    return counters


def _assert_zero_provider_capabilities(counters: dict[str, int]) -> None:
    assert counters == {
        "key_resolver": 0,
        "transport_construction": 0,
        "requests": 0,
    }


def test_normal_job_and_real_flag_without_attestation_have_zero_provider_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository("sqlite+pysqlite://")
    _seed_job(repository, "job_normal_unattested")
    counters = _install_worker_fakes(
        monkeypatch,
        repository,
        _settings("job_normal_unattested"),
    )

    assert asyncio.run(worker.run_once()) == 1
    _assert_zero_provider_capabilities(counters)
    status = repository.job_status(
        "job_normal_unattested", "tnt_synthetic_gate"
    )
    assert status.status == "FAILED"
    assert [item.code for item in status.diagnostics] == [
        "SYNTHETIC_AUTHORIZATION_REQUIRED"
    ]
    activity = repository.get(ActivityRow, "act_synthetic_gate")
    assert isinstance(activity, ActivityRow)
    assert activity.status == "TECHNICAL_FAILURE"


def test_divergent_artifact_hash_has_zero_provider_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository("sqlite+pysqlite://")
    _seed_job(repository, "job_hash_divergent")
    _authorization(repository, "job_hash_divergent")
    with repository.session() as session:
        artifact = session.get(ArtifactRow, "art_synthetic_gate")
        assert artifact is not None
        artifact.sha256 = "sha256:" + "c" * 64
    counters = _install_worker_fakes(
        monkeypatch,
        repository,
        _settings("job_hash_divergent"),
    )

    assert asyncio.run(worker.run_once()) == 1
    _assert_zero_provider_capabilities(counters)
    status = repository.job_status(
        "job_hash_divergent", "tnt_synthetic_gate"
    )
    assert [item.code for item in status.diagnostics] == [
        "SYNTHETIC_AUTHORIZATION_ARTIFACT_HASH_MISMATCH"
    ]


def test_wrong_exact_claim_cannot_consume_another_jobs_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository("sqlite+pysqlite://")
    _seed_job(repository, "job_authorized_exact")
    _seed_job(repository, "job_wrong_claim")
    _authorization(repository, "job_authorized_exact")
    counters = _install_worker_fakes(
        monkeypatch,
        repository,
        _settings("job_wrong_claim"),
    )

    assert asyncio.run(worker.run_once()) == 1
    _assert_zero_provider_capabilities(counters)
    assert repository.job_status(
        "job_authorized_exact", "tnt_synthetic_gate"
    ).status == "QUEUED"
    wrong = repository.job_status("job_wrong_claim", "tnt_synthetic_gate")
    assert [item.code for item in wrong.diagnostics] == [
        "SYNTHETIC_AUTHORIZATION_REQUIRED"
    ]


def test_candidate_boundary_mismatch_has_zero_provider_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository("sqlite+pysqlite://")
    _seed_job(repository, "job_candidate_mismatch")
    _authorization(repository, "job_candidate_mismatch")
    counters = _install_worker_fakes(
        monkeypatch,
        repository,
        _settings("job_candidate_mismatch", candidate_sha="d" * 40),
    )

    assert asyncio.run(worker.run_once()) == 1
    _assert_zero_provider_capabilities(counters)
    status = repository.job_status(
        "job_candidate_mismatch", "tnt_synthetic_gate"
    )
    assert [item.code for item in status.diagnostics] == [
        "SYNTHETIC_AUTHORIZATION_BOUNDARY_MISMATCH"
    ]


def test_valid_attestation_is_consumed_before_key_and_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository("sqlite+pysqlite://")
    _seed_job(repository, "job_valid_attested")
    _authorization(repository, "job_valid_attested")
    settings = _settings("job_valid_attested")
    store = MemoryObjectStore(
        secret="synthetic-valid-object-store-secret-at-least-32-bytes"
    )
    counters = {"key_resolver": 0, "transport_construction": 0, "requests": 0}
    monkeypatch.setattr(worker, "get_worker_settings", lambda: settings)
    monkeypatch.setattr(
        worker,
        "build_worker_bootstrap_runtime",
        lambda _settings: SimpleNamespace(
            repository=repository,
            object_store=store,
        ),
    )

    def resolve_after_claim(resource: str) -> SecretStr:
        counters["key_resolver"] += 1
        assert resource == SECRET_RESOURCE
        with repository.session() as session:
            assert session.scalar(
                select(func.count()).select_from(SyntheticProviderClaimRow)
            ) == 1
        assert repository.job_status(
            "job_valid_attested", "tnt_synthetic_gate"
        ).status == "RUNNING"
        return SecretStr("synthetic-placeholder-never-sent")

    class FakeService:
        async def process_job(self, job_id: str) -> None:
            counters["requests"] += 1
            current = repository.job_status(job_id, "tnt_synthetic_gate")
            repository.save_job_status(
                current.model_copy(
                    update={
                        "status": "SUCCEEDED",
                        "progress": 1.0,
                        "finished_at": datetime.now(UTC),
                    }
                )
            )

    def construct_after_claim(
        _settings: WorkerSettings,
        **kwargs: object,
    ) -> object:
        counters["transport_construction"] += 1
        assert kwargs["provider_grant"] is not None
        assert isinstance(kwargs["api_key"], SecretStr)
        return SimpleNamespace(repository=repository, service=FakeService())

    monkeypatch.setattr(worker, "resolve_openai_api_key", resolve_after_claim)
    monkeypatch.setattr(worker, "build_worker_runtime", construct_after_claim)

    assert asyncio.run(worker.run_once()) == 0
    assert counters == {
        "key_resolver": 1,
        "transport_construction": 1,
        "requests": 1,
    }
    with repository.session() as session:
        assert session.scalar(
            select(func.count()).select_from(SyntheticProviderClaimRow)
        ) == 1

    # A consumed authorization and a terminal job cannot be reopened.
    assert asyncio.run(worker.run_once()) == 0
    assert counters == {
        "key_resolver": 1,
        "transport_construction": 1,
        "requests": 1,
    }


def test_authorization_claim_is_exactly_once_at_repository_boundary() -> None:
    repository = Repository("sqlite+pysqlite://")
    _seed_job(repository, "job_exactly_once_gate")
    _authorization(repository, "job_exactly_once_gate")
    assert repository.claim_job("job_exactly_once_gate") is not None
    kwargs = {
        "job_id": "job_exactly_once_gate",
        "candidate_sha": CANDIDATE_SHA,
        "boundary_hash": synthetic_provider_boundary_hash(),
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "model": LUNA_MODEL_ID,
        "secret_version_resource": SECRET_RESOURCE,
        "maximum_requests": 4,
        "maximum_cost_usd": 0.25,
    }
    grant = repository.consume_synthetic_provider_authorization(**kwargs)
    assert grant.job_id == "job_exactly_once_gate"
    with pytest.raises(Conflict, match="ALREADY_CONSUMED"):
        repository.consume_synthetic_provider_authorization(**kwargs)
