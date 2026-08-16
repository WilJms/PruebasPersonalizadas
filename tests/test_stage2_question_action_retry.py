from __future__ import annotations

from datetime import timedelta
import json

from fastapi.testclient import TestClient

from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import GatewayTimeout
from comprehension_verification.web.repository import utc_now
from tests.test_stage2_web import (
    TENANT_ID,
    _app,
    _login,
    _mutating,
    _processed_submission,
)


def test_question_action_cancellation_wins_without_persisting_failed_action(
    monkeypatch,
) -> None:
    app = _app()
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _login(client)
        fixture = _processed_submission(
            client,
            headers,
            subject_ref="question_action_cancelled",
        )
        assessment_id = fixture["assessment_id"]
        question_id = fixture["review"]["assessment"]["questions"][0][
            "question_id"
        ]
        service = app.state.runtime.service
        repository = app.state.runtime.repository
        original_gateway_stage = service._gateway_stage
        cancelled_job_ids: list[str] = []

        async def cancel_before_generation(job, prompt_id: str, *args, **kwargs):
            if prompt_id == "P07_QUESTION_BUILD_V1":
                cancelled_job_ids.append(job.id)
                repository.request_job_cancel(
                    job_id=job.id,
                    tenant_id=TENANT_ID,
                    actor_id="usr_stage2_cancel_test",
                    control_id="control_question_action_cancel_test",
                )
            return await original_gateway_stage(job, prompt_id, *args, **kwargs)

        monkeypatch.setattr(service, "_gateway_stage", cancel_before_generation)
        cancelled = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "SYNTHETIC_COOPERATIVE_CANCEL",
            },
        )

        assert cancelled.status_code == 409, cancelled.text
        assert cancelled.json()["code"] == "JOB_CANCELLED"
        assert len(cancelled_job_ids) == 1
        job = repository.job_control(cancelled_job_ids[0], TENANT_ID)
        assert job.control_state == "CANCELLED"
        assert job.failure_class == "CANCELLATION"
        assert repository.question_review_actions(
            tenant_id=TENANT_ID,
            assessment_id=assessment_id,
            question_id=question_id,
        ) == []
        unchanged = client.get(
            f"/api/v1/submissions/{fixture['submission_id']}/assessment"
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["assessment_version"] == 1


def test_question_action_terminal_rollback_survives_lease_and_retries(
    monkeypatch,
) -> None:
    """A terminal DB rollback must not destroy the retry source descriptor."""

    app = _app()
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _login(client)
        fixture = _processed_submission(
            client,
            headers,
            subject_ref="question_action_terminal_rollback",
        )
        assessment_id = fixture["assessment_id"]
        question = fixture["review"]["assessment"]["questions"][0]
        question_id = question["question_id"]
        service = app.state.runtime.service
        repository = app.state.runtime.repository
        original_gateway_stage = service._gateway_stage
        original_apply = repository.apply_question_review_action

        async def timeout_question_generation(
            job, prompt_id: str, *args, **kwargs
        ):
            if prompt_id == "P07_QUESTION_BUILD_V1":
                raise GatewayTimeout("synthetic provider detail")
            return await original_gateway_stage(job, prompt_id, *args, **kwargs)

        def rollback_terminal_transaction(*_args, **_kwargs):
            raise ConnectionError("synthetic terminal transaction detail")

        monkeypatch.setattr(service, "_gateway_stage", timeout_question_generation)
        monkeypatch.setattr(
            repository,
            "apply_question_review_action",
            rollback_terminal_transaction,
        )
        failed = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "SYNTHETIC_TRANSIENT_REGENERATION",
                "note": "Synthetic reviewer note retained only in the protected descriptor.",
            },
        )
        monkeypatch.setattr(service, "_gateway_stage", original_gateway_stage)
        monkeypatch.setattr(
            repository, "apply_question_review_action", original_apply
        )

        assert failed.status_code == 500, failed.text
        assert "synthetic" not in failed.text.lower()
        source_events = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question_action.executed",
            aggregate_id=None,
        )
        source_event = source_events[-1]
        source_job = repository.job_control(source_event.aggregate_id, TENANT_ID)
        descriptor = repository.question_action_descriptor(
            job_id=source_job.id, tenant_id=TENANT_ID
        )
        assert source_job.status == "RUNNING"
        assert descriptor is not None and descriptor.output is not None
        assert descriptor.output_hash == source_event.payload["descriptor_hash"]
        assert "note" not in source_event.payload
        assert "replacement" not in source_event.payload
        assert repository.question_review_actions(
            tenant_id=TENANT_ID,
            assessment_id=assessment_id,
            question_id=question_id,
        ) == []

        assert repository.reconcile_stale_jobs(
            lease_seconds=300,
            now=utc_now() + timedelta(seconds=301),
        ) == 1
        control = client.get(f"/api/v1/jobs/{source_job.id}/control")
        assert control.status_code == 200, control.text
        assert control.json()["failure_class"] == "TRANSIENT"
        assert control.json()["allowed_actions"] == ["RETRY"]

        retried = client.post(
            f"/api/v1/jobs/{source_job.id}:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "SYNTHETIC_RETRY_AFTER_TERMINAL_ROLLBACK",
                "target_stage": "QUESTION_GENERATE",
            },
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["job"]["status"] == "SUCCEEDED"
        assert retried.json()["job"]["attempt"] == 2
        retry_job_id = retried.json()["job"]["job_id"]
        assert repository.question_action_descriptor(
            job_id=retry_job_id, tenant_id=TENANT_ID
        ) is not None

        refreshed = client.get(
            f"/api/v1/submissions/{fixture['submission_id']}/assessment"
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["assessment_version"] == 2
        assert refreshed.json()["assessment"]["question_count"] == 1
        assert len(refreshed.json()["assessment"]["questions"]) == 1
        history = repository.question_review_actions(
            tenant_id=TENANT_ID,
            assessment_id=assessment_id,
            question_id=question_id,
        )
        assert len(history) == 1
        applied = m.QuestionReviewActionRecord.model_validate(history[0].data)
        assert applied.status == m.QuestionReviewRecordStatus.APPLIED
        retry_events = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question_action.executed",
            aggregate_id=retry_job_id,
        )
        assert retry_events[-1].payload["logical_action_id"] == (
            source_event.payload["logical_action_id"]
        )

        limited = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(
                headers, **{"If-Match": refreshed.headers["etag"]}
            ),
            json={
                "action": "REGENERATE",
                "reason_code": "SECOND_LOGICAL_REGENERATION",
            },
        )
        assert limited.status_code == 200, limited.text
        limited_record = m.QuestionReviewActionRecord.model_validate(
            limited.json()["action_record"]
        )
        assert limited_record.status == m.QuestionReviewRecordStatus.FAILED
        assert [item.code for item in limited_record.diagnostics] == [
            "LOCAL_REGENERATION_LIMIT"
        ]


def test_edit_retry_reconstructs_protected_replacement_after_terminal_rollback(
    monkeypatch,
) -> None:
    """The content-free audit points to the exact protected EDIT snapshot."""

    app = _app()
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _login(client)
        fixture = _processed_submission(
            client,
            headers,
            subject_ref="question_edit_terminal_rollback",
        )
        assessment_id = fixture["assessment_id"]
        question = fixture["review"]["assessment"]["questions"][0]
        replacement = json.loads(json.dumps(question))
        replacement["question_text"] = (
            "Explique el mecanismo observable usando solo la evidencia anclada."
        )
        service = app.state.runtime.service
        repository = app.state.runtime.repository
        original_apply = repository.apply_question_review_action

        def rollback_terminal_transaction(*_args, **_kwargs):
            raise ConnectionError("synthetic terminal transaction detail")

        monkeypatch.setattr(
            repository,
            "apply_question_review_action",
            rollback_terminal_transaction,
        )
        failed = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question['question_id']}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "EDIT",
                "note": "Edición sintética que debe sobrevivir al rollback.",
                "replacement": replacement,
            },
        )
        monkeypatch.setattr(
            repository, "apply_question_review_action", original_apply
        )
        assert failed.status_code == 500, failed.text

        source_event = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question_action.executed",
            aggregate_id=None,
        )[-1]
        source_job = repository.job_control(source_event.aggregate_id, TENANT_ID)
        descriptor = repository.question_action_descriptor(
            job_id=source_job.id, tenant_id=TENANT_ID
        )
        assert descriptor is not None and descriptor.output is not None
        protected_action = m.QuestionReviewAction.model_validate(
            descriptor.output["action"]
        )
        assert protected_action.replacement == m.SelectedQuestion.model_validate(
            replacement
        )
        assert "note" not in source_event.payload

        assert repository.reconcile_stale_jobs(
            lease_seconds=300,
            now=utc_now() + timedelta(seconds=301),
        ) == 1
        retried = client.post(
            f"/api/v1/jobs/{source_job.id}:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "SYNTHETIC_EDIT_RETRY_AFTER_ROLLBACK",
                "target_stage": "QUESTION_GENERATE",
            },
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["job"]["status"] == "SUCCEEDED"
        action_prompt_ids = [
            item["prompt_id"]
            for item in repository.model_calls(tenant_id=TENANT_ID)
            if item["job_id"]
            in {source_job.id, retried.json()["job"]["job_id"]}
        ]
        assert action_prompt_ids == []
        assert "P08_QUESTION_REVIEW_V1" not in action_prompt_ids
        refreshed = client.get(
            f"/api/v1/submissions/{fixture['submission_id']}/assessment"
        )
        assert refreshed.status_code == 200, refreshed.text
        revised = refreshed.json()["assessment"]["questions"][0]
        assert m.SelectedQuestion.model_validate(revised) == (
            m.SelectedQuestion.model_validate(replacement)
        )
        history = repository.question_review_actions(
            tenant_id=TENANT_ID,
            assessment_id=assessment_id,
            question_id=question["question_id"],
        )
        assert len(history) == 1
        record = m.QuestionReviewActionRecord.model_validate(history[0].data)
        assert record.status == m.QuestionReviewRecordStatus.APPLIED
        assert record.action.note == (
            "Edición sintética que debe sobrevivir al rollback."
        )


def test_preprovider_descriptor_reserves_logical_regeneration_budget(
    monkeypatch,
) -> None:
    """A missing terminal record cannot be used to evade denial-of-wallet limits."""

    app = _app()
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _login(client)
        fixture = _processed_submission(
            client,
            headers,
            subject_ref="question_action_descriptor_budget",
        )
        assessment_id = fixture["assessment_id"]
        question_id = fixture["review"]["assessment"]["questions"][0][
            "question_id"
        ]
        service = app.state.runtime.service
        repository = app.state.runtime.repository
        original_gateway_stage = service._gateway_stage
        original_apply = repository.apply_question_review_action

        async def timeout_question_generation(
            job, prompt_id: str, *args, **kwargs
        ):
            if prompt_id == "P07_QUESTION_BUILD_V1":
                raise GatewayTimeout("synthetic provider detail")
            return await original_gateway_stage(job, prompt_id, *args, **kwargs)

        def rollback_terminal_transaction(*_args, **_kwargs):
            raise ConnectionError("synthetic terminal transaction detail")

        monkeypatch.setattr(service, "_gateway_stage", timeout_question_generation)
        monkeypatch.setattr(
            repository,
            "apply_question_review_action",
            rollback_terminal_transaction,
        )
        first = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "SYNTHETIC_BUDGET_RESERVATION",
            },
        )
        monkeypatch.setattr(service, "_gateway_stage", original_gateway_stage)
        monkeypatch.setattr(
            repository, "apply_question_review_action", original_apply
        )
        assert first.status_code == 500, first.text
        assert repository.question_review_actions(
            tenant_id=TENANT_ID,
            assessment_id=assessment_id,
            question_id=question_id,
        ) == []

        rotated = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "ROTATED_IDEMPOTENCY_KEY",
            },
        )
        assert rotated.status_code == 200, rotated.text
        record = m.QuestionReviewActionRecord.model_validate(
            rotated.json()["action_record"]
        )
        assert record.status == m.QuestionReviewRecordStatus.FAILED
        assert [item.code for item in record.diagnostics] == [
            "LOCAL_REGENERATION_LIMIT"
        ]


def test_retry_chain_uses_ancestor_descriptor_when_attempt_two_prepare_fails(
    monkeypatch,
) -> None:
    """A transient pre-provider outage on a retry does not sever its lineage."""

    app = _app()
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _login(client)
        fixture = _processed_submission(
            client,
            headers,
            subject_ref="question_action_retry_descriptor_lineage",
        )
        assessment_id = fixture["assessment_id"]
        question_id = fixture["review"]["assessment"]["questions"][0][
            "question_id"
        ]
        service = app.state.runtime.service
        repository = app.state.runtime.repository
        original_gateway_stage = service._gateway_stage
        original_prepare = repository.prepare_question_action_job

        async def timeout_question_generation(
            job, prompt_id: str, *args, **kwargs
        ):
            if prompt_id == "P07_QUESTION_BUILD_V1":
                raise GatewayTimeout("synthetic provider detail")
            return await original_gateway_stage(job, prompt_id, *args, **kwargs)

        monkeypatch.setattr(service, "_gateway_stage", timeout_question_generation)
        first = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "SYNTHETIC_FIRST_TIMEOUT",
            },
        )
        monkeypatch.setattr(service, "_gateway_stage", original_gateway_stage)
        assert first.status_code == 200, first.text
        first_record = m.QuestionReviewActionRecord.model_validate(
            first.json()["action_record"]
        )
        assert first_record.status == m.QuestionReviewRecordStatus.FAILED
        source_event = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question_action.executed",
            aggregate_id=None,
        )[-1]
        source_job = repository.job_control(source_event.aggregate_id, TENANT_ID)
        assert source_job.status == "FAILED"
        assert source_job.failure_class == "TRANSIENT"

        def fail_retry_preparation(*args, **kwargs):
            if kwargs.get("create_job") is False:
                raise ConnectionError("synthetic descriptor transaction outage")
            return original_prepare(*args, **kwargs)

        monkeypatch.setattr(
            repository, "prepare_question_action_job", fail_retry_preparation
        )
        second = client.post(
            f"/api/v1/jobs/{source_job.id}:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "SYNTHETIC_RETRY_PREPARE_FAILURE",
                "target_stage": "QUESTION_GENERATE",
            },
        )
        monkeypatch.setattr(
            repository, "prepare_question_action_job", original_prepare
        )
        assert second.status_code == 200, second.text
        assert second.json()["job"]["attempt"] == 2
        assert second.json()["job"]["status"] == "FAILED"
        assert second.json()["failure_class"] == "TRANSIENT"
        second_job_id = second.json()["job"]["job_id"]
        assert repository.question_action_descriptor(
            job_id=second_job_id, tenant_id=TENANT_ID
        ) is None

        third = client.post(
            f"/api/v1/jobs/{second_job_id}:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "SYNTHETIC_RETRY_FROM_ANCESTOR_DESCRIPTOR",
                "target_stage": "QUESTION_GENERATE",
            },
        )
        assert third.status_code == 200, third.text
        assert third.json()["job"]["attempt"] == 3
        assert third.json()["job"]["status"] == "SUCCEEDED"
        third_job_id = third.json()["job"]["job_id"]
        third_events = repository.audit_events(
            tenant_id=TENANT_ID,
            event_type="question_action.executed",
            aggregate_id=third_job_id,
        )
        assert third_events[-1].payload["logical_action_id"] == (
            source_event.payload["logical_action_id"]
        )
        exhausted = client.post(
            f"/api/v1/jobs/{third_job_id}:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "FOURTH_ATTEMPT_FORBIDDEN",
                "target_stage": "QUESTION_GENERATE",
            },
        )
        assert exhausted.status_code == 409, exhausted.text
        assert exhausted.json()["code"] == "JOB_CONTROL_NOT_ALLOWED"
