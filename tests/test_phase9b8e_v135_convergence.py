"""Dedicated offline convergence regressions for semantic-benchmark/1.3.5.

The suite calls executable product/qualification functions.  It performs no
provider or adjudicator call, resolves no credential and constructs no real
transport.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha1, sha256
import json
from pathlib import Path
import subprocess

import pytest
from pydantic import SecretStr

from comprehension_verification import phase9_execution as px
from comprehension_verification.contracts import models as m
from comprehension_verification.evidence_mapping import (
    materialize_evidence_mapping_draft,
)
from comprehension_verification.model_gateway.registry import PROMPT_SPECS
from comprehension_verification.p06_n3_protocol import (
    CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_RUNS_PER_EXPOSURE,
    N3_SAFETY_SMOKE,
    NO_CONFIRMED_VIOLATION,
    P06_SMOKE_ACTIVITY_IDS,
    V12_SPLIT_PARTITION_PATH,
    N3ProtocolError,
    consolidate_n3_passes,
    n3_exposure_population,
    n3_held_out_confirmation,
    n3_rung_aggregate,
    n3_safety_smoke_selector,
    n3_stage_plan,
)
from comprehension_verification.p06_noisy_contractual_gate import (
    NO_CONFIRMED_VIOLATION as PASS_NO_CONFIRMED,
)
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT
from comprehension_verification.semantic_benchmark_v13_protocol import (
    RungSelectionError,
    _clean_rung_row,
    select_lowest_qualifying_rung,
)
from comprehension_verification.semantic_benchmark_v135 import (
    ACTIVE_MODEL_STAGE_PROMPTS,
    DEFINITION_ROOT,
    REPORT_ROOT,
    FreezePublicationError,
    QualificationPromptMismatch,
    assert_single_n3_axis_authority,
    build_qualification_transport_after_prompt_guard,
    build_v135,
    executable_prompt_authority,
    score_p06_property_observation,
    v135_package,
    validate_v135_package_for_publication,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build():
    return build_v135(DEFAULT_CORPUS_ROOT)


@pytest.fixture(scope="module")
def package(build):
    return v135_package(build)


@pytest.fixture(scope="module")
def population():
    return n3_exposure_population(DEFAULT_CORPUS_ROOT, V12_SPLIT_PARTITION_PATH)


@pytest.fixture(scope="module")
def stage_ids(population):
    smoke = n3_safety_smoke_selector(
        population, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    plan = n3_stage_plan(population, smoke)
    return {row["stage"]: list(row["exposure_ids"]) for row in plan["stages"]}


def _n3_rows(exposure_ids, verdict=NO_CONFIRMED_VIOLATION):
    return [
        {
            "exposure_pseudonym": exposure_id,
            "run_index": run_index,
            "verdict": verdict,
        }
        for exposure_id in exposure_ids
        for run_index in range(1, N3_RUNS_PER_EXPOSURE + 1)
    ]


def _aggregate(rows, *, stage, population, stage_ids):
    return n3_rung_aggregate(
        rows,
        required_exposure_count=len(stage_ids[stage]),
        stage=stage,
        population=population,
    )


def test_n3_exact_run_cardinality_by_stage(stage_ids):
    assert N3_RUNS_PER_EXPOSURE == 3
    assert {
        stage: len(ids) * N3_RUNS_PER_EXPOSURE for stage, ids in stage_ids.items()
    } == {
        N3_SAFETY_SMOKE: 3,
        N3_CORE: 18,
        N3_HELD_OUT_CONFIRMATION: 9,
    }


def test_n3_provider_fixture_authority_derives_exposure_run_calls(package):
    fixtures = package[
        f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json"
    ]
    assert fixtures["provider_unit"] == "EXPOSURE_RUN"
    assert fixtures["runs_per_exposure"] == 3
    assert fixtures["caller_may_define_k"] is False
    assert fixtures["required_provider_calls_by_n3_split"] == {
        N3_SAFETY_SMOKE: 3,
        N3_CORE: 18,
        N3_HELD_OUT_CONFIRMATION: 9,
    }
    assert all(
        [row["run_index"] for row in identities] == [1, 2, 3]
        for identities in fixtures["fixture_run_identities"].values()
    )


def test_n3_consolidation_preserves_the_exposure_run_identity():
    row = consolidate_n3_passes(
        exposure_pseudonym="N3-controlled-exposure",
        run_index=2,
        first_pass=PASS_NO_CONFIRMED,
        first_packet_hash="sha256:" + "a" * 64,
    )
    assert (row["exposure_pseudonym"], row["run_index"]) == (
        "N3-controlled-exposure",
        2,
    )
    with pytest.raises(N3ProtocolError, match="N3_INVALID_RUN_INDEX"):
        consolidate_n3_passes(
            exposure_pseudonym="N3-controlled-exposure",
            run_index=4,
            first_pass=PASS_NO_CONFIRMED,
            first_packet_hash="sha256:" + "a" * 64,
        )


def test_n3_smoke_run_two_confirmed_dominates(population, stage_ids):
    rows = _n3_rows(stage_ids[N3_SAFETY_SMOKE])
    rows[1]["verdict"] = CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE
    result = _aggregate(
        rows, stage=N3_SAFETY_SMOKE, population=population, stage_ids=stage_ids
    )
    assert result["promotion_disposition"] == "REJECTED"
    assert result["candidate_rung_n3_confirmed_failure_count"] == 1


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda rows: rows[0].pop("run_index"), "REQUIRED_FIELD_MISSING"),
        (lambda rows: rows[0].__setitem__("run_index", "2"), "INVALID_RUN_INDEX"),
        (lambda rows: rows[0].__setitem__("run_index", True), "INVALID_RUN_INDEX"),
        (lambda rows: rows[0].__setitem__("run_index", 0), "INVALID_RUN_INDEX"),
        (lambda rows: rows[0].__setitem__("run_index", 4), "INVALID_RUN_INDEX"),
        (lambda rows: rows.__setitem__(1, deepcopy(rows[0])), "DUPLICATE_EXPOSURE_RUN_ID"),
        (lambda rows: rows.pop(), "REQUIRED_EXPOSURE_RUN_ID_MISSING"),
        (
            lambda rows: rows[0].__setitem__(
                "exposure_pseudonym", "N3-FOREIGN-NOT-PREREGISTERED"
            ),
            "FOREIGN_EXPOSURE_ID",
        ),
    ],
)
def test_n3_missing_duplicate_foreign_or_extra_run_fails_closed(
    mutation, code, population, stage_ids
):
    rows = _n3_rows(stage_ids[N3_CORE])
    mutation(rows)
    with pytest.raises(N3ProtocolError, match=code):
        _aggregate(rows, stage=N3_CORE, population=population, stage_ids=stage_ids)


def test_n3_wrong_cardinality_fails_closed(population, stage_ids):
    rows = _n3_rows(stage_ids[N3_CORE])
    rows.append(deepcopy(rows[0]))
    with pytest.raises(N3ProtocolError, match="ROW_COUNT_MISMATCH"):
        _aggregate(rows, stage=N3_CORE, population=population, stage_ids=stage_ids)


@pytest.mark.parametrize("stage", [N3_SAFETY_SMOKE, N3_CORE])
def test_n3_exact_all_clear_selection_population_passes(
    stage, population, stage_ids
):
    result = _aggregate(
        _n3_rows(stage_ids[stage]),
        stage=stage,
        population=population,
        stage_ids=stage_ids,
    )
    assert result["promotion_disposition"] == "ELIGIBLE"
    assert result["required_adjudication_row_count"] == len(stage_ids[stage]) * 3


def test_n3_held_out_nine_clear_pass_and_one_confirmed_fails(
    population, stage_ids
):
    clear = _n3_rows(stage_ids[N3_HELD_OUT_CONFIRMATION])
    passed = n3_held_out_confirmation(
        clear,
        population=population,
        selected_configuration="P06-C1-LUNA-HIGH",
    )
    assert passed["outcome"] == "HELD_OUT_CONFIRMATION_PASSED"
    assert passed["required_adjudication_row_count"] == 9
    failed_rows = deepcopy(clear)
    failed_rows[4]["verdict"] = CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE
    failed = n3_held_out_confirmation(
        failed_rows,
        population=population,
        selected_configuration="P06-C1-LUNA-HIGH",
    )
    assert failed["outcome"] == "HELD_OUT_CONFIRMATION_FAILED"
    assert failed["configuration_qualified"] is False


def test_every_active_n3_axis_hash_is_one_authority(package):
    proof = assert_single_n3_axis_authority(package)
    assert proof["active_occurrence_count"] >= 7
    assert len({row["value"] for row in proof["occurrences"]}) == 1


def test_stale_nested_n3_hash_blocks_publication(package):
    mutated = deepcopy(package)
    protocol = mutated[f"{DEFINITION_ROOT}/phase9/qualification_protocol.json"]
    protocol["axes"]["CONTRACTUAL_HARD_SAFETY"]["n3_axis_hash"] = (
        "sha256:stale-superseded-axis"
    )
    with pytest.raises(FreezePublicationError, match="ACTIVE_N3_AXIS_HASH_MISMATCH"):
        validate_v135_package_for_publication(mutated)


@pytest.mark.parametrize("stage", list(ACTIVE_MODEL_STAGE_PROMPTS))
def test_prompt_mutation_moves_authority_and_blocks_before_transport(
    stage, package
):
    prompt_id = ACTIVE_MODEL_STAGE_PROMPTS[stage]
    frozen = package[f"{DEFINITION_ROOT}/phase9/executable_prompt_authority.json"]
    execution = package[
        f"{DEFINITION_ROOT}/phase9/candidate_execution_contract.json"
    ]
    mutated_specs = dict(PROMPT_SPECS)
    mutated_specs[prompt_id] = replace(
        PROMPT_SPECS[prompt_id],
        developer_instruction=(
            PROMPT_SPECS[prompt_id].developer_instruction
            + "\nCONTROLLED_CONVERGENCE_MUTATION"
        ),
    )
    mutated_authority = executable_prompt_authority(mutated_specs)
    assert mutated_authority["prompt_authority_hash"] != frozen[
        "prompt_authority_hash"
    ]
    assert mutated_authority["stages"][stage]["stage_prompt_authority_hash"] != frozen[
        "stages"
    ][stage]["stage_prompt_authority_hash"]
    calls = 0

    def transport_factory():
        nonlocal calls
        calls += 1
        return object()

    with pytest.raises(QualificationPromptMismatch, match="PROMPT_MISMATCH"):
        build_qualification_transport_after_prompt_guard(
            stage=stage,
            prompt_id=prompt_id,
            frozen_prompt_authority=frozen,
            frozen_execution_contract=execution,
            transport_factory=transport_factory,
            live_specs=mutated_specs,
        )
    assert calls == 0


@pytest.mark.parametrize("stage", list(ACTIVE_MODEL_STAGE_PROMPTS))
def test_actual_phase9_transport_boundary_blocks_prompt_drift(stage):
    prompt_id = ACTIVE_MODEL_STAGE_PROMPTS[stage]
    mutated_specs = dict(PROMPT_SPECS)
    mutated_specs[prompt_id] = replace(
        PROMPT_SPECS[prompt_id],
        developer_instruction=(
            PROMPT_SPECS[prompt_id].developer_instruction
            + "\nCONTROLLED_ENTRYPOINT_MUTATION"
        ),
    )
    factory_calls = 0

    def transport_factory(_api_key):
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(
        px.Phase9ExecutionError,
        match="PHASE9_EXECUTABLE_PROMPT_AUTHORITY_MISMATCH",
    ):
        px._build_v135_prompt_guarded_transport(
            candidate=px.CANDIDATE_BY_STAGE[stage],
            api_key=SecretStr("synthetic-test-only-not-a-provider-key"),
            adapter_factory=transport_factory,
            live_specs=mutated_specs,
        )
    assert factory_calls == 0


def test_p06_every_submission_group_has_its_full_route_surface(build, package):
    requests = package[f"{DEFINITION_ROOT}/phase9/p06_submission_requests.json"]
    assert requests["submission_group_count"] == 45
    assert requests["single_route_group_count"] == 23
    assert requests["multi_route_group_count"] == 22
    assert requests["route_count_distribution"] == {"1": 23, "2": 18, "3": 4}
    assert requests["route_count"] == 71
    for row in build.p06_request_groups:
        request, envelope = build.p06_runtime_requests[row["provider_case_id"]]
        expected = row["route_count"]
        assert len(request.blueprint.dimensions) == expected
        assert len(envelope.dimensions) == expected
        assert len(envelope.variants) == expected
        assert len(envelope.templates) == expected
        if expected > 1:
            assert min(
                len(envelope.dimensions),
                len(envelope.variants),
                len(envelope.templates),
            ) > 1
        assert len(envelope.evidence_units) == len(
            request.evidence_bundle.allowed_evidence_ids
        )


def test_p06_denominator_and_oracle_separation_are_preserved(build, package):
    observations = package[
        f"{DEFINITION_ROOT}/phase9/p06_property_observation_bindings.json"
    ]
    assert observations["binding_count"] == 71
    assert observations["candidate_scoring_property_count"] == 69
    assert observations["expected_support_status_exposed_to_candidate"] is False
    assert observations["oracle_outcome_exposed_to_candidate"] is False
    assert all(
        row["model_visible_oracle_fields_present"] is False
        for row in build.p06_request_groups
    )


def test_p06_production_materializer_allows_omission_but_scoring_detects_it(build):
    group = next(row for row in build.p06_request_groups if row["route_count"] > 1)
    request, envelope = build.p06_runtime_requests[group["provider_case_id"]]
    draft = m.EvidenceMappingModelDraft(scope_alias=envelope.scope_alias, mappings=[])
    materialized = materialize_evidence_mapping_draft(draft=draft, request=request)
    assert materialized.opportunities == []
    binding = next(
        row
        for row in build.p06_observation_bindings
        if row["provider_case_id"] == group["provider_case_id"]
        and row["candidate_scoring_allowed"]
    )
    observation = score_p06_property_observation(
        draft=draft, request=request, binding=binding
    )
    assert observation["route_omitted"] is True
    assert observation["result_state"] == "MODEL_FAILURE"


def _rejected_rung(rung):
    row = _clean_rung_row(rung)
    row["stages"]["SEMANTIC_CORE"]["accepted_rate"] = 0.0
    return row


@pytest.mark.parametrize(
    "rows",
    [
        [_clean_rung_row("XHIGH")],
        [_rejected_rung("HIGH"), _clean_rung_row("MAX")],
        [_rejected_rung("HIGH"), _clean_rung_row("HIGH")],
        [_clean_rung_row("HIGH"), _rejected_rung("HIGH")],
        [
            _rejected_rung("HIGH"),
            _rejected_rung("XHIGH"),
            _clean_rung_row("XHIGH"),
        ],
    ],
)
def test_malformed_rung_collections_raise_before_selection(rows):
    with pytest.raises(RungSelectionError):
        select_lowest_qualifying_rung(stage="P06", rung_results=rows)


def test_high_eligible_selects_high():
    result = select_lowest_qualifying_rung(
        stage="P06", rung_results=[_clean_rung_row("HIGH")]
    )
    assert result["selected_rung"] == "HIGH"


def test_rejected_high_then_eligible_xhigh_selects_xhigh_in_any_row_order():
    high = _rejected_rung("HIGH")
    xhigh = _clean_rung_row("XHIGH")
    forward = select_lowest_qualifying_rung(
        stage="P06", rung_results=[high, xhigh]
    )
    reverse = select_lowest_qualifying_rung(
        stage="P06", rung_results=[xhigh, high]
    )
    assert forward["selected_rung"] == reverse["selected_rung"] == "XHIGH"


def test_three_rung_valid_prefix_selects_max():
    result = select_lowest_qualifying_rung(
        stage="P06",
        rung_results=[
            _rejected_rung("HIGH"),
            _rejected_rung("XHIGH"),
            _clean_rung_row("MAX"),
        ],
    )
    assert result["selected_rung"] == "MAX"


def test_complete_exhausted_prefix_has_no_qualifying_configuration():
    result = select_lowest_qualifying_rung(
        stage="P06",
        rung_results=[
            _rejected_rung("HIGH"),
            _rejected_rung("XHIGH"),
            _rejected_rung("MAX"),
        ],
    )
    assert result["selected_rung"] is None
    assert result["outcome"] == "NO_QUALIFYING_CONFIGURATION"


def test_deeper_rung_after_eligible_or_inconclusive_predecessor_is_invalid():
    with pytest.raises(RungSelectionError, match="before HIGH failed"):
        select_lowest_qualifying_rung(
            stage="P06",
            rung_results=[_clean_rung_row("HIGH"), _clean_rung_row("XHIGH")],
        )
    pending = _clean_rung_row("HIGH")
    pending["stages"]["N3_CORE"]["promotion_disposition"] = "PENDING_BLOCKED"
    with pytest.raises(RungSelectionError, match="before HIGH failed"):
        select_lowest_qualifying_rung(
            stage="P06", rung_results=[pending, _clean_rung_row("XHIGH")]
        )


def test_v135_package_is_publication_valid_and_zero_execution(package):
    report = validate_v135_package_for_publication(package)
    assert report == {
        "artifact_count": 16,
        "n3_binding_count": 7,
        "prompt_stage_count": 4,
        "execution_counters_zero": True,
    }
    freeze = package[
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
    ]
    assert freeze["qualification_run"] is False
    assert freeze["high_smoke_authorized"] is False


def test_published_v135_documents_match_the_validated_package(package):
    for relative, document in package.items():
        published = json.loads(
            (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        )
        assert published == document, relative


def test_v135_manifest_keeps_internal_file_and_blob_hashes_distinct(package):
    manifest = json.loads(
        (
            REPOSITORY_ROOT
            / REPORT_ROOT
            / "phase9/freeze_hash_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["artifact_count"] == len(package) == 16
    assert {row["path"] for row in manifest["artifacts"]} == set(package)
    assert manifest["provider_calls"] == manifest["adjudicator_calls"] == 0
    assert manifest["credential_resolutions"] == 0
    assert manifest["real_provider_transport"] is False
    assert manifest["pricing_refresh"] == "NOT_PERFORMED"
    assert manifest["high_smoke"] == "NOT_EXECUTED"
    assert manifest["billable_authorization"] == "NONE"
    for row in manifest["artifacts"]:
        data = (REPOSITORY_ROOT / row["path"]).read_bytes()
        assert row["file_sha256"] == f"sha256:{sha256(data).hexdigest()}"
        assert row["git_blob_sha"] == sha1(
            b"blob %d\0" % len(data) + data
        ).hexdigest()
        assert row["internal_material_hash"] == package[row["path"]][
            row["self_material_hash_field"]
        ]
        assert len(
            {
                row["internal_material_hash"],
                row["file_sha256"],
                row["git_blob_sha"],
            }
        ) == 3


def test_v134_frozen_bytes_remain_unmodified():
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "evaluation/semantic_benchmark/v1_3_4",
            "reports/semantic_benchmark/v1_3_4",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
