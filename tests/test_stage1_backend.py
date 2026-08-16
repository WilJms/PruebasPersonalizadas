from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import cast

import pytest
from pydantic import ValidationError

from comprehension_verification.canonical import sha256_bytes
from comprehension_verification.contracts import models as m
from comprehension_verification.diagnostics import diagnostic
from comprehension_verification.model_gateway import (
    AdapterResult,
    DeterministicMockAdapter,
    GatewayConfig,
    GatewayMode,
    MockBehavior,
    ModelGateway,
)
from comprehension_verification.rehearsal import (
    BASE_SCENARIO_ID,
    build_rehearsal_checkpoints,
)
from comprehension_verification.validation import build_blueprint_review_preflight
from comprehension_verification.web.auth import Actor
from comprehension_verification.web.jobs import RecordingJobRunner
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import (
    ArtifactRow,
    ActivityRow,
    ActivitySpecRow,
    Conflict,
    JobRow,
    NotFound,
    Repository,
    SubmissionRow,
    utc_now,
)
from comprehension_verification.web.settings import Settings
from comprehension_verification.web.workflows import (
    Stage1Service,
    WorkflowError,
    _blueprint_review_descriptor_component_version,
    _blueprint_review_descriptor_policy_hash,
)


def _settings(**updates: object) -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        session_secret="backend-stage1-test-secret-with-32-bytes",
        model_mode="mock",
        **updates,
    )


def _actor(workspace_id: str = "tnt_backend") -> Actor:
    return Actor(
        user_id="usr_backend",
        email="teacher@example.test",
        workspace_id=workspace_id,
        role="TEACHER",
        can_approve_assessments=True,
        csrf_token="csrf_backend",
    )


def _config(tenant_id: str = "tnt_backend") -> m.ActivityConfig:
    return m.ActivityConfig(
        activity_id="act_backend",
        tenant_id=tenant_id,
        title="Actividad backend sintética",
        output_language="es-CL",
        context_mode=m.ContextMode.CLOSED,
        assessment_modality=m.AssessmentModality.WRITTEN,
        question_count=1,
        target_total_minutes=3,
        structured_justification_mode=m.StructuredJustificationMode.NOT_REQUIRED,
        allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
        allowed_artifact_media_types=["text/markdown"],
    )


def _upload_bytes(
    service: Stage1Service,
    store: MemoryObjectStore,
    actor: Actor,
    *,
    role: m.ArtifactRole,
    content: bytes,
    submission_id: str | None = None,
) -> ArtifactRow:
    row, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        submission_id=submission_id,
        filename=f"{role.value.lower()}.md",
        media_type="text/markdown",
        expected_byte_size=len(content),
        role=role,
    )
    store.put_signed(
        upload["upload_url"].rsplit("/", 1)[-1], content, "text/markdown"
    )
    service.complete_upload(row.id, actor)
    completed = service.repository.scoped(ArtifactRow, row.id, actor.workspace_id)
    assert isinstance(completed, ArtifactRow)
    return completed


def test_cloud_settings_fail_closed_without_managed_adapters_and_secrets() -> None:
    with pytest.raises(ValidationError, match="Supabase authentication"):
        Settings(environment="cloud")
    with pytest.raises(ValidationError, match="managed session secret"):
        Settings(
            environment="cloud",
            auth_mode="supabase",
            object_store_mode="r2",
            job_runner_mode="cloud_run",
            supabase_jwt_issuer="https://example.supabase.co/auth/v1",
            supabase_jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
            r2_endpoint_url="https://example.r2.cloudflarestorage.com",
            r2_bucket="private-fixtures",
            r2_access_key_id="scoped-access-key",
            r2_secret_access_key="scoped-secret-key",
            gcp_project_id="example-project",
            gcp_region="us-central1",
            cloud_run_job_name="cva-worker",
        )
    with pytest.raises(ValidationError, match="P10 is disabled"):
        Settings(p10_enabled=True)


def test_signed_memory_object_capability_enforces_method_and_content_type() -> None:
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes",
        upload_ttl_seconds=600,
        download_ttl_seconds=600,
    )
    upload = store.sign_put("raw/tnt/act/art", "text/plain")
    token = upload.url.rsplit("/", 1)[-1]
    with pytest.raises(PermissionError, match="content type"):
        store.put_signed(token, b"content", "text/markdown")
    store.put_signed(token, b"content", "text/plain")
    assert store.head("raw/tnt/act/art").byte_size == 7
    with pytest.raises(PermissionError, match="method"):
        store.get_signed(token)
    download = store.sign_get("raw/tnt/act/art")
    data, media_type = store.get_signed(download.url.rsplit("/", 1)[-1])
    assert data == b"content"
    assert media_type == "text/plain"


def test_historical_p08_audit_is_idempotent_and_content_free() -> None:
    repo = Repository("sqlite+pysqlite://")
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=MemoryObjectStore(
            secret="object-test-secret-with-at-least-thirty-two-bytes"
        ),
        job_runner=RecordingJobRunner(),
    )
    checkpoint = build_rehearsal_checkpoints(BASE_SCENARIO_ID)
    output = DeterministicMockAdapter().factory.output_for(
        "P08_QUESTION_REVIEW_V1",
        checkpoint.p08_request,
        MockBehavior.HAPPY,
    )
    job = JobRow(
        id="job_p08_audit",
        tenant_id="tnt_backend",
        kind="SUBMISSION",
        aggregate_id="sub_p08_audit",
        stage="P08_QUESTION_REVIEW_V1",
        status="RUNNING",
    )

    for _ in range(2):
        service._record_p08_observability(
            job=job,
            stage="P08_QUESTION_REVIEW_V1:question_1",
            request=checkpoint.p08_request,
            output=output,
        )

    events = repo.audit_events(
        tenant_id=job.tenant_id,
        event_type="question.review.decision_observed",
        aggregate_id=job.id,
    )
    assert len(events) == 1
    payload = events[0].payload
    diagnostics = payload["decision_diagnostics"]
    assert diagnostics["decision"] == "ACCEPT"
    assert diagnostics["diagnostic_codes"] == ["P08_DECISION_ACCEPT"]
    assert diagnostics["score_thresholds"]["groundedness"] == {
        "score": 0.98,
        "threshold": 0.9,
        "relation": "AT_OR_ABOVE",
    }
    serialized = str(payload)
    assert "question_text" not in serialized
    assert "content_text" not in serialized
    assert "critical_failure_codes" not in serialized


def test_job_is_durable_before_dispatch_and_cross_workspace_is_hidden() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(secret="object-test-secret-with-at-least-thirty-two-bytes")
    actor = _actor()
    persisted: list[str] = []

    def assert_persisted(job_id: str) -> None:
        row = repo.get(JobRow, job_id)
        assert isinstance(row, JobRow)
        assert row.status == "QUEUED"
        persisted.append(job_id)

    runner = RecordingJobRunner(assert_persisted=assert_persisted)
    service = Stage1Service(
        settings=_settings(), repository=repo, object_store=store, job_runner=runner
    )
    service.create_activity(_config(), actor)
    artifact, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=len(content := b"# Consigna\n\nExplique una decision localizada y su consecuencia.\n"),
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    store.put_signed(
        upload["upload_url"].rsplit("/", 1)[-1], content, "text/markdown"
    )
    completed = service.complete_upload(artifact.id, actor)
    assert completed.sha256 == sha256_bytes(content)
    status = asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    assert persisted == [status.job_id]
    assert runner.dispatched == [status.job_id]

    with pytest.raises(Exception, match="not found"):
        service.create_upload(
            actor=_actor("tnt_other"),
            activity_id="act_backend",
            filename="stolen.md",
            media_type="text/markdown",
            expected_byte_size=16,
            role=m.ArtifactRole.RUBRIC,
        )


def test_dispatch_failure_is_persisted_without_exposing_adapter_exception() -> None:
    class FailingRunner:
        async def dispatch(self, _job_id: str) -> None:
            raise RuntimeError("provider response containing sensitive detail")

    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(secret="object-test-secret-with-at-least-thirty-two-bytes")
    actor = _actor()
    service = Stage1Service(
        settings=_settings(), repository=repo, object_store=store, job_runner=FailingRunner()
    )
    service.create_activity(_config(), actor)
    artifact, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=len(content := b"# Consigna\n\nExplique un mecanismo.\n"),
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    store.put_signed(
        upload["upload_url"].rsplit("/", 1)[-1],
        content,
        "text/markdown",
    )
    service.complete_upload(artifact.id, actor)
    status = asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    assert status.status == "FAILED"
    assert [item.code for item in status.diagnostics] == ["JOB_DISPATCH_FAILED"]
    assert "sensitive" not in status.diagnostics[0].message


def test_duplicate_pending_role_and_unapproved_submission_fail_closed() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(secret="object-test-secret-with-at-least-thirty-two-bytes")
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    with pytest.raises(WorkflowError, match="not enabled for this activity"):
        service.create_upload(
            actor=actor,
            activity_id="act_backend",
            filename="assignment.pdf",
            media_type="application/pdf",
            expected_byte_size=64,
            role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        )
    service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=64,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    with pytest.raises(WorkflowError, match="one artifact") as duplicate:
        service.create_upload(
            actor=actor,
            activity_id="act_backend",
            filename="assignment-second.md",
            media_type="text/markdown",
            expected_byte_size=64,
            role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        )
    assert duplicate.value.status_code == 409

    submission = service.create_submission(
        activity_id="act_backend", subject_ref="subject_backend", actor=actor
    )
    with pytest.raises(WorkflowError, match="approved blueprint") as unapproved:
        asyncio.run(service.enqueue_submission_pipeline(submission.id, actor))
    assert unapproved.value.code == "BLUEPRINT_NOT_APPROVED"
    assert unapproved.value.status_code == 409


def test_repository_stage_key_reuses_only_identical_versioned_inputs() -> None:
    repo = Repository("sqlite+pysqlite://")
    first, reused_first = repo.save_stage(
        job_id="job_first",
        tenant_id="tnt_backend",
        stage="P01_ACTIVITY_SPEC_V1",
        inputs={"activity_id": "act_backend"},
        component_version="1.1.0",
        policy_hash="sha256:" + "a" * 64,
        output={"status": "READY"},
    )
    second, reused_second = repo.save_stage(
        job_id="job_second",
        tenant_id="tnt_backend",
        stage="P01_ACTIVITY_SPEC_V1",
        inputs={"activity_id": "act_backend"},
        component_version="1.1.0",
        policy_hash="sha256:" + "a" * 64,
        output={"status": "READY"},
    )
    third, reused_third = repo.save_stage(
        job_id="job_third",
        tenant_id="tnt_backend",
        stage="P01_ACTIVITY_SPEC_V1",
        inputs={"activity_id": "act_backend"},
        component_version="1.1.1",
        policy_hash="sha256:" + "a" * 64,
        output={"status": "READY"},
    )
    assert not reused_first
    assert reused_second and second.id == first.id
    assert not reused_third and third.stage_key != first.stage_key
    cross_tenant, reused_cross_tenant = repo.save_stage(
        job_id="job_other_tenant",
        tenant_id="tnt_other",
        stage="P01_ACTIVITY_SPEC_V1",
        inputs={"activity_id": "act_backend"},
        component_version="1.1.0",
        policy_hash="sha256:" + "a" * 64,
        output={"status": "READY"},
    )
    assert not reused_cross_tenant
    assert cross_tenant.stage_key != first.stage_key


def test_idempotency_reservation_is_fail_closed_until_completed() -> None:
    repo = Repository("sqlite+pysqlite://")
    fingerprint = "sha256:" + "f" * 64
    assert repo.reserve_idempotency("tnt_backend", "key-1", fingerprint) is None
    with pytest.raises(Conflict, match="IDEMPOTENCY_REQUEST_IN_PROGRESS"):
        repo.reserve_idempotency("tnt_backend", "key-1", fingerprint)
    descriptor = {
        "kind": "json",
        "status_code": 201,
        "body": {"id": "one"},
    }
    repo.complete_idempotency("tnt_backend", "key-1", fingerprint, descriptor)
    assert repo.reserve_idempotency(
        "tnt_backend", "key-1", fingerprint
    ) == descriptor
    with pytest.raises(Conflict, match="IDEMPOTENCY_KEY_REUSED"):
        repo.reserve_idempotency(
            "tnt_backend", "key-1", "sha256:" + "0" * 64
        )

    unsafe_key = "key-with-transient-capability"
    assert repo.reserve_idempotency("tnt_backend", unsafe_key, fingerprint) is None
    with pytest.raises(
        ValueError, match="IDEMPOTENCY_RESPONSE_CONTAINS_TRANSIENT_CAPABILITY"
    ):
        repo.complete_idempotency(
            "tnt_backend",
            unsafe_key,
            fingerprint,
            {
                "kind": "json",
                "body": {
                    "capability": "https://example.invalid/?X-Amz-Signature=redacted"
                },
            },
        )
    repo.release_idempotency("tnt_backend", unsafe_key, fingerprint)
    assert repo.reserve_idempotency("tnt_backend", unsafe_key, fingerprint) is None


def test_completed_idempotency_expires_but_inflight_reservations_never_reclaim() -> None:
    repo = Repository("sqlite+pysqlite://")
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    fingerprint = "sha256:" + "a" * 64
    replacement = "sha256:" + "b" * 64
    descriptor = {"kind": "activity", "activity_id": "act_reference"}

    assert repo.reserve_idempotency(
        "tnt_backend", "expiring-key", fingerprint, ttl_seconds=300, now=now
    ) is None
    repo.complete_idempotency(
        "tnt_backend",
        "expiring-key",
        fingerprint,
        descriptor,
        ttl_seconds=300,
        now=now,
    )
    assert repo.reserve_idempotency(
        "tnt_backend",
        "expiring-key",
        fingerprint,
        ttl_seconds=300,
        now=now + timedelta(seconds=299),
    ) == descriptor
    assert repo.reserve_idempotency(
        "tnt_backend",
        "expiring-key",
        replacement,
        ttl_seconds=300,
        now=now + timedelta(seconds=300),
    ) is None

    assert repo.reserve_idempotency(
        "tnt_backend", "inflight-key", fingerprint, ttl_seconds=300, now=now
    ) is None
    with pytest.raises(Conflict, match="IDEMPOTENCY_REQUEST_IN_PROGRESS"):
        repo.reserve_idempotency(
            "tnt_backend",
            "inflight-key",
            fingerprint,
            ttl_seconds=300,
            now=now + timedelta(days=1),
        )
def test_activity_pipeline_stops_on_non_ready_p01_without_blueprint() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    content = b"# Consigna\n\nTexto insuficiente para el caso fail-closed.\n"
    artifact, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=len(content),
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    store.put_signed(
        upload["upload_url"].rsplit("/", 1)[-1], content, "text/markdown"
    )
    service.complete_upload(artifact.id, actor)

    async def abstaining_p01(job, prompt_id, request, output_model, *, cache_suffix=""):
        assert prompt_id == "P01_ACTIVITY_SPEC_V1"
        return m.ActivitySpec(
            activity_id=request.activity_config.activity_id,
            status=m.WorkflowStatus.NEEDS_REVIEW,
            diagnostics=[
                diagnostic(
                    "ASSIGNMENT_FIELD_MISSING",
                    "La consigna no permite extraer campos obligatorios.",
                )
            ],
        )

    service._gateway_stage = abstaining_p01
    queued = asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    asyncio.run(service.process_job(queued.job_id))
    stopped = repo.job_status(queued.job_id, actor.workspace_id)
    assert stopped.status == "NEEDS_REVIEW"
    assert [item.code for item in stopped.diagnostics] == [
        "ASSIGNMENT_FIELD_MISSING"
    ]
    activity = repo.scoped(ActivityRow, "act_backend", actor.workspace_id)
    assert isinstance(activity, ActivityRow)
    assert activity.status == "NEEDS_REVIEW"
    with pytest.raises(NotFound):
        repo.latest_blueprint("act_backend", actor.workspace_id)


def test_deterministic_blueprint_preflight_persists_failure_and_blocks_approval() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    _upload_bytes(
        service,
        store,
        actor,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        content=b"# Consigna\n\nExplique una decision y su consecuencia local.\n",
    )
    gateway_stage = service._gateway_stage

    async def infeasible_p04(
        job, prompt_id, request, output_model, *, cache_suffix=""
    ):
        output = await gateway_stage(
            job, prompt_id, request, output_model, cache_suffix=cache_suffix
        )
        if prompt_id != "P04_BLUEPRINT_BUILD_V1":
            return output
        return output.model_copy(
            update={
                "assessment_constraints": output.assessment_constraints.model_copy(
                    update={"question_count": 2}
                )
            }
        )

    service._gateway_stage = infeasible_p04
    queued = asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    asyncio.run(service.process_job(queued.job_id))

    terminal = repo.job_status(queued.job_id, actor.workspace_id)
    assert terminal.status == "NEEDS_REVIEW"
    assert terminal.stage == "BLUEPRINT_PREFLIGHT"
    row = repo.latest_blueprint("act_backend", actor.workspace_id)
    blueprint = m.AssessmentBlueprint.model_validate(row.data)
    preflight = m.BlueprintReviewPreflight.model_validate(row.preflight)
    assert blueprint.status == m.WorkflowStatus.NEEDS_REVIEW
    assert not preflight.policy_constraints_match
    assert not preflight.catalog_plan_feasible
    assert blueprint.diagnostics[0].details["diagnostic_source"] == (
        "DETERMINISTIC_BLUEPRINT_PREFLIGHT"
    )
    assert "P05_BLUEPRINT_REVIEW_V1" not in {
        item["prompt_id"]
        for item in repo.model_calls(
            tenant_id=actor.workspace_id, job_id=queued.job_id
        )
    }
    with pytest.raises(WorkflowError) as blocked:
        service.approve_blueprint(
            activity_id="act_backend",
            version=row.version,
            if_match=row.etag,
            actor=actor,
        )
    assert blocked.value.code == "BLUEPRINT_NOT_REVIEWABLE"


def test_product_gateway_rejects_p05_before_constructing_any_gateway() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )

    def forbidden_gateway(_job_id: str) -> ModelGateway:
        raise AssertionError("P05 must be rejected before gateway construction")

    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        gateway_factory=forbidden_gateway,
    )
    job = JobRow(
        id="job_p05_runtime_forbidden",
        tenant_id="tnt_backend",
        kind="ACTIVITY",
        aggregate_id="act_backend",
        stage="BLUEPRINT_REVIEW",
        status="RUNNING",
        progress=0.8,
        attempt=1,
        diagnostics=[],
    )
    request = build_rehearsal_checkpoints().p05_request
    with pytest.raises(WorkflowError) as blocked:
        asyncio.run(
            service._gateway_stage(
                job,
                "P05_BLUEPRINT_REVIEW_V1",
                request,
                m.BlueprintReview,
            )
        )
    assert blocked.value.code == "P05_ACTIVE_RUNTIME_RETIRED"
    assert repo.model_calls(tenant_id="tnt_backend") == []


def test_product_gateway_rejects_p08_before_constructing_any_transport() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    transport_constructed = False

    def forbidden_gateway(_job_id: str) -> ModelGateway:
        nonlocal transport_constructed
        transport_constructed = True
        raise AssertionError("P08 must be rejected before gateway construction")

    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        gateway_factory=forbidden_gateway,
    )
    job = JobRow(
        id="job_p08_runtime_forbidden",
        tenant_id="tnt_backend",
        kind="SUBMISSION",
        aggregate_id="sub_backend",
        stage="QUESTION_VALIDATE",
        status="RUNNING",
        progress=0.55,
        attempt=1,
        diagnostics=[],
    )
    request = build_rehearsal_checkpoints().p08_request
    with pytest.raises(WorkflowError) as blocked:
        asyncio.run(
            service._gateway_stage(
                job,
                "P08_QUESTION_REVIEW_V1",
                request,
                m.QuestionReviewResult,
            )
        )
    assert blocked.value.code == "P08_ACTIVE_RUNTIME_RETIRED"
    assert transport_constructed is False
    assert repo.model_calls(tenant_id="tnt_backend") == []
    assert repo.stage_runs_for_job(job.id, job.tenant_id) == []


def test_activity_waiting_for_legacy_p05_resumes_at_preflight_without_provider() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    _upload_bytes(
        service,
        store,
        actor,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        content=b"# Consigna\n\nExplique una decision y su consecuencia local.\n",
    )
    queued = asyncio.run(
        service.enqueue_activity_pipeline("act_backend", actor)
    )
    deterministic_preflight = service._blueprint_preflight_stage

    def crash_after_p04(**_kwargs):
        raise TimeoutError("simulated cutover crash after durable P04")

    service._blueprint_preflight_stage = crash_after_p04
    asyncio.run(service.process_job(queued.job_id))
    service._blueprint_preflight_stage = deterministic_preflight

    failed = repo.job_status(queued.job_id, actor.workspace_id)
    assert failed.status == "FAILED"
    assert failed.stage == "BLUEPRINT_PREFLIGHT"
    failed_row = repo.scoped(JobRow, queued.job_id, actor.workspace_id)
    assert isinstance(failed_row, JobRow)
    assert failed_row.failure_class == m.FailureClass.TRANSIENT
    assert {
        item["prompt_id"]
        for item in repo.model_calls(
            tenant_id=actor.workspace_id, job_id=queued.job_id
        )
    } == {
        "P01_ACTIVITY_SPEC_V1",
        "P03_AMBIGUITY_TRIAGE_V1",
        "P04_BLUEPRINT_BUILD_V1",
    }

    resumed = repo.schedule_job_retry(
        job_id=queued.job_id,
        tenant_id=actor.workspace_id,
        resulting_job_id="job_activity_legacy_p05_resume",
        control_id="control_activity_legacy_p05_resume",
        actor_id=actor.user_id,
        reason_code="PHASE3_RUNTIME_CUTOVER",
        failure_class="TRANSIENT",
        next_attempt_at=utc_now(),
        resume_from_stage="BLUEPRINT_REVIEW",
    )
    assert resumed.kind == "ACTIVITY"
    asyncio.run(service.process_job(resumed.id))

    terminal = repo.job_status(resumed.id, actor.workspace_id)
    assert terminal.status == "SUCCEEDED"
    assert terminal.stage == "BLUEPRINT_PREFLIGHT"
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=resumed.id
    ) == []
    blueprint = repo.latest_blueprint("act_backend", actor.workspace_id)
    assert blueprint.review is None
    assert m.BlueprintReviewPreflight.model_validate(
        blueprint.preflight
    ).catalog_plan_feasible
    assert repo.has_audit_event(
        tenant_id=actor.workspace_id,
        event_type="stage.reused",
        aggregate_id=resumed.id,
        payload_contains={"stage": "P04_BLUEPRINT_BUILD_V1"},
    )


def test_submission_pipeline_does_not_persist_assessment_when_p09_is_not_ready() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    assignment = b"# Consigna\n\nExplique una decision y su consecuencia local.\n"
    assignment_row, assignment_upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=len(assignment),
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    store.put_signed(
        assignment_upload["upload_url"].rsplit("/", 1)[-1],
        assignment,
        "text/markdown",
    )
    service.complete_upload(assignment_row.id, actor)
    activity_job = asyncio.run(
        service.enqueue_activity_pipeline("act_backend", actor)
    )
    asyncio.run(service.process_job(activity_job.job_id))
    blueprint = repo.latest_blueprint("act_backend", actor.workspace_id)
    service.approve_blueprint(
        activity_id="act_backend",
        version=blueprint.version,
        if_match=blueprint.etag,
        actor=actor,
    )

    submission = service.create_submission(
        activity_id="act_backend", subject_ref="subject_p09", actor=actor
    )
    deliverable = (
        b"# Entrega\n\nLa deduplicacion ocurre antes del promedio para evitar doble peso.\n"
    )
    artifact, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        submission_id=submission.id,
        filename="submission.md",
        media_type="text/markdown",
        expected_byte_size=len(deliverable),
        role=m.ArtifactRole.SUBMISSION,
    )
    store.put_signed(
        upload["upload_url"].rsplit("/", 1)[-1],
        deliverable,
        "text/markdown",
    )
    service.complete_upload(artifact.id, actor)
    original_gateway_stage = service._gateway_stage

    async def p09_needs_review(
        job, prompt_id, request, output_model, *, cache_suffix=""
    ):
        if prompt_id == "P09_GUIDE_BUILD_V1":
            return m.EvaluationGuide(
                guide_id=request.guide_id,
                assessment_id=request.assessment.assessment_id,
                submission_id=request.assessment.submission_id,
                status="NEEDS_REVIEW",
                items=[],
                diagnostics=[
                    diagnostic(
                        "GUIDE_UNSUPPORTED",
                        "La guía requiere revisión humana y no es utilizable.",
                    )
                ],
                created_at=utc_now(),
            )
        return await original_gateway_stage(
            job,
            prompt_id,
            request,
            output_model,
            cache_suffix=cache_suffix,
        )

    service._gateway_stage = p09_needs_review
    submission_job = asyncio.run(
        service.enqueue_submission_pipeline(submission.id, actor)
    )
    asyncio.run(service.process_job(submission_job.job_id))
    stopped = repo.job_status(submission_job.job_id, actor.workspace_id)
    assert stopped.status == "NEEDS_REVIEW"
    assert [item.code for item in stopped.diagnostics] == ["GUIDE_UNSUPPORTED"]
    persisted_submission = repo.scoped(
        SubmissionRow, submission.id, actor.workspace_id
    )
    assert isinstance(persisted_submission, SubmissionRow)
    state = m.SubmissionProcessingState.model_validate(persisted_submission.state)
    assert state.status == m.SubmissionProcessingStatus.NEEDS_REVIEW
    assert state.current_stage == "GUIDE_BUILD"
    with pytest.raises(NotFound):
        repo.latest_assessment(submission.id, actor.workspace_id)


def test_upload_size_is_rejected_from_head_before_object_body_is_read() -> None:
    class ReadCountingStore(MemoryObjectStore):
        reads = 0

        def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
            self.reads += 1
            return super().get_bytes(key, max_bytes=max_bytes)

    repo = Repository("sqlite+pysqlite://")
    store = ReadCountingStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    content = b"# Consigna\n\nExplique un mecanismo.\n"
    artifact, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=len(content),
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    token = upload["upload_url"].rsplit("/", 1)[-1]
    store.put_signed(token, content, "text/markdown")
    store._objects[artifact.object_key] = (content + b"x", "text/markdown")

    with pytest.raises(WorkflowError) as rejected:
        service.complete_upload(artifact.id, actor)

    assert rejected.value.code == "INGEST_SIZE_LIMIT"
    assert store.reads == 0


def test_completed_upload_is_sealed_and_revalidated_before_pipeline() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    runner = RecordingJobRunner()
    service = Stage1Service(
        settings=_settings(), repository=repo, object_store=store, job_runner=runner
    )
    service.create_activity(_config(), actor)
    original = b"# A\n\nOriginal.\n"
    replacement = b"# B\n\nModified.\n"
    assert len(original) == len(replacement)
    artifact, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="assignment.md",
        media_type="text/markdown",
        expected_byte_size=len(original),
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    pending_key = artifact.object_key
    token = upload["upload_url"].rsplit("/", 1)[-1]
    store.put_signed(token, original, "text/markdown")
    service.complete_upload(artifact.id, actor)
    completed = repo.scoped(ArtifactRow, artifact.id, actor.workspace_id)
    assert isinstance(completed, ArtifactRow)
    assert completed.object_key != pending_key
    assert "/sealed/" in completed.object_key

    # The still-valid direct-upload capability can mutate only the disposable
    # upload key. Pipelines dereference the immutable, content-addressed key.
    store.put_signed(token, replacement, "text/markdown")
    assert store.get_bytes(pending_key, max_bytes=len(replacement)) == replacement
    assert store.get_bytes(completed.object_key, max_bytes=len(original)) == original
    first = asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    asyncio.run(service.process_job(first.job_id))
    assert repo.job_status(first.job_id, actor.workspace_id).status == "SUCCEEDED"

    # Simulate storage corruption through the fake's trusted test seam. The
    # provenance check fails closed, while E1 also forbids rerunning an already
    # completed activity pipeline (general retry belongs to Stage 2).
    store._objects[completed.object_key] = (replacement, "text/markdown")
    with pytest.raises(WorkflowError, match="hash changed"):
        service._verified_artifact_bytes(completed)
    with pytest.raises(WorkflowError, match="once per decision state") as rerun:
        asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    assert rerun.value.status_code == 409


def test_activity_uploads_freeze_atomically_and_pending_inputs_block_enqueue() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    _upload_bytes(
        service,
        store,
        actor,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        content=b"# Consigna\n\nExplique una decision localizada.\n",
    )
    rubric = b"# Rubrica\n\nValore evidencia localizada.\n"
    pending, upload = service.create_upload(
        actor=actor,
        activity_id="act_backend",
        filename="rubric.md",
        media_type="text/markdown",
        expected_byte_size=len(rubric),
        role=m.ArtifactRole.RUBRIC,
    )

    with pytest.raises(WorkflowError) as blocked:
        asyncio.run(service.enqueue_activity_pipeline("act_backend", actor))
    assert blocked.value.code == "ARTIFACT_UPLOAD_PENDING"
    assert blocked.value.status_code == 409

    # Simulate the aggregate being frozen between signed PUT and completion;
    # the final repository transition rechecks the parent under the same lock.
    store.put_signed(
        upload["upload_url"].rsplit("/", 1)[-1], rubric, "text/markdown"
    )
    repo.set_activity_status("act_backend", actor.workspace_id, "QUEUED")
    with pytest.raises(WorkflowError) as frozen_completion:
        service.complete_upload(pending.id, actor)
    assert frozen_completion.value.code == "ACTIVITY_INPUTS_FROZEN"
    assert frozen_completion.value.status_code == 409

    with pytest.raises(WorkflowError) as frozen_session:
        service.create_upload(
            actor=actor,
            activity_id="act_backend",
            filename="another-rubric.md",
            media_type="text/markdown",
            expected_byte_size=32,
            role=m.ArtifactRole.RUBRIC,
        )
    assert frozen_session.value.code == "ACTIVITY_INPUTS_FROZEN"


def test_activity_config_repository_cas_rechecks_etag_under_lock() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    created = service.create_activity(_config(), actor)
    original_etag = service.activity_etag(created)
    first_config = _config().model_copy(update={"title": "Primera edicion"})
    repo.update_activity_config(
        activity_id=created.id,
        tenant_id=actor.workspace_id,
        config=first_config.model_dump(mode="json"),
        blueprint_policy=created.blueprint_policy,
        expected_etag=original_etag,
    )

    with pytest.raises(Conflict, match="ETAG_MISMATCH"):
        repo.update_activity_config(
            activity_id=created.id,
            tenant_id=actor.workspace_id,
            config=_config().model_copy(update={"title": "Edicion perdida"}).model_dump(mode="json"),
            blueprint_policy=created.blueprint_policy,
            expected_etag=original_etag,
        )


def test_blueprint_edit_runs_durable_preflight_with_zero_p05_calls() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    runner = RecordingJobRunner()
    initial_service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=runner,
    )
    initial_service.create_activity(_config(), actor)
    _upload_bytes(
        initial_service,
        store,
        actor,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        content=b"# Consigna\n\nExplique una decision y su consecuencia local.\n",
    )
    activity_job = asyncio.run(
        initial_service.enqueue_activity_pipeline("act_backend", actor)
    )
    asyncio.run(initial_service.process_job(activity_job.job_id))
    source = repo.latest_blueprint("act_backend", actor.workspace_id)
    edited = m.AssessmentBlueprint.model_validate(source.data).model_copy(
        update={
            "dimensions": [
                dimension.model_copy(
                    update={"name": f"{dimension.name} revisada"}
                )
                for dimension in m.AssessmentBlueprint.model_validate(
                    source.data
                ).dimensions
            ]
        }
    )

    web_service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=runner,
    )
    queued = asyncio.run(
        web_service.edit_blueprint(
            activity_id="act_backend",
            version=source.version,
            if_match=source.etag,
            edited=edited,
            actor=actor,
        )
    )

    assert queued.status == "QUEUED"
    assert repo.latest_blueprint("act_backend", actor.workspace_id).version == 1
    queued_row = repo.scoped(JobRow, queued.job_id, actor.workspace_id)
    assert isinstance(queued_row, JobRow)
    assert queued_row.kind == "BLUEPRINT_PREFLIGHT"
    descriptor = repo.blueprint_preflight_descriptor(
        job_ids=[queued.job_id], tenant_id=actor.workspace_id
    )
    assert descriptor is not None and descriptor.output is not None
    assert descriptor.output["source_blueprint_version"] == 1
    assert descriptor.output["candidate_blueprint"][
        "blueprint_version"
    ] == 2
    assert repo.model_calls(tenant_id=actor.workspace_id, job_id=queued.job_id) == []
    activity = repo.scoped(ActivityRow, "act_backend", actor.workspace_id)
    assert isinstance(activity, ActivityRow)
    assert activity.status == "BLUEPRINT_PREFLIGHT_QUEUED"

    def preflight_worker(
        job_id: str,
        *,
        mock_adapter: DeterministicMockAdapter | None = None,
    ) -> Stage1Service:
        claimed = repo.claim_job(job_id)
        assert claimed is not None
        return Stage1Service(
            settings=_settings(),
            repository=repo,
            object_store=store,
            gateway_factory=lambda requested_job_id: ModelGateway(
                GatewayConfig(mode=GatewayMode.MOCK, job_id=requested_job_id),
                mock_adapter=mock_adapter,
                ledger_sink=repo.model_call_sink,
            ),
        )

    worker_service = preflight_worker(queued.job_id)
    asyncio.run(worker_service.process_job(queued.job_id))

    terminal = repo.job_status(queued.job_id, actor.workspace_id)
    assert terminal.status == "SUCCEEDED", terminal.diagnostics
    assert terminal.stage == "BLUEPRINT_PREFLIGHT"
    reviewed = repo.latest_blueprint("act_backend", actor.workspace_id)
    assert reviewed.version == 2
    reviewed_value = m.AssessmentBlueprint.model_validate(reviewed.data)
    assert reviewed_value.dimensions[0].name.endswith("revisada")
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=queued.job_id
    ) == []
    assert m.BlueprintReviewPreflight.model_validate(
        reviewed.preflight
    ).catalog_plan_feasible
    assert reviewed.review is None

    cancelled_edit = reviewed_value.model_copy(
        update={
            "dimensions": [
                dimension.model_copy(
                    update={"name": f"{dimension.name} cancelada"}
                )
                for dimension in reviewed_value.dimensions
            ]
        }
    )
    cancelled_job = asyncio.run(
        web_service.edit_blueprint(
            activity_id="act_backend",
            version=reviewed.version,
            if_match=reviewed.etag,
            edited=cancelled_edit,
            actor=actor,
        )
    )
    repo.request_job_cancel(
        job_id=cancelled_job.job_id,
        tenant_id=actor.workspace_id,
        actor_id=actor.user_id,
    )
    cancelled_terminal = repo.job_status(cancelled_job.job_id, actor.workspace_id)
    assert cancelled_terminal.status == "FAILED"
    assert cancelled_terminal.diagnostics[0].code == "JOB_CANCELLED"
    assert repo.latest_blueprint("act_backend", actor.workspace_id).version == 2
    restored = repo.scoped(ActivityRow, "act_backend", actor.workspace_id)
    assert isinstance(restored, ActivityRow)
    assert restored.status == "BLUEPRINT_READY"

    retried_edit = reviewed_value.model_copy(
        update={
            "dimensions": [
                dimension.model_copy(
                    update={"name": f"{dimension.name} reintentada"}
                )
                for dimension in reviewed_value.dimensions
            ]
        }
    )
    failed_dispatch = asyncio.run(
        web_service.edit_blueprint(
            activity_id="act_backend",
            version=reviewed.version,
            if_match=reviewed.etag,
            edited=retried_edit,
            actor=actor,
        )
    )
    assert repo.fail_queued_dispatch(
        job_id=failed_dispatch.job_id,
        tenant_id=actor.workspace_id,
        failure=diagnostic(
            "JOB_DISPATCH_FAILED",
            "The synthetic durable dispatch failed.",
            retryable=True,
        ),
    )
    retry = repo.schedule_job_retry(
        job_id=failed_dispatch.job_id,
        tenant_id=actor.workspace_id,
        resulting_job_id="job_blueprint_preflight_retry",
        control_id="control_blueprint_preflight_retry",
        actor_id=actor.user_id,
        reason_code="TRANSIENT_DISPATCH_FAILURE",
        failure_class="TRANSIENT",
        next_attempt_at=utc_now(),
        resume_from_stage="BLUEPRINT_PREFLIGHT",
    )
    assert retry.kind == "BLUEPRINT_PREFLIGHT"
    assert retry.status == "QUEUED"
    asyncio.run(preflight_worker(retry.id).process_job(retry.id))

    assert repo.job_status(retry.id, actor.workspace_id).status == "SUCCEEDED"
    retried = repo.latest_blueprint("act_backend", actor.workspace_id)
    assert retried.version == 3
    retried_value = m.AssessmentBlueprint.model_validate(retried.data)
    assert retried_value.dimensions[0].name.endswith("reintentada")
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=failed_dispatch.job_id
    ) == []
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=retry.id
    ) == []

    class ForbiddenProviderAdapter(DeterministicMockAdapter):
        async def invoke(self, **kwargs: object) -> AdapterResult:
            raise AssertionError("the deterministic preflight must not call a provider")

    rejected_edit = retried_value.model_copy(
        update={
            "dimensions": [
                dimension.model_copy(
                    update={"name": f"{dimension.name} rechazada"}
                )
                for dimension in retried_value.dimensions
            ]
        }
    )
    rejected_job = asyncio.run(
        web_service.edit_blueprint(
            activity_id="act_backend",
            version=retried.version,
            if_match=retried.etag,
            edited=rejected_edit,
            actor=actor,
        )
    )
    rejecting_worker = preflight_worker(
        rejected_job.job_id,
        mock_adapter=ForbiddenProviderAdapter(),
    )
    asyncio.run(rejecting_worker.process_job(rejected_job.job_id))

    assert repo.job_status(
        rejected_job.job_id, actor.workspace_id
    ).status == "SUCCEEDED"
    assert repo.latest_blueprint(
        "act_backend", actor.workspace_id
    ).version == retried.version + 1
    blocked_activity = repo.scoped(
        ActivityRow, "act_backend", actor.workspace_id
    )
    assert isinstance(blocked_activity, ActivityRow)
    assert blocked_activity.status == "BLUEPRINT_READY"
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=rejected_job.job_id
    ) == []


def test_legacy_p05_job_reconciles_without_provider_and_review_no_longer_gates() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    _upload_bytes(
        service,
        store,
        actor,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        content=b"# Consigna\n\nExplique una decision y su consecuencia local.\n",
    )
    activity_job = asyncio.run(
        service.enqueue_activity_pipeline("act_backend", actor)
    )
    asyncio.run(service.process_job(activity_job.job_id))
    source = repo.latest_blueprint("act_backend", actor.workspace_id)
    source_value = m.AssessmentBlueprint.model_validate(source.data)
    candidate = source_value.model_copy(
        update={
            "blueprint_version": source.version + 1,
            "dimensions": [
                dimension.model_copy(update={"name": f"{dimension.name} heredada"})
                for dimension in source_value.dimensions
            ],
        }
    )
    activity_spec = m.ActivitySpec.model_validate(
        cast(
            ActivitySpecRow,
            repo.scoped(ActivitySpecRow, "act_backend", actor.workspace_id),
        ).data
    )
    activity = cast(
        ActivityRow, repo.scoped(ActivityRow, "act_backend", actor.workspace_id)
    )
    policy = m.BlueprintPolicy.model_validate(activity.blueprint_policy)
    review_request = m.BlueprintReviewRequest(
        blueprint=candidate,
        activity_spec=activity_spec,
        rubric_spec=None,
        resolved_decisions=[],
        blueprint_policy=policy,
        deterministic_preflight=build_blueprint_review_preflight(
            blueprint=candidate,
            activity_spec=activity_spec,
            rubric_spec=None,
            blueprint_policy=policy,
        ),
    )
    queued = service._new_job(
        actor.workspace_id,
        "act_backend",
        "legacy_blueprint_review",
        "BLUEPRINT_REVIEW",
    )
    repo.prepare_blueprint_review_job(
        status=queued,
        source_version=source.version,
        source_etag=source.etag,
        descriptor_output={
            "kind": "BLUEPRINT_REVIEW_DESCRIPTOR",
            "source_blueprint_version": source.version,
            "source_etag": source.etag,
            "source_activity_status": "BLUEPRINT_READY",
            "actor_id": actor.user_id,
            "review_request": review_request.model_dump(mode="json"),
        },
        descriptor_component_version=(
            _blueprint_review_descriptor_component_version()
        ),
        descriptor_policy_hash=_blueprint_review_descriptor_policy_hash(
            review_request
        ),
        actor_id=actor.user_id,
        occurred_at=utc_now(),
    )
    claimed = repo.claim_job(queued.job_id)
    assert claimed is not None and claimed.started_at is not None

    def forbidden_gateway(_job_id: str) -> ModelGateway:
        raise AssertionError("legacy P05 recovery must not construct a gateway")

    worker = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        gateway_factory=forbidden_gateway,
    )
    # Materialize the deterministic output, then model a worker crash before
    # the aggregate transition. Lease recovery plus legacy resume must reuse it.
    gated, preflight = worker._blueprint_preflight_stage(
        job=claimed,
        blueprint=candidate,
        activity_spec=activity_spec,
        rubric_spec=None,
        resolved_decisions=[],
        blueprint_policy=policy,
    )
    assert gated.status == m.WorkflowStatus.READY
    assert preflight.catalog_plan_feasible
    crash_recovery_at = claimed.started_at + timedelta(seconds=301)
    assert repo.reconcile_stale_jobs(
        lease_seconds=300, now=crash_recovery_at
    ) == 1
    assert repo.job_status(queued.job_id, actor.workspace_id).status == "FAILED"
    retry = repo.schedule_job_retry(
        job_id=queued.job_id,
        tenant_id=actor.workspace_id,
        resulting_job_id="job_legacy_blueprint_preflight_retry",
        control_id="control_legacy_blueprint_preflight_retry",
        actor_id=actor.user_id,
        reason_code="LEASE_EXPIRED",
        failure_class="TRANSIENT",
        next_attempt_at=utc_now(),
        resume_from_stage="BLUEPRINT_REVIEW",
    )
    assert retry.kind == "BLUEPRINT_REVIEW"
    assert repo.claim_job(retry.id) is not None
    asyncio.run(worker.process_job(retry.id))

    terminal = repo.job_status(retry.id, actor.workspace_id)
    assert terminal.status == "SUCCEEDED"
    assert terminal.stage == "BLUEPRINT_PREFLIGHT"
    reconciled = repo.latest_blueprint("act_backend", actor.workspace_id)
    assert reconciled.version == source.version + 1
    assert reconciled.review is None
    assert m.BlueprintReviewPreflight.model_validate(
        reconciled.preflight
    ).catalog_plan_feasible
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=queued.job_id
    ) == []
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=retry.id
    ) == []
    assert repo.has_audit_event(
        tenant_id=actor.workspace_id,
        event_type="stage.reused",
        aggregate_id=retry.id,
        payload_contains={"stage": "BLUEPRINT_PREFLIGHT"},
    )

    # A completed historical row may carry a P05 failure and no preflight
    # column. Approval recomputes the deterministic gate and ignores P05.
    historical_review = m.BlueprintReview(
        activity_id="act_backend",
        blueprint_id=candidate.blueprint_id,
        blueprint_version=reconciled.version,
        status="TECHNICAL_FAILURE",
    )
    with repo.session() as session:
        persisted = session.get(type(reconciled), reconciled.row_id)
        assert persisted is not None
        persisted.review = historical_review.model_dump(mode="json")
        persisted.preflight = None
    legacy = repo.latest_blueprint("act_backend", actor.workspace_id)
    projected_preflight, projected_issues = service.blueprint_review_projection(
        legacy, actor
    )
    assert m.BlueprintReviewPreflight.model_validate(
        projected_preflight
    ).catalog_plan_feasible
    assert projected_issues == []
    assert legacy.review is not None
    approved = service.approve_blueprint(
        activity_id="act_backend",
        version=legacy.version,
        if_match=legacy.etag,
        actor=actor,
    )
    assert m.AssessmentBlueprint.model_validate(approved.data).status == "APPROVED"
    assert approved.review is None
    assert m.BlueprintReviewPreflight.model_validate(
        approved.preflight
    ).catalog_plan_feasible


def test_submission_job_is_bound_to_exact_approved_blueprint_version() -> None:
    repo = Repository("sqlite+pysqlite://")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    _upload_bytes(
        service,
        store,
        actor,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        content=b"# Consigna\n\nExplique una decision y su consecuencia local.\n",
    )
    activity_job = asyncio.run(
        service.enqueue_activity_pipeline("act_backend", actor)
    )
    asyncio.run(service.process_job(activity_job.job_id))
    ready = repo.latest_blueprint("act_backend", actor.workspace_id)
    approved = service.approve_blueprint(
        activity_id="act_backend",
        version=ready.version,
        if_match=ready.etag,
        actor=actor,
    )
    approved_model = m.AssessmentBlueprint.model_validate(approved.data)

    with pytest.raises(WorkflowError) as frozen:
        asyncio.run(
            service.edit_blueprint(
                activity_id="act_backend",
                version=approved.version,
                if_match=approved.etag,
                edited=approved_model,
                actor=actor,
            )
        )
    assert frozen.value.code == "BLUEPRINT_FROZEN"
    assert frozen.value.status_code == 409

    submission = service.create_submission(
        activity_id="act_backend", subject_ref="subject_bound_version", actor=actor
    )
    _upload_bytes(
        service,
        store,
        actor,
        role=m.ArtifactRole.SUBMISSION,
        submission_id=submission.id,
        content=(
            b"# Entrega\n\nLa deduplicacion ocurre antes del promedio para evitar doble peso.\n"
        ),
    )
    submission_job = asyncio.run(
        service.enqueue_submission_pipeline(submission.id, actor)
    )
    persisted_submission = repo.scoped(
        SubmissionRow, submission.id, actor.workspace_id
    )
    assert isinstance(persisted_submission, SubmissionRow)
    assert persisted_submission.blueprint_version == approved.version

    with pytest.raises(WorkflowError) as frozen_submission:
        service.create_upload(
            actor=actor,
            activity_id="act_backend",
            submission_id=submission.id,
            filename="replacement.md",
            media_type="text/markdown",
            expected_byte_size=32,
            role=m.ArtifactRole.SUBMISSION,
        )
    assert frozen_submission.value.code == "SUBMISSION_INPUTS_FROZEN"

    # Even if a newer unapproved row appears through a trusted maintenance seam,
    # the worker must use the exact approved version captured at enqueue time.
    newer_version = approved.version + 1
    newer = approved_model.model_copy(
        update={
            "blueprint_version": newer_version,
            "status": m.WorkflowStatus.READY,
            "approved_by": None,
            "approved_at": None,
        }
    )
    newer_preflight = m.BlueprintReviewPreflight.model_validate(
        approved.preflight
    ).model_copy(update={"blueprint_version": newer_version})
    repo.add(
        service._blueprint_row(
            actor.workspace_id,
            newer,
            preflight=newer_preflight,
            review=None,
        )
    )

    asyncio.run(service.process_job(submission_job.job_id))
    assert (
        repo.job_status(submission_job.job_id, actor.workspace_id).status
        == "SUCCEEDED"
    )
    assessment = m.Assessment.model_validate(
        repo.latest_assessment(submission.id, actor.workspace_id).data
    )
    assert assessment.lineage.blueprint_version == approved.version


def test_concurrent_upload_sessions_preserve_one_role_per_scope(tmp_path) -> None:
    barrier = Barrier(2)

    class BarrierRepository(Repository):
        synchronize_artifacts = False

        def reserve_artifact_upload(  # type: ignore[no-untyped-def]
            self,
            row,
            *,
            allowed_activity_statuses,
        ):
            if self.synchronize_artifacts:
                barrier.wait(timeout=5)
            return super().reserve_artifact_upload(
                row,
                allowed_activity_statuses=allowed_activity_statuses,
            )

    repo = BarrierRepository(f"sqlite+pysqlite:///{tmp_path / 'uploads.db'}")
    store = MemoryObjectStore(
        secret="object-test-secret-with-at-least-thirty-two-bytes"
    )
    actor = _actor()
    service = Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    service.create_activity(_config(), actor)
    repo.synchronize_artifacts = True

    def create(index: int) -> tuple[str, str, int | None]:
        try:
            row, _upload = service.create_upload(
                actor=actor,
                activity_id="act_backend",
                filename=f"assignment-{index}.md",
                media_type="text/markdown",
                expected_byte_size=64,
                role=m.ArtifactRole.ASSIGNMENT_PROMPT,
            )
            return "created", row.id, None
        except WorkflowError as exc:
            return "rejected", exc.code, exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, (1, 2)))

    assert sorted(item[0] for item in outcomes) == ["created", "rejected"]
    rejected = next(item for item in outcomes if item[0] == "rejected")
    assert rejected[1:] == ("ARTIFACT_ALREADY_EXISTS", 409)
    artifacts = repo.artifacts_for(
        activity_id="act_backend",
        tenant_id=actor.workspace_id,
        submission_id=None,
        complete_only=False,
    )
    assert len(artifacts) == 1
