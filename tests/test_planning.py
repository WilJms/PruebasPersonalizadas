from __future__ import annotations

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

