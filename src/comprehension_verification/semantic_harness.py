"""Offline, document-shaped semantic qualification fixtures for P04-P09.

No provider adapter, route, secret, or model is imported or constructed here.
The module validates reviewed goldens over product contracts, parsers,
validators, planner, and deterministic assessment assembly only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from .canonical import canonical_hash, stable_id
from .contracts import models as m
from .model_gateway.registry import prompt_spec
from .parsers.service import DOCX_MEDIA_TYPE, PARSER_VERSION, ParsedArtifact, SafeParserService
from .planning import PLANNER_VERSION, build_assessment_plan
from .qualification_semantics import (
    CheckpointAssessment,
    CheckpointClass,
    ContractualAdherence,
    OracleValidity,
    SemanticInterpretation,
    aggregate_causal_classification,
    classify_checkpoint,
)
from .rehearsal import (
    P05_GOLDEN_FIXTURE_PATH,
    QUALIFICATION_EXPECTED_PROVIDER_REQUESTS,
    _p05_review_from_versioned_semantic_fixture,
    blueprint_review_is_approvable,
    run_offline_convergence_sync,
)
from .validation import (
    build_blueprint_review_preflight,
    validate_assessment_plan,
    validate_blueprint_review_preflight_checks,
    validate_evaluation_guide,
    validate_evidence_map,
    validate_generation_result,
    validate_review_result,
)
from .web.workflows import (
    ASSEMBLER_VERSION,
    Stage1Service,
    assemble_assessment_snapshot,
    selected_question_from_candidate,
)


ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_FIXTURE_PATH = (
    ROOT / "tests/fixtures/openai_evals/v3/semantic_qualification_pack.json"
)
FROZEN_PRODUCT_BOUNDARY_PATH = (
    ROOT / "tests/fixtures/openai_evals/v3/frozen_product_boundary.json"
)
SEMANTIC_REHEARSAL_VERSION = "stage2-semantic-harness-rehearsal/1.1.0"
SEMANTIC_REPORT_VERSION = "stage2-semantic-harness-report/1.1.0"
TENANT_ID = "tenant_semantic_harness"
ACTIVITY_ID = "act_demo"
SUFFICIENT_SUBMISSION_ID = "submission_cache_sufficient"
INSUFFICIENT_SUBMISSION_ID = "submission_cache_insufficient"
FIXED_TIME = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
P04_P09_PROMPT_IDS = (
    "P04_BLUEPRINT_BUILD_V1",
    "P05_BLUEPRINT_REVIEW_V1",
    "P06_EVIDENCE_MAP_V1",
    "P07_QUESTION_BUILD_V1",
    "P08_QUESTION_REVIEW_V1",
    "P09_GUIDE_BUILD_V1",
)


@dataclass(frozen=True, slots=True)
class CanonicalArtifacts:
    assignment: ParsedArtifact
    rubric: ParsedArtifact
    sufficient: ParsedArtifact
    insufficient: ParsedArtifact


@dataclass(frozen=True, slots=True)
class SemanticCheckpoints:
    p04_request: m.BlueprintBuildRequest
    blueprint: m.AssessmentBlueprint
    p05_request: m.BlueprintReviewRequest
    p05_review: m.BlueprintReview
    p05_negative_request: m.BlueprintReviewRequest
    p05_negative_review: m.BlueprintReview
    p06_request: m.EvidenceMapRequest
    mapping: m.EvidenceMapPatch
    plan: m.AssessmentPlan
    p07_positive_request: m.QuestionBuildRequest
    p07_positive_result: m.QuestionGenerationResult
    p07_negative_request: m.QuestionBuildRequest
    p07_negative_result: m.QuestionGenerationResult
    p08_positive_request: m.QuestionReviewRequest
    p08_positive_result: m.QuestionReviewResult
    p08_negative_request: m.QuestionReviewRequest
    p08_negative_result: m.QuestionReviewResult
    p09_request: m.GuideBuildRequest
    p09_guide: m.EvaluationGuide
    sufficient_bundle: m.EvidenceBundle
    insufficient_bundle: m.EvidenceBundle
    negative_mapping: m.EvidenceMapPatch
    negative_plan: m.AssessmentPlan
    artifacts: CanonicalArtifacts


@dataclass(frozen=True, slots=True)
class CanonicalDocumentChainInputs:
    """Product-derived inputs allowed before the first integrated LLM stage."""

    p04_request: m.BlueprintBuildRequest
    policy: m.BlueprintPolicy
    artifacts: CanonicalArtifacts

    @property
    def source_artifact_hashes(self) -> dict[str, str]:
        return {
            "assignment": self.artifacts.assignment.artifact.sha256,
            "rubric": self.artifacts.rubric.artifact.sha256,
            "submission": self.artifacts.sufficient.artifact.sha256,
        }


def semantic_checkpoint_requests(
    checkpoints: SemanticCheckpoints,
) -> tuple[tuple[str, str, m.StrictModel], ...]:
    """Return the reviewed semantic sweep in its fixed execution order."""

    return (
        (
            "P04_CANONICAL_POSITIVE",
            "P04_BLUEPRINT_BUILD_V1",
            checkpoints.p04_request,
        ),
        (
            "P05_CANONICAL_POSITIVE",
            "P05_BLUEPRINT_REVIEW_V1",
            checkpoints.p05_request,
        ),
        (
            "P05_PLAN_FEASIBILITY_NEGATIVE",
            "P05_BLUEPRINT_REVIEW_V1",
            checkpoints.p05_negative_request,
        ),
        (
            "P06_CANONICAL_POSITIVE",
            "P06_EVIDENCE_MAP_V1",
            checkpoints.p06_request,
        ),
        (
            "P07_CANONICAL_POSITIVE",
            "P07_QUESTION_BUILD_V1",
            checkpoints.p07_positive_request,
        ),
        (
            "P07_INSUFFICIENT_NEGATIVE",
            "P07_QUESTION_BUILD_V1",
            checkpoints.p07_negative_request,
        ),
        (
            "P08_CANONICAL_POSITIVE",
            "P08_QUESTION_REVIEW_V1",
            checkpoints.p08_positive_request,
        ),
        (
            "P08_UNANSWERABLE_NEGATIVE",
            "P08_QUESTION_REVIEW_V1",
            checkpoints.p08_negative_request,
        ),
        (
            "P09_CANONICAL_POSITIVE",
            "P09_GUIDE_BUILD_V1",
            checkpoints.p09_request,
        ),
    )


def load_semantic_fixture() -> dict[str, Any]:
    raw = json.loads(SEMANTIC_FIXTURE_PATH.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "stage2-semantic-qualification-pack/1.0.0":
        raise ValueError("semantic fixture version is not approved")
    if raw.get("classification") != "SYNTHETIC_ONLY_NO_STUDENT_DATA":
        raise ValueError("semantic fixture must be synthetic-only")
    if raw.get("provider_response_used_as_target") is not False:
        raise ValueError("semantic fixture cannot target a provider response")
    authorship = raw.get("review_authorship") or {}
    if (
        authorship.get("authoring_class")
        != "CODEX_AUTHORED_SEMANTIC_REVIEW"
        or authorship.get("independent_review_status")
        != "USER_SUPPLIED_INDEPENDENT_REVIEW_FINDINGS"
        or authorship.get("human_ratification") is not None
    ):
        raise ValueError("semantic review provenance is not truthful")
    amendment = raw.get("provenance_amendment") or {}
    if (
        amendment.get("amendment_id")
        != "SR-PROVENANCE-AMENDMENT-001"
        or amendment.get("preserve_prior_review_hashes") is not True
    ):
        raise ValueError("semantic review provenance amendment is missing")
    return cast(dict[str, Any], raw)


def frozen_product_boundary_proof() -> dict[str, Any]:
    frozen = json.loads(
        FROZEN_PRODUCT_BOUNDARY_PATH.read_text(encoding="utf-8")
    )
    actual_files = {
        path: sha256((ROOT / path).read_bytes()).hexdigest()
        for path in frozen["source_file_sha256"]
    }
    if actual_files != frozen["source_file_sha256"]:
        raise ValueError("frozen product source boundary changed")
    actual_prompts = {
        prompt_id: {
            "version": prompt_spec(prompt_id).prompt_version,
            "hash": prompt_spec(prompt_id).prompt_hash,
        }
        for prompt_id in frozen["prompts"]
    }
    if actual_prompts != frozen["prompts"]:
        raise ValueError("frozen prompt boundary changed")
    policy = m.QuestionValidationPolicy(policy_id="frozen_boundary_probe")
    actual_thresholds = {
        key: getattr(policy, key)
        for key in frozen["question_validation_thresholds"]
    }
    if actual_thresholds != frozen["question_validation_thresholds"]:
        raise ValueError("frozen validation thresholds changed")
    return {
        "baseline_git_sha": frozen["baseline_git_sha"],
        "manifest_hash": canonical_hash(frozen),
        "source_file_sha256": actual_files,
        "prompts": actual_prompts,
        "question_validation_thresholds": actual_thresholds,
        "component_versions": frozen["component_versions"],
    }


def _parse_artifacts(fixture: dict[str, Any]) -> CanonicalArtifacts:
    parser_probe = SimpleNamespace(
        settings=SimpleNamespace(
            environment="test",
            parser_timeout_seconds=30,
        ),
        parser=SafeParserService(require_libmagic=False),
    )
    parsed: dict[str, ParsedArtifact] = {}
    for descriptor in fixture["artifacts"]:
        role = m.ArtifactRole(descriptor["role"])
        path = ROOT / descriptor["path"]
        artifact_row = SimpleNamespace(
            id=f"artifact_semantic_{descriptor['artifact_key']}",
            tenant_id=TENANT_ID,
            activity_id=ACTIVITY_ID,
            submission_id=descriptor.get("submission_id"),
            role=role.value,
            filename=path.name,
            declared_media_type=DOCX_MEDIA_TYPE,
        )
        artifact = Stage1Service._parse_bytes(
            cast(Any, parser_probe),
            cast(Any, artifact_row),
            path.read_bytes(),
        )
        if artifact.artifact.sha256 != descriptor["sha256"]:
            raise ValueError(f"artifact hash drift: {descriptor['artifact_key']}")
        if artifact.artifact.parser_id != "stage2-docx-structural":
            raise ValueError("canonical document did not use the product DOCX parser")
        parsed[descriptor["artifact_key"]] = artifact
    return CanonicalArtifacts(
        assignment=parsed["assignment"],
        rubric=parsed["rubric"],
        sufficient=parsed["submission_sufficient"],
        insufficient=parsed["submission_insufficient"],
    )


def _unit_by_exact_text(
    artifact: ParsedArtifact,
    text: str,
) -> m.EvidenceUnit:
    matches = [unit for unit in artifact.evidence_units if unit.content_text == text]
    if len(matches) != 1:
        raise ValueError("semantic evidence selector must resolve exactly once")
    return matches[0]


class _CapturedProductBundle(RuntimeError):
    def __init__(self, bundle: m.EvidenceBundle) -> None:
        self.bundle = bundle
        super().__init__("product submission boundary reached")


class _NoopProductSession:
    def __enter__(self) -> "_NoopProductSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def merge(self, _row: object) -> None:
        return None


class _ProductBoundaryRepositoryProbe:
    def __init__(
        self,
        *,
        submission: SimpleNamespace,
        activity: SimpleNamespace,
        artifact: SimpleNamespace,
        parsed: ParsedArtifact,
    ) -> None:
        self._submission = submission
        self._activity = activity
        self._artifact = artifact
        self._cached_parse = SimpleNamespace(
            output={
                "evidence_units": [
                    unit.model_dump(mode="json")
                    for unit in parsed.evidence_units
                ]
            }
        )

    def scoped(
        self,
        model: type[object],
        _row_id: str,
        _tenant_id: str,
    ) -> SimpleNamespace:
        if model.__name__ == "SubmissionRow":
            return self._submission
        if model.__name__ == "ActivityRow":
            return self._activity
        raise AssertionError(f"unexpected product boundary model: {model.__name__}")

    def artifacts_for(self, **_kwargs: object) -> list[SimpleNamespace]:
        return [self._artifact]

    def stage_by_key(self, **_kwargs: object) -> SimpleNamespace:
        return self._cached_parse

    def session(self) -> _NoopProductSession:
        return _NoopProductSession()


class _ProductSubmissionBoundaryProbe:
    def __init__(
        self,
        *,
        repository: _ProductBoundaryRepositoryProbe,
        blueprint: m.AssessmentBlueprint,
    ) -> None:
        self.repository = repository
        self.settings = SimpleNamespace(require_libmagic=False)
        self._blueprint = blueprint

    def _approved_blueprint(self, **_kwargs: object) -> tuple[None, m.AssessmentBlueprint]:
        return None, self._blueprint

    def _set_submission(self, *_args: object) -> None:
        return None

    def _stage_policy_hash(self, _job: object) -> str:
        return "sha256:" + "0" * 64

    def _record_stage_reuse(self, *_args: object) -> None:
        return None

    def _cancellation_checkpoint(self, _job: object) -> None:
        return None

    async def _gateway_stage(
        self,
        _job: object,
        prompt_id: str,
        request: m.StrictModel,
        _output_model: type[m.StrictModel],
        *,
        cache_suffix: str = "",
    ) -> m.StrictModel:
        del cache_suffix
        if prompt_id != "P06_EVIDENCE_MAP_V1":
            raise AssertionError(f"unexpected product boundary stage: {prompt_id}")
        p06_request = m.EvidenceMapRequest.model_validate(
            request.model_dump(mode="json")
        )
        raise _CapturedProductBundle(p06_request.evidence_bundle)


def _bundle_from_product_submission_boundary(
    parsed: ParsedArtifact,
    *,
    submission_id: str,
    blueprint: m.AssessmentBlueprint,
    policy: m.BlueprintPolicy,
) -> m.EvidenceBundle:
    """Capture the bundle built by the frozen product workflow before P06."""

    submission = SimpleNamespace(
        id=submission_id,
        activity_id=ACTIVITY_ID,
        blueprint_version=blueprint.blueprint_version,
    )
    activity = SimpleNamespace(
        id=ACTIVITY_ID,
        blueprint_policy=policy.model_dump(mode="json"),
    )
    artifact = SimpleNamespace(
        id=parsed.artifact.artifact_id,
        sha256=parsed.artifact.sha256,
        byte_size=parsed.artifact.byte_size,
        declared_media_type=DOCX_MEDIA_TYPE,
        media_type=parsed.artifact.media_type,
    )
    repository = _ProductBoundaryRepositoryProbe(
        submission=submission,
        activity=activity,
        artifact=artifact,
        parsed=parsed,
    )
    probe = _ProductSubmissionBoundaryProbe(
        repository=repository,
        blueprint=blueprint,
    )
    job = SimpleNamespace(
        id=f"job_semantic_{submission_id}",
        aggregate_id=submission_id,
        tenant_id=TENANT_ID,
    )
    coroutine = Stage1Service._run_submission_pipeline(
        cast(Any, probe),
        cast(Any, job),
    )
    try:
        coroutine.send(None)
    except _CapturedProductBundle as captured:
        return captured.bundle
    finally:
        coroutine.close()
    raise AssertionError("product submission boundary did not reach P06")


def _source_models(
    fixture: dict[str, Any],
    artifacts: CanonicalArtifacts,
) -> tuple[m.ActivitySpec, m.RubricSpec]:
    selectors = fixture["source_selectors"]
    outcome = _unit_by_exact_text(
        artifacts.assignment, selectors["assignment_outcome"]
    )
    requirement = _unit_by_exact_text(
        artifacts.assignment, selectors["assignment_requirement"]
    )
    product = _unit_by_exact_text(
        artifacts.assignment, selectors["assignment_product"]
    )
    criterion = _unit_by_exact_text(
        artifacts.rubric, selectors["rubric_criterion"]
    )
    weight = _unit_by_exact_text(artifacts.rubric, selectors["rubric_weight"])
    levels = [
        (
            "level_3",
            "Completo",
            3,
            _unit_by_exact_text(artifacts.rubric, selectors["rubric_level_3"]),
        ),
        (
            "level_2",
            "Suficiente",
            2,
            _unit_by_exact_text(artifacts.rubric, selectors["rubric_level_2"]),
        ),
        (
            "level_1",
            "Parcial",
            1,
            _unit_by_exact_text(artifacts.rubric, selectors["rubric_level_1"]),
        ),
        (
            "level_0",
            "No evidenciado",
            0,
            _unit_by_exact_text(artifacts.rubric, selectors["rubric_level_0"]),
        ),
    ]
    activity = m.ActivitySpec(
        activity_id=ACTIVITY_ID,
        status=m.WorkflowStatus.READY,
        learning_outcomes=[
            m.SourcedStatement(
                statement_id="outcome_1",
                text=(
                    "Explicar cómo un cambio en la fuente invalida la entrada "
                    "almacenada y fuerza un recálculo verificable."
                ),
                evidence_ids=[outcome.evidence_id],
                certainty="EXPLICIT",
            )
        ],
        expected_products=[
            m.SourcedStatement(
                statement_id="product_1",
                text=(
                    "Un párrafo y una traza mínima que conecten invalidación "
                    "y resultado posterior al cambio."
                ),
                evidence_ids=[product.evidence_id],
                certainty="EXPLICIT",
            )
        ],
        requirements=[
            m.SourcedStatement(
                statement_id="requirement_1",
                text=(
                    "Justificar por qué reutilizar la entrada anterior podría "
                    "devolver un resultado obsoleto."
                ),
                evidence_ids=[requirement.evidence_id],
                certainty="EXPLICIT",
            )
        ],
        allowed_materials=[],
        prohibited_materials=[],
        contradictions=[],
        diagnostics=[],
    )
    rubric = m.RubricSpec(
        activity_id=ACTIVITY_ID,
        status=m.WorkflowStatus.READY,
        scale_label="0-3",
        criteria=[
            m.RubricCriterion(
                criterion_id="criterion_1",
                name="Explicación causal de invalidación de caché",
                description=criterion.content_text,
                evidence_ids=[criterion.evidence_id, weight.evidence_id],
                grading_weight=1.0,
                levels=[
                    m.RubricLevel(
                        level_id=level_id,
                        label=label,
                        ordinal=ordinal,
                        descriptor=unit.content_text,
                        evidence_ids=[unit.evidence_id],
                    )
                    for level_id, label, ordinal, unit in levels
                ],
                observables=[
                    "Ordena la secuencia causal completa.",
                    "Vincula invalidación con prevención de resultados obsoletos.",
                    "Distingue lo sustentado de lo que no puede inferirse.",
                ],
                verification_fit="HIGH",
                overlaps_with=[],
            )
        ],
        reported_weight_total=1.0,
        diagnostics=[],
    )
    return activity, rubric


def build_canonical_document_chain_inputs() -> CanonicalDocumentChainInputs:
    """Derive the integrated-chain sources from DOCX through product parsing."""

    fixture = load_semantic_fixture()
    artifacts = _parse_artifacts(fixture)
    activity, rubric = _source_models(fixture, artifacts)
    policy = _policy()
    p04 = m.BlueprintBuildRequest(
        target_blueprint_id="blueprint_canonical_document_integrated",
        target_blueprint_version=1,
        activity_spec=activity,
        rubric_spec=rubric,
        resolved_decisions=[_decision()],
        blueprint_policy=policy,
    )
    return CanonicalDocumentChainInputs(
        p04_request=p04,
        policy=policy,
        artifacts=artifacts,
    )


def build_canonical_document_p06_request(
    inputs: CanonicalDocumentChainInputs,
    *,
    approved_blueprint: m.AssessmentBlueprint,
) -> m.EvidenceMapRequest:
    """Continue from the actual P04 output; no intermediate golden is accepted."""

    bundle = _bundle_from_product_submission_boundary(
        inputs.artifacts.sufficient,
        submission_id=SUFFICIENT_SUBMISSION_ID,
        blueprint=approved_blueprint,
        policy=inputs.policy,
    )
    return m.EvidenceMapRequest(
        blueprint=approved_blueprint,
        planning_policy=inputs.policy.planning_policy,
        evidence_bundle=bundle,
    )


def _policy() -> m.BlueprintPolicy:
    return m.BlueprintPolicy(
        policy_id="blueprint_policy_1",
        activity_id=ACTIVITY_ID,
        question_count=1,
        target_total_minutes=5,
        allowed_response_formats=[m.ResponseFormat.OPEN_SHORT],
        priority_criterion_ids=[],
        required_criterion_ids=[],
        structured_justification_policy=m.StructuredJustificationPolicy(
            mode=m.StructuredJustificationMode.NOT_REQUIRED,
            selected_opportunity_template_ids=[],
        ),
        planning_policy=m.AssessmentPlanningPolicy(
            policy_id="planning_policy_1",
            minimum_opportunity_quality=0.75,
            minimum_evidence_fit=0.7,
            max_reserve_opportunities=3,
        ),
        max_local_regenerations=1,
        human_review_required=True,
    )


def _decision() -> m.PolicyDecision:
    return m.PolicyDecision(
        decision_id="decision_closed_materials",
        issue_id="issue_material_boundary",
        selected_option_id="option_closed_materials",
        selected_option=m.DecisionOption(
            option_id="option_closed_materials",
            label="Usar únicamente el paquete autorizado",
            consequence=(
                "Mantiene el contexto cerrado y prohíbe fuentes externas."
            ),
        ),
        decided_by="usr_harness_reviewer",
        decided_at=FIXED_TIME,
        note=None,
    )


def _blueprint() -> m.AssessmentBlueprint:
    raw = json.loads(P05_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8"))
    return m.AssessmentBlueprint.model_validate(raw["golden_positive"]["blueprint"])


def _p05_negative_request(
    positive: m.BlueprintReviewRequest,
) -> m.BlueprintReviewRequest:
    """Apply only the versioned PLAN_FEASIBILITY negative mutation."""

    choice_formats = [m.ResponseFormat.CHOICE]
    dimensions = [
        dimension.model_copy(
            update={
                "evidence_variants": [
                    variant.model_copy(
                        update={
                            "question_opportunities": [
                                opportunity.model_copy(
                                    update={
                                        "allowed_response_formats": choice_formats
                                    }
                                )
                                for opportunity in variant.question_opportunities
                            ]
                        }
                    )
                    for variant in dimension.evidence_variants
                ]
            }
        )
        for dimension in positive.blueprint.dimensions
    ]
    negative_blueprint = positive.blueprint.model_copy(
        update={
            "dimensions": dimensions,
            "assessment_constraints": (
                positive.blueprint.assessment_constraints.model_copy(
                    update={"allowed_response_formats": choice_formats}
                )
            ),
        }
    )
    return m.BlueprintReviewRequest(
        blueprint=negative_blueprint,
        activity_spec=positive.activity_spec,
        rubric_spec=positive.rubric_spec,
        resolved_decisions=positive.resolved_decisions,
        blueprint_policy=positive.blueprint_policy,
        deterministic_preflight=build_blueprint_review_preflight(
            blueprint=negative_blueprint,
            activity_spec=positive.activity_spec,
            rubric_spec=positive.rubric_spec,
            blueprint_policy=positive.blueprint_policy,
        ),
    )


def _mapping_for_evidence(
    *,
    blueprint: m.AssessmentBlueprint,
    bundle: m.EvidenceBundle,
    evidence: m.EvidenceUnit,
) -> m.EvidenceMapPatch:
    dimension = blueprint.dimensions[0]
    variant = dimension.evidence_variants[0]
    template = next(
        item
        for item in variant.question_opportunities
        if item.opportunity_template_id == "oppt_justify_cache_invalidation"
    )
    opportunity = m.QuestionOpportunity(
        opportunity_id=stable_id(
            "opportunity", bundle.submission_id, template.opportunity_template_id
        ),
        opportunity_template_id=template.opportunity_template_id,
        submission_id=bundle.submission_id,
        dimension_id=dimension.dimension_id,
        variant_id=variant.variant_id,
        evidence_ids=[evidence.evidence_id],
        cognitive_operation=template.cognitive_operation,
        focus=template.focus,
        observable=template.observable,
        difficulty=template.difficulty,
        target_minutes=template.target_minutes,
        allowed_anchor_structures=template.allowed_anchor_structures,
        allowed_response_formats=template.allowed_response_formats,
        activity_priority=dimension.verification_priority,
        evidence_fit=0.98,
        opportunity_quality=0.96,
        student_justification_required=template.student_justification_required,
    )
    return m.EvidenceMapPatch(
        submission_id=bundle.submission_id,
        status="READY",
        claims=[
            m.EvidenceClaim(
                claim_id=stable_id("claim", bundle.submission_id, evidence.evidence_id),
                text=(
                    "El cambio de fuente invalida la entrada previa; conservarla "
                    "arriesga un resultado obsoleto y la consulta posterior recalcula."
                ),
                evidence_ids=[evidence.evidence_id],
                alignments=[
                    m.EvidenceAlignment(
                        dimension_id=dimension.dimension_id,
                        variant_ids=[variant.variant_id],
                        criterion_ids=["criterion_1"],
                        strength=0.98,
                        justification=(
                            "El fragmento contiene la secuencia y el riesgo "
                            "exigidos por el criterio."
                        ),
                    )
                ],
                supported_operations=[m.CognitiveOperation.JUSTIFY_DECISION],
                specificity=0.98,
                auditability=1.0,
                self_containment=0.98,
                ambiguity_risk=0.02,
                uncertainties=[],
            )
        ],
        variant_matches=[
            m.EvidenceVariantMatch(
                dimension_id=dimension.dimension_id,
                variant_id=variant.variant_id,
                evidence_ids=[evidence.evidence_id],
                evidence_fit=0.98,
                mapping_confidence=0.98,
                justification=(
                    "El fragmento satisface modalidad, foco, observable y "
                    "operación sin conocimiento externo."
                ),
            )
        ],
        opportunities=[opportunity],
        diagnostics=[],
    )


def _guide_draft(
    fixture: dict[str, Any],
    evidence_id: str,
) -> m.GuideDraft:
    spec = fixture["p07_positive"]
    elements = [
        m.ObservableElement(
            element_id=item["element_id"],
            description=item["description"],
            evidence_ids=[evidence_id],
            source_ids=[],
            required_for_level_2=item["required_for_level_2"],
        )
        for item in spec["expected_elements"]
    ]
    element_ids = [item.element_id for item in elements]
    return m.GuideDraft(
        purpose=spec["purpose"],
        observable_elements=elements,
        acceptable_alternatives=spec["acceptable_alternatives"],
        misconceptions=spec["misconceptions"],
        levels=[
            m.GuideLevel(
                level=0,
                label="No evidenciado",
                descriptor="No establece una relación causal sustentada.",
                observable_element_ids=[],
            ),
            m.GuideLevel(
                level=1,
                label="Parcial",
                descriptor="Reconoce la invalidación, pero omite vínculos requeridos.",
                observable_element_ids=element_ids[:1],
            ),
            m.GuideLevel(
                level=2,
                label="Suficiente",
                descriptor="Explica los tres vínculos requeridos con la evidencia.",
                observable_element_ids=element_ids,
            ),
            m.GuideLevel(
                level=3,
                label="Completo",
                descriptor=(
                    "Explica con precisión los tres vínculos, mantiene el límite "
                    "inferencial y usa una formulación causal clara."
                ),
                observable_element_ids=element_ids,
            ),
        ],
        cannot_infer=spec["cannot_infer"],
    )


def _candidate(
    fixture: dict[str, Any],
    *,
    opportunity: m.QuestionOpportunity,
    evidence: m.EvidenceUnit,
    negative: bool,
) -> m.QuestionCandidate:
    spec = fixture["p08_negative"] if negative else fixture["p07_positive"]
    guide = _guide_draft(fixture, evidence.evidence_id)
    if negative:
        guide = guide.model_copy(
            update={
                "purpose": (
                    "Observar una explicación de detector y concurrencia que no "
                    "está disponible en la evidencia."
                ),
                "cannot_infer": [
                    "El detector interno no puede inferirse.",
                    "La consistencia concurrente no puede inferirse."
                ],
            }
        )
    return m.QuestionCandidate(
        candidate_id=(
            "candidate_cache_unanswerable_negative"
            if negative
            else "candidate_cache_justification_positive"
        ),
        submission_id=opportunity.submission_id,
        opportunity_id=opportunity.opportunity_id,
        opportunity_template_id=opportunity.opportunity_template_id,
        dimension_id=opportunity.dimension_id,
        variant_id=opportunity.variant_id,
        cognitive_operation=opportunity.cognitive_operation,
        response_format=m.ResponseFormat.OPEN_SHORT,
        difficulty=opportunity.difficulty,
        estimated_minutes=opportunity.target_minutes,
        question_text=spec["question_text"],
        anchor=m.Anchor(
            anchor_id=stable_id(
                "anchor", opportunity.submission_id, evidence.evidence_id, negative
            ),
            structure=m.AnchorStructure.SINGLE_FRAGMENT,
            fragments=[
                m.AnchorFragment(
                    evidence_id=evidence.evidence_id,
                    display_text=evidence.content_text,
                    transformation="LITERAL",
                    locator=evidence.locator,
                )
            ],
            student_facing_label="Fragmento del entregable sintético",
            self_containment_score=0.99 if not negative else 0.42,
            answer_leakage_risk=0.22 if not negative else 0.05,
        ),
        evidence_ids=[evidence.evidence_id],
        course_source_ids=[],
        citations=[],
        choices=[],
        student_justification_required=opportunity.student_justification_required,
        preliminary_guide=guide,
        uncertainties=(
            ["La evidencia no describe detector ni concurrencia."]
            if negative
            else []
        ),
    )


def _question_review(
    fixture: dict[str, Any],
    generation: m.QuestionGenerationResult,
    *,
    negative: bool,
) -> m.QuestionReviewResult:
    spec = fixture["p08_negative"] if negative else fixture["p08_positive"]
    candidate = generation.candidate
    if candidate is None:
        raise ValueError("review fixture requires a candidate")
    return m.QuestionReviewResult(
        submission_id=generation.submission_id,
        opportunity_id=generation.opportunity_id,
        status="READY",
        review=m.QuestionSemanticReview(
            candidate_id=candidate.candidate_id,
            decision=(m.ReviewDecision.REJECT if negative else m.ReviewDecision.ACCEPT),
            critical_failure_codes=(
                spec["critical_failure_codes"] if negative else []
            ),
            scores=m.QuestionScores.model_validate(spec["scores"]),
            estimated_difficulty=candidate.difficulty,
            estimated_minutes=candidate.estimated_minutes,
            confidence=spec["confidence"],
            justifications=spec["review_evidence"],
            evidence_ids=[candidate.evidence_ids[0]],
            source_ids=[],
            diagnostics=[],
        ),
        diagnostics=[],
    )


class ReviewedSemanticAdapter:
    """Return reviewed goldens while exercising the normal gateway boundary.

    This adapter is an offline harness instrument.  It never imports or wraps a
    provider transport, and it only accepts an exact, reviewed request hash.
    """

    def __init__(self, checkpoints: SemanticCheckpoints) -> None:
        from .model_gateway.mock_factory import (
            AdapterResult,
            DeterministicMockAdapter,
        )

        self._adapter_result_type = AdapterResult
        self._structural_fallback = DeterministicMockAdapter()
        self.calls: list[str] = []
        self.invocations: list[dict[str, str]] = []
        self._responses = {
            (
                prompt_id,
                canonical_hash(request.model_dump(mode="json")),
            ): _semantic_checkpoint_expected_output(checkpoints, checkpoint_id)
            for checkpoint_id, prompt_id, request in semantic_checkpoint_requests(
                checkpoints
            )
        }

    async def invoke(self, **kwargs: Any) -> Any:
        request = cast(m.StrictModel, kwargs["request"])
        key = (
            str(kwargs["prompt_id"]),
            canonical_hash(request.model_dump(mode="json")),
        )
        if key not in self._responses:
            self.invocations.append(
                {
                    "prompt_id": key[0],
                    "request_hash": key[1],
                    "response_origin": "STRUCTURAL_TRANSPORT_SUBSTITUTE",
                }
            )
            return await self._structural_fallback.invoke(**kwargs)
        self.calls.append(key[0])
        self.invocations.append(
            {
                "prompt_id": key[0],
                "request_hash": key[1],
                "response_origin": "REVIEWED_SEMANTIC_ORACLE",
            }
        )
        raw = self._responses[key].model_dump(mode="json")
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        return self._adapter_result_type(
            raw_output=raw,
            input_tokens=max(1, len(request.model_dump_json()) // 4),
            cached_input_tokens=0,
            output_tokens=max(1, len(encoded) // 4),
            reason_codes=("OFFLINE_REVIEWED_SEMANTIC_ORACLE",),
        )


def _semantic_checkpoint_expected_output(
    checkpoints: SemanticCheckpoints,
    checkpoint_id: str,
) -> m.StrictModel:
    expected: dict[str, m.StrictModel] = {
        "P04_CANONICAL_POSITIVE": checkpoints.blueprint,
        "P05_CANONICAL_POSITIVE": checkpoints.p05_review,
        "P05_PLAN_FEASIBILITY_NEGATIVE": checkpoints.p05_negative_review,
        "P06_CANONICAL_POSITIVE": checkpoints.mapping,
        "P07_CANONICAL_POSITIVE": checkpoints.p07_positive_result,
        "P07_INSUFFICIENT_NEGATIVE": checkpoints.p07_negative_result,
        "P08_CANONICAL_POSITIVE": checkpoints.p08_positive_result,
        "P08_UNANSWERABLE_NEGATIVE": checkpoints.p08_negative_result,
        "P09_CANONICAL_POSITIVE": checkpoints.p09_guide,
    }
    return expected[checkpoint_id]


def build_reviewed_semantic_adapter() -> ReviewedSemanticAdapter:
    """Build the no-network adapter over a freshly validated document pack."""

    return ReviewedSemanticAdapter(build_semantic_checkpoints())


def build_semantic_checkpoints() -> SemanticCheckpoints:
    fixture = load_semantic_fixture()
    artifacts = _parse_artifacts(fixture)
    activity, rubric = _source_models(fixture, artifacts)
    policy = _policy()
    decision = _decision()
    blueprint = _blueprint()
    p04 = m.BlueprintBuildRequest(
        target_blueprint_id=blueprint.blueprint_id,
        target_blueprint_version=blueprint.blueprint_version,
        activity_spec=activity,
        rubric_spec=rubric,
        resolved_decisions=[decision],
        blueprint_policy=policy,
    )
    preflight = build_blueprint_review_preflight(
        blueprint=blueprint,
        activity_spec=activity,
        rubric_spec=rubric,
        blueprint_policy=policy,
    )
    p05 = m.BlueprintReviewRequest(
        blueprint=blueprint,
        activity_spec=activity,
        rubric_spec=rubric,
        resolved_decisions=[decision],
        blueprint_policy=policy,
        deterministic_preflight=preflight,
    )
    p05_review = _p05_review_from_versioned_semantic_fixture(
        p05,
        negative=False,
    )
    p05_negative = _p05_negative_request(p05)
    p05_negative_review = _p05_review_from_versioned_semantic_fixture(
        p05_negative,
        negative=True,
    )
    approved_blueprint = blueprint.model_copy(
        update={
            "status": m.WorkflowStatus.APPROVED,
            "approved_by": "usr_harness_reviewer",
            "approved_at": FIXED_TIME,
        }
    )
    sufficient_bundle = _bundle_from_product_submission_boundary(
        artifacts.sufficient,
        submission_id=SUFFICIENT_SUBMISSION_ID,
        blueprint=approved_blueprint,
        policy=policy,
    )
    insufficient_bundle = _bundle_from_product_submission_boundary(
        artifacts.insufficient,
        submission_id=INSUFFICIENT_SUBMISSION_ID,
        blueprint=approved_blueprint,
        policy=policy,
    )
    selectors = fixture["source_selectors"]
    sufficient_evidence = _unit_by_exact_text(
        artifacts.sufficient, selectors["sufficient_mechanism"]
    )
    insufficient_evidence = _unit_by_exact_text(
        artifacts.insufficient, selectors["insufficient_rule"]
    )
    mapping = _mapping_for_evidence(
        blueprint=approved_blueprint,
        bundle=sufficient_bundle,
        evidence=sufficient_evidence,
    )
    p06 = m.EvidenceMapRequest(
        blueprint=approved_blueprint,
        planning_policy=policy.planning_policy,
        evidence_bundle=sufficient_bundle,
    )
    validate_evidence_map(
        mapping,
        blueprint=approved_blueprint,
        bundle=sufficient_bundle,
        planning_policy=policy.planning_policy,
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=approved_blueprint,
        policy=policy.planning_policy,
    )
    validate_assessment_plan(plan, mapping=mapping)
    opportunity = mapping.opportunities[0]
    p07_positive = m.QuestionBuildRequest(
        target_candidate_id="candidate_cache_justification_positive",
        plan=plan,
        opportunity=opportunity,
        evidence_bundle=sufficient_bundle,
        generation_policy=m.QuestionGenerationPolicy(
            policy_id="question_generation_semantic_v1"
        ),
        avoid=[],
    )
    positive_candidate = _candidate(
        fixture,
        opportunity=opportunity,
        evidence=sufficient_evidence,
        negative=False,
    )
    positive_generation = m.QuestionGenerationResult(
        submission_id=SUFFICIENT_SUBMISSION_ID,
        opportunity_id=opportunity.opportunity_id,
        context_mode=m.ContextMode.CLOSED,
        status="READY",
        candidate=positive_candidate,
        diagnostics=[],
    )
    validate_generation_result(
        positive_generation,
        opportunity=opportunity,
        bundle=sufficient_bundle,
    )

    negative_mapping = _mapping_for_evidence(
        blueprint=approved_blueprint,
        bundle=insufficient_bundle,
        evidence=insufficient_evidence,
    )
    validate_evidence_map(
        negative_mapping,
        blueprint=approved_blueprint,
        bundle=insufficient_bundle,
        planning_policy=policy.planning_policy,
    )
    negative_plan = build_assessment_plan(
        mapping=negative_mapping,
        blueprint=approved_blueprint,
        policy=policy.planning_policy,
    )
    validate_assessment_plan(negative_plan, mapping=negative_mapping)
    negative_opportunity = negative_mapping.opportunities[0]
    p07_negative = m.QuestionBuildRequest(
        target_candidate_id="candidate_cache_insufficient_negative",
        plan=negative_plan,
        opportunity=negative_opportunity,
        evidence_bundle=insufficient_bundle,
        generation_policy=m.QuestionGenerationPolicy(
            policy_id="question_generation_semantic_v1"
        ),
        avoid=[],
    )
    negative_spec = fixture["p07_negative"]
    negative_generation = m.QuestionGenerationResult(
        submission_id=INSUFFICIENT_SUBMISSION_ID,
        opportunity_id=negative_opportunity.opportunity_id,
        context_mode=m.ContextMode.CLOSED,
        status="REPLACEMENT_REQUIRED",
        candidate=None,
        diagnostics=[
            m.Diagnostic(
                code=negative_spec["diagnostic"]["code"],
                severity=negative_spec["diagnostic"]["severity"],
                message=negative_spec["diagnostic"]["message"],
                evidence_ids=[insufficient_evidence.evidence_id],
                source_ids=[],
                retryable=negative_spec["diagnostic"]["retryable"],
                details={"semantic_review_id": negative_spec["semantic_review_id"]},
            )
        ],
    )
    validate_generation_result(
        negative_generation,
        opportunity=negative_opportunity,
        bundle=insufficient_bundle,
    )

    validation_policy = m.QuestionValidationPolicy(
        policy_id="question_validation_semantic_v1"
    )
    p08_positive = m.QuestionReviewRequest(
        generation_result=positive_generation,
        opportunity=opportunity,
        evidence_bundle=sufficient_bundle,
        validation_policy=validation_policy,
    )
    positive_review = _question_review(
        fixture,
        positive_generation,
        negative=False,
    )
    validate_review_result(
        positive_review,
        generation_result=positive_generation,
        validation_policy=validation_policy,
    )

    bad_candidate = _candidate(
        fixture,
        opportunity=negative_opportunity,
        evidence=insufficient_evidence,
        negative=True,
    )
    bad_generation = m.QuestionGenerationResult(
        submission_id=INSUFFICIENT_SUBMISSION_ID,
        opportunity_id=negative_opportunity.opportunity_id,
        context_mode=m.ContextMode.CLOSED,
        status="READY",
        candidate=bad_candidate,
        diagnostics=[],
    )
    validate_generation_result(
        bad_generation,
        opportunity=negative_opportunity,
        bundle=insufficient_bundle,
    )
    p08_negative = m.QuestionReviewRequest(
        generation_result=bad_generation,
        opportunity=negative_opportunity,
        evidence_bundle=insufficient_bundle,
        validation_policy=validation_policy,
    )
    negative_review = _question_review(
        fixture,
        bad_generation,
        negative=True,
    )
    validate_review_result(
        negative_review,
        generation_result=bad_generation,
        validation_policy=validation_policy,
    )

    selected = selected_question_from_candidate(
        positive_candidate,
        opportunity,
        submission_id=SUFFICIENT_SUBMISSION_ID,
    )
    assessment = assemble_assessment_snapshot(
        tenant_id=TENANT_ID,
        activity_id=ACTIVITY_ID,
        submission_id=SUFFICIENT_SUBMISSION_ID,
        subject_ref="synthetic_subject_cache_001",
        created_at=FIXED_TIME,
        blueprint=approved_blueprint,
        plan=plan,
        mapping=mapping,
        questions=[selected],
        assignment_prompt_hashes=[artifacts.assignment.artifact.sha256],
        rubric_hashes=[artifacts.rubric.artifact.sha256],
        submission_hashes=[artifacts.sufficient.artifact.sha256],
        submission_media_type=DOCX_MEDIA_TYPE,
        prompt_versions={
            prompt_id: prompt_spec(prompt_id).prompt_version
            for prompt_id in P04_P09_PROMPT_IDS
        },
        model_snapshots={
            prompt_id: "OFFLINE_REVIEWED_GOLDEN_NO_MODEL_EXECUTION"
            for prompt_id in P04_P09_PROMPT_IDS
        },
        policy_hash=canonical_hash(policy.model_dump(mode="json")),
    )
    guide_id = stable_id("guide", assessment.assessment_id)
    p09 = m.GuideBuildRequest(
        guide_id=guide_id,
        assessment=assessment,
        evidence_bundle=sufficient_bundle,
    )
    guide = m.EvaluationGuide(
        guide_id=guide_id,
        assessment_id=assessment.assessment_id,
        submission_id=assessment.submission_id,
        status="READY",
        items=[
            m.EvaluationGuideItem(
                question_id=selected.question_id,
                guide=positive_candidate.preliminary_guide,
            )
        ],
        diagnostics=[],
        created_at=FIXED_TIME,
    )
    validate_evaluation_guide(
        guide,
        assessment=assessment,
        bundle=sufficient_bundle,
    )
    return SemanticCheckpoints(
        p04_request=p04,
        blueprint=blueprint,
        p05_request=p05,
        p05_review=p05_review,
        p05_negative_request=p05_negative,
        p05_negative_review=p05_negative_review,
        p06_request=p06,
        mapping=mapping,
        plan=plan,
        p07_positive_request=p07_positive,
        p07_positive_result=positive_generation,
        p07_negative_request=p07_negative,
        p07_negative_result=negative_generation,
        p08_positive_request=p08_positive,
        p08_positive_result=positive_review,
        p08_negative_request=p08_negative,
        p08_negative_result=negative_review,
        p09_request=p09,
        p09_guide=guide,
        sufficient_bundle=sufficient_bundle,
        insufficient_bundle=insufficient_bundle,
        negative_mapping=negative_mapping,
        negative_plan=negative_plan,
        artifacts=artifacts,
    )


def _semantic_review_hash(
    fixture: dict[str, Any],
    key: str,
) -> str:
    material: dict[str, Any] = {"review": fixture[key]}
    if key == "p05_positive":
        p05 = json.loads(P05_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8"))
        material["category_review"] = p05["golden_positive"]["semantic_review"]
    elif key == "p05_negative":
        p05 = json.loads(P05_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8"))
        material["negative_oracle"] = p05["golden_negative"]
    return canonical_hash(material)


def _source_hashes(checkpoints: SemanticCheckpoints) -> dict[str, str]:
    return {
        "assignment": checkpoints.artifacts.assignment.artifact.sha256,
        "rubric": checkpoints.artifacts.rubric.artifact.sha256,
        "submission_sufficient": checkpoints.artifacts.sufficient.artifact.sha256,
        "submission_insufficient": checkpoints.artifacts.insufficient.artifact.sha256,
    }


def build_checkpoint_provenance(
    checkpoints: SemanticCheckpoints,
) -> list[dict[str, Any]]:
    fixture = load_semantic_fixture()
    fixture_hash = canonical_hash(fixture)
    source_hashes = _source_hashes(checkpoints)
    rows: list[dict[str, Any]] = []
    definitions = (
        (
            "P04_CANONICAL_POSITIVE",
            "P04_BLUEPRINT_BUILD_V1",
            "p04_positive",
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            [source_hashes["assignment"], source_hashes["rubric"]],
            checkpoints.blueprint,
        ),
        (
            "P05_CANONICAL_POSITIVE",
            "P05_BLUEPRINT_REVIEW_V1",
            "p05_positive",
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            [source_hashes["assignment"], source_hashes["rubric"]],
            checkpoints.p05_review,
        ),
        (
            "P05_PLAN_FEASIBILITY_NEGATIVE",
            "P05_BLUEPRINT_REVIEW_V1",
            "p05_negative",
            CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
            [source_hashes["assignment"], source_hashes["rubric"]],
            checkpoints.p05_negative_review,
        ),
        (
            "P06_CANONICAL_POSITIVE",
            "P06_EVIDENCE_MAP_V1",
            "p06_positive",
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            [source_hashes["submission_sufficient"]],
            checkpoints.mapping,
        ),
        (
            "P07_CANONICAL_POSITIVE",
            "P07_QUESTION_BUILD_V1",
            "p07_positive",
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            [source_hashes["submission_sufficient"]],
            checkpoints.p07_positive_result,
        ),
        (
            "P07_INSUFFICIENT_NEGATIVE",
            "P07_QUESTION_BUILD_V1",
            "p07_negative",
            CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
            [source_hashes["submission_insufficient"]],
            checkpoints.p07_negative_result,
        ),
        (
            "P08_CANONICAL_POSITIVE",
            "P08_QUESTION_REVIEW_V1",
            "p08_positive",
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            [source_hashes["submission_sufficient"]],
            checkpoints.p08_positive_result,
        ),
        (
            "P08_UNANSWERABLE_NEGATIVE",
            "P08_QUESTION_REVIEW_V1",
            "p08_negative",
            CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
            [source_hashes["submission_insufficient"]],
            checkpoints.p08_negative_result,
        ),
        (
            "P09_CANONICAL_POSITIVE",
            "P09_GUIDE_BUILD_V1",
            "p09_positive",
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            [
                source_hashes["assignment"],
                source_hashes["rubric"],
                source_hashes["submission_sufficient"],
            ],
            checkpoints.p09_guide,
        ),
    )
    for checkpoint_id, prompt_id, key, checkpoint_class, hashes, golden in definitions:
        review = fixture[key]
        preserved_review_hash = fixture["prior_review_hashes"][
            review["semantic_review_id"]
        ]
        current_review_material_hash = _semantic_review_hash(fixture, key)
        provenance_amendment_hash = canonical_hash(
            {
                "amendment": fixture["provenance_amendment"],
                "authorship": fixture["review_authorship"],
                "preserved_review_hash": preserved_review_hash,
            }
        )
        row: dict[str, Any] = {
            "checkpoint_id": checkpoint_id,
            "prompt_id": prompt_id,
            "checkpoint_class": checkpoint_class.value,
            "semantic_review_id": review["semantic_review_id"],
            "review_version": review["semantic_review_version"],
            "review_hash": preserved_review_hash,
            "current_review_material_hash": current_review_material_hash,
            "provenance_amendment_hash": provenance_amendment_hash,
            "fixture_hash": fixture_hash,
            "source_artifact_hashes": sorted(hashes),
            "review_evidence": review["review_evidence"],
            "expected_outcome": review["expected_outcome"],
            "golden_id": review["golden_id"],
            "golden_version": review["golden_version"],
            "golden_hash": canonical_hash(
                golden.model_dump(mode="json")
                if isinstance(golden, m.StrictModel)
                else golden
            ),
            "oracle_origin": fixture["review_authorship"]["authoring_class"],
            "independent_review_status": fixture["review_authorship"][
                "independent_review_status"
            ],
            "human_ratification": fixture["review_authorship"][
                "human_ratification"
            ],
            "prior_review_hash": preserved_review_hash,
        }
        if checkpoint_class == CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE:
            row["positive_obligation"] = review.get(
                "positive_obligation", review.get("purpose", review["expected_outcome"])
            )
            row["legitimate_abstention_reasons"] = review.get(
                "legitimate_abstention_reasons",
                review.get("legitimate_rejection_reasons", []),
            )
        else:
            row["negative_condition"] = review["condition"]
            row["correct_behavior"] = review["expected_outcome"]
            row["why_no_positive"] = review["why_no_positive"]
        rows.append(row)

    for legacy in fixture["legacy_structural_checkpoints"]:
        rows.append(
            {
                **legacy,
                "oracle_validity": OracleValidity.NOT_APPLICABLE.value,
                "semantic_review_id": None,
                "review_version": None,
                "review_hash": None,
                "fixture_hash": fixture_hash,
                "source_artifact_hashes": [],
                "review_evidence": [
                    "El mock prueba shape, IDs y orquestación; no califica calidad pedagógica."
                ],
            }
        )
    return rows


def validate_checkpoint_provenance(rows: list[dict[str, Any]]) -> None:
    prompt_ids = {row["prompt_id"] for row in rows}
    if not set(P04_P09_PROMPT_IDS).issubset(prompt_ids):
        raise ValueError("every P04-P09 prompt requires explicit provenance")
    for row in rows:
        checkpoint_class = CheckpointClass(row["checkpoint_class"])
        if not str(row["fixture_hash"]).startswith("sha256:"):
            raise ValueError("checkpoint fixture hash is missing")
        if checkpoint_class in {
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
            CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
        }:
            if not all(
                (
                    row.get("semantic_review_id"),
                    row.get("review_version"),
                    str(row.get("review_hash", "")).startswith("sha256:"),
                    str(
                        row.get("current_review_material_hash", "")
                    ).startswith("sha256:"),
                    str(row.get("provenance_amendment_hash", "")).startswith(
                        "sha256:"
                    ),
                    str(row.get("golden_hash", "")).startswith("sha256:"),
                    row.get("source_artifact_hashes"),
                    row.get("review_evidence"),
                    row.get("oracle_origin")
                    == "CODEX_AUTHORED_SEMANTIC_REVIEW",
                    "human_ratification" in row,
                )
            ):
                raise ValueError("semantic checkpoint lacks provenance")
            if row["review_hash"] != row["prior_review_hash"]:
                raise ValueError("semantic review hash lineage is not preserved")
        if checkpoint_class == CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE:
            if not row.get("positive_obligation"):
                raise ValueError("positive checkpoint lacks a concrete obligation")
            if "legitimate_abstention_reasons" not in row:
                raise ValueError("positive checkpoint lacks abstention analysis")
        elif checkpoint_class == CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE:
            if not all(
                row.get(key)
                for key in ("negative_condition", "correct_behavior", "why_no_positive")
            ):
                raise ValueError("negative checkpoint lacks its semantic condition")
        elif row.get("oracle_origin") == "DeterministicMockFactory" and row[
            "checkpoint_class"
        ] != CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY.value:
            raise ValueError("mock cannot be a semantic positive")


def classifier_branch_proof() -> list[dict[str, Any]]:
    common = {
        "semantic_review_id": "SR-CLASSIFIER-PROOF-001",
        "semantic_review_version": "1.0.0",
        "semantic_review_hash": canonical_hash({"classifier": "proof-v1"}),
    }
    cases: list[tuple[str, CheckpointAssessment, str]] = [
        (
            "valid-positive-semantic-failure",
            classify_checkpoint(
                checkpoint_id="proof-positive-fail",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.INCORRECT,
                contractual_adherence=ContractualAdherence.PASS,
                **common,
            ),
            "MODEL_OWNED_SEMANTIC_FAILURE",
        ),
        (
            "defendible-abstention-adherence-failure",
            classify_checkpoint(
                checkpoint_id="proof-abstention-adherence",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.DEFENDIBLE,
                contractual_adherence=ContractualAdherence.FAIL,
                **common,
            ),
            "MODEL_OWNED_CONTRACTUAL_ADHERENCE_FAILURE",
        ),
        (
            "correct-negative-rejection",
            classify_checkpoint(
                checkpoint_id="proof-correct-reject",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.CORRECT,
                contractual_adherence=ContractualAdherence.PASS,
                **common,
            ),
            "CORRECT_NEGATIVE_DECISION",
        ),
        (
            "invalid-oracle",
            classify_checkpoint(
                checkpoint_id="proof-invalid-oracle",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.INVALID,
                semantic_interpretation=SemanticInterpretation.NOT_EVALUATED,
                contractual_adherence=ContractualAdherence.NOT_EVALUATED,
            ),
            "ORACLE_OR_CHECKPOINT_INVALID",
        ),
        (
            "upstream-cause-indeterminate",
            classify_checkpoint(
                checkpoint_id="proof-indeterminate",
                checkpoint_class=CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE,
                oracle_validity=OracleValidity.VALID,
                semantic_interpretation=SemanticInterpretation.INDETERMINATE,
                contractual_adherence=ContractualAdherence.PASS,
                **common,
            ),
            "CAUSE_INDETERMINATE",
        ),
        (
            "technical-failure",
            classify_checkpoint(
                checkpoint_id="proof-technical",
                checkpoint_class=CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY,
                oracle_validity=OracleValidity.NOT_APPLICABLE,
                semantic_interpretation=SemanticInterpretation.NOT_EVALUATED,
                contractual_adherence=ContractualAdherence.NOT_EVALUATED,
                technical_failure=True,
            ),
            "TECHNICAL_FAILURE",
        ),
    ]
    proof = []
    for case_id, assessment, expected in cases:
        actual = assessment.causal_attribution.value
        proof.append(
            {
                "case_id": case_id,
                "status": "PASS" if actual == expected else "FAIL",
                "expected_causal_attribution": expected,
                "assessment": assessment.model_dump(),
            }
        )
    return proof


def run_semantic_harness_rehearsal() -> dict[str, Any]:
    fixture = load_semantic_fixture()
    frozen_boundary = frozen_product_boundary_proof()
    checkpoints = build_semantic_checkpoints()
    validate_blueprint_review_preflight_checks(
        checkpoints.p05_review,
        checkpoints.p05_request.deterministic_preflight,
    )
    if not blueprint_review_is_approvable(checkpoints.p05_review):
        raise ValueError("reviewed P05 positive must be approvable")
    if checkpoints.p05_request.rubric_spec is None:
        raise ValueError("P05 source-faithful check requires the rubric")
    grading_weight_proof = {
        "rubric": checkpoints.p05_request.rubric_spec.criteria[0].grading_weight,
        "blueprint": checkpoints.p05_request.blueprint.dimensions[0].grading_weight,
    }
    if grading_weight_proof != {"rubric": 1.0, "blueprint": 1.0}:
        raise ValueError("P05 grading weight is not source-faithful")

    provenance = build_checkpoint_provenance(checkpoints)
    validate_checkpoint_provenance(provenance)
    classifier_proof = classifier_branch_proof()
    qualification_rehearsal = run_offline_convergence_sync()
    semantic_sweep = qualification_rehearsal["observations"][0]
    observations_by_run = {
        observation["run_id"]: observation
        for observation in qualification_rehearsal["observations"]
    }
    base_1 = observations_by_run["chain-base-1"]
    base_2 = observations_by_run["chain-base-2"]
    canonical_chain = observations_by_run[
        "chain-canonical-document-sufficient"
    ]
    matrix_rows = qualification_rehearsal["qualification_matrix"]
    matrix_request_total = sum(
        row["max_provider_calls"] for row in matrix_rows
    )
    base_2_is_independent = (
        base_1["status"] == base_2["status"] == "PASS"
        and base_1["run_id"] != base_2["run_id"]
        and base_1["output_hash"] != base_2["output_hash"]
        and [stage["output_hash"] for stage in base_1["stages"]]
        != [stage["output_hash"] for stage in base_2["stages"]]
    )
    canonical_stages = canonical_chain["stages"]
    canonical_stage_by_name = {
        stage.get("prompt_id", stage.get("stage")): stage
        for stage in canonical_stages
    }
    canonical_chain_has_current_run_dataflow = (
        canonical_chain["status"] == "PASS"
        and canonical_stage_by_name["P04_BLUEPRINT_BUILD_V1"].get(
            "input_origin"
        )
        == "PRODUCT_DERIVED_DOCUMENT_BOUNDARY"
        and canonical_stage_by_name["P05_BLUEPRINT_REVIEW_V1"].get(
            "dataflow_input_from"
        )
        == "P04_CURRENT_RUN_OUTPUT"
        and canonical_stage_by_name["P06_EVIDENCE_MAP_V1"].get(
            "dataflow_input_from"
        )
        == "P04_CURRENT_RUN_OUTPUT_WITH_DETERMINISTIC_APPROVAL_TRANSITION"
        and canonical_stage_by_name["PLANNER"].get("dataflow_input_from")
        == "P06_CURRENT_RUN_OUTPUT"
        and canonical_stage_by_name["P07_QUESTION_BUILD_V1"].get(
            "dataflow_input_from"
        )
        == "P06_CURRENT_RUN_OUTPUT_AND_PRODUCT_PLANNER"
        and canonical_stage_by_name["P08_QUESTION_REVIEW_V1"].get(
            "dataflow_input_from"
        )
        == "P07_CURRENT_RUN_OUTPUT"
        and canonical_stage_by_name["ASSEMBLY"].get("dataflow_input_from")
        == "P04_P06_PLANNER_P07_CURRENT_RUN_OUTPUTS"
        and canonical_stage_by_name["P09_GUIDE_BUILD_V1"].get(
            "dataflow_input_from"
        )
        == "ASSEMBLY_CURRENT_RUN_OUTPUT"
        and all(
            stage.get("intermediate_golden_injected") is False
            for stage in canonical_stages
            if "intermediate_golden_injected" in stage
        )
    )
    transport_provenance = qualification_rehearsal[
        "transport_provenance"
    ]
    truthful_review_provenance = all(
        row.get("oracle_origin") == "CODEX_AUTHORED_SEMANTIC_REVIEW"
        and row.get("independent_review_status")
        == "USER_SUPPLIED_INDEPENDENT_REVIEW_FINDINGS"
        and row.get("human_ratification") is None
        and str(row.get("prior_review_hash", "")).startswith("sha256:")
        for row in provenance
        if row["checkpoint_class"]
        in {
            CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE.value,
            CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE.value,
        }
    )
    sweep_axes_complete = (
        qualification_rehearsal["status"] == "PASS"
        and qualification_rehearsal["causal_classification"]
        == "QUALIFICATION_PASSED"
        and semantic_sweep["run_kind"] == "SEMANTIC_QUALIFICATION_SWEEP"
        and len(semantic_sweep["stages"]) == 9
        and len(semantic_sweep["checkpoint_assessments"]) == 9
        and all(
            stage.get("checkpoint_class")
            in {
                CheckpointClass.SEMANTICALLY_QUALIFIED_POSITIVE.value,
                CheckpointClass.SEMANTICALLY_QUALIFIED_NEGATIVE.value,
            }
            and stage.get("operational_outcome") == "PASS"
            and stage.get("semantic_interpretation") == "CORRECT"
            and stage.get("contractual_adherence") == "PASS"
            and str(stage.get("review_hash", "")).startswith("sha256:")
            and str(stage.get("fixture_hash", "")).startswith("sha256:")
            and str(stage.get("golden_hash", "")).startswith("sha256:")
            for stage in semantic_sweep["stages"]
        )
    )
    successful_assessments = [
        classify_checkpoint(
            checkpoint_id=row["checkpoint_id"],
            checkpoint_class=row["checkpoint_class"],
            oracle_validity=(
                OracleValidity.NOT_APPLICABLE
                if row["checkpoint_class"]
                == CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY.value
                else OracleValidity.VALID
            ),
            semantic_interpretation=(
                SemanticInterpretation.NOT_EVALUATED
                if row["checkpoint_class"]
                == CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY.value
                else SemanticInterpretation.CORRECT
            ),
            contractual_adherence=(
                ContractualAdherence.NOT_EVALUATED
                if row["checkpoint_class"]
                == CheckpointClass.STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY.value
                else ContractualAdherence.PASS
            ),
            semantic_review_id=row.get("semantic_review_id"),
            semantic_review_version=row.get("review_version"),
            semantic_review_hash=row.get("review_hash"),
        )
        for row in provenance
    ]
    checks = [
        {
            "check_id": "PRODUCT_BOUNDARY_FROZEN",
            "status": "PASS",
            "baseline_git_sha": frozen_boundary["baseline_git_sha"],
            "manifest_hash": frozen_boundary["manifest_hash"],
        },
        {
            "check_id": "DOCUMENT_PACK_PRODUCT_PARSER",
            "status": "PASS",
            "parser_version": PARSER_VERSION,
            "artifact_count": 4,
            "source_artifact_hashes": _source_hashes(checkpoints),
        },
        {
            "check_id": "P05_SOURCE_FIDELITY",
            "status": "PASS",
            "grading_weight": grading_weight_proof,
            "canonical_categories": sorted(
                check.category for check in checkpoints.p05_review.checks
            ),
            "transition": "APPROVABLE",
        },
        {
            "check_id": "P07_POSITIVE_READY",
            "status": (
                "PASS"
                if checkpoints.p07_positive_result.status == "READY"
                and checkpoints.p07_positive_result.candidate is not None
                else "FAIL"
            ),
            "output_hash": canonical_hash(
                checkpoints.p07_positive_result.model_dump(mode="json")
            ),
        },
        {
            "check_id": "P07_NEGATIVE_REPLACEMENT_REQUIRED",
            "status": (
                "PASS"
                if checkpoints.p07_negative_result.status == "REPLACEMENT_REQUIRED"
                and checkpoints.p07_negative_result.candidate is None
                and bool(checkpoints.p07_negative_result.diagnostics)
                and all(
                    diagnostic.severity in {m.Severity.ERROR, m.Severity.CRITICAL}
                    and not diagnostic.retryable
                    for diagnostic in checkpoints.p07_negative_result.diagnostics
                )
                else "FAIL"
            ),
            "output_hash": canonical_hash(
                checkpoints.p07_negative_result.model_dump(mode="json")
            ),
        },
        {
            "check_id": "P08_POSITIVE_ACCEPT",
            "status": (
                "PASS"
                if checkpoints.p08_positive_result.review is not None
                and checkpoints.p08_positive_result.review.decision
                == m.ReviewDecision.ACCEPT
                else "FAIL"
            ),
            "output_hash": canonical_hash(
                checkpoints.p08_positive_result.model_dump(mode="json")
            ),
        },
        {
            "check_id": "P08_NEGATIVE_REJECT",
            "status": (
                "PASS"
                if checkpoints.p08_negative_result.review is not None
                and checkpoints.p08_negative_result.review.decision
                == m.ReviewDecision.REJECT
                else "FAIL"
            ),
            "output_hash": canonical_hash(
                checkpoints.p08_negative_result.model_dump(mode="json")
            ),
        },
        {
            "check_id": "P09_PRODUCTION_ASSEMBLY_AND_GUIDE",
            "status": "PASS",
            "assembler_version": ASSEMBLER_VERSION,
            "planner_version": PLANNER_VERSION,
            "assessment_hash": canonical_hash(
                checkpoints.p09_request.assessment.model_dump(mode="json")
            ),
            "guide_hash": canonical_hash(
                checkpoints.p09_guide.model_dump(mode="json")
            ),
        },
        {
            "check_id": "CHECKPOINT_PROVENANCE_COMPLETE",
            "status": "PASS",
            "checkpoint_count": len(provenance),
        },
        {
            "check_id": "ADVERSARIAL_REVIEW",
            "status": (
                "PASS"
                if all(
                    value.startswith("PASS:")
                    for value in fixture["adversarial_review"]["questions"].values()
                )
                else "FAIL"
            ),
            "review_hash": canonical_hash(fixture["adversarial_review"]),
        },
        {
            "check_id": "DOCUMENT_VISUAL_QA",
            "status": fixture["document_visual_qa"]["status"],
            "review_hash": canonical_hash(fixture["document_visual_qa"]),
            "page_counts": fixture["document_visual_qa"]["page_counts"],
        },
        {
            "check_id": "CAUSAL_CLASSIFIER_BRANCHES",
            "status": (
                "PASS"
                if all(item["status"] == "PASS" for item in classifier_proof)
                else "FAIL"
            ),
            "branch_count": len(classifier_proof),
        },
        {
            "check_id": "SEMANTIC_SWEEP_RECEIPT_AXES",
            "status": "PASS" if sweep_axes_complete else "FAIL",
            "semantic_checkpoint_count": len(semantic_sweep["stages"]),
            "mock_gateway_invocations": qualification_rehearsal["controls"][
                "provider_attempts"
            ],
            "real_provider_attempts": 0,
            "network_calls_to_openai": 0,
        },
        {
            "check_id": "QUALIFICATION_MATRIX_DERIVED_CAP",
            "status": (
                "PASS"
                if matrix_request_total
                == qualification_rehearsal["derived_max_provider_requests"]
                == QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
                and len(matrix_rows) == 7
                else "FAIL"
            ),
            "matrix_row_count": len(matrix_rows),
            "derived_max_provider_requests": matrix_request_total,
            "monetary_budget_status": (
                "RECALCULATION_FROM_CURRENT_OFFICIAL_PRICES_REQUIRED"
            ),
        },
        {
            "check_id": "BASE_CHAIN_2_INDEPENDENT_COMPOSITION",
            "status": "PASS" if base_2_is_independent else "FAIL",
            "base_1_output_hash": base_1["output_hash"],
            "base_2_output_hash": base_2["output_hash"],
            "semantic_quality_conclusion_allowed": False,
        },
        {
            "check_id": "CANONICAL_DOCUMENT_INTEGRATED_CHAIN",
            "status": (
                "PASS" if canonical_chain_has_current_run_dataflow else "FAIL"
            ),
            "stage_count": len(canonical_stages),
            "intermediate_golden_injections": sum(
                stage.get("intermediate_golden_injected") is True
                for stage in canonical_stages
            ),
            "semantic_quality_conclusion_allowed": False,
        },
        {
            "check_id": "TRANSPORT_PROVENANCE_SEPARATION",
            "status": (
                "PASS"
                if transport_provenance[
                    "reviewed_semantic_oracle_invocations"
                ]
                == 9
                and transport_provenance[
                    "structural_transport_substitute_invocations"
                ]
                == 24
                and transport_provenance["provider_transport_constructed"]
                is False
                else "FAIL"
            ),
            **transport_provenance,
        },
        {
            "check_id": "TRUTHFUL_REVIEW_PROVENANCE",
            "status": "PASS" if truthful_review_provenance else "FAIL",
            "authoring_class": "CODEX_AUTHORED_SEMANTIC_REVIEW",
            "independent_review_status": (
                "USER_SUPPLIED_INDEPENDENT_REVIEW_FINDINGS"
            ),
            "human_ratification": None,
        },
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return {
        "report_schema_version": SEMANTIC_REPORT_VERSION,
        "rehearsal_version": SEMANTIC_REHEARSAL_VERSION,
        "phase": "HARNESS_FINAL_SEMANTIC_HARDENING",
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "status": status,
        "fixture_version": fixture["schema_version"],
        "fixture_hash": canonical_hash(fixture),
        "canonical_pack": {
            "pack_id": fixture["pack_id"],
            "document_shaped": True,
            "artifact_count": 4,
            "parser_version": PARSER_VERSION,
            "source_artifact_hashes": _source_hashes(checkpoints),
            "sufficient_evidence_unit_count": len(
                checkpoints.sufficient_bundle.evidence_units
            ),
            "insufficient_evidence_unit_count": len(
                checkpoints.insufficient_bundle.evidence_units
            ),
            "bundle_construction": "PRODUCT_SUBMISSION_PARSE_BOUNDARY",
            "assessment_assembly": fixture["p09_positive"]["assembly"],
        },
        "checks": checks,
        "checkpoint_provenance": provenance,
        "checkpoint_assessments": [
            assessment.model_dump() for assessment in successful_assessments
        ],
        "causal_classification": aggregate_causal_classification(
            successful_assessments
        ),
        "classifier_branch_proof": classifier_proof,
        "offline_qualification_rehearsal": {
            "status": qualification_rehearsal["status"],
            "mode": qualification_rehearsal["mode"],
            "execution_sequence": qualification_rehearsal[
                "execution_sequence"
            ],
            "semantic_sweep_run_kind": semantic_sweep["run_kind"],
            "semantic_checkpoint_count": len(semantic_sweep["stages"]),
            "checkpoint_assessments": semantic_sweep[
                "checkpoint_assessments"
            ],
            "causal_classification": qualification_rehearsal[
                "causal_classification"
            ],
            "mock_gateway_invocations": qualification_rehearsal["controls"][
                "provider_attempts"
            ],
            "expected_mock_gateway_invocations": (
                QUALIFICATION_EXPECTED_PROVIDER_REQUESTS
            ),
            "network_calls_to_openai": 0,
            "billable_requests": 0,
            "qualification_matrix": matrix_rows,
            "derived_max_provider_requests": matrix_request_total,
            "transport_provenance": transport_provenance,
            "base_chain_2": {
                "status": base_2["status"],
                "independent_output": base_2_is_independent,
                "output_hash": base_2["output_hash"],
            },
            "canonical_document_chain": {
                "status": canonical_chain["status"],
                "stage_count": len(canonical_stages),
                "current_run_dataflow": (
                    canonical_chain_has_current_run_dataflow
                ),
                "intermediate_golden_injections": 0,
                "semantic_quality_conclusion_allowed": False,
            },
        },
        "adversarial_review": fixture["adversarial_review"],
        "document_visual_qa": fixture["document_visual_qa"],
        "frozen_product_boundary": frozen_boundary,
        "controls": {
            "provider_attempts": 0,
            "mock_gateway_invocations": qualification_rehearsal["controls"][
                "provider_attempts"
            ],
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
        },
    }
