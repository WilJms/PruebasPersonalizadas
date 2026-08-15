# Decisiones menores de implementación

> **Precedencia ADR-037 (2026-08-14):** estas decisiones son un registro
> temporal. D-074 gobierna la autoridad actual; cualquier mención anterior a
> evidencia “vigente”, gates abiertos o una autoridad siguiente describe sólo
> su checkpoint histórico y no convierte el harness legado en gate canónico de
> selección de modelo.

## D-001 - Cargar el modelo canónico en su ubicación original

- **Decisión:** `src/comprehension_verification/contracts.py` carga
  `specification/models_v1.1(1).py` sin copiar sus clases.
- **Razón:** los archivos recibidos tienen sufijo `(1)`, mientras la
  documentación usa nombres sin sufijo. Renombrar o duplicar el contrato no es
  necesario para E0 y aumentaría el riesgo de drift.
- **Alternativas:** copiar modelos al paquete; renombrar artefactos canónicos.
  Ambas se descartaron por crear otra fuente o alterar artefactos vinculantes.
- **Relación:** ADR-028.

## D-002 - Salida final de E0 requiere revisión humana

- **Decisión:** el fixture puede contener una aprobación sintética explícita del
  blueprint, pero el `Assessment` producido queda `NEEDS_REVIEW`; nunca se
  autoaprueba ni publica.
- **Razón:** permite probar el pipeline por submission sin fingir una decisión
  académica humana.
- **Relación:** ADR-001, ADR-016/034 y gate de E0.

## D-003 - Validadores contextuales conservadores

- **Decisión:** además de Pydantic/JSON Schema, E0 exige diagnóstico completo en
  toda abstención, outputs no utilizables vacíos y comprobaciones de IDs,
  pertenencia, anclas, fuentes y procedencia.
- **Razón:** algunos roots estructurales permiten combinaciones que el Prompt
  Pack prohíbe operacionalmente.
- **Relación:** ADR-005, ADR-008, ADR-028 y VALIDACION_CONTRATOS.

## D-004 - Etapa 1 conserva IA mock y contexto cerrado por defecto

- **Decisión:** `CVA_MODEL_MODE=mock` y `CVA_P10_ENABLED=false` son los
  defaults locales, de pruebas, del contenedor y de la infraestructura de
  Etapa 1. El arranque cloud rechaza adaptadores locales y secretos de
  desarrollo.
- **Razón:** todavía no hay credencial ni presupuesto de proveedor, y P10 no
  pertenece al primer recorrido vertical.
- **Relación:** ADR-032/033/034 y gate de Etapa 1.

## D-005 - Supabase autentica; la aplicación emite su propia sesión

- **Decisión:** en cloud, React obtiene una sesión de Supabase Auth y entrega
  temporalmente su access token a `/api/v1/session/exchange`. FastAPI valida
  firma ES256/RS256, issuer y audience mediante JWKS; por tanto, la cuenta
  externa debe usar un signing key asimétrico y nunca entregar el secreto
  legacy HS256 al backend. Después exige una membresía previamente persistida
  y emite una cookie `HttpOnly`, `Secure`, `SameSite=Lax` más un token CSRF de
  doble envío. El login local por lista de invitados existe solo para
  desarrollo y pruebas.
- **Razón:** las rutas privadas no dependen de datos de rol controlados por el
  navegador y una cuenta válida sin invitación no obtiene acceso al workspace.
- **Relación:** E1-01 y ADR-032.

## D-006 - Job durable antes del dispatch y sin contenido en overrides

- **Decisión:** la API crea atómicamente la fila `jobs` y congela el agregado
  antes de invocar Cloud Run Jobs. El dispatch no transmite `subject_ref`,
  paths, texto ni `job_id`; el worker reclama con lock la fila `QUEUED` más
  antigua y procesa la ejecución desde PostgreSQL.
- **Razón:** cerrar el navegador no cancela el trabajo y los parámetros de la
  ejecución cloud no se convierten en otro canal de fuga.
- **Relación:** E1-06/E1-07/E1-11 y ADR-013/032.

## D-007 - Carga temporal seguida de sellado inmutable

- **Decisión:** una sesión firmada escribe a una clave desechable `/upload`.
  Al completar, el servidor comprueba HEAD, límite, MIME, tamaño y hash con una
  lectura acotada, parsea de forma segura y copia a una clave
  content-addressed `/sealed/{sha256}` usando escritura condicional. La fila
  pasa a apuntar solamente al objeto sellado y cada consumo vuelve a verificar
  sus bytes.
- **Razón:** una URL PUT todavía vigente nunca puede modificar el artefacto que
  alimenta evidencia, pipelines o exports.
- **Relación:** E1-03, ADR-005/008 y reglas de seguridad del repositorio.

## D-008 - Idempotencia HTTP atómica sin persistir capacidades

- **Decisión:** cada mutación de dominio POST/PATCH/DELETE requiere un
  `Idempotency-Key` UUID. Se reserva `(tenant,key,fingerprint)` antes del
  handler; el fingerprint incluye principal, rol y permiso de aprobación. Un
  replay solo devuelve el resultado canónico si la membresía vigente coincide.
  URLs firmadas y expiraciones no se guardan: para uploads, exports y evidence
  verify solo se persiste un descriptor allowlist y se firma una capacidad
  nueva después de volver a autorizar y validar CSRF. Un guard recursivo del
  repositorio rechaza cualquier descriptor que contenga una URL/capability.
- **Razón:** evita efectos duplicados y evita convertir la tabla de
  idempotencia en un almacén de credenciales temporales.
- **Relación:** ADR-013 y E1-03/E1-11.

## D-009 - Inputs y aprobaciones se congelan con versión exacta

- **Decisión:** configuración de actividad y uploads de sus fuentes solo se
  mutan en `DRAFT`; uploads de submission se congelan al encolar. Edición y
  aprobación usan `ETag/If-Match`, crean una nueva versión y una versión
  aprobada es inmutable. Cada submission persiste `blueprint_version` al
  encolar y el worker revalida esa misma versión y su evento de auditoría.
- **Razón:** elimina lost updates y cambios TOCTOU entre aprobación, dispatch y
  ejecución.
- **Relación:** E1-02/E1-05/E1-06, ADR-002/013/030.

## D-010 - Los estados no READY detienen cada frontera

- **Decisión:** P01-P05 y P06-P09 se validan estructural y contextualmente. Un
  output no utilizable no se transforma en un objeto posterior; el job queda
  `NEEDS_REVIEW` o `FAILED` y la submission conserva un estado de dominio
  explícito. Solo P03 puede continuar tras decisiones docentes persistidas.
- **Razón:** un contrato Pydantic válido no basta para autorizar uso semántico
  ni para fabricar aprobación humana.
- **Relación:** E1-04/E1-06 y ADR-005/034.

## D-011 - PDF y JSON son vistas derivadas

- **Decisión:** Assessment y EvaluationGuide siguen siendo objetos separados.
  Los PDF y el JSON canónico se producen únicamente desde versiones aprobadas
  y no llaman nuevamente al gateway. ReportLab conserva fixtures locales
  deterministas; cloud usa Jinja2 + WeasyPrint.
- **Razón:** exportar no puede cambiar preguntas, guía, costos ni trazabilidad.
- **Relación:** E1-09 y ADR-003/032.

## D-012 - Persistencia cloud alinea una superficie verificable con el ORM

- **Decisión:** la migración Supabase alinea nombres de tablas y columnas con
  el modelo SQLAlchemy de Etapa 1. PostgreSQL real comprueba además que todas
  las tablas tienen RLS y que existen los dos triggers append-only. Esto no se
  denomina “equivalencia exacta”: el verificador no compara exhaustivamente
  todos los tipos, defaults, foreign keys, uniques e índices entre DDL y ORM.
  FastAPI y el worker usan la conexión de servicio; R2 conserva bytes
  raw/sellados y exports.
- **Razón:** declarar con precisión la superficie comprobada evita atribuir a
  una comparación parcial garantías que no demuestra.
- **Relación:** E1-10/E1-11 y ADR-032.

## D-013 - No adelantar robustez ni acciones de Etapa 2 (histórica E1)

- **Decisión:** Etapa 1 admite una sola submission, una única ejecución por
  estado de decisión y aprobación completa. No se añaden retry general,
  cancelación, lote, OCR/DOCX, edición/regeneración por pregunta, aprobación
  masiva, feedback ni borrado operativo.
- **Razón:** esas capacidades pertenecen expresamente a E2-01 a E2-15.
- **Relación:** plan v1.1, secciones “Fuera de etapa” de Etapa 1 y Etapa 2.
- **Vigencia:** preserva el alcance histórico de E1. Fue superada para la rama
  E2 por `STAGE2_GATE_OPEN` del 2026-08-07; no limita E2-01 a E2-15 ni abre E3.

## D-014 - El magic link se completa solo mediante el callback de Auth

- **Decisión:** `signInWithOtp` se usa únicamente para solicitar el enlace con
  `shouldCreateUser=false`. Aunque un mock o versión del SDK devolviera una
  sesión inmediata, el frontend no la intercambia; espera el evento canónico de
  Supabase Auth y recién entonces llama `/api/v1/session/exchange`.
- **Razón:** una respuesta no canónica de la operación de envío no debe saltarse
  el boundary de callback/JWT ni crear una segunda semántica de login.
- **Relación:** E1-01, ADR-032 y D-005.

## D-015 - La migración se valida contra PostgreSQL y el ORM ejecutable

- **Decisión:** `scripts/prepare_postgres.py` solo acepta URLs PostgreSQL de
  loopback, aplica la migración a una base vacía y compara tablas/columnas con
  `Base.metadata`; además exige RLS en las 24 tablas y los dos triggers
  append-only. CI ejecuta este boundary con PostgreSQL 16 antes del E2E y de
  pruebas transaccionales de idempotencia, claims, unicidad, stage keys, CAS,
  aislamiento tenant y append-only.
- **Razón:** SQLite y una comparación textual no validan la aplicación del DDL,
  RLS, triggers ni el comportamiento transaccional del driver PostgreSQL. La
  comparación ORM continúa limitada a tablas y columnas, como explicita D-012.
- **Relación:** E1-06/E1-10/E1-11, ADR-032 y D-012.

## D-016 - Runtime Docker y target de auditoría son superficies distintas

- **Decisión:** `runtime` sigue siendo el último target y no copia fixtures. El
  target `audit` hereda el mismo runtime y agrega fixtures sintéticos únicamente
  para ejecutar `run-synthetic` y generar exports dentro del contenedor.
- **Razón:** la verificación requerida no justifica aumentar la superficie ni
  el contenido de la imagen desplegable.
- **Relación:** E0-02/E0-08/E1-09/E1-11.

## D-017 - Router SPA sin advisories alcanzables ni pendientes

- **Decisión:** se sustituyó `react-router-dom` por Wouter 3.10.0, preservando
  las rutas privadas, parámetros, estado de navegación y deep links. El
  lockfile final pasa `npm audit` con cero vulnerabilidades.
- **Razón:** React Router 7.18.2 corregía advisories de rutas/SSR anteriores pero
  quedaba dentro de una advisory high de RSC; bajar a 7.11.0 reabría XSS,
  deserialización/RCE y DoS. La aplicación es una SPA pequeña y no necesita RSC
  ni el peso del router anterior.
- **Relación:** E1-01/E1-07/E1-11 y cierre correctivo.

## D-018 - El correo local visible debe ser una invitación válida

- **Decisión:** el valor inicial de la pantalla local es
  `teacher@example.test`, igual al default `CVA_LOCAL_INVITED_EMAILS`, y existe
  una aserción frontend que fija esa relación.
- **Razón:** una demo que precarga un usuario no invitado produce un 403 real y
  oculta fallos de integración detrás de un detalle cosmético.
- **Relación:** E1-01.

## D-019 - Dos gates de cierre distintos (decisión histórica del 2026-08-01)

- **Decisión:** este registro documenta el gate local que existía antes de la
  verificación externa. Exigía código, rama, PR y CI verdes, pero mantenía
  E1-11 parcial mientras GCP, Supabase y R2 no hubieran sido observados.
- **Estado actual:** la verificación externa ya se ejecutó. D-030 define la
  separación candidate/final y el manifest externo que sustituyen ese gate
  histórico para el cierre vigente.
- **Razón histórica:** IaC válida, adapters y fakes no demostraban IAM, Auth,
  RLS, CORS, lifecycle, red ni durabilidad de un Cloud Run Job real.
- **Relación:** E1-11 y restricción explícita de alcance.

## D-020 - Cloud Build usa identidad dedicada también para el source staging

- **Decisión:** Terraform habilita Cloud Storage y concede a la cuenta dedicada
  de Cloud Build `roles/storage.bucketViewer` y `roles/storage.objectUser`,
  además de permisos de escritura en Artifact Registry y Logging. No recibe
  `roles/run.admin` ni permiso para actuar como las identidades web/worker.
- **Razón:** un `gcloud builds submit` o trigger con cuenta indicada necesita
  acceder al staging de código; validar solo el push de la imagen dejaba el
  primer build expuesto a fallar antes de ejecutar el Dockerfile.
- **Relación:** E1-11, D-016 y principio de mínimo privilegio dentro del proyecto
  experimental dedicado.

## D-021 - Cloud Run no reintenta una ejecución sin identidad de job

- **Decisión:** el Job de Etapa 1 usa `task_count = 1`, `parallelism = 1` y
  `max_retries = 0`. Cada proceso llama una sola vez a `claim_next_job` y deja
  cualquier fallo como estado durable `FAILED` en PostgreSQL.
- **Razón:** como el dispatch deliberadamente no transmite `job_id`, un retry
  automático podría reclamar otra fila `QUEUED` y presentarla falsamente como
  retry de la primera. El retry funcional general pertenece a Etapa 2.
- **Relación:** E1-06/E1-07/E1-11, D-006 y D-013.

## D-022 - Terraform es el único propietario de la imagen desplegada

- **Decisión:** Cloud Build construye, prueba y publica una imagen, obtiene su
  digest y emite una referencia `@sha256`. No ejecuta `gcloud run ... update`.
  Una persona copia la referencia a un `tfvars` fuera del repositorio, revisa
  el plan y aplica Terraform, que configura la misma imagen en Service y Job.
- **Razón:** dos escritores sobre la imagen causaban drift y podían hacer que un
  plan posterior restaurara una versión antigua.
- **Relación:** E1-11 y D-020.

## D-023 - Cloud falla cerrado y separa liveness de readiness

- **Decisión:** cloud exige una URL completa `postgresql+psycopg://`, adapters
  Supabase/R2/Cloud Run, secreto de sesión gestionado, gateway mock y P10
  deshabilitado. `/api/health` no toca dependencias; `/api/readiness` ejecuta
  una consulta fija contra la tabla final esperada de la migración. Upload y
  download usan TTL separados y acotados.
- **Razón:** una configuración parcial no debe iniciar silenciosamente con
  SQLite ni provocar reinicios por una dependencia externa caída; un TTL
  declarado debe afectar realmente la capacidad correspondiente.
- **Relación:** E1-01/E1-03/E1-06/E1-11 y ADR-032/034.

## D-024 - PrincipalId se aplica por semántica, no por forma global

- **Decisión:** los campos que representan actores externos, usuarios Supabase,
  servicios o sistema usan PrincipalId; los IDs internos de dominio conservan
  Id. Los roots futuros pueden corregirse estructuralmente sin activar sus
  endpoints.
- **Razón:** un UUID Supabase válido no debe ser rechazado por el patrón de un
  identificador interno, pero ampliar Id globalmente debilitaría contratos no
  relacionados.
- **Relación:** AUD-P1-11, modelos canónicos y ADR-028.

## D-025 - OpenAPI usa DTOs de transporte que componen contratos canónicos

- **Decisión:** requests y responses de Etapa 1 usan DTOs Pydantic estrictos
  que importan modelos/enums canónicos. El snapshot OpenAPI normalizado y el
  cliente TypeScript generado se rechazan por drift en tests y CI.
- **Razón:** la wire shape necesita distinguir campos client-owned y
  server-owned sin copiar ni redefinir roots canónicos.
- **Relación:** AUD-P1-10 y F-017 a F-019.

## D-026 - Evidence-first es un receipt durable por fragmento

- **Decisión:** una versión de Assessment solo puede aprobarse cuando cada
  fragmento requerido tiene un receipt server-side tenant-, actor- y
  version-scoped que confirma carga y resolución exacta del locator. Un click
  React no es evidencia.
- **Razón:** cargar/resolver una fuente es verificable; afirmar comprensión
  cognitiva del humano no lo es.
- **Relación:** AUD-P1-08, F-014 y ADR-005/008.

## D-027 - Rollouts SPA separan documentos, assets y cache histórica

- **Decisión:** index y fallbacks HTML usan no-store; assets con hash son
  inmutables. El cliente actual envía un epoch en todas las llamadas API. Un
  GET de sesión desde un shell anterior recibe Clear-Site-Data limitado a
  cache; cookies y storage de autenticación no se borran.
- **Razón:** no-store protege respuestas nuevas, pero no puede retirar por sí
  solo una respuesta almacenada antes de esa política. El epoch ofrece
  autorrecuperación acotada y verificable.
- **Relación:** AUD-P1-03 y E1-11.

## D-028 - GitHub dispara builds; Terraform conserva ownership del runtime

- **Decisión:** una conexión Cloud Build v2 limitada al repositorio y un trigger
  regional de push construyen la rama autorizada con cuenta dedicada. Cloud
  Build prueba y publica; Terraform recibe el digest y es el único que modifica
  Service y Job.
- **Razón:** evita doble escritor, despliegue de código no revisado y permisos
  Run Admin en la identidad de build.
- **Relación:** AUD-P1-01/02, D-020/D-022 y E1-11.

## D-029 - Supply chain reproducible en el boundary práctico de E1

- **Decisión:** bases Docker se fijan por digest, Python por requirements con
  hashes, npm por lockfile/ci y Actions por commit SHA. Cloud Build exige
  provenance verificada; scan y SBOM se ligan al digest.
- **Razón:** permite reconstruir source a runtime y detectar vulnerabilidades
  sin afirmar reproducibilidad bit a bit entre arquitecturas o servicios
  administrados.
- **Relación:** AUD-P2-12 y Plan E1-11.

## D-030 - Candidate y final se separan para evitar autorreferencia falsa

- **Decisión:** el candidato funcional recibe regresión completa, CI, build,
  deployment y verificación cloud. El último commit solo cierra documentación y
  se denomina FINAL_STAGE1_SHA. Su build, digest, runtime y auditoría se guardan
  fuera del repositorio; no existe commit posterior para insertar esos valores.
- **Razón:** el hash de un commit depende de su contenido y los outputs externos
  solo existen después de publicarlo. Es imposible incluir honestamente el hash
  final dentro del propio commit.
- **Relación:** estrategia de candidate/final y procedencia del prompt de cierre.

## D-031 - Verificación de ingeniería y revisión académica son gates distintos

- **Decisión:** agentes de IA, tests y evidencia realizan el cierre técnico. La
  aprobación humana del blueprint y del Assessment permanece como garantía
  académica del producto. No se exige revisión humana de código.
- **Razón:** evita confundir una decisión docente sobre el constructo con un
  proceso de ingeniería no requerido.
- **Relación:** decisión cerrada 5.3 del propietario y ADR-001/034.

## D-032 - Deuda residual no puede degradar un P1

- **Decisión:** solo se acepta deuda P2/P3 con fuente, riesgo residual y
  justificación de no bloqueo. P1 permanece en cero. El backlog final contiene
  copy legal pendiente de autoridad, recuperación visual de exports, limpieza
  de documentación histórica E2 y una deprecación de tests.
- **Razón:** conservar explícitamente deuda menor es más seguro que inventar
  política legal, expandir Etapa 1 o alterar dependencias sin necesidad.
- **Relación:** STAGE1_FINAL_REMEDIATION_BACKLOG.

## D-033 - Replay de capacidades exige la autorización vigente

- **Decisión:** todos los descriptores idempotentes conservan un snapshot
  mínimo de autorización (`principal_id`, rol y permiso de aprobación). Antes
  de resolver un objeto o firmar otra URL, el replay compara exactamente ese
  snapshot con la membresía actual. Un actor distinto del mismo workspace o un
  downgrade del actor original falla cerrado. Evidence verify persiste solo el
  receipt y los IDs/hash necesarios para volver a resolver; nunca guarda URL,
  expiración, object key ni texto normalizado.
- **Razón:** la unicidad `(tenant,key)` por sí sola permitiría que otro
  principal reutilizara una clave conocida y recibiera una capability fresca,
  o que un actor degradado conservara privilegios de una respuesta anterior.
- **Relación:** AUD-P1-08, D-008 y E1-03/E1-08.

## D-034 - Response model debe validar la respuesta runtime

- **Decisión:** las rutas tipadas de Activity, Blueprint y readiness retornan
  DTOs Pydantic. El objeto `Response` inyectado se usa solo para ETag o status;
  no se retorna una `JSONResponse` preconstruida que salte el response_model.
  Los provider tests sustituyen outputs por payloads inválidos y exigen fallo
  500 ProblemDetail en lugar de publicar drift.
- **Razón:** declarar un schema OpenAPI no demuestra que FastAPI filtre o
  valide el body cuando el handler devuelve directamente una subclase de
  `Response`.
- **Relación:** AUD-P1-10, D-025 y F-017/F-018/F-019.

## D-035 - La higiene de idempotencia es un invariante de aplicación y base

- **Decisión:** una migración ordenada elimina reservas legacy representadas
  como JSON `null` y cualquier descriptor que contenga claves de URL,
  capabilities locales, parámetros X-Amz o URLs con credenciales. PostgreSQL
  impone después `ck_idempotency_keys_safe_response`: una respuesta completada
  debe ser un objeto JSON seguro; SQL NULL queda reservado a la petición en
  curso. Readiness cloud exige que ese constraint exista y esté validado.
- **Razón:** corregir el escritor evita nuevos casos pero no sanea datos
  históricos ni protege frente a otro escritor o despliegue incompleto. El
  constraint hace durable la garantía y readiness impide servir con esquema
  anterior al código.
- **Relación:** AUD-P1-08, D-008, D-033 y E1-03/E1-08/E1-11.

## D-036 - Bundle contractual 1.2 compatible con raíces 1.1

- **Decisión:** el bundle generado avanza a `1.2.0` y añade siete raíces E2:
  `StageRun`, `JobControlRecord`, `CoverageReport`, `ExportRecord`,
  `ExperimentMetrics`, `FeedbackEvent` y `QuestionReviewActionRecord`. Las 46
  raíces y 112 definiciones heredadas conservan estructura 1.1 y siguen
  aceptando fixtures explícitos 1.1.
- **Razón:** E2 requiere tipos e invariantes nuevos sin invalidar persistencia,
  fixtures ni consumidores E1.
- **Relación:** E2-03 a E2-09, E2-14 y autoridad canónica Pydantic.

## D-037 - Retry, cancel y resume son control durable de aplicación

- **Decisión:** una continuación crea un Job nuevo ligado a un
  `JobControlRecord`; una fuente/attempt solo puede consumirse una vez. La
  elegibilidad depende de clase y `retryable`, el resume reutiliza únicamente
  `StageRun` con hashes/versiones coincidentes y los jobs RUNNING poseen lease
  reconciliable. Cloud Run conserva `max_retries=0`.
- **Razón:** evita fan-out, denial-of-wallet, efectos duplicados y jobs
  huérfanos; un error de dispatch ambiguo no puede sobrescribir un terminal ya
  confirmado.
- **Relación:** E2-03, E2-04 y ADR-032.

## D-038 - Acciones y aprobación cierran en transacciones atómicas

- **Decisión:** las acciones de pregunta preparan antes del provider un
  descriptor durable content-free, y el terminal Job + action record se
  confirma en una transacción. EDIT conserva su snapshot protegido por hash.
  La aprobación individual confirma versión, proyección de submission y audit
  atómicamente. Bulk usa versiones exactas y partición aprobados/excluidos.
- **Razón:** permite retry tras crash/lease sin perder el intento lógico ni
  dejar un Assessment aprobado con estado de submission divergente.
- **Relación:** E2-04, E2-05 y E2-14.

## D-039 - Parser hostil se aísla y los datos reales continúan bloqueados

- **Decisión:** TXT/Markdown/PDF/DOCX se parsean en subproceso no-root con
  libmagic, seccomp que deniega red, límites de CPU/memoria/ficheros/procesos,
  timeout con kill del grupo, output acotado y sobre de resultado ligado al
  request por hashes e identidad. ClamAV no se despliega en E2.
- **Razón:** la librería parser no debe compartir red o secretos del proceso
  web/worker. Para el piloto sintético, el aislamiento es compensatorio; no se
  atribuye capacidad antivirus inexistente.
- **Relación:** E2-02, E2-10, ADR-032 y `docs/PARSER_SECURITY_E2.md`.

## D-040 - Recovery E2 es fail-closed y no un rollback rutinario

- **Decisión:** la recovery a E1 adquiere locks sobre toda tabla E2 antes de
  comprobar hechos, bloquea writers concurrentes y aborta ante cualquier dato
  o metadata E2 que se perdería. El rollback normal restaura un digest E2
  conocido sin revertir schema.
- **Razón:** un guard que consulta y luego elimina sin quiesce puede perder un
  commit concurrente aunque ambas transacciones hayan sido exitosas.
- **Relación:** E2-01, E2-03, E2-11 y migración 003.

## D-041 - Roles E2 separan propuesta de aprobación

- **Decisión:** OWNER/TEACHER y ASSISTANT pueden cargar submissions, ejecutar y
  proponer acciones de revisión. Aprobar blueprint o Assessment exige
  `can_approve_assessments`; bulk también admite ASSISTANT únicamente con ese
  permiso expreso. Fuentes de actividad continúan restringidas a docentes.
- **Razón:** materializa el subconjunto canónico del ayudante sin inferir
  capacidad académica por el nombre del rol.
- **Relación:** E2-01, E2-04 y E2-14.

## D-042 - Cloud candidate usa mock y Terraform es el único writer

- **Decisión:** CI y Cloud Build prueban con `CVA_MODEL_MODE=mock` y P10
  apagado. Cloud Build publica una etiqueta solo después de gates; el digest se
  resuelve y Terraform aplica un plan guardado que bloquea target, delete,
  replace, IAM, secretos inline, modelo real y P10 inesperados.
- **Razón:** separar build de deployment conserva procedencia e impide que una
  etiqueta mutable o un trigger altere Service/Job fuera del estado.
- **Relación:** E2-11 y runbook `deploy/README.md`.

## D-043 - Fault injection cloud se etiqueta como seed administrativo

- **Decisión:** el recorrido cloud puede insertar estados sintéticos
  deterministas para insuficiencia y para jobs TRANSIENT, RUNNING y
  PRECONDITION exclusivamente mediante el harness temporal autorizado. Esa
  evidencia se clasifica `CLOUD_REAL + CONTROLLED_ADMIN_SEED`: acredita schema,
  persistencia, autorización, idempotencia, cancelación y lineage en el runtime
  real, pero no simula ni reclama un fallo natural de proveedor.
- **Razón:** no existe un endpoint público para fabricar esos estados y no debe
  añadirse uno al producto. La separación evita presentar fault injection como
  calidad semántica o disponibilidad real del proveedor.
- **Relación:** E2-03, pasos 12 y 33–36 del recorrido obligatorio y
  `docs/audits/STAGE2_EVIDENCE_MANIFEST.md`.

## D-044 - El cierre externo acredita solo artefactos observados

- **Decisión:** `STAGE2_RUNTIME_SHA`, el candidato runtime
  `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` se acredita mediante dos runs CI
  verdes, Cloud Build SUCCESS/VERIFIED, digest inmutable, provenance SLSA 3 v1,
  scan finalizado, apply Terraform revisado, doble no-drift y E2E cloud 38/38.
  No se reclama SBOM porque no se observó uno ligado a este digest. Los usuarios
  Auth efímeros se eliminan al cerrar; los hechos sintéticos DB/R2 permanecen
  como evidencia gobernada. El commit documental posterior tiene otra
  identidad y su propia CI; no se presenta como el runtime ya desplegado.
- **Razón:** una afirmación de supply chain, limpieza o ejecución debe estar
  ligada a evidencia real del mismo candidato; un artifact histórico o una
  intención documental no la sustituye.
- **Relación:** E2-11, E2-10, D-032, D-042 y auditorías finales E2.

## D-045 - El proveedor OpenAI queda detrás de dos gates humanos

- **Decisión:** el adapter real puede implementarse y probarse offline desde el
  merge E2 verificado, pero ninguna llamada se ejecuta sin proyecto dedicado,
  billing/límites, clave privada y aprobación humana. El smoke requiere además
  dos confirmaciones técnicas independientes y presupuesto preflight. P11 queda
  fijado a `gpt-5.6-luna` con `reasoning_effort=low`; P10 continúa ausente del
  router. El Service web no recibe la clave y el worker desactiva los retries
  internos del SDK.
- **Razón:** separar implementación, credenciales y gasto hace auditable el
  primer costo y evita que CI, deploy o un fallback inesperado activen modelos
  reales. `store=false` se usa sin reclamar ZDR.
- **Relación:** ADR-035, `OPENAI_PROVIDER_SETUP.md`,
  `OPENAI_REAL_MODEL_VALIDATION.md` y `OPENAI_COST_BUDGETS.md`.

## D-046 - `LUNA_BASELINE_V1` separa routing de prompt y contrato

- **Decisión:** la primera evaluación real usa Luna en P01-P09/P11 con los
  esfuerzos autorizados (`medium`, `high`, `low`) y ninguna ruta P10, Sol,
  fallback o selección heurística. El perfil se identifica en `route_id`,
  reason codes y metadata de eval. La matriz mixta anterior queda documentada
  únicamente como comparación futura no callable.
- **Razón:** evaluar primero la alternativa de menor costo, manteniendo iguales
  los esfuerzos, permite medir si Luna es suficiente sin convertir la hipótesis
  en una decisión permanente de producto. Como no cambian instrucciones ni
  roots Pydantic, `prompt-pack/1.1.1` y contratos conservan su versión.
- **Relación:** ADR-036 y autorización humana del 2026-08-08.

## D-047 - P01 1.1.2 separa extracción usable de diagnóstico

- **Decisión:** una consigna sintética suficiente y fiel produce `READY` aun
  cuando alguna lista sourced no sea necesaria. Todo status distinto de
  `READY` vacía conjuntamente las cinco listas sourced y conserva únicamente
  el diagnóstico estructurado. El fixture de inyección se hace
  inequívocamente suficiente, exige `READY` y trata el marcador hostil sólo
  como dato no propagable. Prompt e input quedan ligados a hashes nuevos y la
  evidencia real 1.1.1 no se reutiliza para aceptar 1.1.2.
- **Razón:** un output parcialmente extraído con status de abstención mezcla
  dos contratos operativos incompatibles, mientras que reutilizar evidencia
  de otra frontera ocultaría precisamente la regresión remediada.
- **Relación:** P01, `REAL_MODEL_EVALS.md` y
  `OPENAI_REAL_MODEL_VALIDATION.md`.

## D-048 - La revisión P05 interactiva se ejecuta como job durable

- **Decisión:** editar un blueprint valida el patch y persiste atómicamente un
  Job `BLUEPRINT_REVIEW` con descriptor sin datos estudiantiles ligado por
  hashes. Sólo el
  worker invoca P05, vuelve a comprobar lineage, política, fuentes y versión,
  y publica la nueva versión junto al terminal del job en una transacción.
  Cancel restaura el estado original y retry reconstruye el descriptor desde
  el ancestro. La API responde `202 JobEnvelope` y la UI espera éxito antes de
  recuperar la versión publicada.
- **Razón:** una llamada directa desde el proceso web eludía durabilidad,
  presupuesto, control de reintentos y la separación web/worker exigida para
  un proveedor real.
- **Relación:** P05, D-037, D-038, ADR-032 y
  `OPENAI_PROVIDER_SETUP.md`.

## D-049 - La decisión P01 y el gasto de qualification son gates distintos

- **Decisión:** `qualification-real` exige primero la aceptación humana de la
  remediación P01 1.1.2 y luego una approval billable independiente. La primera
  queda ligada a los hashes exactos del prompt y del input injection; cualquier
  drift, cap inválido o gate ausente bloquea antes de leer la clave o crear
  transporte. El reporte conserva sólo la disposición hash-bound y los hashes.
- **Razón:** aceptar pagar una observación no resuelve una decisión de
  constructo, y aceptar el constructo tampoco autoriza gasto. Codificar esa
  separación evita que una variable o un runbook ambiguo cierre ambos gates por
  accidente.
- **Relación:** D-045, D-047, P01, `REAL_MODEL_EVALS.md` y
  `OPENAI_PROVIDER_SETUP.md`.

## D-050 - La rotación termina sólo cuando la clave anterior es rechazada

- **Decisión:** crear y autenticar una credencial nueva no completa la rotación.
  Antes de la qualification debe observarse que OpenAI rechaza la clave
  histórica; sólo entonces se deshabilita su versión en Secret Manager. Un
  intento UI sin efecto o una respuesta administrativa `403` mantiene el gate
  cerrado, aunque la versión nueva esté `enabled` y vea el modelo autorizado.
  La evidencia ejecutable usa una sola consulta `models.list`, retries cero,
  clave sólo por stdin y PASS histórico exclusivamente ante 401; una
  incertidumbre de red nunca equivale a revocación.
- **Razón:** deshabilitar sólo la copia local no revoca una credencial todavía
  válida en el proveedor, y continuar con dos claves activas rompe la secuencia
  humana autorizada y la evidencia de contención.
- **Relación:** D-045, D-049, `OPENAI_PROVIDER_SETUP.md` y
  `REAL_MODEL_EVALS.md`.

## D-051 - El PASS real P01 cierra P0 y el primer fallo P02 detiene el gate

- **Decisión:** la qualification 1.1.2 conserva su evidencia aunque termine en
  FAIL agregado. El PASS del primer caso `oa-p01-injection-md`, ligado a hashes
  aceptados y con inyección no propagada, satisface el criterio humano para
  cerrar P0. El fallo contextual del caso 11 `oa-p02-happy-pdf` se clasifica P1
  y detiene la secuencia; no autoriza repetición, resume, P11 ni otro gasto.
- **Razón:** descartar diez PASS por un fallo posterior perdería evidencia
  observada, mientras continuar tras un blocker violaría el stop fail-closed.
  Cerrar P01 no convierte un gate parcial en qualification completa.
- **Relación:** D-047, D-049, P01/P02, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-052 - P02 1.1.3 alinea la abstención sin invalidar P01 1.1.2

- **Decisión:** `prompt-pack/1.1.3` mantiene P01 y todas las entradas no
  modificadas en versión individual 1.1.2; sólo P02 avanza a 1.1.3. P02 copia
  `activity_id`, usa únicamente evidencia de rúbrica y hace explícito que todo
  status no `READY` lleva `criteria=[]` más diagnóstico. El gateway conserva
  subtipos contextuales content-free. Contratos, schema, ruta, fixture y
  expected outcome no cambian.
- **Gate:** una recanary real P02 requiere aceptación normativa hash-bound y
  aprobación billable nuevas. La approval 1.1.2 consumida no sirve para 1.1.3;
  ausencia de cualquiera de los gates bloquea antes de leer la credencial.
- **Razón:** el prompt ejecutable omitía una regla que la especificación y el
  validator ya exigían. Versionar sólo la entrada afectada conserva la prueba
  real P01 exacta y evita presentar la corrección propuesta como aceptada o
  observada antes del gate humano.
- **Relación:** D-047, D-049, D-051, P02,
  `specification/01_Prompt_Pack_v1.1(1).md` y `REAL_MODEL_EVALS.md`.

## D-053 - La continuación reutiliza sólo evidencia real hash-bound

- **Decisión:** el PASS de la única recanary P02 1.1.3 cierra P1. La
  qualification posterior no repite los diez PASS 1.1.2 ni P02: conserva esos
  once casos como evidencia real reutilizada sólo mientras coincidan
  `prompt_id`, versión, prompt hash, input bundle hash, expected outcome,
  behavior y severidad. La secuencia billable queda reducida a los siete casos
  no observados, con máximo defensivo ocho requests y cap propuesto USD 0.16.
- **Gate:** la continuación usa una approval nueva y específica. La approval
  1.1.2, la recanary P02 consumida y el nombre anterior de qualification 1.1.3
  no conceden gasto ni acceso a la credencial. Cualquier drift bloquea antes de
  esos gates.
- **Razón:** repetir evidencia suficiente añade costo y exposición sin probar
  una frontera nueva; reutilizarla sin fijar también el manifest permitiría
  cambiar silenciosamente el criterio de PASS.
- **Relación:** D-049, D-051, D-052, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-054 - P05 1.1.4 explicita el estado del review y P11 no adivina invariantes raíz

- **Decisión observada:** la única continuación 1.1.3 autorizada consumió
  cuatro Responses requests y se detuvo en P05. P03/P04 pasaron; P05 cumplió
  el schema provider pero falló Pydantic con `value_error` en `/`; la única
  P11 produjo un target todavía inválido. P06/P08/P09/P11 directo no se
  ejecutaron. El gate queda consumido y un opt-in histórico no puede reabrirlo.
- **Remediación:** `prompt-pack/1.1.4` mantiene el contrato canónico y avanza
  sólo P05/P11. P05 define `status` como finalización del review: una revisión
  completada usa `READY` y recomendación; critical FAIL exige
  `READY`+`REJECT`; una abstención usa recomendación nula y ningún critical
  FAIL. P11 devuelve `UNREPAIRABLE` ante un `value_error` raíz ambiguo y no
  elige campos semánticos de `BlueprintReview`.
- **Gate:** observar P05 1.1.4 requiere aceptación normativa P05/P11 y una
  approval billable nuevas. La recanary queda hash-bound a una sola Responses
  request, P11 cero y cap máximo USD 0.03; la approval consumida 1.1.3 no se
  transfiere.
- **Razón:** el schema del proveedor no expresa `model_validator` entre
  campos. El prompt primario debe exponer la tabla canónica, mientras una
  reparación estructural no puede escoger silenciosamente una interpretación
  semántica para hacer válido el objeto.
- **Relación:** D-049, D-052, D-053, P05/P11,
  `specification/01_Prompt_Pack_v1.1(1).md` y `REAL_MODEL_EVALS.md`.

## D-055 - El PASS P05 1.1.4 cierra P1 y reduce la continuación a cuatro casos

- **Decisión observada:** la aceptación normativa y la única recanary P05
  v1.1.4 autorizada sobre `35ecaf8` quedaron consumidas. P05 terminó `READY` y
  pasó schema provider, Pydantic, contexto y expected outcome en una Responses
  request, sin P11/retries/P10/Sol/fallback. El costo calculado fue USD
  0.00936825 frente al cap USD 0.03. Esta evidencia cierra P1.
- **Reuso:** los PASS P03/P04 de la continuación v1.1.3 y P05 v1.1.4 se suman
  a los once casos ya fijados. Los catorce sólo son reutilizables mientras
  coincidan prompt, versión, prompt hash, input bundle hash, expected outcome,
  behavior y severidad.
- **Gate siguiente:** la continuación v1.1.4 programa sólo P06/P08/P09/P11,
  máximo defensivo cinco Responses requests, P11 máximo uno, stop al primer
  fallo, retries/P10/Sol/fallback cero y cap propuesto USD 0.10. Exige una
  approval v1.1.4 distinta; ninguna approval consumida se transfiere.
- **Razón:** evitar recomprar evidencia real inmutable reduce costo y superficie
  de exposición, mientras el nuevo nombre de gate impide que una autorización
  histórica abra una frontera de prompt distinta.
- **Relación:** D-049, D-053, D-054, P05/P11, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-056 - El presupuesto preventivo reserva cache-write y el perfil manual no reintenta transportes

- **Hallazgo y cierre:** la auditoría offline previa a deploy encontró que la
  autorización del gateway tasaba el input como ordinario antes de Responses,
  aunque las canaries observaron casi todo el input como cache-write a 1.25×.
  El ledger posterior sí registraba esa categoría, pero una request podía
  exceder el remanente autorizado antes de quedar persistida. Se clasificó P1
  de control de gasto y se cerró antes de cualquier nueva request o deploy.
- **Decisión:** todo input estimado se reserva preventivamente como
  cache-write y el output al máximo del prompt. El perfil inicial de evaluación
  manual usa cero retries automáticos de gateway y SDK; un retry durable exige
  una acción humana explícita. P11 conserva una oportunidad por output inválido
  y limita su input a 80,000 tokens: cubre la reserva calificada máxima de
  76,482 y cualquier exceso bloquea antes de transporte.
- **Evidencia offline:** la ruta real con transporte fake recorrió P01-P09 sobre
  los fixtures sintéticos de cache con nueve tareas semánticas, jobs de actividad
  y submission `SUCCEEDED`, máximo observado de input preflight 27,330 y cero
  red/billable. Para una pregunta y tres reservas, los ceilings agregados son
  USD 0.253571 por actividad y USD 0.490573 por submission, dentro de USD 0.55
  por job. La qualification v1.1.4 permanece 4/4 fake y USD 0.092706.
- **Gate:** esta remediación no autoriza la continuación v1.1.4, build cloud,
  IAM, Terraform apply, deploy ni E2E facturable. Esas acciones deben fijar el
  SHA nuevo y conservar sus caps humanos separados.
- **Relación:** D-045, D-048, D-053, D-055, ADR-035/036,
  `OPENAI_COST_BUDGETS.md` y `OPENAI_REAL_MODEL_VALIDATION.md`.

## D-057 - P09 1.1.5 explicita relaciones por pregunta y recibe un gate aislado

- **Decisión observada:** la única continuación v1.1.4 autorizada sobre
  `abca7c5` ejecutó P06/P08 PASS y se detuvo en P09. P09 pasó schema provider y
  Pydantic, pero falló contexto; P11 directo no se ejecutó. Fueron tres
  Responses requests, USD 0.00864505 calculados y cero retries/P10/P11/Sol/
  fallback. La approval quedó consumida y P06/P08 elevan la evidencia
  hash-bound a 16/18.
- **Límite epistemológico:** el output no se retuvo. El código histórico
  `CONTEXT_INVARIANT_FAILED` no identifica cuál relación falló; no se atribuye
  una causa de campo concreta a partir de una inferencia.
- **Remediación:** `prompt-pack/1.1.5` avanza sólo P09. Ordena copiar
  literalmente `guide_id`, `assessment_id` y `submission_id`; cubrir
  exactamente las preguntas; limitar evidencia y fuentes a cada pregunta; y
  usar `source_ids=[]` en contexto cerrado. El gateway mantiene validación
  contextual separada y añade siete códigos content-free. Contratos, schema,
  ruta, fixture y expected outcome no cambian.
- **Gate:** la recanary candidata contiene sólo `oa-p09-happy-docx`, máximo una
  Responses request, P11/P10/Sol/fallback/retries cero, ceiling
  full-cache-write USD 0.01592350 y cap propuesto USD 0.02. Requiere aceptación
  normativa y approval facturable nuevas fijadas al SHA candidato. Ninguna
  approval o remanente anterior se transfiere. P11 directo queda para un gate
  posterior separado.
- **Evidencia offline:** el dry-run termina `READY`, pasa schema/Pydantic/
  contexto/outcome, verifica IDs raíz, cobertura y referencias por pregunta,
  y usa una request fake con cero red/billable. La frontera prompt/input es
  `sha256:8d29a13a5ee56b39f6aa5545b602e23ca28b6d60d051852d75ecbc0c664179ff`
  / `sha256:d85b124990e457e096fbe4851633ee057b662efcbda3ac84837e8c8a78deacc7`.
- **Relación:** D-049, D-053, D-055, D-056, P09,
  `OPENAI_COST_BUDGETS.md` y `OPENAI_REAL_MODEL_VALIDATION.md`.

## D-058 - El PASS P09 cierra P1 y P11 directo recibe el último gate de corpus

- **Decisión observada:** la remediación normativa y la única recanary P09
  v1.1.5 autorizada sobre `2ae0a0a` quedaron consumidas. P09 terminó `READY` y
  pasó schema provider, Pydantic, contexto y expected outcome en una Responses
  request, sin retries/P10/P11/Sol/fallback. El costo calculado fue USD
  0.00443985 frente al cap USD 0.02. Esta evidencia cierra el P1 y lleva la
  cobertura real hash-bound a 17/18.
- **Antirrepetición:** los valores históricos no reabren la recanary; el
  entrypoint devuelve `OPENAI_P09_V115_RECANARY_ALREADY_CONSUMED` antes del
  adapter. Sólo se conservan usage, latencia y hashes content-free.
- **Gate siguiente:** P11 directo v1.1.4 se aísla en `oa-p11-happy`, Luna-low,
  máximo una Responses request, P11 exactamente uno, retries/P10/Sol/fallback
  cero, ceiling full-cache-write USD 0.01172550 y cap propuesto USD 0.02. Antes
  del gate se recomputan las 17 fronteras reales anteriores.
- **Evidencia offline:** el transporte fake termina `REPAIRED`, valida wrapper
  y modelo objetivo, conserva `target_schema_name` y demuestra que la salida
  equivale exactamente a eliminar el campo estructural extra. También acepta
  sólo una abstención `UNREPAIRABLE` diagnóstica y sin `repaired_output`. Usa
  una request fake y cero red/billable.
- **Límites:** este checkpoint no autoriza P11 real, build, IAM, Terraform
  apply, deploy, E2E, datos reales ni main. Cada superficie conserva un gate
  independiente fijado a SHA/digest y presupuesto.
- **Relación:** D-049, D-054, D-056, D-057, P09/P11,
  `REAL_MODEL_EVALS.md` y `OPENAI_COST_BUDGETS.md`.

## D-059 - P11 directo completa 18/18 y separa qualification de deploy/E2E

- **Decisión observada:** la única canary P11 directa v1.1.4 autorizada sobre
  `976aadc` terminó `REPAIRED` y pasó schema provider, Pydantic, contexto y
  expected outcome. Conservó el target e hizo exactamente la eliminación
  estructural mínima. Consumió una Responses request y USD 0.00070015, con
  P11 uno y retries/P10/Sol/fallback cero.
- **Antirrepetición:** `P11_V114_DIRECT_CONSUMED=True` bloquea cualquier nuevo
  intento con `OPENAI_P11_V114_DIRECT_ALREADY_CONSUMED` antes de credencial y
  adapter. Se conservan usage, latencia y hashes content-free; no payload,
  output, clave ni request ID en claro.
- **Evidencia histórica:** las 17 fronteras anteriores se revalidaron antes de
  la llamada y el mapa hoy llamado `HISTORICAL_COMPLETE_REAL_EVIDENCE` fijó
  entonces los 18 casos real-eligible. D-065 registra los límites que dejaron
  de ser actuales tras cambios posteriores.
- **Separación de gates:** completar el corpus prueba qualification técnica del
  proveedor, pero no autoriza ni prueba el runtime cloud. Build/digest,
  IAM/Terraform deploy y E2E sintético real conservan autorizaciones separadas,
  fijadas al SHA/digest y a sus respectivos límites de mutación y gasto.
- **Relación:** D-054, D-056, D-058, P11, `REAL_MODEL_EVALS.md`,
  `OPENAI_COST_BUDGETS.md` y `OPENAI_REAL_MODEL_VALIDATION.md`.

## D-060 - El build manual fija explícitamente la identidad de mínimo privilegio

- **Incidente observado:** el único submit autorizado para `0a521d6` cargó el
  archivo fuente y falló antes de crear build ID porque Cloud Build seleccionó
  la cuenta de cómputo predeterminada, sin `storage.objects.get`. No hubo retry,
  digest, apply, cambio de runtime/IAM, job, E2E ni Responses request; el gate
  quedó consumido al primer fallo.
- **Causa:** el trigger Terraform ya fijaba `cva-cloudbuild`, pero el comando
  manual equivalente de `deploy/README.md` omitía `--service-account`. La CLI
  documenta que, sin ese flag, usa la identidad predeterminada.
- **Decisión:** todo submit manual obtiene `cloud_build_service_account` desde
  el estado Terraform, construye su resource name completo y lo pasa de forma
  obligatoria a la CLI. También fija 3600 segundos y rechaza un build ID vacío.
  No se amplían los permisos de la cuenta predeterminada.
- **Antirrepetición:** una regresión estática liga el runbook a la identidad,
  timeout y stop sin retry. Un submit fallido no se repite con el mismo gate;
  el siguiente build requiere una autorización exacta fijada al SHA remediado.
- **Relación:** D-059, `deploy/README.md`, `TEST_RESULTS.md` y principio de
  mínimo privilegio de ADR-033/ADR-034.

## D-061 - El gate Cloud Build declara los ejecutables requeridos por su suite

- **Incidente observado:** el build único `ccadfb3c-c645-4de4-879e-7dcaaa8cf8d8`
  sobre `b8142f5` usó correctamente `cva-cloudbuild`, pero terminó en el paso 0.
  Pytest registró 540 PASS, 16 skips y ocho fallos del harness porque la imagen
  Alpine no encontraba `make`. Los pasos posteriores no se ejecutaron y no se
  produjo imagen, digest, apply, cambio de runtime/IAM, job, E2E o Responses.
- **Causa:** los tests versionados invocan Make targets para probar gates
  consumidos y dry-runs, mientras `deploy/cloudbuild.yaml` sólo instalaba
  `git` y `libmagic`. CI y desarrollo tenían `make` preinstalado, por lo que no
  cubrían esa diferencia del contenedor Cloud Build.
- **Decisión:** el gate declara `git`, `libmagic` y `make` en una sola
  instalación explícita. Una regresión lee el YAML parseado y rechaza la
  omisión del comando exacto.
- **Evidencia:** el paso 0 completo se reprodujo desde un contexto fresco de
  211 archivos, con la misma imagen Python fijada por digest: contratos,
  fixtures y secretos PASS; 548/16 pytest; 11/11 deploy; 2/2 seguridad.
- **Gate:** esa reproducción cierra el defecto offline, pero no reabre el
  build consumido. Cualquier verificación cloud o apply requiere autorización
  nueva y exacta fijada al SHA remediado.
- **Relación:** D-059, D-060, `deploy/cloudbuild.yaml`, `TEST_RESULTS.md` y
  principio de gates herméticos de ADR-033/ADR-034.

## D-062 - Web mock y worker real se despliegan mediante un único plan sellado

- **Decisión observada:** el build único
  `613270cf-bdfb-4b18-a423-35f68198f471` del SHA `b4ec283…` terminó
  `SUCCESS/VERIFIED`. Su digest coincidió con Artifact Registry, conservó SLSA
  3 y fijó el SHA autorizado como label OCI.
- **Plan sellado:** antes de mutar cloud, el plan guardado y hash-verificado
  mostró únicamente dos updates in-place —Service y Job— y un create IAM para
  que sólo la cuenta worker lea `cva-openai-api-key`; 36 recursos quedaron
  no-op y no hubo delete/replace. El apply de ese plan se ejecutó exactamente
  una vez y terminó `1 added, 2 changed, 0 destroyed`.
- **Separación de funciones:** web conserva `CVA_MODEL_MODE=mock` y ninguna
  referencia a la clave. Worker usa modo real, versión 2 fijada, máximo USD
  0.55 por job, P10 false, task/paralelismo 1/1 y retries de infraestructura
  cero. Service y Job usan el mismo digest inmutable.
- **Verificación:** la revisión web está Ready, health/readiness son 200, la
  ruta privada anónima es 401, IAM contiene sólo al worker y dos planes
  consecutivos terminan `No changes`. El conteo de ejecuciones del Job no
  cambió y no hubo Responses.
- **Gate restante:** desplegar capacidad no autoriza usarla. El E2E sintético
  real conserva un gate humano billable independiente, limitado por ceiling
  USD 0.855444, cap propuesto USD 0.90, máximo 32 Responses, retries cero y
  stop al primer job no exitoso. Datos estudiantiles reales y P10 permanecen
  fuera de alcance.
- **Relación:** D-059, D-060, D-061, ADR-033/ADR-034,
  `IMPLEMENTATION_STATUS.md`, `TEST_RESULTS.md` y `OPENAI_COST_BUDGETS.md`.

## D-063 - Una ambigüedad P03 válida consume el gate y exige una decisión humana nueva

- **Observación:** el único job de actividad del primer E2E real ejecutó P01,
  P02 y P03 con Luna; las tres salidas fueron `SCHEMA_VALID`. P03 persistió un
  reporte `blocked=true` con seis issues, cuatro bloqueantes, y el job terminó
  `NEEDS_REVIEW`/`ASSIGNMENT_AMBIGUOUS`.
- **Decisión:** `NEEDS_REVIEW` no se reinterpretará como éxito aunque la task
  Cloud Run termine `EXECUTION_SUCCEEDED`. La cláusula `stop al primer ... job
  no SUCCEEDED` detiene el recorrido antes de cualquier decisión P03, P04/P05,
  submission o ejecución adicional.
- **Frontera consumida:** hubo una ejecución, intento 1, 3/32 Responses y USD
  0.01302445/0.90; P10/P11/Sol/fallback/retries fueron cero. El remanente de
  presupuesto no transfiere autoridad a una reanudación.
- **Continuación:** la UI `Guardar y reanudar blueprint` crea un nuevo job de
  actividad. Seleccionar interpretaciones y lanzar ese job requiere decisión
  docente y autorización nuevas, porque excede la frontera consumida de un
  único job de actividad.
- **Relación:** D-062, ADR-030/ADR-034, `REAL_MODEL_EVALS.md`,
  `OPENAI_COST_BUDGETS.md` y `TEST_RESULTS.md`.

## D-064 - P04 explicita invariantes no expresables y la evidencia perdida no se presume PASS

- **Observación de producto:** seis decisiones P03 recomendadas se
  persistieron y una sola reanudación reutilizó P01-P03. P04 v1.1.2 cumplió el
  schema estricto del proveedor, pero falló un `model_validator` raíz de
  `AssessmentBlueprint`; una P11 estructural no reparó el contrato destino.
  Job y task terminaron FAIL y no se continuó a P05.
- **Decisión normativa:** P04 v1.1.6 enumera las referencias allowlist y las
  relaciones entre IDs únicos, operación soportada, formatos permitidos,
  selección de justificación, decisiones exactas y campos de aprobación. Estas
  reglas ya existían en el contrato canónico, pero JSON Schema no puede
  expresar todas sus relaciones entre campos.
- **Evidencia fail-closed:** la primera observación P04 v1.1.6 consumió una
  request, pero su stdout quedó en una sesión de orquestación no archivada.
  Como `store=false` produjo cero logs recuperables, el resultado se declaró
  `INCONCLUSIVE`; no se infirió PASS ni se reabrió el gate original.
- **Recuperación separada:** la autorización amplia posterior se materializó
  como un gate distinto, fijado a los mismos hashes, una request, cap USD 0.03,
  P11/retries/P10/Sol/fallback cero y reporte durable precreado. Terminó PASS
  `READY` con schema/Pydantic/contexto/outcome PASS y USD 0.00537802. Ambos
  gates quedan permanentemente consumidos.
- **Alcance:** el PASS focal vuelve a cubrir 18/18 fronteras actuales, pero no
  cambia el digest desplegado ni sustituye build, plan Terraform o E2E de
  producto sobre P04 v1.1.6.
- **Relación:** D-053, D-054, D-056, D-063, ADR-005/ADR-034,
  `OPENAI_REAL_MODEL_VALIDATION.md` y `REAL_MODEL_EVALS.md`.

## D-065 - Las decisiones P03 viajan autocontenidas y P05 revisa un catálogo, no un plan

- **Observación de producto:** sobre el SHA `dfd102d…` y digest
  `sha256:9048f9da…`, el E2E nuevo ejecutó P01-P05 en dos Cloud Run
  executions. P04 produjo y persistió un blueprint `READY`, pero P05 devolvió
  `READY/REJECT` con fallos críticos de cobertura, catálogo y factibilidad. Se
  respetó el stop: no hubo edición, aprobación, submission ni tercera
  ejecución.
- **Causa normativa:** P05 interpretó `question_count=1` como obligación de que
  cada oportunidad cubriera todos los criterios y trató la diversidad entre
  oportunidades como falta de comparabilidad. Eso contradice ADR-030: el
  catálogo es independiente de N y el planificador selecciona después
  exactamente N. Además, `PolicyDecision` conservaba sólo un option ID opaco;
  P04/P05 no recibían la etiqueta y consecuencia elegidas por la persona.
- **Contrato:** `PolicyDecision.selected_option` conserva ahora el snapshot
  inmutable de `DecisionOption`. Las requests P04/P05 exigen decisiones
  autocontenidas; workflows nuevos las persisten y las filas históricas se
  rehidratan tenant-scoped desde su `AmbiguityReport` sin reescribir historia.
- **Prompts y validación:** P04 avanza a 1.1.7 y P05 a 1.1.5. Separan cobertura
  conceptual del catálogo, cobertura obligatoria por plan y factibilidad
  exacta-N; no inventan oportunidades compuestas ni penalizan diversidad
  válida. El gateway rechaza cobertura fuente incompleta y catálogos que no
  pueden formar N dentro del tiempo/calidad configurados.
- **Gate acoplado:** la recanary preparada ejecuta exactamente P04 y luego P05,
  usando el output P04 validado como input P05. El dry-run pasó con dos
  transportes fake, ceiling full-cache-write USD 0.04988775, cap USD 0.06,
  retries/P10/P11/Sol/fallback cero y stop al primer fallo. Una recanary P06
  separada, de una request y cap USD 0.03, cubre el nuevo lineage de decisiones.
- **Evidencia en ese checkpoint:** los hashes invalidados eran P04, P05 y P06;
  por tanto 15/18 observaciones seguían vigentes antes del gate real. El mapa
  de 18/18 de D-059/D-064 quedó explícitamente histórico.
- **Relación:** D-059, D-062, D-063, D-064, ADR-030/ADR-034,
  `OPENAI_REAL_MODEL_VALIDATION.md`, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-066 - Un timeout consumido exige remediación y recuperación nueva, no replay

- **Observación:** la recanary acoplada P04 1.1.7→P05 1.1.5 ejecutó
  exactamente dos Responses. P04 terminó PASS `READY` con schema provider,
  Pydantic, contexto y outcome PASS. P05 recibió ese output validado como
  input exacto y terminó `MODEL_TIMEOUT` a 120,016 ms, coincidente con el
  antiguo timeout del adapter de 120 s. No hubo retry, P10, P11, Sol o
  fallback; el charge conservador fue USD 0.05106550 bajo cap USD 0.06.
- **Consumo fail-closed:** la autorización original queda permanentemente
  consumida. Su reporte content-free está ligado al SHA-256
  `d0d27500adeee0b4b234a5ee65e3e642f9b85929cd689fc6f86beb87eee2de14`.
  P04 se promueve como frontera real 1.1.7 y la evidencia vigente sube a
  16/18; P05 y P06 permanecen pendientes.
- **Causa y remediación:** el fallo pertenece a la frontera temporal del
  transporte, no al contrato del modelo. El timeout SDK pasa a 240 s y el
  timeout exterior del gateway a 245 s, conservando retries automáticos cero
  y el límite validado de 5–300 s.
- **Recuperación:** `store=false` impide recuperar el contenido P04 y, por
  tanto, reconstruir la request P05 sólo desde hashes. Una P05 aislada no
  probaría acoplamiento. La única recuperación válida repite P04→P05 bajo
  opt-ins y constante de consumo distintos, máximo dos Responses, cap USD
  0.06 y stop al primer fallo. P06 sigue bloqueado hasta el PASS completo.
- **Relación:** D-053, D-064, D-065, ADR-005/ADR-034,
  `OPENAI_REAL_MODEL_VALIDATION.md`, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-067 - La recuperación acoplada promueve P05 sin retener contenido

- **Resultado:** el gate distinto P04 1.1.7→P05 1.1.5 con timeout SDK/gateway
  240/245 s terminó PASS/PASS `READY`. Las dos salidas pasaron schema del
  proveedor, Pydantic, contexto, outcome y controles semánticos de cadena. No
  hubo retry, P10, P11, Sol ni fallback.
- **Frontera:** consumió exactamente 2/2 Responses, USD 0.01645840 actual, USD
  0.04086520 de charge conservador y USD 0.05147825 de ceiling bajo cap USD
  0.06. El reporte content-free está ligado al SHA-256
  `3452b12bf89ea0cb59c29837b054d60db0ef46ceeb950802c680e20001a94df8` y
  el gate queda permanentemente consumido.
- **Evidencia:** P04 conserva su input reproducible y output validado
  `sha256:22dd21e3…`; P05 queda ligado al envelope dinámico
  `sha256:e8bd0e92…`. Como `store=false` no retiene el contenido del output
  P04, el mapa valida P05 como frontera provider-derived encadenada al límite
  P04 actual, sin inventar ni persistir contenido.
- **Alcance:** `CURRENT_REAL_EVIDENCE` sube a 17/18. P06 no se infiere desde
  este PASS: requiere su propia observación decision-lineage de una Responses,
  cap USD 0.03 y rutas laterales/retries cero. Su entrypoint real comprueba
  además, antes de approval, clave o transporte, que la recuperación esté
  consumida como PASS y que la frontera P05 1.1.5 siga presente e idéntica.
- **Relación:** D-065, D-066, ADR-005/ADR-030/ADR-034,
  `OPENAI_REAL_MODEL_VALIDATION.md`, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-068 - P06 decision-lineage completa la evidencia real vigente

- **Precondición:** el entrypoint real comprobó antes de approval, clave y
  transporte que la recuperación P04→P05 estaba consumida como PASS y que la
  frontera P05 1.1.5 seguía presente e idéntica en la evidencia vigente.
- **Resultado:** P06 1.1.2 terminó PASS `READY`; schema del proveedor,
  Pydantic, contexto, outcome y todos los controles de decision lineage
  pasaron. Consumió exactamente 1/1 Responses, 8,270 ms, USD 0.00148525 real,
  USD 0.01992085 de charge y USD 0.023361 de ceiling bajo cap USD 0.03, con
  retries/P10/P11/Sol/fallback cero.
- **Evidencia:** prompt/input quedaron ligados a `sha256:3fcde330…` y
  `sha256:3cabdfaa…`; el output content-free a `sha256:876c6be5…`; el reporte
  tiene SHA-256
  `5daf7774e0ffee1bbc6b9b834b09f2022a496cdf14daabed303467cd7087c5b3`.
  El gate queda permanentemente consumido.
- **Alcance:** `CURRENT_REAL_EVIDENCE` alcanza 18/18 sobre las fronteras
  actuales. Esto habilita el checkpoint de build/deploy, pero no sustituye la
  verificación Cloud Build/digest/Terraform ni el E2E fresco de producto.
- **Relación:** D-065, D-066, D-067, ADR-005/ADR-030/ADR-034,
  `OPENAI_REAL_MODEL_VALIDATION.md`, `REAL_MODEL_EVALS.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-069 - El candidato remediado queda fijado por build, digest y plan sellado

- **Fuente:** se construyó exactamente el SHA
  `88416b522414f316613bea96ad08687e8a335a38` mediante el único Cloud Build
  `441be72d-04ae-46e9-b150-6eec1032c8d6`, con cuenta dedicada, retries cero y
  resultado `SUCCESS/VERIFIED`.
- **Identidad de imagen:** Cloud Build y Artifact Registry coincidieron en
  `sha256:d31899535c76b08ee79163479530b044783b73956c6fe228a01a3e603008893d`.
  Artifact Analysis expone procedencia SLSA 3 firmada, Statement/predicate v1,
  invocation ligada al build y subject ligado al digest.
- **Mutación sellada:** el plan guardado de SHA-256
  `64b200559044ecb2e0a44ea68a63f7c174088c12da1209f6624b77f388c1670e`
  contenía sólo dos updates in-place de imagen para web y worker, 0 create, 0
  delete/replace y 0 cambios adicionales. Su único apply terminó 0/2/0; dos
  planes vivos posteriores terminaron exit 0 y `No changes`.
- **Separación efectiva:** web quedó Ready en mock y sin clave; worker Ready en
  real con secreto v2, USD 0.55, P10 false, 1/1 y `maxRetries=0`. Sólo la cuenta
  worker tiene `secretAccessor`; Service y Job usan el mismo digest.
- **No consumo implícito:** health/readiness y el 401 privado pasaron sin crear
  jobs, E2E o Responses. El deploy no sustituye el E2E fresco sintético con
  edición P05 durable y submission requerido para
  `OPENAI_REAL_MANUAL_EVAL_READY`.
- **Relación:** D-060, D-061, D-062, D-068, ADR-033/ADR-034,
  `IMPLEMENTATION_STATUS.md`, `TEST_RESULTS.md`, `OPENAI_PROVIDER_SETUP.md` y
  `OPENAI_REAL_MODEL_VALIDATION.md`.

## D-070 - P04 separa construcción terminada de aprobación humana posterior

- **Fuente:** el E2E fresco `act_a2d0acdf5d948c365ca8` produjo en P04 un
  catálogo utilizable, válido y ligado a seis decisiones, pero devolvió
  `NEEDS_REVIEW` sólo porque `approved_by/approved_at` seguían null. P05 y la
  aprobación humana ocurren después, por lo que esa condición creó un bucle
  imposible de resolver mediante resume.
- **Decisión normativa:** P04 1.1.8 interpreta `status` como finalización de la
  construcción. Un catálogo completo usa `READY` aunque tenga INFO/WARNING o
  aprobación posterior pendiente. `NEEDS_REVIEW/BLOCKED` requiere una decisión
  académica concreta que impida un catálogo utilizable y al menos un diagnóstico
  ERROR/CRITICAL. `HUMAN_REVIEW_PENDING` no se usa sólo para el gate posterior.
- **Cierre determinista:** el gateway añade
  `P04_NONREADY_WITHOUT_BLOCKING_DIAGNOSTIC`; una salida como la observada falla
  cerrada y no puede reutilizarse como stage run válido.
- **Evidencia y gate:** el cambio invalidó P04 y el P05 derivado, dejando 16/18
  fronteras durante la remediación. La recanary P04 1.1.8→P05 1.1.5 reproduce
  seis decisiones/outcomes vacíos/niveles ausentes y terminó PASS/PASS `READY`:
  2/2 Responses, USD 0.01433335 real, charge USD 0.04082695 y ceiling USD
  0.05127050 bajo cap USD 0.06, sin rutas laterales ni retries. El reporte
  content-free queda ligado a
  `173169216efb15a0ed797d7297d553c38196219bde60f689dd0ba2a694de8ada`; el gate
  está consumido y la evidencia vigente vuelve a 18/18.
- **Relación:** D-068, D-069, ADR-030/ADR-034, `REAL_MODEL_EVALS.md`,
  `OPENAI_REAL_MODEL_VALIDATION.md` y `OPENAI_COST_BUDGETS.md`.

## D-071 - El smoke del parser usa el mismo deadline acotado que producción

- **Fuente:** el único build del SHA `523b2100c4190a8d7db0a7034e85cbd0b86eec81`,
  `9e74ef7a-072b-4094-8dec-3368c0d6afa9`, pasó cuatro pasos completos y falló
  en el smoke final porque el parser aislado agotó 5 s durante el arranque frío
  del intérprete/libmagic.
- **Decisión:** el smoke conserva `require_isolation=True`, libmagic, imagen
  read-only, capabilities retiradas y `no-new-privileges`, pero usa 30 s: el
  mismo default productivo validado por `Settings`, aún bajo el máximo de 120 s
  y el límite CPU interno de 20 s. El deadline de 5 s no representaba runtime y
  convertía contención del builder en falso negativo.
- **Regresión:** la prueba de artefactos exige literalmente
  `timeout_seconds=30` y rechaza `timeout_seconds=5`; YAML, Terraform y las 11
  pruebas de deploy pasan localmente.
- **Consumo fail-closed:** el build fallido no se reintenta ni publica. No hubo
  tag/digest, plan, apply, job, E2E o Responses; Cloud Run conserva el digest
  anterior y el plan vivo terminó `No changes`. Cualquier build posterior debe
  pertenecer a un SHA nuevo después de CI verde.
- **Relación:** D-059, D-060, D-069, ADR-033/ADR-034, `deploy/cloudbuild.yaml`,
  `IMPLEMENTATION_STATUS.md` y `TEST_RESULTS.md`.

## D-072 - Los IDs diagnósticos conservan su tipo y una salida insegura no se normaliza

- **Observación:** el E2E del SHA `fefea94d25a974ddf05e71f7212616e625ee5303`
  pasó P01-P03 y persistió seis decisiones. P04 1.1.8 cumplió el schema del
  proveedor, pero colocó un ID de otra clase en
  `diagnostics[].evidence_ids`. El gateway lo rechazó con
  `CONTEXT_FAILURE_OUTPUT_EVIDENCE_ID_NOT_ALLOWLISTED`; job y execution
  terminaron `FAILED/SECURITY`, sin retry ni P05.
- **Decisión normativa:** P04 1.1.9 exige que `evidence_ids` contenga sólo IDs
  exactos ya presentes en `ActivitySpec`/`RubricSpec`, y que `source_ids`
  contenga sólo fuentes exactas autorizadas. IDs de statement, criterion,
  decision, issue u option nunca cambian de tipo para llenar esos campos; si
  no existe una referencia autorizada, la lista correcta es vacía.
- **Fallo cerrado:** el adaptador no elimina, reemplaza ni corrige referencias
  inválidas. La validación contextual sigue siendo una frontera de seguridad y
  conserva la razón content-free exacta en el ledger.
- **Gate:** el cambio invalida P04 y el P05 derivado, por lo que
  `CURRENT_REAL_EVIDENCE` baja deliberadamente a 16/18. La recanary acoplada
  reproduce la forma productiva, pasa dry-run con 2 fake Responses y ceiling
  USD 0.05046625/cap USD 0.06, y sólo una observación real nueva puede volver a
  promover ambas fronteras.
- **Relación:** D-065, D-068, D-070, ADR-005/ADR-030/ADR-034,
  `REAL_MODEL_EVALS.md`, `OPENAI_REAL_MODEL_VALIDATION.md` y
  `OPENAI_COST_BUDGETS.md`.

## D-073 - El proveedor eval-only exige Job/SA separados y autorización exacta post-claim

- **Autoridad única:** el Service web y el worker ordinario permanecen mock,
  sin clave y con P10 deshabilitado. Terraform puede aprovisionar un Cloud Run
  Job y una service account eval-only separados, pero no concede a la web
  permiso para invocarlo ni a la cuenta ordinaria permiso para leer OpenAI.
- **Orden de capacidades:** el worker eval-only crea primero sólo repositorio y
  object store, reclama el `job_id` exacto y consume en PostgreSQL una
  autorización append-only única. Esa autorización liga tenant, kind,
  aggregate, attempt, conjunto exacto de hashes sellados, SHA candidato,
  boundary ejecutable, Luna/ruta, versión numérica del secreto, expiración y
  caps. Sólo después puede resolver Secret Manager y construir el adapter
  request-capped. Cualquier ausencia, reuso o divergencia produce `SECURITY`
  con cero resolver, cero transporte y cero request.
- **Fixture P05:** el positivo deja de proceder del mock genérico. El golden
  versionado verifica un constructo causal concreto de invalidación de caché y
  documenta alineación y cinco razones semánticas inspeccionables. Un negativo
  separado cambia el catálogo a `CHOICE` contra una política `OPEN_SHORT` y
  debe resultar `REJECT/PLAN_FEASIBILITY` offline, sin request real.
- **Observabilidad:** P06 2.3.0 conserva subcódigos estables por cada relación
  fallida. P08 registra ACCEPT/REJECT/ESCALATE, criticality, categorías,
  hashes de códigos críticos y cada relación score/threshold; el runtime
  persiste sólo esa proyección content-free, no prompts ni outputs.
- **Gate experimental:** el harness final consume una autorización durable
  antes de resolver una versión numérica de Secret Manager, fija exactamente
  24 requests y conserva cero P10/P11/fallback/retries/tools/store. Esta
  decisión prepara una única matriz congelada; no autoriza una segunda matriz
  ni una mutación de prompts/validators ante fallo.
- **Relación:** ADR-035/ADR-036, `AGENTS.md`,
  `OPENAI_PROVIDER_SETUP.md`, `STAGE2_CONVERGENCE_HANDOFF.md` y migración
  `202608120005_stage2_synthetic_provider_gate.sql`.

## D-074 - La simplificación separa autoridad antes del cutover operativo

- **Objetivo:** actividad
  P01→P02→P03→P04→preflight determinista→aprobación docente; submission
  P06→planner→P07→validaciones deterministas→revisión/aprobación docente→P09.
  P05/P08 quedan inactivos en el objetivo y P10 continúa deshabilitado.
- **Autoridad:** backend decide identidad, versions/hashes, estado, lineage,
  pertenencia, allowlists, formatos, conteo, tiempo, restricciones,
  factibilidad, almacenamiento, transiciones y validación determinista. El
  modelo propone semántica, estructura pedagógica, relación evidencia/
  constructo, redacción, observables y alternativas. El docente resuelve
  ambigüedad y tiene autoridad académica final sobre blueprint y preguntas.
- **Causalidad:** los únicos estados de oracle nuevos son `VALID`,
  `ORACLE_SUSPECT`, `INVALID` y `NOT_APPLICABLE`. Un oracle sospechoso vuelve
  la evidencia inconclusa y prevalece sobre `MODEL_OWNED_*`; receipts con
  `UNESTABLISHED` sólo se leen por compatibilidad.
- **Historia/reporting:** el harness y las qualifications existentes no son un
  gate canónico de selección de modelo y se preservan. Sólo un reporte
  `SYNTHETIC_ONLY_NO_STUDENT_DATA` enumera códigos diagnósticos estructurados y
  su hash; no se extrae texto libre ni cambia la política de datos reales.
- **Frontera:** no se cambian routing, prompts ejecutables, workflows, jobs,
  persistencia, P04/P06/P07/P09 ni infraestructura. Retirar invocaciones y
  estados P05/P08, y mover P09 detrás de aprobación docente, requiere una fase
  posterior compatible.
- **Relación:** ADR-037, `PIPELINE_AUTHORITY.md`, `pipeline_authority.py` y
  `qualification_semantics.py`.

## D-075 - P04 propone semántica y el servidor compila el blueprint canónico

- **Frontera:** `P04_BLUEPRINT_BUILD_V1` conserva
  `AssessmentBlueprint` como output de etapa, pero el proveedor devuelve sólo
  `BlueprintModelDraft`. Sus aliases `D*`, `V*` y `T*` son locales a una
  inferencia y no pueden transportar IDs canónicos.
- **Autoridad del modelo:** dimensiones, relación con criterios/outcomes,
  variantes y requisitos de evidencia, operaciones soportadas, oportunidades,
  foco, observable, dificultad, tiempo, anchors, formatos, justificación,
  diversidad, comparabilidad y accesibilidad.
- **Autoridad del servidor:** un compilador determinista valida el grafo y las
  allowlists, rechaza duplicados evidentes/operaciones/formatos/límites
  inválidos, crea todos los IDs y copia identidad, policy, decisiones,
  aprobación y estado. `AssessmentBlueprint` no se reemplaza.
- **Factibilidad:** P04 ya no declara ni demuestra un plan exacto de \(N\).
  Después de compilar, el preflight/planner existente produce `READY` o un
  diagnóstico determinista con `correction_scope=P04_BLUEPRINT_BUILD` que
  permite una futura corrección localizada.
- **Catálogo y compatibilidad:** `BlueprintPolicy` añade defaults compatibles
  para `max_variants_per_dimension=6` y
  `max_templates_per_variant=12`. Son guardrails operacionales provisionales,
  configurables y server-owned; no límites pedagógicos universales.
- **Cache:** el draft provider sólo vive dentro de la llamada. El cache de
  etapa conserva exclusivamente `AssessmentBlueprint`, ligado a request,
  policy hash, provider-schema boundary y compiler boundary. En replay se
  recompila su proyección semántica y se exige igualdad canónica exacta. Los
  snapshots históricos siguen siendo legibles como `AssessmentBlueprint`,
  pero una frontera anterior no se reinterpreta ni comparte component key.
- **Evaluación:** no se llamó a ningún proveedor. La frontera hash-bound liga
  `provider-output-schema-boundary/1.0.0` y
  `blueprint-compiler-boundary/1.0.0`; los receipts históricos no se
  reescriben y siguen siendo evidencia no canónica conforme ADR-037.
- **Relación:** D-074, ADR-037 y `pipeline-authority/1.0.0`.

## D-076 - P05 queda retirado del runtime activo con recovery determinista

- **Flujo activo:** actividad ejecuta P01/P02 opcional/P03/P04, persiste un
  `BLUEPRINT_PREFLIGHT` determinista y entrega el `AssessmentBlueprint` a la
  decisión docente. No construye `BlueprintReviewRequest`, no invoca P05 y no
  consulta recommendation/checks/status P05.
- **Persistencia:** `blueprints.preflight` conserva el snapshot mecánico; la
  columna nullable `review` sigue legible como historia. Nuevas versiones
  activas escriben `review=NULL`. La migración 006 es aditiva y no borra
  contratos, prompts, routes, fixtures, reports ni receipts.
- **Edición/aprobación:** editar crea un job durable
  `BLUEPRINT_PREFLIGHT`, vuelve a ligar spec/rubric/policy/decisiones y publica
  PASS o FAIL. Aprobar recomputa el preflight, verifica snapshot cuando existe,
  ETag, versión, ownership y permiso docente; una review P05 histórica no es
  autoridad.
- **Recovery:** un job legacy `BLUEPRINT_REVIEW` queued/running/retry/resume
  conserva su descriptor, pero el worker lo reconcilia por preflight sin
  gateway. StageRun reuse, lease recovery, cancellation y transición final son
  tenant-scoped, hash-bound y fail-closed ante lineage o fuente divergente. Aun
  si el worker eval-only parte configurado como real, estos jobs usan un
  runtime provider-free: no consumen autorización, no resuelven clave y no
  construyen transporte; tampoco admiten una autorización real nueva.
- **Costo/observabilidad:** el presupuesto activo baja de 4/5 a 3/4 llamadas
  según exista rúbrica; P05 futuro es cero. StageRuns y auditoría exponen
  outcome PASS/FAIL, códigos deterministas y aprobación docente sin scores
  semánticos nuevos.
- **Historia:** el harness congelado conserva el hash archivado del runtime de
  su baseline y se declara no canónico; el workflow activo puede divergir por
  este cutover sin reescribir evidencia histórica. El runner sintético de
  Etapa 0, rehearsal, harness, mocks y tests directos que materializan P05 son
  `TEST_ONLY`/`HISTORICAL_COMPATIBILITY`, no runtime productivo.
- **Fuera de alcance:** P06/P07/P08/P09, routing histórico e infraestructura no
  cambian; P08 y el movimiento de P09 siguen pendientes. P10 permanece
  deshabilitado y no hubo autorización ni transporte billable.
- **Relación:** D-074, D-075, ADR-037,
  `pipeline-authority/1.0.0` y migración
  `202608150006_phase3_p05_runtime_cutover.sql`.
