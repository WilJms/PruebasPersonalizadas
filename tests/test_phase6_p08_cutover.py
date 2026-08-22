from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from comprehension_verification.canonical import stable_id
from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import (
    AdapterResult,
    DeterministicMockAdapter,
    GatewayConfig,
    GatewayContextError,
    GatewayMode,
    MockBehavior,
    ModelGateway,
    build_mock_request,
    build_trusted_context,
)
from comprehension_verification.web.repository import (
    GeneratedQuestionRow,
    NotFound,
    QuestionReviewRow,
    Repository,
    utc_now,
)
from tests.test_stage2_web import (
    TENANT_ID,
    _app,
    _approve_blueprint,
    _create_activity,
    _login,
    _mutating,
    _upload,
)


class _SequencedP07Adapter(DeterministicMockAdapter):
    """Return bounded synthetic P07 outcomes without any network transport."""

    def __init__(self, outcomes: list[str]) -> None:
        super().__init__()
        self.outcomes = outcomes
        self.p07_calls = 0
        self.prompt_ids: list[str] = []

    async def invoke(self, **kwargs: Any) -> AdapterResult:
        prompt_id = str(kwargs["prompt_id"])
        self.prompt_ids.append(prompt_id)
        if prompt_id != "P07_QUESTION_BUILD_V1":
            return await super().invoke(**kwargs)

        request = kwargs["request"]
        outcome = self.outcomes[min(self.p07_calls, len(self.outcomes) - 1)]
        self.p07_calls += 1
        behavior = (
            MockBehavior.ABSTAIN
            if outcome == "replacement"
            else MockBehavior.HAPPY
        )
        draft = self.factory.output_for(prompt_id, request, behavior)
        if outcome == "local_duplicate":
            first = draft.expected_observables[0]
            draft = draft.model_copy(
                update={"expected_observables": [first, first]}
            )
        elif outcome == "scope_mismatch":
            draft = draft.model_copy(update={"scope_alias": "S" + "0" * 24})
        raw = draft.model_dump(mode="json")
        encoded = json.dumps(raw, sort_keys=True).encode()
        return AdapterResult(
            raw_output=raw,
            input_tokens=max(1, len(request.model_dump_json()) // 4),
            cached_input_tokens=0,
            output_tokens=max(1, len(encoded) // 4),
        )


def _prepare_submission(
    client: TestClient,
    headers: dict[str, str],
    *,
    question_count: int = 1,
) -> tuple[str, str]:
    activity_id = _create_activity(
        client, headers, question_count=question_count
    )
    _approve_blueprint(client, headers, activity_id)
    created = client.post(
        f"/api/v1/activities/{activity_id}/submissions:batch",
        headers=_mutating(headers),
        json={"subject_refs": ["phase6_synthetic_subject"]},
    )
    assert created.status_code == 201, created.text
    submission_id = created.json()["submissions"][0]["submission_id"]
    deliverable = (
        b"# Entrega\n\nLa deduplicacion ocurre antes del promedio para evitar "
        b"doble peso.\n\nLos valores extremos se conservan para revision.\n\n"
        b"Cada fila mantiene el identificador de origen para trazabilidad.\n"
    )
    _upload(
        client,
        headers,
        start_path=f"/api/v1/submissions/{submission_id}/artifacts/uploads",
        complete_path=(
            f"/api/v1/submissions/{submission_id}/artifacts/"
            "{artifact_id}:complete"
        ),
        role="SUBMISSION",
        filename="submission.md",
        content=deliverable,
    )
    return activity_id, submission_id


def _install_adapter(app: Any, adapter: _SequencedP07Adapter) -> Repository:
    repository: Repository = app.state.runtime.repository
    service = app.state.runtime.service
    service.gateway_factory = lambda job_id: ModelGateway(
        GatewayConfig(
            mode=GatewayMode.MOCK,
            job_id=job_id,
            max_retries=0,
        ),
        mock_adapter=adapter,
        ledger_sink=repository.model_call_sink,
    )
    return repository


def _run_submission(
    client: TestClient, headers: dict[str, str], submission_id: str
) -> tuple[str, dict[str, Any]]:
    started = client.post(
        f"/api/v1/submissions/{submission_id}:run",
        headers=_mutating(headers),
        json={},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    status = client.get(f"/api/v1/jobs/{job_id}")
    assert status.status_code == 200, status.text
    return job_id, status.json()["job"]


def test_p07_replacement_consumes_one_reserve_and_still_assembles_exact_n() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        _activity_id, submission_id = _prepare_submission(client, headers)
        adapter = _SequencedP07Adapter(["replacement", "happy"])
        repository = _install_adapter(app, adapter)

        job_id, job = _run_submission(client, headers, submission_id)

        assert job["status"] == "SUCCEEDED", job
        view = client.get(f"/api/v1/submissions/{submission_id}/assessment")
        assert view.status_code == 200, view.text
        assert view.json()["assessment"]["question_count"] == 1
        assert len(view.json()["assessment"]["questions"]) == 1
        assert view.json()["reviews"] == []
        assert adapter.prompt_ids == [
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P07_QUESTION_BUILD_V1",
        ]
        assert "P08_QUESTION_REVIEW_V1" not in adapter.prompt_ids
        reserve_events = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question.reserve.consumed",
            aggregate_id=job_id,
        )
        assert len(reserve_events) == 1
        assert reserve_events[0].payload["reason_code"] == (
            "P07_REPLACEMENT_REQUIRED"
        )
        stages = repository.stage_runs_for_job(job_id, TENANT_ID)
        stage_names = [row.stage for row in stages]
        assert "P09_GUIDE_BUILD_V1" not in stage_names
        assert not repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question.review.decision_observed",
            aggregate_id=job_id,
        )


def test_question_local_failure_uses_reserve_but_scope_failure_fails_closed() -> None:
    recoverable_app = _app()
    with TestClient(recoverable_app) as client:
        headers = _login(client)
        _activity_id, submission_id = _prepare_submission(client, headers)
        adapter = _SequencedP07Adapter(["local_duplicate", "happy"])
        repository = _install_adapter(recoverable_app, adapter)

        job_id, job = _run_submission(client, headers, submission_id)

        assert job["status"] == "SUCCEEDED", job
        reserve_events = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question.reserve.consumed",
            aggregate_id=job_id,
        )
        assert [row.payload["reason_code"] for row in reserve_events] == [
            "P07_OBSERVABLE_DUPLICATE"
        ]
        assert "P08_QUESTION_REVIEW_V1" not in adapter.prompt_ids

    blocked_app = _app()
    with TestClient(blocked_app) as client:
        headers = _login(client)
        _activity_id, submission_id = _prepare_submission(client, headers)
        adapter = _SequencedP07Adapter(["scope_mismatch", "happy"])
        repository = _install_adapter(blocked_app, adapter)

        job_id, job = _run_submission(client, headers, submission_id)

        assert job["status"] == "FAILED", job
        assert repository.job_control(job_id, TENANT_ID).failure_class == (
            "SECURITY"
        )
        assert adapter.p07_calls == 1
        assert "P08_QUESTION_REVIEW_V1" not in adapter.prompt_ids
        assert not repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question.reserve.consumed",
            aggregate_id=job_id,
        )
        with pytest.raises(NotFound):
            repository.latest_assessment(submission_id, TENANT_ID)


def test_exhausted_p07_replacements_never_publish_partial_assessment() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        _activity_id, submission_id = _prepare_submission(client, headers)
        adapter = _SequencedP07Adapter(["replacement"])
        repository = _install_adapter(app, adapter)

        job_id, job = _run_submission(client, headers, submission_id)

        assert job["status"] == "NEEDS_REVIEW", job
        assert adapter.p07_calls > 1
        assert "P08_QUESTION_REVIEW_V1" not in adapter.prompt_ids
        with pytest.raises(NotFound):
            repository.latest_assessment(submission_id, TENANT_ID)
        state = client.get(f"/api/v1/submissions/{submission_id}").json()[
            "submission"
        ]
        assert state["status"] == "ASSESSMENT_PLAN_INFEASIBLE"
        reserve_events = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question.reserve.consumed",
            aggregate_id=job_id,
        )
        assert len(reserve_events) == adapter.p07_calls - 1


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT", "ESCALATE"])
@pytest.mark.parametrize("resume_from_stage", ["QUESTION_REVIEW", "GUIDE_BUILD"])
def test_legacy_question_review_resume_ignores_historical_decision(
    decision: str,
    resume_from_stage: str,
) -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        _activity_id, submission_id = _prepare_submission(client, headers)
        adapter = _SequencedP07Adapter(["happy"])
        repository = _install_adapter(app, adapter)
        service = app.state.runtime.service
        validate_stage = service._validate_question_stage

        def crash_after_current_p07(**kwargs: Any) -> None:
            validate_stage(**kwargs)
            raise TimeoutError("synthetic legacy cutover crash")

        service._validate_question_stage = crash_after_current_p07
        source_job_id, source_job = _run_submission(
            client, headers, submission_id
        )
        service._validate_question_stage = validate_stage
        assert source_job["status"] == "FAILED", source_job

        p07_stage = next(
            row
            for row in repository.stage_runs_for_job(source_job_id, TENANT_ID)
            if row.stage.startswith("P07_QUESTION_BUILD_V1:")
            and row.status == "SUCCEEDED"
        )
        assert p07_stage.output is not None
        generation = m.QuestionGenerationResult.model_validate(p07_stage.output)
        assert generation.candidate is not None
        historical = m.QuestionReviewResult(
            submission_id=submission_id,
            opportunity_id=generation.opportunity_id,
            status="READY",
            review=m.QuestionSemanticReview(
                candidate_id=generation.candidate.candidate_id,
                decision=m.ReviewDecision(decision),
                scores=m.QuestionScores(
                    groundedness=0.9,
                    anchor_sufficiency=0.9,
                    criterion_relevance=0.9,
                    answerability=0.9,
                    cognitive_demand=0.9,
                    submission_specificity=0.9,
                    clarity=0.9,
                    accessibility=0.9,
                    discriminative_potential=0.9,
                    guide_observability=0.9,
                ),
                estimated_difficulty=generation.candidate.difficulty,
                estimated_minutes=generation.candidate.estimated_minutes,
                confidence=0.9,
                evidence_ids=list(generation.candidate.evidence_ids),
            ),
        )
        question_id = stable_id(
            "question", submission_id, generation.candidate.candidate_id
        )
        repository.save_generated_question_and_review(
            question=GeneratedQuestionRow(
                id=generation.candidate.candidate_id,
                tenant_id=TENANT_ID,
                submission_id=submission_id,
                data=generation.model_dump(mode="json"),
            ),
            review=QuestionReviewRow(
                question_id=question_id,
                tenant_id=TENANT_ID,
                submission_id=submission_id,
                data=historical.model_dump(mode="json"),
            ),
        )

        retry = repository.schedule_job_retry(
            job_id=source_job_id,
            tenant_id=TENANT_ID,
            resulting_job_id=(
                f"job_phase6_legacy_{decision.lower()}_"
                f"{resume_from_stage.lower()}"
            ),
            control_id=(
                f"control_phase6_legacy_{decision.lower()}_"
                f"{resume_from_stage.lower()}"
            ),
            actor_id="usr_stage2_teacher",
            reason_code="PHASE6_P08_RUNTIME_CUTOVER",
            failure_class="TRANSIENT",
            next_attempt_at=utc_now(),
            resume_from_stage=resume_from_stage,
        )
        asyncio.run(service.process_job(retry.id))

        terminal = repository.job_status(retry.id, TENANT_ID)
        assert terminal.status == "SUCCEEDED", terminal.diagnostics
        view = client.get(f"/api/v1/submissions/{submission_id}/assessment")
        assert view.status_code == 200, view.text
        assert view.json()["assessment"]["status"] == "NEEDS_REVIEW"
        assert view.json()["reviews"][0]["decision"] == decision
        assert [item for item in adapter.prompt_ids if item.startswith("P07")] == [
            "P07_QUESTION_BUILD_V1"
        ]
        assert "P08_QUESTION_REVIEW_V1" not in adapter.prompt_ids
        assert adapter.prompt_ids[-1] == "P07_QUESTION_BUILD_V1"
        assert repository.has_audit_event(
            tenant_id=TENANT_ID,
            event_type="stage.reused",
            aggregate_id=retry.id,
            payload_contains={"stage": p07_stage.stage},
        )
        with repository.session() as session:
            generated_count = session.scalar(
                select(func.count())
                .select_from(GeneratedQuestionRow)
                .where(
                    GeneratedQuestionRow.tenant_id == TENANT_ID,
                    GeneratedQuestionRow.submission_id == submission_id,
                )
            )
        assert generated_count == 1


def test_historical_p08_accept_cannot_make_invalid_cached_p07_current() -> None:
    request = build_mock_request("P07_QUESTION_BUILD_V1")
    gateway = ModelGateway()
    output = asyncio.run(
        gateway.invoke(
            "P07_QUESTION_BUILD_V1",
            request,
            build_trusted_context(request),
        )
    ).output.model_dump(mode="json")
    output["candidate"]["candidate_id"] = "candidate_from_old_boundary"
    historical_request = build_mock_request("P08_QUESTION_REVIEW_V1")
    historical_accept = DeterministicMockAdapter().factory.output_for(
        "P08_QUESTION_REVIEW_V1",
        historical_request,
        MockBehavior.HAPPY,
    )
    assert historical_accept.review is not None
    assert historical_accept.review.decision == m.ReviewDecision.ACCEPT
    repository = Repository("sqlite+pysqlite://")
    repository.save_generated_question_and_review(
        question=GeneratedQuestionRow(
            id="candidate_from_old_boundary",
            tenant_id="tnt_old_boundary",
            submission_id="sub_old_boundary",
            data=output,
        ),
        review=QuestionReviewRow(
            question_id="question_old_boundary",
            tenant_id="tnt_old_boundary",
            submission_id="sub_old_boundary",
            data=historical_accept.model_dump(mode="json"),
        ),
    )
    assert repository.review_rows("sub_old_boundary", "tnt_old_boundary")

    with pytest.raises(GatewayContextError):
        gateway.validate_cached_output(
            "P07_QUESTION_BUILD_V1",
            request,
            build_trusted_context(request),
            output,
        )
