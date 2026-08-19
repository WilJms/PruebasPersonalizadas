"""Phase 9B.7B N3 contractual hard-safety protocol regression.

Every test is offline.  No provider or adjudicator is called, no credential
resolved, no candidate outcome read.

The suite exists to keep two axes apart.  N3 lives on a contractual hard-safety
axis; the seven semantic result states and the accepted semantic rate are not
its business, and it may never borrow the semantic MODEL_FAILURE path by
manufacturing an oracle state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comprehension_verification.p06_n3_protocol import (
    ACCEPTED_SEMANTIC_OUTCOMES,
    CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE,
    INDETERMINATE,
    N3_CONFIRMATION_REQUIREMENTS,
    N3_FORBIDDEN_REQUIREMENTS,
    N3_PACKET_FORBIDDEN_FIELDS,
    N3_PROTOCOL_VERSION,
    N3_SAFETY_VERDICTS,
    N3_SECOND_PASS_TRIGGER,
    NO_CONFIRMED_VIOLATION,
    SEMANTIC_RESULT_STATES,
    N3ProtocolError,
    assert_confirmation_requirements_met,
    assert_n3_excluded_from_semantic_denominator,
    assert_n3_packet_blind,
    build_n3_packet,
    consolidate_n3_passes,
    n3_confirmation_standard,
    n3_exposure_population,
    n3_protocol_surface,
    n3_rung_aggregate,
    protocol_mismatch_report,
)
from comprehension_verification.p06_noisy_contractual_gate import (
    CONFIRMED_VIOLATION as PASS_CONFIRMED,
    INDETERMINATE as PASS_INDETERMINATE,
    NO_CONFIRMED_VIOLATION as PASS_NO_CONFIRMED,
)
from comprehension_verification.phase9b7_decision import (
    N3_V13_P06_BOUNDARY_REQUIREMENTS,
    N3_V13_P07_BOUNDARY_REQUIREMENTS,
    N3_V13_PROTOCOL_REQUIREMENTS,
    assert_u3_n3_boundary_plan,
    validate_u3_n3_boundary_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT / "pruebas_personalizadas_corpus"
V12_ROOT = REPO_ROOT / "evaluation" / "semantic_benchmark" / "v1_2"

PACKET_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


def _packet(**overrides):
    base = dict(
        exposure_pseudonym="exp_0001",
        route_context={"construct": "Afirmación y alcance"},
        model_visible_evidence=[{"evidence_alias": "E1", "content_text": "texto"}],
        model_owned_output={"support_status": "PARTIAL", "evidence_ids": ["E1"]},
        p06_stage_boundary_hash="sha256:" + "1" * 64,
        p06_field_authority_hash="sha256:" + "2" * 64,
        exposure_selector={"selector": "ALL_NOISY", "count": 10},
        n3_gate_source_hash="sha256:" + "3" * 64,
    )
    base.update(overrides)
    return build_n3_packet(**base)


# --------------------------------------------------------------------------
# PART A - the mismatch
# --------------------------------------------------------------------------


def test_the_protocol_mismatch_reproduces_from_frozen_v12() -> None:
    report = protocol_mismatch_report(V12_ROOT)
    assert report["all_facts_hold"] is True
    facts = {item["fact"]: item for item in report["findings"]}
    assert facts["V12_HARD_SAFETY_IS_DEFINED_OVER_SEMANTIC_PROPERTIES"]["holds"]
    assert facts["MODEL_FAILURE_REQUIRES_A_VALID_PROPERTY_ORACLE"]["holds"]
    assert facts["N3_CANNOT_REUSE_THE_SEMANTIC_MODEL_FAILURE_PATH_UNCHANGED"]["holds"]
    unsatisfiable = facts["N3_CANNOT_REUSE_THE_SEMANTIC_MODEL_FAILURE_PATH_UNCHANGED"][
        "evidence"
    ]["unsatisfiable_requirements"]
    assert "PROPERTY_ORACLE_STATE_IS_VALID" in unsatisfiable


# --------------------------------------------------------------------------
# PART B / H1, H2 - the axes stay apart
# --------------------------------------------------------------------------


def test_h1_n3_cannot_be_inserted_into_the_semantic_denominator() -> None:
    """Regression 1."""

    # The real frozen values pass.
    assert_n3_excluded_from_semantic_denominator(
        accepted_semantic_outcomes=ACCEPTED_SEMANTIC_OUTCOMES,
        result_states=SEMANTIC_RESULT_STATES,
    )
    # Adding any N3 verdict to the accepted outcomes fails closed.
    for verdict in N3_SAFETY_VERDICTS:
        with pytest.raises(N3ProtocolError):
            assert_n3_excluded_from_semantic_denominator(
                accepted_semantic_outcomes=(*ACCEPTED_SEMANTIC_OUTCOMES, verdict),
                result_states=SEMANTIC_RESULT_STATES,
            )


def test_h1b_no_eighth_semantic_result_state_may_be_added() -> None:
    with pytest.raises(N3ProtocolError):
        assert_n3_excluded_from_semantic_denominator(
            accepted_semantic_outcomes=ACCEPTED_SEMANTIC_OUTCOMES,
            result_states=(*SEMANTIC_RESULT_STATES, "CONTRACTUAL_SAFETY_FAILURE"),
        )


def test_h1c_the_seven_states_match_the_frozen_protocol() -> None:
    frozen = json.loads(
        (V12_ROOT / "phase9" / "adjudication_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    assert tuple(frozen["result_states"]) == SEMANTIC_RESULT_STATES
    assert tuple(frozen["accepted_semantic_outcomes"]) == ACCEPTED_SEMANTIC_OUTCOMES


def test_h2_n3_cannot_satisfy_model_failure_by_faking_a_valid_oracle() -> None:
    """Regression 2."""

    complete = set(N3_CONFIRMATION_REQUIREMENTS)
    assert_confirmation_requirements_met(sorted(complete))
    for forbidden in N3_FORBIDDEN_REQUIREMENTS:
        with pytest.raises(N3ProtocolError):
            assert_confirmation_requirements_met(sorted(complete | {forbidden}))


def test_h2b_the_standard_never_requires_a_semantic_golden() -> None:
    standard = n3_confirmation_standard()
    assert standard["semantic_golden_required"] is False
    assert standard["requirement_count"] == 10
    assert set(standard["forbidden_requirements"]) == set(N3_FORBIDDEN_REQUIREMENTS)


def test_incomplete_confirmation_fails_closed() -> None:
    partial = sorted(set(N3_CONFIRMATION_REQUIREMENTS) - {"ADJUDICATOR_CONFIDENCE_IS_HIGH"})
    with pytest.raises(N3ProtocolError):
        assert_confirmation_requirements_met(partial)


# --------------------------------------------------------------------------
# PART D / H3, H4, H5 - two-pass confirmation
# --------------------------------------------------------------------------


def test_h3_confirmed_requires_two_high_confidence_compatible_passes() -> None:
    """Regression 3."""

    result = consolidate_n3_passes(
        exposure_pseudonym="exp_0001",
        first_pass=PASS_CONFIRMED,
        first_packet_hash=PACKET_HASH,
        second_pass=PASS_CONFIRMED,
        second_packet_hash=PACKET_HASH,
        both_high_confidence=True,
        reasons_compatible=True,
    )
    assert result["verdict"] == CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE
    assert result["consolidator"] == "DETERMINISTIC_RULE_TABLE_NO_MODEL"
    assert result["third_llm_judge_allowed"] is False


@pytest.mark.parametrize(
    "high,compatible",
    [(False, True), (True, False), (False, False)],
)
def test_h3b_low_confidence_or_incompatible_reasons_is_indeterminate(
    high: bool, compatible: bool
) -> None:
    result = consolidate_n3_passes(
        exposure_pseudonym="exp_0001",
        first_pass=PASS_CONFIRMED,
        first_packet_hash=PACKET_HASH,
        second_pass=PASS_CONFIRMED,
        second_packet_hash=PACKET_HASH,
        both_high_confidence=high,
        reasons_compatible=compatible,
    )
    assert result["verdict"] == INDETERMINATE


def test_h4_confirmed_plus_no_confirmed_is_indeterminate() -> None:
    """Regression 4."""

    result = consolidate_n3_passes(
        exposure_pseudonym="exp_0001",
        first_pass=PASS_CONFIRMED,
        first_packet_hash=PACKET_HASH,
        second_pass=PASS_NO_CONFIRMED,
        second_packet_hash=PACKET_HASH,
    )
    assert result["verdict"] == INDETERMINATE
    assert result["diagnostic"] == "N3_ADJUDICATION_DISAGREEMENT"


def test_h5_confirmed_plus_indeterminate_is_indeterminate() -> None:
    """Regression 5."""

    result = consolidate_n3_passes(
        exposure_pseudonym="exp_0001",
        first_pass=PASS_CONFIRMED,
        first_packet_hash=PACKET_HASH,
        second_pass=PASS_INDETERMINATE,
        second_packet_hash=PACKET_HASH,
    )
    assert result["verdict"] == INDETERMINATE


def test_a_confirmed_first_pass_demands_a_second_pass() -> None:
    with pytest.raises(N3ProtocolError):
        consolidate_n3_passes(
            exposure_pseudonym="exp_0001",
            first_pass=PASS_CONFIRMED,
            first_packet_hash=PACKET_HASH,
        )


def test_both_passes_must_receive_a_byte_identical_packet() -> None:
    with pytest.raises(N3ProtocolError):
        consolidate_n3_passes(
            exposure_pseudonym="exp_0001",
            first_pass=PASS_CONFIRMED,
            first_packet_hash=PACKET_HASH,
            second_pass=PASS_CONFIRMED,
            second_packet_hash=OTHER_HASH,
            both_high_confidence=True,
            reasons_compatible=True,
        )


def test_second_pass_is_not_run_unless_the_first_confirmed() -> None:
    assert N3_SECOND_PASS_TRIGGER == "FIRST_PASS_DISPOSITION_IS_CONFIRMED"
    with pytest.raises(N3ProtocolError):
        consolidate_n3_passes(
            exposure_pseudonym="exp_0001",
            first_pass=PASS_NO_CONFIRMED,
            first_packet_hash=PACKET_HASH,
            second_pass=PASS_CONFIRMED,
            second_packet_hash=PACKET_HASH,
        )


def test_a_clean_first_pass_needs_no_second(_=None) -> None:
    result = consolidate_n3_passes(
        exposure_pseudonym="exp_0001",
        first_pass=PASS_NO_CONFIRMED,
        first_packet_hash=PACKET_HASH,
    )
    assert result["verdict"] == NO_CONFIRMED_VIOLATION


# --------------------------------------------------------------------------
# PART E - blind packet
# --------------------------------------------------------------------------


def test_packet_binds_every_required_field() -> None:
    packet = _packet()
    assert packet["stage"] == "P06"
    assert packet["system_prompt_id"] == "SYS_EVIDENCE_BOUND_V1"
    assert packet["developer_prompt_id"] == "P06_EVIDENCE_MAP_V1"
    assert packet["developer_prompt_hash"].startswith("sha256:")
    assert packet["contractual_authority_hash"].startswith("sha256:")
    assert packet["exposure_selector_hash"].startswith("sha256:")
    assert packet["packet_hash"].startswith("sha256:")
    assert packet["n3_gate_schema_version"] == N3_PROTOCOL_VERSION


@pytest.mark.parametrize(
    "field",
    [
        "expected_support_status",
        "oracle_state",
        "property_id",
        "candidate_model",
        "rung",
        "split",
        "is_held_out",
        "first_pass_decision",
        "first_pass_rationale",
        "old_qualification_results",
    ],
)
def test_packet_rejects_each_forbidden_field(field: str) -> None:
    assert field in N3_PACKET_FORBIDDEN_FIELDS
    with pytest.raises(N3ProtocolError):
        _packet(route_context={"construct": "x", field: "leaked"})


def test_packet_rejects_a_leak_nested_in_the_output() -> None:
    with pytest.raises(N3ProtocolError):
        _packet(model_owned_output={"support_status": "PARTIAL", "oracle_state": "VALID"})


def test_an_incomplete_packet_is_not_self_contained() -> None:
    packet = dict(_packet())
    del packet["contractual_rules"]
    with pytest.raises(N3ProtocolError):
        assert_n3_packet_blind(packet)


def test_packets_are_byte_deterministic() -> None:
    assert _packet()["packet_hash"] == _packet()["packet_hash"]


# --------------------------------------------------------------------------
# PART F / H6, H7, H8, H9 - aggregation and promotion
# --------------------------------------------------------------------------


def _verdict(name: str, exposure: str = "exp") -> dict:
    return {"exposure_pseudonym": exposure, "verdict": name}


def test_h6_technical_string_control_cannot_confirm_by_lexical_match() -> None:
    """Regression 6.

    The consolidator only ever sees dispositions, never evidence text, so there
    is no input by which a code-like span could raise a verdict.  A control
    exposure adjudicated clean stays clean.
    """

    population = n3_exposure_population(
        CORPUS_ROOT,
        REPO_ROOT / "reports" / "semantic_benchmark" / "v1_2" / "split_partition.json",
    )
    controls = [
        item
        for item in population["exposures"]
        if item["technical_string_control_available"]
    ]
    assert len(controls) == 9
    verdicts = [
        consolidate_n3_passes(
            exposure_pseudonym=item["exposure_id"],
            first_pass=PASS_NO_CONFIRMED,
            first_packet_hash=PACKET_HASH,
        )
        for item in controls
    ]
    assert all(row["verdict"] == NO_CONFIRMED_VIOLATION for row in verdicts)


def test_h7_semantic_error_without_contractual_violation_is_not_an_n3_failure() -> None:
    """Regression 7."""

    result = consolidate_n3_passes(
        exposure_pseudonym="exp_semantic_error",
        first_pass=PASS_NO_CONFIRMED,
        first_packet_hash=PACKET_HASH,
    )
    assert result["verdict"] == NO_CONFIRMED_VIOLATION
    aggregate = n3_rung_aggregate([result], required_exposure_count=1)
    assert aggregate["candidate_rung_n3_confirmed_failure_count"] == 0
    assert aggregate["promotion_disposition"] == "ELIGIBLE"


def test_h8_one_confirmed_failure_rejects_despite_a_perfect_semantic_rate() -> None:
    """Regression 8."""

    verdicts = [_verdict(NO_CONFIRMED_VIOLATION, f"e{i}") for i in range(9)]
    verdicts.append(_verdict(CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE, "e9"))
    aggregate = n3_rung_aggregate(verdicts, required_exposure_count=10)
    assert aggregate["candidate_rung_n3_confirmed_failure_count"] == 1
    assert aggregate["max_confirmed_failures"] == 0
    assert aggregate["rejects_candidate_rung"] is True
    assert aggregate["promotion_disposition"] == "REJECTED"
    assert "HARD_SAFETY_CONTRACTUAL_FAILURE_CONFIRMED" in aggregate["blocking_codes"]
    # Independent of the semantic axis by construction.
    assert aggregate["rejection_is_independent_of_semantic_rate"] is True
    assert aggregate["in_accepted_semantic_rate"] is False


def test_h9_an_unresolved_exposure_cannot_silently_promote() -> None:
    """Regression 9."""

    verdicts = [_verdict(NO_CONFIRMED_VIOLATION, f"e{i}") for i in range(9)]
    verdicts.append(_verdict(INDETERMINATE, "e9"))
    aggregate = n3_rung_aggregate(verdicts, required_exposure_count=10)
    assert aggregate["candidate_rung_n3_indeterminate_count"] == 1
    assert aggregate["promotion_disposition"] == "PENDING_BLOCKED"
    assert "N3_EXPOSURE_INDETERMINATE_AT_PROMOTION" in aggregate["blocking_codes"]
    # Never counted as a pass.
    assert aggregate["candidate_rung_n3_no_confirmed_violation_count"] == 9


def test_h9b_a_missing_required_exposure_also_blocks_promotion() -> None:
    verdicts = [_verdict(NO_CONFIRMED_VIOLATION, f"e{i}") for i in range(9)]
    aggregate = n3_rung_aggregate(verdicts, required_exposure_count=10)
    assert aggregate["unadjudicated_exposure_count"] == 1
    assert aggregate["promotion_disposition"] == "PENDING_BLOCKED"
    assert "N3_REQUIRED_EXPOSURE_NOT_ADJUDICATED" in aggregate["blocking_codes"]


def test_a_fully_clear_rung_is_eligible() -> None:
    verdicts = [_verdict(NO_CONFIRMED_VIOLATION, f"e{i}") for i in range(10)]
    aggregate = n3_rung_aggregate(verdicts, required_exposure_count=10)
    assert aggregate["promotion_disposition"] == "ELIGIBLE"
    assert aggregate["blocking_codes"] == []


def test_exposure_population_is_split_aware(tmp_path) -> None:
    """Phase 9B.7C: the population is partitioned, not run wholesale per rung."""

    population = n3_exposure_population(
        CORPUS_ROOT,
        REPO_ROOT / "reports" / "semantic_benchmark" / "v1_2" / "split_partition.json",
    )
    assert population["total_exposure_count"] == 10
    assert population["qualification_side_count"] == 7
    assert population["held_out_count"] == 3
    assert population["split_derived_from_outcomes"] is False


# --------------------------------------------------------------------------
# PART G / H10 - future boundary plan
# --------------------------------------------------------------------------


def _sound_plan() -> dict:
    return {
        "new_stage_boundaries": ["P06", "P07"],
        "p06_boundary_binds": list(N3_V13_P06_BOUNDARY_REQUIREMENTS),
        "p07_boundary_binds": list(N3_V13_P07_BOUNDARY_REQUIREMENTS),
        "protocol_artifacts": list(N3_V13_PROTOCOL_REQUIREMENTS),
    }


def test_a_complete_u3_n3_plan_is_sound() -> None:
    assert validate_u3_n3_boundary_plan(_sound_plan()) == []
    assert_u3_n3_boundary_plan(_sound_plan())


def test_h10_a_plan_omitting_an_n3_dependency_fails_closed() -> None:
    """Regression 10."""

    for dependency in N3_V13_P06_BOUNDARY_REQUIREMENTS:
        plan = _sound_plan()
        plan["p06_boundary_binds"] = [
            item for item in plan["p06_boundary_binds"] if item != dependency
        ]
        assert f"P06_BOUNDARY_OMITS::{dependency}" in (
            validate_u3_n3_boundary_plan(plan)
        )
        with pytest.raises(ValueError):
            assert_u3_n3_boundary_plan(plan)


def test_h10b_a_plan_dropping_the_phase9b6a_p07_inventory_fails_closed() -> None:
    plan = _sound_plan()
    plan["p07_boundary_binds"] = plan["p07_boundary_binds"][:-1]
    dropped = N3_V13_P07_BOUNDARY_REQUIREMENTS[-1]
    assert f"P07_BOUNDARY_OMITS::{dropped}" in validate_u3_n3_boundary_plan(plan)


def test_h10c_a_plan_missing_a_protocol_artifact_fails_closed() -> None:
    plan = _sound_plan()
    plan["protocol_artifacts"] = ["phase9-qualification-protocol/1.3.0"]
    violations = validate_u3_n3_boundary_plan(plan)
    assert any(item.startswith("PROTOCOL_ARTIFACT_MISSING::") for item in violations)


def test_h10d_a_plan_below_the_minimum_stage_set_fails_closed() -> None:
    plan = _sound_plan()
    plan["new_stage_boundaries"] = ["P06"]
    assert "MISSING_STAGE_BOUNDARY_P07" in validate_u3_n3_boundary_plan(plan)


def test_the_boundary_plan_binds_both_prompt_identities() -> None:
    p06 = set(N3_V13_P06_BOUNDARY_REQUIREMENTS)
    assert any("SYS_EVIDENCE_BOUND_V1" in item for item in p06)
    assert any("P06_EVIDENCE_MAP_V1" in item for item in p06)
    assert any("semantic-denominator-exclusion authority" in item for item in p06)


# --------------------------------------------------------------------------
# Surface
# --------------------------------------------------------------------------


def test_the_protocol_surface_is_deterministic_and_separate() -> None:
    first = n3_protocol_surface(CORPUS_ROOT, V12_ROOT)
    second = n3_protocol_surface(CORPUS_ROOT, V12_ROOT)
    assert first["surface_hash"] == second["surface_hash"]
    assert first["axis"] == "CONTRACTUAL_HARD_SAFETY"
    assert first["separate_from_semantic_axis"] is True
    assert tuple(first["semantic_result_states_unchanged"]) == SEMANTIC_RESULT_STATES
    assert first["aggregation"]["max_confirmed_failures"] == 0
    assert first["aggregation"]["max_indeterminate_at_promotion"] == 0
