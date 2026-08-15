# Autoridad del pipeline simplificado

**Estado:** norma aceptada para preparar el cutover de Etapa 2, 2026-08-14

**Versión ejecutable:** `pipeline-authority/1.0.0`

**Estado operativo:** `FORMALIZED_RUNTIME_CUTOVER_PENDING`

Esta decisión simplifica la asignación de autoridad sin rediseñar la
arquitectura conceptual ni cambiar routing. P04 conserva
`AssessmentBlueprint` como output canónico de etapa, pero su frontera de
inferencia se restringe a `BlueprintModelDraft`; un compilador determinista
materializa identidad, policy y estado antes del preflight. P06, P07 y P09 no
cambian. La fuente ejecutable de esta norma es
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

El runtime actual aún conserva dependencias operativas de P05/P08. Esta
iteración formaliza el destino y los invariantes, pero no cambia workflows,
jobs, persistencia, routing ni transiciones productivas. Por eso no puede
declararse completo el cutover hasta resolver la sección 6.

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

## 6. Dependencias para el cutover posterior

P05 todavía participa en:

- `_run_activity_pipeline` y el job durable de revisión/edición de blueprint;
- el guard de aprobación y `BlueprintRow.review`/`BlueprintEnvelope.review`;
- estimación de llamadas/costo, estados de stage y resume;
- contratos, registry, rutas, prompts, fixtures y observabilidad histórica.

El cutover debe reemplazar sólo su gate activo por el preflight determinista ya
existente y la decisión docente, preservando versionado, idempotencia y
compatibilidad de lectura. No debe borrar reviews P05 persistidas.

P08 todavía participa en:

- el loop de generación por oportunidad y la selección de pregunta;
- `QuestionReview`, `GeneratedQuestionRow`, acciones localizadas y
  regeneración;
- estado/resume, estimación de llamadas, métricas y DTO/UI de revisión;
- contratos, registry, rutas, prompts, fixtures y observabilidad histórica.

El cutover debe sustituir su aceptación activa por validaciones deterministas
y decisión docente. También debe separar de forma durable la generación de
P09 para que ocurra después de la revisión/aprobación docente, sin perder
exactly-once, acciones localizadas ni lineage. Ese cambio toca workflows, jobs
y persistencia y queda expresamente fuera de esta iteración.

## 7. Límites de esta formalización

No cambia provider routing, prompts ejecutables, parser, seguridad, tenancy,
auth, storage, exports ni infraestructura. No autoriza despliegue, datos
estudiantiles reales, un corpus nuevo ni llamadas billables. Cualquier cambio
operativo posterior debe mantener P10 deshabilitado y demostrar regresión de
Etapas 0/1/2 antes de promover el cutover.
