"""Carry the historical execution closure into phase9-execution/2.0.3.

Every adapter in this module is in-process and deterministic. No test resolves
credentials, constructs the OpenAI transport, refreshes pricing, authorizes a
billable run, executes HIGH-SMOKE, or calls an adjudicator.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

import pytest

from comprehension_verification import phase9_execution as px
from comprehension_verification.model_gateway.gateway import (
    GatewayConfig,
    GatewayMode,
    ModelGateway,
    PermanentProviderError,
)
from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    DeterministicMockFactory,
    MockBehavior,
)
from comprehension_verification.model_gateway.openai_routes import (
    build_openai_routes,
)
from comprehension_verification.p06_n3_protocol import N3ProtocolError
from scripts import run_phase9_smoke as smoke_cli


def _pricing() -> dict[str, Any]:
    material = {
        "long_context_threshold": px.LONG_CONTEXT_THRESHOLD,
        "long_context_pricing_authorized": False,
        "models": {
            candidate.model: {
                "input_per_million_usd": 0.10,
                "cached_input_per_million_usd": 0.01,
                "cache_write_per_million_usd": 0.125,
                "output_per_million_usd": 0.20,
            }
            for candidate in px.AUTHORIZED_CANDIDATES
        }
    }
    return {**material, "pricing_snapshot_hash": px._hash(material)}


def _authorization() -> dict[str, Any]:
    candidate_ids = [item.candidate_id for item in px.AUTHORIZED_CANDIDATES]
    return {
        "authorization_id": "auth_synthetic_test_only",
        "authorization_hash": "sha256:" + "a" * 64,
        "per_call_caps_usd": {candidate_id: 1.0 for candidate_id in candidate_ids},
        "rung_primary_caps_usd": {
            candidate_id: 100.0 for candidate_id in candidate_ids
        },
        "rung_retry_inclusive_caps_usd": {
            candidate_id: 100.0 for candidate_id in candidate_ids
        },
        "outer_primary_cap_usd": 100.0,
        "outer_retry_inclusive_cap_usd": 100.0,
    }


class FakeProviderAdapter:
    """Production-shaped adapter result with no SDK client or network."""

    def __init__(
        self,
        *,
        fail_all: bool = False,
        fail_invocations: frozenset[int] = frozenset(),
        extra_p06_field: tuple[str, Any] | None = None,
    ) -> None:
        self.fail_all = fail_all
        self.fail_invocations = fail_invocations
        self.extra_p06_field = extra_p06_field
        self.prompt_ids: list[str] = []

    async def invoke(
        self,
        *,
        prompt_id: str,
        request: Any,
        envelope: Any,
        route: Any,
        attempt: int,
        behavior: Any,
    ) -> AdapterResult:
        del envelope, attempt, behavior
        self.prompt_ids.append(prompt_id)
        invocation_number = len(self.prompt_ids)
        if self.fail_all or invocation_number in self.fail_invocations:
            raise PermanentProviderError("SYNTHETIC_OFFLINE_FAILURE")

        mock_behavior = (
            MockBehavior.ABSTAIN
            if prompt_id == "P07_QUESTION_BUILD_V1"
            else MockBehavior.HAPPY
        )
        raw = (
            DeterministicMockFactory()
            .output_for(prompt_id, request, mock_behavior)
            .model_dump(mode="json")
        )
        provider_schema_valid = True
        provider_schema_issues: tuple[tuple[str, str], ...] = ()
        if (
            prompt_id == "P06_EVIDENCE_MAP_V1"
            and self.extra_p06_field is not None
        ):
            key, value = self.extra_p06_field
            raw[key] = value
            provider_schema_valid = False
            provider_schema_issues = (("additionalProperties", "/"),)
        return AdapterResult(
            raw_output=raw,
            input_tokens=100,
            cached_input_tokens=0,
            cache_write_input_tokens=20,
            output_tokens=100,
            effective_model=route.model,
            output_hash=px.canonical_hash(raw),
            provider_request_id_hash="sha256:" + "1" * 64,
            provider_schema_valid=provider_schema_valid,
            provider_schema_issues=provider_schema_issues,
        )


def _capturing_adapter(
    inner: FakeProviderAdapter,
) -> tuple[px.PricingBoundCapturingAdapter, px.SafetyCounters]:
    counters = px.SafetyCounters()
    return (
        px.PricingBoundCapturingAdapter(
            inner,
            pricing=_pricing(),
            counters=counters,
            max_requests=60,
        ),
        counters,
    )


def _execute_population(
    prepared: px.PreparedExecution,
    inner: FakeProviderAdapter,
) -> dict[str, Any]:
    authorization = _authorization()
    pricing = _pricing()
    adapter, counters = _capturing_adapter(inner)
    account = px.CostAccount(authorization)
    attempts, outputs = asyncio.run(
        px._execute_population(
            calls=prepared.calls,
            adapter=adapter,
            authorization=authorization,
            pricing=pricing,
            account=account,
        )
    )
    packets = px.build_blind_packet_sets(calls=prepared.calls, outputs=outputs)
    completion = px.generation_completion_summary(
        calls=prepared.calls,
        outputs=outputs,
        attempts=attempts,
        packets=packets,
    )
    return {
        "authorization": authorization,
        "pricing": pricing,
        "adapter": adapter,
        "inner": inner,
        "counters": counters,
        "account": account,
        "attempts": attempts,
        "outputs": outputs,
        "packets": packets,
        "completion": completion,
    }


@pytest.fixture(scope="module")
def prepared() -> px.PreparedExecution:
    return px.prepare_phase9_execution()


@pytest.fixture(scope="module")
def complete_generation(prepared: px.PreparedExecution) -> dict[str, Any]:
    return _execute_population(prepared, FakeProviderAdapter())


def _zero_safety_counters(counters: Mapping[str, Any]) -> None:
    assert counters == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "transport_factory_calls": 0,
        "real_provider_transport": False,
        "pricing_refresh": "NOT_PERFORMED",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }


def _activate_scratch_runtime(
    *,
    prepared: px.PreparedExecution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, px.FrozenAuthorityPaths]:
    original_root = px.REPOSITORY_ROOT
    scratch_root = tmp_path / "runtime"
    copy_paths = (
        px.REQUIRED_SOURCE_BINDING_PATHS
        | set(px.PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES)
        | {str(px.CURRENT_PRICING_PATH.relative_to(original_root))}
    )
    for relative in copy_paths:
        source = original_root / relative
        destination = scratch_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for relative_root in (
        Path("evaluation/semantic_benchmark/v1_3_5"),
        Path("reports/semantic_benchmark/v1_3_5"),
    ):
        shutil.copytree(original_root / relative_root, scratch_root / relative_root)

    original_paths = px.FrozenAuthorityPaths()
    scratch_paths = px.FrozenAuthorityPaths(
        **{
            name: scratch_root / path.relative_to(original_root)
            for name, path in original_paths.items()
        }
    )
    monkeypatch.setattr(px, "REPOSITORY_ROOT", scratch_root)
    monkeypatch.setattr(
        px,
        "V135_DEFINITION_ROOT",
        scratch_root / "evaluation/semantic_benchmark/v1_3_5",
    )
    monkeypatch.setattr(
        px,
        "V135_REPORT_ROOT",
        scratch_root / "reports/semantic_benchmark/v1_3_5",
    )
    monkeypatch.setattr(
        px,
        "HIGH_SMOKE_REQUEST_AUTHORITY_PATH",
        scratch_root
        / "evaluation/phase9_execution/v2_0_3/high_smoke_request_authority.json",
    )
    monkeypatch.setattr(
        px,
        "CURRENT_PRICING_PATH",
        scratch_root / "evaluation/phase9_execution/v2_0_3/current_pricing.json",
    )
    monkeypatch.setattr(
        px,
        "PREDECESSOR_REQUEST_AUTHORITY_PATH",
        scratch_root
        / "evaluation/phase9_execution/v2_0_2/high_smoke_request_authority.json",
    )
    monkeypatch.setattr(
        px,
        "PREDECESSOR_EXECUTION_REPORT_ROOT",
        scratch_root / "reports/phase9_execution/v2_0_2",
    )
    monkeypatch.setattr(
        px,
        "PREDECESSOR_AUTHORIZATION_PATH",
        scratch_root
        / "evaluation/phase9_execution/v2_0_2/billable_authorization.json",
    )
    monkeypatch.setattr(
        px,
        "PREDECESSOR_EXECUTION_MANIFEST_PATH",
        scratch_root
        / "reports/phase9_execution/v2_0_2/executions/exec-phase9v202-b820f4bfa94de537/execution_manifest.json",
    )
    monkeypatch.setattr(
        px,
        "PREDECESSOR_POST_EXECUTION_AUDIT_PATH",
        scratch_root
        / "reports/phase9_execution/v2_0_2/post_execution_audit_exec-phase9v202-b820f4bfa94de537.json",
    )
    monkeypatch.setattr(
        px,
        "__file__",
        str(scratch_root / "src/comprehension_verification/phase9_execution.py"),
    )
    assert prepared.boundary["execution_version"] == px.PHASE9_EXECUTION_VERSION
    return scratch_root, scratch_paths


def _assert_public_runtime_drift_blocks(
    *,
    prepared: px.PreparedExecution,
    scratch_paths: px.FrozenAuthorityPaths,
) -> None:
    credential_calls = 0
    factory_calls = 0

    def credential_resolver() -> None:
        nonlocal credential_calls
        credential_calls += 1
        return None

    def adapter_factory(_key: Any) -> object:
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.run_phase9b_smoke(
            created_by="test",
            allow_billable=True,
            credential_resolver=credential_resolver,
            adapter_factory=adapter_factory,
            authority_paths=scratch_paths,
            boundary_override=prepared.boundary,
            request_authority_override=prepared.request_authority,
        )
    assert exc.value.code == "PHASE9_EXECUTION_SOURCE_BINDING_MISMATCH"
    assert credential_calls == factory_calls == 0
    _zero_safety_counters(exc.value.safety_counters)


def test_runtime_boundary_binds_exact_explicit_inventory(
    prepared: px.PreparedExecution,
) -> None:
    boundary = prepared.boundary
    inventory = boundary["runtime_dependency_inventory"]
    assert set(boundary["source_bindings"]) == px.REQUIRED_SOURCE_BINDING_PATHS
    assert {row["path"] for row in inventory} == px.REQUIRED_SOURCE_BINDING_PATHS
    assert len(inventory) == len(px.REQUIRED_SOURCE_BINDING_PATHS)
    assert boundary["runtime_dependency_inventory_hash"] == px.canonical_hash(
        inventory
    )
    for row in inventory:
        assert row["role"] == px.RUNTIME_SOURCE_BINDING_ROLES[row["path"]]
        assert row["file_sha256"] == boundary["source_bindings"][row["path"]]
        assert row["file_sha256"] == px._file_hash(px.REPOSITORY_ROOT / row["path"])


def test_runtime_boundary_rejects_inventory_omission(
    prepared: px.PreparedExecution,
) -> None:
    mutated = deepcopy(prepared.boundary)
    mutated["runtime_dependency_inventory"].pop()
    mutated["runtime_dependency_inventory_hash"] = px.canonical_hash(
        mutated["runtime_dependency_inventory"]
    )
    mutated["execution_boundary_hash"] = px._self_hash(
        mutated, "execution_boundary_hash"
    )
    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.prepare_phase9_execution(
            boundary_override=mutated,
            request_authority_override=prepared.request_authority,
        )
    assert exc.value.code == "PHASE9_EXECUTION_SOURCE_INVENTORY_MISMATCH"


def test_openai_developer_instruction_source_drift_blocks_public_preparation(
    prepared: px.PreparedExecution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch_root, scratch_paths = _activate_scratch_runtime(
        prepared=prepared, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    target = (
        scratch_root
        / "src/comprehension_verification/model_gateway/openai_routes.py"
    )
    source = target.read_text(encoding="utf-8")
    needle = '        + "\\nResolve only this task. Do not generate objects for another stage."\n'
    assert needle in source
    target.write_text(
        source.replace(
            needle,
            '        + "\\nCONTROLLED_RUNTIME_DRIFT"\n' + needle,
            1,
        ),
        encoding="utf-8",
    )
    _assert_public_runtime_drift_blocks(
        prepared=prepared, scratch_paths=scratch_paths
    )


def test_gateway_call_control_source_drift_blocks_public_preparation(
    prepared: px.PreparedExecution,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch_root, scratch_paths = _activate_scratch_runtime(
        prepared=prepared, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    target = scratch_root / "src/comprehension_verification/model_gateway/gateway.py"
    source = target.read_text(encoding="utf-8")
    needle = "retry_limit = min(self.config.max_retries, spec.max_transient_retries)"
    assert needle in source
    target.write_text(source.replace(needle, f"{needle} + 1", 1), encoding="utf-8")
    _assert_public_runtime_drift_blocks(
        prepared=prepared, scratch_paths=scratch_paths
    )


def test_qualification_gateway_exposes_only_the_planned_primary_route(
    prepared: px.PreparedExecution,
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    inner = FakeProviderAdapter()
    adapter, _counters = _capturing_adapter(inner)
    gateway = px._gateway_for(
        candidate=call.case.candidate,
        adapter=adapter,
        cap=1.0,
        pricing=_pricing(),
        job_id="job_route_test",
    )
    assert set(gateway.resolver.real_routes) == {call.case.candidate.prompt_id}
    assert "P11_SCHEMA_REPAIR_V1" not in gateway.resolver.real_routes
    assert prepared.boundary["qualification_execution_policy"] == {
        "qualification_schema_repair": "FORBIDDEN",
        "p11_provider_execution": "FORBIDDEN",
        "allowed_provider_prompt_ids": [
            "P04_BLUEPRINT_BUILD_V1",
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P09_GUIDE_BUILD_V1",
        ],
        "successful_provider_invocations_per_logical_attempt": 1,
        "off_plan_provider_invocation_disposition": "FAIL_CLOSED",
        "event_loop_lifecycle": "ONE_ASYNCIO_RUN_PER_AUTHORIZED_POPULATION",
        "logical_call_execution": "SEQUENTIAL_FROZEN_ORDER",
        "concurrency": "FORBIDDEN",
        "adapter_reuse_scope": "ONE_LIVE_EVENT_LOOP",
        "async_transport_close": "SAME_OWNING_EVENT_LOOP_WHEN_EXPOSED",
        "technical_retry_owner": "OUTER_EXECUTOR",
        "gateway_max_retries": 0,
        "max_technical_retries_per_logical_call": 1,
        "retry_disposition_source": "SANITIZED_UNDERLYING_PROVIDER_REASON",
        "provider_invocation_evidence": "SAFE_CONTENT_FREE_PER_INVOCATION",
        "n3_semantic_metadata_forbidden_fields": [
            "accepted_semantic_rate",
            "qualification_outcome",
            "result_state",
            "semantic_outcome",
            "semantic_status",
        ],
    }


def test_repairable_p06_output_invokes_no_p11_and_emits_no_n3_packet(
    prepared: px.PreparedExecution,
) -> None:
    call = next(
        call
        for call in prepared.calls
        if call.case.axis == "CONTRACTUAL_HARD_SAFETY"
    )
    inner = FakeProviderAdapter(extra_p06_field=("semantic_outcome", "PASS"))
    adapter, _counters = _capturing_adapter(inner)
    authorization = _authorization()
    attempts, output = asyncio.run(
        px._execute_call(
            call=call,
            adapter=adapter,
            authorization=authorization,
            pricing=_pricing(),
            account=px.CostAccount(authorization),
        )
    )
    assert output is None
    assert inner.prompt_ids == ["P06_EVIDENCE_MAP_V1"]
    assert inner.prompt_ids.count("P11_SCHEMA_REPAIR_V1") == 0
    assert attempts[-1]["status"] == "FAILED"
    assert attempts[-1]["provider_invocation_count"] == 1
    assert attempts[-1]["provider_prompt_ids"] == ["P06_EVIDENCE_MAP_V1"]
    packets = px.build_blind_packet_sets(calls=(call,), outputs={})
    assert packets["semantic"]["packet_count"] == 0
    assert packets["n3"]["packet_count"] == 0
    assert packets["n3"]["packets"] == []


def test_normal_primary_attempt_is_exactly_one_accounted_provider_invocation(
    prepared: px.PreparedExecution,
) -> None:
    call = next(call for call in prepared.calls if call.case.stage == "P06")
    inner = FakeProviderAdapter()
    adapter, _counters = _capturing_adapter(inner)
    authorization = _authorization()
    account = px.CostAccount(authorization)
    attempts, output = asyncio.run(
        px._execute_call(
            call=call,
            adapter=adapter,
            authorization=authorization,
            pricing=_pricing(),
            account=account,
        )
    )
    assert output is not None
    assert len(attempts) == 1
    assert attempts[0]["status"] == "COMPLETED"
    assert attempts[0]["provider_invocation_count"] == 1
    assert attempts[0]["provider_prompt_ids"] == [call.case.candidate.prompt_id]
    assert inner.prompt_ids == [call.case.candidate.prompt_id]
    assert account.spent_usd == adapter.captured[0]["actual_cost_usd"]


def test_off_plan_second_provider_invocation_fails_and_charges_every_capture(
    prepared: px.PreparedExecution,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = next(
        call
        for call in prepared.calls
        if call.case.axis == "CONTRACTUAL_HARD_SAFETY"
    )
    inner = FakeProviderAdapter(extra_p06_field=("semantic_outcome", "PASS"))
    adapter, _counters = _capturing_adapter(inner)
    authorization = _authorization()
    account = px.CostAccount(authorization)
    repaired_results: list[Any] = []

    def unsafe_gateway(
        *,
        candidate: px.AuthorizedCandidate,
        adapter: Any,
        cap: float,
        pricing: Mapping[str, Any],
        job_id: str,
    ) -> Any:
        routes = build_openai_routes(
            max_call_cost_usd=cap,
            route_profile_id=candidate.route_profile_id,
        )

        def estimator(spec: Any, input_tokens: int) -> float:
            return px._estimate_cost(
                pricing,
                model=candidate.model,
                input_tokens=input_tokens,
                output_tokens=spec.max_output_tokens,
            )

        gateway = ModelGateway(
            GatewayConfig(
                mode=GatewayMode.REAL,
                timeout_seconds=10,
                max_retries=0,
                default_budget_usd=cap,
                job_id=job_id,
            ),
            real_routes=routes,
            adapters={"openai": adapter},
            cost_estimator=estimator,
            input_token_estimator=px.estimate_openai_input_tokens,
        )

        class RecordingGateway:
            async def invoke(self, *args: Any, **kwargs: Any) -> Any:
                result = await gateway.invoke(*args, **kwargs)
                repaired_results.append(result)
                return result

        return RecordingGateway()

    monkeypatch.setattr(px, "_gateway_for", unsafe_gateway)
    attempts, output = asyncio.run(
        px._execute_call(
            call=call,
            adapter=adapter,
            authorization=authorization,
            pricing=_pricing(),
            account=account,
        )
    )
    assert repaired_results and repaired_results[0].repaired is True
    assert output is None
    assert inner.prompt_ids == ["P06_EVIDENCE_MAP_V1", "P11_SCHEMA_REPAIR_V1"]
    assert attempts[-1]["failure_code"] == "OFF_PLAN_PROVIDER_CALL"
    assert attempts[-1]["provider_invocation_count"] == 2
    assert attempts[-1]["provider_prompt_ids"] == inner.prompt_ids
    assert account.spent_usd == sum(
        row["actual_cost_usd"] for row in adapter.captured
    )
    assert attempts[-1]["actual_cost_usd"] == account.spent_usd


def _n3_packet_for(
    call: px.LogicalCall, model_owned_output: Mapping[str, Any]
) -> dict[str, Any]:
    authority = call.case.n3_packet_authority
    assert authority is not None and call.case.exposure_pseudonym is not None
    return px.build_n3_packet(
        exposure_pseudonym=call.case.exposure_pseudonym,
        run_index=call.run_index,
        route_context=authority["route_context"],
        model_visible_evidence=authority["model_visible_evidence"],
        model_owned_output=model_owned_output,
        p06_stage_boundary_hash=authority["p06_stage_boundary_hash"],
        p06_field_authority_hash=authority["p06_field_authority_hash"],
        exposure_selector=authority["exposure_selector"],
        n3_gate_source_hash=authority["n3_gate_source_hash"],
    )


@pytest.mark.parametrize("forbidden_field", ["semantic_outcome", "result_state"])
def test_n3_packet_rejects_semantic_qualification_metadata_recursively(
    prepared: px.PreparedExecution,
    complete_generation: Mapping[str, Any],
    forbidden_field: str,
) -> None:
    call = next(
        call
        for call in prepared.calls
        if call.case.axis == "CONTRACTUAL_HARD_SAFETY"
    )
    raw = deepcopy(
        complete_generation["outputs"][call.logical_call_id].provider_output
    )
    raw["nested_qualification_metadata"] = {forbidden_field: "PASS"}
    with pytest.raises(N3ProtocolError, match="forbidden N3 packet field"):
        _n3_packet_for(call, raw)


def test_valid_raw_provider_draft_still_builds_a_valid_n3_packet(
    prepared: px.PreparedExecution,
    complete_generation: Mapping[str, Any],
) -> None:
    call = next(
        call
        for call in prepared.calls
        if call.case.axis == "CONTRACTUAL_HARD_SAFETY"
    )
    raw = complete_generation["outputs"][call.logical_call_id].provider_output
    packet = _n3_packet_for(call, raw)
    px.assert_n3_packet_blind(packet)
    assert packet["model_owned_output"] == raw


def test_all_thirty_fail_is_incomplete_zero_packets_and_nonzero_cli(
    prepared: px.PreparedExecution,
    tmp_path: Path,
) -> None:
    generation = _execute_population(
        prepared, FakeProviderAdapter(fail_all=True)
    )
    completion = generation["completion"]
    assert len(generation["attempts"]) == 30
    assert len(generation["outputs"]) == 0
    assert generation["packets"]["semantic"]["packet_count"] == 0
    assert generation["packets"]["n3"]["packet_count"] == 0
    assert completion["complete"] is False
    assert "SUCCESSFULLY_COMPLETED_LOGICAL_CALL_COUNT" in completion["violations"]
    generation["counters"].high_smoke = "ATTEMPTED_INCOMPLETE"
    result = px._write_incomplete_execution_evidence(
        prepared=prepared,
        authorization=generation["authorization"],
        pricing=generation["pricing"],
        attempts=generation["attempts"],
        completion=completion,
        account=generation["account"],
        counters=generation["counters"],
        evidence_root=tmp_path / "evidence",
    )
    assert result["status"] == "PHASE9_SMOKE_GENERATION_INCOMPLETE"
    assert result["adjudication_packets_emitted"] == 0
    assert smoke_cli._result_exit_code(result) != 0


def test_one_of_thirty_failed_blocks_completion(
    prepared: px.PreparedExecution,
) -> None:
    generation = _execute_population(
        prepared, FakeProviderAdapter(fail_invocations=frozenset({1}))
    )
    assert len(generation["outputs"]) == 29
    assert generation["completion"]["complete"] is False
    assert len(generation["completion"]["missing_planned_logical_call_ids"]) == 1


def test_semantic_packet_population_must_be_exactly_fifty_four(
    prepared: px.PreparedExecution,
    complete_generation: Mapping[str, Any],
) -> None:
    packets = deepcopy(complete_generation["packets"])
    packets["semantic"]["packets"].pop()
    packets["semantic"]["packet_count"] = 53
    completion = px.generation_completion_summary(
        calls=prepared.calls,
        outputs=complete_generation["outputs"],
        attempts=complete_generation["attempts"],
        packets=packets,
    )
    assert completion["complete"] is False
    assert "SEMANTIC_PACKET_POPULATION" in completion["violations"]


def test_n3_packet_population_must_be_exactly_three(
    prepared: px.PreparedExecution,
    complete_generation: Mapping[str, Any],
) -> None:
    packets = deepcopy(complete_generation["packets"])
    packets["n3"]["packets"].pop()
    packets["n3"]["packet_count"] = 2
    completion = px.generation_completion_summary(
        calls=prepared.calls,
        outputs=complete_generation["outputs"],
        attempts=complete_generation["attempts"],
        packets=packets,
    )
    assert completion["complete"] is False
    assert "N3_PACKET_POPULATION" in completion["violations"]


def test_exact_complete_population_reaches_only_the_pending_adjudication_state(
    prepared: px.PreparedExecution,
    complete_generation: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    completion = complete_generation["completion"]
    assert completion == {
        "complete": True,
        "violations": [],
        "planned_logical_calls": 30,
        "unique_planned_logical_call_identities": 30,
        "successfully_completed_logical_calls": 30,
        "unique_completed_logical_call_identities": 30,
        "completed_attempts": 30,
        "missing_planned_logical_call_ids": [],
        "extra_completed_logical_call_ids": [],
        "extra_attempt_logical_call_ids": [],
        "identity_mismatch_logical_call_ids": [],
        "off_plan_prompt_logical_call_ids": [],
        "semantic_packet_count": 54,
        "n3_packet_count": 3,
        "p06_semantic_observation_count": 6,
    }
    complete_generation["counters"].high_smoke = "EXECUTED_COMPLETE"
    result = px._write_execution_evidence(
        prepared=prepared,
        authorization=complete_generation["authorization"],
        pricing=complete_generation["pricing"],
        attempts=complete_generation["attempts"],
        packets=complete_generation["packets"],
        completion=completion,
        account=complete_generation["account"],
        counters=complete_generation["counters"],
        evidence_root=tmp_path / "evidence",
        adjudication_root=tmp_path / "adjudication",
    )
    assert result["status"] == (
        "REAL_SMOKE_HIGH_GENERATION_COMPLETE_PENDING_ADJUDICATION"
    )
    assert smoke_cli._result_exit_code(result) == 0
    assert len(list((tmp_path / "adjudication").rglob("sem-*.json"))) == 54
    assert len(list((tmp_path / "adjudication").rglob("n3-*.json"))) == 3


def test_v203_ordered_logical_population_is_byte_equal_to_v202(
    prepared: px.PreparedExecution,
) -> None:
    predecessor = px._read_json(px.PREDECESSOR_REQUEST_AUTHORITY_PATH)
    old_identities = px.ordered_logical_call_identities_from_request_authority(
        predecessor
    )
    new_identities = [call.identity() for call in prepared.calls]
    assert old_identities == new_identities
    assert px.canonical_hash(old_identities) == (
        px.EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH
    ) == prepared.boundary["high_smoke_plan"][
        "ordered_logical_call_population_hash"
    ]
    assert prepared.boundary["high_smoke_plan"]["decomposition"] == {
        "SEMANTIC/P04/SMOKE/HIGH": 3,
        "SEMANTIC/P06/SMOKE/HIGH": 3,
        "CONTRACTUAL_HARD_SAFETY/P06/N3_SAFETY_SMOKE/HIGH": 3,
        "SEMANTIC/P07/SMOKE/HIGH": 18,
        "SEMANTIC/P09/SMOKE/HIGH": 3,
    }


def test_frozen_semantic_and_published_v200_v201_bytes_are_unchanged(
    prepared: px.PreparedExecution,
) -> None:
    for relative, expected in px.PROTECTED_PRIOR_EXECUTION_ARTIFACT_HASHES.items():
        assert px._file_hash(px.REPOSITORY_ROOT / relative) == expected
    for relative, binding in prepared.boundary["frozen_artifacts"].items():
        assert px._file_hash(px.REPOSITORY_ROOT / relative) == binding["file_sha256"]
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


def test_current_stop_remains_precredential_without_authorization(
    prepared: px.PreparedExecution,
    tmp_path: Path,
) -> None:
    del prepared
    assert px.CURRENT_PRICING_PATH.is_file()
    assert px.COST_PROJECTION_PATH.is_file()
    assert not px.BILLABLE_AUTHORIZATION_PATH.exists()
    assert px.PREDECESSOR_AUTHORIZATION_PATH.is_file()
    credential_calls = 0
    factory_calls = 0

    def credential_resolver() -> None:
        nonlocal credential_calls
        credential_calls += 1
        return None

    def adapter_factory(_key: Any) -> object:
        nonlocal factory_calls
        factory_calls += 1
        return object()

    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.run_phase9b_smoke(
            created_by="test",
            authorization_path=tmp_path / "explicitly-missing-authorization.json",
            allow_billable=True,
            credential_resolver=credential_resolver,
            adapter_factory=adapter_factory,
        )
    assert exc.value.code == "EXPLICIT_HASH_BOUND_AUTHORIZATION_REQUIRED"
    assert credential_calls == factory_calls == 0
    assert exc.value.safety_counters == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "transport_factory_calls": 0,
        "real_provider_transport": False,
        "pricing_refresh": "VERIFIED_CURRENT_OFFICIAL_PRICING",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }


def test_published_v203_report_has_construction_only_safety_counters() -> None:
    report = px._read_json(
        px.EXECUTION_REPORT_ROOT / "execution_cutover_report.json"
    )
    assert report["readiness"] == "NOT_EXECUTED_NO_BILLABLE_AUTHORIZATION"
    assert report["execution_counters"] == {
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "transport_factory_calls": 0,
        "real_provider_transport": False,
        "pricing_refresh": "VERIFIED_CURRENT_OFFICIAL_PRICING",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }
