#!/usr/bin/env python3
"""Emit and verify the frozen Phase 9 qualification protocol.

Offline by construction: it reads the Phase 8.1 benchmark, writes the protocol
artifacts and reports, and prints the protocol boundary hash.  It never
contacts a provider and never issues an authorization.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comprehension_verification.phase9_protocol import (  # noqa: E402
    AUTHORIZATION_STATE,
    BENCHMARK_BOUNDARY_HASH,
    CORPUS_PACKAGE_BOUNDARY_HASH,
    EXECUTION_STATE,
    PHASE_8_1_BASELINE_SHA,
    PROTOCOL_VERSION,
    build_adjudication_load,
    build_protocol,
    load_benchmark_facts,
    protocol_boundary_hash,
    validate_protocol,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_DIR = REPO_ROOT / "evaluation/semantic_benchmark/v1_1/phase9"
REPORT_DIR = REPO_ROOT / "reports/semantic_benchmark/v1_1/phase9"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    facts = load_benchmark_facts()
    protocol = build_protocol(facts)
    validate_protocol(protocol)
    boundary = protocol_boundary_hash(protocol)

    write_json(PROTOCOL_DIR / "qualification_protocol.json", protocol)
    write_json(PROTOCOL_DIR / "candidate_matrix.json", protocol["candidate_matrix"])
    write_json(
        PROTOCOL_DIR / "adjudication_protocol.json", protocol["adjudication_protocol"]
    )
    write_json(PROTOCOL_DIR / "safety_gate.json", protocol["safety_gate"])
    write_json(
        PROTOCOL_DIR / "qualification_thresholds.json",
        protocol["qualification_thresholds"],
    )
    write_json(PROTOCOL_DIR / "pricing_snapshot.json", protocol["pricing_snapshot"])
    write_json(PROTOCOL_DIR / "budget_plan.json", protocol["budget_plan"])
    write_json(PROTOCOL_DIR / "execution_plan.json", protocol["execution_plan"])

    adjudication_load = build_adjudication_load(facts)
    write_json(REPORT_DIR / "adjudication_load_projection.json", adjudication_load)

    budget = protocol["budget_plan"]
    write_json(
        REPORT_DIR / "call_budget_projection.json",
        {
            "schema_version": "phase9-call-budget-projection/1.0.0",
            "authorization": AUTHORIZATION_STATE,
            "provider_calls_performed": 0,
            "disclaimer": budget["disclaimer"],
            "k": protocol["execution_plan"]["k"],
            "per_candidate": [
                {
                    "candidate_id": entry["candidate_id"],
                    "stage": entry["stage"],
                    "model": entry["model"],
                    "reasoning_effort": entry["reasoning_effort"],
                    "calls_by_rung": {
                        split: rung["calls"] for split, rung in entry["rungs"].items()
                    },
                    "expected_cost_usd_by_rung": {
                        split: rung["expected_cost_usd"]
                        for split, rung in entry["rungs"].items()
                    },
                    "worst_case_cost_usd_by_rung": {
                        split: rung["worst_case_cost_usd"]
                        for split, rung in entry["rungs"].items()
                    },
                    "per_call_cap_usd": entry["per_call_cap_usd"],
                    "full_ladder_cap_usd": entry["full_ladder_cap_usd"],
                }
                for entry in budget["per_candidate"]
            ],
            "per_stage": budget["per_stage"],
            "global_cap_usd": budget["global_cap_usd"],
        },
    )

    write_json(
        REPORT_DIR / "candidate_comparison_plan.json",
        {
            "schema_version": "phase9-candidate-comparison-plan/1.0.0",
            "authorization": AUTHORIZATION_STATE,
            "results_present": False,
            "ladder": protocol["execution_plan"]["ladder"],
            "promotion": protocol["execution_plan"]["promotion"],
            "tie_break_order": protocol["execution_plan"]["tie_break_order"],
            "promotion_metrics": protocol["execution_plan"]["promotion_metrics"],
            "metric_denominators": protocol["execution_plan"]["metric_denominators"],
            "stage_winners_may_differ": True,
        },
    )

    write_json(
        REPORT_DIR / "protocol_freeze_report.json",
        {
            "schema_version": "phase9-protocol-freeze-report/1.0.0",
            "protocol_version": PROTOCOL_VERSION,
            "phase9_protocol_boundary_hash": boundary,
            "benchmark_boundary_hash": BENCHMARK_BOUNDARY_HASH,
            "corpus_package_boundary_hash": CORPUS_PACKAGE_BOUNDARY_HASH,
            "phase_8_1_baseline_sha": PHASE_8_1_BASELINE_SHA,
            "candidate_matrix_hash": protocol["candidate_matrix_hash"],
            "adjudication_protocol_hash": protocol["adjudication_protocol_hash"],
            "thresholds_hash": protocol["thresholds_hash"],
            "pricing_snapshot_hash": protocol["pricing_snapshot_hash"],
            "budget_plan_hash": protocol["budget_plan_hash"],
            "candidate_matrix_status": "FROZEN",
            "authorization": AUTHORIZATION_STATE,
            "execution_state": EXECUTION_STATE,
            "provider_calls": 0,
            "billable_authorizations": 0,
            "adjudicator_calls": 0,
            "held_out_lock": protocol["held_out_lock"],
            "readiness": "PHASE9_PROTOCOL_READY_FOR_EXECUTION",
        },
    )

    print(
        json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "phase9_protocol_boundary_hash": boundary,
                "benchmark_boundary_hash": BENCHMARK_BOUNDARY_HASH,
                "candidate_matrix_hash": protocol["candidate_matrix_hash"],
                "candidate_count": len(protocol["candidate_matrix"]["candidates"]),
                "authorization": AUTHORIZATION_STATE,
                "execution_state": EXECUTION_STATE,
                "provider_calls": 0,
                "global_cap_usd": budget["global_cap_usd"],
                "readiness": "PHASE9_PROTOCOL_READY_FOR_EXECUTION",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
