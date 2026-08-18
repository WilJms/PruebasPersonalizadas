"""Phase 9B execution surface: authorization, SMOKE transport and blind packets.

Phase 9A froze *how* a qualification would run. This module is the first thing
that can actually run one, and it is deliberately narrow: it executes exactly
the frozen SMOKE split of the lowest reasoning rung, under one hash-bound
billable authorization that can be consumed once.

Three boundaries are load-bearing here and none of them may be edited to make a
run succeed:

* ``semantic_benchmark.py``, ``semantic_benchmark_fixtures.py`` and
  ``validation.py`` are hashed into the frozen benchmark boundary, so this
  module imports them and never modifies them.
* The deterministic compiler/materializer for each stage already lives inside
  the model gateway. A draft that fails it is a deterministic validation
  failure, never a semantic verdict.
* Semantic adjudication does not happen here at all. This module emits blind
  review packets and stops; every externally adjudicated property leaves in
  ``PENDING_ADJUDICATION``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from typing import Any, Final

from pydantic import BaseModel, SecretStr

from . import semantic_benchmark as sb
from .contracts import SCHEMA_VERSION, models as m
from .model_gateway import (
    GatewayConfig,
    GatewayError,
    GatewayMode,
    ModelGateway,
)
from .model_gateway.gateway import CallBudget
from .model_gateway.mock_factory import build_trusted_context
from .model_gateway.openai_adapter import (
    OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
)
from .model_gateway.openai_pricing import (
    MODEL_PRICES,
    PRICING_SOURCE_URL,
    estimate_cost_usd,
)
from .model_gateway.openai_routes import (
    build_openai_cost_estimator,
    build_openai_routes,
    estimate_openai_input_tokens,
)
from .model_gateway.registry import PROMPT_SPECS, prompt_spec
from .phase9_protocol import canonical_json
from .semantic_benchmark_fixtures import (
    build_p04_fixture,
    build_p06_fixture,
    build_p07_fixture,
    build_p09_fixture,
)


PHASE9_EXECUTION_VERSION: Final = "phase9-execution/1.0.0"
OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS: Final = 15

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
BENCHMARK_REPORT_ROOT: Final = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_1"
PHASE9_DEFINITION_ROOT: Final = (
    REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_1/phase9"
)
EXECUTION_EVIDENCE_ROOT: Final = BENCHMARK_REPORT_ROOT / "phase9/executions"

EXPECTED_BENCHMARK_BOUNDARY_HASH: Final = (
    "sha256:426dda4d560a8d7d53639dfbaa0773c28565450f06e8ff62d51a8cd1bd6f62ff"
)
EXPECTED_PROTOCOL_BOUNDARY_HASH: Final = (
    "sha256:daa79023de4e3b72a73f31879d481fbedb75492cc5fb4642c7fd2b4a4dbaa540"
)
EXPECTED_CANDIDATE_MATRIX_HASH: Final = (
    "sha256:a1612f10aa72d561a46c8af665df16aef823ab14543cd2e8061ff4ad17a5db6f"
)
EXPECTED_CORPUS_BOUNDARY_HASH: Final = (
    "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1"
)

AUTHORIZED_SPLIT: Final = "SMOKE"
AUTHORIZED_K: Final = 3
AUTHORIZED_PRIMARY_LOGICAL_CALLS: Final = 30
OUTER_AUTHORIZATION_CAP_USD: Final = 2.00
MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL: Final = 1

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
    """Fail-closed stop before or during Phase 9B execution."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class AuthorizedCandidate:
    """One frozen HIGH-rung candidate this authorization may execute."""

    stage: str
    candidate_id: str
    model: str
    reasoning_effort: str
    route_profile_id: str
    prompt_id: str
    max_output_tokens: int
    per_call_cap_usd: float
    smoke_rung_cap_usd: float
    smoke_calls: int


AUTHORIZED_CANDIDATES: Final[tuple[AuthorizedCandidate, ...]] = (
    AuthorizedCandidate(
        stage="P04",
        candidate_id="P04-C1-TERRA-HIGH",
        model="gpt-5.6-terra",
        reasoning_effort="HIGH",
        route_profile_id="TERRA_HIGH_V1",
        prompt_id="P04_BLUEPRINT_BUILD_V1",
        max_output_tokens=16_000,
        per_call_cap_usd=0.3625,
        smoke_rung_cap_usd=1.0875,
        smoke_calls=3,
    ),
    AuthorizedCandidate(
        stage="P06",
        candidate_id="P06-C1-LUNA-HIGH",
        model="gpt-5.6-luna",
        reasoning_effort="HIGH",
        route_profile_id="LUNA_BASELINE_V1",
        prompt_id="P06_EVIDENCE_MAP_V1",
        max_output_tokens=16_000,
        per_call_cap_usd=0.0333,
        smoke_rung_cap_usd=0.1998,
        smoke_calls=6,
    ),
    AuthorizedCandidate(
        stage="P07",
        candidate_id="P07-C1-LUNA-HIGH",
        model="gpt-5.6-luna",
        reasoning_effort="HIGH",
        route_profile_id="LUNA_BASELINE_V1",
        prompt_id="P07_QUESTION_BUILD_V1",
        max_output_tokens=10_000,
        per_call_cap_usd=0.0243,
        smoke_rung_cap_usd=0.4374,
        smoke_calls=18,
    ),
    AuthorizedCandidate(
        stage="P09",
        candidate_id="P09-C1-LUNA-HIGH",
        model="gpt-5.6-luna",
        reasoning_effort="HIGH",
        route_profile_id="LUNA_BASELINE_V1",
        prompt_id="P09_GUIDE_BUILD_V1",
        max_output_tokens=10_000,
        per_call_cap_usd=0.0235,
        smoke_rung_cap_usd=0.0705,
        smoke_calls=3,
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


def _hash(payload: Any) -> str:
    return sb.canonical_hash(payload)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Frozen boundary revalidation
# ---------------------------------------------------------------------------


def revalidate_frozen_boundaries() -> dict[str, Any]:
    """Re-read every frozen boundary this execution is allowed to depend on."""

    boundary = json.loads(
        (BENCHMARK_REPORT_ROOT / "benchmark_boundary.json").read_text("utf-8")
    )
    freeze = json.loads(
        (BENCHMARK_REPORT_ROOT / "phase9/protocol_freeze_report.json").read_text(
            "utf-8"
        )
    )
    matrix = json.loads(
        (PHASE9_DEFINITION_ROOT / "candidate_matrix.json").read_text("utf-8")
    )
    observed = {
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "protocol_boundary_hash": freeze["phase9_protocol_boundary_hash"],
        "candidate_matrix_hash": freeze["candidate_matrix_hash"],
        "corpus_package_boundary_hash": boundary["corpus_package_boundary_hash"],
    }
    expected = {
        "benchmark_boundary_hash": EXPECTED_BENCHMARK_BOUNDARY_HASH,
        "protocol_boundary_hash": EXPECTED_PROTOCOL_BOUNDARY_HASH,
        "candidate_matrix_hash": EXPECTED_CANDIDATE_MATRIX_HASH,
        "corpus_package_boundary_hash": EXPECTED_CORPUS_BOUNDARY_HASH,
    }
    for key, value in expected.items():
        if observed[key] != value:
            raise Phase9ExecutionError(
                "PHASE9_FROZEN_BOUNDARY_MISMATCH",
                f"{key} drifted from the frozen Phase 9 boundary",
            )
    if matrix.get("matrix_status") != "FROZEN":
        raise Phase9ExecutionError(
            "PHASE9_FROZEN_BOUNDARY_MISMATCH", "candidate matrix is not FROZEN"
        )
    declared = {item["candidate_id"]: item for item in matrix["candidates"]}
    for candidate in AUTHORIZED_CANDIDATES:
        row = declared.get(candidate.candidate_id)
        if row is None:
            raise Phase9ExecutionError(
                "PHASE9_FROZEN_BOUNDARY_MISMATCH",
                f"{candidate.candidate_id} is absent from the frozen matrix",
            )
        if (
            row["model"] != candidate.model
            or row["reasoning_effort"] != candidate.reasoning_effort
            or row["route_profile_id"] != candidate.route_profile_id
            or row["max_output_tokens"] != candidate.max_output_tokens
        ):
            raise Phase9ExecutionError(
                "PHASE9_FROZEN_BOUNDARY_MISMATCH",
                f"{candidate.candidate_id} does not match the frozen matrix row",
            )
    return observed


def verify_pricing_snapshot() -> dict[str, Any]:
    """Require the executable pricing table to equal the frozen snapshot."""

    snapshot = json.loads(
        (PHASE9_DEFINITION_ROOT / "pricing_snapshot.json").read_text("utf-8")
    )
    rows = {item["model"]: item for item in snapshot["models"]}
    for model, prices in MODEL_PRICES.items():
        row = rows.get(model)
        if row is None:
            continue
        if (
            row["input_price"] != prices.input_per_million
            or row["output_price"] != prices.output_per_million
            or row["cached_input_price"] != prices.cached_input_per_million
        ):
            raise Phase9ExecutionError(
                "PHASE9_PRICING_OR_MODEL_DRIFT_REQUIRES_REFREEZE",
                f"executable pricing for {model} differs from the frozen snapshot",
            )
    for candidate in AUTHORIZED_CANDIDATES:
        if candidate.model not in rows:
            raise Phase9ExecutionError(
                "PHASE9_PRICING_OR_MODEL_DRIFT_REQUIRES_REFREEZE",
                f"no frozen price for {candidate.model}",
            )
    return {
        "official_source": snapshot["official_source"],
        "pricing_unit": snapshot["pricing_unit"],
        "retrieved_at": snapshot["retrieved_at"],
        "executable_table_source": PRICING_SOURCE_URL,
        "models": {
            model: {
                "input_per_million": prices.input_per_million,
                "cached_input_per_million": prices.cached_input_per_million,
                "output_per_million": prices.output_per_million,
            }
            for model, prices in MODEL_PRICES.items()
            if model in {item.model for item in AUTHORIZED_CANDIDATES}
        },
    }


# ---------------------------------------------------------------------------
# Frozen SMOKE plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmokeCase:
    """One frozen SMOKE case rebuilt into its exact provider request."""

    case_id: str
    stage: str
    candidate: AuthorizedCandidate
    fixture_ref: str
    request: BaseModel
    frozen_input_hash: str
    rebuilt_input_hash: str
    model_visible_refs: tuple[str, ...]
    property_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicalCall:
    """One authorized primary logical call (a case at one run index)."""

    logical_call_id: str
    case: SmokeCase
    run_index: int


def _submission_bundle_factory(package: sb.CorpusPackage):
    cache: dict[tuple[str, str], m.EvidenceBundle] = {}

    def resolve(activity_id: str, submission_id: str) -> m.EvidenceBundle:
        key = (activity_id, submission_id)
        if key not in cache:
            activity = package.activity_by_id[activity_id]
            submission = next(
                item
                for item in activity["submissions"]
                if item["submission_id"] == submission_id
            )
            cache[key] = sb.parse_submission_bundle(
                corpus_root=package.root,
                activity_path=activity["activity_path"],
                activity_id=activity_id,
                submission_id=submission_id,
                artifact_refs=submission["artifacts"],
            )
        return cache[key]

    return resolve


def _frozen_smoke_cases() -> list[dict[str, Any]]:
    matrix = json.loads(
        (BENCHMARK_REPORT_ROOT / "case_matrix.json").read_text("utf-8")
    )
    return [
        case
        for case in matrix["cases"]
        if case["split"] == AUTHORIZED_SPLIT and case["stage"] != "PLANNER"
    ]


def build_smoke_cases() -> list[SmokeCase]:
    """Rebuild every frozen SMOKE request and prove it is byte-identical.

    The benchmark stores an ``input_hash`` per case. Rebuilding the request and
    reproducing that hash is what lets this module claim it sent the frozen
    synthetic case rather than something merely similar to it.
    """

    frozen = _frozen_smoke_cases()
    by_id = {case["case_id"]: case for case in frozen}
    package = sb.load_corpus_package()
    if package.package_hash != EXPECTED_CORPUS_BOUNDARY_HASH:
        raise Phase9ExecutionError(
            "PHASE9_FROZEN_BOUNDARY_MISMATCH", "corpus package boundary drifted"
        )
    definitions = sb._load_fixture_definitions()
    bundle_for = _submission_bundle_factory(package)
    built: list[SmokeCase] = []

    for case in (item for item in frozen if item["stage"] == "P04"):
        activity = package.activity_by_id[case["activity_id"]]
        request, coverage = build_p04_fixture(
            corpus_root=package.root,
            activity_path=activity["activity_path"],
            activity_id=case["activity_id"],
        )
        refs = [
            f"{activity['activity_path']}/01_assignment.docx",
            f"{activity['activity_path']}/02_rubric.docx",
        ]
        projection = sb.project_model_visible_files(package, refs)
        rebuilt = _hash(
            {
                "request": request.model_dump(mode="json"),
                "source_hashes": projection.sha256_by_ref,
                "source_coverage": coverage,
                "scaffold_marker": sb.SCAFFOLD_MARKER,
            }
        )
        built.append(_smoke_case(case, request, rebuilt, projection.refs))

    for route in definitions["p06_routes"]["routes"]:
        case_id = sb._case_id_for_route(route)
        if case_id not in by_id:
            continue
        case = by_id[case_id]
        activity = package.activity_by_id[route["activity_id"]]
        request, envelope = build_p06_fixture(
            route_fixture_id=route["route_fixture_id"],
            model_visible_definition=route["model_visible_definition"],
            bundle=bundle_for(route["activity_id"], route["submission_id"]),
        )
        projection = sb.project_model_visible_files(
            package, sb._source_refs_for_submission(activity, route["submission_id"])
        )
        rebuilt = _hash(
            {
                "request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "route_definition": route["model_visible_definition"],
                "source_hashes": projection.sha256_by_ref,
            }
        )
        built.append(_smoke_case(case, request, rebuilt, projection.refs))

    for opportunity in definitions["p07_opportunities"]["opportunities"]:
        case_id = sb._case_id_for_opportunity(opportunity)
        if case_id not in by_id:
            continue
        case = by_id[case_id]
        request, envelope = build_p07_fixture(
            opportunity_fixture_id=opportunity["opportunity_fixture_id"],
            model_visible_definition=opportunity["model_visible_definition"],
            bundle=bundle_for(
                opportunity["activity_id"], opportunity["submission_id"]
            ),
        )
        support_ids = set(
            opportunity["model_visible_definition"]["support_evidence_ids"]
        )
        support_files = sorted(
            {
                source["relative_ref"]
                for source in opportunity["source_provenance"]
                if source["role"] == "SUBMISSION_SUPPORT"
                and {unit["evidence_id"] for unit in source["resolved_units"]}
                & support_ids
            }
        )
        projection = sb.project_model_visible_files(package, support_files)
        rebuilt = _hash(
            {
                "request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "opportunity_definition": opportunity["model_visible_definition"],
                "opportunity_fixture_id": opportunity["opportunity_fixture_id"],
                "source_hashes": projection.sha256_by_ref,
            }
        )
        built.append(_smoke_case(case, request, rebuilt, projection.refs))

    locator_by_fixture = {
        item["fixture_id"]: item
        for item in definitions["p09_locator_bindings"]["fixtures"]
    }
    fixture_path_by_id = {
        sb._json(package.root / path)["fixture_id"]: path
        for path, entry in package.entries.items()
        if entry["role"] == "P09_STAGE_FIXTURE"
    }
    for fixture in package.p09_fixtures:
        case_id = f"PP-A{sb._activity_number(fixture['activity_id']):02d}-P09-F01"
        if case_id not in by_id:
            continue
        case = by_id[case_id]
        activity = package.activity_by_id[fixture["activity_id"]]
        relative = fixture_path_by_id[fixture["fixture_id"]]
        projected, _model_ref, _oracle_ref = sb.project_p09_questions(
            package, relative
        )
        submission = next(
            item
            for item in activity["submissions"]
            if item["submission_id"] == fixture["submission_id"]
        )
        locator = locator_by_fixture[fixture["fixture_id"]]
        request, envelope, operation_projection, _integrity = build_p09_fixture(
            fixture=projected,
            locator_bindings=locator,
            bundle=bundle_for(fixture["activity_id"], fixture["submission_id"]),
            artifact_refs=submission["artifacts"],
            difficulty=sb._difficulty(activity["difficulty_declared"]),
            assignment_hash=(
                "sha256:"
                + package.entries[
                    f"{activity['activity_path']}/01_assignment.docx"
                ]["sha256"]
            ),
            rubric_hash=(
                "sha256:"
                + package.entries[f"{activity['activity_path']}/02_rubric.docx"][
                    "sha256"
                ]
            ),
        )
        rebuilt = _hash(
            {
                "frozen_questions_projection": projected,
                "guide_request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "operation_projection_version": sb.P09_OPERATION_PROJECTION_VERSION,
                "operation_projection": operation_projection,
                "locator_resolver_version": sb.P09_LOCATOR_RESOLVER_VERSION,
                "locator_binding": locator,
                "fixture_hash": package.entries[relative]["sha256"],
            }
        )
        projection = sb.project_model_visible_files(
            package,
            sb._source_refs_for_submission(activity, fixture["submission_id"]),
        )
        built.append(_smoke_case(case, request, rebuilt, projection.refs))

    if len(built) != len(frozen):
        raise Phase9ExecutionError(
            "PHASE9_SMOKE_PLAN_INCOMPLETE",
            f"rebuilt {len(built)} of {len(frozen)} frozen SMOKE cases",
        )
    return sorted(built, key=lambda item: (item.stage, item.case_id))


def _smoke_case(
    case: Mapping[str, Any],
    request: BaseModel,
    rebuilt_input_hash: str,
    model_visible_refs: Sequence[str],
) -> SmokeCase:
    if rebuilt_input_hash != case["input_hash"]:
        raise Phase9ExecutionError(
            "PHASE9_FROZEN_INPUT_HASH_MISMATCH",
            f"{case['case_id']} rebuilt to a different frozen input hash",
        )
    if case["corpus_boundary_hash"] != EXPECTED_CORPUS_BOUNDARY_HASH:
        raise Phase9ExecutionError(
            "PHASE9_SYNTHETIC_CORPUS_PROOF_FAILED",
            f"{case['case_id']} is not bound to the frozen synthetic corpus",
        )
    return SmokeCase(
        case_id=case["case_id"],
        stage=case["stage"],
        candidate=CANDIDATE_BY_STAGE[case["stage"]],
        fixture_ref=case["input_fixture_ref"],
        request=request,
        frozen_input_hash=case["input_hash"],
        rebuilt_input_hash=rebuilt_input_hash,
        model_visible_refs=tuple(model_visible_refs),
        property_ids=tuple(case["property_ids"]),
    )


def build_logical_calls(cases: Sequence[SmokeCase]) -> list[LogicalCall]:
    """Expand each frozen case to exactly ``k`` primary logical calls."""

    calls: list[LogicalCall] = []
    for case in cases:
        for run_index in range(1, AUTHORIZED_K + 1):
            calls.append(
                LogicalCall(
                    logical_call_id=(
                        f"{case.candidate.candidate_id}:{case.case_id}:run{run_index}"
                    ),
                    case=case,
                    run_index=run_index,
                )
            )
    return calls


# ---------------------------------------------------------------------------
# Pre-call dry authorization proof
# ---------------------------------------------------------------------------


def dry_authorization_proof(calls: Sequence[LogicalCall]) -> dict[str, Any]:
    """Prove offline what this authorization can and cannot reach.

    Every check below is a reachability statement about the plan that already
    exists in memory, so it costs nothing and runs before the authorization is
    consumed. A single failure stops the run before transport is constructed.
    """

    findings: list[str] = []
    reachable_candidates = sorted({call.case.candidate.candidate_id for call in calls})
    reachable_stages = sorted({call.case.stage for call in calls})
    reachable_models = sorted({call.case.candidate.model for call in calls})
    reachable_efforts = sorted(
        {call.case.candidate.reasoning_effort for call in calls}
    )
    reachable_profiles = sorted(
        {call.case.candidate.route_profile_id for call in calls}
    )

    if len(calls) != AUTHORIZED_PRIMARY_LOGICAL_CALLS:
        findings.append(
            f"primary logical call count is {len(calls)}, "
            f"expected {AUTHORIZED_PRIMARY_LOGICAL_CALLS}"
        )
    if len({call.logical_call_id for call in calls}) != len(calls):
        findings.append("logical call identities are not unique")
    authorized_ids = {item.candidate_id for item in AUTHORIZED_CANDIDATES}
    if set(reachable_candidates) != authorized_ids:
        findings.append("reachable candidate set differs from the authorized set")
    if set(reachable_candidates) & set(FORBIDDEN_CANDIDATE_IDS):
        findings.append("a forbidden candidate is reachable")
    if reachable_efforts != ["HIGH"]:
        findings.append(f"a non-HIGH reasoning rung is reachable: {reachable_efforts}")
    if "gpt-5.6-sol" in reachable_models:
        findings.append("Sol is reachable")
    if set(reachable_models) - {"gpt-5.6-luna", "gpt-5.6-terra"}:
        findings.append("an unapproved model family is reachable")
    if set(reachable_profiles) - {"TERRA_HIGH_V1", "LUNA_BASELINE_V1"}:
        findings.append("an unauthorized route profile is reachable")
    if set(reachable_stages) != {"P04", "P06", "P07", "P09"}:
        findings.append(f"unexpected stage surface: {reachable_stages}")

    # Family constraint: Terra owns the activity side, Luna the submission side.
    for call in calls:
        candidate = call.case.candidate
        if candidate.stage == "P04" and candidate.model != "gpt-5.6-terra":
            findings.append("P04 is not routed to Terra")
        if candidate.stage in {"P06", "P07", "P09"} and (
            candidate.model != "gpt-5.6-luna"
        ):
            findings.append(f"{candidate.stage} is not routed to Luna")

    frozen_smoke_ids = {case["case_id"] for case in _frozen_smoke_cases()}
    reached_cases = {call.case.case_id for call in calls}
    if reached_cases != frozen_smoke_ids:
        findings.append("reachable case set is not exactly the frozen SMOKE split")
    for call in calls:
        if call.case.rebuilt_input_hash != call.case.frozen_input_hash:
            findings.append(f"{call.case.case_id} is not the frozen request")

    runs_by_case: dict[str, set[int]] = {}
    for call in calls:
        runs_by_case.setdefault(call.case.case_id, set()).add(call.run_index)
    if any(runs != set(range(1, AUTHORIZED_K + 1)) for runs in runs_by_case.values()):
        findings.append("a case does not carry exactly k=3 run indices")

    # Per-call and outer caps are computed from the frozen worst-case output,
    # which is the full cap: reasoning tokens bill as output tokens.
    worst_case_total = 0.0
    for call in calls:
        candidate = call.case.candidate
        spec = prompt_spec(candidate.prompt_id)
        envelope = _envelope_for(candidate.prompt_id, call.case.request)
        input_upper_bound = estimate_openai_input_tokens(
            spec, call.case.request, envelope
        )
        ceiling = estimate_cost_usd(
            model=candidate.model,
            input_tokens=input_upper_bound,
            output_tokens=candidate.max_output_tokens,
        )
        if ceiling > candidate.per_call_cap_usd:
            findings.append(
                f"{call.logical_call_id} projects {ceiling:.6f} USD above its "
                f"frozen per-call cap {candidate.per_call_cap_usd:.6f} USD"
            )
        worst_case_total += ceiling
    if worst_case_total > OUTER_AUTHORIZATION_CAP_USD:
        findings.append(
            f"projected worst case {worst_case_total:.4f} USD breaches the "
            f"outer cap {OUTER_AUTHORIZATION_CAP_USD:.2f} USD"
        )

    rung_cap_total = sum(item.smoke_rung_cap_usd for item in AUTHORIZED_CANDIDATES)
    if rung_cap_total > OUTER_AUTHORIZATION_CAP_USD:
        findings.append("frozen rung caps sum above the outer authorization cap")

    proof = {
        "schema_version": "phase9-dry-authorization-proof/1.0.0",
        "generated_at": _utc_now(),
        "primary_logical_calls_reachable": len(calls),
        "expected_primary_logical_calls": AUTHORIZED_PRIMARY_LOGICAL_CALLS,
        "reachable_candidate_ids": reachable_candidates,
        "reachable_stages": reachable_stages,
        "reachable_models": reachable_models,
        "reachable_reasoning_efforts": reachable_efforts,
        "reachable_route_profiles": reachable_profiles,
        "reachable_splits": [AUTHORIZED_SPLIT],
        "unreachable": {
            "CORE": True,
            "HELD_OUT_CONFIRMATION": True,
            "XHIGH": True,
            "MAX": True,
            "SOL": True,
            "P01_P02_P03": True,
            "P05_P08": True,
            "P10": True,
            "P11_SEMANTIC_REPAIR": True,
            "CROSS_FAMILY_FALLBACK": True,
            "SEMANTIC_RETRY": True,
        },
        "fallback_routes_declared": 0,
        "semantic_retry_paths_declared": 0,
        "technical_retry_max_per_logical_call": (
            MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL
        ),
        "per_call_cap_enforced_before_transport": True,
        "outer_cap_enforced_before_transport": True,
        "projected_worst_case_total_usd": round(worst_case_total, 6),
        "outer_authorization_cap_usd": OUTER_AUTHORIZATION_CAP_USD,
        "frozen_rung_cap_total_usd": round(rung_cap_total, 6),
        "findings": findings,
        "result": "PASS" if not findings else "BLOCKED",
    }
    proof["proof_hash"] = _hash(proof)
    if findings:
        raise Phase9ExecutionError(
            "PHASE9_AUTHORIZATION_FAILED",
            "; ".join(findings),
        )
    return proof


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


# ---------------------------------------------------------------------------
# Billable authorization
# ---------------------------------------------------------------------------


def build_authorization(
    *,
    boundaries: Mapping[str, Any],
    pricing: Mapping[str, Any],
    calls: Sequence[LogicalCall],
    proof: Mapping[str, Any],
    created_by: str,
) -> dict[str, Any]:
    """Create the single hash-bound, exactly-once authorization for this batch."""

    material = {
        "schema_version": "phase9-billable-authorization/1.0.0",
        "phase": "PHASE_9B_1",
        "purpose": "REAL_SMOKE_HIGH_GENERATION",
        "created_at": _utc_now(),
        "created_by": created_by,
        "benchmark_version": "semantic-benchmark/1.1.0",
        "protocol_version": "phase9-qualification-protocol/1.1.0",
        "benchmark_boundary_hash": boundaries["benchmark_boundary_hash"],
        "protocol_boundary_hash": boundaries["protocol_boundary_hash"],
        "candidate_matrix_hash": boundaries["candidate_matrix_hash"],
        "corpus_package_boundary_hash": boundaries["corpus_package_boundary_hash"],
        "split": AUTHORIZED_SPLIT,
        "k": AUTHORIZED_K,
        "allowed_candidate_ids": sorted(
            item.candidate_id for item in AUTHORIZED_CANDIDATES
        ),
        "allowed_case_ids": sorted({call.case.case_id for call in calls}),
        "allowed_logical_call_ids": sorted(call.logical_call_id for call in calls),
        "primary_logical_calls": len(calls),
        "technical_retry_policy": {
            "max_attempts_per_logical_call": (
                1 + MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL
            ),
            "retryable_codes": sorted(RETRYABLE_TECHNICAL_CODES),
            "semantic_retry": "FORBIDDEN",
            "candidate_fallback": "FORBIDDEN",
        },
        "outer_budget_cap_usd": OUTER_AUTHORIZATION_CAP_USD,
        "per_call_caps_usd": {
            item.candidate_id: item.per_call_cap_usd
            for item in AUTHORIZED_CANDIDATES
        },
        "rung_caps_usd": {
            item.candidate_id: item.smoke_rung_cap_usd
            for item in AUTHORIZED_CANDIDATES
        },
        "pricing_evidence": dict(pricing),
        "dry_authorization_proof_hash": proof["proof_hash"],
        "excluded_scope": list(EXCLUDED_FROM_AUTHORIZATION),
        "excluded_candidate_ids": list(FORBIDDEN_CANDIDATE_IDS),
        "not_a_phase9_global_authorization": True,
        "escalation_authorized": False,
    }
    authorization_hash = _hash(material)
    return {
        **material,
        "authorization_hash": authorization_hash,
        "authorization_id": f"phase9b1-{authorization_hash.removeprefix('sha256:')[:16]}",
        "consumption": {
            "state": "CREATED_NOT_CONSUMED",
            "consumed_at": None,
            "consumed_once": False,
        },
    }


def execution_id_for(authorization: Mapping[str, Any]) -> str:
    """Derive a deterministic, hash-bound and immutable execution identity."""

    digest = authorization["authorization_hash"].removeprefix("sha256:")
    return f"exec-phase9b1-{digest[:16]}"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class CapturingAdapter:
    """Record raw provider evidence without changing transport behaviour.

    The gateway compiles each provider draft into its canonical stage contract
    before returning, so the draft itself would otherwise be unrecoverable. The
    adjudicator never sees this surface; it exists so the execution evidence can
    show exactly what the provider returned.
    """

    def __init__(self, inner: Any, *, max_requests: int) -> None:
        if not 1 <= max_requests <= 64:
            raise ValueError("provider request cap must be between 1 and 64")
        self.inner = inner
        self.config = getattr(inner, "config", None)
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
        started = time.monotonic()
        result = await self.inner.invoke(**kwargs)
        self.captured.append(
            {
                "raw_output": result.raw_output,
                "output_hash": result.output_hash,
                "effective_model": result.effective_model,
                "provider_request_id_hash": result.provider_request_id_hash,
                "provider_schema_valid": result.provider_schema_valid,
                "provider_schema_issues": list(result.provider_schema_issues),
                "input_tokens": result.input_tokens,
                "cached_input_tokens": result.cached_input_tokens,
                "cache_write_input_tokens": result.cache_write_input_tokens,
                "output_tokens": result.output_tokens,
                "reasoning_tokens": result.reasoning_tokens,
                "estimated_cost_usd": result.estimated_cost_usd,
                "actual_cost_usd": result.actual_cost_usd,
                "reason_codes": list(result.reason_codes),
                "adapter_latency_ms": int((time.monotonic() - started) * 1000),
            }
        )
        return result

    def take(self) -> dict[str, Any] | None:
        return self.captured[-1] if self.captured else None


def _gateway_for(
    candidate: AuthorizedCandidate, adapter: Any, *, job_id: str
) -> ModelGateway:
    routes = build_openai_routes(
        max_call_cost_usd=candidate.per_call_cap_usd,
        route_profile_id=candidate.route_profile_id,
    )
    return ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=(
                OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
                + OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS
            ),
            max_retries=0,
            default_budget_usd=candidate.per_call_cap_usd,
            job_id=job_id,
        ),
        real_routes=routes,
        adapters={"openai": adapter},
        cost_estimator=build_openai_cost_estimator(routes),
        input_token_estimator=estimate_openai_input_tokens,
    )


def _reasoning_tokens_from(reason_codes: Iterable[str]) -> int:
    for code in reason_codes:
        if code.startswith("REASONING_TOKENS_"):
            value = code.removeprefix("REASONING_TOKENS_")
            if value.isdigit():
                return int(value)
    return 0


@dataclass
class CostAccount:
    """Running spend, checked against every cap before the next request."""

    outer_cap_usd: float = OUTER_AUTHORIZATION_CAP_USD
    spent_usd: float = 0.0
    by_stage: dict[str, float] = field(default_factory=dict)
    by_candidate: dict[str, float] = field(default_factory=dict)

    def admit(self, candidate: AuthorizedCandidate, projected_usd: float) -> None:
        """Fail closed before transport if this request could breach any cap."""

        if projected_usd > candidate.per_call_cap_usd:
            raise Phase9ExecutionError(
                "PHASE9_PER_CALL_CAP_WOULD_BE_EXCEEDED",
                f"{candidate.candidate_id} projects {projected_usd:.6f} USD",
            )
        rung_spent = self.by_candidate.get(candidate.candidate_id, 0.0)
        if rung_spent + projected_usd > candidate.smoke_rung_cap_usd:
            raise Phase9ExecutionError(
                "PHASE9_RUNG_CAP_WOULD_BE_EXCEEDED",
                f"{candidate.candidate_id} would exceed its frozen SMOKE cap",
            )
        if self.spent_usd + projected_usd > self.outer_cap_usd:
            raise Phase9ExecutionError(
                "PHASE9_OUTER_CAP_WOULD_BE_EXCEEDED",
                f"cumulative spend would exceed USD {self.outer_cap_usd:.2f}",
            )

    def charge(self, candidate: AuthorizedCandidate, actual_usd: float) -> None:
        self.spent_usd += actual_usd
        self.by_stage[candidate.stage] = (
            self.by_stage.get(candidate.stage, 0.0) + actual_usd
        )
        self.by_candidate[candidate.candidate_id] = (
            self.by_candidate.get(candidate.candidate_id, 0.0) + actual_usd
        )


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One provider attempt, primary or technical retry."""

    payload: dict[str, Any]

    @property
    def status(self) -> str:
        return str(self.payload["response_status"])


_DETERMINISTIC_FAILURE_MARKERS: Final = (
    "DRAFT_COMPILATION_FAILED",
    "DRAFT_MATERIALIZATION_FAILED",
    "SOURCE_COVERAGE_MISMATCH",
    "ALIAS_REFERENCE_UNKNOWN",
    "SCOPE_ALIAS_MISMATCH",
    "APPROVAL_BINDING_MISMATCH",
    "ANCHOR",
    "EVIDENCE",
    "ALLOWLIST",
    "NOT_ALLOWLISTED",
)


def _classify_failure(exc: BaseException) -> tuple[str, str]:
    """Separate the four failure kinds this phase must never conflate.

    A deterministic/materializer rejection is a product-boundary result, a
    provider transport error is a technical failure, and neither is ever a
    semantic verdict. Anything unrecognised stays unclassified and
    non-retryable rather than being optimistically called transient.
    """

    codes = tuple(
        str(getattr(item, "value", item))
        for item in getattr(getattr(exc, "failure", None), "codes", ())
    )
    detail = codes[0] if codes else str(
        getattr(exc, "code", None) or type(exc).__name__
    )
    if codes:
        joined = "|".join(codes)
        if any(marker in joined for marker in _DETERMINISTIC_FAILURE_MARKERS):
            return "DETERMINISTIC_VALIDATION_FAILURE", detail
        return "CONTRACT_OR_SCHEMA_FAILURE", detail
    if detail in RETRYABLE_TECHNICAL_CODES:
        return "PROVIDER_TECHNICAL_FAILURE", detail
    if detail.startswith("PROVIDER_"):
        return "PROVIDER_TECHNICAL_FAILURE", detail
    if "SCHEMA" in detail or "CONTRACT" in detail:
        return "CONTRACT_OR_SCHEMA_FAILURE", detail
    return "UNCLASSIFIED_TECHNICAL_FAILURE", detail


def _attempt_payload(
    *,
    call: LogicalCall,
    attempt_index: int,
    authorization: Mapping[str, Any],
    boundaries: Mapping[str, Any],
    envelope_hash: str,
    status: str,
    captured: Mapping[str, Any] | None,
    ledger: Any | None,
    latency_ms: int,
    diagnostic: Mapping[str, Any] | None,
    retry_of: str | None,
) -> dict[str, Any]:
    candidate = call.case.candidate
    reason_codes = list(captured["reason_codes"]) if captured else []
    reasoning_tokens = (
        int(captured["reasoning_tokens"])
        if captured and captured.get("reasoning_tokens") is not None
        else _reasoning_tokens_from(reason_codes)
    )
    input_tokens = int(captured["input_tokens"]) if captured else 0
    cached_tokens = int(captured["cached_input_tokens"]) if captured else 0
    output_tokens = int(captured["output_tokens"]) if captured else 0
    actual_cost = float(captured["actual_cost_usd"]) if captured else 0.0
    return {
        "logical_call_id": call.logical_call_id,
        "attempt_index": attempt_index,
        "retry_of_attempt": retry_of,
        "is_technical_retry": retry_of is not None,
        "is_new_semantic_sample": False,
        "case_id": call.case.case_id,
        "stage": call.case.stage,
        "run_index": call.run_index,
        "candidate_id": candidate.candidate_id,
        "model": candidate.model,
        "effective_model": (captured or {}).get("effective_model"),
        "reasoning_effort": candidate.reasoning_effort,
        "route_profile_id": candidate.route_profile_id,
        "prompt_id": candidate.prompt_id,
        "max_output_tokens": candidate.max_output_tokens,
        "request_hash": call.case.rebuilt_input_hash,
        "model_visible_input_hash": envelope_hash,
        "frozen_benchmark_input_hash": call.case.frozen_input_hash,
        "provider_response_id_hash": (captured or {}).get(
            "provider_request_id_hash"
        ),
        "response_status": status,
        "provider_output_hash": (captured or {}).get("output_hash"),
        "provider_schema_valid": (captured or {}).get("provider_schema_valid"),
        "provider_schema_issues": list(
            (captured or {}).get("provider_schema_issues", [])
        ),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_write_input_tokens": int(
            (captured or {}).get("cache_write_input_tokens", 0) or 0
        ),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": input_tokens + output_tokens,
        "actual_cost_usd": round(actual_cost, 8),
        "estimated_cost_usd": round(
            float((captured or {}).get("estimated_cost_usd", 0.0) or 0.0), 8
        ),
        "latency_ms": latency_ms,
        "provider_reason_codes": reason_codes,
        "technical_diagnostic": dict(diagnostic) if diagnostic else None,
        "ledger_attempt": getattr(ledger, "attempt", None),
        "ledger_prompt_hash": getattr(ledger, "prompt_hash", None),
        "ledger_input_bundle_hash": getattr(ledger, "input_bundle_hash", None),
        "timestamp": _utc_now(),
        "authorization_id": authorization["authorization_id"],
        "authorization_hash": authorization["authorization_hash"],
        "benchmark_boundary_hash": boundaries["benchmark_boundary_hash"],
        "protocol_boundary_hash": boundaries["protocol_boundary_hash"],
        "candidate_matrix_hash": boundaries["candidate_matrix_hash"],
        "semantic_status": "PENDING_ADJUDICATION",
    }


def default_adapter_factory(api_key: SecretStr) -> Any:
    """Build the one real provider adapter this execution is allowed to use."""

    return OpenAIResponsesAdapter(
        api_key=api_key,
        config=OpenAIAdapterConfig(
            request_timeout_seconds=OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
    )


async def _execute_logical_call(
    *,
    call: LogicalCall,
    api_key: SecretStr,
    authorization: Mapping[str, Any],
    boundaries: Mapping[str, Any],
    account: CostAccount,
    remaining_requests: int,
    adapter_factory: Any = default_adapter_factory,
) -> tuple[list[dict[str, Any]], Any | None, int]:
    """Run one logical call with at most one allowlisted technical retry."""

    candidate = call.case.candidate
    spec = prompt_spec(candidate.prompt_id)
    envelope = _envelope_for(candidate.prompt_id, call.case.request)
    envelope_hash = _hash(envelope.model_dump(mode="json"))
    input_upper_bound = estimate_openai_input_tokens(spec, call.case.request, envelope)
    projected = estimate_cost_usd(
        model=candidate.model,
        input_tokens=input_upper_bound,
        output_tokens=candidate.max_output_tokens,
    )

    attempts: list[dict[str, Any]] = []
    output: Any | None = None
    used_requests = 0

    for attempt_index in range(1, MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL + 2):
        if used_requests >= remaining_requests:
            raise Phase9ExecutionError(
                "PHASE9_PROVIDER_REQUEST_CAP_EXCEEDED",
                "no authorized provider request remains",
            )
        account.admit(candidate, projected)

        adapter = CapturingAdapter(adapter_factory(api_key), max_requests=1)
        gateway = _gateway_for(
            candidate, adapter, job_id=f"job_phase9b1_{call.case.stage.lower()}"
        )
        started = time.monotonic()
        try:
            result = await gateway.invoke(
                candidate.prompt_id,
                call.case.request,
                envelope.trusted_context,
                budget=CallBudget(max_cost_usd=candidate.per_call_cap_usd),
            )
        except (GatewayError, Exception) as exc:  # noqa: BLE001 - fail closed
            latency_ms = int((time.monotonic() - started) * 1000)
            captured = adapter.take()
            used_requests += adapter.calls
            kind, code = _classify_failure(exc)
            if captured is not None:
                account.charge(candidate, float(captured["actual_cost_usd"]))
            attempts.append(
                _attempt_payload(
                    call=call,
                    attempt_index=attempt_index,
                    authorization=authorization,
                    boundaries=boundaries,
                    envelope_hash=envelope_hash,
                    status="FAILED",
                    captured=captured,
                    ledger=None,
                    latency_ms=latency_ms,
                    diagnostic={"failure_kind": kind, "failure_code": code},
                    retry_of=(
                        attempts[-1]["logical_call_id"] if attempts else None
                    ),
                )
            )
            retryable = (
                kind == "PROVIDER_TECHNICAL_FAILURE"
                and code in RETRYABLE_TECHNICAL_CODES
                and attempt_index <= MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL
            )
            if retryable:
                continue
            return attempts, None, used_requests

        latency_ms = int((time.monotonic() - started) * 1000)
        captured = adapter.take()
        used_requests += adapter.calls
        ledger = result.ledgers[-1] if result.ledgers else None
        if captured is not None:
            account.charge(candidate, float(captured["actual_cost_usd"]))
        attempts.append(
            _attempt_payload(
                call=call,
                attempt_index=attempt_index,
                authorization=authorization,
                boundaries=boundaries,
                envelope_hash=envelope_hash,
                status="COMPLETED",
                captured=captured,
                ledger=ledger,
                latency_ms=latency_ms,
                diagnostic=None,
                retry_of=None,
            )
        )
        output = result.output
        return attempts, output, used_requests

    return attempts, output, used_requests


# ---------------------------------------------------------------------------
# Deterministic product validation
# ---------------------------------------------------------------------------


def run_deterministic_validation(
    *, stage: str, output: BaseModel, request: BaseModel
) -> dict[str, Any]:
    """Replay the stage's deterministic boundary over the compiled output.

    The gateway already compiled the provider draft; this is the independent
    re-check that the compiled artifact still validates against the trusted
    request. Product code is never adjusted to make an output pass.
    """

    from .blueprint_compiler import (
        BlueprintCompilationError,
        validate_compiled_blueprint,
    )
    from .evidence_mapping import (
        EvidenceMappingCompilationError,
        validate_materialized_evidence_mapping,
    )
    from .guide_generation import (
        GuideGenerationCompilationError,
        validate_materialized_guide,
    )
    from .question_generation import (
        QuestionGenerationCompilationError,
        validate_materialized_question_result,
    )

    boundary = {
        "P04": "BLUEPRINT_COMPILER_AND_VALIDATORS",
        "P06": "EVIDENCE_MAPPING_MATERIALIZER",
        "P07": "QUESTION_MATERIALIZER_AND_EVIDENCE_ANCHOR_VALIDATORS",
        "P09": "GUIDE_MATERIALIZER_AND_VALIDATORS",
    }[stage]
    try:
        if stage == "P04":
            validate_compiled_blueprint(blueprint=output, request=request)
        elif stage == "P06":
            validate_materialized_evidence_mapping(mapping=output, request=request)
        elif stage == "P07":
            validate_materialized_question_result(result=output, request=request)
        else:
            validate_materialized_guide(guide=output, request=request)
    except (
        BlueprintCompilationError,
        EvidenceMappingCompilationError,
        QuestionGenerationCompilationError,
        GuideGenerationCompilationError,
    ) as exc:
        return {
            "stage": stage,
            "boundary": boundary,
            "result": "DETERMINISTIC_VALIDATION_FAILURE",
            "code": getattr(exc, "code", type(exc).__name__),
        }
    except Exception as exc:  # noqa: BLE001 - unknown failures stay fail-closed
        return {
            "stage": stage,
            "boundary": boundary,
            "result": "CONTRACT_OR_SCHEMA_FAILURE",
            "code": type(exc).__name__,
        }
    return {
        "stage": stage,
        "boundary": boundary,
        "result": "PASS",
        "code": None,
        "semantic_status": "PENDING_ADJUDICATION",
    }


# ---------------------------------------------------------------------------
# Blind review packets
# ---------------------------------------------------------------------------

FORBIDDEN_PACKET_FIELDS: Final = (
    "candidate_model",
    "candidate_model_family",
    "candidate_id",
    "candidate_snapshot",
    "reasoning_effort",
    "max_output_tokens",
    "candidate_cost",
    "candidate_cost_usd",
    "promotion_order",
    "split",
    "split_name",
    "rung",
    "is_held_out",
    "other_candidate_results",
    "other_run_results",
    "current_ranking",
    "opus_audit_history",
    "old_qualification_results",
    "first_pass_decision",
    "first_pass_rationale",
    "first_pass_confidence",
    "latency_ms",
    "attempt_count",
)

# A full model identifier can never be legitimate corpus content, so it is a
# leak wherever it appears — including inside the candidate output itself.
HARD_MODEL_IDENTITY_TOKENS: Final = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.6",
)

LEAKAGE_TOKENS: Final = (
    "gpt-5.6",
    "luna",
    "terra",
    "sol",
    "XHIGH",
    "MAX",
    "candidate",
    "SMOKE",
    "CORE",
    "HELD_OUT",
    "promotion",
    "cost",
    "USD",
    "route_profile",
    "reasoning_effort",
    "HIGH",
)

# Fields whose values are authorized source material or ratified property text.
# A sensitive substring inside these is student/benchmark content, not run
# metadata, so it is documented as an exception rather than treated as a leak.
SOURCE_CONTENT_PATHS: Final = (
    "candidate_output",
    "property",
    "defensible_alternatives",
    "relevant_source_refs",
)


def _walk_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def _walk_keys(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, str(key)
            yield from _walk_keys(item, child)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk_keys(item, f"{path}[{index}]")


def scan_packet_for_leakage(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanically verify one packet carries no run/candidate metadata."""

    allowed = set(
        json.loads(
            (PHASE9_DEFINITION_ROOT / "adjudication_protocol.json").read_text("utf-8")
        )["blinding"]["allowed_packet_fields"]
    )
    leaks: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []

    def is_content(path: str) -> bool:
        return path.split(".")[0].split("[")[0] in SOURCE_CONTENT_PATHS

    unexpected_top_level = sorted(set(packet) - allowed)
    for name in unexpected_top_level:
        leaks.append({"kind": "UNEXPECTED_TOP_LEVEL_FIELD", "path": name})

    for path, key in _walk_keys(packet):
        if key not in FORBIDDEN_PACKET_FIELDS:
            continue
        if is_content(path):
            # Inside the candidate output the product's own canonical contract
            # applies: P07's ``candidate_id`` names a question candidate and
            # carries no model, rung or split identity.
            exceptions.append(
                {
                    "path": path,
                    "field": key,
                    "justification": (
                        "domain contract field inside authorized output content, "
                        "not Phase 9 run metadata"
                    ),
                }
            )
        else:
            leaks.append({"kind": "FORBIDDEN_FIELD_NAME", "path": path, "field": key})

    for path, text in _walk_strings(packet):
        folded = text.casefold()
        for token in HARD_MODEL_IDENTITY_TOKENS:
            if token in folded:
                leaks.append(
                    {
                        "kind": "MODEL_IDENTITY",
                        "path": path,
                        "token": token,
                        "value_preview": text[:120],
                    }
                )
                break
        for token in LEAKAGE_TOKENS:
            if token.casefold() not in folded:
                continue
            record = {
                "path": path,
                "token": token,
                "value_preview": text[:120],
            }
            if is_content(path):
                exceptions.append(
                    {
                        **record,
                        "justification": (
                            "occurs inside authorized source or ratified property "
                            "content, not run metadata"
                        ),
                    }
                )
            else:
                leaks.append({"kind": "METADATA_TOKEN", **record})

    return {
        "packet_id": packet.get("packet_id"),
        "leaks": leaks,
        "documented_exceptions": exceptions,
        "result": "PASS" if not leaks else "BLOCKED",
    }


def build_blind_packets(
    *,
    outputs_by_case: Mapping[str, Sequence[tuple[int, Any]]],
) -> list[dict[str, Any]]:
    """Project every completed run into pseudonymous, blind review packets."""

    build = sb.build_benchmark(verify_parser_twice=False)
    case_by_id = {case["case_id"]: case for case in build.cases}
    property_by_id = {item["property_id"]: item for item in build.properties}
    binding_by_property = {
        item["property_id"]: item
        for item in build.fixture_definitions["property_bindings"]["bindings"]
    }
    packets: list[dict[str, Any]] = []
    for case_id in sorted(outputs_by_case):
        case = case_by_id[case_id]
        for run_index, output in sorted(outputs_by_case[case_id]):
            payload = (
                output.model_dump(mode="json")
                if isinstance(output, BaseModel)
                else output
            )
            for property_id in case["property_ids"]:
                property_value = property_by_id[property_id]
                if (
                    property_value["evaluator_mode"]
                    != sb.EvaluatorMode.EXTERNAL_ADJUDICATION_REQUIRED
                ):
                    continue
                packet = sb.make_review_packet(
                    case=case,
                    property_value=property_value,
                    binding=binding_by_property[property_id],
                    candidate_output=payload,
                )
                identity = _hash(
                    {
                        "packet": packet,
                        "run_index": run_index,
                        "namespace": "phase9-blind-packet/1.0.0",
                    }
                )
                packets.append(
                    {
                        # The pseudonymous id lives beside the packet, never
                        # inside it: the packet body must stay exactly the
                        # fields semantic-review-packet/1.1.0 allows.
                        "packet_id": f"pkt-{identity.removeprefix('sha256:')[:20]}",
                        "packet_hash": _hash(packet),
                        "packet": packet,
                    }
                )
    # Ordered by pseudonymous id so manifest position reveals no case, run or
    # promotion ordering.
    return sorted(packets, key=lambda item: item["packet_id"])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _repo_relative(path: Path) -> str:
    """Repository-relative when inside the repo, absolute otherwise (tests)."""

    try:
        return str(path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return str(path)


def _write(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return _hash(payload)


def run_phase9b_smoke(
    *,
    api_key: SecretStr | None,
    created_by: str,
    evidence_root: Path = EXECUTION_EVIDENCE_ROOT,
    adjudication_root: Path | None = None,
    transport: bool = True,
    adapter_factory: Any = default_adapter_factory,
) -> dict[str, Any]:
    """Execute the authorized HIGH SMOKE batch and stop before adjudication."""

    boundaries = revalidate_frozen_boundaries()
    pricing = verify_pricing_snapshot()
    cases = build_smoke_cases()
    calls = build_logical_calls(cases)
    proof = dry_authorization_proof(calls)
    authorization = build_authorization(
        boundaries=boundaries,
        pricing=pricing,
        calls=calls,
        proof=proof,
        created_by=created_by,
    )
    execution_id = execution_id_for(authorization)
    execution_dir = evidence_root / execution_id
    if execution_dir.exists():
        raise Phase9ExecutionError(
            "PHASE9_EXECUTION_EVIDENCE_EXISTS",
            f"{execution_id} already holds a real execution and is immutable",
        )
    if not transport:
        return {
            "status": "DRY_RUN",
            "execution_id": execution_id,
            "authorization_id": authorization["authorization_id"],
            "authorization_hash": authorization["authorization_hash"],
            "dry_authorization_proof": proof,
            "primary_logical_calls": len(calls),
            "provider_calls": 0,
            "billable_authorizations_consumed": 0,
        }
    if api_key is None:
        raise Phase9ExecutionError(
            "OPENAI_CREDENTIAL_REQUIRED",
            "no securely resolved provider credential is available",
        )

    # Consume the authorization exactly once, immediately before transport.
    authorization = {
        **authorization,
        "consumption": {
            "state": "CONSUMED",
            "consumed_at": _utc_now(),
            "consumed_once": True,
        },
    }

    account = CostAccount()
    attempts: list[dict[str, Any]] = []
    deterministic: list[dict[str, Any]] = []
    outputs_by_case: dict[str, list[tuple[int, Any]]] = {}
    provider_outputs: dict[str, Any] = {}
    remaining = AUTHORIZED_PRIMARY_LOGICAL_CALLS + (
        MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL * AUTHORIZED_PRIMARY_LOGICAL_CALLS
    )
    technical_stop: dict[str, Any] | None = None

    # Deterministic order; no output ever influences a later request.
    ordered = sorted(
        calls,
        key=lambda call: (
            ["P04", "P06", "P07", "P09"].index(call.case.stage),
            call.case.case_id,
            call.run_index,
        ),
    )
    for call in ordered:
        try:
            call_attempts, output, used = asyncio.run(
                _execute_logical_call(
                    call=call,
                    api_key=api_key,
                    authorization=authorization,
                    boundaries=boundaries,
                    account=account,
                    remaining_requests=remaining,
                    adapter_factory=adapter_factory,
                )
            )
        except Phase9ExecutionError as exc:
            technical_stop = {"code": exc.code, "logical_call_id": call.logical_call_id}
            break
        remaining -= used
        attempts.extend(call_attempts)
        if output is None:
            continue
        payload = (
            output.model_dump(mode="json")
            if isinstance(output, BaseModel)
            else output
        )
        provider_outputs[call.logical_call_id] = payload
        outputs_by_case.setdefault(call.case.case_id, []).append(
            (call.run_index, output)
        )
        deterministic.append(
            {
                "logical_call_id": call.logical_call_id,
                **run_deterministic_validation(
                    stage=call.case.stage,
                    output=output,
                    request=call.case.request,
                ),
            }
        )

    packets = build_blind_packets(outputs_by_case=outputs_by_case)
    scans = [scan_packet_for_leakage(item["packet"]) for item in packets]
    blocked = [scan for scan in scans if scan["result"] != "PASS"]

    completed = [item for item in attempts if item["response_status"] == "COMPLETED"]
    failed = [item for item in attempts if item["response_status"] == "FAILED"]
    retries = [item for item in attempts if item["is_technical_retry"]]

    def failures_of(kind: str) -> list[dict[str, Any]]:
        return [
            item
            for item in failed
            if (item["technical_diagnostic"] or {}).get("failure_kind") == kind
        ]

    # The protocol gates *technical* failure rate at 2%. A deterministic or
    # materializer rejection is a different category entirely and must never be
    # counted into that gate, nor read as a semantic verdict.
    provider_technical = failures_of("PROVIDER_TECHNICAL_FAILURE") + failures_of(
        "UNCLASSIFIED_TECHNICAL_FAILURE"
    )
    deterministic_failures = failures_of("DETERMINISTIC_VALIDATION_FAILURE")
    contract_failures = failures_of("CONTRACT_OR_SCHEMA_FAILURE")

    usage = {
        "input_tokens": sum(item["input_tokens"] for item in attempts),
        "cached_input_tokens": sum(item["cached_input_tokens"] for item in attempts),
        "output_tokens": sum(item["output_tokens"] for item in attempts),
        "reasoning_tokens": sum(item["reasoning_tokens"] for item in attempts),
        "total_tokens": sum(item["total_tokens"] for item in attempts),
    }
    cost = {
        "actual_total_usd": round(account.spent_usd, 8),
        "outer_authorization_cap_usd": OUTER_AUTHORIZATION_CAP_USD,
        "within_outer_cap": account.spent_usd <= OUTER_AUTHORIZATION_CAP_USD,
        "by_stage_usd": {k: round(v, 8) for k, v in sorted(account.by_stage.items())},
        "by_candidate_usd": {
            k: round(v, 8) for k, v in sorted(account.by_candidate.items())
        },
        "by_call_usd": {
            item["logical_call_id"]: item["actual_cost_usd"] for item in attempts
        },
        "pricing_evidence": pricing,
    }
    accounting = {
        "authorization_consumed_exactly_once": True,
        "primary_logical_calls_authorized": AUTHORIZED_PRIMARY_LOGICAL_CALLS,
        "primary_logical_calls_attempted": len(
            {item["logical_call_id"] for item in attempts}
        ),
        "primary_logical_calls_completed": len(completed),
        "technical_retry_attempts": len(retries),
        "attempts_not_completed": len(failed),
        "provider_technical_failures": len(provider_technical),
        "deterministic_validation_failures": len(deterministic_failures),
        "contract_or_schema_failures": len(contract_failures),
        "technical_failure_rate": (
            round(len(provider_technical) / len(attempts), 6) if attempts else 0.0
        ),
        "unauthorized_candidates_reaching_transport": 0,
        "core_calls": 0,
        "held_out_calls": 0,
        "xhigh_calls": 0,
        "max_calls": 0,
        "sol_calls": 0,
        "p01_p02_p03_calls": 0,
        "p10_p11_calls": 0,
        "semantic_retries": 0,
        "actual_spend_within_cap": account.spent_usd <= OUTER_AUTHORIZATION_CAP_USD,
    }

    status = "REAL_SMOKE_HIGH_GENERATION_COMPLETE_AWAITING_BLIND_ADJUDICATION"
    if technical_stop is not None:
        status = "PHASE9_SMOKE_GENERATION_TECHNICAL_STOP"
    elif blocked:
        status = "PHASE9_BLIND_PACKET_LEAKAGE_BLOCKED"

    manifest = {
        "schema_version": PHASE9_EXECUTION_VERSION,
        "execution_id": execution_id,
        "phase": "PHASE_9B_1",
        "generated_at": _utc_now(),
        "benchmark_version": "semantic-benchmark/1.1.0",
        "protocol_version": "phase9-qualification-protocol/1.1.0",
        **boundaries,
        "split": AUTHORIZED_SPLIT,
        "k": AUTHORIZED_K,
        "candidate_ids": sorted(item.candidate_id for item in AUTHORIZED_CANDIDATES),
        "case_ids": sorted({call.case.case_id for call in calls}),
        "authorization_id": authorization["authorization_id"],
        "authorization_hash": authorization["authorization_hash"],
        "transport": "REAL_OPENAI_RESPONSES_API",
        "service_tier": "STANDARD",
        "status": status,
        "technical_stop": technical_stop,
        "semantic_status": "PENDING_ADJUDICATION",
        "semantic_adjudication_performed_here": False,
        "escalation_performed": False,
        "blind_packet_count": len(packets),
        "accounting": accounting,
    }

    execution_dir.mkdir(parents=True, exist_ok=False)
    hashes = {
        "authorization.json": _write(
            execution_dir / "authorization.json", authorization
        ),
        "dry_authorization_proof.json": _write(
            execution_dir / "dry_authorization_proof.json", proof
        ),
        "call_ledger.json": _write(
            execution_dir / "call_ledger.json",
            {
                "schema_version": "phase9-call-ledger/1.0.0",
                "execution_id": execution_id,
                "attempts": attempts,
            },
        ),
        "usage_and_cost.json": _write(
            execution_dir / "usage_and_cost.json",
            {
                "schema_version": "phase9-usage-and-cost/1.0.0",
                "execution_id": execution_id,
                "usage": usage,
                "cost": cost,
            },
        ),
        "deterministic_validation/report.json": _write(
            execution_dir / "deterministic_validation/report.json",
            {
                "schema_version": "phase9-deterministic-validation/1.0.0",
                "execution_id": execution_id,
                "results": deterministic,
                "semantic_status": "PENDING_ADJUDICATION",
            },
        ),
    }
    for logical_call_id, payload in sorted(provider_outputs.items()):
        name = logical_call_id.replace(":", "__")
        hashes[f"provider_outputs/{name}.json"] = _write(
            execution_dir / "provider_outputs" / f"{name}.json", payload
        )

    bundle_root = (
        adjudication_root
        if adjudication_root is not None
        else BENCHMARK_REPORT_ROOT / "phase9/adjudication_bundles" / execution_id
    )
    bundle_manifest = _write_blind_bundle(bundle_root, packets, scans)
    hashes["blind_bundle_manifest.json"] = _write(
        execution_dir / "blind_bundle_manifest.json",
        {
            "schema_version": "phase9-blind-bundle-pointer/1.0.0",
            "execution_id": execution_id,
            "bundle_manifest_hash": bundle_manifest["manifest_hash"],
            "packet_count": bundle_manifest["packet_count"],
            "bundle_path": _repo_relative(bundle_root),
            "leakage_audit": {
                "packets_scanned": len(scans),
                "leaks": sum(len(scan["leaks"]) for scan in scans),
                "documented_exceptions": sum(
                    len(scan["documented_exceptions"]) for scan in scans
                ),
                "result": "PASS" if not blocked else "BLOCKED",
            },
        },
    )
    hashes["execution_manifest.json"] = _write(
        execution_dir / "execution_manifest.json",
        {**manifest, "evidence_hashes": hashes},
    )

    return {
        "status": status,
        "execution_id": execution_id,
        "execution_dir": _repo_relative(execution_dir),
        "authorization_id": authorization["authorization_id"],
        "authorization_hash": authorization["authorization_hash"],
        "usage": usage,
        "cost": cost,
        "accounting": accounting,
        "deterministic_validation": deterministic,
        "attempts": attempts,
        "blind_packet_count": len(packets),
        "blind_bundle": bundle_manifest,
        "leakage_blocked": [scan for scan in blocked],
        "evidence_hashes": hashes,
        "semantic_status": "PENDING_ADJUDICATION",
    }


def _write_blind_bundle(
    root: Path,
    packets: Sequence[Mapping[str, Any]],
    scans: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Materialize the adjudicator-safe bundle and its metadata-free manifest."""

    schema = json.loads(
        (
            REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_1/schemas/review_packet.schema.json"
        ).read_text("utf-8")
    )
    packet_dir = root / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in packets:
        # Filename is the pseudonymous id only: no stage order, run index,
        # candidate or split may be recoverable from the path.
        filename = f"{item['packet_id']}.json"
        _write(packet_dir / filename, item["packet"])
        rows.append(
            {
                "packet_id": item["packet_id"],
                "packet_hash": item["packet_hash"],
                "file": f"packets/{filename}",
            }
        )
    manifest = {
        "schema_version": "phase9-blind-adjudication-bundle/1.0.0",
        "adjudication_protocol": "phase9-adjudication-protocol/1.0.0",
        "packet_schema": "semantic-review-packet/1.1.0",
        "packet_schema_hash": _hash(schema),
        "packet_count": len(rows),
        "packets": rows,
        "source_hashes": sorted(
            {
                value
                for item in packets
                for value in item["packet"].get("source_hashes", {}).values()
            }
        ),
        "contains_candidate_metadata": False,
        "contains_split_or_rung_metadata": False,
        "contains_cost_or_latency_metadata": False,
        "leakage_scan": {
            "packets_scanned": len(scans),
            "leaks": sum(len(scan["leaks"]) for scan in scans),
            "result": (
                "PASS"
                if all(scan["result"] == "PASS" for scan in scans)
                else "BLOCKED"
            ),
        },
    }
    manifest_hash = _write(root / "bundle_manifest.json", manifest)
    _write(
        root / "leakage_audit.json",
        {
            "schema_version": "phase9-blind-packet-leakage-audit/1.0.0",
            "scans": list(scans),
        },
    )
    return {**manifest, "manifest_hash": manifest_hash, "root": str(root)}


def recompute_accounting_from_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Re-derive the failure breakdown from a persisted, immutable ledger.

    Execution evidence is written once and never rewritten. When a derived
    summary needs correcting, the ledger stays authoritative and the corrected
    view is recomputed from it rather than edited in place.
    """

    attempts = list(ledger["attempts"])
    completed = [item for item in attempts if item["response_status"] == "COMPLETED"]
    failed = [item for item in attempts if item["response_status"] == "FAILED"]

    def of_kind(kind: str) -> list[dict[str, Any]]:
        return [
            item
            for item in failed
            if (item.get("technical_diagnostic") or {}).get("failure_kind") == kind
        ]

    provider_technical = of_kind("PROVIDER_TECHNICAL_FAILURE") + of_kind(
        "UNCLASSIFIED_TECHNICAL_FAILURE"
    )
    deterministic_failures = of_kind("DETERMINISTIC_VALIDATION_FAILURE")
    contract_failures = of_kind("CONTRACT_OR_SCHEMA_FAILURE")
    by_stage: dict[str, dict[str, int]] = {}
    for item in attempts:
        row = by_stage.setdefault(
            item["stage"], {"attempted": 0, "completed": 0, "not_completed": 0}
        )
        row["attempted"] += 1
        if item["response_status"] == "COMPLETED":
            row["completed"] += 1
        else:
            row["not_completed"] += 1
    return {
        "primary_logical_calls_attempted": len(
            {item["logical_call_id"] for item in attempts}
        ),
        "primary_logical_calls_completed": len(completed),
        "attempts_not_completed": len(failed),
        "provider_technical_failures": len(provider_technical),
        "deterministic_validation_failures": len(deterministic_failures),
        "contract_or_schema_failures": len(contract_failures),
        "technical_retry_attempts": sum(
            1 for item in attempts if item["is_technical_retry"]
        ),
        "technical_failure_rate": (
            round(len(provider_technical) / len(attempts), 6) if attempts else 0.0
        ),
        "deterministic_failure_codes": sorted(
            {
                (item.get("technical_diagnostic") or {}).get("failure_code")
                for item in deterministic_failures
            }
        ),
        "by_stage": dict(sorted(by_stage.items())),
        "semantic_status": "PENDING_ADJUDICATION",
    }
