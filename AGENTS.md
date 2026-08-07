# Guía para agentes

## Alcance actual

Este repositorio implementa las Etapas 0 y 1: núcleo offline verificable y un
laboratorio privado de una actividad y una submission, con FastAPI/React,
persistencia PostgreSQL/Supabase, objetos privados R2 y ejecución en Cloud Run
Jobs. No añadir ninguna historia de Etapa 2 (batch, retry/cancel, acciones por
pregunta, aprobación masiva, DOCX completo, métricas/feedback), LMS, OCR,
calificación ni detección de IA sin una instrucción humana que abra otro gate.

## Autoridad canónica

1. `specification/models_v1.1(1).py` es la única fuente manual de contratos.
2. `specification/contracts.schema_v1.1(1).json` es generado y nunca se edita a
   mano.
3. Aplicar ADR aceptados; ADR-030 a ADR-034 sustituyen decisiones anteriores
   según su texto.
4. Plan/MVP mandan sobre el alcance inmediato.

No copie ni redefina modelos Pydantic. Importe `comprehension_verification.contracts.models`.

## Arquitectura E0/E1

- adaptadores de parser seguros -> EvidenceUnit con procedencia;
- dos pipelines explícitos: actividad y submission;
- registry P01-P11 -> ModelGateway -> proveedor mock/real;
- validación estructural y contextual separada;
- planificador determinista antes de generación;
- Assessment y EvaluationGuide JSON separados; HTML/PDF son vistas derivadas;
- artefactos locales son solo desarrollo/fixtures, no operación productiva.
- shell E1 privado y tenant-scoped; Supabase se usa para Auth y PostgreSQL;
- archivos E1 en R2 privado mediante capacidades firmadas de corta vida;
- jobs técnicos durables y estado de dominio son conceptos separados;
- E1 procesa exactamente una submission por actividad y exige aprobación
  humana de blueprint y assessment;
- `CVA_MODEL_MODE=mock` es el modo de cierre; P10 sigue deshabilitado.
- en cloud, `CVA_DATABASE_URL` debe usar explícitamente
  `postgresql+psycopg://`; SQLite y drivers implícitos fallan antes del arranque;
- `/api/health` es liveness sin dependencias y `/api/readiness` comprueba
  PostgreSQL y la superficie de migración esperada;
- cada ejecución del worker reclama como máximo un job y Cloud Run usa
  `max_retries = 0`; retry funcional general sigue fuera de Etapa 1;
- Terraform es el único propietario de la imagen de Service/Job y solo acepta
  referencias inmutables `@sha256`; Cloud Build construye, prueba y publica.

## Comandos previstos

```bash
make install
make contracts
make fixtures
make test
make test-cov
make stage0-demo
make stage0-fail
make stage0-injection
make frontend-install
make frontend-typecheck
make frontend-test
make frontend-build
make postgres-prepare CVA_TEST_POSTGRES_URL=postgresql://...
make postgres-e2e CVA_TEST_POSTGRES_URL=postgresql://...
make postgres-sensitive CVA_TEST_POSTGRES_URL=postgresql://...
make secrets-check
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
