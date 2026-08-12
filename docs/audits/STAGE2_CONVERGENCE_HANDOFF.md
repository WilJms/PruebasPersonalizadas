# Handoff consolidado — Fase 2

Fecha de corte: 2026-08-12 (America/Santiago).

Estado recomendado: **`CONVERGENCE_INCOMPLETE`**.

Este documento es el cierre operacional de la Fase 2 solicitada sobre el PR #3.
No es una certificación independiente ni autoriza build, deploy, migración o E2E
cloud. La documentación se consolida pese a no haberse alcanzado convergencia
para preservar los resultados y permitir una continuación informada.

## 1. Frontera entregada

| Elemento | Valor |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` |
| Branch | `codex/openai-real-provider-gate` |
| PR | `#3`, draft |
| Baseline auditado por Fase 1 | `a2be3c6e777c9832fe4e25bc3276c72eda1b46cb` |
| Baseline de código de la última observación | `10d7622a9d278ed9a6d41d1317dd98b7a49c7721` |
| Commit que preserva la última observación | `03dc0c121b18fae4fbc41aad34672d05ead643f6` |
| Versión del rehearsal/reporte | `stage2-product-rehearsal/1.3.0` / `stage2-convergence-report/1.3.0` |
| Frontera ejecutable | `sha256:be462b18e06f61d86d99831400ca3dc55072ddcf8df2e0150a146243f4996117` |
| Harness | `sha256:f586ff9291c6ed3778537bf8094525a663a40c98f005dc5a09c716ff206b8980` |
| Módulo rehearsal | `sha256:219bb030503ba1721fd271e3bd5ffdb504b7c9cd8881b49698a0f8feb0a2af76` |
| Fixture product-shaped | `sha256:77ba47d46449e0fa8a109304f87b1f18ba9c4cb9b8020866cfe5b3eb99d81ff4` |
| Modelo canónico | `sha256:d9869d721afd83f2ab5a8bd4d14d527b47586e3e33b05e9564abbf68672f933e` |
| Schema generado | `sha256:a6f0657064aa1bd9673079db9c7ce043db43e4038a094482052df895807a93af` |

El HEAD final publicado debe tomarse del PR: un documento versionado no puede
incluir el hash de su propio commit. Los hashes anteriores fijan exactamente el
código y los artefactos que consumió la última observación real.

## 2. Veredicto ejecutivo

La remediación determinista fue amplia y verificable: autoridad, aislamiento
sintético, ownership de IDs, contratos, validadores, seguridad de texto,
planner, cache/reuse, StageRuns, state machines, dispatch, idempotencia,
autenticación y harness quedaron cubiertos por regresiones. Las suites locales,
PostgreSQL, frontend, contratos, deploy estático, secretos y Terraform quedaron
verdes. El rehearsal offline completó sweep y tres cadenas con 24 transportes
fake.

La frontera real Luna llegó por primera vez a completar una cadena integrada
P04→P09. Sin embargo, bajo la misma frontera congelada:

- el sweep independiente rechazó en P05 su blueprint fijo por `CONSTRUCT`;
- la segunda cadena base falló en P06 con `P06_REFERENCE_MISMATCH`;
- la variante distinta llegó a P08, pero no fue aceptada.

Por ello no existen dos cadenas completas consecutivas ni una variante completa,
y tampoco hay evidencia suficiente de confiabilidad residual. No se ejecutó una
repetición automática, no se relajó ningún validator y no se cambió Luna.

## 3. Findings de Fase 1

Todos los gaps deterministas principales fueron confirmados. Ningún finding se
refutó en bloque; en `PLAN-001`, `PLAN-002`, `INF-001` y `REL-001` se confirmó
el gap y se acotó su impacto o fase de resolución.

### P0/P1

| Finding | Estado | Resolución/evidencia |
|---|---|---|
| GOV-001 | CERRADO | `AGENTS.md` y ADR-035/036 separan producto cloud mock del gate real sintético, hash-bound y con caps. |
| DATA-001 | CERRADO | Attestation/hash server-controlled para artefactos sintéticos; rechazo antes de resolver transporte real. |
| EVAL-001 | CERRADO | Ledger SQLite durable, claim transaccional previo a red, consumo irreversible y pruebas de concurrencia/crash/replay. |
| EVAL-002 | ABIERTO | P05 pasó dentro de cadenas, pero el sweep final devolvió `READY/REJECT` con un critical `CONSTRUCT`; no está cualificado de forma estable. |
| OBS-001 | PARCIAL | Reporte versionado, timestamps, SHA, boundary, execution/authorization y controles content-free cerrados; P06/P08 aún no explican el predicado semántico exacto del último fallo. |
| REL-001 | DIFERIDO | HEAD/artefactos locales están ligados; build/digest/plan/runtime del nuevo HEAD quedan para la fase cloud expresamente prohibida aquí. |
| CACHE-001 | CERRADO | Fingerprint ejecutable incluye prompt, schemas, validators, route/model/reasoning/adapter y revalida hits con la frontera vigente. |
| CACHE-002 | CERRADO | Identidad por etapa y dependency-aware; cambios locales invalidan consumidores afectados sin barrer etapas independientes. |
| STAGE-001 | CERRADO | Parse, prompts, planner y assembly se materializan; `EXECUTED/REUSED`, fuente y fingerprint quedan append-only. |
| JOB-001 | CERRADO | Retry/resume actualizan atómicamente la proyección y UI continúa observando el job nuevo. |
| JOB-002 | CERRADO | Edición P05 usa la misma matriz terminal que generación inicial; no publica resultados no aprobables como éxito. |
| JOB-003 | CERRADO | Dispatch transporta y reclama el `job_id` exacto; worker cloud falla cerrado sin claim explícito. |
| CTX-001 | CERRADO | TrustedContext productivo se construye desde facts persistidos/tenant-scoped, no desde el request ni el helper sintético. |
| ID-001 | CERRADO | `candidate_id` es preasignado por servidor y se comprueba; no hay `merge` model-controlled entre owners. |
| ID-002 | CERRADO | Unicidad/ref cerradas en P01/P02/P03 y negativos canónicos. |
| P03-001 | CERRADO | `blocked` equivale a la existencia de issues bloqueantes y cada issue requiere decisión coherente. |
| P04-001 | CERRADO | Copia exacta de constraints, mínimos, reservas y política de justificación hasta planner/assembly. |
| P04-002 | CERRADO | ID/version objetivo son server-owned, están acotados y deben coincidir. |
| P05-001 | CERRADO DETERMINISTA | Matriz completa de checks/recommendation, referencias allowlisted y preflight determinista en el gateway productivo. EVAL-002 sigue abierto por confiabilidad. |
| P06-001 | CERRADO | Calidad mínima efectiva es `max(global, template)`; herencia y elegibilidad del planner se comprueban. |
| P07-001 | CERRADO | Visitor transversal distingue texto generado de anclas hostiles y cubre P07/P08/P09, choices, rationales, guides y diagnostics. |
| P09-001 | CERRADO | Cardinalidad 2–5, unicidad y cobertura no vacua para observables. |
| P11-001 | CERRADO | Reparación sólo estructural con diff allowlisted; cambios semánticos, de IDs, números o estados son rechazados. |

### P2 y deuda

| Finding | Estado | Resolución/aceptación |
|---|---|---|
| P06-002 | CERRADO | Fingerprints evitan oportunidades/reservas duplicadas y `avoid` se aplica a preguntas rechazadas. |
| PLAN-001 | CERRADO | `required_criterion_ids` llega al planner y participa en factibilidad/cobertura. |
| PLAN-002 | CERRADO | Selección exacta completa reemplaza la poda heurística que podía producir falsos `INFEASIBLE`. |
| P08-001 | CERRADO | Igualdad estricta sólo para `ACCEPT`; `REJECT/ESCALATE` puede reportar estimación independiente coherente. |
| API-001 | CERRADO | GET observa; reconciliación de stale jobs se mueve a una acción interna explícita. |
| PRIV-001 | CERRADO PARA E2 | Descriptores de idempotencia minimizados y expiración durable añadida; datos reales siguen prohibidos. |
| INF-001 | ACEPTADO/DEFERIDO | No bloquea rehearsal sintético local; TLS/red/backups/audit externo deben cerrarse antes de certificación fuerte o datos reales. |
| AUTH-001 | CERRADO | Sesión Supabase temporal para exchange y limpieza posterior; regresiones de logout/persistencia. |
| DEBT-001 | CERRADO | La ruta dejó de anunciar IMAGE mientras el adapter sólo transporte texto extraído. |

## 4. Cambios arquitectónicos durables

1. **Autoridad y datos:** producto/cloud permanecen mock; el único real permitido
   es un gate sintético aislado con corpus hash-allowlisted, autorización durable,
   presupuesto y cero datos estudiantiles reales.
2. **Contratos/ownership:** targets e identidades que gobiernan persistencia son
   server-minted; roots canónicos imponen unicidad, cross-root y state machines.
3. **Trusted context:** facts tenant-scoped independientes del request alimentan
   allowlists y lenguaje.
4. **Seguridad transversal:** un visitor de texto generado cubre persistencia,
   review y export; las anclas literales se mantienen como datos hostiles.
5. **Planner:** selección exacta N, criterios requeridos, mínimos global/template,
   reservas distintas y fallo atómico sin plan parcial.
6. **Cache/reuse:** fingerprint por componente y dependencia, revalidación actual y
   procedencia `EXECUTED/REUSED` para parse, modelos, planner y assembly.
7. **Jobs:** transición dominio/job atómica, edición P05 coherente y dispatch/claim
   exacto en lugar de reclamar el queued más antiguo.
8. **Privacidad de control:** idempotencia mínima con TTL y sesión browser reducida.
9. **Evaluación:** rehearsal product-shaped reutiliza registry, prompts, schemas,
   gateway, validators y planner productivos; el ledger consume cada autorización
   antes de la primera red y los reportes no retienen outputs.

## 5. Prompts, contratos y validators

La frontera final usa prompt pack `1.1.13`:

| Prompt | Versión | Relationship | Application |
|---|---:|---|---|
| P04 | 1.1.11 | `relationship-p04/2.0.0` | — |
| P05 | 1.1.8 | `relationship-p05/2.2.0` | `application-validator-p05/2.1.0` |
| P06 | 1.1.5 | `relationship-p06/2.2.0` | `application-validator-p06/2.1.0` |
| P07 | 1.1.4 | `relationship-p07/2.1.0` | `application-validator-p07/2.0.0` |
| P08 | 1.1.4 | `relationship-p08/2.1.0` | `application-validator-p08/2.0.0` |
| P09 | 1.1.6 | `relationship-p09/2.0.0` | `application-validator-p09/2.0.0` |

Cambios relevantes: matriz P05 y preflight tipado; policy/floor del planner en
P06; herencia completa de templates; IDs target explícitos; referencias exactas
P07/P08; separación entre mensajes de seguridad del sistema y texto generado;
P09 observable; P11 diff estructural. `EvidenceMapRequest` transporta ahora la
misma `planning_policy` que ejecutará el planner. El schema JSON fue regenerado
exclusivamente desde el modelo canónico y revisado antes de reemplazarlo.

## 6. Rehearsal product-shaped y findings EXEC

El fixture `product-rehearsal/1.2.0` aporta dos escenarios sintéticos:
`synthetic-open-short-v1` y `synthetic-choice-justification-v1`. Cada uno fija
checkpoints post-P03, blueprint, mapping/planning y assessment. La versión 1.3.0
del runner observa P04, P05, P06, P07, P08 y P09 independientemente; el fallo de
una frontera no oculta las demás.

| Finding | Evidencia | Estado |
|---|---|---|
| EXEC-001 | Rehearsal trataba sólo `APPROVE` como transición válida y ocultaba la matriz P05. | CERRADO |
| EXEC-002 | Un `value_error` semántico activó P11 pese a ser sólo estructural. | CERRADO; P11 limitado a shape/schema. |
| EXEC-003 | Luna duplicó IDs dentro de P04. | CERRADO con prompt + contrato de unicidad. |
| EXEC-004 | P05 no distinguía identidades root de referencias allowlisted. | CERRADO con namespaces y checks agregados. |
| EXEC-005 | P06 no READY omitía diagnostics suficientes. | CERRADO en contrato/prompt; códigos de mismatch READY aún pueden granularizarse. |
| EXEC-006 | P05 reinterpretó factibilidad exacta-N. | CERRADO con preflight server-derived y checks vinculados. |
| EXEC-007 | P06 modificaba constraints heredadas del template. | CERRADO con igualdad completa y validator de relación. |
| EXEC-008 | El fixture inicial era demasiado delgado para representar producto. | CERRADO con bundle, policy, blueprint y variante ampliados. |
| EXEC-009 | Sweep acoplaba P04→P05 y P07→P08, ocultando fronteras hermanas. | CERRADO con seis checkpoints independientes. |
| EXEC-010 | P06 declaraba READY sin conocer el floor aplicado luego por planner. | CERRADO al transportar `planning_policy` y validar elegibilidad. |
| EXEC-011 | P07/P08 colapsaban varias divergencias de IDs en un código genérico. | CERRADO con códigos agregados content-free. |
| EXEC-012 | Un aviso global de seguridad terminaba dentro del texto generado y el visitor lo rechazaba. | CERRADO separando instrucción de sistema y contenido persistible. |
| EXEC-013 | Sweep final P05: `REJECT`, critical `CONSTRUCT`; warnings `COGNITIVE_DEMAND` y `SOURCE_FIDELITY`. | ABIERTO; validar si el checkpoint fijo o el juicio es la causa. |
| EXEC-014 | Cadena base 1 PASS; repetición congelada falla P06 `P06_REFERENCE_MISMATCH`. | ABIERTO; evidencia de inestabilidad, pero el subpredicado no quedó registrado. |
| EXEC-015 | Variante completa hasta P07; P08 devuelve resultado no aceptado. | ABIERTO; faltan decision/scores/códigos content-free para discriminar rechazo correcto de variabilidad. |

## 7. Validación ejecutada

| Superficie | Resultado |
|---|---|
| Backend completo | `make test-cov`: 544 passed, 16 skipped sólo por ausencia explícita de URL PostgreSQL en esa invocación, 1 warning conocido, 80% coverage. |
| PostgreSQL 17 temporal | migraciones/prepare PASS; E2E 1/1; sensitive 7/7; migration/recovery/readiness 158/158. |
| Contratos | 53 roots, 141 `$defs`, 277 refs y 8 fixtures PASS; schema generado sin edición manual. |
| Rehearsal offline | PASS; sweep 6/6, dos cadenas base 8/8 y variante 8/8; 24 fake, cero red/billable/P10/P11/fallback/retries. |
| Frontend | typecheck PASS; Vitest 36/36; build PASS. |
| Navegador | Flujo sintético renderizado completo y revisión responsive pasaron antes del freeze. |
| Deploy estático | 11/11 PASS. |
| Secret scan | PASS sobre 303 archivos versionables. |
| Terraform | fmt, init `-backend=false` y validate PASS. |

El contenedor PostgreSQL temporal se detuvo y eliminó. No se ejecutó build,
deploy, apply, migración remota ni E2E cloud.

## 8. Observaciones reales Luna

Todas usaron exclusivamente `gpt-5.6-luna`, Structured Outputs, `store=false`,
sin tools, máximo 30 requests, cap USD 0.75 por corrida y USD 0.10 por call.

| Boundary | Resultado | Attempts | Costo actual | Charge conservador | Señal principal |
|---|---:|---:|---:|---:|---|
| `400968b`, rehearsal 1.0.0 | FAIL | 12 | USD 0.06409709 | USD 0.20522789 | P04 IDs duplicados, P05/contexto y un único P11 estructural. |
| `e5dcb6a`, rehearsal 1.1.0 | FAIL | 14 | USD 0.07006282 | USD 0.25122322 | Sweep 6/6; P06 diagnostics, P05 feasibility y P06 variant refs. |
| `683d62c`, rehearsal 1.2.0 | FAIL | 14 | USD 0.07368182 | USD 0.25415702 | P07/P08 context, seguridad P07, P05 cognitive y planner variant. |
| `10d7622`, rehearsal 1.3.0 | FAIL | 20 | USD 0.10237906 | USD 0.33254266 | Una cadena 8/8; sweep P05, repetición P06 y variante P08 abiertos. |
| **Total** | — | **60** | **USD 0.31022079** | **USD 1.04315079** | El charge es reserva contable conservadora, no gasto real adicional. |

Reportes machine-readable y SHA-256:

- `stage2_convergence_400968b.json`: `5228ad37938a4e5d7ab91197e61f888b546c730f0040ff62431f4386b988eb65`;
- `stage2_convergence_e5dcb6a.json`: `d3020f60209db3fb9b5714e6f70df92984d4210e52f6549716d70871463078e3`;
- `stage2_convergence_683d62c.json`: `fe529b4ef20616673f35b1836a8185d73a8692a12692ee0ac2013a8c5a4e344e`;
- `stage2_convergence_10d7622.json`: `8f213bc6beede28906727c989b158292536dedafd6f309eaf8e099bc50d2b1c8`.

En total hubo P10=0, fallback=0 y retries gateway/SDK/semánticos=0. Sólo la
primera ronda usó P11=1; las tres fronteras posteriores y la última corrida de
salida usaron P11=0.

### Evaluación de Luna

Una cadena real completa demuestra que Luna puede satisfacer esta forma; no
demuestra estabilidad. La segunda cadena bajo prompts, schemas, validators y
routing idénticos falló antes de planner, y la variante no completó P08. Esto es
compatible con variabilidad del modelo, pero no permite atribuirla de forma
concluyente porque los códigos finales P06/P08 aún son demasiado gruesos y el
reporte deliberadamente no retiene outputs.

Clasificación: **`NEEDS_MORE_EVIDENCE`**, materialmente incompatible con READY.
No se ocultó mediante retry, normalización, validator relajado, fallback o cambio
de modelo.

## 9. Brechas abiertas y continuación segura

1. Auditar offline el checkpoint fijo P05 contra el constructo y su preflight.
   Si es inválido, corregir el fixture por razones de producto; si es válido,
   conservarlo congelado.
2. Dividir `P06_REFERENCE_MISMATCH` en subcódigos content-free y registrar en
   P08 decisión, critical codes y umbrales/scores numéricos seguros. Esto mejora
   diagnóstico sin relajar producción ni retener contenido.
3. Tras tests locales, decidir explícitamente si se autoriza una única repetición
   acotada bajo una nueva boundary/authorization. No reutilizar ninguna de las
   cuatro autorizaciones consumidas.
4. Sólo después de convergencia, resolver REL-001 con un único build del HEAD,
   digest/provenance, plan sellado y E2E sintético en una fase posterior.
5. Mantener INF-001 externo y privacidad/hardening residual como bloqueadores
   antes de datos reales, que siguen fuera de alcance.

## 10. Criterio de convergencia, punto por punto

| # | Criterio | Estado | Evidencia |
|---:|---|---|---|
| 1 | P0/P1 relevantes cerrados/refutados | **NO** | Deterministas cerrados; EVAL-002, OBS-001 parcial y REL-001 siguen abiertos/deferidos. |
| 2 | P2 de evaluación manual resueltos/aceptados | **SÍ** | P06/PLAN/P08/API/PRIV/AUTH/IMAGE cerrados; INF externo aceptado para sintético. |
| 3 | Suite local completa verde | **SÍ** | Backend, PG17, frontend, browser, deploy y Terraform verdes. |
| 4 | Contratos/fixtures/OpenAPI sin drift | **SÍ** | Gate canónico y fixtures PASS; schema regenerado. |
| 5 | Sweeps product-shaped P04–P09 verdes | **NO** | 1.1.0 pasó 6/6, pero la frontera final 1.3.0 falló P05. |
| 6 | Una cadena integrada real completa | **SÍ** | `real-chain-base-1`, 8/8, reporte `10d7622`. |
| 7 | Segunda cadena consecutiva sin cambios | **NO** | `real-chain-base-2` falló P06. Boundary unchanged=true. |
| 8 | Cadena completa sobre variante distinta | **NO** | Variante llegó a P08 y no fue aceptada. |
| 9 | Cero schema/Pydantic/context/security en corridas de salida | **NO** | La primera cadena sí; no existe conjunto completo de corridas de salida. P06 falló contexto. |
| 10 | P10 off | **SÍ** | 0 en las cuatro corridas. |
| 11 | Sin fallback | **SÍ** | 0. |
| 12 | Sin retries semánticos | **SÍ** | 0; gateway y SDK también 0. |
| 13 | Evidencia suficiente de confiabilidad Luna | **NO** | Una cadena PASS seguida de P06/P08 FAIL; `NEEDS_MORE_EVIDENCE`. |
| 14 | Sin findings abiertos incompatibles con READY | **NO** | EXEC-013/014/015 y EVAL-002 son materiales. |

## 11. Recomendación

**`CONVERGENCE_INCOMPLETE`**

No hacer build/deploy/E2E cloud final. La próxima decisión debe concentrarse en
diagnóstico content-free de P05/P06/P08 y, sólo con una autorización nueva,
una repetición real congelada y acotada.
