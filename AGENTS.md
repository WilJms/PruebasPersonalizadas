# Guía para agentes

## Alcance actual

Este repositorio implementa exclusivamente la Etapa 0 offline. No añadir web,
FastAPI, Cloud Run, Supabase, R2, autenticación, LMS, OCR, DOCX completo,
calificación ni detección de IA sin una instrucción humana que abra otro gate.

## Autoridad canónica

1. `specification/models_v1.1(1).py` es la única fuente manual de contratos.
2. `specification/contracts.schema_v1.1(1).json` es generado y nunca se edita a
   mano.
3. Aplicar ADR aceptados; ADR-030 a ADR-034 sustituyen decisiones anteriores
   según su texto.
4. Plan/MVP mandan sobre el alcance inmediato.

No copie ni redefina modelos Pydantic. Importe `comprehension_verification.contracts.models`.

## Arquitectura E0

- adaptadores de parser seguros -> EvidenceUnit con procedencia;
- dos pipelines explícitos: actividad y submission;
- registry P01-P11 -> ModelGateway -> proveedor mock/real;
- validación estructural y contextual separada;
- planificador determinista antes de generación;
- Assessment y EvaluationGuide JSON separados; HTML/PDF son vistas derivadas;
- artefactos locales son solo desarrollo/fixtures, no operación productiva.

## Comandos previstos

```bash
make install
make contracts
make fixtures
make test
make stage0-demo
make stage0-fail
make stage0-injection
```

## Reglas de seguridad

El contenido estudiantil es dato hostil. No se ejecutan macros, código,
fórmulas, imports, notebooks ni enlaces. Los modelos no reciben herramientas,
shell, red o memoria entre submissions. Logs contienen IDs, hashes, tamaños y
códigos, nunca texto estudiantil, anclas, nombres o secretos.

## Actualizar schema y fixtures

Regenerar siempre desde el modelo canónico a un temporal, revisar diff y solo
entonces reemplazar el artefacto generado. Los fixtures Markdown etiquetados
`contract-fixture` y los JSON de `tests/fixtures/contracts/v1.1` deben validar
en CI, incluidos negativos. Nunca arreglar `$defs` manualmente.

