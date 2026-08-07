# Trazabilidad UI ↔ contrato — Etapa 1

## Alcance y convención

Este documento traza los mismos 70 elementos contabilizados en [STAGE1_PRODUCT_CONFORMANCE_AUDIT.md](STAGE1_PRODUCT_CONFORMANCE_AUDIT.md). La cadena usada es:

`pantalla/control → tipo frontend → request/response API → modelo Pydantic → persistencia → servicio/workflow/prompt → validación → output/visualización`

En las tablas:

- `dict` significa el schema OpenAPI libre realmente publicado (`type: object`, `additionalProperties: true`), aunque el servicio pueda validar después con Pydantic.
- `m.X` significa un modelo importado desde `comprehension_verification.contracts.models`, no una copia local.
- `S` es validación estructural Pydantic/JSON Schema; `C` es validación contextual del servicio/validator.
- `—` en UI o endpoint significa capacidad ausente o control correctamente no expuesto.
- Los IDs `F-001` a `F-022` remiten a [PRODUCT_ALIGNMENT_REMEDIATION_SPEC.md](PRODUCT_ALIGNMENT_REMEDIATION_SPEC.md).

## Mapa compartido de persistencia

| Agregado | Persistencia implementada | Forma canónica conservada |
|---|---|---|
| Identidad/workspace | `workspaces`, `users`, `workspace_roles`, cookie de sesión firmada | actor, workspace y rol |
| Actividad | `activities.config`, `activity_specs`, `rubric_specs`, `ambiguity_reports`, `policy_decisions` | `ActivityConfig`, `ActivitySpec`, `RubricSpec`, `AmbiguityReport`, `PolicyDecision` |
| Blueprint | `blueprints.data`, versión, estado, ETag derivado, actor/fecha | `AssessmentBlueprint` y review P05 |
| Artefactos | `artifacts` + objeto privado/sellado | metadatos, hash, tamaño, MIME, rol y object key |
| Submission | `submissions` | identidad, estado de dominio, stage y progreso |
| Evidencia/plan | `evidence_units`, `evidence_maps`, `assessment_plans` | `EvidenceUnit`, `EvidenceMap`, `AssessmentPlan` |
| Preguntas | `generated_questions`, `question_reviews`, `assessments.data` | resultados P07/P08 y `Assessment` completo |
| Guía | `evaluation_guides.data` | `EvaluationGuide` separado |
| Ejecución | `jobs`, `stage_runs`, `model_calls` | job técnico, stages, `ModelCallLedger`/snapshots |
| Salidas | `exports.artifacts` + objetos privados | PDF/JSON derivados y hashes |
| Auditoría/concurrencia | `audit_events`, `idempotency_keys` | actor, agregado, evento, payload no sensible; replay descriptor |

## Acceso, sesión y navegación

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-001 | `LoginPage`: “Acceso por invitación”, correo institucional | `Session`; `email: string` | `POST /session/login`, `dict`; cloud intercambia bearer en `POST /session/exchange` | Actor + `users/workspace_roles`; cookie firmada | `LocalAuth` o Supabase adapter → `AuthProvider`; sin prompt | S: email/headers; C: allowlist/JWT issuer, audience, membership | Rutas privadas usan `PrivateRoute`. Cumple E1-01 y MVP login. | `CONFORME` |
| TC-002 | `LoginPage`: “entorno experimental”; no texto de privacidad | Sin campo | Sin endpoint | No aplica | Copy consumido por usuario | Revisión visual | MVP §8 exige aviso experimental **y privacidad**. Solo existe el primero. | `IMPLEMENTACION_INCOMPLETA` / P2 / F-001 |
| TC-003 | `AppShell`: “Workspace experimental” | `Session.workspace_id`, `workspace_name`, `roles` | Todas las rutas dependen de `current_actor`/`mutating_actor` | Tenant en todas las filas relevantes | Auth → repositorio `scoped` → UI | S: actor; C: tenant coincide y rol autoriza | No se observó lectura cross-tenant; pruebas negativas pasan. | `CONFORME` |
| TC-004 | Botón “Cerrar sesión” | `logout(): Promise<void>` | `POST /session/logout`; sin body | Cookie revocada | Auth service → redirect `/login` | C: CSRF/idempotencia en mutación | Sesión termina y UI vuelve a login. | `CONFORME` |
| TC-005 | Sidebar: solo “Nueva actividad”; ruta raíz redirige a `/activities/new` | No existe `listActivities`; `ActivityResource` omite recuperación operable | Backend sí tiene `GET /activities` | `activities`, con `submission_id` derivado | Repositorio produce lista; frontend no la consume | C: tenant scope ya implementado | E1-11 exige poder cerrar/reabrir sin perder recorrido; MVP §8 pide lista/estado. Sin URL conocida no hay recuperación UI. | `CAPACIDAD_AUSENTE` / P1 / F-002 |

## Configuración de actividad

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-006 | `ActivityCreatePage`: “Título” | `ActivityCreateInput.title` | `POST /activities`, `dict` → `model_validate` | `m.ActivityConfig.title` → `activities.config` | UI → service → P01/P03/P04 | S: 1–300; C: ID/tenant server-owned | Valor se conserva sin cambio semántico. | `CONFORME` |
| TC-007 | “Idioma de salida” | `output_language: string`; opciones `es-CL`, `es`, `en` | Mismo POST, `dict` | `ActivityConfig.output_language` | P01-P09 consumen idioma autorizado | S: 2–35 | Locale elegido llega a prompts/outputs. | `CONFORME` |
| TC-008 | “Modalidad” | `AssessmentModality` | Mismo POST, `dict` | `ActivityConfig.assessment_modality` | Policy P04/P06/P07 | S: enum | `WRITTEN`/`ORAL`/`MIXED` no se confunden con formato. | `CONFORME` |
| TC-009 | “Número de preguntas” | `question_count: number` | Mismo POST, `dict` | `ActivityConfig.question_count`; luego `BlueprintPolicy`, `AssessmentConstraints`, `AssessmentPlan` | P04 produce catálogo independiente de N; planner P06 selecciona N | S: 1–20; C: plan exacto o fail-closed | Flujo sintético con N=1 produjo exactamente una pregunta. | `CONFORME` |
| TC-010 | “Tiempo objetivo … min” | `target_total_minutes: number` | Mismo POST, `dict` | `ActivityConfig` → policy/constraints/plan snapshots | P04/P06/P07 | S: 3–120; C: suma/factibilidad | Tres minutos se conservaron; no se usa como dificultad. | `CONFORME` |
| TC-011 | Tarjetas de “Formatos de respuesta” | `ResponseFormat[]`: cinco enums | Mismo POST, `dict` | `ActivityConfig.allowed_response_formats` → blueprint templates/plan/questions | P04 restringe catálogo; P06/P07 instancian | S: lista no vacía/única; C: pregunta usa formato permitido | Los formatos son medios, no operaciones ni policy de justificación. | `CONFORME` |
| TC-012 | Tarjeta `CHOICE`: “Selección”, ayuda “Con opciones justificadas” | Valor `CHOICE` | Mismo POST | `ResponseFormat.CHOICE`; `ChoiceOption` y `student_justification_required` son campos distintos | P07 crea opciones; P09 crea guía | S: ≥3, una best answer, misconception por distractor; C: policy de justificación independiente | `CHOICE + NOT_REQUIRED` fue válido. El copy sugiere obligación estudiantil inexistente. | `CONFORME_PERO_CONFUSO` / P2 / F-003 |
| TC-013 | Tarjeta `OPEN_SHORT`: “Respuesta abierta breve”, “Explicación concisa” | Valor `OPEN_SHORT` | Mismo POST | `ResponseFormat.OPEN_SHORT` | P04/P07 | S: enum; no hay min/max de respuesta estudiantil | Es formato operacional, no límite de caracteres ni profundidad. Ayuda ambigua. | `CONFORME_PERO_CONFUSO` / P3 / F-004 |
| TC-014 | Radios “No requerida / Seleccionada / En todas” | `StructuredJustificationMode` | Mismo POST | `ActivityConfig.structured_justification_mode` → `StructuredJustificationPolicy` | Service construye policy; P04/P06/P07/P09 consumen | S: SELECTED exige template IDs; otros modos los prohíben; C: flags coinciden | Default `NOT_REQUIRED`; control desacoplado correctamente de formatos. | `CONFORME` |
| TC-015 | Radio “Seleccionada” sin ayuda ni alcance | Enum `SELECTED`; frontend no expone IDs | Mismo POST | Policy contiene `selected_opportunity_template_ids`; template/question contiene flag | Service elige template estable; P04 lo conserva; UI posterior no lo muestra | S/C anteriores | Funciona, pero “seleccionada” no dice que el sistema materializa templates ni cuáles. | `CONFORME_PERO_CONFUSO` / P2 / F-005 |
| TC-016 | No existe selector de dificultad/profundidad/operación | No existe en `ActivityCreateInput` | No se envía | Correcto: no es campo de `ActivityConfig`; `QuestionOpportunityTemplate.difficulty` se genera después | P04 deriva catálogo; P08 estima/revisa | S: DifficultyBand en template/question; C: policy/evidencia/tiempo | E1-02 dice que profundidad y operaciones derivan del sistema/evidencia. | `CONFORME` |
| TC-017 | “Formatos de entrega”: PDF/TXT/MD | `allowed_artifact_media_types: string[]` | `POST /activities`, luego upload | `ActivityConfig.allowed_artifact_media_types`; `artifacts.media_type` | Parser registry consume MIME | S: lista 1–50; C: allowlist, sniffing y rol | Coincide con E1; DOCX/OCR/medios complejos no activos. | `CONFORME` |
| TC-018 | No hay pantalla “Editar actividad” | Cliente solo `createActivity/getActivity` | Backend `GET/PATCH /activities/{id}`, PATCH `dict`, `If-Match` | `activities.config`, versión/ETag | Service `edit_activity`; P01-P05 consumirían nueva config | S: `ActivityConfig`; C: no blueprint aprobado, ETag | Capacidad de backend no es alcanzable desde UI pese a MVP §8/§9. | `CAPACIDAD_AUSENTE` / P2 / F-006 |
| TC-019 | No hay estimación previa en formulario ni confirmación | Sin tipo/campo de estimate | Sin endpoint/preflight visible | `model_calls` guarda estimado/real después; policies contienen máximos | Route resolver/ledger producen costo; UI no consume | C: presupuestos y límites runtime | Plan E1, riesgos: estimación previa visible. Falta proyección antes de iniciar. | `IMPLEMENTACION_INCOMPLETA` / P2 / F-007 |

## Artefactos de actividad y seguridad de capacidades

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-020 | Drop field “Consigna” obligatorio | `File`, rol `ASSIGNMENT_PROMPT` | `POST /activities/{id}/artifacts/uploads` `dict`; PUT firmado; `:complete` `dict` | `artifacts` y objeto privado | Object store → P01/P03/P04 | S: metadata; C: tamaño, MIME, hash, rol, objeto sellado | No se inicia blueprint sin consigna completa. | `CONFORME` |
| TC-021 | Drop field “Rúbrica opcional” | `File | null`, rol `RUBRIC` | Mismas rutas | `artifacts`; `rubric_specs` solo si existe | Parser/P02 | Mismos guardas | Omitir rúbrica es válido. | `CONFORME` |
| TC-022 | Upload directo y complete | `UploadSession`, `ArtifactResource` | POST → PUT capability corta → POST complete | Hash/tamaño/MIME/key en `artifacts`; bytes en R2/memory | Adapter produce artifact sellado; parsers solo consumen sellado | S: tipos; C: tamaño real, hash, MIME, tenant, no ejecución | Carga sintética completó y re-verificó integridad. | `CONFORME` |
| TC-023 | Sin UI; observado en consola de servidor local | Token no aparece en estado React, pero está en URL | `PUT /object-uploads/{token}` y `GET /objects/{token}` fake | No se persiste token; Uvicorn sí imprime request target | Uvicorn access logger consume URL completa | No existe filtro/redacción | Regla de seguridad: logs nunca contienen secretos. Token firmado quedó visible en access log local. | `IMPLEMENTACION_INCORRECTA` / P1 / F-008 |

## Ambigüedades y blueprint

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-024 | Estado “Generando blueprint” y revisión P05 | `StartedOperation`, `JobStatus`, `BlueprintView` | `POST /activities/{id}/blueprints:generate` `dict`; GET job/blueprint | activity specs, rubric specs, ambiguity report, blueprint, stage runs/model calls | P01 actividad, P02 rúbrica, P03 ambigüedad, P04 blueprint, P05 review | S: outputs canónicos; C: registry, authorized evidence, checks P05 | Pipeline explícito y reproducible. | `CONFORME` |
| TC-025 | `AmbiguityReview`: “Selecciona una interpretación” | `AmbiguityView`, `PolicyDecision` | GET ambiguity; `POST /decisions` `dict` | `ambiguity_reports`, `policy_decisions`, audit event | P03 produce; docente decide; workflow reanuda/reusa | S: 2–3 opciones y recomendación válida; C: issue/option/actor | Ninguna opción bloqueante se decide automáticamente. | `CONFORME` |
| TC-026 | `BlueprintReview`: catálogo, dimensiones, variantes, operaciones, foco, observable, tiempo | `AssessmentBlueprint`, `BlueprintOpportunity` | GET latest/version | `blueprints.data` | P04 produce; P05 revisa; P06 consume aprobado | S: root completo; C: catálogo, operaciones soportadas y checks | Elementos exigidos literalmente por E1-05 están visibles. | `CONFORME` |
| TC-027 | Misma tabla, solo columnas catálogo/operación/tiempo | FE **sí** tipa `difficulty`, formats, justification; omite otros campos del template/variant | GET devuelve blueprint completo | `QuestionOpportunityTemplate`, `EvidenceRequirement`, `AssessmentConstraints` completos | P04 produce; P05 y planner consumen; UI descarta visualmente | S: difficulty, anchors, formats, quality, flag; C: P05 factibilidad | Docente aprueba sin ver restricciones que definen el constructo. | `IMPLEMENTACION_INCOMPLETA` / P1 / F-009 |
| TC-028 | Botones “Editar blueprint” / “Guardar nueva versión” | `AssessmentBlueprint` completo | `PATCH /blueprints/{version}`; único body OpenAPI con `$ref` canónica; If-Match | Nueva fila/version de `blueprints` | UI → service `edit_blueprint` → P05 re-review | S: `m.AssessmentBlueprint`; C: campos editables, ETag, identidad | Versionamiento no sobrescribe snapshot aprobado. | `CONFORME` |
| TC-029 | “Aprobar blueprint” | `BlueprintView.etag` | `POST .../{version}:approve`, `dict` vacío + If-Match | estado/actor/fecha + `blueprint.approved` | Service congela; submission gate consume versión | S: blueprint; C: review READY, ETag, audit | Aprobación humana obligatoria y durable. | `CONFORME` |
| TC-030 | Chips `APPROVE`, `PASS · SOURCE FIDELITY`, operaciones inglesas | strings/enums sin catálogo de labels | GET blueprint/review | Valores canónicos intactos | P04/P05 producen; `replaceAll` consume | S/C no afectados | Datos correctos, presentación técnica confusa para usuario de producto. | `CONFORME_PERO_CONFUSO` / P2 / F-010 |

## Submission, ejecución y recuperación

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-031 | `SubmissionStartPage`: subject ref y una entrega | `SubmissionResource` | `POST /activities/{id}/submissions`, `dict` | `submissions`; relación con actividad | Service create; pipeline consume | S: string; C: blueprint aprobado y máximo una submission | Segunda submission se rechaza: gate E1 exacto. | `CONFORME` |
| TC-032 | Drop field de submission | `File` | POST upload, PUT firmado, POST complete | `artifacts` rol `SUBMISSION` | Parser seguro consume objeto sellado | S/C de ingestión | Un PDF/TXT/MD sintético se cargó correctamente. | `CONFORME` |
| TC-033 | Acción de ejecutar y timeline P06-P09 | `StartedOperation`, `JobStatus`, `SubmissionResource` | `POST /submissions/{id}:run`, `dict`; GET job/submission | evidence, map, plan, generated questions, reviews, assessment, guide | P06 mapping/plan, P07 question, P08 review, P09 guide | S: cada output; C: autorización, grounding, plan, review | Flujo completo produjo Assessment/guía. | `CONFORME` |
| TC-034 | Paneles “Estado técnico” y “Estado de dominio” | `TechnicalJobState` y `SubmissionDomainState` separados | GET job y submission | `jobs` vs `submissions` | Worker/repository producen; UI consulta | S: enums; C: transiciones válidas | No se equipara job durable con agregado de dominio. | `CONFORME` |
| TC-035 | Copy “El job no depende del navegador” | Polling depende de URL, job no | Cloud: API encola y Cloud Run ejecuta | `jobs/stage_runs` PostgreSQL | Job runner/worker | C: stage key idempotente; un claim | Arquitectura y tests prueban independencia; no se hizo recorrido cloud real. | `CONFORME` |
| TC-036 | Estados/diagnostics de insuficiencia y fallo | `SubmissionDomainState`, `Diagnostic[]` | GET submission/job | estados + diagnostics seguros | Validators/worker producen; UI muestra | S: state machines; C: no Assessment parcial | Casos negativos y planning tests pasan. | `CONFORME` |
| TC-037 | No hay pantalla de matches, oportunidades, plan o reserves | No hay tipos/vista/cliente dedicados | Falta `GET /submissions/{id}/opportunities` | Datos existen en `evidence_maps`, `assessment_plans`, reviews | P06 produce; P07 consume; humano no consume | S/C existen internamente | MVP §9 especifica read surface autorizada; no exige acciones E2. | `CAPACIDAD_AUSENTE` / P2 / F-011 |

## Assessment evidence-first y aprobación

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-038 | Tabs “Evaluación / Guía estructurada” | `AssessmentBundle`, `EvaluationGuide` | GET assessment; GET guide | `assessments.data`, `evaluation_guides.data` | Assembler/P09 producen; UI/export consumen | S: `Assessment` y `EvaluationGuide`; C: IDs/estado | Objetos separados en API/persistencia/vistas. | `CONFORME` |
| TC-039 | `QuestionEvidenceCard`: texto, dimension, variant, operación, ancla/localizador, scores/diagnostics | Subset de `SelectedQuestion`, `QuestionReview`, `EvidenceUnit` | GET assessment/evidence | assessment, question_reviews, evidence_units | P07/P08 producen; review UI consume | S: roots; C: evidence IDs/localizers/review | Cumple el mínimo literal de E1-08. | `CONFORME` |
| TC-040 | La tarjeta no muestra formato/dificultad/minutos/justificación/planning | FE tipa algunos, pero omite `student_justification_required`, choices, citations, preliminary guide y refs | GET devuelve objeto completo como `dict` | `SelectedQuestion` completo en snapshot | P07/P08/assembler producen; frontend estrecha/ignora | S: modelo canónico; C: policy/formato/dificultad | Aprobación humana no ve restricciones relevantes ya disponibles. | `IMPLEMENTACION_INCOMPLETA` / P1 / F-012 |
| TC-041 | Pregunta `CHOICE`: UI muestra solo enunciado | `SelectedQuestion` frontend no declara `choices` | GET assessment response libre | `SelectedQuestion.choices`: 3 opciones, una best, rationales y misconceptions | P07 crea; P08 valida; export sí consume; UI no | S: validator CHOICE; C: alternativa/misconception/grounding | Flujo real confirmó datos íntegros en DB y ausencia total en pantalla antes de aprobar. | `IMPLEMENTACION_INCORRECTA` / P1 / F-013 |
| TC-042 | Link “Abrir fuente exacta” | `EvidenceUnit.view_url` | GET evidence emite URL firmada; GET objeto fake o R2 | objeto sellado y evidence locator | `evidence_view` firma el hash exacto; navegador consume | C: tenant, expiración, object key/hash; aprobación re-verifica bytes | Fuente exacta y localizador se conservan. | `CONFORME` |
| TC-043 | Footer “Todas las fuentes fueron abiertas” | `openedQuestions: Set<question_id>` solo memoria | El click no llama a receipt; approve `POST ...:approve` lleva body vacío | Solo `assessment.approved`; no `evidence.viewed` | `onClick` habilita; service no conoce apertura | C actual: integridad de evidencia, no revisión efectiva | Se habilita antes de carga, con un click por pregunta aunque haya varios fragmentos, y se pierde al recargar. | `IMPLEMENTACION_INCORRECTA` / P1 / F-014 |
| TC-044 | Botón “Aprobar Assessment” | `bundle.etag` | `POST /assessments/{id}:approve`, `dict` vacío + If-Match | snapshot aprobado, actor/fecha, audit event | Service congela; exports consumen | S: objetos existentes; C: ETag, review, bytes de evidencia | Aprobación completa individual conforme; no bulk. | `CONFORME` |
| TC-045 | No hay aceptar/rechazar/editar/regenerar por pregunta | No existen handlers | No existen endpoints E2 | Roots futuros no activados | — | — | Plan E2-04/E2-05 los difiere. | `CONFORME` |
| TC-046 | Botones con `role=tab` | Estado `tab`; sin ids/roving | No aplica | No aplica | React consume estado | DOM/accessibility review | Faltan `aria-controls`, `tabpanel`, `tabIndex`, Home/End/flechas. Contradice componentes accesibles/WCAG objetivo. | `IMPLEMENTACION_INCOMPLETA` / P2 / F-015 |

## Guía y exports

| ID | Pantalla, componente, etiqueta/ayuda | Tipo/campo frontend | API y request root real | Modelo y persistencia | Productor, consumidor y prompt | Validación S/C | Resultado real, criterio y diferencia | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-047 | `GuideView`: propósito, observables, alternativas, niveles, no permite inferir | `EvaluationGuide`, `GuideItem` | `GET /assessments/{id}/guide` | `evaluation_guides.data` | P09 produce; UI consume | S: READY exige items únicos; C: question IDs/evidence | Contenido básico estructurado consultable. | `CONFORME` |
| TC-048 | Guía no muestra misconceptions ni trazas completas | FE declara misconceptions pero no los renderiza; no declara `source_ids` ni `observable_element_ids` | GET entrega snapshot completo como `dict` | `GuideDraft` completo | P09 produce; renderer PDF/UI consumen parcialmente | S: `ObservableElement`, `GuideLevel`, `GuideDraft`; C: refs a pregunta/evidencia | UI pierde límites pedagógicos y enlaces verificables. | `IMPLEMENTACION_INCOMPLETA` / P1 / F-016 |
| TC-049 | Botón “JSON canónico” tras aprobar | `ExportKind.CANONICAL_JSON` | `POST /assessments/{id}/exports`, `dict` | `exports` + objeto JSON | Export service serializa snapshots | C: Assessment aprobado, tenant, URL corta | Descarga exitosa y reproducible. | `CONFORME` |
| TC-050 | “Evaluación PDF” | `ASSESSMENT_PDF` | Mismo endpoint | `exports.artifacts.assessment_pdf` | Jinja/WeasyPrint o renderer de prueba | Escape + snapshot aprobado | PDF representativo mostró ancla, enunciado y opciones CHOICE sin clipping. | `CONFORME` |
| TC-051 | “Guía PDF” | `GUIDE_PDF` | Mismo endpoint | `exports.artifacts.guide_pdf` | Renderer de guía | Snapshot separado | PDF representativo legible y A4. | `CONFORME` |
| TC-052 | Copy “sin repetir llamadas al modelo” | No campo adicional | Export endpoint no encola P01-P09 | Solo exports | Service renderiza `Assessment`/`EvaluationGuide` existentes | C: no model call nuevo | Ledger no cambia por export. | `CONFORME` |
| TC-053 | Fragmento hostil visible en PDF | String escapado | No request distinto | Snapshot contiene texto hostil | Template renderer consume | Autoescape/CSP; PDF sin JS | `<script>alert('dato')</script>` apareció como texto literal. | `CONFORME` |

## Contratos, OpenAPI, validación e infraestructura

| ID | Superficie | Tipo/campo | API/root | Modelo y persistencia | Productor/consumidor | Validación | Resultado real y criterio | Clase / sev. / solución |
|---|---|---|---|---|---|---|---|---|
| TC-054 | Frontera de dominio | Imports dinámicos canónicos | Interna | `comprehension_verification.contracts.models` | Todos los workflows | Identity/checks de roots | No se encontraron clases Pydantic duplicadas. | `CONFORME` |
| TC-055 | Bundle JSON Schema | 46 roots/112 defs | Gate de contrato | Archivo generado desde modelos | CI/tests/fixtures consumen | Regeneración temporal y diff | Hash y contenido exactos; 8 fixtures pasan. | `CONFORME` |
| TC-056 | OpenAPI request bodies | Casi todos `dict[str, Any]` | 16 mutables genéricos; solo PATCH blueprint usa `$ref` | Runtime luego valida algunos roots | FastAPI genera schema insuficiente; frontend mantiene tipos manuales | No hay provider schema fuerte | Contradice `VALIDACION_CONTRATOS`: importar modelos o DTOs que los compongan. | `IMPLEMENTACION_INCORRECTA` / P1 / F-017 |
| TC-057 | OpenAPI responses | `dict[str, Any]` o `Response` sin model | Schemas libres/vacíos | Snapshots canónicos reales no se publican | Backend produce más que OpenAPI; frontend hace casts | No response validation OpenAPI | Consumers no pueden detectar pérdida de `choices`/guía. | `IMPLEMENTACION_INCORRECTA` / P1 / F-018 |
| TC-058 | Gate de OpenAPI | No fixture/snapshot | `/api/openapi.json` solo local | — | CI no compara | `rg` no encontró test OpenAPI | `VALIDACION_CONTRATOS` §7 exige consumer/provider tests y snapshot. | `IMPLEMENTACION_INCOMPLETA` / P1 / F-019 |
| TC-059 | Validación runtime | `model_validate` canónico | Servicios FastAPI/worker | Snapshots solo después de validar | API/adapters → workflows | S: Pydantic estricto | Actividad, blueprint, evidence, plan, assessment y guía válidos. | `CONFORME` |
| TC-060 | Validadores por frontera | Structural vs contextual | Interna | Diagnósticos/códigos | P01-P09, planner, assembler; P11 no repara | S y C separados | Tests de evidence inventada, tiempo alterado y plan parcial fallan cerrado. | `CONFORME` |
| TC-061 | Planificador | `AssessmentPlanningPolicy/Plan` | Interna | `assessment_plans` | P06/planner produce; P07 consume | Exact N, thresholds, reservas, no parcial | Tests y flujo real conformes. | `CONFORME` |
| TC-062 | Model gateway | Registry P01-P11 | Interna/provider adapter | `model_calls`, snapshots | Resolver determinista | Capabilities, privacy, budget, schema | Mock estable; P10 registrado pero deshabilitado. | `CONFORME` |
| TC-063 | Modo cloud E1 | Settings tipados | Startup guard | Config, no snapshot de estudiante | Runtime/entrypoint | Fail-before-start | Cloud exige mock, P10 false, Supabase, R2, Jobs. | `CONFORME` |
| TC-064 | Tenant/autorización | `Actor` | Depends en todas las rutas | Tenant columns/object keys | Auth/repository | `scoped`, roles, 404/403 | Tests de principal IDs y web pasan. | `CONFORME` |
| TC-065 | Liveness/readiness | — | `/api/health`, `/api/readiness` | Alembic/PostgreSQL metadata | Service probes | DB URL explícita y revisión de migración | Health no depende de DB; readiness sí. | `CONFORME` |
| TC-066 | Worker/IaC | — | Cloud Run invocation | jobs/stages; Terraform state | Worker reclama ≤1; Terraform fija imagen digest | `max_retries=0`, digest `@sha256` | 8 deployment tests y `terraform validate` pasan. | `CONFORME` |
| TC-067 | Checkbox/radio/media cards | Inputs absolutos 1×1, opacity 0; no `:focus-visible` | No aplica | No aplica | Navegador/React | Revisión manual de teclado/CSS | El control recibe foco, pero el usuario no ve dónde. | `IMPLEMENTACION_INCOMPLETA` / P2 / F-020 |
| TC-068 | Workbook “Review and bulk approval” y MVP general | Roots de bulk existen en contrato futuro | Endpoint no activo | Sin tablas E1 activas | — | — | Plan E2-14 y `AGENTS.md` difieren bulk. Contradicción terminológica resuelta: no abrir E2. | `CONTRADICCION_DOCUMENTAL` / P2 / F-021 |
| TC-069 | MVP §8/§9 mezcla lote, retry/cancel, actions, métricas, feedback | Roots futuros | Endpoints no activos | Tablas/roots futuros no implican capacidad activa | — | — | Plan E1/E2 separa esas historias. Falta etiquetar stage en el documento general. | `CONTRADICCION_DOCUMENTAL` / P2 / F-022 |
| TC-070 | Control de scope | No UI E2 | No endpoints batch/retry/cancel/action/bulk | No operación activa | — | Guards/tests | Ninguna capacidad prohibida por el gate está activa. | `CONFORME` |

## Trazas críticas expandidas

### `CHOICE` sin justificación del estudiante

```text
Tarjeta “Selección”
→ ActivityCreateInput.allowed_response_formats = ["CHOICE"]
→ POST /activities (OpenAPI: dict; runtime: ActivityConfig.model_validate)
→ activities.config.allowed_response_formats
→ BlueprintPolicy.allowed_response_formats
→ P04 QuestionOpportunityTemplate.allowed_response_formats
→ P06 oportunidad/plan
→ P07 SelectedQuestion(response_format=CHOICE, choices=[...], student_justification_required=false)
→ validator SelectedQuestion: ≥3 opciones, exactamente una best answer,
  rationale siempre presente y misconception en distractores
→ assessments.data
→ GET /submissions/{id}/assessment
→ SelectedQuestion frontend pierde choices
→ QuestionEvidenceCard no las renderiza
```

La policy paralela sigue:

```text
Radio “No requerida”
→ ActivityConfig.structured_justification_mode = NOT_REQUIRED
→ StructuredJustificationPolicy(mode=NOT_REQUIRED, selected_ids=[])
→ template.student_justification_required = false
→ question.student_justification_required = false
→ StructuredJustificationSummary
```

No hay control redundante. Hay dos decisiones independientes y un label que las confunde.

### Dificultad derivada

```text
Sin selector en ActivityConfig
→ P04 deriva QuestionOpportunityTemplate.difficulty
→ P06 instancia oportunidad y planifica con restricciones/tiempo/evidencia
→ P07 genera candidato
→ P08 produce estimated_difficulty y valida demanda
→ assembler conserva SelectedQuestion.difficulty
→ assessments.data / export JSON-PDF
→ frontend recibe difficulty pero no la muestra
```

En el flujo sintético, el blueprint persistió `LOW`, `MEDIUM`, `HIGH`, `LOW` y la pregunta seleccionada quedó `MEDIUM`. La ausencia está solo en la proyección UI, no en contrato/pipeline/persistencia.

### Aprobación evidence-first

```text
EvidenceUnit(locator + artifact_hash)
→ evidence_view firma el objeto sellado exacto
→ GET /evidence entrega view_url temporal
→ click de <a target="_blank">
→ openedQuestions.add(question_id) antes de verificar response/load/localizer
→ botón se habilita
→ POST /assessments/{id}:approve con body vacío
→ service revalida bytes y ETag, pero no una apertura por fragmento
→ assessment.approved
```

La integridad técnica de la fuente es conforme; la afirmación de que el humano abrió/resolvió todas las fuentes no está demostrada.

## Límites de esta trazabilidad

Las rutas cloud, Supabase, R2 y Cloud Run se trazaron desde código, IaC y tests, no mediante acceso a servicios externos. Los siete tests PostgreSQL y el renderer WeasyPrint nativo del host no se ejecutaron; esas verificaciones pendientes se declaran en el informe principal y no se sustituyen por inferencias.
