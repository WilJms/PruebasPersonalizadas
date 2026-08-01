# Resultados de pruebas realmente ejecutadas

Fecha: **2026-08-01** (`America/Santiago`, corte
`2026-08-01T17:11:34-04:00`).

Este archivo no usa la existencia de tests como evidencia. Cada fila registra
una ejecución observada, su código de salida y su limitación. En los comandos,
`$AUDIT` abrevia el path literal `/tmp/cva-stage01-audit.DO1Ym0` y `$PY`
abrevia `$AUDIT/venv/bin/python`.

## Instalación limpia

| Comando ejecutado | Exit | Resultado observado |
|---|---:|---|
| Python 3.12.13 bundled `-m venv $AUDIT/venv` | 0 | Entorno temporal nuevo, separado del workspace. |
| `$PY -m pip install -e '.[dev]'` | 0 | `comprehension-verification 0.2.0` y dependencias dev instaladas. El primer intento dentro del sandbox falló por DNS; el reintento autorizado con red terminó 0. |
| mover `frontend/node_modules` fuera del árbol y ejecutar Node 24.14 + npm CLI `ci` | 0 | Instalación desde `package-lock.json`: 158 paquetes. Se repitió tras sustituir el router; no se reutilizó el árbol incremental. |

El Dockerfile repitió `npm ci` con `node:22-bookworm-slim`: 159 paquetes,
audit integrado 0 vulnerabilidades.

## Contratos y Python

| Comando ejecutado | Exit | Resultado observado |
|---|---:|---|
| `$PY -m comprehension_verification.cli validate-contracts` | 0 | `PASS`: schema 1.1.0, 46 roots, 112 definiciones, 231 referencias, 8 fixtures; `models_sha256=38c6691a12bb459cfb60fc1f6b0b1cf4d78d00ec59838a00738f21b3dcc671ba`; `schema_sha256=e7f0b54d781afdcf7441371906a815f358b28af4b52854e0b8bcbc6a351cc12f`. |
| `$PY -m pytest` (baseline) | 1 | 115 passed, 2 failed. Fallos reales: IDs de criterios inexistentes en fixtures injection/holdout y precedencia diagnóstica para evidencia inventada. Ambos fueron corregidos. |
| `$PY -m pytest tests/test_cli.py::… tests/test_validation.py::…` | 0 | Las dos regresiones corregidas pasaron. |
| `$PY -m pytest` (final tras todas las correcciones) | 0 | **117 passed**, 1 warning, 8.63 s. |
| `$PY -m pytest --cov=comprehension_verification --cov-report=term-missing` | 0 | **117 passed**, cobertura total **82%**, 24.54 s. |
| `$PY -m pytest deploy/tests/test_deploy_artifacts.py` | 0 | **6 passed**, 0.26 s. |

Warning real de las suites Python: `StarletteDeprecationWarning` sobre el uso de
`httpx` por `starlette.testclient`; no produjo fallo ni cambia el runtime.

## Recorridos Stage 0 y reproducibilidad

| Comando ejecutado | Exit | Resultado observado |
|---|---:|---|
| `$PY -m comprehension_verification.cli run-synthetic --case sufficient --output $AUDIT/final-sufficient` | 0 | `READY`, outcome esperado, 3 preguntas, 13 model calls mock, assessment `NEEDS_REVIEW`, sin red ni tools. |
| `$PY -m comprehension_verification.cli run-synthetic --case insufficient --output $AUDIT/final-insufficient` | 0 | `INSUFFICIENT_DISTINCT_QUESTION_OPPORTUNITIES`, outcome esperado, 5 calls, sin Assessment parcial. |
| `$PY -m comprehension_verification.cli run-synthetic --case injection --output $AUDIT/final-injection` | 0 | `READY`, 3 preguntas; injection presente en fuente y ausente en preguntas; mock sin red/tools. |
| Dos procesos independientes `run-synthetic --case sufficient`, outputs `$AUDIT/repro-a` y `$AUDIT/repro-b` | 0 / 0 | Los seis hashes de export coincidieron. |
| `diff -rq $AUDIT/repro-a $AUDIT/repro-b` | 0 | Directorios idénticos byte a byte, incluidos JSON, HTML y PDF. |

Hashes reproducibles del caso suficiente:

- Assessment JSON `bbe394bd14cbe88acec94dbf727a69253923ee13d0b91badb1ca041265a9db44`;
- Assessment HTML `180c25be27f0e3b02c761ee446d9788cac620b8feb8677c38b8461d2d732b89b`;
- Assessment PDF `26a5be77a53fa58bc55d180e16b00f43894ab9e325a3653fae2fe23a7622dd69`;
- Guide JSON `87858e8a070a8e5ef7fc0bf18506d5b571bdf272fb7ecb4017d0dbb030938d41`;
- Guide HTML `d7d489e28428cbfb5b1043dacdfacd61ce5cd522c5136653746d2da3ec386f18`;
- Guide PDF `ba50b5e4a17e7a64fad767b34b24000c38023ff47b55c611a0e7f387a7ad31dd`.

## Frontend final

Los comandos usaron el Node bundled y el npm extraído al entorno temporal; son
equivalentes a `npm ci`, `npm run …` dentro de `frontend/`.

| Comando ejecutado tras instalación limpia final | Exit | Resultado observado |
|---|---:|---|
| `npm ci` | 0 | 158 paquetes desde lockfile. |
| `npm run typecheck` | 0 | `tsc -b --pretty false`, sin errores. |
| `npm run test` | 0 | Vitest 4.1.10: **4 files, 16 tests passed**, 896 ms. |
| `npm run build` | 0 | Vite 8.2.0: 80 módulos; JS 411.18 kB / gzip 116.47 kB. |
| `npm audit --json` | 0 | **0 vulnerabilidades** en 181 dependencias reportadas. |

Trail correctivo real: Vite/Vitest antiguos se bloquearon con el Node
disponible y el typecheck inicial mostró tres errores; se actualizaron las
herramientas y tipos. React Router 7.18.2 dejó 2 advisories high de RSC; el
downgrade recomendado a 7.11.0 abrió múltiples XSS/RCE/DoS. Se sustituyó por
Wouter 3.10.0, se eliminó React Router y la reinstalación/audit final quedó 0.

## PostgreSQL real y migración

PostgreSQL temporal: contenedor `postgres:16-bookworm`, PostgreSQL **16.14**
ARM64, host loopback `127.0.0.1:55432`. No se usó SQLite para esta evidencia.

| Comando ejecutado | Exit | Resultado observado |
|---|---:|---|
| creación/arranque de `cva-audit-pg-019fbeaa` y conexión `psycopg` | 0 | Servidor real accesible. |
| `$PY scripts/prepare_postgres.py --database-url 'postgresql://cva:…@127.0.0.1:55432/cva_audit_verify'` | 0 | Migración `202607310001_stage1.sql` aplicada a DB vacía; SHA-256 `077daf309162b404820356ed6acbf9b1d8e8d3b9e829b3251d38a25b6e0c35d9`; **24 tablas, 24 con RLS y 2 triggers append-only**, equivalencia exacta con ORM. |
| `CVA_TEST_DATABASE_URL='postgresql://cva:…@127.0.0.1:55432/cva_audit_verify' $PY -m pytest tests/test_stage1_web.py::test_stage1_single_submission_mock_e2e_survives_new_browser_session` | 0 | **1 passed**: actividad, P01–P05, aprobación, submission, worker P06–P09, reapertura, evidence, approval y exports sin nuevas model calls. |

La contraseña mostrada aquí está redactada; la prueba usó una credencial local
efímera sin valor externo.

## Docker

Docker Desktop 29.5.3; configuración temporal sin credential helper para evitar
un helper local bloqueado.

| Comando/acción ejecutada | Exit | Resultado observado |
|---|---:|---|
| `docker build --tag cva-stage01-final:20260801 .` (build final) | 0 | Imagen final `e16bb758ee72`; frontend compilado y npm reportó 0 vulnerabilidades. |
| arrancar imagen final con adaptadores locales y consultar `curl …/api/health` | 0 | `{"status":"ok","stage":"1","model_mode":"mock"}`. |
| `docker build --target audit --tag cva-stage01-audit-fixtures:20260801 .` | 0 | Target de verificación construido sin incorporar fixtures al target runtime. |
| ejecutar dentro del target `audit`: `python -m comprehension_verification.cli run-synthetic --case sufficient --output /tmp/exports/sufficient` | 0 | Proceso del contenedor exit 0; se extrajeron **32 archivos**, incluidos Assessment/Guide JSON, HTML, PDF y manifests. |
| `docker stop --time 5` sobre web final, web previo y PostgreSQL temporal | 0 | Los tres procesos se detuvieron; Docker avisó que `--time` está deprecado en favor de `--timeout`. |
| `docker rm -v` sobre los cinco contenedores `cva-audit-*` | 0 | Se eliminaron los contenedores y el volumen PostgreSQL efímero; consulta final a Engine API devolvió `[]`. Las imágenes de auditoría se conservaron. |

Fallo correctivo registrado: el primer intento de export dentro de la imagen
runtime terminó 1 (`CLI_FAILURE/FileNotFoundError`) porque los fixtures estaban
correctamente ausentes. Se añadió un target `audit` separado y el reintento
terminó 0. En este Docker Desktop, el primer request de `start` de algunas
instancias expiró a los 5 s (exit 124) y el segundo terminó 204; el proceso y
health final fueron verificados independientemente.

## Terraform, CI y artefactos de despliegue

| Comando ejecutado | Exit | Resultado observado |
|---|---:|---|
| `terraform version` | 0 | Terraform 1.14.3 darwin_arm64. |
| `terraform fmt -check -recursive deploy/terraform` | 0 | Sin drift de formato. |
| `terraform -chdir=deploy/terraform init -backend=false -input=false` | 0 | Provider oficial `hashicorp/google 6.50.0`; lockfile generado. El primer intento sandbox terminó 1 por DNS. |
| `terraform -chdir=deploy/terraform validate` | 0 | `Success! The configuration is valid.` El intento sandbox previo terminó 1 al no poder ejecutar el plugin; el reintento autorizado terminó 0. |
| parseo `yaml.safe_load` de `.github/workflows/ci.yml` y `deploy/cloudbuild.yaml` | 0 / 0 | Ambos YAML válidos. |
| `/bin/sh -n deploy/docker-entrypoint.sh` | 0 | Entrypoint válido. |
| `$PY -m pytest deploy/tests/test_deploy_artifacts.py` (final) | 0 | 6/6 en 0.23 s: ORM↔migración, RLS, runtime vars, imagen única, Terraform, IAM de source staging y R2 policies. |

CI quedó definida con jobs separados para contratos/backend/coverage/Stage 0,
PostgreSQL 16 + migración + E2E, frontend, Terraform y builds/runtime audit.
**GitHub Actions no se ejecutó remotamente** porque este repositorio no tiene
commit ni remoto verificable; solo se validaron localmente su sintaxis y los
comandos que contiene.

Corrección final de IaC: tras contrastar la cuenta dedicada de Cloud Build con
el flujo real de source staging, se habilitó `storage.googleapis.com` y se
declararon `roles/storage.bucketViewer`/`roles/storage.objectUser`. Después se
repitieron con exit 0 Terraform fmt/validate, parseo YAML, `sh -n`, los 6 tests
de deploy, contratos y la suite Python completa.

## Integración frontend/backend y E2E de navegador

Acción real con el navegador integrado contra la imagen Docker final en
`127.0.0.1:58082` (no es un test meramente escrito):

1. logout y login con el invitado precargado `teacher@example.test`;
2. actividad de 3 preguntas; uploads sintéticos de consigna y rúbrica;
3. generación/aprobación de blueprint y navegación parametrizada;
4. submission Markdown, pipeline mock hasta `NEEDS_REVIEW`;
5. apertura de las 3 fuentes exactas antes de habilitar aprobación;
6. aprobación de Assessment y generación de Assessment PDF, Guide PDF y JSON;
7. reapertura del deep link en otra pestaña, conservando sesión y estado
   aprobado.

Resultado: **PASS**, tres links de descarga, marcador aprobado único y cero
errores/warnings de consola. No se transmitieron datos reales; solo fixtures
sintéticos del repositorio.

## Lo que no se ejecutó

- ninguna llamada a proveedor de IA real; no es requisito y
  `CVA_MODEL_MODE=mock` permaneció activo;
- ningún `terraform plan/apply`, Cloud Build, despliegue, Supabase real ni R2
  real;
- ninguna historia o capacidad de Etapa 2.

Esas ausencias no se contabilizan como PASS. La verificación pendiente está
descrita en `docs/EXTERNAL_SETUP.md`.

## Integridad documental final

| Comando ejecutado | Exit | Resultado observado |
|---|---:|---|
| aserción Python sobre `docs/*.md` y `docs/IMPLEMENTATION_STATUS.md` | 0 | Fences Markdown balanceados y matriz con exactamente 8 historias E0 + 11 historias E1. |
| `rg` sobre firmas comunes de secretos reales | 0 | Sin coincidencias; los únicos `replace-with` están en checklist, ejemplos y assertions de esos ejemplos. |
| `git status --porcelain=v1 --untracked-files=all` | 0 | 127 rutas `??`; el repositorio continúa sin commit inicial. Esta limitación impide atribuir un diff histórico y ejecutar CI remota hasta que una persona revise/cree el primer commit. |
