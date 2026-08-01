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
  handler; un replay devuelve el resultado canónico. URLs firmadas y
  expiraciones no se guardan: para uploads/exports solo se persiste un
  descriptor y se firma una capacidad nueva después de volver a autorizar y
  validar CSRF.
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

## D-012 - Persistencia cloud refleja el ORM ejecutado

- **Decisión:** la migración Supabase crea exactamente las tablas/columnas del
  modelo SQLAlchemy de Etapa 1, habilita RLS y revoca acceso directo del
  navegador. FastAPI y el worker usan la conexión de servicio; R2 conserva
  bytes raw/sellados y exports.
- **Razón:** un esquema conceptual paralelo que no coincide con el repositorio
  ejecutable produciría un despliegue que compila pero no inicia.
- **Relación:** E1-10/E1-11 y ADR-032.

## D-013 - No adelantar robustez ni acciones de Etapa 2

- **Decisión:** Etapa 1 admite una sola submission, una única ejecución por
  estado de decisión y aprobación completa. No se añaden retry general,
  cancelación, lote, OCR/DOCX, edición/regeneración por pregunta, aprobación
  masiva, feedback ni borrado operativo.
- **Razón:** esas capacidades pertenecen expresamente a E2-01 a E2-15.
- **Relación:** plan v1.1, secciones “Fuera de etapa” de Etapa 1 y Etapa 2.

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
  append-only. CI ejecuta este boundary con PostgreSQL 16 antes del E2E.
- **Razón:** SQLite y una comparación textual no validan DDL, tipos, RLS,
  triggers ni comportamiento del driver PostgreSQL.
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

## D-019 - Dos gates de cierre distintos

- **Decisión:** `READY_FOR_EXTERNAL_STAGE1_VERIFICATION` significa que el
  boundary local/reproducible está verde. E1-11 continúa parcial hasta evidencia
  real de GCP, Supabase y R2. Solo después de esa evidencia podría evaluarse un
  gate posterior; esta auditoría nunca declara `READY_FOR_STAGE_2`.
- **Razón:** IaC válida, adapters y fakes no demuestran IAM, Auth, RLS, CORS,
  lifecycle, red ni durabilidad de un Cloud Run Job real.
- **Relación:** E1-11 y restricción explícita de alcance.

## D-020 - Cloud Build usa identidad dedicada también para el source staging

- **Decisión:** Terraform habilita Cloud Storage y concede a la cuenta dedicada
  de Cloud Build `roles/storage.bucketViewer` y `roles/storage.objectUser`,
  además de los permisos ya acotados para Artifact Registry, Logging y Cloud
  Run. La cuenta del build sigue separada de las identidades web y worker.
- **Razón:** un `gcloud builds submit` o trigger con cuenta indicada necesita
  acceder al staging de código; validar solo el push de la imagen dejaba el
  primer build expuesto a fallar antes de ejecutar el Dockerfile.
- **Relación:** E1-11, D-016 y principio de mínimo privilegio dentro del proyecto
  experimental dedicado.
