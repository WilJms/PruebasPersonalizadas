# Matriz final de aceptación E0/E1

Fecha de corte documental: 2026-08-07.

PASS significa que existe implementación y evidencia ejecutada. La columna
Boundary evita presentar un mock como prueba cloud. Los identificadores del
último build/runtime se resuelven en el manifest externo de FINAL_STAGE1_SHA.

## Etapa 0

| ID | Criterio | Boundary observado | Evidencia | Estado |
|---|---|---|---|---|
| E0-01 | Contratos y schema canónicos validan sin drift | LOCAL_REAL + CI_REAL | Schema 1.1.0, 46 roots, 112 definiciones, 231 refs, fixtures/negativos | PASS |
| E0-02 | Corpus suficiente, insuficiente e injection cubre rúbrica opcional | LOCAL_REAL + Docker CI | CLI, fixtures y target audit con outcomes esperados | PASS |
| E0-03 | Registry P01-P11 y gateway sin tools/red/memoria entre submissions | MOCK + CI_REAL | Gateway/pipeline tests y casos hostiles | PASS |
| E0-04 | Pipelines de actividad y submission explícitos | LOCAL_REAL + POSTGRESQL_REAL | Unit, E2E y estados persistidos | PASS |
| E0-05 | Planificador determinista antes de generación | LOCAL_REAL + CI_REAL | planning tests y dos procesos byte-identical | PASS |
| E0-06 | Validación estructural/contextual fail-closed | LOCAL_REAL + CI_REAL | IDs, anclas, fuentes, extras y diagnósticos negativos | PASS |
| E0-07 | Proveniencia y trazabilidad llegan a SelectedQuestion | LOCAL_REAL + CLOUD_REAL | contracts, review UI y recorrido sintético | PASS |
| E0-08 | Assessment y EvaluationGuide separados; exports derivados | LOCAL_REAL + CLOUD_REAL | JSON/HTML/PDF, Guide separada y delta model calls 0 | PASS |

## Etapa 1

| ID | Criterio | Boundary observado | Evidencia | Estado |
|---|---|---|---|---|
| E1-01 | Auth invitada, sesión propia y workspace privado | CLOUD_REAL | Supabase magic link, membership TEACHER, cookie/CSRF y anónimo 401 | PASS |
| E1-02 | Configuración editable hasta freeze; derivados no son inputs | LOCAL_REAL + CLOUD_REAL | ActivityEdit ETag, preflight y dificultad read-only | PASS |
| E1-03 | R2 privado, uploads acotados, sellado y TTL | CLOUD_REAL | CORS/lifecycle/privacy, PUT/HEAD/hash/sealed y expiración 300 s | PASS |
| E1-04 | P01-P05 producen blueprint versionado y aprobable | CLOUD_REAL | Job de actividad, P05 visible y aprobación académica | PASS |
| E1-05 | Blueprint review muestra restricciones completas y CAS | LOCAL_REAL + CLOUD_REAL | UI completa, derived difficulty, checks y versión aprobada | PASS |
| E1-06 | P06-P09 corren como Job durable de una submission | POSTGRESQL_REAL + CLOUD_REAL | Job real, close browser, claim único, 1/1/0 y fallo durable | PASS |
| E1-07 | Estado técnico y estado de dominio son distintos y recuperables | LOCAL_REAL + CLOUD_REAL | activities landing, Job SUCCEEDED y Assessment/Submission separados | PASS |
| E1-08 | Review muestra SelectedQuestion y exige evidence-first | LOCAL_REAL + CLOUD_REAL | CHOICE completa, receipts por fragmento, replay actor-bound, reload y API gate | PASS |
| E1-09 | Guide consultable; PDF/JSON sin model calls nuevas | CLOUD_REAL | Guide trazable, tres exports y delta tenant 36 a 36/job 4 a 4 | PASS |
| E1-10 | Ledger tipado y append-only | POSTGRESQL_REAL + CLOUD_REAL | P01-P09, resultados/costos y trigger model_calls append-only | PASS |
| E1-11 | React/FastAPI/Jobs/Supabase/R2/CI/CD/Terraform integrados | CI_REAL + CLOUD_REAL | source a digest/runtime, health/readiness, recovery y dos plans 0 | PASS |

## Gates transversales

| Gate | Evidencia | Estado |
|---|---|---|
| P0 | Ningún hallazgo | PASS |
| P1 | AUD-P1-01 a AUD-P1-11 CLOSED | PASS |
| PrincipalId | UUID Supabase y actores externos; Id interno estable | PASS |
| OpenAPI | DTOs runtime-validated, provider drift 500, consumer, snapshot, ref crawl y determinismo | PASS |
| OPEN_SHORT | Enum/semántica sin cambio; no OPEN_LONG ni límites | PASS |
| Dificultad | Derivada, coherente y solo lectura | PASS |
| CHOICE | Alternativas/best/rationale/misconception visibles al evaluador | PASS |
| Evidence-first | Receipt durable tenant/actor/version/fragment; replay reautoriza y no persiste URL | PASS |
| Guide | Trazabilidad y cannot_infer visibles | PASS |
| Tenant isolation | Repository/API/receipts y negativos cross-tenant | PASS |
| Logging | 2.881 entradas sin capabilities/credenciales/payload; 650 eventos por route template | PASS |
| PostgreSQL | PG16/17 y repetición sin limpieza | PASS |
| CI | Push 31199864090 y PR 31199869015 verdes sobre 6374e60; final se captura externamente | PASS |
| GitHub a Cloud Build | Repo/trigger/SA limitados; no direct deploy | PASS |
| Terraform | Imagen y rotación de refs revisadas; dos planes finales exit 0 | PASS |
| Supply chain | OCI revision, digest, provenance, scan y SBOM | PASS |
| Browser | CI E2E y candidato cloud nuevo con dos close/reopen desde shell | PASS |
| Model/P10 | mock y P10 off en runtime | PASS |
| Etapa 2 | Ninguna historia activada | PASS |

## Condición de publicación

La matriz no cambia el estado del PR. El PR #1 permanece draft, sin merge y sin
tag. La salida definitiva depende del manifest de FINAL_STAGE1_SHA y de una
auditoría de IA independiente que intente refutar cada gate.
