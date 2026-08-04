# Auditoría de aceptación E0/E1

Fecha de corte: `2026-08-04` (`America/Santiago`).

## Identificación y alcance

| Elemento | Valor auditado |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` |
| Rama | `fix/stage1-external-readiness` |
| HEAD local/remoto | `2c018ef126622f7d0c6b84eeaf563a20bded593e` |
| Baseline | `origin/main` / `dadaaa736a1c9946971b9fe12cd33023d672c37e` |
| PR | `#1`, abierto, draft, no fusionado, mergeable |
| SHA funcional desplegado | `0167f14cbfe4a1192b26688a8443c5835da60bb4` |
| Imagen desplegada | `sha256:4dc9be449d1c7401dd70beaeeb38b6989b128a1892b59343b59717d2ca0a6f0b` |
| Proyecto / región | `cva-experimento-wiljms` / `us-east1` |
| Service / Job | `cva-web` / `cva-worker` |

El SHA desplegado es ancestro del HEAD. Entre `0167f14…` y `2c018ef…` solo se
añadieron cuatro informes bajo `docs/audits/`; `git diff --quiet` sobre todo lo
demás terminó `0`. Además, los 129 archivos del tar de fuente del build final
coincidieron byte a byte con `0167f14…`. Por ello la evidencia cloud es directa
para `0167f14…` e indirecta, pero materialmente aplicable, al código funcional
del HEAD. No se presenta el despliegue como evidencia directa del SHA documental
actual.

Se aplicó la jerarquía solicitada: modelos Pydantic, schema generado, ADR,
plan/MVP, arquitectura, Prompt Pack, matrices, implementación, documentación de
estado e informes anteriores. La contradicción del workbook que llama MVP a la
aprobación masiva se resolvió a favor del Plan y `AGENTS.md`: es Etapa 2 y quedó
fuera de esta auditoría.

## Resultado ejecutivo

| Estado | Historias |
|---|---:|
| `SATISFECHO` | 10 |
| `SATISFECHO_CON_LIMITACION` | 5 |
| `PARCIAL` | 4 |
| `NO_SATISFECHO` | 0 |
| `NO_VERIFICABLE` | 0 |
| `CONTRADICCION` | 0 |
| `FUERA_DE_ALCANCE` | 0 |

Los ocho criterios E0 están satisfechos. E1 tiene recorrido cloud real y datos
durables, pero cuatro historias son parciales: revisión de blueprint,
evidence-first, guía visible y despliegue cloud. El gate externo no cierra
mientras Terraform produzca exit `2`; tampoco existe el trigger GitHub–Cloud
Build requerido para automatizar la construcción desde una revisión verificable.

Hallazgos consolidados: **P0 0, P1 11, P2 17, P3 2**. El detalle y las pruebas
de cierre están en `STAGE1_REMEDIATION_BACKLOG.md`.

## Ejecuciones observadas

| Boundary | Comando/operación | Entorno | SHA | Resultado | Límite |
|---|---|---|---|---|---|
| Contratos | validación, regeneración a temporal, crawl de roots/refs y comparación byte a byte | `LOCAL_REAL`, Python 3.12.13 | `2c018ef…` | exit `0`; schema 1.1.0, 46 roots, 112 `$defs`, 231 refs, 8 fixtures | No alteró artefactos versionados. |
| Suite Python sin DB | `pytest --cov` | `LOCAL_REAL` | `2c018ef…` | 138 pass, 7 skips PostgreSQL, 82% | Separación declarada, no cuenta skips como pass. |
| Adaptadores aislados E1 | tests FastAPI/repository con `MemoryObjectStore`, dispatcher y proveedor deterministas | `FAKE` | `2c018ef…` | incluidos en los 138 pass; tamper, TTL, idempotencia y fallos cubiertos | No demuestra R2, Cloud Run ni proveedor externos. |
| PostgreSQL fresco | migración + suite completa `pytest --cov` | `POSTGRESQL_REAL`, PostgreSQL 16.14 | `2c018ef…` | 145 pass, 1 warning, 82% | Contenedor local efímero. |
| Repetición PostgreSQL | E2E + sensibles + suite sobre la misma DB | `POSTGRESQL_REAL` | `2c018ef…` | 143 pass, 2 fail por filas residuales | Hallazgo `AUD-P2-07`; en DB nueva pasan 145. |
| Stage 0 | `run-synthetic` sufficient/insufficient/injection | `MOCK` dentro de Docker | `2c018ef…` | `READY`; diagnóstico específico sin parcial; `READY` sin copiar injection | Gateway mock, sin red ni tools. |
| Reproducibilidad | dos procesos sufficient + `diff -rq` | `LOCAL_REAL` | `2c018ef…` | exit `0`, árboles idénticos | Misma plataforma/runtime. |
| Frontend | typecheck, 4 archivos/16 tests, build, `npm audit` | `LOCAL_REAL` | `2c018ef…` | todos exit `0`; 0 vulnerabilidades | Node local 26.5.1; CI usa 22.13.1. |
| Docker | build targets runtime/audit; runtime read-only/cap-drop; 3 casos | `LOCAL_REAL`, Docker 29.6.2 | `2c018ef…` | builds y smoke `200/200`; casos esperados | Arquitectura local arm64. |
| Terraform estático | fmt/init/validate + 8 tests deploy | `LOCAL_REAL`, Terraform 1.14.0, google 6.50.0 | `2c018ef…` | exit `0` | CI usa Terraform 1.14.3. |
| Terraform vivo | `plan -detailed-exitcode`, sin apply | `CLOUD_REAL` | state de `0167f14…` | exit `2`: Service `0 add/1 change/0 destroy` | Solo bloque superior `scaling`; Job sin drift. |
| Terraform diagnóstico | copia en `/tmp`, bloque superior con ambos ceros | `CLOUD_REAL` | misma state copiada | exit `0`, `No changes` | No se aplicó ni modificó el repo/state original. |
| GitHub Actions | run `30929318133`, cinco jobs | `CI_REAL` | PR head `2c018ef…`; checkout merge `3830089…` | todos `success` | Es evidencia del merge result del PR. |
| Cloud Build | build `85514589-a513-46af-ae74-1656a8433aa7` | `CLOUD_REAL` | label `0167f14…` | `SUCCESS`, digest final | Source GCS, no trigger; tar descargado y comparado. |
| Cloud Run | Service/Job describe, executions, IAM | `CLOUD_REAL` | imagen final | Service Ready; tres executions success y un fallo controlado; 1 task, 0 retries | Última ejecución es el fallo controlado. |
| HTTP cloud | health, readiness, sesión anónima | `CLOUD_REAL` | imagen final | `200`, `200`, `401` | No autentica al auditor como docente. |
| Supabase PostgreSQL | consultas agregadas con secreto solo en memoria y modo read-only | `CLOUD_REAL`, PostgreSQL 17.6 | imagen final/datos E2E | 24 tablas/RLS; 2 triggers; 0 grants anon/auth; estados durables | No se leyó contenido estudiantil. |
| R2 | evidencia primaria, prueba anónima y TTL del paquete | `CLOUD_REAL` | imagen final | privado; capacidad `200` inmediata y `403` tras 300 s | Sin sesión Wrangler independiente. |
| Logs | 1.712 entradas Cloud Run, escaneo redactado | `CLOUD_REAL` | despliegue final | 0 JWT, email, credential URL, signed URL o capability path | Patrón heurístico; no prueba ausencia de texto arbitrario. |
| Accesos no disponibles | Auth admin, control plane R2, browser docente y suite PG17 escribible | `NO_VERIFICADO` | N/A | no ejecutado | Registrado exclusivamente en `STAGE1_UNVERIFIED_AND_BLOCKED_ITEMS.md`. |

## Matriz Etapa 0

| ID | Criterio textual | Fuente | Implementación | Pruebas | Evidencia local | CI | Cloud | Estado | Hallazgos | Solución recomendada | Criterio de cierre |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E0-01 | `models_v1.1.py` compila; bundle regenerable; roots/prompts/fixtures validan. | Plan §E0; modelo/schema canónicos; ADR-028. | Carga el modelo en su ubicación canónica; generador y validador Draft 2020-12. | Compilación, regeneración temporal, drift, refs, positivos/negativos. | 46 roots, 112 defs, 231 refs, 8 fixtures; archivos regenerados idénticos. | Backend/Stage 0 verde. | N/A. | `SATISFECHO` | Ninguno de aceptación. | Mantener gate byte a byte. | Repetir desde entorno limpio sin diff. |
| E0-02 | ≥3 actividades con rúbrica ausente/presente, entrega suficiente/insuficiente e injection visible. | Plan E0-02; fixtures sintéticos. | Corpus versionado, sin datos reales. | CLI y target Docker audit. | Tres boundaries y outcomes esperados. | Docker y backend verdes. | N/A. | `SATISFECHO` | Riesgo de dependencias no fijadas: `AUD-P2-12`. | Fijar cadena de build sin alterar corpus. | Casos siguen pasando desde imagen reproducible. |
| E0-03 | TXT/MD/PDF digital producen `EvidenceUnit` con hash y localizador reproducible. | Plan E0-03; `EvidenceUnit`. | Parsers seguros, límites, hashes y locators. | 12 parser tests, PDF digital y MIME. | PASS; no ejecuta enlaces/macros/código. | PASS. | N/A. | `SATISFECHO` | Ninguno. | Conservar corpus hostil. | Hash/localizador estables en dos procesos. |
| E0-04 | Cada P01–P11 tiene roots, mock, timeout, ledger y abstención probada. | Plan E0-04; Prompt Pack; registry. | Registry P01–P11, resolver, validación por fases, P11 acotado; P10 deshabilitado. | 39 gateway tests y dinámicos. | PASS; timeout/budget/routing/repair/abstention. | PASS. | Ledger cloud muestra P01–P09, P10=0. | `SATISFECHO` | Ninguno; proveedor real no es gate E0/E1. | Mantener mock como modo de cierre. | Todos los prompts y fallos siguen cubiertos. |
| E0-05 | Pipeline manual explícito hasta guía y JSON, sin pasos implícitos. | Plan E0-05; ADR-030–034. | CLI secuencia P01–P09, planner antes de generación. | Casos CLI y comparación de artefactos. | PASS, 13 calls en casos suficientes. | PASS. | Mismo orden en worker real. | `SATISFECHO` | Ninguno. | Conservar stages y stage keys. | Manifest/ledger permiten reconstruir cada paso. |
| E0-06 | Rechaza IDs inventados, ancla no derivable, fuentes no autorizadas, extras y diagnóstico incompleto. | Plan E0-06; validación contractual/contextual. | Validadores separados; fail-closed. | Contract/gateway/validation/security tests. | PASS. | PASS. | No se observaron fallos parciales. | `SATISFECHO` | OpenAPI no publica esta fuerza contractual: `AUD-P1-10` (E1). | Tipar la frontera API sin duplicar modelos. | Consumer/provider tests reflejan los mismos roots. |
| E0-07 | Exactamente N primarias + reserva o uno de cuatro diagnósticos, sin conjunto parcial. | Plan E0-07; policy/planner. | Planner determinista antes de P07. | 5 planner tests y caso insuficiente. | N=3; insuficiente sin Assessment parcial. | PASS. | Happy path cloud produjo 3 preguntas. | `SATISFECHO` | Ninguno. | Mantener invariantes fail-closed. | Todo diagnóstico sigue sin emitir parcial. |
| E0-08 | Assessment y EvaluationGuide separados; export no filtra guía al estudiante. | Plan E0-08; ADR-003. | JSON separados, HTML/PDF derivados y manifiesto de export. | Export tests, CLI, Docker. | PASS; seis vistas, guía separada. | PASS. | Tres exports desde versiones aprobadas. | `SATISFECHO` | Cadena de build no totalmente reproducible: `AUD-P2-12`. | Fijar dependencias/base y conservar separación. | Rebuild verificado y sin guía en Assessment. |

## Matriz Etapa 1

| ID | Criterio textual | Fuente | Implementación | Pruebas | Evidencia local | CI | Cloud | Estado | Hallazgos | Solución recomendada | Criterio de cierre |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1-01 | Usuario autorizado entra a workspace experimental; rutas privadas no son públicas. | Plan E1-01; ADR-032; D-005. | Supabase JWT/JWKS → sesión propia, membresía DB, cookie HttpOnly/Secure y CSRF. | Auth, invitation, cross-workspace, cookie/CSRF. | PASS; Browser mostró login sin errores. | PASS. | JWKS `200`, private session `401`, paquete demuestra magic link/membresía. | `SATISFECHO_CON_LIMITACION` | Sin recuperación desde shell `AUD-P1-03`; Auth admin no revalidado independientemente. | Añadir recuperación y conservar membresía server-side. | Usuario invitado reingresa desde shell sin URL conocida; anónimo sigue `401`. |
| E1-02 | Captura título, idioma, modalidad, preguntas, tiempo, formatos y justificación; profundidad/operaciones derivan. | Plan E1-02; `ActivityConfig`. | UI/API persisten campos requeridos; P04 deriva dificultad/operaciones. | Backend/frontend y E2E. | PASS para campos literales. | PASS. | Dos actividades durables. | `SATISFECHO_CON_LIMITACION` | Edición UI, estimate y copy: `AUD-P2-01/02/04/05`. | Exponer edición/preflight sin convertir derivados en inputs. | Todos los campos editables hasta freeze; derivados solo lectura. |
| E1-03 | Carga manual a R2 privado con tamaño, MIME, hash y URL temporal. | Plan E1-03; ADR-005/008; D-007. | PUT temporal, HEAD/read acotado, MIME/hash y key sellada inmutable. | Adapter/backend/web y pruebas de tamper/TTL. | Memory fake y R2 adapter PASS. | PASS. | Paquete: CORS/lifecycle/privacidad/TTL; endpoint anónimo exige autorización. | `SATISFECHO_CON_LIMITACION` | Control plane R2 no independiente `AUD-P2-14`; token fake en logs `AUD-P1-04`. | Acceso auditor read-only y redacción de rutas fake. | Repetir PUT/GET/expiry/sellado y control plane con evidencia primaria. |
| E1-04 | P01–P05 producen specs, ambigüedades, review y versión aprobable. | Plan E1-04; Prompt Pack. | Pipeline de actividad explícito, decisiones persistidas y reanudación. | Unit/integration/E2E. | PASS. | PASS. | Ledger: dos calls de cada P01–P05; blueprints aprobados. | `SATISFECHO` | Principal parcial en eventos: `AUD-P1-11`. | Alinear todos los actores al tipo principal. | Eventos canónicos aceptan UUID y pipeline sigue estable. |
| E1-05 | Pantalla muestra dimensiones, variantes, operaciones y oportunidades; editar/aprobar crea versión y ETag. | Plan E1-05; `AssessmentBlueprint`/P05. | Función literal existe con CAS/versiones. | Frontend/backend/CAS. | Flujo funciona, pero proyección incompleta. | PASS técnico. | Blueprint v2 aprobado. | `PARCIAL` | `AUD-P1-05`; `AUD-P2-05`. | Mostrar constraints, factores, requisitos, checks y correcciones completas. | Auditor humano reconstruye todo lo que P06/P07 aplicará antes de aprobar. |
| E1-06 | Parser→mapa/oportunidades→plan N→preguntas/reviews→guía corre en Cloud Run Jobs. | Plan E1-06; D-006/D-021. | Job durable antes de dispatch, worker reclama uno, sin override sensible. | E2E, claims/locks, worker, failure. | PostgreSQL real PASS. | PASS. | 3 executions success; fallo controlado; task=1, parallelism=1, retries=0. | `SATISFECHO_CON_LIMITACION` | Harness DB no repetible `AUD-P2-07`; último execution esperado está failed. | Aislar pruebas y etiquetar operación controlada. | Suite repetible y una execution happy-path actual verificable. |
| E1-07 | UI diferencia estados técnicos y estado de dominio. | Plan E1-07. | `JobStatus` y submission state separados; polling/recovery por URL. | Backend/frontend/E2E. | PASS. | PASS. | DB: jobs 3 success/1 failed; submissions approved/uploaded. | `SATISFECHO` | Recuperación global ausente `AUD-P1-03`. | Añadir índice de actividades/jobs sin colapsar estados. | Reapertura desde shell muestra ambos estados. |
| E1-08 | Pregunta muestra ancla, localizador, dimensión, operación, scores y diagnostics. | Plan E1-08; evidence-first MVP. | Mínimo literal visible; aprobación humana completa. | Component/integration; inspección de código/UI. | Datos canónicos íntegros, vista estrecha. | PASS técnico. | Paquete afirma review; DB conserva aprobación. | `PARCIAL` | `AUD-P1-06/07/08`. | Proyectar pregunta completa y receipt por fragmento exitoso. | CHOICE y metadata visibles; servidor verifica cada apertura antes de aprobar. |
| E1-09 | Guía consultable; PDFs/JSON sin repetir llamadas a modelo. | Plan E1-09; ADR-003; D-011. | Guía/Assessment separados; exports desde snapshots aprobados. | Exports, E2E, model-call count. | Render y no-model-call PASS. | PASS. | Paquete: 8→8 calls durante export; tres artefactos; ledger vivo P10=0. | `PARCIAL` | Guía visible incompleta `AUD-P1-09`; export UI no recupera estado `AUD-P2-15`. | Proyectar trazas completas y listar/reemitir exports. | Guía UI refleja root íntegro y reload conserva acceso autorizado. |
| E1-10 | Ledger guarda provider, snapshot, modelo, effort, temperatura, reasons, tokens, latencia, costo, intentos y resultado. | Plan E1-10; `ModelCallLedgerEntry`. | Tabla append-only y snapshots tipados. | Gateway/repository/PostgreSQL. | PASS. | PASS. | 18 calls, todas `SCHEMA_VALID`, P01–P09, P10=0; trigger append-only activo. | `SATISFECHO_CON_LIMITACION` | Diferencia PostgreSQL prod/CI `AUD-P2-08`; count export depende de paquete. | Probar misma matriz en PG17 y conservar delta de export automatizado. | Ledger completo en DB administrada y export mantiene conteo. |
| E1-11 | React/FastAPI Service, Jobs, Supabase, R2; GitHub+Cloud Build/Actions; cerrar navegador no detiene job. | Plan E1-11; ADR-032; D-020–023; `EXTERNAL_SETUP`. | Recursos reales, misma imagen inmutable, IaC owner; browser recovery por deep link. | CI, build, Terraform, HTTP, DB, R2, logs. | IaC/Docker verdes. | Run actual verde. | Stack vivo y E2E primario; Terraform exit 2; sin trigger; recovery requiere URL conocida. | `PARCIAL` | `AUD-P1-01/02/03`; `AUD-P2-09/10/11/12/14/17`. | Declarar scaling superior, crear trigger/connection limitada, recuperación UI y evidencia final coherente. | Dos planes consecutivos exit 0; build conectado a SHA; E2E reabrible desde shell; paquete primario completo. |

## Decisiones y límites

- Decisiones de producto solicitadas: **0**. La jerarquía canónica resolvió todas
  las tensiones sin abrir Etapa 2.
- No se llamó a proveedor IA real: `CVA_MODEL_MODE=mock` es el modo obligatorio
  de cierre y P10 continúa deshabilitado.
- No se aplicó Terraform, no se ejecutaron migraciones productivas, no se
  alteraron datos/recursos y no se modificó código o documentación previa.
- La recomendación autoriza remediación de Etapa 1, no Etapa 2.

`READY_FOR_STAGE1_REMEDIATION`
