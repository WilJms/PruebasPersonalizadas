# Handoff consolidado — qualification controlada Luna/XHIGH de Fase 2

Fecha de corte: 2026-08-12 (America/Santiago).

Veredicto de cualificación: **`LUNA_XHIGH_QUALIFICATION_FAILED`**.<br>
Estado de convergencia: **`CONVERGENCE_INCOMPLETE`**.

La única matriz XHIGH autorizada no convergió. Este documento no autoriza
Fase 3/Fase 4 Ultra, datos estudiantiles reales, otra configuración de modelo,
build/deploy, `terraform apply`, migraciones remotas ni E2E cloud.

## 1. Linaje y frontera ejecutada

| Elemento | Valor |
|---|---|
| Repositorio / PR | `WilJms/PruebasPersonalizadas`, PR `#3` |
| Branch | `codex/openai-real-provider-gate` |
| Baseline Stage 2 | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Candidato HIGH previo | `93da59414fb49bd4df5c21af193a0226b4bc5fdb` |
| Evidencia posterior HIGH | `6c69e0359a1a0a327c49a6ce70d3959c384be779` |
| Candidato XHIGH congelado y ejecutado | `d41c2b3e6584ae2f202c3fceda0ec7d1a585242e` |
| Commit focal XHIGH | `d41c2b3` — soporte, ruta, harness y tests; sin remediación de producto |
| Rehearsal / reporte | `stage2-product-rehearsal/1.6.0` / `stage2-convergence-report/1.6.0` |
| Prompt pack | `1.1.14`, sin cambio |
| Ruta / modelo | `LUNA_XHIGH_V1` / sólo `gpt-5.6-luna` |
| Reasoning calificado | `XHIGH` en P04–P09 |
| Frontera ejecutable | `sha256:7d2dc1f8d8a1e3ca4b243b138b7a99d46e22273a5916a2bf2ff14f72f42791e4` |
| Frontera de autorización | `sha256:8bba730005ffd2c8667797fcc7f63ae7b4733bf8ef662529c60293a94ed883f7` |
| Authorization hash | `sha256:c72f0552ae8403cc05a08872540f86f066632d918f6a09cafe681a9e9a52df54` |
| Harness / módulo rehearsal | `sha256:c6caf99c109a9a4ba4e908d89c905dcc7301471c51747ad129a0f58eb4842ebc` / `sha256:20be58b90e943fae116cd9c743b2eda99e159aa8f295cdd5029a3b6686a64eaf` |
| Manifest | `sha256:d5991a48253eead5a4ba87653323177144fb67a4ae455ec9e2595a3e153ffb11` |
| Execution ID | `stage2-xhigh-d41c2b3-20260812-final-01` |

El commit documental posterior no forma parte de la frontera. El reporte y el
ledger conservan `git_head=d41c2b3…`; la autorización se reservó antes del
primer transporte y terminó `FAILED` exactamente una vez.

## 2. Delta exacto HIGH → XHIGH

Se añadió `ReasoningEffort.XHIGH` al modelo canónico, schema generado,
OpenAPI y cliente TypeScript. No se añadió `MAX`. Los tres derivados sólo
incorporan el nuevo valor del enum.

| Etapa | `LUNA_BASELINE_V1` | `LUNA_XHIGH_V1` | Estado en matriz |
|---|---|---|---|
| P01 / P02 | `MEDIUM` | `MEDIUM` | fuera de la matriz |
| P03 | `HIGH` | `HIGH` | checkpoint idéntico |
| P04–P09 | `HIGH` | `XHIGH` | cambio material único |
| P10 | sin ruta | sin ruta | 0 llamadas |
| P11 | `LOW` | `LOW` | 0 llamadas |

La identidad de todas las rutas cambia mecánicamente por el nuevo profile ID;
modelo, provider, snapshot callable, temperatura, límites de entrada/salida,
retención, fallback y caps permanecen iguales. La capability incorpora XHIGH.

La comparabilidad se probó contra el reporte HIGH publicado:

- mismos dos escenarios y hashes de checkpoints;
- mismos golden-positive y golden-negative P05, inputs y outputs;
- mismos prompt versions/hashes P04–P09;
- mismos system/developer prompts y schemas de output;
- mismos relationship/application validators y thresholds;
- mismos planner `stage2-planner/2.0.0` y assembler
  `stage1-assembler/2.0.0`;
- mismo SDK OpenAI `2.53.0`, adapter Responses y serialización; el payload
  XHIGH difiere del HIGH sólo en `reasoning.effort`;
- mismas policies, fixtures, zero-tools/store y retry policy;
- fingerprints de ejecución distintos por identidad/effort de ruta, sin
  cambiar los hashes del registro de prompts.

No hubo tuning de prompts, relajación de validators, normalización semántica,
cambio de thresholds, fixtures, golden, constructo ni datos académicos.

## 3. Regresión y budget antes de red

| Superficie | Resultado |
|---|---|
| Focal XHIGH / comparabilidad | 70/70 PASS |
| Backend + coverage | 620 PASS, 17 skips PostgreSQL cubiertos aparte, 1 warning conocido; 80% |
| Contratos | PASS; 53 roots, 141 `$defs`, 277 refs, 8 fixtures |
| Modelo / schema | `af8fda7041d8f216…` / `b028587932b0d510…` |
| OpenAPI / cliente | regeneración idempotente; `1dfae9e772f17d67…` / `0f411a8ca0b156cb…` |
| Rehearsal XHIGH offline | PASS; 24/24 simulados, 0 red; ambos golden PASS con 0 requests |
| Budget XHIGH fail-closed | USD `0.500531` total y `0.02583075` máximo por llamada |
| PostgreSQL 17 prepare | PASS; 31 tablas; contenedor efímero eliminado |
| PostgreSQL E2E / sensitive | 1/1 y 8/8 PASS |
| PostgreSQL migration/recovery/readiness | 206/206 PASS |
| Frontend | instalación limpia, typecheck, 36/36 tests, build y audit 0 vulnerabilidades |
| Deploy artifacts / seguridad | 11/11 PASS; secret scan PASS sobre 313 archivos versionables |
| CI push / PR del candidato | runs `31658509726` y `31658512804`: 7/7 jobs PASS cada uno |

Los caps sellados fueron 24 provider requests, USD 0.75 total y USD 0.10 por
llamada. El preflight conservador demostró suficiencia antes de la primera
request. Se confirmó soporte efectivo de `gpt-5.6-luna` con `xhigh` mediante la
única matriz, sin probe billable adicional.

No se inició build/deploy de producto, `terraform apply`, migración remota ni
E2E cloud. La CI estándar ejecutó sus validaciones aisladas habituales.

## 4. Única matriz real Luna/XHIGH

Inicio/fin UTC: `2026-08-13T01:49:10.686725Z` /
`2026-08-13T02:04:52.453060Z`.

| Observación | Requests | Resultado | Señal content-free |
|---|---:|---|---|
| Sweep independiente P04–P09 | 6 | **FAIL** | P04/P05/P06/P08/P09 PASS; P07 `UNAUTHORIZED_EVIDENCE`. P08 fue `ACCEPT`. |
| Golden-positive P05 offline | 0 | **PASS** | `APPROVABLE`, `READY`, recomendación `APPROVE`, validator PASS. |
| Golden-negative P05 offline | 0 | **PASS** | `REJECT` exacto; sólo `PLAN_FEASIBILITY=FAIL/critical`, validator PASS. |
| Cadena base 1 P04→P09 | 6 | **PASS** | P04–P09, planner y assembly completos; P08 `ACCEPT`. |
| Cadena base 2 P04→P09 | 6 | **PASS** | P04–P09, planner y assembly completos; P08 `ACCEPT`. |
| Variante choice P04→P09 | 2 | **FAIL** | P04 PASS; P05 `P05_REFERENCED_ID_NOT_ALLOWLISTED`; stop fail-closed. |

Las dos fallas son outputs model-owned contra fronteras contextuales válidas.
No hubo error de credencial, soporte XHIGH, red, SDK, schema, Pydantic,
runtime, infraestructura, pricing, caps ni ledger. No se corrigió ni reintentó
ningún output.

## 5. Requests, tokens, costo y controles

| Control | Resultado |
|---|---|
| Requests / cap | `20 / 24` |
| Input tokens | `95,245` |
| Cached input tokens | `38,234` |
| Cache-write input tokens | `56,951` |
| Output tokens | `133,148` |
| Reasoning tokens | `110,294` — subconjunto de output tokens |
| Costo actual / cap | USD `0.17479203 / 0.75` |
| Charge conservador | USD `0.32701443` |
| Máximo actual / cap por llamada | USD `0.0141085 / 0.10` |
| Máximo charge observado por llamada | USD `0.0203811` |
| Modelo | sólo `gpt-5.6-luna` |
| Reasoning efectivo | sólo `XHIGH` en P04–P09 |
| Boundary entre cadenas | `unchanged_boundary_across_chains=true` |
| P10 / P11 / fallback | `0 / 0 / 0` |
| Retry gateway / SDK / semántico | `0 / 0 / 0` |
| Normalización / prompt / fixture / validator changes | `0 / 0 / 0 / 0` |
| Tools / store | `false / false` |
| Attempts sin precio | `0` |
| Ledger | `FAILED`, `LUNA_XHIGH_QUALIFICATION_FAILED`, autorización consumida exactly-once |

Reporte machine-readable:
`reports/openai/stage2_xhigh_qualification_d41c2b3_20260812_final_01.json`,
SHA-256 `1b62c99b19781d923df9eda4082b8e73de64de2c4a4253b65d555e7d70e8db1a`.

## 6. Comparación descriptiva HIGH vs XHIGH

| Observación | Luna/HIGH | Luna/XHIGH |
|---|---|---|
| Sweep | P07 y P08 fallan | sólo P07 falla; P08 acepta |
| Base 1 | falla P08 | completa P04→P09 |
| Base 2 | falla P05 | completa P04→P09 |
| Choice | falla P06 tras P04/P05 | falla P05 tras P04 |
| Goldens P05 | PASS/PASS, 0 requests | PASS/PASS, 0 requests |
| Requests | 16/24 | 20/24 |
| Costo actual | USD 0.07123828 | USD 0.17479203 |
| Charge conservador | USD 0.27835468 | USD 0.32701443 |
| Veredicto | `LUNA_HIGH_QUALIFICATION_FAILED` | `LUNA_XHIGH_QUALIFICATION_FAILED` |

En esta única matriz XHIGH completó las dos cadenas base y evitó los rechazos
P08 observados con HIGH, pero no superó el sweep ni la variante choice. La
variante además falló antes, en P05. Es evidencia descriptiva de una ejecución,
no una demostración de superioridad estadística general.

## 7. Decisión y autoridad siguiente

| Criterio de PASS | Estado |
|---|---|
| Sweep P04–P09 sin fallas | **NO** — P07 `UNAUTHORIZED_EVIDENCE` |
| Golden-positive / negative P05 exactos | **SÍ / SÍ** |
| Dos cadenas base completas | **SÍ / SÍ** |
| Variante choice completa | **NO** — P05 referenced ID no allowlisted |
| Ningún P08 positivo REJECT/ESCALATE | **SÍ** — todos los P08 alcanzados fueron `ACCEPT` |
| 24 attempts previstos para qualification verde | **NO** — 20 por stop fail-closed |
| Frontera inmutable y controles en cero | **SÍ** |
| Regresión local y CI verdes antes del gate | **SÍ** |

**`LUNA_XHIGH_QUALIFICATION_FAILED`** y **`CONVERGENCE_INCOMPLETE`**.

El PR permanece draft y el candidato no queda listo para aprobación o deploy.
La autorización está consumida. No corresponde retry, tuning, cambio de
validator/threshold/fixture, MAX, Terra, Sol ni otra matriz dentro de esta
autoridad. La siguiente acción permitida es revisión humana de esta evidencia
content-free y una decisión explícita independiente; cualquier nuevo
experimento requeriría alcance, candidato y autorización nuevos.
