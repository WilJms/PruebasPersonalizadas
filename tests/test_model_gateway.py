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
    ContextFailureCode,
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
from comprehension_verification.model_gateway.openai_schema import (
    provider_schema_validation_issues,
    structured_output_format,
)
from comprehension_verification.model_gateway.registry import prompt_spec
from comprehension_verification.model_gateway.gateway import (
    PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS,
)
from comprehension_verification.rehearsal import blueprint_review_is_approvable
from comprehension_verification.validation import build_blueprint_review_preflight


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

    assert {
        prompt_id: spec.prompt_version for prompt_id, spec in PROMPT_SPECS.items()
    } == {
        "P01_ACTIVITY_SPEC_V1": "1.1.3",
        "P02_RUBRIC_NORMALIZE_V1": "1.1.4",
        "P03_AMBIGUITY_TRIAGE_V1": "1.1.3",
        "P04_BLUEPRINT_BUILD_V1": "1.1.11",
        "P05_BLUEPRINT_REVIEW_V1": "1.1.8",
        "P06_EVIDENCE_MAP_V1": "1.1.5",
        "P07_QUESTION_BUILD_V1": "1.1.4",
        "P08_QUESTION_REVIEW_V1": "1.1.4",
        "P09_GUIDE_BUILD_V1": "1.1.6",
        "P10_ENRICHED_CONTEXT_V1": "1.1.3",
        "P11_SCHEMA_REPAIR_V1": "1.1.5",
    }
    assert (
        PROMPT_SPECS["P01_ACTIVITY_SPEC_V1"].prompt_hash
        == "sha256:e6406c13c06d52b3e2523166f48206c5cb0f892f26f8dc9258e311d8330d3d3e"
    )

    with pytest.raises(TypeError):
        PROMPT_CONTRACTS["P12_NOT_ALLOWED"] = ("Diagnostic", "Diagnostic")
    with pytest.raises(FrozenInstanceError):
        PROMPT_SPECS["P01_ACTIVITY_SPEC_V1"].temperature = 1.0


def test_p04_v111_makes_provider_invisible_invariants_explicit() -> None:
    p04 = PROMPT_SPECS["P04_BLUEPRINT_BUILD_V1"].developer_instruction
    for exact_rule in (
        "cada decision_id de resolved_decisions exactamente una vez",
        "no autorizan inventar resultados de aprendizaje",
        "learning_outcome_ids=[]",
        "dimension_id es único",
        "variant_id es único en todo el blueprint",
        "opportunity_template_id es único en todo el blueprint",
        "incluida en supported_operations de esa misma variante",
        "subconjunto de assessment_constraints.allowed_response_formats",
        "selected_opportunity_template_ids",
        "approved_by=null y approved_at=null",
        "selected_option inmutable",
        "No infieras el significado de un ID opaco",
        "required_criterion_ids como única cobertura obligatoria",
        "ni exijas una oportunidad compuesta",
        "status=BLOCKED con Diagnostic completo",
        "estado de finalización de la construcción del catálogo",
        "approved_by=null y approved_at=null no implican status=NEEDS_REVIEW",
        "usa status=READY aunque existan diagnósticos INFO/WARNING",
        "severity=ERROR o CRITICAL",
        "no emitas HUMAN_REVIEW_PENDING",
        "diagnostics[].evidence_ids usa únicamente evidence_id exactos",
        "Nunca escribas ahí statement_id, criterion_id, decision_id, issue_id ni option_id",
        "si ningún evidence_id autorizado sustenta el diagnóstico, usa evidence_ids=[]",
        "diagnostics[].source_ids usa únicamente source_id exactos autorizados",
        "En context_mode=CLOSED sin fuentes de curso autorizadas, usa source_ids=[]",
        "no clones, recicles ni reutilices IDs",
        "cantidad de IDs distintos",
        "semánticamente duplicadas, fusiónalas",
    ):
        assert exact_rule in p04


def test_p05_v117_and_p11_v115_make_root_invariant_handling_explicit() -> None:
    p05 = PROMPT_SPECS["P05_BLUEPRINT_REVIEW_V1"].developer_instruction
    assert "estado de finalización de esta revisión" in p05
    assert "status=READY y approval_recommendation=REJECT" in p05
    assert "approval_recommendation debe ser null" in p05
    assert "critical=true con status=FAIL" in p05
    assert "catálogo independiente de question_count" in p05
    assert "required_criterion_ids está vacío" in p05
    assert "No rechaces un catálogo amplio" in p05
    assert "no exijas identidad global" in p05
    assert "selected_option snapshot" in p05
    assert "exactamente 10 checks" in p05
    assert "APPROVE_WITH_CHANGES" in p05
    assert "nunca uses REJECT sin un FAIL crítico" in p05
    assert "activity_id exactamente desde activity_spec.activity_id" in p05
    assert "cuando status=READY, usa diagnostics=[]" in p05
    assert "deterministic_preflight" in p05
    assert "PLAN_FEASIBILITY debe ser PASS" in p05
    assert "no recalcules ni contradigas sus booleanos" in p05

    p11 = PROMPT_SPECS["P11_SCHEMA_REPAIR_V1"].developer_instruction
    assert "path=/ y error_type=value_error" in p11
    assert "usa UNREPAIRABLE" in p11
    assert "target_schema_name=BlueprintReview" in p11
    for protected_field in (
        "status",
        "approval_recommendation",
        "checks[].status",
        "checks[].critical",
    ):
        assert protected_field in p11


def test_p06_v115_makes_planner_eligibility_and_abstention_exact() -> None:
    p06 = PROMPT_SPECS["P06_EVIDENCE_MAP_V1"].developer_instruction
    for exact_rule in (
        "planning_policy es una restricción confiable",
        "planning_policy.minimum_evidence_fit",
        "no es necesario mapear todas sus dimensiones o variantes",
        "al menos assessment_constraints.question_count oportunidades",
        "copia literalmente desde ese template cognitive_operation",
        "activity_priority desde la dimensión padre",
        "mismo evidence_fit del EvidenceVariantMatch",
        "claims=[], variant_matches=[] y opportunities=[]",
        "code sea exactamente igual al status",
        "retryable=false",
    ):
        assert exact_rule in p06


def test_p07_p08_v114_bind_identities_and_separate_global_notices() -> None:
    p07 = PROMPT_SPECS["P07_QUESTION_BUILD_V1"].developer_instruction
    p08 = PROMPT_SPECS["P08_QUESTION_REVIEW_V1"].developer_instruction
    for exact_rule in (
        "submission_id exactamente desde plan.submission_id",
        "candidate.candidate_id exactamente desde target_candidate_id",
        "No redactes avisos globales",
    ):
        assert exact_rule in p07
    for exact_rule in (
        "submission_id exactamente desde generation_result.submission_id",
        "review.candidate_id exactamente desde generation_result.candidate.candidate_id",
        "nunca inventes candidate_id",
        "critical_failure_codes estables",
    ):
        assert exact_rule in p08


def test_p06_request_binds_planning_policy_to_blueprint_constraints() -> None:
    raw = build_mock_request("P06_EVIDENCE_MAP_V1").model_dump(mode="json")
    raw["planning_policy"]["minimum_opportunity_quality"] = 0.5
    with pytest.raises(
        ValidationError,
        match="planning policy must match",
    ):
        models.EvidenceMapRequest.model_validate(raw)


def test_p09_v115_makes_all_context_relationships_explicit() -> None:
    p09 = PROMPT_SPECS["P09_GUIDE_BUILD_V1"].developer_instruction
    for exact_reference in (
        "guide_id desde request.guide_id",
        "assessment_id desde request.assessment.assessment_id",
        "submission_id desde request.assessment.submission_id",
        "exactamente el mismo conjunto de question_id",
        "evidence_ids de esa pregunta",
        "course_source_ids de esa pregunta",
        "context_mode=CLOSED",
        "source_ids=[]",
        "NEEDS_REVIEW sin items parciales",
    ):
        assert exact_reference in p09


def test_blueprint_requests_require_self_contained_teacher_decisions() -> None:
    request = build_mock_request("P04_BLUEPRINT_BUILD_V1")
    decision = request.resolved_decisions[0]
    assert decision.selected_option is not None
    assert decision.selected_option.option_id == decision.selected_option_id

    raw = request.model_dump(mode="json")
    raw["resolved_decisions"][0]["selected_option"] = None
    with pytest.raises(
        ValidationError,
        match="resolved decisions require selected_option snapshots",
    ):
        models.BlueprintBuildRequest.model_validate(raw)

    mismatched = decision.model_dump(mode="json")
    mismatched["selected_option"]["option_id"] = "option_other"
    with pytest.raises(
        ValidationError,
        match="selected_option must match selected_option_id",
    ):
        models.PolicyDecision.model_validate(mismatched)

    duplicate_decision = decision.model_dump(mode="json")
    duplicate_decision["selected_option_id"] = "option_duplicate"
    duplicate_decision["selected_option"]["option_id"] = "option_duplicate"
    raw = request.model_dump(mode="json")
    raw["resolved_decisions"].append(duplicate_decision)
    with pytest.raises(
        ValidationError,
        match="resolved decisions must have unique decision_ids",
    ):
        models.BlueprintBuildRequest.model_validate(raw)

    duplicate_decision["decision_id"] = "decision_duplicate"
    raw = request.model_dump(mode="json")
    raw["resolved_decisions"].append(duplicate_decision)
    with pytest.raises(
        ValidationError,
        match="resolved decisions must have unique issue_ids",
    ):
        models.BlueprintBuildRequest.model_validate(raw)


def test_source_contracts_reject_duplicate_statement_and_level_ids() -> None:
    activity = _invoke("P01_ACTIVITY_SPEC_V1").output.model_dump(mode="json")
    activity["requirements"].append(dict(activity["learning_outcomes"][0]))
    with pytest.raises(ValidationError, match="ActivitySpec statement_ids must be unique"):
        models.ActivitySpec.model_validate(activity)

    rubric = _invoke("P02_RUBRIC_NORMALIZE_V1").output.model_dump(mode="json")
    duplicate = json.loads(json.dumps(rubric["criteria"][0]))
    duplicate["criterion_id"] = "criterion_duplicate"
    rubric["criteria"].append(duplicate)
    with pytest.raises(ValidationError, match="RubricSpec level_ids must be unique"):
        models.RubricSpec.model_validate(rubric)

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


def test_p04_nonready_requires_a_blocking_diagnostic() -> None:
    def leave_only_nonblocking_diagnostics(raw: dict) -> None:
        raw["status"] = "NEEDS_REVIEW"
        raw["diagnostics"] = [
            {
                "code": "HUMAN_REVIEW_PENDING",
                "severity": "WARNING",
                "message": "La aprobación humana posterior sigue pendiente.",
                "evidence_ids": [],
                "source_ids": [],
                "retryable": False,
                "details": {},
            }
        ]

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P04_BLUEPRINT_BUILD_V1", leave_only_nonblocking_diagnostics
        )
    )

    with pytest.raises(GatewayContextError) as captured:
        _invoke("P04_BLUEPRINT_BUILD_V1", gateway=gateway)

    assert captured.value.failure.phase == ValidationPhase.OUTPUT
    assert captured.value.failure.codes == (
        ContextFailureCode.P04_NONREADY_WITHOUT_BLOCKING_DIAGNOSTIC,
    )
    assert [item.result for item in captured.value.ledgers] == ["SCHEMA_INVALID"]


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


def _mutate_p01_context(raw: dict, scenario: str) -> None:
    diagnostic = {
        "code": "ASSIGNMENT_FIELD_MISSING",
        "severity": "ERROR",
        "message": "Diagnóstico sintético.",
        "evidence_ids": [],
        "source_ids": [],
        "retryable": False,
        "details": {},
    }
    if scenario == "evidence_id":
        raw["learning_outcomes"][0]["evidence_ids"] = ["ctx_private_value"]
    elif scenario == "source_id":
        diagnostic["source_ids"] = ["ctx_private_value"]
        raw["diagnostics"] = [diagnostic]
    elif scenario == "diagnostic_missing":
        raw.update(
            {
                "status": "NEEDS_REVIEW",
                "learning_outcomes": [],
                "expected_products": [],
                "requirements": [],
                "diagnostics": [],
            }
        )
    elif scenario == "sourced_fields_on_abstention":
        raw["status"] = "NEEDS_REVIEW"
        raw["diagnostics"] = [diagnostic]
    elif scenario == "activity_id":
        raw["activity_id"] = "ctx_private_value"
    elif scenario == "combined":
        raw["learning_outcomes"][0]["evidence_ids"] = ["ctx_private_value"]
        diagnostic["source_ids"] = ["ctx_private_value"]
        raw["contradictions"] = [diagnostic]
        raw["status"] = "NEEDS_REVIEW"
        raw["diagnostics"] = []
        raw["activity_id"] = "ctx_private_value"
    else:  # pragma: no cover - guards the test table itself
        raise AssertionError(f"Unknown P01 contextual scenario: {scenario}")


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    (
        ("evidence_id", ContextFailureCode.EVIDENCE_ID_NOT_ALLOWLISTED),
        ("source_id", ContextFailureCode.COURSE_SOURCE_ID_NOT_ALLOWLISTED),
        ("diagnostic_missing", ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING),
        (
            "sourced_fields_on_abstention",
            ContextFailureCode.P01_ABSTENTION_SOURCED_FIELDS_PRESENT,
        ),
        ("activity_id", ContextFailureCode.P01_ACTIVITY_ID_MISMATCH),
    ),
)
def test_p01_contextual_failures_are_distinct_and_content_free(
    scenario: str,
    expected_code: ContextFailureCode,
) -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    raw = (
        DeterministicMockAdapter()
        .factory.output_for(prompt_id, request, MockBehavior.HAPPY)
        .model_dump(mode="json")
    )
    _mutate_p01_context(raw, scenario)

    provider_schema = structured_output_format(
        prompt_spec(prompt_id), request
    )["schema"]
    assert not provider_schema_validation_issues(provider_schema, raw)
    assert isinstance(models.ActivitySpec.model_validate(raw), models.ActivitySpec)

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            prompt_id,
            lambda output: _mutate_p01_context(output, scenario),
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke(prompt_id, gateway=gateway)

    error = captured.value
    assert error.code == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    assert error.failure.phase == ValidationPhase.OUTPUT
    assert error.failure.code == expected_code
    assert error.failure.codes == (expected_code,)
    assert len(error.ledgers) == 1
    ledger = error.ledgers[0]
    assert ledger.prompt_id == prompt_id
    assert ledger.result == "SCHEMA_INVALID"
    assert "OUTPUT_CONTEXT_VALIDATION_FAILED" in ledger.route.reason_codes
    assert (
        f"CONTEXT_FAILURE_OUTPUT_{expected_code.value}"
        in ledger.route.reason_codes
    )
    serialized = json.dumps(ledger.model_dump(mode="json"), sort_keys=True)
    assert "ctx_private_value" not in serialized
    assert "Diagnóstico sintético" not in serialized


def test_p01_context_mode_cannot_match_the_historical_validation_boundary() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    raw = (
        DeterministicMockAdapter()
        .factory.output_for(prompt_id, request, MockBehavior.HAPPY)
        .model_dump(mode="json")
    )
    raw["diagnostics"] = [
        {
            "code": "ASSIGNMENT_FIELD_MISSING",
            "severity": "ERROR",
            "message": "Diagnóstico sintético.",
            "evidence_ids": [],
            "source_ids": [],
            "retryable": False,
            "details": {"context_mode": "COURSE_ENRICHED"},
        }
    ]
    provider_schema = structured_output_format(
        prompt_spec(prompt_id), request
    )["schema"]

    assert provider_schema_validation_issues(provider_schema, raw)
    assert isinstance(models.ActivitySpec.model_validate(raw), models.ActivitySpec)


def test_p01_context_observability_reports_all_coexisting_classes() -> None:
    prompt_id = "P01_ACTIVITY_SPEC_V1"
    request = build_mock_request(prompt_id)
    raw = (
        DeterministicMockAdapter()
        .factory.output_for(prompt_id, request, MockBehavior.HAPPY)
        .model_dump(mode="json")
    )
    _mutate_p01_context(raw, "combined")
    provider_schema = structured_output_format(
        prompt_spec(prompt_id), request
    )["schema"]
    assert not provider_schema_validation_issues(provider_schema, raw)
    assert isinstance(models.ActivitySpec.model_validate(raw), models.ActivitySpec)

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            prompt_id,
            lambda output: _mutate_p01_context(output, "combined"),
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke(prompt_id, gateway=gateway)

    expected_codes = (
        ContextFailureCode.EVIDENCE_ID_NOT_ALLOWLISTED,
        ContextFailureCode.COURSE_SOURCE_ID_NOT_ALLOWLISTED,
        ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING,
        ContextFailureCode.P01_ABSTENTION_SOURCED_FIELDS_PRESENT,
        ContextFailureCode.P01_ACTIVITY_ID_MISMATCH,
    )
    assert captured.value.failure.codes == expected_codes
    reason_codes = captured.value.ledgers[0].route.reason_codes
    assert all(
        f"CONTEXT_FAILURE_OUTPUT_{code.value}" in reason_codes
        for code in expected_codes
    )


def _mutate_p02_context(raw: dict, scenario: str) -> None:
    diagnostic = {
        "code": "RUBRIC_UNPARSABLE",
        "severity": "ERROR",
        "message": "Diagnóstico sintético.",
        "evidence_ids": [],
        "source_ids": [],
        "retryable": False,
        "details": {},
    }
    if scenario == "assignment_evidence_id":
        raw["criteria"][0]["evidence_ids"] = ["ev_assignment_1"]
    elif scenario == "diagnostic_missing":
        raw.update(
            {
                "status": "NEEDS_REVIEW",
                "criteria": [],
                "diagnostics": [],
            }
        )
    elif scenario == "criteria_on_abstention":
        raw["status"] = "NEEDS_REVIEW"
        raw["diagnostics"] = [diagnostic]
    elif scenario == "activity_id":
        raw["activity_id"] = "ctx_private_value"
    elif scenario == "combined":
        raw["criteria"][0]["evidence_ids"] = ["ev_assignment_1"]
        raw["status"] = "NEEDS_REVIEW"
        raw["diagnostics"] = []
        raw["activity_id"] = "ctx_private_value"
    else:  # pragma: no cover - guards the test table itself
        raise AssertionError(f"Unknown P02 contextual scenario: {scenario}")


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    (
        (
            "assignment_evidence_id",
            ContextFailureCode.P02_RUBRIC_EVIDENCE_ID_NOT_ALLOWLISTED,
        ),
        (
            "diagnostic_missing",
            ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING,
        ),
        (
            "criteria_on_abstention",
            ContextFailureCode.P02_ABSTENTION_CRITERIA_PRESENT,
        ),
        ("activity_id", ContextFailureCode.P02_ACTIVITY_ID_MISMATCH),
    ),
)
def test_p02_contextual_failures_are_distinct_and_content_free(
    scenario: str,
    expected_code: ContextFailureCode,
) -> None:
    prompt_id = "P02_RUBRIC_NORMALIZE_V1"
    request = build_mock_request(prompt_id)
    raw = (
        DeterministicMockAdapter()
        .factory.output_for(prompt_id, request, MockBehavior.HAPPY)
        .model_dump(mode="json")
    )
    _mutate_p02_context(raw, scenario)

    provider_schema = structured_output_format(
        prompt_spec(prompt_id), request
    )["schema"]
    assert not provider_schema_validation_issues(provider_schema, raw)
    assert isinstance(models.RubricSpec.model_validate(raw), models.RubricSpec)

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            prompt_id,
            lambda output: _mutate_p02_context(output, scenario),
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke(prompt_id, gateway=gateway)

    error = captured.value
    assert error.failure.phase == ValidationPhase.OUTPUT
    assert error.failure.codes == (expected_code,)
    assert len(error.ledgers) == 1
    reason_codes = error.ledgers[0].route.reason_codes
    assert f"CONTEXT_FAILURE_OUTPUT_{expected_code.value}" in reason_codes
    serialized = json.dumps(error.ledgers[0].model_dump(mode="json"))
    assert "ctx_private_value" not in serialized
    assert "Diagnóstico sintético" not in serialized


def test_p02_context_observability_reports_all_coexisting_classes() -> None:
    prompt_id = "P02_RUBRIC_NORMALIZE_V1"
    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            prompt_id,
            lambda output: _mutate_p02_context(output, "combined"),
        )
    )

    with pytest.raises(GatewayContextError) as captured:
        _invoke(prompt_id, gateway=gateway)

    expected_codes = (
        ContextFailureCode.P02_RUBRIC_EVIDENCE_ID_NOT_ALLOWLISTED,
        ContextFailureCode.ABSTENTION_DIAGNOSTIC_MISSING,
        ContextFailureCode.P02_ABSTENTION_CRITERIA_PRESENT,
        ContextFailureCode.P02_ACTIVITY_ID_MISMATCH,
    )
    assert captured.value.failure.codes == expected_codes
    reason_codes = captured.value.ledgers[0].route.reason_codes
    assert all(
        f"CONTEXT_FAILURE_OUTPUT_{code.value}" in reason_codes
        for code in expected_codes
    )


def _p09_context_case(scenario: str) -> tuple[models.GuideBuildRequest, dict]:
    prompt_id = "P09_GUIDE_BUILD_V1"
    request = build_mock_request(prompt_id)

    if scenario == "question_coverage":
        assessment_data = request.assessment.model_dump(mode="json")
        second_question = json.loads(json.dumps(assessment_data["questions"][0]))
        second_question["question_id"] = "question_demo_2"
        assessment_data["question_count"] = 2
        assessment_data["questions"].append(second_question)
        request = request.model_copy(
            update={"assessment": models.Assessment.model_validate(assessment_data)}
        )
    elif scenario == "question_evidence_id":
        bundle_data = request.evidence_bundle.model_dump(mode="json")
        extra_evidence = json.loads(json.dumps(bundle_data["evidence_units"][0]))
        extra_evidence["evidence_id"] = "ev_context_authorized_not_question"
        bundle_data["allowed_evidence_ids"].append(
            "ev_context_authorized_not_question"
        )
        bundle_data["evidence_units"].append(extra_evidence)
        request = request.model_copy(
            update={
                "evidence_bundle": models.EvidenceBundle.model_validate(bundle_data)
            }
        )
    elif scenario == "question_source_id":
        enriched_bundle = build_mock_request(
            "P10_ENRICHED_CONTEXT_V1"
        ).evidence_bundle
        assessment_data = request.assessment.model_dump(mode="json")
        assessment_data["context_mode"] = "COURSE_ENRICHED"
        request = request.model_copy(
            update={
                "assessment": models.Assessment.model_validate(assessment_data),
                "evidence_bundle": enriched_bundle,
            }
        )

    raw = (
        DeterministicMockAdapter()
        .factory.output_for(prompt_id, request, MockBehavior.HAPPY)
        .model_dump(mode="json")
    )
    if scenario == "guide_id":
        raw["guide_id"] = "ctx_private_value"
    elif scenario == "assessment_id":
        raw["assessment_id"] = "ctx_private_value"
    elif scenario == "submission_id":
        raw["submission_id"] = "ctx_private_value"
    elif scenario == "question_coverage":
        raw["items"] = raw["items"][:1]
    elif scenario == "unknown_question_id":
        raw["items"][0]["question_id"] = "ctx_private_value"
    elif scenario == "question_evidence_id":
        raw["items"][0]["guide"]["observable_elements"][0][
            "evidence_ids"
        ] = ["ev_context_authorized_not_question"]
    elif scenario == "question_source_id":
        raw["items"][0]["guide"]["observable_elements"][0]["source_ids"] = [
            "source_course_1"
        ]
    else:  # pragma: no cover - guards the test table itself
        raise AssertionError(f"Unknown P09 contextual scenario: {scenario}")
    return request, raw


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    (
        ("guide_id", ContextFailureCode.P09_GUIDE_ID_MISMATCH),
        ("assessment_id", ContextFailureCode.P09_ASSESSMENT_ID_MISMATCH),
        ("submission_id", ContextFailureCode.P09_SUBMISSION_ID_MISMATCH),
        (
            "question_coverage",
            ContextFailureCode.P09_QUESTION_COVERAGE_MISMATCH,
        ),
        ("unknown_question_id", ContextFailureCode.P09_UNKNOWN_QUESTION_ID),
        (
            "question_evidence_id",
            ContextFailureCode.P09_QUESTION_EVIDENCE_ID_NOT_ALLOWLISTED,
        ),
        (
            "question_source_id",
            ContextFailureCode.P09_QUESTION_SOURCE_ID_NOT_ALLOWLISTED,
        ),
    ),
)
def test_p09_contextual_failures_are_distinct_and_content_free(
    scenario: str,
    expected_code: ContextFailureCode,
) -> None:
    prompt_id = "P09_GUIDE_BUILD_V1"
    request, raw = _p09_context_case(scenario)
    provider_schema = structured_output_format(
        prompt_spec(prompt_id), request
    )["schema"]
    assert not provider_schema_validation_issues(provider_schema, raw)
    assert isinstance(models.EvaluationGuide.model_validate(raw), models.EvaluationGuide)

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            prompt_id,
            lambda output: output.update(raw),
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        asyncio.run(
            gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
            )
        )

    error = captured.value
    assert error.code == "MODEL_CONTEXT_NOT_ALLOWLISTED"
    assert error.failure.phase == ValidationPhase.OUTPUT
    assert error.failure.codes == (expected_code,)
    assert len(error.ledgers) == 1
    ledger = error.ledgers[0]
    assert ledger.result == "SCHEMA_INVALID"
    assert (
        f"CONTEXT_FAILURE_OUTPUT_{expected_code.value}"
        in ledger.route.reason_codes
    )
    serialized = json.dumps(ledger.model_dump(mode="json"), sort_keys=True)
    for protected_value in (
        "ctx_private_value",
        "ev_context_authorized_not_question",
        "source_course_1",
    ):
        assert protected_value not in serialized


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


def test_p04_rejects_missing_verifiable_source_coverage() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)
    first = request.rubric_spec.criteria[0]
    request = request.model_copy(
        update={
            "rubric_spec": request.rubric_spec.model_copy(
                update={
                    "criteria": [
                        first,
                        first.model_copy(
                            update={
                                "criterion_id": "criterion_2",
                                "name": "Límite",
                                "levels": [
                                    level.model_copy(
                                        update={"level_id": "level_criterion_2"}
                                    )
                                    for level in first.levels
                                ],
                            }
                        ),
                    ]
                }
            )
        }
    )

    def omit_second_criterion(raw: dict) -> None:
        raw["dimensions"][0]["criterion_ids"] = ["criterion_1"]

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(prompt_id, omit_second_criterion)
    )
    with pytest.raises(GatewayContextError) as captured:
        asyncio.run(
            gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
            )
        )

    assert captured.value.failure.codes == (
        ContextFailureCode.P04_SOURCE_COVERAGE_MISMATCH,
    )


def test_p04_rejects_catalog_without_an_exact_n_time_feasible_set() -> None:
    def exceed_total_time(raw: dict) -> None:
        for dimension in raw["dimensions"]:
            for variant in dimension["evidence_variants"]:
                for opportunity in variant["question_opportunities"]:
                    opportunity["target_minutes"] = 6

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P04_BLUEPRINT_BUILD_V1", exceed_total_time
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke("P04_BLUEPRINT_BUILD_V1", gateway=gateway)

    assert captured.value.failure.codes == (
        ContextFailureCode.P04_CATALOG_PLAN_INFEASIBLE,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (
            lambda raw: raw.update({"activity_id": "act_outside_review"}),
            ContextFailureCode.P05_REFERENCE_MISMATCH,
        ),
        (
            lambda raw: raw["checks"][0].update(
                {"referenced_ids": ["id_outside_review_roots"]}
            ),
            ContextFailureCode.P05_REFERENCED_ID_NOT_ALLOWLISTED,
        ),
    ),
)
def test_p05_reference_failures_have_prompt_local_codes(
    mutation,
    expected_code: ContextFailureCode,
) -> None:  # type: ignore[no-untyped-def]
    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P05_BLUEPRINT_REVIEW_V1", mutation
        )
    )

    with pytest.raises(GatewayContextError) as captured:
        _invoke("P05_BLUEPRINT_REVIEW_V1", gateway=gateway)

    assert captured.value.failure.codes == (expected_code,)


def test_p05_rejects_untrusted_preflight_and_output_disagreement() -> None:
    prompt_id = "P05_BLUEPRINT_REVIEW_V1"
    request = build_mock_request(prompt_id)
    assert request.deterministic_preflight == build_blueprint_review_preflight(
        blueprint=request.blueprint,
        activity_spec=request.activity_spec,
        rubric_spec=request.rubric_spec,
        blueprint_policy=request.blueprint_policy,
    )
    forged = request.model_copy(
        update={
            "deterministic_preflight": (
                request.deterministic_preflight.model_copy(
                    update={"catalog_plan_feasible": False}
                )
            )
        }
    )
    with pytest.raises(GatewayContextError) as forged_error:
        asyncio.run(
            ModelGateway().invoke(
                prompt_id,
                forged,
                build_trusted_context(forged),
            )
        )
    assert forged_error.value.failure.codes == (
        ContextFailureCode.P05_PREFLIGHT_MISMATCH,
    )

    def contradict_preflight(raw: dict) -> None:
        for check in raw["checks"]:
            if check["category"] == "PLAN_FEASIBILITY":
                check.update({"status": "FAIL", "critical": True})
        raw["approval_recommendation"] = "REJECT"

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            prompt_id, contradict_preflight
        )
    )
    with pytest.raises(GatewayContextError) as output_error:
        _invoke(prompt_id, gateway=gateway)
    assert output_error.value.failure.codes == (
        ContextFailureCode.P05_PREFLIGHT_CHECK_MISMATCH,
    )


def test_blueprint_review_matrix_is_exact_and_matches_product_transition() -> None:
    valid = _invoke("P05_BLUEPRINT_REVIEW_V1").output
    raw = valid.model_dump(mode="json")

    raw["checks"][0]["status"] = "WARN"
    with pytest.raises(ValidationError):
        models.BlueprintReview.model_validate(raw)
    raw["approval_recommendation"] = "APPROVE_WITH_CHANGES"
    warning_review = models.BlueprintReview.model_validate(raw)
    assert blueprint_review_is_approvable(warning_review) is True

    duplicate_category = valid.model_dump(mode="json")
    duplicate_category["checks"][-1]["category"] = (
        duplicate_category["checks"][0]["category"]
    )
    with pytest.raises(ValidationError):
        models.BlueprintReview.model_validate(duplicate_category)

    unjustified_reject = valid.model_dump(mode="json")
    unjustified_reject["approval_recommendation"] = "REJECT"
    with pytest.raises(ValidationError):
        models.BlueprintReview.model_validate(unjustified_reject)

    critical_reject = valid.model_dump(mode="json")
    critical_reject["checks"][0].update(
        {"status": "FAIL", "critical": True}
    )
    critical_reject["approval_recommendation"] = "REJECT"
    rejected_review = models.BlueprintReview.model_validate(critical_reject)
    assert blueprint_review_is_approvable(rejected_review) is False


def test_p06_rejects_changed_template_inheritance() -> None:
    def change_inherited_focus(raw: dict) -> None:
        raw["opportunities"][0]["focus"] = "Foco distinto"

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P06_EVIDENCE_MAP_V1", change_inherited_focus
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke("P06_EVIDENCE_MAP_V1", gateway=gateway)
    assert captured.value.failure.codes == (
        ContextFailureCode.P06_FOCUS_MISMATCH,
    )


def test_p06_relationship_diagnostics_identify_each_failed_predicate() -> None:
    def change_multiple_relationships(raw: dict) -> None:
        opportunity = raw["opportunities"][0]
        opportunity["observable"] = "Observable distinto"
        opportunity["target_minutes"] += 1
        opportunity["evidence_fit"] = 0.81

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P06_EVIDENCE_MAP_V1", change_multiple_relationships
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke("P06_EVIDENCE_MAP_V1", gateway=gateway)

    assert captured.value.failure.codes == (
        ContextFailureCode.P06_OBSERVABLE_MISMATCH,
        ContextFailureCode.P06_TARGET_MINUTES_MISMATCH,
        ContextFailureCode.P06_EVIDENCE_FIT_MISMATCH,
    )


def test_p06_relationship_diagnostic_identifies_widened_evidence_scope() -> None:
    request = build_mock_request("P06_EVIDENCE_MAP_V1")
    base = request.evidence_bundle.evidence_units[0]
    extra = base.model_copy(
        update={
            "evidence_id": "ev_submission_2",
            "artifact_id": "art_submission_2",
            "artifact_hash": "sha256:" + "d" * 64,
            "normalized_hash": "sha256:" + "e" * 64,
        }
    )
    request = request.model_copy(
        update={
            "evidence_bundle": request.evidence_bundle.model_copy(
                update={
                    "allowed_evidence_ids": [
                        "ev_submission_1",
                        "ev_submission_2",
                    ],
                    "evidence_units": [base, extra],
                }
            )
        }
    )

    def widen_scope(raw: dict) -> None:
        raw["variant_matches"][0]["evidence_ids"] = ["ev_submission_1"]
        raw["opportunities"][0]["evidence_ids"] = ["ev_submission_2"]

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P06_EVIDENCE_MAP_V1", widen_scope
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        asyncio.run(
            gateway.invoke(
                "P06_EVIDENCE_MAP_V1",
                request,
                build_trusted_context(request),
            )
        )

    assert captured.value.failure.codes == (
        ContextFailureCode.P06_EVIDENCE_SCOPE_WIDENED,
    )


def test_p06_ready_requires_the_planner_evidence_fit_floor() -> None:
    def lower_fit(raw: dict) -> None:
        for match in raw["variant_matches"]:
            match["evidence_fit"] = 0.69
        for opportunity in raw["opportunities"]:
            opportunity["evidence_fit"] = 0.69

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P06_EVIDENCE_MAP_V1", lower_fit
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke("P06_EVIDENCE_MAP_V1", gateway=gateway)
    assert captured.value.failure.codes == (
        ContextFailureCode.P06_READY_ELIGIBILITY_MISMATCH,
    )


def test_p07_relationship_failures_are_aggregated_content_free() -> None:
    def change_candidate_roots(raw: dict) -> None:
        raw["candidate"]["candidate_id"] = "candidate_other"
        raw["candidate"]["dimension_id"] = "dimension_other"

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P07_QUESTION_BUILD_V1", change_candidate_roots
        )
    )
    with pytest.raises(GatewayContextError) as captured:
        _invoke("P07_QUESTION_BUILD_V1", gateway=gateway)
    assert captured.value.failure.codes == (
        ContextFailureCode.P07_CANDIDATE_ID_MISMATCH,
        ContextFailureCode.P07_OPPORTUNITY_REFERENCE_MISMATCH,
    )


def test_p06_nonready_diagnostics_are_canonical_fail_closed() -> None:
    request = build_mock_request("P06_EVIDENCE_MAP_V1")
    raw = DeterministicMockAdapter().factory.output_for(
        "P06_EVIDENCE_MAP_V1", request, MockBehavior.ABSTAIN
    ).model_dump(mode="json")
    raw["diagnostics"][0]["retryable"] = True
    with pytest.raises(ValidationError):
        models.EvidenceMapPatch.model_validate(raw)


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

    assert captured.value.failure.codes == (
        ContextFailureCode.P08_ACCEPTED_BELOW_POLICY,
    )
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


def test_value_error_skips_p11_and_preserves_primary_failure_and_ledger() -> None:
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
    assert error.repair_disposition == "NOT_STRUCTURALLY_REPAIRABLE"
    assert error.resolution is None
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


def test_real_attestation_is_verified_before_adapter_transport() -> None:
    prompt_id = "P04_BLUEPRINT_BUILD_V1"
    request = build_mock_request(prompt_id)

    class CountingAdapter(DeterministicMockAdapter):
        calls = 0

        async def invoke(self, **kwargs) -> AdapterResult:  # type: ignore[no-untyped-def]
            self.calls += 1
            return await super().invoke(**kwargs)

    adapter = CountingAdapter()
    routes = build_openai_routes(max_call_cost_usd=1.0)
    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.REAL, max_retries=0),
        real_routes=routes,
        adapters={"openai": adapter},
    )
    forged = build_trusted_context(request).model_copy(
        update={"attested_input_hash": "sha256:" + "0" * 64}
    )

    with pytest.raises(GatewayContextError) as captured:
        asyncio.run(gateway.invoke(prompt_id, request, forged))

    assert captured.value.failure.codes == (
        ContextFailureCode.SYNTHETIC_ATTESTATION_HASH_MISMATCH,
    )
    assert adapter.calls == 0
    assert captured.value.ledgers == ()


def test_execution_fingerprint_invalidates_only_affected_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = ModelGateway()
    p04_before = gateway.execution_fingerprint("P04_BLUEPRINT_BUILD_V1")
    p07_before = gateway.execution_fingerprint("P07_QUESTION_BUILD_V1")

    monkeypatch.setitem(
        PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS,
        "P04_BLUEPRINT_BUILD_V1",
        "relationship-p04/test-local-change",
    )

    assert gateway.execution_fingerprint("P04_BLUEPRINT_BUILD_V1") != p04_before
    assert gateway.execution_fingerprint("P07_QUESTION_BUILD_V1") == p07_before


def test_cached_output_replays_context_and_relationship_validation() -> None:
    prompt_id = "P07_QUESTION_BUILD_V1"
    request = build_mock_request(prompt_id)
    context = build_trusted_context(request)
    output = _invoke(prompt_id).output.model_dump(mode="json")
    output["candidate"]["candidate_id"] = "candidate_stale_other_scope"

    with pytest.raises(GatewayContextError):
        ModelGateway().validate_cached_output(
            prompt_id,
            request,
            context,
            output,
        )


def test_p11_rejects_semantic_mutation_even_when_target_shape_is_valid() -> None:
    def mutate_semantics(raw: dict) -> None:
        raw["repaired_output"]["learning_outcomes"][0]["text"] = (
            "Invented semantic replacement"
        )

    gateway = ModelGateway(
        mock_adapter=ContextBreakingAdapter(
            "P11_SCHEMA_REPAIR_V1", mutate_semantics
        )
    )

    with pytest.raises(
        GatewayContextError,
        match="failed contextual validation",
    ) as exc_info:
        _invoke("P11_SCHEMA_REPAIR_V1", gateway=gateway)
    assert exc_info.value.__cause__ is not None
    assert "semantic content" in str(exc_info.value.__cause__)


def test_direct_p11_repair_is_structural_and_target_valid() -> None:
    request = build_mock_request("P11_SCHEMA_REPAIR_V1")
    result = _invoke("P11_SCHEMA_REPAIR_V1")

    assert result.output.repair_status == models.RepairStatus.REPAIRED
    repaired = model_by_name(request.target_schema_name).model_validate(
        result.output.repaired_output
    )
    assert isinstance(repaired, models.ActivitySpec)
    assert "unexpected_field" not in result.output.repaired_output


def test_p11_abstains_from_ambiguous_blueprint_review_root_invariant() -> None:
    valid_review = _invoke("P05_BLUEPRINT_REVIEW_V1").output.model_dump(
        mode="json"
    )
    valid_review["status"] = "NEEDS_REVIEW"
    valid_review["approval_recommendation"] = "APPROVE"
    request = models.SchemaRepairRequest(
        target_schema_name="BlueprintReview",
        invalid_output=valid_review,
        validation_issues=[
            models.SchemaValidationIssue(
                path="/",
                error_type="value_error",
                message="Canonical output model validation failed",
            )
        ],
    )

    result = asyncio.run(
        ModelGateway().invoke(
            "P11_SCHEMA_REPAIR_V1",
            request,
            build_trusted_context(request),
        )
    )

    assert result.output.repair_status == models.RepairStatus.UNREPAIRABLE
    assert result.output.repaired_output is None


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
