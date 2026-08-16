"""Durable, content-free boundary for synthetic real-provider jobs.

This module contains no credential resolver and no transport construction.  It
only describes the server-attested grant that must exist before either of
those capabilities can be reached by the one-shot worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Final

from .canonical import canonical_hash
from .contracts import model_by_name
from .model_gateway import (
    LUNA_MODEL_ID,
    OPENAI_ROUTE_PROFILE,
    OPENAI_ROUTE_PROFILE_ID,
    OPENAI_ROUTE_PROFILE_MAX_TRANSIENT_RETRIES,
    PROMPT_SPECS,
    build_openai_routes,
)
from .model_gateway.gateway import PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS
from .model_gateway.openai_adapter import OPENAI_SDK_VERSION
from .validation import PROMPT_APPLICATION_VALIDATOR_VERSIONS


SYNTHETIC_DATA_CLASSIFICATION: Final = "SYNTHETIC_ONLY_NO_STUDENT_DATA"
SYNTHETIC_PROVIDER_AUTHORIZATION_VERSION: Final = (
    "stage2-synthetic-provider-authorization/1.0.0"
)
SYNTHETIC_PROVIDER_CLAIM_VERSION: Final = "stage2-synthetic-provider-claim/1.0.0"
SYNTHETIC_PROVIDER_BOUNDARY_VERSION: Final = (
    "stage2-synthetic-provider-boundary/1.0.0"
)
SYNTHETIC_PROVIDER_REQUEST_CAP_VERSION: Final = (
    "stage2-provider-request-cap/1.0.0"
)

# Registry/routes remain a historical capability catalog. This separate
# product policy is the authorization/reachability boundary after Phase 6.
ACTIVE_PRODUCT_MODEL_PROMPT_IDS: Final = frozenset(
    {
        "P01_ACTIVITY_SPEC_V1",
        "P02_RUBRIC_NORMALIZE_V1",
        "P03_AMBIGUITY_TRIAGE_V1",
        "P04_BLUEPRINT_BUILD_V1",
        "P06_EVIDENCE_MAP_V1",
        "P07_QUESTION_BUILD_V1",
        "P09_GUIDE_BUILD_V1",
    }
)
INTERNAL_SCHEMA_REPAIR_PROMPT_IDS: Final = frozenset(
    {"P11_SCHEMA_REPAIR_V1"}
)
HISTORICAL_PRODUCT_PROMPT_IDS: Final = frozenset(
    {"P05_BLUEPRINT_REVIEW_V1", "P08_QUESTION_REVIEW_V1"}
)
DISABLED_PRODUCT_PROMPT_IDS: Final = frozenset(
    {"P10_ENRICHED_CONTEXT_V1"}
)

if (
    ACTIVE_PRODUCT_MODEL_PROMPT_IDS
    | INTERNAL_SCHEMA_REPAIR_PROMPT_IDS
    | HISTORICAL_PRODUCT_PROMPT_IDS
    | DISABLED_PRODUCT_PROMPT_IDS
) != set(PROMPT_SPECS):
    raise RuntimeError("product prompt policy must partition the registry")

_CANONICAL_HASH = re.compile(r"^sha256:[a-f0-9]{64}$")
_CANDIDATE_SHA = re.compile(r"^[a-f0-9]{40}$")
_CANONICAL_ID = re.compile(r"^[a-z][a-z0-9_-]{2,127}$")
_PINNED_SECRET_RESOURCE = re.compile(
    r"^projects/[a-z0-9-]{4,63}/secrets/[A-Za-z0-9_-]{1,255}/versions/[1-9][0-9]*$"
)


def validate_pinned_secret_resource(value: str) -> str:
    """Accept only a concrete Secret Manager version resource, never latest."""

    if _PINNED_SECRET_RESOURCE.fullmatch(value) is None:
        raise ValueError("OpenAI secret resource must name a pinned numeric version")
    return value


def synthetic_provider_boundary_material() -> dict[str, Any]:
    """Return the executable real-provider boundary without any content."""

    routes = build_openai_routes(max_call_cost_usd=1.0)
    prompt_ids = tuple(sorted(routes))
    return {
        "boundary_version": SYNTHETIC_PROVIDER_BOUNDARY_VERSION,
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "model": LUNA_MODEL_ID,
        "openai_sdk_version": OPENAI_SDK_VERSION,
        "gateway_max_transient_retries": (
            OPENAI_ROUTE_PROFILE_MAX_TRANSIENT_RETRIES
        ),
        "request_cap_version": SYNTHETIC_PROVIDER_REQUEST_CAP_VERSION,
        "transport_controls": {
            "store": False,
            "background": False,
            "tools": [],
            "fallback": False,
            "p10_callable": False,
            "sdk_retries": 0,
        },
        "product_runtime_prompt_policy": {
            "active_model_stages": sorted(ACTIVE_PRODUCT_MODEL_PROMPT_IDS),
            "internal_schema_repair": sorted(
                INTERNAL_SCHEMA_REPAIR_PROMPT_IDS
            ),
            "historical_non_callable": sorted(
                HISTORICAL_PRODUCT_PROMPT_IDS
            ),
            "disabled": sorted(DISABLED_PRODUCT_PROMPT_IDS),
        },
        "prompts": {
            prompt_id: {
                "prompt_version": PROMPT_SPECS[prompt_id].prompt_version,
                "prompt_hash": PROMPT_SPECS[prompt_id].prompt_hash,
                "input_schema_hash": canonical_hash(
                    model_by_name(
                        PROMPT_SPECS[prompt_id].input_schema_name
                    ).model_json_schema(mode="validation")
                ),
                "output_schema_hash": canonical_hash(
                    model_by_name(
                        PROMPT_SPECS[prompt_id].output_schema_name
                    ).model_json_schema(mode="validation")
                ),
                "relationship_validator": (
                    PROMPT_RELATIONSHIP_VALIDATOR_VERSIONS[prompt_id]
                ),
                "application_validator": (
                    PROMPT_APPLICATION_VALIDATOR_VERSIONS.get(prompt_id)
                ),
                "route_id": routes[prompt_id].route_id,
                "model": routes[prompt_id].model,
                "reasoning_effort": routes[prompt_id].reasoning_effort.value,
                "max_input_tokens": routes[prompt_id].max_input_tokens,
                "max_output_tokens": routes[prompt_id].max_output_tokens,
                "fallback_route_id": routes[prompt_id].fallback_route_id,
            }
            for prompt_id in prompt_ids
        },
        "profile_prompt_ids": sorted(OPENAI_ROUTE_PROFILE),
    }


def synthetic_provider_boundary_hash() -> str:
    return canonical_hash(synthetic_provider_boundary_material())


@dataclass(frozen=True, slots=True)
class SyntheticProviderAuthorizationSpec:
    """Operator-issued authorization for exactly one already durable job."""

    authorization_id: str
    tenant_id: str
    job_id: str
    job_kind: str
    aggregate_id: str
    expected_claim_attempt: int
    artifact_hashes: tuple[str, ...]
    candidate_sha: str
    boundary_hash: str
    secret_version_resource: str
    max_requests: int
    max_cost_usd: float
    expires_at: datetime
    created_by: str
    route_profile: str = OPENAI_ROUTE_PROFILE_ID
    model: str = LUNA_MODEL_ID
    classification: str = SYNTHETIC_DATA_CLASSIFICATION
    schema_version: str = SYNTHETIC_PROVIDER_AUTHORIZATION_VERSION

    def __post_init__(self) -> None:
        for value in (
            self.authorization_id,
            self.tenant_id,
            self.job_id,
            self.aggregate_id,
            self.created_by,
        ):
            if _CANONICAL_ID.fullmatch(value) is None:
                raise ValueError("synthetic authorization contains a non-canonical ID")
        if self.job_kind not in {
            "ACTIVITY",
            # Retained only so historical P05 authorization rows remain
            # reconstructible. Repository/worker gates forbid new consumption.
            "BLUEPRINT_REVIEW",
            "SUBMISSION",
            "QUESTION_ACTION",
        }:
            raise ValueError("synthetic authorization contains an unsupported job kind")
        if not 1 <= self.expected_claim_attempt <= 10:
            raise ValueError("synthetic authorization claim attempt is out of range")
        if not self.artifact_hashes:
            raise ValueError("synthetic authorization requires sealed artifact hashes")
        if tuple(sorted(set(self.artifact_hashes))) != self.artifact_hashes:
            raise ValueError("synthetic authorization artifact hashes must be unique and sorted")
        if any(_CANONICAL_HASH.fullmatch(value) is None for value in self.artifact_hashes):
            raise ValueError("synthetic authorization contains an invalid artifact hash")
        if _CANDIDATE_SHA.fullmatch(self.candidate_sha) is None:
            raise ValueError("synthetic authorization requires an exact candidate SHA")
        if _CANONICAL_HASH.fullmatch(self.boundary_hash) is None:
            raise ValueError("synthetic authorization requires a canonical boundary hash")
        validate_pinned_secret_resource(self.secret_version_resource)
        if not 1 <= self.max_requests <= 64:
            raise ValueError("synthetic authorization request cap is out of range")
        if not 0.01 <= self.max_cost_usd <= 10.0:
            raise ValueError("synthetic authorization cost cap is out of range")
        if self.expires_at.tzinfo is None:
            raise ValueError("synthetic authorization expiry must be timezone-aware")
        if self.route_profile != OPENAI_ROUTE_PROFILE_ID or self.model != LUNA_MODEL_ID:
            raise ValueError("synthetic authorization route is not approved")
        if self.classification != SYNTHETIC_DATA_CLASSIFICATION:
            raise ValueError("synthetic authorization classification is not approved")
        if self.schema_version != SYNTHETIC_PROVIDER_AUTHORIZATION_VERSION:
            raise ValueError("synthetic authorization schema version is not approved")

    def material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "tenant_id": self.tenant_id,
            "job_id": self.job_id,
            "job_kind": self.job_kind,
            "aggregate_id": self.aggregate_id,
            "expected_claim_attempt": self.expected_claim_attempt,
            "artifact_hashes": list(self.artifact_hashes),
            "candidate_sha": self.candidate_sha,
            "boundary_hash": self.boundary_hash,
            "route_profile": self.route_profile,
            "model": self.model,
            "secret_version_resource": self.secret_version_resource,
            "max_requests": self.max_requests,
            "max_cost_usd": self.max_cost_usd,
            "classification": self.classification,
            "expires_at": self.expires_at,
            "created_by": self.created_by,
        }

    @property
    def authorization_hash(self) -> str:
        return canonical_hash(self.material())


@dataclass(frozen=True, slots=True)
class SyntheticProviderGrant:
    """Consumed claim returned to the worker before it resolves a credential."""

    authorization_id: str
    authorization_hash: str
    tenant_id: str
    job_id: str
    job_kind: str
    aggregate_id: str
    claim_attempt: int
    artifact_hashes: frozenset[str]
    candidate_sha: str
    boundary_hash: str
    route_profile: str
    model: str
    secret_version_resource: str
    max_requests: int
    max_cost_usd: float
    classification: str = SYNTHETIC_DATA_CLASSIFICATION
