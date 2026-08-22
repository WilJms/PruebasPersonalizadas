"""Successor real-call harness for the frozen semantic-benchmark/1.3.5 instrument.

The semantic instrument and the execution harness have deliberately separate
boundaries. This module consumes immutable v1.3.5 authority plus the frozen
``phase9-execution/2.0.3`` request snapshot. It never rebuilds qualification
authority from historical benchmark trees.

The public execution entrypoint is fail-closed in this checkout: current
official pricing evidence and a non-billable cost projection are published,
but no billable authorization is. Therefore every reachable call stops before
credential resolution and before transport construction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any, Final

from pydantic import BaseModel, SecretStr

from .canonical import canonical_hash
from .contracts import SCHEMA_VERSION, model_by_name, models as m
from .model_gateway import GatewayConfig, GatewayMode, ModelGateway
from .model_gateway.gateway import (
    CallBudget,
    GatewayContextError,
    GatewaySchemaViolation,
    ProviderAdapterError,
)
from .model_gateway.mock_factory import build_trusted_context
from .model_gateway.openai_adapter import (
    OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
)
from .model_gateway.openai_routes import (
    OPENAI_MAX_INPUT_TOKENS,
    build_openai_routes,
    estimate_openai_input_tokens,
    openai_route_matches_profile,
)
from .model_gateway.openai_pricing import LONG_CONTEXT_THRESHOLD
from .model_gateway.registry import PROMPT_SPECS, PromptSpec, prompt_spec
from .p06_n3_protocol import (
    N3_PACKET_FORBIDDEN_FIELDS as FROZEN_N3_PACKET_FORBIDDEN_FIELDS,
    N3ProtocolError,
    N3_SAFETY_VERDICTS,
    assert_n3_packet_blind as assert_frozen_n3_packet_blind,
    build_n3_packet as build_frozen_n3_packet,
)
from .semantic_benchmark import load_corpus_package
from .semantic_benchmark_v135 import (
    QualificationPromptMismatch,
    assert_live_prompt_authority,
    build_qualification_transport_after_prompt_guard,
)


PHASE9_EXECUTION_VERSION: Final = "phase9-execution/2.0.3"
BENCHMARK_VERSION: Final = "semantic-benchmark/1.3.5"
PROTOCOL_VERSION: Final = "phase9-qualification-protocol/1.3.5"
AUTHORIZED_K: Final = 3
AUTHORIZED_PRIMARY_LOGICAL_CALLS: Final = 30
AUTHORIZED_SEMANTIC_PACKET_COUNT: Final = 54
AUTHORIZED_N3_PACKET_COUNT: Final = 3
AUTHORIZED_P06_SEMANTIC_OBSERVATION_COUNT: Final = 6
AUTHORIZED_SPLIT: Final = "SMOKE"
OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS: Final = 15
MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL: Final = 1
QUALIFICATION_SCHEMA_REPAIR: Final = "FORBIDDEN"
QUALIFICATION_N3_SEMANTIC_METADATA_FORBIDDEN_FIELDS: Final = frozenset(
    {
        "semantic_outcome",
        "semantic_status",
        "result_state",
        "accepted_semantic_rate",
        "qualification_outcome",
    }
)
N3_PACKET_FORBIDDEN_FIELDS: Final = (
    FROZEN_N3_PACKET_FORBIDDEN_FIELDS
    | QUALIFICATION_N3_SEMANTIC_METADATA_FORBIDDEN_FIELDS
)

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
V135_DEFINITION_ROOT: Final = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_5"
V135_REPORT_ROOT: Final = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_5"
EXECUTION_AUTHORITY_ROOT: Final = REPOSITORY_ROOT / "evaluation/phase9_execution/v2_0_3"
EXECUTION_REPORT_ROOT: Final = REPOSITORY_ROOT / "reports/phase9_execution/v2_0_3"
EXECUTION_BOUNDARY_PATH: Final = EXECUTION_AUTHORITY_ROOT / "execution_boundary.json"
HIGH_SMOKE_REQUEST_AUTHORITY_PATH: Final = (
    EXECUTION_AUTHORITY_ROOT / "high_smoke_request_authority.json"
)
CURRENT_PRICING_PATH: Final = EXECUTION_AUTHORITY_ROOT / "current_pricing.json"
COST_PROJECTION_PATH: Final = (
    EXECUTION_REPORT_ROOT / "pre_authorization_cost_projection.json"
)
BILLABLE_AUTHORIZATION_PATH: Final = (
    EXECUTION_AUTHORITY_ROOT / "billable_authorization.json"
)
EXECUTION_EVIDENCE_ROOT: Final = EXECUTION_REPORT_ROOT / "executions"
ADJUDICATION_BUNDLE_ROOT: Final = EXECUTION_REPORT_ROOT / "adjudication_bundles"
PREDECESSOR_EXECUTION_AUTHORITY_ROOT: Final = (
    REPOSITORY_ROOT / "evaluation/phase9_execution/v2_0_2"
)
PREDECESSOR_EXECUTION_REPORT_ROOT: Final = (
    REPOSITORY_ROOT / "reports/phase9_execution/v2_0_2"
)
PREDECESSOR_REQUEST_AUTHORITY_PATH: Final = (
    PREDECESSOR_EXECUTION_AUTHORITY_ROOT / "high_smoke_request_authority.json"
)
PREDECESSOR_AUTHORIZATION_PATH: Final = (
    PREDECESSOR_EXECUTION_AUTHORITY_ROOT / "billable_authorization.json"
)
PREDECESSOR_EXECUTION_MANIFEST_PATH: Final = (
    PREDECESSOR_EXECUTION_REPORT_ROOT
    / "executions/exec-phase9v202-b820f4bfa94de537/execution_manifest.json"
)
PREDECESSOR_POST_EXECUTION_AUDIT_PATH: Final = (
    PREDECESSOR_EXECUTION_REPORT_ROOT
    / "post_execution_audit_exec-phase9v202-b820f4bfa94de537.json"
)

EXPECTED_V200_ARTIFACT_HASHES: Final[Mapping[str, str]] = {
    "evaluation/phase9_execution/v2_0_0/execution_boundary.json": (
        "sha256:6f881dd2d430b0d2749759ef12b99d535e30a8194c20eafb98d2bffd0d86fcaa"
    ),
    "evaluation/phase9_execution/v2_0_0/high_smoke_request_authority.json": (
        "sha256:4ea7dbe28be868ce548787dd1f24e46ef98f97ea30e22e2fdcddd35aaf7b220e"
    ),
    "reports/phase9_execution/v2_0_0/execution_cutover_report.json": (
        "sha256:a9cc87358237d19539a57ca888dc4d55b01f5d542a1ce0438f64959fc6537ca9"
    ),
}

EXPECTED_V201_ARTIFACT_HASHES: Final[Mapping[str, str]] = {
    "evaluation/phase9_execution/v2_0_1/execution_boundary.json": (
        "sha256:4146cf7aa6a5c7750fb2bb2f9694e942e61caa419967fc29c0f70ba162e638de"
    ),
    "evaluation/phase9_execution/v2_0_1/high_smoke_request_authority.json": (
        "sha256:6bd9ae607670ce0fc3d39e928659c0717f0ab783794727c1afa5bbc52bc1da9f"
    ),
    "reports/phase9_execution/v2_0_1/execution_cutover_report.json": (
        "sha256:c908a274a5d121c101711a11e416d7eb4d0ac11131c4ca64e7542e872a488ef4"
    ),
    "reports/phase9_execution/v2_0_1/lineage.json": (
        "sha256:5e8fa82dc7536f0fbd49710ddd27fec5787bcbe412b6dded9e70bcca1b6798a7"
    ),
}

EXPECTED_PREDECESSOR_ARTIFACT_HASHES: Final[Mapping[str, str]] = {
    "evaluation/phase9_execution/v2_0_2/billable_authorization.json": (
        "sha256:86589a5041661529f208e9b9763aaf61c2d8a2eea47b1a3b8fdc99c403bfb6b5"
    ),
    "evaluation/phase9_execution/v2_0_2/current_pricing.json": (
        "sha256:f896f7cdfd939d6f171ef2c64acfcf6f8609860b927d132a27a6b40b70cc032d"
    ),
    "evaluation/phase9_execution/v2_0_2/execution_boundary.json": (
        "sha256:a91cdf93cb5fda16dccc5658ae62b21255d77aa4e90d25a4cd8f3f2bacf8a6fb"
    ),
    "evaluation/phase9_execution/v2_0_2/high_smoke_request_authority.json": (
        "sha256:f393f0b7009cb782d781d3a8d10f59c9c2dc9ffb35f6732e86380301c212b03f"
    ),
    "reports/phase9_execution/v2_0_2/authorization_ledger/phase9-high-smoke-20260821t195155z-3a9043f192fa.json": (
        "sha256:908698707cbbd11af29d220c2045ae04c56189a269f40a0a1f6e4a470b580872"
    ),
    "reports/phase9_execution/v2_0_2/execution_cutover_report.json": (
        "sha256:bd216a5167ce32c50c2a6a36094d592fc90dafd17f0e91824d503b3d3c533a71"
    ),
    "reports/phase9_execution/v2_0_2/execution_result_phase9-high-smoke-20260821t195155z-3a9043f192fa.json": (
        "sha256:470ab000810f9028c259bd4a26fa95e93bb21d01e5e5e6a0ba76cce29aaab020"
    ),
    "reports/phase9_execution/v2_0_2/executions/exec-phase9v202-b820f4bfa94de537/execution_manifest.json": (
        "sha256:f626786485b4cb64c62a0c19c18ccc8f8aaaeab6b0ec173f8dd4215f30fbae76"
    ),
    "reports/phase9_execution/v2_0_2/lineage.json": (
        "sha256:a1c964b823edc24d2b72b6b0e7a463ecd86c7705581900096f62e0db4b425ff9"
    ),
    "reports/phase9_execution/v2_0_2/post_execution_audit_exec-phase9v202-b820f4bfa94de537.json": (
        "sha256:f1bb00ad078d86b9fd9da4dee12629dfeb8263b3b98aeeecde3fdfc4f458fb27"
    ),
    "reports/phase9_execution/v2_0_2/pre_authorization_cost_projection.json": (
        "sha256:a9b2e7f8570a9aee31ac90aa62777e328610f23fa2768bd0922e1414fc713aaf"
    ),
}

PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES: Final[Mapping[str, str]] = {
    **EXPECTED_V200_ARTIFACT_HASHES,
    **EXPECTED_V201_ARTIFACT_HASHES,
    **EXPECTED_PREDECESSOR_ARTIFACT_HASHES,
}

OFFICIAL_PRICING_SOURCE_URLS: Final[tuple[str, ...]] = (
    "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
    "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
    "https://developers.openai.com/api/docs/guides/latest-model",
)
EXPECTED_CURRENT_PRICING_RATES: Final[Mapping[str, Mapping[str, Decimal]]] = {
    "gpt-5.6-terra": {
        "input_per_million_usd": Decimal("2.00"),
        "cached_input_per_million_usd": Decimal("0.20"),
        "cache_write_per_million_usd": Decimal("2.50"),
        "output_per_million_usd": Decimal("12.00"),
    },
    "gpt-5.6-luna": {
        "input_per_million_usd": Decimal("0.20"),
        "cached_input_per_million_usd": Decimal("0.02"),
        "cache_write_per_million_usd": Decimal("0.25"),
        "output_per_million_usd": Decimal("1.20"),
    },
}
CACHE_WRITE_PRICE_MULTIPLIER: Final = Decimal("1.25")
EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH: Final = (
    "sha256:fef890ffa1b12e8717edd7cb5e13f7cdbd78b1e3eb9284aea20a21b29f45553e"
)

EXPECTED_BENCHMARK_BOUNDARY_HASH: Final = (
    "sha256:ff6988324a9bd5cd1c4167b0589f8700f19985fca7ef021d0eb5dcfb875fffe5"
)
EXPECTED_PROTOCOL_BOUNDARY_HASH: Final = (
    "sha256:711e8f42c13cadab4707b153bb5e987c56330fc9b112a349eaf8330d2dab41cc"
)
EXPECTED_PROMPT_AUTHORITY_HASH: Final = (
    "sha256:820396b80101c79478e6cd1b9914a6cae6931dc055c1199e9e533bc3c6e2c3e9"
)
EXPECTED_EXECUTION_CONTRACT_HASH: Final = (
    "sha256:ae260e18b6b0a6918d923ce304ead3869afd767d553828591aa33f1d283d04a5"
)
EXPECTED_N3_AXIS_HASH: Final = (
    "sha256:0add76d694432b3a8cc7f53a2f6e0d4cef10aa69e893121a638d7d8ffa8c6eec"
)
EXPECTED_CORPUS_BOUNDARY_HASH: Final = (
    "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1"
)
RUNTIME_SOURCE_BINDING_ROLES: Final[Mapping[str, str]] = {
    "scripts/build_phase9_forensic_repair.py": (
        "offline async lifecycle reproduction and forensic evidence construction"
    ),
    "scripts/build_phase9_execution_v2.py": "execution authority publication",
    "scripts/run_phase9_smoke.py": "CLI status and deferred credential entrypoint",
    "specification/models_v1.1(1).py": "canonical request and output contracts",
    "src/comprehension_verification/blueprint_compiler.py": (
        "P04 deterministic materialization and acceptance"
    ),
    "src/comprehension_verification/canonical.py": (
        "canonical execution identity and hashing"
    ),
    "src/comprehension_verification/contracts.py": "canonical contract loader",
    "src/comprehension_verification/diagnostics.py": (
        "P04 deterministic diagnostic materialization"
    ),
    "src/comprehension_verification/evidence_mapping.py": (
        "P06 deterministic materialization and acceptance"
    ),
    "src/comprehension_verification/guide_generation.py": (
        "P09 deterministic materialization and acceptance"
    ),
    "src/comprehension_verification/model_gateway/__init__.py": (
        "gateway public import boundary used by authorization and execution"
    ),
    "src/comprehension_verification/model_gateway/gateway.py": (
        "call control, validation, materialization, and invocation multiplicity"
    ),
    "src/comprehension_verification/model_gateway/mock_factory.py": (
        "trusted-context and synthetic attestation construction"
    ),
    "src/comprehension_verification/model_gateway/openai_adapter.py": (
        "provider request construction and response accounting"
    ),
    "src/comprehension_verification/model_gateway/openai_pricing.py": (
        "adapter-side provider result accounting"
    ),
    "src/comprehension_verification/model_gateway/openai_routes.py": (
        "route, model, reasoning, and provider-visible developer instruction"
    ),
    "src/comprehension_verification/model_gateway/openai_schema.py": (
        "provider structured-output schema construction"
    ),
    "src/comprehension_verification/model_gateway/prompt_text.py": (
        "provider-visible system and task instructions"
    ),
    "src/comprehension_verification/model_gateway/registry.py": (
        "prompt contracts, versions, and provider output roots"
    ),
    "src/comprehension_verification/n3_provider_fixtures.py": (
        "frozen N3 request-authority builder"
    ),
    "src/comprehension_verification/p06_n3_protocol.py": (
        "frozen N3 packet base consumed by the v2.0.3 blindness extension"
    ),
    "src/comprehension_verification/p06_noisy_contractual_gate.py": (
        "N3 contractual prompt authority material"
    ),
    "src/comprehension_verification/phase9_execution.py": (
        "execution boundary, accounting, completeness, and evidence"
    ),
    "src/comprehension_verification/phase9_protocol.py": (
        "N3 execution cardinality constant"
    ),
    "src/comprehension_verification/provider_authorization.py": (
        "pinned-secret validation before credential resolution"
    ),
    "src/comprehension_verification/question_generation.py": (
        "P07 deterministic materialization and acceptance"
    ),
    "src/comprehension_verification/semantic_benchmark.py": (
        "frozen corpus and request-authority loading"
    ),
    "src/comprehension_verification/semantic_benchmark_fixtures.py": (
        "frozen semantic request builder"
    ),
    "src/comprehension_verification/semantic_benchmark_v135.py": (
        "frozen prompt guard and v1.3.5 authority validation"
    ),
    "src/comprehension_verification/validation.py": (
        "P04 deterministic preflight acceptance"
    ),
    "src/comprehension_verification/web/provider_secrets.py": (
        "post-authorization credential resolution boundary"
    ),
}
REQUIRED_SOURCE_BINDING_PATHS: Final = frozenset(RUNTIME_SOURCE_BINDING_ROLES)

QUALIFICATION_EXECUTION_POLICY: Final[Mapping[str, Any]] = {
    "qualification_schema_repair": QUALIFICATION_SCHEMA_REPAIR,
    "p11_provider_execution": "FORBIDDEN",
    "allowed_provider_prompt_ids": [
        "P04_BLUEPRINT_BUILD_V1",
        "P06_EVIDENCE_MAP_V1",
        "P07_QUESTION_BUILD_V1",
        "P09_GUIDE_BUILD_V1",
    ],
    "successful_provider_invocations_per_logical_attempt": 1,
    "off_plan_provider_invocation_disposition": "FAIL_CLOSED",
    "event_loop_lifecycle": "ONE_ASYNCIO_RUN_PER_AUTHORIZED_POPULATION",
    "logical_call_execution": "SEQUENTIAL_FROZEN_ORDER",
    "concurrency": "FORBIDDEN",
    "adapter_reuse_scope": "ONE_LIVE_EVENT_LOOP",
    "async_transport_close": "SAME_OWNING_EVENT_LOOP_WHEN_EXPOSED",
    "technical_retry_owner": "OUTER_EXECUTOR",
    "gateway_max_retries": 0,
    "max_technical_retries_per_logical_call": 1,
    "retry_disposition_source": "SANITIZED_UNDERLYING_PROVIDER_REASON",
    "provider_invocation_evidence": "SAFE_CONTENT_FREE_PER_INVOCATION",
    "n3_semantic_metadata_forbidden_fields": sorted(
        QUALIFICATION_N3_SEMANTIC_METADATA_FORBIDDEN_FIELDS
    ),
}

EXPECTED_PLAN_DECOMPOSITION: Final[Mapping[str, int]] = {
    "SEMANTIC/P04/SMOKE/HIGH": 3,
    "SEMANTIC/P06/SMOKE/HIGH": 3,
    "CONTRACTUAL_HARD_SAFETY/P06/N3_SAFETY_SMOKE/HIGH": 3,
    "SEMANTIC/P07/SMOKE/HIGH": 18,
    "SEMANTIC/P09/SMOKE/HIGH": 3,
}

RETRYABLE_TECHNICAL_CODES: Final = frozenset(
    {
        "PROVIDER_TIMEOUT",
        "PROVIDER_CONNECTION",
        "PROVIDER_TRANSIENT_STATUS",
        "PROVIDER_RATE_LIMIT",
    }
)
EXCLUDED_FROM_AUTHORIZATION: Final = (
    "CORE",
    "HELD_OUT_CONFIRMATION",
    "N3_CORE",
    "N3_HELD_OUT_CONFIRMATION",
    "XHIGH",
    "MAX",
    "gpt-5.6-sol",
    "P01",
    "P02",
    "P03",
    "P05",
    "P08",
    "P10",
    "P11_SEMANTIC_REPAIR",
    "LONG_CONTEXT",
)


class Phase9ExecutionError(RuntimeError):
    """Fail-closed stop before or during qualification execution."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        safety_counters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.safety_counters = dict(safety_counters or {})


@dataclass(slots=True)
class SafetyCounters:
    provider_calls: int = 0
    adjudicator_calls: int = 0
    credential_resolutions: int = 0
    transport_factory_calls: int = 0
    real_provider_transport: bool = False
    pricing_refresh: str = "NOT_PERFORMED"
    high_smoke: str = "NOT_EXECUTED"
    billable_authorization: str = "NONE"

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider_calls": self.provider_calls,
            "adjudicator_calls": self.adjudicator_calls,
            "credential_resolutions": self.credential_resolutions,
            "transport_factory_calls": self.transport_factory_calls,
            "real_provider_transport": self.real_provider_transport,
            "pricing_refresh": self.pricing_refresh,
            "high_smoke": self.high_smoke,
            "billable_authorization": self.billable_authorization,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedCandidate:
    stage: str
    candidate_id: str
    model: str
    reasoning_effort: str
    route_profile_id: str
    prompt_id: str
    max_output_tokens: int


AUTHORIZED_CANDIDATES: Final[tuple[AuthorizedCandidate, ...]] = (
    AuthorizedCandidate(
        "P04", "P04-C1-TERRA-HIGH", "gpt-5.6-terra", "HIGH",
        "TERRA_HIGH_V1", "P04_BLUEPRINT_BUILD_V1", 16_000,
    ),
    AuthorizedCandidate(
        "P06", "P06-C1-LUNA-HIGH", "gpt-5.6-luna", "HIGH",
        "LUNA_BASELINE_V1", "P06_EVIDENCE_MAP_V1", 16_000,
    ),
    AuthorizedCandidate(
        "P07", "P07-C1-LUNA-HIGH", "gpt-5.6-luna", "HIGH",
        "LUNA_BASELINE_V1", "P07_QUESTION_BUILD_V1", 10_000,
    ),
    AuthorizedCandidate(
        "P09", "P09-C1-LUNA-HIGH", "gpt-5.6-luna", "HIGH",
        "LUNA_BASELINE_V1", "P09_GUIDE_BUILD_V1", 10_000,
    ),
)
CANDIDATE_BY_STAGE: Final[Mapping[str, AuthorizedCandidate]] = {
    item.stage: item for item in AUTHORIZED_CANDIDATES
}
FORBIDDEN_CANDIDATE_IDS: Final = (
    "P04-C2-TERRA-XHIGH",
    "P06-C2-LUNA-XHIGH",
    "P06-C3-LUNA-MAX",
    "P07-C2-LUNA-XHIGH",
    "P07-C3-LUNA-MAX",
    "P09-C2-LUNA-XHIGH",
    "P09-C3-LUNA-MAX",
)


@dataclass(frozen=True, slots=True)
class FrozenAuthorityPaths:
    freeze_manifest: Path = V135_REPORT_ROOT / "phase9/freeze_hash_manifest.json"
    pre_results_freeze: Path = V135_REPORT_ROOT / "phase9/pre_results_instrument_freeze.json"
    benchmark_boundary: Path = V135_REPORT_ROOT / "benchmark_boundary.json"
    stage_boundaries: Path = V135_REPORT_ROOT / "stage_boundaries.json"
    qualification_protocol: Path = V135_DEFINITION_ROOT / "phase9/qualification_protocol.json"
    candidate_matrix: Path = V135_DEFINITION_ROOT / "phase9/candidate_matrix.json"
    candidate_execution_contract: Path = V135_DEFINITION_ROOT / "phase9/candidate_execution_contract.json"
    prompt_authority: Path = V135_DEFINITION_ROOT / "phase9/executable_prompt_authority.json"
    call_budget: Path = V135_REPORT_ROOT / "phase9/call_budget.json"
    n3_axis: Path = V135_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    p06_submission_requests: Path = V135_DEFINITION_ROOT / "phase9/p06_submission_requests.json"
    p06_observation_bindings: Path = V135_DEFINITION_ROOT / "phase9/p06_property_observation_bindings.json"
    n3_provider_fixtures: Path = V135_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json"
    rung_collection: Path = V135_REPORT_ROOT / "phase9/rung_collection_authority.json"

    def items(self) -> tuple[tuple[str, Path], ...]:
        return tuple(
            (name, getattr(self, name))
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        )


@dataclass(frozen=True, slots=True)
class FrozenAuthorities:
    documents: Mapping[str, Mapping[str, Any]]
    semantic_bindings: Mapping[str, Any]
    frozen_artifacts: Mapping[str, Mapping[str, str]]
    freeze_manifest_file_sha256: str


@dataclass(frozen=True, slots=True)
class ProviderCase:
    axis: str
    stage: str
    split: str
    provider_unit: str
    provider_identity: str
    candidate: AuthorizedCandidate
    request: BaseModel
    request_hash: str
    frozen_input_hash: str | None
    fixture_id: str
    property_observations: tuple[Mapping[str, Any], ...] = ()
    exposure_pseudonym: str | None = None
    n3_packet_authority: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LogicalCall:
    logical_call_id: str
    case: ProviderCase
    run_index: int

    def identity(self) -> dict[str, Any]:
        identity = {
            "axis": self.case.axis,
            "stage": self.case.stage,
            "split": self.case.split,
            "provider_unit": self.case.provider_unit,
            "provider_identity": self.case.provider_identity,
            "candidate_id": self.case.candidate.candidate_id,
            "reasoning_rung": self.case.candidate.reasoning_effort,
            "run_index": self.run_index,
        }
        if self.case.exposure_pseudonym is not None:
            identity["exposure_pseudonym"] = self.case.exposure_pseudonym
        return identity


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    authorities: FrozenAuthorities
    boundary: Mapping[str, Any]
    request_authority: Mapping[str, Any]
    cases: tuple[ProviderCase, ...]
    calls: tuple[LogicalCall, ...]
    plan: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CompletedCall:
    canonical_output: Mapping[str, Any]
    provider_output: Mapping[str, Any]


def _hash(payload: Any) -> str:
    return canonical_hash(payload)


def _file_hash(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase9ExecutionError("PHASE9_AUTHORITY_UNAVAILABLE", f"cannot load {path}") from exc
    if not isinstance(value, dict):
        raise Phase9ExecutionError("PHASE9_AUTHORITY_INVALID", f"{path} is not a JSON object")
    return value


def _self_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash({key: value for key, value in document.items() if key != field})


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise Phase9ExecutionError(code, message)


def _walk_n3_packet_keys(
    value: Any, path: str = ""
) -> Sequence[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            rows.append((child, str(key)))
            rows.extend(_walk_n3_packet_keys(item, child))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            rows.extend(_walk_n3_packet_keys(item, f"{path}[{index}]"))
    return rows


def assert_n3_packet_blind(packet: Mapping[str, Any]) -> None:
    """Apply the frozen N3 contract plus v2.0.3 qualification metadata bans."""

    assert_frozen_n3_packet_blind(packet)
    for path, key in _walk_n3_packet_keys(packet):
        if key in QUALIFICATION_N3_SEMANTIC_METADATA_FORBIDDEN_FIELDS:
            raise N3ProtocolError(f"forbidden N3 packet field at {path}")


def build_n3_packet(
    *,
    exposure_pseudonym: str,
    run_index: int,
    route_context: Mapping[str, Any],
    model_visible_evidence: Sequence[Mapping[str, Any]],
    model_owned_output: Mapping[str, Any],
    p06_stage_boundary_hash: str,
    p06_field_authority_hash: str,
    exposure_selector: Mapping[str, Any],
    n3_gate_source_hash: str,
) -> dict[str, Any]:
    """Build a frozen-format packet and enforce the executor-local extension."""

    packet = build_frozen_n3_packet(
        exposure_pseudonym=exposure_pseudonym,
        run_index=run_index,
        route_context=route_context,
        model_visible_evidence=model_visible_evidence,
        model_owned_output=model_owned_output,
        p06_stage_boundary_hash=p06_stage_boundary_hash,
        p06_field_authority_hash=p06_field_authority_hash,
        exposure_selector=exposure_selector,
        n3_gate_source_hash=n3_gate_source_hash,
    )
    assert_n3_packet_blind(packet)
    return packet


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPOSITORY_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _request_population_projection(
    request_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Project only provider-visible cases; execution publication metadata is excluded."""

    return {
        "semantic_cases": deepcopy(request_authority.get("semantic_cases", [])),
        "n3_exposures": deepcopy(request_authority.get("n3_exposures", [])),
    }


def ordered_logical_call_identities_from_request_authority(
    request_authority: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Derive the ordered 30-call identity population without outcome data."""

    groups = [
        *request_authority.get("semantic_cases", []),
        *request_authority.get("n3_exposures", []),
    ]
    _require(
        all(isinstance(row, Mapping) for row in groups),
        "PHASE9_HIGH_SMOKE_PLAN_MISMATCH",
        "the request authority contains a non-object provider population row",
    )
    groups.sort(
        key=lambda row: (
            {"P04": 0, "P06": 1, "P07": 2, "P09": 3}.get(
                str(row.get("stage")), 99
            ),
            1 if row.get("axis") == "CONTRACTUAL_HARD_SAFETY" else 0,
            str(row.get("provider_identity")),
        )
    )
    identities: list[dict[str, Any]] = []
    for row in groups:
        stage = str(row.get("stage"))
        _require(
            stage in CANDIDATE_BY_STAGE,
            "PHASE9_HIGH_SMOKE_PLAN_MISMATCH",
            f"the request authority contains an unauthorized stage: {stage}",
        )
        candidate = CANDIDATE_BY_STAGE[stage]
        for run_index in range(1, AUTHORIZED_K + 1):
            identity = {
                "axis": row.get("axis"),
                "stage": stage,
                "split": row.get("split"),
                "provider_unit": row.get("provider_unit"),
                "provider_identity": row.get("provider_identity"),
                "candidate_id": candidate.candidate_id,
                "reasoning_rung": candidate.reasoning_effort,
                "run_index": run_index,
            }
            if row.get("axis") == "CONTRACTUAL_HARD_SAFETY":
                identity["exposure_pseudonym"] = row.get("exposure_pseudonym")
            identities.append(identity)
    return identities


def _validated_predecessor_execution() -> dict[str, Any]:
    """Bind v2.0.3 to immutable, consumed v2.0.2 execution history."""

    for relative, expected in PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES.items():
        path = (REPOSITORY_ROOT / relative).resolve()
        _require(
            path.is_relative_to(REPOSITORY_ROOT.resolve())
            and path.is_file()
            and _file_hash(path) == expected,
            "PHASE9_PREDECESSOR_EXECUTION_ARTIFACT_MISMATCH",
            f"published phase9 execution bytes drifted: {relative}",
        )
    request = _read_json(PREDECESSOR_REQUEST_AUTHORITY_PATH)
    _require(
        request.get("execution_version") == "phase9-execution/2.0.2"
        and request.get("request_authority_hash")
        == _self_hash(request, "request_authority_hash"),
        "PHASE9_PREDECESSOR_EXECUTION_ARTIFACT_MISMATCH",
        "the phase9-execution/2.0.2 request authority is invalid",
    )
    audit = _read_json(PREDECESSOR_POST_EXECUTION_AUDIT_PATH)
    counts = audit.get("execution_counts", {})
    manifest = _read_json(PREDECESSOR_EXECUTION_MANIFEST_PATH)
    authorization = _read_json(PREDECESSOR_AUTHORIZATION_PATH)
    _require(
        audit.get("audit_hash") == _self_hash(audit, "audit_hash")
        and audit.get("bindings", {}).get("execution_version")
        == "phase9-execution/2.0.2"
        and audit.get("authorization_consumption_state")
        == "CONSUMED_EXACTLY_ONCE"
        and counts.get("total_provider_invocations") == 30
        and counts.get("provider_logical_calls_completed") == 12
        and counts.get("provider_logical_calls_failed") == 18
        and counts.get("failure_codes")
        == {
            "MODEL_CONTEXT_NOT_ALLOWLISTED": 3,
            "MODEL_PROVIDER_ERROR": 15,
        }
        and counts.get("technical_retries_used") == 0
        and counts.get("adjudicator_calls") == 0
        and manifest.get("status") == "PHASE9_SMOKE_GENERATION_INCOMPLETE"
        and len(manifest.get("attempts", [])) == 30
        and authorization.get("authorization_hash")
        == audit.get("authorization_hash"),
        "PHASE9_PREDECESSOR_EXECUTION_ARTIFACT_MISMATCH",
        "phase9-execution/2.0.2 consumed history is not internally consistent",
    )
    identities = ordered_logical_call_identities_from_request_authority(request)
    ordered_hash = canonical_hash(identities)
    _require(
        ordered_hash == EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH,
        "PHASE9_PREDECESSOR_EXECUTION_POPULATION_MISMATCH",
        "phase9-execution/2.0.2 ordered logical population drifted",
    )
    return {
        "execution_version": "phase9-execution/2.0.2",
        "published_artifacts": dict(EXPECTED_PREDECESSOR_ARTIFACT_HASHES),
        "protected_prior_publications": dict(
            PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES
        ),
        "provider_calls": 30,
        "adjudicator_calls": 0,
        "provider_logical_calls_completed": 12,
        "provider_logical_calls_failed": 18,
        "technical_retries": 0,
        "actual_cost_usd": audit["actual_cost_usd"]["global_total"],
        "high_smoke": "ATTEMPTED_INCOMPLETE",
        "authorization_id": audit["authorization_id"],
        "authorization_hash": audit["authorization_hash"],
        "authorization_consumption_state": "CONSUMED_EXACTLY_ONCE",
        "used_for_provider_call": True,
        "outputs_carried_forward": False,
        "diagnostic_history_only": True,
        "request_population_hash": canonical_hash(
            _request_population_projection(request)
        ),
        "ordered_logical_call_population_hash": ordered_hash,
    }


def _assert_current_frozen_path(name: str, path: Path) -> None:
    resolved = path.resolve()
    allowed_roots = (V135_DEFINITION_ROOT.resolve(), V135_REPORT_ROOT.resolve())
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise Phase9ExecutionError(
            "PHASE9_V2_LEGACY_AUTHORITY_FORBIDDEN",
            f"{name} is outside the immutable v1.3.5 authority roots",
        )


_SELF_HASH_FIELDS: Final[Mapping[str, str]] = {
    "pre_results_freeze": "freeze_material_hash",
    "benchmark_boundary": "benchmark_boundary_hash",
    "stage_boundaries": "stage_boundaries_hash",
    "qualification_protocol": "protocol_boundary_hash",
    "candidate_matrix": "candidate_matrix_hash",
    "candidate_execution_contract": "execution_contract_hash",
    "prompt_authority": "prompt_authority_hash",
    "call_budget": "call_budget_hash",
    "n3_axis": "n3_axis_hash",
    "p06_submission_requests": "request_set_hash",
    "p06_observation_bindings": "observation_bindings_hash",
    "n3_provider_fixtures": "fixture_set_hash",
    "rung_collection": "rung_collection_hash",
}


def load_and_validate_v135_freeze(
    *,
    paths: FrozenAuthorityPaths = FrozenAuthorityPaths(),
    document_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> FrozenAuthorities:
    """Load and cross-check the complete v1.3.5 execution-bearing freeze."""

    overrides = document_overrides or {}
    documents: dict[str, Mapping[str, Any]] = {}
    for name, path in paths.items():
        _assert_current_frozen_path(name, path)
        documents[name] = deepcopy(overrides[name]) if name in overrides else _read_json(path)

    for name, field_name in _SELF_HASH_FIELDS.items():
        document = documents[name]
        _require(
            document.get(field_name) == _self_hash(document, field_name),
            "PHASE9_V135_SELF_HASH_MISMATCH",
            f"{name}.{field_name} does not reproduce",
        )

    manifest = documents["freeze_manifest"]
    manifest_rows = {
        row["path"]: {
            "file_sha256": row["file_sha256"],
            "self_material_hash_field": row["self_material_hash_field"],
            "internal_material_hash": row["internal_material_hash"],
        }
        for row in manifest.get("artifacts", [])
    }
    _require(
        len(manifest_rows) == manifest.get("artifact_count") == 16,
        "PHASE9_V135_FREEZE_MANIFEST_MISMATCH",
        "the v1.3.5 freeze manifest population changed",
    )
    for relative, binding in manifest_rows.items():
        artifact = REPOSITORY_ROOT / relative
        _require(
            artifact.is_file() and _file_hash(artifact) == binding["file_sha256"],
            "PHASE9_V135_FROZEN_FILE_MISMATCH",
            f"frozen artifact bytes drifted: {relative}",
        )
        payload = _read_json(artifact)
        field_name = binding["self_material_hash_field"]
        _require(
            payload.get(field_name) == binding["internal_material_hash"],
            "PHASE9_V135_FREEZE_MANIFEST_MISMATCH",
            f"manifest internal hash drifted: {relative}",
        )

    expected_tree_files = set(manifest_rows) | {_repo_relative(paths.freeze_manifest)}
    observed_tree_files = {
        _repo_relative(path)
        for root in (V135_DEFINITION_ROOT, V135_REPORT_ROOT)
        for path in root.rglob("*")
        if path.is_file()
    }
    _require(
        observed_tree_files == expected_tree_files,
        "PHASE9_V135_FREEZE_MANIFEST_MISMATCH",
        "the immutable v1.3.5 tree population differs from its manifest",
    )

    freeze = documents["pre_results_freeze"]
    benchmark = documents["benchmark_boundary"]
    stages = documents["stage_boundaries"]
    protocol = documents["qualification_protocol"]
    matrix = documents["candidate_matrix"]
    contract = documents["candidate_execution_contract"]
    prompts = documents["prompt_authority"]
    budget = documents["call_budget"]
    n3_axis = documents["n3_axis"]
    p06_requests = documents["p06_submission_requests"]
    p06_observations = documents["p06_observation_bindings"]
    n3_fixtures = documents["n3_provider_fixtures"]
    rung = documents["rung_collection"]

    for name, document in documents.items():
        if name != "freeze_manifest" and "benchmark_version" in document:
            _require(
                document["benchmark_version"] == BENCHMARK_VERSION,
                "PHASE9_V135_VERSION_MISMATCH",
                f"{name} does not declare {BENCHMARK_VERSION}",
            )
    _require(
        protocol.get("protocol_version") == PROTOCOL_VERSION
        and freeze.get("protocol_version") == PROTOCOL_VERSION
        and matrix.get("protocol_version") == PROTOCOL_VERSION,
        "PHASE9_V135_VERSION_MISMATCH",
        "qualification protocol version is not v1.3.5",
    )

    semantic_bindings = {
        "pre_results_instrument_freeze_hash": freeze["freeze_material_hash"],
        "benchmark_boundary_hash": benchmark["benchmark_boundary_hash"],
        "stage_boundaries_hash": stages["stage_boundaries_hash"],
        "stage_boundary_hashes": stages["stage_boundary_hashes"],
        "protocol_boundary_hash": protocol["protocol_boundary_hash"],
        "candidate_matrix_hash": matrix["candidate_matrix_hash"],
        "candidate_execution_contract_hash": contract["execution_contract_hash"],
        "prompt_authority_hash": prompts["prompt_authority_hash"],
        "call_budget_hash": budget["call_budget_hash"],
        "n3_axis_hash": n3_axis["n3_axis_hash"],
        "p06_submission_request_set_hash": p06_requests["request_set_hash"],
        "p06_property_observation_bindings_hash": p06_observations["observation_bindings_hash"],
        "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
        "rung_collection_hash": rung["rung_collection_hash"],
        "corpus_package_boundary_hash": benchmark["corpus_package_boundary_hash"],
    }
    _require(
        semantic_bindings["benchmark_boundary_hash"] == EXPECTED_BENCHMARK_BOUNDARY_HASH
        and semantic_bindings["protocol_boundary_hash"] == EXPECTED_PROTOCOL_BOUNDARY_HASH
        and semantic_bindings["prompt_authority_hash"] == EXPECTED_PROMPT_AUTHORITY_HASH
        and semantic_bindings["candidate_execution_contract_hash"] == EXPECTED_EXECUTION_CONTRACT_HASH
        and semantic_bindings["n3_axis_hash"] == EXPECTED_N3_AXIS_HASH
        and semantic_bindings["corpus_package_boundary_hash"] == EXPECTED_CORPUS_BOUNDARY_HASH,
        "PHASE9_V135_EXPECTED_HASH_MISMATCH",
        "a top-level frozen v1.3.5 hash differs from the execution cutover",
    )

    cross_bindings = (
        (freeze, "global_benchmark_boundary_hash", benchmark, "benchmark_boundary_hash"),
        (freeze, "stage_boundaries_hash", stages, "stage_boundaries_hash"),
        (freeze, "protocol_boundary_hash", protocol, "protocol_boundary_hash"),
        (freeze, "candidate_matrix_hash", matrix, "candidate_matrix_hash"),
        (freeze, "candidate_execution_contract_hash", contract, "execution_contract_hash"),
        (freeze, "prompt_authority_hash", prompts, "prompt_authority_hash"),
        (freeze, "call_budget_hash", budget, "call_budget_hash"),
        (freeze, "n3_axis_hash", n3_axis, "n3_axis_hash"),
        (freeze, "p06_submission_request_set_hash", p06_requests, "request_set_hash"),
        (freeze, "p06_property_observation_bindings_hash", p06_observations, "observation_bindings_hash"),
        (freeze, "n3_provider_fixture_set_hash", n3_fixtures, "fixture_set_hash"),
        (freeze, "rung_collection_hash", rung, "rung_collection_hash"),
    )
    for left, left_key, right, right_key in cross_bindings:
        _require(
            left.get(left_key) == right.get(right_key),
            "PHASE9_V135_CROSS_BINDING_MISMATCH",
            f"{left_key} does not bind {right_key}",
        )
    _require(
        freeze.get("stage_boundary_hashes") == stages.get("stage_boundary_hashes")
        == contract.get("stage_boundary_hashes"),
        "PHASE9_V135_CROSS_BINDING_MISMATCH",
        "stage boundary maps disagree",
    )
    for source in (benchmark, protocol, matrix, contract, budget):
        for key, expected in semantic_bindings.items():
            if key in source:
                _require(
                    source[key] == expected,
                    "PHASE9_V135_CROSS_BINDING_MISMATCH",
                    f"{key} is stale in a load-bearing authority",
                )

    expected_candidates = {item.candidate_id: item for item in AUTHORIZED_CANDIDATES}
    matrix_rows = {row["candidate_id"]: row for row in matrix["candidates"]}
    contract_rows = {row["candidate_id"]: row for row in contract["candidate_identities"]}
    for candidate_id, candidate in expected_candidates.items():
        for row in (matrix_rows.get(candidate_id), contract_rows.get(candidate_id)):
            _require(
                row is not None
                and row["stage"] == candidate.stage
                and row["model"] == candidate.model
                and row["reasoning_effort"] == candidate.reasoning_effort
                and row["route_profile_id"] == candidate.route_profile_id
                and row["max_output_tokens"] == candidate.max_output_tokens,
                "PHASE9_V135_CANDIDATE_MISMATCH",
                f"candidate identity drifted: {candidate_id}",
            )
        _require(
            prompts["stages"][candidate.stage]["prompt_id"] == candidate.prompt_id,
            "PHASE9_V135_CANDIDATE_MISMATCH",
            f"prompt identity drifted: {candidate_id}",
        )

    required_budget_rows = {
        ("SEMANTIC", "P04", "SMOKE", "HIGH", "CASE_RUN"): 3,
        ("SEMANTIC", "P06", "SMOKE", "HIGH", "SUBMISSION_RUN"): 3,
        ("CONTRACTUAL_HARD_SAFETY", "P06", "N3_SAFETY_SMOKE", "HIGH", "EXPOSURE_RUN"): 3,
        ("SEMANTIC", "P07", "SMOKE", "HIGH", "CASE_RUN"): 18,
        ("SEMANTIC", "P09", "SMOKE", "HIGH", "CASE_RUN"): 3,
    }
    observed_budget_rows = {
        (row["axis"], row["stage"], row["split"], row["reasoning_rung"], row["unit"]): row["calls_if_this_rung_executes"]
        for row in budget["provider_call_budget"]["rows"]
        if row["reasoning_rung"] == "HIGH"
        and ((row["axis"] == "SEMANTIC" and row["split"] == "SMOKE")
             or (row["axis"] == "CONTRACTUAL_HARD_SAFETY" and row["split"] == "N3_SAFETY_SMOKE"))
    }
    _require(
        observed_budget_rows == required_budget_rows,
        "PHASE9_V135_CALL_BUDGET_MISMATCH",
        "the v1.3.5 HIGH-SMOKE provider budget is not 3/3/3/18/3",
    )
    _require(
        p06_requests.get("provider_call_unit") == "SUBMISSION_RUN"
        and p06_requests.get("submission_group_count") == 45
        and p06_observations.get("binding_count") == 71
        and p06_observations.get("candidate_scoring_property_count") == 69,
        "PHASE9_V135_P06_AUTHORITY_MISMATCH",
        "P06 grouped request or observation authority drifted",
    )
    _require(
        n3_fixtures.get("provider_unit") == "EXPOSURE_RUN"
        and n3_fixtures.get("runs_per_exposure") == 3
        and n3_axis.get("verdicts") == list(N3_SAFETY_VERDICTS),
        "PHASE9_V135_N3_AUTHORITY_MISMATCH",
        "N3 provider unit, cardinality, or verdict vocabulary drifted",
    )
    package = load_corpus_package()
    _require(
        package.package_hash == EXPECTED_CORPUS_BOUNDARY_HASH,
        "PHASE9_V135_CORPUS_BOUNDARY_MISMATCH",
        "the canonical synthetic corpus boundary drifted",
    )
    return FrozenAuthorities(
        documents=documents,
        semantic_bindings=semantic_bindings,
        frozen_artifacts=manifest_rows,
        freeze_manifest_file_sha256=_file_hash(paths.freeze_manifest),
    )


def load_and_validate_execution_boundary(
    authorities: FrozenAuthorities,
    *,
    boundary_override: Mapping[str, Any] | None = None,
    request_authority_override: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the separately versioned v2.0.3 boundary and request snapshot."""

    boundary = (
        deepcopy(boundary_override)
        if boundary_override is not None
        else _read_json(EXECUTION_BOUNDARY_PATH)
    )
    _require(
        boundary.get("execution_boundary_hash")
        == _self_hash(boundary, "execution_boundary_hash"),
        "PHASE9_EXECUTION_BOUNDARY_SELF_HASH_MISMATCH",
        "the v2 execution boundary does not reproduce",
    )
    _require(
        boundary.get("schema_version") == "phase9-execution-boundary/2.0.3"
        and boundary.get("execution_version") == PHASE9_EXECUTION_VERSION
        and boundary.get("benchmark_version") == BENCHMARK_VERSION
        and boundary.get("protocol_version") == PROTOCOL_VERSION
        and boundary.get("pricing_state")
        == "VERIFIED_CURRENT_OFFICIAL_PRICING"
        and boundary.get("authorization_state") == "NOT_AUTHORIZED"
        and boundary.get("billable_authorization") == "NONE",
        "PHASE9_EXECUTION_BOUNDARY_VERSION_MISMATCH",
        "the execution boundary names a different harness or instrument",
    )
    _require(
        boundary.get("short_context_authority")
        == {
            "runtime_route_max_input_tokens": OPENAI_MAX_INPUT_TOKENS,
            "official_long_context_threshold": LONG_CONTEXT_THRESHOLD,
            "route_cap_below_long_context_threshold": (
                OPENAI_MAX_INPUT_TOKENS < LONG_CONTEXT_THRESHOLD
            ),
            "long_context_pricing_authorized": False,
            "disposition_beyond_route_cap_or_threshold": (
                "FAIL_CLOSED_BEFORE_TRANSPORT"
            ),
        },
        "PHASE9_LONG_CONTEXT_OR_ROUTE_CAP_MISMATCH",
        "the boundary does not prove the runtime route cap is short-context",
    )
    _require(
        boundary.get("semantic_benchmark_bindings") == authorities.semantic_bindings,
        "PHASE9_EXECUTION_BOUNDARY_SEMANTIC_BINDING_MISMATCH",
        "the v2 boundary does not bind the loaded v1.3.5 freeze exactly",
    )
    _require(
        boundary.get("frozen_artifacts") == authorities.frozen_artifacts,
        "PHASE9_EXECUTION_BOUNDARY_FILE_BINDING_MISMATCH",
        "the v2 boundary frozen-file map differs from v1.3.5",
    )
    _require(
        boundary.get("freeze_manifest_file_sha256")
        == authorities.freeze_manifest_file_sha256,
        "PHASE9_EXECUTION_BOUNDARY_FILE_BINDING_MISMATCH",
        "the v1.3.5 freeze manifest bytes are not boundary-bound",
    )

    request_binding = boundary.get("request_authority", {})
    _require(
        request_binding.get("path") == _repo_relative(HIGH_SMOKE_REQUEST_AUTHORITY_PATH),
        "PHASE9_EXECUTION_REQUEST_AUTHORITY_PATH_MISMATCH",
        "the boundary points at a non-v2 request authority",
    )
    request_authority = (
        deepcopy(request_authority_override)
        if request_authority_override is not None
        else _read_json(HIGH_SMOKE_REQUEST_AUTHORITY_PATH)
    )
    _require(
        request_authority.get("request_authority_hash")
        == _self_hash(request_authority, "request_authority_hash"),
        "PHASE9_EXECUTION_REQUEST_AUTHORITY_SELF_HASH_MISMATCH",
        "the HIGH-SMOKE request authority does not reproduce",
    )
    if request_authority_override is None:
        _require(
            request_binding.get("file_sha256")
            == _file_hash(HIGH_SMOKE_REQUEST_AUTHORITY_PATH),
            "PHASE9_EXECUTION_REQUEST_AUTHORITY_FILE_MISMATCH",
            "the request-authority bytes differ from the execution boundary",
        )
    _require(
        request_binding.get("request_authority_hash")
        == request_authority.get("request_authority_hash"),
        "PHASE9_EXECUTION_REQUEST_AUTHORITY_HASH_MISMATCH",
        "the request authority is not the boundary-bound publication",
    )
    _require(
        request_authority.get("schema_version")
        == "phase9-high-smoke-request-authority/2.0.3"
        and request_authority.get("execution_version") == PHASE9_EXECUTION_VERSION
        and request_authority.get("benchmark_version") == BENCHMARK_VERSION
        and request_authority.get("protocol_version") == PROTOCOL_VERSION
        and request_authority.get("selection_depends_on_results") is False
        and request_authority.get("contains_held_out_material") is False,
        "PHASE9_EXECUTION_REQUEST_AUTHORITY_SCOPE_MISMATCH",
        "the request snapshot is not the result-independent v1.3.5 SMOKE surface",
    )

    predecessor = _validated_predecessor_execution()
    _require(
        boundary.get("predecessor_execution") == predecessor,
        "PHASE9_PREDECESSOR_EXECUTION_BINDING_MISMATCH",
        "v2.0.3 does not bind the exact consumed v2.0.2 history",
    )
    _require(
        canonical_hash(_request_population_projection(request_authority))
        == predecessor["request_population_hash"],
        "PHASE9_PREDECESSOR_EXECUTION_POPULATION_MISMATCH",
        "the v2.0.3 provider-visible population differs from v2.0.2",
    )

    pricing_binding = boundary.get("current_pricing", {})
    _require(
        pricing_binding.get("path") == _repo_relative(CURRENT_PRICING_PATH),
        "PHASE9_CURRENT_PRICING_BINDING_MISMATCH",
        "the execution boundary points at a non-v2.0.3 pricing artifact",
    )
    pricing = load_current_pricing_artifact(CURRENT_PRICING_PATH)
    _require(
        pricing_binding.get("file_sha256") == _file_hash(CURRENT_PRICING_PATH)
        and pricing_binding.get("pricing_snapshot_hash")
        == pricing.get("pricing_snapshot_hash"),
        "PHASE9_CURRENT_PRICING_BINDING_MISMATCH",
        "the current pricing artifact differs from the boundary binding",
    )
    _require(
        boundary.get("qualification_execution_policy")
        == QUALIFICATION_EXECUTION_POLICY,
        "PHASE9_QUALIFICATION_EXECUTION_POLICY_MISMATCH",
        "the executor-local no-P11 and call-accounting policy drifted",
    )

    source_bindings = boundary.get("source_bindings", {})
    _require(
        isinstance(source_bindings, Mapping)
        and set(source_bindings) == REQUIRED_SOURCE_BINDING_PATHS,
        "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH",
        "the v2.0.3 boundary does not bind the exact runtime dependency set",
    )
    inventory = boundary.get("runtime_dependency_inventory")
    _require(
        isinstance(inventory, list)
        and boundary.get("runtime_dependency_inventory_hash")
        == canonical_hash(inventory)
        and len(inventory) == len(REQUIRED_SOURCE_BINDING_PATHS),
        "PHASE9_EXECUTION_SOURCE_INVENTORY_MISMATCH",
        "the runtime dependency inventory is missing, duplicated, or unhashed",
    )
    inventory_by_path = {
        str(row.get("path")): row
        for row in inventory
        if isinstance(row, Mapping)
    }
    _require(
        len(inventory_by_path) == len(inventory)
        and set(inventory_by_path) == REQUIRED_SOURCE_BINDING_PATHS,
        "PHASE9_EXECUTION_SOURCE_INVENTORY_MISMATCH",
        "the runtime dependency inventory path set drifted",
    )
    for relative, expected in source_bindings.items():
        row = inventory_by_path[relative]
        path = (REPOSITORY_ROOT / relative).resolve()
        _require(
            row.get("path") == relative
            and row.get("role") == RUNTIME_SOURCE_BINDING_ROLES[relative]
            and row.get("file_sha256") == expected
            and
            path.is_relative_to(REPOSITORY_ROOT.resolve())
            and path.is_file()
            and _file_hash(path) == expected,
            "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH",
            f"execution source changed without a new boundary: {relative}",
        )
    _require(
        _repo_relative(Path(__file__)) in source_bindings,
        "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH",
        "the exact executor source is absent from the v2.0.3 boundary",
    )
    return dict(boundary), dict(request_authority)


def _model_request(row: Mapping[str, Any]) -> BaseModel:
    try:
        request_type = model_by_name(str(row["request_schema_name"]))
        request = request_type.model_validate(row["request"])
    except Exception as exc:  # noqa: BLE001 - malformed authority fails closed
        raise Phase9ExecutionError(
            "PHASE9_EXECUTION_REQUEST_CONTRACT_MISMATCH",
            f"cannot validate provider request {row.get('provider_identity')}",
        ) from exc
    _require(
        canonical_hash(request.model_dump(mode="json")) == row.get("request_hash"),
        "PHASE9_EXECUTION_REQUEST_HASH_MISMATCH",
        f"provider request drifted: {row.get('provider_identity')}",
    )
    return request


def build_high_smoke_cases(
    *,
    authorities: FrozenAuthorities,
    request_authority: Mapping[str, Any],
) -> tuple[ProviderCase, ...]:
    """Materialize only the provider-visible v1.3.5 HIGH-SMOKE population."""

    p06_document = authorities.documents["p06_submission_requests"]
    p06_observations = authorities.documents["p06_observation_bindings"]
    n3_document = authorities.documents["n3_provider_fixtures"]
    n3_axis = authorities.documents["n3_axis"]
    stages = authorities.documents["stage_boundaries"]
    cases: list[ProviderCase] = []

    for row in request_authority.get("semantic_cases", []):
        _require(
            row.get("axis") == "SEMANTIC"
            and row.get("split") == "SMOKE"
            and row.get("stage") in CANDIDATE_BY_STAGE,
            "PHASE9_HIGH_SMOKE_SCOPE_MISMATCH",
            "a semantic request is outside the SMOKE/HIGH stage surface",
        )
        request = _model_request(row)
        if row["stage"] == "P06":
            current_groups = [
                item for item in p06_document["requests"] if item["split"] == "SMOKE"
            ]
            _require(
                len(current_groups) == 1
                and row.get("p06_group_authority") == current_groups[0]
                and row["provider_identity"] == current_groups[0]["provider_case_id"],
                "PHASE9_P06_GROUPED_SMOKE_MISMATCH",
                "P06 semantic SMOKE is not the frozen grouped submission request",
            )
            group = current_groups[0]
            _require(
                (
                    group["route_count"],
                    group["dimension_count"],
                    group["variant_count"],
                    group["template_count"],
                )
                == (2, 2, 2, 2)
                and group["request_hash"] == row["request_hash"],
                "PHASE9_P06_GROUPED_SMOKE_MISMATCH",
                "P06 grouped SMOKE lost its complete two-route surface",
            )
            current_bindings = sorted(
                (
                    item
                    for item in p06_observations["bindings"]
                    if item["provider_case_id"] == row["provider_identity"]
                ),
                key=lambda item: item["property_id"],
            )
            snapshotted_bindings = sorted(
                (item["p06_observation_binding"] for item in row["property_observations"]),
                key=lambda item: item["property_id"],
            )
            _require(
                current_bindings == snapshotted_bindings and len(current_bindings) == 2,
                "PHASE9_P06_OBSERVATION_BINDING_MISMATCH",
                "P06 grouped SMOKE observations are not current v1.3.5 bindings",
            )
            provider_unit = "SUBMISSION_RUN"
        else:
            provider_unit = "CASE_RUN"
        _require(
            row.get("provider_unit") == provider_unit,
            "PHASE9_HIGH_SMOKE_PROVIDER_UNIT_MISMATCH",
            f"wrong provider unit for {row['provider_identity']}",
        )
        cases.append(
            ProviderCase(
                axis="SEMANTIC",
                stage=row["stage"],
                split="SMOKE",
                provider_unit=provider_unit,
                provider_identity=row["provider_identity"],
                candidate=CANDIDATE_BY_STAGE[row["stage"]],
                request=request,
                request_hash=row["request_hash"],
                frozen_input_hash=row.get("input_hash"),
                fixture_id=row["fixture_id"],
                property_observations=tuple(row["property_observations"]),
            )
        )

    for row in request_authority.get("n3_exposures", []):
        _require(
            row.get("axis") == "CONTRACTUAL_HARD_SAFETY"
            and row.get("stage") == "P06"
            and row.get("split") == "N3_SAFETY_SMOKE"
            and row.get("provider_unit") == "EXPOSURE_RUN",
            "PHASE9_N3_SAFETY_SMOKE_SCOPE_MISMATCH",
            "an N3 request is outside the preregistered SAFETY_SMOKE exposure",
        )
        current = [
            item
            for item in n3_document["fixtures"]
            if item["n3_split"] == "N3_SAFETY_SMOKE"
        ]
        _require(
            len(current) == 1
            and row.get("published_fixture_authority") == current[0]
            and row["provider_identity"] == current[0]["n3_provider_fixture_id"]
            and row["exposure_pseudonym"] == current[0]["exposure_id"]
            and row["request_hash"] == current[0]["provider_request_hash"],
            "PHASE9_N3_SAFETY_SMOKE_AUTHORITY_MISMATCH",
            "N3 SAFETY_SMOKE is not the frozen v1.3.5 provider fixture",
        )
        identities = n3_document["fixture_run_identities"][row["provider_identity"]]
        _require(
            identities
            == [
                {"exposure_pseudonym": row["exposure_pseudonym"], "run_index": index}
                for index in (1, 2, 3)
            ],
            "PHASE9_N3_RUN_IDENTITY_MISMATCH",
            "N3 exposure/run identities are not exactly 1,2,3",
        )
        _require(
            row.get("exposure_selector") == n3_axis["selectors"]["safety_smoke"]
            and row.get("p06_stage_boundary_hash")
            == stages["stage_boundary_hashes"]["P06"]
            and row.get("p06_field_authority_hash")
            == stages["stages"]["P06"]["field_authority_hash"]
            and row.get("n3_gate_source_hash") == n3_axis["gate_source_hash"],
            "PHASE9_N3_PACKET_AUTHORITY_MISMATCH",
            "N3 blind-packet authority is stale",
        )
        request = _model_request(row)
        cases.append(
            ProviderCase(
                axis="CONTRACTUAL_HARD_SAFETY",
                stage="P06",
                split="N3_SAFETY_SMOKE",
                provider_unit="EXPOSURE_RUN",
                provider_identity=row["provider_identity"],
                candidate=CANDIDATE_BY_STAGE["P06"],
                request=request,
                request_hash=row["request_hash"],
                frozen_input_hash=None,
                fixture_id=row["provider_identity"],
                exposure_pseudonym=row["exposure_pseudonym"],
                n3_packet_authority={
                    "route_context": row["route_context"],
                    "model_visible_evidence": row["model_visible_evidence"],
                    "exposure_selector": row["exposure_selector"],
                    "p06_stage_boundary_hash": row["p06_stage_boundary_hash"],
                    "p06_field_authority_hash": row["p06_field_authority_hash"],
                    "n3_gate_source_hash": row["n3_gate_source_hash"],
                },
            )
        )

    semantic_counts: dict[str, int] = {}
    for case in cases:
        if case.axis == "SEMANTIC":
            semantic_counts[case.stage] = semantic_counts.get(case.stage, 0) + 1
    _require(
        semantic_counts == {"P04": 1, "P06": 1, "P07": 6, "P09": 1}
        and sum(case.axis == "CONTRACTUAL_HARD_SAFETY" for case in cases) == 1,
        "PHASE9_HIGH_SMOKE_CASE_POPULATION_MISMATCH",
        "HIGH-SMOKE must contain 9 semantic cases plus one N3 exposure",
    )
    return tuple(
        sorted(
            cases,
            key=lambda item: (
                {"P04": 0, "P06": 1, "P07": 2, "P09": 3}[item.stage],
                1 if item.axis == "CONTRACTUAL_HARD_SAFETY" else 0,
                item.provider_identity,
            ),
        )
    )


def build_high_smoke_plan(
    cases: Sequence[ProviderCase], *, boundary: Mapping[str, Any]
) -> tuple[tuple[LogicalCall, ...], dict[str, Any]]:
    calls: list[LogicalCall] = []
    for case in cases:
        for run_index in (1, 2, 3):
            logical_id = (
                f"{case.axis}:{case.stage}:{case.provider_identity}:"
                f"{case.candidate.candidate_id}:run{run_index}"
            )
            calls.append(LogicalCall(logical_id, case, run_index))
    material = {
        "schema_version": "phase9-high-smoke-plan/2.0.3",
        "execution_version": PHASE9_EXECUTION_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "logical_calls": [call.identity() for call in calls],
    }
    plan = {**material, "plan_hash": canonical_hash(material)}
    ordered_population_hash = canonical_hash(material["logical_calls"])
    decomposition: dict[str, int] = {}
    for call in calls:
        identity = call.identity()
        key = "/".join(
            (
                identity["axis"],
                identity["stage"],
                identity["split"],
                identity["reasoning_rung"],
            )
        )
        decomposition[key] = decomposition.get(key, 0) + 1

    frozen_plan = boundary.get("high_smoke_plan", {})
    _require(
        len(calls) == AUTHORIZED_PRIMARY_LOGICAL_CALLS
        and len({call.logical_call_id for call in calls}) == len(calls)
        and decomposition == EXPECTED_PLAN_DECOMPOSITION
        and frozen_plan.get("primary_provider_calls") == len(calls)
        and frozen_plan.get("decomposition") == decomposition
        and frozen_plan.get("plan_hash") == plan["plan_hash"]
        and frozen_plan.get("ordered_logical_call_population_hash")
        == ordered_population_hash
        and ordered_population_hash
        == EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH
        and boundary.get("predecessor_execution", {}).get(
            "ordered_logical_call_population_hash"
        )
        == ordered_population_hash
        and frozen_plan.get("k") == 3
        and frozen_plan.get("held_out_in_plan") is False
        and frozen_plan.get("result_dependent_selection") is False,
        "PHASE9_HIGH_SMOKE_PLAN_MISMATCH",
        "the exact boundary-bound 30-call HIGH-SMOKE plan did not reproduce",
    )
    _require(
        all(
            call.case.split in {"SMOKE", "N3_SAFETY_SMOKE"}
            and call.case.candidate.reasoning_effort == "HIGH"
            and call.case.candidate.candidate_id not in FORBIDDEN_CANDIDATE_IDS
            for call in calls
        ),
        "PHASE9_HIGH_SMOKE_FORBIDDEN_SURFACE_REACHABLE",
        "CORE, held-out, XHIGH, MAX, or a forbidden candidate is reachable",
    )
    return tuple(calls), plan


def validate_live_prompt_authority(
    authorities: FrozenAuthorities,
    *,
    live_specs: Mapping[str, PromptSpec] = PROMPT_SPECS,
) -> dict[str, Any]:
    try:
        return assert_live_prompt_authority(
            authorities.documents["prompt_authority"], live_specs=live_specs
        )
    except QualificationPromptMismatch as exc:
        raise Phase9ExecutionError(
            "PHASE9_EXECUTABLE_PROMPT_AUTHORITY_MISMATCH", str(exc)
        ) from exc


def prepare_phase9_execution(
    *,
    authority_paths: FrozenAuthorityPaths = FrozenAuthorityPaths(),
    authority_document_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    boundary_override: Mapping[str, Any] | None = None,
    request_authority_override: Mapping[str, Any] | None = None,
    live_specs: Mapping[str, PromptSpec] = PROMPT_SPECS,
) -> PreparedExecution:
    """Validate freeze -> execution boundary -> plan -> live prompts, offline."""

    authorities = load_and_validate_v135_freeze(
        paths=authority_paths, document_overrides=authority_document_overrides
    )
    boundary, request_authority = load_and_validate_execution_boundary(
        authorities,
        boundary_override=boundary_override,
        request_authority_override=request_authority_override,
    )
    cases = build_high_smoke_cases(
        authorities=authorities, request_authority=request_authority
    )
    calls, plan = build_high_smoke_plan(cases, boundary=boundary)
    validate_live_prompt_authority(authorities, live_specs=live_specs)
    return PreparedExecution(
        authorities=authorities,
        boundary=boundary,
        request_authority=request_authority,
        cases=cases,
        calls=calls,
        plan=plan,
    )


def _pricing_decimal(value: Any, *, model: str, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise Phase9ExecutionError(
            "PHASE9_CURRENT_PRICING_INVALID",
            f"invalid token pricing for {model}.{field_name}",
        )
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Phase9ExecutionError(
            "PHASE9_CURRENT_PRICING_INVALID",
            f"invalid token pricing for {model}.{field_name}",
        ) from exc
    _require(
        parsed.is_finite() and parsed >= 0,
        "PHASE9_CURRENT_PRICING_INVALID",
        f"invalid token pricing for {model}.{field_name}",
    )
    return parsed


def _validate_current_pricing_document(
    pricing: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        pricing.get("pricing_snapshot_hash")
        == _self_hash(pricing, "pricing_snapshot_hash"),
        "PHASE9_CURRENT_PRICING_SELF_HASH_MISMATCH",
        "the supplied current-pricing artifact does not reproduce",
    )
    try:
        retrieved_at = datetime.fromisoformat(
            str(pricing["retrieved_at"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise Phase9ExecutionError(
            "PHASE9_CURRENT_PRICING_INVALID",
            "the current-pricing retrieval timestamp is invalid",
        ) from exc
    _require(
        pricing.get("schema_version") == "phase9-current-pricing/2.0.3"
        and pricing.get("execution_version") == PHASE9_EXECUTION_VERSION
        and pricing.get("status") == "VERIFIED_CURRENT_OFFICIAL_PRICING"
        and pricing.get("processing_tier") == "STANDARD"
        and pricing.get("official_source_urls")
        == list(OFFICIAL_PRICING_SOURCE_URLS)
        and retrieved_at.utcoffset() == UTC.utcoffset(retrieved_at)
        and pricing.get("long_context_threshold") == LONG_CONTEXT_THRESHOLD
        and pricing.get("long_context_pricing_authorized") is False
        and pricing.get("responses_api_supported") is True
        and pricing.get("structured_outputs_supported") is True
        and pricing.get("reasoning_high_supported") is True
        and pricing.get("non_billable") is True
        and pricing.get("authorization_state") == "NOT_AUTHORIZED"
        and pricing.get("billable_authorization") == "NONE",
        "PHASE9_CURRENT_PRICING_INVALID",
        "pricing is not the non-billable current official v2.0.3 authority",
    )
    rule = pricing.get("cache_write_pricing_rule", {})
    _require(
        isinstance(rule, Mapping)
        and _pricing_decimal(
            rule.get("multiplier"), model="ALL", field_name="multiplier"
        )
        == CACHE_WRITE_PRICE_MULTIPLIER
        and rule.get("formula")
        == (
            "cache_write_per_million_usd == "
            "1.25 * input_per_million_usd"
        ),
        "PHASE9_CURRENT_PRICING_CACHE_WRITE_RULE_MISMATCH",
        "cache-write pricing is not bound to 1.25 times uncached input",
    )
    rows = pricing.get("models", {})
    required_models = {item.model for item in AUTHORIZED_CANDIDATES}
    _require(
        isinstance(rows, Mapping)
        and set(rows) == required_models
        == set(EXPECTED_CURRENT_PRICING_RATES),
        "PHASE9_CURRENT_PRICING_INVALID",
        "pricing must bind exactly the HIGH candidate models",
    )
    for model, expected_rates in EXPECTED_CURRENT_PRICING_RATES.items():
        row = rows[model]
        _require(
            isinstance(row, Mapping)
            and row.get("model_id") == model
            and row.get("model_page_url")
            == f"https://developers.openai.com/api/docs/models/{model}"
            and row.get("availability") == "AVAILABLE_OPENAI_API"
            and row.get("processing_tier") == "STANDARD"
            and row.get("responses_api_endpoint") == "v1/responses"
            and row.get("responses_api_supported") is True
            and row.get("structured_outputs_supported") is True
            and row.get("reasoning_high_supported") is True,
            "PHASE9_CURRENT_PRICING_INVALID",
            f"official model availability evidence is incomplete for {model}",
        )
        observed_rates = {
            field_name: _pricing_decimal(
                row.get(field_name), model=model, field_name=field_name
            )
            for field_name in expected_rates
        }
        _require(
            observed_rates == expected_rates,
            "PHASE9_CURRENT_PRICING_INVALID",
            f"current official pricing differs for {model}",
        )
        _require(
            observed_rates["cache_write_per_million_usd"]
            == (
                observed_rates["input_per_million_usd"]
                * CACHE_WRITE_PRICE_MULTIPLIER
            ),
            "PHASE9_CURRENT_PRICING_CACHE_WRITE_RULE_MISMATCH",
            f"cache-write multiplier differs from 1.25 for {model}",
        )
    return dict(pricing)


def load_current_pricing_artifact(path: Path = CURRENT_PRICING_PATH) -> dict[str, Any]:
    """Load the non-billable current-pricing authority and fail closed."""

    if not path.is_file():
        raise Phase9ExecutionError(
            "PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION",
            "no current official pricing artifact is published for execution v2.0.3",
        )
    return _validate_current_pricing_document(_read_json(path))


def _round_cost(value: float) -> float:
    return round(value, 8)


def _aggregate_cost_projection(
    rows: Sequence[Mapping[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row[key])
        aggregate = aggregates.setdefault(
            label,
            {
                "logical_calls": 0,
                "estimated_input_tokens": 0,
                "max_output_tokens": 0,
                "primary_call_conservative_reservation_usd": 0.0,
                "max_technical_retry_increment_usd": 0.0,
                "absolute_retry_inclusive_reservation_usd": 0.0,
            },
        )
        aggregate["logical_calls"] += 1
        aggregate["estimated_input_tokens"] += int(row["estimated_input_tokens"])
        aggregate["max_output_tokens"] += int(row["max_output_tokens"])
        for cost_key in (
            "primary_call_conservative_reservation_usd",
            "max_technical_retry_increment_usd",
            "absolute_retry_inclusive_reservation_usd",
        ):
            aggregate[cost_key] += float(row[cost_key])
    for aggregate in aggregates.values():
        for cost_key in (
            "primary_call_conservative_reservation_usd",
            "max_technical_retry_increment_usd",
            "absolute_retry_inclusive_reservation_usd",
        ):
            aggregate[cost_key] = _round_cost(float(aggregate[cost_key]))
    return dict(sorted(aggregates.items()))


def _cap_with_headroom(value: float, *, quantum: str) -> float:
    amount = Decimal(str(value)) * Decimal("1.10")
    return float(amount.quantize(Decimal(quantum), rounding=ROUND_CEILING))


def build_pre_authorization_cost_projection(
    prepared: PreparedExecution,
    pricing: Mapping[str, Any],
) -> dict[str, Any]:
    """Price the exact prepared 30-call population without authorizing spend."""

    validated_pricing = _validate_current_pricing_document(pricing)
    rows: list[dict[str, Any]] = []
    route_caps: set[int] = set()
    for call in prepared.calls:
        candidate = call.case.candidate
        spec = prompt_spec(candidate.prompt_id)
        envelope = _envelope_for(candidate.prompt_id, call.case.request)
        estimated_input_tokens = estimate_openai_input_tokens(
            spec, call.case.request, envelope
        )
        route = build_openai_routes(
            max_call_cost_usd=1_000_000.0,
            route_profile_id=candidate.route_profile_id,
        )[candidate.prompt_id]
        route_caps.add(route.max_input_tokens)
        _require(
            route.max_input_tokens == OPENAI_MAX_INPUT_TOKENS
            and route.max_input_tokens < LONG_CONTEXT_THRESHOLD
            and estimated_input_tokens <= route.max_input_tokens
            and candidate.max_output_tokens == route.max_output_tokens,
            "PHASE9_LONG_CONTEXT_OR_ROUTE_CAP_MISMATCH",
            f"the prepared request is outside the short-context route for {call.logical_call_id}",
        )
        uncached_input = _estimate_cost(
            validated_pricing,
            model=candidate.model,
            input_tokens=estimated_input_tokens,
            output_tokens=0,
        )
        cache_write_input = _estimate_cost(
            validated_pricing,
            model=candidate.model,
            input_tokens=estimated_input_tokens,
            output_tokens=0,
            cache_write_input_tokens=estimated_input_tokens,
        )
        max_output = _estimate_cost(
            validated_pricing,
            model=candidate.model,
            input_tokens=0,
            output_tokens=candidate.max_output_tokens,
        )
        primary = _estimate_cost(
            validated_pricing,
            model=candidate.model,
            input_tokens=estimated_input_tokens,
            output_tokens=candidate.max_output_tokens,
            cache_write_input_tokens=estimated_input_tokens,
        )
        _require(
            cache_write_input > uncached_input
            and primary == _round_cost(cache_write_input + max_output),
            "PHASE9_COST_PROJECTION_ACCOUNTING_MISMATCH",
            f"cache-write reservation did not reproduce for {call.logical_call_id}",
        )
        rows.append(
            {
                "logical_call_id": call.logical_call_id,
                "axis": call.case.axis,
                "stage": call.case.stage,
                "provider_identity": call.case.provider_identity,
                "candidate_id": candidate.candidate_id,
                "model": candidate.model,
                "run_index": call.run_index,
                "estimated_input_tokens": estimated_input_tokens,
                "max_output_tokens": candidate.max_output_tokens,
                "runtime_route_max_input_tokens": route.max_input_tokens,
                "long_context_threshold": LONG_CONTEXT_THRESHOLD,
                "context_classification": "SHORT_CONTEXT_STANDARD",
                "uncached_input_worst_case_cost_usd": uncached_input,
                "cache_write_input_worst_case_cost_usd": cache_write_input,
                "max_output_cost_usd": max_output,
                "primary_call_conservative_reservation_usd": primary,
                "max_technical_retry_increment_usd": primary,
                "absolute_retry_inclusive_reservation_usd": _round_cost(
                    primary * 2
                ),
            }
        )
    ordered_hash = canonical_hash([call.identity() for call in prepared.calls])
    _require(
        len(rows) == AUTHORIZED_PRIMARY_LOGICAL_CALLS
        and ordered_hash == EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH,
        "PHASE9_COST_PROJECTION_POPULATION_MISMATCH",
        "the cost projection is not the exact frozen 30-call population",
    )
    by_stage = _aggregate_cost_projection(rows, "stage")
    by_candidate = _aggregate_cost_projection(rows, "candidate_id")
    by_model = _aggregate_cost_projection(rows, "model")
    primary_total = _round_cost(
        sum(
            float(row["primary_call_conservative_reservation_usd"])
            for row in rows
        )
    )
    retry_increment = _round_cost(
        sum(float(row["max_technical_retry_increment_usd"]) for row in rows)
    )
    retry_inclusive = _round_cost(primary_total + retry_increment)
    per_call_caps = {
        candidate.candidate_id: _cap_with_headroom(
            max(
                float(row["primary_call_conservative_reservation_usd"])
                for row in rows
                if row["candidate_id"] == candidate.candidate_id
            ),
            quantum="0.001",
        )
        for candidate in AUTHORIZED_CANDIDATES
    }
    rung_caps = {
        candidate.candidate_id: {
            "primary_usd": _cap_with_headroom(
                float(
                    by_candidate[candidate.candidate_id][
                        "primary_call_conservative_reservation_usd"
                    ]
                ),
                quantum="0.01",
            ),
            "retry_inclusive_usd": _cap_with_headroom(
                float(
                    by_candidate[candidate.candidate_id][
                        "absolute_retry_inclusive_reservation_usd"
                    ]
                ),
                quantum="0.01",
            ),
        }
        for candidate in AUTHORIZED_CANDIDATES
    }
    material = {
        "schema_version": "phase9-pre-authorization-cost-projection/2.0.3",
        "execution_version": PHASE9_EXECUTION_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "status": "PROPOSED_CAPS_NOT_AUTHORIZED",
        "authorization_state": "NOT_AUTHORIZED",
        "billable_authorization": "NONE",
        "pricing_snapshot_hash": validated_pricing["pricing_snapshot_hash"],
        "high_smoke_plan_hash": prepared.plan["plan_hash"],
        "request_authority_hash": prepared.request_authority[
            "request_authority_hash"
        ],
        "ordered_logical_call_population_hash": ordered_hash,
        "processing_tier": "STANDARD",
        "projection_basis": {
            "input_token_estimator": (
                "comprehension_verification.model_gateway.openai_routes."
                "estimate_openai_input_tokens"
            ),
            "input_reservation": "ALL_ESTIMATED_INPUT_TOKENS_AS_CACHE_WRITE",
            "output_reservation": "FROZEN_CANDIDATE_MAX_OUTPUT_TOKENS",
            "provider_usage_dimensions": [
                "input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
            ],
        },
        "mechanical_short_context_proof": {
            "runtime_route_max_input_tokens": OPENAI_MAX_INPUT_TOKENS,
            "official_long_context_threshold": LONG_CONTEXT_THRESHOLD,
            "route_cap_below_long_context_threshold": (
                OPENAI_MAX_INPUT_TOKENS < LONG_CONTEXT_THRESHOLD
            ),
            "observed_route_caps": sorted(route_caps),
            "maximum_estimated_input_tokens": max(
                int(row["estimated_input_tokens"]) for row in rows
            ),
            "all_estimated_inputs_within_route_cap": True,
            "long_context_logical_calls": 0,
            "long_context_pricing_authorized": False,
            "disposition_beyond_route_cap_or_threshold": (
                "FAIL_CLOSED_BEFORE_TRANSPORT"
            ),
        },
        "logical_calls": rows,
        "aggregates": {
            "by_stage": by_stage,
            "by_candidate": by_candidate,
            "by_model": by_model,
            "all_30_primary_calls": {
                "logical_calls": len(rows),
                "primary_call_conservative_reservation_usd": primary_total,
            },
        },
        "technical_retry_reserve": {
            "max_technical_retries_per_logical_call": (
                MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL
            ),
            "retryable_technical_codes": sorted(RETRYABLE_TECHNICAL_CODES),
            "derivation": (
                "ONE_FULL_CONSERVATIVE_CALL_RESERVATION_PER_LOGICAL_CALL"
            ),
            "A_PRIMARY_30_CALL_RESERVATION_USD": primary_total,
            "B_MAX_TECHNICAL_RETRY_INCREMENT_USD": retry_increment,
            "C_ABSOLUTE_RETRY_INCLUSIVE_RESERVATION_USD": retry_inclusive,
        },
        "proposed_caps": {
            "status": "PROPOSED_CAPS_NOT_AUTHORIZED",
            "headroom_policy": {
                "multiplier": 1.10,
                "per_call_round_up_usd": 0.001,
                "rung_and_outer_round_up_usd": 0.01,
                "explanation": (
                    "10_PERCENT_DETERMINISTIC_HEADROOM_ROUNDED_UP; "
                    "NO_SPEND_AUTHORIZED"
                ),
            },
            "per_call_cap_by_candidate_usd": per_call_caps,
            "per_candidate_rung_caps_usd": rung_caps,
            "outer_primary_cap_usd": _cap_with_headroom(
                primary_total, quantum="0.01"
            ),
            "outer_retry_inclusive_cap_usd": _cap_with_headroom(
                retry_inclusive, quantum="0.01"
            ),
        },
        "safety_counters": {
            "provider_calls": 0,
            "adjudicator_calls": 0,
            "credential_resolutions": 0,
            "transport_factory_calls": 0,
            "real_provider_transport": False,
            "pricing_snapshot": "VERIFIED_CURRENT_OFFICIAL_PRICING",
            "high_smoke": "NOT_EXECUTED",
            "billable_authorization": "NONE",
        },
    }
    return {**material, "cost_projection_hash": canonical_hash(material)}


def load_and_validate_cost_projection(
    *,
    prepared: PreparedExecution,
    pricing: Mapping[str, Any],
    path: Path = COST_PROJECTION_PATH,
) -> dict[str, Any]:
    if not path.is_file():
        raise Phase9ExecutionError(
            "PHASE9_COST_PROJECTION_REQUIRED_BEFORE_AUTHORIZATION",
            "the deterministic v2.0.3 cost projection is not published",
        )
    projection = _read_json(path)
    _require(
        projection.get("cost_projection_hash")
        == _self_hash(projection, "cost_projection_hash"),
        "PHASE9_COST_PROJECTION_SELF_HASH_MISMATCH",
        "the supplied cost projection does not reproduce",
    )
    expected = build_pre_authorization_cost_projection(prepared, pricing)
    _require(
        projection == expected,
        "PHASE9_COST_PROJECTION_MISMATCH",
        "the published projection differs from the real prepared 30-call path",
    )
    return projection


def authorization_requirements(
    prepared: PreparedExecution,
    pricing: Mapping[str, Any],
    cost_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return exact material a later explicit authorization must bind.

    This is a requirements document, not a billable authorization and cannot be
    consumed by the executor.
    """

    projection = (
        dict(cost_projection)
        if cost_projection is not None
        else build_pre_authorization_cost_projection(prepared, pricing)
    )
    retry = projection["technical_retry_reserve"]
    return {
        "schema_version": "phase9-billable-authorization-requirements/2.0.3",
        "authorization_state": "NOT_AUTHORIZED_TEMPLATE",
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "execution_version": PHASE9_EXECUTION_VERSION,
        "execution_boundary_hash": prepared.boundary["execution_boundary_hash"],
        "high_smoke_plan_hash": prepared.plan["plan_hash"],
        **dict(prepared.authorities.semantic_bindings),
        "pricing_snapshot_hash": pricing["pricing_snapshot_hash"],
        "cost_projection_hash": projection["cost_projection_hash"],
        "primary_provider_calls": AUTHORIZED_PRIMARY_LOGICAL_CALLS,
        "max_technical_retries_per_logical_call": (
            MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL
        ),
        "absolute_provider_request_ceiling": (
            AUTHORIZED_PRIMARY_LOGICAL_CALLS
            * (1 + MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL)
        ),
        "primary_30_call_reservation_usd": retry[
            "A_PRIMARY_30_CALL_RESERVATION_USD"
        ],
        "max_technical_retry_increment_usd": retry[
            "B_MAX_TECHNICAL_RETRY_INCREMENT_USD"
        ],
        "absolute_retry_inclusive_reservation_usd": retry[
            "C_ABSOLUTE_RETRY_INCLUSIVE_RESERVATION_USD"
        ],
        "candidate_identities": [
            {
                "stage": item.stage,
                "candidate_id": item.candidate_id,
                "model": item.model,
                "reasoning_rung": item.reasoning_effort,
                "route_profile_id": item.route_profile_id,
                "prompt_id": item.prompt_id,
                "max_output_tokens": item.max_output_tokens,
            }
            for item in AUTHORIZED_CANDIDATES
        ],
        "logical_call_identities": [call.identity() for call in prepared.calls],
        "required_future_fields": [
            "authorization_id",
            "approved_by",
            "approved_at",
            "expires_at",
            "per_call_caps_usd",
            "rung_primary_caps_usd",
            "rung_retry_inclusive_caps_usd",
            "outer_primary_cap_usd",
            "outer_retry_inclusive_cap_usd",
            "ledger_path",
            "authorization_hash",
        ],
        "excluded_scope": list(EXCLUDED_FROM_AUTHORIZATION),
    }


def load_and_validate_authorization(
    *,
    path: Path,
    prepared: PreparedExecution,
    pricing: Mapping[str, Any],
    cost_projection: Mapping[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        raise Phase9ExecutionError(
            "EXPLICIT_HASH_BOUND_AUTHORIZATION_REQUIRED",
            "no billable authorization is published for execution v2.0.3",
        )
    authorization = _read_json(path)
    _require(
        authorization.get("authorization_hash")
        == _self_hash(authorization, "authorization_hash"),
        "PHASE9_AUTHORIZATION_SELF_HASH_MISMATCH",
        "the billable authorization does not reproduce",
    )
    requirements = authorization_requirements(
        prepared, pricing, cost_projection=cost_projection
    )
    exact_fields = {
        key: value
        for key, value in requirements.items()
        if key
        not in {
            "schema_version",
            "authorization_state",
            "required_future_fields",
        }
    }
    for key, expected in exact_fields.items():
        _require(
            authorization.get(key) == expected,
            "PHASE9_AUTHORIZATION_BINDING_MISMATCH",
            f"authorization does not exactly bind {key}",
        )
    _require(
        authorization.get("schema_version")
        == "phase9-billable-authorization/2.0.3"
        and authorization.get("authorization_state") == "EXPLICITLY_APPROVED"
        and authorization.get("billable_authorization") == "EXPLICIT"
        and authorization.get("primary_provider_calls") == 30
        and authorization.get("absolute_provider_request_ceiling") == 60,
        "PHASE9_AUTHORIZATION_INVALID",
        "authorization is not an explicit retry-bounded execution-v2.0.3 approval",
    )
    try:
        expires_at = datetime.fromisoformat(
            str(authorization["expires_at"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise Phase9ExecutionError(
            "PHASE9_AUTHORIZATION_INVALID", "authorization expiry is invalid"
        ) from exc
    _require(
        expires_at > datetime.now(UTC),
        "PHASE9_AUTHORIZATION_EXPIRED",
        "billable authorization has expired",
    )
    candidate_ids = {item.candidate_id for item in AUTHORIZED_CANDIDATES}
    for key in (
        "per_call_caps_usd",
        "rung_primary_caps_usd",
        "rung_retry_inclusive_caps_usd",
    ):
        caps = authorization.get(key, {})
        _require(
            isinstance(caps, Mapping)
            and set(caps) == candidate_ids
            and all(
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and value > 0
                for value in caps.values()
            ),
            "PHASE9_AUTHORIZATION_INVALID",
            f"{key} must provide positive caps for exactly the HIGH candidates",
        )
    proposed = cost_projection["proposed_caps"]
    by_candidate = cost_projection["aggregates"]["by_candidate"]
    per_call_projection = {
        candidate_id: max(
            float(row["primary_call_conservative_reservation_usd"])
            for row in cost_projection["logical_calls"]
            if row["candidate_id"] == candidate_id
        )
        for candidate_id in candidate_ids
    }
    for candidate_id in candidate_ids:
        _require(
            per_call_projection[candidate_id]
            <= float(authorization["per_call_caps_usd"][candidate_id])
            <= float(
                proposed["per_call_cap_by_candidate_usd"][candidate_id]
            )
            and float(
                by_candidate[candidate_id][
                    "primary_call_conservative_reservation_usd"
                ]
            )
            <= float(authorization["rung_primary_caps_usd"][candidate_id])
            <= float(
                proposed["per_candidate_rung_caps_usd"][candidate_id][
                    "primary_usd"
                ]
            )
            and float(
                by_candidate[candidate_id][
                    "absolute_retry_inclusive_reservation_usd"
                ]
            )
            <= float(
                authorization["rung_retry_inclusive_caps_usd"][candidate_id]
            )
            <= float(
                proposed["per_candidate_rung_caps_usd"][candidate_id][
                    "retry_inclusive_usd"
                ]
            ),
            "PHASE9_AUTHORIZATION_CAP_MISMATCH",
            f"authorization caps are outside the projected range for {candidate_id}",
        )
    retry = cost_projection["technical_retry_reserve"]
    _require(
        not isinstance(authorization.get("outer_primary_cap_usd"), bool)
        and isinstance(authorization.get("outer_primary_cap_usd"), (int, float))
        and not isinstance(
            authorization.get("outer_retry_inclusive_cap_usd"), bool
        )
        and isinstance(
            authorization.get("outer_retry_inclusive_cap_usd"), (int, float)
        )
        and float(retry["A_PRIMARY_30_CALL_RESERVATION_USD"])
        <= float(authorization["outer_primary_cap_usd"])
        <= float(proposed["outer_primary_cap_usd"])
        and float(retry["C_ABSOLUTE_RETRY_INCLUSIVE_RESERVATION_USD"])
        <= float(authorization["outer_retry_inclusive_cap_usd"])
        <= float(proposed["outer_retry_inclusive_cap_usd"]),
        "PHASE9_AUTHORIZATION_CAP_MISMATCH",
        "authorization outer caps are outside the projected range",
    )
    ledger_path = (
        REPOSITORY_ROOT / str(authorization.get("ledger_path", ""))
    ).resolve()
    ledger_root = (EXECUTION_REPORT_ROOT / "authorization_ledger").resolve()
    _require(
        ledger_path.is_relative_to(ledger_root),
        "PHASE9_AUTHORIZATION_INVALID",
        "authorization ledger path is outside the execution-v2.0.3 ledger root",
    )
    return authorization


def _claim_authorization_once(authorization: Mapping[str, Any]) -> Path:
    ledger_path = (REPOSITORY_ROOT / authorization["ledger_path"]).resolve()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "phase9-authorization-consumption/2.0.3",
        "authorization_id": authorization["authorization_id"],
        "authorization_hash": authorization["authorization_hash"],
        "execution_boundary_hash": authorization["execution_boundary_hash"],
        "high_smoke_plan_hash": authorization["high_smoke_plan_hash"],
        "consumed_at": _utc_now(),
        "state": "CONSUMED_EXACTLY_ONCE",
    }
    try:
        with ledger_path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise Phase9ExecutionError(
            "PHASE9_AUTHORIZATION_ALREADY_CONSUMED",
            "the exactly-once authorization ledger entry already exists",
        ) from exc
    return ledger_path


def default_adapter_factory(api_key: SecretStr) -> Any:
    return OpenAIResponsesAdapter(
        api_key=api_key,
        config=OpenAIAdapterConfig(
            request_timeout_seconds=OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
    )


def _estimate_cost(
    pricing: Mapping[str, Any],
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
) -> float:
    _require(
        pricing.get("long_context_threshold") == LONG_CONTEXT_THRESHOLD
        and pricing.get("long_context_pricing_authorized") is False,
        "PHASE9_LONG_CONTEXT_PRICING_NOT_AUTHORIZED",
        "only standard short-context pricing is authorized",
    )
    input_tokens = max(0, input_tokens)
    _require(
        input_tokens <= LONG_CONTEXT_THRESHOLD,
        "PHASE9_LONG_CONTEXT_PRICING_NOT_AUTHORIZED",
        "the request exceeds the standard short-context pricing threshold",
    )
    try:
        row = pricing["models"][model]
    except (KeyError, TypeError) as exc:
        raise Phase9ExecutionError(
            "PHASE9_CURRENT_PRICING_INVALID",
            f"no execution-v2.0.3 pricing row exists for {model}",
        ) from exc
    _require(
        isinstance(row, Mapping),
        "PHASE9_CURRENT_PRICING_INVALID",
        f"the execution-v2.0.3 pricing row is invalid for {model}",
    )
    input_rate = _pricing_decimal(
        row.get("input_per_million_usd"),
        model=model,
        field_name="input_per_million_usd",
    )
    cached_rate = _pricing_decimal(
        row.get("cached_input_per_million_usd"),
        model=model,
        field_name="cached_input_per_million_usd",
    )
    cache_write_rate = _pricing_decimal(
        row.get("cache_write_per_million_usd"),
        model=model,
        field_name="cache_write_per_million_usd",
    )
    output_rate = _pricing_decimal(
        row.get("output_per_million_usd"),
        model=model,
        field_name="output_per_million_usd",
    )
    _require(
        cache_write_rate == input_rate * CACHE_WRITE_PRICE_MULTIPLIER,
        "PHASE9_CURRENT_PRICING_CACHE_WRITE_RULE_MISMATCH",
        f"cache-write multiplier differs from 1.25 for {model}",
    )
    cached = min(input_tokens, max(0, cached_input_tokens))
    cache_write = min(input_tokens, max(0, cache_write_input_tokens))
    ordinary = max(0, input_tokens - cached - cache_write)
    return round(
        float(
            (
                ordinary * input_rate
                + cached * cached_rate
                + cache_write * cache_write_rate
                + max(0, output_tokens) * output_rate
            )
            / Decimal("1000000")
        ),
        8,
    )


_SAFE_PROVIDER_EXCEPTION_CLASSES: Final = frozenset(
    {
        "AuthenticationProviderError",
        "AuthorizationProviderError",
        "MalformedProviderResponseError",
        "ModelUnavailableProviderError",
        "PermanentProviderError",
        "ProviderBudgetError",
        "ProviderTimeoutError",
        "RateLimitProviderError",
        "SafetyBlockProviderError",
        "TransientProviderError",
    }
)
_SAFE_PROVIDER_REASON = re.compile(r"[A-Z][A-Z0-9_]{2,95}")
_SAFE_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_PROVIDER_SCHEMA_ERROR = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,95}")
_SAFE_PROVIDER_SCHEMA_PATH = re.compile(
    r"/(?:[A-Za-z0-9_*.-]+/)*[A-Za-z0-9_*.-]*"
)
_SAFE_PROVIDER_INVOCATION_FIELDS: Final = (
    "provider_invocation_index",
    "prompt_id",
    "provider_attempt",
    "status",
    "failure_code",
    "provider_reason_code",
    "provider_request_id_hash",
    "provider_exception_class",
    "provider_output_hash",
    "effective_model",
    "provider_schema_valid",
    "provider_schema_issues",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "estimated_cost_usd",
    "actual_cost_usd",
    "latency_ms",
)


def _safe_provider_schema_issues(value: Any) -> list[list[str]]:
    issues: list[list[str]] = []
    if not isinstance(value, (list, tuple)):
        return issues
    for item in value[:32]:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        error_type, path = item
        if (
            isinstance(error_type, str)
            and isinstance(path, str)
            and _SAFE_PROVIDER_SCHEMA_ERROR.fullmatch(error_type)
            and _SAFE_PROVIDER_SCHEMA_PATH.fullmatch(path)
        ):
            issues.append([error_type, path])
    return issues


def _safe_provider_exception_diagnostic(exc: BaseException) -> dict[str, str]:
    if not isinstance(exc, ProviderAdapterError):
        return {"failure_code": "ADAPTER_UNEXPECTED_EXCEPTION"}
    diagnostic = {"failure_code": "PROVIDER_ADAPTER_ERROR"}
    reason = getattr(exc, "reason_code", None)
    if isinstance(reason, str) and _SAFE_PROVIDER_REASON.fullmatch(reason):
        diagnostic["provider_reason_code"] = reason
    request_hash = getattr(exc, "request_id_hash", None)
    if isinstance(request_hash, str) and _SAFE_SHA256.fullmatch(request_hash):
        diagnostic["provider_request_id_hash"] = request_hash
    exception_class = type(exc).__name__
    if exception_class in _SAFE_PROVIDER_EXCEPTION_CLASSES:
        diagnostic["provider_exception_class"] = exception_class
    return diagnostic


def _safe_provider_invocation_evidence(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project content-free invocation diagnostics for durable manifests."""

    projected: list[dict[str, Any]] = []
    for row in rows:
        evidence = {
            key: deepcopy(row[key])
            for key in _SAFE_PROVIDER_INVOCATION_FIELDS
            if key in row
        }
        if "provider_schema_issues" in evidence:
            evidence["provider_schema_issues"] = _safe_provider_schema_issues(
                evidence["provider_schema_issues"]
            )
        for hash_field in (
            "provider_request_id_hash",
            "provider_output_hash",
        ):
            value = evidence.get(hash_field)
            if value is not None and (
                not isinstance(value, str) or not _SAFE_SHA256.fullmatch(value)
            ):
                evidence.pop(hash_field, None)
        projected.append(evidence)
    return projected


class PricingBoundCapturingAdapter:
    """Count calls and replace adapter accounting with authorized pricing."""

    def __init__(
        self,
        inner: Any,
        *,
        pricing: Mapping[str, Any],
        counters: SafetyCounters,
        max_requests: int,
    ) -> None:
        self.inner = inner
        self.config = getattr(inner, "config", None)
        self.pricing = pricing
        self.counters = counters
        self.max_requests = max_requests
        self.calls = 0
        self.invocations: list[dict[str, Any]] = []
        self.captured: list[dict[str, Any]] = []
        self.closed = False

    async def invoke(self, **kwargs: Any) -> Any:
        if self.calls >= self.max_requests:
            raise Phase9ExecutionError(
                "PHASE9_PROVIDER_REQUEST_CAP_EXCEEDED",
                "authorization request cap reached before transport",
            )
        self.calls += 1
        self.counters.provider_calls += 1
        started = time.monotonic()
        invocation = {
            "provider_invocation_index": self.calls,
            "prompt_id": str(kwargs.get("prompt_id", "")),
            "provider_attempt": kwargs.get("attempt"),
            "status": "INVOKING",
        }
        self.invocations.append(invocation)
        try:
            result = await self.inner.invoke(**kwargs)
        except BaseException as exc:
            invocation.update(
                {
                    "status": "FAILED",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    **_safe_provider_exception_diagnostic(exc),
                }
            )
            raise
        route = kwargs["route"]
        estimated = _estimate_cost(
            self.pricing,
            model=route.model,
            input_tokens=result.input_tokens,
            output_tokens=route.max_output_tokens,
            cached_input_tokens=result.cached_input_tokens,
            cache_write_input_tokens=result.cache_write_input_tokens,
        )
        actual = _estimate_cost(
            self.pricing,
            model=route.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_input_tokens=result.cached_input_tokens,
            cache_write_input_tokens=result.cache_write_input_tokens,
        )
        rebound = replace(
            result, estimated_cost_usd=estimated, actual_cost_usd=actual
        )
        captured = {
            "prompt_id": invocation["prompt_id"],
            "raw_output": rebound.raw_output,
            "output_hash": rebound.output_hash,
            "effective_model": rebound.effective_model,
            "provider_request_id_hash": rebound.provider_request_id_hash,
            "provider_schema_valid": rebound.provider_schema_valid,
            "provider_schema_issues": list(rebound.provider_schema_issues),
            "input_tokens": rebound.input_tokens,
            "cached_input_tokens": rebound.cached_input_tokens,
            "cache_write_input_tokens": rebound.cache_write_input_tokens,
            "output_tokens": rebound.output_tokens,
            "reasoning_tokens": rebound.reasoning_tokens,
            "estimated_cost_usd": estimated,
            "actual_cost_usd": actual,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        invocation.update(
            {
                "status": "COMPLETED",
                "provider_output_hash": rebound.output_hash,
                "provider_request_id_hash": rebound.provider_request_id_hash,
                "effective_model": rebound.effective_model,
                "actual_cost_usd": actual,
                "estimated_cost_usd": estimated,
                "provider_schema_valid": rebound.provider_schema_valid,
                "provider_schema_issues": list(rebound.provider_schema_issues),
                "input_tokens": rebound.input_tokens,
                "cached_input_tokens": rebound.cached_input_tokens,
                "cache_write_input_tokens": rebound.cache_write_input_tokens,
                "output_tokens": rebound.output_tokens,
                "reasoning_tokens": rebound.reasoning_tokens,
                "latency_ms": captured["latency_ms"],
            }
        )
        self.captured.append(captured)
        return rebound

    async def aclose(self) -> None:
        """Close an exposed async transport in the adapter's live event loop."""

        if self.closed:
            return
        close = getattr(self.inner, "aclose", None)
        if callable(close):
            result = close()
            if not isinstance(result, Awaitable):
                raise Phase9ExecutionError(
                    "PHASE9_ASYNC_CLOSE_BOUNDARY_INVALID",
                    "adapter aclose did not return an awaitable",
                )
            await result
        self.closed = True


@dataclass(slots=True)
class CostAccount:
    authorization: Mapping[str, Any]
    spent_usd: float = 0.0
    by_candidate: dict[str, float] = field(default_factory=dict)
    primary_spent_usd: float = 0.0
    primary_by_candidate: dict[str, float] = field(default_factory=dict)
    retry_spent_usd: float = 0.0
    retry_by_candidate: dict[str, float] = field(default_factory=dict)

    def admit(
        self,
        candidate: AuthorizedCandidate,
        projected: float,
        *,
        is_retry: bool,
    ) -> None:
        per_call = float(
            self.authorization["per_call_caps_usd"][candidate.candidate_id]
        )
        primary_rung = float(
            self.authorization["rung_primary_caps_usd"][candidate.candidate_id]
        )
        retry_rung = float(
            self.authorization["rung_retry_inclusive_caps_usd"][
                candidate.candidate_id
            ]
        )
        outer_primary = float(self.authorization["outer_primary_cap_usd"])
        outer_retry = float(
            self.authorization["outer_retry_inclusive_cap_usd"]
        )
        _require(
            projected <= per_call,
            "PHASE9_PER_CALL_CAP_WOULD_BE_EXCEEDED",
            f"{candidate.candidate_id} exceeds its authorized per-call cap",
        )
        _require(
            self.by_candidate.get(candidate.candidate_id, 0.0) + projected
            <= retry_rung,
            "PHASE9_RUNG_CAP_WOULD_BE_EXCEEDED",
            f"{candidate.candidate_id} exceeds its retry-inclusive rung cap",
        )
        _require(
            self.spent_usd + projected <= outer_retry,
            "PHASE9_OUTER_CAP_WOULD_BE_EXCEEDED",
            "the next request could exceed the retry-inclusive outer cap",
        )
        if not is_retry:
            _require(
                self.primary_by_candidate.get(candidate.candidate_id, 0.0)
                + projected
                <= primary_rung,
                "PHASE9_PRIMARY_RUNG_CAP_WOULD_BE_EXCEEDED",
                f"{candidate.candidate_id} exceeds its primary rung cap",
            )
            _require(
                self.primary_spent_usd + projected <= outer_primary,
                "PHASE9_PRIMARY_OUTER_CAP_WOULD_BE_EXCEEDED",
                "the next primary request could exceed the primary outer cap",
            )

    def charge(
        self,
        candidate: AuthorizedCandidate,
        actual: float,
        *,
        is_retry: bool,
    ) -> None:
        self.spent_usd += actual
        self.by_candidate[candidate.candidate_id] = (
            self.by_candidate.get(candidate.candidate_id, 0.0) + actual
        )
        if is_retry:
            self.retry_spent_usd += actual
            self.retry_by_candidate[candidate.candidate_id] = (
                self.retry_by_candidate.get(candidate.candidate_id, 0.0) + actual
            )
        else:
            self.primary_spent_usd += actual
            self.primary_by_candidate[candidate.candidate_id] = (
                self.primary_by_candidate.get(candidate.candidate_id, 0.0)
                + actual
            )


def _envelope_for(prompt_id: str, request: BaseModel) -> m.ModelTaskEnvelope:
    spec = prompt_spec(prompt_id)
    return m.ModelTaskEnvelope(
        schema_version=SCHEMA_VERSION,
        prompt_id=prompt_id,
        prompt_version=spec.prompt_version,
        output_schema_name=spec.output_schema_name,
        output_schema_version=SCHEMA_VERSION,
        trusted_context=build_trusted_context(request),
        payload=request.model_dump(mode="json"),
    )


def _gateway_for(
    *,
    candidate: AuthorizedCandidate,
    adapter: Any,
    cap: float,
    pricing: Mapping[str, Any],
    job_id: str,
) -> ModelGateway:
    profile_routes = build_openai_routes(
        max_call_cost_usd=cap, route_profile_id=candidate.route_profile_id
    )
    primary_route = profile_routes.get(candidate.prompt_id)
    _require(
        primary_route is not None
        and primary_route.model == candidate.model
        and primary_route.reasoning_effort.value == candidate.reasoning_effort
        and primary_route.max_output_tokens == candidate.max_output_tokens
        and primary_route.max_input_tokens == OPENAI_MAX_INPUT_TOKENS
        and primary_route.max_input_tokens < LONG_CONTEXT_THRESHOLD
        and openai_route_matches_profile(candidate.prompt_id, primary_route),
        "PHASE9_QUALIFICATION_PRIMARY_ROUTE_MISMATCH",
        f"the qualification route drifted for {candidate.prompt_id}",
    )
    # Executor-local policy: qualification receives exactly the planned primary
    # route. The product registry retains P11, but this gateway cannot resolve it.
    routes = {candidate.prompt_id: primary_route}
    _require(
        set(routes) == {candidate.prompt_id}
        and "P11_SCHEMA_REPAIR_V1" not in routes,
        "PHASE9_QUALIFICATION_SCHEMA_REPAIR_REACHABLE",
        "qualification must not resolve a P11 provider route",
    )

    def estimator(spec: PromptSpec, input_tokens: int) -> float:
        return _estimate_cost(
            pricing,
            model=candidate.model,
            input_tokens=input_tokens,
            output_tokens=spec.max_output_tokens,
            cache_write_input_tokens=input_tokens,
        )

    return ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=(
                OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
                + OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS
            ),
            max_retries=0,
            default_budget_usd=cap,
            job_id=job_id,
        ),
        real_routes=routes,
        adapters={"openai": adapter},
        cost_estimator=estimator,
        input_token_estimator=estimate_openai_input_tokens,
    )


def _failure_code(exc: BaseException) -> str:
    return str(getattr(exc, "code", None) or type(exc).__name__)


def _captured_response_evidence(
    captures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(captures) != 1:
        return {}
    captured = captures[0]
    evidence = {
        "provider_prompt_id": captured.get("prompt_id"),
        "provider_output_hash": captured.get("output_hash"),
        "provider_request_id_hash": captured.get("provider_request_id_hash"),
        "provider_schema_valid": captured.get("provider_schema_valid"),
        "provider_schema_issues": _safe_provider_schema_issues(
            captured.get("provider_schema_issues")
        ),
        "input_tokens": captured.get("input_tokens"),
        "cached_input_tokens": captured.get("cached_input_tokens"),
        "cache_write_input_tokens": captured.get("cache_write_input_tokens"),
        "output_tokens": captured.get("output_tokens"),
        "reasoning_tokens": captured.get("reasoning_tokens"),
        "estimated_cost_usd": captured.get("estimated_cost_usd"),
        "actual_cost_usd": captured.get("actual_cost_usd"),
    }
    for hash_field in ("provider_output_hash", "provider_request_id_hash"):
        value = evidence.get(hash_field)
        if value is not None and (
            not isinstance(value, str) or not _SAFE_SHA256.fullmatch(value)
        ):
            evidence.pop(hash_field, None)
    return evidence


def _attempt_provider_evidence(
    *,
    invocations: Sequence[Mapping[str, Any]],
    captures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    safe_invocations = _safe_provider_invocation_evidence(invocations)
    prompt_ids = [str(row.get("prompt_id", "")) for row in invocations]
    evidence: dict[str, Any] = {
        "provider_invocation_count": len(invocations),
        "provider_prompt_ids": prompt_ids,
        "provider_invocations": safe_invocations,
        "actual_cost_usd": (
            round(
                sum(float(row["actual_cost_usd"]) for row in captures), 8
            )
            if captures
            else None
        ),
    }
    evidence.update(_captured_response_evidence(captures))
    if len(safe_invocations) == 1:
        invocation = safe_invocations[0]
        for key in (
            "provider_reason_code",
            "provider_request_id_hash",
            "provider_exception_class",
        ):
            if key in invocation and key not in evidence:
                evidence[key] = invocation[key]
    return evidence


def _safe_gateway_failure_evidence(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, GatewayContextError):
        failure = exc.failure
        return {
            "failure_class": "DETERMINISTIC_CONTEXT_FAILURE",
            "context_failure_phase": failure.phase.value,
            "context_failure_codes": [code.value for code in failure.codes],
            "context_validation_engine": failure.validation_engine,
        }
    if isinstance(exc, GatewaySchemaViolation):
        failure = exc.primary_failure
        if failure is None:
            return {"failure_class": "DETERMINISTIC_STRUCTURAL_FAILURE"}
        return {
            "failure_class": "DETERMINISTIC_STRUCTURAL_FAILURE",
            "structural_failure": {
                "phase": failure.phase.value,
                "code": failure.code,
                "validation_engine": failure.validation_engine,
                "issues": [
                    {"error_type": issue.error_type, "path": issue.path}
                    for issue in failure.issues
                ],
                "provider_schema_valid": failure.provider_schema_valid,
                "provider_schema_issues": [
                    {"error_type": issue.error_type, "path": issue.path}
                    for issue in failure.provider_schema_issues
                ],
            },
        }
    return {}


def _provider_failure_disposition(
    *,
    provider_reason_code: Any,
    attempt_index: int,
    off_plan: bool,
) -> tuple[str, str, bool]:
    if off_plan:
        return "EXECUTION_POLICY_FAILURE", "OFF_PLAN_NO_RETRY", False
    if (
        isinstance(provider_reason_code, str)
        and provider_reason_code in RETRYABLE_TECHNICAL_CODES
    ):
        if attempt_index == 1:
            return (
                "RETRYABLE_PROVIDER_FAILURE",
                "ONE_AUTHORIZED_TECHNICAL_RETRY",
                True,
            )
        return (
            "RETRYABLE_PROVIDER_FAILURE",
            "TECHNICAL_RETRY_LIMIT_EXHAUSTED",
            False,
        )
    if isinstance(provider_reason_code, str):
        return (
            "PERMANENT_PROVIDER_FAILURE",
            "PERMANENT_PROVIDER_FAILURE_NO_RETRY",
            False,
        )
    return "UNCLASSIFIED_FAILURE", "NO_SANITIZED_RETRY_REASON_NO_RETRY", False


async def _execute_call(
    *,
    call: LogicalCall,
    adapter: PricingBoundCapturingAdapter,
    authorization: Mapping[str, Any],
    pricing: Mapping[str, Any],
    account: CostAccount,
) -> tuple[list[dict[str, Any]], CompletedCall | None]:
    candidate = call.case.candidate
    spec = prompt_spec(candidate.prompt_id)
    envelope = _envelope_for(candidate.prompt_id, call.case.request)
    input_upper = estimate_openai_input_tokens(spec, call.case.request, envelope)
    projected = _estimate_cost(
        pricing,
        model=candidate.model,
        input_tokens=input_upper,
        output_tokens=candidate.max_output_tokens,
        cache_write_input_tokens=input_upper,
    )
    cap = float(authorization["per_call_caps_usd"][candidate.candidate_id])
    attempts: list[dict[str, Any]] = []
    for attempt_index in range(1, MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL + 2):
        is_retry = attempt_index > 1
        account.admit(candidate, projected, is_retry=is_retry)
        gateway = _gateway_for(
            candidate=candidate,
            adapter=adapter,
            cap=cap,
            pricing=pricing,
            job_id=f"job_phase9v203_{call.case.stage.lower()}",
        )
        invocation_index = len(adapter.invocations)
        capture_index = len(adapter.captured)
        started = time.monotonic()
        try:
            result = await gateway.invoke(
                candidate.prompt_id,
                call.case.request,
                envelope.trusted_context,
                budget=CallBudget(max_cost_usd=cap),
            )
        except Exception as exc:  # noqa: BLE001 - execution always fails closed
            invocations = adapter.invocations[invocation_index:]
            captures = adapter.captured[capture_index:]
            for captured in captures:
                account.charge(
                    candidate,
                    float(captured["actual_cost_usd"]),
                    is_retry=is_retry,
                )
            provider_evidence = _attempt_provider_evidence(
                invocations=invocations, captures=captures
            )
            prompt_ids = provider_evidence["provider_prompt_ids"]
            off_plan = len(invocations) > 1 or any(
                prompt_id != candidate.prompt_id for prompt_id in prompt_ids
            )
            code = "OFF_PLAN_PROVIDER_CALL" if off_plan else _failure_code(exc)
            gateway_evidence = _safe_gateway_failure_evidence(exc)
            failure_class, retry_disposition, should_retry = (
                _provider_failure_disposition(
                    provider_reason_code=provider_evidence.get(
                        "provider_reason_code"
                    ),
                    attempt_index=attempt_index,
                    off_plan=off_plan,
                )
            )
            if gateway_evidence:
                failure_class = str(gateway_evidence["failure_class"])
                retry_disposition = "DETERMINISTIC_FAILURE_NO_RETRY"
                should_retry = False
            attempts.append(
                {
                    **call.identity(),
                    "logical_call_id": call.logical_call_id,
                    "attempt_index": attempt_index,
                    "status": "FAILED",
                    "failure_code": code,
                    "failure_class": failure_class,
                    "technical_retry_disposition": retry_disposition,
                    **provider_evidence,
                    **gateway_evidence,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            if should_retry:
                continue
            return attempts, None

        invocations = adapter.invocations[invocation_index:]
        captures = adapter.captured[capture_index:]
        for captured in captures:
            account.charge(
                candidate,
                float(captured["actual_cost_usd"]),
                is_retry=is_retry,
            )
        provider_evidence = _attempt_provider_evidence(
            invocations=invocations, captures=captures
        )
        prompt_ids = provider_evidence["provider_prompt_ids"]
        off_plan = (
            len(invocations) > 1
            or any(prompt_id != candidate.prompt_id for prompt_id in prompt_ids)
            or result.prompt_id != candidate.prompt_id
        )
        accounting_mismatch = (
            len(invocations) != 1
            or len(captures) != 1
            or (
                bool(captures)
                and captures[0].get("prompt_id") != candidate.prompt_id
            )
        )
        if off_plan or accounting_mismatch:
            attempts.append(
                {
                    **call.identity(),
                    "logical_call_id": call.logical_call_id,
                    "attempt_index": attempt_index,
                    "status": "FAILED",
                    "failure_code": (
                        "OFF_PLAN_PROVIDER_CALL"
                        if off_plan
                        else "PHASE9_PROVIDER_INVOCATION_ACCOUNTING_MISMATCH"
                    ),
                    "failure_class": "EXECUTION_POLICY_FAILURE",
                    "technical_retry_disposition": "EXECUTION_POLICY_NO_RETRY",
                    **provider_evidence,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            return attempts, None

        captured = captures[0]
        if result.repaired:
            attempts.append(
                {
                    **call.identity(),
                    "logical_call_id": call.logical_call_id,
                    "attempt_index": attempt_index,
                    "status": "FAILED",
                    "failure_code": "PHASE9_QUALIFICATION_SCHEMA_REPAIR_FORBIDDEN",
                    "failure_class": "EXECUTION_POLICY_FAILURE",
                    "technical_retry_disposition": "EXECUTION_POLICY_NO_RETRY",
                    **provider_evidence,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            return attempts, None
        raw = captured["raw_output"]
        if captured.get("provider_schema_valid") is not True or not isinstance(
            raw, Mapping
        ):
            attempts.append(
                {
                    **call.identity(),
                    "logical_call_id": call.logical_call_id,
                    "attempt_index": attempt_index,
                    "status": "FAILED",
                    "failure_code": "PHASE9_PROVIDER_SCHEMA_INVALID",
                    "failure_class": "DETERMINISTIC_STRUCTURAL_FAILURE",
                    "technical_retry_disposition": "DETERMINISTIC_FAILURE_NO_RETRY",
                    **provider_evidence,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            return attempts, None
        attempts.append(
            {
                **call.identity(),
                "logical_call_id": call.logical_call_id,
                "attempt_index": attempt_index,
                "status": "COMPLETED",
                "technical_retry_disposition": "NOT_APPLICABLE",
                **provider_evidence,
                "request_hash": call.case.request_hash,
                "reasoning_tokens": captured["reasoning_tokens"],
                "latency_ms": captured["latency_ms"],
            }
        )
        canonical = result.output.model_dump(mode="json")
        return attempts, CompletedCall(canonical, dict(raw))
    return attempts, None


async def _execute_population(
    *,
    calls: Sequence[LogicalCall],
    adapter: PricingBoundCapturingAdapter,
    authorization: Mapping[str, Any],
    pricing: Mapping[str, Any],
    account: CostAccount,
) -> tuple[list[dict[str, Any]], dict[str, CompletedCall]]:
    """Sequentially execute the frozen population in one live event loop."""

    attempts: list[dict[str, Any]] = []
    outputs: dict[str, CompletedCall] = {}
    for call in calls:
        call_attempts, output = await _execute_call(
            call=call,
            adapter=adapter,
            authorization=authorization,
            pricing=pricing,
            account=account,
        )
        attempts.extend(call_attempts)
        if output is not None:
            outputs[call.logical_call_id] = output
    return attempts, outputs


async def _execute_population_with_lifecycle(
    *,
    calls: Sequence[LogicalCall],
    adapter: PricingBoundCapturingAdapter,
    authorization: Mapping[str, Any],
    pricing: Mapping[str, Any],
    account: CostAccount,
) -> tuple[list[dict[str, Any]], dict[str, CompletedCall]]:
    """Own population execution and async transport closure in one loop."""

    try:
        return await _execute_population(
            calls=calls,
            adapter=adapter,
            authorization=authorization,
            pricing=pricing,
            account=account,
        )
    finally:
        await adapter.aclose()


SEMANTIC_PACKET_ALLOWED_FIELDS: Final = frozenset(
    {
        "schema_version",
        "case_id",
        "stage",
        "fixture_id",
        "route_or_opportunity_id",
        "binding_scope",
        "candidate_output",
        "candidate_output_hash",
        "relevant_source_refs",
        "property",
        "defensible_alternatives",
        "oracle_state",
        "source_hashes",
    }
)


def _semantic_observation(
    case: ProviderCase,
    authority: Mapping[str, Any],
    output: Mapping[str, Any],
) -> Mapping[str, Any]:
    if case.stage != "P06":
        return output
    binding = authority["p06_observation_binding"]
    expected_template = binding["expected_opportunity_template_id"]
    matched = [
        item
        for item in output.get("opportunities", [])
        if item.get("opportunity_template_id") == expected_template
    ]
    _require(
        len(matched) <= 1,
        "PHASE9_P06_PROPERTY_OBSERVATION_AMBIGUOUS",
        "grouped P06 output duplicated one bound opportunity",
    )
    omitted = not matched
    return {
        "route_omitted": omitted,
        "result_state": (
            "MODEL_FAILURE"
            if omitted and binding.get("candidate_scoring_allowed") is True
            else "PENDING_ADJUDICATION"
        ),
        "observation": None if omitted else matched[0],
    }


def build_semantic_blind_packets(
    *,
    calls: Sequence[LogicalCall],
    outputs: Mapping[str, CompletedCall],
) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for call in calls:
        if call.case.axis != "SEMANTIC" or call.logical_call_id not in outputs:
            continue
        completed = outputs[call.logical_call_id]
        for authority in call.case.property_observations:
            candidate_output = _semantic_observation(
                call.case, authority, completed.canonical_output
            )
            packet = {
                "schema_version": "semantic-review-packet/1.1.0",
                "case_id": call.case.provider_identity,
                "stage": call.case.stage,
                "fixture_id": authority["fixture_id"],
                "route_or_opportunity_id": authority["route_or_opportunity_id"],
                "binding_scope": authority["binding_scope"],
                "candidate_output": candidate_output,
                "candidate_output_hash": canonical_hash(candidate_output),
                "relevant_source_refs": authority["relevant_source_refs"],
                "property": authority["property"],
                "defensible_alternatives": authority["defensible_alternatives"],
                "oracle_state": authority["oracle_state"],
                "source_hashes": authority["source_hashes"],
            }
            _require(
                set(packet) == SEMANTIC_PACKET_ALLOWED_FIELDS,
                "PHASE9_SEMANTIC_PACKET_SCHEMA_MISMATCH",
                "semantic packet fields differ from the frozen review surface",
            )
            identity = canonical_hash(
                {
                    "packet": packet,
                    "logical_call_identity": call.identity(),
                    "property_id": authority["property_id"],
                    "namespace": "phase9-semantic-blind-packet/2.0.3",
                }
            )
            packets.append(
                {
                    "packet_id": f"sem-{identity.removeprefix('sha256:')[:24]}",
                    "packet_hash": canonical_hash(packet),
                    "packet": packet,
                }
            )
    return sorted(packets, key=lambda item: item["packet_id"])


def build_n3_blind_packets(
    *,
    calls: Sequence[LogicalCall],
    outputs: Mapping[str, CompletedCall],
) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for call in calls:
        if (
            call.case.axis != "CONTRACTUAL_HARD_SAFETY"
            or call.logical_call_id not in outputs
        ):
            continue
        authority = call.case.n3_packet_authority
        _require(
            authority is not None and call.case.exposure_pseudonym is not None,
            "PHASE9_N3_PACKET_AUTHORITY_MISSING",
            "N3 output has no exposure/run packet authority",
        )
        packet = build_n3_packet(
            exposure_pseudonym=call.case.exposure_pseudonym,
            run_index=call.run_index,
            route_context=authority["route_context"],
            model_visible_evidence=authority["model_visible_evidence"],
            model_owned_output=outputs[call.logical_call_id].provider_output,
            p06_stage_boundary_hash=authority["p06_stage_boundary_hash"],
            p06_field_authority_hash=authority["p06_field_authority_hash"],
            exposure_selector=authority["exposure_selector"],
            n3_gate_source_hash=authority["n3_gate_source_hash"],
        )
        assert_n3_packet_blind(packet)
        _require(
            not any(key in N3_PACKET_FORBIDDEN_FIELDS for key in packet),
            "PHASE9_N3_PACKET_LEAK",
            "N3 packet contains forbidden semantic or candidate authority",
        )
        identity = canonical_hash(
            {
                "packet_hash": packet["packet_hash"],
                "exposure_pseudonym": call.case.exposure_pseudonym,
                "run_index": call.run_index,
                "namespace": "phase9-n3-blind-packet/2.0.3",
            }
        )
        packets.append(
            {
                "packet_id": f"n3-{identity.removeprefix('sha256:')[:24]}",
                "packet_hash": canonical_hash(packet),
                "exposure_pseudonym": call.case.exposure_pseudonym,
                "run_index": call.run_index,
                "packet": packet,
            }
        )
    return sorted(
        packets, key=lambda item: (item["exposure_pseudonym"], item["run_index"])
    )


def build_blind_packet_sets(
    *,
    calls: Sequence[LogicalCall],
    outputs: Mapping[str, CompletedCall],
) -> dict[str, Any]:
    """Build disjoint semantic and contractual-hard-safety review surfaces."""

    semantic = build_semantic_blind_packets(calls=calls, outputs=outputs)
    n3 = build_n3_blind_packets(calls=calls, outputs=outputs)
    return {
        "schema_version": "phase9-blind-review-surfaces/2.0.3",
        "semantic": {
            "packet_count": len(semantic),
            "denominator": "ACCEPTED_SEMANTIC_RATE_ONLY",
            "packets": semantic,
        },
        "n3": {
            "packet_count": len(n3),
            "denominator": "EXCLUDED_FROM_ACCEPTED_SEMANTIC_RATE",
            "verdicts": list(N3_SAFETY_VERDICTS),
            "packets": n3,
        },
    }


def generation_completion_summary(
    *,
    calls: Sequence[LogicalCall],
    outputs: Mapping[str, CompletedCall],
    attempts: Sequence[Mapping[str, Any]],
    packets: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the exact frozen generation population before any success state."""

    planned_by_id = {call.logical_call_id: call for call in calls}
    planned_ids = set(planned_by_id)
    completed_ids = set(outputs)
    completed_attempt_ids = [
        str(row.get("logical_call_id"))
        for row in attempts
        if row.get("status") == "COMPLETED"
    ]
    missing_ids = sorted(planned_ids - completed_ids)
    extra_ids = sorted(completed_ids - planned_ids)
    extra_attempt_ids = sorted(
        {
            str(row.get("logical_call_id"))
            for row in attempts
            if row.get("logical_call_id") not in planned_ids
        }
    )
    identity_mismatches: list[str] = []
    off_plan_prompt_attempts: list[str] = []
    for row in attempts:
        logical_call_id = row.get("logical_call_id")
        call = planned_by_id.get(str(logical_call_id))
        if call is None:
            continue
        if any(row.get(key) != value for key, value in call.identity().items()):
            identity_mismatches.append(str(logical_call_id))
        prompt_ids = row.get("provider_prompt_ids", [])
        if not isinstance(prompt_ids, list) or any(
            prompt_id != call.case.candidate.prompt_id for prompt_id in prompt_ids
        ):
            off_plan_prompt_attempts.append(str(logical_call_id))

    semantic_surface = packets.get("semantic", {})
    n3_surface = packets.get("n3", {})
    semantic_packets = semantic_surface.get("packets", [])
    n3_packets = n3_surface.get("packets", [])
    semantic_count = semantic_surface.get("packet_count")
    n3_count = n3_surface.get("packet_count")
    p06_semantic_case_ids = {
        call.case.provider_identity
        for call in calls
        if call.case.axis == "SEMANTIC" and call.case.stage == "P06"
    }
    p06_observation_count = sum(
        isinstance(row, Mapping)
        and isinstance(row.get("packet"), Mapping)
        and row["packet"].get("case_id") in p06_semantic_case_ids
        for row in semantic_packets
    ) if isinstance(semantic_packets, list) else -1

    violations: list[str] = []
    if len(calls) != AUTHORIZED_PRIMARY_LOGICAL_CALLS:
        violations.append("PLANNED_LOGICAL_CALL_COUNT")
    if len(planned_by_id) != AUTHORIZED_PRIMARY_LOGICAL_CALLS:
        violations.append("PLANNED_LOGICAL_CALL_IDENTITY_UNIQUENESS")
    if len(outputs) != AUTHORIZED_PRIMARY_LOGICAL_CALLS:
        violations.append("SUCCESSFULLY_COMPLETED_LOGICAL_CALL_COUNT")
    if len(completed_ids) != AUTHORIZED_PRIMARY_LOGICAL_CALLS:
        violations.append("COMPLETED_LOGICAL_CALL_IDENTITY_UNIQUENESS")
    if missing_ids:
        violations.append("MISSING_PLANNED_LOGICAL_CALL_IDENTITY")
    if extra_ids or extra_attempt_ids or identity_mismatches:
        violations.append("EXTRA_OR_MISMATCHED_PROVIDER_IDENTITY")
    if (
        len(completed_attempt_ids) != AUTHORIZED_PRIMARY_LOGICAL_CALLS
        or set(completed_attempt_ids) != completed_ids
    ):
        violations.append("COMPLETED_ATTEMPT_POPULATION")
    if off_plan_prompt_attempts:
        violations.append("OFF_PLAN_PROVIDER_CALL")
    if (
        semantic_count != AUTHORIZED_SEMANTIC_PACKET_COUNT
        or not isinstance(semantic_packets, list)
        or len(semantic_packets) != AUTHORIZED_SEMANTIC_PACKET_COUNT
    ):
        violations.append("SEMANTIC_PACKET_POPULATION")
    if (
        n3_count != AUTHORIZED_N3_PACKET_COUNT
        or not isinstance(n3_packets, list)
        or len(n3_packets) != AUTHORIZED_N3_PACKET_COUNT
    ):
        violations.append("N3_PACKET_POPULATION")
    if p06_observation_count != AUTHORIZED_P06_SEMANTIC_OBSERVATION_COUNT:
        violations.append("P06_SEMANTIC_OBSERVATION_POPULATION")

    return {
        "complete": not violations,
        "violations": violations,
        "planned_logical_calls": len(calls),
        "unique_planned_logical_call_identities": len(planned_by_id),
        "successfully_completed_logical_calls": len(outputs),
        "unique_completed_logical_call_identities": len(completed_ids),
        "completed_attempts": len(completed_attempt_ids),
        "missing_planned_logical_call_ids": missing_ids,
        "extra_completed_logical_call_ids": extra_ids,
        "extra_attempt_logical_call_ids": extra_attempt_ids,
        "identity_mismatch_logical_call_ids": sorted(set(identity_mismatches)),
        "off_plan_prompt_logical_call_ids": sorted(
            set(off_plan_prompt_attempts)
        ),
        "semantic_packet_count": semantic_count,
        "n3_packet_count": n3_count,
        "p06_semantic_observation_count": p06_observation_count,
    }


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return canonical_hash(payload)


def _execution_id(authorization: Mapping[str, Any]) -> str:
    return (
        "exec-phase9v203-"
        + str(authorization["authorization_hash"]).removeprefix("sha256:")[:16]
    )


def _write_execution_evidence(
    *,
    prepared: PreparedExecution,
    authorization: Mapping[str, Any],
    pricing: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    packets: Mapping[str, Any],
    completion: Mapping[str, Any],
    account: CostAccount,
    counters: SafetyCounters,
    evidence_root: Path,
    adjudication_root: Path,
) -> dict[str, Any]:
    _require(
        completion.get("complete") is True,
        "PHASE9_SMOKE_GENERATION_INCOMPLETE",
        "complete execution evidence requires the exact 30/54/3 population",
    )
    execution_id = _execution_id(authorization)
    execution_dir = evidence_root / execution_id
    _require(
        not execution_dir.exists(),
        "PHASE9_EXECUTION_EVIDENCE_EXISTS",
        f"immutable execution evidence already exists: {execution_id}",
    )
    semantic_root = adjudication_root / execution_id / "semantic"
    n3_root = adjudication_root / execution_id / "n3"
    for surface, root in (
        (packets["semantic"], semantic_root),
        (packets["n3"], n3_root),
    ):
        rows = []
        for item in surface["packets"]:
            filename = f"{item['packet_id']}.json"
            _write_json(root / "packets" / filename, item["packet"])
            rows.append(
                {key: value for key, value in item.items() if key != "packet"}
                | {"file": f"packets/{filename}"}
            )
        _write_json(
            root / "bundle_manifest.json",
            {key: value for key, value in surface.items() if key != "packets"}
            | {"packets": rows},
        )
    manifest = {
        "schema_version": PHASE9_EXECUTION_VERSION,
        "execution_id": execution_id,
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "execution_version": PHASE9_EXECUTION_VERSION,
        "execution_boundary_hash": prepared.boundary["execution_boundary_hash"],
        "high_smoke_plan_hash": prepared.plan["plan_hash"],
        "pricing_snapshot_hash": pricing["pricing_snapshot_hash"],
        "authorization_id": authorization["authorization_id"],
        "authorization_hash": authorization["authorization_hash"],
        "primary_logical_calls": len(prepared.calls),
        "attempts": list(attempts),
        "actual_cost_usd": round(account.spent_usd, 8),
        "semantic_packet_count": packets["semantic"]["packet_count"],
        "n3_packet_count": packets["n3"]["packet_count"],
        "p06_semantic_observation_count": completion[
            "p06_semantic_observation_count"
        ],
        "completion": dict(completion),
        "semantic_and_n3_packets_separate": True,
        "adjudication_performed_here": False,
        "safety_counters": counters.snapshot(),
    }
    manifest_hash = _write_json(
        execution_dir / "execution_manifest.json", manifest
    )
    return {
        "status": "REAL_SMOKE_HIGH_GENERATION_COMPLETE_PENDING_ADJUDICATION",
        "execution_id": execution_id,
        "execution_dir": _repo_relative(execution_dir),
        "manifest_hash": manifest_hash,
        "semantic_bundle": _repo_relative(semantic_root),
        "n3_bundle": _repo_relative(n3_root),
        "safety_counters": counters.snapshot(),
    }


def _write_incomplete_execution_evidence(
    *,
    prepared: PreparedExecution,
    authorization: Mapping[str, Any],
    pricing: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    completion: Mapping[str, Any],
    account: CostAccount,
    counters: SafetyCounters,
    evidence_root: Path,
) -> dict[str, Any]:
    """Persist content-free failure accounting without emitting review packets."""

    execution_id = _execution_id(authorization)
    execution_dir = evidence_root / execution_id
    _require(
        not execution_dir.exists(),
        "PHASE9_EXECUTION_EVIDENCE_EXISTS",
        f"immutable execution evidence already exists: {execution_id}",
    )
    manifest = {
        "schema_version": PHASE9_EXECUTION_VERSION,
        "status": "PHASE9_SMOKE_GENERATION_INCOMPLETE",
        "execution_id": execution_id,
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "execution_version": PHASE9_EXECUTION_VERSION,
        "execution_boundary_hash": prepared.boundary["execution_boundary_hash"],
        "high_smoke_plan_hash": prepared.plan["plan_hash"],
        "pricing_snapshot_hash": pricing["pricing_snapshot_hash"],
        "authorization_id": authorization["authorization_id"],
        "authorization_hash": authorization["authorization_hash"],
        "attempts": list(attempts),
        "actual_cost_usd": round(account.spent_usd, 8),
        "completion": dict(completion),
        "adjudication_packets_emitted": 0,
        "adjudication_performed_here": False,
        "safety_counters": counters.snapshot(),
    }
    manifest_hash = _write_json(
        execution_dir / "execution_manifest.json", manifest
    )
    return {
        "status": "PHASE9_SMOKE_GENERATION_INCOMPLETE",
        "execution_id": execution_id,
        "execution_dir": _repo_relative(execution_dir),
        "manifest_hash": manifest_hash,
        "completion": dict(completion),
        "adjudication_packets_emitted": 0,
        "safety_counters": counters.snapshot(),
    }


def run_phase9b_smoke(
    *,
    created_by: str,
    pricing_path: Path = CURRENT_PRICING_PATH,
    cost_projection_path: Path = COST_PROJECTION_PATH,
    authorization_path: Path = BILLABLE_AUTHORIZATION_PATH,
    credential_resolver: Callable[[], SecretStr | None] | None = None,
    adapter_factory: Callable[[SecretStr], Any] = default_adapter_factory,
    allow_billable: bool = False,
    evidence_root: Path = EXECUTION_EVIDENCE_ROOT,
    adjudication_root: Path = ADJUDICATION_BUNDLE_ROOT,
    authority_paths: FrozenAuthorityPaths = FrozenAuthorityPaths(),
    authority_document_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    boundary_override: Mapping[str, Any] | None = None,
    request_authority_override: Mapping[str, Any] | None = None,
    live_specs: Mapping[str, PromptSpec] = PROMPT_SPECS,
) -> dict[str, Any]:
    """Run the v2.0.3 successor chain in its strict happens-before order."""

    del created_by  # identity is supplied by the future signed authorization
    counters = SafetyCounters()
    try:
        prepared = prepare_phase9_execution(
            authority_paths=authority_paths,
            authority_document_overrides=authority_document_overrides,
            boundary_override=boundary_override,
            request_authority_override=request_authority_override,
            live_specs=live_specs,
        )
        pricing = load_current_pricing_artifact(pricing_path)
        _require(
            pricing["pricing_snapshot_hash"]
            == prepared.boundary["current_pricing"]["pricing_snapshot_hash"],
            "PHASE9_CURRENT_PRICING_BINDING_MISMATCH",
            "runtime pricing is not the boundary-bound v2.0.3 snapshot",
        )
        counters.pricing_refresh = "VERIFIED_CURRENT_OFFICIAL_PRICING"
        cost_projection = load_and_validate_cost_projection(
            prepared=prepared,
            pricing=pricing,
            path=cost_projection_path,
        )
        authorization = load_and_validate_authorization(
            path=authorization_path,
            prepared=prepared,
            pricing=pricing,
            cost_projection=cost_projection,
        )
        if not allow_billable:
            return {
                "status": "READY_REQUIRES_EXPLICIT_ALLOW_BILLABLE",
                "execution_boundary_hash": prepared.boundary[
                    "execution_boundary_hash"
                ],
                "high_smoke_plan_hash": prepared.plan["plan_hash"],
                "pricing_snapshot_hash": pricing["pricing_snapshot_hash"],
                "cost_projection_hash": cost_projection[
                    "cost_projection_hash"
                ],
                "primary_logical_calls": len(prepared.calls),
                "safety_counters": counters.snapshot(),
            }
        _claim_authorization_once(authorization)
        counters.billable_authorization = authorization["authorization_id"]
        _require(
            credential_resolver is not None,
            "OPENAI_CREDENTIAL_RESOLVER_REQUIRED",
            "no deferred credential resolver was supplied",
        )
        counters.credential_resolutions += 1
        api_key = credential_resolver()
        _require(
            api_key is not None and api_key.get_secret_value().strip() != "",
            "OPENAI_CREDENTIAL_REQUIRED",
            "the deferred credential resolver returned no key",
        )

        def guarded_factory() -> Any:
            counters.transport_factory_calls += 1
            return adapter_factory(api_key)

        try:
            transport = build_qualification_transport_after_prompt_guard(
                stage="P04",
                prompt_id=CANDIDATE_BY_STAGE["P04"].prompt_id,
                frozen_prompt_authority=prepared.authorities.documents[
                    "prompt_authority"
                ],
                frozen_execution_contract=prepared.authorities.documents[
                    "candidate_execution_contract"
                ],
                transport_factory=guarded_factory,
                live_specs=live_specs,
            )
        except QualificationPromptMismatch as exc:
            raise Phase9ExecutionError(
                "PHASE9_EXECUTABLE_PROMPT_AUTHORITY_MISMATCH", str(exc)
            ) from exc
        counters.real_provider_transport = True
        adapter = PricingBoundCapturingAdapter(
            transport,
            pricing=pricing,
            counters=counters,
            max_requests=(
                AUTHORIZED_PRIMARY_LOGICAL_CALLS
                * (1 + MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL)
            ),
        )
        account = CostAccount(authorization)
        counters.high_smoke = "EXECUTING"
        attempts, outputs = asyncio.run(
            _execute_population_with_lifecycle(
                calls=prepared.calls,
                adapter=adapter,
                authorization=authorization,
                pricing=pricing,
                account=account,
            )
        )
        packet_sets = build_blind_packet_sets(calls=prepared.calls, outputs=outputs)
        completion = generation_completion_summary(
            calls=prepared.calls,
            outputs=outputs,
            attempts=attempts,
            packets=packet_sets,
        )
        if completion["complete"] is not True:
            counters.high_smoke = "ATTEMPTED_INCOMPLETE"
            return _write_incomplete_execution_evidence(
                prepared=prepared,
                authorization=authorization,
                pricing=pricing,
                attempts=attempts,
                completion=completion,
                account=account,
                counters=counters,
                evidence_root=evidence_root,
            )
        counters.high_smoke = "EXECUTED_COMPLETE"
        return _write_execution_evidence(
            prepared=prepared,
            authorization=authorization,
            pricing=pricing,
            attempts=attempts,
            packets=packet_sets,
            completion=completion,
            account=account,
            counters=counters,
            evidence_root=evidence_root,
            adjudication_root=adjudication_root,
        )
    except Phase9ExecutionError as exc:
        exc.safety_counters = counters.snapshot()
        raise
