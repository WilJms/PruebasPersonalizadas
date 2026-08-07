"""Durable Stage 1 repository backed by PostgreSQL or SQLite in tests.

Only JSON snapshots of canonical contracts are stored here; the contract
classes remain defined exclusively in ``specification/models_v1.1(1).py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import re
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
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


IDEMPOTENCY_CAPABILITY_CONSTRAINT = "ck_idempotency_keys_safe_response"


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
    __table_args__ = (UniqueConstraint("activity_id"),)
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
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StageRunRow(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (UniqueConstraint("stage_key"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str] = mapped_column(String(128))
    stage_key: Mapped[str] = mapped_column(String(71))
    status: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_hash: Mapped[str] = mapped_column(String(71))
    policy_hash: Mapped[str] = mapped_column(String(71))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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
    status: Mapped[str] = mapped_column(String(32))
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
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
        """Check connectivity and the final expected Stage 1 schema surface.

        PostgreSQL must expose the final idempotency capability constraint;
        local adapters require the ORM table. Both fixed queries return no
        application data and let connection or migration errors fail closed.
        """

        with self.engine.connect() as connection:
            if self.engine.dialect.name == "postgresql":
                constraint_exists = connection.scalar(
                    text(
                        """
                        select exists (
                          select 1
                          from pg_constraint
                          where conrelid = to_regclass('public.idempotency_keys')
                            and conname = :constraint_name
                        )
                        """
                    ),
                    {"constraint_name": IDEMPOTENCY_CAPABILITY_CONSTRAINT},
                )
                if not constraint_exists:
                    raise RepositoryError("EXPECTED_MIGRATION_SURFACE_MISSING")
            else:
                connection.execute(text("select 1 from idempotency_keys limit 0"))

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

    def submission_for_activity(self, activity_id: str, tenant_id: str) -> SubmissionRow | None:
        with self.session() as session:
            return session.scalar(
                select(SubmissionRow).where(
                    SubmissionRow.activity_id == activity_id,
                    SubmissionRow.tenant_id == tenant_id,
                )
            )

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
            started_at=status.started_at,
            finished_at=status.finished_at,
        )

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

    def save_job_status(self, status: m.JobStatus, *, kind: str | None = None) -> None:
        with self.session() as session:
            row = session.get(JobRow, status.job_id)
            if row is None:
                if kind is None:
                    raise NotFound("job not found")
                row = self._job_row(status, kind)
                session.add(row)
            else:
                row.stage = status.stage
                row.status = status.status
                row.progress = status.progress
                row.attempt = status.attempt
                row.diagnostics = [item.model_dump(mode="json") for item in status.diagnostics]
                row.started_at = status.started_at
                row.finished_at = status.finished_at

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

    def claim_next_job(self) -> JobRow | None:
        with self.session() as session:
            statement = (
                select(JobRow)
                .where(JobRow.status == "QUEUED")
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
            row.started_at = utc_now()
            return row

    def save_stage(
        self, *, job_id: str, tenant_id: str, stage: str, inputs: Any,
        component_version: str, policy_hash: str, output: dict[str, Any] | None,
        status: str = "SUCCEEDED", diagnostics: list[dict[str, Any]] | None = None,
    ) -> tuple[StageRunRow, bool]:
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
        with self.session() as session:
            existing = session.scalar(select(StageRunRow).where(StageRunRow.stage_key == stage_key))
            if existing is not None:
                return existing, True
            row = StageRunRow(
                id=stable_id("stage", job_id, stage, stage_key),
                job_id=job_id,
                tenant_id=tenant_id,
                stage=stage,
                stage_key=stage_key,
                status=status,
                attempt=1,
                input_hash=input_hash,
                policy_hash=policy_hash,
                output=output,
                diagnostics=diagnostics or [],
                finished_at=utc_now(),
            )
            session.add(row)
            return row, False

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
        with self.session() as session:
            return session.scalar(
                select(StageRunRow).where(
                    StageRunRow.tenant_id == tenant_id,
                    StageRunRow.stage_key == stage_key,
                    StageRunRow.status == "SUCCEEDED",
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
        aggregate_id: str,
        actor_id: str | None = None,
    ) -> list[AuditEventRow]:
        """Return tenant-scoped audit evidence without inspecting payload text."""

        with self.session() as session:
            statement = select(AuditEventRow).where(
                AuditEventRow.tenant_id == tenant_id,
                AuditEventRow.event_type == event_type,
                AuditEventRow.aggregate_id == aggregate_id,
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
        self, tenant_id: str, key: str, fingerprint: str
    ) -> dict[str, Any] | None:
        """Reserve a key atomically, returning its completed replay descriptor.

        ``None`` means the caller owns a new reservation. An existing NULL row
        is deliberately a conflict instead of permitting duplicate side
        effects while the winning request is still running.
        """

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
    ) -> None:
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
