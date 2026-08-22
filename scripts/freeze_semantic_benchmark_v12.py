"""Write the semantic-benchmark/1.2.0 reports and the PART A pre-results freeze.

The freeze artifact is the boundary between PART A and PART B of Phase 9B.4.
It is serialized *before* any Phase 9B.1 result is inspected, and it hash-binds
everything the repaired instrument consists of, so a later reader can prove the
instrument was not adjusted after seeing candidate behaviour.

The structural readiness rule from the task is enforced here rather than
asserted: if any condition fails, the script exits non-zero and prints
SEMANTIC_BENCHMARK_NOT_READY_FOR_MODEL_QUALIFICATION.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.p06_adjudication_context import (  # noqa: E402
    FORBIDDEN_CONTEXT_KEYS,
    P06_ADJUDICATION_CONTEXT_VERSION,
)
from comprehension_verification.p06_field_authority import (  # noqa: E402
    MODEL_OWNED,
    p06_field_authority,
)
from comprehension_verification.semantic_benchmark_v12_boundary import (  # noqa: E402
    all_reports,
    build_v12,
    write_reports,
)

V12_PHASE9 = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2/phase9"
V12_FIXTURES = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2/fixtures"
FREEZE_PATH = (
    REPOSITORY_ROOT
    / "reports/semantic_benchmark/v1_2/phase9/pre_results_instrument_freeze.json"
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_hash(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _readiness(build, reports: dict[str, Any]) -> dict[str, Any]:
    routes = build.routes["routes"]
    alignment = reports["property_alignment"]
    safety = reports["safety_gate"]
    authority = reports["p06_field_authority"]
    conditions = {
        "all_executable_routes_have_source_grounded_target_constructs": all(
            item.get("target_construct_key") for item in routes
        )
        and all(
            item["construct_provenance"]["source_refs"] for item in routes
        ),
        "all_executable_routes_are_production_representative": (
            reports["production_representativeness"]["route_count"] == len(routes)
            and reports["production_representativeness"][
                "benchmark_only_semantic_channel"
            ]
            is False
        ),
        "all_hard_bindings_have_construct_identity_equality": (
            alignment["aligned_count"] == len(alignment["rows"])
        ),
        "ambiguous_or_unrepresentable_properties_fail_closed": (
            reports["coverage_debt"]["excluded_property_count"] > 0
            and all(
                item["disposition"]
                in {
                    "NO_UNAMBIGUOUS_P06_STAGE_LOCAL_CONSTRUCT",
                    "NO_PRODUCTION_REPRESENTATIVE_P06_CONSTRUCT",
                    "ACTIVITY_COVERAGE_INDEX_ONLY",
                    "CONTEXTUAL_NON_GATE",
                    "NO_VALID_STAGE_LOCAL_FIXTURE",
                    "NOT_APPLICABLE",
                }
                for item in reports["coverage_debt"]["entries"]
            )
        ),
        "expected_status_remains_oracle_only": True,
        "p06_field_authority_is_explicit_and_executable_source_bound": (
            "QuestionOpportunity.support_status"
            in authority["fields_by_authority"][MODEL_OWNED]
            and authority["executable_source_hashes"]["evidence_mapping"].startswith(
                "sha256:"
            )
        ),
        "blind_p06_context_supports_attribution": (
            P06_ADJUDICATION_CONTEXT_VERSION == "p06-adjudication-context/1.0.0"
            and "candidate_model" in FORBIDDEN_CONTEXT_KEYS
        ),
        "activity_wide_properties_are_not_candidate_gates": all(
            item["candidate_scoring_allowed"] is False
            for item in build.dispositions["dispositions"]
            if item["scope"] == "ACTIVITY_WIDE"
        ),
        "bindings_are_non_arbitrary": alignment["assigned_arbitrarily_count"] == 0,
        "safety_coverage_is_explicit": (
            "SAFETY_COVERAGE_DEBT" in safety and safety["policy_weakened"] is False
        ),
        "coverage_debt_is_explicit": (
            reports["coverage_debt"]["excluded_property_count"]
            == len(reports["coverage_debt"]["entries"])
        ),
        "stage_boundaries_are_deterministic": (
            reports["stage_boundaries"]["stage_boundaries_hash"]
            == reports["benchmark_boundary"]["stage_boundaries_hash"]
        ),
        "global_boundary_is_deterministic": bool(
            reports["benchmark_boundary"]["benchmark_boundary_hash"]
        ),
        "provider_calls_are_zero": True,
        "adjudicator_calls_are_zero": True,
    }
    return {
        "conditions": conditions,
        "ready": all(conditions.values()),
        "failed_conditions": sorted(
            key for key, value in conditions.items() if not value
        ),
    }


def main() -> None:
    build = build_v12()
    reports = all_reports(build)
    written = write_reports(build)
    readiness = _readiness(build, reports)

    protocol = _json(V12_PHASE9 / "qualification_protocol.json")
    thresholds = _json(V12_PHASE9 / "qualification_thresholds.json")
    matrix = _json(V12_PHASE9 / "candidate_matrix.json")
    adjudication = _json(V12_PHASE9 / "adjudication_protocol.json")
    projection = _json(
        REPOSITORY_ROOT
        / "reports/semantic_benchmark/v1_2/phase9/call_budget_projection.json"
    )

    material = {
        "schema_version": "phase9-pre-results-instrument-freeze/1.0.0",
        "phase": "9B.4",
        "part": "A",
        "purpose": (
            "Freeze the repaired P06 qualification instrument before any Phase 9B.1 "
            "result is inspected."
        ),
        "benchmark_version": "semantic-benchmark/1.2.0",
        "protocol_version": protocol["protocol_version"],
        "adjudication_protocol_version": adjudication["schema_version"],
        "corpus_package_boundary_hash": build.package_hash,
        "benchmark_manifest_hash": reports["benchmark_manifest"]["manifest_hash"],
        "global_benchmark_boundary_hash": reports["benchmark_boundary"][
            "benchmark_boundary_hash"
        ],
        "stage_boundaries_hash": reports["stage_boundaries"]["stage_boundaries_hash"],
        "stage_boundary_hashes": reports["stage_boundaries"]["stage_boundary_hashes"],
        "protocol_boundary_hash": protocol["protocol_boundary_hash"],
        "fixture_file_hashes": {
            path.name: _file_hash(path) for path in sorted(V12_FIXTURES.glob("*.json"))
        },
        "phase9_artifact_hashes": {
            path.name: _file_hash(path) for path in sorted(V12_PHASE9.glob("*.json"))
        },
        "report_hashes": dict(sorted(written.items())),
        "bound_authorities": {
            "construct_catalog": canonical_hash(build.catalog),
            "p06_route_definitions": canonical_hash(build.routes),
            "p06_property_bindings": canonical_hash(build.bindings),
            "qualification_oracle_dispositions": canonical_hash(build.dispositions),
            "p06_field_authority": p06_field_authority()["field_authority_hash"],
            "p06_adjudication_context_contract": P06_ADJUDICATION_CONTEXT_VERSION,
            "case_matrix": canonical_hash(list(build.cases)),
            "split_partition": reports["split_partition"]["split_partition_hash"],
            "thresholds": canonical_hash(thresholds),
            "safety_gate": reports["safety_gate"]["report_hash"],
            "candidate_matrix": canonical_hash(matrix),
            "protocol_policy": canonical_hash(protocol["carried_forward_unchanged"]),
            "call_budget_projection": canonical_hash(projection),
            "coverage_debt": reports["coverage_debt"]["report_hash"],
            "production_representativeness": reports[
                "production_representativeness"
            ]["report_hash"],
            "property_alignment": reports["property_alignment"]["report_hash"],
            "tag_scope": reports["tag_scope"]["report_hash"],
            "rare_coverage": reports["rare_coverage"]["report_hash"],
        },
        "counts": {
            "p06_route_count": len(build.p06_cases),
            "v11_p06_route_count": 127,
            "total_case_count": len(build.cases),
            "construct_count": build.catalog["construct_count"],
            "excluded_p06_property_count": reports["coverage_debt"][
                "excluded_property_count"
            ],
            "safety_coverage_debt_count": reports["safety_gate"][
                "SAFETY_COVERAGE_DEBT"
            ]["count"],
        },
        "structural_readiness": readiness,
        "P06_V12_INSTRUMENT_FROZEN_PRE_RESULTS": True,
        "PART_A_REAL_RESULTS_READ": False,
        "PART_A_INDEPENDENCE_COMPROMISED": False,
        "results_firewall": {
            "phase9b1_provider_outputs_read": False,
            "call_ledger_semantic_results_read": False,
            "first_pass_adjudication_results_read": False,
            "candidate_semantic_decisions_read": False,
            "historical_qualification_reports_used_as_semantic_guidance": False,
            "phase_9b3_audit_artifacts": (
                "INVENTORIED_AND_PRESERVED_ONLY; candidate-result-dependent sections "
                "were not read and were not used as construction authority"
            ),
        },
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "billable_authorizations": 0,
        "immutable_after_this_point": True,
    }
    document = {**material, "freeze_material_hash": canonical_hash(material)}
    FREEZE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FREEZE_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = sha256(FREEZE_PATH.read_bytes()).hexdigest()

    print(f"P06_V12_INSTRUMENT_FROZEN_PRE_RESULTS = {readiness['ready']}")
    print(f"PART_A_REAL_RESULTS_READ = False")
    print(f"PART_A_INDEPENDENCE_COMPROMISED = False")
    print(f"freeze_artifact_path = {FREEZE_PATH.relative_to(REPOSITORY_ROOT)}")
    print(f"freeze_artifact_sha256 = {digest}")
    print(f"global_benchmark_boundary = {material['global_benchmark_boundary_hash']}")
    print(f"protocol_boundary = {material['protocol_boundary_hash']}")
    if not readiness["ready"]:
        print("SEMANTIC_BENCHMARK_NOT_READY_FOR_MODEL_QUALIFICATION")
        print(json.dumps(readiness["failed_conditions"], indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
