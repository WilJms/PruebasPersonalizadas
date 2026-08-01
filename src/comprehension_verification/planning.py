"""Deterministic, atomic selection of primary and reserve opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .canonical import stable_id
from .contracts import models as m
from .diagnostics import diagnostic


PLANNER_VERSION = "stage0-planner/1.0.0"


@dataclass(frozen=True)
class ScoredOpportunity:
    opportunity: m.QuestionOpportunity
    base_score: float


@dataclass(frozen=True)
class _State:
    selected: tuple[int, ...]
    score: float
    minutes: int


def evidence_overlap(left: m.QuestionOpportunity, right: m.QuestionOpportunity) -> float:
    left_ids = set(left.evidence_ids)
    right_ids = set(right.evidence_ids)
    union = left_ids | right_ids
    return 0.0 if not union else len(left_ids & right_ids) / len(union)


def _base_score(
    opportunity: m.QuestionOpportunity,
    policy: m.AssessmentPlanningPolicy,
) -> float:
    return (
        opportunity.activity_priority * policy.activity_priority_weight
        + opportunity.evidence_fit * policy.evidence_fit_weight
        + opportunity.opportunity_quality * policy.opportunity_quality_weight
    )


def _marginal_score(
    opportunity: m.QuestionOpportunity,
    selected: Iterable[m.QuestionOpportunity],
    policy: m.AssessmentPlanningPolicy,
) -> float:
    chosen = tuple(selected)
    dimension_penalty = policy.repeated_dimension_penalty * sum(
        item.dimension_id == opportunity.dimension_id for item in chosen
    )
    variant_penalty = policy.repeated_variant_penalty * sum(
        item.variant_id == opportunity.variant_id for item in chosen
    )
    overlaps = [evidence_overlap(item, opportunity) for item in chosen]
    overlap_penalty = policy.evidence_overlap_penalty * sum(overlaps)
    return _base_score(opportunity, policy) - dimension_penalty - variant_penalty - overlap_penalty


def _complete_failure(
    *,
    status: str,
    submission_id: str,
    blueprint: m.AssessmentBlueprint,
    question_count: int,
    evidence_ids: list[str],
    details: dict[str, object],
) -> m.AssessmentPlan:
    message_by_status = {
        "INSUFFICIENT_RELEVANT_EVIDENCE": "No existe evidencia pertinente suficiente para planificar la evaluación.",
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES": "No existen oportunidades sustancialmente distintas suficientes para el número solicitado.",
        "EVIDENCE_MAPPING_UNCERTAIN": "El mapeo entre evidencia, dimensión y variante no alcanza la confianza requerida.",
        "ASSESSMENT_PLAN_INFEASIBLE": "Las oportunidades válidas no satisfacen conjuntamente las restricciones no relajables.",
    }
    plan_id = stable_id(
        "plan",
        submission_id,
        blueprint.blueprint_id,
        blueprint.blueprint_version,
        status,
        question_count,
    )
    return m.AssessmentPlan(
        plan_id=plan_id,
        submission_id=submission_id,
        blueprint_id=blueprint.blueprint_id,
        blueprint_version=blueprint.blueprint_version,
        status=status,
        question_count=question_count,
        selected_opportunity_ids=[],
        reserve_opportunity_ids=[],
        estimated_total_minutes=0,
        diagnostics=[
            diagnostic(
                status,
                message_by_status[status],
                evidence_ids=evidence_ids[:100],
                retryable=False,
                details=details,
            )
        ],
    )


def _failure_from_mapping(
    mapping: m.EvidenceMapPatch,
    blueprint: m.AssessmentBlueprint,
    question_count: int,
) -> m.AssessmentPlan:
    allowed = {
        "INSUFFICIENT_RELEVANT_EVIDENCE",
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
        "EVIDENCE_MAPPING_UNCERTAIN",
    }
    if mapping.status not in allowed:
        raise ValueError(f"mapping status cannot enter planner: {mapping.status}")
    evidence_ids = sorted(
        {
            evidence_id
            for item in mapping.diagnostics
            for evidence_id in item.evidence_ids
        }
    )
    return _complete_failure(
        status=mapping.status,
        submission_id=mapping.submission_id,
        blueprint=blueprint,
        question_count=question_count,
        evidence_ids=evidence_ids,
        details={"mapping_status": mapping.status},
    )


def _valid_candidates(
    mapping: m.EvidenceMapPatch,
    blueprint: m.AssessmentBlueprint,
    policy: m.AssessmentPlanningPolicy,
) -> list[ScoredOpportunity]:
    allowed_formats = set(blueprint.assessment_constraints.allowed_response_formats)
    candidates = [
        opportunity
        for opportunity in mapping.opportunities
        if opportunity.opportunity_quality >= policy.minimum_opportunity_quality
        and opportunity.evidence_fit >= policy.minimum_evidence_fit
        and bool(set(opportunity.allowed_response_formats) & allowed_formats)
    ]
    scored = [ScoredOpportunity(item, _base_score(item, policy)) for item in candidates]
    return sorted(scored, key=lambda item: (-item.base_score, item.opportunity.opportunity_id))


def _select_exact(
    scored: list[ScoredOpportunity],
    *,
    count: int,
    max_minutes: int,
    policy: m.AssessmentPlanningPolicy,
    beam_width: int = 512,
) -> _State | None:
    states = [_State(selected=(), score=0.0, minutes=0)]
    for _depth in range(count):
        next_states: list[_State] = []
        for state in states:
            start = state.selected[-1] + 1 if state.selected else 0
            selected_items = [scored[index].opportunity for index in state.selected]
            for index in range(start, len(scored)):
                candidate = scored[index].opportunity
                minutes = state.minutes + candidate.target_minutes
                if minutes > max_minutes:
                    continue
                if any(
                    evidence_overlap(candidate, prior) > policy.maximum_evidence_overlap
                    for prior in selected_items
                ):
                    continue
                next_states.append(
                    _State(
                        selected=state.selected + (index,),
                        score=state.score
                        + _marginal_score(candidate, selected_items, policy),
                        minutes=minutes,
                    )
                )
        if not next_states:
            return None
        next_states.sort(
            key=lambda state: (
                -state.score,
                state.minutes,
                tuple(scored[index].opportunity.opportunity_id for index in state.selected),
            )
        )
        states = next_states[:beam_width]
    return states[0] if states else None


def build_assessment_plan(
    *,
    mapping: m.EvidenceMapPatch,
    blueprint: m.AssessmentBlueprint,
    policy: m.AssessmentPlanningPolicy,
) -> m.AssessmentPlan:
    """Return exactly N primary opportunities or a complete fail-closed plan."""

    question_count = blueprint.assessment_constraints.question_count
    if mapping.submission_id == "":
        raise ValueError("mapping submission_id is required")
    if mapping.status != "READY":
        return _failure_from_mapping(mapping, blueprint, question_count)

    all_evidence_ids = sorted(
        {evidence_id for item in mapping.opportunities for evidence_id in item.evidence_ids}
    )
    scored = _valid_candidates(mapping, blueprint, policy)
    if not scored:
        return _complete_failure(
            status="INSUFFICIENT_RELEVANT_EVIDENCE",
            submission_id=mapping.submission_id,
            blueprint=blueprint,
            question_count=question_count,
            evidence_ids=all_evidence_ids,
            details={"valid_opportunity_count": 0, "required_question_count": question_count},
        )
    if len(scored) < question_count:
        return _complete_failure(
            status="INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
            submission_id=mapping.submission_id,
            blueprint=blueprint,
            question_count=question_count,
            evidence_ids=all_evidence_ids,
            details={
                "distinct_opportunity_count": len(scored),
                "required_question_count": question_count,
            },
        )

    state = _select_exact(
        scored,
        count=question_count,
        max_minutes=blueprint.assessment_constraints.target_total_minutes,
        policy=policy,
    )
    if state is None:
        return _complete_failure(
            status="ASSESSMENT_PLAN_INFEASIBLE",
            submission_id=mapping.submission_id,
            blueprint=blueprint,
            question_count=question_count,
            evidence_ids=all_evidence_ids,
            details={
                "valid_opportunity_count": len(scored),
                "required_question_count": question_count,
                "target_total_minutes": blueprint.assessment_constraints.target_total_minutes,
            },
        )

    primary_indices = set(state.selected)
    primary = [scored[index].opportunity for index in state.selected]
    reserve_candidates = [
        scored[index].opportunity
        for index in range(len(scored))
        if index not in primary_indices
    ]
    reserve_candidates.sort(
        key=lambda item: (-_marginal_score(item, primary, policy), item.opportunity_id)
    )
    reserve = reserve_candidates[: policy.max_reserve_opportunities]
    selected_ids = [item.opportunity_id for item in primary]
    reserve_ids = [item.opportunity_id for item in reserve]
    plan_id = stable_id(
        "plan",
        mapping.submission_id,
        blueprint.blueprint_id,
        blueprint.blueprint_version,
        selected_ids,
        reserve_ids,
        PLANNER_VERSION,
    )
    return m.AssessmentPlan(
        plan_id=plan_id,
        submission_id=mapping.submission_id,
        blueprint_id=blueprint.blueprint_id,
        blueprint_version=blueprint.blueprint_version,
        status="READY",
        question_count=question_count,
        selected_opportunity_ids=selected_ids,
        reserve_opportunity_ids=reserve_ids,
        estimated_total_minutes=sum(item.target_minutes for item in primary),
        diagnostics=[],
    )

