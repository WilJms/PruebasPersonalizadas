"""Derive the repaired P06 route set (Phase 9B.6 remediation).

This module answers one question: *what would the P06 instrument be if the
fail-closed resolver of :mod:`p06_construct_resolution` replaced the v1.2 one?*
It is the input to the Phase 9B.6 coverage measurements, which the task
requires to be computed from **final executable routes** rather than inherited
from Phase 9B.5 diagnostics.

It deliberately does not write into ``evaluation/semantic_benchmark/v1_2``.
``semantic-benchmark/1.2.0`` is historical after the Phase 9B.5 audit and its
frozen authority bytes stay exactly as they are; this derivation is held in
memory and reported, so the v1.2 pre-results instrument freeze continues to
reproduce byte-for-byte from the v1.2 code path.

Routing, candidate families, reasoning rungs, caps, split partition and the
0.80/0.95/0.95 accepted-rate bars are inherited unchanged.  The only thing that
changes is which properties are allowed to become executable candidate gates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .canonical import canonical_hash
from .p06_construct_resolution import (
    P06_CONSTRUCT_RESOLUTION_VERSION,
    resolve_declared_construct,
)
from .semantic_benchmark_v12 import build_construct_catalog


P06_REMEDIATED_DERIVATION_VERSION = "p06-remediated-derivation/1.3.0"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPOSITORY_ROOT / "evaluation/corpora/pruebas_personalizadas/v1"

#: Inherited unchanged from v1.1/v1.2.  Held-out membership is never revised
#: after observing an outcome, and nothing here observes one.
HELD_OUT_ACTIVITY_NUMBERS = frozenset({3, 7, 9, 10, 12})

#: Pre-registered SMOKE membership, by property.  Retained only if the property
#: still earns an executable route under the repaired resolver.
PRE_REGISTERED_P06_SMOKE_PROPERTIES = ("A01-S01-P3", "A01-S03-P1")

HARD_SAFETY_TAGS = frozenset(
    {
        "PROMPT_INJECTION_NOISY",
        "PROMPT_INJECTION_SILENT",
        "ADVERSARIAL_AUTHORIZED_SOURCE",
        "SIMULATED_PII",
        "EXTERNAL_KNOWLEDGE_TRAP",
    }
)


@dataclass(frozen=True)
class RemediatedP06Derivation:
    catalog: dict[str, Any]
    routes: list[dict[str, Any]]
    bindings: list[dict[str, Any]]
    coverage_debt: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    property_descriptions: dict[str, str]
    constructs_by_activity: dict[str, list[dict[str, Any]]]
    scoring_property_ids: tuple[str, ...]

    @property
    def route_count(self) -> int:
        return len(self.routes)


def _activity_number(activity_path: str) -> int:
    return int(re.search(r"activity_(\d+)", activity_path).group(1))


def _split_for(activity_number: int) -> str:
    return (
        "HELD_OUT_CONFIRMATION"
        if activity_number in HELD_OUT_ACTIVITY_NUMBERS
        else "CORE"
    )


def _ratifications(corpus_root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(corpus_root.glob("activity_*/final_ratification.json"))
    ]


#: The two scopes at which the ratified corpus states a P06 property.  A
#: submission-level property is a claim about one submission and is the only
#: thing that can ever become a candidate gate.  An activity-level property is
#: a coverage-index statement about the activity as a whole -- "this activity
#: offers all four P06 states across its submissions" -- and is never a gate.
#: They are counted separately for exactly that reason.
SUBMISSION_SCOPE = "SUBMISSION"
ACTIVITY_SCOPE = "ACTIVITY"


def p06_property_inventory(
    corpus_root: Path = CORPUS_ROOT,
) -> tuple[dict[str, Any], ...]:
    """Return every ratified P06 property, at both scopes, with its metadata.

    This is the inventory any P06 count must be derived from.  It carries the
    scope explicitly so a submission-level candidate-gate population is never
    silently added to an activity-level coverage-index statement.
    """

    records: list[dict[str, Any]] = []
    for ratification in _ratifications(corpus_root):
        activity_id = ratification["activity_id"]
        for submission in ratification["submissions"]:
            for prop in submission["properties"]:
                if prop["stage"] != "P06":
                    continue
                records.append(
                    {
                        "property_id": prop["property_id"],
                        "scope": SUBMISSION_SCOPE,
                        "activity_id": activity_id,
                        "submission_id": submission["submission_id"],
                        "kind": prop["kind"],
                        "oracle_state": prop["oracle_state"],
                        "description": prop["description"],
                    }
                )
        for prop in ratification.get("activity_level_properties", []):
            if prop["stage"] != "P06":
                continue
            records.append(
                {
                    "property_id": prop["property_id"],
                    "scope": ACTIVITY_SCOPE,
                    "activity_id": activity_id,
                    "submission_id": None,
                    "kind": prop["kind"],
                    "oracle_state": prop["oracle_state"],
                    "description": prop["description"],
                }
            )
    return tuple(sorted(records, key=lambda item: item["property_id"]))


def derive_remediated_p06(
    corpus_root: Path = CORPUS_ROOT,
) -> RemediatedP06Derivation:
    """Build the repaired P06 route/binding/debt set from frozen authority."""

    catalog = build_construct_catalog(corpus_root)
    constructs_by_activity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for construct in catalog["constructs"]:
        constructs_by_activity[construct["activity_id"]].append(construct)

    routes: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    coverage_debt: list[dict[str, Any]] = []
    property_descriptions: dict[str, str] = {}
    scoring: list[str] = []

    for ratification in _ratifications(corpus_root):
        activity_id = ratification["activity_id"]
        number = _activity_number(ratification["activity_path"])
        split = _split_for(number)
        constructs = constructs_by_activity[activity_id]

        resolved_by_submission: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for submission in ratification["submissions"]:
            submission_tags = list(submission.get("benchmark_tags", []))
            for prop in submission["properties"]:
                if prop["stage"] != "P06":
                    continue
                property_descriptions[prop["property_id"]] = prop["description"]
                resolution = resolve_declared_construct(prop["description"], constructs)
                if not resolution.resolved:
                    lost_tags = sorted(
                        set(prop["benchmark_tags"]) | set(submission_tags)
                    )
                    coverage_debt.append(
                        {
                            "property_id": prop["property_id"],
                            "activity_id": activity_id,
                            "submission_id": submission["submission_id"],
                            "split": split,
                            "disposition": resolution.disposition,
                            "reason": resolution.reason,
                            "lost_tags": lost_tags,
                            "safety_relevant": bool(set(lost_tags) & HARD_SAFETY_TAGS),
                            "blocking_references": list(
                                resolution.blocking_references
                            ),
                        }
                    )
                    continue
                resolved_by_submission[submission["submission_id"]].append(
                    {
                        "property": prop,
                        "submission_tags": submission_tags,
                        "artifacts": list(submission["artifacts"]),
                        "resolution": resolution,
                    }
                )

        for submission_id, items in sorted(resolved_by_submission.items()):
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in items:
                grouped[str(item["resolution"].construct_key)].append(item)
            submission_number = int(re.search(r"(\d+)", submission_id).group(1))
            for index, construct_key in enumerate(sorted(grouped), start=1):
                payloads = grouped[construct_key]
                construct = dict(payloads[0]["resolution"].construct or {})
                properties = [item["property"] for item in payloads]
                route_fixture_id = (
                    f"P06-A{number:02d}-S{submission_number:02d}-R{index:02d}"
                )
                case_id = f"PP-A{number:02d}-S{submission_number:02d}-P06-R{index:02d}"
                fixture_tags = sorted(
                    {tag for item in properties for tag in item["benchmark_tags"]}
                    | set(payloads[0]["submission_tags"])
                )
                routes.append(
                    {
                        "route_fixture_id": route_fixture_id,
                        "case_id": case_id,
                        "activity_id": activity_id,
                        "submission_id": submission_id,
                        "split": split,
                        "target_construct_key": construct_key,
                        "construct_provenance": {
                            "source_kind": construct["source_kind"],
                            "canonical_source_name": construct["canonical_source_name"],
                            "source_refs": list(construct["source_refs"]),
                            "source_hashes": dict(construct["source_hashes"]),
                            "extraction": construct["provenance"],
                        },
                        "evidence_provenance": {
                            "scope": "WHOLE_SUBMISSION_EVIDENCE_BUNDLE",
                            "artifacts": payloads[0]["artifacts"],
                            "oracle_declared_locations": sorted(
                                {
                                    f"{ref['file']}#{ref.get('section', '')}"
                                    for item in properties
                                    for ref in item["source_refs"]
                                }
                            ),
                            "model_visible": False,
                            "note": (
                                "Evaluator-only. The model receives the whole "
                                "submission bundle and must locate the supporting "
                                "evidence itself; no submission evidence location is "
                                "projected into the route. Authorized rubric "
                                "descriptor text is a separate matter and is "
                                "documented in the route's construct provenance."
                            ),
                        },
                        "oracle_binding_metadata": {
                            "property_ids": sorted(
                                item["property_id"] for item in properties
                            )
                        },
                        "fixture_tags": fixture_tags,
                        "derivation_method": (
                            "FAIL_CLOSED_DECLARED_AUTHORIZED_CONSTRUCT"
                        ),
                        "resolver_version": P06_CONSTRUCT_RESOLUTION_VERSION,
                    }
                )
                for item in payloads:
                    prop = item["property"]
                    valid = prop["oracle_state"] == "VALID"
                    if valid:
                        scoring.append(prop["property_id"])
                    bindings.append(
                        {
                            "property_id": prop["property_id"],
                            "stage": "P06",
                            "binding_scope": "CASE_SPECIFIC",
                            "fixture_id": route_fixture_id,
                            "primary_case_id": case_id,
                            "oracle_state": prop["oracle_state"],
                            "property_target_construct_key": construct_key,
                            "route_target_construct_key": construct_key,
                            "selection_rule": (
                                "SINGLE_DECLARED_AUTHORIZED_CONSTRUCT_FAIL_CLOSED"
                            ),
                            "candidate_scoring_allowed": valid,
                            "construct_reference_accounting": [
                                observation.as_dict()
                                for observation in item["resolution"].observations
                            ],
                        }
                    )

    smoke_properties = sorted(
        prop
        for prop in PRE_REGISTERED_P06_SMOKE_PROPERTIES
        if any(binding["property_id"] == prop for binding in bindings)
    )
    smoke_case_ids = {
        binding["primary_case_id"]
        for binding in bindings
        if binding["property_id"] in smoke_properties
    }
    for route in routes:
        if route["case_id"] in smoke_case_ids:
            route["split"] = "SMOKE"

    cases = [
        {
            "case_id": route["case_id"],
            "stage": "P06",
            "split": route["split"],
            "activity_id": route["activity_id"],
            "submission_id": route["submission_id"],
            "fixture_id": route["route_fixture_id"],
            "fixture_tags": list(route["fixture_tags"]),
            "property_ids": list(route["oracle_binding_metadata"]["property_ids"]),
        }
        for route in routes
    ]

    return RemediatedP06Derivation(
        catalog=catalog,
        routes=sorted(routes, key=lambda item: item["route_fixture_id"]),
        bindings=sorted(bindings, key=lambda item: item["property_id"]),
        coverage_debt=sorted(coverage_debt, key=lambda item: item["property_id"]),
        cases=sorted(cases, key=lambda item: item["case_id"]),
        property_descriptions=property_descriptions,
        constructs_by_activity=dict(constructs_by_activity),
        scoring_property_ids=tuple(sorted(scoring)),
    )


def derivation_summary(derivation: RemediatedP06Derivation) -> dict[str, Any]:
    """Summarise the repaired derivation without asserting any target count."""

    by_split: dict[str, int] = defaultdict(int)
    for route in derivation.routes:
        by_split[route["split"]] += 1
    by_disposition: dict[str, int] = defaultdict(int)
    for entry in derivation.coverage_debt:
        by_disposition[entry["disposition"]] += 1
    material = {
        "schema_version": P06_REMEDIATED_DERIVATION_VERSION,
        "resolver_version": P06_CONSTRUCT_RESOLUTION_VERSION,
        "route_count": len(derivation.routes),
        "routes_by_split": dict(sorted(by_split.items())),
        "candidate_scoring_property_count": len(derivation.scoring_property_ids),
        "coverage_debt_count": len(derivation.coverage_debt),
        "coverage_debt_by_disposition": dict(sorted(by_disposition.items())),
        "construct_count": derivation.catalog["construct_count"],
        "route_count_is_not_a_target": True,
    }
    return {**material, "summary_hash": canonical_hash(material)}
