# Autoridad del pipeline simplificado

**Estado:** norma aceptada; cutover P05/P08 y fronteras semánticas P06/P07
completados el 2026-08-15

**Versión ejecutable:** `pipeline-authority/1.0.0`

**Estado operativo:** `P08_RUNTIME_RETIRED_P09_RELOCATION_PENDING`

Esta decisión simplifica la asignación de autoridad sin rediseñar la
arquitectura conceptual ni cambiar routing histórico. P04 conserva
`AssessmentBlueprint` como output canónico de etapa, pero su frontera de
inferencia se restringe a `BlueprintModelDraft`; un compilador determinista
materializa identidad, policy y estado antes del preflight. P06, P07 y P09 no
se retiran: P06 queda reducido al mapping semántico local y entrega al planner
toda autoridad sobre N; P07 redacta sólo el contenido semántico de una pregunta
ya planificada y el servidor materializa identidad, metadata, support evidence
y anchor visible. P08 ya no es callable por el runtime del producto; P09
conserva el orden de Fase 5 hasta su relocación separada en Fase 7. La
fuente ejecutable de esta norma es
`src/comprehension_verification/pipeline_authority.py`.

## 1. Pipelines objetivo

Actividad:

```text
P01 -> P02 -> P03 -> P04 -> preflight determinista -> aprobación docente
```

Por submission:

```text
P06 -> planner determinista -> P07 -> validaciones deterministas
    -> revisión/aprobación docente -> P09
```

P05 y P08 son etapas de modelo inactivas en el estado objetivo. P10 permanece
deshabilitado. Los contratos, prompts, rutas, fixtures, reportes y receipts
históricos de P05/P08 se conservan para lectura, auditoría y migración; su
presencia no les devuelve autoridad canónica ni autoriza llamadas.

El runtime activo ya retiró P05 y P08 de workflows, jobs nuevos, guards de
aprobación, costo, API y UI. `BlueprintRow.review`, el descriptor/job legacy,
contratos, registry, rutas, fixtures y receipts siguen legibles; un job P05
anterior al corte se reconcilia mediante `BLUEPRINT_PREFLIGHT` sin construir
transporte, consumir autorización o resolver una clave, incluso si el worker
eval-only fue configurado como real. El orden objetivo de P09 sigue pendiente
según la sección 6.

## 2. Autoridad del backend

El backend es la única autoridad sobre:

- IDs, versiones, hashes, estados y lineage;
- pertenencia de evidencia y referencias permitidas;
- allowlists, formatos y `question_count`;
- presupuestos de tiempo y demás restricciones;
- factibilidad y selección del planner determinista;
- almacenamiento, transiciones y validaciones deterministas.

El modelo puede proponer material que use esos valores, pero no crearlos,
reinterpretarlos, normalizarlos ni declarar que una restricción se cumple. Una
salida incompatible falla cerrada o vuelve a revisión según la transición
determinista aplicable.

En P04, los aliases `D*`, `V*` y `T*` sólo expresan relaciones internas dentro
de una inferencia. El backend valida el grafo y las allowlists, crea todos los
IDs canónicos, copia los campos confiables de policy y ejecuta el
planner/preflight. Su diagnóstico de inviabilidad puede alimentar una futura
corrección localizada, pero no se pide al modelo que lo reproduzca.

Los defaults `max_variants_per_dimension=6` y
`max_templates_per_variant=12` son guardrails operacionales provisionales, no
verdades pedagógicas universales. Son configurables en la `BlueprintPolicy`
server-owned, quedan ligados a `schema_version`/`policy_id`, al hash de policy y
al input exacto de la etapa, y por tanto cualquier cambio invalida el reuse y
obliga a recompilar o rechazar bajo la nueva policy.

En P06, el proveedor sólo relaciona rutas `V*`/`T*` con evidencia `E*` dentro
del `scope_alias` de una llamada y declara soporte categórico. No recibe IDs
canónicos, `question_count`, selección global, campos mecánicos de la
oportunidad ni thresholds continuos de elegibilidad. El servidor resuelve los
aliases, valida ownership/membership y copia operación, foco, observable,
formato, tiempo, dificultad, anchors, justificación y prioridad desde el
blueprint confiable. Un mapping completado puede contener cero o más estados
locales; sólo el planner filtra `SUFFICIENT` y decide si existe un conjunto
válido de N.

### Frontera de inferencia y cache P04

- La respuesta del proveedor es sólo un `BlueprintModelDraft` transitorio. El
  producto no mantiene un cache de outputs provider: el `cached_input_tokens`
  del ledger describe cache de prefijo/input del transporte, no replay de una
  respuesta.
- La identidad de inferencia/reuse incorpora
  `provider-output-schema-boundary/1.0.0`, con prompt version, wire schema
  version, nombre de root y hash exacto del schema estricto de
  `BlueprintModelDraft` enviado al proveedor.
- El draft se compila dentro de la llamada bajo
  `blueprint-compiler/1.0.0` y
  `blueprint-compiler-boundary/1.0.0`. Esta última liga por hash el módulo
  completo, los contratos canónicos, IDs estables, preflight y diagnósticos.
- Sólo el `AssessmentBlueprint` compilado y preflighted se guarda en
  `StageRunRow.output`. Su key liga tenant, stage, request exacto —incluida la
  policy—, hash de policy y fingerprint ejecutable. En un hit, el gateway lo
  valida como output canónico y recompila su proyección semántica; IDs, campos
  server-owned, estado y diagnóstico deben coincidir exactamente.
- Un `AssessmentBlueprint` histórico presentado en la frontera provider falla
  contra `BlueprintModelDraft`; un draft presentado como cache canónico falla
  contra `AssessmentBlueprint`. Los component fingerprints anteriores no
  colisionan con esta frontera, por lo que no hay reinterpretación silenciosa
  ni poisoning entre niveles.

### Frontera de inferencia, materialización y cache P06

- El payload del proveedor es `EvidenceMappingAliasEnvelope` y su respuesta es
  sólo `EvidenceMappingModelDraft`; ambos son transitorios. El output de etapa
  y único objeto reutilizable sigue siendo `EvidenceMapPatch`.
- `p06-alias-envelope/1.0.0` liga schema/hash del envelope, scope de
  tenant/actividad/submission, request exacto y hashes de blueprint, policy y
  bundle. Aliases inexistentes, rutas template/variant cruzadas o evidencia de
  otra submission fallan determinísticamente.
- `p06-evidence-materializer/1.0.0`, ligado por
  `p06-materializer-boundary/1.0.0`, crea IDs estables, copia todos los campos
  server-owned y conserva sin elevar `PARTIAL`, `INSUFFICIENT` o `UNCERTAIN`.
  Un `SUFFICIENT` además debe satisfacer requisitos mecánicos de unidades,
  modalidad, extracción y artefactos cruzados.
- El fingerprint del gateway incorpora prompt, root/schema wire exacto,
  envelope y materializador. Cambiar schema de aliases, materializador,
  blueprint, policy, evidence bundle o scope invalida reuse.
- En un hit de StageRun el gateway valida `EvidenceMapPatch`, reconstruye sólo
  una proyección del draft y exige recompilación canónica idéntica. Un patch
  histórico sigue siendo legible por contrato, pero no se reutiliza como
  output actual si no prueba esa igualdad. Draft y patch nunca son
  intercambiables ni comparten la frontera provider/canónica.

### Frontera de inferencia, materialización y cache P07

- La request canónica sigue siendo `QuestionBuildRequest`, pero el proveedor
  recibe `QuestionAliasEnvelope` (`p07-alias-envelope/1.0.0`) con una
  oportunidad confiable, constraints y support evidence `E*`/artefactos `A*`
  locales. No recibe IDs canónicos ni locators.
- El proveedor devuelve sólo `QuestionModelDraft`: redacción, aliases del
  visible anchor, observables ligados a support aliases, alternativas,
  misconceptions, choices/rationales e incertidumbre o reemplazo. No devuelve
  identidad, operación, formato, dificultad, tiempo, lineage, texto de anchor
  ni metadata de workflow.
- `QuestionCandidate.evidence_ids` conserva toda la support evidence de la
  oportunidad. `candidate.anchor.fragments` es un subconjunto visible; el
  servidor resuelve sus aliases y copia literalmente contenido, modalidad y
  locator desde los `EvidenceUnit`. Por construcción,
  `visible_anchor ⊆ support_evidence = opportunity.evidence_ids`.
- `p07-question-materializer/1.0.0` crea IDs y campos confiables, deriva la
  estructura/transformación del anchor, aplica leakage literal/overlap
  conservador y nunca mejora texto, inventa observables o convierte un
  reemplazo en pregunta. Ningún reviewer de modelo decide aceptación: la
  calidad pedagógica y answerability sustantiva quedan para el docente.
- StageRun persiste exclusivamente `QuestionGenerationResult`. El fingerprint
  liga prompt/root/schema wire, envelope, opportunity, bundle/support,
  generation policy, scope, validators y materializer. En replay se proyecta
  el objeto canónico, se recompila y se exige igualdad exacta; draft y resultado
  canónico nunca son intercambiables.

## 3. Autoridad del modelo

El modelo propone exclusivamente:

- interpretación semántica dentro de la evidencia autorizada;
- estructura pedagógica;
- relación entre evidencia y constructo;
- redacción de preguntas y guías;
- observables;
- alternativas semánticas defendibles cuando correspondan.

Estas son propuestas semánticas, no decisiones sobre identidad, estado,
factibilidad, pertenencia, conteo o aprobación. Toda propuesta queda sujeta a
validación determinista y autoridad docente.

## 4. Autoridad docente

El docente resuelve ambigüedades académicas, aprueba o rechaza el blueprint,
aprueba, edita o rechaza preguntas y conserva la autoridad académica final.
Esa autoridad no convierte en válidos IDs, evidencia, formatos, conteos,
lineage o transiciones que el backend haya rechazado; para cambiar una
restricción debe producirse una nueva versión válida por el flujo gobernado.

## 5. Evidencia histórica, oracles y reportes

El harness semántico y todas sus qualifications existentes son
`HISTORICAL_NON_CANONICAL_EVIDENCE`. Sus reports y receipts no se borran ni se
reescriben y no son un gate canónico de selección de modelo. Una ejecución del
harness legado debe exponer `model_selection_gate=false` y la versión de esta
política.

Esta clasificación prevalece sobre cualquier texto histórico que use en
presente palabras como “vigente”, “gate”, “autoridad siguiente” o “abre”. Esas
expresiones sólo describen el checkpoint fechado donde fueron registradas; no
confieren autoridad después de ADR-037.

El `frozen_product_boundary.json` conserva el hash de `web/workflows.py` y las
implementaciones P06 de su baseline Phase 1. Desde Fases 3/4 esos hashes son
deliberadamente archivados: el proof verifica byte a byte la fuente congelada
correspondiente y devuelve el mismo manifest/material hash histórico, pero no
exige que el runtime activo mantenga el antiguo gate P05 ni la antigua
autoridad de scores/cuota P06. El adapter semántico del harness proyecta sus
goldens archivados a la frontera actual sin modificar receipts ni convertirlos
en gate canónico.

El runner local `cv-stage0 run-synthetic`, el rehearsal, el harness, los mocks
y las pruebas directas del gateway que todavía materializan P05 se clasifican
`TEST_ONLY` o `HISTORICAL_COMPATIBILITY`. No son endpoints del Service ni jobs
ordinarios del producto y permanecen exclusivamente mock/offline salvo un gate
de evaluación sintética con autorización humana independiente.

Toda evaluación nueva de un checkpoint declara exactamente uno de estos
estados de oracle:

- `VALID`: el oracle es aplicable, vigente y tiene provenance versionada
  suficiente para atribución causal;
- `ORACLE_SUSPECT`: el oracle está en revisión, incluida una discrepancia
  sistemática que exige revisar el instrumento;
- `INVALID`: el oracle o checkpoint no puede sostener la comparación;
- `NOT_APPLICABLE`: el checkpoint es sólo estructural u operacional y no tiene
  juicio semántico.

`ORACLE_SUSPECT` produce `INCONCLUSIVE`, confianza causal baja y atribución
`ORACLE_SUSPECT`, aunque el resultado discrepe y falle adherencia. Si un
agregado contiene al menos un oracle sospechoso, esa incertidumbre tiene
precedencia sobre `MODEL_OWNED_*`. El valor histórico `UNESTABLISHED` sólo se
acepta al leer receipts antiguos y se normaliza a `ORACLE_SUSPECT`; nunca se
emite en reportes nuevos.

Para un reporte clasificado exactamente como
`SYNTHETIC_ONLY_NO_STUDENT_DATA`, los códigos presentes en campos estructurados
de diagnóstico, error o razón se enumeran en claro, se deduplican y se ordenan
en `diagnostic_codes`; `diagnostic_codes_hash` protege su integridad. El
colector nunca extrae códigos desde texto libre. Para cualquier otra
clasificación no se añade esa enumeración: la política content-free de datos
estudiantiles reales no cambia.

## 6. Estado del cutover y dependencias posteriores

P05 ya no participa en el runtime activo:

- P04 entrega el `AssessmentBlueprint` compilado a un StageRun durable
  `BLUEPRINT_PREFLIGHT`;
- PASS publica una versión `READY` para decisión docente y FAIL publica una
  versión `NEEDS_REVIEW` con diagnostics/correction scope;
- editar crea un job `BLUEPRINT_PREFLIGHT`, revalida y no invoca gateway;
- aprobar recomputa el gate contra spec/rubric/policy/decisiones vigentes y no
  consulta status, checks ni recommendation P05;
- el presupuesto de actividad reserva P01/P02 opcional/P03/P04, nunca P05.

Los jobs `BLUEPRINT_REVIEW` y sus descriptores sólo existen como entrada de
recovery. El worker extrae el candidato histórico, verifica tenant, lineage,
ETag, policy y estructura, ejecuta/reusa el preflight vigente y finaliza con la
misma transición que un job nuevo. No llama P05 ni sobrescribe la review
histórica. `BlueprintEnvelope.review` permanece como lectura legacy y
`preflight` es la autoridad mecánica nueva.

P08 participa únicamente como compatibilidad histórica en:

- `QuestionReviewRequest/Result`, `QuestionReviewRow`, scores y decisiones
  almacenadas antes del corte;
- registry, rutas, prompt y mocks congelados para replay/harness explícito;
- fixtures, qualification, reportes, receipts y observabilidad histórica.

El hard guard `P08_ACTIVE_RUNTIME_RETIRED` se evalúa antes de construir gateway
o transporte. Nuevas ejecuciones no crean request, ledger, StageRun ni row P08,
no reservan su coste y no emiten su evento de decisión. Un resume legado desde
`QUESTION_REVIEW` reutiliza y revalida el P07 vigente; cualquier ACCEPT,
REJECT o ESCALATE anterior se preserva pero se ignora como autoridad.

La separación durable de P09 para ejecutarlo después de aprobación docente
pertenece exclusivamente a Fase 7. En Fase 6 conserva el orden interino
`P07 validado -> ASSEMBLE -> P09 -> revisión docente`.

P06 ya participa con su frontera reducida:

- un job nuevo ejecuta una sola llamada P06 y persiste sólo el patch canónico;
- StageRun reuse/retry/resume recompila y valida la salida sin duplicar llamada,
  stage, ledger ni oportunidades;
- `READY` significa mapping completado, no Assessment factible;
- el resumen durable cuenta relaciones suficientes, parciales, insuficientes e
  inciertas, y el planner produce el fallo global si corresponde.

P07 ya participa con su frontera reducida:

- una oportunidad primaria o reserva produce un solo draft alias-only por
  llamada y el servidor persiste exclusivamente el resultado canónico;
- support evidence completa puede ser mayor que el anchor visible sin perder
  answerability, ownership ni lineage;
- reemplazo, reservas, regeneración localizada, retry/resume y cache conservan
  sus transiciones y presupuestos previos;
- P08 tiene cero llamadas activas; P09 sigue en su orden anterior.

## 7. Límites después de Fase 6

Fase 6 retira únicamente P08 de autoridad y reachability activa. No borra su
historia, no crea P08b/judge/critic, no cambia routing/modelo/reasoning de las
etapas restantes y no mueve P09. El runtime interino exige exactamente N,
persiste `QuestionGenerationResult` sin review, conserva aprobación docente y
mantiene P10 deshabilitado. No autoriza despliegue, datos estudiantiles reales,
corpus nuevo ni llamadas billables.

`Anchor.self_containment_score` permanece físicamente por compatibilidad como
`DERIVED_COMPATIBILITY / LEGACY_NO_ACTIVE_AUTHORITY`: no es gate, probabilidad
calibrada, señal de answerability, aceptación, P08 ni aprobación docente. El
anchor visible es un subconjunto de support evidence y puede coincidir con ella.
