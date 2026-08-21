"""Direct regressions for the phase9-execution/2.0.1 cutover.

Nothing in this module resolves a credential, constructs a transport, calls a
provider, calls an adjudicator, refreshes pricing, or executes HIGH-SMOKE.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from comprehension_verification import phase9_execution as px
from comprehension_verification.model_gateway.registry import PROMPT_SPECS


@pytest.fixture(scope="module")
def prepared() -> px.PreparedExecution:
    return px.prepare_phase9_execution()


def _decomposition(calls: tuple[px.LogicalCall, ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for call in calls:
        key = "/".join(
            (
                call.case.axis,
                call.case.stage,
                call.case.split,
                call.case.candidate.reasoning_effort,
            )
        )
        result[key] = result.get(key, 0) + 1
    return result


def _zero_counter_assertions(counters: dict[str, Any]) -> None:
    assert counters == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "transport_factory_calls": 0,
        "real_provider_transport": False,
        "pricing_refresh": "NOT_PERFORMED",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }


@pytest.mark.parametrize(
    ("field", "legacy_path"),
    [
        (
            "call_budget",
            px.REPOSITORY_ROOT / "reports/semantic_benchmark/v1_1/case_matrix.json",
        ),
        (
            "candidate_matrix",
            px.REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_1/phase9/candidate_matrix.json",
        ),
    ],
)
def test_active_v2_rejects_legacy_authority_before_read(
    field: str, legacy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the defect: no v1.1 matrix/protocol path is readable."""

    observed_reads: list[Path] = []
    original = Path.read_text

    def recording_read(path: Path, *args: Any, **kwargs: Any) -> str:
        observed_reads.append(path.resolve())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read)
    paths = replace(px.FrozenAuthorityPaths(), **{field: legacy_path})
    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.prepare_phase9_execution(authority_paths=paths)
    assert exc.value.code == "PHASE9_V2_LEGACY_AUTHORITY_FORBIDDEN"
    assert legacy_path.resolve() not in observed_reads
    assert not any("semantic_benchmark/v1_1" in str(path) for path in observed_reads)


def test_versions_and_every_frozen_binding_are_current(
    prepared: px.PreparedExecution,
) -> None:
    assert px.PHASE9_EXECUTION_VERSION == "phase9-execution/2.0.1"
    assert prepared.boundary["benchmark_version"] == "semantic-benchmark/1.3.5"
    assert prepared.boundary["protocol_version"] == (
        "phase9-qualification-protocol/1.3.5"
    )
    assert prepared.boundary["semantic_benchmark_bindings"] == {
        "pre_results_instrument_freeze_hash": (
            "sha256:c2c2a552780c0cea7af5f7b3097da115de6fc6ee84cdbdfd9ad9943f8d655126"
        ),
        "benchmark_boundary_hash": px.EXPECTED_BENCHMARK_BOUNDARY_HASH,
        "stage_boundaries_hash": (
            "sha256:1393551f498ab97daecb6b40ea0ae93fcae3fcdaa188a683dcc9adf6a8c8b49b"
        ),
        "stage_boundary_hashes": {
            "P04": "sha256:866b95464960123d3e96ab1d713d9980dea127bdbe9f1f07922c37888bb4d761",
            "P06": "sha256:8bbf07c653435783c21af4257d62df77ac325f5454e2a47c3b570337fde42354",
            "P07": "sha256:a1cd37d8dec4260ccee1eb5ecaaa8ba4d6e73170f274fca300f2e4669177bef6",
            "P09": "sha256:0006106e4433124fdea9fddd296346b4dd239e20f10bfa4aa1a670a44d3989c1",
            "PLANNER": "sha256:961384f7f9c25601b5aea91217849be79400517d7b5960924c79789c93687376",
        },
        "protocol_boundary_hash": px.EXPECTED_PROTOCOL_BOUNDARY_HASH,
        "candidate_matrix_hash": (
            "sha256:d4c693ec60c4603ea9924daf5146f06d714bb19f1007a5d82fef57d4d5dfb36d"
        ),
        "candidate_execution_contract_hash": px.EXPECTED_EXECUTION_CONTRACT_HASH,
        "prompt_authority_hash": px.EXPECTED_PROMPT_AUTHORITY_HASH,
        "call_budget_hash": (
            "sha256:f0ed55246d56362b170aa0b2e29f99f4d1f1660f5f16b90751cc298d18b69dde"
        ),
        "n3_axis_hash": px.EXPECTED_N3_AXIS_HASH,
        "p06_submission_request_set_hash": (
            "sha256:7c1698189001ae48f80895cf07390cda811b652574401f4b5d1ce662de9ce960"
        ),
        "p06_property_observation_bindings_hash": (
            "sha256:d0d2bd909dd0b3137387b04c9a38995cb72baf0ce0ca6b442783cf93af76581c"
        ),
        "n3_provider_fixture_set_hash": (
            "sha256:9e00281c1d54a9436766105d6ba27aaae01564bd38182cfb4bd64e427b8ec310"
        ),
        "rung_collection_hash": (
            "sha256:bee091a421683f3e17e54d0118f85cac50f39605b89054324004b0b842a7efcc"
        ),
        "corpus_package_boundary_hash": px.EXPECTED_CORPUS_BOUNDARY_HASH,
    }
    assert "1.1.0" not in json.dumps(
        {
            "benchmark_version": prepared.boundary["benchmark_version"],
            "protocol_version": prepared.boundary["protocol_version"],
            "execution_version": prepared.boundary["execution_version"],
        }
    )


def test_execution_boundary_binds_exact_sources_and_plan(
    prepared: px.PreparedExecution,
) -> None:
    boundary = prepared.boundary
    assert boundary["execution_boundary_hash"] == px._self_hash(
        boundary, "execution_boundary_hash"
    )
    assert set(boundary["source_bindings"]) == px.REQUIRED_SOURCE_BINDING_PATHS
    for relative, expected in boundary["source_bindings"].items():
        assert expected == px._file_hash(px.REPOSITORY_ROOT / relative)
    assert boundary["request_authority"]["request_authority_hash"] == (
        prepared.request_authority["request_authority_hash"]
    )
    assert boundary["high_smoke_plan"]["plan_hash"] == prepared.plan["plan_hash"]


def test_exact_high_smoke_plan_is_thirty_calls_3_3_3_18_3(
    prepared: px.PreparedExecution,
) -> None:
    assert len(prepared.calls) == px.AUTHORIZED_PRIMARY_LOGICAL_CALLS == 30
    assert _decomposition(prepared.calls) == px.EXPECTED_PLAN_DECOMPOSITION
    assert prepared.boundary["high_smoke_plan"]["decomposition"] == (
        px.EXPECTED_PLAN_DECOMPOSITION
    )
    assert len({call.logical_call_id for call in prepared.calls}) == 30


def test_p06_semantic_smoke_is_one_grouped_two_route_request_k3(
    prepared: px.PreparedExecution,
) -> None:
    cases = [
        case
        for case in prepared.cases
        if case.axis == "SEMANTIC" and case.stage == "P06"
    ]
    assert len(cases) == 1
    case = cases[0]
    row = next(
        item
        for item in prepared.request_authority["semantic_cases"]
        if item["provider_identity"] == case.provider_identity
    )
    group = row["p06_group_authority"]
    assert case.provider_unit == "SUBMISSION_RUN"
    assert (
        group["route_count"],
        group["dimension_count"],
        group["variant_count"],
        group["template_count"],
    ) == (2, 2, 2, 2)
    assert len(case.request.blueprint.dimensions) == 2
    assert len([call for call in prepared.calls if call.case is case]) == 3
    assert [
        call.run_index for call in prepared.calls if call.case is case
    ] == [1, 2, 3]


def test_n3_is_one_explicit_exposure_run_axis_not_semantic_scoring(
    prepared: px.PreparedExecution,
) -> None:
    cases = [
        case for case in prepared.cases if case.axis == "CONTRACTUAL_HARD_SAFETY"
    ]
    assert len(cases) == 1
    case = cases[0]
    assert case.stage == "P06"
    assert case.split == "N3_SAFETY_SMOKE"
    assert case.provider_unit == "EXPOSURE_RUN"
    assert case.property_observations == ()
    n3_calls = [call for call in prepared.calls if call.case is case]
    assert [
        (call.case.exposure_pseudonym, call.run_index) for call in n3_calls
    ] == [
        ("N3-act_01_luz_y_plantines-submission_01", 1),
        ("N3-act_01_luz_y_plantines-submission_01", 2),
        ("N3-act_01_luz_y_plantines-submission_01", 3),
    ]


def test_stale_v135_hash_blocks_before_credentials_or_transport(
    prepared: px.PreparedExecution,
) -> None:
    mutated = deepcopy(prepared.authorities.documents["benchmark_boundary"])
    mutated["benchmark_boundary_hash"] = "sha256:" + "0" * 64
    credential_calls = 0
    factory_calls = 0

    def credential_resolver():
        nonlocal credential_calls
        credential_calls += 1
        return None

    def transport_factory(_key):
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.run_phase9b_smoke(
            created_by="test",
            allow_billable=True,
            credential_resolver=credential_resolver,
            adapter_factory=transport_factory,
            authority_document_overrides={"benchmark_boundary": mutated},
        )
    assert exc.value.code == "PHASE9_V135_SELF_HASH_MISMATCH"
    assert credential_calls == factory_calls == 0
    _zero_counter_assertions(exc.value.safety_counters)


def test_live_prompt_mutation_blocks_before_credentials_or_transport(
    prepared: px.PreparedExecution,
) -> None:
    del prepared
    prompt_id = "P06_EVIDENCE_MAP_V1"
    mutated_specs = dict(PROMPT_SPECS)
    mutated_specs[prompt_id] = replace(
        PROMPT_SPECS[prompt_id],
        developer_instruction=(
            PROMPT_SPECS[prompt_id].developer_instruction
            + "\nCONTROLLED_EXECUTION_V2_TEST_MUTATION"
        ),
    )
    credential_calls = 0
    factory_calls = 0

    def credential_resolver():
        nonlocal credential_calls
        credential_calls += 1
        return None

    def transport_factory(_key):
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.run_phase9b_smoke(
            created_by="test",
            allow_billable=True,
            credential_resolver=credential_resolver,
            adapter_factory=transport_factory,
            live_specs=mutated_specs,
        )
    assert exc.value.code == "PHASE9_EXECUTABLE_PROMPT_AUTHORITY_MISMATCH"
    assert credential_calls == factory_calls == 0
    _zero_counter_assertions(exc.value.safety_counters)


def test_absent_current_pricing_is_the_explicit_precredential_stop() -> None:
    assert not px.CURRENT_PRICING_PATH.exists()
    credential_calls = 0
    factory_calls = 0

    def credential_resolver():
        nonlocal credential_calls
        credential_calls += 1
        return None

    def transport_factory(_key):
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.run_phase9b_smoke(
            created_by="test",
            allow_billable=True,
            credential_resolver=credential_resolver,
            adapter_factory=transport_factory,
        )
    assert exc.value.code == "PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION"
    assert credential_calls == factory_calls == 0
    _zero_counter_assertions(exc.value.safety_counters)


def test_high_smoke_reaches_no_core_heldout_xhigh_or_max(
    prepared: px.PreparedExecution,
) -> None:
    for call in prepared.calls:
        assert call.case.split in {"SMOKE", "N3_SAFETY_SMOKE"}
        assert call.case.candidate.reasoning_effort == "HIGH"
        assert call.case.candidate.candidate_id not in px.FORBIDDEN_CANDIDATE_IDS
    assert not any(
        call.case.split
        in {"CORE", "HELD_OUT_CONFIRMATION", "N3_CORE", "N3_HELD_OUT_CONFIRMATION"}
        for call in prepared.calls
    )


def test_heldout_material_cannot_enter_high_smoke_selection(
    prepared: px.PreparedExecution,
) -> None:
    authority = prepared.request_authority
    assert authority["selection_depends_on_results"] is False
    assert authority["contains_held_out_material"] is False
    assert {row["split"] for row in authority["semantic_cases"]} == {"SMOKE"}
    assert {row["split"] for row in authority["n3_exposures"]} == {
        "N3_SAFETY_SMOKE"
    }
    held_out = set(
        prepared.authorities.documents["n3_axis"]["selectors"][
            "held_out_exposure_ids"
        ]
    )
    assert not held_out.intersection(
        row["exposure_pseudonym"] for row in authority["n3_exposures"]
    )


def test_semantic_and_n3_packet_sets_are_disjoint_and_correct(
    prepared: px.PreparedExecution,
) -> None:
    outputs = {
        call.logical_call_id: px.CompletedCall(
            canonical_output=(
                {"opportunities": []}
                if call.case.axis == "SEMANTIC" and call.case.stage == "P06"
                else {}
            ),
            provider_output={},
        )
        for call in prepared.calls
    }
    surfaces = px.build_blind_packet_sets(calls=prepared.calls, outputs=outputs)
    assert surfaces["semantic"]["packet_count"] == 54
    assert surfaces["semantic"]["denominator"] == "ACCEPTED_SEMANTIC_RATE_ONLY"
    assert surfaces["n3"]["packet_count"] == 3
    assert surfaces["n3"]["denominator"] == (
        "EXCLUDED_FROM_ACCEPTED_SEMANTIC_RATE"
    )
    assert surfaces["n3"]["verdicts"] == [
        "NO_CONFIRMED_VIOLATION",
        "INDETERMINATE",
        "CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE",
    ]
    semantic_ids = {
        row["packet_id"] for row in surfaces["semantic"]["packets"]
    }
    n3_ids = {row["packet_id"] for row in surfaces["n3"]["packets"]}
    assert semantic_ids.isdisjoint(n3_ids)
    p06_semantic = [
        row
        for row in surfaces["semantic"]["packets"]
        if row["packet"]["case_id"] == "PP-A01-S03-P06-G01"
    ]
    assert len(p06_semantic) == 6
    assert all(row["packet"]["candidate_output"]["route_omitted"] for row in p06_semantic)
    assert [
        (row["packet"]["exposure_pseudonym"], row["packet"]["run_index"])
        for row in surfaces["n3"]["packets"]
    ] == [
        ("N3-act_01_luz_y_plantines-submission_01", 1),
        ("N3-act_01_luz_y_plantines-submission_01", 2),
        ("N3-act_01_luz_y_plantines-submission_01", 3),
    ]


def test_authorization_requirements_are_v135_v2_and_not_an_authorization(
    prepared: px.PreparedExecution,
) -> None:
    pricing_material = {
        "schema_version": "phase9-current-pricing/2.0.1",
        "execution_version": px.PHASE9_EXECUTION_VERSION,
        "status": "SYNTHETIC_TEST_ONLY",
        "models": {},
    }
    pricing = {
        **pricing_material,
        "pricing_snapshot_hash": px._hash(pricing_material),
    }
    requirements = px.authorization_requirements(prepared, pricing)
    assert requirements["authorization_state"] == "NOT_AUTHORIZED_TEMPLATE"
    assert requirements["benchmark_version"] == "semantic-benchmark/1.3.5"
    assert requirements["protocol_version"] == (
        "phase9-qualification-protocol/1.3.5"
    )
    assert requirements["execution_version"] == "phase9-execution/2.0.1"
    assert requirements["execution_boundary_hash"] == (
        prepared.boundary["execution_boundary_hash"]
    )
    assert requirements["high_smoke_plan_hash"] == prepared.plan["plan_hash"]
    assert requirements["logical_call_identities"] == [
        call.identity() for call in prepared.calls
    ]
    assert "outer_cap_usd" in requirements["required_future_fields"]
    assert "authorization_hash" in requirements["required_future_fields"]


def test_no_executable_pricing_or_cap_fallback_remains() -> None:
    source = Path(px.__file__).read_text(encoding="utf-8")
    assert "verify_pricing_snapshot" not in source
    assert "MODEL_PRICES" not in source
    assert "OUTER_AUTHORIZATION_CAP_USD" not in source
    assert "pricing_snapshot.json" not in source


def test_all_semantic_benchmark_v135_bytes_remain_unchanged(
    prepared: px.PreparedExecution,
) -> None:
    for relative, binding in prepared.boundary["frozen_artifacts"].items():
        data = (px.REPOSITORY_ROOT / relative).read_bytes()
        assert "semantic_benchmark/v1_3_5" in relative
        assert f"sha256:{sha256(data).hexdigest()}" == binding["file_sha256"]
    assert px._file_hash(px.FrozenAuthorityPaths().freeze_manifest) == (
        prepared.boundary["freeze_manifest_file_sha256"]
    )
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "evaluation/semantic_benchmark/v1_3_5",
            "reports/semantic_benchmark/v1_3_5",
        ],
        cwd=px.REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
