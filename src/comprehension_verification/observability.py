"""Content-free diagnostic projections shared by product and rehearsal."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_hash
from .contracts import models as m


def p08_decision_diagnostics(
    review_result: m.QuestionReviewResult,
    validation_policy: m.QuestionValidationPolicy,
) -> dict[str, Any]:
    """Project a P08 decision into stable, reproducible audit metadata."""

    if review_result.status != "READY" or review_result.review is None:
        return {
            "review_status": str(review_result.status),
            "decision": "NONE",
            "criticality": "NON_CRITICAL",
            "critical_failure_count": 0,
            "provider_critical_code_hashes": [],
            "failure_categories": ["ABSTENTION"],
            "diagnostic_codes": ["P08_REVIEW_ABSTAINED"],
            "score_thresholds": {},
        }

    review = review_result.review
    comparisons = {
        "groundedness": (
            review.scores.groundedness,
            validation_policy.minimum_groundedness,
        ),
        "anchor_sufficiency": (
            review.scores.anchor_sufficiency,
            validation_policy.minimum_anchor_sufficiency,
        ),
        "criterion_relevance": (
            review.scores.criterion_relevance,
            validation_policy.minimum_criterion_relevance,
        ),
        "answerability": (
            review.scores.answerability,
            validation_policy.minimum_answerability,
        ),
        "confidence": (
            review.confidence,
            validation_policy.escalate_below_confidence,
        ),
    }
    score_thresholds = {
        name: {
            "score": score,
            "threshold": threshold,
            "relation": "AT_OR_ABOVE" if score >= threshold else "BELOW",
        }
        for name, (score, threshold) in comparisons.items()
    }
    below = [
        name.upper()
        for name, (score, threshold) in comparisons.items()
        if score < threshold
    ]
    critical = bool(review.critical_failure_codes)
    decision = str(review.decision)
    categories = [f"{name}_BELOW_THRESHOLD" for name in below]
    if critical:
        categories.append("MODEL_DECLARED_CRITICAL_FAILURE")
    if decision != m.ReviewDecision.ACCEPT.value and not categories:
        categories.append("MODEL_DECISION_NON_ACCEPT")
    diagnostic_codes = [f"P08_DECISION_{decision}"]
    diagnostic_codes.extend(f"P08_{category}" for category in categories)
    return {
        "review_status": str(review_result.status),
        "decision": decision,
        "criticality": "CRITICAL" if critical else "NON_CRITICAL",
        "critical_failure_count": len(review.critical_failure_codes),
        "provider_critical_code_hashes": sorted(
            canonical_hash({"critical_failure_code": code})
            for code in review.critical_failure_codes
        ),
        "failure_categories": categories,
        "diagnostic_codes": diagnostic_codes,
        "score_thresholds": score_thresholds,
    }
