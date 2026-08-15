# Matriz de consistencia v1.1

**Auditoría:** arquitectura, P01-P11, contratos, Pydantic, JSON Schema, persistencia/API y plan  
**Fecha:** 15-08-2026
**Criterio:** cada fila distingue el objetivo ADR-037 de los contratos y estados legacy retenidos durante el cutover.

## 1. Matriz sistemática

| Elemento | Arquitectura / prompt | Pydantic y JSON Schema | Persistencia / API | Estado |
|---|---|---|---|---|
| `Diagnostic` | fail-closed P01-P11 | root; severidad y códigos estables | embebido en estados/outputs | consistente |
| `ArtifactRef`, `EvidenceUnit`, `SourceLocator` | ingesta e IR con procedencia | roots + union discriminada | artifacts/evidence/viewer | consistente |
| `EvidenceBundle`, `TrustedPromptContext`, `ModelTaskEnvelope` | paquete allowlisted y doble validación | roots exportados | boundary de llamada + hash ledger | consistente |
| `ActivityConfig` | idioma, modalidad, \(N\), tiempo, formatos y justificación; sin profundidad/ops configurables | root actualizado | activities | consistente |
| `ActivitySpecRequest` -> `ActivitySpec` | P01 Sol-medium | roots exportados | snapshot de actividad | consistente |
| `RubricNormalizeRequest` -> `RubricSpec` | P02 Sol-medium | roots exportados | snapshot de rúbrica | consistente |
| `AmbiguityTriageRequest` -> `AmbiguityReport` | P03 Luna-high | roots exportados | decisiones/UI | consistente |
| `BlueprintPolicy`, `AssessmentPlanningPolicy` | restricciones confiables y función de plan; thresholds P06 continuos son legacy | roots exportados | policy snapshots | consistente |
| `BlueprintModelDraft` | output de inferencia P04 con aliases D/V/T locales | dimensiones, variantes, operaciones soportadas y templates sin bookkeeping | sólo frontera provider/compilador | consistente |
| `AssessmentBlueprint` | compilador P04; catálogo independiente de \(N\) -> preflight -> docente | IDs/policy/estado server-owned + semántica compilada | blueprints + preflight + ETag/approve | cutover P05 completo |
| `BlueprintReview` | P05 histórico/inactivo | contrato retenido | review snapshot nullable y legible; no se escribe en flujos nuevos | compatibilidad legacy |
| `EvidenceMappingAliasEnvelope` | payload P06 alias-only, scope local, sin N/IDs canónicos | root exportado; D/V/T/E/A allowlisted | sólo frontera de llamada/hash | consistente |
| `EvidenceMappingModelDraft` | output provider P06: relaciones y soporte categórico | root exportado; sin fields server-owned ni floats gate | transitorio; nunca cache canónico | consistente |
| `EvidenceMapPatch` | materializador P06 | patch canónico con 0..N relaciones, cuatro estados y resumen; READY=mapping completado | StageRun/evidence matches/opportunities; parciales durables | consistente |
| `AssessmentPlan` | planificador determinista sin LLM | exactamente \(N\) primarias + reserva disjunta o diagnóstico específico | assessment_plans | consistente |
| `QuestionAliasEnvelope`, `QuestionModelDraft` | P07 alias-only: redacción/observables/visible E*, sin IDs ni anchor text | roots exportados; provider DTO separado del canónico | transitorios; hash boundary, nunca stage cache | consistente |
| `QuestionBuildRequest` -> `QuestionGenerationResult` | P07 Luna-high; servidor materializa metadata/support/anchor por oportunidad | support completa y anchor visible subset; CLOSED | generated_questions/StageRun canónico | consistente |
| `QuestionReviewRequest` -> `QuestionReviewResult` | P08 inactivo objetivo, aún activo en runtime actual | support y anchor visible separados; contrato retenido | question_reviews activos/legibles | cutover pendiente; adaptación mecánica Fase 5 |
| `ChoiceOption` y justificación | respuesta/rationale de cada opción; misconception por distractor | `CHOICE`; `student_justification_required` | assessment_questions/guides | consistente |
| `GuideBuildRequest` -> `EvaluationGuide` | P09 objetivo después de aprobación; Fase 5 conserva el orden runtime actual | guía completa por assessment/submission | GET assessment guide | cutover pendiente; sin cambio Fase 5 |
| P10 enriquecido | deshabilitado | contrato retenido, no callable | sin activación | consistente |
| `SchemaRepairRequest` -> `SchemaRepairResult` | P11 Luna-minimal, temperatura 0 | repair estructural único | ledger/result | consistente |
| `Assessment` | exactamente \(N\), lineage y resumen de justificación | root + invariantes atómicas | GET/review/approve/export | consistente |
| `QuestionReviewAction` | edición/reemplazo localizado | replacement conserva question ID | actions/audit | consistente |
| `BulkApprovalRequest`, `BulkApprovalRecord` | confirmación explícita, scope/versiones y exclusiones | roots + partición exacta de targets | POST `/assessments:bulk-approve` | consistente |
| `EvaluationGuide` | representación principal en plataforma | root independiente | `evaluation_guides`; PDF/HTML opcional | consistente |
| aviso de autoría/IA/historia | footer/callout fijo de producto | deliberadamente fuera de outputs LLM | componente UI, no export generado | consistente |
| `SubmissionProcessingState` | mapeo -> plan -> generación -> validación -> docente -> guía | cuatro terminales pedagógicos específicos | GET submission | target; migración de estados pendiente |
| `pipeline-authority/1.0.0` | pipelines y autoridad backend/modelo/docente | manifiesto Python inmutable | P05 cutover completo; P08 pendiente | consistente |
| oracle de qualification | `VALID`/`ORACLE_SUSPECT`/`INVALID`/`NOT_APPLICABLE` | clasificador causal | reportes históricos/sintéticos | consistente |
| `JobStatus` | Cloud Run Jobs | root técnico separado | jobs/stage_runs | consistente |
| `ModelRoute` | config aprobada completa | provider/model/snapshot/effort/temp/capabilities/limits | catálogo + ledger | consistente |
| `ModelRouteResolution` | resolvedor determinista | `RESOLVED`, `NEEDS_REVIEW` o `BLOCKED` | reason codes auditables | consistente |
| `ModelCallLedger` | reproducción/costo | route anidada completa | model_calls | consistente |
| `DomainEvent`, `ProblemDetail` | eventos y errores | roots exportados | audit/API | consistente |
| almacenamiento cloud | Supabase para estructura; R2 para raw/JSON grande/exports | no redefine contratos | URLs firmadas temporales | consistente |
| ejecución cloud | FastAPI/React-Vite en Cloud Run Service; Cloud Run Jobs sin Redis | jobs contractuales | API dispara job durable | consistente |

## 2. Invariantes cruzadas verificadas

1. El blueprint no contiene slots ni exige que el tamaño del catálogo sea `question_count`.
2. Una variante solo admite operaciones declaradas en `supported_operations`; P06/P07 no pueden ampliarlas.
3. Un plan `READY` contiene exactamente \(N\) primarias. Un plan fallido no contiene primarias ni reservas.
4. Los únicos fallos de planificación son `INSUFFICIENT_RELEVANT_EVIDENCE`, `INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES`, `EVIDENCE_MAPPING_UNCERTAIN` y `ASSESSMENT_PLAN_INFEASIBLE`.
5. No existen `candidate_multiplier`, lotes de 3-5 candidatos ni `READY_WITH_GAPS`.
6. La reserva se usa para reemplazo localizado; si no se recuperan exactamente \(N\), no se ensambla Assessment utilizable.
7. Para `CHOICE`, existe una mejor respuesta, cada opción tiene rationale y cada distractor una confusión defendible.
8. `NOT_REQUIRED`/`SELECTED`/`ALL` gobierna solo la justificación del estudiante; nunca elimina la evidencia/racionalidad del evaluador.
9. `EvaluationGuide` se asocia a assessment/submission y se consulta en plataforma. Exportar es opcional.
10. La advertencia general sobre autoría/IA/proceso histórico es UI fija y no proviene de P09.
11. Bulk approval exige actor autorizado, confirmación literal y partición exacta entre aprobados/excluidos.
12. Una ruta solo se llama si satisface modalidad, capacidades, privacidad, región, retención, presupuesto, disponibilidad y fallback aprobado.
13. Sol/Terra/Luna pueden recibir imágenes; una imagen sola no cambia proveedor. Gemini 3.6 Flash requiere aprobación por tarea/modalidad/datos o ventaja medida.
14. La API persiste el job antes de disparar Cloud Run Jobs; cerrar el navegador no cancela el trabajo.
15. Backend decide identidad, versiones, hashes, estado, lineage, pertenencia, restricciones, factibilidad, almacenamiento, transiciones y validaciones deterministas.
16. Modelo propone semántica/estructura/redacción/observables; docente resuelve ambigüedad y conserva autoridad académica final.
17. P05 no es etapa activa y P08 no es etapa activa objetivo; P10 está deshabilitado. Contratos/receipts históricos no implican activación.
18. `ORACLE_SUSPECT` hace inconclusa la atribución y prevalece sobre `MODEL_OWNED_*`.
19. Sólo `SYNTHETIC_ONLY_NO_STUDENT_DATA` enumera códigos diagnósticos en claro con hash; la política de datos reales no cambia.
20. P04 no devuelve identidad, workflow, policy materializada ni prueba de factibilidad: el servidor compila `BlueprintModelDraft`, crea los IDs canónicos y ejecuta el preflight/planner exacto después.
21. P06 no devuelve IDs, N, fields de template ni scores continuos: el servidor materializa `EvidenceMappingModelDraft`, conserva las cuatro categorías y crea el patch canónico.
22. `EvidenceMapPatch.READY` afirma mapping completado, no plan factible. Sólo oportunidades `SUFFICIENT` son elegibles y sólo el planner decide exactamente N, cobertura global, tiempo, diversidad, primarias y reservas.
23. `evidence_fit`, `mapping_confidence` y `opportunity_quality` de P06 son `DERIVED_COMPATIBILITY`; ninguna referencia activa en planner/validator/workflow los usa como hard gate o ranking.
24. Provider draft y patch canónico P06 no son intercambiables; scope/blueprint/policy/evidence/alias schema/materializador participan en reuse y bloquean poisoning cross-submission.
25. P07 no devuelve IDs, locators, anchor text, operation, format, difficulty ni time; `QuestionModelDraft` contiene sólo semántica y aliases locales.
26. `QuestionCandidate.evidence_ids` conserva support evidence completa y el anchor visible es un subconjunto reconstruido literalmente por el servidor.
27. Draft y resultado canónico P07 no son intercambiables; support, oportunidad, bundle, policy, scope, schema y materializador invalidan reuse y replay exige igualdad exacta.
28. P08 sigue activo temporalmente y revisa answerability contra support completa sin exigir que sea idéntica al anchor visible; P09 no se mueve y P10 sigue disabled.

## 3. Decisiones cerradas y abiertas

| Decisión | Estado vigente | Evidencia futura |
|---|---|---|
| stack MVP | Cloud Run Service/Jobs + Supabase + R2; sin Redis | revisar solo si telemetría/quotas lo exigen |
| frontend | React/TypeScript/Vite en mismo servicio inicialmente | Vercel Pro opcional si aporta valor |
| rutas retenidas | configuración existente sin cambio; P05/P08 inactivos objetivo | cualquier selección futura exige gate/corpus nuevo |
| harness/qualifications actuales | evidencia histórica no canónica | instrumento futuro independiente |
| Terra | no promovido por la evidencia histórica | decisión humana sobre evidencia nueva gobernada |
| P10 | deshabilitado | ADR, corpus y autorización futuros |
| Gemini 3.6 Flash | alternativa multimodal específica | tarea/modalidad/tenant/datos aprobados |
| formatos posteriores | feature flags por demanda | corpus, parser, viewer y seguridad |
| LMS/uso sumativo | fuera del MVP | piloto, validez y gobernanza |
| escala/comercial | abierto | telemetría y demanda |

## 4. Fuente ejecutable

`models_v1.1.py` es la fuente primaria contractual y `contracts.schema_v1.1.json` se regenera desde `CONTRACT_MODELS`. `src/comprehension_verification/pipeline_authority.py` es la fuente ejecutable de autoridad y orden objetivo, sin sustituir contratos. Los nombres P01-P11 del Prompt Pack coinciden con los request/output roots exportados; P05/P08 se retienen como historia y P10 como contrato deshabilitado. Los fixtures documentales deben validarse en CI junto con las invariantes contextuales descritas en `VALIDACION_CONTRATOS.md`.
