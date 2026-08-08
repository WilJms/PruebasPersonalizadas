from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from comprehension_verification.canonical import sha256_bytes, stable_id
from comprehension_verification.contracts import models as m
from comprehension_verification.web import dto
from comprehension_verification.web.app import create_app
from comprehension_verification.web.jobs import RecordingJobRunner
from comprehension_verification.web.repository import (
    ActivityRow,
    ExportRow,
    IdempotencyRow,
    JobControlRecordRow,
    JobRow,
    Repository,
    StageRunRow,
    SubmissionRow,
    WorkspaceRoleRow,
    utc_now,
)
from comprehension_verification.web.settings import Settings


TENANT_ID = "tnt_experimental"


def _app(
    *,
    job_runner: RecordingJobRunner | None = None,
    frontend_dist: str = "frontend/dist",
):
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        session_secret="stage2-web-test-secret-with-sufficient-length",
        local_invited_emails=(
            "teacher@example.test,reviewer@example.test,assistant@example.test"
        ),
        model_mode="mock",
        frontend_dist=frontend_dist,
        api_mutation_rate_limit_per_minute=500,
        api_read_rate_limit_per_minute=500,
    )
    return create_app(
        settings,
        job_runner=job_runner,
        inline_wait_for_completion=job_runner is None,
    )


def _login(client: TestClient, email: str = "teacher@example.test") -> dict[str, str]:
    response = client.post("/api/v1/session/login", json={"email": email})
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("cva_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


def _mutating(
    headers: dict[str, str],
    *,
    idempotency_key: str | None = None,
    **extra: str,
) -> dict[str, str]:
    return {
        **headers,
        "Idempotency-Key": idempotency_key or str(uuid4()),
        **extra,
    }


def _other_workspace_client(app: Any) -> tuple[TestClient, dict[str, str]]:
    user_id = "usr_stage2_other"
    workspace_id = "tnt_stage2_other"
    csrf = "csrf-stage2-other-workspace"
    app.state.runtime.repository.seed_workspace(
        workspace_id,
        [(user_id, "other-stage2@example.test", "TEACHER")],
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "cva-web",
            "aud": "cva-web",
            "sub": user_id,
            "workspace_id": workspace_id,
            "csrf": csrf,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        app.state.runtime.settings.session_secret,
        algorithm="HS256",
    )
    client = TestClient(app)
    client.cookies.set("cva_session", token)
    client.cookies.set("cva_csrf", csrf)
    return client, {"X-CSRF-Token": csrf}


def _create_activity(
    client: TestClient,
    headers: dict[str, str],
    *,
    question_count: int = 1,
) -> str:
    response = client.post(
        "/api/v1/activities",
        headers=_mutating(headers),
        json={
            "title": "Actividad de integración Stage 2",
            "output_language": "es-CL",
            "assessment_modality": "WRITTEN",
            "question_count": question_count,
            "target_total_minutes": 4 * question_count,
            "allowed_response_formats": ["OPEN_SHORT"],
            "allowed_artifact_media_types": ["text/markdown"],
            "structured_justification_mode": "NOT_REQUIRED",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["activity"]["activity_id"])


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    start_path: str,
    complete_path: str,
    role: str,
    filename: str,
    content: bytes,
    media_type: str = "text/markdown",
) -> dict[str, Any]:
    started = client.post(
        start_path,
        headers=_mutating(headers),
        json={
            "role": role,
            "filename": filename,
            "media_type": media_type,
            "byte_size": len(content),
        },
    )
    assert started.status_code == 201, started.text
    upload = started.json()["upload"]
    sent = client.put(
        upload["upload_url"],
        headers=upload["upload_headers"],
        content=content,
    )
    assert sent.status_code == 204, sent.text
    completed = client.post(
        complete_path.format(artifact_id=upload["artifact_id"]),
        headers=_mutating(headers),
        json={
            "sha256": sha256_bytes(content),
            "byte_size": len(content),
            "media_type": media_type,
        },
    )
    assert completed.status_code == 200, completed.text
    return completed.json()["artifact"]


def test_upload_idempotency_replay_reissues_exact_disposable_reservation() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        activity_id = _create_activity(client, headers)
        content = b"# Consigna\n\nEvidencia sintetica para replay durable.\n"
        payload = {
            "role": "ASSIGNMENT_PROMPT",
            "filename": "replay.md",
            "media_type": "text/markdown",
            "byte_size": len(content),
        }
        key = str(uuid4())
        path = f"/api/v1/activities/{activity_id}/artifacts/uploads"

        started = client.post(
            path,
            headers=_mutating(headers, idempotency_key=key),
            json=payload,
        )
        assert started.status_code == 201, started.text
        artifact_id = started.json()["upload"]["artifact_id"]

        replayed = client.post(
            path,
            headers=_mutating(headers, idempotency_key=key),
            json=payload,
        )
        assert replayed.status_code == 201, replayed.text
        assert replayed.headers["Idempotency-Replayed"] == "true"
        replayed_upload = replayed.json()["upload"]
        assert replayed_upload["artifact"]["status"] == "PENDING"

        sent = client.put(
            replayed_upload["upload_url"],
            headers=replayed_upload["upload_headers"],
            content=content,
        )
        assert sent.status_code == 204, sent.text
        completed = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/{artifact_id}:complete",
            headers=_mutating(headers),
            json={
                "sha256": sha256_bytes(content),
                "byte_size": len(content),
                "media_type": "text/markdown",
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["artifact"]["status"] == "COMPLETE"

        replayed_after_completion = client.post(
            path,
            headers=_mutating(headers, idempotency_key=key),
            json=payload,
        )
        assert replayed_after_completion.status_code == 201
        assert replayed_after_completion.json()["upload"]["artifact"]["status"] == (
            "PENDING"
        )

        repository: Repository = app.state.runtime.repository
        descriptor = repository.scoped(
            IdempotencyRow,
            stable_id("idem", TENANT_ID, key),
            TENANT_ID,
        ).response
        assert descriptor is not None
        assert descriptor["upload_object_key"].startswith(
            f"raw/{TENANT_ID}/{activity_id}/{artifact_id}/"
        )
        serialized = json.dumps(descriptor, sort_keys=True)
        assert "upload_url" not in serialized
        assert "/api/v1/object-uploads/" not in serialized


def _approve_blueprint(
    client: TestClient,
    headers: dict[str, str],
    activity_id: str,
) -> dict[str, Any]:
    assignment = (
        b"# Consigna\n\nExplique una decision del flujo y su consecuencia local.\n\n"
        b"Distinga evidencia observable de una inferencia no autorizada.\n"
    )
    _upload(
        client,
        headers,
        start_path=f"/api/v1/activities/{activity_id}/artifacts/uploads",
        complete_path=(
            f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete"
        ),
        role="ASSIGNMENT_PROMPT",
        filename="assignment.md",
        content=assignment,
    )
    generated = client.post(
        f"/api/v1/activities/{activity_id}/blueprints:generate",
        headers=_mutating(headers),
        json={},
    )
    assert generated.status_code == 202, generated.text
    job_id = generated.json()["job_id"]
    job = client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200, job.text
    assert job.json()["job"]["status"] == "SUCCEEDED", job.text
    latest = client.get(f"/api/v1/activities/{activity_id}/blueprints/latest")
    assert latest.status_code == 200, latest.text
    version = int(latest.json()["version"])
    approved = client.post(
        f"/api/v1/activities/{activity_id}/blueprints/{version}:approve",
        headers=_mutating(headers, **{"If-Match": latest.headers["etag"]}),
        json={},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _processed_submission(
    client: TestClient,
    headers: dict[str, str],
    *,
    question_count: int = 1,
    subject_ref: str = "subject_stage2_web",
) -> dict[str, Any]:
    activity_id = _create_activity(
        client, headers, question_count=question_count
    )
    _approve_blueprint(client, headers, activity_id)
    batch = client.post(
        f"/api/v1/activities/{activity_id}/submissions:batch",
        headers=_mutating(headers),
        json={"subject_refs": [subject_ref]},
    )
    assert batch.status_code == 201, batch.text
    submission_id = batch.json()["submissions"][0]["submission_id"]
    deliverable = (
        b"# Entrega\n\nLa deduplicacion ocurre antes del promedio para evitar doble peso.\n\n"
        b"Los valores extremos se conservan y se marcan para revision.\n\n"
        b"Cada fila mantiene el identificador de origen para trazabilidad.\n\n"
        b"La evidencia no permite decidir si un extremo es falla o evento real.\n"
    )
    artifact = _upload(
        client,
        headers,
        start_path=f"/api/v1/submissions/{submission_id}/artifacts/uploads",
        complete_path=(
            f"/api/v1/submissions/{submission_id}/artifacts/{{artifact_id}}:complete"
        ),
        role="SUBMISSION",
        filename="submission.md",
        content=deliverable,
    )
    started = client.post(
        f"/api/v1/submissions/{submission_id}:run",
        headers=_mutating(headers),
        json={},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    job = client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200, job.text
    assert job.json()["job"]["status"] == "SUCCEEDED", job.text
    review = client.get(f"/api/v1/submissions/{submission_id}/assessment")
    assert review.status_code == 200, review.text
    dto.AssessmentEnvelope.model_validate(review.json())
    return {
        "activity_id": activity_id,
        "submission_id": submission_id,
        "assessment_id": review.json()["assessment"]["assessment_id"],
        "job_id": job_id,
        "artifact": artifact,
        "deliverable": deliverable,
        "review": review.json(),
        "etag": review.headers["etag"],
    }


def _verify_all_evidence(
    client: TestClient,
    headers: dict[str, str],
    fixture: dict[str, Any],
) -> None:
    review = fixture["review"]
    assessment_id = fixture["assessment_id"]
    for question in review["assessment"]["questions"]:
        for index, _fragment in enumerate(question["anchor"]["fragments"]):
            verified = client.post(
                f"/api/v1/assessments/{assessment_id}/evidence:verify",
                headers=_mutating(headers),
                json={
                    "assessment_version": review["assessment_version"],
                    "assessment_etag": review["etag"],
                    "question_id": question["question_id"],
                    "fragment_index": index,
                },
            )
            assert verified.status_code == 200, verified.text


def _approve_assessment(
    client: TestClient,
    headers: dict[str, str],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    _verify_all_evidence(client, headers, fixture)
    approved = client.post(
        f"/api/v1/assessments/{fixture['assessment_id']}:approve",
        headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
        json={},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_batch_is_atomic_filterable_and_cross_tenant_fail_closed() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        activity_id = _create_activity(client, headers)
        created = client.post(
            f"/api/v1/activities/{activity_id}/submissions:batch",
            headers=_mutating(headers),
            json={"subject_refs": ["subject_a", "subject_b", "subject_c"]},
        )
        assert created.status_code == 201, created.text
        assert created.json()["created_count"] == 3
        assert all(
            item["artifact_uploaded"] is False
            for item in created.json()["submissions"]
        )
        assert {
            item["subject_ref"] for item in created.json()["submissions"]
        } == {"subject_a", "subject_b", "subject_c"}

        filtered = client.get(
            f"/api/v1/activities/{activity_id}/submissions",
            params={"subject_ref": "subject_b", "status": "UPLOADED"},
        )
        assert filtered.status_code == 200, filtered.text
        assert [item["subject_ref"] for item in filtered.json()["items"]] == [
            "subject_b"
        ]

        conflict = client.post(
            f"/api/v1/activities/{activity_id}/submissions:batch",
            headers=_mutating(headers),
            json={"subject_refs": ["subject_c", "subject_d"]},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "SUBMISSION_SUBJECT_ALREADY_EXISTS"
        unchanged = client.get(
            f"/api/v1/activities/{activity_id}/submissions"
        ).json()["items"]
        assert {item["subject_ref"] for item in unchanged} == {
            "subject_a",
            "subject_b",
            "subject_c",
        }

        other, other_headers = _other_workspace_client(app)
        with other:
            hidden = other.get(
                f"/api/v1/activities/{activity_id}/submissions"
            )
            assert hidden.status_code == 404
            forbidden_create = other.post(
                f"/api/v1/activities/{activity_id}/submissions:batch",
                headers=_mutating(other_headers),
                json={"subject_refs": ["subject_leak"]},
            )
            assert forbidden_create.status_code == 404


def test_job_control_normalizes_legacy_submillisecond_stage_timestamp_inversion() -> None:
    app = _app()
    started_at = utc_now()
    job = JobRow(
        id="job_legacy_timestamp",
        tenant_id=TENANT_ID,
        kind="SUBMISSION",
        aggregate_id="sub_legacy_timestamp",
        stage="P06",
        status="SUCCEEDED",
        progress=1.0,
        attempt=1,
        diagnostics=[],
    )
    row = StageRunRow(
        id="stage_legacy_timestamp",
        job_id=job.id,
        tenant_id=TENANT_ID,
        stage="P06",
        stage_key="sha256:" + "a" * 64,
        status="SUCCEEDED",
        attempt=1,
        input_hash="sha256:" + "b" * 64,
        policy_hash="sha256:" + "c" * 64,
        component_version="prompt-pack/1.1.0",
        output={"synthetic": True},
        output_hash="sha256:" + "d" * 64,
        diagnostics=[],
        started_at=started_at,
        finished_at=started_at - timedelta(microseconds=1),
    )

    projected = app.state.runtime.stage2._stage_run_contract(row, job)

    assert projected.finished_at == projected.started_at
    assert projected.diagnostics[-1].code == "STAGE_TIMESTAMP_NORMALIZED"


def test_dispatch_failure_remains_transient_and_chainable_once() -> None:
    class FailingRunner:
        async def dispatch(self, _job_id: str) -> None:
            raise ConnectionError("synthetic dispatcher unavailable")

    app = _app(job_runner=FailingRunner())  # type: ignore[arg-type]
    with TestClient(app) as client:
        headers = _login(client)
        repository: Repository = app.state.runtime.repository
        repository.add(
            ActivityRow(
                id="act_dispatch_failure",
                tenant_id=TENANT_ID,
                status="TECHNICAL_FAILURE",
                config={},
                blueprint_policy={},
                created_by="usr_dispatch_failure",
            )
        )
        state = m.SubmissionProcessingState(
            submission_id="sub_dispatch_failure",
            activity_id="act_dispatch_failure",
            status=m.SubmissionProcessingStatus.TECHNICAL_FAILURE,
            current_stage="SUBMISSION_PARSE",
            progress=0.2,
            active_job_id="job_dispatch_source",
            updated_at=utc_now(),
        )
        repository.create_submissions(
            [
                SubmissionRow(
                    id="sub_dispatch_failure",
                    tenant_id=TENANT_ID,
                    activity_id="act_dispatch_failure",
                    subject_ref="subject_dispatch_failure",
                    state=state.model_dump(mode="json"),
                    active_job_id="job_dispatch_source",
                )
            ]
        )
        repository.add(
            JobRow(
                id="job_dispatch_source",
                tenant_id=TENANT_ID,
                kind="SUBMISSION",
                aggregate_id="sub_dispatch_failure",
                stage="SUBMISSION_PARSE",
                status="FAILED",
                progress=0.2,
                attempt=1,
                diagnostics=[],
                failure_class="TRANSIENT",
                finished_at=utc_now(),
            )
        )

        response = client.post(
            "/api/v1/jobs/job_dispatch_source:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "RETRY_DISPATCH_FAILURE",
                "target_stage": "SUBMISSION_PARSE",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["job"]["status"] == "FAILED"
        assert body["failure_class"] == "TRANSIENT"
        assert body["job"]["diagnostics"][0]["code"] == "JOB_DISPATCH_FAILED"
        assert body["job"]["diagnostics"][0]["retryable"] is True
        assert body["allowed_actions"] == ["RETRY"]


def test_assistant_can_operate_submissions_but_cannot_approve_or_upload_activity_sources() -> None:
    app = _app()
    with TestClient(app) as teacher:
        teacher_headers = _login(teacher)
        fixture = _processed_submission(teacher, teacher_headers)
        created = teacher.post(
            f"/api/v1/activities/{fixture['activity_id']}/submissions:batch",
            headers=_mutating(teacher_headers),
            json={"subject_refs": ["subject_guard_a", "subject_guard_b"]},
        )
        assert created.status_code == 201, created.text
        unreserved_id, reserved_id = [
            item["submission_id"] for item in created.json()["submissions"]
        ]
        content = b"# Entrega sintetica protegida\n"
        started = teacher.post(
            f"/api/v1/submissions/{reserved_id}/artifacts/uploads",
            headers=_mutating(teacher_headers),
            json={
                "role": "SUBMISSION",
                "filename": "guarded.md",
                "media_type": "text/markdown",
                "byte_size": len(content),
            },
        )
        assert started.status_code == 201, started.text
        upload = started.json()["upload"]
        sent = teacher.put(
            upload["upload_url"], headers=upload["upload_headers"], content=content
        )
        assert sent.status_code == 204, sent.text

        with TestClient(app) as assistant:
            assistant_headers = _login(assistant, "assistant@example.test")
            reserve = assistant.post(
                f"/api/v1/submissions/{unreserved_id}/artifacts/uploads",
                headers=_mutating(assistant_headers),
                json={
                    "role": "SUBMISSION",
                    "filename": "assistant.md",
                    "media_type": "text/markdown",
                    "byte_size": len(content),
                },
            )
            assert reserve.status_code == 201, reserve.text
            assistant_upload = reserve.json()["upload"]
            sent_by_assistant = assistant.put(
                assistant_upload["upload_url"],
                headers=assistant_upload["upload_headers"],
                content=content,
            )
            assert sent_by_assistant.status_code == 204, sent_by_assistant.text
            assistant_completed = assistant.post(
                (
                    f"/api/v1/submissions/{unreserved_id}/artifacts/"
                    f"{assistant_upload['artifact_id']}:complete"
                ),
                headers=_mutating(assistant_headers),
                json={
                    "sha256": sha256_bytes(content),
                    "byte_size": len(content),
                    "media_type": "text/markdown",
                },
            )
            assert assistant_completed.status_code == 200, assistant_completed.text
            projected = assistant.get(f"/api/v1/submissions/{unreserved_id}")
            assert projected.status_code == 200, projected.text
            assert projected.json()["submission"]["artifact_uploaded"] is True

            complete = assistant.post(
                (
                    f"/api/v1/submissions/{reserved_id}/artifacts/"
                    f"{upload['artifact_id']}:complete"
                ),
                headers=_mutating(assistant_headers),
                json={
                    "sha256": sha256_bytes(content),
                    "byte_size": len(content),
                    "media_type": "text/markdown",
                },
            )
            assert complete.status_code == 200, complete.text

            run = assistant.post(
                f"/api/v1/submissions/{unreserved_id}:run",
                headers=_mutating(assistant_headers),
                json={},
            )
            assert run.status_code == 202, run.text
            assistant_job = assistant.get(f"/api/v1/jobs/{run.json()['job_id']}")
            assert assistant_job.status_code == 200, assistant_job.text
            assert assistant_job.json()["job"]["status"] == "SUCCEEDED"

            question_id = fixture["review"]["assessment"]["questions"][0][
                "question_id"
            ]
            reviewed = assistant.post(
                (
                    f"/api/v1/assessments/{fixture['assessment_id']}/questions/"
                    f"{question_id}/actions"
                ),
                headers=_mutating(
                    assistant_headers, **{"If-Match": fixture["etag"]}
                ),
                json={"action": "ACCEPT"},
            )
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["action_record"]["status"] == "APPLIED"

            activity_source = assistant.post(
                f"/api/v1/activities/{fixture['activity_id']}/artifacts/uploads",
                headers=_mutating(assistant_headers),
                json={
                    "role": "RUBRIC",
                    "filename": "assistant-rubric.md",
                    "media_type": "text/markdown",
                    "byte_size": len(content),
                },
            )
            assert activity_source.status_code == 403, activity_source.text
            assert activity_source.json()["code"] == "ROLE_FORBIDDEN"

            blueprint = assistant.get(
                f"/api/v1/activities/{fixture['activity_id']}/blueprints/latest"
            )
            assert blueprint.status_code == 200, blueprint.text
            blueprint_approval = assistant.post(
                (
                    f"/api/v1/activities/{fixture['activity_id']}/blueprints/"
                    f"{blueprint.json()['version']}:approve"
                ),
                headers=_mutating(
                    assistant_headers, **{"If-Match": blueprint.headers["etag"]}
                ),
                json={},
            )
            assert blueprint_approval.status_code == 403, blueprint_approval.text
            assert blueprint_approval.json()["code"] == "ROLE_FORBIDDEN"

            assessment_approval = assistant.post(
                f"/api/v1/assessments/{fixture['assessment_id']}:approve",
                headers=_mutating(
                    assistant_headers, **{"If-Match": fixture["etag"]}
                ),
                json={},
            )
            assert assessment_approval.status_code == 403, assessment_approval.text
            assert assessment_approval.json()["code"] == "ROLE_FORBIDDEN"


def test_assistant_with_explicit_permission_can_request_bulk_approval() -> None:
    app = _app()
    with TestClient(app) as teacher:
        teacher_headers = _login(teacher)
        fixture = _processed_submission(teacher, teacher_headers)
        repository: Repository = app.state.runtime.repository
        assistant_id = stable_id("usr", "assistant@example.test")
        with repository.session() as session:
            membership = session.get(
                WorkspaceRoleRow, (assistant_id, TENANT_ID)
            )
            assert membership is not None
            membership.can_approve_assessments = True

        with TestClient(app) as assistant:
            assistant_headers = _login(assistant, "assistant@example.test")
            requested = assistant.post(
                (
                    f"/api/v1/activities/{fixture['activity_id']}/"
                    "assessments:bulk-approve"
                ),
                headers=_mutating(assistant_headers),
                json={
                    "targets": [
                        {
                            "assessment_id": fixture["assessment_id"],
                            "assessment_version": fixture["review"][
                                "assessment_version"
                            ],
                        }
                    ],
                    "explicit_confirmation": (
                        "CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS"
                    ),
                },
            )
            assert requested.status_code == 200, requested.text
            record = m.BulkApprovalRecord.model_validate(
                requested.json()["bulk_approval"]
            )
            assert record.actor_id == assistant_id
            assert record.approved_targets == []
            assert len(record.excluded_targets) == 1


def test_job_control_http_creates_distinct_retry_and_durable_cancel() -> None:
    runner = RecordingJobRunner()
    app = _app(job_runner=runner)
    with TestClient(app) as client:
        headers = _login(client)
        repository: Repository = app.state.runtime.repository
        repository.add(
            ActivityRow(
                id="act_job_control",
                tenant_id=TENANT_ID,
                status="QUEUED",
                config={},
                blueprint_policy={},
                created_by="usr_job_control",
            )
        )

        def add_submission_job(
            *, job_id: str, submission_id: str, status: str, failure_class: str | None
        ) -> None:
            state = m.SubmissionProcessingState(
                submission_id=submission_id,
                activity_id="act_job_control",
                status=(
                    m.SubmissionProcessingStatus.TECHNICAL_FAILURE
                    if status == "FAILED"
                    else m.SubmissionProcessingStatus.PARSING
                ),
                current_stage="SUBMISSION_PARSE",
                progress=0.2,
                active_job_id=job_id,
                updated_at=utc_now(),
            )
            repository.add(
                SubmissionRow(
                    id=submission_id,
                    tenant_id=TENANT_ID,
                    activity_id="act_job_control",
                    subject_ref=f"subject_{submission_id}",
                    state=state.model_dump(mode="json"),
                    active_job_id=job_id,
                )
            )
            repository.add(
                JobRow(
                    id=job_id,
                    tenant_id=TENANT_ID,
                    kind="SUBMISSION",
                    aggregate_id=submission_id,
                    stage="SUBMISSION_PARSE",
                    status=status,
                    progress=0.2,
                    attempt=1,
                    diagnostics=(
                        [
                            {
                                "code": "MODEL_TIMEOUT",
                                "severity": "ERROR",
                                "message": "A transient boundary failed.",
                                "evidence_ids": [],
                                "source_ids": [],
                                "retryable": True,
                                "details": {},
                            }
                        ]
                        if status == "FAILED"
                        else []
                    ),
                    failure_class=failure_class,
                    started_at=utc_now(),
                    finished_at=utc_now() if status == "FAILED" else None,
                )
            )

        add_submission_job(
            job_id="job_cancel_http",
            submission_id="sub_cancel_http",
            status="RUNNING",
            failure_class=None,
        )
        before_cancel = client.get("/api/v1/jobs/job_cancel_http/control")
        assert before_cancel.status_code == 200, before_cancel.text
        assert before_cancel.json()["allowed_actions"] == ["CANCEL"]
        invalid_cancel = client.post(
            "/api/v1/jobs/job_cancel_http:cancel",
            headers=_mutating(headers),
            json={
                "reason_code": "TEACHER_CANCELLED",
                "target_stage": "SUBMISSION_PARSE",
            },
        )
        assert invalid_cancel.status_code == 422, invalid_cancel.text
        assert invalid_cancel.json()["code"] == "JOB_CONTROL_INVALID"
        cancelled = client.post(
            "/api/v1/jobs/job_cancel_http:cancel",
            headers=_mutating(headers),
            json={"reason_code": "TEACHER_CANCELLED"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["control_state"] == "CANCEL_REQUESTED"
        source_cancel = client.get("/api/v1/jobs/job_cancel_http/control").json()
        assert source_cancel["control_records"][0]["action"] == "CANCEL"

        add_submission_job(
            job_id="job_retry_http",
            submission_id="sub_retry_http",
            status="FAILED",
            failure_class="TRANSIENT",
        )
        retry_key = str(uuid4())
        retried = client.post(
            "/api/v1/jobs/job_retry_http:retry",
            headers=_mutating(headers, idempotency_key=retry_key),
            json={
                "reason_code": "MODEL_TIMEOUT_RETRY",
                "target_stage": "SUBMISSION_PARSE",
            },
        )
        assert retried.status_code == 200, retried.text
        resulting_job_id = retried.json()["job"]["job_id"]
        assert resulting_job_id != "job_retry_http"
        assert retried.json()["job"]["status"] == "QUEUED"
        assert len(retried.json()["control_records"]) == 1
        linked_control = retried.json()["control_records"][0]
        assert linked_control["job_id"] == "job_retry_http"
        assert linked_control["resulting_job_id"] == resulting_job_id
        assert linked_control["action"] == "RETRY"
        assert runner.dispatched == [resulting_job_id]
        source_retry = client.get("/api/v1/jobs/job_retry_http/control").json()
        assert source_retry["job"]["status"] == "FAILED"
        assert source_retry["control_records"][0]["resulting_job_id"] == resulting_job_id
        replayed = client.post(
            "/api/v1/jobs/job_retry_http:retry",
            headers=_mutating(headers, idempotency_key=retry_key),
            json={
                "reason_code": "MODEL_TIMEOUT_RETRY",
                "target_stage": "SUBMISSION_PARSE",
            },
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.headers["Idempotency-Replayed"] == "true"
        assert replayed.json()["job"]["job_id"] == resulting_job_id
        assert runner.dispatched == [resulting_job_id]

        add_submission_job(
            job_id="job_permanent_http",
            submission_id="sub_permanent_http",
            status="FAILED",
            failure_class="PERMANENT",
        )
        permanent = client.get("/api/v1/jobs/job_permanent_http/control")
        assert permanent.status_code == 200, permanent.text
        assert "RESUME" not in permanent.json()["allowed_actions"]
        rejected_resume = client.post(
            "/api/v1/jobs/job_permanent_http:resume",
            headers=_mutating(headers),
            json={
                "reason_code": "PERMANENT_FAILURE_RESUME",
                "target_stage": "SUBMISSION_PARSE",
            },
        )
        assert rejected_resume.status_code == 409, rejected_resume.text
        assert rejected_resume.json()["code"] == "JOB_CONTROL_NOT_ALLOWED"
        assert runner.dispatched == [resulting_job_id]


def test_metrics_count_retry_controls_without_triangular_or_resume_overcount() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        activity_id = _create_activity(client, headers)
        repository: Repository = app.state.runtime.repository
        now = utc_now()
        jobs = [
            ("job_metrics_initial", 1),
            ("job_metrics_retry_one", 2),
            ("job_metrics_retry_two", 3),
            ("job_metrics_resume_source", 1),
            ("job_metrics_resume_result", 2),
        ]
        for job_id, attempt in jobs:
            repository.add(
                JobRow(
                    id=job_id,
                    tenant_id=TENANT_ID,
                    kind="ACTIVITY",
                    aggregate_id=activity_id,
                    stage="ACTIVITY_SPEC",
                    status="FAILED",
                    progress=0.5,
                    attempt=attempt,
                    diagnostics=[],
                    failure_class="TRANSIENT",
                    started_at=now,
                    finished_at=now,
                )
            )
        for control_id, source, result, action, attempt in (
            (
                "control_metrics_retry_one",
                "job_metrics_initial",
                "job_metrics_retry_one",
                "RETRY",
                1,
            ),
            (
                "control_metrics_retry_two",
                "job_metrics_retry_one",
                "job_metrics_retry_two",
                "RETRY",
                2,
            ),
            (
                "control_metrics_resume",
                "job_metrics_resume_source",
                "job_metrics_resume_result",
                "RESUME",
                1,
            ),
        ):
            repository.add(
                JobControlRecordRow(
                    id=control_id,
                    tenant_id=TENANT_ID,
                    job_id=source,
                    resulting_job_id=result,
                    aggregate_id=activity_id,
                    actor_id="usr_stage2_metrics",
                    action=action,
                    status="APPLIED",
                    source_attempt=attempt,
                    target_stage="ACTIVITY_SPEC",
                    failure_class=("TRANSIENT" if action == "RETRY" else None),
                    data={"action": action},
                    requested_at=now,
                    decided_at=now,
                )
            )
        for suffix, job_id in (
            ("retry", "job_metrics_retry_one"),
            ("resume", "job_metrics_resume_result"),
        ):
            repository.add(
                StageRunRow(
                    id=f"stage_metrics_{suffix}",
                    job_id=job_id,
                    tenant_id=TENANT_ID,
                    stage="P01_ACTIVITY_SPEC_V1",
                    stage_key="sha256:" + ("a" if suffix == "retry" else "b") * 64,
                    status="FAILED",
                    attempt=2,
                    input_hash="sha256:" + "c" * 64,
                    policy_hash="sha256:" + "d" * 64,
                    component_version="1.1.0",
                    output=None,
                    output_hash=None,
                    failure_class="TRANSIENT",
                    diagnostics=[],
                    started_at=now,
                    finished_at=now,
                )
            )

        response = client.get(f"/api/v1/activities/{activity_id}/metrics")
        assert response.status_code == 200, response.text
        metrics = m.ExperimentMetrics.model_validate(response.json()["metrics"])
        assert metrics.technical.retry_count == 2
        assert metrics.by_stage[0].stage == "P01_ACTIVITY_SPEC_V1"
        assert metrics.by_stage[0].retries == 1


def test_feedback_governance_coverage_and_metrics_are_canonical() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        activity_id = fixture["activity_id"]
        submission_id = fixture["submission_id"]
        assessment_id = fixture["assessment_id"]
        review = fixture["review"]
        question_id = review["assessment"]["questions"][0]["question_id"]

        submission_coverage = client.get(
            f"/api/v1/submissions/{submission_id}/coverage"
        )
        assert submission_coverage.status_code == 200, submission_coverage.text
        submission_report = m.CoverageReport.model_validate(
            submission_coverage.json()["coverage"]
        )
        assert submission_report.scope == m.CoverageScope.SUBMISSION
        assert submission_report.tenant_id == TENANT_ID
        assert submission_report.submission_id == submission_id
        assert submission_report.assessment_id == assessment_id
        assert submission_report.traces
        assert any(
            item.outcome == m.CoverageOutcome.GENERATED
            for item in submission_report.traces
        )

        activity_coverage = client.get(
            f"/api/v1/activities/{activity_id}/coverage"
        )
        assert activity_coverage.status_code == 200, activity_coverage.text
        activity_report = m.CoverageReport.model_validate(
            activity_coverage.json()["coverage"]
        )
        assert activity_report.scope == m.CoverageScope.ACTIVITY
        assert activity_report.submission_id is None
        assert {item.submission_id for item in activity_report.traces} == {
            submission_id
        }

        metrics_response = client.get(
            f"/api/v1/activities/{activity_id}/metrics"
        )
        assert metrics_response.status_code == 200, metrics_response.text
        metrics = m.ExperimentMetrics.model_validate(
            metrics_response.json()["metrics"]
        )
        assert metrics.tenant_id == TENANT_ID
        assert metrics.activity_id == activity_id
        assert metrics.technical.job_count >= 2
        assert metrics.technical.succeeded_count >= 2
        assert metrics.quality.assessment_count == 1
        assert metrics.quality.exact_plan_count == 1
        assert metrics.technical.input_tokens > 0

        feedback_response = client.post(
            "/api/v1/feedback",
            headers=_mutating(headers),
            json={
                "activity_id": activity_id,
                "target_type": "QUESTION",
                "assessment_id": assessment_id,
                "assessment_version": review["assessment_version"],
                "question_id": question_id,
                "category": "QUESTION_QUALITY",
                "rating": "VERY_HELPFUL",
                "comment": "La pregunta mantiene un anclaje verificable.",
            },
        )
        assert feedback_response.status_code == 201, feedback_response.text
        event = m.FeedbackEvent.model_validate(
            feedback_response.json()["feedback"]
        )
        assert event.rating == m.FeedbackRating.VERY_HELPFUL
        assert event.training_use_allowed is False
        assert event.public_dataset_use_allowed is False
        assert event.academic_decision_use_allowed is False

        invalid_target = client.post(
            "/api/v1/feedback",
            headers=_mutating(headers),
            json={
                "activity_id": activity_id,
                "target_type": "QUESTION",
                "assessment_id": assessment_id,
                "assessment_version": review["assessment_version"] + 1,
                "question_id": question_id,
                "category": "QUESTION_QUALITY",
                "rating": "NEUTRAL",
            },
        )
        assert invalid_target.status_code == 409, invalid_target.text
        assert invalid_target.json()["code"] == "FEEDBACK_TARGET_INVALID"

        invalid_shape = client.post(
            "/api/v1/feedback",
            headers=_mutating(headers),
            json={
                "activity_id": activity_id,
                "target_type": "ACTIVITY",
                "assessment_id": assessment_id,
                "assessment_version": review["assessment_version"],
                "category": "USABILITY",
                "rating": "NEUTRAL",
            },
        )
        assert invalid_shape.status_code == 422, invalid_shape.text
        assert invalid_shape.json()["code"] == "VALIDATION_FAILED"

        listed = client.get(f"/api/v1/activities/{activity_id}/feedback")
        assert listed.status_code == 200, listed.text
        assert [item["feedback_id"] for item in listed.json()["items"]] == [
            event.feedback_id
        ]


def test_question_regeneration_replaces_locally_and_enforces_limit() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        assessment_id = fixture["assessment_id"]
        original_review = fixture["review"]
        original_question = original_review["assessment"]["questions"][0]
        question_id = original_question["question_id"]

        regenerated = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(
                headers, **{"If-Match": fixture["etag"]}
            ),
            json={
                "action": "REGENERATE",
                "reason_code": "TEACHER_REQUESTED_REPLACEMENT",
                "note": "Usar una oportunidad de reserva no redundante.",
            },
        )
        assert regenerated.status_code == 200, regenerated.text
        first_record = m.QuestionReviewActionRecord.model_validate(
            regenerated.json()["action_record"]
        )
        assert first_record.status == m.QuestionReviewRecordStatus.APPLIED
        assert first_record.revalidation_status == m.RevalidationStatus.PASSED
        assert first_record.assessment_version_after == (
            first_record.assessment_version_before + 1
        )
        assert first_record.after_question is not None
        assert first_record.after_question.question_id == question_id
        assert (
            first_record.after_question.opportunity_id
            != original_question["opportunity_id"]
        )
        regenerated_bundle = regenerated.json()["bundle"]
        assert regenerated_bundle["assessment"]["question_count"] == 1
        assert len(regenerated_bundle["assessment"]["questions"]) == 1
        assert (
            regenerated_bundle["assessment"]["questions"][0]["question_id"]
            == question_id
        )

        stale = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(
                headers, **{"If-Match": fixture["etag"]}
            ),
            json={
                "action": "ACCEPT",
            },
        )
        assert stale.status_code == 412, stale.text
        assert stale.json()["code"] == "ETAG_MISMATCH"

        limited = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            ),
            headers=_mutating(
                headers, **{"If-Match": regenerated.headers["etag"]}
            ),
            json={
                "action": "REGENERATE",
                "reason_code": "SECOND_REGENERATION_ATTEMPT",
            },
        )
        assert limited.status_code == 200, limited.text
        limited_record = m.QuestionReviewActionRecord.model_validate(
            limited.json()["action_record"]
        )
        assert limited_record.status == m.QuestionReviewRecordStatus.FAILED
        assert limited_record.assessment_version_after is None
        assert limited_record.after_question is None
        assert [item.code for item in limited_record.diagnostics] == [
            "LOCAL_REGENERATION_LIMIT"
        ]
        assert limited.json()["bundle"]["assessment_version"] == (
            first_record.assessment_version_after
        )
        history = client.get(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{question_id}/actions"
            )
        )
        assert history.status_code == 200, history.text
        historical = [
            m.QuestionReviewActionRecord.model_validate(item)
            for item in history.json()["items"]
        ]
        assert [item.action.action for item in historical] == [
            m.QuestionReviewActionType.REGENERATE,
            m.QuestionReviewActionType.REGENERATE,
        ]
        assert [item.status for item in historical] == [
            m.QuestionReviewRecordStatus.APPLIED,
            m.QuestionReviewRecordStatus.FAILED,
        ]


def test_question_edit_cannot_switch_to_another_planned_opportunity() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers, question_count=2)
        questions = fixture["review"]["assessment"]["questions"]
        target, other = questions
        listing = client.get(
            f"/api/v1/activities/{fixture['activity_id']}/submissions"
        )
        assert listing.status_code == 200, listing.text
        listed = next(
            item
            for item in listing.json()["items"]
            if item["submission_id"] == fixture["submission_id"]
        )
        assert listed["assessment_id"] == fixture["assessment_id"]
        assert listed["assessment_version"] == fixture["review"]["assessment_version"]

        forged = json.loads(json.dumps(other))
        forged["question_id"] = target["question_id"]
        response = client.post(
            (
                f"/api/v1/assessments/{fixture['assessment_id']}/questions/"
                f"{target['question_id']}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
            json={
                "action": "EDIT",
                "note": "Intento sintético de cambiar la ruta planificada.",
                "replacement": forged,
            },
        )

        assert response.status_code == 200, response.text
        record = m.QuestionReviewActionRecord.model_validate(
            response.json()["action_record"]
        )
        assert record.status == m.QuestionReviewRecordStatus.FAILED
        assert record.assessment_version_after is None
        assert record.after_question is None
        assert record.diagnostics[0].code == "QUESTION_EDIT_PATH_CHANGED"
        assert response.json()["bundle"]["assessment_version"] == (
            fixture["review"]["assessment_version"]
        )
        assert response.json()["bundle"]["assessment"]["questions"] == questions


def test_exports_render_all_kinds_without_model_calls_or_durable_capabilities() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers)
        _approve_assessment(client, headers, fixture)
        assessment_id = fixture["assessment_id"]
        repository: Repository = app.state.runtime.repository
        calls_before = repository.model_calls(tenant_id=TENANT_ID)
        all_kinds = [kind.value for kind in m.ExportKind]
        export_key = str(uuid4())
        exported = client.post(
            f"/api/v1/assessments/{assessment_id}/exports",
            headers=_mutating(headers, idempotency_key=export_key),
            json={"kinds": all_kinds},
        )
        assert exported.status_code == 201, exported.text
        envelope = dto.ExportCreateEnvelope.model_validate(exported.json())
        record = envelope.record
        assert record.status == m.ExportStatus.READY
        assert record.requested_kinds == list(m.ExportKind)
        assert record.model_call_delta == 0
        assert len(record.artifacts) == len(m.ExportKind) == 7
        assert len(envelope.downloads) == 7
        assert repository.model_calls(tenant_id=TENANT_ID) == calls_before

        expected_media_types = {
            m.ExportKind.ASSESSMENT_PDF: "application/pdf",
            m.ExportKind.ASSESSMENT_HTML: "text/html",
            m.ExportKind.GUIDE_PDF: "application/pdf",
            m.ExportKind.GUIDE_HTML: "text/html",
            m.ExportKind.COVERAGE_CSV: "text/csv",
            m.ExportKind.COVERAGE_JSON: "application/json",
            m.ExportKind.CANONICAL_JSON: "application/json",
        }
        for download in envelope.downloads:
            downloaded = client.get(download.download_url)
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.headers["content-type"].split(";")[0] == (
                expected_media_types[download.kind]
            )
            assert sha256_bytes(downloaded.content) == download.sha256

        durable = repository.scoped(ExportRow, record.export_id, TENANT_ID)
        assert durable.data is not None
        durable_json = json.dumps(durable.data, sort_keys=True)
        artifacts_json = json.dumps(durable.artifacts, sort_keys=True)
        assert "download_url" not in durable_json
        assert "expires_at" not in durable_json
        assert "/api/v1/objects/" not in durable_json
        assert "download_url" not in artifacts_json
        assert "/api/v1/objects/" not in artifacts_json

        idempotency = repository.scoped(
            IdempotencyRow,
            stable_id("idem", TENANT_ID, export_key),
            TENANT_ID,
        )
        descriptor_json = json.dumps(idempotency.response, sort_keys=True)
        assert idempotency.response is not None
        assert idempotency.response["kind"] == "export"
        assert "download_url" not in descriptor_json
        assert "expires_at" not in descriptor_json
        assert "/api/v1/objects/" not in descriptor_json

        replayed = client.post(
            f"/api/v1/assessments/{assessment_id}/exports",
            headers=_mutating(headers, idempotency_key=export_key),
            json={"kinds": all_kinds},
        )
        assert replayed.status_code == 201, replayed.text
        assert replayed.headers["Idempotency-Replayed"] == "true"
        replay_envelope = dto.ExportCreateEnvelope.model_validate(replayed.json())
        assert replay_envelope.record.export_id == record.export_id
        assert len(replay_envelope.downloads) == 7

        canonical_only = client.post(
            f"/api/v1/assessments/{assessment_id}/exports",
            headers=_mutating(headers),
            json={"kind": "CANONICAL_JSON"},
        )
        assert canonical_only.status_code == 201, canonical_only.text
        canonical_record = m.ExportRecord.model_validate(
            canonical_only.json()["record"]
        )
        assert canonical_record.export_id != record.export_id
        assert canonical_record.requested_kinds == [m.ExportKind.CANONICAL_JSON]
        assert canonical_record.model_call_delta == 0

        history = client.get(f"/api/v1/assessments/{assessment_id}/exports")
        assert history.status_code == 200, history.text
        parsed_history = dto.ExportHistoryEnvelope.model_validate(history.json())
        assert {item.export_id for item in parsed_history.items} == {
            record.export_id,
            canonical_record.export_id,
        }
        assert repository.model_calls(tenant_id=TENANT_ID) == calls_before


def test_bulk_approval_partitions_exclusions_and_is_idempotent() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        fixture = _processed_submission(client, headers, question_count=2)
        assessment_id = fixture["assessment_id"]
        review = fixture["review"]
        for question in review["assessment"]["questions"]:
            accepted = client.post(
                (
                    f"/api/v1/assessments/{assessment_id}/questions/"
                    f"{question['question_id']}/actions"
                ),
                headers=_mutating(headers, **{"If-Match": fixture["etag"]}),
                json={"action": "ACCEPT"},
            )
            assert accepted.status_code == 200, accepted.text
            action = m.QuestionReviewActionRecord.model_validate(
                accepted.json()["action_record"]
            )
            assert action.status == m.QuestionReviewRecordStatus.APPLIED
        _verify_all_evidence(client, headers, fixture)

        missing_target = {
            "assessment_id": "ass_stage2_missing",
            "assessment_version": 1,
        }
        valid_target = {
            "assessment_id": assessment_id,
            "assessment_version": review["assessment_version"],
        }
        payload = {
            "targets": [valid_target, missing_target],
            "explicit_confirmation": (
                "CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS"
            ),
        }
        key = str(uuid4())
        approved = client.post(
            (
                f"/api/v1/activities/{fixture['activity_id']}/"
                "assessments:bulk-approve"
            ),
            headers=_mutating(headers, idempotency_key=key),
            json=payload,
        )
        assert approved.status_code == 200, approved.text
        record = m.BulkApprovalRecord.model_validate(
            approved.json()["bulk_approval"]
        )
        assert [item.model_dump(mode="json") for item in record.approved_targets] == [
            valid_target
        ]
        assert len(record.excluded_targets) == 1
        assert record.excluded_targets[0].target.model_dump(mode="json") == (
            missing_target
        )
        assert record.excluded_targets[0].reason_code == "BULK_TARGET_NOT_FOUND"
        assert record.excluded_targets[0].requires_individual_review is True

        replayed = client.post(
            (
                f"/api/v1/activities/{fixture['activity_id']}/"
                "assessments:bulk-approve"
            ),
            headers=_mutating(headers, idempotency_key=key),
            json=payload,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.headers["Idempotency-Replayed"] == "true"
        assert replayed.json()["bulk_approval"]["approval_id"] == record.approval_id

        domain_replay = client.post(
            (
                f"/api/v1/activities/{fixture['activity_id']}/"
                "assessments:bulk-approve"
            ),
            headers=_mutating(headers),
            json=payload,
        )
        assert domain_replay.status_code == 200, domain_replay.text
        assert domain_replay.json()["bulk_approval"]["approval_id"] == (
            record.approval_id
        )
        repository: Repository = app.state.runtime.repository
        assert len(
            repository.bulk_approval_requests(tenant_id=TENANT_ID)
        ) == 1
        assert len(
            repository.bulk_approval_records(
                tenant_id=TENANT_ID, request_id=record.request_id
            )
        ) == 1
        history = client.get(
            f"/api/v1/activities/{fixture['activity_id']}/bulk-approvals"
        )
        assert history.status_code == 200, history.text
        history_envelope = dto.BulkApprovalHistoryEnvelope.model_validate(
            history.json()
        )
        assert [item.approval_id for item in history_envelope.items] == [
            record.approval_id
        ]


def test_stage2_controlled_pilot_e2e(tmp_path: Path) -> None:
    """One synthetic HTTP pilot with an explicit 1..38 acceptance manifest."""

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<!doctype html><title>Stage 2 controlled pilot</title>",
        encoding="utf-8",
    )
    app = _app(frontend_dist=str(frontend))
    repository: Repository = app.state.runtime.repository
    export_key = str(uuid4())
    activity_id = ""
    sufficient_id = ""
    insufficient_id = ""
    assessment_id = ""
    final_assessment_version = 0
    expected_question_count = 2
    export_id = ""
    calls_before_export: list[dict[str, Any]] = []

    # Steps 1-27: run the usable experiment in one authenticated browser.
    with TestClient(app) as client:
        headers = _login(client)
        session = client.get("/api/v1/session")
        assert session.status_code == 200, session.text
        assert session.json()["session"]["roles"] == ["TEACHER"]  # 1

        created = client.post(
            "/api/v1/activities",
            headers=_mutating(headers),
            json={
                "title": "Piloto sintético controlado de Etapa 2",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": expected_question_count,
                "target_total_minutes": 8,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": [
                    "text/markdown",
                    "text/plain",
                ],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        assert created.status_code == 201, created.text
        activity_id = created.json()["activity"]["activity_id"]  # 2

        assignment = (
            b"# Consigna\n\nExplique dos decisiones del flujo y sus consecuencias "
            b"locales.\n\nDistinga evidencia observable de inferencias no autorizadas.\n"
        )
        rubric = (
            b"Rubrica sintetica: anclaje localizado, mecanismo explicito y limites "
            b"de inferencia claramente identificados.\n"
        )
        assignment_artifact = _upload(
            client,
            headers,
            start_path=f"/api/v1/activities/{activity_id}/artifacts/uploads",
            complete_path=(
                f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete"
            ),
            role="ASSIGNMENT_PROMPT",
            filename="pilot-assignment.md",
            content=assignment,
        )
        rubric_artifact = _upload(
            client,
            headers,
            start_path=f"/api/v1/activities/{activity_id}/artifacts/uploads",
            complete_path=(
                f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete"
            ),
            role="RUBRIC",
            filename="pilot-rubric.txt",
            content=rubric,
            media_type="text/plain",
        )
        assert assignment_artifact["sha256"] == sha256_bytes(assignment)  # 3
        assert rubric_artifact["sha256"] == sha256_bytes(rubric)  # 4

        generated = client.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(headers),
            json={},
        )
        assert generated.status_code == 202, generated.text
        blueprint_job_id = generated.json()["job_id"]
        blueprint_job = client.get(f"/api/v1/jobs/{blueprint_job_id}")
        assert blueprint_job.json()["job"]["status"] == "SUCCEEDED"  # 5
        latest_blueprint = client.get(
            f"/api/v1/activities/{activity_id}/blueprints/latest"
        )
        approved_blueprint = client.post(
            (
                f"/api/v1/activities/{activity_id}/blueprints/"
                f"{latest_blueprint.json()['version']}:approve"
            ),
            headers=_mutating(
                headers, **{"If-Match": latest_blueprint.headers["etag"]}
            ),
            json={},
        )
        assert approved_blueprint.status_code == 200, approved_blueprint.text
        assert approved_blueprint.json()["blueprint"]["status"] == "APPROVED"  # 6

        batched = client.post(
            f"/api/v1/activities/{activity_id}/submissions:batch",
            headers=_mutating(headers),
            json={"subject_refs": ["pilot_sufficient", "pilot_insufficient"]},
        )
        assert batched.status_code == 201, batched.text
        assert batched.json()["created_count"] == 2  # 7
        submissions_by_subject = {
            item["subject_ref"]: item["submission_id"]
            for item in batched.json()["submissions"]
        }
        assert set(submissions_by_subject) == {
            "pilot_sufficient",
            "pilot_insufficient",
        }  # 8
        sufficient_id = submissions_by_subject["pilot_sufficient"]
        insufficient_id = submissions_by_subject["pilot_insufficient"]

        sufficient_bytes = (
            b"# Entrega suficiente\n\nLa deduplicacion ocurre antes del promedio "
            b"para evitar doble peso.\n\nLos valores extremos se conservan y se "
            b"marcan para revision.\n\nCada fila conserva su identificador de "
            b"origen para trazabilidad.\n\nLa evidencia no permite decidir si un "
            b"extremo es falla o evento real.\n"
        )
        insufficient_bytes = (
            b"Se eligio una segmentacion, pero no se aportan mecanismos, "
            b"trazabilidad ni evidencia suficiente.\n"
        )
        _upload(
            client,
            headers,
            start_path=f"/api/v1/submissions/{sufficient_id}/artifacts/uploads",
            complete_path=(
                f"/api/v1/submissions/{sufficient_id}/artifacts/"
                "{artifact_id}:complete"
            ),
            role="SUBMISSION",
            filename="sufficient.md",
            content=sufficient_bytes,
        )
        _upload(
            client,
            headers,
            start_path=f"/api/v1/submissions/{insufficient_id}/artifacts/uploads",
            complete_path=(
                f"/api/v1/submissions/{insufficient_id}/artifacts/"
                "{artifact_id}:complete"
            ),
            role="SUBMISSION",
            filename="insufficient.txt",
            content=insufficient_bytes,
            media_type="text/plain",
        )
        submission_artifacts = [
            item
            for submission_id in (sufficient_id, insufficient_id)
            for item in repository.artifacts_for(
                activity_id=activity_id,
                tenant_id=TENANT_ID,
                submission_id=submission_id,
            )
        ]
        assert {
            item.media_type
            for item in submission_artifacts
            if item.submission_id in {sufficient_id, insufficient_id}
        } == {"text/markdown", "text/plain"}  # 9

        sufficient_run = client.post(
            f"/api/v1/submissions/{sufficient_id}:run",
            headers=_mutating(headers),
            json={},
        )
        assert sufficient_run.status_code == 202, sufficient_run.text
        sufficient_job_id = sufficient_run.json()["job_id"]
        assert (
            client.get(f"/api/v1/jobs/{sufficient_job_id}").json()["job"]["status"]
            == "SUCCEEDED"
        )  # 11

        original_gateway_stage = app.state.runtime.service._gateway_stage

        async def controlled_insufficient_mapping(
            job: JobRow,
            prompt_id: str,
            request: Any,
            output_model: Any,
            *,
            cache_suffix: str = "",
        ) -> Any:
            if (
                job.aggregate_id == insufficient_id
                and prompt_id == "P06_EVIDENCE_MAP_V1"
            ):
                return m.EvidenceMapPatch(
                    submission_id=insufficient_id,
                    status="INSUFFICIENT_RELEVANT_EVIDENCE",
                    diagnostics=[
                        m.Diagnostic(
                            code="INSUFFICIENT_RELEVANT_EVIDENCE",
                            severity="ERROR",
                            message=(
                                "The authorized synthetic submission does not meet "
                                "the evidence floor."
                            ),
                        )
                    ],
                )
            return await original_gateway_stage(
                job,
                prompt_id,
                request,
                output_model,
                cache_suffix=cache_suffix,
            )

        app.state.runtime.service._gateway_stage = controlled_insufficient_mapping
        insufficient_run = client.post(
            f"/api/v1/submissions/{insufficient_id}:run",
            headers=_mutating(headers),
            json={},
        )
        assert insufficient_run.status_code == 202, insufficient_run.text
        insufficient_job_id = insufficient_run.json()["job_id"]
        assert sufficient_job_id != insufficient_job_id  # 10
        insufficient_job = client.get(f"/api/v1/jobs/{insufficient_job_id}")
        assert insufficient_job.json()["job"]["status"] == "NEEDS_REVIEW"  # 12
        assert insufficient_job.json()["job"]["diagnostics"][0]["code"] == (
            "INSUFFICIENT_RELEVANT_EVIDENCE"
        )
        no_partial_assessment = client.get(
            f"/api/v1/submissions/{insufficient_id}/assessment"
        )
        assert no_partial_assessment.status_code == 404  # 13

        review = client.get(f"/api/v1/submissions/{sufficient_id}/assessment")
        assert review.status_code == 200, review.text
        review_body = review.json()
        assessment_id = review_body["assessment"]["assessment_id"]
        evidence = client.get(f"/api/v1/submissions/{sufficient_id}/evidence")
        assert evidence.status_code == 200, evidence.text
        assert evidence.json()["items"]
        assert all("view_url" not in item for item in evidence.json()["items"])
        assert all(
            question["anchor"]["fragments"]
            for question in review_body["assessment"]["questions"]
        )  # 14

        q_accept, q_mutate = review_body["assessment"]["questions"]
        accepted = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{q_accept['question_id']}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": review.headers["etag"]}),
            json={"action": "ACCEPT"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["action_record"]["status"] == "APPLIED"  # 15

        replacement = json.loads(json.dumps(q_mutate))
        replacement["question_text"] = (
            "Explique el mecanismo observable y el límite inferencial usando "
            "exclusivamente la evidencia anclada."
        )
        edited = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{q_mutate['question_id']}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": accepted.headers["etag"]}),
            json={
                "action": "EDIT",
                "note": "Edición sintética localizada.",
                "replacement": replacement,
            },
        )
        assert edited.status_code == 200, edited.text
        edited_record = m.QuestionReviewActionRecord.model_validate(
            edited.json()["action_record"]
        )
        assert edited_record.status == m.QuestionReviewRecordStatus.APPLIED  # 16
        assert edited_record.after_question == m.SelectedQuestion.model_validate(
            replacement
        )
        assert edited_record.lineage_after is not None
        assert (
            edited_record.lineage_after.submission_hashes
            == edited_record.lineage_before.submission_hashes
        )  # exact lineage preservation

        rejected = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{q_mutate['question_id']}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": edited.headers["etag"]}),
            json={
                "action": "REJECT",
                "reason_code": "PILOT_REVIEW_REJECTION",
            },
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["action_record"]["action"]["action"] == "REJECT"  # 17

        before_regeneration = rejected.json()["bundle"]["assessment"]
        unchanged_before = next(
            item
            for item in before_regeneration["questions"]
            if item["question_id"] == q_accept["question_id"]
        )
        regenerated = client.post(
            (
                f"/api/v1/assessments/{assessment_id}/questions/"
                f"{q_mutate['question_id']}/actions"
            ),
            headers=_mutating(headers, **{"If-Match": rejected.headers["etag"]}),
            json={
                "action": "REGENERATE",
                "reason_code": "PILOT_RESERVE_REPLACEMENT",
            },
        )
        assert regenerated.status_code == 200, regenerated.text
        regeneration = m.QuestionReviewActionRecord.model_validate(
            regenerated.json()["action_record"]
        )
        assert regeneration.status == m.QuestionReviewRecordStatus.APPLIED  # 18
        assert regeneration.after_question is not None
        assert (
            regeneration.after_question.opportunity_id
            != regeneration.before_question.opportunity_id
        )  # 19
        final_bundle = regenerated.json()["bundle"]
        unchanged_after = next(
            item
            for item in final_bundle["assessment"]["questions"]
            if item["question_id"] == q_accept["question_id"]
        )
        assert unchanged_after == unchanged_before  # 20
        assert final_bundle["assessment"]["question_count"] == expected_question_count
        assert len(final_bundle["assessment"]["questions"]) == expected_question_count  # 21
        final_assessment_version = final_bundle["assessment_version"]

        coverage = client.get(f"/api/v1/submissions/{sufficient_id}/coverage")
        assert coverage.status_code == 200, coverage.text
        assert m.CoverageReport.model_validate(coverage.json()["coverage"]).traces  # 22
        guide = client.get(f"/api/v1/assessments/{assessment_id}/guide")
        assert guide.status_code == 200, guide.text
        assert m.EvaluationGuide.model_validate(guide.json()["guide"]).status == (
            m.WorkflowStatus.READY
        )  # 23

        current_question_id = final_bundle["assessment"]["questions"][0]["question_id"]
        feedback = client.post(
            "/api/v1/feedback",
            headers=_mutating(headers),
            json={
                "activity_id": activity_id,
                "target_type": "QUESTION",
                "assessment_id": assessment_id,
                "assessment_version": final_assessment_version,
                "question_id": current_question_id,
                "category": "QUESTION_QUALITY",
                "rating": "HELPFUL",
                "comment": "Evento sintético sin autorización de uso secundario.",
            },
        )
        assert feedback.status_code == 201, feedback.text
        feedback_event = m.FeedbackEvent.model_validate(feedback.json()["feedback"])
        assert not feedback_event.training_use_allowed
        assert not feedback_event.public_dataset_use_allowed  # 24

        final_fixture = {
            "review": final_bundle,
            "assessment_id": assessment_id,
            "etag": regenerated.headers["etag"],
        }
        _verify_all_evidence(client, headers, final_fixture)
        individually_approved = client.post(
            f"/api/v1/assessments/{assessment_id}:approve",
            headers=_mutating(
                headers, **{"If-Match": regenerated.headers["etag"]}
            ),
            json={},
        )
        assert individually_approved.status_code == 200, individually_approved.text
        assert individually_approved.json()["assessment"]["status"] == "APPROVED"  # 25

        bulk = client.post(
            f"/api/v1/activities/{activity_id}/assessments:bulk-approve",
            headers=_mutating(headers),
            json={
                "targets": [
                    {
                        "assessment_id": assessment_id,
                        "assessment_version": final_assessment_version,
                    },
                    {
                        "assessment_id": "ass_pilot_missing",
                        "assessment_version": 1,
                    },
                ],
                "explicit_confirmation": (
                    "CONFIRM_BULK_APPROVAL_OF_ALL_ELIGIBLE_SELECTED_ASSESSMENTS"
                ),
            },
        )
        assert bulk.status_code == 200, bulk.text
        bulk_record = m.BulkApprovalRecord.model_validate(
            bulk.json()["bulk_approval"]
        )
        assert len(bulk_record.approved_targets) == 1
        assert len(bulk_record.excluded_targets) == 1
        assert bulk_record.excluded_targets[0].reason_code == (
            "BULK_TARGET_NOT_FOUND"
        )  # 26

        calls_before_export = repository.model_calls(tenant_id=TENANT_ID)
        exports = client.post(
            f"/api/v1/assessments/{assessment_id}/exports",
            headers=_mutating(headers, idempotency_key=export_key),
            json={"kinds": [kind.value for kind in m.ExportKind]},
        )
        assert exports.status_code == 201, exports.text
        export_envelope = dto.ExportCreateEnvelope.model_validate(exports.json())
        assert len(export_envelope.downloads) == 7
        assert export_envelope.record.model_call_delta == 0
        export_id = export_envelope.record.export_id  # 27
        assert repository.model_calls(tenant_id=TENANT_ID) == calls_before_export

        # A normal reload is already enough to reconstruct state from durable roots.
        reloaded = client.get(f"/api/v1/submissions/{sufficient_id}/assessment")
        assert reloaded.status_code == 200
        assert reloaded.json()["assessment"]["assessment_id"] == assessment_id  # 28

    # Step 29: exiting the context closes the complete browser/client session.
    client.close()
    assert client.is_closed  # 29
    # Steps 30-38: recover from `/` in a fresh client and exercise operations/isolations.
    with TestClient(app) as reopened:
        root = reopened.get("/")
        assert root.status_code == 200
        assert "text/html" in root.headers["content-type"]
        headers = _login(reopened)
        recovered = reopened.get(f"/api/v1/submissions/{sufficient_id}/assessment")
        assert recovered.status_code == 200
        assert recovered.json()["assessment"]["assessment_id"] == assessment_id  # 30

        replayed_export = reopened.post(
            f"/api/v1/assessments/{assessment_id}/exports",
            headers=_mutating(headers, idempotency_key=export_key),
            json={"kinds": [kind.value for kind in m.ExportKind]},
        )
        assert replayed_export.status_code == 201, replayed_export.text
        assert replayed_export.headers["Idempotency-Replayed"] == "true"
        assert replayed_export.json()["record"]["export_id"] == export_id
        export_history = reopened.get(
            f"/api/v1/assessments/{assessment_id}/exports"
        )
        assert export_history.status_code == 200
        assert export_history.json()["items"][0]["export_id"] == export_id  # 28
        assert repository.model_calls(tenant_id=TENANT_ID) == calls_before_export  # 31

        metrics = reopened.get(f"/api/v1/activities/{activity_id}/metrics")
        assert metrics.status_code == 200, metrics.text
        parsed_metrics = m.ExperimentMetrics.model_validate(metrics.json()["metrics"])
        assert parsed_metrics.technical.job_count >= 3
        assert parsed_metrics.quality.assessment_count == 1  # 32

        recording_runner = RecordingJobRunner()
        app.state.runtime.service.job_runner = recording_runner

        def seed_control_job(
            *,
            suffix: str,
            status: str,
            failure_class: str | None,
        ) -> str:
            submission_id = f"sub_pilot_control_{suffix}"
            job_id = f"job_pilot_control_{suffix}"
            domain_status = (
                m.SubmissionProcessingStatus.TECHNICAL_FAILURE
                if status == "FAILED"
                else m.SubmissionProcessingStatus.PARSING
            )
            repository.add(
                SubmissionRow(
                    id=submission_id,
                    tenant_id=TENANT_ID,
                    activity_id=activity_id,
                    subject_ref=f"pilot_control_{suffix}",
                    active_job_id=job_id,
                    state=m.SubmissionProcessingState(
                        submission_id=submission_id,
                        activity_id=activity_id,
                        status=domain_status,
                        current_stage="SUBMISSION_PARSE",
                        progress=0.2,
                        active_job_id=job_id,
                        updated_at=utc_now(),
                    ).model_dump(mode="json"),
                )
            )
            retryable = failure_class in {"TRANSIENT", "PROVIDER"}
            repository.add(
                JobRow(
                    id=job_id,
                    tenant_id=TENANT_ID,
                    kind="SUBMISSION",
                    aggregate_id=submission_id,
                    stage="SUBMISSION_PARSE",
                    status=status,
                    progress=0.2,
                    attempt=1,
                    failure_class=failure_class,
                    diagnostics=(
                        [
                            m.Diagnostic(
                                code="PILOT_CONTROLLED_FAILURE",
                                severity="ERROR",
                                message="Synthetic controlled job failure.",
                                retryable=retryable,
                            ).model_dump(mode="json")
                        ]
                        if status == "FAILED"
                        else []
                    ),
                    started_at=utc_now(),
                    finished_at=utc_now() if status == "FAILED" else None,
                )
            )
            return job_id

        transient_job = seed_control_job(
            suffix="transient", status="FAILED", failure_class="TRANSIENT"
        )
        controlled_failure = reopened.get(
            f"/api/v1/jobs/{transient_job}/control"
        )
        assert controlled_failure.status_code == 200
        assert controlled_failure.json()["failure_class"] == "TRANSIENT"  # 33
        retry = reopened.post(
            f"/api/v1/jobs/{transient_job}:retry",
            headers=_mutating(headers),
            json={
                "reason_code": "PILOT_TRANSIENT_RETRY",
                "target_stage": "SUBMISSION_PARSE",
            },
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["job"]["job_id"] != transient_job
        assert retry.json()["control_records"][0]["action"] == "RETRY"  # 34

        running_job = seed_control_job(
            suffix="running", status="RUNNING", failure_class=None
        )
        cancel = reopened.post(
            f"/api/v1/jobs/{running_job}:cancel",
            headers=_mutating(headers),
            json={"reason_code": "PILOT_COOPERATIVE_CANCEL"},
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["control_state"] == "CANCEL_REQUESTED"  # 35

        resumable_job = seed_control_job(
            suffix="precondition", status="FAILED", failure_class="PRECONDITION"
        )
        resume = reopened.post(
            f"/api/v1/jobs/{resumable_job}:resume",
            headers=_mutating(headers),
            json={
                "reason_code": "PILOT_PRECONDITION_RESOLVED",
                "target_stage": "GUIDE_BUILD",
            },
        )
        assert resume.status_code == 200, resume.text
        assert resume.json()["job"]["job_id"] != resumable_job
        assert resume.json()["control_records"][0]["action"] == "RESUME"  # 36

        current = reopened.get(f"/api/v1/submissions/{sufficient_id}/assessment")
        foreign_question_id = stable_id(
            "question", insufficient_id, "foreign-pilot-question"
        )
        cross_submission = reopened.post(
            "/api/v1/feedback",
            headers=_mutating(headers),
            json={
                "activity_id": activity_id,
                "target_type": "QUESTION",
                "assessment_id": assessment_id,
                "assessment_version": current.json()["assessment_version"],
                "question_id": foreign_question_id,
                "category": "QUESTION_QUALITY",
                "rating": "NEUTRAL",
            },
        )
        assert cross_submission.status_code == 409
        assert cross_submission.json()["code"] == "FEEDBACK_TARGET_INVALID"  # 37

        other, _other_headers = _other_workspace_client(app)
        with other:
            assert other.get(f"/api/v1/activities/{activity_id}").status_code == 404
            assert other.get(
                f"/api/v1/submissions/{sufficient_id}/assessment"
            ).status_code == 404  # 38

    # This is deliberately explicit: every requested pilot step above maps to
    # either a direct assertion in this test or a focused companion test.
    evidence_manifest = {
        1: "authorized session",
        2: "new activity",
        3: "assignment artifact",
        4: "optional rubric artifact",
        5: "blueprint generated",
        6: "blueprint approved",
        7: "two submissions batched",
        8: "distinct subject refs",
        9: "Markdown and plain-text submissions",
        10: "independent submission jobs",
        11: "sufficient submission succeeded",
        12: "controlled insufficient submission",
        13: "no partial assessment on insufficiency",
        14: "evidence-first anchors",
        15: "ACCEPT action",
        16: "EDIT action",
        17: "REJECT action",
        18: "REGENERATE action",
        19: "reserve opportunity replacement",
        20: "unrelated question unchanged",
        21: "exactly N preserved",
        22: "coverage report",
        23: "READY EvaluationGuide",
        24: "governed feedback",
        25: "individual approval",
        26: "bulk approval with exclusion",
        27: "seven export kinds",
        28: "reload, history, and idempotent replay",
        29: "first TestClient fully closed",
        30: "fresh client recovered from root",
        31: "zero model-call delta during export/replay",
        32: "queryable experiment metrics",
        33: "controlled durable failure",
        34: "bounded retry creates a distinct job",
        35: "cooperative cancellation requested",
        36: "stage resume creates a distinct job",
        37: "cross-submission target rejected",
        38: "cross-tenant reads hidden",
    }
    assert list(evidence_manifest) == list(range(1, 39))
