"""Product-shaped P04-P09 synthetic rehearsal over production boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import re
from typing import Any, cast
import unicodedata

from pydantic import BaseModel, SecretStr

from .canonical import canonical_hash, sha256_text, stable_id
from .contracts import model_by_name, models as m
from .model_gateway import (
    CallBudget,
    GatewayCallResult,
    GatewayContextError,
    GatewayError,
    GatewayConfig,
    GatewayMode,
    GatewaySchemaViolation,
    ModelGateway,
    LUNA_MODEL_ID,
    OPENAI_MAX_PROMPT_IDS,
    OPENAI_MAX_ROUTE_PROFILE_ID,
    OPENAI_ROUTE_PROFILE_ID,
    OPENAI_SOL_HIGH_PROMPT_IDS,
    OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
    OPENAI_SOL_MEDIUM_PROMPT_IDS,
    OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
    OPENAI_SOL_XHIGH_PROMPT_IDS,
    OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_MEDIUM_PROMPT_IDS,
    OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
    OPENAI_TERRA_HIGH_PROMPT_IDS,
    OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
    OPENAI_TERRA_XHIGH_PROMPT_IDS,
    OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
    OPENAI_XHIGH_PROMPT_IDS,
    OPENAI_XHIGH_ROUTE_PROFILE_ID,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
    ProviderBudgetError,
    RequestCappedAdapter,
    build_openai_cost_estimator,
    build_openai_input_token_estimator,
    build_openai_routes,
    build_mock_request,
    build_trusted_context,
    SOL_MODEL_ID,
    TERRA_MODEL_ID,
)
from .model_gateway.openai_adapter import OPENAI_SDK_VERSION
from .model_gateway.mock_factory import DeterministicMockAdapter
from .model_gateway.openai_pricing import (
    LONG_CONTEXT_THRESHOLD,
    MODEL_PRICES,
    PRICING_OBSERVED_DATE,
    PRICING_SOURCE_URL,
    estimate_cost_usd,
)
from .model_gateway.openai_routes import REQUEST_FRAMING_TOKEN_ALLOWANCE
from .model_gateway.registry import PROMPT_VERSION, prompt_spec
from .model_gateway.gateway import PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS
from .planning import PLANNER_VERSION, build_assessment_plan
from .observability import p08_decision_diagnostics
from .qualification_semantics import (
    CheckpointAssessment,
    CheckpointClass,
    ContractualAdherence,
    OracleValidity,
    SemanticInterpretation,
    aggregate_causal_classification,
    classify_checkpoint,
)
from .validation import (
    ContextValidationError,
    PROMPT_APPLICATION_VALIDATOR_VERSIONS,
    blueprint_review_preflight_expected_checks,
    build_blueprint_review_preflight,
    validate_assessment_plan,
    validate_blueprint_review_preflight_checks,
    validate_evaluation_guide,
    validate_evidence_map,
    validate_generation_result,
    validate_review_result,
)
from .web.workflows import (
    ASSEMBLER_VERSION,
    assemble_assessment_snapshot,
    selected_question_from_candidate,
)


REHEARSAL_VERSION = "stage2-product-rehearsal/1.12.0"
REHEARSAL_REPORT_VERSION = "stage2-convergence-report/1.12.0"
BASE_SCENARIO_ID = "synthetic-open-short-v1"
VARIANT_SCENARIO_ID = "synthetic-choice-justification-v1"
CANONICAL_DOCUMENT_SCENARIO_ID = "canonical-document-cache-sufficient-v1"
P05_GOLDEN_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/openai_evals/v2/p05_golden_checkpoints.json"
)
PRODUCT_REHEARSAL_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/openai_evals/v2/product_rehearsal.json"
)
SEMANTIC_QUALIFICATION_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/openai_evals/v3/semantic_qualification_pack.json"
)


@dataclass(frozen=True, slots=True)
class QualificationMatrixRow:
    row_id: str
    check_kind: str
    max_provider_calls: int
    stage_scope: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "check_kind": self.check_kind,
            "max_provider_calls": self.max_provider_calls,
            "stage_scope": self.stage_scope,
        }


QUALIFICATION_MATRIX_ROWS = (
    QualificationMatrixRow(
        "semantic-sweep:P04-P09:versioned-positive-and-negative",
        "SEMANTIC_STAGE_LOCAL_ATTRIBUTION",
        9,
        "P04,P05+,P05-,P06,P07+,P07-,P08+,P08-,P09",
    ),
    QualificationMatrixRow(
        "offline-golden-positive:P05",
        "DETERMINISTIC_OFFLINE_ORACLE_CHECK",
        0,
        "P05+",
    ),
    QualificationMatrixRow(
        "offline-golden-negative:P05",
        "DETERMINISTIC_OFFLINE_ORACLE_CHECK",
        0,
        "P05-",
    ),
    QualificationMatrixRow(
        "integrated-chain:base:1:P04-P09",
        "INTEGRATED_COMPOSITIONAL_CHECK",
        6,
        "P04-P09 plus planner/assembly",
    ),
    QualificationMatrixRow(
        "integrated-chain:base:2:P04-P09",
        "INTEGRATED_COMPOSITIONAL_CHECK",
        6,
        "P04-P09 plus planner/assembly",
    ),
    QualificationMatrixRow(
        "integrated-chain:choice-variant:P04-P09",
        "INTEGRATED_COMPOSITIONAL_CHECK",
        6,
        "P04-P09 plus planner/assembly",
    ),
    QualificationMatrixRow(
        "integrated-chain:canonical-document-sufficient:P04-P09",
        "INTEGRATED_COMPOSITIONAL_CHECK",
        6,
        "DOCX parser boundary through P09 plus planner/assembly",
    ),
)
QUALIFICATION_EXPECTED_PROVIDER_REQUESTS = sum(
    row.max_provider_calls for row in QUALIFICATION_MATRIX_ROWS
)

# The semantic sweep calls P05, P07 and P08 twice to exercise one reviewed
# positive and one reviewed negative. Each integrated row calls P04-P09 once.
# Keeping this plan next to the matrix makes the monetary cap derivable from
# the exact provider-call surface instead of from an expected spend.
QUALIFICATION_SEMANTIC_SWEEP_CALLS_BY_PROMPT = {
    "P04_BLUEPRINT_BUILD_V1": 1,
    "P05_BLUEPRINT_REVIEW_V1": 2,
    "P06_EVIDENCE_MAP_V1": 1,
    "P07_QUESTION_BUILD_V1": 2,
    "P08_QUESTION_REVIEW_V1": 2,
    "P09_GUIDE_BUILD_V1": 1,
}
QUALIFICATION_INTEGRATED_CHAIN_COUNT = sum(
    row.check_kind == "INTEGRATED_COMPOSITIONAL_CHECK"
    for row in QUALIFICATION_MATRIX_ROWS
)
QUALIFICATION_PROVIDER_CALLS_BY_PROMPT = {
    prompt_id: semantic_calls + QUALIFICATION_INTEGRATED_CHAIN_COUNT
    for prompt_id, semantic_calls in (
        QUALIFICATION_SEMANTIC_SWEEP_CALLS_BY_PROMPT.items()
    )
}
if sum(QUALIFICATION_PROVIDER_CALLS_BY_PROMPT.values()) != (
    QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
):
    raise AssertionError("qualification prompt counts must match the matrix")


def qualification_matrix_rows() -> list[dict[str, Any]]:
    """Return the evidence-first matrix from which the request cap is derived."""

    return [row.model_dump() for row in QUALIFICATION_MATRIX_ROWS]


def _ceil_usd(value: Decimal, increment: Decimal) -> float:
    units = (value / increment).to_integral_value(rounding=ROUND_CEILING)
    return float(units * increment)


def _model_budget_derivation(
    *,
    route_profile_id: str,
    model_id: str,
    schema_version: str,
    pricing_policy_observed_at: str | None = None,
) -> dict[str, Any]:
    """Derive exact caps from the frozen matrix and route ceilings."""

    routes = build_openai_routes(
        max_call_cost_usd=1.0,
        route_profile_id=route_profile_id,
    )
    prices = MODEL_PRICES[model_id]
    per_prompt: dict[str, dict[str, Any]] = {}
    worst_case_total = Decimal("0")
    maximum_call = Decimal("0")
    for prompt_id, call_count in QUALIFICATION_PROVIDER_CALLS_BY_PROMPT.items():
        route = routes[prompt_id]
        if route.model != model_id:
            raise AssertionError("qualification budget cannot mix models")
        input_ceiling = route.max_input_tokens
        output_ceiling = route.max_output_tokens
        call_cost = Decimal(
            str(
                estimate_cost_usd(
                    model=model_id,
                    input_tokens=input_ceiling,
                    cache_write_tokens=input_ceiling,
                    output_tokens=output_ceiling,
                )
            )
        )
        subtotal = call_cost * call_count
        maximum_call = max(maximum_call, call_cost)
        worst_case_total += subtotal
        per_prompt[prompt_id] = {
            "provider_calls": call_count,
            "route_input_token_ceiling": input_ceiling,
            "route_output_token_ceiling": output_ceiling,
            "request_framing_token_allowance": (
                REQUEST_FRAMING_TOKEN_ALLOWANCE
            ),
            "long_context_pricing_applies": (
                input_ceiling > LONG_CONTEXT_THRESHOLD
            ),
            "conservative_input_class": "FULL_CACHE_WRITE",
            "conservative_call_cost_usd": float(call_cost),
            "conservative_subtotal_usd": float(subtotal),
        }

    cap_increment = Decimal("0.01")
    pricing_policy = {
        "observed_date": PRICING_OBSERVED_DATE,
        "source_url": PRICING_SOURCE_URL,
        "model": model_id,
        "standard_short_context_usd_per_million": {
            "input": prices.input_per_million,
            "cached_input": prices.cached_input_per_million,
            "cache_write": prices.input_per_million * 1.25,
            "output": prices.output_per_million,
        },
        "cache_write_multiplier": 1.25,
        "long_context_threshold_tokens_exclusive": (
            LONG_CONTEXT_THRESHOLD
        ),
        "long_context_multipliers": {"input": 2.0, "output": 1.5},
        "reservation_policy": (
            "ROUTE_INPUT_CEILING_AS_FULL_CACHE_WRITE_PLUS_ROUTE_OUTPUT_CEILING"
        ),
        "cap_rounding": "CEILING_TO_USD_0.01",
    }
    if pricing_policy_observed_at is not None:
        pricing_policy["observed_at"] = pricing_policy_observed_at
    return {
        "schema_version": schema_version,
        "route_profile": route_profile_id,
        "model": model_id,
        "pricing_policy": pricing_policy,
        "pricing_policy_hash": canonical_hash(pricing_policy),
        "matrix_hash": canonical_hash(qualification_matrix_rows()),
        "matrix_provider_calls": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        "max_provider_requests": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        "integrated_chain_count": QUALIFICATION_INTEGRATED_CHAIN_COUNT,
        "provider_calls_by_prompt": dict(
            QUALIFICATION_PROVIDER_CALLS_BY_PROMPT
        ),
        "per_prompt": per_prompt,
        "maximum_conservative_call_cost_usd": float(maximum_call),
        "worst_case_conservative_total_cost_usd": float(worst_case_total),
        "cap_rounding_increment_usd": float(cap_increment),
        "max_call_cost_usd": _ceil_usd(maximum_call, cap_increment),
        "max_total_cost_usd": _ceil_usd(
            worst_case_total, cap_increment
        ),
    }


def terra_medium_budget_derivation() -> dict[str, Any]:
    return _model_budget_derivation(
        route_profile_id=OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
        model_id=TERRA_MODEL_ID,
        schema_version="terra-medium-budget-derivation/1.0.0",
    )


def terra_high_budget_derivation() -> dict[str, Any]:
    return _model_budget_derivation(
        route_profile_id=OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
        model_id=TERRA_MODEL_ID,
        schema_version="terra-high-budget-derivation/1.0.0",
    )


def terra_xhigh_budget_derivation() -> dict[str, Any]:
    return _model_budget_derivation(
        route_profile_id=OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        model_id=TERRA_MODEL_ID,
        schema_version="terra-xhigh-budget-derivation/1.0.0",
    )


SOL_PRICING_POLICY_OBSERVED_AT = "2026-08-14T14:50:29Z"


def sol_medium_budget_derivation() -> dict[str, Any]:
    return _model_budget_derivation(
        route_profile_id=OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
        model_id=SOL_MODEL_ID,
        schema_version="sol-medium-budget-derivation/1.0.0",
        pricing_policy_observed_at=SOL_PRICING_POLICY_OBSERVED_AT,
    )


def sol_high_budget_derivation() -> dict[str, Any]:
    return _model_budget_derivation(
        route_profile_id=OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
        model_id=SOL_MODEL_ID,
        schema_version="sol-high-budget-derivation/1.0.0",
        pricing_policy_observed_at=SOL_PRICING_POLICY_OBSERVED_AT,
    )


def sol_xhigh_budget_derivation() -> dict[str, Any]:
    return _model_budget_derivation(
        route_profile_id=OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
        model_id=SOL_MODEL_ID,
        schema_version="sol-xhigh-budget-derivation/1.0.0",
        pricing_policy_observed_at=SOL_PRICING_POLICY_OBSERVED_AT,
    )


@dataclass(frozen=True, slots=True)
class RehearsalCheckpoints:
    scenario_id: str
    p04_request: m.BlueprintBuildRequest
    p05_request: m.BlueprintReviewRequest
    p06_request: m.EvidenceMapRequest
    p07_request: m.QuestionBuildRequest
    p08_request: m.QuestionReviewRequest
    p09_request: m.GuideBuildRequest

    @property
    def hashes(self) -> dict[str, str]:
        return {
            "post_p03": canonical_hash(
                {
                    "p04": self.p04_request.model_dump(mode="json"),
                    "p05": self.p05_request.model_dump(mode="json"),
                }
            ),
            "blueprint_valid": canonical_hash(
                self.p06_request.model_dump(mode="json")
            ),
            "mapping_planning_valid": canonical_hash(
                {
                    "p07": self.p07_request.model_dump(mode="json"),
                    "p08": self.p08_request.model_dump(mode="json"),
                }
            ),
            "assessment_valid": canonical_hash(
                self.p09_request.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class RehearsalObservation:
    run_id: str
    run_kind: str
    scenario_id: str
    status: str
    stages: tuple[dict[str, Any], ...]
    failure: dict[str, Any] | None
    output_hash: str | None
    checkpoint_assessments: tuple[dict[str, Any], ...] = ()


def _validated_mock_output(prompt_id: str, request: BaseModel) -> BaseModel:
    """Produce a canonical checkpoint dependency without network transport."""

    from .model_gateway import DeterministicMockFactory, MockBehavior

    return DeterministicMockFactory().output_for(
        prompt_id, request, MockBehavior.HAPPY
    )


def _base_p04_request() -> m.BlueprintBuildRequest:
    request = m.BlueprintBuildRequest.model_validate(
        build_mock_request("P04_BLUEPRINT_BUILD_V1").model_dump(mode="json")
    )
    activity_spec = request.activity_spec.model_copy(
        update={
            "learning_outcomes": [
                item.model_copy(
                    update={
                        "text": (
                            "Explicar cómo un cambio en la fuente invalida la "
                            "entrada almacenada y fuerza un recálculo verificable."
                        )
                    }
                )
                for item in request.activity_spec.learning_outcomes
            ],
            "expected_products": [
                item.model_copy(
                    update={
                        "text": (
                            "Un entregable explicativo que conecte la mutación "
                            "de la fuente, la invalidación y la nueva consulta."
                        )
                    }
                )
                for item in request.activity_spec.expected_products
            ],
            "requirements": [
                item.model_copy(
                    update={
                        "text": (
                            "Justificar por qué reutilizar la entrada previa "
                            "produciría un valor obsoleto."
                        )
                    }
                )
                for item in request.activity_spec.requirements
            ],
        }
    )
    rubric_spec = request.rubric_spec.model_copy(
        update={
            "criteria": [
                criterion.model_copy(
                    update={
                        "name": "Explicación causal de invalidación de caché",
                        "description": (
                            "Relaciona cambio de fuente, invalidación, reconsulta "
                            "y recálculo sin atribuir el resultado a la entrada previa."
                        ),
                        "observables": [
                            "Ordena la secuencia causal completa.",
                            "Vincula la invalidación con la prevención de resultados obsoletos.",
                        ],
                        "levels": [
                            level.model_copy(
                                update={
                                    "descriptor": (
                                        "Explica la relación causal entre el cambio "
                                        "de fuente, la invalidación y el recálculo."
                                    )
                                }
                            )
                            for level in criterion.levels
                        ],
                    }
                )
                for criterion in request.rubric_spec.criteria
            ]
        }
    )
    return request.model_copy(
        update={
            "target_blueprint_id": "blueprint_cache_invalidation_golden",
            "activity_spec": activity_spec,
            "rubric_spec": rubric_spec,
        }
    )


def _p05_golden_fixture() -> dict[str, Any]:
    raw = json.loads(P05_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8"))
    if (
        raw.get("schema_version") != "stage2-p05-golden-checkpoints/1.2.0"
        or raw.get("classification") != "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    ):
        raise ValueError("P05 golden fixture metadata is not approved")
    return cast(dict[str, Any], raw)


def _semantic_instrument_metadata() -> dict[str, Any]:
    legacy = json.loads(
        PRODUCT_REHEARSAL_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    replacement = json.loads(
        SEMANTIC_QUALIFICATION_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    if legacy.get("schema_version") != "stage2-product-rehearsal-fixture/1.5.0":
        raise ValueError("legacy rehearsal classification is not approved")
    if replacement.get("schema_version") != (
        "stage2-semantic-qualification-pack/1.1.0"
    ):
        raise ValueError("replacement semantic fixture is not approved")
    return {
        "legacy_sweep_status": legacy["instrument_semantic_status"],
        "legacy_semantic_quality_conclusions_allowed": legacy[
            "execution_discovery"
        ]["semantic_quality_conclusions_allowed"],
        "replacement_fixture": legacy["replacement_fixture"],
        "replacement_fixture_hash": canonical_hash(replacement),
        "replacement_review_set_id": replacement["review_set_id"],
        "replacement_review_version": replacement["review_version"],
        "source_artifact_hashes": {
            artifact["artifact_key"]: artifact["sha256"]
            for artifact in replacement["artifacts"]
        },
        "semantic_sweep_checkpoint_ids": [
            "P04_CANONICAL_POSITIVE",
            "P05_CANONICAL_POSITIVE",
            "P05_PLAN_FEASIBILITY_NEGATIVE",
            "P06_CANONICAL_POSITIVE",
            "P07_CANONICAL_POSITIVE",
            "P07_INSUFFICIENT_NEGATIVE",
            "P08_CANONICAL_POSITIVE",
            "P08_UNANSWERABLE_NEGATIVE",
            "P09_CANONICAL_POSITIVE",
        ],
        "expected_provider_requests": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
        "replacement_status": "READY_FOR_INDEPENDENT_HARNESS_REVIEW",
    }


def _golden_blueprint(scenario_id: str) -> m.AssessmentBlueprint:
    fixture = _p05_golden_fixture()
    blueprint = m.AssessmentBlueprint.model_validate(
        fixture["golden_positive"]["blueprint"]
    )
    if scenario_id == BASE_SCENARIO_ID:
        return blueprint
    choice = fixture["golden_positive"]["choice_variant"]
    choice_formats = [m.ResponseFormat.CHOICE]
    dimensions = []
    for dimension in blueprint.dimensions:
        variants = []
        for variant in dimension.evidence_variants:
            variants.append(
                variant.model_copy(
                    update={
                        "question_opportunities": [
                            opportunity.model_copy(
                                update={
                                    "allowed_response_formats": choice_formats,
                                    "student_justification_required": True,
                                }
                            )
                            for opportunity in variant.question_opportunities
                        ]
                    }
                )
            )
        dimensions.append(
            dimension.model_copy(update={"evidence_variants": variants})
        )
    return blueprint.model_copy(
        update={
            "blueprint_id": choice["blueprint_id"],
            "dimensions": dimensions,
            "assessment_constraints": blueprint.assessment_constraints.model_copy(
                update={
                    "allowed_response_formats": choice_formats,
                    "structured_justification_policy": (
                        m.StructuredJustificationPolicy(
                            mode=m.StructuredJustificationMode.ALL,
                            selected_opportunity_template_ids=[],
                        )
                    ),
                }
            ),
        }
    )


def _expanded_rehearsal_bundle(
    bundle: m.EvidenceBundle,
) -> m.EvidenceBundle:
    """Represent a sufficient product-shaped submission with multiple units."""

    base = bundle.evidence_units[0]
    additions = []
    for index, (evidence_id, artifact_id, content_text) in enumerate(
        (
            (
                "ev_submission_2",
                "art_submission",
                "Cuando la fuente cambia, la entrada previa se invalida para evitar devolver un resultado obsoleto.",
            ),
            (
                "ev_submission_3",
                "art_submission_test",
                "Una prueba sintética modifica la fuente, repite la consulta y verifica que el valor se recalcula.",
            ),
        ),
        start=1,
    ):
        additions.append(
            base.model_copy(
                update={
                    "evidence_id": evidence_id,
                    "artifact_id": artifact_id,
                    "artifact_hash": canonical_hash(
                        {"synthetic_artifact_id": artifact_id}
                    ),
                    "locator": m.DocumentLocator(
                        paragraph_index=index,
                        heading_path=["Sección sintética"],
                    ),
                    "content_text": content_text,
                    "normalized_hash": sha256_text(content_text),
                }
            )
        )
    evidence_units = [base, *additions]
    return bundle.model_copy(
        update={
            "bundle_id": "bundle_stage2_rehearsal_v2",
            "allowed_evidence_ids": [
                item.evidence_id for item in evidence_units
            ],
            "evidence_units": evidence_units,
        }
    )


def build_rehearsal_checkpoints(
    scenario_id: str = BASE_SCENARIO_ID,
) -> RehearsalCheckpoints:
    """Build reproducible canonical checkpoints A-D from product contracts."""

    if scenario_id not in {BASE_SCENARIO_ID, VARIANT_SCENARIO_ID}:
        raise ValueError("unknown synthetic rehearsal scenario")
    p04 = _base_p04_request()
    if scenario_id == VARIANT_SCENARIO_ID:
        policy = p04.blueprint_policy.model_copy(
            update={
                "policy_id": "blueprint_policy_choice_variant",
                "allowed_response_formats": [m.ResponseFormat.CHOICE],
                "structured_justification_policy": (
                    m.StructuredJustificationPolicy(
                        mode=m.StructuredJustificationMode.ALL,
                        selected_opportunity_template_ids=[],
                    )
                ),
            }
        )
        p04 = p04.model_copy(
            update={
                "target_blueprint_id": "blueprint_choice_variant",
                "target_blueprint_version": 1,
                "blueprint_policy": policy,
            }
        )

    generated_blueprint = _golden_blueprint(scenario_id)
    p05 = m.BlueprintReviewRequest(
        activity_spec=p04.activity_spec,
        rubric_spec=p04.rubric_spec,
        blueprint_policy=p04.blueprint_policy,
        resolved_decisions=p04.resolved_decisions,
        blueprint=generated_blueprint,
        deterministic_preflight=build_blueprint_review_preflight(
            blueprint=generated_blueprint,
            activity_spec=p04.activity_spec,
            rubric_spec=p04.rubric_spec,
            blueprint_policy=p04.blueprint_policy,
        ),
    )

    p06 = m.EvidenceMapRequest.model_validate(
        build_mock_request("P06_EVIDENCE_MAP_V1").model_dump(mode="json")
    )
    p06 = p06.model_copy(
        update={
            "blueprint": generated_blueprint.model_copy(
                update={"status": m.WorkflowStatus.APPROVED}
            ),
            "planning_policy": p04.blueprint_policy.planning_policy,
            "evidence_bundle": _expanded_rehearsal_bundle(
                p06.evidence_bundle
            )
        }
    )
    mapping = m.EvidenceMapPatch.model_validate(
        _validated_mock_output("P06_EVIDENCE_MAP_V1", p06).model_dump(
            mode="json"
        )
    )
    validate_evidence_map(
        mapping,
        blueprint=p06.blueprint,
        bundle=p06.evidence_bundle,
        planning_policy=p06.planning_policy,
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=p06.blueprint,
        policy=m.AssessmentPlanningPolicy(
            policy_id="planning_policy_checkpoint",
            minimum_opportunity_quality=(
                p06.blueprint.assessment_constraints.minimum_opportunity_quality
            ),
            max_reserve_opportunities=(
                p06.blueprint.assessment_constraints.max_reserve_opportunities
            ),
        ),
    )
    validate_assessment_plan(plan, mapping=mapping)
    opportunity_by_id = {
        opportunity.opportunity_id: opportunity
        for opportunity in mapping.opportunities
    }
    opportunity = opportunity_by_id[plan.selected_opportunity_ids[0]]
    p07 = m.QuestionBuildRequest(
        target_candidate_id="candidate_checkpoint",
        plan=plan,
        opportunity=opportunity,
        evidence_bundle=p06.evidence_bundle,
        generation_policy=m.QuestionGenerationPolicy(
            policy_id="question_generation_checkpoint"
        ),
        avoid=[],
    )
    generation = m.QuestionGenerationResult.model_validate(
        _validated_mock_output("P07_QUESTION_BUILD_V1", p07).model_dump(
            mode="json"
        )
    )
    validate_generation_result(
        generation,
        opportunity=opportunity,
        bundle=p06.evidence_bundle,
    )
    p08 = m.QuestionReviewRequest(
        generation_result=generation,
        opportunity=opportunity,
        evidence_bundle=p06.evidence_bundle,
        validation_policy=m.QuestionValidationPolicy(
            policy_id="question_validation_checkpoint"
        ),
    )
    p09 = m.GuideBuildRequest.model_validate(
        build_mock_request("P09_GUIDE_BUILD_V1").model_dump(mode="json")
    )
    return RehearsalCheckpoints(
        scenario_id=scenario_id,
        p04_request=p04,
        p05_request=p05,
        p06_request=p06,
        p07_request=p07,
        p08_request=p08,
        p09_request=p09,
    )


def build_p05_golden_negative_request() -> m.BlueprintReviewRequest:
    """Build the versioned known-negative without weakening the P05 boundary."""

    p04 = _base_p04_request()
    blueprint = _golden_blueprint(BASE_SCENARIO_ID)
    choice_formats = [m.ResponseFormat.CHOICE]
    dimensions = []
    for dimension in blueprint.dimensions:
        variants = []
        for variant in dimension.evidence_variants:
            variants.append(
                variant.model_copy(
                    update={
                        "question_opportunities": [
                            opportunity.model_copy(
                                update={
                                    "allowed_response_formats": choice_formats
                                }
                            )
                            for opportunity in variant.question_opportunities
                        ]
                    }
                )
            )
        dimensions.append(
            dimension.model_copy(update={"evidence_variants": variants})
        )
    negative = blueprint.model_copy(
        update={
            "dimensions": dimensions,
            "assessment_constraints": blueprint.assessment_constraints.model_copy(
                update={"allowed_response_formats": choice_formats}
            ),
        }
    )
    return m.BlueprintReviewRequest(
        activity_spec=p04.activity_spec,
        rubric_spec=p04.rubric_spec,
        blueprint_policy=p04.blueprint_policy,
        resolved_decisions=p04.resolved_decisions,
        blueprint=negative,
        deterministic_preflight=build_blueprint_review_preflight(
            blueprint=negative,
            activity_spec=p04.activity_spec,
            rubric_spec=p04.rubric_spec,
            blueprint_policy=p04.blueprint_policy,
        ),
    )


def _p05_expected_check_matrix(
    preflight: m.BlueprintReviewPreflight,
) -> dict[str, dict[str, Any]]:
    return {
        category: {
            "status": status.value,
            "critical": critical,
        }
        for category, (status, critical) in (
            blueprint_review_preflight_expected_checks(preflight).items()
        )
    }


def _p05_actual_check_matrix(
    review: m.BlueprintReview,
    preflight: m.BlueprintReviewPreflight,
) -> dict[str, dict[str, Any]]:
    checks = {check.category: check for check in review.checks}
    return {
        category: {
            "status": checks[category].status.value,
            "critical": checks[category].critical,
        }
        for category in blueprint_review_preflight_expected_checks(preflight)
        if category in checks
    }


_P05_CHECK_CODES = {
    "CONSTRUCT": "BLUEPRINT_CONSTRUCT",
    "SOURCE_FIDELITY": "BLUEPRINT_SOURCE_FIDELITY",
    "COVERAGE": "BLUEPRINT_CONCEPTUAL_COVERAGE",
    "COMPARABILITY": "BLUEPRINT_CATALOG_DIVERSITY",
    "COGNITIVE_DEMAND": "BLUEPRINT_COGNITIVE_DEMAND",
    "TIME": "BLUEPRINT_TIME",
    "FORMAT_FEASIBILITY": "BLUEPRINT_FORMAT_FEASIBILITY",
    "OPPORTUNITY_CATALOG": "BLUEPRINT_OPPORTUNITY_CATALOG",
    "PLAN_FEASIBILITY": "BLUEPRINT_PLAN_FEASIBILITY",
    "ACCESSIBILITY": "BLUEPRINT_ACCESSIBILITY",
}


def _p05_review_from_versioned_semantic_fixture(
    request: m.BlueprintReviewRequest,
    *,
    negative: bool,
) -> m.BlueprintReview:
    """Materialize the reviewed oracle without consulting a mock or provider."""

    fixture = _p05_golden_fixture()
    categories = fixture["golden_positive"]["semantic_review"][
        "category_reviews"
    ]
    checks: list[m.BlueprintReviewCheck] = []
    for category, check_code in _P05_CHECK_CODES.items():
        reviewed = categories[category]
        status = reviewed["status"]
        critical = reviewed["critical"]
        message = reviewed["rationale"]
        correction = None
        if negative and category == "PLAN_FEASIBILITY":
            status = "FAIL"
            critical = True
            message = (
                "El catálogo mutado sólo permite CHOICE, mientras la política "
                "vigente exige OPEN_SHORT; no existe un plan autorizado."
            )
            correction = "Regenerar el catálogo desde la política vigente."
        checks.append(
            m.BlueprintReviewCheck(
                check_code=check_code,
                category=category,
                status=status,
                message=message,
                referenced_ids=reviewed["referenced_ids"],
                correction=correction,
                critical=critical,
            )
        )
    return m.BlueprintReview(
        activity_id=request.activity_spec.activity_id,
        blueprint_id=request.blueprint.blueprint_id,
        blueprint_version=request.blueprint.blueprint_version,
        status="READY",
        approval_recommendation=("REJECT" if negative else "APPROVE"),
        checks=checks,
        diagnostics=[],
    )


def evaluate_p05_golden_positive() -> dict[str, Any]:
    """Prove the positive product transition without requiring APPROVE."""

    fixture = _p05_golden_fixture()
    expected = fixture["golden_positive"]
    request = build_rehearsal_checkpoints(BASE_SCENARIO_ID).p05_request
    review = _p05_review_from_versioned_semantic_fixture(
        request,
        negative=False,
    )
    derived_preflight = build_blueprint_review_preflight(
        blueprint=request.blueprint,
        activity_spec=request.activity_spec,
        rubric_spec=request.rubric_spec,
        blueprint_policy=request.blueprint_policy,
    )
    validator_status = "PASS"
    try:
        validate_blueprint_review_preflight_checks(review, derived_preflight)
    except ContextValidationError:
        validator_status = "FAIL"
    critical_categories = sorted(
        {
            str(check.category)
            for check in review.checks
            if check.critical and check.status == m.ReviewCheckStatus.FAIL
        }
    )
    actual_transition = (
        "APPROVABLE"
        if blueprint_review_is_approvable(review)
        else "NOT_APPROVABLE"
    )
    status = (
        "PASS"
        if request.deterministic_preflight == derived_preflight
        and validator_status == "PASS"
        and actual_transition == expected["expected_transition"]
        and review.status == m.WorkflowStatus.READY
        and not critical_categories
        and review.approval_recommendation
        != m.BlueprintApprovalRecommendation.REJECT
        else "FAIL"
    )
    return {
        "check_id": "P05_GOLDEN_POSITIVE_OFFLINE",
        "status": status,
        "expected_transition": expected["expected_transition"],
        "actual_transition": actual_transition,
        "actual_status": str(review.status),
        "actual_recommendation": str(review.approval_recommendation),
        "critical_categories": critical_categories,
        "product_validator_status": validator_status,
        "deterministic_checks": _p05_actual_check_matrix(
            review, derived_preflight
        ),
        "input_hash": canonical_hash(request.model_dump(mode="json")),
        "output_hash": canonical_hash(review.model_dump(mode="json")),
        "provider_requests": 0,
    }


def evaluate_p05_golden_negative() -> dict[str, Any]:
    """Evaluate the negative offline and return only reproducible metadata."""

    fixture = _p05_golden_fixture()
    expected = fixture["golden_negative"]
    request = build_p05_golden_negative_request()
    review = _p05_review_from_versioned_semantic_fixture(
        request,
        negative=True,
    )
    derived_preflight = build_blueprint_review_preflight(
        blueprint=request.blueprint,
        activity_spec=request.activity_spec,
        rubric_spec=request.rubric_spec,
        blueprint_policy=request.blueprint_policy,
    )
    validator_status = "PASS"
    try:
        validate_blueprint_review_preflight_checks(review, derived_preflight)
    except ContextValidationError:
        validator_status = "FAIL"
    preflight = request.deterministic_preflight.model_dump(mode="json")
    failed_preflight_fields = sorted(
        key
        for key, value in preflight.items()
        if isinstance(value, bool) and value is False
    )
    critical_categories = sorted(
        {
            str(check.category)
            for check in review.checks
            if check.critical and check.status == m.ReviewCheckStatus.FAIL
        }
    )
    expected_checks = expected["expected_deterministic_checks"]
    product_expected_checks = _p05_expected_check_matrix(derived_preflight)
    actual_checks = _p05_actual_check_matrix(review, derived_preflight)
    status = (
        "PASS"
        if request.deterministic_preflight == derived_preflight
        and validator_status == "PASS"
        and review.status == m.WorkflowStatus.READY
        and review.approval_recommendation.value
        == expected["expected_recommendation"]
        and not blueprint_review_is_approvable(review)
        and failed_preflight_fields
        == sorted(expected["expected_failed_preflight_fields"])
        and critical_categories
        == sorted(expected["expected_critical_categories"])
        and actual_checks == expected_checks == product_expected_checks
        else "FAIL"
    )
    return {
        "check_id": "P05_GOLDEN_NEGATIVE_OFFLINE",
        "status": status,
        "expected_recommendation": expected["expected_recommendation"],
        "actual_recommendation": str(review.approval_recommendation),
        "expected_critical_categories": sorted(
            expected["expected_critical_categories"]
        ),
        "critical_categories": critical_categories,
        "expected_deterministic_checks": expected_checks,
        "product_expected_deterministic_checks": product_expected_checks,
        "actual_deterministic_checks": actual_checks,
        "product_validator_status": validator_status,
        "expected_failed_preflight_fields": sorted(
            expected["expected_failed_preflight_fields"]
        ),
        "failed_preflight_fields": failed_preflight_fields,
        "input_hash": canonical_hash(request.model_dump(mode="json")),
        "output_hash": canonical_hash(review.model_dump(mode="json")),
        "provider_requests": 0,
    }


def _route_profile_delta_material(
    route_profile_id: str,
    *,
    max_call_cost_usd: float,
    reference_route_profile_id: str = OPENAI_ROUTE_PROFILE_ID,
) -> dict[str, Any]:
    reference_routes = build_openai_routes(
        max_call_cost_usd=max_call_cost_usd,
        route_profile_id=reference_route_profile_id,
    )
    selected_routes = build_openai_routes(
        max_call_cost_usd=max_call_cost_usd,
        route_profile_id=route_profile_id,
    )
    route_fields = (
        "provider",
        "model",
        "model_snapshot",
        "temperature",
        "retention_mode",
        "region",
        "max_cost_usd",
        "max_input_tokens",
        "max_output_tokens",
        "fallback_route_id",
    )
    return {
        "baseline_route_profile": reference_route_profile_id,
        "selected_route_profile": route_profile_id,
        "route_identity_changed_prompt_ids": sorted(
            prompt_id
            for prompt_id in reference_routes
            if reference_routes[prompt_id].route_id
            != selected_routes[prompt_id].route_id
        ),
        "reasoning_effort_changes": {
            prompt_id: {
                "from": reference_routes[prompt_id].reasoning_effort.value,
                "to": selected_routes[prompt_id].reasoning_effort.value,
            }
            for prompt_id in reference_routes
            if reference_routes[prompt_id].reasoning_effort
            != selected_routes[prompt_id].reasoning_effort
        },
        "other_route_field_changes": {
            field: sorted(
                prompt_id
                for prompt_id in reference_routes
                if getattr(reference_routes[prompt_id], field)
                != getattr(selected_routes[prompt_id], field)
            )
            for field in route_fields
            if any(
                getattr(reference_routes[prompt_id], field)
                != getattr(selected_routes[prompt_id], field)
                for prompt_id in reference_routes
            )
        },
        "prompt_registry_changes": [],
        "schema_changes": [],
        "validator_changes": [],
        "fixture_changes": [],
        "planner_changes": [],
        "assembler_changes": [],
    }


def rehearsal_boundary_material(
    route_profile_id: str = OPENAI_ROUTE_PROFILE_ID,
    *,
    max_call_cost_usd: float = 0.10,
) -> dict[str, Any]:
    from .semantic_harness import terra_ladder_harness_freeze_proof

    routes = build_openai_routes(
        max_call_cost_usd=max_call_cost_usd,
        route_profile_id=route_profile_id,
    )
    golden_fixture = _p05_golden_fixture()
    golden_positive = evaluate_p05_golden_positive()
    golden_negative = evaluate_p05_golden_negative()
    checkpoints = {
        scenario: build_rehearsal_checkpoints(scenario).hashes
        for scenario in (BASE_SCENARIO_ID, VARIANT_SCENARIO_ID)
    }
    prompt_material = {
        prompt_id: {
            "version": prompt_spec(prompt_id).prompt_version,
            "hash": prompt_spec(prompt_id).prompt_hash,
            "input_schema_hash": canonical_hash(
                model_by_name(
                    prompt_spec(prompt_id).input_schema_name
                ).model_json_schema(mode="validation")
            ),
            "output_schema_hash": canonical_hash(
                model_by_name(
                    prompt_spec(prompt_id).output_schema_name
                ).model_json_schema(mode="validation")
            ),
            "relationship_validator": (
                PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS[prompt_id]
            ),
            "application_validator": (
                PROMPT_APPLICATION_VALIDATOR_VERSIONS.get(prompt_id)
            ),
            "registry_reasoning_effort": prompt_spec(
                prompt_id
            ).reasoning_effort.value,
            "route_reasoning_effort": routes[prompt_id].reasoning_effort.value,
        }
        for prompt_id in (
            "P04_BLUEPRINT_BUILD_V1",
            "P05_BLUEPRINT_REVIEW_V1",
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P08_QUESTION_REVIEW_V1",
            "P09_GUIDE_BUILD_V1",
        )
    }
    material = {
        "rehearsal_version": REHEARSAL_VERSION,
        "prompt_pack_version": PROMPT_VERSION,
        "planner_version": PLANNER_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "checkpoints": checkpoints,
        "p05_golden": {
            "fixture_version": golden_fixture["schema_version"],
            "fixture_hash": canonical_hash(golden_fixture),
            "positive_review_status": golden_fixture["golden_positive"][
                "semantic_review"
            ]["status"],
            "positive_expected_transition": golden_positive[
                "expected_transition"
            ],
            "positive_input_hash": golden_positive["input_hash"],
            "positive_output_hash": golden_positive["output_hash"],
            "negative_input_hash": golden_negative["input_hash"],
            "negative_output_hash": golden_negative["output_hash"],
            "negative_expected_recommendation": golden_negative[
                "expected_recommendation"
            ],
            "negative_expected_critical_categories": golden_negative[
                "expected_critical_categories"
            ],
        },
        "prompts": prompt_material,
        "openai_route_boundary": {
            "route_profile": route_profile_id,
            "model_ids": sorted({route.model for route in routes.values()}),
            "xhigh_qualification_prompt_ids": sorted(
                OPENAI_XHIGH_PROMPT_IDS
            ),
            "max_qualification_prompt_ids": sorted(OPENAI_MAX_PROMPT_IDS),
            "terra_medium_qualification_prompt_ids": sorted(
                OPENAI_TERRA_MEDIUM_PROMPT_IDS
            ),
            "terra_high_qualification_prompt_ids": sorted(
                OPENAI_TERRA_HIGH_PROMPT_IDS
            ),
            "terra_xhigh_qualification_prompt_ids": sorted(
                OPENAI_TERRA_XHIGH_PROMPT_IDS
            ),
            "sol_medium_qualification_prompt_ids": sorted(
                OPENAI_SOL_MEDIUM_PROMPT_IDS
            ),
            "sol_high_qualification_prompt_ids": sorted(
                OPENAI_SOL_HIGH_PROMPT_IDS
            ),
            "sol_xhigh_qualification_prompt_ids": sorted(
                OPENAI_SOL_XHIGH_PROMPT_IDS
            ),
            "routes": {
                prompt_id: {
                    "route_id": route.route_id,
                    "model": route.model,
                    "model_snapshot": route.model_snapshot,
                    "reasoning_effort": route.reasoning_effort.value,
                    "max_input_tokens": route.max_input_tokens,
                    "max_output_tokens": route.max_output_tokens,
                    "max_cost_usd": route.max_cost_usd,
                    "fallback_route_id": route.fallback_route_id,
                    "reason_codes": route.reason_codes,
                }
                for prompt_id, route in routes.items()
            },
            "adapter": "OpenAIResponsesAdapter",
            "api": "Responses",
            "openai_sdk_version": OPENAI_SDK_VERSION,
            "gateway_retries": 0,
            "sdk_retries": 0,
            "semantic_retries": 0,
            "tools_enabled": False,
            "store": False,
        },
        "route_delta_from_luna_baseline": _route_profile_delta_material(
            route_profile_id,
            max_call_cost_usd=max_call_cost_usd,
        ),
        "p10_enabled": False,
        "semantic_instrument": _semantic_instrument_metadata(),
        "terra_ladder_harness_freeze": terra_ladder_harness_freeze_proof(),
    }
    if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID:
        material["route_delta_from_luna_xhigh"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=OPENAI_XHIGH_ROUTE_PROFILE_ID,
            )
        )
    elif route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID:
        material["route_delta_from_luna_max"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=OPENAI_MAX_ROUTE_PROFILE_ID,
            )
        )
        material["terra_medium_budget_derivation"] = (
            terra_medium_budget_derivation()
        )
    elif route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID:
        material["route_delta_from_terra_medium"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=(
                    OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
                ),
            )
        )
        material["terra_high_budget_derivation"] = (
            terra_high_budget_derivation()
        )
    elif route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID:
        material["route_delta_from_terra_high"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=(
                    OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
                ),
            )
        )
        material["terra_xhigh_budget_derivation"] = (
            terra_xhigh_budget_derivation()
        )
    elif route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID:
        material["route_delta_from_terra_xhigh"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=(
                    OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
                ),
            )
        )
        material["sol_medium_budget_derivation"] = (
            sol_medium_budget_derivation()
        )
    elif route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID:
        material["route_delta_from_sol_medium"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            )
        )
        material["sol_high_budget_derivation"] = sol_high_budget_derivation()
    elif route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID:
        material["route_delta_from_sol_high"] = (
            _route_profile_delta_material(
                route_profile_id,
                max_call_cost_usd=max_call_cost_usd,
                reference_route_profile_id=OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            )
        )
        material["sol_xhigh_budget_derivation"] = (
            sol_xhigh_budget_derivation()
        )
    if route_profile_id in {
        OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
        OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
        OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
    }:
        material["allowed_delta"] = [
            "SOL_ROUTE_PROFILES",
            "SOL_PROFILE_SELECTION",
            "SOL_PRICING_AND_BUDGET",
            "SOL_AUTHORIZATION_BOUNDARIES",
            "SOL_EXACTLY_ONCE_EXECUTION_PLUMBING",
            "SOL_MECHANICAL_TESTS_AND_DRY_RUNS",
            "SOL_LADDER_REPORTING",
        ]
        material["forbidden_delta"] = []
    return material


def _safe_failure(error: Exception, *, stage: str) -> dict[str, Any]:
    codes: list[str] = []
    issues: list[dict[str, str]] = []
    if isinstance(error, GatewayContextError):
        codes.extend(code.value for code in error.failure.codes)
    elif isinstance(error, GatewaySchemaViolation):
        codes.append(error.code)
        if error.primary_failure is not None:
            codes.append(error.primary_failure.code)
            issues.extend(
                {
                    "error_type": issue.error_type,
                    "path": issue.path,
                }
                for issue in error.primary_failure.issues
            )
            issues.extend(
                {
                    "error_type": issue.error_type,
                    "path": issue.path,
                }
                for issue in error.primary_failure.provider_schema_issues
            )
    elif isinstance(error, ContextValidationError):
        codes.append(error.code)
    elif isinstance(error, GatewayError):
        codes.append(error.code)
    else:
        codes.append(type(error).__name__.upper())
    failure: dict[str, Any] = {
        "stage": stage,
        "codes": list(dict.fromkeys(codes)),
        "issues": list(
            {
                (item["error_type"], item["path"]): item
                for item in issues
            }.values()
        ),
    }
    safe_metadata = getattr(error, "safe_metadata", None)
    if isinstance(safe_metadata, dict):
        failure["metadata"] = safe_metadata
    return failure


def blueprint_review_is_approvable(review: m.BlueprintReview) -> bool:
    """Mirror the product transition without overfitting to APPROVE."""

    return (
        review.status == m.WorkflowStatus.READY
        and not any(
            check.critical and check.status == m.ReviewCheckStatus.FAIL
            for check in review.checks
        )
        and review.approval_recommendation
        != m.BlueprintApprovalRecommendation.REJECT
    )


class _BlueprintReviewNotApprovable(ContextValidationError):
    """Content-free rehearsal failure with enum-only review observability."""

    def __init__(
        self,
        review: m.BlueprintReview,
        blueprint: m.AssessmentBlueprint,
    ) -> None:
        self.semantic_interpretation = SemanticInterpretation.INCORRECT
        self.contractual_adherence = ContractualAdherence.PASS
        super().__init__(
            "P05_NOT_APPROVABLE",
            "P05 output does not permit the canonical product transition",
        )
        templates = [
            template
            for dimension in blueprint.dimensions
            for variant in dimension.evidence_variants
            for template in variant.question_opportunities
        ]
        self.safe_metadata = {
            "review_status": str(review.status),
            "approval_recommendation": (
                str(review.approval_recommendation)
                if review.approval_recommendation is not None
                else "NONE"
            ),
            "critical_fail_count": sum(
                check.critical and check.status == m.ReviewCheckStatus.FAIL
                for check in review.checks
            ),
            "fail_categories": sorted(
                {
                    check.category
                    for check in review.checks
                    if check.status == m.ReviewCheckStatus.FAIL
                }
            ),
            "warn_categories": sorted(
                {
                    check.category
                    for check in review.checks
                    if check.status == m.ReviewCheckStatus.WARN
                }
            ),
            "blueprint_dimension_count": len(blueprint.dimensions),
            "blueprint_variant_count": sum(
                len(dimension.evidence_variants)
                for dimension in blueprint.dimensions
            ),
            "blueprint_template_count": len(templates),
            "blueprint_operation_counts": {
                str(operation): sum(
                    template.cognitive_operation == operation
                    for template in templates
                )
                for operation in sorted(
                    {template.cognitive_operation for template in templates},
                    key=str,
                )
            },
            "blueprint_difficulty_counts": {
                str(difficulty): sum(
                    template.difficulty == difficulty
                    for template in templates
                )
                for difficulty in sorted(
                    {template.difficulty for template in templates},
                    key=str,
                )
            },
        }


class _AssessmentPlanNotReady(ContextValidationError):
    """Content-free planner failure with threshold and shape observability."""

    def __init__(
        self,
        plan: m.AssessmentPlan,
        mapping: m.EvidenceMapPatch,
        policy: m.AssessmentPlanningPolicy,
    ) -> None:
        super().__init__(
            "ASSESSMENT_PLAN_INFEASIBLE",
            "planner did not produce a complete plan",
        )
        evidence_fits = [
            opportunity.evidence_fit for opportunity in mapping.opportunities
        ]
        qualities = [
            opportunity.opportunity_quality
            for opportunity in mapping.opportunities
        ]
        self.safe_metadata = {
            "plan_status": str(plan.status),
            "mapping_status": str(mapping.status),
            "question_count": plan.question_count,
            "opportunity_count": len(mapping.opportunities),
            "minimum_evidence_fit": policy.minimum_evidence_fit,
            "eligible_evidence_fit_count": sum(
                value >= policy.minimum_evidence_fit
                for value in evidence_fits
            ),
            "minimum_observed_evidence_fit": (
                min(evidence_fits) if evidence_fits else None
            ),
            "maximum_observed_evidence_fit": (
                max(evidence_fits) if evidence_fits else None
            ),
            "minimum_observed_opportunity_quality": (
                min(qualities) if qualities else None
            ),
            "maximum_observed_opportunity_quality": (
                max(qualities) if qualities else None
            ),
            "diagnostic_codes": sorted(
                {diagnostic.code for diagnostic in plan.diagnostics}
            ),
        }


class _QuestionReviewNotAccepted(ContextValidationError):
    """Content-free P08 decision failure with reproducible thresholds."""

    def __init__(
        self,
        review_result: m.QuestionReviewResult,
        validation_policy: m.QuestionValidationPolicy,
    ) -> None:
        self.safe_metadata = p08_decision_diagnostics(
            review_result, validation_policy
        )
        decision_code = self.safe_metadata["diagnostic_codes"][0]
        super().__init__(
            decision_code,
            "P08 output does not permit the positive product transition",
        )


class _SemanticCheckpointMismatch(ContextValidationError):
    """Content-free mismatch against a versioned semantic oracle."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        semantic_interpretation: SemanticInterpretation,
        contractual_adherence: ContractualAdherence,
        safe_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message)
        self.semantic_interpretation = semantic_interpretation
        self.contractual_adherence = contractual_adherence
        self.safe_metadata = safe_metadata or {}


def _semantic_checkpoint_provenance() -> tuple[
    Any,
    dict[str, dict[str, Any]],
]:
    """Load reviewed checkpoints lazily to avoid a module import cycle."""

    from .semantic_harness import (
        build_checkpoint_provenance,
        build_semantic_checkpoints,
        semantic_checkpoint_requests,
        validate_checkpoint_provenance,
    )

    checkpoints = build_semantic_checkpoints()
    provenance_rows = build_checkpoint_provenance(checkpoints)
    validate_checkpoint_provenance(provenance_rows)
    provenance = {
        row["checkpoint_id"]: row
        for row in provenance_rows
        if row["checkpoint_class"]
        != CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY.value
    }
    return checkpoints, {
        checkpoint_id: {
            "prompt_id": prompt_id,
            "request": request,
            "provenance": provenance[checkpoint_id],
        }
        for checkpoint_id, prompt_id, request in semantic_checkpoint_requests(
            checkpoints
        )
    }


def _semantic_checkpoint_expected(
    checkpoints: Any,
    checkpoint_id: str,
) -> BaseModel:
    expected = {
        "P04_CANONICAL_POSITIVE": checkpoints.blueprint,
        "P05_CANONICAL_POSITIVE": checkpoints.p05_review,
        "P05_PLAN_FEASIBILITY_NEGATIVE": checkpoints.p05_negative_review,
        "P06_CANONICAL_POSITIVE": checkpoints.mapping,
        "P07_CANONICAL_POSITIVE": checkpoints.p07_positive_result,
        "P07_INSUFFICIENT_NEGATIVE": checkpoints.p07_negative_result,
        "P08_CANONICAL_POSITIVE": checkpoints.p08_positive_result,
        "P08_UNANSWERABLE_NEGATIVE": checkpoints.p08_negative_result,
        "P09_CANONICAL_POSITIVE": checkpoints.p09_guide,
    }
    return cast(BaseModel, expected[checkpoint_id])


_REQUIRED_CACHE_CONCEPTS = frozenset(
    {"source_change", "invalidation", "stale_risk", "recalculation"}
)
_CACHE_CONCEPT_PATTERNS: dict[str, tuple[str, ...]] = {
    "source_change": (
        r"\b(?:fuente|origen|insumo|source)\b.{0,80}\b(?:cambia|cambio|cambiar|modifica|actualiza|changes?|changed|updates?|updated)\b",
        r"\b(?:cambia|cambio|cambiar|modifica|actualiza|changes?|changed|updates?|updated)\b.{0,80}\b(?:fuente|origen|insumo|source)\b",
    ),
    "invalidation": (
        r"\b(?:invalida|invalidar|invalidacion|descarta|descartar|retira|retirar)\w*\b",
        r"\b(?:elimina|eliminar)\w*\b.{0,40}\b(?:entrada|cache)\b",
    ),
    "stale_risk": (
        r"\b(?:obsolet|desactualiz|stale)\w*\b",
        r"\b(?:resultado|valor|version|entrada)\b.{0,50}\b(?:previa|previo|anterior|antigua|antiguo)\b",
    ),
    "recalculation": (
        r"\b(?:recalcul|recomput|vuelve a calcular)\w*\b",
        r"\b(?:nueva|siguiente|posterior)\b.{0,35}\b(?:consulta|query)\b",
        r"\b(?:consulta|query)\b.{0,35}\b(?:nueva|siguiente|posterior|repite)\b",
    ),
}
_JUSTIFICATION_PATTERNS = (
    r"\bjustific\w*\b",
    r"\bexplic\w*\b",
    r"\bfundament\w*\b",
    r"\brelacion\w*\b",
    r"\bpor que\b",
    r"\bwhy\b",
    r"\bjustify\w*\b",
    r"\bexplain\w*\b",
)
_EXTERNAL_REQUIREMENT_PATTERNS = (
    r"\b(?:mutex|semaforo|lock|thread|hilo|concurr|race condition)\w*\b",
    r"\b(?:implementa|implementar|programa|programar)\w*\b",
    r"\b(?:escribe|propone|disena)\w*\b.{0,35}\b(?:codigo|algoritmo)\w*\b",
    r"\b(?:framework|lenguaje de programacion)\w*\b",
    r"\b(?:detector|latencia|rendimiento|complejidad)\w*\b",
    r"\b(?:consulta|busca|investiga)\w*\b.{0,45}\b(?:internet|extern|documentacion)\w*\b",
    r"\bpor que\s+(?:cambia|cambio)\s+(?:la\s+)?fuente\b",
    r"\bcausa\s+del\s+cambio\s+de\s+(?:la\s+)?fuente\b",
)
_ANSWER_LEAKAGE_PATTERNS = (
    r"\bla respuesta correcta es\b",
    r"\bdebes responder\b",
    r"\bnivel\s+[0-3]\s+si\b",
    r"\b(?:puntaje|rubrica|se calificara)\b",
)


def _semantic_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = _semantic_text(text)
    return any(re.search(pattern, normalized) for pattern in patterns)


def _cache_concepts(text: str) -> set[str]:
    normalized = _semantic_text(text)
    return {
        concept
        for concept, patterns in _CACHE_CONCEPT_PATTERNS.items()
        if any(re.search(pattern, normalized) for pattern in patterns)
    }


def _guide_semantic_text(guide: m.GuideDraft) -> str:
    return " ".join(
        [
            guide.purpose,
            *(item.description for item in guide.observable_elements),
            *guide.acceptable_alternatives,
            *guide.misconceptions,
            *(item.descriptor for item in guide.levels),
        ]
    )


def _semantic_mismatch(
    code: str,
    message: str,
    *,
    interpretation: SemanticInterpretation = SemanticInterpretation.INCORRECT,
    metadata: dict[str, Any] | None = None,
) -> None:
    raise _SemanticCheckpointMismatch(
        code,
        message,
        semantic_interpretation=interpretation,
        contractual_adherence=ContractualAdherence.PASS,
        safe_metadata=metadata,
    )


def _validate_p06_positive_invariants(
    *,
    request: m.EvidenceMapRequest,
    mapping: m.EvidenceMapPatch,
) -> None:
    """Qualify any semantically supported, planner-eligible catalog path."""

    validate_evidence_map(
        mapping,
        blueprint=request.blueprint,
        bundle=request.evidence_bundle,
        planning_policy=request.planning_policy,
    )
    if mapping.status != m.WorkflowStatus.READY:
        _semantic_mismatch(
            "P06_POSITIVE_NOT_READY",
            "P06 did not produce the reviewed positive transition",
        )
    bundle = request.evidence_bundle
    if bundle.context_mode != m.ContextMode.CLOSED or bundle.course_passages:
        _semantic_mismatch(
            "P06_POSITIVE_CONTEXT_WIDENED",
            "P06 canonical positive must remain closed without course sources",
        )
    evidence_by_id = {item.evidence_id: item for item in bundle.evidence_units}
    allowed_ids = set(bundle.allowed_evidence_ids)
    templates = {
        (
            dimension.dimension_id,
            variant.variant_id,
            item.opportunity_template_id,
        ): item
        for dimension in request.blueprint.dimensions
        for variant in dimension.evidence_variants
        for item in variant.question_opportunities
    }
    supported_opportunity_ids: set[str] = set()
    semantic_evidence_audit: list[dict[str, Any]] = []
    for opportunity in mapping.opportunities:
        template = templates[
            (
                opportunity.dimension_id,
                opportunity.variant_id,
                opportunity.opportunity_template_id,
            )
        ]
        target_ids = set(opportunity.evidence_ids)
        if not target_ids or not target_ids.issubset(allowed_ids):
            continue
        evidence_text = " ".join(
            evidence_by_id[evidence_id].content_text or ""
            for evidence_id in sorted(target_ids)
        )
        evidence_concepts = _cache_concepts(evidence_text)
        required_concepts = _cache_concepts(
            f"{template.focus} {template.observable}"
        )
        semantic_evidence_audit.append(
            {
                "opportunity_template_id": template.opportunity_template_id,
                "required_concepts": sorted(required_concepts),
                "detected_concepts": sorted(evidence_concepts),
            }
        )
        if not required_concepts or not required_concepts.issubset(
            evidence_concepts
        ):
            continue
        if opportunity.evidence_fit < request.planning_policy.minimum_evidence_fit:
            continue
        if opportunity.opportunity_quality < max(
            request.planning_policy.minimum_opportunity_quality,
            template.minimum_quality,
        ):
            continue
        supported_opportunity_ids.add(opportunity.opportunity_id)
    if not supported_opportunity_ids:
        _semantic_mismatch(
            "P06_POSITIVE_NO_SEMANTICALLY_SUPPORTED_OPPORTUNITY",
            "P06 produced no catalog opportunity supported by its own focus and observable",
            metadata={"opportunity_audit": semantic_evidence_audit},
        )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=request.blueprint,
        policy=request.planning_policy,
    )
    validate_assessment_plan(plan, mapping=mapping)
    planned_ids = set(
        plan.selected_opportunity_ids + plan.reserve_opportunity_ids
    )
    if (
        plan.status != m.WorkflowStatus.READY
        or not supported_opportunity_ids.intersection(planned_ids)
    ):
        _semantic_mismatch(
            "P06_POSITIVE_NO_ELIGIBLE_SEMANTIC_OPPORTUNITY",
            "The product planner cannot select any semantically supported opportunity",
        )


def _validate_p07_positive_invariants(
    *,
    request: m.QuestionBuildRequest,
    generation: m.QuestionGenerationResult,
) -> None:
    """Qualify generative P07 alternatives without enforcing one wording."""

    validate_generation_result(
        generation,
        opportunity=request.opportunity,
        bundle=request.evidence_bundle,
    )
    candidate = generation.candidate
    if generation.status != m.WorkflowStatus.READY or candidate is None:
        _semantic_mismatch(
            "P07_POSITIVE_NOT_READY",
            "P07 abstained from the reviewed positive",
        )
    if (
        generation.context_mode != m.ContextMode.CLOSED
        or request.evidence_bundle.context_mode != m.ContextMode.CLOSED
        or candidate.course_source_ids
        or candidate.citations
    ):
        _semantic_mismatch(
            "P07_POSITIVE_CONTEXT_WIDENED",
            "P07 canonical positive must remain closed without external sources",
        )
    opportunity = request.opportunity
    expected_path = (
        "oppt_justify_cache_invalidation",
        "dimension_cache_invalidation",
        "variant_source_change_trace",
        m.CognitiveOperation.JUSTIFY_DECISION,
    )
    actual_path = (
        candidate.opportunity_template_id,
        candidate.dimension_id,
        candidate.variant_id,
        candidate.cognitive_operation,
    )
    if actual_path != expected_path:
        _semantic_mismatch(
            "P07_POSITIVE_PATH_MISMATCH",
            "P07 changed the reviewed operation, dimension, variant, or template",
        )
    if (
        candidate.response_format not in opportunity.allowed_response_formats
        or candidate.difficulty != opportunity.difficulty
        or candidate.estimated_minutes != opportunity.target_minutes
    ):
        _semantic_mismatch(
            "P07_POSITIVE_FEASIBILITY_MISMATCH",
            "P07 changed the reviewed format, difficulty, or time boundary",
        )
    allowed_ids = set(request.evidence_bundle.allowed_evidence_ids)
    anchor_ids = {item.evidence_id for item in candidate.anchor.fragments}
    if (
        not anchor_ids
        or not anchor_ids.issubset(allowed_ids)
        or not anchor_ids.issubset(set(candidate.evidence_ids))
        or len(candidate.anchor.fragments)
        > request.generation_policy.max_anchor_fragments
    ):
        _semantic_mismatch(
            "P07_POSITIVE_ANCHOR_ALLOWLIST_MISMATCH",
            "P07 anchor is not limited to the authorized evidence",
        )
    anchor_text = " ".join(
        fragment.display_text or "" for fragment in candidate.anchor.fragments
    )
    anchor_concepts = _cache_concepts(anchor_text)
    if not _REQUIRED_CACHE_CONCEPTS.issubset(anchor_concepts):
        _semantic_mismatch(
            "P07_POSITIVE_ANCHOR_INSUFFICIENT",
            "P07 anchor omits material required by the reviewed operation",
            metadata={"detected_anchor_concepts": sorted(anchor_concepts)},
        )
    question_text = candidate.question_text
    guide_text = _guide_semantic_text(candidate.preliminary_guide)
    if _matches_any(question_text, _EXTERNAL_REQUIREMENT_PATTERNS) or _matches_any(
        guide_text, _EXTERNAL_REQUIREMENT_PATTERNS
    ):
        _semantic_mismatch(
            "P07_POSITIVE_REQUIRES_EXTERNAL_KNOWLEDGE",
            "P07 requires implementation, concurrency, or other unauthorized knowledge",
        )
    if _matches_any(question_text, _ANSWER_LEAKAGE_PATTERNS):
        _semantic_mismatch(
            "P07_POSITIVE_ANSWER_LEAKAGE",
            "P07 question exposes a prohibited answer or scoring cue",
        )
    guide_concepts = _cache_concepts(guide_text)
    if not _REQUIRED_CACHE_CONCEPTS.issubset(guide_concepts):
        _semantic_mismatch(
            "P07_POSITIVE_GUIDE_UNSUPPORTED",
            "P07 preliminary guide does not remain observable from the same evidence",
            metadata={"detected_guide_concepts": sorted(guide_concepts)},
        )
    question_concepts = _cache_concepts(question_text)
    if (
        not _matches_any(question_text, _JUSTIFICATION_PATTERNS)
        or len(question_concepts) < 2
    ):
        _semantic_mismatch(
            "P07_POSITIVE_OBJECTIVE_INVARIANTS_INSUFFICIENT",
            "P07 wording is structurally valid but too underspecified for a deterministic semantic judgment",
            interpretation=SemanticInterpretation.INDETERMINATE,
            metadata={"detected_question_concepts": sorted(question_concepts)},
        )


def _semantic_checkpoint_verdict(
    *,
    checkpoint_id: str,
    request: BaseModel,
    output: BaseModel,
    expected: BaseModel,
) -> tuple[SemanticInterpretation, ContractualAdherence]:
    """Apply the frozen product validators and the reviewed expected decision."""

    if checkpoint_id == "P04_CANONICAL_POSITIVE":
        actual = cast(m.AssessmentBlueprint, output)
        target = cast(m.AssessmentBlueprint, expected)
        if actual.status != m.WorkflowStatus.READY:
            raise _SemanticCheckpointMismatch(
                "P04_POSITIVE_NOT_READY",
                "P04 did not produce the reviewed positive transition",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
            )
        if (
            actual.dimensions[0].grading_weight
            != target.dimensions[0].grading_weight
        ):
            raise _SemanticCheckpointMismatch(
                "P04_SOURCE_FIDELITY_MISMATCH",
                "P04 did not preserve the reviewed grading weight",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
            )
    elif checkpoint_id.startswith("P05_"):
        actual = cast(m.BlueprintReview, output)
        review_request = cast(m.BlueprintReviewRequest, request)
        expected_categories = {
            "CONSTRUCT",
            "SOURCE_FIDELITY",
            "COVERAGE",
            "COMPARABILITY",
            "COGNITIVE_DEMAND",
            "TIME",
            "FORMAT_FEASIBILITY",
            "OPPORTUNITY_CATALOG",
            "PLAN_FEASIBILITY",
            "ACCESSIBILITY",
        }
        actual_categories = {str(check.category) for check in actual.checks}
        if actual_categories != expected_categories:
            raise _SemanticCheckpointMismatch(
                "P05_SEMANTIC_CATEGORY_SET_MISMATCH",
                "P05 did not review the ten canonical categories",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
                safe_metadata={
                    "missing_categories": sorted(
                        expected_categories - actual_categories
                    ),
                    "unexpected_categories": sorted(
                        actual_categories - expected_categories
                    ),
                },
            )
        expected_reject = checkpoint_id.endswith("NEGATIVE")
        if expected_reject:
            critical = {
                str(check.category)
                for check in actual.checks
                if check.critical and check.status == m.ReviewCheckStatus.FAIL
            }
            if actual.approval_recommendation != (
                m.BlueprintApprovalRecommendation.REJECT
            ):
                raise _SemanticCheckpointMismatch(
                    "P05_NEGATIVE_NOT_REJECTED",
                    "P05 did not reject the reviewed PLAN_FEASIBILITY negative",
                    semantic_interpretation=SemanticInterpretation.INCORRECT,
                    contractual_adherence=ContractualAdherence.PASS,
                    safe_metadata={"critical_categories": sorted(critical)},
                )
            if critical != {"PLAN_FEASIBILITY"}:
                raise _SemanticCheckpointMismatch(
                    "P05_NEGATIVE_CRITICAL_CATEGORY_MISMATCH",
                    "P05 rejected the negative for a critical category set that differs from the reviewed oracle",
                    semantic_interpretation=SemanticInterpretation.INCORRECT,
                    contractual_adherence=ContractualAdherence.FAIL,
                    safe_metadata={"critical_categories": sorted(critical)},
                )
            validate_blueprint_review_preflight_checks(
                actual,
                review_request.deterministic_preflight,
            )
        else:
            validate_blueprint_review_preflight_checks(
                actual,
                review_request.deterministic_preflight,
            )
            semantic_failures = {
                str(check.category)
                for check in actual.checks
                if check.status == m.ReviewCheckStatus.FAIL
            }
            if semantic_failures:
                raise _SemanticCheckpointMismatch(
                    "P05_POSITIVE_SEMANTIC_FAILURE",
                    "P05 failed a reviewed category on the canonical positive",
                    semantic_interpretation=SemanticInterpretation.INCORRECT,
                    contractual_adherence=ContractualAdherence.PASS,
                    safe_metadata={
                        "failed_categories": sorted(semantic_failures)
                    },
                )
            if not blueprint_review_is_approvable(actual):
                raise _BlueprintReviewNotApprovable(
                    actual,
                    review_request.blueprint,
                )
    elif checkpoint_id == "P06_CANONICAL_POSITIVE":
        mapping = cast(m.EvidenceMapPatch, output)
        map_request = cast(m.EvidenceMapRequest, request)
        _validate_p06_positive_invariants(
            request=map_request,
            mapping=mapping,
        )
    elif checkpoint_id.startswith("P07_"):
        generation = cast(m.QuestionGenerationResult, output)
        generation_request = cast(m.QuestionBuildRequest, request)
        try:
            validate_generation_result(
                generation,
                opportunity=generation_request.opportunity,
                bundle=generation_request.evidence_bundle,
            )
        except ContextValidationError as exc:
            if (
                checkpoint_id == "P07_INSUFFICIENT_NEGATIVE"
                and generation.status == "REPLACEMENT_REQUIRED"
                and generation.candidate is None
            ):
                raise _SemanticCheckpointMismatch(
                    exc.code,
                    "P07 made a defensible abstention but violated its contract",
                    semantic_interpretation=SemanticInterpretation.DEFENDIBLE,
                    contractual_adherence=ContractualAdherence.FAIL,
                ) from exc
            raise
        if checkpoint_id == "P07_INSUFFICIENT_NEGATIVE":
            if (
                generation.status != "REPLACEMENT_REQUIRED"
                or generation.candidate is not None
            ):
                raise _SemanticCheckpointMismatch(
                    "P07_NEGATIVE_NOT_ABSTAINED",
                    "P07 generated a candidate from insufficient evidence",
                    semantic_interpretation=SemanticInterpretation.INCORRECT,
                    contractual_adherence=ContractualAdherence.PASS,
                )
        elif generation.status != "READY" or generation.candidate is None:
            raise _SemanticCheckpointMismatch(
                "P07_POSITIVE_NOT_READY",
                "P07 abstained from the reviewed positive",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
            )
        else:
            _validate_p07_positive_invariants(
                request=generation_request,
                generation=generation,
            )
    elif checkpoint_id.startswith("P08_"):
        review = cast(m.QuestionReviewResult, output)
        review_request = cast(m.QuestionReviewRequest, request)
        validate_review_result(
            review,
            generation_result=review_request.generation_result,
            validation_policy=review_request.validation_policy,
        )
        expected_decision = (
            m.ReviewDecision.REJECT
            if checkpoint_id == "P08_UNANSWERABLE_NEGATIVE"
            else m.ReviewDecision.ACCEPT
        )
        if review.review is None or review.review.decision != expected_decision:
            raise _SemanticCheckpointMismatch(
                (
                    "P08_NEGATIVE_NOT_REJECTED"
                    if expected_decision == m.ReviewDecision.REJECT
                    else "P08_POSITIVE_NOT_ACCEPTED"
                ),
                "P08 did not make the versioned reviewed decision",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
                safe_metadata=p08_decision_diagnostics(
                    review,
                    review_request.validation_policy,
                ),
            )
    elif checkpoint_id == "P09_CANONICAL_POSITIVE":
        guide = cast(m.EvaluationGuide, output)
        guide_request = cast(m.GuideBuildRequest, request)
        validate_evaluation_guide(
            guide,
            assessment=guide_request.assessment,
            bundle=guide_request.evidence_bundle,
        )
        if guide.status != m.WorkflowStatus.READY:
            raise _SemanticCheckpointMismatch(
                "P09_POSITIVE_NOT_READY",
                "P09 did not produce the reviewed positive guide",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
            )
    else:  # pragma: no cover - fixed reviewed matrix
        raise ValueError(f"unknown semantic checkpoint: {checkpoint_id}")
    return SemanticInterpretation.CORRECT, ContractualAdherence.PASS


def _mark_structural_orchestration_rows(
    stages: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Make the non-semantic role of legacy chain rows explicit."""

    for stage in stages:
        stage.update(
            {
                "checkpoint_class": (
                    CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY.value
                ),
                "oracle_validity": OracleValidity.NOT_APPLICABLE.value,
                "semantic_interpretation": (
                    SemanticInterpretation.NOT_EVALUATED.value
                ),
                "contractual_adherence": (
                    ContractualAdherence.NOT_EVALUATED.value
                ),
                "semantic_quality_conclusion_allowed": False,
            }
        )
    return tuple(stages)


class ProductRehearsal:
    """Execute independent sweeps and integrated chains through one gateway."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        max_call_cost_usd: float,
        max_total_cost_usd: float | None = None,
        ledger_records: list[m.ModelCallLedger] | None = None,
    ) -> None:
        self.gateway = gateway
        self.max_call_cost_usd = max_call_cost_usd
        self.max_total_cost_usd = max_total_cost_usd
        self.results: list[GatewayCallResult] = []
        self.ledger_records = ledger_records
        self.provider_call_contexts: list[dict[str, Any]] = []

    def _ledgers(self) -> list[m.ModelCallLedger]:
        if self.ledger_records is not None:
            return self.ledger_records
        return [
            ledger
            for result in self.results
            for ledger in result.ledgers
        ]

    @staticmethod
    def _budget_charge(ledger: m.ModelCallLedger) -> float:
        return max(
            ledger.estimated_cost_usd,
            ledger.actual_cost_usd or 0.0,
        )

    async def _invoke(
        self,
        prompt_id: str,
        request: BaseModel,
        *,
        run_id: str,
        run_kind: str,
        checkpoint_id: str | None = None,
    ) -> BaseModel:
        spent = sum(self._budget_charge(ledger) for ledger in self._ledgers())
        remaining = (
            self.max_call_cost_usd
            if self.max_total_cost_usd is None
            else min(
                self.max_call_cost_usd,
                max(0.0, self.max_total_cost_usd - spent),
            )
        )
        ledger_count_before = len(self._ledgers())
        try:
            result = await self.gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
                budget=CallBudget(max_cost_usd=remaining),
            )
        finally:
            new_ledgers = self._ledgers()[ledger_count_before:]
            self.provider_call_contexts.extend(
                {
                    "run_id": run_id,
                    "run_kind": run_kind,
                    "checkpoint_id": checkpoint_id
                    or f"{run_id}:{prompt_id}",
                    "prompt_id": prompt_id,
                }
                for _ledger in new_ledgers
            )
        self.results.append(result)
        return result.output

    def _stage_row(
        self,
        prompt_id: str,
        request: BaseModel,
        output: BaseModel,
    ) -> dict[str, Any]:
        result = self.results[-1]
        ledger = result.ledgers[-1]
        reasoning_tokens = next(
            (
                int(code.removeprefix("REASONING_TOKENS_"))
                for code in reversed(ledger.route.reason_codes)
                if code.startswith("REASONING_TOKENS_")
            ),
            0,
        )
        cache_write_input_tokens = next(
            (
                int(code.removeprefix("CACHE_WRITE_INPUT_TOKENS_"))
                for code in reversed(ledger.route.reason_codes)
                if code.startswith("CACHE_WRITE_INPUT_TOKENS_")
            ),
            0,
        )
        row = {
            "prompt_id": prompt_id,
            "prompt_version": prompt_spec(prompt_id).prompt_version,
            "input_hash": canonical_hash(request.model_dump(mode="json")),
            "output_hash": canonical_hash(output.model_dump(mode="json")),
            "status": "PASS",
            "model": ledger.route.model,
            "reasoning_effort": ledger.route.reasoning_effort.value,
            "fallback_route_id": ledger.route.fallback_route_id,
            "attempts": len(result.ledgers),
            "provider_attempts": len(result.ledgers),
            "gateway_retries": 0,
            "sdk_retries": 0,
            "semantic_retries": 0,
            "repaired": result.repaired,
            "input_tokens": ledger.input_tokens,
            "cached_input_tokens": ledger.cached_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
            "output_tokens": ledger.output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "actual_cost_usd": round(
                sum(item.actual_cost_usd for item in result.ledgers), 10
            ),
            "conservative_budget_charge_usd": round(
                sum(self._budget_charge(item) for item in result.ledgers),
                10,
            ),
        }
        if (
            prompt_id == "P08_QUESTION_REVIEW_V1"
            and isinstance(output, m.QuestionReviewResult)
            and isinstance(request, m.QuestionReviewRequest)
        ):
            row["decision_diagnostics"] = p08_decision_diagnostics(
                output, request.validation_policy
            )
        return row

    async def run_sweep(
        self,
        *,
        run_id: str,
        scenario_id: str = BASE_SCENARIO_ID,
    ) -> RehearsalObservation:
        if scenario_id != BASE_SCENARIO_ID:
            raise ValueError("the semantic sweep has one reviewed canonical case")
        checkpoints, semantic_matrix = _semantic_checkpoint_provenance()
        stages: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        assessments: list[CheckpointAssessment] = []

        async def observe(checkpoint_id: str) -> None:
            material = semantic_matrix[checkpoint_id]
            prompt_id = str(material["prompt_id"])
            request = cast(BaseModel, material["request"])
            provenance = cast(dict[str, Any], material["provenance"])
            checkpoint_class = CheckpointClass(provenance["checkpoint_class"])
            try:
                output = cast(
                    BaseModel,
                    await self._invoke(
                        prompt_id,
                        request,
                        run_id=run_id,
                        run_kind="SEMANTIC_QUALIFICATION_SWEEP",
                        checkpoint_id=checkpoint_id,
                    ),
                )
                semantic_interpretation, contractual_adherence = (
                    _semantic_checkpoint_verdict(
                        checkpoint_id=checkpoint_id,
                        request=request,
                        output=output,
                        expected=_semantic_checkpoint_expected(
                            checkpoints,
                            checkpoint_id,
                        ),
                    )
                )
                assessment = classify_checkpoint(
                    checkpoint_id=checkpoint_id,
                    checkpoint_class=checkpoint_class,
                    oracle_validity=OracleValidity.VALID,
                    semantic_interpretation=semantic_interpretation,
                    contractual_adherence=contractual_adherence,
                    semantic_review_id=provenance["semantic_review_id"],
                    semantic_review_version=provenance["review_version"],
                    semantic_review_hash=provenance["review_hash"],
                )
                row = self._stage_row(prompt_id, request, output)
                row.update(
                    {
                        "checkpoint_id": checkpoint_id,
                        "checkpoint_class": checkpoint_class.value,
                        "semantic_review_id": provenance["semantic_review_id"],
                        "review_version": provenance["review_version"],
                        "review_hash": provenance["review_hash"],
                        "fixture_hash": provenance["fixture_hash"],
                        "golden_hash": provenance["golden_hash"],
                        "source_artifact_hashes": provenance[
                            "source_artifact_hashes"
                        ],
                        "expected_outcome": provenance["expected_outcome"],
                        "operational_outcome": (
                            assessment.operational_outcome.value
                        ),
                        "semantic_interpretation": (
                            assessment.semantic_interpretation.value
                        ),
                        "contractual_adherence": (
                            assessment.contractual_adherence.value
                        ),
                        "causal_attribution": (
                            assessment.causal_attribution.value
                        ),
                        "causal_confidence": assessment.causal_confidence.value,
                    }
                )
                stages.append(row)
                assessments.append(assessment)
            except Exception as exc:  # content-free aggregation boundary
                failure = _safe_failure(
                    exc,
                    stage=prompt_id.removesuffix("_V1"),
                )
                contract_failure = isinstance(
                    exc,
                    (
                        ContextValidationError,
                        GatewayContextError,
                        GatewaySchemaViolation,
                    ),
                )
                technical_failure = not contract_failure
                semantic_interpretation = getattr(
                    exc,
                    "semantic_interpretation",
                    (
                        SemanticInterpretation.NOT_EVALUATED
                        if technical_failure
                        else SemanticInterpretation.NOT_EVALUATED
                    ),
                )
                contractual_adherence = getattr(
                    exc,
                    "contractual_adherence",
                    (
                        ContractualAdherence.NOT_EVALUATED
                        if technical_failure
                        else ContractualAdherence.FAIL
                    ),
                )
                if (
                    checkpoint_id == "P07_INSUFFICIENT_NEGATIVE"
                    and {
                        "DIAGNOSTIC_INCOMPLETE",
                        "ABSTENTION_DIAGNOSTIC_MISSING",
                    }.intersection(failure["codes"])
                ):
                    semantic_interpretation = SemanticInterpretation.DEFENDIBLE
                    contractual_adherence = ContractualAdherence.FAIL
                if (
                    checkpoint_id == "P05_PLAN_FEASIBILITY_NEGATIVE"
                    and "P05_PREFLIGHT_CHECK_MISMATCH" in failure["codes"]
                ):
                    failure["codes"] = sorted(
                        {
                            *failure["codes"],
                            "P05_NEGATIVE_CRITICAL_CATEGORY_MISMATCH",
                        }
                    )
                    semantic_interpretation = SemanticInterpretation.INCORRECT
                    contractual_adherence = ContractualAdherence.FAIL
                assessment = classify_checkpoint(
                    checkpoint_id=checkpoint_id,
                    checkpoint_class=checkpoint_class,
                    oracle_validity=OracleValidity.VALID,
                    semantic_interpretation=semantic_interpretation,
                    contractual_adherence=contractual_adherence,
                    technical_failure=technical_failure,
                    semantic_review_id=provenance["semantic_review_id"],
                    semantic_review_version=provenance["review_version"],
                    semantic_review_hash=provenance["review_hash"],
                    reason_codes=tuple(failure["codes"]),
                )
                failure.update(
                    {
                        "checkpoint_id": checkpoint_id,
                        "checkpoint_class": checkpoint_class.value,
                        "semantic_review_id": provenance[
                            "semantic_review_id"
                        ],
                        "review_version": provenance["review_version"],
                        "review_hash": provenance["review_hash"],
                        "fixture_hash": provenance["fixture_hash"],
                        "golden_hash": provenance["golden_hash"],
                        "source_artifact_hashes": provenance[
                            "source_artifact_hashes"
                        ],
                        "expected_outcome": provenance["expected_outcome"],
                        "operational_outcome": (
                            assessment.operational_outcome.value
                        ),
                        "semantic_interpretation": (
                            assessment.semantic_interpretation.value
                        ),
                        "contractual_adherence": (
                            assessment.contractual_adherence.value
                        ),
                        "causal_attribution": (
                            assessment.causal_attribution.value
                        ),
                        "causal_confidence": assessment.causal_confidence.value,
                    }
                )
                failures.append(failure)
                assessments.append(assessment)

        for checkpoint_id in semantic_matrix:
            await observe(checkpoint_id)
        return RehearsalObservation(
            run_id=run_id,
            run_kind="SEMANTIC_QUALIFICATION_SWEEP",
            scenario_id=scenario_id,
            status="PASS" if not failures else "FAIL",
            stages=tuple(stages),
            failure=(
                {"aggregated_failures": failures} if failures else None
            ),
            output_hash=(canonical_hash(stages) if not failures else None),
            checkpoint_assessments=tuple(
                item.model_dump() for item in assessments
            ),
        )

    async def run_chain(
        self,
        *,
        run_id: str,
        scenario_id: str = BASE_SCENARIO_ID,
    ) -> RehearsalObservation:
        canonical_inputs: Any | None = None
        if scenario_id == CANONICAL_DOCUMENT_SCENARIO_ID:
            from .semantic_harness import build_canonical_document_chain_inputs

            canonical_inputs = build_canonical_document_chain_inputs()
            p04 = canonical_inputs.p04_request
            source_artifact_hashes = canonical_inputs.source_artifact_hashes
            submission_media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            checkpoints = build_rehearsal_checkpoints(scenario_id)
            p04 = checkpoints.p04_request
            source_artifact_hashes = {
                "assignment": "sha256:" + "a" * 64,
                "rubric": "sha256:" + "b" * 64,
                "submission": "sha256:" + "c" * 64,
            }
            submission_media_type = "text/markdown"
        stages: list[dict[str, Any]] = []
        current_stage = "P04"
        try:
            blueprint = cast(
                m.AssessmentBlueprint,
                await self._invoke(
                    "P04_BLUEPRINT_BUILD_V1",
                    p04,
                    run_id=run_id,
                    run_kind="INTEGRATED_CHAIN",
                ),
            )
            if blueprint.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "P04_NOT_READY", "P04 chain output is not READY"
                )
            p04_row = self._stage_row(
                "P04_BLUEPRINT_BUILD_V1", p04, blueprint
            )
            p04_row.update(
                {
                    "chain_output_role": "CURRENT_RUN_MODEL_OUTPUT",
                    "input_origin": (
                        "PRODUCT_DERIVED_DOCUMENT_BOUNDARY"
                        if canonical_inputs is not None
                        else "VERSIONED_SYNTHETIC_CHAIN_INPUT"
                    ),
                    "source_artifact_hashes": source_artifact_hashes,
                }
            )
            stages.append(p04_row)

            current_stage = "P05"
            p05 = m.BlueprintReviewRequest(
                activity_spec=p04.activity_spec,
                rubric_spec=p04.rubric_spec,
                blueprint_policy=p04.blueprint_policy,
                resolved_decisions=p04.resolved_decisions,
                blueprint=blueprint,
                deterministic_preflight=build_blueprint_review_preflight(
                    blueprint=blueprint,
                    activity_spec=p04.activity_spec,
                    rubric_spec=p04.rubric_spec,
                    blueprint_policy=p04.blueprint_policy,
                ),
            )
            blueprint_review = cast(
                m.BlueprintReview,
                await self._invoke(
                    "P05_BLUEPRINT_REVIEW_V1",
                    p05,
                    run_id=run_id,
                    run_kind="INTEGRATED_CHAIN",
                ),
            )
            if not blueprint_review_is_approvable(blueprint_review):
                raise _BlueprintReviewNotApprovable(
                    blueprint_review, blueprint
                )
            p05_row = self._stage_row(
                "P05_BLUEPRINT_REVIEW_V1", p05, blueprint_review
            )
            p05_row.update(
                {
                    "chain_output_role": "CURRENT_RUN_MODEL_OUTPUT",
                    "dataflow_input_from": "P04_CURRENT_RUN_OUTPUT",
                    "upstream_output_hash": p04_row["output_hash"],
                    "consumed_blueprint_hash": canonical_hash(
                        p05.blueprint.model_dump(mode="json")
                    ),
                }
            )
            stages.append(p05_row)
            approved_blueprint = blueprint.model_copy(
                update={"status": m.WorkflowStatus.APPROVED}
            )

            current_stage = "P06"
            if canonical_inputs is not None:
                from .semantic_harness import build_canonical_document_p06_request

                p06 = build_canonical_document_p06_request(
                    canonical_inputs,
                    approved_blueprint=approved_blueprint,
                )
            else:
                p06 = checkpoints.p06_request.model_copy(
                    update={
                        "blueprint": approved_blueprint,
                        "planning_policy": p04.blueprint_policy.planning_policy,
                    }
                )
            mapping = cast(
                m.EvidenceMapPatch,
                await self._invoke(
                    "P06_EVIDENCE_MAP_V1",
                    p06,
                    run_id=run_id,
                    run_kind="INTEGRATED_CHAIN",
                ),
            )
            validate_evidence_map(
                mapping,
                blueprint=approved_blueprint,
                bundle=p06.evidence_bundle,
                planning_policy=p06.planning_policy,
            )
            p06_row = self._stage_row(
                "P06_EVIDENCE_MAP_V1", p06, mapping
            )
            p06_row.update(
                {
                    "chain_output_role": "CURRENT_RUN_MODEL_OUTPUT",
                    "dataflow_input_from": (
                        "P04_CURRENT_RUN_OUTPUT_WITH_DETERMINISTIC_APPROVAL_TRANSITION"
                    ),
                    "source_p04_output_hash": p04_row["output_hash"],
                    "consumed_blueprint_hash": canonical_hash(
                        p06.blueprint.model_dump(mode="json")
                    ),
                    "intermediate_golden_injected": False,
                }
            )
            stages.append(p06_row)

            current_stage = "PLANNER"
            plan = build_assessment_plan(
                mapping=mapping,
                blueprint=approved_blueprint,
                policy=p06.planning_policy,
            )
            validate_assessment_plan(plan, mapping=mapping)
            if plan.status != m.WorkflowStatus.READY:
                raise _AssessmentPlanNotReady(
                    plan,
                    mapping,
                    p06.planning_policy,
                )
            stages.append(
                {
                    "stage": "PLANNER",
                    "version": PLANNER_VERSION,
                    "input_hash": canonical_hash(
                        {
                            "mapping": mapping.model_dump(mode="json"),
                            "blueprint": approved_blueprint.model_dump(
                                mode="json"
                            ),
                            "policy": p04.blueprint_policy.planning_policy.model_dump(
                                mode="json"
                            ),
                        }
                    ),
                    "output_hash": canonical_hash(
                        plan.model_dump(mode="json")
                    ),
                    "status": "PASS",
                    "dataflow_input_from": "P06_CURRENT_RUN_OUTPUT",
                    "consumed_mapping_hash": p06_row["output_hash"],
                    "intermediate_golden_injected": False,
                }
            )
            opportunity_by_id = {
                opportunity.opportunity_id: opportunity
                for opportunity in mapping.opportunities
            }
            selected: list[m.SelectedQuestion] = []
            for index, opportunity_id in enumerate(
                plan.selected_opportunity_ids
            ):
                opportunity = opportunity_by_id[opportunity_id]
                current_stage = "P07"
                p07 = m.QuestionBuildRequest(
                    target_candidate_id=stable_id(
                        "candidate",
                        run_id,
                        opportunity.opportunity_id,
                        index,
                    ),
                    plan=plan,
                    opportunity=opportunity,
                    evidence_bundle=p06.evidence_bundle,
                    generation_policy=m.QuestionGenerationPolicy(
                        policy_id=stable_id(
                            "generation-policy", scenario_id
                        )
                    ),
                    avoid=[],
                )
                generation = cast(
                    m.QuestionGenerationResult,
                    await self._invoke(
                        "P07_QUESTION_BUILD_V1",
                        p07,
                        run_id=run_id,
                        run_kind="INTEGRATED_CHAIN",
                    ),
                )
                validate_generation_result(
                    generation,
                    opportunity=opportunity,
                    bundle=p06.evidence_bundle,
                )
                if generation.candidate is None:
                    raise ContextValidationError(
                        "P07_NO_CANDIDATE",
                        "P07 chain output has no candidate",
                    )
                p07_row = self._stage_row(
                    "P07_QUESTION_BUILD_V1", p07, generation
                )
                p07_row.update(
                    {
                        "chain_output_role": "CURRENT_RUN_MODEL_OUTPUT",
                        "dataflow_input_from": (
                            "P06_CURRENT_RUN_OUTPUT_AND_PRODUCT_PLANNER"
                        ),
                        "consumed_plan_hash": canonical_hash(
                            p07.plan.model_dump(mode="json")
                        ),
                        "consumed_opportunity_hash": canonical_hash(
                            p07.opportunity.model_dump(mode="json")
                        ),
                        "intermediate_golden_injected": False,
                    }
                )
                stages.append(p07_row)

                current_stage = "P08"
                p08 = m.QuestionReviewRequest(
                    generation_result=generation,
                    opportunity=opportunity,
                    evidence_bundle=p06.evidence_bundle,
                    validation_policy=m.QuestionValidationPolicy(
                        policy_id=stable_id(
                            "validation-policy", scenario_id
                        )
                    ),
                )
                question_review = cast(
                    m.QuestionReviewResult,
                    await self._invoke(
                        "P08_QUESTION_REVIEW_V1",
                        p08,
                        run_id=run_id,
                        run_kind="INTEGRATED_CHAIN",
                    ),
                )
                validate_review_result(
                    question_review,
                    generation_result=generation,
                    validation_policy=p08.validation_policy,
                )
                if (
                    question_review.review is None
                    or question_review.review.decision
                    != m.ReviewDecision.ACCEPT
                ):
                    raise _QuestionReviewNotAccepted(
                        question_review,
                        p08.validation_policy,
                    )
                p08_row = self._stage_row(
                    "P08_QUESTION_REVIEW_V1", p08, question_review
                )
                p08_row.update(
                    {
                        "chain_output_role": "CURRENT_RUN_MODEL_OUTPUT",
                        "dataflow_input_from": "P07_CURRENT_RUN_OUTPUT",
                        "upstream_output_hash": p07_row["output_hash"],
                        "consumed_generation_hash": canonical_hash(
                            p08.generation_result.model_dump(mode="json")
                        ),
                        "intermediate_golden_injected": False,
                    }
                )
                stages.append(p08_row)
                selected.append(
                    selected_question_from_candidate(
                        generation.candidate,
                        opportunity,
                        submission_id=mapping.submission_id,
                    )
                )

            current_stage = "ASSEMBLY"
            prompt_versions = {
                row["prompt_id"]: row["prompt_version"]
                for row in stages
                if "prompt_id" in row
            }
            model_snapshots = {
                row["prompt_id"]: row["model"]
                for row in stages
                if "prompt_id" in row
            }
            assessment = assemble_assessment_snapshot(
                tenant_id=p06.evidence_bundle.tenant_id,
                activity_id=p04.activity_spec.activity_id,
                submission_id=p06.evidence_bundle.submission_id,
                subject_ref=stable_id("subject", scenario_id),
                created_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
                blueprint=approved_blueprint,
                plan=plan,
                mapping=mapping,
                questions=selected,
                assignment_prompt_hashes=[source_artifact_hashes["assignment"]],
                rubric_hashes=[source_artifact_hashes["rubric"]],
                submission_hashes=[source_artifact_hashes["submission"]],
                submission_media_type=submission_media_type,
                prompt_versions=prompt_versions,
                model_snapshots=model_snapshots,
                policy_hash=canonical_hash(
                    p04.blueprint_policy.model_dump(mode="json")
                ),
            )
            stages.append(
                {
                    "stage": "ASSEMBLY",
                    "version": ASSEMBLER_VERSION,
                    "input_hash": canonical_hash(
                        {
                            "plan": plan.model_dump(mode="json"),
                            "mapping": mapping.model_dump(mode="json"),
                            "questions": [
                                item.model_dump(mode="json")
                                for item in selected
                            ],
                        }
                    ),
                    "output_hash": canonical_hash(
                        assessment.model_dump(mode="json")
                    ),
                    "status": "PASS",
                    "dataflow_input_from": (
                        "P04_P06_PLANNER_P07_CURRENT_RUN_OUTPUTS"
                    ),
                    "intermediate_golden_injected": False,
                }
            )

            current_stage = "P09"
            p09 = m.GuideBuildRequest(
                guide_id=stable_id("guide", assessment.assessment_id),
                assessment=assessment,
                evidence_bundle=p06.evidence_bundle,
            )
            guide = cast(
                m.EvaluationGuide,
                await self._invoke(
                    "P09_GUIDE_BUILD_V1",
                    p09,
                    run_id=run_id,
                    run_kind="INTEGRATED_CHAIN",
                ),
            )
            validate_evaluation_guide(
                guide,
                assessment=assessment,
                bundle=p06.evidence_bundle,
            )
            if guide.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "P09_NOT_READY", "P09 chain output is not READY"
                )
            p09_row = self._stage_row("P09_GUIDE_BUILD_V1", p09, guide)
            p09_row.update(
                {
                    "chain_output_role": "CURRENT_RUN_MODEL_OUTPUT",
                    "dataflow_input_from": "ASSEMBLY_CURRENT_RUN_OUTPUT",
                    "consumed_assessment_hash": canonical_hash(
                        p09.assessment.model_dump(mode="json")
                    ),
                    "intermediate_golden_injected": False,
                }
            )
            stages.append(p09_row)
        except Exception as exc:
            structural_stages = _mark_structural_orchestration_rows(stages)
            failure = _safe_failure(exc, stage=current_stage)
            failure.update(
                {
                    "operational_outcome": "INCOMPLETE",
                    "causal_attribution": "CAUSE_INDETERMINATE",
                    "causal_confidence": "LOW",
                    "stage_local_semantic_attribution_allowed": False,
                }
            )
            return RehearsalObservation(
                run_id=run_id,
                run_kind="INTEGRATED_CHAIN",
                scenario_id=scenario_id,
                status="FAIL",
                stages=structural_stages,
                failure=failure,
                output_hash=None,
            )
        structural_stages = _mark_structural_orchestration_rows(stages)
        return RehearsalObservation(
            run_id=run_id,
            run_kind="INTEGRATED_CHAIN",
            scenario_id=scenario_id,
            status="PASS",
            stages=structural_stages,
            failure=None,
            output_hash=canonical_hash(structural_stages),
        )

    def controls(self) -> dict[str, Any]:
        ledgers = self._ledgers()
        return {
            "p10_calls": sum(
                ledger.prompt_id == "P10_ENRICHED_CONTEXT_V1"
                for ledger in ledgers
            ),
            "p11_calls": sum(
                ledger.prompt_id == "P11_SCHEMA_REPAIR_V1"
                for ledger in ledgers
            ),
            "fallback_calls": sum(
                ledger.route.fallback_route_id is not None
                for ledger in ledgers
            ),
            "semantic_retries": 0,
            "provider_attempts": len(ledgers),
            "actual_cost_usd": round(
                sum(ledger.actual_cost_usd or 0.0 for ledger in ledgers), 10
            ),
            "budget_charged_usd": round(
                sum(self._budget_charge(ledger) for ledger in ledgers), 10
            ),
            "unpriced_attempts": sum(
                ledger.actual_cost_usd is None for ledger in ledgers
            ),
            "models": sorted({ledger.route.model for ledger in ledgers}),
        }


def _provider_usage_controls(
    ledgers: list[m.ModelCallLedger],
) -> dict[str, Any]:
    def reason_code_total(prefix: str) -> int:
        return sum(
            next(
                (
                    int(code.removeprefix(prefix))
                    for code in reversed(ledger.route.reason_codes)
                    if code.startswith(prefix)
                ),
                0,
            )
            for ledger in ledgers
        )

    reasoning_efforts_by_prompt = {
        prompt_id: sorted(
            {
                ledger.route.reasoning_effort.value
                for ledger in ledgers
                if ledger.prompt_id == prompt_id
            }
        )
        for prompt_id in sorted({ledger.prompt_id for ledger in ledgers})
    }
    return {
        "input_tokens": sum(ledger.input_tokens for ledger in ledgers),
        "cached_input_tokens": sum(
            ledger.cached_input_tokens for ledger in ledgers
        ),
        "cache_write_input_tokens": reason_code_total(
            "CACHE_WRITE_INPUT_TOKENS_"
        ),
        "output_tokens": sum(ledger.output_tokens for ledger in ledgers),
        "reasoning_tokens": reason_code_total("REASONING_TOKENS_"),
        "reasoning_efforts_by_prompt": reasoning_efforts_by_prompt,
        "max_observed_actual_call_cost_usd": round(
            max(
                (ledger.actual_cost_usd or 0.0 for ledger in ledgers),
                default=0.0,
            ),
            10,
        ),
        "max_observed_budget_charge_usd": round(
            max(
                (
                    max(
                        ledger.estimated_cost_usd,
                        ledger.actual_cost_usd or 0.0,
                    )
                    for ledger in ledgers
                ),
                default=0.0,
            ),
            10,
        ),
    }


def _provider_call_receipts(
    ledgers: list[m.ModelCallLedger],
    contexts: list[dict[str, Any]],
    *,
    provider_transport: bool,
) -> list[dict[str, Any]]:
    """Serialize every billable attempt without retaining prompt content."""

    if len(ledgers) != len(contexts):
        raise AssertionError(
            "every provider ledger must have one execution context"
        )

    def reason_integer(ledger: m.ModelCallLedger, prefix: str) -> int:
        return next(
            (
                int(code.removeprefix(prefix))
                for code in reversed(ledger.route.reason_codes)
                if code.startswith(prefix)
            ),
            0,
        )

    def reason_hash(
        ledger: m.ModelCallLedger, prefix: str
    ) -> str | None:
        return next(
            (
                "sha256:" + code.removeprefix(prefix)
                for code in reversed(ledger.route.reason_codes)
                if code.startswith(prefix)
            ),
            None,
        )

    return [
        {
            "provider_call_index": index,
            "run_id": context["run_id"],
            "run_kind": context["run_kind"],
            "checkpoint_id": context["checkpoint_id"],
            "stage": ledger.stage,
            "prompt_id": ledger.prompt_id,
            "prompt_version": ledger.prompt_version,
            "prompt_hash": ledger.prompt_hash,
            "model": ledger.route.model,
            "effective_model": ledger.route.model_snapshot,
            "reasoning_effort": ledger.route.reasoning_effort.value,
            "input_tokens": ledger.input_tokens,
            "cached_input_tokens": ledger.cached_input_tokens,
            "cache_write_input_tokens": reason_integer(
                ledger, "CACHE_WRITE_INPUT_TOKENS_"
            ),
            "output_tokens": ledger.output_tokens,
            "reasoning_tokens": reason_integer(
                ledger, "REASONING_TOKENS_"
            ),
            "actual_provider_cost_usd": ledger.actual_cost_usd,
            "conservative_budget_charge_usd": max(
                ledger.estimated_cost_usd,
                ledger.actual_cost_usd or 0.0,
            ),
            "attempt": ledger.attempt,
            "gateway_retries": max(0, ledger.attempt - 1),
            "sdk_retries": 0,
            "semantic_retries": 0,
            "fallback": ledger.route.fallback_route_id is not None,
            "repaired": False,
            "result": ledger.result,
            "input_hash": ledger.input_bundle_hash,
            "output_hash": reason_hash(ledger, "OUTPUT_HASH_"),
            "provider_request_id_hash": reason_hash(
                ledger, "PROVIDER_REQUEST_ID_HASH_"
            ),
            "provider_transport": provider_transport,
        }
        for index, (ledger, context) in enumerate(
            zip(ledgers, contexts, strict=True),
            start=1,
        )
    ]


class _ConservativeNoNetworkAdapter:
    """Exercise REAL routing while replacing transport with deterministic data."""

    def __init__(
        self,
        routes: Mapping[str, m.ModelRoute],
        *,
        max_requests: int,
    ) -> None:
        self.routes = routes
        self.max_requests = max_requests
        self.calls = 0
        self.inner = DeterministicMockAdapter()
        self.cost_estimator = build_openai_cost_estimator(routes)
        self.input_token_estimator = build_openai_input_token_estimator(routes)

    async def invoke(self, **kwargs: Any) -> Any:
        if self.calls >= self.max_requests:
            raise ProviderBudgetError("SYNTHETIC_PROVIDER_REQUEST_CAP_EXCEEDED")
        self.calls += 1
        spec = prompt_spec(kwargs["prompt_id"])
        input_tokens = self.input_token_estimator(
            spec,
            kwargs["request"],
            kwargs["envelope"],
        )
        result = await self.inner.invoke(**kwargs)
        return replace(
            result,
            input_tokens=input_tokens,
            estimated_cost_usd=self.cost_estimator(spec, input_tokens),
            actual_cost_usd=0.0,
            cache_write_input_tokens=input_tokens,
            output_hash=canonical_hash(result.raw_output),
            reason_codes=(
                "NO_NETWORK_DETERMINISTIC_PREFLIGHT",
                "CONSERVATIVE_BUDGET_RESERVATION",
            ),
        )


async def _execute_convergence_matrix(
    rehearsal: ProductRehearsal,
    *,
    run_id_prefix: str,
) -> tuple[list[RehearsalObservation], list[dict[str, Any]], list[str]]:
    observations = [
        await rehearsal.run_sweep(run_id=f"{run_id_prefix}sweep-base")
    ]
    deterministic_checks = [
        evaluate_p05_golden_positive(),
        evaluate_p05_golden_negative(),
    ]
    observations.extend(
        [
            await rehearsal.run_chain(
                run_id=f"{run_id_prefix}chain-base-1"
            ),
            await rehearsal.run_chain(
                run_id=f"{run_id_prefix}chain-base-2"
            ),
            await rehearsal.run_chain(
                run_id=f"{run_id_prefix}chain-choice-variant",
                scenario_id=VARIANT_SCENARIO_ID,
            ),
            await rehearsal.run_chain(
                run_id=f"{run_id_prefix}chain-canonical-document-sufficient",
                scenario_id=CANONICAL_DOCUMENT_SCENARIO_ID,
            ),
        ]
    )
    return (
        observations,
        deterministic_checks,
        [row.row_id for row in QUALIFICATION_MATRIX_ROWS],
    )


def _observation_rows(
    observations: list[RehearsalObservation],
) -> list[dict[str, Any]]:
    return [
        {
            "run_id": item.run_id,
            "run_kind": item.run_kind,
            "scenario_id": item.scenario_id,
            "status": item.status,
            "stages": list(item.stages),
            "failure": item.failure,
            "output_hash": item.output_hash,
            "checkpoint_assessments": list(item.checkpoint_assessments),
        }
        for item in observations
    ]


def _qualification_checkpoint_assessments(
    observations: list[RehearsalObservation],
) -> list[CheckpointAssessment]:
    return [
        CheckpointAssessment.model_validate(raw)
        for observation in observations
        if observation.run_kind == "SEMANTIC_QUALIFICATION_SWEEP"
        for raw in observation.checkpoint_assessments
    ]


async def run_offline_convergence(
    *,
    route_profile_id: str = OPENAI_ROUTE_PROFILE_ID,
    max_total_cost_usd: float = 0.75,
    max_call_cost_usd: float = 0.10,
    max_provider_requests: int = QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
) -> dict[str, Any]:
    """Run the semantic sweep and four structural integrated chains offline."""

    from .model_gateway import GatewayConfig, GatewayMode

    ledger_records: list[m.ModelCallLedger] | None = None
    preflight_adapter: _ConservativeNoNetworkAdapter | None = None
    reviewed_semantic_adapter: Any | None = None
    if route_profile_id == OPENAI_ROUTE_PROFILE_ID:
        from .semantic_harness import build_reviewed_semantic_adapter

        reviewed_semantic_adapter = build_reviewed_semantic_adapter()
        gateway = ModelGateway(
            GatewayConfig(
                mode=GatewayMode.MOCK,
                max_retries=0,
                job_id="job_stage2_offline_convergence",
            ),
            mock_adapter=reviewed_semantic_adapter,
        )
        rehearsal = ProductRehearsal(gateway, max_call_cost_usd=1.0)
        run_id_prefix = ""
    elif route_profile_id in {
        OPENAI_XHIGH_ROUTE_PROFILE_ID,
        OPENAI_MAX_ROUTE_PROFILE_ID,
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
        OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
        OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
        OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
        OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
    }:
        if max_total_cost_usd <= 0 or max_call_cost_usd <= 0:
            raise ValueError("positive qualification preflight cost caps are required")
        from .semantic_harness import build_reviewed_semantic_adapter

        routes = build_openai_routes(
            max_call_cost_usd=max_call_cost_usd,
            route_profile_id=route_profile_id,
        )
        ledger_records = []
        preflight_adapter = _ConservativeNoNetworkAdapter(
            routes,
            max_requests=max_provider_requests,
        )
        reviewed_semantic_adapter = build_reviewed_semantic_adapter()
        preflight_adapter.inner = reviewed_semantic_adapter
        gateway = ModelGateway(
            GatewayConfig(
                mode=GatewayMode.REAL,
                max_retries=0,
                default_budget_usd=max_call_cost_usd,
                job_id=(
                    "job_stage2_sol_xhigh_offline_preflight"
                    if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
                    else "job_stage2_sol_high_offline_preflight"
                    if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
                    else "job_stage2_sol_medium_offline_preflight"
                    if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
                    else "job_stage2_terra_xhigh_offline_preflight"
                    if route_profile_id
                    == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
                    else "job_stage2_terra_high_offline_preflight"
                    if route_profile_id
                    == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
                    else "job_stage2_terra_medium_offline_preflight"
                    if route_profile_id
                    == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
                    else "job_stage2_xhigh_offline_preflight"
                    if route_profile_id == OPENAI_XHIGH_ROUTE_PROFILE_ID
                    else "job_stage2_max_offline_preflight"
                ),
            ),
            real_routes=routes,
            adapters={"openai": preflight_adapter},
            ledger_sink=ledger_records.append,
            cost_estimator=build_openai_cost_estimator(routes),
            input_token_estimator=build_openai_input_token_estimator(routes),
        )
        rehearsal = ProductRehearsal(
            gateway,
            max_call_cost_usd=max_call_cost_usd,
            max_total_cost_usd=max_total_cost_usd,
            ledger_records=ledger_records,
        )
        run_id_prefix = (
            "sol-xhigh-offline-"
            if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
            else "sol-high-offline-"
            if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
            else "sol-medium-offline-"
            if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
            else "terra-xhigh-offline-"
            if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
            else "terra-high-offline-"
            if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
            else "terra-medium-offline-"
            if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
            else "xhigh-offline-"
            if route_profile_id == OPENAI_XHIGH_ROUTE_PROFILE_ID
            else "max-offline-"
        )
    else:
        raise ValueError(f"Unknown OpenAI route profile: {route_profile_id}")

    observations, deterministic_checks, execution_sequence = (
        await _execute_convergence_matrix(
            rehearsal,
            run_id_prefix=run_id_prefix,
        )
    )
    checkpoint_assessments = _qualification_checkpoint_assessments(
        observations
    )
    controls = rehearsal.controls()
    if ledger_records is not None and preflight_adapter is not None:
        controls.update(_provider_usage_controls(ledger_records))
        controls.update(
            {
                "route_profile": route_profile_id,
                "network_calls": 0,
                "openai_network_calls": 0,
                "billable_requests": 0,
                "secret_resolutions": 0,
                "simulated_provider_attempts": preflight_adapter.calls,
                "expected_provider_requests": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "max_provider_requests": max_provider_requests,
                "max_total_cost_usd": max_total_cost_usd,
                "max_call_cost_usd": max_call_cost_usd,
                "gateway_retries": 0,
                "sdk_retries": 0,
                "tools_enabled": False,
                "store": False,
                "background": False,
                "semantic_normalizations": 0,
                "fixture_changes": 0,
                "prompt_changes": 0,
                "validator_changes": 0,
                "integrated_golden_injection": False,
            }
        )
    invocation_origins = [
        row["response_origin"]
        for row in getattr(reviewed_semantic_adapter, "invocations", [])
    ]
    transport_provenance = {
        "provider_transport_constructed": False,
        "reviewed_semantic_oracle_invocations": invocation_origins.count(
            "REVIEWED_SEMANTIC_ORACLE"
        ),
        "structural_transport_substitute_invocations": invocation_origins.count(
            "STRUCTURAL_TRANSPORT_SUBSTITUTE"
        ),
        "semantic_sweep_response_origin": "REVIEWED_SEMANTIC_ORACLE",
        "integrated_chain_response_origin": (
            "STRUCTURAL_TRANSPORT_SUBSTITUTE"
        ),
        "integrated_chain_semantic_quality_conclusion_allowed": False,
    }
    qualified_effort = (
        m.ReasoningEffort.XHIGH
        if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.HIGH
        if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MEDIUM
        if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
        else m.ReasoningEffort.XHIGH
        if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.HIGH
        if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MEDIUM
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MAX
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else m.ReasoningEffort.XHIGH
    )
    qualified_prompt_ids = (
        OPENAI_SOL_XHIGH_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
        else OPENAI_SOL_HIGH_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
        else OPENAI_SOL_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
        else OPENAI_TERRA_XHIGH_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
        else OPENAI_TERRA_HIGH_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
        else OPENAI_TERRA_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else OPENAI_MAX_PROMPT_IDS
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else OPENAI_XHIGH_PROMPT_IDS
    )
    expected_model = (
        TERRA_MODEL_ID
        if route_profile_id
        in {
            OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
            OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        }
        else SOL_MODEL_ID
        if route_profile_id
        in {
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
        }
        else LUNA_MODEL_ID
    )
    qualification_efforts_are_exact = (
        route_profile_id == OPENAI_ROUTE_PROFILE_ID
        or controls.get("reasoning_efforts_by_prompt")
        == {
            prompt_id: [qualified_effort.value]
            for prompt_id in sorted(qualified_prompt_ids)
        }
    )
    status = (
        "PASS"
        if all(item.status == "PASS" for item in observations)
        and all(item["status"] == "PASS" for item in deterministic_checks)
        and controls["p10_calls"] == 0
        and controls["p11_calls"] == 0
        and controls["fallback_calls"] == 0
        and qualification_efforts_are_exact
        and aggregate_causal_classification(checkpoint_assessments)
        == "QUALIFICATION_PASSED"
        and (
            route_profile_id == OPENAI_ROUTE_PROFILE_ID
            or (
                controls["provider_attempts"]
                == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
                and controls["simulated_provider_attempts"]
                == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
                and controls["network_calls"] == 0
                and controls["models"] == [expected_model]
                and controls["budget_charged_usd"] <= max_total_cost_usd
                and controls["max_observed_budget_charge_usd"]
                <= max_call_cost_usd
            )
        )
        else "FAIL"
    )
    boundary = rehearsal_boundary_material(
        route_profile_id,
        max_call_cost_usd=max_call_cost_usd,
    )
    return {
        "report_schema_version": REHEARSAL_REPORT_VERSION,
        "rehearsal_version": REHEARSAL_VERSION,
        "mode": (
            "offline-sol-xhigh-qualification"
            if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
            else "offline-sol-high-qualification"
            if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
            else "offline-sol-medium-qualification"
            if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
            else "offline-terra-xhigh-qualification"
            if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
            else "offline-terra-high-qualification"
            if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
            else "offline-terra-medium-qualification"
            if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
            else (
                "offline-max-qualification"
                if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
                else (
                    "offline-xhigh-qualification"
                    if route_profile_id == OPENAI_XHIGH_ROUTE_PROFILE_ID
                    else "offline-convergence"
                )
            )
        ),
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "status": status,
        "route_profile": route_profile_id,
        "executable_boundary_hash": canonical_hash(boundary),
        "boundary": boundary,
        "execution_sequence": execution_sequence,
        "qualification_matrix": qualification_matrix_rows(),
        "derived_max_provider_requests": (
            QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
        ),
        "transport_provenance": transport_provenance,
        "provider_call_receipts": _provider_call_receipts(
            ledger_records or [],
            rehearsal.provider_call_contexts,
            provider_transport=False,
        ),
        "observations": _observation_rows(observations),
        "deterministic_checks": deterministic_checks,
        "checkpoint_assessments": [
            item.model_dump() for item in checkpoint_assessments
        ],
        "causal_classification": aggregate_causal_classification(
            checkpoint_assessments
        ),
        "controls": controls,
    }


def run_offline_convergence_sync() -> dict[str, Any]:
    return asyncio.run(run_offline_convergence())


async def run_real_convergence(
    *,
    api_key: SecretStr,
    max_total_cost_usd: float,
    max_call_cost_usd: float,
    max_provider_requests: int,
    route_profile_id: str = OPENAI_ROUTE_PROFILE_ID,
) -> dict[str, Any]:
    """Run the same convergence matrix with an approved strict route profile."""

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if max_total_cost_usd <= 0 or max_call_cost_usd <= 0:
        raise ValueError("positive real-evaluation cost caps are required")
    if max_call_cost_usd > max_total_cost_usd:
        raise ValueError("per-call cost cap cannot exceed total cost cap")
    routes = build_openai_routes(
        max_call_cost_usd=max_call_cost_usd,
        route_profile_id=route_profile_id,
    )
    capped_adapter = RequestCappedAdapter(
        OpenAIResponsesAdapter(
            api_key=api_key,
            config=OpenAIAdapterConfig(request_timeout_seconds=300.0),
        ),
        max_requests=max_provider_requests,
    )
    ledger_records: list[m.ModelCallLedger] = []
    gateway = ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=305.0,
            max_retries=0,
            default_budget_usd=max_call_cost_usd,
            job_id=(
                "job_stage2_sol_xhigh_real_qualification"
                if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
                else "job_stage2_sol_high_real_qualification"
                if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
                else "job_stage2_sol_medium_real_qualification"
                if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
                else "job_stage2_terra_xhigh_real_qualification"
                if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
                else "job_stage2_terra_high_real_qualification"
                if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
                else "job_stage2_terra_medium_real_qualification"
                if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
                else (
                    "job_stage2_max_real_qualification"
                    if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
                    else (
                        "job_stage2_xhigh_real_qualification"
                        if route_profile_id == OPENAI_XHIGH_ROUTE_PROFILE_ID
                        else "job_stage2_real_convergence"
                    )
                )
            ),
        ),
        real_routes=routes,
        adapters={"openai": capped_adapter},
        ledger_sink=ledger_records.append,
        cost_estimator=build_openai_cost_estimator(routes),
        input_token_estimator=build_openai_input_token_estimator(routes),
    )
    rehearsal = ProductRehearsal(
        gateway,
        max_call_cost_usd=max_call_cost_usd,
        max_total_cost_usd=max_total_cost_usd,
        ledger_records=ledger_records,
    )
    boundary = rehearsal_boundary_material(
        route_profile_id,
        max_call_cost_usd=max_call_cost_usd,
    )
    executable_boundary_hash = canonical_hash(boundary)
    observations, deterministic_checks, execution_sequence = (
        await _execute_convergence_matrix(
            rehearsal,
            run_id_prefix="real-",
        )
    )
    checkpoint_assessments = _qualification_checkpoint_assessments(
        observations
    )
    controls = rehearsal.controls()
    controls.update(_provider_usage_controls(ledger_records))
    controls.update(
        {
            "route_profile": route_profile_id,
            "network_calls": capped_adapter.calls,
            "expected_provider_requests": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
            "max_provider_requests": max_provider_requests,
            "max_total_cost_usd": max_total_cost_usd,
            "max_call_cost_usd": max_call_cost_usd,
            "gateway_retries": 0,
            "sdk_retries": 0,
            "tools_enabled": False,
            "store": False,
            "background": False,
            "semantic_normalizations": 0,
            "fixture_changes": 0,
            "prompt_changes": 0,
            "validator_changes": 0,
            "integrated_golden_injection": False,
        }
    )
    boundary_after_hash = canonical_hash(
        rehearsal_boundary_material(
            route_profile_id,
            max_call_cost_usd=max_call_cost_usd,
        )
    )
    unchanged_boundary = executable_boundary_hash == boundary_after_hash
    qualified_effort = (
        m.ReasoningEffort.XHIGH
        if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.HIGH
        if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MEDIUM
        if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
        else m.ReasoningEffort.XHIGH
        if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.HIGH
        if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MEDIUM
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MAX
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else m.ReasoningEffort.XHIGH
    )
    qualified_prompt_ids = (
        OPENAI_SOL_XHIGH_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
        else OPENAI_SOL_HIGH_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
        else OPENAI_SOL_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
        else OPENAI_TERRA_XHIGH_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
        else OPENAI_TERRA_HIGH_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
        else OPENAI_TERRA_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else OPENAI_MAX_PROMPT_IDS
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else OPENAI_XHIGH_PROMPT_IDS
    )
    expected_model = (
        TERRA_MODEL_ID
        if route_profile_id
        in {
            OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
            OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        }
        else SOL_MODEL_ID
        if route_profile_id
        in {
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
        }
        else LUNA_MODEL_ID
    )
    qualification_efforts_are_exact = (
        route_profile_id == OPENAI_ROUTE_PROFILE_ID
        or controls["reasoning_efforts_by_prompt"]
        == {
            prompt_id: [qualified_effort.value]
            for prompt_id in sorted(qualified_prompt_ids)
        }
    )
    status = (
        "PASS"
        if all(item.status == "PASS" for item in observations)
        and all(item["status"] == "PASS" for item in deterministic_checks)
        and controls["p10_calls"] == 0
        and controls["p11_calls"] == 0
        and controls["fallback_calls"] == 0
        and controls["semantic_retries"] == 0
        and controls["provider_attempts"]
        == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
        and controls["network_calls"]
        == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
        and controls["unpriced_attempts"] == 0
        and controls["models"] == [expected_model]
        and qualification_efforts_are_exact
        and aggregate_causal_classification(checkpoint_assessments)
        == "QUALIFICATION_PASSED"
        and unchanged_boundary
        and controls["actual_cost_usd"] <= max_total_cost_usd
        and controls["budget_charged_usd"] <= max_total_cost_usd
        and controls["max_observed_actual_call_cost_usd"]
        <= max_call_cost_usd
        and controls["max_observed_budget_charge_usd"]
        <= max_call_cost_usd
        else "FAIL"
    )
    return {
        "report_schema_version": REHEARSAL_REPORT_VERSION,
        "rehearsal_version": REHEARSAL_VERSION,
        "mode": (
            "real-sol-xhigh-qualification"
            if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
            else "real-sol-high-qualification"
            if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
            else "real-sol-medium-qualification"
            if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
            else "real-terra-xhigh-qualification"
            if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
            else "real-terra-high-qualification"
            if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
            else "real-terra-medium-qualification"
            if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
            else (
                "real-max-qualification"
                if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
                else (
                    "real-xhigh-qualification"
                    if route_profile_id == OPENAI_XHIGH_ROUTE_PROFILE_ID
                    else "real-convergence"
                )
            )
        ),
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "status": status,
        "route_profile": route_profile_id,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "executable_boundary_hash": executable_boundary_hash,
        "unchanged_boundary_across_chains": unchanged_boundary,
        "boundary": boundary,
        "execution_sequence": execution_sequence,
        "qualification_matrix": qualification_matrix_rows(),
        "derived_max_provider_requests": (
            QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
        ),
        "provider_call_receipts": _provider_call_receipts(
            ledger_records,
            rehearsal.provider_call_contexts,
            provider_transport=True,
        ),
        "observations": _observation_rows(observations),
        "deterministic_checks": deterministic_checks,
        "checkpoint_assessments": [
            item.model_dump() for item in checkpoint_assessments
        ],
        "causal_classification": aggregate_causal_classification(
            checkpoint_assessments
        ),
        "controls": controls,
    }
