from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from comprehension_verification.contract_validation import (
    EXPECTED_CONTRACT_ROOT_COUNT,
    EXPECTED_DOCUMENTED_FIXTURE_COUNT,
    ContractValidationError,
    assert_schema_has_no_drift,
    compile_canonical_models,
    crawl_schema_references,
    extract_documented_contract_fixtures,
    extract_markdown_contract_fixtures,
    load_schema_bundle,
    validate_documented_contract_fixtures,
    validate_json_boundary,
    validate_schema_bundle,
)
from comprehension_verification.contracts import (
    CANONICAL_MODELS_PATH,
    CONTRACT_MODELS,
    SCHEMA_VERSION,
    models,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "contracts" / "v1.1"

STAGE2_VALID_FIXTURES = (
    ("StageRun", "stage_run_succeeded.json"),
    ("JobControlRecord", "job_control_retry_applied.json"),
    ("CoverageReport", "coverage_report_submission.json"),
    ("ExportRecord", "export_record_ready.json"),
    ("ExperimentMetrics", "experiment_metrics.json"),
    ("FeedbackEvent", "feedback_event_question.json"),
    ("QuestionReviewActionRecord", "question_review_action_record_failed.json"),
)

STAGE2_INVALID_FIXTURES = (
    ("StageRun", "stage_run_failed_without_class.json"),
    ("JobControlRecord", "job_control_permanent_retry_applied.json"),
    ("CoverageReport", "coverage_report_count_mismatch.json"),
    ("ExportRecord", "export_record_with_capability.json"),
    ("FeedbackEvent", "feedback_event_target_mismatch.json"),
)


def _fixture_bytes(kind: str, filename: str) -> bytes:
    return (FIXTURE_ROOT / kind / filename).read_bytes()


def test_canonical_models_pass_py_compile_without_local_bytecode() -> None:
    canonical_cache = CANONICAL_MODELS_PATH.parent / "__pycache__"
    before = set(canonical_cache.iterdir()) if canonical_cache.is_dir() else set()

    compile_canonical_models()

    after = set(canonical_cache.iterdir()) if canonical_cache.is_dir() else set()
    assert after == before


def test_schema_regeneration_is_byte_identical() -> None:
    assert_schema_has_no_drift()


def test_schema_bundle_has_exact_roots_and_resolvable_refs() -> None:
    bundle = load_schema_bundle()

    report = validate_schema_bundle(bundle)
    references = crawl_schema_references(bundle)

    assert report.root_names == tuple(model.__name__ for model in CONTRACT_MODELS)
    assert len(report.root_names) == EXPECTED_CONTRACT_ROOT_COUNT == 53
    assert report.definition_count == 140
    assert report.reference_count == len(references) == 275
    assert bundle["version"] == models.CONTRACT_VERSION == "1.2.0"
    assert models.SCHEMA_VERSION == SCHEMA_VERSION == "1.1.0"
    assert all(reference.startswith("#/$defs/") for _, reference in references)


def test_v12_bundle_preserves_v11_root_payloads() -> None:
    bundle = load_schema_bundle()

    legacy = validate_json_boundary(
        "AssessmentPlan",
        _fixture_bytes("valid", "assessment_plan_ready.json"),
    )

    assert legacy.schema_version == "1.1.0"
    assert bundle["$defs"]["AssessmentPlan"]["properties"]["schema_version"] == {
        "const": "1.1.0",
        "default": "1.1.0",
        "title": "Schema Version",
        "type": "string",
    }
    for root_name, _ in STAGE2_VALID_FIXTURES:
        assert (
            bundle["$defs"][root_name]["properties"]["schema_version"]["const"]
            == "1.2.0"
        )


def test_reference_crawler_rejects_a_missing_target() -> None:
    bundle = load_schema_bundle()
    bundle["roots"]["Diagnostic"] = {"$ref": "#/$defs/DoesNotExist"}

    with pytest.raises(ContractValidationError, match="Unresolvable"):
        crawl_schema_references(bundle)


def test_documented_extractor_finds_only_the_eight_real_fixtures() -> None:
    fixtures = extract_documented_contract_fixtures()

    assert len(fixtures) == EXPECTED_DOCUMENTED_FIXTURE_COUNT == 8
    assert Counter(fixture.schema_name for fixture in fixtures) == Counter(
        {
            "ModelTaskEnvelope": 1,
            "QuestionGenerationResult": 1,
            "ModelCallLedger": 1,
            "EvidenceUnit": 1,
            "QuestionOpportunityTemplate": 1,
            "AssessmentPlan": 1,
            "ProblemDetail": 1,
            "DomainEvent": 1,
        }
    )


def test_extractor_ignores_tags_inside_non_json_fences(tmp_path: Path) -> None:
    markdown = tmp_path / "fixtures.md"
    markdown.write_text(
        """````text
<!-- contract-fixture: MustBeIgnored -->
```json
{"not": "a real fixture"}
```
````

<!-- contract-fixture: ProblemDetail -->
```json
{
  "title": "A valid problem",
  "status": 422,
  "detail": "A deterministic test detail",
  "code": "VALIDATION_FAILED"
}
```
""",
        encoding="utf-8",
    )

    fixtures = extract_markdown_contract_fixtures(markdown)

    assert [fixture.schema_name for fixture in fixtures] == ["ProblemDetail"]


def test_all_documented_fixtures_pass_json_schema_and_pydantic() -> None:
    validated = validate_documented_contract_fixtures()

    assert len(validated) == EXPECTED_DOCUMENTED_FIXTURE_COUNT
    assert {item.__class__.__name__ for item in validated} == {
        fixture.schema_name for fixture in extract_documented_contract_fixtures()
    }


def test_strict_boundary_accepts_valid_contract() -> None:
    result = validate_json_boundary(
        "AssessmentPlan",
        _fixture_bytes("valid", "assessment_plan_ready.json"),
    )

    assert result.status == "READY"
    assert result.question_count == 2


@pytest.mark.parametrize(
    "filename, expected_rule",
    [
        ("assessment_plan_extra_property.json", "additionalProperties"),
        ("assessment_plan_coerced_count.json", "type"),
    ],
)
def test_strict_boundary_rejects_schema_violations(
    filename: str, expected_rule: str
) -> None:
    with pytest.raises(ContractValidationError, match=expected_rule):
        validate_json_boundary("AssessmentPlan", _fixture_bytes("invalid", filename))


def test_strict_boundary_requires_explicit_schema_version() -> None:
    raw = _fixture_bytes("invalid", "assessment_plan_missing_version.json")

    # The generated schema carries a default, but an exchanged root must state
    # its version explicitly so an unversioned payload cannot inherit "current".
    with pytest.raises(ContractValidationError, match="explicit schema_version"):
        validate_json_boundary("AssessmentPlan", raw)


def test_strict_boundary_runs_pydantic_cross_field_validators() -> None:
    raw = _fixture_bytes("invalid", "assessment_plan_failed_with_partial.json")

    with pytest.raises(ContractValidationError, match="Pydantic contract"):
        validate_json_boundary("AssessmentPlan", raw)


@pytest.mark.parametrize(("root_name", "filename"), STAGE2_VALID_FIXTURES)
def test_stage2_roots_accept_valid_fixtures(root_name: str, filename: str) -> None:
    result = validate_json_boundary(root_name, _fixture_bytes("valid", filename))

    assert result.schema_version == "1.2.0"


@pytest.mark.parametrize(("root_name", "filename"), STAGE2_INVALID_FIXTURES)
def test_stage2_model_validators_reject_invalid_fixtures(
    root_name: str, filename: str
) -> None:
    with pytest.raises(ContractValidationError, match="Pydantic contract"):
        validate_json_boundary(root_name, _fixture_bytes("invalid", filename))


def test_stage2_metrics_reject_duplicate_dimensions() -> None:
    payload = json.loads(_fixture_bytes("valid", "experiment_metrics.json"))
    payload["by_stage"].append(dict(payload["by_stage"][0]))

    with pytest.raises(ContractValidationError, match="Pydantic contract"):
        validate_json_boundary("ExperimentMetrics", json.dumps(payload))


def test_stage2_review_record_rejects_failed_result_without_diagnostics() -> None:
    payload = json.loads(
        _fixture_bytes("valid", "question_review_action_record_failed.json")
    )
    payload["diagnostics"] = []

    with pytest.raises(ContractValidationError, match="Pydantic contract"):
        validate_json_boundary("QuestionReviewActionRecord", json.dumps(payload))


def test_export_record_schema_has_no_capability_fields() -> None:
    properties = load_schema_bundle()["$defs"]["ExportRecord"]["properties"]

    assert not {
        "download_url",
        "signed_url",
        "capability",
        "access_token",
        "expires_at",
    }.intersection(properties)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1.1.0","plan_id":"plan_a","plan_id":"plan_b"}',
        b'{"schema_version":"1.1.0","value":NaN}',
        b'[]',
    ],
)
def test_strict_boundary_rejects_non_strict_json(raw: bytes) -> None:
    with pytest.raises(ContractValidationError):
        validate_json_boundary("AssessmentPlan", raw)


def test_format_checker_rejects_naive_datetime() -> None:
    event = {
        "schema_version": "1.1.0",
        "event_id": "evt_fixture",
        "event_type": "assessment.created",
        "event_version": "1.1.0",
        "occurred_at": "2026-07-31T12:00:00",
        "tenant_id": "tnt_fixture",
        "aggregate_id": "assessment_fixture",
        "aggregate_version": 1,
        "actor": {"kind": "SYSTEM", "id": "sys_fixture"},
        "correlation_id": "job_fixture",
        "payload": {},
    }

    with pytest.raises(ContractValidationError, match="format"):
        validate_json_boundary("DomainEvent", json.dumps(event))
