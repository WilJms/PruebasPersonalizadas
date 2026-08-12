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
from importlib import metadata as importlib_metadata
import inspect
import json
import re
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from comprehension_verification.contracts import SCHEMA_VERSION, model_by_name, models
from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    DeterministicMockAdapter,
    MockBehavior,
)
from comprehension_verification.model_gateway.registry import (
    PROMPT_CONTRACTS,
    PromptSpec,
    prompt_spec,
)


GATEWAY_CONTEXT_VALIDATOR_VERSION = "gateway-context/2.0.0"
GATEWAY_REPAIR_VALIDATOR_VERSION = "gateway-repair/2.1.0"
# Relationship versions are deliberately prompt-local.  A P04-only invariant
# must not evict reusable P07/P08 outputs whose executable dependencies did not
# change.  Tests assert that these values participate in the fingerprint.
PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS: Mapping[str, str] = {
    "P01_ACTIVITY_SPEC_V1": "relationship-p01/2.0.0",
    "P02_RUBRIC_NORMALIZE_V1": "relationship-p02/2.0.0",
    "P03_AMBIGUITY_TRIAGE_V1": "relationship-p03/2.0.0",
    "P04_BLUEPRINT_BUILD_V1": "relationship-p04/2.0.0",
    "P05_BLUEPRINT_REVIEW_V1": "relationship-p05/2.1.0",
    "P06_EVIDENCE_MAP_V1": "relationship-p06/2.0.0",
    "P07_QUESTION_BUILD_V1": "relationship-p07/2.0.0",
    "P08_QUESTION_REVIEW_V1": "relationship-p08/2.0.0",
    "P09_GUIDE_BUILD_V1": "relationship-p09/2.0.0",
    "P10_ENRICHED_CONTEXT_V1": "relationship-p10/2.0.0",
    "P11_SCHEMA_REPAIR_V1": "relationship-p11/2.0.0",
}


class GatewayMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


class ValidationPhase(StrEnum):
    REQUEST = "request"
    ENVELOPE = "envelope"
    OUTPUT = "output"
    REPAIRED_OUTPUT = "repaired_output"


class ContextFailureCode(StrEnum):
    """Stable, content-free contextual failure classes."""

    CONTEXT_INVARIANT_FAILED = "CONTEXT_INVARIANT_FAILED"
    EVIDENCE_ID_NOT_ALLOWLISTED = "EVIDENCE_ID_NOT_ALLOWLISTED"
    COURSE_SOURCE_ID_NOT_ALLOWLISTED = "COURSE_SOURCE_ID_NOT_ALLOWLISTED"
    CONTEXT_MODE_MISMATCH = "CONTEXT_MODE_MISMATCH"
    REQUIRED_CONTEXT_MODE_MISMATCH = "REQUIRED_CONTEXT_MODE_MISMATCH"
    SYNTHETIC_ATTESTATION_REQUIRED = "SYNTHETIC_ATTESTATION_REQUIRED"
    SYNTHETIC_ATTESTATION_HASH_MISMATCH = "SYNTHETIC_ATTESTATION_HASH_MISMATCH"
    SYNTHETIC_ATTESTATION_ARTIFACT_MISMATCH = (
        "SYNTHETIC_ATTESTATION_ARTIFACT_MISMATCH"
    )
    ABSTENTION_DIAGNOSTIC_MISSING = "ABSTENTION_DIAGNOSTIC_MISSING"
    P01_ABSTENTION_SOURCED_FIELDS_PRESENT = (
        "P01_ABSTENTION_SOURCED_FIELDS_PRESENT"
    )
    P01_ACTIVITY_ID_MISMATCH = "P01_ACTIVITY_ID_MISMATCH"
    P02_RUBRIC_EVIDENCE_ID_NOT_ALLOWLISTED = (
        "P02_RUBRIC_EVIDENCE_ID_NOT_ALLOWLISTED"
    )
    P02_ABSTENTION_CRITERIA_PRESENT = "P02_ABSTENTION_CRITERIA_PRESENT"
    P02_ACTIVITY_ID_MISMATCH = "P02_ACTIVITY_ID_MISMATCH"
    P04_SOURCE_COVERAGE_MISMATCH = "P04_SOURCE_COVERAGE_MISMATCH"
    P04_CATALOG_PLAN_INFEASIBLE = "P04_CATALOG_PLAN_INFEASIBLE"
    P04_NONREADY_WITHOUT_BLOCKING_DIAGNOSTIC = (
        "P04_NONREADY_WITHOUT_BLOCKING_DIAGNOSTIC"
    )
    P05_REFERENCE_MISMATCH = "P05_REFERENCE_MISMATCH"
    P05_REFERENCED_ID_NOT_ALLOWLISTED = (
        "P05_REFERENCED_ID_NOT_ALLOWLISTED"
    )
    P09_GUIDE_ID_MISMATCH = "P09_GUIDE_ID_MISMATCH"
    P09_ASSESSMENT_ID_MISMATCH = "P09_ASSESSMENT_ID_MISMATCH"
    P09_SUBMISSION_ID_MISMATCH = "P09_SUBMISSION_ID_MISMATCH"
    P09_QUESTION_COVERAGE_MISMATCH = "P09_QUESTION_COVERAGE_MISMATCH"
    P09_UNKNOWN_QUESTION_ID = "P09_UNKNOWN_QUESTION_ID"
    P09_QUESTION_EVIDENCE_ID_NOT_ALLOWLISTED = (
        "P09_QUESTION_EVIDENCE_ID_NOT_ALLOWLISTED"
    )
    P09_QUESTION_SOURCE_ID_NOT_ALLOWLISTED = (
        "P09_QUESTION_SOURCE_ID_NOT_ALLOWLISTED"
    )


@dataclass(frozen=True, slots=True)
class ContextFailure:
    """Safe contextual diagnostics without output values or identifiers."""

    phase: ValidationPhase
    codes: tuple[ContextFailureCode, ...]
    validation_engine: str = "GATEWAY_CONTEXT_VALIDATOR"

    def __post_init__(self) -> None:
        if not self.codes:
            raise ValueError("ContextFailure requires at least one safe code")

    @property
    def code(self) -> ContextFailureCode:
        """Primary stable code, preserving the validator's check order."""

        return self.codes[0]


@dataclass(frozen=True, slots=True)
class SafeValidationIssue:
    """Content-free structural failure metadata safe for reports and logs."""

    error_type: str
    path: str


@dataclass(frozen=True, slots=True)
class PrimaryOutputFailure:
    """The primary output failure, separate from any later repair disposition."""

    phase: ValidationPhase
    code: str
    validation_engine: str
    issues: tuple[SafeValidationIssue, ...]
    provider_schema_valid: bool | None = None
    provider_schema_issues: tuple[SafeValidationIssue, ...] = ()


_MAX_SAFE_VALIDATION_ISSUES = 32
_SAFE_VALIDATION_ERROR_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")


def _canonical_property_names(model: type[BaseModel]) -> frozenset[str]:
    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                walk(child)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(str(name) for name in properties)
        for child in value.values():
            walk(child)

    walk(model.model_json_schema(mode="validation"))
    return frozenset(names)


def _safe_validation_path(
    parts: Sequence[Any], *, allowed_names: frozenset[str]
) -> str:
    safe_parts: list[str] = []
    for part in parts:
        if isinstance(part, int) and 0 <= part <= 9_999:
            safe_parts.append(str(part))
        elif isinstance(part, str) and part in allowed_names:
            safe_parts.append(part.replace("~", "~0").replace("/", "~1"))
        else:
            safe_parts.append("*")
    return "/" + "/".join(safe_parts) if safe_parts else "/"


def _safe_pydantic_issues(
    error: ValidationError, model: type[BaseModel]
) -> tuple[SafeValidationIssue, ...]:
    allowed_names = _canonical_property_names(model)
    issues: list[SafeValidationIssue] = []
    for item in error.errors(include_url=False, include_input=False, include_context=False):
        raw_type = str(item.get("type", "validation_error"))
        error_type = (
            raw_type
            if _SAFE_VALIDATION_ERROR_TYPE.fullmatch(raw_type)
            else "validation_error"
        )
        issue = SafeValidationIssue(
            error_type=error_type,
            path=_safe_validation_path(
                tuple(item.get("loc", ())), allowed_names=allowed_names
            ),
        )
        if issue not in issues:
            issues.append(issue)
        if len(issues) >= _MAX_SAFE_VALIDATION_ISSUES:
            break
    return tuple(issues)


def _primary_failure_with_provider_schema(
    failure: PrimaryOutputFailure, result: AdapterResult
) -> PrimaryOutputFailure:
    provider_issues = tuple(
        SafeValidationIssue(error_type=error_type, path=path)
        for error_type, path in result.provider_schema_issues[
            :_MAX_SAFE_VALIDATION_ISSUES
        ]
        if _SAFE_VALIDATION_ERROR_TYPE.fullmatch(error_type)
        and re.fullmatch(r"/(?:[A-Za-z0-9_*.-]+/)*[A-Za-z0-9_*.-]*", path)
    )
    return PrimaryOutputFailure(
        phase=failure.phase,
        code=failure.code,
        validation_engine=failure.validation_engine,
        issues=failure.issues,
        provider_schema_valid=result.provider_schema_valid,
        provider_schema_issues=provider_issues,
    )


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
        resolution: models.ModelRouteResolution | None = None,
    ) -> None:
        super().__init__(message, ledgers=ledgers, resolution=resolution)
        self.phase = phase


class GatewayContextError(GatewayError):
    code = "MODEL_CONTEXT_NOT_ALLOWLISTED"

    def __init__(
        self,
        message: str,
        *,
        phase: ValidationPhase = ValidationPhase.OUTPUT,
        failure_code: ContextFailureCode = (
            ContextFailureCode.CONTEXT_INVARIANT_FAILED
        ),
        failure: ContextFailure | None = None,
        ledgers: Sequence[models.ModelCallLedger] = (),
        resolution: models.ModelRouteResolution | None = None,
    ) -> None:
        super().__init__(message, ledgers=ledgers, resolution=resolution)
        self.failure = failure or ContextFailure(
            phase=phase,
            codes=(failure_code,),
        )


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
    """Canonical output validation failed before contextual validation."""

    code = "MODEL_OUTPUT_VALIDATION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        phase: ValidationPhase,
        ledgers: Sequence[models.ModelCallLedger] = (),
        resolution: models.ModelRouteResolution | None = None,
        primary_failure: PrimaryOutputFailure | None = None,
        repair_disposition: str | None = None,
    ) -> None:
        super().__init__(
            message,
            phase=phase,
            ledgers=ledgers,
            resolution=resolution,
        )
        self.primary_failure = primary_failure
        self.repair_disposition = repair_disposition


class ProviderAdapterError(RuntimeError):
    """Sanitized adapter failure metadata safe for canonical ledger reason codes."""

    default_reason_code = "PROVIDER_ERROR"

    def __init__(
        self,
        reason_code: str | None = None,
        *,
        request_id_hash: str | None = None,
    ) -> None:
        candidate = reason_code or self.default_reason_code
        self.reason_code = (
            candidate
            if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", candidate)
            else self.default_reason_code
        )
        self.request_id_hash = request_id_hash
        super().__init__(self.reason_code)


class TransientProviderError(ProviderAdapterError):
    """An adapter may raise this to request governed transient retry."""

    default_reason_code = "PROVIDER_TRANSIENT"


class RateLimitProviderError(TransientProviderError):
    """Transient provider rate limit, recorded separately in the ledger."""

    default_reason_code = "PROVIDER_RATE_LIMIT"


class ProviderTimeoutError(TransientProviderError):
    """Provider/SDK timeout governed by the same bounded gateway retry policy."""

    default_reason_code = "PROVIDER_TIMEOUT"


class PermanentProviderError(ProviderAdapterError):
    """Non-retryable provider failure."""

    default_reason_code = "PROVIDER_PERMANENT"


class AuthenticationProviderError(PermanentProviderError):
    default_reason_code = "PROVIDER_AUTHENTICATION"


class AuthorizationProviderError(PermanentProviderError):
    default_reason_code = "PROVIDER_AUTHORIZATION"


class ModelUnavailableProviderError(PermanentProviderError):
    default_reason_code = "PROVIDER_MODEL_UNAVAILABLE"


class ProviderBudgetError(PermanentProviderError):
    default_reason_code = "PROVIDER_BUDGET_OR_QUOTA"


class MalformedProviderResponseError(PermanentProviderError):
    default_reason_code = "PROVIDER_MALFORMED_RESPONSE"


class SafetyBlockProviderError(ProviderAdapterError):
    """Provider safety refusal; the gateway never retries to evade it."""

    default_reason_code = "PROVIDER_SAFETY_REFUSAL"


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
            input_modalities=[models.ModelInputModality.TEXT],
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
        cost_estimator: Callable[[PromptSpec, int], float] | None = None,
        input_token_estimator: (
            Callable[[PromptSpec, BaseModel, models.ModelTaskEnvelope], int] | None
        ) = None,
    ) -> None:
        self.config = config or GatewayConfig()
        self.adapters = dict(adapters or {})
        self.mock_adapter = mock_adapter or DeterministicMockAdapter()
        self.ledger_sink = ledger_sink
        self.cost_estimator = cost_estimator
        self.input_token_estimator = input_token_estimator
        self.resolver = ModelRouteResolver(
            mode=self.config.mode,
            real_routes=real_routes,
            available_providers=tuple(self.adapters),
        )

    @staticmethod
    def _implementation_hash(value: Any) -> str:
        try:
            source = inspect.getsource(value)
        except (OSError, TypeError):
            source = f"{getattr(value, '__module__', '')}:{getattr(value, '__qualname__', repr(value))}"
        return _hash(source)

    def execution_fingerprint(
        self,
        prompt_id: str,
        *,
        application_validator_hash: str | None = None,
    ) -> str:
        """Fingerprint every executable dependency relevant to stage reuse."""

        spec = prompt_spec(prompt_id)
        input_model = model_by_name(spec.input_schema_name)
        output_model = model_by_name(spec.output_schema_name)
        route = (
            _mock_route(spec)
            if self.config.mode == GatewayMode.MOCK
            else self.resolver.real_routes.get(prompt_id)
        )
        repair_spec = prompt_spec("P11_SCHEMA_REPAIR_V1")
        repair_route = (
            _mock_route(repair_spec)
            if self.config.mode == GatewayMode.MOCK
            else self.resolver.real_routes.get("P11_SCHEMA_REPAIR_V1")
        )
        if self.config.mode == GatewayMode.MOCK:
            adapter: Any = self.mock_adapter
        elif route is not None:
            adapter = self.adapters.get(route.provider)
        else:
            adapter = None
        try:
            openai_sdk_version = importlib_metadata.version("openai")
        except importlib_metadata.PackageNotFoundError:
            openai_sdk_version = None
        adapter_material: dict[str, Any] | None = None
        if adapter is not None:
            adapter_material = {
                "class": (
                    f"{type(adapter).__module__}.{type(adapter).__qualname__}"
                ),
                "implementation_hash": self._implementation_hash(type(adapter)),
            }
            factory = getattr(adapter, "factory", None)
            if factory is not None:
                adapter_material["factory_class"] = (
                    f"{type(factory).__module__}.{type(factory).__qualname__}"
                )
                adapter_material["factory_implementation_hash"] = (
                    self._implementation_hash(type(factory))
                )
        material = {
            "fingerprint_format": "model-stage-execution/2.0.0",
            "mode": self.config.mode.value,
            "prompt_id": prompt_id,
            "prompt_hash": spec.prompt_hash,
            "input_schema_hash": _hash(
                input_model.model_json_schema(mode="validation")
            ),
            "output_schema_hash": _hash(
                output_model.model_json_schema(mode="validation")
            ),
            "context_validator": GATEWAY_CONTEXT_VALIDATOR_VERSION,
            "context_implementation_hash": self._implementation_hash(
                ModelGateway._validate_context
            ),
            "relationship_validator": (
                PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS[prompt_id]
            ),
            "repair_validator": GATEWAY_REPAIR_VALIDATOR_VERSION,
            "repair_prompt_hash": (
                prompt_spec("P11_SCHEMA_REPAIR_V1").prompt_hash
                if prompt_id != "P11_SCHEMA_REPAIR_V1"
                else None
            ),
            "repair_input_schema_hash": (
                _hash(
                    model_by_name("SchemaRepairRequest").model_json_schema(
                        mode="validation"
                    )
                )
                if prompt_id != "P11_SCHEMA_REPAIR_V1"
                else None
            ),
            "repair_output_schema_hash": (
                _hash(
                    model_by_name("SchemaRepairResult").model_json_schema(
                        mode="validation"
                    )
                )
                if prompt_id != "P11_SCHEMA_REPAIR_V1"
                else None
            ),
            "repair_relationship_validator": (
                PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS[
                    "P11_SCHEMA_REPAIR_V1"
                ]
                if prompt_id != "P11_SCHEMA_REPAIR_V1"
                else None
            ),
            "route": (
                route.model_dump(mode="json") if route is not None else None
            ),
            "repair_route": (
                repair_route.model_dump(mode="json")
                if prompt_id != "P11_SCHEMA_REPAIR_V1"
                and repair_route is not None
                else None
            ),
            "adapter": adapter_material,
            "openai_sdk_version": (
                openai_sdk_version
                if self.config.mode == GatewayMode.REAL
                else None
            ),
            "application_validator_hash": application_validator_hash,
        }
        return f"model-stage-execution/2:{_hash(material).removeprefix('sha256:')}"

    def validate_cached_output(
        self,
        prompt_id: str,
        payload: BaseModel | Mapping[str, Any],
        trusted_context: models.TrustedPromptContext | Mapping[str, Any],
        raw_output: Any,
    ) -> BaseModel:
        """Apply the current request, envelope, context and relationship gates.

        Cache hits deliberately skip transport and ledger creation, but never
        skip any deterministic acceptance boundary that a fresh output faces.
        """

        spec = prompt_spec(prompt_id)
        request = self._validate_request(spec, payload)
        envelope = self._validate_envelope(spec, request, trusted_context)
        self._validate_context(
            request, envelope.trusted_context, prompt_id=prompt_id
        )
        if self.config.mode == GatewayMode.REAL:
            self._validate_real_input_attestation(
                request, envelope.trusted_context
            )
        output = self._validate_output(spec, raw_output)
        self._validate_context(
            output,
            envelope.trusted_context,
            prompt_id=prompt_id,
            output=True,
            phase=ValidationPhase.OUTPUT,
            request=request,
        )
        self._validate_output_relationship(
            prompt_id,
            request,
            output,
            phase=ValidationPhase.OUTPUT,
        )
        if prompt_id == "P11_SCHEMA_REPAIR_V1":
            self._revalidate_repair_target(output)
        return output

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
        if self.config.mode == GatewayMode.REAL:
            self._validate_real_input_attestation(request, envelope.trusted_context)

        encoded_request = _canonical_json(request)
        input_token_estimate = (
            self.input_token_estimator(spec, request, envelope)
            if self.config.mode == GatewayMode.REAL
            and self.input_token_estimator is not None
            else max(1, len(encoded_request) // 4)
        )
        attempt_estimated_cost = (
            self.cost_estimator(spec, input_token_estimate)
            if self.config.mode == GatewayMode.REAL and self.cost_estimator is not None
            else 0.0
        )
        retry_limit = min(self.config.max_retries, spec.max_transient_retries)
        authorization_estimated_cost = attempt_estimated_cost * (retry_limit + 1)
        if budget is None:
            call_budget = CallBudget(
                self.config.default_budget_usd,
                estimated_cost_usd=authorization_estimated_cost,
            )
        else:
            call_budget = CallBudget(
                budget.max_cost_usd,
                estimated_cost_usd=max(
                    budget.estimated_cost_usd, authorization_estimated_cost
                ),
            )
        attempt_budget = CallBudget(
            call_budget.max_cost_usd,
            estimated_cost_usd=attempt_estimated_cost,
        )
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
            except (TimeoutError, ProviderTimeoutError) as exc:
                ledger = self._ledger(
                    spec=spec,
                    envelope=envelope,
                    route=route,
                    attempt=attempt,
                    result="TIMEOUT",
                    latency_ms=self._elapsed_ms(started),
                    input_tokens=input_token_estimate,
                    output_tokens=0,
                    estimated_cost_usd=attempt_estimated_cost,
                    actual_cost_usd=0.0 if self.config.mode == GatewayMode.MOCK else None,
                    reason_codes=self._error_reason_codes(exc),
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
                    attempt_budget,
                    error=exc,
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
                    attempt_budget,
                    error=exc,
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
                    attempt_budget,
                    error=exc,
                )
                raise GatewaySafetyBlock(
                    "Provider returned a safety block; no evasion retry is allowed",
                    ledgers=ledgers,
                ) from exc
            except ProviderBudgetError as exc:
                self._record_provider_failure(
                    ledgers,
                    spec,
                    envelope,
                    route,
                    attempt,
                    started,
                    "PROVIDER_ERROR",
                    input_token_estimate,
                    attempt_budget,
                    error=exc,
                )
                raise GatewayBudgetExceeded(
                    "Provider project budget or quota blocked the call",
                    ledgers=ledgers,
                    resolution=resolution,
                ) from exc
            except PermanentProviderError as exc:
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
                    attempt_budget,
                    error=exc,
                )
                raise GatewayProviderError(
                    "Non-retryable model adapter failure", ledgers=ledgers
                ) from exc
            except Exception as exc:
                self._record_provider_failure(
                    ledgers,
                    spec,
                    envelope,
                    route,
                    attempt,
                    started,
                    "PROVIDER_ERROR",
                    input_token_estimate,
                    attempt_budget,
                    reason_codes=("ADAPTER_UNEXPECTED_EXCEPTION",),
                )
                raise GatewayProviderError(
                    "Unexpected non-retryable model adapter failure", ledgers=ledgers
                ) from exc

            try:
                output = self._validate_output(spec, adapter_result.raw_output)
            except GatewaySchemaViolation as exc:
                validation_order.append(ValidationPhase.OUTPUT)
                primary_failure = exc.primary_failure or PrimaryOutputFailure(
                    phase=ValidationPhase.OUTPUT,
                    code="OUTPUT_PYDANTIC_VALIDATION_FAILED",
                    validation_engine="PYDANTIC_MODEL_VALIDATE",
                    issues=(),
                )
                primary_failure = _primary_failure_with_provider_schema(
                    primary_failure, adapter_result
                )
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
                    adapter_result=adapter_result,
                    reason_codes=(primary_failure.code,),
                )
                self._record(invalid_ledger, ledgers)
                if prompt_id == "P11_SCHEMA_REPAIR_V1":
                    raise GatewaySchemaViolation(
                        "P11 output was invalid; recursive repair is forbidden",
                        phase=ValidationPhase.OUTPUT,
                        ledgers=ledgers,
                        primary_failure=primary_failure,
                        repair_disposition="RECURSIVE_REPAIR_FORBIDDEN",
                    ) from exc
                if not self._is_structural_repair_eligible(
                    primary_failure.issues
                ):
                    raise GatewaySchemaViolation(
                        "Primary output is not eligible for structural repair",
                        phase=ValidationPhase.OUTPUT,
                        ledgers=ledgers,
                        primary_failure=primary_failure,
                        repair_disposition="NOT_STRUCTURALLY_REPAIRABLE",
                    ) from exc
                try:
                    repaired, repair_ledgers, repair_order = await self._repair_once(
                        target_spec=spec,
                        invalid_output=adapter_result.raw_output,
                        validation_issues=primary_failure.issues,
                        trusted_context=envelope.trusted_context,
                        max_cost_usd=max(
                            0.0,
                            call_budget.max_cost_usd
                            - sum(
                                self._ledger_budget_charge(item) for item in ledgers
                            ),
                        ),
                    )
                except GatewayError as repair_error:
                    if isinstance(repair_error, GatewayBudgetExceeded):
                        repair_disposition = "BLOCKED_BY_BUDGET"
                    elif isinstance(repair_error, GatewayRouteBlocked):
                        repair_disposition = "BLOCKED_BY_ROUTE_POLICY"
                    elif isinstance(repair_error, GatewayTimeout):
                        repair_disposition = "FAILED_TIMEOUT"
                    elif isinstance(repair_error, GatewaySafetyBlock):
                        repair_disposition = "FAILED_SAFETY_BLOCK"
                    elif isinstance(repair_error, GatewayProviderError):
                        repair_disposition = "FAILED_PROVIDER"
                    elif isinstance(repair_error, GatewayContextError):
                        repair_disposition = "FAILED_CONTEXT_VALIDATION"
                    elif isinstance(repair_error, GatewaySchemaViolation):
                        repair_disposition = (
                            repair_error.repair_disposition
                            or "FAILED_OUTPUT_VALIDATION"
                        )
                    else:
                        repair_disposition = "FAILED_GATEWAY"
                    raise GatewaySchemaViolation(
                        "Primary output validation failed and repair did not complete",
                        phase=ValidationPhase.OUTPUT,
                        ledgers=(*ledgers, *repair_error.ledgers),
                        resolution=repair_error.resolution,
                        primary_failure=primary_failure,
                        repair_disposition=repair_disposition,
                    ) from repair_error
                ledgers.extend(repair_ledgers)
                validation_order.append(ValidationPhase.REPAIRED_OUTPUT)
                try:
                    self._validate_context(
                        repaired,
                        envelope.trusted_context,
                        prompt_id=prompt_id,
                        output=True,
                        phase=ValidationPhase.REPAIRED_OUTPUT,
                        request=request,
                    )
                    self._validate_output_relationship(
                        prompt_id,
                        request,
                        repaired,
                        phase=ValidationPhase.REPAIRED_OUTPUT,
                    )
                except GatewayContextError as context_error:
                    raise GatewayContextError(
                        "Repaired output failed contextual validation",
                        failure=context_error.failure,
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
                    output,
                    envelope.trusted_context,
                    prompt_id=prompt_id,
                    output=True,
                    phase=ValidationPhase.OUTPUT,
                    request=request,
                )
                self._validate_output_relationship(
                    prompt_id,
                    request,
                    output,
                    phase=ValidationPhase.OUTPUT,
                )
            except GatewayContextError as context_error:
                self._record_invalid_output(
                    ledgers=ledgers,
                    spec=spec,
                    envelope=envelope,
                    route=route,
                    attempt=attempt,
                    started=started,
                    result=adapter_result,
                    failure=context_error.failure,
                )
                raise GatewayContextError(
                    "Model output failed contextual validation",
                    failure=context_error.failure,
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
                adapter_result=adapter_result,
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
            request = request_model.model_validate(raw)
        except ValidationError as exc:
            raise GatewayValidationError(
                "Request root validation failed", phase=ValidationPhase.REQUEST
            ) from exc
        if spec.prompt_id == "P11_SCHEMA_REPAIR_V1":
            repairable_roots = {
                output_root
                for prompt_id, (_input_root, output_root) in PROMPT_CONTRACTS.items()
                if prompt_id not in {
                    "P10_ENRICHED_CONTEXT_V1",
                    "P11_SCHEMA_REPAIR_V1",
                }
            }
            if request.target_schema_name not in repairable_roots:
                raise GatewayValidationError(
                    "P11 target is not an approved P01-P09 output root",
                    phase=ValidationPhase.REQUEST,
                )
        return request

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
            primary_failure = PrimaryOutputFailure(
                phase=ValidationPhase.OUTPUT,
                code="OUTPUT_PYDANTIC_VALIDATION_FAILED",
                validation_engine="PYDANTIC_MODEL_VALIDATE",
                issues=_safe_pydantic_issues(exc, output_model),
            )
        # Raise outside the ``except`` block so the Pydantic exception (which
        # retains invalid input internally) is not attached to the safe error.
        raise GatewaySchemaViolation(
            "Canonical output model validation failed",
            phase=ValidationPhase.OUTPUT,
            primary_failure=primary_failure,
        )

    @staticmethod
    def _validate_real_input_attestation(
        request: BaseModel,
        trusted: models.TrustedPromptContext,
    ) -> None:
        if (
            trusted.data_classification != "SYNTHETIC_ONLY_NO_STUDENT_DATA"
            or trusted.attestation_id is None
            or trusted.attested_input_hash is None
        ):
            raise GatewayContextError(
                "Real provider calls require a server-issued synthetic-data attestation",
                phase=ValidationPhase.REQUEST,
                failure_code=ContextFailureCode.SYNTHETIC_ATTESTATION_REQUIRED,
            )
        if trusted.attested_input_hash != _hash(request):
            raise GatewayContextError(
                "The synthetic-data attestation is not bound to this exact request",
                phase=ValidationPhase.REQUEST,
                failure_code=ContextFailureCode.SYNTHETIC_ATTESTATION_HASH_MISMATCH,
            )
        request_artifact_hashes = ModelGateway._collect_artifact_hashes(
            request.model_dump(mode="json")
        )
        if not request_artifact_hashes.issubset(
            set(trusted.attested_artifact_hashes)
        ):
            raise GatewayContextError(
                "The synthetic-data attestation does not cover every input artifact",
                phase=ValidationPhase.REQUEST,
                failure_code=(
                    ContextFailureCode.SYNTHETIC_ATTESTATION_ARTIFACT_MISMATCH
                ),
            )

    def _validate_context(
        self,
        value: BaseModel,
        trusted: models.TrustedPromptContext,
        *,
        prompt_id: str,
        output: bool = False,
        phase: ValidationPhase | None = None,
        request: BaseModel | None = None,
    ) -> None:
        context_phase = phase or (
            ValidationPhase.OUTPUT if output else ValidationPhase.REQUEST
        )
        data = value.model_dump(mode="json")
        evidence_ids, source_ids = self._collect_authorized_ids(data)
        evidence_invalid = not evidence_ids.issubset(
            set(trusted.allowed_evidence_ids)
        )
        source_invalid = not source_ids.issubset(
            set(trusted.allowed_course_source_ids)
        )
        modes = {
            item.get("context_mode")
            for item in self._walk_dicts(data)
            if item.get("context_mode") is not None
        }
        context_mode_invalid = bool(modes) and any(
            mode != trusted.context_mode.value for mode in modes
        )
        tenant_ids = {
            item["tenant_id"]
            for item in self._walk_dicts(data)
            if isinstance(item.get("tenant_id"), str)
        }
        activity_ids = {
            item["activity_id"]
            for item in self._walk_dicts(data)
            if isinstance(item.get("activity_id"), str)
        }
        submission_ids = {
            item["submission_id"]
            for item in self._walk_dicts(data)
            if isinstance(item.get("submission_id"), str)
        }
        blueprint_ids = {
            item["blueprint_id"]
            for item in self._walk_dicts(data)
            if isinstance(item.get("blueprint_id"), str)
        }
        blueprint_versions = {
            item["blueprint_version"]
            for item in self._walk_dicts(data)
            if isinstance(item.get("blueprint_version"), int)
        }
        output_languages = {
            item["output_language"]
            for item in self._walk_dicts(data)
            if isinstance(item.get("output_language"), str)
        }
        tenant_scope_invalid = bool(tenant_ids - {trusted.tenant_id})
        activity_scope_invalid = bool(activity_ids - {trusted.activity_id})
        submission_scope_invalid = bool(
            submission_ids
            - (
                {trusted.submission_id}
                if trusted.submission_id is not None
                else set()
            )
        )
        blueprint_scope_invalid = bool(
            blueprint_ids
            - (
                {trusted.blueprint_id}
                if trusted.blueprint_id is not None
                else set()
            )
            or blueprint_versions
            - (
                {trusted.blueprint_version}
                if trusted.blueprint_version is not None
                else set()
            )
        )
        # Root identities with dedicated prompt-specific failure codes are
        # validated by the relationship phase below. Masking them here keeps
        # observability precise while tenant and nested scope remain generic.
        if output and prompt_id in {"P01_ACTIVITY_SPEC_V1", "P02_RUBRIC_NORMALIZE_V1"}:
            activity_scope_invalid = False
        if output and prompt_id in {"P04_BLUEPRINT_BUILD_V1", "P05_BLUEPRINT_REVIEW_V1"}:
            activity_scope_invalid = False
            blueprint_scope_invalid = False
        if output and prompt_id in {
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P08_QUESTION_REVIEW_V1",
            "P09_GUIDE_BUILD_V1",
            "P10_ENRICHED_CONTEXT_V1",
        }:
            submission_scope_invalid = False
        scope_invalid = bool(
            tenant_scope_invalid
            or activity_scope_invalid
            or submission_scope_invalid
            or blueprint_scope_invalid
            or output_languages - {trusted.output_language}
        )

        if (
            output
            and prompt_id == "P01_ACTIVITY_SPEC_V1"
            and request is not None
        ):
            codes: list[ContextFailureCode] = []
            if evidence_invalid:
                codes.append(ContextFailureCode.EVIDENCE_ID_NOT_ALLOWLISTED)
            if source_invalid:
                codes.append(
                    ContextFailureCode.COURSE_SOURCE_ID_NOT_ALLOWLISTED
                )
            if context_mode_invalid:
                codes.append(ContextFailureCode.CONTEXT_MODE_MISMATCH)
            if value.status != models.WorkflowStatus.READY:
                if not value.diagnostics:
                    codes.append(
                        ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING
                    )
                if any(
                    (
                        value.learning_outcomes,
                        value.expected_products,
                        value.requirements,
                        value.allowed_materials,
                        value.prohibited_materials,
                    )
                ):
                    codes.append(
                        ContextFailureCode.P01_ABSTENTION_SOURCED_FIELDS_PRESENT
                    )
            if value.activity_id != request.activity_config.activity_id:
                codes.append(ContextFailureCode.P01_ACTIVITY_ID_MISMATCH)
            if codes:
                raise GatewayContextError(
                    "P01 output failed contextual validation",
                    failure=ContextFailure(
                        phase=context_phase,
                        codes=tuple(codes),
                    ),
                )
            return

        if (
            output
            and prompt_id == "P02_RUBRIC_NORMALIZE_V1"
            and request is not None
        ):
            codes: list[ContextFailureCode] = []
            if evidence_invalid:
                codes.append(ContextFailureCode.EVIDENCE_ID_NOT_ALLOWLISTED)
            if source_invalid:
                codes.append(
                    ContextFailureCode.COURSE_SOURCE_ID_NOT_ALLOWLISTED
                )
            if context_mode_invalid:
                codes.append(ContextFailureCode.CONTEXT_MODE_MISMATCH)
            rubric_evidence_ids = {
                item.evidence_id for item in request.rubric_evidence
            }
            if not evidence_ids.issubset(rubric_evidence_ids):
                codes.append(
                    ContextFailureCode.P02_RUBRIC_EVIDENCE_ID_NOT_ALLOWLISTED
                )
            if value.status != models.WorkflowStatus.READY:
                if not value.diagnostics:
                    codes.append(
                        ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING
                    )
                if value.criteria:
                    codes.append(
                        ContextFailureCode.P02_ABSTENTION_CRITERIA_PRESENT
                    )
            if value.activity_id != request.activity_spec.activity_id:
                codes.append(ContextFailureCode.P02_ACTIVITY_ID_MISMATCH)
            if codes:
                raise GatewayContextError(
                    "P02 output failed contextual validation",
                    failure=ContextFailure(
                        phase=context_phase,
                        codes=tuple(codes),
                    ),
                )
            return

        if evidence_invalid:
            raise GatewayContextError(
                "Payload contains an evidence_id outside the allowlist",
                phase=context_phase,
                failure_code=ContextFailureCode.EVIDENCE_ID_NOT_ALLOWLISTED,
            )
        if source_invalid:
            raise GatewayContextError(
                "Payload contains a source_id outside the allowlist",
                phase=context_phase,
                failure_code=(
                    ContextFailureCode.COURSE_SOURCE_ID_NOT_ALLOWLISTED
                ),
            )

        if context_mode_invalid:
            raise GatewayContextError(
                "Context mode differs from the trusted envelope",
                phase=context_phase,
                failure_code=ContextFailureCode.CONTEXT_MODE_MISMATCH,
            )
        if scope_invalid:
            raise GatewayContextError(
                "Payload identity or output language differs from the trusted scope",
                phase=context_phase,
                failure_code=ContextFailureCode.CONTEXT_INVARIANT_FAILED,
            )
        if prompt_id == "P07_QUESTION_BUILD_V1" and trusted.context_mode != models.ContextMode.CLOSED:
            raise GatewayContextError(
                "P07 requires CLOSED context",
                phase=context_phase,
                failure_code=ContextFailureCode.REQUIRED_CONTEXT_MODE_MISMATCH,
            )
        if prompt_id == "P10_ENRICHED_CONTEXT_V1" and trusted.context_mode != models.ContextMode.COURSE_ENRICHED:
            raise GatewayContextError(
                "P10 requires COURSE_ENRICHED context",
                phase=context_phase,
                failure_code=ContextFailureCode.REQUIRED_CONTEXT_MODE_MISMATCH,
            )

        if output:
            self._validate_clean_abstention(
                prompt_id,
                value,
                phase=context_phase,
            )
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

    @classmethod
    def _collect_reference_ids(cls, data: Any) -> set[str]:
        references: set[str] = set()
        for item in cls._walk_dicts(data):
            for key, value in item.items():
                if key.endswith("_id") and isinstance(value, str):
                    references.add(value)
                elif key.endswith("_ids") and isinstance(value, list):
                    references.update(
                        child for child in value if isinstance(child, str)
                    )
        return references

    @classmethod
    def _collect_artifact_hashes(cls, data: Any) -> set[str]:
        hashes: set[str] = set()
        for item in cls._walk_dicts(data):
            for key in ("artifact_hash", "sha256"):
                value = item.get(key)
                if (
                    isinstance(value, str)
                    and re.fullmatch(r"sha256:[a-f0-9]{64}", value)
                ):
                    hashes.add(value)
        return hashes

    @staticmethod
    def _validate_clean_abstention(
        prompt_id: str,
        output: BaseModel,
        *,
        phase: ValidationPhase = ValidationPhase.OUTPUT,
    ) -> None:
        def require_diagnostic() -> None:
            if not getattr(output, "diagnostics", None):
                raise GatewayContextError(
                    "Abstention requires a complete diagnostic",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING
                    ),
                )

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
                raise GatewayContextError(
                    "P01 abstention cannot fabricate sourced fields",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.P01_ABSTENTION_SOURCED_FIELDS_PRESENT
                    ),
                )
        elif (
            prompt_id == "P02_RUBRIC_NORMALIZE_V1"
            and output.status != models.WorkflowStatus.READY
        ):
            require_diagnostic()
            if output.criteria:
                raise GatewayContextError(
                    "P02 abstention cannot fabricate criteria",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.P02_ABSTENTION_CRITERIA_PRESENT
                    ),
                )
        elif prompt_id == "P03_AMBIGUITY_TRIAGE_V1" and output.blocked and not output.issues:
            raise GatewayContextError("Blocked P03 output requires an actionable issue")
        elif prompt_id == "P04_BLUEPRINT_BUILD_V1":
            if output.approved_by is not None or output.approved_at is not None:
                raise GatewayContextError(
                    "P04 cannot fabricate server-side human approval metadata"
                )
            if output.status != models.WorkflowStatus.READY:
                require_diagnostic()
                if not any(
                    diagnostic.severity
                    in {models.Severity.ERROR, models.Severity.CRITICAL}
                    for diagnostic in output.diagnostics
                ):
                    raise GatewayContextError(
                        "Non-ready P04 requires a blocking diagnostic",
                        phase=phase,
                        failure_code=(
                            ContextFailureCode.P04_NONREADY_WITHOUT_BLOCKING_DIAGNOSTIC
                        ),
                    )
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
        prompt_id: str,
        request: BaseModel,
        output: BaseModel,
        *,
        phase: ValidationPhase = ValidationPhase.OUTPUT,
    ) -> None:
        """Check cross-root relationships that JSON Schema cannot express."""

        if prompt_id == "P01_ACTIVITY_SPEC_V1":
            if output.activity_id != request.activity_config.activity_id:
                raise GatewayContextError(
                    "P01 output activity_id mismatch",
                    phase=phase,
                    failure_code=ContextFailureCode.P01_ACTIVITY_ID_MISMATCH,
                )
        elif prompt_id == "P02_RUBRIC_NORMALIZE_V1":
            if output.activity_id != request.activity_spec.activity_id:
                raise GatewayContextError(
                    "P02 output activity_id mismatch",
                    phase=phase,
                    failure_code=ContextFailureCode.P02_ACTIVITY_ID_MISMATCH,
                )
        elif prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
            if output.activity_id != request.activity_spec.activity_id:
                raise GatewayContextError("P03 output activity_id mismatch")
        elif prompt_id == "P04_BLUEPRINT_BUILD_V1":
            if (
                output.activity_id != request.activity_spec.activity_id
                or output.blueprint_id != request.target_blueprint_id
                or output.blueprint_version != request.target_blueprint_version
            ):
                raise GatewayContextError("P04 output activity_id mismatch")
            constraints = output.assessment_constraints
            policy = request.blueprint_policy
            if (
                constraints.question_count != policy.question_count
                or constraints.target_total_minutes != policy.target_total_minutes
                or set(constraints.allowed_response_formats)
                != set(policy.allowed_response_formats)
                or constraints.minimum_opportunity_quality
                != policy.planning_policy.minimum_opportunity_quality
                or constraints.max_reserve_opportunities
                != policy.planning_policy.max_reserve_opportunities
                or set(constraints.priority_criterion_ids)
                != set(policy.priority_criterion_ids)
                or set(constraints.required_criterion_ids)
                != set(policy.required_criterion_ids)
                or constraints.structured_justification_policy
                != policy.structured_justification_policy
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
            blueprint_learning_outcome_ids: set[str] = set()
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
                blueprint_learning_outcome_ids.update(
                    dimension.learning_outcome_ids
                )
            verifiable_criterion_ids = (
                {
                    item.criterion_id
                    for item in request.rubric_spec.criteria
                    if item.verification_fit != "NOT_VERIFIABLE"
                }
                if request.rubric_spec is not None
                else set()
            )
            if (
                not verifiable_criterion_ids.issubset(
                    blueprint_criterion_ids
                )
                or not learning_outcome_ids.issubset(
                    blueprint_learning_outcome_ids
                )
            ):
                raise GatewayContextError(
                    "P04 output omitted source-bound conceptual coverage",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.P04_SOURCE_COVERAGE_MISMATCH
                    ),
                )
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
            eligible_minutes = sorted(
                opportunity.target_minutes
                for dimension in output.dimensions
                for variant in dimension.evidence_variants
                for opportunity in variant.question_opportunities
                if opportunity.minimum_quality
                >= constraints.minimum_opportunity_quality
            )
            if (
                len(eligible_minutes) < constraints.question_count
                or sum(eligible_minutes[: constraints.question_count])
                > constraints.target_total_minutes
            ):
                raise GatewayContextError(
                    "P04 catalog cannot form an exact-N plan within trusted limits",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.P04_CATALOG_PLAN_INFEASIBLE
                    ),
                )
            templates = [
                opportunity
                for dimension in output.dimensions
                for variant in dimension.evidence_variants
                for opportunity in variant.question_opportunities
            ]
            required_templates = {
                template.opportunity_template_id
                for template in templates
                if template.student_justification_required
            }
            justification = policy.structured_justification_policy
            if justification.mode == models.StructuredJustificationMode.ALL:
                expected_templates = {
                    template.opportunity_template_id for template in templates
                }
            elif justification.mode == models.StructuredJustificationMode.SELECTED:
                expected_templates = set(
                    justification.selected_opportunity_template_ids
                )
            else:
                expected_templates = set()
            if required_templates != expected_templates:
                raise GatewayContextError(
                    "P04 output changed the trusted structured-justification matrix"
                )
        elif prompt_id == "P05_BLUEPRINT_REVIEW_V1":
            expected = (
                request.blueprint.blueprint_id,
                request.blueprint.blueprint_version,
                request.activity_spec.activity_id,
            )
            actual = (output.blueprint_id, output.blueprint_version, output.activity_id)
            if actual != expected:
                raise GatewayContextError(
                    "P05 output blueprint reference mismatch",
                    phase=phase,
                    failure_code=ContextFailureCode.P05_REFERENCE_MISMATCH,
                )
            allowed_references = ModelGateway._collect_reference_ids(
                request.model_dump(mode="json")
            )
            if any(
                not set(check.referenced_ids).issubset(allowed_references)
                for check in output.checks
            ):
                raise GatewayContextError(
                    "P05 review check referenced an ID outside the reviewed roots",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.P05_REFERENCED_ID_NOT_ALLOWLISTED
                    ),
                )
        elif prompt_id == "P06_EVIDENCE_MAP_V1":
            if output.submission_id != request.evidence_bundle.submission_id:
                raise GatewayContextError("P06 output submission_id mismatch")
            templates = {
                template.opportunity_template_id: template
                for dimension in request.blueprint.dimensions
                for variant in dimension.evidence_variants
                for template in variant.question_opportunities
            }
            global_minimum = (
                request.blueprint.assessment_constraints.minimum_opportunity_quality
            )
            for opportunity in output.opportunities:
                template = templates.get(opportunity.opportunity_template_id)
                if template is None or opportunity.opportunity_quality < max(
                    global_minimum, template.minimum_quality
                ):
                    raise GatewayContextError(
                        "P06 opportunity lowered a trusted quality threshold"
                    )
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
                    candidate.candidate_id != request.target_candidate_id
                    or
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
                normalized_question_hash = _hash(
                    re.sub(r"\s+", " ", candidate.question_text).strip().casefold()
                )
                if normalized_question_hash in {
                    item.normalized_question_hash for item in request.avoid
                }:
                    raise GatewayContextError(
                        "Question output repeated a rejected question fingerprint"
                    )
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
            if output.guide_id != request.guide_id:
                raise GatewayContextError(
                    "P09 output guide_id mismatch",
                    phase=phase,
                    failure_code=ContextFailureCode.P09_GUIDE_ID_MISMATCH,
                )
            if output.assessment_id != request.assessment.assessment_id:
                raise GatewayContextError(
                    "P09 output assessment_id mismatch",
                    phase=phase,
                    failure_code=ContextFailureCode.P09_ASSESSMENT_ID_MISMATCH,
                )
            if output.submission_id != request.assessment.submission_id:
                raise GatewayContextError(
                    "P09 output submission_id mismatch",
                    phase=phase,
                    failure_code=ContextFailureCode.P09_SUBMISSION_ID_MISMATCH,
                )
            questions = {q.question_id: q for q in request.assessment.questions}
            for item in output.items:
                question = questions.get(item.question_id)
                if question is None:
                    raise GatewayContextError(
                        "Guide references an unknown question_id",
                        phase=phase,
                        failure_code=ContextFailureCode.P09_UNKNOWN_QUESTION_ID,
                    )
                for element in item.guide.observable_elements:
                    if not set(element.evidence_ids).issubset(set(question.evidence_ids)):
                        raise GatewayContextError(
                            "Guide invented evidence for a question",
                            phase=phase,
                            failure_code=(
                                ContextFailureCode.P09_QUESTION_EVIDENCE_ID_NOT_ALLOWLISTED
                            ),
                        )
                    if not set(element.source_ids).issubset(set(question.course_source_ids)):
                        raise GatewayContextError(
                            "Guide invented a course source",
                            phase=phase,
                            failure_code=(
                                ContextFailureCode.P09_QUESTION_SOURCE_ID_NOT_ALLOWLISTED
                            ),
                        )
            if output.status == "READY" and {
                item.question_id for item in output.items
            } != set(questions):
                raise GatewayContextError(
                    "READY guide must cover every assessment question",
                    phase=phase,
                    failure_code=(
                        ContextFailureCode.P09_QUESTION_COVERAGE_MISMATCH
                    ),
                )
        elif prompt_id == "P11_SCHEMA_REPAIR_V1":
            if output.target_schema_name != request.target_schema_name:
                raise GatewayContextError("P11 changed target_schema_name")
            if (
                output.repair_status == models.RepairStatus.REPAIRED
                and not ModelGateway._is_structural_repair(
                    request.invalid_output, output.repaired_output
                )
            ):
                raise GatewayContextError(
                    "P11 changed semantic content instead of structure"
                )

    @classmethod
    def _is_structural_repair(cls, original: Any, repaired: Any) -> bool:
        """Allow shape-only cleanup while preserving every existing semantic leaf."""

        if isinstance(original, dict):
            if not isinstance(repaired, dict):
                return False
            for key in set(original).intersection(repaired):
                if not cls._is_structural_repair(original[key], repaired[key]):
                    return False
            # Unknown fields may be removed. Newly materialized defaults may be
            # null/empty only; a missing semantic value cannot be invented.
            return all(
                value is None or value == [] or value == {}
                for key, value in repaired.items()
                if key not in original
            )
        if isinstance(original, list):
            return (
                isinstance(repaired, list)
                and len(original) == len(repaired)
                and all(
                    cls._is_structural_repair(left, right)
                    for left, right in zip(original, repaired, strict=True)
                )
            )
        return type(original) is type(repaired) and original == repaired

    @staticmethod
    def _is_structural_repair_eligible(
        issues: Sequence[SafeValidationIssue],
    ) -> bool:
        """Permit P11 only when deleting unknown fields can fix the output."""

        return bool(issues) and all(
            issue.error_type == "extra_forbidden" for issue in issues
        )

    async def _repair_once(
        self,
        *,
        target_spec: PromptSpec,
        invalid_output: Any,
        validation_issues: Sequence[SafeValidationIssue],
        trusted_context: models.TrustedPromptContext,
        max_cost_usd: float,
    ) -> tuple[BaseModel, tuple[models.ModelCallLedger, ...], tuple[ValidationPhase, ...]]:
        repair_spec = prompt_spec("P11_SCHEMA_REPAIR_V1")
        issues = []
        for issue in validation_issues[:_MAX_SAFE_VALIDATION_ISSUES]:
            issues.append(
                models.SchemaValidationIssue(
                    path=issue.path,
                    error_type=issue.error_type,
                    message="Canonical output model validation failed",
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
        input_tokens = (
            self.input_token_estimator(repair_spec, repair_request, repair_envelope)
            if self.config.mode == GatewayMode.REAL
            and self.input_token_estimator is not None
            else max(1, len(_canonical_json(repair_request)) // 4)
        )
        repair_budget = CallBudget(
            max_cost_usd,
            estimated_cost_usd=(
                self.cost_estimator(repair_spec, input_tokens)
                if self.config.mode == GatewayMode.REAL
                and self.cost_estimator is not None
                else 0.0
            ),
        )
        repair_resolution = self.resolver.resolve(
            repair_spec,
            required_input_modalities=(models.ModelInputModality.TEXT,),
            required_output_modalities=(models.ModelOutputModality.STRUCTURED_JSON,),
            budget=repair_budget,
            estimated_input_tokens=input_tokens,
        )
        if repair_resolution.status != "RESOLVED" or repair_resolution.route is None:
            error_type = (
                GatewayBudgetExceeded
                if any("BUDGET" in reason for reason in repair_resolution.reason_codes)
                else GatewayRouteBlocked
            )
            raise error_type(
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
        except (TimeoutError, ProviderTimeoutError) as exc:
            ledger = self._ledger(
                spec=repair_spec,
                envelope=repair_envelope,
                route=route,
                attempt=1,
                result="TIMEOUT",
                latency_ms=self._elapsed_ms(started),
                input_tokens=input_tokens,
                output_tokens=0,
                estimated_cost_usd=repair_budget.estimated_cost_usd,
                actual_cost_usd=0.0 if self.config.mode == GatewayMode.MOCK else None,
                reason_codes=self._error_reason_codes(exc),
            )
            self._record(ledger, repair_ledgers)
            raise GatewaySchemaViolation(
                "The single P11 repair attempt timed out",
                phase=ValidationPhase.OUTPUT,
                ledgers=repair_ledgers,
            ) from exc
        except SafetyBlockProviderError as exc:
            self._record_provider_failure(
                repair_ledgers,
                repair_spec,
                repair_envelope,
                route,
                1,
                started,
                "SAFETY_BLOCK",
                input_tokens,
                repair_budget,
                error=exc,
            )
            raise GatewaySafetyBlock(
                "P11 returned a safety refusal; no evasion retry is allowed",
                ledgers=repair_ledgers,
            ) from exc
        except ProviderBudgetError as exc:
            self._record_provider_failure(
                repair_ledgers,
                repair_spec,
                repair_envelope,
                route,
                1,
                started,
                "PROVIDER_ERROR",
                input_tokens,
                repair_budget,
                error=exc,
            )
            raise GatewayBudgetExceeded(
                "Provider budget blocked the single P11 attempt",
                ledgers=repair_ledgers,
                resolution=repair_resolution,
            ) from exc
        except ProviderAdapterError as exc:
            self._record_provider_failure(
                repair_ledgers,
                repair_spec,
                repair_envelope,
                route,
                1,
                started,
                "PROVIDER_ERROR",
                input_tokens,
                repair_budget,
                error=exc,
            )
            raise GatewayProviderError(
                "Provider failed during the single P11 attempt",
                ledgers=repair_ledgers,
            ) from exc
        except Exception as exc:
            self._record_provider_failure(
                repair_ledgers,
                repair_spec,
                repair_envelope,
                route,
                1,
                started,
                "PROVIDER_ERROR",
                input_tokens,
                repair_budget,
                reason_codes=("ADAPTER_UNEXPECTED_EXCEPTION",),
            )
            raise GatewayProviderError(
                "Unexpected provider failure during the single P11 attempt",
                ledgers=repair_ledgers,
            ) from exc
        try:
            repair_output = self._validate_output(repair_spec, result.raw_output)
        except GatewaySchemaViolation as exc:
            repair_primary_failure = exc.primary_failure or PrimaryOutputFailure(
                phase=ValidationPhase.OUTPUT,
                code="OUTPUT_PYDANTIC_VALIDATION_FAILED",
                validation_engine="PYDANTIC_MODEL_VALIDATE",
                issues=(),
            )
            repair_primary_failure = _primary_failure_with_provider_schema(
                repair_primary_failure, result
            )
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
                adapter_result=result,
                reason_codes=(repair_primary_failure.code,),
            )
            self._record(ledger, repair_ledgers)
            raise GatewaySchemaViolation(
                "P11 returned an invalid result; a second repair is forbidden",
                phase=ValidationPhase.OUTPUT,
                ledgers=repair_ledgers,
                primary_failure=repair_primary_failure,
                repair_disposition="RECURSIVE_REPAIR_FORBIDDEN",
            ) from exc
        order.append(ValidationPhase.OUTPUT)
        try:
            self._validate_context(
                repair_output,
                trusted_context,
                prompt_id=repair_spec.prompt_id,
                output=True,
                phase=ValidationPhase.OUTPUT,
            )
            self._validate_output_relationship(
                repair_spec.prompt_id,
                repair_request,
                repair_output,
                phase=ValidationPhase.OUTPUT,
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
                failure=context_error.failure,
            )
            raise GatewayContextError(
                "P11 output failed contextual validation",
                failure=context_error.failure,
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
            adapter_result=result,
        )
        self._record(ledger, repair_ledgers)
        if repair_output.repair_status != models.RepairStatus.REPAIRED:
            raise GatewaySchemaViolation(
                "P11 declared the output unrepairable",
                phase=ValidationPhase.REPAIRED_OUTPUT,
                ledgers=repair_ledgers,
                repair_disposition="DECLARED_UNREPAIRABLE",
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
            primary_failure = PrimaryOutputFailure(
                phase=ValidationPhase.REPAIRED_OUTPUT,
                code="REPAIRED_OUTPUT_PYDANTIC_VALIDATION_FAILED",
                validation_engine="PYDANTIC_MODEL_VALIDATE",
                issues=_safe_pydantic_issues(exc, target_model),
            )
        raise GatewaySchemaViolation(
            "P11 repaired_output still violates the target root",
            phase=ValidationPhase.REPAIRED_OUTPUT,
            primary_failure=primary_failure,
            repair_disposition="REPAIRED_OUTPUT_INVALID",
        )

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
        adapter_result: AdapterResult | None = None,
        reason_codes: Sequence[str] = (),
    ) -> models.ModelCallLedger:
        input_hash = _hash(envelope)
        created = self.config.clock()
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        ledger_route = self._route_for_ledger(
            route,
            adapter_result=adapter_result,
            reason_codes=reason_codes,
        )
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
            route=ledger_route,
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
        error: BaseException | None = None,
        reason_codes: Sequence[str] = (),
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
            reason_codes=(*reason_codes, *self._error_reason_codes(error)),
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
        failure: ContextFailure,
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
            adapter_result=result,
            reason_codes=(
                "OUTPUT_CONTEXT_VALIDATION_FAILED",
                *(
                    f"CONTEXT_FAILURE_{failure.phase.value.upper()}_"
                    f"{code.value}"
                    for code in failure.codes
                ),
            ),
        )
        self._record(ledger, ledgers)

    @staticmethod
    def _error_reason_codes(error: BaseException | None) -> tuple[str, ...]:
        if error is None:
            return ()
        reason = getattr(error, "reason_code", None)
        request_hash = getattr(error, "request_id_hash", None)
        codes: list[str] = []
        if isinstance(reason, str):
            codes.append(reason)
        if isinstance(request_hash, str):
            codes.append(
                f"PROVIDER_REQUEST_ID_HASH_{request_hash.removeprefix('sha256:')}"
            )
        return tuple(codes)

    @staticmethod
    def _ledger_budget_charge(ledger: models.ModelCallLedger) -> float:
        """Reserve the larger observed or preflight cost for later calls."""

        return max(ledger.estimated_cost_usd, ledger.actual_cost_usd or 0.0)

    @staticmethod
    def _route_for_ledger(
        route: models.ModelRoute,
        *,
        adapter_result: AdapterResult | None,
        reason_codes: Sequence[str],
    ) -> models.ModelRoute:
        codes = [*route.reason_codes, *reason_codes]
        model_snapshot = route.model_snapshot
        if adapter_result is not None:
            codes.extend(adapter_result.reason_codes)
            codes.append(
                "CACHE_WRITE_INPUT_TOKENS_"
                f"{max(0, adapter_result.cache_write_input_tokens)}"
            )
            codes.append(
                f"REASONING_TOKENS_{max(0, adapter_result.reasoning_tokens)}"
            )
            if adapter_result.effective_model:
                model_snapshot = adapter_result.effective_model
                codes.append(f"EFFECTIVE_MODEL_{adapter_result.effective_model}")
            if adapter_result.output_hash:
                codes.append(
                    f"OUTPUT_HASH_{adapter_result.output_hash.removeprefix('sha256:')}"
                )
            if adapter_result.provider_request_id_hash:
                codes.append(
                    "PROVIDER_REQUEST_ID_HASH_"
                    + adapter_result.provider_request_id_hash.removeprefix("sha256:")
                )
        return route.model_copy(
            update={
                "model_snapshot": model_snapshot,
                "reason_codes": list(dict.fromkeys(codes)),
            }
        )

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
