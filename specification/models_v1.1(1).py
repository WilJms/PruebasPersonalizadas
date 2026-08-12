"""Canonical contracts for comprehension-verification assessments.

Pydantic v2.13+. Student content is data only; these models do not execute or
dereference artifacts. The 1.2 bundle preserves legacy 1.1 roots and adds
independent Stage 2 roots. All persisted domain objects include schema_version.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


LEGACY_SCHEMA_VERSION = "1.1.0"
CONTRACT_VERSION = "1.2.0"

# Runtime prompt contracts remain on 1.1.0.  The bundle advances to 1.2.0 only
# because Stage 2 adds independent roots without changing any existing root.
SCHEMA_VERSION = LEGACY_SCHEMA_VERSION
SchemaVersion = Literal[LEGACY_SCHEMA_VERSION]
Stage2SchemaVersion = Literal[CONTRACT_VERSION]

Id = Annotated[str, Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")]

PrincipalId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=(
            r"^([a-z][a-z0-9_-]*|"
            r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12})$"
        ),
    ),
]

Hash = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Score = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveInt = Annotated[int, Field(ge=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)


def _require_utc(value: datetime, field_name: str) -> None:
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _require_private_reference(value: str, field_name: str) -> None:
    lowered = value.lower()
    forbidden_markers = (
        "://",
        "?",
        "#",
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-security-token",
        "authorization=",
        "access_token=",
        "token=",
    )
    if value.startswith(("/", "\\")) or any(
        marker in lowered for marker in forbidden_markers
    ):
        raise ValueError(f"{field_name} must be a private opaque reference, not a capability")
    if any(part in {"", ".", ".."} for part in value.replace("\\", "/").split("/")):
        raise ValueError(f"{field_name} contains an unsafe path segment")


def _require_unique(values: list[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")


class ContextMode(StrEnum):
    CLOSED = "CLOSED"
    COURSE_ENRICHED = "COURSE_ENRICHED"


class AssessmentModality(StrEnum):
    WRITTEN = "WRITTEN"
    ORAL = "ORAL"
    MIXED = "MIXED"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ArtifactRole(StrEnum):
    ASSIGNMENT_PROMPT = "ASSIGNMENT_PROMPT"
    RUBRIC = "RUBRIC"
    COURSE_SOURCE = "COURSE_SOURCE"
    SUBMISSION = "SUBMISSION"
    DERIVED_PREVIEW = "DERIVED_PREVIEW"


class EvidenceModality(StrEnum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    LIST = "LIST"
    TABLE = "TABLE"
    CELL_RANGE = "CELL_RANGE"
    FORMULA = "FORMULA"
    SLIDE_SHAPE = "SLIDE_SHAPE"
    SPEAKER_NOTES = "SPEAKER_NOTES"
    CODE_SYMBOL = "CODE_SYMBOL"
    CODE_SPAN = "CODE_SPAN"
    NOTEBOOK_CELL = "NOTEBOOK_CELL"
    IMAGE_REGION = "IMAGE_REGION"
    CHART = "CHART"
    EQUATION = "EQUATION"
    OTHER = "OTHER"


class CognitiveOperation(StrEnum):
    JUSTIFY_DECISION = "JUSTIFY_DECISION"
    EXPLAIN_MECHANISM = "EXPLAIN_MECHANISM"
    RECONSTRUCT_REASONING = "RECONSTRUCT_REASONING"
    CONNECT_INTERNAL = "CONNECT_INTERNAL"
    PREDICT_LOCAL_CONSEQUENCE = "PREDICT_LOCAL_CONSEQUENCE"
    IDENTIFY_DEPENDENCY = "IDENTIFY_DEPENDENCY"
    CRITIQUE_LIMITATION = "CRITIQUE_LIMITATION"
    INTERPRET_REPRESENTATION = "INTERPRET_REPRESENTATION"
    TRACE_FLOW = "TRACE_FLOW"


class AnchorStructure(StrEnum):
    SINGLE_FRAGMENT = "SINGLE_FRAGMENT"
    PAIRED_FRAGMENTS = "PAIRED_FRAGMENTS"
    TABLE_OR_RANGE = "TABLE_OR_RANGE"
    CODE_CONTEXT = "CODE_CONTEXT"
    FIGURE_WITH_CONTEXT = "FIGURE_WITH_CONTEXT"
    SEQUENCE = "SEQUENCE"
    CROSS_ARTIFACT = "CROSS_ARTIFACT"


class ResponseFormat(StrEnum):
    OPEN_SHORT = "OPEN_SHORT"
    STRUCTURED_BULLETS = "STRUCTURED_BULLETS"
    CHOICE = "CHOICE"
    ANNOTATION_OR_DIAGRAM = "ANNOTATION_OR_DIAGRAM"
    ORAL_EQUIVALENT = "ORAL_EQUIVALENT"


class DifficultyBand(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class StructuredJustificationMode(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SELECTED = "SELECTED"
    ALL = "ALL"


class ReasoningEffort(StrEnum):
    MINIMAL = "MINIMAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ModelInputModality(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    PDF = "PDF"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"


class ModelOutputModality(StrEnum):
    TEXT = "TEXT"
    STRUCTURED_JSON = "STRUCTURED_JSON"


class WorkflowStatus(StrEnum):
    DRAFT = "DRAFT"
    BLOCKED = "BLOCKED"
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    INSUFFICIENT_RELEVANT_EVIDENCE = "INSUFFICIENT_RELEVANT_EVIDENCE"
    INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES = (
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES"
    )
    EVIDENCE_MAPPING_UNCERTAIN = "EVIDENCE_MAPPING_UNCERTAIN"
    ASSESSMENT_PLAN_INFEASIBLE = "ASSESSMENT_PLAN_INFEASIBLE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    REJECTED_SECURITY = "REJECTED_SECURITY"


class ReviewDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class ReviewCheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class BlueprintApprovalRecommendation(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CHANGES = "APPROVE_WITH_CHANGES"
    REJECT = "REJECT"


class RepairStatus(StrEnum):
    REPAIRED = "REPAIRED"
    UNREPAIRABLE = "UNREPAIRABLE"


class QuestionReviewActionType(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    EDIT = "EDIT"
    REGENERATE = "REGENERATE"


class SubmissionProcessingStatus(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    PARSING = "PARSING"
    EVIDENCE_READY = "EVIDENCE_READY"
    MAPPING_OPPORTUNITIES = "MAPPING_OPPORTUNITIES"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    VALIDATING_QUESTIONS = "VALIDATING_QUESTIONS"
    GUIDE_READY = "GUIDE_READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    INSUFFICIENT_RELEVANT_EVIDENCE = "INSUFFICIENT_RELEVANT_EVIDENCE"
    INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES = (
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES"
    )
    EVIDENCE_MAPPING_UNCERTAIN = "EVIDENCE_MAPPING_UNCERTAIN"
    ASSESSMENT_PLAN_INFEASIBLE = "ASSESSMENT_PLAN_INFEASIBLE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    REJECTED_SECURITY = "REJECTED_SECURITY"
    CANCELLED = "CANCELLED"


class StageRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailureClass(StrEnum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    SECURITY = "SECURITY"
    VALIDATION = "VALIDATION"
    PRECONDITION = "PRECONDITION"
    PROVIDER = "PROVIDER"
    CANCELLATION = "CANCELLATION"


class JobControlActionType(StrEnum):
    RETRY = "RETRY"
    CANCEL = "CANCEL"
    RESUME = "RESUME"


class JobControlStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class CoverageScope(StrEnum):
    SUBMISSION = "SUBMISSION"
    ACTIVITY = "ACTIVITY"


class CoveragePlanningRole(StrEnum):
    PRIMARY = "PRIMARY"
    RESERVE = "RESERVE"
    EXCLUDED = "EXCLUDED"


class CoverageOutcome(StrEnum):
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    FAILED = "FAILED"
    EXCLUDED = "EXCLUDED"


class ExportKind(StrEnum):
    ASSESSMENT_PDF = "ASSESSMENT_PDF"
    ASSESSMENT_HTML = "ASSESSMENT_HTML"
    GUIDE_PDF = "GUIDE_PDF"
    GUIDE_HTML = "GUIDE_HTML"
    COVERAGE_CSV = "COVERAGE_CSV"
    COVERAGE_JSON = "COVERAGE_JSON"
    CANONICAL_JSON = "CANONICAL_JSON"


class ExportStatus(StrEnum):
    QUEUED = "QUEUED"
    READY = "READY"
    FAILED = "FAILED"


class FeedbackTargetType(StrEnum):
    ACTIVITY = "ACTIVITY"
    ASSESSMENT = "ASSESSMENT"
    QUESTION = "QUESTION"


class FeedbackRating(StrEnum):
    VERY_UNHELPFUL = "VERY_UNHELPFUL"
    UNHELPFUL = "UNHELPFUL"
    NEUTRAL = "NEUTRAL"
    HELPFUL = "HELPFUL"
    VERY_HELPFUL = "VERY_HELPFUL"


class FeedbackCategory(StrEnum):
    GROUNDING = "GROUNDING"
    ANSWERABILITY = "ANSWERABILITY"
    QUESTION_QUALITY = "QUESTION_QUALITY"
    GUIDE_QUALITY = "GUIDE_QUALITY"
    COVERAGE = "COVERAGE"
    WORKFLOW = "WORKFLOW"
    EXPORT = "EXPORT"
    OTHER = "OTHER"


class QuestionReviewRecordStatus(StrEnum):
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class RevalidationStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class Diagnostic(StrictModel):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    severity: Severity
    message: Annotated[str, Field(min_length=3, max_length=1000)]
    evidence_ids: list[Id] = Field(default_factory=list, max_length=100)
    source_ids: list[Id] = Field(default_factory=list, max_length=100)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class PageLocator(StrictModel):
    kind: Literal["PAGE_BBOX"] = "PAGE_BBOX"
    page: PositiveInt
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]
    block_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def bbox_is_ordered(self) -> "PageLocator":
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError("bbox must be ordered [x0,y0,x1,y1]")
        return self


class DocumentLocator(StrictModel):
    kind: Literal["DOCUMENT_PATH"] = "DOCUMENT_PATH"
    paragraph_index: int | None = Field(default=None, ge=0)
    heading_path: list[str] = Field(default_factory=list, max_length=20)
    table_index: int | None = Field(default=None, ge=0)
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)


class SlideLocator(StrictModel):
    kind: Literal["SLIDE_SHAPE"] = "SLIDE_SHAPE"
    slide_number: PositiveInt
    shape_id: str | None = Field(default=None, max_length=128)
    notes: bool = False


class SheetLocator(StrictModel):
    kind: Literal["SHEET_RANGE"] = "SHEET_RANGE"
    workbook: str | None = Field(default=None, max_length=255)
    sheet: Annotated[str, Field(min_length=1, max_length=255)]
    range_a1: Annotated[str, Field(min_length=1, max_length=128)]


class CodeLocator(StrictModel):
    kind: Literal["CODE_SPAN"] = "CODE_SPAN"
    path: Annotated[str, Field(min_length=1, max_length=1024)]
    start_line: PositiveInt
    end_line: PositiveInt
    start_column: int | None = Field(default=None, ge=0)
    end_column: int | None = Field(default=None, ge=0)
    symbol: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def lines_are_ordered(self) -> "CodeLocator":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class NotebookLocator(StrictModel):
    kind: Literal["NOTEBOOK_CELL"] = "NOTEBOOK_CELL"
    path: Annotated[str, Field(min_length=1, max_length=1024)]
    cell_id: Annotated[str, Field(min_length=1, max_length=255)]
    cell_index: int = Field(ge=0)
    output_index: int | None = Field(default=None, ge=0)


class ImageLocator(StrictModel):
    kind: Literal["IMAGE_REGION"] = "IMAGE_REGION"
    path: Annotated[str, Field(min_length=1, max_length=1024)]
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]
    coordinate_space: Literal["PIXELS", "NORMALIZED"] = "PIXELS"


SourceLocator = Annotated[
    PageLocator
    | DocumentLocator
    | SlideLocator
    | SheetLocator
    | CodeLocator
    | NotebookLocator
    | ImageLocator,
    Field(discriminator="kind"),
]


class ArtifactRef(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    artifact_id: Id
    role: ArtifactRole
    filename: Annotated[str, Field(min_length=1, max_length=512)]
    media_type: Annotated[str, Field(min_length=3, max_length=255)]
    sha256: Hash
    byte_size: int = Field(ge=0)
    parser_id: str | None = Field(default=None, max_length=128)
    parser_version: str | None = Field(default=None, max_length=128)


class EvidenceRelation(StrictModel):
    relation: Literal[
        "CONTAINS",
        "DEPENDS_ON",
        "REFERENCES",
        "CONTINUES",
        "DERIVED_FROM",
        "CORROBORATES",
        "CONTRADICTS",
    ]
    target_evidence_id: Id
    confidence: Score


class EvidenceUnit(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    evidence_id: Id
    tenant_id: Id
    submission_id: Id | None = None
    artifact_id: Id
    artifact_hash: Hash
    source_role: ArtifactRole
    modality: EvidenceModality
    locator: SourceLocator
    content_text: str | None = Field(default=None, max_length=100_000)
    structured_content: dict[str, Any] | None = None
    language: str | None = Field(default=None, max_length=35)
    extraction_confidence: Score
    ocr_used: bool = False
    sensitive_labels: list[str] = Field(default_factory=list, max_length=50)
    relations: list[EvidenceRelation] = Field(default_factory=list, max_length=500)
    normalized_hash: Hash

    @model_validator(mode="after")
    def has_content(self) -> "EvidenceUnit":
        if not self.content_text and not self.structured_content:
            raise ValueError("evidence must contain text or structured_content")
        if self.source_role == ArtifactRole.SUBMISSION and not self.submission_id:
            raise ValueError("submission evidence requires submission_id")
        return self


class CoursePassage(StrictModel):
    """Authorized, versioned course passage supplied to an enriched-context call."""

    source_id: Id
    artifact_id: Id
    artifact_hash: Hash
    title: Annotated[str, Field(min_length=1, max_length=500)]
    locator: SourceLocator
    content_text: Annotated[str, Field(min_length=1, max_length=50_000)]
    language: str | None = Field(default=None, max_length=35)
    extraction_confidence: Score


class SourceCitation(StrictModel):
    source_id: Id
    locator: SourceLocator
    supported_claim: Annotated[str, Field(min_length=1, max_length=1000)]


class EvidenceBundle(StrictModel):
    """Exact allowlisted evidence sent to one model call."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    bundle_id: Id
    tenant_id: Id
    activity_id: Id
    submission_id: Id
    context_mode: ContextMode = ContextMode.CLOSED
    allowed_evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=500)]
    evidence_units: Annotated[list[EvidenceUnit], Field(min_length=1, max_length=500)]
    course_passages: list[CoursePassage] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def bundle_is_allowlisted(self) -> "EvidenceBundle":
        unit_ids = [unit.evidence_id for unit in self.evidence_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("evidence_units must have unique evidence_id values")
        if set(unit_ids) != set(self.allowed_evidence_ids):
            raise ValueError("allowed_evidence_ids must exactly match evidence_units")
        for unit in self.evidence_units:
            if unit.tenant_id != self.tenant_id:
                raise ValueError("evidence unit belongs to another tenant")
            if unit.submission_id != self.submission_id:
                raise ValueError("evidence unit belongs to another submission")
        source_ids = [passage.source_id for passage in self.course_passages]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("course_passages must have unique source_id values")
        if self.context_mode == ContextMode.CLOSED and self.course_passages:
            raise ValueError("CLOSED evidence bundle cannot include course passages")
        return self


class TrustedPromptContext(StrictModel):
    tenant_id: Id
    activity_id: Id
    submission_id: Id | None = None
    blueprint_id: Id | None = None
    blueprint_version: PositiveInt | None = None
    allowed_evidence_ids: list[Id] = Field(default_factory=list, max_length=500)
    allowed_course_source_ids: list[Id] = Field(default_factory=list, max_length=100)
    output_language: Annotated[str, Field(min_length=2, max_length=35)] = "es-CL"
    context_mode: ContextMode = ContextMode.CLOSED
    data_classification: Literal["SYNTHETIC_ONLY_NO_STUDENT_DATA"] | None = None
    attestation_id: Id | None = None
    attested_input_hash: Hash | None = None
    attested_artifact_hashes: list[Hash] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def blueprint_ref_is_complete(self) -> "TrustedPromptContext":
        if (self.blueprint_id is None) != (self.blueprint_version is None):
            raise ValueError("blueprint_id and blueprint_version must both be set or absent")
        if self.context_mode == ContextMode.CLOSED and self.allowed_course_source_ids:
            raise ValueError("CLOSED context cannot authorize course sources")
        attestation_fields = (
            self.data_classification,
            self.attestation_id,
            self.attested_input_hash,
        )
        if any(value is not None for value in attestation_fields) and not all(
            value is not None for value in attestation_fields
        ):
            raise ValueError("synthetic attestation fields must all be set or absent")
        if self.attested_artifact_hashes and self.attestation_id is None:
            raise ValueError("attested artifact hashes require an attestation")
        _require_unique(self.attested_artifact_hashes, "attested_artifact_hashes")
        return self


class ModelTaskEnvelope(StrictModel):
    """Transport envelope; payload is validated again against its prompt request root."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    prompt_id: Annotated[str, Field(pattern=r"^P(?:0[1-9]|1[01])_[A-Z0-9_]+_V1$")]
    prompt_version: Annotated[str, Field(pattern=r"^1\.1\.\d+$")]
    output_schema_name: Annotated[str, Field(min_length=3, max_length=128)]
    output_schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    trusted_context: TrustedPromptContext
    payload: dict[str, Any]


class ActivityConfig(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_id: Id
    tenant_id: Id
    title: Annotated[str, Field(min_length=1, max_length=300)]
    output_language: Annotated[str, Field(min_length=2, max_length=35)] = "es-CL"
    context_mode: ContextMode = ContextMode.CLOSED
    assessment_modality: AssessmentModality = AssessmentModality.WRITTEN
    question_count: int = Field(default=5, ge=1, le=20)
    target_total_minutes: int = Field(default=15, ge=3, le=120)
    structured_justification_mode: StructuredJustificationMode = (
        StructuredJustificationMode.NOT_REQUIRED
    )
    priority_criterion_ids: list[Id] = Field(default_factory=list, max_length=100)
    allowed_response_formats: Annotated[list[ResponseFormat], Field(min_length=1)]
    allowed_artifact_media_types: Annotated[list[str], Field(min_length=1, max_length=50)]
    course_source_ids: list[Id] = Field(default_factory=list)
    adaptation_policy_id: Id | None = None
    require_blueprint_approval: Literal[True] = True

    @model_validator(mode="after")
    def enriched_requires_sources(self) -> "ActivityConfig":
        if self.context_mode == ContextMode.COURSE_ENRICHED and not self.course_source_ids:
            raise ValueError("COURSE_ENRICHED requires course_source_ids")
        if len(self.allowed_response_formats) != len(set(self.allowed_response_formats)):
            raise ValueError("allowed_response_formats must be unique")
        return self


class SourcedStatement(StrictModel):
    statement_id: Id
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    certainty: Literal["EXPLICIT", "WEAK_INFERENCE", "MISSING"] = "EXPLICIT"


class ActivitySpec(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_id: Id
    status: WorkflowStatus
    learning_outcomes: list[SourcedStatement] = Field(default_factory=list)
    expected_products: list[SourcedStatement] = Field(default_factory=list)
    requirements: list[SourcedStatement] = Field(default_factory=list)
    allowed_materials: list[SourcedStatement] = Field(default_factory=list)
    prohibited_materials: list[SourcedStatement] = Field(default_factory=list)
    contradictions: list[Diagnostic] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def statement_ids_are_unique(self) -> "ActivitySpec":
        statement_ids = [
            item.statement_id
            for collection in (
                self.learning_outcomes,
                self.expected_products,
                self.requirements,
                self.allowed_materials,
                self.prohibited_materials,
            )
            for item in collection
        ]
        _require_unique(statement_ids, "ActivitySpec statement_ids")
        return self


class RubricLevel(StrictModel):
    level_id: Id
    label: Annotated[str, Field(min_length=1, max_length=200)]
    ordinal: int = Field(ge=0, le=20)
    descriptor: str | None = Field(default=None, max_length=4000)
    evidence_ids: list[Id] = Field(default_factory=list, max_length=50)


class RubricCriterion(StrictModel):
    criterion_id: Id
    name: Annotated[str, Field(min_length=1, max_length=300)]
    description: str | None = Field(default=None, max_length=4000)
    evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=100)]
    grading_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    levels: list[RubricLevel] = Field(default_factory=list, max_length=20)
    observables: list[str] = Field(default_factory=list, max_length=50)
    verification_fit: Literal["HIGH", "MEDIUM", "LOW", "NOT_VERIFIABLE"]
    overlaps_with: list[Id] = Field(default_factory=list)


class RubricSpec(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_id: Id
    status: WorkflowStatus
    scale_label: str | None = Field(default=None, max_length=200)
    criteria: list[RubricCriterion]
    reported_weight_total: float | None = Field(default=None, ge=0.0, le=100.0)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def rubric_ids_are_unique(self) -> "RubricSpec":
        _require_unique(
            [criterion.criterion_id for criterion in self.criteria],
            "RubricSpec criterion_ids",
        )
        _require_unique(
            [level.level_id for criterion in self.criteria for level in criterion.levels],
            "RubricSpec level_ids",
        )
        return self


class DecisionOption(StrictModel):
    option_id: Id
    label: Annotated[str, Field(min_length=1, max_length=300)]
    consequence: Annotated[str, Field(min_length=1, max_length=1000)]


class AmbiguityIssue(StrictModel):
    issue_id: Id
    issue_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    severity: Severity
    evidence_ids: list[Id] = Field(default_factory=list)
    explanation: Annotated[str, Field(min_length=1, max_length=1500)]
    options: Annotated[list[DecisionOption], Field(min_length=2, max_length=3)]
    recommended_option_id: Id
    blocking: bool

    @model_validator(mode="after")
    def recommendation_exists(self) -> "AmbiguityIssue":
        _require_unique(
            [option.option_id for option in self.options],
            "AmbiguityIssue option_ids",
        )
        if self.recommended_option_id not in {x.option_id for x in self.options}:
            raise ValueError("recommended_option_id must reference an option")
        return self


class AmbiguityReport(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_id: Id
    issues: list[AmbiguityIssue] = Field(default_factory=list, max_length=8)
    blocked: bool

    @model_validator(mode="after")
    def issue_state_is_consistent(self) -> "AmbiguityReport":
        _require_unique(
            [issue.issue_id for issue in self.issues],
            "AmbiguityReport issue_ids",
        )
        _require_unique(
            [option.option_id for issue in self.issues for option in issue.options],
            "AmbiguityReport option_ids",
        )
        if self.blocked != any(issue.blocking for issue in self.issues):
            raise ValueError("blocked must exactly match the presence of blocking issues")
        return self


class PolicyDecision(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    decision_id: Id
    issue_id: Id
    selected_option_id: Id
    selected_option: DecisionOption | None = None
    decided_by: PrincipalId
    decided_at: datetime
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def selected_option_matches_id(self) -> "PolicyDecision":
        if (
            self.selected_option is not None
            and self.selected_option.option_id != self.selected_option_id
        ):
            raise ValueError("selected_option must match selected_option_id")
        return self


def _resolved_decisions_are_self_contained(
    decisions: list[PolicyDecision],
) -> None:
    decision_ids = [decision.decision_id for decision in decisions]
    issue_ids = [decision.issue_id for decision in decisions]
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("resolved decisions must have unique decision_ids")
    if len(issue_ids) != len(set(issue_ids)):
        raise ValueError("resolved decisions must have unique issue_ids")
    if any(decision.selected_option is None for decision in decisions):
        raise ValueError("resolved decisions require selected_option snapshots")


class StructuredJustificationPolicy(StrictModel):
    mode: StructuredJustificationMode = StructuredJustificationMode.NOT_REQUIRED
    selected_opportunity_template_ids: list[Id] = Field(
        default_factory=list, max_length=200
    )

    @model_validator(mode="after")
    def selected_ids_match_mode(self) -> "StructuredJustificationPolicy":
        if self.mode == StructuredJustificationMode.SELECTED:
            if not self.selected_opportunity_template_ids:
                raise ValueError("SELECTED mode requires opportunity template ids")
        elif self.selected_opportunity_template_ids:
            raise ValueError("selected ids are allowed only in SELECTED mode")
        return self


class AssessmentPlanningPolicy(StrictModel):
    """Deterministic policy used before question generation."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    policy_id: Id
    minimum_opportunity_quality: Score = 0.75
    minimum_evidence_fit: Score = 0.7
    activity_priority_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    evidence_fit_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    opportunity_quality_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    repeated_dimension_penalty: float = Field(default=0.08, ge=0.0, le=1.0)
    repeated_variant_penalty: float = Field(default=0.12, ge=0.0, le=1.0)
    evidence_overlap_penalty: float = Field(default=0.15, ge=0.0, le=1.0)
    maximum_evidence_overlap: Score = 0.5
    max_reserve_opportunities: int = Field(default=3, ge=0, le=10)


class BlueprintPolicy(StrictModel):
    """Trusted constraints used by P04; depth is derived rather than selected."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    policy_id: Id
    activity_id: Id
    question_count: int = Field(ge=1, le=20)
    target_total_minutes: int = Field(ge=3, le=120)
    allowed_response_formats: Annotated[
        list[ResponseFormat], Field(min_length=1, max_length=20)
    ]
    priority_criterion_ids: list[Id] = Field(default_factory=list, max_length=100)
    required_criterion_ids: list[Id] = Field(default_factory=list, max_length=100)
    structured_justification_policy: StructuredJustificationPolicy
    planning_policy: AssessmentPlanningPolicy
    max_local_regenerations: int = Field(default=1, ge=0, le=3)
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def policy_is_consistent(self) -> "BlueprintPolicy":
        if len(self.allowed_response_formats) != len(set(self.allowed_response_formats)):
            raise ValueError("allowed_response_formats must be unique")
        return self


class QuestionGenerationPolicy(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    policy_id: Id
    max_anchor_fragments: int = Field(default=4, ge=1, le=8)
    max_course_passages: int = Field(default=8, ge=0, le=50)
    require_accessible_alternative: bool = True
    max_local_regenerations: int = Field(default=1, ge=0, le=3)


class QuestionValidationPolicy(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    policy_id: Id
    minimum_groundedness: Score = 0.9
    minimum_anchor_sufficiency: Score = 0.8
    minimum_answerability: Score = 0.85
    minimum_criterion_relevance: Score = 0.8
    escalate_below_confidence: Score = 0.65
    critical_failure_codes: list[str] = Field(default_factory=list, max_length=100)


class VerificationFactors(StrictModel):
    learning_relevance: Score
    centrality: Score
    expected_evidence: Score
    discriminative_potential: Score
    auditability: Score
    short_response_observability: Score


class EvidenceRequirement(StrictModel):
    allowed_modalities: Annotated[list[EvidenceModality], Field(min_length=1)]
    min_distinct_units: int = Field(default=1, ge=1, le=20)
    min_extraction_confidence: Score = 0.75
    min_alignment: Score = 0.65
    cross_artifact_required: bool = False
    course_sources_allowed: bool = False


class SupportedOperation(StrictModel):
    cognitive_operation: CognitiveOperation
    support_strength: Score
    rationale: Annotated[str, Field(min_length=1, max_length=800)]


class QuestionOpportunityTemplate(StrictModel):
    opportunity_template_id: Id
    cognitive_operation: CognitiveOperation
    focus: Annotated[str, Field(min_length=1, max_length=1000)]
    observable: Annotated[str, Field(min_length=1, max_length=1000)]
    difficulty: DifficultyBand
    target_minutes: int = Field(ge=1, le=60)
    allowed_anchor_structures: Annotated[list[AnchorStructure], Field(min_length=1)]
    allowed_response_formats: Annotated[list[ResponseFormat], Field(min_length=1)]
    verification_potential: Score
    minimum_quality: Score = 0.75
    student_justification_required: bool = False


class EvidenceVariant(StrictModel):
    variant_id: Id
    name: Annotated[str, Field(min_length=1, max_length=300)]
    description: Annotated[str, Field(min_length=1, max_length=1200)]
    evidence_requirement: EvidenceRequirement
    verification_potential: Score
    supported_operations: Annotated[
        list[SupportedOperation], Field(min_length=1, max_length=9)
    ]
    question_opportunities: Annotated[
        list[QuestionOpportunityTemplate], Field(min_length=1, max_length=100)
    ]

    @model_validator(mode="after")
    def opportunities_use_supported_operations(self) -> "EvidenceVariant":
        supported = {x.cognitive_operation for x in self.supported_operations}
        if len(supported) != len(self.supported_operations):
            raise ValueError("supported cognitive operations must be unique")
        if any(
            x.cognitive_operation not in supported for x in self.question_opportunities
        ):
            raise ValueError("question opportunity uses an unsupported operation")
        opportunity_ids = [x.opportunity_template_id for x in self.question_opportunities]
        if len(opportunity_ids) != len(set(opportunity_ids)):
            raise ValueError("opportunity_template_ids must be unique within a variant")
        return self


class BlueprintDimension(StrictModel):
    dimension_id: Id
    name: Annotated[str, Field(min_length=1, max_length=300)]
    criterion_ids: Annotated[list[Id], Field(min_length=1)]
    learning_outcome_ids: list[Id] = Field(default_factory=list)
    grading_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_priority: Score
    factors: VerificationFactors
    justification: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_variants: Annotated[list[EvidenceVariant], Field(min_length=1)]


class AssessmentConstraints(StrictModel):
    question_count: int = Field(ge=1, le=20)
    target_total_minutes: int = Field(ge=3, le=120)
    allowed_response_formats: Annotated[
        list[ResponseFormat], Field(min_length=1, max_length=20)
    ]
    minimum_opportunity_quality: Score = 0.75
    max_reserve_opportunities: int = Field(default=3, ge=0, le=10)
    priority_criterion_ids: list[Id] = Field(default_factory=list, max_length=100)
    required_criterion_ids: list[Id] = Field(default_factory=list, max_length=100)
    structured_justification_policy: StructuredJustificationPolicy

    @model_validator(mode="after")
    def criterion_ids_are_unique(self) -> "AssessmentConstraints":
        _require_unique(self.priority_criterion_ids, "priority_criterion_ids")
        _require_unique(self.required_criterion_ids, "required_criterion_ids")
        return self


class AssessmentBlueprint(StrictModel):
    """Activity catalog; its size is independent of question_count."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    blueprint_id: Id
    blueprint_version: PositiveInt
    activity_id: Id
    status: WorkflowStatus
    context_mode: ContextMode
    dimensions: Annotated[list[BlueprintDimension], Field(min_length=1)]
    assessment_constraints: AssessmentConstraints
    decision_ids: list[Id] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    approved_by: PrincipalId | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def blueprint_is_consistent(self) -> "AssessmentBlueprint":
        dimension_ids = [d.dimension_id for d in self.dimensions]
        variant_ids = [
            variant.variant_id
            for dimension in self.dimensions
            for variant in dimension.evidence_variants
        ]
        opportunity_ids = [
            opportunity.opportunity_template_id
            for dimension in self.dimensions
            for variant in dimension.evidence_variants
            for opportunity in variant.question_opportunities
        ]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("dimension_ids must be unique")
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("variant_ids must be unique across the blueprint")
        if len(opportunity_ids) != len(set(opportunity_ids)):
            raise ValueError("opportunity_template_ids must be unique across the blueprint")
        allowed_formats = set(self.assessment_constraints.allowed_response_formats)
        if any(
            not set(opportunity.allowed_response_formats).issubset(allowed_formats)
            for dimension in self.dimensions
            for variant in dimension.evidence_variants
            for opportunity in variant.question_opportunities
        ):
            raise ValueError("opportunity response format is not allowed by constraints")
        selected_templates = set(
            self.assessment_constraints.structured_justification_policy
            .selected_opportunity_template_ids
        )
        if not selected_templates.issubset(set(opportunity_ids)):
            raise ValueError("justification policy references an unknown opportunity")
        if (self.approved_by is None) != (self.approved_at is None):
            raise ValueError("approved_by and approved_at must both be set or absent")
        return self


class BlueprintReviewCheck(StrictModel):
    check_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    category: Literal[
        "CONSTRUCT",
        "SOURCE_FIDELITY",
        "COVERAGE",
        "COMPARABILITY",
        "COGNITIVE_DEMAND",
        "TIME",
        "FORMAT_FEASIBILITY",
        "OPPORTUNITY_CATALOG",
        "PLAN_FEASIBILITY",
        "ACCESSIBILITY",
    ]
    status: ReviewCheckStatus
    message: Annotated[str, Field(min_length=3, max_length=1500)]
    referenced_ids: list[Id] = Field(default_factory=list, max_length=100)
    correction: str | None = Field(default=None, max_length=1500)
    critical: bool = False


class BlueprintReview(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_id: Id
    blueprint_id: Id
    blueprint_version: PositiveInt
    status: Literal["READY", "NEEDS_REVIEW", "TECHNICAL_FAILURE"]
    approval_recommendation: BlueprintApprovalRecommendation | None = None
    checks: list[BlueprintReviewCheck] = Field(default_factory=list, max_length=100)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def recommendation_matches_checks(self) -> "BlueprintReview":
        required_categories = {
            "CONSTRUCT",
            "SOURCE_FIDELITY",
            "COVERAGE",
            "COMPARABILITY",
            "COGNITIVE_DEMAND",
            "TIME",
            "FORMAT_FEASIBILITY",
            "OPPORTUNITY_CATALOG",
            "PLAN_FEASIBILITY",
            "ACCESSIBILITY",
        }
        _require_unique(
            [check.check_code for check in self.checks],
            "BlueprintReview check_codes",
        )
        critical_fail = any(
            check.critical and check.status == ReviewCheckStatus.FAIL
            for check in self.checks
        )
        if self.status == "READY" and self.approval_recommendation is None:
            raise ValueError("READY review requires approval_recommendation")
        if self.status == "READY" and {
            check.category for check in self.checks
        } != required_categories:
            raise ValueError("READY review requires every canonical review category")
        if self.status != "READY" and self.approval_recommendation is not None:
            raise ValueError("non-READY review cannot recommend approval")
        if critical_fail and (
            self.approval_recommendation != BlueprintApprovalRecommendation.REJECT
        ):
            raise ValueError("critical FAIL requires REJECT")
        return self


class EvidenceAlignment(StrictModel):
    dimension_id: Id
    variant_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    criterion_ids: list[Id] = Field(default_factory=list)
    strength: Score
    justification: Annotated[str, Field(min_length=1, max_length=800)]


class EvidenceClaim(StrictModel):
    claim_id: Id
    text: Annotated[str, Field(min_length=1, max_length=1500)]
    evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    alignments: list[EvidenceAlignment] = Field(default_factory=list)
    supported_operations: list[CognitiveOperation] = Field(default_factory=list)
    specificity: Score
    auditability: Score
    self_containment: Score
    ambiguity_risk: Score
    uncertainties: list[str] = Field(default_factory=list, max_length=20)


class EvidenceVariantMatch(StrictModel):
    dimension_id: Id
    variant_id: Id
    evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    evidence_fit: Score
    mapping_confidence: Score
    justification: Annotated[str, Field(min_length=1, max_length=1000)]


class QuestionOpportunity(StrictModel):
    opportunity_id: Id
    opportunity_template_id: Id
    submission_id: Id
    dimension_id: Id
    variant_id: Id
    evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    cognitive_operation: CognitiveOperation
    focus: Annotated[str, Field(min_length=1, max_length=1000)]
    observable: Annotated[str, Field(min_length=1, max_length=1000)]
    difficulty: DifficultyBand
    target_minutes: int = Field(ge=1, le=60)
    allowed_anchor_structures: Annotated[list[AnchorStructure], Field(min_length=1)]
    allowed_response_formats: Annotated[list[ResponseFormat], Field(min_length=1)]
    activity_priority: Score
    evidence_fit: Score
    opportunity_quality: Score
    student_justification_required: bool = False


PlanningFailure = Literal[
    "INSUFFICIENT_RELEVANT_EVIDENCE",
    "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
    "EVIDENCE_MAPPING_UNCERTAIN",
    "ASSESSMENT_PLAN_INFEASIBLE",
]


class EvidenceMapPatch(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    submission_id: Id
    status: Literal[
        "READY",
        "INSUFFICIENT_RELEVANT_EVIDENCE",
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
        "EVIDENCE_MAPPING_UNCERTAIN",
        "TECHNICAL_FAILURE",
    ]
    claims: list[EvidenceClaim] = Field(default_factory=list)
    variant_matches: list[EvidenceVariantMatch] = Field(default_factory=list)
    opportunities: list[QuestionOpportunity] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def opportunity_mapping_is_consistent(self) -> "EvidenceMapPatch":
        opportunity_ids = [x.opportunity_id for x in self.opportunities]
        if len(opportunity_ids) != len(set(opportunity_ids)):
            raise ValueError("opportunity_ids must be unique")
        if any(x.submission_id != self.submission_id for x in self.opportunities):
            raise ValueError("opportunities must belong to the mapped submission")
        if self.status != "READY" and self.opportunities:
            raise ValueError("non-READY mapping cannot expose usable opportunities")
        return self


class AssessmentPlan(StrictModel):
    """Exactly N primary opportunities plus a small, disjoint reserve."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    plan_id: Id
    submission_id: Id
    blueprint_id: Id
    blueprint_version: PositiveInt
    status: Literal[
        "READY",
        "INSUFFICIENT_RELEVANT_EVIDENCE",
        "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
        "EVIDENCE_MAPPING_UNCERTAIN",
        "ASSESSMENT_PLAN_INFEASIBLE",
    ]
    question_count: int = Field(ge=1, le=20)
    selected_opportunity_ids: list[Id] = Field(default_factory=list, max_length=20)
    reserve_opportunity_ids: list[Id] = Field(default_factory=list, max_length=10)
    estimated_total_minutes: int = Field(default=0, ge=0, le=120)
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def plan_is_atomic(self) -> "AssessmentPlan":
        primary = self.selected_opportunity_ids
        reserve = self.reserve_opportunity_ids
        if len(primary) != len(set(primary)) or len(reserve) != len(set(reserve)):
            raise ValueError("planned opportunity ids must be unique")
        if set(primary).intersection(reserve):
            raise ValueError("primary and reserve opportunities must be disjoint")
        if self.status == "READY" and len(primary) != self.question_count:
            raise ValueError("READY plan requires exactly question_count primaries")
        if self.status != "READY" and (primary or reserve):
            raise ValueError("failed plan cannot contain a partial assessment")
        return self


class AnchorFragment(StrictModel):
    evidence_id: Id
    display_text: str | None = Field(default=None, max_length=20_000)
    transformation: Literal["LITERAL", "CROP", "TABLE_SLICE", "CODE_CONTEXT", "ALT_TEXT"]
    locator: SourceLocator


class Anchor(StrictModel):
    anchor_id: Id
    structure: AnchorStructure
    fragments: Annotated[list[AnchorFragment], Field(min_length=1, max_length=8)]
    student_facing_label: str | None = Field(default=None, max_length=300)
    self_containment_score: Score
    answer_leakage_risk: Score


class ObservableElement(StrictModel):
    element_id: Id
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_ids: Annotated[list[Id], Field(min_length=1)]
    source_ids: list[Id] = Field(default_factory=list, max_length=50)
    required_for_level_2: bool = True


class GuideLevel(StrictModel):
    level: Annotated[int, Field(ge=0, le=3)]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    descriptor: Annotated[str, Field(min_length=1, max_length=2000)]
    observable_element_ids: list[Id] = Field(default_factory=list)


class GuideDraft(StrictModel):
    purpose: Annotated[str, Field(min_length=1, max_length=1000)]
    observable_elements: list[ObservableElement] = Field(default_factory=list, max_length=20)
    acceptable_alternatives: list[str] = Field(default_factory=list, max_length=20)
    misconceptions: list[str] = Field(default_factory=list, max_length=20)
    levels: list[GuideLevel] = Field(default_factory=list, max_length=4)
    cannot_infer: list[str] = Field(default_factory=list, max_length=20)


class EvaluationGuideItem(StrictModel):
    question_id: Id
    guide: GuideDraft


class EvaluationGuide(StrictModel):
    """Structured guide persisted with the assessment and submission."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    guide_id: Id
    assessment_id: Id
    submission_id: Id
    status: Literal["READY", "NEEDS_REVIEW", "TECHNICAL_FAILURE"]
    items: list[EvaluationGuideItem] = Field(default_factory=list, max_length=20)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def guide_is_consistent(self) -> "EvaluationGuide":
        question_ids = [item.question_id for item in self.items]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("EvaluationGuide question_ids must be unique")
        if self.status == "READY" and not self.items:
            raise ValueError("READY guide requires items")
        if self.status == "READY":
            for item in self.items:
                elements = item.guide.observable_elements
                if not 2 <= len(elements) <= 5:
                    raise ValueError("READY guide items require 2 to 5 observables")
                _require_unique(
                    [element.element_id for element in elements],
                    "EvaluationGuide observable element_ids",
                )
        return self


class ChoiceOption(StrictModel):
    option_id: Id
    text: Annotated[str, Field(min_length=1, max_length=1000)]
    is_best_answer: bool
    evaluator_rationale: Annotated[str, Field(min_length=1, max_length=1500)]
    misconception: str | None = Field(default=None, max_length=1000)


class RejectedQuestionFingerprint(StrictModel):
    fingerprint_id: Id
    opportunity_id: Id
    evidence_ids: list[Id] = Field(default_factory=list, max_length=50)
    normalized_question_hash: Hash
    rejection_codes: list[str] = Field(default_factory=list, max_length=20)


class QuestionCandidate(StrictModel):
    candidate_id: Id
    submission_id: Id
    opportunity_id: Id
    opportunity_template_id: Id
    dimension_id: Id
    variant_id: Id
    cognitive_operation: CognitiveOperation
    response_format: ResponseFormat
    difficulty: DifficultyBand
    estimated_minutes: int = Field(ge=1, le=60)
    question_text: Annotated[str, Field(min_length=5, max_length=4000)]
    anchor: Anchor
    evidence_ids: Annotated[list[Id], Field(min_length=1, max_length=50)]
    course_source_ids: list[Id] = Field(default_factory=list, max_length=50)
    citations: list[SourceCitation] = Field(default_factory=list, max_length=50)
    choices: list[ChoiceOption] = Field(default_factory=list, max_length=8)
    student_justification_required: bool = False
    preliminary_guide: GuideDraft
    uncertainties: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def candidate_sources_are_consistent(self) -> "QuestionCandidate":
        anchor_ids = {f.evidence_id for f in self.anchor.fragments}
        if not anchor_ids.issubset(set(self.evidence_ids)):
            raise ValueError("anchor evidence must be included in evidence_ids")
        if self.response_format == ResponseFormat.CHOICE:
            if len(self.choices) < 3 or sum(x.is_best_answer for x in self.choices) != 1:
                raise ValueError("choice question requires >=3 options and one best answer")
            if any(
                not option.is_best_answer and not option.misconception
                for option in self.choices
            ):
                raise ValueError("every distractor requires a defendable misconception")
        elif self.choices:
            raise ValueError("choices allowed only for CHOICE")
        cited_source_ids = {citation.source_id for citation in self.citations}
        if set(self.course_source_ids) != cited_source_ids:
            raise ValueError("course_source_ids must exactly match citation source_ids")
        return self


class QuestionGenerationResult(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    submission_id: Id
    opportunity_id: Id
    context_mode: ContextMode = ContextMode.CLOSED
    status: Literal["READY", "REPLACEMENT_REQUIRED", "TECHNICAL_FAILURE"]
    candidate: QuestionCandidate | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def result_is_consistent(self) -> "QuestionGenerationResult":
        if self.candidate is not None:
            if (
                self.candidate.submission_id != self.submission_id
                or self.candidate.opportunity_id != self.opportunity_id
            ):
                raise ValueError("candidate must belong to the requested opportunity")
            if self.context_mode == ContextMode.CLOSED and (
                self.candidate.course_source_ids or self.candidate.citations
            ):
                raise ValueError("CLOSED result cannot contain course citations")
        if self.status == "READY" and self.candidate is None:
            raise ValueError("READY result requires a candidate")
        if self.status != "READY" and self.candidate is not None:
            raise ValueError("failed result cannot expose an unvalidated candidate")
        return self


class QuestionScores(StrictModel):
    groundedness: Score
    anchor_sufficiency: Score
    criterion_relevance: Score
    answerability: Score
    cognitive_demand: Score
    submission_specificity: Score
    clarity: Score
    accessibility: Score
    discriminative_potential: Score
    guide_observability: Score


class QuestionSemanticReview(StrictModel):
    candidate_id: Id
    decision: ReviewDecision
    critical_failure_codes: list[str] = Field(default_factory=list)
    scores: QuestionScores
    estimated_difficulty: DifficultyBand
    estimated_minutes: int = Field(ge=1, le=60)
    confidence: Score
    justifications: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[Id] = Field(default_factory=list, max_length=50)
    source_ids: list[Id] = Field(default_factory=list, max_length=50)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class QuestionReviewResult(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    submission_id: Id
    opportunity_id: Id
    status: Literal["READY", "NEEDS_REVIEW", "TECHNICAL_FAILURE"] = "READY"
    review: QuestionSemanticReview | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def review_matches_status(self) -> "QuestionReviewResult":
        if self.status == "READY" and self.review is None:
            raise ValueError("READY review result requires a review")
        return self


class SelectedQuestion(StrictModel):
    question_id: Id
    source_candidate_id: Id
    opportunity_id: Id
    opportunity_template_id: Id
    dimension_id: Id
    variant_id: Id
    cognitive_operation: CognitiveOperation
    response_format: ResponseFormat
    difficulty: DifficultyBand
    estimated_minutes: int = Field(ge=1, le=60)
    question_text: Annotated[str, Field(min_length=5, max_length=4000)]
    anchor: Anchor
    evidence_ids: Annotated[list[Id], Field(min_length=1)]
    course_source_ids: list[Id] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list, max_length=50)
    choices: list[ChoiceOption] = Field(default_factory=list)
    student_justification_required: bool = False
    preliminary_guide: GuideDraft
    planning_score: Score

    @model_validator(mode="after")
    def selected_question_is_consistent(self) -> "SelectedQuestion":
        anchor_ids = {fragment.evidence_id for fragment in self.anchor.fragments}
        if not anchor_ids.issubset(set(self.evidence_ids)):
            raise ValueError("anchor evidence must be included in evidence_ids")
        cited_source_ids = {citation.source_id for citation in self.citations}
        if set(self.course_source_ids) != cited_source_ids:
            raise ValueError("course_source_ids must exactly match citation source_ids")
        if self.response_format == ResponseFormat.CHOICE:
            if len(self.choices) < 3 or sum(x.is_best_answer for x in self.choices) != 1:
                raise ValueError("choice question requires >=3 options and one best answer")
            if any(
                not option.is_best_answer and not option.misconception
                for option in self.choices
            ):
                raise ValueError("every distractor requires a defendable misconception")
        elif self.choices:
            raise ValueError("choices allowed only for CHOICE")
        return self


class CoverageItem(StrictModel):
    dimension_id: Id
    available_variant_count: int = Field(ge=0)
    available_opportunity_count: int = Field(ge=0)
    selected_opportunity_count: int = Field(ge=0)
    reused_variant_count: int = Field(default=0, ge=0)
    evidence_unit_count: int = Field(ge=0)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class StructuredJustificationSummary(StrictModel):
    mode: StructuredJustificationMode
    required_question_ids: list[Id] = Field(default_factory=list, max_length=20)
    limited_evidence_notice_required: bool = False

    @model_validator(mode="after")
    def notice_matches_mode(self) -> "StructuredJustificationSummary":
        if self.mode == StructuredJustificationMode.NOT_REQUIRED:
            if self.required_question_ids:
                raise ValueError("NOT_REQUIRED cannot list required questions")
        elif (
            self.mode == StructuredJustificationMode.SELECTED
            and not self.required_question_ids
        ):
            raise ValueError("SELECTED requires at least one question")
        if self.limited_evidence_notice_required != (
            self.mode != StructuredJustificationMode.ALL
        ):
            raise ValueError(
                "limited evidence notice is required exactly when justification "
                "is not required for all questions"
            )
        return self


class Lineage(StrictModel):
    assignment_prompt_hashes: list[Hash]
    rubric_hashes: list[Hash]
    submission_hashes: list[Hash]
    blueprint_id: Id
    blueprint_version: PositiveInt
    parser_versions: dict[str, str]
    prompt_versions: dict[str, str]
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    model_snapshots: dict[str, str]
    policy_hash: Hash
    planner_version: str
    renderer_version: str


class Assessment(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    assessment_id: Id
    tenant_id: Id
    activity_id: Id
    submission_id: Id
    subject_ref: Id
    status: WorkflowStatus
    context_mode: ContextMode
    assessment_plan_id: Id
    question_count: int = Field(ge=1, le=20)
    questions: list[SelectedQuestion] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(default_factory=list)
    structured_justification: StructuredJustificationSummary
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    lineage: Lineage
    created_at: datetime
    approved_by: PrincipalId | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def assessment_is_publishable(self) -> "Assessment":
        question_ids = [question.question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("assessment question_ids must be unique")
        if self.status in {
            WorkflowStatus.READY,
            WorkflowStatus.NEEDS_REVIEW,
            WorkflowStatus.APPROVED,
            WorkflowStatus.PUBLISHED,
        } and len(self.questions) != self.question_count:
            raise ValueError("usable assessment requires exactly question_count questions")
        if self.context_mode == ContextMode.CLOSED and any(
            question.course_source_ids or question.citations
            for question in self.questions
        ):
            raise ValueError("CLOSED assessment cannot contain course citations")
        if self.status in {WorkflowStatus.APPROVED, WorkflowStatus.PUBLISHED}:
            if not self.questions:
                raise ValueError("approved assessment requires questions")
            if self.approved_by is None or self.approved_at is None:
                raise ValueError("approved assessment requires human approval metadata")
        if (self.approved_by is None) != (self.approved_at is None):
            raise ValueError("approved_by and approved_at must both be set or absent")
        required_question_ids = {
            question.question_id
            for question in self.questions
            if question.student_justification_required
        }
        if set(self.structured_justification.required_question_ids) != required_question_ids:
            raise ValueError("structured justification summary must match questions")
        all_question_ids = {question.question_id for question in self.questions}
        if (
            self.structured_justification.mode == StructuredJustificationMode.ALL
            and required_question_ids != all_question_ids
        ):
            raise ValueError("ALL requires justification for every question")
        if (
            self.structured_justification.mode
            == StructuredJustificationMode.NOT_REQUIRED
            and required_question_ids
        ):
            raise ValueError("NOT_REQUIRED cannot require a question justification")
        return self


class AssessmentVersionRef(StrictModel):
    assessment_id: Id
    assessment_version: PositiveInt


class BulkApprovalRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    request_id: Id
    tenant_id: Id
    actor_id: PrincipalId
    targets: Annotated[list[AssessmentVersionRef], Field(min_length=1, max_length=500)]
    explicit_confirmation: Literal[
        "CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS"
    ]
    requested_at: datetime

    @model_validator(mode="after")
    def targets_are_unique(self) -> "BulkApprovalRequest":
        refs = [(x.assessment_id, x.assessment_version) for x in self.targets]
        if len(refs) != len(set(refs)):
            raise ValueError("bulk approval targets must be unique")
        return self


class BulkApprovalExclusion(StrictModel):
    target: AssessmentVersionRef
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    message: Annotated[str, Field(min_length=3, max_length=1000)]
    requires_individual_review: Literal[True] = True


class BulkApprovalRecord(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    approval_id: Id
    request_id: Id
    tenant_id: Id
    actor_id: PrincipalId
    scope: Literal["SELECTED_ELIGIBLE_ASSESSMENTS"]
    approved_at: datetime
    requested_targets: Annotated[
        list[AssessmentVersionRef], Field(min_length=1, max_length=500)
    ]
    approved_targets: list[AssessmentVersionRef] = Field(
        default_factory=list, max_length=500
    )
    excluded_targets: list[BulkApprovalExclusion] = Field(
        default_factory=list, max_length=500
    )

    @model_validator(mode="after")
    def outcome_partitions_request(self) -> "BulkApprovalRecord":
        requested = {
            (x.assessment_id, x.assessment_version) for x in self.requested_targets
        }
        approved = {
            (x.assessment_id, x.assessment_version) for x in self.approved_targets
        }
        excluded = {
            (x.target.assessment_id, x.target.assessment_version)
            for x in self.excluded_targets
        }
        if approved.intersection(excluded):
            raise ValueError("a target cannot be both approved and excluded")
        if approved.union(excluded) != requested:
            raise ValueError("approved and excluded targets must partition the request")
        return self


class QuestionReviewAction(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    action_id: Id
    assessment_id: Id
    question_id: Id
    action: QuestionReviewActionType
    actor_id: PrincipalId
    occurred_at: datetime
    reason_code: str | None = Field(
        default=None, pattern=r"^[A-Z][A-Z0-9_]{2,63}$"
    )
    note: str | None = Field(default=None, max_length=2000)
    replacement: SelectedQuestion | None = None

    @model_validator(mode="after")
    def edit_requires_replacement(self) -> "QuestionReviewAction":
        if self.action == QuestionReviewActionType.EDIT and self.replacement is None:
            raise ValueError("EDIT review action requires replacement")
        if (
            self.action == QuestionReviewActionType.EDIT
            and self.replacement is not None
            and self.replacement.question_id != self.question_id
        ):
            raise ValueError("EDIT replacement must preserve question_id")
        if self.action != QuestionReviewActionType.EDIT and self.replacement is not None:
            raise ValueError("replacement is allowed only for EDIT")
        if self.action in {
            QuestionReviewActionType.REJECT,
            QuestionReviewActionType.REGENERATE,
        } and not self.reason_code:
            raise ValueError("REJECT/REGENERATE require reason_code")
        return self


class ModelCapabilities(StrictModel):
    input_modalities: Annotated[list[ModelInputModality], Field(min_length=1)]
    output_modalities: Annotated[list[ModelOutputModality], Field(min_length=1)]
    structured_outputs: bool
    max_context_tokens: int = Field(gt=0)
    supported_reasoning_efforts: Annotated[list[ReasoningEffort], Field(min_length=1)]
    supports_zero_data_retention: bool
    supported_regions: list[str] = Field(default_factory=list, max_length=100)


class ModelRoute(StrictModel):
    """Approved callable unit; routing resolves policy instead of choosing dynamically."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    route_id: Id
    task: str
    provider: Literal["openai", "anthropic", "google", "other"]
    model: Annotated[str, Field(min_length=1, max_length=255)]
    model_snapshot: Annotated[str, Field(min_length=1, max_length=255)]
    reasoning_effort: ReasoningEffort
    temperature: float = Field(ge=0.0, le=2.0)
    capabilities: ModelCapabilities
    retention_mode: Literal["DEFAULT", "MAM", "ZDR"]
    region: str | None = Field(default=None, max_length=100)
    max_cost_usd: float = Field(gt=0.0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    fallback_route_id: Id | None = None
    reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def route_is_callable(self) -> "ModelRoute":
        if self.reasoning_effort not in self.capabilities.supported_reasoning_efforts:
            raise ValueError("route reasoning_effort is not supported by the model")
        if (
            self.retention_mode == "ZDR"
            and not self.capabilities.supports_zero_data_retention
        ):
            raise ValueError("ZDR route requires a compatible model capability")
        if (
            self.region is not None
            and self.capabilities.supported_regions
            and self.region not in self.capabilities.supported_regions
        ):
            raise ValueError("route region is not supported by the model")
        return self


class ModelRouteResolution(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    resolution_id: Id
    task: str
    status: Literal["RESOLVED", "NEEDS_REVIEW", "BLOCKED"]
    required_input_modalities: Annotated[
        list[ModelInputModality], Field(min_length=1)
    ]
    required_output_modalities: Annotated[
        list[ModelOutputModality], Field(min_length=1)
    ]
    route: ModelRoute | None = None
    evaluated_route_ids: list[Id] = Field(default_factory=list, max_length=100)
    reason_codes: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=100,
        ),
    ]

    @model_validator(mode="after")
    def resolution_matches_status(self) -> "ModelRouteResolution":
        if self.status == "RESOLVED" and self.route is None:
            raise ValueError("RESOLVED requires a route")
        if self.status != "RESOLVED" and self.route is not None:
            raise ValueError("unresolved routing cannot expose a callable route")
        if self.route is not None:
            inputs = set(self.route.capabilities.input_modalities)
            outputs = set(self.route.capabilities.output_modalities)
            if not set(self.required_input_modalities).issubset(inputs):
                raise ValueError("resolved route lacks a required input modality")
            if not set(self.required_output_modalities).issubset(outputs):
                raise ValueError("resolved route lacks a required output modality")
        return self


class ModelCallLedger(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    model_call_id: Id
    tenant_id: Id
    job_id: Id
    stage: str
    prompt_id: str
    prompt_version: str
    prompt_hash: Hash
    input_bundle_hash: Hash
    schema_name: str
    schema_version_used: str
    route: ModelRoute
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)
    actual_cost_usd: float | None = Field(default=None, ge=0.0)
    result: Literal[
        "SCHEMA_VALID",
        "SCHEMA_INVALID",
        "SAFETY_BLOCK",
        "RATE_LIMIT",
        "TIMEOUT",
        "PROVIDER_ERROR",
    ]
    attempt: int = Field(ge=1, le=10)
    created_at: datetime


class EventActor(StrictModel):
    kind: Literal["USER", "SERVICE", "SYSTEM"]
    id: PrincipalId


class DomainEvent(StrictModel):
    """Versioned internal event envelope; payload shape is selected by event_type."""

    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    event_id: Id
    event_type: Annotated[
        str, Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    ]
    event_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    occurred_at: datetime
    tenant_id: Id
    aggregate_id: Id
    aggregate_version: PositiveInt
    actor: EventActor
    correlation_id: Id
    causation_id: Id | None = None
    payload: dict[str, Any]


class JobStatus(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    job_id: Id
    tenant_id: Id
    aggregate_id: Id
    stage: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "NEEDS_REVIEW"]
    progress: Score
    attempt: int = Field(ge=0)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SubmissionProcessingState(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    submission_id: Id
    activity_id: Id
    status: SubmissionProcessingStatus
    current_stage: str | None = Field(default=None, max_length=128)
    progress: Score
    active_job_id: Id | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    updated_at: datetime


class StageRun(StrictModel):
    """Durable, reusable execution of one deterministic application stage."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    stage_run_id: Id
    tenant_id: Id
    job_id: Id
    aggregate_id: Id
    stage: Annotated[
        str, Field(min_length=3, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    ]
    stage_key: Hash
    input_hash: Hash
    policy_hash: Hash
    component_version: Annotated[str, Field(min_length=1, max_length=128)]
    status: StageRunStatus
    attempt: int = Field(ge=1, le=10)
    retryable: bool = False
    failure_class: FailureClass | None = None
    output_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    output_hash: Hash | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=100)
    created_at: datetime
    started_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def lifecycle_is_consistent(self) -> "StageRun":
        timestamps = {
            "created_at": self.created_at,
            "started_at": self.started_at,
            "cancel_requested_at": self.cancel_requested_at,
            "finished_at": self.finished_at,
        }
        for name, value in timestamps.items():
            if value is not None:
                _require_utc(value, name)
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot precede created_at")
        if self.cancel_requested_at is not None and self.cancel_requested_at < self.created_at:
            raise ValueError("cancel_requested_at cannot precede created_at")
        if self.finished_at is not None:
            lower_bound = self.started_at or self.created_at
            if self.finished_at < lower_bound:
                raise ValueError("finished_at cannot precede stage execution")

        if (self.output_ref is None) != (self.output_hash is None):
            raise ValueError("output_ref and output_hash must both be set or absent")
        if self.output_ref is not None:
            _require_private_reference(self.output_ref, "output_ref")

        if self.status == StageRunStatus.QUEUED:
            if self.started_at or self.cancel_requested_at or self.finished_at:
                raise ValueError("QUEUED stage cannot have execution timestamps")
        elif self.status == StageRunStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("RUNNING stage requires started_at and no finished_at")
        else:
            if self.started_at is None or self.finished_at is None:
                raise ValueError("terminal stage requires started_at and finished_at")

        if self.status == StageRunStatus.SUCCEEDED:
            if self.output_ref is None:
                raise ValueError("SUCCEEDED stage requires a durable output reference")
            if self.failure_class is not None or self.retryable:
                raise ValueError("SUCCEEDED stage cannot expose failure state")
        elif self.status == StageRunStatus.FAILED:
            if self.failure_class is None or not self.diagnostics:
                raise ValueError("FAILED stage requires failure_class and diagnostics")
            if self.failure_class == FailureClass.CANCELLATION:
                raise ValueError("FAILED stage cannot use CANCELLATION failure class")
            if self.output_ref is not None:
                raise ValueError("FAILED stage cannot expose a reusable output")
        elif self.status == StageRunStatus.CANCELLED:
            if self.failure_class != FailureClass.CANCELLATION:
                raise ValueError("CANCELLED stage requires CANCELLATION failure class")
            if self.cancel_requested_at is None:
                raise ValueError("CANCELLED stage requires cancel_requested_at")
            if self.output_ref is not None or self.retryable:
                raise ValueError("CANCELLED stage cannot expose output or retryable state")
        elif self.failure_class is not None or self.retryable or self.output_ref is not None:
            raise ValueError("non-terminal stage cannot expose result or failure state")

        if self.retryable and self.failure_class not in {
            FailureClass.TRANSIENT,
            FailureClass.PROVIDER,
        }:
            raise ValueError("only transient/provider failures may be retryable")
        return self


class JobControlRecord(StrictModel):
    """Durable authorization and outcome for retry, cancel, or stage resume."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    control_id: Id
    tenant_id: Id
    job_id: Id
    aggregate_id: Id
    action: JobControlActionType
    status: JobControlStatus
    actor_id: PrincipalId
    source_attempt: int = Field(ge=0, le=10)
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    target_stage: str | None = Field(
        default=None,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]{2,127}$",
    )
    failure_class: FailureClass | None = None
    resulting_job_id: Id | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=100)
    requested_at: datetime
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def control_is_auditable(self) -> "JobControlRecord":
        _require_utc(self.requested_at, "requested_at")
        if self.decided_at is not None:
            _require_utc(self.decided_at, "decided_at")
            if self.decided_at < self.requested_at:
                raise ValueError("decided_at cannot precede requested_at")

        if self.action in {JobControlActionType.RETRY, JobControlActionType.RESUME}:
            if self.target_stage is None:
                raise ValueError("RETRY/RESUME require target_stage")
        elif self.target_stage is not None:
            raise ValueError("CANCEL cannot specify target_stage")

        if self.action == JobControlActionType.RETRY:
            if self.failure_class is None:
                raise ValueError("RETRY requires the classified source failure")
        elif self.failure_class is not None:
            raise ValueError("failure_class is allowed only for RETRY")

        if self.status == JobControlStatus.REQUESTED:
            if self.decided_at is not None or self.resulting_job_id is not None:
                raise ValueError("REQUESTED control cannot expose an outcome")
        elif self.status == JobControlStatus.REJECTED:
            if self.decided_at is None or self.resulting_job_id is not None:
                raise ValueError("REJECTED control requires decision without a new job")
            if not self.diagnostics:
                raise ValueError("REJECTED control requires diagnostics")
        else:
            if self.decided_at is None:
                raise ValueError("APPLIED control requires decided_at")
            if self.action in {
                JobControlActionType.RETRY,
                JobControlActionType.RESUME,
            }:
                if self.resulting_job_id is None or self.resulting_job_id == self.job_id:
                    raise ValueError("applied RETRY/RESUME requires a distinct resulting job")
            elif self.resulting_job_id is not None:
                raise ValueError("applied CANCEL does not create a new job")
            if (
                self.action == JobControlActionType.RETRY
                and self.failure_class
                not in {FailureClass.TRANSIENT, FailureClass.PROVIDER}
            ):
                raise ValueError("only transient/provider failures may be retried")
        return self


class CoverageTraceItem(StrictModel):
    submission_id: Id
    assessment_id: Id | None = None
    assessment_version: PositiveInt | None = None
    dimension_id: Id
    criterion_ids: list[Id] = Field(default_factory=list, max_length=100)
    variant_id: Id
    opportunity_id: Id
    evidence_ids: list[Id] = Field(default_factory=list, max_length=50)
    cognitive_operation: CognitiveOperation
    planning_role: CoveragePlanningRole
    outcome: CoverageOutcome
    reused_variant: bool = False
    failure_code: Annotated[
        str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    ] | None = None
    exclusion_reason_code: Annotated[
        str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    ] | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def trace_is_consistent(self) -> "CoverageTraceItem":
        if (self.assessment_id is None) != (self.assessment_version is None):
            raise ValueError("assessment_id and assessment_version must be paired")
        if len(self.criterion_ids) != len(set(self.criterion_ids)):
            raise ValueError("coverage criterion_ids must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("coverage evidence_ids must be unique")
        if self.planning_role in {
            CoveragePlanningRole.PRIMARY,
            CoveragePlanningRole.RESERVE,
        } and not self.evidence_ids:
            raise ValueError("planned opportunity requires evidence_ids")
        if self.planning_role == CoveragePlanningRole.EXCLUDED:
            if (
                self.outcome != CoverageOutcome.EXCLUDED
                or self.exclusion_reason_code is None
            ):
                raise ValueError("excluded opportunity requires outcome and reason")
        elif (
            self.outcome == CoverageOutcome.EXCLUDED
            or self.exclusion_reason_code is not None
        ):
            raise ValueError("exclusion fields are allowed only for EXCLUDED planning role")
        if (self.outcome == CoverageOutcome.FAILED) != (self.failure_code is not None):
            raise ValueError("failure_code is required exactly for FAILED outcome")
        return self


class CoverageReport(StrictModel):
    """Traceable coverage snapshot for one submission or an activity aggregate."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    report_id: Id
    tenant_id: Id
    activity_id: Id
    scope: CoverageScope
    submission_id: Id | None = None
    assessment_id: Id | None = None
    assessment_version: PositiveInt | None = None
    blueprint_id: Id
    blueprint_version: PositiveInt
    source_snapshot_hash: Hash
    summary: Annotated[list[CoverageItem], Field(min_length=1, max_length=500)]
    traces: list[CoverageTraceItem] = Field(default_factory=list, max_length=10_000)
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=500)
    generated_at: datetime

    @model_validator(mode="after")
    def report_is_complete(self) -> "CoverageReport":
        _require_utc(self.generated_at, "generated_at")
        if (self.assessment_id is None) != (self.assessment_version is None):
            raise ValueError("assessment_id and assessment_version must be paired")
        if self.scope == CoverageScope.SUBMISSION:
            if self.submission_id is None:
                raise ValueError("SUBMISSION coverage requires submission_id")
            if any(item.submission_id != self.submission_id for item in self.traces):
                raise ValueError("coverage trace belongs to another submission")
            if self.assessment_id is not None and any(
                item.assessment_id != self.assessment_id
                or item.assessment_version != self.assessment_version
                for item in self.traces
            ):
                raise ValueError("coverage trace belongs to another assessment version")
        elif self.submission_id is not None or self.assessment_id is not None:
            raise ValueError("ACTIVITY coverage cannot select one submission/assessment")

        trace_keys = [
            (item.submission_id, item.opportunity_id) for item in self.traces
        ]
        if len(trace_keys) != len(set(trace_keys)):
            raise ValueError("coverage traces must have unique submission/opportunity pairs")
        summary_ids = [item.dimension_id for item in self.summary]
        if len(summary_ids) != len(set(summary_ids)):
            raise ValueError("coverage summary dimension_ids must be unique")
        if {item.dimension_id for item in self.traces} - set(summary_ids):
            raise ValueError("every trace dimension requires a summary item")

        for item in self.summary:
            traces = [x for x in self.traces if x.dimension_id == item.dimension_id]
            expected = {
                "available_variant_count": len({x.variant_id for x in traces}),
                "available_opportunity_count": len(traces),
                "selected_opportunity_count": sum(
                    x.planning_role == CoveragePlanningRole.PRIMARY for x in traces
                ),
                "reused_variant_count": sum(x.reused_variant for x in traces),
                "evidence_unit_count": len(
                    {evidence_id for x in traces for evidence_id in x.evidence_ids}
                ),
            }
            if any(getattr(item, name) != value for name, value in expected.items()):
                raise ValueError("coverage summary counts must match traceable items")
        return self


class ExportArtifact(StrictModel):
    export_artifact_id: Id
    kind: ExportKind
    media_type: Annotated[str, Field(min_length=3, max_length=255)]
    object_key: Annotated[str, Field(min_length=1, max_length=1024)]
    sha256: Hash
    byte_size: int = Field(ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def artifact_is_private_and_typed(self) -> "ExportArtifact":
        _require_utc(self.created_at, "created_at")
        _require_private_reference(self.object_key, "object_key")
        expected_media_type = {
            ExportKind.ASSESSMENT_PDF: "application/pdf",
            ExportKind.ASSESSMENT_HTML: "text/html",
            ExportKind.GUIDE_PDF: "application/pdf",
            ExportKind.GUIDE_HTML: "text/html",
            ExportKind.COVERAGE_CSV: "text/csv",
            ExportKind.COVERAGE_JSON: "application/json",
            ExportKind.CANONICAL_JSON: "application/json",
        }[self.kind]
        if self.media_type != expected_media_type:
            raise ValueError("export media_type does not match kind")
        return self


class ExportRecord(StrictModel):
    """Durable export metadata; download capabilities are intentionally absent."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    export_id: Id
    tenant_id: Id
    activity_id: Id
    assessment_id: Id
    assessment_version: PositiveInt
    requested_by: PrincipalId
    requested_kinds: Annotated[list[ExportKind], Field(min_length=1, max_length=7)]
    status: ExportStatus
    assessment_snapshot_hash: Hash
    guide_snapshot_hash: Hash | None = None
    coverage_snapshot_hash: Hash | None = None
    renderer_version: Annotated[str, Field(min_length=1, max_length=128)]
    artifacts: list[ExportArtifact] = Field(default_factory=list, max_length=7)
    model_call_delta: Literal[0] = 0
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=100)
    requested_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def export_is_derived_and_complete(self) -> "ExportRecord":
        _require_utc(self.requested_at, "requested_at")
        if self.completed_at is not None:
            _require_utc(self.completed_at, "completed_at")
            if self.completed_at < self.requested_at:
                raise ValueError("completed_at cannot precede requested_at")
        if len(self.requested_kinds) != len(set(self.requested_kinds)):
            raise ValueError("requested export kinds must be unique")

        guide_kinds = {
            ExportKind.GUIDE_PDF,
            ExportKind.GUIDE_HTML,
            ExportKind.CANONICAL_JSON,
        }
        coverage_kinds = {ExportKind.COVERAGE_CSV, ExportKind.COVERAGE_JSON}
        if set(self.requested_kinds).intersection(guide_kinds) and not self.guide_snapshot_hash:
            raise ValueError("guide export requires guide_snapshot_hash")
        if (
            set(self.requested_kinds).intersection(coverage_kinds)
            and not self.coverage_snapshot_hash
        ):
            raise ValueError("coverage export requires coverage_snapshot_hash")

        artifact_ids = [item.export_artifact_id for item in self.artifacts]
        object_keys = [item.object_key for item in self.artifacts]
        artifact_kinds = [item.kind for item in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("export artifact IDs must be unique")
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("export object keys must be unique")
        if len(artifact_kinds) != len(set(artifact_kinds)):
            raise ValueError("an export record has at most one artifact per kind")

        if self.status == ExportStatus.QUEUED:
            if self.completed_at is not None or self.artifacts:
                raise ValueError("QUEUED export cannot expose completed artifacts")
        elif self.status == ExportStatus.READY:
            if self.completed_at is None:
                raise ValueError("READY export requires completed_at")
            if set(artifact_kinds) != set(self.requested_kinds):
                raise ValueError("READY export must contain every requested kind exactly once")
            if any(
                artifact.created_at < self.requested_at
                or artifact.created_at > self.completed_at
                for artifact in self.artifacts
            ):
                raise ValueError("export artifact timestamp is outside the render window")
        else:
            if self.completed_at is None or self.artifacts or not self.diagnostics:
                raise ValueError("FAILED export requires diagnostics and no artifacts")
        return self


class TechnicalMetricAggregate(StrictModel):
    job_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    latency_p50_ms: int = Field(ge=0)
    latency_p95_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)
    actual_cost_usd: float = Field(ge=0.0)

    @model_validator(mode="after")
    def totals_are_consistent(self) -> "TechnicalMetricAggregate":
        if self.succeeded_count + self.failed_count + self.cancelled_count > self.job_count:
            raise ValueError("terminal job counts cannot exceed job_count")
        if self.latency_p95_ms < self.latency_p50_ms:
            raise ValueError("latency p95 must be >= p50")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input tokens cannot exceed input tokens")
        return self


class QualityMetricAggregate(StrictModel):
    assessment_count: int = Field(ge=0)
    fail_closed_count: int = Field(ge=0)
    defect_count: int = Field(ge=0)
    exact_plan_count: int = Field(ge=0)
    replacement_count: int = Field(ge=0)

    @model_validator(mode="after")
    def assessment_counts_are_consistent(self) -> "QualityMetricAggregate":
        if self.fail_closed_count + self.assessment_count < self.exact_plan_count:
            raise ValueError("exact_plan_count exceeds observable outcomes")
        return self


class HumanReviewMetricAggregate(StrictModel):
    reviewed_question_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    edited_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    regenerated_count: int = Field(ge=0)
    review_seconds: int = Field(ge=0)


class StageMetricAggregate(StrictModel):
    stage: Annotated[
        str, Field(min_length=3, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    ]
    runs: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    retries: int = Field(ge=0)
    latency_p50_ms: int = Field(ge=0)
    latency_p95_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def stage_counts_are_consistent(self) -> "StageMetricAggregate":
        if self.succeeded + self.failed + self.cancelled > self.runs:
            raise ValueError("terminal stage counts cannot exceed runs")
        if self.latency_p95_ms < self.latency_p50_ms:
            raise ValueError("stage latency p95 must be >= p50")
        return self


class ModelMetricAggregate(StrictModel):
    route_id: Id
    provider: Literal["openai", "anthropic", "google", "other"]
    model: Annotated[str, Field(min_length=1, max_length=255)]
    model_snapshot: Annotated[str, Field(min_length=1, max_length=255)]
    call_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_p50_ms: int = Field(ge=0)
    latency_p95_ms: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)
    actual_cost_usd: float = Field(ge=0.0)

    @model_validator(mode="after")
    def model_counts_are_consistent(self) -> "ModelMetricAggregate":
        if self.schema_valid_count + self.error_count > self.call_count:
            raise ValueError("model result counts cannot exceed call_count")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached model tokens cannot exceed input tokens")
        if self.latency_p95_ms < self.latency_p50_ms:
            raise ValueError("model latency p95 must be >= p50")
        return self


class ExperimentMetrics(StrictModel):
    """Content-free aggregate metrics for one experimental activity window."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    metrics_id: Id
    tenant_id: Id
    activity_id: Id
    technical: TechnicalMetricAggregate
    quality: QualityMetricAggregate
    human_review: HumanReviewMetricAggregate
    by_stage: list[StageMetricAggregate] = Field(default_factory=list, max_length=100)
    by_model: list[ModelMetricAggregate] = Field(default_factory=list, max_length=100)
    window_start: datetime
    window_end: datetime
    generated_at: datetime

    @model_validator(mode="after")
    def dimensions_are_unique(self) -> "ExperimentMetrics":
        for name, value in {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "generated_at": self.generated_at,
        }.items():
            _require_utc(value, name)
        if self.window_end < self.window_start:
            raise ValueError("metrics window_end cannot precede window_start")
        if self.generated_at < self.window_end:
            raise ValueError("metrics generated_at cannot precede window_end")
        stages = [item.stage for item in self.by_stage]
        if len(stages) != len(set(stages)):
            raise ValueError("stage metric dimensions must be unique")
        models = [(item.route_id, item.model_snapshot) for item in self.by_model]
        if len(models) != len(set(models)):
            raise ValueError("model metric dimensions must be unique")
        return self


class FeedbackEvent(StrictModel):
    """Governed teacher feedback; never authorizes training or academic action."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    feedback_id: Id
    tenant_id: Id
    activity_id: Id
    assessment_id: Id | None = None
    assessment_version: PositiveInt | None = None
    question_id: Id | None = None
    target_type: FeedbackTargetType
    actor_id: PrincipalId
    category: FeedbackCategory
    rating: FeedbackRating
    comment: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    training_use_allowed: Literal[False] = False
    public_dataset_use_allowed: Literal[False] = False
    academic_decision_use_allowed: Literal[False] = False
    created_at: datetime

    @model_validator(mode="after")
    def target_and_governance_are_explicit(self) -> "FeedbackEvent":
        _require_utc(self.created_at, "created_at")
        if (self.assessment_id is None) != (self.assessment_version is None):
            raise ValueError("assessment_id and assessment_version must be paired")
        if self.target_type == FeedbackTargetType.ACTIVITY:
            if self.assessment_id is not None or self.question_id is not None:
                raise ValueError("ACTIVITY feedback cannot target assessment/question")
        elif self.target_type == FeedbackTargetType.ASSESSMENT:
            if self.assessment_id is None or self.question_id is not None:
                raise ValueError("ASSESSMENT feedback requires only assessment target")
        elif self.assessment_id is None or self.question_id is None:
            raise ValueError("QUESTION feedback requires assessment and question targets")
        return self


class QuestionReviewActionRecord(StrictModel):
    """Versioned outcome around the unchanged v1.1 QuestionReviewAction root."""

    schema_version: Stage2SchemaVersion = CONTRACT_VERSION
    record_id: Id
    tenant_id: Id
    activity_id: Id
    submission_id: Id
    assessment_id: Id
    assessment_version_before: PositiveInt
    assessment_version_after: PositiveInt | None = None
    action: QuestionReviewAction
    status: QuestionReviewRecordStatus
    revalidation_status: RevalidationStatus
    before_question: SelectedQuestion
    after_question: SelectedQuestion | None = None
    lineage_before: Lineage
    lineage_after: Lineage | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=100)
    recorded_at: datetime

    @model_validator(mode="after")
    def revision_is_versioned(self) -> "QuestionReviewActionRecord":
        _require_utc(self.recorded_at, "recorded_at")
        _require_utc(self.action.occurred_at, "action.occurred_at")
        if self.recorded_at < self.action.occurred_at:
            raise ValueError("recorded_at cannot precede action occurrence")
        if self.action.assessment_id != self.assessment_id:
            raise ValueError("action belongs to another assessment")
        if self.before_question.question_id != self.action.question_id:
            raise ValueError("before question does not match action question_id")

        mutable_action = self.action.action in {
            QuestionReviewActionType.EDIT,
            QuestionReviewActionType.REGENERATE,
        }
        if self.status == QuestionReviewRecordStatus.FAILED:
            if not mutable_action:
                raise ValueError("only EDIT/REGENERATE may record failed revalidation")
            if self.revalidation_status != RevalidationStatus.FAILED:
                raise ValueError("failed review action requires FAILED revalidation")
            if any(
                value is not None
                for value in (
                    self.assessment_version_after,
                    self.after_question,
                    self.lineage_after,
                )
            ) or not self.diagnostics:
                raise ValueError("failed review action cannot expose a resulting version")
            return self

        if self.action.action == QuestionReviewActionType.ACCEPT:
            if (
                self.assessment_version_after != self.assessment_version_before
                or self.after_question != self.before_question
                or self.lineage_after != self.lineage_before
                or self.revalidation_status != RevalidationStatus.NOT_REQUIRED
            ):
                raise ValueError("ACCEPT must preserve version, question, and lineage")
            return self

        if self.assessment_version_after != self.assessment_version_before + 1:
            raise ValueError("mutating review action must create the next assessment version")
        if self.lineage_after is None:
            raise ValueError("mutating review action requires resulting lineage")

        if self.action.action == QuestionReviewActionType.REJECT:
            if self.after_question is not None:
                raise ValueError("REJECT cannot expose an accepted after question")
            if self.revalidation_status != RevalidationStatus.NOT_REQUIRED:
                raise ValueError("REJECT does not run semantic revalidation")
            return self

        if self.after_question is None:
            raise ValueError("EDIT/REGENERATE require an after question when applied")
        if self.after_question.question_id != self.action.question_id:
            raise ValueError("review replacement must preserve question_id")
        if self.revalidation_status != RevalidationStatus.PASSED:
            raise ValueError("applied EDIT/REGENERATE requires passed revalidation")
        if (
            self.action.action == QuestionReviewActionType.EDIT
            and self.action.replacement != self.after_question
        ):
            raise ValueError("EDIT after question must equal canonical action replacement")
        if (
            self.action.action == QuestionReviewActionType.REGENERATE
            and self.after_question.opportunity_id == self.before_question.opportunity_id
        ):
            raise ValueError("REGENERATE must use a distinct reserve opportunity")
        return self


class ProblemDetail(StrictModel):
    type: str = "about:blank"
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str | None = None
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    trace_id: str | None = None
    retryable: bool = False
    fields: dict[str, list[str]] = Field(default_factory=dict)


class ActivitySpecRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_config: ActivityConfig
    prompt_evidence: Annotated[list[EvidenceUnit], Field(min_length=1, max_length=500)]


class RubricNormalizeRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_spec: ActivitySpec
    rubric_evidence: Annotated[list[EvidenceUnit], Field(min_length=1, max_length=500)]


class AmbiguityTriageRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    activity_spec: ActivitySpec
    rubric_spec: RubricSpec | None = None
    rule_findings: list[Diagnostic] = Field(default_factory=list, max_length=100)


class BlueprintBuildRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    target_blueprint_id: Id
    target_blueprint_version: PositiveInt
    activity_spec: ActivitySpec
    rubric_spec: RubricSpec | None = None
    resolved_decisions: list[PolicyDecision] = Field(default_factory=list, max_length=100)
    blueprint_policy: BlueprintPolicy

    @model_validator(mode="after")
    def decisions_are_self_contained(self) -> "BlueprintBuildRequest":
        _resolved_decisions_are_self_contained(self.resolved_decisions)
        return self


class BlueprintReviewRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    blueprint: AssessmentBlueprint
    activity_spec: ActivitySpec
    rubric_spec: RubricSpec | None = None
    resolved_decisions: list[PolicyDecision] = Field(default_factory=list, max_length=100)
    blueprint_policy: BlueprintPolicy

    @model_validator(mode="after")
    def decisions_are_self_contained(self) -> "BlueprintReviewRequest":
        _resolved_decisions_are_self_contained(self.resolved_decisions)
        return self


class EvidenceMapRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    blueprint: AssessmentBlueprint
    evidence_bundle: EvidenceBundle


class QuestionBuildRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    target_candidate_id: Id
    plan: AssessmentPlan
    opportunity: QuestionOpportunity
    evidence_bundle: EvidenceBundle
    generation_policy: QuestionGenerationPolicy
    avoid: list[RejectedQuestionFingerprint] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def request_matches_plan(self) -> "QuestionBuildRequest":
        allowed = set(self.plan.selected_opportunity_ids).union(
            self.plan.reserve_opportunity_ids
        )
        if self.plan.status != "READY":
            raise ValueError("question generation requires a READY plan")
        if self.opportunity.opportunity_id not in allowed:
            raise ValueError("opportunity is not authorized by the assessment plan")
        if self.opportunity.submission_id != self.plan.submission_id:
            raise ValueError("opportunity and plan submissions do not match")
        if self.evidence_bundle.submission_id != self.plan.submission_id:
            raise ValueError("evidence bundle and plan submissions do not match")
        return self


class QuestionReviewRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    generation_result: QuestionGenerationResult
    opportunity: QuestionOpportunity
    evidence_bundle: EvidenceBundle
    validation_policy: QuestionValidationPolicy

    @model_validator(mode="after")
    def review_matches_opportunity(self) -> "QuestionReviewRequest":
        if self.generation_result.opportunity_id != self.opportunity.opportunity_id:
            raise ValueError("generation result and opportunity do not match")
        return self


class GuideBuildRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    guide_id: Id
    assessment: Assessment
    evidence_bundle: EvidenceBundle


class SchemaValidationIssue(StrictModel):
    path: Annotated[str, Field(min_length=1, max_length=1000)]
    error_type: Annotated[str, Field(min_length=1, max_length=200)]
    message: Annotated[str, Field(min_length=1, max_length=1000)]


class SchemaRepairRequest(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    target_schema_name: Annotated[str, Field(min_length=3, max_length=128)]
    invalid_output: Any
    validation_issues: Annotated[list[SchemaValidationIssue], Field(min_length=1, max_length=100)]


class SchemaRepairResult(StrictModel):
    schema_version: SchemaVersion = LEGACY_SCHEMA_VERSION
    target_schema_name: Annotated[str, Field(min_length=3, max_length=128)]
    repair_status: RepairStatus
    repaired_output: dict[str, Any] | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def repair_result_is_consistent(self) -> "SchemaRepairResult":
        if self.repair_status == RepairStatus.REPAIRED and self.repaired_output is None:
            raise ValueError("REPAIRED requires repaired_output")
        if self.repair_status == RepairStatus.UNREPAIRABLE and self.repaired_output is not None:
            raise ValueError("UNREPAIRABLE cannot include repaired_output")
        return self


CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    Diagnostic,
    ArtifactRef,
    EvidenceUnit,
    CoursePassage,
    SourceCitation,
    EvidenceBundle,
    TrustedPromptContext,
    ModelTaskEnvelope,
    ActivityConfig,
    ActivitySpec,
    RubricSpec,
    AmbiguityReport,
    PolicyDecision,
    AssessmentPlanningPolicy,
    BlueprintPolicy,
    QuestionGenerationPolicy,
    QuestionValidationPolicy,
    AssessmentBlueprint,
    BlueprintReview,
    EvidenceMapPatch,
    AssessmentPlan,
    QuestionGenerationResult,
    QuestionReviewResult,
    EvaluationGuide,
    Assessment,
    CoverageReport,
    QuestionReviewAction,
    QuestionReviewActionRecord,
    BulkApprovalRequest,
    BulkApprovalRecord,
    ExportRecord,
    ExperimentMetrics,
    FeedbackEvent,
    ModelRoute,
    ModelRouteResolution,
    ModelCallLedger,
    DomainEvent,
    JobStatus,
    StageRun,
    JobControlRecord,
    SubmissionProcessingState,
    ProblemDetail,
    ActivitySpecRequest,
    RubricNormalizeRequest,
    AmbiguityTriageRequest,
    BlueprintBuildRequest,
    BlueprintReviewRequest,
    EvidenceMapRequest,
    QuestionBuildRequest,
    QuestionReviewRequest,
    GuideBuildRequest,
    SchemaRepairRequest,
    SchemaRepairResult,
)


def build_schema_bundle() -> dict[str, Any]:
    """Generate the canonical JSON Schema bundle from the Pydantic roots."""

    from pydantic.json_schema import models_json_schema

    root_schemas, definitions = models_json_schema(
        [(model, "validation") for model in CONTRACT_MODELS],
        title="Comprehension Verification Assessment Contracts",
    )
    roots = {
        model.__name__: root_schemas[(model, "validation")]
        for model in CONTRACT_MODELS
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://schemas.evaluaciones-personalizadas.local/"
            f"assessment-contracts/{CONTRACT_VERSION}"
        ),
        "title": "Comprehension Verification Assessment Contracts",
        "version": CONTRACT_VERSION,
        "roots": roots,
        "$defs": definitions["$defs"],
    }


def export_schema(path: str) -> None:
    import json
    from pathlib import Path

    Path(path).write_text(
        json.dumps(build_schema_bundle(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export the canonical contract bundle")
    parser.add_argument("--schema", required=True, help="output JSON Schema path")
    args = parser.parse_args()
    export_schema(args.schema)
