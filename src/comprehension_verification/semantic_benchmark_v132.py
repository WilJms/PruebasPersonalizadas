"""``semantic-benchmark/1.3.2`` -- rebind the U3 claim to the active version.

``semantic-benchmark/1.3.1`` is not edited.  It is marked
``SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED`` and its bytes
stay as published; no provider or adjudicator ever ran against it, so this is an
authority-binding repair rather than result-driven tuning.

The defect is narrow and entirely textual.  1.3.1 is the active pre-execution
candidate, but the qualification text it carries forward still says

    semantic-benchmark/1.3.0 qualifies P06 candidate behaviour ...
    semantic-benchmark/1.3.0 does NOT qualify P06 UNCERTAIN behaviour.

Those sentences were written for 1.3.0 and were correct then.  Carried into
1.3.1 unchanged they became a *current* claim about a superseded version, which
leaves a reader to infer applicability from version lineage -- exactly what an
authority artifact exists to remove.  The mechanical policy never changed:
``SUFFICIENT`` / ``PARTIAL`` / ``INSUFFICIENT`` qualified, ``UNCERTAIN``
excluded and still in the production contract, Phase 9 alone not full contract
coverage.

So 1.3.2 changes wording and binding, and nothing else.  The semantic scoring
set, routes, denominators, thresholds, bars, the N3 provider fixtures and their
hashes, the N3 axis and the call budget are all carried forward and each one is
*proved* unchanged rather than assumed.

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
from .n3_provider_fixtures import (
    N3_CONSTRUCT_SELECTION_RULE,
    N3_SELECTION_FORBIDDEN_INPUTS,
)
from .p06_support_status_coverage import (
    CONTRACT_SUPPORT_STATUSES,
    P06_SUPPORT_STATUS_COVERAGE_VERSION,
    P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
    UNCERTAIN,
    uncertain_coverage_gate,
)
from .semantic_benchmark import ACTIVE_BENCHMARK_STAGES, DEFAULT_CORPUS_ROOT
from .semantic_benchmark_v13 import (
    QUALIFIED_SUPPORT_STATUSES,
    REPOSITORY_ROOT,
    V13Build,
    V13BuildError,
    build_v13,
    p06_instrument_report,
)
from .semantic_benchmark_v131 import (
    SEMANTIC_BENCHMARK_V131_VERSION,
    V130_STATUS,
    HashManifestError,
)


SEMANTIC_BENCHMARK_V132_VERSION = "semantic-benchmark/1.3.2"
BENCHMARK_BOUNDARY_FORMAT_V132 = "semantic-benchmark-boundary/1.3.2"
PROTOCOL_VERSION_V132 = "phase9-qualification-protocol/1.3.2"
CANDIDATE_MATRIX_VERSION_V132 = "phase9-candidate-matrix/1.3.2"
CLAIM_VERSION_V132 = "p06-semantic-qualification-claim/1.3.2"
CONSTRUCT_SELECTION_SEMANTICS_VERSION = "n3-construct-selection-semantics/1.3.2"

V131_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_1"
V131_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_1"
DEFINITION_ROOT = "evaluation/semantic_benchmark/v1_3_2"
REPORT_ROOT = "reports/semantic_benchmark/v1_3_2"

V131_STATUS = "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
V132_STATUS = "PREEXECUTION_FREEZE_CANDIDATE"

#: The N3 provider fixture set 1.3.1 froze.  1.3.2 must reproduce it exactly.
FROZEN_N3_FIXTURE_SET_HASH = (
    "sha256:f53ec77ae4c26732644083d10497e65e1a1bc34f830e675aa4848669d106c62d"
)

#: The claim, worded for the version it actually applies to.
SEMANTIC_QUALIFICATION_CLAIM_V132 = (
    f"{SEMANTIC_BENCHMARK_V132_VERSION} qualifies P06 candidate behaviour on the "
    "support statuses SUFFICIENT, PARTIAL and INSUFFICIENT."
)

#: The four limitations, likewise.  A regression pins them, so the narrowed
#: claim cannot quietly weaken or drift back to naming a superseded version.
U3_LIMITATIONS_V132: tuple[str, ...] = (
    f"{SEMANTIC_BENCHMARK_V132_VERSION} does NOT qualify P06 UNCERTAIN behaviour.",
    "P06 model-selection claims are limited to SUFFICIENT / PARTIAL / INSUFFICIENT.",
    "UNCERTAIN remains an explicit residual risk.",
    "Phase 9 alone does not establish full P06 contract coverage.",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def build_v132(corpus_root: Path = DEFAULT_CORPUS_ROOT) -> V13Build:
    """1.3.2 reuses the 1.3.0/1.3.1 semantic instrument unchanged."""

    return build_v13(corpus_root)


# --------------------------------------------------------------------------
# PART A + B -- the version-correct claim and its applicability metadata
# --------------------------------------------------------------------------


def semantic_qualification_claim_v132(build: V13Build) -> dict[str, Any]:
    """State what the *active* benchmark claims, and for which version.

    The exclusion stays derived rather than declared: a status is listed as
    qualified only when the frozen instrument actually carries candidate-scoring
    properties asserting it.  What changes here is which benchmark version the
    sentence names -- and the applicability metadata that spares a reader from
    inferring it from lineage.
    """

    coverage = build.support_status_coverage
    gate = uncertain_coverage_gate(coverage)
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
    if gate["candidate_scoring_property_count"] != 0:
        raise V13BuildError(
            "UNCERTAIN is claimed unqualified but the instrument carries "
            f"{gate['candidate_scoring_property_count']} scoring properties for it"
        )

    # The v1.3.1 claim, quoted so the semantics comparison is evidence rather
    # than an assertion. Only the version-naming sentences may differ.
    v131_protocol = _json(V131_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    v131_limitations = list(v131_protocol["semantic_qualification_limitations"])
    semantics_unchanged = (
        list(v131_protocol["qualified_support_statuses"]) == list(qualified)
        and list(v131_protocol["excluded_support_statuses"]) == list(excluded)
        and v131_protocol["uncertain_qualification_claimed"] is False
        and v131_protocol["phase9_alone_is_full_p06_contract_coverage"] is False
        and v131_limitations[1:3] == list(U3_LIMITATIONS_V132[1:3])
    )
    if not semantics_unchanged:
        raise V13BuildError(
            "1.3.2 may only rebind the claim wording; its semantics differ from "
            "1.3.1, which would be a product-decision change"
        )

    material = {
        "schema_version": CLAIM_VERSION_V132,
        # --- PART B: applicability, stated rather than inferred
        "applicable_benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "supersedes_claim_binding_from": SEMANTIC_BENCHMARK_V131_VERSION,
        "claim_semantics_changed_from_v131": False,
        "what_changed": (
            "The claim and its limitations now name the benchmark version they "
            "actually apply to. Nothing about which behaviour is qualified "
            "changed."
        ),
        "why_a_new_hash": (
            "The claim text and the applicable benchmark version both changed, "
            "so the claim's material hash must change even though its meaning "
            "did not."
        ),
        "reader_must_not_infer_applicability_from_lineage": True,
        # --- the claim itself
        "accepted_decision": "U3",
        "decision_source": "reports/semantic_benchmark/phase9b7/product_decision.json",
        "claim": SEMANTIC_QUALIFICATION_CLAIM_V132,
        "qualified_support_statuses": list(qualified),
        "excluded_support_statuses": list(excluded),
        "candidate_scoring_property_count_by_status": dict(sorted(counts.items())),
        "uncertain_qualification_claimed": False,
        "uncertain_scoring_property_count": counts[UNCERTAIN],
        "uncertain_scope_census_version": P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
        "uncertain_scope_census_hash": build.uncertain_census["census_hash"],
        "support_status_coverage_version": P06_SUPPORT_STATUS_COVERAGE_VERSION,
        "support_status_coverage_hash": coverage["report_hash"],
        "uncertain_coverage_gate": gate,
        "limitations": list(U3_LIMITATIONS_V132),
        "limitation_count": len(U3_LIMITATIONS_V132),
        "production_contract_unchanged": True,
        "uncertain_removed_from_production_contract": False,
        "production_contract_note": (
            "UNCERTAIN remains a first-class member of the P06 support-status "
            "contract. 1.3.2 changes no production prompt, DTO, materializer or "
            "planner semantics. What it declares is the limit of its own "
            "qualification evidence."
        ),
        "phase9_alone_is_full_p06_contract_coverage": False,
        # --- historical lineage, explicitly labelled as history
        "historical_claim_lineage": [
            {
                "benchmark_version": "semantic-benchmark/1.3.0",
                "status": V130_STATUS,
                "claim_named_version": "semantic-benchmark/1.3.0",
                "correct_when_published": True,
            },
            {
                "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
                "status": V131_STATUS,
                "claim_named_version": "semantic-benchmark/1.3.0",
                "correct_when_published": False,
                "defect": (
                    "The claim was carried forward verbatim, so an active "
                    "version published a current claim naming a superseded one."
                ),
            },
        ],
        "originating_product_decision": {
            "decision": "U3",
            "phase": "9B.7",
            "accepted": True,
            "unchanged_by_this_repair": True,
        },
    }
    return {**material, "claim_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART F -- what the source-order rule does and does not assert
# --------------------------------------------------------------------------


def construct_selection_semantics() -> dict[str, Any]:
    """Clarify the meaning of the N3 construct-selection rule.

    This is wording only.  It is published as its own artifact precisely so the
    clarification cannot move a fixture byte: the fixture set binds the source
    hash of ``n3_provider_fixtures.py``, so editing even a docstring there would
    change ``fixture_set_hash`` and force a rebuild of authority that has not
    actually changed.
    """

    material = {
        "schema_version": CONSTRUCT_SELECTION_SEMANTICS_VERSION,
        "rule": N3_CONSTRUCT_SELECTION_RULE,
        "rule_kind": "PRE_REGISTERED_SAMPLING_RULE",
        "grounded_in": "AUTHORIZED_SOURCE_DOCUMENT_STRUCTURE",
        "what_the_rule_is": (
            "A pre-registered sampling rule. N3 needs exactly one authorized, "
            "deterministic, outcome-independent construct per exposure in order "
            "to instantiate a production-valid P06 call. Source order supplies "
            "that choice without consulting anything a result could influence."
        ),
        "what_the_rule_does_not_assert": [
            "that the instructor academically prioritized the first criterion",
            "that the first construct is more important than the others",
            "that source position changes the semantic expected answer",
            "that the sampled construct is the only one a real P06 run would see",
        ],
        "why_a_sampling_rule_suffices": (
            "The nine contractual obligations N3 adjudicates are "
            "construct-independent: they govern how the model treats "
            "instruction-shaped text in untrusted evidence, not which criterion "
            "it is scoring. Any authorized construct instantiates the call "
            "equally well, so the rule only has to be deterministic and blind to "
            "outcomes -- which is proved separately."
        ),
        "forbidden_inputs": list(N3_SELECTION_FORBIDDEN_INPUTS),
        "changes_any_fixture_material": False,
        "changes_the_selected_construct": False,
        "fixture_set_hash_unchanged": FROZEN_N3_FIXTURE_SET_HASH,
        "published_separately_because": (
            "The fixture set binds the source hash of n3_provider_fixtures.py, "
            "so a prose edit in that module would change fixture_set_hash. "
            "Wording is clarified here instead, and bound by the P06 boundary."
        ),
    }
    return {**material, "semantics_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART D -- boundaries, and the proof that N3 material did not move
# --------------------------------------------------------------------------


def n3_fixture_equality_proof(fixtures: Mapping[str, Any]) -> dict[str, Any]:
    """Prove every N3 provider fixture byte is unchanged from 1.3.1.

    Not "the set hash matches" alone: the published 1.3.1 document is compared
    field by field with the freshly derived one, so a change that happened to
    preserve the aggregate would still be caught, and the per-fixture request
    hashes are compared individually.
    """

    published = _json(V131_DEFINITION_ROOT / "phase9/n3_provider_fixtures.json")

    if fixtures["fixture_set_hash"] != FROZEN_N3_FIXTURE_SET_HASH:
        raise V13BuildError(
            "the N3 provider fixture set moved: "
            f"{fixtures['fixture_set_hash']} != {FROZEN_N3_FIXTURE_SET_HASH}"
        )
    if canonical_hash(fixtures) != canonical_hash(published):
        raise V13BuildError(
            "the derived N3 fixture authority differs from the 1.3.1 published "
            "bytes"
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
                "identical_to_v131": True,
            }
        )

    material = {
        "schema_version": "n3-fixture-equality-proof/1.3.2",
        "method": (
            "Compare the derived fixture authority with the published 1.3.1 "
            "document field by field, then compare every per-fixture request "
            "hash individually. The aggregate hash alone is not the proof."
        ),
        "fixture_set_hash": fixtures["fixture_set_hash"],
        "fixture_set_hash_unchanged": True,
        "fixture_count": len(rows),
        "fixtures_identical_to_v131": True,
        "construct_selections_unchanged": True,
        "per_fixture": rows,
        "counts_by_n3_split": dict(fixtures["counts_by_n3_split"]),
        "split_sequencing_unchanged": (
            fixtures["safety_smoke_fixture_count"] == 1
            and fixtures["core_fixture_count"] == 6
            and fixtures["held_out_fixture_count"] == 3
        ),
    }
    if not material["split_sequencing_unchanged"]:
        raise V13BuildError("the accepted N3 1/6/3 split sequencing moved")
    return {**material, "proof_hash": canonical_hash(material)}


def p06_stage_boundary_v132(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    semantics: Mapping[str, Any],
) -> dict[str, Any]:
    """The 1.3.1 P06 boundary re-bound to the version-correct claim."""

    from .semantic_benchmark_v131 import p06_stage_boundary_v131

    base = p06_stage_boundary_v131(build, n3_axis, fixtures)
    material = {
        key: value
        for key, value in base.items()
        if key
        not in {
            "stage_boundary_hash",
            "n3_provider_authority_inventory",
            "n3_provider_authority_fully_bound",
            "n3_authority_inventory",
            "n3_authority_fully_bound_in_p06_boundary",
            "supersedes_v130_p06_boundary",
        }
    }
    published = _json(V131_REPORT_ROOT / "stage_boundaries.json")
    material.update(
        {
            "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "boundary_status": "NEW_IN_V132",
            "new_because": (
                "The semantic qualification claim is rebound to the active "
                "benchmark version, so its material hash changed and this "
                "boundary must change with it."
            ),
            # --- the rebound claim
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
                "claim_semantics_changed_from_v131"
            ],
            # --- N3 material, carried forward unchanged and proved so
            "n3_construct_selection_semantics_version": semantics["schema_version"],
            "n3_construct_selection_semantics_hash": semantics["semantics_hash"],
            "n3_provider_fixture_set_hash_unchanged_from_v131": True,
        }
    )
    material["dependency_inventory"] = [
        *base["dependency_inventory"],
        "P06 semantic qualification claim applicability metadata",
        "N3 construct-selection semantics",
    ]
    boundary = {**material, "stage_boundary_hash": canonical_hash(material)}

    if boundary["stage_boundary_hash"] == published["stage_boundary_hashes"]["P06"]:
        raise V13BuildError(
            "the 1.3.2 P06 boundary reproduces the 1.3.1 hash; the rebound claim "
            "was not actually bound"
        )
    if boundary["n3_provider_fixture_set_hash"] != FROZEN_N3_FIXTURE_SET_HASH:
        raise V13BuildError("the P06 boundary no longer binds the frozen fixture set")
    boundary["supersedes_v131_p06_boundary"] = published["stage_boundary_hashes"]["P06"]
    boundary["n3_provider_authority_inventory"] = list(
        base["n3_provider_authority_inventory"]
    )
    boundary["n3_provider_authority_fully_bound"] = True
    return boundary


def v131_stage_change_proof(build: V13Build, stage: str) -> dict[str, Any]:
    """Prove component by component whether a stage's 1.3.1 material moved."""

    from .semantic_benchmark_v131 import v130_stage_change_proof

    published = _json(V131_REPORT_ROOT / "stage_boundaries.json")
    frozen_hash = published["stage_boundary_hashes"][stage]
    inner = v130_stage_change_proof(build, stage)
    material = {
        "schema_version": "semantic-benchmark-stage-change-proof/1.3.2",
        "stage": stage,
        "from_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "method": (
            "1.3.1 carried this stage's boundary forward unchanged, so the same "
            "reconstruction that justified that carry-forward is re-executed "
            "here and compared with the hash 1.3.1 published."
        ),
        "components": inner["components"],
        "component_count": len(inner["components"]),
        "changed_components": list(inner["changed_components"]),
        "v132_reconstructed_boundary_hash": inner["v131_reconstructed_boundary_hash"],
        "v131_frozen_boundary_hash": frozen_hash,
        "stage_local_material_changed": (
            bool(inner["changed_components"])
            or inner["v131_reconstructed_boundary_hash"] != frozen_hash
        ),
    }
    return {**material, "proof_hash": canonical_hash(material)}


def carried_forward_stage_boundary_v132(build: V13Build, stage: str) -> dict[str, Any]:
    """Carry a 1.3.1 stage boundary forward, only on a passing change proof."""

    proof = v131_stage_change_proof(build, stage)
    if proof["stage_local_material_changed"]:
        raise V13BuildError(
            f"{stage} material changed between 1.3.1 and 1.3.2 "
            f"({proof['changed_components']}); it needs a new boundary"
        )
    published = _json(V131_REPORT_ROOT / "stage_boundaries.json")
    boundary = dict(published["stages"][stage])
    boundary["boundary_status"] = "CARRIED_FORWARD_FROM_V131"
    boundary["carried_forward_from_benchmark_version"] = SEMANTIC_BENCHMARK_V131_VERSION
    boundary["carry_forward_is_valid_because"] = (
        "Every component of this stage's 1.3.1 boundary material was "
        "reconstructed from 1.3.2 authority and reproduced exactly, and the "
        "reconstruction hashes to the frozen 1.3.1 boundary hash. This stage "
        "binds no semantic qualification claim, so rebinding the claim cannot "
        "reach it."
    )
    boundary["v132_change_proof_hash"] = proof["proof_hash"]
    boundary["v132_change_proof"] = proof
    boundary["stage_boundary_hash"] = published["stage_boundary_hashes"][stage]
    return boundary


def stage_boundaries_v132(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    semantics: Mapping[str, Any],
) -> dict[str, Any]:
    boundaries: dict[str, dict[str, Any]] = {
        "P06": p06_stage_boundary_v132(build, n3_axis, fixtures, claim, semantics)
    }
    for stage in ("P04", "P07", "P09", "PLANNER"):
        boundaries[stage] = carried_forward_stage_boundary_v132(build, stage)

    missing = sorted(set(ACTIVE_BENCHMARK_STAGES) - set(boundaries))
    if missing:
        raise V13BuildError(f"1.3.2 published no stage boundary for: {missing}")

    published = _json(V131_REPORT_ROOT / "stage_boundaries.json")
    statuses = {
        stage: value["boundary_status"] for stage, value in sorted(boundaries.items())
    }
    for stage, status in statuses.items():
        same = (
            boundaries[stage]["stage_boundary_hash"]
            == published["stage_boundary_hashes"][stage]
        )
        if status == "CARRIED_FORWARD_FROM_V131" and not same:
            raise V13BuildError(f"{stage} claims carry-forward but its hash moved")
        if status == "NEW_IN_V132" and same:
            raise V13BuildError(
                f"{stage} claims a new boundary but reproduces the 1.3.1 hash"
            )

    material = {
        "schema_version": "semantic-benchmark-stage-boundaries/1.3.2",
        "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "previous_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "silent_carry_forward_permitted": False,
        "recomputation_without_a_change_is_a_defect": True,
        "stages": dict(sorted(boundaries.items())),
        "stage_boundary_hashes": {
            stage: value["stage_boundary_hash"]
            for stage, value in sorted(boundaries.items())
        },
        "boundary_status_by_stage": statuses,
        "new_boundary_stages": sorted(
            stage for stage, status in statuses.items() if status == "NEW_IN_V132"
        ),
        "carried_forward_stages": sorted(
            stage
            for stage, status in statuses.items()
            if status == "CARRIED_FORWARD_FROM_V131"
        ),
        "v131_stage_boundary_hashes": dict(published["stage_boundary_hashes"]),
    }
    return {**material, "stage_boundaries_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART E -- protocol, global boundary, candidate matrix
# --------------------------------------------------------------------------


def benchmark_boundary_v132(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    semantics: Mapping[str, Any],
) -> dict[str, Any]:
    from .semantic_benchmark_v131 import benchmark_boundary_v131

    base = benchmark_boundary_v131(build, n3_axis, fixtures)
    boundaries = stage_boundaries_v132(build, n3_axis, fixtures, claim, semantics)
    material = {
        key: value for key, value in base.items() if key != "benchmark_boundary_hash"
    }
    shared = dict(material["shared_benchmark_authority"])
    shared["benchmark_version"] = SEMANTIC_BENCHMARK_V132_VERSION
    shared["semantic_qualification_claim_hash"] = claim["claim_hash"]
    shared["accepted_rate_bars_changed_from_v131"] = False
    shared.pop("accepted_rate_bars_changed_from_v130", None)
    aggregation = dict(material["cross_stage_aggregation_authority"])
    aggregation["benchmark_version"] = SEMANTIC_BENCHMARK_V132_VERSION
    material.update(
        {
            "boundary_format": BENCHMARK_BOUNDARY_FORMAT_V132,
            "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "previous_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "previous_version_status": V131_STATUS,
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
            "n3_construct_selection_semantics_hash": semantics["semantics_hash"],
        }
    )
    material["documented_dependencies"] = [
        *base["documented_dependencies"],
        "N3 construct-selection semantics",
    ]
    return {**material, "benchmark_boundary_hash": canonical_hash(material)}


def candidate_matrix_v132(
    build: V13Build, *, benchmark_boundary_hash: str
) -> dict[str, Any]:
    """Candidate identities unchanged; the hash moves with what it binds."""

    from .semantic_benchmark_v131 import candidate_matrix_v131

    base = candidate_matrix_v131(build, benchmark_boundary_hash=benchmark_boundary_hash)
    v131 = _json(V131_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    material = {
        key: value for key, value in base.items() if key != "candidate_matrix_hash"
    }
    material.update(
        {
            "schema_version": CANDIDATE_MATRIX_VERSION_V132,
            "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "protocol_version": PROTOCOL_VERSION_V132,
            "candidate_identities_changed_from_v131": False,
            "carried_candidate_identity_hash": canonical_hash(v131["candidates"]),
            "new_hash_reason": (
                "The candidate identities did not change and are proved "
                "byte-identical to 1.3.1. The matrix hash moves because it binds "
                "phase9-qualification-protocol/1.3.2 and the 1.3.2 global "
                "boundary, both of which changed when the semantic qualification "
                "claim was rebound to the active version."
            ),
        }
    )
    material.pop("candidate_identities_changed_from_v130", None)
    if material["candidates"] != v131["candidates"]:
        raise V13BuildError(
            "candidate identities must carry forward byte-identically from 1.3.1"
        )
    return {**material, "candidate_matrix_hash": canonical_hash(material)}


def qualification_protocol_v132(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    semantics: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
) -> dict[str, Any]:
    """The 1.3.1 protocol with its current claim naming the active version."""

    from .semantic_benchmark_v131 import qualification_protocol_v131

    base = qualification_protocol_v131(
        build,
        n3_axis,
        fixtures,
        benchmark_boundary=benchmark_boundary,
        candidate_matrix=candidate_matrix,
        call_budget=call_budget,
    )
    v131 = _json(V131_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    material = {
        key: value for key, value in base.items() if key != "protocol_boundary_hash"
    }
    material.update(
        {
            "schema_version": PROTOCOL_VERSION_V132,
            "protocol_version": PROTOCOL_VERSION_V132,
            "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "previous_protocol_version": v131["protocol_version"],
            "reason_for_new_version": [
                "the semantic qualification claim and its limitations now name "
                "the benchmark version they apply to",
                "the claim material hash changed",
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
            "semantic_qualification_semantics_changed_from_v131": claim[
                "claim_semantics_changed_from_v131"
            ],
            "qualified_support_statuses": list(claim["qualified_support_statuses"]),
            "excluded_support_statuses": list(claim["excluded_support_statuses"]),
            "n3_construct_selection_semantics_hash": semantics["semantics_hash"],
            "n3_construct_selection_rule_kind": semantics["rule_kind"],
        }
    )
    # Everything mechanical must be identical to 1.3.1.
    for key in ("semantic_gates", "n3_gates", "ordering", "adjudication_protocol_hash"):
        if material[key] != v131[key]:
            raise V13BuildError(f"{key} may not change in 1.3.2")
    if material["call_budget_hash"] != v131["call_budget_hash"]:
        raise V13BuildError(
            "the call budget binds no claim, protocol or global value, so its "
            "hash may not change in 1.3.2"
        )
    return {**material, "protocol_boundary_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART C -- no stale current-version claims
# --------------------------------------------------------------------------

#: Fields that carry a *current* claim or limitation.  A superseded version
#: named in one of these is the defect 1.3.2 exists to repair.
CURRENT_CLAIM_FIELDS: frozenset[str] = frozenset(
    {
        "claim",
        "semantic_qualification_claim",
        "semantic_qualification_limitations",
        "semantic_claim_limitations",
        "limitations",
        "uncertain_coverage_gate",
    }
)

#: Path segments where naming a superseded version is legitimate, because the
#: field exists to record history or provenance rather than to make a claim.
HISTORICAL_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        "previous_version",
        "previous_version_status",
        "from_version",
        "to_version",
        "chain",
        "historical_claim_lineage",
        "supersedes_claim_binding_from",
        "supersedes_v131_p06_boundary",
        "supersedes_v130_p06_boundary",
        "supersedes",
        "carried_forward_from",
        "carried_forward_from_benchmark_version",
        "carry_forward_is_valid_because",
        "v130_stage_boundary_hashes",
        "v131_stage_boundary_hashes",
        "v130_status",
        "v131_status",
        "v130_preserved",
        "v131_preserved",
        "v131_change_proof",
        "v132_change_proof",
        "change_proof",
        "v130_frozen_boundary_hash",
        "v131_frozen_boundary_hash",
        "previous_protocol_version",
        "republished_unchanged",
        "republished_unchanged_hashes",
        "originating_version",
        "inherited_unchanged",
        "new_in_v131",
        "new_in_v132",
        "replaced",
        "results_firewall",
        "reason_for_new_version",
        "new_hash_reason",
        "lineage",
        "what_changed",
        "why_a_new_hash",
        "defect",
        "carried_forward_artifacts",
        "fixtures_identical_to_v131",
        "method",
        "published_separately_because",
        "n3_provider_fixture_set_hash_unchanged_from_v131",
        "semantic_qualification_supersedes_binding_from",
        "semantic_qualification_supersedes_claim_binding_from",
        "candidate_identities_changed_from_v131",
        "semantic_qualification_semantics_changed_from_v131",
        "claim_semantics_changed_from_v131",
        "accepted_rate_bars_changed_from_v131",
        "bars_changed_from_v12",
        "bars_changed_from_v130",
        "boundary_status",
        "new_because",
        # The scan report is a record of observations about version mentions.
        # Its evidence fields quote the very strings it scanned for, so
        # scanning them is a category error: exempt them by construction and
        # say so in the artifact rather than letting the scan flag itself.
        "superseded_versions_scanned_for",
        "permitted_mentions",
        "violations",
        "rule",
    }
)

_SUPERSEDED_VERSION = re.compile(r"semantic-benchmark/1\.3\.[01]\b")


def _walk_strings(node: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_strings(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_strings(value, (*path, f"[{index}]"))
    elif isinstance(node, str):
        yield path, node


def stale_claim_scan(
    package: Mapping[str, Mapping[str, Any]],
    *,
    republished_unchanged: Mapping[str, str],
    deferred: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fail closed if a current claim or limitation names a superseded version.

    A superseded version may still appear -- lineage would be useless otherwise
    -- but only inside a field whose job is history or provenance, or inside an
    artifact republished byte-identically from an earlier version and declared
    as such.  Everything else is a current statement and must name 1.3.2.
    """

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
            in_claim_field = any(
                segment in CURRENT_CLAIM_FIELDS for segment in path
            )
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
            "a current 1.3.2 authority statement names a superseded benchmark "
            f"version: {violations}"
        )

    material = {
        "schema_version": "semantic-benchmark-stale-claim-scan/1.3.2",
        "active_benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "superseded_versions_scanned_for": ["semantic-benchmark/1.3.0", "semantic-benchmark/1.3.1"],
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
            "exist, which raises on any violation. The build cannot publish "
            "while that pass fails."
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

#: Artifacts 1.3.2 republishes byte-identically from 1.3.1.  Their hashes must
#: not move, so they are copied rather than regenerated with a new version
#: stamp; the lineage and the stale-claim scan both know they are republished.
REPUBLISHED_FROM_V131: Mapping[str, str] = {
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": (
        "phase9/n3_provider_fixtures.json"
    ),
    f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": (
        "phase9/n3_contractual_safety_axis.json"
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


def _v131_source(relative: str) -> Path:
    tail = REPUBLISHED_FROM_V131[relative]
    root = V131_DEFINITION_ROOT if relative.startswith(DEFINITION_ROOT) else V131_REPORT_ROOT
    return root / tail


def republished_documents() -> dict[str, dict[str, Any]]:
    """Load the 1.3.1 bytes for every artifact 1.3.2 republishes unchanged."""

    return {
        relative: _json(_v131_source(relative)) for relative in REPUBLISHED_FROM_V131
    }


def lineage_v132(build: V13Build) -> dict[str, Any]:
    v131_lineage = _json(V131_REPORT_ROOT / "lineage.json")
    republished = {
        relative: {
            "originating_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "source_path": _v131_source(relative)
            .relative_to(REPOSITORY_ROOT)
            .as_posix(),
            "bytes_identical": True,
            "reason": (
                "Its complete material is unchanged, so republishing it with a "
                "new version stamp would move a hash without moving a meaning."
            ),
        }
        for relative in sorted(REPUBLISHED_FROM_V131)
    }
    material = {
        "schema_version": "semantic-benchmark-lineage/1.3.2",
        "from_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V132_VERSION,
        "chain": [
            {
                "version": "semantic-benchmark/1.2.0",
                "status": "IMMUTABLE_HISTORICAL_AUTHORITY",
            },
            {
                "version": "semantic-benchmark/1.3.0",
                "status": V130_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
                "bytes_modified_by_v132": False,
            },
            {
                "version": SEMANTIC_BENCHMARK_V131_VERSION,
                "status": V131_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
                "superseded_because": [
                    "its current semantic qualification claim and UNCERTAIN "
                    "limitation named semantic-benchmark/1.3.0, a superseded "
                    "version, while the artifacts carrying them were stamped "
                    "1.3.1"
                ],
                "bytes_modified_by_v132": False,
            },
            {
                "version": SEMANTIC_BENCHMARK_V132_VERSION,
                "status": V132_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
            },
        ],
        "is_a_corpus_change": False,
        "is_a_semantic_product_decision_change": False,
        "is_a_pre_execution_authority_binding_repair": True,
        "no_result_existed_when_this_repair_was_made": True,
        "v131_lineage_hash": v131_lineage["lineage_hash"],
        "replaced": {
            "phase9/qualification_protocol.json": "current claim now names 1.3.2",
            "phase9/candidate_matrix.json": (
                "identities unchanged; binds the new protocol and boundary"
            ),
        },
        "new_in_v132": {
            "phase9/semantic_qualification_claim.json": (
                "the version-correct claim with explicit applicability metadata"
            ),
            "phase9/construct_selection_semantics.json": (
                "what the N3 sampling rule does and does not assert"
            ),
            "phase9/n3_fixture_equality_proof.json": (
                "field-by-field proof that no N3 fixture byte moved"
            ),
            "phase9/stale_claim_scan.json": (
                "the executed scan for current statements naming a superseded "
                "version"
            ),
        },
        "carried_forward_artifacts": republished,
        "carried_forward_artifact_count": len(republished),
        "silent_carry_forward_permitted": False,
    }
    return {**material, "lineage_hash": canonical_hash(material)}


def pre_results_freeze_v132(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    claim: Mapping[str, Any],
    semantics: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    qualification_protocol: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    lineage: Mapping[str, Any],
    fixture_equality: Mapping[str, Any],
    stale_scan: Mapping[str, Any],
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
    material = {
        key: value for key, value in base.items() if key != "freeze_material_hash"
    }
    material.update(
        {
            "schema_version": "phase9-pre-results-instrument-freeze/1.3.2",
            "phase": "9B.8B",
            "benchmark_version": SEMANTIC_BENCHMARK_V132_VERSION,
            "previous_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "previous_version_status": V131_STATUS,
            "status": V132_STATUS,
            "purpose": (
                "Freeze the U3 + N3 pre-execution instrument with its semantic "
                "qualification claim bound to the version it applies to, before "
                "any candidate result exists."
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
            "semantic_qualification_semantics_changed_from_v131": claim[
                "claim_semantics_changed_from_v131"
            ],
            "n3_construct_selection_semantics_hash": semantics["semantics_hash"],
            "n3_fixture_equality_proof_hash": fixture_equality["proof_hash"],
            "n3_provider_fixture_set_hash_unchanged_from_v131": True,
            "stale_claim_scan_hash": stale_scan["scan_hash"],
            "stale_claim_violation_count": stale_scan["violation_count"],
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
            "v131_preserved": {"v131_bytes_modified": False, "status": V131_STATUS},
            "stop_condition": (
                "SEMANTIC_BENCHMARK_V1_3_2_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT"
            ),
        }
    )
    return {**material, "freeze_material_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART G -- the self-hash registry, carried forward in design
# --------------------------------------------------------------------------

SELF_MATERIAL_HASH_FIELD: Mapping[str, str | None] = {
    f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": "protocol_boundary_hash",
    f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": "candidate_matrix_hash",
    f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": "claim_hash",
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
    f"{REPORT_ROOT}/phase9/stale_claim_scan.json": "scan_hash",
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


def v132_package(build: V13Build) -> dict[str, dict[str, Any]]:
    """Every generated 1.3.2 document, keyed by repository-relative path."""

    from .n3_provider_fixtures import n3_provider_fixture_authority
    from .semantic_benchmark_v131 import call_budget_v131
    # 1.3.2 republished the 1.3.1 N3 axis byte-identically.  Preserve that
    # historical authority when current executable N3 source changes.
    n3_axis = _json(
        V131_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    )
    fixtures = n3_provider_fixture_authority(build.corpus_root)
    fixture_equality = n3_fixture_equality_proof(fixtures)
    claim = semantic_qualification_claim_v132(build)
    semantics = construct_selection_semantics()
    boundaries = stage_boundaries_v132(build, n3_axis, fixtures, claim, semantics)
    global_boundary = benchmark_boundary_v132(
        build, n3_axis, fixtures, claim, semantics
    )
    budget = call_budget_v131(build, fixtures)
    matrix = candidate_matrix_v132(
        build, benchmark_boundary_hash=global_boundary["benchmark_boundary_hash"]
    )
    protocol = qualification_protocol_v132(
        build,
        n3_axis,
        fixtures,
        claim,
        semantics,
        benchmark_boundary=global_boundary,
        candidate_matrix=matrix,
        call_budget=budget,
    )
    lineage = lineage_v132(build)

    package = {
        **republished_documents(),
        f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": claim,
        f"{DEFINITION_ROOT}/phase9/construct_selection_semantics.json": semantics,
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": protocol,
        f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": matrix,
        f"{REPORT_ROOT}/lineage.json": lineage,
        f"{REPORT_ROOT}/stage_boundaries.json": boundaries,
        f"{REPORT_ROOT}/benchmark_boundary.json": global_boundary,
        f"{REPORT_ROOT}/phase9/n3_fixture_equality_proof.json": fixture_equality,
    }
    # The scan runs over everything authored so far, then over itself and the
    # freeze once they exist -- neither can name a superseded version outside a
    # historical field either.
    stale_scan = stale_claim_scan(
        package,
        republished_unchanged=REPUBLISHED_FROM_V131,
        deferred={
            f"{REPORT_ROOT}/phase9/stale_claim_scan.json": (
                "this report cannot contain its own hash"
            ),
            f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": (
                "the freeze binds this report's hash"
            ),
        },
    )
    freeze = pre_results_freeze_v132(
        build,
        n3_axis,
        fixtures,
        claim,
        semantics,
        benchmark_boundary=global_boundary,
        stage_boundaries=boundaries,
        qualification_protocol=protocol,
        candidate_matrix=matrix,
        call_budget=budget,
        lineage=lineage,
        fixture_equality=fixture_equality,
        stale_scan=stale_scan,
    )
    package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"] = stale_scan
    package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"] = freeze
    stale_claim_scan(package, republished_unchanged=REPUBLISHED_FROM_V131)
    return package
