"""The Phase 9B.8C document may not state a value the machine does not."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.p06_uncertain_coverage_resolution import (  # noqa: E402
    PRODUCT_DECISION_SOURCE,
)
from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v13_boundary import (  # noqa: E402
    threshold_report_v13,
)
from comprehension_verification.semantic_benchmark_v133 import (  # noqa: E402
    DEFINITION_ROOT,
    REPORT_ROOT,
    REPUBLISHED_FROM_V132,
    build_v133,
    v133_package,
)

DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8C_V133_UNCERTAIN_READINESS_RESOLUTION.md"
V132_DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8B_V132_CLAIM_REBIND.md"


@pytest.fixture(scope="module")
def raw() -> str:
    return DOCUMENT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def text(raw: str) -> str:
    """The document with blockquote markers and line wrapping removed.

    Prose wraps and quotes; a sentence the machine generated does neither, so
    both are normalised away before matching.
    """

    unquoted = re.sub(r"^\s*>\s?", "", raw, flags=re.M)
    return re.sub(r"\s+", " ", unquoted)


@pytest.fixture(scope="module")
def build():
    return build_v133(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v133_package(build)


def test_every_hash_in_the_document_is_a_machine_value(raw, package):
    quoted = set(re.findall(r"`(sha256:[0-9a-f]{64})`", raw))
    assert quoted
    produced = set(re.findall(r'"(sha256:[0-9a-f]{64})"', json.dumps(package)))
    orphans = sorted(quoted - produced)
    assert not orphans, f"the document states hashes the package never produced: {orphans}"


def test_the_claim_and_limitations_match(text, package):
    claim = package[f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json"]
    assert claim["claim"].rstrip(".") in text
    for limitation in claim["limitations"]:
        assert limitation in text, limitation
    assert claim["claim_hash"] in text
    assert claim["applicable_benchmark_version"] in text
    assert claim["supersedes_claim_binding_from"] in text


def test_the_coverage_fact_table_matches(text, package):
    disposition = package[
        f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json"
    ]
    assert disposition["coverage_status"] == "UNCOVERED"
    for field in (
        "coverage_status",
        "candidate_scoring_property_count",
        "uncertain_qualification_claimed",
        "uncertain_removed_from_production_contract",
        "residual_risk",
        "semantic_routes_added",
        "semantic_properties_added",
    ):
        assert f"`{field}`" in text, field
    assert "| `coverage_status` | `UNCOVERED` |" in text
    assert "| `candidate_scoring_property_count` | 0 |" in text
    assert "| `residual_risk` | true |" in text


def test_the_disposition_table_matches(text, package):
    disposition = package[
        f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json"
    ]
    assert disposition["disposition_hash"] in text
    assert f"| `decision_gap` | `{disposition['decision_gap']}` |" in text
    assert f"| `pre_decision_status` | `{disposition['pre_decision_status']}` |" in text
    assert f"| `product_decision` | `{disposition['product_decision']}` |" in text
    assert (
        f"| `product_decision_status` | `{disposition['product_decision_status']}` |"
        in text
    )
    assert f"| `resolution` | `{disposition['resolution']}` |" in text
    assert disposition["product_decision_source"] in text
    for field, value in (
        ("requires_product_decision", "false"),
        ("blocks_phase9_qualification", "false"),
        ("blocks_candidate_rung_selection", "false"),
        ("blocks_full_p06_contract_coverage_claim", "true"),
        ("uncertain_remains_unqualified", "true"),
        ("readiness_blocked", "false"),
        ("active_stop_code", "null"),
    ):
        assert f"| `{field}` | {value} |" in text, field
        assert json.dumps(disposition[field]) == value, field


def test_the_historical_gate_is_described_as_history(text, package):
    history = package[f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json"][
        "pre_u3_uncertain_coverage_gate"
    ]
    assert history["record_kind"] in text
    assert "`is_the_active_state: false`" in text
    assert history["was_the_active_state_in_phase"] in text
    assert history["triggered"] in text
    assert "`superseded_for_readiness_by: U3`" in text
    assert history["superseded_for_readiness_by"] == "U3"


def test_the_product_decision_scan_result_matches(text, package):
    scan = package[f"{REPORT_ROOT}/phase9/product_decision_state_scan.json"]
    assert scan["scan_hash"] in text
    assert f"Occurrences: {scan['occurrences_found']}." in text
    assert f"Violations: {scan['violation_count']}." in text
    reasons = {row["reason"] for row in scan["permitted_occurrences"]}
    for reason in reasons:
        assert reason in text, reason


def test_the_fail_closed_table_matches(text, build):
    from comprehension_verification.p06_uncertain_coverage_resolution import (
        PRE_U3_STOP_CODE,
        uncertain_coverage_disposition,
    )

    unresolved = uncertain_coverage_disposition(
        build.support_status_coverage,
        product_decision="U1",
        product_decision_status="RESOLVED",
    )
    assert unresolved["readiness_blocked"] is True
    assert unresolved["active_stop_code"] == PRE_U3_STOP_CODE
    assert f"| U1, U2 or U4 | true | `{PRE_U3_STOP_CODE}` |" in text
    assert "| U3 / RESOLVED | false | null |" in text
    assert f"| U3 / not RESOLVED | true | `{PRE_U3_STOP_CODE}` |" in text


def test_the_protocol_readiness_table_matches(text, package):
    readiness = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"][
        "uncertain_coverage_readiness"
    ]
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    assert protocol["protocol_boundary_hash"] in text
    assert protocol["protocol_version"] in text
    for field in (
        "zero_uncertain_coverage_blocks_execution",
        "zero_uncertain_coverage_blocks_full_p06_contract_coverage_claim",
        "additional_product_decision_pending_for_this_gap",
        "qualification_may_proceed_only_within_the_narrowed_claim",
        "uncertain_may_enter_accepted_semantic_rate",
        "uncertain_is_claimed_qualified",
        "readiness_release_is_generic",
    ):
        assert (
            f"| `{field}` | {json.dumps(readiness[field])} |" in text
        ), field


def test_the_boundary_table_matches(raw, package):
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    for stage, value in boundaries["stage_boundary_hashes"].items():
        row = re.search(rf"^\| {stage} \| ([^|]+) \| `({value})` \|$", raw, re.M)
        assert row, f"the {stage} row is missing or states the wrong hash"
        status = row.group(1).strip()
        expected = boundaries["boundary_status_by_stage"][stage]
        if expected == "NEW_IN_V133":
            assert status == "new in 1.3.3", stage
        else:
            assert status == "carried forward from 1.3.2", stage


def test_the_aggregate_hash_table_matches(text, package):
    for relative, field in (
        (f"{REPORT_ROOT}/stage_boundaries.json", "stage_boundaries_hash"),
        (f"{REPORT_ROOT}/benchmark_boundary.json", "benchmark_boundary_hash"),
        (f"{DEFINITION_ROOT}/phase9/candidate_matrix.json", "candidate_matrix_hash"),
        (f"{REPORT_ROOT}/lineage.json", "lineage_hash"),
        (
            f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json",
            "freeze_material_hash",
        ),
    ):
        assert package[relative][field] in text, relative


def test_the_unchanged_table_matches(text, build, package):
    thresholds = {
        row["split"]: row["applicable_property_count"]
        for row in threshold_report_v13(build)["p06_thresholds"]
    }
    assert (
        f"CORE {thresholds['CORE']}, HELD_OUT_CONFIRMATION "
        f"{thresholds['HELD_OUT_CONFIRMATION']}, SMOKE {thresholds['SMOKE']}"
    ) in text
    assert f"{len(build.derivation.scoring_property_ids)}, hash identical" in text
    fixtures = package[f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json"]
    assert fixtures["fixture_set_hash"] in text
    counts = fixtures["counts_by_n3_split"]
    assert (
        f"{counts['N3_SAFETY_SMOKE']} SAFETY_SMOKE / {counts['N3_CORE']} CORE / "
        f"{counts['N3_HELD_OUT_CONFIRMATION']} HELD_OUT"
    ) in text
    budget = package[f"{REPORT_ROOT}/phase9/call_budget.json"]
    assert budget["call_budget_hash"] in text
    axis = package[f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json"]
    assert axis["n3_axis_hash"] in text
    invariants = package[f"{REPORT_ROOT}/phase9/semantic_invariant_equality_proof.json"]
    assert invariants["proof_hash"] in text
    assert f"reconstructs {invariants['invariant_count']} invariants" in text
    equality = package[f"{REPORT_ROOT}/phase9/n3_fixture_equality_proof.json"]
    assert equality["proof_hash"] in text
    assert f"all {equality['fixture_count']} identical" in text
    gates = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"][
        "semantic_gates"
    ]
    assert (
        f"{gates['SMOKE_min_accepted_rate']:.2f} SMOKE / "
        f"{gates['CORE_min_accepted_rate']:.2f} CORE / "
        f"{gates['HELD_OUT_CONFIRMATION_min_accepted_rate']:.2f} HELD_OUT"
    ) in text
    assert gates["max_confirmed_hard_safety_model_failures"] == 0


def test_the_stale_scan_result_matches(text, package):
    scan = package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"]
    assert scan["scan_hash"] in text
    assert f"Mentions found: {scan['mentions_found']}." in text
    assert f"Violations: {scan['violation_count']}." in text
    assert "deferred_to_closing_pass" in text
    assert len(scan["deferred_to_closing_pass"]) == 2


def test_the_republished_count_matches(text):
    assert "Seven artifacts are republished" in text
    assert len(REPUBLISHED_FROM_V132) == 7


def test_the_product_decision_source_is_stated(text, package):
    decision = json.loads(
        (REPOSITORY_ROOT / PRODUCT_DECISION_SOURCE).read_text(encoding="utf-8")
    )
    assert PRODUCT_DECISION_SOURCE in text
    assert decision["verdict"] in text
    assert decision["decision_hash"] in text
    assert decision["uncertain_recommendation"] == "U3"
    disposition = package[
        f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json"
    ]
    assert disposition["product_decision_source_file_sha256"] in text


def test_the_status_and_counters_are_stated(text, package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    assert freeze["stop_condition"] in text
    assert freeze["previous_version_status"] in text
    assert (
        "Provider calls 0, adjudicator calls 0, billable authorizations 0, "
        "credentials resolved 0" in text
    )


def test_the_superseded_banner_is_on_the_v132_document(package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    text = V132_DOCUMENT.read_text(encoding="utf-8")
    assert freeze["previous_version_status"] in text
    assert "PHASE9B8C_V133_UNCERTAIN_READINESS_RESOLUTION.md" in text
