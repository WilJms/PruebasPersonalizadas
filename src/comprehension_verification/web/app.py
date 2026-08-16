"""FastAPI shell for the private Stage 2 experimental environment."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
import secrets
from time import monotonic
from typing import Annotated, Any, cast
from uuid import UUID

import jwt
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from ..canonical import canonical_hash, stable_id
from ..contracts import models as m
from .auth import Actor
from . import dto
from .object_store import MemoryObjectStore, ObjectSizeExceeded, ObjectStore
from .repository import (
    ActivityRow,
    ArtifactRow,
    Conflict,
    ExportRow,
    EvidenceRow,
    FeedbackEventRow,
    NotFound,
    PolicyDecisionRow,
    QuestionReviewActionRow,
    Repository,
    SubmissionRow,
    BulkApprovalRecordRow,
)
from .rate_limit import FixedWindowRateLimiter
from .runtime import Runtime, build_runtime
from .settings import Settings, get_settings
from .workflows import ALLOWED_MEDIA_TYPES, Stage1Service, WorkflowError


HTTP_LOGGER = logging.getLogger("cva.http")
SHELL_CACHE_EPOCH = "stage2-v1"
if not HTTP_LOGGER.handlers:
    _http_handler = logging.StreamHandler()
    _http_handler.setFormatter(logging.Formatter("%(message)s"))
    HTTP_LOGGER.addHandler(_http_handler)
HTTP_LOGGER.setLevel(logging.INFO)
HTTP_LOGGER.propagate = False

PROBLEM_RESPONSES = {
    status: {
        "description": "RFC 9457-style problem detail",
        "model": m.ProblemDetail,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"}
            }
        },
    }
    for status in (401, 403, 404, 409, 410, 412, 422, 428, 429, 500)
}

# Every authenticated JSON mutation must have an explicit, content-minimal
# replay recipe before its side effect is allowed to run. This makes a newly
# added route fail closed instead of silently persisting its full response.
_ID_PATH = r"[a-z][a-z0-9_-]{2,127}"
IDEMPOTENT_MUTATION_ROUTES = (
    ("POST", re.compile(r"^/api/v1/activities$"), "/api/v1/activities"),
    ("PATCH", re.compile(rf"^/api/v1/activities/{_ID_PATH}$"), "/api/v1/activities/{activity_id}"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/artifacts/uploads$"), "/api/v1/activities/{activity_id}/artifacts/uploads"),
    ("POST", re.compile(rf"^/api/v1/submissions/{_ID_PATH}/artifacts/uploads$"), "/api/v1/submissions/{submission_id}/artifacts/uploads"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/artifacts/{_ID_PATH}:complete$"), "/api/v1/activities/{activity_id}/artifacts/{artifact_id}:complete"),
    ("POST", re.compile(rf"^/api/v1/submissions/{_ID_PATH}/artifacts/{_ID_PATH}:complete$"), "/api/v1/submissions/{submission_id}/artifacts/{artifact_id}:complete"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/blueprints:generate$"), "/api/v1/activities/{activity_id}/blueprints:generate"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/decisions$"), "/api/v1/activities/{activity_id}/decisions"),
    ("PATCH", re.compile(rf"^/api/v1/activities/{_ID_PATH}/blueprints/[1-9][0-9]*$"), "/api/v1/activities/{activity_id}/blueprints/{version}"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/blueprints/[1-9][0-9]*:approve$"), "/api/v1/activities/{activity_id}/blueprints/{version}:approve"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/submissions$"), "/api/v1/activities/{activity_id}/submissions"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/submissions:batch$"), "/api/v1/activities/{activity_id}/submissions:batch"),
    ("POST", re.compile(rf"^/api/v1/submissions/{_ID_PATH}:run$"), "/api/v1/submissions/{submission_id}:run"),
    ("POST", re.compile(rf"^/api/v1/jobs/{_ID_PATH}:(retry|cancel|resume)$"), "/api/v1/jobs/{job_id}:control"),
    ("POST", re.compile(r"^/api/v1/feedback$"), "/api/v1/feedback"),
    ("POST", re.compile(rf"^/api/v1/assessments/{_ID_PATH}/questions/{_ID_PATH}/actions$"), "/api/v1/assessments/{assessment_id}/questions/{question_id}/actions"),
    ("POST", re.compile(rf"^/api/v1/assessments/{_ID_PATH}/evidence:verify$"), "/api/v1/assessments/{assessment_id}/evidence:verify"),
    ("POST", re.compile(rf"^/api/v1/assessments/{_ID_PATH}:approve$"), "/api/v1/assessments/{assessment_id}:approve"),
    ("POST", re.compile(rf"^/api/v1/assessments/{_ID_PATH}/exports$"), "/api/v1/assessments/{assessment_id}/exports"),
    ("POST", re.compile(rf"^/api/v1/activities/{_ID_PATH}/assessments:bulk-approve$"), "/api/v1/activities/{activity_id}/assessments:bulk-approve"),
)


def _idempotent_mutation_template(method: str, path: str) -> str | None:
    for expected_method, pattern, template in IDEMPOTENT_MUTATION_ROUTES:
        if method == expected_method and pattern.fullmatch(path):
            return template
    return None


def _safe_route_template(request: Request) -> str:
    """Return a framework route template, never a user-controlled URL/path."""

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/") and len(template) <= 500:
        return template
    return "/api/unmatched" if request.scope.get("type") == "http" else "/unmatched"


def _problem(status_code: int, code: str, detail: str, request: Request) -> JSONResponse:
    problem = m.ProblemDetail(
        title="Request could not be completed",
        status=status_code,
        detail=detail,
        instance=_safe_route_template(request),
        code=code,
        trace_id=stable_id("trace", secrets.token_hex(16)),
        retryable=status_code >= 500 or status_code == 429,
    )
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=status_code,
        media_type="application/problem+json",
    )


def _utc_json_datetime(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _activity_payload(row: ActivityRow, repository: Repository) -> dict[str, Any]:
    value = dict(row.config)
    blueprint = None
    value.update(
        {
            "activity_id": row.id,
            "status": row.status,
            "created_at": _utc_json_datetime(row.created_at),
            "updated_at": _utc_json_datetime(row.updated_at),
        }
    )
    try:
        blueprint = repository.latest_blueprint(row.id, row.tenant_id)
        value["latest_blueprint_version"] = blueprint.version
        value["approved_blueprint_version"] = (
            blueprint.version if blueprint.status == "APPROVED" else None
        )
    except NotFound:
        value["latest_blueprint_version"] = None
        value["approved_blueprint_version"] = None
    submission = repository.submission_for_activity(row.id, row.tenant_id)
    activity_job = repository.latest_job_for_aggregate(row.id, row.tenant_id)
    submission_job = (
        repository.latest_job_for_aggregate(submission.id, row.tenant_id)
        if submission is not None
        else None
    )
    job = (
        activity_job
        if activity_job is not None
        and activity_job.stage in {"BLUEPRINT_PREFLIGHT", "BLUEPRINT_REVIEW"}
        and activity_job.status
        in {"QUEUED", "RUNNING", "FAILED", "NEEDS_REVIEW"}
        else submission_job or activity_job
    )
    assessment_row = None
    if submission is not None:
        value["submission_id"] = submission.id
        try:
            assessment_row = repository.latest_assessment(
                submission.id, row.tenant_id
            )
        except NotFound:
            assessment_row = None

    if assessment_row is not None:
        continue_path = f"/submissions/{submission.id}/review"
        next_action = "REVIEW_ASSESSMENT"
    elif submission is not None:
        submission_state = m.SubmissionProcessingState.model_validate(submission.state)
        if (
            submission_state.status == m.SubmissionProcessingStatus.UPLOADED
            and submission.active_job_id is None
        ):
            continue_path = f"/submissions/{submission.id}"
            next_action = "RUN_SUBMISSION"
        else:
            continue_path = f"/submissions/{submission.id}"
            next_action = "VIEW_PROGRESS"
    elif blueprint is not None and blueprint.status == "APPROVED":
        continue_path = f"/activities/{row.id}/submission"
        next_action = "UPLOAD_SUBMISSION"
    elif row.status == "DRAFT":
        continue_path = f"/activities/{row.id}/edit"
        next_action = "EDIT_ACTIVITY"
    else:
        continue_path = f"/activities/{row.id}/blueprint"
        next_action = (
            "VIEW_PROGRESS"
            if job is not None and job.status in {"QUEUED", "RUNNING"}
            else "REVIEW_BLUEPRINT"
        )

    value["journey"] = {
        "continue_path": continue_path,
        "next_action": next_action,
        "blueprint": (
            {
                "version": blueprint.version,
                "status": blueprint.status,
                "etag": blueprint.etag,
            }
            if blueprint is not None
            else None
        ),
        "submission": (
            {
                "submission_id": submission.id,
                "status": m.SubmissionProcessingState.model_validate(
                    submission.state
                ).status,
                "active_job_id": submission.active_job_id,
            }
            if submission is not None
            else None
        ),
        "job": (
            {
                "job_id": job.job_id,
                "stage": job.stage,
                "status": job.status,
                "progress": job.progress,
            }
            if job is not None
            else None
        ),
        "assessment": (
            {
                "assessment_id": assessment_row.assessment_id,
                "version": assessment_row.version,
                "status": assessment_row.status,
                "etag": assessment_row.etag,
            }
            if assessment_row is not None
            else None
        ),
    }
    return value


def _activity_response(
    row: ActivityRow,
    repository: Repository,
    response: Response,
) -> dto.ActivityEnvelope:
    response.headers["ETag"] = f'"{canonical_hash(row.config)}"'
    return dto.ActivityEnvelope.model_validate(
        {"activity": _activity_payload(row, repository)}
    )


def _artifact_payload(row: ArtifactRow) -> dict[str, Any]:
    return {
        "artifact_id": row.id,
        "activity_id": row.activity_id,
        "submission_id": row.submission_id,
        "role": row.role,
        "filename": row.filename,
        "media_type": row.media_type or row.declared_media_type,
        "expected_byte_size": row.expected_byte_size,
        "byte_size": row.byte_size,
        "sha256": row.sha256,
        "status": row.status,
    }


def _submission_payload(row: SubmissionRow, repository: Repository) -> dict[str, Any]:
    state = m.SubmissionProcessingState.model_validate(row.state).model_dump(mode="json")
    state.update(
        {
            "submission_id": row.id,
            "activity_id": row.activity_id,
            "subject_ref": row.subject_ref,
            "artifact_uploaded": bool(
                repository.artifacts_for(
                    activity_id=row.activity_id,
                    tenant_id=row.tenant_id,
                    submission_id=row.id,
                )
            ),
        }
    )
    try:
        assessment = repository.latest_assessment(row.id, row.tenant_id)
        state["assessment_id"] = assessment.assessment_id
        state["assessment_version"] = assessment.version
    except NotFound:
        state["assessment_id"] = None
        state["assessment_version"] = None
    return state


def _blueprint_response(
    row: Any,
    response: Response,
    *,
    preflight: dict[str, Any] | None = None,
    issues: list[dict[str, Any]] | None = None,
) -> dto.BlueprintEnvelope:
    response.headers["ETag"] = row.etag
    return dto.BlueprintEnvelope.model_validate(
        {
            "blueprint": row.data,
            "preflight": preflight if preflight is not None else row.preflight,
            "review": row.review,
            "issues": (
                issues
                if issues is not None
                else (row.data or {}).get("diagnostics", [])
            ),
            "etag": row.etag,
            "version": row.version,
        }
    )


def create_app(
    settings: Settings | None = None,
    *,
    repository: Repository | None = None,
    object_store: ObjectStore | None = None,
    job_runner: Any | None = None,
    inline_wait_for_completion: bool = False,
) -> FastAPI:
    selected = settings or get_settings()
    runtime = build_runtime(
        selected,
        repository=repository,
        object_store=object_store,
        job_runner=job_runner,
        inline_wait_for_completion=inline_wait_for_completion,
    )
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Approval and guide scheduling are intentionally separate commits.
        # Startup closes the only crash gap without revisiting human approval.
        await runtime.service.reconcile_approved_guide_jobs()
        yield

    app = FastAPI(
        title="Comprehension Verification Lab",
        version="0.4.0",
        docs_url="/api/docs" if selected.environment != "cloud" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if selected.environment != "cloud" else None,
        responses=PROBLEM_RESPONSES,
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    rate_limiter = FixedWindowRateLimiter()

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        started = monotonic()
        response: Response
        if request.url.path.startswith("/api/v1/"):
            try:
                actor = runtime.auth.authenticate(request)
                principal_key = f"{actor.workspace_id}:{actor.user_id}"
            except HTTPException:
                peer = request.client.host if request.client is not None else "unknown"
                principal_key = canonical_hash({"peer": peer})
            mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
            limit = (
                selected.api_mutation_rate_limit_per_minute
                if mutation
                else selected.api_read_rate_limit_per_minute
            )
            allowed, retry_after = rate_limiter.consume(
                f"{'mutation' if mutation else 'read'}:{principal_key}",
                limit=limit,
            )
            if not allowed:
                response = _problem(
                    429,
                    "RATE_LIMITED",
                    "The private experimental API rate limit was reached.",
                    request,
                )
                response.headers["Retry-After"] = str(retry_after)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "connect-src 'self' https:; object-src 'none'"
        )
        route_template = _safe_route_template(request)
        if route_template.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if (
            request.method == "GET"
            and request.url.path == "/api/v1/session"
            and request.headers.get("X-CVA-Shell-Epoch") != SHELL_CACHE_EPOCH
        ):
            # Shells cached before HTML responses became ``no-store`` still
            # call this endpoint on startup. Clear only their HTTP cache; the
            # current authenticated session and all browser storage survive.
            response.headers["Clear-Site-Data"] = '"cache"'
        HTTP_LOGGER.info(
            json.dumps(
                {
                    "event": "http.request.completed",
                    "method": request.method,
                    "route": route_template,
                    "status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return response

    def current_assessment_bundle(submission_id: str, actor: Actor) -> dict[str, Any]:
        value = runtime.stage2.assessment_review_view(submission_id, actor)
        value["evidence"] = [
            item["evidence"]
            for item in runtime.service.evidence_view(submission_id, actor)
        ]
        return dto.AssessmentEnvelope.model_validate(value).model_dump(mode="json")

    def replay_response(
        descriptor: dict[str, Any], actor: Actor
    ) -> JSONResponse:
        current_authorization = {
            "principal_id": actor.user_id,
            "role": actor.role,
            "can_approve_assessments": actor.can_approve_assessments,
        }
        if descriptor.get("authorization") != current_authorization:
            # Historical descriptors and changed memberships fail closed. A
            # replay must never become a capability transfer between actors.
            raise Conflict("IDEMPOTENCY_PRINCIPAL_MISMATCH")
        kind = descriptor.get("kind")
        if kind == "upload":
            artifact = cast(
                ArtifactRow,
                runtime.repository.scoped(
                    ArtifactRow, str(descriptor["artifact_id"]), actor.workspace_id
                ),
            )
            pending_key = descriptor.get("upload_object_key")
            expected_prefix = (
                f"raw/{artifact.tenant_id}/{artifact.activity_id}/{artifact.id}/"
            )
            if (
                not isinstance(pending_key, str)
                or not pending_key.startswith(expected_prefix)
                or "/sealed/" in pending_key
            ):
                raise Conflict("IDEMPOTENCY_UPLOAD_RESERVATION_INVALID")
            signed = runtime.object_store.sign_put(
                pending_key,
                artifact.declared_media_type,
                artifact.expected_byte_size,
            )
            body = dto.UploadEnvelope.model_validate(
                {
                    "upload": {
                        "artifact_id": artifact.id,
                        "upload_url": signed.url,
                        "expires_at": signed.expires_at.isoformat(),
                        "upload_headers": signed.headers,
                        # Reproduce the historical upload-session projection,
                        # not the Artifact row's later COMPLETE/REJECTED state.
                        "artifact": {
                            **_artifact_payload(artifact),
                            "media_type": artifact.declared_media_type,
                            "byte_size": None,
                            "sha256": None,
                            "status": "PENDING",
                        },
                    }
                }
            ).model_dump(mode="json")
        elif kind == "export":
            row = cast(
                ExportRow,
                runtime.repository.scoped(
                    ExportRow, str(descriptor["export_id"]), actor.workspace_id
                ),
            )
            if row.data is None:
                raise Conflict("IDEMPOTENCY_EXPORT_SNAPSHOT_MISSING")
            record = m.ExportRecord.model_validate(row.data)
            requested_kinds = [m.ExportKind(value) for value in descriptor["export_kinds"]]
            downloads = [
                item
                for item in runtime.stage2.export_downloads(record, actor)
                if item["kind"] in requested_kinds
            ]
            if not downloads:
                raise Conflict("IDEMPOTENCY_EXPORT_ARTIFACT_MISSING")
            item = downloads[0]
            body = dto.ExportCreateEnvelope.model_validate(
                {
                    "export": {
                        "export_id": row.id,
                        "kind": item["kind"],
                        "status": row.status,
                        "download_url": item["download_url"],
                        "expires_at": item["expires_at"],
                        "sha256": item["sha256"],
                        "byte_size": item["byte_size"],
                    },
                    "record": record,
                    "downloads": downloads,
                }
            ).model_dump(mode="json")
        elif kind == "evidence_verify":
            receipt = dto.EvidenceReceipt.model_validate(descriptor["receipt"])
            evidence_row = cast(
                EvidenceRow,
                runtime.repository.scoped(
                    EvidenceRow, receipt.evidence_id, actor.workspace_id
                ),
            )
            evidence = m.EvidenceUnit.model_validate(evidence_row.data)
            if any(
                (
                    evidence.evidence_id != receipt.evidence_id,
                    evidence.artifact_hash != receipt.artifact_hash,
                    evidence.normalized_hash != receipt.normalized_hash,
                    canonical_hash(evidence.locator.model_dump(mode="json"))
                    != receipt.locator_hash,
                )
            ):
                raise Conflict("IDEMPOTENCY_EVIDENCE_CHANGED")
            artifact = cast(
                ArtifactRow,
                runtime.repository.scoped(
                    ArtifactRow, evidence.artifact_id, actor.workspace_id
                ),
            )
            if artifact.sha256 != evidence.artifact_hash:
                raise Conflict("IDEMPOTENCY_EVIDENCE_CHANGED")
            signed = runtime.object_store.sign_get(artifact.object_key)
            body = dto.EvidenceVerifyEnvelope.model_validate(
                {
                    "verification": {
                        "receipt": receipt.model_dump(mode="json"),
                        "evidence": evidence.model_dump(mode="json"),
                        "view_url": signed.url,
                        "view_url_expires_at": signed.expires_at.isoformat(),
                    }
                }
            ).model_dump(mode="json")
        elif kind == "activity":
            row = cast(
                ActivityRow,
                runtime.repository.scoped(
                    ActivityRow, str(descriptor["activity_id"]), actor.workspace_id
                ),
            )
            body = dto.ActivityEnvelope.model_validate(
                {"activity": _activity_payload(row, runtime.repository)}
            ).model_dump(mode="json")
        elif kind == "artifact":
            row = cast(
                ArtifactRow,
                runtime.repository.scoped(
                    ArtifactRow, str(descriptor["artifact_id"]), actor.workspace_id
                ),
            )
            body = dto.ArtifactEnvelope.model_validate(
                {"artifact": _artifact_payload(row)}
            ).model_dump(mode="json")
        elif kind == "operation":
            job_id = str(descriptor["job_id"])
            body = dto.OperationEnvelope.model_validate(
                {
                    "job_id": job_id,
                    "submission_id": descriptor.get("submission_id"),
                    "operation": runtime.repository.job_status(
                        job_id, actor.workspace_id
                    ),
                }
            ).model_dump(mode="json")
        elif kind == "policy_decision":
            row = cast(
                PolicyDecisionRow,
                runtime.repository.scoped(
                    PolicyDecisionRow,
                    str(descriptor["decision_id"]),
                    actor.workspace_id,
                ),
            )
            body = dto.PolicyDecisionEnvelope.model_validate(
                {"decision": row.data}
            ).model_dump(mode="json")
        elif kind == "job":
            job_id = str(descriptor["job_id"])
            body = dto.JobEnvelope.model_validate(
                {"job": runtime.repository.job_status(job_id, actor.workspace_id)}
            ).model_dump(mode="json")
        elif kind == "blueprint":
            row = runtime.repository.blueprint_version(
                str(descriptor["activity_id"]),
                int(descriptor["version"]),
                actor.workspace_id,
            )
            body = dto.BlueprintEnvelope.model_validate(
                {
                    "blueprint": row.data,
                    "preflight": row.preflight,
                    "review": row.review,
                    "issues": (row.data or {}).get("diagnostics", []),
                    "etag": row.etag,
                    "version": row.version,
                }
            ).model_dump(mode="json")
        elif kind == "submission":
            row = cast(
                SubmissionRow,
                runtime.repository.scoped(
                    SubmissionRow,
                    str(descriptor["submission_id"]),
                    actor.workspace_id,
                ),
            )
            body = dto.SubmissionEnvelope.model_validate(
                {"submission": _submission_payload(row, runtime.repository)}
            ).model_dump(mode="json")
        elif kind == "submission_batch":
            rows = [
                cast(
                    SubmissionRow,
                    runtime.repository.scoped(
                        SubmissionRow, str(submission_id), actor.workspace_id
                    ),
                )
                for submission_id in descriptor["submission_ids"]
            ]
            body = dto.SubmissionBatchEnvelope.model_validate(
                {
                    "submissions": [
                        _submission_payload(row, runtime.repository) for row in rows
                    ],
                    "created_count": len(rows),
                }
            ).model_dump(mode="json")
        elif kind == "job_control":
            body = dto.JobControlEnvelope.model_validate(
                runtime.stage2.job_control_view(
                    str(descriptor["job_id"]), actor
                )
            ).model_dump(mode="json")
        elif kind == "feedback":
            row = cast(
                FeedbackEventRow,
                runtime.repository.scoped(
                    FeedbackEventRow,
                    str(descriptor["feedback_id"]),
                    actor.workspace_id,
                ),
            )
            body = dto.FeedbackEnvelope.model_validate(
                {"feedback": row.data}
            ).model_dump(mode="json")
        elif kind == "question_action":
            row = cast(
                QuestionReviewActionRow,
                runtime.repository.scoped(
                    QuestionReviewActionRow,
                    str(descriptor["record_id"]),
                    actor.workspace_id,
                ),
            )
            if row.submission_id != descriptor.get("submission_id"):
                raise Conflict("IDEMPOTENCY_QUESTION_ACTION_CHANGED")
            body = dto.QuestionReviewActionEnvelope.model_validate(
                {
                    "action_record": row.data,
                    "bundle": current_assessment_bundle(row.submission_id, actor),
                }
            ).model_dump(mode="json")
        elif kind == "assessment":
            body = current_assessment_bundle(
                str(descriptor["submission_id"]), actor
            )
            if body["assessment"]["assessment_id"] != descriptor.get(
                "assessment_id"
            ):
                raise Conflict("IDEMPOTENCY_ASSESSMENT_CHANGED")
        elif kind == "bulk_approval":
            row = cast(
                BulkApprovalRecordRow,
                runtime.repository.scoped(
                    BulkApprovalRecordRow,
                    str(descriptor["approval_id"]),
                    actor.workspace_id,
                ),
            )
            body = dto.BulkApprovalEnvelope.model_validate(
                {"bulk_approval": row.data}
            ).model_dump(mode="json")
        else:
            raise Conflict("IDEMPOTENCY_DESCRIPTOR_UNSUPPORTED")
        response = JSONResponse(body, status_code=int(descriptor["status_code"]))
        etag = cast(dict[str, Any], descriptor.get("headers", {})).get("etag")
        if isinstance(etag, str):
            response.headers["ETag"] = etag
        response.headers["Idempotency-Replayed"] = "true"
        return response

    def replay_descriptor(
        request: Request,
        response: Response,
        body: dict[str, Any],
        actor: Actor,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        authorization = {
            "principal_id": actor.user_id,
            "role": actor.role,
            "can_approve_assessments": actor.can_approve_assessments,
        }
        route_template = _idempotent_mutation_template(
            request.method, request.url.path
        )
        if route_template is None:
            raise RuntimeError("IDEMPOTENCY_ROUTE_UNSUPPORTED")
        base = {
            "descriptor_version": "idempotency-reference/2.0.0",
            "route": route_template,
            "response_hash": canonical_hash(body),
            "status_code": response.status_code,
            "headers": headers,
            "authorization": authorization,
        }
        if response.headers.get("etag"):
            headers["etag"] = str(response.headers["etag"])
        if request.url.path.endswith("/artifacts/uploads"):
            upload = cast(dict[str, Any], body["upload"])
            artifact = cast(
                ArtifactRow,
                runtime.repository.scoped(
                    ArtifactRow,
                    str(upload["artifact_id"]),
                    actor.workspace_id,
                ),
            )
            return {
                **base,
                "kind": "upload",
                "artifact_id": upload["artifact_id"],
                # This is an address, not a capability. A replay uses it to
                # mint a fresh short-lived URL for the exact disposable
                # reservation even after the Artifact moves to a sealed key.
                "upload_object_key": artifact.object_key,
            }
        if request.url.path.endswith("/exports"):
            exported = cast(dict[str, Any], body["export"])
            record = cast(dict[str, Any], body["record"])
            return {
                **base,
                "kind": "export",
                "export_id": exported["export_id"],
                "export_kinds": record["requested_kinds"],
            }
        if request.url.path.endswith("/evidence:verify"):
            verification = dto.EvidenceVerifyEnvelope.model_validate(
                body
            ).verification
            return {
                **base,
                "kind": "evidence_verify",
                "receipt": verification.receipt.model_dump(mode="json"),
            }
        if route_template in {
            "/api/v1/activities",
            "/api/v1/activities/{activity_id}",
        }:
            return {
                **base,
                "kind": "activity",
                "activity_id": body["activity"]["activity_id"],
            }
        if route_template.endswith(":complete"):
            return {
                **base,
                "kind": "artifact",
                "artifact_id": body["artifact"]["artifact_id"],
            }
        if route_template in {
            "/api/v1/activities/{activity_id}/blueprints:generate",
            "/api/v1/submissions/{submission_id}:run",
        }:
            return {
                **base,
                "kind": "operation",
                "job_id": body["job_id"],
                "submission_id": body.get("submission_id"),
            }
        if route_template == "/api/v1/activities/{activity_id}/decisions":
            return {
                **base,
                "kind": "policy_decision",
                "decision_id": body["decision"]["decision_id"],
            }
        if (
            route_template
            == "/api/v1/activities/{activity_id}/blueprints/{version}"
        ):
            return {**base, "kind": "job", "job_id": body["job"]["job_id"]}
        if route_template.endswith("/blueprints/{version}:approve"):
            return {
                **base,
                "kind": "blueprint",
                "activity_id": body["blueprint"]["activity_id"],
                "version": body["version"],
            }
        if route_template == "/api/v1/activities/{activity_id}/submissions":
            return {
                **base,
                "kind": "submission",
                "submission_id": body["submission"]["submission_id"],
            }
        if route_template.endswith("/submissions:batch"):
            return {
                **base,
                "kind": "submission_batch",
                "submission_ids": [
                    item["submission_id"] for item in body["submissions"]
                ],
            }
        if route_template == "/api/v1/jobs/{job_id}:control":
            return {
                **base,
                "kind": "job_control",
                "job_id": body["job"]["job_id"],
            }
        if route_template == "/api/v1/feedback":
            return {
                **base,
                "kind": "feedback",
                "feedback_id": body["feedback"]["feedback_id"],
            }
        if route_template.endswith("/questions/{question_id}/actions"):
            return {
                **base,
                "kind": "question_action",
                "record_id": body["action_record"]["record_id"],
                "submission_id": body["action_record"]["submission_id"],
            }
        if route_template == "/api/v1/assessments/{assessment_id}:approve":
            return {
                **base,
                "kind": "assessment",
                "assessment_id": body["assessment"]["assessment_id"],
                "submission_id": body["assessment"]["submission_id"],
            }
        if route_template.endswith("/assessments:bulk-approve"):
            return {
                **base,
                "kind": "bulk_approval",
                "approval_id": body["bulk_approval"]["approval_id"],
            }
        raise RuntimeError("IDEMPOTENCY_DESCRIPTOR_UNSUPPORTED")

    @app.middleware("http")
    async def domain_idempotency(request: Request, call_next: Any) -> Response:
        is_domain_mutation = (
            request.method in {"POST", "PATCH", "DELETE"}
            and request.url.path.startswith("/api/v1/")
            and not request.url.path.startswith("/api/v1/session/")
        )
        if not is_domain_mutation:
            return await call_next(request)
        try:
            actor = runtime.auth.authenticate(request)
        except HTTPException:
            # Let the endpoint dependency produce the canonical auth response.
            return await call_next(request)
        try:
            runtime.auth.require_csrf(request, actor)
        except HTTPException:
            # A cached success never bypasses the same CSRF boundary as the
            # first request. Let the dependency emit its canonical 403.
            return await call_next(request)
        if _idempotent_mutation_template(request.method, request.url.path) is None:
            return _problem(
                500,
                "IDEMPOTENCY_ROUTE_UNSUPPORTED",
                "The mutation has no content-minimal replay descriptor.",
                request,
            )
        key = request.headers.get("Idempotency-Key", "")
        try:
            if len(key) > 128:
                raise ValueError
            UUID(key)
        except (ValueError, AttributeError):
            return _problem(
                428,
                "IDEMPOTENCY_KEY_REQUIRED",
                "A client-generated UUID Idempotency-Key is required.",
                request,
            )
        raw_body = await request.body()
        try:
            canonical_body: Any = json.loads(raw_body) if raw_body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            canonical_body = {"body_hash": canonical_hash(raw_body.hex())}
        fingerprint = canonical_hash(
            {
                "tenant_id": actor.workspace_id,
                "authorization": {
                    "principal_id": actor.user_id,
                    "role": actor.role,
                    "can_approve_assessments": actor.can_approve_assessments,
                },
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "if_match": request.headers.get("if-match"),
                "body": canonical_body,
            }
        )
        try:
            replay = runtime.repository.reserve_idempotency(
                actor.workspace_id,
                key,
                fingerprint,
                ttl_seconds=selected.idempotency_ttl_seconds,
            )
        except Conflict as exc:
            code = str(exc) if str(exc).isupper() else "RESOURCE_CONFLICT"
            return _problem(
                409,
                code,
                "The idempotency key conflicts with persisted state.",
                request,
            )
        if replay is not None:
            return replay_response(replay, actor)
        try:
            response = await call_next(request)
            chunks = [chunk async for chunk in response.body_iterator]
            response_body = b"".join(chunks)
            rebuilt = Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
            if response.status_code >= 400:
                runtime.repository.release_idempotency(
                    actor.workspace_id, key, fingerprint
                )
                return rebuilt
            if "json" not in response.headers.get("content-type", ""):
                runtime.repository.release_idempotency(
                    actor.workspace_id, key, fingerprint
                )
                return rebuilt
            parsed = json.loads(response_body)
            if not isinstance(parsed, dict):
                raise RuntimeError("Mutable JSON responses must be objects")
            descriptor = replay_descriptor(request, response, parsed, actor)
            runtime.repository.complete_idempotency(
                actor.workspace_id,
                key,
                fingerprint,
                descriptor,
                ttl_seconds=selected.idempotency_ttl_seconds,
            )
            rebuilt.headers["Idempotency-Replayed"] = "false"
            return rebuilt
        except Exception:
            runtime.repository.release_idempotency(
                actor.workspace_id, key, fingerprint
            )
            raise

    @app.exception_handler(WorkflowError)
    async def workflow_error(request: Request, exc: WorkflowError) -> JSONResponse:
        return _problem(exc.status_code, exc.code, str(exc), request)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code_by_status = {
            401: "AUTHENTICATION_REQUIRED",
            403: "ROLE_FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
        }
        detail = exc.detail
        code = code_by_status.get(exc.status_code, "REQUEST_REJECTED")
        if isinstance(detail, dict):
            candidate = detail.get("code")
            if isinstance(candidate, str) and candidate.isupper():
                code = candidate
            message = detail.get("message")
            detail_text = (
                str(message)
                if isinstance(message, str)
                else "The request was rejected at the authorization boundary."
            )
        else:
            detail_text = (
                str(detail)
                if isinstance(detail, str) and exc.status_code < 500
                else "The request was rejected without exposing internal detail."
            )
        return _problem(exc.status_code, code, detail_text, request)

    @app.exception_handler(NotFound)
    async def not_found(request: Request, _exc: NotFound) -> JSONResponse:
        return _problem(404, "RESOURCE_NOT_FOUND", "The requested resource was not found.", request)

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict) -> JSONResponse:
        code = str(exc) if str(exc).isupper() else "RESOURCE_CONFLICT"
        return _problem(409, code, "The request conflicts with persisted state.", request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, list[str]] = {}
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", ())) or "body"
            fields.setdefault(location, []).append(str(item.get("type", "invalid")))
        problem = m.ProblemDetail(
            title="Validation failed",
            status=422,
            detail="The request does not satisfy the versioned boundary.",
            instance=_safe_route_template(request),
            code="VALIDATION_FAILED",
            trace_id=stable_id("trace", secrets.token_hex(16)),
            fields=fields,
        )
        return JSONResponse(
            problem.model_dump(mode="json"),
            status_code=422,
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, _exc: Exception) -> JSONResponse:
        # Do not serialize exception text: adapters and parsers may have seen
        # hostile student-controlled bytes immediately before the failure.
        return _problem(
            500,
            "TECHNICAL_FAILURE",
            "The service failed without exposing input content.",
            request,
        )

    def current_actor(request: Request) -> Actor:
        return runtime.auth.authenticate(request)

    def mutating_actor(
        request: Request,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> Actor:
        runtime.auth.require_csrf(request, actor)
        return actor

    @app.get("/api/health", response_model=dto.HealthResource)
    def health() -> dto.HealthResource:
        return dto.HealthResource(
            status="ok", stage="2", model_mode=selected.model_mode
        )

    @app.get("/api/readiness", response_model=dto.ReadinessResource)
    def readiness(response: Response) -> dto.ReadinessResource:
        try:
            runtime.repository.check_readiness()
        except Exception:
            # Never expose a database URL, SQL, driver exception or stack trace.
            response.status_code = 503
            return dto.ReadinessResource(status="not_ready")
        return dto.ReadinessResource(status="ready")

    @app.get("/api/v1/session", response_model=dto.SessionEnvelope)
    def session(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        return {
            "session": {
                "user_id": actor.user_id,
                "email": actor.email,
                "workspace_id": actor.workspace_id,
                "workspace_name": "Workspace experimental",
                "roles": [actor.role],
            }
        }

    @app.post("/api/v1/session/login", response_model=dto.SessionEnvelope)
    def login(
        response: Response,
        payload: dto.LoginCommand,
    ) -> dict[str, Any]:
        email = payload.email.strip().lower()
        actor = runtime.auth.local_login(email, response)
        return {
            "session": {
                "user_id": actor.user_id,
                "email": actor.email,
                "workspace_id": actor.workspace_id,
                "workspace_name": "Workspace experimental",
                "roles": [actor.role],
            }
        }

    @app.post("/api/v1/session/exchange", response_model=dto.SessionEnvelope)
    def exchange_session(
        response: Response,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "SUPABASE_TOKEN_REQUIRED"})
        actor = runtime.auth.exchange_supabase_token(authorization.removeprefix("Bearer "), response)
        return {
            "session": {
                "user_id": actor.user_id,
                "email": actor.email,
                "workspace_id": actor.workspace_id,
                "workspace_name": "Workspace experimental",
                "roles": [actor.role],
            }
        }

    @app.post("/api/v1/session/logout", status_code=204)
    def logout(
        response: Response,
        _actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> None:
        runtime.auth.logout(response)

    @app.get("/api/v1/activities", response_model=dto.ActivityListEnvelope)
    def activities(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        return {
            "items": [
                _activity_payload(row, runtime.repository)
                for row in runtime.repository.activities(actor.workspace_id)
            ]
        }

    @app.post(
        "/api/v1/activities",
        status_code=201,
        response_model=dto.ActivityEnvelope,
    )
    def create_activity(
        payload: dto.ActivityCreateCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        title = payload.title
        activity_id = stable_id("act", actor.workspace_id, title, datetime.now(UTC))
        client_payload = payload.model_dump(mode="json")
        if not client_payload["allowed_artifact_media_types"]:
            client_payload["allowed_artifact_media_types"] = sorted(ALLOWED_MEDIA_TYPES)
        canonical = m.ActivityConfig.model_validate(
            {
                **client_payload,
                "activity_id": activity_id,
                "tenant_id": actor.workspace_id,
                "context_mode": "CLOSED",
                "course_source_ids": [],
                "require_blueprint_approval": True,
            }
        )
        row = runtime.service.create_activity(canonical, actor)
        return {"activity": _activity_payload(row, runtime.repository)}

    @app.get(
        "/api/v1/activities/{activity_id}",
        response_model=dto.ActivityEnvelope,
        responses={
            200: {
                "description": "Current activity resource",
                "headers": {"ETag": {"schema": {"type": "string"}}},
            }
        },
    )
    def activity_detail(
        activity_id: str,
        response: Response,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dto.ActivityEnvelope:
        row = cast(
            ActivityRow,
            runtime.repository.scoped(ActivityRow, activity_id, actor.workspace_id),
        )
        return _activity_response(row, runtime.repository, response)

    @app.patch(
        "/api/v1/activities/{activity_id}",
        response_model=dto.ActivityEnvelope,
        responses={
            200: {
                "description": "Updated draft activity",
                "headers": {"ETag": {"schema": {"type": "string"}}},
            }
        },
    )
    def edit_activity(
        activity_id: str,
        payload: dto.ActivityUpdateCommand,
        response: Response,
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dto.ActivityEnvelope:
        if not if_match:
            raise WorkflowError(
                "IF_MATCH_REQUIRED", "If-Match is required", status_code=428
            )
        current = cast(
            ActivityRow,
            runtime.repository.scoped(
                ActivityRow, activity_id, actor.workspace_id
            ),
        )
        canonical = m.ActivityConfig.model_validate(
            {
                **current.config,
                **payload.model_dump(mode="json", exclude_unset=True),
                "activity_id": activity_id,
                "tenant_id": actor.workspace_id,
                "context_mode": "CLOSED",
                "course_source_ids": [],
                "require_blueprint_approval": True,
            }
        )
        row = runtime.service.edit_activity(
            activity_id=activity_id,
            config=canonical,
            if_match=if_match,
            actor=actor,
        )
        return _activity_response(row, runtime.repository, response)

    def prepare_upload(
        *,
        activity_id: str,
        submission_id: str | None,
        payload: dto.UploadCommand,
        actor: Actor,
    ) -> dict[str, Any]:
        claimed_size = payload.byte_size
        if claimed_size < 1 or claimed_size > selected.max_upload_bytes:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Declared object size is invalid")
        row, upload = runtime.service.create_upload(
            actor=actor,
            activity_id=activity_id,
            submission_id=submission_id,
            filename=payload.filename,
            media_type=payload.media_type,
            expected_byte_size=claimed_size,
            role=payload.role,
        )
        upload_headers = upload.pop("headers", {})
        return {
            "upload": {
                **upload,
                "upload_headers": upload_headers,
                "artifact": _artifact_payload(row),
            }
        }

    @app.post(
        "/api/v1/activities/{activity_id}/artifacts/uploads",
        status_code=201,
        response_model=dto.UploadEnvelope,
    )
    def activity_upload(
        activity_id: str,
        payload: dto.UploadCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        return prepare_upload(
            activity_id=activity_id, submission_id=None, payload=payload, actor=actor
        )

    @app.post(
        "/api/v1/submissions/{submission_id}/artifacts/uploads",
        status_code=201,
        response_model=dto.UploadEnvelope,
    )
    def submission_upload(
        submission_id: str,
        payload: dto.UploadCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        submission = cast(
            SubmissionRow,
            runtime.repository.scoped(SubmissionRow, submission_id, actor.workspace_id),
        )
        return prepare_upload(
            activity_id=submission.activity_id,
            submission_id=submission.id,
            payload=payload,
            actor=actor,
        )

    @app.put("/api/v1/object-uploads/{token}", include_in_schema=False)
    async def fake_object_put(token: str, request: Request) -> Response:
        if not isinstance(runtime.object_store, MemoryObjectStore):
            raise NotFound("signed upload route is disabled")
        data = await request.body()
        if not data or len(data) > selected.max_upload_bytes:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Object size is invalid")
        try:
            runtime.object_store.put_signed(
                token,
                data,
                request.headers.get("content-type", "application/octet-stream").split(";", 1)[0],
            )
        except (jwt.PyJWTError, KeyError, PermissionError, ObjectSizeExceeded) as exc:
            raise WorkflowError(
                "SIGNED_URL_INVALID", "Signed object URL is invalid", status_code=403
            ) from exc
        return Response(status_code=204)

    @app.get("/api/v1/objects/{token}", include_in_schema=False)
    def fake_object_get(token: str) -> Response:
        if not isinstance(runtime.object_store, MemoryObjectStore):
            raise NotFound("signed download route is disabled")
        try:
            data, media_type = runtime.object_store.get_signed(token)
        except (jwt.PyJWTError, KeyError, PermissionError) as exc:
            raise WorkflowError("SIGNED_URL_INVALID", "Signed object URL is invalid", status_code=403) from exc
        return Response(data, media_type=media_type, headers={"Cache-Control": "private, no-store"})

    def complete_artifact(
        artifact_id: str, payload: dto.UploadCompletionCommand, actor: Actor
    ) -> dict[str, Any]:
        runtime.service.complete_upload(
            artifact_id,
            actor,
            claimed_sha256=payload.sha256,
            claimed_byte_size=payload.byte_size,
            claimed_media_type=payload.media_type,
        )
        completed = cast(
            ArtifactRow,
            runtime.repository.scoped(
                ArtifactRow, artifact_id, actor.workspace_id
            ),
        )
        return {"artifact": _artifact_payload(completed)}

    @app.post(
        "/api/v1/activities/{activity_id}/artifacts/{artifact_id}:complete",
        response_model=dto.ArtifactEnvelope,
    )
    def complete_activity_artifact(
        activity_id: str,
        artifact_id: str,
        payload: dto.UploadCompletionCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        row = cast(ArtifactRow, runtime.repository.scoped(ArtifactRow, artifact_id, actor.workspace_id))
        if row.activity_id != activity_id or row.submission_id is not None:
            raise NotFound("artifact not found")
        return complete_artifact(artifact_id, payload, actor)

    @app.post(
        "/api/v1/submissions/{submission_id}/artifacts/{artifact_id}:complete",
        response_model=dto.ArtifactEnvelope,
    )
    def complete_submission_artifact(
        submission_id: str,
        artifact_id: str,
        payload: dto.UploadCompletionCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        row = cast(ArtifactRow, runtime.repository.scoped(ArtifactRow, artifact_id, actor.workspace_id))
        if row.submission_id != submission_id:
            raise NotFound("artifact not found")
        return complete_artifact(artifact_id, payload, actor)

    @app.post(
        "/api/v1/activities/{activity_id}/blueprints:generate",
        status_code=202,
        response_model=dto.OperationEnvelope,
    )
    async def generate_blueprint(
        activity_id: str,
        _payload: Annotated[dto.EmptyCommand, Body(default_factory=dto.EmptyCommand)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        job = await runtime.service.enqueue_activity_pipeline(activity_id, actor)
        return {"job_id": job.job_id, "operation": job.model_dump(mode="json")}

    @app.get(
        "/api/v1/activities/{activity_id}/estimate",
        response_model=dto.EstimateEnvelope,
    )
    def activity_estimate(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        estimate = runtime.service.activity_cost_estimate(activity_id, actor)
        return {"estimate": estimate.model_dump(mode="json")}

    @app.get(
        "/api/v1/activities/{activity_id}/ambiguity",
        response_model=dto.AmbiguityEnvelope,
    )
    def activity_ambiguity(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return runtime.service.ambiguity_view(activity_id, actor)

    @app.post(
        "/api/v1/activities/{activity_id}/decisions",
        status_code=201,
        response_model=dto.PolicyDecisionEnvelope,
    )
    def create_policy_decision(
        activity_id: str,
        payload: dto.PolicyDecisionCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        decision = runtime.service.record_policy_decision(
            activity_id=activity_id,
            issue_id=payload.issue_id,
            selected_option_id=payload.selected_option_id,
            note=payload.note,
            actor=actor,
        )
        return {"decision": decision.model_dump(mode="json")}

    @app.get(
        "/api/v1/activities/{activity_id}/blueprints/latest",
        response_model=dto.BlueprintEnvelope,
        responses={
            200: {
                "description": "Latest immutable blueprint version",
                "headers": {"ETag": {"schema": {"type": "string"}}},
            }
        },
    )
    def latest_blueprint(
        activity_id: str,
        response: Response,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dto.BlueprintEnvelope:
        row = runtime.repository.latest_blueprint(activity_id, actor.workspace_id)
        preflight, issues = runtime.service.blueprint_review_projection(row, actor)
        return _blueprint_response(
            row, response, preflight=preflight, issues=issues
        )

    @app.get(
        "/api/v1/activities/{activity_id}/blueprints/{version}",
        response_model=dto.BlueprintEnvelope,
        responses={
            200: {
                "description": "Requested immutable blueprint version",
                "headers": {"ETag": {"schema": {"type": "string"}}},
            }
        },
    )
    def blueprint_version(
        activity_id: str,
        version: int,
        response: Response,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dto.BlueprintEnvelope:
        row = runtime.repository.blueprint_version(
            activity_id, version, actor.workspace_id
        )
        preflight, issues = runtime.service.blueprint_review_projection(row, actor)
        return _blueprint_response(
            row, response, preflight=preflight, issues=issues
        )

    @app.patch(
        "/api/v1/activities/{activity_id}/blueprints/{version}",
        status_code=202,
        response_model=dto.JobEnvelope,
    )
    async def edit_blueprint(
        activity_id: str,
        version: int,
        edited: m.AssessmentBlueprint,
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        if not if_match:
            raise WorkflowError("IF_MATCH_REQUIRED", "If-Match is required", status_code=428)
        job = await runtime.service.edit_blueprint(
            activity_id=activity_id,
            version=version,
            if_match=if_match,
            edited=edited,
            actor=actor,
        )
        return {"job": job.model_dump(mode="json")}

    @app.post(
        "/api/v1/activities/{activity_id}/blueprints/{version}:approve",
        response_model=dto.BlueprintEnvelope,
    )
    def approve_blueprint(
        activity_id: str,
        version: int,
        _payload: Annotated[dto.EmptyCommand, Body(default_factory=dto.EmptyCommand)],
        response: Response,
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dto.BlueprintEnvelope:
        if not if_match:
            raise WorkflowError("IF_MATCH_REQUIRED", "If-Match is required", status_code=428)
        return _blueprint_response(
            runtime.service.approve_blueprint(
                activity_id=activity_id,
                version=version,
                if_match=if_match,
                actor=actor,
            ),
            response,
        )

    @app.post(
        "/api/v1/activities/{activity_id}/submissions",
        status_code=201,
        response_model=dto.SubmissionEnvelope,
    )
    def create_submission(
        activity_id: str,
        payload: dto.SubmissionCreateCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        row = runtime.service.create_submission(
            activity_id=activity_id,
            subject_ref=payload.subject_ref,
            actor=actor,
        )
        return {"submission": _submission_payload(row, runtime.repository)}

    @app.post(
        "/api/v1/activities/{activity_id}/submissions:batch",
        status_code=201,
        response_model=dto.SubmissionBatchEnvelope,
    )
    def create_submission_batch(
        activity_id: str,
        payload: dto.SubmissionBatchCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        rows = runtime.stage2.create_submissions(
            activity_id=activity_id,
            subject_refs=payload.subject_refs,
            actor=actor,
        )
        return {
            "submissions": [
                _submission_payload(row, runtime.repository) for row in rows
            ],
            "created_count": len(rows),
        }

    @app.get(
        "/api/v1/activities/{activity_id}/submissions",
        response_model=dto.SubmissionListEnvelope,
    )
    def activity_submissions(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
        status: Annotated[m.SubmissionProcessingStatus | None, Query()] = None,
        subject_ref: Annotated[str | None, Query(max_length=128)] = None,
    ) -> dict[str, Any]:
        rows = runtime.stage2.submissions(
            activity_id=activity_id,
            actor=actor,
            status=status,
            subject_ref=subject_ref,
        )
        return {
            "items": [_submission_payload(row, runtime.repository) for row in rows]
        }

    @app.get(
        "/api/v1/submissions/{submission_id}",
        response_model=dto.SubmissionEnvelope,
    )
    def submission_detail(
        submission_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        row = cast(
            SubmissionRow,
            runtime.repository.scoped(SubmissionRow, submission_id, actor.workspace_id),
        )
        payload = _submission_payload(row, runtime.repository)
        return {"submission": payload}

    @app.post(
        "/api/v1/submissions/{submission_id}:run",
        status_code=202,
        response_model=dto.OperationEnvelope,
    )
    async def run_submission(
        submission_id: str,
        _payload: Annotated[dto.EmptyCommand, Body(default_factory=dto.EmptyCommand)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        job = await runtime.service.enqueue_submission_pipeline(submission_id, actor)
        return {
            "job_id": job.job_id,
            "submission_id": submission_id,
            "operation": job.model_dump(mode="json"),
        }

    @app.get(
        "/api/v1/submissions/{submission_id}/estimate",
        response_model=dto.EstimateEnvelope,
    )
    def submission_estimate(
        submission_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        estimate = runtime.service.submission_cost_estimate(submission_id, actor)
        return {"estimate": estimate.model_dump(mode="json")}

    @app.get("/api/v1/jobs/{job_id}", response_model=dto.JobEnvelope)
    def job_status(
        job_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"job": runtime.repository.job_status(job_id, actor.workspace_id).model_dump(mode="json")}

    @app.get(
        "/api/v1/jobs/{job_id}/control",
        response_model=dto.JobControlEnvelope,
    )
    def job_control(
        job_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return runtime.stage2.job_control_view(job_id, actor)

    async def apply_job_control(
        *,
        job_id: str,
        action: m.JobControlActionType,
        payload: dto.JobControlCommand,
        actor: Actor,
    ) -> dict[str, Any]:
        return await runtime.stage2.control_job(
            job_id=job_id,
            action=action,
            reason_code=payload.reason_code,
            target_stage=payload.target_stage,
            actor=actor,
        )

    @app.post(
        "/api/v1/jobs/{job_id}:retry",
        response_model=dto.JobControlEnvelope,
    )
    async def retry_job(
        job_id: str,
        payload: dto.JobControlCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        return await apply_job_control(
            job_id=job_id,
            action=m.JobControlActionType.RETRY,
            payload=payload,
            actor=actor,
        )

    @app.post(
        "/api/v1/jobs/{job_id}:cancel",
        response_model=dto.JobControlEnvelope,
    )
    async def cancel_job(
        job_id: str,
        payload: dto.JobControlCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        return await apply_job_control(
            job_id=job_id,
            action=m.JobControlActionType.CANCEL,
            payload=payload,
            actor=actor,
        )

    @app.post(
        "/api/v1/jobs/{job_id}:resume",
        response_model=dto.JobControlEnvelope,
    )
    async def resume_job(
        job_id: str,
        payload: dto.JobControlCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        return await apply_job_control(
            job_id=job_id,
            action=m.JobControlActionType.RESUME,
            payload=payload,
            actor=actor,
        )

    @app.get(
        "/api/v1/jobs/{job_id}/model-calls",
        response_model=dto.ModelCallListEnvelope,
    )
    def model_calls(
        job_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        runtime.repository.job_status(job_id, actor.workspace_id)
        return {
            "items": runtime.repository.model_calls(
                tenant_id=actor.workspace_id, job_id=job_id
            )
        }

    @app.get(
        "/api/v1/submissions/{submission_id}/evidence",
        response_model=dto.EvidenceListEnvelope,
    )
    def evidence(
        submission_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=20)] = None,
    ) -> dict[str, Any]:
        items = runtime.service.evidence_view(submission_id, actor)
        try:
            offset = int(cursor or "0")
        except ValueError as exc:
            raise WorkflowError("CURSOR_INVALID", "Evidence cursor is invalid") from exc
        if offset < 0:
            raise WorkflowError("CURSOR_INVALID", "Evidence cursor is invalid")
        page = items[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "items": [item["evidence"] for item in page],
            "next_cursor": str(next_offset) if next_offset < len(items) else None,
        }

    @app.get(
        "/api/v1/submissions/{submission_id}/coverage",
        response_model=dto.CoverageEnvelope,
    )
    def submission_coverage(
        submission_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"coverage": runtime.stage2.coverage_for_submission(submission_id, actor)}

    @app.get(
        "/api/v1/activities/{activity_id}/coverage",
        response_model=dto.CoverageEnvelope,
    )
    def activity_coverage(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"coverage": runtime.stage2.coverage_for_activity(activity_id, actor)}

    @app.get(
        "/api/v1/activities/{activity_id}/metrics",
        response_model=dto.MetricsEnvelope,
    )
    def activity_metrics(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"metrics": runtime.stage2.experiment_metrics(activity_id, actor)}

    @app.post(
        "/api/v1/feedback",
        status_code=201,
        response_model=dto.FeedbackEnvelope,
    )
    def create_feedback(
        payload: dto.FeedbackCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        event = runtime.stage2.record_feedback(
            activity_id=payload.activity_id,
            target_type=payload.target_type,
            category=payload.category,
            rating=payload.rating,
            actor=actor,
            assessment_id=payload.assessment_id,
            assessment_version=payload.assessment_version,
            question_id=payload.question_id,
            comment=payload.comment,
        )
        return {"feedback": event}

    @app.get(
        "/api/v1/activities/{activity_id}/feedback",
        response_model=dto.FeedbackListEnvelope,
    )
    def activity_feedback(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"items": runtime.stage2.feedback_for_activity(activity_id, actor)}

    @app.get(
        "/api/v1/submissions/{submission_id}/assessment",
        response_model=dto.AssessmentEnvelope,
        responses={
            200: {
                "description": "Assessment review bundle",
                "headers": {"ETag": {"schema": {"type": "string"}}},
            }
        },
    )
    def assessment(
        submission_id: str,
        response: Response,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        value = runtime.stage2.assessment_review_view(submission_id, actor)
        value["evidence"] = evidence(submission_id, actor)["items"]
        response.headers["ETag"] = str(value["etag"])
        return value

    @app.get(
        "/api/v1/assessments/{assessment_id}/guide",
        response_model=dto.GuideEnvelope,
    )
    def guide(
        assessment_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return runtime.service.guide_view(assessment_id, actor)

    @app.get(
        "/api/v1/assessments/{assessment_id}/guide/estimate",
        response_model=dto.EstimateEnvelope,
    )
    def guide_estimate(
        assessment_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        estimate = runtime.service.guide_cost_estimate(assessment_id, actor)
        return {"estimate": estimate.model_dump(mode="json")}

    @app.get(
        "/api/v1/assessments/{assessment_id}/guide/history",
        response_model=dto.GuideHistoryEnvelope,
    )
    def guide_history(
        assessment_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"items": runtime.service.guide_history(assessment_id, actor)}

    @app.post(
        "/api/v1/assessments/{assessment_id}/questions/{question_id}/actions",
        response_model=dto.QuestionReviewActionEnvelope,
        responses={
            200: {
                "description": "Durable question action and current review bundle",
                "headers": {"ETag": {"schema": {"type": "string"}}},
            }
        },
    )
    async def review_question(
        assessment_id: str,
        question_id: str,
        payload: dto.QuestionReviewActionCommand,
        response: Response,
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        if not if_match:
            raise WorkflowError(
                "IF_MATCH_REQUIRED", "If-Match is required", status_code=428
            )
        record = await runtime.stage2.review_question(
            assessment_id=assessment_id,
            question_id=question_id,
            action_type=payload.action,
            actor=actor,
            if_match=if_match,
            reason_code=payload.reason_code,
            note=payload.note,
            replacement=payload.replacement,
        )
        value = runtime.stage2.assessment_review_view(record.submission_id, actor)
        value["evidence"] = evidence(record.submission_id, actor)["items"]
        response.headers["ETag"] = str(value["etag"])
        return {"action_record": record, "bundle": value}

    @app.get(
        "/api/v1/assessments/{assessment_id}/questions/{question_id}/actions",
        response_model=dto.QuestionReviewActionListEnvelope,
    )
    def question_action_history(
        assessment_id: str,
        question_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {
            "items": runtime.stage2.question_actions(
                assessment_id=assessment_id,
                question_id=question_id,
                actor=actor,
            )
        }

    @app.post(
        "/api/v1/assessments/{assessment_id}/evidence:verify",
        response_model=dto.EvidenceVerifyEnvelope,
    )
    def verify_assessment_evidence(
        assessment_id: str,
        payload: dto.EvidenceVerifyCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        verification = runtime.service.verify_evidence_fragment(
            assessment_id=assessment_id,
            assessment_version=payload.assessment_version,
            assessment_etag=payload.assessment_etag,
            question_id=payload.question_id,
            fragment_index=payload.fragment_index,
            actor=actor,
        )
        return {"verification": verification}

    @app.post(
        "/api/v1/assessments/{assessment_id}:approve",
        response_model=dto.AssessmentEnvelope,
    )
    async def approve_assessment(
        assessment_id: str,
        _payload: Annotated[dto.EmptyCommand, Body(default_factory=dto.EmptyCommand)],
        response: Response,
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        if not if_match:
            raise WorkflowError(
                "IF_MATCH_REQUIRED", "If-Match is required", status_code=428
            )
        runtime.stage2.assert_no_unresolved_question_action(assessment_id, actor)
        row = await runtime.service.approve_assessment_and_enqueue_guide(
            assessment_id=assessment_id,
            if_match=if_match,
            actor=actor,
        )
        value = runtime.stage2.assessment_review_view(row.submission_id, actor)
        value["evidence"] = evidence(row.submission_id, actor)["items"]
        response.headers["ETag"] = str(value["etag"])
        return value

    @app.post(
        "/api/v1/assessments/{assessment_id}/exports",
        status_code=201,
        response_model=dto.ExportCreateEnvelope,
    )
    def create_export(
        assessment_id: str,
        payload: dto.ExportKindCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        requested_kinds = payload.requested_kinds()
        record = runtime.stage2.create_export(
            assessment_id=assessment_id,
            requested_kinds=requested_kinds,
            actor=actor,
        )
        downloads = runtime.stage2.export_downloads(record, actor)
        item = downloads[0]
        return {
            "export": {
                "export_id": record.export_id,
                "kind": item["kind"],
                "status": record.status,
                "download_url": item["download_url"],
                "expires_at": item["expires_at"],
                "sha256": item["sha256"],
                "byte_size": item["byte_size"],
            },
            "record": record,
            "downloads": downloads,
        }

    @app.get(
        "/api/v1/assessments/{assessment_id}/exports",
        response_model=dto.ExportHistoryEnvelope,
    )
    def export_history(
        assessment_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {
            "items": runtime.stage2.exports_for_assessment(assessment_id, actor)
        }

    @app.post(
        "/api/v1/activities/{activity_id}/assessments:bulk-approve",
        response_model=dto.BulkApprovalEnvelope,
    )
    async def bulk_approve_assessments(
        activity_id: str,
        payload: dto.BulkApprovalCommand,
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        record = await runtime.stage2.bulk_approve(
            activity_id=activity_id,
            targets=payload.targets,
            explicit_confirmation=payload.explicit_confirmation,
            actor=actor,
        )
        return {"bulk_approval": record}

    @app.get(
        "/api/v1/activities/{activity_id}/bulk-approvals",
        response_model=dto.BulkApprovalHistoryEnvelope,
    )
    def bulk_approval_history(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {
            "items": runtime.stage2.bulk_approvals_for_activity(
                activity_id, actor
            )
        }

    frontend = Path(selected.frontend_dist).resolve()

    @app.get("/{spa_path:path}", include_in_schema=False)
    def frontend_route(spa_path: str) -> Response:
        if spa_path.startswith("api/"):
            raise NotFound("API route not found")
        candidate = (frontend / spa_path).resolve()
        if candidate.is_file() and (candidate == frontend or frontend in candidate.parents):
            if candidate.name == "index.html":
                return FileResponse(
                    candidate,
                    headers={"Cache-Control": "no-store, max-age=0"},
                )
            cache_control = (
                "public, max-age=31536000, immutable"
                if spa_path.startswith("assets/")
                else "no-cache"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache_control})
        index = frontend / "index.html"
        if index.is_file():
            # Every client-side route serves the same mutable SPA document.  It
            # must be re-fetched after a rollout so a browser cannot pair an old
            # index with the newly deployed API. Vite's fingerprinted assets
            # remain independently cacheable above.
            return FileResponse(
                index,
                headers={"Cache-Control": "no-store, max-age=0"},
            )
        raise NotFound("frontend build not found")

    return app


app = create_app()
