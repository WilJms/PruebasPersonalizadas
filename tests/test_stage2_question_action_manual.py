from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from comprehension_verification.canonical import canonical_hash, stable_id
from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import (
    LUNA_MODEL_ID,
    OPENAI_ROUTE_PROFILE_ID,
)
from comprehension_verification.model_gateway.mock_factory import (
    DeterministicMockAdapter,
)
from comprehension_verification.provider_authorization import (
    SyntheticProviderAuthorizationSpec,
    synthetic_provider_boundary_hash,
)
from comprehension_verification.web.app import create_app
from comprehension_verification.web.jobs import ManualJobRunner
from comprehension_verification.web.repository import (
    AssessmentPlanRow,
    AssessmentRow,
    Conflict,
    Repository,
)
from comprehension_verification.web.runtime import build_worker_runtime
from comprehension_verification.web.settings import Settings, WorkerSettings
from tests.test_stage2_web import (
    TENANT_ID,
    _app,
    _login,
    _mutating,
    _processed_submission,
    _verify_all_evidence,
)


def _manual_app(source_app):
    settings = Settings(
        environment="local",
        database_url="sqlite+pysqlite://",
        session_secret="stage2-manual-test-secret-with-sufficient-length",
        local_invited_emails=(
            "teacher@example.test,reviewer@example.test,assistant@example.test"
        ),
        model_mode="mock",
        job_runner_mode="manual",
        api_mutation_rate_limit_per_minute=500,
        api_read_rate_limit_per_minute=500,
    )
    return create_app(
        settings,
        repository=source_app.state.runtime.repository,
        object_store=source_app.state.runtime.object_store,
    )


def _seed_reviewable_submission():
    source_app = _app()
    with TestClient(source_app) as client:
        headers = _login(client)
        fixture = _processed_submission(
            client,
            headers,
            subject_ref=f"manual_regenerate_{uuid4().hex[:8]}",
        )
    return source_app, fixture


def _queue_regeneration(client: TestClient, headers: dict[str, str], fixture):
    question = fixture["review"]["assessment"]["questions"][0]
    return client.post(
        (
            f"/api/v1/assessments/{fixture['assessment_id']}/questions/"
            f"{question['question_id']}/actions"
        ),
        headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
        json={
            "action": "REGENERATE",
            "reason_code": "MANUAL_E2E_REPLACEMENT",
        },
    )


def test_manual_regeneration_is_queued_then_processed_by_exact_worker(
    monkeypatch,
) -> None:
    source_app, fixture = _seed_reviewable_submission()
    app = _manual_app(source_app)
    repository: Repository = app.state.runtime.repository
    model_calls_before = repository.model_calls(tenant_id=TENANT_ID)
    gateway_calls: list[str] = []

    async def forbidden_web_gateway(*_args, **_kwargs):
        gateway_calls.append("P07")
        raise AssertionError("manual web must not execute P07")

    monkeypatch.setattr(
        app.state.runtime.service, "_gateway_stage", forbidden_web_gateway
    )
    assert isinstance(app.state.runtime.job_runner, ManualJobRunner)

    with TestClient(app) as client:
        headers = _login(client)
        idempotency_key = str(uuid4())
        question = fixture["review"]["assessment"]["questions"][0]
        path = (
            f"/api/v1/assessments/{fixture['assessment_id']}/questions/"
            f"{question['question_id']}/actions"
        )
        queued = client.post(
            path,
            headers=_mutating(
                headers,
                idempotency_key=idempotency_key,
                **{"If-Match": fixture["etag"]},
            ),
            json={
                "action": "REGENERATE",
                "reason_code": "MANUAL_E2E_REPLACEMENT",
            },
        )
        assert queued.status_code == 200, queued.text
        body = queued.json()
        assert body["action_record"] is None
        assert body["job"]["status"] == "QUEUED"
        assert body["job"]["stage"] == "QUESTION_GENERATE"
        assert body["job"]["attempt"] == 0
        assert body["job"]["progress"] == 0.0
        job_id = body["job"]["job_id"]
        job = repository.job_control(job_id, TENANT_ID)
        assert job.kind == "QUESTION_ACTION"
        assert job.status == "QUEUED"
        assert job.descriptor is not None
        assert job.descriptor["assessment_id"] == fixture["assessment_id"]
        descriptor = repository.question_action_descriptor(
            job_id=job_id, tenant_id=TENANT_ID
        )
        assert descriptor is not None and descriptor.output is not None
        assert descriptor.output["action"]["question_id"] == question["question_id"]
        assert gateway_calls == []
        assert repository.model_calls(tenant_id=TENANT_ID) == model_calls_before
        assert [
            run.stage
            for run in repository.stage_runs_for_job(job_id, TENANT_ID)
        ] == ["QUESTION_ACTION_DESCRIPTOR"]
        assert repository.question_review_actions(
            tenant_id=TENANT_ID,
            assessment_id=fixture["assessment_id"],
            question_id=question["question_id"],
        ) == []
        before_worker = client.get(
            f"/api/v1/submissions/{fixture['submission_id']}/assessment"
        )
        assert before_worker.status_code == 200, before_worker.text
        assert before_worker.json()["assessment_version"] == 1
        assert before_worker.json()["assessment"]["questions"][0] == question

        replay = client.post(
            path,
            headers=_mutating(
                headers,
                idempotency_key=idempotency_key,
                **{"If-Match": fixture["etag"]},
            ),
            json={
                "action": "REGENERATE",
                "reason_code": "MANUAL_E2E_REPLACEMENT",
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert replay.json()["job"]["job_id"] == job_id
        assert replay.json()["job"]["status"] == "QUEUED"

        history = client.get(path)
        assert history.status_code == 200, history.text
        assert history.json()["items"] == []
        assert [item["job_id"] for item in history.json()["jobs"]] == [job_id]

        incompatible = client.post(
            path,
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={"action": "ACCEPT"},
        )
        assert incompatible.status_code == 409, incompatible.text
        assert incompatible.json()["code"] == "QUESTION_ACTION_PENDING"

        approval = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={},
        )
        assert approval.status_code == 409, approval.text
        assert approval.json()["code"] == "QUESTION_ACTION_PENDING"

        claimed = repository.claim_job(job_id, lease_seconds=300)
        assert claimed is not None and claimed.id == job_id
        worker = build_worker_runtime(
            WorkerSettings(
                environment="test",
                database_url="sqlite+pysqlite://",
                model_mode="mock",
                claim_job_id=job_id,
            ),
            repository=repository,
            object_store=app.state.runtime.object_store,
        )
        asyncio.run(worker.service.process_job(job_id))

        completed = repository.job_status(job_id, TENANT_ID)
        assert completed.status == "SUCCEEDED"
        p07_calls = [
            call
            for call in repository.model_calls(tenant_id=TENANT_ID, job_id=job_id)
            if call["prompt_id"] == "P07_QUESTION_BUILD_V1"
        ]
        assert len(p07_calls) == 1
        refreshed = client.get(
            f"/api/v1/submissions/{fixture['submission_id']}/assessment"
        )
        assert refreshed.status_code == 200, refreshed.text
        refreshed_body = refreshed.json()
        assert refreshed_body["assessment_version"] == 2
        assert refreshed_body["assessment"]["question_count"] == 1
        assert len(refreshed_body["assessment"]["questions"]) == 1
        replacement = refreshed_body["assessment"]["questions"][0]
        assert replacement["question_id"] == question["question_id"]
        assert replacement["opportunity_id"] != question["opportunity_id"]

        refreshed_history = client.get(path)
        assert refreshed_history.status_code == 200
        assert refreshed_history.json()["jobs"] == []
        applied = m.QuestionReviewActionRecord.model_validate(
            refreshed_history.json()["items"][0]
        )
        assert applied.status == m.QuestionReviewRecordStatus.APPLIED

        completed_fixture = {
            **fixture,
            "review": refreshed_body,
            "etag": refreshed.headers["etag"],
        }
        _verify_all_evidence(client, headers, completed_fixture)
        approved = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(
                headers, **{"If-Match": refreshed.headers["etag"]}
            ),
            json={},
        )
        assert approved.status_code == 200, approved.text
        guide_job_id = approved.json()["guide_job_id"]
        assert guide_job_id
        guide_job = repository.job_control(guide_job_id, TENANT_ID)
        assert guide_job.kind == "GUIDE_BUILD"
        assert guide_job.status == "QUEUED"


def test_question_action_authorization_binds_derived_inputs() -> None:
    source_app, fixture = _seed_reviewable_submission()
    app = _manual_app(source_app)
    repository: Repository = app.state.runtime.repository
    with TestClient(app) as client:
        headers = _login(client)
        queued = _queue_regeneration(client, headers, fixture)
        assert queued.status_code == 200, queued.text
        job_id = queued.json()["job"]["job_id"]

    hashes = repository.synthetic_artifact_hashes_for_job(job_id)
    raw_hashes = {
        fixture["artifact"]["sha256"],
    }
    assert raw_hashes.issubset(set(hashes))
    assert len(hashes) > len(raw_hashes)
    job = repository.job_control(job_id, TENANT_ID)
    spec = SyntheticProviderAuthorizationSpec(
        authorization_id="auth_question_action_derived_inputs",
        tenant_id=TENANT_ID,
        job_id=job_id,
        job_kind="QUESTION_ACTION",
        aggregate_id=job.aggregate_id,
        expected_claim_attempt=1,
        artifact_hashes=hashes,
        candidate_sha="a" * 40,
        boundary_hash=synthetic_provider_boundary_hash(),
        route_profile=OPENAI_ROUTE_PROFILE_ID,
        model=LUNA_MODEL_ID,
        secret_version_resource=(
            "projects/project-stage2/secrets/cva-openai-api-key/versions/2"
        ),
        max_requests=2,
        max_cost_usd=0.25,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        created_by="operator_question_action_test",
    )
    repository.authorize_synthetic_provider_job(spec)
    with repository.session() as session:
        plan = session.get(AssessmentPlanRow, fixture["submission_id"])
        assert plan is not None
        plan.data = {**plan.data, "tampered_after_authorization": True}
    assert repository.claim_job(job_id, lease_seconds=300) is not None
    with pytest.raises(Conflict, match="SYNTHETIC_AUTHORIZATION_ARTIFACT_HASH_MISMATCH"):
        repository.consume_synthetic_provider_authorization(
            job_id=job_id,
            candidate_sha="a" * 40,
            boundary_hash=synthetic_provider_boundary_hash(),
            route_profile=OPENAI_ROUTE_PROFILE_ID,
            model=LUNA_MODEL_ID,
            secret_version_resource=(
                "projects/project-stage2/secrets/cva-openai-api-key/versions/2"
            ),
            maximum_requests=2,
            maximum_cost_usd=0.25,
        )


def test_real_question_action_boundary_accepts_exact_derived_attestation() -> None:
    source_app, fixture = _seed_reviewable_submission()
    app = _manual_app(source_app)
    repository: Repository = app.state.runtime.repository
    with TestClient(app) as client:
        headers = _login(client)
        queued = _queue_regeneration(client, headers, fixture)
        assert queued.status_code == 200, queued.text
        job_id = queued.json()["job"]["job_id"]

    hashes = repository.synthetic_artifact_hashes_for_job(job_id)
    job = repository.job_control(job_id, TENANT_ID)
    secret_resource = (
        "projects/project-stage2/secrets/cva-openai-api-key/versions/2"
    )
    repository.authorize_synthetic_provider_job(
        SyntheticProviderAuthorizationSpec(
            authorization_id="auth_question_action_exact_attestation",
            tenant_id=TENANT_ID,
            job_id=job_id,
            job_kind="QUESTION_ACTION",
            aggregate_id=job.aggregate_id,
            expected_claim_attempt=1,
            artifact_hashes=hashes,
            candidate_sha="b" * 40,
            boundary_hash=synthetic_provider_boundary_hash(),
            route_profile=OPENAI_ROUTE_PROFILE_ID,
            model=LUNA_MODEL_ID,
            secret_version_resource=secret_resource,
            max_requests=1,
            max_cost_usd=0.25,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            created_by="operator_question_action_exact_test",
        )
    )
    claimed = repository.claim_job(job_id, lease_seconds=300)
    assert claimed is not None
    grant = repository.consume_synthetic_provider_authorization(
        job_id=job_id,
        candidate_sha="b" * 40,
        boundary_hash=synthetic_provider_boundary_hash(),
        route_profile=OPENAI_ROUTE_PROFILE_ID,
        model=LUNA_MODEL_ID,
        secret_version_resource=secret_resource,
        maximum_requests=1,
        maximum_cost_usd=0.25,
    )
    provider_calls: list[str] = []

    class FakeRealAdapter:
        def __init__(self, *, api_key, config) -> None:
            assert isinstance(api_key, SecretStr)
            self.config = config
            self.inner = DeterministicMockAdapter()

        async def invoke(self, **kwargs):
            provider_calls.append(str(kwargs["prompt_id"]))
            return await self.inner.invoke(**kwargs)

    settings = WorkerSettings(
        environment="test",
        database_url="sqlite+pysqlite://",
        model_mode="real",
        claim_job_id=job_id,
        openai_secret_version_resource=secret_resource,
        synthetic_evaluation_candidate_sha="b" * 40,
        synthetic_evaluation_max_requests=1,
        max_job_cost_usd=0.25,
    )
    worker = build_worker_runtime(
        settings,
        repository=repository,
        object_store=app.state.runtime.object_store,
        provider_grant=grant,
        api_key=SecretStr("sk-project-synthetic-placeholder-not-a-real-key"),
        openai_adapter_factory=FakeRealAdapter,
    )
    asyncio.run(worker.service.process_job(job_id))
    assert repository.job_status(job_id, TENANT_ID).status == "SUCCEEDED"
    assert provider_calls == ["P07_QUESTION_BUILD_V1"]


def test_question_action_worker_fails_closed_on_assessment_version_change() -> None:
    source_app, fixture = _seed_reviewable_submission()
    app = _manual_app(source_app)
    repository: Repository = app.state.runtime.repository
    with TestClient(app) as client:
        headers = _login(client)
        queued = _queue_regeneration(client, headers, fixture)
        assert queued.status_code == 200, queued.text
        job_id = queued.json()["job"]["job_id"]

    current = repository.assessment_by_id(fixture["assessment_id"], TENANT_ID)
    changed = m.Assessment.model_validate(current.data).model_copy(
        update={"created_at": datetime.now(UTC)}
    )
    repository.add(
        AssessmentRow(
            row_id=stable_id("assessmentrow", changed.assessment_id, 2),
            assessment_id=changed.assessment_id,
            tenant_id=TENANT_ID,
            submission_id=changed.submission_id,
            version=2,
            status=changed.status.value,
            etag=f'"{canonical_hash(changed)}"',
            data=changed.model_dump(mode="json"),
        )
    )
    assert repository.claim_job(job_id, lease_seconds=300) is not None
    worker = build_worker_runtime(
        WorkerSettings(
            environment="test",
            database_url="sqlite+pysqlite://",
            model_mode="mock",
            claim_job_id=job_id,
        ),
        repository=repository,
        object_store=app.state.runtime.object_store,
    )
    asyncio.run(worker.service.process_job(job_id))
    failed = repository.job_status(job_id, TENANT_ID)
    assert failed.status == "FAILED"
    assert [item.code for item in failed.diagnostics] == [
        "QUESTION_ACTION_VERSION_CHANGED"
    ]
    assert repository.model_calls(tenant_id=TENANT_ID, job_id=job_id) == []
    assert repository.question_review_actions(
        tenant_id=TENANT_ID,
        assessment_id=fixture["assessment_id"],
    ) == []
