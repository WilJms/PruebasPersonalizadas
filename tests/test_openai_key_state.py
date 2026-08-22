from __future__ import annotations

from io import StringIO
import json
from types import SimpleNamespace
from typing import Any

import httpx
from openai import APIConnectionError, AuthenticationError

from scripts import check_openai_key_state as key_state


class _FakeModels:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls = 0

    def list(self) -> object:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _FakeClient:
    def __init__(self, outcome: object) -> None:
        self.models = _FakeModels(outcome)


def _factory(outcome: object) -> tuple[Any, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def build(**kwargs: object) -> _FakeClient:
        calls.append(kwargs)
        return _FakeClient(outcome)

    return build, calls


def _model_list(*ids: str) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in ids])


def _authentication_error() -> AuthenticationError:
    request = httpx.Request("GET", "https://api.openai.com/v1/models")
    response = httpx.Response(401, request=request)
    return AuthenticationError(
        "sensitive provider detail",
        response=response,
        body={"error": {"code": "invalid_api_key", "message": "sensitive"}},
    )


def test_active_key_requires_the_exact_model_and_disables_sdk_retries() -> None:
    factory, calls = _factory(_model_list("gpt-5.6-luna"))

    decision = key_state.probe_key_state(
        "synthetic-key",
        expected_state="active",
        required_model="gpt-5.6-luna",
        client_factory=factory,
    )

    assert decision.exit_code == 0
    assert decision.report == {
        "billable_calls": 0,
        "code": "OPENAI_KEY_ACTIVE_REQUIRED_MODEL_VISIBLE",
        "expected_state": "ACTIVE",
        "model_count": 1,
        "network_calls": 1,
        "observed_state": "ACTIVE",
        "required_model": "gpt-5.6-luna",
        "required_model_visible": True,
        "status": "PASS",
    }
    assert calls == [{"api_key": "synthetic-key", "max_retries": 0}]


def test_active_key_without_required_model_fails_closed() -> None:
    factory, _ = _factory(_model_list("gpt-5.6-terra"))

    decision = key_state.probe_key_state(
        "synthetic-key",
        expected_state="active",
        required_model="gpt-5.6-luna",
        client_factory=factory,
    )

    assert decision.exit_code == 1
    assert decision.report["code"] == "OPENAI_REQUIRED_MODEL_NOT_VISIBLE"
    assert decision.report["required_model_visible"] is False
    assert decision.report["billable_calls"] == 0


def test_rejected_key_confirms_revocation_expectation_without_leaking_detail() -> None:
    factory, _ = _factory(_authentication_error())

    decision = key_state.probe_key_state(
        "synthetic-key",
        expected_state="revoked",
        client_factory=factory,
    )

    assert decision.exit_code == 0
    assert decision.report == {
        "billable_calls": 0,
        "code": "OPENAI_KEY_REJECTION_CONFIRMED",
        "expected_state": "REVOKED",
        "network_calls": 1,
        "observed_state": "REJECTED",
        "provider_status_code": 401,
        "status": "PASS",
    }
    serialized = json.dumps(decision.report)
    assert "sensitive" not in serialized
    assert "invalid_api_key" not in serialized


def test_active_key_fails_a_revocation_expectation() -> None:
    factory, _ = _factory(_model_list("gpt-5.6-luna"))

    decision = key_state.probe_key_state(
        "synthetic-key",
        expected_state="revoked",
        client_factory=factory,
    )

    assert decision.exit_code == 1
    assert decision.report["code"] == "OPENAI_KEY_STILL_ACTIVE"
    assert decision.report["observed_state"] == "ACTIVE"


def test_connection_uncertainty_is_not_misclassified_as_revocation() -> None:
    error = APIConnectionError(
        request=httpx.Request("GET", "https://api.openai.com/v1/models")
    )
    factory, _ = _factory(error)

    decision = key_state.probe_key_state(
        "synthetic-key",
        expected_state="revoked",
        client_factory=factory,
    )

    assert decision.exit_code == 2
    assert decision.report["code"] == "OPENAI_KEY_STATE_UNKNOWN"
    assert decision.report["error_type"] == "APIConnectionError"
    assert decision.report["observed_state"] == "UNKNOWN"


def test_cli_reads_only_stdin_and_never_emits_the_key() -> None:
    secret = "synthetic-key-that-must-not-appear"
    output = StringIO()
    factory, _ = _factory(_model_list("gpt-5.6-luna"))

    exit_code = key_state.main(
        ["--expect", "active", "--required-model", "gpt-5.6-luna"],
        stdin=StringIO(secret),
        stdout=output,
        client_factory=factory,
    )

    assert exit_code == 0
    assert secret not in output.getvalue()
    assert json.loads(output.getvalue())["status"] == "PASS"


def test_cli_blocks_before_transport_when_stdin_is_empty() -> None:
    output = StringIO()
    factory, calls = _factory(_model_list("gpt-5.6-luna"))

    exit_code = key_state.main(
        ["--expect", "revoked"],
        stdin=StringIO(""),
        stdout=output,
        client_factory=factory,
    )

    assert exit_code == 2
    assert calls == []
    assert json.loads(output.getvalue()) == {
        "billable_calls": 0,
        "code": "OPENAI_KEY_STDIN_REQUIRED",
        "expected_state": "REVOKED",
        "network_calls": 0,
        "observed_state": "UNKNOWN",
        "status": "BLOCKED",
    }
