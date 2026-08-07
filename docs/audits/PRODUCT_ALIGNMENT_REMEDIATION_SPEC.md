# Especificación de remediación para alineación de producto

## Propósito y límites

Este documento prescribe la corrección exacta de los 22 hallazgos de la auditoría del commit `0167f14cbfe4a1192b26688a8443c5835da60bb4`. No implementa cambios y no abre Etapa 2.

Las soluciones deben conservar:

- `models_v1.1(1).py` como única fuente manual de contratos;
- schema generado, no editado a mano;
- una actividad y exactamente una submission en E1;
- aprobación completa individual, sin acciones por pregunta ni bulk approval;
- closed context, P10 deshabilitado y mock como modo de cierre cloud;
- objetos privados y contenido estudiantil fuera de logs;
- Assessment y EvaluationGuide JSON separados; PDF/HTML como vistas derivadas;
- planificador determinista y fail-closed.

## Resumen y prioridad

| ID | Sev. | Clasificación | Resultado objetivo resumido |
|---|---|---|---|
| F-001 | P2 | `IMPLEMENTACION_INCOMPLETA` | Login informa uso experimental y privacidad. |
| F-002 | P1 | `CAPACIDAD_AUSENTE` | Usuario puede reencontrar actividad/submission/job desde el shell. |
| F-003 | P2 | `CONFORME_PERO_CONFUSO` | `CHOICE` no se confunde con justificación estudiantil. |
| F-004 | P3 | `CONFORME_PERO_CONFUSO` | `OPEN_SHORT` se explica sin inventar límite de longitud. |
| F-005 | P2 | `CONFORME_PERO_CONFUSO` | `SELECTED` identifica actor, alcance y templates afectados. |
| F-006 | P2 | `CAPACIDAD_AUSENTE` | Configuración editable antes de aprobar blueprint. |
| F-007 | P2 | `IMPLEMENTACION_INCOMPLETA` | Estimación/límite previo visible antes de iniciar jobs. |
| F-008 | P1 | `IMPLEMENTACION_INCORRECTA` | Ningún token firmado aparece en access logs locales. |
| F-009 | P1 | `IMPLEMENTACION_INCOMPLETA` | Blueprint muestra todas las restricciones necesarias para aprobar catálogo. |
| F-010 | P2 | `CONFORME_PERO_CONFUSO` | Enums conservan código, pero se presentan con etiquetas humanas. |
| F-011 | P2 | `CAPACIDAD_AUSENTE` | Vista read-only autorizada de mapping/oportunidades/plan/reviews. |
| F-012 | P1 | `IMPLEMENTACION_INCOMPLETA` | Review muestra metadatos completos de cada `SelectedQuestion`. |
| F-013 | P1 | `IMPLEMENTACION_INCORRECTA` | Review de `CHOICE` muestra todas las alternativas y datos del evaluador. |
| F-014 | P1 | `IMPLEMENTACION_INCORRECTA` | Aprobación requiere receipt verificable por cada fragmento/fuente. |
| F-015 | P2 | `IMPLEMENTACION_INCOMPLETA` | Tabs implementan patrón ARIA y teclado completo. |
| F-016 | P1 | `IMPLEMENTACION_INCOMPLETA` | Guía conserva y muestra misconceptions y enlaces estructurales. |
| F-017 | P1 | `IMPLEMENTACION_INCORRECTA` | Requests OpenAPI usan modelos/DTOs compuestos canónicamente. |
| F-018 | P1 | `IMPLEMENTACION_INCORRECTA` | Responses OpenAPI son tipadas y validadas. |
| F-019 | P1 | `IMPLEMENTACION_INCOMPLETA` | Snapshot OpenAPI bloquea divergencias en CI. |
| F-020 | P2 | `IMPLEMENTACION_INCOMPLETA` | Todos los controles custom tienen foco visible. |
| F-021 | P2 | `CONTRADICCION_DOCUMENTAL` | Bulk approval queda etiquetado inequívocamente como E2. |
| F-022 | P2 | `CONTRADICCION_DOCUMENTAL` | Pantallas/endpoints MVP indican su etapa y gate. |

## Orden de ejecución recomendado

1. **Frontera de contrato:** F-017, F-018 y F-019. Hace visibles las pérdidas entre provider y consumer.
2. **Revisión humana:** F-009, F-012, F-013 y F-016. Restituye la semántica ya persistida.
3. **Grounding verificable:** F-014 y F-008.
4. **Recuperación del recorrido:** F-002, F-006 y F-011.
5. **Accesibilidad y copy:** F-001, F-003, F-004, F-005, F-007, F-010, F-015 y F-020.
6. **Claridad de alcance:** F-021 y F-022.

F-013 debe cerrarse antes de presentar el producto como apto para revisión de preguntas de selección. F-017–F-019 deben cerrar en el mismo cambio lógico para no publicar schemas tipados sin gate de regresión.

## Especificaciones por hallazgo

### F-001 — Aviso de privacidad ausente en login

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | `06_MVP_Entorno_Experimental(1).md` §8, pantalla Login/invitación; arquitectura §§ seguridad/privacidad |
| Módulos afectados | `frontend/src/pages/LoginPage.tsx`, estilos y test de login |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | Copy provisional de privacidad ya aprobado para el entorno experimental; no requiere política institucional completa E3 |

**Estado actual:** se informa acceso por invitación y entorno experimental, pero no finalidad, tratamiento limitado ni enlace/aviso de privacidad.

**Estado objetivo y solución exacta:** añadir en el panel de login un aviso visible, previo a continuar, que indique finalidad de verificación de comprensión, uso de datos sintéticos/controlados, acceso restringido, ausencia de calificación/autoría/IA y enlace o contacto de privacidad vigente. No reutilizar el disclaimer E2-15 como salida generada ni inventar retenciones no documentadas.

**Pruebas necesarias:** test de componente que encuentre el aviso por texto/landmark; contraste y reflow 320/390 px; snapshot/copy review.

**Criterio de cierre:** una persona puede identificar finalidad, carácter experimental y canal/política de privacidad sin iniciar sesión; el aviso no aparece en PDFs ni afirma detectar IA.

**Riesgo:** convertir copy provisional en promesa legal inexacta. Debe enlazar a la política autorizada o declarar honestamente el estado experimental.

### F-002 — Sin lista ni punto de recuperación

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `CAPACIDAD_AUSENTE` |
| Fuente | Plan E1-11 y salida de etapa; MVP §8 “Actividades” |
| Módulos afectados | `frontend/src/App.tsx`, `components/AppShell.tsx`, nueva vista de actividades, `api/client.ts`, `api/types.ts`, tests frontend/E2E |
| Cambio contractual | No; reutiliza `GET /api/v1/activities` existente |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-018 recomendado para tipar la respuesta; tenant scope existente |

**Estado actual:** raíz, login exitoso y sidebar conducen a `/activities/new`. La lista backend incluye estado y `submission_id`, pero el frontend no la consume.

**Estado objetivo y solución exacta:** crear `/activities` como landing privada y navegación “Actividades”. Listar únicamente actividades del workspace, status, última versión/aprobación, submission asociada y job/estado cuando exista. Cada fila debe ofrecer un único “Continuar” calculado: blueprint/ambigüedad, carga de submission, progreso o review. Mantener “Nueva actividad” como acción separada. La reapertura por URL profunda también debe seguir funcionando.

**Pruebas necesarias:** componente con actividades en cada estado; integración fresh browser session contra DB; prueba cross-tenant negativa; actividad sin submission; job RUNNING; estado fail-closed; mobile/keyboard.

**Criterio de cierre:** cerrar la pestaña, abrir la raíz con una sesión válida y recuperar el recorrido sintético sin copiar IDs ni usar historial del navegador.

**Riesgo:** enlazar un estado obsoleto o filtrar datos de otro tenant. La acción se deriva de una lectura fresca y siempre se valida en backend.

### F-003 — Etiqueta `CHOICE` confunde rationale con justificación estudiantil

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CONFORME_PERO_CONFUSO` |
| Fuente | `ResponseFormat`, `ChoiceOption`, `SelectedQuestion`; arquitectura § formato de respuesta |
| Módulos afectados | `frontend/src/pages/ActivityCreatePage.tsx`, tests de copy |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-005 y F-013 para consistencia de extremo a extremo |

**Estado actual:** “Selección · Con opciones justificadas” puede leerse como obligación del estudiante, aunque el rationale es interno y la policy es independiente.

**Estado objetivo y solución exacta:** renombrar ayuda a “Selección entre alternativas” y añadir ayuda contextual: “Cada opción conserva una explicación para el evaluador. La obligación de justificar del estudiante se configura por separado.” No cambiar el valor `CHOICE` ni combinar controles.

**Pruebas necesarias:** test que seleccione `CHOICE + NOT_REQUIRED` y verifique payload; test de texto accesible.

**Criterio de cierre:** el control comunica la independencia y la combinación sigue siendo válida.

**Riesgo:** exponer en la actividad para estudiantes cuál es la alternativa correcta; el texto solo explica configuración, no revela contenido.

### F-004 — Ayuda de `OPEN_SHORT` sugiere límite inexistente

| Campo | Valor |
|---|---|
| Severidad / clasificación | P3 / `CONFORME_PERO_CONFUSO` |
| Fuente | `ResponseFormat.OPEN_SHORT`; arquitectura § formato y constructo |
| Módulos afectados | `ActivityCreatePage.tsx`, copy/tests |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | Ninguna |

**Estado actual:** “Explicación concisa” no dice si “breve” es longitud, tiempo o profundidad.

**Estado objetivo y solución exacta:** mantener “Respuesta abierta breve” y usar ayuda “Respuesta abierta de alcance acotado para el tiempo disponible; no fija por sí sola dificultad ni número de palabras.” No agregar contador o límite.

**Pruebas necesarias:** copy test y verificación de que payload sigue enviando `OPEN_SHORT` sin campos nuevos.

**Criterio de cierre:** la UI no afirma un límite contractual ni equipara formato con demanda cognitiva.

**Riesgo:** introducir una promesa de extensión que el generator no pueda cumplir. Evitar números no contractuales.

### F-005 — `SELECTED` no comunica actor ni alcance

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CONFORME_PERO_CONFUSO` |
| Fuente | `StructuredJustificationPolicy`; Plan E2-13 explica semántica completa, ya contratada |
| Módulos afectados | `ActivityCreatePage.tsx`, `BlueprintPage.tsx`, `AssessmentReviewPage.tsx`, tipos/tests |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-009 y F-012 |

**Estado actual:** el servicio selecciona template IDs determinísticamente; la UI solo dice “Seleccionada” y no muestra los flags resultantes.

**Estado objetivo y solución exacta:** etiqueta “Solo en preguntas seleccionadas por el sistema” con ayuda que indique que el blueprint materializará el alcance. En blueprint, mostrar badge “Justificación estudiantil requerida” en cada template afectado; en review, mostrar el mismo flag por pregunta. No añadir un selector manual de preguntas E2.

**Pruebas necesarias:** `SELECTED` genera al menos un template ID, badges coinciden exactamente con la policy y summary; `NOT_REQUIRED` ninguno; `ALL` todos.

**Criterio de cierre:** usuario puede identificar antes de cada aprobación qué templates/preguntas requieren justificación y por qué.

**Riesgo:** permitir edición granular y abrir E2. E1 solo visualiza la selección determinista.

### F-006 — Edición de actividad no alcanzable desde UI

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CAPACIDAD_AUSENTE` |
| Fuente | MVP §8/§9; backend GET/PATCH actual |
| Módulos afectados | Vista/formulario de actividad, `api/client.ts`, routing, tests |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-002; ETag ya implementado |

**Estado actual:** GET/PATCH y reglas de bloqueo existen; el formulario solo crea.

**Estado objetivo y solución exacta:** reutilizar el mismo formulario en modo edición al entrar desde lista. Obtener config y ETag, enviar PATCH con `If-Match`, mostrar 409/412/428 de forma accionable y deshabilitar edición cuando exista blueprint aprobado. No permitir cambiar tenant, context, source IDs server-owned ni exigir regeneración localizada.

**Pruebas necesarias:** edición antes de aprobación, ETag obsoleto, bloqueo después de aprobación, valores server-owned inmutables, navegación/recovery.

**Criterio de cierre:** actividad draft puede corregirse desde UI y cada cambio crea la versión/auditoría esperada sin sobrescribir un blueprint aprobado.

**Riesgo:** editar después de derivar artifacts/blueprint. El backend sigue siendo autoridad del gate.

### F-007 — Estimación previa de costo no visible

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | Plan E1 riesgos/mitigaciones; arquitectura denial-of-wallet y costos |
| Módulos afectados | API de preflight/actividad, route resolver/cost policy, frontend formulario/confirmación, OpenAPI/tests |
| Cambio contractual | No al schema de dominio v1.1; sí DTO OpenAPI aditivo para una vista derivada |
| Cambio de versión | Sí, revisión minor/patch de API documentada; no versión del bundle canónico |
| Migración | No; cálculo determinista en lectura/preflight |
| Dependencias | F-017–F-019 |

**Estado actual:** max/estimated cost existe en policies/ledger, pero solo es técnico y no se muestra antes de encolar.

**Estado objetivo y solución exacta:** exponer un preflight tenant-scoped que use tamaño declarado, N, rutas aprobadas y policy para devolver rango/estimado, moneda, supuestos, límite máximo y código de no disponibilidad. Mostrarlo antes de “Generar blueprint” y antes de “Ejecutar submission”; requerir solo confirmación normal E1, no un nuevo control pedagógico.

**Pruebas necesarias:** cálculo determinista mock, límite excedido detiene antes de model call, cambio de N/tamaño actualiza estimate, permisos, copy “estimación” no “precio garantizado”, snapshot OpenAPI.

**Criterio de cierre:** ningún job se inicia sin que la UI haya mostrado estimate o un diagnóstico fail-closed de que no puede estimarse.

**Riesgo:** falsa precisión y drift de tarifas. Incluir timestamp/route assumptions y recalibración sin cambiar contratos pedagógicos.

### F-008 — Tokens de capacidad en access logs locales

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCORRECTA` |
| Fuente | `AGENTS.md` reglas de seguridad; arquitectura de objetos privados/capacidades cortas |
| Módulos afectados | `deploy/docker-entrypoint.sh`, configuración de logging Uvicorn/FastAPI, rutas fake, tests de logging |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | Ninguna |

**Estado actual:** las URLs fake ponen JWT en path y Uvicorn registra el request target completo.

**Estado objetivo y solución exacta:** desactivar el access logger sin redacción para estas rutas y emitir logging estructurado propio con route template (`/objects/{token}`), método, status, request ID, byte size e IDs opacos, nunca token, query firmada, student text o filename. Alternativamente mover la capacidad a header solo si no rompe el flujo; no copiarla a payload auditado.

**Pruebas necesarias:** capturar logs de PUT/GET válido e inválido y afirmar ausencia del token completo y sus segmentos; secrets-check; expiración sigue funcionando.

**Criterio de cierre:** buscar el token usado en toda la salida de proceso devuelve cero coincidencias, conservando un evento operativo no sensible.

**Riesgo:** perder observabilidad. Mantener route template, status, hash/size e IDs permitidos.

### F-009 — Blueprint oculta restricciones contractuales de aprobación

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | `QuestionOpportunityTemplate`, `EvidenceVariant`, `AssessmentConstraints`; Prompt P04; E1-05 |
| Módulos afectados | `BlueprintPage.tsx`, `api/types.ts`, estilos, fixtures/tests |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-005 y F-010 |

**Estado actual:** solo foco, observable, operación y tiempo se muestran por template.

**Estado objetivo y solución exacta:** mostrar por oportunidad: difficulty, target minutes, allowed response formats, allowed anchor structures, minimum quality/verification potential y student justification flag. Mostrar por variante un resumen legible de evidence requirement (modalidades, unidades mínimas, confidence/alignment, cross-artifact, course-source). Mostrar constraints globales y criteria IDs. Los campos no autorizados para edición permanecen read-only; no crear selector de dificultad.

**Pruebas necesarias:** fixture con dificultades/formats/flags diversos; todos aparecen; edición no altera campos no editables; P05 warning/fail visible; mobile/table keyboard.

**Criterio de cierre:** un auditor humano puede reconstruir desde la pantalla cada restricción que P06/P07 aplicará al template aprobado.

**Riesgo:** sobrecarga visual. Usar disclosure progresivo sin ocultar datos de aprobación.

### F-010 — Enums y códigos técnicos sin traducción de presentación

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CONFORME_PERO_CONFUSO` |
| Fuente | Arquitectura de UI auditable; enums canónicos deben conservarse |
| Módulos afectados | Catálogo de labels frontend, `StatusBadge`, blueprint/review/diagnostics |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | Ninguna |

**Estado actual:** `APPROVE`, `PASS`, `SOURCE_FIDELITY`, `JUSTIFY_DECISION` y operaciones se muestran mediante reemplazo de `_`.

**Estado objetivo y solución exacta:** crear un catálogo exhaustivo `enum → etiqueta es/en + descripción`, manteniendo el código visible en tooltip/copy técnico para auditoría. Para código desconocido, mostrar fallback seguro y el código, no una traducción inventada.

**Pruebas necesarias:** exhaustiveness TypeScript para enums conocidos, locale es/en, fallback, snapshots visuales.

**Criterio de cierre:** ninguna etiqueta principal expone un enum crudo y el código canónico sigue accesible.

**Riesgo:** traducción que cambie significado. Revisar glosario contra el modelo y Prompt Pack.

### F-011 — Vista autorizada de oportunidades y plan ausente

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CAPACIDAD_AUSENTE` |
| Fuente | MVP §9 `GET /submissions/{submission_id}/opportunities`; E1-06/E1-08 |
| Módulos afectados | `web/app.py`, service/repository read view, DTOs OpenAPI, nueva sección read-only de submission, tests |
| Cambio contractual | No al dominio; sí endpoint OpenAPI aditivo que compone roots existentes |
| Cambio de versión | Sí, minor de API; no bundle v1.1 |
| Migración | No; reutiliza `evidence_maps`, `assessment_plans`, `question_reviews` |
| Dependencias | F-017–F-019 y F-002 |

**Estado actual:** datos existen y alimentan P07, pero no tienen lectura/API/UI humana.

**Estado objetivo y solución exacta:** implementar GET tenant-scoped, paginado si corresponde, que devuelva matches, oportunidades, primary/reserve plan y reviews usando roots canónicos. Añadir vista read-only desde detalle/review. No incluir acciones, regeneración, coverage E2, batch ni edición de plan.

**Pruebas necesarias:** autorización cross-tenant, plan READY y fail-closed, primary/reserve exactos, IDs/evidence refs, response model y snapshot OpenAPI, UI sin acciones E2.

**Criterio de cierre:** el humano puede seguir una pregunta desde evidence map hasta oportunidad y slot del plan usando IDs coincidentes.

**Riesgo:** exponer contenido sensible o prompts. La respuesta contiene solo artefactos de dominio autorizados y diagnostics seguros, nunca prompt raw.

### F-012 — Metadatos de `SelectedQuestion` incompletos en review

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | `SelectedQuestion`, E1-08, arquitectura de revisión humana |
| Módulos afectados | `api/types.ts`, `AssessmentReviewPage.tsx`, fixtures/tests |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-018; F-013; F-009 para lenguaje consistente |

**Estado actual:** response format y difficulty están tipados pero no se muestran; otros campos canónicos ni siquiera están en el tipo frontend.

**Estado objetivo y solución exacta:** proyectar `source_candidate_id`, `opportunity_template_id`, response format, difficulty, estimated minutes, student justification flag, planning score, evidence/course source refs, citations y anchor metadata. `preliminary_guide` puede mostrarse en disclosure de trazabilidad, diferenciada de la guía final P09. No convertir metadata en controles editables.

**Pruebas necesarias:** fixture canónico completo, assert de cada metadata, closed context sin citations, selected/all justification, locales y responsive.

**Criterio de cierre:** ninguna propiedad de `SelectedQuestion` relevante para aprobación se pierde silenciosamente en tipo o presentación; campos sensibles del evaluador se rotulan.

**Riesgo:** duplicar contenido de guía y confundir preliminar/final. Etiquetar origen y mantener P09 como guía vigente.

### F-013 — Alternativas `CHOICE` ausentes en review

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCORRECTA` |
| Fuente | `ChoiceOption` y validator de `SelectedQuestion`; arquitectura § selección |
| Módulos afectados | `api/types.ts`, `AssessmentReviewPage.tsx`, fixtures/tests, eventualmente catálogo de labels |
| Cambio contractual | No; los datos ya están en response/persistencia |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-012 y F-018 |

**Estado actual:** pregunta `CHOICE` se aprueba sin ver opciones; export PDF sí las muestra.

**Estado objetivo y solución exacta:** añadir `choices: ChoiceOption[]` al tipo y renderizar todas las opciones en orden estable. En la vista **solo para evaluador**, marcar best answer y mostrar `evaluator_rationale`; para distractores, mostrar `misconception`. Separar claramente “vista del estudiante” de “información del evaluador”. Nunca incluir best/rationale/misconception en el cuerpo estudiantil del Assessment PDF.

**Pruebas necesarias:** CHOICE + NOT_REQUIRED, SELECTED y ALL; ≥3 opciones; exactamente una best; misconception de cada distractor; non-CHOICE sin options; snapshot PDF no filtra respuesta correcta; autorización.

**Criterio de cierre:** el botón de aprobación no puede presentarse para un CHOICE cuyo conjunto de opciones completo no esté renderizado; el reviewer puede validar cada alternativa y el export estudiantil no revela la clave.

**Riesgo:** fuga de respuesta correcta. El panel de evaluator debe estar tenant/role protegido y no reutilizarse en una futura aplicación al estudiante.

### F-014 — Gate evidence-first basado solo en click

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCORRECTA` |
| Fuente | Plan E1 riesgo “viewer abre la fuente exacta”; MVP §8; arquitectura de grounding |
| Módulos afectados | Viewer/source endpoint, `web/app.py`, workflows/repository audit, `AssessmentReviewPage.tsx`, tests E2E |
| Cambio contractual | No al bundle de dominio: `DomainEvent` admite `evidence.viewed`; sí API transport aditiva para receipt/ack |
| Cambio de versión | Sí, minor de API; no schema canónico v1.1 |
| Migración | No si se usa `audit_events` existente |
| Dependencias | F-017–F-019; exact locator support por parser |

**Estado actual:** `onClick` añade `question_id` a un Set antes de respuesta; un click cubre todos los fragments y el backend de aprobación solo re-verifica bytes/ETag.

**Estado objetivo y solución exacta:** servir una vista controlada por la aplicación que resuelva el locator sobre el objeto sellado. Tras carga exitosa y resolución del fragmento, emitir un receipt corto tenant/user/assessment/question/evidence/locator-hash y registrar `evidence.viewed` en `audit_events`, sin texto estudiantil. La UI consulta receipts y habilita aprobación solo cuando existe uno vigente para **cada fragmento requerido** de la versión/ETag actual. El servicio de aprobación verifica esos events. El mensaje debe decir “Fuentes cargadas y localizadores verificados”, no afirmar comprensión humana.

**Pruebas necesarias:** click con 404/expiración no habilita; múltiples fragments requieren todos; receipt de otro tenant/user/version no sirve; reload conserva estado; cambio de Assessment invalida; logs sin token/texto; PDF/TXT/MD locator; ETag race.

**Criterio de cierre:** no es posible aprobar por UI ni API una versión sin receipts exactos de todos sus fragments, y cada receipt demuestra carga/resolución técnica sin pretender probar lectura cognitiva.

**Riesgo:** convertir telemetría de click en afirmación de revisión. El nombre/copy debe limitarse a evidencia técnica. No añadir tracking invasivo.

### F-015 — Patrón tabs ARIA incompleto

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | ADR de WCAG 2.2 AA; arquitectura RF-15; MVP componentes accesibles |
| Módulos afectados | `AssessmentReviewPage.tsx`, estilos/tests de teclado |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | Ninguna |

**Estado actual:** `tablist` y `tab` existen, pero no su relación con paneles ni navegación de teclado.

**Estado objetivo y solución exacta:** IDs estables, `aria-controls`/`aria-labelledby`, `role=tabpanel`, solo tab activa `tabIndex=0`, flechas/Home/End, foco gestionado y contenido oculto semánticamente. Mantener click y estado React.

**Pruebas necesarias:** keyboard tests izquierda/derecha/Home/End/Tab, roles/relationships, panel único visible, focus visible.

**Criterio de cierre:** el patrón cumple WAI-ARIA tabs y puede operarse sin mouse.

**Riesgo:** mover foco inesperadamente al cargar datos. Solo gestionar foco por interacción del usuario.

### F-016 — Guía visible pierde misconceptions y trazabilidad

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | `ObservableElement`, `GuideLevel`, `GuideDraft`, `EvaluationGuide`; E1-09 |
| Módulos afectados | `api/types.ts`, `AssessmentReviewPage.tsx`, fixtures/tests, renderer si se busca paridad |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-018 |

**Estado actual:** misconceptions existen en el tipo/fixture pero no se renderizan; `source_ids` y `observable_element_ids` faltan en el tipo.

**Estado objetivo y solución exacta:** completar tipos desde el root; mostrar misconceptions como “Errores conceptuales defendibles”, evidence/source refs por observable y los elementos que sustentan cada nivel. Mantener `cannot_infer` separado y prominente. Si un array está vacío, indicarlo sin inventar contenido.

**Pruebas necesarias:** guide completa/vacía, referencias válidas, levels 0–3, source IDs solo en enriched context, paridad UI/PDF, no student text adicional en logs.

**Criterio de cierre:** cada dato canónico de `GuideDraft` tiene representación visible o una decisión explícita/documentada de presentación que no altere significado; los enlaces coinciden con IDs persistidos.

**Riesgo:** presentar misconceptions como diagnóstico del estudiante. Rotularlas como posibles errores que el evaluador puede observar, no como inferencia ocurrida.

### F-017 — Request bodies OpenAPI libres

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCORRECTA` |
| Fuente | `VALIDACION_CONTRATOS(1).md` §§1 y 7; arquitectura OpenAPI generado desde Pydantic |
| Módulos afectados | `web/app.py`, nuevo módulo de DTOs de transporte, imports canónicos, tests OpenAPI/consumer |
| Cambio contractual | Sí en la descripción OpenAPI de transporte; no en semántica del bundle v1.1 |
| Cambio de versión | Sí, actualizar versión de API/OpenAPI; no cambiar `SCHEMA_VERSION` si el wire shape no cambia |
| Migración | No |
| Dependencias | Debe cerrarse junto con F-018/F-019 |

**Estado actual:** login, actividad, uploads, completions, decisiones, submission, run, approvals y export usan `dict[str, Any]`; solo PATCH blueprint referencia `AssessmentBlueprint`.

**Estado objetivo y solución exacta:** sustituir bodies libres por DTOs Pydantic de transporte que **compongan o se generen desde** tipos/enums/fields canónicos; no copiar roots. Separar campos server-owned de comandos del cliente. Conservar wire JSON actual salvo corrección explícita. Aplicar `extra='forbid'`, límites y ejemplos; endpoint handler recibe DTO y lo transforma una sola vez al root canónico.

**Pruebas necesarias:** cada operación mutable tiene `$ref` no genérica; extras/tipos/coerciones inválidos fallan; frontend payloads válidos; provider/consumer; schema refs existen en bundle o DTO; snapshot OpenAPI.

**Criterio de cierre:** ninguna request mutable JSON publicada usa `additionalProperties: true` sin modelo justificado; los campos de dominio remiten a imports canónicos.

**Riesgo:** redefinir `ActivityConfig` manualmente. Generar/derivar comandos o componer el root; añadir un modelo canónico solo mediante proceso de versionado si fuese inevitable.

### F-018 — Responses OpenAPI libres o vacías

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCORRECTA` |
| Fuente | Misma autoridad que F-017; trazabilidad provider/consumer |
| Módulos afectados | `web/app.py`, DTOs/envelopes de response, frontend client/types o generación, tests |
| Cambio contractual | Sí en OpenAPI; el objetivo es describir el wire existente |
| Cambio de versión | Sí, versión API/OpenAPI; no bundle si no cambia dominio |
| Migración | No |
| Dependencias | F-017/F-019; desbloquea F-002/F-011/F-012/F-013/F-016 |

**Estado actual:** responses son objetos libres o vacíos; el frontend castea subsets manuales y pudo perder `choices` sin fallo.

**Estado objetivo y solución exacta:** definir response models/envelopes tipados que aniden/componen roots canónicos (`ActivityConfig`, blueprint view, `Assessment`, `EvaluationGuide`, evidence, job, export). Declarar headers ETag y problem+json. Activar response validation donde no exponga secretos y generar/validar tipos frontend desde la misma OpenAPI o con tests de assignability.

**Pruebas necesarias:** cada 2xx tiene schema concreto, response runtime inválida falla en test, OpenAPI incluye fields CHOICE/guide, problem responses estables, no capability almacenada en idempotency/snapshot.

**Criterio de cierre:** eliminar un campo canónico de una response provoca fallo de provider/consumer o diff del snapshot antes de merge.

**Riesgo:** serializar accidentalmente tenant IDs, secrets o campos internos. Usar allowlist en DTOs y tests de no exposición.

### F-019 — Sin snapshot OpenAPI en CI

| Campo | Valor |
|---|---|
| Severidad / clasificación | P1 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | `VALIDACION_CONTRATOS(1).md` §7, punto 5 |
| Módulos afectados | nuevo fixture/snapshot versionado, test backend, `.github/workflows/ci.yml` si no lo recoge `make test` |
| Cambio contractual | No por sí mismo |
| Cambio de versión | No; cualquier diff futuro sí debe declarar compatibilidad |
| Migración | No |
| Dependencias | F-017/F-018 definen el baseline correcto |

**Estado actual:** OpenAPI se genera localmente, pero no se compara.

**Estado objetivo y solución exacta:** normalizar OpenAPI determinísticamente, escribir baseline revisado después de F-017/F-018 y testear igualdad exacta. El workflow de actualización debe generar a temporal, mostrar diff y reemplazar solo tras revisión, igual que schema canónico.

**Pruebas necesarias:** snapshot exacto, ref crawl sin dangling refs, requests/responses no genéricos, determinismo entre ejecuciones.

**Criterio de cierre:** cualquier cambio de path/schema/header/status hace fallar CI y exige actualizar snapshot con decisión de compatibilidad.

**Riesgo:** snapshot ruidoso por orden/metadata. Canonicalizar JSON, no ignorar campos semánticos.

### F-020 — Foco invisible en controles custom

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `IMPLEMENTACION_INCOMPLETA` |
| Fuente | ADR WCAG 2.2 AA; arquitectura RF-15; MVP pruebas visual/accessibility |
| Módulos afectados | `frontend/src/styles.css`, Activity/Blueprint controls, tests teclado/visual |
| Cambio contractual | No |
| Cambio de versión | No |
| Migración | No |
| Dependencias | F-015 para review completa |

**Estado actual:** checkbox/radio ocultos a 1×1 px reciben foco, pero tarjeta/segmento no dibuja indicador.

**Estado objetivo y solución exacta:** aplicar `label:has(input:focus-visible)` con outline de alto contraste y offset; conservar input accesible mediante técnica visually-hidden estándar, no `display:none`; asegurar indicador en check cards, segmented controls, format cards y decision options. No depender solo de color.

**Pruebas necesarias:** Tab/Shift+Tab por todos los controles, screenshot de foco, contraste, high-contrast mode, Space/Arrow según control, mobile.

**Criterio de cierre:** cada foco interactivo es inequívocamente visible y el orden coincide con DOM.

**Riesgo:** `:has` support. El baseline moderno lo admite; añadir clase/fallback si la matriz de navegadores exige.

### F-021 — Bulk approval mal etiquetado como MVP actual

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CONTRADICCION_DOCUMENTAL` |
| Fuente | Workbook/MVP general frente a Plan E2-14 y `AGENTS.md` |
| Módulos afectados | `04_Matrices_y_Costos_v1.1(1).xlsx`, `06_MVP_Entorno_Experimental(1).md`, matriz de consistencia/changelog si corresponde |
| Cambio contractual | No; semántica futura se conserva |
| Cambio de versión | No de schema; sí revisión documental identificable |
| Migración | No |
| Dependencias | Owner documental; no decisión de producto para E1 |

**Estado actual:** “MVP” puede hacer parecer que E1 incumple por no tener bulk.

**Estado objetivo y solución exacta:** añadir columna/nota de etapa: bulk approval = E2-14, no gate E1. En workbook, mantener componente eventual pero marcar `Stage 2 / inactive in Stage 1`. En MVP, separar “vertical slice E1” de “experimental usable E2”. No eliminar contrato ni endpoint futuro.

**Pruebas necesarias:** revisión cruzada automática/manual de todas las menciones `bulk/masiva`; scope test UI/API E1 sigue sin acción.

**Criterio de cierre:** ninguna fuente llama requisito activo E1 a bulk approval y todas remiten a E2-14.

**Riesgo:** editar XLSX manualmente y dañar formato/fórmulas. Usar workflow de spreadsheet con render y verificación visual.

### F-022 — Tabla MVP mezcla capacidades de etapas

| Campo | Valor |
|---|---|
| Severidad / clasificación | P2 / `CONTRADICCION_DOCUMENTAL` |
| Fuente | `06_MVP_Entorno_Experimental(1).md` §8–§9 frente a Plan E1/E2 y `AGENTS.md` |
| Módulos afectados | `06_MVP_Entorno_Experimental(1).md`, Plan/matriz de consistencia solo para referencias concordantes |
| Cambio contractual | No |
| Cambio de versión | No de schema; revisión documental |
| Migración | No |
| Dependencias | F-021 |

**Estado actual:** una tabla única incluye retry/cancel, batch, granular review, coverage, métricas y feedback junto con funciones E1.

**Estado objetivo y solución exacta:** agregar columna `Etapa/gate` a cada pantalla y endpoint. Marcar con precisión E1, E2 o eventual; distinguir GET read-only E1 de mutaciones E2; añadir regla “un root futuro no activa una capacidad”. Mantener endpoint names y semántica eventual.

**Pruebas necesarias:** revisión de consistencia contra IDs E1-01…E2-15 y `AGENTS.md`; búsqueda automática de historias sin stage.

**Criterio de cierre:** un implementador puede determinar alcance actual de cada fila sin inferencia y no recibe instrucciones incompatibles.

**Riesgo:** rebajar por accidente requisitos transversales de seguridad/accesibilidad. Etiquetar etapa de entrega, no eliminar requisitos arquitectónicos.

## Gate verificable de cierre global

La alineación de producto puede declararse cerrada solo cuando:

1. F-001 a F-022 tienen pruebas y criterios de cierre satisfechos.
2. La matriz de 70 elementos se reaudita y todos quedan `CONFORME`, salvo deuda explícitamente permitida por una nueva decisión registrada.
3. OpenAPI snapshot, schema canónico, fixtures, frontend types y respuestas runtime no divergen.
4. Un flujo fresh-browser `CHOICE + NOT_REQUIRED` muestra alternativas, difficulty, formato, minutos, justification flag, evidencia resuelta y guía completa antes de aprobar.
5. Los exports estudiantiles no revelan best answer/rationale/misconception y no repiten llamadas al modelo.
6. Logs no contienen tokens, texto estudiantil, anchors, nombres ni secretos.
7. PostgreSQL E2E, cloud deployment, Supabase tenant scope y R2 capabilities se validan con identidades/datos sintéticos de auditoría.
8. No aparece ninguna acción batch, retry/cancel, por pregunta, bulk approval, DOCX completo, OCR, LMS, grading o AI detection.

Ninguna remediación propuesta requiere cambiar el significado de `OPEN_SHORT`, añadir selector de dificultad, unir formato y justificación ni abrir un gate E2.
