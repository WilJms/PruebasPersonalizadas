# Backlog de remediación de Etapa 1

Fecha de corte: `2026-08-04`. Este backlog prescribe trabajo futuro; no
implementa correcciones ni abre historias de Etapa 2.

## Resumen y orden

| Severidad | Cantidad | Regla de prioridad |
|---|---:|---|
| P0 | 0 | No se identificó pérdida activa de datos, fuga confirmada ni aislamiento roto. |
| P1 | 11 | Bloquean el cierre técnico/funcional de Etapa 1. |
| P2 | 17 | Cerrar después de P1 o en paralelo cuando no alteren su diseño. |
| P3 | 2 | Deuda menor, sin capacidad de cierre por sí sola. |

Orden recomendado: `AUD-P1-01` y `AUD-P1-02`; frontera contractual
`AUD-P1-10/11`; revisión humana `AUD-P1-05/06/07/09`; grounding/logs
`AUD-P1-08/04`; recuperación `AUD-P1-03`; después P2 y P3 según dependencias.
No hay decisiones de producto pendientes: la jerarquía canónica determina una
salida conservadora para los 30 hallazgos.

## P1 — bloqueantes

### AUD-P1-01 — Terraform no converge

- **Severidad / componente:** P1 · Terraform / Cloud Run Service.
- **Descripción:** el plan vivo propone eliminar el bloque superior
  `scaling` normalizado a ceros, aun sin cambios intencionales.
- **Evidencia:** `plan -detailed-exitcode` terminó `2`, `0 add/1 change/0
  destroy`; solo afecta `google_cloud_run_v2_service.web[0]`. Una copia en
  `/tmp` con `manual_instance_count=0` y `min_instance_count=0` terminó `0`.
- **Fuente canónica:** Plan E1-11, ADR-032 y `docs/EXTERNAL_SETUP.md`, cuyo gate
  exige plan exit `0`; Terraform es el único owner de Service/Job.
- **Impacto:** E1-11 y el gate externo no pueden cerrarse; cada refresh propone
  un cambio espurio.
- **Causa probable:** provider google 6.50.0 materializa defaults API `0`, pero
  la configuración omite el bloque superior.
- **Solución recomendada:** declarar explícitamente ambos ceros; no usar
  `ignore_changes`, porque ocultaría drift futuro.
- **Archivos/recursos afectados:** `deploy/terraform/main.tf`, tests de deploy,
  state y `cva-web`; no debe cambiar `cva-worker` ni aplicarse durante el fix.
- **Pruebas de cierre:** fmt/init/validate/tests; plan guardado revisable y dos
  planes vivos consecutivos exit `0`, `0 add/0 change/0 destroy`.
- **Dependencia:** acceso read-only a GCP/state y variables efímeras; ninguna
  decisión de producto.
- **Riesgo:** bajo si el HCL refleja los ceros remotos; aplicar sin revisar el
  plan podría afectar escalado. **Requiere decisión de producto:** No.

### AUD-P1-02 — No existe trigger GitHub–Cloud Build

- **Severidad / componente:** P1 · CI/CD / procedencia.
- **Descripción:** Cloud Build recibió un tar GCS mediante submit manual y un
  `COMMIT_SHA` proporcionado por el operador; la lista regional de triggers está
  vacía.
- **Evidencia:** build final `85514589-a513-46af-ae74-1656a8433aa7` success y
  fuente 129/129 idéntica a `0167f14…`, pero `triggers list` devolvió `[]`.
- **Fuente canónica:** Plan E1-11, ADR-032, D-020–D-023 y salida de
  `docs/EXTERNAL_SETUP.md` para GitHub + Cloud Build.
- **Impacto:** el build concreto es trazable, pero el proceso no enlaza de forma
  automática y verificable revisión, SHA y artefacto.
- **Causa probable:** bootstrap se cerró con `gcloud builds submit` y no se
  provisionó conexión/trigger de mínimo privilegio.
- **Solución recomendada:** declarar una conexión repositorio y trigger por SHA
  revisado; limitar SA a build/push, conservar Terraform como único deployer y
  exigir imagen por digest.
- **Archivos/recursos afectados:** `deploy/terraform/*.tf`,
  `deploy/cloudbuild.yaml`, `.github/workflows/ci.yml`, conexión GitHub/GCP,
  trigger regional y build SA.
- **Pruebas de cierre:** push de commit sintético autorizado crea un único build;
  source/label/PR SHA coinciden; SA carece de `run.admin`/actAs runtime; Cloud
  Build no despliega; digest alimenta un plan Terraform revisado.
- **Dependencia:** autorización de GitHub App/Developer Connect y GCP para crear
  conexión/trigger en una remediación controlada.
- **Riesgo:** permisos excesivos o builds de refs no confiables. **Requiere
  decisión de producto:** No.

### AUD-P1-03 — El shell no permite recuperar un recorrido

- **Severidad / componente:** P1 · frontend / navegación / API.
- **Descripción:** después de login, raíz y sidebar conducen a crear actividad;
  el usuario necesita una URL/ID conocida para volver a una actividad o job.
- **Evidencia:** inspección de rutas y UI; la prueba aportada recupera por deep
  link, no desde el shell.
- **Fuente canónica:** Plan E1-11 y MVP §8, pantalla “Actividades”.
- **Impacto:** cerrar navegador no detiene el Job, pero el flujo durable no es
  recuperable por una persona normal.
- **Causa probable:** `GET /api/v1/activities` existe, pero no tiene consumidor
  ni landing privada.
- **Solución recomendada:** añadir lista tenant-scoped con status, submission/job
  y acción “Continuar” derivada de lectura fresca; mantener deep links.
- **Archivos/recursos afectados:** `frontend/src/App.tsx`, `routing.tsx`,
  `components/AppShell.tsx`, nueva página, `api/client.ts`, `api/types.ts`, tests.
- **Pruebas de cierre:** nueva sesión de navegador recupera cada estado desde
  `/`; casos sin submission, running/failed/ready y cross-tenant negativo.
- **Dependencia:** `AUD-P1-10` recomendado para tipar la lista.
- **Riesgo:** filtrar otro tenant o enlazar un estado obsoleto. **Requiere
  decisión de producto:** No.

### AUD-P1-04 — Capacidades locales aparecen en access logs

- **Severidad / componente:** P1 · logging / object store local.
- **Descripción:** la capacidad fake está en el path y Uvicorn registra el
  request target completo.
- **Evidencia:** un probe ficticio apareció literalmente como
  `/api/v1/objects/audit-capability-probe`; el cloud scan no encontró esa ruta.
- **Fuente canónica:** reglas de seguridad de `AGENTS.md`, arquitectura de
  objetos privados y URLs/capacidades de corta vida.
- **Impacto:** un token real del adaptador MemoryObjectStore puede quedar en
  logs de desarrollo/CI y ser reutilizable durante su TTL.
- **Causa probable:** access logger genérico, sin route-template redaction.
- **Solución recomendada:** desactivar el raw access log para esas rutas y emitir
  logs estructurados propios con plantilla, método, status, hash/size e IDs
  opacos; nunca token, query, filename ni texto.
- **Archivos/recursos afectados:** `deploy/docker-entrypoint.sh`,
  `web/app.py`, `web/object_store.py`, settings/logging y tests.
- **Pruebas de cierre:** PUT/GET válido, inválido y expirado; buscar el token y
  sus segmentos en toda la salida devuelve cero, manteniendo evento operativo.
- **Dependencia:** ninguna.
- **Riesgo:** perder observabilidad al desactivar logs sin reemplazo. **Requiere
  decisión de producto:** No.

### AUD-P1-05 — Blueprint revisable incompleto

- **Severidad / componente:** P1 · frontend / aprobación de blueprint.
- **Descripción:** la pantalla no muestra todas las constraints, factores,
  evidence requirements, formatos, dificultades, flags y checks que P06/P07
  aplicarán.
- **Evidencia:** comparación `AssessmentBlueprint`/P04 con
  `BlueprintPage.tsx`; solo se proyecta un subconjunto.
- **Fuente canónica:** `QuestionOpportunityTemplate`, `EvidenceVariant`,
  `AssessmentConstraints`, Prompt P04 y Plan E1-05.
- **Impacto:** la aprobación humana congela un catálogo sin poder auditar sus
  restricciones completas.
- **Causa probable:** DTO/tipo frontend estrechado y diseño visual centrado en
  campos editables.
- **Solución recomendada:** proyectar todos los campos relevantes en disclosure
  legible; mantener read-only lo no editable y no añadir selector de dificultad.
- **Archivos/recursos afectados:** `frontend/src/pages/BlueprintPage.tsx`,
  `api/types.ts`, estilos, fixtures y tests.
- **Pruebas de cierre:** fixture heterogéneo; cada restricción aparece; campos
  read-only no mutan; warning/fail P05 visible; responsive/teclado.
- **Dependencia:** `AUD-P1-10`; copy humano de `AUD-P2-05`.
- **Riesgo:** sobrecarga visual o habilitar edición no autorizada. **Requiere
  decisión de producto:** No.

### AUD-P1-06 — `SelectedQuestion` pierde metadata en revisión

- **Severidad / componente:** P1 · frontend / Assessment review.
- **Descripción:** faltan formato, dificultad, minutos, policy de justificación,
  planning score y referencias contractuales/curso.
- **Evidencia:** comparación del root canónico con `api/types.ts` y
  `AssessmentReviewPage.tsx`; persistencia/export conservan los campos.
- **Fuente canónica:** `SelectedQuestion`, Plan E1-08 y arquitectura de revisión.
- **Impacto:** el reviewer no puede validar decisiones de planificación ya
  materializadas.
- **Causa probable:** modelo frontend manual e incompleto, favorecido por
  respuestas OpenAPI libres.
- **Solución recomendada:** tipar/proyectar todas las propiedades relevantes,
  rotulando guía preliminar versus final; mantenerlas no editables.
- **Archivos/recursos afectados:** `frontend/src/api/types.ts`,
  `pages/AssessmentReviewPage.tsx`, fixtures/tests y response models backend.
- **Pruebas de cierre:** fixture canónico completo; assertions por campo,
  closed-context, `NOT_REQUIRED/SELECTED/ALL`, responsive y locale.
- **Dependencia:** `AUD-P1-10` y coordinación con `AUD-P1-07`.
- **Riesgo:** confundir metadata preliminar con guía final.
  **Requiere decisión de producto:** No.

### AUD-P1-07 — Alternativas `CHOICE` ausentes antes de aprobar

- **Severidad / componente:** P1 · frontend / seguridad pedagógica.
- **Descripción:** una pregunta CHOICE puede aprobarse sin mostrar opciones,
  best answer, rationale ni misconception al evaluador.
- **Evidencia:** flujo renderizado con tres opciones; UI no las muestra, mientras
  el JSON/PDF derivado sí conserva las alternativas.
- **Fuente canónica:** `ChoiceOption`, validator de `SelectedQuestion` y Plan
  E1-08.
- **Impacto:** la revisión humana requerida es materialmente incompleta y puede
  aprobar distractores defectuosos.
- **Causa probable:** `choices` falta en el tipo frontend y en el componente.
- **Solución recomendada:** renderizar orden estable y panel de evaluador con
  clave/rationale/misconceptions, separado de cualquier vista estudiantil.
- **Archivos/recursos afectados:** `frontend/src/api/types.ts`,
  `AssessmentReviewPage.tsx`, fixtures/tests y tests de export.
- **Pruebas de cierre:** ≥3 opciones, exactamente una best, misconception de
  cada distractor, non-CHOICE sin options y Assessment PDF sin clave/rationale.
- **Dependencia:** `AUD-P1-06` y `AUD-P1-10`.
- **Riesgo:** filtrar la respuesta correcta en vista/export del estudiante.
  **Requiere decisión de producto:** No.

### AUD-P1-08 — Gate evidence-first no es verificable

- **Severidad / componente:** P1 · frontend/backend / grounding.
- **Descripción:** `onClick` marca una pregunta como revisada antes de que la
  fuente cargue; un click cubre todos sus fragments y la aprobación no verifica
  receipts server-side.
- **Evidencia:** inspección de `AssessmentReviewPage.tsx`, endpoint de fuente y
  servicio de aprobación.
- **Fuente canónica:** Plan E1 risk “viewer abre la fuente exacta”, MVP §8 y
  arquitectura de grounding/auditoría.
- **Impacto:** el producto afirma revisión evidence-first sin demostrar que cada
  localizador se abrió correctamente para usuario/versión actuales.
- **Causa probable:** gate implementado como estado React local.
- **Solución recomendada:** resolver cada locator en viewer controlado; tras
  éxito registrar receipt `evidence.viewed` sin texto, ligado a tenant, actor,
  assessment, question, fragment, locator hash y ETag; verificarlo al aprobar.
- **Archivos/recursos afectados:** `web/app.py`, workflows/repository/audit,
  object viewer, `AssessmentReviewPage.tsx`, API types y tests; tabla existente
  `audit_events` si resulta suficiente.
- **Pruebas de cierre:** 404/expiry no habilita; todos los fragments requeridos;
  otro tenant/actor/versión no sirve; reload conserva; logs no filtran token.
- **Dependencia:** `AUD-P1-10`; soporte exacto de locators de parsers.
- **Riesgo:** convertir el receipt en contenido sensible o inferir comprensión
  humana. **Requiere decisión de producto:** No.

### AUD-P1-09 — Guía visible pierde trazabilidad

- **Severidad / componente:** P1 · frontend / EvaluationGuide.
- **Descripción:** la UI omite misconceptions, evidence/source IDs y enlaces
  nivel→observable aunque el root persistido los conserva.
- **Evidencia:** comparación `EvaluationGuide`/`GuideItem` con `GuideView`.
- **Fuente canónica:** modelos de guía, Plan E1-09, ADR-003 y Prompt P09.
- **Impacto:** la guía consultable no permite auditar de forma completa criterios
  y observables.
- **Causa probable:** tipo/vista frontend reducidos a propósito, niveles y
  alternativas básicas.
- **Solución recomendada:** proyectar el root completo con enlaces navegables y
  etiquetas humanas, sin mezclarlo con Assessment ni exponerlo al estudiante.
- **Archivos/recursos afectados:** `frontend/src/api/types.ts`,
  `AssessmentReviewPage.tsx` (`GuideView`), fixtures/tests.
- **Pruebas de cierre:** fixture con misconceptions/múltiples observables/sources;
  cada relación aparece; separación Assessment/Guide y exports permanece.
- **Dependencia:** `AUD-P1-10`.
- **Riesgo:** mostrar guía/clave en superficie estudiantil futura. **Requiere
  decisión de producto:** No.

### AUD-P1-10 — OpenAPI no expresa los contratos reales

- **Severidad / componente:** P1 · API / contratos / CI.
- **Descripción:** 14 request bodies y 30 responses aparecen como JSON libre o
  schema vacío; no existe snapshot OpenAPI.
- **Evidencia:** OpenAPI 3.1 con 28 paths/21 components; solo PATCH blueprint
  publica el root fuerte, aunque runtime valida más.
- **Fuente canónica:** `VALIDACION_CONTRATOS(1).md` §7, modelos/schema canónicos
  y Plan E0-06/E1.
- **Impacto:** provider/consumer no detectan pérdidas como `choices` o guide
  links y el frontend mantiene casts manuales.
- **Causa probable:** firmas FastAPI `dict[str, Any]`/`Response` y ausencia de
  DTOs transport que compongan roots canónicos.
- **Solución recomendada:** tipar requests/responses con roots importados o DTOs
  de transporte que los contengan; añadir validation y snapshot OpenAPI en CI.
- **Archivos/recursos afectados:** `src/.../web/app.py`, nuevo módulo DTO si
  procede, `frontend/src/api/types.ts`, tests contract/API y snapshot generado.
- **Pruebas de cierre:** ningún JSON mutable/respuesta de dominio libre salvo
  excepción justificada; consumer/provider tests; snapshot diff bloquea CI;
  extras/fallos siguen fail-closed.
- **Dependencia:** cerrar junto, no publicar solo una mitad request/response.
- **Riesgo:** duplicar modelos Pydantic o introducir cambio breaking accidental.
  **Requiere decisión de producto:** No.

### AUD-P1-11 — Principal UUID no valida en todos los actores canónicos

- **Severidad / componente:** P1 · contratos / identidad / auditoría.
- **Descripción:** `QuestionReviewAction.actor_id`, bulk records/request y
  `EventActor.id` siguen usando `Id` slug; un UUID Supabase es rechazado. Los
  tres campos aprobatorios ya migrados a `PrincipalId` sí validan.
- **Evidencia:** probes Pydantic/JSON Schema: PolicyDecision, Blueprint y
  Assessment aceptan UUID; QuestionReviewAction, Bulk y EventActor lo rechazan.
  PostgreSQL conserva cinco audit actors UUID.
- **Fuente canónica:** `PrincipalId`, semántica de actores en modelos v1.1 y
  ADR-032; `models_v1.1(1).py` es la única fuente manual.
- **Impacto:** eventos/acciones futuras o serialización de auditoría no pueden
  representar de extremo a extremo al principal externo real.
- **Causa probable:** migración parcial de `Id` a `PrincipalId`.
- **Solución recomendada:** auditar todos los campos de actor y cambiar solo los
  externos a `PrincipalId`; conservar IDs internos y service/system identities
  según su tipo; regenerar schema desde el modelo.
- **Archivos/recursos afectados:** `specification/models_v1.1(1).py`, schema
  generado, fixtures contractuales, API/services/events/exports y tests; no se
  anticipa migración SQL porque columnas ya aceptan UUID textual.
- **Pruebas de cierre:** matriz Pydantic/schema/OpenAPI/frontend/API/ORM/PG/events
  para UUID, slug permitido y IDs internos inválidos; schema temporal idéntico.
- **Dependencia:** `AUD-P1-10`; gate contractual completo.
- **Riesgo:** ampliar por error campos internos o editar `$defs` manualmente.
  **Requiere decisión de producto:** No.

## P2 — importantes

### AUD-P2-01 — Edición de actividad no alcanzable

- **Severidad / componente:** P2 · frontend/actividad.
- **Descripción / evidencia:** GET/PATCH, ETag y bloqueo backend existen, pero el
  formulario solo crea. **Fuente:** MVP §§8–9 y Plan E1-02.
- **Impacto / causa:** correcciones previas al freeze requieren API manual; falta
  modo edición/ruta en UI.
- **Solución / afectados:** reutilizar `ActivityCreatePage.tsx` como editor,
  `api/client.ts`, routing/tests; respetar CAS y freeze.
- **Cierre:** edición draft, ETag stale y bloqueo tras aprobación pasan en UI/E2E.
  **Dependencia:** `AUD-P1-03/10`. **Riesgo:** mutar tras derivación.
  **Requiere decisión de producto:** No.

### AUD-P2-02 — Estimación previa no visible

- **Severidad / componente:** P2 · API/frontend/costos.
- **Descripción / evidencia:** policies y ledger guardan límites/costo, pero no
  hay preflight antes de encolar. **Fuente:** arquitectura denial-of-wallet,
  matrices/costos y riesgos del Plan.
- **Impacto / causa:** el usuario inicia trabajo sin rango ni diagnóstico;
  policy técnica no se proyectó.
- **Solución / afectados:** DTO/endpoint tenant-scoped determinista y panel en
  actividad/submission; `web/app.py`, workflows/gateway policy, frontend/tests.
- **Cierre:** cambios N/tamaño actualizan estimate, over-limit falla antes de
  model call y OpenAPI lo captura. **Dependencia:** `AUD-P1-10`.
  **Riesgo:** falsa precisión/tarifas obsoletas. **Decisión de producto:** No.

### AUD-P2-03 — Sin vista read-only de mapa, oportunidades y plan

- **Severidad / componente:** P2 · API/frontend/trazabilidad.
- **Descripción / evidencia:** evidence maps, opportunities, primary/reserve y
  reviews existen en DB/pipeline, pero no tienen vista autorizada completa.
  **Fuente:** MVP §9 y Plan E1-06/E1-08.
- **Impacto / causa:** el humano no puede seguir pregunta→oportunidad→evidencia;
  solo se implementaron superficies de aprobación finales.
- **Solución / afectados:** GET tipado tenant-scoped y sección read-only;
  `web/app.py`, repository/workflows, API DTOs, frontend/tests.
- **Cierre:** IDs coinciden end-to-end, cross-tenant falla, READY/fail-closed se
  muestran sin acciones E2. **Dependencia:** `AUD-P1-03/10`.
  **Riesgo:** exponer prompt/texto sensible. **Decisión de producto:** No.

### AUD-P2-04 — Aviso de privacidad/copy experimental incompleto

- **Severidad / componente:** P2 · frontend/login/privacidad.
- **Descripción / evidencia:** login dice invitación/entorno experimental, pero
  no finalidad, tratamiento limitado ni canal/política. **Fuente:** MVP §8 y
  arquitectura de privacidad.
- **Impacto / causa:** consentimiento contextual insuficiente; copy mínimo.
- **Solución / afectados:** aviso autorizado en `LoginPage.tsx`, estilos/tests,
  sin inventar retención ni reutilizar disclaimer E2.
- **Cierre:** finalidad, datos controlados, límites y contacto visibles antes de
  login; reflow/contraste. **Dependencia:** política/enlace institucional vigente.
  **Riesgo:** promesa legal inexacta. **Decisión de producto:** No; usar texto
  canónico/provisional honesto.

### AUD-P2-05 — Enums y semántica `CHOICE/SELECTED` confusos

- **Severidad / componente:** P2 · frontend/copy.
- **Descripción / evidencia:** “Con opciones justificadas”, “Seleccionada” y
  enums crudos no distinguen rationale interno, justificación estudiantil ni
  actor/alcance. **Fuente:** `ResponseFormat`, `StructuredJustificationPolicy` y
  arquitectura UI auditable.
- **Impacto / causa:** una configuración válida puede interpretarse mal; labels
  se derivan mecánicamente del enum.
- **Solución / afectados:** catálogo exhaustivo de labels/ayuda y badges de flags
  materializados en Activity/Blueprint/Review.
- **Cierre:** `CHOICE+NOT_REQUIRED`, `SELECTED` y fallback desconocido probados;
  códigos canónicos siguen disponibles. **Dependencia:** `AUD-P1-05/06/07`.
  **Riesgo:** traducción cambia significado. **Decisión de producto:** No.

### AUD-P2-06 — Tabs y foco incompletos

- **Severidad / componente:** P2 · accesibilidad frontend.
- **Descripción / evidencia:** faltan `aria-controls`, `tabpanel`, roving
  tabindex/teclas; inputs custom no trasladan foco visible. **Fuente:** MVP de
  shell usable y semántica ARIA aplicable.
- **Impacto / causa:** flujo de revisión difícil o imposible con teclado/AT;
  implementación parcial del patrón.
- **Solución / afectados:** `AssessmentReviewPage.tsx`, formularios custom,
  `styles.css` y tests a11y/keyboard.
- **Cierre:** flechas/Home/End, focus ring, asociación tab-panel y 320/390 px.
  **Dependencia:** ninguna. **Riesgo:** regresión visual/foco doble.
  **Decisión de producto:** No.

### AUD-P2-07 — Harness PostgreSQL no es repetible

- **Severidad / componente:** P2 · tests/persistencia.
- **Descripción / evidencia:** E2E + sensibles y luego suite completa en la
  misma DB produjo 143 pass/2 fail por filas residuales; DB nueva dio 145 pass.
  **Fuente:** comandos previstos en `AGENTS.md` y estrategia de tests aislados.
- **Impacto / causa:** orden/reintento genera falsos fallos; fixtures usan IDs o
  conteos globales persistentes.
- **Solución / afectados:** namespace por run/rollback/truncate seguro en DB
  efímera; `scripts/prepare_postgres.py`, tests stage1 y CI.
- **Cierre:** dos ejecuciones completas consecutivas sobre el mismo contenedor
  terminan iguales, sin borrar DB no dedicada. **Dependencia:** PG efímero.
  **Riesgo:** cleanup destructivo fuera de test. **Decisión de producto:** No.

### AUD-P2-08 — Producción PG17, CI PG16

- **Severidad / componente:** P2 · compatibilidad PostgreSQL.
- **Descripción / evidencia:** Supabase reportó 17.6; local/CI cubren 16.14.
  **Fuente:** arquitectura Supabase/PostgreSQL y gate de migración E1.
- **Impacto / causa:** SQL/driver puede divergir por major; matriz CI fijada solo
  a 16.
- **Solución / afectados:** matrix PG16+17 para migración, E2E y sensibles;
  `.github/workflows/ci.yml`, Makefile/tests.
- **Cierre:** ambos majors verdes con misma surface 24/RLS/triggers.
  **Dependencia:** imagen PG17. **Riesgo:** duplicar tiempo CI/flakiness.
  **Decisión de producto:** No.

### AUD-P2-09 — Estado documental y PR obsoletos

- **Severidad / componente:** P2 · documentación/trazabilidad.
- **Descripción / evidencia:** PR body, `IMPLEMENTATION_STATUS.md` y
  `TEST_RESULTS.md` aún dicen que cloud/plan/R2/Supabase no se ejecutaron.
  **Fuente:** obligación documental del prompt y estado real auditado.
- **Impacto / causa:** operadores reciben un snapshot histórico como actual;
  cierre externo ocurrió después sin actualización.
- **Solución / afectados:** actualizar esos documentos y PR con SHA/digest,
  fechas, límites y links al nuevo audit; nunca reemplazar primarios por resumen.
- **Cierre:** cada claim actual tiene evidencia y timestamp; revisión de stale
  markers. **Dependencia:** cerrar P1-01/02 para el snapshot definitivo.
  **Riesgo:** declarar E1 cerrada antes del gate. **Decisión de producto:** No.

### AUD-P2-10 — Paquete externo tiene huecos de calidad

- **Severidad / componente:** P2 · evidence engineering.
- **Descripción / evidencia:** manifest sin hashes, health final vacío,
  snapshots intermedios sin etiqueta y resumen que contradice Terraform.
  **Fuente:** protocolo de evidencia de esta auditoría y `EXTERNAL_SETUP`.
- **Impacto / causa:** dificulta cadena de custodia y permite citar artefactos
  obsoletos; recolección manual incremental.
- **Solución / afectados:** script/plantilla de captura fuera del producto:
  hashes, timestamps UTC, perfil SHA/build/digest y clasificación primaria.
- **Cierre:** nuevo tar seguro, checksum, inventario hash completo, 0 vacíos,
  cada gate ligado a primario. **Dependencia:** P1-01/02 y accesos de auditoría.
  **Riesgo:** capturar secretos/logs completos. **Decisión de producto:** No.

### AUD-P2-11 — CI/deploy prueban SHAs distintos

- **Severidad / componente:** P2 · procedencia CI/CD.
- **Descripción / evidencia:** cloud corre `0167f14…`, CI actual valida merge
  sintético `3830089…` con head `2c018ef…`; equivalencia funcional se infiere de
  diff solo-audits. **Fuente:** prohibición de mezclar commits y Plan E1-11.
- **Impacto / causa:** no hay una atestación única CI→build→digest→deploy para el
  HEAD final; PR siguió avanzando después de desplegar.
- **Solución / afectados:** tras remediar, ejecutar CI del SHA exacto, trigger
  Cloud Build de ese SHA y manifest digest; workflow/build metadata.
- **Cierre:** misma revisión identificable en CI source, build source, OCI label,
  Terraform input y runtime. **Dependencia:** `AUD-P1-02`.
  **Riesgo:** confundir merge ref con head. **Decisión de producto:** No.

### AUD-P2-12 — Supply chain no totalmente reproducible

- **Severidad / componente:** P2 · Docker/dependencias/Artifact Registry.
- **Descripción / evidencia:** bases y dependencias Python no están fijadas por
  digest/hash de extremo a extremo; Artifact Registry informa SLSA level
  `unknown`; no se observó SBOM/vulnerability attestation.
- **Fuente:** Plan E1-11, ADR-032 y requisito de imagen inmutable.
- **Impacto / causa:** reconstruir mismo commit puede producir bytes/dependencias
  distintos; pinning parcial.
- **Solución / afectados:** `Dockerfile`, `pyproject.toml`, lock con hashes,
  `frontend/package-lock.json`, `cloudbuild.yaml`; base por digest, SBOM y scan.
- **Cierre:** dos builds limpios resuelven inputs idénticos, provenance/SBOM
  vinculados al digest y scan bloqueante documentado. **Dependencia:** registry
  y tooling de attestations. **Riesgo:** updates de seguridad más lentos.
  **Decisión de producto:** No.

### AUD-P2-13 — Worker recibe secreto de sesión innecesario

- **Severidad / componente:** P2 · IAM/settings/Secret Manager.
- **Descripción / evidencia:** Job worker referencia los cuatro secretos,
  incluido session secret aunque no sirve HTTP. **Fuente:** least privilege de
  arquitectura/AGENTS y separación Service/Job.
- **Impacto / causa:** amplía blast radius; settings compartidos exigen secretos
  de web al worker.
- **Solución / afectados:** separar settings/runtime de worker y retirar acceso/
  env de `cva-session-secret`; `web/settings.py`, runtime/worker y Terraform IAM.
- **Cierre:** worker procesa un job sin session secret; Service auth sigue; IAM
  describe muestra ausencia. **Dependencia:** plan Terraform revisado.
  **Riesgo:** romper bootstrap por validación común. **Decisión de producto:** No.

### AUD-P2-14 — R2 no fue revalidado con control plane independiente

- **Severidad / componente:** P2 · Cloudflare R2 / evidencia.
- **Descripción / evidencia:** `wrangler whoami` no autenticado; CORS/lifecycle/
  r2.dev/domains se basan en salidas aportadas. **Fuente:** ADR de R2 privado,
  Plan E1-03/E1-11 y protocolo de acceso read-only.
- **Impacto / causa:** configuración actual podría haber cambiado sin detección;
  faltó sesión/token de auditoría.
- **Solución / afectados:** no código necesariamente; conceder token temporal
  read-only y repetir control plane + objeto sintético/TTL sin listar contenido.
- **Cierre:** metadata primaria actual con bucket/proyecto/timestamp y sin
  valores secretos; público sigue denegado. **Dependencia:** acceso Cloudflare.
  **Riesgo:** scope excesivo o exponer objetos. **Decisión de producto:** No.

### AUD-P2-15 — Exports no se recuperan tras reload

- **Severidad / componente:** P2 · frontend/API/exports.
- **Descripción / evidencia:** botones/URLs viven en `useState`; la tabla durable
  existe, pero reload pierde el estado y no hay lista/reemisión visible.
  **Fuente:** Plan E1-09/E1-11, MVP de reapertura y ADR-003.
- **Impacto / causa:** usuario repite export o pierde acceso a un artefacto
  durable; solo se implementó response inmediata.
- **Solución / afectados:** endpoint/lista autorizada de exports y reemisión de
  capability corta; `web/app.py`, repository, client/types y Review page.
- **Cierre:** reload muestra artefactos, URL expirada se reemite sin model call,
  tenant/approval gates pasan. **Dependencia:** `AUD-P1-03/10`.
  **Riesgo:** persistir URL firmada. **Decisión de producto:** No.

### AUD-P2-16 — Documentos mezclan historias E2 con MVP/E1

- **Severidad / componente:** P2 · alcance/documentación.
- **Descripción / evidencia:** workbook/informes previos presentan aprobación
  masiva u otras superficies E2 como MVP, en tensión con Plan y `AGENTS.md`.
  **Fuente:** Plan E2-*, ADR-030–034 y gate explícito del repositorio.
- **Impacto / causa:** un agente puede ampliar scope por leer una fuente inferior
  sin aplicar jerarquía; documentación evolucionó en momentos distintos.
- **Solución / afectados:** etiquetar en workbook/docs cada historia por etapa y
  añadir nota de precedencia; no implementar batch/retry/cancel/actions/bulk.
- **Cierre:** búsqueda de términos E2 no los presenta como cierre E1; matriz de
  consistencia enlaza gate. **Dependencia:** editar fuentes previas solo en una
  remediación autorizada. **Riesgo:** borrar requerimientos futuros.
  **Decisión de producto:** No.

### AUD-P2-17 — No existe browser E2E automatizado

- **Severidad / componente:** P2 · frontend/CI/E2E.
- **Descripción / evidencia:** tests React/integration y backend E2E pasan, pero
  no hay Playwright/browser contra stack real; el paquete solo resume el happy
  path. **Fuente:** salida E1-11 y matriz de pruebas del prompt/MVP.
- **Impacto / causa:** navegación, cookies, reload, viewer y descarga pueden
  romper sin gate; costo/credenciales del stack vivo evitaron automatización.
- **Solución / afectados:** suite browser con usuario/tenant sintético,
  frontend/API y entorno efímero o job cloud dedicado; CI y scripts de evidencia.
- **Cierre:** login→actividad→blueprint→submission→review→exports→reload,
  screenshots/logs redactados, no datos reales. **Dependencia:** `AUD-P1-03/08`
  y credencial temporal segura. **Riesgo:** flakiness/secretos en traces.
  **Decisión de producto:** No.

## P3 — deuda menor

### AUD-P3-01 — Warning de compatibilidad Starlette/httpx

- **Severidad / componente:** P3 · dependencias/tests.
- **Descripción / evidencia:** suite fresca termina 145 pass con un
  `StarletteDeprecationWarning`. **Fuente:** política de mantener suite limpia y
  runtime soportado.
- **Impacto / causa:** futura actualización puede romper TestClient; combinación
  de versiones aún compatible pero deprecada.
- **Solución / afectados:** fijar/actualizar combinación compatible en
  `pyproject.toml` y lock; ajustar tests solo según API soportada.
- **Cierre:** suite 145+ sin ese warning y matriz CI verde. **Dependencia:**
  `AUD-P2-12`. **Riesgo:** upgrade transitorio rompe FastAPI.
  **Decisión de producto:** No.

### AUD-P3-02 — Copy `OPEN_SHORT` sugiere un límite inexistente

- **Severidad / componente:** P3 · frontend/copy.
- **Descripción / evidencia:** “Explicación concisa” puede leerse como número de
  palabras o dificultad, campos que el contrato no define. **Fuente:**
  `ResponseFormat.OPEN_SHORT` y arquitectura de constructo.
- **Impacto / causa:** expectativa errónea; ayuda demasiado breve.
- **Solución / afectados:** `ActivityCreatePage.tsx` y test de copy: “alcance
  acotado para el tiempo disponible; no fija dificultad ni palabras”.
- **Cierre:** payload no cambia y no aparecen límites inventados.
  **Dependencia:** ninguna. **Riesgo:** introducir números no contractuales.
  **Decisión de producto:** No.

## Criterio global de salida

Para volver a auditar cierre deben estar resueltos los 11 P1, existir evidencia
primaria de sus pruebas y permanecer P0=0. Los P2/P3 pueden priorizarse por
riesgo, pero E1-11 exige además una cadena coherente del mismo SHA hasta el
digest y dos planes Terraform consecutivos exit `0`. Nada de este backlog
autoriza historias E2.

`READY_FOR_STAGE1_REMEDIATION`
