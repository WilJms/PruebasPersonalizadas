# Manifest final del corpus - Pruebas Personalizadas

Corpus cerrado de 12 actividades para evaluar la generación de preguntas personalizadas a partir de `assignment + rubric + submission + evidence` autorizada. Esta versión es post-auditoría, autoconsistente y preparada para congelamiento. La autoridad de cada clase de archivo está definida en `CORPUS_AUTHORITY.md`.

## Estado final

- 12 actividades; ninguna en `NEEDS_REVISION` ni `REJECTED`.
- 395 propiedades canónicas: 361 `VALID`, 26 `ORACLE_SUSPECT` y 8 `NOT_APPLICABLE`; cero `INVALID`.
- Un solo caso confirmado de `SILENT_CONCEPTUAL_GAP`: actividad 09.
- Cuatro fixtures aprobados stage-local para P09: actividades 03, 04, 09 y 12.
- Contexto `CLOSED`; sin Internet, modelos externos, datos reales de estudiantes ni qualification.
- Estado de seguridad: `SYNTHETIC_ONLY_NO_STUDENT_DATA`.

## Entradas y autoridad

Entradas model-facing:

- `activity_*/01_assignment.docx`;
- `activity_*/02_rubric.docx`;
- `activity_*/submissions/submission_NN*`.

Autoridad benchmark-only:

- `activity_*/final_ratification.json`;
- `corpus_final_manifest.json`;
- `benchmark_fixtures/p09/*.json`.

Todo `_audit_history/**` es histórico, no canónico y `NON_MODEL_INPUT`.

## Naming y permutación

Todos los filenames de submissions son neutrales. Los grupos de un solo artefacto usan `submission_NN.ext`; los grupos multi-artefacto usan `submission_NN_artifact_MM.ext`. Ningún filename codifica calidad, suficiencia, contradicción o contenido adversarial.

Cada actividad recibió una permutación determinista diferente, derivada únicamente del ID de actividad y de la constante `corpus-final-v1`. El grupo que ocupaba la posición repetida en la versión pre-final quedó distribuido uniformemente: dos casos en cada índice final del 01 al 06. El mapa inverso existe exclusivamente en `_audit_history/submission_id_mapping.json`.

## Correcciones de source data

- Actividad 06: la tabla autorizada permanece en 15/8/3 para apoyo a bicicleteros por banda. Las dos submissions accidentales se corrigieron de forma coherente a esos valores; el total 26 y los defectos deliberados restantes se preservaron.
- Actividad 08: la IP privada fue sustituida por `192.0.2.44`, de TEST-NET-1. La otra IP sigue en TEST-NET-2 y la descripción de documentación ahora es coherente.
- Se diversificó la cadena técnica simulada de la actividad 01 que compartía prefijo con un hash de otra actividad. No se modificó ningún SHA físico.
- Se diversificó una identidad simulada entre actividades 08 y 12; se mantuvieron dominio `.invalid`, teléfono ficticio e ID clínico sintético.

## Política de extensión

En las actividades 05, 06, 07, 09, 10, 11 y 12 los rangos de palabras se conservaron únicamente como **extensión orientativa / no evaluable**. La consigna declara que la extensión es guía de formato y que el trabajo se evalúa por evidencia y razonamiento. `LENGTH_COMPLIANCE` es `NOT_APPLICABLE` como propiedad semántica hard.

La submission de actividad 09 con 1.403 palabras se encuentra dentro de la guía de 1.000-1.600; esa coincidencia no altera su valoración semántica.

## Reclasificaciones post-auditoría

- Actividad 10, `submission_04`: `DECLARED_CONCEPTUAL_OMISSION` y `SELF_DECLARED_GAP`. La omisión segmentada se declara en ambos artefactos; se evalúa la justificación, no el descubrimiento de una ausencia silenciosa.
- Actividad 07, `submission_06`: `EXPLICIT_RECONCILIATION`. El informe anuncia la contradicción y el cuaderno registra el criterio correcto.
- Actividad 04, `submission_06`; actividad 08, `submission_01`; actividad 12, `submission_04`: `CROSS_ARTIFACT_RECONCILIATION` y `EXPLICIT_CROSS_ARTIFACT_CONFLICT`, no detección latente.
- `SELF_DECLARED_GAP` también se registra en las submissions neutrales correspondientes de las actividades 01, 03, 04, 05, 06 y 07. En estos casos una pregunta mide aplicar, completar o comprobar la omisión, no necesariamente descubrirla.

## Answer leakage

El oracle distingue el observable:

- `DETECTION_TASK`: mostrar simultáneamente las dos afirmaciones contradictorias puede volver la respuesta `ANSWER_VISIBLE`;
- `ADJUDICATION_TASK`: ambas afirmaciones pueden ser `PREMISE_VISIBLE` cuando la pregunta exige reconciliar y decidir con evidencia.

El resultado depende del wording concreto. Los casos ambiguos permanecen `LEAKAGE_ORACLE_SUSPECT`; no existe una regla universal de mostrar siempre o nunca ambas premisas.

## Dificultad y diversidad

Se preserva la distribución declarada: 3 simples, 5 intermedias y 4 difíciles. La actividad 03 conserva `dificultad_declarada = simple` con `difficulty_caveat = upper_simple / borderline_intermediate`.

La diversidad incluye rúbricas cualitativas, pauta numérica, checklist, dimensiones ponderadas, pautas informales, código ejecutable, múltiples artefactos, artefactos ausentes declarados, prompt injection ruidosa y silenciosa, fuente autorizada con contenido hostil, PII simulada, traps de conocimiento externo, planes factibles e infactibles y casos de `P06_UNCERTAIN`.

Tags reutilizables canónicos incluyen:

`PROMPT_INJECTION_NOISY`, `PROMPT_INJECTION_SILENT`, `ADVERSARIAL_AUTHORIZED_SOURCE`, `SIMULATED_PII`, `TECHNICAL_STRING_NOT_INSTRUCTION`, `EXTERNAL_KNOWLEDGE_TRAP`, `MULTI_ARTIFACT`, `MISSING_ARTIFACT`, `CROSS_ARTIFACT_RECONCILIATION`, `SELF_DECLARED_GAP`, `SILENT_CONCEPTUAL_GAP`, `DECLARED_CONCEPTUAL_OMISSION`, `LATENT_CONTRADICTION`, `EXPLICIT_RECONCILIATION`, `KEYWORDS_WITHOUT_RELATION`, `PLAN_FEASIBLE`, `PLAN_INFEASIBLE`, `P06_UNCERTAIN`, `VISIBLE_ANCHOR_RISK` y `NEAR_DUPLICATE_OPPORTUNITIES`.

## Fixtures P09

`benchmark_fixtures/p09/` contiene cuatro Assessments aprobados y fijos como input de P09:

| Actividad | Cobertura principal |
|---|---|
| 03 | cadena cuantitativa, alternativas y límite presupuestario |
| 04 | adjudicación multi-artefacto de mutación, duplicados y orden |
| 09 | alternativas interpretativas y `cannot_infer` sobre series agregadas |
| 12 | privacidad, PII simulada no propagable, evidencia mínima y `cannot_infer` |

Cada fixture usa aproximadamente tres preguntas, conserva `visible_anchor_refs ⊆ support_refs` y no contiene una `EvaluationGuide` golden. Son `FIXED_INPUT_FOR_P09`, no `QUESTION_GOLDEN_FOR_P07`.

## Propiedades de oracle incorporadas

La autoridad final conserva las propiedades faltantes identificadas y verificadas contra las fuentes: exclusión asimétrica de A2; esquina azul; alternativa de 75 vasos y máximo 82; defecto invisible en output y `KeyError`; alcance provisional; cifra inventada 40/60; temperatura inicial 75 y líneas temporales no simultáneas; distractor `s_18`; renta objetivo inexistente de 26; crítica a “casi el doble”; dato irrelevante de color favorito; reconciliación de 24 horas; desplazamiento de columnas; comparación de cinco alternativas y rutas cross-artifact.

## Límites de uso

- P04 admite múltiples blueprints defendibles y no predice exact-N.
- P06 puede producir menos de N oportunidades; el planner es la única autoridad sobre factibilidad global.
- P07 mantiene `visible_anchor ⊆ support_evidence` y no exige conocimiento externo.
- P09 opera solo sobre preguntas aprobadas, no las cambia y no ensancha evidencia.
- `ORACLE_SUSPECT` no es hard truth.
- Ejemplos históricos de preguntas no son goldens.
- Filenames e índices nunca deben usarse como señal semántica.
