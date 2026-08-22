"""Offline pricing/accounting regressions for phase9-execution/2.0.3."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from comprehension_verification import phase9_execution as px
from comprehension_verification.model_gateway.gateway import (
    CallBudget,
    GatewayRouteBlocked,
)
from comprehension_verification.model_gateway.mock_factory import AdapterResult
from comprehension_verification.model_gateway.openai_pricing import (
    estimate_cost_usd as estimate_openai_cost_usd,
)


@pytest.fixture(scope="module")
def prepared() -> px.PreparedExecution:
    return px.prepare_phase9_execution()


@pytest.fixture(scope="module")
def pricing() -> dict[str, Any]:
    return px.load_current_pricing_artifact()


@pytest.fixture(scope="module")
def projection(
    prepared: px.PreparedExecution, pricing: dict[str, Any]
) -> dict[str, Any]:
    return px.load_and_validate_cost_projection(
        prepared=prepared, pricing=pricing
    )


def _write_forged_pricing(path: Path, document: dict[str, Any]) -> None:
    document["pricing_snapshot_hash"] = px._self_hash(
        document, "pricing_snapshot_hash"
    )
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_current_official_pricing_is_exact_and_non_billable(
    pricing: dict[str, Any],
) -> None:
    assert pricing["schema_version"] == "phase9-current-pricing/2.0.3"
    assert pricing["execution_version"] == "phase9-execution/2.0.3"
    assert pricing["status"] == "VERIFIED_CURRENT_OFFICIAL_PRICING"
    assert pricing["retrieved_at"] == "2026-08-21T20:50:38Z"
    assert pricing["official_source_urls"] == list(
        px.OFFICIAL_PRICING_SOURCE_URLS
    )
    assert pricing["processing_tier"] == "STANDARD"
    assert pricing["long_context_threshold"] == px.LONG_CONTEXT_THRESHOLD == 272_000
    assert pricing["long_context_pricing_authorized"] is False
    assert pricing["responses_api_supported"] is True
    assert pricing["structured_outputs_supported"] is True
    assert pricing["reasoning_high_supported"] is True
    assert pricing["authorization_state"] == "NOT_AUTHORIZED"
    assert pricing["billable_authorization"] == "NONE"
    assert pricing["pricing_snapshot_hash"] == px._self_hash(
        pricing, "pricing_snapshot_hash"
    )
    assert pricing["models"]["gpt-5.6-terra"] == {
        "availability": "AVAILABLE_OPENAI_API",
        "cache_write_per_million_usd": 2.5,
        "cached_input_per_million_usd": 0.2,
        "input_per_million_usd": 2.0,
        "model_id": "gpt-5.6-terra",
        "model_page_url": px.OFFICIAL_PRICING_SOURCE_URLS[0],
        "output_per_million_usd": 12.0,
        "processing_tier": "STANDARD",
        "reasoning_high_supported": True,
        "responses_api_endpoint": "v1/responses",
        "responses_api_supported": True,
        "structured_outputs_supported": True,
    }
    assert pricing["models"]["gpt-5.6-luna"] == {
        "availability": "AVAILABLE_OPENAI_API",
        "cache_write_per_million_usd": 0.25,
        "cached_input_per_million_usd": 0.02,
        "input_per_million_usd": 0.2,
        "model_id": "gpt-5.6-luna",
        "model_page_url": px.OFFICIAL_PRICING_SOURCE_URLS[1],
        "output_per_million_usd": 1.2,
        "processing_tier": "STANDARD",
        "reasoning_high_supported": True,
        "responses_api_endpoint": "v1/responses",
        "responses_api_supported": True,
        "structured_outputs_supported": True,
    }


def test_cache_write_tokens_materially_change_cost_and_rates_are_exact(
    pricing: dict[str, Any],
) -> None:
    terra_without_write = px._estimate_cost(
        pricing,
        model="gpt-5.6-terra",
        input_tokens=100_000,
        output_tokens=0,
        cache_write_input_tokens=0,
    )
    terra_with_write = px._estimate_cost(
        pricing,
        model="gpt-5.6-terra",
        input_tokens=100_000,
        output_tokens=0,
        cache_write_input_tokens=100_000,
    )
    luna_with_write = px._estimate_cost(
        pricing,
        model="gpt-5.6-luna",
        input_tokens=100_000,
        output_tokens=0,
        cache_write_input_tokens=100_000,
    )
    assert terra_without_write == 0.20
    assert terra_with_write == 0.25
    assert terra_with_write != terra_without_write
    assert luna_with_write == 0.025
    assert pricing["models"]["gpt-5.6-terra"][
        "cache_write_per_million_usd"
    ] == 2.50
    assert pricing["models"]["gpt-5.6-luna"][
        "cache_write_per_million_usd"
    ] == 0.25


def test_executor_cost_semantics_match_openai_pricing_policy_for_short_context(
    pricing: dict[str, Any],
) -> None:
    usage = {
        "input_tokens": 100_000,
        "cached_input_tokens": 10_000,
        "cache_write_input_tokens": 20_000,
        "output_tokens": 30_000,
    }
    assert px._estimate_cost(
        pricing, model="gpt-5.6-terra", **usage
    ) == estimate_openai_cost_usd(
        model="gpt-5.6-terra",
        input_tokens=usage["input_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        cache_write_tokens=usage["cache_write_input_tokens"],
        output_tokens=usage["output_tokens"],
    )


class _UsageAdapter:
    def __init__(self, result: AdapterResult) -> None:
        self.result = result
        self.calls = 0

    async def invoke(self, **_kwargs: Any) -> AdapterResult:
        self.calls += 1
        return self.result


def test_pricing_bound_adapter_charges_every_provider_usage_dimension(
    pricing: dict[str, Any],
) -> None:
    usage = AdapterResult(
        raw_output={"ok": True},
        input_tokens=1_000,
        cached_input_tokens=100,
        cache_write_input_tokens=200,
        output_tokens=300,
        effective_model="gpt-5.6-terra",
        output_hash="sha256:" + "1" * 64,
        provider_request_id_hash="sha256:" + "2" * 64,
        provider_schema_valid=True,
    )
    inner = _UsageAdapter(usage)
    counters = px.SafetyCounters()
    adapter = px.PricingBoundCapturingAdapter(
        inner, pricing=pricing, counters=counters, max_requests=1
    )
    route = px.build_openai_routes(
        max_call_cost_usd=10.0, route_profile_id="TERRA_HIGH_V1"
    )["P04_BLUEPRINT_BUILD_V1"]
    rebound = asyncio.run(
        adapter.invoke(
            prompt_id="P04_BLUEPRINT_BUILD_V1",
            route=route,
            attempt=1,
        )
    )
    expected_actual = px._estimate_cost(
        pricing,
        model=route.model,
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        output_tokens=usage.output_tokens,
    )
    expected_estimated = px._estimate_cost(
        pricing,
        model=route.model,
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        output_tokens=route.max_output_tokens,
    )
    assert inner.calls == counters.provider_calls == adapter.calls == 1
    assert rebound.actual_cost_usd == expected_actual
    assert rebound.estimated_cost_usd == expected_estimated
    assert adapter.captured[0]["input_tokens"] == 1_000
    assert adapter.captured[0]["cached_input_tokens"] == 100
    assert adapter.captured[0]["cache_write_input_tokens"] == 200
    assert adapter.captured[0]["output_tokens"] == 300


def test_forged_pricing_without_cache_write_rate_fails_closed(
    pricing: dict[str, Any], tmp_path: Path
) -> None:
    forged = deepcopy(pricing)
    del forged["models"]["gpt-5.6-terra"][
        "cache_write_per_million_usd"
    ]
    path = tmp_path / "missing-cache-write.json"
    _write_forged_pricing(path, forged)
    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.load_current_pricing_artifact(path)
    assert exc.value.code == "PHASE9_CURRENT_PRICING_INVALID"


def test_forged_cache_write_multiplier_fails_closed(
    pricing: dict[str, Any], tmp_path: Path
) -> None:
    forged = deepcopy(pricing)
    forged["cache_write_pricing_rule"]["multiplier"] = 1.24
    path = tmp_path / "wrong-cache-write-multiplier.json"
    _write_forged_pricing(path, forged)
    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.load_current_pricing_artifact(path)
    assert exc.value.code == (
        "PHASE9_CURRENT_PRICING_CACHE_WRITE_RULE_MISMATCH"
    )


def test_long_context_request_fails_before_adapter_transport(
    prepared: px.PreparedExecution,
    pricing: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = prepared.calls[0]
    inner = _UsageAdapter(
        AdapterResult(
            raw_output={},
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
        )
    )
    counters = px.SafetyCounters()
    adapter = px.PricingBoundCapturingAdapter(
        inner, pricing=pricing, counters=counters, max_requests=1
    )
    monkeypatch.setattr(
        px,
        "estimate_openai_input_tokens",
        lambda *_args, **_kwargs: px.LONG_CONTEXT_THRESHOLD + 1,
    )
    gateway = px._gateway_for(
        candidate=call.case.candidate,
        adapter=adapter,
        cap=10.0,
        pricing=pricing,
        job_id="job_v202_long_context_fail_closed",
    )
    envelope = px._envelope_for(
        call.case.candidate.prompt_id, call.case.request
    )
    with pytest.raises(px.Phase9ExecutionError) as exc:
        asyncio.run(
            gateway.invoke(
                call.case.candidate.prompt_id,
                call.case.request,
                envelope.trusted_context,
                budget=CallBudget(max_cost_usd=10.0),
            )
        )
    assert exc.value.code == "PHASE9_LONG_CONTEXT_PRICING_NOT_AUTHORIZED"
    assert inner.calls == adapter.calls == counters.provider_calls == 0


def test_request_above_live_route_cap_fails_before_adapter_transport(
    prepared: px.PreparedExecution,
    pricing: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = prepared.calls[0]
    inner = _UsageAdapter(
        AdapterResult(
            raw_output={},
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
        )
    )
    counters = px.SafetyCounters()
    adapter = px.PricingBoundCapturingAdapter(
        inner, pricing=pricing, counters=counters, max_requests=1
    )
    monkeypatch.setattr(
        px,
        "estimate_openai_input_tokens",
        lambda *_args, **_kwargs: px.OPENAI_MAX_INPUT_TOKENS + 1,
    )
    gateway = px._gateway_for(
        candidate=call.case.candidate,
        adapter=adapter,
        cap=10.0,
        pricing=pricing,
        job_id="job_v202_route_cap_fail_closed",
    )
    envelope = px._envelope_for(
        call.case.candidate.prompt_id, call.case.request
    )
    with pytest.raises(GatewayRouteBlocked, match="INPUT_TOKEN_LIMIT_EXCEEDED"):
        asyncio.run(
            gateway.invoke(
                call.case.candidate.prompt_id,
                call.case.request,
                envelope.trusted_context,
                budget=CallBudget(max_cost_usd=10.0),
            )
        )
    assert inner.calls == adapter.calls == counters.provider_calls == 0


def test_exact_projection_uses_real_estimator_and_retry_reserve(
    projection: dict[str, Any],
) -> None:
    rows = projection["logical_calls"]
    expected_inputs = {
        "PP-A01-P04-001": 52_071,
        "PP-A01-S03-P06-G01": 23_548,
        "N3F-act_01_luz_y_plantines-submission_01": 19_054,
        "PP-A01-S01-P07-O01": 18_942,
        "PP-A01-S05-P07-O02": 40_605,
        "PP-A02-S02-P07-O01": 18_911,
        "PP-A04-S04-P07-O01": 24_023,
        "PP-A04-S06-P07-O01": 24_010,
        "PP-A08-S02-P07-O02": 24_989,
        "PP-A03-P09-F01": 52_631,
    }
    assert len(rows) == 30
    assert {
        row["provider_identity"]: row["estimated_input_tokens"] for row in rows
    } == expected_inputs
    assert all(row["run_index"] in {1, 2, 3} for row in rows)
    assert all(row["context_classification"] == "SHORT_CONTEXT_STANDARD" for row in rows)
    assert all(row["runtime_route_max_input_tokens"] == 250_000 for row in rows)
    assert projection["mechanical_short_context_proof"] == {
        "all_estimated_inputs_within_route_cap": True,
        "disposition_beyond_route_cap_or_threshold": (
            "FAIL_CLOSED_BEFORE_TRANSPORT"
        ),
        "long_context_logical_calls": 0,
        "long_context_pricing_authorized": False,
        "maximum_estimated_input_tokens": 52_631,
        "observed_route_caps": [250_000],
        "official_long_context_threshold": 272_000,
        "route_cap_below_long_context_threshold": True,
        "runtime_route_max_input_tokens": 250_000,
    }
    assert projection["technical_retry_reserve"] == {
        "A_PRIMARY_30_CALL_RESERVATION_USD": 1.51876725,
        "B_MAX_TECHNICAL_RETRY_INCREMENT_USD": 1.51876725,
        "C_ABSOLUTE_RETRY_INCLUSIVE_RESERVATION_USD": 3.0375345,
        "derivation": "ONE_FULL_CONSERVATIVE_CALL_RESERVATION_PER_LOGICAL_CALL",
        "max_technical_retries_per_logical_call": 1,
        "retryable_technical_codes": [
            "PROVIDER_CONNECTION",
            "PROVIDER_RATE_LIMIT",
            "PROVIDER_TIMEOUT",
            "PROVIDER_TRANSIENT_STATUS",
        ],
    }


def test_projection_aggregates_and_proposed_caps_are_exact(
    projection: dict[str, Any],
) -> None:
    by_stage = projection["aggregates"]["by_stage"]
    assert {
        stage: row["primary_call_conservative_reservation_usd"]
        for stage, row in by_stage.items()
    } == {
        "P04": 0.9665325,
        "P06": 0.1471515,
        "P07": 0.32961,
        "P09": 0.07547325,
    }
    by_model = projection["aggregates"]["by_model"]
    assert by_model["gpt-5.6-terra"][
        "primary_call_conservative_reservation_usd"
    ] == 0.9665325
    assert by_model["gpt-5.6-luna"][
        "primary_call_conservative_reservation_usd"
    ] == 0.55223475
    assert projection["proposed_caps"] == {
        "headroom_policy": {
            "explanation": (
                "10_PERCENT_DETERMINISTIC_HEADROOM_ROUNDED_UP; "
                "NO_SPEND_AUTHORIZED"
            ),
            "multiplier": 1.1,
            "per_call_round_up_usd": 0.001,
            "rung_and_outer_round_up_usd": 0.01,
        },
        "outer_primary_cap_usd": 1.68,
        "outer_retry_inclusive_cap_usd": 3.35,
        "per_call_cap_by_candidate_usd": {
            "P04-C1-TERRA-HIGH": 0.355,
            "P06-C1-LUNA-HIGH": 0.028,
            "P07-C1-LUNA-HIGH": 0.025,
            "P09-C1-LUNA-HIGH": 0.028,
        },
        "per_candidate_rung_caps_usd": {
            "P04-C1-TERRA-HIGH": {
                "primary_usd": 1.07,
                "retry_inclusive_usd": 2.13,
            },
            "P06-C1-LUNA-HIGH": {
                "primary_usd": 0.17,
                "retry_inclusive_usd": 0.33,
            },
            "P07-C1-LUNA-HIGH": {
                "primary_usd": 0.37,
                "retry_inclusive_usd": 0.73,
            },
            "P09-C1-LUNA-HIGH": {
                "primary_usd": 0.09,
                "retry_inclusive_usd": 0.17,
            },
        },
        "status": "PROPOSED_CAPS_NOT_AUTHORIZED",
    }


def test_ordered_population_and_all_protected_publications_are_unchanged(
    prepared: px.PreparedExecution,
) -> None:
    predecessor = px._read_json(px.PREDECESSOR_REQUEST_AUTHORITY_PATH)
    old_identities = px.ordered_logical_call_identities_from_request_authority(
        predecessor
    )
    new_identities = [call.identity() for call in prepared.calls]
    assert old_identities == new_identities
    assert px.canonical_hash(new_identities) == (
        px.EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH
    )
    assert prepared.boundary["high_smoke_plan"]["decomposition"] == {
        "SEMANTIC/P04/SMOKE/HIGH": 3,
        "SEMANTIC/P06/SMOKE/HIGH": 3,
        "CONTRACTUAL_HARD_SAFETY/P06/N3_SAFETY_SMOKE/HIGH": 3,
        "SEMANTIC/P07/SMOKE/HIGH": 18,
        "SEMANTIC/P09/SMOKE/HIGH": 3,
    }
    for relative, expected in px.PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES.items():
        assert px._file_hash(px.REPOSITORY_ROOT / relative) == expected
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "evaluation/semantic_benchmark/v1_3_5",
            "reports/semantic_benchmark/v1_3_5",
            "evaluation/phase9_execution/v2_0_0",
            "reports/phase9_execution/v2_0_0",
            "evaluation/phase9_execution/v2_0_1",
            "reports/phase9_execution/v2_0_1",
            "evaluation/phase9_execution/v2_0_2",
            "reports/phase9_execution/v2_0_2",
        ],
        cwd=px.REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""


def test_construction_safety_counters_and_authorization_absence(
    projection: dict[str, Any],
) -> None:
    assert projection["safety_counters"] == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "transport_factory_calls": 0,
        "real_provider_transport": False,
        "pricing_snapshot": "VERIFIED_CURRENT_OFFICIAL_PRICING",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }
    assert not px.BILLABLE_AUTHORIZATION_PATH.exists()
    assert px.PREDECESSOR_AUTHORIZATION_PATH.is_file()
    assert projection["status"] == "PROPOSED_CAPS_NOT_AUTHORIZED"
    assert projection["authorization_state"] == "NOT_AUTHORIZED"
    assert projection["billable_authorization"] == "NONE"
