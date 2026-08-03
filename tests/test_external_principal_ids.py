from datetime import UTC, datetime

from comprehension_verification.contracts import models as m


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


def test_approval_fields_use_external_principal_id() -> None:
    assert (
        m.PolicyDecision.model_fields["decided_by"].annotation
        == m.PrincipalId
    )
