"""Durable Stage 1/2 repository backed by PostgreSQL or SQLite in tests.

Only JSON snapshots of canonical contracts are stored here; the contract
classes remain defined exclusively in ``specification/models_v1.1(1).py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    cast,
    create_engine,
    delete,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from ..canonical import canonical_hash, stable_id
from ..contracts import models as m
from ..provider_authorization import (
    SYNTHETIC_PROVIDER_AUTHORIZATION_VERSION,
    SYNTHETIC_PROVIDER_CLAIM_VERSION,
    SyntheticProviderAuthorizationSpec,
    SyntheticProviderGrant,
)


IDEMPOTENCY_CAPABILITY_CONSTRAINT = "ck_idempotency_keys_safe_response"
STAGE2_SUBMISSION_CONSTRAINT = "uq_submissions_tenant_activity_subject"
STAGE2_JOB_CONTROL_CONSTRAINT = "ck_jobs_control_state"
STAGE2_CONTINUATION_CONSTRAINT = "uq_job_control_records_source_attempt"
QUESTION_ACTION_DESCRIPTOR_STAGE = "QUESTION_ACTION_DESCRIPTOR"
BLUEPRINT_REVIEW_DESCRIPTOR_STAGE = "BLUEPRINT_REVIEW_DESCRIPTOR"

JOB_CONTROL_STATES = frozenset({"ACTIVE", "CANCEL_REQUESTED", "CANCELLED"})
JOB_FAILURE_CLASSES = frozenset(
    {
        "TRANSIENT",
        "PERMANENT",
        "SECURITY",
        "VALIDATION",
        "PRECONDITION",
        "PROVIDER",
        "CANCELLATION",
    }
)
RETRYABLE_JOB_FAILURE_CLASSES = frozenset({"TRANSIENT", "PROVIDER"})
MAX_JOB_ATTEMPTS = 3


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkspaceRoleRow(Base):
    __tablename__ = "workspace_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    can_approve_assessments: Mapped[bool] = mapped_column(Boolean, default=False)


class ActivityRow(Base):
    __tablename__ = "activities"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(64), default="DRAFT")
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    blueprint_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "activity_id",
            "scope_key",
            "role",
            name="uq_artifacts_role_per_scope",
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str] = mapped_column(String(128), index=True)
    submission_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scope_key: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(512))
    object_key: Mapped[str] = mapped_column(String(1024), unique=True)
    declared_media_type: Mapped[str] = mapped_column(String(255))
    expected_byte_size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ActivitySpecRow(Base):
    __tablename__ = "activity_specs"
    activity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class RubricSpecRow(Base):
    __tablename__ = "rubric_specs"
    activity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class AmbiguityRow(Base):
    __tablename__ = "ambiguity_reports"
    activity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "activity_id", "issue_id", name="uq_policy_decision_issue"
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str] = mapped_column(String(128), index=True)
    issue_id: Mapped[str] = mapped_column(String(128))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BlueprintRow(Base):
    __tablename__ = "blueprints"
    __table_args__ = (UniqueConstraint("activity_id", "version"),)
    row_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str] = mapped_column(String(128), index=True)
    blueprint_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    etag: Mapped[str] = mapped_column(String(80), unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SubmissionRow(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "activity_id",
            "subject_ref",
            name=STAGE2_SUBMISSION_CONSTRAINT,
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str] = mapped_column(String(128), index=True)
    subject_ref: Mapped[str] = mapped_column(String(128))
    blueprint_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    active_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvidenceRow(Base):
    __tablename__ = "evidence_units"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    submission_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class EvidenceMapRow(Base):
    __tablename__ = "evidence_maps"
    submission_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class AssessmentPlanRow(Base):
    __tablename__ = "assessment_plans"
    submission_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class GeneratedQuestionRow(Base):
    __tablename__ = "generated_questions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    submission_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class QuestionReviewRow(Base):
    __tablename__ = "question_reviews"
    question_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    submission_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class AssessmentRow(Base):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("submission_id", "version"),)
    row_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    submission_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(64))
    etag: Mapped[str] = mapped_column(String(80), unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GuideRow(Base):
    __tablename__ = "evaluation_guides"
    guide_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    submission_id: Mapped[str] = mapped_column(String(128), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "control_state in ('ACTIVE', 'CANCEL_REQUESTED', 'CANCELLED')",
            name=STAGE2_JOB_CONTROL_CONSTRAINT,
        ),
        CheckConstraint(
            "failure_class is null or failure_class in "
            "('TRANSIENT', 'PERMANENT', 'SECURITY', 'VALIDATION', "
            "'PRECONDITION', 'PROVIDER', 'CANCELLATION')",
            name="ck_jobs_failure_class",
        ),
        CheckConstraint(
            "max_attempts between 1 and 10",
            name="ck_jobs_max_attempts",
        ),
        CheckConstraint(
            "control_state != 'CANCELLED' or "
            "(status = 'FAILED' and failure_class = 'CANCELLATION' "
            "and cancelled_at is not null)",
            name="ck_jobs_cancelled_projection",
        ),
        Index(
            "ix_jobs_claim_eligible",
            "status",
            "control_state",
            "next_attempt_at",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    control_state: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=MAX_JOB_ATTEMPTS)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resume_from_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyntheticProviderAuthorizationRow(Base):
    """Append-only server attestation for one exact synthetic job claim."""

    __tablename__ = "synthetic_provider_authorizations"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_synthetic_provider_authorization_job"),
        UniqueConstraint(
            "authorization_hash",
            name="uq_synthetic_provider_authorization_hash",
        ),
        CheckConstraint(
            "expected_claim_attempt between 1 and 10",
            name="ck_synthetic_provider_authorization_attempt",
        ),
        CheckConstraint(
            "max_requests between 1 and 64",
            name="ck_synthetic_provider_authorization_requests",
        ),
        CheckConstraint(
            "max_cost_usd between 0.01 and 10.0",
            name="ck_synthetic_provider_authorization_cost",
        ),
        CheckConstraint(
            "classification = 'SYNTHETIC_ONLY_NO_STUDENT_DATA'",
            name="ck_synthetic_provider_authorization_classification",
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    job_kind: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    expected_claim_attempt: Mapped[int] = mapped_column(Integer)
    artifact_hashes: Mapped[list[str]] = mapped_column(JSON)
    candidate_sha: Mapped[str] = mapped_column(String(40))
    boundary_hash: Mapped[str] = mapped_column(String(71))
    route_profile: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    secret_version_resource: Mapped[str] = mapped_column(String(512))
    max_requests: Mapped[int] = mapped_column(Integer)
    max_cost_usd: Mapped[float] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(128))
    authorization_hash: Mapped[str] = mapped_column(String(71))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyntheticProviderClaimRow(Base):
    """Append-only exactly-once consumption fact for an authorization."""

    __tablename__ = "synthetic_provider_claims"
    __table_args__ = (
        UniqueConstraint(
            "authorization_id", name="uq_synthetic_provider_claim_authorization"
        ),
        UniqueConstraint("job_id", name="uq_synthetic_provider_claim_job"),
        CheckConstraint(
            "claim_attempt between 1 and 10",
            name="ck_synthetic_provider_claim_attempt",
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(String(128), index=True)
    authorization_hash: Mapped[str] = mapped_column(String(71))
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    claim_attempt: Mapped[int] = mapped_column(Integer)
    candidate_sha: Mapped[str] = mapped_column(String(40))
    boundary_hash: Mapped[str] = mapped_column(String(71))
    schema_version: Mapped[str] = mapped_column(String(128))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StageRunRow(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "stage_key",
            "attempt",
            name="uq_stage_runs_job_key_attempt",
        ),
        CheckConstraint(
            "failure_class is null or failure_class in "
            "('TRANSIENT', 'PERMANENT', 'SECURITY', 'VALIDATION', "
            "'PRECONDITION', 'PROVIDER', 'CANCELLATION')",
            name="ck_stage_runs_failure_class",
        ),
        Index(
            "uq_stage_runs_succeeded_stage_key",
            "stage_key",
            unique=True,
            postgresql_where=text(
                "status = 'SUCCEEDED' and component_version is not null "
                "and output_hash is not null"
            ),
            sqlite_where=text(
                "status = 'SUCCEEDED' and component_version is not null "
                "and output_hash is not null"
            ),
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str] = mapped_column(String(128))
    stage_key: Mapped[str] = mapped_column(String(71))
    status: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_hash: Mapped[str] = mapped_column(String(71))
    policy_hash: Mapped[str] = mapped_column(String(71))
    component_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resumed_from_stage_run_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelCallRow(Base):
    __tablename__ = "model_calls"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str] = mapped_column(String(128))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ExportRow(Base):
    __tablename__ = "exports"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    assessment_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assessment_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessment_snapshot_hash: Mapped[str | None] = mapped_column(
        String(71), nullable=True
    )
    renderer_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_kinds: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    guide_snapshot_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    coverage_snapshot_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuestionReviewActionRow(Base):
    __tablename__ = "question_review_actions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str] = mapped_column(String(128), index=True)
    assessment_id: Mapped[str] = mapped_column(String(128), index=True)
    assessment_version_before: Mapped[int] = mapped_column(Integer)
    assessment_version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submission_id: Mapped[str] = mapped_column(String(128), index=True)
    question_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    revalidation_status: Mapped[str] = mapped_column(String(32))
    before_snapshot_hash: Mapped[str] = mapped_column(String(71))
    after_snapshot_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeedbackEventRow(Base):
    __tablename__ = "feedback_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_id: Mapped[str] = mapped_column(String(128), index=True)
    assessment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assessment_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(128), index=True)
    rating: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobControlRecordRow(Base):
    __tablename__ = "job_control_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "source_attempt",
            name=STAGE2_CONTINUATION_CONSTRAINT,
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    resulting_job_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    source_attempt: Mapped[int] = mapped_column(Integer)
    target_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BulkApprovalRequestRow(Base):
    __tablename__ = "bulk_approval_requests"
    __table_args__ = (
        CheckConstraint("target_count between 1 and 500", name="ck_bulk_request_count"),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    target_count: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BulkApprovalRecordRow(Base):
    __tablename__ = "bulk_approval_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_bulk_record_request"),
        CheckConstraint(
            "approved_count >= 0 and excluded_count >= 0",
            name="ck_bulk_record_counts",
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    approved_count: Mapped[int] = mapped_column(Integer)
    excluded_count: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(128))
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(71))
    # NULL means that this key has been atomically reserved and the first
    # request is still executing. Capabilities such as signed URLs are never
    # stored here; the API persists only a canonical replay descriptor.
    response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: utc_now() + timedelta(days=1),
    )


_STAGE2_APPEND_ONLY_TABLES = (
    "job_control_records",
    "question_review_actions",
    "feedback_events",
    "bulk_approval_requests",
    "bulk_approval_records",
    "synthetic_provider_authorizations",
    "synthetic_provider_claims",
)

_POSTGRES_REQUIRED_COLUMNS = frozenset(
    {
        ("submissions", "tenant_id"),
        ("submissions", "activity_id"),
        ("submissions", "subject_ref"),
        ("jobs", "control_state"),
        ("jobs", "failure_class"),
        ("jobs", "max_attempts"),
        ("jobs", "next_attempt_at"),
        ("jobs", "resume_from_stage"),
        ("jobs", "cancel_requested_at"),
        ("jobs", "cancel_requested_by"),
        ("jobs", "cancelled_at"),
        ("stage_runs", "component_version"),
        ("stage_runs", "output_hash"),
        ("stage_runs", "failure_class"),
        ("stage_runs", "next_attempt_at"),
        ("stage_runs", "resumed_from_stage_run_id"),
        ("exports", "activity_id"),
        ("exports", "assessment_version"),
        ("exports", "assessment_snapshot_hash"),
        ("exports", "renderer_version"),
        ("exports", "requested_by"),
        ("exports", "requested_kinds"),
        ("exports", "guide_snapshot_hash"),
        ("exports", "coverage_snapshot_hash"),
        ("exports", "completed_at"),
        ("exports", "data"),
        ("idempotency_keys", "expires_at"),
    }
    | {
        (table_name, column.name)
        for table_name in _STAGE2_APPEND_ONLY_TABLES
        for column in Base.metadata.tables[table_name].columns
    }
)

# PostgreSQL ``contype`` values: c = CHECK and u = UNIQUE.
_POSTGRES_REQUIRED_CONSTRAINTS = {
    ("idempotency_keys", IDEMPOTENCY_CAPABILITY_CONSTRAINT): "c",
    ("submissions", STAGE2_SUBMISSION_CONSTRAINT): "u",
    ("jobs", STAGE2_JOB_CONTROL_CONSTRAINT): "c",
    ("jobs", "ck_jobs_failure_class"): "c",
    ("jobs", "ck_jobs_max_attempts"): "c",
    ("jobs", "ck_jobs_cancelled_projection"): "c",
    ("stage_runs", "uq_stage_runs_job_key_attempt"): "u",
    ("stage_runs", "ck_stage_runs_failure_class"): "c",
    ("job_control_records", STAGE2_CONTINUATION_CONSTRAINT): "u",
    ("bulk_approval_requests", "ck_bulk_request_count"): "c",
    ("bulk_approval_records", "uq_bulk_record_request"): "u",
    ("bulk_approval_records", "ck_bulk_record_counts"): "c",
    (
        "synthetic_provider_authorizations",
        "uq_synthetic_provider_authorization_job",
    ): "u",
    (
        "synthetic_provider_authorizations",
        "uq_synthetic_provider_authorization_hash",
    ): "u",
    (
        "synthetic_provider_authorizations",
        "ck_synthetic_provider_authorization_attempt",
    ): "c",
    (
        "synthetic_provider_authorizations",
        "ck_synthetic_provider_authorization_requests",
    ): "c",
    (
        "synthetic_provider_authorizations",
        "ck_synthetic_provider_authorization_cost",
    ): "c",
    (
        "synthetic_provider_authorizations",
        "ck_synthetic_provider_authorization_classification",
    ): "c",
    (
        "synthetic_provider_claims",
        "uq_synthetic_provider_claim_authorization",
    ): "u",
    ("synthetic_provider_claims", "uq_synthetic_provider_claim_job"): "u",
    ("synthetic_provider_claims", "ck_synthetic_provider_claim_attempt"): "c",
}

# These indexes participate in claim ordering and verified cross-job reuse.
_POSTGRES_REQUIRED_INDEXES = {
    ("jobs", "ix_jobs_claim_eligible"): False,
    ("stage_runs", "uq_stage_runs_succeeded_stage_key"): True,
    ("idempotency_keys", "ix_idempotency_keys_expires_at"): False,
}

_POSTGRES_POLICY_QUAL = "cva_is_workspace_member((tenant_id)::text)"


def _postgres_surface_is_ready(
    *,
    relations: dict[str, bool],
    columns: set[tuple[str, str]],
    constraints: dict[tuple[str, str], str],
    indexes: dict[tuple[str, str], tuple[bool, bool, bool]],
    triggers: dict[tuple[str, str], tuple[str, int, str]],
    policies: dict[
        tuple[str, str], tuple[str, bool, bool, int, str | None]
    ],
) -> bool:
    if any(relations.get(table_name) is not True for table_name in _STAGE2_APPEND_ONLY_TABLES):
        return False
    if not _POSTGRES_REQUIRED_COLUMNS.issubset(columns):
        return False
    if any(
        constraints.get(key) != constraint_type
        for key, constraint_type in _POSTGRES_REQUIRED_CONSTRAINTS.items()
    ):
        return False
    for key, must_be_unique in _POSTGRES_REQUIRED_INDEXES.items():
        index = indexes.get(key)
        if index is None:
            return False
        is_unique, is_valid, is_ready = index
        if is_unique is not must_be_unique or not is_valid or not is_ready:
            return False
    for table_name in _STAGE2_APPEND_ONLY_TABLES:
        trigger = triggers.get((table_name, f"{table_name}_are_append_only"))
        if trigger is None:
            return False
        function_name, trigger_type, enabled = trigger
        # 27 = ROW + BEFORE + UPDATE + DELETE, with no INSERT/TRUNCATE event.
        if function_name != "cva_reject_mutation" or trigger_type != 27:
            return False
        if enabled not in {"O", "A"}:
            return False

        policy = policies.get((table_name, f"{table_name}_tenant_read"))
        if policy is None:
            return False
        command, permissive, authenticated_role, role_count, expression = policy
        normalized_expression = re.sub(r"\s+", "", expression or "")
        normalized_expression = normalized_expression.removeprefix("public.")
        if (
            command != "r"
            or not permissive
            or not authenticated_role
            or role_count != 1
            or normalized_expression != _POSTGRES_POLICY_QUAL
        ):
            return False
    return True


class RepositoryError(RuntimeError):
    pass


class NotFound(RepositoryError):
    pass


class Conflict(RepositoryError):
    pass


def _contains_transient_capability(value: Any) -> bool:
    """Reject signed/capability URLs from durable idempotency descriptors."""

    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower().endswith("_url"):
                return True
            if _contains_transient_capability(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_transient_capability(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        if any(
            marker in lowered
            for marker in (
                "/api/v1/objects/",
                "/api/v1/object-uploads/",
                "x-amz-algorithm=",
                "x-amz-signature=",
                "x-amz-credential=",
                "x-amz-date=",
                "x-amz-expires=",
                "x-amz-signedheaders=",
                "x-amz-security-token=",
            )
        ):
            return True
        return re.search(
            r"https?://[^\s\"/:]+:[^\s\"@]+@", value, re.IGNORECASE
        ) is not None
    return False


class Repository:
    def __init__(self, database_url: str, *, create_schema: bool = True) -> None:
        kwargs: dict[str, Any] = {"future": True}
        if database_url in {"sqlite://", "sqlite+pysqlite://"}:
            kwargs.update(
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        elif database_url.startswith("sqlite"):
            kwargs.update(connect_args={"check_same_thread": False})
        self.engine = create_engine(database_url, **kwargs)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if create_schema:
            Base.metadata.create_all(self.engine)

    def check_readiness(self) -> None:
        """Check connectivity and the final expected Stage 2 schema surface.

        PostgreSQL must expose critical Stage 2 columns, constraints, indexes,
        append-only triggers, tenant policies, and RLS. SQLite/local adapters
        must expose every ORM table. Catalog queries return no application data
        and any incomplete migration fails closed.
        """

        with self.engine.connect() as connection:
            if self.engine.dialect.name == "postgresql":
                relations = {
                    str(row["table_name"]): bool(row["rls_enabled"])
                    for row in connection.execute(
                        text(
                            """
                            select c.relname as table_name,
                                   c.relrowsecurity as rls_enabled
                            from pg_class c
                            join pg_namespace n on n.oid = c.relnamespace
                            where n.nspname = 'public'
                              and c.relkind in ('r', 'p')
                            """
                        )
                    ).mappings()
                }
                columns = {
                    (str(row["table_name"]), str(row["column_name"]))
                    for row in connection.execute(
                        text(
                            """
                            select table_name, column_name
                            from information_schema.columns
                            where table_schema = 'public'
                            """
                        )
                    ).mappings()
                }
                constraints = {
                    (str(row["table_name"]), str(row["constraint_name"])): str(
                        row["constraint_type"]
                    )
                    for row in connection.execute(
                        text(
                            """
                            select c.relname as table_name,
                                   p.conname as constraint_name,
                                   p.contype as constraint_type
                            from pg_constraint p
                            join pg_class c on c.oid = p.conrelid
                            join pg_namespace n on n.oid = c.relnamespace
                            where n.nspname = 'public'
                            """
                        )
                    ).mappings()
                }
                indexes = {
                    (str(row["table_name"]), str(row["index_name"])): (
                        bool(row["is_unique"]),
                        bool(row["is_valid"]),
                        bool(row["is_ready"]),
                    )
                    for row in connection.execute(
                        text(
                            """
                            select tc.relname as table_name,
                                   ic.relname as index_name,
                                   i.indisunique as is_unique,
                                   i.indisvalid as is_valid,
                                   i.indisready as is_ready
                            from pg_index i
                            join pg_class tc on tc.oid = i.indrelid
                            join pg_class ic on ic.oid = i.indexrelid
                            join pg_namespace n on n.oid = tc.relnamespace
                            where n.nspname = 'public'
                            """
                        )
                    ).mappings()
                }
                triggers = {
                    (str(row["table_name"]), str(row["trigger_name"])): (
                        str(row["function_name"]),
                        int(row["trigger_type"]),
                        str(row["enabled"]),
                    )
                    for row in connection.execute(
                        text(
                            """
                            select c.relname as table_name,
                                   t.tgname as trigger_name,
                                   p.proname as function_name,
                                   t.tgtype as trigger_type,
                                   t.tgenabled as enabled
                            from pg_trigger t
                            join pg_class c on c.oid = t.tgrelid
                            join pg_namespace n on n.oid = c.relnamespace
                            join pg_proc p on p.oid = t.tgfoid
                            where n.nspname = 'public'
                              and not t.tgisinternal
                            """
                        )
                    ).mappings()
                }
                policies = {
                    (str(row["table_name"]), str(row["policy_name"])): (
                        str(row["command"]),
                        bool(row["permissive"]),
                        bool(row["authenticated_role"]),
                        int(row["role_count"]),
                        None if row["expression"] is None else str(row["expression"]),
                    )
                    for row in connection.execute(
                        text(
                            """
                            select c.relname as table_name,
                                   p.polname as policy_name,
                                   p.polcmd as command,
                                   p.polpermissive as permissive,
                                   exists (
                                     select 1
                                     from pg_roles r
                                     where r.rolname = 'authenticated'
                                       and r.oid = any(p.polroles)
                                   ) as authenticated_role,
                                   cardinality(p.polroles) as role_count,
                                   pg_get_expr(p.polqual, p.polrelid) as expression
                            from pg_policy p
                            join pg_class c on c.oid = p.polrelid
                            join pg_namespace n on n.oid = c.relnamespace
                            where n.nspname = 'public'
                            """
                        )
                    ).mappings()
                }
                if not _postgres_surface_is_ready(
                    relations=relations,
                    columns=columns,
                    constraints=constraints,
                    indexes=indexes,
                    triggers=triggers,
                    policies=policies,
                ):
                    raise RepositoryError("EXPECTED_MIGRATION_SURFACE_MISSING")
            elif self.engine.dialect.name == "sqlite":
                actual_tables = set(
                    connection.execute(
                        text(
                            """
                            select name
                            from sqlite_master
                            where type = 'table' and name not like 'sqlite_%'
                            """
                        )
                    ).scalars()
                )
                if not set(Base.metadata.tables).issubset(actual_tables):
                    raise RepositoryError("EXPECTED_MIGRATION_SURFACE_MISSING")
            else:
                for table_name in Base.metadata.tables:
                    connection.execute(text(f'select 1 from "{table_name}" limit 0'))

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def seed_workspace(self, workspace_id: str, users: list[tuple[str, str, str]]) -> None:
        with self.session() as session:
            if session.get(WorkspaceRow, workspace_id) is None:
                session.add(WorkspaceRow(id=workspace_id, name="Workspace experimental"))
            for user_id, email, role in users:
                user = session.get(UserRow, user_id)
                if user is None:
                    session.add(UserRow(id=user_id, email=email.lower()))
                membership = session.get(WorkspaceRoleRow, (user_id, workspace_id))
                if membership is None:
                    session.add(
                        WorkspaceRoleRow(
                            user_id=user_id,
                            workspace_id=workspace_id,
                            role=role,
                            can_approve_assessments=role in {"OWNER", "TEACHER"},
                        )
                    )

    def membership_for_email(self, email: str) -> tuple[UserRow, WorkspaceRoleRow] | None:
        with self.session() as session:
            user = session.scalar(select(UserRow).where(UserRow.email == email.lower()))
            if user is None:
                return None
            membership = session.scalar(
                select(WorkspaceRoleRow).where(WorkspaceRoleRow.user_id == user.id)
            )
            return None if membership is None else (user, membership)

    def membership_for_user(self, user_id: str) -> tuple[UserRow, WorkspaceRoleRow] | None:
        with self.session() as session:
            user = session.get(UserRow, user_id)
            if user is None:
                return None
            membership = session.scalar(
                select(WorkspaceRoleRow).where(WorkspaceRoleRow.user_id == user.id)
            )
            return None if membership is None else (user, membership)

    def add(self, row: Base) -> None:
        with self.session() as session:
            session.add(row)

    def get(self, model: type[Base], primary_key: Any) -> Base:
        with self.session() as session:
            row = session.get(model, primary_key)
            if row is None:
                raise NotFound(f"{model.__name__} not found")
            return row

    def scoped(self, model: type[Base], primary_key: Any, tenant_id: str) -> Base:
        row = self.get(model, primary_key)
        if getattr(row, "tenant_id", tenant_id) != tenant_id:
            raise NotFound(f"{model.__name__} not found")
        return row

    def save_activity_output(
        self, model: type[ActivitySpecRow | RubricSpecRow | AmbiguityRow], activity_id: str,
        tenant_id: str, data: dict[str, Any]
    ) -> None:
        with self.session() as session:
            row = session.get(model, activity_id)
            if row is None:
                session.add(model(activity_id=activity_id, tenant_id=tenant_id, data=data))
            else:
                row.data = data

    def latest_blueprint(self, activity_id: str, tenant_id: str) -> BlueprintRow:
        with self.session() as session:
            row = session.scalar(
                select(BlueprintRow)
                .where(
                    BlueprintRow.activity_id == activity_id,
                    BlueprintRow.tenant_id == tenant_id,
                )
                .order_by(BlueprintRow.version.desc())
                .limit(1)
            )
            if row is None:
                raise NotFound("blueprint not found")
            return row

    def blueprint_version(self, activity_id: str, version: int, tenant_id: str) -> BlueprintRow:
        with self.session() as session:
            row = session.scalar(
                select(BlueprintRow).where(
                    BlueprintRow.activity_id == activity_id,
                    BlueprintRow.version == version,
                    BlueprintRow.tenant_id == tenant_id,
                )
            )
            if row is None:
                raise NotFound("blueprint not found")
            return row

    def artifacts_for(
        self,
        *,
        activity_id: str,
        tenant_id: str,
        submission_id: str | None,
        complete_only: bool = True,
    ) -> list[ArtifactRow]:
        with self.session() as session:
            statement = select(ArtifactRow).where(
                ArtifactRow.activity_id == activity_id,
                ArtifactRow.tenant_id == tenant_id,
                ArtifactRow.submission_id.is_(submission_id)
                if submission_id is None
                else ArtifactRow.submission_id == submission_id,
            )
            if complete_only:
                statement = statement.where(ArtifactRow.status == "COMPLETE")
            return list(
                session.scalars(statement.order_by(ArtifactRow.created_at, ArtifactRow.id))
            )

    def activities(self, tenant_id: str) -> list[ActivityRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(ActivityRow)
                    .where(ActivityRow.tenant_id == tenant_id)
                    .order_by(ActivityRow.created_at.desc(), ActivityRow.id)
                )
            )

    def update_activity_config(
        self,
        *,
        activity_id: str,
        tenant_id: str,
        config: dict[str, Any],
        blueprint_policy: dict[str, Any],
        expected_etag: str,
    ) -> ActivityRow:
        with self.session() as session:
            statement = select(ActivityRow).where(
                ActivityRow.id == activity_id,
                ActivityRow.tenant_id == tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                raise NotFound("activity not found")
            if row.status != "DRAFT":
                raise Conflict("ACTIVITY_CONFIG_LOCKED")
            if f'"{canonical_hash(row.config)}"' != expected_etag:
                raise Conflict("ETAG_MISMATCH")
            row.config = config
            row.blueprint_policy = blueprint_policy
            row.updated_at = utc_now()
            return row

    def add_artifact_if_inputs_open(
        self,
        row: ArtifactRow,
        *,
        allowed_activity_statuses: set[str],
    ) -> None:
        """Serialize upload creation with the aggregate queue transition."""

        with self.session() as session:
            activity_statement = select(ActivityRow).where(
                ActivityRow.id == row.activity_id,
                ActivityRow.tenant_id == row.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                activity_statement = activity_statement.with_for_update()
            activity = session.scalar(activity_statement)
            if activity is None:
                raise NotFound("activity not found")
            if row.submission_id is None:
                if activity.status not in allowed_activity_statuses:
                    raise Conflict("ACTIVITY_INPUTS_FROZEN")
            else:
                submission_statement = select(SubmissionRow).where(
                    SubmissionRow.id == row.submission_id,
                    SubmissionRow.tenant_id == row.tenant_id,
                    SubmissionRow.activity_id == row.activity_id,
                )
                if self.engine.dialect.name == "postgresql":
                    submission_statement = submission_statement.with_for_update()
                submission = session.scalar(submission_statement)
                if submission is None:
                    raise NotFound("submission not found")
                state = m.SubmissionProcessingState.model_validate(submission.state)
                if (
                    state.status != m.SubmissionProcessingStatus.UPLOADED
                    or submission.active_job_id is not None
                ):
                    raise Conflict("SUBMISSION_INPUTS_FROZEN")
            session.add(row)

    def reserve_artifact_upload(
        self,
        row: ArtifactRow,
        *,
        allowed_activity_statuses: set[str],
    ) -> ArtifactRow:
        """Create an upload slot or recycle a rejected/expired reservation."""

        with self.session() as session:
            activity_statement = select(ActivityRow).where(
                ActivityRow.id == row.activity_id,
                ActivityRow.tenant_id == row.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                activity_statement = activity_statement.with_for_update()
            activity = session.scalar(activity_statement)
            if activity is None:
                raise NotFound("activity not found")
            if row.submission_id is None:
                if activity.status not in allowed_activity_statuses:
                    raise Conflict("ACTIVITY_INPUTS_FROZEN")
            else:
                submission_statement = select(SubmissionRow).where(
                    SubmissionRow.id == row.submission_id,
                    SubmissionRow.tenant_id == row.tenant_id,
                    SubmissionRow.activity_id == row.activity_id,
                )
                if self.engine.dialect.name == "postgresql":
                    submission_statement = submission_statement.with_for_update()
                submission = session.scalar(submission_statement)
                if submission is None:
                    raise NotFound("submission not found")
                state = m.SubmissionProcessingState.model_validate(submission.state)
                if (
                    state.status != m.SubmissionProcessingStatus.UPLOADED
                    or submission.active_job_id is not None
                ):
                    raise Conflict("SUBMISSION_INPUTS_FROZEN")

            existing_statement = select(ArtifactRow).where(
                ArtifactRow.tenant_id == row.tenant_id,
                ArtifactRow.activity_id == row.activity_id,
                ArtifactRow.scope_key == row.scope_key,
                ArtifactRow.role == row.role,
            )
            if self.engine.dialect.name == "postgresql":
                existing_statement = existing_statement.with_for_update()
            existing = session.scalar(existing_statement)
            if existing is None:
                session.add(row)
                session.flush()
                return row

            expires_at = existing.upload_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            reusable = existing.status == "REJECTED" or (
                existing.status == "PENDING" and expires_at <= utc_now()
            )
            if not reusable:
                raise Conflict("ARTIFACT_ALREADY_EXISTS")
            if existing.id != row.id:
                raise Conflict("ARTIFACT_RESERVATION_CHANGED")
            existing.filename = row.filename
            existing.object_key = row.object_key
            existing.declared_media_type = row.declared_media_type
            existing.expected_byte_size = row.expected_byte_size
            existing.media_type = None
            existing.byte_size = None
            existing.sha256 = None
            existing.status = "PENDING"
            existing.upload_expires_at = row.upload_expires_at
            return existing

    def mark_artifact_rejected(self, artifact_id: str, tenant_id: str) -> None:
        with self.session() as session:
            statement = select(ArtifactRow).where(
                ArtifactRow.id == artifact_id,
                ArtifactRow.tenant_id == tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                raise NotFound("artifact not found")
            if row.status == "PENDING":
                row.status = "REJECTED"

    def policy_decisions(self, activity_id: str, tenant_id: str) -> list[PolicyDecisionRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(PolicyDecisionRow)
                    .where(
                        PolicyDecisionRow.activity_id == activity_id,
                        PolicyDecisionRow.tenant_id == tenant_id,
                    )
                    .order_by(PolicyDecisionRow.created_at, PolicyDecisionRow.id)
                )
            )

    def add_policy_decision(self, row: PolicyDecisionRow) -> None:
        try:
            self.add(row)
        except IntegrityError as exc:
            raise Conflict("POLICY_DECISION_ALREADY_EXISTS") from exc

    def create_submissions(self, rows: list[SubmissionRow]) -> list[SubmissionRow]:
        """Persist a manual batch atomically within one tenant/activity.

        The database uniqueness constraint is the final concurrency boundary;
        the locked activity row gives PostgreSQL callers an early, stable
        conflict and prevents a partial batch from being committed.
        """

        if not rows:
            raise ValueError("at least one submission is required")
        tenant_id = rows[0].tenant_id
        activity_id = rows[0].activity_id
        if any(
            row.tenant_id != tenant_id or row.activity_id != activity_id
            for row in rows
        ):
            raise ValueError("a submission batch must share tenant and activity")
        subjects = [row.subject_ref for row in rows]
        identifiers = [row.id for row in rows]
        if len(subjects) != len(set(subjects)) or len(identifiers) != len(
            set(identifiers)
        ):
            raise Conflict("SUBMISSION_BATCH_DUPLICATE")

        try:
            with self.session() as session:
                activity_statement = select(ActivityRow).where(
                    ActivityRow.id == activity_id,
                    ActivityRow.tenant_id == tenant_id,
                )
                if self.engine.dialect.name == "postgresql":
                    activity_statement = activity_statement.with_for_update()
                if session.scalar(activity_statement) is None:
                    raise NotFound("activity not found")
                existing = session.scalar(
                    select(SubmissionRow.id)
                    .where(
                        SubmissionRow.tenant_id == tenant_id,
                        SubmissionRow.activity_id == activity_id,
                        SubmissionRow.subject_ref.in_(subjects),
                    )
                    .limit(1)
                )
                if existing is not None:
                    raise Conflict("SUBMISSION_SUBJECT_ALREADY_EXISTS")
                session.add_all(rows)
                session.flush()
        except IntegrityError as exc:
            raise Conflict("SUBMISSION_SUBJECT_ALREADY_EXISTS") from exc
        return rows

    def submissions_for_activity(
        self, activity_id: str, tenant_id: str
    ) -> list[SubmissionRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(SubmissionRow)
                    .where(
                        SubmissionRow.activity_id == activity_id,
                        SubmissionRow.tenant_id == tenant_id,
                    )
                    .order_by(SubmissionRow.created_at, SubmissionRow.id)
                )
            )

    def submission_for_activity(
        self, activity_id: str, tenant_id: str
    ) -> SubmissionRow | None:
        """Compatibility lookup for E1 callers; deterministic under E2 batches."""

        rows = self.submissions_for_activity(activity_id, tenant_id)
        return rows[0] if rows else None

    def update_artifact_complete(
        self,
        artifact_id: str,
        *,
        tenant_id: str,
        object_key: str,
        media_type: str,
        byte_size: int,
        sha256: str,
        allowed_activity_statuses: set[str],
    ) -> ArtifactRow:
        with self.session() as session:
            snapshot = session.scalar(
                select(ArtifactRow).where(
                    ArtifactRow.id == artifact_id,
                    ArtifactRow.tenant_id == tenant_id,
                )
            )
            if snapshot is None:
                raise NotFound("artifact not found")

            activity_statement = select(ActivityRow).where(
                ActivityRow.id == snapshot.activity_id,
                ActivityRow.tenant_id == tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                activity_statement = activity_statement.with_for_update()
            activity = session.scalar(activity_statement)
            if activity is None:
                raise NotFound("activity not found")

            submission: SubmissionRow | None = None
            if snapshot.submission_id is not None:
                submission_statement = select(SubmissionRow).where(
                    SubmissionRow.id == snapshot.submission_id,
                    SubmissionRow.tenant_id == tenant_id,
                )
                if self.engine.dialect.name == "postgresql":
                    submission_statement = submission_statement.with_for_update()
                submission = session.scalar(submission_statement)
                if submission is None:
                    raise NotFound("submission not found")

            artifact_statement = select(ArtifactRow).where(
                ArtifactRow.id == artifact_id,
                ArtifactRow.tenant_id == tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                artifact_statement = artifact_statement.with_for_update()
            row = session.scalar(artifact_statement)
            if row is None:
                raise NotFound("artifact not found")
            if row.status == "COMPLETE":
                if (
                    row.object_key != object_key
                    or row.media_type != media_type
                    or row.byte_size != byte_size
                    or row.sha256 != sha256
                ):
                    raise Conflict("ARTIFACT_ALREADY_COMPLETE")
                return row
            if row.status != "PENDING":
                raise Conflict("ARTIFACT_NOT_PENDING")
            if submission is None:
                if activity.status not in allowed_activity_statuses:
                    raise Conflict("ACTIVITY_INPUTS_FROZEN")
            else:
                state = m.SubmissionProcessingState.model_validate(submission.state)
                if (
                    state.status != m.SubmissionProcessingStatus.UPLOADED
                    or submission.active_job_id is not None
                ):
                    raise Conflict("SUBMISSION_INPUTS_FROZEN")
            row.object_key = object_key
            row.media_type = media_type
            row.byte_size = byte_size
            row.sha256 = sha256
            row.status = "COMPLETE"
            return row

    def set_activity_status(self, activity_id: str, tenant_id: str, status: str) -> None:
        with self.session() as session:
            row = session.get(ActivityRow, activity_id)
            if row is None or row.tenant_id != tenant_id:
                raise NotFound("activity not found")
            row.status = status
            row.updated_at = utc_now()

    @staticmethod
    def _job_row(status: m.JobStatus, kind: str) -> JobRow:
        return JobRow(
            id=status.job_id,
            tenant_id=status.tenant_id,
            kind=kind,
            aggregate_id=status.aggregate_id,
            stage=status.stage,
            status=status.status,
            progress=status.progress,
            attempt=status.attempt,
            diagnostics=[item.model_dump(mode="json") for item in status.diagnostics],
            control_state="ACTIVE",
            max_attempts=MAX_JOB_ATTEMPTS,
            started_at=status.started_at,
            finished_at=status.finished_at,
        )

    @staticmethod
    def _cancel_diagnostic() -> dict[str, Any]:
        return m.Diagnostic(
            code="JOB_CANCELLED",
            severity=m.Severity.ERROR,
            message="The durable job was cancelled by an authorized actor.",
            retryable=False,
        ).model_dump(mode="json")

    @staticmethod
    def _append_diagnostic_once(
        diagnostics: list[dict[str, Any]], item: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if any(existing.get("code") == item.get("code") for existing in diagnostics):
            return diagnostics
        return [*diagnostics, item]

    def queue_activity_job(
        self,
        status: m.JobStatus,
        *,
        allowed_activity_statuses: set[str],
    ) -> None:
        """Atomically claim the single E1 activity run and persist its job."""

        with self.session() as session:
            statement = select(ActivityRow).where(
                ActivityRow.id == status.aggregate_id,
                ActivityRow.tenant_id == status.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            activity = session.scalar(statement)
            if activity is None:
                raise NotFound("activity not found")
            if activity.status not in allowed_activity_statuses:
                raise Conflict("ACTIVITY_PIPELINE_ALREADY_STARTED")
            pending_artifact = session.scalar(
                select(ArtifactRow.id)
                .where(
                    ArtifactRow.activity_id == activity.id,
                    ArtifactRow.tenant_id == activity.tenant_id,
                    ArtifactRow.submission_id.is_(None),
                    ArtifactRow.status != "COMPLETE",
                )
                .limit(1)
            )
            if pending_artifact is not None:
                raise Conflict("ARTIFACT_UPLOAD_PENDING")
            activity.status = "QUEUED"
            activity.updated_at = utc_now()
            session.add(self._job_row(status, "ACTIVITY"))

    def prepare_blueprint_review_job(
        self,
        *,
        status: m.JobStatus,
        source_version: int,
        source_etag: str,
        descriptor_output: dict[str, Any],
        descriptor_component_version: str,
        descriptor_policy_hash: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> tuple[JobRow, StageRunRow]:
        """Atomically freeze an editable blueprint and persist its worker input."""

        review_request = m.BlueprintReviewRequest.model_validate(
            descriptor_output.get("review_request")
        )
        target = review_request.blueprint
        if any(
            (
                status.stage != "BLUEPRINT_REVIEW",
                status.status != "QUEUED",
                status.attempt != 0,
                status.aggregate_id != target.activity_id,
                target.blueprint_version != source_version + 1,
                descriptor_output.get("source_blueprint_version") != source_version,
                descriptor_output.get("source_etag") != source_etag,
            )
        ):
            raise ValueError("invalid blueprint review preparation state")

        descriptor_inputs = {
            "job_id": status.job_id,
            "source_blueprint_version": source_version,
            "source_etag": source_etag,
            "review_request": review_request.model_dump(mode="json"),
        }
        input_hash = canonical_hash(descriptor_inputs)
        stage_key = canonical_hash(
            {
                "tenant_id": status.tenant_id,
                "stage": BLUEPRINT_REVIEW_DESCRIPTOR_STAGE,
                "inputs": descriptor_inputs,
                "policy_hash": descriptor_policy_hash,
                "component_version": descriptor_component_version,
            }
        )
        output_hash = canonical_hash(descriptor_output)
        descriptor_id = stable_id(
            "stage",
            status.job_id,
            BLUEPRINT_REVIEW_DESCRIPTOR_STAGE,
            stage_key,
            1,
        )
        event_id = stable_id(
            "evt",
            status.tenant_id,
            "blueprint.review_queued",
            status.job_id,
        )

        try:
            with self.session() as session:
                activity_statement = select(ActivityRow).where(
                    ActivityRow.id == status.aggregate_id,
                    ActivityRow.tenant_id == status.tenant_id,
                )
                latest_statement = (
                    select(BlueprintRow)
                    .where(
                        BlueprintRow.activity_id == status.aggregate_id,
                        BlueprintRow.tenant_id == status.tenant_id,
                    )
                    .order_by(BlueprintRow.version.desc())
                    .limit(1)
                )
                if self.engine.dialect.name == "postgresql":
                    activity_statement = activity_statement.with_for_update()
                    latest_statement = latest_statement.with_for_update()
                activity = session.scalar(activity_statement)
                latest = session.scalar(latest_statement)
                if activity is None or latest is None:
                    raise NotFound("blueprint not found")
                if activity.status not in {"BLUEPRINT_READY", "NEEDS_REVIEW"}:
                    raise Conflict("BLUEPRINT_EDIT_NOT_ALLOWED")
                if latest.version != source_version:
                    raise Conflict("BLUEPRINT_VERSION_CONFLICT")
                if latest.etag != source_etag:
                    raise Conflict("ETAG_MISMATCH")
                source = m.AssessmentBlueprint.model_validate(latest.data)
                if (
                    source.status != m.WorkflowStatus.READY
                    or source.approved_by is not None
                    or source.approved_at is not None
                ):
                    raise Conflict("BLUEPRINT_FROZEN")
                if (
                    target.activity_id != source.activity_id
                    or target.blueprint_id != source.blueprint_id
                ):
                    raise Conflict("BLUEPRINT_REFERENCE_MISMATCH")
                if session.get(JobRow, status.job_id) is not None:
                    raise Conflict("BLUEPRINT_REVIEW_JOB_ALREADY_EXISTS")

                job = self._job_row(status, "BLUEPRINT_REVIEW")
                descriptor = StageRunRow(
                    id=descriptor_id,
                    job_id=status.job_id,
                    tenant_id=status.tenant_id,
                    stage=BLUEPRINT_REVIEW_DESCRIPTOR_STAGE,
                    stage_key=stage_key,
                    status="SUCCEEDED",
                    attempt=1,
                    input_hash=input_hash,
                    policy_hash=descriptor_policy_hash,
                    component_version=descriptor_component_version,
                    output=descriptor_output,
                    output_hash=output_hash,
                    diagnostics=[],
                    started_at=occurred_at,
                    finished_at=occurred_at,
                )
                session.add(job)
                session.add(descriptor)
                session.add(
                    AuditEventRow(
                        id=event_id,
                        tenant_id=status.tenant_id,
                        event_type="blueprint.review_queued",
                        aggregate_id=status.aggregate_id,
                        actor_id=actor_id,
                        payload={
                            "job_id": status.job_id,
                            "source_blueprint_version": source_version,
                            "target_blueprint_version": target.blueprint_version,
                            "review_request_hash": canonical_hash(
                                review_request.model_dump(mode="json")
                            ),
                            "prompt_version": descriptor_component_version,
                        },
                        occurred_at=occurred_at,
                    )
                )
                activity.status = "BLUEPRINT_REVIEW_QUEUED"
                activity.updated_at = occurred_at
                session.flush()
                return job, descriptor
        except IntegrityError as exc:
            raise Conflict("BLUEPRINT_REVIEW_PREPARATION_CONFLICT") from exc

    def queue_submission_job(
        self,
        status: m.JobStatus,
        state: m.SubmissionProcessingState,
        *,
        blueprint_version: int,
    ) -> None:
        """Atomically claim the only E1 submission run and persist its job."""

        with self.session() as session:
            statement = select(SubmissionRow).where(
                SubmissionRow.id == state.submission_id,
                SubmissionRow.tenant_id == status.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            submission = session.scalar(statement)
            if submission is None:
                raise NotFound("submission not found")
            current = m.SubmissionProcessingState.model_validate(submission.state)
            if current.status != m.SubmissionProcessingStatus.UPLOADED or submission.active_job_id:
                raise Conflict("SUBMISSION_PIPELINE_ALREADY_STARTED")
            artifacts = list(
                session.scalars(
                    select(ArtifactRow).where(
                        ArtifactRow.submission_id == submission.id,
                        ArtifactRow.tenant_id == submission.tenant_id,
                    )
                )
            )
            if len(artifacts) != 1 or artifacts[0].status != "COMPLETE":
                raise Conflict("SUBMISSION_ARTIFACT_REQUIRED")
            submission.state = state.model_dump(mode="json")
            submission.active_job_id = state.active_job_id
            submission.blueprint_version = blueprint_version
            submission.updated_at = utc_now()
            session.add(self._job_row(status, "SUBMISSION"))

    def set_submission_state(self, state: m.SubmissionProcessingState) -> None:
        with self.session() as session:
            row = session.get(SubmissionRow, state.submission_id)
            if row is None:
                raise NotFound("submission not found")
            row.state = state.model_dump(mode="json")
            row.active_job_id = state.active_job_id
            row.updated_at = utc_now()

    def finalize_submission_assessment(
        self,
        *,
        job_id: str,
        tenant_id: str,
        assessment: AssessmentRow,
        guide: GuideRow,
    ) -> bool:
        """Atomically publish review output or acknowledge a winning cancellation."""

        assessment_value = m.Assessment.model_validate(assessment.data)
        guide_value = m.EvaluationGuide.model_validate(guide.data)
        if any(
            (
                assessment.tenant_id != tenant_id,
                guide.tenant_id != tenant_id,
                assessment.submission_id != guide.submission_id,
                assessment.assessment_id != guide.assessment_id,
                assessment_value.submission_id != assessment.submission_id,
                assessment_value.assessment_id != assessment.assessment_id,
                assessment_value.status != m.WorkflowStatus.NEEDS_REVIEW,
                guide_value.assessment_id != assessment.assessment_id,
                guide_value.status != m.WorkflowStatus.READY,
            )
        ):
            raise ValueError("assessment finalization references are inconsistent")

        now = utc_now()
        with self.session() as session:
            job = self._lock_job(session, job_id, tenant_id, self.engine.dialect.name)
            submission_statement = select(SubmissionRow).where(
                SubmissionRow.id == assessment.submission_id,
                SubmissionRow.tenant_id == tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                submission_statement = submission_statement.with_for_update()
            submission = session.scalar(submission_statement)
            if submission is None:
                raise NotFound("submission not found")

            if job.control_state != "ACTIVE":
                if job.control_state == "CANCEL_REQUESTED":
                    self._complete_job_cancellation(session, job, now)
                return False
            if job.status != "RUNNING" or submission.active_job_id != job.id:
                raise Conflict("SUBMISSION_FINALIZATION_STATE_CHANGED")

            session.merge(assessment)
            session.merge(guide)
            submission.state = m.SubmissionProcessingState(
                submission_id=submission.id,
                activity_id=submission.activity_id,
                status=m.SubmissionProcessingStatus.NEEDS_REVIEW,
                current_stage="NEEDS_REVIEW",
                progress=1.0,
                active_job_id=job.id,
                diagnostics=[],
                updated_at=now,
            ).model_dump(mode="json")
            submission.active_job_id = job.id
            submission.updated_at = now
            job.stage = "ASSEMBLE"
            job.status = "SUCCEEDED"
            job.progress = 1.0
            job.failure_class = None
            job.next_attempt_at = None
            job.finished_at = now
            return True

    def evidence_for_submission(self, submission_id: str, tenant_id: str) -> list[EvidenceRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(EvidenceRow)
                    .where(
                        EvidenceRow.submission_id == submission_id,
                        EvidenceRow.tenant_id == tenant_id,
                    )
                    .order_by(EvidenceRow.id)
                )
            )

    def save_generated_question_and_review(
        self,
        *,
        question: GeneratedQuestionRow,
        review: QuestionReviewRow,
    ) -> None:
        """Persist immutable server-scoped model artifacts without ``merge``.

        Candidate IDs are global primary keys for backward compatibility.  A
        model-supplied collision must therefore fail rather than overwrite a
        row owned by another tenant/submission (or mutate an observed output).
        """

        if (
            question.tenant_id != review.tenant_id
            or question.submission_id != review.submission_id
        ):
            raise ValueError("question and review scopes must match")
        with self.session() as session:
            existing_question = session.get(GeneratedQuestionRow, question.id)
            if existing_question is None:
                session.add(question)
            elif any(
                (
                    existing_question.tenant_id != question.tenant_id,
                    existing_question.submission_id != question.submission_id,
                    existing_question.data != question.data,
                )
            ):
                raise Conflict("GENERATED_QUESTION_ID_COLLISION")

            existing_review = session.get(QuestionReviewRow, review.question_id)
            if existing_review is None:
                session.add(review)
            elif any(
                (
                    existing_review.tenant_id != review.tenant_id,
                    existing_review.submission_id != review.submission_id,
                    existing_review.data != review.data,
                )
            ):
                raise Conflict("QUESTION_REVIEW_ID_COLLISION")

    def save_job_status(self, status: m.JobStatus, *, kind: str | None = None) -> None:
        with self.session() as session:
            row = session.get(JobRow, status.job_id)
            if row is None:
                if kind is None:
                    raise NotFound("job not found")
                row = self._job_row(status, kind)
                session.add(row)
            else:
                if row.tenant_id != status.tenant_id:
                    raise NotFound("job not found")
                if (
                    row.control_state in {"CANCEL_REQUESTED", "CANCELLED"}
                    and status.status == "SUCCEEDED"
                ):
                    raise Conflict("JOB_CANCEL_REQUESTED")
                row.stage = status.stage
                row.status = status.status
                row.progress = status.progress
                row.attempt = status.attempt
                row.diagnostics = [item.model_dump(mode="json") for item in status.diagnostics]
                row.started_at = status.started_at
                row.finished_at = status.finished_at
                if status.status == "SUCCEEDED":
                    row.failure_class = None
                    row.next_attempt_at = None

    def prepare_question_action_job(
        self,
        *,
        status: m.JobStatus,
        max_attempts: int,
        descriptor_inputs: dict[str, Any],
        descriptor_output: dict[str, Any],
        descriptor_component_version: str,
        descriptor_policy_hash: str,
        actor_id: str,
        audit_payload: dict[str, Any],
        occurred_at: datetime,
        create_job: bool,
    ) -> tuple[JobRow, StageRunRow]:
        """Durably prepare a localized action before any provider invocation.

        The technical job, its content-minimizing audit event, and the reusable
        action descriptor share one transaction.  Consequently a worker crash
        or a later terminal-commit rollback can leave either no runnable job or
        a job whose retry source is already reconstructible.
        """

        if any(
            (
                status.stage != "QUESTION_GENERATE",
                status.status != "RUNNING",
                status.attempt < 1,
                not 1 <= max_attempts <= 10,
            )
        ):
            raise ValueError("invalid question action preparation state")
        input_hash = canonical_hash(descriptor_inputs)
        stage_key = canonical_hash(
            {
                "tenant_id": status.tenant_id,
                "stage": QUESTION_ACTION_DESCRIPTOR_STAGE,
                "inputs": descriptor_inputs,
                "policy_hash": descriptor_policy_hash,
                "component_version": descriptor_component_version,
            }
        )
        output_hash = canonical_hash(descriptor_output)
        stage_id = stable_id(
            "stage",
            status.job_id,
            QUESTION_ACTION_DESCRIPTOR_STAGE,
            stage_key,
            status.attempt,
        )
        action_id = str(audit_payload.get("action_id") or "")
        if not action_id:
            raise ValueError("question action audit requires action_id")
        event_id = stable_id(
            "evt",
            status.tenant_id,
            "question_action.executed",
            status.job_id,
            action_id,
        )

        try:
            with self.session() as session:
                job = session.get(JobRow, status.job_id)
                if create_job:
                    if job is not None:
                        raise Conflict("QUESTION_ACTION_JOB_ALREADY_EXISTS")
                    job = self._job_row(status, "QUESTION_ACTION")
                    job.max_attempts = max_attempts
                    session.add(job)
                elif job is None or job.tenant_id != status.tenant_id:
                    raise NotFound("job not found")
                assert job is not None
                if any(
                    (
                        job.tenant_id != status.tenant_id,
                        job.kind != "QUESTION_ACTION",
                        job.aggregate_id != status.aggregate_id,
                        job.status != "RUNNING",
                        job.attempt != status.attempt,
                    )
                ):
                    raise Conflict("QUESTION_ACTION_JOB_STATE_CHANGED")

                descriptor = session.get(StageRunRow, stage_id)
                if descriptor is None:
                    descriptor = StageRunRow(
                        id=stage_id,
                        job_id=status.job_id,
                        tenant_id=status.tenant_id,
                        stage=QUESTION_ACTION_DESCRIPTOR_STAGE,
                        stage_key=stage_key,
                        status="SUCCEEDED",
                        attempt=status.attempt,
                        input_hash=input_hash,
                        policy_hash=descriptor_policy_hash,
                        component_version=descriptor_component_version,
                        output=descriptor_output,
                        output_hash=output_hash,
                        diagnostics=[],
                        started_at=occurred_at,
                        finished_at=occurred_at,
                    )
                    session.add(descriptor)
                elif any(
                    (
                        descriptor.job_id != status.job_id,
                        descriptor.tenant_id != status.tenant_id,
                        descriptor.stage != QUESTION_ACTION_DESCRIPTOR_STAGE,
                        descriptor.stage_key != stage_key,
                        descriptor.status != "SUCCEEDED",
                        descriptor.attempt != status.attempt,
                        descriptor.input_hash != input_hash,
                        descriptor.policy_hash != descriptor_policy_hash,
                        descriptor.component_version != descriptor_component_version,
                        descriptor.output_hash != output_hash,
                        descriptor.output != descriptor_output,
                    )
                ):
                    raise Conflict("QUESTION_ACTION_DESCRIPTOR_CONFLICT")

                audit = session.get(AuditEventRow, event_id)
                if audit is None:
                    session.add(
                        AuditEventRow(
                            id=event_id,
                            tenant_id=status.tenant_id,
                            event_type="question_action.executed",
                            aggregate_id=status.job_id,
                            actor_id=actor_id,
                            payload=audit_payload,
                            occurred_at=occurred_at,
                        )
                    )
                elif any(
                    (
                        audit.tenant_id != status.tenant_id,
                        audit.event_type != "question_action.executed",
                        audit.aggregate_id != status.job_id,
                        audit.actor_id != actor_id,
                        audit.payload != audit_payload,
                    )
                ):
                    raise Conflict("QUESTION_ACTION_AUDIT_CONFLICT")
                session.flush()
                return job, descriptor
        except IntegrityError as exc:
            raise Conflict("QUESTION_ACTION_PREPARATION_CONFLICT") from exc

    def question_action_descriptor(
        self, *, job_id: str, tenant_id: str
    ) -> StageRunRow | None:
        """Return one hash-verified retry descriptor for a localized job."""

        with self.session() as session:
            rows = list(
                session.scalars(
                    select(StageRunRow)
                    .where(
                        StageRunRow.job_id == job_id,
                        StageRunRow.tenant_id == tenant_id,
                        StageRunRow.stage == QUESTION_ACTION_DESCRIPTOR_STAGE,
                        StageRunRow.status == "SUCCEEDED",
                        StageRunRow.output_hash.is_not(None),
                    )
                    .order_by(StageRunRow.attempt.desc(), StageRunRow.id.desc())
                )
            )
            if not rows:
                return None
            if len(rows) != 1:
                raise Conflict("QUESTION_ACTION_DESCRIPTOR_AMBIGUOUS")
            row = rows[0]
            if row.output is None or row.output_hash != canonical_hash(row.output):
                raise Conflict("QUESTION_ACTION_DESCRIPTOR_HASH_MISMATCH")
            return row

    def blueprint_review_descriptor(
        self, *, job_ids: list[str], tenant_id: str
    ) -> StageRunRow | None:
        """Return the single hash-verified P05 request across a retry lineage."""

        if not job_ids:
            return None
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(StageRunRow)
                    .where(
                        StageRunRow.job_id.in_(job_ids),
                        StageRunRow.tenant_id == tenant_id,
                        StageRunRow.stage == BLUEPRINT_REVIEW_DESCRIPTOR_STAGE,
                        StageRunRow.status == "SUCCEEDED",
                        StageRunRow.output_hash.is_not(None),
                    )
                    .order_by(StageRunRow.started_at, StageRunRow.id)
                )
            )
            if not rows:
                return None
            if len(rows) != 1:
                raise Conflict("BLUEPRINT_REVIEW_DESCRIPTOR_AMBIGUOUS")
            row = rows[0]
            if row.output is None or row.output_hash != canonical_hash(row.output):
                raise Conflict("BLUEPRINT_REVIEW_DESCRIPTOR_HASH_MISMATCH")
            source_version = row.output.get("source_blueprint_version")
            source_etag = row.output.get("source_etag")
            source_status = row.output.get("source_activity_status")
            try:
                request = m.BlueprintReviewRequest.model_validate(
                    row.output.get("review_request")
                )
            except Exception as exc:
                raise Conflict("BLUEPRINT_REVIEW_DESCRIPTOR_INVALID") from exc
            if any(
                (
                    not isinstance(source_version, int),
                    not isinstance(source_etag, str),
                    source_status not in {"BLUEPRINT_READY", "NEEDS_REVIEW"},
                    request.blueprint.blueprint_version != source_version + 1,
                )
            ):
                raise Conflict("BLUEPRINT_REVIEW_DESCRIPTOR_INVALID")
            return row

    def finalize_blueprint_review_job(
        self,
        *,
        job_id: str,
        tenant_id: str,
        source_version: int,
        source_etag: str,
        blueprint: BlueprintRow,
        actor_id: str,
    ) -> bool:
        """Atomically publish the next immutable blueprint and finish its job."""

        value = m.AssessmentBlueprint.model_validate(blueprint.data)
        review = m.BlueprintReview.model_validate(blueprint.review)
        if any(
            (
                blueprint.tenant_id != tenant_id,
                blueprint.activity_id != value.activity_id,
                blueprint.blueprint_id != value.blueprint_id,
                blueprint.version != source_version + 1,
                value.blueprint_version != blueprint.version,
                review.blueprint_id != value.blueprint_id,
                review.blueprint_version != value.blueprint_version,
                value.status != m.WorkflowStatus.READY,
                value.approved_by is not None,
                value.approved_at is not None,
            )
        ):
            raise ValueError("blueprint review finalization references are inconsistent")

        now = utc_now()
        try:
            with self.session() as session:
                job = self._lock_job(
                    session, job_id, tenant_id, self.engine.dialect.name
                )
                activity_statement = select(ActivityRow).where(
                    ActivityRow.id == blueprint.activity_id,
                    ActivityRow.tenant_id == tenant_id,
                )
                latest_statement = (
                    select(BlueprintRow)
                    .where(
                        BlueprintRow.activity_id == blueprint.activity_id,
                        BlueprintRow.tenant_id == tenant_id,
                    )
                    .order_by(BlueprintRow.version.desc())
                    .limit(1)
                )
                if self.engine.dialect.name == "postgresql":
                    activity_statement = activity_statement.with_for_update()
                    latest_statement = latest_statement.with_for_update()
                activity = session.scalar(activity_statement)
                latest = session.scalar(latest_statement)
                if activity is None or latest is None:
                    raise NotFound("blueprint not found")
                if job.kind != "BLUEPRINT_REVIEW" or job.aggregate_id != activity.id:
                    raise Conflict("BLUEPRINT_REVIEW_JOB_MISMATCH")
                if job.control_state != "ACTIVE":
                    if job.control_state == "CANCEL_REQUESTED":
                        self._complete_job_cancellation(session, job, now)
                    return False
                if job.status != "RUNNING":
                    raise Conflict("BLUEPRINT_REVIEW_JOB_NOT_RUNNING")
                if activity.status != "BLUEPRINT_REVIEW_QUEUED":
                    raise Conflict("BLUEPRINT_REVIEW_ACTIVITY_STATE_CHANGED")
                if latest.version != source_version or latest.etag != source_etag:
                    raise Conflict("BLUEPRINT_REVIEW_SOURCE_CHANGED")

                review_allows_approval = (
                    review.status == "READY"
                    and review.approval_recommendation
                    != m.BlueprintApprovalRecommendation.REJECT
                )
                if review_allows_approval:
                    session.add(blueprint)
                    activity.status = "BLUEPRINT_READY"
                    job.status = "SUCCEEDED"
                    job.failure_class = None
                    job.diagnostics = []
                elif review.status == "TECHNICAL_FAILURE":
                    activity.status = "TECHNICAL_FAILURE"
                    job.status = "FAILED"
                    job.failure_class = m.FailureClass.VALIDATION.value
                    job.diagnostics = [
                        item.model_dump(mode="json")
                        for item in review.diagnostics
                    ] or [
                        m.Diagnostic(
                            code="BLUEPRINT_REVIEW_TECHNICAL_FAILURE",
                            severity=m.Severity.ERROR,
                            message=(
                                "The edited blueprint failed its validated review boundary."
                            ),
                            retryable=False,
                        ).model_dump(mode="json")
                    ]
                else:
                    activity.status = "NEEDS_REVIEW"
                    job.status = "NEEDS_REVIEW"
                    job.failure_class = None
                    job.diagnostics = [
                        item.model_dump(mode="json")
                        for item in review.diagnostics
                    ]
                activity.updated_at = now
                job.stage = "BLUEPRINT_REVIEW"
                job.progress = 1.0
                job.next_attempt_at = None
                job.finished_at = now
                session.add(
                    AuditEventRow(
                        id=stable_id(
                            "evt",
                            tenant_id,
                            (
                                "blueprint.edited"
                                if review_allows_approval
                                else "blueprint.review_blocked"
                            ),
                            blueprint.blueprint_id,
                            job.id,
                        ),
                        tenant_id=tenant_id,
                        event_type=(
                            "blueprint.edited"
                            if review_allows_approval
                            else "blueprint.review_blocked"
                        ),
                        aggregate_id=blueprint.blueprint_id,
                        actor_id=actor_id,
                        payload={
                            "source_blueprint_version": source_version,
                            "blueprint_version": blueprint.version,
                            "review_status": review.status,
                            "approval_recommendation": review.approval_recommendation,
                            "job_id": job.id,
                        },
                        occurred_at=now,
                    )
                )
                session.flush()
                return True
        except IntegrityError as exc:
            raise Conflict("BLUEPRINT_VERSION_CONFLICT") from exc

    def fail_queued_dispatch(
        self,
        *,
        job_id: str,
        tenant_id: str,
        failure: m.Diagnostic,
        failure_class: m.FailureClass = m.FailureClass.TRANSIENT,
    ) -> bool:
        """Fail a dispatch only while the durable job is still unclaimed.

        A timeout from the executor API is ambiguous: the executor may have
        accepted and even completed the job before the caller loses its
        response.  Locking and comparing ``QUEUED`` prevents that transport
        ambiguity from overwriting RUNNING or terminal application state.
        """

        now = utc_now()
        with self.session() as session:
            row = self._lock_job(session, job_id, tenant_id, self.engine.dialect.name)
            if row.status != "QUEUED" or row.control_state != "ACTIVE":
                return False
            row.status = "FAILED"
            row.failure_class = failure_class.value
            row.diagnostics = [failure.model_dump(mode="json")]
            row.next_attempt_at = None
            row.finished_at = now
            if row.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
                statement = select(ActivityRow).where(
                    ActivityRow.id == row.aggregate_id,
                    ActivityRow.tenant_id == tenant_id,
                )
                if self.engine.dialect.name == "postgresql":
                    statement = statement.with_for_update()
                activity = session.scalar(statement)
                if activity is not None:
                    activity.status = "TECHNICAL_FAILURE"
                    activity.updated_at = now
            elif row.kind == "SUBMISSION":
                statement = select(SubmissionRow).where(
                    SubmissionRow.id == row.aggregate_id,
                    SubmissionRow.tenant_id == tenant_id,
                )
                if self.engine.dialect.name == "postgresql":
                    statement = statement.with_for_update()
                submission = session.scalar(statement)
                if submission is not None and submission.active_job_id == row.id:
                    current = m.SubmissionProcessingState.model_validate(
                        submission.state
                    )
                    submission.state = current.model_copy(
                        update={
                            "status": m.SubmissionProcessingStatus.TECHNICAL_FAILURE,
                            "current_stage": row.stage,
                            "active_job_id": row.id,
                            "diagnostics": [failure],
                            "updated_at": now,
                        }
                    ).model_dump(mode="json")
                    submission.updated_at = now
            return True

    def job_status(self, job_id: str, tenant_id: str) -> m.JobStatus:
        row = self.scoped(JobRow, job_id, tenant_id)
        assert isinstance(row, JobRow)
        return m.JobStatus(
            job_id=row.id,
            tenant_id=row.tenant_id,
            aggregate_id=row.aggregate_id,
            stage=row.stage,
            status=row.status,
            progress=row.progress,
            attempt=row.attempt,
            diagnostics=row.diagnostics,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    def latest_job_for_aggregate(
        self, aggregate_id: str, tenant_id: str
    ) -> m.JobStatus | None:
        with self.session() as session:
            row = session.scalar(
                select(JobRow)
                .where(
                    JobRow.aggregate_id == aggregate_id,
                    JobRow.tenant_id == tenant_id,
                )
                .order_by(JobRow.created_at.desc(), JobRow.id.desc())
                .limit(1)
            )
        return None if row is None else self.job_status(row.id, tenant_id)

    def job_control(self, job_id: str, tenant_id: str) -> JobRow:
        row = self.scoped(JobRow, job_id, tenant_id)
        assert isinstance(row, JobRow)
        return row

    @staticmethod
    def _lock_job(session: Session, job_id: str, tenant_id: str, dialect: str) -> JobRow:
        statement = select(JobRow).where(
            JobRow.id == job_id,
            JobRow.tenant_id == tenant_id,
        )
        if dialect == "postgresql":
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise NotFound("job not found")
        return row

    @staticmethod
    def _add_job_control_record(
        session: Session, record: m.JobControlRecord
    ) -> JobControlRecordRow:
        row = JobControlRecordRow(
            id=record.control_id,
            tenant_id=record.tenant_id,
            job_id=record.job_id,
            resulting_job_id=record.resulting_job_id,
            aggregate_id=record.aggregate_id,
            actor_id=record.actor_id,
            action=record.action.value,
            status=record.status.value,
            source_attempt=record.source_attempt,
            target_stage=record.target_stage,
            failure_class=(
                record.failure_class.value if record.failure_class is not None else None
            ),
            data=record.model_dump(mode="json"),
            requested_at=record.requested_at,
            decided_at=record.decided_at,
        )
        session.add(row)
        return row

    @staticmethod
    def _has_applied_continuation(
        session: Session, source: JobRow
    ) -> bool:
        return session.scalar(
            select(JobControlRecordRow.id)
            .where(
                JobControlRecordRow.tenant_id == source.tenant_id,
                JobControlRecordRow.job_id == source.id,
                JobControlRecordRow.source_attempt == source.attempt,
                JobControlRecordRow.action.in_(("RETRY", "RESUME")),
                JobControlRecordRow.status == "APPLIED",
            )
            .limit(1)
        ) is not None

    def request_job_cancel(
        self,
        *,
        job_id: str,
        tenant_id: str,
        actor_id: str,
        requested_at: datetime | None = None,
        control_id: str | None = None,
        reason_code: str = "USER_REQUESTED_CANCELLATION",
    ) -> JobRow:
        """Request cooperative cancellation, or finish it before a queued claim."""

        now = requested_at or utc_now()
        with self.session() as session:
            row = self._lock_job(session, job_id, tenant_id, self.engine.dialect.name)
            if row.control_state == "CANCELLED":
                return row
            if row.control_state == "CANCEL_REQUESTED":
                return row
            if row.status not in {"QUEUED", "RUNNING"}:
                raise Conflict("JOB_NOT_CANCELLABLE")
            row.control_state = "CANCEL_REQUESTED"
            row.cancel_requested_at = now
            row.cancel_requested_by = actor_id
            row.next_attempt_at = None
            control = m.JobControlRecord(
                control_id=control_id
                or stable_id(
                    "ctl", tenant_id, job_id, "CANCEL", actor_id, now.isoformat()
                ),
                tenant_id=tenant_id,
                job_id=job_id,
                aggregate_id=row.aggregate_id,
                action=m.JobControlActionType.CANCEL,
                status=m.JobControlStatus.APPLIED,
                actor_id=actor_id,
                source_attempt=row.attempt,
                reason_code=reason_code,
                requested_at=now,
                decided_at=now,
            )
            self._add_job_control_record(session, control)
            if row.status == "QUEUED":
                self._complete_job_cancellation(session, row, now)
            return row

    def _complete_job_cancellation(
        self, session: Session, row: JobRow, completed_at: datetime
    ) -> None:
        cancellation = self._cancel_diagnostic()
        row.status = "FAILED"
        row.control_state = "CANCELLED"
        row.failure_class = "CANCELLATION"
        row.finished_at = completed_at
        row.cancelled_at = completed_at
        row.next_attempt_at = None
        row.diagnostics = self._append_diagnostic_once(row.diagnostics or [], cancellation)
        if row.kind == "ACTIVITY":
            activity_statement = select(ActivityRow).where(
                ActivityRow.id == row.aggregate_id,
                ActivityRow.tenant_id == row.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                activity_statement = activity_statement.with_for_update()
            activity = session.scalar(activity_statement)
            if activity is None:
                raise NotFound("activity not found")
            # Cancellation is terminal for this Job, but must not strand the
            # editable aggregate in its transient QUEUED projection. Verified
            # StageRuns remain durable and a later explicit run may reuse only
            # hash/version-compatible outputs.
            activity.status = "DRAFT"
            activity.updated_at = completed_at
            return
        if row.kind == "BLUEPRINT_REVIEW":
            activity_statement = select(ActivityRow).where(
                ActivityRow.id == row.aggregate_id,
                ActivityRow.tenant_id == row.tenant_id,
            )
            latest_statement = (
                select(BlueprintRow)
                .where(
                    BlueprintRow.activity_id == row.aggregate_id,
                    BlueprintRow.tenant_id == row.tenant_id,
                )
                .order_by(BlueprintRow.version.desc())
                .limit(1)
            )
            if self.engine.dialect.name == "postgresql":
                activity_statement = activity_statement.with_for_update()
                latest_statement = latest_statement.with_for_update()
            activity = session.scalar(activity_statement)
            latest = session.scalar(latest_statement)
            if activity is None or latest is None:
                raise NotFound("blueprint not found")
            review = m.BlueprintReview.model_validate(latest.review)
            activity.status = (
                "BLUEPRINT_READY"
                if review.status == "READY"
                and review.approval_recommendation
                != m.BlueprintApprovalRecommendation.REJECT
                else "NEEDS_REVIEW"
            )
            activity.updated_at = completed_at
            return
        if row.kind != "SUBMISSION":
            return
        submission_statement = select(SubmissionRow).where(
            SubmissionRow.id == row.aggregate_id,
            SubmissionRow.tenant_id == row.tenant_id,
        )
        if self.engine.dialect.name == "postgresql":
            submission_statement = submission_statement.with_for_update()
        submission = session.scalar(submission_statement)
        if submission is None:
            raise NotFound("submission not found")
        current = m.SubmissionProcessingState.model_validate(submission.state)
        cancelled = current.model_copy(
            update={
                "status": m.SubmissionProcessingStatus.CANCELLED,
                "current_stage": row.stage,
                "active_job_id": None,
                "diagnostics": [*current.diagnostics, m.Diagnostic.model_validate(cancellation)],
                "updated_at": completed_at,
            }
        )
        submission.state = cancelled.model_dump(mode="json")
        submission.active_job_id = None
        submission.updated_at = completed_at

    def complete_job_cancellation(
        self,
        *,
        job_id: str,
        tenant_id: str,
        completed_at: datetime | None = None,
    ) -> JobRow:
        """Acknowledge cancellation at a worker stage boundary."""

        now = completed_at or utc_now()
        with self.session() as session:
            row = self._lock_job(session, job_id, tenant_id, self.engine.dialect.name)
            if row.control_state == "CANCELLED":
                return row
            if row.control_state != "CANCEL_REQUESTED":
                raise Conflict("JOB_CANCEL_NOT_REQUESTED")
            self._complete_job_cancellation(session, row, now)
            return row

    def job_cancel_requested(self, job_id: str, tenant_id: str) -> bool:
        return self.job_control(job_id, tenant_id).control_state in {
            "CANCEL_REQUESTED",
            "CANCELLED",
        }

    def schedule_job_retry(
        self,
        *,
        job_id: str,
        tenant_id: str,
        resulting_job_id: str,
        control_id: str,
        actor_id: str,
        reason_code: str,
        failure_class: str,
        next_attempt_at: datetime,
        resume_from_stage: str,
        max_attempts: int | None = None,
    ) -> JobRow:
        """Create a distinct retry job and bind it to an append-only control record."""

        if failure_class not in RETRYABLE_JOB_FAILURE_CLASSES:
            raise Conflict("JOB_FAILURE_NOT_RETRYABLE")
        if resulting_job_id == job_id:
            raise Conflict("JOB_RETRY_REQUIRES_DISTINCT_JOB")
        if max_attempts is not None and not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        now = utc_now()
        try:
            with self.session() as session:
                source = self._lock_job(
                    session, job_id, tenant_id, self.engine.dialect.name
                )
                if source.control_state != "ACTIVE":
                    raise Conflict("JOB_CANCEL_REQUESTED")
                if source.status != "FAILED":
                    raise Conflict("JOB_NOT_RETRYABLE")
                if source.failure_class != failure_class:
                    raise Conflict("JOB_FAILURE_CLASS_MISMATCH")
                effective_max = max_attempts or source.max_attempts
                if source.attempt >= effective_max:
                    raise Conflict("JOB_RETRY_LIMIT_EXHAUSTED")
                if self._has_applied_continuation(session, source):
                    raise Conflict("JOB_CONTINUATION_ALREADY_SCHEDULED")
                if failure_class == "PROVIDER" and not any(
                    item.get("retryable") is True for item in source.diagnostics or []
                ):
                    raise Conflict("JOB_FAILURE_NOT_RETRYABLE")
                if session.get(JobRow, resulting_job_id) is not None:
                    raise Conflict("JOB_RESULT_ALREADY_EXISTS")
                result = JobRow(
                    id=resulting_job_id,
                    tenant_id=source.tenant_id,
                    kind=source.kind,
                    aggregate_id=source.aggregate_id,
                    stage=resume_from_stage,
                    status="QUEUED",
                    progress=source.progress,
                    attempt=source.attempt,
                    diagnostics=[],
                    control_state="ACTIVE",
                    max_attempts=effective_max,
                    next_attempt_at=next_attempt_at,
                    resume_from_stage=resume_from_stage,
                    created_at=now,
                )
                session.add(result)
                self._activate_resulting_submission_job(session, source, result, now)
                failed_stage = session.scalar(
                    select(StageRunRow)
                    .where(
                        StageRunRow.job_id == source.id,
                        StageRunRow.tenant_id == source.tenant_id,
                        StageRunRow.status == "FAILED",
                        StageRunRow.stage == resume_from_stage,
                    )
                    .order_by(
                        StageRunRow.attempt.desc(), StageRunRow.started_at.desc()
                    )
                    .limit(1)
                )
                if failed_stage is not None:
                    failed_stage.failure_class = failure_class
                    failed_stage.next_attempt_at = next_attempt_at
                control = m.JobControlRecord(
                    control_id=control_id,
                    tenant_id=tenant_id,
                    job_id=source.id,
                    aggregate_id=source.aggregate_id,
                    action=m.JobControlActionType.RETRY,
                    status=m.JobControlStatus.APPLIED,
                    actor_id=actor_id,
                    source_attempt=source.attempt,
                    reason_code=reason_code,
                    target_stage=resume_from_stage,
                    failure_class=m.FailureClass(failure_class),
                    resulting_job_id=result.id,
                    requested_at=now,
                    decided_at=now,
                )
                self._add_job_control_record(session, control)
                session.flush()
                return result
        except IntegrityError as exc:
            raise Conflict("JOB_RETRY_ALREADY_SCHEDULED") from exc

    def schedule_job_resume(
        self,
        *,
        job_id: str,
        tenant_id: str,
        resulting_job_id: str,
        control_id: str,
        actor_id: str,
        reason_code: str,
        resume_from_stage: str,
        next_attempt_at: datetime | None = None,
    ) -> JobRow:
        """Create a distinct continuation after a durable review/precondition gate."""

        if resulting_job_id == job_id:
            raise Conflict("JOB_RESUME_REQUIRES_DISTINCT_JOB")
        now = utc_now()
        try:
            with self.session() as session:
                source = self._lock_job(
                    session, job_id, tenant_id, self.engine.dialect.name
                )
                if source.control_state != "ACTIVE":
                    raise Conflict("JOB_CANCEL_REQUESTED")
                if source.status not in {"FAILED", "NEEDS_REVIEW"}:
                    raise Conflict("JOB_NOT_RESUMABLE")
                if (
                    source.status == "FAILED"
                    and source.failure_class not in {"PRECONDITION", "VALIDATION"}
                ):
                    raise Conflict("JOB_NOT_RESUMABLE")
                if source.attempt >= source.max_attempts:
                    raise Conflict("JOB_RETRY_LIMIT_EXHAUSTED")
                if self._has_applied_continuation(session, source):
                    raise Conflict("JOB_CONTINUATION_ALREADY_SCHEDULED")
                if session.get(JobRow, resulting_job_id) is not None:
                    raise Conflict("JOB_RESULT_ALREADY_EXISTS")
                result = JobRow(
                    id=resulting_job_id,
                    tenant_id=source.tenant_id,
                    kind=source.kind,
                    aggregate_id=source.aggregate_id,
                    stage=resume_from_stage,
                    status="QUEUED",
                    progress=source.progress,
                    attempt=source.attempt,
                    diagnostics=[],
                    control_state="ACTIVE",
                    max_attempts=source.max_attempts,
                    next_attempt_at=next_attempt_at,
                    resume_from_stage=resume_from_stage,
                    created_at=now,
                )
                session.add(result)
                self._activate_resulting_submission_job(session, source, result, now)
                control = m.JobControlRecord(
                    control_id=control_id,
                    tenant_id=tenant_id,
                    job_id=source.id,
                    aggregate_id=source.aggregate_id,
                    action=m.JobControlActionType.RESUME,
                    status=m.JobControlStatus.APPLIED,
                    actor_id=actor_id,
                    source_attempt=source.attempt,
                    reason_code=reason_code,
                    target_stage=resume_from_stage,
                    resulting_job_id=result.id,
                    requested_at=now,
                    decided_at=now,
                )
                self._add_job_control_record(session, control)
                session.flush()
                return result
        except IntegrityError as exc:
            raise Conflict("JOB_RESUME_ALREADY_SCHEDULED") from exc

    def _activate_resulting_submission_job(
        self,
        session: Session,
        source: JobRow,
        result: JobRow,
        activated_at: datetime,
    ) -> None:
        stage_progress = {
            "ACTIVITY_PARSE": 0.05,
            "ACTIVITY_SPEC": 0.15,
            "RUBRIC_NORMALIZE": 0.30,
            "AMBIGUITY_TRIAGE": 0.45,
            "BLUEPRINT_BUILD": 0.65,
            "BLUEPRINT_REVIEW": 0.82,
            "SUBMISSION_PARSE": 0.08,
            "EVIDENCE_MAP": 0.20,
            "ASSESSMENT_PLAN": 0.32,
            "QUESTION_GENERATE": 0.40,
            "QUESTION_REVIEW": 0.55,
            "ASSEMBLE": 0.72,
            "GUIDE_BUILD": 0.82,
        }
        result.progress = stage_progress.get(result.stage, 0.0)
        if source.kind == "ACTIVITY":
            statement = select(ActivityRow).where(
                ActivityRow.id == source.aggregate_id,
                ActivityRow.tenant_id == source.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            activity = session.scalar(statement)
            if activity is None:
                raise NotFound("activity not found")
            if activity.status not in {"TECHNICAL_FAILURE", "NEEDS_REVIEW"}:
                raise Conflict("ACTIVITY_CONTINUATION_NOT_ALLOWED")
            activity.status = "QUEUED"
            activity.updated_at = activated_at
            return
        if source.kind == "BLUEPRINT_REVIEW":
            statement = select(ActivityRow).where(
                ActivityRow.id == source.aggregate_id,
                ActivityRow.tenant_id == source.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            activity = session.scalar(statement)
            if activity is None:
                raise NotFound("activity not found")
            if activity.status not in {
                "TECHNICAL_FAILURE",
                "NEEDS_REVIEW",
                "BLUEPRINT_READY",
            }:
                raise Conflict("BLUEPRINT_REVIEW_CONTINUATION_NOT_ALLOWED")
            activity.status = "BLUEPRINT_REVIEW_QUEUED"
            activity.updated_at = activated_at
            return
        if source.kind != "SUBMISSION":
            return
        statement = select(SubmissionRow).where(
            SubmissionRow.id == source.aggregate_id,
            SubmissionRow.tenant_id == source.tenant_id,
        )
        if self.engine.dialect.name == "postgresql":
            statement = statement.with_for_update()
        submission = session.scalar(statement)
        if submission is None:
            raise NotFound("submission not found")
        current = m.SubmissionProcessingState.model_validate(submission.state)
        domain_status = {
            "SUBMISSION_PARSE": m.SubmissionProcessingStatus.PARSING,
            "EVIDENCE_MAP": m.SubmissionProcessingStatus.MAPPING_OPPORTUNITIES,
            "ASSESSMENT_PLAN": m.SubmissionProcessingStatus.PLANNING,
            "QUESTION_GENERATE": m.SubmissionProcessingStatus.GENERATING,
            "QUESTION_REVIEW": (
                m.SubmissionProcessingStatus.VALIDATING_QUESTIONS
            ),
            "ASSEMBLE": m.SubmissionProcessingStatus.VALIDATING_QUESTIONS,
            "GUIDE_BUILD": m.SubmissionProcessingStatus.VALIDATING_QUESTIONS,
        }.get(result.stage, m.SubmissionProcessingStatus.PARSING)
        resumed = current.model_copy(
            update={
                "status": domain_status,
                "current_stage": result.stage,
                "progress": result.progress,
                "active_job_id": result.id,
                "diagnostics": [],
                "updated_at": activated_at,
            }
        )
        submission.state = resumed.model_dump(mode="json")
        submission.active_job_id = result.id
        submission.updated_at = activated_at

    def job_control_records(
        self,
        *,
        tenant_id: str,
        job_id: str | None = None,
        resulting_job_id: str | None = None,
    ) -> list[JobControlRecordRow]:
        with self.session() as session:
            statement = select(JobControlRecordRow).where(
                JobControlRecordRow.tenant_id == tenant_id
            )
            if job_id is not None:
                statement = statement.where(JobControlRecordRow.job_id == job_id)
            if resulting_job_id is not None:
                statement = statement.where(
                    JobControlRecordRow.resulting_job_id == resulting_job_id
                )
            return list(
                session.scalars(
                    statement.order_by(
                        JobControlRecordRow.requested_at, JobControlRecordRow.id
                    )
                )
            )

    def reconcile_stale_jobs(
        self,
        *,
        lease_seconds: int = 3900,
        now: datetime | None = None,
    ) -> int:
        """Turn orphaned RUNNING rows into bounded, controllable state."""

        if not 300 <= lease_seconds <= 7200:
            raise ValueError("job lease must be between 300 and 7200 seconds")
        reconciled_at = now or utc_now()
        cutoff = reconciled_at - timedelta(seconds=lease_seconds)
        with self.session() as session:
            statement = (
                select(JobRow)
                .where(
                    JobRow.status == "RUNNING",
                    JobRow.started_at.is_not(None),
                    JobRow.started_at <= cutoff,
                )
                .order_by(JobRow.started_at, JobRow.id)
                .limit(100)
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            rows = list(session.scalars(statement))
            for row in rows:
                if row.control_state == "CANCEL_REQUESTED":
                    self._complete_job_cancellation(session, row, reconciled_at)
                    continue
                if row.control_state != "ACTIVE":
                    continue
                failure = m.Diagnostic(
                    code="JOB_LEASE_EXPIRED",
                    severity=m.Severity.ERROR,
                    message=(
                        "The worker lease expired before a terminal state was "
                        "persisted."
                    ),
                    retryable=True,
                )
                row.status = "FAILED"
                row.failure_class = m.FailureClass.TRANSIENT.value
                row.diagnostics = [failure.model_dump(mode="json")]
                row.next_attempt_at = None
                row.finished_at = reconciled_at
                if row.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
                    activity = session.scalar(
                        select(ActivityRow).where(
                            ActivityRow.id == row.aggregate_id,
                            ActivityRow.tenant_id == row.tenant_id,
                        )
                    )
                    if activity is not None:
                        activity.status = "TECHNICAL_FAILURE"
                        activity.updated_at = reconciled_at
                elif row.kind == "SUBMISSION":
                    submission = session.scalar(
                        select(SubmissionRow).where(
                            SubmissionRow.id == row.aggregate_id,
                            SubmissionRow.tenant_id == row.tenant_id,
                        )
                    )
                    if submission is not None and submission.active_job_id == row.id:
                        current = m.SubmissionProcessingState.model_validate(
                            submission.state
                        )
                        submission.state = current.model_copy(
                            update={
                                "status": m.SubmissionProcessingStatus.TECHNICAL_FAILURE,
                                "current_stage": row.stage,
                                "active_job_id": row.id,
                                "diagnostics": [failure],
                                "updated_at": reconciled_at,
                            }
                        ).model_dump(mode="json")
                        submission.updated_at = reconciled_at
            return len(rows)

    def claim_next_job(self, *, lease_seconds: int = 3900) -> JobRow | None:
        self.reconcile_stale_jobs(lease_seconds=lease_seconds)
        with self.session() as session:
            now = utc_now()
            statement = (
                select(JobRow)
                .where(
                    JobRow.status == "QUEUED",
                    JobRow.control_state == "ACTIVE",
                    JobRow.attempt < JobRow.max_attempts,
                    or_(
                        JobRow.next_attempt_at.is_(None),
                        JobRow.next_attempt_at <= now,
                    ),
                )
                .order_by(JobRow.created_at, JobRow.id)
                .limit(1)
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = session.scalar(statement)
            if row is None:
                return None
            row.status = "RUNNING"
            row.attempt += 1
            row.started_at = now
            row.finished_at = None
            row.next_attempt_at = None
            return row

    def claim_job(
        self, job_id: str, *, lease_seconds: int = 3900
    ) -> JobRow | None:
        """Atomically claim only the content-free ID dispatched to this worker."""

        if not 300 <= lease_seconds <= 7200:
            raise ValueError("job lease must be between 300 and 7200 seconds")
        with self.session() as session:
            now = utc_now()
            statement = select(JobRow).where(
                JobRow.id == job_id,
                JobRow.status == "QUEUED",
                JobRow.control_state == "ACTIVE",
                JobRow.attempt < JobRow.max_attempts,
                or_(
                    JobRow.next_attempt_at.is_(None),
                    JobRow.next_attempt_at <= now,
                ),
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = session.scalar(statement)
            if row is None:
                return None
            row.status = "RUNNING"
            row.attempt += 1
            row.started_at = now
            row.finished_at = None
            row.next_attempt_at = None
            return row

    @staticmethod
    def _synthetic_artifact_scope(
        session: Session,
        job: JobRow,
    ) -> tuple[str, list[ArtifactRow]]:
        """Resolve the exact sealed artifact scope from durable job ownership."""

        submission_id: str | None = None
        if job.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
            activity_id = job.aggregate_id
            activity = session.scalar(
                select(ActivityRow).where(
                    ActivityRow.id == activity_id,
                    ActivityRow.tenant_id == job.tenant_id,
                )
            )
            if activity is None:
                raise Conflict("SYNTHETIC_AUTHORIZATION_SCOPE_MISMATCH")
        elif job.kind in {"SUBMISSION", "QUESTION_ACTION"}:
            submission = session.scalar(
                select(SubmissionRow).where(
                    SubmissionRow.id == job.aggregate_id,
                    SubmissionRow.tenant_id == job.tenant_id,
                )
            )
            if submission is None:
                raise Conflict("SYNTHETIC_AUTHORIZATION_SCOPE_MISMATCH")
            activity_id = submission.activity_id
            submission_id = submission.id
        else:
            raise Conflict("SYNTHETIC_AUTHORIZATION_JOB_KIND_FORBIDDEN")

        artifact_scope = (
            ArtifactRow.submission_id.is_(None)
            if submission_id is None
            else or_(
                ArtifactRow.submission_id.is_(None),
                ArtifactRow.submission_id == submission_id,
            )
        )
        artifacts = list(
            session.scalars(
                select(ArtifactRow)
                .where(
                    ArtifactRow.tenant_id == job.tenant_id,
                    ArtifactRow.activity_id == activity_id,
                    artifact_scope,
                )
                .order_by(ArtifactRow.id)
            )
        )
        if not artifacts or any(
            artifact.status != "COMPLETE"
            or artifact.sha256 is None
            or artifact.byte_size is None
            or artifact.media_type is None
            for artifact in artifacts
        ):
            raise Conflict("SYNTHETIC_AUTHORIZATION_ARTIFACTS_NOT_SEALED")
        return activity_id, artifacts

    def synthetic_artifact_hashes_for_job(self, job_id: str) -> tuple[str, ...]:
        """Return only hashes, never artifact content, for operator attestation."""

        with self.session() as session:
            job = session.get(JobRow, job_id)
            if job is None:
                raise NotFound("job not found")
            _activity_id, artifacts = self._synthetic_artifact_scope(session, job)
            return tuple(sorted({str(artifact.sha256) for artifact in artifacts}))

    def authorize_synthetic_provider_job(
        self,
        spec: SyntheticProviderAuthorizationSpec,
    ) -> SyntheticProviderAuthorizationRow:
        """Persist one immutable authorization before its exact job is claimed."""

        now = utc_now()
        if spec.expires_at <= now:
            raise Conflict("SYNTHETIC_AUTHORIZATION_EXPIRED")
        try:
            with self.session() as session:
                statement = select(JobRow).where(JobRow.id == spec.job_id)
                if self.engine.dialect.name == "postgresql":
                    statement = statement.with_for_update()
                job = session.scalar(statement)
                if job is None:
                    raise NotFound("job not found")
                if any(
                    (
                        job.tenant_id != spec.tenant_id,
                        job.kind != spec.job_kind,
                        job.aggregate_id != spec.aggregate_id,
                        job.status != "QUEUED",
                        job.control_state != "ACTIVE",
                        job.attempt + 1 != spec.expected_claim_attempt,
                    )
                ):
                    raise Conflict("SYNTHETIC_AUTHORIZATION_JOB_MISMATCH")
                _activity_id, artifacts = self._synthetic_artifact_scope(session, job)
                actual_hashes = tuple(
                    sorted({str(artifact.sha256) for artifact in artifacts})
                )
                if actual_hashes != spec.artifact_hashes:
                    raise Conflict("SYNTHETIC_AUTHORIZATION_ARTIFACT_HASH_MISMATCH")
                row = SyntheticProviderAuthorizationRow(
                    id=spec.authorization_id,
                    tenant_id=spec.tenant_id,
                    job_id=spec.job_id,
                    job_kind=spec.job_kind,
                    aggregate_id=spec.aggregate_id,
                    expected_claim_attempt=spec.expected_claim_attempt,
                    artifact_hashes=list(spec.artifact_hashes),
                    candidate_sha=spec.candidate_sha,
                    boundary_hash=spec.boundary_hash,
                    route_profile=spec.route_profile,
                    model=spec.model,
                    secret_version_resource=spec.secret_version_resource,
                    max_requests=spec.max_requests,
                    max_cost_usd=spec.max_cost_usd,
                    classification=spec.classification,
                    schema_version=spec.schema_version,
                    authorization_hash=spec.authorization_hash,
                    created_by=spec.created_by,
                    created_at=now,
                    expires_at=spec.expires_at,
                )
                session.add(row)
                session.flush()
                return row
        except IntegrityError as exc:
            raise Conflict("SYNTHETIC_AUTHORIZATION_ALREADY_EXISTS") from exc

    @staticmethod
    def _authorization_spec_from_row(
        row: SyntheticProviderAuthorizationRow,
    ) -> SyntheticProviderAuthorizationSpec:
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return SyntheticProviderAuthorizationSpec(
            authorization_id=row.id,
            tenant_id=row.tenant_id,
            job_id=row.job_id,
            job_kind=row.job_kind,
            aggregate_id=row.aggregate_id,
            expected_claim_attempt=row.expected_claim_attempt,
            artifact_hashes=tuple(row.artifact_hashes),
            candidate_sha=row.candidate_sha,
            boundary_hash=row.boundary_hash,
            route_profile=row.route_profile,
            model=row.model,
            secret_version_resource=row.secret_version_resource,
            max_requests=row.max_requests,
            max_cost_usd=row.max_cost_usd,
            classification=row.classification,
            schema_version=row.schema_version,
            expires_at=expires_at,
            created_by=row.created_by,
        )

    def consume_synthetic_provider_authorization(
        self,
        *,
        job_id: str,
        candidate_sha: str,
        boundary_hash: str,
        route_profile: str,
        model: str,
        secret_version_resource: str,
        maximum_requests: int,
        maximum_cost_usd: float,
    ) -> SyntheticProviderGrant:
        """Atomically consume the exact attestation after an exact job claim."""

        try:
            with self.session() as session:
                job_statement = select(JobRow).where(JobRow.id == job_id)
                auth_statement = select(SyntheticProviderAuthorizationRow).where(
                    SyntheticProviderAuthorizationRow.job_id == job_id
                )
                if self.engine.dialect.name == "postgresql":
                    job_statement = job_statement.with_for_update()
                    auth_statement = auth_statement.with_for_update()
                job = session.scalar(job_statement)
                if job is None or job.status != "RUNNING":
                    raise Conflict("SYNTHETIC_AUTHORIZATION_EXACT_CLAIM_REQUIRED")
                authorization = session.scalar(auth_statement)
                if authorization is None:
                    raise Conflict("SYNTHETIC_AUTHORIZATION_REQUIRED")
                if session.scalar(
                    select(SyntheticProviderClaimRow).where(
                        SyntheticProviderClaimRow.authorization_id
                        == authorization.id
                    )
                ) is not None:
                    raise Conflict("SYNTHETIC_AUTHORIZATION_ALREADY_CONSUMED")

                spec = self._authorization_spec_from_row(authorization)
                now = utc_now()
                if spec.expires_at <= now:
                    raise Conflict("SYNTHETIC_AUTHORIZATION_EXPIRED")
                if authorization.authorization_hash != spec.authorization_hash:
                    raise Conflict("SYNTHETIC_AUTHORIZATION_HASH_MISMATCH")
                if any(
                    (
                        job.tenant_id != spec.tenant_id,
                        job.kind != spec.job_kind,
                        job.aggregate_id != spec.aggregate_id,
                        job.attempt != spec.expected_claim_attempt,
                        candidate_sha != spec.candidate_sha,
                        boundary_hash != spec.boundary_hash,
                        route_profile != spec.route_profile,
                        model != spec.model,
                        secret_version_resource != spec.secret_version_resource,
                        spec.max_requests > maximum_requests,
                        spec.max_cost_usd > maximum_cost_usd,
                    )
                ):
                    raise Conflict("SYNTHETIC_AUTHORIZATION_BOUNDARY_MISMATCH")
                _activity_id, artifacts = self._synthetic_artifact_scope(session, job)
                actual_hashes = tuple(
                    sorted({str(artifact.sha256) for artifact in artifacts})
                )
                if actual_hashes != spec.artifact_hashes:
                    raise Conflict("SYNTHETIC_AUTHORIZATION_ARTIFACT_HASH_MISMATCH")

                claim = SyntheticProviderClaimRow(
                    id=stable_id(
                        "syntheticclaim",
                        authorization.id,
                        authorization.authorization_hash,
                        job.id,
                        job.attempt,
                    ),
                    authorization_id=authorization.id,
                    authorization_hash=authorization.authorization_hash,
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    claim_attempt=job.attempt,
                    candidate_sha=candidate_sha,
                    boundary_hash=boundary_hash,
                    schema_version=SYNTHETIC_PROVIDER_CLAIM_VERSION,
                    claimed_at=now,
                )
                session.add(claim)
                session.flush()
                return SyntheticProviderGrant(
                    authorization_id=authorization.id,
                    authorization_hash=authorization.authorization_hash,
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    job_kind=job.kind,
                    aggregate_id=job.aggregate_id,
                    claim_attempt=job.attempt,
                    artifact_hashes=frozenset(spec.artifact_hashes),
                    candidate_sha=candidate_sha,
                    boundary_hash=boundary_hash,
                    route_profile=route_profile,
                    model=model,
                    secret_version_resource=secret_version_resource,
                    max_requests=spec.max_requests,
                    max_cost_usd=spec.max_cost_usd,
                    classification=spec.classification,
                )
        except IntegrityError as exc:
            raise Conflict("SYNTHETIC_AUTHORIZATION_ALREADY_CONSUMED") from exc

    def fail_claimed_job_security(self, *, job_id: str, code: str) -> None:
        """Fail a claimed job without preserving exception, artifact, or provider data."""

        allowed_codes = {
            "SYNTHETIC_AUTHORIZATION_REQUIRED",
            "SYNTHETIC_AUTHORIZATION_EXACT_CLAIM_REQUIRED",
            "SYNTHETIC_AUTHORIZATION_ALREADY_CONSUMED",
            "SYNTHETIC_AUTHORIZATION_EXPIRED",
            "SYNTHETIC_AUTHORIZATION_HASH_MISMATCH",
            "SYNTHETIC_AUTHORIZATION_BOUNDARY_MISMATCH",
            "SYNTHETIC_AUTHORIZATION_ARTIFACT_HASH_MISMATCH",
            "SYNTHETIC_AUTHORIZATION_SCOPE_MISMATCH",
            "SYNTHETIC_AUTHORIZATION_ARTIFACTS_NOT_SEALED",
            "SYNTHETIC_AUTHORIZATION_JOB_KIND_FORBIDDEN",
            "SYNTHETIC_PROVIDER_CREDENTIAL_UNAVAILABLE",
        }
        safe_code = code if code in allowed_codes else "SYNTHETIC_AUTHORIZATION_REJECTED"
        now = utc_now()
        failure = m.Diagnostic(
            code=safe_code,
            severity=m.Severity.ERROR,
            message="The synthetic provider boundary rejected the claimed job.",
            retryable=False,
        )
        with self.session() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise NotFound("job not found")
            if row.status != "RUNNING":
                raise Conflict("SYNTHETIC_AUTHORIZATION_EXACT_CLAIM_REQUIRED")
            row.status = "FAILED"
            row.failure_class = m.FailureClass.SECURITY.value
            row.diagnostics = [failure.model_dump(mode="json")]
            row.next_attempt_at = None
            row.finished_at = now
            if row.kind in {"ACTIVITY", "BLUEPRINT_REVIEW"}:
                activity = session.scalar(
                    select(ActivityRow).where(
                        ActivityRow.id == row.aggregate_id,
                        ActivityRow.tenant_id == row.tenant_id,
                    )
                )
                if activity is not None:
                    activity.status = "TECHNICAL_FAILURE"
                    activity.updated_at = now
            elif row.kind == "SUBMISSION":
                submission = session.scalar(
                    select(SubmissionRow).where(
                        SubmissionRow.id == row.aggregate_id,
                        SubmissionRow.tenant_id == row.tenant_id,
                    )
                )
                if (
                    submission is not None
                    and submission.active_job_id == row.id
                ):
                    current = m.SubmissionProcessingState.model_validate(
                        submission.state
                    )
                    submission.state = current.model_copy(
                        update={
                            "status": (
                                m.SubmissionProcessingStatus.TECHNICAL_FAILURE
                            ),
                            "current_stage": row.stage,
                            "active_job_id": row.id,
                            "diagnostics": [failure],
                            "updated_at": now,
                        }
                    ).model_dump(mode="json")
                    submission.updated_at = now

    def save_stage(
        self, *, job_id: str, tenant_id: str, stage: str, inputs: Any,
        component_version: str, policy_hash: str, output: dict[str, Any] | None,
        status: str = "SUCCEEDED", diagnostics: list[dict[str, Any]] | None = None,
        failure_class: str | None = None,
        next_attempt_at: datetime | None = None,
        attempt: int | None = None,
        resumed_from_stage_run_id: str | None = None,
    ) -> tuple[StageRunRow, bool]:
        if failure_class is not None and failure_class not in JOB_FAILURE_CLASSES:
            raise ValueError("unknown stage failure class")
        if status == "SUCCEEDED" and (
            failure_class is not None or next_attempt_at is not None
        ):
            raise ValueError("a succeeded stage cannot retain retry failure state")
        if status == "SUCCEEDED" and output is None:
            raise ValueError("a succeeded stage requires a reusable output")
        if status != "SUCCEEDED" and output is not None:
            raise ValueError("a non-succeeded stage cannot retain reusable output")
        input_hash = canonical_hash(inputs)
        stage_key = canonical_hash(
            {
                "tenant_id": tenant_id,
                "stage": stage,
                "inputs": inputs,
                "policy_hash": policy_hash,
                "component_version": component_version,
            }
        )
        output_hash = canonical_hash(output) if output is not None else None

        def valid_success(row: StageRunRow) -> bool:
            return all(
                (
                    row.tenant_id == tenant_id,
                    row.stage == stage,
                    row.stage_key == stage_key,
                    row.status == "SUCCEEDED",
                    row.input_hash == input_hash,
                    row.policy_hash == policy_hash,
                    row.component_version == component_version,
                    row.output_hash == canonical_hash(row.output),
                )
            )

        with self.sessions() as session:
            existing_success = session.scalar(
                select(StageRunRow).where(
                    StageRunRow.tenant_id == tenant_id,
                    StageRunRow.stage_key == stage_key,
                    StageRunRow.status == "SUCCEEDED",
                    StageRunRow.component_version == component_version,
                    StageRunRow.output_hash.is_not(None),
                )
            )
            if existing_success is not None:
                if not valid_success(existing_success):
                    raise Conflict("STAGE_REUSE_HASH_MISMATCH")
                return existing_success, True
            job = session.scalar(
                select(JobRow).where(
                    JobRow.id == job_id,
                    JobRow.tenant_id == tenant_id,
                )
            )
            stage_attempt = attempt or (job.attempt if job is not None else 1)
            if stage_attempt < 1:
                raise ValueError("stage attempt must be positive")
            existing_attempt = session.scalar(
                select(StageRunRow).where(
                    StageRunRow.job_id == job_id,
                    StageRunRow.stage_key == stage_key,
                    StageRunRow.attempt == stage_attempt,
                )
            )
            if existing_attempt is not None:
                if existing_attempt.status == "SUCCEEDED":
                    if not valid_success(existing_attempt):
                        raise Conflict("STAGE_REUSE_HASH_MISMATCH")
                    return existing_attempt, True
                if any(
                    (
                        existing_attempt.tenant_id != tenant_id,
                        existing_attempt.stage != stage,
                        existing_attempt.input_hash != input_hash,
                        existing_attempt.policy_hash != policy_hash,
                        existing_attempt.component_version != component_version,
                    )
                ):
                    raise Conflict("STAGE_ATTEMPT_CONFLICT")
                existing_attempt.status = status
                existing_attempt.output = output
                existing_attempt.output_hash = output_hash
                existing_attempt.failure_class = failure_class
                existing_attempt.next_attempt_at = next_attempt_at
                existing_attempt.diagnostics = diagnostics or []
                existing_attempt.finished_at = utc_now()
                session.commit()
                return existing_attempt, False
            executed_at = utc_now()
            row = StageRunRow(
                id=stable_id("stage", job_id, stage, stage_key, stage_attempt),
                job_id=job_id,
                tenant_id=tenant_id,
                stage=stage,
                stage_key=stage_key,
                status=status,
                attempt=stage_attempt,
                input_hash=input_hash,
                policy_hash=policy_hash,
                component_version=component_version,
                output=output,
                output_hash=output_hash,
                failure_class=failure_class,
                next_attempt_at=next_attempt_at,
                resumed_from_stage_run_id=resumed_from_stage_run_id,
                diagnostics=diagnostics or [],
                # SQLAlchemy evaluates column defaults during INSERT.  Setting
                # both timestamps explicitly prevents a sub-millisecond
                # inversion where ``finished_at`` was captured first and the
                # ``started_at`` default ran a moment later.
                started_at=executed_at,
                finished_at=executed_at,
            )
            session.add(row)
            try:
                session.commit()
                return row, False
            except IntegrityError:
                session.rollback()
                winner = session.scalar(
                    select(StageRunRow).where(
                        StageRunRow.tenant_id == tenant_id,
                        StageRunRow.stage_key == stage_key,
                        StageRunRow.status == "SUCCEEDED",
                        StageRunRow.component_version == component_version,
                        StageRunRow.output_hash.is_not(None),
                    )
                )
                if winner is not None and valid_success(winner):
                    return winner, True
                raise Conflict("STAGE_ATTEMPT_CONFLICT")

    def stage_by_key(
        self,
        *,
        tenant_id: str,
        stage: str,
        inputs: Any,
        policy_hash: str,
        component_version: str,
    ) -> StageRunRow | None:
        stage_key = canonical_hash(
            {
                "tenant_id": tenant_id,
                "stage": stage,
                "inputs": inputs,
                "policy_hash": policy_hash,
                "component_version": component_version,
            }
        )
        input_hash = canonical_hash(inputs)
        with self.session() as session:
            row = session.scalar(
                select(StageRunRow).where(
                    StageRunRow.tenant_id == tenant_id,
                    StageRunRow.stage_key == stage_key,
                    StageRunRow.status == "SUCCEEDED",
                    StageRunRow.component_version == component_version,
                    StageRunRow.output_hash.is_not(None),
                )
            )
            if row is None:
                return None
            expected_output_hash = canonical_hash(row.output)
            if any(
                (
                    row.stage != stage,
                    row.input_hash != input_hash,
                    row.policy_hash != policy_hash,
                    row.component_version != component_version,
                    row.output_hash != expected_output_hash,
                )
            ):
                return None
            return row

    def stage_runs_for_job(self, job_id: str, tenant_id: str) -> list[StageRunRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(StageRunRow)
                    .where(
                        StageRunRow.job_id == job_id,
                        StageRunRow.tenant_id == tenant_id,
                    )
                    .order_by(
                        StageRunRow.attempt,
                        StageRunRow.started_at,
                        StageRunRow.id,
                    )
                )
            )

    def model_call_sink(self, ledger: m.ModelCallLedger) -> None:
        self.add(
            ModelCallRow(
                id=ledger.model_call_id,
                tenant_id=ledger.tenant_id,
                job_id=ledger.job_id,
                stage=ledger.stage,
                data=ledger.model_dump(mode="json"),
            )
        )

    def model_calls(self, *, tenant_id: str, job_id: str | None = None) -> list[dict[str, Any]]:
        with self.session() as session:
            statement = select(ModelCallRow).where(ModelCallRow.tenant_id == tenant_id)
            if job_id is not None:
                statement = statement.where(ModelCallRow.job_id == job_id)
            rows = session.scalars(statement.order_by(ModelCallRow.id)).all()
            return [row.data for row in rows]

    def latest_assessment(self, submission_id: str, tenant_id: str) -> AssessmentRow:
        with self.session() as session:
            row = session.scalar(
                select(AssessmentRow)
                .where(
                    AssessmentRow.submission_id == submission_id,
                    AssessmentRow.tenant_id == tenant_id,
                )
                .order_by(AssessmentRow.version.desc())
                .limit(1)
            )
            if row is None:
                raise NotFound("assessment not found")
            return row

    def assessment_by_id(self, assessment_id: str, tenant_id: str) -> AssessmentRow:
        with self.session() as session:
            row = session.scalar(
                select(AssessmentRow)
                .where(
                    AssessmentRow.assessment_id == assessment_id,
                    AssessmentRow.tenant_id == tenant_id,
                )
                .order_by(AssessmentRow.version.desc())
                .limit(1)
            )
            if row is None:
                raise NotFound("assessment not found")
            return row

    def approve_assessment_atomic(
        self,
        *,
        expected_etag: str,
        approved_row: AssessmentRow,
        actor_id: str,
    ) -> AssessmentRow:
        """Commit approval version, submission projection, and audit together."""

        approved = m.Assessment.model_validate(approved_row.data)
        if approved.status != m.WorkflowStatus.APPROVED:
            raise ValueError("approved_row must contain an APPROVED assessment")
        if approved.approved_by != actor_id or approved.approved_at is None:
            raise ValueError("approval actor metadata is inconsistent")
        try:
            with self.session() as session:
                latest_statement = (
                    select(AssessmentRow)
                    .where(
                        AssessmentRow.assessment_id == approved_row.assessment_id,
                        AssessmentRow.tenant_id == approved_row.tenant_id,
                    )
                    .order_by(AssessmentRow.version.desc())
                    .limit(1)
                )
                if self.engine.dialect.name == "postgresql":
                    latest_statement = latest_statement.with_for_update()
                latest = session.scalar(latest_statement)
                if latest is None:
                    raise NotFound("assessment not found")
                if latest.etag != expected_etag:
                    raise Conflict("ETAG_MISMATCH")
                current = m.Assessment.model_validate(latest.data)
                if current.status != m.WorkflowStatus.NEEDS_REVIEW:
                    raise Conflict("ASSESSMENT_NOT_REVIEWABLE")
                if any(
                    (
                        approved_row.version != latest.version + 1,
                        approved_row.submission_id != latest.submission_id,
                        approved.submission_id != latest.submission_id,
                    )
                ):
                    raise Conflict("ASSESSMENT_VERSION_CONFLICT")

                submission_statement = select(SubmissionRow).where(
                    SubmissionRow.id == latest.submission_id,
                    SubmissionRow.tenant_id == latest.tenant_id,
                )
                if self.engine.dialect.name == "postgresql":
                    submission_statement = submission_statement.with_for_update()
                submission = session.scalar(submission_statement)
                if submission is None:
                    raise NotFound("submission not found")
                state = m.SubmissionProcessingState.model_validate(submission.state)
                if state.status != m.SubmissionProcessingStatus.NEEDS_REVIEW:
                    raise Conflict("ASSESSMENT_SUBMISSION_NOT_REVIEWABLE")

                session.add(approved_row)
                approved_at = approved.approved_at
                submission.state = state.model_copy(
                    update={
                        "status": m.SubmissionProcessingStatus.APPROVED,
                        "updated_at": approved_at,
                    }
                ).model_dump(mode="json")
                submission.updated_at = approved_at
                session.add(
                    AuditEventRow(
                        id=stable_id(
                            "evt",
                            approved_row.tenant_id,
                            "assessment.approved",
                            approved_row.assessment_id,
                            actor_id,
                            approved_row.version,
                        ),
                        tenant_id=approved_row.tenant_id,
                        event_type="assessment.approved",
                        aggregate_id=approved_row.assessment_id,
                        actor_id=actor_id,
                        payload={"assessment_version": approved_row.version},
                        occurred_at=approved_at,
                    )
                )
                session.flush()
                return approved_row
        except IntegrityError as exc:
            raise Conflict("ASSESSMENT_VERSION_CONFLICT") from exc

    def guide_for_assessment(self, assessment_id: str, tenant_id: str) -> GuideRow:
        with self.session() as session:
            row = session.scalar(
                select(GuideRow).where(
                    GuideRow.assessment_id == assessment_id,
                    GuideRow.tenant_id == tenant_id,
                )
            )
            if row is None:
                raise NotFound("guide not found")
            return row

    def review_rows(self, submission_id: str, tenant_id: str) -> list[QuestionReviewRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(QuestionReviewRow).where(
                        QuestionReviewRow.submission_id == submission_id,
                        QuestionReviewRow.tenant_id == tenant_id,
                    )
                )
            )

    def apply_question_review_action(
        self,
        record: m.QuestionReviewActionRecord,
        resulting_assessment: AssessmentRow | None = None,
        resulting_guide: GuideRow | None = None,
        terminal_job: JobRow | None = None,
        failure_class: m.FailureClass | None = None,
    ) -> QuestionReviewActionRow | None:
        """Apply a review record and any next immutable version atomically."""

        try:
            with self.session() as session:
                locked_job: JobRow | None = None
                if terminal_job is not None:
                    locked_job = self._lock_job(
                        session,
                        terminal_job.id,
                        record.tenant_id,
                        self.engine.dialect.name,
                    )
                    if (
                        locked_job.kind != "QUESTION_ACTION"
                        or locked_job.aggregate_id != record.submission_id
                    ):
                        raise Conflict("QUESTION_REVIEW_JOB_MISMATCH")
                    if locked_job.control_state != "ACTIVE":
                        if locked_job.control_state == "CANCEL_REQUESTED":
                            self._complete_job_cancellation(
                                session, locked_job, record.recorded_at
                            )
                        return None
                    if locked_job.status != "RUNNING":
                        raise Conflict("QUESTION_REVIEW_JOB_NOT_RUNNING")
                latest_statement = (
                    select(AssessmentRow)
                    .where(
                        AssessmentRow.assessment_id == record.assessment_id,
                        AssessmentRow.tenant_id == record.tenant_id,
                    )
                    .order_by(AssessmentRow.version.desc())
                    .limit(1)
                )
                if self.engine.dialect.name == "postgresql":
                    latest_statement = latest_statement.with_for_update()
                latest = session.scalar(latest_statement)
                if latest is None:
                    raise NotFound("assessment version not found")
                if (
                    latest.submission_id != record.submission_id
                    or latest.version != record.assessment_version_before
                ):
                    raise Conflict("QUESTION_REVIEW_STALE_VERSION")
                submission = session.scalar(
                    select(SubmissionRow).where(
                        SubmissionRow.id == record.submission_id,
                        SubmissionRow.tenant_id == record.tenant_id,
                        SubmissionRow.activity_id == record.activity_id,
                    )
                )
                if submission is None:
                    raise NotFound("submission not found")
                current = m.Assessment.model_validate(latest.data)
                persisted_question = next(
                    (
                        item
                        for item in current.questions
                        if item.question_id == record.action.question_id
                    ),
                    None,
                )
                if persisted_question is None:
                    raise NotFound("question not found")
                if persisted_question != record.before_question:
                    raise Conflict("QUESTION_REVIEW_BEFORE_SNAPSHOT_MISMATCH")

                action_type = record.action.action
                mutates_version = (
                    record.status == m.QuestionReviewRecordStatus.APPLIED
                    and action_type != m.QuestionReviewActionType.ACCEPT
                )
                if mutates_version:
                    if resulting_assessment is None:
                        raise Conflict("QUESTION_REVIEW_RESULTING_VERSION_REQUIRED")
                    if any(
                        (
                            resulting_assessment.tenant_id != record.tenant_id,
                            resulting_assessment.submission_id != record.submission_id,
                            resulting_assessment.assessment_id != record.assessment_id,
                            resulting_assessment.version
                            != record.assessment_version_after,
                        )
                    ):
                        raise Conflict("QUESTION_REVIEW_RESULTING_VERSION_MISMATCH")
                    m.Assessment.model_validate(resulting_assessment.data)
                    session.add(resulting_assessment)
                    if action_type in {
                        m.QuestionReviewActionType.EDIT,
                        m.QuestionReviewActionType.REGENERATE,
                    }:
                        if resulting_guide is not None:
                            if any(
                                (
                                    resulting_guide.tenant_id != record.tenant_id,
                                    resulting_guide.submission_id
                                    != record.submission_id,
                                    resulting_guide.assessment_id
                                    != record.assessment_id,
                                )
                            ):
                                raise Conflict("QUESTION_REVIEW_GUIDE_MISMATCH")
                            # EvaluationGuide keeps a stable canonical guide_id across
                            # assessment revisions.  Merge updates that durable row in
                            # the same transaction instead of attempting a second insert
                            # against its primary key.
                            session.merge(resulting_guide)
                    elif resulting_guide is not None:
                        raise Conflict("QUESTION_REVIEW_GUIDE_NOT_ALLOWED")
                elif resulting_assessment is not None or resulting_guide is not None:
                    raise Conflict("QUESTION_REVIEW_UNEXPECTED_RESULTING_VERSION")

                row = QuestionReviewActionRow(
                    id=record.record_id,
                    tenant_id=record.tenant_id,
                    activity_id=record.activity_id,
                    assessment_id=record.assessment_id,
                    assessment_version_before=record.assessment_version_before,
                    assessment_version_after=record.assessment_version_after,
                    submission_id=record.submission_id,
                    question_id=record.action.question_id,
                    actor_id=record.action.actor_id,
                    action=record.action.action.value,
                    status=record.status.value,
                    revalidation_status=record.revalidation_status.value,
                    before_snapshot_hash=canonical_hash(
                        record.before_question.model_dump(mode="json")
                    ),
                    after_snapshot_hash=(
                        canonical_hash(record.after_question.model_dump(mode="json"))
                        if record.after_question is not None
                        else None
                    ),
                    data=record.model_dump(mode="json"),
                    occurred_at=record.recorded_at,
                )
                session.add(row)
                if locked_job is not None:
                    job = locked_job
                    job.finished_at = record.recorded_at
                    job.next_attempt_at = None
                    if record.status == m.QuestionReviewRecordStatus.APPLIED:
                        if failure_class is not None:
                            raise ValueError("an applied action cannot fail its job")
                        job.stage = "QUESTION_ACTION"
                        job.status = "SUCCEEDED"
                        job.progress = 1.0
                        job.failure_class = None
                        job.diagnostics = []
                    else:
                        if failure_class is None:
                            raise ValueError("a failed action requires failure_class")
                        job.status = "FAILED"
                        job.failure_class = failure_class.value
                        job.diagnostics = [
                            item.model_dump(mode="json")
                            for item in record.diagnostics
                        ]
                session.flush()
        except IntegrityError as exc:
            raise Conflict("QUESTION_REVIEW_ACTION_ALREADY_EXISTS") from exc
        return row

    def question_review_actions(
        self,
        *,
        tenant_id: str,
        assessment_id: str,
        assessment_version: int | None = None,
        question_id: str | None = None,
    ) -> list[QuestionReviewActionRow]:
        with self.session() as session:
            statement = select(QuestionReviewActionRow).where(
                QuestionReviewActionRow.tenant_id == tenant_id,
                QuestionReviewActionRow.assessment_id == assessment_id,
            )
            if assessment_version is not None:
                statement = statement.where(
                    QuestionReviewActionRow.assessment_version_before
                    == assessment_version
                )
            if question_id is not None:
                statement = statement.where(
                    QuestionReviewActionRow.question_id == question_id
                )
            return list(
                session.scalars(
                    statement.order_by(
                        QuestionReviewActionRow.occurred_at,
                        QuestionReviewActionRow.id,
                    )
                )
            )

    def add_feedback_event(
        self, event: m.FeedbackEvent | FeedbackEventRow
    ) -> FeedbackEventRow:
        if isinstance(event, FeedbackEventRow):
            event = m.FeedbackEvent.model_validate(event.data)
        row = FeedbackEventRow(
            id=event.feedback_id,
            tenant_id=event.tenant_id,
            actor_id=event.actor_id,
            activity_id=event.activity_id,
            assessment_id=event.assessment_id,
            assessment_version=event.assessment_version,
            question_id=event.question_id,
            target_type=event.target_type.value,
            target_id=event.question_id or event.assessment_id or event.activity_id,
            rating=event.rating.value,
            category=event.category.value,
            data=event.model_dump(mode="json"),
            occurred_at=event.created_at,
        )
        try:
            with self.session() as session:
                activity = session.scalar(
                    select(ActivityRow).where(
                        ActivityRow.id == event.activity_id,
                        ActivityRow.tenant_id == event.tenant_id,
                    )
                )
                if activity is None:
                    raise NotFound("activity not found")
                if event.assessment_id is not None:
                    assessment = session.scalar(
                        select(AssessmentRow).where(
                            AssessmentRow.assessment_id == event.assessment_id,
                            AssessmentRow.tenant_id == event.tenant_id,
                            AssessmentRow.version == event.assessment_version,
                        )
                    )
                    if assessment is None:
                        raise NotFound("assessment version not found")
                session.add(row)
                session.flush()
        except IntegrityError as exc:
            raise Conflict("FEEDBACK_EVENT_ALREADY_EXISTS") from exc
        return row

    def feedback_events(
        self,
        *,
        tenant_id: str,
        target_type: str | None = None,
        activity_id: str | None = None,
        assessment_id: str | None = None,
        question_id: str | None = None,
    ) -> list[FeedbackEventRow]:
        with self.session() as session:
            statement = select(FeedbackEventRow).where(
                FeedbackEventRow.tenant_id == tenant_id
            )
            if target_type is not None:
                statement = statement.where(
                    FeedbackEventRow.target_type == target_type
                )
            if activity_id is not None:
                statement = statement.where(FeedbackEventRow.activity_id == activity_id)
            if assessment_id is not None:
                statement = statement.where(
                    FeedbackEventRow.assessment_id == assessment_id
                )
            if question_id is not None:
                statement = statement.where(FeedbackEventRow.question_id == question_id)
            return list(
                session.scalars(
                    statement.order_by(
                        FeedbackEventRow.occurred_at, FeedbackEventRow.id
                    )
                )
            )

    def add_bulk_approval_request(
        self, request: m.BulkApprovalRequest
    ) -> BulkApprovalRequestRow:
        row = BulkApprovalRequestRow(
            id=request.request_id,
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            target_count=len(request.targets),
            data=request.model_dump(mode="json"),
            requested_at=request.requested_at,
        )
        try:
            self.add(row)
        except IntegrityError as exc:
            raise Conflict("BULK_APPROVAL_REQUEST_ALREADY_EXISTS") from exc
        return row

    def bulk_approval_requests(
        self, *, tenant_id: str, actor_id: str | None = None
    ) -> list[BulkApprovalRequestRow]:
        with self.session() as session:
            statement = select(BulkApprovalRequestRow).where(
                BulkApprovalRequestRow.tenant_id == tenant_id
            )
            if actor_id is not None:
                statement = statement.where(
                    BulkApprovalRequestRow.actor_id == actor_id
                )
            return list(
                session.scalars(
                    statement.order_by(
                        BulkApprovalRequestRow.requested_at,
                        BulkApprovalRequestRow.id,
                    )
                )
            )

    def add_bulk_approval_record(
        self, record: m.BulkApprovalRecord
    ) -> BulkApprovalRecordRow:
        try:
            with self.session() as session:
                request = session.scalar(
                    select(BulkApprovalRequestRow).where(
                        BulkApprovalRequestRow.id == record.request_id,
                        BulkApprovalRequestRow.tenant_id == record.tenant_id,
                    )
                )
                if request is None:
                    raise NotFound("bulk approval request not found")
                if request.actor_id != record.actor_id:
                    raise Conflict("BULK_APPROVAL_ACTOR_MISMATCH")
                row = BulkApprovalRecordRow(
                    id=record.approval_id,
                    tenant_id=record.tenant_id,
                    request_id=record.request_id,
                    actor_id=record.actor_id,
                    approved_count=len(record.approved_targets),
                    excluded_count=len(record.excluded_targets),
                    data=record.model_dump(mode="json"),
                    approved_at=record.approved_at,
                )
                session.add(row)
                session.flush()
        except IntegrityError as exc:
            raise Conflict("BULK_APPROVAL_RECORD_ALREADY_EXISTS") from exc
        return row

    def bulk_approval_records(
        self, *, tenant_id: str, request_id: str | None = None
    ) -> list[BulkApprovalRecordRow]:
        with self.session() as session:
            statement = select(BulkApprovalRecordRow).where(
                BulkApprovalRecordRow.tenant_id == tenant_id
            )
            if request_id is not None:
                statement = statement.where(
                    BulkApprovalRecordRow.request_id == request_id
                )
            return list(
                session.scalars(
                    statement.order_by(
                        BulkApprovalRecordRow.approved_at,
                        BulkApprovalRecordRow.id,
                    )
                )
            )

    def set_export_snapshot_metadata(
        self,
        *,
        export_id: str,
        tenant_id: str,
        assessment_version: int,
        snapshot_hash: str,
        component_version: str,
    ) -> ExportRow:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot_hash) is None:
            raise ValueError("snapshot_hash must be a canonical sha256 hash")
        with self.session() as session:
            statement = select(ExportRow).where(
                ExportRow.id == export_id,
                ExportRow.tenant_id == tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                raise NotFound("export not found")
            assessment = session.scalar(
                select(AssessmentRow).where(
                    AssessmentRow.assessment_id == row.assessment_id,
                    AssessmentRow.tenant_id == tenant_id,
                    AssessmentRow.version == assessment_version,
                )
            )
            if assessment is None:
                raise NotFound("assessment version not found")
            expected = (assessment_version, snapshot_hash, component_version)
            current = (
                row.assessment_version,
                row.assessment_snapshot_hash,
                row.renderer_version,
            )
            if any(value is not None for value in current) and current != expected:
                raise Conflict("EXPORT_SNAPSHOT_ALREADY_BOUND")
            row.assessment_version = assessment_version
            row.assessment_snapshot_hash = snapshot_hash
            row.renderer_version = component_version
            return row

    def save_export_record(self, record: m.ExportRecord) -> ExportRow:
        """Persist a capability-free canonical export snapshot for later reload."""

        artifacts = {
            item.kind.value: item.model_dump(mode="json") for item in record.artifacts
        }
        with self.session() as session:
            statement = select(ExportRow).where(
                ExportRow.id == record.export_id,
                ExportRow.tenant_id == record.tenant_id,
            )
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                row = ExportRow(
                    id=record.export_id,
                    tenant_id=record.tenant_id,
                    assessment_id=record.assessment_id,
                    status=record.status.value,
                    artifacts=artifacts,
                    created_at=record.requested_at,
                )
                session.add(row)
            elif row.assessment_id != record.assessment_id:
                raise Conflict("EXPORT_ASSESSMENT_MISMATCH")
            row.activity_id = record.activity_id
            row.assessment_version = record.assessment_version
            row.assessment_snapshot_hash = record.assessment_snapshot_hash
            row.renderer_version = record.renderer_version
            row.requested_by = record.requested_by
            row.requested_kinds = [item.value for item in record.requested_kinds]
            row.guide_snapshot_hash = record.guide_snapshot_hash
            row.coverage_snapshot_hash = record.coverage_snapshot_hash
            row.completed_at = record.completed_at
            row.data = record.model_dump(mode="json")
            row.status = record.status.value
            row.artifacts = artifacts
            return row

    def list_exports(self, assessment_id: str, tenant_id: str) -> list[ExportRow]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(ExportRow)
                    .where(
                        ExportRow.assessment_id == assessment_id,
                        ExportRow.tenant_id == tenant_id,
                    )
                    .order_by(ExportRow.created_at.desc(), ExportRow.id.desc())
                )
            )

    def audit(
        self,
        *,
        tenant_id: str,
        event_type: str,
        aggregate_id: str,
        actor_id: str,
        payload: dict[str, Any],
    ) -> AuditEventRow:
        row = AuditEventRow(
            id=stable_id(
                "evt", tenant_id, event_type, aggregate_id, actor_id, utc_now()
            ),
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            actor_id=actor_id,
            payload=payload,
        )
        self.add(
            row
        )
        return row

    def audit_events(
        self,
        *,
        tenant_id: str,
        event_type: str,
        aggregate_id: str | None,
        actor_id: str | None = None,
    ) -> list[AuditEventRow]:
        """Return tenant-scoped audit evidence without inspecting payload text."""

        with self.session() as session:
            statement = select(AuditEventRow).where(
                AuditEventRow.tenant_id == tenant_id,
                AuditEventRow.event_type == event_type,
            )
            if aggregate_id is not None:
                statement = statement.where(
                    AuditEventRow.aggregate_id == aggregate_id
                )
            if actor_id is not None:
                statement = statement.where(AuditEventRow.actor_id == actor_id)
            return list(
                session.scalars(
                    statement.order_by(AuditEventRow.occurred_at, AuditEventRow.id)
                )
            )

    def has_audit_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        aggregate_id: str,
        actor_id: str | None = None,
        payload_contains: dict[str, Any] | None = None,
    ) -> bool:
        rows = self.audit_events(
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            actor_id=actor_id,
        )
        return any(
            payload_contains is None
            or all(
                row.payload.get(key) == value
                for key, value in payload_contains.items()
            )
            for row in rows
        )

    def reserve_idempotency(
        self,
        tenant_id: str,
        key: str,
        fingerprint: str,
        *,
        ttl_seconds: int = 86_400,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Reserve a key atomically, returning its completed replay descriptor.

        ``None`` means the caller owns a new reservation. An existing NULL row
        is deliberately a conflict instead of permitting duplicate side
        effects while the winning request is still running.
        """

        if not 300 <= ttl_seconds <= 604_800:
            raise ValueError("idempotency ttl must be between 300 and 604800 seconds")
        reference_time = now or utc_now()
        expires_at = reference_time + timedelta(seconds=ttl_seconds)

        def inspect(session: Session) -> dict[str, Any] | None:
            row = session.scalar(
                select(IdempotencyRow).where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == key,
                )
            )
            if row is None:
                raise Conflict("IDEMPOTENCY_RESERVATION_LOST")
            if row.fingerprint != fingerprint:
                raise Conflict("IDEMPOTENCY_KEY_REUSED")
            if row.response is None:
                raise Conflict("IDEMPOTENCY_REQUEST_IN_PROGRESS")
            return dict(row.response)

        with self.sessions() as session:
            # Expiration applies only to completed replay descriptors. An
            # in-flight reservation remains a conflict: reclaiming it could
            # execute the same domain mutation twice after a process crash.
            session.execute(
                delete(IdempotencyRow).where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == key,
                    IdempotencyRow.response.is_not(None),
                    IdempotencyRow.expires_at <= reference_time,
                )
            )
            session.flush()
            existing = session.scalar(
                select(IdempotencyRow).where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == key,
                )
            )
            if existing is not None:
                return inspect(session)
            session.add(
                IdempotencyRow(
                    id=stable_id("idem", tenant_id, key),
                    tenant_id=tenant_id,
                    key=key,
                    fingerprint=fingerprint,
                    response=None,
                    expires_at=expires_at,
                )
            )
            try:
                session.commit()
                return None
            except IntegrityError:
                session.rollback()
                return inspect(session)

    def complete_idempotency(
        self,
        tenant_id: str,
        key: str,
        fingerprint: str,
        response: dict[str, Any],
        *,
        ttl_seconds: int = 86_400,
        now: datetime | None = None,
    ) -> None:
        if not 300 <= ttl_seconds <= 604_800:
            raise ValueError("idempotency ttl must be between 300 and 604800 seconds")
        if _contains_transient_capability(response):
            raise ValueError("IDEMPOTENCY_RESPONSE_CONTAINS_TRANSIENT_CAPABILITY")
        with self.session() as session:
            row = session.scalar(
                select(IdempotencyRow).where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == key,
                )
            )
            if row is None or row.fingerprint != fingerprint:
                raise Conflict("IDEMPOTENCY_RESERVATION_LOST")
            if row.response is not None and row.response != response:
                raise Conflict("IDEMPOTENCY_RESPONSE_CONFLICT")
            row.response = response
            row.expires_at = (now or utc_now()) + timedelta(seconds=ttl_seconds)

    def release_idempotency(self, tenant_id: str, key: str, fingerprint: str) -> None:
        with self.session() as session:
            session.execute(
                delete(IdempotencyRow).where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == key,
                    IdempotencyRow.fingerprint == fingerprint,
                    or_(
                        IdempotencyRow.response.is_(None),
                        cast(IdempotencyRow.response, Text) == "null",
                    ),
                )
            )
