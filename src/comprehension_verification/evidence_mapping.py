"""Deterministic P06 alias envelope and provider-draft materialization."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from .canonical import canonical_hash, stable_id
from .contracts import models as m


P06_ALIAS_ENVELOPE_VERSION = "p06-alias-envelope/1.0.0"
P06_MATERIALIZER_VERSION = "p06-evidence-materializer/1.0.0"
P06_MATERIALIZER_BOUNDARY_FORMAT = "p06-materializer-boundary/1.0.0"


class EvidenceMappingCompilationError(ValueError):
    """Content-free deterministic rejection of a P06 provider draft/cache."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise EvidenceMappingCompilationError(code, message)


def _source_file_hash(path: str | Path) -> str:
    return f"sha256:{sha256(Path(path).read_bytes()).hexdigest()}"


def _schema_hash(model: type[m.StrictModel]) -> str:
    return canonical_hash(model.model_json_schema(mode="validation"))


def p06_alias_envelope_schema_boundary() -> dict[str, str]:
    material = {
        "format": "p06-alias-envelope-schema-boundary/1.0.0",
        "version": P06_ALIAS_ENVELOPE_VERSION,
        "schema_name": "EvidenceMappingAliasEnvelope",
        "schema_hash": _schema_hash(m.EvidenceMappingAliasEnvelope),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def evidence_mapping_materializer_boundary() -> dict[str, str]:
    """Bind every executable dependency that can affect canonical P06 output."""

    material = {
        "format": P06_MATERIALIZER_BOUNDARY_FORMAT,
        "version": P06_MATERIALIZER_VERSION,
        "materializer_source_hash": _source_file_hash(__file__),
        "canonical_contracts_source_hash": _source_file_hash(m.__file__),
        "canonical_identity_source_hash": _source_file_hash(
            stable_id.__code__.co_filename
        ),
        "alias_envelope_schema": p06_alias_envelope_schema_boundary(),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def _scope_hash(request: m.EvidenceMapRequest) -> str:
    return canonical_hash(request.model_dump(mode="json"))


def _scope_alias(request: m.EvidenceMapRequest) -> str:
    return "S" + _scope_hash(request).removeprefix("sha256:")[:24]


def _catalog(
    request: m.EvidenceMapRequest,
) -> tuple[
    list[m.BlueprintDimension],
    list[tuple[m.BlueprintDimension, m.EvidenceVariant]],
    list[
        tuple[
            m.BlueprintDimension,
            m.EvidenceVariant,
            m.QuestionOpportunityTemplate,
        ]
    ],
]:
    dimensions = list(request.blueprint.dimensions)
    variants = [
        (dimension, variant)
        for dimension in dimensions
        for variant in dimension.evidence_variants
    ]
    templates = [
        (dimension, variant, template)
        for dimension, variant in variants
        for template in variant.question_opportunities
    ]
    return dimensions, variants, templates


def _alias_indexes(
    request: m.EvidenceMapRequest,
) -> tuple[
    dict[str, m.BlueprintDimension],
    dict[str, tuple[m.BlueprintDimension, m.EvidenceVariant]],
    dict[
        str,
        tuple[
            m.BlueprintDimension,
            m.EvidenceVariant,
            m.QuestionOpportunityTemplate,
        ],
    ],
    dict[str, m.EvidenceUnit],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    dimensions, variants, templates = _catalog(request)
    dimensions_by_alias = {
        f"D{index}": item for index, item in enumerate(dimensions, start=1)
    }
    variants_by_alias = {
        f"V{index}": item for index, item in enumerate(variants, start=1)
    }
    templates_by_alias = {
        f"T{index}": item for index, item in enumerate(templates, start=1)
    }
    evidence_by_alias = {
        f"E{index}": item
        for index, item in enumerate(
            request.evidence_bundle.evidence_units, start=1
        )
    }
    variant_alias_by_id = {
        variant.variant_id: alias
        for alias, (_dimension, variant) in variants_by_alias.items()
    }
    template_alias_by_id = {
        template.opportunity_template_id: alias
        for alias, (_dimension, _variant, template) in templates_by_alias.items()
    }
    evidence_alias_by_id = {
        evidence.evidence_id: alias
        for alias, evidence in evidence_by_alias.items()
    }
    return (
        dimensions_by_alias,
        variants_by_alias,
        templates_by_alias,
        evidence_by_alias,
        variant_alias_by_id,
        template_alias_by_id,
        evidence_alias_by_id,
    )


def build_evidence_mapping_alias_envelope(
    request: m.EvidenceMapRequest,
) -> m.EvidenceMappingAliasEnvelope:
    """Project one canonical P06 request into a closed call-local namespace."""

    (
        dimensions_by_alias,
        variants_by_alias,
        templates_by_alias,
        evidence_by_alias,
        variant_alias_by_id,
        _template_alias_by_id,
        _evidence_alias_by_id,
    ) = _alias_indexes(request)
    dimension_alias_by_id = {
        dimension.dimension_id: alias
        for alias, dimension in dimensions_by_alias.items()
    }
    artifact_alias_by_id: dict[str, str] = {}
    for evidence in evidence_by_alias.values():
        artifact_alias_by_id.setdefault(
            evidence.artifact_id, f"A{len(artifact_alias_by_id) + 1}"
        )

    return m.EvidenceMappingAliasEnvelope(
        alias_schema_version=P06_ALIAS_ENVELOPE_VERSION,
        scope_alias=_scope_alias(request),
        source_scope_hash=_scope_hash(request),
        dimensions=[
            m.EvidenceMappingDimensionContext(
                dimension_alias=alias,
                name=dimension.name,
                justification=dimension.justification,
            )
            for alias, dimension in dimensions_by_alias.items()
        ],
        variants=[
            m.EvidenceMappingVariantContext(
                variant_alias=alias,
                dimension_alias=dimension_alias_by_id[dimension.dimension_id],
                name=variant.name,
                description=variant.description,
                evidence_requirement=variant.evidence_requirement.model_copy(
                    deep=True
                ),
                supported_operations=[
                    item.model_copy(deep=True)
                    for item in variant.supported_operations
                ],
            )
            for alias, (dimension, variant) in variants_by_alias.items()
        ],
        templates=[
            m.EvidenceMappingTemplateContext(
                template_alias=alias,
                variant_alias=variant_alias_by_id[variant.variant_id],
                cognitive_operation=template.cognitive_operation,
                focus=template.focus,
                observable=template.observable,
            )
            for alias, (_dimension, variant, template) in templates_by_alias.items()
        ],
        evidence_units=[
            m.EvidenceMappingEvidenceContext(
                evidence_alias=alias,
                artifact_alias=artifact_alias_by_id[evidence.artifact_id],
                modality=evidence.modality,
                content_text=evidence.content_text,
                structured_content=evidence.structured_content,
                language=evidence.language,
                extraction_confidence=evidence.extraction_confidence,
            )
            for alias, evidence in evidence_by_alias.items()
        ],
    )


def p06_alias_envelope_boundary(
    request: m.EvidenceMapRequest,
) -> dict[str, str]:
    envelope = build_evidence_mapping_alias_envelope(request)
    bundle = request.evidence_bundle
    material = {
        **p06_alias_envelope_schema_boundary(),
        "envelope_hash": canonical_hash(envelope.model_dump(mode="json")),
        "source_scope_hash": envelope.source_scope_hash,
        "blueprint_hash": canonical_hash(
            request.blueprint.model_dump(mode="json")
        ),
        "policy_hash": canonical_hash(
            request.planning_policy.model_dump(mode="json")
        ),
        "evidence_bundle_hash": canonical_hash(bundle.model_dump(mode="json")),
        "submission_scope_hash": canonical_hash(
            {
                "tenant_id": bundle.tenant_id,
                "activity_id": bundle.activity_id,
                "submission_id": bundle.submission_id,
            }
        ),
    }
    return {**material, "request_boundary_hash": canonical_hash(material)}


def _compatibility_fit(status: m.EvidenceSupportStatus) -> float:
    """Legacy projection only; no active validator or planner consumes it."""

    return {
        m.EvidenceSupportStatus.SUFFICIENT: 1.0,
        m.EvidenceSupportStatus.PARTIAL: 0.5,
        m.EvidenceSupportStatus.INSUFFICIENT: 0.0,
        m.EvidenceSupportStatus.UNCERTAIN: 0.0,
    }[status]


def _validate_sufficient_evidence(
    *, variant: m.EvidenceVariant, evidence: list[m.EvidenceUnit]
) -> None:
    requirement = variant.evidence_requirement
    if len(evidence) < requirement.min_distinct_units:
        _fail(
            "P06_SUFFICIENT_REQUIREMENT_MISMATCH",
            "SUFFICIENT mapping does not meet the distinct-unit requirement",
        )
    if any(item.modality not in requirement.allowed_modalities for item in evidence):
        _fail(
            "P06_SUFFICIENT_REQUIREMENT_MISMATCH",
            "SUFFICIENT mapping uses a modality outside the route requirement",
        )
    if any(
        item.extraction_confidence < requirement.min_extraction_confidence
        for item in evidence
    ):
        _fail(
            "P06_SUFFICIENT_REQUIREMENT_MISMATCH",
            "SUFFICIENT mapping uses evidence below the extraction floor",
        )
    if requirement.cross_artifact_required and len(
        {item.artifact_id for item in evidence}
    ) < 2:
        _fail(
            "P06_SUFFICIENT_REQUIREMENT_MISMATCH",
            "SUFFICIENT mapping does not meet the cross-artifact requirement",
        )


def _aggregate_support_status(
    statuses: Iterable[m.EvidenceSupportStatus],
) -> m.EvidenceSupportStatus:
    materialized = set(statuses)
    for status in (
        m.EvidenceSupportStatus.SUFFICIENT,
        m.EvidenceSupportStatus.PARTIAL,
        m.EvidenceSupportStatus.UNCERTAIN,
        m.EvidenceSupportStatus.INSUFFICIENT,
    ):
        if status in materialized:
            return status
    raise AssertionError("variant mapping group cannot be empty")


def materialize_evidence_mapping_draft(
    *,
    draft: m.EvidenceMappingModelDraft,
    request: m.EvidenceMapRequest,
) -> m.EvidenceMapPatch:
    """Resolve aliases and copy trusted blueprint fields into canonical P06 IR."""

    expected_scope_alias = _scope_alias(request)
    if draft.scope_alias != expected_scope_alias:
        _fail(
            "P06_SCOPE_ALIAS_MISMATCH",
            "provider output belongs to another P06 alias envelope",
        )
    (
        _dimensions_by_alias,
        variants_by_alias,
        templates_by_alias,
        evidence_by_alias,
        _variant_alias_by_id,
        _template_alias_by_id,
        _evidence_alias_by_id,
    ) = _alias_indexes(request)
    template_aliases = [item.template_alias for item in draft.mappings]
    if len(template_aliases) != len(set(template_aliases)):
        _fail(
            "P06_MAPPING_DUPLICATE",
            "provider output contains more than one mapping for a template route",
        )

    opportunities: list[m.QuestionOpportunity] = []
    relations_by_variant: dict[str, list[m.EvidenceMappingRelationDraft]] = (
        defaultdict(list)
    )
    for relation in draft.mappings:
        variant_path = variants_by_alias.get(relation.variant_alias)
        template_path = templates_by_alias.get(relation.template_alias)
        if variant_path is None or template_path is None:
            _fail(
                "P06_ALIAS_REFERENCE_UNKNOWN",
                "provider output references an unknown route alias",
            )
        dimension, variant = variant_path
        template_dimension, template_variant, template = template_path
        if (
            template_variant.variant_id != variant.variant_id
            or template_dimension.dimension_id != dimension.dimension_id
        ):
            _fail(
                "P06_TEMPLATE_VARIANT_MISMATCH",
                "provider output combines aliases from different blueprint routes",
            )
        evidence: list[m.EvidenceUnit] = []
        for alias in relation.evidence_aliases:
            unit = evidence_by_alias.get(alias)
            if unit is None:
                _fail(
                    "P06_ALIAS_REFERENCE_UNKNOWN",
                    "provider output references an unknown evidence alias",
                )
            evidence.append(unit)
        supported_operations = {
            item.cognitive_operation for item in variant.supported_operations
        }
        if template.cognitive_operation not in supported_operations:
            _fail(
                "P06_UNSUPPORTED_OPERATION",
                "trusted template operation is not declared by its variant",
            )
        if relation.support_status == m.EvidenceSupportStatus.SUFFICIENT:
            _validate_sufficient_evidence(variant=variant, evidence=evidence)
        evidence_ids = [item.evidence_id for item in evidence]
        opportunities.append(
            m.QuestionOpportunity(
                opportunity_id=stable_id(
                    "opportunity",
                    request.evidence_bundle.submission_id,
                    request.blueprint.blueprint_id,
                    request.blueprint.blueprint_version,
                    template.opportunity_template_id,
                    sorted(evidence_ids),
                    P06_MATERIALIZER_VERSION,
                ),
                opportunity_template_id=template.opportunity_template_id,
                submission_id=request.evidence_bundle.submission_id,
                dimension_id=dimension.dimension_id,
                variant_id=variant.variant_id,
                evidence_ids=evidence_ids,
                cognitive_operation=template.cognitive_operation,
                focus=template.focus,
                observable=template.observable,
                difficulty=template.difficulty,
                target_minutes=template.target_minutes,
                allowed_anchor_structures=list(template.allowed_anchor_structures),
                allowed_response_formats=list(template.allowed_response_formats),
                activity_priority=dimension.verification_priority,
                evidence_fit=_compatibility_fit(relation.support_status),
                opportunity_quality=template.minimum_quality,
                student_justification_required=(
                    template.student_justification_required
                ),
                support_status=relation.support_status,
                support_type=relation.support_type,
                support_description=relation.support_description,
                semantic_uncertainty=relation.semantic_uncertainty,
                abstention_reason=relation.abstention_reason,
            )
        )
        relations_by_variant[relation.variant_alias].append(relation)

    variant_matches: list[m.EvidenceVariantMatch] = []
    opportunity_by_template_id = {
        item.opportunity_template_id: item for item in opportunities
    }
    for variant_alias, relations in relations_by_variant.items():
        dimension, variant = variants_by_alias[variant_alias]
        statuses = [item.support_status for item in relations]
        aggregate_status = _aggregate_support_status(statuses)
        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for relation in relations
                for evidence_id in opportunity_by_template_id[
                    templates_by_alias[relation.template_alias][
                        2
                    ].opportunity_template_id
                ].evidence_ids
            )
        )
        variant_matches.append(
            m.EvidenceVariantMatch(
                dimension_id=dimension.dimension_id,
                variant_id=variant.variant_id,
                evidence_ids=evidence_ids,
                evidence_fit=_compatibility_fit(aggregate_status),
                mapping_confidence=(
                    0.0
                    if aggregate_status == m.EvidenceSupportStatus.UNCERTAIN
                    else 1.0
                ),
                justification=(
                    "Relaciones categóricas P06 materializadas por el servidor."
                ),
                support_status=aggregate_status,
            )
        )

    counts = {
        status: sum(item.support_status == status for item in opportunities)
        for status in m.EvidenceSupportStatus
    }
    return m.EvidenceMapPatch(
        submission_id=request.evidence_bundle.submission_id,
        status="READY",
        claims=[],
        variant_matches=variant_matches,
        opportunities=opportunities,
        mapping_summary=m.EvidenceMappingSummary(
            mapped_relation_count=len(opportunities),
            sufficient_count=counts[m.EvidenceSupportStatus.SUFFICIENT],
            partial_count=counts[m.EvidenceSupportStatus.PARTIAL],
            insufficient_count=counts[m.EvidenceSupportStatus.INSUFFICIENT],
            uncertain_count=counts[m.EvidenceSupportStatus.UNCERTAIN],
        ),
        diagnostics=[],
    )


def _draft_from_materialized_mapping(
    *, mapping: m.EvidenceMapPatch, request: m.EvidenceMapRequest
) -> m.EvidenceMappingModelDraft:
    if (
        mapping.status != "READY"
        or mapping.mapping_summary is None
        or mapping.claims
        or mapping.diagnostics
    ):
        _fail(
            "P06_CANONICAL_REPLAY_MISMATCH",
            "canonical mapping is not a current materializer output",
        )
    (
        _dimensions_by_alias,
        _variants_by_alias,
        _templates_by_alias,
        _evidence_by_alias,
        variant_alias_by_id,
        template_alias_by_id,
        evidence_alias_by_id,
    ) = _alias_indexes(request)
    relations: list[m.EvidenceMappingRelationDraft] = []
    for opportunity in mapping.opportunities:
        if opportunity.support_description is None:
            _fail(
                "P06_CANONICAL_REPLAY_MISMATCH",
                "canonical mapping lacks current semantic support metadata",
            )
        try:
            variant_alias = variant_alias_by_id[opportunity.variant_id]
            template_alias = template_alias_by_id[
                opportunity.opportunity_template_id
            ]
            evidence_aliases = [
                evidence_alias_by_id[item] for item in opportunity.evidence_ids
            ]
        except KeyError as exc:
            _fail(
                "P06_CANONICAL_REPLAY_MISMATCH",
                "canonical mapping references outside the current request",
            )
        relations.append(
            m.EvidenceMappingRelationDraft(
                variant_alias=variant_alias,
                template_alias=template_alias,
                evidence_aliases=evidence_aliases,
                support_status=opportunity.support_status,
                support_type=opportunity.support_type,
                support_description=opportunity.support_description,
                semantic_uncertainty=opportunity.semantic_uncertainty,
                abstention_reason=opportunity.abstention_reason,
            )
        )
    return m.EvidenceMappingModelDraft(
        scope_alias=_scope_alias(request), mappings=relations
    )


def validate_materialized_evidence_mapping(
    *, mapping: m.EvidenceMapPatch, request: m.EvidenceMapRequest
) -> None:
    """Recompile a current canonical cache entry and require exact equality."""

    if mapping.submission_id != request.evidence_bundle.submission_id:
        _fail(
            "P06_SCOPE_MISMATCH",
            "canonical mapping belongs to another submission",
        )
    draft = _draft_from_materialized_mapping(mapping=mapping, request=request)
    replayed = materialize_evidence_mapping_draft(draft=draft, request=request)
    if replayed != mapping:
        _fail(
            "P06_CANONICAL_REPLAY_MISMATCH",
            "canonical mapping is not the exact current materializer output",
        )
