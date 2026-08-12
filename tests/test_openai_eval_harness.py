from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
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
)
from comprehension_verification.rehearsal import (
    BASE_SCENARIO_ID,
    P05_GOLDEN_FIXTURE_PATH,
    VARIANT_SCENARIO_ID,
    build_p05_golden_negative_request,
    build_rehearsal_checkpoints,
    evaluate_p05_golden_negative,
    evaluate_p05_golden_positive,
    p08_decision_diagnostics,
    rehearsal_boundary_material,
    run_offline_convergence,
    run_real_convergence,
)
from scripts import run_openai_evals as eval_harness


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_openai_evals.py"
FIXTURE = (
    ROOT
    / "tests/fixtures/openai_evals/v2/product_rehearsal.json"
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
        "stage2-product-rehearsal-fixture/1.4.0"
    )
    assert raw["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    assert raw["p05_golden_fixture"] == (
        "tests/fixtures/openai_evals/v2/p05_golden_checkpoints.json"
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
            "P04",
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
        ],
        "p06_receives_planning_policy": True,
        "failures_are_content_free": True,
    }


def test_p05_golden_positive_is_semantically_qualified_and_negative_is_known() -> None:
    raw = json.loads(P05_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "stage2-p05-golden-checkpoints/1.1.0"
    assert raw["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    semantic_review = raw["golden_positive"]["semantic_review"]
    assert semantic_review["status"] == (
        "SEMANTICALLY_REVIEWED_SYNTHETIC_FIXTURE"
    )
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


def test_offline_convergence_executes_sweep_two_chains_and_variant() -> None:
    report = asyncio.run(run_offline_convergence())
    assert report["status"] == "PASS"
    assert [item["run_id"] for item in report["observations"]] == [
        "sweep-base",
        "chain-base-1",
        "chain-base-2",
        "chain-choice-variant",
    ]
    assert all(item["status"] == "PASS" for item in report["observations"])
    assert [len(item["stages"]) for item in report["observations"]] == [
        6,
        8,
        8,
        8,
    ]
    assert report["controls"] == {
        "p10_calls": 0,
        "p11_calls": 0,
        "fallback_calls": 0,
        "semantic_retries": 0,
        "provider_attempts": 24,
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
        lambda **_kwargs: DeterministicMockAdapter(),
    )
    report = asyncio.run(
        run_real_convergence(
            api_key=SecretStr("sk-project-synthetic-placeholder-not-real"),
            max_total_cost_usd=0.75,
            max_call_cost_usd=0.10,
            max_provider_requests=30,
        )
    )
    assert report["status"] == "PASS"
    assert report["unchanged_boundary_across_chains"] is True
    assert report["controls"]["network_calls"] == 24
    assert report["controls"]["provider_attempts"] == 24
    assert report["controls"]["unpriced_attempts"] == 0
    assert report["controls"]["budget_charged_usd"] <= 0.75
    assert report["controls"]["models"] == ["gpt-5.6-luna"]
    assert report["controls"]["p10_calls"] == 0
    assert report["controls"]["p11_calls"] == 0
    assert report["controls"]["fallback_calls"] == 0


def test_real_convergence_accounts_for_context_invalid_billable_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CostedContextInvalidAdapter(DeterministicMockAdapter):
        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await super().invoke(**kwargs)  # type: ignore[arg-type]
            raw = deepcopy(result.raw_output)
            if kwargs["prompt_id"] == "P04_BLUEPRINT_BUILD_V1":
                raw["blueprint_id"] = "blueprint_outside_target_scope"
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
            max_provider_requests=30,
        )
    )
    assert report["status"] == "FAIL"
    # The independent sweep still observes P05-P09 after the P04 checkpoint
    # fails; each of the three integrated chains then stops at its own P04.
    assert report["controls"]["network_calls"] == 9
    assert report["controls"]["provider_attempts"] == 9
    assert report["controls"]["actual_cost_usd"] == 0.09
    assert report["controls"]["budget_charged_usd"] == 0.108
    assert report["controls"]["unpriced_attempts"] == 0
    sweep = report["observations"][0]
    assert sweep["failure"]["aggregated_failures"] == [
        {
            "stage": "P04",
            "codes": ["CONTEXT_INVARIANT_FAILED"],
            "issues": [],
        }
    ]
    assert [row["prompt_id"] for row in sweep["stages"]] == [
        "P05_BLUEPRINT_REVIEW_V1",
        "P06_EVIDENCE_MAP_V1",
        "P07_QUESTION_BUILD_V1",
        "P08_QUESTION_REVIEW_V1",
        "P09_GUIDE_BUILD_V1",
    ]


def _real_cli_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        mode="convergence-real",
        manifest=eval_harness.DEFAULT_MANIFEST,
        case_id=[],
        allow_billable=True,
        max_total_cost_usd=0.75,
        max_call_cost_usd=0.10,
        max_provider_requests=24,
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
