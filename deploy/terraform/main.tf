data "google_project" "current" {
  project_id = var.project_id
}

locals {
  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "containeranalysis.googleapis.com",
    "containerscanning.googleapis.com",
    "iam.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])

  default_labels = {
    application = "comprehension-verification"
    environment = "experimental"
    stage       = "2"
  }
  labels = merge(local.default_labels, var.labels)

  secret_ids = {
    database_url         = "${var.name_prefix}-database-url"
    r2_access_key_id     = "${var.name_prefix}-r2-access-key-id"
    r2_secret_access_key = "${var.name_prefix}-r2-secret-access-key"
    session_secret       = "${var.name_prefix}-session-secret"
  }

  common_environment = {
    CVA_ENVIRONMENT              = "cloud"
    CVA_AUTH_MODE                = "supabase"
    CVA_OBJECT_STORE_MODE        = "r2"
    CVA_JOB_RUNNER_MODE          = "cloud_run"
    CVA_MODEL_MODE               = "mock"
    CVA_WORKER_MODEL_MODE        = var.enable_openai_real_provider ? "real" : "mock"
    CVA_MAX_JOB_COST_USD         = tostring(coalesce(var.openai_max_job_cost_usd, 0.50))
    CVA_P10_ENABLED              = "false"
    CVA_REQUIRE_LIBMAGIC         = "true"
    CVA_FRONTEND_DIST            = "/app/static"
    CVA_RENDERER_MODE            = "weasyprint"
    CVA_UPLOAD_URL_TTL_SECONDS   = tostring(var.upload_url_ttl_seconds)
    CVA_DOWNLOAD_URL_TTL_SECONDS = tostring(var.download_url_ttl_seconds)
    CVA_SUPABASE_JWT_ISSUER      = "${trimsuffix(var.supabase_url, "/")}/auth/v1"
    CVA_SUPABASE_JWKS_URL        = "${trimsuffix(var.supabase_url, "/")}/auth/v1/.well-known/jwks.json"
    CVA_SUPABASE_JWT_AUDIENCE    = var.supabase_jwt_audience
    CVA_R2_ENDPOINT_URL          = var.r2_endpoint_url
    CVA_R2_BUCKET                = var.r2_bucket_name
    CVA_GCP_PROJECT_ID           = var.project_id
    CVA_GCP_REGION               = var.region
    CVA_CLOUD_RUN_JOB_NAME       = var.job_name
  }

  web_environment = local.common_environment
  worker_environment = {
    CVA_ENVIRONMENT              = "cloud"
    CVA_OBJECT_STORE_MODE        = "r2"
    CVA_MODEL_MODE               = var.enable_openai_real_provider ? "real" : "mock"
    CVA_MAX_JOB_COST_USD         = tostring(coalesce(var.openai_max_job_cost_usd, 0.50))
    CVA_P10_ENABLED              = "false"
    CVA_REQUIRE_LIBMAGIC         = "true"
    CVA_RENDERER_MODE            = "weasyprint"
    CVA_UPLOAD_URL_TTL_SECONDS   = tostring(var.upload_url_ttl_seconds)
    CVA_DOWNLOAD_URL_TTL_SECONDS = tostring(var.download_url_ttl_seconds)
    CVA_R2_ENDPOINT_URL          = var.r2_endpoint_url
    CVA_R2_BUCKET                = var.r2_bucket_name
  }

  authorized_github_repository    = "https://github.com/WilJms/PruebasPersonalizadas.git"
  expected_container_image_prefix = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}/application@sha256:"
}

resource "terraform_data" "runtime_preconditions" {
  input = var.enable_runtime_resources

  lifecycle {
    precondition {
      condition = trimspace(var.container_image) == "" || startswith(
        var.container_image,
        local.expected_container_image_prefix,
      )
      error_message = "container_image must come from this deployment's regional application repository."
    }

    precondition {
      condition = !var.enable_runtime_resources || alltrue([
        trimspace(var.container_image) != "",
        trimspace(var.supabase_url) != "",
        trimspace(var.supabase_publishable_key) != "",
        trimspace(var.r2_endpoint_url) != "",
        trimspace(var.r2_bucket_name) != "",
      ])
      error_message = "Runtime resources require an image and all non-secret Supabase/R2 settings."
    }

    precondition {
      condition = !var.enable_openai_real_provider || alltrue([
        var.enable_runtime_resources,
        var.enable_openai_secret_container,
        var.openai_api_key_secret_version != null,
        var.openai_max_job_cost_usd != null,
      ])
      error_message = "Real OpenAI worker mode requires runtime resources, the separately managed secret container, a pinned secret version, and an explicit job-cost ceiling."
    }
  }
}

resource "terraform_data" "cloud_build_preconditions" {
  input = var.enable_cloud_build_trigger

  lifecycle {
    precondition {
      condition = !var.enable_cloud_build_trigger || alltrue([
        var.enable_cloud_build_connection,
        var.github_app_installation_id != null,
        var.github_oauth_token_secret_version != null,
        trimspace(var.supabase_url) != "",
        trimspace(var.supabase_publishable_key) != "",
      ])
      error_message = "The GitHub trigger requires its connection and all public frontend build settings."
    }
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "application" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "Stage 2 experimental application images"
  format        = "DOCKER"
  labels        = local.labels

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required["artifactregistry.googleapis.com"]]
}

resource "google_service_account" "web" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-web"
  display_name = "CVA Stage 2 web runtime"

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_service_account" "worker" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-worker"
  display_name = "CVA Stage 2 job runtime"

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-cloudbuild"
  display_name = "CVA Stage 2 Cloud Build publisher"

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_project_iam_member" "build_roles" {
  for_each = toset([
    "roles/artifactregistry.writer",
    "roles/logging.logWriter",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/storage.bucketViewer",
    "roles/storage.objectUser",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_secret_manager_secret" "runtime" {
  for_each = local.secret_ids

  project             = var.project_id
  secret_id           = each.value
  labels              = local.labels
  deletion_protection = true

  replication {
    auto {}
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required["secretmanager.googleapis.com"]]
}

resource "google_secret_manager_secret" "openai_api_key" {
  count = var.enable_openai_secret_container ? 1 : 0

  project             = var.project_id
  secret_id           = "${var.name_prefix}-openai-api-key"
  labels              = local.labels
  deletion_protection = true

  replication {
    auto {}
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required["secretmanager.googleapis.com"]]
}

resource "google_secret_manager_secret_iam_member" "openai_worker_access" {
  count = var.enable_openai_real_provider ? 1 : 0

  project   = var.project_id
  secret_id = google_secret_manager_secret.openai_api_key[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

locals {
  runtime_secret_members = merge(
    {
      for secret_key in keys(google_secret_manager_secret.runtime) :
      "${secret_key}|${google_service_account.web.email}" => {
        secret_key = secret_key
        member     = google_service_account.web.email
      }
    },
    {
      for secret_key in setsubtract(
        toset(keys(google_secret_manager_secret.runtime)),
        toset(["session_secret"]),
      ) :
      "${secret_key}|${google_service_account.worker.email}" => {
        secret_key = secret_key
        member     = google_service_account.worker.email
      }
    },
  )
}

resource "google_secret_manager_secret_iam_member" "runtime_access" {
  for_each = local.runtime_secret_members

  project   = var.project_id
  secret_id = google_secret_manager_secret.runtime[each.value.secret_key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.member}"
}

resource "google_cloud_run_v2_service" "web" {
  count = var.enable_runtime_resources ? 1 : 0

  project             = var.project_id
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true
  labels              = local.labels

  # The Cloud Run API persists these zero values in the service-level scaling
  # object.  Declaring them makes refresh/plan converge without ignore_changes.
  scaling {
    manual_instance_count = 0
    min_instance_count    = 0
  }

  template {
    service_account = google_service_account.web.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.web_min_instances
      max_instance_count = var.web_max_instances
    }

    containers {
      image = var.container_image
      args  = ["web"]

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.web_environment
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "CVA_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["database_url"].secret_id
            version = var.secret_version
          }
        }
      }

      env {
        name = "CVA_R2_ACCESS_KEY_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["r2_access_key_id"].secret_id
            version = var.secret_version
          }
        }
      }

      env {
        name = "CVA_R2_SECRET_ACCESS_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["r2_secret_access_key"].secret_id
            version = var.secret_version
          }
        }
      }

      env {
        name = "CVA_SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime["session_secret"].secret_id
            version = var.secret_version
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12

        http_get {
          path = "/api/readiness"
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 10
        timeout_seconds       = 3
        period_seconds        = 30
        failure_threshold     = 3

        http_get {
          path = "/api/health"
          port = 8080
        }
      }
    }
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = terraform_data.runtime_preconditions.output
      error_message = "Runtime preconditions were not satisfied."
    }
  }

  depends_on = [
    google_project_service.required["run.googleapis.com"],
    google_secret_manager_secret_iam_member.runtime_access,
  ]
}

resource "google_cloud_run_v2_job" "worker" {
  count = var.enable_runtime_resources ? 1 : 0

  project             = var.project_id
  name                = var.job_name
  location            = var.region
  deletion_protection = true
  labels              = local.labels

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.worker.email
      timeout         = "3600s"
      # Dispatch carries no job id; an infrastructure retry could otherwise
      # claim a different durable QUEUED row after the first row failed.
      max_retries = 0

      containers {
        image = var.container_image
        args  = ["worker"]

        resources {
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }

        dynamic "env" {
          for_each = local.worker_environment
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name = "CVA_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.runtime["database_url"].secret_id
              version = var.secret_version
            }
          }
        }

        env {
          name = "CVA_R2_ACCESS_KEY_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.runtime["r2_access_key_id"].secret_id
              version = var.secret_version
            }
          }
        }

        env {
          name = "CVA_R2_SECRET_ACCESS_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.runtime["r2_secret_access_key"].secret_id
              version = var.secret_version
            }
          }
        }

        dynamic "env" {
          for_each = var.enable_openai_real_provider ? [1] : []

          content {
            name = "CVA_OPENAI_API_KEY"
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.openai_api_key[0].secret_id
                version = var.openai_api_key_secret_version
              }
            }
          }
        }

      }
    }
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = terraform_data.runtime_preconditions.output
      error_message = "Runtime preconditions were not satisfied."
    }
  }

  depends_on = [
    google_project_service.required["run.googleapis.com"],
    google_secret_manager_secret_iam_member.runtime_access,
    google_secret_manager_secret_iam_member.openai_worker_access,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_login" {
  count = var.enable_runtime_resources && var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job_iam_member" "web_can_execute_worker" {
  count = var.enable_runtime_resources ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.worker[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.web.email}"
}

resource "google_cloudbuildv2_connection" "github" {
  count = var.enable_cloud_build_connection ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = "${var.name_prefix}-github"

  github_config {
    app_installation_id = var.github_app_installation_id

    dynamic "authorizer_credential" {
      for_each = var.github_oauth_token_secret_version == null ? [] : [var.github_oauth_token_secret_version]

      content {
        oauth_token_secret_version = authorizer_credential.value
      }
    }
  }

  depends_on = [google_project_service.required["cloudbuild.googleapis.com"]]
}

resource "google_cloudbuildv2_repository" "github" {
  count = var.enable_cloud_build_trigger ? 1 : 0

  project           = var.project_id
  location          = var.region
  name              = "${var.name_prefix}-github-repository"
  parent_connection = google_cloudbuildv2_connection.github[0].id
  remote_uri        = local.authorized_github_repository
}

resource "google_cloudbuild_trigger" "github_push" {
  count = var.enable_cloud_build_trigger ? 1 : 0

  project     = var.project_id
  location    = var.region
  name        = "${var.name_prefix}-github-push"
  description = "Build and verify Stage 2 from the authorized GitHub repository"
  filename    = "deploy/cloudbuild.yaml"
  service_account = (
    "projects/${var.project_id}/serviceAccounts/${google_service_account.build.email}"
  )
  substitutions = {
    _REGION                        = var.region
    _REPOSITORY                    = var.repository_id
    _IMAGE                         = "application"
    _VITE_SUPABASE_URL             = var.supabase_url
    _VITE_SUPABASE_PUBLISHABLE_KEY = var.supabase_publishable_key
  }

  repository_event_config {
    repository = google_cloudbuildv2_repository.github[0].id

    push {
      branch = "^(main|fix/stage1-external-readiness|codex/stage2-experimental-mvp)$"
    }
  }

  lifecycle {
    precondition {
      condition     = terraform_data.cloud_build_preconditions.output
      error_message = "Cloud Build trigger preconditions were not satisfied."
    }
  }
}
