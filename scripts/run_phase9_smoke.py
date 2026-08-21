#!/usr/bin/env python3
"""Public entrypoint for the phase9-execution/2.0.1 HIGH-SMOKE harness.

Credential lookup is a deferred callback. The harness invokes it only after the
v1.3.5 freeze, v2 execution boundary, exact plan, live prompts, current pricing,
and explicit hash-bound authorization have all validated.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from pydantic import SecretStr

from comprehension_verification.phase9_execution import (
    BILLABLE_AUTHORIZATION_PATH,
    CURRENT_PRICING_PATH,
    Phase9ExecutionError,
    run_phase9b_smoke,
)
from comprehension_verification.provider_authorization import (
    validate_pinned_secret_resource,
)


_SUCCESS_STATUSES = frozenset(
    {
        "REAL_SMOKE_HIGH_GENERATION_COMPLETE_PENDING_ADJUDICATION",
        "READY_REQUIRES_EXPLICIT_ALLOW_BILLABLE",
    }
)


def _result_exit_code(result: dict[str, object]) -> int:
    """Only exact closed success states receive a zero CLI exit code."""

    return 0 if result.get("status") in _SUCCESS_STATUSES else 1


def _credential_resolver(secret_version_resource: str | None):
    """Return a closure; do not inspect env or Secret Manager yet."""

    def resolve() -> SecretStr | None:
        inline = os.environ.get("CVA_OPENAI_API_KEY", "").strip()
        if inline:
            return SecretStr(inline)
        if not secret_version_resource:
            return None
        from comprehension_verification.web.provider_secrets import (
            ProviderCredentialUnavailable,
            resolve_openai_api_key,
        )

        validate_pinned_secret_resource(secret_version_resource)
        try:
            return resolve_openai_api_key(secret_version_resource)
        except ProviderCredentialUnavailable:
            return None

    return resolve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--secret-version-resource", default=None)
    parser.add_argument("--created-by", default="phase9-v201-operator")
    parser.add_argument("--pricing", type=Path, default=CURRENT_PRICING_PATH)
    parser.add_argument(
        "--authorization", type=Path, default=BILLABLE_AUTHORIZATION_PATH
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    try:
        result = run_phase9b_smoke(
            created_by=args.created_by,
            pricing_path=args.pricing,
            authorization_path=args.authorization,
            credential_resolver=(
                _credential_resolver(args.secret_version_resource)
                if args.allow_billable
                else None
            ),
            allow_billable=args.allow_billable,
        )
    except Phase9ExecutionError as exc:
        result = {
            "status": "BLOCKED",
            "code": exc.code,
            "safety_counters": exc.safety_counters,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return (
            0
            if not args.allow_billable
            and exc.code == "PRICING_REFRESH_REQUIRED_BEFORE_AUTHORIZATION"
            else 2
        )

    summary = {
        key: value
        for key, value in result.items()
        if key not in {"attempts", "blind_bundle", "evidence_hashes"}
    }
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return _result_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
