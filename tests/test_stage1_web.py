from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from comprehension_verification.canonical import sha256_bytes, stable_id
from comprehension_verification.contracts import models as m
from comprehension_verification.web.app import create_app
from comprehension_verification.web.jobs import RecordingJobRunner
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import (
    ArtifactRow,
    IdempotencyRow,
    JobRow,
    Repository,
)
from comprehension_verification.web.settings import Settings
from comprehension_verification.web.workflows import Stage1Service


def _app():
    return create_app(
        Settings(
            environment="test",
            database_url="sqlite+pysqlite://",
            session_secret="stage1-test-secret-with-sufficient-length",
            local_invited_emails="teacher@example.test,assistant@example.test",
            model_mode="mock",
        ),
        inline_wait_for_completion=True,
    )


def _login(client: TestClient, email: str = "teacher@example.test") -> dict[str, str]:
    response = client.post("/api/v1/session/login", json={"email": email})
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("cva_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


def _mutating(headers: dict[str, str], **extra: str) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4()), **extra}


def _upload(
    client: TestClient,
    headers: dict[str, str],
    start_path: str,
    complete_path: str,
    *,
    role: str,
    filename: str,
    media_type: str,
    content: bytes,
) -> dict:
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


def test_private_routes_invitation_and_csrf_are_enforced() -> None:
    with TestClient(_app()) as client:
        assert client.get("/api/v1/activities").status_code == 401
        assert (
            client.post(
                "/api/v1/session/login", json={"email": "not-invited@example.test"}
            ).status_code
            == 403
        )
        _login(client)
        assert client.get("/api/v1/session").status_code == 200
        rejected = client.post(
            "/api/v1/activities",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "title": "Sin token CSRF",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/markdown"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        assert rejected.status_code == 403


def test_assistant_cannot_mutate_or_launch_activity_inputs() -> None:
    with TestClient(_app()) as client:
        assistant = _login(client, "assistant@example.test")
        rejected = client.post(
            "/api/v1/activities",
            headers=_mutating(assistant),
            json={
                "title": "Actividad no autorizada",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/markdown"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["code"] == "ROLE_FORBIDDEN"


def test_mutations_require_atomic_idempotency_and_never_persist_signed_urls() -> None:
    app = _app()
    payload = {
        "title": "Actividad idempotente",
        "output_language": "es-CL",
        "assessment_modality": "WRITTEN",
        "question_count": 1,
        "target_total_minutes": 3,
        "allowed_response_formats": ["OPEN_SHORT"],
        "allowed_artifact_media_types": ["text/markdown"],
        "structured_justification_mode": "NOT_REQUIRED",
    }
    with TestClient(app) as client:
        csrf = _login(client)
        missing = client.post("/api/v1/activities", headers=csrf, json=payload)
        assert missing.status_code == 428
        assert missing.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

        key = str(uuid4())
        request_headers = {**csrf, "Idempotency-Key": key}
        first = client.post(
            "/api/v1/activities", headers=request_headers, json=payload
        )
        assert first.status_code == 201, first.text
        assert first.headers["Idempotency-Replayed"] == "false"
        replay = client.post(
            "/api/v1/activities", headers=request_headers, json=payload
        )
        assert replay.status_code == 201, replay.text
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert replay.json() == first.json()
        assert len(client.get("/api/v1/activities").json()["items"]) == 1

        replay_without_csrf = client.post(
            "/api/v1/activities",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        assert replay_without_csrf.status_code == 403

        conflict = client.post(
            "/api/v1/activities",
            headers=request_headers,
            json={**payload, "title": "Otro cuerpo"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

        activity_id = first.json()["activity"]["activity_id"]
        upload_key = str(uuid4())
        upload_headers = {**csrf, "Idempotency-Key": upload_key}
        upload_body = {
            "role": "ASSIGNMENT_PROMPT",
            "filename": "assignment.md",
            "media_type": "text/markdown",
            "byte_size": 16,
        }
        uploaded = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            headers=upload_headers,
            json=upload_body,
        )
        replayed_upload = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            headers=upload_headers,
            json=upload_body,
        )
        assert uploaded.status_code == replayed_upload.status_code == 201
        assert (
            uploaded.json()["upload"]["artifact_id"]
            == replayed_upload.json()["upload"]["artifact_id"]
        )
        persisted = app.state.runtime.repository.get(
            IdempotencyRow,
            stable_id("idem", "tnt_experimental", upload_key),
        )
        assert isinstance(persisted, IdempotencyRow)
        serialized = json.dumps(persisted.response, sort_keys=True)
        assert "upload_url" not in serialized
        assert "expires_at" not in serialized

        original = b"sealed-original!"
        sent = client.put(
            uploaded.json()["upload"]["upload_url"],
            headers=uploaded.json()["upload"]["upload_headers"],
            content=original,
        )
        assert sent.status_code == 204, sent.text
        artifact_id = uploaded.json()["upload"]["artifact_id"]
        completed = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/{artifact_id}:complete",
            headers=_mutating(csrf),
            json={
                "sha256": sha256_bytes(original),
                "byte_size": len(original),
                "media_type": "text/markdown",
            },
        )
        assert completed.status_code == 200, completed.text

        replay_after_seal = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            headers=upload_headers,
            json=upload_body,
        )
        assert replay_after_seal.status_code == 201
        replacement = b"pending-replaced"
        replaced = client.put(
            replay_after_seal.json()["upload"]["upload_url"],
            headers=replay_after_seal.json()["upload"]["upload_headers"],
            content=replacement,
        )
        assert replaced.status_code == 204, replaced.text

        artifact = app.state.runtime.repository.get(ArtifactRow, artifact_id)
        assert isinstance(artifact, ArtifactRow)
        assert "/sealed/" in artifact.object_key
        store = app.state.runtime.object_store
        assert store.get_bytes(artifact.object_key, max_bytes=16) == original
        pending_key = (
            f"raw/{artifact.tenant_id}/{artifact.activity_id}/{artifact.id}/upload"
        )
        assert store.get_bytes(pending_key, max_bytes=16) == replacement

        verified_again = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/{artifact_id}:complete",
            headers=_mutating(csrf),
            json={
                "sha256": sha256_bytes(original),
                "byte_size": len(original),
                "media_type": "text/markdown",
            },
        )
        assert verified_again.status_code == 200, verified_again.text


def test_activity_configuration_uses_etag_and_locks_after_pipeline_start() -> None:
    with TestClient(_app()) as client:
        csrf = _login(client)
        created = client.post(
            "/api/v1/activities",
            headers=_mutating(csrf),
            json={
                "title": "Borrador editable",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/markdown"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        activity_id = created.json()["activity"]["activity_id"]
        detail = client.get(f"/api/v1/activities/{activity_id}")
        original_etag = detail.headers["etag"]
        edited = client.patch(
            f"/api/v1/activities/{activity_id}",
            headers=_mutating(csrf, **{"If-Match": original_etag}),
            json={"title": "Borrador revisado", "target_total_minutes": 4},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["activity"]["title"] == "Borrador revisado"
        assert edited.headers["etag"] != original_etag

        stale = client.patch(
            f"/api/v1/activities/{activity_id}",
            headers=_mutating(csrf, **{"If-Match": original_etag}),
            json={"title": "Edición obsoleta"},
        )
        assert stale.status_code == 412

        _upload(
            client,
            csrf,
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete",
            role="ASSIGNMENT_PROMPT",
            filename="assignment.md",
            media_type="text/markdown",
            content=b"# Consigna\n\nExplique un mecanismo localizado.\n",
        )
        generated = client.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(csrf),
            json={},
        )
        assert generated.status_code == 202
        locked = client.patch(
            f"/api/v1/activities/{activity_id}",
            headers=_mutating(
                csrf, **{"If-Match": edited.headers["etag"]}
            ),
            json={"title": "No debe cambiar"},
        )
        assert locked.status_code == 409
        assert locked.json()["code"] == "ACTIVITY_CONFIG_LOCKED"


def test_blocking_ambiguity_requires_durable_teacher_decision_before_blueprint() -> None:
    app = _app()
    original_gateway_stage = app.state.runtime.service._gateway_stage

    async def ambiguity_gateway_stage(
        job,
        prompt_id,
        request,
        output_model,
        *,
        cache_suffix="",
    ):
        if prompt_id == "P03_AMBIGUITY_TRIAGE_V1":
            return m.AmbiguityReport(
                activity_id=request.activity_spec.activity_id,
                blocked=True,
                issues=[
                    m.AmbiguityIssue(
                        issue_id="issue_scope",
                        issue_code="ASSIGNMENT_AMBIGUOUS",
                        severity=m.Severity.ERROR,
                        evidence_ids=[],
                        explanation="El alcance debe ser confirmado por una persona docente.",
                        options=[
                            m.DecisionOption(
                                option_id="option_keep",
                                label="Mantener alcance",
                                consequence="Conserva el alcance de la consigna.",
                            ),
                            m.DecisionOption(
                                option_id="option_narrow",
                                label="Acotar alcance",
                                consequence="Acota la verificación a evidencia explícita.",
                            ),
                        ],
                        recommended_option_id="option_keep",
                        blocking=True,
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

    app.state.runtime.service._gateway_stage = ambiguity_gateway_stage
    with TestClient(app) as client:
        csrf = _login(client)
        created = client.post(
            "/api/v1/activities",
            headers=_mutating(csrf),
            json={
                "title": "Actividad con ambigüedad",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/markdown"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        activity_id = created.json()["activity"]["activity_id"]
        _upload(
            client,
            csrf,
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete",
            role="ASSIGNMENT_PROMPT",
            filename="assignment.md",
            media_type="text/markdown",
            content=b"# Consigna\n\nExplique una decision localizada.\n",
        )
        first = client.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(csrf),
            json={},
        )
        first_job = client.get(
            f"/api/v1/jobs/{first.json()['job_id']}"
        ).json()["job"]
        assert first_job["status"] == "NEEDS_REVIEW"
        ambiguity = client.get(
            f"/api/v1/activities/{activity_id}/ambiguity"
        )
        assert ambiguity.status_code == 200
        assert ambiguity.json()["report"]["issues"][0]["issue_id"] == "issue_scope"
        assert ambiguity.json()["decisions"] == []

        decision = client.post(
            f"/api/v1/activities/{activity_id}/decisions",
            headers=_mutating(csrf),
            json={
                "issue_id": "issue_scope",
                "selected_option_id": "option_keep",
                "note": "Confirmado para este recorrido experimental.",
            },
        )
        assert decision.status_code == 201, decision.text
        decision_id = decision.json()["decision"]["decision_id"]
        resumed = client.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(csrf),
            json={},
        )
        resumed_job = client.get(
            f"/api/v1/jobs/{resumed.json()['job_id']}"
        ).json()["job"]
        assert resumed_job["status"] == "SUCCEEDED", resumed_job
        blueprint = client.get(
            f"/api/v1/activities/{activity_id}/blueprints/latest"
        ).json()["blueprint"]
        assert blueprint["decision_ids"] == [decision_id]


def test_stage1_single_submission_mock_e2e_survives_new_browser_session() -> None:
    app = _app()
    with TestClient(app) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/activities",
            headers=_mutating(headers),
            json={
                "title": "Decisiones de limpieza de sensores",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 2,
                "target_total_minutes": 8,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/markdown"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        assert created.status_code == 201, created.text
        activity_id = created.json()["activity"]["activity_id"]

        assignment = (
            b"# Consigna\n\nExplique dos decisiones del flujo y sus consecuencias locales.\n\n"
            b"Identifique tambien un limite que la evidencia no permite resolver.\n"
        )
        rubric = (
            b"# Rubrica\n\nSe valora explicar mecanismos con evidencia localizada.\n\n"
            b"Se valora distinguir una consecuencia de una inferencia no autorizada.\n"
        )
        _upload(
            client,
            headers,
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete",
            role="ASSIGNMENT_PROMPT",
            filename="assignment.md",
            media_type="text/markdown",
            content=assignment,
        )
        _upload(
            client,
            headers,
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete",
            role="RUBRIC",
            filename="rubric.md",
            media_type="text/markdown",
            content=rubric,
        )

        generated = client.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(headers),
            json={},
        )
        assert generated.status_code == 202, generated.text
        activity_job = generated.json()["job_id"]
        activity_status = client.get(f"/api/v1/jobs/{activity_job}").json()["job"]
        assert activity_status["status"] == "SUCCEEDED", activity_status
        activity_ledger = client.get(
            f"/api/v1/jobs/{activity_job}/model-calls"
        ).json()["items"]
        assert {item["prompt_id"] for item in activity_ledger} == {
            "P01_ACTIVITY_SPEC_V1",
            "P02_RUBRIC_NORMALIZE_V1",
            "P03_AMBIGUITY_TRIAGE_V1",
            "P04_BLUEPRINT_BUILD_V1",
            "P05_BLUEPRINT_REVIEW_V1",
        }

        latest = client.get(f"/api/v1/activities/{activity_id}/blueprints/latest")
        assert latest.status_code == 200, latest.text
        original = latest.json()["blueprint"]
        assert original["assessment_constraints"]["question_count"] == 2
        assert len(
            [
                opportunity
                for dimension in original["dimensions"]
                for variant in dimension["evidence_variants"]
                for opportunity in variant["question_opportunities"]
            ]
        ) >= 2

        widened = json.loads(json.dumps(original))
        widened["dimensions"][0]["evidence_variants"][0]["question_opportunities"][0][
            "target_minutes"
        ] += 1
        rejected_edit = client.patch(
            f"/api/v1/activities/{activity_id}/blueprints/1",
            headers=_mutating(headers, **{"If-Match": latest.headers["etag"]}),
            json=widened,
        )
        assert rejected_edit.status_code == 422
        assert rejected_edit.json()["code"] == "BLUEPRINT_STRUCTURE_IMMUTABLE"

        original["dimensions"][0]["name"] = "Mecanismos y límites revisados"
        edited = client.patch(
            f"/api/v1/activities/{activity_id}/blueprints/1",
            headers=_mutating(headers, **{"If-Match": latest.headers["etag"]}),
            json=original,
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["blueprint"]["blueprint_version"] == 2
        approved = client.post(
            f"/api/v1/activities/{activity_id}/blueprints/2:approve",
            headers=_mutating(headers, **{"If-Match": edited.headers["etag"]}),
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["blueprint"]["status"] == "APPROVED"
        assert approved.json()["blueprint"]["blueprint_version"] == 3

        submission_response = client.post(
            f"/api/v1/activities/{activity_id}/submissions",
            headers=_mutating(headers),
            json={"subject_ref": "synthetic-subject-001"},
        )
        assert submission_response.status_code == 201, submission_response.text
        submission_id = submission_response.json()["submission"]["submission_id"]
        deliverable = (
            b"# Flujo\n\nLa deduplicacion ocurre antes del promedio para evitar doble peso.\n\n"
            b"Los valores extremos se conservan y se marcan para revision.\n\n"
            b"Cada fila mantiene el identificador de origen para trazabilidad.\n\n"
            b"La evidencia no permite decidir si un extremo es falla o evento real.\n"
        )
        artifact = _upload(
            client,
            headers,
            f"/api/v1/submissions/{submission_id}/artifacts/uploads",
            f"/api/v1/submissions/{submission_id}/artifacts/{{artifact_id}}:complete",
            role="SUBMISSION",
            filename="submission.md",
            media_type="text/markdown",
            content=deliverable,
        )
        assert artifact["sha256"] == sha256_bytes(deliverable)

        started = client.post(
            f"/api/v1/submissions/{submission_id}:run",
            headers=_mutating(headers),
            json={},
        )
        assert started.status_code == 202, started.text
        submission_job = started.json()["job_id"]
        job = client.get(f"/api/v1/jobs/{submission_job}").json()["job"]
        assert job["status"] == "SUCCEEDED", job
        assert job["progress"] == 1.0

        # Preserve the short-lived application session across a browser close.
        session_cookie = client.cookies.get("cva_session")
        csrf_cookie = client.cookies.get("cva_csrf")
        assert session_cookie and csrf_cookie

    with TestClient(app) as reopened:
        reopened.cookies.set("cva_session", session_cookie)
        reopened.cookies.set("cva_csrf", csrf_cookie)
        headers = {"X-CSRF-Token": csrf_cookie}
        submission = reopened.get(f"/api/v1/submissions/{submission_id}")
        assert submission.status_code == 200, submission.text
        state = submission.json()["submission"]
        assert state["status"] == "NEEDS_REVIEW"
        assessment_id = state["assessment_id"]

        review = reopened.get(f"/api/v1/submissions/{submission_id}/assessment")
        assert review.status_code == 200, review.text
        review_body = review.json()
        assessment = review_body["assessment"]
        assert assessment["question_count"] == 2
        assert len(assessment["questions"]) == 2
        assert review_body["guide"]["status"] == "READY"
        assert all(question["anchor"]["fragments"] for question in assessment["questions"])
        assert all(question["dimension_id"] for question in assessment["questions"])
        assert all(question["cognitive_operation"] for question in assessment["questions"])

        evidence = reopened.get(f"/api/v1/submissions/{submission_id}/evidence")
        assert evidence.status_code == 200, evidence.text
        evidence_items = evidence.json()["items"]
        assert evidence_items
        exact_source = reopened.get(evidence_items[0]["view_url"])
        assert exact_source.status_code == 200
        assert exact_source.content == deliverable

        ledger_before = reopened.get(
            f"/api/v1/jobs/{submission_job}/model-calls"
        ).json()["items"]
        assert {item["prompt_id"] for item in ledger_before} >= {
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P08_QUESTION_REVIEW_V1",
            "P09_GUIDE_BUILD_V1",
        }
        required_ledger_fields = {
            "provider",
            "model_snapshot",
            "model",
            "reasoning_effort",
            "temperature",
            "reason_codes",
        }
        assert required_ledger_fields <= set(ledger_before[0]["route"])
        assert {
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "estimated_cost_usd",
            "attempt",
            "result",
        } <= set(ledger_before[0])

        approved_assessment = reopened.post(
            f"/api/v1/assessments/{assessment_id}:approve",
            headers=_mutating(headers, **{"If-Match": review_body["etag"]}),
            json={},
        )
        assert approved_assessment.status_code == 200, approved_assessment.text
        assert approved_assessment.json()["assessment"]["status"] == "APPROVED"

        expected_types = {
            "ASSESSMENT_PDF": "application/pdf",
            "GUIDE_PDF": "application/pdf",
            "CANONICAL_JSON": "application/json",
        }
        for kind, expected_type in expected_types.items():
            export_headers = _mutating(headers)
            exported = reopened.post(
                f"/api/v1/assessments/{assessment_id}/exports",
                headers=export_headers,
                json={"kind": kind},
            )
            assert exported.status_code == 201, exported.text
            replayed_export = reopened.post(
                f"/api/v1/assessments/{assessment_id}/exports",
                headers=export_headers,
                json={"kind": kind},
            )
            assert replayed_export.status_code == 201, replayed_export.text
            assert replayed_export.headers["Idempotency-Replayed"] == "true"
            item = exported.json()["export"]
            assert item["status"] == "READY"
            assert replayed_export.json()["export"]["export_id"] == item["export_id"]
            downloaded = reopened.get(item["download_url"])
            assert downloaded.status_code == 200
            assert downloaded.headers["content-type"].startswith(expected_type)
            if kind == "CANONICAL_JSON":
                canonical = json.loads(downloaded.content)
                assert canonical["assessment"]["assessment_id"] == assessment_id
                assert canonical["evaluation_guide"]["assessment_id"] == assessment_id
            else:
                assert downloaded.content.startswith(b"%PDF-")

        ledger_after = reopened.get(
            f"/api/v1/jobs/{submission_job}/model-calls"
        ).json()["items"]
        assert ledger_after == ledger_before


def test_queued_job_survives_browser_close_and_a_new_worker_processes_it(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'durable-worker.db'}"
    settings = Settings(
        environment="test",
        database_url=database_url,
        session_secret="durable-worker-test-secret-with-32-bytes",
        local_invited_emails="teacher@example.test",
        model_mode="mock",
    )
    store = MemoryObjectStore(secret=settings.session_secret)
    api_repository = Repository(database_url)
    dispatched: list[str] = []

    def assert_queued_before_dispatch(job_id: str) -> None:
        row = api_repository.get(JobRow, job_id)
        assert isinstance(row, JobRow)
        assert row.status == "QUEUED"
        dispatched.append(job_id)

    api_runner = RecordingJobRunner(assert_persisted=assert_queued_before_dispatch)
    app = create_app(
        settings,
        repository=api_repository,
        object_store=store,
        job_runner=api_runner,
    )

    with TestClient(app) as browser:
        headers = _login(browser)
        created = browser.post(
            "/api/v1/activities",
            headers=_mutating(headers),
            json={
                "title": "Persistencia entre API y worker",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/markdown"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        assert created.status_code == 201, created.text
        activity_id = created.json()["activity"]["activity_id"]
        _upload(
            browser,
            headers,
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            f"/api/v1/activities/{activity_id}/artifacts/{{artifact_id}}:complete",
            role="ASSIGNMENT_PROMPT",
            filename="assignment.md",
            media_type="text/markdown",
            content=b"# Consigna\n\nExplique una decision y su consecuencia local.\n",
        )

        generated = browser.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(headers),
            json={},
        )
        assert generated.status_code == 202, generated.text
        job_id = generated.json()["job_id"]
        assert generated.json()["operation"]["status"] == "QUEUED"
        assert dispatched == [job_id]
        assert api_runner.dispatched == [job_id]
        assert api_repository.job_status(job_id, settings.local_workspace_id).status == "QUEUED"

    # A Cloud Run Job starts in another process after the API/browser is gone.
    worker_repository = Repository(database_url)
    claimed = worker_repository.claim_next_job()
    assert claimed is not None
    assert claimed.id == job_id
    assert worker_repository.job_status(job_id, settings.local_workspace_id).status == "RUNNING"
    worker_service = Stage1Service(
        settings=settings,
        repository=worker_repository,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    asyncio.run(worker_service.process_job(claimed.id))
    assert worker_repository.job_status(job_id, settings.local_workspace_id).status == "SUCCEEDED"

    # A different API process and a fresh browser session observe persisted output.
    query_repository = Repository(database_url)
    query_app = create_app(
        settings,
        repository=query_repository,
        object_store=store,
        job_runner=RecordingJobRunner(),
    )
    with TestClient(query_app) as new_browser:
        _login(new_browser)
        observed = new_browser.get(f"/api/v1/jobs/{job_id}")
        assert observed.status_code == 200, observed.text
        assert observed.json()["job"]["status"] == "SUCCEEDED"
        assert observed.json()["job"]["progress"] == 1.0
        blueprint = new_browser.get(
            f"/api/v1/activities/{activity_id}/blueprints/latest"
        )
        assert blueprint.status_code == 200, blueprint.text
        assert blueprint.json()["blueprint"]["activity_id"] == activity_id
