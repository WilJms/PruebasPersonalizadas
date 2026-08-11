# Estado de implementación — Etapa 2

Fecha de corte: 2026-08-10 (America/Santiago).

## Estado vigente — `OPENAI_P09_V115_REMEDIATION_DECISION_REQUIRED` (2026-08-10)

La única continuación sintética OpenAI v1.1.4 autorizada sobre `abca7c5`, cap
USD 0.10 y máximo cinco Responses requests, quedó consumida. Ejecutó P06 PASS,
P08 PASS y P09 FAIL contextual, y se detuvo en el primer fallo antes de P11
directo. Usó tres requests, P11/P10/Sol/fallback cero y retries de
gateway/prompt/SDK 0/0/0. El costo calculado fue USD 0.00864505, el charge
conservador USD 0.04284505 y la reserva transportada full-cache-write USD
0.05226000, dentro del ceiling agregado autorizado USD 0.09270600. El
entrypoint histórico bloquea ahora
`OPENAI_QUALIFICATION_V114_CONTINUATION_ALREADY_CONSUMED` antes de material,
credencial o transporte.

P06 y P08 pasaron schema provider, Pydantic, contexto y expected outcome. Sus
fronteras prompt/input quedaron fijadas respectivamente en
`sha256:3fcde330e122adbf33a21021e89c5bf02eb746203c678c258478e6377519c91d` /
`sha256:d404f46a26c542eb810551312ea3cea7c80adff17b866f5f5d34e18b7c59947d`
y
`sha256:06f48bb22cc1318c39efed17dcb77057f4a920450d3434b3557b5c078d9d84f5` /
`sha256:5deaccfce36fbb2e79d7d17f0d671183bbb75a7c05035173be0ce69144fde130`.
La evidencia real reutilizable cubre ahora **16/18** casos.

P09 pasó schema estricto del proveedor y Pydantic, pero falló contexto con
`MODEL_CONTEXT_NOT_ALLOWLISTED`; el outcome no se evaluó y P11 no corresponde
a fallos contextuales. El código seguro histórico fue
`CONTEXT_INVARIANT_FAILED`. Como `store=false` y no se retuvo el output, no se
atribuye un campo concreto. La remediación v1.1.5 cubre toda la superficie
compatible: copia literal de `guide_id`/`assessment_id`/`submission_id`,
cobertura exacta de preguntas, evidencia limitada por pregunta y
`source_ids=[]` en contexto cerrado. El gateway distingue siete códigos P09
content-free sin registrar IDs ni texto.

El dry-run P09 v1.1.5 pasa con una sola request fake, cero red/billable,
P10/P11/Sol/fallback cero y todas las pruebas contextuales. Queda fijado a
prompt
`sha256:8d29a13a5ee56b39f6aa5545b602e23ca28b6d60d051852d75ecbc0c664179ff`
e input
`sha256:d85b124990e457e096fbe4851633ee057b662efcbda3ac84837e8c8a78deacc7`;
su ceiling full-cache-write es USD 0.01592350 y el cap humano propuesto USD
0.02, máximo una Responses request, retries 0 y P10/P11/Sol/fallback 0. La
remediación normativa y el gasto requieren un gate exacto nuevo fijado al SHA
final; ninguna aprobación previa se transfiere. Después de un PASS P09, P11
directo tendrá su propio gate separado.

El conteo vigente es **P0=0, P1=1, P2=5, P3=1**. Cloud continúa en el digest
histórico, `CVA_MODEL_MODE=mock` y `CVA_P10_ENABLED=false`; no hubo build,
deploy, Terraform apply, IAM, datos estudiantiles reales ni merge a main. Este
estado todavía no es `OPENAI_REAL_MANUAL_EVAL_READY`.

## Historial — `OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL_REQUIRED` (2026-08-10)

La rotación sigue cerrada: Secret Manager v1 está `DISABLED`; v2 está
`ENABLED`, autentica con SDK retries cero y sólo ve `gpt-5.6-luna`. El preflight
inmediatamente anterior a la recanary confirmó el proyecto OpenAI
`PruebasPersonalizadas` (`proj_te2wY3kbHAkFp8IgjglH063t`), USD 3.84 de USD 5.00
en el límite mensual del proyecto, reset en 21 días, y capacidad Luna de
200,000 TPM / 500 RPM. La tarifa oficial coincide con el harness: USD 0.20/M
input, 0.02/M cached input, 0.25/M cache-write y 1.20/M output. La inspección
fue read-only y no expuso secretos.

El propietario aceptó la remediación normativa P05/P11 v1.1.4 y autorizó
exactamente una recanary P05 fijada por `35ecaf8`, cap USD 0.03, máximo una
Responses request, stop al primer fallo y retries/P10/P11/Sol/fallback cero.
La llamada única terminó **PASS**: `READY`, schema provider, Pydantic, contexto
y expected outcome PASS, con Luna-high solicitada y efectiva. Usó 2,520 input,
0 cached, 2,517 cache-write, 7,282 output y 5,478 reasoning tokens en 57,540 ms.
El costo calculado fue USD 0.00936825; el charge conservador USD 0.01982985 y
el ceiling USD 0.02252775. No se retuvo output ni request ID en claro.

La observación queda ligada a prompt
`sha256:1b1bb9cc10bb4eb633486863bba8dbfdbd70d2f0266795cbaa37505b7e6dcb0a`
e input bundle
`sha256:be9521524e643adf11b13914a0e39bbb605f2962e1964b8535a8df1643177969`.
La autorización quedó consumida y el entrypoint bloquea otra recanary con
`OPENAI_P05_V114_RECANARY_ALREADY_CONSUMED`. El PASS cierra el P1 P05; el
conteo vigente es **P0=0, P1=0, P2=5, P3=1**.

La evidencia real hash-bound cubre ahora **14/18** casos: diez PASS de la
qualification 1.1.2, P02 1.1.3, P03/P04 de la continuación 1.1.3 y P05 1.1.4.
Todo gate anterior queda consumido. El harness bloquea drift de prompt, input,
expected outcome, behavior o severidad antes de credencial/transporte.

El nuevo dry-run v1.1.4 fija sólo los cuatro casos aún no observados:
`oa-p06-happy-docx`, `oa-p08-happy-pdf`, `oa-p09-happy-docx` y
`oa-p11-happy`. Pasó 4/4 con cuatro transportes fake, cero red/billable, catorce
evidencias reutilizadas y cobertura acumulable 18/18. Su ceiling es USD
0.08616480 sin cache y USD 0.09270600 reservando todo input como cache-write;
el cap humano propuesto es USD 0.10. La frontera permite máximo cinco Responses
requests, P11 máximo uno, stop al primer fallo y retries/P10/Sol/fallback cero.
El opt-in histórico v1.1.3 no abre este gate.

La auditoría offline de preparación del E2E encontró y cerró un P1 adicional
sin consumir red ni autorización: el gateway calculaba la reserva previa con
tarifa de input ordinario, aunque las ejecuciones reales habían clasificado
casi todo el input como cache-write a 1.25×. El estimador preventivo usa ahora
full-cache-write tanto para el resolvedor como para el preflight de la UI. El
perfil manual Luna-only fija retries automáticos gateway/SDK en 0/0, conserva
retry durable sólo como acción humana y limita P11 a 80,000 tokens de input;
el peor caso calificado de P11 es 76,482 y un exceso falla antes de Responses.
El hallazgo quedó cerrado y el conteo abierto continúa **P0=0, P1=0, P2=5,
P3=1**.

Con los fixtures versionados de `activity_01_rubric`, una actividad de una
pregunta reserva USD 0.253571 y la submission con tres oportunidades de reserva
USD 0.490573; ambas pasan un límite propuesto de USD 0.55 por job. Un recorrido
offline por las rutas reales y transporte fake terminó ambos jobs en
`SUCCEEDED`, ejecutó P01-P09 en nueve tareas semánticas, observó como máximo
27,330 tokens de input preflight y creó cero llamadas de red/facturables. Si el
E2E añade una edición durable P05, su techo route-max es USD 0.111300; el
ceiling agregado actividad+edición+submission es USD 0.855444, cap humano
propuesto USD 0.90 y máximo defensivo 32 Responses requests, sin retries.

La inspección cloud read-only confirmó Service `cva-web` revisión
`cva-web-00016-gml` y Job `cva-worker` en el digest histórico
`sha256:0d8f29f28dc510bf2cb14f10252e42afe5a7ce05c14e67facccaa066d0065765`,
ambos todavía mock/P10 false; el Job mantiene un task, paralelismo uno y
`maxRetries=0`. Health/readiness respondieron 200 y una ruta privada 401. El
secreto `cva-openai-api-key` conserva v2 `enabled`, v1 `disabled` y ninguna
cuenta web/worker tiene todavía su IAM. Un plan Terraform no mutante,
`refresh=false`, con el digest vigente y valores reales provisionales mostró
exactamente dos updates in-place (Service/Job), una creación IAM para el worker
y 36 recursos sin cambio; no se aplicó.

Este estado aún no es `OPENAI_REAL_MANUAL_EVAL_READY`: primero hace falta una
autorización billable exacta para esa continuación v1.1.4; después, bajo gates
separados, deploy/Terraform y E2E sintético real. Cloud continúa
`CVA_MODEL_MODE=mock`, `CVA_P10_ENABLED=false`; no hubo deploy, Terraform apply,
IAM, P10, Sol/fallback, datos estudiantiles reales ni merge a main.

## Historial — `OPENAI_REAL_V112_ROTATION_BLOCKED` (2026-08-10)

La rama `codex/openai-real-provider-gate` remedia técnicamente el P0 P01. El
propietario aceptó la semántica normativa 1.1.2, pero ordenó conservar el P0
como blocker empírico hasta que `oa-p01-injection-md` pase una observación real
v1.1.2. Prompt pack `1.1.2` define `READY` para una
consigna suficiente y usable, y exige que todo status no `READY` vacíe sus
cinco listas sourced. El fixture injection es ahora inequívocamente suficiente,
espera `READY` y conserva el marcador como dato no propagable. Sus hashes
nuevos impiden reutilizar las seis observaciones reales 1.1.1 como evidencia
vigente.

La qualification dry-run pasó los 18 casos `real_eligible`, sin evidencia
reutilizada, con 18 transportes fake, cero red/billable, P11 directo al final,
una reserva estructural, máximo conservador 19 requests y ceiling
full-cache-write USD 0.31043475 frente a cap USD 0.32. P07 quedó cubierto por
cuatro casos suficientes diversos más uno insuficiente; su P2 de recurrencia
permanece abierto hasta evaluación real y revisión humana.

El entrypoint real exige ahora una decisión P01 y una aprobación billable como
opt-ins distintos. La decisión queda ligada a los hashes exactos v1.1.2; un
drift de prompt o input, un cap fuera de rango o la ausencia de cualquiera de
los gates bloquea antes de leer la credencial o crear transporte.

P05 interactivo ya es un job durable: API `202 JobEnvelope`, descriptor
hash-verificado, ejecución exclusiva en worker y publicación atómica de la
nueva versión. Cancel y retry conservan/reconstruyen estado; la UI espera el
job y recupera la versión final. El P2 funcional P05 queda cerrado. El conteo
vigente es **P0=1, P1=0, P2=5, P3=1**.

La revisión integrada pasó backend, frontend, OpenAPI, navegador y E2E local,
incluida corrección del overflow móvil de la revisión P05. Cloud no cambió:
continúa mock/P10 false. No hubo request facturable. El propietario autorizó
la rotación y una única qualification sintética con cap USD 0.32. La rotación
quedó parcialmente ejecutada: la clave restringida
`cva-stage2-qualification-20260810` fue creada en el mismo proyecto, copiada
directamente a `cva-openai-api-key` versión `2`, verificada como `enabled` e
inyectada en memoria para un `models.list` no facturable. La autenticación pasó
y el catálogo devolvió únicamente `gpt-5.6-luna`.

La clave histórica no quedó revocada. Seis confirmaciones sobre el target
exacto en Platform —la última desde la vista organizacional— no cambiaron su
estado y una comprobación autenticada posterior todavía fue aceptada. El
endpoint administrativo oficial respondió `403` a la credencial de proyecto,
como corresponde a una operación que exige una Admin API key. No se creó ni
solicitó esa autoridad adicional. Por ello la versión `1` permanece `enabled`,
no se consumió la autorización de qualification y no se ejecutó el primer caso
P01. El stop es fail-closed y no incluye deploy, Terraform apply, IAM, billing,
P10, Sol/fallback, datos reales ni merge. Un verificador content-free queda
versionado para exigir 401 sobre la clave histórica y Luna visible sobre la
nueva antes de continuar.

Este estado no es `OPENAI_REAL_MANUAL_EVAL_READY`: la credencial nueva está
lista, pero la rotación no termina hasta observar rechazo de la clave anterior
y deshabilitar la versión `1`. Todavía faltan validación empírica/cierre del
P0, qualification 1.1.2 real, deployment real y E2E sintético real de la
aplicación.

## Historial — merge E2 y gate OpenAI (2026-08-09)

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

La investigación posterior queda en
`OPENAI_LUNA_P07_ROOT_CAUSE_UNRESOLVED`. El fallo histórico demuestra que
`QuestionGenerationResult.model_validate()` rechazó el output, pero la evidencia
retenida no distingue incumplimiento del JSON Schema provider de una invariante
Pydantic no representable en ese schema. Por ello no se cambió prompt, contrato
ni expected outcome. El schema P07 exacto quedó fijado en 13.671 bytes y
SHA-256 `80692d48637f0ae2d7a7e6f05ab4e9b0a5e2d8eff6f1b103fbd14f62c482639a`;
la frontera provider/Pydantic/contexto está documentada y reproducida offline.

Sí se cerró un defecto determinista de observabilidad: el bloqueo de P11
enmascaraba el fallo primario y descartaba el ledger que ya contenía latencia,
modelo efectivo, usage y hashes. El gateway conserva ahora ese ledger y separa
`primary_failure=OUTPUT_PYDANTIC_VALIDATION_FAILED` de
`repair_disposition=BLOCKED_BY_CANARY_POLICY`; el adapter clasifica localmente
el objeto contra el mismo schema enviado. Solo se exponen tipos y paths
saneados, nunca valores, mensajes, `input`/`ctx` Pydantic ni output. P11 sigue
en cero dentro del canary.

La validación posterior pasó 107 pruebas focalizadas, ambos canary dry-runs con
cero red/facturación, 471 pruebas con cobertura (16 skips PostgreSQL
explícitos), contratos 53/140/274 sin drift y secret scan de 290 archivos. La
tarifa Standard oficial fue revalidada sin cambios y esta investigación añadió
USD 0.00. P0 permaneció en cero, no apareció otro P1 y el P1 histórico P07
quedó entonces abierto hasta una eventual única recanary expresamente
autorizada.

Esa autorización se consumió sobre
`97a6b2e8cd7cf852e9e3a6fefeb09c135793ac19`. La única recanary P07 terminó
`OPENAI_LUNA_P07_RECANARY_PASS_REVIEW_REQUIRED`: outcome `READY`, Luna-high
solicitada y efectiva, provider schema/Pydantic/contexto/invariantes PASS, una
request, retries 0/0/0 y P10/P11/Sol 0. Registró 3,839 input, 0 cached, 3,836
cache-write, 1,505 output y 655 reasoning tokens, 12,666 ms y USD 0.00276560
calculados frente al cap humano USD 0.03. No hubo cambios de producto, cloud o
expected outcomes. La revisión humana posterior cierra el P1 como blocker sin
atribuir una causa raíz ni afirmar que el modelo fue corregido: el incidente
original fue fail-closed, la pérdida determinista de observabilidad sí quedó
corregida y la frontera sin relajar produjo una recanary completamente válida.
La posible recurrencia de outputs P07 inválidos continúa como P2 independiente.

El gate siguiente queda preparado en un modo específico de calificación. Reusa
las observaciones reales P01/P07/P11 y propone los otros 15 casos
`real_eligible`, incluidos cuatro P07 diferentes, para completar 18/18 sin
repetir gasto. El dry-run pasó 15/15 con adapter real/transporte fake y cero
red/facturación. Hay 15 primarias, una reserva P11 global, máximo 16 requests,
retries 0/0/0, P10/Sol/fallback deshabilitados, ceiling full-cache-write USD
0.26877750 y cap humano propuesto USD 0.30. El alcance es técnico; no declara
calidad pedagógica.

La autorización posterior se consumió una sola vez sobre `73d252b…`. El gate
se detuvo en la primera primaria, `oa-p01-injection-md`: provider schema y
Pydantic PASS, contexto FAIL con `MODEL_CONTEXT_NOT_ALLOWLISTED`, expected
outcome no evaluado y ningún repair/P11. Luna medium fue solicitada y efectiva;
hubo 1 request, retries 0/0/0, P10/Sol/fallback 0, 10,345 ms y USD 0.00156270
calculados. Los otros 14 casos no se ejecutaron ni se reinició la secuencia.
El manifest intacto preclasifica el fallo como P0; su causa raíz sigue abierta
y no se atribuye al modelo sin evidencia. El checkpoint vigente es
`OPENAI_REAL_SYNTHETIC_QUALIFICATION_P01_INJECTION_CONTEXT_FAILED_REVIEW_REQUIRED`.

La investigación offline posterior comprobó que ese código ocultaba cinco
clases P01 distintas: evidence ID no allowlisted, course source ID no
allowlisted, abstención sin diagnóstico, abstención con campos sourced y
`activity_id` cambiado. Todas pasan schema provider/Pydantic en las
regresiones y fallan cerradas sin P11; el output histórico no fue retenido y su
hash no permite recuperar cuál ocurrió. No se atribuye seguimiento de la
inyección ni un defecto del modelo. El gateway/harness conserva ahora el
subtipos contextuales content-free —incluidos los que coexistan— y booleanos de frontera sin output, valores,
IDs ni mensajes.

El fixture fue auditado como una consigna `ASSIGNMENT_PROMPT` ya normalizada,
no una submission ni una prueba de parser. Su descripción se corrigió sin
cambiar request, prompt, schema, contrato o expected `VALID`; los hashes
históricos permanecen fijados. El dry-run de una única recanary P01 pasa con 0
red/billable, Luna-medium, P10/P11/Sol/fallback/retries 0, ceiling USD
0.01201925 y cap humano propuesto USD 0.02. El checkpoint queda en
`OPENAI_P01_INJECTION_RECANARY_APPROVAL_REQUIRED`; no se ejecutó la recanary.

La autorización posterior ejecutó esa única recanary sobre `0a61ff75…`. La
versión 1 del secreto `cva-openai-api-key` estaba `ENABLED` y se inyectó desde
Secret Manager solo al environment efímero del proceso. Provider schema y
Pydantic pasaron; el validator contextual falló con la única clase
`P01_ABSTENTION_SOURCED_FIELDS_PRESENT`. Esto demuestra que el objeto no READY
conservó al menos un campo sourced que la política exige vacío, pero no explica
por qué se produjo esa forma ni demuestra seguimiento de la inyección. El
marcador no reapareció en el output. Hubo 1 request, retries 0/0/0,
P10/P11/Sol/fallback 0, 1,725 input, 0 cached, 1,722 cache-write, 872 output,
516 reasoning, 9,779 ms y USD 0.00147750 calculados frente al cap USD 0.02.
El P0 permanece abierto para revisión en
`OPENAI_P01_INJECTION_RECANARY_P01_ABSTENTION_SOURCED_FIELDS_PRESENT_REVIEW_REQUIRED`.

La regresión local previa al smoke quedó en 457 passed/16 skips PostgreSQL
explícitos, 80% de cobertura, 40 tests focalizados CLI/adapter, golden set
20/20 con 0 network/0 billable, PostgreSQL 16/17
con 155/155 y doble matriz 1+7, frontend 32/32, Playwright 1+2, navegador
integrado limpio, Docker runtime/audit, Stage 0 reproducible,
contratos/OpenAPI sin drift, Terraform válido y secret scan limpio. La CI del
commit previo al gasto quedó 7/7 verde.

| Severidad de ese checkpoint | Abiertos |
|---|---:|
| P0 | 1 |
| P1 | 0 |
| P2 | 6 |
| P3 | 1 |

El P0 nuevo de ese checkpoint correspondía exclusivamente al fallo contextual
P01 preclasificado por el manifest y requería revisión antes de cualquier
avance. No quedaba un P1 abierto. Los P2 históricos seguían siendo
AV/compensación, corpus/política de privacidad y semántica real pendiente. El
cuarto P2 era la re-revisión interactiva P05 del Service: quedaba bloqueada con
`MODEL_EXECUTION_REQUIRES_WORKER` cuando el worker sea real hasta migrarla a un
job durable, por lo que nunca mezclaba silenciosamente mock con OpenAI. El
quinto P2 era la observación de confiabilidad P07: se cerraría con evidencia de no
recurrencia sobre los casos P07 diversos y la revisión humana posterior, o se
reclasificaría si reaparecía una violación estructural/contextual. El sexto P2
era la cobertura limitada de detección de prompt injection: existían prevención,
sentinelas sintéticos y rechazo de eco, pero no un detector general implementado
como `PROMPT_INJECTION_SIGNAL`. El P3 continúa siendo el warning deprecado
Starlette/httpx del adaptador de tests.

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
