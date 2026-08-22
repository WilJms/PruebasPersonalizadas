#!/usr/bin/env python3
"""Run the canonical Phase 8 benchmark without constructing provider transport."""

from __future__ import annotations

import argparse
from pathlib import Path

from comprehension_verification.semantic_benchmark import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORT_ROOT,
    run_offline_dry_run,
    summary_json,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument(
        "--no-write-reports",
        action="store_true",
        help="validate and print the deterministic summary without writing reports",
    )
    parser.add_argument(
        "--single-parser-pass",
        action="store_true",
        help="skip the second parser pass (tests only; canonical dry-run uses two)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_offline_dry_run(
        corpus_root=args.corpus_root,
        report_root=args.report_root,
        write_reports=not args.no_write_reports,
        verify_parser_twice=not args.single_parser_pass,
    )
    print(summary_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
