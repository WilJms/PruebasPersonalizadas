"""Content-free metadata policy for the synthetic evaluation harness."""

from __future__ import annotations

import re
from typing import Any

from .canonical import canonical_hash
from .pipeline_authority import (
    HISTORICAL_HARNESS_EVIDENCE_STATUS,
    PIPELINE_AUTHORITY_VERSION,
)


SYNTHETIC_DATA_CLASSIFICATION = "SYNTHETIC_ONLY_NO_STUDENT_DATA"
DIAGNOSTIC_CODE_POLICY_VERSION = "synthetic-diagnostic-codes/1.0.0"
_DIAGNOSTIC_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_EXPLICIT_CODE_FIELDS = {"code", "codes", "primary_failure"}


def _is_code_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return normalized in _EXPLICIT_CODE_FIELDS or normalized.endswith(
        ("_code", "_codes")
    )


def _code_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def synthetic_diagnostic_codes(report: dict[str, Any]) -> list[str]:
    """Collect only stable code fields; never derive codes from free text."""

    codes: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for field_name, child in value.items():
                if _is_code_field(str(field_name)):
                    codes.update(
                        candidate
                        for candidate in _code_values(child)
                        if _DIAGNOSTIC_CODE.fullmatch(candidate)
                    )
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(report)
    return sorted(codes)


def prepare_historical_harness_report(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Mark the legacy harness as historical and retain clear synthetic codes.

    The transformation is intentionally a no-op for every other data
    classification, preserving the content-free policy for student data.
    """

    if report.get("classification") != SYNTHETIC_DATA_CLASSIFICATION:
        return report
    normalized = dict(report)
    normalized["evidence_status"] = HISTORICAL_HARNESS_EVIDENCE_STATUS
    normalized["model_selection_gate"] = False
    normalized["pipeline_authority_version"] = PIPELINE_AUTHORITY_VERSION
    normalized["diagnostic_code_policy_version"] = (
        DIAGNOSTIC_CODE_POLICY_VERSION
    )
    diagnostic_codes = synthetic_diagnostic_codes(normalized)
    normalized["diagnostic_codes"] = diagnostic_codes
    normalized["diagnostic_codes_hash"] = canonical_hash(diagnostic_codes)
    return normalized
