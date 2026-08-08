# Evals del modelo real

El corpus inicial contiene 20 casos exclusivamente sintéticos en
`tests/fixtures/openai_evals/v1/synthetic_cases.json`. No incluye nombres,
entregas ni contenido estudiantil real. El rango gobernado es de 10 a 30 casos,
con IDs únicos y clasificación obligatoria
`SYNTHETIC_ONLY_NO_STUDENT_DATA`.

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
python scripts/run_openai_evals.py
```

Resultado observado el 2026-08-08: 20/20 PASS, `network_calls=0` y
`billable_calls=0`. La suite automatizada también verifica que real mode sin
doble autorización o sin presupuesto suficiente —incluidos retries y P11— se
bloquee antes del transporte.

Un propietario puede seleccionar un caso por ID, o repetir la opción para
comparar varios, sin habilitar red:

```bash
python scripts/run_openai_evals.py \
  --case-id oa-p07-choice-justification \
  --case-id oa-p07-open-short-txt
```

## Gate real preparado, no autorizado

La futura ejecución exige simultáneamente:

1. `--mode real --allow-billable`;
2. `--max-total-cost-usd` positivo y suficiente para el techo preflight;
3. `CVA_OPENAI_API_KEY` por canal privado;
4. `CVA_OPENAI_REAL_EVALS_APPROVAL=OPENAI_REAL_EVALS_APPROVED`.

Ejemplo documental, que no debe ejecutarse antes del checkpoint:

```bash
python scripts/run_openai_evals.py --mode real --allow-billable \
  --max-total-cost-usd PRESUPUESTO_APROBADO
```

La evaluación real debe registrar por caso schema/context validation, modelo
efectivo, intentos, tokens, latencia y costo. La revisión humana puntúa además
grounding, abstención, preservación de IDs, exactitud de citas, utilidad y
ausencia de invención. Los criterios de salida son P0=0/P1=0, todos los casos
estructural/contextualmente válidos, ningún dato sensible en logs y costos
dentro del techo. Un fallo detiene el gate; no habilita fallback ni P10.

Los resultados reales se anexarán con fecha, commit, versión de prompt/schema,
model ID observado y hash del manifest. Hasta entonces no se reclama calidad
semántica del proveedor.

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
