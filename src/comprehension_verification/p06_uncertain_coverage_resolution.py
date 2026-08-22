"""What Phase 9B.7's accepted U3 decision does to the UNCERTAIN coverage gate.

``uncertain_coverage_gate`` in :mod:`.p06_support_status_coverage` answers one
question: does any candidate-scoring P06 property assert ``UNCERTAIN``?  It does
not, so the gate stops the readiness path with
``P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED``.  That was the correct
*active* state in Phase 9B.6, because every way of closing the gap -- admitting
a multi-construct route, adding a property, changing corpus bytes, or narrowing
the qualification claim -- is a product decision, and none had been made.

Phase 9B.7 made one.  ``U3`` was accepted: narrow the qualification claim and
carry ``UNCERTAIN`` as residual risk rather than manufacture coverage.  The gate
function is deliberately left untouched -- it is still the right answer to the
question it asks, it is bound into published 1.3.0/1.3.1/1.3.2 authority, and
Phase 9B.6's findings quote it.  What this module adds is the *second* question
the gate never asked:

    the coverage status is UNCOVERED -- what has been decided about that?

The two questions have separate answers and this module keeps them separate::

    UNCOVERED   is a fact about the instrument.  U3 does not change it.
    UNRESOLVED  is a fact about the product.     U3 changes exactly this.

So the disposition below carries the gate verbatim as *historical* evidence,
states that ``UNCERTAIN`` is still uncovered and still residual risk, and
releases only the readiness block -- and only while the accepted decision really
is ``U3`` and really is ``RESOLVED``.  Substitute ``U1``, ``U2`` or ``U4``, or
withdraw the decision, and the disposition fails closed back onto the original
stop code.  The bypass is bound to U3; it is not a general permission to
proceed past an uncovered status.

Nothing here executes a provider or an adjudicator, resolves a credential,
constructs a real transport, reads a candidate outcome or refreshes pricing.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_hash
from .p06_support_status_coverage import UNCERTAIN, uncertain_coverage_gate


P06_UNCERTAIN_COVERAGE_RESOLUTION_VERSION = "p06-uncertain-coverage-resolution/1.0.0"

#: The gap, named the same way the pre-decision gate named it.
UNCERTAIN_COVERAGE_DECISION_GAP = "P06_UNCERTAIN_SEMANTIC_COVERAGE"

#: The state the gap was in before Phase 9B.7, and the stop code that expressed
#: it.  Both are retained, and both are historical.
PRE_DECISION_STATUS = "PRODUCT_DECISION_REQUIRED"
PRE_U3_STOP_CODE = "P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED"

#: The accepted decision, its status and what it actually resolves.
ACCEPTED_UNCERTAIN_DECISION = "U3"
RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
U3_RESOLUTION = "NARROW_QUALIFICATION_CLAIM_AND_CARRY_RESIDUAL_RISK"

#: Where the decision lives.  The disposition binds the source, not a copy of
#: its conclusion, so a reader can check the decision rather than trust it.
PRODUCT_DECISION_SOURCE = "reports/semantic_benchmark/phase9b7/product_decision.json"

#: Every option the 9B.7 matrix offered for this gap.  They are enumerated so a
#: substituted decision is an explicit *rejection* rather than an unrecognised
#: value that could fall through to a permissive default.
UNCERTAIN_DECISION_OPTIONS: tuple[str, ...] = ("U1", "U2", "U3", "U4")

#: What each non-accepted option would have required.  None of it was done, so
#: none of it may inherit U3's readiness disposition.
NON_ACCEPTED_OPTION_REQUIREMENTS: Mapping[str, str] = {
    "U1": (
        "construct-set route form -- a scoring unit would stop being one "
        "authorized construct and the accepted-rate denominator would change "
        "meaning. Neither was done."
    ),
    "U2": (
        "artifact-absence route form -- target selection would become a "
        "function of which authorized artifact is absent. Not done."
    ),
    "U4": (
        "extend the corpus with single-construct UNCERTAIN properties -- new "
        "routes would enter the denominator and explicit user authorization "
        "would be required for a new corpus version. Not done."
    ),
}


class UncertainCoverageResolutionError(ValueError):
    """Raised when the UNCERTAIN readiness disposition cannot be established."""


def _sha256_file(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def accepted_uncertain_product_decision(
    repository_root: Path, *, source: str = PRODUCT_DECISION_SOURCE
) -> dict[str, Any]:
    """Read Phase 9B.7's decision and prove it is the one U3 authority needs.

    The decision is *read*, never assumed.  If the published document stops
    saying ``U3``, or stops being the accepted 9B.7 verdict, this raises rather
    than letting 1.3.3 keep asserting a resolution nobody made.
    """

    path = repository_root / source
    if not path.exists():
        raise UncertainCoverageResolutionError(
            f"the Phase 9B.7 product decision is missing at {source}; the "
            "UNCERTAIN readiness disposition has no authority to resolve it"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    decision = document.get("uncertain_recommendation")
    if decision != ACCEPTED_UNCERTAIN_DECISION:
        raise UncertainCoverageResolutionError(
            f"{source} records {decision!r} for the UNCERTAIN gap, not "
            f"{ACCEPTED_UNCERTAIN_DECISION!r}"
        )
    return {
        "source": source,
        "phase": document["phase"],
        "schema_version": document["schema_version"],
        "verdict": document["verdict"],
        "decision": decision,
        "noisy_decision": document["noisy_decision"],
        "decision_hash": document["decision_hash"],
        "source_file_sha256": _sha256_file(path),
        "provider_calls": document["provider_calls"],
        "adjudicator_calls": document["adjudicator_calls"],
        "candidate_outcomes_read": document["candidate_outcomes_read"],
        "corpus_bytes_modified": document["corpus_bytes_modified"],
    }


def historical_pre_u3_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    """The pre-decision gate result, retained and labelled as history.

    The gate itself is not re-implemented or re-worded here.  It is called, and
    its verbatim result is wrapped in metadata saying when it was the active
    state, what it caused, and what supersedes it.
    """

    gate = uncertain_coverage_gate(report)
    return {
        "record_kind": "HISTORICAL_PRE_DECISION_EVIDENCE",
        "is_the_active_state": False,
        "was_the_active_state_in_phase": "9B.6",
        "active_until": "Phase 9B.7 accepted U3",
        "triggered": "PHASE_9B7_UNCERTAIN_PRODUCT_DECISION",
        "superseded_for_readiness_by": ACCEPTED_UNCERTAIN_DECISION,
        "superseded_by_phase": "9B.7",
        "correct_when_published": True,
        "why_retained": (
            "The stop that produced a product decision is the evidence that the "
            "decision was made deliberately rather than assumed. Deleting it "
            "would leave U3 looking like a default."
        ),
        "why_it_is_not_active": (
            "The gate stops the readiness path *until* a product decision is "
            "made. One was made, so its stop condition is discharged. Nothing "
            "about the coverage fact it reports changed."
        ),
        "gate_result_verbatim": gate,
        "readiness_blocked": gate["readiness_blocked"],
        "stop_code": gate["stop_code"],
    }


def uncertain_coverage_disposition(
    report: Mapping[str, Any],
    *,
    product_decision: str,
    product_decision_status: str,
    product_decision_source: str = PRODUCT_DECISION_SOURCE,
    product_decision_hash: str | None = None,
    product_decision_source_file_sha256: str | None = None,
) -> dict[str, Any]:
    """State what is decided about the uncovered UNCERTAIN status.

    The coverage fact is never rewritten: ``UNCOVERED`` stays ``UNCOVERED``, the
    candidate-scoring property count stays zero, ``UNCERTAIN`` stays unqualified
    and stays residual risk, and the production contract keeps it.  What the
    accepted decision releases is the *readiness block*, and only that.

    The release is conditional and derived, not declared.  It holds when the
    accepted decision is ``U3`` and its status is ``RESOLVED``.  Any other
    decision, any other status, or no decision at all, and the disposition
    reproduces the original stop code as the active state.
    """

    gate = uncertain_coverage_gate(report)
    uncertain = report["statuses"][UNCERTAIN]
    covered = bool(uncertain["covered"])
    coverage_status = "COVERED" if covered else "UNCOVERED"

    decision_accepted = product_decision == ACCEPTED_UNCERTAIN_DECISION
    status_resolved = product_decision_status == RESOLVED
    resolved = decision_accepted and status_resolved

    # A decision may only release the block it was actually made about.  If the
    # gap were covered there would be nothing to resolve; if it is uncovered and
    # unresolved, the pre-decision stop is still the active state.
    readiness_blocked = gate["readiness_blocked"] and not resolved
    unresolved_reasons: list[str] = []
    if not decision_accepted:
        unresolved_reasons.append(
            f"the recorded product decision is {product_decision!r}, and only "
            f"{ACCEPTED_UNCERTAIN_DECISION!r} carries this readiness "
            "disposition"
        )
    if not status_resolved:
        unresolved_reasons.append(
            f"the recorded decision status is {product_decision_status!r}, not "
            f"{RESOLVED!r}"
        )

    material: dict[str, Any] = {
        "schema_version": P06_UNCERTAIN_COVERAGE_RESOLUTION_VERSION,
        "record_kind": "ACTIVE_POST_DECISION_DISPOSITION",
        "decision_gap": UNCERTAIN_COVERAGE_DECISION_GAP,
        # --- PART A: the coverage fact, unchanged and not dressed up
        "coverage_status": coverage_status,
        "candidate_scoring_property_count": uncertain[
            "candidate_scoring_property_count"
        ],
        "uncertain_qualification_claimed": False,
        "uncertain_removed_from_production_contract": False,
        "residual_risk": True,
        "semantic_routes_added": 0,
        "semantic_properties_added": 0,
        "corpus_bytes_modified": False,
        # --- PART B: the product-decision state
        "pre_decision_status": PRE_DECISION_STATUS,
        "product_decision": product_decision,
        "product_decision_source": product_decision_source,
        "product_decision_status": product_decision_status if resolved else UNRESOLVED,
        "resolution": U3_RESOLUTION if resolved else None,
        "requires_product_decision": not resolved,
        "blocks_phase9_qualification": readiness_blocked,
        "blocks_candidate_rung_selection": readiness_blocked,
        "blocks_full_p06_contract_coverage_claim": True,
        "uncertain_remains_unqualified": True,
        "readiness_blocked": readiness_blocked,
        "active_stop_code": PRE_U3_STOP_CODE if readiness_blocked else None,
        # --- the distinction the whole artifact exists to make
        "uncovered_is_not_unresolved": (
            "UNCOVERED is a fact about the instrument: no candidate-scoring P06 "
            "property asserts UNCERTAIN, so a qualification run cannot observe "
            "that behaviour. UNRESOLVED was a fact about the product: nobody had "
            "decided what to do about it. U3 decides what to do. It does not, "
            "and must not, make the status covered."
        ),
        "what_u3_resolves": (
            "the question of what to do about zero UNCERTAIN semantic coverage"
        ),
        "what_u3_does_not_resolve": (
            "the coverage itself. UNCERTAIN stays unexercised, unqualified and "
            "an explicit residual risk."
        ),
        "may_be_closed_by_the_instrument": False,
        "accepted_decision_options": list(UNCERTAIN_DECISION_OPTIONS),
        "non_accepted_option_requirements": dict(
            sorted(NON_ACCEPTED_OPTION_REQUIREMENTS.items())
        ),
        "readiness_disposition_is_bound_to": ACCEPTED_UNCERTAIN_DECISION,
        "readiness_disposition_is_generic": False,
        "fail_closed_rule": (
            "This disposition releases the readiness block only while the "
            "recorded decision is U3 and its status is RESOLVED. Withdraw the "
            "decision or substitute U1, U2 or U4 and zero UNCERTAIN coverage "
            "blocks readiness again under the original stop code."
        ),
        "unresolved_reasons": unresolved_reasons,
        # --- PART C: the pre-U3 gate, retained as history
        "pre_u3_uncertain_coverage_gate": historical_pre_u3_gate(report),
    }
    if product_decision_hash is not None:
        material["product_decision_hash"] = product_decision_hash
    if product_decision_source_file_sha256 is not None:
        material["product_decision_source_file_sha256"] = (
            product_decision_source_file_sha256
        )

    # Fail closed on the invariants this artifact exists to guarantee, so a
    # future edit cannot quietly turn it into a coverage claim.
    if material["coverage_status"] != "UNCOVERED":
        raise UncertainCoverageResolutionError(
            "the UNCERTAIN status became covered; U3 narrows a claim and adds no "
            "coverage, so this disposition no longer describes the instrument"
        )
    if material["candidate_scoring_property_count"] != 0:
        raise UncertainCoverageResolutionError(
            "UNCERTAIN carries candidate-scoring properties; the U3 disposition "
            "may not be published over a changed instrument"
        )
    if resolved and material["blocks_full_p06_contract_coverage_claim"] is not True:
        raise UncertainCoverageResolutionError(
            "resolving the product decision may not release the full-contract "
            "coverage claim block"
        )
    if not resolved and material["active_stop_code"] != PRE_U3_STOP_CODE:
        raise UncertainCoverageResolutionError(
            "an unresolved UNCERTAIN gap must reproduce the pre-decision stop "
            "code as the active state"
        )
    return {**material, "disposition_hash": canonical_hash(material)}
