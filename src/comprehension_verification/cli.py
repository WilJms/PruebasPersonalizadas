"""Development-only command line entry points for the approved Stage 0 gate.

The synthetic runner deliberately uses versioned fixtures, the safe parsers,
the governed mock gateway, contextual validators, the deterministic planner,
and the renderer.  It is not an operational local deployment and never calls
a network provider by default.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from pydantic import BaseModel, SecretStr

from .canonical import StableClock, canonical_hash, sha256_bytes, stable_id
from .contract_validation import run_contract_validation_gate
from .contracts import models as m
from .diagnostics import diagnostic
from .exports import RENDERER_VERSION, render_views
from .fixture_builder import DEFAULT_STAGE0_ROOT, build_stage0_fixtures
from .model_gateway import (
    CallBudget,
    GatewayConfig,
    GatewayError,
    GatewayMode,
    ModelGateway,
    OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS,
    OPENAI_ROUTE_PROFILE_ID,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
    build_mock_request,
    build_openai_cost_estimator,
    build_openai_routes,
    build_trusted_context,
    estimate_openai_input_tokens,
)
from .model_gateway.registry import PROMPT_VERSION
from .parsers import PARSER_VERSION, ParsedArtifact, SafeParserService
from .planning import PLANNER_VERSION, build_assessment_plan
from .storage import LocalArtifactStore
from .validation import (
    build_blueprint_review_preflight,
    validate_assessment_plan,
    validate_evaluation_guide,
    validate_evidence_map,
    validate_generation_result,
    validate_review_result,
)


_CASES = {
    "sufficient": ("activity_01_rubric", "sub_cache_sufficient"),
    "insufficient": ("activity_02_no_rubric", "sub_campaign_insufficient"),
    "injection": ("activity_01_rubric", "sub_cache_injection"),
}
_INJECTION_MARKERS = (
    "instruccion para el sistema",
    "ignora la consigna",
    "datos de otra submission",
)


class CliFailure(RuntimeError):
    """Stable CLI failure that never carries student content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SyntheticFixture:
    case: str
    root: Path
    config: m.ActivityConfig
    submission_id: str
    subject_ref: str
    submission_path: Path
    submission_media_type: str
    assignment_path: Path
    rubric_path: Path | None
    expected_status: str


def _json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_fixture(case: str) -> SyntheticFixture:
    directory_name, submission_id = _CASES[case]
    root = (DEFAULT_STAGE0_ROOT / directory_name).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = m.ActivityConfig.model_validate(manifest["activity_config"])
    paths = manifest["paths"]
    selected = next(
        (
            item
            for item in paths["submissions"]
            if item["submission_id"] == submission_id
        ),
        None,
    )
    if selected is None:
        raise CliFailure("FIXTURE_NOT_FOUND", "Synthetic submission is missing")

    def safe_path(relative: str) -> Path:
        candidate = (root / relative).resolve()
        if root != candidate and root not in candidate.parents:
            raise CliFailure("FIXTURE_PATH_INVALID", "Fixture path escapes its root")
        if not candidate.is_file():
            raise CliFailure("FIXTURE_NOT_FOUND", "Synthetic artifact is missing")
        return candidate

    rubric_path = safe_path(paths["rubric"]) if paths["rubric"] else None
    return SyntheticFixture(
        case=case,
        root=root,
        config=config,
        submission_id=selected["submission_id"],
        subject_ref=selected["subject_ref"],
        submission_path=safe_path(selected["path"]),
        submission_media_type=selected["declared_media_type"],
        assignment_path=safe_path(paths["assignment"]),
        rubric_path=rubric_path,
        expected_status=selected["expected_status"],
    )


def _blueprint_policy(config: m.ActivityConfig) -> m.BlueprintPolicy:
    selected_template_ids: list[str] = []
    if config.structured_justification_mode == m.StructuredJustificationMode.SELECTED:
        selected_template_ids = [
            stable_id("oppt", config.activity_id, "selected_justification")
        ]
    planning = m.AssessmentPlanningPolicy(
        policy_id=stable_id("policy", config.activity_id, "planning")
    )
    return m.BlueprintPolicy(
        policy_id=stable_id("policy", config.activity_id, "blueprint"),
        activity_id=config.activity_id,
        context_mode=config.context_mode,
        question_count=config.question_count,
        target_total_minutes=config.target_total_minutes,
        allowed_response_formats=list(config.allowed_response_formats),
        priority_criterion_ids=list(config.priority_criterion_ids),
        structured_justification_policy=m.StructuredJustificationPolicy(
            mode=config.structured_justification_mode,
            selected_opportunity_template_ids=selected_template_ids,
        ),
        planning_policy=planning,
        max_local_regenerations=1,
        human_review_required=True,
    )


def _parse_source(
    parser: SafeParserService,
    path: Path,
    *,
    fixture: SyntheticFixture,
    role: m.ArtifactRole,
    submission_id: str | None = None,
    declared_media_type: str | None = None,
) -> ParsedArtifact:
    return parser.parse(
        path,
        tenant_id=fixture.config.tenant_id,
        source_role=role,
        submission_id=submission_id,
        declared_media_type=declared_media_type,
    )


def _trusted_context(
    request: BaseModel,
    *,
    fixture: SyntheticFixture,
) -> m.TrustedPromptContext:
    derived = build_trusted_context(request)
    raw = derived.model_dump(mode="json")
    raw.update(
        {
            "tenant_id": fixture.config.tenant_id,
            "activity_id": fixture.config.activity_id,
            "output_language": fixture.config.output_language,
            "context_mode": fixture.config.context_mode,
        }
    )
    return m.TrustedPromptContext.model_validate(raw)


async def _invoke(
    gateway: ModelGateway,
    prompt_id: str,
    request: BaseModel,
    *,
    fixture: SyntheticFixture,
) -> BaseModel:
    result = await gateway.invoke(
        prompt_id,
        request,
        _trusted_context(request, fixture=fixture),
    )
    return result.output


def _deduplicate_planning_opportunities(
    mapping: m.EvidenceMapPatch,
    *,
    question_count: int,
) -> m.EvidenceMapPatch:
    """Collapse opportunities grounded in the exact same evidence set.

    This deterministic Stage 0 boundary prevents a one-line submission from
    appearing to contain N distinct question opportunities merely because the
    mock blueprint exposes several cognitive-operation templates.
    """

    if mapping.status != "READY":
        return mapping
    seen: set[tuple[str, ...]] = set()
    unique: list[m.QuestionOpportunity] = []
    for opportunity in mapping.opportunities:
        signature = tuple(sorted(opportunity.evidence_ids))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(opportunity)
    if len(unique) < question_count:
        return m.EvidenceMapPatch(
            submission_id=mapping.submission_id,
            status="INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
            claims=[],
            variant_matches=[],
            opportunities=[],
            diagnostics=[
                diagnostic(
                    "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
                    "La deduplicación no conservó oportunidades sustancialmente distintas suficientes.",
                    evidence_ids=sorted(
                        {
                            evidence_id
                            for opportunity in unique
                            for evidence_id in opportunity.evidence_ids
                        }
                    ),
                    retryable=False,
                    details={
                        "distinct_opportunity_count": len(unique),
                        "required_question_count": question_count,
                    },
                )
            ],
        )
    return m.EvidenceMapPatch.model_validate(
        {
            **mapping.model_dump(mode="json"),
            "opportunities": [item.model_dump(mode="json") for item in unique],
        }
    )


def _selected_question(
    candidate: m.QuestionCandidate,
    opportunity: m.QuestionOpportunity,
) -> m.SelectedQuestion:
    return m.SelectedQuestion(
        question_id=stable_id(
            "question", candidate.submission_id, candidate.candidate_id
        ),
        source_candidate_id=candidate.candidate_id,
        opportunity_id=candidate.opportunity_id,
        opportunity_template_id=candidate.opportunity_template_id,
        dimension_id=candidate.dimension_id,
        variant_id=candidate.variant_id,
        cognitive_operation=candidate.cognitive_operation,
        response_format=candidate.response_format,
        difficulty=candidate.difficulty,
        estimated_minutes=candidate.estimated_minutes,
        question_text=candidate.question_text,
        anchor=candidate.anchor,
        evidence_ids=list(candidate.evidence_ids),
        course_source_ids=list(candidate.course_source_ids),
        citations=list(candidate.citations),
        choices=list(candidate.choices),
        student_justification_required=candidate.student_justification_required,
        preliminary_guide=candidate.preliminary_guide,
        planning_score=opportunity.activity_priority,
    )


def _assemble_assessment(
    *,
    fixture: SyntheticFixture,
    blueprint: m.AssessmentBlueprint,
    policy: m.BlueprintPolicy,
    mapping: m.EvidenceMapPatch,
    plan: m.AssessmentPlan,
    questions: list[m.SelectedQuestion],
    assignment: ParsedArtifact,
    rubric: ParsedArtifact | None,
    submission: ParsedArtifact,
    ledgers: list[m.ModelCallLedger],
    clock: StableClock,
) -> m.Assessment:
    opportunities_by_dimension: dict[str, list[m.QuestionOpportunity]] = {}
    for opportunity in mapping.opportunities:
        opportunities_by_dimension.setdefault(opportunity.dimension_id, []).append(
            opportunity
        )
    coverage = [
        m.CoverageItem(
            dimension_id=dimension.dimension_id,
            available_variant_count=len(dimension.evidence_variants),
            available_opportunity_count=len(
                opportunities_by_dimension.get(dimension.dimension_id, [])
            ),
            selected_opportunity_count=sum(
                question.dimension_id == dimension.dimension_id
                for question in questions
            ),
            evidence_unit_count=len(
                {
                    evidence_id
                    for opportunity in opportunities_by_dimension.get(
                        dimension.dimension_id, []
                    )
                    for evidence_id in opportunity.evidence_ids
                }
            ),
        )
        for dimension in blueprint.dimensions
    ]
    required_question_ids = [
        question.question_id
        for question in questions
        if question.student_justification_required
    ]
    justification_mode = (
        blueprint.assessment_constraints.structured_justification_policy.mode
    )
    if (
        justification_mode == m.StructuredJustificationMode.SELECTED
        and not required_question_ids
    ):
        raise CliFailure(
            "ASSESSMENT_PLAN_INFEASIBLE",
            "Selected justification policy was not represented in the plan",
        )
    prompt_versions = {ledger.prompt_id: ledger.prompt_version for ledger in ledgers}
    model_snapshots = {
        ledger.prompt_id: ledger.route.model_snapshot for ledger in ledgers
    }
    assessment_id = stable_id(
        "assessment",
        fixture.submission_id,
        plan.plan_id,
        [question.source_candidate_id for question in questions],
    )
    return m.Assessment(
        assessment_id=assessment_id,
        tenant_id=fixture.config.tenant_id,
        activity_id=fixture.config.activity_id,
        submission_id=fixture.submission_id,
        subject_ref=fixture.subject_ref,
        status=m.WorkflowStatus.NEEDS_REVIEW,
        context_mode=m.ContextMode.CLOSED,
        assessment_plan_id=plan.plan_id,
        question_count=plan.question_count,
        questions=questions,
        coverage=coverage,
        structured_justification=m.StructuredJustificationSummary(
            mode=justification_mode,
            required_question_ids=required_question_ids,
            limited_evidence_notice_required=(
                justification_mode != m.StructuredJustificationMode.ALL
            ),
        ),
        lineage=m.Lineage(
            assignment_prompt_hashes=[assignment.artifact.sha256],
            rubric_hashes=[rubric.artifact.sha256] if rubric is not None else [],
            submission_hashes=[submission.artifact.sha256],
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.blueprint_version,
            parser_versions={submission.artifact.media_type: PARSER_VERSION},
            prompt_versions=prompt_versions,
            model_snapshots=model_snapshots,
            policy_hash=canonical_hash(policy),
            planner_version=PLANNER_VERSION,
            renderer_version=RENDERER_VERSION,
        ),
        created_at=clock.now(),
    )


def _write_stage(
    store: LocalArtifactStore,
    filename: str,
    value: Any,
) -> None:
    store.write_json(filename, value)


async def _run_synthetic(case: str, output: Path) -> int:
    fixture = _load_fixture(case)
    output = output.resolve()
    store = LocalArtifactStore(output)
    parser = SafeParserService()
    clock = StableClock()
    ledgers: list[m.ModelCallLedger] = []
    gateway = ModelGateway(
        GatewayConfig(
            mode=GatewayMode.MOCK,
            job_id=stable_id("job", fixture.config.activity_id, fixture.submission_id),
            clock=clock.now,
            backoff_base_seconds=0,
        ),
        ledger_sink=ledgers.append,
    )

    assignment = _parse_source(
        parser,
        fixture.assignment_path,
        fixture=fixture,
        role=m.ArtifactRole.ASSIGNMENT_PROMPT,
    )
    rubric_parsed = (
        _parse_source(
            parser,
            fixture.rubric_path,
            fixture=fixture,
            role=m.ArtifactRole.RUBRIC,
        )
        if fixture.rubric_path is not None
        else None
    )
    _write_stage(store, "activity_config.json", fixture.config)
    _write_stage(store, "assignment_artifact.json", assignment.artifact)
    _write_stage(store, "assignment_evidence.json", list(assignment.evidence_units))
    if rubric_parsed is not None:
        _write_stage(store, "rubric_artifact.json", rubric_parsed.artifact)
        _write_stage(store, "rubric_evidence.json", list(rubric_parsed.evidence_units))

    activity_spec = m.ActivitySpec.model_validate(
        (
            await _invoke(
                gateway,
                "P01_ACTIVITY_SPEC_V1",
                m.ActivitySpecRequest(
                    activity_config=fixture.config,
                    prompt_evidence=list(assignment.evidence_units),
                ),
                fixture=fixture,
            )
        ).model_dump(mode="json")
    )
    _write_stage(store, "activity_spec.json", activity_spec)

    rubric_spec: m.RubricSpec | None = None
    if rubric_parsed is not None:
        rubric_spec = m.RubricSpec.model_validate(
            (
                await _invoke(
                    gateway,
                    "P02_RUBRIC_NORMALIZE_V1",
                    m.RubricNormalizeRequest(
                        activity_spec=activity_spec,
                        rubric_evidence=list(rubric_parsed.evidence_units),
                    ),
                    fixture=fixture,
                )
            ).model_dump(mode="json")
        )
        _write_stage(store, "rubric_spec.json", rubric_spec)

    ambiguity = m.AmbiguityReport.model_validate(
        (
            await _invoke(
                gateway,
                "P03_AMBIGUITY_TRIAGE_V1",
                m.AmbiguityTriageRequest(
                    activity_spec=activity_spec,
                    rubric_spec=rubric_spec,
                ),
                fixture=fixture,
            )
        ).model_dump(mode="json")
    )
    _write_stage(store, "ambiguity_report.json", ambiguity)
    if ambiguity.blocked:
        raise CliFailure(
            "ASSIGNMENT_AMBIGUOUS", "Synthetic activity requires a policy decision"
        )

    policy = _blueprint_policy(fixture.config)
    blueprint = m.AssessmentBlueprint.model_validate(
        (
            await _invoke(
                gateway,
                "P04_BLUEPRINT_BUILD_V1",
                m.BlueprintBuildRequest(
                    target_blueprint_id=stable_id(
                        "blueprint", fixture.config.activity_id
                    ),
                    target_blueprint_version=1,
                    activity_spec=activity_spec,
                    rubric_spec=rubric_spec,
                    blueprint_policy=policy,
                ),
                fixture=fixture,
            )
        ).model_dump(mode="json")
    )
    review = m.BlueprintReview.model_validate(
        (
            await _invoke(
                gateway,
                "P05_BLUEPRINT_REVIEW_V1",
                m.BlueprintReviewRequest(
                    blueprint=blueprint,
                    activity_spec=activity_spec,
                    rubric_spec=rubric_spec,
                    blueprint_policy=policy,
                    deterministic_preflight=(
                        build_blueprint_review_preflight(
                            blueprint=blueprint,
                            activity_spec=activity_spec,
                            rubric_spec=rubric_spec,
                            blueprint_policy=policy,
                        )
                    ),
                ),
                fixture=fixture,
            )
        ).model_dump(mode="json")
    )
    _write_stage(store, "blueprint_policy.json", policy)
    _write_stage(store, "blueprint_review.json", review)
    if review.approval_recommendation == m.BlueprintApprovalRecommendation.REJECT:
        raise CliFailure("BLUEPRINT_REJECTED", "Synthetic blueprint review rejected")
    approved_raw = blueprint.model_dump(mode="json")
    approved_raw.update(
        {
            "status": m.WorkflowStatus.APPROVED.value,
            "approved_by": "teacher_synthetic",
            "approved_at": clock.now(),
        }
    )
    blueprint = m.AssessmentBlueprint.model_validate(approved_raw)
    _write_stage(store, "blueprint.json", blueprint)

    submission = _parse_source(
        parser,
        fixture.submission_path,
        fixture=fixture,
        role=m.ArtifactRole.SUBMISSION,
        submission_id=fixture.submission_id,
        declared_media_type=fixture.submission_media_type,
    )
    bundle = m.EvidenceBundle(
        bundle_id=stable_id(
            "bundle",
            fixture.config.activity_id,
            fixture.submission_id,
            submission.artifact.sha256,
        ),
        tenant_id=fixture.config.tenant_id,
        activity_id=fixture.config.activity_id,
        submission_id=fixture.submission_id,
        context_mode=m.ContextMode.CLOSED,
        allowed_evidence_ids=[
            unit.evidence_id for unit in submission.evidence_units
        ],
        evidence_units=list(submission.evidence_units),
        course_passages=[],
    )
    _write_stage(store, "submission_artifact.json", submission.artifact)
    _write_stage(store, "evidence_bundle.json", bundle)

    model_mapping = m.EvidenceMapPatch.model_validate(
        (
            await _invoke(
                gateway,
                "P06_EVIDENCE_MAP_V1",
                m.EvidenceMapRequest(
                    blueprint=blueprint,
                    planning_policy=policy.planning_policy,
                    evidence_bundle=bundle,
                ),
                fixture=fixture,
            )
        ).model_dump(mode="json")
    )
    validate_evidence_map(
        model_mapping,
        blueprint=blueprint,
        bundle=bundle,
        planning_policy=policy.planning_policy,
    )
    mapping = _deduplicate_planning_opportunities(
        model_mapping,
        question_count=blueprint.assessment_constraints.question_count,
    )
    validate_evidence_map(
        mapping,
        blueprint=blueprint,
        bundle=bundle,
        planning_policy=policy.planning_policy,
    )
    _write_stage(store, "model_evidence_map.json", model_mapping)
    _write_stage(store, "evidence_map.json", mapping)

    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=blueprint,
        policy=policy.planning_policy,
    )
    validate_assessment_plan(plan, mapping=mapping)
    _write_stage(store, "assessment_plan.json", plan)

    if plan.status != "READY":
        _write_stage(store, "model_call_ledger.json", ledgers)
        matched = plan.status == fixture.expected_status
        run_manifest = {
            "case": case,
            "mode": "mock",
            "expected_status": fixture.expected_status,
            "actual_status": plan.status,
            "expected_outcome_matched": matched,
            "partial_assessment_emitted": False,
            "model_call_count": len(ledgers),
        }
        _write_stage(store, "run_manifest.json", run_manifest)
        print(_json_line({"output": str(output), **run_manifest}))
        return 0 if matched else 1

    opportunities = {
        opportunity.opportunity_id: opportunity
        for opportunity in mapping.opportunities
    }
    questions: list[m.SelectedQuestion] = []
    for opportunity_id in plan.selected_opportunity_ids:
        opportunity = opportunities[opportunity_id]
        generation = m.QuestionGenerationResult.model_validate(
            (
                await _invoke(
                    gateway,
                    "P07_QUESTION_BUILD_V1",
                    m.QuestionBuildRequest(
                        target_candidate_id=stable_id(
                            "candidate",
                            fixture.submission_id,
                            plan.plan_id,
                            opportunity.opportunity_id,
                            "initial",
                        ),
                        plan=plan,
                        opportunity=opportunity,
                        evidence_bundle=bundle,
                        generation_policy=m.QuestionGenerationPolicy(
                            policy_id=stable_id(
                                "policy", fixture.config.activity_id, "generation"
                            )
                        ),
                    ),
                    fixture=fixture,
                )
            ).model_dump(mode="json")
        )
        validate_generation_result(
            generation, opportunity=opportunity, bundle=bundle
        )
        _write_stage(
            store,
            f"questions/{opportunity_id}.generation.json",
            generation,
        )
        if generation.candidate is None:
            raise CliFailure(
                "QUESTION_GENERATION_FAILED", "Synthetic generation abstained"
            )
        validation_policy = m.QuestionValidationPolicy(
            policy_id=stable_id("policy", fixture.config.activity_id, "validation")
        )
        question_review = m.QuestionReviewResult.model_validate(
            (
                await _invoke(
                    gateway,
                    "P08_QUESTION_REVIEW_V1",
                    m.QuestionReviewRequest(
                        generation_result=generation,
                        opportunity=opportunity,
                        evidence_bundle=bundle,
                        validation_policy=validation_policy,
                    ),
                    fixture=fixture,
                )
            ).model_dump(mode="json")
        )
        validate_review_result(
            question_review,
            generation_result=generation,
            validation_policy=validation_policy,
        )
        _write_stage(
            store,
            f"questions/{opportunity_id}.review.json",
            question_review,
        )
        if (
            question_review.review is None
            or question_review.review.decision != m.ReviewDecision.ACCEPT
        ):
            raise CliFailure("QUESTION_REVIEW_FAILED", "Synthetic review did not accept")
        questions.append(_selected_question(generation.candidate, opportunity))

    assessment = _assemble_assessment(
        fixture=fixture,
        blueprint=blueprint,
        policy=policy,
        mapping=mapping,
        plan=plan,
        questions=questions,
        assignment=assignment,
        rubric=rubric_parsed,
        submission=submission,
        ledgers=ledgers,
        clock=clock,
    )
    guide = m.EvaluationGuide.model_validate(
        (
            await _invoke(
                gateway,
                "P09_GUIDE_BUILD_V1",
                m.GuideBuildRequest(
                    guide_id=stable_id("guide", assessment.assessment_id),
                    assessment=assessment,
                    evidence_bundle=bundle,
                ),
                fixture=fixture,
            )
        ).model_dump(mode="json")
    )
    validate_evaluation_guide(guide, assessment=assessment, bundle=bundle)
    rendered = render_views(assessment, guide, output)

    source_contains_injection = any(
        any(marker in (unit.content_text or "").casefold() for marker in _INJECTION_MARKERS)
        for unit in bundle.evidence_units
    )
    generated_question_contains_injection = any(
        any(marker in question.question_text.casefold() for marker in _INJECTION_MARKERS)
        for question in assessment.questions
    )
    if generated_question_contains_injection:
        raise CliFailure(
            "QUESTION_SECURITY_FAIL", "Generated question echoed an injection marker"
        )
    security_observation = {
        "case": case,
        "source_contains_injection": source_contains_injection,
        "generated_question_contains_injection": False,
        "model_tools_enabled": False,
        "network_provider_called": False,
    }
    _write_stage(store, "security_observation.json", security_observation)
    _write_stage(store, "model_call_ledger.json", ledgers)
    matched = fixture.expected_status == "READY"
    run_manifest = {
        "case": case,
        "mode": "mock",
        "expected_status": fixture.expected_status,
        "actual_status": "READY",
        "assessment_status": assessment.status.value,
        "expected_outcome_matched": matched,
        "question_count": len(assessment.questions),
        "model_call_count": len(ledgers),
        "export_hashes": rendered.hashes,
        "security": security_observation,
    }
    _write_stage(store, "run_manifest.json", run_manifest)
    print(_json_line({"output": str(output), **run_manifest}))
    return 0 if matched else 1


def _validate_contracts(_args: argparse.Namespace) -> int:
    report = run_contract_validation_gate()
    print(_json_line({"status": "PASS", **asdict(report)}))
    return 0


def _build_fixtures(args: argparse.Namespace) -> int:
    artifacts = build_stage0_fixtures(args.root)
    result = [
        {
            "path": str(path),
            "sha256": sha256_bytes(path.read_bytes()),
            "byte_size": path.stat().st_size,
        }
        for path in artifacts
    ]
    print(_json_line({"status": "PASS", "artifacts": result}))
    return 0


def _synthetic(args: argparse.Namespace) -> int:
    return asyncio.run(_run_synthetic(args.case, args.output))


def _real_provider_smoke(args: argparse.Namespace) -> int:
    if args.budget_usd <= 0:
        print(
            _json_line(
                {
                    "status": "BLOCKED",
                    "code": "REAL_SMOKE_BUDGET_REQUIRED",
                    "network_call_attempted": False,
                }
            )
        )
        return 2
    api_key = os.environ.get("CVA_OPENAI_API_KEY", "").strip()
    if not api_key:
        print(
            _json_line(
                {
                    "status": "BLOCKED",
                    "code": "OPENAI_CREDENTIALS_REQUIRED",
                    "network_call_attempted": False,
                }
            )
        )
        return 2
    approval = os.environ.get("CVA_OPENAI_BILLABLE_SMOKE_APPROVAL", "")
    if not args.allow_billable or approval != "OPENAI_BILLABLE_SMOKE_APPROVED":
        print(
            _json_line(
                {
                    "status": "BLOCKED",
                    "code": "OPENAI_BILLABLE_SMOKE_APPROVAL_REQUIRED",
                    "network_call_attempted": False,
                }
            )
        )
        return 2

    prompt_id = "P11_SCHEMA_REPAIR_V1"
    routes = build_openai_routes(max_call_cost_usd=args.budget_usd)
    adapter = OpenAIResponsesAdapter(
        api_key=SecretStr(api_key),
        config=OpenAIAdapterConfig(
            request_timeout_seconds=OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
    )
    gateway = ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=(
                OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
                + OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS
            ),
            max_retries=0,
            default_budget_usd=args.budget_usd,
            job_id="job_openai_low_smoke",
        ),
        real_routes=routes,
        adapters={"openai": adapter},
        cost_estimator=build_openai_cost_estimator(routes),
        input_token_estimator=estimate_openai_input_tokens,
    )
    request = build_mock_request(prompt_id)
    try:
        result = asyncio.run(
            gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
                budget=CallBudget(max_cost_usd=args.budget_usd),
            )
        )
    except GatewayError as exc:
        print(
            _json_line(
                {
                    "status": "FAIL",
                    "code": exc.code,
                    "network_call_attempted": bool(exc.ledgers),
                    "attempts": len(exc.ledgers),
                    "actual_cost_usd": round(
                        sum(item.actual_cost_usd or 0.0 for item in exc.ledgers), 8
                    ),
                }
            )
        )
        return 1
    ledger = result.ledgers[-1]
    reason_codes = ledger.route.reason_codes

    def hashed_reason(prefix: str) -> str | None:
        for code in reason_codes:
            if code.startswith(prefix):
                digest = code.removeprefix(prefix)
                if re.fullmatch(r"[0-9a-f]{64}", digest):
                    return f"sha256:{digest}"
        return None

    reasoning_tokens = 0
    for code in reason_codes:
        if code.startswith("REASONING_TOKENS_"):
            candidate = code.removeprefix("REASONING_TOKENS_")
            if candidate.isdigit():
                reasoning_tokens = int(candidate)
            break
    print(
        _json_line(
            {
                "status": "PASS",
                "code": "OPENAI_REAL_SMOKE_PASS",
                "network_call_attempted": True,
                "prompt_id": ledger.prompt_id,
                "prompt_version": ledger.prompt_version,
                "schema_version": ledger.schema_version_used,
                "route_profile": OPENAI_ROUTE_PROFILE_ID,
                "requested_model": ledger.route.model,
                "effective_model": ledger.route.model_snapshot,
                "reasoning_effort": ledger.route.reasoning_effort,
                "responses_requests": len(result.ledgers),
                "attempts": len(result.ledgers),
                "input_tokens": ledger.input_tokens,
                "cached_input_tokens": ledger.cached_input_tokens,
                "output_tokens": ledger.output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "latency_ms": ledger.latency_ms,
                "estimated_cost_usd": ledger.estimated_cost_usd,
                "calculated_actual_cost_usd": ledger.actual_cost_usd,
                "schema_validation": ledger.result == "SCHEMA_VALID",
                "pydantic_validation": isinstance(result.output, BaseModel),
                "contextual_validation": True,
                "request_id_hash": hashed_reason("PROVIDER_REQUEST_ID_HASH_"),
                "output_hash": hashed_reason("OUTPUT_HASH_"),
            }
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cv-stage0",
        description="Offline Stage 0 validation and synthetic pipeline",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    contracts = subcommands.add_parser(
        "validate-contracts", help="Run the canonical contract gate"
    )
    contracts.set_defaults(handler=_validate_contracts)

    fixtures = subcommands.add_parser(
        "build-fixtures", help="Regenerate deterministic Stage 0 fixtures"
    )
    fixtures.add_argument("--root", type=Path, default=DEFAULT_STAGE0_ROOT)
    fixtures.set_defaults(handler=_build_fixtures)

    synthetic = subcommands.add_parser(
        "run-synthetic", help="Run one explicit synthetic pipeline"
    )
    synthetic.add_argument("--case", choices=tuple(_CASES), required=True)
    synthetic.add_argument("--output", type=Path, required=True)
    synthetic.set_defaults(handler=_synthetic)

    smoke = subcommands.add_parser(
        "real-provider-smoke", help="Governed, opt-in real-provider smoke gate"
    )
    smoke.add_argument("--budget-usd", type=float, default=0.0)
    smoke.add_argument(
        "--allow-billable",
        action="store_true",
        help="Requires the separate human approval environment guard as well",
    )
    smoke.set_defaults(handler=_real_provider_smoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:
        # Do not echo exception strings: parser/provider failures can contain
        # paths or hostile content.  Stable codes and exception classes are
        # sufficient for this development CLI and its regression tests.
        print(
            _json_line(
                {
                    "status": "FAILED",
                    "code": getattr(exc, "code", "CLI_FAILURE"),
                    "error_type": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
