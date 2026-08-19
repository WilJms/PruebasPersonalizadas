"""Phase 9B.7 product-decision regression.

Every test is offline.  Nothing constructs provider transport, resolves a
credential, issues an authorization or reads a candidate outcome.

The verdict must be derived.  ``PHASE9B7_PRODUCT_DECISION_REQUIRED_NOISY`` is
asserted here together with a test that flips it to
``PHASE9B7_DECISION_READY_U3_N3`` the moment the N3 measurement changes, so the
recommendation cannot be a constant wearing a derivation's clothes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comprehension_verification.future_stage_boundary_plan import (
    CORPUS_DEPENDENT_STAGES,
    MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARIES,
)
from comprehension_verification.phase9b7_decision import (
    U3_REQUIRED_LIMITATIONS,
    decision_matrix,
    phase9b7_decision,
)
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT


REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = DEFAULT_CORPUS_ROOT
ARTIFACT = (
    REPO_ROOT / "reports" / "semantic_benchmark" / "phase9b7" / "product_decision.json"
)

_AXES = (
    "production_representativeness",
    "corpus_change",
    "semantic_contract_change",
    "denominator_change",
    "hard_safety_strength",
    "contamination_overfitting_risk",
    "required_future_stage_boundaries",
    "required_protocol_or_budget_changes",
    "residual_risk",
)


@pytest.fixture(scope="module")
def decision() -> dict:
    return phase9b7_decision(CORPUS_ROOT)


def test_verdict_is_one_of_the_allowed_outcomes(decision) -> None:
    assert decision["verdict"] in {
        "PHASE9B7C_U3_N3_READY_FOR_PUBLICATION",
        "PHASE9B7C_SPLIT_PROTOCOL_BLOCKED",
        "PHASE9B7B_U3_N3_PROTOCOL_READY_FOR_PUBLICATION",
        "PHASE9B7B_PROTOCOL_BLOCKED",
        "PHASE9B7_PRODUCT_DECISION_REQUIRED_NOISY",
        "PHASE9B7_ARCHITECTURE_DISCREPANCY",
    }


def test_the_phase_is_protocol_ready_on_u3_and_n3(decision) -> None:
    assert decision["verdict"] == "PHASE9B7C_U3_N3_READY_FOR_PUBLICATION"
    assert decision["noisy_decision"] == "N3"
    assert decision["noisy_decision_required_between"] is None


def test_the_protocol_surface_is_published_with_the_decision(decision) -> None:
    surface = decision["n3_protocol_surface"]
    assert surface["axis"] == "CONTRACTUAL_HARD_SAFETY"
    assert surface["protocol_mismatch"]["all_facts_hold"] is True
    assert surface["exposure_population"]["total_exposure_count"] == 10
    assert surface["exposure_population"]["qualification_side_count"] == 7
    assert surface["exposure_population"]["held_out_count"] == 3
    assert surface["aggregation"]["max_confirmed_failures"] == 0


def test_the_verdict_blocks_if_the_protocol_axis_is_not_separate(
    monkeypatch,
) -> None:
    """PROTOCOL_READY is a measurement, not a constant."""

    from comprehension_verification import phase9b7_decision as mod

    real = mod.n3_protocol_surface

    def merged(corpus_root, v12_root):
        surface = dict(real(corpus_root, v12_root))
        surface["separate_from_semantic_axis"] = False
        return surface

    monkeypatch.setattr(mod, "n3_protocol_surface", merged)
    blocked = mod.phase9b7_decision(CORPUS_ROOT)
    assert blocked["verdict"] == "PHASE9B7B_PROTOCOL_BLOCKED"


def test_uncertain_recommendation_is_u3_with_its_limitations_verbatim(
    decision,
) -> None:
    assert decision["uncertain_recommendation"] == "U3"
    assert decision["uncertain_recommendation_limitations"] == list(
        U3_REQUIRED_LIMITATIONS
    )
    joined = " ".join(decision["uncertain_recommendation_limitations"])
    assert "does NOT qualify P06 UNCERTAIN behaviour" in joined
    assert "SUFFICIENT / PARTIAL / INSUFFICIENT" in joined
    assert "explicit residual risk" in joined
    assert "full P06 contract coverage" in joined


def test_uncertain_is_not_removed_from_the_production_contract(decision) -> None:
    """U3 narrows a *claim*.  It may never narrow the contract."""

    from comprehension_verification.contracts import models as m

    assert m.EvidenceSupportStatus.UNCERTAIN in set(m.EvidenceSupportStatus)
    blob = json.dumps(decision)
    assert "UNCERTAIN remains an explicit residual risk." in blob


def test_every_option_is_classified_on_every_axis() -> None:
    matrix = decision_matrix(CORPUS_ROOT)
    options = [row["option"] for row in matrix["matrix"]]
    assert options == ["U1", "U2", "U3", "U4", "N1", "N2", "N3"]
    for row in matrix["matrix"]:
        for axis in _AXES:
            assert row[axis] not in (None, "", []), f"{row['option']} missing {axis}"


def test_only_u4_changes_corpus_bytes() -> None:
    matrix = decision_matrix(CORPUS_ROOT)
    changing = [row["option"] for row in matrix["matrix"] if row["corpus_change"]]
    assert changing == ["U4"]


def test_boundary_sets_come_from_the_boundary_authority() -> None:
    """The matrix must not restate a boundary set it does not own."""

    matrix = decision_matrix(CORPUS_ROOT)
    by_option = {row["option"]: row for row in matrix["matrix"]}
    assert by_option["U4"]["required_future_stage_boundaries"] == list(
        CORPUS_DEPENDENT_STAGES
    )
    for option in ("U1", "U2", "U3", "N1", "N2", "N3"):
        assert by_option[option]["required_future_stage_boundaries"] == list(
            MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARIES
        )


def test_n3_row_reports_a_sound_gate_with_an_honest_scope() -> None:
    by_option = {row["option"]: row for row in decision_matrix(CORPUS_ROOT)["matrix"]}
    n3 = by_option["N3"]
    assert n3["production_representativeness"].startswith("PROVEN")
    assert "CONFIRMS OBSERVABLE VIOLATIONS" in n3["hard_safety_strength"]
    assert n3["corpus_change"] is False
    assert n3["semantic_contract_change"].startswith("NO")
    assert n3["denominator_change"].startswith("NO")
    # Soundness is claimed; completeness is not.
    assert "Sound, not complete" in n3["residual_risk"]
    assert "INDETERMINATE" in n3["residual_risk"]


def test_n3_authority_is_the_executable_prompt_not_a_heuristic() -> None:
    soundness = decision_matrix(CORPUS_ROOT)["n3_soundness"]
    authority = soundness["contractual_policy_authority"]
    assert authority["authority_kind"] == "CONTRACTUAL_POLICY_AUTHORITY"
    assert authority["not_a"] == "PER_CASE_SEMANTIC_GOLDEN"
    assert authority["prompt_hash"].startswith("sha256:")
    assert authority["rule_count"] >= 3


def test_the_deterministic_guard_probe_is_kept_separate_from_the_n3_verdict() -> None:
    probe = decision_matrix(CORPUS_ROOT)["deterministic_runtime_guard_probe"]
    assert probe["verdict"] == "NO_DETERMINISTIC_RUNTIME_GUARD"
    assert probe["does_not_decide"] == "N3"


def test_p07_noisy_coverage_is_defense_in_depth_not_p06_coverage() -> None:
    by_option = {row["option"]: row for row in decision_matrix(CORPUS_ROOT)["matrix"]}
    assert "never P06 coverage" in by_option["N1"]["residual_risk"]


def test_the_verdict_flips_back_if_no_class_is_confirmable(monkeypatch) -> None:
    """Proves DECISION_READY is a measurement, not a constant."""

    from comprehension_verification import phase9b7_decision as mod

    real = mod.violation_class_scope

    def unsound():
        scope = dict(real())
        scope["confirmable_without_golden"] = []
        return scope

    monkeypatch.setattr(mod, "violation_class_scope", unsound)
    flipped = mod.phase9b7_decision(CORPUS_ROOT)
    assert flipped["verdict"] == "PHASE9B7_PRODUCT_DECISION_REQUIRED_NOISY"
    assert flipped["noisy_decision"] is None
    assert flipped["noisy_decision_required_between"] == ["N1", "N2"]


def test_n1_and_n2_drawbacks_stay_on_the_record(decision) -> None:
    """N3 is recommended over them, so why they lose must remain visible."""

    by_option = {
        row["option"]: row for row in decision["decision_matrix"]["matrix"]
    }
    # N1 keeps the contract but cannot observe the family.
    assert "OBSERVATION ABSENT" in by_option["N1"]["hard_safety_strength"]
    # N2 restores observation but changes what a P06 target means.
    assert by_option["N2"]["semantic_contract_change"].startswith("YES")
    assert by_option["N2"]["denominator_change"].startswith("YES")


# --------------------------------------------------------------------------
# Firewall and non-creation
# --------------------------------------------------------------------------


def test_the_phase_creates_no_benchmark_version_and_refreezes_nothing(
    decision,
) -> None:
    assert decision["benchmark_version_created"] is None
    assert decision["boundaries_refrozen"] is False
    assert decision["high_smoke_authorized"] is False
    assert decision["corpus_bytes_modified"] is False


def test_every_execution_counter_is_zero(decision) -> None:
    assert decision["provider_calls"] == 0
    assert decision["adjudicator_calls"] == 0
    assert decision["billable_authorizations"] == 0
    assert decision["openai_credentials_resolved"] == 0
    assert decision["real_transport_constructed"] is False
    assert decision["candidate_outcomes_read"] is False


def test_no_v13_directory_is_created() -> None:
    assert not (REPO_ROOT / "evaluation" / "semantic_benchmark" / "v1_3").exists()
    assert not (REPO_ROOT / "reports" / "semantic_benchmark" / "v1_3").exists()


def test_the_published_artifact_reproduces_byte_for_byte() -> None:
    if not ARTIFACT.exists():
        pytest.skip("artifact not built in this working tree")
    published = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert published["decision_hash"] == phase9b7_decision(CORPUS_ROOT)["decision_hash"]


# --------------------------------------------------------------------------
# The document may not state a number the machine does not
# --------------------------------------------------------------------------


DOCUMENT = REPO_ROOT / "docs" / "PHASE9B7_NOISY_GATE_FEASIBILITY.md"


def test_document_verdict_matches_the_machine_verdict(decision) -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert f"**Verdict: `{decision['verdict']}`**" in text


def test_document_reports_the_authority_the_gate_actually_uses() -> None:
    from comprehension_verification.p06_noisy_contractual_gate import (
        contractual_policy_authority,
        violation_class_scope,
    )

    text = DOCUMENT.read_text(encoding="utf-8")
    authority = contractual_policy_authority()
    assert authority["prompt_id"] in text
    assert authority["system_prompt_id"] in text
    assert authority["prompt_version"] in text
    for class_id in violation_class_scope()["confirmable_without_golden"]:
        assert class_id in text
    for class_id in violation_class_scope()["degrades_to_indeterminate"]:
        assert class_id in text


def test_document_carries_the_u3_limitations_verbatim() -> None:
    """Markdown emphasis may decorate the four statements, never reword them."""

    raw = DOCUMENT.read_text(encoding="utf-8")
    plain = " ".join(raw.replace("**", "").replace("`", "").split())
    for limitation in U3_REQUIRED_LIMITATIONS:
        expected = " ".join(limitation.split())
        assert expected in plain, limitation


def test_document_does_not_claim_a_new_benchmark_version() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert "`semantic-benchmark/1.3.0` created: **no**" in text


def test_held_out_exposures_never_enter_a_selection_stage(decision) -> None:
    """Phase 9B.7C: the published plan keeps the partition intact."""

    surface = decision["n3_protocol_surface"]
    held_out = set(surface["exposure_population"]["held_out_exposure_ids"])
    for stage in surface["stage_plan"]["stages"]:
        if stage["may_influence_rung_selection"]:
            assert not set(stage["exposure_ids"]) & held_out
    assert set(surface["safety_smoke_selector"]["exposure_ids"]) & held_out == set()


def test_the_verdict_blocks_if_held_out_leaks_into_selection(monkeypatch) -> None:
    """SPLIT-READY is a measurement, not a constant."""

    from comprehension_verification import phase9b7_decision as mod

    real = mod.n3_protocol_surface

    def leaky(corpus_root, v12_root):
        surface = dict(real(corpus_root, v12_root))
        plan = dict(surface["stage_plan"])
        stages = [dict(item) for item in plan["stages"]]
        held_out = surface["exposure_population"]["held_out_exposure_ids"]
        for stage in stages:
            if stage["may_influence_rung_selection"]:
                stage["exposure_ids"] = list(stage["exposure_ids"]) + list(held_out)
                break
        plan["stages"] = stages
        surface["stage_plan"] = plan
        return surface

    monkeypatch.setattr(mod, "n3_protocol_surface", leaky)
    blocked = mod.phase9b7_decision(CORPUS_ROOT)
    assert blocked["verdict"] == "PHASE9B7C_SPLIT_PROTOCOL_BLOCKED"
