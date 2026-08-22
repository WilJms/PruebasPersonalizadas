#!/usr/bin/env python3
"""Create one content-free, append-only synthetic provider authorization."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os

from comprehension_verification.provider_authorization import (
    SyntheticProviderAuthorizationSpec,
    synthetic_provider_boundary_hash,
)
from comprehension_verification.web.repository import JobRow, Repository


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Authorize one already durable synthetic job. This does not dispatch "
            "the job, resolve a key, or create provider transport."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CVA_DATABASE_URL"),
        help="Explicit postgresql+psycopg URL; defaults to CVA_DATABASE_URL.",
    )
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--secret-version-resource", required=True)
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument(
        "--expires-in-minutes",
        type=int,
        default=30,
        choices=range(5, 61),
        metavar="5..60",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.database_url or not args.database_url.startswith(
        "postgresql+psycopg://"
    ):
        raise SystemExit("a complete postgresql+psycopg database URL is required")
    repository = Repository(args.database_url, create_schema=False)
    job = repository.get(JobRow, args.job_id)
    if not isinstance(job, JobRow):
        raise SystemExit("job not found")
    now = datetime.now(UTC)
    spec = SyntheticProviderAuthorizationSpec(
        authorization_id=args.authorization_id,
        tenant_id=job.tenant_id,
        job_id=job.id,
        job_kind=job.kind,
        aggregate_id=job.aggregate_id,
        expected_claim_attempt=job.attempt + 1,
        artifact_hashes=repository.synthetic_artifact_hashes_for_job(job.id),
        candidate_sha=args.candidate_sha,
        boundary_hash=synthetic_provider_boundary_hash(),
        secret_version_resource=args.secret_version_resource,
        max_requests=args.max_requests,
        max_cost_usd=args.max_cost_usd,
        expires_at=now + timedelta(minutes=args.expires_in_minutes),
        created_by=args.created_by,
    )
    repository.authorize_synthetic_provider_job(spec)
    print(
        json.dumps(
            {
                "status": "AUTHORIZED",
                "classification": spec.classification,
                "authorization_id": spec.authorization_id,
                "authorization_hash": spec.authorization_hash,
                "job_id": spec.job_id,
                "candidate_sha": spec.candidate_sha,
                "boundary_hash": spec.boundary_hash,
                "artifact_hash_count": len(spec.artifact_hashes),
                "max_requests": spec.max_requests,
                "max_cost_usd": spec.max_cost_usd,
                "expires_at": spec.expires_at.isoformat().replace("+00:00", "Z"),
                "key_resolved": False,
                "transport_constructed": False,
                "provider_requests": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
