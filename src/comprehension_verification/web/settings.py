"""Validated experimental runtime settings with fail-closed cloud guards."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from ..model_gateway import OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS
from ..provider_authorization import validate_pinned_secret_resource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CVA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["test", "local", "cloud"] = "local"
    database_url: str = "sqlite+pysqlite:///./.local/stage1.db"
    auth_mode: Literal["local", "supabase"] = "local"
    object_store_mode: Literal["memory", "r2"] = "memory"
    job_runner_mode: Literal["inline", "cloud_run"] = "inline"
    model_mode: Literal["mock", "real"] = "mock"
    worker_model_mode: Literal["mock"] = "mock"
    p10_enabled: bool = False
    openai_api_key: SecretStr | None = None

    session_secret: str = Field(
        default="local-development-secret-change-me", min_length=32
    )
    session_cookie_name: str = "cva_session"
    csrf_cookie_name: str = "cva_csrf"
    session_ttl_seconds: int = Field(default=3600, ge=300, le=86_400)
    idempotency_ttl_seconds: int = Field(
        default=86_400,
        ge=300,
        le=604_800,
    )
    local_invited_emails: str = "teacher@example.test,assistant@example.test"
    local_workspace_id: str = "tnt_experimental"

    supabase_jwt_issuer: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwks_url: str | None = None

    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    upload_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    download_url_ttl_seconds: int = Field(default=300, ge=30, le=900)
    max_upload_bytes: int = Field(default=5_000_000, ge=1, le=25_000_000)
    max_job_cost_usd: float = Field(default=0.50, ge=0.01, le=10.0)
    max_batch_submissions: int = Field(default=50, ge=2, le=500)
    job_max_attempts: int = Field(default=3, ge=1, le=5)
    job_lease_seconds: int = Field(default=3900, ge=300, le=7200)
    api_read_rate_limit_per_minute: int = Field(default=240, ge=30, le=2_000)
    api_mutation_rate_limit_per_minute: int = Field(default=60, ge=10, le=500)
    require_libmagic: bool = False
    parser_timeout_seconds: int = Field(default=30, ge=5, le=120)

    gcp_project_id: str | None = None
    gcp_region: str | None = None
    cloud_run_job_name: str | None = None
    frontend_dist: str = "frontend/dist"

    @property
    def invited_emails(self) -> frozenset[str]:
        return frozenset(
            item.strip().lower()
            for item in self.local_invited_emails.split(",")
            if item.strip()
        )

    @model_validator(mode="after")
    def experimental_guards(self) -> "Settings":
        if self.p10_enabled:
            raise ValueError("P10 is disabled throughout the experimental environment")
        if self.openai_api_key and self.openai_api_key.get_secret_value().strip():
            raise ValueError("web runtime must not receive an OpenAI API key")
        if self.environment == "cloud":
            if self.auth_mode != "supabase":
                raise ValueError("cloud requires Supabase authentication")
            if self.object_store_mode != "r2":
                raise ValueError("cloud requires private R2 object storage")
            if self.job_runner_mode != "cloud_run":
                raise ValueError("cloud requires Cloud Run Jobs")
            if self.model_mode != "mock":
                raise ValueError("cloud experimental runtime requires the mock model gateway")
            if self.session_secret == "local-development-secret-change-me":
                raise ValueError("cloud requires a managed session secret")
            if not self.require_libmagic:
                raise ValueError("cloud experimental runtime requires libmagic MIME detection")
            try:
                database = make_url(self.database_url)
            except (ArgumentError, TypeError, ValueError) as exc:
                raise ValueError(
                    "cloud requires a complete postgresql+psycopg database URL"
                ) from exc
            if database.drivername != "postgresql+psycopg":
                raise ValueError("cloud requires the explicit PostgreSQL psycopg driver")
            if not all(
                (
                    database.username,
                    database.password,
                    database.host,
                    database.database,
                )
            ):
                raise ValueError(
                    "cloud requires a complete postgresql+psycopg database URL"
                )
        if self.auth_mode == "supabase" and not (
            self.supabase_jwt_issuer and self.supabase_jwks_url
        ):
            raise ValueError("Supabase auth requires issuer and JWKS URL")
        if self.object_store_mode == "r2" and not all(
            (
                self.r2_endpoint_url,
                self.r2_bucket,
                self.r2_access_key_id,
                self.r2_secret_access_key,
            )
        ):
            raise ValueError("R2 mode requires endpoint, bucket and scoped credentials")
        if self.job_runner_mode == "cloud_run" and not all(
            (self.gcp_project_id, self.gcp_region, self.cloud_run_job_name)
        ):
            raise ValueError("Cloud Run mode requires project, region and job name")
        return self


class WorkerSettings(BaseSettings):
    """Minimal settings surface consumed by the one-shot worker process.

    Authentication, browser sessions and Cloud Run dispatch belong to the web
    process.  Keeping those fields out of this model prevents the worker from
    reading a session secret even when that variable exists in its environment.
    """

    model_config = SettingsConfigDict(
        env_prefix="CVA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["test", "local", "cloud"] = "local"
    database_url: str = "sqlite+pysqlite:///./.local/stage1-worker.db"
    object_store_mode: Literal["memory", "r2"] = "memory"
    model_mode: Literal["mock", "real"] = "mock"
    p10_enabled: bool = False
    claim_job_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_-]{2,127}$"
    )
    openai_secret_version_resource: str | None = None
    synthetic_evaluation_candidate_sha: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{40}$",
    )
    synthetic_evaluation_max_requests: int = Field(default=32, ge=1, le=64)
    openai_request_timeout_seconds: float = Field(
        default=OPENAI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ge=5.0,
        le=300.0,
    )

    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    upload_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    download_url_ttl_seconds: int = Field(default=300, ge=30, le=900)
    max_upload_bytes: int = Field(default=5_000_000, ge=1, le=25_000_000)
    max_job_cost_usd: float = Field(default=0.50, ge=0.01, le=10.0)
    job_max_attempts: int = Field(default=3, ge=1, le=5)
    job_lease_seconds: int = Field(default=3900, ge=300, le=7200)
    require_libmagic: bool = False
    parser_timeout_seconds: int = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def experimental_worker_guards(self) -> "WorkerSettings":
        if self.p10_enabled:
            raise ValueError("P10 is disabled throughout the experimental environment")
        if self.model_mode == "real":
            if self.claim_job_id is None:
                raise ValueError(
                    "synthetic evaluation mode requires the exact dispatched claim job ID"
                )
            if self.openai_secret_version_resource is None:
                raise ValueError(
                    "synthetic evaluation mode requires a pinned secret resource"
                )
            validate_pinned_secret_resource(self.openai_secret_version_resource)
            if self.synthetic_evaluation_candidate_sha is None:
                raise ValueError(
                    "synthetic evaluation mode requires an exact candidate SHA"
                )
        elif any(
            value is not None
            for value in (
                self.openai_secret_version_resource,
                self.synthetic_evaluation_candidate_sha,
            )
        ):
            raise ValueError(
                "mock worker mode must not receive synthetic provider capability metadata"
            )
        if self.environment == "cloud":
            if self.claim_job_id is None:
                raise ValueError(
                    "cloud worker requires the exact dispatched claim job ID"
                )
            if self.object_store_mode != "r2":
                raise ValueError("cloud worker requires private R2 object storage")
            try:
                database = make_url(self.database_url)
            except (ArgumentError, TypeError, ValueError) as exc:
                raise ValueError(
                    "cloud worker requires a complete postgresql+psycopg database URL"
                ) from exc
            if database.drivername != "postgresql+psycopg":
                raise ValueError(
                    "cloud worker requires the explicit PostgreSQL psycopg driver"
                )
            if not all(
                (
                    database.username,
                    database.password,
                    database.host,
                    database.database,
                )
            ):
                raise ValueError(
                    "cloud worker requires a complete postgresql+psycopg database URL"
                )
            if not self.require_libmagic:
                raise ValueError("cloud experimental worker requires libmagic MIME detection")
        if self.object_store_mode == "r2" and not all(
            (
                self.r2_endpoint_url,
                self.r2_bucket,
                self.r2_access_key_id,
                self.r2_secret_access_key,
            )
        ):
            raise ValueError(
                "R2 worker mode requires endpoint, bucket and scoped credentials"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
