# Setup gobernado del proveedor OpenAI

## Estado vigente — P09 1.1.5 preparado; remediación y recanary pendientes

La continuación v1.1.4 ya no está pendiente: se ejecutó una vez y quedó
consumida. P06 y P08 pasaron; P09 falló contexto después de pasar schema y
Pydantic; el stop al primer fallo impidió P11 directo. Fueron tres Responses
requests, USD 0.00864505 calculados, retries 0 y P10/P11/Sol/fallback cero.
Repetir el opt-in v1.1.4 bloquea antes de material/clave/transporte con:

```text
OPENAI_QUALIFICATION_V114_CONTINUATION_ALREADY_CONSUMED
```

La remediación P09 v1.1.5 no cambia contratos ni schema. El dry-run está
hash-bound, devuelve READY, usa una request fake, cero red/billable y fija
ceiling USD 0.01592350 bajo cap propuesto USD 0.02. La interfaz del gate futuro
es:

```text
CVA_OPENAI_P09_V115_REMEDIATION_DECISION=OPENAI_P09_V115_REMEDIATION_ACCEPTED
CVA_OPENAI_P09_V115_RECANARY_APPROVAL=OPENAI_P09_V115_RECANARY_APPROVED
```

Estos valores documentan la interfaz y no constituyen aceptación ni
autorización. La autorización exacta debe fijar además el SHA candidato, una
sola Responses request, stop al primer fallo, retries 0 y
P10/P11/Sol/fallback 0. Una vez consumida, el entrypoint bloqueará
`OPENAI_P09_V115_RECANARY_ALREADY_CONSUMED`. P11 directo requiere un gate
posterior independiente.

Cloud conserva `CVA_MODEL_MODE=mock`, `CVA_P10_ENABLED=false`; ninguna clave
está montada en web/worker y no se autorizó deploy, Terraform apply, IAM, datos
reales ni main.

## Historial — P05 1.1.4 PASS y preparación de continuación v1.1.4

La clave histórica fue revocada en Platform y la sonda content-free confirmó
rechazo HTTP 401. Secret Manager versión `1` se deshabilitó después de esa
prueba; versión `2` está `ENABLED`, autentica y ve exclusivamente
`gpt-5.6-luna`. La credencial nueva no está montada en cloud, CI ni el Service.

La qualification 1.1.2 autorizada consumió 11 requests y USD 0.03258029. P01
injection pasó como primer caso y cerró P0. P02 falló contexto después de pasar
schema provider/Pydantic, por lo que el gate se detuvo. No se hizo una segunda
qualification.

El propietario aceptó `prompt-pack/1.1.3` para P02 y autorizó exactamente una
recanary sintética con cap USD 0.02. La llamada consumió esa autorización y
terminó PASS en una request: `READY`, todas las validaciones técnicas PASS,
USD 0.00123210 calculados y retries/P10/P11/Sol/fallback cero. Esto cierra el P1
P02; no autoriza una segunda llamada.
El entrypoint P02 real queda además bloqueado por
`OPENAI_P02_V113_RECANARY_ALREADY_CONSUMED`, aun si se repiten los valores de
approval históricos.

La continuación reutilizó once PASS reales después de recomprobar hashes,
expected outcomes, behaviors y severidades. La autorización específica fijó
máximo ocho Responses requests y cap USD 0.16. P03/P04 pasaron y P05 falló
Pydantic; una única P11 no reparó el root. El proceso se detuvo tras cuatro
requests, USD 0.02438310 calculados y retries/P10/Sol/fallback cero. P06/P08/P09
y P11 directo no se ejecutaron.

Los opt-ins históricos siguientes quedaron consumidos y se conservan sólo
como trazabilidad:

```text
CVA_OPENAI_P01_V112_REMEDIATION_DECISION=OPENAI_P01_V112_REMEDIATION_ACCEPTED
CVA_OPENAI_P02_V113_REMEDIATION_DECISION=OPENAI_P02_V113_REMEDIATION_ACCEPTED
CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL=OPENAI_REAL_SYNTHETIC_QUALIFICATION_V113_CONTINUATION_APPROVED
```

Repetir esos valores bloquea con
`OPENAI_QUALIFICATION_V113_CONTINUATION_ALREADY_CONSUMED` antes de construir el
adapter. No habilitan `prompt-pack/1.1.4`.

La remediación P05/P11 fue aceptada y la recanary P05 se ejecutó exactamente
una vez con cap USD 0.03. Terminó PASS `READY` en una Responses request, todas
las validaciones técnicas PASS, USD 0.00936825 calculados y
retries/P10/P11/Sol/fallback cero. Los opt-ins siguientes quedaron consumidos:

```text
CVA_OPENAI_P05_V114_REMEDIATION_DECISION=OPENAI_P05_V114_REMEDIATION_ACCEPTED
CVA_OPENAI_P05_V114_RECANARY_APPROVAL=OPENAI_P05_V114_RECANARY_APPROVED
```

Repetirlos bloquea con `OPENAI_P05_V114_RECANARY_ALREADY_CONSUMED`. El PASS
cierra el P1 P05 y deja 14/18 casos con evidencia real hash-bound.

La continuación entonces candidata contenía sólo P06/P08/P09/P11. El dry-run pasó 4/4,
cero red/billable, ceiling USD 0.09270600 y cap máximo propuesto USD 0.10. Su
frontera es máximo cinco Responses requests, P11 máximo uno, stop al primer
fallo y retries/P10/Sol/fallback cero. Requiere un opt-in distinto:

```text
CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL=OPENAI_REAL_SYNTHETIC_QUALIFICATION_V114_CONTINUATION_APPROVED
```

Este valor documenta la interfaz y no constituye autorización. También se
revalidan las tres decisiones normativas P01/P02/P05 antes de credencial o
transporte. Cloud conserva `CVA_MODEL_MODE=mock`, `CVA_P10_ENABLED=false`;
deploy, Terraform, IAM, gasto adicional, P10, datos reales y main siguen fuera
de autorización.

La preparación offline de deploy cerró además un P1 de presupuesto: el
preflight del transporte usa ahora full-cache-write en vez de input ordinario.
El perfil manual fija retries gateway/SDK 0/0 y P11 máximo 80,000 tokens de
input; retry/resume durable requiere intervención humana. Con los fixtures
sintéticos recomendados y una pregunta, el techo es USD 0.55 por job. El E2E
actividad + edición P05 + submission reserva USD 0.855444, cap futuro USD 0.90
y máximo 32 Responses requests. Esta frontera es distinta del cap USD 0.10 de
qualification.

La inspección read-only del runtime mostró el digest histórico aún en
mock/P10 false, health/readiness 200, privado anónimo 401 y el secreto v2
enabled/v1 disabled sin IAM para web o worker. Un plan Terraform provisional y
no mutante mostró dos updates in-place —Service y Job— más la creación del único
binding `secretAccessor` para el worker. La activación final cambiará ambos al
nuevo digest, mantendrá Web en mock sin clave, pondrá sólo el worker en real y
fijará `CVA_MAX_JOB_COST_USD=0.55`. Build, IAM, apply, deploy y E2E continúan
pendientes de gate explícito.

## Historial — preparación 1.1.2 y rotación

Estado al 2026-08-10: el proyecto OpenAI dedicado `PruebasPersonalizadas`
(`proj_te2wY3kbHAkFp8IgjglH063t`) quedó identificado mediante una sesión
autenticada de Platform. La clave histórica permanece en la versión numérica
`1` de `cva-openai-api-key` y no es apta para uso futuro. La rotación autorizada
creó la clave restringida `cva-stage2-qualification-20260810`, la transfirió
directamente a Secret Manager como versión `2` y verificó esa versión como
`enabled` e inyectable sin registrar el payload. Un `models.list` no facturable
autenticó correctamente y devolvió únicamente `gpt-5.6-luna`.

La baja del proveedor continúa pendiente: Platform aceptó seis veces la
confirmación del target histórico —incluida la vista organizacional—, pero la
clave anterior siguió autenticando.
La API administrativa oficial respondió `403` a la credencial de proyecto y
no se amplió autoridad mediante una Admin API key. Para preservar el orden
autorizado, la versión `1` sigue `enabled` y no se inició la qualification. Las
claves no existen en el repositorio, CI, Service web ni runtime cloud. El cloud
vigente conserva `CVA_MODEL_MODE=mock` y
`CVA_P10_ENABLED=false`. Ningún paso de este documento autoriza datos
estudiantiles reales, Etapa 3 o P10.

## Checkpoint previo a la evaluación manual 1.1.2

La rama alcanza `OPENAI_REAL_V112_OFFLINE_GATE_PREPARED`: prompt pack 1.1.2,
dry-run 18/18, P05 durable y cap USD 0.32. Esto no declara
`OPENAI_REAL_MANUAL_EVAL_READY`. La verificación
read-only más reciente mostró spend USD 3.78/5.00, USD 1.22 disponibles, alerta
USD 4.00 y Luna como único modelo permitido. Antes de una request deben
cumplirse, en este orden:

1. revisión humana del P0 P01 y aceptación explícita de la remediación;
2. rotación humana de la clave y verificación de la nueva versión sin leerla;
3. revalidación read-only de proyecto, modelo, spend, alerta y rate limits;
4. aprobación billable específica con cap máximo USD 0.32;
5. ejecución única del entrypoint versionado, sólo con corpus sintético.

El propietario completó el paso 1 y autorizó los pasos 2–5 con cap total USD
0.32. El paso 2 está incompleto por la baja pendiente descrita arriba; la nueva
versión ya pasó autenticación, pero la rotación exige además rechazo empírico
de la clave anterior y deshabilitación posterior de la versión `1`. La decisión
no cierra aún el P0: `oa-p01-injection-md` debe pasar como primer caso real
v1.1.2. La autorización de qualification permanece intacta porque no se creó
ninguna Responses request.

El entrypoint materializa esa separación mediante
`CVA_OPENAI_P01_V112_REMEDIATION_DECISION=OPENAI_P01_V112_REMEDIATION_ACCEPTED`
y, por separado,
`CVA_OPENAI_REAL_QUALIFICATION_APPROVAL=OPENAI_REAL_SYNTHETIC_QUALIFICATION_APPROVED`.
La primera decisión sólo es válida para los hashes P01 1.1.2 documentados; el
harness los recalcula y bloquea cualquier drift antes de leer
`CVA_OPENAI_API_KEY`. La segunda variable no puede cerrar el P0 por sí sola.

La rotación descrita fue autorizada expresamente; su única mutación pendiente
es revocar el target histórico y, sólo tras verificar su rechazo, deshabilitar
Secret Manager versión `1`. Cambiar IAM, billing/límites, cloud, deploy o
Terraform sigue siendo una mutación separada sin autorización.

### Verificación content-free de la rotación

`check_openai_key_state.py` acepta la credencial exclusivamente por stdin,
desactiva retries del SDK, ejecuta un solo `models.list` no facturable y emite
sólo estado, código, conteos y status HTTP seguro. Una desconexión, 403, 429 o
cualquier resultado distinto de 401 nunca se interpreta como revocación.

Antes de deshabilitar la versión histórica, se exige:

```bash
gcloud secrets versions access 1 \
  --secret=cva-openai-api-key --project=cva-experimento-wiljms |
  .venv/bin/python scripts/check_openai_key_state.py --expect revoked
```

La versión nueva se comprueba por separado:

```bash
gcloud secrets versions access 2 \
  --secret=cva-openai-api-key --project=cva-experimento-wiljms |
  .venv/bin/python scripts/check_openai_key_state.py \
  --expect active --required-model gpt-5.6-luna
```

Ninguna de estas órdenes coloca el valor en argumentos, environment, archivos
o salida. Sólo el primer PASS autoriza deshabilitar la versión `1`; ambos PASS
son precondición de la qualification.

## Fronteras obligatorias

1. Una persona autorizada crea o selecciona un proyecto OpenAI dedicado a este
   experimento, separado de uso personal o producción.
2. Configura billing, un límite mensual y alertas compatibles con el presupuesto
   aprobado. Para `LUNA_BASELINE_V1` confirma acceso únicamente a
   `gpt-5.6-luna`; Sol no se usa en este gate.
3. Crea una clave de proyecto con el mínimo alcance disponible. La clave se
   copia directamente a Secret Manager; nunca se pega en Codex, chat, tickets,
   shell history, tfvars, logs, CI, Git o documentos.
4. Registra fuera de Git únicamente el número de versión del secreto. El valor
   nunca entra a Terraform.
5. Solicita un checkpoint humano separado para el smoke facturable. Tener una
   clave no es autorización para usarla.

`store=false` está fijado en cada request. Esto no se presenta como Zero Data
Retention: ZDR requiere aprobación separada del proyecto y las políticas de
retención aplicables deben verificarse antes de cualquier dato no sintético.
No se usa background mode, estado conversacional ni herramientas.

## Preparación de Secret Manager sin valor

El primer plan crea solamente el contenedor protegido:

```hcl
enable_openai_secret_container = true
enable_openai_real_provider    = false
openai_api_key_secret_version  = null
openai_max_job_cost_usd        = null
```

Tras revisar y aplicar ese plan, una persona autorizada agrega el valor por un
canal privado de Google Cloud. Un ejemplo interactivo es:

```bash
gcloud secrets versions add cva-openai-api-key --data-file=- \
  --project=PROJECT_ID
```

La entrada estándar debe provenir directamente del teclado del operador y no
quedar en un archivo, chat ni argumento visible. El agente puede abrir la PTY,
pero nunca solicita, lee, imprime ni reenvía el valor.
Revocar y crear una versión nueva es el rollback ante cualquier sospecha de
exposición.

## Activación posterior, todavía no autorizada

Solo después de smoke y evaluación real aprobados se fija el número de versión
y se revisa un plan Terraform:

```hcl
enable_openai_secret_container = true
enable_openai_real_provider    = true
openai_api_key_secret_version  = "VERSION_NUMERICA"
openai_max_job_cost_usd        = PRESUPUESTO_APROBADO
```

La precondición impide real mode sin runtime, contenedor, versión fijada y techo
agregado por job autorizado. IAM
concede `roles/secretmanager.secretAccessor` solo a la cuenta del worker. El Job
recibe `CVA_OPENAI_API_KEY`; el Service web no recibe clave ni modo real. El
Service conoce solo el flag no secreto `CVA_WORKER_MODEL_MODE`. La edición
interactiva P05 persiste un job y descriptor antes del dispatch; no existe un
camino directo al gateway en el proceso web. Service y Job reciben el mismo
techo no secreto `CVA_MAX_JOB_COST_USD`
para que la autorización previa y el saldo durable coincidan. P10 se inyecta
siempre como `false`. El despliegue continúa usando Cloud Build, digest
inmutable y Terraform; nunca `gcloud run ... update`.

Antes de aplicar se exige plan guardado, revisión de IAM/secretos/env/imagen,
Service y Job en el mismo digest cuando corresponda, health/readiness, privado
anónimo 401 y dos planes vivos consecutivos sin drift. CI permanece sin clave.

## Smoke mínimo y doble autorización

El comando falla sin presupuesto, luego sin credencial y finalmente sin la
aprobación independiente. No se debe ejecutar todavía:

```bash
export CVA_OPENAI_BILLABLE_SMOKE_APPROVAL=OPENAI_BILLABLE_SMOKE_APPROVED
cv-stage0 real-provider-smoke --budget-usd 0.06 --allow-billable
```

La clave se suministra por el canal privado acordado como
`CVA_OPENAI_API_KEY`. El smoke hace como máximo una llamada P11 con datos
sintéticos, `gpt-5.6-luna`, esfuerzo `low`, retries del gateway y SDK iguales a
cero. Su upper bound vigente es USD 0.0112054 y el techo propuesto sigue siendo
USD 0.06; el spend limit del proyecto no amplía esa autorización. El operador
registra tokens, costo estimado/observado, modelo efectivo, latencia, resultado
y hashes; nunca payload u output.

## Checkpoint previo al primer gasto

`OPENAI_BILLABLE_SMOKE_APPROVAL_REQUIRED` quedó alcanzado el 2026-08-08 sin
acceder a la clave y sin ejecutar una llamada a Responses. La configuración del
proyecto lista únicamente `gpt-5.6-luna` entre los modelos permitidos, por lo
que `OPENAI_LUNA_ACCESS=OK` se refiere al acceso no facturable visible en
Platform, no a una prueba de autenticación del payload secreto.

| Control | Valor verificado |
|---|---|
| Proyecto OpenAI | `PruebasPersonalizadas` (`proj_te2wY3kbHAkFp8IgjglH063t`) |
| Secret Manager | `cva-openai-api-key`, versión numérica `1`, `enabled`; payload no leído |
| Smoke | P11, `gpt-5.6-luna`, `reasoning_effort=low`, una llamada máxima |
| Retries | gateway `0`, prompt `0`, SDK `0` |
| Request efectivo | 7,003 bytes serializados; schema estricto 3,777 bytes; formato estructurado 3,861 bytes; envelope 1,278 bytes |
| Input upper bound | 8,027 tokens, incluidos 1,024 tokens de framing conservador |
| Output máximo | 8,000 tokens |
| Precio Luna vigente | USD 0.20/M input, USD 0.02/M cached input y USD 1.20/M output |
| Costo upper bound | USD 0.0112054, sin asumir cache |
| Presupuesto propuesto | USD 0.06; no autorizado todavía |
| Fronteras | datos sintéticos, P10 off, sin Sol, sin tools, `store=false`, `background=false` |
| Cloud/CI | Web y Worker sin clave; ambos en mock/P10 false; IAM del secreto vacío; CI sin clave |
| Consumo de este checkpoint | 0 inferencias, 0 tokens facturables, USD 0.00 |

Este fue un checkpoint histórico previo al gasto. Antes de la llamada del
2026-08-09, OpenAI Platform mostró un spend limit activo de USD 5.00, USD 3.77
usado, USD 1.23 disponible, reset en 23 días y alerta al 80% (USD 4.00). También
mostró `gpt-5.6-luna` como único modelo permitido. Esos límites externos no
ampliaron el techo independiente y humano de USD 0.06 para el smoke.

## Resultado del primer smoke real — 2026-08-09

`OPENAI_REAL_SMOKE_PASS` se alcanzó mediante el único entrypoint versionado,
`cv-stage0 real-provider-smoke --budget-usd 0.06 --allow-billable`. El intento
anterior del harness efímero había fallado localmente por usar `routes=` en vez
de `real_routes=`: registró cero Responses requests, cero retries y USD 0.00.
No se amplió la API de `ModelGateway` ni se cambiaron adapter, rutas o contratos.

Antes del gasto, una regresión localizada ejecutó el CLI real con un cliente
OpenAI falso y el `ModelGateway` auténtico, alcanzando la frontera de transporte
con `network_calls=0` y `billable_calls=0`. La suite local quedó en 457 passed y
16 skips PostgreSQL explícitos; los 40 tests focalizados de CLI/adapter pasaron.
El commit `e1f6714e6d8fd52f4404c8f9f16edc21f8320627` quedó publicado y la CI
`31293361151` terminó 7/7 verde antes de consumir el secreto.

| Metadata segura | Resultado observado |
|---|---|
| Perfil / prompt / schema | `LUNA_BASELINE_V1`; `P11_SCHEMA_REPAIR_V1` `1.1.1`; schema `1.1.0` |
| Modelo solicitado / efectivo | `gpt-5.6-luna` / `gpt-5.6-luna` |
| Reasoning | `low` |
| Responses requests / attempts | 1 / 1 |
| Retries | gateway 0, prompt 0, SDK 0 |
| Tokens | input 1,365; cached input 0; output 257; reasoning 57 |
| Latencia | 3,832 ms |
| Costo estimado post-usage / costo real calculado | USD 0.0099411 / USD 0.0006495 |
| Validación | schema PASS; Pydantic PASS; contextual PASS |
| Request ID hash | `sha256:e819a8b471de6f3092ea6495f23b2b57bd70df597e481dce1434bc49a6f94299` |
| Output hash | `sha256:7a4cd0cf8103b85191a28d9e26c9b30f94cf9abf678184eb2e84bdcba3e89ede` |
| Fronteras | fixture sintético; P10 0; Sol 0; tools 0; `store=false`; `background=false` |

En ese checkpoint se registró que la versión `1` del secreto se entregó sin
echo directamente al environment del proceso y quedó fuera de argumentos,
Git, logs y documentación. La revisión local posterior descrita al inicio de
este documento obliga a rotarla antes de reutilizarla. No se ejecutó una
segunda request ni se continuó con Luna-medium/high, canaries, golden set real,
E2E, deploy, IAM,
PR, merge ni Etapa 3.

Fuentes oficiales: [Responses API](https://developers.openai.com/api/docs/guides/responses),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Reasoning](https://developers.openai.com/api/docs/guides/reasoning),
[controles y retención de datos](https://developers.openai.com/api/docs/guides/your-data)
y [SDK Python oficial](https://github.com/openai/openai-python).
