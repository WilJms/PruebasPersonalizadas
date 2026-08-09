# Resultados verificables — candidato Etapa 2

Fecha de corte documental: 2026-08-07 (America/Santiago; ejecución cloud hasta
2026-08-09 UTC).

Este archivo registra únicamente resultados observados. Las credenciales y
capacidades no se registran. Todos los recorridos E2 usaron modelo mock, P10
deshabilitado y datos sintéticos. Los resultados históricos E1 se conservan al
final y no se presentan como evidencia del candidato E2.

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
