from __future__ import annotations

from datetime import datetime, timezone

from comprehension_verification.canonical import sha256_text
from comprehension_verification.contracts import models as m


NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def evidence_unit(
    index: int = 1,
    *,
    tenant_id: str = "tnt_test",
    submission_id: str = "sub_test",
    content: str | None = None,
) -> m.EvidenceUnit:
    text = content or f"Fragmento verificable {index}: decisión local y consecuencia {index}."
    return m.EvidenceUnit(
        evidence_id=f"ev_test_{index}",
        tenant_id=tenant_id,
        submission_id=submission_id,
        artifact_id="art_test",
        artifact_hash="sha256:" + "a" * 64,
        source_role=m.ArtifactRole.SUBMISSION,
        modality=m.EvidenceModality.PARAGRAPH,
        locator=m.DocumentLocator(paragraph_index=index - 1, heading_path=["Análisis"]),
        content_text=text,
        structured_content={"line_start": index, "line_end": index},
        language="es",
        extraction_confidence=1.0,
        normalized_hash=sha256_text(text),
    )


def evidence_bundle(count: int = 8) -> m.EvidenceBundle:
    units = [evidence_unit(index) for index in range(1, count + 1)]
    return m.EvidenceBundle(
        bundle_id="bundle_test",
        tenant_id="tnt_test",
        activity_id="act_test",
        submission_id="sub_test",
        context_mode=m.ContextMode.CLOSED,
        allowed_evidence_ids=[item.evidence_id for item in units],
        evidence_units=units,
        course_passages=[],
    )


def planning_policy(**overrides: object) -> m.AssessmentPlanningPolicy:
    data: dict[str, object] = {
        "policy_id": "policy_plan_test",
        "minimum_opportunity_quality": 0.75,
        "minimum_evidence_fit": 0.7,
        "max_reserve_opportunities": 2,
    }
    data.update(overrides)
    return m.AssessmentPlanningPolicy.model_validate(data)


def blueprint(
    *,
    question_count: int = 3,
    target_total_minutes: int = 12,
    opportunity_count: int = 8,
    opportunity_minutes: int = 3,
) -> m.AssessmentBlueprint:
    templates = [
        m.QuestionOpportunityTemplate(
            opportunity_template_id=f"opt_test_{index}",
            cognitive_operation=(
                m.CognitiveOperation.EXPLAIN_MECHANISM
                if index % 2
                else m.CognitiveOperation.PREDICT_LOCAL_CONSEQUENCE
            ),
            focus=f"Foco verificable {index}",
            observable=f"Explica la relación localizada {index}",
            difficulty=m.DifficultyBand.MEDIUM,
            target_minutes=opportunity_minutes,
            allowed_anchor_structures=[m.AnchorStructure.SINGLE_FRAGMENT],
            allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
            verification_potential=0.9,
            minimum_quality=0.75,
            student_justification_required=False,
        )
        for index in range(1, opportunity_count + 1)
    ]
    variant = m.EvidenceVariant(
        variant_id="variant_test",
        name="Explicación localizada",
        description="Fragmentos con una decisión y una consecuencia observables.",
        evidence_requirement=m.EvidenceRequirement(
            allowed_modalities=[m.EvidenceModality.PARAGRAPH],
            min_distinct_units=1,
            min_extraction_confidence=0.75,
            min_alignment=0.65,
        ),
        verification_potential=0.9,
        supported_operations=[
            m.SupportedOperation(
                cognitive_operation=m.CognitiveOperation.EXPLAIN_MECHANISM,
                support_strength=0.95,
                rationale="El mecanismo está explícito en evidencia localizada.",
            ),
            m.SupportedOperation(
                cognitive_operation=m.CognitiveOperation.PREDICT_LOCAL_CONSEQUENCE,
                support_strength=0.9,
                rationale="La relación local permite derivar una consecuencia.",
            ),
        ],
        question_opportunities=templates,
    )
    dimension = m.BlueprintDimension(
        dimension_id="dimension_test",
        name="Comprensión del mecanismo",
        criterion_ids=["criterion_test"],
        learning_outcome_ids=["outcome_test"],
        verification_priority=0.9,
        factors=m.VerificationFactors(
            learning_relevance=0.9,
            centrality=0.9,
            expected_evidence=0.9,
            discriminative_potential=0.9,
            auditability=0.9,
            short_response_observability=0.9,
        ),
        justification="Dimensión central y auditable.",
        evidence_variants=[variant],
    )
    return m.AssessmentBlueprint(
        blueprint_id="blueprint_test",
        blueprint_version=1,
        activity_id="act_test",
        status=m.WorkflowStatus.APPROVED,
        context_mode=m.ContextMode.CLOSED,
        dimensions=[dimension],
        assessment_constraints=m.AssessmentConstraints(
            question_count=question_count,
            target_total_minutes=target_total_minutes,
            allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
            minimum_opportunity_quality=0.75,
            max_reserve_opportunities=2,
            structured_justification_policy=m.StructuredJustificationPolicy(
                mode=m.StructuredJustificationMode.NOT_REQUIRED
            ),
        ),
        decision_ids=[],
        diagnostics=[],
        approved_by="usr_fixture",
        approved_at=NOW,
    )


def evidence_map(
    bp: m.AssessmentBlueprint | None = None,
    bundle: m.EvidenceBundle | None = None,
    *,
    opportunity_count: int | None = None,
    quality: float = 0.9,
    evidence_fit: float = 0.9,
) -> m.EvidenceMapPatch:
    bp = bp or blueprint()
    bundle = bundle or evidence_bundle()
    variant = bp.dimensions[0].evidence_variants[0]
    templates = variant.question_opportunities
    count = opportunity_count if opportunity_count is not None else len(templates)
    opportunities = []
    for index, template in enumerate(templates[:count], start=1):
        evidence = bundle.evidence_units[(index - 1) % len(bundle.evidence_units)]
        opportunities.append(
            m.QuestionOpportunity(
                opportunity_id=f"opp_test_{index}",
                opportunity_template_id=template.opportunity_template_id,
                submission_id=bundle.submission_id,
                dimension_id=bp.dimensions[0].dimension_id,
                variant_id=variant.variant_id,
                evidence_ids=[evidence.evidence_id],
                cognitive_operation=template.cognitive_operation,
                focus=template.focus,
                observable=template.observable,
                difficulty=template.difficulty,
                target_minutes=template.target_minutes,
                allowed_anchor_structures=template.allowed_anchor_structures,
                allowed_response_formats=template.allowed_response_formats,
                activity_priority=bp.dimensions[0].verification_priority,
                evidence_fit=evidence_fit,
                opportunity_quality=quality,
                student_justification_required=template.student_justification_required,
            )
        )
    return m.EvidenceMapPatch(
        submission_id=bundle.submission_id,
        status="READY",
        claims=[],
        variant_matches=[
            m.EvidenceVariantMatch(
                dimension_id=bp.dimensions[0].dimension_id,
                variant_id=variant.variant_id,
                evidence_ids=[item.evidence_ids[0] for item in opportunities],
                evidence_fit=evidence_fit,
                mapping_confidence=0.95,
                justification="Mapeo sintético explícito y localizado.",
            )
        ],
        opportunities=opportunities,
        diagnostics=[],
    )


def failed_map(status: str) -> m.EvidenceMapPatch:
    from comprehension_verification.diagnostics import diagnostic

    return m.EvidenceMapPatch(
        submission_id="sub_test",
        status=status,
        claims=[],
        variant_matches=[],
        opportunities=[],
        diagnostics=[diagnostic(status, "El mapeo sintético se abstuvo de forma completa.")],
    )


def assessment_and_guide() -> tuple[m.Assessment, m.EvaluationGuide]:
    evidence = evidence_unit(
        1,
        content="Fragmento hostil visible: <script>alert('dato')</script> y una decisión local.",
    )
    guide_draft = m.GuideDraft(
        purpose="Propósito reservado al evaluador.",
        observable_elements=[
            m.ObservableElement(
                element_id="element_export",
                description="Explica la consecuencia de la decisión local.",
                evidence_ids=[evidence.evidence_id],
            )
        ],
        acceptable_alternatives=["Una formulación causal equivalente."],
        misconceptions=["Confunde causa y consecuencia."],
        levels=[
            m.GuideLevel(
                level=level,
                label=f"Nivel {level}",
                descriptor=f"Descriptor observable {level}.",
                observable_element_ids=[] if level == 0 else ["element_export"],
            )
            for level in range(4)
        ],
        cannot_infer=["No permite inferir un proceso histórico."],
    )
    selected = m.SelectedQuestion(
        question_id="question_export",
        source_candidate_id="candidate_export",
        opportunity_id="opp_export",
        opportunity_template_id="opt_export",
        dimension_id="dimension_export",
        variant_id="variant_export",
        cognitive_operation=m.CognitiveOperation.EXPLAIN_MECHANISM,
        response_format=m.ResponseFormat.CHOICE,
        difficulty=m.DifficultyBand.MEDIUM,
        estimated_minutes=3,
        question_text="¿Qué relación local explica mejor el fragmento?",
        anchor=m.Anchor(
            anchor_id="anchor_export",
            structure=m.AnchorStructure.SINGLE_FRAGMENT,
            fragments=[
                m.AnchorFragment(
                    evidence_id=evidence.evidence_id,
                    display_text=evidence.content_text,
                    transformation="LITERAL",
                    locator=evidence.locator,
                )
            ],
            self_containment_score=0.95,
            answer_leakage_risk=0.1,
        ),
        evidence_ids=[evidence.evidence_id],
        choices=[
            m.ChoiceOption(
                option_id="option_best",
                text="La decisión produce la consecuencia localizada.",
                is_best_answer=True,
                evaluator_rationale="Razonamiento secreto del evaluador.",
            ),
            m.ChoiceOption(
                option_id="option_wrong_a",
                text="No existe ninguna relación.",
                is_best_answer=False,
                evaluator_rationale="La evidencia sí expresa una relación.",
                misconception="Omite la dependencia explícita.",
            ),
            m.ChoiceOption(
                option_id="option_wrong_b",
                text="La consecuencia ocurre antes de la decisión.",
                is_best_answer=False,
                evaluator_rationale="Invierte la relación localizada.",
                misconception="Invierte causa y consecuencia.",
            ),
        ],
        student_justification_required=False,
        preliminary_guide=guide_draft,
        planning_score=0.9,
    )
    assessment = m.Assessment(
        assessment_id="assessment_export",
        tenant_id="tnt_test",
        activity_id="act_test",
        submission_id="sub_test",
        subject_ref="subject_test",
        status=m.WorkflowStatus.NEEDS_REVIEW,
        context_mode=m.ContextMode.CLOSED,
        assessment_plan_id="plan_export",
        question_count=1,
        questions=[selected],
        coverage=[
            m.CoverageItem(
                dimension_id="dimension_export",
                available_variant_count=1,
                available_opportunity_count=3,
                selected_opportunity_count=1,
                evidence_unit_count=1,
            )
        ],
        structured_justification=m.StructuredJustificationSummary(
            mode=m.StructuredJustificationMode.NOT_REQUIRED,
            required_question_ids=[],
            limited_evidence_notice_required=True,
        ),
        diagnostics=[],
        lineage=m.Lineage(
            assignment_prompt_hashes=["sha256:" + "a" * 64],
            rubric_hashes=[],
            submission_hashes=["sha256:" + "b" * 64],
            blueprint_id="blueprint_test",
            blueprint_version=1,
            parser_versions={"markdown": "stage0-parser/1.0.0"},
            prompt_versions={"P01_ACTIVITY_SPEC_V1": "1.1.0"},
            schema_version="1.1.0",
            model_snapshots={"mock": "deterministic-mock-v1"},
            policy_hash="sha256:" + "c" * 64,
            planner_version="stage0-planner/1.0.0",
            renderer_version="stage0-renderer/1.0.0",
        ),
        created_at=NOW,
    )
    guide = m.EvaluationGuide(
        guide_id="guide_export",
        assessment_id=assessment.assessment_id,
        submission_id=assessment.submission_id,
        status="READY",
        items=[
            m.EvaluationGuideItem(question_id=selected.question_id, guide=guide_draft)
        ],
        diagnostics=[],
        created_at=NOW,
    )
    return assessment, guide

