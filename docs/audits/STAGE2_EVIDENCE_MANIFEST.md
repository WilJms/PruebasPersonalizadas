# Manifiesto de evidencia — Etapa 2

Fecha inicial: 2026-08-07. Este manifest no contiene secretos, URLs firmadas,
tokens, connection strings ni contenido estudiantil.

## Identidad

| Campo | Valor |
|---|---|
| `STAGE2_BASELINE_SHA` | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Rama | `codex/stage2-experimental-mvp` |
| `STAGE2_FINAL_SHA` | NOT_VERIFIED — se completa tras commit |
| PR | NOT_VERIFIED |
| Modelo | MOCK |
| P10 | disabled |
| Datos | sintéticos |

## Evidencia local reproducible

| Evidencia | Clasificación | Resultado |
|---|---|---|
| `make contracts` | LOCAL_REAL | PASS; 1.2.0 / 53 roots / 140 defs / 274 refs |
| Regenerar fixtures/OpenAPI/TS + checksums | LOCAL_REAL | PASS; sin drift |
| `make test` | LOCAL_REAL + MOCK_MODEL | 407 passed, 16 PG-only skipped |
| parser+sandbox | LOCAL_REAL | 57 passed |
| `pytest deploy/tests/test_deploy_artifacts.py` | LOCAL_REAL | 11 passed |
| secret scan | LOCAL_REAL | PASS, 270 archivos versionables |
| Terraform fmt/init/validate | LOCAL_REAL | PASS |
| Frontend typecheck/Vitest/build/audit | LOCAL_REAL | PASS / 32 tests / 87 módulos / 0 vulnerabilidades |
| Playwright E1 y E2 | LOCAL_REAL_BROWSER | 1 passed + 1 passed |
| Docker runtime/parser | LOCAL_REAL | PASS; imagen local `sha256:5644dfadccfb1e43f0ce3155912fba44ba069d138199df3ca9d77e51aadf764c` |
| PG16 | POSTGRESQL_REAL | migración/recovery/readiness/regresión PASS |
| PG17 | POSTGRESQL_REAL | migración/recovery/readiness/regresión PASS |

Hashes generados observados:

| Artefacto | SHA-256 |
|---|---|
| `specification/contracts.schema_v1.1(1).json` | `6cefb26e52aa803fc96cbbf2edd2a12ff35cacc25b346375ee1c8e6165851c64` |
| `tests/fixtures/openapi/stage1-v1.json` | `766bbaf082c039b2eb4be9bc3441ad9661bf9c33a2544ab6e9206f9ee4e571d7` |
| `frontend/src/api/generated.ts` | `50e9c660812b8dfcbff934866f7eacbd57b7d74849cb3f5f2653ee0cfb965c19` |

## Evidencia externa del SHA final

| Boundary | ID/valor | Clasificación | Estado |
|---|---|---|---|
| Commit final | pendiente | NOT_VERIFIED | PENDING |
| PR draft | pendiente | NOT_VERIFIED | PENDING |
| CI push/PR | pendiente | NOT_VERIFIED | PENDING |
| Supabase migration 003 | pendiente | NOT_VERIFIED | PENDING |
| Backup/quiesce | pendiente | NOT_VERIFIED | PENDING |
| Cloud Build | pendiente | NOT_VERIFIED | PENDING |
| OCI digest | pendiente | NOT_VERIFIED | PENDING |
| Provenance/scan/SBOM | pendiente | NOT_VERIFIED | PENDING |
| Terraform plan/apply | pendiente | NOT_VERIFIED | PENDING |
| No-drift A/B | pendiente | NOT_VERIFIED | PENDING |
| Service/Job Ready | pendiente | NOT_VERIFIED | PENDING |
| Health/readiness/private | pendiente | NOT_VERIFIED | PENDING |
| Cloud E2E sintético 1–38 | pendiente | NOT_VERIFIED | PENDING |
| Logs/secret/capability scan | pendiente | NOT_VERIFIED | PENDING |

El manifest se actualizará con identificadores públicos/sanitizados después de
cada boundary. Un mock o documento nunca sustituye una ejecución CI/cloud.
