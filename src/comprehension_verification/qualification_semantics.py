"""Post-execution semantic and causal interpretation for qualification.

This module belongs to the evaluation instrument, not to the product runtime.
It deliberately keeps operational outcome, oracle validity, semantic judgment,
contract adherence, and causal attribution as separate axes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class CheckpointClass(StrEnum):
    SEMANTICALLY_QUALIFIED_POSITIVE = "SEMANTICALLY_QUALIFIED_POSITIVE"
    SEMANTICALLY_QUALIFIED_NEGATIVE = "SEMANTICALLY_QUALIFIED_NEGATIVE"
    STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY = (
        "STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY"
    )


class OracleValidity(StrEnum):
    VALID = "VALID"
    ORACLE_SUSPECT = "ORACLE_SUSPECT"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @classmethod
    def _missing_(cls, value: object) -> "OracleValidity | None":
        # Historical receipts used UNESTABLISHED.  They remain readable, but
        # every newly serialized assessment uses the explicit review state.
        if value == "UNESTABLISHED":
            return cls.ORACLE_SUSPECT
        return None


class OperationalOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class SemanticInterpretation(StrEnum):
    CORRECT = "CORRECT"
    DEFENDIBLE = "DEFENDIBLE"
    INCORRECT = "INCORRECT"
    INDETERMINATE = "INDETERMINATE"
    NOT_EVALUATED = "NOT_EVALUATED"


class ContractualAdherence(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class CausalAttribution(StrEnum):
    NONE = "NONE"
    MODEL_OWNED_SEMANTIC_FAILURE = "MODEL_OWNED_SEMANTIC_FAILURE"
    MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE = (
        "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE"
    )
    MODEL_OWNED_SEMANTIC_AND_ADHERENCE_FAILURE = (
        "MODEL_OWNED_SEMANTIC_AND_ADHERENCE_FAILURE"
    )
    CORRECT_NEGATIVE_DECISION = "CORRECT_NEGATIVE_DECISION"
    ORACLE_SUSPECT = "ORACLE_SUSPECT"
    ORACLE_OR_CHECKPOINT_INVALID = "ORACLE_OR_CHECKPOINT_INVALID"
    CAUSE_INDETERMINATE = "CAUSE_INDETERMINATE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class CausalConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class CheckpointAssessment:
    checkpoint_id: str
    checkpoint_class: CheckpointClass
    operational_outcome: OperationalOutcome
    oracle_validity: OracleValidity
    semantic_interpretation: SemanticInterpretation
    contractual_adherence: ContractualAdherence
    causal_attribution: CausalAttribution
    causal_confidence: CausalConfidence
    semantic_review_id: str | None = None
    semantic_review_version: str | None = None
    semantic_review_hash: str | None = None
    reason_codes: tuple[str, ...] = ()

    def model_dump(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["reason_codes"] = list(self.reason_codes)
        return raw

    @classmethod
    def model_validate(cls, raw: dict[str, Any]) -> "CheckpointAssessment":
        return cls(
            checkpoint_id=str(raw["checkpoint_id"]),
            checkpoint_class=CheckpointClass(raw["checkpoint_class"]),
            operational_outcome=OperationalOutcome(raw["operational_outcome"]),
            oracle_validity=OracleValidity(raw["oracle_validity"]),
            semantic_interpretation=SemanticInterpretation(
                raw["semantic_interpretation"]
            ),
            contractual_adherence=ContractualAdherence(
                raw["contractual_adherence"]
            ),
            causal_attribution=CausalAttribution(raw["causal_attribution"]),
            causal_confidence=CausalConfidence(raw["causal_confidence"]),
            semantic_review_id=raw.get("semantic_review_id"),
            semantic_review_version=raw.get("semantic_review_version"),
            semantic_review_hash=raw.get("semantic_review_hash"),
            reason_codes=tuple(raw.get("reason_codes", ())),
        )


def classify_checkpoint(
    *,
    checkpoint_id: str,
    checkpoint_class: CheckpointClass | str,
    oracle_validity: OracleValidity | str,
    semantic_interpretation: SemanticInterpretation | str,
    contractual_adherence: ContractualAdherence | str,
    technical_failure: bool = False,
    semantic_review_id: str | None = None,
    semantic_review_version: str | None = None,
    semantic_review_hash: str | None = None,
    reason_codes: tuple[str, ...] | list[str] = (),
) -> CheckpointAssessment:
    """Classify one checkpoint without inferring blame from an error code."""

    checkpoint_class = CheckpointClass(checkpoint_class)
    oracle_validity = OracleValidity(oracle_validity)
    semantic_interpretation = SemanticInterpretation(semantic_interpretation)
    contractual_adherence = ContractualAdherence(contractual_adherence)
    reasons = tuple(dict.fromkeys(reason_codes))

    semantic_class = checkpoint_class in {
        CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
        CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
    }
    if semantic_class and oracle_validity == OracleValidity.VALID:
        if not all(
            (semantic_review_id, semantic_review_version, semantic_review_hash)
        ):
            raise ValueError(
                "a valid semantic checkpoint requires versioned review provenance"
            )
    if semantic_class and oracle_validity == OracleValidity.NOT_APPLICABLE:
        raise ValueError(
            "semantic checkpoints require an applicable oracle status"
        )
    if (
        checkpoint_class
        == CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY
        and semantic_interpretation
        != SemanticInterpretation.NOT_EVALUATED
    ):
        raise ValueError("structural-only checkpoints cannot rate semantic quality")

    if technical_failure:
        operational = OperationalOutcome.TECHNICAL_FAILURE
        causal = CausalAttribution.TECHNICAL_FAILURE
        confidence = CausalConfidence.HIGH
    elif oracle_validity == OracleValidity.ORACLE_SUSPECT:
        operational = OperationalOutcome.INCONCLUSIVE
        causal = CausalAttribution.ORACLE_SUSPECT
        confidence = CausalConfidence.LOW
    elif oracle_validity == OracleValidity.INVALID:
        operational = OperationalOutcome.INCONCLUSIVE
        causal = CausalAttribution.ORACLE_OR_CHECKPOINT_INVALID
        confidence = CausalConfidence.HIGH
    elif semantic_interpretation == SemanticInterpretation.INDETERMINATE:
        operational = OperationalOutcome.INCONCLUSIVE
        causal = CausalAttribution.CAUSE_INDETERMINATE
        confidence = CausalConfidence.LOW
    elif semantic_interpretation == SemanticInterpretation.INCORRECT:
        operational = OperationalOutcome.FAIL
        causal = (
            CausalAttribution.MODEL_OWNED_SEMANTIC_AND_ADHERENCE_FAILURE
            if contractual_adherence == ContractualAdherence.FAIL
            else CausalAttribution.MODEL_OWNED_SEMANTIC_FAILURE
        )
        confidence = CausalConfidence.HIGH
    elif contractual_adherence == ContractualAdherence.FAIL:
        operational = OperationalOutcome.FAIL
        causal = CausalAttribution.MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE
        confidence = CausalConfidence.HIGH
    elif (
        checkpoint_class
        == CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE
        and semantic_interpretation
        in {
            SemanticInterpretation.CORRECT,
            SemanticInterpretation.DEFENDIBLE,
        }
    ):
        operational = OperationalOutcome.PASS
        causal = CausalAttribution.CORRECT_NEGATIVE_DECISION
        confidence = CausalConfidence.HIGH
    elif contractual_adherence in {
        ContractualAdherence.PASS,
        ContractualAdherence.NOT_EVALUATED,
    } and semantic_interpretation in {
        SemanticInterpretation.CORRECT,
        SemanticInterpretation.DEFENDIBLE,
        SemanticInterpretation.NOT_EVALUATED,
    }:
        operational = OperationalOutcome.PASS
        causal = CausalAttribution.NONE
        confidence = CausalConfidence.NOT_APPLICABLE
    else:
        operational = OperationalOutcome.INCONCLUSIVE
        causal = CausalAttribution.CAUSE_INDETERMINATE
        confidence = CausalConfidence.LOW

    return CheckpointAssessment(
        checkpoint_id=checkpoint_id,
        checkpoint_class=checkpoint_class,
        operational_outcome=operational,
        oracle_validity=oracle_validity,
        semantic_interpretation=semantic_interpretation,
        contractual_adherence=contractual_adherence,
        causal_attribution=causal,
        causal_confidence=confidence,
        semantic_review_id=semantic_review_id,
        semantic_review_version=semantic_review_version,
        semantic_review_hash=semantic_review_hash,
        reason_codes=reasons,
    )


def aggregate_causal_classification(
    assessments: list[CheckpointAssessment] | tuple[CheckpointAssessment, ...],
) -> str:
    """Aggregate explicit evidence while preserving uncertainty and invalid oracles."""

    if not assessments:
        return "ORACLE_STATUS_MISSING"
    causes = {item.causal_attribution for item in assessments}
    oracle_statuses = {item.oracle_validity for item in assessments}
    technical = CausalAttribution.TECHNICAL_FAILURE in causes
    semantic_and_adherence = (
        CausalAttribution.MODEL_OWNED_SEMANTIC_AND_ADHERENCE_FAILURE in causes
    )
    semantic = CausalAttribution.MODEL_OWNED_SEMANTIC_FAILURE in causes
    adherence = (
        CausalAttribution.MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE in causes
    )
    if OracleValidity.ORACLE_SUSPECT in oracle_statuses:
        base = "ORACLE_SUSPECT"
    elif OracleValidity.INVALID in oracle_statuses:
        base = "ORACLE_OR_CHECKPOINT_INVALID"
    elif semantic_and_adherence or (semantic and adherence):
        base = "MODEL_OWNED_SEMANTIC_AND_ADHERENCE_FAILURE"
    elif semantic:
        base = "MODEL_OWNED_SEMANTIC_FAILURE"
    elif adherence:
        base = "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE"
    elif CausalAttribution.CAUSE_INDETERMINATE in causes:
        base = "CAUSE_INDETERMINATE"
    elif technical:
        return "TECHNICAL_QUALIFICATION_FAILURE"
    elif all(
        item.operational_outcome == OperationalOutcome.PASS
        for item in assessments
    ):
        return "QUALIFICATION_PASSED"
    else:
        base = "CAUSE_INDETERMINATE"
    return f"{base}_WITH_TECHNICAL_FAILURES" if technical else base
