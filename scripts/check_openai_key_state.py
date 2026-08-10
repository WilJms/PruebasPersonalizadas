#!/usr/bin/env python3
"""Probe an OpenAI project key without exposing it or creating billable work.

The key is accepted only through stdin. The probe performs one ``models.list``
request with SDK retries disabled and emits a content-free JSON decision.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import sys
from typing import Any, Literal, TextIO

from openai import AuthenticationError, OpenAI


ExpectedState = Literal["active", "revoked"]
ClientFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class KeyStateDecision:
    """Safe result of a single non-billable provider probe."""

    exit_code: int
    report: dict[str, object]


def _base_report(expected_state: ExpectedState) -> dict[str, object]:
    return {
        "billable_calls": 0,
        "expected_state": expected_state.upper(),
        "network_calls": 0,
    }


def probe_key_state(
    api_key: str,
    *,
    expected_state: ExpectedState,
    required_model: str | None = None,
    client_factory: ClientFactory = OpenAI,
) -> KeyStateDecision:
    """Return a fail-closed state decision without provider response content."""

    report = _base_report(expected_state)
    if not api_key:
        report.update(
            {
                "code": "OPENAI_KEY_STDIN_REQUIRED",
                "observed_state": "UNKNOWN",
                "status": "BLOCKED",
            }
        )
        return KeyStateDecision(2, report)
    if expected_state == "active" and not required_model:
        report.update(
            {
                "code": "OPENAI_REQUIRED_MODEL_REQUIRED",
                "observed_state": "UNKNOWN",
                "status": "BLOCKED",
            }
        )
        return KeyStateDecision(2, report)

    try:
        client = client_factory(api_key=api_key, max_retries=0)
        report["network_calls"] = 1
        models = client.models.list()
    except AuthenticationError as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            report.update(
                {
                    "code": (
                        "OPENAI_KEY_REJECTION_CONFIRMED"
                        if expected_state == "revoked"
                        else "OPENAI_KEY_REJECTED"
                    ),
                    "observed_state": "REJECTED",
                    "provider_status_code": 401,
                    "status": "PASS" if expected_state == "revoked" else "FAIL",
                }
            )
            return KeyStateDecision(0 if expected_state == "revoked" else 1, report)
        report.update(
            {
                "code": "OPENAI_KEY_STATE_UNKNOWN",
                "error_type": type(exc).__name__,
                "observed_state": "UNKNOWN",
                "provider_status_code": status_code,
                "status": "UNKNOWN",
            }
        )
        return KeyStateDecision(2, report)
    except Exception as exc:  # noqa: BLE001 - all provider uncertainty fails closed
        report.update(
            {
                "code": "OPENAI_KEY_STATE_UNKNOWN",
                "error_type": type(exc).__name__,
                "observed_state": "UNKNOWN",
                "provider_status_code": getattr(exc, "status_code", None),
                "status": "UNKNOWN",
            }
        )
        return KeyStateDecision(2, report)

    model_ids = {str(model.id) for model in models.data}
    report.update(
        {
            "model_count": len(model_ids),
            "observed_state": "ACTIVE",
            "required_model": required_model,
            "required_model_visible": (
                required_model in model_ids if required_model is not None else None
            ),
        }
    )
    if expected_state == "revoked":
        report.update(
            {
                "code": "OPENAI_KEY_STILL_ACTIVE",
                "status": "FAIL",
            }
        )
        return KeyStateDecision(1, report)
    if required_model not in model_ids:
        report.update(
            {
                "code": "OPENAI_REQUIRED_MODEL_NOT_VISIBLE",
                "status": "FAIL",
            }
        )
        return KeyStateDecision(1, report)
    report.update(
        {
            "code": "OPENAI_KEY_ACTIVE_REQUIRED_MODEL_VISIBLE",
            "status": "PASS",
        }
    )
    return KeyStateDecision(0, report)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe an OpenAI key supplied only through stdin."
    )
    parser.add_argument("--expect", choices=("active", "revoked"), required=True)
    parser.add_argument("--required-model")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    client_factory: ClientFactory = OpenAI,
) -> int:
    args = _parser().parse_args(argv)
    api_key = "" if stdin.isatty() else stdin.read().strip()
    decision = probe_key_state(
        api_key,
        expected_state=args.expect,
        required_model=args.required_model,
        client_factory=client_factory,
    )
    json.dump(decision.report, stdout, sort_keys=True)
    stdout.write("\n")
    return decision.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
