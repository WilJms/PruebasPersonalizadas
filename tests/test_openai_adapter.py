from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

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
from openai.types.shared_params.reasoning_effort import (
    ReasoningEffort as OpenAIReasoningEffort,
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
    GatewaySchemaViolation,
    GatewayTimeout,
    GatewayValidationError,
    ModelGateway,
    OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
    PermanentProviderError,
    ProviderBudgetError,
    RequestCappedAdapter,
    build_mock_request,
    build_openai_cost_estimator,
    build_openai_input_token_estimator,
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
    OPENAI_MAX_PROMPT_IDS,
    OPENAI_MAX_ROUTE_PROFILE,
    OPENAI_MAX_ROUTE_PROFILE_ID,
    OPENAI_MODEL_BY_PROMPT,
    OPENAI_P11_MAX_INPUT_TOKENS,
    OPENAI_ROUTE_PROFILE,
    OPENAI_ROUTE_PROFILE_ID,
    OPENAI_SOL_HIGH_PROMPT_IDS,
    OPENAI_SOL_HIGH_ROUTE_PROFILE,
    OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
    OPENAI_SOL_MEDIUM_PROMPT_IDS,
    OPENAI_SOL_MEDIUM_ROUTE_PROFILE,
    OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
    OPENAI_SOL_XHIGH_PROMPT_IDS,
    OPENAI_SOL_XHIGH_ROUTE_PROFILE,
    OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_MEDIUM_PROMPT_IDS,
    OPENAI_TERRA_MEDIUM_ROUTE_PROFILE,
    OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
    OPENAI_TERRA_HIGH_PROMPT_IDS,
    OPENAI_TERRA_HIGH_ROUTE_PROFILE,
    OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_XHIGH_PROMPT_IDS,
    OPENAI_TERRA_XHIGH_ROUTE_PROFILE,
    OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
    OPENAI_XHIGH_PROMPT_IDS,
    OPENAI_XHIGH_ROUTE_PROFILE,
    OPENAI_XHIGH_ROUTE_PROFILE_ID,
    SOL_MODEL_ID,
    TERRA_MODEL_ID,
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


def test_xhigh_contract_and_route_profile_have_one_material_delta() -> None:
    assert [effort.value for effort in models.ReasoningEffort] == [
        "MINIMAL",
        "LOW",
        "MEDIUM",
        "HIGH",
        "XHIGH",
        "MAX",
    ]
    assert OPENAI_XHIGH_ROUTE_PROFILE_ID == "LUNA_XHIGH_V1"
    assert {
        prompt_id
        for prompt_id, approved in OPENAI_XHIGH_ROUTE_PROFILE.items()
        if approved.reasoning_effort == models.ReasoningEffort.XHIGH
    } == set(OPENAI_XHIGH_PROMPT_IDS)

    baseline = build_openai_routes(max_call_cost_usd=0.10)
    xhigh = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
    )
    assert set(baseline) == set(xhigh)
    assert set(xhigh) == set(PROMPT_SPECS) - {"P10_ENRICHED_CONTEXT_V1"}
    assert all(route.model == LUNA_MODEL_ID for route in xhigh.values())
    assert all(route.fallback_route_id is None for route in xhigh.values())
    assert all(
        models.ReasoningEffort.XHIGH
        in route.capabilities.supported_reasoning_efforts
        for route in xhigh.values()
    )

    reasoning_changes: set[str] = set()
    for prompt_id in baseline:
        baseline_material = baseline[prompt_id].model_dump(mode="json")
        xhigh_material = xhigh[prompt_id].model_dump(mode="json")
        if (
            baseline[prompt_id].reasoning_effort
            != xhigh[prompt_id].reasoning_effort
        ):
            reasoning_changes.add(prompt_id)
        for material in (baseline_material, xhigh_material):
            material.pop("route_id")
            material.pop("reasoning_effort")
            material.pop("reason_codes")
        assert baseline_material == xhigh_material
        assert xhigh[prompt_id].route_id.startswith(
            "route_openai_luna_xhigh_v1_"
        )
    assert reasoning_changes == set(OPENAI_XHIGH_PROMPT_IDS)
    assert all(
        PROMPT_SPECS[prompt_id].reasoning_effort
        == models.ReasoningEffort.HIGH
        for prompt_id in OPENAI_XHIGH_PROMPT_IDS
    )
    assert xhigh["P03_AMBIGUITY_TRIAGE_V1"].reasoning_effort == (
        models.ReasoningEffort.HIGH
    )
    assert xhigh["P11_SCHEMA_REPAIR_V1"].reasoning_effort == (
        models.ReasoningEffort.LOW
    )


def test_max_route_profile_changes_only_xhigh_effort_and_identity() -> None:
    assert OPENAI_MAX_ROUTE_PROFILE_ID == "LUNA_MAX_V1"
    assert OPENAI_MAX_PROMPT_IDS == OPENAI_XHIGH_PROMPT_IDS
    assert {
        prompt_id
        for prompt_id, approved in OPENAI_MAX_ROUTE_PROFILE.items()
        if approved.reasoning_effort == models.ReasoningEffort.MAX
    } == set(OPENAI_MAX_PROMPT_IDS)

    xhigh = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
    )
    maximum = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
    )
    assert set(xhigh) == set(maximum)
    assert all(route.model == LUNA_MODEL_ID for route in maximum.values())
    assert all(route.fallback_route_id is None for route in maximum.values())
    assert all(
        models.ReasoningEffort.MAX
        in route.capabilities.supported_reasoning_efforts
        for route in maximum.values()
    )

    reasoning_changes: set[str] = set()
    for prompt_id in xhigh:
        xhigh_material = xhigh[prompt_id].model_dump(mode="json")
        max_material = maximum[prompt_id].model_dump(mode="json")
        if (
            xhigh[prompt_id].reasoning_effort
            != maximum[prompt_id].reasoning_effort
        ):
            reasoning_changes.add(prompt_id)
        for material in (xhigh_material, max_material):
            material.pop("route_id")
            material.pop("reasoning_effort")
            material.pop("reason_codes")
        assert xhigh_material == max_material
        assert maximum[prompt_id].route_id.startswith(
            "route_openai_luna_max_v1_"
        )
    assert reasoning_changes == set(OPENAI_MAX_PROMPT_IDS)
    assert all(
        maximum[prompt_id].reasoning_effort == models.ReasoningEffort.MAX
        for prompt_id in OPENAI_MAX_PROMPT_IDS
    )
    assert maximum["P03_AMBIGUITY_TRIAGE_V1"].reasoning_effort == (
        models.ReasoningEffort.HIGH
    )
    assert maximum["P11_SCHEMA_REPAIR_V1"].reasoning_effort == (
        models.ReasoningEffort.LOW
    )


def test_terra_medium_profile_changes_model_and_qualified_effort_only() -> None:
    assert OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID == "TERRA_MEDIUM_V1"
    assert OPENAI_TERRA_MEDIUM_PROMPT_IDS == OPENAI_MAX_PROMPT_IDS
    assert {
        prompt_id
        for prompt_id, approved in OPENAI_TERRA_MEDIUM_ROUTE_PROFILE.items()
        if (
            prompt_id in OPENAI_TERRA_MEDIUM_PROMPT_IDS
            and approved.reasoning_effort == models.ReasoningEffort.MEDIUM
        )
    } == set(OPENAI_TERRA_MEDIUM_PROMPT_IDS)

    maximum = build_openai_routes(
        max_call_cost_usd=0.27,
        route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
    )
    terra = build_openai_routes(
        max_call_cost_usd=0.27,
        route_profile_id=OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
    )
    assert set(maximum) == set(terra)
    assert all(route.model == TERRA_MODEL_ID for route in terra.values())
    assert all(route.fallback_route_id is None for route in terra.values())

    reasoning_changes: set[str] = set()
    for prompt_id in maximum:
        if (
            maximum[prompt_id].reasoning_effort
            != terra[prompt_id].reasoning_effort
        ):
            reasoning_changes.add(prompt_id)
        max_material = maximum[prompt_id].model_dump(mode="json")
        terra_material = terra[prompt_id].model_dump(mode="json")
        for material in (max_material, terra_material):
            material.pop("route_id")
            material.pop("model")
            material.pop("model_snapshot")
            material.pop("reasoning_effort")
            material.pop("reason_codes")
        assert max_material == terra_material
        assert terra[prompt_id].route_id.startswith(
            "route_openai_terra_medium_v1_"
        )
    assert reasoning_changes == set(OPENAI_TERRA_MEDIUM_PROMPT_IDS)
    assert all(
        terra[prompt_id].reasoning_effort == models.ReasoningEffort.MEDIUM
        for prompt_id in OPENAI_TERRA_MEDIUM_PROMPT_IDS
    )
    assert terra["P01_ACTIVITY_SPEC_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert terra["P02_RUBRIC_NORMALIZE_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert terra["P03_AMBIGUITY_TRIAGE_V1"].reasoning_effort == (
        models.ReasoningEffort.HIGH
    )
    assert terra["P11_SCHEMA_REPAIR_V1"].reasoning_effort == (
        models.ReasoningEffort.LOW
    )


def test_terra_high_profile_changes_only_model_from_luna_baseline() -> None:
    assert OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID == "TERRA_HIGH_V1"
    assert OPENAI_TERRA_HIGH_PROMPT_IDS == OPENAI_MAX_PROMPT_IDS
    assert {
        prompt_id
        for prompt_id, approved in OPENAI_TERRA_HIGH_ROUTE_PROFILE.items()
        if (
            prompt_id in OPENAI_TERRA_HIGH_PROMPT_IDS
            and approved.reasoning_effort == models.ReasoningEffort.HIGH
        )
    } == set(OPENAI_TERRA_HIGH_PROMPT_IDS)

    luna = build_openai_routes(max_call_cost_usd=0.82)
    terra = build_openai_routes(
        max_call_cost_usd=0.82,
        route_profile_id=OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
    )
    assert set(luna) == set(terra)
    assert all(route.model == TERRA_MODEL_ID for route in terra.values())
    assert all(route.fallback_route_id is None for route in terra.values())
    for prompt_id in luna:
        assert terra[prompt_id].reasoning_effort == (
            luna[prompt_id].reasoning_effort
        )
        luna_material = luna[prompt_id].model_dump(mode="json")
        terra_material = terra[prompt_id].model_dump(mode="json")
        for material in (luna_material, terra_material):
            material.pop("route_id")
            material.pop("model")
            material.pop("model_snapshot")
            material.pop("reason_codes")
        assert luna_material == terra_material
        assert terra[prompt_id].route_id.startswith(
            "route_openai_terra_high_v1_"
        )
    assert terra["P01_ACTIVITY_SPEC_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert terra["P02_RUBRIC_NORMALIZE_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert terra["P03_AMBIGUITY_TRIAGE_V1"].reasoning_effort == (
        models.ReasoningEffort.HIGH
    )
    assert all(
        terra[prompt_id].reasoning_effort == models.ReasoningEffort.HIGH
        for prompt_id in OPENAI_TERRA_HIGH_PROMPT_IDS
    )
    assert terra["P11_SCHEMA_REPAIR_V1"].reasoning_effort == (
        models.ReasoningEffort.LOW
    )


def test_terra_xhigh_profile_changes_only_p04_p09_effort_from_terra_high() -> None:
    assert OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID == "TERRA_XHIGH_V1"
    assert OPENAI_TERRA_XHIGH_PROMPT_IDS == OPENAI_TERRA_HIGH_PROMPT_IDS
    assert {
        prompt_id
        for prompt_id, approved in OPENAI_TERRA_XHIGH_ROUTE_PROFILE.items()
        if approved.reasoning_effort == models.ReasoningEffort.XHIGH
    } == set(OPENAI_TERRA_XHIGH_PROMPT_IDS)

    high = build_openai_routes(
        max_call_cost_usd=0.82,
        route_profile_id=OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
    )
    xhigh = build_openai_routes(
        max_call_cost_usd=0.82,
        route_profile_id=OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
    )
    assert set(high) == set(xhigh)
    assert all(route.model == TERRA_MODEL_ID for route in xhigh.values())
    assert all(route.fallback_route_id is None for route in xhigh.values())
    for prompt_id in high:
        expected_effort = (
            models.ReasoningEffort.XHIGH
            if prompt_id in OPENAI_TERRA_XHIGH_PROMPT_IDS
            else high[prompt_id].reasoning_effort
        )
        assert xhigh[prompt_id].reasoning_effort == expected_effort
        high_material = high[prompt_id].model_dump(mode="json")
        xhigh_material = xhigh[prompt_id].model_dump(mode="json")
        for material in (high_material, xhigh_material):
            material.pop("route_id")
            material.pop("reasoning_effort")
            material.pop("reason_codes")
        assert high_material == xhigh_material
        assert xhigh[prompt_id].route_id.startswith(
            "route_openai_terra_xhigh_v1_"
        )
    assert xhigh["P01_ACTIVITY_SPEC_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert xhigh["P02_RUBRIC_NORMALIZE_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert xhigh["P03_AMBIGUITY_TRIAGE_V1"].reasoning_effort == (
        models.ReasoningEffort.HIGH
    )
    assert xhigh["P11_SCHEMA_REPAIR_V1"].reasoning_effort == (
        models.ReasoningEffort.LOW
    )


@pytest.mark.parametrize(
    ("profile_id", "profile", "qualified_prompt_ids", "qualified_effort"),
    [
        (
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE,
            OPENAI_SOL_MEDIUM_PROMPT_IDS,
            models.ReasoningEffort.MEDIUM,
        ),
        (
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            OPENAI_SOL_HIGH_ROUTE_PROFILE,
            OPENAI_SOL_HIGH_PROMPT_IDS,
            models.ReasoningEffort.HIGH,
        ),
        (
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            OPENAI_SOL_XHIGH_ROUTE_PROFILE,
            OPENAI_SOL_XHIGH_PROMPT_IDS,
            models.ReasoningEffort.XHIGH,
        ),
    ],
)
def test_sol_ladder_profiles_are_exact_and_exclusive(
    profile_id: str,
    profile: Any,
    qualified_prompt_ids: frozenset[str],
    qualified_effort: models.ReasoningEffort,
) -> None:
    routes = build_openai_routes(
        max_call_cost_usd=2.05,
        route_profile_id=profile_id,
    )
    assert set(routes) == set(PROMPT_SPECS) - {"P10_ENRICHED_CONTEXT_V1"}
    assert all(route.model == SOL_MODEL_ID for route in routes.values())
    assert all(route.model_snapshot == SOL_MODEL_ID for route in routes.values())
    assert all(route.fallback_route_id is None for route in routes.values())
    assert all(
        route.route_id.startswith(f"route_openai_{profile_id.lower()}_")
        for route in routes.values()
    )
    assert {
        prompt_id
        for prompt_id, approved in profile.items()
        if (
            prompt_id in qualified_prompt_ids
            and approved.reasoning_effort == qualified_effort
        )
    } == set(qualified_prompt_ids)
    assert routes["P01_ACTIVITY_SPEC_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert routes["P02_RUBRIC_NORMALIZE_V1"].reasoning_effort == (
        models.ReasoningEffort.MEDIUM
    )
    assert routes["P03_AMBIGUITY_TRIAGE_V1"].reasoning_effort == (
        models.ReasoningEffort.HIGH
    )
    assert all(
        routes[prompt_id].reasoning_effort == qualified_effort
        for prompt_id in qualified_prompt_ids
    )
    assert routes["P11_SCHEMA_REPAIR_V1"].reasoning_effort == (
        models.ReasoningEffort.LOW
    )
    assert all(
        "SOL_ADAPTIVE_REASONING_LADDER_AUTHORIZED" in route.reason_codes
        for route in routes.values()
    )


def test_sol_ladder_changes_only_reasoning_within_family() -> None:
    medium = build_openai_routes(
        max_call_cost_usd=2.05,
        route_profile_id=OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
    )
    high = build_openai_routes(
        max_call_cost_usd=2.05,
        route_profile_id=OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
    )
    xhigh = build_openai_routes(
        max_call_cost_usd=2.05,
        route_profile_id=OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
    )
    for prompt_id in medium:
        for routes in (medium, high, xhigh):
            assert routes[prompt_id].model == SOL_MODEL_ID
        if prompt_id in OPENAI_SOL_MEDIUM_PROMPT_IDS:
            assert [
                medium[prompt_id].reasoning_effort,
                high[prompt_id].reasoning_effort,
                xhigh[prompt_id].reasoning_effort,
            ] == [
                models.ReasoningEffort.MEDIUM,
                models.ReasoningEffort.HIGH,
                models.ReasoningEffort.XHIGH,
            ]
        else:
            assert medium[prompt_id].reasoning_effort == (
                high[prompt_id].reasoning_effort
            ) == xhigh[prompt_id].reasoning_effort
        normalized = []
        for routes in (medium, high, xhigh):
            material = routes[prompt_id].model_dump(mode="json")
            material.pop("route_id")
            material.pop("reasoning_effort")
            material.pop("reason_codes")
            normalized.append(material)
        assert normalized[0] == normalized[1] == normalized[2]


def test_sol_profile_adapter_sends_exact_model_effort_and_controls() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=SOL_MODEL_ID)]
    )
    route = build_openai_routes(
        max_call_cost_usd=2.05,
        route_profile_id=OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
    )[prompt_id]
    result = asyncio.run(
        OpenAIResponsesAdapter(client=fake).invoke(
            prompt_id=prompt_id,
            request=request,
            envelope=_envelope(prompt_id, request),
            route=route,
            attempt=1,
            behavior=MockBehavior.HAPPY,
        )
    )
    assert result.raw_output is not None
    assert len(fake.responses.calls) == 1
    payload = fake.responses.calls[0]
    assert payload["model"] == SOL_MODEL_ID
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["tools"] == []
    assert payload["store"] is False
    assert payload["background"] is False
    assert payload["truncation"] == "disabled"


def test_xhigh_adapter_payload_changes_only_effective_reasoning() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    baseline_fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)]
    )
    xhigh_fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)]
    )
    baseline_route = build_openai_routes(max_call_cost_usd=0.10)[prompt_id]
    xhigh_routes = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
    )
    xhigh_route = xhigh_routes[prompt_id]

    for fake, route in (
        (baseline_fake, baseline_route),
        (xhigh_fake, xhigh_route),
    ):
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

    baseline_payload = baseline_fake.responses.calls[0]
    xhigh_payload = xhigh_fake.responses.calls[0]
    assert baseline_payload["reasoning"] == {"effort": "high"}
    assert xhigh_payload["reasoning"] == {"effort": "xhigh"}
    assert {
        key: value
        for key, value in baseline_payload.items()
        if key != "reasoning"
    } == {
        key: value
        for key, value in xhigh_payload.items()
        if key != "reasoning"
    }

    spec = prompt_spec(prompt_id)
    envelope = _envelope(prompt_id, request)
    baseline_tokens = build_openai_input_token_estimator(
        {prompt_id: baseline_route}
    )(spec, request, envelope)
    xhigh_tokens = build_openai_input_token_estimator(xhigh_routes)(
        spec, request, envelope
    )
    assert xhigh_tokens == baseline_tokens + 1


def test_max_adapter_payload_changes_only_xhigh_reasoning() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    xhigh_fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)]
    )
    max_fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)]
    )
    xhigh_routes = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
    )
    max_routes = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
    )

    for fake, route in (
        (xhigh_fake, xhigh_routes[prompt_id]),
        (max_fake, max_routes[prompt_id]),
    ):
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

    xhigh_payload = xhigh_fake.responses.calls[0]
    max_payload = max_fake.responses.calls[0]
    assert xhigh_payload["reasoning"] == {"effort": "xhigh"}
    assert max_payload["reasoning"] == {"effort": "max"}
    assert {
        key: value for key, value in xhigh_payload.items() if key != "reasoning"
    } == {
        key: value for key, value in max_payload.items() if key != "reasoning"
    }

    spec = prompt_spec(prompt_id)
    envelope = _envelope(prompt_id, request)
    xhigh_tokens = build_openai_input_token_estimator(xhigh_routes)(
        spec, request, envelope
    )
    max_tokens = build_openai_input_token_estimator(max_routes)(
        spec, request, envelope
    )
    assert max_tokens == xhigh_tokens - 2


def test_terra_medium_adapter_changes_only_model_and_effective_reasoning() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    max_fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=LUNA_MODEL_ID)]
    )
    terra_fake = FakeClient(
        [_response(_canonical_output(prompt_id), model=TERRA_MODEL_ID)]
    )
    max_route = build_openai_routes(
        max_call_cost_usd=0.27,
        route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
    )[prompt_id]
    terra_route = build_openai_routes(
        max_call_cost_usd=0.27,
        route_profile_id=OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
    )[prompt_id]

    for fake, route in ((max_fake, max_route), (terra_fake, terra_route)):
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

    max_payload = max_fake.responses.calls[0]
    terra_payload = terra_fake.responses.calls[0]
    assert terra_payload["model"] == TERRA_MODEL_ID
    assert terra_payload["reasoning"] == {"effort": "medium"}
    assert {
        key: value
        for key, value in max_payload.items()
        if key not in {"model", "reasoning"}
    } == {
        key: value
        for key, value in terra_payload.items()
        if key not in {"model", "reasoning"}
    }


def test_terra_model_requires_the_exact_profile_before_transport() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([])
    forged = build_openai_routes(max_call_cost_usd=0.27)[
        prompt_id
    ].model_copy(update={"model": TERRA_MODEL_ID})

    with pytest.raises(
        PermanentProviderError,
        match="PROVIDER_REASONING_ROUTE_MISMATCH",
    ):
        asyncio.run(
            OpenAIResponsesAdapter(client=fake).invoke(
                prompt_id=prompt_id,
                request=request,
                envelope=_envelope(prompt_id, request),
                route=forged,
                attempt=1,
                behavior=MockBehavior.HAPPY,
            )
        )
    assert fake.responses.calls == []


def test_max_reasoning_requires_the_exact_profile_before_transport() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([])
    forged = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
    )[prompt_id].model_copy(
        update={"reasoning_effort": models.ReasoningEffort.MAX}
    )

    with pytest.raises(
        PermanentProviderError,
        match="PROVIDER_REASONING_ROUTE_MISMATCH",
    ):
        asyncio.run(
            OpenAIResponsesAdapter(client=fake).invoke(
                prompt_id=prompt_id,
                request=request,
                envelope=_envelope(prompt_id, request),
                route=forged,
                attempt=1,
                behavior=MockBehavior.HAPPY,
            )
        )
    assert fake.responses.calls == []


def test_xhigh_reasoning_requires_the_exact_profile_before_transport() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([])
    forged = build_openai_routes(max_call_cost_usd=0.10)[prompt_id].model_copy(
        update={"reasoning_effort": models.ReasoningEffort.XHIGH}
    )

    with pytest.raises(
        PermanentProviderError,
        match="PROVIDER_REASONING_ROUTE_MISMATCH",
    ):
        asyncio.run(
            OpenAIResponsesAdapter(client=fake).invoke(
                prompt_id=prompt_id,
                request=request,
                envelope=_envelope(prompt_id, request),
                route=forged,
                attempt=1,
                behavior=MockBehavior.HAPPY,
            )
        )
    assert fake.responses.calls == []


def test_xhigh_route_identity_changes_execution_fingerprint() -> None:
    baseline_routes = build_openai_routes(max_call_cost_usd=0.10)
    xhigh_routes = build_openai_routes(
        max_call_cost_usd=0.10,
        route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
    )
    baseline_gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.REAL, max_retries=0),
        real_routes=baseline_routes,
        adapters={"openai": OpenAIResponsesAdapter(client=FakeClient([]))},
    )
    xhigh_gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.REAL, max_retries=0),
        real_routes=xhigh_routes,
        adapters={"openai": OpenAIResponsesAdapter(client=FakeClient([]))},
    )
    for prompt_id in sorted(OPENAI_XHIGH_PROMPT_IDS):
        assert baseline_gateway.execution_fingerprint(prompt_id) != (
            xhigh_gateway.execution_fingerprint(prompt_id)
        )


def test_adapter_rejects_forged_sol_route_before_transport() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    fake = FakeClient([])
    route = build_openai_routes(max_call_cost_usd=1.0)[prompt_id].model_copy(
        update={"model": SOL_MODEL_ID}
    )

    with pytest.raises(
        PermanentProviderError,
        match="PROVIDER_REASONING_ROUTE_MISMATCH",
    ):
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

    assert formatted["name"] == "cva_QuestionGenerationResult_1_1_4"
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
    repair = {
        "schema_version": "1.1.0",
        "target_schema_name": "ActivitySpec",
        "repair_status": "REPAIRED",
        "repaired_output": _canonical_output(prompt_id),
        "diagnostics": [],
    }
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


def test_malformed_json_fails_without_semantic_p11_repair() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    fake = FakeClient(
        [
            _response("{not-json", model=LUNA_MODEL_ID),
        ]
    )
    request = build_mock_request(prompt_id)

    with pytest.raises(GatewaySchemaViolation) as captured:
        asyncio.run(
            _real_gateway(fake).invoke(
                prompt_id, request, build_trusted_context(request)
            )
        )

    assert captured.value.repair_disposition == "NOT_STRUCTURALLY_REPAIRABLE"
    assert len(fake.responses.calls) == 1
    assert [ledger.prompt_id for ledger in captured.value.ledgers] == [
        prompt_id
    ]
    assert captured.value.primary_failure is not None
    assert [
        issue.error_type for issue in captured.value.primary_failure.issues
    ] == [
        "model_type"
    ]


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
    assert token_ceiling == 8_943
    assert cost == 0.01183575
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
    assert OpenAIAdapterConfig().request_timeout_seconds == 240.0
    assert OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS == 240.0
    assert OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS == 5.0
    sdk_effort_literal = get_args(OpenAIReasoningEffort)[0]
    assert "xhigh" in get_args(sdk_effort_literal)
    assert "max" in get_args(sdk_effort_literal)

    root = Path(__file__).resolve().parents[1]
    assert '"openai==2.53.0"' in (root / "pyproject.toml").read_text()
    for lock_name in ("requirements.lock", "requirements-dev.lock"):
        lock = (root / lock_name).read_text()
        assert "openai==2.53.0 \\" in lock
        openai_block = lock.split("openai==2.53.0 \\", 1)[1].split("\n\n", 1)[0]
        assert "--hash=sha256:" in openai_block


def test_authorization_request_cap_blocks_before_inner_transport() -> None:
    class FakeInner:
        config = OpenAIAdapterConfig(request_timeout_seconds=30)

        def __init__(self) -> None:
            self.calls = 0

        async def invoke(self, **_kwargs: Any) -> Any:
            self.calls += 1
            return SimpleNamespace(status="ok")

    inner = FakeInner()
    capped = RequestCappedAdapter(inner, max_requests=1)  # type: ignore[arg-type]

    assert asyncio.run(capped.invoke()).status == "ok"
    with pytest.raises(
        ProviderBudgetError,
        match="SYNTHETIC_PROVIDER_REQUEST_CAP_EXCEEDED",
    ):
        asyncio.run(capped.invoke())
    assert inner.calls == 1
    assert capped.calls == 1
