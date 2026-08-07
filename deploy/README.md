# Despliegue de Etapa 1

Este directorio prepara la verificación externa, pero no crea cuentas, no
introduce secretos y no despliega durante la auditoría local. El runtime debe
conservar `CVA_MODEL_MODE=mock` y `CVA_P10_ENABLED=false`. La checklist humana
completa está en `docs/EXTERNAL_SETUP.md`.

## Límites operativos fijados

- Terraform es el único propietario de la imagen de Cloud Run Service y Job.
- Cloud Build construye, prueba y publica; nunca ejecuta `gcloud run ... update`.
- `container_image` debe ser una referencia inmutable terminada en
  `@sha256:<digest>` y se aplica a ambos recursos.
- El Job usa una tarea, paralelismo uno y `max_retries = 0`. Cada ejecución del
  worker reclama como máximo una fila durable. Un retry funcional general es
  Etapa 2 y no está implementado.
- Cloud exige `postgresql+psycopg://`; SQLite, drivers implícitos y adapters
  locales se rechazan antes de iniciar.
- `/api/health` es liveness sin dependencias. `/api/readiness` comprueba la DB y
  la superficie final esperada de la migración; el startup probe usa readiness
  y el liveness probe conserva health.
- Upload y download usan TTL separados mediante
  `CVA_UPLOAD_URL_TTL_SECONDS` y `CVA_DOWNLOAD_URL_TTL_SECONDS`.

## Boundary 1: bootstrap sin runtime

Copiar el ejemplo a un archivo fuera del repositorio, completar solo valores
públicos y mantener `enable_runtime_resources = false` y
`container_image = ""`:

```bash
cp deploy/terraform/terraform.tfvars.example /tmp/cva-stage1.tfvars
chmod 600 /tmp/cva-stage1.tfvars
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars \
  -out=/tmp/cva-stage1-bootstrap.tfplan
terraform -chdir=deploy/terraform apply \
  /tmp/cva-stage1-bootstrap.tfplan
```

Esto habilita APIs y crea Artifact Registry, identidades y contenedores vacíos
de Secret Manager. No crea todavía Service ni Job.

## Boundary 2: configuración externa manual

Una persona autorizada debe:

1. aplicar `deploy/supabase/migrations/202607310001_stage1.sql` a una base vacía
   y comprobar tablas/columnas, RLS, grants y triggers;
2. guardar fuera de Git las versiones de `database_url`, `session_secret`,
   `r2_access_key_id` y `r2_secret_access_key` en Secret Manager;
3. configurar Auth Supabase y la membresía invitada;
4. crear R2 privado, sin `r2.dev` ni dominio público, y aplicar CORS/lifecycle
   revisados;
5. confirmar que la URL de aplicación usa el driver explícito
   `postgresql+psycopg://` y `sslmode=require`.

No guardar una URL autenticada, tfvars reales, tokens, magic links o secretos en
Git, substitutions, build args o logs. La URL y publishable key de Supabase son
públicas y son los únicos valores Supabase compilados por Vite.

## Boundary 3: imagen inmutable y Terraform

El flujo obligatorio evita dos propietarios de la imagen:

1. construir la imagen;
2. publicarla en Artifact Registry;
3. obtener el digest;
4. construir la referencia inmutable `...@sha256:...`;
5. copiarla a `/tmp/cva-stage1.tfvars` y activar
   `enable_runtime_resources = true`;
6. revisar `terraform plan`;
7. aplicar Terraform;
8. comprobar Service y Job, incluida la misma imagen en ambos;
9. ejecutar otro `terraform plan` y confirmar ausencia de drift.

Cloud Build deja la referencia en `/workspace/container-image.txt` y también la
imprime como dato no secreto. Un ejemplo de build es:

```bash
gcloud builds submit --config deploy/cloudbuild.yaml \
  --substitutions=_VITE_SUPABASE_URL=SUPABASE_URL,_VITE_SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY
```

Después de copiar la referencia por digest al archivo externo:

```bash
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars \
  -out=/tmp/cva-stage1-runtime.tfplan
terraform -chdir=deploy/terraform apply /tmp/cva-stage1-runtime.tfplan
terraform -chdir=deploy/terraform plan \
  -var-file=/tmp/cva-stage1.tfvars -detailed-exitcode
```

El último comando debe terminar 0. Exit 2 indica cambios y debe investigarse;
no aplicar a ciegas.

## Verificación mínima posterior

```bash
CVA_SERVICE_URI="$(terraform -chdir=deploy/terraform output -raw service_uri)"
curl --fail "$CVA_SERVICE_URI/api/health"
curl --fail "$CVA_SERVICE_URI/api/readiness"
gcloud run jobs describe \
  "$(terraform -chdir=deploy/terraform output -raw job_name)" --region REGION
```

La prueba externa E1-11 debe crear un job con fixtures sintéticos, cerrar el
navegador, observar que el Cloud Run Job termina y confirmar desde una sesión
nueva que PostgreSQL conserva el estado terminal. No habilitar proveedor real,
no iniciar Etapa 2 y no hacer merge automático.
