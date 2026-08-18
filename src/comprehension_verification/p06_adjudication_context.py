"""Blind-safe P06 adjudication companion for semantic-benchmark/1.2.0.

Phase 9B.3 found that the generic semantic review packet does not let a blind
adjudicator decide the Phase 9 MODEL_FAILURE conditions for P06.  The reviewer
could not tell which semantic route the candidate saw, nor which canonical
output fields the provider actually owned, so
``VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE`` and
``NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE`` were unanswerable
without guessing the architecture.

Rather than widen the shared packet schema -- which would rewrite stable
P04/P07/P09 packet bytes for a P06-only need -- this module emits a stage
specific companion bound to exactly one packet.  The companion adds route and
field-authority context and nothing else; every candidate-identifying or
outcome-revealing field stays out by construction and is asserted on the way
out.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .canonical import canonical_hash
from .p06_field_authority import (
    MODEL_OWNED,
    SERVER_DERIVED,
    SERVER_OWNED,
    p06_field_authority,
)


P06_ADJUDICATION_CONTEXT_VERSION = "p06-adjudication-context/1.0.0"

#: Keys that must never appear anywhere in a companion context.  Blindness here
#: is about the *candidate* and the *answer*, not about the task: the reviewer
#: is supposed to see the semantic task the model saw.
FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "expected_support_status",
        "expected_status",
        "expected_classification",
        "property_answer",
        "oracle_verdict",
        "oracle_state",
        "oracle_rationale",
        "ratification_verdict",
        "property_id",
        "candidate_id",
        "candidate_model",
        "candidate_family",
        "model",
        "model_family",
        "reasoning_effort",
        "cost",
        "cost_usd",
        "latency",
        "latency_ms",
        "split",
        "rung",
        "promotion_order",
        "other_runs",
        "other_candidates",
        "run_index",
        "qualification_result",
        "accepted_semantic_rate",
        "result_state",
    }
)

#: Canonical support-status tokens. The companion states which *field* carries
#: the status, never which value the oracle expects.
_EXPECTED_STATUS_TOKENS = ("SUFFICIENT", "PARTIAL", "INSUFFICIENT", "UNCERTAIN")

_MODEL_FAILURE_QUESTIONS = (
    "VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE",
    "NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE",
    "FIXTURE_IS_VALID",
)


class AdjudicationContextError(ValueError):
    """Raised when a companion context is unbound or leaks a forbidden field."""


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, str(key), item
            yield from _walk(item, child)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            child = f"{path}[{index}]"
            yield from _walk(item, child)


def route_context_for(
    route: Mapping[str, Any], model_visible_definition: Mapping[str, Any]
) -> dict[str, Any]:
    """Reproduce exactly the semantic task the candidate saw.

    Every field here is model-visible by construction, so restating it to the
    adjudicator reveals nothing the candidate did not already have.  Evidence
    *location* is deliberately absent: the candidate had to find it, and telling
    the reviewer where it was would invite grading the model against the oracle's
    own reading rather than against the construct.
    """

    return {
        "target_construct_key": route["target_construct_key"],
        "target_construct_label": model_visible_definition["construct"],
        "target_construct_description": model_visible_definition[
            "construct_description"
        ],
        "construct_source_kind": route["construct_provenance"]["source_kind"],
        "construct_source_refs": list(route["construct_provenance"]["source_refs"]),
        "cognitive_operation": model_visible_definition["cognitive_operation"],
        "focus": model_visible_definition["focus"],
        "observable": model_visible_definition["observable"],
        "evidence_requirement": dict(model_visible_definition["evidence_requirement"]),
        "allowed_response_formats": list(model_visible_definition["response_formats"]),
        "evidence_scope": route["evidence_provenance"]["scope"],
        "evidence_artifact_count": len(route["evidence_provenance"]["artifacts"]),
        "task_statement": (
            "The provider received the whole submission evidence bundle and one "
            "authorized construct, and decided a support status for that construct."
        ),
    }


def field_authority_context(authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """State ownership of the canonical fields an adjudicator will look at."""

    resolved = dict(authority or p06_field_authority())
    by_authority = resolved["fields_by_authority"]
    return {
        "field_authority_hash": resolved["field_authority_hash"],
        "materializer_version": resolved["materializer_version"],
        "model_owned": list(by_authority[MODEL_OWNED]),
        "server_owned": list(by_authority[SERVER_OWNED]),
        "server_derived_from_model_input": list(by_authority[SERVER_DERIVED]),
        "authority_definitions": dict(resolved["authority_definitions"]),
        "server_derived_rule": (
            "SERVER_DERIVED_FROM_MODEL_INPUT is not independent semantic evidence. "
            "evidence_fit, mapping_confidence, the variant aggregate support_status "
            "and every mapping_summary count are deterministic restatements of the "
            "provider's own support_status."
        ),
        "server_prose_rule": resolved["server_prose_rule"],
        "model_failure_questions_answerable": list(_MODEL_FAILURE_QUESTIONS),
    }


def build_p06_adjudication_context(
    *,
    packet: Mapping[str, Any],
    packet_hash: str,
    route: Mapping[str, Any],
    model_visible_definition: Mapping[str, Any],
    stage_boundary_hash: str,
    route_context_hash: str,
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single companion context bound to one P06 packet."""

    if packet.get("stage") != "P06":
        raise AdjudicationContextError("companion context is P06-only")
    if packet.get("fixture_id") != route["route_fixture_id"]:
        raise AdjudicationContextError("packet fixture does not match the route")
    context = route_context_for(route, model_visible_definition)
    computed = canonical_hash(context)
    if computed != route_context_hash:
        raise AdjudicationContextError(
            "route context does not match the frozen model-visible task"
        )
    material = {
        "schema_version": P06_ADJUDICATION_CONTEXT_VERSION,
        "stage": "P06",
        "packet_hash": packet_hash,
        "fixture_id": route["route_fixture_id"],
        "case_id": packet["case_id"],
        "route_context": context,
        "route_context_hash": computed,
        "field_authority_context": field_authority_context(authority),
        "p06_stage_boundary_hash": stage_boundary_hash,
        "self_contained": True,
    }
    document = {**material, "context_hash": canonical_hash(material)}
    assert_blind_safe(document)
    return document


def assert_blind_safe(context: Mapping[str, Any]) -> None:
    """Fail closed when a companion leaks candidate identity or the answer."""

    for path, key, value in _walk(context):
        if key in FORBIDDEN_CONTEXT_KEYS:
            raise AdjudicationContextError(
                f"forbidden adjudication-context field at {path}"
            )
        if key == "target_construct_key" and any(
            token in str(value).upper() for token in _EXPECTED_STATUS_TOKENS
        ):
            raise AdjudicationContextError(
                f"construct key encodes an expected support status at {path}"
            )


def verify_context_binding(
    context: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    packet_hash: str,
    stage_boundary_hash: str,
    field_authority_hash: str,
) -> None:
    """Reject an unbound context, or one that belongs to a different packet."""

    if context.get("schema_version") != P06_ADJUDICATION_CONTEXT_VERSION:
        raise AdjudicationContextError("unknown adjudication-context version")
    if context.get("packet_hash") != packet_hash:
        raise AdjudicationContextError("context is not bound to this packet")
    if context.get("fixture_id") != packet.get("fixture_id"):
        raise AdjudicationContextError("context fixture does not match the packet")
    if context.get("case_id") != packet.get("case_id"):
        raise AdjudicationContextError("context case does not match the packet")
    if context.get("p06_stage_boundary_hash") != stage_boundary_hash:
        raise AdjudicationContextError("context predates the current P06 boundary")
    authority = context.get("field_authority_context") or {}
    if authority.get("field_authority_hash") != field_authority_hash:
        raise AdjudicationContextError("context field authority is stale")
    recomputed = canonical_hash(
        {key: value for key, value in context.items() if key != "context_hash"}
    )
    if recomputed != context.get("context_hash"):
        raise AdjudicationContextError("context hash does not cover its own content")
    assert_blind_safe(context)


def companion_index(contexts: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Require exactly one companion per adjudicable P06 packet."""

    by_packet: dict[str, int] = {}
    for context in contexts:
        packet_hash = str(context["packet_hash"])
        by_packet[packet_hash] = by_packet.get(packet_hash, 0) + 1
    duplicates = sorted(key for key, count in by_packet.items() if count > 1)
    if duplicates:
        raise AdjudicationContextError(
            f"more than one companion context for packet(s): {duplicates}"
        )
    material = {
        "schema_version": "p06-adjudication-context-index/1.0.0",
        "context_count": len(contexts),
        "packet_hashes": sorted(by_packet),
        "contexts": [
            {
                "packet_hash": item["packet_hash"],
                "fixture_id": item["fixture_id"],
                "context_hash": item["context_hash"],
            }
            for item in sorted(contexts, key=lambda value: str(value["packet_hash"]))
        ],
    }
    return {**material, "index_hash": canonical_hash(material)}
