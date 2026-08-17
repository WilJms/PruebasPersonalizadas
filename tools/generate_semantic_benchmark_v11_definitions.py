#!/usr/bin/env python3
"""Author explicit Phase 8.1 semantic fixture definitions.

This is an offline curation utility.  It reads the frozen corpus and its
ratification authority to write benchmark definitions outside the corpus.  The
runtime benchmark consumes the resulting JSON; it never derives model-visible
fields from oracle descriptions during a qualification run.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import pretty_json  # noqa: E402
from comprehension_verification.contracts import models as m  # noqa: E402
from comprehension_verification.parsers.service import SafeParserService  # noqa: E402


CORPUS_ROOT = REPOSITORY_ROOT / "evaluation/corpora/pruebas_personalizadas/v1"
DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_1"
FIXTURE_ROOT = DEFINITION_ROOT / "fixtures"
TENANT_ID = "tenant_semantic_benchmark"
BENCHMARK_VERSION = "semantic-benchmark/1.1.0"

STOPWORDS = {
    "a",
    "al",
    "con",
    "contra",
    "de",
    "del",
    "el",
    "en",
    "es",
    "esta",
    "este",
    "la",
    "las",
    "lo",
    "los",
    "no",
    "o",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "sus",
    "un",
    "una",
    "y",
}


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        re.sub(r"[^a-z0-9]+", " ", decomposed.encode("ascii", "ignore").decode()).split()
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalized(value).split()
        if len(token) > 2 and token not in STOPWORDS
    }


def _activity_number(activity_id: str) -> int:
    return int(activity_id.split("_", 2)[1])


def _submission_number(submission_id: str) -> int:
    return int(submission_id.rsplit("_", 1)[1])


def _unit_row(unit: m.EvidenceUnit) -> dict[str, Any]:
    return {
        "evidence_id": unit.evidence_id,
        "normalized_hash": unit.normalized_hash,
        "locator": unit.locator.model_dump(mode="json", exclude_none=True),
    }


def _is_noise(unit: m.EvidenceUnit) -> bool:
    value = _normalized(unit.content_text or "")
    return not value or re.fullmatch(r"pagina \d+", value) is not None


def _ranked_units(
    units: list[m.EvidenceUnit],
    *,
    section: str | None,
    description: str,
    limit: int = 3,
) -> list[m.EvidenceUnit]:
    section_value = _normalized(section or "")
    section_tokens = _tokens(section or "")
    description_tokens = _tokens(description)
    scored: list[tuple[float, int, m.EvidenceUnit]] = []
    for index, unit in enumerate(units):
        if _is_noise(unit):
            continue
        content = _normalized(unit.content_text or "")
        content_tokens = _tokens(unit.content_text or "")
        locator = unit.locator.model_dump(mode="json", exclude_none=True)
        heading = _normalized(" ".join(locator.get("heading_path", [])))
        score = 0.0
        if section_value:
            if section_value == content or section_value in heading:
                score += 100.0
            elif section_value in content:
                score += 60.0
            score += 8.0 * len(section_tokens & content_tokens)
        score += 1.0 * len(description_tokens & content_tokens)
        scored.append((score, index, unit))
    if not scored:
        raise RuntimeError("source reference has no non-noise EvidenceUnit")
    scored.sort(key=lambda value: (-value[0], value[1]))
    selected = scored[:limit]
    if section_value and selected[0][0] <= 0:
        raise RuntimeError(f"section cannot be resolved: {section}")
    return [value[2] for value in sorted(selected, key=lambda value: value[1])]


def _operation(description: str, *, cross_artifact: bool) -> str:
    value = _normalized(description)
    if cross_artifact or any(
        marker in value
        for marker in ("reconcili", "contradic", "incompatib", "coherencia entre")
    ):
        return "CONNECT_INTERNAL"
    if any(
        marker in value
        for marker in (
            "calculo",
            "aritmet",
            "porcentaje",
            "promedio",
            "tasa",
            "costo",
            "capacidad",
            "denominador",
        )
    ):
        return "RECONSTRUCT_REASONING"
    if any(marker in value for marker in ("traza", "bucle", "orden", "flujo")):
        return "TRACE_FLOW"
    if any(
        marker in value
        for marker in (
            "limitacion",
            "alcance",
            "no puede inferir",
            "no permite",
            "sesgo",
            "inciert",
            "ausente",
            "omision",
        )
    ):
        return "CRITIQUE_LIMITATION"
    if any(
        marker in value
        for marker in ("alternativa", "decision", "trade off", "defendible", "elegir")
    ):
        return "JUSTIFY_DECISION"
    return "INTERPRET_REPRESENTATION"


def _construct(description: str, sections: Iterable[str]) -> str:
    value = _normalized(description)
    if any(marker in value for marker in ("obedec", "fuente externa", "pii", "privacidad")):
        base = "Restricciones de fuente y seguridad"
    elif any(
        marker in value
        for marker in ("calculo", "porcentaje", "promedio", "tasa", "costo", "capacidad")
    ):
        base = "Relación cuantitativa localizada"
    elif any(marker in value for marker in ("contradic", "incompatib", "reconcili")):
        base = "Coherencia entre afirmaciones y evidencia"
    elif any(marker in value for marker in ("limitacion", "alcance", "no puede", "inciert")):
        base = "Límite inferencial y alcance"
    elif any(marker in value for marker in ("alternativa", "decision", "trade off")):
        base = "Decisión sustentada entre alternativas"
    else:
        base = "Relación entre afirmación y evidencia"
    labels = [" ".join(section.split()) for section in sections if section]
    return f"{base}: {labels[0]}" if labels else base


def _focus(construct: str) -> str:
    return (
        f"Examinar {construct.casefold()} usando exclusivamente la evidencia "
        "localizada y el alcance autorizado de la actividad."
    )


def _observable(operation: str) -> str:
    return {
        "CONNECT_INTERNAL": (
            "Conecta unidades localizadas y hace explícita su coherencia o tensión "
            "sin elegir silenciosamente una fuente."
        ),
        "RECONSTRUCT_REASONING": (
            "Reconstruye una relación o cálculo desde unidades localizadas y conserva "
            "cantidades, denominadores y alcance."
        ),
        "TRACE_FLOW": (
            "Traza el orden o flujo observable desde las unidades de apoyo indicadas."
        ),
        "CRITIQUE_LIMITATION": (
            "Delimita qué sostienen las unidades y qué no puede inferirse de ellas."
        ),
        "JUSTIFY_DECISION": (
            "Justifica una decisión entre alternativas mediante evidencia localizada."
        ),
        "INTERPRET_REPRESENTATION": (
            "Relaciona una afirmación con evidencia localizada sin ampliar fuentes ni "
            "atribuir intención."
        ),
    }[operation]


def _difficulty(value: str) -> str:
    return {
        "simple": "LOW",
        "intermedia": "MEDIUM",
        "intermedio": "MEDIUM",
        "dificil": "HIGH",
    }[value.casefold()]


def _fixture_tags(
    prop: dict[str, Any],
    submission_tags: list[str],
    support: list[m.EvidenceUnit],
) -> list[str]:
    tags = set(prop["benchmark_tags"])
    description = _normalized(prop["description"])
    text = _normalized(" ".join(item.content_text or "" for item in support))
    if "SIMULATED_PII" in submission_tags and (
        any(marker in text for marker in ("example invalid", "clin sim", "diagnostico simulado"))
        or any(marker in description for marker in ("pii", "nombre", "telefono", "correo", "identificador"))
    ):
        tags.add("SIMULATED_PII")
    if "PROMPT_INJECTION_SILENT" in submission_tags and (
        any(marker in description for marker in ("obedec", "docstring", "plantilla", "comentario html", "pie"))
        or any(marker in text for marker in ("override", "system", "no corresponde formular", "evaluador"))
    ):
        tags.add("PROMPT_INJECTION_SILENT")
    if "PROMPT_INJECTION_NOISY" in submission_tags and (
        any(marker in description for marker in ("obedec", "instruccion", "directiva"))
        or any(marker in text for marker in ("system", "override", "ignore", "instruccion"))
    ):
        tags.add("PROMPT_INJECTION_NOISY")
    if "TECHNICAL_STRING_NOT_INSTRUCTION" in submission_tags and any(
        marker in description for marker in ("cadena", "hash", "formula", "directiva")
    ):
        tags.add("TECHNICAL_STRING_NOT_INSTRUCTION")
    if "EXTERNAL_KNOWLEDGE_TRAP" in submission_tags and any(
        marker in description for marker in ("extern", "inventad", "biografi", "mecanismo")
    ):
        tags.add("EXTERNAL_KNOWLEDGE_TRAP")
    if "KEYWORDS_WITHOUT_RELATION" in submission_tags and any(
        marker in description for marker in ("vocabulario", "definicion", "formula academica", "etiqueta")
    ):
        tags.add("KEYWORDS_WITHOUT_RELATION")
    return sorted(tags)


class CorpusIndex:
    def __init__(self) -> None:
        self.ratifications: list[dict[str, Any]] = []
        self.units_by_relative: dict[str, list[m.EvidenceUnit]] = {}
        self.bundle_units: dict[tuple[str, str], list[m.EvidenceUnit]] = {}
        self.artifact_by_evidence_id: dict[str, str] = {}
        parser = SafeParserService()
        for rat_path in sorted(CORPUS_ROOT.glob("activity_*/final_ratification.json")):
            rat = json.loads(rat_path.read_text(encoding="utf-8"))
            self.ratifications.append(rat)
            activity_path = rat["activity_path"]
            for filename, role in (
                ("01_assignment.docx", m.ArtifactRole.ASSIGNMENT_PROMPT),
                ("02_rubric.docx", m.ArtifactRole.RUBRIC),
            ):
                relative = f"{activity_path}/{filename}"
                parsed = parser.parse(
                    CORPUS_ROOT / relative,
                    tenant_id=TENANT_ID,
                    source_role=role,
                )
                self.units_by_relative[relative] = list(parsed.evidence_units)
                for unit in parsed.evidence_units:
                    self.artifact_by_evidence_id[unit.evidence_id] = relative
            for submission in rat["submissions"]:
                bundle: list[m.EvidenceUnit] = []
                for filename in submission["artifacts"]:
                    relative = f"{activity_path}/{filename}"
                    parsed = parser.parse(
                        CORPUS_ROOT / relative,
                        tenant_id=TENANT_ID,
                        source_role=m.ArtifactRole.SUBMISSION,
                        submission_id=submission["submission_id"],
                    )
                    units = list(parsed.evidence_units)
                    self.units_by_relative[relative] = units
                    bundle.extend(units)
                    for unit in units:
                        self.artifact_by_evidence_id[unit.evidence_id] = relative
                self.bundle_units[(rat["activity_id"], submission["submission_id"])] = bundle

    def resolve(
        self,
        rat: dict[str, Any],
        ref: dict[str, Any],
        description: str,
        *,
        limit: int = 3,
    ) -> tuple[str, list[m.EvidenceUnit]]:
        relative = f"{rat['activity_path']}/{ref['file']}"
        units = self.units_by_relative[relative]
        return relative, _ranked_units(
            units,
            section=ref.get("section"),
            description=description,
            limit=limit,
        )


def _all_properties(index: CorpusIndex) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for rat in index.ratifications:
        for raw in rat["activity_level_properties"]:
            values.append({"ratification": rat, "submission_id": None, "raw": raw})
        for submission in rat["submissions"]:
            for raw in submission["properties"]:
                values.append(
                    {
                        "ratification": rat,
                        "submission_id": submission["submission_id"],
                        "raw": raw,
                    }
                )
    return sorted(values, key=lambda value: value["raw"]["property_id"])


def _source_provenance(
    index: CorpusIndex,
    rat: dict[str, Any],
    prop: dict[str, Any],
    *,
    target_submission_id: str | None,
) -> tuple[list[dict[str, Any]], list[m.EvidenceUnit]]:
    provenance: list[dict[str, Any]] = []
    submission_support: list[m.EvidenceUnit] = []
    for ref in prop["source_refs"]:
        relative, units = index.resolve(rat, ref, prop["description"])
        is_submission = ref["file"].startswith("submissions/")
        role = "SUBMISSION_SUPPORT" if is_submission else "SOURCE_CONTEXT"
        provenance.append(
            {
                "relative_ref": relative
                + (f"#{ref['section']}" if ref.get("section") else ""),
                "role": role,
                "resolved_units": [_unit_row(unit) for unit in units],
            }
        )
        if is_submission and target_submission_id is not None:
            submission_support.extend(units)
    unique = {unit.evidence_id: unit for unit in submission_support}
    return provenance, list(unique.values())


def build_routes(index: CorpusIndex, properties: list[dict[str, Any]]) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    counters: defaultdict[tuple[str, str], int] = defaultdict(int)
    for value in properties:
        prop = value["raw"]
        submission_id = value["submission_id"]
        if prop["stage"] != "P06" or submission_id is None or prop["oracle_state"] == "NOT_APPLICABLE":
            continue
        rat = value["ratification"]
        key = (rat["activity_id"], submission_id)
        counters[key] += 1
        route_id = (
            f"P06-A{_activity_number(rat['activity_id']):02d}-"
            f"S{_submission_number(submission_id):02d}-R{counters[key]:02d}"
        )
        provenance, submission_support = _source_provenance(
            index, rat, prop, target_submission_id=submission_id
        )
        bundle = index.bundle_units[key]
        artifact_count = len({unit.artifact_id for unit in submission_support})
        operation = _operation(prop["description"], cross_artifact=artifact_count > 1)
        construct = _construct(
            prop["description"],
            [ref.get("section", "") for ref in prop["source_refs"]],
        )
        modalities = sorted({unit.modality.value for unit in bundle})
        submission = next(
            item for item in rat["submissions"] if item["submission_id"] == submission_id
        )
        fixture_tags = [
            tag
            for tag in submission["benchmark_tags"]
            if tag
            in {
                "PROMPT_INJECTION_NOISY",
                "PROMPT_INJECTION_SILENT",
                "SIMULATED_PII",
                "TECHNICAL_STRING_NOT_INSTRUCTION",
            }
        ]
        if "UNCERTAIN" in prop["description"].upper():
            fixture_tags.append("P06_UNCERTAIN")
        routes.append(
            {
                "route_fixture_id": route_id,
                "activity_id": rat["activity_id"],
                "submission_id": submission_id,
                "model_visible_definition": {
                    "construct": construct,
                    "cognitive_operation": operation,
                    "focus": _focus(construct),
                    "observable": _observable(operation),
                    "evidence_requirement": {
                        "allowed_modalities": modalities,
                        "min_distinct_units": 1,
                        "cross_artifact_required": artifact_count > 1,
                    },
                    "response_formats": ["OPEN_SHORT"],
                },
                "source_provenance": provenance,
                "fixture_tags": sorted(set(fixture_tags)),
                "oracle_binding_metadata": {"property_ids": [prop["property_id"]]},
                "fixture_derivation_provenance": {
                    "authority_ref": (
                        f"{rat['activity_path']}/final_ratification.json#property:"
                        f"{prop['property_id']}"
                    ),
                    "method": "CURATED_NEUTRAL_ROUTE_FROM_SOURCE_REFS",
                },
            }
        )
    return {
        "schema_version": "semantic-p06-route-definitions/1.1.0",
        "benchmark_version": BENCHMARK_VERSION,
        "routes": routes,
    }


P07_EXPLICIT_SUPPORT_SELECTIONS: dict[str, tuple[str, ...]] = {
    # The three exact source refs for this cross-artifact opportunity resolve to
    # nine units, while QuestionOpportunity permits at most eight.  The bare
    # heading "Orden efectivo:" carries no evidence independently, so the
    # fixture authority explicitly excludes it instead of silently slicing the
    # resolved set.
    "A11-S01-P4": (
        "ev_9163391d77bbfe35b761",
        "ev_91cd6819c14468f2e754",
        "ev_8f097d2759b2503580f4",
        "ev_db45aac6022307076e27",
        "ev_1cf3f0b4fee23c0fda53",
        "ev_9ee9eedafc5177c8a853",
        "ev_1533d698521b28deb076",
        "ev_29280bdb46a33f37c0dc",
    ),
}


def build_opportunities(
    index: CorpusIndex, properties: list[dict[str, Any]]
) -> dict[str, Any]:
    opportunities: list[dict[str, Any]] = []
    counters: defaultdict[tuple[str, str], int] = defaultdict(int)
    for value in properties:
        prop = value["raw"]
        submission_id = value["submission_id"]
        if prop["stage"] != "P07" or submission_id is None:
            continue
        rat = value["ratification"]
        key = (rat["activity_id"], submission_id)
        counters[key] += 1
        opportunity_id = (
            f"P07-A{_activity_number(rat['activity_id']):02d}-"
            f"S{_submission_number(submission_id):02d}-O{counters[key]:02d}"
        )
        provenance, support = _source_provenance(
            index, rat, prop, target_submission_id=submission_id
        )
        if not support:
            # Activity/rubric-only rules may later be bound as submission-wide
            # observations, but they cannot manufacture an opportunity without
            # exact submission support.
            continue
        support = list({unit.evidence_id: unit for unit in support}.values())
        if len(support) > 8:
            selected_ids = P07_EXPLICIT_SUPPORT_SELECTIONS.get(prop["property_id"])
            resolved_by_id = {unit.evidence_id: unit for unit in support}
            if (
                not selected_ids
                or len(selected_ids) > 8
                or not set(selected_ids).issubset(resolved_by_id)
            ):
                raise RuntimeError(
                    "P07 exact support exceeds the contract cap without an explicit "
                    f"selection: {prop['property_id']}"
                )
            support = [resolved_by_id[evidence_id] for evidence_id in selected_ids]
        artifact_count = len({unit.artifact_id for unit in support})
        operation = _operation(prop["description"], cross_artifact=artifact_count > 1)
        construct = _construct(
            prop["description"],
            [ref.get("section", "") for ref in prop["source_refs"]],
        )
        if artifact_count > 1:
            anchors = ["CROSS_ARTIFACT"]
        elif any(
            unit.modality
            in {m.EvidenceModality.CODE_SYMBOL, m.EvidenceModality.CODE_SPAN}
            for unit in support
        ):
            anchors = ["CODE_CONTEXT"]
        elif len(support) > 1:
            anchors = ["PAIRED_FRAGMENTS"]
        else:
            anchors = ["SINGLE_FRAGMENT"]
        submission = next(
            item for item in rat["submissions"] if item["submission_id"] == submission_id
        )
        opportunities.append(
            {
                "opportunity_fixture_id": opportunity_id,
                "activity_id": rat["activity_id"],
                "submission_id": submission_id,
                "dimension_fixture_ref": f"benchmark-dimension://{opportunity_id}",
                "variant_fixture_ref": f"benchmark-variant://{opportunity_id}",
                "model_visible_definition": {
                    "operation": operation,
                    "focus": _focus(construct),
                    "observable": _observable(operation),
                    "support_evidence_ids": [unit.evidence_id for unit in support],
                    "allowed_anchor_structures": anchors,
                    "response_format": "OPEN_SHORT",
                    "difficulty": _difficulty(rat["difficulty_declared"]),
                    "target_minutes": 5,
                    "student_justification_required": True,
                },
                "source_provenance": provenance,
                "fixture_tags": _fixture_tags(
                    prop, submission["benchmark_tags"], support
                ),
                "oracle_binding_metadata": {"property_ids": [prop["property_id"]]},
                "fixture_derivation_provenance": {
                    "authority_ref": (
                        f"{rat['activity_path']}/final_ratification.json#property:"
                        f"{prop['property_id']}"
                    ),
                    "method": "CURATED_NEUTRAL_OPPORTUNITY_FROM_EXACT_SUPPORT",
                },
            }
        )
    return {
        "schema_version": "semantic-p07-opportunity-definitions/1.1.0",
        "benchmark_version": BENCHMARK_VERSION,
        "opportunities": opportunities,
    }


P09_SUBMISSION_UNIT_SELECTIONS: dict[str, dict[str, dict[str, dict[str, list[int]]]]] = {
    "p09_fixture_act_03": {
        "P09-A03-Q01": {
            "support": {"submissions/submission_05.pdf#Elección y tabla de cálculos": [3, 6, 7, 8, 9, 10, 11, 12]},
            "visible": {"submissions/submission_05.pdf#Elección y tabla de cálculos": [3, 6, 7, 8, 9, 10, 11, 12]},
        },
        "P09-A03-Q02": {
            "support": {"submissions/submission_05.pdf#Punto de comparación y sensibilidad": list(range(18, 23))},
            "visible": {"submissions/submission_05.pdf#Punto de comparación y sensibilidad": list(range(18, 23))},
        },
        "P09-A03-Q03": {
            "support": {"submissions/submission_05.pdf#Regla de revisión": [31, 32]},
            "visible": {"submissions/submission_05.pdf#Regla de revisión": [31, 32]},
        },
    },
    "p09_fixture_act_04": {
        "P09-A04-Q01": {
            "support": {
                "submissions/submission_06_artifact_01.md#Función y caso de demostración": [1, 2, 3, 4],
                "submissions/submission_06_artifact_02.txt#Afirmación de pureza": [1, 6],
            },
            "visible": {
                "submissions/submission_06_artifact_01.md#Función y caso de demostración": [1, 2, 3, 4],
                "submissions/submission_06_artifact_02.txt#Afirmación de pureza": [1, 6],
            },
        },
        "P09-A04-Q02": {
            "support": {
                "submissions/submission_06_artifact_01.md#Comprensión unicas y demo": [1, 3, 4],
                "submissions/submission_06_artifact_02.txt#Afirmación sobre primera aparición": [1, 4],
            },
            "visible": {
                "submissions/submission_06_artifact_01.md#Comprensión unicas y demo": [1, 3, 4],
                "submissions/submission_06_artifact_02.txt#Afirmación sobre primera aparición": [1, 4],
            },
        },
        "P09-A04-Q03": {
            "support": {
                "submissions/submission_06_artifact_01.md#Bucle por grupo": [1, 4],
                "submissions/submission_06_artifact_02.txt#Afirmación de orden global": [2, 5],
            },
            "visible": {
                "submissions/submission_06_artifact_01.md#Bucle por grupo": [1, 4],
                "submissions/submission_06_artifact_02.txt#Afirmación de orden global": [2, 5],
            },
        },
    },
    "p09_fixture_act_09": {
        "P09-A09-Q01": {
            "support": {"submissions/submission_05.pdf#Secuencia y mecanismos": [7, 17, 18, 19, 20]},
            "visible": {"submissions/submission_05.pdf#Secuencia y mecanismos": [7, 17, 18, 19, 20]},
        },
        "P09-A09-Q02": {
            "support": {"submissions/submission_05.pdf#Contraargumento e interacción entre factores": [22, 23, 24, 25, 26, 55, 56, 57]},
            "visible": {"submissions/submission_05.pdf#Contraargumento e interacción entre factores": [22, 23, 24, 25, 26, 55, 56, 57]},
        },
        "P09-A09-Q03": {
            "support": {"submissions/submission_05.pdf#Tres cantidades y cautela inferencial": [27, 30, 31, 33, 34, 93, 94, 95]},
            "visible": {"submissions/submission_05.pdf#Tres cantidades y cautela inferencial": [27, 30, 31, 33, 34, 93, 94, 95]},
        },
    },
    "p09_fixture_act_12": {
        "P09-A12-Q01": {
            "support": {"submissions/submission_06_artifact_02.md#Cabecera y datos simulados": [1, 2, 3, 4]},
            "visible": {"submissions/submission_06_artifact_02.md#Cabecera y datos simulados": [1, 2, 3]},
        },
        "P09-A12-Q02": {
            "support": {
                "submissions/submission_06_artifact_01.txt#Cálculos no completados": [2, 3],
                "submissions/submission_06_artifact_02.md#Ausencia de asignación": [5],
            },
            "visible": {
                "submissions/submission_06_artifact_01.txt#Cálculos no completados": [2, 3],
                "submissions/submission_06_artifact_02.md#Ausencia de asignación": [5],
            },
        },
        "P09-A12-Q03": {
            "support": {"submissions/submission_06_artifact_02.md#Declaración no sustentada de confianza": [2, 7, 10]},
            "visible": {"submissions/submission_06_artifact_02.md#Declaración no sustentada de confianza": [7, 10]},
        },
    },
}


def build_p09_bindings(index: CorpusIndex) -> dict[str, Any]:
    rat_by_id = {value["activity_id"]: value for value in index.ratifications}
    fixtures: list[dict[str, Any]] = []
    for fixture_path in sorted((CORPUS_ROOT / "benchmark_fixtures/p09").glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        rat = rat_by_id[fixture["activity_id"]]
        selections = P09_SUBMISSION_UNIT_SELECTIONS[fixture["fixture_id"]]
        questions: list[dict[str, Any]] = []
        for question in fixture["questions"]:
            selected = selections[question["question_fixture_id"]]

            def rows(kind: str, declared: list[str]) -> list[dict[str, Any]]:
                result: list[dict[str, Any]] = []
                for ref in declared:
                    filename, _, section = ref.partition("#")
                    relative = f"{rat['activity_path']}/{filename}"
                    if filename.startswith("submissions/"):
                        numbers = selected[kind][ref]
                        units = index.units_by_relative[relative]
                        resolved = [units[number - 1] for number in numbers]
                        role = "SUBMISSION_SUPPORT"
                    else:
                        resolved = _ranked_units(
                            index.units_by_relative[relative],
                            section=section,
                            description=question["question_text"],
                            limit=3,
                        )
                        role = "SOURCE_CONTEXT"
                    result.append(
                        {
                            "declared_ref": ref,
                            "role": role,
                            "resolved_units": [_unit_row(unit) for unit in resolved],
                        }
                    )
                return result

            questions.append(
                {
                    "question_fixture_id": question["question_fixture_id"],
                    "support_refs": rows("support", question["support_refs"]),
                    "visible_anchor_refs": rows(
                        "visible", question["visible_anchor_refs"]
                    ),
                }
            )
        fixtures.append(
            {
                "fixture_id": fixture["fixture_id"],
                "activity_id": fixture["activity_id"],
                "submission_id": fixture["submission_id"],
                "questions": questions,
            }
        )
    return {
        "schema_version": "semantic-p09-locator-bindings/1.1.0",
        "benchmark_version": BENCHMARK_VERSION,
        "resolver_version": "p09-exact-locator-resolver/1.0.0",
        "fixtures": fixtures,
    }


def _case_id_for_route(route: dict[str, Any]) -> str:
    return "PP-" + route["route_fixture_id"].removeprefix("P06-").replace("-R", "-P06-R")


def _case_id_for_opportunity(opportunity: dict[str, Any]) -> str:
    return "PP-" + opportunity["opportunity_fixture_id"].removeprefix("P07-").replace("-O", "-P07-O")


TOPICAL_MARKER_FAMILIES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "SIMULATED_PII",
        ("pii", "privacidad", "correo simulado", "informacion sensible"),
        ("SIMULATED_PII",),
    ),
    (
        "PROMPT_INJECTION",
        ("obedec", "prompt injection", "comentario html", "docstring"),
        ("PROMPT_INJECTION_NOISY", "PROMPT_INJECTION_SILENT"),
    ),
    (
        "CONCEPTUAL_OMISSION",
        ("omision", "hueco conceptual"),
        ("DECLARED_CONCEPTUAL_OMISSION", "SELF_DECLARED_GAP", "SILENT_CONCEPTUAL_GAP"),
    ),
    (
        "ANSWER_LEAKAGE",
        ("leakage",),
        ("ANSWER_VISIBLE", "PREMISE_VISIBLE", "VISIBLE_ANCHOR_RISK"),
    ),
)

# Normative kinds constrain the wording of a produced question, so they are
# bindable to a sibling opportunity whenever that opportunity really exercises
# the condition.  Advisory kinds describe what the corpus is good for and never
# become case assertions.
NORMATIVE_PROPERTY_KINDS = frozenset({"PROHIBITED", "REQUIRED"})


def _topical_marker(description: str) -> tuple[str, tuple[str, ...]] | None:
    """Return the first topical family whose marker occurs in ``description``."""

    for family, markers, tags in TOPICAL_MARKER_FAMILIES:
        if any(marker in description for marker in markers):
            return family, tags
    return None


def build_property_bindings(
    properties: list[dict[str, Any]],
    routes_document: dict[str, Any],
    opportunities_document: dict[str, Any],
) -> dict[str, Any]:
    routes = routes_document["routes"]
    opportunities = opportunities_document["opportunities"]
    route_by_property = {
        property_id: route
        for route in routes
        for property_id in route["oracle_binding_metadata"]["property_ids"]
    }
    opportunity_by_property = {
        property_id: opportunity
        for opportunity in opportunities
        for property_id in opportunity["oracle_binding_metadata"]["property_ids"]
    }
    p06_cases_by_activity: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    p07_cases_by_activity: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    p07_cases_by_submission: defaultdict[
        tuple[str, str], list[tuple[str, dict[str, Any]]]
    ] = defaultdict(list)
    for route in routes:
        p06_cases_by_activity[route["activity_id"]].append((_case_id_for_route(route), route))
    for opportunity in opportunities:
        pair = (_case_id_for_opportunity(opportunity), opportunity)
        p07_cases_by_activity[opportunity["activity_id"]].append(pair)
        p07_cases_by_submission[
            (opportunity["activity_id"], opportunity["submission_id"])
        ].append(pair)
    p09_fixture_by_activity = {
        "act_03_puesto_de_limonada": ("PP-A03-P09-F01", "p09_fixture_act_03", "submission_05"),
        "act_04_asignador_de_turnos": ("PP-A04-P09-F01", "p09_fixture_act_04", "submission_06"),
        "act_09_renovacion_y_desplazamiento": ("PP-A09-P09-F01", "p09_fixture_act_09", "submission_05"),
        "act_12_clinica_movil": ("PP-A12-P09-F01", "p09_fixture_act_12", "submission_06"),
    }
    rows: list[dict[str, Any]] = []
    for value in properties:
        rat = value["ratification"]
        prop = value["raw"]
        property_id = prop["property_id"]
        stage = prop["stage"]
        submission_id = value["submission_id"]
        cases: list[str] = []
        fixture_id: str | None = None
        scope = "CASE_SPECIFIC"
        status = "ALIGNED"
        reason: str | None = None
        selector: dict[str, Any] = {"kind": "NONE", "detail": {}}
        if prop["oracle_state"] == "NOT_APPLICABLE":
            scope = "EXPLICITLY_EXCLUDED"
            status = "NOT_APPLICABLE"
            reason = "SOURCE_ORACLE_NOT_APPLICABLE"
        elif stage == "P04":
            if submission_id is None:
                cases = [f"PP-A{_activity_number(rat['activity_id']):02d}-P04-001"]
                fixture_id = f"p04:{rat['activity_id']}"
                scope = "ACTIVITY_WIDE"
                selector = {
                    "kind": "STAGE_ACTIVITY_FIXTURE",
                    "detail": {"activity_id": rat["activity_id"]},
                }
            else:
                scope = "EXPLICITLY_EXCLUDED"
                status = "EXPLICITLY_EXCLUDED"
                reason = "P04_INPUT_EXCLUDES_SUBMISSIONS_BY_STAGE_CONTRACT"
        elif stage == "P06":
            if submission_id is not None:
                route = route_by_property[property_id]
                cases = [_case_id_for_route(route)]
                fixture_id = route["route_fixture_id"]
                selector = {
                    "kind": "OWN_FIXTURE",
                    "detail": {"fixture_id": route["route_fixture_id"]},
                }
            else:
                candidates = p06_cases_by_activity[rat["activity_id"]]
                source_submissions = {
                    match.group(1)
                    for ref in prop["source_refs"]
                    if (match := re.search(r"submissions/(submission_\d+)", ref["file"]))
                }
                selected = [
                    (case_id, route)
                    for case_id, route in candidates
                    if not source_submissions
                    or route["submission_id"] in source_submissions
                ]
                if selected:
                    cases = [case_id for case_id, _route in selected]
                    fixture_id = selected[0][1]["route_fixture_id"]
                    scope = "ACTIVITY_WIDE"
                    selector = {
                        "kind": (
                            "SOURCE_SUBMISSION_REFS"
                            if source_submissions
                            else "ACTIVITY_STAGE_EXHAUSTIVE"
                        ),
                        "detail": {
                            "activity_id": rat["activity_id"],
                            "submission_ids": sorted(source_submissions),
                        },
                    }
                else:
                    scope = "EXPLICITLY_EXCLUDED"
                    status = "EXPLICITLY_EXCLUDED"
                    reason = "NO_UNAMBIGUOUS_P06_STAGE_LOCAL_ROUTE_FIXTURE"
        elif stage == "P07":
            if submission_id is not None:
                opportunity = opportunity_by_property.get(property_id)
                if opportunity is not None:
                    cases = [_case_id_for_opportunity(opportunity)]
                    fixture_id = opportunity["opportunity_fixture_id"]
                    selector = {
                        "kind": "OWN_FIXTURE",
                        "detail": {
                            "fixture_id": opportunity["opportunity_fixture_id"]
                        },
                    }
                else:
                    siblings = p07_cases_by_submission[
                        (rat["activity_id"], submission_id)
                    ]
                    description = _normalized(prop["description"])
                    marker = _topical_marker(description)
                    if marker is not None:
                        family, marker_tags = marker
                        candidates = [
                            pair
                            for pair in siblings
                            if set(marker_tags) & set(pair[1]["fixture_tags"])
                        ]
                    else:
                        family, marker_tags = "", ()
                        candidates = list(siblings)
                    if prop["kind"] in NORMATIVE_PROPERTY_KINDS and candidates:
                        cases = [case_id for case_id, _opportunity in candidates]
                        fixture_id = candidates[0][1]["opportunity_fixture_id"]
                        scope = "SUBMISSION_WIDE"
                        selector = {
                            "kind": (
                                "TOPICAL_MARKER" if marker else "SUBMISSION_EXHAUSTIVE"
                            ),
                            "detail": {
                                "activity_id": rat["activity_id"],
                                "submission_id": submission_id,
                                "marker_family": family,
                                "marker_tags": sorted(marker_tags),
                            },
                        }
                    else:
                        scope = "EXPLICITLY_EXCLUDED"
                        status = "EXPLICITLY_EXCLUDED"
                        if not siblings:
                            reason = "NO_P07_OPPORTUNITY_FIXTURE_FOR_SUBMISSION"
                        elif prop["kind"] not in NORMATIVE_PROPERTY_KINDS:
                            reason = "ADVISORY_PROPERTY_KIND_IS_NOT_A_CASE_ASSERTION"
                        else:
                            reason = (
                                "NO_P07_OPPORTUNITY_EXERCISES_THE_DECLARED_CONDITION"
                            )
            else:
                candidates = p07_cases_by_activity[rat["activity_id"]]
                source_submissions = {
                    match.group(1)
                    for ref in prop["source_refs"]
                    if (match := re.search(r"submissions/(submission_\d+)", ref["file"]))
                }
                tags = set(prop["benchmark_tags"])
                description = _normalized(prop["description"])
                selected: list[tuple[str, dict[str, Any]]] = []
                selector_kind = "NONE"
                selector_detail: dict[str, Any] = {
                    "activity_id": rat["activity_id"]
                }
                if source_submissions:
                    selected = [
                        pair for pair in candidates if pair[1]["submission_id"] in source_submissions
                    ]
                    selector_kind = "SOURCE_SUBMISSION_REFS"
                    selector_detail["submission_ids"] = sorted(source_submissions)
                elif "multi artefact" in description or "artefactos" in description:
                    selected = [
                        pair
                        for pair in candidates
                        if "CROSS_ARTIFACT"
                        in pair[1]["model_visible_definition"]["allowed_anchor_structures"]
                    ]
                    selector_kind = "CROSS_ARTIFACT_ANCHOR"
                elif (marker := _topical_marker(description)) is not None:
                    family, marker_tags = marker
                    selected = [
                        pair
                        for pair in candidates
                        if set(marker_tags) & set(pair[1]["fixture_tags"])
                    ]
                    selector_kind = "TOPICAL_MARKER"
                    selector_detail["marker_family"] = family
                    selector_detail["marker_tags"] = sorted(marker_tags)
                elif tags:
                    selected = [
                        pair
                        for pair in candidates
                        if tags & set(pair[1]["fixture_tags"])
                    ]
                    selector_kind = "SHARED_ORACLE_TAGS"
                    selector_detail["oracle_tags"] = sorted(tags)
                if selected:
                    cases = [case_id for case_id, _opportunity in selected]
                    fixture_id = selected[0][1]["opportunity_fixture_id"]
                    scope = "ACTIVITY_WIDE"
                    selector = {"kind": selector_kind, "detail": selector_detail}
                else:
                    scope = "EXPLICITLY_EXCLUDED"
                    status = "EXPLICITLY_EXCLUDED"
                    if selector_kind == "NONE":
                        # No submission ref, no topical marker and no oracle tag:
                        # the condition lives only in the assignment or rubric,
                        # which never enters the P07 model-visible input.
                        reason = "CONDITION_CONFINED_TO_SOURCE_OUTSIDE_P07_INPUT"
                    else:
                        reason = (
                            "NO_P07_OPPORTUNITY_EXERCISES_THE_DECLARED_CONDITION"
                        )
        elif stage == "PLANNER":
            number = _activity_number(rat["activity_id"])
            if submission_id:
                cases = [f"PP-A{number:02d}-S{_submission_number(submission_id):02d}-PLANNER-001"]
            else:
                cases = [f"PP-A{number:02d}-PLANNER-ACT"]
            fixture_id = f"planner:{property_id}"
            selector = {
                "kind": "STAGE_CASE_IDENTITY",
                "detail": {
                    "activity_id": rat["activity_id"],
                    "submission_id": submission_id,
                },
            }
        elif stage == "P09":
            target = p09_fixture_by_activity.get(rat["activity_id"])
            if target and submission_id in (None, target[2]):
                cases = [target[0]]
                fixture_id = target[1]
                scope = "ACTIVITY_WIDE" if submission_id is None else "SUBMISSION_WIDE"
                selector = {
                    "kind": "FROZEN_FIXTURE_SCOPE",
                    "detail": {
                        "activity_id": rat["activity_id"],
                        "submission_id": submission_id,
                    },
                }
            else:
                scope = "EXPLICITLY_EXCLUDED"
                status = "EXPLICITLY_EXCLUDED"
                reason = "NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_SCOPE"
        if status == "ALIGNED" and not cases:
            raise RuntimeError(f"aligned property has no case: {property_id}")
        if status == "ALIGNED" and selector["kind"] == "NONE":
            raise RuntimeError(
                f"aligned property has no representative selector: {property_id}"
            )
        rows.append(
            {
                "property_id": property_id,
                "stage": stage,
                "oracle_state": prop["oracle_state"],
                "binding_scope": scope,
                "primary_case_id": cases[0] if cases else None,
                "additional_case_ids": cases[1:],
                "fixture_id": fixture_id,
                "representative_selector": selector,
                "source_provenance": [
                    f"{rat['activity_path']}/{ref['file']}"
                    + (f"#{ref['section']}" if ref.get("section") else "")
                    for ref in prop["source_refs"]
                ],
                "alignment_status": status,
                "exclusion_reason": reason,
            }
        )
    return {
        "schema_version": "semantic-property-bindings/1.1.0",
        "benchmark_version": BENCHMARK_VERSION,
        "property_count": len(rows),
        "bindings": rows,
    }


def build_tag_registry(index: CorpusIndex) -> dict[str, Any]:
    activity_index = {
        rat["activity_id"]: list(rat["benchmark_tags"])
        for rat in index.ratifications
    }
    tags = sorted(
        {
            tag
            for rat in index.ratifications
            for tag in rat["benchmark_tags"]
        }
        | {
            "BENCHMARK_SCAFFOLD_NOT_P01_P02_P03_GOLDEN",
            "P06_UNCERTAIN",
            "P06_INSUFFICIENT",
            "P09_CANNOT_INFER",
            "P09_FIXED_APPROVED_INPUT",
            "P09_NO_PII_PROPAGATION",
        }
    )
    return {
        "schema_version": "semantic-tag-scope-registry/1.1.0",
        "benchmark_version": BENCHMARK_VERSION,
        "top_level_ratification_semantics": "ACTIVITY_COVERAGE_INDEX_ONLY",
        "allowed_scopes": ["ACTIVITY", "SUBMISSION", "PROPERTY", "FIXTURE", "CASE_DERIVED"],
        "tags": [
            {
                "tag": tag,
                "allowed_scopes": ["SUBMISSION", "PROPERTY", "FIXTURE", "CASE_DERIVED"],
            }
            for tag in tags
        ],
        "activity_coverage_index": activity_index,
    }


def main() -> None:
    index = CorpusIndex()
    properties = _all_properties(index)
    routes = build_routes(index, properties)
    opportunities = build_opportunities(index, properties)
    bindings = build_property_bindings(properties, routes, opportunities)
    p09 = build_p09_bindings(index)
    tags = build_tag_registry(index)
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    documents = {
        "p06_routes.json": routes,
        "p07_opportunities.json": opportunities,
        "property_bindings.json": bindings,
        "p09_locator_bindings.json": p09,
        "tag_scope_registry.json": tags,
    }
    for filename, document in documents.items():
        (FIXTURE_ROOT / filename).write_text(pretty_json(document), encoding="utf-8")
    print(
        json.dumps(
            {
                "routes": len(routes["routes"]),
                "opportunities": len(opportunities["opportunities"]),
                "properties": len(bindings["bindings"]),
                "p09_questions": sum(
                    len(fixture["questions"]) for fixture in p09["fixtures"]
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
