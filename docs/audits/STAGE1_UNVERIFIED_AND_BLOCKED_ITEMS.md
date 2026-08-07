# Verificaciones no realizadas y bloqueadas de Etapa 1

Fecha de corte: `2026-08-04`. Este registro contiene exclusivamente
comprobaciones imposibles con los accesos/artefactos disponibles, evidencia
insuficiente, recursos no disponibles y riesgos que no pudieron descartarse.
Los incumplimientos ya demostrados —por ejemplo Terraform exit `2`, ausencia de
trigger y defectos de revisión— están en el backlog y no se duplican aquí.

Ninguno de estos ítems es una decisión de producto. No quedaron decisiones por
preguntar: la jerarquía canónica ofreció una única interpretación defendible.

## Accesos utilizados y faltantes

| Plataforma | Acceso usado | Acceso faltante / límite |
|---|---|---|
| GitHub | App conectada read-only para PR, commits, checks y logs. | Ninguno para las lecturas realizadas. |
| GCP | Sesión `gcloud` existente para describe, IAM, logs, builds, Artifact Registry, objeto source y metadata de secretos. | No se solicitó escritura ni impersonación administrativa. |
| Terraform | State local ignorado y credenciales de refresh/plan read-only. | Apply estaba prohibido y no era necesario para diagnosticar. |
| Supabase PostgreSQL | URL obtenida de Secret Manager solo en memoria; transacción/default read-only. | No se usaron credenciales de roles `anon/authenticated` ni se escribieron fixtures productivos. |
| Supabase Auth | JWKS HTTPS público. | Sin sesión CLI/admin read-only para users, invitations, redirect URLs y provider settings. |
| Cloudflare R2 | HTTPS anónimo y evidencia primaria aportada. | `wrangler 4.118.0` no autenticado; sin token temporal read-only de control plane. |
| Aplicación web | Browser público hasta login; health/readiness/ruta anónima. | Sin sesión docente válida ni magic link reutilizable; no se crearon datos. |

## Ítems

### UV-01 — Control plane actual de Cloudflare R2

- **Clasificación:** `BLOQUEADO_POR_ACCESO`.
- **Criterios afectados:** E1-03 y E1-11.
- **Verificación imposible:** repetir de forma independiente estado de r2.dev,
  custom domains, CORS, lifecycle, bucket privacy y scope del token.
- **Evidencia disponible:** archivos primarios aportados; endpoint S3 anónimo
  devuelve error de autorización; capacidad aportada dio 200 y luego 403.
- **Por qué es insuficiente:** la evidencia es una captura del propietario y
  `wrangler whoami` indicó que el auditor no estaba autenticado; la configuración
  pudo cambiar después.
- **Acceso/recurso mínimo faltante:** token temporal Cloudflare limitado a lectura
  de metadata del único bucket, sin lectura masiva ni escritura de objetos.
- **Riesgo no descartado:** cambio posterior en CORS/lifecycle/domain o scope más
  amplio del necesario.
- **Cierre:** export de metadata actual con timestamp/account/bucket redactados,
  comparación contra IaC/guía y revocación del token tras la auditoría.

### UV-02 — Configuración administrativa de Supabase Auth

- **Clasificación:** `BLOQUEADO_POR_ACCESO`.
- **Criterios afectados:** E1-01 y seguridad JWT/callback/membership.
- **Verificación imposible:** inspeccionar invitation state, redirect allowlist,
  issuer/audience configurados, expiración de magic links y estado del usuario
  desde Auth admin.
- **Evidencia disponible:** JWKS ES256 vivo, implementación y tests de
  issuer/audience/callback, fila agregada de user/membership y prueba aportada.
- **Por qué es insuficiente:** JWKS y PostgreSQL no prueban la configuración del
  panel Auth ni el lifecycle de la invitación.
- **Acceso/recurso mínimo faltante:** Supabase CLI/API con rol read-only para Auth
  settings y metadata de un usuario sintético; nunca service-role key pegada.
- **Riesgo no descartado:** redirect no deseado, invitación reutilizable o
  configuración distinta a los settings validados por la app.
- **Cierre:** captura primaria de settings y ciclo invitation→callback→membership
  con usuario sintético, sin guardar email/token.

### UV-03 — Happy path cloud repetido por el auditor en browser autenticado

- **Clasificación:** `BLOQUEADO_POR_ACCESO_Y_ESCRITURA_PROHIBIDA`.
- **Criterios afectados:** E1-01–E1-11, especialmente E1-08/E1-09/E1-11.
- **Verificación imposible:** repetir personalmente login, actividad, upload,
  blueprint, submission, Job, evidence viewer, aprobación, exports y reload
  contra la imagen final.
- **Evidencia disponible:** resumen/estados primarios del paquete, DB durable,
  Cloud Run executions, ledger, exports y pruebas locales/CI; browser público
  llegó al login sin errores de consola.
- **Por qué es insuficiente:** no había sesión docente o magic link válido y el
  recorrido crearía filas/objetos/Jobs, escrituras prohibidas por el encargo.
- **Acceso/recurso mínimo faltante:** entorno cloud de auditoría aislado o
  autorización explícita para fixtures sintéticos más identidad docente temporal.
- **Riesgo no descartado:** defecto de integración solo visible en navegador,
  cookie/callback/reload o descarga final.
- **Cierre:** browser E2E reproducible sobre tenant sintético aislado, con trace y
  screenshots redactados, IDs/hash/timestamps y cleanup autorizado.

### UV-04 — Enforcement real con roles PostgreSQL de cliente

- **Clasificación:** `BLOQUEADO_POR_CREDENCIAL_Y_ESCRITURA_PROHIBIDA`.
- **Criterios afectados:** E1-01, E1-10, E1-11 y tenant isolation.
- **Verificación imposible:** ejecutar operaciones negativas como roles reales
  `anon/authenticated` sobre dos tenants en la base administrada.
- **Evidencia disponible:** 24/24 tablas con RLS, cero grants a ambos roles,
  grants `service_role`, disciplina `scoped` y tests PostgreSQL locales
  cross-tenant/cross-submission.
- **Por qué es insuficiente:** metadata y tests locales no equivalen a una sesión
  administrada bajo cada rol; la conexión de servicio usada por la app bypassa
  el modelo de cliente y hace crítica la autorización server-side.
- **Acceso/recurso mínimo faltante:** usuario/tenant sintético y credenciales
  efímeras limitadas para pruebas negativas, en un proyecto clone/staging.
- **Riesgo no descartado:** diferencia de grants/policies/runtime en PG17 no
  ejercitada por un cliente real.
- **Cierre:** matriz read/write negativa por rol y tenant en staging, sin datos
  reales, más evidencia de que producción conserva la misma migración.

### UV-05 — Suite completa automatizada sobre PostgreSQL 17

- **Clasificación:** `RECURSO_NO_DISPONIBLE_SIN_ESCRITURA`.
- **Criterios afectados:** E1-06, E1-10 y E1-11.
- **Verificación imposible:** migrar y ejecutar las 145 pruebas contra la base
  administrada PG17.6 sin alterar datos/esquema.
- **Evidencia disponible:** suite completa verde en PG16.14, E2E aportado en
  PG17.6 y consultas agregadas read-only a 24 tablas/triggers/ledger.
- **Por qué es insuficiente:** una consulta de lectura no cubre locks, DDL,
  transactions y diferencias del driver en ese major.
- **Acceso/recurso mínimo faltante:** instancia efímera PG17 o branch Supabase de
  prueba donde migraciones y fixtures estén autorizados.
- **Riesgo no descartado:** incompatibilidad específica de major o extensión.
- **Cierre:** misma matriz de migración/E2E/sensibles/full suite verde en PG16 y
  PG17, con DB fresca y luego repetida.

### UV-06 — Ausencia absoluta de secretos o texto estudiantil en logs

- **Clasificación:** `RIESGO_NO_DESCARTADO`.
- **Criterios afectados:** seguridad y E1-11.
- **Verificación imposible:** demostrar una propiedad negativa absoluta para
  todos los logs históricos y todas las rutas/fallos futuros.
- **Evidencia disponible:** escaneo de 1.712 entradas Cloud Run en 48 horas:
  cero patrones de JWT, email, credential URL, signed URL o capability path;
  secret scans local/CI verdes.
- **Por qué es insuficiente:** búsqueda heurística, ventana limitada y mensajes
  redactados; texto arbitrario podría no coincidir con los patrones.
- **Acceso/recurso mínimo faltante:** ninguno basta para una prueba absoluta;
  se requiere control preventivo y tests de no-log por cada boundary.
- **Riesgo no descartado:** student text, anchor, filename o token en una ruta de
  error no ejercitada; el adaptador local ya demuestra un caso de capability.
- **Cierre:** logging estructurado allowlist, tests adversariales y monitor de
  patrones sobre retención completa autorizada; revisión periódica.

### UV-07 — Provenance, SBOM y vulnerabilidades de la imagen final

- **Clasificación:** `EVIDENCIA_INSUFICIENTE_RECURSO_AUSENTE`.
- **Criterios afectados:** E0-02/E0-08 y E1-11 supply chain.
- **Verificación imposible:** validar una attestation SLSA, SBOM y scan asociado
  al digest final porque no estaban publicados/visibles.
- **Evidencia disponible:** build log success, source GCS 129/129 idéntico al
  commit, digest común, runtime hardening y `npm audit` sin vulnerabilidades.
- **Por qué es insuficiente:** Artifact Registry informó build level `unknown`;
  no hubo SBOM/attestation ni scan integral de paquetes/base Python/OS.
- **Acceso/recurso mínimo faltante:** artefactos de provenance/SBOM/scan ligados
  criptográficamente a `sha256:4dc9be…` o autorización para generarlos en un
  rebuild futuro.
- **Riesgo no descartado:** dependencia/base vulnerable o build no reproducible
  pese a la correcta correlación source→commit.
- **Cierre:** provenance verificable, SBOM y scan policy con resultado/timestamp
  para el mismo digest desplegado.

### UV-08 — Exit del comando que disparó el fallo controlado

- **Clasificación:** `AFIRMACION_NO_DEMOSTRADA`.
- **Criterios afectados:** E1-06/E1-07.
- **Verificación imposible:** recuperar el exit exacto del comando original.
- **Evidencia disponible:** Cloud Run execution/task están failed, PostgreSQL
  registra `JOB_KIND_INVALID`, attempt 1, task 1 y retries 0.
- **Por qué es insuficiente:** el script original consultó `PIPESTATUS` bajo zsh;
  esa medición no demuestra el exit del comando canalizado.
- **Acceso/recurso mínimo faltante:** transcript nuevo con `set -o pipefail` y
  captura POSIX correcta; repetir implicaría otra escritura/Job productivo.
- **Riesgo no descartado:** solo la cifra de exit del cliente; el fallo durable y
  ausencia de retry sí están demostrados.
- **Cierre:** repetir en staging y registrar command exit, execution status,
  task count, attempts y estado DB con timestamps correlacionados.

### UV-09 — Mismo SHA para CI, build y runtime después de la auditoría

- **Clasificación:** `EVIDENCIA_NO_DISPONIBLE_SIN_NUEVO_BUILD_DEPLOY`.
- **Criterios afectados:** E1-11.
- **Verificación imposible:** demostrar que el HEAD documental
  `2c018ef126622f7d0c6b84eeaf563a20bded593e` fue construido y desplegado.
- **Evidencia disponible:** imagen/Cloud Build directos de `0167f14…`; el rango
  `0167f14…` → `2c018ef…` contiene solo cuatro auditorías previas y el diff
  no-audit termina 0; CI actual del PR está verde.
- **Por qué es insuficiente:** equivalencia funcional no convierte la imagen en
  evidencia directa del HEAD, y CI valida un merge sintético distinto.
- **Acceso/recurso mínimo faltante:** nuevo trigger/build y despliegue del SHA
  final, acciones expresamente fuera de una auditoría read-only.
- **Riesgo no descartado:** error de procedencia en una revisión futura que sí
  cambie código entre CI y deploy.
- **Cierre:** un único SHA aparece en checkout CI, source build, label OCI,
  Terraform digest y runtime, con manifest primario.

## Efecto sobre el dictamen

Estos límites no elevan ninguna historia completa a `NO_VERIFICABLE`: existe
evidencia suficiente para clasificarlas como satisfechas, satisfechas con
limitación o parciales. Sí impiden convertir afirmaciones estrechas —control
plane R2 actual, Auth admin, browser E2E independiente, enforcement PG17,
ausencia absoluta en logs y attestations— en hechos demostrados.

Accesos faltantes al cierre: Cloudflare read-only, Supabase Auth admin read-only,
identidad docente/tenant sintético y un recurso PostgreSQL 17 escribible de
prueba. No se solicitaron credenciales por chat ni permisos administrativos.

`READY_FOR_STAGE1_REMEDIATION`
