from __future__ import annotations

import pytest

from comprehension_verification.pipeline_authority import (
    ACTIVE_SUBMISSION_PIPELINE,
    BACKEND_DECISIONS,
    COMPATIBILITY_ONLY_FIELDS,
    DISABLED_MODEL_STAGE_IDS,
    HISTORICAL_HARNESS_EVIDENCE_STATUS,
    MODEL_DECISIONS,
    PIPELINE_AUTHORITY_VERSION,
    PIPELINE_CUTOVER_STATUS,
    TARGET_ACTIVE_MODEL_STAGE_IDS,
    TARGET_ACTIVITY_PIPELINE,
    TARGET_INACTIVE_MODEL_STAGE_IDS,
    TARGET_SUBMISSION_PIPELINE,
    TEACHER_DECISIONS,
    DecisionAuthority,
    authority_for,
    pipeline_authority_manifest,
)


def test_target_pipeline_order_and_stage_policy_are_executable() -> None:
    assert TARGET_ACTIVITY_PIPELINE == (
        "P01",
        "P02",
        "P03",
        "P04",
        "DETERMINISTIC_BLUEPRINT_PREFLIGHT",
        "TEACHER_BLUEPRINT_APPROVAL",
    )
    assert TARGET_SUBMISSION_PIPELINE == (
        "P06",
        "DETERMINISTIC_PLANNER",
        "P07",
        "DETERMINISTIC_QUESTION_VALIDATIONS",
        "TEACHER_QUESTION_REVIEW_APPROVAL",
        "P09",
    )
    assert TARGET_ACTIVE_MODEL_STAGE_IDS == (
        "P01",
        "P02",
        "P03",
        "P04",
        "P06",
        "P07",
        "P09",
    )
    assert TARGET_INACTIVE_MODEL_STAGE_IDS == ("P05", "P08")
    assert DISABLED_MODEL_STAGE_IDS == ("P10",)
    assert not (
        set(TARGET_ACTIVE_MODEL_STAGE_IDS)
        & set(TARGET_INACTIVE_MODEL_STAGE_IDS)
    )


def test_every_governed_decision_has_one_authority() -> None:
    assert set(BACKEND_DECISIONS) == {
        "ids",
        "versions",
        "hashes",
        "states",
        "lineage",
        "evidence_membership",
        "support_evidence",
        "canonical_visible_anchor",
        "allowlists",
        "formats",
        "count",
        "time_budgets",
        "constraints",
        "planner_feasibility",
        "storage",
        "transitions",
        "deterministic_validations",
    }
    assert set(MODEL_DECISIONS) == {
        "semantic_interpretation",
        "pedagogical_structure_proposal",
        "evidence_construct_relationship",
        "wording",
        "observables",
        "semantic_alternatives",
        "visible_anchor_selection_within_support",
    }
    assert set(TEACHER_DECISIONS) == {
        "academic_ambiguity_resolution",
        "blueprint_approval",
        "question_approve_edit_reject",
        "final_academic_authority",
    }
    assert authority_for("hashes") == DecisionAuthority.BACKEND
    assert authority_for("wording") == DecisionAuthority.MODEL
    assert authority_for("blueprint_approval") == DecisionAuthority.TEACHER
    with pytest.raises(ValueError, match="unknown governed decision"):
        authority_for("model_selection")


def test_manifest_marks_p08_retired_and_harness_historical() -> None:
    manifest = pipeline_authority_manifest()
    assert manifest["version"] == PIPELINE_AUTHORITY_VERSION
    assert manifest["cutover_status"] == PIPELINE_CUTOVER_STATUS
    assert PIPELINE_CUTOVER_STATUS == (
        "P08_RUNTIME_RETIRED_P09_RELOCATION_PENDING"
    )
    assert ACTIVE_SUBMISSION_PIPELINE == (
        "P06",
        "DETERMINISTIC_PLANNER",
        "P07",
        "DETERMINISTIC_QUESTION_VALIDATIONS",
        "ASSEMBLE",
        "P09",
        "TEACHER_QUESTION_REVIEW_APPROVAL",
    )
    assert manifest["active_interim_pipelines"]["submission"] == list(
        ACTIVE_SUBMISSION_PIPELINE
    )
    assert manifest["active_interim_pipelines"]["p09_relocation_pending"] is True
    assert COMPATIBILITY_ONLY_FIELDS["Anchor.self_containment_score"] == (
        "DERIVED_COMPATIBILITY_LEGACY_NO_ACTIVE_AUTHORITY"
    )
    assert manifest["compatibility_only_fields"] == dict(
        COMPATIBILITY_ONLY_FIELDS
    )
    assert manifest["historical_semantic_harness"] == {
        "evidence_status": HISTORICAL_HARNESS_EVIDENCE_STATUS,
        "model_selection_gate": False,
        "retain_reports_and_receipts": True,
    }
    assert manifest["model_stage_policy"] == {
        "active": list(TARGET_ACTIVE_MODEL_STAGE_IDS),
        "inactive": ["P05", "P08"],
        "disabled": ["P10"],
    }
