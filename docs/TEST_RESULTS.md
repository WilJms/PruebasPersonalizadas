# Resultados verificables de la corrección final E0/E1

Fecha de ejecución: **2026-08-01** (`America/Santiago`). Corte de este registro:
`2026-08-01T20:23:20-04:00`.

Solo se marca como ejecutado lo observado en esta corrección. `$PY` representa
`/tmp/cva-stage1-final-venv-019fbfaa/bin/python`; las credenciales PostgreSQL
fueron ficticias, efímeras y no se registran. Todos los casos usaron
`CVA_MODEL_MODE=mock` y `CVA_P10_ENABLED=false`.

## Precheck Git obligatorio

| Comando | Fecha | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `pwd` | 2026-08-01 | 0 | Raíz esperada. | Inspección local. |
| `git rev-parse --show-toplevel` | 2026-08-01 | 0 | `/Users/wiljms/Documents/PruebasPersonalizadasCodex`. | Ninguna. |
| `git remote -v` | 2026-08-01 | 0 | `origin` apunta a `WilJms/PruebasPersonalizadas`. | No prueba autenticación de escritura. |
| `git branch --show-current` | 2026-08-01 | 0 | `fix/stage1-external-readiness`. | Ninguna. |
| `git log --oneline --decorate -5` | 2026-08-01 | 0 | `origin/main` y baseline en `dadaaa7`. | Solo historial local/fetched. |
| `git status --short --untracked-files=all` | 2026-08-01 | 0 | Se observaron y preservaron `.gitignore`, `.dockerignore` y el workflow preexistentes. | Estado previo al trabajo. |
| diffs solicitados de `.gitignore`, `.dockerignore` y `.github/workflows/ci.yml` | 2026-08-01 | 0 | Los tres cambios locales quedaron registrados antes de editar. | Los dos `--no-index` usan 1 cuando existe diferencia; `|| true` dejó el bloque en 0 como se pidió. |

## Entornos limpios

| Comando | Fecha | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| Python 3.12.13 bundled: `-m venv /tmp/cva-stage1-final-venv-019fbfaa` | 2026-08-01 | 0 | Entorno nuevo fuera del workspace. | Temporal local. |
| `$PY -m pip install -e '.[dev]'` | 2026-08-01 | 0 | Proyecto y dependencias dev instalados limpiamente. | El primer intento sandbox falló por DNS; el reintento de red autorizado fue el PASS. |
| `make frontend-install` con Node bundled y caché npm temporal vacía | 2026-08-01 | 0 | `npm ci`, 158 paquetes desde `package-lock.json`. | Un primer intento sandbox terminó 2 por el entorno npm; el reintento autorizado terminó 0. |

## Contratos, backend y Stage 0

| Comando | Hora | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `make contracts PYTHON=$PY` | 20:02 | 0 | Schema 1.1.0: 46 roots, 112 `$defs`, 231 referencias y 8 fixtures. Hash modelo `38c6691a…671ba`; hash schema `e7f0b54d…cc12f`. | Validación/generación local. |
| `make fixtures PYTHON=$PY` | 20:02 | 0 | Fixtures reconstruidos y validados; PDF contractual determinista, 3684 bytes. | No modificó manualmente el schema. |
| `make test PYTHON=$PY` | 20:02 | 0 | **134 passed, 7 skipped**, 9.96 s. | Los 7 skips requieren PostgreSQL y se ejecutaron aparte. Suite general usa SQLite local/fakes. |
| `make test-cov PYTHON=$PY` | 20:02 | 0 | **134 passed, 7 skipped**, cobertura total **82%**, 24.56 s. | Misma separación PostgreSQL. |
| `make stage0-demo PYTHON=$PY` | 20:03 | 0 | `READY`, 3 preguntas, 13 calls mock, outcome esperado, sin red/tools. | Fixture sintético. |
| `make stage0-fail PYTHON=$PY` | 20:04 | 0 | Diagnóstico insuficiente esperado, 5 calls, sin Assessment parcial. | Fixture sintético. |
| `make stage0-injection PYTHON=$PY` | 20:04 | 0 | `READY`; injection presente en fuente y ausente en generación, sin red/tools. | Fixture sintético hostil. |
| dos procesos `$PY -m comprehension_verification.cli run-synthetic --case sufficient --output /tmp/cva-stage1-repro-{a,b}-019fbfaa` | 20:04 | 0 / 0 | Ambos recorridos terminaron `READY`. | Procesos locales independientes. |
| `diff -rq /tmp/cva-stage1-repro-a-019fbfaa /tmp/cva-stage1-repro-b-019fbfaa` | 20:04 | 0 | Directorios idénticos byte a byte, incluidos JSON, HTML y PDF. | Reproducibilidad en el mismo SO/runtime. |
| `$PY -m pytest deploy/tests/test_deploy_artifacts.py tests/test_stage1_runtime_guards.py -q` | 20:09 | 0 | **25 passed**, 1 warning. | Focalizada tras las correcciones finales. |

La única advertencia de pytest es `StarletteDeprecationWarning` del adaptador de
`TestClient`; no afecta el runtime ni ocultó fallos.

Hashes de los seis exports reproducibles de `sufficient`:

- Assessment JSON `bbe394bd14cbe88acec94dbf727a69253923ee13d0b91badb1ca041265a9db44`;
- Assessment HTML `180c25be27f0e3b02c761ee446d9788cac620b8feb8677c38b8461d2d732b89b`;
- Assessment PDF `26a5be77a53fa58bc55d180e16b00f43894ab9e325a3653fae2fe23a7622dd69`;
- Guide JSON `87858e8a070a8e5ef7fc0bf18506d5b571bdf272fb7ecb4017d0dbb030938d41`;
- Guide HTML `d7d489e28428cbfb5b1043dacdfacd61ce5cd522c5136653746d2da3ec386f18`;
- Guide PDF `ba50b5e4a17e7a64fad767b34b24000c38023ff47b55c611a0e7f387a7ad31dd`.

## Frontend

| Comando | Hora | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `make frontend-typecheck` | 20:06 | 0 | TypeScript sin errores. | Node 24.14 local; CI declara Node 22.13.1 compatible. |
| `make frontend-test` | 20:06 | 0 | Vitest: **4 files, 16 tests passed**. | DOM simulado; no servicio cloud. |
| `make frontend-build` | 20:06 | 0 | Vite 8.2.0, 80 módulos, bundle JS 411.18 kB (116.47 kB gzip). | Build local. |
| `npm audit --audit-level=high` | 20:06 | 0 | **0 vulnerabilidades**. | Snapshot del registry en la fecha indicada. |

## PostgreSQL 16 real temporal

Se usó `postgres:16-bookworm`, PostgreSQL **16.14**, solo en loopback. La
segunda base `cva_stage1_final` se creó vacía para la ejecución final. Los
comandos siguientes recibieron la URL mediante `$CVA_TEST_POSTGRES_URL`; no se
registra la URL autenticada.

| Comando | Fecha | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `make postgres-prepare CVA_TEST_POSTGRES_URL=… PYTHON=$PY` | 2026-08-01 | 0 | Migración aplicada a DB vacía; SHA `465ec240…fa27`; 24 tablas, 24 RLS y 2 triggers append-only. | Comprueba tablas/columnas y estas invariantes seleccionadas; **no** afirma equivalencia exacta con ORM. |
| `make postgres-e2e CVA_TEST_POSTGRES_URL=… PYTHON=$PY` | 2026-08-01 | 0 | **1 passed**: E2E E1 de una actividad/submission, reapertura y exports. | Model gateway mock; PostgreSQL real. |
| `make postgres-sensitive CVA_TEST_POSTGRES_URL=… PYTHON=$PY` | 2026-08-01 | 0 | **7 passed**: idempotencia, claim/SKIP LOCKED, unicidad, stage keys, CAS/ETag, tenant y append-only. | Contenedor local, no Supabase administrado. |

## Terraform y despliegue estático

| Comando | Fecha | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `terraform fmt -check -recursive deploy/terraform` | 2026-08-01 | 0 | Sin drift de formato. | Estático. |
| `terraform -chdir=deploy/terraform init -backend=false -input=false` | 2026-08-01 | 0 | Provider `hashicorp/google 6.50.0` desde lockfile. | Sin backend, credenciales ni acceso cloud. |
| `terraform -chdir=deploy/terraform validate` | 2026-08-01 | 0 | Configuración válida con Terraform 1.14.3. | No se ejecutó plan/apply. |
| `$PY -m pytest deploy/tests/test_deploy_artifacts.py -q` | 2026-08-01 | 0 | **8 passed**. | Regresión estática de IaC/artefactos. |
| parseo `yaml.safe_load` de `deploy/cloudbuild.yaml` | 2026-08-01 | 0 | YAML válido. | No ejecuta Cloud Build. |
| `sh -n deploy/docker-entrypoint.sh` | 2026-08-01 | 0 | Sintaxis shell válida. | No sustituye el smoke Docker. |

## Docker

Motor local: Docker Desktop 29.5.3. Las imágenes finales se reconstruyeron
después de la última modificación del Dockerfile.

| Comando/acción | Fecha | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `docker build --target runtime -t cva-runtime:local .` | 2026-08-01 | 0 | Target runtime construido. | Arquitectura local; no push. |
| `docker build --target audit -t cva-audit:local .` | 2026-08-01 | 0 | Target audit construido con fixtures. | Arquitectura local; no push. |
| runtime con filesystem read-only, tmpfs, `--cap-drop ALL` y adaptadores locales; `GET /api/health` | 2026-08-01 | 0 | `status=ok`, Stage 1, mock. | Liveness intencionalmente no consulta dependencias externas. |
| mismo runtime; `GET /api/readiness` | 2026-08-01 | 0 | `status=ready`; se comprobó además que `/app/fixtures` no existe. | SQLite seguro solo para smoke local; cloud exige PostgreSQL. |
| target audit: `run-synthetic` para `sufficient`, `insufficient`, `injection` | 2026-08-01 | 0 / 0 / 0 | Outcomes esperados; JSON/HTML/PDF presentes para sufficient/injection y ausentes para insufficient. | Fixtures sintéticos; no proveedor real. |
| cleanup automático del contenedor runtime | 2026-08-01 | 0 | Contenedor eliminado incluso ante fallo por `trap`. | Las imágenes locales se conservaron. |

## Seguridad, integridad y Git

| Comando | Fecha | Exit | Resultado | Limitación |
|---|---|---:|---|---|
| `$PY scripts/check_secrets.py` | 2026-08-01 | 0 | Sin hallazgos de alta confianza en archivos versionables. | Heurístico; se complementa con revisión de rutas ignoradas sin mostrar valores. |
| revisión de rutas `.env`, tfvars/state, credenciales y tokens ignorados | 2026-08-01 | 0 | Sin material versionable que requiera saneamiento. | No se imprimieron contenidos. |
| `git diff --check` y `git diff --cached --check` | 2026-08-01 | 0 / 0 | Sin errores de whitespace antes y después del staging. | Validación local del diff. |
| revisión final: status/stat/diff, workflow en `git ls-files` y búsqueda de caches indexados | 2026-08-01 | 0 | Workflow versionado; ningún `__pycache__`, `.pyc`, `.tsbuildinfo` o `.DS_Store` permanece en el índice. | Revisión del commit local. |
| `git commit -m "Prepare Stage 1 for external verification"` | 2026-08-01 | 0 | Commit funcional `59c932d`, 108 rutas. | Rama `fix/stage1-external-readiness`, no `main`. |
| `git push -u origin fix/stage1-external-readiness` | 2026-08-01 | 0 | Rama publicada sin force. | No se hizo merge. |
| creación del PR draft `#1` con base `main` | 2026-08-01 | 0 | PR abierto: `WilJms/PruebasPersonalizadas#1`. | Permanece draft y sin merge. |
| GitHub Actions run `30725021051` sobre `59c932d` | 2026-08-01 | 0 | **SUCCESS**: backend/Stage 0, PostgreSQL 16, frontend, Terraform/deploy y Docker verdes. | CI real del commit funcional; no prueba cloud real. |

## Intentos fallidos que no se contabilizan como PASS

| Comando/intento | Exit | Causa y acción |
|---|---:|---|
| instalación Python inicial dentro del sandbox | 1 | DNS bloqueado; se repitió con autorización y entorno temporal limpio. |
| primer `make frontend-install` dentro del sandbox | 2 | npm no pudo completar su handler/caché; se repitió con caché temporal writable y terminó 0. |
| primer acceso PostgreSQL desde sandbox | no cero | Loopback restringido; se repitió con autorización contra el mismo contenedor local. |
| primer `terraform validate` sandbox | 1 | Handshake del provider restringido; el reintento autorizado terminó 0. |
| `pytest tests/test_deploy_artifacts.py …` | 4 | Error del operador: el archivo está bajo `deploy/tests/`; el comando corregido pasó 25 pruebas. |

## Pendiente externo real

No se ejecutó `terraform plan/apply`, Cloud Build, GCP, Cloud Run Service/Jobs,
Supabase PostgreSQL/Auth o Cloudflare R2. E1-11 sigue parcial hasta completar
`docs/EXTERNAL_SETUP.md`. No se llamó a un proveedor de IA real y no se
implementó ninguna capacidad de Etapa 2.
