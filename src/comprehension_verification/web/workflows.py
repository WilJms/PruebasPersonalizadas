"""Stage 1 application services and the two explicit vertical pipelines."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError

from ..canonical import canonical_hash, sha256_bytes, stable_id
from ..contracts import models as m
from ..diagnostics import diagnostic
from ..exports import RENDERER_VERSION, render_views
from ..model_gateway import (
    CallBudget,
    GatewayConfig,
    GatewayContextError,
    GatewayMode,
    GatewayProviderError,
    GatewaySafetyBlock,
    GatewayTimeout,
    ModelGateway,
    TransientProviderError,
)
from ..model_gateway.mock_factory import build_trusted_context
from ..model_gateway.openai_pricing import estimate_cost_usd
from ..model_gateway.openai_routes import (
    LUNA_MODEL_ID,
    OPENAI_MODEL_BY_PROMPT,
)
from ..model_gateway.registry import PROMPT_VERSION, prompt_spec
from ..parsers import (
    DOCX_MEDIA_TYPE,
    PARSER_VERSION,
    ParseRejected,
    ParsedArtifact,
    SafeParserService,
    parse_in_subprocess,
)
from ..planning import PLANNER_VERSION, build_assessment_plan
from ..validation import (
    ContextValidationError,
    validate_assessment_plan,
    validate_evaluation_guide,
    validate_evidence_map,
    validate_generation_result,
    validate_review_result,
)
from .auth import Actor
from . import dto
from .jobs import JobRunner
from .object_store import ObjectSizeExceeded, ObjectStore
from .repository import (
    ActivityRow,
    ActivitySpecRow,
    AmbiguityRow,
    ArtifactRow,
    AssessmentPlanRow,
    AssessmentRow,
    BlueprintRow,
    Conflict,
    EvidenceMapRow,
    EvidenceRow,
    ExportRow,
    GeneratedQuestionRow,
    GuideRow,
    JobRow,
    NotFound,
    PolicyDecisionRow,
    QuestionReviewRow,
    Repository,
    RubricSpecRow,
    StageRunRow,
    SubmissionRow,
    utc_now,
)
from .settings import Settings, WorkerSettings


ALLOWED_MEDIA_TYPES = frozenset(
    {"text/plain", "text/markdown", "application/pdf", DOCX_MEDIA_TYPE}
)
ACTIVITY_UPLOAD_OPEN_STATUSES = frozenset({"DRAFT"})
ACTIVITY_PIPELINE_VERSION = "stage1-activity-pipeline/1.0.0"
SUBMISSION_PIPELINE_VERSION = "stage1-submission-pipeline/1.0.0"
ASSEMBLER_VERSION = "stage1-assembler/1.0.0"

_ACTIVITY_RESUME_ORDER = {
    "ACTIVITY_PARSE": 0,
    "ACTIVITY_SPEC": 1,
    "RUBRIC_NORMALIZE": 2,
    "AMBIGUITY_TRIAGE": 3,
    "BLUEPRINT_BUILD": 4,
    "BLUEPRINT_REVIEW": 5,
}
_SUBMISSION_RESUME_ORDER = {
    "SUBMISSION_PARSE": 0,
    "EVIDENCE_MAP": 1,
    "ASSESSMENT_PLAN": 2,
    "QUESTION_GENERATE": 3,
    "QUESTION_REVIEW": 4,
    "GUIDE_BUILD": 5,
    "ASSEMBLE": 6,
}
_BLUEPRINT_REVIEW_RESUME_ORDER = {"BLUEPRINT_REVIEW": 0}
_PROMPT_APPLICATION_STAGE = {
    "P01_ACTIVITY_SPEC_V1": "ACTIVITY_SPEC",
    "P02_RUBRIC_NORMALIZE_V1": "RUBRIC_NORMALIZE",
    "P03_AMBIGUITY_TRIAGE_V1": "AMBIGUITY_TRIAGE",
    "P04_BLUEPRINT_BUILD_V1": "BLUEPRINT_BUILD",
    "P05_BLUEPRINT_REVIEW_V1": "BLUEPRINT_REVIEW",
    "P06_EVIDENCE_MAP_V1": "EVIDENCE_MAP",
    "P07_QUESTION_BUILD_V1": "QUESTION_GENERATE",
    "P08_QUESTION_REVIEW_V1": "QUESTION_REVIEW",
    "P09_GUIDE_BUILD_V1": "GUIDE_BUILD",
}

T = TypeVar("T", bound=BaseModel)


class WorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _CooperativeJobCancellation(RuntimeError):
    """Internal control-flow sentinel after durable cancellation acknowledgement."""


_SECURITY_FAILURE_CODES = frozenset(
    {
        "CROSS_SUBMISSION_EVIDENCE",
        "INGEST_ENCRYPTED_FILE",
        "IR_PROVENANCE_GAP",
        "MODEL_CONTEXT_NOT_ALLOWLISTED",
        "MODEL_SAFETY_BLOCK",
        "REJECTED_SECURITY",
    }
)

_PRECONDITION_FAILURE_CODES = frozenset(
    {
        "BLUEPRINT_NOT_APPROVED",
        "POLICY_DECISION_INVALID",
        "STAGE_RESUME_REUSE_MISSING",
        "SUBMISSION_ARTIFACT_REQUIRED",
        "SUBMISSION_FINALIZATION_STATE_CHANGED",
        "QUESTION_ACTION_ACTOR_REVOKED",
        "QUESTION_ACTION_RETRY_SOURCE_MISSING",
        "QUESTION_ACTION_VERSION_CHANGED",
        "BLUEPRINT_REVIEW_DESCRIPTOR_MISSING",
        "BLUEPRINT_REVIEW_DESCRIPTOR_INVALID",
        "BLUEPRINT_REVIEW_DESCRIPTOR_HASH_MISMATCH",
        "BLUEPRINT_REVIEW_DESCRIPTOR_VERSION_MISMATCH",
        "BLUEPRINT_REVIEW_SOURCE_CHANGED",
    }
)


def build_blueprint_policy(config: m.ActivityConfig) -> m.BlueprintPolicy:
    selected_ids: list[str] = []
    if config.structured_justification_mode == m.StructuredJustificationMode.SELECTED:
        # A localized regeneration must be able to replace a selected
        # justification question with a distinct reserve that carries the
        # same blueprint-bound requirement.  Two templates are the minimum
        # catalog surface that lets the deterministic planner keep one as a
        # primary and one as a compatible reserve.
        selected_ids = [
            stable_id("opt", config.activity_id, "selected_justification", index)
            for index in range(2)
        ]
    planning_policy = m.AssessmentPlanningPolicy(
        policy_id=stable_id("policy", config.activity_id, "planning")
    )
    return m.BlueprintPolicy(
        policy_id=stable_id("policy", config.activity_id, "blueprint"),
        activity_id=config.activity_id,
        question_count=config.question_count,
        target_total_minutes=config.target_total_minutes,
        allowed_response_formats=config.allowed_response_formats,
        priority_criterion_ids=config.priority_criterion_ids,
        required_criterion_ids=[],
        structured_justification_policy=m.StructuredJustificationPolicy(
            mode=config.structured_justification_mode,
            selected_opportunity_template_ids=selected_ids,
        ),
        planning_policy=planning_policy,
        max_local_regenerations=1,
        human_review_required=True,
    )


def _etag(value: Any) -> str:
    return f'"{canonical_hash(value)}"'


def _blueprint_structure(blueprint: m.AssessmentBlueprint) -> dict[str, Any]:
    """Return the source-bound structure that an E1 text edit cannot widen."""

    return {
        "blueprint_id": blueprint.blueprint_id,
        "activity_id": blueprint.activity_id,
        "context_mode": blueprint.context_mode,
        "decision_ids": blueprint.decision_ids,
        "assessment_constraints": blueprint.assessment_constraints,
        "dimensions": [
            {
                "dimension_id": dimension.dimension_id,
                "criterion_ids": dimension.criterion_ids,
                "learning_outcome_ids": dimension.learning_outcome_ids,
                "grading_weight": dimension.grading_weight,
                "verification_priority": dimension.verification_priority,
                "factors": dimension.factors,
                "variants": [
                    {
                        "variant_id": variant.variant_id,
                        "evidence_requirement": variant.evidence_requirement,
                        "verification_potential": variant.verification_potential,
                        "supported_operations": [
                            {
                                "cognitive_operation": operation.cognitive_operation,
                                "support_strength": operation.support_strength,
                            }
                            for operation in variant.supported_operations
                        ],
                        "opportunities": [
                            {
                                "opportunity_template_id": opportunity.opportunity_template_id,
                                "cognitive_operation": opportunity.cognitive_operation,
                                "difficulty": opportunity.difficulty,
                                "target_minutes": opportunity.target_minutes,
                                "allowed_anchor_structures": opportunity.allowed_anchor_structures,
                                "allowed_response_formats": opportunity.allowed_response_formats,
                                "verification_potential": opportunity.verification_potential,
                                "minimum_quality": opportunity.minimum_quality,
                                "student_justification_required": opportunity.student_justification_required,
                            }
                            for opportunity in variant.question_opportunities
                        ],
                    }
                    for variant in dimension.evidence_variants
                ],
            }
            for dimension in blueprint.dimensions
        ],
    }


class Stage1Service:
    def __init__(
        self,
        *,
        settings: Settings | WorkerSettings,
        repository: Repository,
        object_store: ObjectStore,
        parser: SafeParserService | None = None,
        job_runner: JobRunner | None = None,
        gateway_factory: Callable[[str], ModelGateway] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store
        self.parser = parser or SafeParserService(
            require_libmagic=settings.require_libmagic
        )
        self.job_runner = job_runner
        self.gateway_factory = gateway_factory
        self._resume_floor_reached: set[str] = set()
        self._question_action_processor: (
            Callable[[JobRow], Awaitable[None]] | None
        ) = None

    def set_job_runner(self, runner: JobRunner) -> None:
        self.job_runner = runner

    def set_question_action_processor(
        self, processor: Callable[[JobRow], Awaitable[None]]
    ) -> None:
        self._question_action_processor = processor

    @staticmethod
    def _require_activity_teacher(actor: Actor) -> None:
        if actor.role not in {"OWNER", "TEACHER"}:
            raise WorkflowError(
                "ROLE_FORBIDDEN",
                "Only teachers may mutate activity inputs or launch its pipeline",
                status_code=403,
            )

    @staticmethod
    def _require_submission_reviewer(actor: Actor) -> None:
        if actor.role not in {"OWNER", "TEACHER", "ASSISTANT"}:
            raise WorkflowError(
                "ROLE_FORBIDDEN",
                "Only an authorized reviewer may operate submission inputs.",
                status_code=403,
            )

    def create_activity(self, config: m.ActivityConfig, actor: Actor) -> ActivityRow:
        self._require_activity_teacher(actor)
        if config.tenant_id != actor.workspace_id:
            raise WorkflowError("CROSS_WORKSPACE", "Activity tenant does not match session", status_code=404)
        if config.context_mode != m.ContextMode.CLOSED or config.course_source_ids:
            raise WorkflowError("P10_DISABLED", "Stage 1 supports CLOSED context only")
        if set(config.allowed_artifact_media_types) - ALLOWED_MEDIA_TYPES:
            raise WorkflowError(
                "INGEST_UNSUPPORTED_MEDIA",
                "This environment enables digital PDF, structural DOCX, TXT and Markdown",
            )
        policy = build_blueprint_policy(config)
        row = ActivityRow(
            id=config.activity_id,
            tenant_id=actor.workspace_id,
            status="DRAFT",
            config=config.model_dump(mode="json"),
            blueprint_policy=policy.model_dump(mode="json"),
            created_by=actor.user_id,
        )
        self.repository.add(row)
        self.repository.audit(
            tenant_id=actor.workspace_id,
            event_type="activity.created",
            aggregate_id=config.activity_id,
            actor_id=actor.user_id,
            payload={"schema_version": config.schema_version},
        )
        return row

    @staticmethod
    def activity_etag(row: ActivityRow) -> str:
        return _etag(row.config)

    def edit_activity(
        self,
        *,
        activity_id: str,
        config: m.ActivityConfig,
        if_match: str,
        actor: Actor,
    ) -> ActivityRow:
        self._require_activity_teacher(actor)
        current = cast(
            ActivityRow,
            self.repository.scoped(ActivityRow, activity_id, actor.workspace_id),
        )
        if self.activity_etag(current) != if_match:
            raise WorkflowError("ETAG_MISMATCH", "Activity has changed", status_code=412)
        if config.activity_id != activity_id or config.tenant_id != actor.workspace_id:
            raise WorkflowError(
                "CROSS_WORKSPACE", "Activity identity does not match the session", status_code=404
            )
        if config.context_mode != m.ContextMode.CLOSED or config.course_source_ids:
            raise WorkflowError("P10_DISABLED", "Stage 1 supports CLOSED context only")
        if set(config.allowed_artifact_media_types) - ALLOWED_MEDIA_TYPES:
            raise WorkflowError(
                "INGEST_UNSUPPORTED_MEDIA",
                "This environment enables digital PDF, structural DOCX, TXT and Markdown",
            )
        try:
            row = self.repository.update_activity_config(
                activity_id=activity_id,
                tenant_id=actor.workspace_id,
                config=config.model_dump(mode="json"),
                blueprint_policy=build_blueprint_policy(config).model_dump(mode="json"),
                expected_etag=if_match,
            )
        except Conflict as exc:
            if str(exc) == "ETAG_MISMATCH":
                raise WorkflowError(
                    "ETAG_MISMATCH", "Activity has changed", status_code=412
                ) from exc
            raise WorkflowError(
                "ACTIVITY_CONFIG_LOCKED",
                "Activity configuration is immutable after pipeline start",
                status_code=409,
            ) from exc
        self.repository.audit(
            tenant_id=actor.workspace_id,
            event_type="activity.config.updated",
            aggregate_id=activity_id,
            actor_id=actor.user_id,
            payload={"etag": self.activity_etag(row)},
        )
        return row

    def ambiguity_view(self, activity_id: str, actor: Actor) -> dict[str, Any]:
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        report_row = cast(
            AmbiguityRow,
            self.repository.scoped(AmbiguityRow, activity_id, actor.workspace_id),
        )
        decisions = self._resolved_policy_decisions(activity_id, actor.workspace_id)
        return {
            "report": report_row.data,
            "decisions": [item.model_dump(mode="json") for item in decisions],
        }

    def record_policy_decision(
        self,
        *,
        activity_id: str,
        issue_id: str,
        selected_option_id: str,
        note: str | None,
        actor: Actor,
    ) -> m.PolicyDecision:
        if actor.role not in {"OWNER", "TEACHER"}:
            raise WorkflowError(
                "ROLE_FORBIDDEN", "Only teachers may resolve ambiguity", status_code=403
            )
        activity = cast(
            ActivityRow,
            self.repository.scoped(ActivityRow, activity_id, actor.workspace_id),
        )
        if activity.status != "NEEDS_REVIEW":
            raise WorkflowError(
                "POLICY_DECISION_NOT_EXPECTED",
                "Activity is not awaiting an ambiguity decision",
                status_code=409,
            )
        report_row = cast(
            AmbiguityRow,
            self.repository.scoped(AmbiguityRow, activity_id, actor.workspace_id),
        )
        report = m.AmbiguityReport.model_validate(report_row.data)
        issue = next((item for item in report.issues if item.issue_id == issue_id), None)
        if issue is None:
            raise WorkflowError("INVENTED_ID", "Unknown ambiguity issue", status_code=404)
        if selected_option_id not in {item.option_id for item in issue.options}:
            raise WorkflowError(
                "INVENTED_ID", "Selected option does not belong to the issue"
            )
        decision = m.PolicyDecision(
            decision_id=stable_id(
                "decision", actor.workspace_id, activity_id, issue_id, selected_option_id
            ),
            issue_id=issue_id,
            selected_option_id=selected_option_id,
            decided_by=actor.user_id,
            decided_at=utc_now(),
            note=note,
        )
        try:
            self.repository.add_policy_decision(
                PolicyDecisionRow(
                    id=decision.decision_id,
                    tenant_id=actor.workspace_id,
                    activity_id=activity_id,
                    issue_id=issue_id,
                    data=decision.model_dump(mode="json"),
                )
            )
        except Conflict as exc:
            raise WorkflowError(
                "POLICY_DECISION_ALREADY_EXISTS",
                "This issue already has a durable teacher decision",
                status_code=409,
            ) from exc
        self.repository.audit(
            tenant_id=actor.workspace_id,
            event_type="policy_decision.created",
            aggregate_id=decision.decision_id,
            actor_id=actor.user_id,
            payload={"activity_id": activity_id, "issue_id": issue_id},
        )
        return decision

    def _resolved_policy_decisions(
        self, activity_id: str, tenant_id: str
    ) -> list[m.PolicyDecision]:
        return [
            m.PolicyDecision.model_validate(row.data)
            for row in self.repository.policy_decisions(activity_id, tenant_id)
        ]

    def create_upload(
        self,
        *,
        actor: Actor,
        activity_id: str,
        filename: str,
        media_type: str,
        expected_byte_size: int,
        role: m.ArtifactRole,
        submission_id: str | None = None,
    ) -> tuple[ArtifactRow, dict[str, Any]]:
        activity = cast(ActivityRow, self.repository.scoped(ActivityRow, activity_id, actor.workspace_id))
        activity_config = m.ActivityConfig.model_validate(activity.config)
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise WorkflowError("INGEST_UNSUPPORTED_MEDIA", "Media type is not enabled")
        if media_type not in activity_config.allowed_artifact_media_types:
            raise WorkflowError(
                "INGEST_UNSUPPORTED_MEDIA",
                "Media type is not enabled for this activity",
            )
        if expected_byte_size < 1 or expected_byte_size > self.settings.max_upload_bytes:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Declared object size is invalid")
        safe_filename = Path(filename).name[:512]
        if not safe_filename or safe_filename in {".", ".."}:
            raise WorkflowError("INGEST_FILENAME_INVALID", "Artifact filename is invalid")
        if role not in {m.ArtifactRole.ASSIGNMENT_PROMPT, m.ArtifactRole.RUBRIC, m.ArtifactRole.SUBMISSION}:
            raise WorkflowError("INGEST_ROLE_INVALID", "Artifact role is not accepted")
        if role == m.ArtifactRole.SUBMISSION:
            self._require_submission_reviewer(actor)
            if not submission_id:
                raise WorkflowError("IR_PROVENANCE_GAP", "Submission upload requires submission_id")
            submission = cast(
                SubmissionRow,
                self.repository.scoped(SubmissionRow, submission_id, actor.workspace_id),
            )
            if submission.activity_id != activity.id:
                raise WorkflowError("CROSS_SUBMISSION_EVIDENCE", "Submission belongs to another activity", status_code=404)
            submission_state = m.SubmissionProcessingState.model_validate(submission.state)
            if (
                submission_state.status != m.SubmissionProcessingStatus.UPLOADED
                or submission.active_job_id is not None
            ):
                raise WorkflowError(
                    "SUBMISSION_INPUTS_FROZEN",
                    "Submission inputs are immutable after the pipeline is queued",
                    status_code=409,
                )
        elif submission_id is not None:
            raise WorkflowError("IR_PROVENANCE_GAP", "Activity source cannot carry submission_id")
        else:
            self._require_activity_teacher(actor)
            if activity.status not in ACTIVITY_UPLOAD_OPEN_STATUSES:
                raise WorkflowError(
                    "ACTIVITY_INPUTS_FROZEN",
                    "Activity inputs are immutable while a pipeline is active or reviewable",
                    status_code=409,
                )
        current = self.repository.artifacts_for(
            activity_id=activity_id,
            tenant_id=actor.workspace_id,
            submission_id=submission_id,
            complete_only=False,
        )
        existing = next((item for item in current if item.role == role.value), None)
        now = utc_now()
        if existing is not None:
            expires_at = existing.upload_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if existing.status != "REJECTED" and not (
                existing.status == "PENDING" and expires_at <= now
            ):
                raise WorkflowError(
                    "ARTIFACT_ALREADY_EXISTS",
                    "Only one artifact of this role may be active or completed.",
                    status_code=409,
                )
            artifact_id = existing.id
        else:
            artifact_id = stable_id(
                "art",
                actor.workspace_id,
                activity_id,
                submission_id or role.value,
                filename,
                now,
            )
        upload_attempt_id = stable_id("upload", artifact_id, now)
        object_key = (
            f"raw/{actor.workspace_id}/{activity_id}/{artifact_id}/"
            f"{upload_attempt_id}"
        )
        signed = self.object_store.sign_put(
            object_key, media_type, expected_byte_size
        )
        row = ArtifactRow(
            id=artifact_id,
            tenant_id=actor.workspace_id,
            activity_id=activity_id,
            submission_id=submission_id,
            scope_key=submission_id or "__ACTIVITY__",
            role=role.value,
            filename=safe_filename,
            object_key=object_key,
            declared_media_type=media_type,
            expected_byte_size=expected_byte_size,
            status="PENDING",
            upload_expires_at=signed.expires_at,
        )
        try:
            row = self.repository.reserve_artifact_upload(
                row,
                allowed_activity_statuses=set(ACTIVITY_UPLOAD_OPEN_STATUSES),
            )
        except Conflict as exc:
            conflict_code = str(exc)
            if conflict_code in {"ACTIVITY_INPUTS_FROZEN", "SUBMISSION_INPUTS_FROZEN"}:
                raise WorkflowError(
                    conflict_code,
                    "Inputs became immutable before the upload session was reserved",
                    status_code=409,
                ) from exc
            if conflict_code in {
                "ARTIFACT_ALREADY_EXISTS",
                "ARTIFACT_RESERVATION_CHANGED",
            }:
                raise WorkflowError(
                    "ARTIFACT_ALREADY_EXISTS",
                    "Only one artifact of this role may be active or completed.",
                    status_code=409,
                ) from exc
            raise
        except IntegrityError as exc:
            raise WorkflowError(
                "ARTIFACT_ALREADY_EXISTS",
                "Only one artifact of this role is allowed in Stage 1",
                status_code=409,
            ) from exc
        return row, {
            "artifact_id": artifact_id,
            "upload_url": signed.url,
            "expires_at": signed.expires_at.isoformat(),
            "headers": signed.headers,
        }

    def complete_upload(
        self,
        artifact_id: str,
        actor: Actor,
        *,
        claimed_sha256: str | None = None,
        claimed_byte_size: int | None = None,
        claimed_media_type: str | None = None,
    ) -> m.ArtifactRef:
        artifact = cast(ArtifactRow, self.repository.scoped(ArtifactRow, artifact_id, actor.workspace_id))
        if artifact.role == m.ArtifactRole.SUBMISSION.value:
            self._require_submission_reviewer(actor)
        else:
            self._require_activity_teacher(actor)
        if artifact.status == "COMPLETE":
            self._assert_completion_claims(
                artifact,
                claimed_sha256=claimed_sha256,
                claimed_byte_size=claimed_byte_size,
                claimed_media_type=claimed_media_type,
            )
            self._verified_artifact_bytes(artifact)
            return self._artifact_ref(artifact)
        if artifact.upload_expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            raise WorkflowError("UPLOAD_EXPIRED", "Upload session expired", status_code=410)
        try:
            metadata = self.object_store.head(artifact.object_key)
        except KeyError as exc:
            raise WorkflowError("UPLOAD_INCOMPLETE", "Object has not been uploaded") from exc
        if (
            metadata.byte_size != artifact.expected_byte_size
            or metadata.byte_size > self.settings.max_upload_bytes
        ):
            raise WorkflowError("INGEST_SIZE_LIMIT", "Object size is invalid")
        if metadata.content_type != artifact.declared_media_type:
            raise WorkflowError("INGEST_MIME_MISMATCH", "Signed content type differs")
        try:
            data = self.object_store.get_bytes(
                artifact.object_key, max_bytes=artifact.expected_byte_size
            )
        except ObjectSizeExceeded as exc:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Object size is invalid") from exc
        if len(data) != artifact.expected_byte_size:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Object size is invalid")
        digest = sha256_bytes(data)
        if claimed_sha256 is not None and claimed_sha256 != digest:
            raise WorkflowError(
                "UPLOAD_COMPLETION_MISMATCH",
                "Completion metadata does not match the object",
            )
        if claimed_byte_size is not None and claimed_byte_size != len(data):
            raise WorkflowError(
                "UPLOAD_COMPLETION_MISMATCH",
                "Completion metadata does not match the object",
            )
        if claimed_media_type is not None and claimed_media_type != metadata.content_type:
            raise WorkflowError(
                "UPLOAD_COMPLETION_MISMATCH",
                "Completion metadata does not match the object",
            )
        try:
            parsed = self._parse_bytes(artifact, data)
        except ParseRejected as exc:
            # The rejection is observable and content-free.  The hostile
            # object remains unsealed and cannot enter either pipeline.
            self.repository.mark_artifact_rejected(
                artifact.id, actor.workspace_id
            )
            self.repository.audit(
                tenant_id=actor.workspace_id,
                event_type="artifact.rejected",
                aggregate_id=artifact.id,
                actor_id=actor.user_id,
                payload={
                    "activity_id": artifact.activity_id,
                    "submission_id": artifact.submission_id,
                    "code": exc.code,
                    "object_sha256": digest,
                    "byte_size": len(data),
                },
            )
            raise WorkflowError(
                exc.code,
                "The artifact was rejected at a safe parser boundary.",
                status_code=422,
            ) from exc
        sealed_key = self._sealed_object_key(artifact, digest)
        try:
            self.object_store.put_immutable(
                sealed_key, data, parsed.artifact.media_type
            )
        except PermissionError as exc:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "Immutable artifact sealing failed",
                status_code=409,
            ) from exc
        try:
            completed = self.repository.update_artifact_complete(
                artifact_id,
                tenant_id=actor.workspace_id,
                object_key=sealed_key,
                media_type=parsed.artifact.media_type,
                byte_size=len(data),
                sha256=digest,
                allowed_activity_statuses=set(ACTIVITY_UPLOAD_OPEN_STATUSES),
            )
        except Conflict as exc:
            if str(exc) in {"ACTIVITY_INPUTS_FROZEN", "SUBMISSION_INPUTS_FROZEN"}:
                raise WorkflowError(
                    str(exc),
                    "Inputs became immutable before upload completion",
                    status_code=409,
                ) from exc
            raise
        return self._artifact_ref(completed)

    def _cost_estimate(
        self,
        *,
        phase: str,
        aggregate_id: str,
        calls: int,
        input_bytes: int,
        fingerprint_source: dict[str, Any],
    ) -> dto.CostEstimate:
        input_fingerprint = canonical_hash(fingerprint_source)
        execution_model_mode = getattr(
            self.settings, "worker_model_mode", self.settings.model_mode
        )
        # A conservative deterministic envelope: every call may receive the
        # complete bounded native input plus trusted prompt/context overhead.
        if execution_model_mode == "mock":
            estimated_input_tokens = calls * ((input_bytes + 3) // 4 + 1_000)
            estimated_output_tokens = calls * 2_000
            upper_bound_cost_usd = round(calls * 0.01, 6)
            estimated_cost_usd = 0.0
        else:
            if phase == "ACTIVITY_BLUEPRINT":
                prompt_ids = [
                    "P01_ACTIVITY_SPEC_V1",
                    *(["P02_RUBRIC_NORMALIZE_V1"] if calls == 5 else []),
                    "P03_AMBIGUITY_TRIAGE_V1",
                    "P04_BLUEPRINT_BUILD_V1",
                    "P05_BLUEPRINT_REVIEW_V1",
                ]
            elif phase == "SUBMISSION_ASSESSMENT" and calls >= 2:
                question_count = max(0, (calls - 2) // 2)
                prompt_ids = [
                    "P06_EVIDENCE_MAP_V1",
                    *[
                        prompt_id
                        for _ in range(question_count)
                        for prompt_id in (
                            "P07_QUESTION_BUILD_V1",
                            "P08_QUESTION_REVIEW_V1",
                        )
                    ],
                    "P09_GUIDE_BUILD_V1",
                ]
            else:
                raise ValueError(f"Unknown real-mode cost phase: {phase}")
            if len(prompt_ids) != calls:
                raise ValueError("Real-mode cost profile does not match call count")

            # Thirty thousand tokens conservatively cover the largest current
            # strict schema, instructions, envelope metadata, and provider
            # framing before adding every native input byte as one token.
            per_call_input_ceiling = min(250_000, input_bytes + 30_000)
            estimated_input_tokens = 0
            estimated_output_tokens = 0
            upper_bound_cost_usd = 0.0
            for prompt_id in prompt_ids:
                spec = prompt_spec(prompt_id)
                attempts = min(2, spec.max_transient_retries) + 1
                estimated_input_tokens += per_call_input_ceiling * (attempts + 1)
                estimated_output_tokens += spec.max_output_tokens * attempts + 8_000
                upper_bound_cost_usd += estimate_cost_usd(
                    model=OPENAI_MODEL_BY_PROMPT[prompt_id],
                    input_tokens=per_call_input_ceiling,
                    output_tokens=spec.max_output_tokens,
                ) * attempts
                upper_bound_cost_usd += estimate_cost_usd(
                    model=LUNA_MODEL_ID,
                    input_tokens=per_call_input_ceiling,
                    output_tokens=8_000,
                )
            upper_bound_cost_usd = round(upper_bound_cost_usd, 6)
            estimated_cost_usd = upper_bound_cost_usd
        return dto.CostEstimate(
            estimate_id=stable_id(
                "estimate", phase, aggregate_id, input_fingerprint, calls
            ),
            phase=phase,
            model_mode=execution_model_mode,
            estimated_model_calls=calls,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            upper_bound_cost_usd=upper_bound_cost_usd,
            authorized_limit_usd=self.settings.max_job_cost_usd,
            within_limit=upper_bound_cost_usd <= self.settings.max_job_cost_usd,
            assumptions=[
                "CVA_MODEL_MODE=mock has zero billable provider cost during Stage 1 closure."
                if execution_model_mode == "mock"
                else "Provider pricing is an upper-bound estimate, not a quoted price.",
                "P10 and course-enriched context remain disabled.",
                "Real-mode upper bounds include the technical retry ceiling and one eligible P11 repair per semantic call."
                if execution_model_mode == "real"
                else "The mock estimate covers one durable run and no billable retry.",
            ],
            input_fingerprint=input_fingerprint,
            generated_at=utc_now(),
        )

    @staticmethod
    def _artifact_estimate_fingerprint(artifacts: list[ArtifactRow]) -> list[dict[str, Any]]:
        return [
            {
                "artifact_id": row.id,
                "role": row.role,
                "byte_size": row.byte_size,
                "sha256": row.sha256,
                "status": row.status,
            }
            for row in sorted(artifacts, key=lambda item: item.id)
        ]

    def activity_cost_estimate(
        self, activity_id: str, actor: Actor
    ) -> dto.CostEstimate:
        activity = cast(
            ActivityRow,
            self.repository.scoped(ActivityRow, activity_id, actor.workspace_id),
        )
        artifacts = self.repository.artifacts_for(
            activity_id=activity.id,
            tenant_id=actor.workspace_id,
            submission_id=None,
        )
        calls = 5 if any(row.role == m.ArtifactRole.RUBRIC.value for row in artifacts) else 4
        return self._cost_estimate(
            phase="ACTIVITY_BLUEPRINT",
            aggregate_id=activity.id,
            calls=calls,
            input_bytes=sum(row.byte_size or 0 for row in artifacts),
            fingerprint_source={
                "activity_config": activity.config,
                "artifacts": self._artifact_estimate_fingerprint(artifacts),
                "pipeline_version": ACTIVITY_PIPELINE_VERSION,
            },
        )

    def submission_cost_estimate(
        self, submission_id: str, actor: Actor
    ) -> dto.CostEstimate:
        submission = cast(
            SubmissionRow,
            self.repository.scoped(
                SubmissionRow, submission_id, actor.workspace_id
            ),
        )
        _row, blueprint = self._approved_blueprint(
            activity_id=submission.activity_id,
            tenant_id=actor.workspace_id,
        )
        artifacts = self.repository.artifacts_for(
            activity_id=submission.activity_id,
            tenant_id=actor.workspace_id,
            submission_id=submission.id,
        )
        # Reserve the complete governed replacement surface: P06 and P09 once,
        # plus P07/P08 for every selected and maximum reserve opportunity.
        constraints = blueprint.assessment_constraints
        calls = 2 + 2 * (
            constraints.question_count + constraints.max_reserve_opportunities
        )
        return self._cost_estimate(
            phase="SUBMISSION_ASSESSMENT",
            aggregate_id=submission.id,
            calls=calls,
            input_bytes=sum(row.byte_size or 0 for row in artifacts),
            fingerprint_source={
                "submission_id": submission.id,
                "blueprint_id": blueprint.blueprint_id,
                "blueprint_version": blueprint.blueprint_version,
                "question_count": blueprint.assessment_constraints.question_count,
                "artifacts": self._artifact_estimate_fingerprint(artifacts),
                "pipeline_version": SUBMISSION_PIPELINE_VERSION,
            },
        )

    @staticmethod
    def _require_cost_within_limit(estimate: dto.CostEstimate) -> None:
        if not estimate.within_limit:
            raise WorkflowError(
                "COST_LIMIT_EXCEEDED",
                "The conservative Stage 1 cost envelope exceeds the authorized limit",
                status_code=409,
            )

    async def enqueue_activity_pipeline(self, activity_id: str, actor: Actor) -> m.JobStatus:
        self._require_activity_teacher(actor)
        activity = cast(ActivityRow, self.repository.scoped(ActivityRow, activity_id, actor.workspace_id))
        allowed_statuses = {"DRAFT"}
        if activity.status == "NEEDS_REVIEW":
            try:
                report = m.AmbiguityReport.model_validate(
                    cast(
                        AmbiguityRow,
                        self.repository.scoped(
                            AmbiguityRow, activity_id, actor.workspace_id
                        ),
                    ).data
                )
            except NotFound as exc:
                raise WorkflowError(
                    "ACTIVITY_PIPELINE_ALREADY_STARTED",
                    "Stage 1 does not retry completed activity stages",
                    status_code=409,
                ) from exc
            decided_issue_ids = {
                item.issue_id
                for item in self._resolved_policy_decisions(
                    activity_id, actor.workspace_id
                )
            }
            blocking_issue_ids = {
                issue.issue_id for issue in report.issues if issue.blocking
            }
            if (
                not report.blocked
                or not blocking_issue_ids
                or not blocking_issue_ids.issubset(decided_issue_ids)
            ):
                raise WorkflowError(
                    "POLICY_DECISION_REQUIRED",
                    "Every blocking ambiguity requires a teacher decision",
                    status_code=409,
                )
            allowed_statuses.add("NEEDS_REVIEW")
        elif activity.status != "DRAFT":
            raise WorkflowError(
                "ACTIVITY_PIPELINE_ALREADY_STARTED",
                "Stage 1 runs the activity pipeline once per decision state",
                status_code=409,
            )
        sources = self.repository.artifacts_for(
            activity_id=activity.id, tenant_id=actor.workspace_id, submission_id=None
        )
        if not any(row.role == m.ArtifactRole.ASSIGNMENT_PROMPT.value for row in sources):
            raise WorkflowError("ASSIGNMENT_FIELD_MISSING", "Assignment prompt is required")
        self._require_cost_within_limit(
            self.activity_cost_estimate(activity_id, actor)
        )
        job = self._new_job(actor.workspace_id, activity_id, "ACTIVITY", "ACTIVITY_PARSE")
        try:
            self.repository.queue_activity_job(
                job, allowed_activity_statuses=allowed_statuses
            )
        except Conflict as exc:
            if str(exc) == "ARTIFACT_UPLOAD_PENDING":
                raise WorkflowError(
                    "ARTIFACT_UPLOAD_PENDING",
                    "Every activity upload must complete before the pipeline is queued",
                    status_code=409,
                ) from exc
            raise WorkflowError(
                "ACTIVITY_PIPELINE_ALREADY_STARTED",
                "An activity pipeline is already active or complete",
                status_code=409,
            ) from exc
        if self.job_runner is None:
            raise RuntimeError("JobRunner is not configured")
        try:
            await self.job_runner.dispatch(job.job_id)
        except Exception:
            self.repository.fail_queued_dispatch(
                job_id=job.job_id,
                tenant_id=actor.workspace_id,
                failure=diagnostic(
                    "JOB_DISPATCH_FAILED",
                    "The durable job could not be dispatched.",
                    retryable=True,
                ),
            )
        return self.repository.job_status(job.job_id, actor.workspace_id)

    def _approved_blueprint(
        self,
        *,
        activity_id: str,
        tenant_id: str,
        version: int | None = None,
    ) -> tuple[BlueprintRow, m.AssessmentBlueprint]:
        try:
            row = (
                self.repository.latest_blueprint(activity_id, tenant_id)
                if version is None
                else self.repository.blueprint_version(activity_id, version, tenant_id)
            )
        except NotFound as exc:
            raise WorkflowError(
                "BLUEPRINT_NOT_APPROVED",
                "Submission requires an approved blueprint",
                status_code=409,
            ) from exc
        approved = m.AssessmentBlueprint.model_validate(row.data)
        if (
            row.status != m.WorkflowStatus.APPROVED.value
            or approved.status != m.WorkflowStatus.APPROVED
            or not approved.approved_by
            or approved.approved_at is None
            or not self.repository.has_audit_event(
                tenant_id=tenant_id,
                event_type="blueprint.approved",
                aggregate_id=approved.blueprint_id,
                payload_contains={"blueprint_version": row.version},
            )
        ):
            raise WorkflowError(
                "BLUEPRINT_NOT_APPROVED",
                "Submission requires an approved blueprint",
                status_code=409,
            )
        return row, approved

    async def enqueue_submission_pipeline(self, submission_id: str, actor: Actor) -> m.JobStatus:
        self._require_submission_reviewer(actor)
        submission = cast(
            SubmissionRow,
            self.repository.scoped(SubmissionRow, submission_id, actor.workspace_id),
        )
        blueprint, _approved = self._approved_blueprint(
            activity_id=submission.activity_id,
            tenant_id=actor.workspace_id,
        )
        current_state = m.SubmissionProcessingState.model_validate(submission.state)
        if (
            current_state.status != m.SubmissionProcessingStatus.UPLOADED
            or submission.active_job_id is not None
        ):
            raise WorkflowError(
                "SUBMISSION_PIPELINE_ALREADY_STARTED",
                "Stage 1 runs a submission pipeline only once",
                status_code=409,
            )
        artifacts = self.repository.artifacts_for(
            activity_id=submission.activity_id,
            tenant_id=actor.workspace_id,
            submission_id=submission.id,
        )
        if len(artifacts) != 1:
            raise WorkflowError("SUBMISSION_ARTIFACT_REQUIRED", "Stage 1 requires exactly one completed deliverable")
        self._require_cost_within_limit(
            self.submission_cost_estimate(submission_id, actor)
        )
        job = self._new_job(actor.workspace_id, submission.id, "SUBMISSION", "SUBMISSION_PARSE")
        queued_state = m.SubmissionProcessingState(
            submission_id=submission.id,
            activity_id=submission.activity_id,
            status=m.SubmissionProcessingStatus.UPLOADED,
            current_stage="SUBMISSION_PARSE",
            progress=0.0,
            active_job_id=job.job_id,
            updated_at=utc_now(),
        )
        try:
            self.repository.queue_submission_job(
                job,
                queued_state,
                blueprint_version=blueprint.version,
            )
        except Conflict as exc:
            if str(exc) == "SUBMISSION_ARTIFACT_REQUIRED":
                raise WorkflowError(
                    "SUBMISSION_ARTIFACT_REQUIRED",
                    "Stage 1 requires exactly one completed deliverable",
                    status_code=409,
                ) from exc
            raise WorkflowError(
                "SUBMISSION_PIPELINE_ALREADY_STARTED",
                "A submission pipeline is already active or complete",
                status_code=409,
            ) from exc
        if self.job_runner is None:
            raise RuntimeError("JobRunner is not configured")
        try:
            await self.job_runner.dispatch(job.job_id)
        except Exception:
            self.repository.fail_queued_dispatch(
                job_id=job.job_id,
                tenant_id=actor.workspace_id,
                failure=diagnostic(
                    "JOB_DISPATCH_FAILED",
                    "The durable job could not be dispatched.",
                    retryable=True,
                ),
            )
        return self.repository.job_status(job.job_id, actor.workspace_id)

    async def process_job(self, job_id: str) -> None:
        job = cast(JobRow, self.repository.get(JobRow, job_id))
        try:
            self._cancellation_checkpoint(job)
            current = self.repository.job_status(job.id, job.tenant_id)
            attempt = (
                current.attempt
                if current.status == "RUNNING" and current.attempt
                else current.attempt + 1
            )
            running = current.model_copy(
                update={
                    "status": "RUNNING",
                    "attempt": max(1, attempt),
                    "started_at": current.started_at or utc_now(),
                }
            )
            self.repository.save_job_status(running)
            self._cancellation_checkpoint(job)
            if job.kind == "ACTIVITY":
                await self._run_activity_pipeline(job)
            elif job.kind == "SUBMISSION":
                await self._run_submission_pipeline(job)
            elif job.kind == "BLUEPRINT_REVIEW":
                await self._run_blueprint_review_job(job)
            elif job.kind == "QUESTION_ACTION" and self._question_action_processor:
                await self._question_action_processor(job)
            else:
                raise WorkflowError("JOB_KIND_INVALID", "Unknown job kind", status_code=500)
        except _CooperativeJobCancellation:
            return
        except Exception as exc:
            # Never persist exception text because it may contain provider or input detail.
            failure_class, retryable, code = self._classify_failure(exc)
            self._fail_job(
                job,
                code,
                "The workflow failed at a content-minimizing boundary.",
                failure_class=failure_class,
                retryable=retryable,
            )
        finally:
            self._resume_floor_reached.discard(job.id)

    async def _run_activity_pipeline(self, job: JobRow) -> None:
        activity = cast(ActivityRow, self.repository.scoped(ActivityRow, job.aggregate_id, job.tenant_id))
        config = m.ActivityConfig.model_validate(activity.config)
        policy = m.BlueprintPolicy.model_validate(activity.blueprint_policy)
        artifacts = self.repository.artifacts_for(
            activity_id=activity.id, tenant_id=job.tenant_id, submission_id=None
        )
        evidence_by_role: dict[str, list[m.EvidenceUnit]] = {}
        for artifact in artifacts:
            self._cancellation_checkpoint(job)
            parsed = self._parse_bytes(
                artifact, self._verified_artifact_bytes(artifact)
            )
            self._cancellation_checkpoint(job)
            evidence_by_role[artifact.role] = list(parsed.evidence_units)
        prompt_evidence = evidence_by_role.get(m.ArtifactRole.ASSIGNMENT_PROMPT.value, [])
        self._set_job(job, "ACTIVITY_SPEC", 0.15)
        p01 = await self._gateway_stage(
            job,
            "P01_ACTIVITY_SPEC_V1",
            m.ActivitySpecRequest(activity_config=config, prompt_evidence=prompt_evidence),
            m.ActivitySpec,
        )
        self.repository.save_activity_output(
            ActivitySpecRow, activity.id, job.tenant_id, p01.model_dump(mode="json")
        )
        if p01.status != m.WorkflowStatus.READY:
            self._stop_activity_output(
                activity, job, p01.status.value, p01.diagnostics
            )
            return
        rubric: m.RubricSpec | None = None
        rubric_evidence = evidence_by_role.get(m.ArtifactRole.RUBRIC.value, [])
        if rubric_evidence:
            self._set_job(job, "RUBRIC_NORMALIZE", 0.3)
            rubric = await self._gateway_stage(
                job,
                "P02_RUBRIC_NORMALIZE_V1",
                m.RubricNormalizeRequest(activity_spec=p01, rubric_evidence=rubric_evidence),
                m.RubricSpec,
            )
            self.repository.save_activity_output(
                RubricSpecRow, activity.id, job.tenant_id, rubric.model_dump(mode="json")
            )
            if rubric.status != m.WorkflowStatus.READY:
                self._stop_activity_output(
                    activity, job, rubric.status.value, rubric.diagnostics
                )
                return
        self._set_job(job, "AMBIGUITY_TRIAGE", 0.45)
        ambiguity = await self._gateway_stage(
            job,
            "P03_AMBIGUITY_TRIAGE_V1",
            m.AmbiguityTriageRequest(activity_spec=p01, rubric_spec=rubric),
            m.AmbiguityReport,
        )
        self.repository.save_activity_output(
            AmbiguityRow, activity.id, job.tenant_id, ambiguity.model_dump(mode="json")
        )
        resolved_decisions = self._resolved_policy_decisions(
            activity.id, job.tenant_id
        )
        issues_by_id = {issue.issue_id: issue for issue in ambiguity.issues}
        for decision in resolved_decisions:
            issue = issues_by_id.get(decision.issue_id)
            if issue is None or decision.selected_option_id not in {
                option.option_id for option in issue.options
            }:
                raise WorkflowError(
                    "POLICY_DECISION_INVALID",
                    "A persisted decision no longer matches the ambiguity report",
                    status_code=409,
                )
        blocking_issue_ids = {
            issue.issue_id for issue in ambiguity.issues if issue.blocking
        }
        decided_issue_ids = {decision.issue_id for decision in resolved_decisions}
        if ambiguity.blocked and (
            not blocking_issue_ids
            or not blocking_issue_ids.issubset(decided_issue_ids)
        ):
            self.repository.set_activity_status(activity.id, job.tenant_id, "NEEDS_REVIEW")
            self._needs_review_job(
                job,
                "ASSIGNMENT_AMBIGUOUS",
                [
                    diagnostic(
                        "ASSIGNMENT_AMBIGUOUS",
                        "La actividad requiere decisiones docentes para todas las ambigüedades bloqueantes.",
                    )
                ],
            )
            return
        self._set_job(job, "BLUEPRINT_BUILD", 0.65)
        blueprint = await self._gateway_stage(
            job,
            "P04_BLUEPRINT_BUILD_V1",
            m.BlueprintBuildRequest(
                activity_spec=p01,
                rubric_spec=rubric,
                resolved_decisions=resolved_decisions,
                blueprint_policy=policy,
            ),
            m.AssessmentBlueprint,
        )
        if blueprint.status != m.WorkflowStatus.READY:
            self._stop_activity_output(
                activity, job, blueprint.status.value, blueprint.diagnostics
            )
            return
        if set(blueprint.decision_ids) != {
            decision.decision_id for decision in resolved_decisions
        }:
            raise WorkflowError(
                "BLUEPRINT_REFERENCE_MISMATCH",
                "Blueprint does not bind the exact teacher decisions",
            )
        self._set_job(job, "BLUEPRINT_REVIEW", 0.82)
        review = await self._gateway_stage(
            job,
            "P05_BLUEPRINT_REVIEW_V1",
            m.BlueprintReviewRequest(
                blueprint=blueprint,
                activity_spec=p01,
                rubric_spec=rubric,
                resolved_decisions=resolved_decisions,
                blueprint_policy=policy,
            ),
            m.BlueprintReview,
        )
        row = self._blueprint_row(job.tenant_id, blueprint, review)
        with self.repository.session() as session:
            session.merge(row)
        if review.status != "READY" or (
            review.approval_recommendation
            == m.BlueprintApprovalRecommendation.REJECT
        ):
            if review.status == "TECHNICAL_FAILURE":
                self._fail_job(
                    job,
                    "BLUEPRINT_REVIEW_TECHNICAL_FAILURE",
                    "Blueprint review failed at a validated boundary.",
                )
            else:
                self.repository.set_activity_status(
                    activity.id, job.tenant_id, "NEEDS_REVIEW"
                )
                self._needs_review_job(
                    job,
                    "BLUEPRINT_REVIEW_BLOCKED",
                    review.diagnostics
                    or [
                        diagnostic(
                            "BLUEPRINT_REVIEW_BLOCKED",
                            "La revisión del blueprint requiere intervención docente.",
                        )
                    ],
                )
            return
        self.repository.set_activity_status(activity.id, job.tenant_id, "BLUEPRINT_READY")
        self._complete_job(job, "BLUEPRINT_REVIEW")

    async def _run_blueprint_review_job(self, job: JobRow) -> None:
        """Review one teacher edit through the same durable P05 boundary."""

        self._set_job(job, "BLUEPRINT_REVIEW", 0.25)
        descriptor = self.repository.blueprint_review_descriptor(
            job_ids=self._job_lineage_ids(job),
            tenant_id=job.tenant_id,
        )
        if descriptor is None or descriptor.output is None:
            raise WorkflowError(
                "BLUEPRINT_REVIEW_DESCRIPTOR_MISSING",
                "The durable blueprint review input is unavailable.",
                status_code=409,
            )
        if (
            descriptor.component_version != PROMPT_VERSION
            or descriptor.policy_hash != self._stage_policy_hash(job)
        ):
            raise WorkflowError(
                "BLUEPRINT_REVIEW_DESCRIPTOR_VERSION_MISMATCH",
                "The durable blueprint review input no longer matches this worker.",
                status_code=409,
            )
        try:
            request = m.BlueprintReviewRequest.model_validate(
                descriptor.output.get("review_request")
            )
            source_version = TypeAdapter(int).validate_python(
                descriptor.output.get("source_blueprint_version")
            )
            source_etag = TypeAdapter(str).validate_python(
                descriptor.output.get("source_etag")
            )
            actor_id = TypeAdapter(m.Id).validate_python(
                descriptor.output.get("actor_id")
            )
        except ValidationError as exc:
            raise WorkflowError(
                "BLUEPRINT_REVIEW_DESCRIPTOR_INVALID",
                "The durable blueprint review input is invalid.",
                status_code=409,
            ) from exc
        if (
            request.blueprint.activity_id != job.aggregate_id
            or request.blueprint.blueprint_version != source_version + 1
        ):
            raise WorkflowError(
                "BLUEPRINT_REVIEW_DESCRIPTOR_INVALID",
                "The durable blueprint review references are inconsistent.",
                status_code=409,
            )

        activity = cast(
            ActivityRow,
            self.repository.scoped(ActivityRow, job.aggregate_id, job.tenant_id),
        )
        latest = self.repository.latest_blueprint(job.aggregate_id, job.tenant_id)
        original = m.AssessmentBlueprint.model_validate(latest.data)
        persisted_activity_spec = m.ActivitySpec.model_validate(
            cast(
                ActivitySpecRow,
                self.repository.scoped(
                    ActivitySpecRow, job.aggregate_id, job.tenant_id
                ),
            ).data
        )
        try:
            persisted_rubric = m.RubricSpec.model_validate(
                cast(
                    RubricSpecRow,
                    self.repository.scoped(
                        RubricSpecRow, job.aggregate_id, job.tenant_id
                    ),
                ).data
            )
        except NotFound:
            persisted_rubric = None
        if any(
            (
                latest.version != source_version,
                latest.etag != source_etag,
                request.activity_spec != persisted_activity_spec,
                request.rubric_spec != persisted_rubric,
                request.blueprint_policy
                != m.BlueprintPolicy.model_validate(activity.blueprint_policy),
                request.resolved_decisions
                != self._resolved_policy_decisions(job.aggregate_id, job.tenant_id),
                _blueprint_structure(request.blueprint)
                != _blueprint_structure(original),
            )
        ):
            raise WorkflowError(
                "BLUEPRINT_REVIEW_SOURCE_CHANGED",
                "The blueprint review source changed before worker execution.",
                status_code=409,
            )

        review = await self._gateway_stage(
            job,
            "P05_BLUEPRINT_REVIEW_V1",
            request,
            m.BlueprintReview,
        )
        self._cancellation_checkpoint(job)
        row = self._blueprint_row(job.tenant_id, request.blueprint, review)
        finalized = self.repository.finalize_blueprint_review_job(
            job_id=job.id,
            tenant_id=job.tenant_id,
            source_version=source_version,
            source_etag=source_etag,
            blueprint=row,
            actor_id=actor_id,
        )
        if not finalized:
            raise _CooperativeJobCancellation

    async def _run_submission_pipeline(self, job: JobRow) -> None:
        submission = cast(SubmissionRow, self.repository.scoped(SubmissionRow, job.aggregate_id, job.tenant_id))
        activity = cast(ActivityRow, self.repository.scoped(ActivityRow, submission.activity_id, job.tenant_id))
        if submission.blueprint_version is None:
            raise WorkflowError(
                "BLUEPRINT_NOT_APPROVED",
                "Submission job is not bound to an approved blueprint version",
                status_code=409,
            )
        _blueprint_row, blueprint = self._approved_blueprint(
            activity_id=activity.id,
            tenant_id=job.tenant_id,
            version=submission.blueprint_version,
        )
        policy = m.BlueprintPolicy.model_validate(activity.blueprint_policy)
        artifacts = self.repository.artifacts_for(
            activity_id=activity.id, tenant_id=job.tenant_id, submission_id=submission.id
        )
        artifact = artifacts[0]
        self._set_submission(submission, job, m.SubmissionProcessingStatus.PARSING, "SUBMISSION_PARSE", 0.08)
        parse_inputs = {
            "artifact_id": artifact.id,
            "artifact_sha256": artifact.sha256,
            "artifact_byte_size": artifact.byte_size,
            "declared_media_type": artifact.declared_media_type,
            "media_type": artifact.media_type,
        }
        parse_policy_hash = self._stage_policy_hash(job)
        cached_parse = self.repository.stage_by_key(
            tenant_id=job.tenant_id,
            stage="SUBMISSION_PARSE",
            inputs=parse_inputs,
            policy_hash=parse_policy_hash,
            component_version=PARSER_VERSION,
        )
        if cached_parse is not None and cached_parse.output is not None:
            evidence_units = tuple(
                TypeAdapter(list[m.EvidenceUnit]).validate_python(
                    cached_parse.output.get("evidence_units", [])
                )
            )
            if not evidence_units:
                raise WorkflowError(
                    "STAGE_RESUME_REUSE_MISSING",
                    "The reusable parse stage has no verified evidence output.",
                    status_code=409,
                )
            self._record_stage_reuse(job, cached_parse)
        else:
            self._assert_application_stage_may_execute(job, "SUBMISSION_PARSE")
            parsed = self._parse_bytes(
                artifact, self._verified_artifact_bytes(artifact)
            )
            evidence_units = tuple(parsed.evidence_units)
            self.repository.save_stage(
                job_id=job.id,
                tenant_id=job.tenant_id,
                stage="SUBMISSION_PARSE",
                inputs=parse_inputs,
                component_version=PARSER_VERSION,
                policy_hash=parse_policy_hash,
                output={
                    "evidence_units": [
                        item.model_dump(mode="json") for item in evidence_units
                    ]
                },
            )
        self._cancellation_checkpoint(job)
        with self.repository.session() as session:
            for evidence in evidence_units:
                session.merge(
                    EvidenceRow(
                        id=evidence.evidence_id,
                        tenant_id=job.tenant_id,
                        submission_id=submission.id,
                        artifact_id=artifact.id,
                        data=evidence.model_dump(mode="json"),
                    )
                )
        bundle = m.EvidenceBundle(
            bundle_id=stable_id("bundle", submission.id, artifact.sha256),
            tenant_id=job.tenant_id,
            activity_id=activity.id,
            submission_id=submission.id,
            context_mode=m.ContextMode.CLOSED,
            allowed_evidence_ids=[item.evidence_id for item in evidence_units],
            evidence_units=list(evidence_units),
            course_passages=[],
        )
        self._set_submission(submission, job, m.SubmissionProcessingStatus.EVIDENCE_READY, "EVIDENCE_MAP", 0.2)
        mapping = await self._gateway_stage(
            job,
            "P06_EVIDENCE_MAP_V1",
            m.EvidenceMapRequest(blueprint=blueprint, evidence_bundle=bundle),
            m.EvidenceMapPatch,
        )
        validate_evidence_map(mapping, blueprint=blueprint, bundle=bundle)
        with self.repository.session() as session:
            session.merge(EvidenceMapRow(submission_id=submission.id, tenant_id=job.tenant_id, data=mapping.model_dump(mode="json")))
        self._set_submission(submission, job, m.SubmissionProcessingStatus.PLANNING, "ASSESSMENT_PLAN", 0.32)
        plan_inputs = {
            "mapping": mapping.model_dump(mode="json"),
            "blueprint": blueprint.model_dump(mode="json"),
            "planning_policy": policy.planning_policy.model_dump(mode="json"),
        }
        plan_policy_hash = self._stage_policy_hash(job)
        cached_plan = self.repository.stage_by_key(
            tenant_id=job.tenant_id,
            stage="ASSESSMENT_PLAN",
            inputs=plan_inputs,
            policy_hash=plan_policy_hash,
            component_version=PLANNER_VERSION,
        )
        if cached_plan is not None and cached_plan.output is not None:
            plan = m.AssessmentPlan.model_validate(cached_plan.output)
            self._record_stage_reuse(job, cached_plan)
        else:
            self._assert_application_stage_may_execute(job, "ASSESSMENT_PLAN")
            plan = build_assessment_plan(
                mapping=mapping,
                blueprint=blueprint,
                policy=policy.planning_policy,
            )
            self.repository.save_stage(
                job_id=job.id,
                tenant_id=job.tenant_id,
                stage="ASSESSMENT_PLAN",
                inputs=plan_inputs,
                component_version=PLANNER_VERSION,
                policy_hash=plan_policy_hash,
                output=plan.model_dump(mode="json"),
            )
        validate_assessment_plan(plan, mapping=mapping)
        self._cancellation_checkpoint(job)
        with self.repository.session() as session:
            session.merge(AssessmentPlanRow(submission_id=submission.id, tenant_id=job.tenant_id, data=plan.model_dump(mode="json")))
        if plan.status != "READY":
            self._terminal_domain_failure(submission, job, plan.status, plan.diagnostics)
            return
        opportunity_by_id = {item.opportunity_id: item for item in mapping.opportunities}
        generation_policy = m.QuestionGenerationPolicy(
            policy_id=stable_id("policy", activity.id, "question_generation")
        )
        validation_policy = m.QuestionValidationPolicy(
            policy_id=stable_id("policy", activity.id, "question_validation")
        )
        selected: list[m.SelectedQuestion] = []
        reviews: dict[str, m.QuestionReviewResult] = {}
        reserves = list(plan.reserve_opportunity_ids)
        primary_queue = list(plan.selected_opportunity_ids)
        self._set_submission(submission, job, m.SubmissionProcessingStatus.GENERATING, "QUESTION_GENERATE", 0.4)
        while primary_queue and len(selected) < plan.question_count:
            opportunity_id = primary_queue.pop(0)
            opportunity = opportunity_by_id[opportunity_id]
            generation = await self._gateway_stage(
                job,
                "P07_QUESTION_BUILD_V1",
                m.QuestionBuildRequest(
                    plan=plan,
                    opportunity=opportunity,
                    evidence_bundle=bundle,
                    generation_policy=generation_policy,
                    avoid=[],
                ),
                m.QuestionGenerationResult,
                cache_suffix=opportunity_id,
            )
            validate_generation_result(generation, opportunity=opportunity, bundle=bundle)
            self._cancellation_checkpoint(job)
            if generation.status != "READY" or generation.candidate is None:
                if reserves:
                    primary_queue.append(reserves.pop(0))
                    continue
                break
            self._set_submission(submission, job, m.SubmissionProcessingStatus.VALIDATING_QUESTIONS, "QUESTION_REVIEW", 0.55)
            review = await self._gateway_stage(
                job,
                "P08_QUESTION_REVIEW_V1",
                m.QuestionReviewRequest(
                    generation_result=generation,
                    opportunity=opportunity,
                    evidence_bundle=bundle,
                    validation_policy=validation_policy,
                ),
                m.QuestionReviewResult,
                cache_suffix=opportunity_id,
            )
            validate_review_result(
                review,
                generation_result=generation,
                validation_policy=validation_policy,
            )
            self._cancellation_checkpoint(job)
            if review.status != "READY" or review.review is None or review.review.decision != m.ReviewDecision.ACCEPT:
                if reserves:
                    primary_queue.append(reserves.pop(0))
                    continue
                break
            candidate = generation.candidate
            question_id = stable_id("question", submission.id, candidate.candidate_id)
            selected_question = m.SelectedQuestion(
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
                planning_score=(opportunity.activity_priority + opportunity.evidence_fit + opportunity.opportunity_quality) / 3,
            )
            selected.append(selected_question)
            reviews[question_id] = review
            with self.repository.session() as session:
                session.merge(
                    GeneratedQuestionRow(
                        id=candidate.candidate_id,
                        tenant_id=job.tenant_id,
                        submission_id=submission.id,
                        data=generation.model_dump(mode="json"),
                    )
                )
                session.merge(
                    QuestionReviewRow(
                        question_id=question_id,
                        tenant_id=job.tenant_id,
                        submission_id=submission.id,
                        data=review.model_dump(mode="json"),
                    )
                )
        if len(selected) != plan.question_count:
            self._terminal_domain_failure(
                submission,
                job,
                "ASSESSMENT_PLAN_INFEASIBLE",
                [diagnostic("ASSESSMENT_PLAN_INFEASIBLE", "No fue posible validar exactamente N preguntas tras usar la reserva.")],
            )
            return
        assessment = self._assemble_assessment(
            activity=activity,
            submission=submission,
            blueprint=blueprint,
            plan=plan,
            mapping=mapping,
            questions=selected,
            artifact=artifact,
            job=job,
        )
        guide_id = stable_id("guide", assessment.assessment_id, submission.id)
        self._set_submission(submission, job, m.SubmissionProcessingStatus.GUIDE_READY, "GUIDE_BUILD", 0.82)
        guide = await self._gateway_stage(
            job,
            "P09_GUIDE_BUILD_V1",
            m.GuideBuildRequest(guide_id=guide_id, assessment=assessment, evidence_bundle=bundle),
            m.EvaluationGuide,
        )
        validate_evaluation_guide(guide, assessment=assessment, bundle=bundle)
        self._cancellation_checkpoint(job)
        if guide.status != "READY":
            if guide.status == "NEEDS_REVIEW":
                self._terminal_domain_failure(
                    submission,
                    job,
                    m.SubmissionProcessingStatus.NEEDS_REVIEW.value,
                    guide.diagnostics,
                    stage="GUIDE_BUILD",
                )
            else:
                raise WorkflowError(
                    "GUIDE_TECHNICAL_FAILURE",
                    "Evaluation guide generation failed at a validated boundary",
                    status_code=500,
                )
            return
        assessment_row = AssessmentRow(
            row_id=stable_id("assessmentrow", assessment.assessment_id, 1),
            assessment_id=assessment.assessment_id,
            tenant_id=job.tenant_id,
            submission_id=submission.id,
            version=1,
            status=assessment.status.value,
            etag=_etag(assessment),
            data=assessment.model_dump(mode="json"),
        )
        self._mark_resume_floor(job, "ASSEMBLE")
        finalized = self.repository.finalize_submission_assessment(
            job_id=job.id,
            tenant_id=job.tenant_id,
            assessment=assessment_row,
            guide=GuideRow(
                guide_id=guide.guide_id,
                assessment_id=assessment.assessment_id,
                tenant_id=job.tenant_id,
                submission_id=submission.id,
                data=guide.model_dump(mode="json"),
            ),
        )
        if not finalized:
            raise _CooperativeJobCancellation

    def create_submission(self, *, activity_id: str, subject_ref: str, actor: Actor) -> SubmissionRow:
        self._require_submission_reviewer(actor)
        self.repository.scoped(ActivityRow, activity_id, actor.workspace_id)
        try:
            subject_ref = TypeAdapter(m.Id).validate_python(subject_ref)
        except ValidationError as exc:
            raise WorkflowError(
                "SUBJECT_REF_INVALID", "Subject reference must be a pseudonymous identifier"
            ) from exc
        submission_id = stable_id("sub", actor.workspace_id, activity_id, subject_ref)
        state = m.SubmissionProcessingState(
            submission_id=submission_id,
            activity_id=activity_id,
            status=m.SubmissionProcessingStatus.UPLOADED,
            progress=0.0,
            updated_at=utc_now(),
        )
        row = SubmissionRow(
            id=submission_id,
            tenant_id=actor.workspace_id,
            activity_id=activity_id,
            subject_ref=subject_ref,
            state=state.model_dump(mode="json"),
        )
        try:
            self.repository.add(row)
        except Exception as exc:
            raise WorkflowError("STAGE1_SINGLE_SUBMISSION_ONLY", "Stage 1 accepts one submission per activity", status_code=409) from exc
        return row

    async def edit_blueprint(
        self, *, activity_id: str, version: int, if_match: str, edited: m.AssessmentBlueprint, actor: Actor
    ) -> m.JobStatus:
        if actor.role not in {"OWNER", "TEACHER"}:
            raise WorkflowError("ROLE_FORBIDDEN", "Only teachers may edit blueprints", status_code=403)
        current = self.repository.blueprint_version(activity_id, version, actor.workspace_id)
        if current.etag != if_match:
            raise WorkflowError("ETAG_MISMATCH", "Blueprint has changed", status_code=412)
        original = m.AssessmentBlueprint.model_validate(current.data)
        latest = self.repository.latest_blueprint(activity_id, actor.workspace_id)
        if latest.row_id != current.row_id:
            raise WorkflowError(
                "BLUEPRINT_VERSION_CONFLICT",
                "Only the latest blueprint version may be edited",
                status_code=409,
            )
        if (
            original.status != m.WorkflowStatus.READY
            or original.approved_by is not None
            or original.approved_at is not None
        ):
            raise WorkflowError(
                "BLUEPRINT_FROZEN",
                "An approved blueprint version is immutable",
                status_code=409,
            )
        if edited.activity_id != original.activity_id or edited.blueprint_id != original.blueprint_id:
            raise WorkflowError("BLUEPRINT_REFERENCE_MISMATCH", "Blueprint identity is immutable")
        if _blueprint_structure(edited) != _blueprint_structure(original):
            raise WorkflowError(
                "BLUEPRINT_STRUCTURE_IMMUTABLE",
                "Stage 1 edits cannot widen trusted IDs, operations, formats or constraints",
            )
        updated = edited.model_copy(
            update={
                "blueprint_version": current.version + 1,
                "status": m.WorkflowStatus.READY,
                "approved_by": None,
                "approved_at": None,
            }
        )
        activity = cast(ActivityRow, self.repository.scoped(ActivityRow, activity_id, actor.workspace_id))
        if activity.status not in {"BLUEPRINT_READY", "NEEDS_REVIEW"}:
            raise WorkflowError(
                "BLUEPRINT_EDIT_NOT_ALLOWED",
                "Blueprint editing is not allowed in the current activity state",
                status_code=409,
            )
        activity_spec = m.ActivitySpec.model_validate(
            cast(
                ActivitySpecRow,
                self.repository.scoped(
                    ActivitySpecRow, activity_id, actor.workspace_id
                ),
            ).data
        )
        try:
            rubric_spec = m.RubricSpec.model_validate(
                cast(
                    RubricSpecRow,
                    self.repository.scoped(
                        RubricSpecRow, activity_id, actor.workspace_id
                    ),
                ).data
            )
        except NotFound:
            rubric_spec = None
        resolved_decisions = self._resolved_policy_decisions(
            activity_id, actor.workspace_id
        )
        review_request = m.BlueprintReviewRequest(
            blueprint=updated,
            activity_spec=activity_spec,
            rubric_spec=rubric_spec,
            resolved_decisions=resolved_decisions,
            blueprint_policy=m.BlueprintPolicy.model_validate(
                activity.blueprint_policy
            ),
        )
        queued = self._new_job(
            actor.workspace_id,
            activity_id,
            "blueprint_review",
            "BLUEPRINT_REVIEW",
        )
        queued_at = utc_now()
        descriptor_output = {
            "kind": "BLUEPRINT_REVIEW_DESCRIPTOR",
            "source_blueprint_version": current.version,
            "source_etag": current.etag,
            "source_activity_status": activity.status,
            "actor_id": actor.user_id,
            "review_request": review_request.model_dump(mode="json"),
        }
        try:
            self.repository.prepare_blueprint_review_job(
                status=queued,
                source_version=current.version,
                source_etag=current.etag,
                descriptor_output=descriptor_output,
                descriptor_component_version=PROMPT_VERSION,
                descriptor_policy_hash=self._model_policy_hash(activity),
                actor_id=actor.user_id,
                occurred_at=queued_at,
            )
        except Conflict as exc:
            code = str(exc)
            status_code = 412 if code == "ETAG_MISMATCH" else 409
            raise WorkflowError(
                code,
                "The blueprint review could not be queued from this version.",
                status_code=status_code,
            ) from exc
        if self.job_runner is None:
            raise RuntimeError("JobRunner is not configured")
        try:
            await self.job_runner.dispatch(queued.job_id)
        except Exception:
            self.repository.fail_queued_dispatch(
                job_id=queued.job_id,
                tenant_id=actor.workspace_id,
                failure=diagnostic(
                    "JOB_DISPATCH_FAILED",
                    "The durable blueprint review could not be dispatched.",
                    retryable=True,
                ),
            )
        return self.repository.job_status(queued.job_id, actor.workspace_id)

    def approve_blueprint(self, *, activity_id: str, version: int, if_match: str, actor: Actor) -> BlueprintRow:
        if actor.role not in {"OWNER", "TEACHER"}:
            raise WorkflowError("ROLE_FORBIDDEN", "Only teachers may approve blueprints", status_code=403)
        current = self.repository.blueprint_version(activity_id, version, actor.workspace_id)
        activity = cast(
            ActivityRow,
            self.repository.scoped(ActivityRow, activity_id, actor.workspace_id),
        )
        if activity.status not in {"BLUEPRINT_READY", "NEEDS_REVIEW"}:
            raise WorkflowError(
                "BLUEPRINT_APPROVAL_NOT_ALLOWED",
                "Blueprint approval is not allowed in the current activity state",
                status_code=409,
            )
        if current.etag != if_match:
            raise WorkflowError("ETAG_MISMATCH", "Blueprint has changed", status_code=412)
        blueprint = m.AssessmentBlueprint.model_validate(current.data)
        review = m.BlueprintReview.model_validate(current.review)
        if (
            blueprint.status != m.WorkflowStatus.READY
            or blueprint.approved_by is not None
            or blueprint.approved_at is not None
        ):
            raise WorkflowError(
                "BLUEPRINT_NOT_REVIEWABLE",
                "Only a server-unapproved READY blueprint may be approved",
                status_code=409,
            )
        if review.status != "READY" or review.approval_recommendation == m.BlueprintApprovalRecommendation.REJECT:
            raise WorkflowError("BLUEPRINT_REVIEW_BLOCKED", "Blueprint review does not permit approval", status_code=409)
        approved = blueprint.model_copy(
            update={
                "blueprint_version": current.version + 1,
                "status": m.WorkflowStatus.APPROVED,
                "approved_by": actor.user_id,
                "approved_at": utc_now(),
            }
        )
        copied_review = review.model_copy(update={"blueprint_version": approved.blueprint_version})
        row = self._blueprint_row(actor.workspace_id, approved, copied_review)
        try:
            self.repository.add(row)
        except IntegrityError as exc:
            raise WorkflowError(
                "BLUEPRINT_VERSION_CONFLICT",
                "Blueprint version was changed concurrently",
                status_code=409,
            ) from exc
        self.repository.set_activity_status(activity_id, actor.workspace_id, "BLUEPRINT_APPROVED")
        self.repository.audit(
            tenant_id=actor.workspace_id,
            event_type="blueprint.approved",
            aggregate_id=approved.blueprint_id,
            actor_id=actor.user_id,
            payload={"blueprint_version": approved.blueprint_version},
        )
        return row

    def evidence_view(self, submission_id: str, actor: Actor) -> list[dict[str, Any]]:
        submission = cast(SubmissionRow, self.repository.scoped(SubmissionRow, submission_id, actor.workspace_id))
        artifacts = {row.id: row for row in self.repository.artifacts_for(
            activity_id=submission.activity_id, tenant_id=actor.workspace_id, submission_id=submission_id
        )}
        views: list[dict[str, Any]] = []
        verified_artifacts: set[str] = set()
        signed_sources: dict[str, Any] = {}
        for row in self.repository.evidence_for_submission(submission_id, actor.workspace_id):
            evidence = m.EvidenceUnit.model_validate(row.data)
            artifact = artifacts.get(evidence.artifact_id)
            if artifact is None:
                raise WorkflowError("IR_PROVENANCE_GAP", "Evidence no longer resolves to the exact artifact", status_code=409)
            if artifact.id not in verified_artifacts:
                self._verified_artifact_bytes(artifact)
                verified_artifacts.add(artifact.id)
                signed_sources[artifact.id] = self.object_store.sign_get(
                    artifact.object_key
                )
            if artifact.sha256 != evidence.artifact_hash:
                raise WorkflowError("IR_PROVENANCE_GAP", "Evidence no longer resolves to the exact artifact", status_code=409)
            signed = signed_sources[artifact.id]
            views.append({
                "evidence": evidence.model_dump(mode="json"),
                "source_url": signed.url,
                "source_url_expires_at": signed.expires_at.isoformat(),
            })
        return views

    @staticmethod
    def _receipt_payload(
        *,
        assessment_row: AssessmentRow,
        actor_id: str,
        question_id: str,
        fragment_index: int,
        evidence: m.EvidenceUnit,
    ) -> dict[str, Any]:
        locator_hash = canonical_hash(evidence.locator.model_dump(mode="json"))
        receipt_id = stable_id(
            "receipt",
            assessment_row.tenant_id,
            actor_id,
            assessment_row.assessment_id,
            assessment_row.version,
            assessment_row.etag,
            question_id,
            fragment_index,
            evidence.evidence_id,
            evidence.artifact_hash,
            locator_hash,
            evidence.normalized_hash,
        )
        return {
            "receipt_id": receipt_id,
            "assessment_id": assessment_row.assessment_id,
            "assessment_version": assessment_row.version,
            "assessment_etag": assessment_row.etag,
            "question_id": question_id,
            "fragment_index": fragment_index,
            "evidence_id": evidence.evidence_id,
            "artifact_hash": evidence.artifact_hash,
            "locator_hash": locator_hash,
            "normalized_hash": evidence.normalized_hash,
        }

    def evidence_receipts(
        self, assessment_row: AssessmentRow, actor: Actor
    ) -> list[dict[str, Any]]:
        """Return only receipts valid for this exact actor and assessment version."""

        receipts: dict[str, dict[str, Any]] = {}
        for event in self.repository.audit_events(
            tenant_id=actor.workspace_id,
            event_type="evidence.viewed",
            aggregate_id=assessment_row.assessment_id,
            actor_id=actor.user_id,
        ):
            payload = dict(event.payload)
            if (
                payload.get("assessment_version") != assessment_row.version
                or payload.get("assessment_etag") != assessment_row.etag
            ):
                continue
            candidate = {
                **payload,
                "assessment_id": assessment_row.assessment_id,
                "verified_at": event.occurred_at,
            }
            try:
                receipt = dto.EvidenceReceipt.model_validate(candidate)
            except ValidationError:
                continue
            receipts[receipt.receipt_id] = receipt.model_dump(mode="json")
        return [receipts[key] for key in sorted(receipts)]

    def verify_evidence_fragment(
        self,
        *,
        assessment_id: str,
        assessment_version: int,
        assessment_etag: str,
        question_id: str,
        fragment_index: int,
        actor: Actor,
    ) -> dict[str, Any]:
        """Resolve one anchor fragment against sealed bytes, then persist a receipt."""

        current = self.repository.assessment_by_id(assessment_id, actor.workspace_id)
        if current.version != assessment_version or current.etag != assessment_etag:
            raise WorkflowError(
                "ETAG_MISMATCH", "Assessment has changed", status_code=412
            )
        assessment = m.Assessment.model_validate(current.data)
        if assessment.status != m.WorkflowStatus.NEEDS_REVIEW:
            raise WorkflowError(
                "ASSESSMENT_NOT_REVIEWABLE",
                "Evidence verification is only available during assessment review",
                status_code=409,
            )
        assessment_submission = cast(
            SubmissionRow,
            self.repository.scoped(
                SubmissionRow, assessment.submission_id, actor.workspace_id
            ),
        )
        if (
            m.SubmissionProcessingState.model_validate(
                assessment_submission.state
            ).status
            != m.SubmissionProcessingStatus.NEEDS_REVIEW
        ):
            raise WorkflowError(
                "ASSESSMENT_SUBMISSION_NOT_REVIEWABLE",
                "The submission no longer permits assessment review.",
                status_code=409,
            )
        question = next(
            (item for item in assessment.questions if item.question_id == question_id),
            None,
        )
        if question is None or fragment_index >= len(question.anchor.fragments):
            raise WorkflowError(
                "EVIDENCE_FRAGMENT_NOT_FOUND",
                "The requested evidence fragment was not found",
                status_code=404,
            )
        fragment = question.anchor.fragments[fragment_index]
        evidence_rows = {
            row.id: row
            for row in self.repository.evidence_for_submission(
                assessment.submission_id, actor.workspace_id
            )
        }
        evidence_row = evidence_rows.get(fragment.evidence_id)
        if evidence_row is None:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "The anchor no longer resolves to persisted evidence",
                status_code=409,
            )
        evidence = m.EvidenceUnit.model_validate(evidence_row.data)
        if (
            evidence.evidence_id != fragment.evidence_id
            or evidence.locator.model_dump(mode="json")
            != fragment.locator.model_dump(mode="json")
        ):
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "The anchor locator no longer matches persisted evidence",
                status_code=409,
            )
        artifact = cast(
            ArtifactRow,
            self.repository.scoped(
                ArtifactRow, evidence.artifact_id, actor.workspace_id
            ),
        )
        if (
            artifact.submission_id != assessment.submission_id
            or artifact.sha256 != evidence.artifact_hash
        ):
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "The evidence no longer resolves to the exact submission artifact",
                status_code=409,
            )
        try:
            reparsed = self._parse_bytes(
                artifact, self._verified_artifact_bytes(artifact)
            )
        except ParseRejected as exc:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "The sealed evidence could not be resolved by the safe parser",
                status_code=409,
            ) from exc
        reparsed_by_id = {unit.evidence_id: unit for unit in reparsed.evidence_units}
        exact = reparsed_by_id.get(evidence.evidence_id)
        if exact is None or any(
            (
                exact.artifact_id != evidence.artifact_id,
                exact.artifact_hash != evidence.artifact_hash,
                exact.normalized_hash != evidence.normalized_hash,
                exact.locator.model_dump(mode="json")
                != evidence.locator.model_dump(mode="json"),
            )
        ):
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "The evidence locator did not survive safe re-parsing",
                status_code=409,
            )
        payload = self._receipt_payload(
            assessment_row=current,
            actor_id=actor.user_id,
            question_id=question_id,
            fragment_index=fragment_index,
            evidence=evidence,
        )
        existing = next(
            (
                event
                for event in self.repository.audit_events(
                    tenant_id=actor.workspace_id,
                    event_type="evidence.viewed",
                    aggregate_id=assessment_id,
                    actor_id=actor.user_id,
                )
                if all(event.payload.get(key) == value for key, value in payload.items())
            ),
            None,
        )
        event = existing or self.repository.audit(
            tenant_id=actor.workspace_id,
            event_type="evidence.viewed",
            aggregate_id=assessment_id,
            actor_id=actor.user_id,
            payload=payload,
        )
        signed = self.object_store.sign_get(artifact.object_key)
        receipt = dto.EvidenceReceipt.model_validate(
            {
                **payload,
                "verified_at": event.occurred_at,
            }
        )
        return {
            "receipt": receipt.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "view_url": signed.url,
            "view_url_expires_at": signed.expires_at.isoformat(),
        }

    def _assert_evidence_receipts_complete(
        self, assessment_row: AssessmentRow, assessment: m.Assessment, actor: Actor
    ) -> None:
        actual = {
            receipt["receipt_id"]
            for receipt in self.evidence_receipts(assessment_row, actor)
        }
        expected: set[str] = set()
        evidence_by_id = {
            row.id: m.EvidenceUnit.model_validate(row.data)
            for row in self.repository.evidence_for_submission(
                assessment.submission_id, actor.workspace_id
            )
        }
        for question in assessment.questions:
            for fragment_index, fragment in enumerate(question.anchor.fragments):
                evidence = evidence_by_id.get(fragment.evidence_id)
                if evidence is None:
                    raise WorkflowError(
                        "IR_PROVENANCE_GAP",
                        "Assessment evidence is incomplete",
                        status_code=409,
                    )
                expected.add(
                    str(
                        self._receipt_payload(
                            assessment_row=assessment_row,
                            actor_id=actor.user_id,
                            question_id=question.question_id,
                            fragment_index=fragment_index,
                            evidence=evidence,
                        )["receipt_id"]
                    )
                )
        if expected != actual:
            raise WorkflowError(
                "EVIDENCE_REVIEW_REQUIRED",
                "Every source fragment must be loaded and locator-verified by the approving actor",
                status_code=409,
            )

    def assessment_view(self, submission_id: str, actor: Actor) -> dict[str, Any]:
        submission = cast(SubmissionRow, self.repository.scoped(SubmissionRow, submission_id, actor.workspace_id))
        if (
            m.SubmissionProcessingState.model_validate(submission.state).status
            == m.SubmissionProcessingStatus.CANCELLED
        ):
            raise WorkflowError(
                "ASSESSMENT_SUBMISSION_CANCELLED",
                "A cancelled submission has no reviewable assessment output.",
                status_code=409,
            )
        assessment_row = self.repository.latest_assessment(submission.id, actor.workspace_id)
        guide = self.repository.guide_for_assessment(assessment_row.assessment_id, actor.workspace_id)
        reviews = self.repository.review_rows(submission.id, actor.workspace_id)
        review_items: list[dict[str, Any]] = []
        for row in reviews:
            result = m.QuestionReviewResult.model_validate(row.data)
            if result.review is None:
                continue
            review_items.append(
                {
                    **result.review.model_dump(mode="json"),
                    "question_id": row.question_id,
                    "opportunity_id": result.opportunity_id,
                }
            )
        return {
            "assessment": assessment_row.data,
            "assessment_version": assessment_row.version,
            "etag": assessment_row.etag,
            "guide": guide.data,
            "reviews": review_items,
            "evidence_receipts": self.evidence_receipts(assessment_row, actor),
        }

    def approve_assessment(self, *, assessment_id: str, if_match: str, actor: Actor) -> AssessmentRow:
        if not actor.can_approve_assessments:
            raise WorkflowError("ROLE_FORBIDDEN", "Actor cannot approve assessments", status_code=403)
        current = self.repository.assessment_by_id(assessment_id, actor.workspace_id)
        if current.etag != if_match:
            raise WorkflowError("ETAG_MISMATCH", "Assessment has changed", status_code=412)
        assessment = m.Assessment.model_validate(current.data)
        if assessment.status != m.WorkflowStatus.NEEDS_REVIEW:
            raise WorkflowError("ASSESSMENT_NOT_REVIEWABLE", "Assessment is not awaiting review", status_code=409)
        submission = cast(
            SubmissionRow,
            self.repository.scoped(
                SubmissionRow, assessment.submission_id, actor.workspace_id
            ),
        )
        if (
            m.SubmissionProcessingState.model_validate(submission.state).status
            != m.SubmissionProcessingStatus.NEEDS_REVIEW
        ):
            raise WorkflowError(
                "ASSESSMENT_SUBMISSION_NOT_REVIEWABLE",
                "The submission no longer permits assessment approval.",
                status_code=409,
            )
        guide = m.EvaluationGuide.model_validate(
            self.repository.guide_for_assessment(
                assessment_id, actor.workspace_id
            ).data
        )
        if guide.status != "READY":
            raise WorkflowError(
                "GUIDE_NOT_READY",
                "Assessment cannot be approved without a complete READY guide",
                status_code=409,
            )
        # Approval is blocked unless every anchor still resolves byte-for-byte.
        self.evidence_view(assessment.submission_id, actor)
        self._assert_evidence_receipts_complete(current, assessment, actor)
        approved = assessment.model_copy(
            update={
                "status": m.WorkflowStatus.APPROVED,
                "approved_by": actor.user_id,
                "approved_at": utc_now(),
            }
        )
        version = current.version + 1
        row = AssessmentRow(
            row_id=stable_id("assessmentrow", assessment_id, version),
            assessment_id=assessment_id,
            tenant_id=actor.workspace_id,
            submission_id=assessment.submission_id,
            version=version,
            status=approved.status.value,
            etag=_etag(approved),
            data=approved.model_dump(mode="json"),
        )
        try:
            row = self.repository.approve_assessment_atomic(
                expected_etag=if_match,
                approved_row=row,
                actor_id=actor.user_id,
            )
        except Conflict as exc:
            code = str(exc)
            status_code = 412 if code == "ETAG_MISMATCH" else 409
            raise WorkflowError(
                code if code.isupper() else "ASSESSMENT_VERSION_CONFLICT",
                "Assessment approval state changed concurrently.",
                status_code=status_code,
            ) from exc
        return row

    def create_export(self, assessment_id: str, actor: Actor) -> ExportRow:
        assessment_row = self.repository.assessment_by_id(assessment_id, actor.workspace_id)
        assessment = m.Assessment.model_validate(assessment_row.data)
        if (
            assessment.status != m.WorkflowStatus.APPROVED
            or not assessment.approved_by
            or assessment.approved_at is None
            or not self.repository.has_audit_event(
                tenant_id=actor.workspace_id,
                event_type="assessment.approved",
                aggregate_id=assessment_id,
                payload_contains={"assessment_version": assessment_row.version},
            )
        ):
            raise WorkflowError("HUMAN_APPROVAL_REQUIRED", "Export requires human approval", status_code=409)
        guide_row = self.repository.guide_for_assessment(assessment_id, actor.workspace_id)
        guide = m.EvaluationGuide.model_validate(guide_row.data)
        if guide.status != "READY":
            raise WorkflowError(
                "GUIDE_NOT_READY", "Export requires a complete READY guide", status_code=409
            )
        export_id = stable_id("export", assessment_id, assessment_row.version, canonical_hash(guide))
        try:
            return cast(ExportRow, self.repository.scoped(ExportRow, export_id, actor.workspace_id))
        except NotFound:
            pass
        with TemporaryDirectory(prefix="cva-export-") as temp_dir:
            rendered = render_views(assessment, guide, Path(temp_dir))
            canonical_bundle = Path(temp_dir) / "canonical.json"
            canonical_bundle.write_text(
                __import__("json").dumps(
                    {
                        "schema_version": assessment.schema_version,
                        "assessment": assessment.model_dump(mode="json"),
                        "evaluation_guide": guide.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            sources = {
                "assessment_pdf": rendered.assessment_pdf,
                "guide_pdf": rendered.guide_pdf,
                "canonical_json": canonical_bundle,
            }
            artifacts: dict[str, Any] = {}
            for kind, path in sources.items():
                object_key = f"exports/{actor.workspace_id}/{assessment_id}/{export_id}/{path.name}"
                data = path.read_bytes()
                self._store_export_bytes(object_key, data, "application/pdf" if kind.endswith("pdf") else "application/json")
                artifacts[kind] = {
                    "object_key": object_key,
                    "sha256": sha256_bytes(data),
                    "byte_size": len(data),
                }
        row = ExportRow(
            id=export_id,
            tenant_id=actor.workspace_id,
            assessment_id=assessment_id,
            status="READY",
            artifacts=artifacts,
        )
        try:
            self.repository.add(row)
        except IntegrityError:
            return cast(
                ExportRow,
                self.repository.scoped(ExportRow, export_id, actor.workspace_id),
            )
        return row

    def export_artifact(self, row: ExportRow, kind: str) -> dict[str, Any]:
        """Issue a fresh download URL without ever persisting that capability."""

        if kind not in row.artifacts:
            raise WorkflowError("EXPORT_KIND_INVALID", "Export kind is not available")
        stored = dict(row.artifacts[kind])
        signed = self.object_store.sign_get(str(stored["object_key"]))
        return {
            **stored,
            "url": signed.url,
            "expires_at": signed.expires_at.isoformat(),
        }

    def _store_export_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.object_store.put_immutable(key, data, content_type)

    def _verified_artifact_bytes(self, artifact: ArtifactRow) -> bytes:
        if (
            artifact.status != "COMPLETE"
            or artifact.byte_size is None
            or artifact.sha256 is None
            or artifact.media_type is None
        ):
            raise WorkflowError("UPLOAD_INCOMPLETE", "Artifact is not complete")
        if artifact.byte_size > self.settings.max_upload_bytes:
            raise WorkflowError("IR_PROVENANCE_GAP", "Sealed artifact size is invalid", status_code=409)
        try:
            metadata = self.object_store.head(artifact.object_key)
        except KeyError as exc:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "Sealed artifact is missing",
                status_code=409,
            ) from exc
        if (
            metadata.byte_size != artifact.byte_size
            or metadata.content_type != artifact.media_type
        ):
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "Sealed artifact metadata changed",
                status_code=409,
            )
        try:
            data = self.object_store.get_bytes(
                artifact.object_key, max_bytes=artifact.byte_size
            )
        except (KeyError, ObjectSizeExceeded) as exc:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "Sealed artifact cannot be read safely",
                status_code=409,
            ) from exc
        if len(data) != artifact.byte_size or sha256_bytes(data) != artifact.sha256:
            raise WorkflowError(
                "IR_PROVENANCE_GAP",
                "Sealed artifact hash changed",
                status_code=409,
            )
        return data

    @staticmethod
    def _sealed_object_key(artifact: ArtifactRow, digest: str) -> str:
        value = digest.removeprefix("sha256:")
        return (
            f"raw/{artifact.tenant_id}/{artifact.activity_id}/{artifact.id}/"
            f"sealed/{value}"
        )

    @staticmethod
    def _assert_completion_claims(
        artifact: ArtifactRow,
        *,
        claimed_sha256: str | None,
        claimed_byte_size: int | None,
        claimed_media_type: str | None,
    ) -> None:
        if (
            (claimed_sha256 is not None and claimed_sha256 != artifact.sha256)
            or (
                claimed_byte_size is not None
                and claimed_byte_size != artifact.byte_size
            )
            or (
                claimed_media_type is not None
                and claimed_media_type != artifact.media_type
            )
        ):
            raise WorkflowError(
                "UPLOAD_COMPLETION_MISMATCH",
                "Completion metadata does not match the object",
            )

    def _parse_bytes(self, artifact: ArtifactRow, data: bytes) -> ParsedArtifact:
        suffix = Path(artifact.filename).suffix[:12]
        with TemporaryDirectory(prefix="cva-parse-") as temp_dir:
            path = Path(temp_dir) / f"{artifact.id}{suffix}"
            path.write_bytes(data)
            if self.settings.environment == "cloud":
                parsed = parse_in_subprocess(
                    path,
                    parser=self.parser,
                    tenant_id=artifact.tenant_id,
                    source_role=m.ArtifactRole(artifact.role),
                    submission_id=artifact.submission_id,
                    declared_media_type=artifact.declared_media_type,
                    timeout_seconds=self.settings.parser_timeout_seconds,
                    require_isolation=True,
                )
            else:
                parsed = self.parser.parse(
                    path,
                    tenant_id=artifact.tenant_id,
                    source_role=m.ArtifactRole(artifact.role),
                    submission_id=artifact.submission_id,
                    declared_media_type=artifact.declared_media_type,
                )
        # The parser's offline content ID is intentionally deterministic.  At
        # the web boundary, however, the durable upload row is authoritative.
        # Normalize every provenance reference before persistence or inference.
        id_map = {
            unit.evidence_id: stable_id(
                "ev",
                artifact.tenant_id,
                artifact.submission_id or artifact.role,
                artifact.id,
                unit.artifact_hash,
                unit.locator.model_dump(mode="json"),
                unit.normalized_hash,
            )
            for unit in parsed.evidence_units
        }
        evidence_units = tuple(
            unit.model_copy(
                update={
                    "evidence_id": id_map[unit.evidence_id],
                    "artifact_id": artifact.id,
                    "relations": [
                        relation.model_copy(
                            update={
                                "target_evidence_id": id_map.get(
                                    relation.target_evidence_id,
                                    relation.target_evidence_id,
                                )
                            }
                        )
                        for relation in unit.relations
                    ],
                }
            )
            for unit in parsed.evidence_units
        )
        return ParsedArtifact(
            artifact=parsed.artifact.model_copy(
                update={"artifact_id": artifact.id, "filename": artifact.filename}
            ),
            evidence_units=evidence_units,
        )

    @staticmethod
    def _artifact_ref(row: ArtifactRow) -> m.ArtifactRef:
        if not row.sha256 or row.byte_size is None or not row.media_type:
            raise WorkflowError("UPLOAD_INCOMPLETE", "Artifact is not complete")
        return m.ArtifactRef(
            artifact_id=row.id,
            role=m.ArtifactRole(row.role),
            filename=row.filename,
            media_type=row.media_type,
            sha256=row.sha256,
            byte_size=row.byte_size,
            parser_id="safe-parser",
            parser_version=PARSER_VERSION,
        )

    @staticmethod
    def _new_job(tenant_id: str, aggregate_id: str, kind: str, stage: str) -> m.JobStatus:
        return m.JobStatus(
            job_id=stable_id("job", tenant_id, aggregate_id, kind, utc_now()),
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            stage=stage,
            status="QUEUED",
            progress=0.0,
            attempt=0,
            diagnostics=[],
        )

    def _gateway(self, job_id: str) -> ModelGateway:
        if self.gateway_factory is not None:
            return self.gateway_factory(job_id)
        return ModelGateway(
            GatewayConfig(
                mode=GatewayMode(self.settings.model_mode),
                job_id=job_id,
                timeout_seconds=10.0,
                max_retries=2,
                default_budget_usd=0.25,
            ),
            ledger_sink=self.repository.model_call_sink,
        )

    def _remaining_model_budget_usd(self, job_id: str, tenant_id: str) -> float:
        spent = sum(
            max(
                float(item.get("estimated_cost_usd") or 0.0),
                float(item.get("actual_cost_usd") or 0.0),
            )
            for item in self.repository.model_calls(
                tenant_id=tenant_id,
                job_id=job_id,
            )
        )
        return max(0.0, self.settings.max_job_cost_usd - spent)

    async def _gateway_stage(
        self, job: JobRow, prompt_id: str, request: BaseModel, output_model: type[T], *, cache_suffix: str = ""
    ) -> T:
        self._cancellation_checkpoint(job)
        stage = f"{prompt_id}:{cache_suffix}" if cache_suffix else prompt_id
        inputs = request.model_dump(mode="json")
        policy_hash = self._stage_policy_hash(job)
        cached = self.repository.stage_by_key(
            tenant_id=job.tenant_id,
            stage=stage,
            inputs=inputs,
            policy_hash=policy_hash,
            component_version=PROMPT_VERSION,
        )
        if cached is not None and cached.output is not None:
            self._record_stage_reuse(job, cached)
            output = output_model.model_validate(cached.output)
            self._cancellation_checkpoint(job)
            return output
        self._assert_resume_may_execute(job, prompt_id)
        try:
            trusted = build_trusted_context(request).model_copy(
                update={"tenant_id": job.tenant_id}
            )
            result = await self._gateway(job.id).invoke(
                prompt_id,
                request,
                trusted,
                budget=CallBudget(
                    max_cost_usd=self._remaining_model_budget_usd(
                        job.id, job.tenant_id
                    )
                ),
            )
            self._cancellation_checkpoint(job)
            output = output_model.model_validate(
                result.output.model_dump(mode="json")
            )
        except _CooperativeJobCancellation:
            raise
        except Exception as exc:
            if self._complete_cancellation_if_requested(job):
                raise _CooperativeJobCancellation from None
            self._record_failed_stage(
                job=job,
                stage=stage,
                inputs=inputs,
                policy_hash=policy_hash,
                exc=exc,
            )
            raise
        self.repository.save_stage(
            job_id=job.id,
            tenant_id=job.tenant_id,
            stage=stage,
            inputs=inputs,
            component_version=PROMPT_VERSION,
            policy_hash=policy_hash,
            output=output.model_dump(mode="json"),
        )
        self._cancellation_checkpoint(job)
        return output

    def _resume_order(self, job: JobRow) -> dict[str, int]:
        if job.kind == "ACTIVITY":
            return _ACTIVITY_RESUME_ORDER
        if job.kind == "BLUEPRINT_REVIEW":
            return _BLUEPRINT_REVIEW_RESUME_ORDER
        if job.kind == "SUBMISSION":
            return _SUBMISSION_RESUME_ORDER
        if job.kind == "QUESTION_ACTION":
            return _SUBMISSION_RESUME_ORDER
        return {}

    def _mark_resume_floor(self, job: JobRow, application_stage: str) -> None:
        floor = job.resume_from_stage
        if floor is None:
            return
        order = self._resume_order(job)
        if floor not in order:
            raise WorkflowError(
                "STAGE_RESUME_TARGET_INVALID",
                "The durable resume target is not part of this pipeline.",
                status_code=409,
            )
        if order.get(application_stage, -1) >= order[floor]:
            self._resume_floor_reached.add(job.id)

    def _assert_application_stage_may_execute(
        self, job: JobRow, application_stage: str
    ) -> None:
        floor = job.resume_from_stage
        if floor is None or job.id in self._resume_floor_reached:
            return
        order = self._resume_order(job)
        if floor not in order or application_stage not in order:
            raise WorkflowError(
                "STAGE_RESUME_TARGET_INVALID",
                "The durable resume target is not part of this pipeline.",
                status_code=409,
            )
        if order[application_stage] < order[floor]:
            raise WorkflowError(
                "STAGE_RESUME_REUSE_MISSING",
                "A prerequisite application stage has no verified reusable output.",
                status_code=409,
            )
        self._resume_floor_reached.add(job.id)

    def _record_stage_reuse(self, job: JobRow, cached: StageRunRow) -> None:
        if job.resume_from_stage is None:
            return
        if self.repository.has_audit_event(
            tenant_id=job.tenant_id,
            event_type="stage.reused",
            aggregate_id=job.id,
            payload_contains={"stage_run_id": cached.id},
        ):
            return
        self.repository.audit(
            tenant_id=job.tenant_id,
            event_type="stage.reused",
            aggregate_id=job.id,
            actor_id="system_worker",
            payload={
                "stage_run_id": cached.id,
                "source_job_id": cached.job_id,
                "stage": cached.stage,
                "stage_key": cached.stage_key,
                "input_hash": cached.input_hash,
                "policy_hash": cached.policy_hash,
                "component_version": cached.component_version,
                "output_hash": cached.output_hash,
            },
        )

    def _assert_resume_may_execute(self, job: JobRow, prompt_id: str) -> None:
        floor = job.resume_from_stage
        if floor is None or job.id in self._resume_floor_reached:
            return
        order = self._resume_order(job)
        application_stage = _PROMPT_APPLICATION_STAGE.get(prompt_id)
        if floor not in order or application_stage not in order:
            raise WorkflowError(
                "STAGE_RESUME_TARGET_INVALID",
                "The durable resume target is not part of this pipeline.",
                status_code=409,
            )
        if order[application_stage] < order[floor]:
            raise WorkflowError(
                "STAGE_RESUME_REUSE_MISSING",
                "A prerequisite stage cannot be re-executed because its verified reusable output is missing.",
                status_code=409,
            )
        self._resume_floor_reached.add(job.id)

    def _model_policy_hash(self, activity: ActivityRow) -> str:
        return canonical_hash(
            {
                "blueprint_policy": activity.blueprint_policy,
                "model_mode": getattr(
                    self.settings,
                    "worker_model_mode",
                    self.settings.model_mode,
                ),
                "p10_enabled": False,
            }
        )

    def _stage_policy_hash(self, job: JobRow) -> str:
        if job.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
            activity = cast(
                ActivityRow,
                self.repository.scoped(ActivityRow, job.aggregate_id, job.tenant_id),
            )
        else:
            submission = cast(
                SubmissionRow,
                self.repository.scoped(SubmissionRow, job.aggregate_id, job.tenant_id),
            )
            activity = cast(
                ActivityRow,
                self.repository.scoped(
                    ActivityRow, submission.activity_id, job.tenant_id
                ),
            )
        return self._model_policy_hash(activity)

    @staticmethod
    def _blueprint_row(tenant_id: str, blueprint: m.AssessmentBlueprint, review: m.BlueprintReview) -> BlueprintRow:
        data = blueprint.model_dump(mode="json")
        return BlueprintRow(
            row_id=stable_id("blueprintrow", blueprint.activity_id, blueprint.blueprint_version),
            tenant_id=tenant_id,
            activity_id=blueprint.activity_id,
            blueprint_id=blueprint.blueprint_id,
            version=blueprint.blueprint_version,
            status=blueprint.status.value,
            etag=_etag(data),
            data=data,
            review=review.model_dump(mode="json"),
        )

    @staticmethod
    def _caused_by(exc: BaseException, expected: type[BaseException]) -> bool:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            if isinstance(current, expected):
                return True
            visited.add(id(current))
            current = current.__cause__ or current.__context__
        return False

    @classmethod
    def _classify_failure(
        cls, exc: BaseException
    ) -> tuple[m.FailureClass, bool, str]:
        """Map runtime failures to stable, content-free operational classes."""

        code = str(getattr(exc, "code", "TECHNICAL_FAILURE"))
        if isinstance(exc, Conflict):
            conflict_code = str(exc)
            if conflict_code in _PRECONDITION_FAILURE_CODES:
                code = conflict_code
        if isinstance(exc, (GatewaySafetyBlock, GatewayContextError)):
            return m.FailureClass.SECURITY, False, code
        if code in _SECURITY_FAILURE_CODES:
            return m.FailureClass.SECURITY, False, code
        if isinstance(exc, ParseRejected):
            return m.FailureClass.VALIDATION, False, code
        if isinstance(exc, (ContextValidationError, ValidationError)):
            return m.FailureClass.VALIDATION, False, code
        if isinstance(exc, (WorkflowError, Conflict)) and code in _PRECONDITION_FAILURE_CODES:
            return m.FailureClass.PRECONDITION, False, code
        if isinstance(exc, GatewayTimeout):
            return m.FailureClass.TRANSIENT, True, code
        if isinstance(exc, GatewayProviderError):
            if cls._caused_by(exc, TransientProviderError):
                return m.FailureClass.PROVIDER, True, code
            return m.FailureClass.PERMANENT, False, code
        if isinstance(exc, (OperationalError, TimeoutError, ConnectionError)):
            return m.FailureClass.TRANSIENT, True, "TRANSIENT_RUNTIME_FAILURE"
        return m.FailureClass.PERMANENT, False, code

    def _complete_cancellation_if_requested(self, job: JobRow) -> bool:
        control = self.repository.job_control(job.id, job.tenant_id)
        if control.control_state == "ACTIVE":
            return False
        if control.control_state == "CANCEL_REQUESTED":
            self.repository.complete_job_cancellation(
                job_id=job.id,
                tenant_id=job.tenant_id,
            )
        return True

    def _cancellation_checkpoint(self, job: JobRow) -> None:
        if self._complete_cancellation_if_requested(job):
            raise _CooperativeJobCancellation

    def _record_failed_stage(
        self,
        *,
        job: JobRow,
        stage: str,
        inputs: dict[str, Any],
        policy_hash: str,
        exc: BaseException,
    ) -> None:
        failure_class, retryable, code = self._classify_failure(exc)
        failure = diagnostic(
            code,
            "The application stage failed without persisting provider or input detail.",
            retryable=retryable,
        )
        row, reused = self.repository.save_stage(
            job_id=job.id,
            tenant_id=job.tenant_id,
            stage=stage,
            inputs=inputs,
            component_version=PROMPT_VERSION,
            policy_hash=policy_hash,
            output=None,
            status="FAILED",
            diagnostics=[failure.model_dump(mode="json")],
            failure_class=failure_class.value,
        )
        if reused:
            return
        # Repository compatibility: E1's save helper hashes every output,
        # including None.  A failed StageRun must not expose an output hash.
        with self.repository.session() as session:
            persisted = session.get(StageRunRow, row.id)
            if persisted is not None and persisted.status == "FAILED":
                persisted.output = None
                persisted.output_hash = None

    def _set_job(self, job: JobRow, stage: str, progress: float) -> None:
        self._cancellation_checkpoint(job)
        self._mark_resume_floor(job, stage)
        status = self.repository.job_status(job.id, job.tenant_id).model_copy(
            update={"stage": stage, "status": "RUNNING", "progress": progress, "started_at": utc_now()}
        )
        self.repository.save_job_status(status)
        self._cancellation_checkpoint(job)

    def _complete_job(self, job: JobRow, stage: str) -> None:
        self._cancellation_checkpoint(job)
        status = self.repository.job_status(job.id, job.tenant_id).model_copy(
            update={"stage": stage, "status": "SUCCEEDED", "progress": 1.0, "finished_at": utc_now()}
        )
        try:
            self.repository.save_job_status(status)
        except Conflict as exc:
            if str(exc) != "JOB_CANCEL_REQUESTED":
                raise
            self._cancellation_checkpoint(job)
            raise

    def _needs_review_job(
        self,
        job: JobRow,
        code: str,
        diagnostics: list[m.Diagnostic] | None = None,
    ) -> None:
        self._cancellation_checkpoint(job)
        status = self.repository.job_status(job.id, job.tenant_id).model_copy(
            update={
                "status": "NEEDS_REVIEW",
                "progress": 1.0,
                "finished_at": utc_now(),
                "diagnostics": diagnostics
                or [diagnostic(code, "The workflow requires a human decision.")],
            }
        )
        self.repository.save_job_status(status)
        self._cancellation_checkpoint(job)

    def _stop_activity_output(
        self,
        activity: ActivityRow,
        job: JobRow,
        output_status: str,
        diagnostics: list[m.Diagnostic],
    ) -> None:
        if output_status in {
            m.WorkflowStatus.BLOCKED.value,
            m.WorkflowStatus.NEEDS_REVIEW.value,
        }:
            self.repository.set_activity_status(
                activity.id, job.tenant_id, "NEEDS_REVIEW"
            )
            self._needs_review_job(
                job,
                output_status,
                diagnostics
                or [
                    diagnostic(
                        output_status,
                        "La etapa requiere una decisión docente antes de continuar.",
                    )
                ],
            )
            return
        self._fail_job(
            job,
            output_status,
            "The activity pipeline stopped at a validated fail-closed boundary.",
        )

    def _fail_job(
        self,
        job: JobRow,
        code: str,
        message: str,
        *,
        failure_class: m.FailureClass = m.FailureClass.PERMANENT,
        retryable: bool = False,
    ) -> None:
        if self._complete_cancellation_if_requested(job):
            return
        failure = diagnostic(code, message, retryable=retryable)
        status = self.repository.job_status(job.id, job.tenant_id).model_copy(
            update={
                "status": "FAILED",
                "finished_at": utc_now(),
                "diagnostics": [failure],
            }
        )
        self.repository.save_job_status(status)
        if self._complete_cancellation_if_requested(job):
            return
        with self.repository.session() as session:
            persisted = session.get(JobRow, job.id)
            if persisted is None or persisted.tenant_id != job.tenant_id:
                raise NotFound("job not found")
            persisted.failure_class = failure_class.value
            persisted.next_attempt_at = None
        if job.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
            self.repository.set_activity_status(job.aggregate_id, job.tenant_id, "TECHNICAL_FAILURE")
        elif job.kind == "SUBMISSION":
            submission = cast(
                SubmissionRow,
                self.repository.scoped(SubmissionRow, job.aggregate_id, job.tenant_id),
            )
            self.repository.set_submission_state(
                m.SubmissionProcessingState(
                    submission_id=submission.id,
                    activity_id=submission.activity_id,
                    status=m.SubmissionProcessingStatus.TECHNICAL_FAILURE,
                    current_stage=status.stage,
                    progress=status.progress,
                    active_job_id=job.id,
                    diagnostics=[failure],
                    updated_at=utc_now(),
                )
            )

    def _set_submission(
        self, submission: SubmissionRow, job: JobRow, domain_status: m.SubmissionProcessingStatus,
        stage: str, progress: float
    ) -> None:
        self._set_job(job, stage, progress)
        self._cancellation_checkpoint(job)
        self.repository.set_submission_state(
            m.SubmissionProcessingState(
                submission_id=submission.id,
                activity_id=submission.activity_id,
                status=domain_status,
                current_stage=stage,
                progress=progress,
                active_job_id=job.id,
                diagnostics=[],
                updated_at=utc_now(),
            )
        )
        self._cancellation_checkpoint(job)

    def _terminal_domain_failure(
        self,
        submission: SubmissionRow,
        job: JobRow,
        status: str,
        diagnostics: list[m.Diagnostic],
        *,
        stage: str = "ASSESSMENT_PLAN",
    ) -> None:
        self._cancellation_checkpoint(job)
        self.repository.set_submission_state(
            m.SubmissionProcessingState(
                submission_id=submission.id,
                activity_id=submission.activity_id,
                status=m.SubmissionProcessingStatus(status),
                current_stage=stage,
                progress=1.0,
                active_job_id=job.id,
                diagnostics=diagnostics,
                updated_at=utc_now(),
            )
        )
        job_status = self.repository.job_status(job.id, job.tenant_id).model_copy(
            update={"status": "NEEDS_REVIEW", "progress": 1.0, "diagnostics": diagnostics, "finished_at": utc_now()}
        )
        self.repository.save_job_status(job_status)
        self._cancellation_checkpoint(job)

    def _assemble_assessment(
        self, *, activity: ActivityRow, submission: SubmissionRow,
        blueprint: m.AssessmentBlueprint, plan: m.AssessmentPlan,
        mapping: m.EvidenceMapPatch, questions: list[m.SelectedQuestion],
        artifact: ArtifactRow, job: JobRow,
    ) -> m.Assessment:
        required = [question.question_id for question in questions if question.student_justification_required]
        mode = blueprint.assessment_constraints.structured_justification_policy.mode
        opportunity_by_dimension: dict[str, list[m.QuestionOpportunity]] = {}
        for opportunity in mapping.opportunities:
            opportunity_by_dimension.setdefault(opportunity.dimension_id, []).append(opportunity)
        coverage = [
            m.CoverageItem(
                dimension_id=dimension.dimension_id,
                available_variant_count=len(dimension.evidence_variants),
                available_opportunity_count=len(opportunity_by_dimension.get(dimension.dimension_id, [])),
                selected_opportunity_count=sum(q.dimension_id == dimension.dimension_id for q in questions),
                reused_variant_count=0,
                evidence_unit_count=len({eid for o in opportunity_by_dimension.get(dimension.dimension_id, []) for eid in o.evidence_ids}),
                diagnostics=[],
            )
            for dimension in blueprint.dimensions
        ]
        ledgers = [
            ledger
            for lineage_job_id in self._job_lineage_ids(job)
            for ledger in self.repository.model_calls(
                tenant_id=job.tenant_id, job_id=lineage_job_id
            )
            # Assessment assembly is the input to P09.  A later resume must
            # reconstruct that same pre-P09 snapshot rather than feeding the
            # guide call back into its own lineage and changing input_hash.
            if ledger.get("prompt_id") != "P09_GUIDE_BUILD_V1"
        ]
        snapshots = {
            item["prompt_id"]: item["route"]["model_snapshot"]
            for item in ledgers
        }
        prompt_hashes = [
            row.sha256
            for row in self.repository.artifacts_for(
                activity_id=activity.id, tenant_id=job.tenant_id, submission_id=None
            )
            if row.role == m.ArtifactRole.ASSIGNMENT_PROMPT.value and row.sha256
        ]
        rubric_hashes = [
            row.sha256
            for row in self.repository.artifacts_for(
                activity_id=activity.id, tenant_id=job.tenant_id, submission_id=None
            )
            if row.role == m.ArtifactRole.RUBRIC.value and row.sha256
        ]
        assessment_id = stable_id("assessment", submission.id, plan.plan_id, [q.source_candidate_id for q in questions])
        return m.Assessment(
            assessment_id=assessment_id,
            tenant_id=job.tenant_id,
            activity_id=activity.id,
            submission_id=submission.id,
            subject_ref=submission.subject_ref,
            status=m.WorkflowStatus.NEEDS_REVIEW,
            context_mode=m.ContextMode.CLOSED,
            assessment_plan_id=plan.plan_id,
            question_count=plan.question_count,
            questions=questions,
            coverage=coverage,
            structured_justification=m.StructuredJustificationSummary(
                mode=mode,
                required_question_ids=required,
                limited_evidence_notice_required=mode != m.StructuredJustificationMode.ALL,
            ),
            diagnostics=[],
            lineage=m.Lineage(
                assignment_prompt_hashes=prompt_hashes,
                rubric_hashes=rubric_hashes,
                submission_hashes=[cast(str, artifact.sha256)],
                blueprint_id=blueprint.blueprint_id,
                blueprint_version=blueprint.blueprint_version,
                parser_versions={artifact.media_type or "unknown": PARSER_VERSION},
                prompt_versions={key: PROMPT_VERSION for key in snapshots},
                model_snapshots=snapshots,
                policy_hash=canonical_hash(activity.blueprint_policy),
                planner_version=PLANNER_VERSION,
                renderer_version=RENDERER_VERSION,
            ),
            created_at=(
                submission.created_at.replace(tzinfo=UTC)
                if submission.created_at.tzinfo is None
                else submission.created_at.astimezone(UTC)
            ),
        )

    def _job_lineage_ids(self, job: JobRow) -> list[str]:
        """Return source-to-current job ids for a retry/resume chain."""

        lineage = [job.id]
        seen = {job.id}
        current = job.id
        while True:
            records = self.repository.job_control_records(
                tenant_id=job.tenant_id,
                resulting_job_id=current,
            )
            source = next(
                (
                    record.job_id
                    for record in records
                    if record.action in {"RETRY", "RESUME"}
                    and record.status == "APPLIED"
                ),
                None,
            )
            if source is None or source in seen:
                break
            lineage.append(source)
            seen.add(source)
            current = source
        lineage.reverse()
        return lineage
