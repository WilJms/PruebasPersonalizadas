from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from docx import Document
from jsonschema import Draft202012Validator, ValidationError

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.pipeline_authority import (
    HISTORICAL_HARNESS_EVIDENCE_STATUS,
)
from comprehension_verification.semantic_benchmark import (
    ACTIVE_BENCHMARK_STAGES,
    BENCHMARK_DEFINITION_ROOT,
    BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
    CORPUS_VERSION,
    DEFAULT_CORPUS_ROOT,
    DETERMINISTIC_INVARIANT_DEFINITIONS,
    EXPECTED_CORPUS_PACKAGE_HASH,
    ResultState,
    SEMANTIC_BENCHMARK_VERSION,
    BenchmarkValidationError,
    _binding_arbitrariness,
    aggregate_future_semantic_runs,
    benchmark_boundary,
    build_benchmark,
    load_corpus_package,
    make_review_packet,
    p04_source_coverage_report,
    p09_fixture_integrity_report,
    phase9_call_budget,
    project_model_visible_files,
    project_p09_questions,
    property_coverage,
    property_fixture_alignment,
    rare_case_coverage,
    reports_are_reproducible,
    run_offline_dry_run,
    split_manifest,
    tag_scope_report,
    validate_candidate_matrix_template,
)
from comprehension_verification.semantic_benchmark_fixtures import (
    build_p04_fixture,
    build_p07_fixture,
    parse_submission_bundle,
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
    assert {_activity_number(item["activity_id"]) for item in held} == {3, 7, 9, 10, 12}
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
    assert report["hard_model_failure_denominator"] == 1
    assert report["hard_property_run_denominator"] == 2
    assert report["hard_model_failure_rate"] == 1.0
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
    assert result["deterministic_passed"] == result["deterministic_total"] == 17
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
        "P06": 127,
        "P07": 108,
        "P09": 4,
        "PLANNER": 21,
    }
    assert budget["projections_for_one_hypothetical_candidate"]["k=1"][
        "total_model_calls"
    ] == 251
    assert budget["projections_for_one_hypothetical_candidate"]["k=3"][
        "total_model_calls"
    ] == 753
    assert budget["projections_for_one_hypothetical_candidate"]["k=3"][
        "planner_calls"
    ] == 0


def test_property_coverage_has_no_hidden_gap(benchmark_build) -> None:
    coverage = property_coverage(benchmark_build)
    assert coverage["property_count"] == 395
    assert coverage["unexplained_uncovered_count"] == 0
    assert coverage["case_without_property_count"] == 0
    assert (
        coverage["case_bound_count"]
        + coverage["explicitly_excluded_count"]
        + coverage["not_applicable_count"]
        == 395
    )
    assert coverage["assigned_arbitrarily_count"] == 0


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
    binding = next(
        item
        for item in benchmark_build.property_alignment
        if item["property_id"] == prop["property_id"]
    )
    packet = make_review_packet(
        case=case,
        property_value=prop,
        binding=binding,
        candidate_output={"synthetic_schema_fixture": True},
    )
    assert packet["case_id"] == case["case_id"]
    assert packet["property"]["property_id"] == prop["property_id"]
    assert packet["candidate_output_hash"] == canonical_hash(
        {"synthetic_schema_fixture": True}
    )
    assert packet["binding_scope"] == binding["binding_scope"]
    assert packet["fixture_id"] == binding["fixture_id"]


def test_semantic_benchmark_version_is_not_the_historical_harness_version() -> None:
    assert SEMANTIC_BENCHMARK_VERSION == "semantic-benchmark/1.1.0"


def test_p04_projects_every_assignment_and_rubric_unit_without_oracle(
    benchmark_build,
) -> None:
    report = p04_source_coverage_report(benchmark_build)
    assert report["activity_count"] == report["complete_activity_count"] == 12
    assert report["assignment_coverage"] == report["rubric_coverage"] == 1.0
    assert report["oracle_reads"] == 0
    assert sum(item["assignment_units_total"] for item in report["rows"]) == 682
    assert sum(item["rubric_units_total"] for item in report["rows"]) == 470
    for row in report["rows"]:
        assert row["assignment_units_total"] == row["assignment_units_projected"]
        assert row["rubric_units_total"] == row["rubric_units_projected"]

    builder_source = inspect.getsource(build_p04_fixture)
    assert "final_ratification" not in builder_source
    assert "compiled_properties" not in builder_source
    assert "_audit_history" not in builder_source
    assert "opus" not in builder_source.casefold()
    assert "[:3]" not in builder_source


def test_p04_contract_required_fields_stay_scale_neutral() -> None:
    """The projection must not smuggle a judgement into a required field.

    ``verification_fit`` has no neutral member, so the projection has to pick
    one.  It picks the mid-point, applies it to every criterion so it carries no
    differential signal, and never claims the maximum of the scale for source
    text the teacher never graded.  ``certainty`` stays EXPLICIT because each
    requirement really is a verbatim projection of an explicit unit.
    """

    request, _coverage = build_p04_fixture(
        corpus_root=DEFAULT_CORPUS_ROOT,
        activity_path="activity_01_luz_y_plantines",
        activity_id="act_01_luz_y_plantines",
    )
    fits = {item.verification_fit for item in request.rubric_spec.criteria}
    assert fits == {"MEDIUM"}
    assert "HIGH" not in fits
    assert {item.certainty for item in request.activity_spec.requirements} == {
        "EXPLICIT"
    }
    assert all(
        item.grading_weight is None and not item.levels and not item.observables
        for item in request.rubric_spec.criteria
    )
    assert request.rubric_spec.reported_weight_total is None


def test_p04_late_assignment_unit_changes_the_source_faithful_input_hash(
    tmp_path: Path,
) -> None:
    activity_path = "activity_01_luz_y_plantines"
    target = tmp_path / activity_path
    target.mkdir(parents=True)
    for filename in ("01_assignment.docx", "02_rubric.docx"):
        shutil.copy2(DEFAULT_CORPUS_ROOT / activity_path / filename, target / filename)
    before, before_coverage = build_p04_fixture(
        corpus_root=tmp_path,
        activity_path=activity_path,
        activity_id="act_01_luz_y_plantines",
    )
    document = Document(target / "01_assignment.docx")
    late = next(item for item in reversed(document.paragraphs) if item.text.strip())
    late.text += " [late-unit-regression-probe]"
    document.save(target / "01_assignment.docx")
    after, after_coverage = build_p04_fixture(
        corpus_root=tmp_path,
        activity_path=activity_path,
        activity_id="act_01_luz_y_plantines",
    )
    assert canonical_hash(before.model_dump(mode="json")) != canonical_hash(
        after.model_dump(mode="json")
    )
    assert before_coverage["assignment_units_total"] == before_coverage[
        "assignment_units_projected"
    ]
    assert after_coverage["assignment_units_total"] == after_coverage[
        "assignment_units_projected"
    ]


def test_all_p06_cases_have_explicit_source_grounded_routes_without_oracle_leakage(
    benchmark_build,
) -> None:
    routes = benchmark_build.fixture_definitions["p06_routes"]["routes"]
    case_by_id = {item["case_id"]: item for item in benchmark_build.cases}
    assert len(routes) == 127
    forbidden_literals = {"SUFFICIENT", "PARTIAL", "INSUFFICIENT", "UNCERTAIN"}
    sampled_disciplines: set[str] = set()
    for route in routes:
        case_id = "PP-" + route["route_fixture_id"].removeprefix("P06-").replace(
            "-R", "-P06-R"
        )
        case = case_by_id[case_id]
        sampled_disciplines.add(case["discipline"])
        assert case["submission_id"] == route["submission_id"]
        assert set(route["oracle_binding_metadata"]["property_ids"]).issubset(
            case["property_ids"]
        )
        assert route["source_provenance"]
        assert all(
            source["relative_ref"].startswith(
                benchmark_build.package.activity_by_id[route["activity_id"]][
                    "activity_path"
                ]
            )
            and source["resolved_units"]
            for source in route["source_provenance"]
        )
        model_visible = json.dumps(
            route["model_visible_definition"], ensure_ascii=False, sort_keys=True
        )
        assert not any(value in model_visible for value in forbidden_literals)
        assert not any(
            property_id in model_visible
            for property_id in route["oracle_binding_metadata"]["property_ids"]
        )
    assert len(sampled_disciplines) >= 6


def test_p06_insufficient_tag_comes_from_the_direct_route_property_only(
    benchmark_build,
) -> None:
    uncertainty = next(
        item
        for item in benchmark_build.cases
        if item["case_id"] == "PP-A01-S01-P06-R01"
    )
    insufficient = next(
        item
        for item in benchmark_build.cases
        if item["case_id"] == "PP-A01-S03-P06-R01"
    )
    assert "P06_UNCERTAIN" in uncertainty["tags"]
    assert "P06_INSUFFICIENT" not in uncertainty["tags"]
    assert "P06_INSUFFICIENT" in insufficient["tags"]


def test_all_p07_cases_are_explicit_opportunities_with_exact_support(
    benchmark_build,
) -> None:
    opportunities = benchmark_build.fixture_definitions["p07_opportunities"][
        "opportunities"
    ]
    case_by_id = {item["case_id"]: item for item in benchmark_build.cases}
    assert len(opportunities) == 108
    for opportunity in opportunities:
        case_id = "PP-" + opportunity["opportunity_fixture_id"].removeprefix(
            "P07-"
        ).replace("-O", "-P07-O")
        case = case_by_id[case_id]
        definition = opportunity["model_visible_definition"]
        assert definition["operation"]
        assert definition["focus"]
        assert definition["observable"]
        assert definition["support_evidence_ids"]
        resolved = {
            unit["evidence_id"]
            for source in opportunity["source_provenance"]
            if source["role"] == "SUBMISSION_SUPPORT"
            for unit in source["resolved_units"]
        }
        assert set(definition["support_evidence_ids"]).issubset(resolved)
        assert not any(
            "CURATED_PROPERTY_ALIGNED_SUPPORT" in source["relative_ref"]
            for source in opportunity["source_provenance"]
        )
        assert set(opportunity["oracle_binding_metadata"]["property_ids"]).issubset(
            case["property_ids"]
        )
        assert opportunity["opportunity_fixture_id"] in case["input_fixture_ref"]


def test_p07_unknown_support_is_rejected_without_first_unit_fallback(
    benchmark_build,
) -> None:
    opportunity = deepcopy(
        benchmark_build.fixture_definitions["p07_opportunities"]["opportunities"][0]
    )
    activity = benchmark_build.package.activity_by_id[opportunity["activity_id"]]
    submission = next(
        item
        for item in activity["submissions"]
        if item["submission_id"] == opportunity["submission_id"]
    )
    bundle = parse_submission_bundle(
        corpus_root=benchmark_build.package.root,
        activity_path=activity["activity_path"],
        activity_id=activity["activity_id"],
        submission_id=submission["submission_id"],
        artifact_refs=submission["artifacts"],
    )
    opportunity["model_visible_definition"]["support_evidence_ids"] = [
        "ev_does_not_exist"
    ]
    with pytest.raises(ValueError, match="does not resolve exactly"):
        build_p07_fixture(
            opportunity_fixture_id=opportunity["opportunity_fixture_id"],
            model_visible_definition=opportunity["model_visible_definition"],
            bundle=bundle,
        )


def test_p07_rules_without_exact_submission_support_never_create_opportunities(
    benchmark_build,
) -> None:
    opportunities = benchmark_build.fixture_definitions["p07_opportunities"][
        "opportunities"
    ]
    direct_property_ids = {
        property_id
        for opportunity in opportunities
        for property_id in opportunity["oracle_binding_metadata"]["property_ids"]
    }
    bindings = benchmark_build.fixture_definitions["property_bindings"]["bindings"]
    properties = {
        item["property_id"]: item for item in benchmark_build.properties
    }
    cases = {item["case_id"]: item for item in benchmark_build.cases}

    indirect = [
        binding
        for binding in bindings
        if binding["stage"] == "P07"
        and properties[binding["property_id"]]["submission_id"] is not None
        and binding["property_id"] not in direct_property_ids
        and binding["alignment_status"] != "NOT_APPLICABLE"
    ]
    assert len(indirect) == 39
    for binding in indirect:
        prop = properties[binding["property_id"]]
        if binding["alignment_status"] == "ALIGNED":
            # Only a normative rule becomes a case assertion, and only inside
            # the submission it was written about.
            assert prop["kind"] in {"PROHIBITED", "REQUIRED"}
            assert binding["binding_scope"] == "SUBMISSION_WIDE"
            bound_case_ids = [
                binding["primary_case_id"], *binding["additional_case_ids"]
            ]
            assert all(
                cases[case_id]["submission_id"] == prop["submission_id"]
                and cases[case_id]["activity_id"] == prop["activity_id"]
                for case_id in bound_case_ids
            )
        else:
            assert binding["binding_scope"] == "EXPLICITLY_EXCLUDED"
            assert binding["exclusion_reason"] in {
                "NO_P07_OPPORTUNITY_FIXTURE_FOR_SUBMISSION",
                "NO_P07_OPPORTUNITY_EXERCISES_THE_DECLARED_CONDITION",
                "ADVISORY_PROPERTY_KIND_IS_NOT_A_CASE_ASSERTION",
            }


def test_multiple_independent_p07_opportunities_produce_distinct_requests(
    benchmark_build,
) -> None:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for case in benchmark_build.cases:
        if case["stage"] == "P07":
            grouped.setdefault((case["activity_id"], case["submission_id"]), []).append(
                case
            )
    multi = [values for values in grouped.values() if len(values) > 1]
    assert len(grouped) == 63
    assert len(multi) == 36
    assert max(map(len, grouped.values())) == 4
    for values in multi:
        assert len({item["input_hash"] for item in values}) == len(values)
        assert len({item["input_fixture_ref"] for item in values}) == len(values)


def test_p09_exact_locator_integrity_and_property_scope(benchmark_build) -> None:
    report = p09_fixture_integrity_report(benchmark_build)
    assert report["fixture_count"] == 4
    assert report["question_count"] == report["exact_question_count"] == 12
    assert report["unresolved_count"] == report["ambiguous_count"] == 0
    assert report["fallback_count"] == 0
    properties = {item["property_id"]: item for item in benchmark_build.properties}
    for row in report["rows"]:
        assert all("#" in value for value in row["support_refs_declared"])
        assert all("#" in value for value in row["visible_refs_declared"])
        assert set(row["visible_evidence_ids_resolved"]).issubset(
            row["support_evidence_ids_resolved"]
        )
    for case in (item for item in benchmark_build.cases if item["stage"] == "P09"):
        assert all(
            properties[property_id]["activity_id"] == case["activity_id"]
            and properties[property_id]["submission_id"]
            in (None, case["submission_id"])
            for property_id in case["property_ids"]
        )


def test_p09_locator_bindings_use_real_locator_fingerprints(benchmark_build) -> None:
    fixtures = benchmark_build.fixture_definitions["p09_locator_bindings"]["fixtures"]
    units = [
        unit
        for fixture in fixtures
        for question in fixture["questions"]
        for key in ("support_refs", "visible_anchor_refs")
        for source in question[key]
        for unit in source["resolved_units"]
    ]
    assert units
    assert all(unit["normalized_hash"].startswith("sha256:") for unit in units)
    assert all(
        unit["locator"]["kind"] in {"DOCUMENT_PATH", "PAGE_BBOX"}
        and any(
            key in unit["locator"]
            for key in ("paragraph_index", "block_index", "table_index")
        )
        for unit in units
    )


def test_tag_scope_is_case_real_and_never_activity_propagated(benchmark_build) -> None:
    report = tag_scope_report(benchmark_build)
    assert report["contradictory_planner_tag_cases_before"] > 0
    assert report["contradictory_planner_tag_cases_after"] == 0
    assert report["case_tags_without_provenance"] == 0
    assert report["case_activity_scope_assertion_count"] == 0
    assert all(
        provenance["scope"] != "ACTIVITY"
        for case in benchmark_build.cases
        for provenance in case["tag_provenance"]
    )

    pii = [item for item in benchmark_build.cases if "SIMULATED_PII" in item["tags"]]
    act08 = [
        item
        for item in benchmark_build.cases
        if item["activity_id"] == "act_08_triage_de_logs"
        and item["submission_id"] is not None
    ]
    assert pii and len(pii) < len(act08)
    assert {
        item["submission_id"]
        for item in pii
        if item["activity_id"] == "act_08_triage_de_logs"
    } == {"submission_02"}
    assert len(
        [item for item in benchmark_build.cases if "SILENT_CONCEPTUAL_GAP" in item["tags"]]
    ) == 1
    silent_injection = [
        item
        for item in benchmark_build.cases
        if "PROMPT_INJECTION_SILENT" in item["tags"]
    ]
    assert silent_injection
    assert not all(
        "PROMPT_INJECTION_SILENT" in item["tags"] for item in benchmark_build.cases
    )
    adversarial = [
        item
        for item in benchmark_build.cases
        if "ADVERSARIAL_AUTHORIZED_SOURCE" in item["tags"]
    ]
    assert [item["case_id"] for item in adversarial] == ["PP-A08-P04-001"]
    assert all(
        any(
            provenance["scope"] == "CASE_DERIVED"
            for provenance in item["tag_provenance"]
            if provenance["tag"] == "MULTI_ARTIFACT"
        )
        for item in benchmark_build.cases
        if "MULTI_ARTIFACT" in item["tags"]
    )


def test_activity_coverage_index_mutation_does_not_create_rare_cases(
    benchmark_build,
) -> None:
    before = rare_case_coverage(benchmark_build)
    ratifications = deepcopy(list(benchmark_build.package.ratifications))
    ratifications[0]["benchmark_tags"].append("SIMULATED_PII")
    mutated_package = replace(
        benchmark_build.package, ratifications=tuple(ratifications)
    )
    mutated_build = replace(benchmark_build, package=mutated_package)
    assert rare_case_coverage(mutated_build) == before


def test_rare_coverage_distinguishes_properties_cases_and_singletons(
    benchmark_build,
) -> None:
    coverage = rare_case_coverage(benchmark_build)
    assert len(coverage["families"]) == 9
    for family in coverage["families"].values():
        assert family["rare_property_count"] == len(family["property_ids"])
        assert family["rare_case_count"] == len(family["case_ids"])
        assert sum(family["split_distribution"].values()) == family[
            "rare_case_count"
        ]
    silent_gap = coverage["families"]["silent_conceptual_gap"]
    adversarial = coverage["families"]["authorized_source_adversarial"]
    assert silent_gap["singleton_policy"]["classification"] == (
        "SINGLETON_RARE_FAMILY"
    )
    assert silent_gap["splits"] == ["HELD_OUT_CONFIRMATION"]
    assert adversarial["singleton_policy"]["classification"] == (
        "SINGLETON_RARE_FAMILY"
    )
    assert adversarial["splits"] == ["CORE"]
    assert set(coverage["families"]["simulated_pii"]["splits"]) == {
        "SMOKE",
        "HELD_OUT_CONFIRMATION",
    }
    assert set(coverage["families"]["p06_uncertain"]["splits"]) == {
        "SMOKE",
        "CORE",
        "HELD_OUT_CONFIRMATION",
    }


def test_all_395_property_bindings_are_explicit_and_non_arbitrary(
    benchmark_build,
) -> None:
    report = property_fixture_alignment(benchmark_build)
    assert report["property_count"] == 395
    assert report["alignment_counts"] == {
        "ALIGNED": 356,
        "EXPLICITLY_EXCLUDED": 31,
        "NOT_APPLICABLE": 8,
    }
    assert report["assigned_arbitrarily_count"] == 0
    assert report["arbitrary_binding_violations"] == []
    assert all(
        item["alignment_status"] != "ASSIGNED_ARBITRARILY"
        for item in report["rows"]
    )
    for item in report["rows"]:
        if item["alignment_status"] == "ALIGNED":
            assert item["primary_case_id"]
            assert item["fixture_id"]
            assert item["exclusion_reason"] is None
            assert item["representative_selector"]["kind"] != "NONE"
        else:
            assert item["primary_case_id"] is None
            assert item["exclusion_reason"]
            assert item["representative_selector"]["kind"] == "NONE"


def test_arbitrary_binding_detection_is_a_real_recomputation(
    benchmark_build,
) -> None:
    """A convenient case must not survive the selector recomputation.

    The historical v1.0.0 defect attached an activity-level property to the
    first free submission case.  Re-pointing any binding at another case has to
    make the derived counter move, otherwise the readiness gate is asserting a
    constant instead of proving anything.
    """

    assert _binding_arbitrariness(benchmark_build)["assigned_arbitrarily_count"] == 0
    for property_id, replacement in (
        ("A01-ACT-P1", "PP-A02-P04-001"),
        ("A10-S04-P4", "PP-A10-S04-P07-O03"),
        ("A01-S01-P1", "PP-A01-S02-P07-O01"),
    ):
        alignment = [deepcopy(item) for item in benchmark_build.property_alignment]
        row = next(item for item in alignment if item["property_id"] == property_id)
        assert row["primary_case_id"] != replacement
        row["primary_case_id"] = replacement
        mutated = replace(benchmark_build, property_alignment=tuple(alignment))
        result = _binding_arbitrariness(mutated)
        assert result["assigned_arbitrarily_count"] == 1
        assert result["violations"][0]["property_id"] == property_id


def test_normative_p07_rules_bind_to_the_case_that_exercises_them(
    benchmark_build,
) -> None:
    """A REQUIRED wording rule binds wherever its antecedent is real.

    ``A10-S04-P4`` forbids naming the per-segment rates when the observable is
    the evaluation of the declared omission.  ``PP-A10-S04-P07-O01`` is exactly
    that opportunity, so the rule is a case assertion there and its PROHIBITED
    sibling lands on the same case.
    """

    rows = {
        item["property_id"]: item
        for item in benchmark_build.property_alignment
    }
    omission_rule = rows["A10-S04-P4"]
    assert omission_rule["alignment_status"] == "ALIGNED"
    assert omission_rule["primary_case_id"] == "PP-A10-S04-P07-O01"
    assert omission_rule["representative_selector"]["kind"] == "TOPICAL_MARKER"
    assert rows["A10-S04-P6"]["primary_case_id"] == "PP-A10-S04-P07-O01"

    case = next(
        item
        for item in benchmark_build.cases
        if item["case_id"] == "PP-A10-S04-P07-O01"
    )
    assert {"A10-S04-P4", "A10-S04-P6"} <= set(case["property_ids"])

    opportunity = next(
        item
        for item in benchmark_build.fixture_definitions["p07_opportunities"][
            "opportunities"
        ]
        if item["opportunity_fixture_id"] == "P07-A10-S04-O01"
    )
    assert {"DECLARED_CONCEPTUAL_OMISSION", "SELF_DECLARED_GAP"} <= set(
        opportunity["fixture_tags"]
    )


def test_every_exclusion_states_a_concrete_stage_local_reason(
    benchmark_build,
) -> None:
    """No property is dropped for convenience.

    Each exclusion names one structural fact: the stage input cannot carry the
    property's scope, no fixture exists for that scope, no fixture exercises the
    declared condition, the condition lives outside the stage input, or the
    source oracle itself marked the property out of scope.
    """

    allowed = {
        "SOURCE_ORACLE_NOT_APPLICABLE",
        "P04_INPUT_EXCLUDES_SUBMISSIONS_BY_STAGE_CONTRACT",
        "NO_UNAMBIGUOUS_P06_STAGE_LOCAL_ROUTE_FIXTURE",
        "NO_P07_OPPORTUNITY_FIXTURE_FOR_SUBMISSION",
        "NO_P07_OPPORTUNITY_EXERCISES_THE_DECLARED_CONDITION",
        "ADVISORY_PROPERTY_KIND_IS_NOT_A_CASE_ASSERTION",
        "CONDITION_CONFINED_TO_SOURCE_OUTSIDE_P07_INPUT",
        "NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_SCOPE",
    }
    report = property_fixture_alignment(benchmark_build)
    reasons = report["exclusion_reason_counts"]
    assert set(reasons) <= allowed
    assert sum(reasons.values()) == 39
    assert reasons["NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_SCOPE"] == 14

    frozen_p09_activities = {
        item["activity_id"]
        for item in benchmark_build.cases
        if item["stage"] == "P09"
    }
    properties = {
        item["property_id"]: item for item in benchmark_build.properties
    }
    for row in report["rows"]:
        if row["exclusion_reason"] != "NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_SCOPE":
            continue
        assert properties[row["property_id"]]["activity_id"] not in frozen_p09_activities


def test_strict_fixture_schemas_reject_unknown_fields(benchmark_build) -> None:
    route = deepcopy(benchmark_build.fixture_definitions["p06_routes"])
    route["routes"][0]["unexpected"] = True
    schema = json.loads(
        (BENCHMARK_DEFINITION_ROOT / "schemas/p06_routes.schema.json").read_text()
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(route)


def test_model_visible_route_and_opportunity_definitions_are_anti_circular(
    benchmark_build,
) -> None:
    forbidden_keys = {
        "property_id",
        "property_ids",
        "oracle_state",
        "confidence",
        "expected_result",
        "expected_support_status",
        "model_failure",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                nested
                for child in value.values()
                for nested in keys(child)
            }
        if isinstance(value, list):
            return {nested for child in value for nested in keys(child)}
        return set()

    definitions = [
        item["model_visible_definition"]
        for item in benchmark_build.fixture_definitions["p06_routes"]["routes"]
    ] + [
        item["model_visible_definition"]
        for item in benchmark_build.fixture_definitions["p07_opportunities"][
            "opportunities"
        ]
    ]
    assert all(not (keys(value) & forbidden_keys) for value in definitions)


def test_three_cases_times_three_runs_keep_one_property_denominator(
    benchmark_build,
) -> None:
    prop = next(
        item
        for item in benchmark_build.properties
        if item["oracle_state"] == "VALID"
        and item["hardness"] == "HARD_SEMANTIC_PROPERTY"
    )
    rows = [
        {
            "case_id": f"case_{case_index}",
            "property_id": prop["property_id"],
            "run_index": run_index,
            "stage": prop["stage"],
            "candidate_id": "candidate",
            "reasoning_effort": "effort",
            "split": "SMOKE",
            "discipline": "probe",
            "difficulty": "SIMPLE",
            "property_kind": prop["kind"],
            "tags": [],
            "result_state": "PASS",
        }
        for case_index in range(1, 4)
        for run_index in range(1, 4)
    ]
    report = aggregate_future_semantic_runs(rows, properties=benchmark_build.properties)
    assert report["case_observation_count"] == 9
    assert report["property_run_outcome_count"] == 3
    assert report["property_outcome_count"] == 1
    assert report["hard_property_run_denominator"] == 3
    assert report["hard_model_failure_denominator"] == 1


def test_split_matrix_and_call_budget_are_recomputed_from_v11_cases(
    benchmark_build,
) -> None:
    split = split_manifest(benchmark_build.cases)
    assert split["totals_by_split"] == {
        "SMOKE": 12,
        "CORE": 139,
        "HELD_OUT_CONFIRMATION": 121,
    }
    assert set(split["qualification_activity_numbers"]).isdisjoint(
        split["held_out_activity_numbers"]
    )
    budget = phase9_call_budget(benchmark_build.cases)
    assert budget["projections_by_split"]["k=1"]["SMOKE"][
        "total_model_calls"
    ] == 10
    assert budget["projections_by_split"]["k=1"]["CORE"][
        "total_model_calls"
    ] == 127
    assert budget["projections_by_split"]["k=1"]["HELD_OUT_CONFIRMATION"][
        "total_model_calls"
    ] == 114
    assert sum(
        item["total_model_calls"]
        for item in budget["projections_by_split"]["k=3"].values()
    ) == 753


def test_readiness_gate_has_all_seventeen_evidence_backed_invariants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CVA_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CVA_MODEL_MODE", "mock")
    monkeypatch.setenv("CVA_P10_ENABLED", "false")
    run_offline_dry_run(report_root=tmp_path, verify_parser_twice=False)
    report = json.loads((tmp_path / "deterministic_report.json").read_text())
    assert report["passed"] == report["total"] == 17
    assert tuple(item["invariant_id"] for item in report["invariants"]) == (
        DETERMINISTIC_INVARIANT_DEFINITIONS
    )
    assert {item["result"] for item in report["invariants"]} == {"PASS"}
    assert all(item["evidence"] for item in report["invariants"])
