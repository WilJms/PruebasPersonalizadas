# Manifiesto de evidencia — Etapa 2

Fecha inicial: 2026-08-07; evidencia externa observada hasta 2026-08-08 UTC.
Este manifest no contiene secretos, URLs firmadas, tokens, connection strings
ni contenido estudiantil.

## Identidad

| Campo | Valor |
|---|---|
| `STAGE2_BASELINE_SHA` | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Rama | `codex/stage2-experimental-mvp` |
| `STAGE2_RUNTIME_SHA` | `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` |
| PR | draft `#2` |
| Modelo | MOCK |
| P10 | disabled |
| Datos | sintéticos |

`STAGE2_RUNTIME_SHA` identifica exactamente el código probado y desplegado.
El commit documental que incorpore este manifest tendrá otra identidad y su
propia CI; no se presenta `44b9483…` como SHA de ese commit posterior.

## Evidencia local reproducible

| Evidencia | Clasificación | Resultado |
|---|---|---|
| `make contracts` | LOCAL_REAL | PASS; 1.2.0 / 53 roots / 140 defs / 274 refs |
| Regenerar fixtures/OpenAPI/TS + checksums | LOCAL_REAL | PASS; sin drift |
| `make test` | LOCAL_REAL + MOCK_MODEL | 407 passed, 16 PG-only skipped |
| parser+sandbox | LOCAL_REAL | 57 passed |
| `pytest deploy/tests/test_deploy_artifacts.py` | LOCAL_REAL | 11 passed |
| secret scan | LOCAL_REAL | PASS, 275 archivos versionables |
| Terraform fmt/init/validate | LOCAL_REAL | PASS |
| Frontend typecheck/Vitest/build/audit | LOCAL_REAL | PASS / 32 tests / 87 módulos / 0 vulnerabilidades |
| Playwright E1 y E2 | LOCAL_REAL_BROWSER | 1 passed + 2 passed |
| Docker runtime/parser | LOCAL_REAL | PASS; imagen local `sha256:5644dfadccfb1e43f0ce3155912fba44ba069d138199df3ca9d77e51aadf764c` |
| PG16 | POSTGRESQL_REAL | migración/recovery/readiness/regresión PASS |
| PG17 | POSTGRESQL_REAL | migración/recovery/readiness/regresión PASS |

Hashes generados observados:

| Artefacto | SHA-256 |
|---|---|
| `specification/contracts.schema_v1.1(1).json` | `6cefb26e52aa803fc96cbbf2edd2a12ff35cacc25b346375ee1c8e6165851c64` |
| `tests/fixtures/openapi/stage1-v1.json` | `766bbaf082c039b2eb4be9bc3441ad9661bf9c33a2544ab6e9206f9ee4e571d7` |
| `frontend/src/api/generated.ts` | `50e9c660812b8dfcbff934866f7eacbd57b7d74849cb3f5f2653ee0cfb965c19` |

## Evidencia CI y cloud del runtime probado

| Boundary | ID/valor | Clasificación | Estado |
|---|---|---|---|
| Commit runtime | `44b94830bf3346a8fcbc0a8ce11247a42ae5daf5` | CI_REAL + CLOUD_REAL | PASS |
| PR draft | `#2` | CI_REAL | PASS |
| CI push | `31232751301` — 7/7 | CI_REAL | SUCCESS |
| CI PR | `31232752740` — 7/7 | CI_REAL | SUCCESS |
| Supabase migration 003 | `202608070003`, SHA-256 `6bb9de336b176e89abced2dc56032b83c05e4613c9f2462cde3835573a22df61`, aplicada una vez | CLOUD_REAL + POSTGRESQL_REAL | PASS |
| Backup pre-003 | `/private/tmp/cva-stage2-pre003-20260808T002738Z.dump`, SHA-256 `30b39631dda914245196f3cad87cb740b7b2c7294084df02f93fd83bf13cdd2e` | CLOUD_REAL | PASS |
| Cloud Build | `aad1bf58-966e-44f9-ad10-5d7b81144854` | CLOUD_REAL | SUCCESS / VERIFIED |
| OCI digest | `sha256:0c6be928c698cd052763c9daf683ae19d4f5b8a99cba06b54fc32e244d70044e` | CLOUD_REAL | PASS |
| Provenance | SLSA 3 v1, `GoogleHostedWorker` | CLOUD_REAL | PASS |
| Continuous scan | `FINISHED_SUCCESS` | CLOUD_REAL | PASS |
| SBOM | no observado ni capturado | NOT_OBSERVED | NO CLAIM |
| Terraform apply | 0 add / 2 change / 0 destroy | CLOUD_REAL | PASS |
| Terraform no-drift | dos planes live independientes | CLOUD_REAL | PASS / PASS |
| Service/Job | Ready, mismo digest; `mock`, P10 false, libmagic true | CLOUD_REAL | PASS |
| Health/readiness | liveness y PostgreSQL/superficie de migración | CLOUD_REAL | PASS |
| Cloud E2E 1–38 | state `/private/tmp/cva_stage2_cloud_e2e_state_e2e08080110.json`, SHA-256 `38b67798cdc8de3fd60a9464cb4a781cd8c3111f7b6cba3f15a41df75155b628` | CLOUD_REAL + MOCK_MODEL | 38/38 PASS |
| Pasos 12 y 33–36 | estados deterministas sembrados por administración y comprobados por API real | CLOUD_REAL + CONTROLLED_ADMIN_SEED | PASS |
| Browser real | desktop 1440 px y mobile 390 px, cierre/reapertura | CLOUD_REAL_BROWSER | PASS; 0 errores de consola, 0 overflow global |
| Limpieza Auth | dos usuarios iniciales y los efímeros finales eliminados | CLOUD_REAL | 0 restantes |
| Estado operacional final | jobs activos 0; capabilities persistidas 0 | CLOUD_REAL | PASS |
| Logs finales | errores 0; fugas 0 | CLOUD_REAL | PASS |

El recorrido cloud ejercitó retry/resume y su lineage contra el runtime real;
la semántica de éxito de esas transiciones procede de local/CI. Los pasos 12 y
33–36 no representan fallos naturales del proveedor: son
`CONTROLLED_ADMIN_SEED`. La evidencia sintética de DB/R2 se retuvo
deliberadamente; solo los usuarios Auth efímeros se eliminaron. El state y las
capturas del browser son evidencia externa fuera del repositorio, no artefactos
versionados.

## Límite de la aceptación

P0/P1 abiertos: 0/0; P2/P3: 3/1. La evidencia autoriza únicamente un piloto
controlado con fixtures sintéticos, modelo mock y P10 deshabilitado. Datos
estudiantiles reales, modelo real, P10 y Etapa 3 siguen bloqueados. ClamAV no
está instalado y esa ausencia permanece documentada.

## Auditoría final focalizada y custodia externa

La auditoría final del 2026-08-08 cerró cuatro P1 adicionales: replay exacto de
la reserva de upload, recuperación de actividad después de cancel, conteo
canónico de retry y atomicidad cancel/action por pregunta. La regresión del
nuevo candidato pasó 410 pruebas con 16 skips PostgreSQL explícitos, cobertura
79%, parser 57/57, deploy 11/11, frontend 32/32, Playwright 1+2, Terraform,
secret scan y los tres límites Stage 0. Los artefactos generados continúan sin
drift.

La evidencia cloud anterior permanece ligada a `44b9483…`. No se afirma que
las cuatro correcciones nuevas estén desplegadas: quedan ligadas al commit
candidato y a su CI. La revisión browser no mutante del runtime desplegado
repitió desktop/390 px con consola y overflow global en cero.

No existía un paquete durable externo E2. Se creó el siguiente core fuera de
Git, ligado al candidato auditado `d905557eed4a1f4bb38e8aef2a7823beeba5064a`:

| Campo de custodia | Valor |
|---|---|
| Nombre lógico | `STAGE2_FINAL_AUDIT_d905557_20260808T165002Z` |
| Archivo | `STAGE2_FINAL_AUDIT_d905557_20260808T165002Z.tar.gz` |
| Fecha de materialización | `2026-08-08T17:00:36Z` |
| SHA-256 del tar | `cb5e61e25d43a866bd11a0126bf229636fae57366c17dbdba6090657e0bd978d` |
| Inventario | `INVENTORY.sha256`, 14 payload files; checksum verificado después de extracción |
| Validación | sin rutas absolutas/traversal, symlinks, devices ni diferencias pre/post extracción |

El paquete contiene solo documentos/resúmenes sanitizados y la migración 003;
excluye dumps, states, screenshots/logs crudos, credenciales, URLs autenticadas,
capabilities y contenido estudiantil. Debe custodiarse fuera de Git con acceso
del propietario, conservar juntos el tar, su `.sha256` y su `.contents.txt`, y
verificarse con `shasum -a 256 -c` antes de cualquier traslado. Este commit de
custodia no cambia el código auditado.

La CI del candidato auditado terminó verde: push `31267922067` y PR
`31267923824`, 7/7 cada uno. Cloud Build
`40d124f3-8037-49be-8330-49b7bec12aa5` terminó `SUCCESS/VERIFIED` con source
revision exacta, digest
`sha256:4ef1e548359230a981eeeea2e3f002c8304dc835e0ee9c8b4705889b42caf468`,
provenance SLSA v1 y scan `FINISHED_SUCCESS`; no se observó referencia SBOM.
La imagen fue construida y smoke-tested, no desplegada por esta auditoría.
