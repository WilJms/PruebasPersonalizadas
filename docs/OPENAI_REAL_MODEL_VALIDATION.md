# Validación del proveedor OpenAI real

Fecha de corte: 2026-08-09. Estado: smoke P11 Luna-low y canary P01
Luna-medium superados; canary P07 Luna-high fail-closed. Llamadas reales
históricas: **3**, exactamente una para P11, una para P01 y una para P07. La
investigación posterior de P07 es exclusivamente offline y no autoriza una
repetición.

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

Para P07, el `text.format.schema` exacto generado offline tiene 13.671 bytes y
SHA-256
`80692d48637f0ae2d7a7e6f05ab4e9b0a5e2d8eff6f1b103fbd14f62c482639a`.
El root obliga a incluir `schema_version`, `submission_id`, `opportunity_id`,
`context_mode`, `status`, `candidate` y `diagnostics`; los campos nullable
siguen siendo requeridos y usan `null`, como exige la documentación oficial de
Structured Outputs.

### Frontera exacta P07

| Capa | Invariantes efectivamente comprobadas |
|---|---|
| JSON Schema enviado al provider | Root objeto; propiedades requeridas; tipos, enums y const; nullability; patrones y longitudes de IDs/textos; límites de listas/números; uniones de `SourceLocator`; `additionalProperties=false`; `Diagnostic.details={}` |
| Solo Pydantic/model validators | `READY` exige candidate y todo status no-READY lo prohíbe; candidate pertenece a los IDs top-level; CLOSED prohíbe citations/course sources; fragmentos del anchor son subset de `candidate.evidence_ids`; reglas CHOICE/no-CHOICE; `course_source_ids` coincide exactamente con citations; orden de bbox/líneas |
| Solo validación contextual/cross-root | P07 exige trusted `CLOSED`; IDs top-level preservan request; template/dimensión/variante/operación preservados; evidence/source IDs están allowlisted; abstención incluye diagnostic; ninguna fuente de otra submission; outcome limitado por el manifest a `READY` o `REPLACEMENT_REQUIRED` |

El schema del provider es además más estricto en presencia que Pydantic: hace
requeridos campos con default canónico. A la inversa, JSON Schema no representa
los `model_validator` ni relaciones con el request/trusted context. Se demostró
offline que un campo requerido ausente falla ambas capas; `READY` con
`candidate=null` y un anchor fuera de `candidate.evidence_ids` cumplen el
schema del provider pero fallan Pydantic; IDs internamente coherentes pero
distintos del request pasan JSON Schema y Pydantic y fallan contexto.

Por tanto, el literal histórico de ledger `SCHEMA_INVALID` es amplio. En la
ruta estructural observada significa concretamente que
`QuestionGenerationResult.model_validate(raw_output)` lanzó
`ValidationError`; no demuestra que el JSON Schema estricto enviado al provider
fuera incumplido. Los fallos contextuales también usan ese literal canónico,
pero ahora quedan diferenciados mediante reason codes estables.

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

La investigación P07 demostró que el bloqueo de la ruta P11 reemplazaba la
excepción primaria y emergía sin sus ledgers. La corrección conserva el ledger
primario y emite `MODEL_OUTPUT_VALIDATION_FAILED` con dos campos separados:
`primary_failure` (`OUTPUT_PYDANTIC_VALIDATION_FAILED`, fase, engine, tipos y
paths saneados, más estado del schema provider) y `repair_disposition`
(`BLOCKED_BY_CANARY_POLICY` en el harness). Los errores Pydantic se reducen a
tipo/path, con máximo 32 entradas; no se conservan `input`, `ctx`, mensajes,
valores, claves desconocidas ni texto generado. P11 continúa en cero en la
frontera canary.

## Secuencia de aceptación

| Gate | Estado |
|---|---|
| Matriz, schemas, fake transport, fallos, retry, presupuesto y ledger | PASS offline |
| Golden set sintético 20 casos | PASS offline; 0 network/0 billable |
| Proyecto, spend limit y clave privada | proyecto verificado; secret versión 1 `enabled`, payload no inspeccionado |
| Perfil Luna-only y regresión offline | PASS; 456 passed/16 skips PG explícitos, PG16/17, golden 20/20, frontend/browser/Docker/Terraform verdes |
| Smoke P11 sintético, una llamada | `OPENAI_REAL_SMOKE_PASS`; 1 request, retries 0/0/0 |
| Canary P01 Luna-medium | PASS real; `READY`, 1 request, USD 0.00145745 calculados |
| Canary P07 Luna-high | FAIL real fail-closed; 1 request, output Pydantic inválido, P11 0, USD 0.00327560 calculados |
| Investigación P07 provider/Pydantic | PASS offline; schema exacto fijado, pérdida de ledger corregida, clases provider/Pydantic/contexto reproducidas sin contenido |
| Golden set real sintético | pendiente de aprobación y presupuesto separados |
| Calidad/latencia/costo y P0/P1 | P0=0; P1 histórico P07 permanece abierto hasta una eventual recanary autorizada |
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
