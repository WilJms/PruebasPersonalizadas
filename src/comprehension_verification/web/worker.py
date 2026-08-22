"""Single-run Cloud Run Job entrypoint for the oldest durable queued job."""

from __future__ import annotations

import asyncio

from ..model_gateway import LUNA_MODEL_ID, OPENAI_ROUTE_PROFILE_ID
from ..provider_authorization import synthetic_provider_boundary_hash
from .provider_secrets import (
    ProviderCredentialUnavailable,
    resolve_openai_api_key,
)
from .runtime import build_worker_bootstrap_runtime, build_worker_runtime
from .settings import get_worker_settings


_PROVIDER_FREE_JOB_KINDS = frozenset(
    {"BLUEPRINT_PREFLIGHT", "BLUEPRINT_REVIEW"}
)


async def run_once() -> int:
    settings = get_worker_settings()
    bootstrap = build_worker_bootstrap_runtime(settings)
    lease_seconds = getattr(settings, "job_lease_seconds", 3900)
    claim_job_id = getattr(settings, "claim_job_id", None)
    claimed = (
        bootstrap.repository.claim_job(
            claim_job_id, lease_seconds=lease_seconds
        )
        if claim_job_id is not None
        else bootstrap.repository.claim_next_job(lease_seconds=lease_seconds)
    )
    if claimed is None:
        return 0
    provider_grant = None
    api_key = None
    runtime_settings = settings
    if settings.model_mode == "real" and claimed.kind in _PROVIDER_FREE_JOB_KINDS:
        runtime_settings = type(settings).model_validate(
            {
                **settings.model_dump(),
                "model_mode": "mock",
                "openai_secret_version_resource": None,
                "synthetic_evaluation_candidate_sha": None,
            }
        )
    elif settings.model_mode == "real":
        assert settings.synthetic_evaluation_candidate_sha is not None
        assert settings.openai_secret_version_resource is not None
        try:
            provider_grant = (
                bootstrap.repository.consume_synthetic_provider_authorization(
                    job_id=claimed.id,
                    candidate_sha=settings.synthetic_evaluation_candidate_sha,
                    boundary_hash=synthetic_provider_boundary_hash(),
                    route_profile=OPENAI_ROUTE_PROFILE_ID,
                    model=LUNA_MODEL_ID,
                    secret_version_resource=(
                        settings.openai_secret_version_resource
                    ),
                    maximum_requests=(
                        settings.synthetic_evaluation_max_requests
                    ),
                    maximum_cost_usd=settings.max_job_cost_usd,
                )
            )
        except Exception as exc:
            bootstrap.repository.fail_claimed_job_security(
                job_id=claimed.id,
                code=str(exc),
            )
            return 1
        try:
            api_key = resolve_openai_api_key(
                provider_grant.secret_version_resource
            )
        except ProviderCredentialUnavailable as exc:
            bootstrap.repository.fail_claimed_job_security(
                job_id=claimed.id,
                code=exc.code,
            )
            return 1
    runtime = build_worker_runtime(
        runtime_settings,
        repository=bootstrap.repository,
        object_store=bootstrap.object_store,
        provider_grant=provider_grant,
        api_key=api_key,
    )
    await runtime.service.process_job(claimed.id)
    status = runtime.repository.job_status(claimed.id, claimed.tenant_id)
    return 1 if status.status == "FAILED" else 0


def main() -> int:
    return asyncio.run(run_once())


if __name__ == "__main__":
    raise SystemExit(main())
