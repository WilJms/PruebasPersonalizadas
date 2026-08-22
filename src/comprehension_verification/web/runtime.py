"""Separate composition roots for the Stage 2 API and one-shot worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import SecretStr

from .auth import AuthService
from ..model_gateway import (
    GatewayConfig,
    GatewayMode,
    ModelGateway,
    OpenAIAdapterConfig,
    OpenAIResponsesAdapter,
    RequestCappedAdapter,
    OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS,
    OPENAI_ROUTE_PROFILE_MAX_TRANSIENT_RETRIES,
    build_openai_cost_estimator,
    build_openai_routes,
    estimate_openai_input_tokens,
)
from ..provider_authorization import (
    SyntheticProviderGrant,
    synthetic_provider_boundary_hash,
)
from ..parsers import harden_parent_process
from .jobs import CloudRunJobRunner, InlineJobRunner, JobRunner, ManualJobRunner
from .object_store import MemoryObjectStore, ObjectStore, R2ObjectStore
from .repository import Repository
from .settings import Settings, WorkerSettings
from .stage2 import Stage2Service
from .workflows import Stage1Service


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    repository: Repository
    object_store: ObjectStore
    auth: AuthService
    service: Stage1Service
    stage2: Stage2Service
    job_runner: JobRunner


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    settings: WorkerSettings
    repository: Repository
    object_store: ObjectStore
    service: Stage1Service


@dataclass(frozen=True, slots=True)
class WorkerBootstrapRuntime:
    """Credential-free foundation used to claim and attest one exact job."""

    settings: WorkerSettings
    repository: Repository
    object_store: ObjectStore


def _prepare_local_database(settings: Settings | WorkerSettings) -> None:
    prefix = "sqlite+pysqlite:///"
    if not settings.database_url.startswith(prefix):
        return
    value = settings.database_url.removeprefix(prefix)
    if value in {"", ":memory:"}:
        return
    Path(value).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def build_runtime(
    settings: Settings,
    *,
    repository: Repository | None = None,
    object_store: ObjectStore | None = None,
    job_runner: JobRunner | None = None,
    inline_wait_for_completion: bool = False,
) -> Runtime:
    """Build adapters with cloud modes enforced by validated ``Settings``."""

    _prepare_local_database(settings)
    if settings.environment == "cloud":
        harden_parent_process()
    repo = repository or Repository(
        settings.database_url,
        # Cloud schema changes are a controlled migration step, never app boot.
        create_schema=settings.environment != "cloud",
    )
    store: ObjectStore
    if object_store is not None:
        store = object_store
    elif settings.object_store_mode == "r2":
        store = R2ObjectStore(settings)
    else:
        store = MemoryObjectStore(
            secret=settings.session_secret,
            upload_ttl_seconds=settings.upload_url_ttl_seconds,
            download_ttl_seconds=settings.download_url_ttl_seconds,
        )

    service = Stage1Service(settings=settings, repository=repo, object_store=store)
    if job_runner is not None:
        runner = job_runner
    elif settings.job_runner_mode == "inline":
        runner = InlineJobRunner(
            service.process_job,
            wait_for_completion=inline_wait_for_completion,
        )
    elif settings.job_runner_mode == "manual":
        runner = ManualJobRunner()
    elif settings.job_runner_mode == "cloud_run":
        runner = CloudRunJobRunner(settings)
    else:  # pragma: no cover - Settings validates the closed literal set.
        raise ValueError(
            f"unsupported job runner mode: {settings.job_runner_mode}"
        )
    service.set_job_runner(runner)
    stage2 = Stage2Service(service)
    service.set_question_action_processor(stage2.process_question_action_job)
    auth = AuthService(settings, repo)
    auth.seed_local_users()
    return Runtime(
        settings=settings,
        repository=repo,
        object_store=store,
        auth=auth,
        service=service,
        stage2=stage2,
        job_runner=runner,
    )


def build_worker_bootstrap_runtime(
    settings: WorkerSettings,
    *,
    repository: Repository | None = None,
    object_store: ObjectStore | None = None,
) -> WorkerBootstrapRuntime:
    """Build storage only; this path cannot resolve or construct a provider."""

    _prepare_local_database(settings)
    if settings.environment == "cloud":
        harden_parent_process()
    repo = repository or Repository(
        settings.database_url,
        # Cloud schema changes are a controlled migration step, never job boot.
        create_schema=settings.environment != "cloud",
    )
    if object_store is not None:
        store = object_store
    elif settings.object_store_mode == "r2":
        store = R2ObjectStore(settings)
    else:
        # A memory store is development-only and cannot be shared across
        # processes.  It deliberately has a capability key unrelated to web
        # authentication or browser sessions.
        store = MemoryObjectStore(
            secret="worker-local-memory-capability-secret-change-me",
            upload_ttl_seconds=settings.upload_url_ttl_seconds,
            download_ttl_seconds=settings.download_url_ttl_seconds,
        )
    return WorkerBootstrapRuntime(
        settings=settings,
        repository=repo,
        object_store=store,
    )


def build_worker_runtime(
    settings: WorkerSettings,
    *,
    repository: Repository | None = None,
    object_store: ObjectStore | None = None,
    provider_grant: SyntheticProviderGrant | None = None,
    api_key: SecretStr | None = None,
    openai_adapter_factory: Callable[..., OpenAIResponsesAdapter] = (
        OpenAIResponsesAdapter
    ),
) -> WorkerRuntime:
    """Build processing adapters after the synthetic claim gate, if required."""

    foundation = build_worker_bootstrap_runtime(
        settings,
        repository=repository,
        object_store=object_store,
    )
    repo = foundation.repository
    store = foundation.object_store
    effective_settings = settings

    gateway_factory = None
    if settings.model_mode == "real":
        if provider_grant is None or api_key is None:
            raise ValueError(
                "real provider construction requires a consumed synthetic job grant"
            )
        if (
            settings.claim_job_id is None
            or settings.openai_secret_version_resource is None
            or settings.synthetic_evaluation_candidate_sha is None
            or provider_grant.job_id != settings.claim_job_id
            or provider_grant.candidate_sha
            != settings.synthetic_evaluation_candidate_sha
            or provider_grant.boundary_hash != synthetic_provider_boundary_hash()
            or provider_grant.secret_version_resource
            != settings.openai_secret_version_resource
            or provider_grant.max_requests
            > settings.synthetic_evaluation_max_requests
            or provider_grant.max_cost_usd > settings.max_job_cost_usd
        ):
            raise ValueError("synthetic provider grant does not match worker boundary")
        effective_settings = settings.model_copy(
            update={"max_job_cost_usd": provider_grant.max_cost_usd}
        )
        routes = build_openai_routes(max_call_cost_usd=provider_grant.max_cost_usd)
        adapter = RequestCappedAdapter(
            openai_adapter_factory(
                api_key=api_key,
                config=OpenAIAdapterConfig(
                    request_timeout_seconds=settings.openai_request_timeout_seconds
                ),
            ),
            max_requests=provider_grant.max_requests,
        )
        cost_estimator = build_openai_cost_estimator(routes)

        def real_gateway(job_id: str) -> ModelGateway:
            if job_id != provider_grant.job_id:
                raise ValueError("synthetic provider grant cannot cross job scope")
            return ModelGateway(
                GatewayConfig(
                    mode=GatewayMode.REAL,
                    job_id=job_id,
                    timeout_seconds=(
                        settings.openai_request_timeout_seconds
                        + OPENAI_GATEWAY_TIMEOUT_GRACE_SECONDS
                    ),
                    max_retries=OPENAI_ROUTE_PROFILE_MAX_TRANSIENT_RETRIES,
                    default_budget_usd=provider_grant.max_cost_usd,
                ),
                real_routes=routes,
                adapters={"openai": adapter},
                ledger_sink=repo.model_call_sink,
                cost_estimator=cost_estimator,
                input_token_estimator=estimate_openai_input_tokens,
            )

        gateway_factory = real_gateway

    service = Stage1Service(
        settings=effective_settings,
        repository=repo,
        object_store=store,
        gateway_factory=gateway_factory,
        provider_grant=provider_grant,
    )
    stage2 = Stage2Service(service)
    service.set_question_action_processor(stage2.process_question_action_job)
    return WorkerRuntime(
        settings=effective_settings,
        repository=repo,
        object_store=store,
        service=service,
    )
