# Estado de implementación y matriz de cierre

## Veredicto de esta fase

`READY_FOR_EXTERNAL_STAGE1_VERIFICATION`

Fecha de corte: 2026-08-01, America/Santiago.

Todo el boundary reproducible sin cuentas ni secretos externos quedó verde. La
Etapa 1 **no** está cerrada en cloud: E1-11 y las partes de historias que exigen
Supabase/R2/Cloud Run reales permanecen parciales hasta ejecutar la checklist de
`docs/EXTERNAL_SETUP.md`. Este estado no autoriza Etapa 2 y no equivale a
`READY_FOR_STAGE_2`.

## Proveniencia del repositorio

- `git rev-parse --verify HEAD` terminó 128: el repositorio no tiene commit
  inicial (`HEAD` no existe).
- `git log --all --oneline --decorate -n 20` terminó 0 sin entradas.
- `git status --short --untracked-files=all` mostró el árbol completo como
  `??`; por eso `git diff --stat` terminó 0 sin contenido.
- En consecuencia, no hay historial ni baseline Git contra los que atribuir
  cambios. La evidencia de cierre se basa en lectura íntegra, inspección del
  árbol actual y ejecuciones registradas, no en supuestos sobre commits.

## Claves de evidencia realmente ejecutada

| Clave | Evidencia del 2026-08-01 |
|---|---|
| V-CONTRACTS | Gate contractual exit 0: 46 roots, 112 `$defs`, 231 referencias y 8 fixtures; hashes de modelo/schema registrados en `TEST_RESULTS.md`. |
| V-PY | Suite Python final exit 0: 117/117 pruebas. |
| V-COV | Suite con coverage exit 0: 117/117 y 82% total. |
| V-S0 | Recorridos `sufficient`, `insufficient` e `injection`, cada uno exit 0 y outcome esperado. |
| V-REPRO | Dos procesos independientes de `sufficient`; `diff -rq` exit 0 y hashes de los seis exports idénticos. |
| V-FE | Instalación limpia con `npm ci`, typecheck exit 0, 16/16 tests y build Vite exit 0. |
| V-PG | PostgreSQL 16.14 temporal real; migración aplicada a base vacía, 24 tablas/24 RLS/2 triggers validados y E2E mock exit 0. |
| V-BROWSER | Recorrido UI real: login, actividad, uploads, blueprint, aprobación, submission, job, evidence-first, aprobación, tres exports y reapertura; consola sin errores/warnings. |
| V-DOCKER | Runtime construido/ejecutado con health exit 0; target `audit` ejecutó `run-synthetic` dentro del contenedor y produjo 32 archivos. |
| V-IAC | 6/6 tests de deploy, YAML/shell válidos, Terraform fmt/init/validate exit 0 con Google provider 6.50.0; source staging de Cloud Build quedó cubierto por IAM explícito. |

## Matriz completa E0/E1

“Prueba escrita” indica solo que el caso existe. “Ejecutada” cita exclusivamente
las claves anteriores; no se infiere un PASS por la mera presencia de un test.

| Historia y criterio canónico | Implementación inspeccionada | Prueba escrita localizada | Prueba realmente ejecutada | Verificación externa pendiente | Estado formal |
|---|---|---|---|---|---|
| **E0-01** — modelos compilan; bundle regenerable; roots/prompts/fixtures validan | Modelo único en `specification/models_v1.1(1).py`, loader, schema generado y validador de drift | `tests/test_contract_validation.py` y fixtures válidos/negativos | V-CONTRACTS, V-PY, V-COV | Ninguna | **COMPLETA** |
| **E0-02** — ≥3 actividades; rúbrica presente/ausente; suficiente/insuficiente/injection | Tres actividades bajo `fixtures/stage0`; CLI explícita por caso | `tests/test_cli.py`, `tests/test_parsers.py` | V-S0, V-PY | Ninguna | **COMPLETA** |
| **E0-03** — TXT/MD/PDF digital producen `EvidenceUnit` con hash/localizador reproducible | `parsers/service.py` limita MIME/tamaño, rechaza PDF activo/cifrado y conserva procedencia | `tests/test_parsers.py` | V-PY, V-REPRO | Ninguna | **COMPLETA** |
| **E0-04** — P01–P11 con roots, mock, timeout, ledger y abstención | Registry explícito, `ModelGateway`, mock determinista, adapter real bloqueado por gate | `tests/test_model_gateway.py`, `tests/test_dynamic_model_gateway.py` | V-PY; V-S0 confirmó mock sin red | Proveedor real excluido por requisito; no bloquea E1 | **COMPLETA** |
| **E0-05** — pipeline sin pasos implícitos hasta guía/JSON | Pipelines actividad/submission, P01–P09 y planificador antes de generar | CLI, `tests/test_planning.py`, `tests/test_stage1_web.py` | V-PY, V-S0, V-PG, V-BROWSER | Ninguna | **COMPLETA** |
| **E0-06** — rechazar IDs/anclas/fuentes/schema/diagnóstico inválidos | Validación estructural y contextual separada; se corrigió precedencia para `INVENTED_EVIDENCE_ID` | `tests/test_validation.py`, negativos contractuales | V-CONTRACTS, V-PY | Ninguna | **COMPLETA** |
| **E0-07** — exactamente N + reserva o uno de cuatro diagnósticos, nunca parcial | Planner determinista y cierre fail-closed | `tests/test_planning.py`, `tests/test_cli.py` | V-PY, V-S0, V-REPRO | Ninguna | **COMPLETA** |
| **E0-08** — Assessment/Guide separados; export no filtra guía | JSON separados y HTML/PDF derivados | `tests/test_exports.py`, E2E web | V-PY, V-S0, V-REPRO, V-DOCKER | Ninguna | **COMPLETA** |
| **E1-01** — usuario autorizado entra; rutas privadas no son públicas | Cookie HttpOnly + CSRF, membresía por workspace, Supabase/JWKS y shell privado; se alineó el correo local precargado con la invitación real | web/backend/adapters, `frontend/src/App.test.tsx`, tests Supabase | V-PY, V-FE, V-BROWSER | Auth, membresía y RLS en Supabase real | **PARCIAL SOLO POR CLOUD** |
| **E1-02** — captura campos permitidos; profundidad/operaciones derivadas | Formulario/API acotados; config congelada; sin controles de profundidad/operación | backend/web y `Stage1Views.test.tsx` | V-PY, V-FE, V-BROWSER | Ninguna | **COMPLETA** |
| **E1-03** — prompt, rúbrica opcional y una entrega en R2 privado con tamaño/MIME/hash/URL temporal | Upload desechable, HEAD/lectura acotada, sellado content-addressed y adapter R2 | `test_stage1_adapters.py`, backend/web | V-PY, V-PG, V-BROWSER | Bucket/token/CORS/lifecycle y URLs firmadas R2 reales | **PARCIAL SOLO POR CLOUD** |
| **E1-04** — P01–P05 producen specs, ambigüedades, review y versión aprobable | Workflow durable P01–P05, decisiones P03 y aprobación | backend/web/frontend | V-PY, V-PG, V-BROWSER | Recorrido desplegado forma parte de E1-11 | **COMPLETA LOCAL** |
| **E1-05** — pantalla muestra catálogo; editar/aprobar crea versión + ETag | Vista completa, PATCH con `If-Match`, CAS y versiones inmutables | backend/web/`Stage1Views.test.tsx` | V-PY, V-FE, V-BROWSER | Ninguna fuera del smoke cloud | **COMPLETA** |
| **E1-06** — parser→mapa→plan N→P07/P08→P09 corre en Cloud Run Jobs | Fila durable antes del dispatch, inputs congelados, worker separado y adapter Cloud Run | backend/web/jobs y E2E mock | V-PY, V-PG, V-BROWSER, V-DOCKER | Ejecución real de Cloud Run Job e IAM | **PARCIAL SOLO POR CLOUD** |
| **E1-07** — UI separa estados técnicos y estado de dominio | DTO/polling y paneles distintos; job persiste fuera del navegador | web/frontend | V-PY, V-FE, V-PG, V-BROWSER (reapertura en otra pestaña) | Prueba de cerrar navegador durante Job real pertenece a E1-11 | **COMPLETA LOCAL** |
| **E1-08** — pregunta muestra ancla, localizador, dimensión, operación, scores y diagnósticos | Endpoints evidence-first, fuente firmada y aprobación bloqueada hasta abrir anclas | web/frontend | V-PY, V-FE, V-BROWSER (3/3 fuentes) | Fuente exacta mediante R2 real | **PARCIAL SOLO POR CLOUD** |
| **E1-09** — guía en plataforma; PDF/JSON derivados sin otra llamada | Assessment/Guide separados; tres tipos de export desde objetos aprobados | `tests/test_exports.py`, E2E web/frontend | V-PY, V-REPRO, V-BROWSER, V-DOCKER | Descarga desde runtime cloud, dentro de E1-11 | **COMPLETA LOCAL** |
| **E1-10** — ledger con provider/snapshot/model/effort/temperatura/reasons/tokens/latencia/costo/intentos/resultado | Ledger append-only y redacción de contenido sensible | gateway, backend y E2E web | V-PY, V-PG | Observación operacional cloud, dentro de E1-11 | **COMPLETA LOCAL** |
| **E1-11** — Service + Job en GCP, Supabase y R2 reales; CI/CD; cerrar navegador no detiene job | Docker runtime/audit, migración, adapters, Terraform, Cloud Build y Actions | `deploy/tests/test_deploy_artifacts.py`, E2E análogo local | V-PG, V-BROWSER, V-DOCKER, V-IAC | **Obligatoria:** desplegar y ejecutar checklist GCP + Supabase + R2 | **PARCIAL; NO CERRADA** |

## Correcciones realizadas durante la auditoría

- dos manifests sintéticos usaban IDs de criterio inexistentes;
- la validación de oportunidades ocultaba un ID de evidencia inventado detrás
  de otro diagnóstico;
- tipos/fixtures frontend no reflejaban `opportunity_id` ni formatos exactos;
- el flujo OTP trataba como sesión confiable una respuesta inmediata no
  canónica, en vez de esperar el callback de Auth;
- el correo precargado de login local no era uno de los invitados;
- la cadena Vite/Vitest antigua se bloqueaba con el runtime disponible; se
  actualizó y se generó `package-lock.json`; React Router se sustituyó por
  Wouter tras comprobar que no existía una versión sin advisories para los
  rangos necesarios; el audit final quedó en cero;
- faltaban CI integral, verificador PostgreSQL y target Docker de auditoría;
- dos manifests de Docker excluían los fixtures necesarios para el target de
  auditoría; el runtime productivo sigue sin copiarlos.
- la cuenta dedicada de Cloud Build no declaraba acceso al source staging; se
  habilitó Cloud Storage y se añadieron los roles `storage.bucketViewer` y
  `storage.objectUser`, con regresión estática y Terraform final verde.

## Frontera de Etapa 2

No se añadió batch, retry/cancel general, acciones por pregunta,
aprobación masiva, DOCX completo, OCR, LMS, feedback, calificación ni detección
de IA. `CVA_MODEL_MODE=mock` y `CVA_P10_ENABLED=false` permanecen fijados para
este cierre.
