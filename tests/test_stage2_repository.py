from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.contracts import models as m
from comprehension_verification.web.repository import (
    ActivityRow,
    AssessmentRow,
    BulkApprovalRecordRow,
    Conflict,
    ExportRow,
    FeedbackEventRow,
    GuideRow,
    JobRow,
    NotFound,
    Repository,
    SubmissionRow,
    utc_now,
)
from tests.factories import assessment_and_guide


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _activity(activity_id: str = "act_stage2", tenant_id: str = "tnt_stage2") -> ActivityRow:
    return ActivityRow(
        id=activity_id,
        tenant_id=tenant_id,
        status="BLUEPRINT_APPROVED",
        config={},
        blueprint_policy={},
        created_by="usr_stage2",
    )


def _submission(
    subject_ref: str,
    *,
    submission_id: str | None = None,
    activity_id: str = "act_stage2",
    tenant_id: str = "tnt_stage2",
    status: m.SubmissionProcessingStatus = m.SubmissionProcessingStatus.UPLOADED,
    active_job_id: str | None = None,
) -> SubmissionRow:
    identifier = submission_id or f"sub_{subject_ref}"
    state = m.SubmissionProcessingState(
        submission_id=identifier,
        activity_id=activity_id,
        status=status,
        progress=0.0,
        active_job_id=active_job_id,
        updated_at=NOW,
    )
    return SubmissionRow(
        id=identifier,
        tenant_id=tenant_id,
        activity_id=activity_id,
        subject_ref=subject_ref,
        state=state.model_dump(mode="json"),
        active_job_id=active_job_id,
    )


def test_multi_submission_batch_is_atomic_unique_and_tenant_scoped() -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.add(_activity())

    created = repo.create_submissions(
        [_submission("subject_a"), _submission("subject_b")]
    )
    assert [row.subject_ref for row in created] == ["subject_a", "subject_b"]
    assert [
        row.subject_ref
        for row in repo.submissions_for_activity("act_stage2", "tnt_stage2")
    ] == ["subject_a", "subject_b"]
    assert repo.submissions_for_activity("act_stage2", "tnt_other") == []
    assert repo.submission_for_activity("act_stage2", "tnt_stage2").subject_ref == "subject_a"

    with pytest.raises(Conflict, match="SUBMISSION_SUBJECT_ALREADY_EXISTS"):
        repo.create_submissions(
            [
                _submission("subject_b", submission_id="sub_duplicate"),
                _submission("subject_c"),
            ]
        )
    assert [
        row.subject_ref
        for row in repo.submissions_for_activity("act_stage2", "tnt_stage2")
    ] == ["subject_a", "subject_b"]


def test_retry_creates_distinct_job_control_record_and_claims_only_when_due() -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.add(_activity())
    source_submission = _submission(
        "subject_retry",
        submission_id="sub_retry",
        status=m.SubmissionProcessingStatus.TECHNICAL_FAILURE,
        active_job_id="job_source",
    )
    repo.create_submissions([source_submission])
    repo.add(
        JobRow(
            id="job_source",
            tenant_id="tnt_stage2",
            kind="SUBMISSION",
            aggregate_id="sub_retry",
            stage="SUBMISSION_PARSE",
            status="FAILED",
            progress=0.25,
            attempt=1,
            diagnostics=[],
            failure_class="TRANSIENT",
            max_attempts=3,
            finished_at=NOW,
        )
    )

    due = utc_now() - timedelta(seconds=1)
    result = repo.schedule_job_retry(
        job_id="job_source",
        tenant_id="tnt_stage2",
        resulting_job_id="job_retry_2",
        control_id="control_retry_2",
        actor_id="usr_stage2",
        reason_code="TRANSIENT_PROVIDER_FAILURE",
        failure_class="TRANSIENT",
        next_attempt_at=due,
        resume_from_stage="SUBMISSION_PARSE",
    )
    assert result.id == "job_retry_2"
    assert result.status == "QUEUED"
    assert result.attempt == 1
    with pytest.raises(Conflict, match="JOB_CONTINUATION_ALREADY_SCHEDULED"):
        repo.schedule_job_retry(
            job_id="job_source",
            tenant_id="tnt_stage2",
            resulting_job_id="job_retry_duplicate",
            control_id="control_retry_duplicate",
            actor_id="usr_stage2",
            reason_code="DUPLICATE_RETRY_ATTEMPT",
            failure_class="TRANSIENT",
            next_attempt_at=due,
            resume_from_stage="SUBMISSION_PARSE",
        )
    assert repo.job_control("job_source", "tnt_stage2").status == "FAILED"
    with pytest.raises(NotFound):
        repo.job_control("job_retry_2", "tnt_other")

    controls = repo.job_control_records(
        tenant_id="tnt_stage2", job_id="job_source"
    )
    assert len(controls) == 1
    assert controls[0].resulting_job_id == "job_retry_2"
    assert controls[0].data["action"] == "RETRY"
    submission = repo.scoped(SubmissionRow, "sub_retry", "tnt_stage2")
    assert isinstance(submission, SubmissionRow)
    assert submission.active_job_id == "job_retry_2"
    assert submission.state["active_job_id"] == "job_retry_2"

    claimed = repo.claim_next_job()
    assert claimed is not None
    assert claimed.id == "job_retry_2"
    assert claimed.attempt == 2


def test_cancel_is_durable_but_job_status_remains_v11_compatible() -> None:
    repo = Repository("sqlite+pysqlite://")
    repo.add(_activity())
    repo.create_submissions(
        [
            _submission(
                "subject_cancel",
                submission_id="sub_cancel",
                active_job_id="job_cancel",
            )
        ]
    )
    repo.add(
        JobRow(
            id="job_cancel",
            tenant_id="tnt_stage2",
            kind="SUBMISSION",
            aggregate_id="sub_cancel",
            stage="SUBMISSION_PARSE",
            status="QUEUED",
            progress=0.0,
            attempt=0,
            diagnostics=[],
        )
    )

    cancelled = repo.request_job_cancel(
        job_id="job_cancel",
        tenant_id="tnt_stage2",
        actor_id="usr_stage2",
        requested_at=NOW,
        control_id="control_cancel",
    )
    assert cancelled.control_state == "CANCELLED"
    assert cancelled.failure_class == "CANCELLATION"
    assert repo.job_status("job_cancel", "tnt_stage2").status == "FAILED"
    assert repo.job_status("job_cancel", "tnt_stage2").diagnostics[0].code == "JOB_CANCELLED"
    submission = repo.scoped(SubmissionRow, "sub_cancel", "tnt_stage2")
    assert isinstance(submission, SubmissionRow)
    assert submission.state["status"] == "CANCELLED"
    assert submission.active_job_id is None
    assert repo.claim_next_job() is None
    assert repo.job_control_records(tenant_id="tnt_stage2")[0].data["action"] == "CANCEL"


def test_stage_reuse_requires_all_hashes_and_component_version() -> None:
    repo = Repository("sqlite+pysqlite://")
    inputs = {"submission_id": "sub_stage", "sealed_hash": "sha256:" + "a" * 64}
    first, reused = repo.save_stage(
        job_id="job_stage_1",
        tenant_id="tnt_stage2",
        stage="EVIDENCE_MAP",
        inputs=inputs,
        component_version="mapper/1.2.0",
        policy_hash="sha256:" + "b" * 64,
        output={"result": "synthetic"},
    )
    assert not reused
    assert first.output_hash == canonical_hash({"result": "synthetic"})
    assert first.finished_at is not None
    assert first.started_at <= first.finished_at

    second, reused = repo.save_stage(
        job_id="job_stage_2",
        tenant_id="tnt_stage2",
        stage="EVIDENCE_MAP",
        inputs=inputs,
        component_version="mapper/1.2.0",
        policy_hash="sha256:" + "b" * 64,
        output={"ignored": "because-success-is-reused"},
    )
    assert reused
    assert second.id == first.id
    assert repo.stage_by_key(
        tenant_id="tnt_stage2",
        stage="EVIDENCE_MAP",
        inputs=inputs,
        component_version="mapper/1.2.0",
        policy_hash="sha256:" + "b" * 64,
    ) is not None
    assert repo.stage_by_key(
        tenant_id="tnt_stage2",
        stage="EVIDENCE_MAP",
        inputs=inputs,
        component_version="mapper/1.2.1",
        policy_hash="sha256:" + "b" * 64,
    ) is None


def test_cancel_wins_atomically_before_assessment_publication() -> None:
    repo = Repository("sqlite+pysqlite://")
    assessment, guide = assessment_and_guide()
    repo.add(_activity(assessment.activity_id, assessment.tenant_id))
    repo.create_submissions(
        [
            _submission(
                assessment.subject_ref,
                submission_id=assessment.submission_id,
                activity_id=assessment.activity_id,
                tenant_id=assessment.tenant_id,
                status=m.SubmissionProcessingStatus.GUIDE_READY,
                active_job_id="job_finalization_race",
            )
        ]
    )
    repo.add(
        JobRow(
            id="job_finalization_race",
            tenant_id=assessment.tenant_id,
            kind="SUBMISSION",
            aggregate_id=assessment.submission_id,
            stage="GUIDE_BUILD",
            status="RUNNING",
            progress=0.82,
            attempt=1,
            diagnostics=[],
            started_at=NOW,
        )
    )
    repo.request_job_cancel(
        job_id="job_finalization_race",
        tenant_id=assessment.tenant_id,
        actor_id="usr_stage2",
        control_id="control_finalization_race",
    )

    finalized = repo.finalize_submission_assessment(
        job_id="job_finalization_race",
        tenant_id=assessment.tenant_id,
        assessment=AssessmentRow(
            row_id="assessment_row_finalization_race",
            assessment_id=assessment.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=assessment.submission_id,
            version=1,
            status=assessment.status.value,
            etag='"sha256:' + "a" * 64 + '"',
            data=assessment.model_dump(mode="json"),
        ),
        guide=GuideRow(
            guide_id=guide.guide_id,
            assessment_id=assessment.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=assessment.submission_id,
            data=guide.model_dump(mode="json"),
        ),
    )

    assert finalized is False
    with pytest.raises(NotFound):
        repo.latest_assessment(assessment.submission_id, assessment.tenant_id)
    job = repo.job_control("job_finalization_race", assessment.tenant_id)
    assert job.control_state == "CANCELLED"
    assert job.failure_class == "CANCELLATION"
    submission = repo.scoped(
        SubmissionRow, assessment.submission_id, assessment.tenant_id
    )
    assert m.SubmissionProcessingState.model_validate(submission.state).status == (
        m.SubmissionProcessingStatus.CANCELLED
    )


def test_canonical_action_feedback_bulk_and_export_history_are_tenant_scoped() -> None:
    repo = Repository("sqlite+pysqlite://")
    assessment, _guide = assessment_and_guide()
    repo.add(_activity(assessment.activity_id, assessment.tenant_id))
    repo.create_submissions(
        [
            _submission(
                assessment.subject_ref,
                submission_id=assessment.submission_id,
                activity_id=assessment.activity_id,
                tenant_id=assessment.tenant_id,
                status=m.SubmissionProcessingStatus.NEEDS_REVIEW,
            )
        ]
    )
    repo.add(
        AssessmentRow(
            row_id="assessment_row_v1",
            assessment_id=assessment.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=assessment.submission_id,
            version=1,
            status=assessment.status.value,
            etag='"assessment-v1"',
            data=assessment.model_dump(mode="json"),
        )
    )
    question = assessment.questions[0]
    action = m.QuestionReviewAction(
        action_id="action_accept",
        assessment_id=assessment.assessment_id,
        question_id=question.question_id,
        action=m.QuestionReviewActionType.ACCEPT,
        actor_id="usr_stage2",
        occurred_at=NOW,
    )
    record = m.QuestionReviewActionRecord(
        record_id="action_record_accept",
        tenant_id=assessment.tenant_id,
        activity_id=assessment.activity_id,
        submission_id=assessment.submission_id,
        assessment_id=assessment.assessment_id,
        assessment_version_before=1,
        assessment_version_after=1,
        action=action,
        status=m.QuestionReviewRecordStatus.APPLIED,
        revalidation_status=m.RevalidationStatus.NOT_REQUIRED,
        before_question=question,
        after_question=question,
        lineage_before=assessment.lineage,
        lineage_after=assessment.lineage,
        recorded_at=NOW,
    )
    action_row = repo.apply_question_review_action(record)
    assert action_row.data["action"]["action"] == "ACCEPT"
    assert repo.question_review_actions(
        tenant_id=assessment.tenant_id,
        assessment_id=assessment.assessment_id,
        assessment_version=1,
    )[0].id == record.record_id
    assert repo.question_review_actions(
        tenant_id="tnt_other", assessment_id=assessment.assessment_id
    ) == []

    feedback = m.FeedbackEvent(
        feedback_id="feedback_activity",
        tenant_id=assessment.tenant_id,
        activity_id=assessment.activity_id,
        target_type=m.FeedbackTargetType.ACTIVITY,
        actor_id="usr_stage2",
        category=m.FeedbackCategory.WORKFLOW,
        rating=m.FeedbackRating.HELPFUL,
        created_at=NOW,
    )
    feedback_row = repo.add_feedback_event(feedback)
    assert isinstance(feedback_row, FeedbackEventRow)
    assert feedback_row.rating == "HELPFUL"
    assert repo.feedback_events(
        tenant_id=assessment.tenant_id, activity_id=assessment.activity_id
    )[0].id == feedback.feedback_id

    request = m.BulkApprovalRequest(
        request_id="bulk_request",
        tenant_id=assessment.tenant_id,
        actor_id="usr_stage2",
        targets=[
            m.AssessmentVersionRef(
                assessment_id=assessment.assessment_id, assessment_version=1
            )
        ],
        explicit_confirmation="CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS",
        requested_at=NOW,
    )
    repo.add_bulk_approval_request(request)
    bulk_record = m.BulkApprovalRecord(
        approval_id="bulk_record",
        request_id=request.request_id,
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        scope="SELECTED_ELIGIBLE_ASSESSMENTS",
        approved_at=NOW,
        requested_targets=request.targets,
        approved_targets=request.targets,
        excluded_targets=[],
    )
    stored_bulk = repo.add_bulk_approval_record(bulk_record)
    assert isinstance(stored_bulk, BulkApprovalRecordRow)
    assert repo.bulk_approval_records(
        tenant_id=assessment.tenant_id, request_id=request.request_id
    )[0].approved_count == 1

    repo.add(
        ExportRow(
            id="export_history",
            tenant_id=assessment.tenant_id,
            assessment_id=assessment.assessment_id,
            status="READY",
            artifacts={},
        )
    )
    bound = repo.set_export_snapshot_metadata(
        export_id="export_history",
        tenant_id=assessment.tenant_id,
        assessment_version=1,
        snapshot_hash=canonical_hash(assessment.model_dump(mode="json")),
        component_version="renderer/1.2.0",
    )
    assert bound.assessment_version == 1
    assert repo.list_exports(assessment.assessment_id, assessment.tenant_id)[0].id == "export_history"
    assert repo.list_exports(assessment.assessment_id, "tnt_other") == []


@pytest.mark.parametrize(
    "action_type",
    [m.QuestionReviewActionType.EDIT, m.QuestionReviewActionType.REGENERATE],
)
def test_mutating_review_merges_existing_canonical_guide(
    action_type: m.QuestionReviewActionType,
) -> None:
    repo = Repository("sqlite+pysqlite://")
    assessment, guide = assessment_and_guide()
    repo.add(_activity(assessment.activity_id, assessment.tenant_id))
    repo.create_submissions(
        [
            _submission(
                assessment.subject_ref,
                submission_id=assessment.submission_id,
                activity_id=assessment.activity_id,
                tenant_id=assessment.tenant_id,
                status=m.SubmissionProcessingStatus.NEEDS_REVIEW,
            )
        ]
    )
    repo.add(
        AssessmentRow(
            row_id="assessment_review_v1",
            assessment_id=assessment.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=assessment.submission_id,
            version=1,
            status=assessment.status.value,
            etag='"assessment-review-v1"',
            data=assessment.model_dump(mode="json"),
        )
    )
    repo.add(
        GuideRow(
            guide_id=guide.guide_id,
            assessment_id=guide.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=guide.submission_id,
            data=guide.model_dump(mode="json"),
        )
    )

    before = assessment.questions[0]
    if action_type == m.QuestionReviewActionType.EDIT:
        after = before.model_copy(
            update={"question_text": f"{before.question_text} Edición humana."}
        )
        action = m.QuestionReviewAction(
            action_id="action_edit",
            assessment_id=assessment.assessment_id,
            question_id=before.question_id,
            action=action_type,
            actor_id="usr_stage2",
            occurred_at=NOW,
            replacement=after,
        )
    else:
        after = before.model_copy(
            update={
                "source_candidate_id": "candidate_regenerated",
                "opportunity_id": "opp_regenerated",
                "question_text": f"{before.question_text} Regenerada.",
            }
        )
        action = m.QuestionReviewAction(
            action_id="action_regenerate",
            assessment_id=assessment.assessment_id,
            question_id=before.question_id,
            action=action_type,
            actor_id="usr_stage2",
            occurred_at=NOW,
            reason_code="GROUNDING_REVALIDATION",
        )
    resulting_assessment = assessment.model_copy(update={"questions": [after]})
    resulting_guide = guide.model_copy(update={"status": "NEEDS_REVIEW"})
    record = m.QuestionReviewActionRecord(
        record_id=f"action_record_{action_type.value.lower()}",
        tenant_id=assessment.tenant_id,
        activity_id=assessment.activity_id,
        submission_id=assessment.submission_id,
        assessment_id=assessment.assessment_id,
        assessment_version_before=1,
        assessment_version_after=2,
        action=action,
        status=m.QuestionReviewRecordStatus.APPLIED,
        revalidation_status=m.RevalidationStatus.PASSED,
        before_question=before,
        after_question=after,
        lineage_before=assessment.lineage,
        lineage_after=assessment.lineage,
        recorded_at=NOW,
    )

    stored_action = repo.apply_question_review_action(
        record,
        resulting_assessment=AssessmentRow(
            row_id="assessment_review_v2",
            assessment_id=assessment.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=assessment.submission_id,
            version=2,
            status=resulting_assessment.status.value,
            etag=f'"assessment-review-v2-{action_type.value.lower()}"',
            data=resulting_assessment.model_dump(mode="json"),
        ),
        resulting_guide=GuideRow(
            guide_id=guide.guide_id,
            assessment_id=guide.assessment_id,
            tenant_id=assessment.tenant_id,
            submission_id=guide.submission_id,
            data=resulting_guide.model_dump(mode="json"),
        ),
    )

    assert stored_action.assessment_version_after == 2
    assert repo.latest_assessment(
        assessment.submission_id, assessment.tenant_id
    ).version == 2
    merged_guide = repo.guide_for_assessment(
        assessment.assessment_id, assessment.tenant_id
    )
    assert merged_guide.guide_id == guide.guide_id
    assert merged_guide.data["status"] == "NEEDS_REVIEW"
