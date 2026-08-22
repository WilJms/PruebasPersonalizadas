# Benchmark semántico canónico

> **Superseded (Phase 9B.4).** Este documento describe
> `semantic-benchmark/1.1.0`, que se conserva como evidencia histórica con su
> boundary `sha256:426dda4d…` intacto. Tras la auditoría de validez de Phase
> 9B.3, su porción P06 quedó marcada
> `P06_NOT_VALID_FOR_CONTINUED_MODEL_SELECTION` y el instrumento vigente es
> `semantic-benchmark/1.2.0` — ver [SEMANTIC_BENCHMARK_V1_2.md](SEMANTIC_BENCHMARK_V1_2.md).
> El defecto **no** se conocía antes de ejecutar v1.1; se detectó después. Nada
> de lo que sigue se reescribe retroactivamente.

## Estado y autoridad

Phase 8.1 corrige exclusivamente el instrumento de evaluación. El corpus, el
runtime, los prompts, el routing, los DTO/materializers productivos, el planner,
la base de datos, OpenAPI y el frontend no cambian.

- corpus: `pruebas-personalizadas-corpus/1.0.0`;
- corpus package boundary:
  `21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1`;
- benchmark canónico: `semantic-benchmark/1.1.0`;
- benchmark boundary: `sha256:426dda4d560a8d7d53639dfbaa0773c28565450f06e8ff62d51a8cd1bd6f62ff`;
- clasificación: `SYNTHETIC_ONLY_NO_STUDENT_DATA`;
- qualification real: `NOT_YET_RUN`;
- candidate matrix: `UNSET`;
- autorización: `NONE`;
- provider calls: `0`.

`semantic-benchmark/1.0.0` y `reports/semantic_benchmark/v1/` se preservan como
historia con los estados `SUPERSEDED_PRE_QUALIFICATION` y
`NOT_VALID_FOR_PHASE9_MODEL_SELECTION`. El corpus v1 no era inválido: el
problema estaba en la alineación fixture/property/tag del instrumento v1.0.0.
Nunca se ejecutó ese instrumento contra un provider real.

## Corpus inmutable y superficies

La snapshot conserva 218 archivos y 8.384.772 bytes: 12 actividades, 72
submissions, 395 properties, cuatro fixtures P09 y doce preguntas. El validador
exige tanto `CORPUS_READY_FOR_SEMANTIC_BENCHMARK` como el package hash exacto.
Phase 8.1 no modifica un byte bajo
`evaluation/corpora/pruebas_personalizadas/v1/`.

El manifest mantiene tres superficies:

1. `SOURCE_INPUT/model_visible=true`: assignment, rubric y artifacts neutrales.
2. `BENCHMARK_AUTHORITY` y `P09_STAGE_FIXTURE`: ratifications, properties y
   fixtures aprobados; son autoridad del evaluador, no input libre del modelo.
3. `AUDIT_HISTORY`: historia legible pero inalcanzable desde model input y
   adjudicación post-fix.

`ModelVisibleProjection` falla con `BENCHMARK_ORACLE_LEAKAGE_BLOCKED` ante
ratifications, audit history u old labels. Para P09 sólo proyecta `questions` y
mantiene `p09_properties` en una referencia oracle disjunta.

## Causa raíz v1.0.0

La auditoría reproducible en
`reports/semantic_benchmark/v1_1/benchmark_alignment_audit.json` confirmó los
siete defectos:

- tags agregados de actividad se propagaban a cases no relacionados; 32 cases
  tenían simultáneamente `PLAN_FEASIBLE` y `PLAN_INFEASIBLE`;
- P07 usaba una oportunidad genérica por submission, basada en primeros units;
- P06 consumía el scaffold P04 genérico en lugar de una ruta stage-local;
- P04 proyectaba sólo tres EvidenceUnits iniciales de cada fuente;
- P09 resolvía principalmente por filename y admitía fallback al primer unit;
- una property activity-level podía caer sobre la primera submission libre;
- varias observations de una misma property podían inflar el denominador.

La corrección elimina esa implementación canónica: v1.1 consume manifests
explícitos, bindings y locators exactos. Los dos últimos defectos quedan
cerrados por construcciones verificables, no por afirmación: cada binding
declara el `representative_selector` que eligió sus cases y el reporte lo
vuelve a derivar, y el denominador de qualification es la property, con cases y
runs como observations.  Los reports v1 permanecen sin reinterpretar ni borrar.

## Fixtures alineados

| Stage | Casos | Autoridad v1.1 | Llamadas k=1 |
|---|---:|---|---:|
| P04 | 12 | proyección exhaustiva `BlueprintBuildRequest` | 12 |
| P06 | 127 | `p06_routes.json`, una ruta source-grounded por case | 127 |
| PLANNER | 21 | fixture categórico determinista | 0 |
| P07 | 108 | `p07_opportunities.json`, una oportunidad explícita por case | 108 |
| P09 | 4 | cuatro Assessment fixtures, doce preguntas exactas | 4 |
| Total | 272 |  | 251 |

### P04

El builder lee exclusivamente `01_assignment.docx` y `02_rubric.docx` con el
parser real. Proyecta 682/682 units de assignment y 470/470 units de rubric,
conservando orden, EvidenceUnit ID y provenance. No recibe ni lee ratification,
compiled properties, audit history u Opus; `oracle_reads=0`. Sigue marcado
`BENCHMARK_SCAFFOLD_NOT_P01_P02_P03_GOLDEN`: es un input exhaustivo compatible
con el contrato, no un golden P01/P02/P03 ni un expected output P04.

Los campos que el contrato exige y la fuente no declara se mantienen neutros.
`verification_fit` no admite un valor nulo, así que la proyección usa `MEDIUM`
—el punto medio de la escala— de forma uniforme en los 470 criterios: no afirma
la verificabilidad máxima de un texto que el docente nunca calificó, no
introduce señal diferencial entre bloques y conserva la misma semántica de
cobertura que cualquier valor distinto de `NOT_VERIFIABLE`. `certainty` se
queda en `EXPLICIT` porque cada requirement sí es la proyección literal de un
unit explícito. Nombres como `Bloque de rúbrica fuente N` son andamiaje
declarado, sin jerarquía pedagógica inventada.

### P06

Las 127 rutas declaran construct, operación, focus, observable, requisito de
evidencia, formatos y provenance exacta. El request se construye desde una ruta
source-grounded y una sola submission, sin depender del P04 benchmark scaffold.
`oracle_binding_metadata` queda fuera de `model_visible_definition`; los enums
`SUFFICIENT`, `PARTIAL`, `INSUFFICIENT`, `UNCERTAIN`, IDs de property y estados
esperados no entran en model input.

### P07

Las 108 oportunidades cubren 63 submissions con al menos una oportunidad:
promedio 1,71 y máximo 4 por submission. Cada fixture fija operación, focus,
observable, política y `support_evidence_ids` exactos. Los IDs resuelven contra
la submission concreta con hash normalizado y locator; no existe `units[0]`,
primer artefacto ni fallback. Oportunidades independientes de una misma
submission producen distintos case IDs, requests e input hashes. Treinta y
nueve reglas P07 con refs sólo de assignment/rubric no crean una oportunidad
artificial: 29 reglas normativas ejercitables se observan sobre oportunidades
exactas de su submission con scope `SUBMISSION_WIDE`, y 10 quedan excluidas.
En total se excluyen 15 properties P07 para las que no existe una oportunidad
stage-local no circular defendible.

### P09

P09 permanece en cuatro calls, una por Assessment aprobado. Un manifest
separado resuelve las 12 preguntas por archivo + locator hasta EvidenceUnits
exactos y congela EvidenceUnit ID, normalized hash y locator real. Resultado:
12/12 support refs y visible refs resueltos, `unresolved=0`, `ambiguous=0`,
`fallback=0` y `visible_anchor ⊆ support`. Assignment/rubric son sólo lineage;
no amplían `SelectedQuestion.evidence_ids`. Cada case acepta únicamente
properties P09 de su actividad con scope activity-level o de la submission del
fixture.

## Property bindings y adjudicación

`property_bindings.json` cubre las 395 properties y distingue
`CASE_SPECIFIC`, `SUBMISSION_WIDE`, `ACTIVITY_WIDE`, `FIXTURE_WIDE` y
`EXPLICITLY_EXCLUDED`.

| Estado de alineación | Cantidad |
|---|---:|
| `ALIGNED` | 356 |
| `EXPLICITLY_EXCLUDED` | 31 |
| `NOT_APPLICABLE` | 8 |
| `ASSIGNED_ARBITRARILY` | 0 |

Cada binding declara además un `representative_selector`: la regla explícita
que eligió sus cases. `assigned_arbitrarily_count` no es una constante: el
reporte vuelve a derivar el conjunto de cases desde ese selector y cuenta las
filas que no se reproducen. Un binding apuntado a un case simplemente
disponible —el defecto histórico de v1.0.0— aparece como violación.

| `representative_selector` | Filas |
|---|---:|
| `OWN_FIXTURE` | 235 |
| `STAGE_ACTIVITY_FIXTURE` | 45 |
| `SUBMISSION_EXHAUSTIVE` | 28 |
| `STAGE_CASE_IDENTITY` | 21 |
| `TOPICAL_MARKER` | 10 |
| `FROZEN_FIXTURE_SCOPE` | 8 |
| `SOURCE_SUBMISSION_REFS` | 4 |
| `CROSS_ARTIFACT_ANCHOR` | 2 |
| `SHARED_ORACLE_TAGS` | 2 |
| `ACTIVITY_STAGE_EXHAUSTIVE` | 1 |

Las 31 exclusiones declaran un hecho estructural, nunca comodidad:

| Razón | Filas |
|---|---:|
| `NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_SCOPE` | 14 |
| `NO_P07_OPPORTUNITY_FIXTURE_FOR_SUBMISSION` | 9 |
| `NO_P07_OPPORTUNITY_EXERCISES_THE_DECLARED_CONDITION` | 4 |
| `P04_INPUT_EXCLUDES_SUBMISSIONS_BY_STAGE_CONTRACT` | 2 |
| `CONDITION_CONFINED_TO_SOURCE_OUTSIDE_P07_INPUT` | 2 |

Las 14 P09 pertenecen a actividades sin Assessment aprobado congelado; las dos
P04 son properties submission-level cuyo stage input no lleva submissions; las
dos `CONDITION_CONFINED_TO_SOURCE_OUTSIDE_P07_INPUT` describen condiciones que
sólo viven en consigna o rúbrica, fuera del input model-visible de P07; y las
cuatro restantes tienen fixtures hermanos pero ninguno ejercita el antecedente
declarado. Cada fila conserva source provenance y razón. Los ocho N/A siguen
trazables y separados de una exclusión instrumental.

Una regla normativa (`PROHIBITED` o `REQUIRED`) sí se liga a un fixture hermano
cuando ese fixture ejercita realmente la condición: `A10-S04-P4` prohíbe nombrar
las tasas por segmento cuando el observable es la evaluación de la omisión, y
`PP-A10-S04-P07-O01` es exactamente esa oportunidad. Un `CONTEXTUAL_NOTE`
submission-level no se convierte en aserción de case.

Los evaluator modes no cambian: 29 `DETERMINISTIC`, 8 `RULE_BASED` y 358
`EXTERNAL_ADJUDICATION_REQUIRED`. Esa carga externa es deuda explícita de
preparación Phase 9, no scoring simulado.

La métrica final usa `PROPERTY_CANDIDATE_REASONING`, no case ni repetición. La
cadena es
`case/property/run observation -> property/run outcome -> property/config
outcome`. Tres cases por tres runs producen nueve observaciones, tres outcomes
property/run y un único denominador de property. `REQUIRED` exige todas las
observaciones aplicables; en `PROHIBITED` cualquier violación aplicable falla;
`DEFENSIBLE_ALTERNATIVE` no se vuelve hard failure y `CONTEXTUAL_NOTE` no es un
gate automático. Technical/pending, N/A y oracle-suspect quedan fuera del hard
semantic denominator.

## Scope y provenance de tags

Cada tag de case registra `tag`, `scope`, `source` y `property_ids`. Los scopes
permitidos son `SUBMISSION`, `PROPERTY`, `FIXTURE` y `CASE_DERIVED`; `ACTIVITY`
sólo existe como `ACTIVITY_COVERAGE_INDEX` y nunca como assertion de case.
`MULTI_ARTIFACT` se deriva del request concreto. Planner lleva exactamente uno
de sus dos outcomes.

| Tag auditado | Cases v1.0.0 | Cases v1.1.0 |
|---|---:|---:|
| `PLAN_FEASIBLE` | 32 | 2 |
| `PLAN_INFEASIBLE` | 151 | 19 |
| `SIMULATED_PII` | 28 | 4 |
| `SILENT_CONCEPTUAL_GAP` | 14 | 1 |
| `PROMPT_INJECTION_SILENT` | 74 | 12 |
| `ADVERSARIAL_AUTHORIZED_SOURCE` | 14 | 1 |
| `LEAKAGE_ORACLE_SUSPECT` | 119 | 8 |

## Rare coverage y singleton policy

Los conteos salen de tags case-scoped con provenance. `rare_property_count`
cuenta properties explícitamente bound observadas por esos cases; no multiplica
una property por sus observaciones.

| Familia | Properties | Cases | SMOKE | CORE | HELD_OUT | Política |
|---|---:|---:|---:|---:|---:|---|
| silent conceptual gap | 1 | 1 | 0 | 0 | 1 | singleton confirmatorio |
| P06 uncertain | 6 | 5 | 1 | 2 | 2 | qualification + held-out |
| simulated PII | 8 | 4 | 1 | 0 | 3 | safety antes y después del lock |
| silent prompt injection | 19 | 12 | 0 | 7 | 5 | safety multi-instance |
| authorized-source adversarial | 3 | 1 | 0 | 1 | 0 | singleton safety en qualification |
| multi-artifact | 141 | 115 | 3 | 51 | 61 | estructural multi-instance |
| answer leakage | 21 | 8 | 1 | 3 | 4 | safety multi-instance |
| planner infeasibility | 19 | 19 | 1 | 11 | 7 | estructural multi-instance |
| P09 cannot-infer | 4 | 2 | 0 | 1 | 1 | semántica multi-instance |

No se afirma cobertura held-out independiente para una familia singleton. El
payload adversarial autorizado se ubica en CORE para poder eliminar un
candidato peligroso; el único silent conceptual gap se reserva como fenómeno
confirmatorio.

## Splits congelados después de Phase 8.1

| Split | P04 | P06 | PLANNER | P07 | P09 | Total |
|---|---:|---:|---:|---:|---:|---:|
| SMOKE | 1 | 2 | 2 | 6 | 1 | 12 |
| CORE | 6 | 64 | 12 | 55 | 2 | 139 |
| HELD_OUT_CONFIRMATION | 5 | 61 | 7 | 47 | 1 | 121 |

Fuera de la excepción P09 auditada, held-out reserva actividades
03/07/09/10/12 y es disjunto de qualification. SMOKE contiene los cinco stages,
insufficiency, conocimiento externo, prompt injection, leakage, multi-artifact
y safety. PII aparece antes del held-out y en confirmación; P06 uncertainty
aparece en los tres splits.

Desde este cierre, `HELD_OUT_CONFIRMATION` sólo puede confirmar o rechazar. No
puede cambiar prompt, reasoning, routing, candidate list ni thresholds.

## Call budget y candidate matrix

| k | P04 | P06 | P07 | P09 | Total | Planner |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12 | 127 | 108 | 4 | 251 | 0 |
| 3 | 36 | 381 | 324 | 12 | 753 | 0 |

Con k=1, la distribución es SMOKE 10, CORE 127 y HELD_OUT 114 llamadas; con
k=3 es 30/381/342. Son proyecciones de conteo, no autorización ni estimación
USD. Modelo, snapshot, reasoning, token/cost caps, promotion order y thresholds
siguen `UNSET`; pricing debe consultarse sólo en una fase Phase 9 explícita.

## Boundary, reports y gate

El boundary v1.1 liga corpus, schemas, case matrix, splits, P04 completo, rutas
P06, oportunidades P07, property bindings, tag registry/provenance, rare rules,
resolver P09, aggregation policy, código del benchmark y fronteras productivas
actuales. El generador de definitions es offline y sus JSON versionados son la
autoridad consumida durante qualification.

`make semantic-benchmark-dry-run` elimina ambas API keys, fuerza mock/P10 false
y escribe `reports/semantic_benchmark/v1_1/`. El gate ejecuta 17 checks reales:
corpus, P04 completeness/isolation, P06 alignment/isolation, P07
alignment/support, P09 scope/locators, tag/rare validity, bindings/denominator,
splits, anti-leakage, candidate matrix y call graph provider. Todos pasan
17/17; parser y planner también se reproducen. No se puntúa output mock:
provider calls 0, real transport false, billable authorizations 0 y mock
semantic scoring false.

## Stop de Phase 9

Este estado sólo habilita una futura preparación/freeze de qualification. No
selecciona modelos, no consulta pricing, no fija thresholds, no ejecuta SMOKE,
CORE ni held-out y no autoriza presupuesto. Antes de Phase 9 todavía deben
definirse mecanismo/capacidad de adjudicación externa para 358 properties,
candidate matrix, snapshots disponibles, reasoning, k, thresholds, promotion
criteria, call/cost caps y autorización hash-bound exactamente acotada.
