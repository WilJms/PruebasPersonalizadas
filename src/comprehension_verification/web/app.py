"""FastAPI shell for the single-activity/single-submission Stage 1 slice."""

from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
from typing import Annotated, Any, cast
from uuid import UUID

import jwt
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from ..canonical import canonical_hash, stable_id
from ..contracts import models as m
from .auth import Actor
from .object_store import MemoryObjectStore, ObjectSizeExceeded, ObjectStore
from .repository import (
    ActivityRow,
    ArtifactRow,
    Conflict,
    ExportRow,
    GuideRow,
    NotFound,
    Repository,
    SubmissionRow,
)
from .runtime import Runtime, build_runtime
from .settings import Settings, get_settings
from .workflows import ALLOWED_MEDIA_TYPES, Stage1Service, WorkflowError


def _problem(status_code: int, code: str, detail: str, request: Request) -> JSONResponse:
    problem = m.ProblemDetail(
        title="Request could not be completed",
        status=status_code,
        detail=detail,
        instance=request.url.path,
        code=code,
        trace_id=stable_id("trace", secrets.token_hex(16)),
        retryable=status_code >= 500,
    )
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=status_code,
        media_type="application/problem+json",
    )


def _activity_payload(row: ActivityRow, repository: Repository) -> dict[str, Any]:
    value = dict(row.config)
    value.update(
        {
            "activity_id": row.id,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
    )
    try:
        value["latest_blueprint_version"] = repository.latest_blueprint(
            row.id, row.tenant_id
        ).version
    except NotFound:
        value["latest_blueprint_version"] = None
    submission = repository.submission_for_activity(row.id, row.tenant_id)
    if submission is not None:
        value["submission_id"] = submission.id
    return value


def _activity_response(row: ActivityRow, repository: Repository) -> JSONResponse:
    response = JSONResponse({"activity": _activity_payload(row, repository)})
    response.headers["ETag"] = f'"{canonical_hash(row.config)}"'
    return response


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


def _submission_payload(row: SubmissionRow) -> dict[str, Any]:
    state = m.SubmissionProcessingState.model_validate(row.state).model_dump(mode="json")
    state.update(
        {
            "submission_id": row.id,
            "activity_id": row.activity_id,
            "subject_ref": row.subject_ref,
        }
    )
    return state


def _blueprint_response(row: Any) -> JSONResponse:
    response = JSONResponse(
        {
            "blueprint": row.data,
            "review": row.review,
            "issues": (row.review or {}).get("diagnostics", []),
            "etag": row.etag,
            "version": row.version,
        }
    )
    response.headers["ETag"] = row.etag
    return response


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
    app = FastAPI(
        title="Comprehension Verification Lab",
        version="0.2.0",
        docs_url="/api/docs" if selected.environment != "cloud" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if selected.environment != "cloud" else None,
    )
    app.state.runtime = runtime

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
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
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def replay_response(
        descriptor: dict[str, Any], actor: Actor
    ) -> JSONResponse:
        kind = descriptor.get("kind")
        if kind == "upload":
            artifact = cast(
                ArtifactRow,
                runtime.repository.scoped(
                    ArtifactRow, str(descriptor["artifact_id"]), actor.workspace_id
                ),
            )
            # Completion moves the durable row to a sealed content-addressed
            # key. Replays may only reissue the original disposable upload
            # capability, never a PUT capability for the sealed artifact.
            pending_key = (
                f"raw/{artifact.tenant_id}/{artifact.activity_id}/"
                f"{artifact.id}/upload"
            )
            signed = runtime.object_store.sign_put(
                pending_key,
                artifact.declared_media_type,
                artifact.expected_byte_size,
            )
            body = {
                "upload": {
                    "artifact_id": artifact.id,
                    "upload_url": signed.url,
                    "expires_at": signed.expires_at.isoformat(),
                    "upload_headers": signed.headers,
                    "artifact": _artifact_payload(artifact),
                }
            }
        elif kind == "export":
            row = cast(
                ExportRow,
                runtime.repository.scoped(
                    ExportRow, str(descriptor["export_id"]), actor.workspace_id
                ),
            )
            api_kind = str(descriptor["export_kind"])
            stored_kind = {
                "ASSESSMENT_PDF": "assessment_pdf",
                "GUIDE_PDF": "guide_pdf",
                "CANONICAL_JSON": "canonical_json",
            }[api_kind]
            item = runtime.service.export_artifact(row, stored_kind)
            body = {
                "export": {
                    "export_id": row.id,
                    "kind": api_kind,
                    "status": row.status,
                    "download_url": item["url"],
                    "expires_at": item["expires_at"],
                    "sha256": item["sha256"],
                    "byte_size": item["byte_size"],
                }
            }
        else:
            body = cast(dict[str, Any], descriptor["body"])
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
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if response.headers.get("etag"):
            headers["etag"] = str(response.headers["etag"])
        if request.url.path.endswith("/artifacts/uploads"):
            upload = cast(dict[str, Any], body["upload"])
            return {
                "kind": "upload",
                "artifact_id": upload["artifact_id"],
                "status_code": response.status_code,
                "headers": headers,
            }
        if request.url.path.endswith("/exports"):
            exported = cast(dict[str, Any], body["export"])
            return {
                "kind": "export",
                "export_id": exported["export_id"],
                "export_kind": exported["kind"],
                "status_code": response.status_code,
                "headers": headers,
            }
        return {
            "kind": "json",
            "body": body,
            "status_code": response.status_code,
            "headers": headers,
        }

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
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "if_match": request.headers.get("if-match"),
                "body": canonical_body,
            }
        )
        try:
            replay = runtime.repository.reserve_idempotency(
                actor.workspace_id, key, fingerprint
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
            descriptor = replay_descriptor(request, response, parsed)
            runtime.repository.complete_idempotency(
                actor.workspace_id, key, fingerprint, descriptor
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
            instance=request.url.path,
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

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "stage": "1", "model_mode": selected.model_mode}

    @app.get("/api/v1/session")
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

    @app.post("/api/v1/session/login")
    def login(
        response: Response,
        payload: Annotated[dict[str, Any], Body(...)],
    ) -> dict[str, Any]:
        email = str(payload.get("email", "")).strip().lower()
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

    @app.post("/api/v1/session/exchange")
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

    @app.get("/api/v1/activities")
    def activities(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        return {
            "items": [
                _activity_payload(row, runtime.repository)
                for row in runtime.repository.activities(actor.workspace_id)
            ]
        }

    @app.post("/api/v1/activities", status_code=201)
    def create_activity(
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        title = str(payload.get("title", "")).strip()
        activity_id = stable_id("act", actor.workspace_id, title, datetime.now(UTC))
        canonical = m.ActivityConfig.model_validate(
            {
                **payload,
                "activity_id": activity_id,
                "tenant_id": actor.workspace_id,
                "context_mode": "CLOSED",
                "course_source_ids": [],
                "require_blueprint_approval": True,
                "allowed_artifact_media_types": payload.get(
                    "allowed_artifact_media_types", sorted(ALLOWED_MEDIA_TYPES)
                ),
            }
        )
        row = runtime.service.create_activity(canonical, actor)
        return {"activity": _activity_payload(row, runtime.repository)}

    @app.get("/api/v1/activities/{activity_id}")
    def activity_detail(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> Response:
        row = cast(
            ActivityRow,
            runtime.repository.scoped(ActivityRow, activity_id, actor.workspace_id),
        )
        return _activity_response(row, runtime.repository)

    @app.patch("/api/v1/activities/{activity_id}")
    def edit_activity(
        activity_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> Response:
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
                **payload,
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
        return _activity_response(row, runtime.repository)

    def prepare_upload(
        *,
        activity_id: str,
        submission_id: str | None,
        payload: dict[str, Any],
        actor: Actor,
    ) -> dict[str, Any]:
        try:
            claimed_size = int(payload.get("byte_size", 0))
        except (TypeError, ValueError) as exc:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Declared object size is invalid") from exc
        if claimed_size < 1 or claimed_size > selected.max_upload_bytes:
            raise WorkflowError("INGEST_SIZE_LIMIT", "Declared object size is invalid")
        try:
            role = m.ArtifactRole(str(payload.get("role", "")))
        except ValueError as exc:
            raise WorkflowError("INGEST_ROLE_INVALID", "Artifact role is not accepted") from exc
        row, upload = runtime.service.create_upload(
            actor=actor,
            activity_id=activity_id,
            submission_id=submission_id,
            filename=str(payload.get("filename", "")),
            media_type=str(payload.get("media_type", "")),
            expected_byte_size=claimed_size,
            role=role,
        )
        upload_headers = upload.pop("headers", {})
        return {
            "upload": {
                **upload,
                "upload_headers": upload_headers,
                "artifact": _artifact_payload(row),
            }
        }

    @app.post("/api/v1/activities/{activity_id}/artifacts/uploads", status_code=201)
    def activity_upload(
        activity_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        return prepare_upload(
            activity_id=activity_id, submission_id=None, payload=payload, actor=actor
        )

    @app.post("/api/v1/submissions/{submission_id}/artifacts/uploads", status_code=201)
    def submission_upload(
        submission_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
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
        artifact_id: str, payload: dict[str, Any], actor: Actor
    ) -> dict[str, Any]:
        try:
            claimed_size = int(payload.get("byte_size", -1))
        except (TypeError, ValueError) as exc:
            raise WorkflowError(
                "UPLOAD_COMPLETION_MISMATCH", "Completion metadata does not match the object"
            ) from exc
        runtime.service.complete_upload(
            artifact_id,
            actor,
            claimed_sha256=str(payload.get("sha256", "")),
            claimed_byte_size=claimed_size,
            claimed_media_type=str(payload.get("media_type", "")),
        )
        completed = cast(
            ArtifactRow,
            runtime.repository.scoped(
                ArtifactRow, artifact_id, actor.workspace_id
            ),
        )
        return {"artifact": _artifact_payload(completed)}

    @app.post("/api/v1/activities/{activity_id}/artifacts/{artifact_id}:complete")
    def complete_activity_artifact(
        activity_id: str,
        artifact_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        row = cast(ArtifactRow, runtime.repository.scoped(ArtifactRow, artifact_id, actor.workspace_id))
        if row.activity_id != activity_id or row.submission_id is not None:
            raise NotFound("artifact not found")
        return complete_artifact(artifact_id, payload, actor)

    @app.post("/api/v1/submissions/{submission_id}/artifacts/{artifact_id}:complete")
    def complete_submission_artifact(
        submission_id: str,
        artifact_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        row = cast(ArtifactRow, runtime.repository.scoped(ArtifactRow, artifact_id, actor.workspace_id))
        if row.submission_id != submission_id:
            raise NotFound("artifact not found")
        return complete_artifact(artifact_id, payload, actor)

    @app.post("/api/v1/activities/{activity_id}/blueprints:generate", status_code=202)
    async def generate_blueprint(
        activity_id: str,
        _payload: Annotated[dict[str, Any], Body(default_factory=dict)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        job = await runtime.service.enqueue_activity_pipeline(activity_id, actor)
        return {"job_id": job.job_id, "operation": job.model_dump(mode="json")}

    @app.get("/api/v1/activities/{activity_id}/ambiguity")
    def activity_ambiguity(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return runtime.service.ambiguity_view(activity_id, actor)

    @app.post("/api/v1/activities/{activity_id}/decisions", status_code=201)
    def create_policy_decision(
        activity_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        decision = runtime.service.record_policy_decision(
            activity_id=activity_id,
            issue_id=str(payload.get("issue_id", "")),
            selected_option_id=str(payload.get("selected_option_id", "")),
            note=(str(payload["note"]) if payload.get("note") is not None else None),
            actor=actor,
        )
        return {"decision": decision.model_dump(mode="json")}

    @app.get("/api/v1/activities/{activity_id}/blueprints/latest")
    def latest_blueprint(
        activity_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> Response:
        return _blueprint_response(
            runtime.repository.latest_blueprint(activity_id, actor.workspace_id)
        )

    @app.get("/api/v1/activities/{activity_id}/blueprints/{version}")
    def blueprint_version(
        activity_id: str,
        version: int,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> Response:
        return _blueprint_response(
            runtime.repository.blueprint_version(activity_id, version, actor.workspace_id)
        )

    @app.patch("/api/v1/activities/{activity_id}/blueprints/{version}")
    async def edit_blueprint(
        activity_id: str,
        version: int,
        edited: m.AssessmentBlueprint,
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> Response:
        if not if_match:
            raise WorkflowError("IF_MATCH_REQUIRED", "If-Match is required", status_code=428)
        row = await runtime.service.edit_blueprint(
            activity_id=activity_id,
            version=version,
            if_match=if_match,
            edited=edited,
            actor=actor,
        )
        return _blueprint_response(row)

    @app.post("/api/v1/activities/{activity_id}/blueprints/{version}:approve")
    def approve_blueprint(
        activity_id: str,
        version: int,
        _payload: Annotated[dict[str, Any], Body(default_factory=dict)],
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> Response:
        if not if_match:
            raise WorkflowError("IF_MATCH_REQUIRED", "If-Match is required", status_code=428)
        return _blueprint_response(
            runtime.service.approve_blueprint(
                activity_id=activity_id,
                version=version,
                if_match=if_match,
                actor=actor,
            )
        )

    @app.post("/api/v1/activities/{activity_id}/submissions", status_code=201)
    def create_submission(
        activity_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        row = runtime.service.create_submission(
            activity_id=activity_id,
            subject_ref=str(payload.get("subject_ref", "")).strip(),
            actor=actor,
        )
        return {"submission": _submission_payload(row)}

    @app.get("/api/v1/submissions/{submission_id}")
    def submission_detail(
        submission_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        row = cast(
            SubmissionRow,
            runtime.repository.scoped(SubmissionRow, submission_id, actor.workspace_id),
        )
        payload = _submission_payload(row)
        try:
            payload["assessment_id"] = runtime.repository.latest_assessment(
                row.id, actor.workspace_id
            ).assessment_id
        except NotFound:
            payload["assessment_id"] = None
        return {"submission": payload}

    @app.post("/api/v1/submissions/{submission_id}:run", status_code=202)
    async def run_submission(
        submission_id: str,
        _payload: Annotated[dict[str, Any], Body(default_factory=dict)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        job = await runtime.service.enqueue_submission_pipeline(submission_id, actor)
        return {
            "job_id": job.job_id,
            "submission_id": submission_id,
            "operation": job.model_dump(mode="json"),
        }

    @app.get("/api/v1/jobs/{job_id}")
    def job_status(
        job_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        return {"job": runtime.repository.job_status(job_id, actor.workspace_id).model_dump(mode="json")}

    @app.get("/api/v1/jobs/{job_id}/model-calls")
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

    @app.get("/api/v1/submissions/{submission_id}/evidence")
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
            "items": [
                {
                    **item["evidence"],
                    "view_url": item["source_url"],
                    "view_url_expires_at": item["source_url_expires_at"],
                }
                for item in page
            ],
            "next_cursor": str(next_offset) if next_offset < len(items) else None,
        }

    @app.get("/api/v1/submissions/{submission_id}/assessment")
    def assessment(
        submission_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        value = runtime.service.assessment_view(submission_id, actor)
        value["evidence"] = evidence(submission_id, actor)["items"]
        return value

    @app.get("/api/v1/assessments/{assessment_id}/guide")
    def guide(
        assessment_id: str,
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> dict[str, Any]:
        row = cast(
            GuideRow,
            runtime.repository.guide_for_assessment(assessment_id, actor.workspace_id),
        )
        return {"guide": row.data}

    @app.post("/api/v1/assessments/{assessment_id}:approve")
    def approve_assessment(
        assessment_id: str,
        _payload: Annotated[dict[str, Any], Body(default_factory=dict)],
        actor: Annotated[Actor, Depends(mutating_actor)],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        if not if_match:
            raise WorkflowError(
                "IF_MATCH_REQUIRED", "If-Match is required", status_code=428
            )
        row = runtime.service.approve_assessment(
            assessment_id=assessment_id,
            if_match=if_match,
            actor=actor,
        )
        return runtime.service.assessment_view(row.submission_id, actor)

    @app.post("/api/v1/assessments/{assessment_id}/exports", status_code=201)
    def create_export(
        assessment_id: str,
        payload: Annotated[dict[str, Any], Body(...)],
        actor: Annotated[Actor, Depends(mutating_actor)],
    ) -> dict[str, Any]:
        kind = str(payload.get("kind", ""))
        key_by_kind = {
            "ASSESSMENT_PDF": "assessment_pdf",
            "GUIDE_PDF": "guide_pdf",
            "CANONICAL_JSON": "canonical_json",
        }
        if kind not in key_by_kind:
            raise WorkflowError("EXPORT_KIND_INVALID", "Export kind is not enabled")
        row = runtime.service.create_export(assessment_id, actor)
        item = runtime.service.export_artifact(row, key_by_kind[kind])
        return {
            "export": {
                "export_id": row.id,
                "kind": kind,
                "status": row.status,
                "download_url": item["url"],
                "expires_at": item["expires_at"],
                "sha256": item["sha256"],
                "byte_size": item["byte_size"],
            }
        }

    frontend = Path(selected.frontend_dist).resolve()

    @app.get("/{spa_path:path}", include_in_schema=False)
    def frontend_route(spa_path: str) -> Response:
        if spa_path.startswith("api/"):
            raise NotFound("API route not found")
        candidate = (frontend / spa_path).resolve()
        if candidate.is_file() and (candidate == frontend or frontend in candidate.parents):
            return FileResponse(candidate)
        index = frontend / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise NotFound("frontend build not found")

    return app


app = create_app()
