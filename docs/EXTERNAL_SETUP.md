# Operación externa — Etapa 2

Estado al 2026-08-07 America/Santiago, con evidencia hasta 2026-08-08 UTC: el
candidato runtime E2
`44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` está verificado en CI y en los
targets cloud autorizados con datos exclusivamente sintéticos. Este documento
registra el target, lo observado y la secuencia operativa; [deploy/README.md](../deploy/README.md)
conserva los comandos detallados y gates fail-closed.

## Targets autorizados

| Plataforma | Target |
|---|---|
| GitHub | WilJms/PruebasPersonalizadas; rama `codex/stage2-experimental-mvp` |
| GCP | cva-experimento-wiljms, us-east1 |
| Cloud Run | Service cva-web y Job cva-worker |
| Supabase | spkgkruotrpuctfqdfag |
| Cloudflare | account 7cc729fcb2ea8db8ddfce8da1a8ecb75 |
| R2 | cva-experimento-raw-wiljms |

No operar sobre otro repositorio, proyecto, región, cuenta, bucket, base o
tenant. El runtime debe mantener CVA_MODEL_MODE=mock y CVA_P10_ENABLED=false.

## Resultado de los boundaries E2

| Boundary | Clasificación | Resultado observado |
|---|---|---|
| SHA/PR/CI | CI_REAL | PR draft `#2`; push `31232751301` y PR `31232752740`, 7/7 SUCCESS cada uno |
| PostgreSQL | CLOUD_REAL | Backup verificado; migración 003 aplicada una vez; readiness posterior PASS |
| Cloud Build | CLOUD_REAL | `aad1bf58-966e-44f9-ad10-5d7b81144854` SUCCESS/VERIFIED; SLSA 3 v1 y scan `FINISHED_SUCCESS`; SBOM no reclamado |
| Terraform | CLOUD_REAL | Apply 0 add, 2 change, 0 destroy; sin cambio de target/model/P10 |
| Runtime | CLOUD_REAL | `cva-web` y `cva-worker` Ready en `us-east1`, mismo digest; mock/P10 false/libmagic true; health/readiness PASS |
| Producto cloud | CLOUD_REAL + MOCK_MODEL | Recorrido sintético 38/38; browser 1440/390 close/reopen; logs y capability persistence en cero |
| Convergencia | CLOUD_REAL | Dos planes vivos consecutivos sin drift |

Antes de cada write se revalidó identidad y target de GitHub, gcloud/ADC,
Supabase y Cloudflare sin registrar secretos. La base E1 ya contenía 001 y 002;
por tanto el upgrade live aplicó únicamente 003. La recovery E2 no es un
rollback rutinario: conserva el requisito de quiesce, backup y ausencia
demostrada de hechos E2.

Cloud Build construye y publica, pero no despliega. Terraform sigue siendo el
único writer de Service/Job y solo acepta la imagen
`us-east1-docker.pkg.dev/cva-experimento-wiljms/<repository>/application@sha256:…`
del repositorio configurado en el mismo plan.

La ejecución cloud usa exclusivamente fixtures sintéticos, modelo mock y P10
apagado. No se solicitan credenciales de proveedor IA. Los valores PostgreSQL,
R2, sesión y service-role permanecen en mecanismos oficiales/Secret Manager y
nunca se copian a comandos, substitutions, logs, evidencia o Git.

## Snapshot externo verificado de E2

- Candidato runtime: `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5`.
- Pull request: draft `#2`.
- CI: runs push `31232751301` y pull request `31232752740`, ambos SUCCESS con
  siete de siete jobs.
- Cloud Build: `aad1bf58-966e-44f9-ad10-5d7b81144854`, SUCCESS y VERIFIED.
- Digest aplicado a Service y Job:
  `sha256:0c6be928c698cd052763c9daf683ae19d4f5b8a99cba06b54fc32e244d70044e`.
- Supply chain observada: SLSA 3 v1 con `GoogleHostedWorker` y continuous scan
  `FINISHED_SUCCESS`. No se observó ni se reclama SBOM E2.
- Migración 003: SHA-256
  `6bb9de336b176e89abced2dc56032b83c05e4613c9f2462cde3835573a22df61`,
  aplicada una vez. Backup previo fuera de Git: 347166 bytes, SHA-256
  `30b39631dda914245196f3cad87cb740b7b2c7294084df02f93fd83bf13cdd2e`.
- Terraform: 0 add, 2 change, 0 destroy; dos planes vivos posteriores sin
  cambios.
- Runtime: Service/Job Ready con el mismo digest, health/readiness PASS,
  `CVA_MODEL_MODE=mock`, `CVA_P10_ENABLED=false` y
  `CVA_REQUIRE_LIBMAGIC=true`.
- Producto: manifest sintético 38/38 PASS; pasos 12 y 33–36 etiquetados
  `CONTROLLED_ADMIN_SEED`; navegador real desktop 1440 y móvil 390, cierre y
  reapertura, sin errores de consola ni overflow global. Capturas fuera de Git.
- Cierre: cero jobs activos, cero capabilities persistidas, cero errores/leaks
  en el corte final. Los usuarios Auth efímeros quedaron en cero; la evidencia
  sintética PostgreSQL/R2 se retuvo para auditoría.

Estos resultados no habilitan datos reales, proveedor real, P10 ni Etapa 3.
ClamAV continúa ausente y su gate para datos reales permanece abierto.

## Estado externo histórico observado en candidatos E1

### GitHub y Cloud Build

- GitHub Actions push 31209547327 y pull_request 31209552197 del correctivo
  4bab5b4 terminaron SUCCESS, siete jobs cada uno. El checkout PR fue el merge
  sintético 1e695278... con padres base dadaaa7 y head 4bab5b4.
- La conexión cva-github está COMPLETE y el repository resource apunta
  exclusivamente a WilJms/PruebasPersonalizadas.
- El trigger regional cva-github-push usa deploy/cloudbuild.yaml y la identidad
  cva-cloudbuild.
- Cloud Build no ejecuta despliegues de Cloud Run.
- La cuenta de build tiene Artifact Registry writer, Logging writer,
  Service Usage consumer y los permisos Storage mínimos de staging; no tiene
  Run Admin ni actAs sobre web/worker.
- El build correctivo 745eb275-eea4-4493-8b64-293570472265 construyó source
  4bab5b400199b94f2fd003c7f959b4d341363b26, grabó esa OCI revision y
  publicó el digest
  sha256:7d73b1cb7a438f6f8adb8de10f31752efdbca860e1aa08c9314097d4e5daed7a.

### GCP y Terraform

- cva-web y cva-worker están Ready en generación 11 y usan el mismo digest
  inmutable correctivo.
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
- Las dos migraciones ordenadas exponen 24 tablas con RLS, dos triggers
  append-only y el constraint validado
  `ck_idempotency_keys_safe_response`; no conceden tablas al browser.
- La migración correctiva eliminó una respuesta histórica con capability y
  cinco reservas JSON null. La verificación read-only posterior observó 75
  filas, cero SQL/JSON null, cero claves `_url` y cero marcadores X-Amz.
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
4. Exigir requestedVerifyOption VERIFIED, provenance SLSA y scan finalizado;
   registrar SBOM solo si fue efectivamente observado y ligado al digest.
5. Copiar la referencia image@sha256 al tfvars no versionado.
6. Ejecutar fmt, init, validate, pruebas y plan guardado.
7. Revisar el JSON del plan; bloquear ante destroy, replacement, IAM, secreto
   inline, cambio de target, retry/task/parallelism o imagen inesperada.
8. Aplicar exclusivamente el plan guardado.
9. Confirmar el mismo digest en Service y Job.
10. Ejecutar dos planes vivos consecutivos con detailed exit code 0.

Terraform es siempre el único escritor del deployment. Un build exitoso no
autoriza por sí solo actualizar Cloud Run.

## Verificación cloud obligatoria E2

Para cada `STAGE2_RUNTIME_SHA`:

- health 200;
- readiness 200;
- ruta privada anónima 401;
- Service y Job Ready con el mismo digest;
- Job en 1/1/0;
- mock habilitado y P10 deshabilitado;
- Auth y membresía tenant-scoped;
- upload R2, sellado, lectura y expiración de capacidad;
- dos workspaces sintéticos aislados;
- una actividad con consigna/rúbrica, blueprint y aprobación;
- al menos dos submissions sintéticas, con `subject_ref` distintos y formatos
  DOCX/TXT;
- Cloud Run Job durable después de cerrar navegador;
- recuperación desde la raíz sin ID ni URL recordada;
- submission suficiente y otra insuficiente fail-closed;
- ACCEPT, EDIT, REJECT, REGENERATE, reserva, lineage y exactly N;
- CHOICE con tres alternativas, una best y datos de evaluador separados;
- receipt evidence-first durable por fragmento;
- EvaluationGuide, coverage, feedback, métricas, aprobación individual/bulk y
  exports trazables;
- delta de model calls igual a cero durante export;
- retry/cancel/resume y negativos cross-submission/cross-tenant;
- cualquier seed administrativo de insuficiencia o control jobs etiquetado
  `CONTROLLED_ADMIN_SEED`, sin reclamar un fallo natural de proveedor;
- browser real 1440/390 px, cierre/reapertura, consola limpia y sin overflow;
- búsqueda de secretos/capabilities/payload sintético en logs igual a cero;
- usuarios Auth efímeros, jobs activos y capabilities persistidas igual a cero
  al cierre.

El cierre E2 satisfizo esta lista en el manifest 38/38. La lineage cloud de
retry/resume se conserva, pero su semántica de éxito se acredita en local/CI.

### Ejecuciones históricas E1

El candidato funcional 6374e60 ejecutó este recorrido desde cero con la actividad
`act_1497be02cbfc6cf35743` y una única submission
`sub_cfb5cae00678b8ab200f`. La revisión se recuperó dos veces desde la raíz,
los tres exports quedaron READY y el conteo de model calls permaneció 36 antes
y 36 después (4 y 4 para su job). El fallo deliberado
`job_control_6374e60` quedó FAILED, attempt 1, diagnóstico JOB_KIND_INVALID;
la ejecución cva-worker-w9wtl terminó con exit 1, una task y cero retries.

Sobre el digest correctivo 4bab5b4 se cerraron todas las pestañas de la
aplicación, se reabrió la raíz y se recuperaron `/activities`, el Assessment
aprobado y la Guide sin usar ID, history ni URL recordada. Health/readiness y
privado fueron 200/200/401; la base conservó el constraint y cero capabilities.

## Cache y rollouts de la SPA

Las rutas documento, incluida la raíz y los deep links, responden
Cache-Control: no-store, max-age=0. Los assets con hash responden public,
max-age=31536000, immutable.

Los navegadores que almacenaron una respuesta anterior a esta política se
recuperan mediante X-CVA-Shell-Epoch. El shell actual envía stage1-v1. Una
llamada GET de sesión sin ese epoch recibe Clear-Site-Data: "cache". Solo se
purga la caché HTTP; cookies, sesión y storage de autenticación no se borran.
La siguiente apertura carga el shell actual y entra en /activities.

## Evidencia final E2

El paquete externo debe incluir un manifest con timestamp UTC, clasificación y
SHA-256 de cada archivo. Debe registrar:

- `STAGE2_RUNTIME_SHA`, `STAGE2_BASELINE_SHA` y la separación respecto del
  commit documental posterior;
- PR y runs CI;
- migración 003, checksum, aplicación única y backup pre-003 con checksum;
- build ID, source, OCI revision, digest, provenance y scan; SBOM se registra
  solo si fue observado y ligado al mismo digest;
- plan/applied actions y dos planes post-apply;
- Service, Job e IAM;
- health, readiness y privado 401;
- Supabase/Auth/PostgreSQL;
- R2/CORS/lifecycle/privacidad/TTL;
- manifest cloud 1–38 y clasificación explícita de
  `CONTROLLED_ADMIN_SEED`;
- navegador 1440/390, close/reopen, exports y model-call delta;
- cleanup Auth/jobs/capabilities, retención sintética DB/R2 y log/secret scan;
- registro sanitizado de la rotación correctiva, demostrando únicamente que la
  credencial anterior falla y la versión nueva funciona;
- informe del auditor independiente.

Para el runtime E2 se observaron provenance y scan, pero SBOM quedó
`NOT_OBSERVED / NO CLAIM`. Las capturas, el state del harness y el backup viven
fuera del repositorio y se identifican por path/metadata/checksum, sin
versionarlos.

No incluir tokens, URLs firmadas, secretos, database URLs ni sobres de
procedencia completos. Cualquier intento que haya expuesto una capacidad
efímera en output de herramienta debe marcarse inválido, excluirse del paquete
y documentarse solo por su expiración, nunca copiando el valor.

### Paquetes históricos E1 rechazados

Los paquetes asociados a f982ef89 y 5b13428 fueron rechazados por la auditoría
independiente y no pueden reutilizarse como evidencia final. El segundo carecía
del inventario/checksum material que su manifest afirmaba, omitía el merge SHA
real del run PR y precedía al saneamiento live de idempotencia.

## Operación posterior

El prompt maestro del 2026-08-07 autoriza implementar y desplegar E2 únicamente
en los targets indicados. No autoriza merge a `main`, tag, Etapa 3, modelos
reales ni datos reales. Si una sesión externa expira, se repite el login
oficial interactivo y se verifica el target antes de continuar; nunca se
solicita un secreto por chat.
