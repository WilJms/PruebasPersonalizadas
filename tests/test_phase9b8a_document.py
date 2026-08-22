"""The Phase 9B.8A document may not state a value the machine does not.

Same rule as Phase 9B.8: every hash, count, split and status the prose states is
looked up here and compared with the generated package, so a stale number fails
a test rather than misleading a reader.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.n3_provider_fixtures import (  # noqa: E402
    N3_CONSTRUCT_SELECTION_RULE,
    noisy_disposition_census,
)
from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v131 import (  # noqa: E402
    DEFINITION_ROOT,
    REPORT_ROOT,
    build_v131,
    v131_package,
)

DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8A_V131_REPAIR.md"
V130_DOCUMENT = REPOSITORY_ROOT / "docs/PHASE9B8_V13_PREEXECUTION_FREEZE.md"


@pytest.fixture(scope="module")
def raw() -> str:
    return DOCUMENT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def text(raw: str) -> str:
    return re.sub(r"\s+", " ", raw)


@pytest.fixture(scope="module")
def package() -> dict:
    return v131_package(build_v131(DEFAULT_CORPUS_ROOT))


def test_every_hash_in_the_document_is_a_machine_value(raw, package):
    quoted = set(re.findall(r"`(sha256:[0-9a-f]{64})`", raw))
    assert quoted
    produced = set(re.findall(r'"(sha256:[0-9a-f]{64})"', json.dumps(package)))
    orphans = sorted(quoted - produced)
    assert not orphans, f"the document states hashes the package never produced: {orphans}"


def test_the_boundary_table_matches(raw, package):
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    for stage, value in boundaries["stage_boundary_hashes"].items():
        row = re.search(rf"^\| {stage} \| ([^|]+) \| `({value})` \|$", raw, re.M)
        assert row, f"the {stage} row is missing or states the wrong hash"
        status = row.group(1).strip()
        expected = boundaries["boundary_status_by_stage"][stage]
        if expected == "NEW_IN_V131":
            assert status == "new in 1.3.1", stage
        else:
            assert status == "carried forward from 1.3.0", stage


def test_the_fixture_table_matches(raw, package):
    fixtures = package[f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json"]
    for fixture in fixtures["fixtures"]:
        row = re.search(
            rf"^\| {re.escape(fixture['n3_provider_fixture_id'])} \| "
            rf"{fixture['n3_split']} \| [^|]+ \| "
            rf"{fixture['model_visible_evidence_unit_count']} \|$",
            raw,
            re.M,
        )
        assert row, f"{fixture['n3_provider_fixture_id']} row is missing or stale"


def test_the_derived_counts_match(text, package):
    fixtures = package[f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json"]
    assert (
        f"{fixtures['fixture_count']} total, "
        f"{fixtures['safety_smoke_fixture_count']} SAFETY_SMOKE, "
        f"{fixtures['core_fixture_count']} CORE, "
        f"{fixtures['held_out_fixture_count']} HELD_OUT_CONFIRMATION"
    ) in text
    assert fixtures["fixture_set_hash"] in text


def test_the_noisy_census_line_matches(text):
    census = noisy_disposition_census(DEFAULT_CORPUS_ROOT)
    for field in (
        "noisy_exposure_count",
        "noisy_with_executable_semantic_route_count",
        "noisy_with_p06_property_but_excluded_count",
        "noisy_with_no_p06_property_count",
    ):
        assert f"`{field}` {census[field]}" in text, field


def test_the_selection_rule_and_its_independence_match(text, package):
    proof = package[f"{REPORT_ROOT}/phase9/construct_selection_independence.json"]
    assert f"`{N3_CONSTRUCT_SELECTION_RULE}`" in text
    assert proof["rule"] == N3_CONSTRUCT_SELECTION_RULE
    moved = proof["activities_whose_selection_moves_when_source_order_is_reversed"]
    assert f"all {moved} selections move" in text


def test_the_lexical_disagreement_count_matches(text):
    from comprehension_verification.n3_provider_fixtures import (
        build_n3_provider_fixtures,
        source_order_key,
    )
    from comprehension_verification.semantic_benchmark_v12 import build_construct_catalog

    catalog = build_construct_catalog(DEFAULT_CORPUS_ROOT)
    fixtures = build_n3_provider_fixtures(DEFAULT_CORPUS_ROOT).fixtures
    differing = 0
    for fixture in fixtures:
        rows = [
            item
            for item in catalog["constructs"]
            if item["activity_id"] == fixture["activity_id"]
        ]
        differing += (
            min(rows, key=lambda item: item["construct_key"])["construct_key"]
            != min(rows, key=source_order_key)["construct_key"]
        )
    assert f"disagree for {differing} of the {len(fixtures)} activities" in text


def test_the_budget_line_matches(text, package):
    budget = package[f"{REPORT_ROOT}/phase9/call_budget.json"]
    provider = budget["provider_call_budget"]
    n3 = budget["n3_adjudicator_budget"]
    semantic = budget["semantic_adjudicator_budget"]
    assert (
        f"semantic {provider['semantic_qualification_side_lowest_rung_only']} at HIGH / "
        f"{provider['semantic_qualification_side_worst_case_all_rungs']} worst case / "
        f"{provider['semantic_held_out_for_one_selected_configuration']} held-out; N3 "
        f"{provider['n3_qualification_side_lowest_rung_only']} at HIGH / "
        f"{provider['n3_qualification_side_worst_case_all_rungs']} worst case / "
        f"{provider['n3_held_out_for_one_selected_configuration']} held-out"
    ) in text
    assert (
        f"semantic first-pass {semantic['first_pass_qualification_side_lowest_rung_only']} "
        f"at HIGH / {semantic['first_pass_qualification_side_worst_case_all_rungs']} worst "
        f"case / {semantic['first_pass_held_out_for_one_selected_configuration']} held-out; "
        f"N3 {n3['first_pass_qualification_side_lowest_rung_only']} / "
        f"{n3['first_pass_qualification_side_worst_case_all_rungs']} / "
        f"{n3['first_pass_held_out_for_one_selected_configuration']}"
    ) in text


def test_the_prompt_authority_matches(text, package):
    fixtures = package[f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json"]
    first = fixtures["fixtures"][0]
    assert f"`{first['prompt_id']}@{first['prompt_version']}`" in text


def test_the_status_and_counters_are_stated(text, package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    assert freeze["stop_condition"] in text
    assert freeze["previous_version_status"] in text
    assert (
        "Provider calls 0, adjudicator calls 0, billable authorizations 0, "
        "credentials resolved 0" in text
    )


def test_the_manifest_equalities_are_stated(raw, package):
    manifest_path = REPOSITORY_ROOT / f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
    if not manifest_path.exists():
        pytest.skip("the v1.3.1 manifest is not built in this working tree")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert f"All {manifest['artifact_count']} entries now carry" in raw
    for name in (
        "candidate_matrix",
        "qualification_protocol",
        "call_budget",
        "n3_axis",
        "pre_results_freeze",
    ):
        assert f"manifest({name}).internal_material_hash" in raw


def test_the_superseded_banner_is_on_the_v130_document(package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    text = V130_DOCUMENT.read_text(encoding="utf-8")
    assert freeze["previous_version_status"] in text
    assert "PHASE9B8A_V131_REPAIR.md" in text
