from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.pipeline_authority import (
    HISTORICAL_HARNESS_EVIDENCE_STATUS,
)
from comprehension_verification.semantic_benchmark import (
    ACTIVE_BENCHMARK_STAGES,
    BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
    CORPUS_VERSION,
    DEFAULT_CORPUS_ROOT,
    EXPECTED_CORPUS_PACKAGE_HASH,
    ResultState,
    SEMANTIC_BENCHMARK_VERSION,
    BenchmarkValidationError,
    aggregate_future_semantic_runs,
    benchmark_boundary,
    build_benchmark,
    load_corpus_package,
    make_review_packet,
    phase9_call_budget,
    project_model_visible_files,
    project_p09_questions,
    property_coverage,
    rare_case_coverage,
    reports_are_reproducible,
    run_offline_dry_run,
    split_manifest,
    validate_candidate_matrix_template,
)


@pytest.fixture(scope="module")
def benchmark_build():
    return build_benchmark(verify_parser_twice=False)


@pytest.fixture(scope="module")
def benchmark_replay():
    return build_benchmark(verify_parser_twice=False)


def test_expected_corpus_hash_and_frozen_counts_are_accepted(benchmark_build) -> None:
    package = benchmark_build.package
    counts = {
        state: sum(item["oracle_state"] == state for item in benchmark_build.properties)
        for state in ("VALID", "ORACLE_SUSPECT", "NOT_APPLICABLE", "INVALID")
    }
    assert CORPUS_VERSION == "pruebas-personalizadas-corpus/1.0.0"
    assert package.package_hash == EXPECTED_CORPUS_PACKAGE_HASH
    assert len(package.ratifications) == 12
    assert sum(len(item["submissions"]) for item in package.ratifications) == 72
    assert len(benchmark_build.properties) == 395
    assert counts == {
        "VALID": 361,
        "ORACLE_SUSPECT": 26,
        "NOT_APPLICABLE": 8,
        "INVALID": 0,
    }


def test_wrong_expected_corpus_hash_is_rejected() -> None:
    with pytest.raises(BenchmarkValidationError) as error:
        load_corpus_package(expected_hash="0" * 64)
    assert error.value.code == "BENCHMARK_CORPUS_BOUNDARY_MISMATCH"


def test_corpus_mutation_is_detected_before_case_build(tmp_path: Path) -> None:
    mutated = tmp_path / "corpus"
    shutil.copytree(DEFAULT_CORPUS_ROOT, mutated)
    target = mutated / "activity_01_luz_y_plantines/submissions/submission_01.txt"
    target.write_bytes(target.read_bytes() + b"\nmutation")
    with pytest.raises(BenchmarkValidationError) as error:
        load_corpus_package(mutated)
    assert error.value.code == "BENCHMARK_CORPUS_BOUNDARY_MISMATCH"


def test_vendored_snapshot_matches_every_frozen_manifest_byte(benchmark_build) -> None:
    package = benchmark_build.package
    for relative, entry in package.entries.items():
        path = package.root / relative
        assert path.stat().st_size == entry["bytes"]
    assert package.manifest["total_package_file_count"] == 218


@pytest.mark.parametrize(
    "forbidden_ref",
    [
        "activity_01_luz_y_plantines/final_ratification.json",
        "_audit_history/submission_id_mapping.json",
        "_audit_history/submission_id_mapping.json#strong",
    ],
)
def test_oracle_audit_and_old_labels_cannot_become_model_input(
    benchmark_build, forbidden_ref: str
) -> None:
    with pytest.raises(BenchmarkValidationError) as error:
        project_model_visible_files(benchmark_build.package, [forbidden_ref])
    assert error.value.code == BENCHMARK_ORACLE_LEAKAGE_BLOCKED


def test_p09_projection_keeps_questions_and_excludes_scoring_properties(
    benchmark_build,
) -> None:
    fixture_ref = next(
        path
        for path, entry in benchmark_build.package.entries.items()
        if entry["role"] == "P09_STAGE_FIXTURE"
    )
    projection, model_ref, oracle_ref = project_p09_questions(
        benchmark_build.package, fixture_ref
    )
    assert len(projection["questions"]) == 3
    assert "p09_properties" not in projection
    assert model_ref.endswith("#questions")
    assert oracle_ref.endswith("#p09_properties")
    assert model_ref != oracle_ref


def test_case_refs_are_disjoint_and_every_case_has_properties(benchmark_build) -> None:
    for case in benchmark_build.cases:
        assert set(case["model_visible_refs"]).isdisjoint(case["oracle_refs"])
        assert case["property_ids"]


@pytest.mark.parametrize("stage", ["P04", "P06", "P07"])
def test_stage_local_case_builder_identity_is_stable(
    benchmark_build, benchmark_replay, stage: str
) -> None:
    first = next(item for item in benchmark_build.cases if item["stage"] == stage)
    second = next(
        item for item in benchmark_replay.cases if item["case_id"] == first["case_id"]
    )
    assert first["input_hash"] == second["input_hash"]
    assert first["case_fingerprint"] == second["case_fingerprint"]


def test_four_frozen_p09_fixtures_have_twelve_questions(benchmark_build) -> None:
    assert len(benchmark_build.package.p09_fixtures) == 4
    assert sum(
        len(item["questions"]) for item in benchmark_build.package.p09_fixtures
    ) == 12
    assert sum(item["stage"] == "P09" for item in benchmark_build.cases) == 4


def test_all_deterministic_planner_cases_pass_exactly(benchmark_build) -> None:
    assert len(benchmark_build.planner_results) == 21
    assert {item["result"] for item in benchmark_build.planner_results} == {"PASS"}
    for item in benchmark_build.planner_results:
        assert item["actual_status"] == item["expected_status"]
        if item["actual_status"] == "READY":
            assert item["selected_count"] == item["required_count"] == 3
        else:
            assert item["selected_count"] == 0


def test_split_is_deterministic_and_held_out_is_activity_locked(
    benchmark_build, benchmark_replay
) -> None:
    assert split_manifest(benchmark_build.cases) == split_manifest(benchmark_replay.cases)
    held = [
        item
        for item in benchmark_build.cases
        if item["split"] == "HELD_OUT_CONFIRMATION" and item["stage"] != "P09"
    ]
    assert {_activity_number(item["activity_id"]) for item in held} == {3, 8, 9, 10, 12}
    assert {item["stage"] for item in benchmark_build.cases if item["split"] == "SMOKE"} == {
        "P04",
        "P06",
        "PLANNER",
        "P07",
        "P09",
    }


def _activity_number(activity_id: str) -> int:
    return int(activity_id.split("_", 2)[1])


def test_rare_case_families_remain_catalogued(benchmark_build) -> None:
    coverage = rare_case_coverage(benchmark_build)
    assert set(coverage["families"]) == {
        "silent_conceptual_gap",
        "p06_uncertain",
        "simulated_pii",
        "silent_prompt_injection",
        "authorized_source_adversarial",
        "multi_artifact",
        "answer_leakage",
        "planner_infeasibility",
        "p09_cannot_infer",
    }


def test_oracle_suspect_and_non_outcome_states_are_excluded_from_hard_denominator(
    benchmark_build,
) -> None:
    hard = next(
        item
        for item in benchmark_build.properties
        if item["hardness"] == "HARD_SEMANTIC_PROPERTY"
        and item["oracle_state"] == "VALID"
    )
    suspect = next(
        item for item in benchmark_build.properties if item["oracle_state"] == "ORACLE_SUSPECT"
    )

    def row(item: dict[str, object], run: int, state: str) -> dict[str, object]:
        return {
            "case_id": "case_aggregation",
            "property_id": item["property_id"],
            "run_index": run,
            "stage": item["stage"],
            "candidate_id": "candidate_test",
            "reasoning_effort": "test",
            "split": "SMOKE",
            "discipline": "test",
            "difficulty": "SIMPLE",
            "property_kind": item["kind"],
            "tags": [],
            "result_state": state,
        }

    report = aggregate_future_semantic_runs(
        [
            row(hard, 1, "PASS"),
            row(hard, 2, "MODEL_FAILURE"),
            row(suspect, 1, "MODEL_FAILURE"),
        ],
        properties=benchmark_build.properties,
    )
    assert report["hard_model_failure_denominator"] == 2
    assert report["hard_model_failure_rate"] == 0.5
    assert report["case_stability"]["case_aggregation|candidate_test|test"][
        "disagreement"
    ] is True


def test_result_states_are_explicit_and_distinct() -> None:
    assert len(ResultState) == 7
    assert ResultState.DEFENSIBLE_ALTERNATIVE != ResultState.PASS
    assert ResultState.DEFENSIBLE_ALTERNATIVE != ResultState.MODEL_FAILURE
    assert ResultState.PENDING_ADJUDICATION != ResultState.TECHNICAL_FAILURE


def test_provider_call_count_is_zero_and_semantic_scoring_is_not_faked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CVA_MODEL_MODE", "mock")
    monkeypatch.setenv("CVA_P10_ENABLED", "false")
    result = run_offline_dry_run(
        report_root=tmp_path, verify_parser_twice=False
    )
    semantic = json.loads((tmp_path / "semantic_dry_run_report.json").read_text())
    assert result["provider_calls"] == 0
    assert result["billable_authorizations"] == 0
    assert result["real_transport"] is False
    assert semantic["mock_outputs_scored"] is False
    assert set(semantic["outcome_counts"]) <= {
        "PENDING_ADJUDICATION",
        "NOT_APPLICABLE",
    }


def test_offline_modules_do_not_import_provider_call_surfaces() -> None:
    roots = [
        Path("src/comprehension_verification/semantic_benchmark.py"),
        Path("src/comprehension_verification/semantic_benchmark_fixtures.py"),
        Path("scripts/run_semantic_benchmark.py"),
    ]
    forbidden = {
        "model_gateway",
        "openai_adapter",
        "provider_authorization",
        "provider_secrets",
    }
    imported: set[str] = set()
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not any(
        token in module for token in forbidden for module in imported
    ), imported


def test_provider_key_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    with pytest.raises(BenchmarkValidationError) as error:
        run_offline_dry_run(
            report_root=tmp_path,
            write_reports=False,
            verify_parser_twice=False,
        )
    assert error.value.code == "BENCHMARK_PROVIDER_KEY_PRESENT"


def test_only_current_stages_are_active_and_historical_harness_is_retained() -> None:
    assert ACTIVE_BENCHMARK_STAGES == ("P04", "P06", "PLANNER", "P07", "P09")
    assert "P05" not in ACTIVE_BENCHMARK_STAGES
    assert "P08" not in ACTIVE_BENCHMARK_STAGES
    assert "P10" not in ACTIVE_BENCHMARK_STAGES
    assert HISTORICAL_HARNESS_EVIDENCE_STATUS == "HISTORICAL_NON_CANONICAL_EVIDENCE"
    historical = Path("src/comprehension_verification/semantic_harness.py")
    assert historical.is_file() and historical.stat().st_size > 0


def test_benchmark_boundary_and_reports_are_reproducible(
    benchmark_build, benchmark_replay, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert benchmark_boundary(benchmark_build)["benchmark_boundary_hash"] == benchmark_boundary(
        benchmark_replay
    )["benchmark_boundary_hash"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CVA_MODEL_MODE", "mock")
    monkeypatch.setenv("CVA_P10_ENABLED", "false")
    left = tmp_path / "left"
    right = tmp_path / "right"
    first = run_offline_dry_run(report_root=left, verify_parser_twice=False)
    second = run_offline_dry_run(report_root=right, verify_parser_twice=False)
    assert first["reports_hash"] == second["reports_hash"]
    assert reports_are_reproducible(left, right)


def test_boundary_is_reproducible_across_processes() -> None:
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("CVA_OPENAI_API_KEY", None)
    env.update({"CVA_MODEL_MODE": "mock", "CVA_P10_ENABLED": "false"})
    command = [
        sys.executable,
        "scripts/run_semantic_benchmark.py",
        "--no-write-reports",
        "--single-parser-pass",
    ]
    outputs = [
        json.loads(
            subprocess.run(
                command,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        for _ in range(2)
    ]
    assert outputs[0]["benchmark_boundary_hash"] == outputs[1]["benchmark_boundary_hash"]
    assert outputs[0]["reports_hash"] == outputs[1]["reports_hash"]


def test_candidate_matrix_is_unset_and_has_no_implicit_authorization() -> None:
    template = validate_candidate_matrix_template()
    assert template["matrix_status"] == "UNSET"
    assert template["authorization"] == "NONE"
    assert template["qualification_thresholds"] == "UNSET"
    assert {item["model"] for item in template["candidates"]} == {"UNSET"}


def test_phase9_budget_counts_model_calls_but_never_planner_calls(benchmark_build) -> None:
    budget = phase9_call_budget(benchmark_build.cases)
    assert budget["available_cases_by_stage"] == {
        "P04": 12,
        "P06": 69,
        "P07": 72,
        "P09": 4,
        "PLANNER": 21,
    }
    assert budget["projections_for_one_hypothetical_candidate"]["k=1"][
        "total_model_calls"
    ] == 157
    assert budget["projections_for_one_hypothetical_candidate"]["k=3"][
        "total_model_calls"
    ] == 471
    assert budget["projections_for_one_hypothetical_candidate"]["k=3"][
        "planner_calls"
    ] == 0


def test_property_coverage_has_no_hidden_gap(benchmark_build) -> None:
    coverage = property_coverage(benchmark_build)
    assert coverage["property_count"] == 395
    assert coverage["unexplained_uncovered_count"] == 0
    assert coverage["case_without_property_count"] == 0
    assert coverage["case_bound_count"] + coverage["explicitly_excluded_count"] == 395


def test_review_packet_schema_uses_only_one_case_and_property(benchmark_build) -> None:
    prop = next(
        item
        for item in benchmark_build.properties
        if item["evaluator_mode"] == "EXTERNAL_ADJUDICATION_REQUIRED"
        and item["property_id"]
        in {value for case in benchmark_build.cases for value in case["property_ids"]}
    )
    case = next(
        item for item in benchmark_build.cases if prop["property_id"] in item["property_ids"]
    )
    packet = make_review_packet(
        case=case,
        property_value=prop,
        candidate_output={"synthetic_schema_fixture": True},
    )
    assert packet["case_id"] == case["case_id"]
    assert packet["property"]["property_id"] == prop["property_id"]
    assert packet["candidate_output_hash"] == canonical_hash(
        {"synthetic_schema_fixture": True}
    )


def test_semantic_benchmark_version_is_not_the_historical_harness_version() -> None:
    assert SEMANTIC_BENCHMARK_VERSION == "semantic-benchmark/1.0.0"
