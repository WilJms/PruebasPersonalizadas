"""Phase 9B execution tests. None of these may reach a real provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    DeterministicMockFactory,
    MockBehavior,
)
from comprehension_verification.model_gateway.openai_pricing import estimate_cost_usd
from comprehension_verification import phase9_execution as px


class _OfflineAdapter:
    """Deterministic stand-in shaped exactly like the real provider adapter."""

    def __init__(self, *, behavior: MockBehavior = MockBehavior.HAPPY) -> None:
        self.behavior = behavior
        self.config = None
        self.seen: list[str] = []

    async def invoke(self, **kwargs: Any) -> AdapterResult:
        prompt_id = kwargs["prompt_id"]
        request = kwargs["request"]
        route = kwargs["route"]
        self.seen.append(prompt_id)
        draft = DeterministicMockFactory().output_for(
            prompt_id, request, self.behavior
        )
        raw = draft.model_dump(mode="json")
        input_tokens, output_tokens = 1_000, 500
        return AdapterResult(
            raw_output=raw,
            input_tokens=input_tokens,
            cached_input_tokens=0,
            output_tokens=output_tokens,
            estimated_cost_usd=estimate_cost_usd(
                model=route.model,
                input_tokens=input_tokens,
                output_tokens=route.max_output_tokens,
            ),
            actual_cost_usd=estimate_cost_usd(
                model=route.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            reasoning_tokens=120,
            effective_model=route.model,
            output_hash="sha256:" + "0" * 64,
            provider_request_id_hash="sha256:" + "1" * 64,
            provider_schema_valid=True,
            reason_codes=("OFFLINE_TEST_ADAPTER", "REASONING_TOKENS_120"),
        )


@pytest.fixture(scope="module")
def smoke_cases() -> list[px.SmokeCase]:
    return px.build_smoke_cases()


@pytest.fixture(scope="module")
def logical_calls(smoke_cases: list[px.SmokeCase]) -> list[px.LogicalCall]:
    return px.build_logical_calls(smoke_cases)


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("phase9b")
    return px.run_phase9b_smoke(
        api_key=SecretStr("offline-test-key-not-a-credential"),
        created_by="offline-test",
        evidence_root=root / "executions",
        adjudication_root=root / "bundle",
        transport=True,
        adapter_factory=lambda _key: _OfflineAdapter(),
    )


def test_frozen_boundaries_match_the_phase9_freeze() -> None:
    observed = px.revalidate_frozen_boundaries()
    assert observed["benchmark_boundary_hash"] == px.EXPECTED_BENCHMARK_BOUNDARY_HASH
    assert observed["protocol_boundary_hash"] == px.EXPECTED_PROTOCOL_BOUNDARY_HASH
    assert observed["candidate_matrix_hash"] == px.EXPECTED_CANDIDATE_MATRIX_HASH
    assert (
        observed["corpus_package_boundary_hash"] == px.EXPECTED_CORPUS_BOUNDARY_HASH
    )


def test_executable_pricing_equals_the_frozen_snapshot() -> None:
    pricing = px.verify_pricing_snapshot()
    assert pricing["models"]["gpt-5.6-luna"] == {
        "input_per_million": 0.20,
        "cached_input_per_million": 0.02,
        "output_per_million": 1.20,
    }
    assert pricing["models"]["gpt-5.6-terra"] == {
        "input_per_million": 2.00,
        "cached_input_per_million": 0.20,
        "output_per_million": 12.00,
    }


def test_every_smoke_request_reproduces_its_frozen_input_hash(
    smoke_cases: list[px.SmokeCase],
) -> None:
    assert len(smoke_cases) == 10
    for case in smoke_cases:
        assert case.rebuilt_input_hash == case.frozen_input_hash


def test_the_plan_is_exactly_thirty_authorized_primary_calls(
    logical_calls: list[px.LogicalCall],
) -> None:
    assert len(logical_calls) == px.AUTHORIZED_PRIMARY_LOGICAL_CALLS == 30
    per_stage = {"P04": 0, "P06": 0, "P07": 0, "P09": 0}
    for call in logical_calls:
        per_stage[call.case.stage] += 1
    assert per_stage == {"P04": 3, "P06": 6, "P07": 18, "P09": 3}


def test_dry_proof_makes_every_forbidden_surface_unreachable(
    logical_calls: list[px.LogicalCall],
) -> None:
    proof = px.dry_authorization_proof(logical_calls)
    assert proof["result"] == "PASS"
    assert proof["findings"] == []
    assert proof["reachable_reasoning_efforts"] == ["HIGH"]
    assert proof["reachable_splits"] == ["SMOKE"]
    assert "gpt-5.6-sol" not in proof["reachable_models"]
    assert all(proof["unreachable"].values())
    assert proof["projected_worst_case_total_usd"] <= px.OUTER_AUTHORIZATION_CAP_USD


def test_forbidden_candidates_are_absent_from_the_authorized_set() -> None:
    authorized = {item.candidate_id for item in px.AUTHORIZED_CANDIDATES}
    assert authorized.isdisjoint(px.FORBIDDEN_CANDIDATE_IDS)
    assert len(authorized) == 4


def test_authorization_binds_every_frozen_boundary_and_starts_unconsumed(
    logical_calls: list[px.LogicalCall],
) -> None:
    authorization = px.build_authorization(
        boundaries=px.revalidate_frozen_boundaries(),
        pricing=px.verify_pricing_snapshot(),
        calls=logical_calls,
        proof=px.dry_authorization_proof(logical_calls),
        created_by="test",
    )
    assert authorization["benchmark_boundary_hash"] == (
        px.EXPECTED_BENCHMARK_BOUNDARY_HASH
    )
    assert authorization["protocol_boundary_hash"] == (
        px.EXPECTED_PROTOCOL_BOUNDARY_HASH
    )
    assert authorization["candidate_matrix_hash"] == (
        px.EXPECTED_CANDIDATE_MATRIX_HASH
    )
    assert authorization["split"] == "SMOKE"
    assert authorization["k"] == 3
    assert authorization["primary_logical_calls"] == 30
    assert authorization["outer_budget_cap_usd"] == 2.00
    assert authorization["consumption"]["state"] == "CREATED_NOT_CONSUMED"
    assert authorization["consumption"]["consumed_once"] is False
    for excluded in ("CORE", "HELD_OUT_CONFIRMATION", "XHIGH", "MAX", "gpt-5.6-sol"):
        assert excluded in authorization["excluded_scope"]


def test_cost_account_fails_closed_on_each_cap() -> None:
    candidate = px.CANDIDATE_BY_STAGE["P07"]
    account = px.CostAccount()
    with pytest.raises(px.Phase9ExecutionError) as per_call:
        account.admit(candidate, candidate.per_call_cap_usd + 0.01)
    assert per_call.value.code == "PHASE9_PER_CALL_CAP_WOULD_BE_EXCEEDED"

    account.by_candidate[candidate.candidate_id] = candidate.smoke_rung_cap_usd
    with pytest.raises(px.Phase9ExecutionError) as rung:
        account.admit(candidate, 0.001)
    assert rung.value.code == "PHASE9_RUNG_CAP_WOULD_BE_EXCEEDED"

    outer = px.CostAccount(spent_usd=px.OUTER_AUTHORIZATION_CAP_USD)
    with pytest.raises(px.Phase9ExecutionError) as breach:
        outer.admit(candidate, 0.001)
    assert breach.value.code == "PHASE9_OUTER_CAP_WOULD_BE_EXCEEDED"


def test_dry_mode_performs_no_provider_call_and_consumes_nothing() -> None:
    result = px.run_phase9b_smoke(
        api_key=None, created_by="test", transport=False
    )
    assert result["status"] == "DRY_RUN"
    assert result["provider_calls"] == 0
    assert result["billable_authorizations_consumed"] == 0


def test_real_mode_without_a_credential_stops_before_transport() -> None:
    with pytest.raises(px.Phase9ExecutionError) as exc:
        px.run_phase9b_smoke(api_key=None, created_by="test", transport=True)
    assert exc.value.code == "OPENAI_CREDENTIAL_REQUIRED"


def test_offline_execution_attempts_exactly_thirty_calls(
    offline_run: dict[str, Any],
) -> None:
    """The offline adapter reuses the repository's generic deterministic mock.

    That mock cannot author a valid P07 draft for every benchmark opportunity,
    so some runs are rejected by the P07 materializer. That is the deterministic
    boundary doing its job, and the assertion here is about the harness: exactly
    thirty authorized logical calls are attempted and every one is accounted
    for, whatever the product boundary then decides.
    """

    accounting = offline_run["accounting"]
    assert accounting["primary_logical_calls_attempted"] == 30
    assert (
        accounting["primary_logical_calls_completed"]
        + accounting["attempts_not_completed"]
        == 30
    )
    assert accounting["authorization_consumed_exactly_once"] is True
    assert accounting["core_calls"] == 0
    assert accounting["held_out_calls"] == 0
    assert accounting["xhigh_calls"] == 0
    assert accounting["max_calls"] == 0
    assert accounting["sol_calls"] == 0
    assert accounting["p10_p11_calls"] == 0
    assert accounting["semantic_retries"] == 0
    assert offline_run["cost"]["within_outer_cap"] is True


def test_offline_execution_records_full_usage_evidence(
    offline_run: dict[str, Any],
) -> None:
    for attempt in offline_run["attempts"]:
        for field in (
            "logical_call_id",
            "attempt_index",
            "case_id",
            "stage",
            "candidate_id",
            "model",
            "reasoning_effort",
            "route_profile_id",
            "request_hash",
            "model_visible_input_hash",
            "provider_response_id_hash",
            "response_status",
            "provider_output_hash",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "actual_cost_usd",
            "latency_ms",
            "timestamp",
            "authorization_id",
            "benchmark_boundary_hash",
            "protocol_boundary_hash",
            "candidate_matrix_hash",
        ):
            assert field in attempt
        assert attempt["semantic_status"] == "PENDING_ADJUDICATION"


def test_offline_execution_leaves_every_property_pending(
    offline_run: dict[str, Any],
) -> None:
    assert offline_run["semantic_status"] == "PENDING_ADJUDICATION"
    for row in offline_run["deterministic_validation"]:
        assert row["result"] in {
            "PASS",
            "DETERMINISTIC_VALIDATION_FAILURE",
            "CONTRACT_OR_SCHEMA_FAILURE",
        }
        assert "MODEL_FAILURE" not in json.dumps(row)


def test_blind_packets_carry_only_protocol_allowed_fields(
    offline_run: dict[str, Any],
) -> None:
    bundle_root = Path(offline_run["blind_bundle"]["root"])
    manifest = json.loads((bundle_root / "bundle_manifest.json").read_text("utf-8"))
    allowed = set(
        json.loads(
            (
                px.PHASE9_DEFINITION_ROOT / "adjudication_protocol.json"
            ).read_text("utf-8")
        )["blinding"]["allowed_packet_fields"]
    )
    assert manifest["packet_count"] > 0
    for row in manifest["packets"]:
        packet = json.loads((bundle_root / row["file"]).read_text("utf-8"))
        assert set(packet) <= allowed
        for forbidden in px.FORBIDDEN_PACKET_FIELDS:
            assert forbidden not in packet


def test_blind_bundle_manifest_carries_no_run_metadata(
    offline_run: dict[str, Any],
) -> None:
    manifest = offline_run["blind_bundle"]
    assert manifest["contains_candidate_metadata"] is False
    assert manifest["contains_split_or_rung_metadata"] is False
    assert manifest["contains_cost_or_latency_metadata"] is False
    text = json.dumps(manifest["packets"])
    for token in ("luna", "terra", "SMOKE", "HIGH", "candidate_id", "USD"):
        assert token not in text
    # Manifest order is by pseudonymous id, never by case or promotion order.
    ids = [row["packet_id"] for row in manifest["packets"]]
    assert ids == sorted(ids)


def test_leakage_scan_blocks_an_injected_metadata_leak() -> None:
    clean = {
        "schema_version": "semantic-review-packet/1.1.0",
        "case_id": "PP-A01-P04-001",
        "stage": "P04",
        "fixture_id": "benchmark-fixture://p04/act_01",
        "route_or_opportunity_id": None,
        "binding_scope": "CASE",
        "candidate_output": {"text": "una respuesta"},
        "candidate_output_hash": "sha256:" + "0" * 64,
        "relevant_source_refs": [],
        "property": {"text": "propiedad"},
        "defensible_alternatives": [],
        "oracle_state": "VALID",
        "source_hashes": {},
    }
    assert px.scan_packet_for_leakage(clean)["result"] == "PASS"

    leaked = {**clean, "candidate_id": "P04-C1-TERRA-HIGH"}
    scan = px.scan_packet_for_leakage(leaked)
    assert scan["result"] == "BLOCKED"
    assert any(item["kind"] == "FORBIDDEN_FIELD_NAME" for item in scan["leaks"])


def test_offline_bundle_passes_the_leakage_audit(
    offline_run: dict[str, Any],
) -> None:
    assert offline_run["leakage_blocked"] == []
    assert offline_run["blind_bundle"]["leakage_scan"]["leaks"] == 0
    assert offline_run["blind_bundle"]["leakage_scan"]["result"] == "PASS"


def test_execution_evidence_is_written_and_immutable(
    offline_run: dict[str, Any],
) -> None:
    hashes = offline_run["evidence_hashes"]
    for name in (
        "authorization.json",
        "dry_authorization_proof.json",
        "call_ledger.json",
        "usage_and_cost.json",
        "deterministic_validation/report.json",
        "blind_bundle_manifest.json",
        "execution_manifest.json",
    ):
        assert hashes[name].startswith("sha256:")
    assert offline_run["execution_id"].startswith("exec-phase9b1-")


def test_retry_policy_is_one_attempt_on_allowlisted_codes_only() -> None:
    assert px.MAX_TECHNICAL_RETRIES_PER_LOGICAL_CALL == 1
    assert px.RETRYABLE_TECHNICAL_CODES == {
        "PROVIDER_TIMEOUT",
        "PROVIDER_CONNECTION",
        "PROVIDER_TRANSIENT_STATUS",
        "PROVIDER_RATE_LIMIT",
    }


def test_offline_failures_are_classified_and_never_semantic(
    offline_run: dict[str, Any],
) -> None:
    kinds = {
        item["technical_diagnostic"]["failure_kind"]
        for item in offline_run["attempts"]
        if item["technical_diagnostic"] is not None
    }
    assert kinds <= {
        "PROVIDER_TECHNICAL_FAILURE",
        "CONTRACT_OR_SCHEMA_FAILURE",
        "DETERMINISTIC_VALIDATION_FAILURE",
        "UNCLASSIFIED_TECHNICAL_FAILURE",
    }
    text = json.dumps(offline_run["attempts"])
    for verdict in ("MODEL_FAILURE", "DEFENSIBLE_ALTERNATIVE", "ORACLE_SUSPECT"):
        assert verdict not in text


def test_no_retry_is_issued_for_a_deterministic_rejection(
    offline_run: dict[str, Any],
) -> None:
    for item in offline_run["attempts"]:
        diagnostic = item["technical_diagnostic"]
        if diagnostic and diagnostic["failure_kind"] == (
            "DETERMINISTIC_VALIDATION_FAILURE"
        ):
            assert item["attempt_index"] == 1
    assert all(not item["is_new_semantic_sample"] for item in offline_run["attempts"])


def test_accounting_separates_technical_from_deterministic_failures(
    offline_run: dict[str, Any],
) -> None:
    """The 2% technical gate must never absorb a deterministic rejection."""

    accounting = offline_run["accounting"]
    assert accounting["provider_technical_failures"] == 0
    assert accounting["deterministic_validation_failures"] == 6
    assert accounting["technical_failure_rate"] == 0.0
    assert (
        accounting["provider_technical_failures"]
        + accounting["deterministic_validation_failures"]
        + accounting["contract_or_schema_failures"]
        == accounting["attempts_not_completed"]
    )


def test_recomputed_accounting_matches_the_persisted_ledger(
    offline_run: dict[str, Any],
) -> None:
    """A derived summary is recomputed from the ledger, never edited in place."""

    execution_dir = Path(offline_run["execution_dir"])
    ledger = json.loads((execution_dir / "call_ledger.json").read_text("utf-8"))
    recomputed = px.recompute_accounting_from_ledger(ledger)
    accounting = offline_run["accounting"]
    for key in (
        "primary_logical_calls_attempted",
        "primary_logical_calls_completed",
        "attempts_not_completed",
        "provider_technical_failures",
        "deterministic_validation_failures",
        "contract_or_schema_failures",
        "technical_failure_rate",
    ):
        assert recomputed[key] == accounting[key]
    assert recomputed["semantic_status"] == "PENDING_ADJUDICATION"


def test_recorded_execution_evidence_is_internally_consistent() -> None:
    """The committed real execution must stay replay-safe and coherent."""

    root = (
        px.BENCHMARK_REPORT_ROOT
        / "phase9/executions/exec-phase9b1-bfd3cf082617ea8b"
    )
    if not root.exists():  # pragma: no cover - evidence not present in a fork
        pytest.skip("no recorded Phase 9B.1 execution in this checkout")
    ledger = json.loads((root / "call_ledger.json").read_text("utf-8"))
    manifest = json.loads((root / "execution_manifest.json").read_text("utf-8"))
    amendment = json.loads((root / "accounting_amendment.json").read_text("utf-8"))
    authorization = json.loads((root / "authorization.json").read_text("utf-8"))

    assert authorization["consumption"]["consumed_once"] is True
    assert authorization["outer_budget_cap_usd"] == 2.00
    assert manifest["semantic_status"] == "PENDING_ADJUDICATION"
    assert manifest["semantic_adjudication_performed_here"] is False
    assert manifest["escalation_performed"] is False

    recomputed = px.recompute_accounting_from_ledger(ledger)
    assert recomputed == amendment["recomputed_accounting"]
    assert recomputed["primary_logical_calls_attempted"] == 30
    assert recomputed["provider_technical_failures"] == 0
    assert recomputed["technical_failure_rate"] <= 0.02

    for attempt in ledger["attempts"]:
        assert attempt["reasoning_effort"] == "HIGH"
        assert attempt["model"] in {"gpt-5.6-luna", "gpt-5.6-terra"}
        assert attempt["candidate_id"] not in px.FORBIDDEN_CANDIDATE_IDS
        assert attempt["semantic_status"] == "PENDING_ADJUDICATION"

    cost = json.loads((root / "usage_and_cost.json").read_text("utf-8"))
    assert cost["cost"]["actual_total_usd"] <= px.OUTER_AUTHORIZATION_CAP_USD
    assert cost["cost"]["within_outer_cap"] is True


def test_recorded_blind_bundle_has_no_leaks() -> None:
    root = (
        px.BENCHMARK_REPORT_ROOT
        / "phase9/adjudication_bundles/exec-phase9b1-bfd3cf082617ea8b"
    )
    if not root.exists():  # pragma: no cover - evidence not present in a fork
        pytest.skip("no recorded Phase 9B.1 bundle in this checkout")
    manifest = json.loads((root / "bundle_manifest.json").read_text("utf-8"))
    assert manifest["leakage_scan"]["leaks"] == 0
    assert manifest["packet_count"] == len(manifest["packets"])
    for row in manifest["packets"]:
        packet = json.loads((root / row["file"]).read_text("utf-8"))
        assert px.scan_packet_for_leakage(packet)["result"] == "PASS"
        assert px._hash(packet) == row["packet_hash"]
