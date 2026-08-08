# Estado de implementación — Etapa 2

Fecha de corte: 2026-08-07 (America/Santiago).

## Identidad y gate

`STAGE2_GATE_OPEN` fue autorizado el 2026-08-07 sobre
`STAGE2_BASELINE_SHA=80dd57dbf38d56929c307eca956833c31e53bf33`.

| Elemento | Estado |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` |
| Rama | `codex/stage2-experimental-mvp` |
| Candidato | Worktree local; el SHA final se registra después del commit |
| Etapa 0 | Cerrada; regresión preservada |
| Etapa 1 | Cerrada; baseline y auditorías históricas preservados |
| Etapa 2 | Implementada localmente; CI y cloud pendientes de evidencia del SHA final |
| Etapa 3 | No autorizada |
| Modelo | `CVA_MODEL_MODE=mock`; proveedor real no autorizado |
| P10 | `CVA_P10_ENABLED=false` |
| Datos | Solo fixtures sintéticos; datos estudiantiles reales no autorizados |

La regresión previa a cualquier cambio fue `163 passed, 7 skipped`, más 19
pruebas frontend, typecheck, build, Stage 0, contratos y navegador. El único
gate rojo heredado fue `nanoid@3.3.16`; E2 lo actualiza a `3.3.18` y el audit
final queda en cero vulnerabilidades high/critical.

## Superficie E2 implementada

| Historia | Resultado del candidato local |
|---|---|
| E2-01 | Lote manual, múltiples submissions, `subject_ref` seudónimo, filtros y aislamiento por tenant/submission |
| E2-02 | TXT, Markdown, PDF digital y DOCX estructural con MIME real, límites, localizadores y rechazo de contenido activo |
| E2-03 | Jobs durables con clases de fallo, retry acotado, cancel, resume, leases y reutilización de `stage_runs` válida por hashes |
| E2-04 | ACCEPT, REJECT, EDIT y REGENERATE server-side, append-only, versionadas y revalidadas |
| E2-05 | Reemplazo localizado desde reserva, lineage, presupuesto durable y exactly N o fail-closed |
| E2-06 | Coverage por submission y actividad con dimensiones, oportunidades, evidencia, planificación y diagnósticos |
| E2-07 | EvaluationGuide independiente y siete exports derivados de snapshots, con delta de llamadas de modelo igual a cero |
| E2-08 | Métricas técnicas, de calidad y de revisión humana sin texto estudiantil |
| E2-09 | Feedback gobernable de actividad, assessment o pregunta, sin reutilización automática |
| E2-10 | Sandbox parser en subproceso, libmagic, seccomp sin red, RLIMIT/timeout, rate limit, CSP y fronteras de capabilities |
| E2-11 | CI, Cloud Build, Terraform y Cloud Run conservados; imagen por digest y Job 1/1/0 |
| E2-12 | Teclado, foco, labels, tabs roving, Home/End/flechas, axe y viewport de 390 px |
| E2-13 | `NOT_REQUIRED`, `SELECTED` y `ALL`, incluida regeneración coherente de preguntas seleccionadas |
| E2-14 | Aprobación masiva confirmada, versionada, particionada, idempotente y con exclusiones auditables |
| E2-15 | Aviso fijo de límites del producto, independiente del modelo y de P09 |

## Evidencia vigente

| Gate | Clasificación | Estado |
|---|---|---|
| Contratos | LOCAL_REAL | PASS: bundle 1.2.0, 53 roots, 140 definiciones, 274 referencias; 46 roots/112 definiciones E1 sin drift estructural |
| Backend completo | LOCAL_REAL + MOCK_MODEL | PASS: 407 passed, 16 PostgreSQL-only skipped |
| Parser y sandbox | LOCAL_REAL | PASS: 57 pruebas; libmagic, seccomp `EPERM`, timeout, binding de procedencia y rechazo fail-closed |
| Frontend | LOCAL_REAL | PASS: typecheck, 6 archivos/32 tests, build de 87 módulos, audit 0 vulnerabilidades |
| Browser | LOCAL_REAL | PASS: recorrido E1 1/1 y recorrido E2 mock API 1/1, axe, teclado y 390 px |
| PostgreSQL 16 | POSTGRESQL_REAL | PASS: upgrade E1→E2, recovery segura, carrera de writer y readiness negativa |
| PostgreSQL 17 | POSTGRESQL_REAL | PASS: upgrade E1→E2, recovery segura, carrera de writer y readiness negativa |
| Docker | LOCAL_REAL | PASS: runtime no-root/read-only, app inmutable, health/readiness y parser aislado |
| Secrets/deploy/schema drift | LOCAL_REAL | PASS |
| GitHub Actions del SHA E2 | NOT_VERIFIED | Pendiente de publicar el candidato |
| Migración Supabase 003 | NOT_VERIFIED | Pendiente de backup, quiesce y aplicación live revisada |
| Cloud Build/digest E2 | NOT_VERIFIED | Pendiente del SHA publicado y CI verde |
| Terraform apply y doble no-drift | NOT_VERIFIED | Pendiente del digest E2 |
| Cloud E2E sintético 1–38 | NOT_VERIFIED | Pendiente del runtime E2 Ready |

Los detalles reproducibles están en [TEST_RESULTS.md](TEST_RESULTS.md) y en
[STAGE2_EVIDENCE_MANIFEST.md](audits/STAGE2_EVIDENCE_MANIFEST.md). Una entrada
`NOT_VERIFIED` no se presenta como PASS ni se sustituye por evidencia cloud E1.

## Auditoría y deuda

La auditoría adversarial encontró y cerró carreras de cancel/dispatch,
continuaciones múltiples, resume inválido, aprobación no atómica, acciones de
pregunta no recuperables, límites de regeneración, roles, uploads rechazados,
readiness incompleta y recovery con pérdida concurrente. Cada corrección se
revalidó y la regresión completa quedó verde.

| Severidad | Abiertos locales |
|---|---:|
| P0 | 0 |
| P1 | 0 |
| P2 | 3 |
| P3 | 1 |

La deuda P2/P3 está limitada a gates posteriores o no bloqueantes:

- ClamAV no está desplegado. El parser aislado es control compensatorio para
  fixtures sintéticos; los datos reales permanecen bloqueados hasta un AV
  operativo o una aceptación formal equivalente.
- No existe corpus autorizado de documentos reales ni política legal de
  retención; no se infieren.
- La semántica con proveedor IA real no fue validada porque el proveedor real
  sigue prohibido.
- `StarletteDeprecationWarning` del adaptador de tests es deuda P3.

## Límites de cierre

Este candidato no autoriza Etapa 3, modelos reales, datos estudiantiles reales,
OCR, LMS, calificación, detección de IA, inferencia de autoría o fraude. El
estado `READY_FOR_CONTROLLED_PILOT` solo puede emitirse después de CI verde,
migración live, build por digest, apply Terraform revisado, runtime Ready,
cloud E2E sintético y dos planes sin drift.

El cierre histórico de E1 permanece inalterado en
[STAGE1_FINAL_ACCEPTANCE_MATRIX.md](audits/STAGE1_FINAL_ACCEPTANCE_MATRIX.md) y
[STAGE1_EVIDENCE_MANIFEST.md](audits/STAGE1_EVIDENCE_MANIFEST.md).
