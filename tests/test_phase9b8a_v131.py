"""Fail-closed regressions for semantic-benchmark/1.3.1 (Phase 9B.8A).

Two defects are repaired here and each gets a guard that fails rather than
degrades:

* N3 buys its own P06 provider calls, so the exact request behind each of the
  ten exposures is frozen, bound by the P06 stage boundary, and the budget is
  derived from the fixture set rather than from the exposure count;
* the freeze hash manifest names each document's self hash explicitly and
  verifies it, so a dependency hash can never again be reported as one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.contracts import models as m  # noqa: E402
from comprehension_verification.n3_provider_fixtures import (  # noqa: E402
    N3_CONSTRUCT_SELECTION_RULE,
    N3ProviderFixtureError,
    PRODUCTION_REPRESENTATIVENESS_CONDITIONS,
    build_n3_provider_fixtures,
    n3_provider_fixture_authority,
    noisy_disposition_census,
    production_representativeness_proof,
    select_construct,
    selection_independence_proof,
    source_order_key,
)
from comprehension_verification.p06_n3_protocol import (  # noqa: E402
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_SAFETY_SMOKE,
)
from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v13 import V13BuildError  # noqa: E402
from comprehension_verification.semantic_benchmark_v13_boundary import (  # noqa: E402
    n3_axis_authority,
)
from comprehension_verification.semantic_benchmark_v131 import (  # noqa: E402
    DEFINITION_ROOT,
    REPORT_ROOT,
    SELF_MATERIAL_HASH_FIELD,
    HashManifestError,
    build_v131,
    call_budget_v131,
    p06_stage_boundary_v131,
    self_material_hash,
    stage_boundaries_v131,
    v130_stage_change_proof,
    v131_package,
)

V130_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3"
V130_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3"
MANIFEST = REPOSITORY_ROOT / f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"


@pytest.fixture(scope="module")
def build():
    return build_v131(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def fixtures():
    return n3_provider_fixture_authority(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def fixture_build():
    return build_n3_provider_fixtures(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v131_package(build)


@pytest.fixture(scope="module")
def n3_axis(build):
    return n3_axis_authority(build)


# --------------------------------------------------------------------------
# 1-3. the ten fixtures exist, validate, and use only authorized constructs
# --------------------------------------------------------------------------


def test_all_ten_n3_provider_fixtures_exist(fixtures, n3_axis):
    assert fixtures["fixture_count"] == 10
    assert fixtures["safety_smoke_fixture_count"] == 1
    assert fixtures["core_fixture_count"] == 6
    assert fixtures["held_out_fixture_count"] == 3
    assert fixtures["counts_derived_from_the_fixture_set"] is True
    census = n3_axis["census"]
    assert fixtures["fixture_count"] == census["total"]
    assert fixtures["safety_smoke_fixture_count"] == census["N3_SAFETY_SMOKE"]
    assert fixtures["core_fixture_count"] == census["N3_CORE"]
    assert fixtures["held_out_fixture_count"] == census["N3_HELD_OUT_CONFIRMATION"]
    assert len(fixtures["fixture_input_hashes"]) == 10
    assert len(set(fixtures["fixture_input_hashes"].values())) == 10


def test_every_fixture_validates_under_the_real_p06_input_contract(fixture_build):
    for fixture, request in zip(
        fixture_build.fixtures, fixture_build.requests, strict=True
    ):
        payload = request.model_dump(mode="json")
        revalidated = m.EvidenceMapRequest.model_validate(payload)
        assert canonical_hash(revalidated.model_dump(mode="json")) == fixture[
            "provider_request_hash"
        ]


def test_the_representativeness_proof_covers_every_condition(fixture_build):
    proof = production_representativeness_proof(fixture_build, DEFAULT_CORPUS_ROOT)
    assert proof["all_conditions_hold_for_every_fixture"] is True
    assert proof["fixture_count"] == 10
    assert list(proof["conditions"]) == list(PRODUCTION_REPRESENTATIVENESS_CONDITIONS)
    assert len(proof["per_fixture"]) == 10
    for row in proof["per_fixture"]:
        assert row["evidence_units_projected"] == row["evidence_units_in_bundle"]
        assert row["projected_text_is_verbatim_corpus"] is True


def test_no_fixture_uses_an_undeclared_construct(fixtures):
    from comprehension_verification.semantic_benchmark_v12 import build_construct_catalog

    catalog = build_construct_catalog(DEFAULT_CORPUS_ROOT)
    keys = {item["construct_key"] for item in catalog["constructs"]}
    for fixture in fixtures["fixtures"]:
        assert fixture["target_construct_key"] in keys
        assert fixture["construct_source_refs"]
        assert fixture["construct_source_hashes"]
        assert fixture["construct_source_kind"] in {
            "RUBRIC_CRITERION",
            "ASSIGNMENT_REQUIREMENT",
        }


def test_an_activity_without_a_construct_fails_closed():
    with pytest.raises(N3ProviderFixtureError, match="declares no authorized construct"):
        select_construct([], activity_id="act_99_absent")


def test_a_construct_the_source_does_not_order_fails_closed():
    twins = [
        {
            "activity_id": "act_x",
            "construct_key": f"RUBRIC::AX::{name}",
            "source_refs": ["act_x/02_rubric.docx#Criterios[table=0,row=1]"],
            "provenance": {"table_index": 0, "row": 1},
        }
        for name in ("ONE", "TWO")
    ]
    with pytest.raises(N3ProviderFixtureError, match="does not order"):
        select_construct(twins, activity_id="act_x")


# --------------------------------------------------------------------------
# 4-5. selection is outcome-independent; no P04 output is consumed
# --------------------------------------------------------------------------


def test_construct_selection_is_independent_of_noisy_text_and_outcomes():
    proof = selection_independence_proof(DEFAULT_CORPUS_ROOT)
    assert proof["rule"] == N3_CONSTRUCT_SELECTION_RULE
    assert proof["all_forbidden_inputs_are_inert"] is True
    assert all(item["stable"] for item in proof["probes"])
    # and the converse: the rule really does read source order
    assert proof["activities_whose_selection_moves_when_source_order_is_reversed"] > 0
    assert proof["rule_actually_reads_source_order"] is True


def test_selection_reads_only_source_refs_and_provenance():
    from comprehension_verification.semantic_benchmark_v12 import build_construct_catalog

    catalog = build_construct_catalog(DEFAULT_CORPUS_ROOT)
    stripped = [
        {
            "activity_id": item["activity_id"],
            "construct_key": item["construct_key"],
            "source_refs": item["source_refs"],
            "provenance": item["provenance"],
        }
        for item in catalog["constructs"]
    ]
    for activity in sorted({item["activity_id"] for item in catalog["constructs"]}):
        assert (
            select_construct(stripped, activity_id=activity)["construct_key"]
            == select_construct(catalog["constructs"], activity_id=activity)[
                "construct_key"
            ]
        ), "selection changed when every non-source field was removed"


def test_selection_is_not_the_lexical_first_construct():
    """The rule must be source order, not an alphabetical accident."""

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
        lexical = min(rows, key=lambda item: item["construct_key"])["construct_key"]
        by_source = min(rows, key=source_order_key)["construct_key"]
        assert fixture["target_construct_key"] == by_source
        differing += lexical != by_source
    assert differing > 0, (
        "source order never differs from lexical order, so the rule would be "
        "indistinguishable from the arbitrary one it replaced"
    )


def test_no_fixture_consumes_a_p04_candidate_output(fixtures, fixture_build):
    for fixture, request in zip(fixtures["fixtures"], fixture_build.requests, strict=True):
        assert fixture["consumes_p04_candidate_output"] is False
        payload = request.model_dump(mode="json")
        assert payload["blueprint"]["activity_id"] == fixture["activity_id"]
        serialized = json.dumps(payload, ensure_ascii=False)
        for marker in ("p04_candidate", "candidate_blueprint", "p04_output", "PP-A"):
            assert marker not in serialized


def test_no_fixture_carries_a_golden_or_an_outcome(fixtures):
    for fixture in fixtures["fixtures"]:
        assert fixture["expected_semantic_answer"] is None
        assert fixture["expected_support_status"] is None
        assert fixture["oracle_property_id"] is None
        assert fixture["candidate_outcome"] is None
        assert fixture["requires_semantic_golden"] is False
        assert fixture["expected_candidate_family"] == "gpt-5.6-luna"


# --------------------------------------------------------------------------
# 6-9. the boundary moves with the fixtures; missing/changed fixtures block
# --------------------------------------------------------------------------


def test_a_fixture_set_change_changes_the_p06_boundary(build, n3_axis, fixtures):
    baseline = p06_stage_boundary_v131(build, n3_axis, fixtures)["stage_boundary_hash"]
    for key in (
        "fixture_set_hash",
        "construct_selection_independence_hash",
        "production_representativeness_hash",
        "request_construction_source_hash",
        "fixture_builder_source_hash",
        "noisy_disposition_census_hash",
    ):
        mutated = dict(fixtures)
        mutated[key] = "sha256:" + "0" * 64
        assert (
            p06_stage_boundary_v131(build, n3_axis, mutated)["stage_boundary_hash"]
            != baseline
        ), f"the P06 boundary ignored a change to {key}"


def test_a_changed_per_fixture_input_hash_changes_the_p06_boundary(
    build, n3_axis, fixtures
):
    baseline = p06_stage_boundary_v131(build, n3_axis, fixtures)["stage_boundary_hash"]
    mutated = json.loads(json.dumps(fixtures))
    first = sorted(mutated["fixture_input_hashes"])[0]
    mutated["fixture_input_hashes"][first] = "sha256:" + "1" * 64
    assert (
        p06_stage_boundary_v131(build, n3_axis, mutated)["stage_boundary_hash"]
        != baseline
    )


def test_a_missing_fixture_blocks_the_freeze(build, n3_axis, fixtures):
    mutated = json.loads(json.dumps(fixtures))
    dropped = mutated["fixtures"].pop()
    mutated["fixture_input_hashes"].pop(dropped["n3_provider_fixture_id"])
    mutated["fixture_count"] = len(mutated["fixtures"])
    budget = call_budget_v131(build, mutated)
    assert budget["n3_provider_fixture_count"] == 9
    assert budget["n3_fixture_count_equals_exposure_count"] is False
    assert sum(budget["n3_fixture_counts_by_split"].values()) == 9


def test_a_fixture_set_that_does_not_cover_the_population_fails_closed(monkeypatch):
    from comprehension_verification import n3_provider_fixtures as module

    real = module.build_n3_provider_fixtures

    def _short(corpus_root=DEFAULT_CORPUS_ROOT):
        full = real(corpus_root)
        return module.N3FixtureBuild(
            fixtures=full.fixtures[:-1],
            requests=full.requests[:-1],
            envelopes=full.envelopes[:-1],
            population=full.population,
            stage_plan=full.stage_plan,
        )

    monkeypatch.setattr(module, "build_n3_provider_fixtures", _short)
    with pytest.raises(N3ProviderFixtureError, match="does not cover"):
        module.n3_provider_fixture_authority(DEFAULT_CORPUS_ROOT)


def test_the_p06_boundary_is_new_and_supersedes_the_v130_one(build, n3_axis, fixtures):
    boundary = p06_stage_boundary_v131(build, n3_axis, fixtures)
    published = json.loads(
        (V130_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert boundary["boundary_status"] == "NEW_IN_V131"
    assert boundary["stage_boundary_hash"] != published["stage_boundary_hashes"]["P06"]
    assert boundary["supersedes_v130_p06_boundary"] == published[
        "stage_boundary_hashes"
    ]["P06"]
    assert boundary["n3_provider_authority_fully_bound"] is True


def test_the_global_boundary_and_freeze_bind_the_fixture_set(package, fixtures):
    global_boundary = package[f"{REPORT_ROOT}/benchmark_boundary.json"]
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    assert global_boundary["n3_provider_fixture_set_hash"] == fixtures["fixture_set_hash"]
    assert freeze["n3_provider_fixture_set_hash"] == fixtures["fixture_set_hash"]
    assert freeze["n3_provider_fixture_input_hashes"] == dict(
        sorted(fixtures["fixture_input_hashes"].items())
    )
    assert protocol["n3_provider_call_authority"]["fixture_set_hash"] == fixtures[
        "fixture_set_hash"
    ]


# --------------------------------------------------------------------------
# 7. budgets are derived from the fixture count
# --------------------------------------------------------------------------


def test_provider_call_counts_are_derived_from_the_fixture_count(build, fixtures):
    budget = call_budget_v131(build, fixtures)
    k = budget["k"]
    counts = budget["n3_fixture_counts_by_split"]
    rows = [
        row
        for row in budget["provider_call_budget"]["rows"]
        if row["axis"] == "CONTRACTUAL_HARD_SAFETY"
    ]
    assert rows, "the budget allocates no N3 provider calls"
    for row in rows:
        assert row["volume_source"] == "EXECUTABLE_FROZEN_N3_PROVIDER_FIXTURE_COUNT"
        assert row["unit"] == "PROVIDER_FIXTURE_RUN"
        assert row["units"] == counts[row["split"]]
        assert row["calls_if_this_rung_executes"] == counts[row["split"]] * k
    for split, expected in (
        (N3_SAFETY_SMOKE, 1),
        (N3_CORE, 6),
        (N3_HELD_OUT_CONFIRMATION, 3),
    ):
        assert counts[split] == expected


def test_provider_and_adjudicator_budgets_stay_separate(build, fixtures):
    budget = call_budget_v131(build, fixtures)
    assert set(budget) >= {
        "provider_call_budget",
        "semantic_adjudicator_budget",
        "n3_adjudicator_budget",
    }
    assert budget["calls_performed_by_this_task"] == 0
    assert budget["authorization"] == "NONE"
    assert budget["pricing_refreshed"] is False
    assert (
        budget["n3_provider_calls_are_additional"]["n3_rides_existing_semantic_calls"]
        is False
    )


# --------------------------------------------------------------------------
# 10-13. the hash manifest
# --------------------------------------------------------------------------


def _manifest() -> dict:
    if not MANIFEST.exists():
        pytest.skip("the v1.3.1 manifest is not built in this working tree")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "relative",
    sorted(SELF_MATERIAL_HASH_FIELD),
)
def test_every_manifest_entry_uses_the_document_self_hash(relative, package):
    manifest = _manifest()
    row = next(item for item in manifest["artifacts"] if item["path"] == relative)
    document = package[relative]
    field = SELF_MATERIAL_HASH_FIELD[relative]
    assert row["self_material_hash_field"] == field
    if field is None:
        assert row["internal_material_hash"] is None
        assert row["has_self_material_hash"] is False
        return
    assert row["internal_material_hash"] == document[field]
    # and the value really is a self hash, not something copied in
    assert document[field] == canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )


def test_the_named_blockers_are_repaired(package):
    manifest = _manifest()
    rows = {item["path"]: item for item in manifest["artifacts"]}
    pairs = (
        (f"{DEFINITION_ROOT}/phase9/candidate_matrix.json", "candidate_matrix_hash"),
        (
            f"{DEFINITION_ROOT}/phase9/qualification_protocol.json",
            "protocol_boundary_hash",
        ),
        (f"{REPORT_ROOT}/phase9/call_budget.json", "call_budget_hash"),
        (
            f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json",
            "n3_axis_hash",
        ),
        (
            f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json",
            "freeze_material_hash",
        ),
    )
    for path, field in pairs:
        assert rows[path]["internal_material_hash"] == package[path][field], path


def test_a_dependency_hash_cannot_masquerade_as_a_self_hash(package):
    """The v1.3.0 defect, reproduced against the repaired checker."""

    path = f"{DEFINITION_ROOT}/phase9/candidate_matrix.json"
    document = dict(package[path])
    dependency = document["benchmark_boundary_hash"]
    assert dependency != document["candidate_matrix_hash"]
    document["candidate_matrix_hash"] = dependency
    with pytest.raises(HashManifestError, match="may never be reported as a self hash"):
        self_material_hash(path, document)


def test_an_unregistered_artifact_fails_closed():
    with pytest.raises(HashManifestError, match="no entry in SELF_MATERIAL_HASH_FIELD"):
        self_material_hash("reports/semantic_benchmark/v1_3_1/invented.json", {"a": 1})


def test_the_registry_matches_the_generated_package(package):
    assert sorted(package) == sorted(SELF_MATERIAL_HASH_FIELD)


def test_the_manifest_documents_its_own_exclusion():
    manifest = _manifest()
    assert manifest["manifest_excludes_itself"] is True
    assert manifest["manifest_self_exclusion_reason"]
    assert not any(
        "freeze_hash_manifest" in item["path"] for item in manifest["artifacts"]
    )
    assert manifest["artifacts_without_a_self_material_hash"] == []


def test_the_manifest_keeps_the_three_hash_kinds_apart():
    manifest = _manifest()
    assert set(manifest["hash_kinds"]) == {
        "INTERNAL_MATERIAL_HASH",
        "FILE_SHA256",
        "GIT_BLOB_SHA",
    }
    for item in manifest["artifacts"]:
        assert item["file_sha256"].startswith("sha256:")
        assert len(item["git_blob_sha"]) == 40
        assert item["git_blob_sha"] != item["file_sha256"]
        assert item["internal_material_hash"] != item["file_sha256"]


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
    computed = result.stdout.split()
    assert computed == [item["git_blob_sha"] for item in manifest["artifacts"]]


# --------------------------------------------------------------------------
# 14. the 4/6 counts are machine-derived
# --------------------------------------------------------------------------


def test_the_noisy_disposition_counts_are_derived_and_partition_exactly():
    census = noisy_disposition_census(DEFAULT_CORPUS_ROOT)
    assert census["derived_not_asserted"] is True
    assert census["noisy_exposure_count"] == 10
    assert census["noisy_with_executable_semantic_route_count"] == 0
    assert census["noisy_with_p06_property_but_excluded_count"] == 4
    assert census["noisy_with_no_p06_property_count"] == 6
    assert (
        census["noisy_with_executable_semantic_route_count"]
        + census["noisy_with_p06_property_but_excluded_count"]
        + census["noisy_with_no_p06_property_count"]
        == census["noisy_exposure_count"]
    )
    assert len(census["rows"]) == census["noisy_exposure_count"]


def test_the_noisy_prose_is_generated_from_the_counts():
    census = noisy_disposition_census(DEFAULT_CORPUS_ROOT)
    prose = census["prose"]
    for value in (
        census["noisy_exposure_count"],
        census["noisy_with_p06_property_but_excluded_count"],
        census["noisy_with_no_p06_property_count"],
    ):
        assert str(value) in prose
    from comprehension_verification.n3_provider_fixtures import noisy_disposition_prose

    assert prose == noisy_disposition_prose(census)


def test_the_budget_carries_the_derived_counts_not_a_literal(build, fixtures):
    budget = call_budget_v131(build, fixtures)
    finding = budget["n3_provider_calls_are_additional"]
    census = noisy_disposition_census(DEFAULT_CORPUS_ROOT)
    assert finding["noisy_disposition_census_hash"] == census["census_hash"]
    assert finding["finding"] == census["prose"]


# --------------------------------------------------------------------------
# 15-17. immutability, working directory, local corpus
# --------------------------------------------------------------------------


def test_v130_v12_and_the_corpus_remain_byte_identical():
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
            "evaluation/corpora/pruebas_personalizadas/v1",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", (
        "v1.2, v1.3.0 and the canonical corpus must be byte-identical: "
        f"{result.stdout}"
    )


def test_the_lineage_marks_v130_superseded_with_zero_execution(package):
    lineage = package[f"{REPORT_ROOT}/lineage.json"]
    by_version = {item["version"]: item for item in lineage["chain"]}
    v130 = by_version["semantic-benchmark/1.3.0"]
    assert v130["status"] == "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
    assert v130["provider_calls"] == 0
    assert v130["adjudicator_calls"] == 0
    assert v130["candidate_outcomes_read"] is False
    assert v130["bytes_modified_by_v131"] is False
    v131 = by_version["semantic-benchmark/1.3.1"]
    assert v131["status"] == "PREEXECUTION_FREEZE_CANDIDATE"
    assert lineage["is_a_corpus_change"] is False
    assert lineage["is_a_semantic_product_decision_change"] is False
    assert lineage["is_a_pre_execution_instrumentation_repair"] is True


def test_carry_forward_stages_are_proved_unchanged(build, n3_axis, fixtures):
    boundaries = stage_boundaries_v131(build, n3_axis, fixtures)
    published = json.loads(
        (V130_REPORT_ROOT / "stage_boundaries.json").read_text(encoding="utf-8")
    )
    assert boundaries["new_boundary_stages"] == ["P06"]
    assert boundaries["carried_forward_stages"] == ["P04", "P07", "P09", "PLANNER"]
    for stage in boundaries["carried_forward_stages"]:
        proof = v130_stage_change_proof(build, stage)
        assert proof["stage_local_material_changed"] is False
        assert proof["changed_components"] == []
        assert (
            boundaries["stage_boundary_hashes"][stage]
            == published["stage_boundary_hashes"][stage]
        )


def test_a_changed_carry_forward_stage_refuses_to_carry_forward(build, monkeypatch):
    from comprehension_verification import semantic_benchmark_v131 as module

    real = module.v130_stage_change_proof

    def _changed(_build, stage):
        proof = dict(real(_build, stage))
        proof["stage_local_material_changed"] = True
        proof["changed_components"] = ["case_definitions_hash"]
        return proof

    monkeypatch.setattr(module, "v130_stage_change_proof", _changed)
    with pytest.raises(V13BuildError, match="needs a new boundary"):
        module.carried_forward_stage_boundary_v131(build, "P07")


def test_cwd_does_not_change_any_v131_output(package, tmp_path):
    previous = Path.cwd()
    try:
        os.chdir(tmp_path)
        rebuilt = v131_package(build_v131(DEFAULT_CORPUS_ROOT))
    finally:
        os.chdir(previous)
    assert sorted(rebuilt) == sorted(package)
    for relative in package:
        assert canonical_hash(rebuilt[relative]) == canonical_hash(
            package[relative]
        ), relative


def test_the_local_protected_corpus_copy_changes_nothing(package):
    local = REPOSITORY_ROOT / "pruebas_personalizadas_corpus"
    for document in package.values():
        assert "pruebas_personalizadas_corpus" not in json.dumps(document)
    source = (
        REPOSITORY_ROOT / "src/comprehension_verification/n3_provider_fixtures.py"
    ).read_text(encoding="utf-8")
    assert "pruebas_personalizadas_corpus" not in source
    if local.exists():
        rebuilt = v131_package(build_v131(DEFAULT_CORPUS_ROOT))
        for relative in package:
            assert canonical_hash(rebuilt[relative]) == canonical_hash(package[relative])


def test_the_package_is_deterministic_across_two_builds():
    first = v131_package(build_v131(DEFAULT_CORPUS_ROOT))
    second = v131_package(build_v131(DEFAULT_CORPUS_ROOT))
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


def test_every_execution_counter_is_zero(package, fixtures):
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
    assert fixtures["provider_calls"] == 0
    assert fixtures["adjudicator_calls"] == 0


def test_the_semantic_axis_is_untouched_by_the_repair(package):
    protocol = package[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    v130 = json.loads(
        (V130_DEFINITION_ROOT / "phase9/qualification_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["semantic_gates"] == v130["semantic_gates"]
    assert protocol["n3_gates"] == v130["n3_gates"]
    assert protocol["ordering"] == v130["ordering"]
    assert protocol["semantic_qualification_limitations"] == v130[
        "semantic_qualification_limitations"
    ]
    assert protocol["adjudication_protocol_hash"] == v130["adjudication_protocol_hash"]
    matrix = package[f"{DEFINITION_ROOT}/phase9/candidate_matrix.json"]
    v130_matrix = json.loads(
        (V130_DEFINITION_ROOT / "phase9/candidate_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    assert matrix["candidates"] == v130_matrix["candidates"]
    assert matrix["candidate_matrix_hash"] != v130_matrix["candidate_matrix_hash"]
