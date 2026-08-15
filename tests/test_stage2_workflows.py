from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import (
    DeterministicMockAdapter,
    GatewayConfig,
    GatewayMode,
    GatewayProviderError,
    GatewayTimeout,
    ModelGateway,
    PermanentProviderError,
    TransientProviderError,
    build_mock_request,
    build_trusted_context,
)
from comprehension_verification.parsers import DOCX_MEDIA_TYPE, ParseRejected
from comprehension_verification.web.auth import Actor
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import (
    ActivityRow,
    JobRow,
    Repository,
    SubmissionRow,
    utc_now,
)
from comprehension_verification.web.settings import Settings
from comprehension_verification.web.workflows import (
    Stage1Service,
    WorkflowError,
    build_blueprint_policy,
)
from tests.factories import evidence_unit


TENANT_ID = "tnt_stage2_worker"
ACTIVITY_ID = "act_stage2_worker"


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        session_secret="stage2-worker-test-secret-with-32-bytes",
        model_mode="mock",
    )


def _config(*, allowed_media_types: list[str] | None = None) -> m.ActivityConfig:
    return m.ActivityConfig(
        activity_id=ACTIVITY_ID,
        tenant_id=TENANT_ID,
        title="Actividad worker E2",
        output_language="es-CL",
        context_mode=m.ContextMode.CLOSED,
        assessment_modality=m.AssessmentModality.WRITTEN,
        question_count=1,
        target_total_minutes=3,
        structured_justification_mode=m.StructuredJustificationMode.NOT_REQUIRED,
        allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
        allowed_artifact_media_types=allowed_media_types or ["text/markdown"],
    )


def _activity() -> ActivityRow:
    config = _config()
    return ActivityRow(
        id=config.activity_id,
        tenant_id=config.tenant_id,
        status="QUEUED",
        config=config.model_dump(mode="json"),
        blueprint_policy=build_blueprint_policy(config).model_dump(mode="json"),
        created_by="usr_stage2_worker",
    )


def _service(repo: Repository) -> Stage1Service:
    return Stage1Service(
        settings=_settings(),
        repository=repo,
        object_store=MemoryObjectStore(
            secret="stage2-worker-object-secret-with-32-bytes"
        ),
    )


def _add_submission_job(
    repo: Repository,
    *,
    job_id: str,
    submission_id: str,
) -> JobRow:
    state = m.SubmissionProcessingState(
        submission_id=submission_id,
        activity_id=ACTIVITY_ID,
        status=m.SubmissionProcessingStatus.UPLOADED,
        progress=0.0,
        active_job_id=job_id,
        updated_at=utc_now(),
    )
    repo.add(
        SubmissionRow(
            id=submission_id,
            tenant_id=TENANT_ID,
            activity_id=ACTIVITY_ID,
            subject_ref=f"subject_{submission_id}",
            state=state.model_dump(mode="json"),
            active_job_id=job_id,
        )
    )
    job = JobRow(
        id=job_id,
        tenant_id=TENANT_ID,
        kind="SUBMISSION",
        aggregate_id=submission_id,
        stage="SUBMISSION_PARSE",
        status="QUEUED",
        progress=0.0,
        attempt=0,
        diagnostics=[],
    )
    repo.add(job)
    return job


def test_late_worker_delivery_does_not_reopen_cancelled_queued_job() -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.add(_activity())
    job = _add_submission_job(
        repo, job_id="job_cancelled_before_start", submission_id="sub_cancelled"
    )
    repo.request_job_cancel(
        job_id=job.id,
        tenant_id=TENANT_ID,
        actor_id="usr_stage2_worker",
        control_id="control_cancelled_before_start",
    )
    service = _service(repo)
    pipeline_called = False

    async def should_not_run(_job: JobRow) -> None:
        nonlocal pipeline_called
        pipeline_called = True

    service._run_submission_pipeline = should_not_run  # type: ignore[method-assign]
    asyncio.run(service.process_job(job.id))

    control = repo.job_control(job.id, TENANT_ID)
    assert not pipeline_called
    assert control.control_state == "CANCELLED"
    assert control.status == "FAILED"
    assert control.failure_class == "CANCELLATION"
    assert control.diagnostics[0]["code"] == "JOB_CANCELLED"


def test_running_cancellation_stops_at_next_stage_boundary() -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.add(_activity())
    job = _add_submission_job(
        repo, job_id="job_cancel_between", submission_id="sub_cancel_between"
    )
    service = _service(repo)
    reached_second_stage = False

    async def cancel_between_stages(running_job: JobRow) -> None:
        nonlocal reached_second_stage
        service._set_job(running_job, "FIRST_STAGE", 0.2)
        repo.request_job_cancel(
            job_id=running_job.id,
            tenant_id=running_job.tenant_id,
            actor_id="usr_stage2_worker",
            control_id="control_cancel_between",
        )
        service._set_job(running_job, "SECOND_STAGE", 0.4)
        reached_second_stage = True

    service._run_submission_pipeline = cancel_between_stages  # type: ignore[method-assign]
    asyncio.run(service.process_job(job.id))

    control = repo.job_control(job.id, TENANT_ID)
    submission = repo.scoped(SubmissionRow, "sub_cancel_between", TENANT_ID)
    assert isinstance(submission, SubmissionRow)
    state = m.SubmissionProcessingState.model_validate(submission.state)
    assert not reached_second_stage
    assert control.control_state == "CANCELLED"
    assert control.status == "FAILED"
    assert control.failure_class == "CANCELLATION"
    assert state.status == m.SubmissionProcessingStatus.CANCELLED
    assert state.current_stage == "FIRST_STAGE"
    assert state.active_job_id is None


def _transient_provider_failure() -> GatewayProviderError:
    error = GatewayProviderError("sanitized provider failure")
    error.__cause__ = TransientProviderError("provider detail must not persist")
    return error


def _permanent_provider_failure() -> GatewayProviderError:
    error = GatewayProviderError("sanitized provider failure")
    error.__cause__ = PermanentProviderError("provider detail must not persist")
    return error


@pytest.mark.parametrize(
    ("failure_factory", "expected_class", "retryable", "expected_code"),
    [
        (
            lambda: GatewayTimeout("provider timeout detail"),
            "TRANSIENT",
            True,
            "MODEL_TIMEOUT",
        ),
        (
            _transient_provider_failure,
            "PROVIDER",
            True,
            "MODEL_PROVIDER_ERROR",
        ),
        (
            _permanent_provider_failure,
            "PERMANENT",
            False,
            "MODEL_PROVIDER_ERROR",
        ),
        (
            lambda: WorkflowError("WORKFLOW_INVALID", "sensitive workflow detail"),
            "PERMANENT",
            False,
            "WORKFLOW_INVALID",
        ),
        (
            lambda: ParseRejected("REJECTED_SECURITY", "hostile input detail"),
            "SECURITY",
            False,
            "REJECTED_SECURITY",
        ),
    ],
)
def test_worker_persists_stable_failure_classification(
    failure_factory: Callable[[], Exception],
    expected_class: str,
    retryable: bool,
    expected_code: str,
) -> None:
    repo = Repository("sqlite+pysqlite://")
    activity = _activity()
    repo.add(activity)
    job = JobRow(
        id=f"job_failure_{expected_class.lower()}",
        tenant_id=TENANT_ID,
        kind="ACTIVITY",
        aggregate_id=activity.id,
        stage="ACTIVITY_PARSE",
        status="QUEUED",
        progress=0.0,
        attempt=0,
        diagnostics=[],
    )
    repo.add(job)
    service = _service(repo)

    async def fail_pipeline(_job: JobRow) -> None:
        raise failure_factory()

    service._run_activity_pipeline = fail_pipeline  # type: ignore[method-assign]
    asyncio.run(service.process_job(job.id))

    failed = repo.job_control(job.id, TENANT_ID)
    assert failed.status == "FAILED"
    assert failed.failure_class == expected_class
    assert failed.diagnostics == [
        {
            "code": expected_code,
            "severity": "ERROR",
            "message": "The workflow failed at a content-minimizing boundary.",
            "evidence_ids": [],
            "source_ids": [],
            "retryable": retryable,
            "details": {},
        }
    ]


def test_gateway_failure_persists_failed_stage_without_reusable_output() -> None:
    repo = Repository("sqlite+pysqlite://")
    activity = _activity()
    repo.add(activity)
    job = JobRow(
        id="job_gateway_timeout",
        tenant_id=TENANT_ID,
        kind="ACTIVITY",
        aggregate_id=activity.id,
        stage="ACTIVITY_SPEC",
        status="QUEUED",
        progress=0.0,
        attempt=0,
        diagnostics=[],
    )
    repo.add(job)
    service = _service(repo)

    class FailingGateway:
        @staticmethod
        def execution_fingerprint(*_args: object, **_kwargs: object) -> str:
            return "test-failing-gateway/1.0.0"

        async def invoke(self, *_args: object, **_kwargs: object) -> object:
            raise GatewayTimeout("provider timeout detail")

    service._gateway = (  # type: ignore[method-assign,return-value]
        lambda _job_id: FailingGateway()
    )
    service._trusted_prompt_context = (  # type: ignore[method-assign]
        lambda *, request, **_kwargs: build_trusted_context(request)
    )

    async def fail_gateway_stage(running_job: JobRow) -> None:
        await service._gateway_stage(
            running_job,
            "P01_ACTIVITY_SPEC_V1",
            m.ActivitySpecRequest(
                activity_config=_config(),
                prompt_evidence=[evidence_unit(1)],
            ),
            m.ActivitySpec,
        )

    service._run_activity_pipeline = fail_gateway_stage  # type: ignore[method-assign]
    asyncio.run(service.process_job(job.id))

    stage_runs = repo.stage_runs_for_job(job.id, TENANT_ID)
    assert len(stage_runs) == 1
    assert stage_runs[0].status == "FAILED"
    assert stage_runs[0].failure_class == "TRANSIENT"
    assert stage_runs[0].output is None
    assert stage_runs[0].output_hash is None
    assert stage_runs[0].diagnostics[0]["retryable"] is True


def test_completed_p06_stage_replays_canonical_output_without_duplicate_call_or_stage() -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.add(_activity())
    first_job = _add_submission_job(
        repo,
        job_id="job_p06_first",
        submission_id="sub_p06_reuse",
    )
    first_job.attempt = 1
    with repo.session() as session:
        persisted_first = session.get(JobRow, first_job.id)
        assert persisted_first is not None
        persisted_first.attempt = 1
    resumed_job = JobRow(
        id="job_p06_resumed",
        tenant_id=TENANT_ID,
        kind="SUBMISSION",
        aggregate_id="sub_p06_reuse",
        stage="EVIDENCE_MAP",
        status="QUEUED",
        progress=0.0,
        attempt=1,
        diagnostics=[],
        resume_from_stage="EVIDENCE_MAP",
    )
    repo.add(resumed_job)
    service = _service(repo)

    class CountingAdapter(DeterministicMockAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            self.calls += 1
            return await super().invoke(**kwargs)

    adapter = CountingAdapter()
    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=adapter,
        ledger_sink=repo.model_call_sink,
    )
    service.gateway_factory = lambda _job_id: gateway
    service._trusted_prompt_context = (  # type: ignore[method-assign]
        lambda *, request, **_kwargs: build_trusted_context(request)
    )
    request_data = build_mock_request("P06_EVIDENCE_MAP_V1").model_dump(
        mode="json"
    )
    request_data["blueprint"]["activity_id"] = ACTIVITY_ID
    request_data["evidence_bundle"].update(
        {
            "tenant_id": TENANT_ID,
            "activity_id": ACTIVITY_ID,
            "submission_id": "sub_p06_reuse",
        }
    )
    for unit in request_data["evidence_bundle"]["evidence_units"]:
        unit["tenant_id"] = TENANT_ID
        unit["submission_id"] = "sub_p06_reuse"
    request = m.EvidenceMapRequest.model_validate(request_data)

    first = asyncio.run(
        service._gateway_stage(
            first_job,
            "P06_EVIDENCE_MAP_V1",
            request,
            m.EvidenceMapPatch,
        )
    )
    resumed = asyncio.run(
        service._gateway_stage(
            resumed_job,
            "P06_EVIDENCE_MAP_V1",
            request,
            m.EvidenceMapPatch,
        )
    )

    assert first == resumed
    assert first.mapping_summary is not None
    assert adapter.calls == 1
    assert len(repo.model_calls(tenant_id=TENANT_ID)) == 1
    assert len(repo.stage_runs_for_job(first_job.id, TENANT_ID)) == 1
    assert repo.stage_runs_for_job(resumed_job.id, TENANT_ID) == []
    reuse_events = repo.audit_events(
        tenant_id=TENANT_ID,
        event_type="stage.reused",
        aggregate_id=resumed_job.id,
    )
    assert len(reuse_events) == 1


def test_cancellation_during_gateway_discards_uncommitted_stage_output() -> None:
    repo = Repository("sqlite+pysqlite://")
    activity = _activity()
    repo.add(activity)
    repo.set_activity_status(activity.id, TENANT_ID, "QUEUED")
    job = JobRow(
        id="job_cancel_during_gateway",
        tenant_id=TENANT_ID,
        kind="ACTIVITY",
        aggregate_id=activity.id,
        stage="ACTIVITY_SPEC",
        status="QUEUED",
        progress=0.0,
        attempt=0,
        diagnostics=[],
    )
    repo.add(job)
    service = _service(repo)

    class CancellingGateway:
        @staticmethod
        def execution_fingerprint(*_args: object, **_kwargs: object) -> str:
            return "test-cancelling-gateway/1.0.0"

        async def invoke(self, *_args: object, **_kwargs: object) -> object:
            repo.request_job_cancel(
                job_id=job.id,
                tenant_id=TENANT_ID,
                actor_id="usr_stage2_worker",
                control_id="control_cancel_during_gateway",
            )
            return object()

    service._gateway = (  # type: ignore[method-assign,return-value]
        lambda _job_id: CancellingGateway()
    )
    service._trusted_prompt_context = (  # type: ignore[method-assign]
        lambda *, request, **_kwargs: build_trusted_context(request)
    )

    async def cancel_gateway_stage(running_job: JobRow) -> None:
        await service._gateway_stage(
            running_job,
            "P01_ACTIVITY_SPEC_V1",
            m.ActivitySpecRequest(
                activity_config=_config(),
                prompt_evidence=[evidence_unit(1)],
            ),
            m.ActivitySpec,
        )

    service._run_activity_pipeline = cancel_gateway_stage  # type: ignore[method-assign]
    asyncio.run(service.process_job(job.id))

    control = repo.job_control(job.id, TENANT_ID)
    reopened = repo.scoped(ActivityRow, activity.id, TENANT_ID)
    assert control.control_state == "CANCELLED"
    assert control.failure_class == "CANCELLATION"
    assert reopened.status == "DRAFT"
    assert repo.stage_runs_for_job(job.id, TENANT_ID) == []


def test_structural_docx_is_allowed_for_activity_uploads() -> None:
    repo = Repository("sqlite+pysqlite://")
    service = _service(repo)
    actor = Actor(
        user_id="usr_stage2_worker",
        email="teacher@example.test",
        workspace_id=TENANT_ID,
        role="TEACHER",
        can_approve_assessments=True,
        csrf_token="csrf_stage2_worker",
    )
    service.create_activity(_config(allowed_media_types=[DOCX_MEDIA_TYPE]), actor)

    artifact, _signed = service.create_upload(
        actor=actor,
        activity_id=ACTIVITY_ID,
        filename="assignment.docx",
        media_type=DOCX_MEDIA_TYPE,
        expected_byte_size=128,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )

    assert artifact.declared_media_type == DOCX_MEDIA_TYPE
