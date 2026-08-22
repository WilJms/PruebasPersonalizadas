# Setup gobernado del proveedor OpenAI

> **Estado ADR-037 (2026-08-14):** esta superficie se conserva como control
> fail-closed y documentación histórica. No existe autorización vigente para
> usar el harness legado como gate, seleccionar modelo, resolver un secreto o
> ejecutar requests. La disponibilidad técnica nunca sustituye una autoridad
> futura exacta y separada.

## Superficie técnica retenida — capacidad sintética post-claim, no autorización actual

El producto y el Service web permanecen mock y no reciben clave. P10 y datos
estudiantiles reales siguen prohibidos. El worker ordinario también permanece
mock y su service account no puede leer la clave. Terraform sólo puede crear un
Job/SA eval-only separado mediante `enable_synthetic_evaluation_provider`,
desactivado por defecto; el Service web no recibe permiso para invocarlo. Esa
superficie recibe referencia de versión numérica de Secret Manager, SHA
candidato y ceilings de requests/costo. No monta `CVA_OPENAI_API_KEY`.

Esa configuración no autoriza transporte. El worker eval-only primero reclama el
`CVA_CLAIM_JOB_ID` exacto. Luego, dentro de PostgreSQL, consume una
`synthetic_provider_authorization` append-only ligada a tenant, kind,
aggregate, attempt, hashes exactos de todos los artefactos sellados, SHA,
boundary hash de prompts/schemas/validators/routing, Luna, versión de secreto,
expiración y caps. La inserción única en `synthetic_provider_claims` consume la
autorización exactly-once. Sólo después se consulta Secret Manager y se crea el
adapter con request cap; cualquier divergencia falla `SECURITY` con cero
resolver, cero construcción de transporte y cero request.

La autorización se crea server-side para un job ya durable y no existe endpoint
web que la fabrique. Retry/resume requiere otro job y otra autorización. El
estado cloud vivo histórico descrito debajo no se usa como prueba del candidato
actual: esta iteración no ejecuta build, deploy, apply ni E2E cloud.

El control-plane versionado es explícito y no despacha ni lee secretos:

```bash
python scripts/authorize_synthetic_provider_job.py \
  --job-id JOB_ID \
  --authorization-id AUTHORIZATION_ID \
  --candidate-sha EXACT_40_HEX_SHA \
  --secret-version-resource projects/PROJECT/secrets/SECRET/versions/N \
  --max-requests N --max-cost-usd USD \
  --created-by OPERATOR_ID
```

Requiere `CVA_DATABASE_URL=postgresql+psycopg://...` fuera del historial de
shell. La salida sólo contiene IDs, hashes, caps y conteos.

## Historial — worker real desplegado; P04 v1.1.9 pendiente de recanary

Web permanece mock y sin clave; worker real usa exclusivamente
`cva-openai-api-key` v2. Ambos están Ready sobre el digest inmutable
`sha256:04032e44c4177318545ae15a1dc48a9a72b0b04411c86f92f30dfb87a4d6b95d`,
construido desde `fefea94d25a974ddf05e71f7212616e625ee5303` por Cloud Build
`89cff4cb-3b8e-4abf-87e2-af82581ad078` `SUCCESS/VERIFIED`. Build, Artifact
Registry y procedencia firmada coinciden.

El único plan aplicado tenía SHA-256
`4adf5d8526efefdabe251c26ea12429b74971c35d825eaedaf8ad5eb220fc00e` y
dos updates in-place de imagen, sin create/delete/replace/adicional; el apply
terminó 0/2/0. Worker conserva USD 0.55, P10 false, task/paralelismo 1/1 y
`maxRetries=0`; IAM del secreto contiene sólo al worker. Health/readiness y la
ruta privada anónima pasaron, y dos planes posteriores dieron `No changes`.
No hubo jobs ni Responses durante el despliegue.

El E2E sintético sobre ese digest pasó P01-P03, persistió seis decisiones y se
detuvo en P04 1.1.8: el schema provider fue válido, pero un diagnóstico usó un
`evidence_id` no incluido en la allowlist de dos IDs. La ejecución terminó
`FAILED/SECURITY`, sin retry ni P05. Fueron 4 Responses/USD 0.02256005 y cero
P10/P11/Sol/fallback/retries.

P04 1.1.9 aclara las allowlists tipadas de `diagnostics[].evidence_ids` y
`source_ids` sin relajar el validador. El dry-run acoplado P04→P05 pasa con
dos transportes fake, 0 red/billable y ceiling USD 0.05046625 bajo cap USD
0.06. En ese checkpoint la evidencia era 16/18 hasta una única recanary real y
su reporte content-free; esa secuencia ya no constituye autoridad actual.

## Historial — evidencia 18/18 desplegada antes del stop fresco

El SHA `88416b522414f316613bea96ad08687e8a335a38` fue desplegado como
`sha256:d31899535c76b08ee79163479530b044783b73956c6fe228a01a3e603008893d`
por el build `441be72d-04ae-46e9-b150-6eec1032c8d6`. Ese checkpoint y su
evidencia 18/18 quedaron sustituidos por la frontera vigente descrita arriba.

## Historial — evidencia 18/18; deploy pendiente

Web permanece mock/sin clave y worker real sobre
`sha256:9048f9da77fda2b5ab8d6a974d9b4b8b5a2b6a141062bcb36751b8516691e3ab`,
con secreto v2, P10 false, USD 0.55, 1/1 y `maxRetries=0`. Ese digest contiene
el candidato `dfd102d…`, no la remediación local actual.

El E2E más reciente llegó a P05 en dos jobs: P01-P05 fueron estructural y
contextualmente válidos, P04 persistió blueprint `READY`, y P05 respondió
`READY/REJECT`. El stop dejó edición, aprobación y submission sin ejecutar.
Fueron cinco Responses y USD 0.03490275; P10/P11/Sol/fallback/retries cero.

El nuevo contrato transporta `DecisionOption` autocontenido; P04 1.1.7 y P05
1.1.5 aplican ADR-030 correctamente. Los opt-ins acoplados siguientes ya están
cerrados y no pueden volver a leer la clave ni crear transporte:

```text
CVA_OPENAI_BLUEPRINT_V117_V115_REMEDIATION_DECISION
CVA_OPENAI_BLUEPRINT_V117_V115_TIMEOUT_REMEDIATION_DECISION
CVA_OPENAI_BLUEPRINT_V117_V115_TIMEOUT_RECOVERY_APPROVAL
```

El opt-in P06 también quedó cerrado después de su único PASS:

```text
CVA_OPENAI_P06_V112_DECISION_LINEAGE_RECANARY_APPROVAL
```

El gate acoplado original consumió exactamente P04→P05: P04 pasó y P05 agotó
el antiguo timeout de 120 s. Se detuvo con 2/2 Responses, USD 0.05106550 de
charge conservador bajo cap USD 0.06 y cero P10/P11/retries/fallback/Sol. Ese
approval está cerrado permanentemente. El perfil remediado usa 240 s en SDK y
245 s en gateway, y la recuperación exige los opt-ins distintos de arriba,
máximo dos Responses y el mismo cap USD 0.06. La recuperación terminó
PASS/PASS `READY` con exactamente dos Responses, USD 0.01645840 actual, cero
retries/P10/P11/Sol/fallback y quedó consumida. P06 usa un gate independiente
de una request/cap USD 0.03; terminó PASS `READY` en 1/1 Responses, USD
0.00148525 y sin rutas laterales/retries. La evidencia vigente es 18/18.

## Historial — P04 v1.1.6 validado; redeploy pendiente

Web permanece mock y sin clave. Worker sigue real sobre el digest
`sha256:97960034f6c4c6c3b2967d186035f0940e481f9e2c9bf9df24213cd30d31aaeb`,
con clave v2, P10 false, USD 0.55, 1/1 y `maxRetries=0`; ese digest todavía
contiene P04 v1.1.2.

Después de seis decisiones P03 durables, una única reanudación reutilizó
P01-P03 y ejecutó P04 más una P11. P04 pasó el schema del proveedor pero falló
Pydantic; P11 no reparó el contrato destino. El job y la task terminaron FAIL
y se detuvieron antes de P05, blueprint y submission. El E2E acumula cinco
Responses y USD 0.02453340, sin P10/Sol/fallback/retries.

P04 v1.1.6 explicita las invariantes cross-field que originaron el fallo. La
primera observación quedó inconclusa por pérdida externa del reporte y se cerró
sin replay; un gate de recuperación separado terminó PASS `READY` con una
Responses, USD 0.00537802 y schema/Pydantic/contexto/outcome PASS. Los dos
gates están consumidos:

```text
OPENAI_P04_V116_RECANARY_ALREADY_CONSUMED
OPENAI_P04_V116_EVIDENCE_RECOVERY_ALREADY_CONSUMED
```

El siguiente paso es construir y desplegar un SHA nuevo mediante los gates
Cloud Build/digest/Terraform; la evidencia focal no mutó cloud ni autoriza una
ejecución adicional por sí sola.

## Historial — worker real desplegado; E2E detenido en P03

Web permanece en mock y sin clave. Worker está desplegado en modo real sobre
el digest inmutable `sha256:97960034f6c4c6c3b2967d186035f0940e481f9e2c9bf9df24213cd30d31aaeb`,
lee únicamente `cva-openai-api-key` v2 y conserva P10 false, máximo USD 0.55,
task/paralelismo 1/1 y `maxRetries=0`.

El primer E2E real consumió una ejecución Cloud Run y tres Responses Luna.
P01-P03 fueron estructuralmente válidos, pero P03 dejó el job de dominio en
`NEEDS_REVIEW`; se detuvo sin reanudar, sin P05/submission y sin tocar build,
Terraform, IAM o secretos. El siguiente gate exige una decisión docente P03 y
autorización separada para el nuevo job de actividad que crea la UI.

## Historial — P11 directo consumido; corpus real 18/18

La canary P11 directa v1.1.4 autorizada sobre `976aadc` terminó PASS
`REPAIRED`: schema provider, Pydantic, contexto y outcome PASS, target inmutable
y reparación estructural mínima. Consumió exactamente una Responses request,
USD 0.00070015 calculados, P11 uno y retries/P10/Sol/fallback cero. Repetir el
opt-in bloquea antes del adapter con:

```text
OPENAI_P11_V114_DIRECT_ALREADY_CONSUMED
```

La evidencia real vigente cubre 18/18 casos hash-bound y no conserva contenido
del proveedor. El paso siguiente requiere gates nuevos y separados para
build/digest, IAM/Terraform deploy y E2E sintético OpenAI real.

En ese corte histórico, cloud conservaba `CVA_MODEL_MODE=mock` y ninguna clave
estaba montada. Ese estado fue sustituido por el despliegue segregado descrito
arriba: web mock, worker real y clave sólo en worker.

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

El gate posterior construyó el SHA `b4ec283…` en el build único `613270cf…`,
`SUCCESS/VERIFIED`, y Artifact Registry confirmó el digest
`sha256:979600…aaeb`. El plan sellado mostró y aplicó exactamente dos updates
in-place —Service y Job— más el único binding `secretAccessor` para el worker,
sin delete/replace. Web permanece mock sin clave; sólo worker quedó real con
v2, `CVA_MAX_JOB_COST_USD=0.55`, P10 false y 1/1/0. Health/readiness son 200,
privado anónimo 401 y dos planes posteriores no muestran cambios. El E2E
sintético real continúa pendiente de un gate billable explícito; no se ejecutó
ningún Job ni Responses request durante deploy.

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
