# Resultados verificables de remediación E0/E1

Fecha de corte documental: 2026-08-07 (America/Santiago).

Este archivo registra únicamente resultados observados. Las credenciales y
capacidades no se registran. Todos los recorridos usaron model mode mock y P10
deshabilitado. Los identificadores posteriores a FINAL_STAGE1_SHA se guardan
en el paquete de evidencia externo, no mediante un commit adicional.

## Candidato funcional

| Elemento | Resultado |
|---|---|
| SHA | 6374e60ce74ebb2a1ee0ec80531eab218d1b9548 |
| Worktree | Limpio y sincronizado con origin |
| CI push | 31199864090, SUCCESS |
| CI pull_request | 31199869015, SUCCESS |
| Cloud Build | b274ccc5-ef4d-42b1-b4fe-893d77d3b898, SUCCESS |
| Build source | SHA candidato exacto |
| Digest | sha256:94e6b4e786c95f0c746f48703fdd8a4f3641c9627a9fe6766e6ffc25a845967c |
| Provenance | requested VERIFIED; SLSA build level 3 |
| Scan | FINISHED_SUCCESS; OS/PyPI/npm/secret y otros; 0 vulnerabilidades |
| SBOM | SPDX 2.3; 146 paquetes; 290 relaciones; SHA-256 e4a26d8ff24f6595332460f6af59eb73eb78dcc131ef4150a3b99833608e97ae |

## Regresión local

| Prueba | Clasificación | Resultado |
|---|---|---|
| Validación contractual | LOCAL_REAL | PASS: schema 1.1.0, 46 roots, 112 definiciones, 231 referencias, 8 fixtures |
| Suite Python | LOCAL_REAL | 163 passed, 7 PostgreSQL-only skipped |
| Guardas runtime focalizadas | LOCAL_REAL | 21 passed; incluye proceso Uvicorn y cache epoch |
| Deploy artifacts | LOCAL_REAL | 9 passed |
| Secret scan | LOCAL_REAL | PASS en 234 archivos versionables |
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
| PostgreSQL 16 | PASS | 24 tablas, 24 RLS, 2 triggers append-only | E2E 1 + sensibles 7 PASS | E2E 1 + sensibles 7 PASS |
| PostgreSQL 17 | PASS | 24 tablas, 24 RLS, 2 triggers append-only | E2E 1 + sensibles 7 PASS | E2E 1 + sensibles 7 PASS |

No se limpió la base entre las dos matrices. El harness dejó de depender de
conteos globales y no contaminó claim_next_job.

## GitHub Actions

Cada run ejecutó siete jobs:

- contratos, backend y Stage 0;
- PostgreSQL 16;
- PostgreSQL 17;
- frontend, build y audit;
- Terraform/deploy estático;
- Docker runtime/audit;
- Browser E2E, recuperación y accesibilidad.

Los runs push 31199864090 y pull_request 31199869015 terminaron verdes y
reportaron el mismo head candidato. GitHub puede usar un merge ref sintético
para pull_request; la evidencia final distingue CI_MERGE_SHA de PR head.

## Cloud Build, scan y SBOM

El trigger regional creó el build candidato desde el repositorio GitHub
autorizado. El build:

- usó la cuenta cva-cloudbuild;
- construyó con base y dependencias fijadas;
- ejecutó smoke de health/readiness;
- publicó por la sección images;
- exigió provenance verificada;
- no ejecutó gcloud run ni desplegó;
- produjo dos occurrences de provenance ligadas al digest;
- produjo discovery FINISHED_SUCCESS y cero vulnerabilidades;
- produjo un SBOM_REFERENCE oficial ligado al digest y exportó el SPDX 2.3;
- la OCI revision remota coincide exactamente con 6374e60.

No se incluyen substitutions completas ni sobres firmados en la evidencia
porque contienen material público innecesario y aumentan el riesgo de copiar
datos operacionales.

## Terraform candidato

| Acción | Exit/resultado |
|---|---|
| fmt recursive | 0 |
| init | 0, provider Google 6.50.0 |
| validate | 0 |
| pruebas deploy | 9 passed |
| plan guardado | exit 2 esperado: 0 add, 2 update in-place, 0 destroy |
| revisión JSON | solo imagen de cva-web y cva-worker; Job mantuvo 1/1/0 |
| apply del plan guardado | 0 add, 2 change, 0 destroy |
| plan post-apply A | exit 0, no changes |
| plan post-apply B | exit 0, no changes |

No hubo replace, destroy, IAM, secretos inline, cambio de proyecto/región,
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
- mismo digest candidato en ambos;
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
| Migración | CLOUD_REAL | 24 tablas/RLS y 2 triggers append-only |
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
| dos URLs R2 firmadas históricas mostradas por output de herramienta | INTENTO_INVALIDO | capacidades sintéticas individuales de 300 s, expiradas y excluidas de evidencia |
| URL R2 del candidato mostrada por título de pestaña | INTENTO_INVALIDO | capability sintética cerrada, expiró con HEAD 403 y queda excluida; el recorrido se acredita por receipt/bytes, nunca por ese output |
| diagnóstico psql con connection URL | INCIDENTE_REMEDIADO | no se reutiliza como evidencia; contraseña rotada, versión anterior DENIED y nueva OK |

## Baseline histórico

El corte del 2026-08-01 y sus detalles siguen disponibles en el historial Git
anterior a esta remediación. Aquella evidencia local y el tar histórico no se
presentan como evidencia final. Las auditorías previas permanecen intactas en
docs/audits.
