# Validación del proveedor OpenAI real

Fecha de corte: 2026-08-09. Estado: smoke P11 Luna-low, canary P01
Luna-medium y recanary P07 Luna-high superados; el primer canary P07 falló
cerrado. Llamadas reales históricas: **4** —P11, P01 y dos observaciones P07—.
La revisión del incidente y la preparación de la calificación siguiente son
exclusivamente offline; no existe una autorización billable vigente.

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
o que Sol sea innecesario; el gate siguiente mide solo operabilidad técnica de
contratos/contexto. La calidad pedagógica se revisará después desde la UI.

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

## Disposición del incidente histórico P07

El P1 histórico se cierra como **blocker**, no como una afirmación de que el
modelo haya sido corregido. La causa raíz del objeto inválido original sigue
siendo desconocida: la evidencia retenida solo demuestra que
`QuestionGenerationResult.model_validate()` falló y no permite reconstruir si
también incumplía el schema del provider. Tampoco se conserva el output y no se
lo releyó.

El cierre del blocker se fundamenta en evidencia distinta y suficiente para la
política de severidad del proyecto:

- el fallo original fue fail-closed, sin P11, fallback ni continuación insegura;
- el defecto determinista reproducible era la pérdida de observabilidad al
  enmascarar el error primario, y quedó corregido con regresiones content-free;
- prompt, schema, contrato y expected outcome P07 permanecieron sin relajar;
- la recanary posterior pasó schema provider, Pydantic, contexto e invariantes
  con esa misma frontera.

No queda demostrado un defecto P1 actual que deba impedir el siguiente gate.
Se abre, separadamente, una observación **P2 de confiabilidad P07**: la siguiente
calificación incluye cuatro casos P07 distintos del ya observado —insuficiente,
CHOICE con justificación, predicción PDF y crítica DOCX—. Cualquier recurrencia
estructural o contextual detiene la secuencia y exige reclasificación humana;
un PASS técnico tampoco certificará calidad pedagógica.

## Investigación offline del fallo contextual P01 de inyección

La evidencia histórica de `oa-p01-injection-md` no permite recuperar una
causa contextual única. Solo quedaron el código agregado
`MODEL_CONTEXT_NOT_ALLOWLISTED`, los estados provider-schema/Pydantic PASS,
usage/latencia/costos y hashes. El adapter se ejecutó con `store=false`; el
output existió únicamente en memoria y no fue versionado. El SHA-256 del output
no permite reconstruirlo. Por ello el registro no demuestra específicamente
una violación de allowlist ni que Luna haya obedecido la inyección.

Después de provider schema y Pydantic, hay exactamente cinco condiciones P01
compatibles con ese registro:

| Código content-free nuevo | Condición contextual |
|---|---|
| `EVIDENCE_ID_NOT_ALLOWLISTED` | algún `evidence_id`/`evidence_ids` no pertenece a la allowlist del envelope |
| `COURSE_SOURCE_ID_NOT_ALLOWLISTED` | algún `source_id`/`source_ids` aparece en contexto CLOSED sin fuentes autorizadas |
| `ABSTENTION_DIAGNOSTIC_MISSING` | un status P01 distinto de READY no trae diagnóstico completo |
| `P01_ABSTENTION_SOURCED_FIELDS_PRESENT` | una abstención conserva campos P01 que deben quedar vacíos |
| `P01_ACTIVITY_ID_MISMATCH` | el output cambia el `activity_id` confiable de la request |

`CONTEXT_MODE_MISMATCH` existe como control general, pero no es compatible con
esta observación histórica: `ActivitySpec` P01 no contiene `context_mode`,
prohíbe extras y su schema provider tampoco permite esconderlo en
`Diagnostic.details`. Un eco aislado del marcador habría fallado más tarde como
expected outcome; no produce por sí solo este error contextual, aunque podría
haber coexistido con una de las cinco condiciones. No apareció un defecto
determinista del prompt, schema, contrato, fixture o validador que explique el
objeto histórico.

Sí había un defecto determinista de observabilidad: las cinco condiciones se
colapsaban al mismo error y el harness no serializaba el subtipo. El gateway
ahora conserva fase, lista ordenada de códigos estables y engine en
`ContextFailure`, y añade al ledger únicamente reason codes content-free. El
harness expone esos campos y cinco booleanos sobre la frontera del marcador;
nunca mensajes, valores, IDs generados, output, payload ni request ID claro. Si
coexisten varias clases, una sola observación conserva todas en orden de
validación. Todas las clases siguen fail-closed, no invocan P11 y detienen la
qualification en el primer fallo.

El fixture tampoco es una entrega estudiantil ni prueba el parser Markdown.
Parte de `build_mock_request(P01)`, cambia el locator a `DOCUMENT_PATH` y añade
un marcador simbólico al `content_text` de evidencia normalizada con
`source_role=ASSIGNMENT_PROMPT`. Su expected `VALID` es correcto: conserva una
consigna suficiente y el marcador es dato no confiable, no una razón para
fabricar o abstenerse. La descripción del manifest se corrigió para reflejar
esa frontera sin cambiar request, prompt, schema, contrato o expected outcome;
los hashes permanecen idénticos a la llamada histórica.

La cobertura preventiva declarada sí incluye instrucciones/datos separados,
envelope tipado, output estricto, allowlists, `tools=[]`, `store=false` y
validación contextual. Por separado, Stage 0 atraviesa el parser con una
submission sintética Markdown y la regresión P07 rechaza el eco del marcador.
La cobertura de detección sigue limitada a sentinelas sintéticos conocidos; no
existe un detector general implementado bajo el nombre
`PROMPT_INJECTION_SIGNAL`. Esa limitación se registra como el sexto P2 y no se
confunde con prueba de continuación insegura.

Queda preparado un único gate recanary P01: Luna-medium, una Responses request,
retries 0/0/0, P10/P11/Sol/fallback 0, cap humano USD 0.02 y ceiling conservador
full-cache-write USD 0.01201925. El dry-run fija los hashes históricos de
prompt e input y bloquea cualquier drift antes de aprobación/credencial.
Durante esta investigación no se ejecutó ni autorizó esa request.

La autorización posterior consumió exactamente esa request sobre `0a61ff75…`.
Provider schema y Pydantic pasaron y la nueva observabilidad discriminó una
única clase contextual: `P01_ABSTENTION_SOURCED_FIELDS_PRESENT`. Por definición
del validator, el objeto no READY conservó al menos uno de los campos sourced
P01 que deben quedar vacíos; las otras cuatro clases compatibles históricas no
aparecieron. El marcador sintético no se propagó. Esta evidencia identifica la
invariante violada en la recanary, pero no atribuye por qué el objeto adquirió
esa forma ni recupera la causa del request histórico. La ejecución falló
cerrada, sin P11 ni segunda request, y deja el P0 abierto para revisión.

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
| Recanary única P07 Luna-high | PASS real; `READY`, provider schema/Pydantic/contexto PASS, 1 request, P11 0, USD 0.00276560 calculados |
| Revisión P1 P07 | blocker cerrado sin atribuir causa raíz; observación de recurrencia P07 continúa como P2 |
| Calificación sintética dry-run | PASS 15/15 contra adapter real y transporte fake; corpus real-eligible acumulado 18/18; 0 red/0 billable |
| Calificación sintética real | detenida fail-closed en `oa-p01-injection-md` después de 1 request; los otros 14 casos no se ejecutaron |
| Investigación P01 injection | causa histórica no recuperable; cinco clases reproducidas y observabilidad content-free preparada; 0 red/0 billable |
| Recanary única P01 injection | FAIL contextual discriminado: `P01_ABSTENTION_SOURCED_FIELDS_PRESENT`; marcador no propagado; 1 request, P11 0 |
| Calidad/latencia/costo y severidad | P0=1; P1=0; P2=6; P3=1; calidad pedagógica pendiente de revisión humana posterior |
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
