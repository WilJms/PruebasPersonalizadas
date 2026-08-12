"""Official OpenAI Responses API adapter with a fail-closed provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from pydantic import BaseModel, SecretStr

from comprehension_verification.contracts import models
from comprehension_verification.model_gateway.gateway import (
    AuthenticationProviderError,
    AuthorizationProviderError,
    MalformedProviderResponseError,
    ModelUnavailableProviderError,
    PermanentProviderError,
    ProviderBudgetError,
    ProviderTimeoutError,
    RateLimitProviderError,
    SafetyBlockProviderError,
    TransientProviderError,
)
from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    MockBehavior,
)
from comprehension_verification.model_gateway.openai_pricing import estimate_cost_usd
from comprehension_verification.model_gateway.openai_routes import (
    LUNA_MODEL_ID,
    openai_developer_instruction,
)
from comprehension_verification.model_gateway.openai_schema import (
    OpenAISchemaError,
    provider_schema_validation_issues,
    structured_output_format,
)
from comprehension_verification.model_gateway.registry import prompt_spec


OPENAI_SDK_VERSION = "2.53.0"
OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS = 240.0
OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class OpenAIAdapterConfig:
    request_timeout_seconds: float = OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not 5.0 <= self.request_timeout_seconds <= 300.0:
            raise ValueError("OpenAI request timeout must be between 5 and 300 seconds")


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_json(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _request_id_hash(value: Any) -> str | None:
    return _sha256_text(value) if isinstance(value, str) and value else None


def _exception_request_hash(exc: BaseException) -> str | None:
    return _request_id_hash(getattr(exc, "request_id", None))


def _usage_integer(value: Any, *path: str) -> int:
    for part in path:
        value = _get(value, part)
        if value is None:
            return 0
    return max(0, int(value)) if isinstance(value, (int, float)) else 0


class OpenAIResponsesAdapter:
    """Invoke exactly one approved prompt with no tools or provider state."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None = None,
        config: OpenAIAdapterConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or OpenAIAdapterConfig()
        if client is not None:
            self.client = client
            return
        if api_key is None or not api_key.get_secret_value().strip():
            raise ValueError("A non-empty OpenAI project API key is required in real mode")
        # SDK retry is intentionally disabled. ModelGateway owns the canonical
        # bounded retry ledger and backoff policy.
        self.client = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            max_retries=0,
            timeout=self.config.request_timeout_seconds,
        )

    async def invoke(
        self,
        *,
        prompt_id: str,
        request: BaseModel,
        envelope: models.ModelTaskEnvelope,
        route: models.ModelRoute,
        attempt: int,
        behavior: MockBehavior,
    ) -> AdapterResult:
        del behavior
        spec = prompt_spec(prompt_id)
        if route.provider != "openai" or route.model != LUNA_MODEL_ID:
            raise ModelUnavailableProviderError("PROVIDER_ROUTE_NOT_APPROVED")
        if prompt_id == "P10_ENRICHED_CONTEXT_V1":
            raise AuthorizationProviderError("P10_DISABLED")
        if spec.reasoning_effort != route.reasoning_effort:
            raise PermanentProviderError("PROVIDER_REASONING_ROUTE_MISMATCH")
        try:
            output_format = structured_output_format(spec, request)
        except OpenAISchemaError as exc:
            raise PermanentProviderError("PROVIDER_SCHEMA_BOUNDARY_UNSUPPORTED") from exc

        payload = {
            "model": route.model,
            "instructions": spec.system_instruction,
            "input": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": openai_developer_instruction(spec, envelope),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _canonical_json(envelope)}
                    ],
                },
            ],
            "max_output_tokens": spec.max_output_tokens,
            "reasoning": {"effort": route.reasoning_effort.value.lower()},
            "text": {"format": output_format},
            "store": False,
            "background": False,
            "tools": [],
            "parallel_tool_calls": False,
            "truncation": "disabled",
            "service_tier": "default",
            "timeout": self.config.request_timeout_seconds,
        }
        # Temperature is intentionally absent: current GPT-5.6 reasoning docs
        # do not establish compatibility for these non-none reasoning efforts.
        try:
            response = await self.client.responses.create(**payload)
        except APITimeoutError as exc:
            raise ProviderTimeoutError(
                "PROVIDER_TIMEOUT", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except APIConnectionError as exc:
            raise TransientProviderError(
                "PROVIDER_CONNECTION", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except AuthenticationError as exc:
            raise AuthenticationProviderError(
                "PROVIDER_AUTHENTICATION", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except PermissionDeniedError as exc:
            raise AuthorizationProviderError(
                "PROVIDER_AUTHORIZATION", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except NotFoundError as exc:
            raise ModelUnavailableProviderError(
                "PROVIDER_MODEL_UNAVAILABLE", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except RateLimitError as exc:
            code = str(getattr(exc, "code", "") or "").lower()
            if code in {
                "insufficient_quota",
                "billing_hard_limit_reached",
                "usage_limit_reached",
            }:
                raise ProviderBudgetError(
                    "PROVIDER_BUDGET_OR_QUOTA",
                    request_id_hash=_exception_request_hash(exc),
                ) from exc
            raise RateLimitProviderError(
                "PROVIDER_RATE_LIMIT", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except (BadRequestError, UnprocessableEntityError) as exc:
            code = str(getattr(exc, "code", "") or "").lower()
            if code in {"content_filter", "safety_violation"}:
                raise SafetyBlockProviderError(
                    "PROVIDER_SAFETY_REFUSAL",
                    request_id_hash=_exception_request_hash(exc),
                ) from exc
            raise PermanentProviderError(
                "PROVIDER_INVALID_REQUEST", request_id_hash=_exception_request_hash(exc)
            ) from exc
        except APIResponseValidationError as exc:
            raise MalformedProviderResponseError(
                "PROVIDER_SDK_RESPONSE_VALIDATION",
                request_id_hash=_exception_request_hash(exc),
            ) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code in {408, 409}:
                raise TransientProviderError(
                    "PROVIDER_TRANSIENT_STATUS",
                    request_id_hash=_exception_request_hash(exc),
                ) from exc
            raise PermanentProviderError(
                "PROVIDER_PERMANENT_STATUS",
                request_id_hash=_exception_request_hash(exc),
            ) from exc

        return self._result_from_response(
            response,
            route=route,
            attempt=attempt,
            output_schema=output_format["schema"],
        )

    @staticmethod
    def _result_from_response(
        response: Any,
        *,
        route: models.ModelRoute,
        attempt: int,
        output_schema: dict[str, Any],
    ) -> AdapterResult:
        request_hash = _request_id_hash(
            _get(response, "_request_id") or _get(response, "request_id")
        )
        error = _get(response, "error")
        if error is not None:
            code = str(_get(error, "code", "") or "").lower()
            if code in {"content_filter", "safety_violation"}:
                raise SafetyBlockProviderError(
                    "PROVIDER_SAFETY_REFUSAL", request_id_hash=request_hash
                )
            raise PermanentProviderError(
                "PROVIDER_RESPONSE_ERROR", request_id_hash=request_hash
            )
        status = _get(response, "status")
        if status != "completed":
            raise MalformedProviderResponseError(
                "PROVIDER_RESPONSE_INCOMPLETE", request_id_hash=request_hash
            )

        text_parts: list[str] = []
        for item in _get(response, "output", []) or []:
            item_type = _get(item, "type")
            if item_type == "reasoning":
                continue
            if item_type != "message":
                raise PermanentProviderError(
                    "PROVIDER_UNEXPECTED_TOOL_OUTPUT", request_id_hash=request_hash
                )
            for content in _get(item, "content", []) or []:
                content_type = _get(content, "type")
                if content_type == "refusal":
                    raise SafetyBlockProviderError(
                        "PROVIDER_SAFETY_REFUSAL", request_id_hash=request_hash
                    )
                if content_type != "output_text":
                    raise MalformedProviderResponseError(
                        "PROVIDER_UNEXPECTED_CONTENT_TYPE",
                        request_id_hash=request_hash,
                    )
                text = _get(content, "text")
                if not isinstance(text, str):
                    raise MalformedProviderResponseError(
                        "PROVIDER_OUTPUT_TEXT_MISSING", request_id_hash=request_hash
                    )
                text_parts.append(text)
        output_text = "".join(text_parts)
        if not output_text:
            raise MalformedProviderResponseError(
                "PROVIDER_EMPTY_OUTPUT", request_id_hash=request_hash
            )
        try:
            raw_output: Any = json.loads(output_text)
        except json.JSONDecodeError:
            # Preserve the invalid string as data for the one governed P11
            # structural repair. It is never executed or logged.
            raw_output = output_text

        provider_schema_issues = provider_schema_validation_issues(
            output_schema, raw_output
        )

        effective_model = str(_get(response, "model", "") or "")
        if not (
            effective_model == route.model
            or effective_model.startswith(f"{route.model}-")
        ):
            raise ModelUnavailableProviderError(
                "PROVIDER_EFFECTIVE_MODEL_MISMATCH", request_id_hash=request_hash
            )
        usage = _get(response, "usage")
        input_tokens = _usage_integer(usage, "input_tokens")
        cached_tokens = _usage_integer(
            usage, "input_tokens_details", "cached_tokens"
        )
        cache_write_tokens = _usage_integer(
            usage, "input_tokens_details", "cache_write_tokens"
        )
        output_tokens = _usage_integer(usage, "output_tokens")
        reasoning_tokens = _usage_integer(
            usage, "output_tokens_details", "reasoning_tokens"
        )
        estimated_cost = estimate_cost_usd(
            model=route.model,
            input_tokens=input_tokens,
            output_tokens=route.max_output_tokens,
            cached_input_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        actual_cost = estimate_cost_usd(
            model=route.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        return AdapterResult(
            raw_output=raw_output,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
            actual_cost_usd=actual_cost,
            cache_write_input_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            effective_model=effective_model,
            output_hash=_sha256_text(output_text),
            provider_request_id_hash=request_hash,
            provider_schema_valid=not provider_schema_issues,
            provider_schema_issues=provider_schema_issues,
            reason_codes=(
                "OPENAI_RESPONSES_API",
                f"OPENAI_SDK_{OPENAI_SDK_VERSION.replace('.', '_')}",
                "SDK_RETRIES_0",
                "STRUCTURED_OUTPUT_STRICT",
                (
                    "PROVIDER_SCHEMA_VALID"
                    if not provider_schema_issues
                    else "PROVIDER_SCHEMA_INVALID"
                ),
                "STORE_FALSE",
                "BACKGROUND_FALSE",
                "TOOLS_EMPTY",
                "TEMPERATURE_OMITTED",
                "SERVICE_TIER_DEFAULT",
                f"REASONING_EFFORT_{route.reasoning_effort.value}",
                f"PROVIDER_ATTEMPT_{attempt}",
            ),
        )


class RequestCappedAdapter:
    """Enforce one authorization-wide request cap before provider transport."""

    def __init__(self, inner: OpenAIResponsesAdapter, *, max_requests: int) -> None:
        if not 1 <= max_requests <= 64:
            raise ValueError("provider request cap must be between 1 and 64")
        self.inner = inner
        self.config = getattr(inner, "config", None)
        self.max_requests = max_requests
        self.calls = 0

    async def invoke(self, **kwargs: Any) -> AdapterResult:
        if self.calls >= self.max_requests:
            raise ProviderBudgetError("SYNTHETIC_PROVIDER_REQUEST_CAP_EXCEEDED")
        self.calls += 1
        return await self.inner.invoke(**kwargs)
