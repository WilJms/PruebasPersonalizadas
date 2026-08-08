from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from scripts import run_openai_evals as eval_harness


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_openai_evals.py"


def _safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("CVA_OPENAI_API_KEY", None)
    environment.pop("CVA_OPENAI_REAL_EVALS_APPROVAL", None)
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
                        route=SimpleNamespace(model="gpt-5.6-sol"),
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
            "error_code": "OPENAI_REAL_EVAL_EXPECTATION_FAILED",
            "model": "gpt-5.6-sol",
            "status": "FAIL",
        }
    ]
