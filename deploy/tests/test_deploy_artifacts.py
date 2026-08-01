"""Static deployment checks that require no cloud account or credentials."""

from __future__ import annotations

import json
import re
from pathlib import Path

from comprehension_verification.web.repository import Base


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "deploy/supabase/migrations/202607310001_stage1.sql"


def _migration_schema(sql: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    pattern = re.compile(
        r"create\s+table\s+public\.(?P<name>[a-z_]+)\s*\((?P<body>.*?)\n\);",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        columns: set[str] = set()
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.lower().startswith(
                ("constraint ", "primary key ", "unique ", "foreign key ", "check ")
            ):
                continue
            columns.add(line.split(maxsplit=1)[0].strip('"').lower())
        tables[match.group("name").lower()] = columns
    return tables


def test_supabase_migration_matches_executable_orm_tables_and_columns() -> None:
    actual = _migration_schema(MIGRATION.read_text(encoding="utf-8"))
    expected = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }

    assert actual == expected


def test_supabase_migration_has_stage_one_security_and_drift_guards() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    table_names = {table.name for table in Base.metadata.sorted_tables}

    for table_name in table_names:
        assert f"alter table public.{table_name} enable row level security;" in sql

    assert "revoke all on all tables in schema public from anon, authenticated;" in sql
    assert "grant all on all tables in schema public to service_role;" in sql
    assert "uq_artifacts_role_per_scope" in sql
    assert "uq_policy_decision_issue" in sql
    assert "policy_hash varchar(71) not null" in sql
    assert re.search(r"response\s+jsonb\s*,", sql)
    assert re.search(r"blueprint_version\s+integer\s*,", sql)
    assert "model_calls_are_append_only" in sql
    assert "audit_events_are_append_only" in sql
    assert "activity_artifacts" not in sql
    assert "submission_artifacts" not in sql


def test_runtime_configuration_uses_exact_settings_names_and_safe_defaults() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    terraform = (ROOT / "deploy/terraform/main.tf").read_text(encoding="utf-8")
    combined = f"{dockerfile}\n{terraform}"
    required = {
        "CVA_ENVIRONMENT",
        "CVA_DATABASE_URL",
        "CVA_AUTH_MODE",
        "CVA_OBJECT_STORE_MODE",
        "CVA_JOB_RUNNER_MODE",
        "CVA_MODEL_MODE",
        "CVA_P10_ENABLED",
        "CVA_SESSION_SECRET",
        "CVA_SUPABASE_JWT_ISSUER",
        "CVA_SUPABASE_JWKS_URL",
        "CVA_SUPABASE_JWT_AUDIENCE",
        "CVA_R2_ENDPOINT_URL",
        "CVA_R2_BUCKET",
        "CVA_R2_ACCESS_KEY_ID",
        "CVA_R2_SECRET_ACCESS_KEY",
        "CVA_GCP_PROJECT_ID",
        "CVA_GCP_REGION",
        "CVA_CLOUD_RUN_JOB_NAME",
        "CVA_FRONTEND_DIST",
        "CVA_RENDERER_MODE",
    }

    assert not {name for name in required if name not in combined}
    assert re.search(r'CVA_MODEL_MODE\s*=\s*"mock"', terraform)
    assert re.search(r'CVA_P10_ENABLED\s*=\s*"false"', terraform)
    assert "CVA_ENV=" not in combined
    assert "CVA_OBJECT_STORE=" not in combined
    assert "CVA_JOB_RUNNER=" not in combined
    assert "/api/health" in terraform
    assert "/healthz" not in terraform


def test_container_and_cloud_build_are_single_image_and_mock_safe() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "deploy/docker-entrypoint.sh").read_text(encoding="utf-8")
    cloudbuild = (ROOT / "deploy/cloudbuild.yaml").read_text(encoding="utf-8")

    assert "ARG VITE_SUPABASE_URL" in dockerfile
    assert "ARG VITE_SUPABASE_PUBLISHABLE_KEY" in dockerfile
    assert "SUPABASE_SERVICE" not in dockerfile + cloudbuild
    assert "COPY --from=frontend-build /build/frontend/dist /app/static" in dockerfile
    assert "USER 65532:65532" in dockerfile
    assert "comprehension_verification.web.app:app" in entrypoint
    assert "comprehension_verification.web.worker" in entrypoint
    assert "VITE_SUPABASE_URL=${_VITE_SUPABASE_URL}" in cloudbuild
    assert "VITE_SUPABASE_PUBLISHABLE_KEY=${_VITE_SUPABASE_PUBLISHABLE_KEY}" in cloudbuild
    assert "_DEPLOY_RUNTIME" in cloudbuild
    assert "/api/health" in cloudbuild


def test_terraform_declares_service_job_secrets_and_job_invocation() -> None:
    terraform = (ROOT / "deploy/terraform/main.tf").read_text(encoding="utf-8")

    assert 'resource "google_cloud_run_v2_service" "web"' in terraform
    assert 'resource "google_cloud_run_v2_job" "worker"' in terraform
    assert 'resource "google_secret_manager_secret" "runtime"' in terraform
    assert 'resource "google_cloud_run_v2_job_iam_member" "web_can_execute_worker"' in terraform
    assert 'role     = "roles/run.invoker"' in terraform
    assert '"storage.googleapis.com"' in terraform
    assert '"roles/storage.bucketViewer"' in terraform
    assert '"roles/storage.objectUser"' in terraform
    assert "enable_runtime_resources" in terraform
    assert 'version = var.secret_version' in terraform
    assert terraform.count('name = "CVA_SESSION_SECRET"') == 2


def test_r2_policy_examples_are_private_origin_scoped_and_expiring() -> None:
    cors = json.loads((ROOT / "deploy/r2/cors.example.json").read_text(encoding="utf-8"))
    lifecycle = json.loads(
        (ROOT / "deploy/r2/lifecycle.example.json").read_text(encoding="utf-8")
    )

    rule = cors["rules"][0]
    assert rule["allowed"]["origins"] == ["https://replace-with-cloud-run-origin"]
    assert "*" not in json.dumps(cors)
    assert set(rule["allowed"]["methods"]) == {"GET", "PUT", "HEAD"}
    assert rule["allowed"]["headers"] == ["Content-Type"]
    assert rule["exposeHeaders"] == ["ETag"]

    rules_by_prefix = {item["conditions"]["prefix"]: item for item in lifecycle["rules"]}
    assert rules_by_prefix["raw/"]["deleteObjectsTransition"]["condition"] == {
        "type": "Age",
        "maxAge": 2_592_000,
    }
    assert rules_by_prefix["exports/"]["deleteObjectsTransition"]["condition"] == {
        "type": "Age",
        "maxAge": 10_368_000,
    }
