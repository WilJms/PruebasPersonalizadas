# Evals del modelo real

El corpus inicial contiene 20 casos exclusivamente sintéticos en
`tests/fixtures/openai_evals/v1/synthetic_cases.json`. No incluye nombres,
entregas ni contenido estudiantil real. El rango gobernado es de 10 a 30 casos,
con IDs únicos y clasificación obligatoria
`SYNTHETIC_ONLY_NO_STUDENT_DATA`. El manifest fija además
`route_profile=LUNA_BASELINE_V1`, prompt pack `1.1.1` y schema `1.1.0`.

## Cobertura

- un happy path para P01-P09 y P11, con y sin rúbrica;
- evidencia normalizada procedente de casos TXT, Markdown, PDF y DOCX;
- abstención por evidencia insuficiente en P01/P07, ambigüedad e inyección;
- preguntas CHOICE y OPEN_SHORT, con/sin justificación, y tres operaciones
  cognitivas distintas;
- una reparación estructural localizada P01→P11;
- P10 sin ruta y con cero llamadas;
- las diez dimensiones de revisión humana exigidas, incluida severidad.

Los formatos son metadatos gobernados del fixture y se materializan como
locators/evidencia normalizada válida. Este harness aislado no abre ni envía el
archivo raw; la seguridad de los parsers TXT/MD/PDF/DOCX permanece cubierta por
la regresión específica de parsing y por el E2E sintético posterior.

La ejecución offline valida el manifest, contratos, schemas estrictos,
Pydantic, ruta y comportamiento mock sin construir un cliente OpenAI:

```bash
.venv/bin/python scripts/run_openai_evals.py
```

El checkout usa layout `src/`: estos comandos deben ejecutarse con el
intérprete preparado del repositorio después de `make install`, no con un
`python` global que no tenga la instalación editable.

Resultado observado el 2026-08-08: 20/20 PASS, `network_calls=0` y
`billable_calls=0`. Cada fila offline expone metadata reproducible de perfil,
provider, modelo, esfuerzo, prompt/schema y fallback nulo, sin afirmar un
modelo efectivo porque no existe transporte. La suite automatizada también
verifica que real mode sin
doble autorización o sin presupuesto suficiente —incluidos retries y P11— se
bloquee antes del transporte.

Un propietario puede seleccionar un caso por ID, o repetir la opción para
comparar varios, sin habilitar red:

```bash
.venv/bin/python scripts/run_openai_evals.py \
  --case-id oa-p07-choice-justification \
  --case-id oa-p07-open-short-txt
```

## Frontera canary Luna medium/high

Los dos canaries ejecutados una vez reutilizan exclusivamente los casos existentes
`oa-p01-happy-txt` y `oa-p07-open-short-txt`. El modo dry-run construye el
adaptador OpenAI real con un cliente Responses fake versionado, captura el
payload y atraviesa el `ModelGateway` auténtico sin leer una clave ni crear red:

```bash
make openai-canary-dry-run CASE_ID=oa-p01-happy-txt
make openai-canary-dry-run CASE_ID=oa-p07-open-short-txt
```

El target usa `PYTHON=.venv/bin/python` por defecto y elimina del proceso
`CVA_OPENAI_API_KEY` y las dos approvals reales antes de invocar el harness.
Puede validarse en un entorno limpio ya instalado pasando explícitamente
`PYTHON=/ruta/al/python-preparado`.

Cada invocación exige exactamente un caso aprobado. Su mapa real contiene
únicamente el prompt seleccionado, sin P10 ni P11; `max_retries=0` y un guard
anterior al transporte bloquea una segunda invocación del adapter. El SDK
conserva sus retries automáticos en cero. Por ello, incluso una salida
estructural inválida falla cerrada después de una request como máximo y no
puede disparar reparación P11. La política general de retries del worker y del
golden set real no cambia.

Los dry-runs del 2026-08-09 pasaron con Luna-medium para P01 y Luna-high para
P07, Structured Output strict, Pydantic/contexto/IDs válidos, payload sólo
`input_text`, `tools=[]`, `store=false`, `background=false`, sin estado de
conversación, una llamada fake por caso y cero llamadas de red/facturables.
P07 preservó submission, oportunidad, template, dimensión, variante,
operación cognitiva y allowlist de evidencia bajo `context_mode=CLOSED`, sin
fuentes externas.

La ejecución real autorizada posterior terminó P01 en `READY` y P07 en fallo
cerrado tras su única request. P07 llegó a
`QuestionGenerationResult.model_validate()` y luego el intento de resolver P11
fue bloqueado antes del transporte; no hubo P11 ni segunda request. El literal
histórico `SCHEMA_INVALID` no permite distinguir si el objeto incumplía el JSON
Schema del provider o solo un `model_validator`, porque esa clasificación no se
retuvo y el output no se conserva.

La corrección offline valida ahora el objeto contra el mismo schema de
`text.format` y conserva `provider_schema_status`, tipos/paths estructurales
saneados, ledger primario y `repair_disposition` por separado. El schema P07
exacto queda fijado en 13.671 bytes y SHA-256
`80692d48637f0ae2d7a7e6f05ab4e9b0a5e2d8eff6f1b103fbd14f62c482639a`.
Los tests reproducen campos requeridos ausentes, extras, invariantes Pydantic y
fallos contextuales con una sola llamada fake, P11/P10/Sol/retries en cero y
sin serializar contenido.

La recanary real única autorizada después de esa corrección terminó PASS:
outcome `READY`, provider schema/Pydantic/contexto/IDs válidos, Luna-high
solicitada y efectiva, una request, P11/P10/Sol/retries en cero y USD
0.00276560 calculados. El checkpoint es
`OPENAI_LUNA_P07_RECANARY_PASS_REVIEW_REQUIRED`: esta segunda observación no
cierra automáticamente el P1 histórico. La revisión posterior sí lo cierra
como blocker por la combinación fail-closed, corrección del defecto
determinista de observabilidad y recanary PASS sin relajar la frontera. La causa
del output histórico sigue sin conocerse y su recurrencia continúa como P2.
La autorización se consumió y este documento no contiene una aprobación
billable vigente.

## Calificación sintética preparada, no autorizada

La evidencia real ya vigente cubre `oa-p01-happy-txt`,
`oa-p07-open-short-txt` y `oa-p11-happy`. Repetirlos no añadiría una frontera
nueva: desde esas llamadas no cambiaron contratos, prompt pack, rutas ni el
schema generado; la modificación de `openai_schema.py` solo añadió validación
diagnóstica local. La secuencia fija siguiente cubre los **15** casos
`real_eligible` restantes, en orden risk-first:

| Orden | Casos | Cobertura nueva |
|---:|---|---|
| 1 | `oa-p01-injection-md` | inyección sintética y severidad P0 |
| 2–5 | `oa-p07-insufficient`, `oa-p07-choice-justification`, `oa-p07-predict-pdf`, `oa-p07-critique-docx` | recurrencia P07; abstención, CHOICE/OPEN_SHORT, justificación, tres operaciones, TXT/MD/PDF/DOCX |
| 6 | `oa-p01-insufficient` | fail-closed P01 |
| 7–8 | `oa-p03-ambiguous`, `oa-p03-no-rubric` | abstención por ambigüedad y flujo sin rúbrica |
| 9–15 | `oa-p02-happy-pdf`, `oa-p03-happy-with-rubric-md`, `oa-p04-happy`, `oa-p05-happy`, `oa-p06-happy-docx`, `oa-p08-happy-pdf`, `oa-p09-happy-docx` | spine P02–P06/P08/P09, con rúbrica y formatos normalizados |

Junto con las tres observaciones reutilizadas, la cobertura acumulada queda en
18/18 casos real-eligible y P01–P09/P11. P10 continúa comprobado offline sin
ruta; el fixture de reparación controlada `oa-p01-structural-repair` sigue
siendo mock-only y no se intenta inducir una salida inválida real.

El procedimiento offline reproducible desde un checkout preparado es:

```bash
make install
make openai-qualification-dry-run
```

El segundo comando elimina del environment la clave y todas las approvals,
construye 15 payloads mediante el adapter OpenAI real y ejecuta un transporte
Responses fake. El resultado fijado es 15/15 PASS, 0 red, 0 billable, 0
P10/P11/Sol/fallback y retries gateway/prompt/SDK 0/0/0.

La futura ejecución real usará exclusivamente
`--mode qualification-real`, la approval distinta
`CVA_OPENAI_REAL_QUALIFICATION_APPROVAL=OPENAI_REAL_SYNTHETIC_QUALIFICATION_APPROVED`,
la clave por el canal privado y un cap CLI no mayor de USD 0.30. El modo bloquea
selecciones `--case-id`, drift del manifest, presupuesto inferior al ceiling o
superior al cap humano, y solo entonces comprueba approval/credencial y crea el
adapter. Antes de cada transporte vuelve a estimar el request concreto como si
todo su input fuese cache-write y bloquea si la reserva acumulada superaría el
cap; esto también cubre el tamaño dinámico de un P11. El comando documental
—no autorizado todavía— es:

```bash
.venv/bin/python scripts/run_openai_evals.py \
  --mode qualification-real \
  --allow-billable \
  --max-total-cost-usd 0.30
```

Hay 15 requests primarias programadas y una única reserva P11 global: máximo
**16 Responses requests**. Gateway, prompt y SDK tienen retries cero. P11 solo
puede aparecer automáticamente después de un output primario estructuralmente
inválido; después de esa llamada el gate se detiene aunque la reparación pase.
No se programa un P11 directo, no existe ruta P10/fallback/Sol y cualquier
fallo de provider/transporte, schema provider, Pydantic, contexto, expected
outcome, identidad de modelo, presupuesto o request boundary detiene la
secuencia.

La evidencia versionada conserva solo case/prompt/schema, ruta/esfuerzo,
estados de validación, tipos/paths saneados, tokens, latencia, costos y hashes.
No serializa payload, output, mensajes de error, request ID claro ni clave. Los
expected outcomes no cambiaron y el manifest completo bloquea drift. Este gate
demuestra operación técnica de contratos y contexto; no puntúa answerability,
utilidad de guía ni calidad pedagógica, que requieren revisión humana posterior
desde la aplicación.

La matriz mixta Sol/Luna permanece solo como comparador histórico futuro. No
se ejecutará Sol sin otro gate y presupuesto humano.

## Resultado de la calificación sintética real

La única secuencia autorizada se ejecutó sobre `73d252b…` y se detuvo en su
primer caso, `oa-p01-injection-md`, conforme a `FIRST_CONTEXT_OR_EXPECTED_OUTCOME_FAILURE`.
El Structured Output pasó el schema del proveedor y Pydantic; la allowlist
contextual falló con `MODEL_CONTEXT_NOT_ALLOWLISTED`, antes de comprobar el
expected outcome `VALID`. No hubo repair: P11 quedó en cero.

La llamada usó Luna medium solicitada/efectiva y registró 1,725 input, 0
cached, 1,722 cache-write, 943 output y 516 reasoning tokens, 10,345 ms y USD
0.00156270 calculados. Hubo una sola Responses request, retries 0/0/0 y cero
P10/Sol/fallback. Los otros 14 casos no se ejecutaron. El manifest intacto
preclasifica este fallo como P0, pero esta evidencia content-free no determina
si la causa reside en el modelo, el prompt, el corpus sintético o la validación
contextual.

El gate queda detenido en
`OPENAI_REAL_SYNTHETIC_QUALIFICATION_P01_INJECTION_CONTEXT_FAILED_REVIEW_REQUIRED`.
No habilita P05 durable, deployment ni recorrido UI.

## Recorrido humano preparado

La selección `--case-id` cubre prompts aislados y devuelve únicamente metadata
técnica; no crea silenciosamente aggregates en la aplicación. Después de los
checkpoints de credenciales, gasto, evals y despliegue —nunca antes— el
recorrido E2E humano se inicia explícitamente desde la UI con los fixtures
sintéticos versionados de `fixtures/stage0/activity_01_rubric`,
`activity_02_no_rubric` o `activity_03_holdout_pdf`. El propietario crea la
actividad/lote, carga solo esos artefactos, ejecuta el worker y abre evidencia,
preguntas y guía. La vista de métricas separa ruta/latencia/costo de contenido,
y las acciones existentes permiten aceptar, editar, rechazar y regenerar. Una
segunda ejecución se compara por sus IDs de job/ledger; no se afirma que hoy
exista un selector UI del manifest aislado. Ningún caso puede sustituirse por
datos estudiantiles reales.
