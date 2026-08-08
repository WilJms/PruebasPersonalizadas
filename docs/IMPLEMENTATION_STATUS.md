# Estado de implementación — Etapa 2

Fecha de corte: 2026-08-07 (America/Santiago; evidencia externa hasta
2026-08-08 UTC).

## Identidad y gate

`STAGE2_GATE_OPEN` fue autorizado el 2026-08-07 sobre
`STAGE2_BASELINE_SHA=80dd57dbf38d56929c307eca956833c31e53bf33`.

| Elemento | Estado |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` |
| Rama | `codex/stage2-experimental-mvp` |
| Candidato runtime probado | `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` |
| Pull request | Draft `#2` |
| Etapa 0 | Cerrada; regresión preservada |
| Etapa 1 | Cerrada; baseline y auditorías históricas preservados |
| Etapa 2 | Implementada y verificada localmente, en CI y en cloud con datos sintéticos |
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
| GitHub Actions del SHA E2 | CI_REAL | PASS: push `31232751301` y PR `31232752740`, 7/7 jobs SUCCESS cada uno |
| Migración Supabase 003 | CLOUD_REAL | PASS: aplicada una vez; SHA-256 `6bb9de336b176e89abced2dc56032b83c05e4613c9f2462cde3835573a22df61`; backup previo verificado |
| Cloud Build/digest E2 | CLOUD_REAL | PASS: build `aad1bf58-966e-44f9-ad10-5d7b81144854` SUCCESS/VERIFIED; digest `sha256:0c6be928c698cd052763c9daf683ae19d4f5b8a99cba06b54fc32e244d70044e` |
| Supply chain cloud | CLOUD_REAL | PASS observado: SLSA 3 v1 `GoogleHostedWorker` y continuous scan `FINISHED_SUCCESS`; SBOM no reclamado |
| Terraform apply y doble no-drift | CLOUD_REAL | PASS: 0 add, 2 change, 0 destroy; dos planes vivos consecutivos sin cambios |
| Cloud Run | CLOUD_REAL | PASS: Service/Job Ready, mismo digest, mock, P10 false y libmagic true |
| Cloud E2E sintético 1–38 | CLOUD_REAL + MOCK_MODEL | PASS 38/38; pasos 12 y 33–36 usan seed administrativo controlado y se declaran como tales |
| Browser cloud | CLOUD_REAL_BROWSER | PASS desktop 1440 px y móvil 390 px, close/reopen, consola limpia y sin overflow global |
| Logs/capabilities | CLOUD_REAL | PASS: jobs activos 0, persistencia de capabilities 0, errores finales 0 y leaks 0 |

Los detalles reproducibles están en [TEST_RESULTS.md](TEST_RESULTS.md) y en
[STAGE2_EVIDENCE_MANIFEST.md](audits/STAGE2_EVIDENCE_MANIFEST.md). La prueba de
retry/resume en cloud acredita control durable y lineage; su éxito semántico
se conserva como evidencia local/CI, no se presenta como un fallo natural de
proveedor. Tampoco se reclama SBOM para este digest.

## Auditoría y deuda

La auditoría adversarial encontró y cerró carreras de cancel/dispatch,
continuaciones múltiples, resume inválido, aprobación no atómica, acciones de
pregunta no recuperables, límites de regeneración, roles, uploads rechazados,
readiness incompleta y recovery con pérdida concurrente. Cada corrección se
revalidó y la regresión completa quedó verde.

| Severidad | Abiertos |
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
OCR, LMS, calificación, detección de IA, inferencia de autoría o fraude. Los
gates técnicos de CI, migración, build por digest, apply Terraform, runtime,
cloud E2E sintético y doble no-drift quedaron observados. El alcance continúa
siendo exclusivamente un piloto controlado sintético en modo mock.

El cierre histórico de E1 permanece inalterado en
[STAGE1_FINAL_ACCEPTANCE_MATRIX.md](audits/STAGE1_FINAL_ACCEPTANCE_MATRIX.md) y
[STAGE1_EVIDENCE_MANIFEST.md](audits/STAGE1_EVIDENCE_MANIFEST.md).

## Checkpoint de auditoría final focalizada — 2026-08-08

Una pasada inicial de solo lectura confirmó PR/base/head/CI y que
`44b9483…bdb4469` modifica únicamente nueve documentos. La revisión focalizada
posterior reprodujo y cerró cuatro P1: reserva exacta en replay de upload,
actividad recuperable tras cancelación, conteo correcto de retries y frontera
atómica entre cancelación y acción de pregunta. La contradicción del digest en
`PARSER_SECURITY_E2.md` también quedó corregida sin levantar el gate de datos
reales.

El candidato corregido pasa 410 pruebas backend (16 skips PostgreSQL locales
declarados), 79% de cobertura, 57 pruebas parser, 11 de deploy, typecheck,
32 tests frontend, build, audit sin vulnerabilidades, Playwright 1+2, Stage 0,
Terraform, secrets y regeneración sin drift. La CI y el paquete externo durable
se registran por SHA antes de declarar el checkpoint listo para merge. La
evidencia cloud permanece ligada a `44b9483…`; las correcciones nuevas no se
declaran desplegadas.
