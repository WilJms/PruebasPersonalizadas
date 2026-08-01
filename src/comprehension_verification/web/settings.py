"""Validated Stage 1 runtime settings with fail-closed cloud guards."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CVA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["test", "local", "cloud"] = "local"
    database_url: str = "sqlite+pysqlite:///./.local/stage1.db"
    auth_mode: Literal["local", "supabase"] = "local"
    object_store_mode: Literal["memory", "r2"] = "memory"
    job_runner_mode: Literal["inline", "cloud_run"] = "inline"
    model_mode: Literal["mock", "real"] = "mock"
    p10_enabled: bool = False

    session_secret: str = Field(
        default="local-development-secret-change-me", min_length=32
    )
    session_cookie_name: str = "cva_session"
    csrf_cookie_name: str = "cva_csrf"
    session_ttl_seconds: int = Field(default=3600, ge=300, le=86_400)
    local_invited_emails: str = "teacher@example.test,assistant@example.test"
    local_workspace_id: str = "tnt_experimental"

    supabase_jwt_issuer: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwks_url: str | None = None

    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    signed_url_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    max_upload_bytes: int = Field(default=5_000_000, ge=1, le=25_000_000)

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
    def stage_one_guards(self) -> "Settings":
        if self.p10_enabled:
            raise ValueError("P10 is disabled throughout Stage 1")
        if self.environment == "cloud":
            if self.auth_mode != "supabase":
                raise ValueError("cloud requires Supabase authentication")
            if self.object_store_mode != "r2":
                raise ValueError("cloud requires private R2 object storage")
            if self.job_runner_mode != "cloud_run":
                raise ValueError("cloud requires Cloud Run Jobs")
            if self.session_secret == "local-development-secret-change-me":
                raise ValueError("cloud requires a managed session secret")
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
