from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from comprehension_verification.canonical import sha256_bytes, stable_id
from comprehension_verification.contracts import models as m
from comprehension_verification.web import dto
from comprehension_verification.web.app import create_app
from comprehension_verification.web.auth import Actor
from comprehension_verification.web.jobs import RecordingJobRunner
from comprehension_verification.web.object_store import MemoryObjectStore
from comprehension_verification.web.repository import (
    ArtifactRow,
    BlueprintRow,
    EvidenceRow,
    IdempotencyRow,
    JobRow,
    NotFound,
    PolicyDecisionRow,
    Repository,
    WorkspaceRoleRow,
)
from comprehension_verification.web.settings import Settings
from comprehension_verification.web.workflows import Stage1Service


def _app(*, max_job_cost_usd: float = 0.50):
    database_url = os.environ.get("CVA_TEST_DATABASE_URL", "sqlite+pysqlite://")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    settings = Settings(
        environment="test",
        database_url=database_url,
        session_secret="stage1-test-secret-with-sufficient-length",
        local_invited_emails="teacher@example.test,reviewer@example.test,assistant@example.test",
        model_mode="mock",
        max_job_cost_usd=max_job_cost_usd,
    )
    repository = (
        Repository(database_url, create_schema=False)
        if "CVA_TEST_DATABASE_URL" in os.environ
        else None
    )
    return create_app(
        settings,
        repository=repository,
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


def test_activity_landing_is_scoped_to_the_authenticated_workspace() -> None:
    app = _app()
    with TestClient(app) as client:
        teacher = _login(client)
        created = client.post(
            "/api/v1/activities",
            headers=_mutating(teacher),
            json={
                "title": "Visible solo en workspace experimental",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT"],
                "allowed_artifact_media_types": ["text/plain"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        assert created.status_code == 201

        other_user = "usr_other_workspace"
        other_workspace = "tnt_other_workspace"
        app.state.runtime.repository.seed_workspace(
            other_workspace,
            [(other_user, "other-teacher@example.test", "TEACHER")],
        )
        now = datetime.now(UTC)
        other_csrf = "other-workspace-csrf-token"
        other_session = jwt.encode(
            {
                "iss": "cva-web",
                "aud": "cva-web",
                "sub": other_user,
                "workspace_id": other_workspace,
                "csrf": other_csrf,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            app.state.runtime.settings.session_secret,
            algorithm="HS256",
        )

        with TestClient(app) as other:
            other.cookies.set("cva_session", other_session)
            other.cookies.set("cva_csrf", other_csrf)
            isolated = other.get("/api/v1/activities")
            assert isolated.status_code == 200
            assert isolated.json()["items"] == []


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
        activity_id = first.json()["activity"]["activity_id"]
        listed_ids = {
            item["activity_id"]
            for item in client.get("/api/v1/activities").json()["items"]
        }
        assert activity_id in listed_ids

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
        pending_key = persisted.response["upload_object_key"]
        assert pending_key.startswith(
            f"raw/tnt_experimental/{activity_id}/"
            f"{uploaded.json()['upload']['artifact_id']}/"
        )

        with TestClient(app) as assistant_client:
            assistant_csrf = _login(
                assistant_client, "assistant@example.test"
            )
            cross_principal = assistant_client.post(
                f"/api/v1/activities/{activity_id}/artifacts/uploads",
                headers={**assistant_csrf, "Idempotency-Key": upload_key},
                json=upload_body,
            )
            assert cross_principal.status_code == 409
            assert cross_principal.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
            assert "upload_url" not in cross_principal.text

        teacher_id = stable_id("usr", "teacher@example.test")
        with app.state.runtime.repository.session() as session:
            membership = session.get(
                WorkspaceRoleRow, (teacher_id, "tnt_experimental")
            )
            assert membership is not None
            membership.role = "ASSISTANT"
            membership.can_approve_assessments = False
        downgraded = client.post(
            f"/api/v1/activities/{activity_id}/artifacts/uploads",
            headers=upload_headers,
            json=upload_body,
        )
        assert downgraded.status_code == 409
        assert downgraded.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
        assert "upload_url" not in downgraded.text
        with app.state.runtime.repository.session() as session:
            membership = session.get(
                WorkspaceRoleRow, (teacher_id, "tnt_experimental")
            )
            assert membership is not None
            membership.role = "TEACHER"
            membership.can_approve_assessments = True

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
        initial_estimate_response = client.get(
            f"/api/v1/activities/{activity_id}/estimate"
        )
        assert initial_estimate_response.status_code == 200
        initial_estimate = initial_estimate_response.json()["estimate"]
        assert initial_estimate["phase"] == "ACTIVITY_BLUEPRINT"
        assert initial_estimate["estimated_model_calls"] == 3
        assert initial_estimate["within_limit"] is True
        edited = client.patch(
            f"/api/v1/activities/{activity_id}",
            headers=_mutating(csrf, **{"If-Match": original_etag}),
            json={"title": "Borrador revisado", "target_total_minutes": 4},
        )
        assert edited.status_code == 200, edited.text
        dto.ActivityEnvelope.model_validate(edited.json())
        assert edited.json()["activity"]["title"] == "Borrador revisado"
        assert edited.headers["etag"] != original_etag
        revised_estimate = client.get(
            f"/api/v1/activities/{activity_id}/estimate"
        ).json()["estimate"]
        assert revised_estimate["input_fingerprint"] != initial_estimate["input_fingerprint"]

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


def test_activity_estimate_fails_closed_before_launch_when_limit_is_exceeded() -> None:
    with TestClient(_app(max_job_cost_usd=0.01)) as client:
        csrf = _login(client)
        created = client.post(
            "/api/v1/activities",
            headers=_mutating(csrf),
            json={
                "title": "Actividad sobre límite",
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
            content=b"# Consigna\n\nExplique un mecanismo localizado.\n",
        )

        estimate = client.get(
            f"/api/v1/activities/{activity_id}/estimate"
        ).json()["estimate"]
        assert estimate["upper_bound_cost_usd"] > estimate["authorized_limit_usd"]
        assert estimate["within_limit"] is False
        blocked = client.post(
            f"/api/v1/activities/{activity_id}/blueprints:generate",
            headers=_mutating(csrf),
            json={},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "COST_LIMIT_EXCEEDED"


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
        assert decision.json()["decision"]["selected_option"] == {
            "option_id": "option_keep",
            "label": "Mantener alcance",
            "consequence": "Conserva el alcance de la consigna.",
        }
        decision_id = decision.json()["decision"]["decision_id"]
        # Simulate a pre-1.1.7 JSON row: blueprint generation must rehydrate
        # the selected option from the tenant-scoped ambiguity report without
        # rewriting the historical record.
        with app.state.runtime.repository.session() as session:
            historical = session.get(PolicyDecisionRow, decision_id)
            assert historical is not None
            historical_data = dict(historical.data)
            historical_data.pop("selected_option")
            historical.data = historical_data
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
        persisted = app.state.runtime.repository.get(
            PolicyDecisionRow, decision_id
        )
        assert "selected_option" not in persisted.data


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
        }

        latest = client.get(f"/api/v1/activities/{activity_id}/blueprints/latest")
        assert latest.status_code == 200, latest.text
        dto.BlueprintEnvelope.model_validate(latest.json())
        dto.BlueprintEnvelope.model_validate(
            client.get(
                f"/api/v1/activities/{activity_id}/blueprints/1"
            ).json()
        )
        original = latest.json()["blueprint"]
        assert latest.json()["preflight"]["catalog_plan_feasible"] is True
        assert latest.json()["review"] is None
        persisted_blueprint = app.state.runtime.repository.latest_blueprint(
            activity_id, "tnt_experimental"
        )
        with app.state.runtime.repository.session() as session:
            historical = session.get(BlueprintRow, persisted_blueprint.row_id)
            assert historical is not None
            historical.preflight = None
            historical.review = m.BlueprintReview(
                activity_id=activity_id,
                blueprint_id=original["blueprint_id"],
                blueprint_version=original["blueprint_version"],
                status="TECHNICAL_FAILURE",
            ).model_dump(mode="json")
        legacy_projection = client.get(
            f"/api/v1/activities/{activity_id}/blueprints/latest"
        )
        assert legacy_projection.status_code == 200, legacy_projection.text
        assert legacy_projection.json()["review"]["status"] == (
            "TECHNICAL_FAILURE"
        )
        assert legacy_projection.json()["preflight"][
            "catalog_plan_feasible"
        ] is True
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
        assert edited.status_code == 202, edited.text
        queued_edit = dto.JobEnvelope.model_validate(edited.json()).job
        assert queued_edit.status == "SUCCEEDED"
        assert queued_edit.stage == "BLUEPRINT_PREFLIGHT"
        edit_ledger = client.get(
            f"/api/v1/jobs/{queued_edit.job_id}/model-calls"
        ).json()["items"]
        assert edit_ledger == []
        reviewed_edit = client.get(
            f"/api/v1/activities/{activity_id}/blueprints/latest"
        )
        assert reviewed_edit.status_code == 200, reviewed_edit.text
        dto.BlueprintEnvelope.model_validate(reviewed_edit.json())
        assert reviewed_edit.json()["blueprint"]["blueprint_version"] == 2
        approved = client.post(
            f"/api/v1/activities/{activity_id}/blueprints/2:approve",
            headers=_mutating(
                headers, **{"If-Match": reviewed_edit.headers["etag"]}
            ),
            json={},
        )
        assert approved.status_code == 200, approved.text
        dto.BlueprintEnvelope.model_validate(approved.json())
        assert approved.json()["blueprint"]["status"] == "APPROVED"
        assert approved.json()["blueprint"]["blueprint_version"] == 3
        activity_metrics = m.ExperimentMetrics.model_validate(
            client.get(
                f"/api/v1/activities/{activity_id}/metrics"
            ).json()["metrics"]
        )
        assert "BLUEPRINT_PREFLIGHT" in {
            item.stage for item in activity_metrics.by_stage
        }
        assert not any(
            "p05_blueprint_review" in item.route_id
            for item in activity_metrics.by_model
        )
        assert app.state.runtime.repository.has_audit_event(
            tenant_id="tnt_experimental",
            event_type="blueprint.approved",
            aggregate_id=approved.json()["blueprint"]["blueprint_id"],
            payload_contains={"blueprint_version": 3},
        )

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
        assert review_body["reviews"] == []
        assert all(question["anchor"]["fragments"] for question in assessment["questions"])
        assert all(question["dimension_id"] for question in assessment["questions"])
        assert all(question["cognitive_operation"] for question in assessment["questions"])

        evidence = reopened.get(f"/api/v1/submissions/{submission_id}/evidence")
        assert evidence.status_code == 200, evidence.text
        evidence_items = evidence.json()["items"]
        assert evidence_items
        assert all("view_url" not in item for item in evidence_items)

        first_question = assessment["questions"][0]
        verify_path = f"/api/v1/assessments/{assessment_id}/evidence:verify"
        valid_verification = {
            "assessment_version": review_body["assessment_version"],
            "assessment_etag": review_body["etag"],
            "question_id": first_question["question_id"],
            "fragment_index": 0,
        }
        stale_version = reopened.post(
            verify_path,
            headers=_mutating(headers),
            json={
                **valid_verification,
                "assessment_version": review_body["assessment_version"] + 1,
            },
        )
        assert stale_version.status_code == 412
        assert stale_version.json()["code"] == "ETAG_MISMATCH"
        stale_etag = reopened.post(
            verify_path,
            headers=_mutating(headers),
            json={**valid_verification, "assessment_etag": '"stale-etag"'},
        )
        assert stale_etag.status_code == 412
        missing_question = reopened.post(
            verify_path,
            headers=_mutating(headers),
            json={**valid_verification, "question_id": "question_missing"},
        )
        assert missing_question.status_code == 404
        missing_fragment = reopened.post(
            verify_path,
            headers=_mutating(headers),
            json={**valid_verification, "fragment_index": 1},
        )
        assert missing_fragment.status_code == 404

        with pytest.raises(NotFound):
            app.state.runtime.service.verify_evidence_fragment(
                assessment_id=assessment_id,
                assessment_version=review_body["assessment_version"],
                assessment_etag=review_body["etag"],
                question_id=first_question["question_id"],
                fragment_index=0,
                actor=Actor(
                    user_id="usr_other_tenant",
                    email="other@example.test",
                    workspace_id="tnt_other",
                    role="TEACHER",
                    can_approve_assessments=True,
                    csrf_token="synthetic-csrf",
                ),
            )

        first_evidence_id = first_question["anchor"]["fragments"][0]["evidence_id"]
        with app.state.runtime.repository.session() as session:
            persisted_evidence = session.get(EvidenceRow, first_evidence_id)
            assert persisted_evidence is not None
            original_evidence = json.loads(json.dumps(persisted_evidence.data))
            tampered_evidence = json.loads(json.dumps(persisted_evidence.data))
            tampered_evidence["locator"] = {
                "kind": "DOCUMENT_PATH",
                "paragraph_index": 999,
            }
            persisted_evidence.data = tampered_evidence
        locator_mismatch = reopened.post(
            verify_path,
            headers=_mutating(headers),
            json=valid_verification,
        )
        assert locator_mismatch.status_code == 409
        assert locator_mismatch.json()["code"] == "IR_PROVENANCE_GAP"
        with app.state.runtime.repository.session() as session:
            persisted_evidence = session.get(EvidenceRow, first_evidence_id)
            assert persisted_evidence is not None
            persisted_evidence.data = original_evidence

        direct_approval = reopened.post(
            f"/api/v1/assessments/{assessment_id}:approve",
            headers=_mutating(headers, **{"If-Match": review_body["etag"]}),
            json={},
        )
        assert direct_approval.status_code == 409
        assert direct_approval.json()["code"] == "EVIDENCE_REVIEW_REQUIRED"

        expected_fragments = 0
        first_view_url = ""
        for question in assessment["questions"]:
            for fragment_index, _fragment in enumerate(question["anchor"]["fragments"]):
                expected_fragments += 1
                verification_payload = {
                    "assessment_version": review_body["assessment_version"],
                    "assessment_etag": review_body["etag"],
                    "question_id": question["question_id"],
                    "fragment_index": fragment_index,
                }
                verification_key = str(uuid4())
                verification_headers = {
                    **headers,
                    "Idempotency-Key": verification_key,
                }
                verified = reopened.post(
                    f"/api/v1/assessments/{assessment_id}/evidence:verify",
                    headers=verification_headers,
                    json=verification_payload,
                )
                assert verified.status_code == 200, verified.text
                dto.EvidenceVerifyEnvelope.model_validate(verified.json())
                if expected_fragments == 1:
                    persisted = app.state.runtime.repository.get(
                        IdempotencyRow,
                        stable_id(
                            "idem", "tnt_experimental", verification_key
                        ),
                    )
                    assert isinstance(persisted, IdempotencyRow)
                    serialized = json.dumps(persisted.response, sort_keys=True)
                    for forbidden in (
                        "view_url",
                        "expires_at",
                        "/api/v1/objects/",
                        "x-amz-signature",
                        "normalized_text",
                    ):
                        assert forbidden not in serialized.lower()

                    replayed = reopened.post(
                        verify_path,
                        headers=verification_headers,
                        json=verification_payload,
                    )
                    assert replayed.status_code == 200, replayed.text
                    assert replayed.headers["Idempotency-Replayed"] == "true"
                    assert (
                        replayed.json()["verification"]["receipt"]
                        == verified.json()["verification"]["receipt"]
                    )
                    dto.EvidenceVerifyEnvelope.model_validate(replayed.json())
                first_view_url = first_view_url or verified.json()["verification"]["view_url"]
                exact_source = reopened.get(
                    verified.json()["verification"]["view_url"]
                )
                assert exact_source.status_code == 200
                assert exact_source.content == deliverable

        reloaded_review = reopened.get(
            f"/api/v1/submissions/{submission_id}/assessment"
        )
        assert reloaded_review.status_code == 200
        assert len(reloaded_review.json()["evidence_receipts"]) == expected_fragments

        object_store = app.state.runtime.object_store
        assert isinstance(object_store, MemoryObjectStore)
        artifact_row = app.state.runtime.repository.get(
            ArtifactRow, artifact["artifact_id"]
        )
        assert isinstance(artifact_row, ArtifactRow)
        expired_token = object_store._token(artifact_row.object_key, "GET", -1)
        expired_source = reopened.get(f"/api/v1/objects/{expired_token}")
        assert expired_source.status_code == 403
        assert expired_source.json()["code"] == "SIGNED_URL_INVALID"
        invalid_source = reopened.get("/api/v1/objects/not-a-valid-capability")
        assert invalid_source.status_code == 403
        assert invalid_source.json()["code"] == "SIGNED_URL_INVALID"

        with TestClient(app) as reviewer:
            reviewer_headers = _login(reviewer, "reviewer@example.test")
            reviewer_view = reviewer.get(
                f"/api/v1/submissions/{submission_id}/assessment"
            )
            assert reviewer_view.status_code == 200
            assert reviewer_view.json()["evidence_receipts"] == []
            reviewer_approval = reviewer.post(
                f"/api/v1/assessments/{assessment_id}:approve",
                headers=_mutating(
                    reviewer_headers, **{"If-Match": review_body["etag"]}
                ),
                json={},
            )
            assert reviewer_approval.status_code == 409
            assert reviewer_approval.json()["code"] == "EVIDENCE_REVIEW_REQUIRED"

        ledger_before = reopened.get(
            f"/api/v1/jobs/{submission_job}/model-calls"
        ).json()["items"]
        prompt_sequence = [item["prompt_id"] for item in ledger_before]
        assert set(prompt_sequence) == {
            "P06_EVIDENCE_MAP_V1",
            "P07_QUESTION_BUILD_V1",
            "P09_GUIDE_BUILD_V1",
        }
        assert len(prompt_sequence) == 4
        assert prompt_sequence.count("P07_QUESTION_BUILD_V1") == 2
        assert "P08_QUESTION_REVIEW_V1" not in prompt_sequence
        stages = app.state.runtime.repository.stage_runs_for_job(
            submission_job, "tnt_experimental"
        )
        stage_names = [item.stage for item in stages]
        assert len(
            [name for name in stage_names if name.startswith("QUESTION_VALIDATE:")]
        ) == 2
        assert stage_names.index("ASSEMBLE") < stage_names.index(
            "P09_GUIDE_BUILD_V1"
        )
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
