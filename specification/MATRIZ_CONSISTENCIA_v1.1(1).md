# Matriz de consistencia v1.1

**Auditoría:** arquitectura, P01-P11, contratos, Pydantic, JSON Schema, persistencia/API y plan  
**Fecha:** 30-07-2026  
**Criterio:** cada fila describe el diseño vigente después de aplicar las correcciones del texto de revisión.

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
| `BlueprintPolicy`, `AssessmentPlanningPolicy` | restricciones confiables y función de plan | roots exportados | policy snapshots | consistente |
| `AssessmentBlueprint` | P04 Sol-high; catálogo independiente de \(N\) | dimensiones, variantes, operaciones soportadas y templates | blueprints + ETag/approve | consistente |
| `BlueprintReview` | P05 Sol-high | critical FAIL -> REJECT | review snapshot | consistente |
| `EvidenceMapPatch` | P06 Luna-high | claims + variant matches + oportunidades; sin parcial utilizable | evidence claims/matches/opportunities | consistente |
| `AssessmentPlan` | planificador determinista sin LLM | exactamente \(N\) primarias + reserva disjunta o diagnóstico específico | assessment_plans | consistente |
| `QuestionBuildRequest` -> `QuestionGenerationResult` | P07 Luna-high; una pregunta por oportunidad | root request/output; CLOSED por default | generated_questions | consistente |
| `QuestionReviewRequest` -> `QuestionReviewResult` | P08 Luna-high | scores/vetos; una review | question_reviews | consistente |
| `ChoiceOption` y justificación | respuesta/rationale de cada opción; misconception por distractor | `CHOICE`; `student_justification_required` | assessment_questions/guides | consistente |
| `GuideBuildRequest` -> `EvaluationGuide` | P09 Luna-high; sin aviso global generado | guía completa por assessment/submission | GET assessment guide | consistente |
| P10 enriquecido | bake-off OpenAI/Claude Sonnet/Gemini 3.6 Flash | mismo request/result que P07 + citas exactas | feature flag/corpus autorizado | consistente |
| `SchemaRepairRequest` -> `SchemaRepairResult` | P11 Luna-minimal, temperatura 0 | repair estructural único | ledger/result | consistente |
| `Assessment` | exactamente \(N\), lineage y resumen de justificación | root + invariantes atómicas | GET/review/approve/export | consistente |
| `QuestionReviewAction` | edición/reemplazo localizado | replacement conserva question ID | actions/audit | consistente |
| `BulkApprovalRequest`, `BulkApprovalRecord` | confirmación explícita, scope/versiones y exclusiones | roots + partición exacta de targets | POST `/assessments:bulk-approve` | consistente |
| `EvaluationGuide` | representación principal en plataforma | root independiente | `evaluation_guides`; PDF/HTML opcional | consistente |
| aviso de autoría/IA/historia | footer/callout fijo de producto | deliberadamente fuera de outputs LLM | componente UI, no export generado | consistente |
| `SubmissionProcessingState` | mapeo -> plan -> generación -> validación -> guía | cuatro terminales pedagógicos específicos | GET submission | consistente |
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

## 3. Decisiones cerradas y abiertas

| Decisión | Estado vigente | Evidencia futura |
|---|---|---|
| stack MVP | Cloud Run Service/Jobs + Supabase + R2; sin Redis | revisar solo si telemetría/quotas lo exigen |
| frontend | React/TypeScript/Vite en mismo servicio inicialmente | Vercel Pro opcional si aporta valor |
| rutas P01-P09/P11 | matriz Sol/Luna explícita | evals pueden promover snapshot o Terra |
| Terra | no default | ventaja medida frente a Luna-high |
| P10 | bake-off abierto | grounding, citas, abstención, costo y política |
| Gemini 3.6 Flash | alternativa multimodal específica | tarea/modalidad/tenant/datos aprobados |
| formatos posteriores | feature flags por demanda | corpus, parser, viewer y seguridad |
| LMS/uso sumativo | fuera del MVP | piloto, validez y gobernanza |
| escala/comercial | abierto | telemetría y demanda |

## 4. Fuente ejecutable

`models_v1.1.py` es la fuente primaria y `contracts.schema_v1.1.json` se regeneró desde `CONTRACT_MODELS`. Los nombres P01-P11 del Prompt Pack coinciden con los request/output roots exportados. Los fixtures documentales deben validarse en CI junto con las invariantes contextuales descritas en `VALIDACION_CONTRATOS.md`.
