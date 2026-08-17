"""Stage-local Phase 8 fixtures built exclusively through product contracts.

These builders are evaluation scaffolding.  They are deliberately not golden
outputs for an earlier stage and never read semantic-oracle or audit files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .canonical import canonical_hash, stable_id
from .contracts import models as m
from .evidence_mapping import build_evidence_mapping_alias_envelope
from .guide_generation import (
    build_guide_alias_envelope,
    build_guide_approval_binding,
    guide_id_for_binding,
)
from .parsers.service import SafeParserService
from .planning import build_assessment_plan
from .question_generation import (
    anchor_fragment_for_evidence,
    build_question_alias_envelope,
)


P04_FIXTURE_BUILDER_VERSION = "semantic-benchmark-fixture-p04/1.1.1"
P06_FIXTURE_BUILDER_VERSION = "semantic-benchmark-fixture-p06/1.1.0"
PLANNER_FIXTURE_BUILDER_VERSION = "semantic-benchmark-fixture-planner/1.0.0"
P07_FIXTURE_BUILDER_VERSION = "semantic-benchmark-fixture-p07/1.1.0"
P09_FIXTURE_BUILDER_VERSION = "semantic-benchmark-fixture-p09/1.1.0"
P09_OPERATION_PROJECTION_VERSION = "p09-frozen-operation-projection/1.1.0"
P09_LOCATOR_RESOLVER_VERSION = "p09-exact-locator-resolver/1.0.0"

FIXED_INSTANT = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
BENCHMARK_TENANT_ID = "tenant_semantic_benchmark"
SCAFFOLD_MARKER = "BENCHMARK_SCAFFOLD_NOT_P01_P02_P03_GOLDEN"


def _text(unit: m.EvidenceUnit, fallback: str) -> str:
    value = (unit.content_text or "").strip()
    return value[:8_000] if value else fallback


def _parse_source(
    path: Path,
    *,
    role: m.ArtifactRole,
) -> tuple[m.ArtifactRef, tuple[m.EvidenceUnit, ...]]:
    parsed = SafeParserService().parse(
        path,
        tenant_id=BENCHMARK_TENANT_ID,
        source_role=role,
    )
    return parsed.artifact, parsed.evidence_units


def build_p04_fixture(
    *,
    corpus_root: Path,
    activity_path: str,
    activity_id: str,
) -> tuple[m.BlueprintBuildRequest, dict[str, int]]:
    """Project every parsed assignment/rubric unit into a P04 request.

    This benchmark-only projection deliberately performs no semantic grouping:
    every assignment unit becomes one ordered sourced requirement and every
    rubric unit becomes one ordered criterion.  The function has no oracle
    parameter and reads only the two paths named below.
    """

    activity_dir = corpus_root / activity_path
    assignment_artifact, assignment_units = _parse_source(
        activity_dir / "01_assignment.docx",
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    rubric_artifact, rubric_units = _parse_source(
        activity_dir / "02_rubric.docx",
        role=m.ArtifactRole.RUBRIC,
    )
    if not assignment_units or not rubric_units:
        raise ValueError("benchmark P04 sources must yield evidence")

    assignment_rows = list(assignment_units)
    rubric_rows = list(rubric_units)
    requirements = [
        m.SourcedStatement(
            statement_id=stable_id("source_requirement", activity_id, index),
            text=_text(unit, f"Bloque fuente de actividad {index}"),
            evidence_ids=[unit.evidence_id],
            certainty="EXPLICIT",
        )
        for index, unit in enumerate(assignment_rows, start=1)
    ]
    activity = m.ActivitySpec(
        activity_id=activity_id,
        status=m.WorkflowStatus.READY,
        learning_outcomes=[],
        expected_products=[],
        requirements=requirements,
        allowed_materials=[],
        prohibited_materials=[],
        contradictions=[],
        diagnostics=[],
    )

    criteria = [
        m.RubricCriterion(
            criterion_id=stable_id("criterion", activity_id, index),
            name=f"Bloque de rúbrica fuente {index}",
            description=_text(unit, f"Bloque explícito de rúbrica {index}"),
            evidence_ids=[unit.evidence_id],
            grading_weight=None,
            levels=[],
            observables=[],
            # The contract requires one of HIGH / MEDIUM / LOW / NOT_VERIFIABLE
            # and the source states none of them.  MEDIUM is the mid-point of
            # the scale, is applied uniformly so it carries no differential
            # signal, and keeps every criterion inside the verifiable-coverage
            # set exactly as HIGH or LOW would.
            verification_fit="MEDIUM",
            overlaps_with=[],
        )
        for index, unit in enumerate(rubric_rows, start=1)
    ]
    rubric = m.RubricSpec(
        activity_id=activity_id,
        status=m.WorkflowStatus.READY,
        scale_label=None,
        criteria=criteria,
        reported_weight_total=None,
        diagnostics=[],
    )
    planning_policy = m.AssessmentPlanningPolicy(
        policy_id=stable_id("planning_policy", activity_id),
        minimum_opportunity_quality=0.75,
        minimum_evidence_fit=0.70,
        max_reserve_opportunities=0,
    )
    policy = m.BlueprintPolicy(
        policy_id=stable_id("blueprint_policy", activity_id),
        activity_id=activity_id,
        context_mode=m.ContextMode.CLOSED,
        question_count=3,
        target_total_minutes=15,
        allowed_response_formats=[
            m.ResponseFormat.OPEN_SHORT,
            m.ResponseFormat.STRUCTURED_BULLETS,
        ],
        priority_criterion_ids=[],
        required_criterion_ids=[item.criterion_id for item in criteria],
        structured_justification_policy=m.StructuredJustificationPolicy(
            mode=m.StructuredJustificationMode.NOT_REQUIRED,
            selected_opportunity_template_ids=[],
        ),
        planning_policy=planning_policy,
        max_variants_per_dimension=3,
        max_templates_per_variant=4,
        max_local_regenerations=1,
        human_review_required=True,
    )
    request = m.BlueprintBuildRequest(
        target_blueprint_id=stable_id("blueprint", activity_id),
        target_blueprint_version=1,
        activity_spec=activity,
        rubric_spec=rubric,
        resolved_decisions=[],
        blueprint_policy=policy,
    )
    if assignment_artifact.sha256 == rubric_artifact.sha256:
        raise ValueError("assignment and rubric source boundaries must differ")
    coverage = {
        "assignment_units_total": len(assignment_units),
        "assignment_units_projected": len(requirements),
        "rubric_units_total": len(rubric_units),
        "rubric_units_projected": len(criteria),
    }
    if coverage["assignment_units_total"] != coverage["assignment_units_projected"]:
        raise ValueError("benchmark P04 assignment projection is incomplete")
    if coverage["rubric_units_total"] != coverage["rubric_units_projected"]:
        raise ValueError("benchmark P04 rubric projection is incomplete")
    return request, coverage


def parse_submission_bundle(
    *,
    corpus_root: Path,
    activity_path: str,
    activity_id: str,
    submission_id: str,
    artifact_refs: list[str],
) -> m.EvidenceBundle:
    """Group real parser output for exactly one neutral submission."""

    parser = SafeParserService()
    units: list[m.EvidenceUnit] = []
    artifact_hashes: list[str] = []
    for relative in artifact_refs:
        parsed = parser.parse(
            corpus_root / activity_path / relative,
            tenant_id=BENCHMARK_TENANT_ID,
            source_role=m.ArtifactRole.SUBMISSION,
            submission_id=submission_id,
        )
        units.extend(parsed.evidence_units)
        artifact_hashes.append(parsed.artifact.sha256)
    if not units:
        raise ValueError("benchmark submission must yield evidence")
    if any(item.submission_id != submission_id for item in units):
        raise ValueError("cross-submission parser output")
    return m.EvidenceBundle(
        bundle_id=stable_id(
            "bundle", activity_id, submission_id, sorted(artifact_hashes)
        ),
        tenant_id=BENCHMARK_TENANT_ID,
        activity_id=activity_id,
        submission_id=submission_id,
        context_mode=m.ContextMode.CLOSED,
        allowed_evidence_ids=[item.evidence_id for item in units],
        evidence_units=units,
        course_passages=[],
    )


def build_p06_fixture(
    *,
    route_fixture_id: str,
    model_visible_definition: dict[str, Any],
    bundle: m.EvidenceBundle,
) -> tuple[m.EvidenceMapRequest, m.EvidenceMappingAliasEnvelope]:
    """Build one source-grounded P06 route without using the P04 scaffold."""

    operation = m.CognitiveOperation(
        model_visible_definition["cognitive_operation"]
    )
    response_formats = [
        m.ResponseFormat(value)
        for value in model_visible_definition["response_formats"]
    ]
    requirement_value = model_visible_definition["evidence_requirement"]
    criterion_id = stable_id("criterion_p06_route", route_fixture_id)
    outcome_id = stable_id("outcome_p06_route", route_fixture_id)
    template = m.QuestionOpportunityTemplate(
        opportunity_template_id=stable_id("template_p06_route", route_fixture_id),
        cognitive_operation=operation,
        focus=model_visible_definition["focus"],
        observable=model_visible_definition["observable"],
        difficulty=m.DifficultyBand.MEDIUM,
        target_minutes=5,
        allowed_anchor_structures=[m.AnchorStructure.SINGLE_FRAGMENT],
        allowed_response_formats=response_formats,
        verification_potential=0.9,
        minimum_quality=0.75,
        student_justification_required=True,
    )
    variant = m.EvidenceVariant(
        variant_id=stable_id("variant_p06_route", route_fixture_id),
        name=model_visible_definition["construct"],
        description=model_visible_definition["focus"],
        evidence_requirement=m.EvidenceRequirement(
            allowed_modalities=[
                m.EvidenceModality(value)
                for value in requirement_value["allowed_modalities"]
            ],
            min_distinct_units=requirement_value["min_distinct_units"],
            min_extraction_confidence=0.70,
            min_alignment=0.65,
            cross_artifact_required=requirement_value[
                "cross_artifact_required"
            ],
            course_sources_allowed=False,
        ),
        verification_potential=0.9,
        supported_operations=[
            m.SupportedOperation(
                cognitive_operation=operation,
                support_strength=0.9,
                rationale=(
                    "La ruta define una relación verificable sobre evidencia "
                    "localizada de una sola submission."
                ),
            )
        ],
        question_opportunities=[template],
    )
    dimension = m.BlueprintDimension(
        dimension_id=stable_id("dimension_p06_route", route_fixture_id),
        name=model_visible_definition["construct"],
        criterion_ids=[criterion_id],
        learning_outcome_ids=[outcome_id],
        grading_weight=None,
        verification_priority=0.9,
        factors=m.VerificationFactors(
            learning_relevance=0.9,
            centrality=0.9,
            expected_evidence=0.9,
            discriminative_potential=0.9,
            auditability=0.9,
            short_response_observability=0.9,
        ),
        justification=model_visible_definition["focus"],
        evidence_variants=[variant],
    )
    planning_policy = m.AssessmentPlanningPolicy(
        policy_id=stable_id("planning_policy_p06_route", route_fixture_id),
        minimum_opportunity_quality=0.75,
        minimum_evidence_fit=0.70,
        max_reserve_opportunities=0,
    )
    approved_blueprint = m.AssessmentBlueprint(
        blueprint_id=stable_id("blueprint_p06_route", route_fixture_id),
        blueprint_version=1,
        activity_id=bundle.activity_id,
        status=m.WorkflowStatus.APPROVED,
        context_mode=m.ContextMode.CLOSED,
        dimensions=[dimension],
        assessment_constraints=m.AssessmentConstraints(
            question_count=1,
            target_total_minutes=5,
            allowed_response_formats=response_formats,
            minimum_opportunity_quality=0.75,
            max_reserve_opportunities=0,
            priority_criterion_ids=[],
            required_criterion_ids=[criterion_id],
            structured_justification_policy=m.StructuredJustificationPolicy(
                mode=m.StructuredJustificationMode.ALL,
                selected_opportunity_template_ids=[],
            ),
        ),
        decision_ids=[],
        diagnostics=[],
        approved_by="user_benchmark_teacher",
        approved_at=FIXED_INSTANT,
    )
    request = m.EvidenceMapRequest(
        blueprint=approved_blueprint,
        planning_policy=planning_policy,
        evidence_bundle=bundle,
    )
    return request, build_evidence_mapping_alias_envelope(request)


def build_planner_fixture(
    *,
    activity_id: str,
    submission_id: str,
    property_id: str,
    feasible: bool,
) -> tuple[m.EvidenceMapPatch, m.AssessmentBlueprint, m.AssessmentPlanningPolicy, m.AssessmentPlan]:
    """Build one controlled categorical mapping and run the real planner."""

    blueprint_id = stable_id("blueprint_planner", activity_id, property_id)
    dimension_id = stable_id("dimension_planner", activity_id, property_id)
    variant_id = stable_id("variant_planner", activity_id, property_id)
    criterion_id = stable_id("criterion_planner", activity_id, property_id)
    outcome_id = stable_id("outcome_planner", activity_id, property_id)
    count = 4 if feasible else 1
    templates = [
        m.QuestionOpportunityTemplate(
            opportunity_template_id=stable_id("template_planner", property_id, index),
            cognitive_operation=m.CognitiveOperation.RECONSTRUCT_REASONING,
            focus=f"Zona controlada {index}",
            observable=f"Relación controlada {index}",
            difficulty=m.DifficultyBand.MEDIUM,
            target_minutes=4,
            allowed_anchor_structures=[m.AnchorStructure.SINGLE_FRAGMENT],
            allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
            verification_potential=0.9,
            minimum_quality=0.75,
            student_justification_required=False,
        )
        for index in range(1, count + 1)
    ]
    variant = m.EvidenceVariant(
        variant_id=variant_id,
        name="Zonas controladas",
        description="Fixture categórico para factibilidad exacta.",
        evidence_requirement=m.EvidenceRequirement(
            allowed_modalities=[m.EvidenceModality.PARAGRAPH]
        ),
        verification_potential=0.9,
        supported_operations=[
            m.SupportedOperation(
                cognitive_operation=m.CognitiveOperation.RECONSTRUCT_REASONING,
                support_strength=0.9,
                rationale="La oportunidad controlada tiene apoyo local suficiente.",
            )
        ],
        question_opportunities=templates,
    )
    dimension = m.BlueprintDimension(
        dimension_id=dimension_id,
        name="Factibilidad controlada",
        criterion_ids=[criterion_id],
        learning_outcome_ids=[outcome_id],
        grading_weight=None,
        verification_priority=0.9,
        factors=m.VerificationFactors(
            learning_relevance=0.9,
            centrality=0.9,
            expected_evidence=0.9,
            discriminative_potential=0.9,
            auditability=0.9,
            short_response_observability=0.9,
        ),
        justification="Controla exclusivamente selección exacta y abstención.",
        evidence_variants=[variant],
    )
    policy = m.AssessmentPlanningPolicy(
        policy_id=stable_id("planner_case_policy", property_id),
        minimum_opportunity_quality=0.75,
        minimum_evidence_fit=0.70,
        maximum_evidence_overlap=0.50,
        max_reserve_opportunities=1,
    )
    blueprint = m.AssessmentBlueprint(
        blueprint_id=blueprint_id,
        blueprint_version=1,
        activity_id=activity_id,
        status=m.WorkflowStatus.APPROVED,
        context_mode=m.ContextMode.CLOSED,
        dimensions=[dimension],
        assessment_constraints=m.AssessmentConstraints(
            question_count=3,
            target_total_minutes=12,
            allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
            minimum_opportunity_quality=0.75,
            max_reserve_opportunities=1,
            priority_criterion_ids=[],
            required_criterion_ids=[],
            structured_justification_policy=m.StructuredJustificationPolicy(
                mode=m.StructuredJustificationMode.NOT_REQUIRED,
                selected_opportunity_template_ids=[],
            ),
        ),
        decision_ids=[],
        diagnostics=[],
        approved_by="user_benchmark_teacher",
        approved_at=FIXED_INSTANT,
    )
    opportunities = [
        m.QuestionOpportunity(
            opportunity_id=stable_id("opportunity_planner", property_id, index),
            opportunity_template_id=template.opportunity_template_id,
            submission_id=submission_id,
            dimension_id=dimension_id,
            variant_id=variant_id,
            evidence_ids=[stable_id("evidence_planner", property_id, index)],
            cognitive_operation=template.cognitive_operation,
            focus=template.focus,
            observable=template.observable,
            difficulty=template.difficulty,
            target_minutes=template.target_minutes,
            allowed_anchor_structures=list(template.allowed_anchor_structures),
            allowed_response_formats=list(template.allowed_response_formats),
            activity_priority=0.9,
            evidence_fit=1.0,
            opportunity_quality=0.9,
            student_justification_required=False,
            support_status=m.EvidenceSupportStatus.SUFFICIENT,
            support_type=m.EvidenceSupportType.DIRECT,
            support_description="Apoyo controlado suficiente.",
        )
        for index, template in enumerate(templates, start=1)
    ]
    mapping = m.EvidenceMapPatch(
        submission_id=submission_id,
        status="READY",
        claims=[],
        variant_matches=[],
        opportunities=opportunities,
        diagnostics=[],
    )
    plan = build_assessment_plan(mapping=mapping, blueprint=blueprint, policy=policy)
    expected = "READY" if feasible else "ASSESSMENT_PLAN_INFEASIBLE"
    if str(plan.status) != expected:
        raise ValueError(f"planner fixture expected {expected}, got {plan.status}")
    return mapping, blueprint, policy, plan


def build_p07_fixture(
    *,
    opportunity_fixture_id: str,
    model_visible_definition: dict[str, Any],
    bundle: m.EvidenceBundle,
) -> tuple[m.QuestionBuildRequest, m.QuestionAliasEnvelope]:
    """Build one P07 request from an explicit opportunity and exact support."""

    by_id = {item.evidence_id: item for item in bundle.evidence_units}
    support_ids = list(model_visible_definition["support_evidence_ids"])
    if len(support_ids) != len(set(support_ids)) or not support_ids:
        raise ValueError("P07 opportunity support must be non-empty and unique")
    try:
        support = [by_id[value] for value in support_ids]
    except KeyError as exc:
        raise ValueError("P07 opportunity support does not resolve exactly") from exc
    anchor_structures = [
        m.AnchorStructure(value)
        for value in model_visible_definition["allowed_anchor_structures"]
    ]
    if (
        m.AnchorStructure.CROSS_ARTIFACT in anchor_structures
        and len({item.artifact_id for item in support}) < 2
    ):
        raise ValueError("P07 cross-artifact opportunity has one support artifact")
    operation = m.CognitiveOperation(model_visible_definition["operation"])
    response_format = m.ResponseFormat(model_visible_definition["response_format"])
    opportunity = m.QuestionOpportunity(
        opportunity_id=stable_id("opportunity_p07", opportunity_fixture_id),
        opportunity_template_id=stable_id("template_p07", opportunity_fixture_id),
        submission_id=bundle.submission_id,
        dimension_id=stable_id("dimension_p07", opportunity_fixture_id),
        variant_id=stable_id("variant_p07", opportunity_fixture_id),
        evidence_ids=support_ids,
        cognitive_operation=operation,
        focus=model_visible_definition["focus"],
        observable=model_visible_definition["observable"],
        difficulty=m.DifficultyBand(model_visible_definition["difficulty"]),
        target_minutes=model_visible_definition["target_minutes"],
        allowed_anchor_structures=anchor_structures,
        allowed_response_formats=[response_format],
        activity_priority=0.9,
        evidence_fit=1.0,
        opportunity_quality=0.9,
        student_justification_required=model_visible_definition[
            "student_justification_required"
        ],
        support_status=m.EvidenceSupportStatus.SUFFICIENT,
        support_type=(
            m.EvidenceSupportType.COMPOSITE
            if len(support) > 1
            else m.EvidenceSupportType.DIRECT
        ),
        support_description="Soporte stage-local derivado de EvidenceUnits reales.",
    )
    plan = m.AssessmentPlan(
        plan_id=stable_id("plan_p07", opportunity_fixture_id),
        submission_id=bundle.submission_id,
        blueprint_id=stable_id("blueprint_p07", opportunity_fixture_id),
        blueprint_version=1,
        status="READY",
        question_count=1,
        selected_opportunity_ids=[opportunity.opportunity_id],
        reserve_opportunity_ids=[],
        estimated_total_minutes=model_visible_definition["target_minutes"],
        diagnostics=[],
    )
    request = m.QuestionBuildRequest(
        target_candidate_id=stable_id("candidate_p07", opportunity_fixture_id),
        plan=plan,
        opportunity=opportunity,
        evidence_bundle=bundle,
        generation_policy=m.QuestionGenerationPolicy(
            policy_id=stable_id("generation_policy", opportunity_fixture_id),
            max_anchor_fragments=4,
            max_course_passages=0,
            require_accessible_alternative=True,
            max_local_regenerations=1,
        ),
        avoid=[],
    )
    return request, build_question_alias_envelope(request)


_P09_OPERATION_MAP = {
    "RECONSTRUCT_QUANTITATIVE_CHAIN": m.CognitiveOperation.RECONSTRUCT_REASONING,
    "ADJUDICATE_ALTERNATIVES_WITH_EVIDENCE": m.CognitiveOperation.JUSTIFY_DECISION,
    "SOLVE_BUDGET_BOUND": m.CognitiveOperation.RECONSTRUCT_REASONING,
    "CROSS_ARTIFACT_ADJUDICATION": m.CognitiveOperation.CONNECT_INTERNAL,
    "TRACE_DEDUPLICATION_SEMANTICS": m.CognitiveOperation.TRACE_FLOW,
    "ADJUDICATE_OUTPUT_ORDER": m.CognitiveOperation.JUSTIFY_DECISION,
    "INTERPRET_WITH_ALTERNATIVES": m.CognitiveOperation.INTERPRET_REPRESENTATION,
    "ADJUDICATE_HISTORICAL_EXPLANATION": m.CognitiveOperation.CRITIQUE_LIMITATION,
    "BOUND_CANNOT_INFER": m.CognitiveOperation.CRITIQUE_LIMITATION,
    "APPLY_PRIVACY_MINIMIZATION": m.CognitiveOperation.JUSTIFY_DECISION,
    "SPECIFY_MINIMUM_EVIDENCE": m.CognitiveOperation.IDENTIFY_DEPENDENCY,
}


def build_p09_fixture(
    *,
    fixture: dict[str, Any],
    locator_bindings: dict[str, Any],
    bundle: m.EvidenceBundle,
    artifact_refs: list[str],
    difficulty: str,
    assignment_hash: str,
    rubric_hash: str,
) -> tuple[
    m.GuideBuildRequest,
    m.GuideAliasEnvelope,
    dict[str, str],
    list[dict[str, Any]],
]:
    """Project only frozen ``questions`` into a canonical approved P09 request."""

    units_by_artifact_id: dict[str, list[m.EvidenceUnit]] = {}
    for unit in bundle.evidence_units:
        units_by_artifact_id.setdefault(unit.artifact_id, []).append(unit)
    ordered_artifact_ids = list(units_by_artifact_id)
    filename_to_units: dict[str, list[m.EvidenceUnit]] = {}
    for relative, artifact_id in zip(artifact_refs, ordered_artifact_ids, strict=True):
        filename_to_units[Path(relative).name] = units_by_artifact_id[artifact_id]
    binding_by_question = {
        item["question_fixture_id"]: item
        for item in locator_bindings["questions"]
    }
    if set(binding_by_question) != {
        item["question_fixture_id"] for item in fixture["questions"]
    }:
        raise ValueError("P09 locator binding question coverage mismatch")
    level = {
        "SIMPLE": m.DifficultyBand.LOW,
        "INTERMEDIATE": m.DifficultyBand.MEDIUM,
        "DIFFICULT": m.DifficultyBand.HIGH,
    }[difficulty]
    questions: list[m.SelectedQuestion] = []
    operation_projection: dict[str, str] = {}
    integrity_rows: list[dict[str, Any]] = []
    for index, row in enumerate(fixture["questions"], start=1):
        raw_operation = row["cognitive_operation"]
        operation = _P09_OPERATION_MAP[raw_operation]
        operation_projection[raw_operation] = operation.value
        question_binding = binding_by_question[row["question_fixture_id"]]
        if [item["declared_ref"] for item in question_binding["support_refs"]] != row[
            "support_refs"
        ]:
            raise ValueError("P09 declared support refs differ from exact bindings")
        if [
            item["declared_ref"]
            for item in question_binding["visible_anchor_refs"]
        ] != row["visible_anchor_refs"]:
            raise ValueError("P09 declared visible refs differ from exact bindings")

        def resolve_submission_rows(
            values: list[dict[str, Any]], *, visible_anchor: bool
        ) -> list[m.EvidenceUnit]:
            resolved: list[m.EvidenceUnit] = []
            for value in values:
                role = value["role"]
                if role == "SOURCE_CONTEXT":
                    if visible_anchor:
                        raise ValueError("P09 visible anchor cannot use source context")
                    continue
                if role != "SUBMISSION_SUPPORT":
                    raise ValueError("P09 locator binding role is invalid")
                filename = Path(value["declared_ref"].split("#", 1)[0]).name
                file_units = {
                    item.evidence_id: item
                    for item in filename_to_units.get(filename, [])
                }
                if not file_units:
                    raise ValueError("BENCHMARK_FIXTURE_LOCATOR_UNRESOLVED")
                for expected in value["resolved_units"]:
                    unit = file_units.get(expected["evidence_id"])
                    if unit is None:
                        raise ValueError("BENCHMARK_FIXTURE_LOCATOR_UNRESOLVED")
                    if (
                        unit.normalized_hash != expected["normalized_hash"]
                        or unit.locator.model_dump(
                            mode="json", exclude_none=True
                        )
                        != expected["locator"]
                    ):
                        raise ValueError("BENCHMARK_FIXTURE_LOCATOR_AMBIGUOUS")
                    resolved.append(unit)
            unique = {item.evidence_id: item for item in resolved}
            return list(unique.values())

        support = resolve_submission_rows(
            question_binding["support_refs"], visible_anchor=False
        )
        visible = resolve_submission_rows(
            question_binding["visible_anchor_refs"], visible_anchor=True
        )
        if not support or not visible:
            raise ValueError("BENCHMARK_FIXTURE_LOCATOR_UNRESOLVED")
        support_ids = {item.evidence_id for item in support}
        if not {item.evidence_id for item in visible}.issubset(support_ids):
            raise ValueError("P09 visible anchor is outside exact support")
        if len(visible) > 8:
            raise ValueError("P09 exact visible locator exceeds anchor contract")
        integrity_rows.append(
            {
                "question_fixture_id": row["question_fixture_id"],
                "support_refs_declared": list(row["support_refs"]),
                "support_evidence_ids_resolved": [
                    item.evidence_id for item in support
                ],
                "visible_refs_declared": list(row["visible_anchor_refs"]),
                "visible_evidence_ids_resolved": [
                    item.evidence_id for item in visible
                ],
                "unresolved": 0,
                "ambiguous": 0,
                "visible_subset_support": True,
            }
        )
        question_id = stable_id("question_p09", fixture["fixture_id"], index)
        observables = [
            m.ObservableElement(
                element_id=stable_id("observable_p09", question_id, obs_index),
                description=description,
                evidence_ids=[item.evidence_id for item in support],
                source_ids=[],
                required_for_level_2=True,
            )
            for obs_index, description in enumerate(row["core_observables"], start=1)
        ]
        questions.append(
            m.SelectedQuestion(
                question_id=question_id,
                source_candidate_id=stable_id("candidate_p09", fixture["fixture_id"], index),
                opportunity_id=stable_id("opportunity_p09", fixture["fixture_id"], index),
                opportunity_template_id=stable_id("template_p09", fixture["fixture_id"], index),
                dimension_id=stable_id("dimension_p09", fixture["activity_id"], index),
                variant_id=stable_id("variant_p09", fixture["activity_id"], index),
                cognitive_operation=operation,
                response_format=m.ResponseFormat.STRUCTURED_BULLETS,
                difficulty=level,
                estimated_minutes=5,
                question_text=row["question_text"],
                anchor=m.Anchor(
                    anchor_id=stable_id("anchor_p09", fixture["fixture_id"], index),
                    structure=(
                        m.AnchorStructure.CROSS_ARTIFACT
                        if len({item.artifact_id for item in visible}) > 1
                        else m.AnchorStructure.SINGLE_FRAGMENT
                    ),
                    fragments=[anchor_fragment_for_evidence(item) for item in visible],
                    student_facing_label=None,
                    self_containment_score=1.0,
                    answer_leakage_risk=0.0,
                ),
                evidence_ids=[item.evidence_id for item in support],
                course_source_ids=[],
                citations=[],
                choices=[],
                student_justification_required=True,
                preliminary_guide=m.GuideDraft(
                    purpose="Evaluar el observable fijo sin ampliar la evidencia aprobada.",
                    observable_elements=observables,
                    acceptance_conditions=[],
                    acceptable_alternatives=list(row["acceptable_alternatives"]),
                    misconceptions=list(row["misconceptions"]),
                    levels=[],
                    cannot_infer=[],
                    semantic_uncertainties=[],
                ),
                semantic_uncertainties=[],
                planning_score=1.0,
            )
        )
    for source_hash in (assignment_hash, rubric_hash):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", source_hash):
            raise ValueError("P09 source lineage requires canonical SHA-256 values")
    assessment = m.Assessment(
        assessment_id=stable_id("assessment_p09", fixture["fixture_id"]),
        tenant_id=BENCHMARK_TENANT_ID,
        activity_id=fixture["activity_id"],
        submission_id=fixture["submission_id"],
        subject_ref="subject_synthetic_benchmark",
        status=m.WorkflowStatus.APPROVED,
        context_mode=m.ContextMode.CLOSED,
        assessment_plan_id=stable_id("plan_p09", fixture["fixture_id"]),
        question_count=len(questions),
        questions=questions,
        coverage=[],
        structured_justification=m.StructuredJustificationSummary(
            mode=m.StructuredJustificationMode.ALL,
            required_question_ids=[item.question_id for item in questions],
            limited_evidence_notice_required=False,
        ),
        diagnostics=[],
        lineage=m.Lineage(
            assignment_prompt_hashes=[assignment_hash],
            rubric_hashes=[rubric_hash],
            submission_hashes=sorted({item.artifact_hash for item in bundle.evidence_units}),
            blueprint_id=stable_id("blueprint", fixture["activity_id"]),
            blueprint_version=1,
            parser_versions={"submission": "stage2-parser/2.0.0"},
            prompt_versions={"P09": P09_FIXTURE_BUILDER_VERSION},
            model_snapshots={"P09": "UNSET"},
            policy_hash=canonical_hash({"policy": "benchmark-p09-input"}),
            planner_version="stage2-planner/3.0.0",
            renderer_version="not-invoked",
        ),
        created_at=FIXED_INSTANT,
        approved_by="user_benchmark_teacher",
        approved_at=FIXED_INSTANT,
    )
    etag = f'"{canonical_hash(assessment.model_dump(mode="json"))}"'
    binding = build_guide_approval_binding(
        assessment=assessment,
        assessment_version=1,
        assessment_etag=etag,
        approval_event_id=stable_id("approval_event", fixture["fixture_id"]),
    )
    request = m.GuideBuildRequest(
        guide_id=guide_id_for_binding(binding),
        assessment=assessment,
        binding=binding,
        evidence_bundle=bundle,
    )
    return (
        request,
        build_guide_alias_envelope(request),
        operation_projection,
        integrity_rows,
    )
