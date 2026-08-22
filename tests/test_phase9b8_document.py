"""The Phase 9B.8 document may not state a value the machine does not.

Phase 9B.6 found prose sitting beside a machine artifact and disagreeing with
it.  This file exists so that cannot recur: every hash, count and status the
document states is looked up here and compared with the generated package, and
a stale number fails a test instead of misleading a reader.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v13 import (  # noqa: E402
    build_v13,
)
from comprehension_verification.semantic_benchmark_v13_protocol import (  # noqa: E402
    DEFINITION_ROOT,
    REPORT_ROOT,
    v13_package,
)

DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8_V13_PREEXECUTION_FREEZE.md"


@pytest.fixture(scope="module")
def raw() -> str:
    return DOCUMENT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def text(raw: str) -> str:
    """The document with line wrapping collapsed.

    Prose wraps; a sentence the machine generated does not. Matching against a
    whitespace-normalized copy pins the numbers without pinning the wrapping.
    """

    return re.sub(r"\s+", " ", raw)


@pytest.fixture(scope="module")
def package() -> dict:
    return v13_package(build_v13(DEFAULT_CORPUS_ROOT))


def _doc(package: dict, relative: str) -> dict:
    return package[relative]


def test_every_hash_in_the_document_is_a_machine_value(raw, package):
    """No sha256 may appear in the prose unless the package produced it."""

    quoted = set(re.findall(r"`(sha256:[0-9a-f]{64})`", raw))
    assert quoted, "the document states no hashes at all"
    produced = set(re.findall(r'"(sha256:[0-9a-f]{64})"', json.dumps(package)))
    orphans = sorted(quoted - produced)
    assert not orphans, f"the document states hashes the package never produced: {orphans}"


def test_the_stage_boundary_table_matches(raw, package):
    boundaries = _doc(package, f"{REPORT_ROOT}/stage_boundaries.json")
    for stage, value in boundaries["stage_boundary_hashes"].items():
        row = re.search(rf"^\| {stage} \| ([^|]+) \| `({value})` \|$", raw, re.M)
        assert row, f"the {stage} row is missing or states the wrong hash"
        status = row.group(1).strip()
        expected = boundaries["boundary_status_by_stage"][stage]
        if expected == "NEW_IN_V13":
            assert status == "new in v1.3", stage
        else:
            assert status == "carried forward from v1.2", stage


def test_the_global_boundary_matches(text, package):
    boundary = _doc(package, f"{REPORT_ROOT}/benchmark_boundary.json")
    assert boundary["benchmark_boundary_hash"] in text


def test_the_instrument_counts_match(text, package):
    instrument = _doc(package, f"{REPORT_ROOT}/p06_instrument.json")
    splits = instrument["routes_by_split"]
    assert (
        f"{instrument['executable_route_count']} executable routes "
        f"({splits['CORE']} CORE, {splits['HELD_OUT_CONFIRMATION']} "
        f"HELD_OUT_CONFIRMATION, {splits['SMOKE']} SMOKE) over "
        f"{instrument['candidate_scoring_property_count']} candidate-scoring "
        f"properties, with {instrument['coverage_debt_count']} coverage-debt"
    ) in text
    narrowing = instrument["narrowing_proof_against_v12"]
    assert (
        f"{narrowing['v13_derived_scoring_property_count']} of "
        f"{narrowing['v12_audited_scoring_property_count']}, "
        f"{narrowing['removed_property_count']} removed and none added"
    ) in text


def test_the_support_status_line_matches(text, package):
    instrument = _doc(package, f"{REPORT_ROOT}/p06_instrument.json")
    counts = {
        status: value["candidate_scoring_property_count"]
        for status, value in instrument[
            "candidate_scoring_by_support_status_opportunity"
        ].items()
    }
    assert (
        f"`SUFFICIENT` {counts['SUFFICIENT']}, `PARTIAL` {counts['PARTIAL']}, "
        f"`INSUFFICIENT` {counts['INSUFFICIENT']}, `UNCERTAIN` {counts['UNCERTAIN']}"
    ) in text
    assert (
        f"{instrument['multi_status_property_count']} properties assert more "
        "than one status"
    ) in text


def test_the_threshold_table_matches(raw, package):
    thresholds = _doc(package, f"{DEFINITION_ROOT}/phase9/qualification_thresholds.json")
    for row in thresholds["p06_thresholds"]:
        expected = (
            f"| {row['split']} | {row['applicable_property_count']} | "
            f"{row['max_confirmed_model_failures']} | "
            f"{row['accepted_semantic_rate_bar']:.2f} |"
        )
        assert expected in raw, f"threshold row for {row['split']} is stale"


def test_the_n3_census_line_matches(text, package):
    axis = _doc(package, f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json")
    census = axis["census"]
    assert (
        f"{census['total']} exposures total, {census['qualification_side']} on "
        f"the qualification side, {census['held_out']} held" in text
    )
    assert (
        f"`N3_SAFETY_SMOKE` takes {census['N3_SAFETY_SMOKE']}" in text
    )
    assert f"remaining {census['N3_CORE']}" in text
    assert f"all {census['N3_HELD_OUT_CONFIRMATION']} held-out exposures" in text


def test_the_contractual_rule_count_and_prompt_match(text, package):
    axis = _doc(package, f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json")
    authority = axis["contractual_policy_authority"]
    assert f"{axis['contractual_rule_count']} contractual rules" in text
    assert (
        f"`{authority['prompt_id']}@{authority['prompt_version']}`" in text
    )


def test_the_n3_provider_call_finding_is_stated(text, package):
    budget = _doc(package, f"{REPORT_ROOT}/phase9/call_budget.json")
    finding = budget["n3_provider_calls_are_additional"]
    assert finding["n3_rides_existing_semantic_calls"] is False
    assert finding["noisy_submissions_with_an_executable_v13_p06_route"] == []
    assert "needs its own P06 provider" in text
    assert "four had their P06 properties excluded" in text
    assert "six state no P06 property at all" in text


def test_the_counters_are_stated_as_zero(text, package):
    freeze = _doc(package, f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json")
    counters = freeze["execution_counters"]
    assert counters["provider_calls"] == 0
    assert counters["adjudicator_calls"] == 0
    assert "Provider calls 0, adjudicator calls 0, billable authorizations 0," in text
    assert freeze["stop_condition"] in text


def test_the_candidate_policy_matches(text, package):
    matrix = _doc(package, f"{DEFINITION_ROOT}/phase9/candidate_matrix.json")
    assert matrix["stage_model_family"]["P04"] in text
    assert matrix["stage_model_family"]["P06"] in text
    assert matrix["candidate_matrix_hash"] in text
    assert "HIGH → XHIGH" in text
    assert "HIGH → XHIGH → MAX" in text
