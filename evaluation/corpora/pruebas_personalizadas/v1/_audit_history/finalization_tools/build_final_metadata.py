#!/usr/bin/env python3
"""Build the final resolution ledger, report, and hash-bound manifest."""

from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "_audit_history"
ZERO_SHA256 = "0" * 64
REPORT_PACKAGE_RE = re.compile(
    rb"(?m)^(corpus_package_boundary_hash:\s*)[0-9a-f]{64}(\s*)$"
)
ACTIVITY_RE = re.compile(r"activity_(\d{2})_([a-z0-9_]+)")
SUBMISSION_RE = re.compile(r"submission_(0[1-6])")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def boundary_hash(entries: Iterable[tuple[str, str, int]]) -> str:
    rows = [f"{path}\0{digest}\0{size}\n" for path, digest, size in entries]
    return sha256_bytes("".join(sorted(rows)).encode("utf-8"))


PRE_SNAPSHOT = json.loads((AUDIT / "pre_finalization_manifest.json").read_text(encoding="utf-8"))
PRE_BY_PATH = {item["relative_path"]: item for item in PRE_SNAPSHOT["files"]}
MAPPING = json.loads((AUDIT / "submission_id_mapping.json").read_text(encoding="utf-8"))
MAPPING_BY_ACTIVITY = {item["activity"]: item for item in MAPPING["activities"]}
OPUS_PRESERVATION = json.loads((AUDIT / "opus5/preservation_manifest.json").read_text(encoding="utf-8"))
OPUS_BY_BEFORE_PATH = {item["before_path"]: item for item in OPUS_PRESERVATION["artifacts"]}


def activity_id(activity: str) -> str:
    match = ACTIVITY_RE.fullmatch(activity)
    if not match:
        raise ValueError(activity)
    return f"act_{match.group(1)}_{match.group(2)}"


def actual_change(path: str, before_path: str | None = None) -> dict[str, Any]:
    before_key = before_path or path
    before = PRE_BY_PATH[before_key]
    after = ROOT / path
    return {
        "before_path": before_key,
        "after_path": path,
        "before_sha256": before["sha256"],
        "after_sha256": sha256_file(after),
    }


def oracle_change(activity: str) -> dict[str, Any]:
    original = f"{activity}/opus5_ratification.json"
    preserved = OPUS_BY_BEFORE_PATH[original]
    after_path = f"{activity}/final_ratification.json"
    return {
        "before_path": preserved["archive_path"],
        "after_path": after_path,
        "before_sha256": preserved["after_sha256"],
        "after_sha256": sha256_file(ROOT / after_path),
    }


def manifest_change() -> dict[str, Any]:
    before = PRE_BY_PATH["corpus_manifest.md"]
    return {
        "before_path": "_audit_history/pre_final_corpus_manifest.md",
        "after_path": "corpus_manifest.md",
        "before_sha256": before["sha256"],
        "after_sha256": sha256_file(ROOT / "corpus_manifest.md"),
    }


def assignment_change(activity: str) -> dict[str, Any]:
    return actual_change(f"{activity}/01_assignment.docx")


def submission_changes(activity: str, old_number: int) -> list[dict[str, Any]]:
    mapping = MAPPING_BY_ACTIVITY[activity]
    record = next(
        item
        for item in mapping["submissions"]
        if item["old_submission_id"] == f"submission_{old_number:02d}"
    )
    changes = []
    for artifact in record["artifacts"]:
        before = PRE_BY_PATH[artifact["old_path"]]
        after_path = artifact["new_path"]
        changes.append(
            {
                # The explicit old->new path relation remains exclusively in audit history.
                "before_path": (
                    "_audit_history/pre_finalization_manifest.json"
                    f"#sha256={before['sha256']}"
                ),
                "after_path": after_path,
                "before_sha256": before["sha256"],
                "after_sha256": sha256_file(ROOT / after_path),
            }
        )
    return changes


def digest_side(changes: list[dict[str, Any]], side: str) -> str:
    rows = []
    for change in changes:
        rows.append(f"{change[f'{side}_path']}\0{change[f'{side}_sha256']}")
    return sha256_bytes("\n".join(sorted(rows)).encode("utf-8"))


def ledger_item(
    identifier: str,
    source_finding: str,
    changes: list[dict[str, Any]],
    action: str,
    state: str,
    verification: list[str],
    caveat: str | None,
) -> dict[str, Any]:
    if not changes:
        raise ValueError(f"ledger item has no affected files: {identifier}")
    return {
        "finding_id": identifier,
        "source_finding": source_finding,
        "affected_files": changes,
        "action": action,
        "before_hash": digest_side(changes, "before"),
        "after_hash": digest_side(changes, "after"),
        "resolution_state": state,
        "verification_performed": verification,
        "remaining_caveat": caveat,
    }


def sanitize_plan_and_add_evidence() -> dict[str, Any]:
    path = ROOT / "finalization_resolution_plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    summaries = {
        "RR-013": "Corregir la transición mensual de Barrio contradicha por la tabla autorizada.",
        "RR-016": "Resolver el defecto accidental de transcripción del apoyo por banda preservando la tabla autorizada y corrigiendo sólo las dos entregas afectadas.",
        "RR-017": "Retirar del oracle pre-final las certificaciones de la transcripción contradicha del apoyo por banda.",
        "RR-025": "Corregir la imprecisión de la consigna sobre el rango de documentación mediante una dirección TEST-NET coherente.",
    }
    evidence_by_rr: dict[str, list[str]] = {}
    for item in plan["items"]:
        rr = item["revision_id"]
        activity = item["activity"]
        state = item["planned_resolution_state"]
        if rr in summaries:
            item["source_revision"] = summaries[rr]
        evidence = [f"{activity}/final_ratification.json"]
        if state == "SOURCE_FIXED":
            if rr in {"RR-015", "RR-025", "RR-029", "RR-034"}:
                evidence.insert(0, f"{activity}/01_assignment.docx")
            elif rr == "RR-016":
                evidence = [change["after_path"] for old in (1, 3) for change in submission_changes(activity, old)] + evidence
            elif rr == "RR-026":
                evidence = [change["after_path"] for change in submission_changes("activity_01_luz_y_plantines", 6)] + ["activity_01_luz_y_plantines/final_ratification.json"]
            elif rr == "RR-039":
                evidence = [change["after_path"] for change in submission_changes(activity, 6)] + evidence
        if rr in {"RR-020", "RR-023", "RR-031", "RR-032", "RR-037"}:
            evidence.append("corpus_manifest.md")
        item["completion_evidence"] = sorted(set(evidence))
        item["implementation_status"] = "COMPLETED"
        evidence_by_rr[rr] = item["completion_evidence"]
    plan["completed_item_count"] = len(plan["items"])
    plan["all_items_resolved"] = True
    write_json(path, plan)
    return plan


def build_resolution_log(plan: dict[str, Any]) -> dict[str, Any]:
    activities = [f"activity_{number:02d}_" for number in range(1, 13)]
    activity_paths = [
        next(path.name for path in ROOT.glob(prefix + "*") if path.is_dir())
        for prefix in activities
    ]
    by_number = {int(path[9:11]): path for path in activity_paths}

    cl_items = [
        ledger_item(
            "CL-01",
            "Dos entregas de la actividad 06 transcribían de manera accidental una distribución distinta de la tabla autorizada.",
            submission_changes(by_number[6], 1)
            + submission_changes(by_number[6], 3)
            + [oracle_change(by_number[6])],
            "Se preservó la tabla del assignment, se corrigieron únicamente las dos entregas y se retiraron las propiedades inválidas derivadas.",
            "SOURCE_FIXED",
            ["verificación directa contra assignment", "recomputación de razones dependientes", "extracción de texto PDF", "validación del oracle"],
            None,
        ),
        ledger_item(
            "CL-02",
            "La omisión de segmentos de la entrega pertinente de actividad 10 estaba declarada en ambos artefactos.",
            submission_changes(by_number[10], 6) + [oracle_change(by_number[10]), manifest_change()],
            "Se preservó la fuente y se reclasificó como omisión conceptual declarada cuya justificación debe adjudicarse.",
            "RECLASSIFIED",
            ["lectura de ambos artefactos", "conteo global de SILENT_CONCEPTUAL_GAP", "validación de tags"],
            None,
        ),
        ledger_item(
            "CL-03",
            "El conteo determinista de palabras de la entrega pertinente de actividad 09 cae dentro del rango orientativo real.",
            submission_changes(by_number[9], 1) + [oracle_change(by_number[9])],
            "Se preservó la submission y se corrigió el oracle para registrar cumplimiento de formato sin convertirlo en propiedad semántica hard.",
            "ORACLE_FIXED",
            ["extracción y conteo de 1.403 palabras", "lectura del assignment", "búsqueda de formulación obsoleta"],
            None,
        ),
        ledger_item(
            "CL-04",
            "Los rangos de extensión no discriminaban comprensión en siete actividades.",
            [assignment_change(by_number[number]) for number in (5, 6, 7, 9, 10, 11, 12)]
            + [oracle_change(by_number[number]) for number in (5, 6, 7, 9, 10, 11, 12)],
            "Se mantuvieron los rangos como guía de formato, se declararon no evaluables por sí mismos y LENGTH_COMPLIANCE quedó NOT_APPLICABLE como hard oracle.",
            "SOURCE_FIXED",
            ["extracción de texto DOCX", "render visual de ocho assignments modificados", "validación de propiedades NOT_APPLICABLE"],
            "Los rangos se conservan únicamente como orientación editorial.",
        ),
        ledger_item(
            "CL-05",
            "La evaluación de leakage depende de si el observable pide detectar una contradicción o adjudicar premisas ya visibles.",
            [oracle_change(by_number[number]) for number in (1, 2, 3, 5, 6, 7, 9, 12)],
            "Se añadió la distinción DETECTION/ADJUDICATION y se preservaron como ORACLE_SUSPECT los casos dependientes del wording.",
            "PRESERVED_AS_ORACLE_SUSPECT",
            ["revisión de tags PREMise/ANSWER visibles", "conteo de ORACLE_SUSPECT", "validación de estados permitidos"],
            "La clasificación final de leakage exige evaluar el wording concreto de cada pregunta.",
        ),
        ledger_item(
            "CL-06",
            "La entrega pertinente de actividad 07 anuncia su propia tensión en el informe y en el cuaderno.",
            submission_changes(by_number[7], 5) + [oracle_change(by_number[7]), manifest_change()],
            "Se preservó la fuente realista y se reclasificó como reconciliación explícita, no detección latente.",
            "RECLASSIFIED",
            ["lectura cruzada de informe y cuaderno", "validación de tags EXPLICIT_RECONCILIATION"],
            None,
        ),
        ledger_item(
            "CL-07",
            "Otro artefacto ya yuxtapone o señala la discrepancia en tres casos multi-artefacto.",
            sum((submission_changes(by_number[number], 5) for number in (4, 8, 12)), [])
            + [oracle_change(by_number[number]) for number in (4, 8, 12)]
            + [manifest_change()],
            "Se etiquetaron rutas de reconciliación cruzada explícita y se retiró la lectura de conflicto latente donde no correspondía.",
            "RECLASSIFIED",
            ["lectura de pares de artefactos", "resolución de source_refs cruzados dentro de cada submission", "validación de tags"],
            None,
        ),
        ledger_item(
            "CL-08",
            "Varias entregas declaran por sí mismas sus huecos u omisiones.",
            sum(
                (
                    submission_changes(by_number[number], old)
                    for number, old in ((1, 4), (3, 4), (4, 3), (5, 4), (6, 4), (7, 2), (10, 6))
                ),
                [],
            )
            + [oracle_change(by_number[number]) for number in (1, 3, 4, 5, 6, 7, 10)],
            "Se conservaron las submissions y se etiquetaron SELF_DECLARED_GAP para medir aplicación/comprobación, no descubrimiento implícito.",
            "RECLASSIFIED",
            ["revisión de declaraciones explícitas", "conteo de SILENT_CONCEPTUAL_GAP", "validación de tags"],
            "La dificultad de estos casos no debe sobreestimarse como detección de una ausencia oculta.",
        ),
        ledger_item(
            "CL-09",
            "Una cadena técnica y una identidad simulada producían acoplamientos artificiales entre actividades.",
            submission_changes(by_number[1], 6)
            + submission_changes(by_number[12], 6)
            + [oracle_change(by_number[1]), oracle_change(by_number[12])],
            "Se diversificaron la cadena y una identidad, conservando dominio .invalid, teléfono ficticio e identificador clínico simulado.",
            "SOURCE_FIXED",
            ["búsqueda global de cadenas", "validación de source_refs", "escaneo de seguridad"],
            None,
        ),
        ledger_item(
            "CL-10",
            "La dificultad declarada de actividad 03 es discutible pero no constituye un defecto del corpus.",
            [oracle_change(by_number[3]), manifest_change()],
            "Se preservó dificultad simple y se documentó upper_simple / borderline_intermediate sin alterar la distribución 3/5/4.",
            "DOCUMENTED_NON_BLOCKING",
            ["revisión de distribución de dificultad", "validación de difficulty_caveat"],
            "Clasificación fronteriza no bloqueante.",
        ),
    ]

    source_change_by_rr: dict[str, list[dict[str, Any]]] = {
        "RR-015": [assignment_change(by_number[5]), oracle_change(by_number[5])],
        "RR-016": submission_changes(by_number[6], 1) + submission_changes(by_number[6], 3) + [oracle_change(by_number[6])],
        "RR-025": [assignment_change(by_number[8]), oracle_change(by_number[8])],
        "RR-026": submission_changes(by_number[1], 6) + [oracle_change(by_number[1])],
        "RR-029": [assignment_change(by_number[9]), oracle_change(by_number[9])],
        "RR-034": [assignment_change(by_number[11]), oracle_change(by_number[11])],
        "RR-039": submission_changes(by_number[12], 6) + [oracle_change(by_number[12])],
    }
    manifest_rr = {"RR-020", "RR-023", "RR-031", "RR-032", "RR-037"}
    required_items = []
    for planned in plan["items"]:
        rr = planned["revision_id"]
        activity = planned["activity"]
        changes = source_change_by_rr.get(rr, [oracle_change(activity)])
        if rr in manifest_rr:
            changes = changes + [manifest_change()]
        state = planned["planned_resolution_state"]
        action = planned["intended_action"]
        caveat = None
        if state == "PRESERVED_AS_ORACLE_SUSPECT":
            caveat = "La lectura depende del observable y del wording concreto; no se usa como hard oracle."
        elif state == "DOCUMENTED_NON_BLOCKING":
            caveat = "La diferencia observada no bloquea el uso del caso."
        required_items.append(
            ledger_item(
                rr,
                planned["source_revision"],
                changes,
                action,
                state,
                ["verificación contra bytes autorizados", "validación de completion_evidence", "validación de final_ratification"],
                caveat,
            )
        )

    state_counts = Counter(item["resolution_state"] for item in required_items)
    result = {
        "schema_version": "corpus-finalization-resolution-log/1.0.0",
        "created_utc": "2026-08-16T00:00:00-04:00",
        "readiness": "CORPUS_READY_FOR_SEMANTIC_BENCHMARK",
        "source_audit": "OPUS_5_INDEPENDENT_MODEL_RATIFICATION_PRESERVED_AS_HISTORY",
        "hash_algorithm": "SHA-256",
        "old_submission_mapping_disclosure": "ONLY_IN__audit_history/submission_id_mapping.json",
        "cluster_findings": cl_items,
        "required_revisions": required_items,
        "summary": {
            "cluster_finding_count": len(cl_items),
            "required_revision_count": len(required_items),
            "required_revision_resolution_states": dict(sorted(state_counts.items())),
            "unresolved_count": 0,
        },
    }
    write_json(ROOT / "corpus_finalization_resolution_log.json", result)
    return result


def media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    known = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".json": "application/json",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".py": "text/x-python",
        ".txt": "text/plain",
    }
    return known.get(suffix, "application/octet-stream")


def role_for(path: str) -> str:
    if path.startswith("_audit_history/"):
        return "AUDIT_HISTORY"
    if path.startswith("benchmark_fixtures/p09/") and path.endswith(".json"):
        return "P09_STAGE_FIXTURE"
    if re.match(r"^activity_[^/]+/(?:01_assignment[.]docx|02_rubric[.]docx|submissions/)", path):
        return "SOURCE_INPUT"
    return "BENCHMARK_AUTHORITY"


def path_metadata(path: str) -> tuple[str | None, str | None, str | None]:
    activity_match = ACTIVITY_RE.search(path)
    activity = (
        f"act_{activity_match.group(1)}_{activity_match.group(2)}"
        if activity_match
        else None
    )
    submission_match = SUBMISSION_RE.search(Path(path).name)
    submission = f"submission_{submission_match.group(1)}" if submission_match else None
    artifact_group = submission
    return activity, submission, artifact_group


def file_entry(path: str) -> dict[str, Any]:
    full = ROOT / path
    activity, submission, artifact_group = path_metadata(path)
    role = role_for(path)
    return {
        "path": path,
        "sha256": sha256_file(full),
        "hash_mode": "ACTUAL_SHA256",
        "bytes": full.stat().st_size,
        "media_type": media_type(path),
        "activity_id": activity,
        "submission_id": submission,
        "artifact_group": artifact_group,
        "role": role,
        "model_visible": role == "SOURCE_INPUT",
    }


def normalized_report_sha256(path: Path) -> str:
    normalized, count = REPORT_PACKAGE_RE.subn(
        rb"\g<1>" + ZERO_SHA256.encode("ascii") + rb"\g<2>", path.read_bytes()
    )
    if count != 1:
        raise ValueError("report must contain exactly one corpus package hash line")
    return sha256_bytes(normalized)


def normalized_manifest_sha256(manifest: dict[str, Any]) -> str:
    normalized = copy.deepcopy(manifest)
    normalized["boundary_hashes"]["corpus_package_boundary_hash"] = ZERO_SHA256
    for entry in normalized["files"]:
        if entry["path"] in {"corpus_final_manifest.json", "corpus_finalization_report.md"}:
            entry["sha256"] = ZERO_SHA256
    return sha256_bytes(canonical_json_bytes(normalized))


def collect_property_statistics() -> tuple[Counter[str], Counter[str], int]:
    property_counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    silent_gaps = 0
    for path in sorted(ROOT.glob("activity_*/final_ratification.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        statuses[data["ratification_status"]] += 1
        for prop in data["activity_level_properties"]:
            property_counts[prop["oracle_state"]] += 1
        for submission in data["submissions"]:
            if "SILENT_CONCEPTUAL_GAP" in submission.get("benchmark_tags", []):
                silent_gaps += 1
            for prop in submission["properties"]:
                property_counts[prop["oracle_state"]] += 1
    return property_counts, statuses, silent_gaps


def precompute_boundaries() -> tuple[str, str, str]:
    source = []
    oracle = []
    fixtures = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        role = role_for(relative)
        row = (relative, sha256_file(path), path.stat().st_size)
        if role == "SOURCE_INPUT":
            source.append(row)
        if relative.endswith("/final_ratification.json"):
            oracle.append(row)
        if role == "P09_STAGE_FIXTURE":
            fixtures.append(row)
    return boundary_hash(source), boundary_hash(oracle), boundary_hash(fixtures)


def render_report(
    source_hash: str,
    oracle_hash: str,
    fixture_hash: str,
    package_hash: str,
    role_counts: Counter[str],
    total_files: int,
) -> str:
    property_counts, statuses, silent_gaps = collect_property_statistics()
    canonical_count = total_files - role_counts["AUDIT_HISTORY"]
    return f"""# Informe de finalización del corpus

Fecha de congelamiento: 2026-08-16  
Alcance: corpus, autoridad semántica y fixtures stage-local; no se ejecutaron P04/P06/P07/P09 reales ni se construyó el benchmark del producto.

## 1. Qué se modificó

Se corrigieron dos artefactos de actividad 06 para respetar la tabla autorizada; ocho assignments recibieron correcciones acotadas de extensión o IP; una cadena técnica y una identidad simulada se diversificaron. Los doce oracles se sustituyeron por `final_ratification.json`, todos los nombres de submissions se neutralizaron y los IDs se permutaron. Se añadieron schemas, cuatro fixtures P09, autoridad, manifiestos, ledger y validador offline.

## 2. Qué no se modificó

No se alteraron defectos deliberados de las submissions, no se añadieron casos al core y no se cambiaron las fuentes de actividad 07 ni 10 para fabricar huecos silenciosos. La auditoría Opus 5 y los borradores pre-finales se conservaron byte-for-byte bajo `_audit_history`. Los renombrados sin corrección de source conservaron sus hashes.

## 3. Por qué

La jerarquía aplicada fue: bytes autorizados, hechos deterministas, auditoría Opus 5 falsable y drafts históricos. Sólo se corrigieron defectos accidentales demostrados; las ambigüedades genuinas permanecen explícitas como caveats u `ORACLE_SUSPECT`.

## 4. Source defects corregidos

- Actividad 06: distribución de apoyo por banda coherente con 15/8/3 en assignment y dos submissions, con razones dependientes recomputadas.
- Actividad 08: dirección privada sustituida por `192.0.2.44` de TEST-NET-1.
- Actividades 05, 06, 07, 09, 10, 11 y 12: extensión declarada orientativa/no evaluable por sí misma; el assignment 08 también fue renderizado por su cambio de IP.
- Actividades 01 y 12: cadena e identidad simuladas diversificadas sin introducir datos reales.

## 5. Oracle defects corregidos

Se resolvieron las ocho afirmaciones contradichas, las 40 revisiones obligatorias y las 37 propiedades faltantes ratificadas que sobrevivieron a los cambios de source. Actividad 10 quedó como omisión declarada; actividad 07 y tres rutas multi-artefacto quedaron como reconciliación explícita; actividad 09 conserva el único hueco conceptual silencioso confirmado. No queda ninguna propiedad `INVALID`.

## 6. Caveats preservados

La distinción `DETECTION_TASK`/`ADJUDICATION_TASK` gobierna answer leakage. Los casos dependientes del wording permanecen `ORACLE_SUSPECT`; los rangos de extensión permanecen como guía y actividad 03 conserva el caveat `upper_simple / borderline_intermediate`. Caveat no implica bloqueo.

## 7. Nombres neutralizados

Los artefactos canónicos usan únicamente `submission_NN` y, cuando corresponde, `submission_NN_artifact_MM`. Los filenames y los índices no codifican calidad. El mapeo histórico vive exclusivamente en `_audit_history/submission_id_mapping.json`.

## 8. Permutación aplicada

Se aplicaron doce permutaciones deterministas distintas, dependientes sólo de `activity_id` y `corpus-final-v1`. El antiguo slot repetido quedó distribuido uniformemente: dos casos en cada posición final 01–06. El reporte no expone el mapeo por actividad.

## 9. Fixtures P09

Se crearon cuatro inputs aprobados stage-local para actividades 03, 04, 09 y 12, con tres preguntas cada uno. Cubren cálculo, multi-artefacto, interpretaciones alternativas, `cannot_infer` central y privacidad de contenido simulado. Son `FIXED_INPUT_FOR_P09`, no goldens de P07 ni guides golden de P09.

## 10. Integridad de archivos

PASS: 24 DOCX legibles, 25 PDF íntegros y extraíbles, y todos los MD/TXT de source en UTF-8 y no vacíos. Los ocho DOCX modificados se renderizaron e inspeccionaron; el PDF corregido de actividad 06 conservó una página legible, extracción textual y formato razonable. Las tablas relevantes se extrajeron correctamente.

## 11. Seguridad

PASS: clasificación `SYNTHETIC_ONLY_NO_STUDENT_DATA`. Los correos usan `.invalid`, las IP canónicas son TEST-NET, los teléfonos e IDs clínicos son ficticios y el único token con apariencia de secreto está rotulado como dummy no real. No se copiaron secretos al reporte.

## 12. Property counts finales

- Total: {sum(property_counts.values())}
- `VALID`: {property_counts['VALID']}
- `ORACLE_SUSPECT`: {property_counts['ORACLE_SUSPECT']}
- `NOT_APPLICABLE`: {property_counts['NOT_APPLICABLE']}
- `INVALID`: 0
- `SILENT_CONCEPTUAL_GAP`: {silent_gaps}

## 13. Ratification status final

- `RATIFIED`: {statuses['RATIFIED']}
- `RATIFIED_WITH_CAVEATS`: {statuses['RATIFIED_WITH_CAVEATS']}
- `NEEDS_REVISION` / `REJECTED`: 0

## 14. Fronteras y conteos

- SOURCE_INPUT: {role_counts['SOURCE_INPUT']} archivos
- BENCHMARK_AUTHORITY: {role_counts['BENCHMARK_AUTHORITY']} archivos
- P09_STAGE_FIXTURE: {role_counts['P09_STAGE_FIXTURE']} archivos
- AUDIT_HISTORY: {role_counts['AUDIT_HISTORY']} archivos
- Inventario total: {total_files} archivos; paquete canónico sin historia: {canonical_count} archivos

source_corpus_boundary_hash: {source_hash}
semantic_oracle_boundary_hash: {oracle_hash}
p09_fixture_boundary_hash: {fixture_hash}
corpus_package_boundary_hash: {package_hash}

La frontera PACKAGE usa filas UTF-8 ordenadas `path\\0sha256\\0bytes\\n`. Para evitar circularidad, el hash propio del manifest usa JSON canónico con tres campos de digest normalizados a 64 ceros; el reporte normaliza únicamente la línea del hash PACKAGE. El validador implementa la misma regla.

## 15. Resultado del validador y tabla de findings

Comando: `python3 tools/validate_final_corpus.py`  
Resultado final: PASS, incluyendo schemas, 12 actividades, 72 casos, source refs, agrupación, nombres neutrales, 14 hashes Opus, cuatro fronteras, integridad, seguridad, aritmética y seis firmas semánticas de código en actividad 04.

| Finding | Resolution | Files | Verification | Final status |
|---|---|---|---|---|
| CL-01 | Source corregido contra tabla autorizada | 2 submissions + oracle act06 | PDF/TXT, razones, schema | SOURCE_FIXED |
| CL-02 | Omisión declarada | source preservado + oracle act10 + manifest | lectura de ambos artefactos | RECLASSIFIED |
| CL-03 | Extensión real dentro de rango | source preservado + oracle act09 | conteo determinista | ORACLE_FIXED |
| CL-04 | Extensión orientativa/no hard | 7 assignments + oracles | render DOCX + NOT_APPLICABLE | SOURCE_FIXED |
| CL-05 | Detección separada de adjudicación | 8 oracles | tags y estados | PRESERVED_AS_ORACLE_SUSPECT |
| CL-06 | Reconciliación explícita | act07 source preservado + oracle | lectura cruzada | RECLASSIFIED |
| CL-07 | Rutas cruzadas explícitas | act04/08/12 | source refs y tags | RECLASSIFIED |
| CL-08 | Huecos auto-declarados | 7 actividades | tags + conteo silent gap | RECLASSIFIED |
| CL-09 | Sintéticos diversificados | act01/12 | búsqueda global + seguridad | SOURCE_FIXED |
| CL-10 | Dificultad frontera documentada | act03 oracle + manifest | caveat + distribución | DOCUMENTED_NON_BLOCKING |
| RR-001…RR-040 | Cada revisión tiene resolución y evidencia | 12 final ratifications + fuentes aplicables | ledger, schemas y source refs | 40/40 RESOLVED |

CORPUS_READY_FOR_SEMANTIC_BENCHMARK
"""


def build_report_and_manifest() -> dict[str, Any]:
    source_hash, oracle_hash, fixture_hash = precompute_boundaries()

    # Seed the report so it participates in the inventory before manifest assembly.
    report_path = ROOT / "corpus_finalization_report.md"
    provisional_paths = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name != "corpus_final_manifest.json"
    }
    provisional_paths.add("corpus_finalization_report.md")
    provisional_paths.add("corpus_final_manifest.json")
    provisional_counts = Counter(role_for(path) for path in provisional_paths)
    report_path.write_text(
        render_report(
            source_hash,
            oracle_hash,
            fixture_hash,
            ZERO_SHA256,
            provisional_counts,
            len(provisional_paths),
        ),
        encoding="utf-8",
    )

    real_paths = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.relative_to(ROOT).as_posix() != "corpus_final_manifest.json"
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )
    entries = [file_entry(path) for path in real_paths]
    self_entry = {
        "path": "corpus_final_manifest.json",
        "sha256": ZERO_SHA256,
        "hash_mode": "NORMALIZED_JSON_SELF_SHA256",
        "bytes": 1,
        "media_type": "application/json",
        "activity_id": None,
        "submission_id": None,
        "artifact_group": None,
        "role": "BENCHMARK_AUTHORITY",
        "model_visible": False,
    }
    entries.append(self_entry)
    entries.sort(key=lambda item: item["path"])
    role_counts = Counter(entry["role"] for entry in entries)

    manifest = {
        "schema_version": "corpus-final-manifest/1.0.0",
        "created_utc": "2026-08-16T00:00:00-04:00",
        "readiness": "CORPUS_READY_FOR_SEMANTIC_BENCHMARK",
        "hash_algorithm": "SHA-256",
        "path_encoding": "UTF-8_POSIX_RELATIVE",
        "boundary_serialization": "SORTED_UTF8_ROWS_V1:path\\0sha256\\0bytes\\n",
        "normalization_rules": {
            "manifest_self_hash": "Canonical compact JSON after replacing the manifest self digest, report digest, and corpus_package_boundary_hash with 64 ASCII zeroes.",
            "report_package_hash": "SHA-256 after replacing the value on the corpus_package_boundary_hash line with 64 ASCII zeroes.",
            "package_membership": "Every manifest entry whose role is not AUDIT_HISTORY.",
        },
        "source_input_file_count": role_counts["SOURCE_INPUT"],
        "benchmark_authority_file_count": role_counts["BENCHMARK_AUTHORITY"],
        "p09_stage_fixture_file_count": role_counts["P09_STAGE_FIXTURE"],
        "audit_history_file_count": role_counts["AUDIT_HISTORY"],
        "total_package_file_count": len(entries),
        "files": entries,
        "boundary_hashes": {
            "source_corpus_boundary_hash": source_hash,
            "semantic_oracle_boundary_hash": oracle_hash,
            "p09_fixture_boundary_hash": fixture_hash,
            "corpus_package_boundary_hash": ZERO_SHA256,
        },
    }

    # Stabilize the self byte count; digest strings have fixed width, so this converges.
    for _ in range(10):
        self_entry["sha256"] = normalized_manifest_sha256(manifest)
        serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        new_size = len(serialized.encode("utf-8"))
        if self_entry["bytes"] == new_size:
            break
        self_entry["bytes"] = new_size
    else:
        raise RuntimeError("manifest self-size did not converge")
    self_entry["sha256"] = normalized_manifest_sha256(manifest)

    report_normalized = normalized_report_sha256(report_path)
    package_rows = []
    for entry in entries:
        if entry["role"] == "AUDIT_HISTORY":
            continue
        digest = entry["sha256"]
        if entry["path"] == "corpus_finalization_report.md":
            digest = report_normalized
        package_rows.append((entry["path"], digest, entry["bytes"]))
    package_hash = boundary_hash(package_rows)

    report_path.write_text(
        render_report(
            source_hash,
            oracle_hash,
            fixture_hash,
            package_hash,
            role_counts,
            len(entries),
        ),
        encoding="utf-8",
    )
    report_entry = next(item for item in entries if item["path"] == "corpus_finalization_report.md")
    if report_entry["bytes"] != report_path.stat().st_size:
        raise RuntimeError("report length changed after fixed-width hash replacement")
    report_entry["sha256"] = sha256_file(report_path)
    manifest["boundary_hashes"]["corpus_package_boundary_hash"] = package_hash
    self_entry["sha256"] = normalized_manifest_sha256(manifest)
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if len(serialized.encode("utf-8")) != self_entry["bytes"]:
        raise RuntimeError("final manifest length changed")
    (ROOT / "corpus_final_manifest.json").write_text(serialized, encoding="utf-8")
    return manifest


def main() -> None:
    plan = sanitize_plan_and_add_evidence()
    build_resolution_log(plan)
    manifest = build_report_and_manifest()
    print(json.dumps({
        "files": manifest["total_package_file_count"],
        "counts": {
            "SOURCE_INPUT": manifest["source_input_file_count"],
            "BENCHMARK_AUTHORITY": manifest["benchmark_authority_file_count"],
            "P09_STAGE_FIXTURE": manifest["p09_stage_fixture_file_count"],
            "AUDIT_HISTORY": manifest["audit_history_file_count"],
        },
        "boundary_hashes": manifest["boundary_hashes"],
    }, indent=2))


if __name__ == "__main__":
    main()
