"""Durable job dispatch seam for inline, manual, and Cloud Run execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import re
from typing import Protocol

import google.auth
from google.auth.transport.requests import AuthorizedSession

from .settings import Settings


_CANONICAL_JOB_ID = re.compile(r"[a-z][a-z0-9_-]{2,127}")


def _validate_job_id(job_id: str) -> str:
    if _CANONICAL_JOB_ID.fullmatch(job_id) is None:
        raise ValueError("job_id is not a canonical opaque identifier")
    return job_id


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


class ManualJobRunner:
    """Local-only dispatcher that leaves an already durable job queued."""

    async def dispatch(self, job_id: str) -> str:
        canonical_job_id = _validate_job_id(job_id)
        return f"manual/{canonical_job_id}"


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
    """Execute the configured Cloud Run Job for one exact durable row.

    Only the opaque canonical job ID crosses the control-plane boundary.  No
    subject reference, path, document content, or provider credential is sent.
    """

    def __init__(self, settings: Settings) -> None:
        assert settings.gcp_project_id and settings.gcp_region and settings.cloud_run_job_name
        self.endpoint = (
            "https://run.googleapis.com/v2/projects/"
            f"{settings.gcp_project_id}/locations/{settings.gcp_region}/jobs/"
            f"{settings.cloud_run_job_name}:run"
        )

    async def dispatch(self, job_id: str) -> str | None:
        _validate_job_id(job_id)
        return await asyncio.to_thread(self._dispatch_sync, job_id)

    def _dispatch_sync(self, job_id: str) -> str | None:
        credentials, _project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        session = AuthorizedSession(credentials)
        response = session.post(
            self.endpoint,
            json={
                "overrides": {
                    "taskCount": 1,
                    "containerOverrides": [
                        {
                            "env": [
                                {
                                    "name": "CVA_CLAIM_JOB_ID",
                                    "value": job_id,
                                }
                            ]
                        }
                    ],
                }
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("name")
