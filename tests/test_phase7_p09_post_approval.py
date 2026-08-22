from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from comprehension_verification.canonical import stable_id
from comprehension_verification.contracts import models as m
from comprehension_verification.guide_generation import (
    GuideGenerationCompilationError,
    build_guide_alias_envelope,
    materialize_guide_draft,
    validate_materialized_guide,
)
from comprehension_verification.model_gateway import (
    DeterministicMockAdapter,
    GatewayConfig,
    GatewayMode,
    MockBehavior,
    ModelGateway,
    build_mock_request,
)
from comprehension_verification.model_gateway.mock_factory import AdapterResult
from comprehension_verification.pipeline_authority import (
    DISABLED_MODEL_STAGE_IDS,
    TARGET_INACTIVE_MODEL_STAGE_IDS,
    TARGET_SUBMISSION_PIPELINE,
)
from comprehension_verification.web.auth import Actor
from comprehension_verification.web.jobs import RecordingJobRunner
from comprehension_verification.web.repository import (
    AssessmentRow,
    GuideRow,
    JobRow,
    NotFound,
    Repository,
    SubmissionRow,
    utc_now,
)
from comprehension_verification.web.workflows import WorkflowError, _etag
from tests.test_stage2_web import (
    TENANT_ID,
    _app,
    _login,
    _mutating,
    _processed_submission,
    _verify_all_evidence,
)


def _teacher_actor() -> Actor:
    return Actor(
        user_id=stable_id("usr", "teacher@example.test"),
        email="teacher@example.test",
        workspace_id=TENANT_ID,
        role="TEACHER",
        can_approve_assessments=True,
        csrf_token="phase7-synthetic-csrf",
    )


def _p09_calls(repository: Repository) -> list[Any]:
    return [
        item
        for item in repository.model_calls(tenant_id=TENANT_ID)
        if item["prompt_id"] == "P09_GUIDE_BUILD_V1"
    ]


def _guide_job_rows(repository: Repository, submission_id: str) -> list[JobRow]:
    with repository.session() as session:
        return list(
            session.scalars(
                select(JobRow).where(
                    JobRow.tenant_id == TENANT_ID,
                    JobRow.aggregate_id == submission_id,
                    JobRow.kind == "GUIDE_BUILD",
                )
            )
        )


def _guide_row_count(repository: Repository, assessment_id: str) -> int:
    with repository.session() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(GuideRow)
                .where(
                    GuideRow.tenant_id == TENANT_ID,
                    GuideRow.assessment_id == assessment_id,
                )
            )
            or 0
        )


class _P09OutcomeAdapter(DeterministicMockAdapter):
    """Offline adapter for semantic abstention or an invalid local alias."""

    def __init__(self, outcome: str) -> None:
        super().__init__()
        self.outcome = outcome

    async def invoke(self, **kwargs: Any) -> AdapterResult:
        result = await super().invoke(**kwargs)
        if kwargs["prompt_id"] != "P09_GUIDE_BUILD_V1":
            return result
        raw = json.loads(json.dumps(result.raw_output))
        if self.outcome == "needs_review":
            raw = {
                "scope_alias": raw["scope_alias"],
                "status": "NEEDS_REVIEW",
                "items": [],
                "abstention_reason": (
                    "La evidencia local no permite completar todos los niveles."
                ),
            }
        elif self.outcome == "unknown_evidence_alias":
            raw["items"][0]["additional_observables"] = [
                {
                    "observable_alias": "N1",
                    "description": "Un observable fuera de la frontera local.",
                    "support_evidence_aliases": ["E99"],
                    "required_for_level_2": False,
                }
            ]
        else:  # pragma: no cover - protects the test adapter itself
            raise AssertionError(f"unknown P09 outcome: {self.outcome}")
        return replace(result, raw_output=raw)


def _install_adapter(app: Any, adapter: DeterministicMockAdapter) -> None:
    repository: Repository = app.state.runtime.repository
    app.state.runtime.service.gateway_factory = lambda job_id: ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, job_id=job_id, max_retries=0),
        mock_adapter=adapter,
        ledger_sink=repository.model_call_sink,
    )


def test_p09_waits_for_final_approval_and_runs_once_for_n_plus_two_calls() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers, question_count=2)
        repository: Repository = app.state.runtime.repository

        submission_calls = repository.model_calls(
            tenant_id=TENANT_ID, job_id=fixture["job_id"]
        )
        assert [item["prompt_id"] for item in submission_calls].count(
            "P06_EVIDENCE_MAP_V1"
        ) == 1
        assert [item["prompt_id"] for item in submission_calls].count(
            "P07_QUESTION_BUILD_V1"
        ) == 2
        assert not _p09_calls(repository)
        assert _guide_row_count(repository, fixture["assessment_id"]) == 0
        assert fixture["review"]["assessment"]["status"] == "NEEDS_REVIEW"
        assert fixture["review"]["guide"] is None
        assert fixture["review"]["guide_status"] == "NOT_AVAILABLE"

        current = fixture["review"]
        current_etag = fixture["etag"]
        question_id = current["assessment"]["questions"][0]["question_id"]
        for edit_number in range(1, 4):
            replacement = json.loads(
                json.dumps(current["assessment"]["questions"][0])
            )
            replacement["question_text"] = (
                "Explique la relación observable usando solo la evidencia "
                f"anclada. Ajuste docente {edit_number}."
            )
            edited = client.post(
                (
                    f"/api/v1/assessments/{fixture['assessment_id']}/questions/"
                    f"{question_id}/actions"
                ),
                headers=_mutating(
                    headers,
                    **{"If-Match": current_etag},
                ),
                json={
                    "action": "EDIT",
                    "note": f"Edición sintética {edit_number}.",
                    "replacement": replacement,
                },
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["action_record"]["status"] == "APPLIED"
            current = edited.json()["bundle"]
            current_etag = edited.headers["etag"]
            assert current["guide"] is None
            assert current["guide_status"] == "NOT_AVAILABLE"
            assert not _p09_calls(repository)
            assert _guide_row_count(repository, fixture["assessment_id"]) == 0

        final_fixture = {
            **fixture,
            "review": current,
            "etag": current_etag,
        }
        _verify_all_evidence(client, headers, final_fixture)
        approved = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(headers, **{"If-Match": current_etag}),
            json={},
        )
        assert approved.status_code == 200, approved.text
        approved_body = approved.json()
        assert approved_body["assessment"]["status"] == "APPROVED"
        assert approved_body["guide_status"] == "READY"
        assert approved_body["guide_job_id"]
        assert len(_guide_job_rows(repository, fixture["submission_id"])) == 1
        assert len(_p09_calls(repository)) == 1

        repeated = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(
                headers,
                **{"If-Match": approved.headers["etag"]},
            ),
            json={},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["guide_job_id"] == approved_body["guide_job_id"]
        assert len(_guide_job_rows(repository, fixture["submission_id"])) == 1
        assert len(_p09_calls(repository)) == 1

        guide = m.EvaluationGuide.model_validate(repeated.json()["guide"])
        approved_assessment = m.Assessment.model_validate(
            repeated.json()["assessment"]
        )
        assert guide.binding is not None
        assert guide.binding.assessment_version == repeated.json()[
            "assessment_version"
        ]
        assert guide.binding.assessment_etag == repeated.json()["etag"]
        for question, item in zip(
            approved_assessment.questions, guide.items, strict=True
        ):
            core = question.preliminary_guide.observable_elements
            assert item.guide.observable_elements[: len(core)] == core
            assert [level.level for level in item.guide.levels] == [0, 1, 2, 3]
            assert item.guide.acceptance_conditions
            assert item.guide.cannot_infer

        logical_calls = [
            item
            for item in repository.model_calls(tenant_id=TENANT_ID)
            if item["prompt_id"]
            in {
                "P06_EVIDENCE_MAP_V1",
                "P07_QUESTION_BUILD_V1",
                "P09_GUIDE_BUILD_V1",
            }
        ]
        assert len(logical_calls) == approved_assessment.question_count + 2
        assert "P05" in TARGET_INACTIVE_MODEL_STAGE_IDS
        assert "P08" in TARGET_INACTIVE_MODEL_STAGE_IDS
        assert DISABLED_MODEL_STAGE_IDS == ("P10",)
        assert TARGET_SUBMISSION_PIPELINE[-2:] == (
            "TEACHER_ASSESSMENT_APPROVAL",
            "P09_POST_APPROVAL_GUIDE_ENRICHMENT",
        )

        current_row = repository.assessment_by_id(
            fixture["assessment_id"], TENANT_ID
        )
        active_guide = repository.guide_for_approved_version(current_row)
        with repository.session() as session:
            tampered_row = session.get(GuideRow, active_guide.guide_id)
            assert tampered_row is not None
            tampered_row.guide_policy_hash = "sha256:" + "0" * 64
        with pytest.raises(NotFound):
            repository.guide_for_approved_version(current_row)


def test_teacher_regeneration_before_approval_never_calls_p09() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        repository: Repository = app.state.runtime.repository
        question_id = fixture["review"]["assessment"]["questions"][0][
            "question_id"
        ]

        regenerated = client.post(
            (
                f"/api/v1/assessments/{fixture['assessment_id']}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "PHASE7_PREAPPROVAL_REGENERATION",
                "note": "Usar una oportunidad de reserva sintética.",
            },
        )

        assert regenerated.status_code == 200, regenerated.text
        assert regenerated.json()["action_record"]["status"] == "APPLIED"
        assert regenerated.json()["bundle"]["assessment"]["status"] == (
            "NEEDS_REVIEW"
        )
        assert regenerated.json()["bundle"]["guide"] is None
        assert not _p09_calls(repository)
        assert _guide_row_count(repository, fixture["assessment_id"]) == 0


def test_submission_job_cannot_reach_post_approval_p09() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        repository: Repository = app.state.runtime.repository
        submission_job = repository.get(JobRow, fixture["job_id"])
        request = build_mock_request("P09_GUIDE_BUILD_V1")
        assert isinstance(submission_job, JobRow)
        assert isinstance(request, m.GuideBuildRequest)

        with pytest.raises(WorkflowError) as captured:
            asyncio.run(
                app.state.runtime.service._gateway_stage(
                    submission_job,
                    "P09_GUIDE_BUILD_V1",
                    request,
                    m.EvaluationGuide,
                )
            )

        assert captured.value.code == "P09_POST_APPROVAL_JOB_REQUIRED"
        assert not _p09_calls(repository)


def test_p09_alias_dto_preserves_core_and_rejects_scope_widening() -> None:
    request = build_mock_request("P09_GUIDE_BUILD_V1")
    assert isinstance(request, m.GuideBuildRequest)
    envelope = build_guide_alias_envelope(request)
    serialized_envelope = json.dumps(envelope.model_dump(mode="json"))
    for canonical_value in (
        request.guide_id,
        request.assessment.assessment_id,
        request.assessment.submission_id,
        request.assessment.questions[0].question_id,
        request.assessment.questions[0].evidence_ids[0],
    ):
        assert canonical_value not in serialized_envelope

    draft = DeterministicMockAdapter().factory.output_for(
        "P09_GUIDE_BUILD_V1", request, MockBehavior.HAPPY
    )
    assert isinstance(draft, m.GuideModelDraft)
    assert {
        "question_id",
        "question_text",
        "anchor",
        "locator",
        "path",
        "evidence_ids",
        "opportunity_id",
        "workflow_status",
        "approval_event_id",
    }.isdisjoint(m.GuideQuestionModelDraft.model_fields)
    with pytest.raises(ValueError):
        m.GuideAdditionalObservableDraft(
            observable_alias="N1",
            description="Intento de referencia a soporte de Q2.",
            support_evidence_aliases=["Q2.E1"],
            required_for_level_2=False,
        )
    guide = materialize_guide_draft(draft=draft, request=request)
    validate_materialized_guide(guide=guide, request=request)
    question = request.assessment.questions[0]
    item = guide.items[0]
    core = question.preliminary_guide.observable_elements
    assert item.question_id == question.question_id
    assert item.guide.purpose == question.preliminary_guide.purpose
    assert item.guide.observable_elements[: len(core)] == core
    assert [level.level for level in item.guide.levels] == [0, 1, 2, 3]
    observable_ids = {
        element.element_id for element in item.guide.observable_elements
    }
    assert all(
        set(level.observable_element_ids).issubset(observable_ids)
        for level in item.guide.levels
    )
    level_two = item.guide.levels[2]
    assert {
        element.element_id
        for element in item.guide.observable_elements
        if element.required_for_level_2
    }.issubset(level_two.observable_element_ids)
    assert item.guide.cannot_infer

    raw = draft.model_dump(mode="json")
    raw["items"][0]["additional_observables"] = [
        {
            "observable_alias": "N1",
            "description": "Pretende usar soporte exclusivo de otro ámbito.",
            "support_evidence_aliases": ["E99"],
            "required_for_level_2": False,
        }
    ]
    with pytest.raises(
        GuideGenerationCompilationError, match="outside its question"
    ):
        materialize_guide_draft(
            draft=m.GuideModelDraft.model_validate(raw), request=request
        )

    tampered = guide.model_copy(deep=True)
    tampered.items[0].guide.observable_elements[0].description = (
        "Un constructo distinto inventado después de P07."
    )
    with pytest.raises(GuideGenerationCompilationError, match="P07 core"):
        validate_materialized_guide(guide=tampered, request=request)

    generic = draft.model_dump(mode="json")
    generic["items"][0]["cannot_infer"] = [
        "No se puede determinar la autoría ni el uso de IA."
    ]
    with pytest.raises(GuideGenerationCompilationError, match="global policy"):
        materialize_guide_draft(
            draft=m.GuideModelDraft.model_validate(generic), request=request
        )


@pytest.mark.parametrize(
    (
        "outcome",
        "expected_job_status",
        "expected_guide_status",
        "expected_guide_rows",
    ),
    (
        ("needs_review", "NEEDS_REVIEW", "NEEDS_REVIEW", 1),
        ("unknown_evidence_alias", "FAILED", "FAILED", 0),
    ),
)
def test_p09_failure_never_revokes_approval_or_publishes_a_partial_ready_guide(
    outcome: str,
    expected_job_status: str,
    expected_guide_status: str,
    expected_guide_rows: int,
) -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        _install_adapter(app, _P09OutcomeAdapter(outcome))
        _verify_all_evidence(client, headers, fixture)

        approved = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={},
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["assessment"]["status"] == "APPROVED"
        assert body["guide_status"] == expected_guide_status
        assert body["guide"] is None or body["guide"]["items"] == []

        repository: Repository = app.state.runtime.repository
        jobs = _guide_job_rows(repository, fixture["submission_id"])
        assert len(jobs) == 1
        assert jobs[0].status == expected_job_status
        assert _guide_row_count(repository, fixture["assessment_id"]) == (
            expected_guide_rows
        )
        latest = repository.assessment_by_id(
            fixture["assessment_id"], TENANT_ID
        )
        assert latest.status == "APPROVED"
        state = m.SubmissionProcessingState.model_validate(
            repository.scoped(
                SubmissionRow, fixture["submission_id"], TENANT_ID
            ).state
        )
        assert state.status == m.SubmissionProcessingStatus.APPROVED
        assert state.current_stage == "GUIDE_FAILED"


def test_approval_crash_gap_reconciliation_creates_and_dispatches_one_job() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        _verify_all_evidence(client, headers, fixture)
        repository: Repository = app.state.runtime.repository
        service = app.state.runtime.service

        approved_row = service.approve_assessment(
            assessment_id=fixture["assessment_id"],
            if_match=fixture["etag"],
            actor=_teacher_actor(),
        )
        assert approved_row.status == "APPROVED"
        assert not _guide_job_rows(repository, fixture["submission_id"])

        runner = RecordingJobRunner()
        service.job_runner = runner
        assert asyncio.run(service.reconcile_approved_guide_jobs()) == 1
        assert asyncio.run(service.reconcile_approved_guide_jobs()) == 0
        jobs = _guide_job_rows(repository, fixture["submission_id"])
        assert len(jobs) == 1
        assert runner.dispatched == [jobs[0].id]
        assert not _p09_calls(repository)


def test_crash_after_p09_stage_reuses_output_and_publishes_one_logical_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        _verify_all_evidence(client, headers, fixture)
        repository: Repository = app.state.runtime.repository
        service = app.state.runtime.service
        approved_row = service.approve_assessment(
            assessment_id=fixture["assessment_id"],
            if_match=fixture["etag"],
            actor=_teacher_actor(),
        )
        service.job_runner = RecordingJobRunner()
        source = asyncio.run(
            service.ensure_approved_guide_job(
                approved_row, actor_id=_teacher_actor().user_id
            )
        )
        claimed = repository.claim_next_job()
        assert claimed is not None and claimed.id == source.id

        original_finalize = repository.finalize_guide_build

        def crash_before_projection(**_kwargs: Any) -> bool:
            raise ConnectionError("synthetic projection crash")

        monkeypatch.setattr(
            repository, "finalize_guide_build", crash_before_projection
        )
        asyncio.run(service.process_job(claimed.id))
        monkeypatch.setattr(
            repository, "finalize_guide_build", original_finalize
        )
        failed = repository.job_status(claimed.id, TENANT_ID)
        assert failed.status == "FAILED"
        assert _guide_row_count(repository, fixture["assessment_id"]) == 0
        assert len(_p09_calls(repository)) == 1

        retry = repository.schedule_job_retry(
            job_id=claimed.id,
            tenant_id=TENANT_ID,
            resulting_job_id=stable_id("job", claimed.id, "phase7_retry"),
            control_id=stable_id("control", claimed.id, "phase7_retry"),
            actor_id=_teacher_actor().user_id,
            reason_code="PHASE7_GUIDE_PROJECTION_RECOVERY",
            failure_class="TRANSIENT",
            next_attempt_at=utc_now(),
            resume_from_stage="GUIDE_BUILD",
        )
        asyncio.run(service.process_job(retry.id))
        assert repository.job_status(retry.id, TENANT_ID).status == "SUCCEEDED"
        assert _guide_row_count(repository, fixture["assessment_id"]) == 1
        assert len(_p09_calls(repository)) == 1
        assert repository.has_audit_event(
            tenant_id=TENANT_ID,
            event_type="stage.reused",
            aggregate_id=retry.id,
        )


def _legacy_guide(assessment: m.Assessment) -> m.EvaluationGuide:
    items: list[m.EvaluationGuideItem] = []
    for question in assessment.questions:
        base = question.preliminary_guide
        element_ids = [item.element_id for item in base.observable_elements]
        items.append(
            m.EvaluationGuideItem(
                question_id=question.question_id,
                guide=base.model_copy(
                    update={
                        "levels": [
                            m.GuideLevel(
                                level=level,
                                label=f"Nivel histórico {level}",
                                descriptor="Descriptor histórico legible.",
                                observable_element_ids=(
                                    [] if level == 0 else element_ids
                                ),
                            )
                            for level in range(4)
                        ]
                    }
                ),
            )
        )
    return m.EvaluationGuide(
        guide_id=stable_id("guide", assessment.assessment_id, "legacy"),
        assessment_id=assessment.assessment_id,
        submission_id=assessment.submission_id,
        status="READY",
        items=items,
        diagnostics=[],
        created_at=assessment.created_at,
    )


def test_legacy_guide_is_readable_history_but_never_current_or_exportable() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        repository: Repository = app.state.runtime.repository
        review_assessment = m.Assessment.model_validate(
            fixture["review"]["assessment"]
        )
        legacy = _legacy_guide(review_assessment)
        repository.add(
            GuideRow(
                guide_id=legacy.guide_id,
                assessment_id=legacy.assessment_id,
                tenant_id=TENANT_ID,
                submission_id=legacy.submission_id,
                assessment_version=None,
                assessment_etag=None,
                assessment_snapshot_hash=None,
                question_set_hash=None,
                approval_event_id=None,
                approval_snapshot_hash=None,
                guide_policy_hash=None,
                materializer_boundary_hash=None,
                guide_job_id=None,
                status="HISTORICAL_PREAPPROVAL",
                created_at=legacy.created_at,
                data=legacy.model_dump(mode="json"),
            )
        )
        history = client.get(
            f"/api/v1/assessments/{fixture['assessment_id']}/guide/history"
        )
        assert history.status_code == 200, history.text
        assert history.json()["items"][0]["lifecycle_status"] == (
            "HISTORICAL_PREAPPROVAL"
        )
        assert history.json()["items"][0]["guide"]["guide_id"] == legacy.guide_id

        _verify_all_evidence(client, headers, fixture)
        runner = RecordingJobRunner()
        app.state.runtime.service.job_runner = runner
        approved = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["assessment"]["status"] == "APPROVED"
        assert approved.json()["guide"] is None
        assert approved.json()["guide_status"] == "PENDING"
        current = repository.assessment_by_id(
            fixture["assessment_id"], TENANT_ID
        )
        with pytest.raises(NotFound):
            repository.guide_for_approved_version(current)

        exported = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}/exports",
            headers=_mutating(headers),
            json={"kind": "CANONICAL_JSON"},
        )
        assert exported.status_code == 409
        assert exported.json()["code"] == "GUIDE_NOT_READY"


def test_new_review_version_cannot_reuse_old_guide_and_reapproval_gets_one_new_p09() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        _verify_all_evidence(client, headers, fixture)
        first = client.post(
            f"/api/v1/assessments/{fixture['assessment_id']}:approve",
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={},
        )
        assert first.status_code == 200, first.text
        repository: Repository = app.state.runtime.repository
        old_row = repository.assessment_by_id(
            fixture["assessment_id"], TENANT_ID
        )
        old_guide = repository.guide_for_approved_version(old_row)

        old_assessment = m.Assessment.model_validate(old_row.data)
        edited_question = old_assessment.questions[0].model_copy(
            update={
                "question_text": (
                    "Explique la relación revisada usando únicamente la "
                    "evidencia anclada."
                )
            }
        )
        review_assessment = old_assessment.model_copy(
            update={
                "status": m.WorkflowStatus.NEEDS_REVIEW,
                "approved_by": None,
                "approved_at": None,
                "questions": [
                    edited_question,
                    *old_assessment.questions[1:],
                ],
            }
        )
        review_version = old_row.version + 1
        review_etag = _etag(review_assessment)
        review_row = AssessmentRow(
            row_id=stable_id(
                "assessmentrow", review_assessment.assessment_id, review_version
            ),
            assessment_id=review_assessment.assessment_id,
            tenant_id=TENANT_ID,
            submission_id=review_assessment.submission_id,
            version=review_version,
            status=m.WorkflowStatus.NEEDS_REVIEW.value,
            etag=review_etag,
            data=review_assessment.model_dump(mode="json"),
        )
        repository.add(review_row)
        submission = repository.scoped(
            SubmissionRow, fixture["submission_id"], TENANT_ID
        )
        repository.set_submission_state(
            m.SubmissionProcessingState(
                submission_id=submission.id,
                activity_id=submission.activity_id,
                status=m.SubmissionProcessingStatus.NEEDS_REVIEW,
                current_stage="ASSEMBLE",
                progress=1.0,
                active_job_id=None,
                diagnostics=[],
                updated_at=utc_now(),
            )
        )

        current_view = client.get(
            f"/api/v1/submissions/{fixture['submission_id']}/assessment"
        )
        assert current_view.status_code == 200, current_view.text
        assert current_view.json()["assessment_version"] == review_version
        assert current_view.json()["guide"] is None
        assert current_view.json()["guide_status"] == "NOT_AVAILABLE"
        with pytest.raises(NotFound):
            repository.guide_for_approved_version(review_row)
        assert repository.guide_history(
            fixture["assessment_id"], TENANT_ID
        )[0].guide_id == old_guide.guide_id

        new_fixture = {
            **fixture,
            "review": current_view.json(),
            "etag": review_etag,
        }
        _verify_all_evidence(client, headers, new_fixture)
        second_row = asyncio.run(
            app.state.runtime.service.approve_assessment_and_enqueue_guide(
                assessment_id=fixture["assessment_id"],
                if_match=review_etag,
                actor=_teacher_actor(),
            )
        )
        assert second_row.version == review_version + 1
        second_guide = repository.guide_for_approved_version(second_row)
        assert second_guide.guide_id != old_guide.guide_id
        assert second_guide.assessment_version == second_row.version
        assert len(_p09_calls(repository)) == 2
        assert len(repository.guide_history(fixture["assessment_id"], TENANT_ID)) == 2
