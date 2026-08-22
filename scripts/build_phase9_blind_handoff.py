#!/usr/bin/env python3
"""Make the Phase 9B blind bundle self-contained. No provider call, no verdict.

Rebuilding is idempotent: the 38 packets are never touched, and the source,
projection and binding surfaces are derived deterministically from them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from comprehension_verification.phase9_blind_handoff import (
    BlindHandoffError,
    build_blind_handoff,
    bundle_root,
    verify_self_contained,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-id", default=None)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    root = bundle_root() if args.execution_id is None else bundle_root(
        args.execution_id
    )
    try:
        if args.verify_only:
            result = verify_self_contained(root)
        else:
            result = build_blind_handoff(root=root)
    except BlindHandoffError as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code}, indent=2))
        return 2

    summary = {key: value for key, value in result.items() if key != "leakage"}
    if "leakage" in result:
        summary["metadata_leaks"] = result["leakage"]["metadata_leak_count"]
    summary["provider_calls"] = 0
    summary["adjudicator_calls"] = 0
    summary["semantic_status"] = "PENDING_ADJUDICATION"
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary.get("self_contained", True) else 1


if __name__ == "__main__":
    sys.exit(main())
