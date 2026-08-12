"""Product-shaped P04-P09 synthetic rehearsal over production boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, SecretStr

from .canonical import canonical_hash, stable_id
from .contracts import model_by_name, models as m
from .model_gateway import (
    CallBudget,
    GatewayCallResult,
    GatewayContextError,
    GatewayError,
    GatewayConfig,
    GatewayMode,
    GatewaySchemaViolation,
    ModelGateway,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
    ProviderBudgetError,
    build_openai_cost_estimator,
    build_openai_routes,
    build_mock_request,
    build_trusted_context,
    estimate_openai_input_tokens,
)
from .model_gateway.registry import PROMPT_VERSION, prompt_spec
from .model_gateway.gateway import PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS
from .planning import PLANNER_VERSION, build_assessment_plan
from .validation import (
    ContextValidationError,
    PROMPT_APPLICATION_VALIDATOR_VERSIONS,
    validate_assessment_plan,
    validate_evaluation_guide,
    validate_evidence_map,
    validate_generation_result,
    validate_review_result,
)
from .web.workflows import (
    ASSEMBLER_VERSION,
    assemble_assessment_snapshot,
    selected_question_from_candidate,
)


REHEARSAL_VERSION = "stage2-product-rehearsal/1.0.0"
REHEARSAL_REPORT_VERSION = "stage2-convergence-report/1.0.0"
BASE_SCENARIO_ID = "synthetic-open-short-v1"
VARIANT_SCENARIO_ID = "synthetic-choice-justification-v1"


@dataclass(frozen=True, slots=True)
class RehearsalCheckpoints:
    scenario_id: str
    p04_request: m.BlueprintBuildRequest
    p06_request: m.EvidenceMapRequest
    p07_request: m.QuestionBuildRequest
    p08_request: m.QuestionReviewRequest
    p09_request: m.GuideBuildRequest

    @property
    def hashes(self) -> dict[str, str]:
        return {
            "post_p03": canonical_hash(
                self.p04_request.model_dump(mode="json")
            ),
            "blueprint_valid": canonical_hash(
                self.p06_request.model_dump(mode="json")
            ),
            "mapping_planning_valid": canonical_hash(
                {
                    "p07": self.p07_request.model_dump(mode="json"),
                    "p08": self.p08_request.model_dump(mode="json"),
                }
            ),
            "assessment_valid": canonical_hash(
                self.p09_request.model_dump(mode="json")
            ),
        }


@dataclass(frozen=True, slots=True)
class RehearsalObservation:
    run_id: str
    run_kind: str
    scenario_id: str
    status: str
    stages: tuple[dict[str, Any], ...]
    failure: dict[str, Any] | None
    output_hash: str | None


def _validated_mock_output(prompt_id: str, request: BaseModel) -> BaseModel:
    """Produce a canonical checkpoint dependency without network transport."""

    from .model_gateway import DeterministicMockFactory, MockBehavior

    return DeterministicMockFactory().output_for(
        prompt_id, request, MockBehavior.HAPPY
    )


def _base_p04_request() -> m.BlueprintBuildRequest:
    return m.BlueprintBuildRequest.model_validate(
        build_mock_request("P04_BLUEPRINT_BUILD_V1").model_dump(mode="json")
    )


def build_rehearsal_checkpoints(
    scenario_id: str = BASE_SCENARIO_ID,
) -> RehearsalCheckpoints:
    """Build reproducible canonical checkpoints A-D from product contracts."""

    if scenario_id not in {BASE_SCENARIO_ID, VARIANT_SCENARIO_ID}:
        raise ValueError("unknown synthetic rehearsal scenario")
    p04 = _base_p04_request()
    if scenario_id == VARIANT_SCENARIO_ID:
        policy = p04.blueprint_policy.model_copy(
            update={
                "policy_id": "blueprint_policy_choice_variant",
                "allowed_response_formats": [m.ResponseFormat.CHOICE],
                "structured_justification_policy": (
                    m.StructuredJustificationPolicy(
                        mode=m.StructuredJustificationMode.ALL,
                        selected_opportunity_template_ids=[],
                    )
                ),
            }
        )
        p04 = p04.model_copy(
            update={
                "target_blueprint_id": "blueprint_choice_variant",
                "target_blueprint_version": 1,
                "blueprint_policy": policy,
            }
        )

    p06 = m.EvidenceMapRequest.model_validate(
        build_mock_request("P06_EVIDENCE_MAP_V1").model_dump(mode="json")
    )
    mapping = m.EvidenceMapPatch.model_validate(
        _validated_mock_output("P06_EVIDENCE_MAP_V1", p06).model_dump(
            mode="json"
        )
    )
    validate_evidence_map(
        mapping,
        blueprint=p06.blueprint,
        bundle=p06.evidence_bundle,
    )
    plan = build_assessment_plan(
        mapping=mapping,
        blueprint=p06.blueprint,
        policy=m.AssessmentPlanningPolicy(
            policy_id="planning_policy_checkpoint",
            minimum_opportunity_quality=(
                p06.blueprint.assessment_constraints.minimum_opportunity_quality
            ),
            max_reserve_opportunities=(
                p06.blueprint.assessment_constraints.max_reserve_opportunities
            ),
        ),
    )
    validate_assessment_plan(plan, mapping=mapping)
    opportunity_by_id = {
        opportunity.opportunity_id: opportunity
        for opportunity in mapping.opportunities
    }
    opportunity = opportunity_by_id[plan.selected_opportunity_ids[0]]
    p07 = m.QuestionBuildRequest(
        target_candidate_id="candidate_checkpoint",
        plan=plan,
        opportunity=opportunity,
        evidence_bundle=p06.evidence_bundle,
        generation_policy=m.QuestionGenerationPolicy(
            policy_id="question_generation_checkpoint"
        ),
        avoid=[],
    )
    generation = m.QuestionGenerationResult.model_validate(
        _validated_mock_output("P07_QUESTION_BUILD_V1", p07).model_dump(
            mode="json"
        )
    )
    validate_generation_result(
        generation,
        opportunity=opportunity,
        bundle=p06.evidence_bundle,
    )
    p08 = m.QuestionReviewRequest(
        generation_result=generation,
        opportunity=opportunity,
        evidence_bundle=p06.evidence_bundle,
        validation_policy=m.QuestionValidationPolicy(
            policy_id="question_validation_checkpoint"
        ),
    )
    p09 = m.GuideBuildRequest.model_validate(
        build_mock_request("P09_GUIDE_BUILD_V1").model_dump(mode="json")
    )
    return RehearsalCheckpoints(
        scenario_id=scenario_id,
        p04_request=p04,
        p06_request=p06,
        p07_request=p07,
        p08_request=p08,
        p09_request=p09,
    )


def rehearsal_boundary_material() -> dict[str, Any]:
    checkpoints = {
        scenario: build_rehearsal_checkpoints(scenario).hashes
        for scenario in (BASE_SCENARIO_ID, VARIANT_SCENARIO_ID)
    }
    prompt_material = {
        prompt_id: {
            "version": prompt_spec(prompt_id).prompt_version,
            "hash": prompt_spec(prompt_id).prompt_hash,
            "input_schema_hash": canonical_hash(
                model_by_name(
                    prompt_spec(prompt_id).input_schema_name
                ).model_json_schema(mode="validation")
            ),
            "output_schema_hash": canonical_hash(
                model_by_name(
                    prompt_spec(prompt_id).output_schema_name
                ).model_json_schema(mode="validation")
            ),
            "relationship_validator": (
                PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS[prompt_id]
            ),
            "application_validator": (
                PROMPT_APPLICATION_VALIDATOR_VERSIONS.get(prompt_id)
            ),
        }
        for prompt_id in (
            "P04_BLUEPRINT_BUILD_V1",
            "P05_BLUEPRINT_REVIEW_V1",
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P08_QUESTION_REVIEW_V1",
            "P09_GUIDE_BUILD_V1",
        )
    }
    return {
        "rehearsal_version": REHEARSAL_VERSION,
        "prompt_pack_version": PROMPT_VERSION,
        "planner_version": PLANNER_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "checkpoints": checkpoints,
        "prompts": prompt_material,
        "p10_enabled": False,
    }


def _safe_failure(error: Exception, *, stage: str) -> dict[str, Any]:
    codes: list[str] = []
    issues: list[dict[str, str]] = []
    if isinstance(error, GatewayContextError):
        codes.extend(code.value for code in error.failure.codes)
    elif isinstance(error, GatewaySchemaViolation):
        codes.append(error.code)
        if error.primary_failure is not None:
            codes.append(error.primary_failure.code)
            issues.extend(
                {
                    "error_type": issue.error_type,
                    "path": issue.path,
                }
                for issue in error.primary_failure.issues
            )
            issues.extend(
                {
                    "error_type": issue.error_type,
                    "path": issue.path,
                }
                for issue in error.primary_failure.provider_schema_issues
            )
    elif isinstance(error, ContextValidationError):
        codes.append(error.code)
    elif isinstance(error, GatewayError):
        codes.append(error.code)
    else:
        codes.append(type(error).__name__.upper())
    return {
        "stage": stage,
        "codes": list(dict.fromkeys(codes)),
        "issues": list(
            {
                (item["error_type"], item["path"]): item
                for item in issues
            }.values()
        ),
    }


class ProductRehearsal:
    """Execute independent sweeps and integrated chains through one gateway."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        max_call_cost_usd: float,
        max_total_cost_usd: float | None = None,
    ) -> None:
        self.gateway = gateway
        self.max_call_cost_usd = max_call_cost_usd
        self.max_total_cost_usd = max_total_cost_usd
        self.results: list[GatewayCallResult] = []

    async def _invoke(
        self,
        prompt_id: str,
        request: BaseModel,
    ) -> BaseModel:
        spent = sum(
            ledger.actual_cost_usd
            for result in self.results
            for ledger in result.ledgers
        )
        remaining = (
            self.max_call_cost_usd
            if self.max_total_cost_usd is None
            else min(
                self.max_call_cost_usd,
                max(0.0, self.max_total_cost_usd - spent),
            )
        )
        result = await self.gateway.invoke(
            prompt_id,
            request,
            build_trusted_context(request),
            budget=CallBudget(max_cost_usd=remaining),
        )
        self.results.append(result)
        return result.output

    def _stage_row(
        self,
        prompt_id: str,
        request: BaseModel,
        output: BaseModel,
    ) -> dict[str, Any]:
        result = self.results[-1]
        ledger = result.ledgers[-1]
        return {
            "prompt_id": prompt_id,
            "prompt_version": prompt_spec(prompt_id).prompt_version,
            "input_hash": canonical_hash(request.model_dump(mode="json")),
            "output_hash": canonical_hash(output.model_dump(mode="json")),
            "status": "PASS",
            "model": ledger.route.model,
            "reasoning_effort": ledger.route.reasoning_effort.value,
            "fallback_route_id": ledger.route.fallback_route_id,
            "attempts": len(result.ledgers),
            "repaired": result.repaired,
            "actual_cost_usd": round(
                sum(item.actual_cost_usd for item in result.ledgers), 10
            ),
        }

    async def run_sweep(
        self,
        *,
        run_id: str,
        scenario_id: str = BASE_SCENARIO_ID,
    ) -> RehearsalObservation:
        checkpoints = build_rehearsal_checkpoints(scenario_id)
        stages: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        async def observe(
            stage: str,
            callback: Any,
        ) -> Any | None:
            try:
                return await callback()
            except Exception as exc:  # content-free aggregation boundary
                failures.append(_safe_failure(exc, stage=stage))
                return None

        async def blueprint_checkpoint() -> None:
            p04 = checkpoints.p04_request
            blueprint = cast(
                m.AssessmentBlueprint,
                await self._invoke("P04_BLUEPRINT_BUILD_V1", p04),
            )
            if blueprint.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "P04_NOT_READY", "P04 checkpoint did not produce READY"
                )
            stages.append(
                self._stage_row("P04_BLUEPRINT_BUILD_V1", p04, blueprint)
            )
            p05 = m.BlueprintReviewRequest(
                activity_spec=p04.activity_spec,
                rubric_spec=p04.rubric_spec,
                blueprint_policy=p04.blueprint_policy,
                resolved_decisions=p04.resolved_decisions,
                blueprint=blueprint,
            )
            review = cast(
                m.BlueprintReview,
                await self._invoke("P05_BLUEPRINT_REVIEW_V1", p05),
            )
            if (
                review.status != m.WorkflowStatus.READY
                or review.approval_recommendation
                != m.BlueprintApprovalRecommendation.APPROVE
            ):
                raise ContextValidationError(
                    "P05_NOT_APPROVABLE",
                    "P05 checkpoint did not produce an approvable review",
                )
            stages.append(
                self._stage_row("P05_BLUEPRINT_REVIEW_V1", p05, review)
            )

        async def evidence_checkpoint() -> None:
            request = checkpoints.p06_request
            mapping = cast(
                m.EvidenceMapPatch,
                await self._invoke("P06_EVIDENCE_MAP_V1", request),
            )
            validate_evidence_map(
                mapping,
                blueprint=request.blueprint,
                bundle=request.evidence_bundle,
            )
            stages.append(
                self._stage_row("P06_EVIDENCE_MAP_V1", request, mapping)
            )

        async def question_checkpoint() -> None:
            p07 = checkpoints.p07_request
            generation = cast(
                m.QuestionGenerationResult,
                await self._invoke("P07_QUESTION_BUILD_V1", p07),
            )
            validate_generation_result(
                generation,
                opportunity=p07.opportunity,
                bundle=p07.evidence_bundle,
            )
            stages.append(
                self._stage_row("P07_QUESTION_BUILD_V1", p07, generation)
            )
            p08 = checkpoints.p08_request.model_copy(
                update={"generation_result": generation}
            )
            review = cast(
                m.QuestionReviewResult,
                await self._invoke("P08_QUESTION_REVIEW_V1", p08),
            )
            validate_review_result(
                review,
                generation_result=generation,
                validation_policy=p08.validation_policy,
            )
            stages.append(
                self._stage_row("P08_QUESTION_REVIEW_V1", p08, review)
            )

        async def guide_checkpoint() -> None:
            request = checkpoints.p09_request
            guide = cast(
                m.EvaluationGuide,
                await self._invoke("P09_GUIDE_BUILD_V1", request),
            )
            validate_evaluation_guide(
                guide,
                assessment=request.assessment,
                bundle=request.evidence_bundle,
            )
            stages.append(
                self._stage_row("P09_GUIDE_BUILD_V1", request, guide)
            )

        await observe("P04_P05", blueprint_checkpoint)
        await observe("P06", evidence_checkpoint)
        await observe("P07_P08", question_checkpoint)
        await observe("P09", guide_checkpoint)
        return RehearsalObservation(
            run_id=run_id,
            run_kind="INDEPENDENT_SWEEP",
            scenario_id=scenario_id,
            status="PASS" if not failures else "FAIL",
            stages=tuple(stages),
            failure=(
                {"aggregated_failures": failures} if failures else None
            ),
            output_hash=(canonical_hash(stages) if not failures else None),
        )

    async def run_chain(
        self,
        *,
        run_id: str,
        scenario_id: str = BASE_SCENARIO_ID,
    ) -> RehearsalObservation:
        checkpoints = build_rehearsal_checkpoints(scenario_id)
        stages: list[dict[str, Any]] = []
        current_stage = "P04"
        try:
            p04 = checkpoints.p04_request
            blueprint = cast(
                m.AssessmentBlueprint,
                await self._invoke("P04_BLUEPRINT_BUILD_V1", p04),
            )
            if blueprint.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "P04_NOT_READY", "P04 chain output is not READY"
                )
            stages.append(
                self._stage_row("P04_BLUEPRINT_BUILD_V1", p04, blueprint)
            )

            current_stage = "P05"
            p05 = m.BlueprintReviewRequest(
                activity_spec=p04.activity_spec,
                rubric_spec=p04.rubric_spec,
                blueprint_policy=p04.blueprint_policy,
                resolved_decisions=p04.resolved_decisions,
                blueprint=blueprint,
            )
            blueprint_review = cast(
                m.BlueprintReview,
                await self._invoke("P05_BLUEPRINT_REVIEW_V1", p05),
            )
            if (
                blueprint_review.status != m.WorkflowStatus.READY
                or blueprint_review.approval_recommendation
                != m.BlueprintApprovalRecommendation.APPROVE
            ):
                raise ContextValidationError(
                    "P05_NOT_APPROVABLE",
                    "P05 chain output is not approvable",
                )
            stages.append(
                self._stage_row(
                    "P05_BLUEPRINT_REVIEW_V1", p05, blueprint_review
                )
            )
            approved_blueprint = blueprint.model_copy(
                update={"status": m.WorkflowStatus.APPROVED}
            )

            current_stage = "P06"
            p06 = checkpoints.p06_request.model_copy(
                update={"blueprint": approved_blueprint}
            )
            mapping = cast(
                m.EvidenceMapPatch,
                await self._invoke("P06_EVIDENCE_MAP_V1", p06),
            )
            validate_evidence_map(
                mapping,
                blueprint=approved_blueprint,
                bundle=p06.evidence_bundle,
            )
            stages.append(
                self._stage_row("P06_EVIDENCE_MAP_V1", p06, mapping)
            )

            current_stage = "PLANNER"
            plan = build_assessment_plan(
                mapping=mapping,
                blueprint=approved_blueprint,
                policy=p04.blueprint_policy.planning_policy,
            )
            validate_assessment_plan(plan, mapping=mapping)
            if plan.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "ASSESSMENT_PLAN_INFEASIBLE",
                    "planner did not produce a complete plan",
                )
            stages.append(
                {
                    "stage": "PLANNER",
                    "version": PLANNER_VERSION,
                    "input_hash": canonical_hash(
                        {
                            "mapping": mapping.model_dump(mode="json"),
                            "blueprint": approved_blueprint.model_dump(
                                mode="json"
                            ),
                            "policy": p04.blueprint_policy.planning_policy.model_dump(
                                mode="json"
                            ),
                        }
                    ),
                    "output_hash": canonical_hash(
                        plan.model_dump(mode="json")
                    ),
                    "status": "PASS",
                }
            )
            opportunity_by_id = {
                opportunity.opportunity_id: opportunity
                for opportunity in mapping.opportunities
            }
            selected: list[m.SelectedQuestion] = []
            for index, opportunity_id in enumerate(
                plan.selected_opportunity_ids
            ):
                opportunity = opportunity_by_id[opportunity_id]
                current_stage = "P07"
                p07 = m.QuestionBuildRequest(
                    target_candidate_id=stable_id(
                        "candidate",
                        run_id,
                        opportunity.opportunity_id,
                        index,
                    ),
                    plan=plan,
                    opportunity=opportunity,
                    evidence_bundle=p06.evidence_bundle,
                    generation_policy=m.QuestionGenerationPolicy(
                        policy_id=stable_id(
                            "generation-policy", scenario_id
                        )
                    ),
                    avoid=[],
                )
                generation = cast(
                    m.QuestionGenerationResult,
                    await self._invoke("P07_QUESTION_BUILD_V1", p07),
                )
                validate_generation_result(
                    generation,
                    opportunity=opportunity,
                    bundle=p06.evidence_bundle,
                )
                if generation.candidate is None:
                    raise ContextValidationError(
                        "P07_NO_CANDIDATE",
                        "P07 chain output has no candidate",
                    )
                stages.append(
                    self._stage_row(
                        "P07_QUESTION_BUILD_V1", p07, generation
                    )
                )

                current_stage = "P08"
                p08 = m.QuestionReviewRequest(
                    generation_result=generation,
                    opportunity=opportunity,
                    evidence_bundle=p06.evidence_bundle,
                    validation_policy=m.QuestionValidationPolicy(
                        policy_id=stable_id(
                            "validation-policy", scenario_id
                        )
                    ),
                )
                question_review = cast(
                    m.QuestionReviewResult,
                    await self._invoke("P08_QUESTION_REVIEW_V1", p08),
                )
                validate_review_result(
                    question_review,
                    generation_result=generation,
                    validation_policy=p08.validation_policy,
                )
                if (
                    question_review.review is None
                    or question_review.review.decision
                    != m.ReviewDecision.ACCEPT
                ):
                    raise ContextValidationError(
                        "P08_NOT_ACCEPTED",
                        "P08 chain output is not accepted",
                    )
                stages.append(
                    self._stage_row(
                        "P08_QUESTION_REVIEW_V1", p08, question_review
                    )
                )
                selected.append(
                    selected_question_from_candidate(
                        generation.candidate,
                        opportunity,
                        submission_id=mapping.submission_id,
                    )
                )

            current_stage = "ASSEMBLY"
            prompt_versions = {
                row["prompt_id"]: row["prompt_version"]
                for row in stages
                if "prompt_id" in row
            }
            model_snapshots = {
                row["prompt_id"]: row["model"]
                for row in stages
                if "prompt_id" in row
            }
            assessment = assemble_assessment_snapshot(
                tenant_id=p06.evidence_bundle.tenant_id,
                activity_id=p04.activity_spec.activity_id,
                submission_id=p06.evidence_bundle.submission_id,
                subject_ref=stable_id("subject", scenario_id),
                created_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
                blueprint=approved_blueprint,
                plan=plan,
                mapping=mapping,
                questions=selected,
                assignment_prompt_hashes=["sha256:" + "a" * 64],
                rubric_hashes=["sha256:" + "b" * 64],
                submission_hashes=["sha256:" + "c" * 64],
                submission_media_type="text/markdown",
                prompt_versions=prompt_versions,
                model_snapshots=model_snapshots,
                policy_hash=canonical_hash(
                    p04.blueprint_policy.model_dump(mode="json")
                ),
            )
            stages.append(
                {
                    "stage": "ASSEMBLY",
                    "version": ASSEMBLER_VERSION,
                    "input_hash": canonical_hash(
                        {
                            "plan": plan.model_dump(mode="json"),
                            "mapping": mapping.model_dump(mode="json"),
                            "questions": [
                                item.model_dump(mode="json")
                                for item in selected
                            ],
                        }
                    ),
                    "output_hash": canonical_hash(
                        assessment.model_dump(mode="json")
                    ),
                    "status": "PASS",
                }
            )

            current_stage = "P09"
            p09 = m.GuideBuildRequest(
                guide_id=stable_id("guide", assessment.assessment_id),
                assessment=assessment,
                evidence_bundle=p06.evidence_bundle,
            )
            guide = cast(
                m.EvaluationGuide,
                await self._invoke("P09_GUIDE_BUILD_V1", p09),
            )
            validate_evaluation_guide(
                guide,
                assessment=assessment,
                bundle=p06.evidence_bundle,
            )
            if guide.status != m.WorkflowStatus.READY:
                raise ContextValidationError(
                    "P09_NOT_READY", "P09 chain output is not READY"
                )
            stages.append(
                self._stage_row("P09_GUIDE_BUILD_V1", p09, guide)
            )
        except Exception as exc:
            return RehearsalObservation(
                run_id=run_id,
                run_kind="INTEGRATED_CHAIN",
                scenario_id=scenario_id,
                status="FAIL",
                stages=tuple(stages),
                failure=_safe_failure(exc, stage=current_stage),
                output_hash=None,
            )
        return RehearsalObservation(
            run_id=run_id,
            run_kind="INTEGRATED_CHAIN",
            scenario_id=scenario_id,
            status="PASS",
            stages=tuple(stages),
            failure=None,
            output_hash=canonical_hash(stages),
        )

    def controls(self) -> dict[str, Any]:
        ledgers = [
            ledger
            for result in self.results
            for ledger in result.ledgers
        ]
        return {
            "p10_calls": sum(
                ledger.prompt_id == "P10_ENRICHED_CONTEXT_V1"
                for ledger in ledgers
            ),
            "p11_calls": sum(
                ledger.prompt_id == "P11_SCHEMA_REPAIR_V1"
                for ledger in ledgers
            ),
            "fallback_calls": sum(
                ledger.route.fallback_route_id is not None
                for ledger in ledgers
            ),
            "semantic_retries": 0,
            "provider_attempts": len(ledgers),
            "actual_cost_usd": round(
                sum(ledger.actual_cost_usd for ledger in ledgers), 10
            ),
            "models": sorted({ledger.route.model for ledger in ledgers}),
        }


async def run_offline_convergence() -> dict[str, Any]:
    """Run sweep, two unchanged chains and one distinct variant with mocks."""

    from .model_gateway import GatewayConfig, GatewayMode

    gateway = ModelGateway(
        GatewayConfig(
            mode=GatewayMode.MOCK,
            max_retries=0,
            job_id="job_stage2_offline_convergence",
        )
    )
    rehearsal = ProductRehearsal(gateway, max_call_cost_usd=1.0)
    observations = [
        await rehearsal.run_sweep(run_id="sweep-base"),
        await rehearsal.run_chain(run_id="chain-base-1"),
        await rehearsal.run_chain(run_id="chain-base-2"),
        await rehearsal.run_chain(
            run_id="chain-choice-variant",
            scenario_id=VARIANT_SCENARIO_ID,
        ),
    ]
    controls = rehearsal.controls()
    status = (
        "PASS"
        if all(item.status == "PASS" for item in observations)
        and controls["p10_calls"] == 0
        and controls["p11_calls"] == 0
        and controls["fallback_calls"] == 0
        else "FAIL"
    )
    return {
        "report_schema_version": REHEARSAL_REPORT_VERSION,
        "rehearsal_version": REHEARSAL_VERSION,
        "mode": "offline-convergence",
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "status": status,
        "boundary": rehearsal_boundary_material(),
        "observations": [
            {
                "run_id": item.run_id,
                "run_kind": item.run_kind,
                "scenario_id": item.scenario_id,
                "status": item.status,
                "stages": list(item.stages),
                "failure": item.failure,
                "output_hash": item.output_hash,
            }
            for item in observations
        ],
        "controls": controls,
    }


def run_offline_convergence_sync() -> dict[str, Any]:
    return asyncio.run(run_offline_convergence())


class RequestCappedAdapter:
    """Enforce the execution-wide provider-request ceiling before transport."""

    def __init__(self, inner: OpenAIResponsesAdapter, *, max_requests: int) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self.inner = inner
        self.max_requests = max_requests
        self.calls = 0

    async def invoke(self, **kwargs: Any) -> Any:
        if self.calls >= self.max_requests:
            raise ProviderBudgetError("EVALUATION_REQUEST_CAP_EXCEEDED")
        self.calls += 1
        return await self.inner.invoke(**kwargs)


async def run_real_convergence(
    *,
    api_key: SecretStr,
    max_total_cost_usd: float,
    max_call_cost_usd: float,
    max_provider_requests: int,
) -> dict[str, Any]:
    """Run the same convergence matrix with Luna and strict transport caps."""

    if max_total_cost_usd <= 0 or max_call_cost_usd <= 0:
        raise ValueError("positive real-evaluation cost caps are required")
    if max_call_cost_usd > max_total_cost_usd:
        raise ValueError("per-call cost cap cannot exceed total cost cap")
    routes = build_openai_routes(max_call_cost_usd=max_call_cost_usd)
    capped_adapter = RequestCappedAdapter(
        OpenAIResponsesAdapter(
            api_key=api_key,
            config=OpenAIAdapterConfig(request_timeout_seconds=300.0),
        ),
        max_requests=max_provider_requests,
    )
    gateway = ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=305.0,
            max_retries=0,
            default_budget_usd=max_call_cost_usd,
            job_id="job_stage2_real_convergence",
        ),
        real_routes=routes,
        adapters={"openai": capped_adapter},
        cost_estimator=build_openai_cost_estimator(routes),
        input_token_estimator=estimate_openai_input_tokens,
    )
    rehearsal = ProductRehearsal(
        gateway,
        max_call_cost_usd=max_call_cost_usd,
        max_total_cost_usd=max_total_cost_usd,
    )
    executable_boundary_hash = canonical_hash(rehearsal_boundary_material())
    observations = [
        await rehearsal.run_sweep(run_id="real-sweep-base"),
        await rehearsal.run_chain(run_id="real-chain-base-1"),
        await rehearsal.run_chain(run_id="real-chain-base-2"),
        await rehearsal.run_chain(
            run_id="real-chain-choice-variant",
            scenario_id=VARIANT_SCENARIO_ID,
        ),
    ]
    controls = rehearsal.controls()
    controls.update(
        {
            "network_calls": capped_adapter.calls,
            "max_provider_requests": max_provider_requests,
            "max_total_cost_usd": max_total_cost_usd,
            "max_call_cost_usd": max_call_cost_usd,
            "gateway_retries": 0,
            "sdk_retries": 0,
            "tools_enabled": False,
            "store": False,
        }
    )
    boundary_after_hash = canonical_hash(rehearsal_boundary_material())
    unchanged_boundary = executable_boundary_hash == boundary_after_hash
    status = (
        "PASS"
        if all(item.status == "PASS" for item in observations)
        and controls["p10_calls"] == 0
        and controls["p11_calls"] == 0
        and controls["fallback_calls"] == 0
        and controls["semantic_retries"] == 0
        and unchanged_boundary
        and controls["actual_cost_usd"] <= max_total_cost_usd
        else "FAIL"
    )
    return {
        "report_schema_version": REHEARSAL_REPORT_VERSION,
        "rehearsal_version": REHEARSAL_VERSION,
        "mode": "real-convergence",
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "status": status,
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "executable_boundary_hash": executable_boundary_hash,
        "unchanged_boundary_across_chains": unchanged_boundary,
        "boundary": rehearsal_boundary_material(),
        "observations": [
            {
                "run_id": item.run_id,
                "run_kind": item.run_kind,
                "scenario_id": item.scenario_id,
                "status": item.status,
                "stages": list(item.stages),
                "failure": item.failure,
                "output_hash": item.output_hash,
            }
            for item in observations
        ],
        "controls": controls,
    }
