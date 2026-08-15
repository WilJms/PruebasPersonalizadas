# Validación del proveedor OpenAI real

> **Estado ADR-037 (2026-08-14):** las validaciones, recanaries y gates
> descritos debajo son evidencia histórica no canónica. Se conservan con sus
> hashes y resultados originales, pero no seleccionan modelo, no mantienen una
> recanary abierta y no autorizan provider, build o deploy. El objetivo actual
> está en `PIPELINE_AUTHORITY.md`.

**Estado Fase 4 (2026-08-15):** P06 `1.1.6` se validó únicamente con adapter
mock y dry-runs offline. Su provider root pasó a `EvidenceMappingModelDraft`,
sin cambiar modelo/ruta/reasoning ni abrir una recanary. Hubo cero requests,
resoluciones de secreto, transporte o costo; todas las cifras y receipts reales
inferiores permanecen históricos e inalterados.

Fecha de corte: 2026-08-11. Estado: el E2E del digest `sha256:04032e44…`
se detuvo en P04 1.1.8 por `EVIDENCE_ID_NOT_ALLOWLISTED`. P04 1.1.9 está
remediado y ligado a un dry-run acoplado; en ese corte histórico la evidencia
quedó en **16/18** hasta una recanary real nueva.

## Historial: P04 v1.1.9→P05 v1.1.5 recanary pendiente en su gate original

La actividad `act_8187dcc2159d5462d99a` usó exclusivamente
`assignment.md`/`rubric.md` sintéticos. P01-P03 pasaron y seis decisiones
recomendadas quedaron persistidas. La reanudación llamó sólo P04: el proveedor
devolvió schema válido, pero `diagnostics[].evidence_ids` incluyó un ID no
perteneciente a los dos `ev_*` autorizados. El gateway registró
`CONTEXT_FAILURE_OUTPUT_EVIDENCE_ID_NOT_ALLOWLISTED`, stage
`FAILED/SECURITY`, Cloud Run exit 1 y cero retries. El ledger conserva sólo
metadatos content-free; P05 y toda mutación posterior quedaron en cero.

El E2E suma 4 Responses y USD 0.02256005; P04 representa 1 request y
USD 0.01308515. P10/P11/Sol/fallback/retries son cero. P04 1.1.9 no elimina ni
normaliza el diagnóstico inválido: instruye que `evidence_ids` sólo acepte IDs
exactos de `activity_spec/rubric_spec`, que IDs de otras clases nunca ocupen ese
campo y que la lista quede vacía si no hay evidencia autorizada; `source_ids`
queda análogamente vacío en CLOSED sin fuentes.

El gate fijo reproduce un outcome, dos criterios sin niveles/pesos, seis
decisiones exactas, N=1, diez minutos, OPEN_SHORT/STRUCTURED_BULLETS, dos
evidence IDs y cero source IDs. El dry-run P04→P05 pasa schema/Pydantic/contexto
y controles acoplados con 2 fake Responses, 0 red, P10/P11/Sol/fallback/retries
0. P04 queda ligado a prompt/input
`sha256:d34145db85d8f5dfed5e6f278e9c78f5e564e5eb589e1773534c8b02c819f5f8` /
`sha256:0cacc7b7aa151c6910592949edae03d9d0e8e1250ba171227f76265322e14bc2`;
ceiling agregado USD 0.05046625 bajo cap USD 0.06. El gate real permanece
abierto una sola vez y sin afirmar PASS antes de observarlo.

## Historial: 18/18 desplegado antes del stop fresco

El SHA `88416b522414f316613bea96ad08687e8a335a38` fue construido una sola
vez por `441be72d-04ae-46e9-b150-6eec1032c8d6`, con estado
`SUCCESS/VERIFIED`, y publicado/desplegado bajo
`sha256:d31899535c76b08ee79163479530b044783b73956c6fe228a01a3e603008893d`.
Artifact Registry coincidió con el digest del build y observó procedencia SLSA
3 firmada. El plan guardado de SHA-256 `64b20055…` contenía sólo dos cambios de
imagen in-place; su único apply terminó 0/2/0 y dos planes posteriores dieron
`No changes`.

Web continúa mock y sin clave; worker está real con secreto v2, USD 0.55, P10
false, 1/1 y `maxRetries=0`. Service y Job están Ready sobre el mismo digest,
IAM limita la clave al worker y health/readiness/401 privado pasaron. La fase
de despliegue ejecutó cero jobs y cero Responses. Las fronteras reales siguen
18/18; sólo falta el E2E sintético fresco de producto con edición P05 durable
y submission.

## Historial: P04→P05 y P06 PASS; deploy pendiente

La actividad `act_aecd258c017c5b37c603` usó dos jobs y dos executions. P01,
P02 y P03 terminaron `SCHEMA_VALID`; después de persistir tres decisiones
recomendadas, P04 y P05 también terminaron `SCHEMA_VALID`. El job de dominio
quedó `NEEDS_REVIEW` porque P05 recomendó `REJECT`, aunque el blueprint fue
persistido `READY`. El agregado fue cinco Responses y USD 0.03490275, con
P10/P11/Sol/fallback/retries cero. No hubo edición, aprobación ni submission.

La revisión adversarial confirmó que los fallos críticos de P05 exigían que
una sola oportunidad cubriera dos criterios porque `question_count=1`, y
consideraban inválida la diversidad entre oportunidades. ADR-030 define lo
contrario: P04 produce un catálogo conceptual y el planificador elige después
exactamente N. También se comprobó que `PolicyDecision` no transportaba la
semántica de la opción elegida.

El contrato conserva ahora un snapshot `selected_option`; P04/P05 requieren
decisiones autocontenidas. P04 1.1.7 materializa consecuencias representables
y separa cobertura conceptual de cobertura por plan. P05 1.1.5 revisa
factibilidad exacta-N y acepta diversidad calibrada. El gateway rechaza
cobertura fuente incompleta o un catálogo incapaz de formar N dentro del
tiempo/calidad configurados.

| Gate o evidencia histórica en ese corte | Resultado |
|---|---|
| P04→P05 acoplado | PASS; dos fake Responses; output P04 exacto como input P05; ambos READY; P05 no REJECT y sin critical FAIL |
| Frontera/costo | P04 `sha256:48f9aa99…` + input `sha256:e2f944b4…`; P05 `sha256:d5f35e82…` + input derivado `sha256:022bcdd3…`; ceiling USD 0.04988775/cap USD 0.06 |
| Controles | provider schema/Pydantic/contexto, IDs allowlist, decisiones autocontenidas, cobertura fuente, exact-N, categorías P05 objetivo; retries/P10/P11/Sol/fallback 0 |
| P06 lineage | PASS dry-run separado; una fake Response; `sha256:3fcde330…`/`sha256:3cabdfaa…`; ceiling USD 0.023361/cap USD 0.03 |
| P04 real | PASS `READY`; 4,570 input, 4,567 cache-write, 7,132 output, 5,094 reasoning; 56,949 ms; USD 0.00970075 |
| P05 real | `MODEL_TIMEOUT` a 120,016 ms; input dinámico ligado a `sha256:cf4aeb8…`; sin metadata de usage porque no hubo respuesta |
| Frontera consumida | 2/2 Responses; USD 0.05106550 charge conservador/cap USD 0.06; retries/P10/P11/Sol/fallback 0; stop al primer fallo |
| Recuperación real | PASS/PASS `READY`; 2/2 Responses; P04 48,578 ms/USD 0.00840355 y P05 47,023 ms/USD 0.00805485; actual USD 0.01645840, charge USD 0.04086520, ceiling USD 0.05147825/cap USD 0.06 |
| Evidencia recuperada | P04 output validado `sha256:22dd21e3…`; P05 input dinámico `sha256:e8bd0e92…`; reporte SHA-256 `3452b12bf89ea0cb59c29837b054d60db0ef46ceeb950802c680e20001a94df8` |
| P06 real | PASS `READY`; provider/Pydantic/contexto/outcome/lineage PASS; 1/1 Responses; 2,884 input, 2,881 cache-write, 637 output, 224 reasoning; 8,270 ms; USD 0.00148525 actual, USD 0.01992085 charge, USD 0.023361 ceiling/cap USD 0.03 |
| Evidencia P06 | `sha256:3fcde330…`/`sha256:3cabdfaa…`; output `sha256:876c6be5…`; reporte SHA-256 `5daf7774e0ffee1bbc6b9b834b09f2022a496cdf14daabed303467cd7087c5b3`; retries/P10/P11/Sol/fallback 0 |

El timeout fue el límite del adapter, no un fallo de contrato. El perfil real
sube de 120/125 s a 240/245 s (SDK/gateway), dentro del máximo configurado de
300 s y con retries cero. La aprobación anterior no puede abrir otra request:
su constante está consumida. La recuperación tiene opt-ins y consumo propios,
repite la cadena completa porque `store=false` no permite recuperar el payload
P04 para una P05 aislada, y conserva máximo dos Responses/cap USD 0.06. Esa
recuperación terminó PASS sin repair ni rutas laterales y su approval quedó
consumido. El runtime desplegado todavía contiene la versión anterior; faltan
build/deploy y E2E fresco antes de `OPENAI_REAL_MANUAL_EVAL_READY`.

## Historial: P04 v1.1.6 real PASS tras stop de producto

Las seis interpretaciones recomendadas P03 se persistieron y la única acción
de reanudación creó un job/una ejecución. P01-P03 se reutilizaron sin llamadas.
P04 v1.1.2 pasó schema del proveedor pero falló Pydantic; la única P11
permitida no reparó el contrato destino. P04 y P11 consumieron dos Responses y
USD 0.01150895; el E2E acumula cinco Responses y USD 0.02453340. El job quedó
`FAILED`/`PERMANENT`, Cloud Run exit 1 y no se ejecutó P05 ni se creó blueprint
o submission.

P04 v1.1.6 añade instrucciones explícitas para IDs únicos, operación soportada,
formatos permitidos, referencias de justificación, allowlists de fuente,
decisiones exactas y ausencia de aprobación humana. La primera observación
aislada quedó `INCONCLUSIVE` porque el orquestador no archivó stdout; el
transporte `store=false` dejó 0 logs recuperables y no se repitió ese gate.
Una recuperación separada, con máximo una request y cap USD 0.03, terminó PASS
`READY`:

| Magnitud P04 v1.1.6 | Observado |
|---|---|
| Validaciones | provider schema PASS; Pydantic PASS; contexto PASS; expected outcome PASS |
| Frontera | Luna-high; 1/1 Responses; P10/P11/Sol/fallback/retries 0 |
| Uso | 3,554 input; 3,551 cached; 4,422 output; 2,588 reasoning; 35,515 ms |
| Costo | USD 0.00537802 actual; USD 0.01927162 charge; USD 0.02442225 ceiling; cap USD 0.03 |
| Prompt/input | `sha256:95989468…` / `sha256:7320de03…` |
| Request/output | `sha256:cfb9adb8…` / `sha256:1c04e1e0…` |

Ambos gates P04 están consumidos. Ninguna salida, request ID o clave se retuvo
en claro; el reporte content-free tiene SHA-256
`c47db41ae010c38e3bfe4c3c461d04fac50f5e0d17774e884836b5c90bb9402a`.

## Historial: tres llamadas E2E válidas y parada P03

Sobre el SHA/digest desplegado autorizado, P01, P02 y P03 usaron Luna y
terminaron `SCHEMA_VALID`, intento 1. Sus tres stage runs quedaron
`SUCCEEDED`, versionados y hash-bound. P03 produjo un `AmbiguityReport` válido
con `blocked=true`, seis issues y cuatro bloqueantes, por lo que el job durable
quedó `NEEDS_REVIEW` con `ASSIGNMENT_AMBIGUOUS`.

El agregado fue 8,650 input, 0 cached, 9,052 output, 82,288 ms y USD
0.01302445. P10, P11, Sol, fallback y retries fueron cero. Se detuvo antes de
P04/P05; no hubo decisión docente, blueprint, submission ni segunda ejecución.
El resultado demuestra fail-closed y revisión humana efectiva, pero todavía
no prueba el recorrido manual completo.

## Historial: P11 directo PASS y corpus real completo

P11 devolvió `REPAIRED` y pasó schema provider, Pydantic, contexto y expected
outcome. Conservó el target e hizo exactamente el cambio estructural mínimo.
Usó una request, P11 uno, retries gateway/prompt/SDK 0/0/0 y P10/Sol/fallback
cero. El costo calculado fue USD 0.00070015, el charge conservador USD
0.00996535 y el ceiling full-cache-write USD 0.01172550, bajo el cap USD 0.02.

La observación registró 1,462 input, 0 cached, 1,459 cache-write, 279 output, 34
reasoning y 3,892 ms. Prompt/input quedaron en:

```text
sha256:43f2ca4d6a0c02f015125a96f3a12bc5dd8d6c0eab0583f9c2f11b0f1c1f1f04
sha256:f8c2a6058214a4958b83e8850780e2827e1269720251f25f1e21d062371fb185
```

No se retuvo contenido; sólo hashes seguros de output y request ID. El
entrypoint rechaza otra canary con `OPENAI_P11_V114_DIRECT_ALREADY_CONSUMED`
antes del adapter. Las 18 fronteras real-eligible pueden recomprobarse offline
sin una llamada adicional. Build/deploy y E2E conservan gates separados.

## Hardening presupuestario predeploy

Una auditoría offline posterior reprodujo una brecha P1 en la autorización de
costo: antes del transporte el gateway tasaba el input como ordinario, mientras
las llamadas observadas lo clasificaban casi íntegramente como cache-write a
1.25×. El ledger posterior era correcto, pero no podía impedir que la request
ya enviada sobrepasara el remanente. El estimador preventivo reserva ahora todo
el input como cache-write, tanto en el resolvedor como en los estimates de UI;
una prueba confirma el bloqueo antes de adapter/red con un cap que sólo cubriría
la tarifa ordinaria.

El perfil del primer manual eval ejecuta cero retries automáticos de gateway y
SDK. Los controles retry/resume de Etapa 2 siguen disponibles como decisiones
humanas durables y auditables. P11 conserva una oportunidad por salida
estructural inválida, pero su ruta admite como máximo 80,000 tokens de input;
la reserva calificada máxima es 76,482. El caso dinámico mayor falla por
`INPUT_TOKEN_LIMIT_EXCEEDED` antes de crear el transporte P11.

Con la actividad sintética de cache, una pregunta y tres reservas, el preflight
queda en USD 0.253571 para actividad y USD 0.490573 para submission bajo USD
0.55 por job. La ruta real con adapter fake terminó P01-P09 en jobs
`SUCCEEDED`, nueve tareas semánticas, máximo input estimado 27,330 y cero
red/billable. Sumando una edición durable P05, el E2E futuro reserva USD
0.855444, cap propuesto USD 0.90 y máximo 32 Responses sin retries. Ese P1 de
presupuesto quedó cerrado y no quedan P0/P1 abiertos. Ninguna de estas pruebas
autoriza gasto o deploy.

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

## Historial: P01 1.1.2, P02 1.1.3 y P05/P11 1.1.4 aceptados en su corte

P01 distingue suficiencia de completitud: una especificación fiel y usable
puede ser `READY` sin llenar todos los campos sourced. En cambio, todo status
no `READY` exige las cinco listas sourced vacías y diagnóstico. El fixture
injection contiene outcome, producto, requisitos y materiales
permitidos/prohibidos suficientes; por eso exige `READY` mientras trata el
marcador sólo como dato. La qualification observó `READY`, provider schema,
Pydantic, contexto y outcome PASS, sin propagación del marcador. El prompt
conservó exactamente el hash aceptado
`sha256:b706477b13e33e8a2f3d1847c86af5b917fa93f17a5071cfe821f692a8c41b4a`;
esa evidencia cierra P0 sin convertir la qualification parcial en PASS global.

La qualification 1.1.2 real pasó los casos 1 a 10 y se detuvo fail-closed en
P02 después de 11 requests, sin retry, P10, P11, Sol o fallback. El fallo
`MODEL_CONTEXT_NOT_ALLOWLISTED` ocurrió después de provider schema y Pydantic
PASS; el outcome no se evaluó. Como `store=false` y el output no se persistió,
la evidencia conservada sólo permite dos clases compatibles: `activity_id`
distinto de la request o una abstención P02 con criterios parciales. No se
atribuye una de ellas sin evidencia.

El prompt ejecutable P02 omitía reglas que la especificación y el validator ya
exigían: copiar el `activity_id`, sustentar criterios sólo con
`rubric_evidence` y usar `criteria=[]` más diagnóstico en toda abstención. La
versión 1.1.3 explicita esas invariantes y añade reason codes content-free;
contratos, schema, ruta, fixture y expected outcome permanecen iguales. P01 y
las demás entradas conservan su versión individual 1.1.2. El dry-run candidato
pasó 18/18 con 18 transportes fake, cero red/billable, máximo conservador 19 y
ceiling full-cache-write USD 0.31063875.

La recanary P02 se ejecutó sobre su frontera exacta y terminó PASS `READY`:
provider schema, Pydantic, contexto y expected outcome PASS; Luna medium
solicitada/efectiva; una request; retries/P10/P11/Sol/fallback cero. Registró
2,049 input, 0 cached, 2,046 cache-write, 600 output y 300 reasoning tokens,
7,579 ms y USD 0.00123210 calculados frente al cap USD 0.02. La autorización
quedó consumida.

La continuación reutilizó los diez PASS 1.1.2 y el PASS P02 sólo después de
recomprobar sus fronteras hash-bound. El bloque autorizado con cap USD 0.16
ejecutó P03 PASS, P04 PASS y P05 FAIL más una P11, y se detuvo antes de
P06/P08/P09/P11 directo. Hubo cuatro requests, USD 0.02438310 calculados, USD
0.06006390 de charge conservador y USD 0.07136750 reservados; retries,
P10/Sol/fallback quedaron en cero. La approval quedó consumida y el código
rechaza su reutilización antes de credencial/transporte.

P05 pasó el schema estricto del proveedor pero falló el `model_validator`
canónico con `value_error` en `/`; contexto y outcome no se evaluaron. La
única P11 pasó su wrapper estructurado, pero el objeto objetivo volvió a fallar
Pydantic. El output no se retuvo, así que no se inventa una causa concreta. La
omisión determinista del prompt era la tabla de estados del review, y P11 no
tenía una orden explícita de abstenerse ante un invariante raíz ambiguo.

La versión 1.1.4 hace explícito que una revisión completada usa `READY` con
recomendación no nula; critical FAIL fuerza `READY`+`REJECT`; y una abstención
usa recomendación nula sin critical FAIL. P11 devuelve `UNREPAIRABLE` en vez de
elegir campos semánticos ante ese error raíz. Tras aceptar la remediación, la
recanary P05 1.1.4 pasó en una request: `READY`, las cuatro capas de validación
PASS, P11 cero y USD 0.00936825 calculados frente al cap USD 0.03. Su approval
quedó consumida.

Los catorce PASS reales se reutilizan sólo bajo hashes exactos. El dry-run
entonces candidato programaba P06/P08/P09/P11, pasaba 4/4 sin red ni costo y fijaba ceiling USD
0.09270600, cap propuesto USD 0.10, máximo cinco requests, P11 máximo uno y
stop al primer fallo. Requiere una approval v1.1.4 distinta.

Las aceptaciones normativas y las autorizaciones facturables no comparten
opt-in. El harness liga cada decisión y cada evidencia reutilizada a su
frontera, valida el cap antes de comprobar los gates y sólo después consulta la
credencial. Las approvals consumidas no habilitan la continuación. Los reportes
conservan disposiciones hash-bound y hashes, nunca el valor del secreto ni el
contenido de request/output.

La edición interactiva P05 ya no invoca modelos desde el Service. `PATCH`
responde `202 JobEnvelope`, congela source version/ETag y persiste un descriptor
hash-verificado antes del dispatch. El worker reconstruye actividad, rúbrica,
decisiones, política y estructura, ejecuta P05 y publica la nueva versión junto
con el estado terminal en una transacción. Cancel y retry preservan el
blueprint anterior o reconstruyen el descriptor desde el linaje. Web real no
recibe clave ni conserva un camino `_direct_gateway`.

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
- timeout entre 5 y 300 segundos y retries gateway/SDK iguales a cero en el
  perfil manual inicial;
- preflight que contabiliza prompt, envelope y schema completos, full
  cache-write, una oportunidad P11 por tarea y el saldo durable del presupuesto
  agregado por job.

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

El gateway genérico conserva soporte probado de hasta dos retries transitorios,
pero el perfil manual activo fija su límite en cero: timeout, conexión,
408/409/5xx o rate limit terminan el job y sólo una acción durable puede crear
otro intento. Auth, autorización, modelo ausente,
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

## Investigación histórica del fallo contextual P01 de inyección (1.1.1)

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
`source_role=ASSIGNMENT_PROMPT`. En ese checkpoint su expected `VALID` era
correcto: conservaba una consigna suficiente y el marcador era dato no
confiable, no una razón para
fabricar o abstenerse. La descripción del manifest se corrigió para reflejar
esa frontera sin cambiar request, prompt, schema, contrato o expected outcome;
los hashes permanecen idénticos a la llamada histórica.

La cobertura preventiva declarada sí incluye instrucciones/datos separados,
envelope tipado, output estricto, allowlists, `tools=[]`, `store=false` y
validación contextual. Por separado, Stage 0 atraviesa el parser con una
submission sintética Markdown y la regresión P07 rechaza el eco del marcador.
En ese checkpoint la cobertura de detección seguía limitada a sentinelas
sintéticos conocidos; no existía un detector general implementado bajo el nombre
`PROMPT_INJECTION_SIGNAL`. Esa limitación se registró como el sexto P2 y no se
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
| Proyecto, spend limit y clave privada | proyecto verificado; clave histórica rechazada 401; Secret Manager v1 `DISABLED`, v2 `ENABLED`; v2 autentica y sólo ve Luna |
| Perfil Luna-only y regresión offline | PASS; golden sintético y controles de ruta/budget/ledger verdes; cloud permanece mock con P10 false |
| Smoke P11 sintético, una llamada | `OPENAI_REAL_SMOKE_PASS`; 1 request, retries 0/0/0 |
| Canary P01 Luna-medium | PASS real; `READY`, 1 request, USD 0.00145745 calculados |
| Canary P07 Luna-high | FAIL real fail-closed; 1 request, output Pydantic inválido, P11 0, USD 0.00327560 calculados |
| Investigación P07 provider/Pydantic | PASS offline; schema exacto fijado, pérdida de ledger corregida, clases provider/Pydantic/contexto reproducidas sin contenido |
| Recanary única P07 Luna-high | PASS real; `READY`, provider schema/Pydantic/contexto PASS, 1 request, P11 0, USD 0.00276560 calculados |
| Revisión P1 P07 | blocker cerrado sin atribuir causa raíz; observación de recurrencia P07 continúa como P2 |
| Calificación sintética dry-run 1.1.2 | PASS 18/18 contra adapter real y transporte fake; sin evidencia real reutilizada; 0 red/0 billable; ceiling USD 0.31043475/cap USD 0.32 |
| Separación de gates P01/billable | PASS offline; decisión P01 hash-bound independiente, approval de gasto separada y credencial posterior |
| Calificación sintética real 1.1.1 | detenida fail-closed en `oa-p01-injection-md` después de 1 request; los otros 14 casos no se ejecutaron |
| Investigación P01 injection 1.1.1 | causa histórica no recuperable; cinco clases reproducidas y observabilidad content-free preparada; 0 red/0 billable |
| Recanary única P01 injection 1.1.1 | FAIL contextual discriminado: `P01_ABSTENTION_SOURCED_FIELDS_PRESENT`; marcador no propagado; 1 request, P11 0 |
| Rotación de credencial | PASS; clave anterior rechazada por OpenAI antes de deshabilitar v1; v2 quedó como única versión local habilitada |
| Qualification sintética real 1.1.2 | FAIL agregado al primer P02; casos 1–10 PASS, caso 11 FAIL contextual, casos 12–18 no ejecutados; 11 requests, retries/P10/P11/Sol/fallback 0 |
| Remediación P01 | PASS real exacto en `oa-p01-injection-md`; P0 cerrado, marker no propagado y frontera 1.1.2 preservada |
| Investigación P02 | fallo histórico fail-closed; provider schema/Pydantic PASS y contexto FAIL; subtipo no recuperable entre dos clases compatibles |
| Remediación P02 1.1.3 | aceptada y PASS real: una recanary, `READY`, todas las validaciones PASS, USD 0.00123210; P1 cerrado |
| Continuación 1.1.3 | FAIL gobernado real: P03/P04 PASS, P05 FAIL más una P11; stop tras 4 requests; P06/P08/P09/P11 directo no ejecutados; USD 0.02438310; approval consumida |
| Remediación y recanary P05/P11 1.1.4 | PASS real: `READY`, schema/Pydantic/contexto/outcome PASS, 1 request, P11 0, USD 0.00936825; P1 cerrado y approval consumida |
| Continuación 1.1.4 dry-run | 4/4 PASS, 14 evidencias reales hash-bound, 4 fake, 0 red/billable, máximo 5, ceiling USD 0.09270600/cap propuesto USD 0.10 |
| Continuación 1.1.4 real | FAIL gobernado en P09: P06/P08 PASS, P09 schema/Pydantic PASS y contexto FAIL, P11 directo no ejecutado; 3 requests; USD 0.00864505; approval consumida |
| Recanary P09 1.1.5 | PASS real `READY`: schema/Pydantic/contexto/outcome PASS, 1 request, USD 0.00443985, P10/P11/Sol/fallback/retries 0; approval consumida |
| P11 directo 1.1.4 dry-run | PASS `REPAIRED`: 17 evidencias previas revalidadas, 1 fake, 0 red/billable, ceiling USD 0.01172550/cap propuesto USD 0.02 |
| P11 directo 1.1.4 real | PASS `REPAIRED`: schema/Pydantic/contexto/outcome PASS, target inmutable y cambio mínimo; 1 request, USD 0.00070015, P11 1, retries/P10/Sol/fallback 0; approval consumida; corpus 18/18 |
| Hardening de presupuesto predeploy | PASS offline; full-cache-write antes de transporte, gateway/SDK retries 0/0, P11 máximo 80K, E2E fake P01-P09 `SUCCEEDED`; P1 cerrado |
| Edición P05 durable | PASS backend/API/frontend/E2E; P2 funcional cerrado |
| Calidad/latencia/costo y severidad | P0=0; P1=0; P2=5; P3=1; calidad pedagógica pendiente de revisión humana posterior |
| Build, digest y deploy real del worker | PASS cloud: build `613270cf…` SUCCESS/VERIFIED; digest `sha256:979600…aaeb`; apply exacto 1/2/0; web mock sin clave y worker real v2; dos planes posteriores sin cambios |
| Primer E2E real, tramo P01-P03 | PASS técnico y stop humano: 3 Responses; P03 `NEEDS_REVIEW`; USD 0.01302445 |
| Reanudación P03 y stop P04 | seis decisiones durables; P01-P03 reutilizados; P04 + P11 fallan el target Pydantic; 2 Responses, USD 0.01150895; job/ejecución FAIL, sin P05/blueprint/submission |
| P04 1.1.6 recuperación real | PASS `READY`: schema/Pydantic/contexto/outcome PASS, 1 request, USD 0.00537802, P10/P11/Sol/fallback/retries 0; recanary inconclusa y recuperación consumidas; corpus actual 18/18 |

El camino interactivo P05 está ya detrás del worker durable y no puede entregar
un review mock dentro de un recorrido declarado OpenAI. El digest desplegado
todavía contiene P04 v1.1.2; el estado no es `OPENAI_REAL_MANUAL_EVAL_READY`.
Falta cerrar regresión/CI, construir y desplegar P04 v1.1.6 y ejecutar un E2E
sintético nuevo. Los gates P04 ya consumidos no autorizan por sí solos otro
build, job, E2E o datos estudiantiles reales.

Fuentes oficiales: páginas de
[`gpt-5.6-sol`](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[`gpt-5.6-terra`](https://developers.openai.com/api/docs/models/gpt-5.6-terra) y
[`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[precios](https://developers.openai.com/api/docs/pricing),
[Responses](https://developers.openai.com/api/docs/guides/responses),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
y [manejo de errores](https://developers.openai.com/api/docs/guides/error-codes).
