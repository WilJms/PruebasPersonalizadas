# Setup gobernado del proveedor OpenAI

Estado al 2026-08-08: el propietario confirmó proyecto OpenAI dedicado, API key
de proyecto y USD 5.00 de saldo para pruebas iniciales. La clave aún no se ha
introducido en Secret Manager y no existe en el repositorio, CI, Service web ni
runtime cloud. El cloud vigente conserva `CVA_MODEL_MODE=mock` y
`CVA_P10_ENABLED=false`. Ningún paso de este documento autoriza datos
estudiantiles reales, Etapa 3 o P10.

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
Service conoce solo el flag no secreto `CVA_WORKER_MODEL_MODE`: cuando es real,
cualquier camino interactivo que intentara invocar el gateway directamente
falla con `MODEL_EXECUTION_REQUIRES_WORKER`, evitando una mezcla silenciosa con
mock. Service y Job reciben el mismo techo no secreto `CVA_MAX_JOB_COST_USD`
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
USD 0.06; el saldo de USD 5.00 no amplía esa autorización. El operador registra
tokens, costo estimado/observado, modelo efectivo, latencia, resultado y hashes;
nunca payload u output.

Fuentes oficiales: [Responses API](https://developers.openai.com/api/docs/guides/responses),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Reasoning](https://developers.openai.com/api/docs/guides/reasoning),
[controles y retención de datos](https://developers.openai.com/api/docs/guides/your-data)
y [SDK Python oficial](https://github.com/openai/openai-python).
