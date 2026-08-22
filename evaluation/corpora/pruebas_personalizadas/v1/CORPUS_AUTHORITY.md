# Autoridad del corpus

Este paquete es la versión finalizada del corpus de **Pruebas Personalizadas**. Su contexto es cerrado: ninguna inferencia puede apoyarse en fuentes ajenas a la consigna, la rúbrica, la submission y la evidencia autorizada de la misma actividad.

## Model-facing / product input

Solo pueden entrar al producto o mostrarse a un modelo que opera sobre el corpus:

- `activity_*/01_assignment.docx`;
- `activity_*/02_rubric.docx`;
- los artefactos neutrales dentro de `activity_*/submissions/`.

Los nombres de archivo no son labels. El índice de una submission no codifica calidad, suficiencia, dificultad, adversarialidad ni resultado esperado. Los IDs se permutaron por actividad mediante una regla determinista independiente del contenido.

## Benchmark-only

Son autoridad del benchmark, pero nunca input del producto ni del modelo evaluado:

- `activity_*/final_ratification.json`;
- `corpus_final_manifest.json`;
- `benchmark_fixtures/p09/*.json`;
- los schemas de `_schemas/`.

Los fixtures P09 contienen preguntas aprobadas y fijas como input stage-local. No son expected outputs de P09 ni preguntas golden de P07.

## Historical / never model input

Todo `_audit_history/**` es exclusivamente histórico y nunca puede entrar al producto, al modelo o a una calificación:

- auditoría y ratificaciones originales de Opus 5;
- borradores pre-finales;
- snapshot anterior a la finalización;
- mapeo de IDs y nombres anteriores;
- herramientas y renders de QA usados durante la curación.

La auditoría Opus es falsable. Cuando difiere de los bytes reales, mandan los bytes. `ORACLE_SUSPECT` expresa una ambigüedad genuina y no debe tratarse como hard oracle ni convertirse automáticamente en `VALID`.

Los ejemplos de preguntas, cuando existen en material histórico, ilustran posibilidades; no son goldens ni textos que un sistema deba reproducir.
