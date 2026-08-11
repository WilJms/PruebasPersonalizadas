from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import SecretStr, ValidationError
import pytest

from comprehension_verification.contracts import SCHEMA_VERSION, models
from comprehension_verification.model_gateway import (
    CallBudget,
    GatewayBudgetExceeded,
    GatewayConfig,
    GatewayMode,
    GatewayProviderError,
    GatewaySafetyBlock,
    GatewayTimeout,
    GatewayValidationError,
    ModelGateway,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
    build_mock_request,
    build_openai_cost_estimator,
    build_openai_routes,
    build_trusted_context,
    estimate_openai_input_tokens,
)
from comprehension_verification.model_gateway.mock_factory import (
    DeterministicMockFactory,
    MockBehavior,
)
from comprehension_verification.model_gateway.openai_pricing import estimate_cost_usd
from comprehension_verification.model_gateway.openai_adapter import OPENAI_SDK_VERSION
from comprehension_verification.model_gateway.gateway import (
    ModelUnavailableProviderError,
)
from comprehension_verification.model_gateway.openai_routes import (
    LUNA_MODEL_ID,
    OPENAI_MAX_INPUT_TOKENS,
    OPENAI_MODEL_BY_PROMPT,
    OPENAI_P11_MAX_INPUT_TOKENS,
    OPENAI_ROUTE_PROFILE,
    OPENAI_ROUTE_PROFILE_ID,
    SOL_MODEL_ID,
)
from comprehension_verification.model_gateway.openai_schema import (
    provider_schema_validation_issues,
    structured_output_format,
)
from comprehension_verification.model_gateway.registry import PROMPT_SPECS, prompt_spec


@dataclass
class FakeResponses:
    queued: list[Any]

    def __post_init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.queued:
            raise AssertionError("Unexpected fake OpenAI call")
        item = self.queued.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@dataclass
class FakeClient:
    queued: list[Any]

    def __post_init__(self) -> None:
        self.responses = FakeResponses(self.queued)


def _response(
    output: Any,
    *,
    model: str,
    status: str = "completed",
    content_type: str = "output_text",
    input_tokens: int = 1_000,
    cached_tokens: int = 100,
    cache_write_tokens: int = 50,
    output_tokens: int = 200,
    reasoning_tokens: int = 25,
) -> Any:
    text = output if isinstance(output, str) else json.dumps(output, sort_keys=True)
    return SimpleNamespace(
        _request_id="req_synthetic_not_secret",
        error=None,
        status=status,
        model=model,
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type=content_type, text=text)],
            )
        ],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            input_tokens_details=SimpleNamespace(
                cached_tokens=cached_tokens,
                cache_write_tokens=cache_write_tokens,
            ),
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
        ),
    )


def _official_status_error(error_type: type[Exception], status: int, code: str) -> Exception:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        status,
        request=request,
        headers={"x-request-id": "req_error_synthetic"},
    )
    return error_type(  # type: ignore[call-arg]
        "provider detail must not escape",
        response=response,
        body={"code": code, "type": "synthetic"},
    )


def _envelope(prompt_id: str, request: Any) -> models.ModelTaskEnvelope:
    spec = prompt_spec(prompt_id)
    return models.ModelTaskEnvelope(
        schema_version=SCHEMA_VERSION,
        prompt_id=prompt_id,
        prompt_version=spec.prompt_version,
        output_schema_name=spec.output_schema_name,
        output_schema_version=SCHEMA_VERSION,
        trusted_context=build_trusted_context(request),
        payload=request.model_dump(mode="json"),
    )


def _real_gateway(fake: FakeClient, *, timeout: float = 1.0) -> ModelGateway:
    routes = build_openai_routes(max_call_cost_usd=1.0)
    return ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=timeout,
            max_retries=2,
            backoff_base_seconds=0,
            default_budget_usd=1.0,
            job_id="job_openai_synthetic",
        ),
        real_routes=routes,
        adapters={"openai": OpenAIResponsesAdapter(client=fake)},
        cost_estimator=build_openai_cost_estimator(routes),
        input_token_estimator=estimate_openai_input_tokens,
    )


def _canonical_output(prompt_id: str) -> dict[str, Any]:
    request = build_mock_request(prompt_id)
    output = DeterministicMockFactory().output_for(
        prompt_id, request, MockBehavior.HAPPY
    )
    return output.model_dump(mode="json")


def _walk_schema(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schema(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema(child)


def test_route_matrix_is_explicit_and_p10_has_no_route() -> None:
    routes = build_openai_routes(max_call_cost_usd=0.75)
    assert set(routes) == set(PROMPT_SPECS) - {"P10_ENRICHED_CONTEXT_V1"}
    assert OPENAI_ROUTE_PROFILE_ID == "LUNA_BASELINE_V1"
    assert set(OPENAI_MODEL_BY_PROMPT.values()) == {LUNA_MODEL_ID}
    assert SOL_MODEL_ID not in OPENAI_MODEL_BY_PROMPT.values()
    assert all(route.model == LUNA_MODEL_ID for route in routes.values())
    assert all(route.provider == "openai" for route in routes.values())
    assert all(
        route.route_id.startswith("route_openai_luna_baseline_v1_")
        for route in routes.values()
    )
    assert {
        prompt_id: approved.reasoning_effort
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    } == {
        "P01_ACTIVITY_SPEC_V1": models.ReasoningEffort.MEDIUM,
        "P02_RUBRIC_NORMALIZE_V1": models.ReasoningEffort.MEDIUM,
        "P03_AMBIGUITY_TRIAGE_V1": models.ReasoningEffort.HIGH,
        "P04_BLUEPRINT_BUILD_V1": models.ReasoningEffort.HIGH,
        "P05_BLUEPRINT_REVIEW_V1": models.ReasoningEffort.HIGH,
        "P06_EVIDENCE_MAP_V1": models.ReasoningEffort.HIGH,
        "P07_QUESTION_BUILD_V1": models.ReasoningEffort.HIGH,
        "P08_QUESTION_REVIEW_V1": models.ReasoningEffort.HIGH,
        "P09_GUIDE_BUILD_V1": models.ReasoningEffort.HIGH,
        "P11_SCHEMA_REPAIR_V1": models.ReasoningEffort.LOW,
    }
    assert routes["P11_SCHEMA_REPAIR_V1"].reasoning_effort == models.ReasoningEffort.LOW
    assert prompt_spec("P11_SCHEMA_REPAIR_V1").reasoning_effort == models.ReasoningEffort.LOW
    assert all(route.fallback_route_id is None for route in routes.values())
    assert all(route.retention_mode == "DEFAULT" for route in routes.values())
    assert all(not route.capabilities.supports_zero_data_retention for route in routes.values())
    assert (
        routes["P11_SCHEMA_REPAIR_V1"].max_input_tokens
        == OPENAI_P11_MAX_INPUT_TOKENS
        == 80_000
    )
    assert all(
        route.max_input_tokens == OPENAI_MAX_INPUT_TOKENS == 250_000
        for prompt_id, route in routes.items()
        if prompt_id != "P11_SCHEMA_REPAIR_V1"
    )
    assert all(
        "GATEWAY_RETRIES_0_MANUAL_EVAL" in route.reason_codes
        and "FULL_CACHE_WRITE_BUDGET_RESERVATION" in route.reason_codes
        for route in routes.values()
    )
    assert "P11_INPUT_LIMIT_80000" in routes[
        "P11_SCHEMA_REPAIR_V1"
    ].reason_codes


def test_adapter_rejects_historical_sol_route_before_transport() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([])
    route = build_openai_routes(max_call_cost_usd=1.0)[prompt_id].model_copy(
        update={"model": SOL_MODEL_ID}
    )

    with pytest.raises(ModelUnavailableProviderError, match="PROVIDER_ROUTE_NOT_APPROVED"):
        asyncio.run(
            OpenAIResponsesAdapter(client=fake).invoke(
                prompt_id=prompt_id,
                request=request,
                envelope=_envelope(prompt_id, request),
                route=route,
                attempt=1,
                behavior=MockBehavior.HAPPY,
            )
        )

    assert fake.responses.calls == []


@pytest.mark.parametrize(
    "prompt_id", tuple(set(PROMPT_SPECS) - {"P10_ENRICHED_CONTEXT_V1"})
)
def test_canonical_output_schemas_are_strict_provider_payloads(prompt_id: str) -> None:
    request = build_mock_request(prompt_id)
    formatted = structured_output_format(prompt_spec(prompt_id), request)
    assert formatted["type"] == "json_schema"
    assert formatted["strict"] is True
    schema = formatted["schema"]
    assert schema["type"] == "object"
    for item in _walk_schema(schema):
        assert "oneOf" not in item
        assert "discriminator" not in item
        assert "default" not in item
        if item.get("type") == "object":
            assert item.get("additionalProperties") is False
            assert set(item.get("required", [])) == set(item.get("properties", {}))


def test_p07_exact_provider_schema_boundary_excludes_canonical_model_validators() -> None:
    prompt_id = "P07_QUESTION_BUILD_V1"
    request = build_mock_request(prompt_id)
    formatted = structured_output_format(prompt_spec(prompt_id), request)
    schema = formatted["schema"]
    encoded = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert formatted["name"] == "cva_QuestionGenerationResult_1_1_2"
    assert len(encoded) == 13_671
    assert (
        hashlib.sha256(encoded).hexdigest()
        == "80692d48637f0ae2d7a7e6f05ab4e9b0a5e2d8eff6f1b103fbd14f62c482639a"
    )
    assert schema["required"] == [
        "schema_version",
        "submission_id",
        "opportunity_id",
        "context_mode",
        "status",
        "candidate",
        "diagnostics",
    ]

    valid = DeterministicMockFactory().output_for(
        prompt_id, request, MockBehavior.HAPPY
    ).model_dump(mode="json")
    provider_missing = json.loads(json.dumps(valid))
    provider_missing.pop("submission_id")
    assert provider_schema_validation_issues(schema, provider_missing) == (
        ("required", "/"),
    )

    status_candidate_mismatch = json.loads(json.dumps(valid))
    status_candidate_mismatch["candidate"] = None
    assert not provider_schema_validation_issues(schema, status_candidate_mismatch)
    with pytest.raises(ValidationError) as status_error:
        models.QuestionGenerationResult.model_validate(status_candidate_mismatch)
    assert {
        (item["type"], item["loc"])
        for item in status_error.value.errors(include_url=False)
    } == {("value_error", ())}

    anchor_subset_mismatch = json.loads(json.dumps(valid))
    anchor_subset_mismatch["candidate"]["anchor"]["fragments"][0][
        "evidence_id"
    ] = "ev_other"
    assert not provider_schema_validation_issues(schema, anchor_subset_mismatch)
    with pytest.raises(ValidationError) as anchor_error:
        models.QuestionGenerationResult.model_validate(anchor_subset_mismatch)
    assert {
        (item["type"], item["loc"])
        for item in anchor_error.value.errors(include_url=False)
    } == {("value_error", ("candidate",))}

    contextual_only = json.loads(json.dumps(valid))
    contextual_only["submission_id"] = "sub_other"
    contextual_only["candidate"]["submission_id"] = "sub_other"
    assert not provider_schema_validation_issues(schema, contextual_only)
    assert models.QuestionGenerationResult.model_validate(contextual_only)


def test_p11_schema_is_specialized_to_the_named_canonical_target() -> None:
    request = build_mock_request("P11_SCHEMA_REPAIR_V1").model_copy(
        update={"target_schema_name": "QuestionGenerationResult"}
    )
    schema = structured_output_format(
        prompt_spec("P11_SCHEMA_REPAIR_V1"), request
    )["schema"]
    repaired = schema["properties"]["repaired_output"]["anyOf"][0]
    assert repaired["type"] == "object"
    assert "candidate" in repaired["properties"]
    assert all("oneOf" not in item for item in _walk_schema(schema))


def test_p11_rejects_non_output_target_before_transport() -> None:
    request = build_mock_request("P11_SCHEMA_REPAIR_V1").model_copy(
        update={"target_schema_name": "ActivitySpecRequest"}
    )
    fake = FakeClient([])

    with pytest.raises(GatewayValidationError):
        asyncio.run(
            _real_gateway(fake).invoke(
                "P11_SCHEMA_REPAIR_V1",
                request,
                build_trusted_context(request),
            )
        )

    assert fake.responses.calls == []


def test_responses_payload_has_governed_state_tools_and_reasoning_controls() -> None:
    prompt_id = "P11_SCHEMA_REPAIR_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)])
    adapter = OpenAIResponsesAdapter(client=fake)
    route = build_openai_routes(max_call_cost_usd=1.0)[prompt_id]

    result = asyncio.run(
        adapter.invoke(
            prompt_id=prompt_id,
            request=request,
            envelope=_envelope(prompt_id, request),
            route=route,
            attempt=1,
            behavior=MockBehavior.HAPPY,
        )
    )

    assert result.effective_model == LUNA_MODEL_ID
    assert result.provider_schema_valid is True
    assert result.provider_schema_issues == ()
    assert result.reasoning_tokens == 25
    call = fake.responses.calls[0]
    assert call["model"] == LUNA_MODEL_ID
    assert call["reasoning"] == {"effort": "low"}
    assert call["store"] is False
    assert call["background"] is False
    assert call["tools"] == []
    assert call["parallel_tool_calls"] is False
    assert call["truncation"] == "disabled"
    assert call["service_tier"] == "default"
    assert "temperature" not in call
    assert "previous_response_id" not in call
    assert "conversation" not in call
    assert "prompt_cache_retention" not in call
    assert call["text"]["format"]["strict"] is True
    assert [item["role"] for item in call["input"]] == ["developer", "user"]
    assert "transformador JSON" in call["instructions"]
    developer_text = call["input"][0]["content"][0]["text"]
    assert "CALL_CONTROLS_JSON" in developer_text
    assert '"output_language":"es-CL"' in developer_text
    assert '"prompt_id":"P11_SCHEMA_REPAIR_V1"' in developer_text
    envelope_json = json.loads(call["input"][1]["content"][0]["text"])
    assert envelope_json["prompt_id"] == prompt_id
    assert envelope_json["trusted_context"]["tenant_id"] == "tnt_demo"


def test_untrusted_evidence_is_serialized_only_in_the_user_envelope() -> None:
    prompt_id = "P07_QUESTION_BUILD_V1"
    request = build_mock_request(prompt_id)
    untrusted_text = request.evidence_bundle.evidence_units[0].content_text
    fake = FakeClient([_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)])
    adapter = OpenAIResponsesAdapter(client=fake)

    asyncio.run(
        adapter.invoke(
            prompt_id=prompt_id,
            request=request,
            envelope=_envelope(prompt_id, request),
            route=build_openai_routes(max_call_cost_usd=1.0)[prompt_id],
            attempt=1,
            behavior=MockBehavior.HAPPY,
        )
    )

    call = fake.responses.calls[0]
    developer_text = call["input"][0]["content"][0]["text"]
    user_text = call["input"][1]["content"][0]["text"]
    assert untrusted_text not in call["instructions"]
    assert untrusted_text not in developer_text
    assert untrusted_text in user_text


def test_successful_gateway_call_records_effective_usage_hashes_and_cost() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    fake = FakeClient([_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)])
    request = build_mock_request(prompt_id)
    result = asyncio.run(
        _real_gateway(fake).invoke(prompt_id, request, build_trusted_context(request))
    )
    ledger = result.ledgers[0]
    assert ledger.result == "SCHEMA_VALID"
    assert ledger.input_tokens == 1_000
    assert ledger.cached_input_tokens == 100
    assert ledger.output_tokens == 200
    assert ledger.actual_cost_usd == estimate_cost_usd(
        model=LUNA_MODEL_ID,
        input_tokens=1_000,
        cached_input_tokens=100,
        cache_write_tokens=50,
        output_tokens=200,
    )
    codes = ledger.route.reason_codes
    assert "CACHE_WRITE_INPUT_TOKENS_50" in codes
    assert "REASONING_TOKENS_25" in codes
    assert "EFFECTIVE_MODEL_gpt-5.6-luna" in codes
    assert "ROUTE_PROFILE_LUNA_BASELINE_V1" in codes
    assert any(code.startswith("OUTPUT_HASH_") for code in codes)
    assert any(code.startswith("PROVIDER_REQUEST_ID_HASH_") for code in codes)
    assert all("req_synthetic" not in code for code in codes)


def test_refusal_is_safety_block_without_retry_or_p11() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    fake = FakeClient(
        [_response("refused", model=LUNA_MODEL_ID, content_type="refusal")]
    )
    request = build_mock_request(prompt_id)
    with pytest.raises(GatewaySafetyBlock) as caught:
        asyncio.run(
            _real_gateway(fake).invoke(
                prompt_id, request, build_trusted_context(request)
            )
        )
    assert len(fake.responses.calls) == 1
    assert len(caught.value.ledgers) == 1
    assert caught.value.ledgers[0].result == "SAFETY_BLOCK"


def test_sdk_timeout_is_retried_only_by_gateway_and_stops_after_three_attempts() -> None:
    request_object = httpx.Request("POST", "https://api.openai.com/v1/responses")
    fake = FakeClient([APITimeoutError(request_object) for _ in range(3)])
    request = build_mock_request("P01_ACTIVITY_SPEC_V1")
    with pytest.raises(GatewayTimeout) as caught:
        asyncio.run(
            _real_gateway(fake).invoke(
                "P01_ACTIVITY_SPEC_V1", request, build_trusted_context(request)
            )
        )
    assert len(fake.responses.calls) == 3
    assert [ledger.attempt for ledger in caught.value.ledgers] == [1, 2, 3]
    assert all(ledger.result == "TIMEOUT" for ledger in caught.value.ledgers)


def test_transient_429_and_5xx_are_bounded_but_quota_and_auth_are_not_retried() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    context = build_trusted_context(request)

    rate = _official_status_error(RateLimitError, 429, "rate_limit_exceeded")
    fake_rate = FakeClient([rate, rate, rate])
    with pytest.raises(GatewayProviderError):
        asyncio.run(_real_gateway(fake_rate).invoke(prompt_id, request, context))
    assert len(fake_rate.responses.calls) == 3

    server = _official_status_error(InternalServerError, 500, "server_error")
    fake_server = FakeClient([server, server, server])
    with pytest.raises(GatewayProviderError):
        asyncio.run(_real_gateway(fake_server).invoke(prompt_id, request, context))
    assert len(fake_server.responses.calls) == 3

    quota = _official_status_error(RateLimitError, 429, "insufficient_quota")
    fake_quota = FakeClient([quota])
    with pytest.raises(GatewayBudgetExceeded):
        asyncio.run(_real_gateway(fake_quota).invoke(prompt_id, request, context))
    assert len(fake_quota.responses.calls) == 1

    auth = _official_status_error(AuthenticationError, 401, "invalid_api_key")
    fake_auth = FakeClient([auth])
    with pytest.raises(GatewayProviderError) as caught:
        asyncio.run(_real_gateway(fake_auth).invoke(prompt_id, request, context))
    assert len(fake_auth.responses.calls) == 1
    assert "provider detail" not in str(caught.value)
    assert "invalid_api_key" not in str(caught.value)


def test_connection_errors_are_bounded_by_the_gateway() -> None:
    request_object = httpx.Request("POST", "https://api.openai.com/v1/responses")
    failures = [APIConnectionError(request=request_object) for _ in range(3)]
    fake = FakeClient(failures)
    request = build_mock_request("P01_ACTIVITY_SPEC_V1")

    with pytest.raises(GatewayProviderError) as caught:
        asyncio.run(
            _real_gateway(fake).invoke(
                "P01_ACTIVITY_SPEC_V1",
                request,
                build_trusted_context(request),
            )
        )

    assert len(fake.responses.calls) == 3
    assert all(
        "PROVIDER_CONNECTION" in ledger.route.reason_codes
        for ledger in caught.value.ledgers
    )


@pytest.mark.parametrize(
    ("error_type", "status", "code", "gateway_error"),
    [
        (PermissionDeniedError, 403, "permission_denied", GatewayProviderError),
        (NotFoundError, 404, "model_not_found", GatewayProviderError),
        (BadRequestError, 400, "invalid_request_error", GatewayProviderError),
        (BadRequestError, 400, "content_filter", GatewaySafetyBlock),
    ],
)
def test_permanent_provider_failures_never_retry(
    error_type: type[Exception],
    status: int,
    code: str,
    gateway_error: type[Exception],
) -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([_official_status_error(error_type, status, code)])

    with pytest.raises(gateway_error):
        asyncio.run(
            _real_gateway(fake).invoke(
                prompt_id, request, build_trusted_context(request)
            )
        )

    assert len(fake.responses.calls) == 1


def test_effective_model_mismatch_fails_closed_without_retry() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient(
        [_response(_canonical_output(prompt_id), model="gpt-5.6-unapproved")]
    )

    with pytest.raises(GatewayProviderError):
        asyncio.run(
            _real_gateway(fake).invoke(
                prompt_id, request, build_trusted_context(request)
            )
        )

    assert len(fake.responses.calls) == 1


def test_structurally_invalid_output_gets_exactly_one_p11_luna_low_attempt() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    invalid = _canonical_output(prompt_id)
    invalid["unexpected_field"] = "untrusted data"
    repair = _canonical_output("P11_SCHEMA_REPAIR_V1")
    fake = FakeClient(
        [
            _response(invalid, model=LUNA_MODEL_ID),
            _response(repair, model=LUNA_MODEL_ID),
        ]
    )
    request = build_mock_request(prompt_id)
    result = asyncio.run(
        _real_gateway(fake).invoke(prompt_id, request, build_trusted_context(request))
    )
    assert result.repaired is True
    assert [call["model"] for call in fake.responses.calls] == [
        LUNA_MODEL_ID,
        LUNA_MODEL_ID,
    ]
    assert fake.responses.calls[1]["reasoning"] == {"effort": "low"}
    assert len(fake.responses.calls) == 2
    assert "PROVIDER_SCHEMA_INVALID" in result.ledgers[0].route.reason_codes
    assert (
        "OUTPUT_PYDANTIC_VALIDATION_FAILED"
        in result.ledgers[0].route.reason_codes
    )
    assert "PROVIDER_SCHEMA_VALID" in result.ledgers[1].route.reason_codes


def test_malformed_json_is_data_for_exactly_one_p11_attempt() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    fake = FakeClient(
        [
            _response("{not-json", model=LUNA_MODEL_ID),
            _response(_canonical_output("P11_SCHEMA_REPAIR_V1"), model=LUNA_MODEL_ID),
        ]
    )
    request = build_mock_request(prompt_id)

    result = asyncio.run(
        _real_gateway(fake).invoke(
            prompt_id, request, build_trusted_context(request)
        )
    )

    assert result.repaired is True
    assert len(fake.responses.calls) == 2
    repair_envelope = json.loads(
        fake.responses.calls[1]["input"][1]["content"][0]["text"]
    )
    assert repair_envelope["payload"]["invalid_output"] == "{not-json"


def test_incomplete_response_fails_closed_without_p11() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID, status="incomplete")]
    )
    request = build_mock_request(prompt_id)
    with pytest.raises(GatewayProviderError):
        asyncio.run(
            _real_gateway(fake).invoke(
                prompt_id, request, build_trusted_context(request)
            )
        )
    assert len(fake.responses.calls) == 1


def test_preflight_budget_blocks_before_transport_and_no_fallback_exists() -> None:
    fake = FakeClient([])
    request = build_mock_request("P04_BLUEPRINT_BUILD_V1")
    with pytest.raises(GatewayBudgetExceeded):
        asyncio.run(
            _real_gateway(fake).invoke(
                "P04_BLUEPRINT_BUILD_V1",
                request,
                build_trusted_context(request),
                budget=CallBudget(max_cost_usd=0.01),
            )
        )
    assert fake.responses.calls == []


def test_preflight_counts_full_schema_prompt_and_retry_ceiling() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    spec = prompt_spec(prompt_id)
    envelope = _envelope(prompt_id, request)
    token_ceiling = estimate_openai_input_tokens(spec, request, envelope)
    request_only_estimate = len(
        json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
    ) // 4
    assert token_ceiling > request_only_estimate

    routes = build_openai_routes(max_call_cost_usd=1.0)
    one_attempt = build_openai_cost_estimator(routes)(spec, token_ceiling)
    fake = FakeClient([])
    gateway = _real_gateway(fake)
    with pytest.raises(GatewayBudgetExceeded):
        asyncio.run(
            gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
                budget=CallBudget(max_cost_usd=one_attempt * 3 - 0.000001),
            )
        )
    assert fake.responses.calls == []


def test_preflight_reserves_full_cache_write_before_transport() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    spec = prompt_spec(prompt_id)
    envelope = _envelope(prompt_id, request)
    token_ceiling = estimate_openai_input_tokens(spec, request, envelope)
    routes = build_openai_routes(max_call_cost_usd=1.0)
    ordinary_input_ceiling = estimate_cost_usd(
        model=LUNA_MODEL_ID,
        input_tokens=token_ceiling,
        output_tokens=spec.max_output_tokens,
    )
    full_cache_write_ceiling = build_openai_cost_estimator(routes)(
        spec, token_ceiling
    )

    assert full_cache_write_ceiling == estimate_cost_usd(
        model=LUNA_MODEL_ID,
        input_tokens=token_ceiling,
        output_tokens=spec.max_output_tokens,
        cache_write_tokens=token_ceiling,
    )
    assert full_cache_write_ceiling > ordinary_input_ceiling

    fake = FakeClient([])
    gateway = _real_gateway(fake)
    with pytest.raises(GatewayBudgetExceeded):
        asyncio.run(
            gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
                budget=CallBudget(max_cost_usd=ordinary_input_ceiling * 3),
            )
        )
    assert fake.responses.calls == []


def test_p11_preflight_has_one_attempt_and_luna_low_smoke_ceiling() -> None:
    prompt_id = "P11_SCHEMA_REPAIR_V1"
    request = build_mock_request(prompt_id)
    spec = prompt_spec(prompt_id)
    token_ceiling = estimate_openai_input_tokens(
        spec, request, _envelope(prompt_id, request)
    )
    routes = build_openai_routes(max_call_cost_usd=0.06)
    cost = build_openai_cost_estimator(routes)(spec, token_ceiling)
    assert token_ceiling == 8_502
    assert cost == 0.0117255
    assert spec.max_transient_retries == 0


def test_official_sdk_client_is_pinned_with_automatic_retries_disabled() -> None:
    adapter = OpenAIResponsesAdapter(
        api_key=SecretStr("sk-project-synthetic-placeholder-not-a-real-key"),
        config=OpenAIAdapterConfig(request_timeout_seconds=30),
    )
    assert adapter.client.max_retries == 0
    assert adapter.client.timeout == 30
    assert "synthetic-placeholder" not in repr(adapter.client)
    assert openai.__version__ == OPENAI_SDK_VERSION == "2.53.0"

    root = Path(__file__).resolve().parents[1]
    assert '"openai==2.53.0"' in (root / "pyproject.toml").read_text()
    for lock_name in ("requirements.lock", "requirements-dev.lock"):
        lock = (root / lock_name).read_text()
        assert "openai==2.53.0 \\" in lock
        openai_block = lock.split("openai==2.53.0 \\", 1)[1].split("\n\n", 1)[0]
        assert "--hash=sha256:" in openai_block
