"""Deterministic P04 provider-draft to canonical-blueprint compilation."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re
import unicodedata
from typing import Iterable

from .canonical import canonical_hash, stable_id
from .contracts import models as m
from .diagnostics import diagnostic
from .validation import build_blueprint_review_preflight


BLUEPRINT_COMPILER_VERSION = "blueprint-compiler/1.0.0"
BLUEPRINT_COMPILER_BOUNDARY_FORMAT = "blueprint-compiler-boundary/1.0.0"


def _source_file_hash(path: str | Path) -> str:
    return f"sha256:{sha256(Path(path).read_bytes()).hexdigest()}"


def blueprint_compiler_boundary() -> dict[str, str]:
    """Return the complete executable boundary for P04 draft compilation.

    Hashing only ``compile_and_preflight_blueprint`` would miss changes in its
    helpers and imported deterministic dependencies.  The boundary therefore
    binds the whole compiler module, canonical contract validators, stable-ID
    implementation, deterministic preflight and diagnostic materialization.
    """

    material = {
        "format": BLUEPRINT_COMPILER_BOUNDARY_FORMAT,
        "version": BLUEPRINT_COMPILER_VERSION,
        "compiler_source_hash": _source_file_hash(__file__),
        "canonical_contracts_source_hash": _source_file_hash(m.__file__),
        "canonical_identity_source_hash": _source_file_hash(
            stable_id.__code__.co_filename
        ),
        "preflight_source_hash": _source_file_hash(
            build_blueprint_review_preflight.__code__.co_filename
        ),
        "diagnostics_source_hash": _source_file_hash(
            diagnostic.__code__.co_filename
        ),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


class BlueprintCompilationError(ValueError):
    """A content-free deterministic rejection of a P04 provider draft."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise BlueprintCompilationError(code, message)


def _require_unique(values: Iterable[object], *, code: str, label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        _fail(code, f"{label} must be unique")


def _semantic_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def _evidence_requirement_signature(
    requirement: m.EvidenceRequirement,
) -> tuple[object, ...]:
    return (
        tuple(sorted(item.value for item in requirement.allowed_modalities)),
        requirement.min_distinct_units,
        requirement.min_extraction_confidence,
        requirement.min_alignment,
        requirement.cross_artifact_required,
        requirement.course_sources_allowed,
    )


def _supported_operations_signature(
    operations: list[m.SupportedOperation],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                operation.cognitive_operation.value,
                _semantic_text(operation.rationale),
            )
            for operation in operations
        )
    )


def _validate_alias_graph(
    draft: m.BlueprintModelDraft,
    policy: m.BlueprintPolicy,
) -> tuple[
    dict[str, m.BlueprintDimensionDraft],
    dict[str, m.EvidenceVariantDraft],
    dict[str, m.QuestionOpportunityTemplateDraft],
]:
    _require_unique(
        (item.dimension_alias for item in draft.dimensions),
        code="BLUEPRINT_ALIAS_DUPLICATE",
        label="dimension aliases",
    )
    _require_unique(
        (item.variant_alias for item in draft.evidence_variants),
        code="BLUEPRINT_ALIAS_DUPLICATE",
        label="variant aliases",
    )
    _require_unique(
        (item.template_alias for item in draft.question_opportunities),
        code="BLUEPRINT_ALIAS_DUPLICATE",
        label="template aliases",
    )
    dimensions = {item.dimension_alias: item for item in draft.dimensions}
    variants = {item.variant_alias: item for item in draft.evidence_variants}
    templates = {item.template_alias: item for item in draft.question_opportunities}

    if any(item.dimension_alias not in dimensions for item in draft.evidence_variants):
        _fail(
            "BLUEPRINT_ALIAS_REFERENCE_UNKNOWN",
            "a variant references an unknown dimension alias",
        )
    if any(item.variant_alias not in variants for item in draft.question_opportunities):
        _fail(
            "BLUEPRINT_ALIAS_REFERENCE_UNKNOWN",
            "an opportunity references an unknown variant alias",
        )

    variant_counts = Counter(item.dimension_alias for item in draft.evidence_variants)
    template_counts = Counter(item.variant_alias for item in draft.question_opportunities)
    if any(variant_counts[alias] == 0 for alias in dimensions):
        _fail(
            "BLUEPRINT_STRUCTURE_IMPOSSIBLE",
            "every dimension requires at least one evidence variant",
        )
    if any(template_counts[alias] == 0 for alias in variants):
        _fail(
            "BLUEPRINT_STRUCTURE_IMPOSSIBLE",
            "every evidence variant requires at least one opportunity",
        )
    if any(
        count > policy.max_variants_per_dimension
        for count in variant_counts.values()
    ):
        _fail(
            "BLUEPRINT_POLICY_LIMIT_EXCEEDED",
            "a dimension exceeds the trusted variant limit",
        )
    if any(
        count > policy.max_templates_per_variant
        for count in template_counts.values()
    ):
        _fail(
            "BLUEPRINT_POLICY_LIMIT_EXCEEDED",
            "a variant exceeds the trusted opportunity limit",
        )
    return dimensions, variants, templates


def _validate_source_relationships(
    draft: m.BlueprintModelDraft,
    request: m.BlueprintBuildRequest,
) -> None:
    learning_outcome_ids = {
        item.statement_id for item in request.activity_spec.learning_outcomes
    }
    source_statement_ids = {
        item.statement_id
        for collection in (
            request.activity_spec.learning_outcomes,
            request.activity_spec.expected_products,
            request.activity_spec.requirements,
        )
        for item in collection
    }
    rubric_criterion_ids = (
        {item.criterion_id for item in request.rubric_spec.criteria}
        if request.rubric_spec is not None
        else set()
    )
    allowed_criterion_ids = rubric_criterion_ids or source_statement_ids
    referenced_criterion_ids: set[str] = set()
    referenced_outcome_ids: set[str] = set()
    for dimension in draft.dimensions:
        _require_unique(
            dimension.criterion_ids,
            code="BLUEPRINT_REFERENCE_DUPLICATE",
            label="dimension criterion references",
        )
        _require_unique(
            dimension.learning_outcome_ids,
            code="BLUEPRINT_REFERENCE_DUPLICATE",
            label="dimension outcome references",
        )
        if not set(dimension.criterion_ids).issubset(allowed_criterion_ids):
            _fail(
                "BLUEPRINT_REFERENCE_NOT_ALLOWLISTED",
                "a dimension references an unknown criterion",
            )
        if not set(dimension.learning_outcome_ids).issubset(
            learning_outcome_ids
        ):
            _fail(
                "BLUEPRINT_REFERENCE_NOT_ALLOWLISTED",
                "a dimension references an unknown learning outcome",
            )
        referenced_criterion_ids.update(dimension.criterion_ids)
        referenced_outcome_ids.update(dimension.learning_outcome_ids)

    policy_criterion_ids = set(request.blueprint_policy.priority_criterion_ids).union(
        request.blueprint_policy.required_criterion_ids
    )
    if not policy_criterion_ids.issubset(allowed_criterion_ids):
        _fail(
            "BLUEPRINT_POLICY_REFERENCE_NOT_ALLOWLISTED",
            "the trusted policy references an unknown criterion",
        )
    verifiable_criterion_ids = (
        {
            item.criterion_id
            for item in request.rubric_spec.criteria
            if item.verification_fit != "NOT_VERIFIABLE"
        }
        if request.rubric_spec is not None
        else set()
    )
    if not verifiable_criterion_ids.issubset(referenced_criterion_ids):
        _fail(
            "BLUEPRINT_SOURCE_COVERAGE_INCOMPLETE",
            "the draft omits a verifiable rubric criterion",
        )
    if not learning_outcome_ids.issubset(referenced_outcome_ids):
        _fail(
            "BLUEPRINT_SOURCE_COVERAGE_INCOMPLETE",
            "the draft omits a learning outcome",
        )
    if not set(request.blueprint_policy.required_criterion_ids).issubset(
        referenced_criterion_ids
    ):
        _fail(
            "BLUEPRINT_SOURCE_COVERAGE_INCOMPLETE",
            "the draft omits a required trusted criterion",
        )


def _validate_semantic_catalog(
    draft: m.BlueprintModelDraft,
    policy: m.BlueprintPolicy,
) -> None:
    dimension_signatures = [
        (
            _semantic_text(item.name),
            tuple(sorted(item.criterion_ids)),
            tuple(sorted(item.learning_outcome_ids)),
        )
        for item in draft.dimensions
    ]
    _require_unique(
        dimension_signatures,
        code="BLUEPRINT_SEMANTIC_DUPLICATE",
        label="semantic dimensions",
    )

    variant_signatures = [
        (
            item.dimension_alias,
            _semantic_text(item.name),
            _semantic_text(item.description),
            _evidence_requirement_signature(item.evidence_requirement),
            _supported_operations_signature(item.supported_operations),
        )
        for item in draft.evidence_variants
    ]
    _require_unique(
        variant_signatures,
        code="BLUEPRINT_SEMANTIC_DUPLICATE",
        label="semantic evidence variants",
    )

    allowed_formats = set(policy.allowed_response_formats)
    opportunity_signatures: list[tuple[object, ...]] = []
    operations_by_variant: dict[str, set[m.CognitiveOperation]] = {}
    for variant in draft.evidence_variants:
        if (
            policy.context_mode == m.ContextMode.CLOSED
            and variant.evidence_requirement.course_sources_allowed
        ):
            _fail(
                "BLUEPRINT_REFERENCE_NOT_ALLOWLISTED",
                "closed context cannot authorize course-source evidence",
            )
        operation_values = [
            item.cognitive_operation for item in variant.supported_operations
        ]
        _require_unique(
            operation_values,
            code="BLUEPRINT_UNSUPPORTED_OPERATION",
            label="supported cognitive operations",
        )
        _require_unique(
            variant.evidence_requirement.allowed_modalities,
            code="BLUEPRINT_REFERENCE_DUPLICATE",
            label="allowed evidence modalities",
        )
        operations_by_variant[variant.variant_alias] = set(operation_values)

    for item in draft.question_opportunities:
        if item.cognitive_operation not in operations_by_variant[item.variant_alias]:
            _fail(
                "BLUEPRINT_UNSUPPORTED_OPERATION",
                "an opportunity widens its variant's supported operations",
            )
        _require_unique(
            item.allowed_anchor_structures,
            code="BLUEPRINT_REFERENCE_DUPLICATE",
            label="allowed anchor structures",
        )
        _require_unique(
            item.allowed_response_formats,
            code="BLUEPRINT_REFERENCE_DUPLICATE",
            label="allowed response formats",
        )
        if not set(item.allowed_response_formats).issubset(allowed_formats):
            _fail(
                "BLUEPRINT_FORMAT_NOT_ALLOWED",
                "an opportunity uses a response format outside policy",
            )
        opportunity_signatures.append(
            (
                item.variant_alias,
                item.cognitive_operation.value,
                _semantic_text(item.focus),
                _semantic_text(item.observable),
                item.difficulty.value,
                item.target_minutes,
                tuple(sorted(value.value for value in item.allowed_anchor_structures)),
                tuple(sorted(value.value for value in item.allowed_response_formats)),
                item.justification_required,
            )
        )
    _require_unique(
        opportunity_signatures,
        code="BLUEPRINT_SEMANTIC_DUPLICATE",
        label="semantic question opportunities",
    )

    justification = policy.structured_justification_policy
    if justification.mode == m.StructuredJustificationMode.SELECTED:
        selected_count = sum(
            item.justification_required for item in draft.question_opportunities
        )
        if selected_count != len(justification.selected_opportunity_template_ids):
            _fail(
                "BLUEPRINT_JUSTIFICATION_POLICY_MISMATCH",
                "the semantic justification selection does not match policy cardinality",
            )


def _template_ids(
    draft: m.BlueprintModelDraft,
    request: m.BlueprintBuildRequest,
    variant_ids: dict[str, str],
) -> dict[str, str]:
    justification = request.blueprint_policy.structured_justification_policy
    selected_aliases = [
        item.template_alias
        for item in draft.question_opportunities
        if item.justification_required
    ]
    selected_ids_by_alias = (
        dict(
            zip(
                selected_aliases,
                justification.selected_opportunity_template_ids,
                strict=True,
            )
        )
        if justification.mode == m.StructuredJustificationMode.SELECTED
        else {}
    )
    ids: dict[str, str] = {}
    for variant in draft.evidence_variants:
        children = [
            item
            for item in draft.question_opportunities
            if item.variant_alias == variant.variant_alias
        ]
        for index, item in enumerate(children):
            ids[item.template_alias] = selected_ids_by_alias.get(
                item.template_alias,
                stable_id("oppt", variant_ids[variant.variant_alias], index),
            )
    _require_unique(
        ids.values(),
        code="BLUEPRINT_STRUCTURE_IMPOSSIBLE",
        label="compiled opportunity IDs",
    )
    return ids


def compile_blueprint_model_draft(
    *,
    draft: m.BlueprintModelDraft,
    request: m.BlueprintBuildRequest,
) -> m.AssessmentBlueprint:
    """Compile semantic aliases and trusted inputs into one canonical blueprint."""

    if request.blueprint_policy.activity_id != request.activity_spec.activity_id:
        _fail(
            "BLUEPRINT_POLICY_SCOPE_MISMATCH",
            "blueprint policy and activity spec must identify the same activity",
        )
    _dimensions, _variants, _templates = _validate_alias_graph(
        draft, request.blueprint_policy
    )
    _validate_source_relationships(draft, request)
    _validate_semantic_catalog(draft, request.blueprint_policy)

    dimension_ids = {
        item.dimension_alias: stable_id(
            "dimension",
            request.target_blueprint_id,
            request.target_blueprint_version,
            index,
        )
        for index, item in enumerate(draft.dimensions)
    }
    variant_ids: dict[str, str] = {}
    for dimension in draft.dimensions:
        children = [
            item
            for item in draft.evidence_variants
            if item.dimension_alias == dimension.dimension_alias
        ]
        for index, item in enumerate(children):
            variant_ids[item.variant_alias] = stable_id(
                "variant", dimension_ids[dimension.dimension_alias], index
            )
    template_ids = _template_ids(draft, request, variant_ids)
    justification_mode = (
        request.blueprint_policy.structured_justification_policy.mode
    )
    selected_ids = set(
        request.blueprint_policy.structured_justification_policy
        .selected_opportunity_template_ids
    )

    compiled_dimensions: list[m.BlueprintDimension] = []
    for dimension in draft.dimensions:
        compiled_variants: list[m.EvidenceVariant] = []
        for variant in (
            item
            for item in draft.evidence_variants
            if item.dimension_alias == dimension.dimension_alias
        ):
            compiled_templates: list[m.QuestionOpportunityTemplate] = []
            for template in (
                item
                for item in draft.question_opportunities
                if item.variant_alias == variant.variant_alias
            ):
                template_id = template_ids[template.template_alias]
                if justification_mode == m.StructuredJustificationMode.ALL:
                    justification_required = True
                elif justification_mode == m.StructuredJustificationMode.SELECTED:
                    justification_required = template_id in selected_ids
                else:
                    justification_required = False
                compiled_templates.append(
                    m.QuestionOpportunityTemplate(
                        opportunity_template_id=template_id,
                        cognitive_operation=template.cognitive_operation,
                        focus=template.focus,
                        observable=template.observable,
                        difficulty=template.difficulty,
                        target_minutes=template.target_minutes,
                        allowed_anchor_structures=list(
                            template.allowed_anchor_structures
                        ),
                        allowed_response_formats=list(
                            template.allowed_response_formats
                        ),
                        verification_potential=template.verification_potential,
                        minimum_quality=(
                            request.blueprint_policy.planning_policy
                            .minimum_opportunity_quality
                        ),
                        student_justification_required=justification_required,
                    )
                )
            compiled_variants.append(
                m.EvidenceVariant(
                    variant_id=variant_ids[variant.variant_alias],
                    name=variant.name,
                    description=variant.description,
                    evidence_requirement=variant.evidence_requirement.model_copy(
                        deep=True
                    ),
                    verification_potential=variant.verification_potential,
                    supported_operations=[
                        item.model_copy(deep=True)
                        for item in variant.supported_operations
                    ],
                    question_opportunities=compiled_templates,
                )
            )
        compiled_dimensions.append(
            m.BlueprintDimension(
                dimension_id=dimension_ids[dimension.dimension_alias],
                name=dimension.name,
                criterion_ids=list(dimension.criterion_ids),
                learning_outcome_ids=list(dimension.learning_outcome_ids),
                grading_weight=dimension.grading_weight,
                verification_priority=dimension.verification_priority,
                factors=dimension.factors.model_copy(deep=True),
                justification=dimension.justification,
                evidence_variants=compiled_variants,
            )
        )

    policy = request.blueprint_policy
    return m.AssessmentBlueprint(
        blueprint_id=request.target_blueprint_id,
        blueprint_version=request.target_blueprint_version,
        activity_id=request.activity_spec.activity_id,
        status=m.WorkflowStatus.READY,
        context_mode=policy.context_mode,
        dimensions=compiled_dimensions,
        assessment_constraints=m.AssessmentConstraints(
            question_count=policy.question_count,
            target_total_minutes=policy.target_total_minutes,
            allowed_response_formats=list(policy.allowed_response_formats),
            minimum_opportunity_quality=(
                policy.planning_policy.minimum_opportunity_quality
            ),
            max_reserve_opportunities=policy.planning_policy.max_reserve_opportunities,
            priority_criterion_ids=list(policy.priority_criterion_ids),
            required_criterion_ids=list(policy.required_criterion_ids),
            structured_justification_policy=(
                policy.structured_justification_policy.model_copy(deep=True)
            ),
        ),
        decision_ids=[item.decision_id for item in request.resolved_decisions],
        diagnostics=[],
        approved_by=None,
        approved_at=None,
    )


def _preflight_failure_code(preflight: m.BlueprintReviewPreflight) -> str:
    if not preflight.catalog_size_sufficient:
        return "P04_CATALOG_SIZE_INSUFFICIENT"
    if not preflight.time_feasible:
        return "P04_CATALOG_TIME_INFEASIBLE"
    if not preflight.justification_matrix_valid:
        return "P04_JUSTIFICATION_MATRIX_INFEASIBLE"
    if not preflight.source_coverage_complete:
        return "P04_SOURCE_COVERAGE_INCOMPLETE"
    if not preflight.format_feasible:
        return "P04_FORMAT_INFEASIBLE"
    return "P04_REQUIRED_COVERAGE_INFEASIBLE"


def preflight_compiled_blueprint(
    *,
    blueprint: m.AssessmentBlueprint,
    request: m.BlueprintBuildRequest,
) -> m.AssessmentBlueprint:
    """Derive P04 workflow status only after deterministic catalog preflight."""

    preflight = build_blueprint_review_preflight(
        blueprint=blueprint,
        activity_spec=request.activity_spec,
        rubric_spec=request.rubric_spec,
        blueprint_policy=request.blueprint_policy,
    )
    if preflight.catalog_plan_feasible:
        return blueprint.model_copy(
            update={
                "status": m.WorkflowStatus.READY,
                "diagnostics": [],
            },
            deep=True,
        )
    code = _preflight_failure_code(preflight)
    return blueprint.model_copy(
        update={
            "status": m.WorkflowStatus.NEEDS_REVIEW,
            "diagnostics": [
                diagnostic(
                    code,
                    "El catálogo compilado no admite un plan determinista bajo la policy vigente.",
                    details={
                        "catalog_size_sufficient": preflight.catalog_size_sufficient,
                        "catalog_plan_feasible": preflight.catalog_plan_feasible,
                        "time_feasible": preflight.time_feasible,
                        "format_feasible": preflight.format_feasible,
                        "justification_matrix_valid": (
                            preflight.justification_matrix_valid
                        ),
                        "source_coverage_complete": preflight.source_coverage_complete,
                        "question_count": request.blueprint_policy.question_count,
                        "target_total_minutes": (
                            request.blueprint_policy.target_total_minutes
                        ),
                        "required_criterion_ids": list(
                            request.blueprint_policy.required_criterion_ids
                        ),
                        "max_variants_per_dimension": (
                            request.blueprint_policy.max_variants_per_dimension
                        ),
                        "max_templates_per_variant": (
                            request.blueprint_policy.max_templates_per_variant
                        ),
                        "diagnostic_source": "DETERMINISTIC_BLUEPRINT_PREFLIGHT",
                        "correction_scope": "P04_BLUEPRINT_BUILD",
                    },
                )
            ],
        },
        deep=True,
    )


def compile_and_preflight_blueprint(
    *,
    draft: m.BlueprintModelDraft,
    request: m.BlueprintBuildRequest,
) -> m.AssessmentBlueprint:
    return preflight_compiled_blueprint(
        blueprint=compile_blueprint_model_draft(draft=draft, request=request),
        request=request,
    )


def _semantic_draft_from_compiled_blueprint(
    blueprint: m.AssessmentBlueprint,
) -> m.BlueprintModelDraft:
    """Project a canonical cache entry back to semantics for exact replay.

    The generated aliases are validation-local only.  Recompiling this
    projection proves that canonical IDs and every server-owned field are the
    output of the current compiler boundary rather than provider/cache data.
    """

    dimensions: list[m.BlueprintDimensionDraft] = []
    variants: list[m.EvidenceVariantDraft] = []
    templates: list[m.QuestionOpportunityTemplateDraft] = []
    variant_index = 0
    template_index = 0
    for dimension_index, dimension in enumerate(blueprint.dimensions, start=1):
        dimension_alias = f"D{dimension_index}"
        dimensions.append(
            m.BlueprintDimensionDraft(
                dimension_alias=dimension_alias,
                name=dimension.name,
                criterion_ids=list(dimension.criterion_ids),
                learning_outcome_ids=list(dimension.learning_outcome_ids),
                grading_weight=dimension.grading_weight,
                verification_priority=dimension.verification_priority,
                factors=dimension.factors.model_copy(deep=True),
                justification=dimension.justification,
            )
        )
        for variant in dimension.evidence_variants:
            variant_index += 1
            variant_alias = f"V{variant_index}"
            variants.append(
                m.EvidenceVariantDraft(
                    variant_alias=variant_alias,
                    dimension_alias=dimension_alias,
                    name=variant.name,
                    description=variant.description,
                    evidence_requirement=variant.evidence_requirement.model_copy(
                        deep=True
                    ),
                    verification_potential=variant.verification_potential,
                    supported_operations=[
                        item.model_copy(deep=True)
                        for item in variant.supported_operations
                    ],
                )
            )
            for template in variant.question_opportunities:
                template_index += 1
                templates.append(
                    m.QuestionOpportunityTemplateDraft(
                        template_alias=f"T{template_index}",
                        variant_alias=variant_alias,
                        cognitive_operation=template.cognitive_operation,
                        focus=template.focus,
                        observable=template.observable,
                        difficulty=template.difficulty,
                        target_minutes=template.target_minutes,
                        allowed_anchor_structures=list(
                            template.allowed_anchor_structures
                        ),
                        allowed_response_formats=list(
                            template.allowed_response_formats
                        ),
                        verification_potential=template.verification_potential,
                        justification_required=(
                            template.student_justification_required
                        ),
                    )
                )
    return m.BlueprintModelDraft(
        dimensions=dimensions,
        evidence_variants=variants,
        question_opportunities=templates,
    )


def validate_compiled_blueprint(
    *,
    blueprint: m.AssessmentBlueprint,
    request: m.BlueprintBuildRequest,
) -> None:
    """Recheck a cached canonical P04 result against current trusted inputs."""

    policy = request.blueprint_policy
    constraints = blueprint.assessment_constraints
    if (
        blueprint.blueprint_id != request.target_blueprint_id
        or blueprint.blueprint_version != request.target_blueprint_version
        or blueprint.activity_id != request.activity_spec.activity_id
        or blueprint.context_mode != policy.context_mode
        or blueprint.approved_by is not None
        or blueprint.approved_at is not None
    ):
        _fail(
            "BLUEPRINT_SERVER_FIELD_MISMATCH",
            "cached blueprint identity or approval fields differ from trusted input",
        )
    if (
        constraints.question_count != policy.question_count
        or constraints.target_total_minutes != policy.target_total_minutes
        or constraints.allowed_response_formats != policy.allowed_response_formats
        or constraints.minimum_opportunity_quality
        != policy.planning_policy.minimum_opportunity_quality
        or constraints.max_reserve_opportunities
        != policy.planning_policy.max_reserve_opportunities
        or constraints.priority_criterion_ids != policy.priority_criterion_ids
        or constraints.required_criterion_ids != policy.required_criterion_ids
        or constraints.structured_justification_policy
        != policy.structured_justification_policy
        or blueprint.decision_ids
        != [item.decision_id for item in request.resolved_decisions]
    ):
        _fail(
            "BLUEPRINT_SERVER_FIELD_MISMATCH",
            "cached blueprint policy fields differ from trusted input",
        )
    if any(
        len(dimension.evidence_variants) > policy.max_variants_per_dimension
        for dimension in blueprint.dimensions
    ) or any(
        len(variant.question_opportunities) > policy.max_templates_per_variant
        for dimension in blueprint.dimensions
        for variant in dimension.evidence_variants
    ):
        _fail(
            "BLUEPRINT_POLICY_LIMIT_EXCEEDED",
            "cached blueprint exceeds trusted catalog limits",
        )
    semantic_draft = _semantic_draft_from_compiled_blueprint(blueprint)
    replayed = compile_blueprint_model_draft(
        draft=semantic_draft,
        request=request,
    )
    canonical_without_derived_state = blueprint.model_copy(
        update={"status": m.WorkflowStatus.READY, "diagnostics": []},
        deep=True,
    )
    if canonical_without_derived_state != replayed:
        _fail(
            "BLUEPRINT_COMPILER_REPLAY_MISMATCH",
            "cached blueprint is not the exact current compiler output",
        )
    expected = preflight_compiled_blueprint(
        blueprint=replayed,
        request=request,
    )
    if blueprint.status != expected.status or blueprint.diagnostics != expected.diagnostics:
        _fail(
            "BLUEPRINT_DERIVED_STATE_MISMATCH",
            "cached blueprint status or diagnostics are not server-derived",
        )
