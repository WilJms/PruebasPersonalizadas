# Resultados verificables — candidato Etapa 2

Fecha de corte documental: 2026-08-07 (America/Santiago).

Este archivo registra únicamente resultados observados. Las credenciales y
capacidades no se registran. Todos los recorridos E2 usaron modelo mock, P10
deshabilitado y datos sintéticos. Los resultados históricos E1 se conservan al
final y no se presentan como evidencia del candidato E2.

## Candidato E2 local

| Elemento | Resultado |
|---|---|
| Baseline | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Rama | `codex/stage2-experimental-mvp` |
| SHA candidato | Se completa después del commit; estas ejecuciones corresponden al worktree que lo precede |
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
| Secret scan | LOCAL_REAL | PASS en 270 archivos versionables |
| Terraform | LOCAL_REAL | fmt, init `-backend=false -lockfile=readonly` y validate PASS; provider Google 6.50.0 |
| YAML y shell | LOCAL_REAL | Cloud Build/Actions parsean; entrypoint `sh -n` PASS |
| Frontend | LOCAL_REAL | typecheck PASS; 6 archivos/32 Vitest PASS; build 87 módulos PASS |
| Dependency audit | LOCAL_REAL + red | `npm audit --audit-level=high`: 0 vulnerabilidades |
| Playwright E1 | LOCAL_REAL_BROWSER + MOCK_MODEL | 1 passed; recorrido crítico, evidence-first y cierre/reapertura |
| Playwright E2 | LOCAL_REAL_BROWSER + MOCK_API | 1 passed; lote, teclado, axe y viewport 390 px |
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

### Gates todavía no ejecutados para E2

| Gate | Clasificación | Estado |
|---|---|---|
| GitHub Actions del SHA final | NOT_VERIFIED | Pendiente de commit/push/PR |
| Migración 003 en Supabase autorizado | NOT_VERIFIED | Pendiente de backup/quiesce/aplicación |
| Cloud Build E2, scan, SBOM y digest | NOT_VERIFIED | Pendiente del SHA publicado |
| Terraform apply E2 y doble plan | NOT_VERIFIED | Pendiente del digest |
| Cloud Run E2 y E2E sintético 1–38 | NOT_VERIFIED | Pendiente del apply |
| Proveedor IA real y corpus real | BLOCKED | Fuera del gate; no se ejecutarán en E2 |

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
