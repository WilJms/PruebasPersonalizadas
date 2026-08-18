"""Freeze phase9-qualification-protocol/1.2.0 over semantic-benchmark/1.2.0.

The protocol version moves because the benchmark boundary, the P06 adjudication
evidence context, the qualification dispositions and the stage boundaries all
changed.  Every *policy* carries forward unchanged: candidate families, the
reasoning ladders, the cross-family fallback prohibition, k, retry rules, the
two-pass MODEL_FAILURE confirmation, PASS QA and the semantic rate bars.

Only the mechanically recomputed quantities move: P06 case counts, P06 calls,
P06 denominators, P06 safety counts and the P06 budget projection.

This script issues no authorization and performs no provider call.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification import phase9_protocol as p9  # noqa: E402
from comprehension_verification.p06_adjudication_context import (  # noqa: E402
    P06_ADJUDICATION_CONTEXT_VERSION,
)
from comprehension_verification.semantic_benchmark_v12_boundary import (  # noqa: E402
    ACCEPTED_RATE_BAR,
    benchmark_boundary_v12,
    build_v12,
    p06_threshold_rows,
    safety_gate_report,
    stage_boundaries,
)

PROTOCOL_VERSION_V12 = "phase9-qualification-protocol/1.2.0"
ADJUDICATION_PROTOCOL_VERSION_V12 = "phase9-adjudication-protocol/1.1.0"
V11_PHASE9 = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_1/phase9"
V12_PHASE9 = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2/phase9"
V12_REPORTS = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_2/phase9"

V11_PROTOCOL_BOUNDARY = (
    "sha256:daa79023de4e3b72a73f31879d481fbedb75492cc5fb4642c7fd2b4a4dbaa540"
)
V11_BENCHMARK_BOUNDARY = (
    "sha256:426dda4d560a8d7d53639dfbaa0773c28565450f06e8ff62d51a8cd1bd6f62ff"
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return canonical_hash(payload)


def _case_counts(build) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for case in build.cases:
        counts.setdefault(case["stage"], {}).setdefault(case["split"], 0)
        counts[case["stage"]][case["split"]] += 1
    return {stage: dict(sorted(value.items())) for stage, value in sorted(counts.items())}


def _call_projection(counts: dict[str, dict[str, int]]) -> dict[str, Any]:
    per_stage: dict[str, Any] = {}
    for stage in p9.SEMANTIC_STAGES:
        stage_counts = counts.get(stage, {})
        k = p9.SEMANTIC_K
        calls = {split: value * k for split, value in stage_counts.items()}
        rungs = len(p9.STAGE_REASONING_LADDER[stage])
        expected = calls.get("SMOKE", 0) + calls.get("CORE", 0)
        worst = (
            (calls.get("SMOKE", 0) + calls.get("CORE", 0)) * rungs
            + calls.get("HELD_OUT_CONFIRMATION", 0)
        )
        per_stage[stage] = {
            "cases": stage_counts,
            "k": k,
            "calls_per_candidate": calls,
            "ladder_rungs": rungs,
            "expected_economic_path": {
                "assumption": "The default HIGH rung qualifies on SMOKE and CORE.",
                "rungs_executed": 1,
                "calls": expected + calls.get("HELD_OUT_CONFIRMATION", 0),
            },
            "worst_case": {
                "assumption": (
                    "Every rung clears SMOKE and fails CORE until the last, which "
                    "qualifies and is confirmed on held-out."
                ),
                "rungs_executed": rungs,
                "calls": worst,
            },
        }
    planner_cases = sum(counts.get("PLANNER", {}).values())
    return {
        "schema_version": "phase9-call-budget-projection/1.2.0",
        "authorization": "NONE",
        "estimate_status": "ESTIMATE_NOT_BILL",
        "calls_performed_by_this_task": 0,
        "planner_deterministic_k": 1,
        "planner_cases": planner_cases,
        "planner_model_calls": 0,
        "not_a_single_number": (
            "expected_economic_path and worst_case describe different outcomes of the "
            "same protocol and must never be presented as one figure."
        ),
        "per_stage": per_stage,
        "totals": {
            "expected_economic_path_calls": sum(
                value["expected_economic_path"]["calls"] for value in per_stage.values()
            ),
            "worst_case_calls": sum(
                value["worst_case"]["calls"] for value in per_stage.values()
            ),
        },
    }


def main() -> None:
    build = build_v12()
    boundary = benchmark_boundary_v12(build)
    boundaries = stage_boundaries(build)
    safety = safety_gate_report(build)
    counts = _case_counts(build)

    v11_matrix = _json(V11_PHASE9 / "candidate_matrix.json")
    matrix = {
        **v11_matrix,
        "benchmark_version": "semantic-benchmark/1.2.0",
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "protocol_version": PROTOCOL_VERSION_V12,
        "semantic_equivalence_to_v11": {
            "candidates_unchanged": True,
            "stage_model_family_unchanged": True,
            "stage_reasoning_ladder_unchanged": True,
            "promotion_order_unchanged": True,
            "output_caps_unchanged": True,
            "routing_unchanged": True,
            "excluded_families_unchanged": True,
            "only_change": (
                "benchmark_version and benchmark_boundary_hash now reference v1.2. No "
                "candidate, family, ladder, promotion order, cap or routing value "
                "differs from the v1.1 matrix."
            ),
            "v11_candidate_digest": canonical_hash(v11_matrix["candidates"]),
        },
    }
    matrix_hash = _write(V12_PHASE9 / "candidate_matrix.json", matrix)

    thresholds = {
        "schema_version": "phase9-qualification-thresholds/1.2.0",
        "benchmark_version": "semantic-benchmark/1.2.0",
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "accepted_rate_bar_by_split": dict(ACCEPTED_RATE_BAR),
        "bars_carried_forward_unchanged": True,
        "derived_from_historical_qualifications": False,
        "tuned_from_prior_high_results": False,
        "denominator_unit": "PROPERTY_CANDIDATE_REASONING",
        "accepted_semantic_outcomes": ["PASS", "DEFENSIBLE_ALTERNATIVE"],
        "max_technical_failure_rate": p9.MAX_TECHNICAL_FAILURE_RATE,
        "max_pending_adjudication_at_promotion": 0,
        "rounding_rule": (
            "max_confirmed_model_failures = floor(applicable * (1 - bar)). Recomputed "
            "mechanically because the P06 denominator changed; no v1.1 integer "
            "allowance was carried over by hand."
        ),
        "p06_thresholds": p06_threshold_rows(build),
        "non_p06_threshold_equivalence": {
            "source": "evaluation/semantic_benchmark/v1_1/phase9/qualification_thresholds.json",
            "stages": ["P04", "P07", "P09"],
            "bars_identical": True,
            "denominators_unchanged": True,
            "note": (
                "P04/P07/P09 case and property sets are carried forward unchanged, so "
                "their rows are semantically identical to v1.1."
            ),
        },
    }
    thresholds_hash = _write(V12_PHASE9 / "qualification_thresholds.json", thresholds)

    safety_doc = {
        **safety,
        "benchmark_version": "semantic-benchmark/1.2.0",
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "non_p06_safety_carried_forward": True,
    }
    safety_hash = _write(V12_PHASE9 / "safety_gate.json", safety_doc)

    v11_adjudication = _json(V11_PHASE9 / "adjudication_protocol.json")
    adjudication = {
        **v11_adjudication,
        "schema_version": ADJUDICATION_PROTOCOL_VERSION_V12,
        "benchmark_version": "semantic-benchmark/1.2.0",
        "decision_semantics_changed": False,
        "model_failure_requirement_count": len(
            v11_adjudication["model_failure_requirements"]
        ),
        "model_failure_rule_changed": False,
        "two_pass_rule_changed": False,
        "pass_qa_changed": False,
        "p06_evidence_context": {
            "strengthened": True,
            "companion_schema_version": P06_ADJUDICATION_CONTEXT_VERSION,
            "reason": (
                "Phase 9B.3 showed a blind P06 reviewer could not answer "
                "VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE or "
                "NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE without "
                "guessing the architecture."
            ),
            "adds": [
                "route_context: the semantic task the candidate actually saw",
                "field_authority_context: MODEL_OWNED / SERVER_OWNED / "
                "SERVER_DERIVED_FROM_MODEL_INPUT",
                "p06_stage_boundary_hash",
            ],
            "generic_packet_bytes_changed": False,
            "p04_p07_p09_packets_unchanged": True,
        },
        "first_pass_result_transfer": {
            "v11_first_pass_results_transferred_into_v12": False,
            "rule": (
                "No first-pass adjudication result from v1.1 is automatically carried "
                "into v1.2 qualification."
            ),
        },
        "adjudicator_calls_in_this_task": 0,
    }
    adjudication_hash = _write(
        V12_PHASE9 / "adjudication_protocol.json", adjudication
    )

    projection = _call_projection(counts)
    projection_hash = _write(V12_REPORTS / "call_budget_projection.json", projection)

    protocol_material = {
        "schema_version": PROTOCOL_VERSION_V12,
        "protocol_version": PROTOCOL_VERSION_V12,
        "benchmark_version": "semantic-benchmark/1.2.0",
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "stage_boundary_hashes": dict(boundaries["stage_boundary_hashes"]),
        "corpus_package_boundary_hash": p9.CORPUS_PACKAGE_BOUNDARY_HASH,
        "supersedes": {
            "protocol_version": p9.PROTOCOL_VERSION,
            "protocol_boundary_hash": V11_PROTOCOL_BOUNDARY,
            "benchmark_boundary_hash": V11_BENCHMARK_BOUNDARY,
            "status": "SUPERSEDED_AFTER_P06_INSTRUMENT_VALIDITY_FAILURE",
            "never_executed": False,
            "execution_note": (
                "phase9-qualification-protocol/1.1.0 did produce real evidence. Its "
                "P06 qualification validity was compromised afterwards by instrument "
                "defects; non-P06 evidence remains useful historical evidence subject "
                "to an equivalence proof. No final HIGH qualification was completed."
            ),
        },
        "reason_for_new_version": [
            "benchmark boundary changed",
            "P06 adjudication evidence context changed",
            "qualification dispositions changed",
            "stage boundaries introduced",
        ],
        "carried_forward_unchanged": {
            "candidate_family_policy": dict(p9.STAGE_MODEL_FAMILY),
            "stage_reasoning_ladder": {
                stage: list(value)
                for stage, value in p9.STAGE_REASONING_LADDER.items()
            },
            "cross_family_fallback": p9.CROSS_FAMILY_FALLBACK,
            "cross_family_fallback_rule": p9.CROSS_FAMILY_FALLBACK_RULE,
            "semantic_k": p9.SEMANTIC_K,
            "planner_deterministic_k": 1,
            "max_technical_retries": p9.MAX_TECHNICAL_RETRIES,
            "semantic_retry_prohibited": True,
            "blind_two_pass_model_failure_confirmation": True,
            "pass_qa_sample_percent": p9.PASS_QA_SAMPLE_PERCENT,
            "accepted_rate_bar_by_split": dict(ACCEPTED_RATE_BAR),
            "held_out_role": (
                "Confirmation of the selection, never a second selection surface."
            ),
            "selection_rule": p9.SELECTION_RULE,
            "max_candidates_per_stage": p9.MAX_CANDIDATES_PER_STAGE,
            "stage_production_output_cap": dict(p9.STAGE_PRODUCTION_OUTPUT_CAP),
            "excluded_model_families": [
                dict(item) for item in p9.EXCLUDED_MODEL_FAMILIES
            ],
            "pricing_refresh_policy": "REFRESH_BEFORE_ANY_AUTHORIZATION",
            "budget_philosophy": "FAIL_CLOSED",
        },
        "model_selection_policy_changed_by_v11_outcomes": False,
        "recomputed_mechanically": {
            "case_counts_by_stage_split": counts,
            "p06_thresholds": thresholds["p06_thresholds"],
            "p06_safety_rows": safety["rows"],
            "p06_safety_coverage_debt": safety["SAFETY_COVERAGE_DEBT"]["count"],
            "call_budget_projection_hash": projection_hash,
        },
        "candidate_matrix_hash": matrix_hash,
        "qualification_thresholds_hash": thresholds_hash,
        "safety_gate_hash": safety_hash,
        "adjudication_protocol_version": ADJUDICATION_PROTOCOL_VERSION_V12,
        "adjudication_protocol_hash": adjudication_hash,
        "execution_state": "NOT_EXECUTED",
        "authorization": "NONE",
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "billable_authorizations": 0,
        "next_real_execution": {
            "action": "FRESH_COMPLETE_HIGH_SMOKE",
            "stages": ["P04", "P06", "P07", "P09"],
            "requires_independent_pre_execution_audit": True,
            "requires_new_exactly_once_authorization": True,
            "legacy_evidence_may_substitute": False,
        },
    }
    protocol = {
        **protocol_material,
        "protocol_boundary_hash": canonical_hash(protocol_material),
    }
    protocol_hash = _write(V12_PHASE9 / "qualification_protocol.json", protocol)

    print(
        json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION_V12,
                "protocol_boundary_hash": protocol["protocol_boundary_hash"],
                "protocol_document_hash": protocol_hash,
                "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
                "adjudication_protocol_version": ADJUDICATION_PROTOCOL_VERSION_V12,
                "candidate_matrix_hash": matrix_hash,
                "case_counts": counts,
                "expected_economic_path_calls": projection["totals"][
                    "expected_economic_path_calls"
                ],
                "worst_case_calls": projection["totals"]["worst_case_calls"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
