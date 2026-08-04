# Auditoría de infraestructura externa de Etapa 1

Fecha de comprobación viva: `2026-08-04` (`America/Santiago`). No se ejecutó
`terraform apply`, no se cambió IAM, secretos, builds, deployments, datos,
migraciones, CORS, lifecycle ni DNS.

## Dictamen

El stack real existe y responde: Cloud Run Service y Job usan el mismo digest,
health/readiness están verdes, la ruta privada rechaza anónimos, Cloud Run Jobs
ejecutó tres recorridos exitosos y un fallo controlado, Supabase PostgreSQL
conserva estados/ledger/auditoría, y el paquete primario demuestra R2 privado,
expiración y exports. La imagen final se correlacionó directamente con el tar de
fuente usado por Cloud Build y ese tar coincide con el commit declarado.

El gate externo sigue abierto por dos incumplimientos objetivos:

1. Terraform no converge: el plan vivo termina `2` y propone una actualización
   recurrente del Service.
2. No existe trigger GitHub–Cloud Build; el build fue un submit manual de un tar
   GCS con `COMMIT_SHA` proporcionado por el operador.

Además, no hubo acceso independiente al control plane de Cloudflare y el SHA
desplegado es el ancestro funcional, no el HEAD documental actual.

## Correlación de identidad

| Dimensión | Valor final | Verificación |
|---|---|---|
| Commit desplegado | `0167f14cbfe4a1192b26688a8443c5835da60bb4` | Sustitución Cloud Build y label OCI; PR/evidencia externa. |
| HEAD de auditoría | `2c018ef126622f7d0c6b84eeaf563a20bded593e` | Git local/remoto y PR vivo. |
| Delta entre ambos | Solo 4 archivos nuevos bajo `docs/audits/` | `git diff` y diff no-audit exit `0`. |
| Build final | `85514589-a513-46af-ae74-1656a8433aa7` | Cloud Build describe: `SUCCESS`, 2026-08-03 22:20:02Z–22:22:52Z. |
| Source build | `gs://cva-experimento-wiljms_cloudbuild/source/1785795600.133271-5508b770b30746faa67cd2b8a642f9cb.tgz`, generation `1785795602086109` | Metadata GCS: 394.383 bytes, MD5 `34e39f79…31825`; descarga SHA-256 `c990b26a…b49d1`. |
| Coincidencia source/commit | 129/129 archivos del tar existen en `0167f14…` y tienen bytes idénticos | Comparación directa; 0 extras y 0 mismatches. Los inputs que copia Docker están incluidos. |
| Digest | `sha256:4dc9be449d1c7401dd70beaeeb38b6989b128a1892b59343b59717d2ca0a6f0b` | Cloud Build result, Artifact Registry y ambos runtimes. |
| Artifact Registry | `us-east1-docker.pkg.dev/cva-experimento-wiljms/comprehension-verification/application@…` | Describe directo; SLSA build level `unknown`. |
| Proyecto/región | `cva-experimento-wiljms` / `us-east1` | gcloud config y recursos vivos. |
| Service/Job | `cva-web` / `cva-worker` | gcloud describe y Terraform state. |

Esta comparación rescata la procedencia del build concreto pese al submit
manual: la etiqueta de commit por sí sola no era prueba, pero el objeto GCS
exacto sí se pudo descargar y comparar. No convierte el proceso manual en una
cadena reproducible ni sustituye un trigger/attestation.

## GCP y Cloud Run

### Service

| Propiedad | Observado |
|---|---|
| Generación | 3 |
| Ready | `True` desde `2026-08-03T22:25:40Z` |
| Revisión lista | `cva-web-00003-qgs` |
| Service account | `cva-web@cva-experimento-wiljms.iam.gserviceaccount.com` |
| Imagen | Digest final `4dc9be…6f0b` |
| Escala de revisión | min 0, max 3 |
| IAM invoker | `allUsers` (necesario para login/static; app protege API privada) |
| URL | `https://cva-web-tsdkybr67a-ue.a.run.app` |

Comprobación HTTP viva:

- `/api/health`: `200`, `{"status":"ok","stage":"1","model_mode":"mock"}`;
- `/api/readiness`: `200`, `{"status":"ready"}`;
- `/api/v1/session` anónima: `401 SESSION_REQUIRED`;
- headers: CSP, no-store en API, no-referrer, nosniff, DENY frame y
  Permissions-Policy restrictiva.

### Job

| Propiedad | Observado |
|---|---|
| Generación/Ready | 3 / `True` |
| Service account | `cva-worker@cva-experimento-wiljms.iam.gserviceaccount.com` |
| Imagen | Mismo digest final |
| Task/parallelism | 1 / 1 |
| `maxRetries` | 0 |
| Timeout | 3600 s |
| Invoker IAM | Solo la service account web |
| Executions | `n5xjz`, `j26kp`, `xprjq` success; `qbsrb` failed controlado |

La última ejecución está `EXECUTION_FAILED` porque fue la prueba deliberada
`JOB_KIND_INVALID`, no porque el happy path quedara inconcluso. PostgreSQL
confirma 3 jobs `SUCCEEDED` y 1 `FAILED`; el paquete primario muestra attempt 1,
una task y ningún retry.

## Cloud Build, Artifact Registry y GitHub

| Control | Observado | Evaluación |
|---|---|---|
| Build final | SUCCESS; source GCS; imagen publicada por digest | Conforme para el build concreto. |
| Label commit | `org.opencontainers.image.revision=0167f14…` | Corroborado mediante comparación del source tar. |
| Deploy directo | `deploy/cloudbuild.yaml` no contiene `gcloud run`; solo build/smoke/push/resolve digest. | Conforme: Terraform es único owner. |
| Build SA | artifact writer, logging writer, service usage consumer, storage bucket viewer/object user | Conforme al submit; no `run.admin`, no actAs web/worker. |
| Triggers | `gcloud builds triggers list --region us-east1` devolvió lista vacía | No conforme con el enlace GitHub–Cloud Build. |
| Artifact provenance | Digest presente; SLSA level `unknown`; sin build provenance en describe | Limitación supply-chain. |
| PR | #1 abierto, draft, mergeable, 119 archivos, 7 commits, head `2c018ef…` | Directo mediante GitHub app. |
| CI actual | Run `30929318133`, run 14, conclusión success; 5 jobs success | Conforme para PR result. |
| SHA efectivo de CI | Checkout del merge sintético `38300897…` de head sobre base | Normal para `pull_request`, pero no es el digest desplegado. |

Versiones/resultados CI comprobados en logs y metadatos:

- Python 3.12.13, pytest 8.4.2: backend 138 pass/7 skips, 82%;
- PostgreSQL 16.14: migración, E2E 1 pass y 7 transaccionales;
- Node 22.13.1: 4 archivos/16 tests, build y audit 0 vulnerabilidades;
- Terraform 1.14.3: fmt/init/validate y 8 tests deploy;
- Docker runtime/audit y tres boundaries E0: success;
- secret scan: success.

El PR body y la documentación de estado todavía dicen que Cloud Build,
Terraform plan, GCP, Supabase y R2 no se ejecutaron. Son snapshots históricos,
no el estado actual (`AUD-P2-09`).

## Terraform: investigación obligatoria

### Resultado vivo

Se ejecutó `terraform plan -input=false -lock=false -detailed-exitcode` con
Terraform 1.14.0, provider google 6.50.0, state original y únicamente valores
públicos más un placeholder para la publishable key no usada por recursos.
Resultado:

```text
# google_cloud_run_v2_service.web[0] will be updated in-place
- scaling {
    manual_instance_count = 0 -> null
    min_instance_count    = 0 -> null
  }
Plan: 0 to add, 1 to change, 0 to destroy.
exit 2
```

| Pregunta obligatoria | Conclusión |
|---|---|
| ¿Continúa? | Sí; paquete 2026-08-03 y auditoría 2026-08-04 reproducen la misma diferencia. |
| ¿Service, Job o ambos? | Solo `google_cloud_run_v2_service.web[0]`; Job y resto sin cambios. |
| ¿Configuración? | La configuración gestiona `template.scaling` min/max, pero omite el bloque superior `service.scaling`. |
| ¿Provider/API? | Provider 6.50.0 refresca defaults API del bloque superior como ceros aunque HCL lo omite; luego plan intenta llevarlos a null. |
| ¿State obsoleto? | No es la causa suficiente: cada refresh vivo vuelve a obtener los ceros. El state refleja la normalización remota. |
| ¿Converge? | No con la configuración versionada; múltiples planes posteriores terminaron 2. |
| ¿Excepción documentada? | El paquete intentó aceptar esa diferencia, pero `docs/EXTERNAL_SETUP.md` dice expresamente que exit 2 bloquea la verificación. No hay excepción canónica aprobada. |
| ¿Gate? | Exige exit 0. |

### Solución probada sin aplicar

Se probaron dos variantes únicamente en copias de `/tmp` con copia del state:

1. `lifecycle.ignore_changes = [scaling]`: plan exit `0`.
2. Declarar el bloque superior con `manual_instance_count = 0` y
   `min_instance_count = 0`: plan exit `0`, `No changes`.

La segunda es la recomendación conservadora porque no oculta futuros cambios
de esa superficie. Afecta solo a la declaración de
`google_cloud_run_v2_service.web`; no cambia `template.scaling`, el Job, la
imagen, IAM ni secretos y, contra el estado actual, no propone acción remota.
Debe implementarse en una remediación separada, con fmt/validate/tests y dos
planes vivos consecutivos exit `0`. Actualizar provider puede investigarse,
pero no fue necesario ni probado como solución.

## Secret Manager e IAM

Existen cuatro secretos administrados y etiquetados por Terraform:

- `cva-database-url`;
- `cva-r2-access-key-id`;
- `cva-r2-secret-access-key`;
- `cva-session-secret`.

Cada uno tiene versión `1` habilitada; nunca se imprimió su valor. Service y
Job referencian versiones, no valores inline. La auditoría obtuvo la URL DB solo
como variable de proceso y ejecutó consultas read-only. El worker recibe los
cuatro secretos aunque no sirve sesiones HTTP; desacoplar su settings/runtime
permitiría retirar `cva-session-secret` de su IAM (`AUD-P2-13`).

## Supabase Auth y PostgreSQL

### Auth

El JWKS público respondió `200`, algoritmo ES256. La implementación valida
issuer, audience, firma y membership. La evidencia primaria registra magic link
y un usuario/membership docente. El auditor no dispuso de acceso admin Supabase
para repetir invitation/email/callback; tampoco se guardó un token.

### PostgreSQL administrado

Se usó una transacción/default read-only; no se leyó texto ni identificadores.

| Comprobación agregada | Observado |
|---|---|
| Versión | PostgreSQL 17.6, x86_64 |
| Tablas públicas / con RLS | 24 / 24 |
| Grants `anon`/`authenticated` | 0 |
| Tablas con grant `service_role` | 24 |
| Triggers append-only | `audit_events_are_append_only`, `model_calls_are_append_only` |
| Filas | 1 user, 1 membership, 2 activities, 2 submissions, 4 jobs, 18 model calls, 5 audit events |
| Submission states | 1 `APPROVED`, 1 `UPLOADED` |
| Job states | 3 `SUCCEEDED`, 1 `FAILED` |
| Assessment states | 1 `APPROVED`, 1 `NEEDS_REVIEW` |
| Identidades | 1/1 users UUID; 5/5 audit actors UUID |
| Ledger | P01–P05 ×2; P06 ×1; P07 ×3; P08 ×3; P09 ×1; P10 ×0; 18 `SCHEMA_VALID` |

La producción usa major 17 mientras CI usa 16; el E2E real pasó, pero falta
regresión automatizada en el major administrado (`AUD-P2-08`).

## Cloudflare R2

El paquete contiene salidas primarias de lifecycle, r2.dev, domain list,
privacy y CORS; la secuencia es compatible con el bucket final
`cva-experimento-raw-wiljms`. También registra una capacidad de descarga `200`
inmediata y `403` después de 300 segundos. Una petición anónima viva al endpoint
S3 devolvió `400 InvalidArgument: Authorization`, consistente con no permitir
listing sin firma.

`wrangler 4.118.0 whoami` indicó “not authenticated”. Por ello no se
revalidaron independientemente r2.dev, dominios, CORS, lifecycle ni scope del
token. La evidencia aportada es útil y primaria, pero no es autoridad ni acceso
independiente (`AUD-P2-14`).

## Logs y secretos

Antes de leer el paquete se escaneó por private keys, bearer/JWT, cloud tokens,
credential URLs y asignaciones sensibles: cero hallazgos de alta confianza.
Los nombres de secretos, JWKS y publishable key pública no se trataron como
secretos; sus valores sensibles no se copiaron a los informes.

Se analizaron las 1.712 entradas Cloud Run disponibles en 48 horas sin imprimir
mensajes. Resultado: cero patrones de JWT, email, URL con password, firma R2 o
ruta fake con capability. Distribución: 1.298 default, 368 info, 32 warning, 9
notice y 5 error. La prueba es heurística y no demuestra que ningún texto
arbitrario pueda aparecer en una ruta de error futura.

## Coherencia del paquete externo

| Hallazgo de evidencia | Clasificación |
|---|---|
| Checksum del tar coincide; 92 archivos; 0 paths inseguros, duplicados de path o especiales. | Cadena de custodia válida. |
| `phase-20-final-state.txt` usa commit `a817546…`, build inicial y digest `a09ff…`. | Archivo intermedio/obsoleto, no snapshot final. |
| Descripciones Service/Job de 12:46 muestran generación 1/digest inicial; imágenes finales llegaron después. | Snapshot intermedio, no prueba final. La consulta viva corrigió la carencia. |
| Tres builds/digests (inicial, auth fix, principal fix). | Secuencia explicable, no contradicción si se etiqueta por fase. |
| `health-principal-fix.txt` tiene 0 bytes. | No evidencia nada; health previo a principal fix no prueba esa imagen. Health vivo sí lo hace. |
| `model-call-original-attempt-invalid.txt` admite interpolación psql incorrecta y dos archivos vacíos. | Intento inválido; no usar. Recheck 8→8 es la evidencia aplicable. |
| Control de fallo calculó exit CLI con `PIPESTATUS` bajo zsh. | Exit numérico no demostrado; DB y Cloud Run failed sí son evidencia directa. |
| `SUMMARY.txt` acepta drift recurrente aunque la guía canónica lo bloquea. | Resumen de agente, contradicción con gate; prevalece `EXTERNAL_SETUP`. |
| Manifest incluido contiene nombres, no hashes/correlación por archivo. | Índice incompleto; sustituido por `STAGE1_EVIDENCE_MANIFEST.md`. |
| GitHub/PR final del paquete apunta a `0167f14…`; HEAD actual avanzó solo por auditorías. | Evidencia directa del ancestro, indirecta del HEAD funcional. |

## Accesos

Usados: GitHub app read-only; `gcloud` con cuenta activa para metadatos GCP,
logs, objeto source y Secret Manager; HTTPS público para Service/JWKS/R2;
PostgreSQL mediante secreto efímero en memoria y sesión read-only; Terraform
state local ignorado y plan read-only.

Faltantes: Cloudflare/Wrangler autenticado y Supabase Auth admin/CLI. No se
solicitó una credencial pegada ni se amplió IAM.

## Cierre

El stack es real y el happy path es verosímil y ampliamente demostrado. No se
puede cerrar E1-11 hasta remediar `AUD-P1-01` y `AUD-P1-02`, repetir la cadena
desde el SHA final y producir un snapshot externo coherente. Ningún resultado
autoriza Etapa 2.

`READY_FOR_STAGE1_REMEDIATION`
