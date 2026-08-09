# Validación del proveedor OpenAI real

Fecha de corte: 2026-08-09. Estado: primer smoke P11 Luna-low aprobado y
superado; canaries P01 Luna-medium y P07 Luna-high preparados y demostrados
offline, pendientes de un gate humano nuevo. Llamadas reales históricas: **1**,
exclusivamente P11; llamadas reales de estos canaries: **0**.

## Perfil vinculante `LUNA_BASELINE_V1`

| Prompts | Modelo explícito | Esfuerzo |
|---|---|---|
| P01, P02 | `gpt-5.6-luna` | `medium` |
| P03, P04, P05, P06, P07, P08, P09 | `gpt-5.6-luna` | `high` |
| P10 | sin ruta; deshabilitado | n/a |
| P11 | `gpt-5.6-luna` | `low` |

Los IDs se envían literalmente. No hay chooser, alias propio, fallback,
escalamiento silencioso ni snapshot fechado inventado. El ledger conserva el
modelo solicitado y el modelo efectivo observado; una identidad efectiva
incompatible falla cerrada. ADR-035 conserva la decisión P11 Luna-low y
ADR-036 registra el baseline Luna-only.

La matriz mixta anterior permanece como historia y candidato comparador futuro,
pero no es callable ni fallback. Este experimento no afirma que Luna sea óptimo
o que Sol sea innecesario; mide primero si Luna mantiene calidad suficiente.

## Boundary de request y output

Cada llamada representa una sola tarea semántica y usa Responses API con:

- instrucciones de sistema y desarrollador versionadas;
- un `ModelTaskEnvelope` ya validado y serializado como JSON canónico;
- solo evidencia allowlisted y previamente parseada; nunca archivos raw;
- `text.format` con JSON Schema estricto derivado de Pydantic;
- `store=false`, `background=false`, `tools=[]`, parallel tool calls false,
  truncation disabled y service tier default;
- esfuerzo explícito; temperatura omitida por falta de compatibilidad oficial
  documentada con estas rutas de reasoning;
- timeout entre 5 y 300 segundos y retries internos del SDK iguales a cero;
- preflight que contabiliza prompt, envelope y schema completos, el techo de
  retries y el saldo durable del presupuesto agregado por job.

La transformación de schema no redefine contratos: convierte `oneOf` a
`anyOf`, quita defaults/discriminadores no admitidos, marca las propiedades del
objeto como requeridas y fija `additionalProperties=false`. P11 especializa
`repaired_output` al root objetivo. El único objeto libre del contrato,
`Diagnostic.details`, se estrecha a `{}` en esta frontera porque el subset
estricto no admite mapas arbitrarios; `code`, mensaje e IDs permanecen
tipados y el contrato canónico no se redefine. El resultado se valida primero contra su
modelo Pydantic canónico y luego contra contexto, IDs, grounding y reglas.

P11 tiene una sola oportunidad y solo corrige JSON, tipos o enums. Nunca
repara evidencia, fuente, IDs, grounding, seguridad, suficiencia o significado.
Una segunda violación estructural queda bloqueada.

## Fallos y observabilidad

Timeout, conexión, 408/409/5xx y rate limit transitorio pueden consumir como
máximo los retries acotados del gateway. Auth, autorización, modelo ausente,
quota/budget, request permanente, refusal/safety, respuesta incompleta, tool
output inesperado y modelo efectivo incompatible no se reintentan ciegamente.
Todo mensaje externo se reduce a códigos estables; texto del proveedor o del
estudiante no llega a logs.

Cada ledger incluye hashes de prompt/input/output/request-id, ruta completa,
versión del SDK, esfuerzo, intento, latencia, tokens input/cache-write/cache-hit/
output/reasoning, costo estimado/observado y códigos de política. No conserva
payload, output, clave ni request-id en claro.

## Secuencia de aceptación

| Gate | Estado |
|---|---|
| Matriz, schemas, fake transport, fallos, retry, presupuesto y ledger | PASS offline |
| Golden set sintético 20 casos | PASS offline; 0 network/0 billable |
| Proyecto, spend limit y clave privada | proyecto verificado; secret versión 1 `enabled`, payload no inspeccionado |
| Perfil Luna-only y regresión offline | PASS; 456 passed/16 skips PG explícitos, PG16/17, golden 20/20, frontend/browser/Docker/Terraform verdes |
| Smoke P11 sintético, una llamada | `OPENAI_REAL_SMOKE_PASS`; 1 request, retries 0/0/0 |
| Canary P01 Luna-medium | PASS offline contra transporte fake; real pendiente de autorización |
| Canary P07 Luna-high | PASS offline contra transporte fake; real pendiente de autorización |
| Golden set real sintético | pendiente de aprobación y presupuesto separados |
| Calidad/latencia/costo y P0/P1 | pendiente de evidencia real |
| Build, digest y deploy real del worker | pendiente de gate posterior |

El camino interactivo de re-revisión P05 que aún reside en el Service no se
presenta como real: al anunciar un worker real queda bloqueado hasta migrar esa
acción a un job durable. El pipeline worker y los evals aislados sí tienen ruta
P05 explícita. Esta limitación funcional es P2 y no autoriza entregar un review
mock dentro de un recorrido declarado OpenAI.

Fuentes oficiales: páginas de
[`gpt-5.6-sol`](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[`gpt-5.6-terra`](https://developers.openai.com/api/docs/models/gpt-5.6-terra) y
[`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[precios](https://developers.openai.com/api/docs/pricing),
[Responses](https://developers.openai.com/api/docs/guides/responses),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
y [manejo de errores](https://developers.openai.com/api/docs/guides/error-codes).
