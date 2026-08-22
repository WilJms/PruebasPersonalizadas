"""The Phase 9B.8B document may not state a value the machine does not."""

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
from comprehension_verification.semantic_benchmark_v13_boundary import (  # noqa: E402
    threshold_report_v13,
)
from comprehension_verification.semantic_benchmark_v132 import (  # noqa: E402
    DEFINITION_ROOT,
    REPORT_ROOT,
    REPUBLISHED_FROM_V131,
    build_v132,
    v132_package,
)

DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8B_V132_CLAIM_REBIND.md"
V131_DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8A_V131_REPAIR.md"


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
    return build_v132(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v132_package(build)


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


def test_the_boundary_table_matches(raw, package):
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    for stage, value in boundaries["stage_boundary_hashes"].items():
        row = re.search(rf"^\| {stage} \| ([^|]+) \| `({value})` \|$", raw, re.M)
        assert row, f"the {stage} row is missing or states the wrong hash"
        status = row.group(1).strip()
        expected = boundaries["boundary_status_by_stage"][stage]
        if expected == "NEW_IN_V132":
            assert status == "new in 1.3.2", stage
        else:
            assert status == "carried forward from 1.3.1", stage


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


def test_the_scan_result_matches(text, package):
    scan = package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"]
    assert f"Violations: {scan['violation_count']}" in text
    assert "deferred_to_closing_pass" in text
    assert len(scan["deferred_to_closing_pass"]) == 2


def test_the_republished_count_matches(text, package):
    assert f"Six artifacts are republished" in text
    assert len(REPUBLISHED_FROM_V131) == 6


def test_the_selection_semantics_match(text, package):
    semantics = package[f"{DEFINITION_ROOT}/phase9/construct_selection_semantics.json"]
    assert semantics["semantics_hash"] in text
    assert semantics["rule"] in text
    assert "pre-registered sampling rule" in text.lower()
    for denial in (
        "academically prioritized the first criterion",
        "the first construct is more important",
        "source position changes a semantic expected answer",
    ):
        assert denial in text, denial


def test_the_status_and_counters_are_stated(text, package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    assert freeze["stop_condition"] in text
    assert freeze["previous_version_status"] in text
    assert (
        "Provider calls 0, adjudicator calls 0, billable authorizations 0, "
        "credentials resolved 0" in text
    )


def test_the_superseded_banner_is_on_the_v131_document(package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    text = V131_DOCUMENT.read_text(encoding="utf-8")
    assert freeze["previous_version_status"] in text
    assert "PHASE9B8B_V132_CLAIM_REBIND.md" in text
