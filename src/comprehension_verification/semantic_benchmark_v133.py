"""``semantic-benchmark/1.3.3`` -- resolve the pre-U3 readiness gate.

``semantic-benchmark/1.3.2`` is not edited.  It is marked
``SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED`` and its bytes
stay as published; no provider or adjudicator ever ran against any 1.3.x
candidate, so this is an authority-binding repair rather than result-driven
tuning.

The defect is a *state* left behind, not a wording slip.  1.3.2 says the right
things about coverage -- ``SUFFICIENT`` / ``PARTIAL`` / ``INSUFFICIENT``
qualified, ``UNCERTAIN`` excluded and still residual risk, Phase 9 alone not
full contract coverage -- but its active claim still embeds the pre-decision
gate verbatim::

    uncertain_coverage_gate.readiness_blocked = true
    uncertain_coverage_gate.stop_code =
        P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED

``uncertain_coverage_gate()`` defines that state as stopping the readiness path
until a product decision is made.  That was exactly right in Phase 9B.6.  Phase
9B.7 then made the decision -- ``U3``: narrow the qualification claim and carry
``UNCERTAIN`` as residual risk -- so an *active* 1.3.2 field is now demanding a
decision that exists.

1.3.3 resolves the state and changes nothing else.  It does not pretend
``UNCERTAIN`` is covered: the status stays ``UNCOVERED``, the candidate-scoring
property count stays zero, the production contract keeps ``UNCERTAIN``, and the
residual risk stays declared.  What moves is the *disposition*: the gap is
resolved by U3, so it no longer blocks readiness -- and it still blocks any
claim of full P06 contract coverage.

    UNCOVERED  is a fact about the instrument.  U3 does not change it.
    UNRESOLVED was a fact about the product.    U3 changes exactly this.

The release is bound to U3 rather than granted generally: withdraw the decision
or substitute U1, U2 or U4 and zero UNCERTAIN coverage blocks readiness again
under the original stop code.  ``uncertain_coverage_gate()`` itself is left
untouched -- it is still the right answer to the question it asks, it is bound
into published 1.3.0/1.3.1/1.3.2 authority, and Phase 9B.6 quotes it.

The semantic scoring set, routes, denominators, thresholds, bars, the N3
provider fixtures and their hashes, the N3 axis and the call budget are all
carried forward and each one is *proved* unchanged rather than assumed.

Nothing here executes a provider or an adjudicator, resolves a credential,
constructs a real transport, reads a candidate outcome or refreshes pricing.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .canonical import canonical_hash
from .p06_support_status_coverage import (
    CONTRACT_SUPPORT_STATUSES,
    P06_SUPPORT_STATUS_COVERAGE_VERSION,
    P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
    UNCERTAIN,
)
from .p06_uncertain_coverage_resolution import (
    ACCEPTED_UNCERTAIN_DECISION,
    PRE_DECISION_STATUS,
    PRE_U3_STOP_CODE,
    PRODUCT_DECISION_SOURCE,
    RESOLVED,
    U3_RESOLUTION,
    UNCERTAIN_COVERAGE_DECISION_GAP,
    accepted_uncertain_product_decision,
    uncertain_coverage_disposition,
)
from .semantic_benchmark import ACTIVE_BENCHMARK_STAGES, DEFAULT_CORPUS_ROOT
from .semantic_benchmark_v13 import (
    QUALIFIED_SUPPORT_STATUSES,
    REPOSITORY_ROOT,
    V13Build,
    V13BuildError,
    build_v13,
)
from .semantic_benchmark_v131 import HashManifestError
from .semantic_benchmark_v132 import (
    FROZEN_N3_FIXTURE_SET_HASH,
    SEMANTIC_BENCHMARK_V132_VERSION,
    U3_LIMITATIONS_V132,
    V131_STATUS,
)


SEMANTIC_BENCHMARK_V133_VERSION = "semantic-benchmark/1.3.3"
BENCHMARK_BOUNDARY_FORMAT_V133 = "semantic-benchmark-boundary/1.3.3"
PROTOCOL_VERSION_V133 = "phase9-qualification-protocol/1.3.3"
CANDIDATE_MATRIX_VERSION_V133 = "phase9-candidate-matrix/1.3.3"
CLAIM_VERSION_V133 = "p06-semantic-qualification-claim/1.3.3"
DISPOSITION_VERSION_V133 = "p06-uncertain-coverage-disposition/1.3.3"

V132_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_2"
V132_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_2"
DEFINITION_ROOT = "evaluation/semantic_benchmark/v1_3_3"
REPORT_ROOT = "reports/semantic_benchmark/v1_3_3"

V132_STATUS = "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
V133_STATUS = "PREEXECUTION_FREEZE_CANDIDATE"

#: The claim text, worded for the version it actually applies to.  1.3.2 fixed
#: the version binding; 1.3.3 keeps it and moves only the disposition.
SEMANTIC_QUALIFICATION_CLAIM_V133 = (
    f"{SEMANTIC_BENCHMARK_V133_VERSION} qualifies P06 candidate behaviour on the "
    "support statuses SUFFICIENT, PARTIAL and INSUFFICIENT."
)

#: The four limitations, likewise.  Their *meaning* is pinned to 1.3.2 by a
#: regression: only the version each sentence names may differ.
U3_LIMITATIONS_V133: tuple[str, ...] = (
    f"{SEMANTIC_BENCHMARK_V133_VERSION} does NOT qualify P06 UNCERTAIN behaviour.",
    "P06 model-selection claims are limited to SUFFICIENT / PARTIAL / INSUFFICIENT.",
    "UNCERTAIN remains an explicit residual risk.",
    "Phase 9 alone does not establish full P06 contract coverage.",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def build_v133(corpus_root: Path = DEFAULT_CORPUS_ROOT) -> V13Build:
    """1.3.3 reuses the 1.3.0/1.3.1/1.3.2 semantic instrument unchanged."""

    return build_v13(corpus_root)


# --------------------------------------------------------------------------
# PART B -- the resolved post-decision disposition
# --------------------------------------------------------------------------


def u3_uncertain_disposition(build: V13Build) -> dict[str, Any]:
    """Publish the active disposition of the UNCERTAIN coverage gap.

    The accepted decision is *read* from the Phase 9B.7 package rather than
    hard-coded into the conclusion, and the disposition is derived from it.  If
    that document stops recording U3, the load raises; if the decision or its
    status is anything but ``U3`` / ``RESOLVED``, the disposition fails closed
    onto the pre-decision stop code instead of quietly proceeding.
    """

    decision = accepted_uncertain_product_decision(REPOSITORY_ROOT)
    disposition = uncertain_coverage_disposition(
        build.support_status_coverage,
        product_decision=decision["decision"],
        product_decision_status=RESOLVED,
        product_decision_source=decision["source"],
        product_decision_hash=decision["decision_hash"],
        product_decision_source_file_sha256=decision["source_file_sha256"],
    )
    material = {
        **disposition,
        "schema_version": DISPOSITION_VERSION_V133,
        "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "resolution_engine_version": disposition["schema_version"],
        "product_decision_authority": decision,
        "supersedes_disposition_in": SEMANTIC_BENCHMARK_V132_VERSION,
        "what_changed_from_v132": (
            "1.3.2 carried the pre-decision gate as its active state, so an "
            "active field still demanded a product decision that Phase 9B.7 had "
            "already made. 1.3.3 publishes the post-decision disposition and "
            "retains that gate as explicitly historical evidence."
        ),
        "what_did_not_change_from_v132": [
            "the coverage status: UNCERTAIN is UNCOVERED in both",
            "the candidate-scoring property count for UNCERTAIN: zero in both",
            "the production contract: UNCERTAIN remains a member in both",
            "the residual-risk declaration",
            "every semantic route, property, split, threshold and bar",
        ],
    }
    material.pop("disposition_hash", None)
    disposition_hash = canonical_hash(material)

    # Fail closed on the active semantics PART B requires, so a later edit
    # cannot weaken them without this build refusing to publish.
    required = {
        "requires_product_decision": False,
        "blocks_phase9_qualification": False,
        "blocks_candidate_rung_selection": False,
        "blocks_full_p06_contract_coverage_claim": True,
        "uncertain_remains_unqualified": True,
        "readiness_blocked": False,
        "active_stop_code": None,
        "coverage_status": "UNCOVERED",
        "candidate_scoring_property_count": 0,
        "uncertain_qualification_claimed": False,
        "uncertain_removed_from_production_contract": False,
        "residual_risk": True,
        "product_decision": ACCEPTED_UNCERTAIN_DECISION,
        "product_decision_status": RESOLVED,
        "resolution": U3_RESOLUTION,
        "decision_gap": UNCERTAIN_COVERAGE_DECISION_GAP,
        "pre_decision_status": PRE_DECISION_STATUS,
    }
    wrong = {
        key: material[key]
        for key, value in required.items()
        if material[key] != value
    }
    if wrong:
        raise V13BuildError(
            f"the active U3 disposition does not carry its required semantics: {wrong}"
        )
    history = material["pre_u3_uncertain_coverage_gate"]
    if history["is_the_active_state"] is not False:
        raise V13BuildError("the pre-U3 gate may only be retained as history")
    if history["stop_code"] != PRE_U3_STOP_CODE:
        raise V13BuildError(
            "the historical record must retain the pre-U3 stop code verbatim"
        )
    return {**material, "disposition_hash": disposition_hash}


# --------------------------------------------------------------------------
# PART A + D -- the claim, with the gap resolved and the coverage fact intact
# --------------------------------------------------------------------------


def semantic_qualification_claim_v133(
    build: V13Build, disposition: Mapping[str, Any]
) -> dict[str, Any]:
    """State what the active benchmark claims, and what is decided about the gap.

    The exclusion stays derived rather than declared: a status is listed as
    qualified only when the frozen instrument actually carries candidate-scoring
    properties asserting it.  What changes from 1.3.2 is that the claim now
    carries a *resolved* disposition where it used to carry an open gate.
    """

    coverage = build.support_status_coverage
    counts = {
        status: coverage["statuses"][status]["candidate_scoring_property_count"]
        for status in CONTRACT_SUPPORT_STATUSES
    }
    qualified = tuple(
        status for status in CONTRACT_SUPPORT_STATUSES if counts[status] > 0
    )
    excluded = tuple(
        status for status in CONTRACT_SUPPORT_STATUSES if counts[status] == 0
    )
    if qualified != QUALIFIED_SUPPORT_STATUSES:
        raise V13BuildError(
            f"the derived qualified support-status set {qualified} does not "
            f"match the accepted U3 claim {QUALIFIED_SUPPORT_STATUSES}"
        )
    if excluded != (UNCERTAIN,):
        raise V13BuildError(
            f"U3 excludes exactly UNCERTAIN from the claim; derived: {excluded}"
        )
    if disposition["candidate_scoring_property_count"] != 0:
        raise V13BuildError(
            "UNCERTAIN is claimed unqualified but the instrument carries "
            f"{disposition['candidate_scoring_property_count']} scoring properties"
        )

    # The 1.3.2 claim, quoted so the semantics comparison is evidence rather
    # than an assertion.  Only the version-naming sentences may differ.
    v132_claim = _json(V132_DEFINITION_ROOT / "phase9/semantic_qualification_claim.json")
    semantics_unchanged = (
        list(v132_claim["qualified_support_statuses"]) == list(qualified)
        and list(v132_claim["excluded_support_statuses"]) == list(excluded)
        and v132_claim["uncertain_qualification_claimed"] is False
        and v132_claim["uncertain_removed_from_production_contract"] is False
        and v132_claim["phase9_alone_is_full_p06_contract_coverage"] is False
        and list(v132_claim["limitations"])[1:] == list(U3_LIMITATIONS_V133)[1:]
        and v132_claim["uncertain_coverage_gate"]["covered"] is False
        and v132_claim["uncertain_coverage_gate"]["candidate_scoring_property_count"]
        == 0
    )
    if not semantics_unchanged:
        raise V13BuildError(
            "1.3.3 may only resolve the product-decision state; the qualification "
            "semantics differ from 1.3.2, which would be a product-decision change"
        )

    material = {
        "schema_version": CLAIM_VERSION_V133,
        # --- applicability, stated rather than inferred
        "applicable_benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "supersedes_claim_binding_from": SEMANTIC_BENCHMARK_V132_VERSION,
        "claim_semantics_changed_from_v132": False,
        "what_changed": (
            "The claim now carries a resolved disposition of the UNCERTAIN "
            "coverage gap instead of the open pre-decision gate. Nothing about "
            "which behaviour is qualified changed, and UNCERTAIN is no more "
            "covered than it was."
        ),
        "why_a_new_hash": (
            "The claim's active disposition of the UNCERTAIN gap changed from "
            "PRODUCT_DECISION_REQUIRED to RESOLVED-by-U3, and the claim text "
            "names the version it applies to, so its material hash must change."
        ),
        "reader_must_not_infer_applicability_from_lineage": True,
        # --- the claim itself
        "accepted_decision": ACCEPTED_UNCERTAIN_DECISION,
        "decision_source": PRODUCT_DECISION_SOURCE,
        "claim": SEMANTIC_QUALIFICATION_CLAIM_V133,
        "qualified_support_statuses": list(qualified),
        "excluded_support_statuses": list(excluded),
        "candidate_scoring_property_count_by_status": dict(sorted(counts.items())),
        "uncertain_qualification_claimed": False,
        "uncertain_scoring_property_count": counts[UNCERTAIN],
        "uncertain_scope_census_version": P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
        "uncertain_scope_census_hash": build.uncertain_census["census_hash"],
        "support_status_coverage_version": P06_SUPPORT_STATUS_COVERAGE_VERSION,
        "support_status_coverage_hash": coverage["report_hash"],
        # --- PART A + B: the coverage fact and the decision about it
        "uncertain_coverage_status": disposition["coverage_status"],
        "uncertain_coverage_disposition_version": disposition["schema_version"],
        "uncertain_coverage_disposition_hash": disposition["disposition_hash"],
        "uncertain_coverage_decision_gap": disposition["decision_gap"],
        "uncertain_coverage_product_decision": disposition["product_decision"],
        "uncertain_coverage_product_decision_status": disposition[
            "product_decision_status"
        ],
        "uncertain_coverage_resolution": disposition["resolution"],
        "uncertain_coverage_requires_product_decision": disposition[
            "requires_product_decision"
        ],
        "uncertain_coverage_blocks_phase9_qualification": disposition[
            "blocks_phase9_qualification"
        ],
        "uncertain_coverage_blocks_full_p06_contract_coverage_claim": disposition[
            "blocks_full_p06_contract_coverage_claim"
        ],
        "uncertain_remains_unqualified": disposition["uncertain_remains_unqualified"],
        "uncovered_is_not_unresolved": disposition["uncovered_is_not_unresolved"],
        "limitations": list(U3_LIMITATIONS_V133),
        "limitation_count": len(U3_LIMITATIONS_V133),
        "production_contract_unchanged": True,
        "uncertain_removed_from_production_contract": False,
        "production_contract_note": (
            "UNCERTAIN remains a first-class member of the P06 support-status "
            "contract. 1.3.3 changes no production prompt, DTO, materializer or "
            "planner semantics. What it declares is the limit of its own "
            "qualification evidence, and what has been decided about that limit."
        ),
        "phase9_alone_is_full_p06_contract_coverage": False,
        # --- historical lineage, explicitly labelled as history
        "historical_claim_lineage": [
            {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "status": "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED",
                "claim_named_version": "semantic-benchmark/1.3.0",
                "uncertain_gap_state": PRE_DECISION_STATUS,
                "correct_when_published": True,
            },
            {
                "benchmark_version": "semantic-benchmark/1.3.1",
                "status": V131_STATUS,
                "claim_named_version": "semantic-benchmark/1.3.0",
                "uncertain_gap_state": PRE_DECISION_STATUS,
                "correct_when_published": False,
                "defect": (
                    "The claim was carried forward verbatim, so an active "
                    "version published a current claim naming a superseded one."
                ),
            },
            {
                "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
                "status": V132_STATUS,
                "claim_named_version": SEMANTIC_BENCHMARK_V132_VERSION,
                "uncertain_gap_state": PRE_DECISION_STATUS,
                "correct_when_published": False,
                "defect": (
                    "The version binding was repaired but the pre-decision "
                    "coverage gate stayed the active state, so an active field "
                    "still required a product decision Phase 9B.7 had made."
                ),
            },
        ],
        "originating_product_decision": {
            "decision": ACCEPTED_UNCERTAIN_DECISION,
            "phase": "9B.7",
            "accepted": True,
            "unchanged_by_this_repair": True,
            "reopened_by_this_repair": False,
        },
    }
    return {**material, "claim_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART G -- the proofs that no N3 or semantic material moved
# --------------------------------------------------------------------------


def n3_fixture_equality_proof_v133(fixtures: Mapping[str, Any]) -> dict[str, Any]:
    """Prove every N3 provider fixture byte is unchanged from 1.3.2.

    Not "the set hash matches" alone: the published 1.3.2 document is compared
    field by field with the freshly derived one, so a change that happened to
    preserve the aggregate would still be caught, and the per-fixture request
    hashes are compared individually.
    """

    published = _json(V132_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json")

    if fixtures["fixture_set_hash"] != FROZEN_N3_FIXTURE_SET_HASH:
        raise V13BuildError(
            "the N3 provider fixture set moved: "
            f"{fixtures['fixture_set_hash']} != {FROZEN_N3_FIXTURE_SET_HASH}"
        )
    if canonical_hash(fixtures) != canonical_hash(published):
        raise V13BuildError(
            "the derived N3 fixture authority differs from the 1.3.2 published bytes"
        )

    by_id = {item["n3_provider_fixture_id"]: item for item in fixtures["fixtures"]}
    published_by_id = {
        item["n3_provider_fixture_id"]: item for item in published["fixtures"]
    }
    if sorted(by_id) != sorted(published_by_id):
        raise V13BuildError("the N3 fixture identifiers changed")

    rows = []
    for fixture_id in sorted(by_id):
        current, previous = by_id[fixture_id], published_by_id[fixture_id]
        differing = sorted(
            key
            for key in set(current) | set(previous)
            if current.get(key) != previous.get(key)
        )
        if differing:
            raise V13BuildError(f"{fixture_id} changed in fields {differing}")
        rows.append(
            {
                "n3_provider_fixture_id": fixture_id,
                "n3_split": current["n3_split"],
                "target_construct_key": current["target_construct_key"],
                "provider_request_hash": current["provider_request_hash"],
                "alias_envelope_hash": current["alias_envelope_hash"],
                "identical_to_v132": True,
            }
        )

    material = {
        "schema_version": "n3-fixture-equality-proof/1.3.3",
        "from_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "method": (
            "Compare the derived fixture authority with the published 1.3.2 "
            "document field by field, then compare every per-fixture request "
            "hash individually. The aggregate hash alone is not the proof."
        ),
        "fixture_set_hash": fixtures["fixture_set_hash"],
        "fixture_set_hash_unchanged": True,
        "fixture_count": len(rows),
        "fixtures_identical_to_v132": True,
        "construct_selections_unchanged": True,
        "per_fixture": rows,
        "counts_by_n3_split": dict(fixtures["counts_by_n3_split"]),
        "split_sequencing_unchanged": (
            fixtures["safety_smoke_fixture_count"] == 1
            and fixtures["core_fixture_count"] == 6
            and fixtures["held_out_fixture_count"] == 3
        ),
        "provider_calls": 0,
        "adjudicator_calls": 0,
    }
    if not material["split_sequencing_unchanged"]:
        raise V13BuildError("the accepted N3 1/6/3 split sequencing moved")
    return {**material, "proof_hash": canonical_hash(material)}


#: The semantic material PART G requires to be provably identical to 1.3.2.
#: Each row is (label, how it is read from the 1.3.2 P06 boundary).
_P06_BOUNDARY_INVARIANTS: tuple[str, ...] = (
    "candidate_scoring_set_hash",
    "route_definitions_hash",
    "case_definitions_hash",
    "property_bindings_hash",
    "split_assignments_hash",
    "construct_catalog_hash",
    "coverage_debt_hash",
    "fixture_input_hashes_hash",
    "p06_instrument_hash",
    "support_status_coverage_hash",
    "n3_axis_hash",
    "n3_exposure_population_hash",
    "n3_provider_fixture_set_hash",
    "n3_contractual_policy_authority_hash",
    "n3_safety_smoke_selector_hash",
    "n3_violation_classes_hash",
    "corpus_package_boundary_hash",
    "field_authority_hash",
)


def semantic_invariant_equality_proof(
    build: V13Build,
    fixtures: Mapping[str, Any],
    *,
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    qualification_protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove, component by component, that no semantic material moved.

    PART G lists what must be identical to 1.3.2.  Every row below is derived
    from 1.3.3 authority and compared with the published 1.3.2 value; a row that
    differs raises rather than being reported as a difference, because 1.3.3 has
    no licence to move any of it.
    """

    from .semantic_benchmark_v13_boundary import (
        split_partition_authority_v13,
        threshold_report_v13,
    )

    v132_boundary = _json(V132_REPORT_ROOT / "stage_boundaries.json")["stages"]["P06"]
    v132_protocol = _json(V132_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    v132_matrix = _json(V132_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    v132_budget = _json(V132_REPORT_ROOT / "phase9/call_budget.json")

    from .semantic_benchmark_v131 import p06_stage_boundary_v131
    n3_axis = _json(V132_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json")
    derived_boundary = p06_stage_boundary_v131(build, n3_axis, fixtures)

    rows: list[dict[str, Any]] = []

    def _row(name: str, derived: Any, published: Any, note: str) -> None:
        rows.append(
            {
                "invariant": name,
                "derived_from_v133_authority": derived,
                "published_in_v132": published,
                "identical": derived == published,
                "note": note,
            }
        )

    for key in _P06_BOUNDARY_INVARIANTS:
        _row(
            key,
            derived_boundary[key],
            v132_boundary[key],
            "reconstructed from 1.3.3 authority and compared with the published "
            "1.3.2 P06 boundary",
        )

    scoring = list(build.derivation.scoring_property_ids)
    _row(
        "candidate_scoring_property_count",
        len(scoring),
        69,
        "the 69 candidate-scoring P06 properties, counted rather than declared",
    )

    thresholds = {
        row["split"]: row["applicable_property_count"]
        for row in threshold_report_v13(build)["p06_thresholds"]
    }
    _row(
        "p06_applicable_property_count_by_split",
        thresholds,
        {"CORE": 41, "HELD_OUT_CONFIRMATION": 27, "SMOKE": 1},
        "the semantic denominators behind the accepted-rate bars",
    )
    _row(
        "semantic_gates",
        qualification_protocol["semantic_gates"],
        v132_protocol["semantic_gates"],
        "the 0.80 SMOKE / 0.95 CORE / 0.95 HELD_OUT bars and the zero "
        "hard-safety allowance",
    )
    _row(
        "n3_gates",
        qualification_protocol["n3_gates"],
        v132_protocol["n3_gates"],
        "the N3 contractual hard-safety promotion gates",
    )
    _row(
        "ordering",
        qualification_protocol["ordering"],
        v132_protocol["ordering"],
        "the pre-registered execution ordering",
    )
    _row(
        "adjudication_protocol_hash",
        qualification_protocol["adjudication_protocol_hash"],
        v132_protocol["adjudication_protocol_hash"],
        "the semantic adjudication decision semantics",
    )
    _row(
        "candidate_identities",
        canonical_hash(candidate_matrix["candidates"]),
        canonical_hash(v132_matrix["candidates"]),
        "candidate identities, rungs and families",
    )
    _row(
        "call_budget_hash",
        call_budget["call_budget_hash"],
        v132_budget["call_budget_hash"],
        "provider, semantic-adjudicator and N3-adjudicator call counts",
    )
    _row(
        "n3_counts_by_split",
        dict(fixtures["counts_by_n3_split"]),
        dict(
            _json(V132_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json")[
                "counts_by_n3_split"
            ]
        ),
        "the accepted N3 1/6/3 split sequencing",
    )
    splits = split_partition_authority_v13(build)
    _row(
        "split_partition_hash",
        splits["split_partition_hash"],
        _json(V132_REPORT_ROOT / "phase9/pre_results_instrument_freeze.json")[
            "split_partition_hash"
        ],
        "semantic split assignments and the held-out partition",
    )

    moved = sorted(row["invariant"] for row in rows if not row["identical"])
    if moved:
        raise V13BuildError(
            f"1.3.3 moved semantic or N3 material it may not touch: {moved}"
        )

    material = {
        "schema_version": "semantic-invariant-equality-proof/1.3.3",
        "from_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "method": (
            "Each invariant is reconstructed from 1.3.3 authority and compared "
            "with the value 1.3.2 published. A difference raises; nothing here "
            "is reported as an acceptable delta."
        ),
        "invariants": rows,
        "invariant_count": len(rows),
        "all_identical": True,
        "moved_invariants": [],
        "thresholds": {
            "SMOKE_min_accepted_rate": 0.80,
            "CORE_min_accepted_rate": 0.95,
            "HELD_OUT_CONFIRMATION_min_accepted_rate": 0.95,
        },
        "semantic_routes_added": 0,
        "semantic_properties_added": 0,
        "construct_selection_changed": False,
        "threshold_rung_or_family_changed": False,
        "corpus_bytes_modified": False,
        "provider_calls": 0,
        "adjudicator_calls": 0,
    }
    return {**material, "proof_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART F -- boundaries
# --------------------------------------------------------------------------


def p06_stage_boundary_v133(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
) -> dict[str, Any]:
    """The 1.3.2 P06 boundary re-bound to the resolved claim and disposition."""

    v132 = _json(V132_REPORT_ROOT / "stage_boundaries.json")
    material = {
        key: value
        for key, value in v132["stages"]["P06"].items()
        if key
        not in {
            "stage_boundary_hash",
            "n3_provider_authority_inventory",
            "n3_provider_authority_fully_bound",
            "supersedes_v131_p06_boundary",
            "n3_provider_fixture_set_hash_unchanged_from_v131",
        }
    }
    material.update(
        {
            "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "boundary_status": "NEW_IN_V133",
            "new_because": (
                "The active semantic qualification claim and the disposition of "
                "the UNCERTAIN coverage gap both changed: the gap is resolved by "
                "the accepted U3 product decision instead of standing open. Both "
                "material hashes moved, so this boundary must move with them."
            ),
            # --- the resolved claim
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_claim_version": claim["schema_version"],
            "semantic_qualification_claim": claim["claim"],
            "qualified_support_statuses": list(claim["qualified_support_statuses"]),
            "excluded_support_statuses": list(claim["excluded_support_statuses"]),
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed": claim[
                "claim_semantics_changed_from_v132"
            ],
            # --- the U3 disposition and the decision it rests on
            "uncertain_coverage_disposition_version": disposition["schema_version"],
            "uncertain_coverage_disposition_hash": disposition["disposition_hash"],
            "uncertain_coverage_status": disposition["coverage_status"],
            "uncertain_coverage_product_decision": disposition["product_decision"],
            "uncertain_coverage_product_decision_status": disposition[
                "product_decision_status"
            ],
            "uncertain_coverage_product_decision_source": disposition[
                "product_decision_source"
            ],
            "uncertain_coverage_product_decision_hash": disposition[
                "product_decision_hash"
            ],
            "uncertain_coverage_product_decision_source_file_sha256": disposition[
                "product_decision_source_file_sha256"
            ],
            "uncertain_coverage_blocks_phase9_qualification": disposition[
                "blocks_phase9_qualification"
            ],
            "uncertain_coverage_blocks_full_p06_contract_coverage_claim": disposition[
                "blocks_full_p06_contract_coverage_claim"
            ],
            # --- N3 material, carried forward unchanged and proved so
            "n3_provider_fixture_set_hash_unchanged_from_v132": True,
        }
    )
    material["dependency_inventory"] = [
        *v132["stages"]["P06"]["dependency_inventory"],
        "P06 UNCERTAIN coverage disposition",
        "Phase 9B.7 accepted UNCERTAIN product decision",
    ]
    boundary = {**material, "stage_boundary_hash": canonical_hash(material)}

    if boundary["stage_boundary_hash"] == v132["stage_boundary_hashes"]["P06"]:
        raise V13BuildError(
            "the 1.3.3 P06 boundary reproduces the 1.3.2 hash; the resolved "
            "disposition was not actually bound"
        )
    if boundary["n3_provider_fixture_set_hash"] != FROZEN_N3_FIXTURE_SET_HASH:
        raise V13BuildError("the P06 boundary no longer binds the frozen fixture set")
    if boundary["n3_axis_hash"] != n3_axis["n3_axis_hash"]:
        raise V13BuildError("the P06 boundary no longer binds the derived N3 axis")
    boundary["supersedes_v132_p06_boundary"] = v132["stage_boundary_hashes"]["P06"]
    boundary["n3_provider_authority_inventory"] = list(
        v132["stages"]["P06"]["n3_provider_authority_inventory"]
    )
    boundary["n3_provider_authority_fully_bound"] = True
    return boundary


def v132_stage_change_proof(build: V13Build, stage: str) -> dict[str, Any]:
    """Prove component by component whether a stage's 1.3.2 material moved."""

    from .semantic_benchmark_v131 import v130_stage_change_proof

    published = _json(V132_REPORT_ROOT / "stage_boundaries.json")
    frozen_hash = published["stage_boundary_hashes"][stage]
    inner = v130_stage_change_proof(build, stage)
    material = {
        "schema_version": "semantic-benchmark-stage-change-proof/1.3.3",
        "stage": stage,
        "from_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "method": (
            "1.3.1 and 1.3.2 carried this stage's boundary forward unchanged, so "
            "the same reconstruction that justified those carry-forwards is "
            "re-executed here and compared with the hash 1.3.2 published."
        ),
        "components": inner["components"],
        "component_count": len(inner["components"]),
        "changed_components": list(inner["changed_components"]),
        "v133_reconstructed_boundary_hash": inner["v131_reconstructed_boundary_hash"],
        "v132_frozen_boundary_hash": frozen_hash,
        "stage_local_material_changed": (
            bool(inner["changed_components"])
            or inner["v131_reconstructed_boundary_hash"] != frozen_hash
        ),
    }
    return {**material, "proof_hash": canonical_hash(material)}


def carried_forward_stage_boundary_v133(build: V13Build, stage: str) -> dict[str, Any]:
    """Carry a 1.3.2 stage boundary forward, only on a passing change proof."""

    proof = v132_stage_change_proof(build, stage)
    if proof["stage_local_material_changed"]:
        raise V13BuildError(
            f"{stage} material changed between 1.3.2 and 1.3.3 "
            f"({proof['changed_components']}); it needs a new boundary"
        )
    published = _json(V132_REPORT_ROOT / "stage_boundaries.json")
    boundary = dict(published["stages"][stage])
    boundary["boundary_status"] = "CARRIED_FORWARD_FROM_V132"
    boundary["carried_forward_from_benchmark_version"] = SEMANTIC_BENCHMARK_V132_VERSION
    boundary["carry_forward_is_valid_because"] = (
        "Every component of this stage's 1.3.2 boundary material was "
        "reconstructed from 1.3.3 authority and reproduced exactly, and the "
        "reconstruction hashes to the frozen 1.3.2 boundary hash. This stage "
        "binds neither the semantic qualification claim nor the UNCERTAIN "
        "coverage disposition, so resolving the gap cannot reach it."
    )
    boundary["v133_change_proof_hash"] = proof["proof_hash"]
    boundary["v133_change_proof"] = proof
    boundary["stage_boundary_hash"] = published["stage_boundary_hashes"][stage]
    return boundary


def stage_boundaries_v133(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
) -> dict[str, Any]:
    boundaries: dict[str, dict[str, Any]] = {
        "P06": p06_stage_boundary_v133(build, n3_axis, fixtures, claim, disposition)
    }
    for stage in ("P04", "P07", "P09", "PLANNER"):
        boundaries[stage] = carried_forward_stage_boundary_v133(build, stage)

    missing = sorted(set(ACTIVE_BENCHMARK_STAGES) - set(boundaries))
    if missing:
        raise V13BuildError(f"1.3.3 published no stage boundary for: {missing}")

    published = _json(V132_REPORT_ROOT / "stage_boundaries.json")
    statuses = {
        stage: value["boundary_status"] for stage, value in sorted(boundaries.items())
    }
    for stage, status in statuses.items():
        same = (
            boundaries[stage]["stage_boundary_hash"]
            == published["stage_boundary_hashes"][stage]
        )
        if status == "CARRIED_FORWARD_FROM_V132" and not same:
            raise V13BuildError(f"{stage} claims carry-forward but its hash moved")
        if status == "NEW_IN_V133" and same:
            raise V13BuildError(
                f"{stage} claims a new boundary but reproduces the 1.3.2 hash"
            )

    material = {
        "schema_version": "semantic-benchmark-stage-boundaries/1.3.3",
        "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "previous_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "silent_carry_forward_permitted": False,
        "recomputation_without_a_change_is_a_defect": True,
        "stages": dict(sorted(boundaries.items())),
        "stage_boundary_hashes": {
            stage: value["stage_boundary_hash"]
            for stage, value in sorted(boundaries.items())
        },
        "boundary_status_by_stage": statuses,
        "new_boundary_stages": sorted(
            stage for stage, status in statuses.items() if status == "NEW_IN_V133"
        ),
        "carried_forward_stages": sorted(
            stage
            for stage, status in statuses.items()
            if status == "CARRIED_FORWARD_FROM_V132"
        ),
        "v132_stage_boundary_hashes": dict(published["stage_boundary_hashes"]),
    }
    return {**material, "stage_boundaries_hash": canonical_hash(material)}


def benchmark_boundary_v133(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
) -> dict[str, Any]:
    v132 = _json(V132_REPORT_ROOT / "benchmark_boundary.json")
    boundaries = stage_boundaries_v133(build, n3_axis, fixtures, claim, disposition)
    material = {
        key: value for key, value in v132.items() if key != "benchmark_boundary_hash"
    }
    shared = dict(material["shared_benchmark_authority"])
    shared["benchmark_version"] = SEMANTIC_BENCHMARK_V133_VERSION
    shared["semantic_qualification_claim_hash"] = claim["claim_hash"]
    shared["accepted_rate_bars_changed_from_v132"] = False
    shared.pop("accepted_rate_bars_changed_from_v131", None)
    aggregation = dict(material["cross_stage_aggregation_authority"])
    aggregation["benchmark_version"] = SEMANTIC_BENCHMARK_V133_VERSION
    material.update(
        {
            "boundary_format": BENCHMARK_BOUNDARY_FORMAT_V133,
            "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "previous_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "previous_version_status": V132_STATUS,
            "shared_benchmark_authority": shared,
            "cross_stage_aggregation_authority": aggregation,
            "stage_boundaries_hash": boundaries["stage_boundaries_hash"],
            "stage_boundary_hashes": dict(boundaries["stage_boundary_hashes"]),
            "boundary_status_by_stage": dict(boundaries["boundary_status_by_stage"]),
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "uncertain_coverage_disposition_hash": disposition["disposition_hash"],
            "uncertain_coverage_status": disposition["coverage_status"],
            "uncertain_coverage_product_decision": disposition["product_decision"],
            "uncertain_coverage_product_decision_status": disposition[
                "product_decision_status"
            ],
            "uncertain_coverage_product_decision_hash": disposition[
                "product_decision_hash"
            ],
            "uncertain_coverage_blocks_full_p06_contract_coverage_claim": disposition[
                "blocks_full_p06_contract_coverage_claim"
            ],
        }
    )
    material["documented_dependencies"] = [
        *v132["documented_dependencies"],
        "P06 UNCERTAIN coverage disposition",
        "Phase 9B.7 accepted UNCERTAIN product decision",
    ]
    return {**material, "benchmark_boundary_hash": canonical_hash(material)}


def candidate_matrix_v133(
    build: V13Build, *, benchmark_boundary_hash: str
) -> dict[str, Any]:
    """Candidate identities unchanged; the hash moves with what it binds."""

    from .semantic_benchmark_v131 import candidate_matrix_v131

    base = candidate_matrix_v131(build, benchmark_boundary_hash=benchmark_boundary_hash)
    v132 = _json(V132_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    material = {
        key: value for key, value in base.items() if key != "candidate_matrix_hash"
    }
    material.update(
        {
            "schema_version": CANDIDATE_MATRIX_VERSION_V133,
            "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "protocol_version": PROTOCOL_VERSION_V133,
            "candidate_identities_changed_from_v132": False,
            "carried_candidate_identity_hash": canonical_hash(v132["candidates"]),
            "new_hash_reason": (
                "The candidate identities, rungs and families did not change and "
                "are proved byte-identical to 1.3.2. The matrix hash moves "
                "because it binds phase9-qualification-protocol/1.3.3 and the "
                "1.3.3 global boundary, both of which changed when the UNCERTAIN "
                "coverage gap was published as resolved by U3."
            ),
        }
    )
    material.pop("candidate_identities_changed_from_v130", None)
    material.pop("candidate_identities_changed_from_v131", None)
    if material["candidates"] != v132["candidates"]:
        raise V13BuildError(
            "candidate identities must carry forward byte-identically from 1.3.2"
        )
    return {**material, "candidate_matrix_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART E -- protocol readiness under accepted U3
# --------------------------------------------------------------------------


def qualification_protocol_v133(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
) -> dict[str, Any]:
    """The 1.3.2 protocol, stating mechanically what U3 does and does not permit."""

    from .semantic_benchmark_v131 import qualification_protocol_v131

    base = qualification_protocol_v131(
        build,
        n3_axis,
        fixtures,
        benchmark_boundary=benchmark_boundary,
        candidate_matrix=candidate_matrix,
        call_budget=call_budget,
    )
    v132 = _json(V132_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    material = {
        key: value for key, value in base.items() if key != "protocol_boundary_hash"
    }
    # 1.3.2 carried these forward; 1.3.3 keeps them and adds the readiness block.
    material.update(
        {
            key: v132[key]
            for key in (
                "n3_construct_selection_rule_kind",
                "n3_construct_selection_semantics_hash",
            )
        }
    )
    material.update(
        {
            "schema_version": PROTOCOL_VERSION_V133,
            "protocol_version": PROTOCOL_VERSION_V133,
            "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "previous_protocol_version": v132["protocol_version"],
            "reason_for_new_version": [
                "the UNCERTAIN coverage gap is published as resolved by the "
                "accepted U3 product decision instead of standing open",
                "the semantic qualification claim binds that resolved "
                "disposition, so the claim material hash changed",
                "the P06 stage boundary changed",
                "the global benchmark boundary changed",
            ],
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_claim_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed_from_v132": claim[
                "claim_semantics_changed_from_v132"
            ],
            "qualified_support_statuses": list(claim["qualified_support_statuses"]),
            "excluded_support_statuses": list(claim["excluded_support_statuses"]),
            # --- PART E: what zero UNCERTAIN coverage does and does not block
            "uncertain_coverage_readiness": {
                "decision_gap": disposition["decision_gap"],
                "coverage_status": disposition["coverage_status"],
                "candidate_scoring_property_count": disposition[
                    "candidate_scoring_property_count"
                ],
                "product_decision": disposition["product_decision"],
                "product_decision_status": disposition["product_decision_status"],
                "product_decision_source": disposition["product_decision_source"],
                "product_decision_hash": disposition["product_decision_hash"],
                "resolution": disposition["resolution"],
                "disposition_hash": disposition["disposition_hash"],
                "zero_uncertain_coverage_blocks_execution": False,
                "zero_uncertain_coverage_blocks_full_p06_contract_coverage_claim": True,
                "additional_product_decision_pending_for_this_gap": False,
                "qualification_may_proceed_only_within_the_narrowed_claim": True,
                "narrowed_claim": claim["claim"],
                "uncertain_may_enter_accepted_semantic_rate": False,
                "uncertain_is_claimed_qualified": False,
                "readiness_release_is_bound_to": ACCEPTED_UNCERTAIN_DECISION,
                "readiness_release_is_generic": False,
                "fail_closed_rule": disposition["fail_closed_rule"],
                "rule": (
                    "Zero UNCERTAIN semantic coverage does not block execution "
                    "under the accepted U3 decision. It does block any claim "
                    "that Phase 9 established full P06 contract coverage. No "
                    "further product decision is pending for this known gap, and "
                    "qualification may proceed only within the narrowed claim."
                ),
            },
        }
    )
    # Everything mechanical must be identical to 1.3.2.
    for key in ("semantic_gates", "n3_gates", "ordering", "adjudication_protocol_hash"):
        if material[key] != v132[key]:
            raise V13BuildError(f"{key} may not change in 1.3.3")
    if material["call_budget_hash"] != v132["call_budget_hash"]:
        raise V13BuildError(
            "the call budget binds no claim, protocol or global value, so its "
            "hash may not change in 1.3.3"
        )
    if list(material["semantic_qualification_limitations"])[1:] != list(
        v132["semantic_qualification_limitations"]
    )[1:]:
        raise V13BuildError("the U3 limitations may not change in 1.3.3")
    return {**material, "protocol_boundary_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART C -- no active field may still demand the product decision
# --------------------------------------------------------------------------

#: Path segments under which the pre-decision state is legitimate, because the
#: field exists to record history rather than to state the current disposition.
HISTORICAL_DECISION_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        "pre_u3_uncertain_coverage_gate",
        "pre_decision_status",
        "historical_claim_lineage",
        "uncertain_gap_state",
        "gate_result_verbatim",
        "what_changed",
        "what_changed_from_v132",
        "why_a_new_hash",
        "why_it_is_not_active",
        "why_retained",
        "defect",
        "fail_closed_rule",
        "unresolved_reasons",
        "reason_for_new_version",
        "new_because",
        "new_hash_reason",
        "superseded_because",
        "replaced",
    }
)

#: This report records observations *about* the stop code, so its own rule and
#: evidence fields necessarily quote it.  Scanning them is a category error --
#: they are exempt by construction and the artifact says so -- but the exemption
#: is kept separate from the historical one, because "this field is a record of
#: history" and "this field is this scan's own evidence" are different reasons
#: and conflating them would let a real defect hide behind either label.
SCAN_SELF_EVIDENCE_FIELDS: frozenset[str] = frozenset(
    {
        "scanned_for",
        "also_scanned_for_true",
        "rule",
        "historical_path_segments",
        "self_evidence_fields",
        "self_exemption_reason",
        "closing_pass_rule",
        "deferred_to_closing_pass",
        "permitted_occurrences",
        "violations",
    }
)

_STOP_CODE = re.compile(re.escape(PRE_U3_STOP_CODE) + r"|\bPRODUCT_DECISION_REQUIRED\b")


def _walk_strings(
    node: Any, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_strings(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_strings(value, (*path, f"[{index}]"))
    elif isinstance(node, str):
        yield path, node


def _occurrence_reason(
    relative: str, path: tuple[str, ...], origin: str | None
) -> str:
    """Say why an occurrence of the pre-decision state is or is not permitted."""

    if origin is not None:
        return "REPUBLISHED_UNCHANGED_FROM_" + origin
    if any(segment in SCAN_SELF_EVIDENCE_FIELDS for segment in path):
        return "SCAN_SELF_EVIDENCE_FIELD"
    if any(segment in HISTORICAL_DECISION_PATH_SEGMENTS for segment in path):
        return "EXPLICIT_HISTORICAL_RECORD"
    return "ACTIVE_STATEMENT"


def product_decision_state_scan(
    package: Mapping[str, Mapping[str, Any]],
    *,
    republished_unchanged: Mapping[str, str],
    deferred: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fail closed if an active 1.3.3 field still demands the product decision.

    ``PRODUCT_DECISION_REQUIRED`` may still appear -- deleting the stop that
    produced Phase 9B.7 would make U3 look like a default -- but only inside a
    field whose job is history, or inside an artifact republished byte-identically
    from 1.3.2 and declared as such.  Every other occurrence is a current
    statement about an open gap, and the gap is not open.
    """

    violations: list[dict[str, str]] = []
    permitted: list[dict[str, str]] = []
    found = 0

    for relative in sorted(package):
        document = package[relative]
        origin = republished_unchanged.get(relative)
        for path, value in _walk_strings(document):
            if not _STOP_CODE.search(value):
                continue
            found += 1
            row = {
                "path": f"{relative}::{'.'.join(path)}",
                "value": value[:200],
                "reason": _occurrence_reason(relative, path, origin),
            }
            (violations if row["reason"] == "ACTIVE_STATEMENT" else permitted).append(row)

    # A truthy readiness block outside a historical record is the same defect
    # wearing a different field name, so scan for it too.
    for relative in sorted(package):
        document = package[relative]
        origin = republished_unchanged.get(relative)
        for path, value in _walk_bools(document):
            if path[-1] not in {"readiness_blocked", "requires_product_decision"}:
                continue
            if value is not True:
                continue
            found += 1
            row = {
                "path": f"{relative}::{'.'.join(path)}",
                "value": "true",
                "reason": _occurrence_reason(relative, path, origin),
            }
            (violations if row["reason"] == "ACTIVE_STATEMENT" else permitted).append(row)

    if violations:
        raise V13BuildError(
            "an active 1.3.3 field still says the UNCERTAIN coverage gap needs a "
            f"product decision: {violations}"
        )

    material = {
        "schema_version": "p06-uncertain-product-decision-state-scan/1.3.3",
        "active_benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "decision_gap": UNCERTAIN_COVERAGE_DECISION_GAP,
        "scanned_for": [PRE_U3_STOP_CODE, "PRODUCT_DECISION_REQUIRED"],
        "also_scanned_for_true": ["readiness_blocked", "requires_product_decision"],
        "rule": (
            "PRODUCT_DECISION_REQUIRED, and a true readiness block, may appear "
            "only in a field that records the pre-decision history or in an "
            "artifact republished byte-identically from 1.3.2 and declared as "
            "such. Every other occurrence is a current statement that the gap is "
            "open, and Phase 9B.7 closed it with U3."
        ),
        "historical_path_segments": sorted(HISTORICAL_DECISION_PATH_SEGMENTS),
        "self_evidence_fields": sorted(SCAN_SELF_EVIDENCE_FIELDS),
        "self_exemption_reason": (
            "This report records observations about the stop code, so its rule "
            "and evidence fields necessarily quote it. They are exempt by "
            "construction; every other field is scanned like any other."
        ),
        "artifacts_scanned": len(package),
        "scanned_artifacts": sorted(package),
        "deferred_to_closing_pass": dict(sorted((deferred or {}).items())),
        "closing_pass_rule": (
            "This report and the pre-results freeze cannot appear in their own "
            "scan without self-reference. They are covered instead by a closing "
            "pass over the complete package, run after both exist, which raises "
            "on any violation."
        ),
        "occurrences_found": found,
        "violations": [],
        "violation_count": 0,
        "permitted_occurrences": permitted,
        "permitted_occurrence_count": len(permitted),
        "active_stop_code": None,
        "active_requires_product_decision": False,
        "active_readiness_blocked": False,
    }
    return {**material, "scan_hash": canonical_hash(material)}


def _walk_bools(
    node: Any, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], bool]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_bools(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_bools(value, (*path, f"[{index}]"))
    elif isinstance(node, bool):
        yield path, node


# --------------------------------------------------------------------------
# no stale current-version claims
# --------------------------------------------------------------------------

CURRENT_CLAIM_FIELDS: frozenset[str] = frozenset(
    {
        "claim",
        "semantic_qualification_claim",
        "semantic_qualification_limitations",
        "semantic_claim_limitations",
        "limitations",
    }
)

HISTORICAL_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        "previous_version",
        "previous_version_status",
        "from_version",
        "to_version",
        "chain",
        "historical_claim_lineage",
        "supersedes_claim_binding_from",
        "supersedes_disposition_in",
        "supersedes_v132_p06_boundary",
        "supersedes_v131_p06_boundary",
        "supersedes_v130_p06_boundary",
        "supersedes",
        "carried_forward_from",
        "carried_forward_from_benchmark_version",
        "carry_forward_is_valid_because",
        "v130_stage_boundary_hashes",
        "v131_stage_boundary_hashes",
        "v132_stage_boundary_hashes",
        "v130_status",
        "v131_status",
        "v132_status",
        "v130_preserved",
        "v131_preserved",
        "v132_preserved",
        "v131_change_proof",
        "v132_change_proof",
        "v133_change_proof",
        "change_proof",
        "v130_frozen_boundary_hash",
        "v131_frozen_boundary_hash",
        "v132_frozen_boundary_hash",
        "previous_protocol_version",
        "republished_unchanged",
        "republished_unchanged_hashes",
        "originating_version",
        "inherited_unchanged",
        "new_in_v131",
        "new_in_v132",
        "new_in_v133",
        "replaced",
        "results_firewall",
        "reason_for_new_version",
        "new_hash_reason",
        "lineage",
        "what_changed",
        "what_changed_from_v132",
        "what_did_not_change_from_v132",
        "why_a_new_hash",
        "defect",
        "superseded_because",
        "carried_forward_artifacts",
        "fixtures_identical_to_v131",
        "fixtures_identical_to_v132",
        "method",
        "published_separately_because",
        "n3_provider_fixture_set_hash_unchanged_from_v131",
        "n3_provider_fixture_set_hash_unchanged_from_v132",
        "semantic_qualification_supersedes_binding_from",
        "semantic_qualification_supersedes_claim_binding_from",
        "candidate_identities_changed_from_v131",
        "candidate_identities_changed_from_v132",
        "semantic_qualification_semantics_changed_from_v131",
        "semantic_qualification_semantics_changed_from_v132",
        "claim_semantics_changed_from_v131",
        "claim_semantics_changed_from_v132",
        "accepted_rate_bars_changed_from_v131",
        "accepted_rate_bars_changed_from_v132",
        "bars_changed_from_v12",
        "bars_changed_from_v130",
        "boundary_status",
        "new_because",
        "published_in_v132",
        "invariants",
        "superseded_versions_scanned_for",
        "permitted_mentions",
        "violations",
        "rule",
    }
)

_SUPERSEDED_VERSION = re.compile(r"semantic-benchmark/1\.3\.[012]\b")


def stale_claim_scan(
    package: Mapping[str, Mapping[str, Any]],
    *,
    republished_unchanged: Mapping[str, str],
    deferred: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fail closed if a current claim or limitation names a superseded version."""

    violations: list[dict[str, str]] = []
    permitted: list[dict[str, str]] = []
    scanned = 0

    for relative in sorted(package):
        document = package[relative]
        origin = republished_unchanged.get(relative)
        for path, value in _walk_strings(document):
            if not _SUPERSEDED_VERSION.search(value):
                continue
            scanned += 1
            joined = ".".join(path)
            in_claim_field = any(segment in CURRENT_CLAIM_FIELDS for segment in path)
            historical = any(segment in HISTORICAL_PATH_SEGMENTS for segment in path)
            carried_stage = (
                len(path) >= 3
                and path[0] == "stages"
                and str(
                    document.get("stages", {})
                    .get(path[1], {})
                    .get("boundary_status", "")
                ).startswith("CARRIED_FORWARD")
            )
            row = {
                "path": f"{relative}::{joined}",
                "value": value[:160],
                "reason": (
                    "REPUBLISHED_UNCHANGED_FROM_" + origin
                    if origin
                    else "HISTORICAL_OR_PROVENANCE_FIELD"
                    if historical
                    else "CARRIED_FORWARD_STAGE_SUBTREE"
                    if carried_stage
                    else "CURRENT_STATEMENT"
                ),
            }
            if in_claim_field and not origin:
                violations.append({**row, "reason": "CURRENT_CLAIM_OR_LIMITATION"})
            elif row["reason"] == "CURRENT_STATEMENT":
                violations.append(row)
            else:
                permitted.append(row)

    if violations:
        raise V13BuildError(
            "a current 1.3.3 authority statement names a superseded benchmark "
            f"version: {violations}"
        )

    material = {
        "schema_version": "semantic-benchmark-stale-claim-scan/1.3.3",
        "active_benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "superseded_versions_scanned_for": [
            "semantic-benchmark/1.3.0",
            "semantic-benchmark/1.3.1",
            "semantic-benchmark/1.3.2",
        ],
        "rule": (
            "A superseded version may appear only in a field that records "
            "history or provenance, in a carried-forward stage subtree, or in an "
            "artifact republished byte-identically and declared as such. Every "
            "other mention is a current statement and must name the active "
            "version."
        ),
        "current_claim_fields": sorted(CURRENT_CLAIM_FIELDS),
        "self_exempt_evidence_fields": [
            "superseded_versions_scanned_for",
            "permitted_mentions",
            "violations",
            "rule",
        ],
        "self_exemption_reason": (
            "This report records observations about version mentions, so its "
            "evidence fields necessarily quote the strings it scans for. They "
            "are exempt by construction; every other field of this artifact is "
            "scanned like any other."
        ),
        "artifacts_scanned": len(package),
        "scanned_artifacts": sorted(package),
        "deferred_to_closing_pass": dict(sorted((deferred or {}).items())),
        "closing_pass_rule": (
            "This report and the pre-results freeze cannot appear in their own "
            "scan without self-reference: the freeze binds this report's hash, "
            "and this report would have to contain its own. They are covered "
            "instead by a closing pass over the complete package, run after both "
            "exist, which raises on any violation."
        ),
        "mentions_found": scanned,
        "violations": [],
        "violation_count": 0,
        "permitted_mentions": permitted,
        "permitted_mention_count": len(permitted),
        "republished_unchanged_artifacts": dict(sorted(republished_unchanged.items())),
    }
    return {**material, "scan_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# Lineage and the pre-results freeze
# --------------------------------------------------------------------------

#: Artifacts 1.3.3 republishes byte-identically from 1.3.2.  Their complete
#: material is unchanged, so their hashes must not move: they are copied rather
#: than regenerated with a new version stamp.
REPUBLISHED_FROM_V132: Mapping[str, str] = {
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": (
        "phase9/n3_provider_fixtures.json"
    ),
    f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": (
        "phase9/n3_contractual_safety_axis.json"
    ),
    f"{DEFINITION_ROOT}/phase9/construct_selection_semantics.json": (
        "phase9/construct_selection_semantics.json"
    ),
    f"{REPORT_ROOT}/phase9/call_budget.json": "phase9/call_budget.json",
    f"{REPORT_ROOT}/phase9/noisy_disposition_census.json": (
        "phase9/noisy_disposition_census.json"
    ),
    f"{REPORT_ROOT}/phase9/construct_selection_independence.json": (
        "phase9/construct_selection_independence.json"
    ),
    f"{REPORT_ROOT}/phase9/n3_production_representativeness.json": (
        "phase9/n3_production_representativeness.json"
    ),
}


def _v132_source(relative: str) -> Path:
    tail = REPUBLISHED_FROM_V132[relative]
    root = (
        V132_DEFINITION_ROOT if relative.startswith(DEFINITION_ROOT) else V132_REPORT_ROOT
    )
    return root / tail


def republished_documents() -> dict[str, dict[str, Any]]:
    """Load the 1.3.2 bytes for every artifact 1.3.3 republishes unchanged."""

    return {
        relative: _json(_v132_source(relative)) for relative in REPUBLISHED_FROM_V132
    }


def lineage_v133(build: V13Build) -> dict[str, Any]:
    v132_lineage = _json(V132_REPORT_ROOT / "lineage.json")
    republished = {
        relative: {
            "originating_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "source_path": _v132_source(relative)
            .relative_to(REPOSITORY_ROOT)
            .as_posix(),
            "bytes_identical": True,
            "reason": (
                "Its complete material is unchanged, so republishing it with a "
                "new version stamp would move a hash without moving a meaning."
            ),
        }
        for relative in sorted(REPUBLISHED_FROM_V132)
    }
    material = {
        "schema_version": "semantic-benchmark-lineage/1.3.3",
        "from_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "chain": [
            {
                "version": "semantic-benchmark/1.2.0",
                "status": "IMMUTABLE_HISTORICAL_AUTHORITY",
            },
            {
                "version": "semantic-benchmark/1.3.0",
                "status": V131_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
                "bytes_modified_by_v133": False,
            },
            {
                "version": "semantic-benchmark/1.3.1",
                "status": V131_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
                "bytes_modified_by_v133": False,
            },
            {
                "version": SEMANTIC_BENCHMARK_V132_VERSION,
                "status": V132_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
                "superseded_because": [
                    "its active semantic qualification claim still embedded the "
                    "pre-decision UNCERTAIN coverage gate, so an active field "
                    "carried readiness_blocked=true and the stop code "
                    "PRODUCT_DECISION_REQUIRED for a gap Phase 9B.7 had already "
                    "decided with U3"
                ],
                "bytes_modified_by_v133": False,
            },
            {
                "version": SEMANTIC_BENCHMARK_V133_VERSION,
                "status": V133_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
            },
        ],
        "is_a_corpus_change": False,
        "is_a_semantic_product_decision_change": False,
        "is_a_pre_execution_authority_binding_repair": True,
        "reopens_the_u3_product_decision": False,
        "no_result_existed_when_this_repair_was_made": True,
        "v132_lineage_hash": v132_lineage["lineage_hash"],
        "replaced": {
            "phase9/semantic_qualification_claim.json": (
                "the open pre-decision gate is replaced by the resolved U3 "
                "disposition; the coverage fact is unchanged"
            ),
            "phase9/qualification_protocol.json": (
                "states mechanically what zero UNCERTAIN coverage does and does "
                "not block under accepted U3"
            ),
            "phase9/candidate_matrix.json": (
                "identities unchanged; binds the new protocol and boundary"
            ),
        },
        "new_in_v133": {
            "phase9/uncertain_coverage_disposition.json": (
                "the active post-decision disposition of the UNCERTAIN coverage "
                "gap, with the pre-U3 gate retained as history"
            ),
            "phase9/semantic_invariant_equality_proof.json": (
                "component-by-component proof that no semantic or N3 material "
                "moved"
            ),
            "phase9/product_decision_state_scan.json": (
                "the executed scan for active fields still demanding the product "
                "decision"
            ),
        },
        "carried_forward_artifacts": republished,
        "carried_forward_artifact_count": len(republished),
        "silent_carry_forward_permitted": False,
    }
    return {**material, "lineage_hash": canonical_hash(material)}


def pre_results_freeze_v133(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    qualification_protocol: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    lineage: Mapping[str, Any],
    fixture_equality: Mapping[str, Any],
    invariant_equality: Mapping[str, Any],
    stale_scan: Mapping[str, Any],
    decision_scan: Mapping[str, Any],
) -> dict[str, Any]:
    from .semantic_benchmark_v131 import pre_results_freeze_v131

    base = pre_results_freeze_v131(
        build,
        n3_axis,
        fixtures,
        benchmark_boundary=benchmark_boundary,
        stage_boundaries=stage_boundaries,
        qualification_protocol=qualification_protocol,
        candidate_matrix=candidate_matrix,
        call_budget=call_budget,
        lineage=lineage,
    )
    v132_freeze = _json(V132_REPORT_ROOT / "phase9/pre_results_instrument_freeze.json")
    material = {
        key: value for key, value in base.items() if key != "freeze_material_hash"
    }
    material.update(
        {
            "schema_version": "phase9-pre-results-instrument-freeze/1.3.3",
            "phase": "9B.8C",
            "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "previous_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "previous_version_status": V132_STATUS,
            "status": V133_STATUS,
            "purpose": (
                "Freeze the U3 + N3 pre-execution instrument with the UNCERTAIN "
                "coverage gap published as resolved by the accepted U3 product "
                "decision -- still uncovered, no longer undecided -- before any "
                "candidate result exists."
            ),
            "file_sha256_and_git_blob_sha_live_in": (
                f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
            ),
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_claim_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_claim_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed_from_v132": claim[
                "claim_semantics_changed_from_v132"
            ],
            # --- the resolved disposition
            "uncertain_coverage_disposition_hash": disposition["disposition_hash"],
            "uncertain_coverage_status": disposition["coverage_status"],
            "uncertain_coverage_decision_gap": disposition["decision_gap"],
            "uncertain_coverage_product_decision": disposition["product_decision"],
            "uncertain_coverage_product_decision_status": disposition[
                "product_decision_status"
            ],
            "uncertain_coverage_product_decision_source": disposition[
                "product_decision_source"
            ],
            "uncertain_coverage_product_decision_hash": disposition[
                "product_decision_hash"
            ],
            "uncertain_coverage_resolution": disposition["resolution"],
            "uncertain_coverage_requires_product_decision": disposition[
                "requires_product_decision"
            ],
            "uncertain_coverage_blocks_phase9_qualification": disposition[
                "blocks_phase9_qualification"
            ],
            "uncertain_coverage_blocks_candidate_rung_selection": disposition[
                "blocks_candidate_rung_selection"
            ],
            "uncertain_coverage_blocks_full_p06_contract_coverage_claim": disposition[
                "blocks_full_p06_contract_coverage_claim"
            ],
            "uncertain_remains_unqualified": disposition["uncertain_remains_unqualified"],
            # --- proofs
            "n3_construct_selection_semantics_hash": v132_freeze[
                "n3_construct_selection_semantics_hash"
            ],
            "n3_fixture_equality_proof_hash": fixture_equality["proof_hash"],
            "n3_provider_fixture_set_hash_unchanged_from_v132": True,
            "semantic_invariant_equality_proof_hash": invariant_equality["proof_hash"],
            "stale_claim_scan_hash": stale_scan["scan_hash"],
            "stale_claim_violation_count": stale_scan["violation_count"],
            "product_decision_state_scan_hash": decision_scan["scan_hash"],
            "product_decision_state_violation_count": decision_scan["violation_count"],
            "results_firewall": {
                "candidate_outcomes_read": False,
                "first_pass_adjudication_results_read": False,
                "provider_outputs_read": False,
                "historical_qualification_results_used_as_construction_authority": False,
                "note": (
                    "No candidate result exists for any 1.3.x pre-execution "
                    "candidate. Superseding one is an instrumentation or "
                    "authority-binding repair, never a response to an outcome."
                ),
            },
            "v132_preserved": {"v132_bytes_modified": False, "status": V132_STATUS},
            "stop_condition": (
                "SEMANTIC_BENCHMARK_V1_3_3_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT"
            ),
        }
    )
    return {**material, "freeze_material_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART K -- the self-hash registry
# --------------------------------------------------------------------------

SELF_MATERIAL_HASH_FIELD: Mapping[str, str | None] = {
    f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": "protocol_boundary_hash",
    f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": "candidate_matrix_hash",
    f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": "claim_hash",
    f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json": "disposition_hash",
    f"{DEFINITION_ROOT}/phase9/construct_selection_semantics.json": "semantics_hash",
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": "fixture_set_hash",
    f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": "n3_axis_hash",
    f"{REPORT_ROOT}/lineage.json": "lineage_hash",
    f"{REPORT_ROOT}/stage_boundaries.json": "stage_boundaries_hash",
    f"{REPORT_ROOT}/benchmark_boundary.json": "benchmark_boundary_hash",
    f"{REPORT_ROOT}/phase9/call_budget.json": "call_budget_hash",
    f"{REPORT_ROOT}/phase9/noisy_disposition_census.json": "census_hash",
    f"{REPORT_ROOT}/phase9/construct_selection_independence.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/n3_production_representativeness.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/n3_fixture_equality_proof.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/semantic_invariant_equality_proof.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/stale_claim_scan.json": "scan_hash",
    f"{REPORT_ROOT}/phase9/product_decision_state_scan.json": "scan_hash",
    f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": "freeze_material_hash",
}


def self_material_hash(path: str, document: Mapping[str, Any]) -> str | None:
    """Return a document's own material hash, proved rather than guessed."""

    if path not in SELF_MATERIAL_HASH_FIELD:
        raise HashManifestError(
            f"{path} has no entry in SELF_MATERIAL_HASH_FIELD; a generated "
            "artifact must declare which field is its self hash, or declare "
            "explicitly that it has none"
        )
    field = SELF_MATERIAL_HASH_FIELD[path]
    if field is None:
        return None
    if field not in document:
        raise HashManifestError(f"{path} declares self hash {field!r}, which is absent")
    declared = document[field]
    recomputed = canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )
    if declared != recomputed:
        raise HashManifestError(
            f"{path}.{field} is not this document's material hash: it declares "
            f"{declared} but the document hashes to {recomputed}. A dependency "
            "hash may never be reported as a self hash."
        )
    return declared


# --------------------------------------------------------------------------
# Package assembly
# --------------------------------------------------------------------------


def v133_package(build: V13Build) -> dict[str, dict[str, Any]]:
    """Every generated 1.3.3 document, keyed by repository-relative path."""

    from .n3_provider_fixtures import n3_provider_fixture_authority
    from .semantic_benchmark_v131 import call_budget_v131
    # v1.3.3 remains immutable historical evidence after later executable N3
    # repairs.  Rebuild it against the axis bytes it actually published.
    n3_axis = _json(V132_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json")
    fixtures = n3_provider_fixture_authority(build.corpus_root)
    fixture_equality = n3_fixture_equality_proof_v133(fixtures)
    disposition = u3_uncertain_disposition(build)
    claim = semantic_qualification_claim_v133(build, disposition)
    boundaries = stage_boundaries_v133(build, n3_axis, fixtures, claim, disposition)
    global_boundary = benchmark_boundary_v133(
        build, n3_axis, fixtures, claim, disposition
    )
    budget = call_budget_v131(build, fixtures)
    matrix = candidate_matrix_v133(
        build, benchmark_boundary_hash=global_boundary["benchmark_boundary_hash"]
    )
    protocol = qualification_protocol_v133(
        build,
        n3_axis,
        fixtures,
        claim,
        disposition,
        benchmark_boundary=global_boundary,
        candidate_matrix=matrix,
        call_budget=budget,
    )
    invariant_equality = semantic_invariant_equality_proof(
        build,
        fixtures,
        candidate_matrix=matrix,
        call_budget=budget,
        qualification_protocol=protocol,
    )
    lineage = lineage_v133(build)

    package = {
        **republished_documents(),
        f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json": disposition,
        f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": claim,
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": protocol,
        f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": matrix,
        f"{REPORT_ROOT}/lineage.json": lineage,
        f"{REPORT_ROOT}/stage_boundaries.json": boundaries,
        f"{REPORT_ROOT}/benchmark_boundary.json": global_boundary,
        f"{REPORT_ROOT}/phase9/n3_fixture_equality_proof.json": fixture_equality,
        f"{REPORT_ROOT}/phase9/semantic_invariant_equality_proof.json": (
            invariant_equality
        ),
    }
    deferred_stale = {
        f"{REPORT_ROOT}/phase9/stale_claim_scan.json": (
            "this report cannot contain its own hash"
        ),
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": (
            "the freeze binds this report's hash"
        ),
    }
    deferred_decision = {
        f"{REPORT_ROOT}/phase9/product_decision_state_scan.json": (
            "this report cannot contain its own hash"
        ),
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": (
            "the freeze binds this report's hash"
        ),
    }
    stale_scan = stale_claim_scan(
        package,
        republished_unchanged=REPUBLISHED_FROM_V132,
        deferred=deferred_stale,
    )
    decision_scan = product_decision_state_scan(
        package,
        republished_unchanged=REPUBLISHED_FROM_V132,
        deferred=deferred_decision,
    )
    freeze = pre_results_freeze_v133(
        build,
        n3_axis,
        fixtures,
        claim,
        disposition,
        benchmark_boundary=global_boundary,
        stage_boundaries=boundaries,
        qualification_protocol=protocol,
        candidate_matrix=matrix,
        call_budget=budget,
        lineage=lineage,
        fixture_equality=fixture_equality,
        invariant_equality=invariant_equality,
        stale_scan=stale_scan,
        decision_scan=decision_scan,
    )
    package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"] = stale_scan
    package[f"{REPORT_ROOT}/phase9/product_decision_state_scan.json"] = decision_scan
    package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"] = freeze
    # Closing passes over the complete package, including the two scans and the
    # freeze themselves.  Either raises rather than reporting a violation.
    stale_claim_scan(package, republished_unchanged=REPUBLISHED_FROM_V132)
    product_decision_state_scan(package, republished_unchanged=REPUBLISHED_FROM_V132)
    return package
