# Estado de implementación y preparación externa

Fecha de corte local: 2026-08-01 (`America/Santiago`).

## Estado del gate

`NOT_READY_FOR_EXTERNAL_STAGE1_VERIFICATION`

El boundary local de Etapas 0 y 1 está verde. Este estado sigue siendo
provisional porque el workflow todavía debe versionarse, subirse y observarse
verde en GitHub Actions sobre el commit final. No se ha desplegado ni verificado
GCP, Supabase o R2 reales.

Cuando GitHub Actions confirme el commit final, y solo si no aparece un defecto
local nuevo, el estado de este gate puede pasar a
`READY_FOR_EXTERNAL_STAGE1_VERIFICATION`. En ningún caso autoriza Etapa 2 ni
equivale a `READY_FOR_STAGE_2`.

## Proveniencia Git comprobada

- raíz: `/Users/wiljms/Documents/PruebasPersonalizadasCodex`;
- repositorio privado: `WilJms/PruebasPersonalizadas`;
- remote `origin`: `https://github.com/WilJms/PruebasPersonalizadas.git`;
- rama de trabajo: `fix/stage1-external-readiness`;
- baseline: `origin/main` en `dadaaa7`;
- los cambios locales preexistentes de `.gitignore`, `.dockerignore` y
  `.github/workflows/ci.yml` se conservaron y completaron;
- no se trabajó en `main`, no se hizo merge, force push, reset, clean ni rebase.

## Evidencia por entorno

| Boundary | Implementado | Test escrito | Ejecutado | Resultado y límite |
|---|---:|---:|---:|---|
| Contratos y fixtures canónicos | Sí | Sí | Local, Python 3.12 | PASS; 46 roots, 112 `$defs`, 231 referencias, 8 fixtures. |
| Backend y Stage 0 | Sí | Sí | Local, SQLite y mock | PASS; 134 pruebas, 7 PostgreSQL-only omitidas; coverage total 82%. |
| Reproducibilidad `sufficient` | Sí | Sí/CI | Dos procesos locales | PASS; directorios idénticos byte a byte. |
| Frontend | Sí | Sí | Node/npm local limpio | PASS; typecheck, 16 tests, build y audit con 0 vulnerabilidades. |
| Persistencia PostgreSQL | Sí | Sí | PostgreSQL 16.14 temporal real | PASS; migración en DB vacía, E2E y 7 pruebas transaccionales. |
| Health/readiness | Sí | Sí | Unitario y Docker | PASS; liveness sin dependencias y readiness fail-closed contra esquema/DB. |
| Docker runtime/audit | Sí | Sí/CI | Docker Desktop local | PASS; ambos targets, runtime sin fixtures y tres casos sintéticos en audit. |
| Terraform/deploy estático | Sí | Sí | Terraform 1.14.3 local | PASS; fmt, init sin backend, validate, YAML, shell y 8 pruebas. No hubo plan/apply. |
| Revisión de secretos | Sí | Sí/CI | Árbol versionable local | PASS; sin hallazgos de alta confianza. No se usaron secretos externos. |
| GitHub Actions | Workflow local | Sí | Pendiente de push | No se declara PASS hasta observar el run remoto del commit final. |
| Cloud real | IaC/adaptadores preparados | Checklist | No ejecutado | E1-11 continúa parcial: GCP, Cloud Run, Supabase y R2 requieren intervención humana. |

Los comandos, fechas, códigos de salida y limitaciones están registrados en
`docs/TEST_RESULTS.md`.

## Correcciones cerradas en esta rama

- higiene Git ampliada y artefactos generados retirados del índice sin borrar
  fuentes, contratos, fixtures, migraciones, lockfiles o ejemplos;
- contexto Docker acotado; `runtime` no contiene fixtures y `audit` sí;
- CI separado en backend/Stage 0, PostgreSQL, frontend, Terraform/deploy y
  Docker, sin secretos reales, proveedor IA, despliegue ni `terraform apply`;
- `max_retries = 0` para Cloud Run Job, fallo durable en PostgreSQL y una sola
  reclamación por ejecución del worker;
- Terraform como propietario único de la imagen del Service y Job; Cloud Build
  solo construye/publica y produce una referencia inmutable `@sha256`;
- configuración cloud fail-closed: PostgreSQL explícito con driver `psycopg`,
  URL completa, auth/R2/job runner administrados, session secret no-dev,
  `CVA_MODEL_MODE=mock` y `CVA_P10_ENABLED=false`;
- `/api/health` conservado como liveness ligero y `/api/readiness` añadido con
  consulta mínima y comprobación de la superficie de migración;
- documentación de migración corregida: se validan tablas, columnas, RLS y
  triggers append-only seleccionados; no se afirma equivalencia exacta con el
  ORM;
- TTL de upload y download separados, acotados, conectados al runtime y
  probados;
- escáner de secretos que informa solo ruta/categoría/acción, nunca valores.

## Estado de las historias

- **Etapa 0:** completa localmente con mock, contratos, fixtures, regresión,
  casos sintéticos y reproducibilidad verdes.
- **E1-01/E1-03/E1-06/E1-08:** implementación y pruebas locales completas;
  conservan verificación externa de Supabase Auth/R2/Cloud Run Job.
- **E1-02/E1-04/E1-05/E1-07/E1-09/E1-10:** completas en el boundary local,
  incluidas persistencia, CAS/ETag, aislamiento tenant y append-only donde
  corresponde.
- **E1-11:** **PARCIAL** hasta completar la checklist externa real en GCP,
  Cloud Run Service/Jobs, Supabase PostgreSQL/Auth, Cloudflare R2 y Cloud Build.

## Frontera preservada

No se añadió batch, retry funcional general, cancelación, reanudación por
etapa, acciones por pregunta, regeneración localizada, aprobación masiva, DOCX
completo, OCR, LMS, métricas/feedback, calificación, detección de IA ni
proveedor IA real. El siguiente gate permitido es la verificación externa de
Etapa 1, no Etapa 2.
