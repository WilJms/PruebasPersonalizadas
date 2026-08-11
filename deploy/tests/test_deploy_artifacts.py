"""Static deployment checks that require no cloud account or credentials."""

from __future__ import annotations

import json
import re
from pathlib import Path
import subprocess

import yaml

from comprehension_verification.web.repository import Base
from comprehension_verification.web.settings import Settings, WorkerSettings


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "deploy/supabase/migrations"
MIGRATION = MIGRATION_DIR / "202607310001_stage1.sql"
IDEMPOTENCY_HYGIENE_MIGRATION = (
    MIGRATION_DIR / "202608070002_idempotency_capability_hygiene.sql"
)
STAGE2_MIGRATION = MIGRATION_DIR / "202608070003_stage2_experimental.sql"
STAGE2_RECOVERY = (
    ROOT
    / "deploy/supabase/rollbacks/202608070003_stage2_experimental_recovery.sql"
)


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


def test_supabase_migration_matches_orm_table_and_column_surface() -> None:
    actual = _migration_schema(MIGRATION.read_text(encoding="utf-8"))
    stage2_tables = {
        "bulk_approval_records",
        "bulk_approval_requests",
        "feedback_events",
        "job_control_records",
        "question_review_actions",
    }
    stage2_columns = {
        "exports": {
            "activity_id", "assessment_version", "assessment_snapshot_hash",
            "renderer_version", "requested_by", "requested_kinds",
            "guide_snapshot_hash", "coverage_snapshot_hash", "completed_at", "data",
        },
        "jobs": {
            "control_state", "failure_class", "max_attempts", "next_attempt_at",
            "resume_from_stage", "cancel_requested_at", "cancel_requested_by",
            "cancelled_at",
        },
        "stage_runs": {
            "component_version", "output_hash", "failure_class", "next_attempt_at",
            "resumed_from_stage_run_id",
        },
    }
    expected = {
        table.name: {column.name for column in table.columns}
        - stage2_columns.get(table.name, set())
        for table in Base.metadata.sorted_tables
        if table.name not in stage2_tables
    }

    assert actual == expected


def test_supabase_migration_has_stage_one_security_and_drift_guards() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    ordered_sql = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(MIGRATION_DIR.glob("*.sql"))
    )
    table_names = {table.name for table in Base.metadata.sorted_tables}

    for table_name in table_names:
        assert (
            f"alter table public.{table_name} enable row level security;"
            in ordered_sql
        )

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
    index_names = re.findall(r"create\s+(?:unique\s+)?index\s+([a-z0-9_]+)", sql)
    assert len(index_names) == len(set(index_names))


def test_idempotency_hygiene_migration_removes_and_blocks_capabilities() -> None:
    assert [path.name for path in sorted(MIGRATION_DIR.glob("*.sql"))] == [
        "202607310001_stage1.sql",
        "202608070002_idempotency_capability_hygiene.sql",
        "202608070003_stage2_experimental.sql",
    ]
    sql = IDEMPOTENCY_HYGIENE_MIGRATION.read_text(encoding="utf-8").lower()
    assert sql.startswith("begin;")
    assert sql.rstrip().endswith("commit;")
    assert "delete from public.idempotency_keys" in sql
    assert "response = 'null'::jsonb" in sql
    assert '"[^"]*_url"' in sql
    assert "x-amz-" in sql
    assert "ck_idempotency_keys_safe_response" in sql
    assert "jsonb_typeof(response) = 'object'" in sql
    assert "drop table" not in sql


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
        "CVA_WORKER_MODEL_MODE",
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
        "CVA_UPLOAD_URL_TTL_SECONDS",
        "CVA_DOWNLOAD_URL_TTL_SECONDS",
    }

    assert not {name for name in required if name not in combined}
    assert re.search(r'CVA_MODEL_MODE\s*=\s*"mock"', terraform)
    assert 'var.enable_openai_real_provider ? "real" : "mock"' in terraform
    assert re.search(r'CVA_P10_ENABLED\s*=\s*"false"', terraform)
    assert "CVA_ENV=" not in combined
    assert "CVA_OBJECT_STORE=" not in combined
    assert "CVA_JOB_RUNNER=" not in combined
    assert "/api/health" in terraform
    assert "/api/readiness" in terraform
    assert "CVA_SIGNED_URL_TTL_SECONDS" not in combined
    assert "/healthz" not in terraform


def test_container_and_cloud_build_are_single_image_and_mock_safe() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "deploy/docker-entrypoint.sh").read_text(encoding="utf-8")
    cloudbuild = (ROOT / "deploy/cloudbuild.yaml").read_text(encoding="utf-8")
    parsed_cloudbuild = yaml.safe_load(cloudbuild)

    assert "ARG VITE_SUPABASE_URL" in dockerfile
    assert "ARG VITE_SUPABASE_PUBLISHABLE_KEY" in dockerfile
    assert "SUPABASE_SERVICE" not in dockerfile + cloudbuild
    assert "COPY --from=frontend-build /build/frontend/dist /app/static" in dockerfile
    assert "USER 65532:65532" in dockerfile
    assert "chown -R root:root /app" in dockerfile
    assert "chmod -R a-w /app" in dockerfile
    assert "comprehension_verification.web.app:app" in entrypoint
    assert "comprehension_verification.web.worker" in entrypoint
    assert "VITE_SUPABASE_URL=${_VITE_SUPABASE_URL}" in cloudbuild
    assert "VITE_SUPABASE_PUBLISHABLE_KEY=${_VITE_SUPABASE_PUBLISHABLE_KEY}" in cloudbuild
    assert "gcloud run" not in cloudbuild
    assert "org.opencontainers.image.revision=$COMMIT_SHA" in cloudbuild
    assert "requestedVerifyOption: VERIFIED" in cloudbuild
    assert parsed_cloudbuild["options"]["requestedVerifyOption"] == "VERIFIED"
    assert all(step.get("args", [None])[0] != "push" for step in parsed_cloudbuild["steps"])
    assert parsed_cloudbuild["images"]
    assert "/api/health" in cloudbuild
    assert "/api/readiness" in cloudbuild

    steps = {step["id"]: step for step in parsed_cloudbuild["steps"]}
    step_ids = [step["id"] for step in parsed_cloudbuild["steps"]]
    assert step_ids[:3] == [
        "verify-contracts-backend-deploy-security",
        "verify-terraform",
        "verify-frontend",
    ]
    assert step_ids.index("verify-terraform") < step_ids.index("build-image")
    assert step_ids.index("verify-frontend") < step_ids.index("build-image")
    assert step_ids.index("build-image") < step_ids.index("smoke-runtime-locally")
    assert all("waitFor" not in step for step in parsed_cloudbuild["steps"])
    assert all(not step.get("allowFailure", False) for step in parsed_cloudbuild["steps"])
    assert all("allowExitCodes" not in step for step in parsed_cloudbuild["steps"])
    for gate_id in step_ids[:3]:
        assert re.fullmatch(
            r"[^@\s]+@sha256:[0-9a-f]{64}",
            steps[gate_id]["name"],
        )

    runtime_smoke = "\n".join(steps["smoke-runtime-locally"]["args"])
    for boundary in (
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "SafeParserService(require_libmagic=True)",
        "timeout_seconds=30",
        "require_isolation=True",
        "parsed.mime_detector == \"libmagic\"",
    ):
        assert boundary in runtime_smoke
    assert "timeout_seconds=5" not in runtime_smoke
    assert Settings.model_fields["parser_timeout_seconds"].default == 30
    assert WorkerSettings.model_fields["parser_timeout_seconds"].default == 30

    python_gate = "\n".join(steps["verify-contracts-backend-deploy-security"]["args"])
    assert "apk add --no-cache git libmagic make" in python_gate
    for command in (
        "python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock",
        "git init -q",
        "git add -A",
        "python -m comprehension_verification.cli validate-contracts",
        "python -m comprehension_verification.cli build-fixtures",
        "python scripts/generate_openapi.py",
        "python -m pytest tests",
        "python -m pytest deploy/tests/test_deploy_artifacts.py",
        "python -m pytest tests/test_stage2_security.py",
        "python scripts/check_secrets.py",
    ):
        assert command in python_gate
    assert "git diff --exit-code" in python_gate
    assert python_gate.index("git add -A") < python_gate.index("python scripts/generate_openapi.py")

    terraform_gate = "\n".join(steps["verify-terraform"]["args"])
    for command in (
        "terraform fmt -check -recursive deploy/terraform",
        "terraform -chdir=deploy/terraform init -backend=false -input=false -lockfile=readonly",
        "terraform -chdir=deploy/terraform validate",
    ):
        assert command in terraform_gate

    frontend_gate = "\n".join(steps["verify-frontend"]["args"])
    for command in (
        "npm ci",
        "npm run openapi:generate",
        "sha256sum --check /tmp/cva-generated-openapi.sha256",
        "npm run typecheck",
        "npm run test",
        "npm run build",
        "npm audit --audit-level=high",
    ):
        assert command in frontend_gate
    assert steps["verify-frontend"]["dir"] == "frontend"
    assert parsed_cloudbuild["timeout"] == "3600s"


def test_build_inputs_are_immutable_and_dependency_installs_are_locked() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    production_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    development_lock = (ROOT / "requirements-dev.lock").read_text(encoding="utf-8")

    assert re.search(r"ARG NODE_IMAGE=node:[^\s]+@sha256:[0-9a-f]{64}", dockerfile)
    assert re.search(r"ARG PYTHON_IMAGE=python:[^\s]+@sha256:[0-9a-f]{64}", dockerfile)
    assert re.search(
        r"ARG PYTHON_IMAGE=python:3\.12-alpine[^\s]*@sha256:[0-9a-f]{64}",
        dockerfile,
    )
    assert "apt-get" not in dockerfile
    assert re.search(r"apk add --no-cache[\s\\\n]+.*libmagic", dockerfile, re.DOTALL)
    assert "ENV CVA_REQUIRE_LIBMAGIC=true" in dockerfile
    assert "apk upgrade --no-cache" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "npm install" not in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    assert dockerfile.count("pip uninstall --yes pip") == 2
    assert "rm -rf /usr/local/lib/python3.12/ensurepip" in dockerfile
    for lock in (production_lock, development_lock):
        assert "--hash=sha256:" in lock
        assert "comprehension-verification (pyproject.toml)" in lock

    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_cloud_build_yaml_and_entrypoint_are_parseable() -> None:
    parsed = yaml.safe_load(
        (ROOT / "deploy/cloudbuild.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(parsed, dict)
    assert parsed["steps"]
    subprocess.run(
        ["sh", "-n", str(ROOT / "deploy/docker-entrypoint.sh")],
        check=True,
    )


def test_terraform_declares_service_job_secrets_and_job_invocation() -> None:
    terraform = (ROOT / "deploy/terraform/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "deploy/terraform/variables.tf").read_text(encoding="utf-8")
    outputs = (ROOT / "deploy/terraform/outputs.tf").read_text(encoding="utf-8")

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
    assert terraform.count('name = "CVA_SESSION_SECRET"') == 1
    worker = terraform.split(
        'resource "google_cloud_run_v2_job" "worker"', 1
    )[1].split(
        'resource "google_cloud_run_v2_service_iam_member" "public_login"', 1
    )[0]
    assert "CVA_SESSION_SECRET" not in worker
    assert 'toset(["session_secret"])' in terraform
    assert re.search(r"max_retries\s*=\s*0", terraform)
    assert terraform.count("image = var.container_image") == 2
    assert (
        "${var.region}-docker\\\\.pkg\\\\.dev/${var.project_id}/"
        "${var.repository_id}/application@sha256:[0-9a-f]{64}"
        in variables
    )
    assert "local.expected_container_image_prefix" in terraform
    assert "/application@sha256:" in terraform
    assert "deletion_protection = false" not in terraform
    assert terraform.count("deletion_protection = true") == 4
    assert terraform.count("prevent_destroy = true") == 5
    assert 'output "service_name"' in outputs
    assert 'output "job_name"' in outputs
    assert 'output "runtime_container_image"' in outputs
    assert '"roles/run.admin"' not in terraform
    assert "build_can_use_web_identity" not in terraform
    assert "build_can_use_worker_identity" not in terraform
    assert re.search(
        r"scaling\s*\{\s*manual_instance_count\s*=\s*0\s*"
        r"min_instance_count\s*=\s*0\s*\}",
        terraform,
    )
    assert 'resource "google_cloudbuildv2_connection" "github"' in terraform
    assert 'resource "google_cloudbuildv2_repository" "github"' in terraform
    assert 'resource "google_cloudbuild_trigger" "github_push"' in terraform
    assert 'https://github.com/WilJms/PruebasPersonalizadas.git' in terraform
    assert (
        'branch = "^(main|fix/stage1-external-readiness|codex/stage2-experimental-mvp)$"'
        in terraform
    )
    assert terraform.count('CVA_REQUIRE_LIBMAGIC         = "true"') == 2
    assert terraform.count('name = "CVA_OPENAI_API_KEY"') == 1
    assert terraform.count("CVA_MAX_JOB_COST_USD") == 2
    assert 'resource "google_secret_manager_secret" "openai_api_key"' in terraform
    assert (
        'resource "google_secret_manager_secret_iam_member" "openai_worker_access"'
        in terraform
    )
    web = terraform.split(
        'resource "google_cloud_run_v2_service" "web"', 1
    )[1].split('resource "google_cloud_run_v2_job" "worker"', 1)[0]
    assert "CVA_OPENAI_API_KEY" not in web
    openai_iam = terraform.split(
        'resource "google_secret_manager_secret_iam_member" "openai_worker_access"', 1
    )[1].split("\n}\n\nlocals", 1)[0]
    assert "google_service_account.worker.email" in openai_iam
    assert "google_service_account.web.email" not in openai_iam
    assert 'version = var.openai_api_key_secret_version' in worker
    assert "CVA_MAX_JOB_COST_USD" in terraform
    assert "var.openai_max_job_cost_usd != null" in terraform
    assert "openai_max_job_cost_usd         = null" in (
        ROOT / "deploy/terraform/terraform.tfvars.example"
    ).read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in (ROOT / "deploy/cloudbuild.yaml").read_text(
        encoding="utf-8"
    )
    assert "OPENAI_API_KEY" not in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "openai_api_key =" not in (
        ROOT / "deploy/terraform/terraform.tfvars.example"
    ).read_text(encoding="utf-8")
    assert 'filename    = "deploy/cloudbuild.yaml"' in terraform
    assert "google_service_account.build.email" in terraform
    assert "github_oauth_token_secret_version" in terraform
    assert "oauth_token_secret_version = authorizer_credential.value" in terraform
    assert "github_app_installation_id != null" in terraform
    assert "pull_request" not in terraform
    assert '"containeranalysis.googleapis.com"' in terraform
    assert '"containerscanning.googleapis.com"' in terraform
    startup = re.search(r"startup_probe\s*\{(?P<body>.*?)\n\s*\}", terraform, re.DOTALL)
    liveness = re.search(r"liveness_probe\s*\{(?P<body>.*?)\n\s*\}", terraform, re.DOTALL)
    assert startup and '/api/readiness' in startup.group("body")
    assert liveness and '/api/health' in liveness.group("body")


def test_stage2_deployment_runbook_has_real_digest_and_fail_closed_recovery() -> None:
    readme = (ROOT / "deploy/README.md").read_text(encoding="utf-8")
    migrations = [
        "202607310001_stage1.sql",
        "202608070002_idempotency_capability_hygiene.sql",
        "202608070003_stage2_experimental.sql",
    ]
    positions = [readme.index(name) for name in migrations]
    assert positions == sorted(positions)
    assert all((MIGRATION_DIR / name).is_file() for name in migrations)
    assert STAGE2_MIGRATION.is_file()
    assert STAGE2_RECOVERY.is_file()
    assert str(STAGE2_RECOVERY.relative_to(ROOT)) in readme
    assert "PGSERVICE=cva-stage2-admin" in readme
    assert "--set=ON_ERROR_STOP=1" in readme
    assert "gcloud artifacts docker images describe" in readme
    assert "value(results.images[0].digest)" in readme
    assert "value(image_summary.digest)" in readme
    assert "^sha256:[0-9a-f]{64}$" in readme
    assert 'test "$CVA_STAGE2_BUILD_DIGEST" = "$CVA_STAGE2_REGISTRY_DIGEST"' in readme
    assert "/tmp/cva-stage2-container-image.txt" in readme
    assert "/workspace/container-image.txt" not in readme
    assert 'COMMIT_SHA="$CVA_STAGE2_SOURCE_SHA"' in readme
    assert 'test -z "$(git status --porcelain=v1)"' in readme
    assert "output -raw cloud_build_service_account" in readme
    assert (
        'CVA_STAGE2_BUILD_SERVICE_ACCOUNT_RESOURCE="projects/'
        '$CVA_STAGE2_PROJECT/serviceAccounts/$CVA_STAGE2_BUILD_SERVICE_ACCOUNT"'
        in readme
    )
    assert '"cva-cloudbuild@$CVA_STAGE2_PROJECT.iam.gserviceaccount.com"' in readme
    assert '--service-account="$CVA_STAGE2_BUILD_SERVICE_ACCOUNT_RESOURCE"' in readme
    assert "--timeout=3600s" in readme
    assert 'test -n "$CVA_STAGE2_BUILD_ID"' in readme
    assert "cualquier repetición requiere un gate humano" in readme
    assert readme.count("-detailed-exitcode") == 2
    assert "gcloud run services describe" in readme
    assert "gcloud run jobs describe" in readme
    assert 'test "$CVA_STAGE2_SERVICE_IMAGE" = "$CVA_STAGE2_EXPECTED_IMAGE"' in readme
    assert 'test "$CVA_STAGE2_JOB_IMAGE" = "$CVA_STAGE2_EXPECTED_IMAGE"' in readme
    assert "transacción conserva íntegro el schema E2" in readme
    assert "no se fuerzan `DROP`" in readme
    recovery = STAGE2_RECOVERY.read_text(encoding="utf-8").lower()
    assert "max_attempts <> 3" in recovery


def test_docker_context_keeps_audit_fixtures_out_of_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    runtime_section = dockerfile.split("FROM runtime-base AS runtime", 1)[1]
    audit_section = dockerfile.split("FROM runtime-base AS audit", 1)[1].split(
        "FROM runtime-base AS runtime", 1
    )[0]
    assert "fixtures" not in runtime_section
    assert "COPY --chown=65532:65532 fixtures/ /app/fixtures/" in audit_section
    assert "fixtures" not in {
        line.strip().rstrip("/")
        for line in dockerignore.splitlines()
        if line.strip() and not line.startswith("#")
    }


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
