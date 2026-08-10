"""Stage 2 orchestration layered over the verified Stage 0/1 pipelines.

This module keeps new experimental commands explicit while reusing the
canonical parser, planner, gateway and evidence-first approval boundaries.
Persisted domain objects always use the canonical contract module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import csv
import io
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any, Iterable, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..canonical import canonical_hash, sha256_bytes, stable_id
from ..contracts import models as m
from ..diagnostics import diagnostic
from ..exports import RENDERER_VERSION, render_views
from ..validation import (
    ContextValidationError,
    validate_evaluation_guide,
    validate_question_candidate,
    validate_review_result,
)
from .auth import Actor
from .repository import (
    ActivityRow,
    AssessmentPlanRow,
    AssessmentRow,
    AuditEventRow,
    Conflict,
    EvidenceMapRow,
    EvidenceRow,
    ExportRow,
    GuideRow,
    JobControlRecordRow,
    JobRow,
    ModelCallRow,
    NotFound,
    QuestionReviewActionRow,
    StageRunRow,
    SubmissionRow,
    utc_now,
)
from .workflows import Stage1Service, WorkflowError


_FAIL_CLOSED_STATUSES = {
    m.SubmissionProcessingStatus.INSUFFICIENT_RELEVANT_EVIDENCE,
    m.SubmissionProcessingStatus.INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES,
    m.SubmissionProcessingStatus.EVIDENCE_MAPPING_UNCERTAIN,
    m.SubmissionProcessingStatus.ASSESSMENT_PLAN_INFEASIBLE,
    m.SubmissionProcessingStatus.REJECTED_SECURITY,
}

_QUESTION_ACTION_DESCRIPTOR_VERSION = "stage2-question-action-descriptor/1.0.0"
_QUESTION_ACTION_DESCRIPTOR_POLICY_HASH = canonical_hash(
    {
        "kind": "QUESTION_ACTION_DESCRIPTOR",
        "version": _QUESTION_ACTION_DESCRIPTOR_VERSION,
    }
)


def _etag(value: Any) -> str:
    return f'"{canonical_hash(value)}"'


def _percentile(values: Iterable[int], percentile: float) -> int:
    ordered = sorted(max(0, int(value)) for value in values)
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.999)))
    return ordered[index]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> int:
    if started_at is None or finished_at is None:
        return 0
    started_at = _as_utc(started_at)
    finished_at = _as_utc(finished_at)
    if finished_at < started_at:
        return 0
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


class Stage2Service:
    """Application service for the explicitly opened E2 gate."""

    def __init__(self, legacy: Stage1Service) -> None:
        self.legacy = legacy
        self.repository = legacy.repository
        self.object_store = legacy.object_store
        self.settings = legacy.settings

    @staticmethod
    def _require_teacher(actor: Actor) -> None:
        if actor.role not in {"OWNER", "TEACHER"}:
            raise WorkflowError(
                "ROLE_FORBIDDEN",
                "Only an authorized teacher may perform this Stage 2 action.",
                status_code=403,
            )

    @staticmethod
    def _require_reviewer(actor: Actor) -> None:
        if actor.role not in {"OWNER", "TEACHER", "ASSISTANT"}:
            raise WorkflowError(
                "ROLE_FORBIDDEN",
                "Only an authorized reviewer may perform this action.",
                status_code=403,
            )

    def create_submissions(
        self,
        *,
        activity_id: str,
        subject_refs: list[str],
        actor: Actor,
    ) -> list[SubmissionRow]:
        """Create one manual batch atomically without leaking subject identity."""

        self._require_reviewer(actor)
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        if not 1 <= len(subject_refs) <= self.settings.max_batch_submissions:
            raise WorkflowError(
                "SUBMISSION_BATCH_SIZE_INVALID",
                "The manual batch size is outside the configured experimental bound.",
            )
        normalized: list[str] = []
        for value in subject_refs:
            try:
                normalized.append(TypeAdapter(m.Id).validate_python(value))
            except ValidationError as exc:
                raise WorkflowError(
                    "SUBJECT_REF_INVALID",
                    "Every subject reference must be a pseudonymous identifier.",
                ) from exc
        if len(normalized) != len(set(normalized)):
            raise WorkflowError(
                "SUBMISSION_BATCH_DUPLICATE",
                "A manual batch cannot repeat a subject reference.",
                status_code=409,
            )
        rows: list[SubmissionRow] = []
        for subject_ref in normalized:
            submission_id = stable_id(
                "sub", actor.workspace_id, activity_id, subject_ref
            )
            state = m.SubmissionProcessingState(
                submission_id=submission_id,
                activity_id=activity_id,
                status=m.SubmissionProcessingStatus.UPLOADED,
                progress=0.0,
                updated_at=utc_now(),
            )
            rows.append(
                SubmissionRow(
                    id=submission_id,
                    tenant_id=actor.workspace_id,
                    activity_id=activity_id,
                    subject_ref=subject_ref,
                    state=state.model_dump(mode="json"),
                )
            )
        try:
            return self.repository.create_submissions(rows)
        except Conflict as exc:
            code = str(exc) if str(exc).isupper() else "SUBMISSION_BATCH_CONFLICT"
            raise WorkflowError(
                code,
                "The batch conflicts with an existing pseudonymous submission.",
                status_code=409,
            ) from exc

    def submissions(
        self,
        *,
        activity_id: str,
        actor: Actor,
        status: m.SubmissionProcessingStatus | None = None,
        subject_ref: str | None = None,
    ) -> list[SubmissionRow]:
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        rows = self.repository.submissions_for_activity(
            activity_id, actor.workspace_id
        )
        if status is not None:
            rows = [
                row
                for row in rows
                if m.SubmissionProcessingState.model_validate(row.state).status == status
            ]
        if subject_ref is not None:
            try:
                expected = TypeAdapter(m.Id).validate_python(subject_ref)
            except ValidationError as exc:
                raise WorkflowError(
                    "SUBJECT_REF_INVALID",
                    "The subject filter must be a pseudonymous identifier.",
                ) from exc
            rows = [row for row in rows if row.subject_ref == expected]
        return rows

    def _submission_inputs(
        self, submission: SubmissionRow
    ) -> tuple[
        m.AssessmentBlueprint,
        m.EvidenceMapPatch | None,
        m.AssessmentPlan | None,
        AssessmentRow | None,
        m.Assessment | None,
    ]:
        blueprint_row, blueprint = self.legacy._approved_blueprint(
            activity_id=submission.activity_id,
            tenant_id=submission.tenant_id,
            version=submission.blueprint_version,
        )
        del blueprint_row
        try:
            mapping = m.EvidenceMapPatch.model_validate(
                cast(
                    EvidenceMapRow,
                    self.repository.scoped(
                        EvidenceMapRow, submission.id, submission.tenant_id
                    ),
                ).data
            )
        except NotFound:
            mapping = None
        try:
            plan = m.AssessmentPlan.model_validate(
                cast(
                    AssessmentPlanRow,
                    self.repository.scoped(
                        AssessmentPlanRow, submission.id, submission.tenant_id
                    ),
                ).data
            )
        except NotFound:
            plan = None
        try:
            assessment_row = self.repository.latest_assessment(
                submission.id, submission.tenant_id
            )
            assessment = m.Assessment.model_validate(assessment_row.data)
        except NotFound:
            assessment_row = None
            assessment = None
        return blueprint, mapping, plan, assessment_row, assessment

    @staticmethod
    def _coverage_summary(
        blueprint: m.AssessmentBlueprint,
        traces: list[m.CoverageTraceItem],
    ) -> list[m.CoverageItem]:
        result: list[m.CoverageItem] = []
        for dimension in blueprint.dimensions:
            scoped = [item for item in traces if item.dimension_id == dimension.dimension_id]
            result.append(
                m.CoverageItem(
                    dimension_id=dimension.dimension_id,
                    available_variant_count=len({item.variant_id for item in scoped}),
                    available_opportunity_count=len(scoped),
                    selected_opportunity_count=sum(
                        item.planning_role == m.CoveragePlanningRole.PRIMARY
                        for item in scoped
                    ),
                    reused_variant_count=sum(item.reused_variant for item in scoped),
                    evidence_unit_count=len(
                        {
                            evidence_id
                            for item in scoped
                            for evidence_id in item.evidence_ids
                        }
                    ),
                    diagnostics=[],
                )
            )
        return result

    def _coverage_traces(
        self,
        submission: SubmissionRow,
        *,
        blueprint: m.AssessmentBlueprint,
        mapping: m.EvidenceMapPatch | None,
        plan: m.AssessmentPlan | None,
        assessment_row: AssessmentRow | None,
        assessment: m.Assessment | None,
    ) -> list[m.CoverageTraceItem]:
        if mapping is None:
            return []
        primary_ids = set(plan.selected_opportunity_ids if plan else [])
        reserve_ids = set(plan.reserve_opportunity_ids if plan else [])
        selected_by_opportunity = {
            item.opportunity_id: item for item in assessment.questions
        } if assessment is not None else {}
        variant_use = Counter(
            item.variant_id for item in selected_by_opportunity.values()
        )
        dimension_by_id = {item.dimension_id: item for item in blueprint.dimensions}

        latest_actions: dict[str, str] = {}
        if assessment is not None:
            for row in self.repository.question_review_actions(
                tenant_id=submission.tenant_id,
                assessment_id=assessment.assessment_id,
            ):
                try:
                    payload = dict(row.data)
                    action_payload = payload.get("action", payload)
                    action = m.QuestionReviewAction.model_validate(action_payload)
                except (TypeError, ValidationError):
                    continue
                latest_actions[action.question_id] = action.action.value

        traces: list[m.CoverageTraceItem] = []
        for opportunity in mapping.opportunities:
            selected = selected_by_opportunity.get(opportunity.opportunity_id)
            if opportunity.opportunity_id in primary_ids:
                planning_role = m.CoveragePlanningRole.PRIMARY
            elif opportunity.opportunity_id in reserve_ids:
                planning_role = m.CoveragePlanningRole.RESERVE
            else:
                planning_role = m.CoveragePlanningRole.EXCLUDED

            failure_code: str | None = None
            exclusion_code: str | None = None
            if planning_role == m.CoveragePlanningRole.EXCLUDED:
                outcome = m.CoverageOutcome.EXCLUDED
                exclusion_code = "NOT_SELECTED_BY_PLAN"
            elif selected is not None:
                if assessment is not None and assessment.status == m.WorkflowStatus.APPROVED:
                    outcome = m.CoverageOutcome.APPROVED
                elif latest_actions.get(selected.question_id) in {
                    m.QuestionReviewActionType.ACCEPT.value,
                    m.QuestionReviewActionType.EDIT.value,
                    m.QuestionReviewActionType.REGENERATE.value,
                }:
                    outcome = m.CoverageOutcome.REVIEWED
                else:
                    outcome = m.CoverageOutcome.GENERATED
            elif assessment is not None and planning_role == m.CoveragePlanningRole.PRIMARY:
                outcome = m.CoverageOutcome.FAILED
                failure_code = "QUESTION_REPLACED_OR_REJECTED"
            else:
                outcome = m.CoverageOutcome.PLANNED

            dimension = dimension_by_id[opportunity.dimension_id]
            traces.append(
                m.CoverageTraceItem(
                    submission_id=submission.id,
                    assessment_id=(
                        assessment.assessment_id if assessment is not None else None
                    ),
                    assessment_version=(
                        assessment_row.version if assessment_row is not None else None
                    ),
                    dimension_id=opportunity.dimension_id,
                    criterion_ids=list(dimension.criterion_ids),
                    variant_id=opportunity.variant_id,
                    opportunity_id=opportunity.opportunity_id,
                    evidence_ids=list(opportunity.evidence_ids),
                    cognitive_operation=opportunity.cognitive_operation,
                    planning_role=planning_role,
                    outcome=outcome,
                    reused_variant=(
                        selected is not None
                        and variant_use[opportunity.variant_id] > 1
                    ),
                    failure_code=failure_code,
                    exclusion_reason_code=exclusion_code,
                    diagnostics=[],
                )
            )
        return traces

    def coverage_for_submission(
        self, submission_id: str, actor: Actor
    ) -> m.CoverageReport:
        submission = cast(
            SubmissionRow,
            self.repository.scoped(
                SubmissionRow, submission_id, actor.workspace_id
            ),
        )
        blueprint, mapping, plan, assessment_row, assessment = self._submission_inputs(
            submission
        )
        traces = self._coverage_traces(
            submission,
            blueprint=blueprint,
            mapping=mapping,
            plan=plan,
            assessment_row=assessment_row,
            assessment=assessment,
        )
        snapshot = {
            "blueprint": blueprint.model_dump(mode="json"),
            "mapping": mapping.model_dump(mode="json") if mapping else None,
            "plan": plan.model_dump(mode="json") if plan else None,
            "assessment": assessment.model_dump(mode="json") if assessment else None,
            "assessment_version": assessment_row.version if assessment_row else None,
        }
        return m.CoverageReport(
            report_id=stable_id(
                "coverage", actor.workspace_id, submission.id, canonical_hash(snapshot)
            ),
            tenant_id=actor.workspace_id,
            activity_id=submission.activity_id,
            scope=m.CoverageScope.SUBMISSION,
            submission_id=submission.id,
            assessment_id=assessment.assessment_id if assessment else None,
            assessment_version=assessment_row.version if assessment_row else None,
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.blueprint_version,
            source_snapshot_hash=canonical_hash(snapshot),
            summary=self._coverage_summary(blueprint, traces),
            traces=traces,
            diagnostics=[],
            generated_at=utc_now(),
        )

    def coverage_for_activity(
        self, activity_id: str, actor: Actor
    ) -> m.CoverageReport:
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        blueprint_row, blueprint = self.legacy._approved_blueprint(
            activity_id=activity_id, tenant_id=actor.workspace_id
        )
        traces: list[m.CoverageTraceItem] = []
        diagnostics: list[m.Diagnostic] = []
        snapshots: list[dict[str, Any]] = []
        for submission in self.repository.submissions_for_activity(
            activity_id, actor.workspace_id
        ):
            if submission.blueprint_version not in {None, blueprint_row.version}:
                diagnostics.append(
                    diagnostic(
                        "COVERAGE_BLUEPRINT_VERSION_EXCLUDED",
                        "A submission bound to another blueprint version is excluded from this activity snapshot.",
                    )
                )
                continue
            _, mapping, plan, assessment_row, assessment = self._submission_inputs(
                submission
            )
            scoped = self._coverage_traces(
                submission,
                blueprint=blueprint,
                mapping=mapping,
                plan=plan,
                assessment_row=assessment_row,
                assessment=assessment,
            )
            traces.extend(scoped)
            snapshots.append(
                {
                    "submission_id": submission.id,
                    "mapping": mapping.model_dump(mode="json") if mapping else None,
                    "plan": plan.model_dump(mode="json") if plan else None,
                    "assessment": assessment.model_dump(mode="json") if assessment else None,
                    "assessment_version": assessment_row.version if assessment_row else None,
                }
            )
        source_hash = canonical_hash(
            {"blueprint": blueprint.model_dump(mode="json"), "submissions": snapshots}
        )
        return m.CoverageReport(
            report_id=stable_id(
                "coverage", actor.workspace_id, activity_id, source_hash
            ),
            tenant_id=actor.workspace_id,
            activity_id=activity_id,
            scope=m.CoverageScope.ACTIVITY,
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.blueprint_version,
            source_snapshot_hash=source_hash,
            summary=self._coverage_summary(blueprint, traces),
            traces=traces,
            diagnostics=diagnostics,
            generated_at=utc_now(),
        )

    def record_feedback(
        self,
        *,
        activity_id: str,
        target_type: m.FeedbackTargetType,
        category: m.FeedbackCategory,
        rating: m.FeedbackRating,
        actor: Actor,
        assessment_id: str | None = None,
        assessment_version: int | None = None,
        question_id: str | None = None,
        comment: str | None = None,
    ) -> m.FeedbackEvent:
        self._require_reviewer(actor)
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        if target_type != m.FeedbackTargetType.ACTIVITY:
            if assessment_id is None or assessment_version is None:
                raise WorkflowError(
                    "FEEDBACK_TARGET_INVALID",
                    "Assessment feedback requires an exact assessment version.",
                )
            assessment_row = self.repository.assessment_by_id(
                assessment_id, actor.workspace_id
            )
            if (
                assessment_row.version != assessment_version
                or m.Assessment.model_validate(assessment_row.data).activity_id
                != activity_id
            ):
                raise WorkflowError(
                    "FEEDBACK_TARGET_INVALID",
                    "The feedback target does not match the requested activity/version.",
                    status_code=409,
                )
            if target_type == m.FeedbackTargetType.QUESTION:
                assessment = m.Assessment.model_validate(assessment_row.data)
                if question_id is None or question_id not in {
                    item.question_id for item in assessment.questions
                }:
                    raise WorkflowError(
                        "FEEDBACK_TARGET_INVALID",
                        "Question feedback requires a question in the exact assessment version.",
                        status_code=409,
                    )
            if target_type == m.FeedbackTargetType.QUESTION:
                assessment = m.Assessment.model_validate(assessment_row.data)
                if question_id not in {item.question_id for item in assessment.questions}:
                    raise WorkflowError(
                        "FEEDBACK_TARGET_INVALID",
                        "The feedback question does not belong to the assessment.",
                        status_code=404,
                    )
        created_at = utc_now()
        event = m.FeedbackEvent(
            feedback_id=stable_id(
                "feedback",
                actor.workspace_id,
                actor.user_id,
                activity_id,
                assessment_id,
                question_id,
                created_at,
            ),
            tenant_id=actor.workspace_id,
            activity_id=activity_id,
            assessment_id=assessment_id,
            assessment_version=assessment_version,
            question_id=question_id,
            target_type=target_type,
            actor_id=actor.user_id,
            category=category,
            rating=rating,
            comment=comment,
            created_at=created_at,
        )
        self.repository.add_feedback_event(event)
        return event

    def feedback_for_activity(
        self, activity_id: str, actor: Actor
    ) -> list[m.FeedbackEvent]:
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        values: list[m.FeedbackEvent] = []
        for row in self.repository.feedback_events(
            tenant_id=actor.workspace_id, activity_id=activity_id
        ):
            try:
                event = m.FeedbackEvent.model_validate(row.data)
            except ValidationError:
                continue
            if event.activity_id == activity_id:
                values.append(event)
        return values

    def experiment_metrics(
        self, activity_id: str, actor: Actor
    ) -> m.ExperimentMetrics:
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        submissions = self.repository.submissions_for_activity(
            activity_id, actor.workspace_id
        )
        submission_ids = {item.id for item in submissions}
        aggregate_ids = {activity_id, *submission_ids}
        with self.repository.session() as session:
            jobs = list(
                session.scalars(
                    select(JobRow).where(
                        JobRow.tenant_id == actor.workspace_id,
                        JobRow.aggregate_id.in_(aggregate_ids),
                    )
                )
            )
            job_ids = {item.id for item in jobs}
            stage_runs = (
                list(
                    session.scalars(
                        select(StageRunRow).where(
                            StageRunRow.tenant_id == actor.workspace_id,
                            StageRunRow.job_id.in_(job_ids),
                        )
                    )
                )
                if job_ids
                else []
            )
            model_rows = (
                list(
                    session.scalars(
                        select(ModelCallRow).where(
                            ModelCallRow.tenant_id == actor.workspace_id,
                            ModelCallRow.job_id.in_(job_ids),
                        )
                    )
                )
                if job_ids
                else []
            )
            assessments = (
                list(
                    session.scalars(
                        select(AssessmentRow).where(
                            AssessmentRow.tenant_id == actor.workspace_id,
                            AssessmentRow.submission_id.in_(submission_ids),
                        )
                    )
                )
                if submission_ids
                else []
            )
            actions = (
                list(
                    session.scalars(
                        select(QuestionReviewActionRow).where(
                            QuestionReviewActionRow.tenant_id == actor.workspace_id,
                            QuestionReviewActionRow.submission_id.in_(submission_ids),
                        )
                    )
                )
                if submission_ids
                else []
            )
            plans = (
                list(
                    session.scalars(
                        select(AssessmentPlanRow).where(
                            AssessmentPlanRow.tenant_id == actor.workspace_id,
                            AssessmentPlanRow.submission_id.in_(submission_ids),
                        )
                    )
                )
                if submission_ids
                else []
            )
            audit_rows = (
                list(
                    session.scalars(
                        select(AuditEventRow).where(
                            AuditEventRow.tenant_id == actor.workspace_id,
                            AuditEventRow.aggregate_id.in_(
                                {item.assessment_id for item in assessments}
                            ),
                        )
                    )
                )
                if assessments
                else []
            )
            control_rows = (
                list(
                    session.scalars(
                        select(JobControlRecordRow).where(
                            JobControlRecordRow.tenant_id == actor.workspace_id,
                            JobControlRecordRow.job_id.in_(job_ids),
                            JobControlRecordRow.action == "RETRY",
                            JobControlRecordRow.status == "APPLIED",
                        )
                    )
                )
                if job_ids
                else []
            )

        model_calls = [m.ModelCallLedger.model_validate(row.data) for row in model_rows]
        job_latencies = [_duration_ms(row.started_at, row.finished_at) for row in jobs]
        technical = m.TechnicalMetricAggregate(
            job_count=len(jobs),
            succeeded_count=sum(row.status == "SUCCEEDED" for row in jobs),
            failed_count=sum(
                row.status == "FAILED" and row.control_state != "CANCELLED"
                for row in jobs
            ),
            cancelled_count=sum(row.control_state == "CANCELLED" for row in jobs),
            retry_count=len(control_rows),
            latency_p50_ms=_percentile(job_latencies, 0.50),
            latency_p95_ms=_percentile(job_latencies, 0.95),
            input_tokens=sum(item.input_tokens for item in model_calls),
            cached_input_tokens=sum(item.cached_input_tokens for item in model_calls),
            output_tokens=sum(item.output_tokens for item in model_calls),
            estimated_cost_usd=sum(item.estimated_cost_usd for item in model_calls),
            actual_cost_usd=sum(item.actual_cost_usd or 0.0 for item in model_calls),
        )

        latest_assessments: dict[str, AssessmentRow] = {}
        for row in assessments:
            current = latest_assessments.get(row.assessment_id)
            if current is None or row.version > current.version:
                latest_assessments[row.assessment_id] = row
        states = [m.SubmissionProcessingState.model_validate(row.state) for row in submissions]
        defect_codes = {
            item.get("code")
            for row in jobs
            for item in (row.diagnostics or [])
            if item.get("severity") in {"ERROR", "CRITICAL"}
        }
        action_types: list[m.QuestionReviewActionType] = []
        action_records: list[m.QuestionReviewActionRecord] = []
        for row in actions:
            payload = dict(row.data)
            try:
                record = m.QuestionReviewActionRecord.model_validate(payload)
            except ValidationError:
                continue
            action_records.append(record)
            action_types.append(record.action.action)
        fail_closed_count = sum(item.status in _FAIL_CLOSED_STATUSES for item in states)
        ready_plan_count = sum(
            m.AssessmentPlan.model_validate(row.data).status == "READY"
            for row in plans
        )
        quality = m.QualityMetricAggregate(
            assessment_count=len(latest_assessments),
            fail_closed_count=fail_closed_count,
            defect_count=len({value for value in defect_codes if value}),
            # A READY plan still being processed is not yet an observable
            # assessment outcome and therefore is excluded from the quality
            # aggregate until it reaches assessment or fail-closed state.
            exact_plan_count=min(
                ready_plan_count, len(latest_assessments) + fail_closed_count
            ),
            replacement_count=sum(
                record.status == m.QuestionReviewRecordStatus.APPLIED
                and record.action.action == m.QuestionReviewActionType.REGENERATE
                for record in action_records
            ),
        )

        opened_by_assessment: dict[str, datetime] = {}
        closed_by_assessment: dict[str, datetime] = {}
        for event in audit_rows:
            if event.event_type == "assessment.review.opened":
                occurred_at = _as_utc(event.occurred_at)
                opened_by_assessment[event.aggregate_id] = min(
                    occurred_at,
                    opened_by_assessment.get(event.aggregate_id, occurred_at),
                )
            elif event.event_type in {
                "assessment.approved",
                "assessment.bulk_approved",
            }:
                occurred_at = _as_utc(event.occurred_at)
                closed_by_assessment[event.aggregate_id] = max(
                    occurred_at,
                    closed_by_assessment.get(event.aggregate_id, occurred_at),
                )
        review_seconds = sum(
            max(0, int((closed_by_assessment[key] - started).total_seconds()))
            for key, started in opened_by_assessment.items()
            if key in closed_by_assessment and closed_by_assessment[key] >= started
        )
        human = m.HumanReviewMetricAggregate(
            reviewed_question_count=len(
                {
                    (row.assessment_id, row.question_id)
                    for row in actions
                }
            ),
            accepted_count=sum(
                value == m.QuestionReviewActionType.ACCEPT for value in action_types
            ),
            edited_count=sum(
                value == m.QuestionReviewActionType.EDIT for value in action_types
            ),
            rejected_count=sum(
                value == m.QuestionReviewActionType.REJECT for value in action_types
            ),
            regenerated_count=sum(
                value == m.QuestionReviewActionType.REGENERATE for value in action_types
            ),
            review_seconds=review_seconds,
        )

        by_stage_values: list[m.StageMetricAggregate] = []
        retry_job_ids = {
            row.resulting_job_id
            for row in control_rows
            if row.resulting_job_id is not None
        }
        stage_groups: dict[str, list[StageRunRow]] = defaultdict(list)
        for row in stage_runs:
            stage_groups[row.stage.split(":", 1)[0]].append(row)
        for stage, rows in sorted(stage_groups.items()):
            latencies = [_duration_ms(row.started_at, row.finished_at) for row in rows]
            by_stage_values.append(
                m.StageMetricAggregate(
                    stage=stage,
                    runs=len(rows),
                    succeeded=sum(row.status == "SUCCEEDED" for row in rows),
                    failed=sum(row.status == "FAILED" for row in rows),
                    cancelled=sum(row.status == "CANCELLED" for row in rows),
                    retries=sum(row.job_id in retry_job_ids for row in rows),
                    latency_p50_ms=_percentile(latencies, 0.50),
                    latency_p95_ms=_percentile(latencies, 0.95),
                )
            )

        model_groups: dict[tuple[str, str], list[m.ModelCallLedger]] = defaultdict(list)
        for item in model_calls:
            model_groups[(item.route.route_id, item.route.model_snapshot)].append(item)
        by_model_values: list[m.ModelMetricAggregate] = []
        for (_route_id, _snapshot), items in sorted(model_groups.items()):
            route = items[0].route
            latencies = [item.latency_ms for item in items]
            by_model_values.append(
                m.ModelMetricAggregate(
                    route_id=route.route_id,
                    provider=route.provider,
                    model=route.model,
                    model_snapshot=route.model_snapshot,
                    call_count=len(items),
                    schema_valid_count=sum(item.result == "SCHEMA_VALID" for item in items),
                    error_count=sum(item.result != "SCHEMA_VALID" for item in items),
                    input_tokens=sum(item.input_tokens for item in items),
                    cached_input_tokens=sum(item.cached_input_tokens for item in items),
                    output_tokens=sum(item.output_tokens for item in items),
                    latency_p50_ms=_percentile(latencies, 0.50),
                    latency_p95_ms=_percentile(latencies, 0.95),
                    estimated_cost_usd=sum(item.estimated_cost_usd for item in items),
                    actual_cost_usd=sum(item.actual_cost_usd or 0.0 for item in items),
                )
            )

        observed_times = [
            *(_as_utc(row.created_at) for row in jobs),
            *(_as_utc(row.created_at) for row in assessments),
            *(_as_utc(row.occurred_at) for row in actions),
        ]
        now = utc_now()
        window_start = min(observed_times) if observed_times else now
        window_end = max([*observed_times, now])
        return m.ExperimentMetrics(
            metrics_id=stable_id(
                "metrics", actor.workspace_id, activity_id, window_start, window_end
            ),
            tenant_id=actor.workspace_id,
            activity_id=activity_id,
            technical=technical,
            quality=quality,
            human_review=human,
            by_stage=by_stage_values,
            by_model=by_model_values,
            window_start=window_start,
            window_end=window_end,
            generated_at=utc_now(),
        )

    def assessment_review_view(
        self, submission_id: str, actor: Actor
    ) -> dict[str, Any]:
        """Return the legacy review bundle and record content-free review time."""

        value = self.legacy.assessment_view(submission_id, actor)
        assessment = m.Assessment.model_validate(value["assessment"])
        if not self.repository.audit_events(
            tenant_id=actor.workspace_id,
            event_type="assessment.review.opened",
            aggregate_id=assessment.assessment_id,
            actor_id=actor.user_id,
        ):
            self.repository.audit(
                tenant_id=actor.workspace_id,
                event_type="assessment.review.opened",
                aggregate_id=assessment.assessment_id,
                actor_id=actor.user_id,
                payload={"assessment_version": int(value["assessment_version"])},
            )
        return value

    def assert_no_unresolved_question_action(
        self, assessment_id: str, actor: Actor
    ) -> None:
        """Block individual approval after a rejection or failed revalidation."""

        self.repository.assessment_by_id(assessment_id, actor.workspace_id)
        latest: dict[str, m.QuestionReviewActionRecord] = {}
        for row in self.repository.question_review_actions(
            tenant_id=actor.workspace_id, assessment_id=assessment_id
        ):
            record = m.QuestionReviewActionRecord.model_validate(row.data)
            latest[record.action.question_id] = record
        if any(
            record.status == m.QuestionReviewRecordStatus.FAILED
            or record.action.action == m.QuestionReviewActionType.REJECT
            for record in latest.values()
        ):
            raise WorkflowError(
                "QUESTION_REVIEW_REQUIRED",
                "A rejected or failed question action requires individual resolution.",
                status_code=409,
            )

    def _evidence_bundle(
        self, submission: SubmissionRow, assessment: m.Assessment
    ) -> m.EvidenceBundle:
        evidence = [
            m.EvidenceUnit.model_validate(row.data)
            for row in self.repository.evidence_for_submission(
                submission.id, submission.tenant_id
            )
        ]
        if not evidence:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "Question review requires the persisted evidence bundle.",
                status_code=409,
            )
        return m.EvidenceBundle(
            bundle_id=stable_id(
                "bundle",
                submission.id,
                [item.normalized_hash for item in evidence],
            ),
            tenant_id=submission.tenant_id,
            activity_id=submission.activity_id,
            submission_id=submission.id,
            context_mode=assessment.context_mode,
            allowed_evidence_ids=[item.evidence_id for item in evidence],
            evidence_units=evidence,
            course_passages=[],
        )

    @staticmethod
    def _candidate_from_selected(
        question: m.SelectedQuestion,
        *,
        submission_id: str,
    ) -> m.QuestionCandidate:
        return m.QuestionCandidate(
            candidate_id=question.source_candidate_id,
            submission_id=submission_id,
            opportunity_id=question.opportunity_id,
            opportunity_template_id=question.opportunity_template_id,
            dimension_id=question.dimension_id,
            variant_id=question.variant_id,
            cognitive_operation=question.cognitive_operation,
            response_format=question.response_format,
            difficulty=question.difficulty,
            estimated_minutes=question.estimated_minutes,
            question_text=question.question_text,
            anchor=question.anchor,
            evidence_ids=question.evidence_ids,
            course_source_ids=question.course_source_ids,
            citations=question.citations,
            choices=question.choices,
            student_justification_required=question.student_justification_required,
            preliminary_guide=question.preliminary_guide,
            uncertainties=[],
        )

    @staticmethod
    def _selected_from_candidate(
        candidate: m.QuestionCandidate,
        *,
        question_id: str,
        opportunity: m.QuestionOpportunity,
    ) -> m.SelectedQuestion:
        return m.SelectedQuestion(
            question_id=question_id,
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
            evidence_ids=candidate.evidence_ids,
            course_source_ids=candidate.course_source_ids,
            citations=candidate.citations,
            choices=candidate.choices,
            student_justification_required=candidate.student_justification_required,
            preliminary_guide=candidate.preliminary_guide,
            planning_score=(
                opportunity.activity_priority
                + opportunity.evidence_fit
                + opportunity.opportunity_quality
            )
            / 3,
        )

    def _question_action_job(
        self,
        *,
        submission: SubmissionRow,
        action: m.QuestionReviewAction,
        logical_action_id: str,
        assessment_version: int,
        assessment_etag: str,
    ) -> JobRow:
        job_id = stable_id(
            "job", submission.tenant_id, action.action_id, "QUESTION_ACTION"
        )
        status = m.JobStatus(
            job_id=job_id,
            tenant_id=submission.tenant_id,
            aggregate_id=submission.id,
            stage="QUESTION_GENERATE",
            status="RUNNING",
            progress=0.0,
            attempt=1,
            diagnostics=[],
            started_at=utc_now(),
        )
        self._prepare_question_action(
            status=status,
            submission=submission,
            action=action,
            logical_action_id=logical_action_id,
            assessment_version=assessment_version,
            assessment_etag=assessment_etag,
            create_job=True,
        )
        return cast(JobRow, self.repository.get(JobRow, job_id))

    def _prepare_question_action(
        self,
        *,
        status: m.JobStatus,
        submission: SubmissionRow,
        action: m.QuestionReviewAction,
        logical_action_id: str,
        assessment_version: int,
        assessment_etag: str,
        create_job: bool,
    ) -> None:
        """Persist a reconstructible source before localized provider work."""

        replacement_hash = (
            canonical_hash(action.replacement.model_dump(mode="json"))
            if action.replacement is not None
            else None
        )
        descriptor_inputs = {
            "action_id": action.action_id,
            "logical_action_id": logical_action_id,
            "assessment_id": action.assessment_id,
            "assessment_version": assessment_version,
            "assessment_etag": assessment_etag,
            "submission_id": submission.id,
            "activity_id": submission.activity_id,
            "question_id": action.question_id,
            "action_type": action.action.value,
            "actor_id": action.actor_id,
            "reason_code": action.reason_code,
            # Free-form notes and edited question text stay out of audit and
            # stage identity.  Their hashes bind the separately protected
            # descriptor output required to reconstruct an EDIT retry.
            "note_hash": canonical_hash(action.note) if action.note else None,
            "replacement_hash": replacement_hash,
        }
        descriptor_output = {
            "descriptor_version": _QUESTION_ACTION_DESCRIPTOR_VERSION,
            "tenant_id": status.tenant_id,
            "activity_id": submission.activity_id,
            "submission_id": submission.id,
            "assessment_id": action.assessment_id,
            "assessment_version": assessment_version,
            "assessment_etag": assessment_etag,
            "logical_action_id": logical_action_id,
            # This protected stage snapshot is not logged or returned by the
            # API.  It is necessary only because an EDIT retry cannot be
            # reconstructed from content-free IDs and hashes alone.
            "action": action.model_dump(mode="json"),
        }
        audit_payload = {
            "action_id": action.action_id,
            "logical_action_id": logical_action_id,
            "assessment_id": action.assessment_id,
            "assessment_version": assessment_version,
            "submission_id": submission.id,
            "question_id": action.question_id,
            "action_type": action.action.value,
            "descriptor_hash": canonical_hash(descriptor_output),
        }
        self.repository.prepare_question_action_job(
            status=status,
            max_attempts=self.settings.job_max_attempts,
            descriptor_inputs=descriptor_inputs,
            descriptor_output=descriptor_output,
            descriptor_component_version=_QUESTION_ACTION_DESCRIPTOR_VERSION,
            descriptor_policy_hash=_QUESTION_ACTION_DESCRIPTOR_POLICY_HASH,
            actor_id=action.actor_id,
            audit_payload=audit_payload,
            occurred_at=action.occurred_at,
            create_job=create_job,
        )

    def _lineage_after_job(
        self, lineage: m.Lineage, job: JobRow
    ) -> m.Lineage:
        ledgers = [
            m.ModelCallLedger.model_validate(item)
            for item in self.repository.model_calls(
                tenant_id=job.tenant_id, job_id=job.id
            )
        ]
        prompt_versions = dict(lineage.prompt_versions)
        model_snapshots = dict(lineage.model_snapshots)
        for item in ledgers:
            prompt_versions[item.prompt_id] = item.prompt_version
            model_snapshots[item.prompt_id] = item.route.model_snapshot
        return lineage.model_copy(
            update={
                "prompt_versions": prompt_versions,
                "model_snapshots": model_snapshots,
            }
        )

    @staticmethod
    def _assessment_row(
        assessment: m.Assessment,
        *,
        tenant_id: str,
        version: int,
    ) -> AssessmentRow:
        return AssessmentRow(
            row_id=stable_id("assessmentrow", assessment.assessment_id, version),
            assessment_id=assessment.assessment_id,
            tenant_id=tenant_id,
            submission_id=assessment.submission_id,
            version=version,
            status=assessment.status.value,
            etag=_etag(assessment),
            data=assessment.model_dump(mode="json"),
        )

    def _failed_question_action(
        self,
        *,
        action: m.QuestionReviewAction,
        assessment: m.Assessment,
        assessment_version: int,
        question: m.SelectedQuestion,
        diagnostics: list[m.Diagnostic],
        job: JobRow | None = None,
        failure_class: m.FailureClass = m.FailureClass.VALIDATION,
        retryable: bool = False,
    ) -> m.QuestionReviewActionRecord:
        record = m.QuestionReviewActionRecord(
            record_id=stable_id("reviewrecord", action.action_id),
            tenant_id=assessment.tenant_id,
            activity_id=assessment.activity_id,
            submission_id=assessment.submission_id,
            assessment_id=assessment.assessment_id,
            assessment_version_before=assessment_version,
            action=action,
            status=m.QuestionReviewRecordStatus.FAILED,
            revalidation_status=m.RevalidationStatus.FAILED,
            before_question=question,
            lineage_before=assessment.lineage,
            diagnostics=diagnostics,
            recorded_at=utc_now(),
        )
        stored = self.repository.apply_question_review_action(
            record,
            terminal_job=job,
            failure_class=failure_class if job is not None else None,
        )
        if stored is None:
            raise WorkflowError(
                "JOB_CANCELLED",
                "The localized question action stopped at a cancellation boundary.",
                status_code=409,
            )
        return record

    async def review_question(
        self,
        *,
        assessment_id: str,
        question_id: str,
        action_type: m.QuestionReviewActionType,
        actor: Actor,
        if_match: str,
        reason_code: str | None = None,
        note: str | None = None,
        replacement: m.SelectedQuestion | None = None,
        _execution_job: JobRow | None = None,
        _logical_action_id: str | None = None,
    ) -> m.QuestionReviewActionRecord:
        """Apply one canonical question action with server-side revalidation."""

        self._require_reviewer(actor)
        current = self.repository.assessment_by_id(
            assessment_id, actor.workspace_id
        )
        if current.etag != if_match:
            raise WorkflowError(
                "ETAG_MISMATCH", "Assessment has changed.", status_code=412
            )
        assessment = m.Assessment.model_validate(current.data)
        if assessment.status != m.WorkflowStatus.NEEDS_REVIEW:
            raise WorkflowError(
                "ASSESSMENT_NOT_REVIEWABLE",
                "Question actions require an assessment awaiting review.",
                status_code=409,
            )
        submission = cast(
            SubmissionRow,
            self.repository.scoped(
                SubmissionRow, assessment.submission_id, actor.workspace_id
            ),
        )
        if submission.activity_id != assessment.activity_id:
            raise WorkflowError(
                "CROSS_SUBMISSION_ASSESSMENT",
                "The assessment does not belong to the submission activity.",
                status_code=409,
            )
        if (
            m.SubmissionProcessingState.model_validate(submission.state).status
            != m.SubmissionProcessingStatus.NEEDS_REVIEW
        ):
            raise WorkflowError(
                "ASSESSMENT_SUBMISSION_NOT_REVIEWABLE",
                "The submission no longer permits question review.",
                status_code=409,
            )
        question_index = next(
            (
                index
                for index, value in enumerate(assessment.questions)
                if value.question_id == question_id
            ),
            None,
        )
        if question_index is None:
            raise WorkflowError(
                "QUESTION_NOT_FOUND",
                "The question does not belong to this assessment.",
                status_code=404,
            )
        before = assessment.questions[question_index]
        occurred_at = utc_now()
        action = m.QuestionReviewAction(
            action_id=stable_id(
                "reviewaction",
                actor.workspace_id,
                assessment_id,
                current.version,
                question_id,
                action_type.value,
                occurred_at,
            ),
            assessment_id=assessment_id,
            question_id=question_id,
            action=action_type,
            actor_id=actor.user_id,
            occurred_at=occurred_at,
            reason_code=reason_code,
            note=note,
            replacement=replacement,
        )

        if action_type == m.QuestionReviewActionType.ACCEPT:
            record = m.QuestionReviewActionRecord(
                record_id=stable_id("reviewrecord", action.action_id),
                tenant_id=actor.workspace_id,
                activity_id=assessment.activity_id,
                submission_id=assessment.submission_id,
                assessment_id=assessment_id,
                assessment_version_before=current.version,
                assessment_version_after=current.version,
                action=action,
                status=m.QuestionReviewRecordStatus.APPLIED,
                revalidation_status=m.RevalidationStatus.NOT_REQUIRED,
                before_question=before,
                after_question=before,
                lineage_before=assessment.lineage,
                lineage_after=assessment.lineage,
                diagnostics=[],
                recorded_at=utc_now(),
            )
            self.repository.apply_question_review_action(record)
            return record

        if action_type == m.QuestionReviewActionType.REJECT:
            revised = assessment.model_copy(update={"created_at": utc_now()})
            version = current.version + 1
            row = self._assessment_row(
                revised, tenant_id=actor.workspace_id, version=version
            )
            record = m.QuestionReviewActionRecord(
                record_id=stable_id("reviewrecord", action.action_id),
                tenant_id=actor.workspace_id,
                activity_id=assessment.activity_id,
                submission_id=assessment.submission_id,
                assessment_id=assessment_id,
                assessment_version_before=current.version,
                assessment_version_after=version,
                action=action,
                status=m.QuestionReviewRecordStatus.APPLIED,
                revalidation_status=m.RevalidationStatus.NOT_REQUIRED,
                before_question=before,
                lineage_before=assessment.lineage,
                lineage_after=assessment.lineage,
                diagnostics=[],
                recorded_at=utc_now(),
            )
            self.repository.apply_question_review_action(record, row)
            return record

        blueprint_row, blueprint = self.legacy._approved_blueprint(
            activity_id=assessment.activity_id,
            tenant_id=actor.workspace_id,
            version=assessment.lineage.blueprint_version,
        )
        del blueprint_row
        mapping = m.EvidenceMapPatch.model_validate(
            cast(
                EvidenceMapRow,
                self.repository.scoped(
                    EvidenceMapRow, submission.id, actor.workspace_id
                ),
            ).data
        )
        plan = m.AssessmentPlan.model_validate(
            cast(
                AssessmentPlanRow,
                self.repository.scoped(
                    AssessmentPlanRow, submission.id, actor.workspace_id
                ),
            ).data
        )
        opportunities = {item.opportunity_id: item for item in mapping.opportunities}
        bundle = self._evidence_bundle(submission, assessment)
        logical_action_id = _logical_action_id or action.action_id
        if _execution_job is None:
            job = self._question_action_job(
                submission=submission,
                action=action,
                logical_action_id=logical_action_id,
                assessment_version=current.version,
                assessment_etag=current.etag,
            )
        else:
            job = _execution_job
            self._prepare_question_action(
                status=self.repository.job_status(job.id, job.tenant_id),
                submission=submission,
                action=action,
                logical_action_id=logical_action_id,
                assessment_version=current.version,
                assessment_etag=current.etag,
                create_job=False,
            )
        validation_policy = m.QuestionValidationPolicy(
            policy_id=stable_id("policy", assessment.activity_id, "question_validation")
        )
        after: m.SelectedQuestion | None = None
        guide: m.EvaluationGuide | None = None
        try:
            if action_type == m.QuestionReviewActionType.EDIT:
                if replacement is None:
                    raise ContextValidationError(
                        "QUESTION_EDIT_INVALID", "The replacement question is missing."
                    )
                if any(
                    (
                        replacement.question_id != before.question_id,
                        replacement.opportunity_id != before.opportunity_id,
                        replacement.source_candidate_id != before.source_candidate_id,
                    )
                ):
                    raise ContextValidationError(
                        "QUESTION_EDIT_PATH_CHANGED",
                        "An edit must preserve the reviewed question and planned opportunity.",
                    )
                opportunity = opportunities.get(replacement.opportunity_id)
                if opportunity is None:
                    raise ContextValidationError(
                        "INVENTED_ID", "Edited question uses an unknown opportunity."
                    )
                candidate = self._candidate_from_selected(
                    replacement, submission_id=submission.id
                )
                validate_question_candidate(
                    candidate, opportunity=opportunity, bundle=bundle
                )
                generation = m.QuestionGenerationResult(
                    submission_id=submission.id,
                    opportunity_id=opportunity.opportunity_id,
                    context_mode=assessment.context_mode,
                    status="READY",
                    candidate=candidate,
                    diagnostics=[],
                )
            else:
                policy = m.BlueprintPolicy.model_validate(
                    cast(
                        ActivityRow,
                        self.repository.scoped(
                            ActivityRow, assessment.activity_id, actor.workspace_id
                        ),
                    ).blueprint_policy
                )
                previous_records = self.repository.question_review_actions(
                    tenant_id=actor.workspace_id,
                    assessment_id=assessment_id,
                    question_id=question_id,
                )
                execution_events = self.repository.audit_events(
                    tenant_id=actor.workspace_id,
                    event_type="question_action.executed",
                    aggregate_id=None,
                )
                logical_by_action = {
                    str(event.payload.get("action_id")): str(
                        event.payload.get("logical_action_id")
                        or event.payload.get("action_id")
                    )
                    for event in execution_events
                    if event.payload.get("action_id")
                }
                # New descriptors reserve the bounded logical regeneration
                # budget before provider work.  This remains enforceable even
                # when every terminal action transaction rolls back and there
                # is consequently no QuestionReviewActionRecord to count.
                regeneration_attempts: set[str] = {
                    str(
                        event.payload.get("logical_action_id")
                        or event.payload.get("action_id")
                    )
                    for event in execution_events
                    if event.payload.get("action_type")
                    == m.QuestionReviewActionType.REGENERATE.value
                    and event.payload.get("action_id") != action.action_id
                    and event.payload.get("assessment_id") == assessment_id
                    and event.payload.get("question_id") == question_id
                    and (
                        event.payload.get("logical_action_id")
                        or event.payload.get("action_id")
                    )
                }
                used_opportunities = {item.opportunity_id for item in assessment.questions}
                rejected: list[m.RejectedQuestionFingerprint] = []
                for row_value in previous_records:
                    try:
                        value = m.QuestionReviewActionRecord.model_validate(row_value.data)
                    except ValidationError:
                        continue
                    if (
                        value.action.action
                        == m.QuestionReviewActionType.REGENERATE
                    ):
                        # Failed provider/validation attempts consume the same
                        # bounded local budget as successful replacements.  A
                        # caller cannot evade the denial-of-wallet guard by
                        # rotating idempotency keys after failures.
                        regeneration_attempts.add(
                            logical_by_action.get(
                                value.action.action_id,
                                value.action.action_id,
                            )
                        )
                    if value.after_question is not None:
                        used_opportunities.add(value.after_question.opportunity_id)
                    rejected.append(
                        m.RejectedQuestionFingerprint(
                            fingerprint_id=stable_id(
                                "rejected", value.record_id, value.before_question.question_id
                            ),
                            opportunity_id=value.before_question.opportunity_id,
                            evidence_ids=value.before_question.evidence_ids,
                            normalized_question_hash=canonical_hash(
                                value.before_question.question_text.strip().lower()
                            ),
                            rejection_codes=[
                                value.action.reason_code or "TEACHER_REGENERATE"
                            ],
                        )
                    )
                if (
                    logical_action_id not in regeneration_attempts
                    and len(regeneration_attempts)
                    >= policy.max_local_regenerations
                ):
                    return self._failed_question_action(
                        action=action,
                        assessment=assessment,
                        assessment_version=current.version,
                        question=before,
                        diagnostics=[
                            diagnostic(
                                "LOCAL_REGENERATION_LIMIT",
                                "The configured localized regeneration limit was reached.",
                            )
                        ],
                        job=job,
                    )
                reserve_id = next(
                    (
                        value
                        for value in plan.reserve_opportunity_ids
                        if value not in used_opportunities
                        and opportunities[value].student_justification_required
                        == before.student_justification_required
                    ),
                    None,
                )
                if reserve_id is None:
                    return self._failed_question_action(
                        action=action,
                        assessment=assessment,
                        assessment_version=current.version,
                        question=before,
                        diagnostics=[
                            diagnostic(
                                "ASSESSMENT_PLAN_INFEASIBLE",
                                "No unused reserve opportunity can preserve exactly N.",
                            )
                        ],
                        job=job,
                    )
                opportunity = opportunities[reserve_id]
                rejected.append(
                    m.RejectedQuestionFingerprint(
                        fingerprint_id=stable_id(
                            "rejected", action.action_id, before.question_id
                        ),
                        opportunity_id=before.opportunity_id,
                        evidence_ids=before.evidence_ids,
                        normalized_question_hash=canonical_hash(
                            before.question_text.strip().lower()
                        ),
                        rejection_codes=[reason_code or "TEACHER_REGENERATE"],
                    )
                )
                generation = await self.legacy._gateway_stage(
                    job,
                    "P07_QUESTION_BUILD_V1",
                    m.QuestionBuildRequest(
                        plan=plan,
                        opportunity=opportunity,
                        evidence_bundle=bundle,
                        generation_policy=m.QuestionGenerationPolicy(
                            policy_id=stable_id(
                                "policy", assessment.activity_id, "question_generation"
                            ),
                            max_local_regenerations=policy.max_local_regenerations,
                        ),
                        avoid=rejected[-100:],
                    ),
                    m.QuestionGenerationResult,
                    cache_suffix=f"local-{logical_action_id}",
                )
                if generation.status != "READY" or generation.candidate is None:
                    return self._failed_question_action(
                        action=action,
                        assessment=assessment,
                        assessment_version=current.version,
                        question=before,
                        diagnostics=generation.diagnostics
                        or [
                            diagnostic(
                                "ASSESSMENT_PLAN_INFEASIBLE",
                                "The reserve opportunity did not produce a usable replacement.",
                            )
                        ],
                        job=job,
                    )
                validate_question_candidate(
                    generation.candidate, opportunity=opportunity, bundle=bundle
                )

            review = await self.legacy._gateway_stage(
                job,
                "P08_QUESTION_REVIEW_V1",
                m.QuestionReviewRequest(
                    generation_result=generation,
                    opportunity=opportunity,
                    evidence_bundle=bundle,
                    validation_policy=validation_policy,
                ),
                m.QuestionReviewResult,
                cache_suffix=f"local-{logical_action_id}",
            )
            validate_review_result(
                review,
                generation_result=generation,
                validation_policy=validation_policy,
            )
            if (
                review.status != "READY"
                or review.review is None
                or review.review.decision != m.ReviewDecision.ACCEPT
                or generation.candidate is None
            ):
                return self._failed_question_action(
                    action=action,
                    assessment=assessment,
                    assessment_version=current.version,
                    question=before,
                    diagnostics=review.diagnostics
                    or [
                        diagnostic(
                            "QUESTION_POLICY_VIOLATION",
                            "The edited or regenerated question did not pass semantic review.",
                        )
                    ],
                    job=job,
                )
            after = self._selected_from_candidate(
                generation.candidate,
                question_id=before.question_id,
                opportunity=opportunity,
            )
            if action_type == m.QuestionReviewActionType.EDIT and after != replacement:
                raise ContextValidationError(
                    "QUESTION_EDIT_INVALID",
                    "The validated edit differs from the submitted replacement.",
                )
            questions = list(assessment.questions)
            questions[question_index] = after
            opportunity_ids = [item.opportunity_id for item in questions]
            if len(opportunity_ids) != len(set(opportunity_ids)):
                raise ContextValidationError(
                    "ASSESSMENT_PLAN_INFEASIBLE",
                    "A localized action cannot duplicate a planned opportunity.",
                )
            lineage = self._lineage_after_job(assessment.lineage, job)
            required_question_ids = [
                item.question_id
                for item in questions
                if item.student_justification_required
            ]
            revised = assessment.model_copy(
                update={
                    "questions": questions,
                    "structured_justification": (
                        assessment.structured_justification.model_copy(
                            update={
                                "required_question_ids": required_question_ids
                            }
                        )
                    ),
                    "lineage": lineage,
                    "created_at": utc_now(),
                }
            )
            existing_guide = m.EvaluationGuide.model_validate(
                self.repository.guide_for_assessment(
                    assessment_id, actor.workspace_id
                ).data
            )
            guide = await self.legacy._gateway_stage(
                job,
                "P09_GUIDE_BUILD_V1",
                m.GuideBuildRequest(
                    guide_id=existing_guide.guide_id,
                    assessment=revised,
                    evidence_bundle=bundle,
                ),
                m.EvaluationGuide,
                cache_suffix=f"local-{logical_action_id}",
            )
            validate_evaluation_guide(guide, assessment=revised, bundle=bundle)
            revised = revised.model_copy(
                update={"lineage": self._lineage_after_job(revised.lineage, job)}
            )
        except (ContextValidationError, ValidationError, WorkflowError) as exc:
            failure_class, retryable, code = self.legacy._classify_failure(exc)
            return self._failed_question_action(
                action=action,
                assessment=assessment,
                assessment_version=current.version,
                question=before,
                diagnostics=[
                    diagnostic(
                        code,
                        "The localized question action failed required revalidation.",
                        retryable=retryable,
                    )
                ],
                job=job,
                failure_class=failure_class,
                retryable=retryable,
            )
        except Exception as exc:
            # Provider and adapter exceptions are deliberately collapsed so
            # neither hostile content nor provider detail enters persistence.
            failure_class, retryable, code = self.legacy._classify_failure(exc)
            return self._failed_question_action(
                action=action,
                assessment=assessment,
                assessment_version=current.version,
                question=before,
                diagnostics=[
                    diagnostic(
                        code,
                        "The localized question action could not be revalidated.",
                        retryable=retryable,
                    )
                ],
                job=job,
                failure_class=failure_class,
                retryable=retryable,
            )

        assert after is not None and guide is not None
        next_version = current.version + 1
        resulting_row = self._assessment_row(
            revised, tenant_id=actor.workspace_id, version=next_version
        )
        resulting_guide = GuideRow(
            guide_id=guide.guide_id,
            assessment_id=assessment_id,
            tenant_id=actor.workspace_id,
            submission_id=assessment.submission_id,
            data=guide.model_dump(mode="json"),
        )
        record = m.QuestionReviewActionRecord(
            record_id=stable_id("reviewrecord", action.action_id),
            tenant_id=actor.workspace_id,
            activity_id=assessment.activity_id,
            submission_id=assessment.submission_id,
            assessment_id=assessment_id,
            assessment_version_before=current.version,
            assessment_version_after=next_version,
            action=action,
            status=m.QuestionReviewRecordStatus.APPLIED,
            revalidation_status=m.RevalidationStatus.PASSED,
            before_question=before,
            after_question=after,
            lineage_before=assessment.lineage,
            lineage_after=revised.lineage,
            diagnostics=[],
            recorded_at=utc_now(),
        )
        try:
            stored = self.repository.apply_question_review_action(
                record,
                resulting_row,
                resulting_guide,
                terminal_job=job,
            )
            if stored is None:
                raise WorkflowError(
                    "JOB_CANCELLED",
                    "The localized question action stopped at a cancellation boundary.",
                    status_code=409,
                )
        except Exception as exc:
            failure_class, retryable, code = self.legacy._classify_failure(exc)
            return self._failed_question_action(
                action=action,
                assessment=assessment,
                assessment_version=current.version,
                question=before,
                diagnostics=[
                    diagnostic(
                        code or "QUESTION_ACTION_COMMIT_FAILED",
                        "The localized question result could not be committed.",
                        retryable=retryable,
                    )
                ],
                job=job,
                failure_class=failure_class,
                retryable=retryable,
            )
        return record

    async def process_question_action_retry(self, job: JobRow) -> None:
        """Execute one bounded durable retry of a localized review action."""

        controls = self.repository.job_control_records(
            tenant_id=job.tenant_id,
            resulting_job_id=job.id,
        )
        control = next(
            (
                item
                for item in controls
                if item.action == "RETRY" and item.status == "APPLIED"
            ),
            None,
        )
        if control is None:
            raise WorkflowError(
                "QUESTION_ACTION_RETRY_SOURCE_MISSING",
                "The localized retry has no durable source control record.",
                status_code=409,
            )
        source_action: m.QuestionReviewAction | None = None
        source_assessment_id: str | None = None
        source_assessment_version: int | None = None
        source_assessment_etag: str | None = None
        logical_action_id: str | None = None
        source_job_id = control.job_id
        seen_job_ids: set[str] = set()

        # A retry can itself fail before its descriptor transaction commits.
        # Walk the applied continuation chain backwards until the nearest
        # reconstructible attempt instead of turning that transient outage into
        # a permanent failure.
        while source_job_id not in seen_job_ids:
            seen_job_ids.add(source_job_id)
            descriptor_row = self.repository.question_action_descriptor(
                job_id=source_job_id, tenant_id=job.tenant_id
            )
            source_events = self.repository.audit_events(
                tenant_id=job.tenant_id,
                event_type="question_action.executed",
                aggregate_id=source_job_id,
            )
            if descriptor_row is not None and descriptor_row.output is not None:
                descriptor = descriptor_row.output
                try:
                    descriptor_action = m.QuestionReviewAction.model_validate(
                        descriptor["action"]
                    )
                    descriptor_version = int(descriptor["assessment_version"])
                    descriptor_logical_id = TypeAdapter(m.Id).validate_python(
                        descriptor["logical_action_id"]
                    )
                    descriptor_assessment_id = TypeAdapter(m.Id).validate_python(
                        descriptor["assessment_id"]
                    )
                    descriptor_etag = str(descriptor["assessment_etag"])
                except (KeyError, TypeError, ValueError, ValidationError) as exc:
                    raise WorkflowError(
                        "QUESTION_ACTION_RETRY_SOURCE_INVALID",
                        "The localized retry descriptor failed validation.",
                        status_code=409,
                    ) from exc
                source_event = next(
                    (
                        event
                        for event in reversed(source_events)
                        if event.payload.get("action_id")
                        == descriptor_action.action_id
                    ),
                    None,
                )
                if any(
                    (
                        descriptor.get("descriptor_version")
                        != _QUESTION_ACTION_DESCRIPTOR_VERSION,
                        descriptor.get("tenant_id") != job.tenant_id,
                        descriptor.get("submission_id") != job.aggregate_id,
                        descriptor_action.assessment_id
                        != descriptor_assessment_id,
                        descriptor_version < 1,
                        len(descriptor_etag) < 10,
                        source_event is None,
                        source_event is not None
                        and source_event.actor_id != descriptor_action.actor_id,
                        source_event is not None
                        and source_event.payload.get("logical_action_id")
                        != descriptor_logical_id,
                        source_event is not None
                        and source_event.payload.get("descriptor_hash")
                        != descriptor_row.output_hash,
                    )
                ):
                    raise WorkflowError(
                        "QUESTION_ACTION_RETRY_SOURCE_INVALID",
                        "The localized retry descriptor is inconsistent.",
                        status_code=409,
                    )
                try:
                    terminal_row = cast(
                        QuestionReviewActionRow,
                        self.repository.scoped(
                            QuestionReviewActionRow,
                            stable_id(
                                "reviewrecord", descriptor_action.action_id
                            ),
                            job.tenant_id,
                        ),
                    )
                except NotFound:
                    terminal_row = None
                if terminal_row is not None:
                    terminal_record = m.QuestionReviewActionRecord.model_validate(
                        terminal_row.data
                    )
                    if any(
                        (
                            terminal_record.status
                            != m.QuestionReviewRecordStatus.FAILED,
                            terminal_record.action != descriptor_action,
                            terminal_record.assessment_id
                            != descriptor_assessment_id,
                            terminal_record.assessment_version_before
                            != descriptor_version,
                        )
                    ):
                        raise WorkflowError(
                            "QUESTION_ACTION_NOT_RETRYABLE",
                            "Only a failed localized revalidation can be retried.",
                            status_code=409,
                        )
                source_action = descriptor_action
                source_assessment_id = descriptor_assessment_id
                source_assessment_version = descriptor_version
                source_assessment_etag = descriptor_etag
                logical_action_id = descriptor_logical_id
                break

            # Backward compatibility for terminal records created before the
            # durable descriptor was introduced.
            source_event = source_events[-1] if source_events else None
            if source_event is not None:
                source_action_id = str(source_event.payload.get("action_id") or "")
                if source_action_id:
                    try:
                        source_row = cast(
                            QuestionReviewActionRow,
                            self.repository.scoped(
                                QuestionReviewActionRow,
                                stable_id("reviewrecord", source_action_id),
                                job.tenant_id,
                            ),
                        )
                    except NotFound:
                        source_row = None
                    if source_row is not None:
                        source_record = (
                            m.QuestionReviewActionRecord.model_validate(
                                source_row.data
                            )
                        )
                        if (
                            source_record.status
                            != m.QuestionReviewRecordStatus.FAILED
                        ):
                            raise WorkflowError(
                                "QUESTION_ACTION_NOT_RETRYABLE",
                                "Only a failed localized revalidation can be retried.",
                                status_code=409,
                            )
                        source_action = source_record.action
                        source_assessment_id = source_record.assessment_id
                        source_assessment_version = (
                            source_record.assessment_version_before
                        )
                        logical_action_id = str(
                            source_event.payload.get("logical_action_id")
                            or source_action_id
                        )
                        break

            predecessor = next(
                (
                    item
                    for item in self.repository.job_control_records(
                        tenant_id=job.tenant_id,
                        resulting_job_id=source_job_id,
                    )
                    if item.action == "RETRY" and item.status == "APPLIED"
                ),
                None,
            )
            if predecessor is None:
                break
            source_job_id = predecessor.job_id

        if any(
            value is None
            for value in (
                source_action,
                source_assessment_id,
                source_assessment_version,
                logical_action_id,
            )
        ):
            raise WorkflowError(
                "QUESTION_ACTION_RETRY_SOURCE_MISSING",
                "The localized retry has no reconstructible durable source.",
                status_code=409,
            )
        assert source_action is not None
        assert source_assessment_id is not None
        assert source_assessment_version is not None
        assert logical_action_id is not None
        if source_action.action not in {
            m.QuestionReviewActionType.EDIT,
            m.QuestionReviewActionType.REGENERATE,
        }:
            raise WorkflowError(
                "QUESTION_ACTION_NOT_RETRYABLE",
                "Only a failed localized revalidation can be retried.",
                status_code=409,
            )
        membership = self.repository.membership_for_user(
            source_action.actor_id
        )
        if membership is None or membership[1].workspace_id != job.tenant_id:
            raise WorkflowError(
                "QUESTION_ACTION_ACTOR_REVOKED",
                "The original actor no longer belongs to this workspace.",
                status_code=409,
            )
        user, role = membership
        if role.role not in {"OWNER", "TEACHER", "ASSISTANT"}:
            raise WorkflowError(
                "QUESTION_ACTION_ACTOR_REVOKED",
                "The original actor no longer has review permission.",
                status_code=409,
            )
        current = self.repository.assessment_by_id(
            source_assessment_id, job.tenant_id
        )
        if current.version != source_assessment_version or (
            source_assessment_etag is not None
            and current.etag != source_assessment_etag
        ):
            raise WorkflowError(
                "QUESTION_ACTION_VERSION_CHANGED",
                "The assessment changed after the failed localized action.",
                status_code=409,
            )
        actor = Actor(
            user_id=user.id,
            email=user.email,
            workspace_id=job.tenant_id,
            role=role.role,
            can_approve_assessments=role.can_approve_assessments,
            csrf_token="worker-question-action-retry",
        )
        await self.review_question(
            assessment_id=source_assessment_id,
            question_id=source_action.question_id,
            action_type=source_action.action,
            actor=actor,
            if_match=current.etag,
            reason_code=source_action.reason_code,
            note=source_action.note,
            replacement=source_action.replacement,
            _execution_job=job,
            _logical_action_id=logical_action_id,
        )

    @staticmethod
    def _canonical_stage_name(value: str) -> str:
        normalized = re.sub(r"[^A-Z0-9_]", "_", value.upper()).strip("_")
        if not normalized or not normalized[0].isalpha():
            normalized = f"STAGE_{normalized}"
        return normalized[:128]

    def _stage_run_contract(self, row: StageRunRow, job: JobRow) -> m.StageRun:
        """Project a persistence row into the capability-free Stage 2 contract."""

        status = m.StageRunStatus(row.status)
        diagnostics = [m.Diagnostic.model_validate(item) for item in row.diagnostics]
        failure_class = (
            m.FailureClass(row.failure_class) if row.failure_class is not None else None
        )
        if status == m.StageRunStatus.FAILED:
            failure_class = failure_class or m.FailureClass.PERMANENT
            diagnostics = diagnostics or [
                diagnostic(
                    "STAGE_FAILURE_CLASS_MISSING",
                    "A legacy failed stage was conservatively classified as permanent.",
                )
            ]
        elif status == m.StageRunStatus.CANCELLED:
            failure_class = m.FailureClass.CANCELLATION
            diagnostics = diagnostics or [
                diagnostic("JOB_CANCELLED", "The stage stopped at a cancellation boundary.")
            ]
        started_at = _as_utc(row.started_at)
        finished_at = _as_utc(row.finished_at) if row.finished_at else None
        if status not in {m.StageRunStatus.QUEUED, m.StageRunStatus.RUNNING}:
            finished_at = finished_at or started_at
        if finished_at is not None and finished_at < started_at:
            # Rows written before Stage 2 explicitly set both timestamps can
            # differ by a few microseconds because the INSERT default ran
            # after ``finished_at`` was captured.  Preserve the row, surface a
            # content-free diagnostic, and project a valid durable contract.
            finished_at = started_at
            diagnostics = [
                *diagnostics[:99],
                diagnostic(
                    "STAGE_TIMESTAMP_NORMALIZED",
                    "A legacy stage timestamp was normalized to its execution start.",
                ),
            ]
        output_ref = (
            f"database/stage_outputs/{row.id}"
            if status == m.StageRunStatus.SUCCEEDED
            else None
        )
        output_hash = (
            row.output_hash or canonical_hash(row.output)
            if status == m.StageRunStatus.SUCCEEDED
            else None
        )
        return m.StageRun(
            stage_run_id=row.id,
            tenant_id=row.tenant_id,
            job_id=row.job_id,
            aggregate_id=job.aggregate_id,
            stage=self._canonical_stage_name(row.stage),
            stage_key=row.stage_key,
            input_hash=row.input_hash,
            policy_hash=row.policy_hash,
            component_version=row.component_version or "legacy-unknown",
            status=status,
            attempt=max(1, row.attempt),
            retryable=(
                status == m.StageRunStatus.FAILED
                and (
                    failure_class == m.FailureClass.TRANSIENT
                    or (
                        failure_class == m.FailureClass.PROVIDER
                        and any(item.retryable for item in diagnostics)
                    )
                )
            ),
            failure_class=failure_class,
            output_ref=output_ref,
            output_hash=output_hash,
            diagnostics=diagnostics,
            created_at=started_at,
            started_at=(
                None if status == m.StageRunStatus.QUEUED else started_at
            ),
            cancel_requested_at=(
                _as_utc(job.cancel_requested_at or started_at)
                if status == m.StageRunStatus.CANCELLED
                else None
            ),
            finished_at=finished_at,
        )

    def job_control_view(self, job_id: str, actor: Actor) -> dict[str, Any]:
        self.repository.reconcile_stale_jobs(
            lease_seconds=self.settings.job_lease_seconds
        )
        job = self.repository.job_control(job_id, actor.workspace_id)
        runs = [
            self._stage_run_contract(row, job)
            for row in self.repository.stage_runs_for_job(job.id, actor.workspace_id)
        ]
        records = [
            m.JobControlRecord.model_validate(row.data)
            for row in {
                item.id: item
                for item in [
                    *self.repository.job_control_records(
                        tenant_id=actor.workspace_id, job_id=job.id
                    ),
                    *self.repository.job_control_records(
                        tenant_id=actor.workspace_id, resulting_job_id=job.id
                    ),
                ]
            }.values()
        ]
        continued = any(
            record.job_id == job.id
            and record.status == m.JobControlStatus.APPLIED
            and record.action
            in {m.JobControlActionType.RETRY, m.JobControlActionType.RESUME}
            for record in records
        )
        provider_retryable = any(
            item.get("retryable") is True for item in job.diagnostics or []
        )
        allowed: list[m.JobControlActionType] = []
        if job.control_state == "ACTIVE" and not continued:
            if job.status in {"QUEUED", "RUNNING"}:
                allowed.append(m.JobControlActionType.CANCEL)
            if (
                job.status == "FAILED"
                and (
                    job.failure_class == "TRANSIENT"
                    or (
                        job.failure_class == "PROVIDER" and provider_retryable
                    )
                )
                and job.attempt < job.max_attempts
            ):
                allowed.append(m.JobControlActionType.RETRY)
            if (
                job.status == "NEEDS_REVIEW"
                or (
                    job.status == "FAILED"
                    and job.failure_class in {"PRECONDITION", "VALIDATION"}
                )
            ) and job.attempt < job.max_attempts:
                allowed.append(m.JobControlActionType.RESUME)
        return {
            "job": self.repository.job_status(job.id, actor.workspace_id),
            "stage_runs": runs,
            "control_records": records,
            "allowed_actions": allowed,
            "resumable_stage": (
                self._canonical_stage_name(job.resume_from_stage or job.stage)
                if m.JobControlActionType.RESUME in allowed
                else None
            ),
            "control_state": job.control_state,
            "failure_class": job.failure_class,
        }

    async def control_job(
        self,
        *,
        job_id: str,
        action: m.JobControlActionType,
        reason_code: str,
        actor: Actor,
        target_stage: str | None = None,
    ) -> dict[str, Any]:
        source = self.repository.job_control(job_id, actor.workspace_id)
        if source.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
            self._require_teacher(actor)
        else:
            self._require_reviewer(actor)
        allowed_actions = set(
            self.job_control_view(source.id, actor)["allowed_actions"]
        )
        if action not in allowed_actions:
            raise WorkflowError(
                "JOB_CONTROL_NOT_ALLOWED",
                "The requested action is not allowed for the durable job state.",
                status_code=409,
            )
        if action == m.JobControlActionType.CANCEL and target_stage is not None:
            raise WorkflowError(
                "JOB_CONTROL_INVALID",
                "Cancellation cannot specify a resume target.",
            )
        now = utc_now()
        control_id = stable_id(
            "control", actor.workspace_id, job_id, action.value, actor.user_id, now
        )
        try:
            if action == m.JobControlActionType.CANCEL:
                result = self.repository.request_job_cancel(
                    job_id=source.id,
                    tenant_id=actor.workspace_id,
                    actor_id=actor.user_id,
                    requested_at=now,
                    control_id=control_id,
                    reason_code=reason_code,
                )
            else:
                resume_from = self._canonical_stage_name(
                    target_stage or source.resume_from_stage or source.stage
                )
                allowed_stages = {
                    "ACTIVITY": {
                        "ACTIVITY_PARSE",
                        "ACTIVITY_SPEC",
                        "RUBRIC_NORMALIZE",
                        "AMBIGUITY_TRIAGE",
                        "BLUEPRINT_BUILD",
                        "BLUEPRINT_REVIEW",
                    },
                    "SUBMISSION": {
                        "SUBMISSION_PARSE",
                        "EVIDENCE_MAP",
                        "ASSESSMENT_PLAN",
                        "QUESTION_GENERATE",
                        "QUESTION_REVIEW",
                        "GUIDE_BUILD",
                        "ASSEMBLE",
                    },
                    "QUESTION_ACTION": {"QUESTION_GENERATE"},
                    "BLUEPRINT_REVIEW": {"BLUEPRINT_REVIEW"},
                }
                if resume_from not in allowed_stages.get(source.kind, set()):
                    raise WorkflowError(
                        "STAGE_RESUME_TARGET_INVALID",
                        "The selected resume target is not part of this job pipeline.",
                        status_code=409,
                    )
                resulting_job_id = stable_id(
                    "job", actor.workspace_id, control_id, action.value
                )
                if action == m.JobControlActionType.RETRY:
                    if source.failure_class not in {"TRANSIENT", "PROVIDER"}:
                        raise WorkflowError(
                            "JOB_FAILURE_NOT_RETRYABLE",
                            "Only transient or provider failures may be retried.",
                            status_code=409,
                        )
                    result = self.repository.schedule_job_retry(
                        job_id=source.id,
                        tenant_id=actor.workspace_id,
                        resulting_job_id=resulting_job_id,
                        control_id=control_id,
                        actor_id=actor.user_id,
                        reason_code=reason_code,
                        failure_class=source.failure_class,
                        next_attempt_at=now,
                        resume_from_stage=resume_from,
                        max_attempts=self.settings.job_max_attempts,
                    )
                elif action == m.JobControlActionType.RESUME:
                    result = self.repository.schedule_job_resume(
                        job_id=source.id,
                        tenant_id=actor.workspace_id,
                        resulting_job_id=resulting_job_id,
                        control_id=control_id,
                        actor_id=actor.user_id,
                        reason_code=reason_code,
                        resume_from_stage=resume_from,
                        next_attempt_at=now,
                    )
                else:  # pragma: no cover - enum boundary is exhaustive
                    raise WorkflowError(
                        "JOB_CONTROL_INVALID", "Unsupported job control action."
                    )
                if self.legacy.job_runner is None:
                    raise RuntimeError("JobRunner is not configured")
                try:
                    await self.legacy.job_runner.dispatch(result.id)
                except Exception:
                    self.repository.fail_queued_dispatch(
                        job_id=result.id,
                        tenant_id=actor.workspace_id,
                        failure=diagnostic(
                            "JOB_DISPATCH_FAILED",
                            "The durable continuation could not be dispatched.",
                            retryable=True,
                        ),
                    )
        except Conflict as exc:
            code = str(exc) if str(exc).isupper() else "JOB_CONTROL_CONFLICT"
            raise WorkflowError(
                code,
                "The requested durable job control is not currently allowed.",
                status_code=409,
            ) from exc
        except ValidationError as exc:
            raise WorkflowError(
                "JOB_CONTROL_INVALID",
                "The requested durable job control is invalid.",
            ) from exc
        return self.job_control_view(result.id, actor)

    def question_actions(
        self,
        *,
        assessment_id: str,
        question_id: str,
        actor: Actor,
    ) -> list[m.QuestionReviewActionRecord]:
        assessment = m.Assessment.model_validate(
            self.repository.assessment_by_id(
                assessment_id, actor.workspace_id
            ).data
        )
        if question_id not in {item.question_id for item in assessment.questions}:
            raise NotFound("question not found")
        return [
            m.QuestionReviewActionRecord.model_validate(row.data)
            for row in self.repository.question_review_actions(
                tenant_id=actor.workspace_id,
                assessment_id=assessment_id,
                question_id=question_id,
            )
        ]

    @staticmethod
    def _coverage_csv(report: m.CoverageReport) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "submission_id",
                "assessment_id",
                "assessment_version",
                "dimension_id",
                "criterion_ids",
                "variant_id",
                "opportunity_id",
                "evidence_ids",
                "cognitive_operation",
                "planning_role",
                "outcome",
                "reused_variant",
                "failure_code",
                "exclusion_reason_code",
            ]
        )
        for item in report.traces:
            writer.writerow(
                [
                    item.submission_id,
                    item.assessment_id or "",
                    item.assessment_version or "",
                    item.dimension_id,
                    ";".join(item.criterion_ids),
                    item.variant_id,
                    item.opportunity_id,
                    ";".join(item.evidence_ids),
                    item.cognitive_operation.value,
                    item.planning_role.value,
                    item.outcome.value,
                    "true" if item.reused_variant else "false",
                    item.failure_code or "",
                    item.exclusion_reason_code or "",
                ]
            )
        return stream.getvalue().encode("utf-8")

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")

    def create_export(
        self,
        *,
        assessment_id: str,
        requested_kinds: list[m.ExportKind],
        actor: Actor,
    ) -> m.ExportRecord:
        """Render approved snapshots without invoking a model or persisting URLs."""

        self._require_teacher(actor)
        if not requested_kinds or len(requested_kinds) != len(set(requested_kinds)):
            raise WorkflowError(
                "EXPORT_KIND_INVALID", "Export kinds must be a non-empty unique set."
            )
        assessment_row = self.repository.assessment_by_id(
            assessment_id, actor.workspace_id
        )
        assessment = m.Assessment.model_validate(assessment_row.data)
        if (
            assessment.status != m.WorkflowStatus.APPROVED
            or assessment.approved_by is None
            or assessment.approved_at is None
            or not self.repository.has_audit_event(
                tenant_id=actor.workspace_id,
                event_type="assessment.approved",
                aggregate_id=assessment_id,
                payload_contains={"assessment_version": assessment_row.version},
            )
        ):
            raise WorkflowError(
                "HUMAN_APPROVAL_REQUIRED",
                "Exports require the exact approved assessment version.",
                status_code=409,
            )
        guide = m.EvaluationGuide.model_validate(
            self.repository.guide_for_assessment(
                assessment_id, actor.workspace_id
            ).data
        )
        if guide.status != m.WorkflowStatus.READY:
            raise WorkflowError(
                "GUIDE_NOT_READY",
                "Exports require the complete READY evaluation guide.",
                status_code=409,
            )
        coverage = self.coverage_for_submission(assessment.submission_id, actor)
        # Snapshot exports are reproducible: volatile observation time is
        # anchored to the immutable approval instant.
        coverage = coverage.model_copy(update={"generated_at": assessment.approved_at})
        assessment_hash = canonical_hash(assessment)
        guide_hash = canonical_hash(guide)
        coverage_hash = coverage.source_snapshot_hash
        export_id = stable_id(
            "export",
            actor.workspace_id,
            assessment_id,
            assessment_row.version,
            assessment_hash,
            guide_hash,
            coverage_hash,
            sorted(item.value for item in requested_kinds),
            RENDERER_VERSION,
        )
        try:
            existing = cast(
                ExportRow,
                self.repository.scoped(ExportRow, export_id, actor.workspace_id),
            )
            if existing.data is None:
                raise WorkflowError(
                    "EXPORT_LEGACY_RECORD_UNSUPPORTED",
                    "The historical export predates the versioned Stage 2 snapshot.",
                    status_code=409,
                )
            return m.ExportRecord.model_validate(existing.data)
        except NotFound:
            pass

        with self.repository.session() as session:
            assessment_job_ids = list(
                session.scalars(
                    select(JobRow.id).where(
                        JobRow.tenant_id == actor.workspace_id,
                        JobRow.aggregate_id == assessment.submission_id,
                    )
                )
            )
        calls_before = sum(
            len(
                self.repository.model_calls(
                    tenant_id=actor.workspace_id, job_id=job_id
                )
            )
            for job_id in assessment_job_ids
        )
        requested_at = utc_now()
        with TemporaryDirectory(prefix="cva-stage2-export-") as temp_dir:
            rendered = render_views(assessment, guide, Path(temp_dir))
            coverage_payload = coverage.model_dump(mode="json")
            canonical_payload = {
                "schema_version": "1.2.0",
                "assessment_version": assessment_row.version,
                "assessment": assessment.model_dump(mode="json"),
                "evaluation_guide": guide.model_dump(mode="json"),
                "coverage": coverage_payload,
            }
            source_bytes: dict[m.ExportKind, tuple[bytes, str, str]] = {
                m.ExportKind.ASSESSMENT_PDF: (
                    rendered.assessment_pdf.read_bytes(),
                    "application/pdf",
                    "assessment.pdf",
                ),
                m.ExportKind.ASSESSMENT_HTML: (
                    rendered.assessment_html.read_bytes(),
                    "text/html",
                    "assessment.html",
                ),
                m.ExportKind.GUIDE_PDF: (
                    rendered.guide_pdf.read_bytes(),
                    "application/pdf",
                    "guide.pdf",
                ),
                m.ExportKind.GUIDE_HTML: (
                    rendered.guide_html.read_bytes(),
                    "text/html",
                    "guide.html",
                ),
                m.ExportKind.COVERAGE_CSV: (
                    self._coverage_csv(coverage),
                    "text/csv",
                    "coverage.csv",
                ),
                m.ExportKind.COVERAGE_JSON: (
                    self._json_bytes(coverage_payload),
                    "application/json",
                    "coverage.json",
                ),
                m.ExportKind.CANONICAL_JSON: (
                    self._json_bytes(canonical_payload),
                    "application/json",
                    "canonical.json",
                ),
            }
            completed_at = utc_now()
            artifacts: list[m.ExportArtifact] = []
            for kind in requested_kinds:
                data, media_type, filename = source_bytes[kind]
                object_key = (
                    f"exports/{actor.workspace_id}/{assessment_id}/"
                    f"{export_id}/{filename}"
                )
                self.object_store.put_immutable(object_key, data, media_type)
                artifacts.append(
                    m.ExportArtifact(
                        export_artifact_id=stable_id(
                            "exportartifact", export_id, kind.value
                        ),
                        kind=kind,
                        media_type=media_type,
                        object_key=object_key,
                        sha256=sha256_bytes(data),
                        byte_size=len(data),
                        created_at=completed_at,
                    )
                )

        calls_after = sum(
            len(
                self.repository.model_calls(
                    tenant_id=actor.workspace_id, job_id=job_id
                )
            )
            for job_id in assessment_job_ids
        )
        if calls_after != calls_before:
            raise WorkflowError(
                "EXPORT_MODEL_CALL_DETECTED",
                "Snapshot export attempted to change the model-call ledger.",
                status_code=500,
            )
        record = m.ExportRecord(
            export_id=export_id,
            tenant_id=actor.workspace_id,
            activity_id=assessment.activity_id,
            assessment_id=assessment_id,
            assessment_version=assessment_row.version,
            requested_by=actor.user_id,
            requested_kinds=requested_kinds,
            status=m.ExportStatus.READY,
            assessment_snapshot_hash=assessment_hash,
            guide_snapshot_hash=guide_hash,
            coverage_snapshot_hash=coverage_hash,
            renderer_version=RENDERER_VERSION,
            artifacts=artifacts,
            model_call_delta=0,
            diagnostics=[],
            requested_at=requested_at,
            completed_at=completed_at,
        )
        try:
            self.repository.save_export_record(record)
        except IntegrityError:
            existing = cast(
                ExportRow,
                self.repository.scoped(ExportRow, export_id, actor.workspace_id),
            )
            if existing.data is None:
                raise
            return m.ExportRecord.model_validate(existing.data)
        return record

    def export_downloads(
        self, record: m.ExportRecord, actor: Actor
    ) -> list[dict[str, Any]]:
        if record.tenant_id != actor.workspace_id:
            raise NotFound("export not found")
        downloads: list[dict[str, Any]] = []
        for artifact in record.artifacts:
            signed = self.object_store.sign_get(artifact.object_key)
            downloads.append(
                {
                    "export_artifact_id": artifact.export_artifact_id,
                    "kind": artifact.kind,
                    "media_type": artifact.media_type,
                    "sha256": artifact.sha256,
                    "byte_size": artifact.byte_size,
                    "download_url": signed.url,
                    "expires_at": signed.expires_at,
                }
            )
        return downloads

    def exports_for_assessment(
        self, assessment_id: str, actor: Actor
    ) -> list[m.ExportRecord]:
        self.repository.assessment_by_id(assessment_id, actor.workspace_id)
        values: list[m.ExportRecord] = []
        for row in self.repository.list_exports(assessment_id, actor.workspace_id):
            if row.data is None:
                continue
            values.append(m.ExportRecord.model_validate(row.data))
        return values

    def _bulk_target_exclusion(
        self,
        target: m.AssessmentVersionRef,
        code: str,
        message: str,
    ) -> m.BulkApprovalExclusion:
        return m.BulkApprovalExclusion(
            target=target,
            reason_code=code,
            message=message,
        )

    def _ensure_bulk_completion_audit(
        self,
        *,
        activity_id: str,
        actor: Actor,
        record: m.BulkApprovalRecord,
    ) -> None:
        """Bind a durable bulk record to its tenant-scoped activity history."""

        payload = {
            "request_id": record.request_id,
            "approval_id": record.approval_id,
            "requested_count": len(record.requested_targets),
            "approved_count": len(record.approved_targets),
            "excluded_count": len(record.excluded_targets),
        }
        if self.repository.has_audit_event(
            tenant_id=actor.workspace_id,
            event_type="bulk.approval.completed",
            aggregate_id=activity_id,
            payload_contains={"request_id": record.request_id},
        ):
            return
        self.repository.audit(
            tenant_id=actor.workspace_id,
            event_type="bulk.approval.completed",
            aggregate_id=activity_id,
            actor_id=actor.user_id,
            payload=payload,
        )

    def bulk_approve(
        self,
        *,
        activity_id: str,
        targets: list[m.AssessmentVersionRef],
        explicit_confirmation: str,
        actor: Actor,
    ) -> m.BulkApprovalRecord:
        """Approve only the exact evidence-first eligible partition."""

        self._require_reviewer(actor)
        if not actor.can_approve_assessments:
            raise WorkflowError(
                "ROLE_FORBIDDEN", "Actor cannot approve assessments.", status_code=403
            )
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        request_id = stable_id(
            "bulkrequest",
            actor.workspace_id,
            activity_id,
            actor.user_id,
            sorted(
                (item.assessment_id, item.assessment_version) for item in targets
            ),
            explicit_confirmation,
        )
        existing_records = self.repository.bulk_approval_records(
            tenant_id=actor.workspace_id, request_id=request_id
        )
        if existing_records:
            existing_record = m.BulkApprovalRecord.model_validate(
                existing_records[-1].data
            )
            self._ensure_bulk_completion_audit(
                activity_id=activity_id, actor=actor, record=existing_record
            )
            return existing_record
        request = m.BulkApprovalRequest(
            request_id=request_id,
            tenant_id=actor.workspace_id,
            actor_id=actor.user_id,
            targets=targets,
            explicit_confirmation=explicit_confirmation,
            requested_at=utc_now(),
        )
        try:
            self.repository.add_bulk_approval_request(request)
        except Conflict as exc:
            if str(exc) != "BULK_APPROVAL_REQUEST_ALREADY_EXISTS":
                raise

        approved: list[m.AssessmentVersionRef] = []
        excluded: list[m.BulkApprovalExclusion] = []
        accepted_actions = {
            m.QuestionReviewActionType.ACCEPT,
            m.QuestionReviewActionType.EDIT,
            m.QuestionReviewActionType.REGENERATE,
        }
        for target in targets:
            if self.repository.has_audit_event(
                tenant_id=actor.workspace_id,
                event_type="assessment.bulk_approved",
                aggregate_id=target.assessment_id,
                payload_contains={
                    "request_id": request_id,
                    "requested_version": target.assessment_version,
                },
            ):
                approved.append(target)
                continue
            try:
                row = self.repository.assessment_by_id(
                    target.assessment_id, actor.workspace_id
                )
                assessment = m.Assessment.model_validate(row.data)
                if assessment.activity_id != activity_id:
                    raise WorkflowError(
                        "BULK_TARGET_OUT_OF_SCOPE",
                        "Target is outside the selected activity.",
                        status_code=409,
                    )
                if (
                    row.version == target.assessment_version + 1
                    and assessment.status == m.WorkflowStatus.APPROVED
                    and assessment.approved_by == actor.user_id
                    and self.repository.has_audit_event(
                        tenant_id=actor.workspace_id,
                        event_type="assessment.approved",
                        aggregate_id=target.assessment_id,
                        payload_contains={"assessment_version": row.version},
                    )
                ):
                    # Recover a request interrupted after the exact individual
                    # approval committed but before its bulk outcome record.
                    self.repository.audit(
                        tenant_id=actor.workspace_id,
                        event_type="assessment.bulk_approved",
                        aggregate_id=target.assessment_id,
                        actor_id=actor.user_id,
                        payload={
                            "request_id": request_id,
                            "requested_version": target.assessment_version,
                        },
                    )
                    approved.append(target)
                    continue
                if row.version != target.assessment_version:
                    raise WorkflowError(
                        "BULK_TARGET_VERSION_STALE",
                        "Target is not the exact latest assessment version.",
                        status_code=409,
                    )
                if assessment.status != m.WorkflowStatus.NEEDS_REVIEW:
                    raise WorkflowError(
                        "BULK_TARGET_NOT_REVIEWABLE",
                        "Target is not awaiting review.",
                        status_code=409,
                    )
                guide = m.EvaluationGuide.model_validate(
                    self.repository.guide_for_assessment(
                        target.assessment_id, actor.workspace_id
                    ).data
                )
                if guide.status != m.WorkflowStatus.READY:
                    raise WorkflowError(
                        "GUIDE_NOT_READY", "Target guide is not READY.", status_code=409
                    )
                latest_by_question: dict[str, m.QuestionReviewActionRecord] = {}
                for action_row in self.repository.question_review_actions(
                    tenant_id=actor.workspace_id,
                    assessment_id=target.assessment_id,
                ):
                    action_record = m.QuestionReviewActionRecord.model_validate(
                        action_row.data
                    )
                    latest_by_question[action_record.action.question_id] = action_record
                if any(
                    question.question_id not in latest_by_question
                    or latest_by_question[question.question_id].status
                    != m.QuestionReviewRecordStatus.APPLIED
                    or latest_by_question[question.question_id].action.action
                    not in accepted_actions
                    for question in assessment.questions
                ):
                    raise WorkflowError(
                        "QUESTION_REVIEW_REQUIRED",
                        "Every current question requires an applied accepting action.",
                        status_code=409,
                    )
                self.legacy.evidence_view(assessment.submission_id, actor)
                self.legacy._assert_evidence_receipts_complete(row, assessment, actor)
                self.legacy.approve_assessment(
                    assessment_id=target.assessment_id,
                    if_match=row.etag,
                    actor=actor,
                )
                self.repository.audit(
                    tenant_id=actor.workspace_id,
                    event_type="assessment.bulk_approved",
                    aggregate_id=target.assessment_id,
                    actor_id=actor.user_id,
                    payload={
                        "request_id": request_id,
                        "requested_version": target.assessment_version,
                    },
                )
                approved.append(target)
            except (NotFound, WorkflowError, ValidationError) as exc:
                code = getattr(exc, "code", "BULK_TARGET_NOT_FOUND")
                if not isinstance(code, str) or not code.isupper():
                    code = "BULK_TARGET_INELIGIBLE"
                exclusion = self._bulk_target_exclusion(
                    target,
                    code,
                    "The target requires individual review before approval.",
                )
                excluded.append(exclusion)
                self.repository.audit(
                    tenant_id=actor.workspace_id,
                    event_type="assessment.bulk_excluded",
                    aggregate_id=target.assessment_id,
                    actor_id=actor.user_id,
                    payload={
                        "request_id": request_id,
                        "requested_version": target.assessment_version,
                        "reason_code": code,
                    },
                )

        record = m.BulkApprovalRecord(
            approval_id=stable_id("bulkapproval", request_id),
            request_id=request_id,
            tenant_id=actor.workspace_id,
            actor_id=actor.user_id,
            scope="SELECTED_ELIGIBLE_ASSESSMENTS",
            approved_at=utc_now(),
            requested_targets=targets,
            approved_targets=approved,
            excluded_targets=excluded,
        )
        try:
            self.repository.add_bulk_approval_record(record)
        except Conflict as exc:
            if str(exc) != "BULK_APPROVAL_RECORD_ALREADY_EXISTS":
                raise
            existing = self.repository.bulk_approval_records(
                tenant_id=actor.workspace_id, request_id=request_id
            )
            if not existing:
                raise
            existing_record = m.BulkApprovalRecord.model_validate(existing[-1].data)
            self._ensure_bulk_completion_audit(
                activity_id=activity_id, actor=actor, record=existing_record
            )
            return existing_record
        self._ensure_bulk_completion_audit(
            activity_id=activity_id, actor=actor, record=record
        )
        return record

    def bulk_approvals_for_activity(
        self, activity_id: str, actor: Actor
    ) -> list[m.BulkApprovalRecord]:
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        request_ids = {
            str(event.payload["request_id"])
            for event in self.repository.audit_events(
                tenant_id=actor.workspace_id,
                event_type="bulk.approval.completed",
                aggregate_id=activity_id,
            )
            if isinstance(event.payload.get("request_id"), str)
        }
        values: list[m.BulkApprovalRecord] = []
        for row in self.repository.bulk_approval_records(
            tenant_id=actor.workspace_id
        ):
            record = m.BulkApprovalRecord.model_validate(row.data)
            if record.request_id in request_ids:
                values.append(record)
        return values
