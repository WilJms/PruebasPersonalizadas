"""Small, governed ModelGateway for the Stage 0 offline harness.

There is no agent loop, tool execution, network access, or implicit provider
fallback here.  A call validates request, envelope and output in that order,
and records one canonical ledger entry per provider/mock attempt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
import json
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from comprehension_verification.contracts import SCHEMA_VERSION, model_by_name, models
from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    DeterministicMockAdapter,
    MockBehavior,
)
from comprehension_verification.model_gateway.registry import PromptSpec, prompt_spec


class GatewayMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


class ValidationPhase(StrEnum):
    REQUEST = "request"
    ENVELOPE = "envelope"
    OUTPUT = "output"
    REPAIRED_OUTPUT = "repaired_output"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    mode: GatewayMode = GatewayMode.MOCK
    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.01
    default_budget_usd: float = 0.25
    job_id: str = "job_model_gateway"
    clock: Callable[[], datetime] = field(default=_utc_now, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            object.__setattr__(self, "mode", GatewayMode(self.mode))
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if not 0 <= self.max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2")
        if self.backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds must be >= 0")
        if self.default_budget_usd < 0:
            raise ValueError("default_budget_usd must be >= 0")


@dataclass(frozen=True, slots=True)
class CallBudget:
    max_cost_usd: float
    estimated_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.max_cost_usd < 0 or self.estimated_cost_usd < 0:
            raise ValueError("cost budgets must be >= 0")


@dataclass(frozen=True, slots=True)
class GatewayCallResult:
    prompt_id: str
    output: BaseModel
    envelope: models.ModelTaskEnvelope
    route_resolution: models.ModelRouteResolution
    ledgers: tuple[models.ModelCallLedger, ...]
    validation_order: tuple[ValidationPhase, ...]
    repair_validation_order: tuple[ValidationPhase, ...] = ()
    repaired: bool = False


class GatewayError(RuntimeError):
    code = "MODEL_GATEWAY_ERROR"

    def __init__(
        self,
        message: str,
        *,
        ledgers: Sequence[models.ModelCallLedger] = (),
        resolution: models.ModelRouteResolution | None = None,
    ) -> None:
        super().__init__(message)
        self.ledgers = tuple(ledgers)
        self.resolution = resolution


class GatewayValidationError(GatewayError):
    code = "MODEL_CONTRACT_VALIDATION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        phase: ValidationPhase,
        ledgers: Sequence[models.ModelCallLedger] = (),
    ) -> None:
        super().__init__(message, ledgers=ledgers)
        self.phase = phase


class GatewayContextError(GatewayError):
    code = "MODEL_CONTEXT_NOT_ALLOWLISTED"


class GatewayRouteBlocked(GatewayError):
    code = "MODEL_ROUTE_BLOCKED"


class GatewayBudgetExceeded(GatewayRouteBlocked):
    code = "MODEL_BUDGET_EXCEEDED"


class GatewayTimeout(GatewayError):
    code = "MODEL_TIMEOUT"


class GatewayProviderError(GatewayError):
    code = "MODEL_PROVIDER_ERROR"


class GatewaySafetyBlock(GatewayError):
    code = "MODEL_SAFETY_BLOCK"


class GatewaySchemaViolation(GatewayValidationError):
    code = "MODEL_SCHEMA_VIOLATION"


class TransientProviderError(RuntimeError):
    """An adapter may raise this to request governed transient retry."""


class RateLimitProviderError(TransientProviderError):
    """Transient provider rate limit, recorded separately in the ledger."""


class PermanentProviderError(RuntimeError):
    """Non-retryable provider failure."""


class SafetyBlockProviderError(RuntimeError):
    """Provider safety refusal; the gateway never retries to evade it."""


@runtime_checkable
class ModelAdapter(Protocol):
    async def invoke(
        self,
        *,
        prompt_id: str,
        request: BaseModel,
        envelope: models.ModelTaskEnvelope,
        route: models.ModelRoute,
        attempt: int,
        behavior: MockBehavior,
    ) -> AdapterResult: ...


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return f"sha256:{sha256(_canonical_json(value)).hexdigest()}"


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _mock_route(spec: PromptSpec) -> models.ModelRoute:
    """Truthful local route: never claims a paid provider was called."""

    return models.ModelRoute(
        route_id=f"route_mock_{spec.prompt_id.lower()}",
        task=spec.task,
        provider="other",
        model=f"deterministic-mock-{spec.prompt_id.lower()}",
        model_snapshot="deterministic-mock-v1",
        reasoning_effort=spec.reasoning_effort,
        temperature=spec.temperature,
        capabilities=models.ModelCapabilities(
            input_modalities=[
                models.ModelInputModality.TEXT,
                models.ModelInputModality.IMAGE,
                models.ModelInputModality.PDF,
            ],
            output_modalities=[models.ModelOutputModality.STRUCTURED_JSON],
            structured_outputs=True,
            max_context_tokens=250_000,
            supported_reasoning_efforts=[
                models.ReasoningEffort.MINIMAL,
                models.ReasoningEffort.LOW,
                models.ReasoningEffort.MEDIUM,
                models.ReasoningEffort.HIGH,
            ],
            supports_zero_data_retention=True,
            supported_regions=["local-offline"],
        ),
        retention_mode="ZDR",
        region="local-offline",
        # Canonical ModelRoute requires a positive cap. Actual mock cost is zero.
        max_cost_usd=0.01,
        max_input_tokens=250_000,
        max_output_tokens=max(16_000, spec.max_output_tokens),
        reason_codes=["MOCK_MODE", "NO_NETWORK", f"PROMPT_POLICY_{spec.prompt_id[:3]}"],
    )


class ModelRouteResolver:
    """Resolve only pre-approved configurations; never choose heuristically."""

    def __init__(
        self,
        *,
        mode: GatewayMode,
        real_routes: Mapping[str, models.ModelRoute] | None = None,
        available_providers: Sequence[str] = (),
    ) -> None:
        self.mode = GatewayMode(mode)
        self.real_routes = dict(real_routes or {})
        self.available_providers = frozenset(available_providers)

    def resolve(
        self,
        spec: PromptSpec,
        *,
        required_input_modalities: Sequence[models.ModelInputModality],
        required_output_modalities: Sequence[models.ModelOutputModality],
        budget: CallBudget,
        estimated_input_tokens: int,
    ) -> models.ModelRouteResolution:
        route = (
            _mock_route(spec)
            if self.mode == GatewayMode.MOCK
            else self.real_routes.get(spec.prompt_id)
        )
        evaluated = [route.route_id] if route is not None else []

        if route is None:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "REAL_ROUTE_NOT_CONFIGURED",
            )
        if self.mode == GatewayMode.REAL and route.provider not in self.available_providers:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "REAL_ADAPTER_NOT_CONFIGURED",
            )
        if budget.estimated_cost_usd > budget.max_cost_usd:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "CALL_BUDGET_EXCEEDED",
            )
        if budget.estimated_cost_usd > route.max_cost_usd:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "ROUTE_BUDGET_EXCEEDED",
            )
        if estimated_input_tokens > route.max_input_tokens:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "INPUT_TOKEN_LIMIT_EXCEEDED",
            )
        if spec.max_output_tokens > route.max_output_tokens:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "OUTPUT_TOKEN_LIMIT_EXCEEDED",
            )

        route_inputs = set(route.capabilities.input_modalities)
        route_outputs = set(route.capabilities.output_modalities)
        if not set(required_input_modalities).issubset(route_inputs):
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "INPUT_MODALITY_UNSUPPORTED",
                status="NEEDS_REVIEW",
            )
        if not set(required_output_modalities).issubset(route_outputs):
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "OUTPUT_MODALITY_UNSUPPORTED",
                status="NEEDS_REVIEW",
            )
        if not route.capabilities.structured_outputs:
            return self._unresolved(
                spec,
                required_input_modalities,
                required_output_modalities,
                evaluated,
                "STRUCTURED_OUTPUTS_REQUIRED",
            )

        return models.ModelRouteResolution(
            resolution_id=_stable_id("resolution", spec.prompt_id, route.route_id, "resolved"),
            task=spec.task,
            status="RESOLVED",
            required_input_modalities=list(required_input_modalities),
            required_output_modalities=list(required_output_modalities),
            route=route,
            evaluated_route_ids=evaluated,
            reason_codes=["PROMPT_ROUTE_APPROVED", "CAPABILITIES_AND_POLICY_MATCH"],
        )

    def _unresolved(
        self,
        spec: PromptSpec,
        inputs: Sequence[models.ModelInputModality],
        outputs: Sequence[models.ModelOutputModality],
        evaluated: list[str],
        reason: str,
        *,
        status: str = "BLOCKED",
    ) -> models.ModelRouteResolution:
        return models.ModelRouteResolution(
            resolution_id=_stable_id("resolution", spec.prompt_id, reason),
            task=spec.task,
            status=status,
            required_input_modalities=list(inputs),
            required_output_modalities=list(outputs),
            route=None,
            evaluated_route_ids=evaluated,
            reason_codes=[reason],
        )


class ModelGateway:
    """Governed P01-P11 executor with deterministic mocks by default."""

    def __init__(
        self,
        config: GatewayConfig | None = None,
        *,
        real_routes: Mapping[str, models.ModelRoute] | None = None,
        adapters: Mapping[str, ModelAdapter] | None = None,
        ledger_sink: Callable[[models.ModelCallLedger], None] | None = None,
        mock_adapter: DeterministicMockAdapter | None = None,
    ) -> None:
        self.config = config or GatewayConfig()
        self.adapters = dict(adapters or {})
        self.mock_adapter = mock_adapter or DeterministicMockAdapter()
        self.ledger_sink = ledger_sink
        self.resolver = ModelRouteResolver(
            mode=self.config.mode,
            real_routes=real_routes,
            available_providers=tuple(self.adapters),
        )

    async def invoke(
        self,
        prompt_id: str,
        payload: BaseModel | Mapping[str, Any],
        trusted_context: models.TrustedPromptContext | Mapping[str, Any],
        *,
        behavior: MockBehavior = MockBehavior.HAPPY,
        budget: CallBudget | None = None,
        required_input_modalities: Sequence[models.ModelInputModality] = (
            models.ModelInputModality.TEXT,
        ),
    ) -> GatewayCallResult:
        """Validate and execute exactly one model task.

        ``behavior`` is honored only in mock mode.  Real mode always uses
        ``happy`` and is blocked unless an explicit route and adapter exist.
        """

        spec = prompt_spec(prompt_id)
        validation_order: list[ValidationPhase] = []
        ledgers: list[models.ModelCallLedger] = []

        request = self._validate_request(spec, payload)
        validation_order.append(ValidationPhase.REQUEST)

        envelope = self._validate_envelope(spec, request, trusted_context)
        validation_order.append(ValidationPhase.ENVELOPE)
        self._validate_context(request, envelope.trusted_context, prompt_id=prompt_id)

        encoded_request = _canonical_json(request)
        input_token_estimate = max(1, len(encoded_request) // 4)
        call_budget = budget or CallBudget(self.config.default_budget_usd)
        resolution = self.resolver.resolve(
            spec,
            required_input_modalities=required_input_modalities,
            required_output_modalities=(models.ModelOutputModality.STRUCTURED_JSON,),
            budget=call_budget,
            estimated_input_tokens=input_token_estimate,
        )
        if resolution.status != "RESOLVED" or resolution.route is None:
            error_type = (
                GatewayBudgetExceeded
                if any("BUDGET" in reason for reason in resolution.reason_codes)
                else GatewayRouteBlocked
            )
            raise error_type(
                f"Model route is {resolution.status}: {','.join(resolution.reason_codes)}",
                resolution=resolution,
            )

        route = resolution.route
        adapter = self._adapter_for(route)
        effective_behavior = (
            MockBehavior(behavior)
            if self.config.mode == GatewayMode.MOCK
            else MockBehavior.HAPPY
        )
        retry_limit = min(self.config.max_retries, spec.max_transient_retries)

        for attempt in range(1, retry_limit + 2):
            started = perf_counter()
            try:
                adapter_result = await asyncio.wait_for(
                    adapter.invoke(
                        prompt_id=prompt_id,
                        request=request,
                        envelope=envelope,
                        route=route,
                        attempt=attempt,
                        behavior=effective_behavior,
                    ),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError as exc:
                ledger = self._ledger(
                    spec=spec,
                    envelope=envelope,
                    route=route,
                    attempt=attempt,
                    result="TIMEOUT",
                    latency_ms=self._elapsed_ms(started),
                    input_tokens=input_token_estimate,
                    output_tokens=0,
                    estimated_cost_usd=call_budget.estimated_cost_usd,
                    actual_cost_usd=0.0 if self.config.mode == GatewayMode.MOCK else None,
                )
                self._record(ledger, ledgers)
                if attempt <= retry_limit:
                    await self._backoff(attempt)
                    continue
                raise GatewayTimeout(
                    "Model call timed out after governed retries", ledgers=ledgers
                ) from exc
            except RateLimitProviderError as exc:
                self._record_provider_failure(
                    ledgers,
                    spec,
                    envelope,
                    route,
                    attempt,
                    started,
                    "RATE_LIMIT",
                    input_token_estimate,
                    call_budget,
                )
                if attempt <= retry_limit:
                    await self._backoff(attempt)
                    continue
                raise GatewayProviderError(
                    "Provider rate limit exhausted governed retries", ledgers=ledgers
                ) from exc
            except TransientProviderError as exc:
                self._record_provider_failure(
                    ledgers,
                    spec,
                    envelope,
                    route,
                    attempt,
                    started,
                    "PROVIDER_ERROR",
                    input_token_estimate,
                    call_budget,
                )
                if attempt <= retry_limit:
                    await self._backoff(attempt)
                    continue
                raise GatewayProviderError(
                    "Transient provider failure exhausted governed retries",
                    ledgers=ledgers,
                ) from exc
            except SafetyBlockProviderError as exc:
                self._record_provider_failure(
                    ledgers,
                    spec,
                    envelope,
                    route,
                    attempt,
                    started,
                    "SAFETY_BLOCK",
                    input_token_estimate,
                    call_budget,
                )
                raise GatewaySafetyBlock(
                    "Provider returned a safety block; no evasion retry is allowed",
                    ledgers=ledgers,
                ) from exc
            except (PermanentProviderError, Exception) as exc:
                # Adapter exceptions are never exposed with provider/content detail.
                self._record_provider_failure(
                    ledgers,
                    spec,
                    envelope,
                    route,
                    attempt,
                    started,
                    "PROVIDER_ERROR",
                    input_token_estimate,
                    call_budget,
                )
                raise GatewayProviderError(
                    "Non-retryable model adapter failure", ledgers=ledgers
                ) from exc

            try:
                output = self._validate_output(spec, adapter_result.raw_output)
            except GatewaySchemaViolation as exc:
                validation_order.append(ValidationPhase.OUTPUT)
                invalid_ledger = self._ledger(
                    spec=spec,
                    envelope=envelope,
                    route=route,
                    attempt=attempt,
                    result="SCHEMA_INVALID",
                    latency_ms=self._elapsed_ms(started),
                    input_tokens=adapter_result.input_tokens,
                    cached_input_tokens=adapter_result.cached_input_tokens,
                    output_tokens=adapter_result.output_tokens,
                    estimated_cost_usd=adapter_result.estimated_cost_usd,
                    actual_cost_usd=adapter_result.actual_cost_usd,
                )
                self._record(invalid_ledger, ledgers)
                if prompt_id == "P11_SCHEMA_REPAIR_V1":
                    raise GatewaySchemaViolation(
                        "P11 output was invalid; recursive repair is forbidden",
                        phase=ValidationPhase.OUTPUT,
                        ledgers=ledgers,
                    ) from exc
                repaired, repair_ledgers, repair_order = await self._repair_once(
                    target_spec=spec,
                    invalid_output=adapter_result.raw_output,
                    validation_error=exc,
                    trusted_context=envelope.trusted_context,
                )
                ledgers.extend(repair_ledgers)
                validation_order.append(ValidationPhase.REPAIRED_OUTPUT)
                try:
                    self._validate_context(
                        repaired,
                        envelope.trusted_context,
                        prompt_id=prompt_id,
                        output=True,
                    )
                    self._validate_output_relationship(prompt_id, request, repaired)
                except GatewayContextError as context_error:
                    raise GatewayContextError(
                        "Repaired output failed contextual validation",
                        ledgers=ledgers,
                    ) from context_error
                return GatewayCallResult(
                    prompt_id=prompt_id,
                    output=repaired,
                    envelope=envelope,
                    route_resolution=resolution,
                    ledgers=tuple(ledgers),
                    validation_order=tuple(validation_order),
                    repair_validation_order=repair_order,
                    repaired=True,
                )

            validation_order.append(ValidationPhase.OUTPUT)
            try:
                self._validate_context(
                    output, envelope.trusted_context, prompt_id=prompt_id, output=True
                )
                self._validate_output_relationship(prompt_id, request, output)
            except GatewayContextError as context_error:
                self._record_invalid_output(
                    ledgers=ledgers,
                    spec=spec,
                    envelope=envelope,
                    route=route,
                    attempt=attempt,
                    started=started,
                    result=adapter_result,
                )
                raise GatewayContextError(
                    "Model output failed contextual validation",
                    ledgers=ledgers,
                ) from context_error
            if prompt_id == "P11_SCHEMA_REPAIR_V1":
                self._revalidate_repair_target(output)
                if output.repair_status == models.RepairStatus.REPAIRED:
                    validation_order.append(ValidationPhase.REPAIRED_OUTPUT)
            valid_ledger = self._ledger(
                spec=spec,
                envelope=envelope,
                route=route,
                attempt=attempt,
                result="SCHEMA_VALID",
                latency_ms=self._elapsed_ms(started),
                input_tokens=adapter_result.input_tokens,
                cached_input_tokens=adapter_result.cached_input_tokens,
                output_tokens=adapter_result.output_tokens,
                estimated_cost_usd=adapter_result.estimated_cost_usd,
                actual_cost_usd=adapter_result.actual_cost_usd,
            )
            self._record(valid_ledger, ledgers)
            return GatewayCallResult(
                prompt_id=prompt_id,
                output=output,
                envelope=envelope,
                route_resolution=resolution,
                ledgers=tuple(ledgers),
                validation_order=tuple(validation_order),
            )

        raise AssertionError("unreachable retry loop")

    def _validate_request(
        self, spec: PromptSpec, payload: BaseModel | Mapping[str, Any]
    ) -> BaseModel:
        request_model = model_by_name(spec.input_schema_name)
        raw = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        try:
            return request_model.model_validate(raw)
        except ValidationError as exc:
            raise GatewayValidationError(
                "Request root validation failed", phase=ValidationPhase.REQUEST
            ) from exc

    def _validate_envelope(
        self,
        spec: PromptSpec,
        request: BaseModel,
        trusted_context: models.TrustedPromptContext | Mapping[str, Any],
    ) -> models.ModelTaskEnvelope:
        raw_context = (
            trusted_context.model_dump(mode="json")
            if isinstance(trusted_context, BaseModel)
            else trusted_context
        )
        raw = {
            "schema_version": SCHEMA_VERSION,
            "prompt_id": spec.prompt_id,
            "prompt_version": spec.prompt_version,
            "output_schema_name": spec.output_schema_name,
            "output_schema_version": SCHEMA_VERSION,
            "trusted_context": raw_context,
            "payload": request.model_dump(mode="json"),
        }
        try:
            return models.ModelTaskEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise GatewayValidationError(
                "ModelTaskEnvelope validation failed", phase=ValidationPhase.ENVELOPE
            ) from exc

    def _validate_output(self, spec: PromptSpec, raw_output: Any) -> BaseModel:
        output_model = model_by_name(spec.output_schema_name)
        try:
            return output_model.model_validate(raw_output)
        except ValidationError as exc:
            error = GatewaySchemaViolation(
                "Output root validation failed", phase=ValidationPhase.OUTPUT
            )
            error.validation_errors = tuple(exc.errors(include_url=False))
            raise error from exc

    def _validate_context(
        self,
        value: BaseModel,
        trusted: models.TrustedPromptContext,
        *,
        prompt_id: str,
        output: bool = False,
    ) -> None:
        data = value.model_dump(mode="json")
        evidence_ids, source_ids = self._collect_authorized_ids(data)
        if not evidence_ids.issubset(set(trusted.allowed_evidence_ids)):
            raise GatewayContextError("Payload contains an evidence_id outside the allowlist")
        if not source_ids.issubset(set(trusted.allowed_course_source_ids)):
            raise GatewayContextError("Payload contains a source_id outside the allowlist")

        modes = {
            item.get("context_mode")
            for item in self._walk_dicts(data)
            if item.get("context_mode") is not None
        }
        if modes and any(mode != trusted.context_mode.value for mode in modes):
            raise GatewayContextError("Context mode differs from the trusted envelope")
        if prompt_id == "P07_QUESTION_BUILD_V1" and trusted.context_mode != models.ContextMode.CLOSED:
            raise GatewayContextError("P07 requires CLOSED context")
        if prompt_id == "P10_ENRICHED_CONTEXT_V1" and trusted.context_mode != models.ContextMode.COURSE_ENRICHED:
            raise GatewayContextError("P10 requires COURSE_ENRICHED context")

        if output:
            self._validate_clean_abstention(prompt_id, value)
            if prompt_id == "P09_GUIDE_BUILD_V1" and value.status == "READY":
                # A ready P09 output must cover the full input assessment.  The
                # request-level relationship is checked in invoke's envelope.
                if not value.items:
                    raise GatewayContextError("READY guide cannot be empty")

    @staticmethod
    def _walk_dicts(value: Any):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from ModelGateway._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from ModelGateway._walk_dicts(child)

    @classmethod
    def _collect_authorized_ids(cls, data: Any) -> tuple[set[str], set[str]]:
        evidence_ids: set[str] = set()
        source_ids: set[str] = set()
        for item in cls._walk_dicts(data):
            if isinstance(item.get("evidence_id"), str):
                evidence_ids.add(item["evidence_id"])
            evidence_ids.update(
                value for value in item.get("evidence_ids", []) if isinstance(value, str)
            )
            if isinstance(item.get("source_id"), str):
                source_ids.add(item["source_id"])
            source_ids.update(
                value for value in item.get("source_ids", []) if isinstance(value, str)
            )
            source_ids.update(
                value
                for value in item.get("course_source_ids", [])
                if isinstance(value, str)
            )
        return evidence_ids, source_ids

    @staticmethod
    def _validate_clean_abstention(prompt_id: str, output: BaseModel) -> None:
        def require_diagnostic() -> None:
            if not getattr(output, "diagnostics", None):
                raise GatewayContextError("Abstention requires a complete diagnostic")

        if (
            prompt_id == "P01_ACTIVITY_SPEC_V1"
            and output.status != models.WorkflowStatus.READY
        ):
            require_diagnostic()
            if any(
                (
                    output.learning_outcomes,
                    output.expected_products,
                    output.requirements,
                    output.allowed_materials,
                    output.prohibited_materials,
                )
            ):
                raise GatewayContextError("P01 abstention cannot fabricate sourced fields")
        elif (
            prompt_id == "P02_RUBRIC_NORMALIZE_V1"
            and output.status != models.WorkflowStatus.READY
        ):
            require_diagnostic()
            if output.criteria:
                raise GatewayContextError("P02 abstention cannot fabricate criteria")
        elif prompt_id == "P03_AMBIGUITY_TRIAGE_V1" and output.blocked and not output.issues:
            raise GatewayContextError("Blocked P03 output requires an actionable issue")
        elif prompt_id == "P04_BLUEPRINT_BUILD_V1":
            if output.approved_by is not None or output.approved_at is not None:
                raise GatewayContextError(
                    "P04 cannot fabricate server-side human approval metadata"
                )
            if output.status != models.WorkflowStatus.READY:
                require_diagnostic()
        elif prompt_id == "P05_BLUEPRINT_REVIEW_V1" and output.status != "READY":
            require_diagnostic()
            if output.approval_recommendation is not None:
                raise GatewayContextError("Non-ready P05 output cannot recommend approval")
        elif prompt_id == "P06_EVIDENCE_MAP_V1" and output.status != "READY":
            require_diagnostic()
            if output.opportunities:
                raise GatewayContextError("Failed P06 output cannot expose opportunities")
        elif prompt_id in {"P07_QUESTION_BUILD_V1", "P10_ENRICHED_CONTEXT_V1"} and output.status != "READY":
            require_diagnostic()
            if output.candidate is not None:
                raise GatewayContextError("Failed question generation cannot expose a candidate")
        elif prompt_id == "P08_QUESTION_REVIEW_V1" and output.status != "READY":
            require_diagnostic()
            if output.review is not None:
                raise GatewayContextError("P08 abstention cannot fabricate scores")
        elif prompt_id == "P09_GUIDE_BUILD_V1" and output.status != "READY":
            require_diagnostic()
            if output.items:
                raise GatewayContextError("P09 abstention cannot expose a partial guide")
        elif prompt_id == "P11_SCHEMA_REPAIR_V1" and output.repair_status == models.RepairStatus.UNREPAIRABLE:
            require_diagnostic()

    @staticmethod
    def _validate_output_relationship(
        prompt_id: str, request: BaseModel, output: BaseModel
    ) -> None:
        """Check cross-root relationships that JSON Schema cannot express."""

        if prompt_id == "P01_ACTIVITY_SPEC_V1":
            if output.activity_id != request.activity_config.activity_id:
                raise GatewayContextError("P01 output activity_id mismatch")
        elif prompt_id == "P02_RUBRIC_NORMALIZE_V1":
            if output.activity_id != request.activity_spec.activity_id:
                raise GatewayContextError("P02 output activity_id mismatch")
        elif prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
            if output.activity_id != request.activity_spec.activity_id:
                raise GatewayContextError("P03 output activity_id mismatch")
        elif prompt_id == "P04_BLUEPRINT_BUILD_V1":
            if output.activity_id != request.activity_spec.activity_id:
                raise GatewayContextError("P04 output activity_id mismatch")
            constraints = output.assessment_constraints
            policy = request.blueprint_policy
            if (
                constraints.question_count != policy.question_count
                or constraints.target_total_minutes != policy.target_total_minutes
                or set(constraints.allowed_response_formats)
                != set(policy.allowed_response_formats)
            ):
                raise GatewayContextError("P04 output changed trusted blueprint constraints")
            if set(output.decision_ids) != {
                decision.decision_id for decision in request.resolved_decisions
            }:
                raise GatewayContextError("P04 output changed trusted policy decisions")
            learning_outcome_ids = {
                item.statement_id for item in request.activity_spec.learning_outcomes
            }
            source_statement_ids = {
                item.statement_id
                for collection in (
                    request.activity_spec.learning_outcomes,
                    request.activity_spec.expected_products,
                    request.activity_spec.requirements,
                )
                for item in collection
            }
            rubric_criterion_ids = (
                {item.criterion_id for item in request.rubric_spec.criteria}
                if request.rubric_spec is not None
                else set()
            )
            allowed_criterion_ids = rubric_criterion_ids or source_statement_ids
            blueprint_criterion_ids: set[str] = set()
            for dimension in output.dimensions:
                if not set(dimension.learning_outcome_ids).issubset(
                    learning_outcome_ids
                ):
                    raise GatewayContextError(
                        "P04 output invented learning outcome IDs"
                    )
                if not set(dimension.criterion_ids).issubset(
                    allowed_criterion_ids
                ):
                    raise GatewayContextError("P04 output invented criterion IDs")
                blueprint_criterion_ids.update(dimension.criterion_ids)
            policy_criterion_ids = set(policy.priority_criterion_ids).union(
                policy.required_criterion_ids
            )
            if not policy_criterion_ids.issubset(allowed_criterion_ids):
                raise GatewayContextError(
                    "P04 policy references criteria absent from normalized sources"
                )
            if not set(policy.required_criterion_ids).issubset(
                blueprint_criterion_ids
            ):
                raise GatewayContextError(
                    "P04 output omitted a required trusted criterion"
                )
        elif prompt_id == "P05_BLUEPRINT_REVIEW_V1":
            expected = (
                request.blueprint.blueprint_id,
                request.blueprint.blueprint_version,
                request.activity_spec.activity_id,
            )
            actual = (output.blueprint_id, output.blueprint_version, output.activity_id)
            if actual != expected:
                raise GatewayContextError("P05 output blueprint reference mismatch")
        elif prompt_id == "P06_EVIDENCE_MAP_V1":
            if output.submission_id != request.evidence_bundle.submission_id:
                raise GatewayContextError("P06 output submission_id mismatch")
        elif prompt_id in {"P07_QUESTION_BUILD_V1", "P10_ENRICHED_CONTEXT_V1"}:
            if (
                output.submission_id != request.plan.submission_id
                or output.opportunity_id != request.opportunity.opportunity_id
                or output.context_mode != request.evidence_bundle.context_mode
            ):
                raise GatewayContextError("Question output does not match its authorized request")
            if output.candidate is not None:
                candidate = output.candidate
                if (
                    candidate.opportunity_template_id
                    != request.opportunity.opportunity_template_id
                    or candidate.dimension_id != request.opportunity.dimension_id
                    or candidate.variant_id != request.opportunity.variant_id
                    or candidate.cognitive_operation
                    != request.opportunity.cognitive_operation
                ):
                    raise GatewayContextError("Question output changed its planned opportunity")
                if not set(candidate.evidence_ids).issubset(
                    set(request.evidence_bundle.allowed_evidence_ids)
                ):
                    raise GatewayContextError("Question output invented evidence_ids")
        elif prompt_id == "P08_QUESTION_REVIEW_V1":
            if (
                output.submission_id != request.evidence_bundle.submission_id
                or output.opportunity_id != request.opportunity.opportunity_id
            ):
                raise GatewayContextError("P08 output request reference mismatch")
            if output.review is not None:
                candidate = request.generation_result.candidate
                if candidate is None or output.review.candidate_id != candidate.candidate_id:
                    raise GatewayContextError("P08 reviewed a different candidate")
                review = output.review
                policy = request.validation_policy
                if review.decision == models.ReviewDecision.ACCEPT and (
                    review.critical_failure_codes
                    or review.confidence < policy.escalate_below_confidence
                    or review.scores.groundedness < policy.minimum_groundedness
                    or review.scores.anchor_sufficiency
                    < policy.minimum_anchor_sufficiency
                    or review.scores.criterion_relevance
                    < policy.minimum_criterion_relevance
                    or review.scores.answerability < policy.minimum_answerability
                ):
                    raise GatewayContextError(
                        "P08 accepted a question below trusted validation gates"
                    )
        elif prompt_id == "P09_GUIDE_BUILD_V1":
            if (
                output.guide_id != request.guide_id
                or output.assessment_id != request.assessment.assessment_id
                or output.submission_id != request.assessment.submission_id
            ):
                raise GatewayContextError("P09 output assessment reference mismatch")
            questions = {q.question_id: q for q in request.assessment.questions}
            if output.status == "READY" and {item.question_id for item in output.items} != set(
                questions
            ):
                raise GatewayContextError("READY guide must cover every assessment question")
            for item in output.items:
                question = questions.get(item.question_id)
                if question is None:
                    raise GatewayContextError("Guide references an unknown question_id")
                for element in item.guide.observable_elements:
                    if not set(element.evidence_ids).issubset(set(question.evidence_ids)):
                        raise GatewayContextError("Guide invented evidence for a question")
                    if not set(element.source_ids).issubset(set(question.course_source_ids)):
                        raise GatewayContextError("Guide invented a course source")
        elif prompt_id == "P11_SCHEMA_REPAIR_V1":
            if output.target_schema_name != request.target_schema_name:
                raise GatewayContextError("P11 changed target_schema_name")

    async def _repair_once(
        self,
        *,
        target_spec: PromptSpec,
        invalid_output: Any,
        validation_error: GatewaySchemaViolation,
        trusted_context: models.TrustedPromptContext,
    ) -> tuple[BaseModel, tuple[models.ModelCallLedger, ...], tuple[ValidationPhase, ...]]:
        repair_spec = prompt_spec("P11_SCHEMA_REPAIR_V1")
        issues = []
        for error in getattr(validation_error, "validation_errors", ())[:100]:
            location = "/" + "/".join(str(part) for part in error.get("loc", ()))
            issues.append(
                models.SchemaValidationIssue(
                    path=location or "/",
                    error_type=str(error.get("type", "schema_error"))[:200],
                    message=str(error.get("msg", "schema validation failed"))[:1000],
                )
            )
        if not issues:
            issues = [
                models.SchemaValidationIssue(
                    path="/", error_type="schema_error", message="Schema validation failed"
                )
            ]
        repair_request = models.SchemaRepairRequest(
            target_schema_name=target_spec.output_schema_name,
            invalid_output=invalid_output,
            validation_issues=issues,
        )
        order = [ValidationPhase.REQUEST]
        repair_envelope = self._validate_envelope(
            repair_spec, repair_request, trusted_context
        )
        order.append(ValidationPhase.ENVELOPE)
        input_tokens = max(1, len(_canonical_json(repair_request)) // 4)
        repair_resolution = self.resolver.resolve(
            repair_spec,
            required_input_modalities=(models.ModelInputModality.TEXT,),
            required_output_modalities=(models.ModelOutputModality.STRUCTURED_JSON,),
            budget=CallBudget(self.config.default_budget_usd),
            estimated_input_tokens=input_tokens,
        )
        if repair_resolution.status != "RESOLVED" or repair_resolution.route is None:
            raise GatewayRouteBlocked(
                "No approved route for the single structural repair",
                resolution=repair_resolution,
            )
        route = repair_resolution.route
        adapter = self._adapter_for(route)
        started = perf_counter()
        repair_ledgers: list[models.ModelCallLedger] = []
        try:
            result = await asyncio.wait_for(
                adapter.invoke(
                    prompt_id=repair_spec.prompt_id,
                    request=repair_request,
                    envelope=repair_envelope,
                    route=route,
                    attempt=1,
                    behavior=MockBehavior.HAPPY,
                ),
                timeout=self.config.timeout_seconds,
            )
        except TimeoutError as exc:
            ledger = self._ledger(
                spec=repair_spec,
                envelope=repair_envelope,
                route=route,
                attempt=1,
                result="TIMEOUT",
                latency_ms=self._elapsed_ms(started),
                input_tokens=input_tokens,
                output_tokens=0,
                estimated_cost_usd=0.0,
                actual_cost_usd=0.0 if self.config.mode == GatewayMode.MOCK else None,
            )
            self._record(ledger, repair_ledgers)
            raise GatewaySchemaViolation(
                "The single P11 repair attempt timed out",
                phase=ValidationPhase.OUTPUT,
                ledgers=repair_ledgers,
            ) from exc
        try:
            repair_output = self._validate_output(repair_spec, result.raw_output)
        except GatewaySchemaViolation as exc:
            ledger = self._ledger(
                spec=repair_spec,
                envelope=repair_envelope,
                route=route,
                attempt=1,
                result="SCHEMA_INVALID",
                latency_ms=self._elapsed_ms(started),
                input_tokens=result.input_tokens,
                cached_input_tokens=result.cached_input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_usd=result.estimated_cost_usd,
                actual_cost_usd=result.actual_cost_usd,
            )
            self._record(ledger, repair_ledgers)
            raise GatewaySchemaViolation(
                "P11 returned an invalid result; a second repair is forbidden",
                phase=ValidationPhase.OUTPUT,
                ledgers=repair_ledgers,
            ) from exc
        order.append(ValidationPhase.OUTPUT)
        try:
            self._validate_context(
                repair_output,
                trusted_context,
                prompt_id=repair_spec.prompt_id,
                output=True,
            )
        except GatewayContextError as context_error:
            self._record_invalid_output(
                ledgers=repair_ledgers,
                spec=repair_spec,
                envelope=repair_envelope,
                route=route,
                attempt=1,
                started=started,
                result=result,
            )
            raise GatewayContextError(
                "P11 output failed contextual validation",
                ledgers=repair_ledgers,
            ) from context_error
        ledger = self._ledger(
            spec=repair_spec,
            envelope=repair_envelope,
            route=route,
            attempt=1,
            result="SCHEMA_VALID",
            latency_ms=self._elapsed_ms(started),
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            actual_cost_usd=result.actual_cost_usd,
        )
        self._record(ledger, repair_ledgers)
        if repair_output.repair_status != models.RepairStatus.REPAIRED:
            raise GatewaySchemaViolation(
                "P11 declared the output unrepairable",
                phase=ValidationPhase.REPAIRED_OUTPUT,
                ledgers=repair_ledgers,
            )
        repaired = self._revalidate_repair_target(repair_output)
        order.append(ValidationPhase.REPAIRED_OUTPUT)
        assert repaired is not None
        return repaired, tuple(repair_ledgers), tuple(order)

    @staticmethod
    def _revalidate_repair_target(repair_output: BaseModel) -> BaseModel | None:
        if repair_output.repair_status == models.RepairStatus.UNREPAIRABLE:
            return None
        target_model = model_by_name(repair_output.target_schema_name)
        try:
            return target_model.model_validate(repair_output.repaired_output)
        except ValidationError as exc:
            raise GatewaySchemaViolation(
                "P11 repaired_output still violates the target root",
                phase=ValidationPhase.REPAIRED_OUTPUT,
            ) from exc

    def _adapter_for(self, route: models.ModelRoute) -> ModelAdapter:
        if self.config.mode == GatewayMode.MOCK:
            return self.mock_adapter
        try:
            return self.adapters[route.provider]
        except KeyError as exc:
            raise GatewayRouteBlocked("Resolved route has no installed adapter") from exc

    def _ledger(
        self,
        *,
        spec: PromptSpec,
        envelope: models.ModelTaskEnvelope,
        route: models.ModelRoute,
        attempt: int,
        result: str,
        latency_ms: int,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        actual_cost_usd: float | None = None,
    ) -> models.ModelCallLedger:
        input_hash = _hash(envelope)
        created = self.config.clock()
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return models.ModelCallLedger(
            model_call_id=_stable_id(
                "modelcall",
                self.config.job_id,
                spec.prompt_id,
                input_hash,
                attempt,
                result,
            ),
            tenant_id=envelope.trusted_context.tenant_id,
            job_id=self.config.job_id,
            stage=spec.task,
            prompt_id=spec.prompt_id,
            prompt_version=spec.prompt_version,
            prompt_hash=spec.prompt_hash,
            input_bundle_hash=input_hash,
            schema_name=spec.output_schema_name,
            schema_version_used=SCHEMA_VERSION,
            route=route,
            input_tokens=max(0, input_tokens),
            cached_input_tokens=max(0, cached_input_tokens),
            output_tokens=max(0, output_tokens),
            latency_ms=max(0, latency_ms),
            estimated_cost_usd=max(0.0, estimated_cost_usd),
            actual_cost_usd=(
                None if actual_cost_usd is None else max(0.0, actual_cost_usd)
            ),
            result=result,
            attempt=attempt,
            created_at=created,
        )

    def _record(
        self,
        ledger: models.ModelCallLedger,
        collection: list[models.ModelCallLedger],
    ) -> None:
        collection.append(ledger)
        if self.ledger_sink is not None:
            self.ledger_sink(ledger)

    def _record_provider_failure(
        self,
        ledgers: list[models.ModelCallLedger],
        spec: PromptSpec,
        envelope: models.ModelTaskEnvelope,
        route: models.ModelRoute,
        attempt: int,
        started: float,
        result: str,
        input_tokens: int,
        budget: CallBudget,
    ) -> None:
        ledger = self._ledger(
            spec=spec,
            envelope=envelope,
            route=route,
            attempt=attempt,
            result=result,
            latency_ms=self._elapsed_ms(started),
            input_tokens=input_tokens,
            output_tokens=0,
            estimated_cost_usd=budget.estimated_cost_usd,
            actual_cost_usd=0.0 if self.config.mode == GatewayMode.MOCK else None,
        )
        self._record(ledger, ledgers)

    def _record_invalid_output(
        self,
        *,
        ledgers: list[models.ModelCallLedger],
        spec: PromptSpec,
        envelope: models.ModelTaskEnvelope,
        route: models.ModelRoute,
        attempt: int,
        started: float,
        result: AdapterResult,
    ) -> None:
        """Record a structurally or contextually unusable provider output."""

        ledger = self._ledger(
            spec=spec,
            envelope=envelope,
            route=route,
            attempt=attempt,
            result="SCHEMA_INVALID",
            latency_ms=self._elapsed_ms(started),
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            actual_cost_usd=result.actual_cost_usd,
        )
        self._record(ledger, ledgers)

    def _elapsed_ms(self, started: float) -> int:
        if self.config.mode == GatewayMode.MOCK:
            # Wall-clock timings make otherwise identical offline runs differ at
            # the byte level.  A mock call has no provider latency to measure,
            # so keep the canonical ledger value deterministic.
            return 0
        return max(0, int((perf_counter() - started) * 1000))

    async def _backoff(self, attempt: int) -> None:
        """Deterministic exponential backoff for reproducible offline tests."""

        delay = self.config.backoff_base_seconds * (2 ** max(0, attempt - 1))
        if delay:
            await asyncio.sleep(delay)
