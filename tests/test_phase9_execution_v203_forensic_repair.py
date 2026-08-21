"""Offline forensic-repair regressions for phase9-execution/2.0.3."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

import pytest

from comprehension_verification import phase9_execution as px
from comprehension_verification.model_gateway.gateway import (
    AuthenticationProviderError,
    AuthorizationProviderError,
    ContextFailure,
    ContextFailureCode,
    GatewayContextError,
    ModelUnavailableProviderError,
    PermanentProviderError,
    ProviderBudgetError,
    ProviderTimeoutError,
    RateLimitProviderError,
    SafetyBlockProviderError,
    TransientProviderError,
    ValidationPhase,
)
from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    DeterministicMockFactory,
    MockBehavior,
)
from comprehension_verification.model_gateway.openai_routes import (
    build_openai_routes,
)
from scripts import build_phase9_forensic_repair as forensic


@pytest.fixture(scope="module")
def prepared() -> px.PreparedExecution:
    return px.prepare_phase9_execution()


@pytest.fixture(scope="module")
def reproduction() -> dict[str, Any]:
    return forensic.build_async_reproduction()


def _valid_result(prompt_id: str, request: Any, route: Any) -> AdapterResult:
    behavior = (
        MockBehavior.ABSTAIN
        if prompt_id == "P07_QUESTION_BUILD_V1"
        else MockBehavior.HAPPY
    )
    raw = (
        DeterministicMockFactory()
        .output_for(prompt_id, request, behavior)
        .model_dump(mode="json")
    )
    return AdapterResult(
        raw_output=raw,
        input_tokens=101,
        cached_input_tokens=11,
        cache_write_input_tokens=21,
        output_tokens=31,
        reasoning_tokens=17,
        effective_model=route.model,
        output_hash=px.canonical_hash(raw),
        provider_request_id_hash="sha256:" + "2" * 64,
        provider_schema_valid=True,
    )


class _RetryOnceAdapter:
    def __init__(self, failure_factory: Callable[[], BaseException]) -> None:
        self.failure_factory = failure_factory
        self.calls = 0

    async def invoke(self, **kwargs: Any) -> AdapterResult:
        self.calls += 1
        if self.calls == 1:
            raise self.failure_factory()
        return _valid_result(kwargs["prompt_id"], kwargs["request"], kwargs["route"])


class _AlwaysFailAdapter:
    def __init__(self, failure_factory: Callable[[], BaseException]) -> None:
        self.failure_factory = failure_factory
        self.calls = 0

    async def invoke(self, **_kwargs: Any) -> AdapterResult:
        self.calls += 1
        raise self.failure_factory()


class _InvalidResponseAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, **kwargs: Any) -> AdapterResult:
        self.calls += 1
        raw = {
            "unsafe_student_material": "DO_NOT_PERSIST_THIS_RAW_PROVIDER_BODY"
        }
        return AdapterResult(
            raw_output=raw,
            input_tokens=111,
            cached_input_tokens=12,
            cache_write_input_tokens=13,
            output_tokens=14,
            reasoning_tokens=15,
            effective_model=kwargs["route"].model,
            output_hash=px.canonical_hash(raw),
            provider_request_id_hash="sha256:" + "3" * 64,
            provider_schema_valid=False,
            provider_schema_issues=(("required", "/status"),),
        )


def _execute_one(
    call: px.LogicalCall,
    inner: Any,
) -> tuple[list[dict[str, Any]], px.CompletedCall | None, px.PricingBoundCapturingAdapter]:
    authorization = forensic._synthetic_authorization()
    adapter = px.PricingBoundCapturingAdapter(
        inner,
        pricing=forensic._pricing(),
        counters=px.SafetyCounters(),
        max_requests=2,
    )
    attempts, output = asyncio.run(
        px._execute_call(
            call=call,
            adapter=adapter,
            authorization=authorization,
            pricing=forensic._pricing(),
            account=px.CostAccount(authorization),
        )
    )
    return attempts, output, adapter


def test_old_per_call_event_loop_pattern_reproduces_failure(
    reproduction: dict[str, Any],
) -> None:
    old = reproduction["old_per_call_asyncio_run"]
    assert old["orchestration_shape"] == (
        "ONE_PERSISTENT_ADAPTER_PLUS_ASYNCIO_RUN_PER_LOGICAL_CALL"
    )
    assert old["planned_logical_calls"] == old["attempt_rows"] == 30
    assert old["completed_logical_calls"] == 1
    assert old["failed_logical_calls"] == 29
    assert old["cross_loop_lifecycle_failures"] == 29
    assert old["bound_loop_closed_after_first_asyncio_run"] is True
    assert old["result"] == "CROSS_EVENT_LOOP_FAILURE_REPRODUCED"


def test_new_single_loop_population_eliminates_cross_loop_failure(
    reproduction: dict[str, Any],
) -> None:
    new = reproduction["new_single_population_asyncio_run"]
    assert new["planned_logical_calls"] == new["attempt_rows"] == 30
    assert new["completed_logical_calls"] == new["provider_invocations"] == 30
    assert new["failed_logical_calls"] == 0
    assert new["event_loops_seen"] == 1
    assert new["cross_loop_lifecycle_failures"] == 0


def test_thirty_calls_are_sequential_and_keep_frozen_order(
    reproduction: dict[str, Any],
) -> None:
    new = reproduction["new_single_population_asyncio_run"]
    assert new["frozen_order_preserved"] is True
    assert new["orchestration_shape"] == (
        "ONE_ASYNCIO_RUN_FOR_SEQUENTIAL_AUTHORIZED_POPULATION"
    )


def test_async_adapter_close_occurs_in_same_live_loop(
    reproduction: dict[str, Any],
) -> None:
    new = reproduction["new_single_population_asyncio_run"]
    assert new["adapter_closed"] is True
    assert new["adapter_close_same_live_loop"] is True


@pytest.mark.parametrize(
    ("reason", "failure_factory"),
    [
        ("PROVIDER_TIMEOUT", lambda: ProviderTimeoutError("PROVIDER_TIMEOUT")),
        (
            "PROVIDER_CONNECTION",
            lambda: TransientProviderError("PROVIDER_CONNECTION"),
        ),
        (
            "PROVIDER_TRANSIENT_STATUS",
            lambda: TransientProviderError("PROVIDER_TRANSIENT_STATUS"),
        ),
        (
            "PROVIDER_RATE_LIMIT",
            lambda: RateLimitProviderError("PROVIDER_RATE_LIMIT"),
        ),
    ],
)
def test_each_retryable_provider_reason_gets_exactly_one_outer_retry(
    prepared: px.PreparedExecution,
    reason: str,
    failure_factory: Callable[[], BaseException],
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    inner = _RetryOnceAdapter(failure_factory)
    attempts, output, adapter = _execute_one(call, inner)
    assert output is not None
    assert inner.calls == adapter.calls == 2
    assert [row["attempt_index"] for row in attempts] == [1, 2]
    assert [row["status"] for row in attempts] == ["FAILED", "COMPLETED"]
    assert attempts[0]["provider_reason_code"] == reason
    assert attempts[0]["failure_class"] == "RETRYABLE_PROVIDER_FAILURE"
    assert attempts[0]["technical_retry_disposition"] == (
        "ONE_AUTHORIZED_TECHNICAL_RETRY"
    )
    identity_keys = set(call.identity()) | {"logical_call_id"}
    expected_identity = {**call.identity(), "logical_call_id": call.logical_call_id}
    for row in attempts:
        assert {key: row[key] for key in identity_keys} == expected_identity
    assert attempts[1]["candidate_id"] == attempts[0]["candidate_id"]
    assert attempts[1]["reasoning_rung"] == attempts[0]["reasoning_rung"]


@pytest.mark.parametrize(
    "failure_factory",
    [
        lambda: AuthenticationProviderError("PROVIDER_AUTHENTICATION"),
        lambda: AuthorizationProviderError("PROVIDER_AUTHORIZATION"),
        lambda: ProviderBudgetError("PROVIDER_BUDGET_OR_QUOTA"),
        lambda: PermanentProviderError("PROVIDER_INVALID_REQUEST"),
        lambda: ModelUnavailableProviderError("PROVIDER_MODEL_UNAVAILABLE"),
        lambda: SafetyBlockProviderError("PROVIDER_SAFETY_REFUSAL"),
        lambda: PermanentProviderError("PROVIDER_SCHEMA_FAILURE"),
        lambda: RuntimeError("unsafe provider body must never persist"),
    ],
)
def test_permanent_and_unexpected_provider_errors_get_zero_retries(
    prepared: px.PreparedExecution,
    failure_factory: Callable[[], BaseException],
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    inner = _AlwaysFailAdapter(failure_factory)
    attempts, output, adapter = _execute_one(call, inner)
    assert output is None
    assert inner.calls == adapter.calls == 1
    assert len(attempts) == 1
    assert attempts[0]["attempt_index"] == 1
    assert attempts[0]["technical_retry_disposition"] != (
        "ONE_AUTHORIZED_TECHNICAL_RETRY"
    )


def test_underlying_reason_survives_gateway_provider_error_wrapping(
    prepared: px.PreparedExecution,
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    attempts, output, _adapter = _execute_one(
        call,
        _RetryOnceAdapter(
            lambda: TransientProviderError("PROVIDER_CONNECTION")
        ),
    )
    assert output is not None
    first = attempts[0]
    assert first["failure_code"] == "MODEL_PROVIDER_ERROR"
    assert first["provider_reason_code"] == "PROVIDER_CONNECTION"
    assert first["provider_invocations"][0]["provider_reason_code"] == (
        "PROVIDER_CONNECTION"
    )
    assert "message" not in first["provider_invocations"][0]


def test_context_failure_codes_and_post_response_usage_survive(
    prepared: px.PreparedExecution,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P04")
    inner = forensic.EventLoopBoundFakeAdapter()

    def context_gateway(
        *,
        candidate: px.AuthorizedCandidate,
        adapter: Any,
        cap: float,
        pricing: Any,
        job_id: str,
    ) -> Any:
        del pricing, job_id
        route = build_openai_routes(
            max_call_cost_usd=cap,
            route_profile_id=candidate.route_profile_id,
        )[candidate.prompt_id]

        class _ContextFailureGateway:
            async def invoke(
                self,
                prompt_id: str,
                request: Any,
                trusted_context: Any,
                budget: Any,
            ) -> None:
                del trusted_context, budget
                await adapter.invoke(
                    prompt_id=prompt_id,
                    request=request,
                    envelope=object(),
                    route=route,
                    attempt=1,
                    behavior=MockBehavior.HAPPY,
                )
                raise GatewayContextError(
                    "content-free deterministic context failure",
                    failure=ContextFailure(
                        phase=ValidationPhase.OUTPUT,
                        codes=(ContextFailureCode.P04_SOURCE_COVERAGE_MISMATCH,),
                    ),
                )

        return _ContextFailureGateway()

    monkeypatch.setattr(px, "_gateway_for", context_gateway)
    attempts, output, _adapter = _execute_one(call, inner)
    assert output is None
    assert len(attempts) == 1
    row = attempts[0]
    assert row["failure_code"] == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    assert row["failure_class"] == "DETERMINISTIC_CONTEXT_FAILURE"
    assert row["context_failure_codes"] == ["P04_SOURCE_COVERAGE_MISMATCH"]
    assert row["technical_retry_disposition"] == "DETERMINISTIC_FAILURE_NO_RETRY"
    assert row["provider_prompt_id"] == call.case.candidate.prompt_id
    assert row["input_tokens"] == 100
    assert row["cached_input_tokens"] == 10
    assert row["cache_write_input_tokens"] == 20
    assert row["output_tokens"] == 100
    assert row["reasoning_tokens"] == 7
    assert row["provider_output_hash"].startswith("sha256:")
    assert row["provider_request_id_hash"].startswith("sha256:")
    assert row["provider_schema_valid"] is True
    assert row["actual_cost_usd"] > 0


def test_schema_failure_persists_only_safe_structural_and_usage_evidence(
    prepared: px.PreparedExecution,
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    attempts, output, _adapter = _execute_one(call, _InvalidResponseAdapter())
    assert output is None
    assert len(attempts) == 1
    row = attempts[0]
    assert row["failure_class"] == "DETERMINISTIC_STRUCTURAL_FAILURE"
    assert row["input_tokens"] == 111
    assert row["cached_input_tokens"] == 12
    assert row["cache_write_input_tokens"] == 13
    assert row["output_tokens"] == 14
    assert row["reasoning_tokens"] == 15
    assert row["provider_schema_valid"] is False
    assert row["provider_schema_issues"] == [["required", "/status"]]
    serialized = json.dumps(row, sort_keys=True)
    assert "DO_NOT_PERSIST_THIS_RAW_PROVIDER_BODY" not in serialized
    assert "unsafe_student_material" not in serialized
    assert "raw_output" not in serialized


def test_completed_attempt_persists_reasoning_tokens(
    prepared: px.PreparedExecution,
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")

    class _SuccessAdapter:
        async def invoke(self, **kwargs: Any) -> AdapterResult:
            return _valid_result(
                kwargs["prompt_id"], kwargs["request"], kwargs["route"]
            )

    attempts, output, _adapter = _execute_one(call, _SuccessAdapter())
    assert output is not None
    assert attempts[0]["status"] == "COMPLETED"
    assert attempts[0]["reasoning_tokens"] == 17
    assert attempts[0]["provider_invocations"][0]["reasoning_tokens"] == 17


def test_unsafe_exception_text_and_raw_error_body_never_persist(
    prepared: px.PreparedExecution,
) -> None:
    marker = "SECRET_STUDENT_TEXT_FROM_PROVIDER_BODY"
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    attempts, output, _adapter = _execute_one(
        call, _AlwaysFailAdapter(lambda: RuntimeError(marker))
    )
    assert output is None
    serialized = json.dumps(attempts, sort_keys=True)
    assert marker not in serialized
    assert "raw_output" not in serialized
    assert "exception_text" not in serialized
    assert attempts[0]["provider_invocations"][0]["failure_code"] == (
        "ADAPTER_UNEXPECTED_EXCEPTION"
    )


def test_historical_v202_and_v135_bytes_are_unchanged(
    prepared: px.PreparedExecution,
) -> None:
    for relative, expected in px.PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES.items():
        assert px._file_hash(px.REPOSITORY_ROOT / relative) == expected
    for relative, binding in prepared.boundary["frozen_artifacts"].items():
        assert px._file_hash(px.REPOSITORY_ROOT / relative) == binding["file_sha256"]
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "evaluation/semantic_benchmark/v1_3_5",
            "reports/semantic_benchmark/v1_3_5",
            "evaluation/phase9_execution/v2_0_2",
            "reports/phase9_execution/v2_0_2",
        ],
        cwd=px.REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def test_successor_population_and_no_carry_forward_are_exact(
    prepared: px.PreparedExecution,
) -> None:
    identities = [call.identity() for call in prepared.calls]
    assert len(identities) == 30
    assert px.canonical_hash(identities) == (
        "sha256:fef890ffa1b12e8717edd7cb5e13f7cdbd78b1e3eb9284aea20a21b29f45553e"
    )
    repair = forensic.build_repair_report(
        forensic.build_async_reproduction(),
        forensic.build_forensic_classification(forensic.build_async_reproduction()),
    )
    assert repair["v2_0_2_successful_outputs_carried_forward"] is False
    assert repair["historical_output_hashes_present_in_successor_documents"] == []
    assert repair["successor_execution_manifest_count"] == 0


def test_v203_has_no_authorization_and_stops_before_credentials_or_transport(
    tmp_path: Path,
) -> None:
    credential_calls = 0
    transport_calls = 0

    def credential_resolver() -> None:
        nonlocal credential_calls
        credential_calls += 1
        return None

    def adapter_factory(_key: Any) -> object:
        nonlocal transport_calls
        transport_calls += 1
        return object()

    assert not px.BILLABLE_AUTHORIZATION_PATH.exists()
    with pytest.raises(px.Phase9ExecutionError) as caught:
        px.run_phase9b_smoke(
            created_by="offline-test",
            authorization_path=tmp_path / "missing-authorization.json",
            credential_resolver=credential_resolver,
            adapter_factory=adapter_factory,
            allow_billable=True,
        )
    assert caught.value.code == "EXPLICIT_HASH_BOUND_AUTHORIZATION_REQUIRED"
    assert credential_calls == transport_calls == 0
    assert caught.value.safety_counters == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "transport_factory_calls": 0,
        "real_provider_transport": False,
        "pricing_refresh": "VERIFIED_CURRENT_OFFICIAL_PRICING",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }


def test_historical_v202_authorization_ledger_cannot_be_consumed_twice() -> None:
    authorization = px._read_json(px.PREDECESSOR_AUTHORIZATION_PATH)
    ledger = px.REPOSITORY_ROOT / authorization["ledger_path"]
    before = ledger.read_bytes()
    with pytest.raises(px.Phase9ExecutionError) as caught:
        px._claim_authorization_once(authorization)
    assert caught.value.code == "PHASE9_AUTHORIZATION_ALREADY_CONSUMED"
    assert ledger.read_bytes() == before


def test_published_forensic_reports_keep_proven_inference_unknown_separate() -> None:
    reproduction, classification, repair = forensic.check()
    assert classification["proven"]["provider_invocations"] == 30
    assert classification["proven"]["completed_logical_calls"] == 12
    assert classification["proven"]["failure_counts"] == {
        "MODEL_PROVIDER_ERROR": 15,
        "MODEL_CONTEXT_NOT_ALLOWLISTED": 3,
    }
    assert classification["proven"]["context_error_positions"] == [1, 3, 29]
    assert classification["inference"]["limit"] == (
        "CONSISTENCY_INFERENCE_ONLY_NOT_HISTORICAL_ROOT_CAUSE_PROOF"
    )
    assert "NOT_PERSISTED" in classification["unknown"][
        "underlying_reason_code_for_15_model_provider_error_rows"
    ]
    assert classification["historical_rows_relabelled"] is False
    assert reproduction["safety_counters"]["provider_calls"] == 0
    assert repair["billable_authorization_v2_0_3"] == "NONE"
    assert repair["high_smoke_v2_0_3"] == "NOT_EXECUTED"
