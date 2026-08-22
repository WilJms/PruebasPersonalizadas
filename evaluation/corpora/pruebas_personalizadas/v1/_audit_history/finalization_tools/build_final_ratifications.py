#!/usr/bin/env python3
"""Derive canonical final ratifications from the preserved Opus 5 review."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "_audit_history"
MAPPING = json.loads((AUDIT / "submission_id_mapping.json").read_text(encoding="utf-8"))
PLAN = json.loads((ROOT / "finalization_resolution_plan.json").read_text(encoding="utf-8"))
OPUS_MANIFEST = json.loads(
    (AUDIT / "opus5/root/opus5_ratification_manifest.json").read_text(encoding="utf-8")
)

CL05_ACTIVITIES = {1, 2, 3, 5, 6, 7, 9, 12}
LENGTH_ACTIVITIES = {5, 6, 7, 9, 10, 11, 12}
NOISY_OLD_SIX = {1, 2, 4, 5, 6, 7, 8, 9, 11, 12}
SILENT_INJECTION = {(4, 2), (5, 1), (7, 2), (10, 1), (11, 2)}
SELF_DECLARED = {(1, 4), (3, 4), (4, 3), (5, 4), (6, 4), (7, 2), (10, 6)}
MISSING_ARTIFACT = {(4, 4), (7, 2), (8, 4), (12, 4)}
CROSS_RECONCILIATION = {(4, 5), (8, 5), (12, 5)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boundary_hash(paths: list[Path], base: Path) -> str:
    rows = []
    for path in sorted(paths, key=lambda item: item.relative_to(base).as_posix()):
        relative = path.relative_to(base).as_posix()
        rows.append(f"{relative}\0{sha256(path)}\0{path.stat().st_size}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def activity_number(activity_path: str) -> int:
    return int(re.match(r"activity_(\d{2})_", activity_path).group(1))


def rewrite_submission_mentions(text: str, id_map: dict[int, int]) -> str:
    def singular(match: re.Match[str]) -> str:
        return f"{match.group(1)} {id_map[int(match.group(2))]:02d}"

    text = re.sub(r"\b(entrega) (0[1-6])\b", singular, text, flags=re.IGNORECASE)

    def plural(match: re.Match[str]) -> str:
        prefix, values = match.group(1), match.group(2)
        values = re.sub(
            r"\b0([1-6])\b",
            lambda token: f"{id_map[int(token.group(1))]:02d}",
            values,
        )
        return prefix + values

    text = re.sub(
        r"\b(entregas\s+)((?:0[1-6](?:\s*,\s*|\s+y\s+|\s+)?)+)",
        plural,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"submission_0([1-6])",
        lambda match: f"submission_{id_map[int(match.group(1))]:02d}",
        text,
    )
    return text


def description_tags(description: str) -> list[str]:
    upper = description.upper()
    tags = set()
    for tag in (
        "PLAN_FEASIBLE",
        "PLAN_INFEASIBLE",
        "P06_UNCERTAIN",
        "PREMISE_VISIBLE",
        "ANSWER_VISIBLE",
        "DETECTION_TASK",
        "ADJUDICATION_TASK",
        "LEAKAGE_ORACLE_SUSPECT",
    ):
        if tag in upper:
            tags.add(tag)
    if "ANCHOR" in upper or "VISIBLE" in upper:
        tags.add("VISIBLE_ANCHOR_RISK")
    if "OPORTUNIDADES" in upper and ("DUPLIC" in upper or "SOLAP" in upper):
        tags.add("NEAR_DUPLICATE_OPPORTUNITIES")
    return sorted(tags)


def property_id_for_new_submission(property_id: str, id_map: dict[int, int]) -> str:
    match = re.match(r"^(A\d+-S)(\d{2})(-.+)$", property_id)
    if not match:
        return property_id
    return f"{match.group(1)}{id_map[int(match.group(2))]:02d}{match.group(3)}"


def transform_property(
    prop: dict,
    id_map: dict[int, int],
    file_map: dict[str, str],
    activity_num: int,
) -> dict | None:
    obsolete_act06 = {
        "A06-ACT-P5",
        "A06-ACT-P09a",
        "A06-S01-P2",
        "A06-S03-P3",
    }
    if prop["property_id"] in obsolete_act06 or prop["oracle_state"] == "INVALID":
        return None

    original_id = prop["property_id"]
    result = copy.deepcopy(prop)
    result["property_id"] = property_id_for_new_submission(original_id, id_map)
    result["description"] = rewrite_submission_mentions(result["description"], id_map)
    result["description"] = result["description"].replace(
        "LAB-12H-4H-7F3A9C", "LAB-12H-4H-C28D51"
    )
    result["defensible_alternatives"] = [
        rewrite_submission_mentions(value, id_map)
        for value in result.get("defensible_alternatives", [])
    ]
    result["notes"] = ""
    for source_ref in result["source_refs"]:
        source_ref["file"] = file_map.get(source_ref["file"], source_ref["file"])

    if original_id == "A09-S01-P5":
        result["kind"] = "CONTEXTUAL_NOTE"
        result["oracle_state"] = "VALID"
        result["description"] = (
            "La submission se encuentra dentro de la guía orientativa de 1.000 a 1.600 "
            "palabras (1.403 palabras). Esta coincidencia de formato no constituye una "
            "propiedad semántica hard ni altera la valoración de evidencia y razonamiento."
        )
    if original_id == "A11-ACT-P6":
        result["kind"] = "CONTEXTUAL_NOTE"
        result["oracle_state"] = "NOT_APPLICABLE"
        result["confidence"] = "HIGH"
        result["description"] = (
            "LENGTH_COMPLIANCE es NOT_APPLICABLE como propiedad semántica hard: los rangos "
            "de postmortem y ADR son orientación de formato y la pauta valora evidencia, "
            "razonamiento y coherencia entre artefactos."
        )
        result["source_refs"] = [{"file": "01_assignment.docx", "section": "Extensión orientativa / no evaluable"}]

    result["benchmark_tags"] = description_tags(result["description"])
    return result


def new_property(
    property_id: str,
    stage: str,
    kind: str,
    state: str,
    confidence: str,
    description: str,
    refs: list[dict],
    alternatives: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    return {
        "property_id": property_id,
        "stage": stage,
        "kind": kind,
        "oracle_state": state,
        "confidence": confidence,
        "description": description,
        "source_refs": refs,
        "defensible_alternatives": alternatives or [],
        "notes": "",
        "benchmark_tags": sorted(set(tags or [])),
    }


def submission_tags(
    activity_num: int,
    old_id: int,
    artifacts: list[str],
    properties: list[dict],
    adversarial_characteristics: list[str],
) -> list[str]:
    tags = set()
    if len(artifacts) > 1:
        tags.add("MULTI_ARTIFACT")
    if (activity_num, old_id) in MISSING_ARTIFACT:
        tags.add("MISSING_ARTIFACT")
    if old_id == 3:
        tags.add("KEYWORDS_WITHOUT_RELATION")
    if old_id == 5 and (activity_num, old_id) not in CROSS_RECONCILIATION and activity_num != 7:
        tags.add("LATENT_CONTRADICTION")
        tags.add("DETECTION_TASK")
    if activity_num in NOISY_OLD_SIX and old_id == 6:
        tags.add("PROMPT_INJECTION_NOISY")
    if (activity_num, old_id) in SILENT_INJECTION:
        tags.add("PROMPT_INJECTION_SILENT")
    if (activity_num, old_id) in SELF_DECLARED:
        tags.add("SELF_DECLARED_GAP")
    if (activity_num, old_id) in CROSS_RECONCILIATION:
        tags.update(
            {
                "CROSS_ARTIFACT_RECONCILIATION",
                "EXPLICIT_CROSS_ARTIFACT_CONFLICT",
                "ADJUDICATION_TASK",
                "PREMISE_VISIBLE",
            }
        )
    if activity_num == 7 and old_id == 5:
        tags.update({"EXPLICIT_RECONCILIATION", "ADJUDICATION_TASK", "PREMISE_VISIBLE"})
    if activity_num == 9 and old_id == 6:
        tags.add("SILENT_CONCEPTUAL_GAP")
    if activity_num == 10 and old_id == 6:
        tags.update(
            {
                "DECLARED_CONCEPTUAL_OMISSION",
                "SELF_DECLARED_GAP",
                "ADJUDICATION_TASK",
            }
        )
    if activity_num in {8, 12} and old_id == 6:
        tags.add("SIMULATED_PII")
    adversarial_text = " ".join(adversarial_characteristics).lower()
    if any(word in adversarial_text for word in ("extern", "fabricad", "biograf", "autoridad")):
        tags.add("EXTERNAL_KNOWLEDGE_TRAP")
    if any(word in adversarial_text for word in ("identificador", "cadena", "hash", "token")):
        tags.add("TECHNICAL_STRING_NOT_INSTRUCTION")
    for prop in properties:
        tags.update(prop["benchmark_tags"])
    return sorted(tags)


def main() -> None:
    manifest_activity = {entry["activity_path"]: entry for entry in OPUS_MANIFEST["activities"]}
    mapping_activity = {entry["activity"]: entry for entry in MAPPING["activities"]}
    plan_by_activity: dict[str, list[dict]] = {}
    for item in PLAN["items"]:
        plan_by_activity.setdefault(item["activity"], []).append(item)

    for activity_path, map_entry in sorted(mapping_activity.items()):
        num = activity_number(activity_path)
        activity_dir = ROOT / activity_path
        opus_path = AUDIT / "opus5" / activity_path / "opus5_ratification.json"
        opus = json.loads(opus_path.read_text(encoding="utf-8"))
        metadata = manifest_activity[activity_path]

        old_to_new_id: dict[int, int] = {}
        file_map: dict[str, str] = {}
        artifact_map: dict[int, list[str]] = {}
        artifact_hashes: dict[int, dict[str, str]] = {}
        for submission_map in map_entry["submissions"]:
            old_id = int(submission_map["old_submission_id"].split("_")[-1])
            new_id = int(submission_map["new_submission_id"].split("_")[-1])
            old_to_new_id[old_id] = new_id
            artifact_map[old_id] = []
            artifact_hashes[old_id] = {}
            for artifact in submission_map["artifacts"]:
                old_relative = artifact["old_path"].split(f"{activity_path}/", 1)[1]
                new_relative = artifact["new_path"].split(f"{activity_path}/", 1)[1]
                file_map[old_relative] = new_relative
                artifact_map[old_id].append(new_relative)
                artifact_hashes[old_id][new_relative] = sha256(activity_dir / new_relative)

        activity_properties = []
        for prop in opus["activity_level_properties"]:
            transformed = transform_property(prop, old_to_new_id, file_map, num)
            if transformed:
                activity_properties.append(transformed)

        submissions = []
        by_old_submission = {
            int(re.search(r"submission_(\d{2})", submission["submission_id"]).group(1)): submission
            for submission in opus["submissions"]
        }
        for old_id, source_submission in sorted(by_old_submission.items()):
            new_id = old_to_new_id[old_id]
            properties = []
            for prop in source_submission["properties"]:
                transformed = transform_property(prop, old_to_new_id, file_map, num)
                if transformed:
                    properties.append(transformed)

            if num == 6 and old_id == 1:
                properties.append(
                    new_property(
                        "A06-S01-FINAL-P2",
                        "P06",
                        "REQUIRED",
                        "VALID",
                        "HIGH",
                        "SUFFICIENT en la dimensión de apoyo por banda: 15/20, 8/25 y 3/15 coincide con la tabla autorizada; 26/60 = 43,3% conserva un denominador identificable.",
                        [
                            {"file": artifact_map[old_id][0], "section": "Comparación con la alternativa A"},
                            {"file": "01_assignment.docx", "section": "Resultados"},
                        ],
                    )
                )
            if num == 6 and old_id == 3:
                properties.append(
                    new_property(
                        f"A06-S{new_id:02d}-FINAL-P3",
                        "P06",
                        "CONTEXTUAL_NOTE",
                        "VALID",
                        "HIGH",
                        "El desglose 15/20, 8/25 y 3/15 está transcrito correctamente. Esto no corrige los defectos deliberados restantes: usar 26 como porcentaje y llamar estratificada a una encuesta voluntaria siguen siendo insuficientes.",
                        [
                            {"file": artifact_map[old_id][0], "section": "Desglose usado"},
                            {"file": "01_assignment.docx", "section": "Resultados"},
                        ],
                    )
                )

            if (num, old_id) in CROSS_RECONCILIATION:
                properties.append(
                    new_property(
                        f"A{num:02d}-S{new_id:02d}-FINAL-XAR",
                        "P07",
                        "CONTEXTUAL_NOTE",
                        "VALID",
                        "HIGH",
                        "El segundo artefacto yuxtapone o señala explícitamente el conflicto. La operación evaluable es reconciliar o adjudicar con evidencia cruzada, no descubrir una contradicción latente.",
                        [{"file": path} for path in artifact_map[old_id]],
                        tags=[
                            "CROSS_ARTIFACT_RECONCILIATION",
                            "EXPLICIT_CROSS_ARTIFACT_CONFLICT",
                            "ADJUDICATION_TASK",
                            "PREMISE_VISIBLE",
                        ],
                    )
                )
            if num == 7 and old_id == 5:
                properties.append(
                    new_property(
                        f"A07-S{new_id:02d}-FINAL-RECON",
                        "P07",
                        "CONTEXTUAL_NOTE",
                        "VALID",
                        "HIGH",
                        "El informe anuncia que concluye lo contrario y el cuaderno registra que menor caída es el criterio correcto. Una pregunta válida exige reconciliar y aplicar el criterio, no atribuir detección de un hueco oculto.",
                        [{"file": path} for path in artifact_map[old_id]],
                        tags=["EXPLICIT_RECONCILIATION", "ADJUDICATION_TASK", "PREMISE_VISIBLE"],
                    )
                )
            if num == 9 and old_id == 6:
                properties.append(
                    new_property(
                        f"A09-S{new_id:02d}-FINAL-SILENT-GAP",
                        "P06",
                        "REQUIRED",
                        "VALID",
                        "HIGH",
                        "SILENT_CONCEPTUAL_GAP confirmado: la submission no confronta la capacidad construida con los 22 y 18 hogares del sector y no declara esa omisión.",
                        [
                            {"file": artifact_map[old_id][0]},
                            {"file": "01_assignment.docx", "section": "Fuente C"},
                        ],
                        tags=["SILENT_CONCEPTUAL_GAP", "DETECTION_TASK"],
                    )
                )
            if num == 10 and old_id == 6:
                properties.append(
                    new_property(
                        f"A10-S{new_id:02d}-FINAL-DECLARED-OMISSION",
                        "P07",
                        "CONTEXTUAL_NOTE",
                        "VALID",
                        "HIGH",
                        "La omisión de cálculos segmentados está declarada en ambos artefactos. La operación evaluable es juzgar si la justificación para omitirlos está sustentada, no detectar que faltan.",
                        [{"file": path} for path in artifact_map[old_id]],
                        tags=["DECLARED_CONCEPTUAL_OMISSION", "SELF_DECLARED_GAP", "ADJUDICATION_TASK"],
                    )
                )

            tags = submission_tags(
                num,
                old_id,
                artifact_map[old_id],
                properties,
                source_submission.get("adversarial_characteristics", []),
            )
            submissions.append(
                {
                    "submission_id": f"submission_{new_id:02d}",
                    "artifacts": artifact_map[old_id],
                    "source_snapshot_hashes": artifact_hashes[old_id],
                    "properties": properties,
                    "benchmark_tags": tags,
                }
            )

        submissions.sort(key=lambda entry: entry["submission_id"])

        if num == 6:
            corrected_refs = [
                {"file": "01_assignment.docx", "section": "Resultados"},
                {"file": artifact_map[1][0], "section": "Comparación con la alternativa A"},
                {"file": artifact_map[3][0], "section": "Desglose usado"},
            ]
            activity_properties.extend(
                [
                    new_property(
                        "A06-ACT-FINAL-P5",
                        "P06",
                        "REQUIRED",
                        "VALID",
                        "HIGH",
                        "La tabla autorizada y las dos submissions corregidas son consistentes en el apoyo por banda: 15, 8 y 3; el total es 26.",
                        corrected_refs,
                    ),
                    new_property(
                        "A06-ACT-FINAL-P09",
                        "P09",
                        "REQUIRED",
                        "VALID",
                        "HIGH",
                        "P09 puede construir observables, acceptance conditions y niveles sobre el apoyo por banda usando 15/20, 8/25 y 3/15, sin ampliar evidencia ni alterar las preguntas aprobadas.",
                        corrected_refs,
                    ),
                ]
            )

        if num in CL05_ACTIVITIES:
            activity_properties.append(
                new_property(
                    f"A{num:02d}-ACT-FINAL-LEAKAGE",
                    "P07",
                    "CONTEXTUAL_NOTE",
                    "ORACLE_SUSPECT",
                    "MEDIUM",
                    "La clasificación de answer leakage depende del observable y del wording concreto. En DETECTION_TASK, mostrar simultáneamente las dos afirmaciones contradictorias puede ser ANSWER_VISIBLE. En ADJUDICATION_TASK, ambas pueden ser PREMISE_VISIBLE si la pregunta exige decidir con evidencia. No existe una regla universal para todos los casos.",
                    [{"file": "02_rubric.docx", "section": "Condiciones u orientaciones de valoración"}],
                    alternatives=[
                        "DETECTION_TASK con una sola zona visible",
                        "ADJUDICATION_TASK con ambas premisas visibles y exigencia de evidencia",
                    ],
                    tags=[
                        "DETECTION_TASK",
                        "ADJUDICATION_TASK",
                        "ANSWER_VISIBLE",
                        "PREMISE_VISIBLE",
                        "LEAKAGE_ORACLE_SUSPECT",
                    ],
                )
            )

        if num in LENGTH_ACTIVITIES:
            activity_properties.append(
                new_property(
                    f"A{num:02d}-ACT-FINAL-LENGTH",
                    "P04",
                    "CONTEXTUAL_NOTE",
                    "NOT_APPLICABLE",
                    "HIGH",
                    "LENGTH_COMPLIANCE no es una propiedad semántica hard en esta actividad. El rango conservado es una guía de formato no evaluable por sí misma; se valoran evidencia y razonamiento.",
                    [{"file": "01_assignment.docx", "section": "Entregable o entregables"}],
                    tags=["LENGTH_ORIENTATIVE_NON_EVALUABLE"],
                )
            )

        if num == 3:
            activity_properties.append(
                new_property(
                    "A03-ACT-FINAL-DIFFICULTY",
                    "P04",
                    "CONTEXTUAL_NOTE",
                    "VALID",
                    "MEDIUM",
                    "Se preserva dificultad_declarada=simple para mantener la distribución original, con caveat upper_simple / borderline_intermediate por la restricción presupuestaria compuesta y el máximo derivable de 82 vasos.",
                    [{"file": "01_assignment.docx", "section": "Disciplina y dificultad"}],
                    tags=["DIFFICULTY_CAVEAT"],
                )
            )

        all_properties = activity_properties + [
            prop for submission in submissions for prop in submission["properties"]
        ]
        states = Counter(prop["oracle_state"] for prop in all_properties)
        caveats = [
            {"property_id": prop["property_id"], "summary": prop["description"]}
            for prop in all_properties
            if prop["oracle_state"] == "ORACLE_SUSPECT"
        ]
        if num == 3:
            caveats.append(
                {
                    "property_id": "ACTIVITY-DIFFICULTY-CAVEAT",
                    "summary": "upper_simple / borderline_intermediate; la clasificación declarada simple se preserva deliberadamente.",
                }
            )

        activity_tags = set()
        for submission in submissions:
            activity_tags.update(submission["benchmark_tags"])
        for prop in activity_properties:
            activity_tags.update(prop["benchmark_tags"])
        if num == 8:
            activity_tags.add("ADVERSARIAL_AUTHORIZED_SOURCE")
        if num == 3:
            activity_tags.add("DIFFICULTY_CAVEAT")

        resolved = []
        for item in plan_by_activity.get(activity_path, []):
            resolved.append(
                {
                    "revision_id": item["revision_id"],
                    "resolution_state": item["planned_resolution_state"],
                    "summary": item["intended_action"],
                }
            )

        submission_paths = [activity_dir / path for submission in submissions for path in submission["artifacts"]]
        output = {
            "schema_version": "corpus-final-ratification/1.0.0",
            "ratification_type": "INDEPENDENT_MODEL_RATIFICATION_DERIVED_FROM_OPUS5",
            "source_reviewer_model": "OPUS_5",
            "curation_role": "CORPUS_FINALIZATION",
            "activity_id": opus["activity_id"],
            "activity_path": activity_path,
            "discipline": metadata["disciplina"],
            "difficulty_declared": metadata["dificultad_declarada"],
            "difficulty_caveat": (
                "upper_simple / borderline_intermediate" if num == 3 else None
            ),
            "ratification_status": "RATIFIED_WITH_CAVEATS" if caveats else "RATIFIED",
            "confidence": opus["confidence"],
            "source_snapshot_hashes": {
                "assignment_sha256": sha256(activity_dir / "01_assignment.docx"),
                "rubric_sha256": sha256(activity_dir / "02_rubric.docx"),
                "submissions_boundary_sha256": boundary_hash(submission_paths, activity_dir),
            },
            "submissions": submissions,
            "activity_level_properties": activity_properties,
            "known_caveats": caveats,
            "resolved_findings": resolved,
            "benchmark_tags": sorted(activity_tags),
            "property_counts": {
                "total": len(all_properties),
                "VALID": states["VALID"],
                "ORACLE_SUSPECT": states["ORACLE_SUSPECT"],
                "NOT_APPLICABLE": states["NOT_APPLICABLE"],
            },
        }
        (activity_dir / "final_ratification.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
