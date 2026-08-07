# Resultados verificables de remediación E0/E1

Fecha de corte documental: 2026-08-07 (America/Santiago).

Este archivo registra únicamente resultados observados. Las credenciales y
capacidades no se registran. Todos los recorridos usaron model mode mock y P10
deshabilitado. Los identificadores posteriores a FINAL_STAGE1_SHA se guardan
en el paquete de evidencia externo, no mediante un commit adicional.

## Candidato funcional

| Elemento | Resultado |
|---|---|
| SHA | 6d0c96837c552254d8f23a534975862e47d5a079 |
| Worktree | Limpio y sincronizado con origin |
| CI push | 31154598870, SUCCESS |
| CI pull_request | 31154601586, SUCCESS |
| Cloud Build | 4be4e25b-98f7-4d06-a3b9-59ea4f99625f, SUCCESS |
| Build source | SHA candidato exacto |
| Digest | sha256:4611f0812da2402b30e81bcfaa6aa5cb73a558c6f411db2ba259eaffe9f190d4 |
| Provenance | requested VERIFIED; SLSA build level 3 |
| Scan | FINISHED_SUCCESS; OS/PyPI/npm/secret y otros; 0 vulnerabilidades |
| SBOM | SPDX 2.3; 146 paquetes; 290 relaciones; SHA-256 f3a7aa44f2039e162a00d15dabfa344193c6ed3d064638a1b7155e016430c4f8 |

## Regresión local

| Prueba | Clasificación | Resultado |
|---|---|---|
| Validación contractual | LOCAL_REAL | PASS: schema 1.1.0, 46 roots, 112 definiciones, 231 referencias, 8 fixtures |
| Suite Python | LOCAL_REAL | 162 passed, 7 PostgreSQL-only skipped |
| Guardas runtime focalizadas | LOCAL_REAL | 21 passed; incluye proceso Uvicorn y cache epoch |
| Deploy artifacts | LOCAL_REAL | 9 passed |
| Secret scan | LOCAL_REAL | PASS en 231 archivos versionables |
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

Los runs push 31154598870 y pull_request 31154601586 terminaron verdes y
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
- exportó un SBOM oficial cuyo nombre incluye el digest exacto.

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
- actividad Aceptación final Etapa 1 2026-08-07;
- CHOICE + NOT_REQUIRED, una pregunta y tres minutos;
- consigna y rúbrica sintéticas subidas a R2;
- blueprint derivado, P05 visible y aprobado;
- submission sintética y Cloud Run Job real;
- assessment con tres alternativas, una best, rationales y misconceptions;
- dificultad derivada HIGH de solo lectura;
- planning, operación, dimensión, anclas, locators, scores y referencias;
- source R2 cargada y receipt durable tras reload;
- aprobación bloqueada antes del receipt y habilitada después;
- Guide con propósito, observables, evidencia, fuentes, alternativas,
  misconceptions, niveles y cannot_infer;
- Assessment PDF, Guide PDF y JSON canónico;
- model calls 4 antes y 4 después de export: delta 0;
- capacidad de descarga con TTL 300 segundos que dejó de funcionar al expirar.

Los tres exports fueron leídos únicamente como datos sintéticos de aceptación:
10.372, 19.271 y 9.614 bytes; hashes y tamaños coincidieron con sus receipts.
El Assessment PDF excluyó datos del evaluador y el Guide PDF conservó
trazabilidad.

### Recuperación de shell

El primer candidato de cache no podía retirar retroactivamente un index.html
almacenado antes de la política no-store. El candidato 6d0c968 añadió el epoch.
Con el mismo perfil autenticado:

1. una apertura reprodujo deliberadamente el shell anterior y su GET de sesión
   recibió la purga de cache;
2. se cerró completamente esa pestaña;
3. una nueva apertura en la raíz resolvió /activities sin /login, hard refresh,
   ID ni URL recordada;
4. aparecieron navegación actual, actividad, blueprint APPROVED, submission
   APPROVED, Job SUCCEEDED y Assessment APPROVED.

## Supabase y Cloudflare

| Boundary | Clasificación | Resultado |
|---|---|---|
| Supabase health | CLOUD_REAL | ACTIVE_HEALTHY, PostgreSQL 17 |
| Auth | CLOUD_REAL | Magic link sintético; usuario y membresía tenant-scoped |
| Migración | CLOUD_REAL | 24 tablas/RLS y 2 triggers append-only |
| R2 control plane | CLOUD_REAL | Bucket correcto, privado, r2.dev off, domains 0 |
| R2 CORS | CLOUD_REAL | Origen Cloud Run exacto; GET/PUT/HEAD; Content-Type; ETag; 3600 |
| R2 lifecycle | CLOUD_REAL | multipart 1d, raw 30d, exports 120d |

## Intentos inválidos o fallidos no contados como PASS

| Intento | Clasificación | Causa/acción |
|---|---|---|
| npm audit dentro del sandbox | INTENTO_INVALIDO | DNS bloqueado; reintento autorizado terminó con 0 vulnerabilidades |
| suite runtime dentro del sandbox | INTENTO_INVALIDO | Bind de puerto local bloqueado; misma suite autorizada terminó 21/21 |
| terraform show JSON dentro del sandbox | INTENTO_INVALIDO | Provider no pudo iniciar; reintento read-only autorizado produjo resumen sanitizado |
| export SBOM con location forzada | INTENTO_INVALIDO | Artifact Analysis no resolvió occurrence; resolución automática exportó el SBOM correcto |
| candidato b1d1aa6 | SNAPSHOT_INTERMEDIO | no-store correcto para respuestas nuevas, pero no desalojaba cache histórica; reemplazado por 6d0c968 |
| dos URLs R2 firmadas mostradas por output de herramienta | INTENTO_INVALIDO | capacidades sintéticas individuales de 300 s, ya expiradas; excluidas de evidencia y nunca repetidas |

## Baseline histórico

El corte del 2026-08-01 y sus detalles siguen disponibles en el historial Git
anterior a esta remediación. Aquella evidencia local y el tar histórico no se
presentan como evidencia final. Las auditorías previas permanecen intactas en
docs/audits.
