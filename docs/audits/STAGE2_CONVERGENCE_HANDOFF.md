# Handoff final — Terra/MEDIUM requalification con pricing vigente

Fecha de corte: 2026-08-13 (America/Santiago).

Fase: **`TERRA_MEDIUM_PRENETWORK_PRICE_REFRESH_AND_CONTROLLED_REQUALIFICATION`**.<br>
Veredicto: **`TERRA_MEDIUM_QUALIFICATION_FAILED`**.<br>
Convergencia: **`CONVERGENCE_INCOMPLETE`**.<br>
Clasificación causal:
**`MODEL_OWNED_SEMANTIC_AND_ADHERENCE_FAILURE_WITH_INDETERMINATE_FAILURES`**.<br>
Autoridad siguiente:
**`INDEPENDENT_HARNESS_REVIEW_BEFORE_ANY_TERRA_HIGH_AUTHORITY`**.

Se ejecutó exactamente una nueva matriz real, sintética y billable con
`gpt-5.6-terra` y `reasoning.effort=medium`. No hubo segunda matriz, retry,
fallback, P10, P11, tuning, cambio de producto, deploy ni datos estudiantiles
reales. El receipt crudo se conserva byte-inmutable y el candidato ejecutado
no se modificó después del primer request.

## 0. GitHub y candidato ejecutado

| Elemento | Valor |
|---|---|
| Repositorio / checkout | `WilJms/PruebasPersonalizadas` / `/Users/wiljms/Documents/PruebasPersonalizadasCodex` |
| Branch | `codex/openai-real-provider-gate` |
| PR | `#3`, `OPEN`, `DRAFT`, `MERGEABLE` |
| HEAD inicial contrastado | `2fec84c012ad3aaf2be30763ddb927c6d4bb8049` — `Harden qualification harness semantics` |
| Commit pricing/budget y candidato | `0dbf6142e80f3d3e2aaae9076fe7d8eb3b0280ef` — `Freeze Terra MEDIUM qualification budget` |
| Parent del candidato | `2fec84c012ad3aaf2be30763ddb927c6d4bb8049` |
| CI candidato | push `31754665685`, attempt 2, 7/7 PASS; PR `31754668491`, 7/7 PASS |
| Árbol al ejecutar | tracked tree e index limpios; sólo `coverage.xml` y `reports/openai/blueprint_v119_v115_recanary_a2be3c6.json` untracked preexistentes |

El primer attempt del job backend del run push encontró una carrera
preexistente de SQLite al activar WAL en
`test_exactly_once_ledger_is_atomic_under_concurrency`; el mismo test pasó
aislado, en el run PR sobre el mismo SHA y en el único rerun del job CI. No se
cambió código ni candidato para ocultar el flake. El SHA documental posterior
y su CI se publican en el PR y en la entrega final para evitar autorreferencia
del propio commit.

## 1. Pricing oficial y budget congelado

Se reverificaron inmediatamente antes del gate las páginas oficiales de
pricing y del modelo. La referencia de la autoridad —USD `2.50` input,
`0.25` cached y `15.00` output— estaba desactualizada. Los precios Standard
short-context vigentes y usados son:

| Modelo | Input / 1M | Cached / 1M | Cache write / 1M | Output / 1M |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | USD 5.00 | USD 0.50 | USD 6.25 | USD 30.00 |
| `gpt-5.6-terra` | USD 2.00 | USD 0.20 | USD 2.50 | USD 12.00 |
| `gpt-5.6-luna` | USD 0.20 | USD 0.02 | USD 0.25 | USD 1.20 |

Fuente: `https://developers.openai.com/api/docs/pricing`; observed date
`2026-08-13`. El modelo exacto soporta Responses, Structured Outputs y
`medium`. Cache writes cuestan `1.25 ×` el input no cacheado. Requests con
más de `272,000` input tokens cuestan `2 ×` input y `1.5 ×` output para la
request completa. Las rutas calificadas tienen ceiling de input `250,000`,
incluyendo allowance de framing `1,024`, por lo que el multiplicador long
context no aplica.

`openai_pricing.py` ya contenía exactamente estos valores al reanclar, por lo
que no se fabricó un diff de pricing. El delta permitido quedó limitado a la
derivación auditable, caps, authorization metadata, receipts por llamada,
Make/CLI y tests del harness.

La reserva worst-case trata todo el input como cache write y todo el output
como consumido:

| Prompt | Calls | Input/output ceilings | Coste por call | Subtotal |
|---|---:|---:|---:|---:|
| P04 | 5 | 250,000 / 16,000 | USD 0.817 | USD 4.085 |
| P05 | 6 | 250,000 / 16,000 | USD 0.817 | USD 4.902 |
| P06 | 5 | 250,000 / 16,000 | USD 0.817 | USD 4.085 |
| P07 | 6 | 250,000 / 10,000 | USD 0.745 | USD 4.470 |
| P08 | 6 | 250,000 / 8,000 | USD 0.721 | USD 4.326 |
| P09 | 5 | 250,000 / 10,000 | USD 0.745 | USD 3.725 |
| **Total** | **33** | — | **máximo USD 0.817** | **USD 25.593** |

Ceiling fail-closed a centavos: request cap `33`, max-call cap USD `0.82` y
total cap USD `25.60`. Pricing policy hash
`sha256:1043f12f6cce4be87f0a27af1062a30d7cab835dca12ab50ec9a6286a770c5ba`;
matrix hash
`sha256:94fbd798732b057f3ba051144a0f0de5533ce6ffb85b103d766c6abeb660ea49`.
Los caps históricos USD `5.10`/`0.27` permanecen registrados sólo como
historia y no fueron reutilizados.

## 2. Regresión y dry-run pre-network

| Superficie | Resultado |
|---|---|
| Pricing/harness/semantic/classifier | 77/77 focales PASS; matrix y ramas causales cubiertas |
| Backend completo | 670 PASS, 17 skips sólo de PostgreSQL cubierto aparte, coverage 81 % |
| PostgreSQL 16 / 17 | migrations, readiness, recovery y suites: 215/215 PASS en cada versión |
| Contratos/schema/OpenAPI/client | contratos 1.2, 141 definiciones, 8 fixtures; 40 tests focales; regeneración idempotente |
| Frontend | `npm ci`, typecheck, 36/36 tests, build y audit 0 PASS |
| Browser/Playwright | QA desktop/mobile sin errores ni overflow; Stage 1 1/1 y Stage 2 2/2 PASS |
| Terraform/static/deploy | fmt/init sin backend/validate PASS; deploy artifacts 11/11; YAML/shell PASS |
| Docker | runtime/audit images, health/readiness y Stage 0 audit PASS |
| Seguridad | secret scan PASS sobre 329 archivos versionables |
| DOCX | rebuild byte-idéntico 4/4; render de una página e inspección visual 4/4 PASS |
| Rehearsal Terra/MEDIUM | 33/33 simulados, 9 reviewed oracles + 24 transport substitutes, PASS, red 0 y secret resolution 0 |

El dry-run confirmó modelo único `gpt-5.6-terra`, MEDIUM P04–P09, P05
offline ± PASS, base1/base2/choice/canonical PASS, cero golden intermedio en
canonical, P10/P11/retry/fallback `0`, tools/store/background `false` y caps
exactos USD `25.60`/`0.82`/`33`.

## 3. Frontera congelada

| Material | Identidad |
|---|---|
| Route/model/effort | `TERRA_MEDIUM_V1` / `gpt-5.6-terra` / MEDIUM P04–P09 |
| SDK / adapter | OpenAI Python `2.53.0` / `OpenAIResponsesAdapter`, Responses API |
| Planner / assembler | `stage2-planner/2.0.0` / `stage1-assembler/2.0.0` |
| Semantic fixture | `sha256:4a5cd49f86256839befc19cfd9aa9c803726929d5124e4c38d8ac3a82a999b12` |
| Executable boundary | `sha256:0977efb472f6a39b971b79cfc868cf3a45dd68a79be515a80542a998d7a2dbd7` |
| Authorization boundary | `sha256:75ab8e7f8f80de07a1be07b276a3aee5aeba92ef635f19f8b21ad08407ac8c3f` |
| Authorization hash | `sha256:124562d092475f589c541d76cede7177ea2a4f09793d38b6cd6e5b1c42bc9ea4` |
| Harness / rehearsal module | `sha256:1f5c663d133bd823f1fa97bce843573fb534ca8ae28c844d2495eb326aae141c` / `sha256:adf9a6c1ae88e07f9053751744147e18b761a9f2233c624b0cdcdcfc7060ac10` |
| Manifest | `sha256:d5991a48253eead5a4ba87653323177144fb67a4ae455ec9e2595a3e153ffb11` |
| Contract / schema / OpenAPI / client | `3f1a42102b10a558f42885a14034d5d41944f7c23f597d257baa6dd21d2cee0f` / `318f1dceee27f919934aa11eab81cfab703bfd5791e7b72c6d3e636f36304e8d` / `83cd3dbcc728c613460533fb9841df335524fc44c28242d80b5482d8afafd0a2` / `2ee42d9587897ddc1546308b0541e6aa196b03cb9f5c8bb8ed839af7cfddb303` |

Prompts congelados:

| Prompt | Versión | Hash |
|---|---|---|
| P04 | 1.1.11 | `sha256:f8c12331bacc676920095f353b8a3d7180f90ba2015c23aa3a378cbb505064e0` |
| P05 | 1.1.8 | `sha256:4b38cf144dd44ce235399efdf6938f611bfac820aa3b31497859f5fd5e426bb4` |
| P06 | 1.1.5 | `sha256:01bf8fabac2cf3c7aa235b4ecb0e16edf8844a57efe7be2aaac7ffa2948d2e26` |
| P07 | 1.1.4 | `sha256:db0f6d91ad0357bbd7984e2b7d8564944e969fa8f39c0b95ca88085157d24b6c` |
| P08 | 1.1.5 | `sha256:f63230dde5dadbbba78b24ae229fefc61a6b7d072a9c3d7c1ea9044be2463949` |
| P09 | 1.1.6 | `sha256:a7607fb64499efdbb377469d1078ae758cfd47d09828f35af1ac603b46b5f2d3` |

Relationship/application validators permanecieron, respectivamente:
P04 `2.0.0`/none; P05 `2.2.0`/`2.2.0`; P06 `2.3.0`/`2.1.0`; P07
`2.1.0`/`2.0.0`; P08 `2.1.0`/`2.0.0`; P09 `2.0.0`/`2.0.0`.
Thresholds P08: groundedness `0.90`, anchor sufficiency `0.80`, answerability
`0.85`, criterion relevance `0.80`, escalate below confidence `0.65`.

Los cuatro DOCX preservaron sus hashes: assignment
`ac8ade8c3dc529d06d439dcbc3af0b866c6e1deaa3ebaa0552963f7a93d54025`, rubric
`71c8101a6d1c50acb81c2f04e8479540e9c90a35974819f46af497a81f5361f7`, sufficient
`d4983ba075c625f4c58858db8ec02a603f57b71145517e7160afd29df32be49a` e insufficient
`67d3ebaff85dfa269c65a8df23d3cc0e18631c6b2a51613c82fadeb2098f8204`. No cambió
prompt, schema funcional, validator, threshold, planner, assembler, model
payload, routing effort, retry/fallback ni product workflow.

## 4. Única qualification real

Execution ID:
`stage2-terra-medium-requalification-0dbf614-20260813-final-01`.<br>
Authorization ID:
`authorization-stage2-terra-medium-requalification-0dbf614-20260813-final-01`.<br>
Inicio/fin UTC: `2026-08-13T23:59:52.856279Z` /
`2026-08-14T00:05:33.219281Z`.

La autorización se reservó durablemente antes de resolver el secreto pinneado.
El ledger quedó terminal `FAILED`; la autorización no es recuperable ni
reutilizable.

### Semantic sweep — 9/9 provider calls realizadas

| Checkpoint | Review v1.0.0 | Resultado | Interpretación / causalidad |
|---|---|---|---|
| `P04_CANONICAL_POSITIVE` | `SR-P04-CACHE-POS-001` / `63aabc66a4664d9d4393ab0d4708ff383ce2d17bd21e2be969319e04024b0bf2` | PASS | semantic CORRECT; adherence PASS |
| `P05_CANONICAL_POSITIVE` | `SR-P05-CACHE-BLUEPRINT-001` / `2f3baf9c64931487f53fcfc6c3d4557e4f634cb776a0a4dd65918f2ffddb42b1` | FAIL | `BLUEPRINT_REVIEW_PREFLIGHT_MISMATCH`; adherence FAIL, HIGH model-owned |
| `P05_PLAN_FEASIBILITY_NEGATIVE` | `SR-P05-CACHE-PLAN-NEG-001` / `9d1bba041da78a78600a7645d40cb62aba8294c90e6c1c976e796b4e8490e808` | FAIL | no rechazó el negative; semantic INCORRECT, HIGH model-owned |
| `P06_CANONICAL_POSITIVE` | `SR-P06-CACHE-MAP-POS-001` / `8cdfd4dcc53decab54e1167c20625573fb00b5e511ab92eb141b5975b08634d4` | FAIL | oportunidad canónica ausente; semantic INCORRECT, HIGH model-owned |
| `P07_CANONICAL_POSITIVE` | `SR-P07-CACHE-POS-001` / `fc20c9360a36707762a91d76d2ce9f9d3c167bc8bcb088d1f94d6e8397e084f1` | FAIL | `ANCHOR_NOT_DERIVABLE`; adherence FAIL, HIGH model-owned |
| `P07_INSUFFICIENT_NEGATIVE` | `SR-P07-CACHE-NEG-001` / `3a8c665373a3aad141571d8aced682410d5c7d3a8747eac2f91f2f12122006c2` | FAIL | no se abstuvo; semantic INCORRECT, HIGH model-owned |
| `P08_CANONICAL_POSITIVE` | `SR-P08-CACHE-POS-001` / `e28976bdc1ad874d4fad0bc465a73eec899354b3edcdebaefc631167d4e36493` | PASS | semantic CORRECT; adherence PASS |
| `P08_UNANSWERABLE_NEGATIVE` | `SR-P08-CACHE-NEG-001` / `a1094aefabd40a9396bda991679f36332adab024e33e667906fc3b2f8d75ef24` | PASS | rechazo correcto; semantic CORRECT, HIGH |
| `P09_CANONICAL_POSITIVE` | `SR-P09-CACHE-POS-001` / `515ea95c840e9b8fb430ab744c3c9863fcfe5064c4c222afd32f50c9639710f4` | PASS | semantic CORRECT; adherence PASS |

Todos los oracles del sweep constan `VALID`. Los cinco failures model-owned
poseen confianza `HIGH`; por ello cumplen la regla humana de clean
model-owned failure aunque coexistan fallos indeterminados en cadenas
integradas.

### Deterministic checks e integrated chains

| Fila | Calls | Resultado | Clasificación |
|---|---:|---|---|
| P05 positive offline | 0 | PASS | `APPROVABLE`, `READY`, `APPROVE` |
| P05 negative offline | 0 | PASS | `REJECT`, sólo `PLAN_FEASIBILITY` crítico |
| Base 1 | 3 | INCOMPLETE | planner fail-closed `ASSESSMENT_PLAN_INFEASIBLE`; `CAUSE_INDETERMINATE`, LOW |
| Base 2 | 6 | PASS | P04→P09 completo |
| Choice variant | 6 | PASS | P04→P09 completo |
| Canonical DOCX sufficient | 2 | INCOMPLETE | P05 `REJECT` por `CONSTRUCT`; `CAUSE_INDETERMINATE`, LOW |

Las cadenas miden composición y no se usaron como jueces stage-local. Las
paradas fail-closed explican `26` requests efectivas frente al cap worst-case
`33`; no se redujo ni alteró la matriz.

## 5. Provider controls, tokens y costo

| Control | Resultado |
|---|---|
| Requests reales / cap | `26 / 33` |
| Input tokens | `131,539` |
| Cached input / cache-write input | `52,948 / 78,513` |
| Output / reasoning tokens | `34,970 / 10,995` |
| Costo real / cap | USD `0.6266681 / 25.60` |
| Charge conservador / cap | USD `4.3110281 / 25.60` |
| Máximo costo real / cap por call | USD `0.0456955 / 0.82` |
| Máximo charge conservador / cap por call | USD `0.2083485 / 0.82` |
| Attempts sin precio / errores técnicos | `0 / 0` |
| Gateway / SDK / semantic retries | `0 / 0 / 0` |
| Fallback / repaired | `0 / 0` |
| P10 / P11 | `0 / 0` |
| Tools / store / background | `false / false / false` |
| Modelo / effort | sólo `gpt-5.6-terra` / sólo MEDIUM en P04–P09 |
| Provider hashes | input/output/request-id presentes en 26/26 calls; contenido no persistido |
| Boundary | `unchanged_boundary_across_chains=true` |

No hubo provider error, timeout, schema-invalid ledger result ni causa
technical-only. Todas las 26 invocaciones tuvieron attempt `1`, transport
real, hashes completos y cero retry/fallback.

## 6. Receipt, ledger y veredicto

Receipt crudo e inmutable:
`reports/openai/stage2_terra_medium_requalification_0dbf614_20260813_final_01.json`.<br>
SHA-256:
`8971d8ce0c07cfcb0574f909f24a6db79b83daaa2334124db65a64d0e5e4f17d`.

Ledger durable fuera del repo:
`/Users/wiljms/.codex/evaluation-ledgers/PruebasPersonalizadas/stage2-terra-medium-requalification-0dbf614-20260813-final-01.sqlite3`.
Estado `FAILED`, failure code `TERRA_MEDIUM_QUALIFICATION_FAILED`, boundary
hash y report hash coincidentes con el receipt. El receipt no se consolidó,
reescribió ni reinterpretó retroactivamente.

`TERRA_MEDIUM_QUALIFICATION_FAILED`<br>
`CONVERGENCE_INCOMPLETE`

## 7. Controles de salida

- Segunda matriz Terra/MEDIUM: `0`.
- Terra/HIGH, XHIGH o MAX: `0`.
- Luna o Sol: `0`.
- Prompt/model tuning: `0`.
- Cambios de validators/thresholds/planner/assembler/product workflow: `0`.
- P10/P11, retry y fallback: `0`.
- Cloud Build, deploy, `terraform apply`, migración remota y cloud E2E: `0`.
- Datos estudiantiles reales: `0`; clasificación
  `SYNTHETIC_ONLY_NO_STUDENT_DATA`.
- Merge o mark-ready: `0`; PR continúa draft.

Los receipts históricos Luna/HIGH, Luna/XHIGH, Luna/MAX raw/consolidado y
Terra/MEDIUM anterior mantienen, respectivamente, SHA-256 `30a422dc…`,
`1b62c99b…`, `532ba5e1…`, `74fc1323…` y `af56425a…`. La qualification anterior
sigue metodológicamente contaminada; este nuevo receipt no reescribe su
historia.

La operación queda detenida para revisión independiente. No se autoriza HIGH,
otra matrix ni fase posterior.

---

# Anexo histórico — hardening semántico final del harness de Fase 2

Fecha de corte actual: 2026-08-13 (America/Santiago).

Fase: **`HARNESS_FINAL_SEMANTIC_HARDENING`**.<br>
Estado local: **completo y pendiente únicamente de CI del commit publicado**.<br>
Siguiente autoridad posible: **revisión independiente final del harness**.<br>
Qualification real autorizada por este handoff: **ninguna**.

Esta fase corrige exclusivamente los cuatro defectos metodológicos restantes:
el oracle generativo de P07, la agregación causal global, la ausencia de la
segunda cadena base y la falta de una cadena integrada document-shaped. No
modifica el producto ni reinterpreta receipts históricos. El resultado durable
de Terra/MEDIUM continúa siendo `TERRA_MEDIUM_QUALIFICATION_FAILED`, pero su
qualification sigue metodológicamente contaminada y su causalidad histórica no
constituye evidencia limpia de fallo model-owned.

## 0. Reanclaje de esta fase

| Elemento | Estado observado antes de editar |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` (privado) |
| Checkout | `/Users/wiljms/Documents/PruebasPersonalizadasCodex` |
| Branch local/remota | `codex/openai-real-provider-gate` |
| HEAD local / remoto / GitHub | `29a69d5da9c9d56e977eb21f3a39ed63d59a5e7d` |
| Commit de entrada | `Remediate qualification harness semantics` |
| PR | `#3`, `OPEN`, `DRAFT`, `MERGEABLE` |
| CI de entrada | push `31741903012` y PR `31741907761`, 14/14 jobs PASS agregados |
| Árbol inicial | sólo `coverage.xml` y `reports/openai/blueprint_v119_v115_recanary_a2be3c6.json` untracked preexistentes; no se incorporan |

Se contrastaron checkout, remoto, PR, commits, checks, body, receipts, fixtures,
boundary congelada, DOCX y reporte offline. También se verificaron las
herramientas locales de Python, frontend, PostgreSQL 16/17, Docker, Terraform,
contratos/OpenAPI/client, parser DOCX, LibreOffice y GitHub. No se obtuvo ni se
intentó resolver ningún secreto de provider.

El SHA final y los run IDs de CI se publican en el PR y en la entrega final: no
se incrustan en el mismo commit para evitar una autorreferencia imposible.

## 1. Cambios finales del instrumento

### P06 — equivalencia semántica, no igualdad de mapping

El positive exige `READY`, contexto cerrado, operación `JUSTIFY_DECISION`,
dimension/variant correctas, IDs y allowlist válidos, evidencia causal que
cubra cambio de fuente, invalidación, riesgo de obsolescencia y nueva
consulta/recálculo, métricas sobre los mínimos congelados y al menos una
oportunidad elegible por el planner productivo. Claims, IDs alternativos y
redacción pueden variar. Un mapping equivalente pasa; evidencia equivocada o
incompleta no pasa.

### P07 — oracle por invariantes

El golden `GOLDEN-P07-CACHE-POS-001` queda como ejemplo revisado, no como única
respuesta permitida. El oracle ya no compara `candidate.model_dump()` completo.
Evalúa determinísticamente status/candidate, IDs, contexto cerrado, allowlist,
template/dimension/variant/operación, formato, dificultad, tiempo, suficiencia
del anchor, límites inferenciales, guía preliminar, PII/leakage y validators
congelados. Una pregunta con wording distinto y los mismos invariantes pasa;
una que exige implementación, concurrencia o conocimiento externo falla; una
salida genuinamente no decidible queda `INDETERMINATE`.

### Outcome global — incertidumbre no es FAIL

`_terra_medium_qualification_outcome()` sólo emite
`TERRA_MEDIUM_QUALIFICATION_FAILED` cuando existe un checkpoint semánticamente
calificado, oracle válido, failure model-owned limpio y confianza `HIGH` en
semántica, adherence o ambas. `CAUSE_INDETERMINATE`, oracle inválido/no
establecido y technical-only producen
`TERRA_MEDIUM_QUALIFICATION_INCONCLUSIVE`; la clasificación causal específica
se conserva aparte. Todos los obligatorios PASS producen
`TERRA_MEDIUM_QUALIFICATION_PASSED`.

### Base 2 — composición independiente restaurada

`integrated-chain:base:2:P04-P09` vuelve a la matriz con run ID, seis
invocaciones y outputs independientes de base 1. No hay replay, retries ni
fallback. Como todas las cadenas integradas, mide composición/estabilidad y no
autoriza por sí sola atribución stage-local. Un stop propagado por el planner
se conserva como chain incomplete y `CAUSE_INDETERMINATE` si no puede aislarse
la causa upstream.

### Canonical document-shaped chain

Se añadió `integrated-chain:canonical-document-sufficient:P04-P09`:

`DOCX → parser productivo → EvidenceUnit/EvidenceBundle → P04 → P05 → P06 → planner → P07 → P08 → assembler productivo → P09`.

La entrada se deriva de los cuatro artefactos `SYNTHETIC_ONLY_NO_STUDENT_DATA`.
Cada request downstream consume outputs producidos dentro del mismo run; las
ocho filas de dataflow registran hashes de entrada/salida y
`intermediate_golden_injected=false`. Los goldens sólo evalúan el semantic
sweep; nunca alimentan esta cadena. En offline, `DeterministicMockAdapter`
actúa exclusivamente como `STRUCTURAL_TRANSPORT_SUBSTITUTE`, no como oracle de
calidad. La futura ejecución provider usaría la misma frontera congelada, sin
retries, fallback, P10 ni P11.

### Provenance de reviews

El pack declara verazmente:

- `authoring_class=CODEX_AUTHORED_SEMANTIC_REVIEW`;
- `independent_review_status=USER_SUPPLIED_INDEPENDENT_REVIEW_FINDINGS`;
- `human_ratification=null`;
- `provider_response_used_as_target=false`.

`SR-PROVENANCE-AMENDMENT-001` v1.0.0 corrige sólo la atribución de autoría. Los
nueve review IDs/versiones y hashes registrados previamente se preservan en
`prior_review_hashes`; el material actual y el amendment poseen hashes
separados, por lo que no se fabrica una ratificación humana ni se rompe el
linaje.

## 2. Matriz futura evidence-first y request cap derivado

| Row | Clase | Provider calls máximas |
|---|---|---:|
| `semantic-sweep:P04-P09:versioned-positive-and-negative` | atribución semántica stage-local: P04, P05+/−, P06, P07+/−, P08+/−, P09 | 9 |
| `offline-golden-positive:P05` | oracle determinista offline | 0 |
| `offline-golden-negative:P05` | oracle determinista offline | 0 |
| `integrated-chain:base:1:P04-P09` | composición end-to-end | 6 |
| `integrated-chain:base:2:P04-P09` | composición end-to-end independiente | 6 |
| `integrated-chain:choice-variant:P04-P09` | composición end-to-end variante | 6 |
| `integrated-chain:canonical-document-sufficient:P04-P09` | composición desde frontera DOCX | 6 |
| **Worst case derivado** | **7 rows** | **33** |

El cap `33` se calcula como suma de la matriz y es compartido por rehearsal,
authorization plan y CLI; no se diseñó la evidencia alrededor del antiguo cap
24. El sweep usa `REVIEWED_SEMANTIC_ORACLE` en nueve invocaciones. Las cuatro
cadenas usan 24 `STRUCTURAL_TRANSPORT_SUBSTITUTE` y declaran
`semantic_quality_conclusion_allowed=false`.

Los caps monetarios históricos USD `5.10`/`0.27` no se reutilizan. El estado
queda `RECALCULATION_FROM_CURRENT_OFFICIAL_PRICES_REQUIRED`. El target real de
Terra/MEDIUM falla cerrado con
`OPENAI_TERRA_MEDIUM_MONETARY_BUDGET_RECALCULATION_REQUIRED` antes de pedir o
resolver secreto, abrir ledger o construir transporte. Una eventual nueva
qualification requiere revisión independiente, precios oficiales vigentes y
una autorización humana nueva.

## 3. Evidencia reproducible y revisión adversarial

Reporte: `reports/openai/harness_semantic_remediation_offline.json`.<br>
Schema/rehearsal: `stage2-semantic-harness-report/1.1.0` /
`stage2-semantic-harness-rehearsal/1.1.0`.<br>
SHA-256: `36ef8051ef2d21c303d2bb08175ea68db1dacc91d7c6965f05a85371bc41914e`.<br>
Fixture: `stage2-semantic-qualification-pack/1.0.0`, canonical hash
`sha256:4a5cd49f86256839befc19cfd9aa9c803726929d5124e4c38d8ac3a82a999b12`.

Los 18 checks del reporte están en PASS. La revisión adversarial registra 19
preguntas PASS y demuestra específicamente: P06/P07 equivalentes válidos pasan;
malos anchors/evidence/knowledge externo fallan; casos no decidibles quedan
`INDETERMINATE`; indeterminate y technical-only agregan INCONCLUSIVE;
model-owned limpio agrega FAILED; base2 existe; la cadena documental usa
outputs del run y cero goldens intermedios; el cap suma 33; y la autoría de
reviews es veraz.

Los DOCX fueron regenerados a un directorio efímero y comparados byte a byte
con los fixtures. LibreOfficeDev 26.8 + `render_docx.py` produjo exactamente
una página por documento; se inspeccionaron visualmente las cuatro páginas sin
clipping, overflow, superposición, tabla rota, sustitución visible de fuente ni
página vacía. Los hashes permanecen:

| Documento | SHA-256 |
|---|---|
| `official_assignment.docx` | `ac8ade8c3dc529d06d439dcbc3af0b866c6e1deaa3ebaa0552963f7a93d54025` |
| `official_rubric.docx` | `71c8101a6d1c50acb81c2f04e8479540e9c90a35974819f46af497a81f5361f7` |
| `submission_sufficient.docx` | `d4983ba075c625f4c58858db8ec02a603f57b71145517e7160afd29df32be49a` |
| `submission_insufficient.docx` | `67d3ebaff85dfa269c65a8df23d3cc0e18631c6b2a51613c82fadeb2098f8204` |

El insufficient sigue siendo negative semántico: abstención correcta no es
failure semántico; una abstención con Diagnostic inválido sí es failure de
adherence independiente.

## 4. Regresión offline de esta fase

| Superficie | Resultado |
|---|---|
| Harness semántico + eval/outcome/matrix | 72/72 PASS |
| Backend completo | 668 PASS, 17 skipped sólo por PostgreSQL separado; coverage 81 % |
| PostgreSQL 16 y 17 efímeros | prepare/migrations PASS; recovery/readiness 206/206; E2E 1/1 y sensitive 8/8 repetidos; contenedores eliminados |
| Contratos/schema/fixtures | contratos 1.2, 141 definiciones, 8 fixtures PASS; regeneración idempotente |
| OpenAPI/client | regenerados desde fuente canónica, idempotentes y sin diff |
| Frontend | `npm ci`, typecheck, 36/36 tests, build y audit 0 vulnerabilidades PASS |
| Browser/Playwright | login→activities sin warnings/errors ni overflow a 320 px; Stage 1 1/1 y Stage 2 2/2 PASS |
| Terraform/static/deploy artifacts | fmt, init sin backend y validate PASS; artifacts 11/11; YAML y shell syntax PASS |
| Seguridad | secret scan PASS sobre 329 archivos versionables |
| DOCX | build determinista 4/4; render e inspección visual 4/4 PASS |
| Rehearsal final | 18/18 checks; 33 invocaciones offline; 9 reviewed oracles + 24 transport substitutes; PASS |

El CI final pertenece al commit que publica esta sección y se registra en el
PR #3 y en la entrega final. El PR debe permanecer `OPEN` y `DRAFT`; no se hace
merge ni se marca ready.

## 5. Freeze, controles y receipts históricos

El diff de esta fase está limitado a harness, CLI/eval runner, fixtures de
evaluación, tests, reporte offline y este handoff. La boundary congelada pasa y
confirma cero cambios en prompts P04–P09, system/developer text, contratos,
Pydantic, validators, thresholds, planner, assembler, product workflows,
routing/model/reasoning, retry/fallback, P10/P11, persistence y UI.

Controles finales del reporte: provider attempts reales `0`; billable requests
`0`; network calls to OpenAI `0`; provider adapter constructed `false`; provider
secret resolved `false`; Terra/Luna/Sol executions `0/0/0`; P10/P11 calls
`0/0`; deploys `0`.

Todos los receipts permanecen byte-inmutables:

| Receipt | SHA-256 preservado |
|---|---|
| Luna/HIGH | `30a422dc79a2098ff6e7066a39cb2517e959d2d1d8a169f287c68101c2dc519e` |
| Luna/XHIGH | `1b62c99b19781d923df9eda4082b8e73de64de2c4a4253b65d555e7d70e8db1a` |
| Luna/MAX raw | `532ba5e19537c039f9746c177ae3ed17cf9fbc3d6fdb9bf34c5f07f32a6eda0e` |
| Luna/MAX consolidado | `74fc1323da3925a9805b4c957bbd597b342909f4b77855fcce706db6afbb17fd` |
| Terra/MEDIUM | `af56425a8d00fc1bbcee06c6e088f590cff68c9938c2b23190c1b5a72fdd776c` |

No se ejecutó Terra/MEDIUM después de esta validación. El instrumento queda
detenido para revisión independiente final.

## Anexo 0 — remediación semántica anterior (estado previo)

Fecha de corte actual: 2026-08-13 (America/Santiago).

Fase: **`HARNESS_SEMANTIC_REMEDIATION`**.<br>
Conclusión independiente gobernante: **`B — HARNESS_SEMANTIC_REMEDIATION_REQUIRED`**.<br>
Estado de qualification real: **no ejecutada en esta fase**.<br>
Autoridad siguiente: **revisión independiente del harness; no Terra/HIGH**.

El resultado durable de la única ejecución Terra/MEDIUM se conserva sin
modificar: **`TERRA_MEDIUM_QUALIFICATION_FAILED`** y
**`CONVERGENCE_INCOMPLETE`**. Su campo histórico
`MODEL_OWNED_QUALIFICATION_FAILURE` ya no se interpreta como una conclusión
causal limpia: P05, P07 y P08 contenían defectos de oracle/input y P09 mezclaba
plumbing con calidad. La ejecución sí dejó una infracción contractual real en
P07 (`DIAGNOSTIC_INCOMPLETE`), pero la decisión semántica de abstenerse era
defendible. Las cadenas integradas también demostraron capacidad end-to-end.
El planner de la cadena base 2 falló cerrado correctamente; su causa upstream
permanece indeterminada.

Por ello, la qualification Terra/MEDIUM anterior queda explícitamente
**metodológicamente contaminada** como medición de confiabilidad semántica. Su
outcome machine-readable continúa siendo evidencia operacional histórica; su
clasificación causal anterior no es evidencia limpia de fallo model-owned.

Esta fase corrige sólo el instrumento. No cambia producto, prompts, schemas,
validators, thresholds, planner, assembler, rutas, payload, modelo ni
reasoning. No consume ni reutiliza una autorización, no resuelve el secreto y
no construye transporte real.

## 0. Reanclaje y estado real observado

| Elemento | Valor observado antes de editar |
|---|---|
| Repositorio | `WilJms/PruebasPersonalizadas` (privado) |
| Checkout | `/Users/wiljms/Documents/PruebasPersonalizadasCodex` |
| Branch local/remota | `codex/openai-real-provider-gate` |
| HEAD local / remoto / GitHub | `9dbce36d21ba6b28b32b051862cf8b305ded61e8` |
| Candidato Terra ejecutado | `9185dbaccc36cd2150f723525b13e00bf86c3842` |
| PR | `#3`, `OPEN`, `DRAFT`, `MERGEABLE` |
| CI candidato | push `31716336517`, PR `31716341310`, ambos 7/7 PASS |
| CI documental | push `31717845766`, PR `31717849698`, ambos 7/7 PASS |
| Árbol inicial | limpio salvo `reports/openai/blueprint_v119_v115_recanary_a2be3c6.json`, untracked preexistente y no incorporado |

Se verificaron acceso de escritura al checkout, Git/GitHub/PR/Actions, Python,
Node/frontend, PostgreSQL local, Docker, Terraform, generadores de contratos,
OpenAPI y cliente, parser DOCX, LibreOffice headless y secret scan. No se pidió
información recuperable del repositorio y no se reveló ninguna credencial.

## 1. Diagnóstico metodológico confirmado

| Checkpoint | Defecto del instrumento anterior | Corrección | Superficie congelada |
|---|---|---|---|
| P05 | `RubricSpec.criteria[criterion_1].grading_weight=1.0`, pero el blueprint positive tenía `grading_weight=null`; el supuesto positive no era source-faithful. | El golden conserva `1.0` y su revisión manual/versionada cubre las diez categorías canónicas; el negative `PLAN_FEASIBILITY` conserva la misma mutación y resultado. | Prompt P05, preflight, validator y criterio de aprobación. |
| P07 | `oppt_justify_cache_invalidation` autorizaba sólo evidencia que decía **cuándo** invalidar, no **por qué**; abstenerse era defendible. | Positive con condición, riesgo de obsolescencia y recálculo en la allowlist; negative legítimamente insuficiente con `REPLACEMENT_REQUIRED`, `candidate=null` y Diagnostic completo. | Prompt P07, validator, allowlists y forma fail-closed. |
| P08 | El candidate provenía de `DeterministicMockFactory` y pedía causalidad no suficientemente sustentada por el anchor. | Candidate positive revisado con scores sobre thresholds y candidate negative estructuralmente válido pero no respondible, cuyo resultado correcto es `REJECT`. | Prompt P08, validator, scores mínimos y thresholds. |
| P09 | Un Assessment estático con candidates mock servía simultáneamente como plumbing y supuesto oracle pedagógico. | El Assessment positive se deriva del P08 positive mediante `selected_question_from_candidate` y `assemble_assessment_snapshot`; la guía se valida contra ese snapshot. | Prompt P09, assembler y validator. |

Los checkpoints históricos P05/P07/P08 quedan invalidados como medición
semántica limpia; el P09 histórico queda clasificado sólo como plumbing. El
fixture v2 completo declara ahora
`LEGACY_INVALIDATED_NOT_AUTHORIZED_FOR_SEMANTIC_QUALIFICATION`, y todas sus
filas mock son `STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY`.

## 2. Goldens y revisiones semánticas versionadas

Fuente principal:
`tests/fixtures/openai_evals/v3/semantic_qualification_pack.json`, versión
`stage2-semantic-qualification-pack/1.0.0`, canonical hash
`sha256:6ea22a27b96d7f2932b75e0302d1cef20a70f30a7c282c96ad46cec33f9fd8b9`.

| Checkpoint / golden | Clase / expected | Semantic review | Review hash | Golden hash |
|---|---|---|---|---|
| `GOLDEN-P04-CACHE-POS-001` v1.0.0 | positive / `READY` | `SR-P04-CACHE-POS-001` v1.0.0 | `sha256:63aabc66a4664d9d4393ab0d4708ff383ce2d17bd21e2be969319e04024b0bf2` | `sha256:6ecf88f553fdf0323f027be16f39b1105c2b434d7b671eb77fcb8ec63235015b` |
| `GOLDEN-P05-CACHE-POS-001` v1.0.0 | positive / `APPROVABLE` | `SR-P05-CACHE-BLUEPRINT-001` v1.0.0 | `sha256:2f3baf9c64931487f53fcfc6c3d4557e4f634cb776a0a4dd65918f2ffddb42b1` | `sha256:e52fbe61c01d25d91010a91ff120f3df741c2400516a90586320e02329e20262` |
| `GOLDEN-P05-CACHE-NEG-001` v1.0.0 | negative / `REJECT` | `SR-P05-CACHE-PLAN-NEG-001` v1.0.0 | `sha256:9d1bba041da78a78600a7645d40cb62aba8294c90e6c1c976e796b4e8490e808` | `sha256:1e304e40a62e41aa5acb368e667e69bc6dacb02b03dd7d664bffaa2a413e6fbf` |
| `GOLDEN-P06-CACHE-POS-001` v1.0.0 | positive / `READY` | `SR-P06-CACHE-MAP-POS-001` v1.0.0 | `sha256:8cdfd4dcc53decab54e1167c20625573fb00b5e511ab92eb141b5975b08634d4` | `sha256:5579e89a6542cab0d2d9e6e25767bd9070e486ea7d25bb5ec0e32177b6ee4292` |
| `GOLDEN-P07-CACHE-POS-001` v1.0.0 | positive / `READY` | `SR-P07-CACHE-POS-001` v1.0.0 | `sha256:fc20c9360a36707762a91d76d2ce9f9d3c167bc8bcb088d1f94d6e8397e084f1` | `sha256:6baffa267001e9f26478243593b03183e305727edd227089cd67c9d9845eb3e7` |
| `GOLDEN-P07-CACHE-NEG-001` v1.0.0 | negative / `REPLACEMENT_REQUIRED` | `SR-P07-CACHE-NEG-001` v1.0.0 | `sha256:3a8c665373a3aad141571d8aced682410d5c7d3a8747eac2f91f2f12122006c2` | `sha256:0d8b149bdbcff5c0d540cff0214d21b6fdd2516137b462dfdb293de7db3b14c3` |
| `GOLDEN-P08-CACHE-POS-001` v1.0.0 | positive / `ACCEPT` | `SR-P08-CACHE-POS-001` v1.0.0 | `sha256:e28976bdc1ad874d4fad0bc465a73eec899354b3edcdebaefc631167d4e36493` | `sha256:a63efd2c1dad0a0165a4ddf7354412529538ed32209a60bd19df7d81ae32f28e` |
| `GOLDEN-P08-CACHE-NEG-001` v1.0.0 | negative / `REJECT` | `SR-P08-CACHE-NEG-001` v1.0.0 | `sha256:a1094aefabd40a9396bda991679f36332adab024e33e667906fc3b2f8d75ef24` | `sha256:703cb5251121c64d09c575dfbc838eb77df4fffd0cb5c13d4d65ae776260c6d9` |
| `GOLDEN-P09-CACHE-POS-001` v1.0.0 | positive / `READY` | `SR-P09-CACHE-POS-001` v1.0.0 | `sha256:515ea95c840e9b8fb430ab744c3c9863fcfe5064c4c222afd32f50c9639710f4` | `sha256:75fb4de34312937534365727943e577f46647456313eebcb672173ddce76b3c7` |

Cada row registra fixture hash, hashes de fuentes, obligación positiva o
condición negativa exacta, razones legítimas de abstención, evidencia de
revisión y outcome. Ningún output de `DeterministicMockFactory` aparece como
`SEMANTICALLY_QUALIFIED_POSITIVE`.

## 3. Canonical document-shaped pack

| Artefacto sintético | Rol / contenido | SHA-256 |
|---|---|---|
| `official_assignment.docx` | consigna oficial, outcome, formato, tiempo y límite inferencial | `ac8ade8c3dc529d06d439dcbc3af0b866c6e1deaa3ebaa0552963f7a93d54025` |
| `official_rubric.docx` | rúbrica oficial, criterio único, `grading_weight=1.0`, observables y niveles 0–3 | `71c8101a6d1c50acb81c2f04e8479540e9c90a35974819f46af497a81f5361f7` |
| `submission_sufficient.docx` | condición, riesgo de resultado obsoleto, nueva consulta, recálculo y traza textual | `d4983ba075c625f4c58858db8ec02a603f57b71145517e7160afd29df32be49a` |
| `submission_insufficient.docx` | regla de cuándo invalidar, sin sustento causal ni resultado de segunda consulta | `67d3ebaff85dfa269c65a8df23d3cc0e18631c6b2a51613c82fadeb2098f8204` |

Los cuatro DOCX son deterministas, inertes y totalmente sintéticos. Se
derivan mediante `SafeParserService` / `stage2-docx-structural`, con preflight
OOXML, detección de tipo y `stage2-parser/2.0.0`; el bundle usa la misma frontera
parser→EvidenceUnit→EvidenceBundle del workflow. La ruta completa validada es:

`documentos → parser productivo → EvidenceUnit → ActivitySpec/RubricSpec → P04/P05 → EvidenceMapPatch → planner → P07/P08 → assembly productivo → P09`.

El harness no construye manualmente el `EvidenceBundle` final. Invoca
`Stage1Service._parse_bytes`, que aplica la normalización productiva de IDs y
provenance, y luego ejecuta la rama de resume de
`Stage1Service._run_submission_pipeline` hasta capturar el request P06 exacto
que contiene el bundle creado por el workflow. La ejecución se detiene en esa
frontera antes del gateway; no construye adapter de proveedor ni hace red. El
hash congelado de `web/workflows.py` impide que esta derivación diverja sin que
el rehearsal falle.

La evidencia suficiente autoriza `JUSTIFY_DECISION` y no autoriza inferir
lenguaje, rendimiento, concurrencia o causa externa. La insuficiente prueba
que una abstención semánticamente correcta es PASS del instrumento; una
abstención sin Diagnostic completo es un fallo separado de adherence.
LibreOffice headless renderizó los cuatro documentos en una página cada uno;
la revisión `DOCX-QA-CACHE-001` v1.0.0 comprobó tablas, jerarquía, clipping,
headers/footers, clasificación visible y ausencia de páginas vacías.

## 4. Provenance y clasificador post-ejecución

El modelo causal nuevo vive en
`src/comprehension_verification/qualification_semantics.py` y conserva cinco
ejes independientes:

1. outcome operacional;
2. validez del oracle;
3. interpretación semántica (`CORRECT`, `DEFENDIBLE`, `INCORRECT`,
   `INDETERMINATE`);
4. adherence contractual;
5. atribución y confianza causal.

Las ramas probadas son: positive válido incumplido; abstención defendible con
adherence incorrecta; rechazo correcto; oracle inválido; causa indeterminada;
y fallo técnico. La regla anterior «todo código no técnico → model-owned» se
elimina para Terra: un reporte sin provenance versionada queda
`ORACLE_VALIDITY_UNESTABLISHED`, aunque su outcome operacional siga siendo
FAIL. Esto actualiza interpretación futura, no el receipt ya persistido.

El sweep ejecutable futuro consume directamente los nueve requests goldens
versionados: P04/P05/P06/P07/P08/P09 positives y P05/P07/P08 negatives. Cada
fila del receipt lleva clase, semantic review/version/hash, fixture/golden y
source hashes, outcome operacional, interpretación semántica, adherence,
atribución y confianza. Las dos cadenas integradas restantes se rotulan
`STRUCTURAL_ORCHESTRATION_CHECKPOINT_ONLY` y se excluyen de conclusiones de
calidad. Así, un `REJECT` correcto o una abstención correcta son PASS, y una
abstención defendible con Diagnostic inválido conserva `DEFENDIBLE` junto con
`contractual_adherence=FAIL`.

## 5. Freeze verificable y rehearsal offline

`frozen_product_boundary.json` liga al HEAD inicial `9dbce36…` los hashes de
modelos canónicos, prompts, registry, adapter, rutas, validators, planner y
assembler. También fija los seis prompt hashes y los thresholds P08. El
rehearsal falla si cualquiera cambia.

Reporte reproducible:
`reports/openai/harness_semantic_remediation_offline.json`, SHA-256
`b2d3bc075b4599729d1ef82fc3aaf5207f83bb92bafffc3bd4ae15acc2bd579b`.

| Control offline | Resultado |
|---|---|
| Product boundary frozen | PASS |
| DOCX parser / cuatro artefactos | PASS |
| P05 `1.0 → 1.0`, diez categorías, `APPROVABLE` | PASS |
| P07 positive / negative | `READY` / `REPLACEMENT_REQUIRED` PASS |
| P08 positive / negative | `ACCEPT` / `REJECT` PASS |
| P09 production assembly / guide | PASS |
| Provenance | 13 filas explícitas PASS |
| Revisión adversarial | 8/8 preguntas PASS |
| QA visual | 4/4 documentos PASS |
| Clasificador | 6/6 ramas PASS |
| Sweep/receipt remediado | 9/9 semantic checkpoints PASS; 2 cadenas structural-only PASS |
| Calls simuladas / provider real / billable / Terra | `21 / 0 / 0 / 0` |

El rehearsal conserva el cap configurado de 24 requests pero espera
21 invocaciones (nueve en el sweep y doce en dos cadenas); su charge
conservador es USD `4.4342675`, con máximo USD `0.26935`, dentro de los caps
congelados USD `5.10` / `0.27`. No se ejecutó ese perfil contra red: el reporte
de esta fase usa exclusivamente el adapter offline de goldens revisados y el
mock structural.

La authorization boundary futura sube a
`openai-stage2-convergence-authorization/1.4.0`: además del producto congelado,
liga por hash los módulos del clasificador/harness, los fixtures v2/v3 y los
cuatro DOCX. Esta fase no crea, consume ni reutiliza una autorización.

## 6. Receipts históricos preservados y autoridad

El receipt Terra/MEDIUM permanece bitwise idéntico:
`reports/openai/stage2_terra_medium_qualification_9185dba_20260813_final_01.json`,
SHA-256 `af56425a8d00fc1bbcee06c6e088f590cff68c9938c2b23190c1b5a72fdd776c`.
También se preservan los receipts HIGH, XHIGH y MAX con sus hashes históricos.
No se reescribe `TERRA_MEDIUM_QUALIFICATION_FAILED`; se corrige únicamente la
lectura causal en este handoff y en el clasificador del instrumento.

No existe autoridad para Terra/HIGH, otra qualification real, retry, build,
deploy, `terraform apply`, migración remota ni cloud E2E. El PR permanece
draft. El único paso autorizado al cerrar esta fase es revisión independiente
del harness.

## 7. Regresión offline de cierre

Todos los comandos se ejecutaron con `CVA_MODEL_MODE=mock`, P10 deshabilitado
y `CVA_OPENAI_API_KEY` / `OPENAI_API_KEY` eliminadas del entorno.

| Superficie | Resultado local |
|---|---|
| Harness semántico + eval harness | 58/58 PASS |
| Backend completo | 654 PASS, 17 skipped sólo por matriz PostgreSQL separada, coverage 81 % |
| PostgreSQL 16 y 17 efímeros | prepare/migrations PASS; recovery/readiness 206/206; E2E 1/1 y sensitive 8/8, matriz repetida; contenedores eliminados |
| Contratos / schema / OpenAPI / client | contratos 1.2 con 141 definiciones y 8 fixtures PASS; regeneración idempotente, sin diff |
| Frontend | `npm ci`, typecheck, 36/36 unit tests, build y audit 0 vulnerabilidades PASS |
| Browser / Playwright | smoke login→activities sin logs; Stage 1 1/1 y Stage 2 2/2 PASS |
| Infra / deploy artifacts | `terraform fmt`, init sin backend y validate PASS; deploy artifacts 11/11; YAML y shell syntax PASS |
| Seguridad | secret scan PASS sobre 329 archivos versionables; cero secretos resueltos |
| DOCX | build determinista y render visual 4/4 PASS, una página por artefacto |
| Rehearsal offline | 13/13 checks; 9/9 checkpoints semánticos y 2/2 cadenas structural-only PASS |

El guardrail adversarial adicional demuestra que un output P07 distinto del
golden, aunque sea estructuralmente válido, queda `INDETERMINATE` y exige
revisión semántica independiente; no se convierte automáticamente en PASS ni
en fallo model-owned.

Controles de cierre locales: provider attempts `0`; billable requests `0`;
network calls to OpenAI `0`; Terra/Luna/Sol executions `0/0/0`; prompts,
validators, thresholds, planner, assembler y product workflow cambiados
`0/0/0/0/0/0`; deploys `0`.

## Anexo 1 — ejecución Terra/MEDIUM histórica (inmutable)

## A. Estado GitHub y linaje Terra

| Elemento | Valor |
|---|---|
| Repositorio / PR | `WilJms/PruebasPersonalizadas`, PR `#3` (open, draft, mergeable antes de publicar este handoff) |
| Branch | `codex/openai-real-provider-gate` |
| Baseline Stage 2 | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Candidato / evidencia Luna/MAX preservados | `62d73ae5f183c0da4fb87a9ba673905c64225880` / `b4325b617529739f163471e43af54e125c754b91` |
| Candidato Terra/MEDIUM congelado y ejecutado | `9185dbaccc36cd2150f723525b13e00bf86c3842` |
| HEAD documental posterior | commit Git que contiene este handoff y el receipt; el SHA exacto se publica en el PR y en la entrega final para evitar autorreferencia hash imposible |
| CI candidato push / PR | runs `31716336517` / `31716341310`, 7/7 jobs PASS en ambos |
| Ruta / modelo / reasoning calificado | `TERRA_MEDIUM_V1` / `gpt-5.6-terra` / `MEDIUM` en P04–P09 |
| Rehearsal / reporte | `stage2-product-rehearsal/1.8.0` / `stage2-convergence-report/1.8.0` |
| SDK / API / adapter | OpenAI SDK `2.53.0`; Responses API; `OpenAIResponsesAdapter` |

El estado conocido se reancló directamente contra GitHub antes de editar:
Luna/MAX seguía en `LUNA_MAX_QUALIFICATION_FAILED`, la familia Luna en
`LUNA_FAMILY_QUALIFICATION_EXHAUSTED` y la convergencia en
`CONVERGENCE_INCOMPLETE`. El remoto no había avanzado después de `b4325b6…`.

## B. Delta mecánico Terra/MEDIUM

El commit candidato añade una identidad canónica nueva, `TERRA_MEDIUM_V1`, sin
reutilizar ni sobrescribir rutas Luna históricas. Para mantener coherencia de
perfil, todas las rutas del perfil usan exclusivamente `gpt-5.6-terra`; los
esfuerzos congelados quedan P01/P02 `MEDIUM`, P03 `HIGH`, P04–P09 `MEDIUM` y
P11 `LOW`. P10 continúa sin ruta.

Archivos del candidato:

- `Makefile`;
- `scripts/run_openai_evals.py`;
- `src/comprehension_verification/model_gateway/__init__.py`;
- `src/comprehension_verification/model_gateway/openai_adapter.py`;
- `src/comprehension_verification/model_gateway/openai_pricing.py`;
- `src/comprehension_verification/model_gateway/openai_routes.py`;
- `src/comprehension_verification/rehearsal.py`;
- `tests/test_openai_adapter.py`;
- `tests/test_openai_eval_harness.py`;
- `tests/test_openai_pricing.py`.

El adapter sólo amplía su guard fail-closed para aceptar los dos IDs exactos
aprobados, Luna y Terra. El payload permanece congelado: Structured Outputs,
`store=false`, `background=false`, `tools=[]`, paralelismo deshabilitado,
truncation disabled, service tier default, sin temperature, timeout idéntico y
retry SDK cero. No se cambió el SDK.

No hubo cambios de prompts, prompt registry, fixtures, goldens P05, schemas
funcionales, contratos, OpenAPI, cliente generado, validators, allowlists,
thresholds, planner, assembler, grounding, P11, fallback ni criterios
PASS/FAIL. El delta ejecutable registrado declara `prompt_registry_changes=[]`,
`fixture_changes=[]`, `schema_changes=[]`, `validator_changes=[]`,
`planner_changes=[]` y `assembler_changes=[]`.

## C. API oficial, regresión y rehearsal pre-red

La documentación oficial vigente de OpenAI confirmó antes de implementar que
`gpt-5.6-terra`, `reasoning.effort=medium`, Responses API y Structured Outputs
seguían soportados por la ruta congelada. No se detectó incompatibilidad de SDK
o parámetros y no se actualizó ninguna dependencia.

| Superficie | Resultado antes de red |
|---|---|
| Tests focales profile/routing/adapter/harness | 95 PASS |
| Backend completo con cobertura | 642 PASS, 17 skips PostgreSQL cubiertos aparte, 81% coverage |
| PostgreSQL 17 local efímero | prepare/migrations PASS; recovery/readiness 206 PASS; E2E 1 PASS y sensitive 8 PASS, matriz repetida; contenedor eliminado |
| Contratos/schema/OpenAPI/client | PASS e idempotentes, sin diff; modelo `3f1a4210…`, schema `318f1dce…` |
| Frontend | typecheck, 36/36 tests, build y audit con 0 vulnerabilidades |
| Terraform/static/deploy | fmt, init backend=false y validate PASS; deploy artifacts 11/11 PASS; YAML y shell válidos |
| Secret scan | PASS sobre 316 archivos versionables |
| Rehearsal Terra/MEDIUM | PASS, 24 intentos simulados, 0 red; matriz exacta y ambos goldens PASS |
| CI candidato push / PR | runs `31716336517` / `31716341310`: 7/7 jobs PASS cada uno |

El rehearsal fijó la secuencia exacta: sweep P04–P09; golden P05 positivo y
negativo offline; cadena base 1; cadena base 2; variante choice. Los goldens
consumieron cero requests. El peor caso conservador fue USD `5.0054075` total
y USD `0.25831` por llamada, dentro de caps fail-closed de `24` requests, USD
`5.10` total y USD `0.27` por llamada.

## D. Freeze y autorización exactly-once

| Identidad | Valor |
|---|---|
| Execution ID | `stage2-terra-medium-9185dba-20260813-01` |
| Authorization hash | `sha256:9c8031b2a9407ab20b38f645073d72fd9eb0942fa823fef34999ba5351b60fc6` |
| Authorization boundary | `sha256:6c3aa08aea04fbc2f12e32899c7426282e4e8eb846019062512ffcbea9891926` |
| Executable boundary | `sha256:d0fcb2889827ed0fd1c6ca57bd7664aa587bf82152db4b9168da3fee35f2800b` |
| Harness | `sha256:fa90edcfeec075081387cc1b63ec55ce4d438e26faba6894b729eefdd744ac66` |
| Rehearsal module | `sha256:b4cd168904e150fe38263e39eac8a39de53a45500511548ba453134e4fb305b5` |
| Manifest | `sha256:d5991a48253eead5a4ba87653323177144fb67a4ae455ec9e2595a3e153ffb11` |
| P05 golden fixture | `sha256:9f6849dfc8ff2aceee569d1c44122e589ace1c519fc171c50f3fdf4a05e9e9b0` |
| Planner / assembler | `stage2-planner/2.0.0` / `stage1-assembler/2.0.0` |

Prompt hashes congelados: P04 `f8c12331…`, P05 `4b38cf14…`, P06
`01bf8fab…`, P07 `db0f6d91…`, P08 `f63230dd…` y P09 `a7607fb6…`.
Relationship validators: P04 `2.0.0`, P05 `2.2.0`, P06 `2.3.0`, P07/P08
`2.1.0`, P09 `2.0.0`; application validators: P05 `2.2.0`, P06 `2.1.0` y
P07/P08/P09 `2.0.0`.

Antes de red se verificaron candidate/remote SHA exactos, ambos CI verdes, PR
draft/open/mergeable, secreto numérico fijado y habilitado sin revelar su
valor, ledger íntegro, IDs inéditos, reporte ausente y caps exactos. La reserva
se creó antes de resolver el secreto y quedó consumida exactamente una vez.

## E. Única matriz real Terra/MEDIUM

Inicio/fin UTC: `2026-08-13T15:44:36.508812Z` /
`2026-08-13T15:49:59.166328Z`.

| Fila | Attempts | Resultado | Evidencia content-free |
|---|---:|---|---|
| Sweep independiente P04–P09 | 6 | **FAIL** | P04/P06/P09 PASS. P05 `P05_NOT_APPROVABLE` por `SOURCE_FIDELITY`; P07 `DIAGNOSTIC_INCOMPLETE`; P08 `P08_DECISION_REJECT`, con groundedness, anchor sufficiency, criterion relevance y answerability bajo los thresholds congelados. |
| Golden-positive P05 offline | 0 | **PASS** | `APPROVABLE`, `READY`, `APPROVE`; validator PASS. |
| Golden-negative P05 offline | 0 | **PASS** | `REJECT` exacto; `PLAN_FEASIBILITY=FAIL/critical`; validator PASS. |
| Cadena base 1 P04→P09 | 6 | **PASS** | P04–P09 y planner/assembly PASS. |
| Cadena base 2 P04→P09 | 3 | **FAIL** | P04/P05/P06 completaron; planner fail-closed con `ASSESSMENT_PLAN_INFEASIBLE` / `EVIDENCE_MAPPING_UNCERTAIN`, sin oportunidades elegibles. |
| Variante choice P04→P09 | 6 | **PASS** | P04–P09 y planner/assembly PASS. |

No hubo error técnico del provider, timeout ni receipt sin precio. El harness
histórico trató esos fallos como model-owned, pero esta remediación determina
que esa atribución conjunta no es una medición semántica limpia: P05 tenía una
inconsistencia de fuente, P07 autorizaba evidencia insuficiente y P08 usaba un
candidate mock no calificado. Sólo `DIAGNOSTIC_INCOMPLETE` queda demostrado
como infracción contractual model-owned independiente de la decisión semántica.

## F. Requests, tokens, costo y controles Terra

| Control | Resultado |
|---|---|
| Provider attempts / cap | `21 / 24` |
| Input tokens | `96,559` |
| Cached input / cache-write input | `40,684 / 55,812` |
| Output tokens | `26,639` |
| Reasoning tokens | `8,567`, subconjunto del output |
| Costo actual / cap | USD `0.4674608 / 5.10` |
| Charge conservador observado | USD `3.4597928` |
| Máximo actual / cap por llamada | USD `0.034957 / 0.27` |
| Máximo charge conservador por llamada | USD `0.203811` |
| Attempts sin precio / errores técnicos | `0 / 0` |
| P10 / P11 / fallback | `0 / 0 / 0` |
| Retry gateway / SDK / semántico | `0 / 0 / 0` |
| Normalizaciones / prompt / fixture / validator changes | `0 / 0 / 0 / 0` |
| Tools / store | `false / false` |
| Boundary entre cadenas | `unchanged_boundary_across_chains=true` |

## G. Receipt, veredicto y autoridad siguiente

Receipt crudo e inmutable:
`reports/openai/stage2_terra_medium_qualification_9185dba_20260813_final_01.json`,
SHA-256 `af56425a8d00fc1bbcee06c6e088f590cff68c9938c2b23190c1b5a72fdd776c`.

El ledger conserva exactamente la misma frontera y report hash, con estado
terminal `FAILED` y código `TERRA_MEDIUM_QUALIFICATION_FAILED`. No se reescribió
ni consolidó el receipt. El PR debe permanecer draft; no se autoriza deploy ni
otra matriz. La autoridad histórica registrada fue
`INDEPENDENT_REVIEW_BEFORE_ANY_TERRA_HIGH_AUTHORITY`; la interpretación actual
la estrecha a `INDEPENDENT_HARNESS_REVIEW_BEFORE_ANY_TERRA_HIGH_AUTHORITY`.

`TERRA_MEDIUM_QUALIFICATION_FAILED`<br>
`CONVERGENCE_INCOMPLETE`

## Anexo histórico Luna/MAX preservado

Nota metodológica posterior: las etiquetas causales model-owned de este anexo
se preservan como historia de sus instrumentos originales. Esta fase no las
recalifica retroactivamente ni las usa como evidencia semántica limpia sin
provenance versionada por checkpoint.

Fecha de corte: 2026-08-12 (America/Santiago).

Veredicto: **`LUNA_MAX_QUALIFICATION_FAILED`**.<br>
Familia: **`LUNA_FAMILY_QUALIFICATION_EXHAUSTED`**.<br>
Convergencia: **`CONVERGENCE_INCOMPLETE`**.

La única matriz Luna/MAX autorizada no superó la qualification congelada. La
experimentación HIGH/XHIGH/MAX de Luna para esta frontera queda agotada. Esto
no afirma incapacidad general de Luna y no autoriza otra configuración, otro
modelo, Fase 3/Fase 4 Ultra, build/deploy, `terraform apply`, migración remota
ni E2E cloud.

## 1. Linaje y frontera ejecutada

| Elemento | Valor |
|---|---|
| Repositorio / PR | `WilJms/PruebasPersonalizadas`, PR `#3` (draft) |
| Branch | `codex/openai-real-provider-gate` |
| Baseline Stage 2 | `80dd57dbf38d56929c307eca956833c31e53bf33` |
| Candidato / evidencia HIGH | `93da59414fb49bd4df5c21af193a0226b4bc5fdb` / `6c69e0359a1a0a327c49a6ce70d3959c384be779` |
| Candidato / evidencia XHIGH | `d41c2b3e6584ae2f202c3fceda0ec7d1a585242e` / `23a16668c3cdd325919acfb5c871db30aefa0dc2` |
| Candidato MAX congelado y ejecutado | `62d73ae5f183c0da4fb87a9ba673905c64225880` |
| HEAD documental posterior | commit Git que contiene este handoff y el reporte consolidado; el SHA exacto se publica en el PR y en la entrega final para evitar una autorreferencia hash imposible |
| Rehearsal / reporte de ejecución | `stage2-product-rehearsal/1.7.0` / `stage2-convergence-report/1.7.0` |
| Prompt pack | `1.1.14`, sin cambio semántico |
| Ruta / modelo | `LUNA_MAX_V1` / sólo `gpt-5.6-luna` |
| Reasoning calificado | `MAX` en P04–P09 |
| Frontera ejecutable | `sha256:70f6796c222955705caee704e164a4c6a7030eaacc78947a381f9b1e20ca82cf` |
| Frontera de autorización | `sha256:62aad8356cb235e5ab4c22120a4413cdb1ab473c3c15bac21798f1412c63ee81` |
| Authorization hash | `sha256:77543f242723b44bff268e3c3cff3a2c786895eb8df264798ab911a114c8e990` |
| Harness / módulo rehearsal | `sha256:a690aff9025973eaa4257d03a8356d34924116667e38b84cc30bbbfc414f9cff` / `sha256:9f7c626a61409ed1acf2ee51c0bc1aafe507f9c634ade9b13669fb01b89d453e` |
| Manifest | `sha256:d5991a48253eead5a4ba87653323177144fb67a4ae455ec9e2595a3e153ffb11` |
| Execution / authorization ID | `stage2-max-62d73ae-20260812-final-01` / `authorization-stage2-max-62d73ae-20260812-final-01` |

La autorización nueva se reservó antes del primer transporte y se consumió
exactamente una vez. El candidato ejecutado permanece ligado a `62d73ae…`; el
commit documental posterior no integra ni altera esa frontera.

Los reportes fuente HIGH/XHIGH son, respectivamente,
`reports/openai/stage2_convergence_93da594_20260812_final_01.json`
(`sha256:30a422dc79a2098ff6e7066a39cb2517e959d2d1d8a169f287c68101c2dc519e`)
y `reports/openai/stage2_xhigh_qualification_d41c2b3_20260812_final_01.json`
(`sha256:1b62c99b19781d923df9eda4082b8e73de64de2c4a4253b65d555e7d70e8db1a`).

## 2. Delta exacto XHIGH → MAX

Se añadió `ReasoningEffort.MAX` a la fuente canónica y, mecánicamente, al
schema generado, OpenAPI y cliente TypeScript. Se creó la identidad
`LUNA_MAX_V1`; no se reutilizó ninguna ruta previa.

| Etapa | `LUNA_XHIGH_V1` | `LUNA_MAX_V1` | Uso en matriz |
|---|---|---|---|
| P01 / P02 | `MEDIUM` | `MEDIUM` | fuera de matriz |
| P03 | `HIGH` | `HIGH` | checkpoint idéntico |
| P04–P09 | `XHIGH` | `MAX` | cambio material único |
| P10 | sin ruta | sin ruta | 0 llamadas |
| P11 | `LOW` | `LOW` | 0 llamadas |

Permanecieron iguales: provider/model, system/developer/task prompts, hashes y
versiones P04–P09, fixtures product-shaped, ambos golden P05, policies,
inputs académicos sintéticos, schemas funcionales salvo el enum mecánico,
relationship/application validators, thresholds, planner
`stage2-planner/2.0.0`, assembler `stage1-assembler/2.0.0`, SDK OpenAI `2.53.0`,
adapter Responses, zero-tools/store y retries en cero. El payload XHIGH/MAX
difiere materialmente sólo en `reasoning.effort`. No hubo tuning ni
remediación de producto.

## 3. Regresión, budget y CI antes de red

| Superficie | Resultado |
|---|---|
| Focal MAX / adapter / harness | 80/80 PASS |
| Backend completo | 647 tests: 630 PASS, 17 skips PostgreSQL cubiertos aparte, 0 fallas/errores |
| PostgreSQL 17 | prepare 31 tablas; E2E 1/1; sensitive 8/8; migration/recovery/readiness 206/206 PASS; contenedor eliminado |
| Contratos | PASS: 53 roots, 141 `$defs`, 277 refs, 8 fixtures; regeneración idempotente |
| Modelo / schema | `3f1a42102b10a558…` / `318f1dceee27f919…` |
| OpenAPI / cliente | `83cd3dbcc728c613…` / `2ee42d9587897ddc…` |
| Rehearsal MAX offline | PASS; 24/24 simulados, 0 red; ambos golden PASS con 0 requests |
| Budget MAX fail-closed | USD `0.500519` total y `0.02583025` máximo por llamada |
| Frontend | instalación limpia, typecheck, 36/36 tests, build y audit 0 vulnerabilidades |
| Terraform/static / deploy tests | fmt/init backend=false/validate PASS; 11/11 PASS |
| Secret scan | PASS sobre 313 archivos versionables |
| CI push / PR del candidato | runs `31661764201` y `31661765833`: 7/7 jobs PASS cada uno |

Los caps sellados —24 requests, USD 0.75 total, USD 0.10 por llamada— fueron
suficientes. También se probó fail-closed con caps incorrectos: bloqueo
`OPENAI_MAX_QUALIFICATION_EXACT_CAPS_REQUIRED`, 0 llamadas. No hubo Cloud
Build, deploy, `terraform apply`, migración remota ni E2E cloud.

## 4. Única matriz real Luna/MAX

Inicio/fin UTC: `2026-08-13T02:51:40.389894Z` /
`2026-08-13T03:04:29.893520Z`.

| Observación | Attempts | Resultado | Señal content-free |
|---|---:|---|---|
| Sweep independiente P04–P09 | 6 | **FAIL** | P05/P06/P09 PASS. P04 y P08 `MODEL_PROVIDER_ERROR`. P07 `MODEL_OUTPUT_VALIDATION_FAILED` + `OUTPUT_PYDANTIC_VALIDATION_FAILED`, `value_error` en `/candidate`. |
| Golden-positive P05 offline | 0 | **PASS** | `APPROVABLE`, `READY`, `APPROVE`, validator PASS. |
| Golden-negative P05 offline | 0 | **PASS** | `REJECT` exacto; sólo `PLAN_FEASIBILITY=FAIL/critical`, validator PASS. |
| Cadena base 1 P04→P09 | 1 | **FAIL** | P04 `MODEL_PROVIDER_ERROR`; stop fail-closed. |
| Cadena base 2 P04→P09 | 1 | **FAIL** | P04 `MODEL_PROVIDER_ERROR`; stop fail-closed. |
| Variante choice P04→P09 | 1 | **FAIL** | P04 `MODEL_PROVIDER_ERROR`; stop fail-closed. |

No se sustituyó ningún output, no se cambió la frontera y no hubo retry ni
segunda matriz. El P07 positivo del sweep produjo una violación Pydantic
model-owned. Según la regla terminal explícita, esa sola observación basta para
`LUNA_MAX_QUALIFICATION_FAILED`, aunque coexistan cinco intentos con error
técnico del proveedor.

## 5. Corrección post-ejecución del clasificador

El recibo crudo clasificó el conjunto mixto como
`MAX_QUALIFICATION_INCONCLUSIVE` porque el clasificador daba precedencia a
`MODEL_PROVIDER_ERROR`. Esa precedencia contradice la regla humana: cualquier
fallo positivo model-owned contractual/Pydantic es terminal.

Se preservó sin modificar el recibo crudo y su hash del ledger. El reporte
consolidado aplica la regla dominante y registra:

- clasificación causal:
  `MODEL_OWNED_QUALIFICATION_FAILURE_WITH_TECHNICAL_FAILURES`;
- veredicto: `LUNA_MAX_QUALIFICATION_FAILED`;
- familia: `LUNA_FAMILY_QUALIFICATION_EXHAUSTED`;
- autoridad siguiente:
  `HUMAN_REVIEW_OF_LUNA_EXHAUSTION_NO_AUTOMATIC_MODEL_CHANGE`.

El clasificador post-ejecución quedó corregido y cubierto por un test del caso
mixto. Esto no modifica prompts, schemas funcionales, validators, fixtures,
outputs, candidato ejecutado ni ledger, y no genera requests.

## 6. Requests, tokens, costo y controles MAX

| Control | Resultado |
|---|---|
| Provider attempts / cap | `9 / 24` |
| Input tokens | `142,256` |
| Cached input / cache-write input | `0 / 16,897` |
| Output tokens | `39,893` |
| Reasoning tokens | `35,493` — subconjunto de output tokens |
| Costo actual / cap | USD `0.05209825 / 0.75` |
| Charge conservador | USD `0.1843634` |
| Máximo actual / cap por llamada | USD `0.01493045 / 0.10` |
| Máximo charge conservador por llamada | USD `0.02583025` |
| Attempts sin precio | `5` — los errores de proveedor |
| Modelo / reasoning | sólo `gpt-5.6-luna` / sólo `MAX` en P04–P09 |
| Boundary | `unchanged_boundary_across_chains=true` |
| P10 / P11 / fallback | `0 / 0 / 0` |
| Retry gateway / SDK / semántico | `0 / 0 / 0` |
| Normalización / prompt / fixture / validator / threshold changes | `0 / 0 / 0 / 0 / 0` |
| Tools / store | `false / false` |
| P08 positivos | ninguno produjo decisión: sweep falló en transporte; cadenas no llegaron a P08 |

## 7. Comparación descriptiva HIGH / XHIGH / MAX

| Configuración | Runs completos | Fallos principales | Requests | Tokens input / output / reasoning | Costo actual / conservador | P08 alcanzados | Veredicto |
|---|---|---|---:|---|---|---|---|
| Luna/HIGH `93da594…` | ninguno | sweep P07/P08; base 1 P08; base 2 P05; choice P06 | 16 | no registrados / no registrados / no registrados | USD `0.07123828` / `0.27835468` | sweep/base 1 `REJECT` | `LUNA_HIGH_QUALIFICATION_FAILED` |
| Luna/XHIGH `d41c2b3…` | base 1 y base 2 | sweep P07 `UNAUTHORIZED_EVIDENCE`; choice P05 ID no allowlisted | 20 | `95,245 / 133,148 / 110,294` | USD `0.17479203` / `0.32701443` | sweep/base 1/base 2 `ACCEPT` | `LUNA_XHIGH_QUALIFICATION_FAILED` |
| Luna/MAX `62d73ae…` | ninguno | sweep P07 Pydantic model-owned; P04/P08 provider; las tres cadenas P04 provider | 9 | `142,256 / 39,893 / 35,493` | USD `0.05209825` / `0.1843634` | sin decisión | `LUNA_MAX_QUALIFICATION_FAILED` |

Las tres configuraciones tuvieron fallback, retries, P10 y P11 en cero. Los
contadores de tokens HIGH no existen en su reporte fuente y no se
reconstruyeron. La comparación describe una sola matriz por configuración: no
afirma significancia estadística ni superioridad general.

## 8. Evidencia y autoridad siguiente

Recibo de ejecución inmutable:
`reports/openai/stage2_max_qualification_62d73ae_20260812_final_01.json`,
SHA-256 `532ba5e19537c039f9746c177ae3ed17cf9fbc3d6fdb9bf34c5f07f32a6eda0e`.
El ledger conserva `FAILED`, ese mismo report hash y su código histórico
`MAX_QUALIFICATION_INCONCLUSIVE`; no se reescribió historia durable.

Reporte final consolidado:
`reports/openai/stage2_max_qualification_62d73ae_20260812_consolidated_final_01.json`,
SHA-256 `74fc1323da3925a9805b4c957bbd597b342909f4b77855fcce706db6afbb17fd`.

El PR permanece draft. La autorización está consumida. No corresponde retry,
segunda matriz, tuning, cambio de validator/threshold/fixture, otra
configuración Luna, Terra, Sol, build ni deploy. Sólo queda permitida una
revisión humana de esta evidencia y cualquier acción posterior exige autoridad
explícita nueva.

`LUNA_MAX_QUALIFICATION_FAILED`
`LUNA_FAMILY_QUALIFICATION_EXHAUSTED`
`CONVERGENCE_INCOMPLETE`
