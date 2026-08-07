"""Strict HTTP transport models for the private Stage 1 API.

Domain roots are always composed from the canonical contracts.  The models in
this module only describe HTTP commands, resource metadata and response
envelopes; they do not redefine persisted domain objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, model_validator

from ..contracts import models as m


ShortText = Annotated[str, Field(min_length=1, max_length=300)]
Etag = Annotated[str, Field(min_length=10, max_length=128)]


class EmptyCommand(m.StrictModel):
    """Explicit empty JSON command used by mutation endpoints."""


class HealthResource(m.StrictModel):
    status: Literal["ok"]
    stage: Literal["1"]
    model_mode: Literal["mock", "real"]


class ReadinessResource(m.StrictModel):
    status: Literal["ready", "not_ready"]


class SessionResource(m.StrictModel):
    user_id: m.PrincipalId
    email: Annotated[str, Field(min_length=3, max_length=320)]
    workspace_id: m.Id
    workspace_name: ShortText
    roles: Annotated[list[str], Field(min_length=1, max_length=10)]


class SessionEnvelope(m.StrictModel):
    session: SessionResource


class LoginCommand(m.StrictModel):
    email: Annotated[
        str,
        Field(
            min_length=3,
            max_length=320,
            pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
        ),
    ]


class ActivityCreateCommand(m.StrictModel):
    title: ShortText
    output_language: Annotated[str, Field(min_length=2, max_length=35)] = "es-CL"
    assessment_modality: m.AssessmentModality = m.AssessmentModality.WRITTEN
    question_count: Annotated[StrictInt, Field(ge=1, le=20)] = 5
    target_total_minutes: Annotated[StrictInt, Field(ge=3, le=120)] = 15
    structured_justification_mode: m.StructuredJustificationMode = (
        m.StructuredJustificationMode.NOT_REQUIRED
    )
    priority_criterion_ids: list[m.Id] = Field(default_factory=list, max_length=100)
    allowed_response_formats: Annotated[
        list[m.ResponseFormat], Field(min_length=1, max_length=20)
    ]
    allowed_artifact_media_types: Annotated[
        list[str], Field(default_factory=list, max_length=50)
    ]
    adaptation_policy_id: m.Id | None = None

    @model_validator(mode="after")
    def formats_are_unique(self) -> "ActivityCreateCommand":
        if len(self.allowed_response_formats) != len(set(self.allowed_response_formats)):
            raise ValueError("allowed_response_formats must be unique")
        return self


class ActivityUpdateCommand(m.StrictModel):
    title: ShortText | None = None
    output_language: Annotated[str, Field(min_length=2, max_length=35)] | None = None
    assessment_modality: m.AssessmentModality | None = None
    question_count: Annotated[StrictInt, Field(ge=1, le=20)] | None = None
    target_total_minutes: Annotated[StrictInt, Field(ge=3, le=120)] | None = None
    structured_justification_mode: m.StructuredJustificationMode | None = None
    priority_criterion_ids: list[m.Id] | None = Field(default=None, max_length=100)
    allowed_response_formats: Annotated[
        list[m.ResponseFormat], Field(min_length=1, max_length=20)
    ] | None = None
    allowed_artifact_media_types: Annotated[
        list[str], Field(min_length=1, max_length=50)
    ] | None = None
    adaptation_policy_id: m.Id | None = None

    @model_validator(mode="after")
    def command_is_non_empty_and_unique(self) -> "ActivityUpdateCommand":
        changed = self.model_fields_set
        if not changed:
            raise ValueError("activity update must include at least one field")
        if (
            self.allowed_response_formats is not None
            and len(self.allowed_response_formats)
            != len(set(self.allowed_response_formats))
        ):
            raise ValueError("allowed_response_formats must be unique")
        return self


class JourneyBlueprintSummary(m.StrictModel):
    version: int = Field(ge=1)
    status: str
    etag: Etag


class JourneySubmissionSummary(m.StrictModel):
    submission_id: m.Id
    status: m.SubmissionProcessingStatus
    active_job_id: m.Id | None = None


class JourneyJobSummary(m.StrictModel):
    job_id: m.Id
    stage: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "NEEDS_REVIEW"]
    progress: float = Field(ge=0.0, le=1.0)


class JourneyAssessmentSummary(m.StrictModel):
    assessment_id: m.Id
    version: int = Field(ge=1)
    status: m.WorkflowStatus
    etag: Etag


class ActivityJourney(m.StrictModel):
    continue_path: Annotated[str, Field(min_length=1, max_length=500)]
    next_action: Literal[
        "EDIT_ACTIVITY",
        "REVIEW_BLUEPRINT",
        "UPLOAD_SUBMISSION",
        "RUN_SUBMISSION",
        "VIEW_PROGRESS",
        "REVIEW_ASSESSMENT",
    ]
    blueprint: JourneyBlueprintSummary | None = None
    submission: JourneySubmissionSummary | None = None
    job: JourneyJobSummary | None = None
    assessment: JourneyAssessmentSummary | None = None


class ActivityResource(m.ActivityConfig):
    status: str
    created_at: datetime
    updated_at: datetime
    latest_blueprint_version: int | None = Field(default=None, ge=1)
    approved_blueprint_version: int | None = Field(default=None, ge=1)
    submission_id: m.Id | None = None
    journey: ActivityJourney


class ActivityEnvelope(m.StrictModel):
    activity: ActivityResource


class ActivityListEnvelope(m.StrictModel):
    items: list[ActivityResource]


class ArtifactResource(m.StrictModel):
    artifact_id: m.Id
    activity_id: m.Id
    submission_id: m.Id | None = None
    role: m.ArtifactRole
    filename: Annotated[str, Field(min_length=1, max_length=512)]
    media_type: Annotated[str, Field(min_length=3, max_length=255)]
    expected_byte_size: int = Field(ge=1)
    byte_size: int | None = Field(default=None, ge=1)
    sha256: m.Hash | None = None
    status: Literal["PENDING", "COMPLETE"]


class UploadCommand(m.StrictModel):
    filename: Annotated[str, Field(min_length=1, max_length=512)]
    media_type: Annotated[str, Field(min_length=3, max_length=255)]
    byte_size: Annotated[StrictInt, Field(ge=1)]
    role: m.ArtifactRole


class UploadResource(m.StrictModel):
    artifact_id: m.Id
    upload_url: Annotated[str, Field(min_length=1, max_length=4096)]
    expires_at: datetime
    upload_headers: dict[str, str] = Field(default_factory=dict)
    artifact: ArtifactResource


class UploadEnvelope(m.StrictModel):
    upload: UploadResource


class UploadCompletionCommand(m.StrictModel):
    sha256: m.Hash
    byte_size: Annotated[StrictInt, Field(ge=1)]
    media_type: Annotated[str, Field(min_length=3, max_length=255)]


class ArtifactEnvelope(m.StrictModel):
    artifact: ArtifactResource


class OperationEnvelope(m.StrictModel):
    job_id: m.Id
    submission_id: m.Id | None = None
    operation: m.JobStatus


class AmbiguityEnvelope(m.StrictModel):
    report: m.AmbiguityReport
    decisions: list[m.PolicyDecision]


class PolicyDecisionCommand(m.StrictModel):
    issue_id: m.Id
    selected_option_id: m.Id
    note: str | None = Field(default=None, max_length=2000)


class PolicyDecisionEnvelope(m.StrictModel):
    decision: m.PolicyDecision


class BlueprintEnvelope(m.StrictModel):
    blueprint: m.AssessmentBlueprint
    review: m.BlueprintReview | None = None
    issues: list[m.Diagnostic] = Field(default_factory=list)
    etag: Etag
    version: int = Field(ge=1)


class SubmissionCreateCommand(m.StrictModel):
    subject_ref: m.Id


class SubmissionResource(m.SubmissionProcessingState):
    activity_id: m.Id
    subject_ref: m.Id
    assessment_id: m.Id | None = None


class SubmissionEnvelope(m.StrictModel):
    submission: SubmissionResource


class JobEnvelope(m.StrictModel):
    job: m.JobStatus


class ModelCallListEnvelope(m.StrictModel):
    items: list[m.ModelCallLedger]


class EvidenceResource(m.EvidenceUnit):
    """Canonical evidence without a capability URL."""


class EvidenceListEnvelope(m.StrictModel):
    items: list[EvidenceResource]
    next_cursor: str | None = None


class QuestionReviewResource(m.QuestionSemanticReview):
    question_id: m.Id
    opportunity_id: m.Id


class EvidenceReceipt(m.StrictModel):
    receipt_id: m.Id
    assessment_id: m.Id
    assessment_version: int = Field(ge=1)
    assessment_etag: Etag
    question_id: m.Id
    fragment_index: int = Field(ge=0, le=7)
    evidence_id: m.Id
    artifact_hash: m.Hash
    locator_hash: m.Hash
    normalized_hash: m.Hash
    verified_at: datetime


class AssessmentEnvelope(m.StrictModel):
    assessment: m.Assessment
    assessment_version: int = Field(ge=1)
    etag: Etag
    guide: m.EvaluationGuide
    reviews: list[QuestionReviewResource]
    evidence: list[EvidenceResource] = Field(default_factory=list)
    evidence_receipts: list[EvidenceReceipt] = Field(default_factory=list)


class GuideEnvelope(m.StrictModel):
    guide: m.EvaluationGuide


class EvidenceVerifyCommand(m.StrictModel):
    assessment_version: Annotated[StrictInt, Field(ge=1)]
    assessment_etag: Etag
    question_id: m.Id
    fragment_index: Annotated[StrictInt, Field(ge=0, le=7)]


class EvidenceVerifyResource(m.StrictModel):
    receipt: EvidenceReceipt
    evidence: EvidenceResource
    view_url: Annotated[str, Field(min_length=1, max_length=4096)]
    view_url_expires_at: datetime


class EvidenceVerifyEnvelope(m.StrictModel):
    verification: EvidenceVerifyResource


class ExportKindCommand(m.StrictModel):
    kind: Literal["ASSESSMENT_PDF", "GUIDE_PDF", "CANONICAL_JSON"]


class ExportResource(m.StrictModel):
    export_id: m.Id
    kind: Literal["ASSESSMENT_PDF", "GUIDE_PDF", "CANONICAL_JSON"]
    status: Literal["QUEUED", "READY", "FAILED"]
    download_url: Annotated[str, Field(min_length=1, max_length=4096)]
    expires_at: datetime
    sha256: m.Hash
    byte_size: int = Field(ge=1)


class ExportEnvelope(m.StrictModel):
    export: ExportResource


class CostEstimate(m.StrictModel):
    estimate_id: m.Id
    phase: Literal["ACTIVITY_BLUEPRINT", "SUBMISSION_ASSESSMENT"]
    model_mode: Literal["mock", "real"]
    estimated_model_calls: int = Field(ge=0, le=100)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)
    upper_bound_cost_usd: float = Field(ge=0.0)
    authorized_limit_usd: float = Field(ge=0.0)
    currency: Literal["USD"] = "USD"
    within_limit: bool
    assumptions: Annotated[list[str], Field(min_length=1, max_length=20)]
    input_fingerprint: m.Hash
    generated_at: datetime


class EstimateEnvelope(m.StrictModel):
    estimate: CostEstimate


class GenericObjectEnvelope(m.StrictModel):
    """Temporary boundary for an explicitly documented object response."""

    value: dict[str, Any]
