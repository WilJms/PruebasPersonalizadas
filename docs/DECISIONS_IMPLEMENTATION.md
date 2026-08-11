# Decisiones menores de implementación

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
