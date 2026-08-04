# Auditoría de implementación de Etapa 1

Fecha: `2026-08-04`. HEAD auditado:
`2c018ef126622f7d0c6b84eeaf563a20bded593e` sobre
`fix/stage1-external-readiness`.

## Dictamen

El núcleo persiste y valida correctamente los objetos canónicos, separa los
pipelines de actividad y submission, planifica antes de generar, falla cerrado,
mantiene una única submission por actividad, registra llamadas al modelo y
deriva exports desde snapshots aprobados. No se detectó copia de modelos
Pydantic, edición manual del schema, P10 activo, proveedor con tools/red,
SQLite cloud, retry funcional general ni mezcla de Assessment y Guide.

La implementación no está lista para cerrar Etapa 1. La revisión humana se
realiza sobre proyecciones incompletas; el gate evidence-first es solo estado
React; casi toda la API JSON se publica como objetos libres; actores UUID no
validan en todos los roots canónicos; y el adaptador local deja capacidades en
el access log. Estos defectos no corrompieron los snapshots/exports observados,
pero impiden atribuir al flujo humano y a la frontera API las garantías de los
contratos persistidos.

## Contratos y arquitectura

| Superficie | Observado | Evaluación |
|---|---|---|
| Autoridad canónica | `src/comprehension_verification/contracts.py` carga `specification/models_v1.1(1).py`; no redefine clases. | Conforme. |
| Schema | Draft 2020-12 regenerable; modelo y schema temporales coincidieron byte a byte con lo versionado. | Conforme. |
| Fixtures | Ocho fixtures documentales/JSON, incluidos negativos; PDF contractual determinista en el mismo runtime. | Conforme. |
| Pipelines | Actividad P01–P05 y submission P06–P09 son funciones/stages distintos; P10 solo está registrado y falla cerrado por settings. | Conforme. |
| Gateway | Request, envelope, output y contexto se validan en fases; P11 no repara fallos críticos; mock no usa red/tools. | Conforme. |
| Planner | Produce N exacto antes de P07, reserva disjunta o diagnóstico específico; no ensambla Assessment parcial. | Conforme. |
| Persistencia | Assessment y EvaluationGuide se almacenan separados; versions/ETag y stage keys son durables. | Conforme con las limitaciones API/UI descritas abajo. |
| Exports | Solo desde versiones aprobadas y evento de aprobación; no encola P01–P09 ni llama al gateway. | Conforme. |

La suite fresca con PostgreSQL real terminó con 145 pruebas aprobadas y 82% de
cobertura. El valor no se usa como porcentaje de aceptación; solo registra la
medición ejecutada.

## Investigación obligatoria de Principal ID

El contrato define `Id` como slug minúsculo y `PrincipalId` como slug o UUID
minúsculo. Solo tres campos externos migraron a `PrincipalId`.

| Campo | Pydantic | JSON Schema | OpenAPI | API/servicio | ORM/PostgreSQL | Test | Resultado |
|---|---|---|---|---|---|---|---|
| `PolicyDecision.decided_by` | UUID acepta | UUID acepta | Root no expuesto por request tipado | Actor se deriva de sesión | `varchar(128)` acepta | Sí | Conforme. |
| `AssessmentBlueprint.approved_by` | UUID acepta | UUID acepta | PATCH contiene el root; aprobación body vacío | Actor server-side | JSON/varchar acepta | Sí | Conforme. |
| `Assessment.approved_by` | UUID acepta | UUID acepta | Response no tipada | Actor server-side | JSON/varchar acepta | Sí | Conforme. |
| `QuestionReviewAction.actor_id` | UUID rechaza (`Id`) | UUID rechaza | No expuesto | Capacidad E2 no activa | Sin flujo E1 | No | Inconsistencia contractual futura; fuera del flujo activo. |
| `BulkApprovalRequest.actor_id` | UUID rechaza (`Id`) | UUID rechaza | No expuesto | E2 | Sin tabla E1 | No | Fuera de alcance E1, pero inconsistente. |
| `BulkApprovalRecord.actor_id` | UUID rechaza (`Id`) | UUID rechaza | No expuesto | E2 | Sin tabla E1 | No | Fuera de alcance E1, pero inconsistente. |
| `EventActor.id` | UUID rechaza (`Id`) | UUID rechaza | No expuesto | `AuditEventRow`, no `DomainEvent` | `actor_id varchar(128)` acepta | No | Defecto E1: los eventos reales no pueden proyectarse al envelope canónico. |
| Feedback | No existe root E1 | N/A | N/A | No existe | No existe | N/A | `FUERA_DE_ALCANCE`: Plan E2-09. |
| Membership/user | No usa root de dominio | N/A | No expuesto | `sub` Supabase es identidad | `users.id` y `workspace_roles.user_id` aceptan UUID; RLS compara `auth.uid()::text` | Auth/E2E | Conforme operativo. |

Una prueba adversarial independiente validó el mismo UUID contra los siete
roots: 3 aceptaron y 4 rechazaron tanto en Pydantic como en JSON Schema. La base
cloud contiene 5 audit events; los 5 `actor_id` tienen forma UUID y pertenecen a
un único principal. Por tanto, el problema no es hipotético: persistencia y
runtime aceptan actores que `EventActor(USER)` rechaza. No hay export canónico
de audit events que pueda ocultar el fallo; simplemente falta esa frontera.

Solución recomendada: clasificar explícitamente cada actor como principal
externo, servicio o sistema; usar `PrincipalId` para identidades externas en
todos los roots afectados; mantener IDs de servicio/sistema bajo tipos
separados si su gramática difiere; añadir tests Pydantic/schema/OpenAPI/eventos
y migración de compatibilidad solo si existieran datos que no validen. No se
debe activar QuestionReview/Bulk/Feedback al cerrar este defecto.

## Frontera HTTP y OpenAPI

La aplicación genera OpenAPI 3.1.0 con 28 paths y solo 21 component schemas.
La inspección ejecutada encontró 14 operaciones JSON con request schema libre y
30 responses JSON libres o vacías. Salvo el PATCH del blueprint, los endpoints
mutables usan `dict[str, Any]`; no hay response models ni snapshot OpenAPI.

Consecuencias observables:

- el frontend mantiene tipos manuales más estrechos que los objetos canónicos;
- la pérdida de `choices`, `misconceptions` o referencias no rompe CI;
- consumidores no pueden saber qué campos son actor server-owned;
- algunos handlers ignoran extras y otros los rechazan solo después, por una
  semántica que OpenAPI no comunica;
- los tres campos `PrincipalId` corregidos no quedan demostrados de extremo a
  extremo por el contrato publicado.

El runtime valida muchos roots después del parseo y por ello las pruebas de
seguridad pasan; esto mitiga inputs mal formados, pero no sustituye un contrato
provider/consumer. `AUD-P1-10` agrupa requests, responses y snapshot porque el
cierre requiere tratarlos como una sola frontera.

## Frontend y revisión humana

### Shell y actividad

- Las rutas privadas existen y el login vivo se renderizó sin errores de
  consola.
- `App.tsx` redirige toda ruta desconocida a `/activities/new`; el sidebar solo
  enlaza “Nueva actividad”. Aunque el backend tiene `GET /activities`, el
  frontend no puede reencontrar una actividad, submission o job sin conocer la
  URL. La evidencia de “cerrar/reabrir” abrió un deep link conocido; no prueba
  descubrimiento desde el shell (`AUD-P1-03`).
- La creación captura todos los campos literales de E1-02 y no pregunta por
  dificultad/operación. La edición backend con ETag no tiene pantalla
  (`AUD-P2-01`), y no existe estimate previo (`AUD-P2-02`).

### Blueprint

La pantalla muestra dimensiones, variantes, operaciones, foco, observable,
tiempo, versión, ETag y checks P05. Sin embargo, antes de aprobar no muestra de
forma reconstruible:

- constraints completas (min quality/verification, formatos, reserva, target
  total y política de justificación);
- learning outcomes/factores de cada dimensión;
- evidence requirements y verification potential de variantes;
- difficulty, anchor structure, allowed formats, quality y justification de
  cada opportunity;
- IDs/referencias, corrección recomendada y mensaje completo de cada check P05.

El mensaje de un check queda en `title`, no como contenido visible. La edición
solo permite nombre/justificación, nombre/descripción y foco/observable. La
aprobación funciona técnicamente, pero el docente puede congelar un catálogo
sin ver restricciones que P06/P07 aplicarán (`AUD-P1-05`).

### Assessment evidence-first

El objeto frontend `SelectedQuestion` omite `source_candidate_id`,
`opportunity_template_id`, `choices`, `student_justification_required`,
course-source/citations y preliminary guide. La tarjeta tampoco presenta todos
los campos que sí declara (format, difficulty, minutes, planning score). En
particular, una pregunta `CHOICE` no muestra ninguna alternativa y puede
aprobarse (`AUD-P1-06/07`).

El gate de apertura es un `Set<question_id>` en memoria. El `onClick` del link
marca la pregunta antes de confirmar que la ventana cargó; un click cubre la
pregunta aunque tenga varios fragments; el estado se pierde al recargar; y el
POST de aprobación lleva body vacío. El backend revalida bytes/hash, pero no
existe receipt de que el docente abrió cada fuente. Integridad de objeto y
revisión humana son garantías diferentes (`AUD-P1-08`).

### Guía y exports

La guía muestra propósito, descriptions, required flag, alternativas,
`cannot_infer` y niveles. Omite `misconceptions`, evidence/source IDs y la
relación nivel→observable. Así, el root persistido es más fuerte que la vista
usada para aprobar/consultar (`AUD-P1-09`). Los exports son correctos y no
repiten llamadas; sus botones/download URLs solo viven en estado React y no se
recuperan después de reload (`AUD-P2-15`).

### Accesibilidad y copy

Los tabs tienen `tablist/tab` pero carecen de `id`, `aria-controls`,
`tabpanel`, roving tabindex y teclado Home/End/flechas. Inputs custom ocultos no
trasladan foco visible a su tarjeta. El login no incluye el aviso de privacidad
completo del MVP; `CHOICE`, `SELECTED`, `OPEN_SHORT` y varios enums se explican
de forma ambigua o técnica (`AUD-P2-04/05/06`, `AUD-P3-02`).

## Backend, persistencia y jobs

| Tema | Evidencia | Evaluación |
|---|---|---|
| Tenant/workspace | Cada endpoint obtiene Actor server-side y usa `scoped`; tests rechazan cross-tenant/cross-submission. | Conforme. La conexión de servicio hace crítica esta disciplina porque no depende de RLS por usuario. |
| Auth | JWT Supabase RS/ES, issuer/audience/JWKS, membership, sesión propia, CSRF doble envío. | Conforme; admin Auth no fue inspeccionado directamente. |
| Upload | Tamaño declarado y real, MIME, hash, lectura acotada, key `/upload` y sellado condicional content-addressed. | Conforme. |
| Idempotencia | Reserva atómica `(tenant,key,fingerprint)`; replay vuelve a autorizar y reemite capability, no la persiste. | Conforme. |
| Versiones/CAS | Activity y blueprint usan ETag; aprobación congela versión y actor/fecha. | Conforme. |
| Submission única | Unique por activity y estado frozen al encolar. | Conforme para E1. |
| Job durable | Fila antes de dispatch; Cloud Run no recibe student/job IDs; worker reclama como máximo uno. | Conforme. |
| Fallos | Dominio y técnica separados; failure durable; Cloud Run `maxRetries=0`. | Conforme. |
| Ledger/auditoría | Model calls y audit events tienen triggers append-only. | Conforme con mismatch `EventActor`. |
| Exports | Exigen Assessment aprobado, Guide ready y audit event; artefactos inmutables. | Conforme. |

El harness PostgreSQL no limpia/namespacea sus datos. E2E y tests sensibles
pasaron sobre una DB fresca; ejecutar luego la suite completa sobre la misma DB
produjo dos fallos por actividades/jobs residuales. Una segunda DB vacía dio
145 pass. Es un defecto de aislamiento/repetibilidad de pruebas, no evidencia de
un fallo del algoritmo `SKIP LOCKED` (`AUD-P2-07`).

La base administrada es PostgreSQL 17.6, mientras CI/local cubren 16.14. Las
consultas directas read-only confirmaron 24 tablas, RLS en 24, los dos triggers,
cero grants a `anon/authenticated`, grants de `service_role` sobre 24 tablas y
estados terminales esperados. El skew de major queda sin regresión dedicada
(`AUD-P2-08`).

## Seguridad adversarial

| Control | Resultado | Límite/hallazgo |
|---|---|---|
| Prompt injection | Fuente hostil visible; texto generado no la copia; 0 red/tools. | `MOCK`, no proveedor real por diseño. |
| IDs/anchors/sources | Validadores rechazan referencias inventadas/no autorizadas y extras. | PASS. |
| Fail-closed | Diagnóstico insuficiente no produce Assessment parcial. | PASS. |
| CSRF/cookies | CSRF header+cookie+claim; HttpOnly/Secure/SameSite session en cloud. | PASS. |
| JWT/JWKS | JWKS público ES256 vivo; issuer/audience obligatorios; membership posterior. | PASS operativo. |
| MIME/tamaño/hash | HEAD + read acotado + libmagic + hash y objeto sellado. | PASS. |
| URL firmada | R2 no se persiste; TTL separado; referrer `no-referrer`. | Control plane independiente limitado. |
| Logs cloud | 1.712 entradas: 0 patrones JWT, email, credential URL, signed URL o fake capability path. | Heurístico, no demuestra ausencia de texto arbitrario. |
| Logs locales | Uvicorn imprime request target completo. Probe ficticio apareció como `/api/v1/objects/audit-capability-probe`. | Un JWT real de MemoryObjectStore quedaría en log: `AUD-P1-04`. |
| Secretos | Scan repo/package sin secretos de alta confianza; settings oculta inputs en errors; secretos por version. | Worker recibe session secret sin necesitar sesión HTTP: `AUD-P2-13`. |
| Build/runtime | Usuario 65532, read-only/tmpfs/cap-drop en smoke; fixtures fuera de runtime. | Bases/deps no totalmente fijadas: `AUD-P2-12`. |

## Pruebas y límites

- Suite fresca: 145 pass, 1 `StarletteDeprecationWarning`, 82%.
- CI actual: cinco jobs success; backend 138 pass/7 skips y PostgreSQL separado
  1+7 pass; frontend 16 pass; deploy 8 pass; Docker pass.
- No existe browser E2E automatizado. Se inspeccionó login vivo y existe
  evidencia externa primaria del happy path, pero no una grabación verificable
  de cada interacción (`AUD-P2-17`).
- No se ejecutó código estudiantil, no se usaron datos reales y no se abrió
  ninguna historia E2.

## Severidades

| Severidad | Cantidad | Bloque de mayor riesgo |
|---|---:|---|
| P0 | 0 | — |
| P1 | 11 | revisión humana, contrato API, Principal ID, logs de capability y cierre externo |
| P2 | 17 | UX, accesibilidad, pruebas, documentación, evidencia y supply chain |
| P3 | 2 | warning y copy menor |

Las soluciones exactas, dependencias y pruebas de cierre están en
`STAGE1_REMEDIATION_BACKLOG.md`.

`READY_FOR_STAGE1_REMEDIATION`
