"""Deterministically generate the semantic-benchmark/1.2.0 P06 definitions.

The v1.1 generator derived a route's target semantics from the first
``source_ref`` section of its oracle property, so ``construct`` recorded where
evidence sat rather than what was being verified.  This generator inverts that
order:

1. build the authorized construct catalog from real parser output over the
   activity's own rubric/assignment;
2. resolve each P06 property to exactly one *declared* authorized construct;
3. derive the model-visible route from the construct alone;
4. attach the submission evidence as evaluator-only provenance.

Ambiguous properties fail closed and are recorded as coverage debt rather than
receiving an invented generic route.

Run::

    python tools/generate_semantic_benchmark_v12_definitions.py
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.semantic_benchmark_v12 import (  # noqa: E402
    ACTIVITY_COVERAGE_INDEX_ONLY,
    CONTEXTUAL_NON_GATE,
    NOT_APPLICABLE,
    NO_UNAMBIGUOUS_CONSTRUCT,
    NO_VALID_STAGE_LOCAL_FIXTURE,
    ORACLE_SUSPECT_FOR_QUALIFICATION,
    P06_PROPERTY_BINDINGS_VERSION,
    P06_ROUTE_DEFINITIONS_VERSION,
    QUALIFICATION_DISPOSITIONS_VERSION,
    QUALIFICATION_VALID,
    SEMANTIC_BENCHMARK_V12_VERSION,
    build_construct_catalog,
    resolve_target_construct,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPOSITORY_ROOT / "evaluation/corpora/pruebas_personalizadas/v1"
V11_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_1"
V12_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2"

#: Held-out activity partition, inherited unchanged from v1.1.
HELD_OUT_ACTIVITY_NUMBERS = frozenset({3, 7, 9, 10, 12})

#: Hard-safety tag family, mirrored from the frozen Phase 9 safety gate so a
#: property excluded by fail-closed resolution can be reported as safety debt.
HARD_SAFETY_TAGS = frozenset(
    {
        "PROMPT_INJECTION_NOISY",
        "PROMPT_INJECTION_SILENT",
        "ADVERSARIAL_AUTHORIZED_SOURCE",
        "SIMULATED_PII",
        "EXTERNAL_KNOWLEDGE_TRAP",
    }
)

#: v1.2 P06 SMOKE membership is declared by *property*, not by a v1.1 case-id
#: string, because repaired routes renumber.  Retained pre-registered members
#: only; nothing was added after observing any output.
PRE_REGISTERED_P06_SMOKE_PROPERTIES = ("A01-S01-P3", "A01-S03-P1")

_SUBMISSION_ORDINAL = re.compile(r"(?<![\d,.])(0[1-9]|1[0-2])(?![\d,.])")


def _write(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return canonical_hash(payload)


def _activity_number(activity_path: str) -> int:
    return int(re.search(r"activity_(\d+)", activity_path).group(1))


def _split_for(activity_number: int) -> str:
    return "HELD_OUT_CONFIRMATION" if activity_number in HELD_OUT_ACTIVITY_NUMBERS else "CORE"


def _ratifications() -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CORPUS_ROOT.glob("activity_*/final_ratification.json"))
    ]


def _p06_properties(ratification: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    submission_level = [
        {**prop, "submission_id": submission["submission_id"],
         "submission_tags": list(submission.get("benchmark_tags", [])),
         "artifacts": list(submission["artifacts"])}
        for submission in ratification["submissions"]
        for prop in submission["properties"]
        if prop["stage"] == "P06"
    ]
    activity_level = [
        prop
        for prop in ratification["activity_level_properties"]
        if prop["stage"] == "P06"
    ]
    return submission_level, activity_level


def _activity_wide_disposition(prop: dict[str, Any]) -> tuple[str, str]:
    """Re-evaluate one activity-wide P06 property from its own structure.

    The question is narrow: can the model output of ONE authorized P06 call,
    scoped to ONE submission, demonstrate or refute this statement?
    """

    if prop["oracle_state"] == "NOT_APPLICABLE":
        return (
            NOT_APPLICABLE,
            "The corpus itself marks the property NOT_APPLICABLE as a hard semantic "
            "property, so it carries no candidate obligation at any stage.",
        )
    referenced_submissions = {
        ref["file"] for ref in prop["source_refs"] if "submissions/" in ref["file"]
    }
    if len(referenced_submissions) > 1:
        return (
            NO_VALID_STAGE_LOCAL_FIXTURE,
            "The statement is asserted across more than one submission. A P06 call "
            "is scoped to exactly one EvidenceBundle, so no single authorized call "
            "can evaluate it. It remains a corpus consistency assertion.",
        )
    ordinals = set(_SUBMISSION_ORDINAL.findall(prop["description"]))
    if len(ordinals) > 1:
        return (
            ACTIVITY_COVERAGE_INDEX_ONLY,
            "The statement indexes which submissions of the activity exhibit which "
            "support states. It describes corpus coverage, not a candidate decision, "
            "and one call sees only one submission. Scoring it from a single "
            "arbitrary submission route would be the v1.1 defect.",
        )
    if prop["kind"] == "CONTEXTUAL_NOTE":
        return (
            CONTEXTUAL_NON_GATE,
            "A reviewable contextual note without a case-local candidate obligation.",
        )
    return (
        NO_UNAMBIGUOUS_CONSTRUCT,
        "No single authorized stage-local construct could be resolved.",
    )


def main() -> None:
    catalog = build_construct_catalog(CORPUS_ROOT)
    constructs_by_activity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for construct in catalog["constructs"]:
        constructs_by_activity[construct["activity_id"]].append(construct)

    routes: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    coverage_debt: list[dict[str, Any]] = []

    for ratification in _ratifications():
        activity_id = ratification["activity_id"]
        activity_path = ratification["activity_path"]
        number = _activity_number(activity_path)
        split = _split_for(number)
        constructs = constructs_by_activity[activity_id]
        submission_level, activity_level = _p06_properties(ratification)

        resolved_by_submission: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for prop in submission_level:
            resolution = resolve_target_construct(prop["description"], constructs)
            description_hash = canonical_hash(prop["description"])
            if not resolution["resolved"]:
                dispositions.append(
                    {
                        "property_id": prop["property_id"],
                        "stage": "P06",
                        "scope": "SUBMISSION_LOCAL",
                        "activity_id": activity_id,
                        "submission_id": prop["submission_id"],
                        "original_oracle_state": prop["oracle_state"],
                        "original_kind": prop["kind"],
                        "original_description_hash": description_hash,
                        "qualification_disposition": resolution["disposition"],
                        "reason": resolution["reason"],
                        "audit_provenance": "PHASE_9B4_P06_CONSTRUCT_RESOLUTION",
                        "source_evidence": [
                            f"{ref['file']}#{ref.get('section', '')}"
                            for ref in prop["source_refs"]
                        ],
                        "candidate_scoring_allowed": False,
                        "candidate_construct_keys": resolution["candidate_construct_keys"],
                    }
                )
                lost_tags = sorted(
                    set(prop["benchmark_tags"]) | set(prop["submission_tags"])
                )
                coverage_debt.append(
                    {
                        "property_id": prop["property_id"],
                        "activity_id": activity_id,
                        "submission_id": prop["submission_id"],
                        "split": split,
                        "disposition": resolution["disposition"],
                        "reason": resolution["reason"],
                        "v11_had_executable_route": True,
                        "lost_tags": lost_tags,
                        "safety_relevant": bool(set(lost_tags) & HARD_SAFETY_TAGS),
                    }
                )
                continue
            resolved_by_submission[prop["submission_id"]].append(
                (resolution["construct_key"], {"property": prop, "resolution": resolution})
            )

        for submission_id, items in sorted(resolved_by_submission.items()):
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for construct_key, payload in items:
                grouped[construct_key].append(payload)
            for index, construct_key in enumerate(sorted(grouped), start=1):
                payloads = grouped[construct_key]
                construct = payloads[0]["resolution"]["construct"]
                properties = [item["property"] for item in payloads]
                route_fixture_id = (
                    f"P06-A{number:02d}-"
                    f"S{int(re.search(r'(\d+)', submission_id).group(1)):02d}-"
                    f"R{index:02d}"
                )
                case_id = (
                    f"PP-A{number:02d}-"
                    f"S{int(re.search(r'(\d+)', submission_id).group(1)):02d}-"
                    f"P06-R{index:02d}"
                )
                property_ids = sorted(item["property_id"] for item in properties)
                fixture_tags = sorted(
                    {tag for item in properties for tag in item["benchmark_tags"]}
                    | set(properties[0]["submission_tags"])
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
                            "source_refs": construct["source_refs"],
                            "source_hashes": construct["source_hashes"],
                            "extraction": construct["provenance"],
                        },
                        "evidence_provenance": {
                            "scope": "WHOLE_SUBMISSION_EVIDENCE_BUNDLE",
                            "artifacts": properties[0]["artifacts"],
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
                                "submission bundle and must locate evidence itself; "
                                "no location is projected into the route."
                            ),
                        },
                        "oracle_binding_metadata": {"property_ids": property_ids},
                        "fixture_tags": fixture_tags,
                        "tag_provenance_scope": "CASE_SCOPED_PROPERTY_AND_SUBMISSION",
                        "derivation_method": (
                            "DECLARED_AUTHORIZED_CONSTRUCT_THEN_SUBMISSION_EVIDENCE"
                        ),
                    }
                )
                for item in payloads:
                    prop = item["property"]
                    resolution = item["resolution"]
                    valid = prop["oracle_state"] == "VALID"
                    bindings.append(
                        {
                            "property_id": prop["property_id"],
                            "stage": "P06",
                            "binding_scope": "CASE_SPECIFIC",
                            "alignment_status": "ALIGNED",
                            "fixture_id": route_fixture_id,
                            "primary_case_id": case_id,
                            "additional_case_ids": [],
                            "oracle_state": prop["oracle_state"],
                            "property_target_construct_key": construct_key,
                            "route_target_construct_key": construct_key,
                            "selection_rule": "SINGLE_DECLARED_AUTHORIZED_CONSTRUCT",
                            "why_route_exercises_property": (
                                f"The property declares its target criterion "
                                f"({construct['canonical_source_name']!r}); the route's "
                                f"model-visible construct is that same authorized "
                                f"criterion, and the call is scoped to the submission "
                                f"the property is about."
                            ),
                            "construct_match_evidence": resolution["match_evidence"],
                            "construct_provenance": construct["source_refs"],
                            "evidence_provenance": [
                                f"{ref['file']}#{ref.get('section', '')}"
                                for ref in prop["source_refs"]
                            ],
                            "exclusion_reason": None,
                        }
                    )
                    dispositions.append(
                        {
                            "property_id": prop["property_id"],
                            "stage": "P06",
                            "scope": "SUBMISSION_LOCAL",
                            "activity_id": activity_id,
                            "submission_id": submission_id,
                            "original_oracle_state": prop["oracle_state"],
                            "original_kind": prop["kind"],
                            "original_description_hash": canonical_hash(
                                prop["description"]
                            ),
                            "qualification_disposition": (
                                QUALIFICATION_VALID
                                if valid
                                else ORACLE_SUSPECT_FOR_QUALIFICATION
                            ),
                            "reason": (
                                "Resolved to exactly one authorized construct declared "
                                "by the property itself."
                                if valid
                                else "Resolved to one authorized construct, but the "
                                "corpus records the oracle itself as unable to decide, "
                                "so it cannot produce a hard MODEL_FAILURE."
                            ),
                            "audit_provenance": "PHASE_9B4_P06_CONSTRUCT_RESOLUTION",
                            "source_evidence": [
                                f"{ref['file']}#{ref.get('section', '')}"
                                for ref in prop["source_refs"]
                            ],
                            "candidate_scoring_allowed": valid,
                            "target_construct_key": construct_key,
                        }
                    )

        for prop in activity_level:
            disposition, reason = _activity_wide_disposition(prop)
            dispositions.append(
                {
                    "property_id": prop["property_id"],
                    "stage": "P06",
                    "scope": "ACTIVITY_WIDE",
                    "activity_id": activity_id,
                    "submission_id": None,
                    "original_oracle_state": prop["oracle_state"],
                    "original_kind": prop["kind"],
                    "original_description_hash": canonical_hash(prop["description"]),
                    "qualification_disposition": disposition,
                    "reason": reason,
                    "audit_provenance": "PHASE_9B4_ACTIVITY_WIDE_REEVALUATION",
                    "source_evidence": [
                        f"{ref['file']}#{ref.get('section', '')}"
                        for ref in prop["source_refs"]
                    ],
                    "candidate_scoring_allowed": False,
                    "v11_binding_scope": "ACTIVITY_WIDE",
                }
            )
            coverage_debt.append(
                {
                    "property_id": prop["property_id"],
                    "activity_id": activity_id,
                    "submission_id": None,
                    "split": split,
                    "disposition": disposition,
                    "reason": reason,
                    "v11_had_executable_route": prop["property_id"] in {"A01-ACT-P5"},
                    "lost_tags": sorted(prop["benchmark_tags"]),
                    "safety_relevant": bool(
                        set(prop["benchmark_tags"]) & HARD_SAFETY_TAGS
                    ),
                }
            )

    identities: dict[tuple[str, str], list[str]] = defaultdict(list)
    for route in routes:
        identities[(route["submission_id"], route["activity_id"])].append(
            route["target_construct_key"]
        )
    for key, values in identities.items():
        if len(values) != len(set(values)):
            raise SystemExit(f"intra-submission construct collision at {key}")

    v11_bindings = json.loads(
        (V11_ROOT / "fixtures/property_bindings.json").read_text(encoding="utf-8")
    )
    carried = [item for item in v11_bindings["bindings"] if item["stage"] != "P06"]

    smoke_properties = sorted(
        prop
        for prop in PRE_REGISTERED_P06_SMOKE_PROPERTIES
        if any(prop in binding["property_id"] for binding in bindings
               if binding["property_id"] == prop)
    )
    smoke_case_ids = sorted(
        {
            binding["primary_case_id"]
            for binding in bindings
            if binding["property_id"] in smoke_properties
        }
    )
    for route in routes:
        if route["case_id"] in smoke_case_ids:
            route["split"] = "SMOKE"
    suspended_smoke = sorted(set(PRE_REGISTERED_P06_SMOKE_PROPERTIES) - set(smoke_properties))

    catalog_hash = _write(V12_ROOT / "fixtures/p06_construct_catalog.json", catalog)
    routes_doc = {
        "schema_version": P06_ROUTE_DEFINITIONS_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V12_VERSION,
        "construct_catalog_hash": catalog["catalog_hash"],
        "derivation_policy": {
            "target_construct_first": True,
            "location_derived_semantics_forbidden": True,
            "ambiguous_properties_fail_closed": True,
            "route_count_is_not_a_target": True,
        },
        "routes": sorted(routes, key=lambda item: item["route_fixture_id"]),
        "route_count": len(routes),
    }
    routes_hash = _write(V12_ROOT / "fixtures/p06_routes.json", routes_doc)
    bindings_doc = {
        "schema_version": P06_PROPERTY_BINDINGS_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V12_VERSION,
        "carried_forward_from": "semantic-benchmark/1.1.0",
        "carried_forward_stages": ["P04", "PLANNER", "P07", "P09"],
        "bindings": sorted(
            carried + bindings, key=lambda item: (item["stage"], item["property_id"])
        ),
        "property_count": len(carried) + len(bindings),
        "p06_binding_count": len(bindings),
        "assigned_arbitrarily_count": 0,
    }
    bindings_hash = _write(V12_ROOT / "fixtures/property_bindings.json", bindings_doc)
    dispositions_doc = {
        "schema_version": QUALIFICATION_DISPOSITIONS_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V12_VERSION,
        "scope": "QUALIFICATION_LEVEL_ONLY",
        "corpus_history_rewritten": False,
        "note": (
            "A qualification disposition never edits corpus ratification bytes. The "
            "corpus records what the reviewer ratified; this artifact records whether "
            "semantic-benchmark/1.2.0 may score a candidate against it."
        ),
        "dispositions": sorted(dispositions, key=lambda item: item["property_id"]),
        "disposition_count": len(dispositions),
    }
    dispositions_hash = _write(
        V12_ROOT / "fixtures/qualification_oracle_dispositions.json", dispositions_doc
    )
    debt_doc = {
        "schema_version": "p06-coverage-debt/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_V12_VERSION,
        "policy": "A smaller valid benchmark is preferable to a larger invalid one.",
        "smoke_membership": {
            "pre_registered_p06_properties": list(PRE_REGISTERED_P06_SMOKE_PROPERTIES),
            "retained": smoke_properties,
            "suspended": suspended_smoke,
            "replacement_added_after_observation": False,
            "case_ids": smoke_case_ids,
        },
        "entries": sorted(coverage_debt, key=lambda item: item["property_id"]),
        "entry_count": len(coverage_debt),
    }
    debt_hash = _write(V12_ROOT / "fixtures/p06_coverage_debt.json", debt_doc)

    print(json.dumps({
        "construct_count": catalog["construct_count"],
        "catalog_hash": catalog_hash,
        "route_count": len(routes),
        "routes_hash": routes_hash,
        "p06_binding_count": len(bindings),
        "bindings_hash": bindings_hash,
        "disposition_count": len(dispositions),
        "dispositions_hash": dispositions_hash,
        "coverage_debt_count": len(coverage_debt),
        "coverage_debt_hash": debt_hash,
        "smoke_retained": smoke_properties,
        "smoke_suspended": suspended_smoke,
    }, indent=2))


if __name__ == "__main__":
    main()
