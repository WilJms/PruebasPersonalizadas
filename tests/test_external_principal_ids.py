from datetime import UTC, datetime

from comprehension_verification.contracts import models as m

from .factories import assessment_and_guide, blueprint


SUPABASE_USER_ID = "3f14edbd-e5cd-41d1-a172-62e51b6a10e8"


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
