# Anexo B - Contratos, schemas e invariantes

**Versión de bundle:** `assessment-contracts/1.2.0`
**Marker wire runtime retenido:** `schema_version=1.1.0`
**Fuente primaria:** `models_v1.1.py` (Pydantic v2.13+)  
**Artefacto generado:** `contracts.schema_v1.1.json` (JSON Schema Draft 2020-12)  
**Regla:** el JSON Schema no se edita manualmente; se regenera desde Pydantic y CI compara bytes canónicos.

**Estado ADR-037 / Fase 4:** `EvidenceMapPatch` sigue siendo el contrato
canónico P06 y se añaden dos roots de frontera, `EvidenceMappingAliasEnvelope`
y `EvidenceMappingModelDraft`. El bundle generado contiene 56 roots, 155
`$defs`, 306 refs y 8 fixtures. P05/P08 permanecen para lectura histórica;
P05 no es alcanzable en ejecuciones nuevas y P08 sigue activo hasta su cutover.
P10 permanece deshabilitado. La presencia de un root no confiere autoridad ni
autoriza invocación.

---

## 1. Reglas de compatibilidad

1. Todo root de dominio persistido o intercambiado que evoluciona independientemente incluye `schema_version`. Objetos embebidos y `ProblemDetail` pueden heredar la versión del root contenedor.
2. Cambios aditivos opcionales son minor; cambiar significado, enum, obligatoriedad o invariante es major.
3. Productores escriben una versión; consumidores admiten la actual y, durante migración, una versión anterior.
4. Eventos son inmutables. Una corrección crea un nuevo evento/versión, no modifica el anterior.
5. IDs son opacos, locales al dominio y nunca contienen nombres, correos o matrícula.
6. Hashes usan `sha256:<64 hex>` sobre bytes originales o representación canónica declarada.
7. Fechas se serializan ISO 8601 UTC.
8. Scores 0-1 expresan una señal/umbral, no una probabilidad calibrada salvo documentación explícita. Los scores legacy materializados en P06 no son señales activas: son proyecciones derivadas de compatibilidad y no gobiernan elegibilidad o ranking.
9. `extra="forbid"`: un campo desconocido falla, evitando aceptar silenciosamente cambios de modelos.
10. Ningún contrato implica ejecutar o dereferenciar contenido. Un `path` o `locator` es dato validado por el servicio propietario.

## 2. Raíces exportadas

### 2.1 Dominio, ejecución y API

| Root | Productor | Consumidor | Uso |
|---|---|---|---|
| `ArtifactRef` | ingesta | parsing/auditoría | manifiesto seguro |
| `EvidenceUnit` | parser/indexer | evidence/generator/viewer | unidad canónica con procedencia |
| `CoursePassage` | parser de corpus | P10/validator | pasaje autorizado y localizable |
| `SourceCitation` | P10/ensamblador | validator/viewer | cita de corpus en pregunta/guía |
| `EvidenceBundle` | retrieval determinista | P06-P10 | paquete allowlisted de una submission |
| `ActivityConfig` | API/UI | activity workflow | parámetros experimentales confiables |
| `ActivitySpec` | P01 | P02-P04 | requisitos normalizados |
| `RubricSpec` | P02 | P03/P04 | criterios atómicos; opcional a nivel de actividad |
| `AmbiguityReport` | P03 | UI/docente | decisiones pendientes |
| `PolicyDecision` | UI/docente | P04/P05/auditoría | resolución versionada |
| `BlueprintPolicy` | UI/reglas | P04/P05 | restricciones confiables del blueprint |
| `AssessmentPlanningPolicy` | config | planificador | prioridad/penalizaciones server-owned, constraints y tamaño de reserva; mínimos continuos legacy no consumen scores P06 |
| `BlueprintModelDraft` | proveedor P04 | compilador P04 | propuesta semántica plana con aliases locales D/V/T; sin identidad, workflow ni policy materializada |
| `AssessmentBlueprint` | compilador P04 | preflight/aprobación docente/student workflows | catálogo canónico comparable de dimensiones, variantes y oportunidades |
| `BlueprintReview` | P05 histórico | lectura/UI de compatibilidad | checks y recomendación legados |
| `EvidenceMappingAliasEnvelope` | compilador de input P06 | proveedor P06 | namespace cerrado D/V/T/E/A, semántica mínima de rutas/evidencia y scope hash; sin IDs canónicos ni N |
| `EvidenceMappingModelDraft` | proveedor P06 | materializador P06 | relaciones locales con soporte categórico y abstención; sin fields server-owned |
| `EvidenceMapPatch` | materializador P06 | evidence service/planificador | mapping canónico, estados locales y resumen durable; `READY` significa mapping completado, no plan factible |
| `AssessmentPlan` | planificador determinista | P07/assembler | exactamente \(N\) oportunidades primarias y reserva disjunta |
| `QuestionGenerationPolicy` | config | P07/P10 | límites de una generación localizada |
| `QuestionValidationPolicy` | config | validaciones/P08 histórico | umbrales retenidos |
| `QuestionGenerationResult` | P07/P10 | validaciones/revisión docente | una pregunta generada o solicitud de reemplazo |
| `QuestionReviewResult` | P08 histórico | lectura/compatibilidad | scores, decisión o abstención legados |
| `EvaluationGuide` | P09 posterior a aprobación | plataforma/evaluador | guía estructurada asociada a assessment/submission |
| `Assessment` | planificador/generador/guide | review/export | objeto canónico de salida, siempre con exactamente \(N\) preguntas cuando es utilizable |
| `QuestionReviewAction` | UI docente | revision service/auditoría | aceptar, editar, rechazar o regenerar |
| `BulkApprovalRequest` | UI autorizada | approval service | selección y confirmación explícita |
| `BulkApprovalRecord` | approval service | auditoría/UI | targets aprobados y excepciones para revisión individual |
| `SubmissionProcessingState` | workflow | API/UI | estado de dominio visible |
| `JobStatus` | worker/cola | API/UI | estado técnico de una ejecución |
| `ModelRoute` | catálogo de políticas | model gateway | proveedor, snapshot, modelo, esfuerzo, temperatura, capacidades y límites aprobados |
| `ModelRouteResolution` | resolvedor determinista | model gateway/auditoría | ruta resuelta o `NEEDS_REVIEW`/`BLOCKED` con códigos de razón |
| `ModelCallLedger` | model gateway | observabilidad/FinOps | lineage y costo sin texto |
| `DomainEvent` | dominio/workflow | auditoría/outbox futuro | envelope interno versionado; payload tipado por `event_type` en el registry |
| `ProblemDetail` | API | clientes | error RFC 9457 extendido |
| `Diagnostic` | cualquier etapa | UI/ops | código estable y acción |

### 2.2 Frontera código-modelo

| Root | Prompt | Output del proveedor | Output de etapa |
|---|---|---|---|
| `ActivitySpecRequest` | P01 | `ActivitySpec` | `ActivitySpec` |
| `RubricNormalizeRequest` | P02 | `RubricSpec` | `RubricSpec` |
| `AmbiguityTriageRequest` | P03 | `AmbiguityReport` | `AmbiguityReport` |
| `BlueprintBuildRequest` | P04 | `BlueprintModelDraft` | `AssessmentBlueprint` compilado y con preflight determinista |
| `BlueprintReviewRequest` | P05 | `BlueprintReview` | `BlueprintReview` |
| `EvidenceMapRequest` | P06 | `EvidenceMappingModelDraft` sobre payload `EvidenceMappingAliasEnvelope` | `EvidenceMapPatch` materializado |
| `QuestionBuildRequest` | P07/P10 | `QuestionGenerationResult` | `QuestionGenerationResult` |
| `QuestionReviewRequest` | P08 | `QuestionReviewResult` | `QuestionReviewResult` |
| `GuideBuildRequest` | P09 | `EvaluationGuide` | `EvaluationGuide` |
| `SchemaRepairRequest` | P11 | `SchemaRepairResult` | `SchemaRepairResult` |

`ModelTaskEnvelope` envuelve una llamada y `TrustedPromptContext` declara las
allowlists. Para P01-P05/P07-P11, `payload` se vuelve a validar contra el input
root de la fila. P04 proyecta `BlueprintBuildRequest` a su draft boundary; P06
proyecta `EvidenceMapRequest` al root alias-only
`EvidenceMappingAliasEnvelope`. En P04,
`provider_output_schema_name=BlueprintModelDraft` limita la inferencia y
`output_schema_name=AssessmentBlueprint` conserva el objeto canónico. En P06,
`provider_output_schema_name=EvidenceMappingModelDraft` y
`output_schema_name=EvidenceMapPatch` separan igualmente wire y etapa.

La identidad P06 liga prompt, schema wire exacto, versión/hash del alias
envelope, `p06-evidence-materializer/1.0.0`, blueprint/policy/evidence hashes y
scope de submission. El materializador resuelve aliases y copia desde el
blueprint identidad, operación, foco, observable, dificultad, minutos,
formatos, anchors, justificación y prioridad. Los estados
`SUFFICIENT`/`PARTIAL`/`INSUFFICIENT`/`UNCERTAIN` y el resumen se preservan.
Los floats `evidence_fit`, `mapping_confidence` y `opportunity_quality` siguen
en el IR para lectura histórica, pero nuevos patches los derivan server-side y
ningún gate activo los consume.

Los campos `claims` y sus IDs permanecen en `EvidenceMapPatch` para lectura de
snapshots 1.1. El materializador 1.0 no pide al proveedor recrearlos: emite
`claims=[]` y conserva grounding/diagnóstico útil por relación en
`support_description`, `support_type`, `semantic_uncertainty` y
`abstention_reason`.

`BlueprintPolicy.max_variants_per_dimension=6` y
`max_templates_per_variant=12` son defaults operacionales provisionales,
configurables y server-owned. No son invariantes pedagógicos universales. La
policy conserva `schema_version`/`policy_id` y su valor completo participa en el
input y hash de reuse; el proveedor sólo debe respetar el cap recibido y nunca
devolverlo como decisión propia.

Las filas P05/P08 de esta frontera documentan contratos retenidos. La frontera
activa ya salta de P04 a preflight/aprobación docente. El salto P07 a
validaciones/revisión docente y la ubicación final de P09 siguen pendientes.

## 3. Invariantes críticas

### Evidencia

- `EvidenceUnit` debe tener `content_text` o `structured_content`.
- Evidencia de rol `SUBMISSION` requiere `submission_id`.
- `artifact_hash`, `normalized_hash` y localizador son obligatorios en `EvidenceUnit`; `parser_id`/`parser_version` son opcionales en el manifiesto `ArtifactRef` previo al parsing y contextualmente obligatorios cuando se publica evidencia.
- Bounding boxes y líneas deben estar ordenados.
- Un ID citado se resuelve dentro del mismo `tenant_id` y versión de submission en la capa de repositorio.
- La base no permite update de contenido normalizado: una nueva extracción crea nueva versión.

### Blueprint

- IDs de dimensión, variante y `opportunity_template_id` son únicos dentro del blueprint;
- cada oportunidad usa una operación incluida en `supported_operations` de su variante;
- el catálogo es independiente de `question_count`: un blueprint `READY`/`APPROVED` no exige una oportunidad por pregunta;
- la política `SELECTED` de justificación referencia únicamente templates existentes;
- `approved_by` y `approved_at` aparecen juntos.
- aprobar requiere ETag/`If-Match` para evitar edición concurrente.
- el preflight determinista debe pasar antes de ofrecer aprobación docente;
- `BlueprintReview` conserva sus invariantes para artefactos históricos, pero su recomendación no es autoridad canónica.

### Mapeo, plan y pregunta

- una oportunidad concreta pertenece a la misma submission, dimensión y variante que su mapeo;
- las operaciones soportadas por variante son permitidas, no preferencias ampliables;
- un `AssessmentPlan READY` contiene exactamente `question_count` primarias, sin duplicados, y una reserva disjunta pequeña;
- cualquiera de los cuatro fallos de planificación deja primarias/reserva vacías: no existe evaluación parcial;
- los evidence IDs del ancla son subconjunto de los IDs de la pregunta;
- selección solo existe con `CHOICE`, al menos tres opciones y una mejor respuesta;
- toda opción conserva `evaluator_rationale` y todo distractor una `misconception` defendible;
- `student_justification_required` se resuelve desde la política `NOT_REQUIRED`, `SELECTED` o `ALL`;
- pertenencia de IDs y literalidad/transformación del ancla se validan fuera de Pydantic contra el evidence store;
- una pregunta con fallo crítico no puede llegar a revisión/aprobación docente; se intenta sólo un reemplazo localizado desde reserva;
- `QuestionGenerationResult.context_mode=CLOSED` prohíbe `course_source_ids` y `citations`;
- en contexto enriquecido, la pregunta mantiene igualdad exacta entre `course_source_ids` y los `source_id` citados.

### Guía y reparación

- `EvaluationGuide` referencia preguntas aprobadas, no reescribe pregunta/ancla y no duplica IDs;
- la guía se persiste con `guide_id`, `assessment_id` y `submission_id`; PDF/HTML es vista opcional;
- los avisos globales de autoría/IA/proceso histórico pertenecen a UI fija, no a P09 ni al objeto generado;
- `SchemaRepairResult.REPAIRED` exige `repaired_output`, que luego valida contra el root objetivo;
- `UNREPAIRABLE` exige `repaired_output=null`; P11 nunca repara grounding ni añade evidencia.

### Assessment

- `READY`/`NEEDS_REVIEW`/`APPROVED`/`PUBLISHED` requiere exactamente `question_count` preguntas;
- `question_id` es único dentro del Assessment;
- una `SelectedQuestion` repite las reglas de ancla, opciones y equivalencia exacta entre `course_source_ids` y citas; una edición humana no puede eludirlas;
- `QuestionReviewAction.EDIT` exige replacement y conserva el mismo `question_id`;
- `context_mode=CLOSED` prohíbe citas de curso también en el objeto ensamblado;
- una pregunta seleccionada conserva `source_candidate_id`, oportunidad/template, variante, evidencia, guía preliminar y score de planificación;
- el resumen de justificación coincide exactamente con los booleanos de las preguntas y activa el aviso de alcance limitado cuando corresponde;
- `lineage` fija hashes, parsers, prompts, schemas, modelos, política, planner y renderer;
- renderizados son artefactos derivados y nunca la fuente de verdad;
- una edición docente crea `AssessmentRevision`/nueva versión en persistencia, aunque la vista de este contrato muestre el estado vigente.

### Aprobación masiva

- requiere actor autorizado, lista concreta de assessment/version y confirmación literal;
- `approved_targets` y `excluded_targets` son disjuntos y juntos particionan exactamente lo solicitado;
- cada exclusión incluye código, mensaje y `requires_individual_review=true`;
- se auditan actor, fecha, alcance y versiones; una excepción nunca se aprueba silenciosamente.

### Resolución de modelos

- una ruta es proveedor + snapshot + modelo + `reasoning_effort` + temperatura + límites y capacidades;
- antes de llamar, las modalidades requeridas deben ser subconjunto de las capacidades de la ruta;
- privacidad, región, retención y fallback se comprueban antes de la llamada;
- si no existe ruta aprobada compatible, `ModelRouteResolution` es `NEEDS_REVIEW` o `BLOCKED`, nunca una elección improvisada.

## 4. Localizadores

El union discriminado `SourceLocator` evita un campo genérico ambiguo:

| `kind` | Campos mínimos | Formatos |
|---|---|---|
| `PAGE_BBOX` | página, `[x0,y0,x1,y1]` | PDF |
| `DOCUMENT_PATH` | párrafo/heading/tabla/fila/columna | DOCX/ODT |
| `SLIDE_SHAPE` | slide, shape, notes | PPTX |
| `SHEET_RANGE` | sheet y A1 | XLSX/CSV normalizado |
| `CODE_SPAN` | path, líneas, columnas/símbolo | código |
| `NOTEBOOK_CELL` | path, cell ID/index/output | IPYNB |
| `IMAGE_REGION` | path, bbox y espacio | imágenes/crops |

El viewer resuelve el localizador contra `artifact_hash`; si el hash no coincide, devuelve `IR_PROVENANCE_GAP`.

## 5. Ejemplo de evidencia

<!-- contract-fixture: EvidenceUnit -->
```json
{
  "schema_version": "1.1.0",
  "evidence_id": "ev_a73b",
  "tenant_id": "tnt_demo",
  "submission_id": "sub_0194",
  "artifact_id": "art_027",
  "artifact_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "source_role": "SUBMISSION",
  "modality": "CODE_SPAN",
  "locator": {
    "kind": "CODE_SPAN",
    "path": "src/cache.py",
    "start_line": 41,
    "end_line": 58,
    "symbol": "get_or_compute"
  },
  "content_text": "def get_or_compute(...): ...",
  "structured_content": {"ast_kind": "function_definition"},
  "language": "python",
  "extraction_confidence": 0.99,
  "ocr_used": false,
  "sensitive_labels": [],
  "relations": [{
    "relation": "DEPENDS_ON",
    "target_evidence_id": "ev_a71c",
    "confidence": 0.94
  }],
  "normalized_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

## 6. Ejemplo de oportunidad de catálogo

<!-- contract-fixture: QuestionOpportunityTemplate -->
```json
{
  "opportunity_template_id": "opt_arch_consequence",
  "cognitive_operation": "PREDICT_LOCAL_CONSEQUENCE",
  "focus": "La dependencia entre el orden de consulta y la invalidación del caché.",
  "observable": "Explica una consecuencia local sustentada en el fragmento y conserva la dirección causal.",
  "difficulty": "MEDIUM",
  "target_minutes": 3,
  "allowed_anchor_structures": ["CODE_CONTEXT", "PAIRED_FRAGMENTS"],
  "allowed_response_formats": ["OPEN_SHORT", "STRUCTURED_BULLETS", "ORAL_EQUIVALENT"],
  "verification_potential": 0.88,
  "minimum_quality": 0.78,
  "student_justification_required": false
}
```

## 7. Ejemplo de plan fail-closed

<!-- contract-fixture: AssessmentPlan -->
```json
{
  "schema_version": "1.1.0",
  "plan_id": "plan_0194",
  "submission_id": "sub_0194",
  "blueprint_id": "blueprint_demo",
  "blueprint_version": 3,
  "status": "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
  "question_count": 5,
  "selected_opportunity_ids": [],
  "reserve_opportunity_ids": [],
  "estimated_total_minutes": 0,
  "diagnostics": [{
    "code": "INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES",
    "severity": "ERROR",
    "message": "La evidencia pertinente solo admite tres focos sustancialmente distintos para cinco preguntas.",
    "evidence_ids": ["ev_a73b"],
    "source_ids": [],
    "retryable": false,
    "details": {"required_question_count": 5, "distinct_opportunity_count": 3}
  }]
}
```

## 8. Problem Details

Respuesta API:

```http
HTTP/1.1 422 Unprocessable Content
Content-Type: application/problem+json
```

<!-- contract-fixture: ProblemDetail -->
```json
{
  "type": "https://errors.product.example/assignment-ambiguous",
  "title": "La actividad requiere una decisión docente",
  "status": 422,
  "detail": "La rúbrica y la consigna asignan alcances incompatibles al criterio de análisis.",
  "instance": "/v1/activities/act_91/blueprints:generate",
  "code": "ASSIGNMENT_AMBIGUOUS",
  "trace_id": "tr_01j...",
  "retryable": false,
  "fields": {"rubric": ["criterion_analysis"]}
}
```

Los mensajes pueden localizarse; `code` y `type` son estables. Nunca se devuelve stack trace, texto completo del estudiante o detalle de proveedor al cliente.

## 9. Idempotencia

Para operaciones mutables:

```text
Idempotency-Key = client generated UUID
operation_fingerprint = sha256(tenant + route + canonical body + relevant version)
```

La API conserva key/fingerprint/response por 24 h como mínimo. Reusar una key con fingerprint distinto devuelve `409 IDEMPOTENCY_KEY_REUSED`. Los workflows además usan una clave de etapa:

```text
stage_key = sha256(stage_name + canonical_inputs + policy_hash + component_version)
```

## 10. Persistencia sugerida

### Entorno experimental

- `users` y una fila de `workspaces/tenants` experimental para conservar la frontera futura sin implementar administración institucional;
- `activities`, `activity_artifacts`, `activity_specs`, `rubric_specs`, `blueprints`, `policy_decisions`;
- `submissions`, `artifacts`, `evidence_units`, `evidence_claims`, `evidence_variant_matches`, `question_opportunities`;
- `assessment_plans`, `generated_questions`, `question_reviews`, `assessments`, `assessment_questions`, `evaluation_guides`, `question_review_actions`;
- `bulk_approval_records` y `bulk_approval_exclusions`;
- `jobs`, `stage_runs`, `model_calls`, `exports`, `feedback_events`.

Se permite JSONB para snapshots contractuales y columnas relacionales solo para búsquedas/joins críticos. Los datos estructurados y estados de job viven en Supabase PostgreSQL; archivos brutos, JSON grandes y exportaciones viven en Cloudflare R2 privado. `tenant_id` se conserva desde el primer prototipo, pero membresías complejas y despliegues dedicados no son requisitos del experimento.

`question_reviews` y los snapshots `BlueprintReview` existentes no se eliminan
durante el cutover: pasan a lectura histórica/compatibilidad. Cambiar su
escritura o las transiciones asociadas requiere una migración posterior.

### Arquitectura institucional futura

Añade `memberships`, políticas por tenant, `assessment_revisions` completas, `retention_actions`, outbox/event bus, `lms_installations`, `lms_cursors`, `external_mappings`, RLS exhaustiva y aislamiento avanzado. Estas tablas no deben anticiparse si no tienen un consumidor experimental.

## 11. Eventos

Envelope común validable como `DomainEvent`:

<!-- contract-fixture: DomainEvent -->
```json
{
  "schema_version": "1.1.0",
  "event_id": "evt_01jabc",
  "event_type": "assessment_plan.ready",
  "event_version": "1.1.0",
  "occurred_at": "2026-07-18T14:00:00Z",
  "tenant_id": "tnt_demo",
  "aggregate_id": "assess_01jabc",
  "aggregate_version": 3,
  "actor": {"kind": "SERVICE", "id": "svc_planner"},
  "correlation_id": "job_01jabc",
  "causation_id": "evt_01iabc",
  "payload": {
    "submission_id": "sub_0194",
    "question_count": 5,
    "status": "READY"
  }
}
```

En el entorno experimental, `audit_events` puede ser una tabla transaccional y Cloud Run Jobs consume filas/ejecuciones sin Redis ni broker de eventos. El outbox y consumidores deduplicables se mantienen como patrón objetivo para cuando aparezca un consumidor externo real.

## 12. Validaciones que no pertenecen a JSON Schema

Estas comprobaciones son autoridad del backend. Un output de modelo o una
decisión académica no puede declarar que se cumplen sin ejecución server-side.

Se ejecutan con acceso a repositorios/políticas:

- pertenencia a tenant y autorización del actor;
- existencia y versión de IDs;
- substring/crop/tabla derivable del original;
- hashes y localizadores;
- fuentes permitidas por `context_mode`;
- capacidades, modalidades, presupuesto, proveedor/región/retención y fallback aprobado;
- score de oportunidades y redundancia de evidencia/foco;
- planificación determinista de exactamente \(N\) oportunidades y reserva;
- reglas de publicación y revisión humana;
- permiso, elegibilidad y partición de una aprobación masiva;
- borrado/retención y legal hold.

Separar validación estructural de validación contextual evita dar falsa seguridad a partir de un JSON bien formado.

Los juicios del harness usan los estados ejecutables `VALID`,
`ORACLE_SUSPECT`, `INVALID` y `NOT_APPLICABLE`. Esta taxonomía pertenece al
instrumento de evaluación, no se incorpora al bundle contractual del producto
en esta iteración. `ORACLE_SUSPECT` bloquea cualquier atribución automática
`MODEL_OWNED_*`.

## 13. Pruebas de contrato

- round-trip de cada root y golden JSON;
- rechazo de campos extra, enums desconocidos, IDs/Hash inválidos;
- property tests para bbox/líneas, catálogo/operaciones, plan atómico y choices;
- fuzzing de strings Unicode, largos y payloads de injection;
- consumidor N-1 contra productor N durante migración;
- OpenAPI snapshot diff en CI;
- validación del bundle JSON Schema con un validador independiente;
- extracción y validación automática de fixtures concretos del prompt pack;
- comparación de roots, propiedades, `required`, enums y `$refs` entre Pydantic y el bundle generado;
- pruebas de RLS/tenant para cada repository method;
- replay de eventos duplicados/desordenados.

## 14. Generación y compatibilidad de v1.1

Comando canónico desde el directorio de entregables:

```bash
python models_v1.1.py --schema contracts.schema_v1.1.json
```

La generación usa `pydantic.json_schema.models_json_schema` sobre `CONTRACT_MODELS`. El bundle agrega únicamente metadatos (`$schema`, `$id`, `version`, `roots`) y las `$defs` emitidas por Pydantic. `context_mode` en `QuestionGenerationResult` tiene default `CLOSED`; un consumidor enriquecido debe exigir explícitamente `COURSE_ENRICHED` y validar sus citas. La corrección del blueprint/plan elimina slots, batches masivos y salidas parciales antes de implementación productiva, por lo que no se migran objetos aprobados como si fueran equivalentes: se regeneran desde sus fuentes versionadas.

La guía ejecutable completa, comandos de CI y fixtures se encuentran en `VALIDACION_CONTRATOS.md`.
