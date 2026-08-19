"""Independent P06 support-status coverage derivation (Phase 9B.6 remediation).

Phase 9B.5 reported zero semantic ``UNCERTAIN`` coverage among candidate-scoring
P06 properties.  The task treats that as a blocking claim unless independently
disproven from frozen oracle authority, and forbids deriving the answer from
benchmark tags -- which would be circular anyway: the corpus declares no
``P06_UNCERTAIN`` tag at any scope, so a tag-derived answer is zero by
construction and says nothing about semantics.

This module derives coverage from the oracle property text instead, using two
authorized vocabularies:

``canonical status tokens``
    The ratified properties state the expected P06 outcome with the contract's
    own uppercase tokens -- ``SUFFICIENT``, ``PARTIAL``, ``INSUFFICIENT``,
    ``UNCERTAIN`` -- e.g. ``INSUFFICIENT para 'Variables y medidas'``.

``the activity 04 checklist vocabulary``
    Activity 04's rubric defines its own three-valued scale in authorized
    source: *Sí* / *No* / *No verificable*, with the explicit rule that
    ``"No verificable" no equivale a "No"``.  That scale maps onto the contract
    statuses, and it is the only place in the corpus where the *UNCERTAIN*
    distinction is stated as a rubric rule rather than as an English token.

Both vocabularies are frozen authorized text.  Neither is a benchmark tag, and
neither is a candidate outcome.

The derivation is deliberately conservative about *which* status attaches to
*which* construct.  When a property names one construct and mentions two
statuses -- ``SUFFICIENT para la cronología y simultáneamente INSUFFICIENT para
'Hecho, hipótesis e incertidumbre'`` -- this module records both tokens and
flags the property, rather than guessing by proximity.  For the question the
task actually asks (is any status uncovered?) that is sufficient and sound: a
status counts as covered only if some candidate-scoring property asserts it at
all, so an over-inclusive reading can only *understate* a coverage gap.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Mapping, Sequence

from .canonical import canonical_hash


P06_SUPPORT_STATUS_COVERAGE_VERSION = "p06-support-status-coverage/1.3.0"

SUFFICIENT = "SUFFICIENT"
PARTIAL = "PARTIAL"
INSUFFICIENT = "INSUFFICIENT"
UNCERTAIN = "UNCERTAIN"

#: The four statuses ``EvidenceSupportStatus`` admits.  Production can express
#: every one of them; expressiveness is not the constraint here.
CONTRACT_SUPPORT_STATUSES = (SUFFICIENT, PARTIAL, INSUFFICIENT, UNCERTAIN)

_CANONICAL_TOKEN = re.compile(r"\b(SUFFICIENT|PARTIAL|INSUFFICIENT|UNCERTAIN)\b")

#: Activity 04's authorized checklist scale, from ``02_rubric.docx``:
#: ``Cada línea se marca Sí / No / No verificable con lo entregado.`` and
#: ``"No verificable" no equivale a "No". Se usa cuando el entregable no
#: contiene la parte del artefacto donde esa propiedad se decidiría.``
_CHECKLIST_VOCABULARY: tuple[tuple[str, str, str], ...] = (
    (
        UNCERTAIN,
        r"no\s+verificable",
        'Activity 04 rubric: "No verificable" marks a line the submission '
        "cannot decide because the deciding artifact is absent.",
    ),
    (
        INSUFFICIENT,
        r"(?:queda|quedan|marcarse|marca)\s+en\s+No\b",
        'Activity 04 rubric: "No" marks a line the submission decides '
        "negatively.",
    ),
    (
        SUFFICIENT,
        r"(?:queda|quedan)\s+en\s+S[ií]\b",
        'Activity 04 rubric: "Sí" marks a line the submission satisfies.',
    ),
)


class SupportStatusCoverageError(ValueError):
    """Raised when coverage cannot be derived from the material provided."""


def asserted_statuses(description: str) -> dict[str, list[str]]:
    """Return the statuses a property asserts, with the evidence for each."""

    found: dict[str, list[str]] = defaultdict(list)
    for token in _CANONICAL_TOKEN.findall(description):
        evidence = f"canonical contract token {token!r} in the property text"
        if evidence not in found[token]:
            found[token].append(evidence)
    for status, pattern, rationale in _CHECKLIST_VOCABULARY:
        match = re.search(pattern, description, flags=re.IGNORECASE)
        if match is not None:
            found[status].append(f"{match.group(0)!r} -- {rationale}")
    return {status: sorted(set(rows)) for status, rows in sorted(found.items())}


def support_status_coverage_report(
    *,
    scoring_property_ids: Sequence[str],
    property_descriptions: Mapping[str, str],
    split_by_property: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Derive candidate-scoring coverage for each contract support status."""

    splits = dict(split_by_property or {})
    per_status: dict[str, dict[str, Any]] = {
        status: {"property_ids": [], "by_split": defaultdict(int), "evidence": []}
        for status in CONTRACT_SUPPORT_STATUSES
    }
    unclassified: list[str] = []
    multi_status: list[dict[str, Any]] = []

    for property_id in sorted(scoring_property_ids):
        description = property_descriptions.get(property_id)
        if description is None:
            raise SupportStatusCoverageError(
                f"{property_id}: no frozen property description to derive from"
            )
        found = asserted_statuses(description)
        if not found:
            unclassified.append(property_id)
            continue
        if len(found) > 1:
            multi_status.append(
                {
                    "property_id": property_id,
                    "asserted_statuses": sorted(found),
                    "note": (
                        "The property mentions more than one status. Which status "
                        "attaches to the resolved construct is not inferred here; "
                        "both are recorded so an over-inclusive reading can only "
                        "understate a coverage gap, never invent one."
                    ),
                }
            )
        for status, evidence in found.items():
            row = per_status[status]
            row["property_ids"].append(property_id)
            row["by_split"][splits.get(property_id, "UNKNOWN")] += 1
            for item in evidence:
                if len(row["evidence"]) < 5 and item not in row["evidence"]:
                    row["evidence"].append(item)

    statuses = {
        status: {
            "candidate_scoring_property_count": len(row["property_ids"]),
            "property_ids": sorted(row["property_ids"]),
            "by_split": dict(sorted(row["by_split"].items())),
            "covered": bool(row["property_ids"]),
            "sample_evidence": list(row["evidence"]),
        }
        for status, row in per_status.items()
    }
    uncovered = sorted(
        status for status, row in statuses.items() if not row["covered"]
    )
    material = {
        "schema_version": P06_SUPPORT_STATUS_COVERAGE_VERSION,
        "derivation_authority": "FROZEN_ORACLE_PROPERTY_TEXT_AND_ACTIVITY_RUBRIC_SCALE",
        "derived_from_benchmark_tags": False,
        "contract_support_statuses": list(CONTRACT_SUPPORT_STATUSES),
        "statuses": dict(sorted(statuses.items())),
        "uncovered_statuses": uncovered,
        "unclassified_property_ids": sorted(unclassified),
        "multi_status_properties": multi_status,
        "candidate_scoring_property_count": len(scoring_property_ids),
    }
    return {**material, "report_hash": canonical_hash(material)}


def uncertain_coverage_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    """Decide whether the readiness path may continue past UNCERTAIN.

    Zero ``UNCERTAIN`` coverage is not a bug to be patched by the instrument.
    Every way of closing it -- admitting a multi-construct route, adding a
    property, changing corpus bytes, or narrowing the qualification claim --
    is a product decision, so the gate stops the readiness path and says so
    rather than choosing one.
    """

    uncertain = report["statuses"][UNCERTAIN]
    blocked = not uncertain["covered"]
    return {
        "gate": "P06_UNCERTAIN_SEMANTIC_COVERAGE",
        "covered": uncertain["covered"],
        "candidate_scoring_property_count": uncertain[
            "candidate_scoring_property_count"
        ],
        "readiness_blocked": blocked,
        "stop_code": (
            "P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED" if blocked else None
        ),
        "may_be_closed_by_the_instrument": False,
        "rationale": (
            "No candidate-scoring P06 property asserts UNCERTAIN as the correct "
            "support status, so a qualification run cannot observe whether a "
            "candidate reaches UNCERTAIN when the deciding artifact is absent. "
            "The instrument must not manufacture that coverage."
            if blocked
            else "At least one candidate-scoring property asserts UNCERTAIN."
        ),
    }
