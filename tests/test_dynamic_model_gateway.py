from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from comprehension_verification.canonical import sha256_text
from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import (
    GatewayConfig,
    ModelGateway,
    build_trusted_context,
)
from comprehension_verification.planning import build_assessment_plan
from comprehension_verification.validation import (
    validate_evaluation_guide,
    validate_evidence_map,
    validate_generation_result,
    validate_review_result,
)


FIXED_TIME = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
FIXED_HASH = "sha256:" + "f" * 64


def _invoke(prompt_id: str, request):
    gateway = ModelGateway(GatewayConfig(clock=lambda: FIXED_TIME))
    return asyncio.run(
        gateway.invoke(prompt_id, request, build_trusted_context(request))
    ).output


def _assignment_evidence() -> m.EvidenceUnit:
    text = "Analiza una decisión del entregable y explica sus consecuencias locales."
    return m.EvidenceUnit(
        evidence_id="ev_assignment_custom",
        tenant_id="tnt_custom",
        artifact_id="art_assignment_custom",
        artifact_hash=FIXED_HASH,
        source_role=m.ArtifactRole.ASSIGNMENT_PROMPT,
        modality=m.EvidenceModality.PARAGRAPH,
        locator=m.DocumentLocator(paragraph_index=4, heading_path=["Consigna"]),
        content_text=text,
        language="es-CL",
        extraction_confidence=1.0,
        normalized_hash=sha256_text(text),
    )


def _activity_pipeline_inputs() -> tuple[
    m.ActivityConfig,
    m.ActivitySpec,
    m.BlueprintPolicy,
    m.AssessmentBlueprint,
]:
    activity = m.ActivityConfig(
        activity_id="act_custom",
        tenant_id="tnt_custom",
        title="Actividad E1 dinámica",
        question_count=3,
        target_total_minutes=18,
        structured_justification_mode=m.StructuredJustificationMode.ALL,
        allowed_response_formats=[
            m.ResponseFormat.CHOICE,
            m.ResponseFormat.STRUCTURED_BULLETS,
        ],
        allowed_artifact_media_types=[
            "text/plain",
            "text/markdown",
            "application/pdf",
        ],
    )
    activity_spec = _invoke(
        "P01_ACTIVITY_SPEC_V1",
        m.ActivitySpecRequest(
            activity_config=activity,
            prompt_evidence=[_assignment_evidence()],
        ),
    )
    planning_policy = m.AssessmentPlanningPolicy(
        policy_id="planning_custom",
        max_reserve_opportunities=2,
    )
    blueprint_policy = m.BlueprintPolicy(
        policy_id="blueprint_policy_custom",
        activity_id=activity.activity_id,
        question_count=activity.question_count,
        target_total_minutes=activity.target_total_minutes,
        allowed_response_formats=list(activity.allowed_response_formats),
        structured_justification_policy=m.StructuredJustificationPolicy(
            mode=m.StructuredJustificationMode.ALL
        ),
        planning_policy=planning_policy,
    )
    blueprint = _invoke(
        "P04_BLUEPRINT_BUILD_V1",
        m.BlueprintBuildRequest(
            target_blueprint_id="bp_custom",
            target_blueprint_version=1,
            activity_spec=activity_spec,
            blueprint_policy=blueprint_policy,
        ),
    )
    return activity, activity_spec, blueprint_policy, blueprint


def _submission_bundle(activity_id: str) -> m.EvidenceBundle:
    evidence_units = []
    for index in range(5):
        text = (
            f"Fragmento {index + 1}: la decisión local {index + 1} produce "
            f"una consecuencia verificable {index + 1}."
        )
        evidence_units.append(
            m.EvidenceUnit(
                evidence_id=f"ev_submission_custom_{index}",
                tenant_id="tnt_custom",
                submission_id="sub_custom",
                artifact_id="art_submission_custom",
                artifact_hash=FIXED_HASH,
                source_role=m.ArtifactRole.SUBMISSION,
                modality=m.EvidenceModality.PARAGRAPH,
                locator=m.PageLocator(
                    page=index + 1,
                    bbox=[10.0, 20.0, 300.0, 40.0],
                    block_index=index,
                ),
                content_text=text,
                language="es-CL",
                extraction_confidence=1.0,
                normalized_hash=sha256_text(text),
            )
        )
    return m.EvidenceBundle(
        bundle_id="bundle_custom",
        tenant_id="tnt_custom",
        activity_id=activity_id,
        submission_id="sub_custom",
        context_mode=m.ContextMode.CLOSED,
        allowed_evidence_ids=[item.evidence_id for item in evidence_units],
        evidence_units=evidence_units,
    )


def _catalog(blueprint: m.AssessmentBlueprint):
    return [
        template
        for dimension in blueprint.dimensions
        for variant in dimension.evidence_variants
        for template in variant.question_opportunities
    ]


def test_p04_and_p05_preserve_non_demo_e1_configuration() -> None:
    activity, activity_spec, policy, blueprint = _activity_pipeline_inputs()
    catalog = _catalog(blueprint)

    assert blueprint.activity_id == activity.activity_id
    assert blueprint.context_mode == m.ContextMode.CLOSED
    assert blueprint.assessment_constraints.question_count == 3
    assert blueprint.assessment_constraints.target_total_minutes == 18
    assert blueprint.assessment_constraints.allowed_response_formats == [
        m.ResponseFormat.CHOICE,
        m.ResponseFormat.STRUCTURED_BULLETS,
    ]
    assert len(catalog) == 5
    assert all(template.target_minutes == 6 for template in catalog)
    assert all(template.student_justification_required for template in catalog)
    assert all(
        template.allowed_response_formats
        == blueprint.assessment_constraints.allowed_response_formats
        for template in catalog
    )

    review = _invoke(
        "P05_BLUEPRINT_REVIEW_V1",
        m.BlueprintReviewRequest(
            blueprint=blueprint,
            activity_spec=activity_spec,
            blueprint_policy=policy,
        ),
    )
    assert review.blueprint_id == blueprint.blueprint_id
    assert review.blueprint_version == blueprint.blueprint_version
    assert review.approval_recommendation == m.BlueprintApprovalRecommendation.APPROVE
    assert all(check.status == m.ReviewCheckStatus.PASS for check in review.checks)


def test_p06_maps_current_blueprint_catalog_to_current_evidence_and_exact_plan() -> None:
    _, _, policy, blueprint = _activity_pipeline_inputs()
    bundle = _submission_bundle(blueprint.activity_id)
    mapping = _invoke(
        "P06_EVIDENCE_MAP_V1",
        m.EvidenceMapRequest(blueprint=blueprint, evidence_bundle=bundle),
    )

    validate_evidence_map(mapping, blueprint=blueprint, bundle=bundle)
    assert mapping.status == "READY"
    assert len(mapping.opportunities) == len(_catalog(blueprint)) == 5
    assert {item.opportunity_template_id for item in mapping.opportunities} == {
        item.opportunity_template_id for item in _catalog(blueprint)
    }
    assert {
        evidence_id
        for opportunity in mapping.opportunities
        for evidence_id in opportunity.evidence_ids
    }.issubset(set(bundle.allowed_evidence_ids))

    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=blueprint,
        policy=policy.planning_policy,
    )
    assert plan.status == "READY"
    assert len(plan.selected_opportunity_ids) == 3
    assert len(plan.reserve_opportunity_ids) == 2
    assert plan.estimated_total_minutes == 18


def test_p07_p08_and_p09_derive_ids_anchors_scores_and_guide_from_request() -> None:
    _, _, policy, blueprint = _activity_pipeline_inputs()
    bundle = _submission_bundle(blueprint.activity_id)
    mapping = _invoke(
        "P06_EVIDENCE_MAP_V1",
        m.EvidenceMapRequest(blueprint=blueprint, evidence_bundle=bundle),
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=blueprint,
        policy=policy.planning_policy,
    )
    opportunities = {item.opportunity_id: item for item in mapping.opportunities}
    selected_questions: list[m.SelectedQuestion] = []

    for index, opportunity_id in enumerate(plan.selected_opportunity_ids):
        opportunity = opportunities[opportunity_id]
        generation = _invoke(
            "P07_QUESTION_BUILD_V1",
            m.QuestionBuildRequest(
                target_candidate_id=f"candidate_custom_{index}",
                plan=plan,
                opportunity=opportunity,
                evidence_bundle=bundle,
                generation_policy=m.QuestionGenerationPolicy(
                    policy_id="generation_custom"
                ),
            ),
        )
        validate_generation_result(
            generation,
            opportunity=opportunity,
            bundle=bundle,
        )
        candidate = generation.candidate
        assert candidate is not None
        assert candidate.response_format == m.ResponseFormat.CHOICE
        assert len(candidate.choices) == 3
        assert sum(choice.is_best_answer for choice in candidate.choices) == 1
        for fragment in candidate.anchor.fragments:
            evidence = next(
                item
                for item in bundle.evidence_units
                if item.evidence_id == fragment.evidence_id
            )
            assert fragment.locator == evidence.locator
            assert fragment.display_text in (evidence.content_text or "")

        validation_policy = m.QuestionValidationPolicy(
            policy_id="validation_custom"
        )
        review = _invoke(
            "P08_QUESTION_REVIEW_V1",
            m.QuestionReviewRequest(
                generation_result=generation,
                opportunity=opportunity,
                evidence_bundle=bundle,
                validation_policy=validation_policy,
            ),
        )
        validate_review_result(
            review,
            generation_result=generation,
            validation_policy=validation_policy,
        )
        assert review.review is not None
        assert review.review.candidate_id == candidate.candidate_id
        assert review.review.evidence_ids == candidate.evidence_ids

        selected_questions.append(
            m.SelectedQuestion(
                question_id=f"question_custom_{index}",
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
                choices=candidate.choices,
                student_justification_required=(
                    candidate.student_justification_required
                ),
                preliminary_guide=candidate.preliminary_guide,
                planning_score=0.95,
            )
        )

    question_ids = [question.question_id for question in selected_questions]
    assessment = m.Assessment(
        assessment_id="assessment_custom",
        tenant_id=bundle.tenant_id,
        activity_id=bundle.activity_id,
        submission_id=bundle.submission_id,
        subject_ref="subject_custom",
        status=m.WorkflowStatus.NEEDS_REVIEW,
        context_mode=m.ContextMode.CLOSED,
        assessment_plan_id=plan.plan_id,
        question_count=plan.question_count,
        questions=selected_questions,
        coverage=[
            m.CoverageItem(
                dimension_id=blueprint.dimensions[0].dimension_id,
                available_variant_count=len(
                    blueprint.dimensions[0].evidence_variants
                ),
                available_opportunity_count=len(mapping.opportunities),
                selected_opportunity_count=len(selected_questions),
                evidence_unit_count=len(bundle.evidence_units),
            )
        ],
        structured_justification=m.StructuredJustificationSummary(
            mode=m.StructuredJustificationMode.ALL,
            required_question_ids=question_ids,
            limited_evidence_notice_required=False,
        ),
        lineage=m.Lineage(
            assignment_prompt_hashes=[FIXED_HASH],
            rubric_hashes=[],
            submission_hashes=[FIXED_HASH],
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.blueprint_version,
            parser_versions={"pdf": "dynamic-test/1"},
            prompt_versions={"pack": "1.1.0"},
            model_snapshots={"mock": "deterministic-mock-v1"},
            policy_hash=FIXED_HASH,
            planner_version="stage0-planner/1.0.0",
            renderer_version="stage0-renderer/1.0.0",
        ),
        created_at=FIXED_TIME,
    )
    guide = _invoke(
        "P09_GUIDE_BUILD_V1",
        m.GuideBuildRequest(
            guide_id="guide_custom",
            assessment=assessment,
            evidence_bundle=bundle,
        ),
    )

    validate_evaluation_guide(guide, assessment=assessment, bundle=bundle)
    assert guide.assessment_id == assessment.assessment_id
    assert guide.submission_id == bundle.submission_id
    assert [item.question_id for item in guide.items] == question_ids
    for item in guide.items:
        question = next(
            question
            for question in assessment.questions
            if question.question_id == item.question_id
        )
        assert {
            evidence_id
            for element in item.guide.observable_elements
            for evidence_id in element.evidence_ids
        }.issubset(set(question.evidence_ids))
        assert [level.level for level in item.guide.levels] == [0, 1, 2, 3]
