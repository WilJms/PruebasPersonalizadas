"""Product-shaped P04-P09 synthetic rehearsal over production boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast

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
    OPENAI_TERRA_MEDIUM_PROMPT_IDS,
    OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
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
    TERRA_MODEL_ID,
)
from .model_gateway.openai_adapter import OPENAI_SDK_VERSION
from .model_gateway.mock_factory import DeterministicMockAdapter
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


REHEARSAL_VERSION = "stage2-product-rehearsal/1.9.0"
REHEARSAL_REPORT_VERSION = "stage2-convergence-report/1.9.0"
QUALIFICATION_EXPECTED_PROVIDER_REQUESTS = 21
BASE_SCENARIO_ID = "synthetic-open-short-v1"
VARIANT_SCENARIO_ID = "synthetic-choice-justification-v1"
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
        "stage2-semantic-qualification-pack/1.0.0"
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
        validate_blueprint_review_preflight_checks(
            actual,
            review_request.deterministic_preflight,
        )
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
            if (
                actual.approval_recommendation
                != m.BlueprintApprovalRecommendation.REJECT
                or critical != {"PLAN_FEASIBILITY"}
            ):
                raise _SemanticCheckpointMismatch(
                    "P05_NEGATIVE_NOT_REJECTED",
                    "P05 did not reject the reviewed PLAN_FEASIBILITY negative",
                    semantic_interpretation=SemanticInterpretation.INCORRECT,
                    contractual_adherence=ContractualAdherence.PASS,
                    safe_metadata={"critical_categories": sorted(critical)},
                )
        else:
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
        validate_evidence_map(
            mapping,
            blueprint=map_request.blueprint,
            bundle=map_request.evidence_bundle,
            planning_policy=map_request.planning_policy,
        )
        if (
            mapping.status != m.WorkflowStatus.READY
            or not mapping.opportunities
        ):
            raise _SemanticCheckpointMismatch(
                "P06_POSITIVE_NOT_READY",
                "P06 did not map the reviewed positive opportunity",
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
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
            reviewed_generation = cast(m.QuestionGenerationResult, expected)
            reviewed_candidate = reviewed_generation.candidate
            if (
                reviewed_candidate is None
                or generation.candidate.model_dump(mode="json")
                != reviewed_candidate.model_dump(mode="json")
            ):
                raise _SemanticCheckpointMismatch(
                    "P07_POSITIVE_REQUIRES_INDEPENDENT_SEMANTIC_REVIEW",
                    (
                        "P07 produced a structurally valid alternative that has "
                        "not received the versioned semantic review"
                    ),
                    semantic_interpretation=(
                        SemanticInterpretation.INDETERMINATE
                    ),
                    contractual_adherence=ContractualAdherence.PASS,
                    safe_metadata={"reviewed_golden_match": False},
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
                "P08 did not make the independently reviewed decision",
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
        result = await self.gateway.invoke(
            prompt_id,
            request,
            build_trusted_context(request),
            budget=CallBudget(max_cost_usd=remaining),
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
            "repaired": result.repaired,
            "input_tokens": ledger.input_tokens,
            "cached_input_tokens": ledger.cached_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
            "output_tokens": ledger.output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "actual_cost_usd": round(
                sum(item.actual_cost_usd for item in result.ledgers), 10
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
                    await self._invoke(prompt_id, request),
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
        checkpoints = build_rehearsal_checkpoints(scenario_id)
        stages: list[dict[str, Any]] = []
        current_stage = "P04"
        try:
            p04 = checkpoints.p04_request
            blueprint = cast(
                m.AssessmentBlueprint,
                await self._invoke("P04_BLUEPRINT_BUILD_V1", p04),
            )
            if blueprint.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "P04_NOT_READY", "P04 chain output is not READY"
                )
            stages.append(
                self._stage_row("P04_BLUEPRINT_BUILD_V1", p04, blueprint)
            )

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
                await self._invoke("P05_BLUEPRINT_REVIEW_V1", p05),
            )
            if not blueprint_review_is_approvable(blueprint_review):
                raise _BlueprintReviewNotApprovable(
                    blueprint_review, blueprint
                )
            stages.append(
                self._stage_row(
                    "P05_BLUEPRINT_REVIEW_V1", p05, blueprint_review
                )
            )
            approved_blueprint = blueprint.model_copy(
                update={"status": m.WorkflowStatus.APPROVED}
            )

            current_stage = "P06"
            p06 = checkpoints.p06_request.model_copy(
                update={
                    "blueprint": approved_blueprint,
                    "planning_policy": p04.blueprint_policy.planning_policy,
                }
            )
            mapping = cast(
                m.EvidenceMapPatch,
                await self._invoke("P06_EVIDENCE_MAP_V1", p06),
            )
            validate_evidence_map(
                mapping,
                blueprint=approved_blueprint,
                bundle=p06.evidence_bundle,
                planning_policy=p06.planning_policy,
            )
            stages.append(
                self._stage_row("P06_EVIDENCE_MAP_V1", p06, mapping)
            )

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
                    await self._invoke("P07_QUESTION_BUILD_V1", p07),
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
                stages.append(
                    self._stage_row(
                        "P07_QUESTION_BUILD_V1", p07, generation
                    )
                )

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
                    await self._invoke("P08_QUESTION_REVIEW_V1", p08),
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
                stages.append(
                    self._stage_row(
                        "P08_QUESTION_REVIEW_V1", p08, question_review
                    )
                )
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
                assignment_prompt_hashes=["sha256:" + "a" * 64],
                rubric_hashes=["sha256:" + "b" * 64],
                submission_hashes=["sha256:" + "c" * 64],
                submission_media_type="text/markdown",
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
                await self._invoke("P09_GUIDE_BUILD_V1", p09),
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
            stages.append(
                self._stage_row("P09_GUIDE_BUILD_V1", p09, guide)
            )
        except Exception as exc:
            structural_stages = _mark_structural_orchestration_rows(stages)
            return RehearsalObservation(
                run_id=run_id,
                run_kind="INTEGRATED_CHAIN",
                scenario_id=scenario_id,
                status="FAIL",
                stages=structural_stages,
                failure=_safe_failure(exc, stage=current_stage),
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
                run_id=f"{run_id_prefix}chain-choice-variant",
                scenario_id=VARIANT_SCENARIO_ID,
            ),
        ]
    )
    return (
        observations,
        deterministic_checks,
        [
            "semantic-sweep:P04-P09:versioned-positive-and-negative",
            "offline-golden-positive:P05",
            "offline-golden-negative:P05",
            "integrated-chain:base:1:P04-P09",
            "integrated-chain:choice-variant:P04-P09",
        ],
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
    max_provider_requests: int = 24,
) -> dict[str, Any]:
    """Run the semantic sweep and two structural integrated chains offline."""

    from .model_gateway import GatewayConfig, GatewayMode

    ledger_records: list[m.ModelCallLedger] | None = None
    preflight_adapter: _ConservativeNoNetworkAdapter | None = None
    if route_profile_id == OPENAI_ROUTE_PROFILE_ID:
        from .semantic_harness import build_reviewed_semantic_adapter

        reviewed_adapter = build_reviewed_semantic_adapter()
        gateway = ModelGateway(
            GatewayConfig(
                mode=GatewayMode.MOCK,
                max_retries=0,
                job_id="job_stage2_offline_convergence",
            ),
            mock_adapter=reviewed_adapter,
        )
        rehearsal = ProductRehearsal(gateway, max_call_cost_usd=1.0)
        run_id_prefix = ""
    elif route_profile_id in {
        OPENAI_XHIGH_ROUTE_PROFILE_ID,
        OPENAI_MAX_ROUTE_PROFILE_ID,
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
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
        preflight_adapter.inner = build_reviewed_semantic_adapter()
        gateway = ModelGateway(
            GatewayConfig(
                mode=GatewayMode.REAL,
                max_retries=0,
                default_budget_usd=max_call_cost_usd,
                job_id=(
                    "job_stage2_terra_medium_offline_preflight"
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
            "terra-medium-offline-"
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
                "simulated_provider_attempts": preflight_adapter.calls,
                "expected_provider_requests": QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
                "max_provider_requests": max_provider_requests,
                "max_total_cost_usd": max_total_cost_usd,
                "max_call_cost_usd": max_call_cost_usd,
                "gateway_retries": 0,
                "sdk_retries": 0,
                "tools_enabled": False,
                "store": False,
                "semantic_normalizations": 0,
                "fixture_changes": 0,
                "prompt_changes": 0,
                "validator_changes": 0,
            }
        )
    qualified_effort = (
        m.ReasoningEffort.MEDIUM
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MAX
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else m.ReasoningEffort.XHIGH
    )
    qualified_prompt_ids = (
        OPENAI_TERRA_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else OPENAI_MAX_PROMPT_IDS
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else OPENAI_XHIGH_PROMPT_IDS
    )
    expected_model = (
        TERRA_MODEL_ID
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
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
            "offline-terra-medium-qualification"
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
                "job_stage2_terra_medium_real_qualification"
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
            "semantic_normalizations": 0,
            "fixture_changes": 0,
            "prompt_changes": 0,
            "validator_changes": 0,
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
        m.ReasoningEffort.MEDIUM
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else m.ReasoningEffort.MAX
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else m.ReasoningEffort.XHIGH
    )
    qualified_prompt_ids = (
        OPENAI_TERRA_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else OPENAI_MAX_PROMPT_IDS
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else OPENAI_XHIGH_PROMPT_IDS
    )
    expected_model = (
        TERRA_MODEL_ID
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
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
            "real-terra-medium-qualification"
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
