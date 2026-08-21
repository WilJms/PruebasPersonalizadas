"""First-real-call harness for the frozen semantic-benchmark/1.3.5 instrument.

The semantic instrument and the execution harness have deliberately separate
boundaries. This module consumes immutable v1.3.5 authority plus the frozen
``phase9-execution/2.0.0`` request snapshot. It never rebuilds qualification
authority from historical benchmark trees.

The public execution entrypoint is fail-closed in this checkout: no current
pricing artifact or billable authorization is published. Therefore every
reachable call stops before credential resolution and before transport
construction with ``PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Final

from pydantic import BaseModel, SecretStr

from .canonical import canonical_hash
from .contracts import SCHEMA_VERSION, model_by_name, models as m
from .model_gateway import GatewayConfig, GatewayMode, ModelGateway
from .model_gateway.gateway import CallBudget
from .model_gateway.mock_factory import build_trusted_context
from .model_gateway.openai_adapter import (
    OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
)
from .model_gateway.openai_routes import build_openai_routes, estimate_openai_input_tokens
from .model_gateway.registry import PROMPT_SPECS, PromptSpec, prompt_spec
from .p06_n3_protocol import (
    N3_PACKET_FORBIDDEN_FIELDS,
    N3_SAFETY_VERDICTS,
    assert_n3_packet_blind,
    build_n3_packet,
)
from .semantic_benchmark import load_corpus_package
from .semantic_benchmark_v135 import (
    QualificationPromptMismatch,
    assert_live_prompt_authority,
    build_qualification_transport_after_prompt_guard,
)


PHASE9_EXECUTION_VERSION: Final = "phase9-execution/2.0.0"
BENCHMARK_VERSION: Final = "semantic-benchmark/1.3.5"
PROTOCOL_VERSION: Final = "phase9-qualification-protocol/1.3.5"
AUTHORIZED_K: Final = 3
AUTHORIZED_PRIMARY_LOGICAL_CALLS: Final = 30
AUTHORIZED_SPLIT: Final = "SMOKE"
OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS: Final = 15
MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL: Final = 1

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
V135_DEFINITION_ROOT: Final = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_5"
V135_REPORT_ROOT: Final = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_5"
EXECUTION_AUTHORITY_ROOT: Final = REPOSITORY_ROOT / "evaluation/phase9_execution/v2_0_0"
EXECUTION_REPORT_ROOT: Final = REPOSITORY_ROOT / "reports/phase9_execution/v2_0_0"
EXECUTION_BOUNDARY_PATH: Final = EXECUTION_AUTHORITY_ROOT / "execution_boundary.json"
HIGH_SMOKE_REQUEST_AUTHORITY_PATH: Final = (
    EXECUTION_AUTHORITY_ROOT / "high_smoke_request_authority.json"
)
CURRENT_PRICING_PATH: Final = EXECUTION_AUTHORITY_ROOT / "current_pricing.json"
BILLABLE_AUTHORIZATION_PATH: Final = (
    EXECUTION_AUTHORITY_ROOT / "billable_authorization.json"
)
EXECUTION_EVIDENCE_ROOT: Final = EXECUTION_REPORT_ROOT / "executions"
ADJUDICATION_BUNDLE_ROOT: Final = EXECUTION_REPORT_ROOT / "adjudication_bundles"

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
REQUIRED_SOURCE_BINDING_PATHS: Final = frozenset(
    {
        "scripts/build_phase9_execution_v2.py",
        "scripts/run_phase9_smoke.py",
        "src/comprehension_verification/n3_provider_fixtures.py",
        "src/comprehension_verification/p06_n3_protocol.py",
        "src/comprehension_verification/phase9_execution.py",
        "src/comprehension_verification/semantic_benchmark.py",
        "src/comprehension_verification/semantic_benchmark_fixtures.py",
        "src/comprehension_verification/semantic_benchmark_v135.py",
    }
)

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


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPOSITORY_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


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
    """Validate the separately versioned v2 boundary and request snapshot."""

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
        boundary.get("execution_version") == PHASE9_EXECUTION_VERSION
        and boundary.get("benchmark_version") == BENCHMARK_VERSION
        and boundary.get("protocol_version") == PROTOCOL_VERSION,
        "PHASE9_EXECUTION_BOUNDARY_VERSION_MISMATCH",
        "the execution boundary names a different harness or instrument",
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
        request_authority.get("execution_version") == PHASE9_EXECUTION_VERSION
        and request_authority.get("benchmark_version") == BENCHMARK_VERSION
        and request_authority.get("protocol_version") == PROTOCOL_VERSION
        and request_authority.get("selection_depends_on_results") is False
        and request_authority.get("contains_held_out_material") is False,
        "PHASE9_EXECUTION_REQUEST_AUTHORITY_SCOPE_MISMATCH",
        "the request snapshot is not the result-independent v1.3.5 SMOKE surface",
    )

    source_bindings = boundary.get("source_bindings", {})
    _require(
        isinstance(source_bindings, Mapping)
        and set(source_bindings) == REQUIRED_SOURCE_BINDING_PATHS,
        "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH",
        "the v2 boundary does not bind the exact executor/builder source set",
    )
    for relative, expected in source_bindings.items():
        path = (REPOSITORY_ROOT / relative).resolve()
        _require(
            path.is_relative_to(REPOSITORY_ROOT.resolve())
            and path.is_file()
            and _file_hash(path) == expected,
            "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH",
            f"execution source changed without a new boundary: {relative}",
        )
    _require(
        _repo_relative(Path(__file__)) in source_bindings,
        "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH",
        "the exact executor source is absent from the v2 boundary",
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
        "schema_version": "phase9-high-smoke-plan/2.0.0",
        "execution_version": PHASE9_EXECUTION_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "logical_calls": [call.identity() for call in calls],
    }
    plan = {**material, "plan_hash": canonical_hash(material)}
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


def load_current_pricing_artifact(path: Path = CURRENT_PRICING_PATH) -> dict[str, Any]:
    """Load only a future explicitly published current-pricing authority."""

    if not path.is_file():
        raise Phase9ExecutionError(
            "PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION",
            "no current official pricing artifact is published for execution v2",
        )
    pricing = _read_json(path)
    _require(
        pricing.get("pricing_snapshot_hash")
        == _self_hash(pricing, "pricing_snapshot_hash"),
        "PHASE9_CURRENT_PRICING_SELF_HASH_MISMATCH",
        "the supplied current-pricing artifact does not reproduce",
    )
    _require(
        pricing.get("schema_version") == "phase9-current-pricing/2.0.0"
        and pricing.get("execution_version") == PHASE9_EXECUTION_VERSION
        and pricing.get("status") == "VERIFIED_CURRENT_OFFICIAL_PRICING"
        and pricing.get("official_source_url")
        and pricing.get("retrieved_at"),
        "PHASE9_CURRENT_PRICING_INVALID",
        "pricing is not explicitly current and official for execution v2",
    )
    required_models = {item.model for item in AUTHORIZED_CANDIDATES}
    rows = pricing.get("models", {})
    _require(
        set(rows) == required_models,
        "PHASE9_CURRENT_PRICING_INVALID",
        "pricing must bind exactly the HIGH candidate models",
    )
    for model, row in rows.items():
        _require(
            all(
                isinstance(row.get(key), (int, float)) and row[key] >= 0
                for key in (
                    "input_per_million_usd",
                    "cached_input_per_million_usd",
                    "output_per_million_usd",
                )
            ),
            "PHASE9_CURRENT_PRICING_INVALID",
            f"invalid token pricing for {model}",
        )
    return pricing


def authorization_requirements(
    prepared: PreparedExecution, pricing: Mapping[str, Any]
) -> dict[str, Any]:
    """Return exact material a later explicit authorization must bind.

    This is a requirements document, not a billable authorization and cannot be
    consumed by the executor.
    """

    return {
        "schema_version": "phase9-billable-authorization-requirements/2.0.0",
        "authorization_state": "NOT_AUTHORIZED_TEMPLATE",
        "benchmark_version": BENCHMARK_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "execution_version": PHASE9_EXECUTION_VERSION,
        "execution_boundary_hash": prepared.boundary["execution_boundary_hash"],
        "high_smoke_plan_hash": prepared.plan["plan_hash"],
        **dict(prepared.authorities.semantic_bindings),
        "pricing_snapshot_hash": pricing["pricing_snapshot_hash"],
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
            "rung_caps_usd",
            "outer_cap_usd",
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
) -> dict[str, Any]:
    if not path.is_file():
        raise Phase9ExecutionError(
            "EXPLICIT_HASH_BOUND_AUTHORIZATION_REQUIRED",
            "no billable authorization is published for execution v2",
        )
    authorization = _read_json(path)
    _require(
        authorization.get("authorization_hash")
        == _self_hash(authorization, "authorization_hash"),
        "PHASE9_AUTHORIZATION_SELF_HASH_MISMATCH",
        "the billable authorization does not reproduce",
    )
    requirements = authorization_requirements(prepared, pricing)
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
        == "phase9-billable-authorization/2.0.0"
        and authorization.get("authorization_state") == "EXPLICITLY_APPROVED"
        and authorization.get("billable_authorization") == "EXPLICIT"
        and authorization.get("primary_provider_calls") == 30,
        "PHASE9_AUTHORIZATION_INVALID",
        "authorization is not an explicit 30-call execution-v2 approval",
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
    for key in ("per_call_caps_usd", "rung_caps_usd"):
        caps = authorization.get(key, {})
        _require(
            set(caps) == candidate_ids
            and all(
                isinstance(value, (int, float)) and value > 0
                for value in caps.values()
            ),
            "PHASE9_AUTHORIZATION_INVALID",
            f"{key} must provide positive caps for exactly the HIGH candidates",
        )
    _require(
        isinstance(authorization.get("outer_cap_usd"), (int, float))
        and authorization["outer_cap_usd"] > 0,
        "PHASE9_AUTHORIZATION_INVALID",
        "authorization outer cap must be positive",
    )
    ledger_path = (
        REPOSITORY_ROOT / str(authorization.get("ledger_path", ""))
    ).resolve()
    ledger_root = (EXECUTION_REPORT_ROOT / "authorization_ledger").resolve()
    _require(
        ledger_path.is_relative_to(ledger_root),
        "PHASE9_AUTHORIZATION_INVALID",
        "authorization ledger path is outside the execution-v2 ledger root",
    )
    return authorization


def _claim_authorization_once(authorization: Mapping[str, Any]) -> Path:
    ledger_path = (REPOSITORY_ROOT / authorization["ledger_path"]).resolve()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "phase9-authorization-consumption/2.0.0",
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
) -> float:
    row = pricing["models"][model]
    input_tokens = max(0, input_tokens)
    cached = min(input_tokens, max(0, cached_input_tokens))
    ordinary = input_tokens - cached
    return round(
        (
            ordinary * float(row["input_per_million_usd"])
            + cached * float(row["cached_input_per_million_usd"])
            + max(0, output_tokens) * float(row["output_per_million_usd"])
        )
        / 1_000_000,
        8,
    )


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
        self.captured: list[dict[str, Any]] = []

    async def invoke(self, **kwargs: Any) -> Any:
        if self.calls >= self.max_requests:
            raise Phase9ExecutionError(
                "PHASE9_PROVIDER_REQUEST_CAP_EXCEEDED",
                "authorization request cap reached before transport",
            )
        self.calls += 1
        self.counters.provider_calls += 1
        started = time.monotonic()
        result = await self.inner.invoke(**kwargs)
        route = kwargs["route"]
        estimated = _estimate_cost(
            self.pricing,
            model=route.model,
            input_tokens=result.input_tokens,
            output_tokens=route.max_output_tokens,
            cached_input_tokens=result.cached_input_tokens,
        )
        actual = _estimate_cost(
            self.pricing,
            model=route.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_input_tokens=result.cached_input_tokens,
        )
        rebound = replace(
            result, estimated_cost_usd=estimated, actual_cost_usd=actual
        )
        self.captured.append(
            {
                "raw_output": rebound.raw_output,
                "output_hash": rebound.output_hash,
                "effective_model": rebound.effective_model,
                "provider_request_id_hash": rebound.provider_request_id_hash,
                "provider_schema_valid": rebound.provider_schema_valid,
                "provider_schema_issues": list(rebound.provider_schema_issues),
                "input_tokens": rebound.input_tokens,
                "cached_input_tokens": rebound.cached_input_tokens,
                "output_tokens": rebound.output_tokens,
                "reasoning_tokens": rebound.reasoning_tokens,
                "estimated_cost_usd": estimated,
                "actual_cost_usd": actual,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        )
        return rebound


@dataclass(slots=True)
class CostAccount:
    authorization: Mapping[str, Any]
    spent_usd: float = 0.0
    by_candidate: dict[str, float] = field(default_factory=dict)

    def admit(self, candidate: AuthorizedCandidate, projected: float) -> None:
        per_call = float(
            self.authorization["per_call_caps_usd"][candidate.candidate_id]
        )
        rung = float(self.authorization["rung_caps_usd"][candidate.candidate_id])
        outer = float(self.authorization["outer_cap_usd"])
        _require(
            projected <= per_call,
            "PHASE9_PER_CALL_CAP_WOULD_BE_EXCEEDED",
            f"{candidate.candidate_id} exceeds its authorized per-call cap",
        )
        _require(
            self.by_candidate.get(candidate.candidate_id, 0.0) + projected <= rung,
            "PHASE9_RUNG_CAP_WOULD_BE_EXCEEDED",
            f"{candidate.candidate_id} exceeds its authorized rung cap",
        )
        _require(
            self.spent_usd + projected <= outer,
            "PHASE9_OUTER_CAP_WOULD_BE_EXCEEDED",
            "the next request could exceed the authorized outer cap",
        )

    def charge(self, candidate: AuthorizedCandidate, actual: float) -> None:
        self.spent_usd += actual
        self.by_candidate[candidate.candidate_id] = (
            self.by_candidate.get(candidate.candidate_id, 0.0) + actual
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
    routes = build_openai_routes(
        max_call_cost_usd=cap, route_profile_id=candidate.route_profile_id
    )

    def estimator(spec: PromptSpec, input_tokens: int) -> float:
        return _estimate_cost(
            pricing,
            model=candidate.model,
            input_tokens=input_tokens,
            output_tokens=spec.max_output_tokens,
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
    )
    cap = float(authorization["per_call_caps_usd"][candidate.candidate_id])
    attempts: list[dict[str, Any]] = []
    for attempt_index in range(1, MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL + 2):
        account.admit(candidate, projected)
        gateway = _gateway_for(
            candidate=candidate,
            adapter=adapter,
            cap=cap,
            pricing=pricing,
            job_id=f"job_phase9v2_{call.case.stage.lower()}",
        )
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
            code = _failure_code(exc)
            captured = (
                adapter.captured[capture_index]
                if len(adapter.captured) > capture_index
                else None
            )
            if captured is not None:
                account.charge(candidate, float(captured["actual_cost_usd"]))
            attempts.append(
                {
                    **call.identity(),
                    "logical_call_id": call.logical_call_id,
                    "attempt_index": attempt_index,
                    "status": "FAILED",
                    "failure_code": code,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            if code in RETRYABLE_TECHNICAL_CODES and attempt_index == 1:
                continue
            return attempts, None
        captured = adapter.captured[capture_index]
        account.charge(candidate, float(captured["actual_cost_usd"]))
        attempts.append(
            {
                **call.identity(),
                "logical_call_id": call.logical_call_id,
                "attempt_index": attempt_index,
                "status": "COMPLETED",
                "request_hash": call.case.request_hash,
                "provider_output_hash": captured["output_hash"],
                "provider_request_id_hash": captured["provider_request_id_hash"],
                "actual_cost_usd": captured["actual_cost_usd"],
                "input_tokens": captured["input_tokens"],
                "output_tokens": captured["output_tokens"],
                "latency_ms": captured["latency_ms"],
            }
        )
        canonical = result.output.model_dump(mode="json")
        raw = captured["raw_output"]
        if not isinstance(raw, Mapping):
            raw = {"unstructured_provider_output": raw}
        return attempts, CompletedCall(canonical, dict(raw))
    return attempts, None


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
                    "namespace": "phase9-semantic-blind-packet/2.0.0",
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
                "namespace": "phase9-n3-blind-packet/2.0.0",
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
        "schema_version": "phase9-blind-review-surfaces/2.0.0",
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


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return canonical_hash(payload)


def _write_execution_evidence(
    *,
    prepared: PreparedExecution,
    authorization: Mapping[str, Any],
    pricing: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    packets: Mapping[str, Any],
    account: CostAccount,
    counters: SafetyCounters,
    evidence_root: Path,
    adjudication_root: Path,
) -> dict[str, Any]:
    execution_id = (
        "exec-phase9v2-"
        + authorization["authorization_hash"].removeprefix("sha256:")[:16]
    )
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


def run_phase9b_smoke(
    *,
    created_by: str,
    pricing_path: Path = CURRENT_PRICING_PATH,
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
    """Run the v2 first-real-call chain in its strict happens-before order."""

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
        authorization = load_and_validate_authorization(
            path=authorization_path, prepared=prepared, pricing=pricing
        )
        if not allow_billable:
            return {
                "status": "READY_REQUIRES_EXPLICIT_ALLOW_BILLABLE",
                "execution_boundary_hash": prepared.boundary[
                    "execution_boundary_hash"
                ],
                "high_smoke_plan_hash": prepared.plan["plan_hash"],
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
        attempts: list[dict[str, Any]] = []
        outputs: dict[str, CompletedCall] = {}
        counters.high_smoke = "EXECUTING"
        for call in prepared.calls:
            call_attempts, output = asyncio.run(
                _execute_call(
                    call=call,
                    adapter=adapter,
                    authorization=authorization,
                    pricing=pricing,
                    account=account,
                )
            )
            attempts.extend(call_attempts)
            if output is not None:
                outputs[call.logical_call_id] = output
        counters.high_smoke = "EXECUTED"
        packet_sets = build_blind_packet_sets(calls=prepared.calls, outputs=outputs)
        return _write_execution_evidence(
            prepared=prepared,
            authorization=authorization,
            pricing=pricing,
            attempts=attempts,
            packets=packet_sets,
            account=account,
            counters=counters,
            evidence_root=evidence_root,
            adjudication_root=adjudication_root,
        )
    except Phase9ExecutionError as exc:
        exc.safety_counters = counters.snapshot()
        raise
