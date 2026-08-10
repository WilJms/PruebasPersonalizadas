from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
import json

from pydantic import ValidationError
import pytest

from comprehension_verification.contracts import model_by_name, models
from comprehension_verification.model_gateway import (
    CallBudget,
    GatewayBudgetExceeded,
    GatewayConfig,
    GatewayContextError,
    GatewayMode,
    GatewayRouteBlocked,
    GatewaySchemaViolation,
    GatewayTimeout,
    GatewayValidationError,
    MockBehavior,
    ModelGateway,
    PROMPT_CONTRACTS,
    PROMPT_SPECS,
    ValidationPhase,
    build_mock_request,
    build_openai_routes,
    build_trusted_context,
)
from comprehension_verification.model_gateway.mock_factory import (
    AdapterResult,
    DeterministicMockAdapter,
)


EXPECTED_PROMPT_CONTRACTS = {
    "P01_ACTIVITY_SPEC_V1": ("ActivitySpecRequest", "ActivitySpec"),
    "P02_RUBRIC_NORMALIZE_V1": ("RubricNormalizeRequest", "RubricSpec"),
    "P03_AMBIGUITY_TRIAGE_V1": ("AmbiguityTriageRequest", "AmbiguityReport"),
    "P04_BLUEPRINT_BUILD_V1": ("BlueprintBuildRequest", "AssessmentBlueprint"),
    "P05_BLUEPRINT_REVIEW_V1": ("BlueprintReviewRequest", "BlueprintReview"),
    "P06_EVIDENCE_MAP_V1": ("EvidenceMapRequest", "EvidenceMapPatch"),
    "P07_QUESTION_BUILD_V1": ("QuestionBuildRequest", "QuestionGenerationResult"),
    "P08_QUESTION_REVIEW_V1": ("QuestionReviewRequest", "QuestionReviewResult"),
    "P09_GUIDE_BUILD_V1": ("GuideBuildRequest", "EvaluationGuide"),
    "P10_ENRICHED_CONTEXT_V1": ("QuestionBuildRequest", "QuestionGenerationResult"),
    "P11_SCHEMA_REPAIR_V1": ("SchemaRepairRequest", "SchemaRepairResult"),
}


FIXED_CLOCK = lambda: datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _invoke(
    prompt_id: str,
    *,
    behavior: MockBehavior = MockBehavior.HAPPY,
    gateway: ModelGateway | None = None,
    budget: CallBudget | None = None,
):
    request = build_mock_request(prompt_id)
    context = build_trusted_context(request)
    return asyncio.run(
        (gateway or ModelGateway()).invoke(
            prompt_id, request, context, behavior=behavior, budget=budget
        )
    )


class ContextBreakingAdapter(DeterministicMockAdapter):
    def __init__(self, prompt_id: str, mutate) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.prompt_id = prompt_id
        self.mutate = mutate

    async def invoke(self, **kwargs) -> AdapterResult:  # type: ignore[no-untyped-def]
        result = await super().invoke(**kwargs)
        if kwargs["prompt_id"] != self.prompt_id:
            return result
        raw = json.loads(json.dumps(result.raw_output))
        self.mutate(raw)
        return AdapterResult(
            raw_output=raw,
            input_tokens=result.input_tokens,
            cached_input_tokens=result.cached_input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            actual_cost_usd=result.actual_cost_usd,
        )


def test_registry_is_exact_complete_and_immutable() -> None:
    assert dict(PROMPT_CONTRACTS) == EXPECTED_PROMPT_CONTRACTS
    assert set(PROMPT_SPECS) == set(EXPECTED_PROMPT_CONTRACTS)
    for prompt_id, (request_root, output_root) in EXPECTED_PROMPT_CONTRACTS.items():
        spec = PROMPT_SPECS[prompt_id]
        assert (spec.input_schema_name, spec.output_schema_name) == (
            request_root,
            output_root,
        )
        assert model_by_name(request_root).__name__ == request_root
        assert model_by_name(output_root).__name__ == output_root

    with pytest.raises(TypeError):
        PROMPT_CONTRACTS["P12_NOT_ALLOWED"] = ("Diagnostic", "Diagnostic")
    with pytest.raises(FrozenInstanceError):
        PROMPT_SPECS["P01_ACTIVITY_SPEC_V1"].temperature = 1.0


@pytest.mark.parametrize("prompt_id", tuple(EXPECTED_PROMPT_CONTRACTS))
def test_every_prompt_happy_path_is_canonical_and_deterministic(prompt_id: str) -> None:
    gateway = ModelGateway(GatewayConfig(clock=FIXED_CLOCK))
    first = _invoke(prompt_id, gateway=gateway)
    second = _invoke(prompt_id, gateway=gateway)
    expected_root = model_by_name(EXPECTED_PROMPT_CONTRACTS[prompt_id][1])

    assert isinstance(first.output, expected_root)
    assert first.output.model_dump(mode="json") == second.output.model_dump(mode="json")
    assert first.validation_order[:3] == (
        ValidationPhase.REQUEST,
        ValidationPhase.ENVELOPE,
        ValidationPhase.OUTPUT,
    )
    assert len(first.ledgers) == 1
    ledger = first.ledgers[0]
    assert ledger.result == "SCHEMA_VALID"
    assert ledger.route.provider == "other"
    assert ledger.route.model.startswith("deterministic-mock-")
    assert ledger.route.reason_codes[0] == "MOCK_MODE"
    assert ledger.actual_cost_usd == 0.0
    assert first.route_resolution.status == "RESOLVED"


def test_mock_ledger_is_byte_stable_across_runtime_latencies(monkeypatch) -> None:
    def serialized_ledger(started: float, finished: float) -> str:
        ticks = iter((started, finished))
        monkeypatch.setattr(
            "comprehension_verification.model_gateway.gateway.perf_counter",
            lambda: next(ticks),
        )
        result = _invoke(
            "P01_ACTIVITY_SPEC_V1",
            gateway=ModelGateway(GatewayConfig(clock=FIXED_CLOCK)),
        )
        return json.dumps(
            [item.model_dump(mode="json") for item in result.ledgers],
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )

    fast = serialized_ledger(10.0, 10.001)
    slow = serialized_ledger(20.0, 20.750)

    assert fast == slow
    assert json.loads(fast)[0]["latency_ms"] == 0


@pytest.mark.parametrize("prompt_id", tuple(EXPECTED_PROMPT_CONTRACTS))
def test_every_prompt_has_contract_valid_abstention(prompt_id: str) -> None:
    result = _invoke(prompt_id, behavior=MockBehavior.ABSTAIN)
    expected_root = model_by_name(EXPECTED_PROMPT_CONTRACTS[prompt_id][1])
    assert isinstance(result.output, expected_root)
    assert result.ledgers[-1].result == "SCHEMA_VALID"

    output = result.output
    if prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
        assert output.blocked is True
        assert output.issues
    elif prompt_id == "P11_SCHEMA_REPAIR_V1":
        assert output.repair_status == models.RepairStatus.UNREPAIRABLE
        assert output.repaired_output is None
        assert output.diagnostics
    elif prompt_id in {"P07_QUESTION_BUILD_V1", "P10_ENRICHED_CONTEXT_V1"}:
        assert output.status == "REPLACEMENT_REQUIRED"
        assert output.candidate is None
        assert output.diagnostics
    elif prompt_id == "P08_QUESTION_REVIEW_V1":
        assert output.status == "NEEDS_REVIEW"
        assert output.review is None
        assert output.diagnostics
    elif prompt_id == "P09_GUIDE_BUILD_V1":
        assert output.status == "NEEDS_REVIEW"
        assert output.items == []
        assert output.diagnostics
    else:
        assert output.status != "READY"
        if hasattr(output, "diagnostics"):
            assert output.diagnostics


def test_p04_cannot_fabricate_human_approval_metadata() -> None:
    blueprint = _invoke("P04_BLUEPRINT_BUILD_V1").output
    forged = blueprint.model_copy(
        update={
            "status": models.WorkflowStatus.APPROVED,
            "approved_by": "usr_forged",
            "approved_at": FIXED_CLOCK(),
        }
    )
    with pytest.raises(GatewayContextError, match="human approval metadata"):
        ModelGateway._validate_clean_abstention(
            "P04_BLUEPRINT_BUILD_V1", forged
        )


def test_context_invalid_provider_output_is_ledgered_as_invalid() -> None:
    adapter = ContextBreakingAdapter(
        "P01_ACTIVITY_SPEC_V1",
        lambda raw: raw.update({"activity_id": "act_invented"}),
    )
    sink: list[models.ModelCallLedger] = []
    gateway = ModelGateway(mock_adapter=adapter, ledger_sink=sink.append)

    with pytest.raises(GatewayContextError) as captured:
        _invoke("P01_ACTIVITY_SPEC_V1", gateway=gateway)

    assert len(captured.value.ledgers) == 1
    assert captured.value.ledgers[0].result == "SCHEMA_INVALID"
    assert sink == list(captured.value.ledgers)


def test_p04_rejects_invented_source_ids_and_records_attempt() -> None:
    def invent_criterion(raw: dict) -> None:
        raw["dimensions"][0]["criterion_ids"] = ["criterion_invented"]
        raw["dimensions"][0]["learning_outcome_ids"] = ["outcome_invented"]

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P04_BLUEPRINT_BUILD_V1", invent_criterion
        )
    )

    with pytest.raises(GatewayContextError) as captured:
        _invoke("P04_BLUEPRINT_BUILD_V1", gateway=gateway)

    assert [item.result for item in captured.value.ledgers] == ["SCHEMA_INVALID"]


def test_p08_cannot_accept_below_trusted_validation_thresholds() -> None:
    def lower_scores(raw: dict) -> None:
        raw["review"]["scores"]["groundedness"] = 0.0
        raw["review"]["confidence"] = 0.0
        raw["review"]["critical_failure_codes"] = ["UNGROUNDED"]

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P08_QUESTION_REVIEW_V1", lower_scores
        )
    )

    with pytest.raises(GatewayContextError) as captured:
        _invoke("P08_QUESTION_REVIEW_V1", gateway=gateway)

    assert [item.result for item in captured.value.ledgers] == ["SCHEMA_INVALID"]


def test_invalid_once_uses_one_p11_repair_and_revalidates_target() -> None:
    result = _invoke("P01_ACTIVITY_SPEC_V1", behavior=MockBehavior.INVALID_ONCE)

    assert result.repaired is True
    assert isinstance(result.output, models.ActivitySpec)
    assert result.validation_order == (
        ValidationPhase.REQUEST,
        ValidationPhase.ENVELOPE,
        ValidationPhase.OUTPUT,
        ValidationPhase.REPAIRED_OUTPUT,
    )
    assert result.repair_validation_order == (
        ValidationPhase.REQUEST,
        ValidationPhase.ENVELOPE,
        ValidationPhase.OUTPUT,
        ValidationPhase.REPAIRED_OUTPUT,
    )
    assert [(ledger.prompt_id, ledger.result) for ledger in result.ledgers] == [
        ("P01_ACTIVITY_SPEC_V1", "SCHEMA_INVALID"),
        ("P11_SCHEMA_REPAIR_V1", "SCHEMA_VALID"),
    ]
    assert sum(ledger.prompt_id == "P11_SCHEMA_REPAIR_V1" for ledger in result.ledgers) == 1


def test_blocked_p11_preserves_primary_p07_validation_failure_and_ledger() -> None:
    prompt_id = "P07_QUESTION_BUILD_V1"
    request = build_mock_request(prompt_id)
    raw_output = DeterministicMockAdapter().factory.output_for(
        prompt_id, request, MockBehavior.HAPPY
    ).model_dump(mode="json")
    raw_output["candidate"] = None

    class OneInvalidP07Adapter:
        calls = 0

        async def invoke(self, **_kwargs) -> AdapterResult:  # type: ignore[no-untyped-def]
            self.calls += 1
            return AdapterResult(
                raw_output=raw_output,
                input_tokens=321,
                cached_input_tokens=21,
                output_tokens=45,
                estimated_cost_usd=0.002,
                actual_cost_usd=0.001,
                cache_write_input_tokens=9,
                reasoning_tokens=17,
                effective_model="gpt-5.6-luna",
                output_hash="sha256:" + "1" * 64,
                provider_request_id_hash="sha256:" + "2" * 64,
                provider_schema_valid=True,
                provider_schema_issues=(),
                reason_codes=("SDK_RETRIES_0", "STRUCTURED_OUTPUT_STRICT"),
            )

    adapter = OneInvalidP07Adapter()
    all_routes = build_openai_routes(max_call_cost_usd=1.0)
    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.REAL, max_retries=0),
        real_routes={prompt_id: all_routes[prompt_id]},
        adapters={"openai": adapter},
    )

    with pytest.raises(GatewaySchemaViolation) as captured:
        asyncio.run(
            gateway.invoke(prompt_id, request, build_trusted_context(request))
        )

    error = captured.value
    assert error.code == "MODEL_OUTPUT_VALIDATION_FAILED"
    assert error.repair_disposition == "BLOCKED_BY_ROUTE_POLICY"
    assert error.resolution is not None
    assert error.resolution.reason_codes == ["REAL_ROUTE_NOT_CONFIGURED"]
    assert adapter.calls == 1
    assert len(error.ledgers) == 1
    ledger = error.ledgers[0]
    assert ledger.prompt_id == prompt_id
    assert ledger.result == "SCHEMA_INVALID"
    assert ledger.input_tokens == 321
    assert ledger.cached_input_tokens == 21
    assert ledger.output_tokens == 45
    assert ledger.actual_cost_usd == 0.001
    assert ledger.route.model_snapshot == "gpt-5.6-luna"
    assert "OUTPUT_PYDANTIC_VALIDATION_FAILED" in ledger.route.reason_codes
    assert "PROVIDER_REQUEST_ID_HASH_" + "2" * 64 in ledger.route.reason_codes
    assert "OUTPUT_HASH_" + "1" * 64 in ledger.route.reason_codes
    primary = error.primary_failure
    assert primary is not None
    assert primary.phase == ValidationPhase.OUTPUT
    assert primary.code == "OUTPUT_PYDANTIC_VALIDATION_FAILED"
    assert primary.validation_engine == "PYDANTIC_MODEL_VALIDATE"
    assert primary.provider_schema_valid is True
    assert primary.provider_schema_issues == ()
    assert [(issue.error_type, issue.path) for issue in primary.issues] == [
        ("value_error", "/")
    ]
    assert not isinstance(error.__context__, ValidationError)


def test_direct_p11_repair_is_structural_and_target_valid() -> None:
    request = build_mock_request("P11_SCHEMA_REPAIR_V1")
    result = _invoke("P11_SCHEMA_REPAIR_V1")

    assert result.output.repair_status == models.RepairStatus.REPAIRED
    repaired = model_by_name(request.target_schema_name).model_validate(
        result.output.repaired_output
    )
    assert isinstance(repaired, models.ActivitySpec)
    assert "unexpected_field" not in result.output.repaired_output


def test_p11_never_repairs_its_own_invalid_output_recursively() -> None:
    with pytest.raises(GatewaySchemaViolation) as captured:
        _invoke("P11_SCHEMA_REPAIR_V1", behavior=MockBehavior.INVALID_ONCE)

    assert len(captured.value.ledgers) == 1
    assert captured.value.ledgers[0].prompt_id == "P11_SCHEMA_REPAIR_V1"
    assert captured.value.ledgers[0].result == "SCHEMA_INVALID"


def test_timeout_retries_at_most_twice_and_ledgers_every_attempt() -> None:
    sink: list[models.ModelCallLedger] = []
    gateway = ModelGateway(
        GatewayConfig(
            timeout_seconds=0.001,
            max_retries=2,
            backoff_base_seconds=0,
            clock=FIXED_CLOCK,
        ),
        ledger_sink=sink.append,
    )

    with pytest.raises(GatewayTimeout) as captured:
        _invoke("P01_ACTIVITY_SPEC_V1", behavior=MockBehavior.TIMEOUT, gateway=gateway)

    assert len(captured.value.ledgers) == 3
    assert sink == list(captured.value.ledgers)
    assert [(ledger.attempt, ledger.result) for ledger in sink] == [
        (1, "TIMEOUT"),
        (2, "TIMEOUT"),
        (3, "TIMEOUT"),
    ]


def test_p11_timeout_has_exactly_one_attempt() -> None:
    gateway = ModelGateway(
        GatewayConfig(
            timeout_seconds=0.001,
            max_retries=2,
            backoff_base_seconds=0,
        )
    )
    with pytest.raises(GatewayTimeout) as captured:
        _invoke("P11_SCHEMA_REPAIR_V1", behavior=MockBehavior.TIMEOUT, gateway=gateway)
    assert [(ledger.attempt, ledger.result) for ledger in captured.value.ledgers] == [
        (1, "TIMEOUT")
    ]


def test_budget_is_checked_before_any_adapter_call() -> None:
    sink: list[models.ModelCallLedger] = []
    gateway = ModelGateway(ledger_sink=sink.append)
    with pytest.raises(GatewayBudgetExceeded) as captured:
        _invoke(
            "P01_ACTIVITY_SPEC_V1",
            gateway=gateway,
            budget=CallBudget(max_cost_usd=0.001, estimated_cost_usd=0.002),
        )
    assert sink == []
    assert captured.value.resolution.status == "BLOCKED"
    assert captured.value.resolution.reason_codes == ["CALL_BUDGET_EXCEEDED"]


def test_real_mode_without_explicit_route_or_adapter_is_blocked() -> None:
    gateway = ModelGateway(GatewayConfig(mode=GatewayMode.REAL))
    with pytest.raises(GatewayRouteBlocked) as captured:
        _invoke("P01_ACTIVITY_SPEC_V1", gateway=gateway)
    assert captured.value.resolution.status == "BLOCKED"
    assert captured.value.resolution.reason_codes == ["REAL_ROUTE_NOT_CONFIGURED"]


def test_ledger_contains_hashes_and_metrics_but_no_student_content() -> None:
    result = _invoke("P07_QUESTION_BUILD_V1")
    serialized = json.dumps(result.ledgers[0].model_dump(mode="json"), ensure_ascii=False)

    assert "sha256:" in serialized
    assert "La caché se consulta antes del cálculo" not in serialized
    assert "content_text" not in serialized
    assert "question_text" not in serialized
    assert "anchor" not in serialized
    assert "payload" not in serialized


def test_request_validation_happens_before_envelope_or_ledger() -> None:
    request = build_mock_request("P01_ACTIVITY_SPEC_V1")
    context = build_trusted_context(request)
    sink: list[models.ModelCallLedger] = []
    gateway = ModelGateway(ledger_sink=sink.append)

    with pytest.raises(GatewayValidationError) as captured:
        asyncio.run(gateway.invoke("P01_ACTIVITY_SPEC_V1", {}, context))
    assert captured.value.phase == ValidationPhase.REQUEST
    assert sink == []


def test_gateway_configuration_rejects_more_than_two_retries() -> None:
    with pytest.raises(ValueError, match="between 0 and 2"):
        GatewayConfig(max_retries=3)


def test_mock_is_the_explicit_default_mode() -> None:
    assert GatewayConfig().mode == GatewayMode.MOCK
