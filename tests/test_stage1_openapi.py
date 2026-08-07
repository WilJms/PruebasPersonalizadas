from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from comprehension_verification.contracts import models as m
from comprehension_verification.web import dto
from comprehension_verification.web.app import create_app
from comprehension_verification.web.settings import Settings
from scripts.generate_openapi import build_schema


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "fixtures" / "openapi" / "stage1-v1.json"


def _refs(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_refs(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_refs(item))
    return found


def _resolve_local_ref(schema: dict[str, Any], ref: str) -> Any:
    assert ref.startswith("#/"), ref
    value: Any = schema
    for raw_part in ref.removeprefix("#/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[part]
    return value


def test_openapi_snapshot_is_deterministic() -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert build_schema() == expected
    assert build_schema() == build_schema()


def test_every_local_openapi_reference_resolves() -> None:
    schema = build_schema()
    for ref in _refs(schema):
        _resolve_local_ref(schema, ref)


def test_every_stage1_success_response_has_a_schema() -> None:
    schema = build_schema()
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "patch", "put", "delete"}:
                continue
            success_responses = {
                code: response
                for code, response in operation["responses"].items()
                if code.startswith("2")
            }
            assert success_responses, (method, path)
            for code, response in success_responses.items():
                if code == "204":
                    continue
                content = response.get("content", {})
                assert "application/json" in content, (method, path, code)
                assert "schema" in content["application/json"], (method, path, code)


def test_openapi_exposes_complete_review_contracts_and_no_stage2_actions() -> None:
    schema = build_schema()
    components = schema["components"]["schemas"]
    selected = components["SelectedQuestion"]["properties"]
    assert {
        "source_candidate_id",
        "opportunity_template_id",
        "choices",
        "student_justification_required",
        "preliminary_guide",
    }.issubset(selected)
    guide = components["GuideDraft"]["properties"]
    assert {"misconceptions", "cannot_infer", "observable_elements"}.issubset(guide)
    observable = components["ObservableElement"]["properties"]
    assert "source_ids" in observable
    level = components["GuideLevel"]["properties"]
    assert "observable_element_ids" in level
    paths = "\n".join(schema["paths"])
    for forbidden in ("bulk", "question-action", "retry", "cancel"):
        assert forbidden not in paths.lower()


def test_problem_detail_and_etag_are_documented() -> None:
    schema = build_schema()
    detail = schema["paths"]["/api/v1/activities/{activity_id}"]["get"]
    assert "ETag" in detail["responses"]["200"]["headers"]
    problem = detail["responses"]["404"]["content"]["application/problem+json"]
    assert problem["schema"]["$ref"].endswith("/ProblemDetail")


def test_provider_responses_validate_against_declared_transport_models() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+pysqlite://",
            session_secret="openapi-provider-test-secret-with-32-bytes",
            local_invited_emails="teacher@example.test",
        )
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/session/login", json={"email": "teacher@example.test"}
        )
        dto.SessionEnvelope.model_validate(login.json())
        csrf = client.cookies.get("cva_csrf")
        assert csrf
        created = client.post(
            "/api/v1/activities",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
            json={
                "title": "OpenAPI provider contract",
                "output_language": "es-CL",
                "assessment_modality": "WRITTEN",
                "question_count": 1,
                "target_total_minutes": 3,
                "allowed_response_formats": ["OPEN_SHORT", "CHOICE"],
                "allowed_artifact_media_types": ["text/plain"],
                "structured_justification_mode": "NOT_REQUIRED",
            },
        )
        created_body = dto.ActivityEnvelope.model_validate(created.json())
        activity_id = created_body.activity.activity_id
        detail = client.get(f"/api/v1/activities/{activity_id}")
        dto.ActivityEnvelope.model_validate(detail.json())
        assert detail.headers["etag"]
        dto.ActivityListEnvelope.model_validate(
            client.get("/api/v1/activities").json()
        )
        dto.EstimateEnvelope.model_validate(
            client.get(f"/api/v1/activities/{activity_id}/estimate").json()
        )
        problem = client.get("/api/v1/activities/activity_missing")
        assert problem.headers["content-type"].startswith("application/problem+json")
        m.ProblemDetail.model_validate(problem.json())


def test_transport_dtos_reject_coercion_extra_fields_and_invented_enums() -> None:
    valid = {
        "title": "Strict request",
        "output_language": "es-CL",
        "assessment_modality": "WRITTEN",
        "question_count": 1,
        "target_total_minutes": 3,
        "allowed_response_formats": ["OPEN_SHORT"],
        "allowed_artifact_media_types": ["text/plain"],
        "structured_justification_mode": "NOT_REQUIRED",
    }
    with pytest.raises(ValidationError):
        dto.ActivityCreateCommand.model_validate({**valid, "question_count": "1"})
    with pytest.raises(ValidationError):
        dto.ActivityCreateCommand.model_validate({**valid, "difficulty": "HARD"})
    with pytest.raises(ValidationError):
        dto.ActivityCreateCommand.model_validate(
            {**valid, "allowed_response_formats": ["OPEN_LONG"]}
        )
