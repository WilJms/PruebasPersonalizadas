# Guía para agentes

## Alcance actual

`STAGE2_GATE_OPEN` desde 2026-08-07, sobre
`STAGE2_BASELINE_SHA=80dd57dbf38d56929c307eca956833c31e53bf33`.

- Etapa 0: cerrada y protegida por regresión.
- Etapa 1: cerrada y protegida por regresión.
- Etapa 2: activa exclusivamente para el entorno experimental usable descrito
  en la especificación, el plan, el MVP y ADR-030 a ADR-037.
- Etapa 3: no autorizada.
- Datos estudiantiles reales: no autorizados. El Service web y todo workload
  ordinario del producto cloud conservan `CVA_MODEL_MODE=mock` y
  `CVA_P10_ENABLED=false`.
- IA real sólo se autoriza en un gate de evaluación aislado, sintético,
  explícitamente aprobado, con frontera hash-bound, ledger exactly-once y caps
  de requests/costo según ADR-035/ADR-036. Un Cloud Run Job y una service
  account eval-only, separados del worker ordinario, no autorizan por sí mismos
  una llamada: exigen claim exacto y una attestation durable específica del job
  antes de resolver la clave o construir transporte.

La apertura incluye múltiples submissions, ingestión DOCX segura,
retry/cancel/resume funcional, acciones y regeneración localizada por pregunta,
aprobación masiva, exportaciones, cobertura, métricas y feedback de Etapa 2.
No incluye LMS, OCR, calificación, detección de IA, multi-tenant SaaS ni otras
historias de Etapa 3.

## Autoridad canónica

1. `specification/models_v1.1(1).py` es la única fuente manual de contratos.
2. `specification/contracts.schema_v1.1(1).json` es generado y nunca se edita a
   mano.
3. Aplicar ADR aceptados; ADR-030 a ADR-037 sustituyen decisiones anteriores
   según su texto.
4. Plan/MVP mandan sobre el alcance inmediato.

No copie ni redefina modelos Pydantic. Importe `comprehension_verification.contracts.models`.

## Arquitectura E0/E1/E2

- adaptadores de parser seguros -> EvidenceUnit con procedencia;
- dos pipelines explícitos: actividad y submission;
- registry P01-P11 -> ModelGateway -> proveedor mock/real;
- validación estructural y contextual separada;
- planificador determinista antes de generación;
- autoridad objetivo formalizada por `pipeline-authority/1.0.0`: actividad
  P01→P02→P03→P04→preflight determinista→aprobación docente; por submission
  P06→planner determinista→P07→validaciones deterministas→revisión/aprobación
  docente→P09. P05/P08 son inactivos en el objetivo y P10 sigue deshabilitado;
  el cutover runtime de P05 está completo con lectura/recovery histórico;
  el cutover de P08 y el orden objetivo de P09 permanecen pendientes;
- Assessment y EvaluationGuide JSON separados; HTML/PDF son vistas derivadas;
- artefactos locales son solo desarrollo/fixtures, no operación productiva.
- shell E1 privado y tenant-scoped; Supabase se usa para Auth y PostgreSQL;
- archivos E1 en R2 privado mediante capacidades firmadas de corta vida;
- jobs técnicos durables y estado de dominio son conceptos separados;
- E1 procesa exactamente una submission por actividad; E2 retira esa
  restricción mediante migración compatible y conserva aprobación humana de
  blueprint y assessment;
- `CVA_MODEL_MODE=mock` es el modo de cierre del producto, del Service web y
  del worker ordinario; P10 sigue deshabilitado. Una evaluación cloud sintética
  puede aprovisionar un Job/SA eval-only separado, no invocable por el Service
  web. El flag de infraestructura sólo entrega a esa superficie una referencia
  no secreta y caps. El worker eval-only debe reclamar el job exacto, consumir
  una autorización append-only ligada a
  tenant/kind/aggregate/attempt, SHA candidato, boundary hash, hashes exactos de
  artefactos, ruta/modelo, expiración y caps; recién entonces resuelve la clave
  y construye el adapter. Sin esa secuencia el proveedor es inalcanzable.
- en cloud, `CVA_DATABASE_URL` debe usar explícitamente
  `postgresql+psycopg://`; SQLite y drivers implícitos fallan antes del arranque;
- `/api/health` es liveness sin dependencias y `/api/readiness` comprueba
  PostgreSQL y la superficie de migración esperada;
- cada ejecución del worker reclama como máximo un job y Cloud Run usa
  `max_retries = 0`; retry/cancel/resume de E2 pertenece a la aplicación y a
  sus `stage_runs`, nunca a reintentos opacos de infraestructura;
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
make openai-convergence-dry-run
# Sólo con autorización humana, IDs únicos, ledger durable, reporte y caps:
make openai-convergence-real EXECUTION_ID=... AUTHORIZATION_ID=... LEDGER=... REPORT=... SECRET_VERSION_RESOURCE=projects/.../versions/N
make postgres-prepare CVA_TEST_POSTGRES_URL=postgresql://...
make postgres-e2e CVA_TEST_POSTGRES_URL=postgresql://...
make postgres-sensitive CVA_TEST_POSTGRES_URL=postgresql://...
make postgres-stage2-recovery CVA_TEST_POSTGRES_URL=postgresql://...
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
