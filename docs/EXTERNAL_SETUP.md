# Operación externa verificada de Etapa 1

Estado al 2026-08-07: el stack externo autorizado fue configurado y verificado
con datos exclusivamente sintéticos. Este documento es el runbook operativo y
el snapshot del candidato; ya no representa una tarea externa pendiente.

La evidencia exacta del último commit se genera fuera del repositorio porque
FINAL_STAGE1_SHA, su build y su digest solo existen después del commit que
contiene este documento.

## Targets autorizados

| Plataforma | Target |
|---|---|
| GitHub | WilJms/PruebasPersonalizadas, PR #1 |
| GCP | cva-experimento-wiljms, us-east1 |
| Cloud Run | Service cva-web y Job cva-worker |
| Supabase | spkgkruotrpuctfqdfag |
| Cloudflare | account 7cc729fcb2ea8db8ddfce8da1a8ecb75 |
| R2 | cva-experimento-raw-wiljms |

No operar sobre otro repositorio, proyecto, región, cuenta, bucket, base o
tenant. El runtime debe mantener CVA_MODEL_MODE=mock y CVA_P10_ENABLED=false.

## Estado externo observado en el candidato

### GitHub y Cloud Build

- GitHub Actions push 31199864090 y pull_request 31199869015 del candidato
  6374e60 terminaron SUCCESS sobre el mismo head.
- La conexión cva-github está COMPLETE y el repository resource apunta
  exclusivamente a WilJms/PruebasPersonalizadas.
- El trigger regional cva-github-push usa deploy/cloudbuild.yaml y la identidad
  cva-cloudbuild.
- Cloud Build no ejecuta despliegues de Cloud Run.
- La cuenta de build tiene Artifact Registry writer, Logging writer,
  Service Usage consumer y los permisos Storage mínimos de staging; no tiene
  Run Admin ni actAs sobre web/worker.
- El build candidato b274ccc5-ef4d-42b1-b4fe-893d77d3b898 construyó source y
  resolved source 6374e60ce74ebb2a1ee0ec80531eab218d1b9548, grabó la misma
  OCI revision y publicó el digest
  sha256:94e6b4e786c95f0c746f48703fdd8a4f3641c9627a9fe6766e6ffc25a845967c.

### GCP y Terraform

- cva-web y cva-worker están Ready en generación 9 y usan el mismo digest
  inmutable candidato.
- Service y Job usan identidades distintas.
- El Job conserva task count 1, parallelism 1 y max retries 0.
- El worker no recibe CVA_SESSION_SECRET ni su binding de Secret Manager.
- Health y readiness responden 200; la ruta privada de sesión responde 401 sin
  autenticación.
- Terraform aplicó dos actualizaciones in-place de imagen. Una rotación
  correctiva posterior aplicó solo dos actualizaciones in-place de referencias
  de Secret Manager; no cambió imagen, IAM ni topología. El estado final tuvo
  dos planes vivos consecutivos exit 0.
- El bloque scaling superior fija manual instance count 0 y min instance count
  0; no se usa ignore_changes para ocultar drift.

### Supabase

- El proyecto está ACTIVE_HEALTHY y usa PostgreSQL 17.
- La migración seleccionada expone 24 tablas con RLS y dos triggers
  append-only; no concede tablas al browser.
- Existe el workspace tnt_experimental.
- El usuario sintético teacher@example.test tiene UUID Supabase persistido y
  membresía TEACHER can_approve=true en ese workspace.
- El magic link se generó y consumió mediante el flujo oficial; el enlace y la
  clave service-role transitoria no se guardaron, imprimieron ni incluyeron en
  evidencia.
- FastAPI valida JWKS y emite su propia cookie segura; el frontend compila solo
  la URL y publishable key públicas.
- La contraseña PostgreSQL fue rotada durante esta verificación después de que
  un diagnóstico local inválido mostrara la credencial anterior. La versión 1
  quedó denegada, la versión 2 conecta y health/readiness permanecen 200. El
  valor no se copia en este repositorio ni en la evidencia.

### Cloudflare R2

- El bucket cva-experimento-raw-wiljms existe en la cuenta autorizada.
- r2.dev está deshabilitado y no hay custom domains.
- CORS contiene un único origen:
  https://cva-web-tsdkybr67a-ue.a.run.app.
- Métodos: GET, PUT y HEAD; header permitido Content-Type; header expuesto
  ETag; max age 3600.
- Lifecycle: abort multipart a 1 día, raw/ a 30 días y exports/ a 120 días.
- No se enumeró ni descargó contenido ajeno; las pruebas de datos usaron
  exclusivamente objetos sintéticos del recorrido.

## Manejo de secretos

Nunca introducir en chat, Git, substitutions, build args, evidencia o logs:

- password o URL autenticada de PostgreSQL;
- R2 Access Key ID, Secret Access Key o token Cloudflare;
- CVA_SESSION_SECRET;
- tokens GCP/GitHub/Supabase;
- secret/service-role keys, magic links o URLs firmadas;
- credenciales de proveedor IA.

Secret Manager contiene cuatro secret containers. cva-web accede a database,
R2 key pair y session secret. cva-worker accede únicamente a database y R2 key
pair. El runtime candidato fija sus referencias en la versión 2. Las versiones
se inspeccionan por metadata, nunca imprimiendo valores.

## Flujo reproducible de build y deploy

1. Confirmar repo, rama, HEAD limpio y PR draft.
2. Exigir CI verde para el HEAD exacto.
3. Confirmar que el trigger produjo un build cuyo source revision y label OCI
   son ese HEAD.
4. Exigir requestedVerifyOption VERIFIED, provenance SLSA, scan finalizado sin
   vulnerabilidades bloqueantes y SBOM ligado al digest.
5. Copiar la referencia image@sha256 al tfvars no versionado.
6. Ejecutar fmt, init, validate, pruebas y plan guardado.
7. Revisar el JSON del plan; bloquear ante destroy, replacement, IAM, secreto
   inline, cambio de target, retry/task/parallelism o imagen inesperada.
8. Aplicar exclusivamente el plan guardado.
9. Confirmar el mismo digest en Service y Job.
10. Ejecutar dos planes vivos consecutivos con detailed exit code 0.

Terraform es siempre el único escritor del deployment. Un build exitoso no
autoriza por sí solo actualizar Cloud Run.

## Verificación cloud obligatoria

Para cada candidato final:

- health 200;
- readiness 200;
- ruta privada anónima 401;
- Service y Job Ready con el mismo digest;
- Job en 1/1/0;
- mock habilitado y P10 deshabilitado;
- Auth y membresía tenant-scoped;
- upload R2, sellado, lectura y expiración de capacidad;
- una actividad y una submission sintéticas;
- Cloud Run Job durable después de cerrar navegador;
- recuperación desde la raíz sin ID ni URL recordada;
- blueprint y Assessment con dificultad derivada;
- CHOICE con tres alternativas, una best y datos de evaluador separados;
- receipt evidence-first durable por fragmento;
- EvaluationGuide trazable;
- Assessment PDF, Guide PDF y JSON;
- delta de model calls igual a cero durante export;
- fallo controlado durable con una ejecución fallida y sin retry automático;
- búsqueda de secretos/capabilities/payload sintético en logs igual a cero.

El candidato 6374e60 ejecutó este recorrido desde cero con la actividad
`act_1497be02cbfc6cf35743` y una única submission
`sub_cfb5cae00678b8ab200f`. La revisión se recuperó dos veces desde la raíz,
los tres exports quedaron READY y el conteo de model calls permaneció 36 antes
y 36 después (4 y 4 para su job). El fallo deliberado
`job_control_6374e60` quedó FAILED, attempt 1, diagnóstico JOB_KIND_INVALID;
la ejecución cva-worker-w9wtl terminó con exit 1, una task y cero retries.

## Cache y rollouts de la SPA

Las rutas documento, incluida la raíz y los deep links, responden
Cache-Control: no-store, max-age=0. Los assets con hash responden public,
max-age=31536000, immutable.

Los navegadores que almacenaron una respuesta anterior a esta política se
recuperan mediante X-CVA-Shell-Epoch. El shell actual envía stage1-v1. Una
llamada GET de sesión sin ese epoch recibe Clear-Site-Data: "cache". Solo se
purga la caché HTTP; cookies, sesión y storage de autenticación no se borran.
La siguiente apertura carga el shell actual y entra en /activities.

## Evidencia final

El paquete externo debe incluir un manifest con timestamp UTC, clasificación y
SHA-256 de cada archivo. Debe registrar:

- FINAL_STAGE1_SHA, base SHA y CI merge SHA si aplica;
- PR y runs CI;
- build ID, source, OCI revision, digest, provenance, scan y SBOM;
- plan/applied actions y dos planes post-apply;
- Service, Job e IAM;
- health, readiness y privado 401;
- Supabase/Auth/PostgreSQL;
- R2/CORS/lifecycle/privacidad/TTL;
- navegador, close/reopen, exports y model-call delta;
- fallo controlado y log/secret scan;
- registro sanitizado de la rotación correctiva, demostrando únicamente que la
  credencial anterior falla y la versión nueva funciona;
- informe del auditor independiente.

No incluir tokens, URLs firmadas, secretos, database URLs ni sobres de
procedencia completos. Cualquier intento que haya expuesto una capacidad
efímera en output de herramienta debe marcarse inválido, excluirse del paquete
y documentarse solo por su expiración, nunca copiando el valor.

El paquete histórico asociado a f982ef89 fue rechazado por la auditoría
independiente y no puede reutilizarse como evidencia final.

## Operación posterior

El PR permanece draft. Este runbook no autoriza merge, tag ni Etapa 2. Si una
sesión externa expira, se repite el login oficial interactivo y se verifica el
target antes de continuar; nunca se solicita un secreto por chat.
