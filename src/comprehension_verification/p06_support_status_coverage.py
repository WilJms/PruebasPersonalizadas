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

P06_UNCERTAIN_SCOPE_CENSUS_VERSION = "p06-uncertain-scope-census/1.0.0"

#: Scope labels for the UNCERTAIN census.  They mirror the scopes the ratified
#: corpus itself uses: a property is stated about one submission or about the
#: activity as a whole.
SUBMISSION_LEVEL = "SUBMISSION"
ACTIVITY_LEVEL = "ACTIVITY"
BOTH_SCOPES = "SUBMISSION_LEVEL_AND_ACTIVITY_LEVEL"

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


#: Row order and human labels for the UNCERTAIN census.  The explanatory prose
#: in the findings and in the phase document is *generated* from this mapping
#: plus the derived counts, so a count can never be restated as an independent
#: numeric literal that drifts away from the machine value.
UNCERTAIN_CENSUS_ROWS: tuple[tuple[str, str], ...] = (
    (
        "submission_level_asserting_uncertain",
        "submission-level P06 properties whose text asserts UNCERTAIN",
    ),
    (
        "submission_level_asserting_uncertain_oracle_valid",
        "... of those, `oracle_state VALID`",
    ),
    (
        "submission_level_asserting_uncertain_oracle_valid_kind_required",
        "... of those, kind `REQUIRED`",
    ),
    (
        "activity_level_describing_uncertain",
        "activity-level P06 properties describing UNCERTAIN "
        "(coverage-index statements, never candidate gates)",
    ),
    (
        "combined_both_scopes",
        "combined across both scopes (submission-level + activity-level)",
    ),
    (
        "candidate_scoring_executable_asserting_uncertain",
        "candidate-scoring executable P06 properties asserting UNCERTAIN",
    ),
)


def uncertain_scope_census(
    *,
    property_records: Sequence[Mapping[str, Any]],
    scoring_property_ids: Sequence[str],
) -> dict[str, Any]:
    """Count UNCERTAIN-bearing P06 properties with the scope always explicit.

    Six populations are derived, never asserted.  They are kept apart because
    they answer different questions and only one of them is a readiness fact:

    * a *submission-level* property asserts UNCERTAIN about one submission and
      is the only kind that can ever become a candidate gate;
    * an *activity-level* property describes which of the four P06 states the
      activity offers across its submissions.  It is a coverage index, not a
      gate, and adding it to the submission-level population produces a number
      that answers no question at all;
    * a *candidate-scoring executable* property is a submission-level property
      that actually reached an executable route with ``oracle_state VALID``.
      Only this population can be observed by a qualification run, so only its
      count is the blocking readiness fact.
    """

    scoring = set(scoring_property_ids)
    by_scope: dict[str, list[Mapping[str, Any]]] = {
        SUBMISSION_LEVEL: [],
        ACTIVITY_LEVEL: [],
    }
    for record in property_records:
        scope = record["scope"]
        if scope not in by_scope:
            raise SupportStatusCoverageError(
                f"{record['property_id']}: unknown property scope {scope!r}"
            )
        if UNCERTAIN in asserted_statuses(record["description"]):
            by_scope[scope].append(record)

    submission = sorted(by_scope[SUBMISSION_LEVEL], key=lambda r: r["property_id"])
    activity = sorted(by_scope[ACTIVITY_LEVEL], key=lambda r: r["property_id"])
    valid = [r for r in submission if r["oracle_state"] == "VALID"]
    valid_required = [r for r in valid if r["kind"] == "REQUIRED"]
    executable = [r for r in submission if r["property_id"] in scoring]

    def _population(rows: Sequence[Mapping[str, Any]], scope: str) -> dict[str, Any]:
        return {
            "scope": scope,
            "count": len(rows),
            "activity_count": len({r["activity_id"] for r in rows}),
            "property_ids": [r["property_id"] for r in rows],
        }

    populations = {
        "submission_level_asserting_uncertain": _population(
            submission, SUBMISSION_LEVEL
        ),
        "submission_level_asserting_uncertain_oracle_valid": _population(
            valid, SUBMISSION_LEVEL
        ),
        "submission_level_asserting_uncertain_oracle_valid_kind_required": _population(
            valid_required, SUBMISSION_LEVEL
        ),
        "activity_level_describing_uncertain": {
            **_population(activity, ACTIVITY_LEVEL),
            "is_a_candidate_gate": False,
            "rule": (
                "An activity-level property states which P06 states the activity "
                "offers across its submissions. It is a coverage index over the "
                "activity, not a claim a candidate can be scored against, and it "
                "must never be counted as though it were a gate."
            ),
        },
        "combined_both_scopes": {
            **_population([*submission, *activity], BOTH_SCOPES),
            "includes_activity_level_coverage_index_statements": True,
            "rule": (
                "Reported only with the scope stated. This number is the size of "
                "the corpus material that touches UNCERTAIN at any scope; it is "
                "not a population of candidate gates."
            ),
        },
        "candidate_scoring_executable_asserting_uncertain": {
            **_population(executable, SUBMISSION_LEVEL),
            "is_the_blocking_readiness_fact": True,
            "rule": (
                "A submission-level property that reached an executable route "
                "with oracle_state VALID. Only this population can be observed "
                "by a qualification run."
            ),
        },
    }

    material = {
        "schema_version": P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
        "derivation_authority": (
            "FROZEN_ORACLE_PROPERTY_TEXT_AND_ACTIVITY_RUBRIC_SCALE"
        ),
        "derived_from_benchmark_tags": False,
        "counts_are_derived_not_declared": True,
        "scope_rule": (
            "Every count states its scope. A submission-level candidate-gate "
            "population is never summed with an activity-wide coverage-index "
            "statement without saying so."
        ),
        "p06_property_record_count": len(property_records),
        "populations": populations,
    }
    return {**material, "census_hash": canonical_hash(material)}


def uncertain_census_counts(census: Mapping[str, Any]) -> dict[str, int]:
    """Return the census row key -> count mapping the prose is generated from."""

    return {
        key: census["populations"][key]["count"] for key, _label in UNCERTAIN_CENSUS_ROWS
    }


def uncertain_census_markdown_table(census: Mapping[str, Any]) -> str:
    """Render the census as the exact table the phase document must carry."""

    counts = uncertain_census_counts(census)
    lines = ["| Population | Count |", "|---|---|"]
    for key, label in UNCERTAIN_CENSUS_ROWS:
        lines.append(f"| {label} | {counts[key]} |")
    return "\n".join(lines)


def uncertain_census_prose(census: Mapping[str, Any]) -> str:
    """Generate the corpus-semantics sentence from the derived counts."""

    populations = census["populations"]
    submission = populations["submission_level_asserting_uncertain"]
    valid_required = populations[
        "submission_level_asserting_uncertain_oracle_valid_kind_required"
    ]
    activity = populations["activity_level_describing_uncertain"]
    combined = populations["combined_both_scopes"]
    executable = populations["candidate_scoring_executable_asserting_uncertain"]
    return (
        f"The frozen corpus asserts UNCERTAIN in {submission['count']} "
        f"submission-level P06 properties across {submission['activity_count']} "
        f"activities, {valid_required['count']} of them with oracle_state VALID "
        f"and kind REQUIRED. A further {activity['count']} activity-level P06 "
        "properties describe UNCERTAIN as a coverage index over their activity's "
        f"submissions, which is not a candidate gate; both scopes together are "
        f"{combined['count']} properties. Of the submission-level population, "
        f"{executable['count']} reach an executable candidate-scoring route. The "
        "material exists; it cannot be routed."
    )


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
