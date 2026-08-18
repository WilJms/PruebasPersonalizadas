#!/usr/bin/env python3
"""Run the authorized Phase 9B.1 HIGH SMOKE generation.

Dry mode proves the authorization offline and performs zero provider calls.
Real mode consumes the authorization exactly once and executes the 30 frozen
primary logical calls. Neither mode adjudicates anything: the run ends at
``PENDING_ADJUDICATION`` with a blind bundle for a separate context.

The credential is never printed, logged, written or passed as an argument. It is
resolved from a pinned Secret Manager version, or from ``CVA_OPENAI_API_KEY``
when one is already present in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from pydantic import SecretStr

from comprehension_verification.phase9_execution import (
    Phase9ExecutionError,
    run_phase9b_smoke,
)
from comprehension_verification.provider_authorization import (
    validate_pinned_secret_resource,
)


def _resolve_credential(secret_version_resource: str | None) -> SecretStr | None:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--secret-version-resource", default=None)
    parser.add_argument("--created-by", default="phase9b1-operator")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    api_key = None
    if args.allow_billable:
        api_key = _resolve_credential(args.secret_version_resource)
        if api_key is None:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "code": "OPENAI_CREDENTIAL_REQUIRED",
                        "provider_calls": 0,
                    },
                    indent=2,
                )
            )
            return 2

    try:
        result = run_phase9b_smoke(
            api_key=api_key,
            created_by=args.created_by,
            transport=bool(args.allow_billable),
        )
    except Phase9ExecutionError as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code}, indent=2))
        return 2

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
    return 0 if result["status"].startswith(
        ("REAL_SMOKE_HIGH_GENERATION_COMPLETE", "DRY_RUN")
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
