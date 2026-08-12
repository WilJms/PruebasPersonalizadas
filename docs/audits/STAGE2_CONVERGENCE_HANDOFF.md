# Handoff consolidado — cierre focalizado de Fase 2

Fecha de corte: 2026-08-12 (America/Santiago).

Estado final: **`CONVERGENCE_INCOMPLETE`**.

Este documento consolida la única iteración solicitada después de la revisión
Pro. No autoriza Fase 3/Fase 4 Ultra, datos estudiantiles reales, build/deploy,
`terraform apply`, migraciones remotas ni E2E cloud.

## 1. Frontera exacta

| Elemento | Valor |
|---|---|
| Repositorio / PR | `WilJms/PruebasPersonalizadas`, PR `#3` |
| Branch | `codex/openai-real-provider-gate` |
| Candidato ejecutado | `4e53767d79555b27efc5c7d92344d6f10db1b221` |
| Commit del candidato | `Close Stage 2 convergence review gaps` |
| Baseline Stage 2 | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Rehearsal / reporte | `stage2-product-rehearsal/1.4.0` / `stage2-convergence-report/1.4.0` |
| Prompt pack | `1.1.13` |
| Ruta / modelo | `LUNA_BASELINE_V1` / `gpt-5.6-luna` |
| Frontera ejecutable | `sha256:118da5dd9b9f18f41181b24fd7ecd39ed52f9afb77c60206a9cfa46ae81ea0ba` |
| Frontera de autorización | `sha256:cae1eaf6c27c094cbdb0a4e20d9d99f65cf0aba84e29ea5789293591b734ef98` |
| Frontera productiva del provider | `sha256:be65de1bed684d1df8ecd53e2264acd3a0319d873370033b906bb365f957af71` |
| Harness | `sha256:620d5f31ef16fab816c1fd8c7a5c372dfc7176ea925cd93bc80fbd202e7f9d37` |
| Módulo rehearsal | `sha256:e7d70f52c93fb5bb544bfa3efa0b20c44dd68485697496b8f1fbd62330893025` |
| Manifest | `sha256:07f06a0f872956b156ca5207f32352f708334984dcb6e9b5d8757a1f6a45980b` |
| Execution ID | `stage2-convergence-4e53767d-20260812-01` |
| Authorization hash | `sha256:bd65fe864042fd60ffc50c3683fd2d52fea1ee42b0ef318ef16333576c355e82` |

El commit que contiene este handoff y el reporte es evidencia posterior y no
forma parte de la frontera ejecutada. El PR debe distinguir su HEAD documental
del SHA candidato anterior; un documento versionado no puede contener el hash
de su propio commit.

## 2. Veredicto ejecutivo

Los gaps deterministas solicitados quedaron cerrados: la capacidad real está
aislada del producto ordinario; P05 tiene un positivo sintético concreto y un
negativo conocido; P06 emite predicados estables; P08 registra diagnósticos
content-free; y toda la regresión local/remota quedó verde sobre el candidato.

La única matriz Luna autorizada no alcanzó convergencia. Bajo una frontera
inmutable:

- el sweep independiente pasó P04, P05, P06, P07 y P09, pero P08 amplió los
  `evidence_ids` del candidato y fue bloqueado con `UNAUTHORIZED_EVIDENCE`;
- la cadena base 1 pasó P04 y luego P05 emitió `referenced_ids` fuera de los IDs
  presentes en su request; el gateway la bloqueó con
  `P05_REFERENCED_ID_NOT_ALLOWLISTED`;
- la cadena base 2 completó P04→P09;
- la variante choice completa también completó P04→P09;
- el golden-negative P05 fue rechazado offline por la causa prevista, sin
  consumir una request.

Los dos fallos son incumplimientos contractuales/contextuales de outputs del
modelo, no fallos de schema, Pydantic, credenciales, red, runtime o
infraestructura. Los validadores fallaron cerrado y conservaron el predicado
exacto. Conforme al criterio acordado, Luna queda como **blocker de
cualificación/confiabilidad para este candidato**. Las dos cadenas completas
demuestran capacidad posible, no estabilidad suficiente ni incapacidad general.

No hubo retry, segunda matriz, cambio de prompt, relajación de validator,
normalización semántica, fallback ni cambio de modelo después del resultado.

## 3. Autoridad y aislamiento del provider real

La arquitectura resultante expresa una sola autoridad:

1. Web y worker ordinario conservan `CVA_MODEL_MODE=mock`; settings no ofrecen
   un flag productivo para construir `GatewayMode.REAL`.
2. El worker ordinario no recibe clave, referencia al secreto ni IAM para leerlo.
3. El job sintético de evaluación es una superficie distinta, con service
   account propio. Sólo esa identidad puede leer la versión numérica fijada del
   secreto; la clave nunca viaja como variable de entorno.
4. La autorización durable queda ligada al job, artefactos sintéticos, SHA,
   hashes de frontera, ruta/modelo, request cap y cost cap.
5. El orden obligatorio es claim exacto `RUNNING` → consumo exactly-once de la
   autorización → resolución del secreto → construcción del transporte.
6. Job ordinario, attestation ausente, SHA/hash divergente, claim incorrecto o
   autorización ya consumida terminan antes del resolver, transporte y primera
   request. Las regresiones prueban los tres contadores en cero.
7. P10 permanece deshabilitado en producto, cloud y evaluación. La matriz
   además mantuvo P11, fallback, retries, tools y store en cero.

Terraform mantiene service/job, imágenes y permisos separados. Esto fue
validado de forma estática; no se aplicó infraestructura ni se afirma estado
runtime cloud.

## 4. Golden P05 y diagnósticos

### P05

El positivo genérico del mock fue sustituido por
`stage2-p05-golden-checkpoints/1.0.0`, un fixture sintético versionado que modela
un constructo causal concreto de invalidación de caché, cinco rationales
semánticos, alineación con fuentes, blueprint y oportunidades coherentes.

| Evidencia | Hash / resultado |
|---|---|
| Golden positivo | `sha256:b0b40365dfd369991e7689c788668a9e087475458b01dba38af333b217596a89` |
| Estado de revisión | `SEMANTICALLY_REVIEWED_SYNTHETIC_FIXTURE` |
| Input negativo | `sha256:430295f51b164a6b3ca671ae50180f97c8f1926f4e532eb45cea8cb5c53cf9ff` |
| Output negativo | `sha256:d38c61ce937f3f5135080c2af99cbbf8a9c9f8e865418aea853b5a3757df2db6` |
| Oráculo negativo | `REJECT`, categoría crítica `PLAN_FEASIBILITY`, campos `catalog_plan_feasible` y `policy_constraints_match` fallidos |

El negativo obtuvo exactamente ese resultado offline. P05 no fue relajado.

### P06

`relationship-p06/2.3.0` reemplaza el mismatch genérico por códigos
deterministas por predicado: submission, conteo, elegibilidad, template,
dimension/variant, operación cognitiva, foco, observable, dificultad, tiempo,
anchors, formatos, justificación, prioridad, fit/scope de evidencia, calidad y
ruta. Los códigos se agregan en orden estable y sin duplicados.

### P08

La observabilidad registra únicamente decisión `ACCEPT/REJECT/ESCALATE`,
criticality/conteo, categorías y códigos seguros, hashes de códigos raw y la
relación score/threshold de cada dimensión. No persiste texto del estudiante,
anclas ni outputs del modelo. En las dos cadenas completas P08 emitió
`ACCEPT`, `NON_CRITICAL`, cero fallos críticos y todos los scores en o sobre su
threshold. El fallo del sweep ocurrió antes de aceptación por el predicado
contextual exacto `UNAUTHORIZED_EVIDENCE`.

## 5. Regresión sobre el candidato congelado

| Superficie | Resultado |
|---|---|
| Backend final | `make test`: 607 passed, 17 skipped esperados, 1 warning conocido |
| Cobertura | `make test-cov`: 604 passed antes de tres casos adicionales; 80%. El `make test` final cubrió 607 y no hubo cambio productivo posterior. |
| PostgreSQL 17 prepare | PASS; 31 tablas |
| PostgreSQL E2E | 1/1 PASS |
| PostgreSQL sensitive | 8/8 PASS, incluida autorización exactly-once y append-only |
| PostgreSQL migration/recovery/readiness | 206/206 PASS |
| Frontend | instalación limpia sin vulnerabilidades; typecheck PASS; 36/36 tests; build PASS |
| Contratos | 53 roots, 141 `$defs`, 277 refs, 8 fixtures; hashes canónicos sin drift |
| OpenAPI / fixtures | regeneración sin diff |
| Rehearsal offline | PASS; 24 intentos fake, negativo P05 PASS/0 requests, P10/P11/fallback/retries 0 |
| Secret scan | PASS sobre 310 archivos versionables |
| Terraform | `fmt`, `init -backend=false`, `validate` PASS |
| CI remoto candidato | run `31637415306`: 7/7 jobs PASS, incluidos PG16, PG17, frontend, browser E2E, Docker/audit, Terraform/static y backend/contracts |

El PostgreSQL temporal fue detenido y eliminado. No se ejecutó build/deploy,
`terraform apply`, migración remota ni E2E cloud.

## 6. Única matriz real decisiva

Inicio/fin UTC: `2026-08-12T20:30:21.557042Z` /
`2026-08-12T20:39:14.973763Z`.

| Observación | Requests | Resultado | Señal |
|---|---:|---|---|
| Sweep independiente P04–P09 | 6 | **FAIL** | P04/P05/P06/P07/P09 PASS; P08 `UNAUTHORIZED_EVIDENCE` |
| Cadena base 1 P04→P09 | 2 | **FAIL** | P04 PASS; P05 `P05_REFERENCED_ID_NOT_ALLOWLISTED` |
| Cadena base 2 P04→P09 | 6 | **PASS** | P04→P09 completos; P08 ACCEPT |
| Variante choice P04→P09 | 6 | **PASS** | P04→P09 completos; P08 ACCEPT |
| Golden-negative P05 | 0 | **PASS** | REJECT / `PLAN_FEASIBILITY` esperado |

Controles sellados:

| Control | Resultado |
|---|---|
| Requests / cap | `20 / 24` |
| Costo actual / cap | `USD 0.08738144 / USD 0.75` |
| Charge conservador | `USD 0.32618144` |
| Cap por llamada | `USD 0.10` |
| Modelo | sólo `gpt-5.6-luna` |
| Reasoning | `HIGH` en P04–P09 |
| Boundary entre cadenas | `unchanged_boundary_across_chains=true` |
| P10 / P11 / fallback | `0 / 0 / 0` |
| Retry gateway / SDK / semántico | `0 / 0 / 0` |
| Tools / store | `false / false` |
| Attempts sin precio | `0` |
| Estado del ledger | `FAILED`, autorización consumida exactly-once |

Reporte machine-readable:
`reports/openai/stage2_convergence_4e53767d_20260812_01.json`, SHA-256
`1b95209f429df7fdb7d19e3c5412a36ae932bd02835ceff2b54e552e61f9961c`.

## 7. Matriz de convergencia

| Criterio | Estado | Evidencia |
|---|---|---|
| Positivos del sweep P04–P09 | **NO** | P08 amplió evidencia; código exacto `UNAUTHORIZED_EVIDENCE` |
| Golden-negative P05 rechazado por causa esperada | **SÍ** | REJECT / `PLAN_FEASIBILITY`, 0 requests |
| Cadena base 1 completa | **NO** | P05 referenció ID no allowlisted |
| Cadena base 2 completa sin cambio de frontera | **SÍ** | P04→P09 PASS |
| Variante choice completa | **SÍ** | P04→P09 PASS |
| Cero fallos schema/Pydantic/context/security en positivas | **NO** | Dos outputs violaron controles contextuales; cero fallos schema/Pydantic/security |
| Autoridad/settings/runtime/Terraform coherentes | **SÍ** | Producto mock; real sólo en job sintético autorizado |
| Provider real imposible fuera del gate exacto | **SÍ, probado local/estáticamente** | Casos normal/missing/mismatch/wrong claim con resolver/transporte/requests = 0 |
| Regresión y CI verdes | **SÍ** | Suites locales y run remoto 7/7 PASS |
| Evidencia ligada al SHA candidato | **SÍ** | Reporte `git_head=4e53767d…` y hashes sellados |
| Caps y controles conservados | **SÍ** | 20 requests, USD 0.08738144; todo fallback/retry/tool/store/P10/P11 en cero |
| Luna cualificada para liberar el candidato | **NO** | Dos incumplimientos de output bajo frontera congelada |
| REL-001 cloud | **DIFERIDO** | Cloud estaba expresamente fuera de alcance; no hay assertions de deploy/runtime |

## 8. Decisión y siguiente autoridad

**`CONVERGENCE_INCOMPLETE`**.

El PR debe permanecer draft y el candidato no debe congelarse para Fase 4 Ultra.
No corresponde otra matriz, retry ni ajuste oportunista dentro de esta
autorización. Cualquier continuación requerirá una decisión humana posterior,
un alcance nuevo y una autorización nueva; este cierre no la presupone.
