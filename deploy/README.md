# Despliegue de Etapa 1

Este directorio deja reproducible el despliegue, pero no crea cuentas ni
introduce secretos. El recorrido se mantiene en `CVA_MODEL_MODE=mock` y P10
queda deshabilitado.

## Boundary 1: recursos sin secretos ni imagen

1. Crear o seleccionar un proyecto GCP con facturación y una cuenta Supabase.
2. Crear un bucket R2 privado, sin `r2.dev` ni dominio público.
3. Copiar `deploy/terraform/terraform.tfvars.example` fuera del repositorio,
   reemplazar solo valores no secretos y mantener
   `enable_runtime_resources = false`.
4. Ejecutar desde `deploy/terraform`:

   ```bash
   terraform init
   terraform plan -out stage1-bootstrap.tfplan
   terraform apply stage1-bootstrap.tfplan
   ```

Esto habilita APIs y crea Artifact Registry, identidades y contenedores de
Secret Manager. No crea todavía Cloud Run Service/Job.

## Boundary 2: configuración externa manual

1. Aplicar `deploy/supabase/migrations/202607310001_stage1.sql` al proyecto
   Supabase y verificar que RLS está activo y que `anon`/`authenticated` no
   tienen privilegios sobre las tablas de aplicación.
2. Añadir la versión numérica `1` de estos secretos desde una terminal segura,
   nunca desde el chat ni el repositorio:
   `database_url`, `session_secret`, `r2_access_key_id` y
   `r2_secret_access_key`. Usar los nombres exactos de
   `terraform output -json runtime_secret_names`.
3. Sustituir el origen placeholder en `deploy/r2/cors.example.json`; conservar
   un origen HTTPS exacto y sin wildcard. Aplicar y comprobar las reglas:

   ```bash
   npx wrangler r2 bucket cors set BUCKET --file deploy/r2/cors.example.json
   npx wrangler r2 bucket cors list BUCKET
   npx wrangler r2 bucket lifecycle set BUCKET --file deploy/r2/lifecycle.example.json
   npx wrangler r2 bucket lifecycle list BUCKET
   ```

   Ratificar antes los plazos del lifecycle: raw 30 días desde creación y
   exports 120 días son defaults experimentales, no una regla legal universal.

## Boundary 3: imagen y runtime

Ejecutar Cloud Build con URL/clave publicable de Supabase como substitutions
de build. La service-role key nunca se compila en Vite:

```bash
gcloud builds submit --config deploy/cloudbuild.yaml \
  --substitutions=_DEPLOY_RUNTIME=false,_VITE_SUPABASE_URL=SUPABASE_URL,_VITE_SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY
```

Para el primer despliegue, construir y publicar la imagen antes de que existan
Service/Job, copiar su referencia inmutable a `container_image`, cambiar
`enable_runtime_resources = true`, ejecutar `terraform plan`/`apply` y luego
volver a ejecutar Cloud Build con `_DEPLOY_RUNTIME=true`. Conectar el repositorio GitHub a un trigger de
Cloud Build que use `deploy/cloudbuild.yaml` y la service account indicada por
`terraform output cloud_build_service_account`.

Verificación mínima posterior:

```bash
curl --fail "$(terraform output -raw service_uri)/api/health"
gcloud run jobs describe "$(terraform output -raw job_name)" --region REGION
```

La prueba E2E cloud debe crear un job mock, cerrar el navegador, ejecutar el
Cloud Run Job y confirmar desde una sesión nueva que el estado durable llegó a
terminal. No habilitar proveedor real ni comenzar Etapa 2 durante esta prueba.
