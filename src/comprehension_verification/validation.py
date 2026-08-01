"""Contextual grounding, provenance and fail-closed validators.

Pydantic validates shape. These functions validate repository facts and the
operational invariants deliberately documented outside JSON Schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .contracts import models as m


class ContextValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EvidenceContext:
    tenant_id: str
    submission_id: str
    evidence_by_id: Mapping[str, m.EvidenceUnit]
    course_sources_by_id: Mapping[str, m.CoursePassage]

    @classmethod
    def from_bundle(cls, bundle: m.EvidenceBundle) -> "EvidenceContext":
        return cls(
            tenant_id=bundle.tenant_id,
            submission_id=bundle.submission_id,
            evidence_by_id={item.evidence_id: item for item in bundle.evidence_units},
            course_sources_by_id={item.source_id: item for item in bundle.course_passages},
        )


def _require_unique(values: Iterable[str], *, code: str, label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ContextValidationError(code, f"{label} must be unique")


def validate_utc(value: datetime, *, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContextValidationError("DATETIME_NOT_UTC", f"{label} must be timezone-aware")
    if value.astimezone(timezone.utc).utcoffset() != timezone.utc.utcoffset(value):
        # Any aware time can be normalized, but persisted canonical objects must be UTC.
        raise ContextValidationError("DATETIME_NOT_UTC", f"{label} must be UTC")


def validate_complete_diagnostics(
    diagnostics: list[m.Diagnostic],
    *,
    status: str,
    require_matching_code: bool = True,
) -> None:
    if not diagnostics:
        raise ContextValidationError("DIAGNOSTIC_INCOMPLETE", "failed output requires diagnostics")
    if require_matching_code and not any(item.code == status for item in diagnostics):
        raise ContextValidationError(
            "DIAGNOSTIC_INCOMPLETE", "failed output requires a diagnostic matching its status"
        )
    for item in diagnostics:
        if item.severity not in {m.Severity.ERROR, m.Severity.CRITICAL}:
            raise ContextValidationError(
                "DIAGNOSTIC_INCOMPLETE", "failed output diagnostics must be ERROR or CRITICAL"
            )
        if item.retryable:
            raise ContextValidationError(
                "DIAGNOSTIC_INCOMPLETE", "domain fail-closed diagnostics are not retryable"
            )


def validate_evidence_context(bundle: m.EvidenceBundle) -> EvidenceContext:
    context = EvidenceContext.from_bundle(bundle)
    if set(bundle.allowed_evidence_ids) != set(context.evidence_by_id):
        raise ContextValidationError("EVIDENCE_ALLOWLIST_MISMATCH", "evidence allowlist mismatch")
    for evidence in bundle.evidence_units:
        if evidence.tenant_id != bundle.tenant_id:
            raise ContextValidationError("CROSS_TENANT_EVIDENCE", "evidence belongs to another tenant")
        if evidence.submission_id != bundle.submission_id:
            raise ContextValidationError(
                "CROSS_SUBMISSION_EVIDENCE", "evidence belongs to another submission"
            )
        if evidence.source_role != m.ArtifactRole.SUBMISSION:
            raise ContextValidationError(
                "EVIDENCE_ROLE_MISMATCH", "submission bundle contains a non-submission role"
            )
    if bundle.context_mode == m.ContextMode.CLOSED and bundle.course_passages:
        raise ContextValidationError(
            "UNAUTHORIZED_SOURCE", "closed context cannot contain course passages"
        )
    return context


def _blueprint_index(
    blueprint: m.AssessmentBlueprint,
) -> tuple[dict[str, m.BlueprintDimension], dict[str, m.EvidenceVariant], dict[str, m.QuestionOpportunityTemplate]]:
    dimensions: dict[str, m.BlueprintDimension] = {}
    variants: dict[str, m.EvidenceVariant] = {}
    templates: dict[str, m.QuestionOpportunityTemplate] = {}
    for dimension in blueprint.dimensions:
        dimensions[dimension.dimension_id] = dimension
        for variant in dimension.evidence_variants:
            variants[variant.variant_id] = variant
            for template in variant.question_opportunities:
                templates[template.opportunity_template_id] = template
    return dimensions, variants, templates


def validate_evidence_map(
    mapping: m.EvidenceMapPatch,
    *,
    blueprint: m.AssessmentBlueprint,
    bundle: m.EvidenceBundle,
) -> None:
    context = validate_evidence_context(bundle)
    if mapping.submission_id != bundle.submission_id:
        raise ContextValidationError(
            "CROSS_SUBMISSION_EVIDENCE", "mapping belongs to another submission"
        )
    if mapping.status != "READY":
        if mapping.opportunities or mapping.claims or mapping.variant_matches:
            raise ContextValidationError(
                "PARTIAL_ASSESSMENT_FORBIDDEN", "failed mapping cannot expose usable annotations"
            )
        validate_complete_diagnostics(mapping.diagnostics, status=mapping.status)
        return
    dimensions, variants, templates = _blueprint_index(blueprint)
    variant_dimension_ids = {
        variant.variant_id: dimension.dimension_id
        for dimension in blueprint.dimensions
        for variant in dimension.evidence_variants
    }
    template_variant_ids = {
        template.opportunity_template_id: variant.variant_id
        for dimension in blueprint.dimensions
        for variant in dimension.evidence_variants
        for template in variant.question_opportunities
    }
    _require_unique(
        (claim.claim_id for claim in mapping.claims),
        code="DUPLICATE_ID",
        label="claim IDs",
    )
    _require_unique(
        (f"{match.dimension_id}:{match.variant_id}" for match in mapping.variant_matches),
        code="DUPLICATE_ID",
        label="variant match paths",
    )
    for claim in mapping.claims:
        if any(evidence_id not in context.evidence_by_id for evidence_id in claim.evidence_ids):
            raise ContextValidationError(
                "INVENTED_EVIDENCE_ID", "claim references unknown evidence"
            )
        allowed_operations: set[m.CognitiveOperation] = set()
        for alignment in claim.alignments:
            dimension = dimensions.get(alignment.dimension_id)
            if dimension is None:
                raise ContextValidationError(
                    "INVENTED_ID", "claim alignment references an unknown dimension"
                )
            if not set(alignment.criterion_ids).issubset(set(dimension.criterion_ids)):
                raise ContextValidationError(
                    "BLUEPRINT_REFERENCE_MISMATCH",
                    "claim alignment widens the dimension criteria",
                )
            for variant_id in alignment.variant_ids:
                variant = variants.get(variant_id)
                if variant is None:
                    raise ContextValidationError(
                        "INVENTED_ID", "claim alignment references an unknown variant"
                    )
                if variant_dimension_ids[variant_id] != alignment.dimension_id:
                    raise ContextValidationError(
                        "BLUEPRINT_REFERENCE_MISMATCH",
                        "claim alignment variant belongs to another dimension",
                    )
                allowed_operations.update(
                    item.cognitive_operation for item in variant.supported_operations
                )
        if set(claim.supported_operations) - allowed_operations:
            raise ContextValidationError(
                "UNSUPPORTED_COGNITIVE_OPERATION",
                "claim widens the operations supported by its alignments",
            )
    for match in mapping.variant_matches:
        if match.dimension_id not in dimensions or match.variant_id not in variants:
            raise ContextValidationError("INVENTED_ID", "mapping references an unknown blueprint ID")
        if variant_dimension_ids[match.variant_id] != match.dimension_id:
            raise ContextValidationError(
                "BLUEPRINT_REFERENCE_MISMATCH", "variant match path is invalid"
            )
        if any(evidence_id not in context.evidence_by_id for evidence_id in match.evidence_ids):
            raise ContextValidationError("INVENTED_EVIDENCE_ID", "mapping references unknown evidence")
        variant = variants[match.variant_id]
        _require_unique(
            match.evidence_ids,
            code="DUPLICATE_ID",
            label="variant match evidence IDs",
        )
        selected = [context.evidence_by_id[evidence_id] for evidence_id in match.evidence_ids]
        requirement = variant.evidence_requirement
        if match.mapping_confidence < requirement.min_alignment:
            raise ContextValidationError(
                "EVIDENCE_MAPPING_UNCERTAIN",
                "variant match confidence is below the blueprint alignment floor",
            )
        if len(set(match.evidence_ids)) < requirement.min_distinct_units:
            raise ContextValidationError(
                "INSUFFICIENT_RELEVANT_EVIDENCE",
                "variant match does not satisfy the minimum distinct evidence units",
            )
        if any(item.modality not in requirement.allowed_modalities for item in selected):
            raise ContextValidationError(
                "EVIDENCE_MODALITY_MISMATCH", "variant match uses a disallowed modality"
            )
        if any(item.extraction_confidence < requirement.min_extraction_confidence for item in selected):
            raise ContextValidationError(
                "EVIDENCE_CONFIDENCE_LOW", "variant match uses evidence below the confidence floor"
            )
        if requirement.cross_artifact_required and len({item.artifact_id for item in selected}) < 2:
            raise ContextValidationError(
                "INSUFFICIENT_RELEVANT_EVIDENCE", "variant match requires distinct artifacts"
            )
    matches_by_path = {
        (match.dimension_id, match.variant_id): match
        for match in mapping.variant_matches
    }
    for opportunity in mapping.opportunities:
        if opportunity.submission_id != mapping.submission_id:
            raise ContextValidationError(
                "CROSS_SUBMISSION_EVIDENCE", "opportunity belongs to another submission"
            )
        dimension = dimensions.get(opportunity.dimension_id)
        variant = variants.get(opportunity.variant_id)
        template = templates.get(opportunity.opportunity_template_id)
        if dimension is None or variant is None or template is None:
            raise ContextValidationError("INVENTED_ID", "opportunity references an unknown ID")
        if variant not in dimension.evidence_variants or template not in variant.question_opportunities:
            raise ContextValidationError("BLUEPRINT_REFERENCE_MISMATCH", "opportunity path is invalid")
        if (
            variant_dimension_ids[opportunity.variant_id] != opportunity.dimension_id
            or template_variant_ids[opportunity.opportunity_template_id] != opportunity.variant_id
        ):
            raise ContextValidationError("BLUEPRINT_REFERENCE_MISMATCH", "opportunity path is invalid")
        match = matches_by_path.get((opportunity.dimension_id, opportunity.variant_id))
        if match is None:
            raise ContextValidationError(
                "BLUEPRINT_REFERENCE_MISMATCH",
                "opportunity has no validated variant match",
            )
        if any(
            evidence_id not in context.evidence_by_id
            for evidence_id in opportunity.evidence_ids
        ):
            raise ContextValidationError(
                "INVENTED_EVIDENCE_ID",
                "opportunity references unknown evidence",
            )
        if not set(opportunity.evidence_ids).issubset(set(match.evidence_ids)):
            raise ContextValidationError(
                "UNAUTHORIZED_EVIDENCE",
                "opportunity widens the evidence of its variant match",
            )
        if opportunity.evidence_fit != match.evidence_fit:
            raise ContextValidationError(
                "BLUEPRINT_REFERENCE_MISMATCH",
                "opportunity changes the evidence fit of its variant match",
            )
        supported = {item.cognitive_operation for item in variant.supported_operations}
        if opportunity.cognitive_operation not in supported:
            raise ContextValidationError(
                "UNSUPPORTED_COGNITIVE_OPERATION", "opportunity widens the variant operation"
            )
        if opportunity.cognitive_operation != template.cognitive_operation:
            raise ContextValidationError(
                "UNSUPPORTED_COGNITIVE_OPERATION", "opportunity changes its template operation"
            )
        inherited = (
            opportunity.focus == template.focus
            and opportunity.observable == template.observable
            and opportunity.difficulty == template.difficulty
            and opportunity.target_minutes == template.target_minutes
            and opportunity.allowed_anchor_structures == template.allowed_anchor_structures
            and opportunity.allowed_response_formats == template.allowed_response_formats
            and opportunity.student_justification_required
            == template.student_justification_required
            and opportunity.activity_priority == dimension.verification_priority
        )
        if not inherited:
            raise ContextValidationError(
                "BLUEPRINT_REFERENCE_MISMATCH",
                "opportunity changes source-bound template constraints",
            )
        if any(evidence_id not in context.evidence_by_id for evidence_id in opportunity.evidence_ids):
            raise ContextValidationError(
                "INVENTED_EVIDENCE_ID", "opportunity references unknown evidence"
            )
        requirement = variant.evidence_requirement
        _require_unique(
            opportunity.evidence_ids,
            code="DUPLICATE_ID",
            label="opportunity evidence IDs",
        )
        selected = [context.evidence_by_id[evidence_id] for evidence_id in opportunity.evidence_ids]
        if len(set(opportunity.evidence_ids)) < requirement.min_distinct_units:
            raise ContextValidationError(
                "INSUFFICIENT_RELEVANT_EVIDENCE",
                "opportunity does not satisfy the variant evidence requirement",
            )
        if any(item.modality not in requirement.allowed_modalities for item in selected):
            raise ContextValidationError(
                "EVIDENCE_MODALITY_MISMATCH", "opportunity uses a disallowed modality"
            )
        if any(item.extraction_confidence < requirement.min_extraction_confidence for item in selected):
            raise ContextValidationError(
                "EVIDENCE_CONFIDENCE_LOW", "opportunity uses evidence below the confidence floor"
            )
        if requirement.cross_artifact_required and len({item.artifact_id for item in selected}) < 2:
            raise ContextValidationError(
                "INSUFFICIENT_RELEVANT_EVIDENCE",
                "opportunity requires evidence from distinct artifacts",
            )


def validate_assessment_plan(
    plan: m.AssessmentPlan,
    *,
    mapping: m.EvidenceMapPatch,
) -> None:
    opportunity_ids = {item.opportunity_id for item in mapping.opportunities}
    if plan.submission_id != mapping.submission_id:
        raise ContextValidationError("CROSS_SUBMISSION_EVIDENCE", "plan submission mismatch")
    if plan.status == "READY":
        if len(plan.selected_opportunity_ids) != plan.question_count:
            raise ContextValidationError(
                "PARTIAL_ASSESSMENT_FORBIDDEN", "ready plan does not contain exactly N"
            )
        if not set(plan.selected_opportunity_ids + plan.reserve_opportunity_ids).issubset(
            opportunity_ids
        ):
            raise ContextValidationError("INVENTED_ID", "plan references unknown opportunities")
        _require_unique(
            plan.selected_opportunity_ids + plan.reserve_opportunity_ids,
            code="PLAN_DUPLICATE_OPPORTUNITY",
            label="planned opportunity IDs",
        )
    else:
        if plan.selected_opportunity_ids or plan.reserve_opportunity_ids:
            raise ContextValidationError(
                "PARTIAL_ASSESSMENT_FORBIDDEN", "failed plan contains a partial assessment"
            )
        validate_complete_diagnostics(plan.diagnostics, status=plan.status)


_SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
]
_PROHIBITED_CLAIMS = re.compile(
    r"\b(detector de ia|hecho por ia|autor(?:ía)?|fraude|culpable|otro estudiante|system prompt|ignore (?:all |previous )?instructions)\b",
    flags=re.IGNORECASE,
)


def _check_safe_generated_text(text: str) -> None:
    if _PROHIBITED_CLAIMS.search(text):
        raise ContextValidationError(
            "QUESTION_SECURITY_FAIL", "generated question contains a prohibited claim or instruction"
        )
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        raise ContextValidationError("QUESTION_PII", "generated question exposes PII or a secret")


def validate_question_candidate(
    candidate: m.QuestionCandidate,
    *,
    opportunity: m.QuestionOpportunity,
    bundle: m.EvidenceBundle,
) -> None:
    context = validate_evidence_context(bundle)
    if candidate.submission_id != bundle.submission_id or candidate.submission_id != opportunity.submission_id:
        raise ContextValidationError(
            "CROSS_SUBMISSION_EVIDENCE", "candidate submission mismatch"
        )
    if candidate.opportunity_id != opportunity.opportunity_id:
        raise ContextValidationError("INVENTED_ID", "candidate opportunity mismatch")
    if (
        candidate.opportunity_template_id != opportunity.opportunity_template_id
        or candidate.dimension_id != opportunity.dimension_id
        or candidate.variant_id != opportunity.variant_id
    ):
        raise ContextValidationError(
            "BLUEPRINT_REFERENCE_MISMATCH", "candidate changes its opportunity path"
        )
    if candidate.cognitive_operation != opportunity.cognitive_operation:
        raise ContextValidationError(
            "UNSUPPORTED_COGNITIVE_OPERATION", "candidate changes the planned operation"
        )
    if candidate.response_format not in opportunity.allowed_response_formats:
        raise ContextValidationError(
            "RESPONSE_FORMAT_NOT_ALLOWED", "candidate uses a response format outside the opportunity"
        )
    if (
        candidate.difficulty != opportunity.difficulty
        or candidate.estimated_minutes != opportunity.target_minutes
        or candidate.student_justification_required
        != opportunity.student_justification_required
    ):
        raise ContextValidationError(
            "BLUEPRINT_REFERENCE_MISMATCH", "candidate changes planned difficulty, time or justification"
        )
    if candidate.anchor.structure not in opportunity.allowed_anchor_structures:
        raise ContextValidationError(
            "ANCHOR_STRUCTURE_NOT_ALLOWED", "candidate uses an anchor structure outside the opportunity"
        )
    if set(candidate.evidence_ids) - set(opportunity.evidence_ids):
        raise ContextValidationError(
            "UNAUTHORIZED_EVIDENCE", "candidate widens the opportunity evidence"
        )
    if set(candidate.evidence_ids) - set(context.evidence_by_id):
        raise ContextValidationError("INVENTED_EVIDENCE_ID", "candidate uses unknown evidence")
    for element in candidate.preliminary_guide.observable_elements:
        if not set(element.evidence_ids).issubset(set(candidate.evidence_ids)):
            raise ContextValidationError(
                "UNAUTHORIZED_EVIDENCE", "candidate guide widens candidate evidence"
            )
        if not set(element.source_ids).issubset(set(candidate.course_source_ids)):
            raise ContextValidationError(
                "UNAUTHORIZED_SOURCE", "candidate guide widens candidate sources"
            )
    _check_safe_generated_text(candidate.question_text)
    for fragment in candidate.anchor.fragments:
        evidence = context.evidence_by_id.get(fragment.evidence_id)
        if evidence is None:
            raise ContextValidationError("INVENTED_EVIDENCE_ID", "anchor uses unknown evidence")
        if fragment.locator.model_dump(mode="json") != evidence.locator.model_dump(mode="json"):
            raise ContextValidationError("ANCHOR_NOT_DERIVABLE", "anchor locator does not match evidence")
        if fragment.display_text is None:
            raise ContextValidationError("ANCHOR_NOT_DERIVABLE", "Stage 0 anchor requires display text")
        source_text = evidence.content_text or ""
        if fragment.transformation in {"LITERAL", "CROP", "CODE_CONTEXT", "ALT_TEXT"}:
            if fragment.display_text not in source_text:
                raise ContextValidationError(
                    "ANCHOR_NOT_DERIVABLE", "anchor text is not derivable from evidence"
                )
        elif fragment.transformation == "TABLE_SLICE":
            if evidence.structured_content is None:
                raise ContextValidationError(
                    "ANCHOR_NOT_DERIVABLE", "table slice has no structured evidence"
                )
    if bundle.context_mode == m.ContextMode.CLOSED:
        if candidate.course_source_ids or candidate.citations:
            raise ContextValidationError("UNAUTHORIZED_SOURCE", "closed question cites course sources")
    else:
        if set(candidate.course_source_ids) != {item.source_id for item in candidate.citations}:
            raise ContextValidationError("UNAUTHORIZED_SOURCE", "citation IDs do not match")
        if set(candidate.course_source_ids) - set(context.course_sources_by_id):
            raise ContextValidationError("UNAUTHORIZED_SOURCE", "course source is not allowlisted")


def validate_generation_result(
    result: m.QuestionGenerationResult,
    *,
    opportunity: m.QuestionOpportunity,
    bundle: m.EvidenceBundle,
) -> None:
    if result.status == "READY":
        if result.candidate is None:
            raise ContextValidationError("MODEL_OUTPUT_INVALID", "ready generation has no candidate")
        validate_question_candidate(result.candidate, opportunity=opportunity, bundle=bundle)
    else:
        if result.candidate is not None:
            raise ContextValidationError(
                "PARTIAL_ASSESSMENT_FORBIDDEN", "failed generation exposes a candidate"
            )
        validate_complete_diagnostics(
            result.diagnostics,
            status=result.status,
            require_matching_code=False,
        )


def validate_review_result(
    review_result: m.QuestionReviewResult,
    *,
    generation_result: m.QuestionGenerationResult,
    validation_policy: m.QuestionValidationPolicy,
) -> None:
    if review_result.status == "READY":
        if review_result.review is None or generation_result.candidate is None:
            raise ContextValidationError("MODEL_OUTPUT_INVALID", "ready review is incomplete")
        if review_result.review.candidate_id != generation_result.candidate.candidate_id:
            raise ContextValidationError("INVENTED_ID", "review candidate mismatch")
        if (
            review_result.submission_id != generation_result.submission_id
            or review_result.opportunity_id != generation_result.opportunity_id
        ):
            raise ContextValidationError("INVENTED_ID", "review result request mismatch")
        candidate = generation_result.candidate
        if not set(review_result.review.evidence_ids).issubset(set(candidate.evidence_ids)):
            raise ContextValidationError(
                "UNAUTHORIZED_EVIDENCE", "review widens candidate evidence"
            )
        if not set(review_result.review.source_ids).issubset(set(candidate.course_source_ids)):
            raise ContextValidationError(
                "UNAUTHORIZED_SOURCE", "review widens candidate sources"
            )
        if (
            review_result.review.estimated_difficulty != candidate.difficulty
            or review_result.review.estimated_minutes != candidate.estimated_minutes
        ):
            raise ContextValidationError(
                "BLUEPRINT_REFERENCE_MISMATCH", "review changes planned difficulty or time"
            )
        semantic = review_result.review
        if semantic.decision == m.ReviewDecision.ACCEPT:
            scores = semantic.scores
            below_threshold = any(
                (
                    scores.groundedness < validation_policy.minimum_groundedness,
                    scores.anchor_sufficiency
                    < validation_policy.minimum_anchor_sufficiency,
                    scores.criterion_relevance
                    < validation_policy.minimum_criterion_relevance,
                    scores.answerability < validation_policy.minimum_answerability,
                    semantic.confidence < validation_policy.escalate_below_confidence,
                )
            )
            if below_threshold or semantic.critical_failure_codes:
                raise ContextValidationError(
                    "QUESTION_POLICY_VIOLATION",
                    "an accepted question violates validation thresholds or critical gates",
                )
    else:
        if review_result.review is not None:
            raise ContextValidationError(
                "PARTIAL_ASSESSMENT_FORBIDDEN", "abstained review contains scores"
            )
        validate_complete_diagnostics(
            review_result.diagnostics,
            status=review_result.status,
            require_matching_code=False,
        )


def validate_evaluation_guide(
    guide: m.EvaluationGuide,
    *,
    assessment: m.Assessment,
    bundle: m.EvidenceBundle,
) -> None:
    if guide.assessment_id != assessment.assessment_id:
        raise ContextValidationError("INVENTED_ID", "guide assessment mismatch")
    if guide.submission_id != assessment.submission_id or guide.submission_id != bundle.submission_id:
        raise ContextValidationError("CROSS_SUBMISSION_EVIDENCE", "guide submission mismatch")
    assessment_questions = {item.question_id: item for item in assessment.questions}
    if guide.status == "READY":
        if {item.question_id for item in guide.items} != set(assessment_questions):
            raise ContextValidationError("GUIDE_INCOMPLETE", "guide must cover every question exactly")
        for item in guide.items:
            question = assessment_questions[item.question_id]
            levels = [level.level for level in item.guide.levels]
            if levels != [0, 1, 2, 3]:
                raise ContextValidationError("GUIDE_INCOMPLETE", "guide levels must be 0,1,2,3")
            observable_ids = {element.element_id for element in item.guide.observable_elements}
            for level in item.guide.levels:
                if not set(level.observable_element_ids).issubset(observable_ids):
                    raise ContextValidationError("INVENTED_ID", "guide level uses unknown element")
            allowed_evidence = set(question.evidence_ids)
            allowed_sources = set(question.course_source_ids)
            for element in item.guide.observable_elements:
                if not set(element.evidence_ids).issubset(allowed_evidence):
                    raise ContextValidationError(
                        "UNAUTHORIZED_EVIDENCE", "guide widens question evidence"
                    )
                if not set(element.source_ids).issubset(allowed_sources):
                    raise ContextValidationError("UNAUTHORIZED_SOURCE", "guide widens sources")
    else:
        if guide.items:
            raise ContextValidationError(
                "PARTIAL_ASSESSMENT_FORBIDDEN", "failed guide contains partial items"
            )
        validate_complete_diagnostics(
            guide.diagnostics,
            status=guide.status,
            require_matching_code=False,
        )
