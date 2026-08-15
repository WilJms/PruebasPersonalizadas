"""Normative target authority for the Stage 2 pipeline simplification.

P05 has been removed from active product routing while its historical evidence
remains readable.  The independent P08 cutover is still pending.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


PIPELINE_AUTHORITY_VERSION = "pipeline-authority/1.0.0"
PIPELINE_CUTOVER_STATUS = "P05_RUNTIME_CUTOVER_COMPLETE_P08_PENDING"
HISTORICAL_HARNESS_EVIDENCE_STATUS = "HISTORICAL_NON_CANONICAL_EVIDENCE"

TARGET_ACTIVITY_PIPELINE = (
    "P01",
    "P02",
    "P03",
    "P04",
    "DETERMINISTIC_BLUEPRINT_PREFLIGHT",
    "TEACHER_BLUEPRINT_APPROVAL",
)
TARGET_SUBMISSION_PIPELINE = (
    "P06",
    "DETERMINISTIC_PLANNER",
    "P07",
    "DETERMINISTIC_QUESTION_VALIDATIONS",
    "TEACHER_QUESTION_REVIEW_APPROVAL",
    "P09",
)
TARGET_ACTIVE_MODEL_STAGE_IDS = (
    "P01",
    "P02",
    "P03",
    "P04",
    "P06",
    "P07",
    "P09",
)
TARGET_INACTIVE_MODEL_STAGE_IDS = ("P05", "P08")
DISABLED_MODEL_STAGE_IDS = ("P10",)


class DecisionAuthority(StrEnum):
    BACKEND = "BACKEND"
    MODEL = "MODEL"
    TEACHER = "TEACHER"


@dataclass(frozen=True, slots=True)
class DecisionAuthorityRule:
    decision_id: str
    authority: DecisionAuthority


BACKEND_DECISIONS = (
    "ids",
    "versions",
    "hashes",
    "states",
    "lineage",
    "evidence_membership",
    "allowlists",
    "formats",
    "count",
    "time_budgets",
    "constraints",
    "planner_feasibility",
    "storage",
    "transitions",
    "deterministic_validations",
)
MODEL_DECISIONS = (
    "semantic_interpretation",
    "pedagogical_structure_proposal",
    "evidence_construct_relationship",
    "wording",
    "observables",
    "semantic_alternatives",
)
TEACHER_DECISIONS = (
    "academic_ambiguity_resolution",
    "blueprint_approval",
    "question_approve_edit_reject",
    "final_academic_authority",
)

DECISION_AUTHORITY_RULES = tuple(
    DecisionAuthorityRule(decision_id, authority)
    for authority, decisions in (
        (DecisionAuthority.BACKEND, BACKEND_DECISIONS),
        (DecisionAuthority.MODEL, MODEL_DECISIONS),
        (DecisionAuthority.TEACHER, TEACHER_DECISIONS),
    )
    for decision_id in decisions
)
DECISION_AUTHORITY_BY_ID = MappingProxyType(
    {rule.decision_id: rule.authority for rule in DECISION_AUTHORITY_RULES}
)

if len(DECISION_AUTHORITY_BY_ID) != len(DECISION_AUTHORITY_RULES):
    raise RuntimeError("decision authority IDs must be unique")
if set(TARGET_ACTIVE_MODEL_STAGE_IDS) & set(TARGET_INACTIVE_MODEL_STAGE_IDS):
    raise RuntimeError("active and inactive model stages must be disjoint")
if set(TARGET_ACTIVE_MODEL_STAGE_IDS) & set(DISABLED_MODEL_STAGE_IDS):
    raise RuntimeError("active and disabled model stages must be disjoint")


def authority_for(decision_id: str) -> DecisionAuthority:
    """Return the single normative authority for a governed decision."""

    try:
        return DECISION_AUTHORITY_BY_ID[decision_id]
    except KeyError as exc:
        raise ValueError(f"unknown governed decision: {decision_id}") from exc


def pipeline_authority_manifest() -> dict[str, Any]:
    """Return a JSON-shaped, deterministic statement of the approved target."""

    return {
        "version": PIPELINE_AUTHORITY_VERSION,
        "cutover_status": PIPELINE_CUTOVER_STATUS,
        "target_pipelines": {
            "activity": list(TARGET_ACTIVITY_PIPELINE),
            "submission": list(TARGET_SUBMISSION_PIPELINE),
        },
        "model_stage_policy": {
            "active": list(TARGET_ACTIVE_MODEL_STAGE_IDS),
            "inactive": list(TARGET_INACTIVE_MODEL_STAGE_IDS),
            "disabled": list(DISABLED_MODEL_STAGE_IDS),
        },
        "decision_authority": {
            authority.value: [
                rule.decision_id
                for rule in DECISION_AUTHORITY_RULES
                if rule.authority == authority
            ]
            for authority in DecisionAuthority
        },
        "historical_semantic_harness": {
            "evidence_status": HISTORICAL_HARNESS_EVIDENCE_STATUS,
            "model_selection_gate": False,
            "retain_reports_and_receipts": True,
        },
    }
