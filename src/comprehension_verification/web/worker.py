"""Single-run Cloud Run Job entrypoint for the oldest durable queued job."""

from __future__ import annotations

import asyncio

from .runtime import build_worker_runtime
from .settings import get_worker_settings


async def run_once() -> int:
    settings = get_worker_settings()
    runtime = build_worker_runtime(settings)
    claimed = runtime.repository.claim_next_job(
        lease_seconds=getattr(settings, "job_lease_seconds", 3900)
    )
    if claimed is None:
        return 0
    await runtime.service.process_job(claimed.id)
    status = runtime.repository.job_status(claimed.id, claimed.tenant_id)
    return 1 if status.status == "FAILED" else 0


def main() -> int:
    return asyncio.run(run_once())


if __name__ == "__main__":
    raise SystemExit(main())
