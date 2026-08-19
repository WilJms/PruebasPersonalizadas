#!/usr/bin/env python3
"""Emit the Phase 9B.7 product-decision artifact.

Offline and byte-deterministic from frozen source.  No provider is executed, no
credential is resolved, no benchmark version is created and no corpus byte is
touched.
"""

from __future__ import annotations

import json
from pathlib import Path

from comprehension_verification.phase9b7_decision import phase9b7_decision
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT


REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = DEFAULT_CORPUS_ROOT
OUTPUT = (
    REPO_ROOT / "reports" / "semantic_benchmark" / "phase9b7" / "product_decision.json"
)


def main() -> int:
    decision = phase9b7_decision(CORPUS_ROOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(decision, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "verdict": decision["verdict"],
            "uncertain_recommendation": decision["uncertain_recommendation"],
            "noisy_decision_required_between": decision[
                "noisy_decision_required_between"
            ],
            "noisy_decision": decision["noisy_decision"],
            "n3_sound": decision["decision_matrix"]["n3_soundness"]["sound"],
            "deterministic_runtime_guard": decision["decision_matrix"][
                "deterministic_runtime_guard_probe"
            ]["verdict"],
            "decision_hash": decision["decision_hash"],
            "provider_calls": decision["provider_calls"],
            "adjudicator_calls": decision["adjudicator_calls"],
            "billable_authorizations": decision["billable_authorizations"],
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
