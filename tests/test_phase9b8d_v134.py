"""Offline freeze regressions for semantic-benchmark/1.3.4 (Phase 9B.8D)."""

from __future__ import annotations

from hashlib import sha1, sha256
import json
import os
from pathlib import Path

import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.p06_n3_protocol import (
    N3_ADJUDICATION_COLLECTION_REQUIREMENTS,
    N3_ADJUDICATION_POPULATION_CONTRACT,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_SAFETY_SMOKE,
    N3_SAFETY_VERDICTS,
)
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT
from comprehension_verification.semantic_benchmark_v134 import (
    DEFINITION_ROOT,
    REPORT_ROOT,
    REPUBLISHED_FROM_V133,
    SELF_MATERIAL_HASH_FIELD,
    SEMANTIC_BENCHMARK_V134_VERSION,
    V133_DEFINITION_ROOT,
    V133_REPORT_ROOT,
    build_v134,
    self_material_hash,
    v134_package,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build():
    return build_v134(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v134_package(build)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v134_preserves_the_canonical_corpus_and_semantic_census(build) -> None:
    assert build.package_hash == (
        "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1"
    )
    assert len(build.derivation.routes) == 71
    assert len(build.derivation.scoring_property_ids) == 69


def test_n3_axis_binds_the_single_exact_collection_contract(package) -> None:
    axis = package[
        f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json"
    ]
    validation = axis["adjudication_population_validation"]
    assert validation["contract"] == N3_ADJUDICATION_POPULATION_CONTRACT
    assert validation["requirements"] == list(N3_ADJUDICATION_COLLECTION_REQUIREMENTS)
    assert validation["closed_verdict_vocabulary"] == list(N3_SAFETY_VERDICTS)
    assert validation["validation_precedes_clearance_promotion_or_qualification"]
    assert validation["malformed_collection_consequence"] == "RAISE_N3_PROTOCOL_ERROR"


def test_n3_source_and_axis_hashes_move_without_moving_population(package) -> None:
    axis = package[
        f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json"
    ]
    old = _json(
        V133_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    )
    source = REPO_ROOT / "src/comprehension_verification/p06_n3_protocol.py"
    assert axis["protocol_source_hash"] == f"sha256:{sha256(source.read_bytes()).hexdigest()}"
    assert axis["protocol_source_hash"] != old["protocol_source_hash"]
    assert axis["n3_axis_hash"] != old["n3_axis_hash"]
    assert axis["exposure_population"] == old["exposure_population"]
    assert axis["selectors"] == old["selectors"]
    assert axis["stage_plan"] == old["stage_plan"]
    assert axis["census"] == old["census"]


def test_protocol_binds_exact_ids_for_all_three_n3_stages(package) -> None:
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    expected = protocol["n3_expected_exposure_ids_by_stage"]
    assert set(expected) == {
        N3_SAFETY_SMOKE,
        N3_CORE,
        N3_HELD_OUT_CONFIRMATION,
    }
    assert {stage: len(ids) for stage, ids in expected.items()} == {
        N3_SAFETY_SMOKE: 1,
        N3_CORE: 6,
        N3_HELD_OUT_CONFIRMATION: 3,
    }
    assert protocol["n3_gates"]["closed_verdict_vocabulary"] == list(
        N3_SAFETY_VERDICTS
    )
    assert protocol["n3_gates"]["exactly_one_row_per_expected_stage_exposure"]


def test_only_p06_gets_a_new_stage_boundary(package) -> None:
    current = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    previous = _json(V133_REPORT_ROOT / "stage_boundaries.json")
    assert current["new_boundary_stages"] == ["P06"]
    assert current["stage_boundary_hashes"]["P06"] != previous[
        "stage_boundary_hashes"
    ]["P06"]
    for stage in ("P04", "P07", "P09", "PLANNER"):
        assert current["stage_boundary_hashes"][stage] == previous[
            "stage_boundary_hashes"
        ][stage]
        assert current["stages"][stage]["boundary_status"] == (
            "CARRIED_FORWARD_FROM_V133"
        )


def test_global_protocol_and_matrix_hashes_move_transitively(package) -> None:
    boundary = package[f"{REPORT_ROOT}/benchmark_boundary.json"]
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    matrix = package[f"{DEFINITION_ROOT}/phase9/candidate_matrix.json"]
    old_boundary = _json(V133_REPORT_ROOT / "benchmark_boundary.json")
    old_protocol = _json(V133_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    old_matrix = _json(V133_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    assert boundary["benchmark_boundary_hash"] != old_boundary[
        "benchmark_boundary_hash"
    ]
    assert protocol["protocol_boundary_hash"] != old_protocol[
        "protocol_boundary_hash"
    ]
    assert matrix["candidate_matrix_hash"] != old_matrix["candidate_matrix_hash"]
    assert matrix["candidates"] == old_matrix["candidates"]


@pytest.mark.parametrize("relative", sorted(REPUBLISHED_FROM_V133))
def test_declared_carry_forward_is_byte_identical(relative, package) -> None:
    source = (
        V133_DEFINITION_ROOT
        if relative.startswith(DEFINITION_ROOT)
        else V133_REPORT_ROOT
    ) / REPUBLISHED_FROM_V133[relative][1]
    generated = (
        json.dumps(package[relative], indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    assert generated == source.read_bytes()


def test_carry_forward_proof_distinguishes_equal_and_changed_material(package) -> None:
    proof = package[
        f"{REPORT_ROOT}/phase9/semantic_carry_forward_equality_proof.json"
    ]
    assert proof["all_required_equalities_hold"] is True
    assert proof["carried_forward_artifact_count"] == len(REPUBLISHED_FROM_V133)
    assert "N3 axis hash" in proof["changed_components"]
    assert "provider fixture inputs and call budget" in proof["unchanged_semantics"]


def test_lineage_preserves_and_supersedes_v133_for_the_two_defects(package) -> None:
    lineage = package[f"{REPORT_ROOT}/lineage.json"]
    by_version = {row["version"]: row for row in lineage["chain"]}
    v133 = by_version["semantic-benchmark/1.3.3"]
    assert v133["status"] == (
        "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
    )
    assert len(v133["superseded_because"]) == 2
    assert v133["bytes_modified_by_v134"] is False
    assert lineage["v133_preserved_as_historical_evidence"] is True
    assert lineage["no_provider_or_adjudicator_outcome_informed_the_repair"] is True


def test_freeze_carries_zero_execution_counters(package) -> None:
    freeze = package[
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
    ]
    assert freeze["benchmark_version"] == SEMANTIC_BENCHMARK_V134_VERSION
    counters = freeze["execution_counters"]
    assert counters == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credentials_resolved": 0,
        "real_transport_constructed": False,
        "pricing_refreshed": False,
        "high_smoke_authorized": False,
        "billable_authorizations": 0,
        "spend_authorized": False,
        "candidate_outcomes_read": False,
        "authorization": "NONE",
    }
    assert freeze["corpus_bytes_modified"] is False
    assert freeze["qualification_run"] is False


def test_every_artifact_has_an_explicit_verified_self_hash(package) -> None:
    assert set(package) == set(SELF_MATERIAL_HASH_FIELD)
    for relative, document in package.items():
        assert self_material_hash(relative, document) == document[
            SELF_MATERIAL_HASH_FIELD[relative]
        ]


def test_published_package_matches_a_fresh_build(package) -> None:
    for relative, document in package.items():
        path = REPO_ROOT / relative
        assert path.exists(), relative
        assert _json(path) == document, relative


def test_manifest_reports_all_three_hash_kinds(package) -> None:
    manifest = _json(
        REPO_ROOT / REPORT_ROOT / "phase9/freeze_hash_manifest.json"
    )
    assert set(manifest["hash_kinds"]) == {
        "INTERNAL_MATERIAL_HASH",
        "FILE_SHA256",
        "GIT_BLOB_SHA",
    }
    freeze_relative = f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
    row = next(item for item in manifest["artifacts"] if item["path"] == freeze_relative)
    data = (REPO_ROOT / freeze_relative).read_bytes()
    assert row["internal_material_hash"] == package[freeze_relative][
        "freeze_material_hash"
    ]
    assert row["file_sha256"] == f"sha256:{sha256(data).hexdigest()}"
    assert row["git_blob_sha"] == sha1(b"blob %d\0" % len(data) + data).hexdigest()
    assert len({row["internal_material_hash"], row["file_sha256"], row["git_blob_sha"]}) == 3


def test_scans_are_clean(package) -> None:
    stale = package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"]
    decision = package[f"{REPORT_ROOT}/phase9/product_decision_state_scan.json"]
    assert stale["violation_count"] == 0
    assert decision["violation_count"] == 0


def test_build_is_deterministic_and_cwd_independent(build, tmp_path) -> None:
    first = v134_package(build)
    old = Path.cwd()
    try:
        os.chdir(tmp_path)
        second = v134_package(build_v134(DEFAULT_CORPUS_ROOT))
    finally:
        os.chdir(old)
    assert canonical_hash(first) == canonical_hash(second)
