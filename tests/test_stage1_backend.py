from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
    ModelGateway,
)
from comprehension_verification.web.auth import Actor
from comprehension_verification.web.jobs import RecordingJobRunner
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import (
    ArtifactRow,
    ActivityRow,
    Conflict,
    JobRow,
    NotFound,
    Repository,
    SubmissionRow,
    utc_now,
)
from comprehension_verification.web.settings import Settings, WorkerSettings
from comprehension_verification.web.workflows import Stage1Service, WorkflowError


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


def test_blueprint_edit_is_durable_before_p05_and_runs_in_real_worker_mode() -> None:
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
        settings=_settings(worker_model_mode="real"),
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
    assert queued_row.kind == "BLUEPRINT_REVIEW"
    descriptor = repo.blueprint_review_descriptor(
        job_ids=[queued.job_id], tenant_id=actor.workspace_id
    )
    assert descriptor is not None and descriptor.output is not None
    assert descriptor.output["source_blueprint_version"] == 1
    assert descriptor.output["review_request"]["blueprint"][
        "blueprint_version"
    ] == 2
    assert repo.model_calls(tenant_id=actor.workspace_id, job_id=queued.job_id) == []
    activity = repo.scoped(ActivityRow, "act_backend", actor.workspace_id)
    assert isinstance(activity, ActivityRow)
    assert activity.status == "BLUEPRINT_REVIEW_QUEUED"

    worker_service = Stage1Service(
        settings=WorkerSettings(
            environment="test",
                database_url="sqlite+pysqlite://",
                model_mode="real",
                openai_api_key="sk-project-synthetic-placeholder-not-a-real-key",
                synthetic_artifact_sha256_allowlist=cast(
                    str,
                    repo.artifacts_for(
                        activity_id="act_backend",
                        tenant_id=actor.workspace_id,
                        submission_id=None,
                    )[0].sha256,
                ),
            ),
        repository=repo,
        object_store=store,
        gateway_factory=lambda job_id: ModelGateway(
            GatewayConfig(mode=GatewayMode.MOCK, job_id=job_id),
            ledger_sink=repo.model_call_sink,
        ),
    )
    asyncio.run(worker_service.process_job(queued.job_id))

    terminal = repo.job_status(queued.job_id, actor.workspace_id)
    assert terminal.status == "SUCCEEDED"
    assert terminal.stage == "BLUEPRINT_REVIEW"
    reviewed = repo.latest_blueprint("act_backend", actor.workspace_id)
    assert reviewed.version == 2
    reviewed_value = m.AssessmentBlueprint.model_validate(reviewed.data)
    assert reviewed_value.dimensions[0].name.endswith("revisada")
    assert [
        item["prompt_id"]
        for item in repo.model_calls(
            tenant_id=actor.workspace_id, job_id=queued.job_id
        )
    ] == ["P05_BLUEPRINT_REVIEW_V1"]

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
        resulting_job_id="job_blueprint_review_retry",
        control_id="control_blueprint_review_retry",
        actor_id=actor.user_id,
        reason_code="TRANSIENT_DISPATCH_FAILURE",
        failure_class="TRANSIENT",
        next_attempt_at=utc_now(),
        resume_from_stage="BLUEPRINT_REVIEW",
    )
    assert retry.kind == "BLUEPRINT_REVIEW"
    assert retry.status == "QUEUED"
    asyncio.run(worker_service.process_job(retry.id))

    assert repo.job_status(retry.id, actor.workspace_id).status == "SUCCEEDED"
    retried = repo.latest_blueprint("act_backend", actor.workspace_id)
    assert retried.version == 3
    retried_value = m.AssessmentBlueprint.model_validate(retried.data)
    assert retried_value.dimensions[0].name.endswith("reintentada")
    assert repo.model_calls(
        tenant_id=actor.workspace_id, job_id=failed_dispatch.job_id
    ) == []
    assert [
        item["prompt_id"]
        for item in repo.model_calls(
            tenant_id=actor.workspace_id, job_id=retry.id
        )
    ] == ["P05_BLUEPRINT_REVIEW_V1"]

    class RejectingP05Adapter(DeterministicMockAdapter):
        async def invoke(self, **kwargs: object) -> AdapterResult:
            result = await super().invoke(**kwargs)  # type: ignore[arg-type]
            if kwargs["prompt_id"] != "P05_BLUEPRINT_REVIEW_V1":
                return result
            raw = dict(result.raw_output)
            raw["approval_recommendation"] = "REJECT"
            checks = [dict(item) for item in raw["checks"]]
            checks[0]["status"] = "FAIL"
            checks[0]["critical"] = True
            raw["checks"] = checks
            return replace(result, raw_output=raw)

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
    worker_service.gateway_factory = lambda job_id: ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, job_id=job_id),
        mock_adapter=RejectingP05Adapter(),
        ledger_sink=repo.model_call_sink,
    )
    asyncio.run(worker_service.process_job(rejected_job.job_id))

    assert repo.job_status(
        rejected_job.job_id, actor.workspace_id
    ).status == "NEEDS_REVIEW"
    assert repo.latest_blueprint(
        "act_backend", actor.workspace_id
    ).version == retried.version
    blocked_activity = repo.scoped(
        ActivityRow, "act_backend", actor.workspace_id
    )
    assert isinstance(blocked_activity, ActivityRow)
    assert blocked_activity.status == "NEEDS_REVIEW"


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
    newer_review = m.BlueprintReview.model_validate(approved.review).model_copy(
        update={"blueprint_version": newer_version}
    )
    repo.add(service._blueprint_row(actor.workspace_id, newer, newer_review))

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
