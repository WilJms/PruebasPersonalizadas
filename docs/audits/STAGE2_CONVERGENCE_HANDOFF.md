# Handoff consolidado — qualification final Luna/MAX de Fase 2

Fecha de corte: 2026-08-12 (America/Santiago).

Veredicto: **`LUNA_MAX_QUALIFICATION_FAILED`**.<br>
Familia: **`LUNA_FAMILY_QUALIFICATION_EXHAUSTED`**.<br>
Convergencia: **`CONVERGENCE_INCOMPLETE`**.

La única matriz Luna/MAX autorizada no superó la qualification congelada. La
experimentación HIGH/XHIGH/MAX de Luna para esta frontera queda agotada. Esto
no afirma incapacidad general de Luna y no autoriza otra configuración, otro
modelo, Fase 3/Fase 4 Ultra, build/deploy, `terraform apply`, migración remota
ni E2E cloud.

## 1. Linaje y frontera ejecutada

| Elemento | Valor |
|---|---|
| Repositorio / PR | `WilJms/PruebasPersonalizadas`, PR `#3` (draft) |
| Branch | `codex/openai-real-provider-gate` |
| Baseline Stage 2 | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Candidato / evidencia HIGH | `93da59414fb49bd4df5c21af193a0226b4bc5fdb` / `6c69e0359a1a0a327c49a6ce70d3959c384be779` |
| Candidato / evidencia XHIGH | `d41c2b3e6584ae2f202c3fceda0ec7d1a585242e` / `23a16668c3cdd325919acfb5c871db30aefa0dc2` |
| Candidato MAX congelado y ejecutado | `62d73ae5f183c0da4fb87a9ba673905c64225880` |
| HEAD documental posterior | commit Git que contiene este handoff y el reporte consolidado; el SHA exacto se publica en el PR y en la entrega final para evitar una autorreferencia hash imposible |
| Rehearsal / reporte de ejecución | `stage2-product-rehearsal/1.7.0` / `stage2-convergence-report/1.7.0` |
| Prompt pack | `1.1.14`, sin cambio semántico |
| Ruta / modelo | `LUNA_MAX_V1` / sólo `gpt-5.6-luna` |
| Reasoning calificado | `MAX` en P04–P09 |
| Frontera ejecutable | `sha256:70f6796c222955705caee704e164a4c6a7030eaacc78947a381f9b1e20ca82cf` |
| Frontera de autorización | `sha256:62aad8356cb235e5ab4c22120a4413cdb1ab473c3c15bac21798f1412c63ee81` |
| Authorization hash | `sha256:77543f242723b44bff268e3c3cff3a2c786895eb8df264798ab911a114c8e990` |
| Harness / módulo rehearsal | `sha256:a690aff9025973eaa4257d03a8356d34924116667e38b84cc30bbbfc414f9cff` / `sha256:9f7c626a61409ed1acf2ee51c0bc1aafe507f9c634ade9b13669fb01b89d453e` |
| Manifest | `sha256:d5991a48253eead5a4ba87653323177144fb67a4ae455ec9e2595a3e153ffb11` |
| Execution / authorization ID | `stage2-max-62d73ae-20260812-final-01` / `authorization-stage2-max-62d73ae-20260812-final-01` |

La autorización nueva se reservó antes del primer transporte y se consumió
exactamente una vez. El candidato ejecutado permanece ligado a `62d73ae…`; el
commit documental posterior no integra ni altera esa frontera.

Los reportes fuente HIGH/XHIGH son, respectivamente,
`reports/openai/stage2_convergence_93da594_20260812_final_01.json`
(`sha256:30a422dc79a2098ff6e7066a39cb2517e959d2d1d8a169f287c68101c2dc519e`)
y `reports/openai/stage2_xhigh_qualification_d41c2b3_20260812_final_01.json`
(`sha256:1b62c99b19781d923df9eda4082b8e73de64de2c4a4253b65d555e7d70e8db1a`).

## 2. Delta exacto XHIGH → MAX

Se añadió `ReasoningEffort.MAX` a la fuente canónica y, mecánicamente, al
schema generado, OpenAPI y cliente TypeScript. Se creó la identidad
`LUNA_MAX_V1`; no se reutilizó ninguna ruta previa.

| Etapa | `LUNA_XHIGH_V1` | `LUNA_MAX_V1` | Uso en matriz |
|---|---|---|---|
| P01 / P02 | `MEDIUM` | `MEDIUM` | fuera de matriz |
| P03 | `HIGH` | `HIGH` | checkpoint idéntico |
| P04–P09 | `XHIGH` | `MAX` | cambio material único |
| P10 | sin ruta | sin ruta | 0 llamadas |
| P11 | `LOW` | `LOW` | 0 llamadas |

Permanecieron iguales: provider/model, system/developer/task prompts, hashes y
versiones P04–P09, fixtures product-shaped, ambos golden P05, policies,
inputs académicos sintéticos, schemas funcionales salvo el enum mecánico,
relationship/application validators, thresholds, planner
`stage2-planner/2.0.0`, assembler `stage1-assembler/2.0.0`, SDK OpenAI `2.53.0`,
adapter Responses, zero-tools/store y retries en cero. El payload XHIGH/MAX
difiere materialmente sólo en `reasoning.effort`. No hubo tuning ni
remediación de producto.

## 3. Regresión, budget y CI antes de red

| Superficie | Resultado |
|---|---|
| Focal MAX / adapter / harness | 80/80 PASS |
| Backend completo | 647 tests: 630 PASS, 17 skips PostgreSQL cubiertos aparte, 0 fallas/errores |
| PostgreSQL 17 | prepare 31 tablas; E2E 1/1; sensitive 8/8; migration/recovery/readiness 206/206 PASS; contenedor eliminado |
| Contratos | PASS: 53 roots, 141 `$defs`, 277 refs, 8 fixtures; regeneración idempotente |
| Modelo / schema | `3f1a42102b10a558…` / `318f1dceee27f919…` |
| OpenAPI / cliente | `83cd3dbcc728c613…` / `2ee42d9587897ddc…` |
| Rehearsal MAX offline | PASS; 24/24 simulados, 0 red; ambos golden PASS con 0 requests |
| Budget MAX fail-closed | USD `0.500519` total y `0.02583025` máximo por llamada |
| Frontend | instalación limpia, typecheck, 36/36 tests, build y audit 0 vulnerabilidades |
| Terraform/static / deploy tests | fmt/init backend=false/validate PASS; 11/11 PASS |
| Secret scan | PASS sobre 313 archivos versionables |
| CI push / PR del candidato | runs `31661764201` y `31661765833`: 7/7 jobs PASS cada uno |

Los caps sellados —24 requests, USD 0.75 total, USD 0.10 por llamada— fueron
suficientes. También se probó fail-closed con caps incorrectos: bloqueo
`OPENAI_MAX_QUALIFICATION_EXACT_CAPS_REQUIRED`, 0 llamadas. No hubo Cloud
Build, deploy, `terraform apply`, migración remota ni E2E cloud.

## 4. Única matriz real Luna/MAX

Inicio/fin UTC: `2026-08-13T02:51:40.389894Z` /
`2026-08-13T03:04:29.893520Z`.

| Observación | Attempts | Resultado | Señal content-free |
|---|---:|---|---|
| Sweep independiente P04–P09 | 6 | **FAIL** | P05/P06/P09 PASS. P04 y P08 `MODEL_PROVIDER_ERROR`. P07 `MODEL_OUTPUT_VALIDATION_FAILED` + `OUTPUT_PYDANTIC_VALIDATION_FAILED`, `value_error` en `/candidate`. |
| Golden-positive P05 offline | 0 | **PASS** | `APPROVABLE`, `READY`, `APPROVE`, validator PASS. |
| Golden-negative P05 offline | 0 | **PASS** | `REJECT` exacto; sólo `PLAN_FEASIBILITY=FAIL/critical`, validator PASS. |
| Cadena base 1 P04→P09 | 1 | **FAIL** | P04 `MODEL_PROVIDER_ERROR`; stop fail-closed. |
| Cadena base 2 P04→P09 | 1 | **FAIL** | P04 `MODEL_PROVIDER_ERROR`; stop fail-closed. |
| Variante choice P04→P09 | 1 | **FAIL** | P04 `MODEL_PROVIDER_ERROR`; stop fail-closed. |

No se sustituyó ningún output, no se cambió la frontera y no hubo retry ni
segunda matriz. El P07 positivo del sweep produjo una violación Pydantic
model-owned. Según la regla terminal explícita, esa sola observación basta para
`LUNA_MAX_QUALIFICATION_FAILED`, aunque coexistan cinco intentos con error
técnico del proveedor.

## 5. Corrección post-ejecución del clasificador

El recibo crudo clasificó el conjunto mixto como
`MAX_QUALIFICATION_INCONCLUSIVE` porque el clasificador daba precedencia a
`MODEL_PROVIDER_ERROR`. Esa precedencia contradice la regla humana: cualquier
fallo positivo model-owned contractual/Pydantic es terminal.

Se preservó sin modificar el recibo crudo y su hash del ledger. El reporte
consolidado aplica la regla dominante y registra:

- clasificación causal:
  `MODEL_OWNED_QUALIFICATION_FAILURE_WITH_TECHNICAL_FAILURES`;
- veredicto: `LUNA_MAX_QUALIFICATION_FAILED`;
- familia: `LUNA_FAMILY_QUALIFICATION_EXHAUSTED`;
- autoridad siguiente:
  `HUMAN_REVIEW_OF_LUNA_EXHAUSTION_NO_AUTOMATIC_MODEL_CHANGE`.

El clasificador post-ejecución quedó corregido y cubierto por un test del caso
mixto. Esto no modifica prompts, schemas funcionales, validators, fixtures,
outputs, candidato ejecutado ni ledger, y no genera requests.

## 6. Requests, tokens, costo y controles MAX

| Control | Resultado |
|---|---|
| Provider attempts / cap | `9 / 24` |
| Input tokens | `142,256` |
| Cached input / cache-write input | `0 / 16,897` |
| Output tokens | `39,893` |
| Reasoning tokens | `35,493` — subconjunto de output tokens |
| Costo actual / cap | USD `0.05209825 / 0.75` |
| Charge conservador | USD `0.1843634` |
| Máximo actual / cap por llamada | USD `0.01493045 / 0.10` |
| Máximo charge conservador por llamada | USD `0.02583025` |
| Attempts sin precio | `5` — los errores de proveedor |
| Modelo / reasoning | sólo `gpt-5.6-luna` / sólo `MAX` en P04–P09 |
| Boundary | `unchanged_boundary_across_chains=true` |
| P10 / P11 / fallback | `0 / 0 / 0` |
| Retry gateway / SDK / semántico | `0 / 0 / 0` |
| Normalización / prompt / fixture / validator / threshold changes | `0 / 0 / 0 / 0 / 0` |
| Tools / store | `false / false` |
| P08 positivos | ninguno produjo decisión: sweep falló en transporte; cadenas no llegaron a P08 |

## 7. Comparación descriptiva HIGH / XHIGH / MAX

| Configuración | Runs completos | Fallos principales | Requests | Tokens input / output / reasoning | Costo actual / conservador | P08 alcanzados | Veredicto |
|---|---|---|---:|---|---|---|---|
| Luna/HIGH `93da594…` | ninguno | sweep P07/P08; base 1 P08; base 2 P05; choice P06 | 16 | no registrados / no registrados / no registrados | USD `0.07123828` / `0.27835468` | sweep/base 1 `REJECT` | `LUNA_HIGH_QUALIFICATION_FAILED` |
| Luna/XHIGH `d41c2b3…` | base 1 y base 2 | sweep P07 `UNAUTHORIZED_EVIDENCE`; choice P05 ID no allowlisted | 20 | `95,245 / 133,148 / 110,294` | USD `0.17479203` / `0.32701443` | sweep/base 1/base 2 `ACCEPT` | `LUNA_XHIGH_QUALIFICATION_FAILED` |
| Luna/MAX `62d73ae…` | ninguno | sweep P07 Pydantic model-owned; P04/P08 provider; las tres cadenas P04 provider | 9 | `142,256 / 39,893 / 35,493` | USD `0.05209825` / `0.1843634` | sin decisión | `LUNA_MAX_QUALIFICATION_FAILED` |

Las tres configuraciones tuvieron fallback, retries, P10 y P11 en cero. Los
contadores de tokens HIGH no existen en su reporte fuente y no se
reconstruyeron. La comparación describe una sola matriz por configuración: no
afirma significancia estadística ni superioridad general.

## 8. Evidencia y autoridad siguiente

Recibo de ejecución inmutable:
`reports/openai/stage2_max_qualification_62d73ae_20260812_final_01.json`,
SHA-256 `532ba5e19537c039f9746c177ae3ed17cf9fbc3d6fdb9bf34c5f07f32a6eda0e`.
El ledger conserva `FAILED`, ese mismo report hash y su código histórico
`MAX_QUALIFICATION_INCONCLUSIVE`; no se reescribió historia durable.

Reporte final consolidado:
`reports/openai/stage2_max_qualification_62d73ae_20260812_consolidated_final_01.json`,
SHA-256 `74fc1323da3925a9805b4c957bbd597b342909f4b77855fcce706db6afbb17fd`.

El PR permanece draft. La autorización está consumida. No corresponde retry,
segunda matriz, tuning, cambio de validator/threshold/fixture, otra
configuración Luna, Terra, Sol, build ni deploy. Sólo queda permitida una
revisión humana de esta evidencia y cualquier acción posterior exige autoridad
explícita nueva.

`LUNA_MAX_QUALIFICATION_FAILED`
`LUNA_FAMILY_QUALIFICATION_EXHAUSTED`
`CONVERGENCE_INCOMPLETE`
