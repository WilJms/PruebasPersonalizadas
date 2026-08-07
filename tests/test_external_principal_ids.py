from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comprehension_verification.contracts import models as m

from .factories import assessment_and_guide, blueprint


SUPABASE_USER_ID = "3f14edbd-e5cd-41d1-a172-62e51b6a10e8"
LEGACY_PRINCIPAL_ID = "teacher_stage1"


def test_policy_decision_accepts_supabase_user_uuid() -> None:
    decision = m.PolicyDecision(
        decision_id="decision_uuid_test",
        issue_id="issue_uuid_test",
        selected_option_id="option_uuid_test",
        decided_by=SUPABASE_USER_ID,
        decided_at=datetime.now(UTC),
    )

    assert decision.decided_by == SUPABASE_USER_ID


def test_blueprint_approval_accepts_supabase_user_uuid() -> None:
    payload = blueprint().model_dump(mode="json")
    payload["approved_by"] = SUPABASE_USER_ID
    payload["approved_at"] = datetime.now(UTC).isoformat()

    approved = m.AssessmentBlueprint.model_validate(payload)

    assert approved.approved_by == SUPABASE_USER_ID


def test_assessment_approval_accepts_supabase_user_uuid() -> None:
    assessment, _guide = assessment_and_guide()
    payload = assessment.model_dump(mode="json")
    payload["status"] = "APPROVED"
    payload["approved_by"] = SUPABASE_USER_ID
    payload["approved_at"] = datetime.now(UTC).isoformat()

    approved = m.Assessment.model_validate(payload)

    assert approved.approved_by == SUPABASE_USER_ID


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            m.BulkApprovalRequest,
            {
                "request_id": "request_uuid_test",
                "tenant_id": "tenant_uuid_test",
                "actor_id": SUPABASE_USER_ID,
                "targets": [
                    {
                        "assessment_id": "assessment_uuid_test",
                        "assessment_version": 1,
                    }
                ],
                "explicit_confirmation": (
                    "CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS"
                ),
                "requested_at": datetime.now(UTC),
            },
        ),
        (
            m.QuestionReviewAction,
            {
                "action_id": "action_uuid_test",
                "assessment_id": "assessment_uuid_test",
                "question_id": "question_uuid_test",
                "action": "ACCEPT",
                "actor_id": SUPABASE_USER_ID,
                "occurred_at": datetime.now(UTC),
            },
        ),
        (
            m.EventActor,
            {"kind": "USER", "id": SUPABASE_USER_ID},
        ),
    ],
)
def test_external_actor_roots_accept_supabase_user_uuid(model: type, payload: dict) -> None:
    parsed = model.model_validate(payload)
    principal = parsed.actor_id if "actor_id" in payload else parsed.id
    assert principal == SUPABASE_USER_ID


def test_bulk_approval_record_accepts_supabase_user_uuid() -> None:
    record = m.BulkApprovalRecord(
        approval_id="approval_uuid_test",
        request_id="request_uuid_test",
        tenant_id="tenant_uuid_test",
        actor_id=SUPABASE_USER_ID,
        scope="SELECTED_ELIGIBLE_ASSESSMENTS",
        requested_targets=[
            m.AssessmentVersionRef(
                assessment_id="assessment_uuid_test", assessment_version=1
            )
        ],
        approved_targets=[
            m.AssessmentVersionRef(
                assessment_id="assessment_uuid_test", assessment_version=1
            )
        ],
        approved_at=datetime.now(UTC),
    )

    assert record.actor_id == SUPABASE_USER_ID


@pytest.mark.parametrize("principal", [LEGACY_PRINCIPAL_ID, SUPABASE_USER_ID])
def test_event_actor_preserves_legacy_and_external_principals(principal: str) -> None:
    assert m.EventActor(kind="USER", id=principal).id == principal


@pytest.mark.parametrize(
    "principal",
    [
        "Teacher_Stage1",
        "teacher@example.com",
        "3F14EDBD-E5CD-41D1-A172-62E51B6A10E8",
        "3f14edbd-e5cd-41d1-a172-62e51b6a10e",
    ],
)
def test_external_actor_roots_reject_invalid_principals(principal: str) -> None:
    with pytest.raises(ValidationError):
        m.EventActor(kind="USER", id=principal)


def test_internal_ids_still_reject_supabase_uuid() -> None:
    with pytest.raises(ValidationError):
        m.AssessmentVersionRef(assessment_id=SUPABASE_USER_ID, assessment_version=1)
