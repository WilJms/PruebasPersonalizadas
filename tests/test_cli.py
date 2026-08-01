from __future__ import annotations

import json

from comprehension_verification.cli import main


def test_real_smoke_without_budget_is_blocked_before_network(capsys) -> None:
    result = main(["real-provider-smoke", "--budget-usd", "0"])

    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output == {
        "code": "REAL_SMOKE_BUDGET_REQUIRED",
        "network_call_attempted": False,
        "status": "BLOCKED",
    }


def test_insufficient_synthetic_case_is_expected_fail_closed(tmp_path) -> None:
    output = tmp_path / "insufficient"

    assert (
        main(
            [
                "run-synthetic",
                "--case",
                "insufficient",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["actual_status"] == (
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES"
    )
    assert manifest["expected_outcome_matched"] is True
    assert manifest["partial_assessment_emitted"] is False
    assert not (output / "assessment.json").exists()


def test_injection_case_stays_data_and_produces_reviewable_views(tmp_path) -> None:
    output = tmp_path / "injection"

    assert (
        main(
            [
                "run-synthetic",
                "--case",
                "injection",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["actual_status"] == "READY"
    assert manifest["assessment_status"] == "NEEDS_REVIEW"
    assert manifest["question_count"] == 3
    assert manifest["security"] == {
        "case": "injection",
        "generated_question_contains_injection": False,
        "model_tools_enabled": False,
        "network_provider_called": False,
        "source_contains_injection": True,
    }
    assert (output / "assessment.pdf").is_file()
    assert (output / "evaluation_guide.pdf").is_file()
    assert (output / "assessment.json").is_file()
    assert (output / "evaluation_guide.json").is_file()
