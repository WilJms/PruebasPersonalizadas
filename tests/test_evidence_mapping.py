from __future__ import annotations

from pydantic import ValidationError
import pytest

from comprehension_verification.contracts import models as m
from comprehension_verification.evidence_mapping import (
    EvidenceMappingCompilationError,
    build_evidence_mapping_alias_envelope,
    evidence_mapping_materializer_boundary,
    materialize_evidence_mapping_draft,
    p06_alias_envelope_boundary,
    validate_materialized_evidence_mapping,
)
from comprehension_verification.model_gateway import build_mock_request
from comprehension_verification.model_gateway import (
    GatewaySchemaViolation,
    ModelGateway,
    build_trusted_context,
)
from comprehension_verification.planning import build_assessment_plan

from .factories import blueprint, evidence_bundle, evidence_map, planning_policy


def _request(
    *,
    question_count: int = 3,
    opportunity_count: int = 8,
    evidence_count: int = 8,
) -> m.EvidenceMapRequest:
    return m.EvidenceMapRequest(
        blueprint=blueprint(
            question_count=question_count,
            opportunity_count=opportunity_count,
            target_total_minutes=max(12, question_count * 3),
        ),
        planning_policy=planning_policy(),
        evidence_bundle=evidence_bundle(evidence_count),
    )


def _relation(
    index: int,
    *,
    evidence_aliases: list[str] | None = None,
    status: m.EvidenceSupportStatus = m.EvidenceSupportStatus.SUFFICIENT,
) -> m.EvidenceMappingRelationDraft:
    return m.EvidenceMappingRelationDraft(
        variant_alias="V1",
        template_alias=f"T{index}",
        evidence_aliases=evidence_aliases or [f"E{index}"],
        support_status=status,
        support_type=m.EvidenceSupportType.DIRECT,
        support_description=f"Relación semántica localizada {index}.",
        semantic_uncertainty=(
            "La evidencia admite dos lecturas locales."
            if status == m.EvidenceSupportStatus.UNCERTAIN
            else None
        ),
        abstention_reason=(
            "La evidencia relacionada no completa el observable."
            if status == m.EvidenceSupportStatus.INSUFFICIENT
            else None
        ),
    )


def _draft(
    request: m.EvidenceMapRequest,
    relations: list[m.EvidenceMappingRelationDraft],
) -> m.EvidenceMappingModelDraft:
    envelope = build_evidence_mapping_alias_envelope(request)
    return m.EvidenceMappingModelDraft(
        scope_alias=envelope.scope_alias,
        mappings=relations,
    )


def test_alias_envelope_is_local_and_materializes_canonical_server_fields() -> None:
    request = _request(opportunity_count=1, evidence_count=1)
    envelope = build_evidence_mapping_alias_envelope(request)
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(request, [_relation(1)]), request=request
    )
    opportunity = mapping.opportunities[0]
    template = request.blueprint.dimensions[0].evidence_variants[0].question_opportunities[0]

    assert envelope.dimensions[0].dimension_alias == "D1"
    assert envelope.variants[0].variant_alias == "V1"
    assert envelope.templates[0].template_alias == "T1"
    assert envelope.evidence_units[0].evidence_alias == "E1"
    assert request.evidence_bundle.submission_id not in envelope.model_dump_json()
    assert opportunity.submission_id == request.evidence_bundle.submission_id
    assert opportunity.dimension_id == request.blueprint.dimensions[0].dimension_id
    assert opportunity.variant_id == request.blueprint.dimensions[0].evidence_variants[0].variant_id
    assert opportunity.opportunity_template_id == template.opportunity_template_id
    assert opportunity.cognitive_operation == template.cognitive_operation
    assert opportunity.focus == template.focus
    assert opportunity.observable == template.observable
    assert opportunity.difficulty == template.difficulty
    assert opportunity.target_minutes == template.target_minutes
    assert opportunity.allowed_response_formats == template.allowed_response_formats
    assert opportunity.evidence_ids == [request.evidence_bundle.evidence_units[0].evidence_id]
    assert opportunity.support_status == m.EvidenceSupportStatus.SUFFICIENT


def test_unknown_alias_and_alias_scope_from_another_submission_fail_closed() -> None:
    request = _request(opportunity_count=1, evidence_count=1)
    with pytest.raises(EvidenceMappingCompilationError, match="unknown evidence alias") as unknown:
        materialize_evidence_mapping_draft(
            draft=_draft(request, [_relation(1, evidence_aliases=["E99"])]),
            request=request,
        )
    assert unknown.value.code == "P06_ALIAS_REFERENCE_UNKNOWN"

    foreign_bundle = request.evidence_bundle.model_dump(mode="json")
    foreign_bundle["submission_id"] = "sub_foreign"
    for unit in foreign_bundle["evidence_units"]:
        unit["submission_id"] = "sub_foreign"
    foreign_request = request.model_copy(
        update={"evidence_bundle": m.EvidenceBundle.model_validate(foreign_bundle)}
    )
    local_draft = _draft(request, [_relation(1)])
    with pytest.raises(EvidenceMappingCompilationError, match="another P06 alias envelope") as foreign:
        materialize_evidence_mapping_draft(
            draft=local_draft,
            request=foreign_request,
        )
    assert foreign.value.code == "P06_SCOPE_ALIAS_MISMATCH"


@pytest.mark.parametrize(
    ("status", "expected_fit"),
    (
        (m.EvidenceSupportStatus.SUFFICIENT, 1.0),
        (m.EvidenceSupportStatus.PARTIAL, 0.5),
        (m.EvidenceSupportStatus.INSUFFICIENT, 0.0),
        (m.EvidenceSupportStatus.UNCERTAIN, 0.0),
    ),
)
def test_categorical_support_is_preserved_without_provider_scores(
    status: m.EvidenceSupportStatus, expected_fit: float
) -> None:
    request = _request(opportunity_count=1, evidence_count=1)
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(request, [_relation(1, status=status)]), request=request
    )

    assert mapping.status == "READY"
    assert mapping.opportunities[0].support_status == status
    assert mapping.opportunities[0].evidence_fit == expected_fit
    assert mapping.opportunities[0].opportunity_quality == 0.75
    assert mapping.mapping_summary is not None
    assert mapping.mapping_summary.mapped_relation_count == 1


def test_partial_is_not_planner_eligible_by_default() -> None:
    request = _request(question_count=1, opportunity_count=2, evidence_count=2)
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(
            request,
            [
                _relation(1, status=m.EvidenceSupportStatus.PARTIAL),
                _relation(2, status=m.EvidenceSupportStatus.INSUFFICIENT),
            ],
        ),
        request=request,
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=request.blueprint,
        policy=request.planning_policy,
    )

    assert mapping.status == "READY"
    assert plan.status == "INSUFFICIENT_RELEVANT_EVIDENCE"
    assert plan.selected_opportunity_ids == []


def test_mapping_with_three_sufficient_for_n_five_completes_then_planner_fails() -> None:
    request = _request(question_count=5, opportunity_count=9, evidence_count=9)
    relations = [
        *[_relation(index) for index in range(1, 4)],
        *[
            _relation(index, status=m.EvidenceSupportStatus.PARTIAL)
            for index in range(4, 6)
        ],
        *[
            _relation(index, status=m.EvidenceSupportStatus.INSUFFICIENT)
            for index in range(6, 10)
        ],
    ]
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(request, relations), request=request
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=request.blueprint,
        policy=request.planning_policy,
    )

    assert mapping.status == "READY"
    assert mapping.mapping_summary is not None
    assert mapping.mapping_summary.sufficient_count == 3
    assert mapping.mapping_summary.partial_count == 2
    assert mapping.mapping_summary.insufficient_count == 4
    assert plan.status == "ASSESSMENT_PLAN_INFEASIBLE"
    assert plan.selected_opportunity_ids == []


def test_mapping_more_than_n_does_not_select_and_planner_is_deterministic() -> None:
    request = _request(question_count=5, opportunity_count=10, evidence_count=10)
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(request, [_relation(index) for index in range(1, 11)]),
        request=request,
    )
    first = build_assessment_plan(
        mapping=mapping,
        blueprint=request.blueprint,
        policy=request.planning_policy,
    )
    second = build_assessment_plan(
        mapping=mapping,
        blueprint=request.blueprint,
        policy=request.planning_policy,
    )

    assert len(mapping.opportunities) == 10
    assert not hasattr(mapping, "selected_opportunity_ids")
    assert first == second
    assert first.status == "READY"
    assert len(first.selected_opportunity_ids) == 5


def test_multi_span_and_same_submission_cross_artifact_mapping_are_preserved() -> None:
    request = _request(question_count=1, opportunity_count=1, evidence_count=7)
    bundle_data = request.evidence_bundle.model_dump(mode="json")
    bundle_data["evidence_units"][6]["artifact_id"] = "art_test_second"
    bundle_data["evidence_units"][6]["artifact_hash"] = "sha256:" + "b" * 64
    bundle = m.EvidenceBundle.model_validate(bundle_data)
    variant = request.blueprint.dimensions[0].evidence_variants[0]
    strict_variant = variant.model_copy(
        update={
            "evidence_requirement": variant.evidence_requirement.model_copy(
                update={"min_distinct_units": 2, "cross_artifact_required": True}
            )
        }
    )
    dimension = request.blueprint.dimensions[0].model_copy(
        update={"evidence_variants": [strict_variant]}
    )
    strict_request = request.model_copy(
        update={
            "blueprint": request.blueprint.model_copy(update={"dimensions": [dimension]}),
            "evidence_bundle": bundle,
        }
    )
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(strict_request, [_relation(1, evidence_aliases=["E2", "E7"])]),
        request=strict_request,
    )

    assert mapping.opportunities[0].evidence_ids == ["ev_test_2", "ev_test_7"]
    assert {
        item.artifact_id
        for item in strict_request.evidence_bundle.evidence_units
        if item.evidence_id in mapping.opportunities[0].evidence_ids
    } == {"art_test", "art_test_second"}


def test_duplicate_template_mapping_is_rejected_without_inventing_diversity() -> None:
    request = _request(opportunity_count=1, evidence_count=2)
    with pytest.raises(EvidenceMappingCompilationError, match="more than one mapping") as duplicate:
        materialize_evidence_mapping_draft(
            draft=_draft(
                request,
                [
                    _relation(1, evidence_aliases=["E1"]),
                    _relation(1, evidence_aliases=["E2"]),
                ],
            ),
            request=request,
        )
    assert duplicate.value.code == "P06_MAPPING_DUPLICATE"


def test_provider_draft_and_canonical_cache_are_not_interchangeable() -> None:
    request = _request(opportunity_count=1, evidence_count=1)
    draft = _draft(request, [_relation(1)])
    canonical = materialize_evidence_mapping_draft(draft=draft, request=request)

    with pytest.raises(ValidationError):
        m.EvidenceMapPatch.model_validate(draft.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        m.EvidenceMappingModelDraft.model_validate(canonical.model_dump(mode="json"))
    validate_materialized_evidence_mapping(mapping=canonical, request=request)

    historical = evidence_map(request.blueprint, request.evidence_bundle, opportunity_count=1)
    assert m.EvidenceMapPatch.model_validate(historical.model_dump(mode="json")) == historical
    with pytest.raises(EvidenceMappingCompilationError, match="current materializer output"):
        validate_materialized_evidence_mapping(mapping=historical, request=request)

    gateway = ModelGateway()
    trusted = build_trusted_context(request)
    assert gateway.validate_cached_output(
        "P06_EVIDENCE_MAP_V1",
        request,
        trusted,
        canonical.model_dump(mode="json"),
    ) == canonical
    with pytest.raises(GatewaySchemaViolation):
        gateway.validate_cached_output(
            "P06_EVIDENCE_MAP_V1",
            request,
            trusted,
            draft.model_dump(mode="json"),
        )


def test_alias_cache_boundary_changes_with_blueprint_policy_evidence_and_scope() -> None:
    request = _request(opportunity_count=2, evidence_count=2)
    baseline = p06_alias_envelope_boundary(request)

    blueprint_request = request.model_copy(
        update={"blueprint": request.blueprint.model_copy(update={"blueprint_version": 2})}
    )
    policy_request = request.model_copy(
        update={
            "planning_policy": request.planning_policy.model_copy(
                update={"minimum_evidence_fit": 0.71}
            )
        }
    )
    evidence_data = request.evidence_bundle.model_dump(mode="json")
    evidence_data["evidence_units"][0]["content_text"] = "Evidencia sintética distinta."
    evidence_request = request.model_copy(
        update={"evidence_bundle": m.EvidenceBundle.model_validate(evidence_data)}
    )
    foreign_data = request.evidence_bundle.model_dump(mode="json")
    foreign_data["submission_id"] = "sub_foreign"
    for unit in foreign_data["evidence_units"]:
        unit["submission_id"] = "sub_foreign"
    scope_request = request.model_copy(
        update={"evidence_bundle": m.EvidenceBundle.model_validate(foreign_data)}
    )

    for changed in (
        blueprint_request,
        policy_request,
        evidence_request,
        scope_request,
    ):
        assert (
            p06_alias_envelope_boundary(changed)["request_boundary_hash"]
            != baseline["request_boundary_hash"]
        )

    materializer = evidence_mapping_materializer_boundary()
    assert materializer["version"] == "p06-evidence-materializer/1.0.0"
    assert materializer["materializer_source_hash"].startswith("sha256:")
    assert materializer["boundary_hash"].startswith("sha256:")


def test_alias_schema_and_materializer_version_changes_invalidate_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from comprehension_verification import evidence_mapping as compiler

    alias_before = compiler.p06_alias_envelope_schema_boundary()[
        "boundary_hash"
    ]
    materializer_before = compiler.evidence_mapping_materializer_boundary()[
        "boundary_hash"
    ]
    monkeypatch.setattr(
        compiler,
        "P06_ALIAS_ENVELOPE_VERSION",
        "p06-alias-envelope/test-change",
    )
    monkeypatch.setattr(
        compiler,
        "P06_MATERIALIZER_VERSION",
        "p06-evidence-materializer/test-change",
    )

    assert (
        compiler.p06_alias_envelope_schema_boundary()["boundary_hash"]
        != alias_before
    )
    assert (
        compiler.evidence_mapping_materializer_boundary()["boundary_hash"]
        != materializer_before
    )


def test_empty_semantic_mapping_is_a_completed_mapping_not_a_provider_failure() -> None:
    request = build_mock_request("P06_EVIDENCE_MAP_V1")
    mapping = materialize_evidence_mapping_draft(
        draft=_draft(request, []), request=request
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=request.blueprint,
        policy=request.planning_policy,
    )

    assert mapping.status == "READY"
    assert mapping.opportunities == []
    assert mapping.mapping_summary is not None
    assert mapping.mapping_summary.mapped_relation_count == 0
    assert plan.status == "INSUFFICIENT_RELEVANT_EVIDENCE"
