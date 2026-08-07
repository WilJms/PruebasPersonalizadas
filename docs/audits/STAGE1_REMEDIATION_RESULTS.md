# Resultados de remediación integral de Etapa 1

Fecha de corte documental: 2026-08-07.

Este informe relaciona la auditoría de producto del Prompt 1 (F-001 a F-022)
con la auditoría técnica del Prompt 2 (AUD-P1/P2/P3). Las auditorías originales
se conservan sin edición. La evidencia primaria final se publica fuera del
repositorio después de FINAL_STAGE1_SHA.

## Commits de remediación

| Commit | Alcance |
|---|---|
| 7ea3a3a | PrincipalId, DTOs OpenAPI, snapshot y tests provider/consumer |
| 159a2d1 | recuperación durable, edición, preflight, evidence receipts y backend review |
| e3b8d67 | shell, review UX, CHOICE, Guide, accesibilidad y Playwright |
| 000e771 | logging, PostgreSQL 16/17, Terraform, trigger/build, IAM y supply chain |
| 5e7eaca | eliminación de superficie runtime vulnerable |
| b1d1aa6 | documentos SPA no-store y assets inmutables |
| 6d0c968 | autorrecuperación de cache histórica mediante shell epoch |
| FINAL_STAGE1_SHA | documentación de cierre; su hash se resuelve al crear este último commit |

## P1: todos cerrados

| Prompt 2 | Prompt 1 | Corrección y archivos | Contrato/infra | Pruebas y evidencia | Resultado |
|---|---|---|---|---|---|
| AUD-P1-01 | — | Scaling superior explícito en deploy/terraform/main.tf; sin ignore_changes | Terraform conserva ownership | Plan reproducido exit 2, apply revisado y dos planes vivos exit 0 | CLOSED |
| AUD-P1-02 | — | Connection/repository/trigger v2 y outputs Terraform | Repo único, us-east1, build SA sin Run Admin | Trigger real, build exacto, provenance, digest y runtime | CLOSED |
| AUD-P1-03 | F-002 | ActivitiesPage, AppShell, recovery DTO, no-store y shell epoch | Lista tenant-scoped desde estado durable | Unit/Vitest/Playwright y reapertura cloud desde raíz | CLOSED |
| AUD-P1-04 | F-008 | Access log Uvicorn deshabilitado; middleware JSON allowlist por plantilla | Nunca URL/query/path crudo ni payload | Proceso real con capability válida/inválida/expirada: 0 apariciones | CLOSED |
| AUD-P1-05 | F-009 | BlueprintPage proyecta restricciones, checks, requisitos y derivados | Dificultad/operaciones siguen read-only | Tests frontend y revisión cloud del blueprint sintético | CLOSED |
| AUD-P1-06 | F-012 | DTO/tipos y AssessmentReviewPage conservan SelectedQuestion completo | No se estrecha el root canónico | Snapshot OpenAPI, consumer tests y cloud review | CLOSED |
| AUD-P1-07 | F-013 | CHOICE muestra orden, alternativas, best, rationale y misconception | Student justification permanece independiente | Validator, frontend y caso cloud CHOICE+NOT_REQUIRED | CLOSED |
| AUD-P1-08 | F-014 | Evidence receipt durable por fragmento en repository/workflows/API | Tenant, actor y assessment version scoped | Éxito, múltiples fragments, expiración, locator, tenant, actor, reload y API directa | CLOSED |
| AUD-P1-09 | F-016 | Guide UI/template conserva purpose, observables, refs, alternatives, misconceptions, levels y cannot_infer | Assessment y Guide siguen separados | Tests de export/UI y Guide cloud completa | CLOSED |
| AUD-P1-10 | F-017/F-018/F-019 | web/dto.py, response models, generator, snapshot y cliente generado | DTOs componen modelos/enums canónicos | Provider/consumer, ref crawl, negativos, determinismo y CI | CLOSED |
| AUD-P1-11 | — | PrincipalId en actores externos canónicos y tests negativos/UUID | Id interno no se amplió globalmente | Pydantic, schema, fixtures, events y OpenAPI | CLOSED |

## P2 y P3

| Prompt 2 | Prompt 1 | Corrección/decisión | Commit o evidencia | Pruebas/límite | Resultado |
|---|---|---|---|---|---|
| AUD-P2-01 | F-006 | ActivityEditPage con GET/PATCH, ETag e If-Match; freeze bloqueado | 159a2d1/e3b8d67 | stale ETag y ruta UI | CLOSED |
| AUD-P2-02 | F-007 | Preflight determinista visible para actividad/submission; fail-closed por límite | 159a2d1/e3b8d67 | cambios de inputs y over-limit antes de model call | CLOSED |
| AUD-P2-03 | F-011 | Review read-only expone planning, oportunidades, evidencia, locators y reviews sin acciones E2 | 159a2d1/e3b8d67 | tenant scope y trazas end-to-end | CLOSED |
| AUD-P2-04 | F-001 | Se conserva copy experimental honesto; no se inventa política legal/contacto sin autoridad | Backlog final | Riesgo de aviso institucional incompleto | ACCEPTED_DEBT |
| AUD-P2-05 | F-003/F-005/F-010 | Labels humanos distinguen CHOICE, SELECTED, rationale y justificación | e3b8d67 | CHOICE+NOT_REQUIRED y alcance seleccionado | CLOSED |
| AUD-P2-06 | F-015/F-020 | Tablist/tab/tabpanel, roving tabindex, flechas, Home/End y focus-visible | e3b8d67 | teclado, Vitest y Playwright accessibility | CLOSED |
| AUD-P2-07 | — | Fixtures y conteos scoped; no dejan QUEUED/RUNNING contaminantes | 000e771 | matriz PG16/17 repetida dos veces sin limpieza | CLOSED |
| AUD-P2-08 | — | CI matrix PostgreSQL 16 y 17 | 000e771 | migración, E2E y sensibles en ambos majors | CLOSED |
| AUD-P2-09 | — | Estado, setup, decisiones, resultados, matrices y PR actualizados | FINAL_STAGE1_SHA | stale markers históricos diferenciados | CLOSED |
| AUD-P2-10 | — | Paquete final externo con manifest, timestamps, hashes y clasificación | Evidencia final externa | excluye secretos, URLs firmadas y archivos vacíos | CLOSED |
| AUD-P2-11 | — | Cadena PR head a CI/build/OCI/digest/Terraform/runtime explícita | Trigger + manifest final | distingue CI_MERGE_SHA de head | CLOSED |
| AUD-P2-12 | — | Bases por digest, locks con hashes, Actions por SHA, provenance, scan y SBOM | 000e771/5e7eaca | cierre práctico E1; no afirma bit reproducibility universal | CLOSED |
| AUD-P2-13 | — | WorkerSettings separado; env/IAM sin session secret | 000e771 | worker y auth web reales Ready | CLOSED |
| AUD-P2-14 | — | Control plane R2 revalidado directamente en cuenta/bucket autorizados | CLOUD_REAL | CORS/lifecycle/privacy; no objetos ajenos | CLOSED |
| AUD-P2-15 | — | Export durable puede recrearse determinísticamente con delta de modelo 0; falta lista/reemisión visual automática tras reload | Backlog final | Riesgo de usabilidad, no pérdida del snapshot ni del objeto | ACCEPTED_DEBT |
| AUD-P2-16 | F-021/F-022 | Jerarquía y AGENTS bloquean E2; no se reescribe historia contractual inferior | Backlog final | Riesgo documental controlado por gate explícito | ACCEPTED_DEBT |
| AUD-P2-17 | — | Playwright crítico local en CI y verificación cloud real | e3b8d67/000e771 | login a export, close/reopen y accessibility | CLOSED |
| AUD-P3-01 | — | Combinación actual compatible y fijada; warning documentado | Backlog final | Upgrade sin necesidad puede romper FastAPI/TestClient | ACCEPTED_DEBT |
| AUD-P3-02 | F-004 | OPEN_SHORT explicado como formato operacional sin palabras, caracteres ni dificultad | e3b8d67 | payload/enum/schema 1.1.0 sin cambio semántico | CLOSED |

## Contratos y alcance

- SCHEMA_VERSION permanece 1.1.0.
- OPEN_SHORT permanece sin OPEN_LONG, límites inventados ni cambio de
  profundidad.
- La dificultad continúa derivada y visible de solo lectura.
- CHOICE y la justificación estudiantil continúan como conceptos separados.
- Los roots futuros corregidos por PrincipalId no activan bulk approval ni
  question actions.
- La revisión académica humana se conserva; el gate de ingeniería usa agentes
  de IA, tests y evidencia.

## Infraestructura y evidencia

El candidato 6d0c968 fue validado con CI doble verde, Cloud Build exacto,
provenance SLSA 3, scan limpio, SBOM, mismo digest en Service/Job, Terraform
convergente, Supabase/PostgreSQL/Auth, R2 privado y navegador cloud.

FINAL_STAGE1_SHA repite esa cadena desde su source exacto. Los identificadores,
checksums y resultados posteriores al commit se guardan en el artifact externo
y se someten a auditoría independiente. No se hace merge ni tag.
