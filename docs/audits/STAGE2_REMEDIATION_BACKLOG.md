# Backlog de remediación — Etapa 2

Fecha: 2026-08-07; evidencia externa observada hasta 2026-08-08 UTC. Solo
deuda P2/P3 puede sobrevivir al cierre técnico. CI o cloud fallidos se elevan
a P1 y bloquean el estado final.

## Cerrados durante la auditoría

| ID | Severidad | Hallazgo | Estado |
|---|---|---|---|
| E2-AUD-001 | P0 | retry/resume fan-out y bypass de max attempts | CLOSED |
| E2-AUD-002 | P0 | recovery podía eliminar un commit concurrente | CLOSED |
| E2-AUD-003 | P1 | EDIT/candidate cross-question y duplicación de oportunidad | CLOSED |
| E2-AUD-004 | P1 | cancel/dispatch dejaban Assessment y estado divergentes | CLOSED |
| E2-AUD-005 | P1 | resume ASSEMBLE no reutilizaba el corte correcto | CLOSED |
| E2-AUD-006 | P1 | QUESTION_ACTION transient sin retry/crash recovery | CLOSED |
| E2-AUD-007 | P1 | regeneración SELECTED y presupuesto de fallos incoherentes | CLOSED |
| E2-AUD-008 | P1 | aprobación individual no atómica y bulk role guard incorrecto | CLOSED |
| E2-AUD-009 | P1 | parser hostil inline/rechazo 500/slot irrecuperable | CLOSED |
| E2-AUD-010 | P1 | job RUNNING sin lease/reaper | CLOSED |
| E2-AUD-011 | P1 | readiness incompleta para schema E2 | CLOSED |
| E2-AUD-012 | P1 | UI batch sin assessment elegible y overflow móvil | CLOSED |

## Abiertos aceptables

| ID | Severidad | Deuda y control | Gate de salida |
|---|---|---|---|
| E2-DEBT-001 | P2 | ClamAV ausente; sandbox/libmagic/seccomp/limits compensan solo fixtures sintéticos | AV operativo o compensación formal antes de datos reales |
| E2-DEBT-002 | P2 | No existe corpus PDF/DOCX real autorizado ni política legal de retención | Autoridad humana provee corpus/política antes de datos reales |
| E2-DEBT-003 | P2 | Mock no valida calidad/latencia/costo semántico de proveedor real | Gate posterior explícito, presupuesto y golden set autorizado |
| E2-DEBT-004 | P3 | `StarletteDeprecationWarning` en TestClient | Migrar cuando el stack soporte el adaptador nuevo |

## Conteo

| Severidad | Abiertos |
|---|---:|
| P0 | 0 |
| P1 | 0 |
| P2 | 3 |
| P3 | 1 |

## Validación externa del backlog

La CI del runtime pasó 7/7 tanto en push (`31232751301`) como en PR
(`31232752740`). Migración 003, Cloud Build/digest, Service/Job,
health/readiness, Terraform apply y dos planes no-drift pasaron en cloud. El
manifest sintético completó 38/38 y el browser real pasó 1440/390 px,
cierre/reapertura, consola limpia y sin overflow global. El cierre operacional
dejó Auth efímero 0, jobs activos 0, capabilities persistidas 0 y errores/fugas
de logs 0/0. No surgió ningún P0/P1 nuevo.

Los pasos 12 y 33–36 usaron `CONTROLLED_ADMIN_SEED`; no se contabilizan como
fallos naturales del proveedor. La provenance SLSA 3 v1 y el scan
`FINISHED_SUCCESS` fueron observados; SBOM quedó `NOT_OBSERVED / NO CLAIM`.

Los P2 no autorizan datos reales, modelos reales ni Etapa 3. No bloquean una
validación controlada exclusivamente sintética en modelo mock. P10 continúa
deshabilitado y ClamAV continúa ausente.
