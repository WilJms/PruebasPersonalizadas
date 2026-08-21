#!/usr/bin/env python3
"""Publish the phase9-execution/2.0.0 authority outside the v1.3.5 freeze.

This is a publication tool, never the first-real-call entrypoint.  It rebuilds
the current v1.3.5 HIGH-SMOKE provider-visible requests, snapshots only that
population, and binds the resulting request authority plus executable sources
into a separately versioned execution boundary.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification import semantic_benchmark as sb  # noqa: E402
from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.n3_provider_fixtures import (  # noqa: E402
    build_n3_provider_fixtures,
)
from comprehension_verification.semantic_benchmark_fixtures import (  # noqa: E402
    build_p04_fixture,
    build_p07_fixture,
    build_p09_fixture,
)
from comprehension_verification.semantic_benchmark_v135 import (  # noqa: E402
    SEMANTIC_BENCHMARK_V135_VERSION,
    PROTOCOL_VERSION_V135,
    build_v135,
    validate_v135_package_for_publication,
    v135_package,
)


EXECUTION_VERSION = "phase9-execution/2.0.0"
AUTHORITY_ROOT = REPOSITORY_ROOT / "evaluation/phase9_execution/v2_0_0"
REPORT_ROOT = REPOSITORY_ROOT / "reports/phase9_execution/v2_0_0"
REQUEST_AUTHORITY_PATH = AUTHORITY_ROOT / "high_smoke_request_authority.json"
EXECUTION_BOUNDARY_PATH = AUTHORITY_ROOT / "execution_boundary.json"
CUTOVER_REPORT_PATH = REPORT_ROOT / "execution_cutover_report.json"

V135_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_5"
V135_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_5"
FREEZE_MANIFEST_PATH = V135_REPORT_ROOT / "phase9/freeze_hash_manifest.json"

SOURCE_BINDING_PATHS = (
    "src/comprehension_verification/phase9_execution.py",
    "scripts/run_phase9_smoke.py",
    "scripts/build_phase9_execution_v2.py",
    "src/comprehension_verification/semantic_benchmark.py",
    "src/comprehension_verification/semantic_benchmark_v135.py",
    "src/comprehension_verification/semantic_benchmark_fixtures.py",
    "src/comprehension_verification/n3_provider_fixtures.py",
    "src/comprehension_verification/p06_n3_protocol.py",
)

CANDIDATE_BY_STAGE: Mapping[str, Mapping[str, str]] = {
    "P04": {
        "candidate_id": "P04-C1-TERRA-HIGH",
        "reasoning_rung": "HIGH",
    },
    "P06": {
        "candidate_id": "P06-C1-LUNA-HIGH",
        "reasoning_rung": "HIGH",
    },
    "P07": {
        "candidate_id": "P07-C1-LUNA-HIGH",
        "reasoning_rung": "HIGH",
    },
    "P09": {
        "candidate_id": "P09-C1-LUNA-HIGH",
        "reasoning_rung": "HIGH",
    },
}

STAGE_ORDER = {"P04": 0, "P06": 1, "P07": 2, "P09": 3}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_hash(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _serialize(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialize(payload), encoding="utf-8")


def _submission_bundle_factory(package: sb.CorpusPackage):
    cache: dict[tuple[str, str], Any] = {}

    def resolve(activity_id: str, submission_id: str):
        key = (activity_id, submission_id)
        if key not in cache:
            activity = package.activity_by_id[activity_id]
            submission = next(
                item
                for item in activity["submissions"]
                if item["submission_id"] == submission_id
            )
            cache[key] = sb.parse_submission_bundle(
                corpus_root=package.root,
                activity_path=activity["activity_path"],
                activity_id=activity_id,
                submission_id=submission_id,
                artifact_refs=submission["artifacts"],
            )
        return cache[key]

    return resolve


def _carried_smoke_requests(
    current_cases: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Rebuild carried P04/P07/P09 requests selected by v1.3.5 case authority."""

    package = sb.load_corpus_package()
    definitions = sb._load_fixture_definitions()
    bundle_for = _submission_bundle_factory(package)
    requests: dict[str, Any] = {}

    for case in current_cases.values():
        if case["stage"] != "P04":
            continue
        activity = package.activity_by_id[case["activity_id"]]
        request, coverage = build_p04_fixture(
            corpus_root=package.root,
            activity_path=activity["activity_path"],
            activity_id=case["activity_id"],
        )
        refs = [
            f"{activity['activity_path']}/01_assignment.docx",
            f"{activity['activity_path']}/02_rubric.docx",
        ]
        projection = sb.project_model_visible_files(package, refs)
        rebuilt = canonical_hash(
            {
                "request": request.model_dump(mode="json"),
                "source_hashes": projection.sha256_by_ref,
                "source_coverage": coverage,
                "scaffold_marker": sb.SCAFFOLD_MARKER,
            }
        )
        if rebuilt != case["input_hash"]:
            raise RuntimeError(f"v1.3.5 P04 input drift: {case['case_id']}")
        requests[case["case_id"]] = request

    for opportunity in definitions["p07_opportunities"]["opportunities"]:
        case_id = sb._case_id_for_opportunity(opportunity)
        case = current_cases.get(case_id)
        if case is None or case["stage"] != "P07":
            continue
        request, envelope = build_p07_fixture(
            opportunity_fixture_id=opportunity["opportunity_fixture_id"],
            model_visible_definition=opportunity["model_visible_definition"],
            bundle=bundle_for(
                opportunity["activity_id"], opportunity["submission_id"]
            ),
        )
        support_ids = set(
            opportunity["model_visible_definition"]["support_evidence_ids"]
        )
        support_files = sorted(
            {
                source["relative_ref"]
                for source in opportunity["source_provenance"]
                if source["role"] == "SUBMISSION_SUPPORT"
                and {unit["evidence_id"] for unit in source["resolved_units"]}
                & support_ids
            }
        )
        projection = sb.project_model_visible_files(package, support_files)
        rebuilt = canonical_hash(
            {
                "request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "opportunity_definition": opportunity["model_visible_definition"],
                "opportunity_fixture_id": opportunity["opportunity_fixture_id"],
                "source_hashes": projection.sha256_by_ref,
            }
        )
        if rebuilt != case["input_hash"]:
            raise RuntimeError(f"v1.3.5 P07 input drift: {case_id}")
        requests[case_id] = request

    locator_by_fixture = {
        item["fixture_id"]: item
        for item in definitions["p09_locator_bindings"]["fixtures"]
    }
    fixture_path_by_id = {
        sb._json(package.root / path)["fixture_id"]: path
        for path, entry in package.entries.items()
        if entry["role"] == "P09_STAGE_FIXTURE"
    }
    for fixture in package.p09_fixtures:
        case_id = f"PP-A{sb._activity_number(fixture['activity_id']):02d}-P09-F01"
        case = current_cases.get(case_id)
        if case is None or case["stage"] != "P09":
            continue
        activity = package.activity_by_id[fixture["activity_id"]]
        relative = fixture_path_by_id[fixture["fixture_id"]]
        projected, _model_ref, _oracle_ref = sb.project_p09_questions(package, relative)
        submission = next(
            item
            for item in activity["submissions"]
            if item["submission_id"] == fixture["submission_id"]
        )
        locator = locator_by_fixture[fixture["fixture_id"]]
        request, envelope, operation_projection, _integrity = build_p09_fixture(
            fixture=projected,
            locator_bindings=locator,
            bundle=bundle_for(fixture["activity_id"], fixture["submission_id"]),
            artifact_refs=submission["artifacts"],
            difficulty=sb._difficulty(activity["difficulty_declared"]),
            assignment_hash=(
                "sha256:"
                + package.entries[
                    f"{activity['activity_path']}/01_assignment.docx"
                ]["sha256"]
            ),
            rubric_hash=(
                "sha256:"
                + package.entries[f"{activity['activity_path']}/02_rubric.docx"][
                    "sha256"
                ]
            ),
        )
        rebuilt = canonical_hash(
            {
                "frozen_questions_projection": projected,
                "guide_request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "operation_projection_version": sb.P09_OPERATION_PROJECTION_VERSION,
                "operation_projection": operation_projection,
                "locator_resolver_version": sb.P09_LOCATOR_RESOLVER_VERSION,
                "locator_binding": locator,
                "fixture_hash": package.entries[relative]["sha256"],
            }
        )
        if rebuilt != case["input_hash"]:
            raise RuntimeError(f"v1.3.5 P09 input drift: {case_id}")
        requests[case_id] = request

    expected = {
        case_id
        for case_id, case in current_cases.items()
        if case["stage"] in {"P04", "P07", "P09"}
    }
    if set(requests) != expected:
        raise RuntimeError(
            f"carried request population mismatch: {sorted(expected - set(requests))}"
        )
    return requests


def _packet_authority(
    *,
    case: Mapping[str, Any],
    property_value: Mapping[str, Any],
    binding: Mapping[str, Any],
    p06: bool,
) -> dict[str, Any]:
    fixture_id = (
        binding.get("fixture_id")
        or case.get("fixture_id")
        or case.get("input_fixture_ref")
        or case.get("fixture_ref")
    )
    row = {
        "property_id": property_value["property_id"],
        "fixture_id": fixture_id,
        "route_or_opportunity_id": (
            fixture_id if case["stage"] in {"P06", "P07"} else None
        ),
        "binding_scope": binding["binding_scope"],
        "relevant_source_refs": deepcopy(property_value["source_refs"]),
        "property": deepcopy(property_value["raw_property"]),
        "defensible_alternatives": list(property_value["defensible_alternatives"]),
        "oracle_state": property_value["oracle_state"],
        "source_hashes": {
            key: f"sha256:{value}"
            for key, value in property_value["source_file_hashes"].items()
        },
    }
    if p06:
        row["p06_observation_binding"] = deepcopy(binding)
    return row


def build_request_authority() -> dict[str, Any]:
    build = build_v135(sb.DEFAULT_CORPUS_ROOT)
    package = v135_package(build)
    validate_v135_package_for_publication(package)
    benchmark = sb.build_benchmark(verify_parser_twice=False)
    property_by_id = {item["property_id"]: item for item in benchmark.properties}
    legacy_binding_by_property = {
        item["property_id"]: item
        for item in benchmark.fixture_definitions["property_bindings"]["bindings"]
    }
    smoke_cases = {
        item["case_id"]: item
        for item in build.cases
        if item["split"] == "SMOKE" and item["stage"] != "PLANNER"
    }
    carried_requests = _carried_smoke_requests(smoke_cases)

    p06_requests = _read(V135_DEFINITION_ROOT / "phase9/p06_submission_requests.json")
    p06_observations = _read(
        V135_DEFINITION_ROOT / "phase9/p06_property_observation_bindings.json"
    )
    semantic_cases: list[dict[str, Any]] = []
    for case_id, case in sorted(smoke_cases.items()):
        if case["stage"] == "P06":
            request, envelope = build.p06_runtime_requests[case_id]
            group = next(
                row
                for row in p06_requests["requests"]
                if row["provider_case_id"] == case_id
            )
            observation_bindings = [
                row
                for row in p06_observations["bindings"]
                if row["provider_case_id"] == case_id
            ]
            observations = [
                _packet_authority(
                    case=case,
                    property_value=property_by_id[row["property_id"]],
                    binding=row,
                    p06=True,
                )
                for row in observation_bindings
            ]
            provider_unit = "SUBMISSION_RUN"
            p06_group_authority: dict[str, Any] | None = group
            envelope_hash: str | None = canonical_hash(
                envelope.model_dump(mode="json")
            )
        else:
            request = carried_requests[case_id]
            observations = [
                _packet_authority(
                    case=case,
                    property_value=property_by_id[property_id],
                    binding=legacy_binding_by_property[property_id],
                    p06=False,
                )
                for property_id in case["property_ids"]
            ]
            provider_unit = "CASE_RUN"
            p06_group_authority = None
            envelope_hash = None

        request_payload = request.model_dump(mode="json")
        row = {
            "axis": "SEMANTIC",
            "stage": case["stage"],
            "split": "SMOKE",
            "provider_unit": provider_unit,
            "provider_identity": case_id,
            "fixture_id": (
                case.get("fixture_id")
                or case.get("input_fixture_ref")
                or case.get("fixture_ref")
            ),
            "request_schema_name": type(request).__name__,
            "request": request_payload,
            "request_hash": canonical_hash(request_payload),
            "input_hash": case["input_hash"],
            "property_observations": observations,
        }
        if p06_group_authority is not None:
            row["p06_group_authority"] = p06_group_authority
            row["model_visible_envelope_hash"] = envelope_hash
        semantic_cases.append(row)

    n3_document = _read(V135_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json")
    n3_axis = _read(V135_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json")
    stage_boundaries = _read(V135_REPORT_ROOT / "stage_boundaries.json")
    n3_build = build_n3_provider_fixtures(sb.DEFAULT_CORPUS_ROOT)
    n3_exposures: list[dict[str, Any]] = []
    for fixture, request, envelope in zip(
        n3_build.fixtures, n3_build.requests, n3_build.envelopes, strict=True
    ):
        if fixture["n3_split"] != "N3_SAFETY_SMOKE":
            continue
        published = next(
            row
            for row in n3_document["fixtures"]
            if row["n3_provider_fixture_id"]
            == fixture["n3_provider_fixture_id"]
        )
        request_payload = request.model_dump(mode="json")
        n3_exposures.append(
            {
                "axis": "CONTRACTUAL_HARD_SAFETY",
                "stage": "P06",
                "split": "N3_SAFETY_SMOKE",
                "provider_unit": "EXPOSURE_RUN",
                "provider_identity": fixture["n3_provider_fixture_id"],
                "exposure_pseudonym": fixture["exposure_id"],
                "request_schema_name": type(request).__name__,
                "request": request_payload,
                "request_hash": canonical_hash(request_payload),
                "published_fixture_authority": published,
                "route_context": {
                    "n3_provider_fixture_id": fixture["n3_provider_fixture_id"],
                    "target_construct_key": fixture["target_construct_key"],
                    "construct_canonical_source_name": fixture[
                        "construct_canonical_source_name"
                    ],
                    "construct_source_kind": fixture["construct_source_kind"],
                    "construct_source_refs": fixture["construct_source_refs"],
                    "production_projection": fixture["production_projection"],
                },
                "model_visible_evidence": [
                    item.model_dump(mode="json") for item in envelope.evidence_units
                ],
                "exposure_selector": n3_axis["selectors"]["safety_smoke"],
                "p06_stage_boundary_hash": stage_boundaries[
                    "stage_boundary_hashes"
                ]["P06"],
                "p06_field_authority_hash": stage_boundaries["stages"]["P06"][
                    "field_authority_hash"
                ],
                "n3_gate_source_hash": n3_axis["gate_source_hash"],
            }
        )

    material = {
        "schema_version": "phase9-high-smoke-request-authority/2.0.0",
        "execution_version": EXECUTION_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "protocol_version": PROTOCOL_VERSION_V135,
        "corpus_package_boundary_hash": build.package_hash,
        "selection_depends_on_results": False,
        "contains_held_out_material": False,
        "semantic_cases": semantic_cases,
        "n3_exposures": n3_exposures,
    }
    return {**material, "request_authority_hash": canonical_hash(material)}


def _plan_calls(request_authority: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = [*request_authority["semantic_cases"], *request_authority["n3_exposures"]]
    groups.sort(
        key=lambda row: (
            STAGE_ORDER[row["stage"]],
            1 if row["axis"] == "CONTRACTUAL_HARD_SAFETY" else 0,
            row["provider_identity"],
        )
    )
    calls: list[dict[str, Any]] = []
    for row in groups:
        candidate = CANDIDATE_BY_STAGE[row["stage"]]
        for run_index in (1, 2, 3):
            identity = {
                "axis": row["axis"],
                "stage": row["stage"],
                "split": row["split"],
                "provider_unit": row["provider_unit"],
                "provider_identity": row["provider_identity"],
                "candidate_id": candidate["candidate_id"],
                "reasoning_rung": candidate["reasoning_rung"],
                "run_index": run_index,
            }
            if row["axis"] == "CONTRACTUAL_HARD_SAFETY":
                identity["exposure_pseudonym"] = row["exposure_pseudonym"]
            calls.append(identity)
    return calls


def build_execution_boundary(
    request_authority: Mapping[str, Any],
) -> dict[str, Any]:
    freeze_manifest = _read(FREEZE_MANIFEST_PATH)
    frozen_artifacts = {
        row["path"]: {
            "file_sha256": row["file_sha256"],
            "self_material_hash_field": row["self_material_hash_field"],
            "internal_material_hash": row["internal_material_hash"],
        }
        for row in freeze_manifest["artifacts"]
    }
    benchmark = _read(V135_REPORT_ROOT / "benchmark_boundary.json")
    stages = _read(V135_REPORT_ROOT / "stage_boundaries.json")
    protocol = _read(V135_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    matrix = _read(V135_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    contract = _read(
        V135_DEFINITION_ROOT / "phase9/candidate_execution_contract.json"
    )
    prompts = _read(V135_DEFINITION_ROOT / "phase9/executable_prompt_authority.json")
    budget = _read(V135_REPORT_ROOT / "phase9/call_budget.json")
    n3_axis = _read(V135_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json")
    p06_requests = _read(V135_DEFINITION_ROOT / "phase9/p06_submission_requests.json")
    p06_observations = _read(
        V135_DEFINITION_ROOT / "phase9/p06_property_observation_bindings.json"
    )
    n3_fixtures = _read(V135_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json")
    freeze = _read(V135_REPORT_ROOT / "phase9/pre_results_instrument_freeze.json")
    rung = _read(V135_REPORT_ROOT / "phase9/rung_collection_authority.json")

    calls = _plan_calls(request_authority)
    plan_material = {
        "schema_version": "phase9-high-smoke-plan/2.0.0",
        "execution_version": EXECUTION_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "protocol_version": PROTOCOL_VERSION_V135,
        "logical_calls": calls,
    }
    decomposition: dict[str, int] = {}
    for call in calls:
        key = "/".join(
            (
                call["axis"],
                call["stage"],
                call["split"],
                call["reasoning_rung"],
            )
        )
        decomposition[key] = decomposition.get(key, 0) + 1

    material = {
        "schema_version": "phase9-execution-boundary/2.0.0",
        "execution_version": EXECUTION_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "protocol_version": PROTOCOL_VERSION_V135,
        "semantic_benchmark_bindings": {
            "pre_results_instrument_freeze_hash": freeze["freeze_material_hash"],
            "benchmark_boundary_hash": benchmark["benchmark_boundary_hash"],
            "stage_boundaries_hash": stages["stage_boundaries_hash"],
            "stage_boundary_hashes": stages["stage_boundary_hashes"],
            "protocol_boundary_hash": protocol["protocol_boundary_hash"],
            "candidate_matrix_hash": matrix["candidate_matrix_hash"],
            "candidate_execution_contract_hash": contract[
                "execution_contract_hash"
            ],
            "prompt_authority_hash": prompts["prompt_authority_hash"],
            "call_budget_hash": budget["call_budget_hash"],
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "p06_submission_request_set_hash": p06_requests["request_set_hash"],
            "p06_property_observation_bindings_hash": p06_observations[
                "observation_bindings_hash"
            ],
            "n3_provider_fixture_set_hash": n3_fixtures["fixture_set_hash"],
            "rung_collection_hash": rung["rung_collection_hash"],
            "corpus_package_boundary_hash": benchmark[
                "corpus_package_boundary_hash"
            ],
        },
        "frozen_artifacts": frozen_artifacts,
        "freeze_manifest_file_sha256": _file_hash(FREEZE_MANIFEST_PATH),
        "request_authority": {
            "path": str(REQUEST_AUTHORITY_PATH.relative_to(REPOSITORY_ROOT)),
            "file_sha256": _file_hash(REQUEST_AUTHORITY_PATH),
            "request_authority_hash": request_authority[
                "request_authority_hash"
            ],
        },
        "source_bindings": {
            relative: _file_hash(REPOSITORY_ROOT / relative)
            for relative in SOURCE_BINDING_PATHS
        },
        "high_smoke_plan": {
            "plan_hash": canonical_hash(plan_material),
            "primary_provider_calls": len(calls),
            "decomposition": dict(sorted(decomposition.items())),
            "semantic_provider_call_unit_by_stage": {
                "P04": "CASE_RUN",
                "P06": "SUBMISSION_RUN",
                "P07": "CASE_RUN",
                "P09": "CASE_RUN",
            },
            "n3_provider_call_unit": "EXPOSURE_RUN",
            "k": 3,
            "held_out_in_plan": False,
            "result_dependent_selection": False,
        },
        "pricing_state": "PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION",
        "billable_authorization": "NONE",
    }
    return {**material, "execution_boundary_hash": canonical_hash(material)}


def build_cutover_report(boundary: Mapping[str, Any]) -> dict[str, Any]:
    material = {
        "schema_version": "phase9-execution-cutover-report/2.0.0",
        "execution_version": EXECUTION_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "protocol_version": PROTOCOL_VERSION_V135,
        "execution_boundary_hash": boundary["execution_boundary_hash"],
        "high_smoke_plan_hash": boundary["high_smoke_plan"]["plan_hash"],
        "high_smoke_decomposition": boundary["high_smoke_plan"]["decomposition"],
        "readiness": "PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION",
        "execution_counters": {
            "provider_calls": 0,
            "adjudicator_calls": 0,
            "credential_resolutions": 0,
            "real_provider_transport": False,
            "pricing_refresh": "NOT_PERFORMED",
            "high_smoke": "NOT_EXECUTED",
            "billable_authorization": "NONE",
        },
        "semantic_benchmark_v1_3_5_bytes_modified": False,
    }
    return {**material, "report_hash": canonical_hash(material)}


def _verify_frozen_bytes_unchanged(before: Mapping[str, str]) -> None:
    after = {
        row["path"]: _file_hash(REPOSITORY_ROOT / row["path"])
        for row in _read(FREEZE_MANIFEST_PATH)["artifacts"]
    }
    if dict(before) != after:
        raise RuntimeError("semantic-benchmark/1.3.5 bytes changed during publication")


def publish() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    frozen_before = {
        row["path"]: _file_hash(REPOSITORY_ROOT / row["path"])
        for row in _read(FREEZE_MANIFEST_PATH)["artifacts"]
    }
    request_authority = build_request_authority()
    _write(REQUEST_AUTHORITY_PATH, request_authority)
    boundary = build_execution_boundary(request_authority)
    _write(EXECUTION_BOUNDARY_PATH, boundary)
    report = build_cutover_report(boundary)
    _write(CUTOVER_REPORT_PATH, report)
    _verify_frozen_bytes_unchanged(frozen_before)
    return request_authority, boundary, report


def check() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected_request = build_request_authority()
    published_request = _read(REQUEST_AUTHORITY_PATH)
    if published_request != expected_request:
        raise RuntimeError("published HIGH-SMOKE request authority is stale")
    expected_boundary = build_execution_boundary(published_request)
    published_boundary = _read(EXECUTION_BOUNDARY_PATH)
    if published_boundary != expected_boundary:
        raise RuntimeError("published phase9-execution/2.0.0 boundary is stale")
    expected_report = build_cutover_report(published_boundary)
    published_report = _read(CUTOVER_REPORT_PATH)
    if published_report != expected_report:
        raise RuntimeError("published execution cutover report is stale")
    return published_request, published_boundary, published_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    request, boundary, report = publish() if args.publish else check()
    print(
        json.dumps(
            {
                "status": "PUBLISHED" if args.publish else "VALID",
                "execution_version": EXECUTION_VERSION,
                "request_authority_hash": request["request_authority_hash"],
                "execution_boundary_hash": boundary["execution_boundary_hash"],
                "high_smoke_plan_hash": boundary["high_smoke_plan"]["plan_hash"],
                "readiness": report["readiness"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
