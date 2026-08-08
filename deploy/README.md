# Despliegue experimental de Etapa 2

Este directorio contiene el runbook y la infraestructura declarativa de E2.
Ningún comando de esta guía se ejecuta automáticamente al validar el
repositorio: crear cuentas, cargar secretos, migrar la base y aplicar Terraform
siguen siendo acciones externas, explícitas y revisadas. El entorno conserva
`CVA_MODEL_MODE=mock`, `CVA_P10_ENABLED=false` y
`CVA_REQUIRE_LIBMAGIC=true`; no se autorizan IA real ni datos estudiantiles
reales.

## Invariantes operativos

- Terraform es el único propietario de la imagen de Cloud Run Service y Job.
  Cloud Build verifica, construye y publica, pero nunca ejecuta
  `gcloud run ... update`.
- Cloud Build ejecuta contratos, backend, artefactos de despliegue, seguridad y
  los gates frontend (`typecheck`, tests, build y `npm audit`) antes de publicar
  la etiqueta declarada en `images`.
- `container_image` solo acepta
  `REGION-docker.pkg.dev/PROJECT/REPOSITORY/application@sha256:<64 hex>` para la
  región, proyecto y repositorio configurados en el mismo plan. Service y Job
  reciben exactamente esa referencia.
- El Job conserva una tarea, paralelismo uno y `max_retries = 0`. Retry,
  cancelación y resume de E2 pertenecen a los registros durables de la
  aplicación, no a reintentos opacos de Cloud Run.
- Cloud exige `postgresql+psycopg://`; `/api/health` es liveness sin
  dependencias y `/api/readiness` comprueba PostgreSQL y la superficie de
  migración esperada.
- Artifact Registry y secretos tienen `prevent_destroy`; los secretos, Service
  y Job activan además protección de borrado del proveedor. Desmontar el
  entorno exige un cambio de código revisado y un plan separado: nunca un
  `terraform destroy` improvisado.

## Boundary 1: bootstrap sin runtime

Copiar el ejemplo a un archivo fuera del repositorio, completar solo valores
públicos y mantener `enable_runtime_resources = false` y
`container_image = ""`:

```bash
cp deploy/terraform/terraform.tfvars.example /tmp/cva-stage2.tfvars
chmod 600 /tmp/cva-stage2.tfvars
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage2.tfvars \
  -out=/tmp/cva-stage2-bootstrap.tfplan
terraform -chdir=deploy/terraform apply \
  /tmp/cva-stage2-bootstrap.tfplan
```

Este boundary habilita APIs y crea Artifact Registry, identidades y
contenedores vacíos de Secret Manager. No crea todavía Service ni Job.

## Boundary 2: migraciones PostgreSQL 001 -> 002 -> 003

Antes de migrar se debe detener todo writer, capturar un backup restaurable y
registrar su identificador fuera de Git. En una base vacía, el orden único es:

1. `deploy/supabase/migrations/202607310001_stage1.sql`;
2. `deploy/supabase/migrations/202608070002_idempotency_capability_hygiene.sql`;
3. `deploy/supabase/migrations/202608070003_stage2_experimental.sql`.

Cada archivo contiene su propia transacción y debe ejecutarse con fallo cerrado:

```bash
PGSERVICE=cva-stage2-admin psql -X --set=ON_ERROR_STOP=1 \
  --file=deploy/supabase/migrations/202607310001_stage1.sql
PGSERVICE=cva-stage2-admin psql -X --set=ON_ERROR_STOP=1 \
  --file=deploy/supabase/migrations/202608070002_idempotency_capability_hygiene.sql
PGSERVICE=cva-stage2-admin psql -X --set=ON_ERROR_STOP=1 \
  --file=deploy/supabase/migrations/202608070003_stage2_experimental.sql
```

Una base E1 que ya tenga 001 y 002 verificadas aplica únicamente 003; no se
reproducen migraciones ya registradas. Después se comprueban RLS, grants,
triggers append-only, constraints y `/api/readiness` antes de habilitar tráfico.
La URL o credencial PostgreSQL vive en un `PGSERVICE` externo, nunca en el
comando, logs, tfvars o Git.

## Boundary 3: configuración externa

Una persona autorizada debe cargar fuera de Git versiones numéricas de
`database_url`, `session_secret`, `r2_access_key_id` y
`r2_secret_access_key` en Secret Manager; configurar Auth Supabase y la
membresía invitada; y confirmar que R2 permanece privado, sin `r2.dev` ni
dominio público, con CORS y lifecycle revisados. La URL y publishable key de
Supabase son públicas y son los únicos valores Supabase compilados por Vite.

## Boundary 4: build verificado y digest real

El build manual siguiente devuelve un build ID real. El trigger GitHub usa el
mismo `deploy/cloudbuild.yaml` y la misma secuencia de gates:

```bash
CVA_STAGE2_PROJECT=cva-experimento-wiljms
CVA_STAGE2_REGION=us-east1
CVA_STAGE2_REPOSITORY=comprehension-verification
CVA_STAGE2_SOURCE_SHA="$(git rev-parse HEAD)"
test -z "$(git status --porcelain=v1)"

CVA_STAGE2_BUILD_ID="$(gcloud builds submit \
  --project="$CVA_STAGE2_PROJECT" \
  --region="$CVA_STAGE2_REGION" \
  --config=deploy/cloudbuild.yaml \
  --substitutions=COMMIT_SHA="$CVA_STAGE2_SOURCE_SHA",_REGION="$CVA_STAGE2_REGION",_REPOSITORY="$CVA_STAGE2_REPOSITORY",_IMAGE=application,_VITE_SUPABASE_URL=SUPABASE_URL,_VITE_SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY \
  --async --format='value(id)')"

gcloud builds log --stream "$CVA_STAGE2_BUILD_ID" \
  --project="$CVA_STAGE2_PROJECT" --region="$CVA_STAGE2_REGION"
test "$(gcloud builds describe "$CVA_STAGE2_BUILD_ID" \
  --project="$CVA_STAGE2_PROJECT" --region="$CVA_STAGE2_REGION" \
  --format='value(status)')" = SUCCESS
```

Cloud Build publica la etiqueta `$BUILD_ID` solo si todos los pasos terminan
bien. El digest se resuelve después de esa publicación desde Artifact Registry,
sin confundirlo con el ID de build ni con una etiqueta mutable:

```bash
CVA_STAGE2_TAG="$CVA_STAGE2_REGION-docker.pkg.dev/$CVA_STAGE2_PROJECT/$CVA_STAGE2_REPOSITORY/application:$CVA_STAGE2_BUILD_ID"
CVA_STAGE2_BUILD_DIGEST="$(gcloud builds describe "$CVA_STAGE2_BUILD_ID" \
  --project="$CVA_STAGE2_PROJECT" --region="$CVA_STAGE2_REGION" \
  --format='value(results.images[0].digest)')"
CVA_STAGE2_REGISTRY_DIGEST="$(gcloud artifacts docker images describe \
  "$CVA_STAGE2_TAG" --project="$CVA_STAGE2_PROJECT" \
  --format='value(image_summary.digest)')"
printf '%s\n' "$CVA_STAGE2_BUILD_DIGEST" | grep -Eq '^sha256:[0-9a-f]{64}$'
test "$CVA_STAGE2_BUILD_DIGEST" = "$CVA_STAGE2_REGISTRY_DIGEST"
CVA_STAGE2_DIGEST="$CVA_STAGE2_BUILD_DIGEST"
CVA_STAGE2_IMAGE="${CVA_STAGE2_TAG%:*}@$CVA_STAGE2_DIGEST"
printf '%s\n' "$CVA_STAGE2_IMAGE" > /tmp/cva-stage2-container-image.txt
```

Se copia esa referencia inmutable al tfvars externo, se activa
`enable_runtime_resources = true`, y se revisa el plan antes de aplicar:

```bash
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage2.tfvars \
  -out=/tmp/cva-stage2-runtime.tfplan
terraform -chdir=deploy/terraform apply /tmp/cva-stage2-runtime.tfplan
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage2.tfvars -detailed-exitcode
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage2.tfvars -detailed-exitcode
```

Los dos planes consecutivos posteriores al apply deben terminar con exit 0.
Exit 2 indica drift o cambios pendientes y debe investigarse; no se aplica a
ciegas.

## Recovery y rollback

El rollback normal cambia únicamente `container_image` a un digest E2 conocido
como bueno y pasa nuevamente por plan/aprobación Terraform. Mantener el schema
E2 evita perder historial de retry, acciones, feedback, exports y aprobación
masiva.

La recuperación de schema a E1 es excepcional y fail-closed. Solo después de
detener Service/Job, confirmar el backup restaurable y verificar que no se
descartará ningún hecho E2 se ejecuta:

```bash
PGSERVICE=cva-stage2-admin psql -X --set=ON_ERROR_STOP=1 \
  --file=deploy/supabase/rollbacks/202608070003_stage2_experimental_recovery.sql
```

El script toma locks y rechaza la operación si existen múltiples submissions,
historial de control/reintentos, metadata de resume/export o registros
append-only E2. Si un guard falla, la transacción conserva íntegro el schema E2:
no se fuerzan `DROP`, no se editan los guards y se restaura el último digest E2
conocido mientras se exportan o resuelven los datos señalados. Solo una
recuperación exitosa autoriza verificar el schema E1 y planificar una imagen
anterior compatible.

## Verificación posterior

```bash
CVA_STAGE2_SERVICE_URI="$(terraform -chdir=deploy/terraform output -raw service_uri)"
CVA_STAGE2_SERVICE_NAME="$(terraform -chdir=deploy/terraform output -raw service_name)"
CVA_STAGE2_JOB_NAME="$(terraform -chdir=deploy/terraform output -raw job_name)"
CVA_STAGE2_EXPECTED_IMAGE="$(terraform -chdir=deploy/terraform output -raw runtime_container_image)"
curl --fail "$CVA_STAGE2_SERVICE_URI/api/health"
curl --fail "$CVA_STAGE2_SERVICE_URI/api/readiness"
CVA_STAGE2_SERVICE_IMAGE="$(gcloud run services describe \
  "$CVA_STAGE2_SERVICE_NAME" --project="$CVA_STAGE2_PROJECT" \
  --region="$CVA_STAGE2_REGION" \
  --format='value(spec.template.spec.containers[0].image)')"
CVA_STAGE2_JOB_IMAGE="$(gcloud run jobs describe \
  "$CVA_STAGE2_JOB_NAME" --project="$CVA_STAGE2_PROJECT" \
  --region="$CVA_STAGE2_REGION" \
  --format='value(spec.template.spec.template.spec.containers[0].image)')"
test "$CVA_STAGE2_SERVICE_IMAGE" = "$CVA_STAGE2_EXPECTED_IMAGE"
test "$CVA_STAGE2_JOB_IMAGE" = "$CVA_STAGE2_EXPECTED_IMAGE"
test "$(gcloud run services describe "$CVA_STAGE2_SERVICE_NAME" \
  --project="$CVA_STAGE2_PROJECT" --region="$CVA_STAGE2_REGION" \
  --format='value(status.conditions[0].status)')" = True
test "$(gcloud run jobs describe "$CVA_STAGE2_JOB_NAME" \
  --project="$CVA_STAGE2_PROJECT" --region="$CVA_STAGE2_REGION" \
  --format='value(status.conditions[0].status)')" = True
```

Finalmente se confirma que Service y Job usan el mismo digest, que el entorno
sigue en mock/P10 off, que un job durable sobrevive al cierre/reapertura del
navegador y que retry/cancel/resume conserva sus `stage_runs`. El gate maestro
del 2026-08-07 autoriza estos boundaries únicamente para el target indicado y
con datos sintéticos; no autoriza Etapa 3, merge a `main`, modelos ni datos
reales.
