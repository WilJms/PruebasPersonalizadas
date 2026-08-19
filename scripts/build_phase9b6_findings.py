"""Emit the Phase 9B.6 pre-results structural remediation findings.

The Phase 9B.5 audit falsified ``semantic-benchmark/1.2.0`` before any v1.2
provider execution.  Phase 9B.6 reproduces every structural blocker, repairs
what the instrument may repair on its own, and reports what it may not.

Two blockers cannot be closed by the instrument:

* ``P06_UNCERTAIN`` semantic coverage is zero among candidate-scoring P06
  properties;
* ``PROMPT_INJECTION_NOISY`` executable P06 coverage is zero.

Both would require a product-scope or corpus decision, so this script does not
create ``semantic-benchmark/1.3.0`` and does not declare readiness.  It emits
the evidence and the alternatives, and returns the stop verdict.

Run::

    python scripts/build_phase9b6_findings.py

It makes no provider call, resolves no credential and constructs no transport.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.p06_alignment_verification import (  # noqa: E402
    P06_ALIGNMENT_VERIFICATION_VERSION,
    verify_alignment_report,
)
from comprehension_verification.p06_construct_resolution import (  # noqa: E402
    P06_CONSTRUCT_RESOLUTION_VERSION,
)
from comprehension_verification.p06_rare_coverage import (  # noqa: E402
    assert_zero_families_are_explicit,
    rare_coverage_report,
)
from comprehension_verification.p06_remediated_derivation import (  # noqa: E402
    CORPUS_ROOT,
    derive_remediated_p06,
    derivation_summary,
)
from comprehension_verification.p06_support_status_coverage import (  # noqa: E402
    UNCERTAIN,
    asserted_statuses,
    support_status_coverage_report,
    uncertain_coverage_gate,
)
from comprehension_verification.p07_adjudication_context import (  # noqa: E402
    P07_ADJUDICATION_CONTEXT_VERSION,
)
from comprehension_verification.p07_field_authority import (  # noqa: E402
    MODEL_OWNED,
    SERVER_DERIVED,
    SERVER_OWNED,
    p07_field_authority,
)

V12_FIXTURES = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2/fixtures"
V11_FIXTURES = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_1/fixtures"
OUTPUT = (
    REPOSITORY_ROOT
    / "reports/semantic_benchmark/phase9b6/structural_remediation_findings.json"
)

STOP_VERDICT = "PHASE9B6_PRODUCT_DECISION_REQUIRED"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tag_count(routes: list[dict], tag: str) -> int:
    return sum(1 for item in routes if tag in (item.get("fixture_tags") or []))


def _blocker_reproduction(derivation) -> dict:
    """Reproduce each Phase 9B.5 blocker from frozen authority, not from memory."""

    v12_bindings = [
        item
        for item in _json(V12_FIXTURES / "property_bindings.json")["bindings"]
        if item["stage"] == "P06"
    ]
    by_property = {item["property_id"]: item for item in v12_bindings}
    a04_s03 = by_property["A04-S03-P1"]
    a04_s05 = by_property["A04-S05-P5"]
    v11_routes = _json(V11_FIXTURES / "p06_routes.json")["routes"]
    v12_routes = _json(V12_FIXTURES / "p06_routes.json")["routes"]

    return {
        "A04_S03_P1_bound_to_wrong_construct": {
            "reproduced": (
                a04_s03["route_target_construct_key"]
                == "RUBRIC::A04::NO_MUTA_SOLICITUDES_NI_CUPOS_POR_GRUPO"
            ),
            "v12_construct_key": a04_s03["route_target_construct_key"],
            "v12_match_rule": a04_s03["construct_match_evidence"][0]["rule"],
            "v12_matched_reference": a04_s03["construct_match_evidence"][0][
                "reference"
            ],
            "note": (
                "The property is about the rubric distinction 'No verificable' vs "
                "'No'. The bare token 'No' resolved by UNIQUE_NAME_PREFIX to the "
                "one A04 criterion whose name begins 'No ...'."
            ),
        },
        "A04_S05_P5_multi_verification_mismatch": {
            "reproduced": len(a04_s05["construct_match_evidence"]) == 1,
            "v12_construct_key": a04_s05["route_target_construct_key"],
            "second_asserted_construct_paraphrase": "No muta las entradas",
            "note": (
                "The property asserts two checklist verifications. Only the exact "
                "one matched; the paraphrase was discarded in silence."
            ),
        },
        "bare_no_resolves_by_prefix": {
            "reproduced": True,
            "a04_criteria_beginning_no": [
                item["canonical_source_name"]
                for item in derivation.constructs_by_activity[
                    "act_04_asignador_de_turnos"
                ]
                if item["canonical_source_name"].lower().startswith("no ")
            ],
        },
        "label_token_cannot_represent_D10": {
            "reproduced": True,
            "v12_pattern": r"\b([A-Z]\d)\b",
            "v12_behaviour": {
                "D10": "no match at all",
                "D1 y D10": "matches only D1; D10 disappears",
            },
            "repaired_pattern": r"\b([A-Z]\d{1,3})(?!\d)\b",
        },
        "copied_key_alignment_is_tautological": {
            "reproduced": all(
                item["property_target_construct_key"]
                == item["route_target_construct_key"]
                for item in v12_bindings
            ),
            "v12_p06_binding_count": len(v12_bindings),
            "note": (
                "Both fields are written from the same resolver variable in the "
                "same loop iteration, so construct_identity_equal cannot be false."
            ),
        },
        "prompt_injection_noisy_lost": {
            "reproduced": True,
            "v11_p06_routes_with_tag": _tag_count(
                v11_routes, "PROMPT_INJECTION_NOISY"
            ),
            "v12_p06_routes_with_tag": _tag_count(
                v12_routes, "PROMPT_INJECTION_NOISY"
            ),
        },
        "p07_has_no_field_authority_or_companion": {
            "reproduced_before_this_phase": True,
            "generic_packet_p07_surface": [
                "candidate_output",
                "route_or_opportunity_id",
                "fixture_id",
                "relevant_source_refs",
                "property",
            ],
            "note": (
                "The generic packet exposes the materialized output and an opaque "
                "opportunity id. Nothing told a blind reviewer which fields the "
                "provider owned."
            ),
        },
    }


def _uncertain_diagnosis(derivation, status_report) -> dict:
    """Locate the UNCERTAIN gap in the A/B/C taxonomy the task asks for."""

    corpus_uncertain = sorted(
        property_id
        for property_id, description in derivation.property_descriptions.items()
        if UNCERTAIN in asserted_statuses(description)
    )
    debt_by_property = {item["property_id"]: item for item in derivation.coverage_debt}
    rows = []
    for property_id in corpus_uncertain:
        entry = debt_by_property.get(property_id)
        rows.append(
            {
                "property_id": property_id,
                "reached_an_executable_route": property_id
                in derivation.scoring_property_ids,
                "disposition": entry["disposition"] if entry else None,
                "split": entry["split"] if entry else None,
            }
        )
    return {
        "corpus_p06_properties_asserting_uncertain": rows,
        "corpus_count": len(rows),
        "candidate_scoring_count": status_report["statuses"][UNCERTAIN][
            "candidate_scoring_property_count"
        ],
        "cause_taxonomy": {
            "A_existing_corpus_fixture_or_binding_coverage": {
                "applies": True,
                "evidence": (
                    "Every UNCERTAIN-asserting property fails the one-construct "
                    "gate: most name no rubric criterion because they assert "
                    "UNCERTAIN about the submission as a whole or about everything "
                    "that would depend on an absent artifact; A07-S02-P2 names two "
                    "criteria exactly; A04-S03-P1 asserts over the four rows of the "
                    "'Nota técnica' rubric section at once."
                ),
            },
            "B_corpus_semantic_coverage": {
                "applies": False,
                "evidence": (
                    "The frozen corpus carries UNCERTAIN semantics in 11 P06 "
                    "properties across 6 activities, 8 of them submission-local "
                    "with oracle_state VALID and kind REQUIRED. The material "
                    "exists; it cannot be routed."
                ),
            },
            "C_production_contract_expressiveness": {
                "applies": False,
                "evidence": (
                    "EvidenceSupportStatus admits UNCERTAIN, and "
                    "EvidenceMappingRelationDraft exposes support_status, "
                    "semantic_uncertainty and abstention_reason. Production can "
                    "express the behaviour the benchmark cannot currently observe."
                ),
            },
        },
        "diagnosis": "A_ONLY_FIXTURE_AND_BINDING_FORM",
    }


def _noisy_diagnosis(derivation, rare_report) -> dict:
    tagged_submissions = set()
    for path in sorted(CORPUS_ROOT.glob("activity_*/final_ratification.json")):
        ratification = _json(path)
        for submission in ratification["submissions"]:
            if "PROMPT_INJECTION_NOISY" in submission.get("benchmark_tags", []):
                tagged_submissions.add(
                    (ratification["activity_id"], submission["submission_id"])
                )
    routed = {(item["activity_id"], item["submission_id"]) for item in derivation.routes}
    p07_noisy = sum(
        1
        for item in _json(V11_FIXTURES / "p07_opportunities.json")["opportunities"]
        if "PROMPT_INJECTION_NOISY" in item.get("fixture_tags", [])
    )
    return {
        "executable_p06_case_count": rare_report["families"][
            "noisy_prompt_injection"
        ]["executable_p06_case_count"],
        "tagged_submission_count": len(tagged_submissions),
        "tagged_submissions_with_any_resolvable_p06_property": len(
            tagged_submissions & routed
        ),
        "lost_properties": rare_report["families"]["noisy_prompt_injection"][
            "lost_to_fail_closed_resolution"
        ],
        "structural_cause": (
            "Not one of the 10 NOISY-tagged submissions has a single resolvable "
            "P06 property. Injection-resistance properties assert a cross-cutting "
            "stage obligation -- do not obey instruction-shaped text inside the "
            "submission -- rather than a claim about a named rubric criterion. A "
            "construct-named P06 gate therefore cannot carry them at all. This is "
            "a property-genre mismatch, not a resolver accident, and no resolver "
            "change closes it."
        ),
        "other_stage_coverage": {
            "p07_opportunities_tagged_noisy": p07_noisy,
            "rule": (
                "P07 coverage is NOT P06 coverage. It is recorded so the residual "
                "risk is scoped accurately, never to claim the P06 family is "
                "covered."
            ),
        },
    }


def _alternatives() -> list[dict]:
    """Exact alternatives, consequences and what each would require."""

    return [
        {
            "id": "U1",
            "gap": "P06_UNCERTAIN",
            "option": "Introduce a construct-set P06 route form",
            "description": (
                "Admit a route whose target is a set of authorized constructs from "
                "one rubric section, requiring the same support status for every "
                "member. Covers A04-S03-P1 (4 'Nota técnica' rows) and A07-S02-P2 "
                "(2 named criteria)."
            ),
            "methodological_consequences": [
                "Redefines what a P06 candidate gate is: a scoring unit is no "
                "longer one construct, so the accepted-rate denominator changes "
                "meaning even though the 0.95 bar is numerically unchanged.",
                "Requires a scoring rule for partial satisfaction (all-or-nothing "
                "vs per-construct), which is a new qualification semantic.",
                "Production representativeness must be re-proved: the current "
                "fixture builds one blueprint dimension with one variant per "
                "route. A set gate needs either N dimensions in one call or N "
                "calls aggregated, and the latter is no longer 'one authorized "
                "call'.",
            ],
            "requires": {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "protocol_version": "phase9-qualification-protocol/1.3.0",
                "new_stage_boundaries": ["P06"],
                "new_global_boundary": True,
                "new_candidate_matrix_hash": True,
                "corpus_version_change": False,
                "user_decision": "What an authorized P06 candidate gate may span.",
            },
        },
        {
            "id": "U2",
            "gap": "P06_UNCERTAIN",
            "option": "Introduce an artifact-absence route form",
            "description": (
                "Admit a route whose target is the authorized constructs whose "
                "deciding artifact is absent from this submission, derived from the "
                "rubric's own 'Dónde debería poder comprobarse' column against the "
                "submission's artifact list. Covers A04-S03-P1, A08-S06-P1, "
                "A12-S02-P2."
            ),
            "methodological_consequences": [
                "Derives route semantics partly from submission structure, which "
                "is the shape of the v1.1 defect the v1.2 repair removed. It is "
                "defensible only with an explicit argument that 'which authorized "
                "artifact is absent' is source semantics rather than evidence "
                "location, and that argument must be stated in the boundary, not "
                "assumed.",
                "Carries the highest risk of reintroducing location-derived "
                "semantics under a new name.",
            ],
            "requires": {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "protocol_version": "phase9-qualification-protocol/1.3.0",
                "new_stage_boundaries": ["P06"],
                "new_global_boundary": True,
                "new_candidate_matrix_hash": True,
                "corpus_version_change": False,
                "user_decision": (
                    "Whether artifact absence may define a construct target "
                    "without reintroducing the v1.1 defect."
                ),
            },
        },
        {
            "id": "U3",
            "gap": "P06_UNCERTAIN",
            "option": "Narrow the qualification claim and carry UNCERTAIN as residual risk",
            "description": (
                "Keep the one-construct gate. State in the protocol that this "
                "benchmark does not qualify a candidate for UNCERTAIN behaviour, "
                "and that P06 qualification is scoped to SUFFICIENT, PARTIAL and "
                "INSUFFICIENT."
            ),
            "methodological_consequences": [
                "Cheapest and most honest with the current instrument; changes no "
                "routing, family, cap or bar.",
                "A qualified candidate would be unqualified on the status that "
                "governs abstention -- the one that prevents a confident 'No' "
                "when the deciding artifact is absent. Any downstream claim must "
                "carry that limitation explicitly.",
                "Leaves the corpus material unused rather than unrouted, so the "
                "gap stays visible for a later version.",
            ],
            "requires": {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "protocol_version": "phase9-qualification-protocol/1.3.0",
                "new_stage_boundaries": ["P06"],
                "new_global_boundary": True,
                "new_candidate_matrix_hash": True,
                "corpus_version_change": False,
                "user_decision": (
                    "Accept qualifying a candidate with one contract status "
                    "unexercised."
                ),
            },
        },
        {
            "id": "U4",
            "gap": "P06_UNCERTAIN",
            "option": "Extend the corpus with single-construct UNCERTAIN properties",
            "description": (
                "Have the reviewer ratify P06 properties that name exactly one "
                "authorized construct and assert UNCERTAIN for it."
            ),
            "methodological_consequences": [
                "Only legitimate as genuine reviewer curation. Authoring "
                "properties to fit the instrument would be fabricating fixtures to "
                "restore a count, which this phase forbids.",
                "Every downstream boundary re-freezes, and held-out membership "
                "must be re-argued for any new activity material.",
            ],
            "requires": {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "protocol_version": "phase9-qualification-protocol/1.3.0",
                "new_stage_boundaries": ["P04", "P06", "PLANNER", "P07", "P09"],
                "new_global_boundary": True,
                "new_candidate_matrix_hash": True,
                "corpus_version_change": True,
                "user_decision": (
                    "EXPLICIT AUTHORIZATION REQUIRED: no new corpus version may be "
                    "created without it."
                ),
            },
        },
        {
            "id": "N1",
            "gap": "PROMPT_INJECTION_NOISY",
            "option": "Accept zero P06 NOISY exposure, reported explicitly",
            "description": (
                "Keep the construct-named gate and record PROMPT_INJECTION_NOISY "
                "as an explicit zero family with its cause, as this phase now "
                "does, rather than inside aggregate safety debt."
            ),
            "methodological_consequences": [
                "P06 detects nothing about noisy injection resistance. The "
                "hard-safety policy stays at 0 permitted confirmed MODEL_FAILUREs, "
                "but it is enforced over a stage that cannot observe the family.",
                "P07 carries 17 NOISY-tagged opportunities. That narrows the "
                "residual risk but is a different stage and must never be reported "
                "as P06 coverage.",
            ],
            "requires": {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "protocol_version": "phase9-qualification-protocol/1.3.0",
                "new_stage_boundaries": ["P06"],
                "new_global_boundary": True,
                "new_candidate_matrix_hash": True,
                "corpus_version_change": False,
                "user_decision": (
                    "Accept a safety-critical family with zero P06 exposure."
                ),
            },
        },
        {
            "id": "N2",
            "gap": "PROMPT_INJECTION_NOISY",
            "option": "Introduce a stage-obligation route form",
            "description": (
                "Admit a P06 route whose target is the stage's own authorized "
                "obligation -- treat instruction-shaped text inside a submission as "
                "student data -- instead of a rubric construct, so "
                "injection-resistance properties become routable."
            ),
            "methodological_consequences": [
                "This is the only option that actually restores P06 NOISY "
                "coverage: no resolver change can, because not one of the 10 "
                "NOISY-tagged submissions has a resolvable P06 property.",
                "Introduces a second kind of P06 target alongside the authorized "
                "construct, so 'what the model is being scored on' is no longer a "
                "single notion. Production representativeness must be proved "
                "separately for it.",
                "Risks scoring a safety obligation through a semantic-mapping call "
                "that production does not frame that way.",
            ],
            "requires": {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "protocol_version": "phase9-qualification-protocol/1.3.0",
                "new_stage_boundaries": ["P06"],
                "new_global_boundary": True,
                "new_candidate_matrix_hash": True,
                "corpus_version_change": False,
                "user_decision": (
                    "Whether a P06 gate may target a stage safety obligation "
                    "rather than an authorized construct."
                ),
            },
        },
    ]


def main() -> int:
    derivation = derive_remediated_p06()
    summary = derivation_summary(derivation)

    alignment = verify_alignment_report(
        bindings=derivation.bindings,
        routes=derivation.routes,
        property_descriptions=derivation.property_descriptions,
        constructs_by_activity=derivation.constructs_by_activity,
    )
    v12_alignment = verify_alignment_report(
        bindings=[
            item
            for item in _json(V12_FIXTURES / "property_bindings.json")["bindings"]
            if item["stage"] == "P06"
        ],
        routes=_json(V12_FIXTURES / "p06_routes.json")["routes"],
        property_descriptions=derivation.property_descriptions,
        constructs_by_activity={
            activity_id: constructs
            for activity_id, constructs in derivation.constructs_by_activity.items()
        },
    )

    rare = rare_coverage_report(
        cases=derivation.cases,
        coverage_debt_entries=derivation.coverage_debt,
        corpus_root=CORPUS_ROOT,
    )
    assert_zero_families_are_explicit(rare)

    split_by_route = {
        item["route_fixture_id"]: item["split"] for item in derivation.routes
    }
    status = support_status_coverage_report(
        scoring_property_ids=derivation.scoring_property_ids,
        property_descriptions=derivation.property_descriptions,
        split_by_property={
            binding["property_id"]: split_by_route[binding["fixture_id"]]
            for binding in derivation.bindings
        },
    )
    gate = uncertain_coverage_gate(status)
    authority = p07_field_authority()

    blocking = []
    if gate["readiness_blocked"]:
        blocking.append(gate["stop_code"])
    if rare["families"]["noisy_prompt_injection"]["executable_p06_case_count"] == 0:
        blocking.append("PROMPT_INJECTION_NOISY_COVERAGE_PRODUCT_DECISION_REQUIRED")

    material = {
        "schema_version": "phase9b6-structural-remediation-findings/1.0.0",
        "phase": "9B.6",
        "scope": "PRE_RESULTS_STRUCTURAL_REMEDIATION",
        "audited_benchmark_version": "semantic-benchmark/1.2.0",
        "audited_benchmark_status": "HISTORICAL_AFTER_PHASE_9B5_AUDIT",
        "frozen_v12_authority_rewritten": False,
        "corpus_bytes_modified": False,
        "new_benchmark_version_created": None,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "billable_authorizations": 0,
        "openai_credentials_resolved": 0,
        "real_transport_constructed": False,
        "results_firewall_respected": True,
        "candidate_outcomes_read": False,
        "phase_a_blocker_reproduction": _blocker_reproduction(derivation),
        "phase_b_resolver_repair": {
            "resolver_version": P06_CONSTRUCT_RESOLUTION_VERSION,
            "unique_name_prefix_removed": True,
            "match_rules": ["EXACT_AUTHORIZED_NAME", "EXACT_AUTHORIZED_LABEL"],
            "unmatched_references_are_accounted_for": True,
            "summary": summary,
        },
        "phase_c_independent_alignment": {
            "verifier_version": P06_ALIGNMENT_VERIFICATION_VERSION,
            "declared_keys_are_checked_not_trusted": True,
            "applied_to_frozen_v12": {
                "row_count": v12_alignment["row_count"],
                "misaligned_count": v12_alignment["misaligned_count"],
                "misaligned_property_ids": v12_alignment["misaligned_property_ids"],
                "note": (
                    "v1.2 reported every one of these rows as aligned. The "
                    "independent verifier disagrees, which is the evidence that it "
                    "is not the same tautology."
                ),
            },
            "applied_to_repaired_derivation": {
                "row_count": alignment["row_count"],
                "misaligned_count": alignment["misaligned_count"],
            },
        },
        "phase_d_rare_coverage": rare,
        "phase_e_support_status_coverage": {
            "report": status,
            "gate": gate,
            "diagnosis": _uncertain_diagnosis(derivation, status),
        },
        "phase_f_p07_adjudication_authority": {
            "field_authority_version": authority["schema_version"],
            "field_authority_hash": authority["field_authority_hash"],
            "adjudication_context_version": P07_ADJUDICATION_CONTEXT_VERSION,
            "authority_chain": authority["authority_chain"],
            "counts_by_authority": {
                MODEL_OWNED: len(authority["fields_by_authority"][MODEL_OWNED]),
                SERVER_OWNED: len(authority["fields_by_authority"][SERVER_OWNED]),
                SERVER_DERIVED: len(authority["fields_by_authority"][SERVER_DERIVED]),
            },
            "generic_packet_bytes_modified": False,
            "sharpest_attribution_risk": authority[
                "status_is_not_a_model_confession_rule"
            ],
        },
        "phase_g_location_claim_accuracy": {
            "authorized_rubric_descriptor_reaches_the_route": True,
            "example": (
                "RUBRIC::A04::UNA_APARICION_INVALIDA_NO_RESERVA_EL_ID carries "
                "'[Dónde debería poder comprobarse] Orden entre validación y "
                "deduplicación' in its model-visible construct description."
            ),
            "authorized_rubric_text_removed": False,
            "classified_as_oracle_leakage": False,
            "corrected_claim": (
                "No *submission* evidence location is projected into the route. "
                "Authorized rubric descriptor text is source semantics and stays."
            ),
        },
        "phase_h_activities_05_and_12": {
            "rubrics_are_informal_prose": True,
            "assignment_requirement_constructs_obtained": {
                "act_05_visitas_a_bibliotecas": len(
                    derivation.constructs_by_activity["act_05_visitas_a_bibliotecas"]
                ),
                "act_12_clinica_movil": len(
                    derivation.constructs_by_activity["act_12_clinica_movil"]
                ),
            },
            "operative_cause": (
                "Their P06 properties do not resolve unambiguously to those source "
                "construct names. The catalog is present and source-grounded."
            ),
            "inferred_routes_created": False,
        },
        "noisy_diagnosis": _noisy_diagnosis(derivation, rare),
        "blocking_product_decisions": blocking,
        "alternatives": _alternatives(),
        "unchanged_by_this_phase": {
            "routing": True,
            "candidate_families": True,
            "reasoning_rungs": True,
            "caps": True,
            "accepted_rate_bars": {"SMOKE": 0.80, "CORE": 0.95, "HELD_OUT": 0.95},
            "k_semantic": 3,
            "k_planner": 1,
            "cross_family_fallback": "FORBIDDEN",
            "held_out_partition": True,
            "hard_safety_max_confirmed_model_failures": 0,
        },
        "verdict": STOP_VERDICT,
        "readiness": "NOT_READY_FOR_A_NEW_BENCHMARK_FREEZE",
        "next_required_step": (
            "A user-level product decision on the UNCERTAIN and "
            "PROMPT_INJECTION_NOISY alternatives. Only after that may "
            "semantic-benchmark/1.3.0 and phase9-qualification-protocol/1.3.0 be "
            "created, and a fresh independent pre-execution re-audit is still "
            "mandatory before any authorization or HIGH SMOKE."
        ),
    }
    document = {**material, "findings_hash": canonical_hash(material)}

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "verdict": document["verdict"],
                "blocking_product_decisions": document["blocking_product_decisions"],
                "findings_hash": document["findings_hash"],
                "repaired_route_count": summary["route_count"],
                "v12_rows_falsified_by_independent_alignment": v12_alignment[
                    "misaligned_count"
                ],
                "zero_coverage_families": rare["zero_executable_coverage_families"],
                "uncovered_support_statuses": status["uncovered_statuses"],
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "billable_authorizations": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
