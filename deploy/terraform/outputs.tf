output "artifact_registry_repository" {
  description = "Docker repository prefix for application images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.application.repository_id}"
}

output "cloud_build_service_account" {
  description = "Select this service account when creating the Cloud Build trigger."
  value       = google_service_account.build.email
}

output "cloud_build_connection" {
  description = "Regional GitHub connection and its non-secret installation state."
  value = var.enable_cloud_build_connection ? {
    id                 = google_cloudbuildv2_connection.github[0].id
    installation_state = google_cloudbuildv2_connection.github[0].installation_state
  } : null
}

output "cloud_build_repository" {
  description = "Authorized GitHub repository resource used by the trigger."
  value       = try(google_cloudbuildv2_repository.github[0].id, null)
}

output "cloud_build_trigger" {
  description = "Regional push trigger id."
  value       = try(google_cloudbuild_trigger.github_push[0].trigger_id, null)
}

output "runtime_secret_names" {
  description = "Add secret version values outside Terraform before enabling runtime resources."
  value = {
    for key, secret in google_secret_manager_secret.runtime : key => secret.secret_id
  }
}

output "web_service_account" {
  value = google_service_account.web.email
}

output "worker_service_account" {
  value = google_service_account.worker.email
}

output "synthetic_evaluation_worker_service_account" {
  value = try(google_service_account.synthetic_evaluation_worker[0].email, null)
}

output "service_uri" {
  description = "Cloud Run URL after the second apply."
  value       = try(google_cloud_run_v2_service.web[0].uri, null)
}

output "service_name" {
  description = "Cloud Run Service name after the second apply."
  value       = try(google_cloud_run_v2_service.web[0].name, null)
}

output "job_name" {
  description = "Cloud Run Job name after the second apply."
  value       = try(google_cloud_run_v2_job.worker[0].name, null)
}

output "synthetic_evaluation_job_name" {
  description = "Dedicated eval-only Cloud Run Job name when that capability is enabled."
  value       = try(google_cloud_run_v2_job.synthetic_evaluation_worker[0].name, null)
}

output "runtime_container_image" {
  description = "Immutable digest reference Terraform applies to both Service and Job."
  value       = var.enable_runtime_resources ? var.container_image : null
}
