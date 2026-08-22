"""Run the semantic harness remediation rehearsal without a provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from comprehension_verification.semantic_harness import (
    run_semantic_harness_rehearsal,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    ROOT / "reports/openai/harness_semantic_remediation_offline.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()
    report = run_semantic_harness_rehearsal()
    serialized = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    destination = args.report.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(destination)
    if args.stdout:
        print(serialized, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
