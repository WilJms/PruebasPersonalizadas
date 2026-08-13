from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import zipfile

from docx import Document
import pytest

from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway import (
    GatewayConfig,
    GatewayMode,
    ModelGateway,
)
from comprehension_verification.qualification_semantics import (
    CheckpointClass,
    ContractualAdherence,
    OracleValidity,
    SemanticInterpretation,
    aggregate_causal_classification,
    classify_checkpoint,
)
from comprehension_verification.semantic_harness import (
    FROZEN_PRODUCT_BOUNDARY_PATH,
    SEMANTIC_FIXTURE_PATH,
    build_checkpoint_provenance,
    build_reviewed_semantic_adapter,
    build_semantic_checkpoints,
    classifier_branch_proof,
    frozen_product_boundary_proof,
    load_semantic_fixture,
    run_semantic_harness_rehearsal,
    validate_checkpoint_provenance,
)
from comprehension_verification.rehearsal import (
    CANONICAL_DOCUMENT_SCENARIO_ID,
    QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
    ProductRehearsal,
    qualification_matrix_rows,
    run_offline_convergence_sync,
)
from comprehension_verification.validation import (
    ContextValidationError,
    validate_generation_result,
)
from comprehension_verification.web.workflows import Stage1Service
from scripts import run_openai_evals as eval_harness
from scripts.build_semantic_harness_documents import build_documents


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_ROOT = (
    ROOT / "tests/fixtures/openai_evals/v3/document_shaped_cache_case"
)


def test_document_pack_is_deterministic_inert_and_structurally_readable(
    tmp_path: Path,
) -> None:
    generated = build_documents(tmp_path)
    expected = sorted(DOCUMENT_ROOT.glob("*.docx"))
    generated_by_name = {path.name: path for path in generated}
    assert set(generated_by_name) == {path.name for path in expected}
    for reference in expected:
        actual = generated_by_name[reference.name]
        assert actual.read_bytes() == reference.read_bytes()
        document = Document(actual)
        assert document.paragraphs
        with zipfile.ZipFile(actual) as package:
            names = package.namelist()
            assert "word/document.xml" in names
            assert not any(
                marker in name.casefold()
                for name in names
                for marker in (
                    "vbaproject",
                    "activex",
                    "embeddings/",
                    "webextensions/",
                )
            )
            for name in names:
                if not name.endswith(".rels"):
                    continue
                assert b'TargetMode="External"' not in package.read(name)


def test_document_shaped_checkpoints_use_parser_goldens_and_product_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_bundle_calls: list[str] = []
    original_submission_pipeline = Stage1Service._run_submission_pipeline

    def capture_product_boundary(self: object, job: object):  # type: ignore[no-untyped-def]
        product_bundle_calls.append(str(getattr(job, "aggregate_id")))
        return original_submission_pipeline(self, job)  # type: ignore[arg-type]

    monkeypatch.setattr(
        Stage1Service,
        "_run_submission_pipeline",
        capture_product_boundary,
    )
    checkpoints = build_semantic_checkpoints()
    assert product_bundle_calls == [
        "submission_cache_sufficient",
        "submission_cache_insufficient",
    ]
    assert {
        unit.artifact_id for unit in checkpoints.sufficient_bundle.evidence_units
    } == {"artifact_semantic_submission_sufficient"}
    assert {
        unit.artifact_id for unit in checkpoints.insufficient_bundle.evidence_units
    } == {"artifact_semantic_submission_insufficient"}
    assert checkpoints.p04_request.rubric_spec is not None
    assert checkpoints.p04_request.rubric_spec.criteria[0].grading_weight == 1.0
    assert checkpoints.blueprint.dimensions[0].grading_weight == 1.0
    assert len(checkpoints.p05_review.checks) == 10
    assert checkpoints.p05_review.approval_recommendation == (
        m.BlueprintApprovalRecommendation.APPROVE
    )

    assert checkpoints.p07_positive_result.status == "READY"
    assert checkpoints.p07_positive_result.candidate is not None
    positive_evidence = checkpoints.p07_positive_result.candidate.evidence_ids
    assert set(positive_evidence).issubset(
        checkpoints.sufficient_bundle.allowed_evidence_ids
    )
    assert checkpoints.p07_negative_result.status == "REPLACEMENT_REQUIRED"
    assert checkpoints.p07_negative_result.candidate is None
    assert checkpoints.p07_negative_result.diagnostics[0].severity == m.Severity.ERROR
    assert checkpoints.p07_negative_result.diagnostics[0].retryable is False

    assert checkpoints.p08_positive_result.review is not None
    assert checkpoints.p08_positive_result.review.decision == m.ReviewDecision.ACCEPT
    assert checkpoints.p08_negative_result.review is not None
    assert checkpoints.p08_negative_result.review.decision == m.ReviewDecision.REJECT
    policy = checkpoints.p08_positive_request.validation_policy
    scores = checkpoints.p08_positive_result.review.scores
    assert scores.groundedness >= policy.minimum_groundedness
    assert scores.anchor_sufficiency >= policy.minimum_anchor_sufficiency
    assert scores.criterion_relevance >= policy.minimum_criterion_relevance
    assert scores.answerability >= policy.minimum_answerability

    assessment = checkpoints.p09_request.assessment
    assert len(assessment.questions) == 1
    assert assessment.questions[0].source_candidate_id == (
        checkpoints.p07_positive_result.candidate.candidate_id
    )
    assert checkpoints.p09_guide.assessment_id == assessment.assessment_id
    assert checkpoints.p09_guide.items[0].question_id == (
        assessment.questions[0].question_id
    )


def test_canonical_document_integrated_chain_uses_current_outputs_without_goldens() -> None:
    adapter = build_reviewed_semantic_adapter()
    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=adapter,
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_chain(
            run_id="canonical-document-no-golden-injection",
            scenario_id=CANONICAL_DOCUMENT_SCENARIO_ID,
        )
    )
    assert observation.status == "PASS"
    assert [
        row.get("prompt_id", row.get("stage")) for row in observation.stages
    ] == [
        "P04_BLUEPRINT_BUILD_V1",
        "P05_BLUEPRINT_REVIEW_V1",
        "P06_EVIDENCE_MAP_V1",
        "PLANNER",
        "P07_QUESTION_BUILD_V1",
        "P08_QUESTION_REVIEW_V1",
        "ASSEMBLY",
        "P09_GUIDE_BUILD_V1",
    ]
    assert len(adapter.invocations) == 6
    assert {
        item["response_origin"] for item in adapter.invocations
    } == {"STRUCTURAL_TRANSPORT_SUBSTITUTE"}
    by_stage = {
        row.get("prompt_id", row.get("stage")): row
        for row in observation.stages
    }
    assert by_stage["P04_BLUEPRINT_BUILD_V1"]["input_origin"] == (
        "PRODUCT_DERIVED_DOCUMENT_BOUNDARY"
    )
    assert by_stage["P05_BLUEPRINT_REVIEW_V1"]["upstream_output_hash"] == (
        by_stage["P05_BLUEPRINT_REVIEW_V1"]["consumed_blueprint_hash"]
    )
    assert by_stage["PLANNER"]["consumed_mapping_hash"] == (
        by_stage["P06_EVIDENCE_MAP_V1"]["output_hash"]
    )
    assert by_stage["P08_QUESTION_REVIEW_V1"]["upstream_output_hash"] == (
        by_stage["P08_QUESTION_REVIEW_V1"]["consumed_generation_hash"]
    )
    assert by_stage["P09_GUIDE_BUILD_V1"]["consumed_assessment_hash"] == (
        by_stage["ASSEMBLY"]["output_hash"]
    )
    assert not any(
        row.get("intermediate_golden_injected") is True
        for row in observation.stages
    )


def test_matrix_restores_independent_base2_and_derives_request_cap() -> None:
    matrix = qualification_matrix_rows()
    assert [row["row_id"] for row in matrix] == [
        "semantic-sweep:P04-P09:versioned-positive-and-negative",
        "offline-golden-positive:P05",
        "offline-golden-negative:P05",
        "integrated-chain:base:1:P04-P09",
        "integrated-chain:base:2:P04-P09",
        "integrated-chain:choice-variant:P04-P09",
        "integrated-chain:canonical-document-sufficient:P04-P09",
    ]
    assert sum(row["max_provider_calls"] for row in matrix) == 33
    assert QUALIFICATION_EXPECTED_PROVIDER_REQUESTS == 33
    report = run_offline_convergence_sync()
    by_id = {item["run_id"]: item for item in report["observations"]}
    base1 = by_id["chain-base-1"]
    base2 = by_id["chain-base-2"]
    assert base1["status"] == base2["status"] == "PASS"
    assert base1["output_hash"] != base2["output_hash"]
    assert report["controls"]["provider_attempts"] == 33
    assert report["derived_max_provider_requests"] == 33


def test_negative_abstention_semantics_and_contract_adherence_are_separate() -> None:
    checkpoints = build_semantic_checkpoints()
    incomplete = checkpoints.p07_negative_result.model_copy(
        update={"diagnostics": []}
    )
    with pytest.raises(ContextValidationError, match="failed output requires diagnostics"):
        validate_generation_result(
            incomplete,
            opportunity=checkpoints.p07_negative_request.opportunity,
            bundle=checkpoints.insufficient_bundle,
        )
    reviewed = classify_checkpoint(
        checkpoint_id="P07_INSUFFICIENT_WITH_BAD_DIAGNOSTIC",
        checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
        oracle_validity=OracleValidity.VALID,
        semantic_interpretation=SemanticInterpretation.DEFENDIBLE,
        contractual_adherence=ContractualAdherence.FAIL,
        semantic_review_id="SR-P07-CACHE-NEG-001",
        semantic_review_version="1.0.0",
        semantic_review_hash="sha256:" + "1" * 64,
        reason_codes=["DIAGNOSTIC_INCOMPLETE"],
    )
    assert reviewed.semantic_interpretation == SemanticInterpretation.DEFENDIBLE
    assert reviewed.contractual_adherence == ContractualAdherence.FAIL
    assert reviewed.causal_attribution.value == (
        "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE"
    )


def test_semantic_sweep_receipt_preserves_defendible_abstention_on_bad_adherence() -> None:
    class IncompleteNegativeDiagnosticAdapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            request = kwargs["request"]
            raw = deepcopy(result.raw_output)
            if (
                kwargs["prompt_id"] == "P07_QUESTION_BUILD_V1"
                and isinstance(request, m.QuestionBuildRequest)
                and request.evidence_bundle.submission_id
                == "submission_cache_insufficient"
            ):
                raw["diagnostics"] = []
            return replace(result, raw_output=raw)

    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=IncompleteNegativeDiagnosticAdapter(),
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_sweep(
            run_id="semantic-adherence-proof"
        )
    )
    by_id = {
        row["checkpoint_id"]: row
        for row in observation.checkpoint_assessments
    }
    assessment = by_id["P07_INSUFFICIENT_NEGATIVE"]
    assert observation.status == "FAIL"
    assert assessment["operational_outcome"] == "FAIL"
    assert assessment["semantic_interpretation"] == "DEFENDIBLE"
    assert assessment["contractual_adherence"] == "FAIL"
    assert assessment["causal_attribution"] == (
        "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE"
    )


def test_p05_positive_cannot_hide_a_semantic_failure_as_approvable() -> None:
    class SourceFidelityFailureAdapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            request = kwargs["request"]
            raw = deepcopy(result.raw_output)
            if (
                kwargs["prompt_id"] == "P05_BLUEPRINT_REVIEW_V1"
                and isinstance(request, m.BlueprintReviewRequest)
                and request.blueprint.assessment_constraints.allowed_response_formats
                == [m.ResponseFormat.OPEN_SHORT]
            ):
                for check in raw["checks"]:
                    if check["category"] == "SOURCE_FIDELITY":
                        check["status"] = "FAIL"
                        check["critical"] = False
                raw["approval_recommendation"] = "APPROVE_WITH_CHANGES"
            return replace(result, raw_output=raw)

    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=SourceFidelityFailureAdapter(),
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_sweep(
            run_id="semantic-p05-failure-proof"
        )
    )
    by_id = {
        row["checkpoint_id"]: row
        for row in observation.checkpoint_assessments
    }
    assessment = by_id["P05_CANONICAL_POSITIVE"]
    assert observation.status == "FAIL"
    assert assessment["semantic_interpretation"] == "INCORRECT"
    assert assessment["contractual_adherence"] == "PASS"
    assert assessment["causal_attribution"] == "MODEL_OWNED_SEMANTIC_FAILURE"


def test_p07_semantically_equivalent_alternative_passes_without_exact_equality() -> None:
    class StructurallyValidAlternativeAdapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            request = kwargs["request"]
            raw = deepcopy(result.raw_output)
            if (
                kwargs["prompt_id"] == "P07_QUESTION_BUILD_V1"
                and isinstance(request, m.QuestionBuildRequest)
                and request.evidence_bundle.submission_id
                == "submission_cache_sufficient"
            ):
                raw["candidate"]["question_text"] = (
                    "Explica la relación entre el cambio de fuente, la "
                    "invalidación y la consulta posterior usando el fragmento."
                )
            return replace(result, raw_output=raw)

    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=StructurallyValidAlternativeAdapter(),
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_sweep(
            run_id="semantic-p07-independent-review-proof"
        )
    )
    by_id = {
        row["checkpoint_id"]: row
        for row in observation.checkpoint_assessments
    }
    assessment = by_id["P07_CANONICAL_POSITIVE"]
    assert observation.status == "PASS"
    assert assessment["operational_outcome"] == "PASS"
    assert assessment["semantic_interpretation"] == "CORRECT"
    assert assessment["contractual_adherence"] == "PASS"
    assert assessment["causal_attribution"] == "NONE"


@pytest.mark.parametrize(
    ("mutation", "expected_interpretation", "expected_operational", "expected_cause"),
    [
        (
            "external",
            "INCORRECT",
            "FAIL",
            "MODEL_OWNED_SEMANTIC_FAILURE",
        ),
        (
            "insufficient_anchor",
            "INCORRECT",
            "FAIL",
            "MODEL_OWNED_SEMANTIC_FAILURE",
        ),
        (
            "underdetermined",
            "INDETERMINATE",
            "INCONCLUSIVE",
            "CAUSE_INDETERMINATE",
        ),
    ],
)
def test_p07_invariant_oracle_distinguishes_bad_and_indeterminate_candidates(
    mutation: str,
    expected_interpretation: str,
    expected_operational: str,
    expected_cause: str,
) -> None:
    class P07MutationAdapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            request = kwargs["request"]
            raw = deepcopy(result.raw_output)
            if (
                kwargs["prompt_id"] == "P07_QUESTION_BUILD_V1"
                and isinstance(request, m.QuestionBuildRequest)
                and request.evidence_bundle.submission_id
                == "submission_cache_sufficient"
            ):
                if mutation == "external":
                    raw["candidate"]["question_text"] = (
                        "Explica cómo implementar la invalidación con un mutex "
                        "y coordinar hilos concurrentes cuando cambia la fuente."
                    )
                elif mutation == "insufficient_anchor":
                    source = next(
                        unit.content_text
                        for unit in request.evidence_bundle.evidence_units
                        if unit.evidence_id
                        == raw["candidate"]["anchor"]["fragments"][0][
                            "evidence_id"
                        ]
                    )
                    assert source is not None
                    raw["candidate"]["anchor"]["fragments"][0][
                        "display_text"
                    ] = source.split(".", maxsplit=1)[0] + "."
                else:
                    raw["candidate"]["question_text"] = (
                        "Comenta la decisión descrita en el fragmento."
                    )
            return replace(result, raw_output=raw)

    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=P07MutationAdapter(),
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_sweep(
            run_id=f"semantic-p07-{mutation}-proof"
        )
    )
    assessment = next(
        row
        for row in observation.checkpoint_assessments
        if row["checkpoint_id"] == "P07_CANONICAL_POSITIVE"
    )
    assert observation.status == "FAIL"
    assert assessment["semantic_interpretation"] == expected_interpretation
    assert assessment["operational_outcome"] == expected_operational
    assert assessment["contractual_adherence"] == "PASS"
    assert assessment["causal_attribution"] == expected_cause


def test_p06_semantically_equivalent_mapping_passes_without_exact_equality() -> None:
    class AlternativeP06Adapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            request = kwargs["request"]
            raw = deepcopy(result.raw_output)
            if (
                kwargs["prompt_id"] == "P06_EVIDENCE_MAP_V1"
                and isinstance(request, m.EvidenceMapRequest)
                and request.evidence_bundle.submission_id
                == "submission_cache_sufficient"
            ):
                raw["claims"][0]["claim_id"] = "claim_cache_equivalent_alternative"
                raw["claims"][0]["text"] = (
                    "La fuente actualizada deja sin validez la entrada previa; "
                    "la consulta posterior vuelve a calcular y evita un valor "
                    "desactualizado."
                )
                raw["variant_matches"][0]["justification"] = (
                    "La misma secuencia causal está localizada en la evidencia."
                )
                raw["opportunities"][0]["opportunity_id"] = (
                    "opportunity_cache_equivalent_alternative"
                )
            return replace(result, raw_output=raw)

    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=AlternativeP06Adapter(),
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_sweep(
            run_id="semantic-p06-equivalent-proof"
        )
    )
    assessment = next(
        row
        for row in observation.checkpoint_assessments
        if row["checkpoint_id"] == "P06_CANONICAL_POSITIVE"
    )
    assert observation.status == "PASS"
    assert assessment["operational_outcome"] == "PASS"
    assert assessment["semantic_interpretation"] == "CORRECT"


def test_p06_mapping_with_wrong_evidence_fails_semantically() -> None:
    class WrongEvidenceP06Adapter:
        def __init__(self) -> None:
            self.inner = build_reviewed_semantic_adapter()

        async def invoke(self, **kwargs: object):  # type: ignore[no-untyped-def]
            result = await self.inner.invoke(**kwargs)
            request = kwargs["request"]
            raw = deepcopy(result.raw_output)
            if (
                kwargs["prompt_id"] == "P06_EVIDENCE_MAP_V1"
                and isinstance(request, m.EvidenceMapRequest)
                and request.evidence_bundle.submission_id
                == "submission_cache_sufficient"
            ):
                wrong_evidence = next(
                    unit.evidence_id
                    for unit in request.evidence_bundle.evidence_units
                    if unit.modality == m.EvidenceModality.PARAGRAPH
                    and "Informe técnico breve" == unit.content_text
                )
                raw["variant_matches"][0]["evidence_ids"] = [wrong_evidence]
                raw["opportunities"][0]["evidence_ids"] = [wrong_evidence]
            return replace(result, raw_output=raw)

    gateway = ModelGateway(
        GatewayConfig(mode=GatewayMode.MOCK, max_retries=0),
        mock_adapter=WrongEvidenceP06Adapter(),
    )
    observation = asyncio.run(
        ProductRehearsal(gateway, max_call_cost_usd=1.0).run_sweep(
            run_id="semantic-p06-wrong-evidence-proof"
        )
    )
    assessment = next(
        row
        for row in observation.checkpoint_assessments
        if row["checkpoint_id"] == "P06_CANONICAL_POSITIVE"
    )
    assert observation.status == "FAIL"
    assert assessment["semantic_interpretation"] == "INCORRECT"
    assert assessment["contractual_adherence"] == "PASS"
    assert assessment["causal_attribution"] == "MODEL_OWNED_SEMANTIC_FAILURE"


def test_every_checkpoint_has_explicit_provenance_and_mocks_are_structural() -> None:
    checkpoints = build_semantic_checkpoints()
    rows = build_checkpoint_provenance(checkpoints)
    validate_checkpoint_provenance(rows)
    assert {row["prompt_id"] for row in rows}.issuperset(
        {
            "P04_BLUEPRINT_BUILD_V1",
            "P05_BLUEPRINT_REVIEW_V1",
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P08_QUESTION_REVIEW_V1",
            "P09_GUIDE_BUILD_V1",
        }
    )
    for row in rows:
        if row["oracle_origin"] == "DeterministicMockFactory":
            assert row["checkpoint_class"] == (
                "STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY"
            )
        elif row["checkpoint_class"].startswith("SEMANTICALLY_QUALIFIED_"):
            assert row["oracle_origin"] == "CODEX_AUTHORED_SEMANTIC_REVIEW"
            assert row["independent_review_status"] == (
                "USER_SUPPLIED_INDEPENDENT_REVIEW_FINDINGS"
            )
            assert row["human_ratification"] is None
            assert row["prior_review_hash"].startswith("sha256:")
            assert row["review_hash"] == row["prior_review_hash"]
            assert row["current_review_material_hash"].startswith("sha256:")
            assert row["provenance_amendment_hash"].startswith("sha256:")
        elif row["checkpoint_class"] != (
            "STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY"
        ):
            assert row["review_hash"].startswith("sha256:")
            assert row["golden_hash"].startswith("sha256:")
            assert row["source_artifact_hashes"]


def test_classifier_covers_semantics_adherence_oracle_uncertainty_and_technical() -> None:
    proof = classifier_branch_proof()
    assert len(proof) == 6
    assert all(item["status"] == "PASS" for item in proof)
    assert {item["expected_causal_attribution"] for item in proof} == {
        "MODEL_OWNED_SEMANTIC_FAILURE",
        "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE",
        "CORRECT_NEGATIVE_DECISION",
        "ORACLE_OR_CHECKPOINT_INVALID",
        "CAUSE_INDETERMINATE",
        "TECHNICAL_FAILURE",
    }
    assessments = [
        classify_checkpoint(
            checkpoint_id="negative-pass",
            checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
            oracle_validity=OracleValidity.VALID,
            semantic_interpretation=SemanticInterpretation.CORRECT,
            contractual_adherence=ContractualAdherence.PASS,
            semantic_review_id="SR-NEG",
            semantic_review_version="1.0.0",
            semantic_review_hash="sha256:" + "2" * 64,
        )
    ]
    assert aggregate_causal_classification(assessments) == "QUALIFICATION_PASSED"


def test_terra_outcome_uses_versioned_checkpoint_assessments() -> None:
    assessment = classify_checkpoint(
        checkpoint_id="P08_VALID_POSITIVE",
        checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
        oracle_validity=OracleValidity.VALID,
        semantic_interpretation=SemanticInterpretation.INCORRECT,
        contractual_adherence=ContractualAdherence.PASS,
        semantic_review_id="SR-P08",
        semantic_review_version="1.0.0",
        semantic_review_hash="sha256:" + "3" * 64,
        reason_codes=["QUESTION_POLICY_VIOLATION"],
    )
    outcome = eval_harness._terra_medium_qualification_outcome(
        {
            "status": "FAIL",
            "observations": [
                {"failure": {"codes": ["QUESTION_POLICY_VIOLATION"]}}
            ],
            "checkpoint_assessments": [assessment.model_dump()],
        }
    )
    assert outcome["qualification_outcome"] == (
        "TERRA_MEDIUM_QUALIFICATION_FAILED"
    )
    assert outcome["causal_classification"] == (
        "MODEL_OWNED_SEMANTIC_FAILURE"
    )


def test_offline_rehearsal_has_zero_provider_activity_and_valid_goldens() -> None:
    report = run_semantic_harness_rehearsal()
    assert report["status"] == "PASS"
    assert report["causal_classification"] == "QUALIFICATION_PASSED"
    assert all(item["status"] == "PASS" for item in report["checks"])
    assert report["controls"] == {
        "provider_attempts": 0,
        "mock_gateway_invocations": 33,
        "billable_requests": 0,
        "network_calls_to_openai": 0,
        "terra_executions": 0,
        "luna_executions": 0,
        "sol_executions": 0,
        "provider_adapter_constructed": False,
        "provider_secret_resolved": False,
        "p10_calls": 0,
        "p11_calls": 0,
        "prompt_changes": 0,
        "validator_changes": 0,
        "threshold_changes": 0,
        "planner_changes": 0,
        "assembler_changes": 0,
        "product_workflow_changes": 0,
        "deploys": 0,
    }
    assert report["phase"] == "HARNESS_FINAL_SEMANTIC_HARDENING"
    assert report["canonical_pack"]["document_shaped"] is True
    assert report["canonical_pack"]["artifact_count"] == 4
    rehearsal = report["offline_qualification_rehearsal"]
    assert rehearsal["derived_max_provider_requests"] == 33
    assert rehearsal["base_chain_2"]["independent_output"] is True
    assert rehearsal["canonical_document_chain"] == {
        "status": "PASS",
        "stage_count": 8,
        "current_run_dataflow": True,
        "intermediate_golden_injections": 0,
        "semantic_quality_conclusion_allowed": False,
    }
    assert rehearsal["transport_provenance"] == {
        "provider_transport_constructed": False,
        "reviewed_semantic_oracle_invocations": 9,
        "structural_transport_substitute_invocations": 24,
        "semantic_sweep_response_origin": "REVIEWED_SEMANTIC_ORACLE",
        "integrated_chain_response_origin": (
            "STRUCTURAL_TRANSPORT_SUBSTITUTE"
        ),
        "integrated_chain_semantic_quality_conclusion_allowed": False,
    }


def test_frozen_product_boundary_matches_initial_head() -> None:
    manifest = json.loads(FROZEN_PRODUCT_BOUNDARY_PATH.read_text(encoding="utf-8"))
    proof = frozen_product_boundary_proof()
    assert proof["baseline_git_sha"] == (
        "9dbce36d21ba6b28b32b051862cf8b305ded61e8"
    )
    assert proof["source_file_sha256"] == manifest["source_file_sha256"]
    assert proof["prompts"] == manifest["prompts"]
    assert proof["question_validation_thresholds"] == (
        manifest["question_validation_thresholds"]
    )


def test_semantic_fixture_and_historical_receipts_are_versioned_and_immutable() -> None:
    fixture = load_semantic_fixture()
    assert fixture["schema_version"] == "stage2-semantic-qualification-pack/1.0.0"
    assert fixture["provider_response_used_as_target"] is False
    assert fixture["classification"] == "SYNTHETIC_ONLY_NO_STUDENT_DATA"
    assert SEMANTIC_FIXTURE_PATH.is_file()
    expected_receipts = {
        "reports/openai/stage2_convergence_93da594_20260812_final_01.json": "30a422dc79a2098ff6e7066a39cb2517e959d2d1d8a169f287c68101c2dc519e",
        "reports/openai/stage2_xhigh_qualification_d41c2b3_20260812_final_01.json": "1b62c99b19781d923df9eda4082b8e73de64de2c4a4253b65d555e7d70e8db1a",
        "reports/openai/stage2_max_qualification_62d73ae_20260812_final_01.json": "532ba5e19537c039f9746c177ae3ed17cf9fbc3d6fdb9bf34c5f07f32a6eda0e",
        "reports/openai/stage2_max_qualification_62d73ae_20260812_consolidated_final_01.json": "74fc1323da3925a9805b4c957bbd597b342909f4b77855fcce706db6afbb17fd",
        "reports/openai/stage2_terra_medium_qualification_9185dba_20260813_final_01.json": "af56425a8d00fc1bbcee06c6e088f590cff68c9938c2b23190c1b5a72fdd776c",
    }
    for relative_path, expected_hash in expected_receipts.items():
        assert sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected_hash
