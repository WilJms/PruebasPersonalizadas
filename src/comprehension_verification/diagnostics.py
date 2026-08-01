"""Stable, content-minimizing diagnostics used by fail-closed paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import models as m


_SENSITIVE_DETAIL_KEYS = {
    "content",
    "content_text",
    "display_text",
    "email",
    "name",
    "prompt",
    "secret",
    "student_text",
}


def _safe_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key.lower() in _SENSITIVE_DETAIL_KEYS:
            raise ValueError(f"sensitive diagnostic detail key is forbidden: {key}")
        if isinstance(value, str) and len(value) > 256:
            raise ValueError(f"diagnostic detail is too long: {key}")
        cleaned[key] = value
    return cleaned


def diagnostic(
    code: str,
    message: str,
    *,
    severity: m.Severity = m.Severity.ERROR,
    evidence_ids: Sequence[str] = (),
    source_ids: Sequence[str] = (),
    retryable: bool = False,
    details: Mapping[str, Any] | None = None,
) -> m.Diagnostic:
    return m.Diagnostic(
        code=code,
        severity=severity,
        message=message,
        evidence_ids=list(evidence_ids),
        source_ids=list(source_ids),
        retryable=retryable,
        details=_safe_details(details),
    )

