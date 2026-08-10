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
            "prompt_version": "1.1.1",
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
        "worst_case_usd",
    ),
    (
        (
            "oa-p01-happy-txt",
            "P01_ACTIVITY_SPEC_V1",
            "MEDIUM",
            8_608,
            3_111,
            9_632,
            8_000,
            0.0115264,
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
    worst_case_usd: float,
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
    assert report["p10_calls"] == report["p11_calls"] == report["sol_calls"] == 0
    assert report["secret_read"] is False
    row = report["cases"][0]
    assert row["case_id"] == case_id
    assert row["provider"] == "openai"
    assert row["model"] == row["effective_model"] == "gpt-5.6-luna"
    assert row["reasoning_effort"] == reasoning
    assert row["prompt_version"] == "1.1.1"
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
    assert budget["worst_case_usd"] == worst_case_usd
    assert budget["cache_assumption"] == "NONE"
    assert budget["pricing_standard_short_context_usd_per_million"] == {
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
