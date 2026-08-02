# Verificación externa pendiente de Etapa 1

Estado al 2026-08-01: **no ejecutada**. Esta guía requiere cuentas, facturación,
IAM y secretos reales, por lo que queda fuera de la corrección local. Consultar
`docs/IMPLEMENTATION_STATUS.md` para el estado Git/CI observado del commit que
se pretende verificar.

La checklist no autoriza Etapa 2 ni un proveedor de IA real. Todo el recorrido
debe conservar:

```text
CVA_MODEL_MODE=mock
CVA_P10_ENABLED=false
```

Una persona autorizada debe revisar costos, región, retención, identidades y
cada plan antes de `terraform apply`.

## 1. Recursos y secretos

Recursos externos mínimos:

- proyecto GCP experimental con facturación;
- proyecto Supabase vacío con PostgreSQL y Auth por email;
- bucket Cloudflare R2 privado y token limitado a ese bucket;
- repositorio GitHub privado y conexión de Cloud Build limitada al repositorio.

Datos públicos que sí pueden usarse en comandos: project ID, región, nombres de
Repository/Service/Job, URL y publishable key de Supabase, endpoint/nombre del
bucket R2, commit y digest de imagen.

Nunca introducir en chat, Git, tfvars versionados, substitutions, build args o
logs:

- password o URL autenticada de PostgreSQL;
- R2 Access Key ID/Secret Access Key o token Cloudflare;
- `CVA_SESSION_SECRET`;
- tokens GCP/GitHub/Supabase, secret/service-role keys o magic links;
- cualquier secreto de proveedor de IA.

La publishable key de Supabase es pública y es la única key compilada por Vite.

## 2. Preflight de repositorio

Trabajar solo desde el commit final aprobado de la rama/PR y comprobar que CI
remota está verde para ese SHA:

```bash
git rev-parse --show-toplevel
git remote get-url origin
git branch --show-current
git status --short
git rev-parse HEAD
gh pr view --json number,url,baseRefName,headRefName,headRefOid
gh pr checks --watch --fail-fast
```

No desplegar desde un árbol sucio ni desde un SHA distinto al observado por
GitHub Actions.

Crear un archivo de variables fuera del repositorio. Solo contiene valores
públicos y la referencia de imagen, que tampoco es secreta:

```bash
cp deploy/terraform/terraform.tfvars.example /tmp/cva-stage1.tfvars
chmod 600 /tmp/cva-stage1.tfvars
${EDITOR:-vi} /tmp/cva-stage1.tfvars
```

Para bootstrap deben permanecer:

```hcl
enable_runtime_resources = false
container_image          = ""
```

## 3. Bootstrap GCP sin runtime

La autenticación es interactiva y humana:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project PROJECT_ID
gcloud billing projects describe PROJECT_ID
```

Revisar y aplicar el primer boundary:

```bash
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform validate
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars \
  -out=/tmp/cva-stage1-bootstrap.tfplan
terraform -chdir=deploy/terraform show -no-color \
  /tmp/cva-stage1-bootstrap.tfplan
terraform -chdir=deploy/terraform apply \
  /tmp/cva-stage1-bootstrap.tfplan
```

El plan debe crear APIs, Artifact Registry, tres identidades y cuatro
contenedores vacíos de Secret Manager, pero ningún Service/Job. La cuenta de
Cloud Build no debe tener `roles/run.admin` ni permiso para actuar como web o
worker.

## 4. Supabase PostgreSQL y Auth

### 4.1 Migración

Aplicar la migración a una base vacía con el password solicitado en una terminal
privada. El comando de `psql` no incluye la contraseña:

```bash
export CVA_SUPABASE_DB_HOST='replace-with-session-pooler-host'
export CVA_SUPABASE_DB_USER='replace-with-postgres-user'
printf 'Supabase DB password: '
IFS= read -r -s PGPASSWORD
printf '\n'
export PGPASSWORD
psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 \
  -f deploy/supabase/migrations/202607310001_stage1.sql
```

Comprobar 24 tablas con RLS, cero grants a browser y dos triggers append-only:

```bash
psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 -Atc \
  "select count(*) || '|' || count(*) filter (where c.relrowsecurity) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r';"

psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 -c \
  "select grantee, table_name, privilege_type from information_schema.role_table_grants where table_schema='public' and grantee in ('anon','authenticated') order by 1,2,3;"

psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 -Atc \
  "select count(distinct trigger_name) from information_schema.triggers where trigger_schema='public' and trigger_name in ('model_calls_are_append_only','audit_events_are_append_only');"
unset PGPASSWORD
```

La verificación anterior demuestra la superficie seleccionada —tablas,
columnas, RLS y triggers—, no una equivalencia exhaustiva DDL↔ORM.

La URL secreta de aplicación debe ser completa, usar
`postgresql+psycopg://` y `sslmode=require`. El runtime rechaza SQLite,
`postgresql://` sin driver y URLs parciales.

### 4.2 Auth y membresía

1. usar signing key ES256 o RS256 y confirmar un JWKS compatible;
2. después del deploy, fijar Site URL y único redirect al origen HTTPS exacto;
3. invitar el único usuario sintético de prueba;
4. persistir su UUID en `public.users` y `public.workspace_roles` dentro de
   `tnt_experimental` con rol `TEACHER`.

No entregar una secret/service-role key a la aplicación: FastAPI usa la conexión
PostgreSQL y el browser solo la publishable key.

## 5. R2 privado

Comprobar que `r2.dev` está deshabilitado y no existe dominio público. Revisar
los plazos experimentales antes de aplicar:

```bash
npx wrangler login
npx wrangler r2 bucket dev-url get BUCKET
npx wrangler r2 bucket domain list BUCKET
npx wrangler r2 bucket lifecycle set BUCKET \
  --file deploy/r2/lifecycle.example.json
npx wrangler r2 bucket lifecycle list BUCKET
```

Después de conocer la URL de Cloud Run, copiar el ejemplo CORS a `/tmp`,
reemplazar el origen y aplicar. Debe haber un único origen HTTPS, métodos
`GET/PUT/HEAD`, header `Content-Type`, `ETag` expuesto y ningún wildcard.

## 6. Secret Manager

Obtener nombres mediante `terraform output -json runtime_secret_names`. Añadir
por stdin, nunca como argumento, estas cuatro versiones:

- URL `postgresql+psycopg://...`;
- R2 Access Key ID;
- R2 Secret Access Key;
- session secret aleatorio de al menos 32 caracteres.

Verificar solo metadata con `gcloud secrets versions list`; nunca leer ni
imprimir valores. `secret_version` del tfvars externo debe apuntar a una versión
numérica habilitada que exista para los cuatro secretos.

## 7. Imagen: Cloud Build publica, Terraform despliega

Terraform es el único propietario de la imagen desplegada. Cloud Build no
actualiza Service ni Job.

### 7.1 Construir y publicar

```bash
export CVA_BUILD_SA_EMAIL="$(terraform -chdir=deploy/terraform output -raw cloud_build_service_account)"
export CVA_BUILD_SA="projects/PROJECT_ID/serviceAccounts/${CVA_BUILD_SA_EMAIL}"
export CVA_BUILD_ID="$(gcloud builds submit . \
  --async \
  --project=PROJECT_ID \
  --region=REGION \
  --service-account="$CVA_BUILD_SA" \
  --config=deploy/cloudbuild.yaml \
  --substitutions=_REGION=REGION,_REPOSITORY=REPOSITORY,_IMAGE=application,_VITE_SUPABASE_URL=SUPABASE_URL,_VITE_SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY \
  --format='value(id)')"
gcloud builds log --stream "$CVA_BUILD_ID" --project=PROJECT_ID --region=REGION
test "$(gcloud builds describe "$CVA_BUILD_ID" --project=PROJECT_ID --region=REGION --format='value(status)')" = SUCCESS
```

Cloud Build ejecuta smoke local de health/readiness, publica y muestra la
referencia inmutable. Verificarla independientemente:

```bash
export CVA_TAGGED_IMAGE="REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY/application:${CVA_BUILD_ID}"
export CVA_IMAGE_DIGEST="$(gcloud artifacts docker images describe "$CVA_TAGGED_IMAGE" --project=PROJECT_ID --format='value(image_summary.digest)')"
case "$CVA_IMAGE_DIGEST" in
  sha256:????????????????????????????????????????????????????????????????) ;;
  *) echo 'digest inválido' >&2; exit 1 ;;
esac
export CVA_IMMUTABLE_IMAGE="${CVA_TAGGED_IMAGE%:*}@${CVA_IMAGE_DIGEST}"
printf '%s\n' "$CVA_IMMUTABLE_IMAGE"
```

### 7.2 Plan, apply y prueba de drift

Copiar `CVA_IMMUTABLE_IMAGE` en `container_image` del tfvars externo y cambiar
`enable_runtime_resources = true`. Luego:

```bash
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars \
  -out=/tmp/cva-stage1-runtime.tfplan
terraform -chdir=deploy/terraform show -no-color \
  /tmp/cva-stage1-runtime.tfplan
terraform -chdir=deploy/terraform apply \
  /tmp/cva-stage1-runtime.tfplan

gcloud run services describe SERVICE --project=PROJECT_ID --region=REGION \
  --format='value(spec.template.spec.containers[0].image)'
gcloud run jobs describe JOB --project=PROJECT_ID --region=REGION \
  --format='value(template.template.containers[0].image)'

terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars -detailed-exitcode
```

Service y Job deben usar el mismo digest. El plan posterior debe terminar 0;
exit 2 indica drift y bloquea la verificación.

## 8. GitHub Actions y trigger de Cloud Build

GitHub Actions debe estar verde sobre el mismo SHA desplegado. El trigger de
Cloud Build puede construir/publicar en `main`, pero no despliega directamente:
cada nueva imagen requiere copiar el digest a tfvars, revisar plan y aplicar
Terraform.

```bash
gh run list --workflow ci.yml --branch main --limit 3
gh run watch RUN_ID --exit-status
gcloud builds triggers describe TRIGGER --project=PROJECT_ID --region=REGION
```

No configurar substitutions secretas ni permisos `run.admin` para la cuenta de
build.

## 9. Verificación cloud obligatoria de E1-11

### 9.1 Runtime e infraestructura

```bash
export CVA_SERVICE_URI="$(terraform -chdir=deploy/terraform output -raw service_uri)"
curl --fail --show-error "$CVA_SERVICE_URI/api/health"
curl --fail --show-error "$CVA_SERVICE_URI/api/readiness"
test "$(curl -sS -o /tmp/cva-private-route.json -w '%{http_code}' "$CVA_SERVICE_URI/api/v1/session")" = 401
```

Comprobar además:

- identidades web/worker distintas;
- secrets por versión, nunca valores inline;
- `maxRetries = 0`, una tarea y paralelismo uno;
- startup probe a `/api/readiness` y liveness a `/api/health`;
- misma imagen `@sha256` en Service y Job;
- TTL de upload y download separados y dentro de límites.

### 9.2 E2E con fixtures sintéticos

1. entrar mediante magic link del usuario invitado;
2. crear una actividad de tres preguntas, cargar consigna/rúbrica sintéticas,
   ejecutar P01–P05 y aprobar blueprint;
3. crear la única submission, cargar un fixture y arrancar el pipeline;
4. anotar `job_id` y cerrar todo el navegador inmediatamente;
5. observar una ejecución real del Cloud Run Job;
6. abrir una sesión nueva y confirmar el estado durable terminal;
7. abrir todas las fuentes, aprobar Assessment y generar Assessment PDF, Guide
   PDF y JSON sin nuevas model calls;
8. comprobar CORS/PUT/GET R2 sin credenciales en requests o logs;
9. confirmar que una capacidad de descarga expira después de
   `CVA_DOWNLOAD_URL_TTL_SECONDS`;
10. verificar en PostgreSQL que el job esperado, y no otro, quedó terminal; un
    fallo queda `FAILED` y no dispara un retry automático.

Revisar logs por metadata/códigos, nunca por payload estudiantil:

```bash
gcloud logging read \
  'severity>=ERROR AND (resource.type="cloud_run_revision" OR resource.type="cloud_run_job")' \
  --project=PROJECT_ID --freshness=2h --limit=100
```

## 10. Evidencia y criterio de cierre

Guardar fuera del repositorio, con timestamps y secretos redactados:

- commit/PR/run de GitHub Actions;
- build ID, digest y dos planes Terraform, incluido el plan sin drift;
- outputs de health/readiness, Service/Job/IAM y ejecución;
- migración, tablas/RLS/grants/triggers y filas terminales;
- Auth, CORS/lifecycle/privacidad R2 y expiración de download;
- cierre/reapertura del navegador y exports;
- confirmación de gateway mock, P10 deshabilitado y cero secretos en logs.

E1-11 continúa **parcial y no cerrada** hasta que toda esta evidencia real
pase. Incluso entonces, esta checklist no declara `READY_FOR_STAGE_2`; requiere
un gate humano posterior y separado.
