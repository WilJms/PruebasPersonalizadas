# Handoff consolidado — remediación final focalizada de Fase 2

Fecha de corte: 2026-08-12 (America/Santiago).

Veredicto de cualificación: **`LUNA_HIGH_QUALIFICATION_FAILED`**.<br>
Estado de convergencia: **`CONVERGENCE_INCOMPLETE`**.

Este documento consolida la única iteración autorizada después de la revisión
Pro final. No autoriza Fase 3/Fase 4 Ultra, datos estudiantiles reales,
build/deploy, `terraform apply`, migraciones remotas ni E2E cloud.

## 1. Frontera ejecutada

| Elemento | Valor |
|---|---|
| Repositorio / PR | `WilJms/PruebasPersonalizadas`, PR `#3` |
| Branch | `codex/openai-real-provider-gate` |
| Candidato congelado y ejecutado | `93da59414fb49bd4df5c21af193a0226b4bc5fdb` |
| Commits focales | `c35bd7a` P08/P05; `93da594` cliente OpenAPI derivado |
| Baseline Stage 2 | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Rehearsal / reporte | `stage2-product-rehearsal/1.5.0` / `stage2-convergence-report/1.5.0` |
| Prompt pack | `1.1.14` |
| Ruta / modelo | `LUNA_BASELINE_V1` / `gpt-5.6-luna` |
| Reasoning | `HIGH` en P04–P09 |
| Frontera ejecutable | `sha256:1626eec76899f91575a2a9856bd47176dfe7b7ec7e17c91fe96fa61c2f947ad8` |
| Frontera de autorización | `sha256:35dda6266a762a2f61b2f9c880445b3692da85f58d7e257ea5a3b98ce10a5dda` |
| Authorization hash | `sha256:750971682e2486508498af28a961406ac2b13419ed5de3726207f7fd38c1930b` |
| Harness | `sha256:620d5f31ef16fab816c1fd8c7a5c372dfc7176ea925cd93bc80fbd202e7f9d37` |
| Módulo rehearsal | `sha256:18b6639e87bb78b9a6fde81fb277971fd25d862deaef5c1c817f3ff9b96bd973` |
| Manifest | `sha256:d5991a48253eead5a4ba87653323177144fb67a4ae455ec9e2595a3e153ffb11` |
| Execution ID | `stage2-convergence-93da594-20260812-final-01` |

El commit documental posterior no forma parte de esta frontera. El reporte
conserva `git_head=93da594…` y el ledger durable consumió una sola autorización.

## 2. Cierre focal determinista

### P08: review limitado a la candidata

El validador fail-closed existente no se relajó:

- `review.evidence_ids ⊆ generation_result.candidate.evidence_ids`;
- `review.source_ids ⊆ generation_result.candidate.course_source_ids`;
- un ID presente sólo en `evidence_bundle` u `opportunity` no queda autorizado;
- `[]` es el valor explícito cuando el review no necesita referencias;
- P08 revisa la candidata y nunca amplía su frontera.

La obligación quedó expresada una sola vez en el prompt ejecutable y en las
descripciones del modelo canónico; schema, OpenAPI y cliente TypeScript fueron
regenerados desde esa autoridad.

| Material P08 | Anterior | Candidato final |
|---|---|---|
| Versión | `1.1.4` | `1.1.5` |
| Prompt hash | `sha256:0514112a43750f7891b47eaf2cff7bec8cc52d2b2763c0c588e115a48edf50fc` | `sha256:f63230dde5dadbbba78b24ae229fefc61a6b7d072a9c3d7c1ea9044be2463949` |
| Input schema | `sha256:3af65fdec7493a6eccc9d8eb636f989fcda5e1774a5dfad717b921be0a4db54d` | sin cambio |
| Output schema | `sha256:122c5e9fe03ab8e546e1dc36e6f7829184e1c8025167f60fbae3f07e041bdd8a` | `sha256:7f9e72c2a44a91e23f09c6ec82675767524ab749124948b2c2ba1ec2c6f45ebb` |
| Relationship / application validator | `relationship-p08/2.1.0` / `application-validator-p08/2.0.0` | sin cambio |

No hubo tuning semántico de P04/P05/P06/P07/P09.

### P05: oráculo fiel al producto

`stage2-p05-golden-checkpoints/1.1.0` conserva intactos el blueprint positivo,
el contenido semántico y la mutación negativa. Sólo corrige el oráculo:

- positivo esperado: `APPROVABLE`, definido como `READY`, sin FAIL crítico y
  recomendación distinta de `REJECT`; no exige `APPROVE`;
- negativo: atraviesa `build_blueprint_review_preflight` y
  `validate_blueprint_review_preflight_checks` del producto;
- las cinco categorías deterministas se derivan mediante una sola función
  compartida por mock, validator y oráculo;
- la comparación es igualdad exacta de status/criticality y del conjunto de
  categorías críticas.

| Evidencia P05 | Resultado |
|---|---|
| Fixture / hash | `stage2-p05-golden-checkpoints/1.1.0` / `sha256:9f6849dfc8ff2aceee569d1c44122e589ace1c519fc171c50f3fdf4a05e9e9b0` |
| Positivo | `APPROVABLE`, `READY`, sin FAIL crítico, recomendación no `REJECT`, validator PASS, 0 requests |
| Input / output positivo | `sha256:cd6ac2ac5c2b74f810c7f0a3a665027c4c86c1941dca39899a7f200ba47d99af` / `sha256:5efb926236c47900bc4155fbd41664a6d0f72c7a10c2aa20937a6e237d4aabdd` |
| Negativo | `REJECT`; sólo `PLAN_FEASIBILITY=FAIL/critical`; las otras cuatro categorías `PASS/non-critical`; validator PASS; 0 requests |
| Input / output negativo | `sha256:430295f51b164a6b3ca671ae50180f97c8f1926f4e532eb45cea8cb5c53cf9ff` / `sha256:0692536d463be7b0404ece104bff425dc971edd10b470102ad3cf7203f88a8a0` |
| Application validator | `application-validator-p05/2.2.0` |

## 3. Regresión previa al gate real

| Superficie | Resultado |
|---|---|
| Backend + coverage | `609 passed`, 17 skips PostgreSQL cubiertos por su matriz, 1 warning conocido; 80% |
| Focal P05/P08/gateway/validation | 156/156 PASS; subconjunto inicial 124/124 PASS |
| PostgreSQL 17 prepare | PASS; 31 tablas |
| PostgreSQL E2E / sensitive | 1/1 y 8/8 PASS |
| PostgreSQL migration/recovery/readiness | 206/206 PASS |
| Frontend | instalación limpia, 0 vulnerabilidades, typecheck, 36/36 tests y build PASS |
| Contratos | 53 roots, 141 `$defs`, 277 refs, 8 fixtures; modelo `1abd49c3…`, schema `d2375484…` |
| Schema / OpenAPI / cliente | regeneración idempotente y sin drift sobre el candidato final |
| Rehearsal offline | PASS; 24/24 fake; golden positivo/negativo PASS y 0 requests; P10/P11/fallback/retries 0 |
| Exactly-once + cache/reuse focal | 8/8 PASS |
| Secret scan | PASS sobre 312 archivos versionables después de crear el reporte |
| Terraform | `fmt -check`, `init -backend=false`, `validate` PASS |
| CI push / PR del candidato | runs `31649989407` y `31649992484`: 7/7 jobs PASS cada uno |

Un primer CI preflight detectó sólo drift del cliente OpenAPI generado. Se
regeneró el artefacto derivado, se volvió a congelar el SHA y ambos CI finales
quedaron verdes antes de resolver la clave. Esa corrección consumió 0 requests.

El PostgreSQL temporal fue detenido y eliminado. No se ejecutó build/deploy,
`terraform apply`, migración remota ni E2E cloud.

## 4. Única matriz Luna final

Inicio/fin UTC: `2026-08-12T23:17:26.226364Z` /
`2026-08-12T23:23:42.870476Z`.

| Observación | Requests | Resultado | Señal content-free |
|---|---:|---|---|
| Sweep independiente P04–P09 | 6 | **FAIL** | P07 `UNAUTHORIZED_EVIDENCE`; P08 `REJECT`, answerability bajo threshold y critical failure declarado. P04/P05/P06/P09 PASS. |
| Cadena base 1 P04→P09 | 5 | **FAIL** | P04/P05/P06/planner/P07 PASS; P08 `REJECT` con critical failure declarado. |
| Cadena base 2 P04→P09 | 2 | **FAIL** | P04 PASS; P05 `P05_REFERENCED_ID_NOT_ALLOWLISTED`. |
| Variante choice P04→P09 | 3 | **FAIL** | P04/P05 PASS; P06 `UNSUPPORTED_COGNITIVE_OPERATION`. |
| Golden P05 positivo y negativo | 0 | **PASS/PASS** | `APPROVABLE` y rechazo exacto por `PLAN_FEASIBILITY`, respectivamente. |

Los cuatro stops son outputs model-owned bajo fronteras explícitas o una señal
semántica P08 negativa. No hubo fallo de credencial, red, schema, Pydantic,
runtime, infraestructura, pricing ni ledger. Los validadores fallaron cerrado y
no normalizaron semántica.

| Control | Resultado |
|---|---|
| Requests / cap | `16 / 24` |
| Costo actual / cap | `USD 0.07123828 / USD 0.75` |
| Charge conservador | `USD 0.27835468` |
| Cap por llamada | `USD 0.10` |
| Modelo / reasoning | sólo `gpt-5.6-luna` / `HIGH` |
| Boundary entre cadenas | `unchanged_boundary_across_chains=true` |
| P10 / P11 / fallback | `0 / 0 / 0` |
| Retry gateway / SDK / semántico | `0 / 0 / 0` |
| Tools / store | `false / false` |
| Attempts sin precio | `0` |
| Ledger | `FAILED`, `OPENAI_CONVERGENCE_FAILED`, autorización consumida exactly-once |

Reporte machine-readable:
`reports/openai/stage2_convergence_93da594_20260812_final_01.json`, SHA-256
`30a422dc79a2098ff6e7066a39cb2517e959d2d1d8a169f287c68101c2dc519e`.

## 5. Matriz de decisión final

| Criterio | Estado | Evidencia |
|---|---|---|
| P08 comunica y valida la frontera de la candidata | **SÍ** | Prompt/model/schema explícitos; validators sin relajar; tests positivos y negativos PASS |
| Golden positivo P05 usa la transición real | **SÍ** | `APPROVABLE`, no igualdad rígida con `APPROVE` |
| Golden negativo P05 usa validators de producto | **SÍ** | Matriz exacta; sólo `PLAN_FEASIBILITY` crítico; 0 requests |
| Sweep P04–P09 completo | **NO** | P07/P08 fallaron |
| Dos cadenas base completas bajo frontera idéntica | **NO** | Base 1 falló P08; base 2 falló P05 |
| Variante choice completa | **NO** | P06 falló |
| Cero fallos técnicos/no-Luna | **SÍ** | Credencial, red, schema, Pydantic, runtime, ledger y caps operaron correctamente |
| Regresión local y CI verdes antes del gate | **SÍ** | Suites locales y dos runs remotos 7/7 |
| Candidato apto para revisión independiente | **NO** | La matriz real no convergió |

## 6. Decisión y autoridad siguiente

**`LUNA_HIGH_QUALIFICATION_FAILED`** y **`CONVERGENCE_INCOMPLETE`**.

El PR permanece draft y el candidato no pasa a Fase 4 Ultra. No corresponde
tuning, retry, segunda matriz, cambio a XHIGH, intercambio de modelo ni
relajación de validators dentro de esta autorización. Cualquier continuación
requiere una decisión humana posterior, un alcance nuevo y otra autorización;
este handoff no la presupone.
