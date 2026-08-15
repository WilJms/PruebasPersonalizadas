from __future__ import annotations

import asyncio
from copy import deepcopy

from pydantic import ValidationError
import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.blueprint_compiler import (
    BlueprintCompilationError,
    blueprint_compiler_boundary,
    compile_and_preflight_blueprint,
    compile_blueprint_model_draft,
    preflight_compiled_blueprint,
)
from comprehension_verification.contracts import SCHEMA_VERSION, models as m
import comprehension_verification.model_gateway.gateway as gateway_module
from comprehension_verification.model_gateway import (
    DeterministicMockFactory,
    GatewayContextError,
    GatewaySchemaViolation,
    MockBehavior,
    ModelGateway,
    build_mock_request,
    build_trusted_context,
)
from comprehension_verification.model_gateway.registry import (
    prompt_spec,
    provider_output_schema_boundary,
)
from comprehension_verification.model_gateway.openai_schema import (
    structured_output_format,
)
from comprehension_verification.validation import build_blueprint_review_preflight
from comprehension_verification.web.repository import Repository


PROMPT_ID = "P04_BLUEPRINT_BUILD_V1"


def _request() -> m.BlueprintBuildRequest:
    return build_mock_request(PROMPT_ID)


def _draft(request: m.BlueprintBuildRequest | None = None) -> m.BlueprintModelDraft:
    effective_request = request or _request()
    output = DeterministicMockFactory().output_for(
        PROMPT_ID, effective_request, MockBehavior.HAPPY
    )
    assert isinstance(output, m.BlueprintModelDraft)
    return output


def _compile(
    request: m.BlueprintBuildRequest | None = None,
    draft: m.BlueprintModelDraft | None = None,
) -> m.AssessmentBlueprint:
    effective_request = request or _request()
    return compile_blueprint_model_draft(
        draft=draft or _draft(effective_request),
        request=effective_request,
    )


def _draft_with_catalog_size(
    *,
    request: m.BlueprintBuildRequest,
    variants_per_dimension: int,
    templates_per_variant: int,
) -> m.BlueprintModelDraft:
    source = _draft(request)
    source_variant = source.evidence_variants[0]
    source_templates = source.question_opportunities
    variants: list[m.EvidenceVariantDraft] = []
    templates: list[m.QuestionOpportunityTemplateDraft] = []
    template_index = 0
    for variant_index in range(1, variants_per_dimension + 1):
        variant_alias = f"V{variant_index}"
        variants.append(
            source_variant.model_copy(
                update={
                    "variant_alias": variant_alias,
                    "name": f"Modalidad de evidencia {variant_index}",
                    "description": (
                        f"Evidencia semántica diferenciada para la modalidad "
                        f"{variant_index}."
                    ),
                },
                deep=True,
            )
        )
        for local_index in range(1, templates_per_variant + 1):
            template_index += 1
            source_template = source_templates[
                (local_index - 1) % len(source_templates)
            ]
            templates.append(
                source_template.model_copy(
                    update={
                        "template_alias": f"T{template_index}",
                        "variant_alias": variant_alias,
                        "focus": (
                            f"Foco verificable {variant_index}.{local_index}"
                        ),
                        "observable": (
                            f"Observable verificable {variant_index}.{local_index}"
                        ),
                    },
                    deep=True,
                )
            )
    return source.model_copy(
        update={
            "evidence_variants": variants,
            "question_opportunities": templates,
        },
        deep=True,
    )


def test_compiler_resolves_local_aliases_to_server_owned_canonical_ids() -> None:
    request = _request()
    draft = _draft(request)
    blueprint = _compile(request, draft)

    dimension_ids = [item.dimension_id for item in blueprint.dimensions]
    variant_ids = [
        item.variant_id
        for dimension in blueprint.dimensions
        for item in dimension.evidence_variants
    ]
    template_ids = [
        item.opportunity_template_id
        for dimension in blueprint.dimensions
        for variant in dimension.evidence_variants
        for item in variant.question_opportunities
    ]
    assert all(item.startswith("dimension_") for item in dimension_ids)
    assert all(item.startswith("variant_") for item in variant_ids)
    assert all(item.startswith("oppt_") for item in template_ids)
    assert not ({item.dimension_alias for item in draft.dimensions} & set(dimension_ids))
    assert not ({item.variant_alias for item in draft.evidence_variants} & set(variant_ids))
    assert not (
        {item.template_alias for item in draft.question_opportunities}
        & set(template_ids)
    )


def test_compiler_rejects_an_invented_alias_reference() -> None:
    request = _request()
    draft = _draft(request)
    forged_variant = draft.evidence_variants[0].model_copy(
        update={"dimension_alias": "D999"}
    )
    forged = draft.model_copy(
        update={
            "evidence_variants": [
                forged_variant,
                *draft.evidence_variants[1:],
            ]
        }
    )

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(request, forged)

    assert captured.value.code == "BLUEPRINT_ALIAS_REFERENCE_UNKNOWN"


def test_provider_draft_cannot_fabricate_canonical_identity_fields() -> None:
    raw = _draft().model_dump(mode="json")
    raw["blueprint_id"] = "blueprint_forged"
    raw["dimensions"][0]["dimension_id"] = "dimension_forged"

    with pytest.raises(ValidationError) as captured:
        m.BlueprintModelDraft.model_validate(raw)

    forbidden_locations = {tuple(item["loc"]) for item in captured.value.errors()}
    assert ("blueprint_id",) in forbidden_locations
    assert ("dimensions", 0, "dimension_id") in forbidden_locations
    schema_text = str(m.BlueprintModelDraft.model_json_schema(mode="validation"))
    for forbidden in (
        "schema_version",
        "blueprint_id",
        "blueprint_version",
        "activity_id",
        "tenant_id",
        "context_mode",
        "status",
        "question_count",
        "target_total_minutes",
        "assessment_constraints",
        "decision_ids",
        "diagnostics",
        "approved_by",
        "approved_at",
        "opportunity_template_id",
        "minimum_quality",
        "max_reserve_opportunities",
        "priority_criterion_ids",
        "required_criterion_ids",
        "structured_justification_policy",
        "created_at",
        "updated_at",
        "timestamp",
        "sha256",
        "lineage",
        "owner_id",
    ):
        assert forbidden not in schema_text


def test_policy_and_workflow_fields_are_materialized_only_by_server() -> None:
    request = _request()
    policy = request.blueprint_policy.model_copy(
        update={
            "context_mode": m.ContextMode.COURSE_ENRICHED,
            "target_total_minutes": 17,
            "allowed_response_formats": [
                m.ResponseFormat.OPEN_SHORT,
                m.ResponseFormat.STRUCTURED_BULLETS,
            ],
            "planning_policy": request.blueprint_policy.planning_policy.model_copy(
                update={"minimum_opportunity_quality": 0.83}
            ),
        }
    )
    request = request.model_copy(update={"blueprint_policy": policy})
    draft = _draft(request)
    blueprint = _compile(request, draft)

    assert blueprint.blueprint_id == request.target_blueprint_id
    assert blueprint.blueprint_version == request.target_blueprint_version
    assert blueprint.activity_id == request.activity_spec.activity_id
    assert blueprint.context_mode == policy.context_mode
    assert blueprint.status == m.WorkflowStatus.READY
    assert blueprint.decision_ids == [
        item.decision_id for item in request.resolved_decisions
    ]
    assert blueprint.approved_by is None
    assert blueprint.approved_at is None
    assert blueprint.assessment_constraints.question_count == policy.question_count
    assert (
        blueprint.assessment_constraints.target_total_minutes
        == policy.target_total_minutes
    )
    assert (
        blueprint.assessment_constraints.allowed_response_formats
        == policy.allowed_response_formats
    )
    assert blueprint.assessment_constraints.minimum_opportunity_quality == 0.83


def test_compiler_is_deterministic_and_alias_spelling_does_not_define_identity() -> None:
    request = _request()
    draft = _draft(request)
    first = _compile(request, draft)
    second = _compile(request, draft.model_copy(deep=True))
    assert first == second

    variant_aliases = {
        item.variant_alias: f"V{index + 20}"
        for index, item in enumerate(draft.evidence_variants)
    }
    renamed = draft.model_copy(
        update={
            "dimensions": [
                draft.dimensions[0].model_copy(update={"dimension_alias": "D9"})
            ],
            "evidence_variants": [
                item.model_copy(
                    update={
                        "variant_alias": f"V{index + 20}",
                        "dimension_alias": "D9",
                    }
                )
                for index, item in enumerate(draft.evidence_variants)
            ],
            "question_opportunities": [
                item.model_copy(
                    update={
                        "template_alias": f"T{index + 100}",
                        "variant_alias": variant_aliases[item.variant_alias],
                    }
                )
                for index, item in enumerate(draft.question_opportunities)
            ],
        }
    )
    assert _compile(request, renamed) == first


def test_p04_draft_remains_semantically_rich_after_compilation() -> None:
    draft = _draft()
    blueprint = _compile(draft=draft)
    assert len(blueprint.dimensions) == len(draft.dimensions)
    for draft_dimension, dimension in zip(
        draft.dimensions,
        blueprint.dimensions,
        strict=True,
    ):
        assert dimension.name == draft_dimension.name
        assert dimension.criterion_ids == draft_dimension.criterion_ids
        assert dimension.learning_outcome_ids == draft_dimension.learning_outcome_ids
        assert dimension.grading_weight == draft_dimension.grading_weight
        assert dimension.verification_priority == draft_dimension.verification_priority
        assert dimension.factors == draft_dimension.factors
        assert dimension.justification == draft_dimension.justification
        draft_variants = [
            item
            for item in draft.evidence_variants
            if item.dimension_alias == draft_dimension.dimension_alias
        ]
        assert len(dimension.evidence_variants) == len(draft_variants)
        for draft_variant, variant in zip(
            draft_variants,
            dimension.evidence_variants,
            strict=True,
        ):
            assert variant.name == draft_variant.name
            assert variant.description == draft_variant.description
            assert variant.evidence_requirement == draft_variant.evidence_requirement
            assert variant.verification_potential == (
                draft_variant.verification_potential
            )
            assert variant.supported_operations == draft_variant.supported_operations
            draft_templates = [
                item
                for item in draft.question_opportunities
                if item.variant_alias == draft_variant.variant_alias
            ]
            assert len(variant.question_opportunities) == len(draft_templates)
            for draft_template, template in zip(
                draft_templates,
                variant.question_opportunities,
                strict=True,
            ):
                assert template.cognitive_operation == (
                    draft_template.cognitive_operation
                )
                assert template.focus == draft_template.focus
                assert template.observable == draft_template.observable
                assert template.difficulty == draft_template.difficulty
                assert template.target_minutes == draft_template.target_minutes
                assert template.allowed_anchor_structures == (
                    draft_template.allowed_anchor_structures
                )
                assert template.allowed_response_formats == (
                    draft_template.allowed_response_formats
                )
                assert template.verification_potential == (
                    draft_template.verification_potential
                )


def test_compiler_preserves_academic_choices_instead_of_repairing_for_convenience() -> None:
    request = _request()
    draft = _draft(request)
    semantic_template = draft.question_opportunities[0].model_copy(
        update={
            "focus": "Foco académico deliberadamente específico",
            "observable": "Observable académico deliberadamente específico",
            "difficulty": m.DifficultyBand.HIGH,
            "target_minutes": 11,
        }
    )
    revised = draft.model_copy(
        update={
            "question_opportunities": [
                semantic_template,
                *draft.question_opportunities[1:],
            ]
        },
        deep=True,
    )

    compiled = _compile(request, revised)
    result = compiled.dimensions[0].evidence_variants[0].question_opportunities[0]
    assert result.focus == semantic_template.focus
    assert result.observable == semantic_template.observable
    assert result.difficulty == m.DifficultyBand.HIGH
    assert result.target_minutes == 11


def test_missing_academic_coverage_is_diagnosed_not_completed_by_compiler() -> None:
    request = _request()
    assert request.rubric_spec is not None
    second_criterion = request.rubric_spec.criteria[0].model_copy(
        update={
            "criterion_id": "criterion_2",
            "name": "Segundo criterio verificable",
        },
        deep=True,
    )
    expanded_rubric = request.rubric_spec.model_copy(
        update={
            "criteria": [
                *request.rubric_spec.criteria,
                second_criterion,
            ]
        },
        deep=True,
    )
    expanded_request = request.model_copy(update={"rubric_spec": expanded_rubric})
    draft = _draft(request)
    before = draft.model_dump(mode="json")

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(expanded_request, draft)

    assert captured.value.code == "BLUEPRINT_SOURCE_COVERAGE_INCOMPLETE"
    assert draft.model_dump(mode="json") == before
    assert "criterion_2" not in {
        criterion_id
        for dimension in draft.dimensions
        for criterion_id in dimension.criterion_ids
    }


def test_missing_focus_or_observable_fails_provider_contract_without_invention() -> None:
    for field in ("focus", "observable"):
        raw = _draft().model_dump(mode="json")
        raw["question_opportunities"][0].pop(field)
        with pytest.raises(ValidationError):
            m.BlueprintModelDraft.model_validate(raw)


def test_deterministic_preflight_discovers_infeasibility_after_compilation() -> None:
    request = _request()
    draft = _draft(request).model_copy(
        update={
            "question_opportunities": [
                item.model_copy(update={"target_minutes": 60})
                for item in _draft(request).question_opportunities
            ]
        }
    )
    compiled = _compile(request, draft)
    assert compiled.status == m.WorkflowStatus.READY

    checked = preflight_compiled_blueprint(blueprint=compiled, request=request)

    assert checked.status == m.WorkflowStatus.NEEDS_REVIEW
    assert [item.code for item in checked.diagnostics] == [
        "P04_CATALOG_TIME_INFEASIBLE"
    ]
    assert checked.diagnostics[0].details["correction_scope"] == PROMPT_ID.removesuffix(
        "_V1"
    )
    assert checked.diagnostics[0].details["question_count"] == (
        request.blueprint_policy.question_count
    )
    assert checked.diagnostics[0].details["target_total_minutes"] == (
        request.blueprint_policy.target_total_minutes
    )
    assert checked.diagnostics[0].details["catalog_plan_feasible"] is False
    assert checked.diagnostics[0].details["diagnostic_source"] == (
        "DETERMINISTIC_BLUEPRINT_PREFLIGHT"
    )
    assert set(checked.diagnostics[0].details) == {
        "catalog_size_sufficient",
        "catalog_plan_feasible",
        "time_feasible",
        "format_feasible",
        "justification_matrix_valid",
        "source_coverage_complete",
        "question_count",
        "target_total_minutes",
        "required_criterion_ids",
        "max_variants_per_dimension",
        "max_templates_per_variant",
        "diagnostic_source",
        "correction_scope",
    }
    provider_schema_text = str(
        m.BlueprintModelDraft.model_json_schema(mode="validation")
    )
    for planner_owned_field in (
        "question_count",
        "target_total_minutes",
        "catalog_plan_feasible",
        "selected_opportunity_ids",
        "reserve_opportunity_ids",
        "planner_version",
    ):
        assert planner_owned_field not in provider_schema_text


def test_regeneration_is_idempotent_per_version_and_rekeys_a_new_version() -> None:
    request = _request()
    draft = _draft(request)
    first = compile_and_preflight_blueprint(draft=draft, request=request)
    replay = compile_and_preflight_blueprint(draft=draft, request=request)
    assert replay == first

    next_request = request.model_copy(update={"target_blueprint_version": 2})
    regenerated = compile_and_preflight_blueprint(
        draft=draft,
        request=next_request,
    )
    assert regenerated.blueprint_id == first.blueprint_id
    assert regenerated.blueprint_version == 2
    assert regenerated.dimensions[0].dimension_id != first.dimensions[0].dimension_id
    assert regenerated.dimensions[0].name == first.dimensions[0].name


def test_compiled_p04_output_remains_usable_by_legacy_p05_until_phase3() -> None:
    gateway = ModelGateway()
    p04_request = _request()
    blueprint = asyncio.run(
        gateway.invoke(
            PROMPT_ID,
            p04_request,
            build_trusted_context(p04_request),
        )
    ).output
    assert isinstance(blueprint, m.AssessmentBlueprint)
    p05_request = build_mock_request("P05_BLUEPRINT_REVIEW_V1")
    p05_request = p05_request.model_copy(
        update={
            "blueprint": blueprint,
            "deterministic_preflight": build_blueprint_review_preflight(
                blueprint=blueprint,
                activity_spec=p05_request.activity_spec,
                rubric_spec=p05_request.rubric_spec,
                blueprint_policy=p05_request.blueprint_policy,
            ),
        },
        deep=True,
    )

    review = asyncio.run(
        gateway.invoke(
            "P05_BLUEPRINT_REVIEW_V1",
            p05_request,
            build_trusted_context(p05_request),
        )
    ).output

    assert isinstance(review, m.BlueprintReview)
    assert review.status == m.WorkflowStatus.READY
    assert review.blueprint_id == blueprint.blueprint_id
    assert review.blueprint_version == blueprint.blueprint_version


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (
            lambda draft: draft.model_copy(
                update={
                    "question_opportunities": [
                        draft.question_opportunities[0].model_copy(
                            update={
                                "cognitive_operation": m.CognitiveOperation.TRACE_FLOW
                            }
                        ),
                        *draft.question_opportunities[1:],
                    ]
                }
            ),
            "BLUEPRINT_UNSUPPORTED_OPERATION",
        ),
        (
            lambda draft: draft.model_copy(
                update={
                    "question_opportunities": [
                        draft.question_opportunities[0].model_copy(
                            update={
                                "allowed_response_formats": [m.ResponseFormat.CHOICE]
                            }
                        ),
                        *draft.question_opportunities[1:],
                    ]
                }
            ),
            "BLUEPRINT_FORMAT_NOT_ALLOWED",
        ),
        (
            lambda draft: draft.model_copy(
                update={
                    "question_opportunities": [
                        draft.question_opportunities[0],
                        draft.question_opportunities[0].model_copy(
                            update={"template_alias": "T999"}
                        ),
                        *draft.question_opportunities[1:],
                    ]
                }
            ),
            "BLUEPRINT_SEMANTIC_DUPLICATE",
        ),
    ),
)
def test_compiler_rejects_deterministic_catalog_violations(mutation, code: str) -> None:  # type: ignore[no-untyped-def]
    request = _request()
    mutated = mutation(_draft(request))
    before = mutated.model_dump(mode="json")
    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(request, mutated)
    assert captured.value.code == code
    assert mutated.model_dump(mode="json") == before


@pytest.mark.parametrize(
    ("field", "forged_id"),
    (
        ("criterion_ids", "criterion_forged"),
        ("learning_outcome_ids", "outcome_forged"),
    ),
)
def test_compiler_rejects_academic_references_outside_the_allowlist(
    field: str,
    forged_id: str,
) -> None:
    request = _request()
    draft = _draft(request)
    forged_dimension = draft.dimensions[0].model_copy(
        update={field: [forged_id]}
    )

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(
            request,
            draft.model_copy(update={"dimensions": [forged_dimension]}),
        )

    assert captured.value.code == "BLUEPRINT_REFERENCE_NOT_ALLOWLISTED"


def test_compiler_enforces_server_owned_catalog_limits() -> None:
    request = _request()
    draft = _draft(request)
    assert len(draft.question_opportunities) > 1
    limited_policy = request.blueprint_policy.model_copy(
        update={"max_templates_per_variant": 1}
    )

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(
            request.model_copy(update={"blueprint_policy": limited_policy}),
            draft,
        )

    assert captured.value.code == "BLUEPRINT_POLICY_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    ("variants_per_dimension", "templates_per_variant"),
    (
        (5, 11),  # one below both operational defaults
        (6, 12),  # exactly at both operational defaults
    ),
)
def test_operational_catalog_caps_accept_below_and_exactly_at_default(
    variants_per_dimension: int,
    templates_per_variant: int,
) -> None:
    request = _request()
    assert request.blueprint_policy.max_variants_per_dimension == 6
    assert request.blueprint_policy.max_templates_per_variant == 12
    draft = _draft_with_catalog_size(
        request=request,
        variants_per_dimension=variants_per_dimension,
        templates_per_variant=templates_per_variant,
    )

    compiled = _compile(request, draft)

    assert len(compiled.dimensions[0].evidence_variants) == variants_per_dimension
    assert all(
        len(variant.question_opportunities) == templates_per_variant
        for variant in compiled.dimensions[0].evidence_variants
    )


@pytest.mark.parametrize(
    ("variants_per_dimension", "templates_per_variant"),
    (
        (7, 1),
        (1, 13),
    ),
)
def test_operational_catalog_caps_reject_above_default(
    variants_per_dimension: int,
    templates_per_variant: int,
) -> None:
    request = _request()
    draft = _draft_with_catalog_size(
        request=request,
        variants_per_dimension=variants_per_dimension,
        templates_per_variant=templates_per_variant,
    )

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(request, draft)

    assert captured.value.code == "BLUEPRINT_POLICY_LIMIT_EXCEEDED"


def test_catalog_caps_are_configurable_versioned_server_policy() -> None:
    request = _request()
    historical_policy = request.blueprint_policy.model_dump(mode="json")
    historical_policy.pop("max_variants_per_dimension")
    historical_policy.pop("max_templates_per_variant")
    defaulted = m.BlueprintPolicy.model_validate(historical_policy)
    assert defaulted.max_variants_per_dimension == 6
    assert defaulted.max_templates_per_variant == 12

    custom_policy = request.blueprint_policy.model_copy(
        update={
            "policy_id": "blueprint_policy_custom_caps",
            "max_variants_per_dimension": 2,
            "max_templates_per_variant": 3,
        }
    )
    custom_request = request.model_copy(update={"blueprint_policy": custom_policy})
    exact_custom_draft = _draft_with_catalog_size(
        request=custom_request,
        variants_per_dimension=2,
        templates_per_variant=3,
    )
    assert _compile(custom_request, exact_custom_draft)
    assert custom_policy.schema_version == SCHEMA_VERSION

    tighter_policy = custom_policy.model_copy(
        update={
            "policy_id": "blueprint_policy_tighter_caps",
            "max_variants_per_dimension": 1,
            "max_templates_per_variant": 2,
        }
    )
    tighter_request = request.model_copy(update={"blueprint_policy": tighter_policy})
    assert canonical_hash(custom_policy.model_dump(mode="json")) != canonical_hash(
        tighter_policy.model_dump(mode="json")
    )
    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(tighter_request, exact_custom_draft)
    assert captured.value.code == "BLUEPRINT_POLICY_LIMIT_EXCEEDED"

    provider_properties = str(
        m.BlueprintModelDraft.model_json_schema(mode="validation")
    )
    assert "max_variants_per_dimension" not in provider_properties
    assert "max_templates_per_variant" not in provider_properties


def test_compiler_rejects_course_sources_outside_closed_context() -> None:
    request = _request()
    draft = _draft(request)
    first_variant = draft.evidence_variants[0]
    widened_requirement = first_variant.evidence_requirement.model_copy(
        update={"course_sources_allowed": True}
    )
    widened_variant = first_variant.model_copy(
        update={"evidence_requirement": widened_requirement}
    )
    widened = draft.model_copy(
        update={
            "evidence_variants": [
                widened_variant,
                *draft.evidence_variants[1:],
            ]
        }
    )

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(request, widened)

    assert captured.value.code == "BLUEPRINT_REFERENCE_NOT_ALLOWLISTED"


def test_compiler_rejects_a_variant_without_any_opportunity() -> None:
    request = _request()
    draft = _draft(request)
    impossible = draft.model_copy(update={"question_opportunities": []})

    with pytest.raises(BlueprintCompilationError) as captured:
        _compile(request, impossible)

    assert captured.value.code == "BLUEPRINT_STRUCTURE_IMPOSSIBLE"


def test_historical_assessment_blueprint_shape_remains_backward_compatible() -> None:
    request = _request()
    context = build_trusted_context(request)
    gateway = ModelGateway()
    fresh = asyncio.run(gateway.invoke(PROMPT_ID, request, context)).output
    historical_payload = fresh.model_dump(mode="json")

    assert m.AssessmentBlueprint.model_validate(historical_payload) == fresh
    assert (
        gateway.validate_cached_output(
            PROMPT_ID,
            request,
            context,
            historical_payload,
        )
        == fresh
    )


def test_historical_provider_assessment_blueprint_cannot_be_read_as_current_draft() -> None:
    request = _request()
    historical_provider_payload = _compile(request).model_dump(mode="json")
    gateway = ModelGateway()

    with pytest.raises(GatewaySchemaViolation):
        gateway._validate_output(  # noqa: SLF001 - exercises the provider boundary
            prompt_spec(PROMPT_ID),
            historical_provider_payload,
        )

    assert m.AssessmentBlueprint.model_validate(historical_provider_payload)
    with pytest.raises(ValidationError):
        m.BlueprintModelDraft.model_validate(historical_provider_payload)


def test_provider_draft_and_canonical_stage_cache_cannot_poison_each_other() -> None:
    request = _request()
    context = build_trusted_context(request)
    draft_payload = _draft(request).model_dump(mode="json")
    canonical_payload = _compile(request).model_dump(mode="json")
    gateway = ModelGateway()

    with pytest.raises(GatewaySchemaViolation):
        gateway.validate_cached_output(
            PROMPT_ID,
            request,
            context,
            draft_payload,
        )
    with pytest.raises(GatewaySchemaViolation):
        gateway._validate_output(  # noqa: SLF001 - exercises the provider boundary
            prompt_spec(PROMPT_ID),
            canonical_payload,
        )
    assert gateway.validate_cached_output(
        PROMPT_ID,
        request,
        context,
        canonical_payload,
    ) == m.AssessmentBlueprint.model_validate(canonical_payload)


@pytest.mark.parametrize(
    "poison",
    (
        lambda payload: payload["dimensions"][0].update(
            {"dimension_id": "dimension_cache_poison"}
        ),
        lambda payload: payload["dimensions"][0].update(
            {"criterion_ids": ["criterion_cache_poison"]}
        ),
    ),
)
def test_canonical_cache_replay_rejects_identity_or_reference_poisoning(poison) -> None:  # type: ignore[no-untyped-def]
    request = _request()
    context = build_trusted_context(request)
    payload = _compile(request).model_dump(mode="json")
    poison(payload)

    with pytest.raises(GatewayContextError):
        ModelGateway().validate_cached_output(
            PROMPT_ID,
            request,
            context,
            payload,
        )


def test_p04_execution_identity_binds_provider_schema_version_and_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    boundary = provider_output_schema_boundary(PROMPT_ID)
    assert boundary == {
        "format": "provider-output-schema-boundary/1.0.0",
        "prompt_id": PROMPT_ID,
        "prompt_version": prompt_spec(PROMPT_ID).prompt_version,
        "wire_schema_version": SCHEMA_VERSION,
        "schema_name": "BlueprintModelDraft",
        "schema_hash": canonical_hash(
            structured_output_format(
                prompt_spec(PROMPT_ID),
                request,
            )["schema"]
        ),
    }
    gateway = ModelGateway()
    before = gateway.execution_fingerprint(PROMPT_ID)
    changed = deepcopy(boundary)
    changed["schema_hash"] = "sha256:" + "f" * 64
    monkeypatch.setattr(
        gateway_module,
        "provider_output_schema_boundary",
        lambda _prompt_id: changed,
    )
    assert gateway.execution_fingerprint(PROMPT_ID) != before


def test_p04_model_call_identity_binds_provider_schema_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    context = build_trusted_context(request)
    gateway = ModelGateway()
    first = asyncio.run(gateway.invoke(PROMPT_ID, request, context))
    boundary = provider_output_schema_boundary(PROMPT_ID)
    changed = dict(boundary)
    changed["schema_hash"] = "sha256:" + "d" * 64
    monkeypatch.setattr(
        gateway_module,
        "provider_output_schema_boundary",
        lambda _prompt_id: changed,
    )
    second = asyncio.run(gateway.invoke(PROMPT_ID, request, context))

    assert first.ledgers[0].input_bundle_hash != second.ledgers[0].input_bundle_hash
    assert first.ledgers[0].model_call_id != second.ledgers[0].model_call_id


def test_p04_execution_identity_binds_complete_compiler_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = blueprint_compiler_boundary()
    material = {key: value for key, value in boundary.items() if key != "boundary_hash"}
    assert boundary["format"] == "blueprint-compiler-boundary/1.0.0"
    assert boundary["version"] == "blueprint-compiler/1.0.0"
    assert boundary["boundary_hash"] == canonical_hash(material)
    for key in (
        "compiler_source_hash",
        "canonical_contracts_source_hash",
        "canonical_identity_source_hash",
        "preflight_source_hash",
        "diagnostics_source_hash",
    ):
        assert boundary[key].startswith("sha256:")

    gateway = ModelGateway()
    before = gateway.execution_fingerprint(PROMPT_ID)
    changed = dict(boundary)
    changed["boundary_hash"] = "sha256:" + "e" * 64
    monkeypatch.setattr(
        gateway_module,
        "blueprint_compiler_boundary",
        lambda: changed,
    )
    assert gateway.execution_fingerprint(PROMPT_ID) != before


def test_p04_stage_cache_is_policy_bound_and_recompiles_server_fields() -> None:
    request = _request()
    draft = _draft(request)
    compiled = compile_and_preflight_blueprint(draft=draft, request=request)
    gateway = ModelGateway()
    component_version = gateway.execution_fingerprint(PROMPT_ID)
    repository = Repository("sqlite+pysqlite://")

    def policy_hash(item: m.BlueprintBuildRequest) -> str:
        return canonical_hash(
            {
                "blueprint_policy": item.blueprint_policy.model_dump(mode="json"),
                "model_mode": "mock",
                "p10_enabled": False,
            }
        )

    inputs = request.model_dump(mode="json")
    stored, reused = repository.save_stage(
        job_id="job_p04_original",
        tenant_id="tnt_test",
        stage=PROMPT_ID,
        inputs=inputs,
        component_version=component_version,
        policy_hash=policy_hash(request),
        output=compiled.model_dump(mode="json"),
    )
    assert not reused
    assert stored.output == compiled.model_dump(mode="json")

    revised_policy = request.blueprint_policy.model_copy(
        update={
            "target_total_minutes": request.blueprint_policy.target_total_minutes + 1
        }
    )
    revised_request = request.model_copy(update={"blueprint_policy": revised_policy})
    original_call = asyncio.run(
        gateway.invoke(PROMPT_ID, request, build_trusted_context(request))
    )
    revised_call = asyncio.run(
        gateway.invoke(
            PROMPT_ID,
            revised_request,
            build_trusted_context(revised_request),
        )
    )
    assert original_call.ledgers[0].input_bundle_hash != (
        revised_call.ledgers[0].input_bundle_hash
    )
    assert repository.stage_by_key(
        tenant_id="tnt_test",
        stage=PROMPT_ID,
        inputs=revised_request.model_dump(mode="json"),
        component_version=component_version,
        policy_hash=policy_hash(revised_request),
    ) is None

    recompiled = compile_and_preflight_blueprint(
        draft=draft,
        request=revised_request,
    )
    assert recompiled.assessment_constraints.target_total_minutes == (
        revised_policy.target_total_minutes
    )
    with pytest.raises(GatewayContextError):
        gateway.validate_cached_output(
            PROMPT_ID,
            revised_request,
            build_trusted_context(revised_request),
            compiled.model_dump(mode="json"),
        )
