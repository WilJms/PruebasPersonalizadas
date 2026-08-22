# Manual E2E Product Pilot

Runbook local para recorrer actividad, submissions, revisión docente,
`GUIDE_BUILD` y exports con PostgreSQL/R2 compartidos y ejecución one-shot por
job. Este documento no es una autorización de gasto y no debe usarse con datos
estudiantiles reales.

## Frontera del piloto

Actividad, submission, una regeneración P07 y `GUIDE_BUILD` usan el provider
real únicamente en un worker autorizado para el job exacto. El web permanece
en `CVA_MODEL_MODE=mock`: sólo valida, persiste y despacha operaciones
durables. `ACCEPT`, `EDIT` y `REJECT` no necesitan provider. Una acción
`REGENERATE` crea primero un `QUESTION_ACTION` `QUEUED`; la pregunta vigente no
cambia hasta que el worker exacto termina validación y materialización.

No cambie el web a `CVA_MODEL_MODE=real`, no le entregue una clave y no
improvise una autorización. Este runbook tampoco autoriza gasto: cada job
provider-bearing requiere una aprobación operativa externa y explícita.

## 1. Preconditions

Use exclusivamente:

- repositorio `WilJms/PruebasPersonalizadas`;
- PR `#3`, todavía `OPEN`, `DRAFT` y no mergeado;
- rama `codex/openai-real-provider-gate`;
- baseline durable/manual
  `5ab776f9a95e1b1d2fe23405e7e1c960564c0dbb`;
- un `PILOT_CANDIDATE_SHA` exacto de 40 hex que sea el HEAD revisado del PR y
  descendiente de ese baseline.

Compruebe el checkout antes de cada run:

```bash
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor \
  5ab776f9a95e1b1d2fe23405e7e1c960564c0dbb HEAD
gh pr view 3 --repo WilJms/PruebasPersonalizadas \
  --json state,isDraft,mergedAt,headRefName,headRefOid
git status --short
```

Deténgase si la rama no coincide, si el HEAD no es el candidato aprobado, si
el PR no está `OPEN`/`DRAFT`/`mergedAt: null`, o si hay cambios locales no
explicados.

Requisitos locales vigentes:

- Python `>=3.12` y el virtualenv instalado con `make install`;
- Node `>=22.13` y dependencias instaladas con `make frontend-install`;
- PostgreSQL compartido con las migraciones 001–007 aplicadas en orden y
  `/api/readiness` verde;
- bucket R2 privado compartido por web y worker, con credenciales limitadas al
  bucket;
- CORS temporal de R2 para el origen exacto
  `http://127.0.0.1:5173`, con `GET`, `PUT`, `HEAD`, header `Content-Type` y
  `ETag` expuesto;
- una versión numérica fijada de Secret Manager, con forma
  `projects/PROJECT/secrets/SECRET/versions/N`; nunca `latest`;
- credenciales ADC/Workload Identity del operador capaces de leer sólo esa
  versión cuando el worker alcance el gate post-claim;
- candidate SHA, caps, expiry, `authorization_id` y `created_by` aprobados
  explícitamente por el operador para cada job provider-bearing.

No copie la API key a shell history, chat, Git, `.env`, variables del web ni
argumentos. No defina `OPENAI_API_KEY` ni `CVA_OPENAI_API_KEY`. El worker recibe
sólo la referencia numérica; resuelve la clave después de claim y attestation.

La UI corre en `http://127.0.0.1:5173`; `http://localhost:5173` es otro origen
y no queda cubierto por la regla CORS anterior. No amplíe CORS a `*`. Retire el
origen local al terminar el piloto mediante el procedimiento externo revisado;
este runbook no aplica cambios en Cloudflare.

## 2. Configuración del web local

Guarde los valores compartidos en un archivo con permisos `0600`, fuera del
repositorio y fuera de cualquier directorio sincronizado. El siguiente bloque
contiene sólo placeholders:

```bash
CVA_PILOT_SHARED_ENV=/absolute/path/outside/repo/manual-pilot.shared.env
umask 077
${EDITOR:-vi} "$CVA_PILOT_SHARED_ENV"
chmod 600 "$CVA_PILOT_SHARED_ENV"
```

Contenido esperado:

```bash
CVA_DATABASE_URL='postgresql+psycopg://replace-with-user:replace-with-password@replace-with-host:5432/replace-with-database'
CVA_OBJECT_STORE_MODE='r2'
CVA_R2_ENDPOINT_URL='https://ACCOUNT_ID.r2.cloudflarestorage.com'
CVA_R2_BUCKET='PRIVATE_BUCKET'
CVA_R2_ACCESS_KEY_ID='replace-with-scoped-access-key-id'
CVA_R2_SECRET_ACCESS_KEY='replace-with-scoped-secret-access-key'
CVA_SESSION_SECRET='replace-with-local-random-value-of-at-least-32-characters'
CVA_LOCAL_INVITED_EMAILS='teacher@example.test'
CVA_LOCAL_WORKSPACE_ID='tnt_experimental'
CVA_MAX_UPLOAD_BYTES='5000000'
CVA_REQUIRE_LIBMAGIC='true'
```

En la terminal del web:

```bash
set -a
. "$CVA_PILOT_SHARED_ENV"
set +a

env -u OPENAI_API_KEY -u CVA_OPENAI_API_KEY \
  CVA_ENVIRONMENT=local \
  CVA_AUTH_MODE=local \
  CVA_OBJECT_STORE_MODE=r2 \
  CVA_JOB_RUNNER_MODE=manual \
  CVA_MODEL_MODE=mock \
  CVA_P10_ENABLED=false \
  .venv/bin/python -m uvicorn comprehension_verification.web.app:app \
    --host 127.0.0.1 --port 8000 --no-access-log
```

`manual` es local-only. El web persiste y devuelve cada job, pero no llama
`process_job`, no crea tareas, no invoca Cloud Run, no consulta GCP, no resuelve
secretos y no consume autorizaciones. Verifique la base antes de abrir la UI:

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/readiness
```

## 3. Frontend

En otra terminal, no cargue las variables privadas del web:

```bash
cd frontend
env VITE_SUPABASE_URL= VITE_SUPABASE_PUBLISHABLE_KEY= \
  VITE_API_BASE_URL=/api/v1 \
  npm run dev -- --host 127.0.0.1
```

Vite sirve `http://127.0.0.1:5173` y proxifica `/api` a
`http://127.0.0.1:8000`. Abra la URL, ingrese con uno de los correos de
`CVA_LOCAL_INVITED_EMAILS` y confirme que aparece la lista `Actividades`.

Los uploads del navegador no pasan por el proxy: usan directamente la URL
firmada de R2. Un error CORS en el PUT se corrige en la configuración externa
de R2; nunca poniendo credenciales R2 en el frontend.

## 4. Ciclo exacto para un job con provider

Use este ciclo sólo para jobs cuyo kind activo requiere modelo: `ACTIVITY`,
`SUBMISSION`, `QUESTION_ACTION`, `GUIDE_BUILD` y una continuación
provider-bearing creada por retry/resume. No lo use para
`BLUEPRINT_PREFLIGHT` o `BLUEPRINT_REVIEW`.

En una tercera terminal, vuelva a fijar la ruta, cargue los valores compartidos
y añada los inputs aprobados del operador. Todos los IDs deben ser canónicos
(`[a-z][a-z0-9_-]{2,127}`):

```bash
CVA_PILOT_SHARED_ENV=/absolute/path/outside/repo/manual-pilot.shared.env
set -a
. "$CVA_PILOT_SHARED_ENV"
set +a

PILOT_CANDIDATE_SHA='<APPROVED_40_HEX_HEAD>'
PILOT_SECRET_VERSION_RESOURCE='projects/PROJECT/secrets/SECRET/versions/N'
PILOT_MAX_REQUESTS='<EXPLICIT_JOB_CAP>'
PILOT_MAX_COST_USD='<EXPLICIT_JOB_CAP_USD>'
PILOT_CREATED_BY='operator_pilot'
PILOT_EXPIRY_MINUTES='<5_TO_60>'

test "$(git rev-parse HEAD)" = "$PILOT_CANDIDATE_SHA"
.venv/bin/python -c \
  'from comprehension_verification.provider_authorization import synthetic_provider_boundary_hash; print(synthetic_provider_boundary_hash())'
```

Registre esa salida como el boundary hash esperado para comparar la
autorización. El web permanece mock, por lo que la estimación mostrada por la
UI no concede gasto ni sustituye los caps explícitos ya aprobados para el job.

Después de copiar el ID visible de la UI, defina IDs nuevos para ese job:

```bash
PILOT_JOB_ID='<COPIED_DURABLE_JOB_ID>'
PILOT_AUTHORIZATION_ID='<NEW_UNIQUE_AUTHORIZATION_ID>'
```

Primero autorice. Este comando crea la única attestation append-only; no
despacha, no resuelve clave y no construye transporte:

```bash
env -u OPENAI_API_KEY -u CVA_OPENAI_API_KEY \
  .venv/bin/python scripts/authorize_synthetic_provider_job.py \
    --job-id "$PILOT_JOB_ID" \
    --authorization-id "$PILOT_AUTHORIZATION_ID" \
    --candidate-sha "$PILOT_CANDIDATE_SHA" \
    --secret-version-resource "$PILOT_SECRET_VERSION_RESOURCE" \
    --max-requests "$PILOT_MAX_REQUESTS" \
    --max-cost-usd "$PILOT_MAX_COST_USD" \
    --created-by "$PILOT_CREATED_BY" \
    --expires-in-minutes "$PILOT_EXPIRY_MINUTES"
```

Lea la salida y deténgase salvo que coincidan exactamente `job_id`,
`authorization_id`, candidate SHA, boundary hash esperado, caps y expiry, y que
muestre `key_resolved=false`, `transport_constructed=false` y
`provider_requests=0`.

Sólo entonces ejecute una vez el worker, fijado al mismo job y a los mismos
caps. Las variables R2/PostgreSQL ya provienen del archivo compartido:

```bash
env -u OPENAI_API_KEY -u CVA_OPENAI_API_KEY \
  CVA_ENVIRONMENT=local \
  CVA_OBJECT_STORE_MODE=r2 \
  CVA_MODEL_MODE=real \
  CVA_P10_ENABLED=false \
  CVA_CLAIM_JOB_ID="$PILOT_JOB_ID" \
  CVA_OPENAI_SECRET_VERSION_RESOURCE="$PILOT_SECRET_VERSION_RESOURCE" \
  CVA_SYNTHETIC_EVALUATION_CANDIDATE_SHA="$PILOT_CANDIDATE_SHA" \
  CVA_SYNTHETIC_EVALUATION_MAX_REQUESTS="$PILOT_MAX_REQUESTS" \
  CVA_MAX_JOB_COST_USD="$PILOT_MAX_COST_USD" \
  .venv/bin/python -m comprehension_verification.web.worker
```

No confíe sólo en el exit code: vuelva a la UI, pulse `Actualizar controles` o
espere el polling y confirme el estado durable y los diagnósticos. El worker
reclama como máximo el `CVA_CLAIM_JOB_ID` exacto. No repita el comando sobre un
job ya reclamado o terminal.

## 5. Actividad

1. En `Actividades`, pulse `Nueva actividad`.
2. Complete título, idioma, modalidad, número de preguntas, tiempo, formatos
   de respuesta, formatos de artefacto y política de justificación.
3. Cargue la consigna y la rúbrica sintéticas. No use datos reales.
4. Pulse el botón de preparación para crear la actividad, subir los archivos y
   obtener la estimación.
5. Revise la estimación y pulse `Confirmar e iniciar blueprint`.
6. La UI abre `Construyendo el blueprint`. El panel `Control durable del job`
   debe mostrar `En cola`, progreso 0 %, el `Identificador durable` y el botón
   `Copiar job ID`. El estado `QUEUED` es espera deliberada, no error.
7. Use el ciclo de la sección 4 con un `PILOT_AUTHORIZATION_ID` nuevo, por
   ejemplo un ID canónico dedicado a actividad.
8. Vuelva a la UI. Revise interpretación, normalización de rúbrica,
   ambigüedades, diagnósticos, dimensiones, variantes y oportunidades.
9. Si P03 exige decisiones, elija cada opción en la UI y confirme. La nueva
   generación crea otro job `ACTIVITY`: copie su nuevo ID, cree otra
   autorización y ejecute otro worker exacto. Nunca reutilice la anterior.
10. Cuando el preflight sea factible, revise el blueprint y pulse aprobación.

Editar un blueprint crea un job determinista `BLUEPRINT_PREFLIGHT`. En modo
manual también queda `QUEUED`, pero no admite una autorización provider. Para
ese job ejecute sólo el worker mock exacto:

```bash
PILOT_JOB_ID='<BLUEPRINT_PREFLIGHT_JOB_ID>'
env -u OPENAI_API_KEY -u CVA_OPENAI_API_KEY \
  -u CVA_OPENAI_SECRET_VERSION_RESOURCE \
  -u CVA_SYNTHETIC_EVALUATION_CANDIDATE_SHA \
  CVA_ENVIRONMENT=local \
  CVA_OBJECT_STORE_MODE=r2 \
  CVA_MODEL_MODE=mock \
  CVA_P10_ENABLED=false \
  CVA_CLAIM_JOB_ID="$PILOT_JOB_ID" \
  .venv/bin/python -m comprehension_verification.web.worker
```

No cree synthetic provider authorization para ese kind.

## 6. Submission

1. Abra `Lote de entregas` y pulse `Alta individual`.
2. Ingrese una referencia seudónima canónica; no use nombre, correo ni
   matrícula.
3. Cargue un único entregable sintético compatible y obtenga la estimación.
4. Pulse `Confirmar e iniciar pipeline`.
5. En `Pipeline por evidencia`, confirme que el job técnico está `En cola` y
   copie el ID desde `Control durable del job`.
6. Use la sección 4 con un authorization ID nuevo para ese `SUBMISSION`.
7. Vuelva a la UI. Espere `NEEDS_REVIEW` y pulse `Revisar evaluación`.
8. Cargue y verifique cada fragmento de evidencia antes de actuar sobre una
   pregunta. La aprobación permanece bloqueada mientras falten receipts.

Cada submission tiene artefactos, job, autorización, assessment y guía
independientes. No comparta IDs ni autorizaciones entre submissions.

## 7. Revisión docente

Las acciones actuales significan:

- `ACCEPT`: registra aceptación durable de la pregunta sin cambiarla, sin
  nueva versión y sin llamada al modelo.
- `EDIT`: la UI permite cambiar sólo `question_text` sobre una copia canónica
  completa; el servidor preserva identidad, oportunidad y evidencia y aplica
  revalidación determinista. No llama al provider.
- `REJECT`: registra el rechazo y su motivo; no inventa reemplazo. La
  aprobación queda bloqueada hasta una resolución posterior de esa pregunta.
- `REGENERATE`: prepara una oportunidad de reserva y crea un
  `QUESTION_ACTION` durable `QUEUED`. P07 sólo se ejecuta después en el worker
  exacto; la versión y pregunta vigentes permanecen visibles mientras espera.
  Una aplicación válida preserva el question ID, exactamente N preguntas,
  justificación, evidencia, lineage y límites de regeneración.

Use `ACCEPT` cuando la pregunta ya sea adecuada, `EDIT` para una corrección de
texto compatible con la misma evidencia, y `REJECT` cuando no deba aprobarse.
No use `REGENERATE` como retry genérico.

Para una regeneración gobernada:

1. Pulse `Regenerar pregunta`, elija el motivo y confirme.
2. Compruebe que la UI muestra `Regeneración durable pendiente`, el
   `QUESTION_ACTION` en `En cola` y la pregunta original sin reemplazo
   optimista.
3. Copie el `job_id` desde `Control durable del job`. Puede cerrar o refrescar
   la pantalla: la operación pending se recupera desde persistencia.
4. Ejecute la sección 4 con una synthetic authorization nueva ligada a ESE
   job. Una autorización anterior del `SUBMISSION` no es reutilizable.
5. Antes de ejecutar, verifique en la salida de autorización el job ID,
   candidate SHA, provider boundary, request/cost caps y expiry exactos, además
   de `key_resolved=false`, `transport_constructed=false` y
   `provider_requests=0`.
6. Ejecute una sola vez el worker con `CVA_CLAIM_JOB_ID` igual al ID copiado.
   No permita fallback a mock. Una regeneración nominal consume una llamada
   P07 por esta autorización independiente.
7. Vuelva a la UI y refresque la página de revisión.
8. Confirme la nueva versión del Assessment, la pregunta regenerada, exactamente
   N preguntas y la acción aplicada en el historial durable.
9. Cargue y verifique los localizadores de la evidencia de reemplazo. Después
   continúe aceptando/editando/rechazando preguntas o apruebe el Assessment
   cuando todas las precondiciones estén satisfechas.

Un retry/resume técnico crea un job durable nuevo. Si ese job volverá a tocar
provider, necesita otro authorization ID, una nueva attestation y un worker
fijado al nuevo job. El ID y autorización anteriores no se reutilizan.

## 8. Assessment approval y `GUIDE_BUILD`

1. Confirme que todas las evidencias están verificadas y que no existe una
   acción `REJECT` o revalidación fallida sin resolver.
2. Pulse `Aprobar Assessment`. La aprobación exacta y durable crea o reconcilia
   un job separado `GUIDE_BUILD`; P09 no corre dentro de la aprobación.
3. Abra la pestaña `Guía estructurada`. Mientras espera, muestra `Guía
   pendiente` y el `guide_job_id` como código. Cópielo exactamente.
4. Use la sección 4 con ese ID y un authorization ID nuevo. No reutilice la
   autorización del submission.
5. Vuelva a la pestaña. El polling cambia de `PENDING/BUILDING` a `READY` o
   muestra el fallo durable. Revise propósito, observables, condiciones de
   aceptación, alternativas, misconceptions, límites de inferencia, niveles y
   diagnósticos de la `EvaluationGuide`.

## 9. Exports

Con Assessment aprobado y guía `READY`, use `Vistas derivadas` para generar y
descargar los formatos disponibles, incluidos Assessment/Guide HTML y PDF,
canonical JSON y reportes de cobertura cuando aparezcan en la UI. Revise
también el historial de exports.

Los exports se derivan de Assessment, EvaluationGuide y cobertura persistidos;
no crean model calls. Un export `QUEUED` se actualiza desde su estado durable y
un export `FAILED` se diagnostica como render/storage, no se “arregla”
autorizando provider.

## 10. Segunda y tercera submissions

Repita desde la sección 6 para cada entrega:

```text
UI crea SUBMISSION job QUEUED
→ autorización nueva ligada a ese job/artefactos/attempt
→ worker one-shot con claim exacto
→ revisión docente
→ aprobación
→ GUIDE_BUILD nuevo y autorización independiente
→ worker one-shot
→ guía y exports
```

No cambie prompts, routing, modelo, reasoning effort, thresholds ni benchmark
entre resultados. No haga tuning después de observar una submission. Registre
los resultados por separado.

## 11. Failure handling

| Situación | Interpretación y acción segura |
|---|---|
| Job todavía `QUEUED` | Espera normal en `manual`. Si no existe autorización, créela sólo tras revisar todos los inputs. Si ya existe, verifique scope/expiry/caps antes de ejecutar una sola vez el worker. |
| Autorización ausente | No ejecute el worker real. Si se ejecuta, el claim falla cerrado como `SECURITY` y no alcanza resolver/transport. El job fallido no se reabre manualmente. |
| Autorización expirada | No se extiende ni reutiliza. Cree un retry/job nuevo por la aplicación y una autorización nueva. |
| Scope, candidate, boundary, secret, cap o artifact hash mismatch | Detenga el run. El worker debe fallar antes de resolver la clave. No relaje el matcher ni edite filas. |
| Job ya reclamado o autorización consumida | No vuelva a ejecutar. Observe el estado terminal o use retry/resume permitido, que crea un ID nuevo y requiere autorización nueva si toca provider. |
| Provider failure | Espere `FAILED` y revise diagnóstico content-free. Use `Reintentar job` sólo si la UI lo permite; autorice el resulting job nuevo. |
| Fallo determinista o semántico del modelo | Distinga invariantes/validación de transporte. Puede terminar `FAILED` o `NEEDS_REVIEW`; no autorice a ciegas otro intento. |
| `NEEDS_REVIEW` | Resultado de dominio accionable por docente; no equivale a fallo técnico ni justifica retry automático. |
| `FAILED` | Estado técnico terminal. Use únicamente acciones server-authorized de retry/resume y nunca cambie la fila a mano. |
| Teacher retry | El nuevo job conserva lineage y stage runs; si requiere provider, necesita attestation nueva. |
| Teacher `REGENERATE` pendiente | La pregunta anterior sigue vigente. Copie el `QUESTION_ACTION` visible, cree su autorización independiente y ejecute sólo el worker exacto; no autorice de nuevo el `SUBMISSION`. |

Un worker one-shot que no encuentra el job exacto puede salir sin procesar
otro job. Aun así, confirme siempre el estado en la UI; no use el exit code
como sustituto del estado durable.

## 12. Stop conditions

Deténgase sin ejecutar el worker o sin repetirlo ante cualquiera de estos
hechos:

- HEAD inesperado, PR no draft/open o candidate SHA distinto;
- secret resource no numérico o versión distinta de la aprobada;
- request/cost cap distinto entre autorización y worker;
- provider boundary, ruta/modelo o candidate SHA mismatch;
- artefactos o hashes distintos de la attestation;
- job state distinto del esperado;
- cualquier intento de poner una provider key en web, frontend, shell history,
  chat o Git;
- cualquier necesidad de relajar exactly-once, scope, expiry, caps o checks de
  artefactos;
- CORS ampliado más allá del origen local exacto;
- datos no sintéticos o cualquier historia de Etapa 3.

Al cerrar el piloto, detenga web y Vite, retire el origen CORS local mediante un
cambio externo revisado, y conserve sólo metadata content-free permitida. No
haga deploy, Terraform apply ni cambios externos desde este runbook sin una
autorización separada.
