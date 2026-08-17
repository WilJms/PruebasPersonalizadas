# Benchmark semántico canónico

## Estado y autoridad

Phase 8 integra un corpus sintético congelado y construye un instrumento
offline para la futura qualification de Phase 9. No cambia el pipeline del
producto, sus prompts, routing, reasoning, contratos públicos ni validadores.

- corpus: `pruebas-personalizadas-corpus/1.0.0`;
- benchmark: `semantic-benchmark/1.0.0`;
- corpus package boundary:
  `21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1`;
- benchmark boundary:
  `sha256:9dc8df63b01f1e29a65a7540ceff1359ed037fa240e7c1c1f0e8b485edb35771`;
- clasificación: `SYNTHETIC_ONLY_NO_STUDENT_DATA`;
- ratificación: `INDEPENDENT_MODEL_RATIFICATION_DERIVED_FROM_OPUS5`;
- qualification real: `NOT_YET_RUN`;
- candidate matrix: `UNSET`;
- autorización billable: `NONE`.

No se describe el corpus como “human-ratified”: no hubo esa ratificación. El
old harness y todos sus resultados conservan
`HISTORICAL_NON_CANONICAL_EVIDENCE`; siguen legibles, pero no son selector,
oracle, baseline ni fallback del benchmark nuevo.

## Snapshot y superficies

La snapshot se conserva byte a byte en
`evaluation/corpora/pruebas_personalizadas/v1/`: 218 archivos, 8.384.772 bytes,
12 actividades, 72 submissions neutrales, 395 propiedades, cuatro fixtures
P09 y doce preguntas P09. El validador original se ejecuta tanto sobre la
fuente resuelta como sobre la copia y exige
`CORPUS_READY_FOR_SEMANTIC_BENCHMARK` y el package hash exacto.
La regla rooted de `.gitattributes` desactiva normalización de texto y el lint
de trailing whitespace sólo para esta snapshot, de modo que Git preserve sus
bytes congelados sin ocultar los diffs de texto.

El manifest separa tres superficies:

1. `SOURCE_INPUT` + `model_visible=true`: assignment, rubric y artifacts
   neutrales de submission. Son los únicos archivos completos proyectables.
2. `BENCHMARK_AUTHORITY` y `P09_STAGE_FIXTURE`: ratifications, manifest y
   definiciones de properties. Los lee el evaluador, nunca el modelo.
3. `AUDIT_HISTORY`: `_audit_history/**`, mappings, drafts y material Opus
   previo. Nunca es model input ni oracle post-fix.

`CorpusPackage -> ModelVisibleProjection` falla cerrado con
`BENCHMARK_ORACLE_LEAKAGE_BLOCKED` si una referencia no es `SOURCE_INPUT` o no
declara `model_visible=true`. Para P09 existe una única proyección tipada
adicional: extrae `questions` de uno de los cuatro fixtures congelados y deja
`p09_properties` fuera. Las referencias `#questions` y `#p09_properties` son
distintas y todo case exige conjuntos `model_visible_refs`/`oracle_refs`
disjuntos.

## Stages y fixtures

Los stages semánticos activos son P04, P06, P07 y P09. PLANNER es un componente
determinista. P05/P08 son históricos; P10 sigue disabled. P01/P02/P03 no se
convierten en qualification stages porque el corpus no contiene properties
ratificadas para ellos.

| Stage | Casos | Fixture stage-local | Naturaleza |
|---|---:|---|---|
| P04 | 12 | `BlueprintBuildRequest` + draft mínimo compilado | `BENCHMARK_SCAFFOLD_NOT_P01_P02_P03_GOLDEN` |
| P06 | 69 | blueprint controlado + `EvidenceBundle` del parser real | input P06, no P04 golden |
| PLANNER | 21 | `EvidenceMapPatch` categórico + blueprint + policy | input controlado, no P06 golden |
| P07 | 72 | `QuestionBuildRequest` + oportunidad/support reales | input P07, no expected output |
| P09 | 4 | fixture congelado proyectado a `GuideBuildRequest` aprobado | input P09, no P07 golden |
| Total | 178 |  |  |

P06 no inventa casos sin propiedad: tres submissions con properties de
actividad ocupan casos que de otro modo no tendrían property P06, y tres
submissions sin property P06 ratificada quedan catalogadas por sus otros
stages. P07 cubre las 72 submissions mediante properties submission-locales o
de actividad. Los 21 casos planner corresponden a las 21 properties
deterministas, incluida la factibilidad e inviabilidad explícitas.

P09 usa exactamente los fixtures de actividades 03, 04, 09 y 12. Sus preguntas,
core observables, alternativas y misconceptions permanecen fijos. La
proyección versionada de las operaciones propias del fixture a los enums
canónicos sólo permite construir el request; no cambia los bytes ni declara un
golden P07. Ocho properties P09 de esas actividades quedan case-bound. Las 14
properties P09 de actividades sin fixture se conservan e indexan como
`EXPLICITLY_EXCLUDED/NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_ACTIVITY`; no hay
property oculta ni caso vacío.

Los `support_refs` del fixture permanecen como provenance del evaluador. El
request canónico P09 contiene únicamente el support de submission que ya
pertenece a las preguntas aprobadas; las referencias a assignment/rubric no se
convierten en evidence IDs ni amplían el bundle. El model-visible envelope sí
conserva question text, core observables, alternativas y misconceptions fijos.

El parser es `stage2-parser/2.0.0`. DOCX, PDF, Markdown y TXT atraviesan
`SafeParserService`; no existe parser alternativo, OCR especial ni
normalización favorable al corpus. El dry-run compara dos extracciones de las
72 submissions, incluidos artifact hashes, locators, IDs y agrupamiento.

## Properties y resultados

La compilación conserva el objeto raw, wording, ID, stage, kind, oracle state,
confidence, refs, alternativas, tags, hash de fuente y hash de ratification.

| Oracle state | Cantidad | Política |
|---|---:|---|
| `VALID` | 361 | utilizable para adjudicación |
| `ORACLE_SUSPECT` | 26 | revisión separada; nunca hard-failure denominator |
| `NOT_APPLICABLE` | 8 | trazable, fuera de denominador |
| `INVALID` | 0 | incompatible con el corpus READY |

Los kinds `REQUIRED`, `PROHIBITED`, `DEFENSIBLE_ALTERNATIVE` y
`CONTEXTUAL_NOTE` se preservan. Una confidence alta no vuelve hard una property.
La clasificación interna distingue `HARD_SEMANTIC_PROPERTY`,
`REVIEWABLE_SEMANTIC_PROPERTY`, `ORACLE_SUSPECT_PROPERTY` y
`NOT_APPLICABLE_PROPERTY`.

Los result states son mutuamente distintos:

- `PASS`;
- `MODEL_FAILURE`;
- `DEFENSIBLE_ALTERNATIVE`;
- `ORACLE_SUSPECT`;
- `TECHNICAL_FAILURE`;
- `NOT_APPLICABLE`;
- `PENDING_ADJUDICATION`.

El dry-run no tiene outputs de candidatos. Por eso las properties semánticas
aplicables quedan `PENDING_ADJUDICATION` y las ocho no aplicables conservan
`NOT_APPLICABLE`. No se puntúa output mock ni se genera review packet falso.

## Adjudicación y métricas

Cada property declara uno de tres modos. La distribución es:

| Stage | DETERMINISTIC | RULE_BASED | EXTERNAL_ADJUDICATION_REQUIRED |
|---|---:|---:|---:|
| P04 | 7 | 0 | 47 |
| P06 | 1 | 0 | 130 |
| PLANNER | 21 | 0 | 0 |
| P07 | 0 | 5 | 162 |
| P09 | 0 | 3 | 19 |
| Total | 29 | 8 | 358 |

`RULE_BASED` se limita a prohibiciones mecánicas explícitas de literal o
source/evidence membership. Interpretación, pertinencia, equivalencia,
suficiencia compleja y alternativas abiertas requieren adjudicación externa.
No existe LLM judge autoritativo.

El agregador futuro conserva runs dentro de su case, calcula success rate,
disagreement, alternativas, abstención y technical failures, y agrupa por
stage, candidate, reasoning, split, disciplina, dificultad, kind y tag. Cada
rate declara denominador. Las properties `ORACLE_SUSPECT`, `NOT_APPLICABLE`,
technical failures y pending no entran en el hard model-failure denominator.
`statistical_significance_claimed=false`; sólo se habilita comparación
descriptiva.

El schema de review packet contiene un único case/output/property, sus refs y
hashes necesarios. No incluye el corpus, audit history, old labels ni otros
held-out cases. Phase 8 sólo valida ese schema con un fixture sintético.

## Identidad, boundary y replay

Cada case fingerprint liga corpus version/package boundary, input hash,
stage, property IDs, fixture builder y benchmark version. El input hash liga
los contratos y envelopes canónicos más hashes de los archivos model-visible;
cambiar un byte de source invalida la identidad aunque el parser extrajera el
mismo texto. Candidate config queda fuera de la identidad del caso y entrará
en la identidad de la corrida futura.

El benchmark boundary liga además schemas, case matrix, split manifest,
compiled properties/evaluators, reglas de oracle/result, parser/planner,
compiler P04, materializadores P06/P07/P09, pipeline authority, validadores,
fixture builders e invariantes. No contiene timestamp, path absoluto, UUID ni
working directory. Se prueba en procesos separados.

## Splits y held-out

La estrategia normal reserva por actividad 03, 08, 09, 10 y 12, de manera
activity-disjoint. La única excepción explícita es P09: actividad 03 SMOKE,
04/09 CORE y 12 HELD_OUT, porque sólo existen cuatro fixtures y el stage debe
seguir siendo calificable.

| Split | P04 | P06 | PLANNER | P07 | P09 | Total |
|---|---:|---:|---:|---:|---:|---:|
| SMOKE | 1 | 4 | 2 | 5 | 1 | 13 |
| CORE | 6 | 37 | 13 | 37 | 2 | 95 |
| HELD_OUT_CONFIRMATION | 5 | 28 | 6 | 30 | 1 | 70 |

SMOKE incluye grounding, insufficiency, external knowledge, prompt injection,
P06 UNCERTAIN, multi-artifact, answer leakage, replacement, planner
feasible/infeasible y preservación P09. El reporte protege explícitamente
silent conceptual gap, P06 uncertain, simulated PII, silent injection,
authorized-source adversarial, multi-artifact, leakage, PLAN_INFEASIBLE y P09
cannot_infer.

Una vez iniciada Phase 9, HELD_OUT no puede ajustar prompt, reasoning, routing,
thresholds ni candidate list. Sólo confirma o rechaza la configuración ya
seleccionada. El candidato final debe completar esa confirmación.

## Calls y promoción futura

PLANNER nunca cuenta como llamada. Para un candidato hipotético sobre todos los
casos disponibles:

| k | P04 | P06 | P07 | P09 | Total |
|---:|---:|---:|---:|---:|---:|
| 1 | 12 | 69 | 72 | 4 | 157 |
| 3 | 36 | 207 | 216 | 12 | 471 |

Phase 9 no necesariamente ejecutará el full corpus por candidato. La plantilla
permite la ladder `SMOKE -> CORE -> HELD_OUT_CONFIRMATION`, k >= 3 para stages
semánticos y una ejecución para planner. Candidate IDs, modelos, snapshots,
reasoning, token/cost caps, promotion order y thresholds siguen `UNSET`. No se
publica precio: debe refrescarse justo antes de Phase 9.

## Ejecución offline

```bash
make semantic-benchmark-dry-run
```

El target elimina ambas API keys, fija mock/P10 false, valida el corpus,
construye fixtures/cases, ejecuta parser/planner/invariantes y escribe reportes
machine-readable en `reports/semantic_benchmark/v1/`. Su call graph no importa
gateway, adapter, transport, Secret Manager, autorización billable ni ledger
real. El resultado exige 13/13 invariantes y reporta:

- provider calls: 0;
- real transport: false;
- billable authorizations: 0;
- mock semantic scoring: false.

Frontend, base de datos, migrations, OpenAPI y runtime productivo son
`NOT_AFFECTED`.
