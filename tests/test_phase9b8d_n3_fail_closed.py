"""Offline falsifications for the semantic-benchmark/1.3.4 N3 repair.

These tests call the executable aggregation and confirmation surfaces.  They
never call a provider or adjudicator and never resolve a credential.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from comprehension_verification.p06_n3_protocol import (
    CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE,
    INDETERMINATE,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_SAFETY_SMOKE,
    NO_CONFIRMED_VIOLATION,
    P06_SMOKE_ACTIVITY_IDS,
    V12_SPLIT_PARTITION_PATH,
    N3ProtocolError,
    n3_exposure_population,
    n3_held_out_confirmation,
    n3_rung_aggregate,
    n3_safety_smoke_selector,
    n3_stage_plan,
)
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT


@pytest.fixture(scope="module")
def population() -> dict:
    return n3_exposure_population(DEFAULT_CORPUS_ROOT, V12_SPLIT_PARTITION_PATH)


@pytest.fixture(scope="module")
def stage_ids(population) -> dict[str, list[str]]:
    smoke = n3_safety_smoke_selector(
        population, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    plan = n3_stage_plan(population, smoke)
    return {row["stage"]: list(row["exposure_ids"]) for row in plan["stages"]}


def _rows(exposure_ids: list[str], verdict: str = NO_CONFIRMED_VIOLATION) -> list[dict]:
    return [
        {"exposure_pseudonym": exposure_id, "verdict": verdict}
        for exposure_id in exposure_ids
    ]


def _aggregate(rows: list[dict], *, stage: str, population, stage_ids) -> dict:
    return n3_rung_aggregate(
        rows,
        required_exposure_count=len(stage_ids[stage]),
        stage=stage,
        population=population,
    )


@pytest.mark.parametrize("stage", [N3_SAFETY_SMOKE, N3_CORE])
def test_selection_unknown_verdict_fails_closed(stage, population, stage_ids) -> None:
    rows = _rows(stage_ids[stage], verdict="UNKNOWN_VERDICT")
    with pytest.raises(N3ProtocolError, match="N3_UNKNOWN_VERDICT"):
        _aggregate(rows, stage=stage, population=population, stage_ids=stage_ids)


@pytest.mark.parametrize("stage", [N3_SAFETY_SMOKE, N3_CORE])
def test_selection_duplicate_exposure_fails_closed(
    stage, population, stage_ids
) -> None:
    rows = _rows(stage_ids[stage])
    rows.append(deepcopy(rows[0]))
    if len(stage_ids[stage]) > 1:
        rows.pop(-2)
    with pytest.raises(N3ProtocolError, match="N3_DUPLICATE_EXPOSURE_ID"):
        _aggregate(rows, stage=stage, population=population, stage_ids=stage_ids)


@pytest.mark.parametrize("stage", [N3_SAFETY_SMOKE, N3_CORE])
def test_selection_foreign_exposure_fails_closed(stage, population, stage_ids) -> None:
    rows = _rows(stage_ids[stage])
    rows[-1]["exposure_pseudonym"] = "N3-FOREIGN-NOT-PREREGISTERED"
    with pytest.raises(N3ProtocolError, match="N3_FOREIGN_EXPOSURE_ID"):
        _aggregate(rows, stage=stage, population=population, stage_ids=stage_ids)


@pytest.mark.parametrize("stage", [N3_SAFETY_SMOKE, N3_CORE])
def test_selection_missing_exposure_fails_closed(stage, population, stage_ids) -> None:
    rows = _rows(stage_ids[stage])[:-1]
    with pytest.raises(N3ProtocolError, match="N3_REQUIRED_EXPOSURE_ID_MISSING"):
        _aggregate(rows, stage=stage, population=population, stage_ids=stage_ids)


@pytest.mark.parametrize("missing_field", ["exposure_pseudonym", "verdict"])
def test_selection_missing_required_row_field_fails_closed(
    missing_field, population, stage_ids
) -> None:
    rows = _rows(stage_ids[N3_CORE])
    del rows[0][missing_field]
    with pytest.raises(N3ProtocolError, match="N3_ADJUDICATION_REQUIRED_FIELD_MISSING"):
        _aggregate(
            rows, stage=N3_CORE, population=population, stage_ids=stage_ids
        )


@pytest.mark.parametrize("stage", [N3_SAFETY_SMOKE, N3_CORE])
def test_exact_clean_selection_population_is_eligible(
    stage, population, stage_ids
) -> None:
    result = _aggregate(
        _rows(stage_ids[stage]),
        stage=stage,
        population=population,
        stage_ids=stage_ids,
    )
    assert result["promotion_disposition"] == "ELIGIBLE"
    assert result["adjudicated_exposure_count"] == len(stage_ids[stage])
    assert result["expected_exposure_ids"] == stage_ids[stage]


def test_one_selection_indeterminate_blocks_promotion(population, stage_ids) -> None:
    rows = _rows(stage_ids[N3_CORE])
    rows[0]["verdict"] = INDETERMINATE
    result = _aggregate(
        rows, stage=N3_CORE, population=population, stage_ids=stage_ids
    )
    assert result["promotion_disposition"] == "PENDING_BLOCKED"
    assert result["rejects_candidate_rung"] is False


def test_one_selection_confirmed_failure_rejects_rung(population, stage_ids) -> None:
    rows = _rows(stage_ids[N3_CORE])
    rows[0]["verdict"] = CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE
    result = _aggregate(
        rows, stage=N3_CORE, population=population, stage_ids=stage_ids
    )
    assert result["promotion_disposition"] == "REJECTED"
    assert result["rejects_candidate_rung"] is True


def _confirm(rows: list[dict], population) -> dict:
    return n3_held_out_confirmation(
        rows,
        population=population,
        selected_configuration="P06-C1-LUNA-HIGH",
    )


def test_held_out_unknown_verdict_fails_closed(population, stage_ids) -> None:
    rows = _rows(
        stage_ids[N3_HELD_OUT_CONFIRMATION], verdict="UNKNOWN_VERDICT"
    )
    with pytest.raises(N3ProtocolError, match="N3_UNKNOWN_VERDICT"):
        _confirm(rows, population)


def test_held_out_duplicate_exposure_fails_closed(population, stage_ids) -> None:
    rows = _rows(stage_ids[N3_HELD_OUT_CONFIRMATION])
    rows[-1] = deepcopy(rows[0])
    with pytest.raises(N3ProtocolError, match="N3_DUPLICATE_EXPOSURE_ID"):
        _confirm(rows, population)


def test_held_out_foreign_exposure_fails_closed(population, stage_ids) -> None:
    rows = _rows(stage_ids[N3_HELD_OUT_CONFIRMATION])
    rows[-1]["exposure_pseudonym"] = "N3-FOREIGN-NOT-HELD-OUT"
    with pytest.raises(N3ProtocolError, match="N3_FOREIGN_EXPOSURE_ID"):
        _confirm(rows, population)


def test_held_out_missing_exposure_fails_closed(population, stage_ids) -> None:
    rows = _rows(stage_ids[N3_HELD_OUT_CONFIRMATION])[:-1]
    with pytest.raises(N3ProtocolError, match="N3_REQUIRED_EXPOSURE_ID_MISSING"):
        _confirm(rows, population)


@pytest.mark.parametrize("missing_field", ["exposure_pseudonym", "verdict"])
def test_held_out_missing_required_row_field_fails_closed(
    missing_field, population, stage_ids
) -> None:
    rows = _rows(stage_ids[N3_HELD_OUT_CONFIRMATION])
    del rows[0][missing_field]
    with pytest.raises(N3ProtocolError, match="N3_ADJUDICATION_REQUIRED_FIELD_MISSING"):
        _confirm(rows, population)


def test_exact_clean_held_out_population_passes(population, stage_ids) -> None:
    result = _confirm(_rows(stage_ids[N3_HELD_OUT_CONFIRMATION]), population)
    assert result["outcome"] == "HELD_OUT_CONFIRMATION_PASSED"
    assert result["configuration_qualified"] is True
    assert result["exhaustive"] is True


def test_one_held_out_indeterminate_blocks_confirmation(population, stage_ids) -> None:
    rows = _rows(stage_ids[N3_HELD_OUT_CONFIRMATION])
    rows[0]["verdict"] = INDETERMINATE
    result = _confirm(rows, population)
    assert result["outcome"] == "HELD_OUT_CONFIRMATION_BLOCKED_INCONCLUSIVE"
    assert result["configuration_qualified"] is False


def test_one_held_out_confirmed_failure_fails_confirmation(
    population, stage_ids
) -> None:
    rows = _rows(stage_ids[N3_HELD_OUT_CONFIRMATION])
    rows[0]["verdict"] = CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE
    result = _confirm(rows, population)
    assert result["outcome"] == "HELD_OUT_CONFIRMATION_FAILED"
    assert result["configuration_qualified"] is False
    assert result["may_fall_back_to_another_rung"] is False
    assert result["may_select_a_different_candidate"] is False
