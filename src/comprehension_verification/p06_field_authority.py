"""Executable P06 field-authority derivation for semantic-benchmark/1.2.0.

Phase 9B.3 established that a blind P06 adjudicator cannot decide
``VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE`` without knowing which
canonical output fields the provider actually owns.  This module answers that
question from product authority instead of from human-readable output prose.

The classification is traced along the real P06 chain::

    EvidenceMappingAliasEnvelope
        -> EvidenceMappingModelDraft
        -> materialize_evidence_mapping_draft()
        -> EvidenceMapPatch

``MODEL_OWNED`` is derived mechanically from the provider draft contract.
Everything the materializer copies from the trusted request is ``SERVER_OWNED``.
Fields the materializer computes deterministically *from* provider input are
``SERVER_DERIVED_FROM_MODEL_INPUT`` and are explicitly not independent semantic
evidence: they restate a model decision through a server function.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .canonical import canonical_hash
from .contracts import models as m
from .evidence_mapping import (
    P06_MATERIALIZER_VERSION,
    evidence_mapping_materializer_boundary,
    p06_alias_envelope_schema_boundary,
)


P06_FIELD_AUTHORITY_VERSION = "p06-field-authority/1.0.0"

MODEL_OWNED = "MODEL_OWNED"
SERVER_OWNED = "SERVER_OWNED"
SERVER_DERIVED = "SERVER_DERIVED_FROM_MODEL_INPUT"

#: Draft fields that select which blueprint route and evidence the relation is
#: about.  They are model decisions, but they are *routing* decisions: the
#: server resolves each alias against the trusted envelope and rejects unknown
#: aliases, so a wrong alias is a rejected call and never a silent semantic
#: claim.
_MODEL_ROUTING_DRAFT_FIELDS = frozenset(
    {"variant_alias", "template_alias", "evidence_aliases"}
)

#: Draft fields that carry the semantic decision itself.
_MODEL_SEMANTIC_DRAFT_FIELDS = frozenset(
    {
        "support_status",
        "support_type",
        "support_description",
        "semantic_uncertainty",
        "abstention_reason",
    }
)


def _source_file_hash(path: str | Path) -> str:
    return f"sha256:{sha256(Path(path).read_bytes()).hexdigest()}"


def _draft_surface() -> dict[str, list[str]]:
    """Read the provider-owned surface straight off the draft contract."""

    relation_fields = sorted(m.EvidenceMappingRelationDraft.model_fields)
    unclassified = (
        set(relation_fields)
        - _MODEL_ROUTING_DRAFT_FIELDS
        - _MODEL_SEMANTIC_DRAFT_FIELDS
    )
    if unclassified:
        raise ValueError(
            "EvidenceMappingRelationDraft exposes an unclassified provider field: "
            + ", ".join(sorted(unclassified))
        )
    return {
        "relation_fields": relation_fields,
        "semantic_fields": sorted(_MODEL_SEMANTIC_DRAFT_FIELDS),
        "routing_fields": sorted(_MODEL_ROUTING_DRAFT_FIELDS),
        "draft_fields": sorted(m.EvidenceMappingModelDraft.model_fields),
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


def _opportunity_rows() -> list[dict[str, Any]]:
    """Classify every ``QuestionOpportunity`` field the materializer writes."""

    model_semantic = [
        ("support_status", "relation.support_status"),
        ("support_type", "relation.support_type"),
        ("support_description", "relation.support_description"),
        ("semantic_uncertainty", "relation.semantic_uncertainty"),
        ("abstention_reason", "relation.abstention_reason"),
    ]
    server_trusted = [
        ("opportunity_template_id", "template.opportunity_template_id"),
        ("submission_id", "request.evidence_bundle.submission_id"),
        ("dimension_id", "dimension.dimension_id"),
        ("variant_id", "variant.variant_id"),
        ("cognitive_operation", "template.cognitive_operation"),
        ("focus", "template.focus"),
        ("observable", "template.observable"),
        ("difficulty", "template.difficulty"),
        ("target_minutes", "template.target_minutes"),
        ("allowed_anchor_structures", "template.allowed_anchor_structures"),
        ("allowed_response_formats", "template.allowed_response_formats"),
        ("activity_priority", "dimension.verification_priority"),
        ("opportunity_quality", "template.minimum_quality"),
        (
            "student_justification_required",
            "template.student_justification_required",
        ),
    ]
    rows = [
        _field(
            "QuestionOpportunity",
            name,
            MODEL_OWNED,
            f"copied verbatim from {src}",
            independent_semantic_evidence=True,
        )
        for name, src in model_semantic
    ]
    rows.append(
        _field(
            "QuestionOpportunity",
            "evidence_ids",
            MODEL_OWNED,
            "resolved from relation.evidence_aliases against the trusted envelope",
            independent_semantic_evidence=True,
            note=(
                "The model chooses which evidence supports the construct. Unknown "
                "aliases are rejected deterministically, so this field cannot carry "
                "a silent invention."
            ),
        )
    )
    rows.extend(
        _field(
            "QuestionOpportunity",
            name,
            SERVER_OWNED,
            f"copied verbatim from trusted {src}",
            independent_semantic_evidence=False,
        )
        for name, src in server_trusted
    )
    rows.append(
        _field(
            "QuestionOpportunity",
            "opportunity_id",
            SERVER_OWNED,
            "stable_id() over submission, blueprint, template and evidence ids",
            independent_semantic_evidence=False,
        )
    )
    rows.append(
        _field(
            "QuestionOpportunity",
            "evidence_fit",
            SERVER_DERIVED,
            "_compatibility_fit(relation.support_status)",
            independent_semantic_evidence=False,
            note=(
                "A pure function of the model support_status. It restates the model "
                "decision as a float and adds no independent server judgement."
            ),
        )
    )
    return rows


def _variant_match_rows() -> list[dict[str, Any]]:
    return [
        _field(
            "EvidenceVariantMatch",
            "dimension_id",
            SERVER_OWNED,
            "copied verbatim from trusted dimension.dimension_id",
            independent_semantic_evidence=False,
        ),
        _field(
            "EvidenceVariantMatch",
            "variant_id",
            SERVER_OWNED,
            "copied verbatim from trusted variant.variant_id",
            independent_semantic_evidence=False,
        ),
        _field(
            "EvidenceVariantMatch",
            "justification",
            SERVER_OWNED,
            "constant server string",
            independent_semantic_evidence=False,
            note=(
                "Fixed prose ('Relaciones categoricas P06 materializadas por el "
                "servidor.'). It is a constant and therefore carries no information "
                "about any field's authority. It must never be read as evidence that "
                "the neighbouring support_status is server-owned."
            ),
        ),
        _field(
            "EvidenceVariantMatch",
            "support_status",
            SERVER_DERIVED,
            "_aggregate_support_status(model relation statuses)",
            independent_semantic_evidence=False,
            note=(
                "Deterministic precedence over the model's own per-template "
                "statuses. It is a restatement, not a second opinion."
            ),
        ),
        _field(
            "EvidenceVariantMatch",
            "evidence_fit",
            SERVER_DERIVED,
            "_compatibility_fit(aggregate model support_status)",
            independent_semantic_evidence=False,
        ),
        _field(
            "EvidenceVariantMatch",
            "mapping_confidence",
            SERVER_DERIVED,
            "0.0 when the aggregate model status is UNCERTAIN, otherwise 1.0",
            independent_semantic_evidence=False,
            note=(
                "Not a server confidence estimate. It is a two-valued projection of "
                "the model's own status."
            ),
        ),
        _field(
            "EvidenceVariantMatch",
            "evidence_ids",
            SERVER_DERIVED,
            "ordered union of the model-selected evidence ids for the variant",
            independent_semantic_evidence=False,
        ),
    ]


def _patch_rows() -> list[dict[str, Any]]:
    summary = [
        ("mapped_relation_count", "count of model-emitted relations"),
        ("sufficient_count", "count of model relations with SUFFICIENT"),
        ("partial_count", "count of model relations with PARTIAL"),
        ("insufficient_count", "count of model relations with INSUFFICIENT"),
        ("uncertain_count", "count of model relations with UNCERTAIN"),
    ]
    rows = [
        _field(
            "EvidenceMapPatch",
            "submission_id",
            SERVER_OWNED,
            "copied verbatim from request.evidence_bundle.submission_id",
            independent_semantic_evidence=False,
        ),
        _field(
            "EvidenceMapPatch",
            "status",
            SERVER_OWNED,
            "constant 'READY' set by the materializer",
            independent_semantic_evidence=False,
        ),
        _field(
            "EvidenceMapPatch",
            "claims",
            SERVER_OWNED,
            "always empty at P06",
            independent_semantic_evidence=False,
        ),
        _field(
            "EvidenceMapPatch",
            "diagnostics",
            SERVER_OWNED,
            "always empty at P06",
            independent_semantic_evidence=False,
        ),
    ]
    rows.extend(
        _field(
            "EvidenceMappingSummary",
            name,
            SERVER_DERIVED,
            derivation,
            independent_semantic_evidence=False,
        )
        for name, derivation in summary
    )
    return rows


def p06_field_authority() -> dict[str, Any]:
    """Return the executable-source-bound P06 field authority artifact."""

    rows = _opportunity_rows() + _variant_match_rows() + _patch_rows()
    by_authority: dict[str, list[str]] = {
        MODEL_OWNED: [],
        SERVER_OWNED: [],
        SERVER_DERIVED: [],
    }
    for row in rows:
        by_authority[row["authority"]].append(f"{row['contract']}.{row['field']}")
    material = {
        "schema_version": P06_FIELD_AUTHORITY_VERSION,
        "benchmark_version": "semantic-benchmark/1.2.0",
        "stage": "P06",
        "materializer_version": P06_MATERIALIZER_VERSION,
        "authority_chain": [
            "EvidenceMappingAliasEnvelope",
            "EvidenceMappingModelDraft",
            "materialize_evidence_mapping_draft()",
            "EvidenceMapPatch",
        ],
        "provider_draft_surface": _draft_surface(),
        "fields": sorted(rows, key=lambda item: (item["contract"], item["field"])),
        "fields_by_authority": {
            key: sorted(value) for key, value in by_authority.items()
        },
        "authority_definitions": {
            MODEL_OWNED: (
                "The provider decides this value. A wrong value here is a candidate "
                "failure."
            ),
            SERVER_OWNED: (
                "The server copies this from the trusted request. The provider cannot "
                "influence it, so it can never be a candidate failure."
            ),
            SERVER_DERIVED: (
                "The server computes this deterministically from provider input. It "
                "is NOT independent semantic evidence: it restates a model decision."
            ),
        },
        "server_prose_rule": (
            "Server justification prose never establishes field authority. Only this "
            "artifact, derived from the executable materializer, does."
        ),
        "materializer_boundary": evidence_mapping_materializer_boundary(),
        "alias_envelope_schema_boundary": p06_alias_envelope_schema_boundary(),
        "executable_source_hashes": {
            "evidence_mapping": _source_file_hash(
                Path(__file__).with_name("evidence_mapping.py")
            ),
            "field_authority": _source_file_hash(__file__),
            "canonical_contracts": _source_file_hash(m.__file__),
        },
        "model_draft_schema_hash": canonical_hash(
            m.EvidenceMappingModelDraft.model_json_schema(mode="validation")
        ),
        "relation_draft_schema_hash": canonical_hash(
            m.EvidenceMappingRelationDraft.model_json_schema(mode="validation")
        ),
    }
    return {**material, "field_authority_hash": canonical_hash(material)}
