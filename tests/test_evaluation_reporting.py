from __future__ import annotations

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.evaluation_reporting import (
    DIAGNOSTIC_CODE_POLICY_VERSION,
    prepare_historical_harness_report,
    synthetic_diagnostic_codes,
)
from comprehension_verification.pipeline_authority import (
    HISTORICAL_HARNESS_EVIDENCE_STATUS,
    PIPELINE_AUTHORITY_VERSION,
)


def test_synthetic_reports_retain_clear_enumerated_diagnostic_codes() -> None:
    report = {
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "checkpoint_assessments": [
            {"reason_codes": ["P08_ORACLE_DISAGREEMENT", "P07_INVALID"]}
        ],
        "observations": [
            {
                "failure": {"codes": ["MODEL_PROVIDER_ERROR"]},
                "diagnostics": [
                    {"code": "QUESTION_POLICY_VIOLATION", "message": "ignored"}
                ],
            }
        ],
        "free_text": "MUST_NOT_BECOME_A_DIAGNOSTIC_CODE",
    }
    normalized = prepare_historical_harness_report(report)
    expected = [
        "MODEL_PROVIDER_ERROR",
        "P07_INVALID",
        "P08_ORACLE_DISAGREEMENT",
        "QUESTION_POLICY_VIOLATION",
    ]
    assert synthetic_diagnostic_codes(report) == expected
    assert normalized["diagnostic_codes"] == expected
    assert normalized["diagnostic_codes_hash"] == canonical_hash(expected)
    assert normalized["diagnostic_code_policy_version"] == (
        DIAGNOSTIC_CODE_POLICY_VERSION
    )
    assert normalized["evidence_status"] == (
        HISTORICAL_HARNESS_EVIDENCE_STATUS
    )
    assert normalized["model_selection_gate"] is False
    assert normalized["pipeline_authority_version"] == (
        PIPELINE_AUTHORITY_VERSION
    )
    assert "MUST_NOT_BECOME_A_DIAGNOSTIC_CODE" not in expected


def test_non_synthetic_reports_keep_the_existing_content_free_policy() -> None:
    report = {
        "classification": "CONTENT_FREE_STUDENT_DATA_REPORT",
        "failure": {"codes": ["STUDENT_CONTENT_MUST_NOT_BE_ENUMERATED"]},
    }
    assert prepare_historical_harness_report(report) is report
    assert "diagnostic_codes" not in report
    assert "evidence_status" not in report
