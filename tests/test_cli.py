from __future__ import annotations

import json
from types import SimpleNamespace

import comprehension_verification.cli as cli_module
from comprehension_verification.cli import main
from comprehension_verification.model_gateway import GatewayProviderError


def test_real_smoke_without_budget_is_blocked_before_network(capsys) -> None:
    result = main(["real-provider-smoke", "--budget-usd", "0"])

    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output == {
        "code": "REAL_SMOKE_BUDGET_REQUIRED",
        "network_call_attempted": False,
        "status": "BLOCKED",
    }


def test_real_smoke_with_budget_stops_at_credentials_without_network(
    capsys, monkeypatch
) -> None:
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    result = main(["real-provider-smoke", "--budget-usd", "0.06"])
    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["code"] == "OPENAI_CREDENTIALS_REQUIRED"
    assert output["network_call_attempted"] is False


def test_real_smoke_with_placeholder_key_stops_at_human_spend_gate(
    capsys, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.delenv("CVA_OPENAI_BILLABLE_SMOKE_APPROVAL", raising=False)
    result = main(["real-provider-smoke", "--budget-usd", "0.06"])
    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["code"] == "OPENAI_BILLABLE_SMOKE_APPROVAL_REQUIRED"
    assert output["network_call_attempted"] is False


def test_real_smoke_sanitizes_provider_failure_after_an_attempt(
    capsys, monkeypatch
) -> None:
    class FailingGateway:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def invoke(self, *_args, **_kwargs):
            raise GatewayProviderError(
                "provider detail must not escape",
                ledgers=[SimpleNamespace(actual_cost_usd=None)],
            )

    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setenv(
        "CVA_OPENAI_BILLABLE_SMOKE_APPROVAL", "OPENAI_BILLABLE_SMOKE_APPROVED"
    )
    monkeypatch.setattr(cli_module, "OpenAIResponsesAdapter", lambda **_: object())
    monkeypatch.setattr(cli_module, "ModelGateway", FailingGateway)

    result = main(
        [
            "real-provider-smoke",
            "--budget-usd",
            "0.06",
            "--allow-billable",
        ]
    )
    captured = capsys.readouterr().out
    output = json.loads(captured)
    assert result == 1
    assert output == {
        "actual_cost_usd": 0.0,
        "attempts": 1,
        "code": "MODEL_PROVIDER_ERROR",
        "network_call_attempted": True,
        "status": "FAIL",
    }
    assert "provider detail" not in captured


def test_insufficient_synthetic_case_is_expected_fail_closed(tmp_path) -> None:
    output = tmp_path / "insufficient"

    assert (
        main(
            [
                "run-synthetic",
                "--case",
                "insufficient",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["actual_status"] == (
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES"
    )
    assert manifest["expected_outcome_matched"] is True
    assert manifest["partial_assessment_emitted"] is False
    assert not (output / "assessment.json").exists()


def test_injection_case_stays_data_and_produces_reviewable_views(tmp_path) -> None:
    output = tmp_path / "injection"

    assert (
        main(
            [
                "run-synthetic",
                "--case",
                "injection",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["actual_status"] == "READY"
    assert manifest["assessment_status"] == "NEEDS_REVIEW"
    assert manifest["question_count"] == 3
    assert manifest["security"] == {
        "case": "injection",
        "generated_question_contains_injection": False,
        "model_tools_enabled": False,
        "network_provider_called": False,
        "source_contains_injection": True,
    }
    assert (output / "assessment.pdf").is_file()
    assert (output / "evaluation_guide.pdf").is_file()
    assert (output / "assessment.json").is_file()
    assert (output / "evaluation_guide.json").is_file()
