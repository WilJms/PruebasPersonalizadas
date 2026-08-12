from __future__ import annotations

from comprehension_verification.contracts import models as m
from comprehension_verification.planning import build_assessment_plan

from .factories import blueprint, evidence_bundle, evidence_map, failed_map, planning_policy


def test_ready_plan_has_exact_n_and_disjoint_reserve_and_is_deterministic() -> None:
    bp = blueprint(question_count=3, opportunity_count=8)
    bundle = evidence_bundle(8)
    mapping = evidence_map(bp, bundle)
    first = build_assessment_plan(mapping=mapping, blueprint=bp, policy=planning_policy())
    second = build_assessment_plan(mapping=mapping, blueprint=bp, policy=planning_policy())

    assert first == second
    assert first.status == "READY"
    assert len(first.selected_opportunity_ids) == 3
    assert len(first.reserve_opportunity_ids) == 2
    assert set(first.selected_opportunity_ids).isdisjoint(first.reserve_opportunity_ids)
    assert first.estimated_total_minutes == 9


def test_insufficient_relevant_evidence_has_no_partial_plan() -> None:
    bp = blueprint()
    mapping = evidence_map(bp, evidence_bundle(), quality=0.2, evidence_fit=0.2)
    plan = build_assessment_plan(mapping=mapping, blueprint=bp, policy=planning_policy())
    assert plan.status == "INSUFFICIENT_RELEVANT_EVIDENCE"
    assert not plan.selected_opportunity_ids
    assert not plan.reserve_opportunity_ids
    assert plan.diagnostics[0].code == plan.status


def test_insufficient_distinct_opportunities_has_no_partial_plan() -> None:
    bp = blueprint(question_count=3)
    mapping = evidence_map(bp, evidence_bundle(), opportunity_count=2)
    plan = build_assessment_plan(mapping=mapping, blueprint=bp, policy=planning_policy())
    assert plan.status == "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES"
    assert plan.selected_opportunity_ids == []
    assert plan.reserve_opportunity_ids == []


def test_mapping_uncertain_propagates_exact_diagnostic() -> None:
    bp = blueprint()
    mapping = failed_map("EVIDENCE_MAPPING_UNCERTAIN")
    plan = build_assessment_plan(mapping=mapping, blueprint=bp, policy=planning_policy())
    assert plan.status == "EVIDENCE_MAPPING_UNCERTAIN"
    assert plan.diagnostics[0].code == plan.status


def test_time_constraint_produces_plan_infeasible_not_partial() -> None:
    bp = blueprint(question_count=3, target_total_minutes=6, opportunity_minutes=3)
    mapping = evidence_map(bp, evidence_bundle())
    plan = build_assessment_plan(mapping=mapping, blueprint=bp, policy=planning_policy())
    assert plan.status == "ASSESSMENT_PLAN_INFEASIBLE"
    assert plan.selected_opportunity_ids == []
    assert plan.reserve_opportunity_ids == []


def test_required_criterion_survives_beam_pruning_via_complete_fallback() -> None:
    # 33 high-score common opportunities create 528 two-item combinations,
    # enough to fill the 512-state beam before the low-score required path.
    common_count = 33
    bp = blueprint(
        question_count=2,
        target_total_minutes=6,
        opportunity_count=common_count,
        opportunity_minutes=3,
    )
    common_dimension = bp.dimensions[0]
    common_variant = common_dimension.evidence_variants[0]
    required_template = common_variant.question_opportunities[0].model_copy(
        update={
            "opportunity_template_id": "opt_required",
            "focus": "Criterio obligatorio",
            "observable": "Explica el criterio obligatorio",
        }
    )
    required_variant = common_variant.model_copy(
        update={
            "variant_id": "variant_required",
            "name": "Variante obligatoria",
            "question_opportunities": [required_template],
        }
    )
    required_dimension = common_dimension.model_copy(
        update={
            "dimension_id": "dimension_required",
            "name": "Dimensión obligatoria",
            "criterion_ids": ["criterion_required"],
            "verification_priority": 0.0,
            "evidence_variants": [required_variant],
        }
    )
    constraints = bp.assessment_constraints.model_copy(
        update={"required_criterion_ids": ["criterion_required"]}
    )
    bp = bp.model_copy(
        update={
            "dimensions": [common_dimension, required_dimension],
            "assessment_constraints": constraints,
        }
    )
    bundle = evidence_bundle(common_count + 1)
    mapping = evidence_map(bp, bundle, opportunity_count=common_count)
    required_evidence = bundle.evidence_units[-1]
    required_opportunity = m.QuestionOpportunity(
        opportunity_id="opp_required",
        opportunity_template_id=required_template.opportunity_template_id,
        submission_id=bundle.submission_id,
        dimension_id=required_dimension.dimension_id,
        variant_id=required_variant.variant_id,
        evidence_ids=[required_evidence.evidence_id],
        cognitive_operation=required_template.cognitive_operation,
        focus=required_template.focus,
        observable=required_template.observable,
        difficulty=required_template.difficulty,
        target_minutes=required_template.target_minutes,
        allowed_anchor_structures=required_template.allowed_anchor_structures,
        allowed_response_formats=required_template.allowed_response_formats,
        activity_priority=required_dimension.verification_priority,
        evidence_fit=0.7,
        opportunity_quality=0.75,
        student_justification_required=False,
    )
    mapping = mapping.model_copy(
        update={
            "variant_matches": [
                *mapping.variant_matches,
                m.EvidenceVariantMatch(
                    dimension_id=required_dimension.dimension_id,
                    variant_id=required_variant.variant_id,
                    evidence_ids=[required_evidence.evidence_id],
                    evidence_fit=0.7,
                    mapping_confidence=0.95,
                    justification="Checkpoint sintético requerido.",
                ),
            ],
            "opportunities": [
                *mapping.opportunities,
                required_opportunity,
            ],
        }
    )

    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=bp,
        policy=planning_policy(max_reserve_opportunities=0),
    )

    assert plan.status == "READY"
    assert len(plan.selected_opportunity_ids) == 2
    assert "opp_required" in plan.selected_opportunity_ids


def test_missing_required_criterion_fails_without_partial_plan() -> None:
    bp = blueprint(question_count=1, opportunity_count=2)
    bp = bp.model_copy(
        update={
            "assessment_constraints": bp.assessment_constraints.model_copy(
                update={"required_criterion_ids": ["criterion_absent"]}
            )
        }
    )
    plan = build_assessment_plan(
        mapping=evidence_map(bp, evidence_bundle(2)),
        blueprint=bp,
        policy=planning_policy(),
    )
    assert plan.status == "ASSESSMENT_PLAN_INFEASIBLE"
    assert plan.selected_opportunity_ids == []
    assert plan.reserve_opportunity_ids == []
