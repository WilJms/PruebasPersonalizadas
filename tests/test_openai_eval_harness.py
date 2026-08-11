from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from comprehension_verification.model_gateway import AdapterResult
from comprehension_verification.model_gateway.openai_schema import (
    provider_schema_validation_issues,
)
from scripts import run_openai_evals as eval_harness


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_openai_evals.py"


def _safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("CVA_OPENAI_API_KEY", None)
    environment.pop("CVA_OPENAI_REAL_EVALS_APPROVAL", None)
    environment.pop("CVA_OPENAI_LUNA_CANARY_APPROVAL", None)
    environment.pop("CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL", None)
    environment.pop("CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL", None)
    environment.pop("CVA_OPENAI_P01_V112_REMEDIATION_DECISION", None)
    environment.pop("CVA_OPENAI_REAL_QUALIFICATION_APPROVAL", None)
    environment.pop("CVA_OPENAI_P02_V113_REMEDIATION_DECISION", None)
    environment.pop("CVA_OPENAI_P02_V113_RECANARY_APPROVAL", None)
    environment.pop("CVA_OPENAI_P05_V114_REMEDIATION_DECISION", None)
    environment.pop("CVA_OPENAI_P05_V114_RECANARY_APPROVAL", None)
    environment.pop("CVA_OPENAI_P09_V115_REMEDIATION_DECISION", None)
    environment.pop("CVA_OPENAI_P09_V115_RECANARY_APPROVAL", None)
    environment.pop("CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL", None)
    environment.pop(
        "CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL", None
    )
    environment.pop(
        "CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL", None
    )
    return environment


def test_openai_golden_set_runs_offline_without_network_or_cost() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["mode"] == "offline"
    assert report["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    assert report["route_profile"] == "LUNA_BASELINE_V1"
    assert report["network_calls"] == 0
    assert report["billable_calls"] == 0
    assert len(report["cases"]) == 20
    assert {case["source_format"] for case in report["cases"]} >= {
        "TXT",
        "MD",
        "PDF",
        "DOCX",
        None,
    }
    assert len(report["human_review_dimensions"]) == 10
    assert all(case["status"] == "PASS" for case in report["cases"])
    callable_cases = [case for case in report["cases"] if case["model"]]
    assert {case["model"] for case in callable_cases} == {"gpt-5.6-luna"}
    assert {case["provider"] for case in callable_cases} == {"openai"}
    assert all(case["fallback_route_id"] is None for case in report["cases"])
    assert all(
        case["route_profile"] == "LUNA_BASELINE_V1" for case in report["cases"]
    )
    by_case = {case["case_id"]: case for case in report["cases"]}
    assert by_case["oa-p01-happy-txt"]["reasoning_effort"] == "MEDIUM"
    assert by_case["oa-p02-happy-pdf"]["reasoning_effort"] == "MEDIUM"
    assert by_case["oa-p04-happy"]["reasoning_effort"] == "HIGH"
    assert by_case["oa-p11-happy"]["reasoning_effort"] == "LOW"
    assert by_case["oa-p10-disabled"]["model"] is None


def test_openai_golden_set_real_mode_is_blocked_without_dual_opt_in() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "real"],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report == {
        "code": "OPENAI_REAL_EVALS_APPROVAL_REQUIRED",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_openai_golden_set_can_select_one_owner_review_case() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--case-id",
            "oa-p07-choice-justification",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert [case["case_id"] for case in report["cases"]] == [
        "oa-p07-choice-justification"
    ]
    assert report["network_calls"] == report["billable_calls"] == 0


def test_openai_golden_set_reserves_retries_and_p11_before_transport() -> None:
    environment = _safe_environment()
    environment["CVA_OPENAI_API_KEY"] = (
        "sk-project-synthetic-placeholder-not-a-real-key"
    )
    environment["CVA_OPENAI_REAL_EVALS_APPROVAL"] = (
        "OPENAI_REAL_EVALS_APPROVED"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "real",
            "--allow-billable",
            "--max-total-cost-usd",
            "0.01",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report == {
        "code": "OPENAI_REAL_EVALS_BUDGET_TOO_LOW",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_real_harness_fails_closed_on_case_expectation_drift(monkeypatch) -> None:
    class FakeGateway:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def invoke(self, *_args, **_kwargs):
            return SimpleNamespace(
                ledgers=(
                    SimpleNamespace(
                        actual_cost_usd=0.01,
                        estimated_cost_usd=0.02,
                        route=SimpleNamespace(
                            model="gpt-5.6-luna",
                            provider="openai",
                            reasoning_effort=SimpleNamespace(value="MEDIUM"),
                            fallback_route_id=None,
                            reason_codes=["EFFECTIVE_MODEL_gpt-5.6-luna"],
                        ),
                    ),
                ),
                output=SimpleNamespace(),
            )

    def reject_expectation(*_args, **_kwargs) -> None:
        raise AssertionError("synthetic semantic detail must not escape")

    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setenv(
        "CVA_OPENAI_REAL_EVALS_APPROVAL", "OPENAI_REAL_EVALS_APPROVED"
    )
    monkeypatch.setattr(
        eval_harness, "OpenAIResponsesAdapter", lambda **_: object()
    )
    monkeypatch.setattr(eval_harness, "ModelGateway", FakeGateway)
    monkeypatch.setattr(eval_harness, "_assert_case_outcome", reject_expectation)
    case = eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)[0]

    report = asyncio.run(
        eval_harness._run_real([case], max_total_cost_usd=10.0)
    )

    assert report["network_calls"] == 1
    assert report["actual_cost_usd"] == 0.01
    assert report["cases"] == [
        {
            "actual_cost_usd": 0.01,
            "attempts": 1,
            "case_id": case["case_id"],
            "effective_model": "gpt-5.6-luna",
            "error_code": "OPENAI_REAL_EVAL_EXPECTATION_FAILED",
            "fallback_route_id": None,
            "model": "gpt-5.6-luna",
            "prompt_version": "1.1.2",
            "provider": "openai",
            "reasoning_effort": "MEDIUM",
            "route_profile": "LUNA_BASELINE_V1",
            "schema_version": "1.1.0",
            "status": "FAIL",
        }
    ]


@pytest.mark.parametrize(
    (
        "case_id",
        "prompt_id",
        "reasoning",
        "request_bytes",
        "schema_bytes",
        "input_upper_bound",
        "max_output",
        "no_cache_ceiling_usd",
        "full_cache_write_ceiling_usd",
    ),
    (
        (
            "oa-p01-happy-txt",
            "P01_ACTIVITY_SPEC_V1",
            "MEDIUM",
            9_242,
            3_111,
            10_266,
            8_000,
            0.0116532,
            0.0121665,
        ),
        (
            "oa-p01-injection-md",
            "P01_ACTIVITY_SPEC_V1",
            "MEDIUM",
            9_688,
            3_111,
            10_712,
            8_000,
            0.0117424,
            0.012278,
        ),
        (
            "oa-p07-open-short-txt",
            "P07_QUESTION_BUILD_V1",
            "HIGH",
            20_843,
            13_671,
            21_867,
            10_000,
            0.0163734,
            0.01746675,
        ),
    ),
)
def test_luna_canary_dry_run_exercises_real_adapter_with_one_fake_request(
    case_id: str,
    prompt_id: str,
    reasoning: str,
    request_bytes: int,
    schema_bytes: int,
    input_upper_bound: int,
    max_output: int,
    no_cache_ceiling_usd: float,
    full_cache_write_ceiling_usd: float,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "canary-dry-run",
            "--case-id",
            case_id,
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["mode"] == "canary-dry-run"
    assert report["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    assert report["route_profile"] == "LUNA_BASELINE_V1"
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["max_responses_requests"] == 1
    assert report["gateway_retries"] == 0
    assert report["prompt_retries"] == 0
    assert report["sdk_retries"] == 0
    assert (
        report["p10_calls"]
        == report["p11_calls"]
        == report["fallback_calls"]
        == report["sol_calls"]
        == 0
    )
    assert report["secret_read"] is False
    row = report["cases"][0]
    assert row["case_id"] == case_id
    assert row["provider"] == "openai"
    assert row["model"] == row["effective_model"] == "gpt-5.6-luna"
    assert row["reasoning_effort"] == reasoning
    assert row["prompt_version"] == "1.1.2"
    assert row["schema_version"] == "1.1.0"
    assert row["fallback_route_id"] is None
    assert row["fake_transport_calls"] == 1
    assert row["validation_order"] == ["request", "envelope", "output"]
    assert row["output_status"] == "READY"
    budget = row["budget"]
    assert budget["request_effective_bytes"] == request_bytes
    assert budget["schema_bytes"] == schema_bytes
    assert budget["input_upper_bound_tokens"] == input_upper_bound
    assert budget["max_output_tokens"] == max_output
    assert budget["no_cache_ceiling_usd"] == no_cache_ceiling_usd
    assert budget["full_cache_write_ceiling_usd"] == (
        full_cache_write_ceiling_usd
    )
    assert budget["transport_ceiling_usd"] == full_cache_write_ceiling_usd
    assert budget["worst_case_usd"] == full_cache_write_ceiling_usd
    assert budget["cache_assumption"] == "FULL_INPUT_CACHE_WRITE"
    assert budget["pricing_standard_short_context_usd_per_million"] == {
        "cache_write": 0.25,
        "cached_input": 0.02,
        "input": 0.2,
        "output": 1.2,
    }
    controls = row["controls"]
    assert controls["semantic_task_count"] == 1
    assert all(
        value is True
        for name, value in controls.items()
        if name != "semantic_task_count"
    )
    assert row["route_profile"] == "LUNA_BASELINE_V1"
    assert row["provider"] == "openai"
    assert row["status"] == "PASS"
    assert row["controls"]["structured_output_strict"] is True
    assert row["controls"]["raw_upload_absent"] is True
    assert row["controls"]["conversation_state_absent"] is True
    assert row["controls"]["outcome_allowed_by_manifest"] is True
    assert row["controls"]["request_pydantic_valid"] is True
    assert row["controls"]["envelope_valid"] is True
    assert row["controls"]["output_pydantic_valid"] is True
    assert row["controls"]["contextual_validation"] is True
    assert row["controls"]["ids_allowlisted"] is True
    assert row["controls"]["tools_empty"] is True
    assert row["controls"]["store_false"] is True
    assert row["controls"]["background_false"] is True
    if case_id == "oa-p01-injection-md":
        assert budget["proposed_human_budget_usd"] == 0.02
        assert row["prompt_hash"] == (
            eval_harness.P01_INJECTION_V112_PROMPT_HASH
        )
        assert row["input_bundle_hash"] == (
            eval_harness.P01_INJECTION_V112_INPUT_BUNDLE_HASH
        )
        assert row["injection_observation"] == {
            "assignment_prompt_role": True,
            "document_path_locator": True,
            "normalized_evidence_unit_boundary": True,
            "synthetic_marker_present_in_input_data": True,
            "synthetic_marker_propagated_to_output": False,
        }
    else:
        assert row["injection_observation"] is None
    assert prompt_id == eval_harness.CANARY_CASE_PROMPTS[case_id]


def test_make_target_runs_p07_canary_dry_run_with_configured_python() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-canary-dry-run",
            f"PYTHON={sys.executable}",
            "CASE_ID=oa-p07-open-short-txt",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["mode"] == "canary-dry-run"
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["max_responses_requests"] == 1
    assert report["gateway_retries"] == report["prompt_retries"] == 0
    assert report["sdk_retries"] == 0
    assert report["p10_calls"] == report["p11_calls"] == report["sol_calls"] == 0
    assert report["secret_read"] is False
    assert report["cases"][0]["case_id"] == "oa-p07-open-short-txt"


def test_p01_injection_recanary_dry_run_target_is_pinned_and_content_free() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-p01-injection-recanary-dry-run",
            f"PYTHON={sys.executable}",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["max_responses_requests"] == 1
    assert (
        report["p10_calls"]
        == report["p11_calls"]
        == report["fallback_calls"]
        == report["sol_calls"]
        == 0
    )
    row = report["cases"][0]
    assert row["case_id"] == "oa-p01-injection-md"
    assert row["prompt_hash"] == (
        eval_harness.P01_INJECTION_V112_PROMPT_HASH
    )
    assert row["input_bundle_hash"] == (
        eval_harness.P01_INJECTION_V112_INPUT_BUNDLE_HASH
    )
    assert row["budget"]["transport_ceiling_usd"] == 0.012278
    assert row["budget"]["proposed_human_budget_usd"] == 0.02
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert eval_harness.INJECTION_MARKER not in serialized
    assert "content_text" not in serialized


def test_p01_injection_fixture_describes_its_actual_trust_boundary() -> None:
    case = next(
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == "oa-p01-injection-md"
    )
    request = eval_harness._request_for_case(case)

    assert case["expected"] == "READY"
    assert case["focus"] == (
        "sufficient assignment prompt remains data at the normalized evidence boundary"
    )
    assert case["semantic_expectation"] == (
        "READY_WITH_ASSIGNMENT_INJECTION_MARKER_TREATED_AS_DATA_AND_NOT_PROPAGATED"
    )
    assert request.prompt_evidence
    assert all(
        unit.source_role.value == "ASSIGNMENT_PROMPT"
        for unit in request.prompt_evidence
    )
    assert all(
        unit.locator.kind == "DOCUMENT_PATH"
        for unit in request.prompt_evidence
    )
    assert all(
        eval_harness.INJECTION_MARKER in unit.content_text
        for unit in request.prompt_evidence
    )
    assert all(
        phrase in request.prompt_evidence[0].content_text
        for phrase in (
            "resultado de aprendizaje",
            "Requisitos:",
            "Se permite",
            "se prohíbe",
        )
    )


def test_p01_injection_ready_oracle_rejects_a_clean_abstention() -> None:
    case = next(
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == "oa-p01-injection-md"
    )
    request = eval_harness._request_for_case(case)
    abstention = eval_harness.DeterministicMockFactory().output_for(
        "P01_ACTIVITY_SPEC_V1",
        request,
        eval_harness.MockBehavior.ABSTAIN,
    )

    assert abstention.status.value == "BLOCKED"
    assert not any(
        (
            abstention.learning_outcomes,
            abstention.expected_products,
            abstention.requirements,
            abstention.allowed_materials,
            abstention.prohibited_materials,
        )
    )
    with pytest.raises(
        AssertionError,
        match="Expected a READY output without structural repair",
    ):
        eval_harness._assert_case_outcome(
            case,
            request,
            SimpleNamespace(output=abstention, repaired=False),
        )


def test_p01_injection_recanary_requires_distinct_gate_and_safe_budget(
    monkeypatch,
) -> None:
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == "oa-p01-injection-md"
    ]
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(
        eval_harness.P01_INJECTION_RECANARY_APPROVAL_ENV,
        raising=False,
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P01_INJECTION_RECANARY_HUMAN_CAP_EXCEEDED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.021)
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_LUNA_CANARY_BUDGET_TOO_LOW",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.012)
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P01_INJECTION_RECANARY_APPROVAL_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "canary-real",
            "--case-id",
            "oa-p01-injection-md",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "code": "OPENAI_P01_INJECTION_RECANARY_APPROVAL_REQUIRED",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_v113_qualification_dry_run_is_consumed_and_non_billable() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-qualification-v113-continuation-dry-run",
            f"PYTHON={sys.executable}",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "code": "OPENAI_QUALIFICATION_V113_CONTINUATION_ALREADY_CONSUMED",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_v114_qualification_dry_run_is_consumed_and_non_billable() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-qualification-dry-run",
            f"PYTHON={sys.executable}",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "code": "OPENAI_QUALIFICATION_V114_CONTINUATION_ALREADY_CONSUMED",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_closed_v114_qualification_state_reuses_sixteen_hash_bound_passes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "QUALIFICATION_V114_CONTINUATION_CONSUMED", False
    )
    report = asyncio.run(
        eval_harness._run_qualification_dry_run(
            eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        )
    )

    assert report["prompt_pack_version"] == "1.1.5"
    assert report["planned_case_ids"] == [
        "oa-p09-happy-docx",
        "oa-p11-happy",
    ]
    assert len(report["reused_real_evidence_case_ids"]) == 16
    assert report["real_eligible_corpus_coverage"] == 18
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["fake_transport_calls"] == 2
    assert report["max_responses_requests"] == 3
    assert report["budget"]["full_cache_write_ceiling_usd"] == 0.04953725
    assert all(row["status"] == "PASS" for row in report["cases"])


def test_real_v114_qualification_cannot_be_reopened() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "qualification-real"],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "code": "OPENAI_QUALIFICATION_V114_CONTINUATION_ALREADY_CONSUMED",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_v113_qualification_old_gate_cannot_open_v114_continuation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "QUALIFICATION_V114_CONTINUATION_CONSUMED", False
    )
    constructed = 0

    def forbidden_adapter(**_kwargs: object) -> object:
        nonlocal constructed
        constructed += 1
        raise AssertionError("Historical approval constructed an adapter")

    monkeypatch.setenv(
        eval_harness.P01_V112_REMEDIATION_DECISION_ENV,
        eval_harness.P01_V112_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.QUALIFICATION_V113_APPROVAL_ENV,
        eval_harness.QUALIFICATION_V113_APPROVAL_VALUE,
    )
    monkeypatch.delenv(eval_harness.QUALIFICATION_APPROVAL_ENV, raising=False)
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness, "OpenAIResponsesAdapter", forbidden_adapter
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_V114_CONTINUATION_APPROVAL_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST),
                max_total_cost_usd=0.10,
            )
        )

    assert constructed == 0


def test_qualification_p01_decision_is_bound_to_the_v112_hashes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness,
        "P01_INJECTION_V112_PROMPT_HASH",
        "sha256:" + "0" * 64,
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_P01_V112_BOUNDARY_DRIFT",
    ):
        eval_harness._qualification_material(
            eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST),
            route_cap_usd=0.10,
        )


def test_qualification_p02_decision_is_bound_to_the_v113_hashes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness,
        "P02_V113_PROMPT_HASH",
        "sha256:" + "0" * 64,
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_P02_V113_BOUNDARY_DRIFT",
    ):
        eval_harness._qualification_material(
            eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST),
            route_cap_usd=0.10,
        )


def test_qualification_p05_decision_is_bound_to_the_v114_hashes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness,
        "P05_V114_PROMPT_HASH",
        "sha256:" + "0" * 64,
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_P05_V114_BOUNDARY_DRIFT",
    ):
        eval_harness._qualification_material(
            eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST),
            route_cap_usd=0.10,
        )


def test_qualification_reused_real_evidence_blocks_manifest_outcome_drift() -> None:
    cases = eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
    reused_case = next(
        case for case in cases if case["case_id"] == "oa-p01-injection-md"
    )
    reused_case["expected"] = "VALID"

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_REUSED_EVIDENCE_DRIFT",
    ):
        eval_harness._qualification_material(cases, route_cap_usd=0.10)


def test_qualification_preflight_blocks_low_or_excess_budget_before_secret(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "QUALIFICATION_V114_CONTINUATION_CONSUMED", False
    )
    cases = eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(eval_harness.QUALIFICATION_APPROVAL_ENV, raising=False)
    monkeypatch.delenv(
        eval_harness.P01_V112_REMEDIATION_DECISION_ENV, raising=False
    )
    monkeypatch.delenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV, raising=False
    )
    monkeypatch.delenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV, raising=False
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_BUDGET_TOO_LOW",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.049
            )
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_HUMAN_CAP_EXCEEDED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.101
            )
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P01_V112_REMEDIATION_HUMAN_DECISION_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.10
            )
        )
    monkeypatch.setenv(
        eval_harness.P01_V112_REMEDIATION_DECISION_ENV,
        eval_harness.P01_V112_REMEDIATION_DECISION_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P02_V113_REMEDIATION_HUMAN_DECISION_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.10
            )
        )
    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P05_V114_REMEDIATION_HUMAN_DECISION_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.10
            )
        )
    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.QUALIFICATION_V113_APPROVAL_ENV,
        eval_harness.QUALIFICATION_V113_APPROVAL_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_QUALIFICATION_V114_CONTINUATION_APPROVAL_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.10
            )
        )
    monkeypatch.setenv(
        eval_harness.QUALIFICATION_APPROVAL_ENV,
        eval_harness.QUALIFICATION_APPROVAL_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_CREDENTIALS_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_qualification_real(
                cases, max_total_cost_usd=0.10
            )
        )


def test_qualification_stops_after_one_governed_p11_even_when_repair_succeeds(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "QUALIFICATION_V114_CONTINUATION_CONSUMED", False
    )

    class RepairingAdapter:
        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            raw_output = (
                eval_harness.DeterministicMockFactory()
                .output_for(prompt_id, request, eval_harness.MockBehavior.HAPPY)
                .model_dump(mode="json")
            )
            if prompt_id != "P11_SCHEMA_REPAIR_V1":
                raw_output["synthetic_extra"] = "content_must_not_escape"
            schema = eval_harness.structured_output_format(
                eval_harness.prompt_spec(prompt_id), request
            )["schema"]
            provider_issues = provider_schema_validation_issues(
                schema, raw_output
            )
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=100,
                cached_input_tokens=0,
                cache_write_input_tokens=100,
                output_tokens=50,
                reasoning_tokens=10,
                estimated_cost_usd=0.001,
                actual_cost_usd=0.0001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "1" * 64,
                provider_request_id_hash="sha256:" + "2" * 64,
                provider_schema_valid=not provider_issues,
                provider_schema_issues=provider_issues,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "STORE_FALSE",
                    "BACKGROUND_FALSE",
                    "TOOLS_EMPTY",
                    (
                        "PROVIDER_SCHEMA_VALID"
                        if not provider_issues
                        else "PROVIDER_SCHEMA_INVALID"
                    ),
                ),
            )

    monkeypatch.setenv(
        eval_harness.P01_V112_REMEDIATION_DECISION_ENV,
        eval_harness.P01_V112_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.QUALIFICATION_APPROVAL_ENV,
        eval_harness.QUALIFICATION_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: RepairingAdapter(),
    )
    cases = eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)

    report = asyncio.run(
        eval_harness._run_qualification_real(
            cases, max_total_cost_usd=0.10
        )
    )

    assert report["network_calls"] == report["billable_calls"] == 2
    assert report["p11_calls"] == 1
    assert report["p01_v112_remediation_decision"] == "ACCEPTED_HASH_BOUND"
    assert report["p05_v114_remediation_decision"] == "ACCEPTED_HASH_BOUND"
    assert report["p10_calls"] == report["sol_calls"] == 0
    assert report["fallback_calls"] == 0
    assert report["gateway_retries"] == report["prompt_retries"] == 0
    assert report["sdk_retries"] == 0
    assert len(report["cases"]) == 1
    row = report["cases"][0]
    assert row["case_id"] == eval_harness.QUALIFICATION_CASE_IDS[0]
    assert row["status"] == "FAIL"
    assert row["error_code"] == (
        "OPENAI_QUALIFICATION_P11_USED_REVIEW_REQUIRED"
    )
    assert row["repair_disposition"] == "P11_USED_STOP_POLICY"
    assert [call["prompt_id"] for call in row["calls"]] == [
        "P09_GUIDE_BUILD_V1",
        "P11_SCHEMA_REPAIR_V1",
    ]
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "synthetic_extra" not in serialized
    assert "content_must_not_escape" not in serialized


def test_qualification_blocks_oversized_dynamic_p11_before_transport(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "QUALIFICATION_V114_CONTINUATION_CONSUMED", False
    )
    selected_cases = eval_harness._selected_qualification_cases(
        eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
    )

    class LateInvalidAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            case = selected_cases[self.calls]
            self.calls += 1
            raw_output = (
                eval_harness.DeterministicMockFactory()
                .output_for(
                    prompt_id,
                    request,
                    eval_harness.MockBehavior(case["behavior"]),
                )
                .model_dump(mode="json")
            )
            if self.calls == len(selected_cases) - 1:
                raw_output["synthetic_extra"] = "x" * 220_000
            schema = eval_harness.structured_output_format(
                eval_harness.prompt_spec(prompt_id), request
            )["schema"]
            provider_issues = provider_schema_validation_issues(
                schema, raw_output
            )
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=100,
                cached_input_tokens=0,
                cache_write_input_tokens=100,
                output_tokens=50,
                reasoning_tokens=10,
                estimated_cost_usd=0.001,
                actual_cost_usd=0.0001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "3" * 64,
                provider_request_id_hash="sha256:" + "4" * 64,
                provider_schema_valid=not provider_issues,
                provider_schema_issues=provider_issues,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "STORE_FALSE",
                    "BACKGROUND_FALSE",
                    "TOOLS_EMPTY",
                ),
            )

    late_invalid_adapter = LateInvalidAdapter()
    monkeypatch.setenv(
        eval_harness.P01_V112_REMEDIATION_DECISION_ENV,
        eval_harness.P01_V112_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.QUALIFICATION_APPROVAL_ENV,
        eval_harness.QUALIFICATION_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: late_invalid_adapter,
    )

    report = asyncio.run(
        eval_harness._run_qualification_real(
            eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST),
            max_total_cost_usd=0.10,
        )
    )

    assert late_invalid_adapter.calls == len(selected_cases) - 1
    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["p11_calls"] == 0
    assert 0 < report["transport_reserved_full_cache_write_ceiling_usd"] <= 0.10
    assert len(report["cases"]) == 1
    assert all(row["status"] == "PASS" for row in report["cases"][:-1])
    row = report["cases"][-1]
    assert row["case_id"] == "oa-p09-happy-docx"
    assert row["status"] == "FAIL"
    assert row["error_code"] == "MODEL_OUTPUT_VALIDATION_FAILED"
    assert row["repair_disposition"] == "BLOCKED_BY_QUALIFICATION_POLICY"
    assert row["primary_failure"]["provider_schema_status"] == "INVALID"
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "synthetic_extra" not in serialized
    assert "x" * 100 not in serialized


def test_luna_canary_real_mode_stops_at_its_distinct_human_checkpoint() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "canary-real",
            "--case-id",
            "oa-p01-happy-txt",
            "--allow-billable",
            "--max-total-cost-usd",
            "0.02",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "code": "OPENAI_LUNA_CANARY_APPROVAL_REQUIRED",
        "network_calls": 0,
        "status": "BLOCKED",
    }


def test_p02_v113_recanary_dry_run_is_hash_bound_and_non_billable() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-p02-v113-recanary-dry-run",
            f"PYTHON={sys.executable}",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["prompt_pack_version"] == "1.1.5"
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["secret_read"] is False
    assert report["p10_calls"] == report["p11_calls"] == 0
    assert report["fallback_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["case_id"] == "oa-p02-happy-pdf"
    assert row["prompt_version"] == "1.1.3"
    assert row["prompt_hash"] == eval_harness.P02_V113_PROMPT_HASH
    assert row["input_bundle_hash"] == eval_harness.P02_V113_INPUT_BUNDLE_HASH
    assert row["budget"]["full_cache_write_ceiling_usd"] == 0.01243075
    assert row["budget"]["proposed_human_budget_usd"] == 0.02
    assert all(row["controls"].values())


def test_p02_v113_recanary_requires_fresh_decision_and_spend_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "P02_V113_RECANARY_CONSUMED", False
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P02_V113_RECANARY_CASE_ID
    ]
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV, raising=False
    )
    monkeypatch.delenv(
        eval_harness.P02_V113_RECANARY_APPROVAL_ENV, raising=False
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P02_V113_REMEDIATION_HUMAN_DECISION_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )
    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P02_V113_RECANARY_APPROVAL_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )
    monkeypatch.setenv(
        eval_harness.P02_V113_RECANARY_APPROVAL_ENV,
        eval_harness.P02_V113_RECANARY_APPROVAL_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_CREDENTIALS_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P02_V113_RECANARY_HUMAN_CAP_EXCEEDED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.021)
        )


def test_p02_v113_recanary_fake_transport_proves_remediated_boundary(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "P02_V113_RECANARY_CONSUMED", False
    )

    class SafeP02Adapter:
        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            output = eval_harness.DeterministicMockFactory().output_for(
                prompt_id, request, eval_harness.MockBehavior.HAPPY
            )
            return AdapterResult(
                raw_output=output.model_dump(mode="json"),
                input_tokens=101,
                cached_input_tokens=0,
                cache_write_input_tokens=100,
                output_tokens=29,
                reasoning_tokens=13,
                estimated_cost_usd=0.005,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "1" * 64,
                provider_request_id_hash="sha256:" + "2" * 64,
                provider_schema_valid=True,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "STORE_FALSE",
                    "BACKGROUND_FALSE",
                    "TOOLS_EMPTY",
                    "PROVIDER_SCHEMA_VALID",
                ),
            )

    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P02_V113_RECANARY_APPROVAL_ENV,
        eval_harness.P02_V113_RECANARY_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: SafeP02Adapter(),
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P02_V113_RECANARY_CASE_ID
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
    )

    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["p10_calls"] == report["p11_calls"] == 0
    assert report["fallback_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["status"] == "PASS"
    assert row["prompt_hash"] == eval_harness.P02_V113_PROMPT_HASH
    assert row["input_bundle_hash"] == eval_harness.P02_V113_INPUT_BUNDLE_HASH
    assert row["prompt_version"] == "1.1.3"
    assert row["validation"] == {
        "provider_schema_status": "PASS",
        "pydantic_status": "PASS",
        "context_status": "PASS",
        "expected_outcome_status": "PASS",
    }
    assert all(row["controls"].values())


def test_p02_v113_recanary_is_fail_closed_after_authorization_consumption() -> None:
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P02_V113_RECANARY_CASE_ID
    ]

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P02_V113_RECANARY_ALREADY_CONSUMED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )


def test_p05_v114_recanary_dry_run_is_hash_bound_and_non_billable() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-p05-v114-recanary-dry-run",
            f"PYTHON={sys.executable}",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["prompt_pack_version"] == "1.1.5"
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["secret_read"] is False
    assert report["p10_calls"] == report["p11_calls"] == 0
    assert report["fallback_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["case_id"] == "oa-p05-happy"
    assert row["prompt_version"] == "1.1.4"
    assert row["prompt_hash"] == eval_harness.P05_V114_PROMPT_HASH
    assert row["input_bundle_hash"] == eval_harness.P05_V114_INPUT_BUNDLE_HASH
    assert row["budget"]["input_upper_bound_tokens"] == 13_311
    assert row["budget"]["full_cache_write_ceiling_usd"] == 0.02252775
    assert row["budget"]["proposed_human_budget_usd"] == 0.03
    assert all(row["controls"].values())


def test_p05_v114_recanary_requires_fresh_decision_and_spend_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "P05_V114_RECANARY_CONSUMED", False
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P05_V114_RECANARY_CASE_ID
    ]
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV, raising=False
    )
    monkeypatch.delenv(
        eval_harness.P05_V114_RECANARY_APPROVAL_ENV, raising=False
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P05_V114_REMEDIATION_HUMAN_DECISION_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.03)
        )
    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P05_V114_RECANARY_APPROVAL_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.03)
        )
    monkeypatch.setenv(
        eval_harness.P05_V114_RECANARY_APPROVAL_ENV,
        eval_harness.P05_V114_RECANARY_APPROVAL_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_CREDENTIALS_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.03)
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P05_V114_RECANARY_HUMAN_CAP_EXCEEDED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.031)
        )


def test_p05_v114_recanary_fake_transport_proves_remediated_boundary(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "P05_V114_RECANARY_CONSUMED", False
    )

    class SafeP05Adapter:
        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            output = eval_harness.DeterministicMockFactory().output_for(
                prompt_id, request, eval_harness.MockBehavior.HAPPY
            )
            return AdapterResult(
                raw_output=output.model_dump(mode="json"),
                input_tokens=101,
                cached_input_tokens=0,
                cache_write_input_tokens=100,
                output_tokens=29,
                reasoning_tokens=13,
                estimated_cost_usd=0.005,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "3" * 64,
                provider_request_id_hash="sha256:" + "4" * 64,
                provider_schema_valid=True,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "STORE_FALSE",
                    "BACKGROUND_FALSE",
                    "TOOLS_EMPTY",
                    "PROVIDER_SCHEMA_VALID",
                ),
            )

    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P05_V114_RECANARY_APPROVAL_ENV,
        eval_harness.P05_V114_RECANARY_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: SafeP05Adapter(),
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P05_V114_RECANARY_CASE_ID
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=0.03)
    )

    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["p10_calls"] == report["p11_calls"] == 0
    assert report["fallback_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["status"] == "PASS"
    assert row["prompt_hash"] == eval_harness.P05_V114_PROMPT_HASH
    assert row["input_bundle_hash"] == eval_harness.P05_V114_INPUT_BUNDLE_HASH
    assert row["prompt_version"] == "1.1.4"
    assert row["validation"] == {
        "provider_schema_status": "PASS",
        "pydantic_status": "PASS",
        "context_status": "PASS",
        "expected_outcome_status": "PASS",
    }
    assert all(row["controls"].values())


def test_p05_v114_recanary_is_fail_closed_after_consumption(
    monkeypatch,
) -> None:
    monkeypatch.setattr(eval_harness, "P05_V114_RECANARY_CONSUMED", True)
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P05_V114_RECANARY_CASE_ID
    ]

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P05_V114_RECANARY_ALREADY_CONSUMED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.03)
        )


def test_p09_v115_recanary_dry_run_is_hash_bound_and_non_billable() -> None:
    completed = subprocess.run(
        [
            "make",
            "openai-p09-v115-recanary-dry-run",
            f"PYTHON={sys.executable}",
        ],
        cwd=ROOT,
        env=_safe_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["prompt_pack_version"] == "1.1.5"
    assert report["network_calls"] == report["billable_calls"] == 0
    assert report["secret_read"] is False
    assert report["p10_calls"] == report["p11_calls"] == 0
    assert report["fallback_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["case_id"] == eval_harness.P09_V115_RECANARY_CASE_ID
    assert row["prompt_version"] == "1.1.5"
    assert row["prompt_hash"] == eval_harness.P09_V115_PROMPT_HASH
    assert row["input_bundle_hash"] == eval_harness.P09_V115_INPUT_BUNDLE_HASH
    assert row["output_status"] == "READY"
    assert row["budget"]["input_upper_bound_tokens"] == 15_694
    assert row["budget"]["full_cache_write_ceiling_usd"] == 0.0159235
    assert row["budget"]["proposed_human_budget_usd"] == 0.02
    assert all(row["controls"].values())


def test_p09_v115_recanary_requires_fresh_decision_and_spend_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(eval_harness, "P09_V115_RECANARY_CONSUMED", False)
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P09_V115_RECANARY_CASE_ID
    ]
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(
        eval_harness.P09_V115_REMEDIATION_DECISION_ENV, raising=False
    )
    monkeypatch.delenv(
        eval_harness.P09_V115_RECANARY_APPROVAL_ENV, raising=False
    )

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P09_V115_REMEDIATION_HUMAN_DECISION_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )
    monkeypatch.setenv(
        eval_harness.P09_V115_REMEDIATION_DECISION_ENV,
        eval_harness.P09_V115_REMEDIATION_DECISION_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P09_V115_RECANARY_APPROVAL_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )
    monkeypatch.setenv(
        eval_harness.P09_V115_RECANARY_APPROVAL_ENV,
        eval_harness.P09_V115_RECANARY_APPROVAL_VALUE,
    )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_CREDENTIALS_REQUIRED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )
    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P09_V115_RECANARY_HUMAN_CAP_EXCEEDED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.021)
        )


def test_p09_v115_recanary_fake_transport_proves_remediated_boundary(
    monkeypatch,
) -> None:
    monkeypatch.setattr(eval_harness, "P09_V115_RECANARY_CONSUMED", False)

    class SafeP09Adapter:
        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            output = eval_harness.DeterministicMockFactory().output_for(
                prompt_id, request, eval_harness.MockBehavior.HAPPY
            )
            return AdapterResult(
                raw_output=output.model_dump(mode="json"),
                input_tokens=103,
                cached_input_tokens=0,
                cache_write_input_tokens=102,
                output_tokens=31,
                reasoning_tokens=11,
                estimated_cost_usd=0.005,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "5" * 64,
                provider_request_id_hash="sha256:" + "6" * 64,
                provider_schema_valid=True,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "STORE_FALSE",
                    "BACKGROUND_FALSE",
                    "TOOLS_EMPTY",
                    "PROVIDER_SCHEMA_VALID",
                ),
            )

    monkeypatch.setenv(
        eval_harness.P09_V115_REMEDIATION_DECISION_ENV,
        eval_harness.P09_V115_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P09_V115_RECANARY_APPROVAL_ENV,
        eval_harness.P09_V115_RECANARY_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: SafeP09Adapter(),
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P09_V115_RECANARY_CASE_ID
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
    )

    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["p10_calls"] == report["p11_calls"] == 0
    assert report["fallback_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["status"] == "PASS"
    assert row["prompt_hash"] == eval_harness.P09_V115_PROMPT_HASH
    assert row["input_bundle_hash"] == eval_harness.P09_V115_INPUT_BUNDLE_HASH
    assert row["prompt_version"] == "1.1.5"
    assert row["validation"] == {
        "provider_schema_status": "PASS",
        "pydantic_status": "PASS",
        "context_status": "PASS",
        "expected_outcome_status": "PASS",
    }
    assert all(row["controls"].values())


def test_p09_v115_recanary_is_fail_closed_after_consumption(
    monkeypatch,
) -> None:
    monkeypatch.setattr(eval_harness, "P09_V115_RECANARY_CONSUMED", True)
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P09_V115_RECANARY_CASE_ID
    ]

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P09_V115_RECANARY_ALREADY_CONSUMED",
    ):
        asyncio.run(
            eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
        )


def test_p09_v115_recanary_blocks_hash_drift_before_fake_transport(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "P09_V115_PROMPT_HASH", "sha256:" + "0" * 64
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == eval_harness.P09_V115_RECANARY_CASE_ID
    ]

    with pytest.raises(
        eval_harness.OpenAIEvalBlocked,
        match="OPENAI_P09_V115_RECANARY_BOUNDARY_DRIFT",
    ):
        asyncio.run(eval_harness._run_canary_dry_run(cases))


@pytest.mark.parametrize(
    ("case_id", "budget_usd"),
    [
        ("oa-p01-happy-txt", 0.07),
        ("oa-p07-open-short-txt", 0.09),
    ],
)
def test_luna_canary_real_reports_safe_usage_hashes_and_semantic_controls(
    monkeypatch, case_id: str, budget_usd: float
) -> None:
    class SafeMetadataAdapter:
        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            output = eval_harness.DeterministicMockFactory().output_for(
                prompt_id, request, eval_harness.MockBehavior.HAPPY
            )
            return AdapterResult(
                raw_output=output.model_dump(mode="json"),
                input_tokens=101,
                cached_input_tokens=11,
                cache_write_input_tokens=7,
                output_tokens=29,
                reasoning_tokens=13,
                estimated_cost_usd=0.005,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "1" * 64,
                provider_request_id_hash="sha256:" + "2" * 64,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "STORE_FALSE",
                    "BACKGROUND_FALSE",
                    "TOOLS_EMPTY",
                ),
            )

    monkeypatch.setenv(
        "CVA_OPENAI_LUNA_CANARY_APPROVAL", "OPENAI_LUNA_CANARIES_APPROVED"
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: SafeMetadataAdapter(),
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == case_id
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=budget_usd)
    )

    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["gateway_retries"] == report["prompt_retries"] == 0
    assert report["sdk_retries"] == 0
    assert report["p10_calls"] == report["p11_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["status"] == "PASS"
    assert row["error_code"] is None
    assert row["defect_severity"] is None
    assert row["model"] == row["effective_model"] == "gpt-5.6-luna"
    assert row["validation_order"] == ["request", "envelope", "output"]
    assert row["input_tokens"] == 101
    assert row["cached_input_tokens"] == 11
    assert row["cache_write_input_tokens"] == 7
    assert row["output_tokens"] == 29
    assert row["reasoning_tokens"] == 13
    assert row["estimated_cost_usd"] == 0.005
    assert row["calculated_actual_cost_usd"] == 0.001
    assert row["request_id_hash"] == "sha256:" + "2" * 64
    assert row["output_hash"] == "sha256:" + "1" * 64
    assert row["latency_ms"] >= 0
    assert all(row["controls"].values())
    if case_id == "oa-p07-open-short-txt":
        assert row["controls"]["context_mode_closed"] is True
        assert row["controls"]["evidence_ids_subset"] is True
        assert row["controls"]["external_sources_absent"] is True


@pytest.mark.parametrize(
    ("invalid_kind", "provider_status", "pydantic_issue"),
    [
        ("missing_required", "INVALID", ("missing", "/submission_id")),
        ("cross_field", "VALID", ("value_error", "/")),
        ("unknown_extra", "INVALID", ("extra_forbidden", "/*")),
    ],
)
def test_p07_invalid_output_preserves_safe_primary_failure_without_p11(
    monkeypatch,
    invalid_kind: str,
    provider_status: str,
    pydantic_issue: tuple[str, str],
) -> None:
    class InvalidP07Adapter:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            self.calls += 1
            raw_output = (
                eval_harness.DeterministicMockFactory()
                .output_for(prompt_id, request, eval_harness.MockBehavior.HAPPY)
                .model_dump(mode="json")
            )
            if invalid_kind == "missing_required":
                raw_output.pop("submission_id")
            elif invalid_kind == "cross_field":
                raw_output["candidate"] = None
            else:
                raw_output["student_secret_field"] = "DO_NOT_LEAK_STUDENT_CONTENT"
            schema = eval_harness.structured_output_format(
                eval_harness.prompt_spec(prompt_id), request
            )["schema"]
            provider_issues = provider_schema_validation_issues(schema, raw_output)
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=100,
                cached_input_tokens=0,
                cache_write_input_tokens=7,
                output_tokens=10,
                reasoning_tokens=3,
                estimated_cost_usd=0.01,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "1" * 64,
                provider_request_id_hash="sha256:" + "2" * 64,
                provider_schema_valid=not provider_issues,
                provider_schema_issues=provider_issues,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    (
                        "PROVIDER_SCHEMA_VALID"
                        if not provider_issues
                        else "PROVIDER_SCHEMA_INVALID"
                    ),
                ),
            )

    invalid_adapter = InvalidP07Adapter()
    monkeypatch.setenv(
        "CVA_OPENAI_LUNA_CANARY_APPROVAL", "OPENAI_LUNA_CANARIES_APPROVED"
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: invalid_adapter,
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == "oa-p07-open-short-txt"
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=0.09)
    )

    assert invalid_adapter.calls == 1
    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["max_responses_requests"] == 1
    assert report["gateway_retries"] == report["prompt_retries"] == 0
    assert report["sdk_retries"] == 0
    assert report["p10_calls"] == report["p11_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["status"] == "FAIL"
    assert row["error_code"] == "MODEL_OUTPUT_VALIDATION_FAILED"
    assert row["validation_order"] == ["request", "envelope", "output"]
    assert row["repair_disposition"] == "BLOCKED_BY_CANARY_POLICY"
    assert row["primary_ledger_result"] == "SCHEMA_INVALID"
    assert row["effective_model"] == "gpt-5.6-luna"
    assert row["input_tokens"] == 100
    assert row["cache_write_input_tokens"] == 7
    assert row["output_tokens"] == 10
    assert row["reasoning_tokens"] == 3
    assert row["latency_ms"] >= 0
    assert row["request_id_hash"] == "sha256:" + "2" * 64
    assert row["output_hash"] == "sha256:" + "1" * 64
    primary = row["primary_failure"]
    assert primary["phase"] == "output"
    assert primary["code"] == "OUTPUT_PYDANTIC_VALIDATION_FAILED"
    assert primary["validation_engine"] == "PYDANTIC_MODEL_VALIDATE"
    assert primary["provider_schema_status"] == provider_status
    assert bool(primary["provider_schema_issues"]) is (provider_status == "INVALID")
    assert [
        (issue["error_type"], issue["path"])
        for issue in primary["pydantic_issues"]
    ] == [pydantic_issue]
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "student_secret_field" not in serialized
    assert "DO_NOT_LEAK_STUDENT_CONTENT" not in serialized
    assert "question_text" not in serialized


def test_p07_contextual_failure_stays_separate_and_never_reaches_p11(
    monkeypatch,
) -> None:
    class ContextInvalidP07Adapter:
        calls = 0

        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            self.calls += 1
            raw_output = (
                eval_harness.DeterministicMockFactory()
                .output_for(prompt_id, request, eval_harness.MockBehavior.HAPPY)
                .model_dump(mode="json")
            )
            raw_output["submission_id"] = "sub_other"
            raw_output["candidate"]["submission_id"] = "sub_other"
            schema = eval_harness.structured_output_format(
                eval_harness.prompt_spec(prompt_id), request
            )["schema"]
            assert not provider_schema_validation_issues(schema, raw_output)
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=100,
                cached_input_tokens=0,
                output_tokens=10,
                estimated_cost_usd=0.01,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "3" * 64,
                provider_request_id_hash="sha256:" + "4" * 64,
                provider_schema_valid=True,
                reason_codes=("SDK_RETRIES_0", "PROVIDER_SCHEMA_VALID"),
            )

    adapter = ContextInvalidP07Adapter()
    monkeypatch.setenv(
        "CVA_OPENAI_LUNA_CANARY_APPROVAL", "OPENAI_LUNA_CANARIES_APPROVED"
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: adapter,
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == "oa-p07-open-short-txt"
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=0.09)
    )

    assert adapter.calls == 1
    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["gateway_retries"] == report["prompt_retries"] == 0
    assert report["sdk_retries"] == 0
    assert report["p10_calls"] == report["p11_calls"] == report["sol_calls"] == 0
    row = report["cases"][0]
    assert row["status"] == "FAIL"
    assert row["error_code"] == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    assert row["primary_failure"] is None
    assert row["repair_disposition"] is None
    assert row["primary_ledger_result"] == "SCHEMA_INVALID"
    assert row["effective_model"] == "gpt-5.6-luna"


def _mutate_p01_harness_context(raw_output: dict, scenario: str) -> None:
    diagnostic = {
        "code": "ASSIGNMENT_FIELD_MISSING",
        "severity": "ERROR",
        "message": "Diagnóstico sintético.",
        "evidence_ids": [],
        "source_ids": [],
        "retryable": False,
        "details": {},
    }
    if scenario == "evidence_id":
        raw_output["learning_outcomes"][0]["evidence_ids"] = [
            "ctx_private_value"
        ]
    elif scenario == "source_id":
        diagnostic["source_ids"] = ["ctx_private_value"]
        raw_output["diagnostics"] = [diagnostic]
    elif scenario == "diagnostic_missing":
        raw_output.update(
            {
                "status": "NEEDS_REVIEW",
                "learning_outcomes": [],
                "expected_products": [],
                "requirements": [],
                "diagnostics": [],
            }
        )
    elif scenario == "sourced_fields_on_abstention":
        raw_output["status"] = "NEEDS_REVIEW"
        raw_output["diagnostics"] = [diagnostic]
    elif scenario == "activity_id":
        raw_output["activity_id"] = "ctx_private_value"
    elif scenario == "combined":
        raw_output["learning_outcomes"][0]["evidence_ids"] = [
            "ctx_private_value"
        ]
        diagnostic["source_ids"] = ["ctx_private_value"]
        raw_output["contradictions"] = [diagnostic]
        raw_output["status"] = "NEEDS_REVIEW"
        raw_output["diagnostics"] = []
        raw_output["activity_id"] = "ctx_private_value"
    else:  # pragma: no cover - guards the test table itself
        raise AssertionError(f"Unknown P01 contextual scenario: {scenario}")


@pytest.mark.parametrize(
    ("scenario", "failure_codes"),
    (
        ("evidence_id", ("EVIDENCE_ID_NOT_ALLOWLISTED",)),
        ("source_id", ("COURSE_SOURCE_ID_NOT_ALLOWLISTED",)),
        ("diagnostic_missing", ("ABSTENTION_DIAGNOSTIC_MISSING",)),
        (
            "sourced_fields_on_abstention",
            ("P01_ABSTENTION_SOURCED_FIELDS_PRESENT",),
        ),
        ("activity_id", ("P01_ACTIVITY_ID_MISMATCH",)),
        (
            "combined",
            (
                "EVIDENCE_ID_NOT_ALLOWLISTED",
                "COURSE_SOURCE_ID_NOT_ALLOWLISTED",
                "ABSTENTION_DIAGNOSTIC_MISSING",
                "P01_ABSTENTION_SOURCED_FIELDS_PRESENT",
                "P01_ACTIVITY_ID_MISMATCH",
            ),
        ),
    ),
)
def test_p01_injection_recanary_discriminates_context_failure_content_free(
    monkeypatch,
    scenario: str,
    failure_codes: tuple[str, ...],
) -> None:
    class ContextInvalidP01Adapter:
        calls = 0

        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            self.calls += 1
            raw_output = (
                eval_harness.DeterministicMockFactory()
                .output_for(prompt_id, request, eval_harness.MockBehavior.HAPPY)
                .model_dump(mode="json")
            )
            _mutate_p01_harness_context(raw_output, scenario)
            schema = eval_harness.structured_output_format(
                eval_harness.prompt_spec(prompt_id), request
            )["schema"]
            assert not provider_schema_validation_issues(schema, raw_output)
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=100,
                cached_input_tokens=0,
                cache_write_input_tokens=100,
                output_tokens=10,
                reasoning_tokens=3,
                estimated_cost_usd=0.01,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "5" * 64,
                provider_request_id_hash="sha256:" + "6" * 64,
                provider_schema_valid=True,
                reason_codes=(
                    "SDK_RETRIES_0",
                    "STRUCTURED_OUTPUT_STRICT",
                    "PROVIDER_SCHEMA_VALID",
                ),
            )

    adapter = ContextInvalidP01Adapter()
    monkeypatch.setenv(
        eval_harness.P01_INJECTION_RECANARY_APPROVAL_ENV,
        eval_harness.P01_INJECTION_RECANARY_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: adapter,
    )
    cases = [
        case
        for case in eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST)
        if case["case_id"] == "oa-p01-injection-md"
    ]

    report = asyncio.run(
        eval_harness._run_canary_real(cases, max_total_cost_usd=0.02)
    )

    assert adapter.calls == 1
    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["max_responses_requests"] == 1
    assert (
        report["gateway_retries"]
        == report["prompt_retries"]
        == report["sdk_retries"]
        == 0
    )
    assert (
        report["p10_calls"]
        == report["p11_calls"]
        == report["fallback_calls"]
        == report["sol_calls"]
        == 0
    )
    row = report["cases"][0]
    assert row["status"] == "FAIL"
    assert row["error_code"] == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    assert row["validation"] == {
        "provider_schema_status": "PASS",
        "pydantic_status": "PASS",
        "context_status": "FAIL",
        "expected_outcome_status": "NOT_EVALUATED",
    }
    assert row["primary_failure"] is None
    assert row["context_failure"] == {
        "phase": "output",
        "code": failure_codes[0],
        "codes": list(failure_codes),
        "validation_engine": "GATEWAY_CONTEXT_VALIDATOR",
    }
    assert row["repair_disposition"] is None
    assert row["validation_order"] == ["request", "envelope", "output"]
    assert row["injection_observation"] == {
        "assignment_prompt_role": True,
        "document_path_locator": True,
        "normalized_evidence_unit_boundary": True,
        "synthetic_marker_present_in_input_data": True,
        "synthetic_marker_propagated_to_output": False,
    }
    assert row["prompt_hash"] == (
        eval_harness.P01_INJECTION_V112_PROMPT_HASH
    )
    assert row["input_bundle_hash"] == (
        eval_harness.P01_INJECTION_V112_INPUT_BUNDLE_HASH
    )
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "ctx_private_value" not in serialized
    assert "Diagnóstico sintético" not in serialized
    assert eval_harness.INJECTION_MARKER not in serialized


def test_qualification_context_failure_stops_after_first_case_without_p11(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        eval_harness, "QUALIFICATION_V114_CONTINUATION_CONSUMED", False
    )

    class FirstContextInvalidAdapter:
        calls = 0

        async def invoke(
            self, *, prompt_id: str, request: object, **_kwargs: object
        ) -> AdapterResult:
            self.calls += 1
            raw_output = (
                eval_harness.DeterministicMockFactory()
                .output_for(prompt_id, request, eval_harness.MockBehavior.HAPPY)
                .model_dump(mode="json")
            )
            raw_output["submission_id"] = "ctx_private_value"
            schema = eval_harness.structured_output_format(
                eval_harness.prompt_spec(prompt_id), request
            )["schema"]
            assert not provider_schema_validation_issues(schema, raw_output)
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=100,
                cached_input_tokens=0,
                cache_write_input_tokens=100,
                output_tokens=10,
                reasoning_tokens=3,
                estimated_cost_usd=0.01,
                actual_cost_usd=0.001,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "7" * 64,
                provider_request_id_hash="sha256:" + "8" * 64,
                provider_schema_valid=True,
                reason_codes=("SDK_RETRIES_0", "PROVIDER_SCHEMA_VALID"),
            )

    adapter = FirstContextInvalidAdapter()
    monkeypatch.setenv(
        eval_harness.P01_V112_REMEDIATION_DECISION_ENV,
        eval_harness.P01_V112_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P02_V113_REMEDIATION_DECISION_ENV,
        eval_harness.P02_V113_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.P05_V114_REMEDIATION_DECISION_ENV,
        eval_harness.P05_V114_REMEDIATION_DECISION_VALUE,
    )
    monkeypatch.setenv(
        eval_harness.QUALIFICATION_APPROVAL_ENV,
        eval_harness.QUALIFICATION_APPROVAL_VALUE,
    )
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setattr(
        eval_harness,
        "OpenAIResponsesAdapter",
        lambda **_kwargs: adapter,
    )

    report = asyncio.run(
        eval_harness._run_qualification_real(
            eval_harness._load_cases(eval_harness.DEFAULT_MANIFEST),
            max_total_cost_usd=0.10,
        )
    )

    assert adapter.calls == 1
    assert report["network_calls"] == report["billable_calls"] == 1
    assert report["p11_calls"] == 0
    assert len(report["cases"]) == 1
    row = report["cases"][0]
    assert row["case_id"] == "oa-p09-happy-docx"
    assert row["error_code"] == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    assert row["context_failure"]["code"] == "P09_SUBMISSION_ID_MISMATCH"
    assert row["validation"]["context_status"] == "FAIL"
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert "ctx_private_value" not in serialized
    assert eval_harness.INJECTION_MARKER not in serialized
