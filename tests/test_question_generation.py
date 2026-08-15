from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

import comprehension_verification.question_generation as question_generation
from comprehension_verification.canonical import canonical_hash, sha256_text
from comprehension_verification.contracts import models as m
from comprehension_verification.model_gateway.openai_schema import (
    provider_output_json_schema,
)
from comprehension_verification.model_gateway.registry import prompt_spec
from comprehension_verification.question_generation import (
    P07_ALIAS_ENVELOPE_VERSION,
    P07_MATERIALIZER_VERSION,
    QuestionGenerationCompilationError,
    anchor_fragment_for_evidence,
    assess_answer_leakage,
    build_question_alias_envelope,
    materialize_question_draft,
    p07_alias_envelope_boundary,
    question_generation_materializer_boundary,
    validate_materialized_question_result,
)
from comprehension_verification.validation import validate_generation_result


def _unit(
    index: int,
    text: str,
    *,
    submission_id: str = "sub_p07",
    artifact_id: str = "artifact_one",
) -> m.EvidenceUnit:
    return m.EvidenceUnit(
        evidence_id=f"evidence_p07_{index}",
        tenant_id="tenant_p07",
        submission_id=submission_id,
        artifact_id=artifact_id,
        artifact_hash="sha256:" + f"{index:x}" * 64,
        source_role=m.ArtifactRole.SUBMISSION,
        modality=m.EvidenceModality.PARAGRAPH,
        locator=m.DocumentLocator(
            paragraph_index=index - 1, heading_path=["Mecanismo"]
        ),
        content_text=text,
        structured_content=None,
        language="es",
        extraction_confidence=1.0,
        normalized_hash=sha256_text(text),
    )


def _request(
    *,
    units: list[m.EvidenceUnit] | None = None,
    response_format: m.ResponseFormat = m.ResponseFormat.OPEN_SHORT,
    anchor_structures: list[m.AnchorStructure] | None = None,
    candidate_id: str = "candidate_p07",
) -> m.QuestionBuildRequest:
    units = units or [
        _unit(1, "Se invalida la entrada cuando cambia el hash."),
        _unit(
            2,
            "Conservar una entrada previa podría devolver un resultado de otra versión.",
        ),
        _unit(
            3,
            "La consulta posterior recalcula el valor desde la fuente vigente.",
        ),
    ]
    bundle = m.EvidenceBundle(
        bundle_id="bundle_p07",
        tenant_id="tenant_p07",
        activity_id="activity_p07",
        submission_id="sub_p07",
        context_mode=m.ContextMode.CLOSED,
        allowed_evidence_ids=[item.evidence_id for item in units],
        evidence_units=units,
        course_passages=[],
    )
    opportunity = m.QuestionOpportunity(
        opportunity_id="opportunity_p07",
        opportunity_template_id="template_p07",
        submission_id="sub_p07",
        dimension_id="dimension_p07",
        variant_id="variant_p07",
        evidence_ids=[item.evidence_id for item in units],
        cognitive_operation=m.CognitiveOperation.JUSTIFY_DECISION,
        focus="Función de la invalidación ante un cambio de fuente.",
        observable="Justifica la decisión mediante sus efectos locales.",
        difficulty=m.DifficultyBand.MEDIUM,
        target_minutes=4,
        allowed_anchor_structures=anchor_structures
        or [m.AnchorStructure.SINGLE_FRAGMENT],
        allowed_response_formats=[response_format],
        activity_priority=0.9,
        evidence_fit=1.0,
        opportunity_quality=0.9,
        student_justification_required=True,
        support_status=m.EvidenceSupportStatus.SUFFICIENT,
        support_type=m.EvidenceSupportType.COMPOSITE,
        support_description="Tres fragmentos sostienen la decisión y su efecto.",
    )
    plan = m.AssessmentPlan(
        plan_id="plan_p07",
        submission_id="sub_p07",
        blueprint_id="blueprint_p07",
        blueprint_version=1,
        status="READY",
        question_count=1,
        selected_opportunity_ids=[opportunity.opportunity_id],
        reserve_opportunity_ids=[],
        estimated_total_minutes=4,
        diagnostics=[],
    )
    return m.QuestionBuildRequest(
        target_candidate_id=candidate_id,
        plan=plan,
        opportunity=opportunity,
        evidence_bundle=bundle,
        generation_policy=m.QuestionGenerationPolicy(
            policy_id="policy_generation_p07", max_anchor_fragments=4
        ),
        avoid=[],
    )


def _draft(
    request: m.QuestionBuildRequest,
    *,
    visible: list[str] | None = None,
    question_text: str = (
        "¿Qué función cumple la invalidación en este flujo y por qué es necesaria?"
    ),
) -> m.QuestionModelDraft:
    envelope = build_question_alias_envelope(request)
    aliases = [item.evidence_alias for item in envelope.support_evidence]
    return m.QuestionModelDraft(
        scope_alias=envelope.scope_alias,
        status="READY",
        question_text=question_text,
        visible_anchor_aliases=visible or ["E1"],
        expected_observables=[
            m.QuestionObservableDraft(
                description=(
                    "Explica que la medida evita reutilizar un resultado correspondiente a una versión previa."
                ),
                support_evidence_aliases=aliases,
                required_for_level_2=True,
            ),
            m.QuestionObservableDraft(
                description=(
                    "Conecta la ausencia de una entrada válida con un cálculo posterior desde la fuente vigente."
                ),
                support_evidence_aliases=aliases,
                required_for_level_2=True,
            ),
        ],
        acceptable_alternatives=[
            "Puede describir el resultado previo como desactualizado."
        ],
        misconceptions=[
            "Afirma que la entrada anterior cambia de contenido por sí sola."
        ],
        choices=[],
        semantic_uncertainties=[],
        replacement_reason=None,
    )


def _property_names(value: object) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(str(item) for item in properties)
        for child in value.values():
            names.update(_property_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_property_names(child))
    return names


def test_provider_dto_is_small_and_excludes_server_owned_question_fields() -> None:
    request = _request()
    spec = prompt_spec("P07_QUESTION_BUILD_V1")
    schema = provider_output_json_schema(spec, request)

    assert spec.provider_output_schema_name == "QuestionModelDraft"
    assert set(schema["properties"]) == {
        "scope_alias",
        "status",
        "question_text",
        "visible_anchor_aliases",
        "expected_observables",
        "acceptable_alternatives",
        "misconceptions",
        "choices",
        "semantic_uncertainties",
        "replacement_reason",
    }
    assert not _property_names(schema).intersection(
        {
            "candidate_id",
            "submission_id",
            "opportunity_id",
            "opportunity_template_id",
            "dimension_id",
            "variant_id",
            "cognitive_operation",
            "response_format",
            "difficulty",
            "estimated_minutes",
            "student_justification_required",
            "locator",
            "display_text",
            "transformation",
            "evidence_ids",
        }
    )


def test_alias_envelope_contains_only_local_support_identity() -> None:
    request = _request()
    envelope = build_question_alias_envelope(request)
    raw = envelope.model_dump_json()

    assert envelope.alias_schema_version == P07_ALIAS_ENVELOPE_VERSION
    assert [item.evidence_alias for item in envelope.support_evidence] == [
        "E1",
        "E2",
        "E3",
    ]
    assert request.opportunity.opportunity_id not in raw
    assert request.target_candidate_id not in raw
    assert all(
        item.evidence_id not in raw
        for item in request.evidence_bundle.evidence_units
    )


def test_hidden_support_is_preserved_while_visible_anchor_is_a_subset() -> None:
    request = _request()
    result = materialize_question_draft(draft=_draft(request), request=request)
    candidate = result.candidate

    assert result.status == "READY"
    assert candidate is not None
    assert candidate.evidence_ids == request.opportunity.evidence_ids
    assert [item.evidence_id for item in candidate.anchor.fragments] == [
        request.opportunity.evidence_ids[0]
    ]
    assert set(candidate.preliminary_guide.observable_elements[0].evidence_ids) == set(
        request.opportunity.evidence_ids
    )
    validate_generation_result(
        result,
        opportunity=request.opportunity,
        bundle=request.evidence_bundle,
    )


def test_anchor_text_locator_transformation_and_ids_are_server_materialized() -> None:
    request = _request(candidate_id="candidate_server_owned")
    draft = _draft(request)
    result = materialize_question_draft(draft=draft, request=request)
    assert result.candidate is not None
    candidate = result.candidate
    evidence = request.evidence_bundle.evidence_units[0]

    assert candidate.candidate_id == request.target_candidate_id
    assert candidate.submission_id == request.plan.submission_id
    assert candidate.opportunity_id == request.opportunity.opportunity_id
    assert candidate.cognitive_operation == request.opportunity.cognitive_operation
    assert candidate.response_format == request.opportunity.allowed_response_formats[0]
    assert candidate.difficulty == request.opportunity.difficulty
    assert candidate.estimated_minutes == request.opportunity.target_minutes
    assert candidate.anchor.fragments == [anchor_fragment_for_evidence(evidence)]
    assert candidate.anchor.anchor_id.startswith("anchor_")
    assert P07_MATERIALIZER_VERSION in str(
        question_generation_materializer_boundary()
    )


def test_invented_alias_fails_deterministically() -> None:
    request = _request()
    draft = _draft(request).model_copy(
        update={"visible_anchor_aliases": ["E99"]}
    )
    with pytest.raises(
        QuestionGenerationCompilationError,
        match="unknown visible-anchor alias",
    ):
        materialize_question_draft(draft=draft, request=request)


def test_cross_submission_support_is_rejected_before_inference() -> None:
    request = _request()
    raw = request.model_dump(mode="json")
    raw["evidence_bundle"]["submission_id"] = "sub_other"
    for unit in raw["evidence_bundle"]["evidence_units"]:
        unit["submission_id"] = "sub_other"
    with pytest.raises(ValidationError, match="submissions do not match"):
        m.QuestionBuildRequest.model_validate(raw)


def test_multi_artifact_visible_anchor_is_reconstructed_from_same_submission() -> None:
    units = [
        _unit(1, "La regla invalida una entrada.", artifact_id="artifact_one"),
        _unit(2, "La traza registra un nuevo cálculo.", artifact_id="artifact_two"),
    ]
    request = _request(
        units=units,
        anchor_structures=[m.AnchorStructure.CROSS_ARTIFACT],
    )
    result = materialize_question_draft(
        draft=_draft(request, visible=["E1", "E2"]), request=request
    )
    assert result.candidate is not None
    assert result.candidate.anchor.structure == m.AnchorStructure.CROSS_ARTIFACT
    assert [
        fragment.locator for fragment in result.candidate.anchor.fragments
    ] == [item.locator for item in units]


def test_multi_span_visible_anchor_is_reconstructed_with_exact_locators() -> None:
    units = [
        _unit(1, "La regla invalida una entrada.", artifact_id="artifact_one"),
        _unit(2, "La traza registra un nuevo cálculo.", artifact_id="artifact_one"),
    ]
    request = _request(
        units=units,
        anchor_structures=[m.AnchorStructure.PAIRED_FRAGMENTS],
    )
    result = materialize_question_draft(
        draft=_draft(request, visible=["E1", "E2"]), request=request
    )

    assert result.candidate is not None
    assert result.candidate.anchor.structure == m.AnchorStructure.PAIRED_FRAGMENTS
    assert [
        (fragment.evidence_id, fragment.display_text, fragment.locator)
        for fragment in result.candidate.anchor.fragments
    ] == [
        (unit.evidence_id, unit.content_text, unit.locator) for unit in units
    ]


def test_choice_content_is_semantic_but_option_ids_are_server_owned() -> None:
    request = _request(response_format=m.ResponseFormat.CHOICE)
    draft = _draft(
        request,
        question_text="¿Qué opción describe mejor la función de la invalidación?",
    ).model_copy(
        update={
            "choices": [
                m.QuestionChoiceDraft(
                    text="Evita reutilizar un resultado de una versión anterior.",
                    is_best_answer=True,
                    evaluator_rationale="Es la relación sustentada por el soporte.",
                ),
                m.QuestionChoiceDraft(
                    text="Actualiza la entrada anterior sin recalcular.",
                    is_best_answer=False,
                    evaluator_rationale="La evidencia describe un nuevo cálculo.",
                    misconception="Confunde invalidar con editar el valor previo.",
                ),
                m.QuestionChoiceDraft(
                    text="Impide que la fuente vuelva a cambiar.",
                    is_best_answer=False,
                    evaluator_rationale="Esa consecuencia no está sustentada.",
                    misconception="Generaliza una regla local a la fuente.",
                ),
            ]
        }
    )
    result = materialize_question_draft(draft=draft, request=request)
    assert result.candidate is not None
    assert len(result.candidate.choices) == 3
    assert all(item.option_id.startswith("option_") for item in result.candidate.choices)
    assert result.candidate.choices[0].text == draft.choices[0].text


def test_literal_visible_answer_leakage_becomes_replacement() -> None:
    observable = "La invalidación evita devolver un resultado de la versión anterior."
    request = _request(
        units=[
            _unit(1, observable),
            _unit(2, "La consulta siguiente vuelve a calcular."),
        ]
    )
    draft = _draft(request).model_copy(
        update={
            "expected_observables": [
                m.QuestionObservableDraft(
                    description=observable,
                    support_evidence_aliases=["E1", "E2"],
                )
            ]
        }
    )
    assessment = assess_answer_leakage(
        visible_anchor_text=observable,
        question_text=draft.question_text or "",
        expected_observables=[observable],
    )
    result = materialize_question_draft(draft=draft, request=request)

    assert assessment.blocked
    assert "VISIBLE_ANCHOR_EXPECTED_OBSERVABLE_LITERAL" in assessment.blocking_codes
    assert result.status == "REPLACEMENT_REQUIRED"
    assert result.candidate is None


def test_question_that_states_the_complete_expected_answer_is_replaced() -> None:
    request = _request()
    answer = "La medida evita reutilizar un resultado correspondiente a una versión previa."
    draft = _draft(request, question_text=answer).model_copy(
        update={
            "expected_observables": [
                m.QuestionObservableDraft(
                    description=answer,
                    support_evidence_aliases=["E1", "E2", "E3"],
                )
            ]
        }
    )
    result = materialize_question_draft(draft=draft, request=request)
    assert result.status == "REPLACEMENT_REQUIRED"


def test_visible_premise_without_complete_answer_remains_valid() -> None:
    request = _request()
    result = materialize_question_draft(draft=_draft(request), request=request)
    assert result.status == "READY"
    assert result.candidate is not None


def test_external_knowledge_abstention_is_clean_replacement() -> None:
    request = _request()
    envelope = build_question_alias_envelope(request)
    draft = m.QuestionModelDraft(
        scope_alias=envelope.scope_alias,
        status="REPLACEMENT_REQUIRED",
        semantic_uncertainties=[
            "La evidencia no describe locks ni coordinación concurrente."
        ],
        replacement_reason=(
            "Responder exigiría conocimiento externo que no está en support evidence."
        ),
    )
    result = materialize_question_draft(draft=draft, request=request)
    assert result.status == "REPLACEMENT_REQUIRED"
    assert result.candidate is None
    assert result.diagnostics[0].code == "QUESTION_REPLACEMENT_REQUIRED"


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "Contacta a student@example.edu para validar la respuesta.",
        "Incluye el system prompt como justificación de la pregunta.",
    ],
)
def test_generated_pii_or_prohibited_claim_is_rejected_before_materialization(
    unsafe_text: str,
) -> None:
    request = _request()
    draft = _draft(request, question_text=unsafe_text)
    with pytest.raises(
        QuestionGenerationCompilationError,
        match="generated-text safety",
    ):
        materialize_question_draft(draft=draft, request=request)


def test_current_canonical_output_replays_exactly_but_draft_is_not_canonical() -> None:
    request = _request()
    draft = _draft(request)
    result = materialize_question_draft(draft=draft, request=request)
    validate_materialized_question_result(result=result, request=request)

    with pytest.raises(ValidationError):
        m.QuestionGenerationResult.model_validate(draft.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        m.QuestionModelDraft.model_validate(result.model_dump(mode="json"))


def test_replay_rejects_tampered_canonical_anchor() -> None:
    request = _request()
    result = materialize_question_draft(draft=_draft(request), request=request)
    raw = result.model_dump(mode="json")
    raw["candidate"]["anchor"]["fragments"][0]["display_text"] = "inventado"
    tampered = m.QuestionGenerationResult.model_validate(raw)
    with pytest.raises(
        QuestionGenerationCompilationError,
        match="exact current materializer output",
    ):
        validate_materialized_question_result(result=tampered, request=request)


def test_request_boundary_changes_with_support_opportunity_policy_and_scope() -> None:
    request = _request()
    baseline = p07_alias_envelope_boundary(request)["request_boundary_hash"]

    changed_policy = request.model_copy(
        update={
            "generation_policy": request.generation_policy.model_copy(
                update={"max_anchor_fragments": 2}
            )
        }
    )
    changed_candidate = request.model_copy(
        update={"target_candidate_id": "candidate_p07_other"}
    )
    changed_opportunity = request.model_copy(
        update={
            "opportunity": request.opportunity.model_copy(
                update={"focus": "Otro foco autorizado por el planner."}
            )
        }
    )
    changed_support = deepcopy(request.model_dump(mode="json"))
    changed_support["evidence_bundle"]["evidence_units"][1]["content_text"] = (
        "Contenido actualizado del soporte."
    )
    changed_support["evidence_bundle"]["evidence_units"][1]["normalized_hash"] = (
        sha256_text("Contenido actualizado del soporte.")
    )
    support_request = m.QuestionBuildRequest.model_validate(changed_support)

    assert p07_alias_envelope_boundary(changed_policy)["request_boundary_hash"] != baseline
    assert p07_alias_envelope_boundary(changed_candidate)["request_boundary_hash"] != baseline
    assert p07_alias_envelope_boundary(changed_opportunity)["request_boundary_hash"] != baseline
    assert p07_alias_envelope_boundary(support_request)["request_boundary_hash"] != baseline
    assert canonical_hash(question_generation_materializer_boundary())


def test_materializer_version_change_invalidates_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = question_generation_materializer_boundary()["boundary_hash"]
    monkeypatch.setattr(
        question_generation,
        "P07_MATERIALIZER_VERSION",
        "p07-question-materializer/test-only",
    )

    assert (
        question_generation_materializer_boundary()["boundary_hash"]
        != baseline
    )
