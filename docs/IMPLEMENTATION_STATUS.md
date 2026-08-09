# Estado de implementación — Etapa 2

Fecha de corte: 2026-08-07 (America/Santiago; evidencia externa hasta
2026-08-09 UTC).

## Estado vigente — merge E2 y gate OpenAI (2026-08-09)

`STAGE2_MERGED_AND_VERIFIED` quedó registrado antes de iniciar este gate.

| Elemento | Evidencia vigente |
|---|---|
| Merge E2 en `main` | `ced91544931afe4453d39ba5e7e86b399d18fcdc` |
| CI completa de `main` | run `31269564662`, 7/7 jobs; commit checks 8/8 |
| Cloud Build baseline corregido | `7c05fba0-a573-44e3-b1a2-4f1338ef21ec`, `SUCCESS/VERIFIED`, SLSA 3 |
| Digest desplegado | `sha256:0d8f29f28dc510bf2cb14f10252e42afe5a7ce05c14e67facccaa066d0065765` |
| Cloud Run | Service rev `cva-web-00016-gml` y Job generación 16 Ready, mismo digest |
| Invariantes runtime | health/readiness 200, privado anónimo 401, mock, P10 false, libmagic true, Job retries 0 |
| Verificación focalizada cloud | E2-FINAL-001..004 y regresión sintética PASS |
| Terraform | apply revisado y dos planes vivos consecutivos sin drift |
| Evidencia durable del cierre | `STAGE2_MERGED_AND_VERIFIED_ced9154_20260808T180056Z.json`, SHA-256 `f70a2aea2d8193e85d81770b60c0e0f555079de669f2a9a39a9c220db3efb71b` |
| Paquete de auditoría focalizada | SHA-256 `cb5e61e25d43a866bd11a0126bf229636fae57366c17dbdba6090657e0bd978d` |

El código auditado fue `d905557…` con 410 passed/16 skips PostgreSQL
explícitos y auditoría focalizada P0=0/P1=0. El runtime histórico
`44b9483…` precede las cuatro correcciones P1 y no se presenta como runtime del
candidato corregido.

Desde ese `main` verificado se creó `codex/openai-real-provider-gate`.
El estado técnico alcanzado es `OPENAI_REAL_SMOKE_PASS` sobre
`LUNA_BASELINE_V1`: SDK oficial `openai==2.53.0` fijado con hashes, Responses
API, modelos explícitos,
Structured Outputs derivados de Pydantic, errores/retries/budget/ledger,
Secret Manager/IAM worker-only, smoke gobernado y golden set sintético. P11 es
efectivamente `gpt-5.6-luna` con `reasoning_effort=low`; P10 no tiene ruta.
P01/P02 usan Luna-medium y P03-P09 Luna-high. La matriz Sol histórica no es
callable ni fallback y el adapter la rechaza antes de crear transporte.
Los schemas, prompts versionados, allowlists y validación posterior alcanzan
`OPENAI_CONTRACT_BOUNDARIES_PASS` offline. La calidad del proveedor permanece
en `OPENAI_SEMANTIC_EVAL_PENDING`; no se declara
`OPENAI_SYNTHETIC_E2E_PASS` antes de ejecutar el recorrido real autorizado.

El proyecto OpenAI dedicado `PruebasPersonalizadas`
(`proj_te2wY3kbHAkFp8IgjglH063t`) quedó identificado y permite únicamente
`gpt-5.6-luna`. El propietario insertó privadamente la clave de aplicación como
la versión numérica `1` de `cva-openai-api-key`; Secret Manager informa esa
única versión `enabled`. El agente no inspeccionó el payload: el proceso aislado
del smoke lo consumió solo en memoria y limpió su environment al terminar. La
clave no está montada en ningún runtime, el secreto no tiene bindings IAM y CI
no recibe la clave. El cloud vigente no fue modificado: sigue en mock/P10 false.
La temperatura deseada se conserva en la ruta canónica y se omite del request,
con reason codes explícitos.

Tras un fallo local/pre-provider del harness efímero (`routes=`), con cero
Responses requests y USD 0.00, se protegió el entrypoint versionado sin cambiar
gateway, adapter, rutas ni contratos. El commit `e1f6714…` pasó la CI
`31293361151` 7/7. La única llamada P11 Luna-low autorizada terminó
`OPENAI_REAL_SMOKE_PASS`: 1 request/attempt, 1,365 input tokens, 0 cached, 257
output, 57 reasoning, 3,832 ms, costo estimado post-usage USD 0.0099411 y costo
real calculado USD 0.0006495. Modelo solicitado/efectivo Luna, validaciones
schema/Pydantic/contextual PASS y cero retries. P10, Sol y tools permanecieron
en cero; `store=false`, `background=false`. Los request/output IDs se conservaron
solo como hashes. Platform mostró antes del smoke spend limit USD 5.00, USD 3.77
usado y `gpt-5.6-luna` como único modelo permitido. No hubo segunda request.

La preparación posterior de los dos canaries quedó cerrada offline en
`OPENAI_LUNA_CANARY_APPROVAL_REQUIRED`. El harness versionado admite un único
caso P01 o P07 por ejecución bajo una frontera separada: ruta Luna seleccionada
únicamente, P10/P11 ausentes, guard de una request y retries
gateway/prompt/SDK 0/0/0, sin alterar la política del worker. P01 Luna-medium y
P07 Luna-high pasaron contra el adapter real y transporte fake con
schema/Pydantic/contexto/IDs válidos. Los precios Standard vigentes permanecen
en Sol 5.00/0.50/30.00, Terra 2.00/0.20/12.00 y Luna 0.20/0.02/1.20 USD por
millón de tokens de input/cached input/output.

La autorización humana posterior produjo `OPENAI_LUNA_CANARY_P07_FAILED` sobre
el sucesor `9923097f7b511453af5306614fa62ae436c6c4b3`, cuya CI
`31323517518` había terminado 7/7. P01 pasó con outcome `READY`, Luna efectiva,
1 request, 1,712/858 tokens input/output, 516 reasoning, 9,030 ms y USD
0.00145745 calculados. P07 consumió su única request y falló estructuralmente;
P11 no tenía ruta y fue bloqueado antes de transporte, por lo que no hubo
repair ni segunda request. P07 registró 3,839/1,930 tokens input/output, 1,034
reasoning y USD 0.00327560 calculados; el outcome y las validaciones
contextuales no se alcanzaron. La severidad manifest es P1. Total: 2 requests,
USD 0.00473305; P10/P11/Sol/retries/exposición del secreto en cero. Platform no
ofreció aún costo atribuible por llamada: conservó spend redondeado USD 3.77 y
el desglose Luna histórico de 1,365 input tokens. Cloud no se modificó y sigue
mock/P10 false.

La regresión local previa al smoke quedó en 457 passed/16 skips PostgreSQL
explícitos, 80% de cobertura, 40 tests focalizados CLI/adapter, golden set
20/20 con 0 network/0 billable, PostgreSQL 16/17
con 155/155 y doble matriz 1+7, frontend 32/32, Playwright 1+2, navegador
integrado limpio, Docker runtime/audit, Stage 0 reproducible,
contratos/OpenAPI sin drift, Terraform válido y secret scan limpio. La CI del
commit previo al gasto quedó 7/7 verde.

| Severidad vigente | Abiertos |
|---|---:|
| P0 | 0 |
| P1 | 1 |
| P2 | 4 |
| P3 | 1 |

El P1 nuevo es el fallo estructural del canary P07 Luna-high; quedó fail-closed
sin reparación ni continuación. Los P2 históricos siguen siendo
AV/compensación, corpus/política de privacidad y semántica real pendiente. El
cuarto P2 es la re-revisión interactiva P05 del Service: queda bloqueada con
`MODEL_EXECUTION_REQUIRES_WORKER` cuando el worker sea real hasta migrarla a un
job durable, por lo que nunca mezcla silenciosamente mock con OpenAI. El P3
continúa siendo el warning deprecado Starlette/httpx del adaptador de tests.

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
Terraform, secrets y regeneración sin drift. El candidato `d905557…` pasó CI
push/PR 7/7 y Cloud Build `SUCCESS/VERIFIED`; el paquete externo durable quedó
registrado con SHA-256
`cb5e61e25d43a866bd11a0126bf229636fae57366c17dbdba6090657e0bd978d`.
La evidencia cloud desplegada permanece ligada a `44b9483…`; las correcciones
nuevas fueron construidas/smoke-tested, pero no se declaran desplegadas.
