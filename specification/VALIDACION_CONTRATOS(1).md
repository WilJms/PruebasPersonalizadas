# Validación de contratos v1.1

## 1. Fuente primaria

`models_v1.1.py` es la única fuente primaria de la forma estructural del dominio y de la frontera código-modelo.

- `CONTRACT_MODELS` enumera todos los roots exportados.
- `build_schema_bundle()` usa `pydantic.json_schema.models_json_schema`.
- `contracts.schema_v1.1.json` es un artefacto generado; no se edita manualmente.
- OpenAPI debe importar los mismos modelos Pydantic o DTOs que los compongan.
- Prompt registry guarda `input_schema_name`, `output_schema_name`, `provider_output_schema_name` y `schema_version=1.1.0`; no acepta nombres no presentes en `roots`.

La documentación explica invariantes contextuales, pero no redefine tipos, enums ni obligatoriedad.

ADR-037 no cambia contratos ni exige regenerar el bundle. La autoridad y el
orden objetivo se validan aparte contra `pipeline-authority/1.0.0`. Los roots y
fixtures P05/P08 continúan obligatorios como compatibilidad histórica, y P10
como contrato deshabilitado; ninguno prueba que la etapa esté activa.

---

## 2. Generación del JSON Schema

Desde el directorio que contiene ambos archivos:

```bash
python -m py_compile models_v1.1.py
python models_v1.1.py --schema contracts.schema_v1.1.json
python -m json.tool contracts.schema_v1.1.json >/dev/null
```

Para verificar que el artefacto versionado no tiene drift:

```bash
tmp_schema="$(mktemp)"
python models_v1.1.py --schema "$tmp_schema"
cmp --silent "$tmp_schema" contracts.schema_v1.1.json
```

En CI, un `cmp` distinto falla y muestra la instrucción de regenerar. El pipeline no sobrescribe silenciosamente el archivo versionado.

---

## 3. Validación independiente del bundle

Comprobación mínima con `jsonschema` Draft 2020-12:

```python
import json
from jsonschema import Draft202012Validator

bundle = json.load(open("contracts.schema_v1.1.json", encoding="utf-8"))
Draft202012Validator.check_schema(bundle)

defs = bundle["$defs"]
for root_name, root_schema in bundle["roots"].items():
    assert root_schema == {"$ref": f"#/$defs/{root_name}"}
    assert root_name in defs
```

Este test comprueba sintaxis, roots y referencias directas. Un crawler adicional recorre cada `$ref` interno y falla si el destino no existe.

---

## 4. Fixtures

### 4.1 Convención

Los ejemplos concretos validables de Markdown se etiquetan inmediatamente antes del bloque:

```text
<!-- contract-fixture: AssessmentPlan -->
```

El extractor toma el siguiente bloque `json`, lo parsea y valida contra `roots/<name>` o `$defs/<name>`. Plantillas con placeholders `{{...}}` no llevan la etiqueta y no se presentan como instancias.

### 4.2 Fixtures incluidos en los entregables

| Archivo | Fixture | Cobertura |
|---|---|---|
| `01_Prompt_Pack_v1.1.md` | `ModelTaskEnvelope` | envelope y allowlist |
| `01_Prompt_Pack_v1.1.md` | `QuestionGenerationResult` | reemplazo requerido en P07 con Diagnostic completo |
| `01_Prompt_Pack_v1.1.md` | `ModelCallLedger` | route anidada, enums y costos |
| `02_Contratos_y_Esquemas_v1.1.md` | `EvidenceUnit` | locator discriminado, hashes y submission |
| `02_Contratos_y_Esquemas_v1.1.md` | `QuestionOpportunityTemplate` | operación/foco/observable y formatos |
| `02_Contratos_y_Esquemas_v1.1.md` | `AssessmentPlan` | fail-closed atómico |
| `02_Contratos_y_Esquemas_v1.1.md` | `ProblemDetail` | error API |
| `02_Contratos_y_Esquemas_v1.1.md` | `DomainEvent` | envelope, actor, versiones y correlación |

### 4.3 Fixtures de implementación recomendados

Crear `tests/fixtures/contracts/v1.1/{valid,invalid}` durante la implementación. El conjunto mínimo debe cubrir:

- P01 activity con y sin campos opcionales;
- P02 rúbrica ausente a nivel de workflow y rúbrica contradictoria;
- P05 `critical FAIL -> REJECT` y abstención sin recommendation;
- P06 mapeo dimensión-variante y rechazo de operación no soportada;
- plan `READY` con exactamente \(N\), reserva disjunta y los cuatro fallos sin parcial;
- P07 closed sin citas y `REPLACEMENT_REQUIRED` sin candidate;
- P10 enriched con igualdad exacta entre `course_source_ids` y citations;
- P08 `NEEDS_REVIEW` sin scores fabricados;
- P09 ready completo y `NEEDS_REVIEW` sin items fabricados;
- P11 repaired/unrepairable;
- localizadores de todas las variantes habilitadas;
- human approval, bulk approval con partición/exclusiones, `SelectedQuestion` editada y `QuestionReviewAction`;
- ModelRoute/Resolution con modalidad compatible e incompatible;
- evento válido y rechazo de versión/ID/tipo inválido.

Los casos P05/P08 anteriores son regresión de lectura/contrato histórico, no
un corpus nuevo ni un gate de selección de modelo.

---

## 5. Pruebas obligatorias

### 5.1 Sintaxis y generación

- `py_compile` de `models_v1.1.py`;
- import con Pydantic soportado;
- generación determinista del bundle;
- `Draft202012Validator.check_schema`;
- version `$id`, `version` y `SCHEMA_VERSION` iguales.

### 5.2 Correspondencia Pydantic/JSON Schema

No se comparan dos definiciones manuales: se regenera. Además, CI verifica para cada root:

- conjunto de propiedades;
- conjunto `required`;
- defaults y `const` de `schema_version`;
- enums y literals;
- límites `min/max/pattern`;
- `additionalProperties=false`;
- `$refs` resolubles;
- union `SourceLocator` discriminada por `kind`.

### 5.3 Round-trip y negativos

- `model_validate_json -> model_dump_json -> model_validate_json` por root;
- rechazo de campos extra;
- rechazo de enum/case incorrecto;
- rechazo de ID/hash inválido;
- bbox/líneas invertidas;
- EvidenceBundle con tenant/submission cruzados;
- blueprint con variante/template duplicado u operación no soportada;
- plan `READY` con menos/más de \(N\), IDs repetidos o reserva solapada;
- plan fallido con primarias parciales;
- choice sin una única mejor respuesta, rationale o misconception de distractor;
- QuestionGenerationResult closed con citation;
- EvaluationGuide duplicada o READY sin items;
- repair result contradictorio;
- SelectedQuestion con ancla/opciones/citas incoherentes y Assessment CLOSED enriquecido;
- approval sin actor/fecha y bulk approval sin confirmación/partición exacta;
- edit sin replacement y reject/regenerate sin reason.

### 5.4 Frontera P01-P11

Tabla esperada en test, no inferida desde texto libre:

```python
PROMPT_CONTRACTS = {
    "P01_ACTIVITY_SPEC_V1": ("ActivitySpecRequest", "ActivitySpec"),
    "P02_RUBRIC_NORMALIZE_V1": ("RubricNormalizeRequest", "RubricSpec"),
    "P03_AMBIGUITY_TRIAGE_V1": ("AmbiguityTriageRequest", "AmbiguityReport"),
    "P04_BLUEPRINT_BUILD_V1": ("BlueprintBuildRequest", "AssessmentBlueprint"),
    "P05_BLUEPRINT_REVIEW_V1": ("BlueprintReviewRequest", "BlueprintReview"),
    "P06_EVIDENCE_MAP_V1": ("EvidenceMapRequest", "EvidenceMapPatch"),
    "P07_QUESTION_BUILD_V1": ("QuestionBuildRequest", "QuestionGenerationResult"),
    "P08_QUESTION_REVIEW_V1": ("QuestionReviewRequest", "QuestionReviewResult"),
    "P09_GUIDE_BUILD_V1": ("GuideBuildRequest", "EvaluationGuide"),
    "P10_ENRICHED_CONTEXT_V1": ("QuestionBuildRequest", "QuestionGenerationResult"),
    "P11_SCHEMA_REPAIR_V1": ("SchemaRepairRequest", "SchemaRepairResult"),
}

PROVIDER_OUTPUT_CONTRACTS = {
    **{prompt_id: output for prompt_id, (_, output) in PROMPT_CONTRACTS.items()},
    "P04_BLUEPRINT_BUILD_V1": "BlueprintModelDraft",
}
```

`PROMPT_CONTRACTS` conserva el output canónico de etapa para compatibilidad. El
schema estructurado que ve el proveedor se toma de
`PROVIDER_OUTPUT_CONTRACTS`; sólo P04 difiere y el gateway compila su draft
antes de devolver `AssessmentBlueprint`.

El test exige que los 21 nombres distintos existan en `roots`, que el registry use versión 1.1.0 y que la llamada valide request, envelope, output del proveedor, compilación y validaciones contextuales en ese orden.

Un test independiente exige que el pipeline objetivo incluya sólo P01-P04,
P06/P07/P09 como etapas de modelo, marque P05/P08 `inactive`, P10 `disabled` y
asigne una única autoridad a cada decisión. La presencia de una ruta en el
registry es compatibilidad histórica, no reachability. Para P05 el cutover ya
está completo y ninguna ejecución nueva consulta su ruta; P08 sigue pendiente
de retiro operativo.

---

## 6. Validaciones fuera de JSON Schema

Pydantic/JSON Schema no pueden comprobar por sí solos:

- que IDs existen, pertenecen al workspace y a la misma submission;
- que un locator/hash resuelve el archivo exacto;
- que `display_text` es literal/crop/transformación autorizada;
- que una cita sustenta realmente `supported_claim`;
- groundedness, answerability y demanda cognitiva;
- score/redundancia y planificación determinista de exactamente \(N\);
- autorización del actor, ETag y elegibilidad/partición de aprobación masiva;
- capabilities/modalidades y políticas de proveedor, región, retención, presupuesto, disponibilidad y fallback;
- revisión humana antes de aprobación;
- seguridad de archivos y borrado real.

Estas reglas viven en servicios/validators con códigos estables. P11 nunca las repara.

El clasificador de qualification prueba además los estados `VALID`,
`ORACLE_SUSPECT`, `INVALID` y `NOT_APPLICABLE`; la sospecha debe producir
`INCONCLUSIVE` aun ante desacuerdo sistemático. El reporting prueba que sólo la
clasificación sintética enumera códigos estructurados y su hash.

---

## 7. Mecanismo para impedir divergencias futuras

Un cambio de contrato solo se integra si el mismo PR incluye:

1. cambio en `models_v1.1.py` o nueva versión mayor/minor;
2. bundle regenerado y diff revisado;
3. fixture válido y, cuando corresponda, inválido;
4. actualización de `PROMPT_CONTRACTS` si toca P01-P11;
5. consumer/provider tests y OpenAPI snapshot;
6. actualización de documentación/changelog;
7. decisión de compatibilidad y migración.

Checks de CI recomendados:

```text
contracts:compile
contracts:generate-and-diff
contracts:draft2020-check
contracts:root-ref-crawl
contracts:fixtures
contracts:negative-invariants
prompts:registry-contract-map
api:openapi-snapshot
```

Se prohíbe:

- editar manualmente `$defs`;
- introducir un nombre de campo solo en un prompt;
- aceptar `dict[str, Any]` como payload final sin request root;
- promover prompt/modelo/schema por separado;
- usar ejemplos no validables como si fueran fixtures.

---

## 8. Compatibilidad y migración 1.0 -> 1.1

- El constructo y los contratos de evidencia conservan continuidad.
- La corrección de blueprint/plan no es wire-compatible con `BlueprintSlot`, candidate batches, selector posterior o guide patches.
- No se convierten slots en oportunidades mediante un rename: el catálogo y cada plan se regeneran desde consigna, rúbrica, decisiones y evidencia versionadas.
- `QuestionGenerationResult.context_mode` tiene default `CLOSED`; P10 exige `COURSE_ENRICHED` explícito.
- P07/P08 usan IDs y roots nuevos; el prompt registry debe actualizarse de forma atómica con el schema.
- P09 persiste `EvaluationGuide` independiente, asociado a assessment/submission.
- `ActivityConfig` elimina profundidad/operaciones solicitadas y añade modo de justificación.
- bulk approval y ModelRouteResolution son nuevos roots operacionales.
- P11 cambia su contrato operacional: el consumidor extrae `repaired_output` y lo valida contra el target. No tratar `SchemaRepairResult` como el objeto reparado.
- `DomainEvent` añade `schema_version`, actor tipado y IDs normalizados; migrar envelopes internos antes de activar outbox/consumidores.

Como el mecanismo sustituido no tenía snapshots productivos aprobados, no se define migración automática de evaluaciones parciales/candidatos. Si existieran datos de prueba, se preservan como históricos y se vuelve a ejecutar el pipeline vigente; nunca se marcan como equivalentes sin revalidación.
