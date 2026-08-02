"""Composition root shared by the Stage 1 API and Cloud Run Job worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .auth import AuthService
from .jobs import CloudRunJobRunner, InlineJobRunner, JobRunner
from .object_store import MemoryObjectStore, ObjectStore, R2ObjectStore
from .repository import Repository
from .settings import Settings
from .workflows import Stage1Service


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    repository: Repository
    object_store: ObjectStore
    auth: AuthService
    service: Stage1Service
    job_runner: JobRunner


def _prepare_local_database(settings: Settings) -> None:
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
    elif settings.job_runner_mode == "cloud_run":
        runner = CloudRunJobRunner(settings)
    else:
        runner = InlineJobRunner(
            service.process_job,
            wait_for_completion=inline_wait_for_completion,
        )
    service.set_job_runner(runner)
    auth = AuthService(settings, repo)
    auth.seed_local_users()
    return Runtime(
        settings=settings,
        repository=repo,
        object_store=store,
        auth=auth,
        service=service,
        job_runner=runner,
    )
