"""Executable P07 field-authority derivation (Phase 9B.6 remediation).

Phase 9B.5 recorded that P07 has no field-authority artifact and no
stage-specific blind adjudication companion.  The generic review packet exposes
a materialized ``QuestionGenerationResult`` plus an opaque ``opportunity_id``,
which is not enough for a blind adjudicator to answer
``VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE`` or
``NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE``.  This is a
pre-execution adjudication-validity blocker, not future debt: without it a
reviewer looking at a P07 output has to guess which parts the provider wrote.

P07 makes that guess particularly unsafe, because ``materialize_question_draft``
mixes three kinds of field in one canonical result:

* text the provider composed (``question_text``, choices, expected observables);
* identifiers and constraints copied verbatim from the trusted request
  (``candidate_id``, ``dimension_id``, ``response_format``, ``evidence_ids``);
* values the server computes deterministically *from* provider input
  (``anchor.structure``, ``anchor.answer_leakage_risk``, every ``stable_id``).

The sharpest case is ``QuestionGenerationResult.status``.  A
``REPLACEMENT_REQUIRED`` result may come from the provider asking for a
replacement -- or from the *server* rejecting the draft for answer leakage, a
repeated fingerprint, or a choice/format mismatch.  Those are deterministic
materializer decisions.  Attributing one to the model would be exactly the
misattribution the Phase 9 adjudication questions exist to prevent.

The classification is traced along the real P07 chain::

    QuestionAliasEnvelope
        -> QuestionModelDraft
        -> materialize_question_draft()
        -> QuestionGenerationResult / QuestionCandidate

Nothing here reads candidate output.  It reads the executable contracts.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .canonical import canonical_hash
from .contracts import models as m
from .question_generation import (
    P07_MATERIALIZER_VERSION,
    p07_alias_envelope_schema_boundary,
    question_generation_materializer_boundary,
)


P07_FIELD_AUTHORITY_VERSION = "p07-field-authority/1.0.0"

MODEL_OWNED = "MODEL_OWNED"
SERVER_OWNED = "SERVER_OWNED"
SERVER_DERIVED = "SERVER_DERIVED_FROM_MODEL_INPUT"

#: Draft fields that select *which* trusted material the question is built from.
#: The server resolves every alias against the envelope and fails the call on an
#: unknown one, so a wrong alias is a rejected request, never a silent claim.
_MODEL_ROUTING_DRAFT_FIELDS = frozenset({"scope_alias", "visible_anchor_aliases"})

#: Draft fields that carry the provider's own composed content.
_MODEL_SEMANTIC_DRAFT_FIELDS = frozenset(
    {
        "question_text",
        "choices",
        "expected_observables",
        "acceptable_alternatives",
        "misconceptions",
        "semantic_uncertainties",
    }
)

#: Draft fields by which the provider controls the outcome of its own call.
_MODEL_CONTROL_DRAFT_FIELDS = frozenset({"status", "replacement_reason"})


class P07FieldAuthorityError(ValueError):
    """Raised when the P07 provider surface cannot be classified exhaustively."""


def _source_file_hash(path: str | Path) -> str:
    return f"sha256:{sha256(Path(path).read_bytes()).hexdigest()}"


def _schema_hash(model: type[Any]) -> str:
    return canonical_hash(model.model_json_schema())


def _draft_surface() -> dict[str, list[str]]:
    """Read the provider-owned surface straight off the draft contract.

    A field added to ``QuestionModelDraft`` without being classified here raises
    rather than defaulting to a safe-looking authority.  Silent defaulting is
    how an unowned field becomes evidence.
    """

    draft_fields = sorted(m.QuestionModelDraft.model_fields)
    unclassified = (
        set(draft_fields)
        - _MODEL_ROUTING_DRAFT_FIELDS
        - _MODEL_SEMANTIC_DRAFT_FIELDS
        - _MODEL_CONTROL_DRAFT_FIELDS
    )
    if unclassified:
        raise P07FieldAuthorityError(
            "QuestionModelDraft exposes an unclassified provider field: "
            + ", ".join(sorted(unclassified))
        )
    return {
        "draft_fields": draft_fields,
        "semantic_fields": sorted(_MODEL_SEMANTIC_DRAFT_FIELDS),
        "routing_fields": sorted(_MODEL_ROUTING_DRAFT_FIELDS),
        "control_fields": sorted(_MODEL_CONTROL_DRAFT_FIELDS),
        "observable_draft_fields": sorted(m.QuestionObservableDraft.model_fields),
        "choice_draft_fields": sorted(m.QuestionChoiceDraft.model_fields),
    }


def _field(
    contract: str,
    field: str,
    authority: str,
    derivation: str,
    *,
    independent_semantic_evidence: bool,
    note: str | None = None,
) -> dict[str, Any]:
    row = {
        "contract": contract,
        "field": field,
        "authority": authority,
        "derivation": derivation,
        "independent_semantic_evidence": independent_semantic_evidence,
    }
    if note is not None:
        row["note"] = note
    return row


def _candidate_rows() -> list[dict[str, Any]]:
    """Classify every ``QuestionCandidate`` field the materializer writes."""

    rows: list[dict[str, Any]] = []

    model_semantic = [
        ("question_text", "draft.question_text"),
        ("uncertainties", "draft.semantic_uncertainties"),
    ]
    for field, derivation in model_semantic:
        rows.append(
            _field(
                "QuestionCandidate",
                field,
                MODEL_OWNED,
                derivation,
                independent_semantic_evidence=True,
            )
        )

    server_copied = [
        ("candidate_id", "request.target_candidate_id"),
        ("submission_id", "request.plan.submission_id"),
        ("opportunity_id", "request.opportunity.opportunity_id"),
        ("opportunity_template_id", "request.opportunity.opportunity_template_id"),
        ("dimension_id", "request.opportunity.dimension_id"),
        ("variant_id", "request.opportunity.variant_id"),
        ("cognitive_operation", "request.opportunity.cognitive_operation"),
        ("response_format", "request.opportunity.allowed_response_formats[0]"),
        ("difficulty", "request.opportunity.difficulty"),
        ("estimated_minutes", "request.opportunity.target_minutes"),
        ("evidence_ids", "request.opportunity.evidence_ids"),
        ("course_source_ids", "constant []"),
        ("citations", "constant []"),
        (
            "student_justification_required",
            "request.opportunity.student_justification_required",
        ),
    ]
    for field, derivation in server_copied:
        rows.append(
            _field(
                "QuestionCandidate",
                field,
                SERVER_OWNED,
                derivation,
                independent_semantic_evidence=False,
                note=(
                    "Copied from the trusted request. A provider cannot change it, "
                    "so it can never be evidence of provider behaviour."
                ),
            )
        )

    rows.extend(
        [
            _field(
                "QuestionCandidate.anchor",
                "anchor_id",
                SERVER_DERIVED,
                "stable_id(candidate_id, visible evidence ids, materializer version)",
                independent_semantic_evidence=False,
            ),
            _field(
                "QuestionCandidate.anchor",
                "structure",
                SERVER_DERIVED,
                "derive_anchor_structure(resolved draft.visible_anchor_aliases, "
                "request.opportunity.allowed_anchor_structures)",
                independent_semantic_evidence=False,
                note=(
                    "A deterministic function of how many units the provider "
                    "selected. It restates a routing choice; it is not a second, "
                    "independent judgement."
                ),
            ),
            _field(
                "QuestionCandidate.anchor",
                "fragments",
                SERVER_DERIVED,
                "anchor_fragment_for_evidence(resolved draft.visible_anchor_aliases)",
                independent_semantic_evidence=False,
                note=(
                    "Fragment *content* is authorized submission evidence rendered "
                    "by the server. Only the selection was the provider's."
                ),
            ),
            _field(
                "QuestionCandidate.anchor",
                "answer_leakage_risk",
                SERVER_DERIVED,
                "assess_answer_leakage(...).risk_score",
                independent_semantic_evidence=False,
                note=(
                    "A server heuristic over provider text. A high score is a "
                    "server measurement, not a provider assertion."
                ),
            ),
            _field(
                "QuestionCandidate.anchor",
                "self_containment_score",
                SERVER_OWNED,
                "constant 1.0",
                independent_semantic_evidence=False,
            ),
            _field(
                "QuestionCandidate.anchor",
                "student_facing_label",
                SERVER_OWNED,
                "constant None",
                independent_semantic_evidence=False,
            ),
        ]
    )

    rows.extend(
        [
            _field(
                "QuestionCandidate.choices[]",
                "text",
                MODEL_OWNED,
                "draft.choices[].text",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.choices[]",
                "is_best_answer",
                MODEL_OWNED,
                "draft.choices[].is_best_answer",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.choices[]",
                "evaluator_rationale",
                MODEL_OWNED,
                "draft.choices[].evaluator_rationale",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.choices[]",
                "misconception",
                MODEL_OWNED,
                "draft.choices[].misconception",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.choices[]",
                "option_id",
                SERVER_DERIVED,
                "stable_id(candidate_id, index, materializer version)",
                independent_semantic_evidence=False,
            ),
        ]
    )

    rows.extend(
        [
            _field(
                "QuestionCandidate.preliminary_guide",
                "purpose",
                SERVER_OWNED,
                "request.opportunity.observable",
                independent_semantic_evidence=False,
            ),
            _field(
                "QuestionCandidate.preliminary_guide",
                "acceptable_alternatives",
                MODEL_OWNED,
                "draft.acceptable_alternatives",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.preliminary_guide",
                "misconceptions",
                MODEL_OWNED,
                "draft.misconceptions",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.preliminary_guide",
                "levels",
                SERVER_OWNED,
                "constant []",
                independent_semantic_evidence=False,
            ),
            _field(
                "QuestionCandidate.preliminary_guide",
                "cannot_infer",
                SERVER_OWNED,
                "constant []",
                independent_semantic_evidence=False,
            ),
            _field(
                "QuestionCandidate.preliminary_guide.observable_elements[]",
                "description",
                MODEL_OWNED,
                "draft.expected_observables[].description",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.preliminary_guide.observable_elements[]",
                "required_for_level_2",
                MODEL_OWNED,
                "draft.expected_observables[].required_for_level_2",
                independent_semantic_evidence=True,
            ),
            _field(
                "QuestionCandidate.preliminary_guide.observable_elements[]",
                "evidence_ids",
                SERVER_DERIVED,
                "resolved draft.expected_observables[].support_evidence_aliases",
                independent_semantic_evidence=False,
                note=(
                    "The alias-to-id resolution is the server's; the selection was "
                    "the provider's and is already counted as routing."
                ),
            ),
            _field(
                "QuestionCandidate.preliminary_guide.observable_elements[]",
                "element_id",
                SERVER_DERIVED,
                "stable_id(candidate_id, index, description, evidence ids, version)",
                independent_semantic_evidence=False,
            ),
            _field(
                "QuestionCandidate.preliminary_guide.observable_elements[]",
                "source_ids",
                SERVER_OWNED,
                "constant []",
                independent_semantic_evidence=False,
            ),
        ]
    )
    return rows


def _result_rows() -> list[dict[str, Any]]:
    """Classify the ``QuestionGenerationResult`` envelope around the candidate."""

    return [
        _field(
            "QuestionGenerationResult",
            "submission_id",
            SERVER_OWNED,
            "request.plan.submission_id",
            independent_semantic_evidence=False,
        ),
        _field(
            "QuestionGenerationResult",
            "opportunity_id",
            SERVER_OWNED,
            "request.opportunity.opportunity_id",
            independent_semantic_evidence=False,
        ),
        _field(
            "QuestionGenerationResult",
            "context_mode",
            SERVER_OWNED,
            "request.evidence_bundle.context_mode",
            independent_semantic_evidence=False,
        ),
        _field(
            "QuestionGenerationResult",
            "status",
            SERVER_DERIVED,
            "draft.status, overridden by materializer replacement decisions",
            independent_semantic_evidence=False,
            note=(
                "REPLACEMENT_REQUIRED is NOT proof the provider asked for a "
                "replacement. materialize_question_draft() also returns it for "
                "blocked answer leakage, a repeated question fingerprint, and a "
                "choice/response-format mismatch. Those are deterministic "
                "materializer decisions and must not be attributed to the model."
            ),
        ),
        _field(
            "QuestionGenerationResult",
            "diagnostics",
            SERVER_OWNED,
            "server leakage heuristic and replacement reporting",
            independent_semantic_evidence=False,
            note=(
                "Diagnostic prose is written by the server. It never establishes "
                "field authority and is never provider evidence."
            ),
        ),
        _field(
            "QuestionGenerationResult",
            "candidate",
            SERVER_DERIVED,
            "present only when the materializer accepted the draft",
            independent_semantic_evidence=False,
        ),
    ]


def p07_field_authority() -> dict[str, Any]:
    """Classify the canonical P07 surface from executable product authority."""

    surface = _draft_surface()
    fields = _candidate_rows() + _result_rows()
    by_authority: dict[str, list[str]] = {
        MODEL_OWNED: [],
        SERVER_OWNED: [],
        SERVER_DERIVED: [],
    }
    for row in fields:
        label = f"{row['contract']}.{row['field']}"
        by_authority[row["authority"]].append(label)

    materializer_boundary = question_generation_materializer_boundary()
    material = {
        "schema_version": P07_FIELD_AUTHORITY_VERSION,
        "stage": "P07",
        "materializer_version": P07_MATERIALIZER_VERSION,
        "authority_chain": [
            "QuestionAliasEnvelope",
            "QuestionModelDraft",
            "materialize_question_draft()",
            "QuestionGenerationResult / QuestionCandidate",
        ],
        "authority_definitions": {
            MODEL_OWNED: (
                "The provider composed this value. It is the only kind of field "
                "whose content can support VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_"
                "OWNED_STAGE."
            ),
            SERVER_OWNED: (
                "Copied verbatim from the trusted request, or a constant. The "
                "provider could not have changed it."
            ),
            SERVER_DERIVED: (
                "Computed deterministically by the server from provider input. It "
                "restates a provider decision through a server function and is "
                "never independent semantic evidence."
            ),
        },
        "provider_draft_surface": surface,
        "fields": sorted(
            fields, key=lambda row: (row["contract"], row["field"])
        ),
        "fields_by_authority": {
            key: sorted(value) for key, value in sorted(by_authority.items())
        },
        "model_draft_schema_hash": _schema_hash(m.QuestionModelDraft),
        "candidate_schema_hash": _schema_hash(m.QuestionCandidate),
        "result_schema_hash": _schema_hash(m.QuestionGenerationResult),
        "alias_envelope_schema_boundary": p07_alias_envelope_schema_boundary(),
        "materializer_boundary": materializer_boundary["boundary_hash"],
        "executable_source_hashes": {
            "question_generation": _source_file_hash(
                Path(__file__).with_name("question_generation.py")
            ),
            "contracts": _source_file_hash(Path(m.__file__)),
        },
        "server_prose_rule": (
            "Server diagnostic prose never establishes field authority. Only this "
            "artifact, derived from the executable materializer, does."
        ),
        "status_is_not_a_model_confession_rule": (
            "QuestionGenerationResult.status is SERVER_DERIVED. A blind "
            "adjudicator may not read REPLACEMENT_REQUIRED as the model declaring "
            "failure without separate MODEL_OWNED evidence."
        ),
    }
    return {**material, "field_authority_hash": canonical_hash(material)}
