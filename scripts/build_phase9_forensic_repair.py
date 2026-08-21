#!/usr/bin/env python3
"""Build/check offline proof for the phase9-execution/2.0.3 repair.

This script never resolves credentials and never constructs a real provider
transport.  It reproduces the old event-loop lifecycle with an in-process fake,
proves the successor lifecycle, and classifies immutable v2.0.2 evidence using
only fields that were durably persisted by that execution.
"""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification import phase9_execution as px  # noqa: E402
from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification.model_gateway.gateway import (  # noqa: E402
    PermanentProviderError,
)
from comprehension_verification.model_gateway.mock_factory import (  # noqa: E402
    AdapterResult,
    DeterministicMockFactory,
    MockBehavior,
)


REPORT_ROOT = REPOSITORY_ROOT / "reports/phase9_execution/v2_0_3"
ASYNC_REPRODUCTION_PATH = REPORT_ROOT / "async_lifecycle_reproduction.json"
FORENSIC_CLASSIFICATION_PATH = (
    REPORT_ROOT / "v2_0_2_forensic_classification.json"
)
FORENSIC_REPAIR_REPORT_PATH = (
    REPORT_ROOT / "post_execution_forensic_repair_report.json"
)


def _read(artifact: Path) -> dict[str, Any]:
    return json.loads(artifact.read_text(encoding="utf-8"))


def _serialize(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write(artifact: Path, payload: Any) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(_serialize(payload), encoding="utf-8")


def _file_hash(artifact: Path) -> str:
    return f"sha256:{sha256(artifact.read_bytes()).hexdigest()}"


def _pricing() -> dict[str, Any]:
    return {
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
        },
    }


def _synthetic_authorization() -> dict[str, Any]:
    candidate_ids = [item.candidate_id for item in px.AUTHORIZED_CANDIDATES]
    return {
        "authorization_id": "OFFLINE_NON_BILLABLE_LIFECYCLE_REPRODUCTION",
        "authorization_hash": "sha256:" + "0" * 64,
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


class EventLoopBoundFakeAdapter:
    """Fake reusable async transport that is permanently bound on first use."""

    def __init__(self) -> None:
        self.bound_loop: asyncio.AbstractEventLoop | None = None
        self.seen_loops: list[asyncio.AbstractEventLoop] = []
        self.invocations = 0
        self.cross_loop_failures = 0
        self.closed = False
        self.close_same_loop: bool | None = None

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
        loop = asyncio.get_running_loop()
        if all(loop is not observed for observed in self.seen_loops):
            self.seen_loops.append(loop)
        if self.bound_loop is None:
            self.bound_loop = loop
        elif loop is not self.bound_loop:
            self.cross_loop_failures += 1
            raise PermanentProviderError("PROVIDER_CLIENT_EVENT_LOOP_MISMATCH")
        self.invocations += 1
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
        return AdapterResult(
            raw_output=raw,
            input_tokens=100,
            cached_input_tokens=10,
            cache_write_input_tokens=20,
            output_tokens=100,
            reasoning_tokens=7,
            effective_model=route.model,
            output_hash=canonical_hash(raw),
            provider_request_id_hash=canonical_hash(
                {"prompt_id": prompt_id, "invocation": self.invocations}
            ),
            provider_schema_valid=True,
        )

    async def aclose(self) -> None:
        loop = asyncio.get_running_loop()
        self.close_same_loop = loop is self.bound_loop
        if not self.close_same_loop:
            raise RuntimeError("fake async transport closed from a foreign loop")
        self.closed = True


def _wrapped_adapter(
    inner: EventLoopBoundFakeAdapter,
) -> px.PricingBoundCapturingAdapter:
    return px.PricingBoundCapturingAdapter(
        inner,
        pricing=_pricing(),
        counters=px.SafetyCounters(),
        max_requests=60,
    )


def _old_per_call_loop_reproduction(
    prepared: px.PreparedExecution,
) -> dict[str, Any]:
    inner = EventLoopBoundFakeAdapter()
    adapter = _wrapped_adapter(inner)
    authorization = _synthetic_authorization()
    account = px.CostAccount(authorization)
    attempts: list[dict[str, Any]] = []
    outputs: dict[str, px.CompletedCall] = {}
    observed_order: list[str] = []
    for call in prepared.calls:
        observed_order.append(call.logical_call_id)
        call_attempts, output = asyncio.run(
            px._execute_call(
                call=call,
                adapter=adapter,
                authorization=authorization,
                pricing=_pricing(),
                account=account,
            )
        )
        attempts.extend(call_attempts)
        if output is not None:
            outputs[call.logical_call_id] = output
    mismatch_attempts = [
        row
        for row in attempts
        if row.get("provider_reason_code")
        == "PROVIDER_CLIENT_EVENT_LOOP_MISMATCH"
    ]
    return {
        "orchestration_shape": (
            "ONE_PERSISTENT_ADAPTER_PLUS_ASYNCIO_RUN_PER_LOGICAL_CALL"
        ),
        "planned_logical_calls": len(prepared.calls),
        "attempt_rows": len(attempts),
        "completed_logical_calls": len(outputs),
        "failed_logical_calls": len(prepared.calls) - len(outputs),
        "provider_invocations": adapter.calls,
        "event_loops_seen": len(inner.seen_loops),
        "cross_loop_lifecycle_failures": len(mismatch_attempts),
        "first_call_established_reusable_async_state": inner.bound_loop is not None,
        "bound_loop_closed_after_first_asyncio_run": bool(
            inner.bound_loop and inner.bound_loop.is_closed()
        ),
        "frozen_order_preserved": observed_order
        == [call.logical_call_id for call in prepared.calls],
        "adapter_closed": inner.closed,
        "result": "CROSS_EVENT_LOOP_FAILURE_REPRODUCED",
    }


def _new_single_loop_reproduction(
    prepared: px.PreparedExecution,
) -> dict[str, Any]:
    inner = EventLoopBoundFakeAdapter()
    adapter = _wrapped_adapter(inner)
    authorization = _synthetic_authorization()
    attempts, outputs = asyncio.run(
        px._execute_population_with_lifecycle(
            calls=prepared.calls,
            adapter=adapter,
            authorization=authorization,
            pricing=_pricing(),
            account=px.CostAccount(authorization),
        )
    )
    return {
        "orchestration_shape": (
            "ONE_ASYNCIO_RUN_FOR_SEQUENTIAL_AUTHORIZED_POPULATION"
        ),
        "planned_logical_calls": len(prepared.calls),
        "attempt_rows": len(attempts),
        "completed_logical_calls": len(outputs),
        "failed_logical_calls": len(prepared.calls) - len(outputs),
        "provider_invocations": adapter.calls,
        "event_loops_seen": len(inner.seen_loops),
        "cross_loop_lifecycle_failures": inner.cross_loop_failures,
        "frozen_order_preserved": [
            row["logical_call_id"] for row in attempts if row["status"] == "COMPLETED"
        ]
        == [call.logical_call_id for call in prepared.calls],
        "adapter_closed": inner.closed and adapter.closed,
        "adapter_close_same_live_loop": inner.close_same_loop is True,
        "result": "THIRTY_CALL_SINGLE_LOOP_REGRESSION_PASSED",
    }


def build_async_reproduction() -> dict[str, Any]:
    prepared = px.prepare_phase9_execution()
    old = _old_per_call_loop_reproduction(prepared)
    new = _new_single_loop_reproduction(prepared)
    if not (
        old["cross_loop_lifecycle_failures"] > 0
        and old["completed_logical_calls"] < 30
        and new["completed_logical_calls"] == 30
        and new["provider_invocations"] == 30
        and new["event_loops_seen"] == 1
        and new["adapter_close_same_live_loop"] is True
    ):
        raise RuntimeError("offline async lifecycle reproduction did not prove the repair")
    material = {
        "schema_version": "phase9-async-lifecycle-reproduction/1.0.0",
        "execution_version": px.PHASE9_EXECUTION_VERSION,
        "mode": "OFFLINE_IN_PROCESS_NO_NETWORK",
        "fake_transport_property": (
            "REUSABLE_ASYNC_STATE_BINDS_TO_FIRST_LIVE_EVENT_LOOP"
        ),
        "old_per_call_asyncio_run": old,
        "new_single_population_asyncio_run": new,
        "conclusion": (
            "OLD_SHAPE_REPRODUCES_CROSS_LOOP_FAILURE_NEW_SHAPE_ELIMINATES_IT"
        ),
        "historical_causality_claim": "NOT_PROVEN_BY_OFFLINE_REPRODUCTION_ALONE",
        "safety_counters": {
            "provider_calls": 0,
            "adjudicator_calls": 0,
            "credential_resolutions": 0,
            "transport_factory_calls": 0,
            "real_provider_transport": False,
        },
    }
    return {**material, "reproduction_hash": canonical_hash(material)}


def _attempt_projection(position: int, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "position": position,
        "logical_call_id": row["logical_call_id"],
        "failure_code": row["failure_code"],
        "provider_prompt_ids": row["provider_prompt_ids"],
        "latency_ms": row["latency_ms"],
        "actual_cost_usd": row["actual_cost_usd"],
        "attempt_index": row["attempt_index"],
    }


def _timing_and_cost_projection(
    position: int, row: Mapping[str, Any]
) -> dict[str, Any]:
    projection = {
        "position": position,
        "logical_call_id": row["logical_call_id"],
        "status": row["status"],
        "attempt_index": row["attempt_index"],
        "latency_ms": row["latency_ms"],
        "actual_cost_usd": row["actual_cost_usd"],
    }
    if "failure_code" in row:
        projection["failure_code"] = row["failure_code"]
    return projection


def build_forensic_classification(
    reproduction: Mapping[str, Any],
) -> dict[str, Any]:
    px._validated_predecessor_execution()
    manifest = _read(px.PREDECESSOR_EXECUTION_MANIFEST_PATH)
    audit = _read(px.PREDECESSOR_POST_EXECUTION_AUDIT_PATH)
    attempts = manifest["attempts"]
    provider_errors = [
        _attempt_projection(position, row)
        for position, row in enumerate(attempts, 1)
        if row.get("failure_code") == "MODEL_PROVIDER_ERROR"
    ]
    context_errors = [
        _attempt_projection(position, row)
        for position, row in enumerate(attempts, 1)
        if row.get("failure_code") == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    ]
    completed = [row for row in attempts if row.get("status") == "COMPLETED"]
    material = {
        "schema_version": "phase9-v2.0.2-forensic-classification/1.0.0",
        "source_execution_version": "phase9-execution/2.0.2",
        "source_execution_id": manifest["execution_id"],
        "classification_rule": "PERSISTED_V2_0_2_EVIDENCE_ONLY",
        "historical_rows_relabelled": False,
        "proven": {
            "provider_invocations": 30,
            "completed_logical_calls": 12,
            "failed_logical_calls": 18,
            "failure_counts": {
                "MODEL_PROVIDER_ERROR": 15,
                "MODEL_CONTEXT_NOT_ALLOWLISTED": 3,
            },
            "technical_retries": 0,
            "actual_accounted_cost_usd": manifest["actual_cost_usd"],
            "adjudicator_calls": 0,
            "all_attempt_timing_and_cost_evidence": [
                _timing_and_cost_projection(position, row)
                for position, row in enumerate(attempts, 1)
            ],
            "provider_error_rows": provider_errors,
            "context_error_rows": context_errors,
            "context_error_positions": [row["position"] for row in context_errors],
            "provider_error_positions": [row["position"] for row in provider_errors],
            "provider_error_latency_range_ms": [
                min(row["latency_ms"] for row in provider_errors),
                max(row["latency_ms"] for row in provider_errors),
            ],
            "provider_error_rows_with_zero_persisted_cost": sum(
                row["actual_cost_usd"] == 0 for row in provider_errors
            ),
            "completed_rows_with_full_four_billable_dimensions": sum(
                all(
                    field in row
                    for field in (
                        "input_tokens",
                        "cached_input_tokens",
                        "cache_write_input_tokens",
                        "output_tokens",
                    )
                )
                for row in completed
            ),
            "persisted_token_usage": audit["persisted_token_usage"],
            "authorization_consumption_state": audit[
                "authorization_consumption_state"
            ],
            "authorization_hash": audit["authorization_hash"],
        },
        "inference": {
            "classification": (
                "ASYNC_CROSS_LOOP_LIFECYCLE_IS_CONSISTENT_WITH_OBSERVED_PATTERN"
            ),
            "conditional_on": reproduction["reproduction_hash"],
            "basis": [
                "OFFLINE_LOOP_BOUND_FAKE_REPRODUCES_FAILURE_UNDER_OLD_SHAPE",
                "OFFLINE_SINGLE_LOOP_POPULATION_ELIMINATES_THE_FAILURE",
                "ALL_15_HISTORICAL_GENERIC_PROVIDER_ERRORS_ARE_AT_EVEN_POSITIONS",
                "ALL_15_HAVE_PERSISTED_LATENCY_21_TO_35_MS_AND_ZERO_PERSISTED_COST",
            ],
            "limit": (
                "CONSISTENCY_INFERENCE_ONLY_NOT_HISTORICAL_ROOT_CAUSE_PROOF"
            ),
        },
        "unknown": {
            "underlying_reason_code_for_15_model_provider_error_rows": (
                "NOT_PERSISTED_CANNOT_BE_RETROACTIVELY_MANUFACTURED"
            ),
            "context_failure_code_for_3_context_rows": (
                "NOT_PERSISTED_CANNOT_BE_RETROACTIVELY_MANUFACTURED"
            ),
            "token_usage_for_18_failed_rows": "NOT_PERSISTED",
            "reasoning_tokens_for_all_30_rows": "NOT_PERSISTED",
            "provider_request_id_hash_for_18_failed_rows": "NOT_PERSISTED",
            "provider_output_hash_for_3_post_response_context_failures": (
                "NOT_PERSISTED_IN_ATTEMPT_ROWS"
            ),
        },
        "non_actions": {
            "adjudication_bundle_created": False,
            "v2_0_2_evidence_modified": False,
            "historical_failure_codes_reclassified": False,
        },
        "source_file_hashes": {
            str(px.PREDECESSOR_EXECUTION_MANIFEST_PATH.relative_to(REPOSITORY_ROOT)): (
                _file_hash(px.PREDECESSOR_EXECUTION_MANIFEST_PATH)
            ),
            str(
                px.PREDECESSOR_POST_EXECUTION_AUDIT_PATH.relative_to(
                    REPOSITORY_ROOT
                )
            ): _file_hash(px.PREDECESSOR_POST_EXECUTION_AUDIT_PATH),
        },
    }
    return {**material, "forensic_report_hash": canonical_hash(material)}


def build_repair_report(
    reproduction: Mapping[str, Any],
    classification: Mapping[str, Any],
) -> dict[str, Any]:
    prepared = px.prepare_phase9_execution()
    historical_manifest = _read(px.PREDECESSOR_EXECUTION_MANIFEST_PATH)
    historical_output_hashes = {
        row["provider_output_hash"]
        for row in historical_manifest["attempts"]
        if row.get("status") == "COMPLETED"
    }
    successor_documents = [
        artifact
        for root in (px.EXECUTION_AUTHORITY_ROOT, px.EXECUTION_REPORT_ROOT)
        for artifact in root.rglob("*.json")
        if artifact
        not in {
            ASYNC_REPRODUCTION_PATH,
            FORENSIC_CLASSIFICATION_PATH,
            FORENSIC_REPAIR_REPORT_PATH,
        }
    ]
    successor_text = "\n".join(
        artifact.read_text(encoding="utf-8") for artifact in successor_documents
    )
    carried_hashes = sorted(
        output_hash
        for output_hash in historical_output_hashes
        if output_hash in successor_text
    )
    if carried_hashes:
        raise RuntimeError("v2.0.2 successful output hashes leaked into v2.0.3")
    material = {
        "schema_version": "phase9-post-execution-forensic-repair/2.0.3",
        "execution_version": px.PHASE9_EXECUTION_VERSION,
        "execution_boundary_hash": prepared.boundary["execution_boundary_hash"],
        "high_smoke_plan_hash": prepared.plan["plan_hash"],
        "ordered_logical_call_population_hash": canonical_hash(
            [call.identity() for call in prepared.calls]
        ),
        "population_decomposition": prepared.boundary["high_smoke_plan"][
            "decomposition"
        ],
        "async_lifecycle_reproduction_hash": reproduction["reproduction_hash"],
        "v2_0_2_forensic_report_hash": classification["forensic_report_hash"],
        "historical_v2_0_2_completed_output_hash_count": len(
            historical_output_hashes
        ),
        "historical_output_hashes_present_in_successor_documents": carried_hashes,
        "v2_0_2_successful_outputs_carried_forward": False,
        "successor_execution_manifest_count": (
            len(list(px.EXECUTION_EVIDENCE_ROOT.glob("*/execution_manifest.json")))
            if px.EXECUTION_EVIDENCE_ROOT.exists()
            else 0
        ),
        "successor_adjudication_bundle_count": (
            len(list(px.ADJUDICATION_BUNDLE_ROOT.rglob("bundle_manifest.json")))
            if px.ADJUDICATION_BUNDLE_ROOT.exists()
            else 0
        ),
        "billable_authorization_v2_0_3": (
            "NONE" if not px.BILLABLE_AUTHORIZATION_PATH.exists() else "PRESENT"
        ),
        "high_smoke_v2_0_3": "NOT_EXECUTED",
        "safety_counters": {
            "provider_calls": 0,
            "adjudicator_calls": 0,
            "credential_resolutions": 0,
            "transport_factory_calls": 0,
            "real_provider_transport": False,
        },
    }
    if (
        material["ordered_logical_call_population_hash"]
        != px.EXPECTED_ORDERED_LOGICAL_CALL_POPULATION_HASH
        or material["successor_execution_manifest_count"] != 0
        or material["successor_adjudication_bundle_count"] != 0
        or material["billable_authorization_v2_0_3"] != "NONE"
    ):
        raise RuntimeError("successor forensic safety state is not closed")
    return {**material, "repair_report_hash": canonical_hash(material)}


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    reproduction = build_async_reproduction()
    classification = build_forensic_classification(reproduction)
    repair = build_repair_report(reproduction, classification)
    return reproduction, classification, repair


def publish() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    documents = build()
    for artifact, payload in zip(
        (
            ASYNC_REPRODUCTION_PATH,
            FORENSIC_CLASSIFICATION_PATH,
            FORENSIC_REPAIR_REPORT_PATH,
        ),
        documents,
        strict=True,
    ):
        _write(artifact, payload)
    return documents


def check() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    documents = build()
    for artifact, expected in zip(
        (
            ASYNC_REPRODUCTION_PATH,
            FORENSIC_CLASSIFICATION_PATH,
            FORENSIC_REPAIR_REPORT_PATH,
        ),
        documents,
        strict=True,
    ):
        if not artifact.is_file() or _read(artifact) != expected:
            raise RuntimeError(f"published forensic repair evidence is stale: {artifact}")
    return documents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    reproduction, classification, repair = publish() if args.publish else check()
    print(
        json.dumps(
            {
                "status": "PUBLISHED" if args.publish else "VALID",
                "execution_version": px.PHASE9_EXECUTION_VERSION,
                "reproduction_hash": reproduction["reproduction_hash"],
                "forensic_report_hash": classification["forensic_report_hash"],
                "repair_report_hash": repair["repair_report_hash"],
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "credential_resolutions": 0,
                "transport_factory_calls": 0,
                "real_provider_transport": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
