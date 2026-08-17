# Informe de finalización del corpus

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

- Total: 395
- `VALID`: 361
- `ORACLE_SUSPECT`: 26
- `NOT_APPLICABLE`: 8
- `INVALID`: 0
- `SILENT_CONCEPTUAL_GAP`: 1

## 13. Ratification status final

- `RATIFIED`: 1
- `RATIFIED_WITH_CAVEATS`: 11
- `NEEDS_REVISION` / `REJECTED`: 0

## 14. Fronteras y conteos

- SOURCE_INPUT: 134 archivos
- BENCHMARK_AUTHORITY: 23 archivos
- P09_STAGE_FIXTURE: 4 archivos
- AUDIT_HISTORY: 57 archivos
- Inventario total: 218 archivos; paquete canónico sin historia: 161 archivos

source_corpus_boundary_hash: 46281a3dd96a900ae5a3aa3cde864e1b3aa44d640701d8ce8371d602926ababc
semantic_oracle_boundary_hash: d7f665567404fff4e4caead14a5a50748123e1c64cef57a0d4177ccced58fea2
p09_fixture_boundary_hash: ef3c97944b4dc84861d3380c3cbafc296c6ab26c5358abdb50a922245da18bb8
corpus_package_boundary_hash: 21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1

La frontera PACKAGE usa filas UTF-8 ordenadas `path\0sha256\0bytes\n`. Para evitar circularidad, el hash propio del manifest usa JSON canónico con tres campos de digest normalizados a 64 ceros; el reporte normaliza únicamente la línea del hash PACKAGE. El validador implementa la misma regla.

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
