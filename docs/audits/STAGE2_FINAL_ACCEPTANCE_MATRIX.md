# Matriz final de aceptación — Etapa 2

Fecha: 2026-08-07. `PASS_LOCAL` no equivale a `CLOUD_REAL`.

## E2-01 a E2-15

| Historia | Evidencia principal | Estado |
|---|---|---|
| E2-01 | Batch, multi-submission, PG16/17 upgrade/recovery, negativos cross-scope | PASS_LOCAL + POSTGRESQL_REAL |
| E2-02 | Parser/sandbox 57 pruebas y viewer evidence-first | PASS_LOCAL |
| E2-03 | Jobs control, lease, CAS, retry/cancel/resume/stage reuse | PASS_LOCAL |
| E2-04 | Acciones por pregunta y descriptores durables | PASS_LOCAL |
| E2-05 | Reserva, lineage, rejected fingerprints, limit y exactly N | PASS_LOCAL |
| E2-06 | Coverage submission/activity | PASS_LOCAL |
| E2-07 | Guide y siete exports, replay y model delta 0 | PASS_LOCAL |
| E2-08 | Métricas técnicas/calidad/review | PASS_LOCAL |
| E2-09 | Feedback separado y flags de gobernanza false | PASS_LOCAL |
| E2-10 | MIME, sandbox, CSP, rate limit, privacidad y adversariales | PASS_LOCAL; DATA_REAL_BLOCKED |
| E2-11 | CI/Cloud Build/Terraform declarados y localmente validados | NOT_VERIFIED_EXTERNAL |
| E2-12 | Vitest/Playwright/browser, axe, teclado y 390 px | PASS_LOCAL |
| E2-13 | NOT_REQUIRED/SELECTED/ALL y CHOICE | PASS_LOCAL |
| E2-14 | Bulk autorizado, confirmado, exacto, idempotente y con excepciones | PASS_LOCAL |
| E2-15 | Warning fijo independiente de modelo | PASS_LOCAL |

## Recorrido obligatorio 1–38

El test `test_stage2_controlled_pilot_e2e` materializa el recorrido HTTP local
con FastAPI/repository reales, modelo mock y fixtures sintéticos.

| Paso | Comprobación | Local |
|---:|---|---|
| 1 | usuario autorizado | PASS |
| 2 | actividad nueva | PASS |
| 3 | consigna | PASS |
| 4 | rúbrica opcional | PASS |
| 5 | blueprint | PASS |
| 6 | aprobación blueprint | PASS |
| 7 | al menos dos submissions | PASS |
| 8 | subject_ref distintos | PASS |
| 9 | formatos diferentes | PASS: Markdown/TXT; parsers PDF/DOCX focales |
| 10 | jobs independientes | PASS |
| 11 | submission suficiente | PASS |
| 12 | submission insuficiente | PASS |
| 13 | fail-closed sin assessment parcial | PASS |
| 14 | evidence-first | PASS |
| 15 | ACCEPT | PASS |
| 16 | EDIT | PASS |
| 17 | REJECT | PASS |
| 18 | REGENERATE | PASS |
| 19 | replacement desde reserva | PASS |
| 20 | preservación de otras preguntas | PASS |
| 21 | exactly N | PASS |
| 22 | coverage | PASS |
| 23 | EvaluationGuide | PASS |
| 24 | feedback | PASS |
| 25 | aprobación individual | PASS |
| 26 | bulk con excepción | PASS |
| 27 | exports | PASS |
| 28 | reload/recovery | PASS |
| 29 | cierre completo de navegador | PASS en Playwright E1; E2 browser cloud pendiente |
| 30 | recuperación desde raíz | PASS en Playwright E1; E2 browser cloud pendiente |
| 31 | model-call delta 0 | PASS |
| 32 | métricas | PASS |
| 33 | fallo controlado | PASS |
| 34 | retry controlado | PASS |
| 35 | cancelación | PASS |
| 36 | reanudación | PASS |
| 37 | cross-submission negativo | PASS |
| 38 | cross-tenant negativo | PASS |

## Gates finales

| Gate | Estado |
|---|---|
| Contratos/schema/OpenAPI/frontend drift | PASS_LOCAL |
| Backend completo | PASS_LOCAL: 407 passed |
| PostgreSQL 16/17 | PASS_POSTGRESQL_REAL |
| Frontend/browser | PASS_LOCAL |
| Docker/parser/supply-chain estático | PASS_LOCAL |
| CI del SHA final | NOT_VERIFIED |
| Migración live 003 | NOT_VERIFIED |
| Build/digest/scan/SBOM | NOT_VERIFIED |
| Terraform apply + dos no-drift | NOT_VERIFIED |
| Cloud E2E 1–38 sintético | NOT_VERIFIED |
| P0/P1 locales | 0/0 |
