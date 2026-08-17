"""Phase 9A protocol freeze regression.

Every test here is offline. Nothing in this module constructs provider
transport, issues an authorization, or reads a historical qualification report
for anything that could influence candidate selection or thresholds.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import pytest

from comprehension_verification.phase9_protocol import (
    ACCEPTED_RATE_BAR,
    BENCHMARK_BOUNDARY_HASH,
    CANDIDATE_MATRIX,
    CORPUS_PACKAGE_BOUNDARY_HASH,
    MAX_CANDIDATES_PER_STAGE,
    MAX_TECHNICAL_RETRIES,
    PASS_QA_SAMPLE_PERCENT,
    PHASE_8_1_BASELINE_SHA,
    REVIEW_PACKET_FORBIDDEN_FIELDS,
    SEMANTIC_K,
    SEMANTIC_STAGES,
    SPLITS,
    STAGE_PRODUCTION_OUTPUT_CAP,
    VERIFIED_MODEL_IDS,
    Phase9ProtocolError,
    build_adjudication_load,
    build_protocol,
    consolidate_failure,
    load_benchmark_facts,
    max_confirmed_failures,
    pass_qa_selected,
    protocol_boundary_hash,
    validate_protocol,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_DIR = REPO_ROOT / "evaluation/semantic_benchmark/v1_1/phase9"
REPORT_DIR = REPO_ROOT / "reports/semantic_benchmark/v1_1/phase9"


@pytest.fixture(scope="module")
def facts():
    return load_benchmark_facts()


@pytest.fixture(scope="module")
def protocol(facts):
    return build_protocol(facts)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- A: baseline benchmark boundary --------------------------------------


def test_a_baseline_benchmark_boundary_is_exact(protocol) -> None:
    assert protocol["benchmark_boundary_hash"] == BENCHMARK_BOUNDARY_HASH
    assert protocol["corpus_package_boundary_hash"] == CORPUS_PACKAGE_BOUNDARY_HASH
    assert protocol["phase_8_1_baseline_sha"] == PHASE_8_1_BASELINE_SHA
    benchmark = _read(REPO_ROOT / "reports/semantic_benchmark/v1_1/benchmark_boundary.json")
    encoded = json.dumps(benchmark)
    assert BENCHMARK_BOUNDARY_HASH.removeprefix("sha256:") in encoded


# --- B: held-out case membership unchanged -------------------------------


def test_b_held_out_case_membership_unchanged(facts) -> None:
    manifest = _read(REPO_ROOT / "reports/semantic_benchmark/v1_1/split_manifest.json")
    assert manifest["freeze_status"] == "FROZEN_AT_PHASE_8_1_CLOSE"
    assert manifest["counts_by_split_and_stage"] == {
        "CORE": {"P04": 6, "P06": 64, "P07": 55, "P09": 2, "PLANNER": 12},
        "HELD_OUT_CONFIRMATION": {"P04": 5, "P06": 61, "P07": 47, "P09": 1, "PLANNER": 7},
        "SMOKE": {"P04": 1, "P06": 2, "P07": 6, "P09": 1, "PLANNER": 2},
    }
    assert sum(manifest["totals_by_split"].values()) == 272


# --- C/D/E/F: candidate matrix integrity ---------------------------------


def test_c_candidate_matrix_only_officially_verified_model_ids() -> None:
    assert VERIFIED_MODEL_IDS == {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"}
    for candidate in CANDIDATE_MATRIX:
        assert candidate["model"] in VERIFIED_MODEL_IDS


def test_c2_candidate_models_are_invocable_by_the_real_provider_registry() -> None:
    from comprehension_verification.model_gateway.openai_routes import (
        OPENAI_APPROVED_MODEL_IDS,
    )

    for candidate in CANDIDATE_MATRIX:
        assert candidate["model"] in OPENAI_APPROVED_MODEL_IDS


def test_d_candidate_matrix_has_no_duplicate_equivalent_configs() -> None:
    identities = [
        (c["stage"], c["model"], c["reasoning_effort"], c["max_output_tokens"])
        for c in CANDIDATE_MATRIX
    ]
    assert len(identities) == len(set(identities))


def test_e_max_candidate_count_per_stage_respected() -> None:
    for stage in SEMANTIC_STAGES:
        entries = [c for c in CANDIDATE_MATRIX if c["stage"] == stage]
        assert 0 < len(entries) <= MAX_CANDIDATES_PER_STAGE


def test_f_candidate_identity_includes_reasoning_and_output_cap(protocol) -> None:
    fields = protocol["candidate_matrix"]["candidate_identity_fields"]
    assert "reasoning_effort" in fields
    assert "max_output_tokens" in fields
    assert protocol["candidate_matrix"]["reasoning_change_creates_new_candidate"] is True
    # Same model at two efforts must be two distinct candidates.
    luna_p06 = sorted(
        c["reasoning_effort"]
        for c in CANDIDATE_MATRIX
        if c["stage"] == "P06" and c["model"] == "gpt-5.6-luna"
    )
    assert luna_p06 == ["HIGH", "XHIGH"]


def test_f2_output_caps_match_the_production_registry_contract() -> None:
    from comprehension_verification.model_gateway.registry import PROMPT_SPECS
    from comprehension_verification.phase9_protocol import STAGE_PROMPT_ID

    for stage, cap in STAGE_PRODUCTION_OUTPUT_CAP.items():
        assert PROMPT_SPECS[STAGE_PROMPT_ID[stage]].max_output_tokens == cap
    for candidate in CANDIDATE_MATRIX:
        assert candidate["max_output_tokens"] == STAGE_PRODUCTION_OUTPUT_CAP[candidate["stage"]]


# --- G/H/I: adjudicator blinding -----------------------------------------


def test_g_adjudicator_packet_hides_candidate_identity(protocol) -> None:
    blinding = protocol["adjudication_protocol"]["blinding"]
    forbidden = set(blinding["forbidden_packet_fields"])
    for field in (
        "candidate_model",
        "candidate_model_family",
        "candidate_id",
        "reasoning_effort",
        "candidate_cost",
        "promotion_order",
        "current_ranking",
    ):
        assert field in forbidden
    assert not forbidden & set(blinding["allowed_packet_fields"])


def test_h_adjudicator_packet_hides_split(protocol) -> None:
    forbidden = set(protocol["adjudication_protocol"]["blinding"]["forbidden_packet_fields"])
    assert {"split", "split_name", "rung", "is_held_out"} <= forbidden
    assert protocol["adjudication_protocol"]["blinding"]["held_out_indistinguishable_from_core"]


def test_i_packet_contains_only_relevant_source_property_and_output() -> None:
    schema = _read(
        REPO_ROOT / "evaluation/semantic_benchmark/v1_1/schemas/review_packet.schema.json"
    )
    allowed = set(schema["properties"])
    assert schema["additionalProperties"] is False
    assert not allowed & set(REVIEW_PACKET_FORBIDDEN_FIELDS)
    assert {"candidate_output", "relevant_source_refs", "property", "oracle_state"} <= allowed


def test_i2_bidirectional_leakage_is_forbidden(protocol) -> None:
    blinding = protocol["adjudication_protocol"]["blinding"]
    assert "never sees the oracle" in blinding["bidirectional"]
    assert "separate" in blinding["process_separation"]


# --- J/K: MODEL_FAILURE high bar -----------------------------------------


def test_j_model_failure_impossible_on_oracle_suspect_property(protocol) -> None:
    adjudication = protocol["adjudication_protocol"]
    assert adjudication["model_failure_forbidden_on_oracle_suspect"] is True
    assert "PROPERTY_ORACLE_STATE_IS_VALID" in adjudication["model_failure_requirements"]
    schema = _read(PROTOCOL_DIR / "schemas/adjudication_decision.schema.json")
    required = schema["properties"]["model_failure_requirements"]["required"]
    assert "PROPERTY_ORACLE_STATE_IS_VALID" in required


def test_k_model_failure_requires_high_confidence(protocol) -> None:
    assert protocol["adjudication_protocol"]["model_failure_requires_high_confidence"]
    schema = _read(PROTOCOL_DIR / "schemas/adjudication_decision.schema.json")
    guard = schema["allOf"][0]
    assert guard["if"]["properties"]["decision"]["const"] == "MODEL_FAILURE"
    assert guard["then"]["properties"]["confidence"]["const"] == "HIGH"


def test_k2_model_failure_requirement_list_is_complete(protocol) -> None:
    requirements = protocol["adjudication_protocol"]["model_failure_requirements"]
    assert len(requirements) == 11
    assert "NO_REASONABLE_DEFENSIBLE_ALTERNATIVE_EXISTS" in requirements
    assert "NOT_A_TECHNICAL_FAILURE" in requirements
    assert "JUDGEMENT_DOES_NOT_DEPEND_ON_EXTERNAL_KNOWLEDGE" in requirements


# --- L/M/N/O: two-pass confirmation --------------------------------------


def test_l_first_pass_failure_requires_a_second_pass(protocol) -> None:
    second = protocol["adjudication_protocol"]["second_pass"]
    assert second["trigger"] == "FIRST_PASS_DECISION_IS_MODEL_FAILURE"
    assert second["context"] == "FRESH_CONTEXT_NO_SHARED_STATE"


def test_m_second_pass_cannot_read_first_pass_result(protocol) -> None:
    second = protocol["adjudication_protocol"]["second_pass"]
    assert second["second_pass_sees_first_pass_decision"] is False
    assert second["second_pass_sees_first_pass_rationale"] is False
    assert second["second_pass_sees_candidate_identity"] is False
    forbidden = set(protocol["adjudication_protocol"]["blinding"]["forbidden_packet_fields"])
    assert {"first_pass_decision", "first_pass_rationale", "first_pass_confidence"} <= forbidden
    schema = _read(PROTOCOL_DIR / "schemas/failure_consolidation.schema.json")
    assert schema["$defs"]["passRecord"]["properties"]["saw_other_pass"]["const"] is False


def test_n_consolidator_is_deterministic(protocol) -> None:
    assert protocol["adjudication_protocol"]["second_pass"]["third_llm_judge_allowed"] is False
    kwargs = dict(
        first_pass="MODEL_FAILURE",
        second_pass="MODEL_FAILURE",
        first_confidence="HIGH",
        second_confidence="HIGH",
        source_reasons_compatible=True,
    )
    results = {json.dumps(consolidate_failure(**kwargs), sort_keys=True) for _ in range(25)}
    assert len(results) == 1
    assert consolidate_failure(**kwargs) == {
        "diagnostic": "MODEL_FAILURE_CONFIRMED",
        "result_state": "MODEL_FAILURE",
    }


@pytest.mark.parametrize(
    "second_pass,second_confidence,compatible",
    [
        ("PASS", "HIGH", True),
        ("DEFENSIBLE_ALTERNATIVE", "HIGH", True),
        ("PENDING_ADJUDICATION", "HIGH", True),
        ("MODEL_FAILURE", "MEDIUM", True),
        ("MODEL_FAILURE", "HIGH", False),
    ],
)
def test_o_disagreement_cannot_silently_become_model_failure(
    second_pass: str, second_confidence: str, compatible: bool
) -> None:
    outcome = consolidate_failure(
        first_pass="MODEL_FAILURE",
        second_pass=second_pass,
        first_confidence="HIGH",
        second_confidence=second_confidence,
        source_reasons_compatible=compatible,
    )
    assert outcome["result_state"] != "MODEL_FAILURE"
    assert outcome["result_state"] in {"PENDING_ADJUDICATION", "ORACLE_SUSPECT"}


def test_o2_oracle_suspect_second_pass_yields_oracle_suspect() -> None:
    assert consolidate_failure(
        first_pass="MODEL_FAILURE",
        second_pass="ORACLE_SUSPECT",
        first_confidence="HIGH",
        second_confidence="HIGH",
        source_reasons_compatible=True,
    ) == {"diagnostic": "ORACLE_REVIEW_FINDING", "result_state": "ORACLE_SUSPECT"}


def test_o3_consolidation_only_applies_to_a_first_pass_failure() -> None:
    with pytest.raises(ValueError):
        consolidate_failure(
            first_pass="PASS",
            second_pass="PASS",
            first_confidence="HIGH",
            second_confidence="HIGH",
            source_reasons_compatible=True,
        )


# --- PASS QA --------------------------------------------------------------


def test_pass_qa_sample_is_predetermined_by_packet_identity() -> None:
    sample = "sha256:" + "ab" * 32
    assert pass_qa_selected(sample) == pass_qa_selected(sample)
    hashes = [f"sha256:{i:064x}" for i in range(4000)]
    selected = sum(pass_qa_selected(h) for h in hashes)
    # Selector is uniform, so the realised rate tracks the frozen percentage.
    assert abs(selected / len(hashes) * 100 - PASS_QA_SAMPLE_PERCENT) < 3


def test_pass_qa_policy_is_frozen(protocol) -> None:
    qa = protocol["adjudication_protocol"]["pass_qa"]
    assert qa["sample_percent"] == PASS_QA_SAMPLE_PERCENT
    assert qa["selection_depends_only_on_packet_identity"] is True
    assert qa["stratified_by"] == "STAGE"
    assert qa["second_pass_is_blind"] is True
    assert qa["on_exceeded"] == "PAUSE_QUALIFICATION"
    assert qa["oracle_edits_during_run"] is False


# --- P/Q/R/S/T: safety, alternatives, technical failure -------------------


def test_p_hard_safety_failure_rejects_candidate(protocol) -> None:
    hard = protocol["safety_gate"]["classes"]["HARD_SAFETY"]
    assert hard["max_confirmed_model_failures"] == 0
    assert hard["averaging_allowed"] is False
    for row in protocol["qualification_thresholds"]["thresholds"]:
        assert row["max_hard_safety_failures"] == 0
    codes = {rule["code"] for rule in protocol["execution_plan"]["early_stop_rules"]}
    assert "HARD_SAFETY_FAILURE_CONFIRMED" in codes


def test_p2_safety_gate_distinguishes_three_classes(protocol) -> None:
    classes = protocol["safety_gate"]["classes"]
    assert set(classes) == {"HARD_SAFETY", "REVIEWABLE_SAFETY", "NON_SAFETY"}
    assert protocol["safety_gate"]["totals"]["hard_safety_properties"] > 0
    assert protocol["safety_gate"]["totals"]["reviewable_safety_properties"] > 0


def test_q_defensible_alternative_is_not_a_model_failure(protocol) -> None:
    adjudication = protocol["adjudication_protocol"]
    assert adjudication["accepted_semantic_outcomes"] == ["PASS", "DEFENSIBLE_ALTERNATIVE"]
    assert "never a MODEL_FAILURE" in adjudication["defensible_alternative_policy"]
    assert protocol["qualification_thresholds"]["accepted_semantic_outcomes"] == [
        "PASS",
        "DEFENSIBLE_ALTERNATIVE",
    ]


def test_r_technical_failure_is_never_model_failure(protocol) -> None:
    retry = protocol["execution_plan"]["retry_policy"]
    assert retry["technical_failure_is_never_model_failure"] is True
    assert "NOT_A_TECHNICAL_FAILURE" in protocol["adjudication_protocol"]["model_failure_requirements"]
    decision_schema = _read(PROTOCOL_DIR / "schemas/adjudication_decision.schema.json")
    assert "TECHNICAL_FAILURE" not in decision_schema["properties"]["decision"]["enum"]


def test_s_semantic_retry_is_forbidden(protocol) -> None:
    retry = protocol["execution_plan"]["retry_policy"]
    assert retry["semantic_retry_allowed"] is False
    assert retry["retry_counts_as_new_semantic_sample"] is False
    assert retry["fallback_to_other_candidate_within_run_identity"] is False


def test_t_technical_retry_max_is_enforced(protocol) -> None:
    retry = protocol["execution_plan"]["retry_policy"]
    assert retry["max_technical_retries"] == MAX_TECHNICAL_RETRIES == 1
    assert "attempt_count" in retry["records"]
    retryable = set(retry["retryable_error_codes"])
    non_retryable = set(retry["non_retryable_error_codes"])
    assert not retryable & non_retryable
    assert "PROVIDER_OUTPUT_TRUNCATED_MAX_OUTPUT_TOKENS" in non_retryable
    assert "PROVIDER_INVALID_REQUEST" in non_retryable


def test_t2_retry_allowlist_matches_the_real_adapter_taxonomy(protocol) -> None:
    source = (
        REPO_ROOT / "src/comprehension_verification/model_gateway/openai_adapter.py"
    ).read_text(encoding="utf-8")
    for code in protocol["execution_plan"]["retry_policy"]["retryable_error_codes"]:
        assert f'"{code}"' in source


# --- U/V/W: k and thresholds ---------------------------------------------


def test_u_k_is_frozen(protocol) -> None:
    assert SEMANTIC_K == 3
    assert protocol["execution_plan"]["k"]["semantic"] == 3
    assert protocol["execution_plan"]["k"]["planner"] == 1
    for entry in protocol["budget_plan"]["per_candidate"]:
        for rung in entry["rungs"].values():
            assert rung["k"] == 3
            assert rung["calls"] == rung["cases"] * 3


def test_v_thresholds_are_frozen_and_pre_registered(protocol) -> None:
    thresholds = protocol["qualification_thresholds"]
    assert thresholds["pre_registered_before_any_real_output"] is True
    assert thresholds["derived_from_historical_qualifications"] is False
    assert thresholds["denominator_unit"] == "PROPERTY_CANDIDATE_REASONING"
    assert thresholds["max_pending_adjudication_at_promotion"] == 0
    assert thresholds["deterministic_hard_gate"]["required_pass_rate"] == 1.0
    assert thresholds["rule_based_hard_gate"]["required_pass_rate"] == 1.0
    assert len(thresholds["thresholds"]) == len(SEMANTIC_STAGES) * len(SPLITS)


def test_w_threshold_rounding_is_exact_per_stage_and_split(protocol) -> None:
    for row in protocol["qualification_thresholds"]["thresholds"]:
        applicable = row["applicable_property_count"]
        allowed = row["max_confirmed_model_failures"]
        bar = row["accepted_semantic_rate_bar"]
        assert applicable > 0
        # The allowance meets the bar.
        assert (applicable - allowed) / applicable >= bar
        # One more failure breaks it, so the allowance is maximal.
        assert (applicable - allowed - 1) / applicable < bar
        assert row["zero_tolerance_forced_by_denominator"] == (allowed == 0)


def test_w2_boundary_denominators_do_not_round_surprisingly() -> None:
    # 60 * 0.05 is exactly 3.0: the allowance must be 3, landing exactly on the
    # bar, not 2 through floating point drift.
    assert max_confirmed_failures(60, 0.95) == 3
    assert (60 - 3) / 60 == pytest.approx(0.95)
    # 69 * 0.05 is 3.45, so the allowance truncates to 3.
    assert max_confirmed_failures(69, 0.95) == 3
    # 19 * 0.05 is 0.95: a single failure would fall below the bar.
    assert max_confirmed_failures(19, 0.95) == 0
    assert max_confirmed_failures(0, 0.95) == 0


def test_w3_thresholds_match_the_benchmark_denominators(facts, protocol) -> None:
    for row in protocol["qualification_thresholds"]["thresholds"]:
        expected = facts.semantic_denominator[(row["stage"], row["split"])]
        assert row["applicable_property_count"] == expected
    total = sum(facts.semantic_denominator.values())
    assert total == 304


# --- X: held-out lock -----------------------------------------------------


def test_x_held_out_lock_is_declared(protocol) -> None:
    lock = protocol["held_out_lock"]
    assert lock["splits_frozen_at"] == "PHASE_8_1_CLOSE"
    assert lock["phase9_may_read_not_restructure"] is True
    for key in (
        "held_out_may_not_select_candidates",
        "held_out_may_not_choose_reasoning",
        "held_out_may_not_modify_prompts",
        "held_out_may_not_modify_routing",
        "held_out_may_not_adjust_thresholds",
    ):
        assert lock[key] is True
    promotion = protocol["execution_plan"]["promotion"]
    assert promotion["candidates_on_held_out"] == "ONLY_THE_SELECTED_STAGE_WINNER"
    assert promotion["held_out_multi_candidate_allowed"] is False


# --- Y: tie-break ---------------------------------------------------------


def test_y_tie_break_is_deterministic_and_total(protocol) -> None:
    order = protocol["execution_plan"]["tie_break_order"]
    assert order[0] == "ZERO_HARD_SAFETY_FAILURES"
    assert order[1] == "MEETS_RUNG_QUALIFICATION_THRESHOLD"
    assert order.index("LOWER_STABILITY_DISAGREEMENT_COUNT") < order.index(
        "LOWER_PROJECTED_PRODUCTION_COST"
    )
    assert order.index("LOWER_CONFIRMED_MODEL_FAILURE_RATE") < order.index(
        "LOWER_PROJECTED_PRODUCTION_COST"
    )
    # A total order needs a final discriminator that can never tie.
    assert order[-1] == "LEXICOGRAPHICALLY_SMALLEST_CANDIDATE_ID"


# --- Z: budget caps -------------------------------------------------------


def test_z_budget_caps_fail_closed(protocol) -> None:
    budget = protocol["budget_plan"]
    assert budget["status"] == "BUDGET_PLAN_FROZEN"
    assert "refused before any provider transport" in budget["fail_closed_rule"]
    assert budget["global_cap_usd"] > 0
    for entry in budget["per_candidate"]:
        assert entry["per_call_cap_usd"] >= entry["worst_case_call_cost_usd"]
        for rung in entry["rungs"].values():
            assert rung["cap_usd"] >= rung["worst_case_cost_usd"]
            assert rung["technical_retry_reserve_usd"] > 0 or rung["calls"] == 0
    stage_sum = sum(entry["stage_cap_usd"] for entry in budget["per_stage"].values())
    assert budget["global_cap_usd"] >= stage_sum


def test_z2_every_cap_level_exists(protocol) -> None:
    budget = protocol["budget_plan"]
    assert {"P04", "P06", "P07", "P09"} == set(budget["per_stage"])
    for entry in budget["per_candidate"]:
        assert set(entry["rungs"]) == set(SPLITS)


# --- AA: pricing ----------------------------------------------------------


def test_aa_pricing_snapshot_uses_only_official_openai_source(protocol) -> None:
    pricing = protocol["pricing_snapshot"]
    assert pricing["source_authority"] == "OFFICIAL_OPENAI_ONLY"
    assert pricing["official_source"].startswith("https://developers.openai.com/")
    assert pricing["copied_from_repository_history"] is False
    assert pricing["retrieved_at"] == "2026-08-17"
    for entry in pricing["models"]:
        for entry_key in ("input_price", "cached_input_price", "output_price"):
            assert entry_key in entry
    for model in protocol["candidate_matrix"]["verified_models"]:
        assert model["official_source"].startswith("https://developers.openai.com/")


def test_aa2_pricing_refresh_guard_is_defined(protocol) -> None:
    guard = protocol["pricing_snapshot"]["refresh_guard"]
    assert guard["when"] == "IMMEDIATELY_BEFORE_THE_FIRST_REAL_CALL_OF_PHASE_9B"
    assert guard["on_any_difference"] == "STOP_DO_NOT_EXECUTE"
    assert "model_alias_still_resolves" in guard["also_verifies"]


def test_aa3_no_dated_snapshot_is_invented(protocol) -> None:
    for model in protocol["candidate_matrix"]["verified_models"]:
        assert model["identifier_kind"] == "STABLE_ALIAS_NO_DATED_SNAPSHOT_PUBLISHED"
    assert "alias" in protocol["candidate_matrix"]["model_drift_risk"]


# --- AB/AC: authorization and provider calls ------------------------------


def test_ab_authorization_remains_none(protocol) -> None:
    assert protocol["authorization"] == "NONE"
    assert protocol["execution_state"] == "REAL_EXECUTION_NOT_AUTHORIZED"
    assert protocol["candidate_matrix"]["authorization"] == "NONE"
    assert protocol["budget_plan"]["authorization"] == "NONE"
    assert protocol["budget_plan"]["billable_authorization_created"] is False
    assert protocol["execution_plan"]["exactly_once"]["implemented_in_phase_9a"] is False


def test_ab2_phase_8_1_template_remains_unset() -> None:
    template = _read(
        REPO_ROOT
        / "evaluation/semantic_benchmark/v1_1/phase9_candidate_matrix_template.json"
    )
    assert template["matrix_status"] == "UNSET"
    assert template["authorization"] == "NONE"


def test_ac_provider_calls_in_phase9a_are_zero(protocol) -> None:
    assert protocol["provider_calls"] == 0
    assert protocol["execution_plan"]["provider_calls_performed"] == 0
    load = build_adjudication_load(load_benchmark_facts())
    assert load["adjudicator_calls_performed_in_phase_9a"] == 0


def test_ac2_protocol_module_constructs_no_transport() -> None:
    source = (
        REPO_ROOT / "src/comprehension_verification/phase9_protocol.py"
    ).read_text(encoding="utf-8")
    # Documentation URLs mention openai.com; what must be absent is any means
    # of actually reaching a provider.
    for forbidden in (
        "import openai",
        "from openai",
        "import httpx",
        "import requests",
        "AsyncOpenAI",
        "responses.create",
        "urllib",
        "socket",
    ):
        assert forbidden not in source
    imports = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith("import ")
    }
    assert imports <= {"json"}


# --- AD: historical qualifications ----------------------------------------


def test_ad_historical_qualification_not_read_by_selection_logic(protocol) -> None:
    policy = protocol["historical_qualification_policy"]
    assert policy["status"] == "HISTORICAL_NON_CANONICAL_EVIDENCE"
    assert policy["used_for_candidate_selection"] is False
    assert policy["used_for_threshold_derivation"] is False
    assert policy["used_for_reasoning_selection"] is False
    source = (
        REPO_ROOT / "src/comprehension_verification/phase9_protocol.py"
    ).read_text(encoding="utf-8")
    # The module must not reach into any historical qualification report.
    assert "reports/openai" not in source
    assert "stage2_" not in source
    assert "qualification_v1" not in source


# --- AE: cross-process determinism ----------------------------------------


def test_ae_protocol_boundary_is_deterministic_in_process(protocol) -> None:
    assert protocol_boundary_hash(protocol) == protocol_boundary_hash(build_protocol())


def test_ae2_protocol_boundary_is_deterministic_cross_process(protocol) -> None:
    script = (
        "import sys; sys.path.insert(0, 'src');"
        "from comprehension_verification.phase9_protocol import"
        " build_protocol, protocol_boundary_hash;"
        "print(protocol_boundary_hash(build_protocol()))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "random"},
    )
    assert completed.stdout.strip() == protocol_boundary_hash(protocol)


# --- Emitted artifacts stay in sync ---------------------------------------


def test_emitted_artifacts_match_the_module(protocol) -> None:
    assert _read(PROTOCOL_DIR / "candidate_matrix.json") == protocol["candidate_matrix"]
    assert _read(PROTOCOL_DIR / "safety_gate.json") == protocol["safety_gate"]
    assert (
        _read(PROTOCOL_DIR / "qualification_thresholds.json")
        == protocol["qualification_thresholds"]
    )
    assert _read(PROTOCOL_DIR / "budget_plan.json") == protocol["budget_plan"]
    assert _read(PROTOCOL_DIR / "pricing_snapshot.json") == protocol["pricing_snapshot"]
    assert (
        _read(PROTOCOL_DIR / "adjudication_protocol.json")
        == protocol["adjudication_protocol"]
    )
    assert _read(PROTOCOL_DIR / "execution_plan.json") == protocol["execution_plan"]


@pytest.mark.parametrize(
    "artifact,schema",
    [
        ("candidate_matrix.json", "frozen_candidate_matrix.schema.json"),
        ("qualification_thresholds.json", "qualification_thresholds.schema.json"),
        ("safety_gate.json", "safety_gate.schema.json"),
        ("pricing_snapshot.json", "pricing_snapshot.schema.json"),
        ("budget_plan.json", "budget_plan.schema.json"),
    ],
)
def test_emitted_artifacts_validate_against_their_schemas(
    artifact: str, schema: str
) -> None:
    validator = Draft202012Validator(_read(PROTOCOL_DIR / "schemas" / schema))
    validator.validate(_read(PROTOCOL_DIR / artifact))


def test_every_phase9_schema_is_itself_valid() -> None:
    for path in sorted((PROTOCOL_DIR / "schemas").glob("*.schema.json")):
        Draft202012Validator.check_schema(_read(path))


def test_adjudication_decision_schema_rejects_a_low_confidence_failure() -> None:
    validator = Draft202012Validator(
        _read(PROTOCOL_DIR / "schemas/adjudication_decision.schema.json")
    )
    decision = {
        "schema_version": "phase9-adjudication-decision/1.0.0",
        "packet_hash": "sha256:" + "0" * 64,
        "property_id": "A01-ACT-P1",
        "decision": "MODEL_FAILURE",
        "confidence": "MEDIUM",
        "source_findings": [{"source_ref": "rubric#1", "finding": "x"}],
        "candidate_output_findings": ["y"],
        "defensible_alternative_considered": True,
        "oracle_problem_detected": False,
        "model_failure_requirements": {
            key: True
            for key in _read(PROTOCOL_DIR / "schemas/adjudication_decision.schema.json")[
                "properties"
            ]["model_failure_requirements"]["required"]
        },
        "rationale": "z",
    }
    assert not validator.is_valid(decision)
    decision["confidence"] = "HIGH"
    validator.validate(decision)


def test_consolidation_schema_rejects_failure_without_two_high_confidence_passes() -> None:
    validator = Draft202012Validator(
        _read(PROTOCOL_DIR / "schemas/failure_consolidation.schema.json")
    )
    record = {
        "schema_version": "phase9-failure-consolidation/1.0.0",
        "packet_hash": "sha256:" + "1" * 64,
        "property_id": "A01-ACT-P1",
        "first_pass": {
            "decision": "MODEL_FAILURE",
            "confidence": "HIGH",
            "packet_result_hash": "sha256:" + "2" * 64,
            "saw_other_pass": False,
        },
        "second_pass": {
            "decision": "PASS",
            "confidence": "HIGH",
            "packet_result_hash": "sha256:" + "3" * 64,
            "saw_other_pass": False,
        },
        "source_reasons_compatible": False,
        "diagnostic": "MODEL_FAILURE_CONFIRMED",
        "result_state": "MODEL_FAILURE",
        "consolidator": "DETERMINISTIC_RULE_TABLE_NO_MODEL",
    }
    assert not validator.is_valid(record)
    record["diagnostic"] = "ADJUDICATION_DISAGREEMENT"
    record["result_state"] = "PENDING_ADJUDICATION"
    validator.validate(record)


def test_freeze_report_records_the_boundary(protocol) -> None:
    report = _read(REPORT_DIR / "protocol_freeze_report.json")
    assert report["phase9_protocol_boundary_hash"] == protocol_boundary_hash(protocol)
    assert report["candidate_matrix_status"] == "FROZEN"
    assert report["authorization"] == "NONE"
    assert report["provider_calls"] == 0
    assert report["billable_authorizations"] == 0
    assert report["adjudicator_calls"] == 0
    assert report["readiness"] == "PHASE9_PROTOCOL_READY_FOR_EXECUTION"


def test_no_real_output_reports_are_emitted() -> None:
    for path in REPORT_DIR.glob("*.json"):
        payload = _read(path)
        encoded = json.dumps(payload)
        assert "candidate_output" not in encoded
        assert '"results"' not in encoded
    plan = _read(REPORT_DIR / "candidate_comparison_plan.json")
    assert plan["results_present"] is False


# --- Validation refuses violations ---------------------------------------


def test_validate_protocol_accepts_the_frozen_protocol(protocol) -> None:
    validate_protocol(protocol)


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda p: p.__setitem__("authorization", "GRANTED"), "PHASE9_AUTHORIZATION_NOT_NONE"),
        (lambda p: p.__setitem__("provider_calls", 1), "PHASE9_PROVIDER_CALLS_NOT_ZERO"),
        (
            lambda p: p["candidate_matrix"]["candidates"][0].__setitem__("model", "gpt-4o"),
            "PHASE9_UNVERIFIED_MODEL_ID",
        ),
        (
            lambda p: p["execution_plan"]["retry_policy"].__setitem__(
                "semantic_retry_allowed", True
            ),
            "PHASE9_SEMANTIC_RETRY_ALLOWED",
        ),
        (
            lambda p: p["execution_plan"]["k"].__setitem__("semantic", 1),
            "PHASE9_K_DRIFT",
        ),
        (
            lambda p: p["execution_plan"].__setitem__("early_success_stop_allowed", True),
            "PHASE9_EARLY_SUCCESS_STOP",
        ),
        (
            lambda p: p["execution_plan"]["promotion"].__setitem__(
                "held_out_multi_candidate_allowed", True
            ),
            "PHASE9_HELD_OUT_MULTI_CANDIDATE",
        ),
        (
            lambda p: p["budget_plan"].__setitem__("billable_authorization_created", True),
            "PHASE9_BILLABLE_AUTHORIZATION_CREATED",
        ),
        (
            lambda p: p["pricing_snapshot"].__setitem__(
                "official_source", "https://example.invalid/prices"
            ),
            "PHASE9_PRICING_SOURCE_NOT_OFFICIAL",
        ),
        (
            lambda p: p["pricing_snapshot"].__setitem__(
                "copied_from_repository_history", True
            ),
            "PHASE9_PRICING_FROM_HISTORY",
        ),
    ],
)
def test_validate_protocol_rejects_violations(mutation, code) -> None:
    protocol = build_protocol()
    mutation(protocol)
    with pytest.raises(Phase9ProtocolError) as excinfo:
        validate_protocol(protocol)
    assert excinfo.value.code == code


def test_validate_protocol_rejects_a_loosened_threshold() -> None:
    protocol = build_protocol()
    row = next(
        entry
        for entry in protocol["qualification_thresholds"]["thresholds"]
        if entry["stage"] == "P06" and entry["split"] == "CORE"
    )
    row["max_confirmed_model_failures"] = 4
    with pytest.raises(Phase9ProtocolError) as excinfo:
        validate_protocol(protocol)
    assert excinfo.value.code == "PHASE9_THRESHOLD_ROUNDING_INVALID"


def test_validate_protocol_rejects_a_duplicate_candidate() -> None:
    protocol = build_protocol()
    candidates = protocol["candidate_matrix"]["candidates"]
    clone = dict(candidates[0])
    clone["candidate_id"] = "P04-C9-LUNA-HIGH"
    candidates.append(clone)
    with pytest.raises(Phase9ProtocolError) as excinfo:
        validate_protocol(protocol)
    assert excinfo.value.code == "PHASE9_DUPLICATE_CANDIDATE"


def test_validate_protocol_rejects_too_many_candidates() -> None:
    protocol = build_protocol()
    protocol["candidate_matrix"]["candidates"].append(
        {
            "candidate_id": "P04-C4-TERRA-XHIGH",
            "stage": "P04",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "XHIGH",
            "max_output_tokens": 16_000,
            "route_profile_id": "TERRA_XHIGH_V1",
            "promotion_order": 4,
            "hypothesis": "extra",
        }
    )
    with pytest.raises(Phase9ProtocolError) as excinfo:
        validate_protocol(protocol)
    assert excinfo.value.code == "PHASE9_TOO_MANY_CANDIDATES"


def test_candidate_adjudicator_family_never_overlaps(protocol) -> None:
    adjudicator = protocol["adjudication_protocol"]["adjudicator"]
    assert adjudicator["adjudicator_model"] == "OPUS_5"
    assert adjudicator["candidate_may_judge_own_output"] is False
    assert adjudicator["candidate_adjudicator_family_overlap"] is False
    for candidate in protocol["candidate_matrix"]["candidates"]:
        assert candidate["model"].startswith("gpt-")


def test_oracle_lineage_limitation_is_disclosed(protocol) -> None:
    adjudicator = protocol["adjudication_protocol"]["adjudicator"]
    assert adjudicator["adjudicator_type"] == "MODEL_ADJUDICATOR"
    assert adjudicator["adjudicator_is_human"] is False
    assert (
        adjudicator["oracle_lineage"]
        == "INDEPENDENT_MODEL_RATIFICATION_DERIVED_FROM_OPUS5"
    )
    assert adjudicator["independence_level"] == "SAME_MODEL_FAMILY_SEPARATE_CONTEXT"
    assert "share a model" in adjudicator["disclosed_limitation"]
    assert "WORDING_SIMILARITY" in adjudicator["prohibited_signals"]


def test_oracle_stays_frozen_during_a_run(protocol) -> None:
    policy = protocol["adjudication_protocol"]["oracle_policy"]
    assert policy["oracle_frozen_during_qualification"] is True
    assert policy["editable_during_run"] == []
    assert policy["review_timing"] == "POST_RUN_ONLY"
    assert "final_ratification" in policy["forbidden_edits"]
    assert "cannot retroactively rescue" in policy["post_run_change_consequence"]


def test_early_stop_rules_cover_the_required_conditions(protocol) -> None:
    codes = {rule["code"] for rule in protocol["execution_plan"]["early_stop_rules"]}
    assert {
        "HARD_SAFETY_FAILURE_CONFIRMED",
        "DETERMINISTIC_HARD_GATE_FAILED",
        "RULE_BASED_HARD_GATE_FAILED",
        "THRESHOLD_MATHEMATICALLY_UNREACHABLE",
        "TECHNICAL_FAILURE_RATE_OVER_CAP",
        "ADJUDICATION_SYSTEM_INSTABILITY",
        "BUDGET_CAP_WOULD_BE_EXCEEDED",
    } <= codes
    assert protocol["execution_plan"]["early_success_stop_allowed"] is False


def test_promotion_blocks_on_pending_adjudication(protocol) -> None:
    promotion = protocol["execution_plan"]["promotion"]
    assert promotion["pending_adjudication_blocks_promotion"] is True
    assert "incomplete scoreboard" in promotion["pending_adjudication_rule"]
    assert tuple(promotion["ladder"]) == ("SMOKE", "CORE", "HELD_OUT_CONFIRMATION")
    assert promotion["skipping_rungs_allowed"] is False
    assert promotion["stage_winners_may_differ"] is True


def test_adjudication_load_distinguishes_packets_from_cases(protocol) -> None:
    load = build_adjudication_load(load_benchmark_facts())
    assert load["unit"] == "PROPERTY_ADJUDICATION_PACKET"
    assert load["benchmark_external_adjudication_property_total"] == 358
    assert load["case_bound_external_valid_property_total"] == 304
    assert load["totals"]["first_pass_adjudications_worst_case"] > 0
    for row in load["rows"]:
        if row["split"] == "HELD_OUT_CONFIRMATION":
            assert row["candidates_running_worst_case"] == 1
