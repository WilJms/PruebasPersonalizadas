output "artifact_registry_repository" {
  description = "Docker repository prefix for application images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.application.repository_id}"
}

output "cloud_build_service_account" {
  description = "Select this service account when creating the Cloud Build trigger."
  value       = google_service_account.build.email
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

output "service_uri" {
  description = "Cloud Run URL after the second apply."
  value       = try(google_cloud_run_v2_service.web[0].uri, null)
}

output "job_name" {
  description = "Cloud Run Job name after the second apply."
  value       = try(google_cloud_run_v2_job.worker[0].name, null)
}

output "runtime_container_image" {
  description = "Immutable digest reference Terraform applies to both Service and Job."
  value       = var.enable_runtime_resources ? var.container_image : null
}
