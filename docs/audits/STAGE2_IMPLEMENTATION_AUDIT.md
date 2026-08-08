# Auditoría de implementación — Etapa 2

Fecha: 2026-08-07. Baseline:
`80dd57dbf38d56929c307eca956833c31e53bf33`. Rama:
`codex/stage2-experimental-mvp`.

## Método y clasificación

Se contrastó el candidato con E2-01 a E2-15, contratos Pydantic, ADR, Plan y
MVP. Se ejecutaron pruebas positivas, negativas, fault injection y carreras.
`LOCAL_REAL` y `POSTGRESQL_REAL` describen ejecuciones observadas; `MOCK_MODEL`
declara el proveedor; `CI_REAL` y `CLOUD_REAL` solo se completan con IDs reales.

## Trazabilidad de implementación

| Área | Implementación principal | Evidencia local | Estado |
|---|---|---|---|
| Contratos 1.2 | `specification/models_v1.1(1).py`, schema generado y fixtures | 53 roots, 140 defs, 274 refs; E1 estructuralmente compatible | PASS |
| Multi-submission/migración | `repository.py`, migración 003 y recovery | PG16/17 upgrade, datos preservados, carrera y rollback lógico | PASS |
| Parsers | `parsers/service.py`, `sandbox.py`, `sandbox_worker.py` | 57 pruebas; TXT/MD/PDF/DOCX, MIME, límites, active content | PASS |
| Jobs | `web/workflows.py`, `web/stage2.py`, `repository.py` | retry/cancel/resume, lease, CAS, stage reuse y negativos | PASS |
| Review/regeneración | `web/stage2.py` | ACCEPT/REJECT/EDIT/REGENERATE, exactly N, reserva y lineage | PASS |
| Coverage/metrics/feedback | contratos, repository y rutas Stage2 | HTTP/provider/consumer tests y aislamiento | PASS |
| Exports | rutas Stage2 y renderers E1 reutilizados | siete tipos, snapshots, replay y model delta 0 | PASS |
| Bulk approval | Stage2 service + persistencia append-only | partición exacta, exclusiones, roles, idempotencia | PASS |
| Frontend | `ActivityLabPage`, review, job control y API tipada | 32 tests, build, axe/teclado/390 px y Playwright | PASS |
| Deploy | Cloud Build, Terraform, Docker, CI, readiness | Validación local; ejecución del SHA final pendiente | NOT_VERIFIED_EXTERNAL |

## Auditoría adversarial y remediación

La primera implementación no se aceptó como cierre. Las rondas adversariales
reprodujeron, corrigieron y revalidaron, entre otros:

- fan-out ilimitado de retry/resume y consumo duplicado de un attempt;
- carreras de cancelación, dispatch ambiguo y jobs RUNNING huérfanos;
- resume ASSEMBLE que repetía trabajo o fallaba por lineage P09;
- provider permanente marcado retryable y clases PRECONDITION/VALIDATION
  inalcanzables;
- EDIT que podía cambiar la oportunidad o duplicarla, y REGENERATE `SELECTED`
  con summary incoherente;
- presupuesto de regeneración evadible por fallos y retry de QUESTION_ACTION
  sin descriptor durable después de crash;
- aprobación individual no atómica y bulk con autorización/partición
  incompletas;
- parser hostil inline, rechazo PDF convertido en 500 y upload rechazado que
  ocupaba el slot para siempre;
- readiness que ignoraba tablas/constraints/policies/triggers E2;
- recovery que permitía un INSERT confirmado después del guard y luego
  eliminaba su tabla;
- lista frontend sin assessment elegible, upload duplicable y overflow móvil.

Las correcciones terminan en una suite completa `407 passed, 16 skipped`, más
ejecuciones PG16/17 de los grupos omitidos y matrices frontend/browser verdes.

## Resultado local

| Severidad | Abiertos |
|---|---:|
| P0 | 0 |
| P1 | 0 |
| P2 | 3 |
| P3 | 1 |

No se emite todavía cierre externo: CI, migración Supabase, Cloud Build,
Terraform y cloud E2E permanecen `NOT_VERIFIED` hasta existir evidencia ligada
al SHA final. La deuda se detalla en
[STAGE2_REMEDIATION_BACKLOG.md](STAGE2_REMEDIATION_BACKLOG.md).
