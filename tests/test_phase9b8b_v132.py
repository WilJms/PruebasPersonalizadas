"""Fail-closed regressions for semantic-benchmark/1.3.2 (Phase 9B.8B).

1.3.2 rebinds the U3 semantic qualification claim to the version it applies to.
Two things therefore have to hold at once: every current statement must name
1.3.2, and everything mechanical -- the scoring set, routes, denominators, bars,
the N3 fixtures and the budget -- must be provably identical to 1.3.1.
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
from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v13 import (  # noqa: E402
    V13BuildError,
)
from comprehension_verification.semantic_benchmark_v13_boundary import (  # noqa: E402
    n3_axis_authority,
    threshold_report_v13,
)
from comprehension_verification.semantic_benchmark_v131 import (  # noqa: E402
    HashManifestError,
    call_budget_v131,
)
from comprehension_verification.semantic_benchmark_v132 import (  # noqa: E402
    CURRENT_CLAIM_FIELDS,
    DEFINITION_ROOT,
    FROZEN_N3_FIXTURE_SET_HASH,
    REPORT_ROOT,
    REPUBLISHED_FROM_V131,
    SELF_MATERIAL_HASH_FIELD,
    SEMANTIC_BENCHMARK_V132_VERSION,
    U3_LIMITATIONS_V132,
    build_v132,
    construct_selection_semantics,
    n3_fixture_equality_proof,
    p06_stage_boundary_v132,
    self_material_hash,
    semantic_qualification_claim_v132,
    stage_boundaries_v132,
    stale_claim_scan,
    v131_stage_change_proof,
    v132_package,
)

V131_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_1"
V131_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_1"
MANIFEST = REPOSITORY_ROOT / f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
_SUPERSEDED = re.compile(r"semantic-benchmark/1\.3\.[01]\b")


@pytest.fixture(scope="module")
def build():
    return build_v132(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v132_package(build)


@pytest.fixture(scope="module")
def fixtures():
    return n3_provider_fixture_authority(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def claim(build):
    return semantic_qualification_claim_v132(build)


def _v131(relative: str) -> dict:
    root = (
        V131_DEFINITION_ROOT
        if relative.startswith("evaluation")
        else V131_REPORT_ROOT
    )
    tail = relative.split("v1_3_2/", 1)[1]
    return json.loads((root / tail).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 1-2. the active claim and limitation name 1.3.2
# --------------------------------------------------------------------------


def test_the_active_claim_names_the_active_version(claim, package):
    expected = (
        f"{SEMANTIC_BENCHMARK_V132_VERSION} qualifies P06 candidate behaviour on "
        "the support statuses SUFFICIENT, PARTIAL and INSUFFICIENT."
    )
    assert claim["claim"] == expected
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    assert protocol["semantic_qualification_claim"] == expected
    boundary = package[f"{REPORT_ROOT}/benchmark_boundary.json"]
    assert boundary["semantic_qualification_claim"] == expected
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    assert freeze["semantic_qualification_claim"] == expected


def test_the_active_uncertain_limitation_names_the_active_version(claim, package):
    expected = (
        f"{SEMANTIC_BENCHMARK_V132_VERSION} does NOT qualify P06 UNCERTAIN behaviour."
    )
    assert claim["limitations"][0] == expected
    assert list(claim["limitations"]) == list(U3_LIMITATIONS_V132)
    for path, field in (
        (f"{DEFINITION_ROOT}/phase9/qualification_protocol.json", "semantic_qualification_limitations"),
        (f"{REPORT_ROOT}/benchmark_boundary.json", "semantic_qualification_limitations"),
        (f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json", "semantic_claim_limitations"),
    ):
        assert package[path][field][0] == expected, path
        assert list(package[path][field]) == list(U3_LIMITATIONS_V132), path
    p06 = package[f"{REPORT_ROOT}/stage_boundaries.json"]["stages"]["P06"]
    assert p06["semantic_qualification_limitations"][0] == expected


def test_the_four_required_limitations_are_all_present(claim):
    joined = " ".join(claim["limitations"])
    assert f"{SEMANTIC_BENCHMARK_V132_VERSION} does NOT qualify P06 UNCERTAIN" in joined
    assert "limited to SUFFICIENT / PARTIAL / INSUFFICIENT" in joined
    assert "UNCERTAIN remains an explicit residual risk" in joined
    assert "Phase 9 alone does not establish full P06 contract coverage" in joined


def test_uncertain_stays_in_the_production_contract(claim):
    assert claim["uncertain_removed_from_production_contract"] is False
    assert claim["production_contract_unchanged"] is True
    assert claim["excluded_support_statuses"] == ["UNCERTAIN"]
    assert claim["uncertain_scoring_property_count"] == 0
    assert claim["phase9_alone_is_full_p06_contract_coverage"] is False


def test_applicability_metadata_is_explicit(claim):
    assert claim["applicable_benchmark_version"] == SEMANTIC_BENCHMARK_V132_VERSION
    assert claim["supersedes_claim_binding_from"] == "semantic-benchmark/1.3.1"
    assert claim["claim_semantics_changed_from_v131"] is False
    assert claim["reader_must_not_infer_applicability_from_lineage"] is True
    versions = {row["benchmark_version"] for row in claim["historical_claim_lineage"]}
    assert versions == {"semantic-benchmark/1.3.0", "semantic-benchmark/1.3.1"}


def test_the_claim_hash_changed_from_v131(claim):
    v131_protocol = json.loads(
        (V131_DEFINITION_ROOT / "phase9/qualification_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    assert claim["claim_hash"] != v131_protocol["semantic_qualification_claim_hash"]


# --------------------------------------------------------------------------
# 3-4. no current v1.3.2 authority names a superseded version
# --------------------------------------------------------------------------


def test_no_current_authority_names_a_superseded_version(package):
    scan = package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"]
    assert scan["violation_count"] == 0
    assert scan["violations"] == []
    covered = set(scan["scanned_artifacts"]) | set(scan["deferred_to_closing_pass"])
    assert covered == set(package), "the scan leaves an artifact uncovered"
    assert scan["closing_pass_rule"]


def test_the_closing_pass_rejects_a_poisoned_freeze(package):
    """The two deferred artifacts are really covered, not merely excused."""

    poisoned = dict(package)
    path = f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
    document = dict(poisoned[path])
    document["semantic_claim_limitations"] = [
        "semantic-benchmark/1.3.1 does NOT qualify P06 UNCERTAIN behaviour."
    ]
    poisoned[path] = document
    with pytest.raises(V13BuildError, match="names a superseded benchmark version"):
        stale_claim_scan(poisoned, republished_unchanged=REPUBLISHED_FROM_V131)


def test_current_claim_fields_never_mention_an_older_version(package):
    for relative, document in package.items():
        if relative in REPUBLISHED_FROM_V131:
            continue
        for field in CURRENT_CLAIM_FIELDS:
            value = document.get(field)
            if value is None:
                continue
            assert not _SUPERSEDED.search(json.dumps(value, ensure_ascii=False)), (
                f"{relative}.{field} names a superseded benchmark version"
            )


def test_a_stale_current_claim_fails_closed(package):
    """Reintroduce the 1.3.1 defect and require the scan to reject it."""

    poisoned = dict(package)
    path = f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"
    document = dict(poisoned[path])
    document["semantic_qualification_claim"] = (
        "semantic-benchmark/1.3.0 qualifies P06 candidate behaviour."
    )
    poisoned[path] = document
    with pytest.raises(V13BuildError, match="names a superseded benchmark version"):
        stale_claim_scan(poisoned, republished_unchanged=REPUBLISHED_FROM_V131)


def test_a_stale_limitation_fails_closed(package):
    poisoned = dict(package)
    path = f"{REPORT_ROOT}/benchmark_boundary.json"
    document = dict(poisoned[path])
    document["semantic_qualification_limitations"] = [
        "semantic-benchmark/1.3.1 does NOT qualify P06 UNCERTAIN behaviour."
    ]
    poisoned[path] = document
    with pytest.raises(V13BuildError, match="names a superseded benchmark version"):
        stale_claim_scan(poisoned, republished_unchanged=REPUBLISHED_FROM_V131)


def test_old_versions_appear_only_in_declared_history(package):
    scan = package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"]
    reasons = {row["reason"] for row in scan["permitted_mentions"]}
    assert reasons <= {
        "HISTORICAL_OR_PROVENANCE_FIELD",
        "CARRIED_FORWARD_STAGE_SUBTREE",
        *{f"REPUBLISHED_UNCHANGED_FROM_{v}" for v in REPUBLISHED_FROM_V131.values()},
    }
    assert scan["permitted_mention_count"] > 0
    assert scan["self_exempt_evidence_fields"]
    assert scan["self_exemption_reason"]


# --------------------------------------------------------------------------
# 5-7. the semantic instrument is byte-identical to 1.3.1
# --------------------------------------------------------------------------


def test_the_semantic_scoring_property_ids_are_unchanged(build):
    v131_boundary = json.loads(
        (V131_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert canonical_hash(list(build.derivation.scoring_property_ids)) == v131_boundary[
        "stages"
    ]["P06"]["candidate_scoring_set_hash"]
    assert len(build.derivation.scoring_property_ids) == 69


def test_the_semantic_routes_are_unchanged(build, package):
    v131_boundary = json.loads(
        (V131_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )["stages"]["P06"]
    v132_boundary = package[f"{REPORT_ROOT}/stage_boundaries.json"]["stages"]["P06"]
    for key in (
        "route_definitions_hash",
        "case_definitions_hash",
        "property_bindings_hash",
        "split_assignments_hash",
        "construct_catalog_hash",
        "coverage_debt_hash",
        "fixture_input_hashes_hash",
        "candidate_scoring_set_hash",
    ):
        assert v132_boundary[key] == v131_boundary[key], key


def test_denominators_and_bars_are_unchanged(build, package):
    thresholds = threshold_report_v13(build)
    rows = {row["split"]: row for row in thresholds["p06_thresholds"]}
    assert rows["CORE"]["applicable_property_count"] == 41
    assert rows["HELD_OUT_CONFIRMATION"]["applicable_property_count"] == 27
    assert rows["SMOKE"]["applicable_property_count"] == 1
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    v131 = _v131(f"{DEFINITION_ROOT}/phase9/qualification_protocol.json")
    assert protocol["semantic_gates"] == v131["semantic_gates"]
    assert protocol["n3_gates"] == v131["n3_gates"]
    assert protocol["ordering"] == v131["ordering"]
    assert protocol["adjudication_protocol_hash"] == v131["adjudication_protocol_hash"]


# --------------------------------------------------------------------------
# 8-12. the N3 material is unchanged
# --------------------------------------------------------------------------


def test_the_n3_fixture_set_hash_is_unchanged(fixtures):
    assert fixtures["fixture_set_hash"] == FROZEN_N3_FIXTURE_SET_HASH


def test_all_ten_provider_request_hashes_are_unchanged(fixtures):
    proof = n3_fixture_equality_proof(fixtures)
    published = json.loads(
        (V131_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    assert proof["fixture_count"] == 10
    assert proof["fixtures_identical_to_v131"] is True
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


def test_the_construct_selections_are_unchanged(fixtures):
    published = json.loads(
        (V131_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        item["n3_provider_fixture_id"]: item["target_construct_key"]
        for item in published["fixtures"]
    }
    actual = {
        item["n3_provider_fixture_id"]: item["target_construct_key"]
        for item in fixtures["fixtures"]
    }
    assert actual == expected


def test_the_n3_split_sequencing_is_unchanged(fixtures):
    proof = n3_fixture_equality_proof(fixtures)
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
        n3_fixture_equality_proof(mutated)


def test_the_provider_and_adjudicator_counts_are_unchanged(build, fixtures, package):
    budget = call_budget_v131(build, fixtures)
    v131 = _v131(f"{REPORT_ROOT}/phase9/call_budget.json")
    assert budget["call_budget_hash"] == v131["call_budget_hash"]
    assert package[f"{REPORT_ROOT}/phase9/call_budget.json"] == v131
    for section in (
        "provider_call_budget",
        "semantic_adjudicator_budget",
        "n3_adjudicator_budget",
    ):
        assert budget[section] == v131[section]


def test_the_call_budget_hash_did_not_change(package):
    budget = package[f"{REPORT_ROOT}/phase9/call_budget.json"]
    v131 = _v131(f"{REPORT_ROOT}/phase9/call_budget.json")
    assert budget["call_budget_hash"] == v131["call_budget_hash"]
    for key in budget:
        assert "claim" not in key and "protocol_boundary" not in key
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    assert protocol["call_budget_hash"] == v131["call_budget_hash"]


# --------------------------------------------------------------------------
# 13-14. boundaries
# --------------------------------------------------------------------------


def test_the_new_claim_hash_changes_the_p06_boundary(build, fixtures, claim):
    n3_axis = n3_axis_authority(build)
    semantics = construct_selection_semantics()
    baseline = p06_stage_boundary_v132(build, n3_axis, fixtures, claim, semantics)[
        "stage_boundary_hash"
    ]
    mutated = dict(claim)
    mutated["claim_hash"] = "sha256:" + "0" * 64
    assert (
        p06_stage_boundary_v132(build, n3_axis, fixtures, mutated, semantics)[
            "stage_boundary_hash"
        ]
        != baseline
    )
    v131 = json.loads(
        (V131_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert baseline != v131["stage_boundary_hashes"]["P06"]


def test_the_selection_semantics_are_bound(build, fixtures, claim):
    n3_axis = n3_axis_authority(build)
    semantics = construct_selection_semantics()
    baseline = p06_stage_boundary_v132(build, n3_axis, fixtures, claim, semantics)[
        "stage_boundary_hash"
    ]
    mutated = dict(semantics)
    mutated["semantics_hash"] = "sha256:" + "1" * 64
    assert (
        p06_stage_boundary_v132(build, n3_axis, fixtures, claim, mutated)[
            "stage_boundary_hash"
        ]
        != baseline
    )
    assert semantics["rule_kind"] == "PRE_REGISTERED_SAMPLING_RULE"
    assert semantics["changes_any_fixture_material"] is False
    assert semantics["changes_the_selected_construct"] is False
    assert semantics["fixture_set_hash_unchanged"] == FROZEN_N3_FIXTURE_SET_HASH


def test_carry_forward_stages_are_proved_unchanged(build, fixtures, claim, package):
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    v131 = json.loads(
        (V131_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert boundaries["new_boundary_stages"] == ["P06"]
    assert boundaries["carried_forward_stages"] == ["P04", "P07", "P09", "PLANNER"]
    for stage in boundaries["carried_forward_stages"]:
        proof = v131_stage_change_proof(build, stage)
        assert proof["stage_local_material_changed"] is False
        assert proof["changed_components"] == []
        assert (
            boundaries["stage_boundary_hashes"][stage]
            == v131["stage_boundary_hashes"][stage]
        )


def test_a_changed_carry_forward_stage_refuses_to_carry_forward(build, monkeypatch):
    from comprehension_verification import semantic_benchmark_v132 as module

    real = module.v131_stage_change_proof

    def _changed(_build, stage):
        proof = dict(real(_build, stage))
        proof["stage_local_material_changed"] = True
        proof["changed_components"] = ["case_definitions_hash"]
        return proof

    monkeypatch.setattr(module, "v131_stage_change_proof", _changed)
    with pytest.raises(V13BuildError, match="needs a new boundary"):
        module.carried_forward_stage_boundary_v132(build, "P07")


# --------------------------------------------------------------------------
# 15. the hash manifest
# --------------------------------------------------------------------------


def _manifest() -> dict:
    if not MANIFEST.exists():
        pytest.skip("the 1.3.2 manifest is not built in this working tree")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.mark.parametrize("relative", sorted(SELF_MATERIAL_HASH_FIELD))
def test_every_manifest_entry_uses_the_document_self_hash(relative, package):
    manifest = _manifest()
    row = next(item for item in manifest["artifacts"] if item["path"] == relative)
    document = package[relative]
    field = SELF_MATERIAL_HASH_FIELD[relative]
    assert row["self_material_hash_field"] == field
    if field is None:
        assert row["internal_material_hash"] is None
        return
    assert row["internal_material_hash"] == document[field]
    assert document[field] == canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )


def test_a_dependency_hash_cannot_masquerade_as_a_self_hash(package):
    path = f"{DEFINITION_ROOT}/phase9/candidate_matrix.json"
    document = dict(package[path])
    dependency = document["benchmark_boundary_hash"]
    assert dependency != document["candidate_matrix_hash"]
    document["candidate_matrix_hash"] = dependency
    with pytest.raises(HashManifestError, match="may never be reported as a self hash"):
        self_material_hash(path, document)


def test_the_registry_matches_the_generated_package(package):
    assert sorted(package) == sorted(SELF_MATERIAL_HASH_FIELD)


def test_the_manifest_excludes_itself_and_flags_republished_entries():
    manifest = _manifest()
    assert manifest["manifest_excludes_itself"] is True
    assert manifest["manifest_self_exclusion_reason"]
    assert not any("freeze_hash_manifest" in i["path"] for i in manifest["artifacts"])
    assert manifest["artifacts_without_a_self_material_hash"] == []
    republished = [i for i in manifest["artifacts"] if i["republished_unchanged_from"]]
    assert len(republished) == len(REPUBLISHED_FROM_V131)
    assert all(
        i["republished_unchanged_from"] == "semantic-benchmark/1.3.1" for i in republished
    )


def test_git_agrees_with_the_recorded_blob_shas():
    manifest = _manifest()
    paths = [item["path"] for item in manifest["artifacts"]]
    result = subprocess.run(
        ["git", "hash-object", *paths],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == [i["git_blob_sha"] for i in manifest["artifacts"]]


# --------------------------------------------------------------------------
# 16-17. immutability, determinism, working directory, local corpus
# --------------------------------------------------------------------------


def test_republished_artifacts_are_byte_identical_to_v131():
    for relative, tail in REPUBLISHED_FROM_V131.items():
        current = REPOSITORY_ROOT / relative
        if not current.exists():
            pytest.skip(f"{relative} is not built in this working tree")
        root = (
            V131_DEFINITION_ROOT
            if relative.startswith("evaluation")
            else V131_REPORT_ROOT
        )
        assert current.read_bytes() == (root / tail).read_bytes(), relative


def test_v131_v130_v12_and_the_corpus_remain_byte_identical():
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


def test_the_lineage_marks_v131_superseded_with_zero_execution(package):
    lineage = package[f"{REPORT_ROOT}/lineage.json"]
    by_version = {item["version"]: item for item in lineage["chain"]}
    v131 = by_version["semantic-benchmark/1.3.1"]
    assert (
        v131["status"]
        == "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
    )
    assert v131["provider_calls"] == 0
    assert v131["adjudicator_calls"] == 0
    assert v131["candidate_outcomes_read"] is False
    assert v131["authorization"] == "NONE"
    assert v131["bytes_modified_by_v132"] is False
    assert by_version["semantic-benchmark/1.3.0"]["bytes_modified_by_v132"] is False
    assert (
        by_version[SEMANTIC_BENCHMARK_V132_VERSION]["status"]
        == "PREEXECUTION_FREEZE_CANDIDATE"
    )
    assert lineage["is_a_corpus_change"] is False
    assert lineage["is_a_semantic_product_decision_change"] is False
    assert lineage["is_a_pre_execution_authority_binding_repair"] is True
    assert lineage["carried_forward_artifact_count"] == len(REPUBLISHED_FROM_V131)


def test_cwd_does_not_change_any_v132_output(package, tmp_path):
    previous = Path.cwd()
    try:
        os.chdir(tmp_path)
        rebuilt = v132_package(build_v132(DEFAULT_CORPUS_ROOT))
    finally:
        os.chdir(previous)
    assert sorted(rebuilt) == sorted(package)
    for relative in package:
        assert canonical_hash(rebuilt[relative]) == canonical_hash(package[relative])


def test_the_local_protected_corpus_copy_changes_nothing(package):
    for document in package.values():
        assert "pruebas_personalizadas_corpus" not in json.dumps(document)
    source = (
        REPOSITORY_ROOT / "src/comprehension_verification/semantic_benchmark_v132.py"
    ).read_text(encoding="utf-8")
    assert "pruebas_personalizadas_corpus" not in source


def test_the_package_is_deterministic_across_two_builds():
    first = v132_package(build_v132(DEFAULT_CORPUS_ROOT))
    second = v132_package(build_v132(DEFAULT_CORPUS_ROOT))
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


def test_every_execution_counter_is_zero(package):
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
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
