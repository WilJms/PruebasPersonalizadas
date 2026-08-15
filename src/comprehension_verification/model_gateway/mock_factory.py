"""Deterministic, contract-valid P01-P11 mocks and synthetic request factory.

These mocks prove orchestration and contract behavior only.  They do not claim
to validate semantic model quality.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from typing import Any

from pydantic import BaseModel, ValidationError

from comprehension_verification.canonical import canonical_hash, stable_id
from comprehension_verification.contracts import model_by_name, models
from comprehension_verification.evidence_mapping import (
    build_evidence_mapping_alias_envelope,
)
from comprehension_verification.question_generation import (
    build_question_alias_envelope,
)


FIXED_TIME = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


class MockBehavior(StrEnum):
    HAPPY = "happy"
    ABSTAIN = "abstain"
    INVALID_ONCE = "invalid_once"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class AdapterResult:
    raw_output: Any
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    cache_write_input_tokens: int = 0
    reasoning_tokens: int = 0
    effective_model: str | None = None
    output_hash: str | None = None
    provider_request_id_hash: str | None = None
    provider_schema_valid: bool | None = None
    provider_schema_issues: tuple[tuple[str, str], ...] = ()
    reason_codes: tuple[str, ...] = ()


def _diagnostic(
    code: str,
    message: str,
    *,
    evidence_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> models.Diagnostic:
    return models.Diagnostic(
        code=code,
        severity=models.Severity.ERROR,
        message=message,
        evidence_ids=evidence_ids or [],
        source_ids=source_ids or [],
        retryable=False,
        details=details or {},
    )


def _document_locator(paragraph_index: int = 0) -> models.DocumentLocator:
    return models.DocumentLocator(
        paragraph_index=paragraph_index,
        heading_path=["Sección sintética"],
    )


def _assignment_evidence() -> models.EvidenceUnit:
    return models.EvidenceUnit(
        evidence_id="ev_assignment_1",
        tenant_id="tnt_demo",
        artifact_id="art_assignment",
        artifact_hash=HASH_A,
        source_role=models.ArtifactRole.ASSIGNMENT_PROMPT,
        modality=models.EvidenceModality.PARAGRAPH,
        locator=_document_locator(),
        content_text=(
            "Explique un mecanismo de su entrega y justifique una consecuencia local."
        ),
        language="es-CL",
        extraction_confidence=1.0,
        normalized_hash=HASH_B,
    )


def _rubric_evidence() -> models.EvidenceUnit:
    return models.EvidenceUnit(
        evidence_id="ev_rubric_1",
        tenant_id="tnt_demo",
        artifact_id="art_rubric",
        artifact_hash=HASH_B,
        source_role=models.ArtifactRole.RUBRIC,
        modality=models.EvidenceModality.PARAGRAPH,
        locator=_document_locator(),
        content_text="Explica el mecanismo con evidencia localizada.",
        language="es-CL",
        extraction_confidence=1.0,
        normalized_hash=HASH_C,
    )


def _submission_evidence() -> models.EvidenceUnit:
    return models.EvidenceUnit(
        evidence_id="ev_submission_1",
        tenant_id="tnt_demo",
        submission_id="sub_demo",
        artifact_id="art_submission",
        artifact_hash=HASH_C,
        source_role=models.ArtifactRole.SUBMISSION,
        modality=models.EvidenceModality.PARAGRAPH,
        locator=_document_locator(),
        content_text=(
            "La caché se consulta antes del cálculo y se invalida cuando cambia la fuente."
        ),
        language="es-CL",
        extraction_confidence=1.0,
        normalized_hash=HASH_D,
    )


def _activity_config() -> models.ActivityConfig:
    return models.ActivityConfig(
        activity_id="act_demo",
        tenant_id="tnt_demo",
        title="Actividad sintética",
        question_count=1,
        target_total_minutes=5,
        allowed_response_formats=[models.ResponseFormat.OPEN_SHORT],
        allowed_artifact_media_types=["text/plain", "text/markdown", "application/pdf"],
    )


def _activity_spec(*, status: models.WorkflowStatus = models.WorkflowStatus.READY) -> models.ActivitySpec:
    evidence_ids = ["ev_assignment_1"]
    return models.ActivitySpec(
        activity_id="act_demo",
        status=status,
        learning_outcomes=[
            models.SourcedStatement(
                statement_id="outcome_1",
                text="Explicar un mecanismo localizado.",
                evidence_ids=evidence_ids,
            )
        ],
        expected_products=[
            models.SourcedStatement(
                statement_id="product_1",
                text="Un entregable explicativo.",
                evidence_ids=evidence_ids,
            )
        ],
        requirements=[
            models.SourcedStatement(
                statement_id="requirement_1",
                text="Justificar una consecuencia local.",
                evidence_ids=evidence_ids,
            )
        ],
    )


def _rubric_spec() -> models.RubricSpec:
    return models.RubricSpec(
        activity_id="act_demo",
        status=models.WorkflowStatus.READY,
        scale_label="0-3",
        criteria=[
            models.RubricCriterion(
                criterion_id="criterion_1",
                name="Explicación",
                evidence_ids=["ev_rubric_1"],
                grading_weight=1.0,
                levels=[
                    models.RubricLevel(
                        level_id="level_2",
                        label="Suficiente",
                        ordinal=2,
                        descriptor="Explica el núcleo del mecanismo.",
                        evidence_ids=["ev_rubric_1"],
                    )
                ],
                observables=["Relaciona consulta e invalidación."],
                verification_fit="HIGH",
            )
        ],
        reported_weight_total=1.0,
    )


def _planning_policy() -> models.AssessmentPlanningPolicy:
    return models.AssessmentPlanningPolicy(policy_id="planning_policy_1")


def _blueprint_policy() -> models.BlueprintPolicy:
    return models.BlueprintPolicy(
        policy_id="blueprint_policy_1",
        activity_id="act_demo",
        question_count=1,
        target_total_minutes=5,
        allowed_response_formats=[models.ResponseFormat.OPEN_SHORT],
        structured_justification_policy=models.StructuredJustificationPolicy(
            mode=models.StructuredJustificationMode.NOT_REQUIRED
        ),
        planning_policy=_planning_policy(),
    )


def _policy_decision() -> models.PolicyDecision:
    selected_option = models.DecisionOption(
        option_id="option_closed_materials",
        label="Usar únicamente el paquete autorizado",
        consequence=(
            "Mantiene el contexto cerrado y prohíbe fuentes de curso externas."
        ),
    )
    return models.PolicyDecision(
        decision_id="decision_closed_materials",
        issue_id="issue_material_boundary",
        selected_option_id=selected_option.option_id,
        selected_option=selected_option,
        decided_by="usr_teacher",
        decided_at=FIXED_TIME,
    )


def _opportunity_template() -> models.QuestionOpportunityTemplate:
    return models.QuestionOpportunityTemplate(
        opportunity_template_id="opt_explain_1",
        cognitive_operation=models.CognitiveOperation.EXPLAIN_MECHANISM,
        focus="Orden entre consulta e invalidación de la caché.",
        observable="Explica la relación funcional usando el fragmento.",
        difficulty=models.DifficultyBand.MEDIUM,
        target_minutes=3,
        allowed_anchor_structures=[models.AnchorStructure.SINGLE_FRAGMENT],
        allowed_response_formats=[models.ResponseFormat.OPEN_SHORT],
        verification_potential=0.9,
        minimum_quality=0.75,
    )


def _blueprint(*, status: models.WorkflowStatus = models.WorkflowStatus.READY) -> models.AssessmentBlueprint:
    template = _opportunity_template()
    return models.AssessmentBlueprint(
        blueprint_id="blueprint_demo",
        blueprint_version=1,
        activity_id="act_demo",
        status=status,
        context_mode=models.ContextMode.CLOSED,
        dimensions=[
            models.BlueprintDimension(
                dimension_id="dimension_1",
                name="Comprensión del mecanismo",
                criterion_ids=["criterion_1"],
                learning_outcome_ids=["outcome_1"],
                grading_weight=1.0,
                verification_priority=0.9,
                factors=models.VerificationFactors(
                    learning_relevance=0.9,
                    centrality=0.9,
                    expected_evidence=0.9,
                    discriminative_potential=0.9,
                    auditability=1.0,
                    short_response_observability=0.9,
                ),
                justification="La actividad exige explicar un mecanismo localizado.",
                evidence_variants=[
                    models.EvidenceVariant(
                        variant_id="variant_1",
                        name="Explicación textual",
                        description="Fragmento que declara un mecanismo y su dependencia.",
                        evidence_requirement=models.EvidenceRequirement(
                            allowed_modalities=[models.EvidenceModality.PARAGRAPH]
                        ),
                        verification_potential=0.9,
                        supported_operations=[
                            models.SupportedOperation(
                                cognitive_operation=(
                                    models.CognitiveOperation.EXPLAIN_MECHANISM
                                ),
                                support_strength=0.9,
                                rationale="El fragmento expone el orden funcional.",
                            )
                        ],
                        question_opportunities=[template],
                    )
                ],
            )
        ],
        assessment_constraints=models.AssessmentConstraints(
            question_count=1,
            target_total_minutes=5,
            allowed_response_formats=[models.ResponseFormat.OPEN_SHORT],
            structured_justification_policy=models.StructuredJustificationPolicy(
                mode=models.StructuredJustificationMode.NOT_REQUIRED
            ),
        ),
        decision_ids=[_policy_decision().decision_id],
    )


def _evidence_bundle(*, enriched: bool = False) -> models.EvidenceBundle:
    passages: list[models.CoursePassage] = []
    mode = models.ContextMode.CLOSED
    if enriched:
        mode = models.ContextMode.COURSE_ENRICHED
        passages = [
            models.CoursePassage(
                source_id="source_course_1",
                artifact_id="art_course",
                artifact_hash=HASH_D,
                title="Material autorizado",
                locator=_document_locator(1),
                content_text="Una caché coherente invalida entradas cuando cambia la fuente.",
                language="es-CL",
                extraction_confidence=1.0,
            )
        ]
    evidence = _submission_evidence()
    return models.EvidenceBundle(
        bundle_id="bundle_demo_enriched" if enriched else "bundle_demo",
        tenant_id="tnt_demo",
        activity_id="act_demo",
        submission_id="sub_demo",
        context_mode=mode,
        allowed_evidence_ids=[evidence.evidence_id],
        evidence_units=[evidence],
        course_passages=passages,
    )


def _opportunity() -> models.QuestionOpportunity:
    template = _opportunity_template()
    return models.QuestionOpportunity(
        opportunity_id="opp_demo_1",
        opportunity_template_id=template.opportunity_template_id,
        submission_id="sub_demo",
        dimension_id="dimension_1",
        variant_id="variant_1",
        evidence_ids=["ev_submission_1"],
        cognitive_operation=template.cognitive_operation,
        focus=template.focus,
        observable=template.observable,
        difficulty=template.difficulty,
        target_minutes=template.target_minutes,
        allowed_anchor_structures=template.allowed_anchor_structures,
        allowed_response_formats=template.allowed_response_formats,
        activity_priority=0.9,
        evidence_fit=0.95,
        opportunity_quality=0.9,
    )


def _plan() -> models.AssessmentPlan:
    return models.AssessmentPlan(
        plan_id="plan_demo",
        submission_id="sub_demo",
        blueprint_id="blueprint_demo",
        blueprint_version=1,
        status="READY",
        question_count=1,
        selected_opportunity_ids=["opp_demo_1"],
        estimated_total_minutes=3,
    )


def _guide_draft() -> models.GuideDraft:
    element_ids = ["observable_1", "observable_2"]
    return models.GuideDraft(
        purpose="Observar una explicación localizada del mecanismo.",
        observable_elements=[
            models.ObservableElement(
                element_id="observable_1",
                description="Relaciona consulta e invalidación.",
                evidence_ids=["ev_submission_1"],
            ),
            models.ObservableElement(
                element_id="observable_2",
                description="Delimita la consecuencia observable del cambio.",
                evidence_ids=["ev_submission_1"],
            ),
        ],
        acceptable_alternatives=["Puede describir la relación en orden inverso."],
        misconceptions=["Confunde invalidación con cálculo inicial."],
        levels=[
            models.GuideLevel(
                level=level,
                label=f"Nivel {level}",
                descriptor=(
                    "No explica el mecanismo."
                    if level == 0
                    else "Explica el mecanismo con precisión creciente."
                ),
                observable_element_ids=[] if level == 0 else element_ids,
            )
            for level in range(4)
        ],
        cannot_infer=["No permite inferir el proceso histórico de producción."],
    )


def _candidate(*, enriched: bool = False) -> models.QuestionCandidate:
    citations: list[models.SourceCitation] = []
    source_ids: list[str] = []
    if enriched:
        citations = [
            models.SourceCitation(
                source_id="source_course_1",
                locator=_document_locator(1),
                supported_claim="La invalidación mantiene coherencia con la fuente.",
            )
        ]
        source_ids = ["source_course_1"]
    return models.QuestionCandidate(
        candidate_id="candidate_demo_1",
        submission_id="sub_demo",
        opportunity_id="opp_demo_1",
        opportunity_template_id="opt_explain_1",
        dimension_id="dimension_1",
        variant_id="variant_1",
        cognitive_operation=models.CognitiveOperation.EXPLAIN_MECHANISM,
        response_format=models.ResponseFormat.OPEN_SHORT,
        difficulty=models.DifficultyBand.MEDIUM,
        estimated_minutes=3,
        question_text=(
            "¿Qué función cumple consultar la caché antes del cálculo y cuándo se invalida?"
        ),
        anchor=models.Anchor(
            anchor_id="anchor_demo_1",
            structure=models.AnchorStructure.SINGLE_FRAGMENT,
            fragments=[
                models.AnchorFragment(
                    evidence_id="ev_submission_1",
                    display_text=(
                        "La caché se consulta antes del cálculo y se invalida cuando "
                        "cambia la fuente."
                    ),
                    transformation="LITERAL",
                    locator=_document_locator(),
                )
            ],
            self_containment_score=0.95,
            answer_leakage_risk=0.1,
        ),
        evidence_ids=["ev_submission_1"],
        course_source_ids=source_ids,
        citations=citations,
        preliminary_guide=_guide_draft(),
    )


def _dynamic_blueprint_draft(
    request: models.BlueprintBuildRequest,
) -> models.BlueprintModelDraft:
    """Build a deterministic semantic draft from the trusted P04 inputs.

    Canonical IDs, constraints, status and approval metadata are deliberately
    absent; the production compiler owns those fields in mock and real modes.
    """

    policy = request.blueprint_policy
    selected_count = len(
        policy.structured_justification_policy.selected_opportunity_template_ids
    )
    requested_catalog_size = max(
        policy.question_count + policy.planning_policy.max_reserve_opportunities,
        selected_count,
    )
    catalog_size = min(
        requested_catalog_size,
        policy.max_variants_per_dimension * policy.max_templates_per_variant,
    )
    operations = list(models.CognitiveOperation)
    difficulties = list(models.DifficultyBand)
    target_minutes = min(
        60,
        max(1, policy.target_total_minutes // policy.question_count),
    )
    rubric_criterion_ids = (
        [criterion.criterion_id for criterion in request.rubric_spec.criteria]
        if request.rubric_spec is not None
        else []
    )
    sourced_statement_ids = [
        item.statement_id
        for collection in (
            request.activity_spec.learning_outcomes,
            request.activity_spec.expected_products,
            request.activity_spec.requirements,
        )
        for item in collection
    ]
    criterion_ids = rubric_criterion_ids or sourced_statement_ids
    learning_outcome_ids = [
        outcome.statement_id for outcome in request.activity_spec.learning_outcomes
    ]
    dimension = models.BlueprintDimensionDraft(
        dimension_alias="D1",
        name="Comprensión verificable del entregable",
        criterion_ids=criterion_ids,
        learning_outcome_ids=learning_outcome_ids,
        verification_priority=0.95,
        factors=models.VerificationFactors(
            learning_relevance=0.95,
            centrality=0.9,
            expected_evidence=0.9,
            discriminative_potential=0.85,
            auditability=1.0,
            short_response_observability=0.9,
        ),
        justification=(
            "Dimensión sintética derivada de requisitos y evidencia "
            "autorizados para probar la orquestación."
        ),
    )

    variants: list[models.EvidenceVariantDraft] = []
    templates: list[models.QuestionOpportunityTemplateDraft] = []
    for chunk_index, start in enumerate(
        range(0, catalog_size, policy.max_templates_per_variant)
    ):
        variant_alias = f"V{chunk_index + 1}"
        stop = min(start + policy.max_templates_per_variant, catalog_size)
        chunk_operations = list(
            dict.fromkeys(
                operations[index % len(operations)]
                for index in range(start, stop)
            )
        )
        variants.append(
            models.EvidenceVariantDraft(
                variant_alias=variant_alias,
                dimension_alias="D1",
                name=f"Evidencia localizada {chunk_index + 1}",
                description=(
                    "Fragmentos textuales localizables que permiten una "
                    f"verificación acotada en la variante {chunk_index + 1}."
                ),
                evidence_requirement=models.EvidenceRequirement(
                    allowed_modalities=[
                        models.EvidenceModality.HEADING,
                        models.EvidenceModality.PARAGRAPH,
                        models.EvidenceModality.LIST,
                        models.EvidenceModality.OTHER,
                    ],
                    min_distinct_units=1,
                    min_extraction_confidence=0.0,
                    min_alignment=0.0,
                ),
                verification_potential=0.95,
                supported_operations=[
                    models.SupportedOperation(
                        cognitive_operation=operation,
                        support_strength=0.95,
                        rationale=(
                            "La evidencia localizada sustenta la operación "
                            f"{operation.value.lower()}."
                        ),
                    )
                    for operation in chunk_operations
                ],
            )
        )
        for index in range(start, stop):
            templates.append(
                models.QuestionOpportunityTemplateDraft(
                    template_alias=f"T{index + 1}",
                    variant_alias=variant_alias,
                    cognitive_operation=operations[index % len(operations)],
                    focus=f"Aspecto verificable {index + 1} del entregable.",
                    observable=(
                        "Relaciona la afirmación localizada "
                        f"{index + 1} con una consecuencia observable."
                    ),
                    difficulty=difficulties[index % len(difficulties)],
                    target_minutes=target_minutes,
                    allowed_anchor_structures=[
                        models.AnchorStructure.SINGLE_FRAGMENT
                    ],
                    allowed_response_formats=list(policy.allowed_response_formats),
                    verification_potential=0.95,
                    justification_required=(
                        policy.structured_justification_policy.mode
                        == models.StructuredJustificationMode.SELECTED
                        and index < selected_count
                    ),
                )
            )

    return models.BlueprintModelDraft(
        dimensions=[
            dimension,
        ],
        evidence_variants=variants,
        question_opportunities=templates,
    )


def _eligible_evidence(
    variant: models.EvidenceVariant,
    bundle: models.EvidenceBundle,
) -> list[models.EvidenceUnit]:
    requirement = variant.evidence_requirement
    eligible = [
        evidence
        for evidence in bundle.evidence_units
        if evidence.modality in requirement.allowed_modalities
        and evidence.extraction_confidence >= requirement.min_extraction_confidence
    ]
    if requirement.cross_artifact_required and len(
        {evidence.artifact_id for evidence in eligible}
    ) < 2:
        return []
    if len(eligible) < requirement.min_distinct_units:
        return []
    return eligible


def _dynamic_evidence_map(
    request: models.EvidenceMapRequest,
) -> models.EvidenceMappingModelDraft:
    """Produce semantic aliases only; the gateway materializes canonical IR."""

    envelope = build_evidence_mapping_alias_envelope(request)
    evidence_alias_by_id = {
        evidence.evidence_id: context.evidence_alias
        for evidence, context in zip(
            request.evidence_bundle.evidence_units,
            envelope.evidence_units,
            strict=True,
        )
    }
    variant_alias_by_id = {
        variant.variant_id: context.variant_alias
        for variant, context in zip(
            (
                variant
                for dimension in request.blueprint.dimensions
                for variant in dimension.evidence_variants
            ),
            envelope.variants,
            strict=True,
        )
    }
    template_contexts = iter(envelope.templates)
    mappings: list[models.EvidenceMappingRelationDraft] = []
    for dimension in request.blueprint.dimensions:
        for variant in dimension.evidence_variants:
            eligible = _eligible_evidence(
                variant, request.evidence_bundle
            )
            for template_index, _template in enumerate(
                variant.question_opportunities
            ):
                template_context = next(template_contexts)
                if not eligible:
                    continue
                minimum_units = variant.evidence_requirement.min_distinct_units
                selected = [
                    eligible[(template_index + offset) % len(eligible)]
                    for offset in range(minimum_units)
                ]
                selected_aliases = list(
                    dict.fromkeys(
                        evidence_alias_by_id[item.evidence_id]
                        for item in selected
                    )
                )
                mappings.append(
                    models.EvidenceMappingRelationDraft(
                        variant_alias=variant_alias_by_id[variant.variant_id],
                        template_alias=template_context.template_alias,
                        evidence_aliases=selected_aliases,
                        support_status=models.EvidenceSupportStatus.SUFFICIENT,
                        support_type=(
                            models.EvidenceSupportType.COMPOSITE
                            if len(selected_aliases) > 1
                            else models.EvidenceSupportType.DIRECT
                        ),
                        support_description=(
                            "La evidencia localizada sustenta el aspecto "
                            "observable de esta ruta sintética."
                        ),
                    )
                )
    return models.EvidenceMappingModelDraft(
        scope_alias=envelope.scope_alias,
        mappings=mappings,
    )


def _anchor_transformation(evidence: models.EvidenceUnit) -> str:
    if evidence.structured_content is not None and evidence.modality in {
        models.EvidenceModality.TABLE,
        models.EvidenceModality.CELL_RANGE,
        models.EvidenceModality.FORMULA,
    }:
        return "TABLE_SLICE"
    if evidence.modality in {
        models.EvidenceModality.CODE_SYMBOL,
        models.EvidenceModality.CODE_SPAN,
        models.EvidenceModality.NOTEBOOK_CELL,
    }:
        return "CODE_CONTEXT"
    if evidence.modality in {
        models.EvidenceModality.IMAGE_REGION,
        models.EvidenceModality.CHART,
    }:
        return "ALT_TEXT"
    if evidence.content_text:
        return "LITERAL"
    return "TABLE_SLICE"


def _anchor_display_text(evidence: models.EvidenceUnit) -> str:
    source_text = (evidence.content_text or "").strip()
    if source_text:
        return source_text[:20_000]
    return json.dumps(
        evidence.structured_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )[:20_000]


def _guide_for_question(
    question_key: str,
    evidence_ids: list[str],
    *,
    source_ids: list[str] | None = None,
) -> models.GuideDraft:
    element_ids = [
        stable_id("observable", question_key, evidence_ids, source_ids or [], index)
        for index in range(2)
    ]
    return models.GuideDraft(
        purpose="Observar una explicación acotada a la evidencia señalada.",
        observable_elements=[
            models.ObservableElement(
                element_id=element_ids[0],
                description=(
                    "Relaciona el fragmento localizado con la respuesta sin "
                    "añadir supuestos externos."
                ),
                evidence_ids=list(evidence_ids),
                source_ids=list(source_ids or []),
            ),
            models.ObservableElement(
                element_id=element_ids[1],
                description=(
                    "Delimita qué conclusión es observable y cuál excede la evidencia."
                ),
                evidence_ids=list(evidence_ids),
                source_ids=list(source_ids or []),
            ),
        ],
        acceptable_alternatives=[
            "Puede expresar la misma relación con una formulación equivalente."
        ],
        misconceptions=[
            "Introduce una explicación que no está respaldada por el fragmento."
        ],
        levels=[
            models.GuideLevel(
                level=level,
                label=f"Nivel {level}",
                descriptor=(
                    "No establece una relación respaldada por la evidencia."
                    if level == 0
                    else "Establece la relación con precisión creciente y evidencia localizada."
                ),
                observable_element_ids=[] if level == 0 else element_ids,
            )
            for level in range(4)
        ],
        cannot_infer=[
            "No permite inferir autoría, intención ni proceso histórico de producción."
        ],
    )


def _dynamic_candidate(
    request: models.QuestionBuildRequest,
) -> models.QuestionCandidate:
    opportunity = request.opportunity
    evidence_by_id = {
        evidence.evidence_id: evidence
        for evidence in request.evidence_bundle.evidence_units
    }
    evidence_ids = [
        evidence_id
        for evidence_id in opportunity.evidence_ids
        if evidence_id in evidence_by_id
    ]
    if not evidence_ids:
        # A governed gateway rejects this request before the adapter, but keep
        # the factory total for direct tests and custom adapters.
        evidence_ids = [request.evidence_bundle.evidence_units[0].evidence_id]

    anchor_limit = min(
        request.generation_policy.max_anchor_fragments,
        len(evidence_ids),
    )
    anchor_evidence = [evidence_by_id[evidence_id] for evidence_id in evidence_ids[:anchor_limit]]
    preferred_structure = (
        models.AnchorStructure.SINGLE_FRAGMENT
        if len(anchor_evidence) == 1
        else models.AnchorStructure.PAIRED_FRAGMENTS
    )
    anchor_structure = (
        preferred_structure
        if preferred_structure in opportunity.allowed_anchor_structures
        else opportunity.allowed_anchor_structures[0]
    )
    if anchor_structure == models.AnchorStructure.SINGLE_FRAGMENT:
        anchor_evidence = anchor_evidence[:1]

    response_format = opportunity.allowed_response_formats[0]
    candidate_id = request.target_candidate_id
    choices: list[models.ChoiceOption] = []
    if response_format == models.ResponseFormat.CHOICE:
        choices = [
            models.ChoiceOption(
                option_id=stable_id("option", candidate_id, index),
                text=text,
                is_best_answer=index == 0,
                evaluator_rationale=rationale,
                misconception=None if index == 0 else misconception,
            )
            for index, (text, rationale, misconception) in enumerate(
                [
                    (
                        "La interpretación que se limita a la relación mostrada.",
                        "Es la única opción respaldada directamente por el ancla.",
                        None,
                    ),
                    (
                        "Una generalización sobre todo el proceso de producción.",
                        "Excede el alcance observable del fragmento.",
                        "Confunde evidencia localizada con una conclusión global.",
                    ),
                    (
                        "Una afirmación independiente del fragmento señalado.",
                        "No utiliza la evidencia autorizada para responder.",
                        "Trata una opinión externa como si fuera evidencia del entregable.",
                    ),
                ]
            )
        ]

    course_passages = request.evidence_bundle.course_passages
    citations = [
        models.SourceCitation(
            source_id=passage.source_id,
            locator=passage.locator.model_copy(deep=True),
            supported_claim="Aporta contexto autorizado a la relación evaluada.",
        )
        for passage in course_passages[:1]
    ]
    source_ids = [citation.source_id for citation in citations]
    question_stem = {
        models.ResponseFormat.CHOICE: (
            "¿Qué interpretación está mejor respaldada por el fragmento señalado?"
        ),
        models.ResponseFormat.STRUCTURED_BULLETS: (
            "Explica en puntos la relación observable indicada en el fragmento."
        ),
        models.ResponseFormat.ANNOTATION_OR_DIAGRAM: (
            "Representa y explica la relación observable indicada en el fragmento."
        ),
        models.ResponseFormat.ORAL_EQUIVALENT: (
            "Explica oralmente la relación observable indicada en el fragmento."
        ),
        models.ResponseFormat.OPEN_SHORT: (
            "Explica la relación observable indicada en el fragmento señalado."
        ),
    }[response_format]
    question_text = (
        f"{question_stem} Enfoca tu respuesta en: {opportunity.focus[:500]}"
    )
    return models.QuestionCandidate(
        candidate_id=candidate_id,
        submission_id=request.plan.submission_id,
        opportunity_id=opportunity.opportunity_id,
        opportunity_template_id=opportunity.opportunity_template_id,
        dimension_id=opportunity.dimension_id,
        variant_id=opportunity.variant_id,
        cognitive_operation=opportunity.cognitive_operation,
        response_format=response_format,
        difficulty=opportunity.difficulty,
        estimated_minutes=opportunity.target_minutes,
        question_text=question_text,
        anchor=models.Anchor(
            anchor_id=stable_id("anchor", candidate_id, evidence_ids),
            structure=anchor_structure,
            fragments=[
                models.AnchorFragment(
                    evidence_id=evidence.evidence_id,
                    display_text=_anchor_display_text(evidence),
                    transformation=_anchor_transformation(evidence),
                    locator=evidence.locator.model_copy(deep=True),
                )
                for evidence in anchor_evidence
            ],
            self_containment_score=0.95,
            answer_leakage_risk=0.1,
        ),
        evidence_ids=evidence_ids,
        course_source_ids=source_ids,
        citations=citations,
        choices=choices,
        student_justification_required=opportunity.student_justification_required,
        preliminary_guide=_guide_for_question(
            candidate_id,
            evidence_ids,
            source_ids=source_ids,
        ),
    )


def _dynamic_question_draft(
    request: models.QuestionBuildRequest,
) -> models.QuestionModelDraft:
    envelope = build_question_alias_envelope(request)
    support_aliases = [
        item.evidence_alias for item in envelope.support_evidence
    ]
    allowed = set(envelope.opportunity.allowed_anchor_structures)
    visible_count = 1
    if not allowed.intersection(
        {
            models.AnchorStructure.SINGLE_FRAGMENT,
            models.AnchorStructure.TABLE_OR_RANGE,
            models.AnchorStructure.CODE_CONTEXT,
            models.AnchorStructure.FIGURE_WITH_CONTEXT,
        }
    ):
        visible_count = min(2, len(support_aliases))
    response_format = envelope.opportunity.response_format
    question_text = {
        models.ResponseFormat.CHOICE: (
            "¿Qué interpretación está mejor respaldada por la evidencia señalada?"
        ),
        models.ResponseFormat.STRUCTURED_BULLETS: (
            "Explica en puntos qué función cumple la decisión localizada."
        ),
        models.ResponseFormat.ANNOTATION_OR_DIAGRAM: (
            "Representa y explica cómo funciona la decisión localizada."
        ),
        models.ResponseFormat.ORAL_EQUIVALENT: (
            "Explica oralmente qué función cumple la decisión localizada."
        ),
        models.ResponseFormat.OPEN_SHORT: (
            "Explica qué función cumple la decisión localizada y fundamenta tu respuesta."
        ),
    }[response_format]
    question_text = (
        f"{question_text} Enfoca tu respuesta en: "
        f"{envelope.opportunity.focus[:500]}"
    )
    choices: list[models.QuestionChoiceDraft] = []
    if response_format == models.ResponseFormat.CHOICE:
        choices = [
            models.QuestionChoiceDraft(
                text=text,
                is_best_answer=index == 0,
                evaluator_rationale=rationale,
                misconception=None if index == 0 else misconception,
            )
            for index, (text, rationale, misconception) in enumerate(
                [
                    (
                        "Limita el resultado a la versión vigente de la fuente.",
                        "La evidencia de soporte describe esa relación localizada.",
                        None,
                    ),
                    (
                        "Conserva cualquier resultado anterior sin volver a consultarlo.",
                        "Contradice la relación observable de la evidencia.",
                        "Confunde reutilización con validez de una versión anterior.",
                    ),
                    (
                        "Elimina la necesidad de mantener una fuente actualizada.",
                        "Añade una conclusión que el soporte no autoriza.",
                        "Generaliza una consecuencia local a todo el sistema.",
                    ),
                ]
            )
        ]
    return models.QuestionModelDraft(
        scope_alias=envelope.scope_alias,
        status="READY",
        question_text=question_text,
        visible_anchor_aliases=support_aliases[:visible_count],
        expected_observables=[
            models.QuestionObservableDraft(
                description=(
                    "Relaciona la decisión localizada con la vigencia del resultado."
                ),
                support_evidence_aliases=support_aliases,
                required_for_level_2=True,
            ),
            models.QuestionObservableDraft(
                description=(
                    "Delimita la consecuencia defendible sin agregar conocimiento externo."
                ),
                support_evidence_aliases=support_aliases,
                required_for_level_2=True,
            ),
        ],
        acceptable_alternatives=[
            "Puede expresar la misma relación con una formulación equivalente."
        ],
        misconceptions=[
            "Generaliza el efecto local más allá de la evidencia autorizada."
        ],
        choices=choices,
        semantic_uncertainties=[],
        replacement_reason=None,
    )


def _generation_result(*, enriched: bool = False) -> models.QuestionGenerationResult:
    return models.QuestionGenerationResult(
        submission_id="sub_demo",
        opportunity_id="opp_demo_1",
        context_mode=(
            models.ContextMode.COURSE_ENRICHED if enriched else models.ContextMode.CLOSED
        ),
        status="READY",
        candidate=_candidate(enriched=enriched),
    )


def _selected_question() -> models.SelectedQuestion:
    candidate = _candidate()
    return models.SelectedQuestion(
        question_id="question_demo_1",
        source_candidate_id=candidate.candidate_id,
        opportunity_id=candidate.opportunity_id,
        opportunity_template_id=candidate.opportunity_template_id,
        dimension_id=candidate.dimension_id,
        variant_id=candidate.variant_id,
        cognitive_operation=candidate.cognitive_operation,
        response_format=candidate.response_format,
        difficulty=candidate.difficulty,
        estimated_minutes=candidate.estimated_minutes,
        question_text=candidate.question_text,
        anchor=candidate.anchor,
        evidence_ids=candidate.evidence_ids,
        course_source_ids=candidate.course_source_ids,
        citations=candidate.citations,
        choices=candidate.choices,
        student_justification_required=candidate.student_justification_required,
        preliminary_guide=candidate.preliminary_guide,
        planning_score=0.91,
    )


def _assessment() -> models.Assessment:
    return models.Assessment(
        assessment_id="assessment_demo",
        tenant_id="tnt_demo",
        activity_id="act_demo",
        submission_id="sub_demo",
        subject_ref="subject_demo",
        status=models.WorkflowStatus.DRAFT,
        context_mode=models.ContextMode.CLOSED,
        assessment_plan_id="plan_demo",
        question_count=1,
        questions=[_selected_question()],
        coverage=[
            models.CoverageItem(
                dimension_id="dimension_1",
                available_variant_count=1,
                available_opportunity_count=1,
                selected_opportunity_count=1,
                evidence_unit_count=1,
            )
        ],
        structured_justification=models.StructuredJustificationSummary(
            mode=models.StructuredJustificationMode.NOT_REQUIRED,
            limited_evidence_notice_required=True,
        ),
        lineage=models.Lineage(
            assignment_prompt_hashes=[HASH_A],
            rubric_hashes=[HASH_B],
            submission_hashes=[HASH_C],
            blueprint_id="blueprint_demo",
            blueprint_version=1,
            parser_versions={"text": "mock-parser/1"},
            # This fixture lineage is part of previously observed real input
            # bundles. Keep the historical pack marker stable when unrelated
            # prompt entries advance.
            prompt_versions={"pack": "1.1.5"},
            model_snapshots={"mock": "deterministic-mock-v1"},
            policy_hash=HASH_D,
            planner_version="mock-planner/1",
            renderer_version="mock-renderer/1",
        ),
        created_at=FIXED_TIME,
    )


def build_mock_request(prompt_id: str) -> BaseModel:
    """Build a valid, self-contained request root for one prompt."""

    if prompt_id == "P01_ACTIVITY_SPEC_V1":
        return models.ActivitySpecRequest(
            activity_config=_activity_config(), prompt_evidence=[_assignment_evidence()]
        )
    if prompt_id == "P02_RUBRIC_NORMALIZE_V1":
        return models.RubricNormalizeRequest(
            activity_spec=_activity_spec(), rubric_evidence=[_rubric_evidence()]
        )
    if prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
        return models.AmbiguityTriageRequest(
            activity_spec=_activity_spec(), rubric_spec=_rubric_spec()
        )
    if prompt_id == "P04_BLUEPRINT_BUILD_V1":
        return models.BlueprintBuildRequest(
            target_blueprint_id="blueprint_demo",
            target_blueprint_version=1,
            activity_spec=_activity_spec(),
            rubric_spec=_rubric_spec(),
            resolved_decisions=[_policy_decision()],
            blueprint_policy=_blueprint_policy(),
        )
    if prompt_id == "P05_BLUEPRINT_REVIEW_V1":
        from comprehension_verification.validation import (
            build_blueprint_review_preflight,
        )

        blueprint = _blueprint()
        activity_spec = _activity_spec()
        rubric_spec = _rubric_spec()
        blueprint_policy = _blueprint_policy()
        return models.BlueprintReviewRequest(
            blueprint=blueprint,
            activity_spec=activity_spec,
            rubric_spec=rubric_spec,
            resolved_decisions=[_policy_decision()],
            blueprint_policy=blueprint_policy,
            deterministic_preflight=build_blueprint_review_preflight(
                blueprint=blueprint,
                activity_spec=activity_spec,
                rubric_spec=rubric_spec,
                blueprint_policy=blueprint_policy,
            ),
        )
    if prompt_id == "P06_EVIDENCE_MAP_V1":
        return models.EvidenceMapRequest(
            blueprint=_blueprint(),
            planning_policy=_blueprint_policy().planning_policy,
            evidence_bundle=_evidence_bundle(),
        )
    if prompt_id in {"P07_QUESTION_BUILD_V1", "P10_ENRICHED_CONTEXT_V1"}:
        enriched = prompt_id == "P10_ENRICHED_CONTEXT_V1"
        return models.QuestionBuildRequest(
            target_candidate_id="candidate_demo_1",
            plan=_plan(),
            opportunity=_opportunity(),
            evidence_bundle=_evidence_bundle(enriched=enriched),
            generation_policy=models.QuestionGenerationPolicy(
                policy_id="generation_policy_1"
            ),
        )
    if prompt_id == "P08_QUESTION_REVIEW_V1":
        return models.QuestionReviewRequest(
            generation_result=_generation_result(),
            opportunity=_opportunity(),
            evidence_bundle=_evidence_bundle(),
            validation_policy=models.QuestionValidationPolicy(
                policy_id="validation_policy_1"
            ),
        )
    if prompt_id == "P09_GUIDE_BUILD_V1":
        return models.GuideBuildRequest(
            guide_id="guide_demo", assessment=_assessment(), evidence_bundle=_evidence_bundle()
        )
    if prompt_id == "P11_SCHEMA_REPAIR_V1":
        invalid = _activity_spec().model_dump(mode="json")
        invalid["unexpected_field"] = "remove structurally"
        return models.SchemaRepairRequest(
            target_schema_name="ActivitySpec",
            invalid_output=invalid,
            validation_issues=[
                models.SchemaValidationIssue(
                    path="/unexpected_field",
                    error_type="extra_forbidden",
                    message="Extra inputs are not permitted",
                )
            ],
        )
    raise ValueError(f"No mock request factory for {prompt_id}")


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def build_trusted_context(request: BaseModel) -> models.TrustedPromptContext:
    """Derive the allowlist metadata for synthetic tests, never production input."""

    data = request.model_dump(mode="json")
    objects = list(_walk(data))

    def first(key: str, default: Any = None) -> Any:
        return next((obj[key] for obj in objects if obj.get(key) is not None), default)

    evidence_ids: set[str] = set()
    source_ids: set[str] = set()
    for obj in objects:
        if isinstance(obj.get("evidence_id"), str):
            evidence_ids.add(obj["evidence_id"])
        evidence_ids.update(
            value for value in obj.get("evidence_ids", []) if isinstance(value, str)
        )
        if isinstance(obj.get("source_id"), str):
            source_ids.add(obj["source_id"])
        source_ids.update(
            value for value in obj.get("source_ids", []) if isinstance(value, str)
        )
        source_ids.update(
            value for value in obj.get("course_source_ids", []) if isinstance(value, str)
        )

    mode = first("context_mode", models.ContextMode.CLOSED)
    return models.TrustedPromptContext(
        tenant_id=first("tenant_id", "tnt_demo"),
        activity_id=first("activity_id", "act_demo"),
        submission_id=first("submission_id"),
        blueprint_id=first("blueprint_id", first("target_blueprint_id")),
        blueprint_version=first(
            "blueprint_version", first("target_blueprint_version")
        ),
        allowed_evidence_ids=sorted(evidence_ids),
        allowed_course_source_ids=sorted(source_ids) if mode == "COURSE_ENRICHED" else [],
        output_language=first("output_language", "es-CL"),
        context_mode=mode,
        data_classification="SYNTHETIC_ONLY_NO_STUDENT_DATA",
        attestation_id=stable_id("attestation", canonical_hash(data)),
        attested_input_hash=canonical_hash(data),
        attested_artifact_hashes=sorted(
            {
                value
                for obj in objects
                for key, value in obj.items()
                if key in {"artifact_hash", "sha256"}
                and isinstance(value, str)
                and value.startswith("sha256:")
            }
        ),
    )


class DeterministicMockFactory:
    """Produces canonical outputs from canonical inputs without external calls."""

    def output_for(
        self, prompt_id: str, request: BaseModel, behavior: MockBehavior
    ) -> BaseModel:
        if behavior == MockBehavior.ABSTAIN:
            return self._abstention(prompt_id, request)
        return self._happy(prompt_id, request)

    def _happy(self, prompt_id: str, request: BaseModel) -> BaseModel:
        if prompt_id == "P01_ACTIVITY_SPEC_V1":
            evidence_id = request.prompt_evidence[0].evidence_id
            activity_id = request.activity_config.activity_id
            return models.ActivitySpec(
                activity_id=activity_id,
                status=models.WorkflowStatus.READY,
                learning_outcomes=[
                    models.SourcedStatement(
                        statement_id=stable_id("outcome", activity_id, evidence_id),
                        text="Explicar un mecanismo localizado.",
                        evidence_ids=[evidence_id],
                    )
                ],
                expected_products=[
                    models.SourcedStatement(
                        statement_id=stable_id("product", activity_id, evidence_id),
                        text="Un entregable explicativo.",
                        evidence_ids=[evidence_id],
                    )
                ],
                requirements=[
                    models.SourcedStatement(
                        statement_id=stable_id("requirement", activity_id, evidence_id),
                        text="Justificar una consecuencia local.",
                        evidence_ids=[evidence_id],
                    )
                ],
            )
        if prompt_id == "P02_RUBRIC_NORMALIZE_V1":
            evidence_id = request.rubric_evidence[0].evidence_id
            rubric = _rubric_spec()
            criterion = rubric.criteria[0].model_copy(
                update={
                    "evidence_ids": [evidence_id],
                    "levels": [
                        rubric.criteria[0].levels[0].model_copy(
                            update={"evidence_ids": [evidence_id]}
                        )
                    ],
                }
            )
            return rubric.model_copy(
                update={"activity_id": request.activity_spec.activity_id, "criteria": [criterion]}
            )
        if prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
            return models.AmbiguityReport(
                activity_id=request.activity_spec.activity_id, issues=[], blocked=False
            )
        if prompt_id == "P04_BLUEPRINT_BUILD_V1":
            return _dynamic_blueprint_draft(request)
        if prompt_id == "P05_BLUEPRINT_REVIEW_V1":
            blueprint = request.blueprint
            from comprehension_verification.validation import (
                blueprint_review_preflight_expected_checks,
            )

            deterministic_checks = blueprint_review_preflight_expected_checks(
                request.deterministic_preflight
            )
            approved = not any(
                critical
                for _status, critical in deterministic_checks.values()
            )

            def deterministic_check(
                category: str,
            ) -> tuple[models.ReviewCheckStatus, bool]:
                return deterministic_checks[category]

            time_status, time_critical = deterministic_check("TIME")
            format_status, format_critical = deterministic_check(
                "FORMAT_FEASIBILITY"
            )
            catalog_status, catalog_critical = deterministic_check(
                "OPPORTUNITY_CATALOG"
            )
            plan_status, plan_critical = deterministic_check(
                "PLAN_FEASIBILITY"
            )
            coverage_status, coverage_critical = deterministic_check(
                "COVERAGE"
            )
            return models.BlueprintReview(
                activity_id=request.activity_spec.activity_id,
                blueprint_id=blueprint.blueprint_id,
                blueprint_version=blueprint.blueprint_version,
                status="READY",
                approval_recommendation=("APPROVE" if approved else "REJECT"),
                checks=[
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_CONSTRUCT",
                        category="CONSTRUCT",
                        status="PASS",
                        message="El catálogo representa el constructo declarado.",
                        referenced_ids=[blueprint.blueprint_id],
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_SOURCE_FIDELITY",
                        category="SOURCE_FIDELITY",
                        status="PASS",
                        message="El catálogo conserva la frontera de evidencia.",
                        referenced_ids=[blueprint.blueprint_id],
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_CONCEPTUAL_COVERAGE",
                        category="COVERAGE",
                        status=coverage_status,
                        message=(
                            "Las dimensiones cubren conceptualmente las fuentes; "
                            "la selección exacta pertenece al planificador."
                        ),
                        referenced_ids=[blueprint.blueprint_id],
                        critical=coverage_critical,
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_CATALOG_DIVERSITY",
                        category="COMPARABILITY",
                        status="PASS",
                        message=(
                            "La diversidad entre oportunidades conserva una "
                            "calibración auditable."
                        ),
                        referenced_ids=[blueprint.blueprint_id],
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_COGNITIVE_DEMAND",
                        category="COGNITIVE_DEMAND",
                        status="PASS",
                        message="Las operaciones declaran una demanda cognitiva verificable.",
                        referenced_ids=[blueprint.blueprint_id],
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_TIME",
                        category="TIME",
                        status=time_status,
                        message="El catálogo conserva el límite temporal confiable.",
                        referenced_ids=[blueprint.blueprint_id],
                        critical=time_critical,
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_FORMAT_FEASIBILITY",
                        category="FORMAT_FEASIBILITY",
                        status=format_status,
                        message="Los formatos pertenecen a la política confiable.",
                        referenced_ids=[blueprint.blueprint_id],
                        critical=format_critical,
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_OPPORTUNITY_CATALOG",
                        category="OPPORTUNITY_CATALOG",
                        status=catalog_status,
                        message=(
                            "El catálogo contiene suficientes oportunidades "
                            "independientemente del número solicitado."
                            if catalog_status == models.ReviewCheckStatus.PASS
                            else "El catálogo no contiene suficientes oportunidades."
                        ),
                        referenced_ids=[blueprint.blueprint_id],
                        correction=(
                            None
                            if catalog_status == models.ReviewCheckStatus.PASS
                            else "Regenerar suficientes oportunidades elegibles."
                        ),
                        critical=catalog_critical,
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_PLAN_FEASIBILITY",
                        category="PLAN_FEASIBILITY",
                        status=plan_status,
                        message=(
                            "El catálogo contiene suficientes oportunidades y "
                            "conserva las restricciones configuradas."
                            if plan_status == models.ReviewCheckStatus.PASS
                            else "El catálogo o sus restricciones no permiten el plan solicitado."
                        ),
                        referenced_ids=[blueprint.blueprint_id],
                        correction=(
                            None
                            if plan_status == models.ReviewCheckStatus.PASS
                            else "Regenerar el catálogo desde la política vigente."
                        ),
                        critical=plan_critical,
                    ),
                    models.BlueprintReviewCheck(
                        check_code="BLUEPRINT_ACCESSIBILITY",
                        category="ACCESSIBILITY",
                        status="PASS",
                        message="Las alternativas del catálogo conservan una forma accesible.",
                        referenced_ids=[blueprint.blueprint_id],
                    ),
                ],
            )
        if prompt_id == "P06_EVIDENCE_MAP_V1":
            return _dynamic_evidence_map(request)
        if prompt_id == "P07_QUESTION_BUILD_V1":
            return _dynamic_question_draft(request)
        if prompt_id == "P10_ENRICHED_CONTEXT_V1":
            candidate = _dynamic_candidate(request)
            return models.QuestionGenerationResult(
                submission_id=request.plan.submission_id,
                opportunity_id=request.opportunity.opportunity_id,
                context_mode=request.evidence_bundle.context_mode,
                status="READY",
                candidate=candidate,
            )
        if prompt_id == "P08_QUESTION_REVIEW_V1":
            candidate = request.generation_result.candidate
            if candidate is None:
                return models.QuestionReviewResult(
                    submission_id=request.evidence_bundle.submission_id,
                    opportunity_id=request.opportunity.opportunity_id,
                    status="NEEDS_REVIEW",
                    diagnostics=[
                        _diagnostic(
                            "QUESTION_REVIEW_UNCERTAIN",
                            "No existe una candidata utilizable que revisar.",
                            evidence_ids=list(request.opportunity.evidence_ids),
                        )
                    ],
                )
            return models.QuestionReviewResult(
                submission_id=request.evidence_bundle.submission_id,
                opportunity_id=request.opportunity.opportunity_id,
                status="READY",
                review=models.QuestionSemanticReview(
                    candidate_id=candidate.candidate_id,
                    decision=models.ReviewDecision.ACCEPT,
                    scores=models.QuestionScores(
                        groundedness=0.98,
                        anchor_sufficiency=0.95,
                        criterion_relevance=0.9,
                        answerability=0.95,
                        cognitive_demand=0.85,
                        submission_specificity=0.95,
                        clarity=0.95,
                        accessibility=0.95,
                        discriminative_potential=0.85,
                        guide_observability=0.9,
                    ),
                    estimated_difficulty=candidate.difficulty,
                    estimated_minutes=candidate.estimated_minutes,
                    confidence=0.95,
                    justifications=["La pregunta se resuelve desde la evidencia permitida."],
                    evidence_ids=list(candidate.evidence_ids),
                    source_ids=list(candidate.course_source_ids),
                ),
            )
        if prompt_id == "P09_GUIDE_BUILD_V1":
            if not request.assessment.questions:
                return models.EvaluationGuide(
                    guide_id=request.guide_id,
                    assessment_id=request.assessment.assessment_id,
                    submission_id=request.assessment.submission_id,
                    status="NEEDS_REVIEW",
                    diagnostics=[
                        _diagnostic(
                            "GUIDE_UNSUPPORTED",
                            "La evaluación no contiene preguntas utilizables.",
                        )
                    ],
                    created_at=FIXED_TIME,
                )
            return models.EvaluationGuide(
                guide_id=request.guide_id,
                assessment_id=request.assessment.assessment_id,
                submission_id=request.assessment.submission_id,
                status="READY",
                items=[
                    models.EvaluationGuideItem(
                        question_id=question.question_id,
                        guide=_guide_for_question(
                            question.question_id,
                            list(question.evidence_ids),
                            source_ids=list(question.course_source_ids),
                        ),
                    )
                    for question in request.assessment.questions
                ],
                created_at=FIXED_TIME,
            )
        if prompt_id == "P11_SCHEMA_REPAIR_V1":
            return self._repair(request)
        raise ValueError(f"No happy mock for {prompt_id}")

    def _abstention(self, prompt_id: str, request: BaseModel) -> BaseModel:
        if prompt_id == "P01_ACTIVITY_SPEC_V1":
            return models.ActivitySpec(
                activity_id=request.activity_config.activity_id,
                status=models.WorkflowStatus.BLOCKED,
                diagnostics=[
                    _diagnostic(
                        "ASSIGNMENT_FIELD_MISSING",
                        "La consigna sintética no permite extraer los campos requeridos.",
                    )
                ],
            )
        if prompt_id == "P02_RUBRIC_NORMALIZE_V1":
            return models.RubricSpec(
                activity_id=request.activity_spec.activity_id,
                status=models.WorkflowStatus.BLOCKED,
                criteria=[],
                diagnostics=[
                    _diagnostic(
                        "RUBRIC_UNPARSABLE",
                        "La rúbrica sintética no admite normalización fiel.",
                    )
                ],
            )
        if prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
            evidence_ids = [
                evidence_id
                for collection in (
                    request.activity_spec.learning_outcomes,
                    request.activity_spec.expected_products,
                    request.activity_spec.requirements,
                )
                for statement in collection
                for evidence_id in statement.evidence_ids
            ]
            return models.AmbiguityReport(
                activity_id=request.activity_spec.activity_id,
                blocked=True,
                issues=[
                    models.AmbiguityIssue(
                        issue_id="issue_demo_1",
                        issue_code="ASSIGNMENT_AMBIGUOUS",
                        severity=models.Severity.ERROR,
                        evidence_ids=list(dict.fromkeys(evidence_ids))[:100],
                        explanation="La decisión académica requiere confirmación docente.",
                        options=[
                            models.DecisionOption(
                                option_id="option_a",
                                label="Mantener alcance",
                                consequence="Conserva el alcance textual.",
                            ),
                            models.DecisionOption(
                                option_id="option_b",
                                label="Acotar alcance",
                                consequence="Reduce las dimensiones evaluables.",
                            ),
                        ],
                        recommended_option_id="option_a",
                        blocking=True,
                    )
                ],
            )
        if prompt_id == "P04_BLUEPRINT_BUILD_V1":
            draft = _dynamic_blueprint_draft(request)
            return draft.model_copy(
                update={
                    "question_opportunities": [
                        item.model_copy(update={"target_minutes": 60})
                        for item in draft.question_opportunities
                    ]
                }
            )
        if prompt_id == "P05_BLUEPRINT_REVIEW_V1":
            return models.BlueprintReview(
                activity_id=request.activity_spec.activity_id,
                blueprint_id=request.blueprint.blueprint_id,
                blueprint_version=request.blueprint.blueprint_version,
                status="NEEDS_REVIEW",
                approval_recommendation=None,
                diagnostics=[
                    _diagnostic(
                        "BLUEPRINT_REVIEW_UNCERTAIN",
                        "El revisor no puede emitir scores defendibles.",
                    )
                ],
            )
        if prompt_id == "P06_EVIDENCE_MAP_V1":
            envelope = build_evidence_mapping_alias_envelope(request)
            return models.EvidenceMappingModelDraft(
                scope_alias=envelope.scope_alias,
                mappings=[
                    models.EvidenceMappingRelationDraft(
                        variant_alias=envelope.variants[0].variant_alias,
                        template_alias=envelope.templates[0].template_alias,
                        evidence_aliases=[
                            envelope.evidence_units[0].evidence_alias
                        ],
                        support_status=models.EvidenceSupportStatus.UNCERTAIN,
                        support_type=None,
                        support_description=(
                            "La relación sintética no puede resolverse con fidelidad."
                        ),
                        semantic_uncertainty=(
                            "La evidencia admite más de una interpretación local."
                        ),
                        abstention_reason=(
                            "No existe base suficiente para declarar soporte."
                        ),
                    )
                ],
            )
        if prompt_id == "P07_QUESTION_BUILD_V1":
            envelope = build_question_alias_envelope(request)
            return models.QuestionModelDraft(
                scope_alias=envelope.scope_alias,
                status="REPLACEMENT_REQUIRED",
                semantic_uncertainties=[
                    "La evidencia no permite resolver el observable con fidelidad."
                ],
                replacement_reason=(
                    "La oportunidad no admite una pregunta grounded dentro del soporte autorizado."
                ),
            )
        if prompt_id == "P10_ENRICHED_CONTEXT_V1":
            return models.QuestionGenerationResult(
                submission_id=request.plan.submission_id,
                opportunity_id=request.opportunity.opportunity_id,
                context_mode=request.evidence_bundle.context_mode,
                status="REPLACEMENT_REQUIRED",
                candidate=None,
                diagnostics=[
                    _diagnostic(
                        "QUESTION_GROUNDEDNESS_FAIL",
                        "La oportunidad no admite una pregunta grounded.",
                        evidence_ids=list(request.opportunity.evidence_ids),
                    )
                ],
            )
        if prompt_id == "P08_QUESTION_REVIEW_V1":
            return models.QuestionReviewResult(
                submission_id=request.evidence_bundle.submission_id,
                opportunity_id=request.opportunity.opportunity_id,
                status="NEEDS_REVIEW",
                review=None,
                diagnostics=[
                    _diagnostic(
                        "QUESTION_REVIEW_UNCERTAIN",
                        "La evidencia es genuinamente ambigua.",
                        evidence_ids=list(request.opportunity.evidence_ids),
                    )
                ],
            )
        if prompt_id == "P09_GUIDE_BUILD_V1":
            return models.EvaluationGuide(
                guide_id=request.guide_id,
                assessment_id=request.assessment.assessment_id,
                submission_id=request.assessment.submission_id,
                status="NEEDS_REVIEW",
                items=[],
                diagnostics=[
                    _diagnostic(
                        "GUIDE_UNSUPPORTED",
                        "No se puede construir una guía observable completa.",
                    )
                ],
                created_at=FIXED_TIME,
            )
        if prompt_id == "P11_SCHEMA_REPAIR_V1":
            return models.SchemaRepairResult(
                target_schema_name=request.target_schema_name,
                repair_status=models.RepairStatus.UNREPAIRABLE,
                repaired_output=None,
                diagnostics=[
                    _diagnostic(
                        "MODEL_SCHEMA_VIOLATION",
                        "La reparación exigiría inventar contenido semántico.",
                    )
                ],
            )
        raise ValueError(f"No abstention mock for {prompt_id}")

    def _repair(self, request: models.SchemaRepairRequest) -> models.SchemaRepairResult:
        raw = request.invalid_output
        if not isinstance(raw, dict):
            return self._abstention("P11_SCHEMA_REPAIR_V1", request)
        try:
            target_model = model_by_name(request.target_schema_name)
        except ValueError:
            return self._abstention("P11_SCHEMA_REPAIR_V1", request)
        repaired = deepcopy(raw)
        allowed_fields = set(target_model.model_fields)
        for key in list(repaired):
            if key not in allowed_fields:
                repaired.pop(key)
        try:
            validated = target_model.model_validate(repaired)
        except ValidationError:
            return self._abstention("P11_SCHEMA_REPAIR_V1", request)
        return models.SchemaRepairResult(
            target_schema_name=request.target_schema_name,
            repair_status=models.RepairStatus.REPAIRED,
            repaired_output=validated.model_dump(mode="json"),
        )


class DeterministicMockAdapter:
    """No-network adapter with deterministic behavior selected by the caller."""

    def __init__(self, factory: DeterministicMockFactory | None = None) -> None:
        self.factory = factory or DeterministicMockFactory()

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
        del route  # Mocks never inspect provider transport secrets.
        if behavior == MockBehavior.TIMEOUT:
            # Cancellation by asyncio.timeout/wait_for is the expected exit.
            await asyncio.sleep(3_600)
        output = self.factory.output_for(prompt_id, request, behavior)
        raw: Any = output.model_dump(mode="json")
        if behavior == MockBehavior.INVALID_ONCE and attempt == 1:
            raw = deepcopy(raw)
            raw["unexpected_field"] = "structural-only"
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        # Preserve historical mock accounting for unchanged prompts. P06/P07
        # count their reduced alias-only wire envelopes because those are now
        # the payloads actually sent to the provider boundary.
        request_bytes = (
            envelope.model_dump_json().encode("utf-8")
            if prompt_id in {
                "P06_EVIDENCE_MAP_V1",
                "P07_QUESTION_BUILD_V1",
            }
            else request.model_dump_json().encode("utf-8")
        )
        return AdapterResult(
            raw_output=raw,
            input_tokens=max(1, len(request_bytes) // 4),
            cached_input_tokens=0,
            output_tokens=max(1, len(encoded) // 4),
        )
