# Matriz final de aceptación — Etapa 2

Fecha: 2026-08-07; evidencia externa observada hasta 2026-08-08 UTC.
`PASS_LOCAL`, `CI_REAL`, `CLOUD_REAL` y `CLOUD_REAL_BROWSER` identifican
fronteras distintas y no se sustituyen entre sí.

## E2-01 a E2-15

| Historia | Evidencia principal | Estado |
|---|---|---|
| E2-01 | Batch, multi-submission, PG16/17 upgrade/recovery y negativos cross-scope; dos submissions cloud | PASS_LOCAL + POSTGRESQL_REAL + CLOUD_REAL |
| E2-02 | Parser/sandbox 57 pruebas, viewer evidence-first y DOCX/TXT cloud | PASS_LOCAL + CLOUD_REAL |
| E2-03 | Jobs, lease, CAS, retry/cancel/resume/stage reuse; lineage cloud | PASS_LOCAL + CI_REAL + CLOUD_REAL + CONTROLLED_ADMIN_SEED |
| E2-04 | Acciones por pregunta y descriptores durables | PASS_LOCAL + CLOUD_REAL |
| E2-05 | Reserva, lineage, rejected fingerprints, limit y exactly N | PASS_LOCAL + CLOUD_REAL |
| E2-06 | Coverage submission/activity | PASS_LOCAL + CLOUD_REAL |
| E2-07 | Guide y siete exports, replay y model delta 0 | PASS_LOCAL + CLOUD_REAL |
| E2-08 | Métricas técnicas/calidad/review | PASS_LOCAL + CLOUD_REAL |
| E2-09 | Feedback separado y flags de gobernanza false | PASS_LOCAL + CLOUD_REAL |
| E2-10 | MIME, sandbox, CSP, rate limit, privacidad y adversariales | PASS_LOCAL + CLOUD_REAL; DATA_REAL_BLOCKED |
| E2-11 | CI 7/7 en push/PR; build, migración, digest, Terraform y runtime verificados | PASS_CI_REAL + PASS_CLOUD_REAL |
| E2-12 | Vitest/Playwright/browser, axe, teclado; cloud 1440/390 y cierre/reapertura | PASS_LOCAL_BROWSER + PASS_CLOUD_REAL_BROWSER |
| E2-13 | NOT_REQUIRED/SELECTED/ALL y CHOICE | PASS_LOCAL + CLOUD_REAL |
| E2-14 | Bulk autorizado, confirmado, exacto, idempotente y con excepciones | PASS_LOCAL + CLOUD_REAL |
| E2-15 | Warning fijo independiente de modelo | PASS_LOCAL + CLOUD_REAL |

## Recorrido obligatorio 1–38

El test local `test_stage2_controlled_pilot_e2e` y el manifest cloud sintético
materializaron el recorrido con modelo mock. En cloud se usaron DOCX y TXT. Los
pasos 12 y 33–36 se probaron contra el runtime real después de sembrar
determinísticamente el estado requerido: su clasificación es
`CLOUD_REAL + CONTROLLED_ADMIN_SEED`, no un fallo natural del proveedor. La
lineage de retry/resume se observó en cloud; su semántica de éxito queda
demostrada por local/CI.

| Paso | Comprobación | Local/CI | Cloud |
|---:|---|---|---|
| 1 | usuario autorizado | PASS | PASS_CLOUD_REAL |
| 2 | actividad nueva | PASS | PASS_CLOUD_REAL |
| 3 | consigna | PASS | PASS_CLOUD_REAL |
| 4 | rúbrica opcional | PASS | PASS_CLOUD_REAL |
| 5 | blueprint | PASS | PASS_CLOUD_REAL |
| 6 | aprobación blueprint | PASS | PASS_CLOUD_REAL |
| 7 | al menos dos submissions | PASS | PASS_CLOUD_REAL |
| 8 | `subject_ref` distintos | PASS | PASS_CLOUD_REAL |
| 9 | formatos diferentes | PASS: Markdown/TXT; parsers PDF/DOCX focales | PASS_CLOUD_REAL: DOCX/TXT |
| 10 | jobs independientes | PASS | PASS_CLOUD_REAL |
| 11 | submission suficiente | PASS | PASS_CLOUD_REAL |
| 12 | submission insuficiente | PASS | PASS_CLOUD_REAL + CONTROLLED_ADMIN_SEED |
| 13 | fail-closed sin assessment parcial | PASS | PASS_CLOUD_REAL |
| 14 | evidence-first | PASS | PASS_CLOUD_REAL |
| 15 | ACCEPT | PASS | PASS_CLOUD_REAL |
| 16 | EDIT | PASS | PASS_CLOUD_REAL |
| 17 | REJECT | PASS | PASS_CLOUD_REAL |
| 18 | REGENERATE | PASS | PASS_CLOUD_REAL |
| 19 | replacement desde reserva | PASS | PASS_CLOUD_REAL |
| 20 | preservación de otras preguntas | PASS | PASS_CLOUD_REAL |
| 21 | exactly N | PASS | PASS_CLOUD_REAL |
| 22 | coverage | PASS | PASS_CLOUD_REAL |
| 23 | EvaluationGuide | PASS | PASS_CLOUD_REAL |
| 24 | feedback | PASS | PASS_CLOUD_REAL |
| 25 | aprobación individual | PASS | PASS_CLOUD_REAL |
| 26 | bulk con excepción | PASS | PASS_CLOUD_REAL |
| 27 | exports | PASS | PASS_CLOUD_REAL |
| 28 | reload/recovery | PASS | PASS_CLOUD_REAL |
| 29 | cierre completo de navegador | PASS | PASS_CLOUD_REAL_BROWSER |
| 30 | recuperación desde raíz | PASS | PASS_CLOUD_REAL_BROWSER |
| 31 | model-call delta 0 | PASS | PASS_CLOUD_REAL |
| 32 | métricas | PASS | PASS_CLOUD_REAL |
| 33 | fallo controlado | PASS | PASS_CLOUD_REAL + CONTROLLED_ADMIN_SEED |
| 34 | retry controlado y lineage | PASS | PASS_CLOUD_REAL + CONTROLLED_ADMIN_SEED; semántica LOCAL/CI |
| 35 | cancelación | PASS | PASS_CLOUD_REAL + CONTROLLED_ADMIN_SEED |
| 36 | reanudación y lineage | PASS | PASS_CLOUD_REAL + CONTROLLED_ADMIN_SEED; semántica LOCAL/CI |
| 37 | cross-submission negativo | PASS | PASS_CLOUD_REAL |
| 38 | cross-tenant negativo | PASS | PASS_CLOUD_REAL |

Resultado del manifest cloud: 38/38 PASS. Estado externo:
`/private/tmp/cva_stage2_cloud_e2e_state_e2e08080110.json`, SHA-256
`38b67798cdc8de3fd60a9464cb4a781cd8c3111f7b6cba3f15a41df75155b628`.

## Gates finales

| Gate | Estado |
|---|---|
| Contratos/schema/OpenAPI/frontend drift | PASS_LOCAL |
| Backend completo | PASS_LOCAL: 407 passed |
| PostgreSQL 16/17 | PASS_POSTGRESQL_REAL |
| Frontend/browser | PASS_LOCAL_BROWSER + PASS_CLOUD_REAL_BROWSER |
| CI runtime push/PR | PASS_CI_REAL: `31232751301` y `31232752740`, 7/7 cada uno |
| Migración live 003 | PASS_CLOUD_REAL + POSTGRESQL_REAL: aplicada una vez |
| Build/digest | PASS_CLOUD_REAL: `aad1bf58-966e-44f9-ad10-5d7b81144854`, digest inmutable verificado |
| Provenance/scan | PASS_CLOUD_REAL: SLSA 3 v1 `GoogleHostedWorker`; `FINISHED_SUCCESS` |
| SBOM | NOT_OBSERVED / NO CLAIM |
| Terraform apply + dos no-drift | PASS_CLOUD_REAL: 0 add/2 change/0 destroy; PASS/PASS |
| Service/Job + health/readiness | PASS_CLOUD_REAL; Ready y mismo digest, mock, P10 false, libmagic true |
| Cloud E2E 1–38 sintético | PASS_CLOUD_REAL: 38/38, con seeds controlados declarados |
| Cleanup y estado final | PASS_CLOUD_REAL: Auth 0, jobs activos 0, capabilities 0, errores/fugas de logs 0/0 |
| P0/P1 | 0/0 |

La matriz admite un piloto controlado exclusivamente sintético en modelo mock.
Datos reales, modelo real, P10 y Etapa 3 permanecen bloqueados; ClamAV está
ausente. P2/P3 abiertos: 3/1.

## Addendum de auditoría final focalizada — 2026-08-08

La matriz fue reabierta únicamente para cuatro defectos P1 reproducibles y se
volvió a cerrar después de corregirlos: replay de upload sobre la reserva
exacta, actividad cancelada recuperable, métricas de retry no triangulares y
cancelación atómica de `QUESTION_ACTION`. Las pruebas adversariales y la suite
completa pasaron; backend local actual: 410 passed, 16 skips PostgreSQL
declarados, 79% de cobertura. Los gates frontend/browser/parser/deploy/Stage 0
y drift generado también pasaron.

La aceptación del código nuevo es `PASS_LOCAL + PASS_CI_REAL`: candidato
`d905557…`, GitHub Actions push `31267922067` y PR `31267923824` 7/7 cada uno,
y Cloud Build `40d124f3…` `SUCCESS/VERIFIED` sobre el source exacto. La imagen
por digest solo fue construida/smoke-tested. `PASS_CLOUD_REAL` continúa
describiendo exclusivamente el runtime desplegado `44b9483…`; no se extiende
por inferencia al código nuevo. P0/P1 abiertos permanecen 0/0 y P2/P3
permanecen 3/1.
