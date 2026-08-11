from __future__ import annotations

import json
from types import SimpleNamespace

import comprehension_verification.cli as cli_module
from comprehension_verification.cli import main
from comprehension_verification.model_gateway import (
    DeterministicMockFactory,
    GatewayProviderError,
    MockBehavior,
    OpenAIResponsesAdapter,
    build_mock_request,
)
from comprehension_verification.model_gateway.openai_pricing import estimate_cost_usd
from comprehension_verification.model_gateway.openai_routes import LUNA_MODEL_ID


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


def test_real_smoke_versioned_entrypoint_reaches_fake_transport_once(
    capsys, monkeypatch
) -> None:
    calls: list[dict] = []

    class FakeResponses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            prompt_id = "P11_SCHEMA_REPAIR_V1"
            request = build_mock_request(prompt_id)
            output = DeterministicMockFactory().output_for(
                prompt_id, request, MockBehavior.HAPPY
            )
            return SimpleNamespace(
                _request_id="req_synthetic_cli_smoke",
                error=None,
                status="completed",
                model=LUNA_MODEL_ID,
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[
                            SimpleNamespace(
                                type="output_text",
                                text=json.dumps(output.model_dump(mode="json")),
                            )
                        ],
                    )
                ],
                usage=SimpleNamespace(
                    input_tokens=1_000,
                    input_tokens_details=SimpleNamespace(
                        cached_tokens=100,
                        cache_write_tokens=0,
                    ),
                    output_tokens=200,
                    output_tokens_details=SimpleNamespace(reasoning_tokens=25),
                ),
            )

    fake_client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setenv(
        "CVA_OPENAI_API_KEY", "sk-project-synthetic-placeholder-not-a-real-key"
    )
    monkeypatch.setenv(
        "CVA_OPENAI_BILLABLE_SMOKE_APPROVAL", "OPENAI_BILLABLE_SMOKE_APPROVED"
    )
    monkeypatch.setattr(
        cli_module,
        "OpenAIResponsesAdapter",
        lambda **_: OpenAIResponsesAdapter(client=fake_client),
    )

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

    assert result == 0
    assert len(calls) == 1
    payload = calls[0]
    assert payload["model"] == LUNA_MODEL_ID
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["tools"] == []
    assert payload["store"] is False
    assert payload["background"] is False
    assert output == {
        "status": "PASS",
        "code": "OPENAI_REAL_SMOKE_PASS",
        "network_call_attempted": True,
        "prompt_id": "P11_SCHEMA_REPAIR_V1",
        "prompt_version": "1.1.4",
        "schema_version": "1.1.0",
        "route_profile": "LUNA_BASELINE_V1",
        "requested_model": LUNA_MODEL_ID,
        "effective_model": LUNA_MODEL_ID,
        "reasoning_effort": "LOW",
        "responses_requests": 1,
        "attempts": 1,
        "input_tokens": 1_000,
        "cached_input_tokens": 100,
        "output_tokens": 200,
        "reasoning_tokens": 25,
        "latency_ms": output["latency_ms"],
        "estimated_cost_usd": estimate_cost_usd(
            model=LUNA_MODEL_ID,
            input_tokens=1_000,
            cached_input_tokens=100,
            output_tokens=8_000,
        ),
        "calculated_actual_cost_usd": estimate_cost_usd(
            model=LUNA_MODEL_ID,
            input_tokens=1_000,
            cached_input_tokens=100,
            output_tokens=200,
        ),
        "schema_validation": True,
        "pydantic_validation": True,
        "contextual_validation": True,
        "request_id_hash": output["request_id_hash"],
        "output_hash": output["output_hash"],
    }
    assert output["latency_ms"] >= 0
    assert output["request_id_hash"].startswith("sha256:")
    assert output["output_hash"].startswith("sha256:")
    assert "synthetic-placeholder" not in captured
    assert "req_synthetic_cli_smoke" not in captured


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
