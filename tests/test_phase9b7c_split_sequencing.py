"""Phase 9B.7C N3 split-sequencing and atomic-boundary regression.

Every test is offline.  No provider or adjudicator is called, no credential
resolved, no candidate outcome read.

The property under test is held-out isolation.  ``HELD_OUT_CONFIRMATION`` may
only confirm or reject a configuration that was already selected without it.
The N3 population spans both sides of that partition, so a selector that ran
exhaustively over all ten exposures per rung -- which Phase 9B.7B published --
would have let held-out material choose the configuration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comprehension_verification.p06_n3_protocol import (
    CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE,
    HELD_OUT_SIDE,
    INDETERMINATE,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_SAFETY_SMOKE,
    NO_CONFIRMED_VIOLATION,
    P06_SMOKE_ACTIVITY_IDS,
    QUALIFICATION_SIDE,
    N3ProtocolError,
    assert_no_held_out_in_selection,
    n3_exposure_population,
    n3_held_out_confirmation,
    n3_rung_aggregate,
    n3_safety_smoke_selector,
    n3_stage_plan,
)
from comprehension_verification.phase9b7_decision import (
    N3_V13_P06_BOUNDARY_REQUIREMENTS,
    N3_V13_P07_BOUNDARY_REQUIREMENTS,
    N3_V13_PROTOCOL_REQUIREMENTS,
    n3_future_boundary_requirements,
    validate_u3_n3_boundary_plan,
)
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = DEFAULT_CORPUS_ROOT
SPLIT_PARTITION = (
    REPO_ROOT / "reports" / "semantic_benchmark" / "v1_2" / "split_partition.json"
)


@pytest.fixture(scope="module")
def population() -> dict:
    return n3_exposure_population(CORPUS_ROOT, SPLIT_PARTITION)


@pytest.fixture(scope="module")
def safety_smoke(population) -> dict:
    return n3_safety_smoke_selector(
        population, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )


@pytest.fixture(scope="module")
def stage_plan(population, safety_smoke) -> dict:
    return n3_stage_plan(population, safety_smoke)


def _verdict(name: str, exposure: str) -> dict:
    return {"exposure_pseudonym": exposure, "verdict": name}


# --------------------------------------------------------------------------
# PART A - the derived partition
# --------------------------------------------------------------------------


def test_population_is_the_ten_frozen_noisy_exposures(population) -> None:
    assert population["total_exposure_count"] == 10
    for exposure in population["exposures"]:
        for field in (
            "exposure_id",
            "activity_id",
            "submission_id",
            "activity_split",
            "side",
            "model_visible_input_identity_hash",
            "technical_string_control_available",
        ):
            assert field in exposure


def test_split_comes_from_the_v12_partition_not_from_outcomes(population) -> None:
    frozen = json.loads(SPLIT_PARTITION.read_text(encoding="utf-8"))
    assert population["held_out_activity_numbers"] == sorted(
        frozen["held_out_activity_numbers"]
    )
    assert population["split_partition_hash"] == frozen["split_partition_hash"]
    assert population["split_derived_from_outcomes"] is False
    # v1.2 carries the v1.1 partition forward; the stale v1.0 list is not used.
    assert population["held_out_partition_source"] == "semantic-benchmark/1.1.0"
    assert population["held_out_activity_numbers"] == [3, 7, 9, 10, 12]


def test_both_sides_of_the_partition_are_non_empty(population) -> None:
    assert population["qualification_side_count"] >= 1
    assert population["held_out_count"] >= 1
    assert (
        population["qualification_side_count"] + population["held_out_count"]
        == population["total_exposure_count"]
    )


def test_the_census_matches_the_activity_disjoint_strategy(population) -> None:
    held_out = set(population["held_out_activity_numbers"])
    for exposure in population["exposures"]:
        expected = (
            HELD_OUT_SIDE
            if exposure["activity_number"] in held_out
            else QUALIFICATION_SIDE
        )
        assert exposure["side"] == expected


def test_technical_string_controls_are_recorded_per_exposure(population) -> None:
    assert population["technical_string_control_count"] == 9


# --------------------------------------------------------------------------
# PART D - anti-contamination
# --------------------------------------------------------------------------


def test_d1_held_out_cannot_appear_in_safety_smoke(population, safety_smoke) -> None:
    """Regression 1."""

    held_out = set(population["held_out_exposure_ids"])
    assert not set(safety_smoke["exposure_ids"]) & held_out
    assert safety_smoke["held_out_members"] == 0
    assert safety_smoke["pre_registered"] is True
    assert safety_smoke["selection_depends_on_outcomes"] is False


def test_d1b_a_smoke_selector_over_a_held_out_activity_fails_closed(
    population,
) -> None:
    held_out_activity = next(
        item["activity_id"]
        for item in population["exposures"]
        if item["side"] == HELD_OUT_SIDE
    )
    selector = n3_safety_smoke_selector(
        population, smoke_activity_ids=(held_out_activity,)
    )
    # The held-out activity contributes nothing; the rule falls back to a
    # qualification-side exposure rather than reaching across the partition.
    assert selector["held_out_members"] == 0
    assert not set(selector["exposure_ids"]) & set(
        population["held_out_exposure_ids"]
    )


def test_d2_held_out_cannot_appear_in_core_selection(population, stage_plan) -> None:
    """Regression 2."""

    held_out = set(population["held_out_exposure_ids"])
    stages = {item["stage"]: item for item in stage_plan["stages"]}
    assert not set(stages[N3_CORE]["exposure_ids"]) & held_out
    assert not set(stages[N3_SAFETY_SMOKE]["exposure_ids"]) & held_out
    assert set(stages[N3_HELD_OUT_CONFIRMATION]["exposure_ids"]) == held_out


def test_d2b_aggregating_a_held_out_exposure_into_selection_fails_closed(
    population,
) -> None:
    held_out_id = population["held_out_exposure_ids"][0]
    with pytest.raises(N3ProtocolError):
        n3_rung_aggregate(
            [_verdict(NO_CONFIRMED_VIOLATION, held_out_id)],
            required_exposure_count=1,
            stage=N3_CORE,
            population=population,
        )
    with pytest.raises(N3ProtocolError):
        assert_no_held_out_in_selection(
            selection_exposure_ids=[held_out_id], population=population
        )


def test_d3_qualification_side_failure_can_reject_a_rung(population) -> None:
    """Regression 3."""

    qualification = population["qualification_side_exposure_ids"]
    verdicts = [
        _verdict(NO_CONFIRMED_VIOLATION, item) for item in qualification[:-1]
    ]
    verdicts.append(
        _verdict(CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE, qualification[-1])
    )
    aggregate = n3_rung_aggregate(
        verdicts,
        required_exposure_count=len(qualification),
        stage=N3_CORE,
        population=population,
    )
    assert aggregate["rejects_candidate_rung"] is True
    assert aggregate["promotion_disposition"] == "REJECTED"
    assert aggregate["may_influence_rung_selection"] is True


def test_d4_held_out_failure_cannot_trigger_escalation(population) -> None:
    """Regression 4."""

    verdicts = [
        _verdict(NO_CONFIRMED_VIOLATION, item)
        for item in population["held_out_exposure_ids"][:-1]
    ]
    verdicts.append(
        _verdict(
            CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE,
            population["held_out_exposure_ids"][-1],
        )
    )
    result = n3_held_out_confirmation(
        verdicts, population=population, selected_configuration="cfg_high_rung_1"
    )
    assert result["outcome"] == "HELD_OUT_CONFIRMATION_FAILED"
    assert result["configuration_qualified"] is False
    assert result["may_fall_back_to_another_rung"] is False
    assert result["may_select_a_different_candidate"] is False
    assert "NEW pre-execution decision" in result["on_failure_consequence"]


def test_d5_held_out_result_cannot_alter_ranking(population, stage_plan) -> None:
    """Regression 5."""

    verdicts = [
        _verdict(NO_CONFIRMED_VIOLATION, item)
        for item in population["held_out_exposure_ids"]
    ]
    result = n3_held_out_confirmation(
        verdicts, population=population, selected_configuration="cfg_a"
    )
    assert result["may_alter_candidate_ranking"] is False
    assert stage_plan["held_out_results_may_alter_ranking"] is False
    stages = {item["stage"]: item for item in stage_plan["stages"]}
    assert stages[N3_HELD_OUT_CONFIRMATION]["may_influence_rung_selection"] is False


def test_d6_held_out_runs_only_after_a_configuration_is_selected(
    population,
) -> None:
    """Regression 6."""

    verdicts = [
        _verdict(NO_CONFIRMED_VIOLATION, item)
        for item in population["held_out_exposure_ids"]
    ]
    for absent in (None, ""):
        with pytest.raises(N3ProtocolError):
            n3_held_out_confirmation(
                verdicts, population=population, selected_configuration=absent
            )


def test_d6b_held_out_execution_is_forbidden_before_selection(stage_plan) -> None:
    assert stage_plan["held_out_execution_forbidden_before_selection"] is True
    stages = {item["stage"]: item for item in stage_plan["stages"]}
    assert "already qualified" in stages[N3_HELD_OUT_CONFIRMATION]["precondition"]


def test_d7_all_held_out_exposures_are_exhausted_at_confirmation(
    population,
) -> None:
    """Regression 7."""

    full = [
        _verdict(NO_CONFIRMED_VIOLATION, item)
        for item in population["held_out_exposure_ids"]
    ]
    complete = n3_held_out_confirmation(
        full, population=population, selected_configuration="cfg_a"
    )
    assert complete["exhaustive"] is True
    assert complete["outcome"] == "HELD_OUT_CONFIRMATION_PASSED"

    partial = n3_held_out_confirmation(
        full[:-1], population=population, selected_configuration="cfg_a"
    )
    assert partial["exhaustive"] is False
    assert partial["configuration_qualified"] is False
    assert partial["outcome"] == "HELD_OUT_CONFIRMATION_BLOCKED_INCONCLUSIVE"


def test_d7b_a_non_held_out_exposure_cannot_enter_confirmation(
    population,
) -> None:
    verdicts = [
        _verdict(NO_CONFIRMED_VIOLATION, item)
        for item in population["held_out_exposure_ids"]
    ]
    verdicts.append(
        _verdict(
            NO_CONFIRMED_VIOLATION,
            population["qualification_side_exposure_ids"][0],
        )
    )
    with pytest.raises(N3ProtocolError):
        n3_held_out_confirmation(
            verdicts, population=population, selected_configuration="cfg_a"
        )


def test_d8_unresolved_held_out_blocks_final_confirmation(population) -> None:
    """Regression 8."""

    verdicts = [
        _verdict(NO_CONFIRMED_VIOLATION, item)
        for item in population["held_out_exposure_ids"][:-1]
    ]
    verdicts.append(_verdict(INDETERMINATE, population["held_out_exposure_ids"][-1]))
    result = n3_held_out_confirmation(
        verdicts, population=population, selected_configuration="cfg_a"
    )
    assert result["indeterminate_count"] == 1
    assert result["configuration_qualified"] is False
    assert result["outcome"] == "HELD_OUT_CONFIRMATION_BLOCKED_INCONCLUSIVE"
    assert "never silently passed" in result["on_inconclusive_consequence"]


def test_d9_selector_output_exists_before_any_candidate_outcome() -> None:
    """Regression 9."""

    first = n3_exposure_population(CORPUS_ROOT, SPLIT_PARTITION)
    second = n3_exposure_population(CORPUS_ROOT, SPLIT_PARTITION)
    assert first["population_hash"] == second["population_hash"]
    smoke_a = n3_safety_smoke_selector(
        first, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    smoke_b = n3_safety_smoke_selector(
        second, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    assert smoke_a["selector_hash"] == smoke_b["selector_hash"]
    # Nothing in either signature is an outcome.
    blob = json.dumps(first) + json.dumps(smoke_a)
    for token in ("verdict", "support_status", "accepted_rate", "MODEL_FAILURE"):
        assert token not in blob


def test_d10_an_outcome_cannot_change_split_or_selector_membership(
    population, safety_smoke
) -> None:
    """Regression 10."""

    baseline_split = {
        item["exposure_id"]: item["side"] for item in population["exposures"]
    }
    baseline_smoke = list(safety_smoke["exposure_ids"])

    # Adjudicate every exposure as a confirmed failure -- the most outcome-laden
    # state possible -- then re-derive. Nothing may move.
    _ = [
        _verdict(CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE, item["exposure_id"])
        for item in population["exposures"]
    ]
    rederived = n3_exposure_population(CORPUS_ROOT, SPLIT_PARTITION)
    rederived_smoke = n3_safety_smoke_selector(
        rederived, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    assert {
        item["exposure_id"]: item["side"] for item in rederived["exposures"]
    } == baseline_split
    assert list(rederived_smoke["exposure_ids"]) == baseline_smoke


# --------------------------------------------------------------------------
# PART B - sequencing
# --------------------------------------------------------------------------


def test_qualification_side_is_exhaustive_across_smoke_and_core(
    population, stage_plan
) -> None:
    stages = {item["stage"]: item for item in stage_plan["stages"]}
    covered = set(stages[N3_SAFETY_SMOKE]["exposure_ids"]) | set(
        stages[N3_CORE]["exposure_ids"]
    )
    assert covered == set(population["qualification_side_exposure_ids"])
    assert stages[N3_CORE]["exhaustive_over"] == (
        "ALL_REMAINING_QUALIFICATION_SIDE_EXPOSURES"
    )


def test_the_lifecycle_order_is_smoke_then_core_then_held_out(stage_plan) -> None:
    assert stage_plan["lifecycle"] == [
        N3_SAFETY_SMOKE,
        N3_CORE,
        N3_HELD_OUT_CONFIRMATION,
    ]


def test_held_out_confirmation_cannot_aggregate_into_rung_selection(
    population,
) -> None:
    with pytest.raises(N3ProtocolError):
        n3_rung_aggregate(
            [],
            required_exposure_count=0,
            stage=N3_HELD_OUT_CONFIRMATION,
            population=population,
        )


# --------------------------------------------------------------------------
# PART E - atomic boundary inventory
# --------------------------------------------------------------------------


def test_the_dependency_count_is_derived_from_the_inventory() -> None:
    report = n3_future_boundary_requirements()
    assert report["P06_atomic_dependency_count"] == len(
        N3_V13_P06_BOUNDARY_REQUIREMENTS
    )
    assert report["P06_count_is_derived_not_declared"] is True
    assert len(set(N3_V13_P06_BOUNDARY_REQUIREMENTS)) == len(
        N3_V13_P06_BOUNDARY_REQUIREMENTS
    )


def test_field_authority_and_source_hash_are_separate_dependencies() -> None:
    inventory = set(N3_V13_P06_BOUNDARY_REQUIREMENTS)
    assert "P06 field-authority hash" in inventory
    assert "P06 field-authority executable source hash" in inventory
    assert "N3 contractual gate definition" in inventory
    assert "N3 contractual gate executable source hash" in inventory
    assert "executable system prompt hash" in inventory
    assert "executable P06 developer prompt hash" in inventory


def test_the_n3_split_dependencies_are_present() -> None:
    inventory = set(N3_V13_P06_BOUNDARY_REQUIREMENTS)
    assert "N3 exposure population authority and hash" in inventory
    assert "N3 exposure split assignments" in inventory
    assert "N3 SAFETY_SMOKE selector authority and hash" in inventory
    assert "N3 qualification-side and held-out sequencing rule" in inventory
    assert "N3 held-out confirmation rule" in inventory
    assert (
        "N3 prohibition on result-driven post-held-out escalation" in inventory
    )


def _sound_plan() -> dict:
    return {
        "new_stage_boundaries": ["P06", "P07"],
        "p06_boundary_binds": list(N3_V13_P06_BOUNDARY_REQUIREMENTS),
        "p07_boundary_binds": list(N3_V13_P07_BOUNDARY_REQUIREMENTS),
        "protocol_artifacts": list(N3_V13_PROTOCOL_REQUIREMENTS),
    }


@pytest.mark.parametrize("dependency", N3_V13_P06_BOUNDARY_REQUIREMENTS)
def test_removing_exactly_one_p06_dependency_fails_closed(dependency: str) -> None:
    """PART E: every atomic dependency is individually load-bearing."""

    plan = _sound_plan()
    plan["p06_boundary_binds"] = [
        item for item in plan["p06_boundary_binds"] if item != dependency
    ]
    violations = validate_u3_n3_boundary_plan(plan)
    assert f"P06_BOUNDARY_OMITS::{dependency}" in violations


@pytest.mark.parametrize("dependency", N3_V13_P07_BOUNDARY_REQUIREMENTS)
def test_removing_exactly_one_p07_dependency_fails_closed(dependency: str) -> None:
    plan = _sound_plan()
    plan["p07_boundary_binds"] = [
        item for item in plan["p07_boundary_binds"] if item != dependency
    ]
    assert f"P07_BOUNDARY_OMITS::{dependency}" in validate_u3_n3_boundary_plan(plan)


@pytest.mark.parametrize("artifact", N3_V13_PROTOCOL_REQUIREMENTS)
def test_removing_exactly_one_protocol_artifact_fails_closed(artifact: str) -> None:
    plan = _sound_plan()
    plan["protocol_artifacts"] = [
        item for item in plan["protocol_artifacts"] if item != artifact
    ]
    assert f"PROTOCOL_ARTIFACT_MISSING::{artifact}" in (
        validate_u3_n3_boundary_plan(plan)
    )


def test_the_complete_plan_is_still_sound() -> None:
    assert validate_u3_n3_boundary_plan(_sound_plan()) == []


# --------------------------------------------------------------------------
# PART F - protocol additions
# --------------------------------------------------------------------------


def test_protocol_binds_the_split_sequencing_artifacts() -> None:
    protocol = set(N3_V13_PROTOCOL_REQUIREMENTS)
    assert "N3 exposure split assignments" in protocol
    assert "N3 SAFETY_SMOKE selector" in protocol
    assert "N3 qualification-side aggregation" in protocol
    assert "N3 held-out confirmation rule" in protocol
    assert "prohibition on result-driven post-held-out escalation" in protocol


def test_the_phase9b6a_p07_inventory_is_unchanged() -> None:
    from comprehension_verification.future_stage_boundary_plan import (
        P07_FUTURE_STAGE_BOUNDARY_DEPENDENCIES,
    )

    assert tuple(N3_V13_P07_BOUNDARY_REQUIREMENTS) == tuple(
        P07_FUTURE_STAGE_BOUNDARY_DEPENDENCIES
    )
