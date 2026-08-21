"""``semantic-benchmark/1.3.5`` final convergence pre-execution repair.

The product pipeline is unchanged.  This module builds the successor benchmark
authority from the immutable 1.3.4 freeze and closes only the five accepted
pre-execution blockers: N3 exposure/run identity, a single N3 hash authority,
complete executable-prompt binding, production-shaped P06 submission requests,
and fail-closed rung-result collection.

No function in this module resolves credentials or constructs provider
transport unless its caller explicitly supplies a factory *after* the frozen
prompt guard has cleared.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from .canonical import canonical_hash
from .contracts import SCHEMA_VERSION, models as m
from .evidence_mapping import materialize_evidence_mapping_draft
from .model_gateway.openai_schema import provider_output_json_schema
from .model_gateway.registry import PROMPT_SPECS, PromptSpec
from .n3_provider_fixtures import n3_provider_fixture_authority_current
from .p06_n3_protocol import (
    N3_ADJUDICATION_COLLECTION_REQUIREMENTS,
    N3_ADJUDICATION_POPULATION_CONTRACT,
    N3_ADJUDICATION_RUN_INDEX_FIELD,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_PROTOCOL_VERSION,
    N3_RUNS_PER_EXPOSURE,
    N3_SAFETY_SMOKE,
    N3_SAFETY_VERDICTS,
)
from .phase9_protocol import (
    MAX_TECHNICAL_RETRIES,
    PASS_QA_SAMPLE_PERCENT,
    SEMANTIC_K,
    SEMANTIC_STAGES,
    STAGE_REASONING_LADDER,
)
from .semantic_benchmark import DEFAULT_CORPUS_ROOT, load_corpus_package
from .semantic_benchmark_fixtures import (
    P06_SUBMISSION_FIXTURE_BUILDER_V135_VERSION,
    build_p06_submission_fixture_v135,
    parse_submission_bundle,
)
from .semantic_benchmark_v12 import model_visible_definition_for
from .semantic_benchmark_v12_boundary import _assert_no_leakage
from .semantic_benchmark_v13 import REPOSITORY_ROOT, V13Build, build_v13
from .semantic_benchmark_v13_boundary import n3_axis_authority_current
from .semantic_benchmark_v13_protocol import (
    N3_ADJUDICATIONS_PER_EXPOSURE,
    _adjudicable_pairs,
)
from .semantic_benchmark_v134 import (
    U3_LIMITATIONS_V134,
    semantic_qualification_claim_v134,
)


SEMANTIC_BENCHMARK_V135_VERSION = "semantic-benchmark/1.3.5"
BENCHMARK_BOUNDARY_FORMAT_V135 = "semantic-benchmark-boundary/1.3.5"
PROTOCOL_VERSION_V135 = "phase9-qualification-protocol/1.3.5"
CANDIDATE_MATRIX_VERSION_V135 = "phase9-candidate-matrix/1.3.5"
CALL_BUDGET_VERSION_V135 = "phase9-call-budget/1.3.5"

V134_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_4"
V134_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_4"
DEFINITION_ROOT = "evaluation/semantic_benchmark/v1_3_5"
REPORT_ROOT = "reports/semantic_benchmark/v1_3_5"

ACTIVE_MODEL_STAGE_PROMPTS: Mapping[str, str] = {
    "P04": "P04_BLUEPRINT_BUILD_V1",
    "P06": "P06_EVIDENCE_MAP_V1",
    "P07": "P07_QUESTION_BUILD_V1",
    "P09": "P09_GUIDE_BUILD_V1",
}


class V135BuildError(ValueError):
    """Raised when the 1.3.5 pre-execution instrument is inconsistent."""


class FreezePublicationError(V135BuildError):
    """Raised before publication when active freeze bindings disagree."""


class QualificationPromptMismatch(V135BuildError):
    """Raised before transport when live prompt material differs from freeze."""


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialize(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _provider_schema_boundary(spec: PromptSpec) -> dict[str, str]:
    schema = provider_output_json_schema(spec)
    encoded = json.dumps(
        schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "format": "provider-output-schema-boundary/1.0.0",
        "wire_schema_version": SCHEMA_VERSION,
        "schema_name": spec.provider_output_schema_name,
        "schema_hash": _sha256_bytes(encoded),
    }


def executable_prompt_authority(
    specs: Mapping[str, PromptSpec] = PROMPT_SPECS,
) -> dict[str, Any]:
    """Hash the complete live PromptSpec for every active candidate stage."""

    stages: dict[str, dict[str, Any]] = {}
    for stage, prompt_id in ACTIVE_MODEL_STAGE_PROMPTS.items():
        try:
            spec = specs[prompt_id]
        except KeyError as exc:
            raise V135BuildError(f"active prompt is absent: {prompt_id}") from exc
        schema = _provider_schema_boundary(spec)
        material = {
            "stage": stage,
            "prompt_id": spec.prompt_id,
            "prompt_version": spec.prompt_version,
            "system_prompt_id": spec.system_prompt_id,
            "prompt_hash": spec.prompt_hash,
            "input_schema_name": spec.input_schema_name,
            "output_schema_name": spec.output_schema_name,
            "provider_output_schema": schema,
            "complete_prompt_hash_covers_system_and_developer_instructions": True,
        }
        stages[stage] = {
            **material,
            "stage_prompt_authority_hash": canonical_hash(material),
        }
    material = {
        "schema_version": "phase9-executable-prompt-authority/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "active_model_stages": list(ACTIVE_MODEL_STAGE_PROMPTS),
        "stages": stages,
        "live_registry_must_match_before_transport": True,
    }
    return {**material, "prompt_authority_hash": canonical_hash(material)}


def assert_live_prompt_authority(
    frozen: Mapping[str, Any],
    *,
    live_specs: Mapping[str, PromptSpec] = PROMPT_SPECS,
) -> dict[str, Any]:
    """Fail closed when any live executable prompt differs from the freeze."""

    expected_hash = frozen.get("prompt_authority_hash")
    frozen_material_hash = canonical_hash(
        {
            key: value
            for key, value in frozen.items()
            if key != "prompt_authority_hash"
        }
    )
    if expected_hash != frozen_material_hash:
        raise QualificationPromptMismatch(
            "QUALIFICATION_FROZEN_PROMPT_AUTHORITY_SELF_HASH_MISMATCH"
        )
    live = executable_prompt_authority(live_specs)
    if live != frozen:
        mismatched = [
            stage
            for stage in ACTIVE_MODEL_STAGE_PROMPTS
            if live["stages"].get(stage) != frozen.get("stages", {}).get(stage)
        ]
        raise QualificationPromptMismatch(
            "QUALIFICATION_EXECUTABLE_PROMPT_MISMATCH::" + ",".join(mismatched)
        )
    return live


def build_qualification_transport_after_prompt_guard(
    *,
    stage: str,
    prompt_id: str,
    frozen_prompt_authority: Mapping[str, Any],
    frozen_execution_contract: Mapping[str, Any],
    transport_factory: Callable[[], Any],
    live_specs: Mapping[str, PromptSpec] = PROMPT_SPECS,
) -> Any:
    """The authoritative v1.3.5 pre-call boundary.

    The factory is deliberately invoked only after both the execution contract
    and every live active PromptSpec reproduce the frozen prompt authority.
    Tests can therefore prove a mismatch leaves transport construction at zero.
    """

    if frozen_execution_contract.get("prompt_authority_hash") != frozen_prompt_authority.get(
        "prompt_authority_hash"
    ):
        raise QualificationPromptMismatch(
            "QUALIFICATION_EXECUTION_CONTRACT_PROMPT_BINDING_MISMATCH"
        )
    declared_contract_hash = frozen_execution_contract.get(
        "execution_contract_hash"
    )
    recomputed_contract_hash = canonical_hash(
        {
            key: value
            for key, value in frozen_execution_contract.items()
            if key != "execution_contract_hash"
        }
    )
    if declared_contract_hash != recomputed_contract_hash:
        raise QualificationPromptMismatch(
            "QUALIFICATION_EXECUTION_CONTRACT_SELF_HASH_MISMATCH"
        )
    assert_live_prompt_authority(frozen_prompt_authority, live_specs=live_specs)
    expected = frozen_prompt_authority.get("stages", {}).get(stage)
    if expected is None or expected.get("prompt_id") != prompt_id:
        raise QualificationPromptMismatch(
            f"QUALIFICATION_STAGE_PROMPT_MISMATCH::{stage}::{prompt_id}"
        )
    return transport_factory()


@dataclass(frozen=True)
class V135Build:
    """Base semantic authority plus production-shaped P06 provider requests."""

    base: V13Build
    p06_request_groups: tuple[dict[str, Any], ...]
    p06_provider_cases: tuple[dict[str, Any], ...]
    p06_observation_bindings: tuple[dict[str, Any], ...]
    p06_runtime_requests: Mapping[
        str, tuple[m.EvidenceMapRequest, m.EvidenceMappingAliasEnvelope]
    ]

    @property
    def package_hash(self) -> str:
        return self.base.package_hash

    @property
    def corpus_root(self) -> Path:
        return self.base.corpus_root

    @property
    def derivation(self):
        return self.base.derivation

    @property
    def carried_cases(self) -> tuple[dict[str, Any], ...]:
        return self.base.carried_cases

    @property
    def cases(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            sorted(
                self.p06_provider_cases + self.base.carried_cases,
                key=lambda item: item["case_id"],
            )
        )


def _submission_group_id(routes: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    first = routes[0]
    match = re.fullmatch(r"P06-A(\d+)-S(\d+)-R\d+", first["route_fixture_id"])
    if match is None:
        raise V135BuildError(
            f"unexpected P06 route identity {first['route_fixture_id']!r}"
        )
    activity_number, submission_number = match.groups()
    return (
        f"P06-A{activity_number}-S{submission_number}-G01",
        f"PP-A{activity_number}-S{submission_number}-P06-G01",
    )


def _provider_split(routes: Sequence[Mapping[str, Any]]) -> str:
    splits = {str(route["split"]) for route in routes}
    if N3_HELD_OUT_CONFIRMATION in splits and len(splits) > 1:
        raise V135BuildError("a submission group crosses the held-out partition")
    if "HELD_OUT_CONFIRMATION" in splits and len(splits) > 1:
        raise V135BuildError("a submission group crosses the held-out partition")
    if "SMOKE" in splits:
        return "SMOKE"
    if len(splits) != 1:
        raise V135BuildError(f"unsupported P06 group split combination: {splits}")
    return next(iter(splits))


def build_v135(corpus_root: Path = DEFAULT_CORPUS_ROOT) -> V135Build:
    """Group all executable P06 routes for each submission into one request."""

    base = build_v13(corpus_root)
    package = load_corpus_package(corpus_root)
    catalog = {
        item["construct_key"]: item for item in base.derivation.catalog["constructs"]
    }
    bindings_by_fixture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for binding in base.derivation.bindings:
        bindings_by_fixture[binding["fixture_id"]].append(binding)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for route in base.derivation.routes:
        grouped[(route["activity_id"], route["submission_id"])].append(route)

    request_groups: list[dict[str, Any]] = []
    provider_cases: list[dict[str, Any]] = []
    observation_bindings: list[dict[str, Any]] = []
    runtime_requests: dict[
        str, tuple[m.EvidenceMapRequest, m.EvidenceMappingAliasEnvelope]
    ] = {}
    observed_routes: set[str] = set()
    for (activity_id, submission_id), routes in sorted(grouped.items()):
        routes = sorted(routes, key=lambda item: item["route_fixture_id"])
        group_fixture_id, provider_case_id = _submission_group_id(routes)
        activity = package.activity_by_id[activity_id]
        artifact_sets = {
            tuple(route["evidence_provenance"]["artifacts"]) for route in routes
        }
        if len(artifact_sets) != 1:
            raise V135BuildError("routes in one submission disagree on evidence scope")
        bundle = parse_submission_bundle(
            corpus_root=package.root,
            activity_path=activity["activity_path"],
            activity_id=activity_id,
            submission_id=submission_id,
            artifact_refs=list(next(iter(artifact_sets))),
        )
        route_inputs = [
            {
                "route_fixture_id": route["route_fixture_id"],
                "model_visible_definition": model_visible_definition_for(
                    catalog[route["target_construct_key"]], bundle
                ),
            }
            for route in routes
        ]
        request, envelope, aliases = build_p06_submission_fixture_v135(
            submission_fixture_id=group_fixture_id,
            routes=route_inputs,
            bundle=bundle,
        )
        alias_by_route = {item["route_fixture_id"]: item for item in aliases}
        property_ids = sorted(
            binding["property_id"]
            for route in routes
            for binding in bindings_by_fixture[route["route_fixture_id"]]
        )
        model_visible_material = {
            "request": request.model_dump(mode="json"),
            "model_visible_envelope": envelope.model_dump(mode="json"),
            "route_definitions": route_inputs,
        }
        _assert_no_leakage(
            material=model_visible_material,
            property_ids=property_ids,
            descriptions=[
                base.derivation.property_descriptions[property_id]
                for property_id in property_ids
            ],
        )
        input_hash = canonical_hash(model_visible_material)
        provider_split = _provider_split(routes)
        full_evidence_ids = set(bundle.allowed_evidence_ids)
        envelope_evidence_count = len(envelope.evidence_units)
        if envelope_evidence_count != len(full_evidence_ids):
            raise V135BuildError("P06 grouped request lost submission evidence scope")
        row = {
            "provider_case_id": provider_case_id,
            "submission_fixture_id": group_fixture_id,
            "activity_id": activity_id,
            "submission_id": submission_id,
            "split": provider_split,
            "fixture_builder_version": P06_SUBMISSION_FIXTURE_BUILDER_V135_VERSION,
            "route_fixture_ids": [route["route_fixture_id"] for route in routes],
            "route_count": len(routes),
            "dimension_count": len(envelope.dimensions),
            "variant_count": len(envelope.variants),
            "template_count": len(envelope.templates),
            "evidence_unit_count": envelope_evidence_count,
            "full_submission_evidence_scope_preserved": True,
            "request_hash": canonical_hash(request.model_dump(mode="json")),
            "envelope_hash": canonical_hash(envelope.model_dump(mode="json")),
            "input_hash": input_hash,
            "model_visible_oracle_fields_present": False,
        }
        request_groups.append(row)
        runtime_requests[provider_case_id] = (request, envelope)
        provider_cases.append(
            {
                "case_id": provider_case_id,
                "stage": "P06",
                "activity_id": activity_id,
                "submission_id": submission_id,
                "split": provider_split,
                "fixture_ref": f"benchmark-fixture://p06-submission/{group_fixture_id}",
                "fixture_id": group_fixture_id,
                "fixture_builder_version": P06_SUBMISSION_FIXTURE_BUILDER_V135_VERSION,
                "input_hash": input_hash,
                "property_ids": property_ids,
                "evaluator_mode": "EXTERNAL_ADJUDICATION_REQUIRED",
                "route_count": len(routes),
            }
        )
        for route in routes:
            route_id = route["route_fixture_id"]
            observed_routes.add(route_id)
            alias = alias_by_route[route_id]
            for binding in bindings_by_fixture[route_id]:
                observation_bindings.append(
                    {
                        **binding,
                        "original_route_case_id": binding["primary_case_id"],
                        "provider_case_id": provider_case_id,
                        "provider_split": provider_split,
                        "original_route_split": route["split"],
                        "expected_dimension_alias": alias["dimension_alias"],
                        "expected_variant_alias": alias["variant_alias"],
                        "expected_template_alias": alias["template_alias"],
                        "expected_variant_id": alias["variant_id"],
                        "expected_opportunity_template_id": alias[
                            "opportunity_template_id"
                        ],
                        "candidate_sees_property_or_oracle": False,
                    }
                )

    expected_routes = {route["route_fixture_id"] for route in base.derivation.routes}
    if observed_routes != expected_routes:
        raise V135BuildError("P06 submission grouping did not cover every route exactly once")
    if len(observation_bindings) != len(base.derivation.bindings):
        raise V135BuildError("P06 property observation denominator changed during grouping")
    return V135Build(
        base=base,
        p06_request_groups=tuple(
            sorted(request_groups, key=lambda item: item["provider_case_id"])
        ),
        p06_provider_cases=tuple(
            sorted(provider_cases, key=lambda item: item["case_id"])
        ),
        p06_observation_bindings=tuple(
            sorted(observation_bindings, key=lambda item: item["property_id"])
        ),
        p06_runtime_requests=runtime_requests,
    )


def score_p06_property_observation(
    *,
    draft: m.EvidenceMappingModelDraft,
    request: m.EvidenceMapRequest,
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one property observation to its route after real materialization."""

    materialized = materialize_evidence_mapping_draft(draft=draft, request=request)
    expected_template_id = binding["expected_opportunity_template_id"]
    matched = [
        item
        for item in materialized.opportunities
        if item.opportunity_template_id == expected_template_id
    ]
    if len(matched) > 1:
        raise V135BuildError("materializer produced duplicate property route output")
    omitted = not matched
    result_state = (
        "MODEL_FAILURE"
        if omitted and binding.get("candidate_scoring_allowed") is True
        else "PENDING_ADJUDICATION"
    )
    return {
        "property_id": binding["property_id"],
        "provider_case_id": binding["provider_case_id"],
        "expected_template_alias": binding["expected_template_alias"],
        "expected_opportunity_template_id": expected_template_id,
        "route_omitted": omitted,
        "candidate_observation": (
            "EXPECTED_CONSTRUCT_ROUTE_OMITTED" if omitted else "ROUTE_PRESENT"
        ),
        "result_state": result_state,
        "expected_support_status_exposed_to_candidate": False,
    }


def p06_submission_requests_document(build: V135Build) -> dict[str, Any]:
    distribution = Counter(item["route_count"] for item in build.p06_request_groups)
    single = sum(item["route_count"] == 1 for item in build.p06_request_groups)
    multi = sum(item["route_count"] > 1 for item in build.p06_request_groups)
    material = {
        "schema_version": "semantic-p06-submission-requests/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "qualification_unit": "PROPERTY_CANDIDATE_REASONING",
        "provider_call_unit": "SUBMISSION_RUN",
        "fixture_builder_version": P06_SUBMISSION_FIXTURE_BUILDER_V135_VERSION,
        "requests": list(build.p06_request_groups),
        "submission_group_count": len(build.p06_request_groups),
        "single_route_group_count": single,
        "multi_route_group_count": multi,
        "route_count": sum(item["route_count"] for item in build.p06_request_groups),
        "route_count_distribution": {
            str(key): value for key, value in sorted(distribution.items())
        },
        "all_multi_route_groups_have_d_v_t_greater_than_one": all(
            min(
                item["dimension_count"],
                item["variant_count"],
                item["template_count"],
            )
            > 1
            for item in build.p06_request_groups
            if item["route_count"] > 1
        ),
        "all_requests_preserve_complete_submission_evidence_scope": all(
            item["full_submission_evidence_scope_preserved"]
            for item in build.p06_request_groups
        ),
        "candidate_visible_oracle_fields": False,
    }
    return {**material, "request_set_hash": canonical_hash(material)}


def p06_property_observation_bindings_document(build: V135Build) -> dict[str, Any]:
    scoring = [
        row
        for row in build.p06_observation_bindings
        if row["candidate_scoring_allowed"]
    ]
    material = {
        "schema_version": "semantic-p06-property-observation-bindings/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "visibility": "EVALUATOR_ONLY_NEVER_MODEL_VISIBLE",
        "bindings": list(build.p06_observation_bindings),
        "binding_count": len(build.p06_observation_bindings),
        "candidate_scoring_property_count": len(scoring),
        "candidate_scoring_property_ids": sorted(
            row["property_id"] for row in scoring
        ),
        "omitted_expected_route_can_be_scored_as_model_failure": True,
        "expected_support_status_exposed_to_candidate": False,
        "oracle_outcome_exposed_to_candidate": False,
    }
    return {**material, "observation_bindings_hash": canonical_hash(material)}


def n3_axis_v135(build: V135Build) -> dict[str, Any]:
    """Rebind the executable run-aware N3 authority as one current object."""

    derived = n3_axis_authority_current(build.base)
    previous = _json(
        V134_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    )
    material = {key: value for key, value in derived.items() if key != "n3_axis_hash"}
    material.update(
        {
            "schema_version": "semantic-benchmark-n3-axis/1.3.5",
            "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
            "supersedes_n3_axis_hash": previous["n3_axis_hash"],
            "repair_scope": "EXPOSURE_PSEUDONYM_AND_FROZEN_RUN_INDEX_IDENTITY",
            "adjudication_identity": {
                "fields": ["exposure_pseudonym", N3_ADJUDICATION_RUN_INDEX_FIELD],
                "run_index_minimum": 1,
                "run_index_maximum": N3_RUNS_PER_EXPOSURE,
                "run_cardinality_authority": "phase9_protocol.SEMANTIC_K",
                "caller_may_define_k": False,
            },
            "adjudication_population_validation": {
                "contract": N3_ADJUDICATION_POPULATION_CONTRACT,
                "requirements": list(N3_ADJUDICATION_COLLECTION_REQUIREMENTS),
                "closed_verdict_vocabulary": list(N3_SAFETY_VERDICTS),
                "validation_precedes_clearance_promotion_or_qualification": True,
                "aggregation_is_conservative_over_all_expected_runs": True,
                "confirmed_failure_dominates": True,
                "indeterminate_dominates_clear_only_when_no_confirmed_failure": True,
                "all_expected_runs_clear_required_for_clearance": True,
            },
        }
    )
    required = material["census"]["required_adjudication_rows_by_stage"]
    expected = {
        N3_SAFETY_SMOKE: material["census"][N3_SAFETY_SMOKE]
        * N3_RUNS_PER_EXPOSURE,
        N3_CORE: material["census"][N3_CORE] * N3_RUNS_PER_EXPOSURE,
        N3_HELD_OUT_CONFIRMATION: material["census"][N3_HELD_OUT_CONFIRMATION]
        * N3_RUNS_PER_EXPOSURE,
    }
    if required != expected:
        raise V135BuildError(
            f"N3 stage run cardinality was not derived from frozen k: {required}"
        )
    return {**material, "n3_axis_hash": canonical_hash(material)}


def semantic_qualification_claim_v135(build: V135Build) -> dict[str, Any]:
    previous = semantic_qualification_claim_v134(build.base)
    material = {key: value for key, value in previous.items() if key != "claim_hash"}
    history = [*material.get("historical_claim_lineage", [])]
    history.append(
        {
            "benchmark_version": "semantic-benchmark/1.3.4",
            "status": "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED",
            "claim_named_version": "semantic-benchmark/1.3.4",
            "correct_when_published": True,
            "superseded_because": "five independent pre-execution convergence blockers",
        }
    )
    limitations = [
        sentence.replace("semantic-benchmark/1.3.4", SEMANTIC_BENCHMARK_V135_VERSION)
        for sentence in U3_LIMITATIONS_V134
    ]
    material.update(
        {
            "schema_version": "p06-semantic-qualification-claim/1.3.5",
            "applicable_benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
            "supersedes_claim_binding_from": "semantic-benchmark/1.3.4",
            "claim_semantics_changed_from_v134": False,
            "claim": (
                f"{SEMANTIC_BENCHMARK_V135_VERSION} qualifies P06 candidate "
                "behaviour on the support statuses SUFFICIENT, PARTIAL and "
                "INSUFFICIENT."
            ),
            "limitations": limitations,
            "limitation_count": len(limitations),
            "historical_claim_lineage": history,
            "what_changed": (
                "The semantic property denominator and U3 status scope are "
                "unchanged; P06 provider requests are regrouped by submission."
            ),
        }
    )
    return {**material, "claim_hash": canonical_hash(material)}


def call_budget_v135(
    build: V135Build,
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive provider and adjudicator calls from grouped requests and k=3."""

    if N3_ADJUDICATIONS_PER_EXPOSURE != SEMANTIC_K != N3_RUNS_PER_EXPOSURE:
        raise V135BuildError("N3 and semantic run-cardinality authorities diverged")
    case_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for case in build.cases:
        case_counts[case["stage"]][case["split"]] += 1

    pairs = _adjudicable_pairs(build.base)
    p06_pairs = Counter(
        row["provider_split"] for row in build.p06_observation_bindings
    )
    pairs["P06"] = dict(sorted(p06_pairs.items()))

    provider_rows: list[dict[str, Any]] = []
    for stage in SEMANTIC_STAGES:
        unit = "SUBMISSION_RUN" if stage == "P06" else "CASE_RUN"
        for split, count in sorted(case_counts[stage].items()):
            for rung in STAGE_REASONING_LADDER[stage]:
                provider_rows.append(
                    {
                        "axis": "SEMANTIC",
                        "stage": stage,
                        "split": split,
                        "reasoning_rung": rung,
                        "side": (
                            "HELD_OUT_CONFIRMATION"
                            if split == "HELD_OUT_CONFIRMATION"
                            else "QUALIFICATION"
                        ),
                        "unit": unit,
                        "cases": count,
                        "k": SEMANTIC_K,
                        "calls_if_this_rung_executes": count * SEMANTIC_K,
                    }
                )

    n3_by_stage = {
        stage: n3_axis["census"][stage]
        for stage in (N3_SAFETY_SMOKE, N3_CORE, N3_HELD_OUT_CONFIRMATION)
    }
    if n3_fixtures["fixture_count"] != n3_axis["census"]["total"]:
        raise V135BuildError("N3 provider fixtures do not cover the frozen census")
    if n3_fixtures["required_provider_calls_by_n3_split"] != n3_axis["census"][
        "required_adjudication_rows_by_stage"
    ]:
        raise V135BuildError(
            "N3 provider fixture run counts disagree with the N3 axis"
        )
    for stage_name, count in n3_by_stage.items():
        for rung in STAGE_REASONING_LADDER["P06"]:
            provider_rows.append(
                {
                    "axis": "CONTRACTUAL_HARD_SAFETY",
                    "stage": "P06",
                    "split": stage_name,
                    "reasoning_rung": rung,
                    "side": (
                        "HELD_OUT_CONFIRMATION"
                        if stage_name == N3_HELD_OUT_CONFIRMATION
                        else "QUALIFICATION"
                    ),
                    "unit": "EXPOSURE_RUN",
                    "cases": count,
                    "k": SEMANTIC_K,
                    "calls_if_this_rung_executes": count * SEMANTIC_K,
                }
            )

    semantic_adjudication_rows: list[dict[str, Any]] = []
    for stage in SEMANTIC_STAGES:
        for split, count in sorted(pairs.get(stage, {}).items()):
            for rung in STAGE_REASONING_LADDER[stage]:
                first_pass = count * SEMANTIC_K
                semantic_adjudication_rows.append(
                    {
                        "axis": "SEMANTIC",
                        "stage": stage,
                        "split": split,
                        "reasoning_rung": rung,
                        "side": (
                            "HELD_OUT_CONFIRMATION"
                            if split == "HELD_OUT_CONFIRMATION"
                            else "QUALIFICATION"
                        ),
                        "unit": "CASE_PROPERTY_RUN",
                        "observation_units": count,
                        "k": SEMANTIC_K,
                        "first_pass_calls": first_pass,
                        "max_conditional_second_pass_calls": first_pass,
                        "pass_qa_second_pass_floor": -(
                            -first_pass * PASS_QA_SAMPLE_PERCENT // 100
                        ),
                    }
                )

    n3_adjudication_rows: list[dict[str, Any]] = []
    for stage_name, count in n3_by_stage.items():
        for rung in STAGE_REASONING_LADDER["P06"]:
            first_pass = count * N3_ADJUDICATIONS_PER_EXPOSURE
            n3_adjudication_rows.append(
                {
                    "axis": "CONTRACTUAL_HARD_SAFETY",
                    "stage": "P06",
                    "split": stage_name,
                    "reasoning_rung": rung,
                    "side": (
                        "HELD_OUT_CONFIRMATION"
                        if stage_name == N3_HELD_OUT_CONFIRMATION
                        else "QUALIFICATION"
                    ),
                    "unit": "EXPOSURE_RUN",
                    "observation_units": count,
                    "adjudications_per_exposure": N3_ADJUDICATIONS_PER_EXPOSURE,
                    "first_pass_calls": first_pass,
                    "max_conditional_second_pass_calls": first_pass,
                }
            )

    def total(rows: Sequence[Mapping[str, Any]], key: str, **filters: Any) -> int:
        return sum(
            int(row[key])
            for row in rows
            if all(row.get(name) == value for name, value in filters.items())
        )

    provider_budget = {
        "rows": provider_rows,
        "aggregation_rule": (
            "Qualification-side worst case walks every rung; held-out executes "
            "once for the selected configuration."
        ),
        "semantic_qualification_side_worst_case_all_rungs": total(
            provider_rows, "calls_if_this_rung_executes", axis="SEMANTIC", side="QUALIFICATION"
        ),
        "semantic_qualification_side_lowest_rung_only": total(
            provider_rows,
            "calls_if_this_rung_executes",
            axis="SEMANTIC",
            side="QUALIFICATION",
            reasoning_rung="HIGH",
        ),
        "semantic_held_out_for_one_selected_configuration": total(
            provider_rows,
            "calls_if_this_rung_executes",
            axis="SEMANTIC",
            side="HELD_OUT_CONFIRMATION",
            reasoning_rung="HIGH",
        ),
        "n3_qualification_side_worst_case_all_rungs": total(
            provider_rows,
            "calls_if_this_rung_executes",
            axis="CONTRACTUAL_HARD_SAFETY",
            side="QUALIFICATION",
        ),
        "n3_qualification_side_lowest_rung_only": total(
            provider_rows,
            "calls_if_this_rung_executes",
            axis="CONTRACTUAL_HARD_SAFETY",
            side="QUALIFICATION",
            reasoning_rung="HIGH",
        ),
        "n3_held_out_for_one_selected_configuration": total(
            provider_rows,
            "calls_if_this_rung_executes",
            axis="CONTRACTUAL_HARD_SAFETY",
            side="HELD_OUT_CONFIRMATION",
            reasoning_rung="HIGH",
        ),
    }
    semantic_budget = {
        "rows": semantic_adjudication_rows,
        "first_pass_qualification_side_worst_case_all_rungs": total(
            semantic_adjudication_rows, "first_pass_calls", side="QUALIFICATION"
        ),
        "first_pass_qualification_side_lowest_rung_only": total(
            semantic_adjudication_rows,
            "first_pass_calls",
            side="QUALIFICATION",
            reasoning_rung="HIGH",
        ),
        "first_pass_held_out_for_one_selected_configuration": total(
            semantic_adjudication_rows,
            "first_pass_calls",
            side="HELD_OUT_CONFIRMATION",
            reasoning_rung="HIGH",
        ),
        "max_conditional_second_pass_qualification_side_worst_case_all_rungs": total(
            semantic_adjudication_rows,
            "max_conditional_second_pass_calls",
            side="QUALIFICATION",
        ),
        "max_conditional_second_pass_held_out_for_one_selected_configuration": total(
            semantic_adjudication_rows,
            "max_conditional_second_pass_calls",
            side="HELD_OUT_CONFIRMATION",
            reasoning_rung="HIGH",
        ),
        "second_pass_trigger": "FIRST_PASS_IS_MODEL_FAILURE_OR_PASS_QA_SAMPLE",
    }
    n3_budget = {
        "rows": n3_adjudication_rows,
        "exposure_census": dict(n3_axis["census"]),
        "required_consolidated_rows_by_stage": dict(
            n3_axis["census"]["required_adjudication_rows_by_stage"]
        ),
        "first_pass_qualification_side_worst_case_all_rungs": total(
            n3_adjudication_rows, "first_pass_calls", side="QUALIFICATION"
        ),
        "first_pass_qualification_side_lowest_rung_only": total(
            n3_adjudication_rows,
            "first_pass_calls",
            side="QUALIFICATION",
            reasoning_rung="HIGH",
        ),
        "first_pass_held_out_for_one_selected_configuration": total(
            n3_adjudication_rows,
            "first_pass_calls",
            side="HELD_OUT_CONFIRMATION",
            reasoning_rung="HIGH",
        ),
        "max_conditional_second_pass_qualification_side_worst_case_all_rungs": total(
            n3_adjudication_rows,
            "max_conditional_second_pass_calls",
            side="QUALIFICATION",
        ),
        "max_conditional_second_pass_held_out_for_one_selected_configuration": total(
            n3_adjudication_rows,
            "max_conditional_second_pass_calls",
            side="HELD_OUT_CONFIRMATION",
            reasoning_rung="HIGH",
        ),
        "second_pass_trigger": "FIRST_PASS_DISPOSITION_IS_CONFIRMED",
    }
    material = {
        "schema_version": CALL_BUDGET_VERSION_V135,
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "estimate_status": "DERIVED_COUNT_NOT_A_BILL",
        "authorization": "NONE",
        "calls_performed_by_this_task": 0,
        "pricing_refreshed": False,
        "provider_and_adjudicator_budgets_are_never_summed": True,
        "k": SEMANTIC_K,
        "n3_runs_per_exposure": N3_RUNS_PER_EXPOSURE,
        "n3_run_cardinality_authority": "phase9_protocol.SEMANTIC_K",
        "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
        "max_technical_retries": MAX_TECHNICAL_RETRIES,
        "pass_qa_sample_percent": PASS_QA_SAMPLE_PERCENT,
        "p06_provider_call_unit": "SUBMISSION_RUN",
        "p06_submission_group_count": len(build.p06_request_groups),
        "p06_executable_route_count": len(build.base.derivation.routes),
        "p06_property_observation_count": len(build.p06_observation_bindings),
        "p06_candidate_scoring_property_count": len(
            build.base.derivation.scoring_property_ids
        ),
        "provider_call_budget": provider_budget,
        "semantic_adjudicator_budget": semantic_budget,
        "n3_adjudicator_budget": n3_budget,
        "case_counts_by_stage_split": {
            stage: dict(sorted(counts.items()))
            for stage, counts in sorted(case_counts.items())
        },
        "adjudicable_observation_units_by_stage_split": pairs,
    }
    return {**material, "call_budget_hash": canonical_hash(material)}


def rung_collection_authority() -> dict[str, Any]:
    source = REPOSITORY_ROOT / (
        "src/comprehension_verification/semantic_benchmark_v13_protocol.py"
    )
    material = {
        "schema_version": "phase9-rung-result-collection/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "frozen_ladders": {
            stage: list(STAGE_REASONING_LADDER[stage])
            for stage in ACTIVE_MODEL_STAGE_PROMPTS
        },
        "requirements": [
            "EVERY_SUPPLIED_RUNG_IS_KNOWN",
            "RUNG_IDENTITIES_ARE_UNIQUE",
            "EXECUTED_RUNGS_FORM_A_CONTIGUOUS_FROZEN_LADDER_PREFIX",
            "A_DEEPER_RUNG_REQUIRES_THE_PRECEDING_RUNG",
            "A_DEEPER_RUNG_REQUIRES_PRECEDING_REJECTION",
            "HELD_OUT_MATERIAL_IS_FORBIDDEN",
            "VALIDATION_COMPLETES_BEFORE_SELECTION",
        ],
        "row_order_affects_selection": False,
        "held_out_may_enter_validation_or_selection": False,
        "selector": "select_lowest_qualifying_rung",
        "selector_source_hash": _sha256_file(source),
        "malformed_collection_consequence": "RAISE_RUNG_SELECTION_ERROR",
    }
    return {**material, "rung_collection_hash": canonical_hash(material)}


def stage_boundaries_v135(
    *,
    prompt_authority: Mapping[str, Any],
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
    requests: Mapping[str, Any],
    observations: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    claim: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(V134_REPORT_ROOT / "stage_boundaries.json")
    stages: dict[str, dict[str, Any]] = {}
    for stage in ACTIVE_MODEL_STAGE_PROMPTS:
        old = previous["stages"][stage]
        material = {
            key: value
            for key, value in old.items()
            if key != "stage_boundary_hash"
            and not key.startswith(
                (
                    "v134_",
                    "v133_",
                    "carried_forward_",
                    "carry_forward_",
                    "supersedes_",
                )
            )
        }
        prompt_row = prompt_authority["stages"][stage]
        material.update(
            {
                "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
                "boundary_status": "NEW_IN_V135",
                "new_because": (
                    "The stage now binds its complete executable PromptSpec and "
                    "provider output schema."
                ),
                "executable_prompt_authority": dict(prompt_row),
                "executable_prompt_authority_hash": prompt_row[
                    "stage_prompt_authority_hash"
                ],
                "prompt_authority_set_hash": prompt_authority[
                    "prompt_authority_hash"
                ],
                "supersedes_v134_stage_boundary": old["stage_boundary_hash"],
            }
        )
        if stage == "P06":
            material.update(
                {
                    "new_because": (
                        "P06 binds complete executable prompt material, the "
                        "production-shaped submission request population and the "
                        "run-aware N3 authority."
                    ),
                    "p06_submission_request_set_hash": requests["request_set_hash"],
                    "p06_property_observation_bindings_hash": observations[
                        "observation_bindings_hash"
                    ],
                    "p06_provider_call_unit": "SUBMISSION_RUN",
                    "p06_submission_group_count": requests[
                        "submission_group_count"
                    ],
                    "p06_executable_route_count": requests["route_count"],
                    "p06_candidate_scoring_property_count": observations[
                        "candidate_scoring_property_count"
                    ],
                    "p06_fixture_builder_version": requests[
                        "fixture_builder_version"
                    ],
                    "n3_axis_hash": n3_axis["n3_axis_hash"],
                    "n3_provider_fixture_set_hash": n3_fixtures[
                        "fixture_set_hash"
                    ],
                    "n3_protocol_version": n3_axis["protocol_version"],
                    "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
                    "n3_run_identity": dict(n3_axis["adjudication_identity"]),
                    "n3_required_rows_by_stage": dict(
                        n3_axis["census"]["required_adjudication_rows_by_stage"]
                    ),
                    "call_budget_hash": call_budget["call_budget_hash"],
                    "semantic_qualification_claim_hash": claim["claim_hash"],
                    "semantic_qualification_claim": claim["claim"],
                    "semantic_qualification_limitations": list(
                        claim["limitations"]
                    ),
                    "semantic_qualification_applicable_benchmark_version": claim[
                        "applicable_benchmark_version"
                    ],
                }
            )
        stages[stage] = {
            **material,
            "stage_boundary_hash": canonical_hash(material),
        }

    planner = dict(previous["stages"]["PLANNER"])
    planner.update(
        {
            "boundary_status": "CARRIED_FORWARD_FROM_V134",
            "carried_forward_from_benchmark_version": "semantic-benchmark/1.3.4",
            "carry_forward_is_valid_because": (
                "The deterministic planner is outside all five convergence "
                "blocker classes."
            ),
        }
    )
    stages["PLANNER"] = planner
    hashes = {stage: row["stage_boundary_hash"] for stage, row in stages.items()}
    material = {
        "schema_version": "semantic-benchmark-stage-boundaries/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "previous_version": "semantic-benchmark/1.3.4",
        "previous_version_status": (
            "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
        ),
        "stages": stages,
        "stage_boundary_hashes": hashes,
        "boundary_status_by_stage": {
            stage: row["boundary_status"] for stage, row in stages.items()
        },
        "new_boundary_stages": list(ACTIVE_MODEL_STAGE_PROMPTS),
        "carried_forward_stages": ["PLANNER"],
        "v134_stage_boundary_hashes": dict(previous["stage_boundary_hashes"]),
    }
    return {**material, "stage_boundaries_hash": canonical_hash(material)}


def candidate_execution_contract_v135(
    *,
    prompt_authority: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    requests: Mapping[str, Any],
    observations: Mapping[str, Any],
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    rung_collection: Mapping[str, Any],
) -> dict[str, Any]:
    previous_matrix = _json(
        V134_DEFINITION_ROOT / "phase9/candidate_matrix.json"
    )
    material = {
        "schema_version": "phase9-candidate-execution-contract/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "candidate_identities": list(previous_matrix["candidates"]),
        "candidate_identity_hash": canonical_hash(previous_matrix["candidates"]),
        "stage_boundary_hashes": dict(stage_boundaries["stage_boundary_hashes"]),
        "prompt_authority_hash": prompt_authority["prompt_authority_hash"],
        "prompt_authority_by_stage": {
            stage: row["stage_prompt_authority_hash"]
            for stage, row in prompt_authority["stages"].items()
        },
        "p06_submission_request_set_hash": requests["request_set_hash"],
        "p06_property_observation_bindings_hash": observations[
            "observation_bindings_hash"
        ],
        "call_budget_hash": call_budget["call_budget_hash"],
        "semantic_k": SEMANTIC_K,
        "n3_axis_hash": n3_axis["n3_axis_hash"],
        "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
        "n3_runs_per_exposure": N3_RUNS_PER_EXPOSURE,
        "n3_run_identity_fields": list(n3_axis["adjudication_identity"]["fields"]),
        "rung_collection_hash": rung_collection["rung_collection_hash"],
        "qualification_execution_entrypoint": (
            "comprehension_verification.phase9_execution._execute_logical_call"
        ),
        "transport_construction_boundary": (
            "comprehension_verification.phase9_execution."
            "_build_v135_prompt_guarded_transport"
        ),
        "pre_call_guard": (
            "build_qualification_transport_after_prompt_guard"
        ),
        "expected_prompt_authority_constant": (
            "phase9_execution.EXPECTED_V135_PROMPT_AUTHORITY_HASH"
        ),
        "pre_call_guard_runs_before_transport_factory": True,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "real_provider_transport": False,
        "authorization": "NONE",
    }
    return {**material, "execution_contract_hash": canonical_hash(material)}


def benchmark_boundary_v135(
    *,
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    prompt_authority: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    requests: Mapping[str, Any],
    observations: Mapping[str, Any],
    rung_collection: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(V134_REPORT_ROOT / "benchmark_boundary.json")
    material = {
        key: value for key, value in previous.items() if key != "benchmark_boundary_hash"
    }
    dependencies = list(material.get("documented_dependencies", []))
    for dependency in (
        "complete executable PromptSpec authority for P04/P06/P07/P09",
        "production-shaped P06 submission request population",
        "N3 exposure_pseudonym plus frozen run_index identity",
        "fail-closed contiguous rung-result collection",
    ):
        if dependency not in dependencies:
            dependencies.append(dependency)
    material.update(
        {
            "boundary_format": BENCHMARK_BOUNDARY_FORMAT_V135,
            "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
            "previous_version": "semantic-benchmark/1.3.4",
            "previous_version_status": (
                "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
            ),
            "stage_boundaries_hash": stage_boundaries["stage_boundaries_hash"],
            "stage_boundary_hashes": dict(stage_boundaries["stage_boundary_hashes"]),
            "boundary_status_by_stage": dict(
                stage_boundaries["boundary_status_by_stage"]
            ),
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
            "prompt_authority_hash": prompt_authority["prompt_authority_hash"],
            "candidate_execution_contract_hash": execution_contract[
                "execution_contract_hash"
            ],
            "p06_submission_request_set_hash": requests["request_set_hash"],
            "p06_property_observation_bindings_hash": observations[
                "observation_bindings_hash"
            ],
            "rung_collection_hash": rung_collection["rung_collection_hash"],
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "documented_dependencies": dependencies,
        }
    )
    return {**material, "benchmark_boundary_hash": canonical_hash(material)}


def candidate_matrix_v135(
    *,
    benchmark_boundary: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    prompt_authority: Mapping[str, Any],
    rung_collection: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(V134_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    material = {
        key: value for key, value in previous.items() if key != "candidate_matrix_hash"
    }
    material.update(
        {
            "schema_version": CANDIDATE_MATRIX_VERSION_V135,
            "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
            "protocol_version": PROTOCOL_VERSION_V135,
            "benchmark_boundary_hash": benchmark_boundary[
                "benchmark_boundary_hash"
            ],
            "candidate_execution_contract_hash": execution_contract[
                "execution_contract_hash"
            ],
            "prompt_authority_hash": prompt_authority["prompt_authority_hash"],
            "rung_collection_hash": rung_collection["rung_collection_hash"],
            "candidate_identities_changed_from_v134": False,
            "carried_candidate_identity_hash": canonical_hash(previous["candidates"]),
            "new_hash_reason": (
                "Candidate identities are unchanged; the matrix binds the 1.3.5 "
                "execution, prompt, rung and global authorities."
            ),
        }
    )
    material.pop("candidate_identities_changed_from_v133", None)
    return {**material, "candidate_matrix_hash": canonical_hash(material)}


def qualification_protocol_v135(
    *,
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    benchmark_boundary: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    prompt_authority: Mapping[str, Any],
    requests: Mapping[str, Any],
    observations: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    rung_collection: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(
        V134_DEFINITION_ROOT / "phase9/qualification_protocol.json"
    )
    material = {
        key: value for key, value in previous.items() if key != "protocol_boundary_hash"
    }
    axes = dict(material["axes"])
    contractual = dict(axes["CONTRACTUAL_HARD_SAFETY"])
    contractual.update(
        {
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
            "n3_protocol_version": n3_axis["protocol_version"],
            "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
            "adjudication_identity": dict(n3_axis["adjudication_identity"]),
            "required_adjudication_rows_by_stage": dict(
                n3_axis["census"]["required_adjudication_rows_by_stage"]
            ),
        }
    )
    axes["CONTRACTUAL_HARD_SAFETY"] = contractual

    expected_ids = {
        N3_SAFETY_SMOKE: list(
            n3_axis["selectors"]["safety_smoke"]["exposure_ids"]
        ),
        N3_CORE: list(n3_axis["selectors"]["core_exposure_ids"]),
        N3_HELD_OUT_CONFIRMATION: list(
            n3_axis["selectors"]["held_out_exposure_ids"]
        ),
    }
    expected_run_identities = {
        stage: [
            {"exposure_pseudonym": exposure_id, "run_index": run_index}
            for exposure_id in exposure_ids
            for run_index in range(1, N3_RUNS_PER_EXPOSURE + 1)
        ]
        for stage, exposure_ids in expected_ids.items()
    }
    gates = dict(material["n3_gates"])
    gates.update(
        {
            "adjudication_population_contract": N3_ADJUDICATION_POPULATION_CONTRACT,
            "adjudication_collection_requirements": list(
                N3_ADJUDICATION_COLLECTION_REQUIREMENTS
            ),
            "closed_verdict_vocabulary": list(N3_SAFETY_VERDICTS),
            "identity_fields": [
                "exposure_pseudonym",
                N3_ADJUDICATION_RUN_INDEX_FIELD,
            ],
            "run_cardinality_authority": "phase9_protocol.SEMANTIC_K",
            "runs_per_exposure": N3_RUNS_PER_EXPOSURE,
            "caller_may_define_k": False,
            "exactly_one_row_per_expected_stage_exposure_run": True,
            "validation_precedes_clearance_promotion_or_qualification": True,
            "malformed_collection_fails_closed": True,
        }
    )
    gates.pop("exactly_one_row_per_expected_stage_exposure", None)
    material.update(
        {
            "schema_version": PROTOCOL_VERSION_V135,
            "protocol_version": PROTOCOL_VERSION_V135,
            "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
            "previous_protocol_version": previous["protocol_version"],
            "reason_for_new_version": [
                "N3 adjudication identity includes frozen run_index 1..k",
                "all active N3 hash bindings derive from one current axis object",
                "P04/P06/P07/P09 bind complete executable PromptSpec material",
                "P06 candidate calls use complete submission route groups",
                "rung result collections validate sequencing before selection",
            ],
            "benchmark_boundary_hash": benchmark_boundary[
                "benchmark_boundary_hash"
            ],
            "candidate_matrix_hash": candidate_matrix["candidate_matrix_hash"],
            "candidate_execution_contract_hash": execution_contract[
                "execution_contract_hash"
            ],
            "prompt_authority_hash": prompt_authority["prompt_authority_hash"],
            "p06_submission_request_set_hash": requests["request_set_hash"],
            "p06_property_observation_bindings_hash": observations[
                "observation_bindings_hash"
            ],
            "call_budget_hash": call_budget["call_budget_hash"],
            "rung_collection_hash": rung_collection["rung_collection_hash"],
            "rung_result_collection_contract": dict(rung_collection),
            "axes": axes,
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "n3_protocol_version": n3_axis["protocol_version"],
            "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
            "n3_expected_exposure_ids_by_stage": expected_ids,
            "n3_expected_exposure_run_identities_by_stage": expected_run_identities,
            "n3_required_adjudication_rows_by_stage": dict(
                n3_axis["census"]["required_adjudication_rows_by_stage"]
            ),
            "n3_gates": gates,
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_claim_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed_from_v134": False,
            "next_real_execution": "NOT_AUTHORIZED_BY_THIS_FREEZE",
            "authorization": "NONE",
            "provider_calls": 0,
            "adjudicator_calls": 0,
        }
    )
    material.pop("semantic_qualification_semantics_changed_from_v133", None)
    return {**material, "protocol_boundary_hash": canonical_hash(material)}


def lineage_v135() -> dict[str, Any]:
    previous = _json(V134_REPORT_ROOT / "lineage.json")
    chain = [dict(row) for row in previous["chain"]]
    if chain[-1]["version"] != "semantic-benchmark/1.3.4":
        raise V135BuildError("v1.3.4 is not the immediate frozen predecessor")
    chain[-1].update(
        {
            "status": (
                "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
            ),
            "superseded_because": [
                "N3 k=3 adjudication rows lacked run identity",
                "active protocol bindings contained two N3 axis hashes",
                "active executable prompts were not completely freeze-bound",
                "P06 semantic fixtures isolated routes instead of grouping submissions",
                "rung result collection allowed duplicates and sparse prefixes",
            ],
            "bytes_modified_by_v135": False,
            "v134_repair_retained": (
                "unknown verdict, duplicate exposure identity, foreign exposure "
                "identity and missing exposure identity remain fail-closed"
            ),
        }
    )
    chain.append(
        {
            "version": SEMANTIC_BENCHMARK_V135_VERSION,
            "status": "PREEXECUTION_FREEZE_CANDIDATE",
            "provider_calls": 0,
            "adjudicator_calls": 0,
            "credential_resolutions": 0,
            "candidate_outcomes_read": False,
            "authorization": "NONE",
        }
    )
    material = {
        "schema_version": "semantic-benchmark-lineage/1.3.5",
        "from_version": "semantic-benchmark/1.3.4",
        "to_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "chain": chain,
        "v134_lineage_hash": previous["lineage_hash"],
        "v134_bytes_modified": False,
        "v134_preserved_as_historical_evidence": True,
        "v134_successfully_repaired_malformed_one_row_n3_population_validation": True,
        "no_provider_or_adjudicator_qualification_outcome_existed": True,
        "no_provider_or_adjudicator_outcome_informed_the_repair": True,
        "is_a_corpus_change": False,
        "is_a_product_pipeline_architecture_change": False,
        "repair_scope": [
            "N3 exposure/run collection identity",
            "single N3 axis authority",
            "active executable prompt freeze binding and pre-call guard",
            "P06 submission-group request representativeness",
            "rung-result collection sequencing",
        ],
    }
    return {**material, "lineage_hash": canonical_hash(material)}


def convergence_delta_v135(
    *,
    build: V135Build,
    requests: Mapping[str, Any],
    observations: Mapping[str, Any],
    prompt_authority: Mapping[str, Any],
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
) -> dict[str, Any]:
    previous_axis = _json(
        V134_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    )
    previous_n3_fixtures = _json(
        V134_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json"
    )
    if n3_fixtures["fixture_input_hashes"] != previous_n3_fixtures[
        "fixture_input_hashes"
    ]:
        raise V135BuildError("N3 provider-visible request bytes changed unexpectedly")
    material = {
        "schema_version": "semantic-benchmark-convergence-delta/1.3.5",
        "from_version": "semantic-benchmark/1.3.4",
        "to_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "v134_bytes_modified": False,
        "unchanged": {
            "corpus_package_hash": build.package_hash,
            "executable_p06_route_count": len(build.base.derivation.routes),
            "p06_candidate_scoring_property_count": len(
                build.base.derivation.scoring_property_ids
            ),
            "p06_property_observation_count": len(build.p06_observation_bindings),
            "candidate_identities": True,
            "semantic_bars": True,
            "u3_status_scope": True,
            "product_pipeline_architecture": True,
        },
        "changed": {
            "n3_axis_hash_transition": {
                "before": previous_axis["n3_axis_hash"],
                "after": n3_axis["n3_axis_hash"],
            },
            "n3_adjudication_identity": "EXPOSURE_PSEUDONYM_PLUS_RUN_INDEX",
            "n3_provider_fixture_set_hash_transition": {
                "before": previous_n3_fixtures["fixture_set_hash"],
                "after": n3_fixtures["fixture_set_hash"],
                "provider_request_hashes_changed": False,
                "change_reason": (
                    "fixture authority now binds exposure/run identities and "
                    "run-derived stage call counts"
                ),
            },
            "p06_provider_request_count": {
                "before_route_isolated": len(build.base.derivation.routes),
                "after_submission_grouped": requests["submission_group_count"],
            },
            "p06_request_set_hash": requests["request_set_hash"],
            "p06_observation_bindings_hash": observations[
                "observation_bindings_hash"
            ],
            "prompt_authority_hash": prompt_authority["prompt_authority_hash"],
            "active_stage_boundaries": list(ACTIVE_MODEL_STAGE_PROMPTS),
            "rung_collection_validation": True,
        },
        "no_claim_of_byte_carry_forward_for_changed_material": True,
    }
    return {**material, "delta_hash": canonical_hash(material)}


def pre_results_freeze_v135(
    *,
    build: V135Build,
    n3_axis: Mapping[str, Any],
    n3_fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    prompt_authority: Mapping[str, Any],
    requests: Mapping[str, Any],
    observations: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    rung_collection: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    benchmark_boundary: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    protocol: Mapping[str, Any],
    lineage: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> dict[str, Any]:
    material = {
        "schema_version": "phase9-pre-results-instrument-freeze/1.3.5",
        "phase": "PHASE_9_PRE_EXECUTION_CONVERGENCE_REPAIR",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "previous_version": "semantic-benchmark/1.3.4",
        "previous_version_status": (
            "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
        ),
        "status": "PREEXECUTION_FREEZE_CANDIDATE",
        "purpose": (
            "Freeze the five accepted convergence repairs before any first "
            "real qualification call."
        ),
        "corpus_package_boundary_hash": build.package_hash,
        "corpus_bytes_modified": False,
        "v134_preserved": True,
        "global_benchmark_boundary_hash": benchmark_boundary[
            "benchmark_boundary_hash"
        ],
        "stage_boundaries_hash": stage_boundaries["stage_boundaries_hash"],
        "stage_boundary_hashes": dict(stage_boundaries["stage_boundary_hashes"]),
        "candidate_execution_contract_hash": execution_contract[
            "execution_contract_hash"
        ],
        "candidate_matrix_hash": candidate_matrix["candidate_matrix_hash"],
        "protocol_boundary_hash": protocol["protocol_boundary_hash"],
        "protocol_version": protocol["protocol_version"],
        "call_budget_hash": call_budget["call_budget_hash"],
        "prompt_authority_hash": prompt_authority["prompt_authority_hash"],
        "prompt_authority_by_stage": {
            stage: row["stage_prompt_authority_hash"]
            for stage, row in prompt_authority["stages"].items()
        },
        "pre_call_prompt_guard": (
            "build_qualification_transport_after_prompt_guard"
        ),
        "pre_call_prompt_guard_runs_before_transport_factory": True,
        "p06_submission_request_set_hash": requests["request_set_hash"],
        "p06_property_observation_bindings_hash": observations[
            "observation_bindings_hash"
        ],
        "p06_submission_group_count": requests["submission_group_count"],
        "p06_single_route_group_count": requests["single_route_group_count"],
        "p06_multi_route_group_count": requests["multi_route_group_count"],
        "p06_executable_route_count": requests["route_count"],
        "p06_property_observation_count": observations["binding_count"],
        "p06_candidate_scoring_property_count": observations[
            "candidate_scoring_property_count"
        ],
        "n3_axis_hash": n3_axis["n3_axis_hash"],
        "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
        "n3_protocol_version": n3_axis["protocol_version"],
        "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
        "n3_adjudication_population_contract": N3_ADJUDICATION_POPULATION_CONTRACT,
        "n3_adjudication_identity_fields": list(
            n3_axis["adjudication_identity"]["fields"]
        ),
        "n3_runs_per_exposure": N3_RUNS_PER_EXPOSURE,
        "n3_required_adjudication_rows_by_stage": dict(
            n3_axis["census"]["required_adjudication_rows_by_stage"]
        ),
        "n3_closed_verdict_vocabulary": list(N3_SAFETY_VERDICTS),
        "rung_collection_hash": rung_collection["rung_collection_hash"],
        "semantic_qualification_claim_hash": claim["claim_hash"],
        "semantic_qualification_claim": claim["claim"],
        "semantic_claim_limitations": list(claim["limitations"]),
        "semantic_qualification_applicable_benchmark_version": claim[
            "applicable_benchmark_version"
        ],
        "lineage_hash": lineage["lineage_hash"],
        "convergence_delta_hash": delta["delta_hash"],
        "execution_counters": {
            "provider_calls": 0,
            "adjudicator_calls": 0,
            "credentials_resolved": 0,
            "real_transport_constructed": False,
            "pricing_refreshed": False,
            "high_smoke_executed": False,
            "billable_authorizations": 0,
            "authorization": "NONE",
            "candidate_outcomes_read": False,
        },
        "qualification_run": False,
        "high_smoke_authorized": False,
        "results_firewall": (
            "No provider or adjudicator outcome may enter this pre-results freeze."
        ),
        "stop_condition": (
            "Fresh audit remains separate; this freeze is not a PASS and does "
            "not authorize provider execution."
        ),
        "immutable_after_this_point": True,
    }
    return {**material, "freeze_material_hash": canonical_hash(material)}


def _walk_key_values(value: Any, key_name: str, path: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == key_name:
                yield child_path, child
            yield from _walk_key_values(child, key_name, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_key_values(child, key_name, f"{path}[{index}]")


def assert_single_n3_axis_authority(
    package: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    axis_path = f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json"
    try:
        expected = package[axis_path]["n3_axis_hash"]
    except KeyError as exc:
        raise FreezePublicationError("current standalone N3 axis is absent") from exc
    occurrences: list[dict[str, str]] = []
    for relative, document in package.items():
        for path, value in _walk_key_values(document, "n3_axis_hash"):
            occurrences.append({"artifact": relative, "path": path, "value": value})
    stale = [row for row in occurrences if row["value"] != expected]
    if stale:
        raise FreezePublicationError(f"ACTIVE_N3_AXIS_HASH_MISMATCH::{stale}")
    required_artifacts = {
        axis_path,
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json",
        f"{DEFINITION_ROOT}/phase9/candidate_execution_contract.json",
        f"{REPORT_ROOT}/benchmark_boundary.json",
        f"{REPORT_ROOT}/stage_boundaries.json",
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json",
    }
    observed_artifacts = {row["artifact"] for row in occurrences}
    missing = sorted(required_artifacts - observed_artifacts)
    if missing:
        raise FreezePublicationError(f"ACTIVE_N3_AXIS_BINDING_MISSING::{missing}")
    return {
        "n3_axis_hash": expected,
        "active_occurrence_count": len(occurrences),
        "occurrences": occurrences,
    }


def assert_prompt_authority_bindings(
    package: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    prompt_path = f"{DEFINITION_ROOT}/phase9/executable_prompt_authority.json"
    prompt = package[prompt_path]
    expected = prompt["prompt_authority_hash"]
    direct_paths = {
        f"{DEFINITION_ROOT}/phase9/candidate_execution_contract.json": (
            "prompt_authority_hash"
        ),
        f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": "prompt_authority_hash",
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": (
            "prompt_authority_hash"
        ),
        f"{REPORT_ROOT}/benchmark_boundary.json": "prompt_authority_hash",
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": (
            "prompt_authority_hash"
        ),
    }
    mismatches: list[str] = []
    for relative, field in direct_paths.items():
        if package.get(relative, {}).get(field) != expected:
            mismatches.append(f"{relative}.{field}")
    boundaries = package[f"{REPORT_ROOT}/stage_boundaries.json"]
    for stage, expected_row in prompt["stages"].items():
        stage_boundary = boundaries["stages"][stage]
        if stage_boundary.get("executable_prompt_authority") != expected_row:
            mismatches.append(f"stage_boundaries.{stage}.executable_prompt_authority")
        if stage_boundary.get("prompt_authority_set_hash") != expected:
            mismatches.append(f"stage_boundaries.{stage}.prompt_authority_set_hash")
    if mismatches:
        raise FreezePublicationError(
            f"ACTIVE_EXECUTABLE_PROMPT_BINDING_MISMATCH::{mismatches}"
        )
    return {
        "prompt_authority_hash": expected,
        "active_stage_count": len(prompt["stages"]),
        "stages": list(prompt["stages"]),
    }


SELF_MATERIAL_HASH_FIELD: Mapping[str, str] = {
    f"{DEFINITION_ROOT}/phase9/executable_prompt_authority.json": (
        "prompt_authority_hash"
    ),
    f"{DEFINITION_ROOT}/phase9/p06_submission_requests.json": "request_set_hash",
    f"{DEFINITION_ROOT}/phase9/p06_property_observation_bindings.json": (
        "observation_bindings_hash"
    ),
    f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": "n3_axis_hash",
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": "fixture_set_hash",
    f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": "claim_hash",
    f"{DEFINITION_ROOT}/phase9/candidate_execution_contract.json": (
        "execution_contract_hash"
    ),
    f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": "candidate_matrix_hash",
    f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": (
        "protocol_boundary_hash"
    ),
    f"{REPORT_ROOT}/stage_boundaries.json": "stage_boundaries_hash",
    f"{REPORT_ROOT}/benchmark_boundary.json": "benchmark_boundary_hash",
    f"{REPORT_ROOT}/phase9/call_budget.json": "call_budget_hash",
    f"{REPORT_ROOT}/phase9/rung_collection_authority.json": (
        "rung_collection_hash"
    ),
    f"{REPORT_ROOT}/lineage.json": "lineage_hash",
    f"{REPORT_ROOT}/phase9/convergence_delta.json": "delta_hash",
    f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": (
        "freeze_material_hash"
    ),
}


def self_material_hash(path: str, document: Mapping[str, Any]) -> str:
    try:
        field = SELF_MATERIAL_HASH_FIELD[path]
    except KeyError as exc:
        raise FreezePublicationError(f"unregistered artifact {path}") from exc
    declared = document.get(field)
    recomputed = canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )
    if declared != recomputed:
        raise FreezePublicationError(
            f"{path}.{field} declares {declared}, recomputed {recomputed}"
        )
    return recomputed


def validate_v135_package_for_publication(
    package: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if set(package) != set(SELF_MATERIAL_HASH_FIELD):
        raise FreezePublicationError(
            "V135_PACKAGE_REGISTRY_MISMATCH::"
            f"unregistered={sorted(set(package) - set(SELF_MATERIAL_HASH_FIELD))}::"
            f"missing={sorted(set(SELF_MATERIAL_HASH_FIELD) - set(package))}"
        )
    # Cross-document single-authority invariants run before document self-hash
    # checks so a stale active binding is reported as the authority violation it
    # is, rather than only as generic tampering with the containing document.
    n3 = assert_single_n3_axis_authority(package)
    prompts = assert_prompt_authority_bindings(package)
    for relative, document in package.items():
        if "/v1_3_4/" in relative:
            raise FreezePublicationError("v1.3.5 publication targets v1.3.4 bytes")
        self_material_hash(relative, document)
    freeze = package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"]
    expected_counters = {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credentials_resolved": 0,
        "real_transport_constructed": False,
        "pricing_refreshed": False,
        "high_smoke_executed": False,
        "billable_authorizations": 0,
        "authorization": "NONE",
        "candidate_outcomes_read": False,
    }
    if freeze.get("execution_counters") != expected_counters:
        raise FreezePublicationError("pre-results execution counters are not zero")
    return {
        "artifact_count": len(package),
        "n3_binding_count": n3["active_occurrence_count"],
        "prompt_stage_count": prompts["active_stage_count"],
        "execution_counters_zero": True,
    }


def v135_package(build: V135Build) -> dict[str, dict[str, Any]]:
    """Build and validate every 1.3.5 artifact without writing files."""

    prompt_authority = executable_prompt_authority()
    requests = p06_submission_requests_document(build)
    observations = p06_property_observation_bindings_document(build)
    n3_axis = n3_axis_v135(build)
    n3_fixtures = n3_provider_fixture_authority_current(build.corpus_root)
    claim = semantic_qualification_claim_v135(build)
    call_budget = call_budget_v135(build, n3_axis, n3_fixtures)
    rung_collection = rung_collection_authority()
    stage_boundaries = stage_boundaries_v135(
        prompt_authority=prompt_authority,
        n3_axis=n3_axis,
        n3_fixtures=n3_fixtures,
        requests=requests,
        observations=observations,
        call_budget=call_budget,
        claim=claim,
    )
    execution_contract = candidate_execution_contract_v135(
        prompt_authority=prompt_authority,
        stage_boundaries=stage_boundaries,
        requests=requests,
        observations=observations,
        n3_axis=n3_axis,
        n3_fixtures=n3_fixtures,
        call_budget=call_budget,
        rung_collection=rung_collection,
    )
    benchmark_boundary = benchmark_boundary_v135(
        n3_axis=n3_axis,
        n3_fixtures=n3_fixtures,
        claim=claim,
        prompt_authority=prompt_authority,
        stage_boundaries=stage_boundaries,
        execution_contract=execution_contract,
        requests=requests,
        observations=observations,
        rung_collection=rung_collection,
    )
    candidate_matrix = candidate_matrix_v135(
        benchmark_boundary=benchmark_boundary,
        execution_contract=execution_contract,
        prompt_authority=prompt_authority,
        rung_collection=rung_collection,
    )
    protocol = qualification_protocol_v135(
        n3_axis=n3_axis,
        n3_fixtures=n3_fixtures,
        claim=claim,
        benchmark_boundary=benchmark_boundary,
        candidate_matrix=candidate_matrix,
        execution_contract=execution_contract,
        prompt_authority=prompt_authority,
        requests=requests,
        observations=observations,
        call_budget=call_budget,
        rung_collection=rung_collection,
    )
    lineage = lineage_v135()
    delta = convergence_delta_v135(
        build=build,
        requests=requests,
        observations=observations,
        prompt_authority=prompt_authority,
        n3_axis=n3_axis,
        n3_fixtures=n3_fixtures,
    )
    freeze = pre_results_freeze_v135(
        build=build,
        n3_axis=n3_axis,
        n3_fixtures=n3_fixtures,
        claim=claim,
        prompt_authority=prompt_authority,
        requests=requests,
        observations=observations,
        call_budget=call_budget,
        rung_collection=rung_collection,
        stage_boundaries=stage_boundaries,
        execution_contract=execution_contract,
        benchmark_boundary=benchmark_boundary,
        candidate_matrix=candidate_matrix,
        protocol=protocol,
        lineage=lineage,
        delta=delta,
    )
    package = {
        f"{DEFINITION_ROOT}/phase9/executable_prompt_authority.json": prompt_authority,
        f"{DEFINITION_ROOT}/phase9/p06_submission_requests.json": requests,
        f"{DEFINITION_ROOT}/phase9/p06_property_observation_bindings.json": observations,
        f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": n3_axis,
        f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": n3_fixtures,
        f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": claim,
        f"{DEFINITION_ROOT}/phase9/candidate_execution_contract.json": execution_contract,
        f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": candidate_matrix,
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": protocol,
        f"{REPORT_ROOT}/stage_boundaries.json": stage_boundaries,
        f"{REPORT_ROOT}/benchmark_boundary.json": benchmark_boundary,
        f"{REPORT_ROOT}/phase9/call_budget.json": call_budget,
        f"{REPORT_ROOT}/phase9/rung_collection_authority.json": rung_collection,
        f"{REPORT_ROOT}/lineage.json": lineage,
        f"{REPORT_ROOT}/phase9/convergence_delta.json": delta,
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": freeze,
    }
    validate_v135_package_for_publication(package)
    return package
