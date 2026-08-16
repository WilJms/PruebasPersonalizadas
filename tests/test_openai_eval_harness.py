from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from pydantic import SecretStr
import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.contracts import models as m
from comprehension_verification.evaluation_gate import (
    EvaluationAuthorizationConsumed,
    EvaluationAuthorizationLedger,
)
from comprehension_verification.model_gateway import (
    DeterministicMockAdapter,
    MockBehavior,
    OPENAI_MAX_PROMPT_IDS,
    OPENAI_MAX_ROUTE_PROFILE_ID,
    OPENAI_ROUTE_PROFILE_ID,
    OPENAI_SOL_HIGH_PROMPT_IDS,
    OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
    OPENAI_SOL_MEDIUM_PROMPT_IDS,
    OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
    OPENAI_SOL_XHIGH_PROMPT_IDS,
    OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_HIGH_PROMPT_IDS,
    OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_XHIGH_PROMPT_IDS,
    OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_MEDIUM_PROMPT_IDS,
    OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
    OPENAI_XHIGH_PROMPT_IDS,
    OPENAI_XHIGH_ROUTE_PROFILE_ID,
)
from comprehension_verification.rehearsal import (
    BASE_SCENARIO_ID,
    P05_GOLDEN_FIXTURE_PATH,
    QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
    VARIANT_SCENARIO_ID,
    build_p05_golden_negative_request,
    build_rehearsal_checkpoints,
    evaluate_p05_golden_negative,
    evaluate_p05_golden_positive,
    p08_decision_diagnostics,
    rehearsal_boundary_material,
    run_offline_convergence,
    run_real_convergence,
    sol_high_budget_derivation,
    sol_medium_budget_derivation,
    sol_xhigh_budget_derivation,
    terra_high_budget_derivation,
    terra_medium_budget_derivation,
    terra_xhigh_budget_derivation,
)
from comprehension_verification.qualification_semantics import (
    CheckpointClass,
    ContractualAdherence,
    OracleValidity,
    SemanticInterpretation,
    classify_checkpoint,
)
from comprehension_verification.semantic_harness import (
    build_reviewed_semantic_adapter,
)
from scripts import run_openai_evals as eval_harness


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_openai_evals.py"
FIXTURE = (
    ROOT
    / "tests/fixtures/openai_evals/v2/product_rehearsal.json"
)

_SEMANTIC_PROMPT_FIELDS = {
    "version",
    "hash",
    "input_schema_hash",
    "output_schema_hash",
    "provider_output_schema_version",
    "provider_output_schema_hash",
    "relationship_validator",
    "application_validator",
}
_P04_INTENTIONAL_BOUNDARY_DELTA = {
    "version",
    "hash",
    "input_schema_hash",
    "provider_output_schema_version",
    "provider_output_schema_hash",
    "relationship_validator",
}
_P06_INTENTIONAL_BOUNDARY_DELTA = {
    "version",
    "hash",
    "output_schema_hash",
    "provider_output_schema_version",
    "provider_output_schema_hash",
    "relationship_validator",
    "application_validator",
}
_P07_INTENTIONAL_BOUNDARY_DELTA = {
    "version",
    "hash",
    "input_schema_hash",
    "provider_output_schema_version",
    "provider_output_schema_hash",
    "relationship_validator",
    "application_validator",
}


def _assert_p04_contract_boundary_delta(
    *,
    current: dict[str, object],
    historical: dict[str, object],
    prompt_ids: set[str] | frozenset[str],
) -> None:
    for prompt_id in sorted(prompt_ids):
        current_row = current[prompt_id]
        historical_row = historical[prompt_id]
        assert isinstance(current_row, dict)
        assert isinstance(historical_row, dict)
        changed = {
            key
            for key in _SEMANTIC_PROMPT_FIELDS
            if current_row.get(key) != historical_row.get(key)
        }
        if prompt_id == "P04_BLUEPRINT_BUILD_V1":
            assert changed == _P04_INTENTIONAL_BOUNDARY_DELTA
            assert current_row["version"] == "1.1.12"
            assert current_row["relationship_validator"] == (
                "relationship-p04/3.0.0"
            )
            assert current_row["provider_output_schema_version"] == (
                m.SCHEMA_VERSION
            )
            assert str(current_row["provider_output_schema_hash"]).startswith(
                "sha256:"
            )
        elif prompt_id == "P05_BLUEPRINT_REVIEW_V1":
            # P05 is inactive but its retained request embeds BlueprintPolicy,
            # whose new catalog caps are backward-compatible defaults.
            assert changed == {"input_schema_hash"}
        elif prompt_id == "P06_EVIDENCE_MAP_V1":
            assert changed == _P06_INTENTIONAL_BOUNDARY_DELTA
            assert current_row["version"] == "1.1.6"
            assert current_row["relationship_validator"] == (
                "relationship-p06/3.0.0"
            )
            assert current_row["application_validator"] == (
                "application-validator-p06/3.0.0"
            )
            assert current_row["provider_output_schema_version"] == (
                m.SCHEMA_VERSION
            )
        elif prompt_id == "P07_QUESTION_BUILD_V1":
            assert changed == _P07_INTENTIONAL_BOUNDARY_DELTA
            assert current_row["version"] == "1.1.5"
            assert current_row["relationship_validator"] == (
                "relationship-p07/3.0.0"
            )
            assert current_row["application_validator"] == (
                "application-validator-p07/3.0.0"
            )
            assert current_row["provider_output_schema_version"] == (
                m.SCHEMA_VERSION
            )
        elif prompt_id == "P08_QUESTION_REVIEW_V1":
            # P08 is retained only as frozen historical harness evidence. Its
            # prompt/input adapt mechanically so
            # support evidence and the visible anchor remain distinct.
            assert changed == {"hash", "input_schema_hash"}
        else:
            assert changed == set()


def _reviewed_sol_candidate_delta_proof() -> dict[str, object]:
    observed = sorted(eval_harness.SOL_ALLOWED_DELTA_PATHS)
    return {
        "baseline_sha": eval_harness.SOL_LADDER_BASELINE_SHA,
        "observed_delta": observed,
        "allowed_delta": observed,
        "forbidden_delta": [],
        "allowed_paths": observed,
    }


@pytest.fixture
def reviewed_sol_candidate_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep unit tests independent from the checkout's Git history depth."""

    monkeypatch.setattr(
        eval_harness,
        "_sol_candidate_delta_proof",
        _reviewed_sol_candidate_delta_proof,
    )


def _safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("CVA_OPENAI_") or name in {
            "OPENAI_API_KEY",
            "OPENAI_ORG_ID",
            "OPENAI_PROJECT_ID",
        }:
            environment.pop(name, None)
    return environment


def test_golden_set_runs_offline_without_network_or_cost() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["network_calls"] == report["billable_calls"] == 0
    assert all(row["status"] == "PASS" for row in report["cases"])


@pytest.mark.parametrize(
    "mode",
    [
        "real",
        "canary-real",
        "blueprint-recanary-real",
        "blueprint-timeout-recovery-real",
        "qualification-real",
    ],
)
def test_historical_billable_gates_are_permanently_closed(mode: str) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            mode,
            "--allow-billable",
            "--max-total-cost-usd",
            "1",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "status": "BLOCKED",
        "code": "OPENAI_HISTORICAL_EVAL_GATE_CLOSED",
        "network_calls": 0,
    }


def test_product_rehearsal_fixture_is_synthetic_and_versioned() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert raw["schema_version"] == (
        "stage2-product-rehearsal-fixture/1.5.0"
    )
    assert raw["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    assert raw["p05_golden_fixture"] == (
        "tests/fixtures/openai_evals/v2/p05_golden_checkpoints.json"
    )
    assert raw["instrument_semantic_status"] == (
        "LEGACY_INVALIDATED_NOT_AUTHORIZED_FOR_SEMANTIC_QUALIFICATION"
    )
    assert raw["replacement_fixture"] == (
        "tests/fixtures/openai_evals/v3/semantic_qualification_pack.json"
    )
    assert set(raw["checkpoints"]) == {"A", "B", "C", "D"}
    assert [item["scenario_id"] for item in raw["scenarios"]] == [
        BASE_SCENARIO_ID,
        VARIANT_SCENARIO_ID,
    ]
    assert all(value is False for value in raw["invariants"].values())
    assert raw["integrated_submission_shape"] == {
        "evidence_units": 3,
        "artifacts": 2,
        "data_classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
    }
    assert raw["execution_discovery"] == {
        "independent_sweep_stages": [
            {
                "stage": stage,
                "checkpoint_class": (
                    "STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY"
                ),
            }
            for stage in ("P04", "P05", "P06", "P07", "P08", "P09")
        ],
        "p06_receives_planning_policy": True,
        "failures_are_content_free": True,
        "semantic_quality_conclusions_allowed": False,
    }


def test_p05_golden_positive_is_semantically_qualified_and_negative_is_known() -> None:
    raw = json.loads(P05_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "stage2-p05-golden-checkpoints/1.2.0"
    assert raw["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    semantic_review = raw["golden_positive"]["semantic_review"]
    assert semantic_review["status"] == "SEMANTICALLY_QUALIFIED_POSITIVE"
    assert semantic_review["independent_of_provider_response"] is True
    assert set(semantic_review["category_reviews"]) == {
        "CONSTRUCT",
        "SOURCE_FIDELITY",
        "COVERAGE",
        "COMPARABILITY",
        "COGNITIVE_DEMAND",
        "TIME",
        "FORMAT_FEASIBILITY",
        "OPPORTUNITY_CATALOG",
        "PLAN_FEASIBILITY",
        "ACCESSIBILITY",
    }
    assert len(semantic_review["rationale"]) >= 5

    positive = build_rehearsal_checkpoints(BASE_SCENARIO_ID).p05_request
    assert m.AssessmentBlueprint.model_validate(positive.blueprint)
    assert all(
        value is not False
        for key, value in positive.deterministic_preflight.model_dump(
            mode="json"
        ).items()
        if key not in {"blueprint_id", "blueprint_version", "schema_version"}
    )
    assert positive.blueprint.dimensions[0].name == (
        "Explicación causal de la invalidación de caché"
    )
    assert positive.rubric_spec is not None
    assert positive.rubric_spec.criteria[0].grading_weight == 1.0
    assert positive.blueprint.dimensions[0].grading_weight == 1.0
    positive_result = evaluate_p05_golden_positive()
    assert positive_result["status"] == "PASS"
    assert positive_result["expected_transition"] == "APPROVABLE"
    assert positive_result["actual_transition"] == "APPROVABLE"
    assert positive_result["actual_status"] == "READY"
    assert positive_result["critical_categories"] == []
    assert positive_result["actual_recommendation"] != "REJECT"
    assert positive_result["product_validator_status"] == "PASS"
    assert positive_result["provider_requests"] == 0

    negative = build_p05_golden_negative_request()
    assert negative.deterministic_preflight.policy_constraints_match is False
    assert negative.deterministic_preflight.catalog_plan_feasible is False
    result = evaluate_p05_golden_negative()
    assert result["status"] == "PASS"
    assert result["actual_recommendation"] == "REJECT"
    assert result["critical_categories"] == ["PLAN_FEASIBILITY"]
    assert result["actual_deterministic_checks"] == {
        "COVERAGE": {"status": "PASS", "critical": False},
        "TIME": {"status": "PASS", "critical": False},
        "FORMAT_FEASIBILITY": {"status": "PASS", "critical": False},
        "OPPORTUNITY_CATALOG": {"status": "PASS", "critical": False},
        "PLAN_FEASIBILITY": {"status": "FAIL", "critical": True},
    }
    assert (
        result["actual_deterministic_checks"]
        == result["expected_deterministic_checks"]
        == result["product_expected_deterministic_checks"]
    )
    assert result["product_validator_status"] == "PASS"
    assert result["provider_requests"] == 0


@pytest.mark.parametrize(
    "scenario_id", [BASE_SCENARIO_ID, VARIANT_SCENARIO_ID]
)
def test_product_checkpoints_validate_as_canonical_roots(
    scenario_id: str,
) -> None:
    checkpoints = build_rehearsal_checkpoints(scenario_id)
    assert m.BlueprintBuildRequest.model_validate(checkpoints.p04_request)
    assert m.EvidenceMapRequest.model_validate(checkpoints.p06_request)
    assert m.QuestionBuildRequest.model_validate(checkpoints.p07_request)
    assert m.QuestionReviewRequest.model_validate(checkpoints.p08_request)
    assert m.GuideBuildRequest.model_validate(checkpoints.p09_request)
    assert len(checkpoints.p06_request.evidence_bundle.evidence_units) == 3
    assert len(
        {
            item.artifact_id
            for item in checkpoints.p06_request.evidence_bundle.evidence_units
        }
    ) == 2
    assert set(checkpoints.hashes) == {
        "post_p03",
        "blueprint_valid",
        "mapping_planning_valid",
        "assessment_valid",
    }


def test_relevant_variant_changes_the_checkpoint_boundary() -> None:
    base = build_rehearsal_checkpoints(BASE_SCENARIO_ID)
    variant = build_rehearsal_checkpoints(VARIANT_SCENARIO_ID)
    assert base.hashes["post_p03"] != variant.hashes["post_p03"]
    assert base.p04_request.blueprint_policy.allowed_response_formats == [
        m.ResponseFormat.OPEN_SHORT
    ]
    assert variant.p04_request.blueprint_policy.allowed_response_formats == [
        m.ResponseFormat.CHOICE
    ]
    assert (
        variant.p04_request.blueprint_policy.structured_justification_policy.mode
        == m.StructuredJustificationMode.ALL
    )


def test_p08_decision_diagnostics_are_content_free_and_reproducible() -> None:
    checkpoint = build_rehearsal_checkpoints(BASE_SCENARIO_ID)
    adapter = DeterministicMockAdapter()
    accepted = m.QuestionReviewResult.model_validate(
        adapter.factory.output_for(
            "P08_QUESTION_REVIEW_V1",
            checkpoint.p08_request,
            MockBehavior.HAPPY,
        ).model_dump(mode="json")
    )
    accepted_metadata = p08_decision_diagnostics(
        accepted, checkpoint.p08_request.validation_policy
    )
    assert accepted_metadata["decision"] == "ACCEPT"
    assert accepted_metadata["criticality"] == "NON_CRITICAL"
    assert accepted_metadata["diagnostic_codes"] == [
        "P08_DECISION_ACCEPT"
    ]
    assert all(
        item["relation"] == "AT_OR_ABOVE"
        for item in accepted_metadata["score_thresholds"].values()
    )

    rejected_raw = accepted.model_dump(mode="json")
    rejected_raw["review"]["decision"] = "REJECT"
    rejected_raw["review"]["critical_failure_codes"] = ["UNGROUNDED"]
    rejected_raw["review"]["scores"]["groundedness"] = 0.4
    rejected_raw["review"]["confidence"] = 0.5
    rejected = m.QuestionReviewResult.model_validate(rejected_raw)
    rejected_metadata = p08_decision_diagnostics(
        rejected, checkpoint.p08_request.validation_policy
    )
    serialized = json.dumps(rejected_metadata, sort_keys=True)
    assert rejected_metadata["decision"] == "REJECT"
    assert rejected_metadata["criticality"] == "CRITICAL"
    assert rejected_metadata["score_thresholds"]["groundedness"] == {
        "score": 0.4,
        "threshold": 0.9,
        "relation": "BELOW",
    }
    assert rejected_metadata["failure_categories"] == [
        "GROUNDEDNESS_BELOW_THRESHOLD",
        "CONFIDENCE_BELOW_THRESHOLD",
        "MODEL_DECLARED_CRITICAL_FAILURE",
    ]
    assert "UNGROUNDED" not in serialized
    assert rejected_metadata["provider_critical_code_hashes"][0].startswith(
        "sha256:"
    )

    escalated_raw = accepted.model_dump(mode="json")
    escalated_raw["review"]["decision"] = "ESCALATE"
    escalated_raw["review"]["confidence"] = 0.5
    escalated = m.QuestionReviewResult.model_validate(escalated_raw)
    escalated_metadata = p08_decision_diagnostics(
        escalated, checkpoint.p08_request.validation_policy
    )
    assert escalated_metadata["decision"] == "ESCALATE"
    assert escalated_metadata["criticality"] == "NON_CRITICAL"
    assert escalated_metadata["failure_categories"] == [
        "CONFIDENCE_BELOW_THRESHOLD"
    ]
    assert escalated_metadata["diagnostic_codes"] == [
        "P08_DECISION_ESCALATE",
        "P08_CONFIDENCE_BELOW_THRESHOLD",
    ]


def test_offline_convergence_executes_semantic_sweep_and_four_chains() -> None:
    report = asyncio.run(run_offline_convergence())
    assert report["status"] == "PASS"
    assert [item["run_id"] for item in report["observations"]] == [
        "sweep-base",
        "chain-base-1",
        "chain-base-2",
        "chain-choice-variant",
        "chain-canonical-document-sufficient",
    ]
    assert all(item["status"] == "PASS" for item in report["observations"])
    semantic_sweep = report["observations"][0]
    assert semantic_sweep["run_kind"] == "SEMANTIC_QUALIFICATION_SWEEP"
    assert len(semantic_sweep["checkpoint_assessments"]) == 9
    assert report["causal_classification"] == "QUALIFICATION_PASSED"
    for stage in semantic_sweep["stages"]:
        assert stage["checkpoint_class"].startswith("SEMANTICALLY_QUALIFIED_")
        assert stage["review_hash"].startswith("sha256:")
        assert stage["fixture_hash"].startswith("sha256:")
        assert stage["golden_hash"].startswith("sha256:")
        assert stage["operational_outcome"] == "PASS"
        assert stage["semantic_interpretation"] == "CORRECT"
        assert stage["contractual_adherence"] == "PASS"
    assert [len(item["stages"]) for item in report["observations"]] == [
        9,
        8,
        8,
        8,
        8,
    ]
    assert report["transport_provenance"] == {
        "provider_transport_constructed": False,
        "reviewed_semantic_oracle_invocations": 9,
        "structural_transport_substitute_invocations": 24,
        "semantic_sweep_response_origin": "REVIEWED_SEMANTIC_ORACLE",
        "integrated_chain_response_origin": (
            "STRUCTURAL_TRANSPORT_SUBSTITUTE"
        ),
        "integrated_chain_semantic_quality_conclusion_allowed": False,
    }
    assert report["controls"] == {
        "p10_calls": 0,
        "p11_calls": 0,
        "fallback_calls": 0,
        "semantic_retries": 0,
        "provider_attempts": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        "actual_cost_usd": 0.0,
        "budget_charged_usd": 0.0,
        "unpriced_attempts": 0,
        "models": [
            "deterministic-mock-p04_blueprint_build_v1",
            "deterministic-mock-p05_blueprint_review_v1",
            "deterministic-mock-p06_evidence_map_v1",
            "deterministic-mock-p07_question_build_v1",
            "deterministic-mock-p08_question_review_v1",
            "deterministic-mock-p09_guide_build_v1",
        ],
    }


def test_convergence_cli_dry_run_is_content_free_and_non_billable() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "convergence-dry-run"],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    serialized = json.dumps(report, sort_keys=True)
    assert report["status"] == "PASS"
    assert report["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    assert report["controls"]["actual_cost_usd"] == 0.0
    assert "OPENAI_API_KEY" not in serialized
    assert "content_text" not in serialized
    assert "question_text" not in serialized


def test_xhigh_offline_qualification_is_exact_and_non_billable() -> None:
    report = asyncio.run(
        run_offline_convergence(
            route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        )
    )
    controls = report["controls"]
    assert report["status"] == "PASS"
    assert report["route_profile"] == "LUNA_XHIGH_V1"
    assert report["execution_sequence"] == [
        "semantic-sweep:P04-P09:versioned-positive-and-negative",
        "offline-golden-positive:P05",
        "offline-golden-negative:P05",
        "integrated-chain:base:1:P04-P09",
        "integrated-chain:base:2:P04-P09",
        "integrated-chain:choice-variant:P04-P09",
        "integrated-chain:canonical-document-sufficient:P04-P09",
    ]
    assert [item["status"] for item in report["observations"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert [len(item["stages"]) for item in report["observations"]] == [
        9,
        8,
        8,
        8,
        8,
    ]
    assert all(
        check["status"] == "PASS" and check["provider_requests"] == 0
        for check in report["deterministic_checks"]
    )
    assert controls["network_calls"] == 0
    assert controls["provider_attempts"] == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    assert controls["simulated_provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert controls["models"] == ["gpt-5.6-luna"]
    assert controls["reasoning_efforts_by_prompt"] == {
        prompt_id: ["XHIGH"]
        for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS)
    }
    assert controls["p10_calls"] == 0
    assert controls["p11_calls"] == 0
    assert controls["fallback_calls"] == 0
    assert controls["gateway_retries"] == 0
    assert controls["sdk_retries"] == 0
    assert controls["semantic_retries"] == 0
    assert controls["tools_enabled"] is False
    assert controls["store"] is False
    assert controls["semantic_normalizations"] == 0
    assert controls["fixture_changes"] == 0
    assert controls["prompt_changes"] == 0
    assert controls["validator_changes"] == 0
    assert controls["budget_charged_usd"] == pytest.approx(0.648857)
    assert controls["max_observed_budget_charge_usd"] == pytest.approx(
        0.02496675
    )
    assert controls["budget_charged_usd"] <= controls["max_total_cost_usd"]
    assert controls["max_observed_budget_charge_usd"] <= (
        controls["max_call_cost_usd"]
    )


def test_xhigh_cli_dry_run_has_zero_network_and_no_secret_surface() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "xhigh-qualification-dry-run",
            "--max-total-cost-usd",
            "0.75",
            "--max-call-cost-usd",
            "0.10",
            "--max-provider-requests",
            "33",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    serialized = json.dumps(report, sort_keys=True)
    assert report["status"] == "PASS"
    assert report["route_profile"] == "LUNA_XHIGH_V1"
    assert report["controls"]["network_calls"] == 0
    assert "OPENAI_API_KEY" not in serialized
    assert "content_text" not in serialized
    assert "question_text" not in serialized


def test_xhigh_boundary_preserves_product_semantics_and_records_harness_delta() -> None:
    baseline_report = json.loads(
        eval_harness.XHIGH_QUALIFICATION_BASELINE_REPORT.read_text(
            encoding="utf-8"
        )
    )
    high = baseline_report["boundary"]
    xhigh = rehearsal_boundary_material(
        OPENAI_XHIGH_ROUTE_PROFILE_ID,
        max_call_cost_usd=0.10,
    )
    assert xhigh["prompt_pack_version"] == "1.1.16"
    assert high["prompt_pack_version"] == "1.1.14"
    assert xhigh["planner_version"] == "stage2-planner/3.0.0"
    assert high["planner_version"] == "stage2-planner/2.0.0"
    assert xhigh["assembler_version"] == high["assembler_version"]
    assert high["p05_golden"]["fixture_version"] == (
        "stage2-p05-golden-checkpoints/1.1.0"
    )
    assert xhigh["p05_golden"]["fixture_version"] == (
        "stage2-p05-golden-checkpoints/1.2.0"
    )
    assert xhigh["p05_golden"]["negative_expected_recommendation"] == (
        high["p05_golden"]["negative_expected_recommendation"]
    )
    assert xhigh["p05_golden"]["negative_expected_critical_categories"] == (
        high["p05_golden"]["negative_expected_critical_categories"]
    )
    for scenario_id in high["checkpoints"]:
        assert {
            key
            for key in high["checkpoints"][scenario_id]
            if high["checkpoints"][scenario_id][key]
            != xhigh["checkpoints"][scenario_id][key]
        } == {"post_p03", "blueprint_valid", "mapping_planning_valid"}
    _assert_p04_contract_boundary_delta(
        current=xhigh["prompts"],
        historical=high["prompts"],
        prompt_ids=OPENAI_XHIGH_PROMPT_IDS,
    )
    for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS):
        assert xhigh["prompts"][prompt_id][
            "registry_reasoning_effort"
        ] == "HIGH"
        assert xhigh["prompts"][prompt_id][
            "route_reasoning_effort"
        ] == "XHIGH"

    delta = xhigh["route_delta_from_luna_baseline"]
    assert delta["baseline_route_profile"] == OPENAI_ROUTE_PROFILE_ID
    assert delta["selected_route_profile"] == OPENAI_XHIGH_ROUTE_PROFILE_ID
    assert delta["reasoning_effort_changes"] == {
        prompt_id: {"from": "HIGH", "to": "XHIGH"}
        for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS)
    }
    assert delta["other_route_field_changes"] == {}
    for unchanged_surface in (
        "prompt_registry_changes",
        "schema_changes",
        "validator_changes",
        "fixture_changes",
        "planner_changes",
        "assembler_changes",
    ):
        assert delta[unchanged_surface] == []
    route_boundary = xhigh["openai_route_boundary"]
    assert route_boundary["model_ids"] == ["gpt-5.6-luna"]
    assert route_boundary["route_profile"] == "LUNA_XHIGH_V1"
    assert {
        prompt_id: route_boundary["routes"][prompt_id][
            "reasoning_effort"
        ]
        for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS)
    } == {
        prompt_id: "XHIGH"
        for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS)
    }


def test_xhigh_authorization_boundary_seals_baseline_route_sdk_and_caps(
    tmp_path: Path,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "xhigh-qualification-real"
    boundary = eval_harness._convergence_authorization_boundary(args)
    assert boundary["git_head"]
    assert boundary["route_profile"] == "LUNA_XHIGH_V1"
    assert boundary["model_ids"] == ["gpt-5.6-luna"]
    assert boundary["qualified_reasoning_effort"] == {
        prompt_id: "XHIGH"
        for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS)
    }
    assert boundary["max_provider_requests"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert boundary["max_total_cost_usd"] == 0.75
    assert boundary["max_call_cost_usd"] == 0.10
    assert boundary["executable_boundary"]["openai_route_boundary"][
        "openai_sdk_version"
    ] == "2.53.0"
    assert boundary["xhigh_qualification_baseline"] == {
        "candidate_sha": eval_harness.XHIGH_QUALIFICATION_BASELINE_SHA,
        "evidence_sha": eval_harness.XHIGH_QUALIFICATION_EVIDENCE_SHA,
        "report_hash": (
            "sha256:"
            + hashlib.sha256(
                eval_harness.XHIGH_QUALIFICATION_BASELINE_REPORT.read_bytes()
            ).hexdigest()
        ),
        "route_profile": "LUNA_BASELINE_V1",
        "model": "gpt-5.6-luna",
        "reasoning_effort": "HIGH",
    }


def test_max_offline_qualification_is_exact_and_non_billable() -> None:
    report = asyncio.run(
        run_offline_convergence(
            route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        )
    )
    controls = report["controls"]
    assert report["status"] == "PASS"
    assert report["mode"] == "offline-max-qualification"
    assert report["route_profile"] == "LUNA_MAX_V1"
    assert [item["status"] for item in report["observations"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert [len(item["stages"]) for item in report["observations"]] == [
        9,
        8,
        8,
        8,
        8,
    ]
    assert all(
        check["status"] == "PASS" and check["provider_requests"] == 0
        for check in report["deterministic_checks"]
    )
    assert controls["network_calls"] == 0
    assert controls["provider_attempts"] == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    assert controls["simulated_provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert controls["models"] == ["gpt-5.6-luna"]
    assert controls["reasoning_efforts_by_prompt"] == {
        prompt_id: ["MAX"]
        for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS)
    }
    assert controls["p10_calls"] == 0
    assert controls["p11_calls"] == 0
    assert controls["fallback_calls"] == 0
    assert controls["gateway_retries"] == 0
    assert controls["sdk_retries"] == 0
    assert controls["semantic_retries"] == 0
    assert controls["tools_enabled"] is False
    assert controls["store"] is False
    assert controls["semantic_normalizations"] == 0
    assert controls["fixture_changes"] == 0
    assert controls["prompt_changes"] == 0
    assert controls["validator_changes"] == 0
    assert controls["budget_charged_usd"] == pytest.approx(0.6488405)
    assert controls["max_observed_budget_charge_usd"] == pytest.approx(
        0.02496625
    )
    assert controls["budget_charged_usd"] <= 0.75
    assert controls["max_observed_budget_charge_usd"] <= 0.10


def test_max_cli_dry_run_has_zero_network_and_no_secret_surface() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "max-qualification-dry-run",
            "--max-total-cost-usd",
            "0.75",
            "--max-call-cost-usd",
            "0.10",
            "--max-provider-requests",
            "33",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    serialized = json.dumps(report, sort_keys=True)
    assert report["status"] == "PASS"
    assert report["route_profile"] == "LUNA_MAX_V1"
    assert report["controls"]["network_calls"] == 0
    assert "OPENAI_API_KEY" not in serialized
    assert "content_text" not in serialized
    assert "question_text" not in serialized


def test_max_boundary_preserves_product_semantics_and_records_harness_delta() -> None:
    baseline_report = json.loads(
        eval_harness.MAX_QUALIFICATION_BASELINE_REPORT.read_text(
            encoding="utf-8"
        )
    )
    xhigh = baseline_report["boundary"]
    maximum = rehearsal_boundary_material(
        OPENAI_MAX_ROUTE_PROFILE_ID,
        max_call_cost_usd=0.10,
    )
    assert maximum["prompt_pack_version"] == "1.1.16"
    assert xhigh["prompt_pack_version"] == "1.1.14"
    assert maximum["planner_version"] == "stage2-planner/3.0.0"
    assert xhigh["planner_version"] == "stage2-planner/2.0.0"
    assert maximum["assembler_version"] == xhigh["assembler_version"]
    assert maximum["p05_golden"]["fixture_version"] == (
        "stage2-p05-golden-checkpoints/1.2.0"
    )
    assert xhigh["p05_golden"]["fixture_version"] == (
        "stage2-p05-golden-checkpoints/1.1.0"
    )
    assert maximum["p05_golden"]["negative_expected_recommendation"] == (
        xhigh["p05_golden"]["negative_expected_recommendation"]
    )
    for scenario_id in xhigh["checkpoints"]:
        assert {
            key
            for key in xhigh["checkpoints"][scenario_id]
            if xhigh["checkpoints"][scenario_id][key]
            != maximum["checkpoints"][scenario_id][key]
        } == {"post_p03", "blueprint_valid", "mapping_planning_valid"}
    _assert_p04_contract_boundary_delta(
        current=maximum["prompts"],
        historical=xhigh["prompts"],
        prompt_ids=OPENAI_MAX_PROMPT_IDS,
    )
    for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS):
        assert maximum["prompts"][prompt_id][
            "registry_reasoning_effort"
        ] == "HIGH"
        assert maximum["prompts"][prompt_id][
            "route_reasoning_effort"
        ] == "MAX"

    delta = maximum["route_delta_from_luna_xhigh"]
    assert delta["baseline_route_profile"] == OPENAI_XHIGH_ROUTE_PROFILE_ID
    assert delta["selected_route_profile"] == OPENAI_MAX_ROUTE_PROFILE_ID
    assert delta["reasoning_effort_changes"] == {
        prompt_id: {"from": "XHIGH", "to": "MAX"}
        for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS)
    }
    assert delta["other_route_field_changes"] == {}
    for unchanged_surface in (
        "prompt_registry_changes",
        "schema_changes",
        "validator_changes",
        "fixture_changes",
        "planner_changes",
        "assembler_changes",
    ):
        assert delta[unchanged_surface] == []
    route_boundary = maximum["openai_route_boundary"]
    assert route_boundary["model_ids"] == ["gpt-5.6-luna"]
    assert route_boundary["route_profile"] == "LUNA_MAX_V1"
    assert route_boundary["adapter"] == "OpenAIResponsesAdapter"
    assert route_boundary["openai_sdk_version"] == "2.53.0"
    assert {
        prompt_id: route_boundary["routes"][prompt_id]["reasoning_effort"]
        for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS)
    } == {
        prompt_id: "MAX" for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS)
    }


def test_max_authorization_boundary_seals_xhigh_sdk_and_caps(
    tmp_path: Path,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "max-qualification-real"
    boundary = eval_harness._convergence_authorization_boundary(args)
    assert boundary["git_head"]
    assert boundary["route_profile"] == "LUNA_MAX_V1"
    assert boundary["model_ids"] == ["gpt-5.6-luna"]
    assert boundary["qualified_reasoning_effort"] == {
        prompt_id: "MAX" for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS)
    }
    assert boundary["max_provider_requests"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert boundary["max_total_cost_usd"] == 0.75
    assert boundary["max_call_cost_usd"] == 0.10
    assert boundary["executable_boundary"]["openai_route_boundary"][
        "openai_sdk_version"
    ] == "2.53.0"
    assert boundary["max_qualification_baseline"] == {
        "candidate_sha": eval_harness.MAX_QUALIFICATION_BASELINE_SHA,
        "evidence_sha": eval_harness.MAX_QUALIFICATION_EVIDENCE_SHA,
        "report_hash": (
            "sha256:"
            + hashlib.sha256(
                eval_harness.MAX_QUALIFICATION_BASELINE_REPORT.read_bytes()
            ).hexdigest()
        ),
        "route_profile": "LUNA_XHIGH_V1",
        "model": "gpt-5.6-luna",
        "reasoning_effort": "XHIGH",
    }
    assert boundary["single_material_hypothesis"] == (
        "P04-P09 reasoning effort XHIGH_TO_MAX"
    )


def test_terra_medium_offline_qualification_is_exact_and_non_billable() -> None:
    report = asyncio.run(
        run_offline_convergence(
            route_profile_id=OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
            max_total_cost_usd=(
                eval_harness.TERRA_MEDIUM_OFFLINE_REHEARSAL_MAX_TOTAL_COST_USD
            ),
            max_call_cost_usd=(
                eval_harness.TERRA_MEDIUM_OFFLINE_REHEARSAL_MAX_CALL_COST_USD
            ),
            max_provider_requests=(
                eval_harness.TERRA_MEDIUM_MAX_PROVIDER_REQUESTS
            ),
        )
    )
    controls = report["controls"]
    assert report["status"] == "PASS"
    assert report["mode"] == "offline-terra-medium-qualification"
    assert report["route_profile"] == "TERRA_MEDIUM_V1"
    assert report["execution_sequence"] == [
        "semantic-sweep:P04-P09:versioned-positive-and-negative",
        "offline-golden-positive:P05",
        "offline-golden-negative:P05",
        "integrated-chain:base:1:P04-P09",
        "integrated-chain:base:2:P04-P09",
        "integrated-chain:choice-variant:P04-P09",
        "integrated-chain:canonical-document-sufficient:P04-P09",
    ]
    assert [item["status"] for item in report["observations"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert all(
        check["status"] == "PASS" and check["provider_requests"] == 0
        for check in report["deterministic_checks"]
    )
    assert controls["network_calls"] == 0
    assert controls["provider_attempts"] == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    assert controls["simulated_provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert controls["models"] == ["gpt-5.6-terra"]
    assert controls["reasoning_efforts_by_prompt"] == {
        prompt_id: ["MEDIUM"]
        for prompt_id in sorted(OPENAI_TERRA_MEDIUM_PROMPT_IDS)
    }
    assert controls["p10_calls"] == 0
    assert controls["p11_calls"] == 0
    assert controls["fallback_calls"] == 0
    assert controls["gateway_retries"] == 0
    assert controls["sdk_retries"] == 0
    assert controls["semantic_retries"] == 0
    assert controls["tools_enabled"] is False
    assert controls["store"] is False
    assert controls["background"] is False
    assert controls["budget_charged_usd"] == pytest.approx(6.4887025)
    assert controls["max_observed_budget_charge_usd"] == pytest.approx(
        0.24967
    )
    assert controls["budget_charged_usd"] <= controls[
        "max_total_cost_usd"
    ]
    assert controls["max_observed_budget_charge_usd"] <= controls[
        "max_call_cost_usd"
    ]
    call_receipts = report["provider_call_receipts"]
    assert len(call_receipts) == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    assert [row["provider_call_index"] for row in call_receipts] == list(
        range(1, QUALIFICATION_EXPECTED_PROVIDER_REQUESTS + 1)
    )
    assert [row["checkpoint_id"] for row in call_receipts[:9]] == [
        "P04_CANONICAL_POSITIVE",
        "P05_CANONICAL_POSITIVE",
        "P05_PLAN_FEASIBILITY_NEGATIVE",
        "P06_CANONICAL_POSITIVE",
        "P07_CANONICAL_POSITIVE",
        "P07_INSUFFICIENT_NEGATIVE",
        "P08_CANONICAL_POSITIVE",
        "P08_UNANSWERABLE_NEGATIVE",
        "P09_CANONICAL_POSITIVE",
    ]
    assert all(
        isinstance(row["checkpoint_id"], str) and row["checkpoint_id"]
        for row in call_receipts
    )
    assert all(
        row["provider_transport"] is False
        and row["actual_provider_cost_usd"] == 0.0
        and row["input_hash"].startswith("sha256:")
        and row["output_hash"].startswith("sha256:")
        and row["gateway_retries"] == 0
        and row["sdk_retries"] == 0
        and row["semantic_retries"] == 0
        and row["fallback"] is False
        for row in call_receipts
    )


def test_terra_medium_cli_dry_run_has_zero_network_and_no_secret_surface() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "terra-medium-qualification-dry-run",
            "--max-total-cost-usd",
            "25.60",
            "--max-call-cost-usd",
            "0.82",
            "--max-provider-requests",
            "33",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    serialized = json.dumps(report, sort_keys=True)
    assert report["status"] == "PASS"
    assert report["route_profile"] == "TERRA_MEDIUM_V1"
    assert report["controls"]["network_calls"] == 0
    assert "OPENAI_API_KEY" not in serialized
    assert "content_text" not in serialized
    assert "question_text" not in serialized


def test_terra_medium_make_real_target_is_fail_closed_without_secret_inputs() -> None:
    completed = subprocess.run(
        ["make", "openai-terra-medium-qualification-real"],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "EXECUTION_ID is required" in completed.stderr
    assert "SECRET_VERSION_RESOURCE is required" not in completed.stderr


def test_terra_medium_budget_is_derived_from_matrix_and_route_ceilings() -> None:
    budget = terra_medium_budget_derivation()
    assert budget["matrix_provider_calls"] == 33
    assert budget["provider_calls_by_prompt"] == {
        "P04_BLUEPRINT_BUILD_V1": 5,
        "P05_BLUEPRINT_REVIEW_V1": 6,
        "P06_EVIDENCE_MAP_V1": 5,
        "P07_QUESTION_BUILD_V1": 6,
        "P08_QUESTION_REVIEW_V1": 6,
        "P09_GUIDE_BUILD_V1": 5,
    }
    assert budget["maximum_conservative_call_cost_usd"] == 0.817
    assert budget["worst_case_conservative_total_cost_usd"] == 25.593
    assert budget["max_call_cost_usd"] == 0.82
    assert budget["max_total_cost_usd"] == 25.60
    assert budget["pricing_policy"]["standard_short_context_usd_per_million"] == {
        "input": 2.0,
        "cached_input": 0.2,
        "cache_write": 2.5,
        "output": 12.0,
    }
    assert budget["pricing_policy"][
        "long_context_threshold_tokens_exclusive"
    ] == 272_000
    assert all(
        row["route_input_token_ceiling"] == 250_000
        and row["request_framing_token_allowance"] == 1_024
        and row["long_context_pricing_applies"] is False
        and row["conservative_input_class"] == "FULL_CACHE_WRITE"
        for row in budget["per_prompt"].values()
    )


def test_terra_medium_boundary_preserves_product_and_records_harness_delta() -> None:
    max_report = json.loads(
        eval_harness.TERRA_MEDIUM_QUALIFICATION_BASELINE_RAW_REPORT.read_text(
            encoding="utf-8"
        )
    )
    maximum = max_report["boundary"]
    terra = rehearsal_boundary_material(
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
        max_call_cost_usd=(
            eval_harness.TERRA_MEDIUM_OFFLINE_REHEARSAL_MAX_CALL_COST_USD
        ),
    )
    assert terra["prompt_pack_version"] == "1.1.16"
    assert maximum["prompt_pack_version"] == "1.1.14"
    assert terra["planner_version"] == "stage2-planner/3.0.0"
    assert maximum["planner_version"] == "stage2-planner/2.0.0"
    assert terra["assembler_version"] == maximum["assembler_version"]
    assert terra["p05_golden"]["fixture_version"] == (
        "stage2-p05-golden-checkpoints/1.2.0"
    )
    assert maximum["p05_golden"]["fixture_version"] == (
        "stage2-p05-golden-checkpoints/1.1.0"
    )
    assert terra["p05_golden"]["negative_expected_recommendation"] == (
        maximum["p05_golden"]["negative_expected_recommendation"]
    )
    for scenario_id in maximum["checkpoints"]:
        assert {
            key
            for key in maximum["checkpoints"][scenario_id]
            if maximum["checkpoints"][scenario_id][key]
            != terra["checkpoints"][scenario_id][key]
        } == {"post_p03", "blueprint_valid", "mapping_planning_valid"}
    _assert_p04_contract_boundary_delta(
        current=terra["prompts"],
        historical=maximum["prompts"],
        prompt_ids=OPENAI_TERRA_MEDIUM_PROMPT_IDS,
    )
    for prompt_id in sorted(OPENAI_TERRA_MEDIUM_PROMPT_IDS):
        assert terra["prompts"][prompt_id][
            "registry_reasoning_effort"
        ] == "HIGH"
        assert terra["prompts"][prompt_id][
            "route_reasoning_effort"
        ] == "MEDIUM"

    delta = terra["route_delta_from_luna_max"]
    expected_all_prompts = sorted(
        {
            "P01_ACTIVITY_SPEC_V1",
            "P02_RUBRIC_NORMALIZE_V1",
            "P03_AMBIGUITY_TRIAGE_V1",
            *OPENAI_TERRA_MEDIUM_PROMPT_IDS,
            "P11_SCHEMA_REPAIR_V1",
        }
    )
    assert delta["baseline_route_profile"] == OPENAI_MAX_ROUTE_PROFILE_ID
    assert delta["selected_route_profile"] == (
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
    )
    assert delta["route_identity_changed_prompt_ids"] == expected_all_prompts
    assert delta["reasoning_effort_changes"] == {
        prompt_id: {"from": "MAX", "to": "MEDIUM"}
        for prompt_id in sorted(OPENAI_TERRA_MEDIUM_PROMPT_IDS)
    }
    assert delta["other_route_field_changes"] == {
        "model": expected_all_prompts,
        "model_snapshot": expected_all_prompts,
    }
    for unchanged_surface in (
        "prompt_registry_changes",
        "schema_changes",
        "validator_changes",
        "fixture_changes",
        "planner_changes",
        "assembler_changes",
    ):
        assert delta[unchanged_surface] == []
    route_boundary = terra["openai_route_boundary"]
    assert route_boundary["model_ids"] == ["gpt-5.6-terra"]
    assert route_boundary["route_profile"] == "TERRA_MEDIUM_V1"
    assert route_boundary["adapter"] == "OpenAIResponsesAdapter"
    assert route_boundary["openai_sdk_version"] == "2.53.0"


def test_terra_medium_boundary_seals_matrix_and_derived_budget(
    tmp_path: Path,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-medium-qualification-real"
    args.max_total_cost_usd = eval_harness.TERRA_MEDIUM_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.TERRA_MEDIUM_MAX_CALL_COST_USD
    boundary = eval_harness._convergence_authorization_boundary(args)
    assert boundary["boundary_format"] == (
        "openai-stage2-convergence-authorization/1.7.0"
    )
    assert {
        "src/comprehension_verification/qualification_semantics.py",
        "src/comprehension_verification/semantic_harness.py",
        "tests/fixtures/openai_evals/v2/p05_golden_checkpoints.json",
        "tests/fixtures/openai_evals/v2/product_rehearsal.json",
        "tests/fixtures/openai_evals/v3/frozen_product_boundary.json",
        "tests/fixtures/openai_evals/v3/semantic_qualification_pack.json",
        (
            "tests/fixtures/openai_evals/v3/document_shaped_cache_case/"
            "official_assignment.docx"
        ),
        (
            "tests/fixtures/openai_evals/v3/document_shaped_cache_case/"
            "official_rubric.docx"
        ),
        (
            "tests/fixtures/openai_evals/v3/document_shaped_cache_case/"
            "submission_sufficient.docx"
        ),
        (
            "tests/fixtures/openai_evals/v3/document_shaped_cache_case/"
            "submission_insufficient.docx"
        ),
    }.issubset(boundary["runtime_hashes"])
    assert boundary["route_profile"] == "TERRA_MEDIUM_V1"
    assert boundary["model_ids"] == ["gpt-5.6-terra"]
    assert boundary["qualified_reasoning_effort"] == {
        prompt_id: "MEDIUM"
        for prompt_id in sorted(OPENAI_TERRA_MEDIUM_PROMPT_IDS)
    }
    assert boundary["max_provider_requests"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert boundary["max_total_cost_usd"] == 25.60
    assert boundary["max_call_cost_usd"] == 0.82
    assert sum(
        row["max_provider_calls"]
        for row in boundary["provider_request_cap_derivation"]["matrix_rows"]
    ) == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    assert boundary["provider_request_cap_derivation"] == {
        "matrix_rows": boundary["provider_request_cap_derivation"][
            "matrix_rows"
        ],
        "worst_case_total": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        "cap_is_derived_from_matrix": True,
    }
    monetary_budget = boundary["monetary_budget"]
    assert monetary_budget["status"] == (
        "DERIVED_FROM_CURRENT_OFFICIAL_PRICES_AND_FROZEN"
    )
    assert monetary_budget["future_real_execution_authorized"] is True
    assert monetary_budget["historical_caps_not_reusable"] == {
        "max_total_cost_usd": 5.10,
        "max_call_cost_usd": 0.27,
    }
    assert monetary_budget["enforced_caps"] == {
        "max_provider_requests": 33,
        "max_total_cost_usd": 25.60,
        "max_call_cost_usd": 0.82,
    }
    assert monetary_budget["derivation"] == terra_medium_budget_derivation()
    assert boundary["pricing_policy_hash"] == monetary_budget["derivation"][
        "pricing_policy_hash"
    ]
    assert boundary["qualification_matrix_hash"] == monetary_budget[
        "derivation"
    ]["matrix_hash"]
    assert boundary["p10_enabled"] is False
    assert boundary["p11_enabled_during_qualification"] is False
    assert boundary["fallback_enabled"] is False
    assert boundary["tools_enabled"] is False
    assert boundary["store"] is False
    assert boundary["gateway_retries"] == 0
    assert boundary["sdk_retries"] == 0
    assert boundary["semantic_retries"] == 0
    baseline = boundary["terra_medium_qualification_baseline"]
    assert baseline["candidate_sha"] == (
        eval_harness.TERRA_MEDIUM_QUALIFICATION_BASELINE_SHA
    )
    assert baseline["evidence_sha"] == (
        eval_harness.TERRA_MEDIUM_QUALIFICATION_EVIDENCE_SHA
    )
    assert baseline["raw_report_hash"] == (
        "sha256:"
        + hashlib.sha256(
            eval_harness.TERRA_MEDIUM_QUALIFICATION_BASELINE_RAW_REPORT.read_bytes()
        ).hexdigest()
    )
    assert baseline["consolidated_report_hash"] == (
        "sha256:"
        + hashlib.sha256(
            eval_harness.TERRA_MEDIUM_QUALIFICATION_BASELINE_CONSOLIDATED_REPORT.read_bytes()
        ).hexdigest()
    )
    assert baseline["route_profile"] == "LUNA_MAX_V1"
    assert baseline["model"] == "gpt-5.6-luna"
    assert baseline["reasoning_effort"] == "MAX"
    assert boundary["univariate_comparison"] is False


def test_terra_high_profile_is_the_frozen_medium_boundary_plus_high() -> None:
    boundary = rehearsal_boundary_material(
        OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
        max_call_cost_usd=eval_harness.TERRA_HIGH_MAX_CALL_COST_USD,
    )
    delta = boundary["route_delta_from_terra_medium"]
    expected_all_prompts = sorted(
        {
            "P01_ACTIVITY_SPEC_V1",
            "P02_RUBRIC_NORMALIZE_V1",
            "P03_AMBIGUITY_TRIAGE_V1",
            *OPENAI_TERRA_HIGH_PROMPT_IDS,
            "P11_SCHEMA_REPAIR_V1",
        }
    )
    assert delta["baseline_route_profile"] == (
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
    )
    assert delta["selected_route_profile"] == (
        OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
    )
    assert delta["route_identity_changed_prompt_ids"] == expected_all_prompts
    assert delta["reasoning_effort_changes"] == {
        prompt_id: {"from": "MEDIUM", "to": "HIGH"}
        for prompt_id in sorted(OPENAI_TERRA_HIGH_PROMPT_IDS)
    }
    assert delta["other_route_field_changes"] == {}
    for unchanged_surface in (
        "prompt_registry_changes",
        "schema_changes",
        "validator_changes",
        "fixture_changes",
        "planner_changes",
        "assembler_changes",
    ):
        assert delta[unchanged_surface] == []
    routes = boundary["openai_route_boundary"]["routes"]
    assert routes["P01_ACTIVITY_SPEC_V1"]["reasoning_effort"] == "MEDIUM"
    assert routes["P02_RUBRIC_NORMALIZE_V1"]["reasoning_effort"] == "MEDIUM"
    assert routes["P03_AMBIGUITY_TRIAGE_V1"]["reasoning_effort"] == "HIGH"
    assert routes["P11_SCHEMA_REPAIR_V1"]["reasoning_effort"] == "LOW"
    assert all(
        routes[prompt_id]["reasoning_effort"] == "HIGH"
        and routes[prompt_id]["model"] == "gpt-5.6-terra"
        for prompt_id in OPENAI_TERRA_HIGH_PROMPT_IDS
    )


def test_terra_high_budget_is_derived_from_frozen_matrix_and_ceilings() -> None:
    budget = terra_high_budget_derivation()
    assert budget["schema_version"] == "terra-high-budget-derivation/1.0.0"
    assert budget["matrix_provider_calls"] == 33
    assert budget["provider_calls_by_prompt"] == {
        "P04_BLUEPRINT_BUILD_V1": 5,
        "P05_BLUEPRINT_REVIEW_V1": 6,
        "P06_EVIDENCE_MAP_V1": 5,
        "P07_QUESTION_BUILD_V1": 6,
        "P08_QUESTION_REVIEW_V1": 6,
        "P09_GUIDE_BUILD_V1": 5,
    }
    assert budget["maximum_conservative_call_cost_usd"] == 0.817
    assert budget["worst_case_conservative_total_cost_usd"] == 25.593
    assert budget["max_call_cost_usd"] == 0.82
    assert budget["max_total_cost_usd"] == 25.60
    assert budget["pricing_policy_hash"] == (
        "sha256:1043f12f6cce4be87f0a27af1062a30d7cab835dca12ab50ec9a6286a770c5ba"
    )
    assert budget["matrix_hash"] == (
        "sha256:94fbd798732b057f3ba051144a0f0de5533ce6ffb85b103d766c6abeb660ea49"
    )


def test_terra_high_offline_qualification_is_exact_and_non_billable() -> None:
    report = asyncio.run(
        run_offline_convergence(
            route_profile_id=OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
            max_total_cost_usd=eval_harness.TERRA_HIGH_MAX_TOTAL_COST_USD,
            max_call_cost_usd=eval_harness.TERRA_HIGH_MAX_CALL_COST_USD,
            max_provider_requests=eval_harness.TERRA_HIGH_MAX_PROVIDER_REQUESTS,
        )
    )
    controls = report["controls"]
    assert report["status"] == "PASS"
    assert report["mode"] == "offline-terra-high-qualification"
    assert report["route_profile"] == "TERRA_HIGH_V1"
    assert [item["status"] for item in report["observations"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert controls["network_calls"] == 0
    assert controls["provider_attempts"] == 33
    assert controls["simulated_provider_attempts"] == 33
    assert controls["models"] == ["gpt-5.6-terra"]
    assert controls["reasoning_efforts_by_prompt"] == {
        prompt_id: ["HIGH"]
        for prompt_id in sorted(OPENAI_TERRA_HIGH_PROMPT_IDS)
    }
    assert controls["p10_calls"] == controls["p11_calls"] == 0
    assert controls["fallback_calls"] == 0
    assert controls["gateway_retries"] == controls["sdk_retries"] == 0
    assert controls["semantic_retries"] == 0
    assert controls["tools_enabled"] is False
    assert controls["store"] is False
    assert controls["background"] is False
    assert len(report["provider_call_receipts"]) == 33
    assert all(
        row["provider_transport"] is False
        and row["actual_provider_cost_usd"] == 0.0
        for row in report["provider_call_receipts"]
    )
    assert report["boundary"]["terra_ladder_harness_freeze"][
        "material_hash"
    ] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )


def test_terra_high_authorization_boundary_seals_baseline_budget_and_freeze(
    tmp_path: Path,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-high-qualification-real"
    args.max_total_cost_usd = eval_harness.TERRA_HIGH_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.TERRA_HIGH_MAX_CALL_COST_USD
    boundary = eval_harness._convergence_authorization_boundary(args)
    assert boundary["boundary_format"] == (
        "openai-stage2-convergence-authorization/1.7.0"
    )
    assert boundary["route_profile"] == "TERRA_HIGH_V1"
    assert boundary["model_ids"] == ["gpt-5.6-terra"]
    assert boundary["qualified_reasoning_effort"] == {
        prompt_id: "HIGH"
        for prompt_id in sorted(OPENAI_TERRA_HIGH_PROMPT_IDS)
    }
    assert boundary["max_provider_requests"] == 33
    assert boundary["max_total_cost_usd"] == 25.60
    assert boundary["max_call_cost_usd"] == 0.82
    assert boundary["monetary_budget"]["derivation"] == (
        terra_high_budget_derivation()
    )
    assert boundary["monetary_budget"]["prior_authorizations_reusable"] is False
    baseline = boundary["terra_high_qualification_baseline"]
    assert baseline["candidate_sha"] == (
        eval_harness.TERRA_HIGH_QUALIFICATION_BASELINE_SHA
    )
    assert baseline["evidence_sha"] == (
        eval_harness.TERRA_HIGH_QUALIFICATION_EVIDENCE_SHA
    )
    assert baseline["report_hash"] == (
        "sha256:"
        + hashlib.sha256(
            eval_harness.TERRA_HIGH_QUALIFICATION_BASELINE_REPORT.read_bytes()
        ).hexdigest()
    )
    freeze = boundary["executable_boundary"]["terra_ladder_harness_freeze"]
    assert freeze["status"] == "TERRA_LADDER_HARNESS_FROZEN"
    assert freeze["material_hash"] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )
    assert freeze["oracles"]["p06_hash"] == (
        "sha256:d559af8784d553a4df56166d27ab309c48064e577438c3e372213f175a857048"
    )
    assert freeze["oracles"]["p07_hash"] == (
        "sha256:25df80e7ee502f95692d800697760dfed10e8ade69488ab84f67bc0d7aa6daeb"
    )


def test_terra_xhigh_profile_is_the_frozen_high_boundary_plus_xhigh() -> None:
    boundary = rehearsal_boundary_material(
        OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        max_call_cost_usd=eval_harness.TERRA_XHIGH_MAX_CALL_COST_USD,
    )
    delta = boundary["route_delta_from_terra_high"]
    expected_all_prompts = sorted(
        {
            "P01_ACTIVITY_SPEC_V1",
            "P02_RUBRIC_NORMALIZE_V1",
            "P03_AMBIGUITY_TRIAGE_V1",
            *OPENAI_TERRA_XHIGH_PROMPT_IDS,
            "P11_SCHEMA_REPAIR_V1",
        }
    )
    assert delta["baseline_route_profile"] == (
        OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
    )
    assert delta["selected_route_profile"] == (
        OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
    )
    assert delta["route_identity_changed_prompt_ids"] == expected_all_prompts
    assert delta["reasoning_effort_changes"] == {
        prompt_id: {"from": "HIGH", "to": "XHIGH"}
        for prompt_id in sorted(OPENAI_TERRA_XHIGH_PROMPT_IDS)
    }
    assert delta["other_route_field_changes"] == {}
    for unchanged_surface in (
        "prompt_registry_changes",
        "schema_changes",
        "validator_changes",
        "fixture_changes",
        "planner_changes",
        "assembler_changes",
    ):
        assert delta[unchanged_surface] == []
    routes = boundary["openai_route_boundary"]["routes"]
    assert routes["P01_ACTIVITY_SPEC_V1"]["reasoning_effort"] == "MEDIUM"
    assert routes["P02_RUBRIC_NORMALIZE_V1"]["reasoning_effort"] == "MEDIUM"
    assert routes["P03_AMBIGUITY_TRIAGE_V1"]["reasoning_effort"] == "HIGH"
    assert routes["P11_SCHEMA_REPAIR_V1"]["reasoning_effort"] == "LOW"
    assert all(
        routes[prompt_id]["reasoning_effort"] == "XHIGH"
        and routes[prompt_id]["model"] == "gpt-5.6-terra"
        for prompt_id in OPENAI_TERRA_XHIGH_PROMPT_IDS
    )


def test_terra_xhigh_budget_is_rederived_from_current_prices_and_matrix() -> None:
    budget = terra_xhigh_budget_derivation()
    assert budget["schema_version"] == "terra-xhigh-budget-derivation/1.0.0"
    assert budget["route_profile"] == "TERRA_XHIGH_V1"
    assert budget["matrix_provider_calls"] == 33
    assert budget["maximum_conservative_call_cost_usd"] == 0.817
    assert budget["worst_case_conservative_total_cost_usd"] == 25.593
    assert budget["max_call_cost_usd"] == 0.82
    assert budget["max_total_cost_usd"] == 25.60
    assert budget["pricing_policy_hash"] == (
        "sha256:1043f12f6cce4be87f0a27af1062a30d7cab835dca12ab50ec9a6286a770c5ba"
    )
    assert budget["matrix_hash"] == (
        "sha256:94fbd798732b057f3ba051144a0f0de5533ce6ffb85b103d766c6abeb660ea49"
    )


def test_terra_xhigh_offline_qualification_is_exact_and_non_billable() -> None:
    report = asyncio.run(
        run_offline_convergence(
            route_profile_id=OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
            max_total_cost_usd=eval_harness.TERRA_XHIGH_MAX_TOTAL_COST_USD,
            max_call_cost_usd=eval_harness.TERRA_XHIGH_MAX_CALL_COST_USD,
            max_provider_requests=eval_harness.TERRA_XHIGH_MAX_PROVIDER_REQUESTS,
        )
    )
    controls = report["controls"]
    assert report["status"] == "PASS"
    assert report["mode"] == "offline-terra-xhigh-qualification"
    assert report["route_profile"] == "TERRA_XHIGH_V1"
    assert [item["status"] for item in report["observations"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert controls["network_calls"] == 0
    assert controls["provider_attempts"] == 33
    assert controls["simulated_provider_attempts"] == 33
    assert controls["models"] == ["gpt-5.6-terra"]
    assert controls["reasoning_efforts_by_prompt"] == {
        prompt_id: ["XHIGH"]
        for prompt_id in sorted(OPENAI_TERRA_XHIGH_PROMPT_IDS)
    }
    assert controls["p10_calls"] == controls["p11_calls"] == 0
    assert controls["fallback_calls"] == 0
    assert controls["gateway_retries"] == controls["sdk_retries"] == 0
    assert controls["semantic_retries"] == 0
    assert controls["tools_enabled"] is False
    assert controls["store"] is False
    assert controls["background"] is False
    assert len(report["provider_call_receipts"]) == 33
    assert all(
        row["provider_transport"] is False
        and row["actual_provider_cost_usd"] == 0.0
        for row in report["provider_call_receipts"]
    )
    assert report["boundary"]["terra_ladder_harness_freeze"][
        "material_hash"
    ] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )


def test_terra_xhigh_authorization_boundary_seals_high_budget_and_freeze(
    tmp_path: Path,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-xhigh-qualification-real"
    args.max_total_cost_usd = eval_harness.TERRA_XHIGH_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.TERRA_XHIGH_MAX_CALL_COST_USD
    boundary = eval_harness._convergence_authorization_boundary(args)
    assert boundary["boundary_format"] == (
        "openai-stage2-convergence-authorization/1.8.0"
    )
    assert boundary["route_profile"] == "TERRA_XHIGH_V1"
    assert boundary["model_ids"] == ["gpt-5.6-terra"]
    assert boundary["qualified_reasoning_effort"] == {
        prompt_id: "XHIGH"
        for prompt_id in sorted(OPENAI_TERRA_XHIGH_PROMPT_IDS)
    }
    assert boundary["max_provider_requests"] == 33
    assert boundary["max_total_cost_usd"] == 25.60
    assert boundary["max_call_cost_usd"] == 0.82
    assert boundary["statistical_significance_claimed"] is False
    assert boundary["official_capability_verification"] == {
        "observed_at": "2026-08-14T02:29:25Z",
        "model_url": (
            "https://developers.openai.com/api/docs/models/gpt-5.6-terra"
        ),
        "pricing_url": "https://developers.openai.com/api/docs/pricing",
        "model_id": "gpt-5.6-terra",
        "available": True,
        "responses_api": True,
        "structured_outputs": True,
        "reasoning_efforts": [
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ],
        "context_window_tokens": 1_050_000,
        "max_output_tokens": 128_000,
        "standard_short_context_usd_per_million": {
            "input": 2.0,
            "cached_input": 0.2,
            "cache_write": 2.5,
            "output": 12.0,
        },
        "standard_long_context_usd_per_million": {
            "input": 4.0,
            "cached_input": 0.4,
            "cache_write": 5.0,
            "output": 18.0,
        },
        "long_context_threshold_tokens_exclusive": 272_000,
        "cache_write_multiplier": 1.25,
        "long_context_multipliers": {"input": 2.0, "output": 1.5},
    }
    assert boundary["official_capability_verification_hash"].startswith(
        "sha256:"
    )
    assert boundary["monetary_budget"]["derivation"] == (
        terra_xhigh_budget_derivation()
    )
    assert boundary["monetary_budget"]["prior_authorizations_reusable"] is False
    baseline = boundary["terra_xhigh_qualification_baseline"]
    assert baseline["candidate_sha"] == (
        eval_harness.TERRA_XHIGH_QUALIFICATION_BASELINE_SHA
    )
    assert baseline["evidence_sha"] == (
        eval_harness.TERRA_XHIGH_QUALIFICATION_EVIDENCE_SHA
    )
    assert baseline["report_hash"] == (
        "sha256:"
        + hashlib.sha256(
            eval_harness.TERRA_XHIGH_QUALIFICATION_BASELINE_REPORT.read_bytes()
        ).hexdigest()
    )
    freeze = boundary["executable_boundary"]["terra_ladder_harness_freeze"]
    assert freeze["material_hash"] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )
    assert freeze["matrix"]["hash"] == (
        "sha256:94fbd798732b057f3ba051144a0f0de5533ce6ffb85b103d766c6abeb660ea49"
    )


@pytest.mark.parametrize(
    ("profile_id", "budget_factory", "schema_version"),
    [
        (
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            sol_medium_budget_derivation,
            "sol-medium-budget-derivation/1.0.0",
        ),
        (
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            sol_high_budget_derivation,
            "sol-high-budget-derivation/1.0.0",
        ),
        (
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            sol_xhigh_budget_derivation,
            "sol-xhigh-budget-derivation/1.0.0",
        ),
    ],
)
def test_sol_budgets_are_derived_from_the_same_frozen_matrix(
    profile_id: str,
    budget_factory: object,
    schema_version: str,
) -> None:
    budget = budget_factory()  # type: ignore[operator]
    assert budget["schema_version"] == schema_version
    assert budget["route_profile"] == profile_id
    assert budget["model"] == "gpt-5.6-sol"
    assert budget["matrix_provider_calls"] == 33
    assert budget["maximum_conservative_call_cost_usd"] == 2.0425
    assert budget["worst_case_conservative_total_cost_usd"] == 63.9825
    assert budget["max_call_cost_usd"] == 2.05
    assert budget["max_total_cost_usd"] == 63.99
    assert budget["matrix_hash"] == (
        "sha256:94fbd798732b057f3ba051144a0f0de5533ce6ffb85b103d766c6abeb660ea49"
    )
    assert budget["pricing_policy"][
        "standard_short_context_usd_per_million"
    ] == {
        "input": 5.0,
        "cached_input": 0.5,
        "cache_write": 6.25,
        "output": 30.0,
    }
    assert budget["pricing_policy"]["observed_at"] == (
        "2026-08-14T14:50:29Z"
    )
    assert budget["pricing_policy_hash"].startswith("sha256:")
    assert all(
        row["request_framing_token_allowance"] == 1_024
        and row["route_input_token_ceiling"] == 250_000
        and row["long_context_pricing_applies"] is False
        for row in budget["per_prompt"].values()
    )
    assert eval_harness.SOL_LADDER_ABSOLUTE_MAX_PROVIDER_REQUESTS == 99
    assert eval_harness.SOL_LADDER_ABSOLUTE_MAX_COST_USD == 191.97


@pytest.mark.parametrize(
    ("profile_id", "effort", "mode"),
    [
        (
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            "MEDIUM",
            "offline-sol-medium-qualification",
        ),
        (
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            "HIGH",
            "offline-sol-high-qualification",
        ),
        (
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            "XHIGH",
            "offline-sol-xhigh-qualification",
        ),
    ],
)
def test_each_sol_profile_rehearses_33_calls_completely_offline(
    profile_id: str,
    effort: str,
    mode: str,
) -> None:
    report = asyncio.run(
        run_offline_convergence(
            route_profile_id=profile_id,
            max_total_cost_usd=eval_harness.SOL_PER_RUNG_MAX_TOTAL_COST_USD,
            max_call_cost_usd=eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD,
            max_provider_requests=(
                eval_harness.SOL_PER_RUNG_MAX_PROVIDER_REQUESTS
            ),
        )
    )
    controls = report["controls"]
    assert report["status"] == "PASS"
    assert report["mode"] == mode
    assert report["route_profile"] == profile_id
    assert [row["status"] for row in report["observations"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert [row["status"] for row in report["deterministic_checks"]] == [
        "PASS",
        "PASS",
    ]
    assert controls["provider_attempts"] == 33
    assert controls["simulated_provider_attempts"] == 33
    assert controls["network_calls"] == controls["openai_network_calls"] == 0
    assert controls["billable_requests"] == controls["secret_resolutions"] == 0
    assert controls["actual_cost_usd"] == 0.0
    assert controls["models"] == ["gpt-5.6-sol"]
    qualified_ids = {
        "MEDIUM": OPENAI_SOL_MEDIUM_PROMPT_IDS,
        "HIGH": OPENAI_SOL_HIGH_PROMPT_IDS,
        "XHIGH": OPENAI_SOL_XHIGH_PROMPT_IDS,
    }[effort]
    assert controls["reasoning_efforts_by_prompt"] == {
        prompt_id: [effort] for prompt_id in sorted(qualified_ids)
    }
    assert controls["p10_calls"] == controls["p11_calls"] == 0
    assert controls["fallback_calls"] == 0
    assert controls["gateway_retries"] == controls["sdk_retries"] == 0
    assert controls["semantic_retries"] == 0
    assert controls["integrated_golden_injection"] is False
    assert controls["tools_enabled"] is False
    assert controls["store"] is False
    assert controls["background"] is False
    assert report["transport_provenance"] == {
        "provider_transport_constructed": False,
        "reviewed_semantic_oracle_invocations": 9,
        "structural_transport_substitute_invocations": 24,
        "semantic_sweep_response_origin": "REVIEWED_SEMANTIC_ORACLE",
        "integrated_chain_response_origin": "STRUCTURAL_TRANSPORT_SUBSTITUTE",
        "integrated_chain_semantic_quality_conclusion_allowed": False,
    }
    assert report["boundary"]["forbidden_delta"] == []
    freeze = report["boundary"]["terra_ladder_harness_freeze"]
    assert freeze["material_hash"] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )


@pytest.mark.parametrize(
    ("mode", "profile_id", "effort", "previous_profile"),
    [
        (
            "sol-medium-qualification-real",
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            "MEDIUM",
            None,
        ),
        (
            "sol-high-qualification-real",
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            "HIGH",
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
        ),
        (
            "sol-xhigh-qualification-real",
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            "XHIGH",
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
        ),
    ],
)
def test_sol_authorization_boundaries_are_distinct_and_frozen(
    tmp_path: Path,
    reviewed_sol_candidate_delta: None,
    mode: str,
    profile_id: str,
    effort: str,
    previous_profile: str | None,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = mode
    args.max_total_cost_usd = eval_harness.SOL_PER_RUNG_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD
    boundary = eval_harness._convergence_authorization_boundary(args)
    assert boundary["boundary_format"] == (
        "openai-stage2-convergence-authorization/1.9.0"
    )
    assert boundary["route_profile"] == profile_id
    assert boundary["model_ids"] == ["gpt-5.6-sol"]
    assert boundary["qualified_reasoning_effort"] == {
        prompt_id: effort
        for prompt_id in sorted(OPENAI_SOL_MEDIUM_PROMPT_IDS)
    }
    assert boundary["cross_family_baseline_univariate"] is False
    assert boundary["intra_sol_reasoning_comparison_univariate"] is (
        previous_profile is not None
    )
    assert boundary["previous_sol_route_profile"] == previous_profile
    assert boundary["candidate_delta"]["forbidden_delta"] == []
    assert set(boundary["candidate_delta"]["observed_delta"]) <= (
        eval_harness.SOL_ALLOWED_DELTA_PATHS
    )
    assert boundary["official_capability_verification"]["model_id"] == (
        "gpt-5.6-sol"
    )
    assert boundary["official_capability_verification"]["responses_api"] is True
    assert boundary["official_capability_verification"][
        "structured_outputs"
    ] is True
    assert boundary["monetary_budget"]["enforced_caps"] == {
        "max_provider_requests": 33,
        "max_total_cost_usd": 63.99,
        "max_call_cost_usd": 2.05,
    }
    assert boundary["sol_ladder"]["absolute_max_provider_requests"] == 99
    assert boundary["sol_ladder"]["absolute_max_cost_usd"] == 191.97
    baseline = boundary["terra_xhigh_evidence_baseline"]
    assert baseline["candidate_sha"] == (
        eval_harness.SOL_LADDER_TERRA_XHIGH_CANDIDATE_SHA
    )
    assert baseline["evidence_sha"] == eval_harness.SOL_LADDER_BASELINE_SHA
    assert baseline["receipt_is_historical_and_immutable"] is True
    freeze = boundary["executable_boundary"]["terra_ladder_harness_freeze"]
    assert freeze["material_hash"] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )


def test_sol_profile_authorization_hashes_are_pairwise_distinct(
    tmp_path: Path,
    reviewed_sol_candidate_delta: None,
) -> None:
    hashes: set[str] = set()
    for mode in (
        "sol-medium-qualification-real",
        "sol-high-qualification-real",
        "sol-xhigh-qualification-real",
    ):
        args = _real_cli_args(tmp_path)
        args.mode = mode
        args.max_total_cost_usd = eval_harness.SOL_PER_RUNG_MAX_TOTAL_COST_USD
        args.max_call_cost_usd = eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD
        hashes.add(canonical_hash(eval_harness._convergence_authorization_boundary(args)))
    assert len(hashes) == 3


def _reservation_boundary() -> dict[str, object]:
    return {
        "git_head": "a" * 40,
        "harness_hash": "sha256:" + "b" * 64,
        "prompt_hash": "sha256:" + "c" * 64,
        "input_hash": "sha256:" + "d" * 64,
        "max_cost_usd": 0.5,
        "max_requests": 30,
    }


def test_exactly_once_ledger_survives_crash_and_rejects_reuse(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authorization.sqlite3"
    first = EvaluationAuthorizationLedger(path)
    reservation = first.reserve(
        execution_id="execution-1",
        authorization_id="authorization-1",
        boundary=_reservation_boundary(),
    )
    assert reservation.status == "RESERVED"

    reopened_after_simulated_crash = EvaluationAuthorizationLedger(path)
    with pytest.raises(
        EvaluationAuthorizationConsumed,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        reopened_after_simulated_crash.reserve(
            execution_id="execution-1",
            authorization_id="authorization-1",
            boundary=_reservation_boundary(),
        )
    assert reopened_after_simulated_crash.record("execution-1")["status"] == (
        "RESERVED"
    )


def test_exactly_once_ledger_rejects_authorization_alias_reuse(
    tmp_path: Path,
) -> None:
    ledger = EvaluationAuthorizationLedger(tmp_path / "authorization.sqlite3")
    ledger.reserve(
        execution_id="execution-1",
        authorization_id="authorization-1",
        boundary=_reservation_boundary(),
    )
    with pytest.raises(EvaluationAuthorizationConsumed):
        ledger.reserve(
            execution_id="execution-2",
            authorization_id="authorization-1",
            boundary={**_reservation_boundary(), "max_cost_usd": 0.6},
        )


def test_exactly_once_ledger_is_atomic_under_concurrency(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authorization.sqlite3"

    def reserve() -> str:
        ledger = EvaluationAuthorizationLedger(path)
        try:
            ledger.reserve(
                execution_id="execution-concurrent",
                authorization_id="authorization-concurrent",
                boundary=_reservation_boundary(),
            )
        except EvaluationAuthorizationConsumed:
            return "CONSUMED"
        return "RESERVED"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: reserve(), range(8)))
    assert outcomes.count("RESERVED") == 1
    assert outcomes.count("CONSUMED") == 7


def test_exactly_once_ledger_terminal_record_cannot_reopen(
    tmp_path: Path,
) -> None:
    ledger = EvaluationAuthorizationLedger(tmp_path / "authorization.sqlite3")
    reservation = ledger.reserve(
        execution_id="execution-complete",
        authorization_id="authorization-complete",
        boundary=_reservation_boundary(),
    )
    ledger.finish(
        reservation=reservation,
        status="COMPLETED",
        report_hash="sha256:" + "e" * 64,
    )
    assert ledger.record("execution-complete")["status"] == "COMPLETED"
    with pytest.raises(EvaluationAuthorizationConsumed):
        ledger.reserve(
            execution_id="execution-complete",
            authorization_id="authorization-complete",
            boundary=_reservation_boundary(),
        )


def test_real_convergence_code_path_uses_real_routes_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        )
    )
    assert report["status"] == "PASS"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["unpriced_attempts"] == 0
    assert report["controls"]["budget_charged_usd"] <= 0.75
    assert report["controls"]["models"] == ["gpt-5.6-luna"]
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


def test_xhigh_real_code_path_uses_exact_routes_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
        )
    )
    assert report["status"] == "PASS"
    assert report["mode"] == "real-xhigh-qualification"
    assert report["route_profile"] == "LUNA_XHIGH_V1"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["models"] == ["gpt-5.6-luna"]
    assert report["controls"]["reasoning_efforts_by_prompt"] == {
        prompt_id: ["XHIGH"]
        for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS)
    }
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


def test_max_real_code_path_uses_exact_routes_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
        )
    )
    assert report["status"] == "PASS"
    assert report["mode"] == "real-max-qualification"
    assert report["route_profile"] == "LUNA_MAX_V1"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["models"] == ["gpt-5.6-luna"]
    assert report["controls"]["reasoning_efforts_by_prompt"] == {
        prompt_id: ["MAX"]
        for prompt_id in sorted(OPENAI_MAX_PROMPT_IDS)
    }
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


def test_terra_medium_route_uses_offline_substitute_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=(
                eval_harness.TERRA_MEDIUM_OFFLINE_REHEARSAL_MAX_TOTAL_COST_USD
            ),
            max_call_cost_usd=(
                eval_harness.TERRA_MEDIUM_OFFLINE_REHEARSAL_MAX_CALL_COST_USD
            ),
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            route_profile_id=OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
        )
    )
    assert report["status"] == "PASS"
    assert report["mode"] == "real-terra-medium-qualification"
    assert report["route_profile"] == "TERRA_MEDIUM_V1"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["provider_attempts"] == (
        QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
    )
    assert report["controls"]["models"] == ["gpt-5.6-terra"]
    assert report["controls"]["reasoning_efforts_by_prompt"] == {
        prompt_id: ["MEDIUM"]
        for prompt_id in sorted(OPENAI_TERRA_MEDIUM_PROMPT_IDS)
    }
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


def test_terra_high_route_uses_offline_substitute_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=eval_harness.TERRA_HIGH_MAX_TOTAL_COST_USD,
            max_call_cost_usd=eval_harness.TERRA_HIGH_MAX_CALL_COST_USD,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            route_profile_id=OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
        )
    )
    assert report["status"] == "PASS"
    assert report["mode"] == "real-terra-high-qualification"
    assert report["route_profile"] == "TERRA_HIGH_V1"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == 33
    assert report["controls"]["provider_attempts"] == 33
    assert report["controls"]["models"] == ["gpt-5.6-terra"]
    assert report["controls"]["reasoning_efforts_by_prompt"] == {
        prompt_id: ["HIGH"]
        for prompt_id in sorted(OPENAI_TERRA_HIGH_PROMPT_IDS)
    }
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


def test_terra_xhigh_route_uses_offline_substitute_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=eval_harness.TERRA_XHIGH_MAX_TOTAL_COST_USD,
            max_call_cost_usd=eval_harness.TERRA_XHIGH_MAX_CALL_COST_USD,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            route_profile_id=OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        )
    )
    assert report["status"] == "PASS"
    assert report["mode"] == "real-terra-xhigh-qualification"
    assert report["route_profile"] == "TERRA_XHIGH_V1"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == 33
    assert report["controls"]["provider_attempts"] == 33
    assert report["controls"]["models"] == ["gpt-5.6-terra"]
    assert report["controls"]["reasoning_efforts_by_prompt"] == {
        prompt_id: ["XHIGH"]
        for prompt_id in sorted(OPENAI_TERRA_XHIGH_PROMPT_IDS)
    }
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


@pytest.mark.parametrize(
    ("profile_id", "effort", "mode"),
    [
        (
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            "MEDIUM",
            "real-sol-medium-qualification",
        ),
        (
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            "HIGH",
            "real-sol-high-qualification",
        ),
        (
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            "XHIGH",
            "real-sol-xhigh-qualification",
        ),
    ],
)
def test_sol_real_code_paths_use_exact_routes_with_offline_substitute(
    monkeypatch: pytest.MonkeyPatch,
    profile_id: str,
    effort: str,
    mode: str,
) -> None:
    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: build_reviewed_semantic_adapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=eval_harness.SOL_PER_RUNG_MAX_TOTAL_COST_USD,
            max_call_cost_usd=eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            route_profile_id=profile_id,
        )
    )
    assert report["status"] == "PASS"
    assert report["mode"] == mode
    assert report["route_profile"] == profile_id
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == 33
    assert report["controls"]["provider_attempts"] == 33
    assert report["controls"]["models"] == ["gpt-5.6-sol"]
    assert report["controls"]["reasoning_efforts_by_prompt"] == {
        prompt_id: [effort]
        for prompt_id in sorted(OPENAI_SOL_MEDIUM_PROMPT_IDS)
    }
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0
    assert report["controls"]["integrated_golden_injection"] is False


def test_real_convergence_accounts_for_context_invalid_billable_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CostedContextInvalidAdapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            raw = deepcopy(result.raw_output)
            if kwargs["prompt_id"] == "P04_BLUEPRINT_BUILD_V1":
                raw["evidence_variants"][0]["dimension_alias"] = "D999"
            return replace(
                result,
                raw_output=raw,
                estimated_cost_usd=0.012,
                actual_cost_usd=0.01,
            )

    monkeypatch.setattr(
        "comprehension_verification.rehearsal.OpenAIResponsesAdapter",
        lambda **_kwargs: CostedContextInvalidAdapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        )
    )
    assert report["status"] == "FAIL"
    # The semantic sweep observes all nine reviewed checkpoints after P04
    # fails; each of the four structural chains then stops at its own P04.
    assert report["controls"]["network_calls"] == 13
    assert report["controls"]["provider_attempts"] == 13
    assert report["controls"]["actual_cost_usd"] == 0.13
    assert report["controls"]["budget_charged_usd"] == 0.156
    assert report["controls"]["unpriced_attempts"] == 0
    assert len(report["provider_call_receipts"]) == 13
    assert report["provider_call_receipts"][0]["checkpoint_id"] == (
        "P04_CANONICAL_POSITIVE"
    )
    assert report["provider_call_receipts"][0]["result"] == "SCHEMA_INVALID"
    assert report["provider_call_receipts"][0]["provider_transport"] is True
    sweep = report["observations"][0]
    failures = sweep["failure"]["aggregated_failures"]
    assert len(failures) == 1
    assert failures[0]["stage"] == "P04_BLUEPRINT_BUILD"
    assert failures[0]["codes"] == ["P04_DRAFT_COMPILATION_FAILED"]
    assert failures[0]["checkpoint_id"] == "P04_CANONICAL_POSITIVE"
    assert failures[0]["checkpoint_class"] == (
        "SEMANTICALLY_QUALIFIED_POSITIVE"
    )
    assert failures[0]["contractual_adherence"] == "FAIL"
    assert failures[0]["semantic_interpretation"] == "NOT_EVALUATED"
    assert [row["checkpoint_id"] for row in sweep["stages"]] == [
        "P05_CANONICAL_POSITIVE",
        "P05_PLAN_FEASIBILITY_NEGATIVE",
        "P06_CANONICAL_POSITIVE",
        "P07_CANONICAL_POSITIVE",
        "P07_INSUFFICIENT_NEGATIVE",
        "P08_CANONICAL_POSITIVE",
        "P08_UNANSWERABLE_NEGATIVE",
        "P09_CANONICAL_POSITIVE",
    ]


def _real_cli_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        mode="convergence-real",
        manifest=eval_harness.DEFAULT_MANIFEST,
        case_id=[],
        allow_billable=True,
        max_total_cost_usd=0.75,
        max_call_cost_usd=0.10,
        max_provider_requests=QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        execution_id="phase2-test-execution",
        authorization_id="phase2-test-authorization",
        ledger=tmp_path / "authorization.sqlite3",
        report_path=tmp_path / "report.json",
        secret_version_resource=(
            "projects/test-project/secrets/openai-key/versions/1"
        ),
        p04_evidence_recovery=False,
    )


def test_real_cli_reserves_before_key_read_and_consumes_failed_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _real_cli_args(tmp_path)
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)

    def unavailable(resource: str) -> SecretStr:
        assert resource == args.secret_version_resource
        record = EvaluationAuthorizationLedger(args.ledger).record(
            args.execution_id
        )
        assert record["status"] == "RESERVED"
        raise eval_harness.ProviderCredentialUnavailable

    monkeypatch.setattr(eval_harness, "resolve_openai_api_key", unavailable)
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_CONVERGENCE_CREDENTIAL_UNAVAILABLE",
    ):
        eval_harness._run_convergence_cli(args)
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "FAILED"
    assert record["failure_code"] == (
        "OPENAI_CONVERGENCE_CREDENTIAL_UNAVAILABLE"
    )
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["failure"]["codes"] == [
        "OPENAI_CONVERGENCE_CREDENTIAL_UNAVAILABLE"
    ]
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_real_cli_persists_provenance_and_completes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _real_cli_args(tmp_path)
    monkeypatch.setenv("CVA_OPENAI_API_KEY", "synthetic-test-key")

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        return {
            "report_schema_version": "stage2-convergence-report/1.0.0",
            "status": "PASS",
            "mode": "real-convergence",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "observations": [],
            "controls": {
                "network_calls": 0,
                "actual_cost_usd": 0.0,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["git_head"]
    assert report["harness_hash"].startswith("sha256:")
    assert report["manifest_hash"].startswith("sha256:")
    assert report["runtime_hashes"]
    assert all(
        value.startswith("sha256:")
        for value in report["runtime_hashes"].values()
    )
    assert report["authorization_hash"].startswith("sha256:")
    assert "synthetic-test-key" not in json.dumps(report)
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    assert record["report_hash"].startswith("sha256:")


def test_xhigh_cli_persists_pass_verdict_and_consumes_authorization_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "xhigh-qualification-real"

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        return {
            "report_schema_version": "stage2-convergence-report/1.6.0",
            "status": "PASS",
            "mode": "real-xhigh-qualification",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "route_profile": "LUNA_XHIGH_V1",
            "observations": [],
            "controls": {
                "network_calls": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "provider_attempts": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "actual_cost_usd": 0.01,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["qualification_outcome"] == (
        "LUNA_XHIGH_QUALIFICATION_PASSED"
    )
    assert report["convergence_outcome"] == (
        "READY_FOR_INDEPENDENT_REVIEW"
    )
    assert report["baseline_high_candidate"] == (
        eval_harness.XHIGH_QUALIFICATION_BASELINE_SHA
    )
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_xhigh_outcome_distinguishes_model_failure_from_implementation() -> None:
    assert eval_harness._xhigh_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["UNAUTHORIZED_EVIDENCE"]}}
            ],
        }
    ) == (
        "LUNA_XHIGH_QUALIFICATION_FAILED",
        "CONVERGENCE_INCOMPLETE",
    )
    assert eval_harness._xhigh_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["MODEL_PROVIDER_ERROR"]}}
            ],
        }
    ) == (
        "XHIGH_QUALIFICATION_INCONCLUSIVE",
        "CONVERGENCE_INCOMPLETE",
    )


def test_max_cli_persists_pass_and_three_way_comparison_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "max-qualification-real"

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        return {
            "report_schema_version": "stage2-convergence-report/1.7.0",
            "status": "PASS",
            "mode": "real-max-qualification",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "route_profile": "LUNA_MAX_V1",
            "observations": [],
            "controls": {
                "network_calls": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "provider_attempts": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "input_tokens": 100,
                "output_tokens": 200,
                "reasoning_tokens": 150,
                "actual_cost_usd": 0.01,
                "budget_charged_usd": 0.02,
                "gateway_retries": 0,
                "sdk_retries": 0,
                "semantic_retries": 0,
                "fallback_calls": 0,
                "p10_calls": 0,
                "p11_calls": 0,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["qualification_outcome"] == (
        "LUNA_MAX_QUALIFICATION_PASSED"
    )
    assert report["family_outcome"] is None
    assert report["convergence_outcome"] == (
        "READY_FOR_INDEPENDENT_REVIEW"
    )
    assert report["causal_classification"] == "QUALIFICATION_PASSED"
    assert report["recommended_next_authority"] == (
        "INDEPENDENT_REVIEW_ONLY_NO_BUILD_DEPLOY"
    )
    assert report["baseline_xhigh_candidate"] == (
        eval_harness.MAX_QUALIFICATION_BASELINE_SHA
    )
    comparison = report["configuration_comparison"]
    assert comparison["statistical_significance_claimed"] is False
    assert [
        item["reasoning_effort"] for item in comparison["configurations"]
    ] == ["HIGH", "XHIGH", "MAX"]
    assert comparison["configurations"][0][
        "token_usage_availability"
    ] == "NOT_RECORDED_IN_SOURCE_REPORT"
    assert comparison["configurations"][2]["token_usage"] == {
        "input_tokens": 100,
        "output_tokens": 200,
        "reasoning_tokens": 150,
    }
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_max_outcome_is_terminal_for_model_failure_and_inconclusive_for_transport() -> None:
    assert eval_harness._max_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["UNAUTHORIZED_EVIDENCE"]}}
            ],
        }
    ) == {
        "qualification_outcome": "LUNA_MAX_QUALIFICATION_FAILED",
        "family_outcome": "LUNA_FAMILY_QUALIFICATION_EXHAUSTED",
        "convergence_outcome": "CONVERGENCE_INCOMPLETE",
        "causal_classification": "MODEL_OWNED_QUALIFICATION_FAILURE",
        "recommended_next_authority": (
            "HUMAN_REVIEW_OF_LUNA_EXHAUSTION_NO_AUTOMATIC_MODEL_CHANGE"
        ),
    }


@pytest.mark.parametrize(
    ("max_total_cost_usd", "max_call_cost_usd"),
    [
        (5.10, 0.27),
        (20.0, 0.27),
    ],
)
def test_terra_medium_real_cli_is_budget_blocked_before_secret_or_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_total_cost_usd: float,
    max_call_cost_usd: float,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-medium-qualification-real"
    args.max_total_cost_usd = max_total_cost_usd
    args.max_call_cost_usd = max_call_cost_usd

    def forbidden_secret_resolution(_resource: str) -> SecretStr:
        raise AssertionError("provider secret must remain unresolved")

    monkeypatch.setattr(
        eval_harness, "resolve_openai_api_key", forbidden_secret_resolution
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_TERRA_MEDIUM_QUALIFICATION_EXACT_CAPS_REQUIRED",
    ):
        eval_harness._run_convergence_cli(args)
    assert not args.ledger.exists()
    assert not args.report_path.exists()


def test_terra_medium_cli_reserves_exact_budget_and_completes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-medium-qualification-real"
    args.max_total_cost_usd = eval_harness.TERRA_MEDIUM_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.TERRA_MEDIUM_MAX_CALL_COST_USD

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        record = EvaluationAuthorizationLedger(args.ledger).record(
            args.execution_id
        )
        assert record["status"] == "RESERVED"
        return {
            "report_schema_version": "stage2-convergence-report/1.11.0",
            "status": "PASS",
            "mode": "real-terra-medium-qualification",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "route_profile": "TERRA_MEDIUM_V1",
            "observations": [],
            "controls": {
                "network_calls": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "provider_attempts": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "actual_cost_usd": 0.01,
                "budget_charged_usd": 0.02,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["qualification_outcome"] == (
        "TERRA_MEDIUM_QUALIFICATION_PASSED"
    )
    assert report["convergence_outcome"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert report["pricing_policy_hash"] == (
        eval_harness.TERRA_MEDIUM_BUDGET_DERIVATION["pricing_policy_hash"]
    )
    assert report["budget_derivation"]["matrix_provider_calls"] == 33
    assert report["budget_derivation"]["max_provider_requests"] == 33
    assert report["budget_derivation"]["max_call_cost_usd"] == 0.82
    assert report["budget_derivation"]["max_total_cost_usd"] == 25.60
    assert report["authorization_id"] == args.authorization_id
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_terra_medium_pass_outcome_is_machine_readable() -> None:
    assert eval_harness._terra_medium_qualification_outcome(
        {"status": "PASS", "observations": []}
    ) == {
        "qualification_outcome": "TERRA_MEDIUM_QUALIFICATION_PASSED",
        "convergence_outcome": "READY_FOR_INDEPENDENT_REVIEW",
        "causal_classification": "QUALIFICATION_PASSED",
        "recommended_next_authority": (
            "INDEPENDENT_REVIEW_ONLY_NO_BUILD_DEPLOY_OR_TERRA_HIGH"
        ),
    }


def test_report_writer_enumerates_codes_only_for_synthetic_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic-report.json"
    report_hash = eval_harness._write_json_atomic(
        path,
        {
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "checkpoint_assessments": [
                {"reason_codes": ["SYSTEMATIC_ORACLE_DISAGREEMENT"]}
            ],
            "failure": {"codes": ["MODEL_OUTPUT_VALIDATION_FAILED"]},
        },
    )
    written = json.loads(path.read_text(encoding="utf-8"))
    assert report_hash.startswith("sha256:")
    assert written["diagnostic_codes"] == [
        "MODEL_OUTPUT_VALIDATION_FAILED",
        "SYSTEMATIC_ORACLE_DISAGREEMENT",
    ]
    assert written["diagnostic_codes_hash"].startswith("sha256:")
    assert written["evidence_status"] == (
        "HISTORICAL_NON_CANONICAL_EVIDENCE"
    )
    assert written["model_selection_gate"] is False


def test_terra_medium_outcome_requires_semantic_provenance_for_causality() -> None:
    unprovenanced = eval_harness._terra_medium_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {
                    "failure": {
                        "codes": [
                            "MODEL_OUTPUT_VALIDATION_FAILED",
                            "OUTPUT_PYDANTIC_VALIDATION_FAILED",
                        ]
                    }
                }
            ],
        }
    )
    assert unprovenanced["qualification_outcome"] == (
        "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE"
    )
    assert unprovenanced["causal_classification"] == (
        "ORACLE_STATUS_MISSING"
    )
    assert eval_harness._terra_medium_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["MODEL_PROVIDER_ERROR"]}}
            ],
        }
    ) == {
        "qualification_outcome": "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE",
        "convergence_outcome": "CONVERGENCE_INCOMPLETE",
        "causal_classification": "TECHNICAL_QUALIFICATION_FAILURE",
        "recommended_next_authority": (
            "TECHNICAL_REVIEW_ONLY_NO_RERUN_WITHOUT_NEW_AUTHORITY"
        ),
    }
    assert eval_harness._terra_medium_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {
                    "failure": {
                        "aggregated_failures": [
                            {"codes": ["MODEL_PROVIDER_ERROR"]},
                            {
                                "codes": [
                                    "MODEL_OUTPUT_VALIDATION_FAILED",
                                    "OUTPUT_PYDANTIC_VALIDATION_FAILED",
                                ]
                            },
                        ]
                    }
                }
            ],
        }
    ) == {
        "qualification_outcome": "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE",
        "convergence_outcome": "CONVERGENCE_INCOMPLETE",
        "causal_classification": (
            "ORACLE_STATUS_MISSING_WITH_TECHNICAL_FAILURES"
        ),
        "recommended_next_authority": (
            "INDEPENDENT_HARNESS_REVIEW_BEFORE_ANY_TERRA_HIGH_AUTHORITY"
        ),
    }


@pytest.mark.parametrize(
    ("assessment", "expected_outcome", "expected_cause"),
    [
        (
            classify_checkpoint(
                checkpoint_id="semantic-failure",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
                semantic_review_id="SR-SEMANTIC",
                semantic_review_version="1.0.0",
                semantic_review_hash="sha256:" + "1" * 64,
                reason_codes=["SEMANTIC_MISMATCH"],
            ),
            "TERRA_MEDIUM_QUALIFICATION_FAILED",
            "MODEL_OWNED_SEMANTIC_FAILURE",
        ),
        (
            classify_checkpoint(
                checkpoint_id="adherence-failure",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.DEFENDIBLE,
                contractual_adherence=ContractualAdherence.FAIL,
                semantic_review_id="SR-ADHERENCE",
                semantic_review_version="1.0.0",
                semantic_review_hash="sha256:" + "2" * 64,
                reason_codes=["DIAGNOSTIC_INCOMPLETE"],
            ),
            "TERRA_MEDIUM_QUALIFICATION_FAILED",
            "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE",
        ),
        (
            classify_checkpoint(
                checkpoint_id="indeterminate",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.INDETERMINATE,
                contractual_adherence=ContractualAdherence.PASS,
                semantic_review_id="SR-INDETERMINATE",
                semantic_review_version="1.0.0",
                semantic_review_hash="sha256:" + "3" * 64,
                reason_codes=["OBJECTIVE_INVARIANTS_INSUFFICIENT"],
            ),
            "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE",
            "CAUSE_INDETERMINATE",
        ),
        (
            classify_checkpoint(
                checkpoint_id="suspect-oracle",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.ORACLE_SUSPECT,
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.FAIL,
                reason_codes=["SYSTEMATIC_ORACLE_DISAGREEMENT"],
            ),
            "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE",
            "ORACLE_SUSPECT",
        ),
        (
            classify_checkpoint(
                checkpoint_id="invalid-oracle",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.INVALID,
                semantic_interpretation=SemanticInterpretation.NOT_EVALUATED,
                contractual_adherence=ContractualAdherence.NOT_EVALUATED,
                reason_codes=["ORACLE_INVALID"],
            ),
            "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE",
            "ORACLE_OR_CHECKPOINT_INVALID",
        ),
        (
            classify_checkpoint(
                checkpoint_id="technical-only",
                checkpoint_class=CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY,
                oracle_validity=OracleValidity.NOT_APPLICABLE,
                semantic_interpretation=SemanticInterpretation.NOT_EVALUATED,
                contractual_adherence=ContractualAdherence.NOT_EVALUATED,
                technical_failure=True,
                reason_codes=["MODEL_PROVIDER_ERROR"],
            ),
            "TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE",
            "TECHNICAL_QUALIFICATION_FAILURE",
        ),
    ],
)
def test_terra_medium_global_outcome_requires_clean_model_owned_evidence(
    assessment: object,
    expected_outcome: str,
    expected_cause: str,
) -> None:
    raw = assessment.model_dump()  # type: ignore[attr-defined]
    outcome = eval_harness._terra_medium_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": list(raw["reason_codes"])}}
            ],
            "checkpoint_assessments": [raw],
        }
    )
    assert outcome["qualification_outcome"] == expected_outcome
    assert outcome["causal_classification"] == expected_cause


@pytest.mark.parametrize(
    ("max_total_cost_usd", "max_call_cost_usd"),
    [(20.0, 0.82), (25.60, 0.81)],
)
def test_terra_high_real_cli_rejects_nonexact_caps_before_secret_or_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_total_cost_usd: float,
    max_call_cost_usd: float,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-high-qualification-real"
    args.max_total_cost_usd = max_total_cost_usd
    args.max_call_cost_usd = max_call_cost_usd

    def forbidden_secret_resolution(_resource: str) -> SecretStr:
        raise AssertionError("provider secret must remain unresolved")

    monkeypatch.setattr(
        eval_harness, "resolve_openai_api_key", forbidden_secret_resolution
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_TERRA_HIGH_QUALIFICATION_EXACT_CAPS_REQUIRED",
    ):
        eval_harness._run_convergence_cli(args)
    assert not args.ledger.exists()
    assert not args.report_path.exists()


def test_terra_high_cli_reserves_exactly_once_and_records_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-high-qualification-real"
    args.max_total_cost_usd = eval_harness.TERRA_HIGH_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.TERRA_HIGH_MAX_CALL_COST_USD

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        record = EvaluationAuthorizationLedger(args.ledger).record(
            args.execution_id
        )
        assert record["status"] == "RESERVED"
        return {
            "report_schema_version": "stage2-convergence-report/1.12.0",
            "status": "PASS",
            "mode": "real-terra-high-qualification",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "route_profile": "TERRA_HIGH_V1",
            "observations": [],
            "controls": {
                "network_calls": 33,
                "provider_attempts": 33,
                "actual_cost_usd": 0.01,
                "budget_charged_usd": 0.02,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["qualification_outcome"] == (
        "TERRA_HIGH_QUALIFICATION_PASSED"
    )
    assert report["convergence_outcome"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert report["baseline_terra_medium_candidate"] == (
        eval_harness.TERRA_HIGH_QUALIFICATION_BASELINE_SHA
    )
    assert report["budget_derivation"] == terra_high_budget_derivation()
    assert report["terra_ladder_harness_freeze"]["status"] == (
        "TERRA_LADDER_HARNESS_FROZEN"
    )
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_terra_high_outcomes_obey_the_final_decision_policy() -> None:
    assert eval_harness._terra_high_qualification_outcome(
        {"status": "PASS", "observations": []}
    ) == {
        "qualification_outcome": "TERRA_HIGH_QUALIFICATION_PASSED",
        "convergence_outcome": "READY_FOR_INDEPENDENT_REVIEW",
        "causal_classification": "QUALIFICATION_PASSED",
        "recommended_next_authority": (
            "INDEPENDENT_REVIEW_ONLY_NO_RERUN_XHIGH_BUILD_OR_DEPLOY"
        ),
    }
    technical = eval_harness._terra_high_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["MODEL_PROVIDER_ERROR"]}}
            ],
        }
    )
    assert technical["qualification_outcome"] == (
        "TERRA_HIGH_QUALIFICATION_INCONCLUSIVE"
    )
    assert technical["causal_classification"] == (
        "TECHNICAL_QUALIFICATION_FAILURE"
    )
    clean_failure = classify_checkpoint(
        checkpoint_id="high-semantic-failure",
        checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
        oracle_validity=OracleValidity.VALID,
        semantic_interpretation=SemanticInterpretation.INCORRECT,
        contractual_adherence=ContractualAdherence.PASS,
        semantic_review_id="SR-HIGH-FROZEN",
        semantic_review_version="1.0.0",
        semantic_review_hash="sha256:" + "4" * 64,
        reason_codes=["SEMANTIC_MISMATCH"],
    ).model_dump()
    failed = eval_harness._terra_high_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["SEMANTIC_MISMATCH"]}}
            ],
            "checkpoint_assessments": [clean_failure],
        }
    )
    assert failed["qualification_outcome"] == (
        "TERRA_HIGH_QUALIFICATION_FAILED"
    )
    assert failed["causal_classification"] == "MODEL_OWNED_SEMANTIC_FAILURE"
    assert all("XHIGH" in outcome["recommended_next_authority"] for outcome in (
        technical,
        failed,
    ))


@pytest.mark.parametrize(
    ("max_total_cost_usd", "max_call_cost_usd"),
    [(20.0, 0.82), (25.60, 0.81)],
)
def test_terra_xhigh_real_cli_rejects_nonexact_caps_before_secret_or_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_total_cost_usd: float,
    max_call_cost_usd: float,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-xhigh-qualification-real"
    args.max_total_cost_usd = max_total_cost_usd
    args.max_call_cost_usd = max_call_cost_usd

    def forbidden_secret_resolution(_resource: str) -> SecretStr:
        raise AssertionError("provider secret must remain unresolved")

    monkeypatch.setattr(
        eval_harness, "resolve_openai_api_key", forbidden_secret_resolution
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_TERRA_XHIGH_QUALIFICATION_EXACT_CAPS_REQUIRED",
    ):
        eval_harness._run_convergence_cli(args)
    assert not args.ledger.exists()
    assert not args.report_path.exists()


def test_terra_xhigh_cli_reserves_exactly_once_and_records_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "terra-xhigh-qualification-real"
    args.max_total_cost_usd = eval_harness.TERRA_XHIGH_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.TERRA_XHIGH_MAX_CALL_COST_USD

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        record = EvaluationAuthorizationLedger(args.ledger).record(
            args.execution_id
        )
        assert record["status"] == "RESERVED"
        return {
            "report_schema_version": "stage2-convergence-report/1.12.0",
            "status": "PASS",
            "mode": "real-terra-xhigh-qualification",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "route_profile": "TERRA_XHIGH_V1",
            "observations": [],
            "controls": {
                "network_calls": 33,
                "provider_attempts": 33,
                "actual_cost_usd": 0.01,
                "budget_charged_usd": 0.02,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["qualification_outcome"] == (
        "TERRA_XHIGH_QUALIFICATION_PASSED"
    )
    assert report["convergence_outcome"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert report["baseline_terra_high_candidate"] == (
        eval_harness.TERRA_XHIGH_QUALIFICATION_BASELINE_SHA
    )
    assert report["budget_derivation"] == terra_xhigh_budget_derivation()
    assert report["terra_ladder_harness_freeze"]["status"] == (
        "TERRA_LADDER_HARNESS_FROZEN"
    )
    assert report["statistical_significance_claimed"] is False
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_terra_xhigh_outcomes_enforce_terminal_family_policy() -> None:
    assert eval_harness._terra_xhigh_qualification_outcome(
        {"status": "PASS", "observations": []}
    ) == {
        "qualification_outcome": "TERRA_XHIGH_QUALIFICATION_PASSED",
        "convergence_outcome": "READY_FOR_INDEPENDENT_REVIEW",
        "causal_classification": "QUALIFICATION_PASSED",
        "recommended_next_authority": (
            "INDEPENDENT_REVIEW_ONLY_NO_RERUN_MAX_BUILD_OR_DEPLOY"
        ),
    }
    technical = eval_harness._terra_xhigh_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["MODEL_PROVIDER_ERROR"]}}
            ],
        }
    )
    assert technical["qualification_outcome"] == (
        "TERRA_XHIGH_QUALIFICATION_INCONCLUSIVE"
    )
    assert technical["causal_classification"] == (
        "TECHNICAL_QUALIFICATION_FAILURE"
    )
    clean_failure = classify_checkpoint(
        checkpoint_id="terra-xhigh-semantic-failure",
        checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
        oracle_validity=OracleValidity.VALID,
        semantic_interpretation=SemanticInterpretation.INCORRECT,
        contractual_adherence=ContractualAdherence.PASS,
        semantic_review_id="SR-TERRA-XHIGH-FROZEN",
        semantic_review_version="1.0.0",
        semantic_review_hash="sha256:" + "5" * 64,
        reason_codes=["SEMANTIC_MISMATCH"],
    ).model_dump()
    failed = eval_harness._terra_xhigh_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["SEMANTIC_MISMATCH"]}}
            ],
            "checkpoint_assessments": [clean_failure],
        }
    )
    assert failed["qualification_outcome"] == (
        "TERRA_XHIGH_QUALIFICATION_FAILED"
    )
    assert failed["family_outcome"] == (
        "TERRA_FAMILY_QUALIFICATION_EXHAUSTED"
    )
    assert failed["causal_classification"] == "MODEL_OWNED_SEMANTIC_FAILURE"
    assert "NO_TERRA_MAX" in failed["recommended_next_authority"]


@pytest.mark.parametrize(
    "mode",
    [
        "sol-medium-qualification-real",
        "sol-high-qualification-real",
        "sol-xhigh-qualification-real",
    ],
)
def test_sol_real_cli_blocks_inexact_caps_before_secret_or_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reviewed_sol_candidate_delta: None,
    mode: str,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = mode
    args.max_total_cost_usd = 63.98
    args.max_call_cost_usd = eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD

    def forbidden_secret_resolution(_resource: str) -> SecretStr:
        raise AssertionError("provider secret must remain unresolved")

    monkeypatch.setattr(
        eval_harness, "resolve_openai_api_key", forbidden_secret_resolution
    )
    rung = mode.split("-")[1].upper()
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match=f"OPENAI_SOL_{rung}_QUALIFICATION_EXACT_CAPS_REQUIRED",
    ):
        eval_harness._run_convergence_cli(args)
    assert not args.ledger.exists()
    assert not args.report_path.exists()


def test_sol_forbidden_delta_blocks_before_secret_or_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = "sol-medium-qualification-real"
    args.max_total_cost_usd = eval_harness.SOL_PER_RUNG_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD
    monkeypatch.setattr(
        eval_harness,
        "_sol_candidate_delta_proof",
        lambda: {
            "allowed_delta": [],
            "forbidden_delta": ["src/product_workflow.py"],
        },
    )

    def forbidden_secret_resolution(_resource: str) -> SecretStr:
        raise AssertionError("provider secret must remain unresolved")

    monkeypatch.setattr(
        eval_harness, "resolve_openai_api_key", forbidden_secret_resolution
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="SOL_LADDER_PRECONDITIONS_FAILED",
    ):
        eval_harness._run_convergence_cli(args)
    assert not args.ledger.exists()
    assert not args.report_path.exists()


def test_sol_candidate_delta_proof_fails_closed_without_baseline_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_harness.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "diff"],
            returncode=128,
            stdout="",
            stderr="fatal: bad object synthetic-baseline",
        ),
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="SOL_LADDER_PRECONDITIONS_FAILED",
    ):
        eval_harness._sol_candidate_delta_proof()


@pytest.mark.parametrize(
    ("mode", "profile_id", "rung"),
    [
        (
            "sol-medium-qualification-real",
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            "MEDIUM",
        ),
        (
            "sol-high-qualification-real",
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            "HIGH",
        ),
        (
            "sol-xhigh-qualification-real",
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            "XHIGH",
        ),
    ],
)
def test_each_sol_rung_reserves_its_own_authorization_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reviewed_sol_candidate_delta: None,
    mode: str,
    profile_id: str,
    rung: str,
) -> None:
    args = _real_cli_args(tmp_path)
    args.mode = mode
    args.execution_id = f"sol-{rung.lower()}-test-execution"
    args.authorization_id = f"sol-{rung.lower()}-test-authorization"
    args.max_total_cost_usd = eval_harness.SOL_PER_RUNG_MAX_TOTAL_COST_USD
    args.max_call_cost_usd = eval_harness.SOL_PER_RUNG_MAX_CALL_COST_USD

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        record = EvaluationAuthorizationLedger(args.ledger).record(
            args.execution_id
        )
        assert record["status"] == "RESERVED"
        return {
            "report_schema_version": "stage2-convergence-report/1.12.0",
            "status": "PASS",
            "mode": f"real-sol-{rung.lower()}-qualification",
            "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
            "route_profile": profile_id,
            "observations": [],
            "provider_call_receipts": [{}],
            "controls": {
                "network_calls": 33,
                "provider_attempts": 33,
                "actual_cost_usd": 0.01,
                "budget_charged_usd": 0.02,
            },
        }

    monkeypatch.setattr(
        eval_harness, "_run_current_convergence_real", fake_run
    )
    assert eval_harness._run_convergence_cli(args) == 0
    capsys.readouterr()
    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    assert report["qualification_outcome"] == (
        f"SOL_{rung}_QUALIFICATION_PASSED"
    )
    assert report["ladder_outcome"] == "SOL_LADDER_STOPPED_ON_PASS"
    assert report["ladder_decision"] == "STOP_ON_FIRST_PASS"
    assert report["convergence_outcome"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert report["route_profile"] == profile_id
    assert report["provider_call_receipts"] == [
        {"route_profile": profile_id, "rung": rung}
    ]
    assert report["budget_derivation"] == eval_harness._sol_profile_budget(
        profile_id
    )
    assert report["frozen_semantic_harness"]["material_hash"] == (
        "sha256:1b37e8d6b0a68b4e7e88fc2dc873fa87ba490a743fd3c3ba9497d5b337fd8566"
    )
    assert report["candidate_delta"]["forbidden_delta"] == []
    record = EvaluationAuthorizationLedger(args.ledger).record(
        args.execution_id
    )
    assert record["status"] == "COMPLETED"
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="EVALUATION_AUTHORIZATION_ALREADY_CONSUMED",
    ):
        eval_harness._run_convergence_cli(args)


def test_sol_adaptive_outcomes_stop_or_advance_exactly_as_authorized() -> None:
    for rung in ("MEDIUM", "HIGH", "XHIGH"):
        passed = eval_harness._sol_qualification_outcome(
            {"status": "PASS", "observations": []},
            rung=rung,
        )
        assert passed["qualification_outcome"] == (
            f"SOL_{rung}_QUALIFICATION_PASSED"
        )
        assert passed["ladder_outcome"] == "SOL_LADDER_STOPPED_ON_PASS"
        assert passed["ladder_decision"] == "STOP_ON_FIRST_PASS"

        technical = eval_harness._sol_qualification_outcome(
            {
                "status": "FAIL",
                "observations": [
                    {"failure": {"codes": ["MODEL_PROVIDER_ERROR"]}}
                ],
            },
            rung=rung,
        )
        assert technical["qualification_outcome"] == (
            f"SOL_{rung}_QUALIFICATION_INCONCLUSIVE"
        )
        assert technical["ladder_outcome"] == (
            "SOL_LADDER_STOPPED_INCONCLUSIVE"
        )
        assert technical["ladder_decision"] == "STOP_ON_INCONCLUSIVE"

    clean_failure = classify_checkpoint(
        checkpoint_id="sol-ladder-semantic-failure",
        checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
        oracle_validity=OracleValidity.VALID,
        semantic_interpretation=SemanticInterpretation.INCORRECT,
        contractual_adherence=ContractualAdherence.PASS,
        semantic_review_id="SR-SOL-FROZEN",
        semantic_review_version="1.0.0",
        semantic_review_hash="sha256:" + "6" * 64,
        reason_codes=["SEMANTIC_MISMATCH"],
    ).model_dump()
    failed_result = {
        "status": "FAIL",
        "observations": [
            {"failure": {"codes": ["SEMANTIC_MISMATCH"]}}
        ],
        "checkpoint_assessments": [clean_failure],
    }
    medium = eval_harness._sol_qualification_outcome(
        failed_result,
        rung="MEDIUM",
    )
    high = eval_harness._sol_qualification_outcome(
        failed_result,
        rung="HIGH",
    )
    xhigh = eval_harness._sol_qualification_outcome(
        failed_result,
        rung="XHIGH",
    )
    assert medium["qualification_outcome"] == "SOL_MEDIUM_QUALIFICATION_FAILED"
    assert medium["ladder_decision"] == "ADVANCE_TO_SOL_HIGH"
    assert high["qualification_outcome"] == "SOL_HIGH_QUALIFICATION_FAILED"
    assert high["ladder_decision"] == "ADVANCE_TO_SOL_XHIGH"
    assert xhigh["qualification_outcome"] == "SOL_XHIGH_QUALIFICATION_FAILED"
    assert xhigh["ladder_outcome"] == "SOL_REASONING_LADDER_EXHAUSTED"
    assert xhigh["ladder_decision"] == "STOP_AFTER_XHIGH"
    assert xhigh["causal_classification"] == "MODEL_OWNED_SEMANTIC_FAILURE"
    with pytest.raises(ValueError, match="unknown Sol ladder rung"):
        eval_harness._sol_qualification_outcome(failed_result, rung="MAX")


def test_max_outcome_additional_contract_and_mixed_cases() -> None:
    assert eval_harness._max_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {
                    "failure": {
                        "codes": ["MODEL_CONTRACT_VALIDATION_FAILED"]
                    }
                }
            ],
        }
    )["qualification_outcome"] == "LUNA_MAX_QUALIFICATION_FAILED"
    assert eval_harness._max_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["MODEL_PROVIDER_ERROR"]}}
            ],
        }
    ) == {
        "qualification_outcome": "MAX_QUALIFICATION_INCONCLUSIVE",
        "family_outcome": None,
        "convergence_outcome": "CONVERGENCE_INCOMPLETE",
        "causal_classification": (
            "TECHNICAL_MAX_SUPPORT_OR_EXECUTION_FAILURE"
        ),
        "recommended_next_authority": (
            "TECHNICAL_REVIEW_ONLY_NO_RERUN_WITHOUT_NEW_AUTHORITY"
        ),
    }
    assert eval_harness._max_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["TYPEERROR"]}}
            ],
        }
    )["qualification_outcome"] == "MAX_QUALIFICATION_INCONCLUSIVE"
    assert eval_harness._max_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {
                    "failure": {
                        "aggregated_failures": [
                            {"codes": ["MODEL_PROVIDER_ERROR"]},
                            {
                                "codes": [
                                    "MODEL_OUTPUT_VALIDATION_FAILED",
                                    "OUTPUT_PYDANTIC_VALIDATION_FAILED",
                                ]
                            },
                        ]
                    }
                }
            ],
        }
    ) == {
        "qualification_outcome": "LUNA_MAX_QUALIFICATION_FAILED",
        "family_outcome": "LUNA_FAMILY_QUALIFICATION_EXHAUSTED",
        "convergence_outcome": "CONVERGENCE_INCOMPLETE",
        "causal_classification": (
            "MODEL_OWNED_QUALIFICATION_FAILURE_WITH_TECHNICAL_FAILURES"
        ),
        "recommended_next_authority": (
            "HUMAN_REVIEW_OF_LUNA_EXHAUSTION_NO_AUTOMATIC_MODEL_CHANGE"
        ),
    }


def test_authorization_boundary_binds_prompts_schemas_validators_and_inputs() -> None:
    boundary = rehearsal_boundary_material()
    assert boundary["p10_enabled"] is False
    assert set(boundary["checkpoints"]) == {
        BASE_SCENARIO_ID,
        VARIANT_SCENARIO_ID,
    }
    for prompt in boundary["prompts"].values():
        assert prompt["hash"].startswith("sha256:")
        assert prompt["input_schema_hash"].startswith("sha256:")
        assert prompt["output_schema_hash"].startswith("sha256:")
        assert prompt["relationship_validator"]
    assert canonical_hash(boundary).startswith("sha256:")
