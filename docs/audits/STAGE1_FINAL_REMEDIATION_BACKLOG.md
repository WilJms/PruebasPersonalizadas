# Backlog residual real después de Etapa 1

Fecha de corte documental: 2026-08-07.

P0 abiertos: 0. P1 abiertos: 0. No existe deuda P1 aceptada. Este archivo solo
contiene deuda P2/P3 que no bloquea E0/E1 y no autoriza implementar Etapa 2.

## AUD-P2-04 — Copy institucional de privacidad

- **Estado:** ACCEPTED_DEBT.
- **Fuente:** F-001, MVP de login y arquitectura de privacidad.
- **Motivo:** la UI declara invitación, workspace y entorno experimental, pero
  no existe texto institucional autorizado con finalidad legal, retención y
  canal de contacto. Inventarlo durante una remediación técnica crearía una
  promesa potencialmente falsa.
- **Riesgo residual:** aviso contextual menos completo del deseable antes del
  login.
- **Por qué no bloquea E0/E1:** el entorno es privado, de una persona
  autorizada, con datos sintéticos; controles técnicos de aislamiento,
  minimización, retención R2 y no logging sí están implementados.
- **Cierre futuro:** propietario entrega copy/política/contacto canónicos y se
  valida reflow, contraste y accesibilidad. No requiere historia E2.

## AUD-P2-15 — Lista y reemisión visual de exports después de reload

- **Estado:** ACCEPTED_DEBT.
- **Fuente:** Plan E1-09/E1-11 y auditoría técnica.
- **Motivo:** snapshots y objetos exportados son durables, y el usuario puede
  recrear los tres exports determinísticamente sin model calls. La UI no lista
  automáticamente exports históricos ni reemite su capability después de
  reload.
- **Riesgo residual:** fricción de usabilidad y operación repetida; no pérdida
  del Assessment, Guide, snapshot, objeto ni trazabilidad.
- **Por qué no bloquea E0/E1:** el recorrido obligatorio exporta Assessment
  PDF, Guide PDF y JSON; hashes/tamaños coinciden y model-call delta es cero.
  No se persisten URLs firmadas.
- **Cierre futuro:** endpoint/lista tenant-scoped que reemita una capability
  corta para un export aprobado existente, con CSRF/idempotencia y sin regenerar
  contenido. Debe abrirse mediante un gate posterior explícito.

## AUD-P2-16 — Fuentes históricas mezclan terminología E2

- **Estado:** ACCEPTED_DEBT.
- **Fuente:** F-021/F-022, workbook/MVP histórico, Plan E2 y AGENTS.md.
- **Motivo:** algunas fuentes inferiores antiguas conservan bulk approval,
  retry/cancel, acciones y métricas bajo una etiqueta amplia de MVP. Reescribir
  historia contractual podría borrar requerimientos futuros.
- **Riesgo residual:** un lector que ignore la jerarquía puede interpretar E2
  como parte del cierre actual.
- **Por qué no bloquea E0/E1:** Plan, ADR-030 a ADR-034 y AGENTS.md son
  explícitos; tests, rutas, migración e infraestructura confirman que esas
  capacidades no están activas.
- **Cierre futuro:** edición editorial coordinada que etiquete cada historia por
  etapa sin cambiar semántica ni habilitar código.

## AUD-P3-01 — Deprecación Starlette TestClient/httpx

- **Estado:** ACCEPTED_DEBT.
- **Fuente:** warning reproducido por pytest y locks actuales.
- **Motivo:** la combinación fijada es funcional y todas las pruebas pasan.
  Forzar un upgrade solo para silenciar un warning puede romper FastAPI o la
  API de TestClient sin beneficio runtime.
- **Riesgo residual:** una futura actualización de dependencias podría exigir
  migrar el adaptador de tests.
- **Por qué no bloquea E0/E1:** no afecta producción, no oculta excepciones y
  las suites locales/CI/PostgreSQL permanecen verdes.
- **Cierre futuro:** actualizar el conjunto FastAPI/Starlette/httpx de forma
  coordinada, regenerar locks y repetir toda la matriz.

## Resumen de clasificación

| Clasificación | Cantidad |
|---|---:|
| CLOSED P1 | 11 |
| CLOSED P2 | 14 |
| ACCEPTED_DEBT P2 | 3 |
| CLOSED P3 | 1 |
| ACCEPTED_DEBT P3 | 1 |
| BLOCKED | 0 |
| NOT_REPRODUCED | 0 |

No hay deuda residual que permita degradar el gate, y ninguna entrada de este
backlog constituye autorización para batch, retry/cancel general, actions,
bulk approval, feedback, métricas E2, OCR, LMS, grading o AI detection.
