"""Fail-closed regressions for semantic-benchmark/1.3.3 (Phase 9B.8C).

1.3.3 resolves the pre-U3 readiness gate.  Three things therefore have to hold
at once:

* the coverage fact is untouched -- UNCERTAIN is still UNCOVERED, still carries
  zero candidate-scoring properties, is still unqualified and still residual
  risk;
* the *disposition* of that fact is resolved -- U3 was accepted, so no active
  field demands a product decision and zero UNCERTAIN coverage no longer blocks
  readiness, while it still blocks any full-P06-contract-coverage claim;
* the release is bound to U3 -- withdraw the decision or substitute U1/U2/U4
  and readiness fails closed again.

Everything mechanical -- the 69 scoring properties, routes, denominators, bars,
the N3 fixtures and the budget -- must be provably identical to 1.3.2.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.n3_provider_fixtures import (  # noqa: E402
    n3_provider_fixture_authority,
)
from comprehension_verification.p06_support_status_coverage import (  # noqa: E402
    UNCERTAIN,
    uncertain_coverage_gate,
)
from comprehension_verification.p06_uncertain_coverage_resolution import (  # noqa: E402
    ACCEPTED_UNCERTAIN_DECISION,
    PRE_U3_STOP_CODE,
    PRODUCT_DECISION_SOURCE,
    RESOLVED,
    U3_RESOLUTION,
    UNCERTAIN_DECISION_OPTIONS,
    UncertainCoverageResolutionError,
    accepted_uncertain_product_decision,
    uncertain_coverage_disposition,
)
from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v13 import (  # noqa: E402
    V13BuildError,
)
from comprehension_verification.semantic_benchmark_v13_boundary import (  # noqa: E402
    threshold_report_v13,
)
from comprehension_verification.semantic_benchmark_v131 import (  # noqa: E402
    HashManifestError,
    call_budget_v131,
)
from comprehension_verification.semantic_benchmark_v133 import (  # noqa: E402
    DEFINITION_ROOT,
    FROZEN_N3_FIXTURE_SET_HASH,
    REPORT_ROOT,
    REPUBLISHED_FROM_V132,
    SELF_MATERIAL_HASH_FIELD,
    SEMANTIC_BENCHMARK_V133_VERSION,
    U3_LIMITATIONS_V133,
    build_v133,
    n3_fixture_equality_proof_v133,
    product_decision_state_scan,
    semantic_qualification_claim_v133,
    stale_claim_scan,
    u3_uncertain_disposition,
    v132_stage_change_proof,
    v133_package,
)

V132_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_2"
V132_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_2"
MANIFEST = REPOSITORY_ROOT / f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
_SUPERSEDED = re.compile(r"semantic-benchmark/1\.3\.[012]\b")

CLAIM_PATH = f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json"
DISPOSITION_PATH = f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json"
PROTOCOL_PATH = f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"
MATRIX_PATH = f"{DEFINITION_ROOT}/phase9/candidate_matrix.json"
BUDGET_PATH = f"{REPORT_ROOT}/phase9/call_budget.json"
FREEZE_PATH = f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
DECISION_SCAN_PATH = f"{REPORT_ROOT}/phase9/product_decision_state_scan.json"


@pytest.fixture(scope="module")
def build():
    return build_v133(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v133_package(build)


@pytest.fixture(scope="module")
def fixtures():
    return n3_provider_fixture_authority(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def disposition(build):
    return u3_uncertain_disposition(build)


@pytest.fixture(scope="module")
def claim(build, disposition):
    return semantic_qualification_claim_v133(build, disposition)


def _v132(relative: str) -> dict:
    root = (
        V132_DEFINITION_ROOT if relative.startswith("evaluation") else V132_REPORT_ROOT
    )
    return json.loads(
        (root / relative.split("v1_3_3/", 1)[1]).read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------
# PART A -- 1. the coverage fact survives the resolution untouched
# --------------------------------------------------------------------------


def test_active_coverage_is_still_uncovered(disposition, package, build):
    assert disposition["coverage_status"] == "UNCOVERED"
    assert disposition["candidate_scoring_property_count"] == 0
    assert disposition["residual_risk"] is True
    assert disposition["semantic_routes_added"] == 0
    assert disposition["semantic_properties_added"] == 0
    # derived, not declared: the instrument really carries no UNCERTAIN property
    coverage = build.support_status_coverage
    assert coverage["statuses"][UNCERTAIN]["covered"] is False
    assert coverage["statuses"][UNCERTAIN]["candidate_scoring_property_count"] == 0
    assert UNCERTAIN in coverage["uncovered_statuses"]
    assert package[DISPOSITION_PATH]["coverage_status"] == "UNCOVERED"
    assert package[CLAIM_PATH]["uncertain_coverage_status"] == "UNCOVERED"


def test_u3_did_not_manufacture_coverage(disposition, claim, package):
    assert claim["uncertain_scoring_property_count"] == 0
    assert claim["excluded_support_statuses"] == [UNCERTAIN]
    assert claim["qualified_support_statuses"] == [
        "SUFFICIENT",
        "PARTIAL",
        "INSUFFICIENT",
    ]
    assert disposition["what_u3_does_not_resolve"].startswith("the coverage itself")
    boundary = package[f"{REPORT_ROOT}/stage_boundaries.json"]["stages"]["P06"]
    assert boundary["uncertain_coverage_status"] == "UNCOVERED"


# --------------------------------------------------------------------------
# PART B -- 2-6. the resolved product-decision state
# --------------------------------------------------------------------------


def test_active_product_decision_is_u3(disposition, package):
    assert disposition["product_decision"] == "U3"
    assert disposition["product_decision_source"] == PRODUCT_DECISION_SOURCE
    assert package[CLAIM_PATH]["uncertain_coverage_product_decision"] == "U3"
    assert package[FREEZE_PATH]["uncertain_coverage_product_decision"] == "U3"
    protocol = package[PROTOCOL_PATH]["uncertain_coverage_readiness"]
    assert protocol["product_decision"] == "U3"


def test_active_decision_status_is_resolved(disposition, package):
    assert disposition["product_decision_status"] == RESOLVED
    assert disposition["resolution"] == U3_RESOLUTION
    assert package[CLAIM_PATH]["uncertain_coverage_product_decision_status"] == RESOLVED
    assert package[FREEZE_PATH]["uncertain_coverage_product_decision_status"] == RESOLVED
    assert (
        package[PROTOCOL_PATH]["uncertain_coverage_readiness"][
            "product_decision_status"
        ]
        == RESOLVED
    )


def test_active_requires_product_decision_is_false(disposition, package):
    assert disposition["requires_product_decision"] is False
    assert package[CLAIM_PATH]["uncertain_coverage_requires_product_decision"] is False
    assert package[FREEZE_PATH]["uncertain_coverage_requires_product_decision"] is False
    assert (
        package[PROTOCOL_PATH]["uncertain_coverage_readiness"][
            "additional_product_decision_pending_for_this_gap"
        ]
        is False
    )


def test_active_blocks_phase9_qualification_is_false(disposition, package):
    assert disposition["blocks_phase9_qualification"] is False
    assert disposition["blocks_candidate_rung_selection"] is False
    assert disposition["readiness_blocked"] is False
    assert package[CLAIM_PATH]["uncertain_coverage_blocks_phase9_qualification"] is False
    readiness = package[PROTOCOL_PATH]["uncertain_coverage_readiness"]
    assert readiness["zero_uncertain_coverage_blocks_execution"] is False


def test_active_blocks_full_contract_coverage_claim_is_true(disposition, package):
    assert disposition["blocks_full_p06_contract_coverage_claim"] is True
    assert (
        package[CLAIM_PATH]["uncertain_coverage_blocks_full_p06_contract_coverage_claim"]
        is True
    )
    assert package[CLAIM_PATH]["phase9_alone_is_full_p06_contract_coverage"] is False
    readiness = package[PROTOCOL_PATH]["uncertain_coverage_readiness"]
    assert (
        readiness[
            "zero_uncertain_coverage_blocks_full_p06_contract_coverage_claim"
        ]
        is True
    )


def test_uncovered_is_not_unresolved(disposition):
    text = disposition["uncovered_is_not_unresolved"]
    assert "UNCOVERED is a fact about the instrument" in text
    assert "UNRESOLVED was a fact about the product" in text
    assert disposition["may_be_closed_by_the_instrument"] is False


# --------------------------------------------------------------------------
# PART C -- 7-8. the stop code lives only in explicit history
# --------------------------------------------------------------------------


def test_no_active_field_says_product_decision_required(package):
    scan = product_decision_state_scan(
        package, republished_unchanged=REPUBLISHED_FROM_V132
    )
    assert scan["violations"] == []
    assert scan["violation_count"] == 0
    assert scan["active_stop_code"] is None
    assert scan["active_requires_product_decision"] is False
    assert scan["active_readiness_blocked"] is False
    assert scan["occurrences_found"] > 0, "the scan must actually find the token"
    assert package[DECISION_SCAN_PATH]["violation_count"] == 0
    assert package[FREEZE_PATH]["product_decision_state_violation_count"] == 0


def test_the_historical_gate_keeps_the_pre_u3_stop_code(disposition):
    history = disposition["pre_u3_uncertain_coverage_gate"]
    assert history["record_kind"] == "HISTORICAL_PRE_DECISION_EVIDENCE"
    assert history["is_the_active_state"] is False
    assert history["was_the_active_state_in_phase"] == "9B.6"
    assert history["triggered"] == "PHASE_9B7_UNCERTAIN_PRODUCT_DECISION"
    assert history["superseded_for_readiness_by"] == "U3"
    assert history["superseded_by_phase"] == "9B.7"
    assert history["readiness_blocked"] is True
    assert history["stop_code"] == PRE_U3_STOP_CODE
    # the gate function itself is quoted verbatim, not paraphrased
    assert history["gate_result_verbatim"]["stop_code"] == PRE_U3_STOP_CODE
    assert history["gate_result_verbatim"]["readiness_blocked"] is True


def test_the_pre_u3_gate_function_is_unchanged(build):
    gate = uncertain_coverage_gate(build.support_status_coverage)
    assert gate["readiness_blocked"] is True
    assert gate["stop_code"] == PRE_U3_STOP_CODE
    assert gate["covered"] is False
    assert gate["may_be_closed_by_the_instrument"] is False
    v132_claim = _v132(CLAIM_PATH)
    assert v132_claim["uncertain_coverage_gate"] == gate


def test_an_active_stop_code_fails_the_scan_closed(package):
    poisoned = json.loads(json.dumps(package))
    poisoned[CLAIM_PATH]["active_stop_code"] = PRE_U3_STOP_CODE
    with pytest.raises(V13BuildError, match="still says"):
        product_decision_state_scan(
            poisoned, republished_unchanged=REPUBLISHED_FROM_V132
        )


def test_an_active_readiness_block_fails_the_scan_closed(package):
    poisoned = json.loads(json.dumps(package))
    poisoned[PROTOCOL_PATH]["uncertain_coverage_readiness"]["readiness_blocked"] = True
    with pytest.raises(V13BuildError, match="still says"):
        product_decision_state_scan(
            poisoned, republished_unchanged=REPUBLISHED_FROM_V132
        )


# --------------------------------------------------------------------------
# PART E -- 9-10. the bypass exists only because U3 is bound
# --------------------------------------------------------------------------


def test_removing_the_decision_makes_readiness_fail_closed(build):
    unresolved = uncertain_coverage_disposition(
        build.support_status_coverage,
        product_decision=ACCEPTED_UNCERTAIN_DECISION,
        product_decision_status="PRODUCT_DECISION_REQUIRED",
    )
    assert unresolved["readiness_blocked"] is True
    assert unresolved["active_stop_code"] == PRE_U3_STOP_CODE
    assert unresolved["requires_product_decision"] is True
    assert unresolved["blocks_phase9_qualification"] is True
    assert unresolved["blocks_candidate_rung_selection"] is True
    assert unresolved["resolution"] is None
    assert unresolved["product_decision_status"] == "UNRESOLVED"
    assert unresolved["unresolved_reasons"]


@pytest.mark.parametrize("substitute", ["U1", "U2", "U4"])
def test_substituting_another_option_inherits_nothing(build, substitute):
    other = uncertain_coverage_disposition(
        build.support_status_coverage,
        product_decision=substitute,
        product_decision_status=RESOLVED,
    )
    assert other["readiness_blocked"] is True
    assert other["active_stop_code"] == PRE_U3_STOP_CODE
    assert other["requires_product_decision"] is True
    assert other["blocks_phase9_qualification"] is True
    assert other["resolution"] is None
    assert other["product_decision_status"] == "UNRESOLVED"
    assert any(substitute in reason for reason in other["unresolved_reasons"])
    # and it is a *rejection*, not an unrecognised value falling through
    assert substitute in UNCERTAIN_DECISION_OPTIONS
    assert substitute in other["non_accepted_option_requirements"]


def test_the_readiness_release_is_not_generic(disposition, package):
    assert disposition["readiness_disposition_is_bound_to"] == "U3"
    assert disposition["readiness_disposition_is_generic"] is False
    readiness = package[PROTOCOL_PATH]["uncertain_coverage_readiness"]
    assert readiness["readiness_release_is_bound_to"] == "U3"
    assert readiness["readiness_release_is_generic"] is False


def test_the_decision_is_read_from_the_9b7_package_not_assumed(tmp_path):
    decision = accepted_uncertain_product_decision(REPOSITORY_ROOT)
    assert decision["decision"] == "U3"
    assert decision["phase"] == "9B.7"
    assert decision["verdict"] == "PHASE9B7C_U3_N3_READY_FOR_PUBLICATION"
    assert decision["noisy_decision"] == "N3"
    assert decision["provider_calls"] == 0
    assert decision["adjudicator_calls"] == 0
    assert decision["candidate_outcomes_read"] is False
    with pytest.raises(UncertainCoverageResolutionError, match="missing"):
        accepted_uncertain_product_decision(tmp_path)


def test_a_9b7_package_that_stops_saying_u3_refuses_to_resolve(tmp_path):
    source = REPOSITORY_ROOT / PRODUCT_DECISION_SOURCE
    document = json.loads(source.read_text(encoding="utf-8"))
    document["uncertain_recommendation"] = "U1"
    target = tmp_path / PRODUCT_DECISION_SOURCE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(UncertainCoverageResolutionError, match="'U1'"):
        accepted_uncertain_product_decision(tmp_path)


def test_the_protocol_states_the_readiness_rule_mechanically(package):
    readiness = package[PROTOCOL_PATH]["uncertain_coverage_readiness"]
    assert readiness["zero_uncertain_coverage_blocks_execution"] is False
    assert (
        readiness["zero_uncertain_coverage_blocks_full_p06_contract_coverage_claim"]
        is True
    )
    assert readiness["additional_product_decision_pending_for_this_gap"] is False
    assert readiness["qualification_may_proceed_only_within_the_narrowed_claim"] is True
    assert readiness["narrowed_claim"] == package[CLAIM_PATH]["claim"]
    assert readiness["disposition_hash"] == package[DISPOSITION_PATH]["disposition_hash"]
    assert readiness["product_decision_hash"] == json.loads(
        (REPOSITORY_ROOT / PRODUCT_DECISION_SOURCE).read_text(encoding="utf-8")
    )["decision_hash"]


# --------------------------------------------------------------------------
# 11-13. UNCERTAIN stays out of the rate, out of the claim, in the contract
# --------------------------------------------------------------------------


def test_uncertain_cannot_enter_the_accepted_semantic_rate(build, package):
    readiness = package[PROTOCOL_PATH]["uncertain_coverage_readiness"]
    assert readiness["uncertain_may_enter_accepted_semantic_rate"] is False
    # the denominators are the proof: no split counts an UNCERTAIN property
    coverage = build.support_status_coverage
    assert coverage["statuses"][UNCERTAIN]["property_ids"] == []
    assert coverage["statuses"][UNCERTAIN]["by_split"] == {}
    rows = {
        row["split"]: row for row in threshold_report_v13(build)["p06_thresholds"]
    }
    assert rows["CORE"]["applicable_property_count"] == 41
    assert rows["HELD_OUT_CONFIRMATION"]["applicable_property_count"] == 27
    assert rows["SMOKE"]["applicable_property_count"] == 1


def test_uncertain_is_not_claimed_qualified(claim, disposition, package):
    assert claim["uncertain_qualification_claimed"] is False
    assert disposition["uncertain_qualification_claimed"] is False
    assert disposition["uncertain_remains_unqualified"] is True
    assert package[PROTOCOL_PATH]["uncertain_qualification_claimed"] is False
    assert (
        package[PROTOCOL_PATH]["uncertain_coverage_readiness"][
            "uncertain_is_claimed_qualified"
        ]
        is False
    )
    assert UNCERTAIN not in claim["qualified_support_statuses"]
    expected = (
        f"{SEMANTIC_BENCHMARK_V133_VERSION} does NOT qualify P06 UNCERTAIN behaviour."
    )
    assert claim["limitations"][0] == expected
    assert list(claim["limitations"]) == list(U3_LIMITATIONS_V133)
    assert "UNCERTAIN remains an explicit residual risk." in claim["limitations"]
    assert (
        "Phase 9 alone does not establish full P06 contract coverage."
        in claim["limitations"]
    )


def test_the_production_uncertain_contract_is_unchanged(claim, disposition, package):
    assert claim["uncertain_removed_from_production_contract"] is False
    assert disposition["uncertain_removed_from_production_contract"] is False
    assert claim["production_contract_unchanged"] is True
    assert package[PROTOCOL_PATH]["uncertain_removed_from_production_contract"] is False
    v132_claim = _v132(CLAIM_PATH)
    assert (
        claim["candidate_scoring_property_count_by_status"]
        == v132_claim["candidate_scoring_property_count_by_status"]
    )
    assert (
        claim["support_status_coverage_hash"]
        == v132_claim["support_status_coverage_hash"]
    )
    assert claim["uncertain_scope_census_hash"] == v132_claim["uncertain_scope_census_hash"]


# --------------------------------------------------------------------------
# PART G -- 14. the N3 fixture set is byte-identical
# --------------------------------------------------------------------------


def test_the_n3_fixture_set_hash_is_unchanged(fixtures):
    assert fixtures["fixture_set_hash"] == FROZEN_N3_FIXTURE_SET_HASH


def test_all_ten_provider_request_hashes_are_unchanged(fixtures):
    proof = n3_fixture_equality_proof_v133(fixtures)
    published = json.loads(
        (V132_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    assert proof["fixture_count"] == 10
    assert proof["fixtures_identical_to_v132"] is True
    expected = {
        item["n3_provider_fixture_id"]: item["provider_request_hash"]
        for item in published["fixtures"]
    }
    actual = {
        item["n3_provider_fixture_id"]: item["provider_request_hash"]
        for item in proof["per_fixture"]
    }
    assert actual == expected
    assert len(set(actual.values())) == 10


def test_the_construct_selections_and_split_are_unchanged(fixtures):
    published = json.loads(
        (V132_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    assert {
        item["n3_provider_fixture_id"]: item["target_construct_key"]
        for item in fixtures["fixtures"]
    } == {
        item["n3_provider_fixture_id"]: item["target_construct_key"]
        for item in published["fixtures"]
    }
    proof = n3_fixture_equality_proof_v133(fixtures)
    assert proof["split_sequencing_unchanged"] is True
    assert proof["counts_by_n3_split"] == {
        "N3_SAFETY_SMOKE": 1,
        "N3_CORE": 6,
        "N3_HELD_OUT_CONFIRMATION": 3,
    }


def test_a_moved_fixture_hash_fails_the_equality_proof(fixtures):
    mutated = json.loads(json.dumps(fixtures))
    mutated["fixture_set_hash"] = "sha256:" + "0" * 64
    with pytest.raises(V13BuildError, match="fixture set moved"):
        n3_fixture_equality_proof_v133(mutated)


def test_the_n3_axis_is_unchanged(package):
    assert package[f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json"] == _v132(
        f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json"
    )


# --------------------------------------------------------------------------
# PART G -- the rest of the semantic instrument is identical to 1.3.2
# --------------------------------------------------------------------------


def test_the_semantic_invariant_proof_covers_every_required_row(package, build):
    proof = package[f"{REPORT_ROOT}/phase9/semantic_invariant_equality_proof.json"]
    assert proof["all_identical"] is True
    assert proof["moved_invariants"] == []
    by_name = {row["invariant"]: row for row in proof["invariants"]}
    for required in (
        "candidate_scoring_set_hash",
        "route_definitions_hash",
        "case_definitions_hash",
        "property_bindings_hash",
        "split_assignments_hash",
        "candidate_scoring_property_count",
        "p06_applicable_property_count_by_split",
        "semantic_gates",
        "n3_gates",
        "ordering",
        "adjudication_protocol_hash",
        "candidate_identities",
        "call_budget_hash",
        "n3_counts_by_split",
        "n3_axis_hash",
        "split_partition_hash",
    ):
        assert required in by_name, required
        assert by_name[required]["identical"] is True, required
    assert proof["thresholds"] == {
        "SMOKE_min_accepted_rate": 0.80,
        "CORE_min_accepted_rate": 0.95,
        "HELD_OUT_CONFIRMATION_min_accepted_rate": 0.95,
    }
    assert proof["construct_selection_changed"] is False
    assert proof["threshold_rung_or_family_changed"] is False
    assert proof["corpus_bytes_modified"] is False


def test_the_sixty_nine_scoring_properties_are_unchanged(build):
    v132_boundary = json.loads(
        (V132_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert len(build.derivation.scoring_property_ids) == 69
    assert canonical_hash(list(build.derivation.scoring_property_ids)) == v132_boundary[
        "stages"
    ]["P06"]["candidate_scoring_set_hash"]


def test_the_semantic_routes_are_unchanged(package):
    v132_boundary = json.loads(
        (V132_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )["stages"]["P06"]
    v133_boundary = package[f"{REPORT_ROOT}/stage_boundaries.json"]["stages"]["P06"]
    for key in (
        "route_definitions_hash",
        "case_definitions_hash",
        "property_bindings_hash",
        "split_assignments_hash",
        "construct_catalog_hash",
        "coverage_debt_hash",
        "fixture_input_hashes_hash",
        "candidate_scoring_set_hash",
        "p06_instrument_hash",
        "corpus_package_boundary_hash",
    ):
        assert v133_boundary[key] == v132_boundary[key], key


def test_bars_ordering_and_adjudication_are_unchanged(package):
    protocol = package[PROTOCOL_PATH]
    v132 = _v132(PROTOCOL_PATH)
    assert protocol["semantic_gates"] == v132["semantic_gates"]
    assert protocol["n3_gates"] == v132["n3_gates"]
    assert protocol["ordering"] == v132["ordering"]
    assert protocol["adjudication_protocol_hash"] == v132["adjudication_protocol_hash"]
    assert protocol["semantic_gates"]["max_confirmed_hard_safety_model_failures"] == 0


def test_candidate_identities_rungs_and_families_are_unchanged(package):
    matrix = package[MATRIX_PATH]
    v132 = _v132(MATRIX_PATH)
    assert matrix["candidates"] == v132["candidates"]
    assert matrix["candidate_identities_changed_from_v132"] is False
    assert matrix["carried_candidate_identity_hash"] == canonical_hash(v132["candidates"])


def test_the_call_budget_hash_did_not_move(package, build, fixtures):
    budget = package[BUDGET_PATH]
    v132 = _v132(BUDGET_PATH)
    assert budget == v132
    assert call_budget_v131(build, fixtures)["call_budget_hash"] == v132["call_budget_hash"]
    assert package[PROTOCOL_PATH]["call_budget_hash"] == v132["call_budget_hash"]
    for section in (
        "provider_call_budget",
        "semantic_adjudicator_budget",
        "n3_adjudicator_budget",
    ):
        assert budget[section] == v132[section]


# --------------------------------------------------------------------------
# PART F -- boundaries move only where their bound material moved
# --------------------------------------------------------------------------


def test_the_p06_boundary_is_new_and_binds_the_resolution(package, claim, disposition):
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    v132 = json.loads(
        (V132_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    p06 = boundaries["stages"]["P06"]
    assert p06["boundary_status"] == "NEW_IN_V133"
    assert p06["stage_boundary_hash"] != v132["stage_boundary_hashes"]["P06"]
    assert p06["supersedes_v132_p06_boundary"] == v132["stage_boundary_hashes"]["P06"]
    assert p06["semantic_qualification_claim_hash"] == claim["claim_hash"]
    assert p06["uncertain_coverage_disposition_hash"] == disposition["disposition_hash"]
    assert p06["uncertain_coverage_product_decision"] == "U3"
    assert (
        p06["uncertain_coverage_product_decision_source"] == PRODUCT_DECISION_SOURCE
    )
    assert p06["uncertain_coverage_product_decision_hash"] == json.loads(
        (REPOSITORY_ROOT / PRODUCT_DECISION_SOURCE).read_text(encoding="utf-8")
    )["decision_hash"]
    assert p06["n3_provider_fixture_set_hash"] == FROZEN_N3_FIXTURE_SET_HASH
    assert p06["n3_provider_fixture_set_hash_unchanged_from_v132"] is True
    assert p06["n3_provider_authority_fully_bound"] is True


@pytest.mark.parametrize("stage", ["P04", "P07", "P09", "PLANNER"])
def test_carry_forward_stages_are_proved_unchanged(build, package, stage):
    proof = v132_stage_change_proof(build, stage)
    assert proof["stage_local_material_changed"] is False
    assert proof["changed_components"] == []
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    v132 = json.loads(
        (V132_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert boundaries["boundary_status_by_stage"][stage] == "CARRIED_FORWARD_FROM_V132"
    assert (
        boundaries["stage_boundary_hashes"][stage]
        == v132["stage_boundary_hashes"][stage]
    )


def test_the_global_boundary_and_protocol_moved_with_their_inputs(package):
    global_boundary = package[f"{REPORT_ROOT}/benchmark_boundary.json"]
    v132_global = _v132(f"{REPORT_ROOT}/benchmark_boundary.json")
    assert (
        global_boundary["benchmark_boundary_hash"]
        != v132_global["benchmark_boundary_hash"]
    )
    assert global_boundary["previous_version"] == "semantic-benchmark/1.3.2"
    assert (
        global_boundary["previous_version_status"]
        == "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
    )
    assert global_boundary["uncertain_coverage_product_decision"] == "U3"
    protocol = package[PROTOCOL_PATH]
    assert protocol["protocol_boundary_hash"] != _v132(PROTOCOL_PATH)[
        "protocol_boundary_hash"
    ]
    assert protocol["benchmark_boundary_hash"] == global_boundary[
        "benchmark_boundary_hash"
    ]


# --------------------------------------------------------------------------
# no current statement names a superseded version
# --------------------------------------------------------------------------


def test_no_current_authority_names_a_superseded_version(package):
    scan = stale_claim_scan(package, republished_unchanged=REPUBLISHED_FROM_V132)
    assert scan["violations"] == []
    assert scan["violation_count"] == 0
    assert scan["mentions_found"] > 0
    assert package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"]["violation_count"] == 0


def test_a_stale_current_claim_fails_closed(package):
    poisoned = json.loads(json.dumps(package))
    poisoned[CLAIM_PATH]["claim"] = (
        "semantic-benchmark/1.3.2 qualifies P06 candidate behaviour."
    )
    with pytest.raises(V13BuildError, match="names a superseded"):
        stale_claim_scan(poisoned, republished_unchanged=REPUBLISHED_FROM_V132)


def test_the_active_claim_and_limitation_name_the_active_version(claim, package):
    expected = (
        f"{SEMANTIC_BENCHMARK_V133_VERSION} qualifies P06 candidate behaviour on "
        "the support statuses SUFFICIENT, PARTIAL and INSUFFICIENT."
    )
    assert claim["claim"] == expected
    for path in (PROTOCOL_PATH, FREEZE_PATH):
        assert package[path]["semantic_qualification_claim"] == expected
    assert (
        package[f"{REPORT_ROOT}/benchmark_boundary.json"][
            "semantic_qualification_claim"
        ]
        == expected
    )
    assert not _SUPERSEDED.search(claim["claim"])
    assert not _SUPERSEDED.search(claim["limitations"][0])


# --------------------------------------------------------------------------
# PART K -- the hash manifest
# --------------------------------------------------------------------------


@pytest.mark.parametrize("relative", sorted(SELF_MATERIAL_HASH_FIELD))
def test_every_manifest_entry_uses_the_document_self_hash(relative, package):
    from comprehension_verification.semantic_benchmark_v133 import self_material_hash

    if not MANIFEST.exists():
        pytest.skip("the 1.3.3 manifest is not built in this working tree")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {item["path"]: item for item in manifest["artifacts"]}
    assert relative in entries
    assert entries[relative]["internal_material_hash"] == self_material_hash(
        relative, package[relative]
    )
    assert (
        entries[relative]["self_material_hash_field"]
        == SELF_MATERIAL_HASH_FIELD[relative]
    )


def test_a_dependency_hash_cannot_masquerade_as_a_self_hash(package):
    from comprehension_verification.semantic_benchmark_v133 import self_material_hash

    poisoned = dict(package[PROTOCOL_PATH])
    poisoned["protocol_boundary_hash"] = poisoned["benchmark_boundary_hash"]
    with pytest.raises(HashManifestError, match="not this document's material hash"):
        self_material_hash(PROTOCOL_PATH, poisoned)


def test_the_registry_matches_the_generated_package(package):
    assert sorted(package) == sorted(SELF_MATERIAL_HASH_FIELD)


def test_the_manifest_excludes_itself_and_flags_republished_entries():
    if not MANIFEST.exists():
        pytest.skip("the 1.3.3 manifest is not built in this working tree")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["artifacts"]}
    assert manifest["manifest_excludes_itself"] is True
    assert f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json" not in paths
    republished = {
        item["path"]
        for item in manifest["artifacts"]
        if item["republished_unchanged_from"] == "semantic-benchmark/1.3.2"
    }
    assert republished == set(REPUBLISHED_FROM_V132)
    assert manifest["republished_unchanged_artifact_count"] == len(
        REPUBLISHED_FROM_V132
    )
    assert manifest["artifacts_without_a_self_material_hash"] == []


def test_git_agrees_with_the_recorded_blob_shas():
    if not MANIFEST.exists():
        pytest.skip("the 1.3.3 manifest is not built in this working tree")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        path = REPOSITORY_ROOT / item["path"]
        if not path.exists():
            pytest.skip(f"{item['path']} is not built in this working tree")
        result = subprocess.run(
            ["git", "hash-object", item["path"]],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == item["git_blob_sha"], item["path"]


# --------------------------------------------------------------------------
# 15. immutability, determinism, working directory, local corpus
# --------------------------------------------------------------------------


def test_republished_artifacts_are_byte_identical_to_v132():
    for relative, tail in REPUBLISHED_FROM_V132.items():
        current = REPOSITORY_ROOT / relative
        if not current.exists():
            pytest.skip(f"{relative} is not built in this working tree")
        root = (
            V132_DEFINITION_ROOT
            if relative.startswith("evaluation")
            else V132_REPORT_ROOT
        )
        assert current.read_bytes() == (root / tail).read_bytes(), relative


def test_v132_v131_v130_v12_and_the_corpus_remain_byte_identical():
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "evaluation/semantic_benchmark/v1_2",
            "reports/semantic_benchmark/v1_2",
            "evaluation/semantic_benchmark/v1_3",
            "reports/semantic_benchmark/v1_3",
            "evaluation/semantic_benchmark/v1_3_1",
            "reports/semantic_benchmark/v1_3_1",
            "evaluation/semantic_benchmark/v1_3_2",
            "reports/semantic_benchmark/v1_3_2",
            "reports/semantic_benchmark/phase9b6",
            "reports/semantic_benchmark/phase9b7",
            "evaluation/corpora/pruebas_personalizadas/v1",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        f"published versions must stay byte-identical: {result.stdout}"
    )


def test_the_lineage_marks_v132_superseded_with_zero_execution(package):
    lineage = package[f"{REPORT_ROOT}/lineage.json"]
    by_version = {item["version"]: item for item in lineage["chain"]}
    v132 = by_version["semantic-benchmark/1.3.2"]
    assert (
        v132["status"] == "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
    )
    assert v132["provider_calls"] == 0
    assert v132["adjudicator_calls"] == 0
    assert v132["candidate_outcomes_read"] is False
    assert v132["authorization"] == "NONE"
    assert v132["bytes_modified_by_v133"] is False
    for older in ("semantic-benchmark/1.3.0", "semantic-benchmark/1.3.1"):
        assert by_version[older]["bytes_modified_by_v133"] is False
    assert (
        by_version[SEMANTIC_BENCHMARK_V133_VERSION]["status"]
        == "PREEXECUTION_FREEZE_CANDIDATE"
    )
    assert lineage["is_a_corpus_change"] is False
    assert lineage["is_a_semantic_product_decision_change"] is False
    assert lineage["reopens_the_u3_product_decision"] is False
    assert lineage["is_a_pre_execution_authority_binding_repair"] is True
    assert lineage["carried_forward_artifact_count"] == len(REPUBLISHED_FROM_V132)


def test_cwd_does_not_change_any_v133_output(package, tmp_path):
    previous = Path.cwd()
    try:
        os.chdir(tmp_path)
        rebuilt = v133_package(build_v133(DEFAULT_CORPUS_ROOT))
    finally:
        os.chdir(previous)
    assert sorted(rebuilt) == sorted(package)
    for relative in package:
        assert canonical_hash(rebuilt[relative]) == canonical_hash(package[relative])


def test_the_local_protected_corpus_copy_changes_nothing(package):
    for document in package.values():
        assert "pruebas_personalizadas_corpus" not in json.dumps(document)
    for name in (
        "semantic_benchmark_v133.py",
        "p06_uncertain_coverage_resolution.py",
    ):
        source = (
            REPOSITORY_ROOT / "src/comprehension_verification" / name
        ).read_text(encoding="utf-8")
        assert "pruebas_personalizadas_corpus" not in source


def test_the_package_is_deterministic_across_two_builds():
    first = v133_package(build_v133(DEFAULT_CORPUS_ROOT))
    second = v133_package(build_v133(DEFAULT_CORPUS_ROOT))
    assert sorted(first) == sorted(second)
    for relative in first:
        assert canonical_hash(first[relative]) == canonical_hash(second[relative])


def test_the_published_package_matches_a_fresh_build(package):
    for relative, document in package.items():
        path = REPOSITORY_ROOT / relative
        if not path.exists():
            pytest.skip(f"{relative} is not built in this working tree")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert canonical_hash(on_disk) == canonical_hash(document), relative


# --------------------------------------------------------------------------
# PART J -- zero execution
# --------------------------------------------------------------------------


def test_every_execution_counter_is_zero(package):
    freeze = package[FREEZE_PATH]
    counters = freeze["execution_counters"]
    assert counters["provider_calls"] == 0
    assert counters["adjudicator_calls"] == 0
    assert counters["billable_authorizations"] == 0
    assert counters["credentials_resolved"] == 0
    assert counters["real_transport_constructed"] is False
    assert counters["candidate_outcomes_read"] is False
    assert counters["high_smoke_authorized"] is False
    assert counters["pricing_refreshed"] is False
    assert counters["authorization"] == "NONE"
    assert freeze["qualification_run"] is False
    assert freeze["stale_claim_violation_count"] == 0
    assert freeze["product_decision_state_violation_count"] == 0
    assert freeze["results_firewall"]["candidate_outcomes_read"] is False
    assert freeze["corpus_bytes_modified"] is False
    assert freeze["stop_condition"] == (
        "SEMANTIC_BENCHMARK_V1_3_3_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT"
    )
