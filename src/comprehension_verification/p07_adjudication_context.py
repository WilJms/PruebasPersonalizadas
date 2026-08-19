"""Blind-safe P07 adjudication companion (Phase 9B.6 remediation).

The generic semantic review packet gives a P07 reviewer a materialized
``QuestionGenerationResult`` and an opaque ``opportunity_id``.  From that alone
the Phase 9 questions are unanswerable: the reviewer cannot see the semantic
opportunity the provider was asked to write for, and cannot tell which fields
the provider owned.  Phase 9B.5 classified this as a pre-execution
adjudication-validity blocker.

As with P06, the repair is a *companion* bound to exactly one packet rather
than a widening of the shared packet schema -- the generic P04/P06/P09 packet
bytes are not touched to solve a P07-only problem.

The companion carries four things and nothing else:

``opportunity context``
    Exactly the ``QuestionOpportunityContext`` and generation constraints the
    provider saw through its ``QuestionAliasEnvelope``.  Restating them reveals
    nothing the provider did not already have.

``field authority``
    Which canonical fields are ``MODEL_OWNED``, ``SERVER_OWNED`` and
    ``SERVER_DERIVED_FROM_MODEL_INPUT``, from
    :mod:`p07_field_authority`.

``the deterministic-failure surface``
    The materializer's own replacement conditions, so a reviewer can tell a
    server rejection from a provider failure instead of inferring one from
    ``status``.

``binding``
    Packet hash, fixture/opportunity identity, case id, P07 stage boundary and
    field-authority hash, so a companion cannot be detached and reattached to a
    different packet.

Blindness here is about the *candidate* and the *answer*, never about the task.
Candidate identity, reasoning rung, cost, split, expected answer, oracle
verdict, other candidates' results and first-pass decisions are excluded by
construction and asserted on the way out.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .canonical import canonical_hash
from .p07_field_authority import (
    MODEL_OWNED,
    SERVER_DERIVED,
    SERVER_OWNED,
    p07_field_authority,
)


P07_ADJUDICATION_CONTEXT_VERSION = "p07-adjudication-context/1.0.0"

#: Keys that must never appear anywhere in a companion context.
FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "expected_answer",
        "expected_question_text",
        "expected_observables",
        "expected_support_status",
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
        "rung",
        "cost",
        "cost_usd",
        "latency",
        "latency_ms",
        "split",
        "promotion_order",
        "other_runs",
        "other_candidates",
        "run_index",
        "qualification_result",
        "accepted_semantic_rate",
        "result_state",
        "first_pass_decision",
        "first_pass_reliability",
    }
)

#: Exact top-level shape of a companion.  Checked as an allow-list so an added
#: field fails closed even if its hash were recomputed.
_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "packet_hash",
        "fixture_id",
        "opportunity_fixture_id",
        "case_id",
        "opportunity_context",
        "opportunity_context_hash",
        "field_authority_context",
        "deterministic_failure_surface",
        "p07_stage_boundary_hash",
        "self_contained",
        "context_hash",
    }
)

_ALLOWED_OPPORTUNITY_CONTEXT_KEYS = frozenset(
    {
        "cognitive_operation",
        "focus",
        "observable",
        "response_format",
        "difficulty",
        "target_minutes",
        "allowed_anchor_structures",
        "student_justification_required",
        "max_visible_anchor_fragments",
        "require_accessible_alternative",
        "support_evidence_alias_count",
        "avoid_fingerprint_count",
        "task_statement",
    }
)

_MODEL_FAILURE_QUESTIONS = (
    "VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE",
    "NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE",
    "FIXTURE_IS_VALID",
)

#: Every condition on which ``materialize_question_draft`` returns
#: REPLACEMENT_REQUIRED without the provider having asked for one.
_SERVER_REPLACEMENT_CONDITIONS = (
    {
        "condition": "CHOICE_FORMAT_WITHOUT_CHOICES",
        "owner": "SERVER",
        "description": (
            "The opportunity's response format is CHOICE and the draft carried no "
            "choices."
        ),
    },
    {
        "condition": "CHOICES_FOR_NON_CHOICE_FORMAT",
        "owner": "SERVER",
        "description": (
            "The draft carried choices for a response format that is not CHOICE."
        ),
    },
    {
        "condition": "REPEATED_QUESTION_FINGERPRINT",
        "owner": "SERVER",
        "description": (
            "The question text matched a fingerprint the request told the "
            "materializer to avoid."
        ),
    },
    {
        "condition": "ANSWER_LEAKAGE_BLOCKED",
        "owner": "SERVER",
        "description": (
            "The server's answer-leakage policy blocked the draft because the "
            "visible anchor or question restated an expected observable."
        ),
    },
    {
        "condition": "PROVIDER_REQUESTED_REPLACEMENT",
        "owner": "MODEL",
        "description": (
            "The provider itself set status=REPLACEMENT_REQUIRED with a reason."
        ),
    },
)

#: Hard failures the materializer raises rather than returning a result.  These
#: are rejected calls, not semantic claims.
_SERVER_REJECTION_CONDITIONS = (
    "P07_CONTEXT_MODE_INVALID",
    "P07_SCOPE_ALIAS_MISMATCH",
    "P07_ALIAS_REFERENCE_UNKNOWN",
    "P07_VISIBLE_ANCHOR_LIMIT_EXCEEDED",
    "P07_OBSERVABLE_DUPLICATE",
    "P07_SUPPORT_EVIDENCE_UNKNOWN",
    "P07_GENERATED_TEXT_UNSAFE",
)


class P07AdjudicationContextError(ValueError):
    """Raised when a companion is unbound, malformed or leaks a forbidden field."""


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


def opportunity_context_for(
    opportunity: Mapping[str, Any],
    *,
    support_evidence_alias_count: int,
    generation_constraints: Mapping[str, Any],
    avoid_fingerprint_count: int = 0,
) -> dict[str, Any]:
    """Reproduce exactly the semantic opportunity the provider saw.

    Every field here reached the provider through its own alias envelope, so
    restating it to a blind reviewer discloses nothing new.  Evidence *content*
    is deliberately not copied: the reviewer reads the packet's authorized
    source material for that, and duplicating it here would let a companion
    drift from the packet it is bound to.
    """

    return {
        "cognitive_operation": opportunity["cognitive_operation"],
        "focus": opportunity["focus"],
        "observable": opportunity["observable"],
        "response_format": opportunity["response_format"],
        "difficulty": opportunity["difficulty"],
        "target_minutes": opportunity["target_minutes"],
        "allowed_anchor_structures": list(opportunity["allowed_anchor_structures"]),
        "student_justification_required": bool(
            opportunity["student_justification_required"]
        ),
        "max_visible_anchor_fragments": generation_constraints[
            "max_visible_anchor_fragments"
        ],
        "require_accessible_alternative": bool(
            generation_constraints["require_accessible_alternative"]
        ),
        "support_evidence_alias_count": support_evidence_alias_count,
        "avoid_fingerprint_count": avoid_fingerprint_count,
        "task_statement": (
            "The provider received this opportunity and a closed set of aliased "
            "support evidence, and composed one question with its expected "
            "observables. It could not see any other opportunity or submission."
        ),
    }


def field_authority_context(
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """State ownership of the canonical fields an adjudicator will look at."""

    resolved = dict(authority or p07_field_authority())
    by_authority = resolved["fields_by_authority"]
    return {
        "field_authority_hash": resolved["field_authority_hash"],
        "materializer_version": resolved["materializer_version"],
        "authority_chain": list(resolved["authority_chain"]),
        "model_owned": list(by_authority[MODEL_OWNED]),
        "server_owned": list(by_authority[SERVER_OWNED]),
        "server_derived_from_model_input": list(by_authority[SERVER_DERIVED]),
        "authority_definitions": dict(resolved["authority_definitions"]),
        "server_derived_rule": (
            "SERVER_DERIVED_FROM_MODEL_INPUT is not independent semantic evidence. "
            "anchor.structure, anchor.answer_leakage_risk, every stable_id and the "
            "resolved observable evidence_ids are deterministic restatements of "
            "provider input, and must not be counted as a second observation of "
            "the same behaviour."
        ),
        "server_prose_rule": resolved["server_prose_rule"],
        "status_is_not_a_model_confession_rule": resolved[
            "status_is_not_a_model_confession_rule"
        ],
        "model_failure_questions_answerable": list(_MODEL_FAILURE_QUESTIONS),
    }


def deterministic_failure_surface() -> dict[str, Any]:
    """Enumerate which failures are the server's, so none is misattributed."""

    return {
        "replacement_conditions": [dict(row) for row in _SERVER_REPLACEMENT_CONDITIONS],
        "server_rejection_codes": list(_SERVER_REJECTION_CONDITIONS),
        "attribution_rule": (
            "A REPLACEMENT_REQUIRED result is attributable to the model only when "
            "PROVIDER_REQUESTED_REPLACEMENT is the condition that fired. Every "
            "other listed condition is a deterministic materializer decision and "
            "answers NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE "
            "in the negative."
        ),
        "rejection_rule": (
            "A server rejection code means the call never produced a canonical "
            "result. It is a rejected call, not a semantic claim, and cannot "
            "support a MODEL_FAILURE."
        ),
    }


def build_p07_adjudication_context(
    *,
    packet: Mapping[str, Any],
    packet_hash: str,
    opportunity_fixture_id: str,
    opportunity_context: Mapping[str, Any],
    stage_boundary_hash: str,
    opportunity_context_hash: str,
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single companion context bound to one P07 packet."""

    if packet.get("stage") != "P07":
        raise P07AdjudicationContextError("companion context is P07-only")
    if packet.get("fixture_id") != opportunity_fixture_id:
        raise P07AdjudicationContextError(
            "packet fixture does not match the opportunity"
        )
    context = dict(opportunity_context)
    unexpected = sorted(set(context) - _ALLOWED_OPPORTUNITY_CONTEXT_KEYS)
    if unexpected:
        raise P07AdjudicationContextError(
            "opportunity context carries undeclared fields: " + ", ".join(unexpected)
        )
    computed = canonical_hash(context)
    if computed != opportunity_context_hash:
        raise P07AdjudicationContextError(
            "opportunity context does not match the frozen model-visible task"
        )
    material = {
        "schema_version": P07_ADJUDICATION_CONTEXT_VERSION,
        "stage": "P07",
        "packet_hash": packet_hash,
        "fixture_id": opportunity_fixture_id,
        "opportunity_fixture_id": opportunity_fixture_id,
        "case_id": packet["case_id"],
        "opportunity_context": context,
        "opportunity_context_hash": computed,
        "field_authority_context": field_authority_context(authority),
        "deterministic_failure_surface": deterministic_failure_surface(),
        "p07_stage_boundary_hash": stage_boundary_hash,
        "self_contained": True,
    }
    document = {**material, "context_hash": canonical_hash(material)}
    assert_blind_safe(document)
    return document


def assert_blind_safe(context: Mapping[str, Any]) -> None:
    """Fail closed when a companion leaks candidate identity or the answer."""

    unexpected = sorted(set(context) - _ALLOWED_TOP_LEVEL_KEYS)
    if unexpected:
        raise P07AdjudicationContextError(
            "companion carries undeclared top-level fields: " + ", ".join(unexpected)
        )
    for path, key, _value in _walk(context):
        if key in FORBIDDEN_CONTEXT_KEYS:
            raise P07AdjudicationContextError(
                f"forbidden adjudication-context field at {path}"
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

    if context.get("schema_version") != P07_ADJUDICATION_CONTEXT_VERSION:
        raise P07AdjudicationContextError("unknown adjudication-context version")
    if context.get("stage") != "P07" or packet.get("stage") != "P07":
        raise P07AdjudicationContextError("context or packet is not P07")
    if context.get("packet_hash") != packet_hash:
        raise P07AdjudicationContextError("context is not bound to this packet")
    if context.get("fixture_id") != packet.get("fixture_id"):
        raise P07AdjudicationContextError("context fixture does not match the packet")
    if context.get("case_id") != packet.get("case_id"):
        raise P07AdjudicationContextError("context case does not match the packet")
    if context.get("p07_stage_boundary_hash") != stage_boundary_hash:
        raise P07AdjudicationContextError("context predates the current P07 boundary")
    authority = context.get("field_authority_context") or {}
    if authority.get("field_authority_hash") != field_authority_hash:
        raise P07AdjudicationContextError("context field authority is stale")
    recomputed = canonical_hash(
        {key: value for key, value in context.items() if key != "context_hash"}
    )
    if recomputed != context.get("context_hash"):
        raise P07AdjudicationContextError("context hash does not cover its own content")
    assert_blind_safe(context)


def assert_not_independent_model_evidence(
    field_labels: Iterable[str], *, authority: Mapping[str, Any] | None = None
) -> None:
    """Reject an attribution that rests on server-owned or derived fields.

    This is the executable form of the rule the companion states in prose: a
    reviewer may not present ``anchor.structure`` or a ``REPLACEMENT_REQUIRED``
    status as independent evidence of provider behaviour.
    """

    resolved = dict(authority or p07_field_authority())
    by_authority = resolved["fields_by_authority"]
    model_owned = set(by_authority[MODEL_OWNED])
    not_model = set(by_authority[SERVER_OWNED]) | set(by_authority[SERVER_DERIVED])
    offending = sorted(label for label in field_labels if label in not_model)
    if offending:
        raise P07AdjudicationContextError(
            "these fields are not independent model evidence: " + ", ".join(offending)
        )
    unknown = sorted(
        label
        for label in field_labels
        if label not in model_owned and label not in not_model
    )
    if unknown:
        raise P07AdjudicationContextError(
            "unclassified P07 fields cannot support an attribution: "
            + ", ".join(unknown)
        )
