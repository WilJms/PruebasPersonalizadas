"""semantic-benchmark/1.2.0 P06 construct authority and route derivation.

Phase 9B.3 found two structural defects in the P06 portion of
semantic-benchmark/1.1.0:

``A``
    Route semantics were derived from *where* evidence appears.  ``_construct``
    in the v1.1 generator returned ``f"{family}: {first_source_ref_section}"``,
    so ``Relacion entre afirmacion y evidencia: parrafo 2`` described a
    location, not a criterion.

``B``
    The blind adjudication surface carried no stage authority, so a reviewer
    could not tell which fields the provider owned.

This module repairs ``A``.  ``p06_adjudication_context`` repairs ``B``.

The repair rests on one observation about the ratified corpus: a P06 property
names its target criterion explicitly, in quotes, e.g. ``INSUFFICIENT para
'Variables y medidas'``.  The target construct is therefore *declared* by the
authorized source chain rather than inferred from prose similarity.  When no
such declaration resolves to exactly one authorized criterion, the property
fails closed instead of receiving an invented generic route.

Nothing here reads candidate outputs, adjudication results or execution
ledgers.  The only oracle read happens at build time, to decide *which*
authorized construct a property is about; the resulting model-visible route is
built solely from the activity's own rubric/assignment text.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable

from .canonical import canonical_hash, stable_id
from .contracts import models as m
from .evidence_mapping import build_evidence_mapping_alias_envelope
from .parsers.service import SafeParserService


SEMANTIC_BENCHMARK_V12_VERSION = "semantic-benchmark/1.2.0"
P06_CONSTRUCT_CATALOG_VERSION = "p06-construct-catalog/1.0.0"
P06_ROUTE_DEFINITIONS_VERSION = "semantic-p06-route-definitions/1.2.0"
P06_PROPERTY_BINDINGS_VERSION = "semantic-property-bindings/1.2.0"
P06_FIXTURE_BUILDER_V12_VERSION = "semantic-benchmark-fixture-p06/1.2.0"
QUALIFICATION_DISPOSITIONS_VERSION = "qualification-oracle-dispositions/1.0.0"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_TENANT_ID = "tenant_semantic_benchmark"
FIXED_INSTANT = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)

#: Header labels that identify the criterion-name column of a rubric table.
#: ``verificacion`` covers the contract-behaviour rubric of activity 04.
_NAME_COLUMN_HEADERS = frozenset({"criterio", "dimension", "verificacion"})

#: Header labels that carry no construct semantics and are dropped from the
#: authorized description (row indexes and weights).
_NON_SEMANTIC_HEADERS = frozenset({"", "#", "n", "peso", "ponderacion", "puntos"})

#: Assignment headings whose list items are authorized activity requirements.
_REQUIREMENT_HEADINGS = frozenset({"tarea", "tareas"})

_QUOTED = re.compile(r"[‘'\"“«]([^'’\"”»‘“«]{2,90})[’'\"”»]")
_LABEL_TOKEN = re.compile(r"\b([A-Z]\d)\b")
_LEADING_LABEL = re.compile(r"^([A-Za-z]?\d+)[.)]\s")

#: Disposition codes for properties that cannot receive an executable route.
NO_UNAMBIGUOUS_CONSTRUCT = "NO_UNAMBIGUOUS_P06_STAGE_LOCAL_CONSTRUCT"
NO_PRODUCTION_REPRESENTATIVE = "NO_PRODUCTION_REPRESENTATIVE_P06_CONSTRUCT"
ACTIVITY_COVERAGE_INDEX_ONLY = "ACTIVITY_COVERAGE_INDEX_ONLY"
CONTEXTUAL_NON_GATE = "CONTEXTUAL_NON_GATE"
NO_VALID_STAGE_LOCAL_FIXTURE = "NO_VALID_STAGE_LOCAL_FIXTURE"
QUALIFICATION_VALID = "QUALIFICATION_VALID"
ORACLE_SUSPECT_FOR_QUALIFICATION = "ORACLE_SUSPECT_FOR_QUALIFICATION"
NOT_APPLICABLE = "NOT_APPLICABLE"


class ConstructResolutionError(ValueError):
    """Raised when the repaired instrument cannot be built deterministically."""


def _fold(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", _fold(value).upper()).strip("_")[:64]


def _source_file_hash(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _activity_number(activity_path: str) -> int:
    match = re.search(r"activity_(\d+)", activity_path)
    if match is None:
        raise ConstructResolutionError(f"unnumbered activity path: {activity_path}")
    return int(match.group(1))


# --------------------------------------------------------------------------
# Construct catalog
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedSource:
    relative: str
    sha256: str
    units: tuple[m.EvidenceUnit, ...]


def _parse(path: Path, role: m.ArtifactRole, relative: str) -> ParsedSource:
    parsed = SafeParserService().parse(
        path, tenant_id=BENCHMARK_TENANT_ID, source_role=role
    )
    return ParsedSource(relative, parsed.artifact.sha256, tuple(parsed.evidence_units))


def _tables(units: Iterable[m.EvidenceUnit]) -> dict[tuple[tuple[str, ...], int], dict[tuple[int, int], str]]:
    grids: dict[tuple[tuple[str, ...], int], dict[tuple[int, int], str]] = defaultdict(dict)
    for unit in units:
        if unit.modality != "TABLE" or unit.locator is None:
            continue
        locator = unit.locator
        if locator.table_index is None or locator.row is None or locator.column is None:
            continue
        key = (tuple(locator.heading_path), locator.table_index)
        grids[key][(locator.row, locator.column)] = (unit.content_text or "").strip()
    return grids


def _operations_for(text: str) -> list[str]:
    """Derive authorized operations from the *rubric* text of the construct.

    The v1.1 generator derived the operation from the oracle property
    description.  This function only ever sees authorized activity source, so a
    construct's operation cannot encode an expected verdict.
    """

    folded = _fold(text)

    def has(*markers: str) -> bool:
        return any(marker in folded for marker in markers)

    if has("no puede", "no permite", "limitacion", "limite", "alcance", "invalida", "incertidumbre"):
        return ["CRITIQUE_LIMITATION"]
    if has("calcul", "tasa", "denominador", "porcentaje", "cifra", "costo", "capacidad", "suma", "resta", "multiplic"):
        return ["RECONSTRUCT_REASONING"]
    if has("decision", "elige", "elegida", "alternativa", "trade off", "tradeoff", "riesgo", "recomend"):
        return ["JUSTIFY_DECISION"]
    if has("orden", "secuencia", "flujo", "temporal", "linea de tiempo", "primero", "correlacion"):
        return ["TRACE_FLOW"]
    if has("contradic", "coherencia", "incompatib", "entre artefactos", "conecta", "relacion", "integra"):
        return ["CONNECT_INTERNAL"]
    return ["INTERPRET_REPRESENTATION"]


_OBSERVABLE_BY_OPERATION = {
    "CONNECT_INTERNAL": (
        "Conecta unidades localizadas de la entrega y hace explicita su coherencia "
        "o su tension, sin elegir silenciosamente una sola fuente."
    ),
    "RECONSTRUCT_REASONING": (
        "Reconstruye la relacion o el calculo desde unidades localizadas y conserva "
        "cantidades, denominadores y alcance."
    ),
    "TRACE_FLOW": (
        "Traza el orden o el flujo observable a partir de las unidades de apoyo de "
        "la entrega."
    ),
    "CRITIQUE_LIMITATION": (
        "Delimita que sostienen las unidades localizadas y que no puede inferirse "
        "de ellas."
    ),
    "JUSTIFY_DECISION": (
        "Justifica una decision entre alternativas usando exclusivamente evidencia "
        "localizada en la entrega."
    ),
    "INTERPRET_REPRESENTATION": (
        "Relaciona el criterio con evidencia localizada sin ampliar fuentes ni "
        "atribuir intencion."
    ),
}


def _construct_entry(
    *,
    activity_id: str,
    activity_path: str,
    source_kind: str,
    source_relative: str,
    source_sha256: str,
    name: str,
    descriptor_pairs: list[tuple[str, str]],
    locator_ref: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Build one neutral, source-grounded construct catalog entry."""

    if descriptor_pairs:
        described = " ".join(
            f"[{label}] {text}" if label else text for label, text in descriptor_pairs
        )
        description = (
            f"Criterio autorizado de la actividad: \"{name}\". "
            f"Definicion segun la fuente autorizada: {described}"
        )
    else:
        description = f"Requisito autorizado de la actividad: \"{name}\"."
    description = description[:1200]
    operation_source = " ".join([name] + [text for _, text in descriptor_pairs])
    operations = _operations_for(operation_source)
    prefix = "RUBRIC" if source_kind == "RUBRIC_CRITERION" else "ASSIGNMENT"
    key = f"{prefix}::A{_activity_number(activity_path):02d}::{_slug(name)}"
    return {
        "construct_key": key,
        "activity_id": activity_id,
        "source_kind": source_kind,
        "canonical_source_name": name,
        "neutral_description": description,
        "authorized_operations": operations,
        "neutral_observable": _OBSERVABLE_BY_OPERATION[operations[0]],
        "source_refs": [locator_ref],
        "source_hashes": {source_relative: source_sha256},
        "provenance": provenance,
        "contains_expected_support_status": False,
        "contains_oracle_verdict": False,
    }


def build_construct_catalog(corpus_root: Path) -> dict[str, Any]:
    """Extract every authorized P06 target construct from real parser output.

    Rubric criteria/dimension tables are the preferred authority.  Activities
    whose rubric is informal prose contribute their assignment ``Tarea``
    requirements instead, so the catalog documents the full authorized construct
    space even where no property can resolve against it.
    """

    entries: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    for activity_dir in sorted(corpus_root.glob("activity_*")):
        activity_path = activity_dir.name
        activity_id = _activity_id_for(activity_dir)
        rubric = _parse(
            activity_dir / "02_rubric.docx", m.ArtifactRole.RUBRIC, "02_rubric.docx"
        )
        assignment = _parse(
            activity_dir / "01_assignment.docx",
            m.ArtifactRole.ASSIGNMENT_PROMPT,
            "01_assignment.docx",
        )
        activity_entries = _rubric_constructs(
            activity_id=activity_id, activity_path=activity_path, rubric=rubric
        )
        source_kind = "RUBRIC_CRITERION"
        if not activity_entries:
            activity_entries = _assignment_constructs(
                activity_id=activity_id,
                activity_path=activity_path,
                assignment=assignment,
            )
            source_kind = "ASSIGNMENT_REQUIREMENT" if activity_entries else "NONE"
        entries.extend(activity_entries)
        activities.append(
            {
                "activity_id": activity_id,
                "activity_path": activity_path,
                "construct_source_kind": source_kind,
                "construct_count": len(activity_entries),
                "rubric_sha256": rubric.sha256,
                "assignment_sha256": assignment.sha256,
                "rubric_has_criteria_table": source_kind == "RUBRIC_CRITERION",
            }
        )
    keys = [item["construct_key"] for item in entries]
    if len(keys) != len(set(keys)):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        raise ConstructResolutionError(f"duplicate construct keys: {duplicates}")
    material = {
        "schema_version": P06_CONSTRUCT_CATALOG_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V12_VERSION,
        "extraction_method": "REAL_PARSER_STRUCTURED_SOURCE_EXTRACTION",
        "activities": activities,
        "constructs": sorted(entries, key=lambda item: item["construct_key"]),
        "construct_count": len(entries),
    }
    return {**material, "catalog_hash": canonical_hash(material)}


def _activity_id_for(activity_dir: Path) -> str:
    import json

    ratification = json.loads(
        (activity_dir / "final_ratification.json").read_text(encoding="utf-8")
    )
    return str(ratification["activity_id"])


def _rubric_constructs(
    *, activity_id: str, activity_path: str, rubric: ParsedSource
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for (heading_path, table_index), cells in sorted(
        _tables(rubric.units).items(), key=lambda item: (item[0][0], item[0][1])
    ):
        rows = max(row for row, _ in cells) + 1
        columns = max(column for _, column in cells) + 1
        if rows < 3 or columns < 2:
            continue
        headers = [_fold(cells.get((0, column), "")) for column in range(columns)]
        name_column = next(
            (
                column
                for column, header in enumerate(headers)
                if header in _NAME_COLUMN_HEADERS
            ),
            None,
        )
        if name_column is None:
            continue
        descriptor_columns = [
            column
            for column in range(columns)
            if column != name_column and headers[column] not in _NON_SEMANTIC_HEADERS
        ]
        for row in range(1, rows):
            name = cells.get((row, name_column), "").strip()
            if not name:
                continue
            pairs = [
                (cells.get((0, column), "").strip(), cells.get((row, column), "").strip())
                for column in descriptor_columns
                if cells.get((row, column), "").strip()
            ]
            heading_label = "/".join(heading_path) if heading_path else "(root)"
            entries.append(
                _construct_entry(
                    activity_id=activity_id,
                    activity_path=activity_path,
                    source_kind="RUBRIC_CRITERION",
                    source_relative="02_rubric.docx",
                    source_sha256=rubric.sha256,
                    name=name,
                    descriptor_pairs=pairs,
                    locator_ref=(
                        f"{activity_path}/02_rubric.docx"
                        f"#{heading_label}[table={table_index},row={row}]"
                    ),
                    provenance={
                        "method": "RUBRIC_CRITERIA_TABLE_ROW",
                        "heading_path": list(heading_path),
                        "table_index": table_index,
                        "row": row,
                        "name_column": name_column,
                        "descriptor_columns": descriptor_columns,
                    },
                )
            )
    return entries


def _assignment_constructs(
    *, activity_id: str, activity_path: str, assignment: ParsedSource
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, unit in enumerate(assignment.units):
        locator = unit.locator
        if unit.modality != "LIST" or locator is None or not locator.heading_path:
            continue
        if _fold(locator.heading_path[-1]) not in _REQUIREMENT_HEADINGS:
            continue
        text = (unit.content_text or "").strip()
        if not text:
            continue
        entries.append(
            _construct_entry(
                activity_id=activity_id,
                activity_path=activity_path,
                source_kind="ASSIGNMENT_REQUIREMENT",
                source_relative="01_assignment.docx",
                source_sha256=assignment.sha256,
                name=text[:280],
                descriptor_pairs=[],
                locator_ref=(
                    f"{activity_path}/01_assignment.docx"
                    f"#{'/'.join(locator.heading_path)}[unit={index}]"
                ),
                provenance={
                    "method": "ASSIGNMENT_REQUIREMENT_LIST_ITEM",
                    "heading_path": list(locator.heading_path),
                    "unit_index": index,
                },
            )
        )
    return entries


# --------------------------------------------------------------------------
# Declarative property -> construct resolution
# --------------------------------------------------------------------------


def resolve_target_construct(
    description: str, constructs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve which authorized construct a P06 property targets.

    The resolution is declarative: the property must *name* its criterion.  A
    reference matches by exact folded name, by leading label (``D1.``), or by a
    unique word-boundary prefix (``Contextualizacion`` for ``Contextualizacion y
    madurez historiografica``).  Anything else fails closed.
    """

    by_name = {_fold(item["canonical_source_name"]): item for item in constructs}
    by_label: dict[str, dict[str, Any]] = {}
    for item in constructs:
        match = _LEADING_LABEL.match(item["canonical_source_name"])
        if match is not None:
            by_label[_fold(match.group(1))] = item

    references = [_fold(value) for value in _QUOTED.findall(description)]
    references.extend(_fold(token) for token in _LABEL_TOKEN.findall(description))

    matched: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, str]] = []
    for reference in references:
        if not reference:
            continue
        hit = by_name.get(reference) or by_label.get(reference)
        rule = "EXACT_NAME" if reference in by_name else "LEADING_LABEL"
        if hit is None:
            prefixed = [
                item
                for name, item in by_name.items()
                if name.startswith(f"{reference} ")
            ]
            if len(prefixed) == 1:
                hit, rule = prefixed[0], "UNIQUE_NAME_PREFIX"
        if hit is None:
            continue
        matched[hit["construct_key"]] = hit
        evidence.append(
            {"reference": reference, "construct_key": hit["construct_key"], "rule": rule}
        )

    if len(matched) == 1:
        construct = next(iter(matched.values()))
        return {
            "resolved": True,
            "construct_key": construct["construct_key"],
            "construct": construct,
            "match_evidence": evidence,
            "resolution_rule": "SINGLE_DECLARED_AUTHORIZED_CONSTRUCT",
        }
    if len(matched) > 1:
        return {
            "resolved": False,
            "disposition": NO_UNAMBIGUOUS_CONSTRUCT,
            "reason": (
                "The property declares more than one authorized construct, so a "
                "single P06 call cannot demonstrate or refute it as one gate."
            ),
            "candidate_construct_keys": sorted(matched),
            "match_evidence": evidence,
        }
    if not constructs:
        return {
            "resolved": False,
            "disposition": NO_PRODUCTION_REPRESENTATIVE,
            "reason": (
                "The activity exposes no structured authorized construct that "
                "production P04 could compile into a blueprint dimension."
            ),
            "candidate_construct_keys": [],
            "match_evidence": [],
        }
    return {
        "resolved": False,
        "disposition": NO_UNAMBIGUOUS_CONSTRUCT,
        "reason": (
            "The property names no authorized construct, so its target would have "
            "to be inferred. v1.1 inferred it from the evidence location; v1.2 "
            "fails closed instead."
        ),
        "candidate_construct_keys": [],
        "match_evidence": [],
    }


# --------------------------------------------------------------------------
# Production-representative P06 fixture (v1.2)
# --------------------------------------------------------------------------


def build_p06_fixture_v12(
    *,
    route_fixture_id: str,
    model_visible_definition: dict[str, Any],
    bundle: m.EvidenceBundle,
) -> tuple[m.EvidenceMapRequest, m.EvidenceMappingAliasEnvelope]:
    """Project one repaired route through the real production P06 boundary.

    Every model-visible field travels the production path
    ``AssessmentBlueprint -> dimension -> evidence variant -> question
    opportunity template -> EvidenceMappingAliasEnvelope``.  The envelope is
    produced by the product's own ``build_evidence_mapping_alias_envelope``,
    so the benchmark cannot expose a semantic surface production lacks.
    """

    operation = m.CognitiveOperation(model_visible_definition["cognitive_operation"])
    response_formats = [
        m.ResponseFormat(value) for value in model_visible_definition["response_formats"]
    ]
    requirement = model_visible_definition["evidence_requirement"]
    criterion_id = stable_id("criterion_p06_route_v12", route_fixture_id)
    outcome_id = stable_id("outcome_p06_route_v12", route_fixture_id)
    template = m.QuestionOpportunityTemplate(
        opportunity_template_id=stable_id("template_p06_route_v12", route_fixture_id),
        cognitive_operation=operation,
        focus=model_visible_definition["focus"],
        observable=model_visible_definition["observable"],
        difficulty=m.DifficultyBand.MEDIUM,
        target_minutes=5,
        allowed_anchor_structures=[m.AnchorStructure.SINGLE_FRAGMENT],
        allowed_response_formats=response_formats,
        verification_potential=0.9,
        minimum_quality=0.75,
        student_justification_required=True,
    )
    variant = m.EvidenceVariant(
        variant_id=stable_id("variant_p06_route_v12", route_fixture_id),
        name=model_visible_definition["construct"],
        description=model_visible_definition["construct_description"],
        evidence_requirement=m.EvidenceRequirement(
            allowed_modalities=[
                m.EvidenceModality(value) for value in requirement["allowed_modalities"]
            ],
            min_distinct_units=requirement["min_distinct_units"],
            min_extraction_confidence=0.70,
            min_alignment=0.65,
            cross_artifact_required=requirement["cross_artifact_required"],
            course_sources_allowed=False,
        ),
        verification_potential=0.9,
        supported_operations=[
            m.SupportedOperation(
                cognitive_operation=operation,
                support_strength=0.9,
                rationale=(
                    "El criterio autorizado de la actividad define una relacion "
                    "verificable sobre evidencia localizada de una sola entrega."
                ),
            )
        ],
        question_opportunities=[template],
    )
    dimension = m.BlueprintDimension(
        dimension_id=stable_id("dimension_p06_route_v12", route_fixture_id),
        name=model_visible_definition["construct"],
        criterion_ids=[criterion_id],
        learning_outcome_ids=[outcome_id],
        grading_weight=None,
        verification_priority=0.9,
        factors=m.VerificationFactors(
            learning_relevance=0.9,
            centrality=0.9,
            expected_evidence=0.9,
            discriminative_potential=0.9,
            auditability=0.9,
            short_response_observability=0.9,
        ),
        justification=model_visible_definition["construct_description"],
        evidence_variants=[variant],
    )
    planning_policy = m.AssessmentPlanningPolicy(
        policy_id=stable_id("planning_policy_p06_route_v12", route_fixture_id),
        minimum_opportunity_quality=0.75,
        minimum_evidence_fit=0.70,
        max_reserve_opportunities=0,
    )
    blueprint = m.AssessmentBlueprint(
        blueprint_id=stable_id("blueprint_p06_route_v12", route_fixture_id),
        blueprint_version=1,
        activity_id=bundle.activity_id,
        status=m.WorkflowStatus.APPROVED,
        context_mode=m.ContextMode.CLOSED,
        dimensions=[dimension],
        assessment_constraints=m.AssessmentConstraints(
            question_count=1,
            target_total_minutes=5,
            allowed_response_formats=response_formats,
            minimum_opportunity_quality=0.75,
            max_reserve_opportunities=0,
            priority_criterion_ids=[],
            required_criterion_ids=[criterion_id],
            structured_justification_policy=m.StructuredJustificationPolicy(
                mode=m.StructuredJustificationMode.ALL,
                selected_opportunity_template_ids=[],
            ),
        ),
        decision_ids=[],
        diagnostics=[],
        approved_by="user_benchmark_teacher",
        approved_at=FIXED_INSTANT,
    )
    request = m.EvidenceMapRequest(
        blueprint=blueprint,
        planning_policy=planning_policy,
        evidence_bundle=bundle,
    )
    return request, build_evidence_mapping_alias_envelope(request)


def model_visible_definition_for(
    construct: dict[str, Any], bundle: m.EvidenceBundle
) -> dict[str, Any]:
    """Build the model-visible route from the construct and the evidence scope.

    The definition never mentions where the supporting evidence sits.  Evidence
    location stays in evaluator-only provenance, which is what separates the
    target construct from the submission evidence location.
    """

    operation = construct["authorized_operations"][0]
    modalities = sorted({unit.modality.value for unit in bundle.evidence_units})
    return {
        "construct": construct["canonical_source_name"],
        "construct_description": construct["neutral_description"],
        "cognitive_operation": operation,
        "focus": (
            f"Determinar en que medida la entrega sostiene el criterio autorizado "
            f"\"{construct['canonical_source_name']}\", usando exclusivamente la "
            f"evidencia de esta entrega y el alcance autorizado de la actividad."
        ),
        "observable": construct["neutral_observable"],
        "evidence_requirement": {
            # Neutral by construction: the benchmark must not encode how much
            # evidence a given submission happens to contain, because that would
            # constrain the support status the model may report.
            "allowed_modalities": modalities,
            "min_distinct_units": 1,
            "cross_artifact_required": False,
        },
        "response_formats": ["OPEN_SHORT"],
    }


def route_semantic_identity(model_visible_definition: dict[str, Any]) -> str:
    """Hash the semantics a candidate can actually distinguish.

    Two routes with the same identity are indistinguishable to the model, no
    matter how different their fixture ids are.
    """

    return canonical_hash(
        {
            "construct": model_visible_definition["construct"],
            "construct_description": model_visible_definition["construct_description"],
            "cognitive_operation": model_visible_definition["cognitive_operation"],
            "focus": model_visible_definition["focus"],
            "observable": model_visible_definition["observable"],
            "evidence_requirement": model_visible_definition["evidence_requirement"],
            "response_formats": model_visible_definition["response_formats"],
        }
    )
