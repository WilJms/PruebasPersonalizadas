from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.model_gateway import (
    LUNA_MODEL_ID,
    OPENAI_ROUTE_PROFILE_ID,
)
from comprehension_verification.provider_authorization import (
    SyntheticProviderAuthorizationSpec,
    synthetic_provider_boundary_hash,
)
from comprehension_verification.web.repository import (
    ActivityRow,
    ArtifactRow,
    AuditEventRow,
    Conflict,
    IdempotencyRow,
    JobRow,
    ModelCallRow,
    NotFound,
    Repository,
    SyntheticProviderAuthorizationRow,
    SyntheticProviderClaimRow,
)


@pytest.fixture(scope="module")
def postgres_repository() -> Repository:
    raw_url = os.environ.get("CVA_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("CVA_TEST_DATABASE_URL is required for PostgreSQL semantics")
    database_url = raw_url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    repository = Repository(database_url, create_schema=False)
    if repository.engine.dialect.name != "postgresql":
        pytest.fail("PostgreSQL-sensitive tests require a PostgreSQL database")
    repository.check_readiness()
    return repository


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def test_postgres_idempotency_reservation_is_durable_and_unique(
    postgres_repository: Repository,
) -> None:
    tenant_id = _id("tnt_idem")
    key = _id("key")
    fingerprint = "sha256:" + "a" * 64

    assert postgres_repository.reserve_idempotency(tenant_id, key, fingerprint) is None
    with pytest.raises(Conflict, match="IDEMPOTENCY_REQUEST_IN_PROGRESS"):
        postgres_repository.reserve_idempotency(tenant_id, key, fingerprint)

    descriptor = {"kind": "activity", "activity_id": _id("act")}
    postgres_repository.complete_idempotency(
        tenant_id, key, fingerprint, descriptor
    )
    assert (
        postgres_repository.reserve_idempotency(tenant_id, key, fingerprint)
        == descriptor
    )
    with pytest.raises(Conflict, match="IDEMPOTENCY_KEY_REUSED"):
        postgres_repository.reserve_idempotency(
            tenant_id, key, "sha256:" + "b" * 64
        )

    sql_null_key = _id("key_sql_null")
    assert (
        postgres_repository.reserve_idempotency(
            tenant_id, sql_null_key, fingerprint
        )
        is None
    )
    postgres_repository.release_idempotency(
        tenant_id, sql_null_key, fingerprint
    )
    with postgres_repository.session() as session:
        assert session.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.tenant_id == tenant_id,
                IdempotencyRow.key == sql_null_key,
            )
        ) is None

    legacy_json_null_key = _id("key_json_null")
    assert (
        postgres_repository.reserve_idempotency(
            tenant_id, legacy_json_null_key, fingerprint
        )
        is None
    )
    with pytest.raises(IntegrityError):
        with postgres_repository.session() as session:
            session.execute(
                update(IdempotencyRow)
                .where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == legacy_json_null_key,
                )
                .values(response=text("'null'::jsonb"))
            )
    postgres_repository.release_idempotency(
        tenant_id, legacy_json_null_key, fingerprint
    )
    with postgres_repository.session() as session:
        assert session.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.tenant_id == tenant_id,
                IdempotencyRow.key == legacy_json_null_key,
            )
        ) is None

    unsafe_key = _id("key_unsafe_capability")
    assert (
        postgres_repository.reserve_idempotency(
            tenant_id, unsafe_key, fingerprint
        )
        is None
    )
    with pytest.raises(IntegrityError):
        with postgres_repository.session() as session:
            session.execute(
                update(IdempotencyRow)
                .where(
                    IdempotencyRow.tenant_id == tenant_id,
                    IdempotencyRow.key == unsafe_key,
                )
                .values(
                    response={
                        "kind": "json",
                        "body": {
                            "view_url": "https://synthetic.invalid/object"
                            "?X-Amz-Signature=synthetic"
                        },
                    }
                )
            )
    postgres_repository.release_idempotency(
        tenant_id, unsafe_key, fingerprint
    )
    with postgres_repository.session() as session:
        assert session.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.tenant_id == tenant_id,
                IdempotencyRow.key == unsafe_key,
            )
        ) is None


def test_postgres_artifact_scope_uniqueness_is_enforced(
    postgres_repository: Repository,
) -> None:
    tenant_id = _id("tnt_unique")
    activity_id = _id("act_unique")
    common = {
        "tenant_id": tenant_id,
        "activity_id": activity_id,
        "submission_id": None,
        "scope_key": "activity",
        "role": "ASSIGNMENT_PROMPT",
        "filename": "assignment.md",
        "declared_media_type": "text/markdown",
        "expected_byte_size": 4,
        "status": "PENDING",
        "upload_expires_at": datetime.now(UTC),
    }
    postgres_repository.add(
        ArtifactRow(
            id=_id("art"),
            object_key=_id("raw"),
            **common,
        )
    )
    with pytest.raises(IntegrityError):
        postgres_repository.add(
            ArtifactRow(
                id=_id("art"),
                object_key=_id("raw"),
                **common,
            )
        )


def test_postgres_claim_skips_a_locked_job_and_claims_only_one(
    postgres_repository: Repository,
) -> None:
    tenant_id = _id("tnt_claim")
    first_id = _id("job_a")
    second_id = _id("job_b")
    created_at = datetime.now(UTC)
    with postgres_repository.session() as session:
        session.add_all(
            [
                JobRow(
                    id=first_id,
                    tenant_id=tenant_id,
                    kind="ACTIVITY",
                    aggregate_id=_id("aggregate"),
                    stage="QUEUED",
                    status="QUEUED",
                    created_at=created_at,
                ),
                JobRow(
                    id=second_id,
                    tenant_id=tenant_id,
                    kind="ACTIVITY",
                    aggregate_id=_id("aggregate"),
                    stage="QUEUED",
                    status="QUEUED",
                    created_at=created_at,
                ),
            ]
        )

    ordered_ids = sorted((first_id, second_id))
    with postgres_repository.sessions() as locking_session:
        locked = locking_session.scalar(
            select(JobRow)
            .where(JobRow.id == ordered_ids[0])
            .with_for_update()
        )
        assert locked is not None

        independent = Repository(
            postgres_repository.engine.url.render_as_string(hide_password=False),
            create_schema=False,
        )
        claimed = independent.claim_next_job()
        assert claimed is not None
        assert claimed.id == ordered_ids[1]
        locking_session.rollback()

    first = postgres_repository.job_status(ordered_ids[0], tenant_id)
    second = postgres_repository.job_status(ordered_ids[1], tenant_id)
    assert first.status == "QUEUED"
    assert first.attempt == 0
    assert second.status == "RUNNING"
    assert second.attempt == 1
    with postgres_repository.session() as session:
        session.execute(
            update(JobRow)
            .where(JobRow.id.in_(ordered_ids))
            .values(status="SUCCEEDED", stage="TEST_CLEANUP")
        )


def test_postgres_stage_keys_are_replayed_and_tenant_bound(
    postgres_repository: Repository,
) -> None:
    job_id = _id("job_stage")
    tenant_id = _id("tnt_stage")
    arguments = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "stage": "P01_ACTIVITY_SPEC_V1",
        "inputs": {"artifact": "sha256:" + "c" * 64},
        "component_version": "test-v1",
        "policy_hash": "sha256:" + "d" * 64,
        "output": {"status": "READY"},
    }
    first, replayed_first = postgres_repository.save_stage(**arguments)
    second, replayed_second = postgres_repository.save_stage(**arguments)
    other_tenant, replayed_other = postgres_repository.save_stage(
        **{**arguments, "tenant_id": _id("tnt_stage_other")}
    )

    assert replayed_first is False
    assert replayed_second is True
    assert second.id == first.id
    assert replayed_other is False
    assert other_tenant.stage_key != first.stage_key


def test_postgres_activity_etag_compare_and_swap_rejects_stale_write(
    postgres_repository: Repository,
) -> None:
    tenant_id = _id("tnt_cas")
    activity_id = _id("act_cas")
    original_config = {"title": "original", "question_count": 1}
    postgres_repository.add(
        ActivityRow(
            id=activity_id,
            tenant_id=tenant_id,
            status="DRAFT",
            config=original_config,
            blueprint_policy={"context_mode": "CLOSED"},
            created_by=_id("user"),
        )
    )
    original_etag = f'"{canonical_hash(original_config)}"'
    postgres_repository.update_activity_config(
        activity_id=activity_id,
        tenant_id=tenant_id,
        config={"title": "first writer", "question_count": 1},
        blueprint_policy={"context_mode": "CLOSED"},
        expected_etag=original_etag,
    )

    with pytest.raises(Conflict, match="ETAG_MISMATCH"):
        postgres_repository.update_activity_config(
            activity_id=activity_id,
            tenant_id=tenant_id,
            config={"title": "stale writer", "question_count": 1},
            blueprint_policy={"context_mode": "CLOSED"},
            expected_etag=original_etag,
        )


def test_postgres_repository_hides_cross_tenant_rows(
    postgres_repository: Repository,
) -> None:
    job_id = _id("job_tenant")
    postgres_repository.add(
        JobRow(
            id=job_id,
            tenant_id=_id("tnt_owner"),
            kind="ACTIVITY",
            aggregate_id=_id("aggregate"),
            stage="QUEUED",
            status="QUEUED",
        )
    )
    with pytest.raises(NotFound, match="not found"):
        postgres_repository.scoped(JobRow, job_id, _id("tnt_other"))
    with postgres_repository.session() as session:
        session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(status="SUCCEEDED", stage="TEST_CLEANUP")
        )


def test_postgres_model_calls_and_audit_events_are_append_only(
    postgres_repository: Repository,
) -> None:
    tenant_id = _id("tnt_append")
    model_call_id = _id("call")
    audit_event_id = _id("event")
    postgres_repository.add(
        ModelCallRow(
            id=model_call_id,
            tenant_id=tenant_id,
            job_id=_id("job"),
            stage="P01_ACTIVITY_SPEC_V1",
            data={"result": "SUCCEEDED"},
        )
    )
    postgres_repository.add(
        AuditEventRow(
            id=audit_event_id,
            tenant_id=tenant_id,
            event_type="test.append_only",
            aggregate_id=_id("aggregate"),
            actor_id=_id("actor"),
            payload={"safe": True},
        )
    )

    with pytest.raises(DBAPIError):
        with postgres_repository.session() as session:
            session.execute(
                update(ModelCallRow)
                .where(ModelCallRow.id == model_call_id)
                .values(stage="MUTATED")
            )
    with pytest.raises(DBAPIError):
        with postgres_repository.session() as session:
            session.execute(
                delete(AuditEventRow).where(AuditEventRow.id == audit_event_id)
            )

    assert postgres_repository.get(ModelCallRow, model_call_id)
    assert postgres_repository.get(AuditEventRow, audit_event_id)


def test_postgres_synthetic_provider_authorization_is_exactly_once_and_append_only(
    postgres_repository: Repository,
) -> None:
    tenant_id = _id("tnt_synthetic")
    activity_id = _id("act_synthetic")
    artifact_id = _id("art_synthetic")
    job_id = _id("job_synthetic")
    authorization_id = _id("authorization_synthetic")
    artifact_hash = "sha256:" + "a" * 64
    candidate_sha = "b" * 40
    boundary_hash = synthetic_provider_boundary_hash()
    secret_resource = (
        "projects/test-project/secrets/openai-key/versions/1"
    )
    postgres_repository.add(
        ActivityRow(
            id=activity_id,
            tenant_id=tenant_id,
            status="DRAFT",
            config={},
            blueprint_policy={},
            created_by=_id("operator"),
        )
    )
    postgres_repository.add(
        ArtifactRow(
            id=artifact_id,
            tenant_id=tenant_id,
            activity_id=activity_id,
            submission_id=None,
            scope_key=activity_id,
            role="ASSIGNMENT_PROMPT",
            filename="synthetic.md",
            object_key=f"synthetic/{artifact_id}",
            declared_media_type="text/markdown",
            expected_byte_size=32,
            media_type="text/markdown",
            byte_size=32,
            sha256=artifact_hash,
            status="COMPLETE",
            upload_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    postgres_repository.add(
        JobRow(
            id=job_id,
            tenant_id=tenant_id,
            kind="ACTIVITY",
            aggregate_id=activity_id,
            stage="QUEUED",
            status="QUEUED",
        )
    )
    spec = SyntheticProviderAuthorizationSpec(
        authorization_id=authorization_id,
        tenant_id=tenant_id,
        job_id=job_id,
        job_kind="ACTIVITY",
        aggregate_id=activity_id,
        expected_claim_attempt=1,
        artifact_hashes=(artifact_hash,),
        candidate_sha=candidate_sha,
        boundary_hash=boundary_hash,
        secret_version_resource=secret_resource,
        max_requests=4,
        max_cost_usd=0.25,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        created_by=_id("operator"),
    )
    postgres_repository.authorize_synthetic_provider_job(spec)
    assert postgres_repository.claim_job(job_id) is not None
    arguments = {
        "job_id": job_id,
        "candidate_sha": candidate_sha,
        "boundary_hash": boundary_hash,
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "model": LUNA_MODEL_ID,
        "secret_version_resource": secret_resource,
        "maximum_requests": 4,
        "maximum_cost_usd": 0.25,
    }
    grant = postgres_repository.consume_synthetic_provider_authorization(
        **arguments
    )
    assert grant.authorization_id == authorization_id
    with pytest.raises(Conflict, match="ALREADY_CONSUMED"):
        postgres_repository.consume_synthetic_provider_authorization(
            **arguments
        )
    with pytest.raises(DBAPIError):
        with postgres_repository.session() as session:
            session.execute(
                update(SyntheticProviderAuthorizationRow)
                .where(SyntheticProviderAuthorizationRow.id == authorization_id)
                .values(max_requests=3)
            )
    with postgres_repository.session() as session:
        claim = session.scalar(
            select(SyntheticProviderClaimRow).where(
                SyntheticProviderClaimRow.authorization_id
                == authorization_id
            )
        )
        assert claim is not None
        assert claim.job_id == job_id
