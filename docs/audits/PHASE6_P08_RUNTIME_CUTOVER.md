# Auditoría Fase 6 — cutover runtime P08

Baseline auditado: `61d1cbd84418d348dd1dd7e28cb67d2a9ca4751c`.

## Resultado

`ACTIVE PRODUCT P08 PROVIDER INVOCATIONS = 0`.

El flujo activo es `P06 -> planner -> P07 -> validación determinista ->
exactamente N -> ASSEMBLE -> P09 -> workflow docente`. P09 conserva el orden
de Fase 5 y su relocación pertenece a Fase 7. P10 permanece disabled.

La búsqueda global incluyó `P08_QUESTION_REVIEW_V1`, `QuestionReviewRequest`,
`QuestionReviewResult`, `QuestionReview`, `ReviewDecision`, scores/confidence,
`critical_failure_codes`, `QuestionValidationPolicy` y sus thresholds,
`validate_review_result`, `QuestionReviewRow`, persistencia/transacciones,
observabilidad, `p08_decision_diagnostics`, `QUESTION_REVIEW`,
`VALIDATING_QUESTIONS`, resume/retry, reservas, gateway/routes/prompt/mocks,
coste/ledger/cache, harness/qualification, API/UI, exports, teacher actions y
métricas.

## Clasificación del grafo del baseline

### TO_REMOVE_FROM_ACTIVE_RUNTIME — retirado

- `web/workflows.py`: request/invocación P08, `validate_review_result`, espera
  de ACCEPT, uso de REJECT/ESCALATE, dict de reviews y escritura acoplada.
- `web/stage2.py`: P08 posterior a edit/regenerate y dependencia de ACCEPT.
- `web/repository.py`: obligación de persistir generated question + review en
  la misma operación para flujos nuevos.
- coste/autorización/observabilidad: N llamadas P08, prompt set activo y evento
  `question.review.decision_observed` requerido por ejecuciones nuevas.
- API/UI: expectativa de review, confidence, scores y recommendation para una
  pregunta nueva; label `Reglas y scores P08`.

Cada arista anterior quedó eliminada. La persistencia nueva usa
`save_generated_question`; el evento activo expresa sólo validación objetiva y
reserva consumida. El hard guard devuelve `P08_ACTIVE_RUNTIME_RETIRED` antes de
gateway/trusted context/adapter/transporte.

### ACTIVE_RUNTIME — conceptos legítimos, sin autoridad P08

- `src/comprehension_verification/web/workflows.py`: hard guard, validación
  determinista `QUESTION_VALIDATE`, reserva finita, exact-N y alias legado
  `QUESTION_REVIEW` sólo como resume floor.
- `src/comprehension_verification/web/stage2.py`: `QuestionReviewAction*` es el
  workflow **docente**, no P08; edit/regenerate revalidan P07 y luego conservan
  P09 en el orden actual. `QUESTION_REVIEW` sólo aparece en allowed resume
  legacy.
- `frontend/src/components/StatusBadge.tsx`,
  `frontend/src/components/JobControlPanel.test.tsx`,
  `frontend/src/pages/SubmissionPage.tsx`: `VALIDATING_QUESTIONS` significa
  validación determinista activa.
- `frontend/src/pages/AssessmentReviewPage.tsx`: nuevas preguntas funcionan con
  `reviews=[]`; una row antigua se muestra sólo como “Review histórico P08 ·
  compatibilidad no autoritativa”.
- exports/assembly/coverage/lineage no consumen score, confidence, decision,
  critical code ni row P08. `Assessment` sigue `NEEDS_REVIEW`.

### HISTORICAL_COMPATIBILITY — conservar

- Contratos/schema/client: `specification/models_v1.1(1).py`,
  `specification/contracts.schema_v1.1(1).json`,
  `frontend/src/api/generated.ts`.
- Catálogo directo/replay: `src/comprehension_verification/model_gateway/`
  (`gateway.py`, `mock_factory.py`, `openai_routes.py`, `prompt_text.py`,
  `registry.py`), `src/comprehension_verification/validation.py`,
  `src/comprehension_verification/observability.py`,
  `src/comprehension_verification/rehearsal.py`,
  `src/comprehension_verification/semantic_harness.py`,
  `src/comprehension_verification/cli.py` y `scripts/run_openai_evals.py`.
  Son superficies offline/históricas directas, no el runtime web del producto.
- `src/comprehension_verification/question_generation.py` permanece byte por
  byte en la frontera P07 de Fase 5 (`341316e12724…`). Su mensaje diagnóstico
  legacy que nombra P08 es prosa congelada, no una arista de ejecución,
  autorización, score o aceptación; cambiarlo rompería el boundary/replay P07.
- Persistencia/lectura: `src/comprehension_verification/web/repository.py`
  conserva `QuestionReviewRow`, `review_rows` y
  `save_generated_question_and_review` para snapshots/replay anteriores.
- Policy: `src/comprehension_verification/provider_authorization.py` mantiene
  metadata de ruta pero clasifica P08 en `historical_non_callable`;
  `src/comprehension_verification/pipeline_authority.py` lo clasifica inactive.

### TEST_HISTORICAL — conservar

- Tests directos de contrato/gateway/adapter/harness:
  `tests/test_dynamic_model_gateway.py`, `tests/test_model_gateway.py`,
  `tests/test_openai_adapter.py`, `tests/test_openai_eval_harness.py`,
  `tests/test_semantic_harness.py`, `tests/test_evaluation_reporting.py` y
  `tests/test_validation.py`.
- Regresión y cutover: `tests/test_stage1_backend.py`,
  `tests/test_stage1_web.py`, `tests/test_stage2_repository.py`,
  `tests/test_stage2_question_action_retry.py`,
  `tests/test_synthetic_provider_gate.py`, `tests/test_pipeline_authority.py` y
  `tests/test_phase6_p08_cutover.py`.
- UI/e2e: `frontend/src/pages/Stage1Views.test.tsx` prueba la etiqueta
  histórica cuando sí existe una row P08; `frontend/e2e/stage2-mocked.spec.ts`
  usa `QUESTION_VALIDATE` para el estado vigente.
- Fixtures congelados: `tests/fixtures/openai_evals/v1/synthetic_cases.json`,
  `tests/fixtures/openai_evals/v2/product_rehearsal.json`,
  `tests/fixtures/openai_evals/v3/frozen_product_boundary.json`,
  `tests/fixtures/openai_evals/v3/semantic_qualification_pack.json` y
  `tests/fixtures/openapi/stage1-v1.json`.

Los tests históricos pueden invocar directamente el gateway/mock P08 para
probar lectura y replay. Ninguno atraviesa `_gateway_stage` productivo salvo el
test que demuestra el hard guard.

### DOCUMENTATION_HISTORICAL — conservar y etiquetar

- `docs/DECISIONS_IMPLEMENTATION.md`, `docs/IMPLEMENTATION_STATUS.md`,
  `docs/OPENAI_COST_BUDGETS.md`, `docs/OPENAI_PROVIDER_SETUP.md`,
  `docs/OPENAI_REAL_MODEL_VALIDATION.md`, `docs/PIPELINE_AUTHORITY.md`,
  `docs/REAL_MODEL_EVALS.md`, `docs/TEST_RESULTS.md`, los audits históricos
  `STAGE1_EXTERNAL_INFRASTRUCTURE_AUDIT.md`,
  `STAGE2_CONVERGENCE_HANDOFF.md`, `UI_CONTRACT_TRACEABILITY.md` y este audit.
- `AGENTS.md`, `specification/00_Especificacion_Arquitectura_v1.1(1).md` y
  `specification/05_Plan_Implementacion_v1.1(1).md` documentan el estado
  operativo nuevo; sus menciones P08 son negativas o históricas.
- `specification/01_Prompt_Pack_v1.1(1).md`,
  `specification/02_Contratos_y_Esquemas_v1.1(1).md`,
  `specification/03_ADRs_v1.1(1).md`,
  `specification/06_MVP_Entorno_Experimental(1).md`,
  `specification/MATRIZ_CONSISTENCIA_v1.1(1).md` y
  `specification/VALIDACION_CONTRATOS(1).md`.

El texto íntegro del prompt P08 queda congelado. Su frase histórica
“subconjunto estricto” está etiquetada como wording no autoritativo; la norma
vigente dice `visible_anchor ⊆ support_evidence`, admitiendo igualdad.

## Recovery y autoridad

- P07 vigente + P08 viejo: se recompila y valida P07; la decisión P08 se ignora.
- P07 viejo/incompatible + P08 ACCEPT: no se acepta por el ACCEPT; cache/replay
  vigente debe validar o la ejecución falla cerrada/regenera conforme a policy.
- P08 REJECT no veta un P07 vigente válido; ESCALATE no deja un estado varado.
- Resume `QUESTION_REVIEW` es idempotente y tenant-scoped: reutiliza P06/plan/P07
  compatibles, crea cero P08 y continúa con validación/ASSEMBLE/P09.
- Nuevas ejecuciones guardan candidate/StageRun/lineage sin review. Rows P08
  anteriores siguen consultables con ACCEPT/REJECT/ESCALATE.

## Compatibilidad menor P07

El visible anchor es un subconjunto, no necesariamente propio, de support
evidence. `Anchor.self_containment_score` queda clasificado como
`DERIVED_COMPATIBILITY / LEGACY_NO_ACTIVE_AUTHORITY`: no es gate, no decide
answerability o aceptación, no alimenta P08 y no decide aprobación docente.
