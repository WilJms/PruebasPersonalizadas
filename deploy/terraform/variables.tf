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

  validation {
    condition     = can(regex("^[a-z]+-[a-z0-9]+[0-9]+$", var.region))
    error_message = "region must be a concrete lowercase Google Cloud region."
  }
}

variable "name_prefix" {
  description = "Prefix for experimental resources."
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

  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{2,62}$", var.repository_id))
    error_message = "repository_id must be a valid lowercase Artifact Registry repository id."
  }
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

variable "synthetic_evaluation_job_name" {
  description = "Dedicated Cloud Run Job name for manually authorized synthetic evaluation only."
  type        = string
  default     = "cva-synthetic-eval"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,61}[a-z0-9]$", var.synthetic_evaluation_job_name))
    error_message = "synthetic_evaluation_job_name must be a valid lowercase Cloud Run Job name."
  }
}

variable "enable_cloud_build_connection" {
  description = "Create the regional GitHub connection. OAuth/GitHub App authorization is completed interactively after its first apply."
  type        = bool
  default     = false
}

variable "enable_cloud_build_trigger" {
  description = "Create the authorized repository and push trigger after the GitHub connection reaches COMPLETE."
  type        = bool
  default     = false
}

variable "github_app_installation_id" {
  description = "Cloud Build GitHub App installation id returned by the official authorization flow."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.github_app_installation_id == null || var.github_app_installation_id > 0
    error_message = "github_app_installation_id must be null or a positive installation id."
  }
}

variable "github_oauth_token_secret_version" {
  description = "Secret Manager version reference created by the official Cloud Build GitHub OAuth flow; never the token value."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.github_oauth_token_secret_version == null || can(regex(
      "^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]+/versions/(latest|[1-9][0-9]*)$",
      var.github_oauth_token_secret_version,
    ))
    error_message = "github_oauth_token_secret_version must be null or a Secret Manager version resource name."
  }
}

variable "container_image" {
  description = "Immutable application image from the configured regional Artifact Registry repository, including @sha256 digest."
  type        = string
  default     = ""

  validation {
    condition = var.container_image == "" || can(regex(
      "^${var.region}-docker\\.pkg\\.dev/${var.project_id}/${var.repository_id}/application@sha256:[0-9a-f]{64}$",
      var.container_image,
    ))
    error_message = "container_image must be empty or the immutable application@sha256 reference from the configured region, project, and repository."
  }
}

variable "enable_runtime_resources" {
  description = "Create Cloud Run resources after secret versions and an image exist."
  type        = bool
  default     = false
}

variable "enable_openai_secret_container" {
  description = "Create only the empty OpenAI API key Secret Manager container. The value is added out-of-band and never enters Terraform."
  type        = bool
  default     = false
}

variable "enable_synthetic_evaluation_provider" {
  description = "Expose only the post-claim synthetic evaluation capability. A matching append-only job authorization remains mandatory before secret resolution."
  type        = bool
  default     = false
}

variable "openai_api_key_secret_version" {
  description = "Pinned numeric version of the separately inserted OpenAI project API key. This is a version identifier, never the key value."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.openai_api_key_secret_version == null
      || can(regex("^[1-9][0-9]*$", var.openai_api_key_secret_version))
    )
    error_message = "openai_api_key_secret_version must be null or a pinned positive numeric version."
  }
}

variable "synthetic_evaluation_candidate_sha" {
  description = "Exact 40-character source SHA bound to every durable synthetic evaluation authorization."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.synthetic_evaluation_candidate_sha == null
      || can(regex("^[0-9a-f]{40}$", var.synthetic_evaluation_candidate_sha))
    )
    error_message = "synthetic_evaluation_candidate_sha must be null or an exact lowercase Git SHA."
  }
}

variable "synthetic_evaluation_max_requests" {
  description = "Infrastructure ceiling for a separately authorized synthetic job; the durable authorization may only reduce it."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition = (
      var.synthetic_evaluation_max_requests == null
      || (
        var.synthetic_evaluation_max_requests >= 1
        && var.synthetic_evaluation_max_requests <= 64
        && floor(var.synthetic_evaluation_max_requests) == var.synthetic_evaluation_max_requests
      )
    )
    error_message = "synthetic_evaluation_max_requests must be null or an integer from 1 through 64."
  }
}

variable "synthetic_evaluation_max_job_cost_usd" {
  description = "Infrastructure cost ceiling for a separately authorized synthetic job; the durable authorization may only reduce it."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition = (
      var.synthetic_evaluation_max_job_cost_usd == null
      || (var.synthetic_evaluation_max_job_cost_usd >= 0.01 && var.synthetic_evaluation_max_job_cost_usd <= 10.0)
    )
    error_message = "synthetic_evaluation_max_job_cost_usd must be null or between USD 0.01 and USD 10.00."
  }
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
  description = "Maximum Cloud Run web instances during the controlled experiment."
  type        = number
  default     = 3
}

variable "labels" {
  description = "Additional labels applied to managed resources."
  type        = map(string)
  default     = {}
}
