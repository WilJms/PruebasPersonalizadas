# Verificación externa pendiente de Etapa 1

Estado al 2026-08-01: **no ejecutada**. El boundary local está verde y el
repositorio está `READY_FOR_EXTERNAL_STAGE1_VERIFICATION`, pero E1-11 sigue
parcial. Esta guía comienza donde termina la auditoría local: requiere cuentas,
facturación, IAM y secretos reales. No autoriza Etapa 2 ni un proveedor de IA;
todo el recorrido debe conservar `CVA_MODEL_MODE=mock` y
`CVA_P10_ENABLED=false`.

No ejecutar automáticamente esta checklist. Una persona debe revisar costos,
región, retención, identidades y el plan de Terraform antes de cada `apply`.

## 1. Cuentas y recursos mínimos

| Sistema | Recurso mínimo | Acción exclusivamente humana |
|---|---|---|
| GCP | Un proyecto experimental dedicado, con facturación; `gcloud` y Terraform autenticados por una persona autorizada | Crear/seleccionar proyecto, aceptar facturación y otorgar al operador permisos para APIs, IAM, Cloud Build, Artifact Registry, Secret Manager y Cloud Run. |
| Supabase | Un proyecto vacío de prueba con PostgreSQL y Auth por email | Elegir región, conservar el password de DB fuera del chat, activar un signing key asimétrico ES256/RS256, configurar magic links y crear/invitar el único usuario de prueba. |
| Cloudflare R2 | Un bucket privado y un token **Object Read & Write** limitado a ese bucket | Aceptar facturación R2, crear bucket/token, mantener deshabilitados `r2.dev` y dominios públicos y ratificar retención. |
| GitHub/Cloud Build | Un repositorio privado con este árbol y una conexión de Cloud Build | Revisar/crear el primer commit, hacer push, instalar/autorizar la GitHub App de Cloud Build solo para ese repositorio y aprobar el trigger. |

No hace falta una cuenta, clave ni presupuesto de IA real.

## 2. Valores que sí y que no pueden compartirse

Valores no secretos que pueden proporcionarse para preparar comandos:

- GCP project ID, región y nombres de repository/service/job;
- URL del proyecto Supabase, project ref, publishable key y audiencia JWT;
- account ID/endpoint y nombre de bucket R2;
- recurso de repositorio/trigger de Cloud Build y URL final de Cloud Run;
- UUID de Auth y correo del usuario invitado, si la política de privacidad local
  permite compartirlos. No son credenciales, pero sí identificadores.

No introducir en chat, Git, `terraform.tfvars`, build args ni logs:

- password o URL autenticada de PostgreSQL;
- R2 Access Key ID, Secret Access Key o token de Cloudflare;
- `CVA_SESSION_SECRET`;
- access/refresh tokens de GCP, GitHub o Supabase, claves secret/service-role o
  enlaces magic-link;
- cualquier secreto de proveedor de IA.

Los secretos se capturan en una terminal privada, por stdin, y se envían
directamente a Secret Manager. La publishable key de Supabase es pública y es
la única key que se compila en Vite.

## 3. Preflight humano y variables públicas

El repositorio auditado no tenía `HEAD` ni remoto. Antes de cloud, una persona
debe revisar el árbol completo, crear el commit inicial y hacer push al remoto
privado. Verificación (debe terminar 0 y mostrar valores reales):

```bash
git rev-parse --verify HEAD
git remote get-url origin
git status --short
```

Desde la raíz del repositorio, definir solo datos públicos:

```bash
export CVA_GCP_PROJECT_ID='replace-with-project-id'
export CVA_GCP_REGION='us-central1'
export CVA_REPOSITORY_ID='comprehension-verification'
export CVA_SERVICE_NAME='cva-web'
export CVA_JOB_NAME='cva-worker'
export CVA_SUPABASE_URL='https://replace-with-project-ref.supabase.co'
export CVA_SUPABASE_PUBLISHABLE_KEY='replace-with-publishable-key'
export CVA_R2_ACCOUNT_ID='replace-with-account-id'
export CVA_R2_ENDPOINT_URL="https://${CVA_R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
export CVA_R2_BUCKET='replace-with-private-bucket-name'
```

Copiar el archivo de variables fuera del repositorio y editar únicamente los
valores anteriores. En este primer boundary deben quedar
`enable_runtime_resources = false`, `container_image = ""` y
`secret_version = "1"`.

```bash
cp deploy/terraform/terraform.tfvars.example /tmp/cva-stage1.tfvars
chmod 600 /tmp/cva-stage1.tfvars
${EDITOR:-vi} /tmp/cva-stage1.tfvars
```

Autenticación interactiva, realizada por la persona y nunca por el agente:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project "$CVA_GCP_PROJECT_ID"
gcloud auth list --filter=status:ACTIVE
gcloud billing projects describe "$CVA_GCP_PROJECT_ID"
```

## 4. Bootstrap GCP sin runtime

Esto habilita APIs y crea Artifact Registry, identidades separadas y cuatro
contenedores vacíos de Secret Manager. Todavía no crea Service ni Job.

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
terraform -chdir=deploy/terraform output -json
```

La revisión humana del plan debe confirmar cero recursos
`google_cloud_run_v2_service`/`google_cloud_run_v2_job`, ningún valor secreto y
una cuenta de build distinta de web/worker.

## 5. Supabase PostgreSQL y Auth

### 5.1 Aplicar y validar la migración

Usar una base nueva. Para migración, tomar del panel **Connect** el host/usuario
directo o session-pooler; la contraseña se solicita silenciosamente y nunca va
en el comando:

```bash
export CVA_SUPABASE_DB_HOST='replace-with-db-or-session-pooler-host'
export CVA_SUPABASE_DB_USER='replace-with-postgres-user'
printf 'Supabase DB password: '
IFS= read -r -s PGPASSWORD
printf '\n'
export PGPASSWORD
psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 \
  -f deploy/supabase/migrations/202607310001_stage1.sql
```

Comprobaciones exactas; los resultados esperados son `24|24`, cero filas de
grants y dos triggers:

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
```

Conservar la conexión de aplicación como secreto con el prefijo explícito
`postgresql+psycopg://` y `sslmode=require`. Para Cloud Run sin IPv4 adicional,
usar el **Supavisor session pooler, puerto 5432**, no transaction mode 6543.
Finalmente limpiar la contraseña del shell:

```bash
unset PGPASSWORD
```

### 5.2 Configurar Auth y membresía

Después de conocer la URL de Cloud Run, una persona debe:

1. en JWT Signing Keys, migrar/rotar la clave activa a **ES256** (preferida) o
   RS256; el backend deliberadamente no recibe el secreto legacy HS256;
2. comprobar que JWKS publica al menos una key compatible:

   ```bash
   curl --fail --show-error \
     "$CVA_SUPABASE_URL/auth/v1/.well-known/jwks.json" | \
     jq -e '.keys | length > 0 and all(.[]; (.alg == "ES256" or .alg == "RS256"))'
   ```

3. fijar en Supabase Auth URL Configuration el Site URL y único redirect
   permitido al origen HTTPS exacto de Cloud Run;
4. invitar/crear el usuario de prueba por email; `shouldCreateUser=false`
   impide que la aplicación cree cuentas;
5. copiar el UUID real desde `auth.users` y ejecutar en SQL Editor, sustituyendo
   los tres placeholders antes de confirmar:

```sql
begin;
insert into public.workspaces (id, name)
values ('tnt_experimental', 'Workspace experimental')
on conflict (id) do update set name = excluded.name;

insert into public.users (id, email)
values ('REPLACE_WITH_AUTH_USER_UUID', 'REPLACE_WITH_INVITED_EMAIL')
on conflict (id) do update set email = excluded.email;

insert into public.workspace_roles
  (user_id, workspace_id, role, can_approve_assessments)
values
  ('REPLACE_WITH_AUTH_USER_UUID', 'tnt_experimental', 'TEACHER', true)
on conflict (user_id, workspace_id) do update
set role = excluded.role,
    can_approve_assessments = excluded.can_approve_assessments;
commit;
```

No crear ni entregar una secret/service-role key a la aplicación: FastAPI usa
la conexión PostgreSQL y el browser usa solo la publishable key.

## 6. R2 privado

Una persona crea el bucket y un token **Object Read & Write** limitado a ese
bucket. Autenticar Wrangler interactivamente y comprobar que no hay URL pública:

```bash
npx wrangler login
npx wrangler r2 bucket list
npx wrangler r2 bucket dev-url get "$CVA_R2_BUCKET"
npx wrangler r2 bucket domain list "$CVA_R2_BUCKET"
```

El estado de `dev-url` debe ser deshabilitado y la lista de dominios vacía. Si
no lo está, corregirlo manualmente antes de continuar. Ratificar explícitamente
los defaults experimentales: abort multipart 1 día, `raw/` 30 días y
`exports/` 120 días. Si son aceptados:

```bash
cp deploy/r2/lifecycle.example.json /tmp/cva-r2-lifecycle.json
npx wrangler r2 bucket lifecycle set "$CVA_R2_BUCKET" \
  --file /tmp/cva-r2-lifecycle.json
npx wrangler r2 bucket lifecycle list "$CVA_R2_BUCKET"
```

El CORS se aplica solo después de obtener el origen Cloud Run exacto:

```bash
jq --arg origin "$CVA_SERVICE_URI" \
  '.rules[0].allowed.origins = [$origin]' \
  deploy/r2/cors.example.json > /tmp/cva-r2-cors.json
npx wrangler r2 bucket cors set "$CVA_R2_BUCKET" \
  --file /tmp/cva-r2-cors.json
npx wrangler r2 bucket cors list "$CVA_R2_BUCKET"
```

La regla debe contener un solo origen HTTPS, métodos `GET`, `PUT`, `HEAD`, solo
`Content-Type` como header permitido y `ETag` expuesto; nunca `*`.

## 7. Introducir secretos fuera del chat

Obtener los nombres no secretos y confirmar que cada contenedor está vacío.
En un bootstrap nuevo, la primera versión real de los cuatro debe ser `1`, que
es el valor fijado en `/tmp/cva-stage1.tfvars`.

```bash
export CVA_DB_SECRET_NAME="$(terraform -chdir=deploy/terraform output -json runtime_secret_names | jq -r '.database_url')"
export CVA_R2_ID_SECRET_NAME="$(terraform -chdir=deploy/terraform output -json runtime_secret_names | jq -r '.r2_access_key_id')"
export CVA_R2_SECRET_NAME="$(terraform -chdir=deploy/terraform output -json runtime_secret_names | jq -r '.r2_secret_access_key')"
export CVA_SESSION_SECRET_NAME="$(terraform -chdir=deploy/terraform output -json runtime_secret_names | jq -r '.session_secret')"
```

Captura silenciosa y envío por stdin:

```bash
printf 'CVA_DATABASE_URL (postgresql+psycopg, sslmode=require): '
IFS= read -r -s CVA_DATABASE_URL_SECRET
printf '\n'
printf '%s' "$CVA_DATABASE_URL_SECRET" | \
  gcloud secrets versions add "$CVA_DB_SECRET_NAME" --data-file=-
unset CVA_DATABASE_URL_SECRET

printf 'R2 Access Key ID: '
IFS= read -r -s CVA_R2_ACCESS_KEY_ID_SECRET
printf '\n'
printf '%s' "$CVA_R2_ACCESS_KEY_ID_SECRET" | \
  gcloud secrets versions add "$CVA_R2_ID_SECRET_NAME" --data-file=-
unset CVA_R2_ACCESS_KEY_ID_SECRET

printf 'R2 Secret Access Key: '
IFS= read -r -s CVA_R2_SECRET_ACCESS_KEY_SECRET
printf '\n'
printf '%s' "$CVA_R2_SECRET_ACCESS_KEY_SECRET" | \
  gcloud secrets versions add "$CVA_R2_SECRET_NAME" --data-file=-
unset CVA_R2_SECRET_ACCESS_KEY_SECRET

openssl rand -base64 48 | tr -d '\n' | \
  gcloud secrets versions add "$CVA_SESSION_SECRET_NAME" --data-file=-
```

Verificar solo metadata, nunca contenido:

```bash
for secret_name in \
  "$CVA_DB_SECRET_NAME" \
  "$CVA_R2_ID_SECRET_NAME" \
  "$CVA_R2_SECRET_NAME" \
  "$CVA_SESSION_SECRET_NAME"
do
  gcloud secrets versions list "$secret_name" \
    --filter='state=ENABLED' \
    --format='table(name,state,createTime)'
done
```

Si alguna primera versión no es `1`, detenerse: no habilitar runtime hasta que
los cuatro secretos tengan una misma versión numérica y `secret_version` la
refleje.

## 8. Construir imagen, habilitar runtime y desplegar

La cuenta dedicada de build y la publishable key no son secretos:

```bash
export CVA_BUILD_SA_EMAIL="$(terraform -chdir=deploy/terraform output -raw cloud_build_service_account)"
export CVA_BUILD_SA="projects/${CVA_GCP_PROJECT_ID}/serviceAccounts/${CVA_BUILD_SA_EMAIL}"
```

Primer build sin update de Service/Job:

```bash
export CVA_BUILD_ID="$(gcloud builds submit . \
  --async \
  --project="$CVA_GCP_PROJECT_ID" \
  --region="$CVA_GCP_REGION" \
  --service-account="$CVA_BUILD_SA" \
  --config=deploy/cloudbuild.yaml \
  --substitutions="_DEPLOY_RUNTIME=false,_REGION=$CVA_GCP_REGION,_REPOSITORY=$CVA_REPOSITORY_ID,_IMAGE=application,_SERVICE_NAME=$CVA_SERVICE_NAME,_JOB_NAME=$CVA_JOB_NAME,_VITE_SUPABASE_URL=$CVA_SUPABASE_URL,_VITE_SUPABASE_PUBLISHABLE_KEY=$CVA_SUPABASE_PUBLISHABLE_KEY" \
  --format='value(id)')"
gcloud builds log --stream "$CVA_BUILD_ID" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION"
test "$(gcloud builds describe "$CVA_BUILD_ID" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION" \
  --format='value(status)')" = 'SUCCESS'
export CVA_CONTAINER_IMAGE="${CVA_GCP_REGION}-docker.pkg.dev/${CVA_GCP_PROJECT_ID}/${CVA_REPOSITORY_ID}/application:${CVA_BUILD_ID}"
gcloud artifacts docker images describe "$CVA_CONTAINER_IMAGE" \
  --project="$CVA_GCP_PROJECT_ID"
```

Editar `/tmp/cva-stage1.tfvars`: fijar `container_image` al valor inmutable
anterior y `enable_runtime_resources = true`. Revisar y aplicar el segundo plan:

```bash
${EDITOR:-vi} /tmp/cva-stage1.tfvars
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars \
  -out=/tmp/cva-stage1-runtime.tfplan
terraform -chdir=deploy/terraform show -no-color \
  /tmp/cva-stage1-runtime.tfplan
terraform -chdir=deploy/terraform apply \
  /tmp/cva-stage1-runtime.tfplan
export CVA_SERVICE_URI="$(terraform -chdir=deploy/terraform output -raw service_uri)"
```

Ahora aplicar CORS y Auth URL del paso 5/6. Ejecutar un segundo Cloud Build con
`_DEPLOY_RUNTIME=true`; esto prueba realmente las fases de update y health del
artefacto de CD:

```bash
export CVA_DEPLOY_BUILD_ID="$(gcloud builds submit . \
  --async \
  --project="$CVA_GCP_PROJECT_ID" \
  --region="$CVA_GCP_REGION" \
  --service-account="$CVA_BUILD_SA" \
  --config=deploy/cloudbuild.yaml \
  --substitutions="_DEPLOY_RUNTIME=true,_REGION=$CVA_GCP_REGION,_REPOSITORY=$CVA_REPOSITORY_ID,_IMAGE=application,_SERVICE_NAME=$CVA_SERVICE_NAME,_JOB_NAME=$CVA_JOB_NAME,_VITE_SUPABASE_URL=$CVA_SUPABASE_URL,_VITE_SUPABASE_PUBLISHABLE_KEY=$CVA_SUPABASE_PUBLISHABLE_KEY" \
  --format='value(id)')"
gcloud builds log --stream "$CVA_DEPLOY_BUILD_ID" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION"
test "$(gcloud builds describe "$CVA_DEPLOY_BUILD_ID" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION" \
  --format='value(status)')" = 'SUCCESS'
```

## 9. GitHub Actions y trigger de Cloud Build

Una persona debe ejecutar/autorizar estas dos integraciones; la auditoría local
solo validó sus archivos:

1. comprobar que `.github/workflows/ci.yml` pasa en el commit desplegado;
2. conectar el repositorio privado a Cloud Build y crear un trigger de push a
   `main` que use `deploy/cloudbuild.yaml`, la cuenta
   `$CVA_BUILD_SA`, `_DEPLOY_RUNTIME=true` y las mismas substitutions públicas
   del build anterior.

Verificación exacta de GitHub Actions con `gh` autenticado fuera del chat:

```bash
export CVA_GIT_BRANCH='main'
export CVA_GH_RUN_ID="$(gh run list --workflow ci.yml \
  --branch "$CVA_GIT_BRANCH" --limit 1 \
  --json databaseId --jq '.[0].databaseId')"
gh run watch "$CVA_GH_RUN_ID" --exit-status
```

Verificación del trigger (sustituir el nombre creado por la persona):

```bash
export CVA_BUILD_TRIGGER='replace-with-trigger-name'
gcloud builds triggers describe "$CVA_BUILD_TRIGGER" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION"
gcloud builds triggers run "$CVA_BUILD_TRIGGER" \
  --branch="$CVA_GIT_BRANCH" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION"
gcloud builds list --project="$CVA_GCP_PROJECT_ID" \
  --region="$CVA_GCP_REGION" --limit=3
```

El último build del trigger debe ser `SUCCESS` y su imagen debe quedar aplicada
tanto al Service como al Job.

## 10. Comandos de verificación cloud

### 10.1 Runtime, privacidad y modo mock

```bash
curl --fail --show-error "$CVA_SERVICE_URI/api/health"
test "$(curl -sS -o /tmp/cva-private-route.json -w '%{http_code}' \
  "$CVA_SERVICE_URI/api/v1/session")" = '401'
gcloud run services describe "$CVA_SERVICE_NAME" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION"
gcloud run jobs describe "$CVA_JOB_NAME" \
  --project="$CVA_GCP_PROJECT_ID" --region="$CVA_GCP_REGION"
```

Health debe responder `status=ok`, `stage=1`, `model_mode=mock`; la ruta privada
sin cookie debe ser 401. Las descripciones deben mostrar identidades distintas,
referencias versionadas a Secret Manager y la misma imagen inmutable.

### 10.2 E2E cloud obligatorio de E1-11

Usar solo archivos sintéticos. Una persona debe observar y registrar hora/IDs:

1. seguir el magic link del usuario previamente invitado;
2. crear una actividad de tres preguntas, cargar consigna y rúbrica, ejecutar
   P01-P05 y aprobar el blueprint;
3. crear la única submission, cargar PDF digital/TXT/MD y arrancar el pipeline;
4. anotar `job_id` y cerrar **todo el navegador inmediatamente**, sin esperar el
   resultado;
5. comprobar en terminal que una ejecución real del Job termina sin intervención:

   ```bash
   gcloud run jobs executions list \
     --job="$CVA_JOB_NAME" \
     --project="$CVA_GCP_PROJECT_ID" \
     --region="$CVA_GCP_REGION" --limit=5
   ```

6. abrir una sesión nueva, entrar al deep link y confirmar estado terminal,
   tres preguntas evidence-first y todos sus campos;
7. abrir cada fuente firmada, aprobar el Assessment y generar Assessment PDF,
   Guide PDF y JSON; confirmar que exportar no agrega model calls;
8. en DevTools/Network comprobar `OPTIONS`/`PUT`/`GET` R2 sin error CORS, origen
   exacto y ausencia de credenciales en requests/logs;
9. conservar una URL firmada de un fixture y confirmar que deja de funcionar
   después de `CVA_SIGNED_URL_TTL_SECONDS`.

Verificación PostgreSQL posterior (password por prompt como en el paso 5):

```bash
psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 -c \
  "select id, kind, stage, status, progress, attempt, finished_at from public.jobs order by created_at desc limit 4;"
psql "host=$CVA_SUPABASE_DB_HOST port=5432 dbname=postgres user=$CVA_SUPABASE_DB_USER sslmode=require" \
  -v ON_ERROR_STOP=1 -c \
  "select stage, data->>'result' as result, data->'route'->>'provider' as provider, data->>'estimated_cost_usd' as estimated_cost_usd from public.model_calls order by id;"
```

Todos los jobs deben estar en estado de dominio/técnico esperado, y el ledger
debe reflejar exclusivamente el proveedor mock/configurado como `other`, costo
cero y resultados estructurados; nunca contenido estudiantil.

Con AWS CLI, introducir R2 keys solo como variables temporales de una terminal
segura y verificar los dos prefijos realmente creados:

```bash
printf 'R2 Access Key ID para verificación: '
IFS= read -r -s AWS_ACCESS_KEY_ID
printf '\n'
export AWS_ACCESS_KEY_ID
printf 'R2 Secret Access Key para verificación: '
IFS= read -r -s AWS_SECRET_ACCESS_KEY
printf '\n'
export AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION='auto'

aws --endpoint-url "$CVA_R2_ENDPOINT_URL" s3 ls \
  "s3://$CVA_R2_BUCKET/raw/" --recursive
aws --endpoint-url "$CVA_R2_ENDPOINT_URL" s3 ls \
  "s3://$CVA_R2_BUCKET/exports/" --recursive

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
```

Finalmente revisar errores sin imprimir payloads:

```bash
gcloud logging read \
  'severity>=ERROR AND (resource.type="cloud_run_revision" OR resource.type="cloud_run_job")' \
  --project="$CVA_GCP_PROJECT_ID" --freshness=2h --limit=100
```

## 11. Evidencia y criterio de cierre

Guardar fuera del repositorio de código, con timestamps y valores sensibles
redactados:

- URL/commit/build IDs e imagen por digest;
- outputs de `terraform plan/apply`, GitHub Actions y Cloud Build;
- health, 401 de ruta privada, Service/Job/IAM y ejecución del Job;
- resultado de migración, RLS/grants/triggers y filas terminales;
- CORS/lifecycle/privacidad de R2 y listado de prefijos;
- capturas del E2E antes de cerrar y después de reabrir el navegador;
- confirmación explícita de `CVA_MODEL_MODE=mock` y cero secretos en logs.

Estado antes de esta checklist:

- **completas:** E0-01 a E0-08; E1-02, E1-04, E1-05, E1-07, E1-09 y E1-10
  en su boundary local;
- **parciales exclusivamente por cloud:** E1-01, E1-03, E1-06 y E1-08;
- **parcial y no cerrada:** E1-11.

Solo si toda la evidencia externa anterior pasa pueden cerrarse las partes
cloud y E1-11. Un fallo de Auth, RLS, R2, IAM, Job, CI/CD o reapertura mantiene
Etapa 1 parcial. Incluso con todo verde, este procedimiento **no** declara
`READY_FOR_STAGE_2`; esa decisión requiere un gate humano posterior y separado.

Referencias operativas vigentes consultadas: documentación oficial de
[Cloud Build con service accounts dedicadas](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts),
[Cloud Run Jobs](https://docs.cloud.google.com/run/docs/execute/jobs),
[conexiones PostgreSQL de Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres),
[redirect URLs de Supabase Auth](https://supabase.com/docs/guides/auth/redirect-urls),
[JWT Signing Keys de Supabase](https://supabase.com/docs/guides/auth/signing-keys)
y [Wrangler para R2](https://developers.cloudflare.com/r2/reference/wrangler-commands/).
