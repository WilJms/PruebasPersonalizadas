"""Durable job dispatch seam for inline tests and Cloud Run Jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import google.auth
from google.auth.transport.requests import AuthorizedSession

from .settings import Settings


class JobRunner(Protocol):
    async def dispatch(self, job_id: str) -> str | None: ...


@dataclass(slots=True)
class RecordingJobRunner:
    """Fake that proves a durable row existed before dispatch."""

    assert_persisted: Callable[[str], None] | None = None
    dispatched: list[str] | None = None

    def __post_init__(self) -> None:
        if self.dispatched is None:
            self.dispatched = []

    async def dispatch(self, job_id: str) -> str:
        if self.assert_persisted is not None:
            self.assert_persisted(job_id)
        assert self.dispatched is not None
        self.dispatched.append(job_id)
        return f"fake-execution/{job_id}"


class InlineJobRunner:
    """Development/test runner; never selected by validated cloud settings."""

    def __init__(
        self,
        processor: Callable[[str], Awaitable[None]],
        *,
        wait_for_completion: bool = False,
    ) -> None:
        self.processor = processor
        self.wait_for_completion = wait_for_completion
        self.tasks: set[asyncio.Task[None]] = set()

    async def dispatch(self, job_id: str) -> str:
        if self.wait_for_completion:
            await self.processor(job_id)
        else:
            task = asyncio.create_task(self.processor(job_id), name=f"job:{job_id}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return f"inline/{job_id}"


class CloudRunJobRunner:
    """Executes the configured Cloud Run Job without sensitive overrides.

    The worker claims the oldest durable QUEUED row. The API therefore cannot
    leak subject references, paths, or content through execution parameters.
    """

    def __init__(self, settings: Settings) -> None:
        assert settings.gcp_project_id and settings.gcp_region and settings.cloud_run_job_name
        self.endpoint = (
            "https://run.googleapis.com/v2/projects/"
            f"{settings.gcp_project_id}/locations/{settings.gcp_region}/jobs/"
            f"{settings.cloud_run_job_name}:run"
        )

    async def dispatch(self, job_id: str) -> str | None:
        del job_id  # Deliberately not transmitted; the worker claims a DB row.
        return await asyncio.to_thread(self._dispatch_sync)

    def _dispatch_sync(self) -> str | None:
        credentials, _project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        session = AuthorizedSession(credentials)
        response = session.post(self.endpoint, json={}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        return payload.get("name")

