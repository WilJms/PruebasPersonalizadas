"""``semantic-benchmark/1.3.1`` -- the N3 provider-call and hash-manifest repair.

``semantic-benchmark/1.3.0`` is not edited.  It is marked
``SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED`` and its bytes
stay exactly as published: no provider or adjudicator ever ran against it, so
superseding it is an instrumentation repair, not result-driven tuning.

Two defects are repaired, and nothing else moves.

**The N3 provider call shape.**  v1.3.0 correctly concluded that N3 needs its
own P06 provider calls but froze no request for them.  A gate whose exposure is
decided at run time can be changed after a result is seen, so v1.3.1 freezes the
exact provider-facing P06 fixture for each of the ten exposures and binds that
authority into the P06 stage boundary.

**The hash manifest.**  v1.3.0 chose an artifact's "internal material hash" by
scanning for the first field whose name ended in ``_hash``.  For the candidate
matrix and the qualification protocol that found a *dependency* --
``benchmark_boundary_hash`` -- and reported it as the document's own hash.
v1.3.1 replaces the heuristic with an explicit per-path registry, and validates
every entry against the property that actually defines a self hash:
``canonical_hash(document minus the field) == document[field]``.  A dependency
hash cannot satisfy that, so a recurrence fails the build rather than the
reader.

Nothing here executes a provider or an adjudicator, resolves a credential,
constructs a real transport, reads a candidate outcome or refreshes pricing.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_hash
from .n3_provider_fixtures import (
    N3_CONSTRUCT_SELECTION_RULE,
    N3_PROVIDER_FIXTURES_VERSION,
    n3_provider_fixture_authority,
    noisy_disposition_census,
)
from .p06_n3_protocol import (
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_SAFETY_SMOKE,
)
from .phase9_protocol import SEMANTIC_K, SEMANTIC_STAGES, STAGE_REASONING_LADDER
from .semantic_benchmark import ACTIVE_BENCHMARK_STAGES, DEFAULT_CORPUS_ROOT
from .semantic_benchmark_v13 import (
    REPOSITORY_ROOT,
    SEMANTIC_BENCHMARK_V13_VERSION,
    V13Build,
    V13BuildError,
    build_v13,
    lineage_report,
    p06_instrument_report,
    result_axis_separation,
    semantic_qualification_claim,
)
from .semantic_benchmark_v13_boundary import (
    p06_stage_boundary_v13,
    p07_stage_boundary_v13,
    split_partition_authority_v13,
    stage_change_proof,
)


SEMANTIC_BENCHMARK_V131_VERSION = "semantic-benchmark/1.3.1"
BENCHMARK_BOUNDARY_FORMAT_V131 = "semantic-benchmark-boundary/1.3.1"
STAGE_BOUNDARY_FORMAT = "semantic-benchmark-stage-boundary/1.0.0"
PROTOCOL_VERSION_V131 = "phase9-qualification-protocol/1.3.1"
CANDIDATE_MATRIX_VERSION_V131 = "phase9-candidate-matrix/1.3.1"
CALL_BUDGET_VERSION_V131 = "phase9-call-budget/1.3.1"

V130_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3"
V130_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3"
DEFINITION_ROOT = "evaluation/semantic_benchmark/v1_3_1"
REPORT_ROOT = "reports/semantic_benchmark/v1_3_1"

V130_STATUS = "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
V131_STATUS = "PREEXECUTION_FREEZE_CANDIDATE"

#: Stages whose v1.3.0 boundary may be carried forward if it provably did not
#: move.  P06 is excluded by construction: it gains the provider-fixture
#: authority.
CARRY_FORWARD_CANDIDATE_STAGES: tuple[str, ...] = ("P04", "P07", "P09", "PLANNER")

#: The N3 provider-call authority the v1.3.1 P06 boundary must additionally
#: bind.  Checked for presence, so an added dependency cannot be forgotten.
N3_PROVIDER_AUTHORITY_INVENTORY: tuple[str, ...] = (
    "n3_provider_fixture_schema",
    "n3_provider_fixture_set_hash",
    "n3_provider_fixture_input_hashes",
    "n3_construct_selection_authority",
    "n3_construct_selection_independence_hash",
    "n3_provider_fixture_builder_version",
    "n3_provider_fixture_builder_source_hash",
    "n3_provider_request_construction_source_hash",
    "n3_provider_alias_envelope_schema_boundary",
    "n3_provider_materializer_boundary",
    "n3_provider_production_representativeness_hash",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


# --------------------------------------------------------------------------
# PART F -- the P06 boundary gains the provider-call authority
# --------------------------------------------------------------------------


def p06_stage_boundary_v131(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
) -> dict[str, Any]:
    """The v1.3.0 P06 boundary plus everything the N3 provider calls depend on.

    A stage boundary exists so that a change to anything a result depended on
    invalidates it.  Once N3 buys its own calls, the request those calls send is
    exactly such a thing, so it belongs here.
    """

    base = p06_stage_boundary_v13(build, n3_axis)
    # The v1.3.0 builder appends two descriptive keys after hashing; drop them
    # so the v1.3.1 material is a clean superset of the v1.3.0 material.
    material = {
        key: value
        for key, value in base.items()
        if key
        not in {
            "stage_boundary_hash",
            "n3_authority_inventory",
            "n3_authority_fully_bound_in_p06_boundary",
        }
    }
    material.update(
        {
            "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "boundary_status": "NEW_IN_V131",
            "new_because": (
                "N3 buys its own P06 provider calls, so the exact provider "
                "request for each of the ten exposures is qualification "
                "authority and must invalidate this boundary when it moves."
            ),
            "n3_provider_fixture_schema": fixtures["schema_version"],
            "n3_provider_fixture_set_hash": fixtures["fixture_set_hash"],
            "n3_provider_fixture_count": fixtures["fixture_count"],
            "n3_provider_fixture_input_hashes": dict(
                sorted(fixtures["fixture_input_hashes"].items())
            ),
            "n3_construct_selection_rule": fixtures["construct_selection_rule"],
            "n3_construct_selection_authority": fixtures[
                "construct_selection_authority"
            ],
            "n3_construct_selection_order_key": list(
                fixtures["construct_selection_order_key"]
            ),
            "n3_construct_selection_independence_hash": fixtures[
                "construct_selection_independence_hash"
            ],
            "n3_provider_fixture_builder_version": fixtures[
                "fixture_builder_version"
            ],
            "n3_provider_fixture_builder_source_hash": fixtures[
                "fixture_builder_source_hash"
            ],
            "n3_provider_request_construction_source_hash": fixtures[
                "request_construction_source_hash"
            ],
            "n3_provider_alias_envelope_schema_boundary": fixtures[
                "alias_envelope_schema_boundary"
            ],
            "n3_provider_materializer_boundary": fixtures["materializer_boundary"],
            "n3_provider_production_representativeness_hash": fixtures[
                "production_representativeness_hash"
            ],
            "n3_noisy_disposition_census_hash": fixtures[
                "noisy_disposition_census_hash"
            ],
        }
    )
    material["dependency_inventory"] = [
        *base["dependency_inventory"],
        "N3 provider fixture set",
        "N3 provider per-exposure request hashes",
        "N3 construct-selection authority",
        "N3 provider request construction source",
        "N3 provider fixture builder",
        "N3 provider production-representativeness proof",
    ]
    boundary = {**material, "stage_boundary_hash": canonical_hash(material)}

    unbound = sorted(set(N3_PROVIDER_AUTHORITY_INVENTORY) - set(boundary))
    if unbound:
        raise V13BuildError(
            "the v1.3.1 P06 boundary must bind every N3 provider-call "
            f"authority; unbound: {unbound}"
        )
    published = _json(V130_REPORT_ROOT / "stage_boundaries.json")
    if boundary["stage_boundary_hash"] == published["stage_boundary_hashes"]["P06"]:
        raise V13BuildError(
            "the v1.3.1 P06 boundary reproduces the v1.3.0 hash; the provider "
            "authority was not actually bound"
        )
    boundary["n3_provider_authority_inventory"] = list(
        N3_PROVIDER_AUTHORITY_INVENTORY
    )
    boundary["n3_provider_authority_fully_bound"] = True
    boundary["supersedes_v130_p06_boundary"] = published["stage_boundary_hashes"]["P06"]
    return boundary


# --------------------------------------------------------------------------
# PART J -- carry forward only what provably did not move
# --------------------------------------------------------------------------


def v130_stage_change_proof(build: V13Build, stage: str) -> dict[str, Any]:
    """Prove component by component whether a stage's v1.3.0 material moved.

    P07 had a boundary computed fresh in v1.3.0, so its material is recomputed
    with the v1.3.0 builder and compared field by field with what was published.
    P04, P09 and PLANNER carried their v1.2 boundary through v1.3.0 unchanged,
    so the v1.2 reconstruction is the proof for them too, and the published
    v1.3.0 hash must still equal it.
    """

    published = _json(V130_REPORT_ROOT / "stage_boundaries.json")
    frozen = published["stages"][stage]
    frozen_hash = published["stage_boundary_hashes"][stage]

    if stage == "P07":
        recomputed = p07_stage_boundary_v13(build)
        method = "RECOMPUTE_THE_V130_P07_BOUNDARY_AND_COMPARE_FIELD_BY_FIELD"
        components = []
        changed: list[str] = []
        for key in sorted(k for k in recomputed if k != "stage_boundary_hash"):
            value = recomputed[key]
            frozen_value = frozen.get(key, "<<ABSENT_FROM_V130_BOUNDARY>>")
            equal = value == frozen_value
            if not equal:
                changed.append(key)
            components.append(
                {"component": key, "v131_recomputed": value, "v130_frozen": frozen_value, "equal": equal}
            )
        recomputed_hash = recomputed["stage_boundary_hash"]
    else:
        inner = stage_change_proof(build, stage)
        method = (
            "RECONSTRUCT_THE_V12_MATERIAL_THE_V130_BOUNDARY_CARRIED_AND_COMPARE"
        )
        components = inner["components"]
        changed = list(inner["changed_components"])
        recomputed_hash = inner["v13_reconstructed_boundary_hash"]

    material = {
        "schema_version": "semantic-benchmark-stage-change-proof/1.3.1",
        "stage": stage,
        "from_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "method": method,
        "components": components,
        "component_count": len(components),
        "changed_components": changed,
        "v131_reconstructed_boundary_hash": recomputed_hash,
        "v130_frozen_boundary_hash": frozen_hash,
        "stage_local_material_changed": bool(changed) or recomputed_hash != frozen_hash,
    }
    return {**material, "proof_hash": canonical_hash(material)}


def carried_forward_stage_boundary_v131(build: V13Build, stage: str) -> dict[str, Any]:
    """Carry a v1.3.0 stage boundary forward, only on a passing change proof."""

    proof = v130_stage_change_proof(build, stage)
    if proof["stage_local_material_changed"]:
        raise V13BuildError(
            f"{stage} material changed between v1.3.0 and v1.3.1 "
            f"({proof['changed_components']}); it needs a new boundary"
        )
    published = _json(V130_REPORT_ROOT / "stage_boundaries.json")
    boundary = dict(published["stages"][stage])
    boundary["boundary_status"] = "CARRIED_FORWARD_FROM_V130"
    boundary["carried_forward_from_benchmark_version"] = SEMANTIC_BENCHMARK_V13_VERSION
    boundary["carry_forward_is_valid_because"] = (
        "Every component of this stage's v1.3.0 boundary material was "
        "reconstructed from v1.3.1 authority and reproduced exactly, and the "
        "reconstruction hashes to the frozen v1.3.0 boundary hash. Nothing this "
        "boundary binds moved, so recomputing it would change the hash without "
        "changing its meaning."
    )
    boundary["v131_change_proof_hash"] = proof["proof_hash"]
    boundary["v131_change_proof"] = proof
    boundary["stage_boundary_hash"] = published["stage_boundary_hashes"][stage]
    return boundary


def stage_boundaries_v131(
    build: V13Build, n3_axis: Mapping[str, Any], fixtures: Mapping[str, Any]
) -> dict[str, Any]:
    """One boundary per active stage, each explicitly new or carried forward."""

    boundaries: dict[str, dict[str, Any]] = {
        "P06": p06_stage_boundary_v131(build, n3_axis, fixtures)
    }
    for stage in CARRY_FORWARD_CANDIDATE_STAGES:
        boundaries[stage] = carried_forward_stage_boundary_v131(build, stage)

    missing = sorted(set(ACTIVE_BENCHMARK_STAGES) - set(boundaries))
    if missing:
        raise V13BuildError(f"v1.3.1 published no stage boundary for: {missing}")

    published = _json(V130_REPORT_ROOT / "stage_boundaries.json")
    statuses = {
        stage: value["boundary_status"] for stage, value in sorted(boundaries.items())
    }
    for stage, status in statuses.items():
        same = (
            boundaries[stage]["stage_boundary_hash"]
            == published["stage_boundary_hashes"][stage]
        )
        if status == "CARRIED_FORWARD_FROM_V130" and not same:
            raise V13BuildError(f"{stage} claims carry-forward but its hash moved")
        if status == "NEW_IN_V131" and same:
            raise V13BuildError(
                f"{stage} claims a new boundary but reproduces the v1.3.0 hash"
            )

    material = {
        "schema_version": "semantic-benchmark-stage-boundaries/1.3.1",
        "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "previous_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "silent_carry_forward_permitted": False,
        "recomputation_without_a_change_is_a_defect": True,
        "stages": dict(sorted(boundaries.items())),
        "stage_boundary_hashes": {
            stage: value["stage_boundary_hash"]
            for stage, value in sorted(boundaries.items())
        },
        "boundary_status_by_stage": statuses,
        "new_boundary_stages": sorted(
            stage for stage, status in statuses.items() if status == "NEW_IN_V131"
        ),
        "carried_forward_stages": sorted(
            stage
            for stage, status in statuses.items()
            if status == "CARRIED_FORWARD_FROM_V130"
        ),
        "v130_stage_boundary_hashes": dict(published["stage_boundary_hashes"]),
    }
    return {**material, "stage_boundaries_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART K (boundary half) -- the global v1.3.1 boundary
# --------------------------------------------------------------------------


def benchmark_boundary_v131(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind everything needed to reproduce the v1.3.1 instrument."""

    from .semantic_benchmark_v13 import ACCEPTED_RATE_BAR
    from .semantic_benchmark import PROPERTY_AGGREGATION_RULES, RARE_FAMILY_POLICIES

    boundaries = stage_boundaries_v131(build, n3_axis, fixtures)
    splits = split_partition_authority_v13(build)
    claim = semantic_qualification_claim(build)
    instrument = p06_instrument_report(build)

    material = {
        "boundary_format": BENCHMARK_BOUNDARY_FORMAT_V131,
        "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "previous_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "previous_version_status": V130_STATUS,
        "corpus_package_boundary_hash": build.package_hash,
        "shared_benchmark_authority": {
            "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "corpus_package_boundary_hash": build.package_hash,
            "property_aggregation_rules": PROPERTY_AGGREGATION_RULES,
            "rare_coverage_rules": RARE_FAMILY_POLICIES,
            "accepted_rate_bar_by_split": ACCEPTED_RATE_BAR,
            "accepted_rate_bars_changed_from_v130": False,
            "property_binding_authority_hash": canonical_hash(
                build.derivation.bindings
            ),
            "candidate_scoring_authority_hash": canonical_hash(
                list(build.derivation.scoring_property_ids)
            ),
            "semantic_qualification_claim_hash": claim["claim_hash"],
        },
        "stage_boundaries_hash": boundaries["stage_boundaries_hash"],
        "stage_boundary_hashes": dict(boundaries["stage_boundary_hashes"]),
        "boundary_status_by_stage": dict(boundaries["boundary_status_by_stage"]),
        "split_partition_hash": splits["split_partition_hash"],
        "p06_instrument_hash": instrument["instrument_hash"],
        "semantic_qualification_claim_hash": claim["claim_hash"],
        "semantic_qualification_limitations": list(claim["limitations"]),
        "n3_axis_hash": n3_axis["n3_axis_hash"],
        "n3_provider_fixture_set_hash": fixtures["fixture_set_hash"],
        "n3_provider_fixture_schema": fixtures["schema_version"],
        "n3_axis_is_separate_from_semantic_axis": True,
        "cross_stage_aggregation_authority": {
            "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "case_count": len(build.cases),
            "case_matrix_hash": canonical_hash(
                [
                    {
                        "case_id": item["case_id"],
                        "stage": item["stage"],
                        "split": item["split"],
                    }
                    for item in build.cases
                ]
            ),
            "property_aggregation_rules": PROPERTY_AGGREGATION_RULES,
        },
        "documented_dependencies": [
            "shared benchmark authority",
            "stage boundaries",
            "corpus boundary",
            "split partition authority",
            "cross-stage aggregation/version authority",
            "P06 semantic instrument",
            "P06 semantic qualification claim and limitations",
            "N3 contractual hard-safety axis",
            "N3 provider fixture set",
        ],
    }
    return {**material, "benchmark_boundary_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART G -- the budget, with N3 provider calls derived from the fixture set
# --------------------------------------------------------------------------


def call_budget_v131(
    build: V13Build, fixtures: Mapping[str, Any]
) -> dict[str, Any]:
    """Re-derive every call count.  N3 comes from fixtures, not exposures.

    The distinction matters: an exposure is a submission the corpus tagged, a
    fixture is a request that provably builds.  Budgeting from the exposure
    count would let an exposure without a constructible request quietly cost
    nothing, which is precisely the gap v1.3.0 left.
    """

    from .semantic_benchmark_v13_protocol import (
        N3_ADJUDICATIONS_PER_EXPOSURE,
        _adjudicable_pairs,
    )
    from .phase9_protocol import MAX_TECHNICAL_RETRIES, PASS_QA_SAMPLE_PERCENT

    split_by_case = {item["case_id"]: item["split"] for item in build.cases}
    case_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for case in build.cases:
        case_counts[case["stage"]][case["split"]] += 1
    pairs = _adjudicable_pairs(build)

    # N3 volumes come from the frozen fixture set.
    fixture_rows = fixtures["fixtures"]
    n3_by_split: dict[str, int] = defaultdict(int)
    for row in fixture_rows:
        n3_by_split[row["n3_split"]] += 1
    if sum(n3_by_split.values()) != fixtures["fixture_count"]:
        raise V13BuildError("the N3 fixture split counts do not sum to the fixture set")

    provider_rows: list[dict[str, Any]] = []
    for stage in SEMANTIC_STAGES:
        for split, count in sorted(case_counts[stage].items()):
            for rung in STAGE_REASONING_LADDER[stage]:
                provider_rows.append(
                    {
                        "axis": "SEMANTIC",
                        "stage": stage,
                        "split": split,
                        "reasoning_rung": rung,
                        "side": (
                            "HELD_OUT_CONFIRMATION"
                            if split == "HELD_OUT_CONFIRMATION"
                            else "QUALIFICATION"
                        ),
                        "unit": "CASE_RUN",
                        "volume_source": "CASE_COUNT",
                        "units": count,
                        "k": SEMANTIC_K,
                        "calls_if_this_rung_executes": count * SEMANTIC_K,
                    }
                )
    for split in (N3_SAFETY_SMOKE, N3_CORE, N3_HELD_OUT_CONFIRMATION):
        count = n3_by_split[split]
        for rung in STAGE_REASONING_LADDER["P06"]:
            provider_rows.append(
                {
                    "axis": "CONTRACTUAL_HARD_SAFETY",
                    "stage": "P06",
                    "split": split,
                    "reasoning_rung": rung,
                    "side": (
                        "HELD_OUT_CONFIRMATION"
                        if split == N3_HELD_OUT_CONFIRMATION
                        else "QUALIFICATION"
                    ),
                    "unit": "PROVIDER_FIXTURE_RUN",
                    "volume_source": "EXECUTABLE_FROZEN_N3_PROVIDER_FIXTURE_COUNT",
                    "units": count,
                    "k": SEMANTIC_K,
                    "calls_if_this_rung_executes": count * SEMANTIC_K,
                }
            )

    semantic_adjudication_rows: list[dict[str, Any]] = []
    for stage in SEMANTIC_STAGES:
        for split, count in sorted(pairs.get(stage, {}).items()):
            for rung in STAGE_REASONING_LADDER[stage]:
                first_pass = count * SEMANTIC_K
                semantic_adjudication_rows.append(
                    {
                        "axis": "SEMANTIC",
                        "stage": stage,
                        "split": split,
                        "reasoning_rung": rung,
                        "side": (
                            "HELD_OUT_CONFIRMATION"
                            if split == "HELD_OUT_CONFIRMATION"
                            else "QUALIFICATION"
                        ),
                        "unit": "CASE_PROPERTY_RUN",
                        "observation_units": count,
                        "k": SEMANTIC_K,
                        "first_pass_calls": first_pass,
                        "max_conditional_second_pass_calls": first_pass,
                        "pass_qa_second_pass_floor": -(
                            -first_pass * PASS_QA_SAMPLE_PERCENT // 100
                        ),
                    }
                )

    n3_adjudication_rows: list[dict[str, Any]] = []
    for split in (N3_SAFETY_SMOKE, N3_CORE, N3_HELD_OUT_CONFIRMATION):
        count = n3_by_split[split]
        for rung in STAGE_REASONING_LADDER["P06"]:
            first_pass = count * N3_ADJUDICATIONS_PER_EXPOSURE
            n3_adjudication_rows.append(
                {
                    "axis": "CONTRACTUAL_HARD_SAFETY",
                    "stage": "P06",
                    "split": split,
                    "reasoning_rung": rung,
                    "side": (
                        "HELD_OUT_CONFIRMATION"
                        if split == N3_HELD_OUT_CONFIRMATION
                        else "QUALIFICATION"
                    ),
                    "unit": "PROVIDER_FIXTURE_RUN",
                    "volume_source": "EXECUTABLE_FROZEN_N3_PROVIDER_FIXTURE_COUNT",
                    "observation_units": count,
                    "adjudications_per_fixture_run": N3_ADJUDICATIONS_PER_EXPOSURE,
                    "first_pass_calls": first_pass,
                    "max_conditional_second_pass_calls": first_pass,
                }
            )

    def _sum(rows, key, **filters):
        return sum(
            row[key]
            for row in rows
            if all(row.get(name) == value for name, value in filters.items())
        )

    census = noisy_disposition_census(build.corpus_root)
    material = {
        "schema_version": CALL_BUDGET_VERSION_V131,
        "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "estimate_status": "DERIVED_COUNT_NOT_A_BILL",
        "authorization": "NONE",
        "calls_performed_by_this_task": 0,
        "pricing_refreshed": False,
        "provider_and_adjudicator_budgets_are_never_summed": (
            "They buy different things under different gates. A single figure "
            "would hide which of the two a change moved."
        ),
        "n3_volume_rule": (
            "provider N3 calls = executable frozen N3 provider fixtures x k, "
            "per applicable rung and split. Not derived from exposure_count: an "
            "exposure whose request does not build must not cost nothing."
        ),
        "n3_provider_fixture_set_hash": fixtures["fixture_set_hash"],
        "n3_provider_fixture_count": fixtures["fixture_count"],
        "n3_fixture_counts_by_split": dict(sorted(n3_by_split.items())),
        "n3_exposure_count": census["noisy_exposure_count"],
        "n3_fixture_count_equals_exposure_count": (
            fixtures["fixture_count"] == census["noisy_exposure_count"]
        ),
        "units": {
            "provider_semantic": "CASE_RUN",
            "provider_n3": "PROVIDER_FIXTURE_RUN",
            "semantic_adjudication": "CASE_PROPERTY_RUN",
            "n3_adjudication": "PROVIDER_FIXTURE_RUN",
        },
        "k": SEMANTIC_K,
        "max_technical_retries": MAX_TECHNICAL_RETRIES,
        "pass_qa_sample_percent": PASS_QA_SAMPLE_PERCENT,
        "planner_excluded_from_provider_budget": (
            "PLANNER is deterministic (k=1) and carries no reasoning ladder, so "
            "it is not a provider candidate stage in Phase 9."
        ),
        "n3_provider_calls_are_additional": {
            "n3_rides_existing_semantic_calls": False,
            "noisy_disposition_census_hash": census["census_hash"],
            "noisy_exposure_count": census["noisy_exposure_count"],
            "noisy_with_executable_semantic_route_count": census[
                "noisy_with_executable_semantic_route_count"
            ],
            "noisy_with_p06_property_but_excluded_count": census[
                "noisy_with_p06_property_but_excluded_count"
            ],
            "noisy_with_no_p06_property_count": census[
                "noisy_with_no_p06_property_count"
            ],
            "finding": census["prose"],
        },
        "provider_call_budget": {
            "rows": provider_rows,
            "aggregation_rule": (
                "Qualification-side totals are summed over every rung, the worst "
                "case in which the whole ladder is walked. Held-out confirmation "
                "runs once, for the selected configuration, so its total is one "
                "rung's worth and is never summed over the ladder."
            ),
            "semantic_qualification_side_worst_case_all_rungs": _sum(
                provider_rows, "calls_if_this_rung_executes", axis="SEMANTIC", side="QUALIFICATION"
            ),
            "semantic_qualification_side_lowest_rung_only": _sum(
                provider_rows, "calls_if_this_rung_executes", axis="SEMANTIC", side="QUALIFICATION", reasoning_rung="HIGH"
            ),
            "semantic_held_out_for_one_selected_configuration": _sum(
                provider_rows, "calls_if_this_rung_executes", axis="SEMANTIC", side="HELD_OUT_CONFIRMATION", reasoning_rung="HIGH"
            ),
            "n3_qualification_side_worst_case_all_rungs": _sum(
                provider_rows, "calls_if_this_rung_executes", axis="CONTRACTUAL_HARD_SAFETY", side="QUALIFICATION"
            ),
            "n3_qualification_side_lowest_rung_only": _sum(
                provider_rows, "calls_if_this_rung_executes", axis="CONTRACTUAL_HARD_SAFETY", side="QUALIFICATION", reasoning_rung="HIGH"
            ),
            "n3_held_out_for_one_selected_configuration": _sum(
                provider_rows, "calls_if_this_rung_executes", axis="CONTRACTUAL_HARD_SAFETY", side="HELD_OUT_CONFIRMATION", reasoning_rung="HIGH"
            ),
        },
        "semantic_adjudicator_budget": {
            "rows": semantic_adjudication_rows,
            "first_pass_qualification_side_worst_case_all_rungs": _sum(
                semantic_adjudication_rows, "first_pass_calls", side="QUALIFICATION"
            ),
            "first_pass_qualification_side_lowest_rung_only": _sum(
                semantic_adjudication_rows, "first_pass_calls", side="QUALIFICATION", reasoning_rung="HIGH"
            ),
            "first_pass_held_out_for_one_selected_configuration": _sum(
                semantic_adjudication_rows, "first_pass_calls", side="HELD_OUT_CONFIRMATION", reasoning_rung="HIGH"
            ),
            "max_conditional_second_pass_qualification_side_worst_case_all_rungs": _sum(
                semantic_adjudication_rows, "max_conditional_second_pass_calls", side="QUALIFICATION"
            ),
            "max_conditional_second_pass_held_out_for_one_selected_configuration": _sum(
                semantic_adjudication_rows, "max_conditional_second_pass_calls", side="HELD_OUT_CONFIRMATION", reasoning_rung="HIGH"
            ),
            "second_pass_trigger": "FIRST_PASS_IS_MODEL_FAILURE_OR_PASS_QA_SAMPLE",
        },
        "n3_adjudicator_budget": {
            "rows": n3_adjudication_rows,
            "volume_source": "EXECUTABLE_FROZEN_N3_PROVIDER_FIXTURE_COUNT",
            "qualification_side_fixtures": n3_by_split[N3_SAFETY_SMOKE]
            + n3_by_split[N3_CORE],
            "held_out_fixtures": n3_by_split[N3_HELD_OUT_CONFIRMATION],
            "first_pass_qualification_side_worst_case_all_rungs": _sum(
                n3_adjudication_rows, "first_pass_calls", side="QUALIFICATION"
            ),
            "first_pass_qualification_side_lowest_rung_only": _sum(
                n3_adjudication_rows, "first_pass_calls", side="QUALIFICATION", reasoning_rung="HIGH"
            ),
            "first_pass_held_out_for_one_selected_configuration": _sum(
                n3_adjudication_rows, "first_pass_calls", side="HELD_OUT_CONFIRMATION", reasoning_rung="HIGH"
            ),
            "max_conditional_second_pass_qualification_side_worst_case_all_rungs": _sum(
                n3_adjudication_rows, "max_conditional_second_pass_calls", side="QUALIFICATION"
            ),
            "max_conditional_second_pass_held_out_for_one_selected_configuration": _sum(
                n3_adjudication_rows, "max_conditional_second_pass_calls", side="HELD_OUT_CONFIRMATION", reasoning_rung="HIGH"
            ),
            "second_pass_trigger": "FIRST_PASS_DISPOSITION_IS_CONFIRMED",
        },
        "case_counts_by_stage_split": {
            stage: dict(sorted(values.items()))
            for stage, values in sorted(case_counts.items())
        },
        "adjudicable_observation_units_by_stage_split": pairs,
    }
    return {**material, "call_budget_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# Protocol and candidate matrix
# --------------------------------------------------------------------------


def candidate_matrix_v131(
    build: V13Build, *, benchmark_boundary_hash: str
) -> dict[str, Any]:
    """Candidate identities unchanged; the hash moves with what it binds."""

    from .semantic_benchmark_v13_protocol import candidate_matrix_v13

    base = candidate_matrix_v13(build, benchmark_boundary_hash=benchmark_boundary_hash)
    material = {
        key: value for key, value in base.items() if key != "candidate_matrix_hash"
    }
    v130 = _json(V130_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    material.update(
        {
            "schema_version": CANDIDATE_MATRIX_VERSION_V131,
            "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "protocol_version": PROTOCOL_VERSION_V131,
            "candidate_identities_changed_from_v130": False,
            "carried_candidate_identity_hash": canonical_hash(v130["candidates"]),
            "new_hash_reason": (
                "The candidate identities did not change and are proved "
                "byte-identical to v1.3.0. The matrix hash moves because it binds "
                "phase9-qualification-protocol/1.3.1 and the v1.3.1 global "
                "boundary, both of which changed when the N3 provider-call "
                "authority became bound."
            ),
        }
    )
    if material["candidates"] != v130["candidates"]:
        raise V13BuildError(
            "candidate identities must carry forward byte-identically from v1.3.0"
        )
    return {**material, "candidate_matrix_hash": canonical_hash(material)}


def qualification_protocol_v131(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
) -> dict[str, Any]:
    """The v1.3.0 protocol, re-bound to the repaired call authority."""

    from .semantic_benchmark_v13_protocol import (
        adjudication_protocol_v13,
        qualification_protocol_v13,
    )

    base = qualification_protocol_v13(
        build,
        n3_axis,
        benchmark_boundary=benchmark_boundary,
        candidate_matrix=candidate_matrix,
        call_budget=call_budget,
    )
    material = {
        key: value for key, value in base.items() if key != "protocol_boundary_hash"
    }
    material.update(
        {
            "schema_version": PROTOCOL_VERSION_V131,
            "protocol_version": PROTOCOL_VERSION_V131,
            "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
            "previous_protocol_version": "phase9-qualification-protocol/1.3.0",
            "reason_for_new_version": [
                "the N3 provider-call authority is now bound: the exact P06 "
                "request for each of the ten exposures is frozen",
                "the P06 stage boundary changed",
                "the global benchmark boundary changed",
                "the call budget derives N3 volumes from the frozen fixture set",
            ],
            "n3_provider_call_authority": {
                "fixture_schema": fixtures["schema_version"],
                "fixture_set_hash": fixtures["fixture_set_hash"],
                "fixture_count": fixtures["fixture_count"],
                "construct_selection_rule": fixtures["construct_selection_rule"],
                "construct_selection_independence_hash": fixtures[
                    "construct_selection_independence_hash"
                ],
                "production_representativeness_hash": fixtures[
                    "production_representativeness_hash"
                ],
                "expected_candidate_family": fixtures["expected_candidate_family"],
                "n3_calls_are_additional_to_the_semantic_budget": True,
            },
        }
    )
    # Semantic decision semantics and bars are untouched; prove it rather than
    # restate it.
    adjudication = adjudication_protocol_v13()
    if material["adjudication_protocol_hash"] != adjudication["adjudication_protocol_hash"]:
        raise V13BuildError("the semantic adjudication protocol may not change in v1.3.1")
    v130 = _json(V130_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    if material["semantic_gates"] != v130["semantic_gates"]:
        raise V13BuildError("the semantic gates may not change in v1.3.1")
    if material["semantic_qualification_limitations"] != v130[
        "semantic_qualification_limitations"
    ]:
        raise V13BuildError("the U3 limitation may not change in v1.3.1")
    if material["ordering"] != v130["ordering"]:
        raise V13BuildError("the pre-registered ordering may not change in v1.3.1")
    return {**material, "protocol_boundary_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART I -- lineage
# --------------------------------------------------------------------------


def lineage_v131(build: V13Build) -> dict[str, Any]:
    """Classify what 1.3.1 replaces, inherits and introduces."""

    v130_lineage = _json(V130_REPORT_ROOT / "lineage.json")
    inherited = (
        "phase9/adjudication_protocol.json",
        "phase9/semantic_qualification_claim.json",
        "phase9/safety_gate.json",
        "phase9/qualification_thresholds.json",
        "fixtures/p06_routes.json",
        "fixtures/property_bindings.json",
        "fixtures/p06_coverage_debt.json",
        "fixtures/qualification_oracle_dispositions.json",
    )
    republished_unchanged = {
        "phase9/n3_contractual_safety_axis.json": (
            "Republished under v1.3.1 byte-identically so the v1.3.1 directory "
            "is self-contained for an auditor and its self hash appears in the "
            "v1.3.1 manifest. Its material did not change, so neither did its "
            "hash."
        ),
    }
    replaced = {
        "phase9/qualification_protocol.json": (
            "binds the N3 provider-call authority and the re-derived budget"
        ),
        "phase9/candidate_matrix.json": (
            "candidate identities unchanged; binds the new protocol and boundary"
        ),
    }
    new = {
        "phase9/n3_provider_fixtures.json": (
            "the ten frozen provider-facing P06 requests, their selection rule "
            "and their production-representativeness proof"
        ),
        "phase9/noisy_disposition_census.json": (
            "the NOISY disposition partition, derived instead of written in prose"
        ),
        "phase9/construct_selection_independence.json": (
            "the executed proof that construct selection reads no forbidden input"
        ),
    }

    on_disk = sorted(
        path.relative_to(V130_DEFINITION_ROOT).as_posix()
        for path in V130_DEFINITION_ROOT.rglob("*.json")
    )
    classified = set(inherited) | set(replaced) | set(republished_unchanged)
    unclassified = sorted(set(on_disk) - classified)
    if unclassified:
        raise V13BuildError(
            "every v1.3.0 authority artifact must be classified in the v1.3.1 "
            f"lineage; unclassified: {unclassified}"
        )

    material = {
        "schema_version": "semantic-benchmark-lineage/1.3.1",
        "from_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "chain": [
            {
                "version": "semantic-benchmark/1.2.0",
                "status": "IMMUTABLE_HISTORICAL_AUTHORITY",
            },
            {
                "version": SEMANTIC_BENCHMARK_V13_VERSION,
                "status": V130_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "superseded_because": [
                    "the exact provider request for the additional N3 P06 calls "
                    "was not frozen",
                    "freeze_hash_manifest.json reported a dependency hash as the "
                    "internal material hash for the candidate matrix and the "
                    "qualification protocol",
                ],
                "bytes_modified_by_v131": False,
            },
            {
                "version": SEMANTIC_BENCHMARK_V131_VERSION,
                "status": V131_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
            },
        ],
        "is_a_corpus_change": False,
        "is_a_semantic_product_decision_change": False,
        "is_a_pre_execution_instrumentation_repair": True,
        "no_result_existed_when_this_repair_was_made": True,
        "v12_lineage_hash": v130_lineage["lineage_hash"],
        "v130_authority_artifact_count": len(on_disk),
        "inherited_unchanged": sorted(inherited),
        "republished_unchanged": dict(sorted(republished_unchanged.items())),
        "republished_unchanged_hashes": {
            name: _json(V130_DEFINITION_ROOT / name)["n3_axis_hash"]
            for name in republished_unchanged
        },
        "replaced": dict(sorted(replaced.items())),
        "new_in_v131": dict(sorted(new.items())),
        "silent_carry_forward_permitted": False,
    }
    return {**material, "lineage_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART K -- the pre-results freeze
# --------------------------------------------------------------------------


def pre_results_freeze_v131(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    qualification_protocol: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    call_budget: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the whole v1.3.1 instrument before any result exists."""

    from .p06_field_authority import p06_field_authority
    from .p07_field_authority import p07_field_authority
    from .semantic_benchmark_v13_protocol import (
        HASH_KINDS,
        _counter_evidence,
        adjudication_protocol_v13,
    )

    claim = semantic_qualification_claim(build)
    splits = split_partition_authority_v13(build)
    instrument = p06_instrument_report(build)
    separation = result_axis_separation(build)
    adjudication = adjudication_protocol_v13()
    counters = _counter_evidence()

    material = {
        "schema_version": "phase9-pre-results-instrument-freeze/1.3.1",
        "phase": "9B.8A",
        "benchmark_version": SEMANTIC_BENCHMARK_V131_VERSION,
        "previous_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "previous_version_status": V130_STATUS,
        "status": V131_STATUS,
        "purpose": (
            "Freeze the U3 + N3 pre-execution instrument, including the exact "
            "provider request behind every additional N3 P06 call, before any "
            "candidate result exists."
        ),
        "immutable_after_this_point": True,
        "hash_kinds": dict(HASH_KINDS),
        "all_hashes_bound_here_are": "INTERNAL_MATERIAL_HASH",
        "file_sha256_and_git_blob_sha_live_in": (
            f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
        ),
        "corpus_package_boundary_hash": build.package_hash,
        "corpus_root": "evaluation/corpora/pruebas_personalizadas/v1",
        "corpus_authority": (
            "comprehension_verification.semantic_benchmark.DEFAULT_CORPUS_ROOT"
        ),
        "corpus_bytes_modified": False,
        "global_benchmark_boundary_hash": benchmark_boundary["benchmark_boundary_hash"],
        "stage_boundaries_hash": stage_boundaries["stage_boundaries_hash"],
        "stage_boundary_hashes": dict(stage_boundaries["stage_boundary_hashes"]),
        "boundary_status_by_stage": dict(stage_boundaries["boundary_status_by_stage"]),
        "protocol_version": qualification_protocol["protocol_version"],
        "protocol_boundary_hash": qualification_protocol["protocol_boundary_hash"],
        "adjudication_protocol_version": adjudication["schema_version"],
        "adjudication_protocol_hash": adjudication["adjudication_protocol_hash"],
        "adjudication_protocol_policy_core_hash": adjudication["policy_core_hash"],
        "field_authority_hashes": {
            "p06": p06_field_authority()["field_authority_hash"],
            "p07": p07_field_authority()["field_authority_hash"],
        },
        "n3_axis_hash": n3_axis["n3_axis_hash"],
        "n3_protocol_version": n3_axis["protocol_version"],
        "n3_gate_version": n3_axis["contractual_policy_authority"]["gate_version"],
        "n3_contractual_policy_authority_hash": n3_axis["contractual_policy_authority"][
            "authority_hash"
        ],
        "n3_exposure_population_hash": n3_axis["exposure_population"]["population_hash"],
        "n3_census": dict(n3_axis["census"]),
        "n3_promotion_gates": dict(n3_axis["promotion_gates"]),
        # --- the repair
        "n3_provider_fixture_schema": fixtures["schema_version"],
        "n3_provider_fixture_set_hash": fixtures["fixture_set_hash"],
        "n3_provider_fixture_count": fixtures["fixture_count"],
        "n3_provider_fixture_counts_by_split": dict(fixtures["counts_by_n3_split"]),
        "n3_provider_fixture_input_hashes": dict(
            sorted(fixtures["fixture_input_hashes"].items())
        ),
        "n3_construct_selection_rule": fixtures["construct_selection_rule"],
        "n3_construct_selection_independence_hash": fixtures[
            "construct_selection_independence_hash"
        ],
        "n3_production_representativeness_hash": fixtures[
            "production_representativeness_hash"
        ],
        "n3_noisy_disposition_census_hash": fixtures["noisy_disposition_census_hash"],
        "candidate_matrix_hash": candidate_matrix["candidate_matrix_hash"],
        "call_budget_hash": call_budget["call_budget_hash"],
        "split_partition_hash": splits["split_partition_hash"],
        "held_out_activity_numbers": list(splits["held_out_activity_numbers"]),
        "held_out_partition_changed": False,
        "held_out_is_confirmation_only": True,
        "lineage_hash": lineage["lineage_hash"],
        "p06_instrument_hash": instrument["instrument_hash"],
        "semantic_qualification_claim_hash": claim["claim_hash"],
        "semantic_claim_limitations": list(claim["limitations"]),
        "qualified_support_statuses": list(claim["qualified_support_statuses"]),
        "excluded_support_statuses": list(claim["excluded_support_statuses"]),
        "axis_separation_hash": separation["separation_hash"],
        "execution_counters": counters,
        "results_firewall": {
            "candidate_outcomes_read": False,
            "first_pass_adjudication_results_read": False,
            "provider_outputs_read": False,
            "historical_qualification_results_used_as_construction_authority": False,
            "note": (
                "No candidate result exists for semantic-benchmark/1.3.0 or "
                "1.3.1. Superseding 1.3.0 is an instrumentation repair, not a "
                "response to an observed outcome."
            ),
        },
        "v12_preserved": {"v12_bytes_modified": False},
        "v130_preserved": {"v130_bytes_modified": False, "status": V130_STATUS},
        "stop_condition": (
            "SEMANTIC_BENCHMARK_V1_3_1_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT"
        ),
        "qualification_run": False,
        "high_smoke_authorized": False,
    }
    return {**material, "freeze_material_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART H -- explicit self-hash registry, validated fail-closed
# --------------------------------------------------------------------------

#: Which field carries each generated document's own internal material hash.
#: Explicit on purpose: v1.3.0 guessed by scanning for the first ``*_hash``
#: field and found ``benchmark_boundary_hash`` -- a *dependency* -- on the
#: candidate matrix and the qualification protocol.  ``None`` would mean a
#: document deliberately has no self hash; every entry here has one.
SELF_MATERIAL_HASH_FIELD: Mapping[str, str | None] = {
    f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": "protocol_boundary_hash",
    f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": "candidate_matrix_hash",
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": "fixture_set_hash",
    f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": "n3_axis_hash",
    f"{REPORT_ROOT}/lineage.json": "lineage_hash",
    f"{REPORT_ROOT}/stage_boundaries.json": "stage_boundaries_hash",
    f"{REPORT_ROOT}/benchmark_boundary.json": "benchmark_boundary_hash",
    f"{REPORT_ROOT}/phase9/call_budget.json": "call_budget_hash",
    f"{REPORT_ROOT}/phase9/noisy_disposition_census.json": "census_hash",
    f"{REPORT_ROOT}/phase9/construct_selection_independence.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/n3_production_representativeness.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": "freeze_material_hash",
}


class HashManifestError(ValueError):
    """Raised when a manifest entry cannot be shown to be a real self hash."""


def self_material_hash(path: str, document: Mapping[str, Any]) -> str | None:
    """Return a document's own internal material hash, proved not guessed.

    The registry names the field; this function then *verifies* the claim
    cryptographically: a document's self hash is the canonical hash of the
    document with that field removed.  A dependency hash copied in from another
    artifact cannot satisfy that, so the old defect cannot recur silently.
    """

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


def _rebuild_v131_package_with_original_builders(
    build: V13Build,
) -> dict[str, dict[str, Any]]:
    """Every generated v1.3.1 document, keyed by repository-relative path.

    Pure: it reads frozen authority and returns documents, writing nothing, so
    it can be called twice and compared.
    """

    from .n3_provider_fixtures import (
        build_n3_provider_fixtures,
        production_representativeness_proof,
        selection_independence_proof,
    )

    # Historical packages are reconstructed against their published N3 axis,
    # not against later executable repairs.
    n3_axis = _json(
        REPOSITORY_ROOT
        / DEFINITION_ROOT
        / "phase9/n3_contractual_safety_axis.json"
    )
    fixtures = n3_provider_fixture_authority(build.corpus_root)
    boundaries = stage_boundaries_v131(build, n3_axis, fixtures)
    global_boundary = benchmark_boundary_v131(build, n3_axis, fixtures)
    budget = call_budget_v131(build, fixtures)
    matrix = candidate_matrix_v131(
        build, benchmark_boundary_hash=global_boundary["benchmark_boundary_hash"]
    )
    protocol = qualification_protocol_v131(
        build,
        n3_axis,
        fixtures,
        benchmark_boundary=global_boundary,
        candidate_matrix=matrix,
        call_budget=budget,
    )
    lineage = lineage_v131(build)
    freeze = pre_results_freeze_v131(
        build,
        n3_axis,
        fixtures,
        benchmark_boundary=global_boundary,
        stage_boundaries=boundaries,
        qualification_protocol=protocol,
        candidate_matrix=matrix,
        call_budget=budget,
        lineage=lineage,
    )
    fixture_build = build_n3_provider_fixtures(build.corpus_root)

    return {
        f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": fixtures,
        f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": n3_axis,
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": protocol,
        f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": matrix,
        f"{REPORT_ROOT}/lineage.json": lineage,
        f"{REPORT_ROOT}/stage_boundaries.json": boundaries,
        f"{REPORT_ROOT}/benchmark_boundary.json": global_boundary,
        f"{REPORT_ROOT}/phase9/call_budget.json": budget,
        f"{REPORT_ROOT}/phase9/noisy_disposition_census.json": noisy_disposition_census(
            build.corpus_root
        ),
        f"{REPORT_ROOT}/phase9/construct_selection_independence.json": (
            selection_independence_proof(build.corpus_root)
        ),
        f"{REPORT_ROOT}/phase9/n3_production_representativeness.json": (
            production_representativeness_proof(fixture_build, build.corpus_root)
        ),
        f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": freeze,
    }


def build_v131(corpus_root: Path = DEFAULT_CORPUS_ROOT) -> V13Build:
    """v1.3.1 reuses the v1.3.0 semantic instrument unchanged."""

    return build_v13(corpus_root)


def v131_package(build: V13Build) -> dict[str, dict[str, Any]]:
    """Return immutable, already-published v1.3.1 evidence."""

    if build.package_hash != (
        "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1"
    ):
        raise V13BuildError("v1.3.1 historical package requires canonical corpus")
    package = {
        relative: _json(REPOSITORY_ROOT / relative)
        for relative in SELF_MATERIAL_HASH_FIELD
    }
    for relative, document in package.items():
        self_material_hash(relative, document)
    return package
