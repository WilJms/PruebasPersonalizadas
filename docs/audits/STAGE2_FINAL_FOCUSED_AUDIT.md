# Auditoría final focalizada — Etapa 2

Fecha: 2026-08-08 (America/Santiago). Esta auditoría cubre únicamente el
checkpoint pre-merge de Etapa 2. No autoriza el merge, modelos reales, datos
estudiantiles reales, P10 ni Etapa 3.

## Método e identidad observada

La primera pasada fue estrictamente `READ-ONLY`: identidad Git/PR/CI, contratos,
migración y aislamiento multi-submission, jobs, review, bulk, parser, seguridad
y consistencia documental. Solo después de clasificar los defectos se corrigió
el mínimo necesario y se ejecutó una regresión completa.

| Campo | Valor observado antes de corregir |
|---|---|
| Baseline/base PR | `80dd57dbf38d56929c307eca956833c31e53bf33` / `main` |
| Runtime cloud probado | `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` |
| Head bootstrap | `bdb44696ca907390521ad05a405b03e21dc6a490` |
| Rama/PR | `codex/stage2-experimental-mvp` / draft `#2` |
| Mergeabilidad inicial | `MERGEABLE`, `CLEAN` |
| CI del head bootstrap | push `31233969228` y PR `31233971682`: 7/7 `SUCCESS` cada uno |
| Modelo/P10/datos | `mock` / `false` / exclusivamente sintéticos |

El rango `44b9483…bdb4469` modifica exactamente nueve archivos y todos están bajo
`docs/`; no contiene cambios de código, contratos, migraciones, frontend ni
deploy. El rango baseline→head contiene los commits E2 documentados en el PR.

## Resultado de la pasada focalizada

Se reprodujeron cuatro defectos P1 capaces de invalidar el cierre técnico. No
se encontró ningún P0.

| ID | Severidad | Hallazgo | Corrección y prueba |
|---|---|---|---|
| E2-FINAL-001 | P1 | El replay idempotente de upload firmaba una clave fabricada terminada en `/upload`, distinta de la reserva aleatoria original. Después de `COMPLETE` o `REJECTED` además intentaba proyectar un estado incompatible con el DTO. | El descriptor durable conserva la clave no-capability exacta, valida su scope, nunca firma la clave sellada y reconstruye la proyección histórica `PENDING`. Pruebas verifican replay antes/después de sellar, ausencia de URL/capability persistida y preservación del objeto sellado. |
| E2-FINAL-002 | P1 | Cancelar un job `ACTIVITY` dejaba la actividad en `QUEUED` sin ruta funcional de reejecución. | La cancelación terminal bloquea el aggregate y lo devuelve a `DRAFT`, conservando `StageRun` reutilizable solo bajo hashes/versiones compatibles. Regresión cooperativa añadida. |
| E2-FINAL-003 | P1 | Métricas sumaban `attempt - 1` por job, produciendo conteo triangular, y trataban `RESUME` como retry por etapa. | Se cuentan únicamente controles `RETRY/APPLIED` tenant/activity-scoped; por etapa se atribuye el retry al job resultante. Prueba 1→2→3 más un `RESUME` exige total 2 y retry por etapa 1. |
| E2-FINAL-004 | P1 | Una cancelación concurrente de `QUESTION_ACTION` podía persistir o sobrescribir una acción fallida después de que el job ya quedara cancelado. | El job se bloquea y la cancelación se completa dentro de la misma transacción antes de escribir acción/versiones. La prueba cancela durante P07 y exige `409 JOB_CANCELLED`, job `CANCELLATION`, historial vacío y Assessment sin cambio. |

También se corrigió la contradicción documental conocida de
`PARSER_SECURITY_E2.md`: el digest cloud sí fue verificado. La corrección no
levanta el gate de antivirus/compensación formal; datos reales siguen
bloqueados.

## Contratos y regresión final local

| Frontera | Resultado |
|---|---|
| Contratos/fixtures | `PASS`; bundle `1.2.0`, 53 roots, 140 defs, 274 refs, 8 fixtures |
| Schema/OpenAPI/TypeScript | regenerados sin drift; SHA-256 `6cefb26e…`, `766bbaf0…`, `50e9c660…` |
| Backend completo | 410 passed, 16 skipped por ausencia de PostgreSQL local, 1 warning conocido |
| Cobertura | 410 passed, 16 skipped; 79% global |
| Recovery/migración local sin URL PG | 146 passed, 9 skipped explícitos |
| PostgreSQL real | evidencia previa PG16/17 en CI permanece vigente; no se simula como ejecución local |
| Parser/sandbox | 57 passed |
| Deploy estático | 11 passed |
| Secret scan | 275 archivos versionables; 0 secretos de alta confianza |
| Stage 0 | sufficient, insufficient e injection `PASS`; ejecución determinista independiente sin diff |
| Frontend | typecheck, 32/32 tests, build de 87 módulos y audit 0 vulnerabilidades |
| Playwright | recorrido E1 1/1 y E2 2/2, incluido viewport 390 px |
| Terraform | fmt, init sin backend y validate `PASS` |
| Docker local | daemon no disponible; la frontera queda cubierta por CI, sin reclamo local nuevo |

Los grupos PostgreSQL omitidos requieren `CVA_TEST_POSTGRES_URL` y no se
reinterpretan como PASS local. La evidencia histórica PG16/17, cloud y Docker
está ligada a `44b9483…`; las cuatro correcciones de esta auditoría quedan
ligadas al nuevo candidato local/CI y no se presentan como ya desplegadas.

## Revisión cloud/browser no mutante

Sobre el runtime desplegado se abrió el lote E2 y la pestaña Métricas en desktop
y 390×844. El DOM fue significativo, la interacción respondió, no hubo
errores/warnings de consola ni overlay, y a 390 px
`innerWidth = scrollWidth = bodyScrollWidth = 390`. Esta comprobación confirma
el runtime ya desplegado; no acredita despliegue de las correcciones nuevas.

## Deuda y dictamen

| Severidad | Abiertos al checkpoint |
|---|---:|
| P0 | 0 |
| P1 | 0 |
| P2 | 3 |
| P3 | 1 |

Los P2 son ClamAV/compensación pendiente, corpus/política de retención real no
autorizados y validación semántica/latencia/costo con proveedor real pendiente.
El P3 es `StarletteDeprecationWarning` del adaptador de tests.

El dictamen técnico es apto para el checkpoint pre-merge después de que el
commit candidato tenga CI final verde, el paquete externo durable quede
inventariado y el PR siga mergeable. El merge continúa reservado a una nueva
autorización humana explícita.
