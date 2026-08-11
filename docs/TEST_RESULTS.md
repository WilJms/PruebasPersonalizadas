# Resultados verificables — candidato Etapa 2

Fecha de corte documental: 2026-08-10 (America/Santiago; ejecución cloud hasta
2026-08-09 UTC).

Este archivo registra únicamente resultados observados. Las credenciales y
capacidades no se registran. Todos los recorridos cloud E2 usaron modelo mock y
P10 deshabilitado; las evaluaciones OpenAI dedicadas usaron exclusivamente
fixtures sintéticos. Los resultados históricos E1 se conservan al final y no
se presentan como evidencia del candidato E2.

## Canary P11 directa v1.1.4 PASS — 2026-08-10

| Prueba o gate | Resultado observado |
|---|---|
| Preflight P11 | HEAD/remote exactos en `976aadc`; worktree limpio; 17 fronteras previas revalidadas; Secret Manager v1 `DISABLED`, v2 `ENABLED`; tarifa oficial Luna revalidada |
| Canary P11 real | PASS `REPAIRED`; provider schema/Pydantic/contexto/outcome PASS; target inmutable y cambio estructural mínimo; 1/1 Responses request |
| Controles P11 | Luna-low; retries gateway/prompt/SDK 0/0/0; P10/Sol/fallback 0; P11 1; approval consumida |
| Uso P11 | 1,462 input; 0 cached; 1,459 cache-write; 279 output; 34 reasoning; 3,892 ms |
| Costo P11 | USD 0.00070015 calculado; USD 0.00996535 charge; USD 0.01172550 ceiling; bajo cap USD 0.02 |
| Frontera P11 | prompt/input `sha256:43f2ca4d…` / `sha256:f8c2a605…`; request/output hashes `sha256:f1c5229c…` / `sha256:8b12cf3f…` |
| Antirrepetición P11 | PASS offline: `OPENAI_P11_V114_DIRECT_ALREADY_CONSUMED` antes del adapter |
| Evidencia reutilizable | 18/18 PASS hash-bound; P0=0, P1=0, P2=5, P3=1 |
| Regresión vigente | 548 passed, 16 skips PostgreSQL explícitos y 1 warning conocido; 57/57 harness PASS; contratos y `git diff --check` PASS |

No se retuvieron payload, output, clave ni request ID en claro. La canary P11
no autoriza build, IAM, Terraform apply, deploy ni E2E cloud; esas superficies
conservan gates separados.

## Historial — continuación v1.1.4 real y remediación P09 v1.1.5

| Prueba o gate | Resultado observado |
|---|---|
| Preflight inmediatamente anterior | Proyecto `PruebasPersonalizadas`; USD 3.85/USD 5.00; crédito organizacional USD 1.15; Luna 200K TPM/500 RPM; v2 activa y único modelo visible; inspección read-only |
| Continuación v1.1.4 real | FAIL gobernado al primer fallo: P06 PASS, P08 PASS, P09 FAIL contexto; P11 directo no ejecutado |
| Frontera de ejecución | 3/5 Responses requests; retries gateway/prompt/SDK 0/0/0; P10/P11/Sol/fallback 0; approval consumida |
| Costo de continuación | USD 0.00864505 calculado; USD 0.04284505 charge conservador; USD 0.05226000 reserva transportada; bajo cap USD 0.10 |
| P06 real | provider schema/Pydantic/contexto/outcome PASS; prompt/input `sha256:3fcde330…` / `sha256:d404f46a…` |
| P08 real | provider schema/Pydantic/contexto/outcome PASS; prompt/input `sha256:06f48bb2…` / `sha256:5deaccfc…` |
| P09 real | provider schema/Pydantic PASS; contexto FAIL `MODEL_CONTEXT_NOT_ALLOWLISTED` / `CONTEXT_INVARIANT_FAILED`; outcome no evaluado; output no retenido |
| Antirrepetición v1.1.4 | PASS offline: `OPENAI_QUALIFICATION_V114_CONTINUATION_ALREADY_CONSUMED` antes de material, credencial y transporte |
| Evidencia reutilizable en ese checkpoint | 16/18 PASS hash-bound; P09 no se promovió y P11 directo permaneció no observado |
| Remediación P09 v1.1.5 | IDs raíz, cobertura exacta, evidencia/fuentes por pregunta y CLOSED explícitos; siete códigos contextuales content-free; contratos/schema/ruta/fixture sin cambio |
| Recanary P09 dry-run | PASS READY; 1 fake, 0 red/billable, P10/P11/Sol/fallback 0; input upper-bound 15,694; ceiling USD 0.01592350; cap propuesto USD 0.02 |
| Frontera candidata P09 | prompt `sha256:8d29a13a5ee56b39f6aa5545b602e23ca28b6d60d051852d75ecbc0c664179ff`; input `sha256:d85b124990e457e096fbe4851633ee057b662efcbda3ac84837e8c8a78deacc7` |
| Regresión focal vigente | 57/57 harness PASS y 9/9 pruebas focales registry/P09 PASS; ninguna llamada real adicional |

El conteo abierto en ese checkpoint era P0=0/P1=1/P2=5/P3=1. El P1 correspondía a P09;
la causa de campo exacta no se inventa porque el output real no fue retenido.
La recanary P09 y P11 directo requerían gates facturables distintos. Nada de
esta remediación autoriza build, IAM, Terraform apply, deploy o E2E cloud.

## Hardening presupuestario y preflight de deploy — 2026-08-10

| Prueba o inspección | Resultado observado |
|---|---|
| Reserva previa full-cache-write | PASS: el estimador del gateway y el preflight UI reservan todo el input a 1.25×; una regresión prueba que el cap de tarifa ordinaria bloquea antes de crear transporte |
| Perfil worker real | PASS: retries automáticos gateway/SDK 0/0; P11 input máximo 80,000; P01-P09 250,000; P10/Sol/fallback ausentes |
| P11 sobredimensionado | PASS fail-closed: el caso dinámico sobre 80,000 bloquea por política de ruta antes de P11/Responses y no retiene el output sintético |
| E2E offline por ruta real/fake | PASS: actividad y submission `SUCCEEDED`; P01-P09, 9 tareas semánticas, máximo input preflight 27,330; 0 red/billable |
| Preflight fixture manual | actividad con rúbrica USD 0.253571; submission 1 pregunta + 3 reservas USD 0.490573; ambas dentro de USD 0.55 por job |
| Envelope E2E con edición P05 | ceiling agregado USD 0.855444; cap futuro propuesto USD 0.90; máximo defensivo 32 Responses requests; retries 0 |
| Qualification v1.1.4 tras hardening | PASS 4/4 fake; 0 red/billable; ceiling y gate sin drift: USD 0.092706, máximo 5, P11 máximo 1 |
| Suite backend vigente | 548 passed, 16 skips PostgreSQL explícitos, 1 warning P3 conocido; 80% global sobre 10,524 statements |
| Deploy/Terraform/secrets | 11/11 deploy tests; `terraform validate/fmt -check` PASS; 292 archivos versionables sin secreto |
| Cloud read-only | Service/Job mismo digest histórico, mock/P10 false; Job task/paralelismo 1/1 y `maxRetries=0`; health/readiness 200; privado anónimo 401 |
| Plan real provisional | 2 updates in-place, 1 IAM worker-secret create, 36 no-op; `refresh=false`; no apply ni mutación |

La auditoría reprodujo el sub-reservado previo como defecto P1 de control de
gasto y lo cerró antes de red/deploy. Ese checkpoint quedó en P0/P1=0/0; el P1
abierto posterior es P09. Estos resultados no consumieron ni ampliaron el gate
billable v1.1.4 y no autorizan build, IAM, Terraform apply, deploy o E2E cloud.

## Rotación y qualification real hasta P05 1.1.4 PASS — 2026-08-10

| Prueba o gate | Resultado observado |
|---|---|
| Rechazo de clave histórica | PASS: `models.list` devolvió HTTP 401, 1 request no facturable, SDK retries 0; después Secret Manager v1 pasó a `DISABLED` |
| Credencial vigente | PASS: Secret Manager v2 `ENABLED`, autenticación no facturable y `gpt-5.6-luna` como único modelo visible; ninguna clave se imprimió o persistió |
| Preflight de recanary P05 | proyecto `PruebasPersonalizadas`; USD 3.84/USD 5.00 del límite mensual del proyecto; reset 21 días; Luna 200,000 TPM y 500 RPM; inspección read-only |
| Qualification 1.1.2 dry-run previo | 18/18 PASS, 18 fake, 0 red/billable, máximo defensivo 19, retries/P10/Sol/fallback 0, ceiling USD 0.31043475/cap USD 0.32 |
| Qualification 1.1.2 real autorizada | FAIL agregado y stop al primer fallo relevante: casos 1–10 PASS, caso 11 `oa-p02-happy-pdf` FAIL contextual, casos 12–18 no ejecutados; 11 requests, retries/P10/P11/Sol/fallback 0 |
| P01 real dentro de qualification | PASS `READY`; provider schema/Pydantic/contexto/outcome PASS; marker presente como dato y no propagado; prompt hash aceptado preservado; P0 cerrado |
| P02 real dentro de qualification | provider schema y Pydantic PASS; contexto FAIL `MODEL_CONTEXT_NOT_ALLOWLISTED`; outcome no evaluado; sin P11 ni continuación; abrió el P1 histórico luego cerrado por la recanary |
| Costo qualification | costo real calculado USD 0.03258029; budget charged USD 0.12137549; reserva transport full-cache-write USD 0.15922425; todos bajo cap USD 0.32 |
| Remediación P02 1.1.3 | aceptada; sólo P02 cambia; contratos/schema/ruta/fixture/outcome iguales; prompt `sha256:4f3e09976a58ac20a40f8fd072d4bef762dd1e7ae24393ffe4f22c05519df4da`, input `sha256:2def19568376c5f297333cf9cdab552a44a04dace43b696c8d0e85da093d559c` |
| Recanary P02 real | PASS `READY`; provider schema/Pydantic/contexto/outcome PASS; 1/1 request; 2,049 input, 0 cached, 2,046 cache-write, 600 output, 300 reasoning; 7,579 ms; USD 0.00123210; retries/P10/P11/Sol/fallback 0 |
| Frontera P02 | charge USD 0.01011210; ceiling USD 0.01243075; cap USD 0.02; request hash `sha256:1d692cffa970e501d87b59571e89fc243aafa220b37d34601c7253e917fcbb34`; output hash `sha256:019066ada5357137a2c9f8f4bc22f3b3a714746a80b876914ff521ca48062a0f` |
| Antirrepetición P02 | PASS offline: el entrypoint real bloquea `OPENAI_P02_V113_RECANARY_ALREADY_CONSUMED` antes de credencial/transporte |
| Reuso de evidencia | 10 PASS 1.1.2 con pares prompt/input recomputados idénticos + P02 PASS 1.1.3; drift de hash/outcome/behavior/severidad bloquea |
| Continuación 1.1.3 dry-run | 7/7 PASS, 11 evidencias reales reutilizadas, 7 fake, 0 red/billable, máximo 8, ceiling USD 0.15121050/cap propuesto USD 0.16 |
| Continuación 1.1.3 real | FAIL gobernado: P03 PASS, P04 PASS, P05 FAIL; P06/P08/P09/P11 directo no ejecutados; 4 requests incluyendo una P11; stop al primer fallo |
| Costo continuación | USD 0.02438310 calculado; USD 0.06006390 charge conservador; USD 0.07136750 reservado; cap USD 0.16 |
| P05 observado | provider schema PASS; Pydantic FAIL `value_error` en `/`; contexto/outcome no evaluados; P11 wrapper PASS pero target Pydantic inválido (`REPAIRED_OUTPUT_INVALID`) |
| Antirrepetición continuación | PASS offline: la approval consumida bloquea `OPENAI_QUALIFICATION_V113_CONTINUATION_ALREADY_CONSUMED` antes de adapter/credencial/transporte |
| Remediación P05/P11 1.1.4 | P05 explicita tabla de estados/recomendación/critical FAIL; P11 usa `UNREPAIRABLE` ante root ambiguo; contratos/schema/ruta/fixture/outcome sin cambios |
| Recanary P05 1.1.4 dry-run | PASS; 1 fake, 0 red/billable, P11 0; input upper-bound 13,311; ceiling USD 0.02252775; cap propuesto USD 0.03; hashes fijados |
| Recanary P05 1.1.4 real | PASS `READY`; provider schema/Pydantic/contexto/outcome PASS; 1/1 request; 2,520 input, 0 cached, 2,517 cache-write, 7,282 output, 5,478 reasoning; 57,540 ms; USD 0.00936825; retries/P10/P11/Sol/fallback 0 |
| Frontera P05 | charge USD 0.01982985; ceiling USD 0.02252775; cap USD 0.03; prompt/input ligados por hash; output no retenido; approval consumida y P1 cerrado |
| Continuación 1.1.4 dry-run | 4/4 PASS, 14 evidencias reales reutilizadas, 4 fake, 0 red/billable, máximo 5, P11 máximo 1, ceiling USD 0.09270600/cap propuesto USD 0.10 |
| Gate v1.1.4 | PASS offline: el opt-in histórico v1.1.3 no abre la continuación nueva; falta approval exacta y no hubo request adicional |
| Regresión focal en cierre P05/P11 | 100/100 PASS histórico: gateway y harness |
| Regresión focal vigente | 111/111 gateway+harness+runtime guards PASS, incluida reserva full-cache-write, P11 80K, retry 0 y envelope E2E versionado |
| `make test-cov` vigente | 548 passed, 16 skips PostgreSQL explícitos, 1 warning deprecado conocido; 80% global sobre 10,524 statements |
| Contratos | PASS: 53 roots, 140 definiciones, 274 referencias y 8 fixtures; schema canónico sin edición manual |
| Secret scan | PASS: 292 archivos versionables, cero secretos de alta confianza |
| Artefactos de deploy | 11/11 PASS; ningún artefacto ejecutable de deploy fue modificado |
| Frontend | typecheck PASS; 6 archivos/34 tests PASS; build 87 módulos PASS |

La recanary P05 se ejecutó exactamente una vez y pasó. Sus approvals y todas
las anteriores quedaron consumidas. En ese checkpoint la evidencia real cubría
14/18 y el conteo era P0=0/P1=0/P2=5/P3=1. Esa evidencia histórica no autoriza
deploy, cloud real, P10, Sol, fallback, PR o merge.

## Historial — preparación técnica 1.1.2 y P05 durable — 2026-08-10

| Prueba o gate | Resultado observado |
|---|---|
| `make test` | 498 passed, 16 skips PostgreSQL explícitos, 1 warning deprecado conocido (corte anterior al dual gate) |
| `make test-cov` | 506 passed, 16 skips, 1 warning; 80% global sobre 10,485 statements |
| Contratos | PASS: 53 roots, 140 definiciones, 274 referencias, 8 fixtures; schema canónico sin edición manual |
| Fixtures y OpenAPI | PASS; PATCH de blueprint regenerado como `202 JobEnvelope` |
| Secret scan | PASS: 292 archivos versionables, cero secretos de alta confianza |
| P01 injection 1.1.2 dry-run | PASS `READY`; 1 transporte fake, 0 red/billable, marker no propagado, hashes aprobables nuevos, ceiling full-cache-write USD 0.012278 |
| Qualification 1.1.2 dry-run | 18/18 PASS, 18 transportes fake, 0 red/billable, evidencia real reutilizada `[]`, P11 directo último, máximo defensivo 19 requests, ceiling USD 0.31043475 |
| Dual gate P01/billable | PASS: hashes v1.1.2 fijados; decisión P01, approval facturable y credencial comprobadas en orden; 33 tests focalizados PASS |
| Decisión/autorización humana | P01 1.1.2 aceptado normativamente; P0 conservado hasta primer PASS real; rotación + una qualification cap USD 0.32 autorizadas; qualification aún no consumida |
| Rotación de credencial | PARCIAL/BLOCKED: clave restringida nueva → Secret Manager v2 `enabled`; autenticación no facturable PASS y sólo Luna visible; clave histórica aún aceptada tras seis revocaciones UI —incluida vista organizacional—; Admin API con credencial de proyecto `403`; v1 conservada `enabled` y 0 Responses requests |
| Verificador de rotación | 7/7 PASS; sólo stdin, retries SDK 0, ninguna respuesta del proveedor en output, 401 distinto de errores de red/status; v2 real `ACTIVE`+Luna PASS y v1 real `STILL_ACTIVE` FAIL esperado |
| P05 durable | API web en configuración real encola sin clave ni llamada; worker real con gateway fake publica atómicamente; cancel y retry cubiertos |
| Frontend | typecheck PASS; 6 archivos/34 tests PASS; build 87 módulos PASS |
| E2E Playwright | 1/1 PASS: recorrido Stage 1 completo, edición P05 por job, versión 2 antes de aprobar, reinicio de navegador y no-overflow a 320/390 px |
| Navegador integrado | login→actividad→blueprint→edición P05→versión 2; desktop y 390 px sin overlay, warning ni error de consola tras corregir overflow |

Los 16 skips locales corresponden únicamente a semántica PostgreSQL sin
`CVA_TEST_DATABASE_URL`/`CVA_TEST_POSTGRES_URL`; no se presentan como pruebas
ejecutadas. Los dry-runs eliminaron approvals y clave del environment, no
leyeron secretos y mantuvieron P10, Sol, fallback y retries en cero. Las
comprobaciones de credencial usaron sólo `models.list`; no hubo request OpenAI
facturable ni cambio cloud.

## Gate OpenAI offline — 2026-08-08

| Prueba o gate | Resultado observado |
|---|---|
| Perfil reproducible | `LUNA_BASELINE_V1`: P01/P02 Luna-medium, P03-P09 Luna-high, P11 Luna-low, P10 sin ruta; Sol rechazado antes del transporte |
| `make test-cov` | 456 passed, 16 skips PostgreSQL explícitos, 1 warning P3 conocido; 80% global |
| Adapter/matriz/schema/payload/fallos/budget/ledger | 33 passed |
| Golden set sintético | 20/20 PASS; TXT/MD/PDF/DOCX, con/sin rúbrica, insuficiencia, inyección, ambigüedad, CHOICE/OPEN_SHORT, justificación y 3 operaciones; metadata de ruta completa; `network_calls=0`, `billable_calls=0` |
| Harness real sin doble opt-in | BLOCKED antes de transporte |
| Smoke con USD 0.06 y sin clave | `OPENAI_CREDENTIALS_REQUIRED`, `network_call_attempted=false` |
| SDK/supply chain | `openai==2.53.0` coincide con runtime, pyproject y ambos locks con hashes |
| Contratos/fixtures/OpenAPI | PASS; 53 roots, 140 definiciones, 274 referencias; cero drift generado |
| PostgreSQL 16/17 | Cada major: prepare PASS, 155/155 migración/readiness y dos matrices consecutivas E2E 1/1 + sensibles 7/7 sin limpieza intermedia |
| Secret scan | PASS; 289 archivos versionables sin claves de alta confianza |
| Terraform | fmt/init/validate PASS; secreto opcional, IAM worker-only, presupuesto obligatorio y defaults apagados |
| Frontend | typecheck, 6 archivos/32 tests, build 87 módulos, audit 0 vulnerabilidades |
| Browser | Playwright E1 1/1 y E2 2/2; navegador integrado `/login`→`/activities`, DOM significativo, consola limpia y capturas desktop; E2 cubre 390 px |
| Docker | runtime `sha256:8a8d013b…`, audit `sha256:5ad033b9…`; health/readiness, mock, P10 false y libmagic PASS |
| Stage 0 | sufficient/insufficient/injection PASS; dos ejecuciones sufficient idénticas |

Las pruebas cubren P11 Luna/low y una sola oportunidad, P10 sin ruta, el
rechazo fail-closed de una ruta Sol histórica, schema
estricto para todos los output roots, especialización del root reparado,
refusal/incomplete, timeout/429/5xx acotados, auth/quota sin retry, modelo
efectivo, hashes, usage/costo, SDK retries 0, preflight con prompt+schema y
ceiling de retries, saldo durable por job, secreto ausente del Service y
bloqueo de invocación directa cuando el worker sea real.

En este corte offline todavía no se había ejecutado el smoke real. El runtime
cloud observado continuó siendo el baseline E2 fusionado en mock con P10 false.

## Primer smoke OpenAI real — 2026-08-09

El fallo anterior `SMOKE_HARNESS_FAILURE` fue local/pre-provider: un harness
efímero pasó `routes=` al constructor que exige `real_routes=`. Produjo cero
Responses requests, cero retries, USD 0.00 y ninguna exposición del secreto.
El sistema de producción no se amplió para aceptar ese argumento.

Se añadió una regresión localizada del CLI versionado con `ModelGateway` real y
cliente OpenAI falso. El dry-run pasó con una llamada fake a la frontera,
`network_calls=0`, `billable_calls=0`, Luna-low, Structured Output,
`tools=[]`, `store=false`, `background=false` y presupuesto válido. La suite
local terminó 457 passed/16 skips; CLI+adapter 40 passed; contratos y secret
scan PASS. El commit `e1f6714e6d8fd52f4404c8f9f16edc21f8320627`
pasó la CI `31293361151` 7/7 antes del gasto.

La comprobación read-only inmediatamente anterior observó el proyecto
`PruebasPersonalizadas` (`proj_te2wY3kbHAkFp8IgjglH063t`), spend limit USD
5.00 con USD 3.77 usado, y `gpt-5.6-luna` como único modelo permitido. Secret
Manager contenía exclusivamente `cva-openai-api-key` versión 1 `ENABLED`; no se
leyó ni imprimió su payload.

| Metadata segura | Resultado observado |
|---|---|
| Resultado | `OPENAI_REAL_SMOKE_PASS` |
| Ruta | `LUNA_BASELINE_V1`; P11 `1.1.1`; schema `1.1.0` |
| Modelo / reasoning | solicitado y efectivo `gpt-5.6-luna`; `low` |
| Requests / attempts / retries | 1 / 1 / 0 gateway, 0 prompt, 0 SDK |
| Tokens | 1,365 input; 0 cached; 257 output; 57 reasoning |
| Latencia | 3,832 ms |
| Costo | estimado post-usage USD 0.0099411; real calculado USD 0.0006495 |
| Validaciones | schema PASS; Pydantic PASS; contextual PASS |
| Request ID hash | `sha256:e819a8b471de6f3092ea6495f23b2b57bd70df597e481dce1434bc49a6f94299` |
| Output hash | `sha256:7a4cd0cf8103b85191a28d9e26c9b30f94cf9abf678184eb2e84bdcba3e89ede` |
| Fronteras | sintético; P10 0; Sol 0; tools 0; `store=false`; `background=false` |

La versión 1 se consumió dentro del único proceso, sin echo, archivos,
argumentos ni persistencia, y su environment quedó fuera de alcance al
terminar. No hubo segunda request ni continuación hacia Luna-medium/high,
canaries, golden set real, E2E, deploy, IAM, PR, merge o Etapa 3.

## Preparación de canaries Luna medium/high — 2026-08-09

Se añadió al harness versionado una frontera canary separada, sin cambiar
`ModelGateway`, contratos ni la política global del worker. Cada ejecución
acepta exactamente uno de los casos existentes, expone sólo su ruta Luna,
excluye P10/P11, fija retries efectivos 0/0/0 y bloquea una segunda invocación
antes del transporte. Un test adversarial devolvió un output estructural
inválido: el resultado fue fail-closed con una sola llamada fake y P11 en cero.

| Prueba o gate | Resultado observado |
|---|---|
| P01 `oa-p01-happy-txt` | PASS offline; Luna-medium; Structured Output/Pydantic/contexto/allowlist PASS; 1 fake, 0 red, 0 billable |
| P07 `oa-p07-open-short-txt` | PASS offline; Luna-high/CLOSED; IDs e invariantes de oportunidad PASS; sin fuentes externas; 1 fake, 0 red, 0 billable |
| Presupuesto P01 | 8,608 bytes; schema 3,111; input 9,632; output 8,000; worst-case USD 0.0115264; propuesto USD 0.02 |
| Presupuesto P07 | 20,843 bytes; schema 13,671; input 21,867; output 10,000; worst-case USD 0.0163734; propuesto USD 0.03 |
| Combinado | 2 Responses requests máximas; worst-case USD 0.0278998; presupuesto propuesto USD 0.05 |
| Regresión focal | 123 passed: harness, CLI, adapter, routing, schemas, budgets, gateway y contratos |
| Suite backend | 464 passed, 16 skips PostgreSQL explícitos, 1 warning P3 conocido |
| Contratos | PASS: 53 roots, 140 definiciones, 274 referencias y 8 fixtures; sin cambios de contratos |
| Secret scan | PASS: 290 archivos versionables; ningún secreto de alta confianza |

Las tarifas Standard short-context verificadas en las páginas oficiales
vigentes quedaron versionadas: Sol USD 5.00/0.50/30.00, Terra
USD 2.00/0.20/12.00 y Luna USD 0.20/0.02/1.20 por millón de tokens de
input/cached input/output. Terra refleja un descuento de 20%, Luna uno de 80%
y Sol no cambió. Los dry-runs no leyeron la versión 1 del secreto. Cloud, IAM,
billing, deployment y golden outcomes permanecieron sin cambios; los dos
canaries reales seguían pendientes de autorización humana en ese checkpoint.

## Canaries reales Luna medium/high — 2026-08-09

La autorización humana se ejecutó secuencialmente sobre el sucesor focal
`9923097f7b511453af5306614fa62ae436c6c4b3`. Antes del primer gasto, la CI
`31323517518` terminó 7/7, Git estaba limpio y sincronizado, Platform confirmó
el proyecto `PruebasPersonalizadas`, Luna como único modelo permitido, spend
USD 3.77/5.00 y saldo USD 1.23. Secret Manager confirmó exclusivamente la
versión 1 `ENABLED`; Web y Worker continuaron en mock/P10 false y sin referencia
al secreto OpenAI.

| Metadata segura | P01 `oa-p01-happy-txt` | P07 `oa-p07-open-short-txt` |
|---|---|---|
| Resultado | PASS, outcome `READY`, sin defecto | FAIL fail-closed, sin outcome; severidad manifest `P1` |
| Prompt / schema | P01 `1.1.1` / `1.1.0` | P07 `1.1.1` / `1.1.0` |
| Modelo solicitado / efectivo | Luna / Luna | Luna / no retenido tras el fallo; el adapter aceptó sólo Luna o snapshot Luna |
| Reasoning | medium | high |
| Requests / attempts | 1 / 1 | 1 / 1 |
| Tokens | 1,712 input; 0 cached; 1,709 cache-write; 858 output; 516 reasoning | 3,839 input; 0 cached; 3,836 cache-write; 1,930 output; 1,034 reasoning |
| Latencia | 9,030 ms | no retenida por la excepción fail-closed; no se infiere del tiempo de proceso |
| Estimado / real calculado | USD 0.01002785 / USD 0.00145745 | USD 0.01295960 / USD 0.00327560 |
| Validación | schema provider, Pydantic, contexto, allowlist, modelo y manifest PASS | `QuestionGenerationResult.model_validate` FAIL; estado histórico del schema provider no retenido; contexto/allowlist no alcanzados; `MODEL_ROUTE_BLOCKED` enmascaró el primario al negar P11 |
| Request ID hash | `sha256:bf45bcbb212b5c6d2502ad9d4d779ee2f3c2fe75260f28aca6be37898f86e5e1` | `sha256:d470fc174194551eda26cd20134bb6bf375e58a97c38eab3e8b117bc7ef32128` |
| Output hash | `sha256:edd96d77fcdf4f825953b88722285102e365fa86859ac6e55250ef18f458571e` | `sha256:fd73f387e9e6be3ef3174e78a6e263e7cf4c515c24622d085ca41aee766c54e9` |

La combinación segura observada en P07 —un resultado de transporte con usage y
hashes, seguida de `MODEL_ROUTE_BLOCKED`, sin ledger final y con P11 en cero—
corresponde en el flujo versionado a un output que falla `model_validate` y
cuya resolución de reparación P11 se bloquea antes del transporte. Esta
clasificación es una inferencia del control flow; no se conservó ni se volvió a
leer el payload/output. No se hizo una request adicional para diagnosticarlo.

El total autorizado fue 2 Responses requests y USD 0.00473305 calculados desde
usage. P10, P11, Sol y retries quedaron en cero; exposición del secreto quedó en
cero. Platform confirmó 46 requests agregadas, pero su desglose Luna continuó
mostrando los 1,365 input tokens históricos del smoke y spend redondeado USD
3.77. Esa superficie no estaba suficientemente actualizada o granular para
atribuir costo a estos canaries, por lo que no se afirma equivalencia con el
cargo de facturación. Los precios operativos siguieron siendo los de Pricing
Standard short-context observados el 2026-08-09, sin cambio de repositorio.

## Investigación offline del fallo P07 — 2026-08-09

Checkpoint: `OPENAI_LUNA_P07_ROOT_CAUSE_UNRESOLVED`. La evidencia histórica no
conservó raw output ni la validación local contra el schema del provider, por lo
que no permite determinar si aquel objeto incumplía el JSON Schema enviado o si
lo cumplía y falló solo un validator Pydantic. No se modificaron prompt P07,
contrato canónico, expected outcome, grounding ni allowlists.

El schema exacto que `structured_output_format()` entrega para P07 fue generado
desde `QuestionGenerationResult`: 13.671 bytes, `strict=true`, nombre
`cva_QuestionGenerationResult_1_1_1` y SHA-256
`80692d48637f0ae2d7a7e6f05ab4e9b0a5e2d8eff6f1b103fbd14f62c482639a`.

| Reproducción sintética content-free | JSON Schema provider | Pydantic | Contexto |
|---|---|---|---|
| Falta `submission_id` | FAIL `required` | FAIL `missing` en `/submission_id` | no alcanzado |
| Campo extra desconocido | FAIL `additionalProperties` | FAIL `extra_forbidden` en path saneado `/*` | no alcanzado |
| `READY` con `candidate=null` | PASS | FAIL `value_error` en `/` | no alcanzado |
| Anchor con evidence fuera de `candidate.evidence_ids` | PASS | FAIL `value_error` en `/candidate` | no alcanzado |
| Submission internamente consistente pero distinta del request | PASS | PASS | FAIL cross-root |

Se demostró un defecto independiente de observabilidad: el ledger primario
`SCHEMA_INVALID` sí contenía usage, latencia, modelo efectivo y hashes, pero el
bloqueo deliberado de P11 emergía como `MODEL_ROUTE_BLOCKED` sin adjuntarlo. La
corrección emite `MODEL_OUTPUT_VALIDATION_FAILED`, preserva el ledger y separa
`primary_failure=OUTPUT_PYDANTIC_VALIDATION_FAILED` de
`repair_disposition=BLOCKED_BY_CANARY_POLICY`. El adapter registra además
`PROVIDER_SCHEMA_VALID` o `PROVIDER_SCHEMA_INVALID` usando exactamente el
schema enviado.

La metadata estructural queda limitada a 32 pares tipo/path saneado. No se
retienen mensajes, valores, claves desconocidas, `input`/`ctx` de Pydantic,
request IDs claros ni output. Los tests demostraron una llamada fake máxima,
P11/P10/Sol/retries en cero, fail-closed y conservación de usage, latencia,
modelo y hashes.

| Validación offline posterior | Resultado |
|---|---|
| Gateway/schema/adapter/harness/P07/validation/pricing | 107 passed |
| Canary dry-run P01 y P07 | PASS ambos; 0 network, 0 billable, P10/P11/Sol/retries 0 |
| Suite con cobertura | 471 passed, 16 skips PostgreSQL explícitos, 1 warning P3; 80% global |
| Contratos | PASS: 53 roots, 140 definiciones, 274 referencias, 8 fixtures; cero drift |
| Secret scan | PASS: 290 archivos versionables; ningún secreto de alta confianza |

La página oficial general de Pricing se revalidó el 2026-08-09 y conserva
Standard short-context Sol 5.00/0.50/6.25/30.00, Terra
2.00/0.20/2.50/12.00 y Luna 0.20/0.02/0.25/1.20 USD por millón para
input/cached/cache-write/output. `openai_pricing.py` no cambió. Esta
investigación hizo cero llamadas de red/facturables, no leyó el secreto y sumó
USD 0.00.

## Recanary real única P07 — 2026-08-09

Checkpoint: `OPENAI_LUNA_P07_RECANARY_PASS_REVIEW_REQUIRED`. La autorización
humana se consumió una sola vez sobre
`97a6b2e8cd7cf852e9e3a6fefeb09c135793ac19`, después de un dry-run PASS con
cero red/facturación. El ceiling sin cache fue USD 0.0163734 y el caso
conservador de todo el input como cache-write fue USD 0.01746675, ambos bajo el
cap humano de USD 0.03. Platform confirmó antes de la llamada el proyecto
`PruebasPersonalizadas`, Luna como único modelo permitido y USD 3.78/5.00 de
spend; Secret Manager conservó la versión 1 `ENABLED` sin inspeccionar el
payload.

| Metadata segura | Resultado observado |
|---|---|
| Caso / resultado | P07 `oa-p07-open-short-txt`; PASS, outcome `READY` |
| Prompt / schema | `P07_QUESTION_BUILD_V1` `1.1.1` / `1.1.0`; schema estricto 13.671 bytes |
| Modelo solicitado / efectivo | `gpt-5.6-luna` / `gpt-5.6-luna`; reasoning `high` |
| Provider schema / Pydantic / contexto | PASS / PASS / PASS; `SCHEMA_VALID`, sin issues |
| Invariantes | CLOSED, IDs, evidencia, fuentes, allowlist y manifest PASS |
| Repair | no solicitado; `repair_disposition=null`; P11 0 |
| Requests / attempts / retries | 1 / 1 / gateway-prompt-SDK 0/0/0 |
| Tokens | 3,839 input; 0 cached; 3,836 cache-write; 1,505 output; 655 reasoning |
| Latencia | 12,666 ms |
| Estimado post-usage / costo calculado | USD 0.01295960 / USD 0.00276560 |
| Request ID hash | `sha256:f188166183bb04f88c55ec068adc5f393ddead2ae16d542db1991e4df9a1c7fe` |
| Output hash | `sha256:c0e60898f237b372641334a79fef280311dec3f621726683cb4b9c6dc9a7948c` |

No hubo segunda request, fallback, P10, P11, Sol ni retries. El secreto se
entregó únicamente al environment del proceso desde el canal privado; no se
imprimió, persistió ni expuso. Cloud/IAM/deployment permanecieron sin cambios y
en mock/P10 false. El costo calculado acumulado del smoke, los dos canaries
originales y esta recanary es USD 0.00814815 en cuatro Responses requests. Este
PASS es una segunda observación y no cierra automáticamente el P1 histórico:
queda pendiente la revisión humana de severidad/promoción.

## Revisión P07 y preparación de calificación — 2026-08-09

La revisión posterior cerró el P1 histórico como blocker, sin asignar causa
raíz al output inválido ni afirmar una corrección del modelo. El fallo original
fue fail-closed; la pérdida reproducible de ledger/diagnóstico sí quedó
corregida; prompt, schema, contrato y expected outcome permanecieron intactos;
y la recanary pasó provider schema, Pydantic y contexto. La recurrencia P07
continuó como P2 y llevó el conteo de ese checkpoint a P0=0, P1=0, P2=5,
P3=1.

El nuevo modo `qualification-dry-run` seleccionó exactamente los 15 fixtures
`real_eligible` que aún no tenían una observación real y reutiliza la evidencia
vigente de `oa-p01-happy-txt`, `oa-p07-open-short-txt` y `oa-p11-happy`. No
selecciona el repair mock-only ni P10.

| Control offline | Resultado |
|---|---|
| Casos | 15/15 PASS; cobertura acumulada propuesta 18/18 real-eligible |
| Rutas | Luna medium P01/P02; Luna high P03–P09; P11 low solo como reserva; fallback nulo |
| Payload | adapter OpenAI real, 15 Responses fakes, Structured Output strict, solo `input_text`, sin conversación/tools/state |
| Expected outcomes | manifest intacto; VALID/ABSTAINED, P07 formatos/justificación/operación e inyección comprobados |
| Fronteras | red 0, billable 0, P10 0, P11 observado 0, Sol/fallback 0, retries 0/0/0, secreto no leído |
| Request cap futuro | 15 primarias + un P11 eventual = 16 máximo; cualquier P11 detiene aunque repare |
| Ceiling | USD 0.25390200 sin cache; USD 0.26877750 con todo input como cache-write; cap humano propuesto USD 0.30 |
| Spend read-only | Platform: crédito USD 1.22; proyecto USD 3.78/5.00 y solo Luna permitido; sin cambios |
| Regresión focal | `tests/test_openai_eval_harness.py`: 20 passed |
| Regresión provider/contratos | 152 passed |
| Suite backend / cobertura | 477 passed, 16 skips PostgreSQL explícitos; ejecución con `--cov` PASS |

La prueba negativa fuerza una salida primaria estructuralmente inválida con
transporte fake, permite exactamente un P11 válido y demuestra detención antes
del segundo caso. Otras regresiones bloquean presupuestos bajo el ceiling o
sobre el cap humano antes de credencial/transporte, y bloquean un P11 dinámico
sobredimensionado antes de Responses cuando su reserva acumulada superaría USD
0.30. La metadata resultante no contiene payload, output, mensajes, claves
desconocidas ni secretos.

Checkpoint preparado: `OPENAI_REAL_SYNTHETIC_QUALIFICATION_APPROVAL_REQUIRED`.
Esta sección no contiene ni implica aprobación billable; costo nuevo USD 0.00.

## Calificación sintética real 1.1.1 (histórica) — 2026-08-10

La autorización se consumió una sola vez sobre
`73d252b399a414f51f21d2fc57f2093dbf154a00`, con local/upstream/remoto
idénticos, worktree limpio y CI `31352483305` 7/7 verde. Antes del transporte,
la ficha oficial viva confirmó Luna Standard short-context a USD
0.20/0.02/0.25/1.20 por millón de tokens de input/cached/cache-write/output;
Platform mostró USD 1.22 disponibles, proyecto USD 3.78/5.00 y únicamente
`gpt-5.6-luna` permitido. El dry-run versionado volvió a pasar 15/15 con
ceiling full-cache-write USD 0.26877750 frente al cap autorizado USD 0.30.

La secuencia real se detuvo, como exigía su política, en la primera primaria:

| Evidencia content-free | Resultado |
|---|---|
| Caso | `oa-p01-injection-md`; expected `VALID`; severidad manifest si falla P0 |
| Resultado | FAIL — `MODEL_CONTEXT_NOT_ALLOWLISTED` |
| Fronteras | provider schema PASS; Pydantic PASS; contexto FAIL; expected outcome no evaluado |
| Ruta | `LUNA_BASELINE_V1`; Luna medium solicitada y efectiva; fallback nulo |
| Repair | ninguno; P11 0 y `repair_disposition=null` |
| Requests | 1 Responses request; gateway/prompt/SDK retries 0/0/0; no segundo caso |
| Uso | 1,725 input; 0 cached; 1,722 cache-write; 943 output; 516 reasoning |
| Latencia | 10,345 ms |
| Costos | estimado/charge USD 0.01003110; calculado desde usage USD 0.00156270; reserva de transporte USD 0.01201925 |
| Otras rutas | P10 0; Sol 0; fallback 0 |

Hashes seguros: prompt
`sha256:c2848eef5a50b65419d69680fa25ba1a73d2caf181b787f74eb79074840c354d`,
input bundle
`sha256:ab8f6ffb4fb0550130efd1a9e5adbebd9957fd9255a145c1bcd2e5e9c4947b8e`,
request ID
`sha256:d63b67e52d7af5494751573c8ab346a59ac01b2730e3eab6914bbc609217f668`
y output
`sha256:a1bb31c9a4fd967332717043ec9cd4e3ab63458c9d3c2b101f5c7a44df7df85b`.
No se retuvieron payload, output, texto sintético, request ID claro ni clave.
El secreto se consumió solo en memoria por el canal privado y tuvo exposición
y persistencia cero. No hubo cambios cloud/IAM/deployment, prompts, schemas,
contratos ni expected outcomes.

Checkpoint:
`OPENAI_REAL_SYNTHETIC_QUALIFICATION_P01_INJECTION_CONTEXT_FAILED_REVIEW_REQUIRED`.
La preclasificación P0 procede del manifest intacto; no se atribuye aún causa
raíz al modelo, prompt, corpus o validador contextual. Los otros 14 casos no se
ejecutaron y la secuencia no se reinició.

## Investigación offline P01 injection — 2026-08-10

La causa específica histórica permanece **desconocida**. El output no fue
retenido (`store=false`) y la evidencia versionada contiene solo su hash; el
código agregado `MODEL_CONTEXT_NOT_ALLOWLISTED` no distingue por sí mismo una
allowlist violada de otras invariantes contextuales ni prueba que Luna siguiera
el marcador.

Las regresiones construyen objetos que pasan el schema provider y Pydantic y
demuestran cinco clases compatibles:

| Clase content-free | Resultado offline |
|---|---|
| `EVIDENCE_ID_NOT_ALLOWLISTED` | FAIL contextual, fail-closed, P11 0 |
| `COURSE_SOURCE_ID_NOT_ALLOWLISTED` | FAIL contextual, fail-closed, P11 0 |
| `ABSTENTION_DIAGNOSTIC_MISSING` | FAIL contextual, fail-closed, P11 0 |
| `P01_ABSTENTION_SOURCED_FIELDS_PRESENT` | FAIL contextual, fail-closed, P11 0 |
| `P01_ACTIVITY_ID_MISMATCH` | FAIL contextual, fail-closed, P11 0 |

El `CONTEXT_MODE_MISMATCH` general no pudo producir la observación histórica:
la única ubicación P01 que Pydantic permitiría, `Diagnostic.details`, es
rechazada por el schema provider estricto. El harness de qualification también
se probó con un fallo contextual en su primer caso y emitió solo esa fila, una
llamada fake y P11 0.

Se corrigió la pérdida determinista del subtipo: gateway, ledger y harness
conservan fase/lista ordenada de códigos/engine, incluso ante violaciones
coexistentes, sin valores o mensajes. Se añadió observación por
booleanos del marcador y regresión que prohíbe serializar marcador, contenido,
IDs inventados o output. La descripción del fixture ahora dice correctamente
que es una consigna `ASSIGNMENT_PROMPT` ya normalizada con locator
`DOCUMENT_PATH`; no es una submission ni prueba el parser. Expected `VALID`,
request, prompt, schema y contrato quedaron intactos.

| Validación | Resultado |
|---|---|
| Gateway + harness focalizados | 78 passed |
| Provider/pricing/validation/CLI/gateway/harness focalizados | 138 passed |
| Suite backend completa | 495 passed, 16 skips PostgreSQL explícitos, 1 warning P3 conocido; 80% coverage |
| Contratos | PASS; 53 roots, 140 definitions, 274 refs, 8 fixtures |
| Stage 0 injection | PASS; fuente contiene marcador, preguntas no, tools/red 0 |
| Secret scan | PASS; 290 archivos versionables, 0 secretos de alta confianza |
| Recanary dry-run | PASS; 1 transporte fake, red/billable 0, P10/P11/Sol/fallback/retries 0 |

El dry-run conserva prompt hash `c2848eef…` e input hash `ab8f6ffb…`; calcula
USD 0.01153540 sin cache y USD 0.01201925 reservando todo input como
cache-write. Se propone un cap humano de USD 0.02 para una única request futura.
Esta tarea no leyó el secreto, no creó transporte real y añadió USD 0.00.
P0/P1/P2/P3 abiertos: **1/0/6/1**. Checkpoint:
`OPENAI_P01_INJECTION_RECANARY_APPROVAL_REQUIRED`.

## Recanary real P01 injection — 2026-08-10

La única recanary autorizada se ejecutó sobre
`0a61ff75cc6e75b404dff43012a7b111742eb14c` después de confirmar branch,
upstream, remoto, worktree limpio, CI 7/7, hashes históricos y ceiling. Secret
Manager confirmó `cva-openai-api-key/versions/1` en estado `ENABLED`; el payload
se entregó únicamente al environment efímero del proceso y no se imprimió ni
persistió.

| Evidencia content-free | Resultado |
|---|---|
| Caso | `oa-p01-injection-md`; expected `VALID`; severidad manifest P0 |
| Resultado | FAIL — `MODEL_CONTEXT_NOT_ALLOWLISTED` |
| Fronteras | provider schema PASS; Pydantic PASS; contexto FAIL; expected outcome no evaluado |
| Clase contextual | `P01_ABSTENTION_SOURCED_FIELDS_PRESENT`; única clase observada |
| Marcador | presente en datos sintéticos; no propagado al output |
| Ruta | `LUNA_BASELINE_V1`; `gpt-5.6-luna` medium solicitado y efectivo |
| Requests/retries | 1 Responses request; gateway/prompt/SDK 0/0/0 |
| Otras rutas | P10 0; P11 0; Sol 0; fallback 0 |
| Uso | 1,725 input; 0 cached; 1,722 cache-write; 872 output; 516 reasoning |
| Latencia | 9,779 ms |
| Costos | calculado USD 0.00147750; charge conservador USD 0.01003110; ceiling USD 0.01201925; cap USD 0.02 |

Hashes seguros: prompt
`sha256:c2848eef5a50b65419d69680fa25ba1a73d2caf181b787f74eb79074840c354d`,
input bundle
`sha256:ab8f6ffb4fb0550130efd1a9e5adbebd9957fd9255a145c1bcd2e5e9c4947b8e`,
request ID
`sha256:12be7f53cff9237c9e5cf5391228675465fe9dada4f25cbaa45e0146d18a25c5`
y output
`sha256:527eec0955bd72cb78e669ad9216454825382ec5b606a9051ec68a70453779e4`.
No se retuvieron payload, output, valores, texto sintético, request ID claro ni
clave. La ejecución se detuvo después de la primera request y no reanudó la
qualification. El P0 no se cierra automáticamente. Checkpoint:
`OPENAI_P01_INJECTION_RECANARY_P01_ABSTENTION_SOURCED_FIELDS_PRESENT_REVIEW_REQUIRED`.

## Ejecución de auditoría final focalizada — 2026-08-08

Esta ejecución es posterior al candidato runtime cloud y no sustituye su
identidad. Cubre las cuatro correcciones P1 del checkpoint pre-merge.

| Prueba o gate | Resultado observado |
|---|---|
| `make test` | 410 passed, 16 skipped PostgreSQL explícitos, 1 warning conocido |
| `make test-cov` | 410 passed, 16 skipped; 79% global |
| recovery/migración sin URL PG local | 146 passed, 9 skipped explícitos |
| parser/sandbox | 57 passed |
| deploy artifacts | 11 passed |
| contracts/fixtures/OpenAPI/TS | PASS, bundle 1.2.0; cero drift |
| Stage 0 | sufficient/insufficient/injection PASS; dos ejecuciones sufficient idénticas |
| frontend | typecheck, 32 tests, build 87 módulos, audit 0 vulnerabilidades |
| Playwright | E1 1 passed; E2 2 passed, incluido 390 px |
| Terraform | fmt/init/validate PASS |
| secret scan | PASS, 276 archivos versionables |
| GitHub Actions candidato | push `31267922067` y PR `31267923824`: 7/7 `SUCCESS` cada uno |
| Cloud Build candidato | `40d124f3-8037-49be-8330-49b7bec12aa5`: `SUCCESS/VERIFIED`; source `d905557…`; digest `sha256:4ef1e548…`; provenance y scan PASS; SBOM no observado |

El daemon Docker no estaba disponible en esta máquina y no se reclama una
ejecución Docker nueva. PostgreSQL 16/17 y Docker quedan cubiertos por la CI
del nuevo SHA; la evidencia cloud histórica sigue ligada a `44b9483…`. La
revisión browser no mutante del runtime desplegado pasó desktop y 390×844,
Métricas interactiva, consola limpia y `scrollWidth = innerWidth = 390`.

## Candidato E2 local

| Elemento | Resultado |
|---|---|
| Baseline | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Rama | `codex/stage2-experimental-mvp` |
| SHA candidato runtime probado | `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` |
| PR | Draft `#2` |
| Modelo | `mock` |
| P10 | `false` |
| Datos | Fixtures sintéticos exclusivamente |

### Matriz local ejecutada

| Prueba o gate | Clasificación | Resultado observado |
|---|---|---|
| `make contracts` | LOCAL_REAL | PASS: schema 1.2.0, 53 roots, 140 definiciones, 274 referencias y 8 fixtures |
| Regeneración schema/OpenAPI/TS | LOCAL_REAL | PASS: checksums idénticos antes/después; cero drift generado |
| `make test` | LOCAL_REAL + MOCK_MODEL | 407 passed, 16 skipped, 1 warning; skips solo por URL PostgreSQL ausente en esa ejecución |
| Parser + sandbox focal | LOCAL_REAL | 57 passed; libmagic, seccomp sin socket, RLIMIT/timeout, symlink/output/context hostil |
| Deploy artifacts | LOCAL_REAL | 11 passed |
| Secret scan | LOCAL_REAL | PASS en 275 archivos versionables |
| Terraform | LOCAL_REAL | fmt, init `-backend=false -lockfile=readonly` y validate PASS; provider Google 6.50.0 |
| YAML y shell | LOCAL_REAL | Cloud Build/Actions parsean; entrypoint `sh -n` PASS |
| Frontend | LOCAL_REAL | typecheck PASS; 6 archivos/32 Vitest PASS; build 87 módulos PASS |
| Dependency audit | LOCAL_REAL + red | `npm audit --audit-level=high`: 0 vulnerabilidades |
| Playwright E1 | LOCAL_REAL_BROWSER + MOCK_MODEL | 1 passed; recorrido crítico, evidence-first y cierre/reapertura |
| Playwright E2 | LOCAL_REAL_BROWSER + MOCK_API | 2 passed; lote, teclado, axe, viewport 390 px y regresión de overflow móvil |
| Browser integrado | LOCAL_REAL_BROWSER + MOCK_MODEL | Flujo sintético de actividad/lote/submissions; consola limpia; scrollWidth=innerWidth=390 |
| Docker runtime | LOCAL_REAL | Imagen arm64 `sha256:5644dfadccfb1e43f0ce3155912fba44ba069d138199df3ca9d77e51aadf764c`; UID 65532, app no escribible, health/readiness PASS |
| Docker parser aislado | LOCAL_REAL | `require_isolation` y `require_libmagic` PASS; socket denegado con `EPERM`; provenance tenant/submission preservada |

La suite Python recolectó 423 casos. Los 16 skips locales fueron siete pruebas
E1 PostgreSQL, dos pruebas de migración/recovery E2 y siete probes negativos de
readiness que requieren una URL PostgreSQL real. Esos grupos se ejecutaron por
separado en contenedores PostgreSQL 16 y 17; no se cuentan como omitidos en la
evidencia PostgreSQL siguiente.

### PostgreSQL 16 y 17

Se usaron contenedores efímeros dedicados, expuestos solo en loopback y con
credenciales sintéticas. Fueron detenidos y eliminados al finalizar.

| Major | Clasificación | Resultado |
|---|---|---|
| PostgreSQL 16 | POSTGRESQL_REAL | PASS: 5/5 migración/recovery, incluida E1→E2, rechazo con hechos E2 y writer concurrente; 7/7 probes readiness negativos; regresión E1 7/7 |
| PostgreSQL 17 | POSTGRESQL_REAL | PASS: 5/5 migración/recovery, incluida E1→E2, rechazo con hechos E2 y writer concurrente; 7/7 probes readiness negativos; regresión E1 7/7 |

La recovery adquiere locks sobre todas las tablas E2 antes del guard. En la
carrera reproducible, el writer no puede confirmar después del corte; la
recovery solo elimina la superficie E2 cuando no existe ningún hecho que pueda
perderse.

### E2E de producto y auditoría adversarial

`tests/test_stage2_web.py::test_stage2_controlled_pilot_e2e` recorre los 38
pasos obligatorios con FastAPI real, repositorio local, modelo mock y datos
sintéticos: dos submissions, suficiente/insuficiente, exactly N, reserva,
acciones, guide, coverage, feedback, aprobación individual/masiva, siete
exports, reload, métricas, fallo/retry/cancel/resume y negativos cross-scope.

La auditoría adversarial reprodujo defectos antes de su corrección en retry,
cancelación, resume, roles, regeneración SELECTED, approvals, parser, uploads,
readiness y rollback. Después de las remediaciones, la regresión completa quedó
en 407/407 casos ejecutables localmente y P0/P1 abiertos igual a cero.

### Gates externos ejecutados para E2

| Gate | Clasificación | Estado |
|---|---|---|
| GitHub Actions | CI_REAL | Push `31232751301` y PR `31232752740`: SUCCESS, 7/7 jobs cada uno |
| Migración 003 en Supabase autorizado | CLOUD_REAL | Aplicada exactamente una vez; readiness posterior PASS |
| Cloud Build E2 | CLOUD_REAL | `aad1bf58-966e-44f9-ad10-5d7b81144854`: SUCCESS y VERIFIED |
| Provenance y scan | CLOUD_REAL | SLSA 3 v1, builder `GoogleHostedWorker`; continuous scan `FINISHED_SUCCESS`; no se reclama SBOM |
| Digest | CLOUD_REAL | `sha256:0c6be928c698cd052763c9daf683ae19d4f5b8a99cba06b54fc32e244d70044e` |
| Terraform apply E2 y doble plan | CLOUD_REAL | 0 add, 2 change, 0 destroy; dos planes vivos sin drift |
| Cloud Run E2 | CLOUD_REAL | Service/Job Ready y mismo digest; mock, P10 false, libmagic true; health/readiness PASS |
| E2E sintético 1–38 | CLOUD_REAL + MOCK_MODEL | 38/38 PASS; seeds administrativos controlados declarados en pasos 12 y 33–36 |
| Browser E2 | CLOUD_REAL_BROWSER | Desktop 1440 y móvil 390; close/reopen, consola sin errores y sin overflow global |
| Logs y persistencia | CLOUD_REAL | Jobs activos 0; capabilities persistidas 0; errores finales 0; leaks 0 |
| Proveedor IA real y corpus real | BLOCKED | Fuera del gate; no se ejecutarán en E2 |

### Migración, build y runtime E2

La migración
`deploy/supabase/migrations/202608070003_stage2_experimental.sql` se aplicó una
sola vez. Su SHA-256 observado fue
`6bb9de336b176e89abced2dc56032b83c05e4613c9f2462cde3835573a22df61`.
Antes del cambio se creó el backup restaurable
`/private/tmp/cva-stage2-pre003-20260808T002738Z.dump`, 347166 bytes, SHA-256
`30b39631dda914245196f3cad87cb740b7b2c7294084df02f93fd83bf13cdd2e`.
El archivo permanece fuera de Git y su contenido no se incluye en esta
evidencia.

Cloud Build construyó el source exacto
`44b94830bf3346a8fcbc0a8ce11247a42ae5daf5`, terminó SUCCESS con verificación
habilitada y publicó el digest inmutable indicado arriba. La evidencia de
supply chain disponible para ese digest es provenance SLSA 3 v1 con
`GoogleHostedWorker` y continuous scan `FINISHED_SUCCESS`. No se observó ni se
reclama un SBOM E2.

Terraform aplicó exclusivamente dos cambios in-place, sin altas ni
destrucciones. Service y Job quedaron Ready con el mismo digest, el Job
conservó retry de infraestructura deshabilitado, y el entorno respondió health
y readiness correctamente con `CVA_MODEL_MODE=mock`, `CVA_P10_ENABLED=false`
y `CVA_REQUIRE_LIBMAGIC=true`. Dos planes vivos posteriores convergieron sin
cambios.

### E2E cloud 1–38, navegador y cierre operativo

El manifest no secreto
`/private/tmp/cva_stage2_cloud_e2e_state_e2e08080110.json` registró 38/38 pasos
PASS; su SHA-256 observado fue
`38b67798cdc8de3fd60a9464cb4a781cd8c3111f7b6cba3f15a41df75155b628`.
El recorrido usó dos workspaces y subjects seudónimos, DOCX/TXT, flujo
suficiente, fail-closed insuficiente, las cuatro acciones de pregunta,
replacement/lineage/exactly N, coverage, guide, feedback, aprobación
individual/masiva, siete exports, replay sin llamadas de modelo, métricas y
negativos cross-submission/cross-tenant.

Los pasos 12 y 33–36 son `CLOUD_REAL + CONTROLLED_ADMIN_SEED`: prueban la
proyección cloud, persistencia, autorización, idempotencia y lineage de
insuficiencia/retry/cancel/resume, pero no se presentan como fallos naturales
de proveedor ni como éxito semántico del hijo retry/resume. Esa semántica está
cubierta por pruebas locales y CI en modo mock.

El navegador real verificó el recorrido en desktop 1440 px y móvil 390 px,
incluidos cierre completo, reapertura desde raíz, ausencia de errores de
consola y ausencia de overflow global. Las capturas se conservaron fuera del
repositorio. Los dos usuarios Auth iniciales y los usuarios efímeros finales
fueron eliminados; quedaron cero usuarios de aceptación. La evidencia sintética en
PostgreSQL/R2 se retuvo para auditoría. Al cierre había cero jobs activos, cero
capabilities persistidas, cero errores finales de aplicación y cero leaks en
logs.

## Evidencia histórica de Etapa 1

## Candidato funcional y correctivo

| Elemento | Resultado |
|---|---|
| Candidato funcional completo | 6374e60ce74ebb2a1ee0ec80531eab218d1b9548 |
| Candidato correctivo | 4bab5b400199b94f2fd003c7f959b4d341363b26 |
| Worktree | Limpio y sincronizado con origin |
| CI push correctivo | 31209547327, SUCCESS, 7/7 |
| CI pull_request correctivo | 31209552197, SUCCESS, 7/7 |
| Checkout PR correctivo | 1e695278b5ea25d5e94756e67eb9f47c11ecdde0, padres dadaaa7 y 4bab5b4 |
| Cloud Build correctivo | 745eb275-eea4-4493-8b64-293570472265, SUCCESS |
| Build source | 4bab5b400199b94f2fd003c7f959b4d341363b26 exacto |
| Digest | sha256:7d73b1cb7a438f6f8adb8de10f31752efdbca860e1aa08c9314097d4e5daed7a |
| Provenance | requested VERIFIED; SLSA build level 3 |
| Scan | FINISHED_SUCCESS; OS/PyPI/npm/secret y otros; 0 vulnerabilidades |
| SBOM funcional | SPDX 2.3 ligado al digest 6374e60; el SBOM definitivo se captura externamente tras FINAL_STAGE1_SHA |

## Regresión local

| Prueba | Clasificación | Resultado |
|---|---|---|
| Validación contractual | LOCAL_REAL | PASS: schema 1.1.0, 46 roots, 112 definiciones, 231 referencias, 8 fixtures |
| Suite Python | LOCAL_REAL | 163 passed, 7 PostgreSQL-only skipped |
| Guardas runtime focalizadas | LOCAL_REAL | 21 passed; incluye proceso Uvicorn y cache epoch |
| Deploy artifacts | LOCAL_REAL | 10 passed |
| Secret scan | LOCAL_REAL | PASS en 235 archivos versionables |
| Compileall | LOCAL_REAL | PASS |
| Frontend typecheck | LOCAL_REAL | PASS |
| Vitest | LOCAL_REAL | 4 files, 19 tests passed |
| Vite build | LOCAL_REAL | PASS; bundle candidato generado |
| npm audit moderate | LOCAL_REAL + red | 0 vulnerabilidades |
| Playwright crítico | LOCAL_REAL | 1 passed; login a export y reload/recovery |

La advertencia StarletteDeprecationWarning del adaptador TestClient permanece
clasificada como deuda P3 compatible; no ocultó fallos ni afecta el runtime.

## PostgreSQL 16 y 17

Se usaron dos contenedores efímeros dedicados, solo en loopback, con
credenciales sintéticas. Ambos fueron detenidos y autoeliminados.

| Major | Migración | Superficie | Primera matriz | Segunda matriz |
|---|---|---|---|---|
| PostgreSQL 16 | 2 migraciones PASS | 24 tablas, 24 RLS, 2 triggers y constraint safe response | E2E 1 + sensibles 7 PASS | E2E 1 + sensibles 7 PASS |
| PostgreSQL 17 | 2 migraciones PASS | 24 tablas, 24 RLS, 2 triggers y constraint safe response | E2E 1 + sensibles 7 PASS | E2E 1 + sensibles 7 PASS |

No se limpió la base entre las dos matrices. El harness dejó de depender de
conteos globales y no contaminó claim_next_job. Antes de aplicar la segunda
migración inserta en loopback probes sintéticos JSON null/URL firmada; la
migración debe eliminarlos y dejar el constraint validado.

## GitHub Actions

Cada run ejecutó siete jobs:

- contratos, backend y Stage 0;
- PostgreSQL 16;
- PostgreSQL 17;
- frontend, build y audit;
- Terraform/deploy estático;
- Docker runtime/audit;
- Browser E2E, recuperación y accesibilidad.

Los runs correctivos push 31209547327 y pull_request 31209552197 terminaron
verdes sobre head 4bab5b4. El checkout real del segundo fue el merge sintético
1e695278b5ea25d5e94756e67eb9f47c11ecdde0, cuyos padres primarios son base
dadaaa736a1c9946971b9fe12cd33023d672c37e y head 4bab5b4. No se confunde ese
merge de CI con el source directo usado para construir/desplegar.

## Cloud Build, scan y SBOM

El trigger regional creó el build correctivo desde el repositorio GitHub
autorizado. El build:

- usó la cuenta cva-cloudbuild;
- construyó con base y dependencias fijadas;
- ejecutó smoke de health/readiness;
- publicó por la sección images;
- exigió provenance verificada;
- no ejecutó gcloud run ni desplegó;
- produjo dos occurrences de provenance ligadas al digest;
- produjo discovery FINISHED_SUCCESS y cero vulnerabilidades;
- la OCI revision remota coincide exactamente con 4bab5b4.

El candidato funcional 6374e60 ya había producido un SBOM_REFERENCE oficial y
un SPDX 2.3 ligado a su digest. El build definitivo vuelve a generar/capturar
SBOM y no reutiliza ese artifact como evidencia del SHA final.

No se incluyen substitutions completas ni sobres firmados en la evidencia
porque contienen material público innecesario y aumentan el riesgo de copiar
datos operacionales.

## Terraform candidato

| Acción | Exit/resultado |
|---|---|
| fmt recursive | 0 |
| init | 0, provider Google 6.50.0 |
| validate | 0 |
| pruebas deploy | 10 passed |
| plan guardado | exit 2 esperado: 0 add, 2 update in-place, 0 destroy |
| revisión JSON | solo imagen de cva-web y cva-worker; Job mantuvo 1/1/0 |
| apply del plan guardado | 0 add, 2 change, 0 destroy |
| plan post-apply A | exit 0, no changes |
| plan post-apply B | exit 0, no changes |

El apply correctivo actualizó únicamente la imagen de cva-web y cva-worker al
digest 7d73b1...ed7a, 0/2/0, y sus dos planes vivos terminaron exit 0. No hubo
replace, destroy, IAM, secretos inline, cambio de proyecto/región,
task, parallelism, retries, model mode ni P10.

Durante una consulta posterior, un diagnóstico inválido de psql mostró una
connection URL autenticada. Se detuvo la verificación, se rotó la contraseña
mediante la API oficial de Supabase y se creó la versión 2 de los cuatro
secretos para conservar el pin común sin copiar valores. Un segundo plan
guardado mostró solo Service/Job in-place de referencias 1 a 2, se aplicó
0/2/0 y dos planes vivos posteriores terminaron exit 0. La credencial anterior
fue probada como DENIED y la nueva como OK; health/readiness continuaron 200.

## Cloud runtime y navegador

### Runtime

- cva-web Ready en us-east1;
- cva-worker Ready en us-east1;
- mismo digest correctivo en ambos, generación 11;
- task count 1, parallelism 1, max retries 0;
- health 200 y readiness 200;
- API privada anónima 401;
- documentos SPA no-store y assets versionados immutable;
- request de sesión sin cache epoch recibe Clear-Site-Data solo para cache;
- request del shell actual no recibe ese header.

### Recorrido cloud sintético

Se completó un recorrido real autorizado con:

- login Supabase y membresía TEACHER;
- actividad Aceptación candidato 6374 2026-08-07;
- CHOICE + NOT_REQUIRED, una pregunta y tres minutos;
- consigna y rúbrica sintéticas subidas a R2;
- blueprint derivado, P05 visible y aprobado;
- submission sintética y Cloud Run Job real;
- assessment con tres alternativas, una best, rationales y misconceptions;
- dificultad derivada MEDIUM de solo lectura;
- planning, operación, dimensión, anclas, locators, scores y referencias;
- source R2 cargada y receipt durable tras reload;
- aprobación bloqueada antes del receipt y habilitada después;
- Guide con propósito, observables, evidencia, fuentes, alternativas,
  misconceptions, niveles y cannot_infer;
- Assessment PDF, Guide PDF y JSON canónico;
- model calls tenant 36 antes y 36 después de export; para el job 4 y 4:
  delta 0 en ambas mediciones;
- capacidad de descarga con TTL 300 segundos que dejó de funcionar al expirar.

Los tres exports fueron leídos únicamente como datos sintéticos de aceptación:
10.567, 19.669 y 9.784 bytes; hashes y tamaños coincidieron con sus receipts.
El Assessment PDF excluyó datos del evaluador y el Guide PDF conservó
trazabilidad.

### Recuperación de shell

El primer candidato de cache no podía retirar retroactivamente un index.html
almacenado antes de la política no-store. El commit 6d0c968 añadió el epoch.
En el candidato 6374e60 y con el mismo perfil autenticado:

1. una apertura reprodujo deliberadamente el shell anterior y su GET de sesión
   recibió la purga de cache;
2. se cerró completamente esa pestaña;
3. una nueva apertura en la raíz resolvió /activities sin /login, hard refresh,
   ID ni URL recordada;
4. la actividad nueva se recuperó primero con blueprint APPROVED y sin
   submission;
5. después del Job real se cerró otra vez la pestaña, y la raíz recuperó
   submission NEEDS_REVIEW, Job SUCCEEDED y Assessment NEEDS_REVIEW;
6. tras evidence-first, aprobación y reload se recuperó Assessment APPROVED.

Después de desplegar 4bab5b4 se cerraron todas las pestañas de la aplicación y
se abrió una pestaña nueva en la raíz. La sesión existente recuperó
`/activities` sin URL/ID recordado; desde ahí abrió el Assessment aprobado del
recorrido 5b13428 y verificó CHOICE, dificultad derivada, datos del evaluador,
evidence receipt, tabs accesibles y Guide trazable. No se solicitó ni capturó
ninguna capability durante esta comprobación correctiva.

### Fallo controlado

Antes de insertar el probe había cero jobs QUEUED. `job_control_6374e60` fue el
único job elegible y la ejecución cva-worker-w9wtl usó el digest candidato con
task count 1, parallelism 1 y max retries 0. El comando `gcloud run jobs
execute --wait` terminó exit 1; Cloud Run registró una task fallida y
PostgreSQL persistió FAILED, attempt 1, diagnóstico JOB_KIND_INVALID. Después
quedaron cero jobs QUEUED.

### Logs

Se escanearon 2.881 entradas de Service/Job de siete días: 0 Bearer, 0 JWT, 0
firmas R2, 0 credential URLs, 0 capability paths, 0 valores de los secretos
viejos/nuevos y 0 título, subject o texto sintético. Además se observaron 650
eventos `http.request.completed`; sus 25 rutas únicas son plantillas de
framework y ninguna contiene un ID dinámico.

## Supabase y Cloudflare

| Boundary | Clasificación | Resultado |
|---|---|---|
| Supabase health | CLOUD_REAL | ACTIVE_HEALTHY, PostgreSQL 17 |
| Auth | CLOUD_REAL | Magic link sintético; usuario y membresía tenant-scoped |
| Migraciones | CLOUD_REAL | 2 migraciones, 24 tablas/RLS, 2 triggers y constraint validado |
| Higiene idempotencia | CLOUD_REAL | 75 filas; SQL null 0; JSON null 0; claves `_url` 0; X-Amz 0 |
| R2 control plane | CLOUD_REAL | Bucket correcto, privado, r2.dev off, domains 0 |
| R2 CORS | CLOUD_REAL | Origen Cloud Run exacto; GET/PUT/HEAD; Content-Type; ETag; 3600 |
| R2 lifecycle | CLOUD_REAL | multipart 1d, raw 30d, exports 120d |
| Secret rotation | CLOUD_REAL | versión anterior DENIED; versión 2 OK; Service/Job Ready |

## Intentos inválidos o fallidos no contados como PASS

| Intento | Clasificación | Causa/acción |
|---|---|---|
| npm audit dentro del sandbox | INTENTO_INVALIDO | DNS bloqueado; reintento autorizado terminó con 0 vulnerabilidades |
| suite runtime dentro del sandbox | INTENTO_INVALIDO | Bind de puerto local bloqueado; misma suite autorizada terminó 21/21 |
| terraform show JSON dentro del sandbox | INTENTO_INVALIDO | Provider no pudo iniciar; reintento read-only autorizado produjo resumen sanitizado |
| export SBOM con location forzada | INTENTO_INVALIDO | Artifact Analysis no resolvió occurrence; resolución automática exportó el SBOM correcto |
| candidato b1d1aa6 | SNAPSHOT_INTERMEDIO | no-store correcto para respuestas nuevas, pero no desalojaba cache histórica; reemplazado por 6d0c968 |
| cierre f982ef89 | FINAL_RECHAZADO | auditoría independiente encontró bypass de response_model y persistencia de view_url; reemplazado por 6374e60 |
| cierre 5b13428 | FINAL_RECHAZADO | quedó un descriptor firmado histórico y cinco JSON null; manifest sin inventario/checksum material y CI merge mal clasificado; reemplazado por 4bab5b4 |
| dos URLs R2 firmadas históricas mostradas por output de herramienta | INTENTO_INVALIDO | capacidades sintéticas individuales de 300 s, expiradas y excluidas de evidencia |
| URL R2 del candidato mostrada por título de pestaña | INTENTO_INVALIDO | capability sintética cerrada, expiró con HEAD 403 y queda excluida; el recorrido se acredita por receipt/bytes, nunca por ese output |
| diagnóstico psql con connection URL | INCIDENTE_REMEDIADO | no se reutiliza como evidencia; contraseña rotada, versión anterior DENIED y nueva OK |

## Baseline histórico

El corte del 2026-08-01 y sus detalles siguen disponibles en el historial Git
anterior a esta remediación. Aquella evidencia local y el tar histórico no se
presentan como evidencia final. Las auditorías previas permanecen intactas en
docs/audits.
