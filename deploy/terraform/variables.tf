variable "project_id" {
  description = "Google Cloud project that owns the experimental environment."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project id."
  }
}

variable "region" {
  description = "Single region used by Artifact Registry and Cloud Run."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix for Stage 1 resources."
  type        = string
  default     = "cva"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be a short lowercase resource prefix."
  }
}

variable "repository_id" {
  description = "Artifact Registry Docker repository id."
  type        = string
  default     = "comprehension-verification"
}

variable "service_name" {
  description = "Cloud Run Service name."
  type        = string
  default     = "cva-web"
}

variable "job_name" {
  description = "Cloud Run Job name."
  type        = string
  default     = "cva-worker"
}

variable "container_image" {
  description = "Immutable Artifact Registry image reference owned by Terraform, including @sha256 digest."
  type        = string
  default     = ""

  validation {
    condition = var.container_image == "" || can(regex(
      "^[a-z0-9][a-z0-9.-]*/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$",
      var.container_image,
    ))
    error_message = "container_image must be empty or an immutable registry reference ending in @sha256:<64 lowercase hex>."
  }
}

variable "enable_runtime_resources" {
  description = "Create Cloud Run resources after secret versions and an image exist."
  type        = bool
  default     = false
}

variable "allow_unauthenticated" {
  description = "Expose login/static routes; application authorization still protects private routes."
  type        = bool
  default     = true
}

variable "supabase_url" {
  description = "Public Supabase project URL."
  type        = string
  default     = ""
}

variable "supabase_publishable_key" {
  description = "Supabase publishable key. It is intentionally not a secret key."
  type        = string
  default     = ""
}

variable "supabase_jwt_audience" {
  description = "Expected audience for Supabase user JWTs."
  type        = string
  default     = "authenticated"
}

variable "r2_endpoint_url" {
  description = "Private Cloudflare R2 S3 endpoint URL."
  type        = string
  default     = ""
}

variable "r2_bucket_name" {
  description = "Existing private R2 bucket name."
  type        = string
  default     = ""
}

variable "secret_version" {
  description = "Pinned Secret Manager version used by Cloud Run. Add it manually before enabling runtime resources."
  type        = string
  default     = "1"

  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.secret_version))
    error_message = "secret_version must be a pinned positive numeric version."
  }
}

variable "upload_url_ttl_seconds" {
  description = "Maximum lifetime for a direct R2 upload URL."
  type        = number
  default     = 900

  validation {
    condition     = var.upload_url_ttl_seconds >= 60 && var.upload_url_ttl_seconds <= 3600
    error_message = "upload_url_ttl_seconds must be between 60 and 3600."
  }
}

variable "download_url_ttl_seconds" {
  description = "Maximum lifetime for a private R2 download URL."
  type        = number
  default     = 300

  validation {
    condition     = var.download_url_ttl_seconds >= 30 && var.download_url_ttl_seconds <= 900
    error_message = "download_url_ttl_seconds must be between 30 and 900."
  }
}

variable "web_min_instances" {
  description = "Minimum Cloud Run web instances. Zero keeps the experiment scale-to-zero."
  type        = number
  default     = 0
}

variable "web_max_instances" {
  description = "Maximum Cloud Run web instances during Stage 1."
  type        = number
  default     = 3
}

variable "labels" {
  description = "Additional labels applied to managed resources."
  type        = map(string)
  default     = {}
}
