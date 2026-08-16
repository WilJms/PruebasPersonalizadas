# Auditoría de Fase 7 — P09 post-aprobación y enrichment-only

**Fecha:** 2026-08-16
**Baseline:** `a2bef1af811d63720213ef784dc14088d9a414df`
**Autoridad:** ADR-037, D-080, `pipeline-authority/1.1.0`
**Modo:** exclusivamente sintético, offline/mock, P10 disabled y cero
autorización o llamada billable

## 1. Resultado

El pipeline funcional objetivo queda cerrado:

```text
ACTIVITY
P01 -> P02 -> P03 -> P04 -> deterministic preflight -> teacher approval

SUBMISSION
P06 -> deterministic planner -> P07 -> deterministic validation
-> exactly N -> ASSEMBLE / Assessment NEEDS_REVIEW
-> teacher edit / regenerate / reject / approve
-> durable GUIDE_BUILD -> P09 enrichment
-> deterministic materialization / validation -> EvaluationGuide READY
```

P05 y P08 permanecen históricos/no callables; P10 permanece disabled. P09 no
es reviewer, judge, gate ni autoridad sobre la aprobación o las preguntas.

## 2. Before / after

| Frontera | Antes, Fase 6 | Después, Fase 7 |
|---|---|---|
| ASSEMBLE | exactamente N -> P09 -> workflow docente | exactamente N -> `Assessment.NEEDS_REVIEW`, P09=0 |
| Acción docente pre-aprobación | guía ya podía existir | edit/regenerate/reject mantienen P09=0 |
| Aprobación | posterior a una guía ya creada | se persiste primero y habilita un `GUIDE_BUILD` durable |
| P09 input/output | request canónica -> `EvaluationGuide` con campos repetidos | `GuideAliasEnvelope` -> `GuideModelDraft` transitorio -> materializador |
| P09 autoridad | guía completa recreada antes de decisión humana | enrichment-only de una versión ya aceptada |
| Fallo P09 | podía impedir llegar al workflow docente | Assessment sigue aprobado; Guide no queda READY |
| Guide current | asociación general por assessment/submission | binding exacto por tenant/version/ETag/approval/question set/boundary |

## 3. Happens-before, job e idempotencia

La transacción de aprobación actualiza/persiste el `Assessment.APPROVED` y su
audit event antes de crear el descriptor `GUIDE_BUILD`. El descriptor contiene
únicamente referencias/hash-bound metadata y su `approval_event_id` debe
resolver exactamente. La API puede despachar después del commit y no espera el
resultado P09.

El binding incluye tenant, submission, assessment ID, versión, ETag, hashes de
assessment y preguntas, event/snapshot de aprobación, actor/fecha, policy y
materializer boundary. `guide_id`, logical job ID y stage key se derivan de ese
binding. Repetir approval no crea otro trabajo; reconciliation repone un job
perdido después del commit y un retry técnico puede cambiar de job row sin
cambiar logical ID ni duplicar el StageRun/P09.

## 4. Reparto de autoridad

| Clasificación | Propietario | Campos/decisiones |
|---|---|---|
| `P07_SEMANTIC_SEED` | P07 | purpose, observables core, alternativas y misconceptions base, incertidumbres de pregunta |
| `P09_ENRICHMENT` | P09 | acceptance conditions, observables adicionales N*, adiciones de alternativas/misconceptions, levels 0–3, `cannot_infer`, incertidumbres de guía |
| `SERVER_OWNED` | backend | identidad, versiones/hashes, question mapping, support membership, IDs, locators, materialización, validación, estados, current/export |
| `TEACHER_OWNED` | docente | aceptar, editar, regenerar, rechazar y aprobar preguntas/Assessment |
| `HISTORICAL_COMPATIBILITY` | lectura | P05/P08 y guías P09 pre-Fase 7; no autorizan una decisión actual |

El materializador copia literalmente purpose y observables core P07 como
prefijo. P09 no tiene un campo con el que cambiar texto, anchor, locator,
operation, format, difficulty, time, canonical IDs o support evidence.

## 5. Frontera P09

- Prompt pack/P09: `1.1.17` / `1.1.7`.
- Provider root: `GuideModelDraft`.
- Schema provider estricto: 3.131 bytes frente a 4.461 bytes del root
  `EvaluationGuide` en el baseline de Fase 6 (−1.330; −29,81%),
  `sha256:21b2020c83e941d260273b4ffc95511e057522093395cf85e621e5056ce04a3f`.
- Envelope: `p09-alias-envelope/1.0.0`; schema
  `sha256:3b0050e44d98575b9c54b9612312f431085560a76943754c0a73d4325ebff2e9`;
  boundary
  `sha256:a3979376b3394fff812524bceb836272420d7b16c3e4fec2d5ca0a585fce0b82`.
- Materializador: `p09-guide-materializer/1.0.0`; source
  `sha256:0d4af856781cb9df11e7299a2eeef04efae4fc5e44e8d0f7c46c7614e882a563`;
  boundary
  `sha256:0fe0051d348d418707c2698f0e632de18ce71fb3e5572792337b5b6ce89795f6`.
- Policy: `p09-guide-enrichment-policy/1.0.0`; boundary
  `sha256:627f0dfcbbd96da86c484ee4d0b0d62c17c2b0a2ce698e28baf55244f6a09c00`.

Cada pregunta tiene namespaces locales `Q*`, `E*` y `O*`; el output sólo
puede añadir `N*`. Una referencia desconocida o evidence alias de otra
pregunta falla determinísticamente. El source scope, envelope, support bundle,
approval y todos los hashes anteriores forman la frontera de cache/replay.

## 6. Invariantes de guía

- READY cubre exactamente todas las preguntas aprobadas una vez; no hay guía
  parcial.
- Cada item queda limitado a su support evidence question-local y CLOSED no
  admite course sources/conocimiento externo.
- Purpose y observables core P07 no se omiten, reformulan ni contradicen.
- El total queda entre 2 y 5 observables; las adiciones no duplican el core.
- Existen exactamente niveles 0, 1, 2 y 3; sus aliases son válidos y nivel 2
  contiene cada observable `required_for_level_2`.
- `cannot_infer` y semantic uncertainties son item-specific; los avisos
  globales de autoría/IA/fraude/historia/system prompt se rechazan.
- `NEEDS_REVIEW` contiene cero items; error de provider/materializador deja el
  Assessment aprobado y ninguna guía READY parcial.

## 7. Versiones, historia, exports y UX

La migración `202608160007_phase7_post_approval_p09.sql` es aditiva. Agrega
binding nullable a `evaluation_guides`, descriptor nullable a `jobs` e índice
único parcial `(tenant_id, assessment_id, assessment_version)`. El backfill
marca filas antiguas `HISTORICAL_PREAPPROVAL` sin borrar su JSON ni reescribir
receipts/reportes.

Una guía sólo es current si todo el binding coincide con la versión aprobada
vigente. Una guía legacy o de v1 no se usa para v2. History continúa legible y
etiquetada; export falla con precondition mientras no exista Guide READY exacta
y nunca mezcla Assessment/Guide de versiones distintas.

La revisión muestra Assessment/preguntas antes de approval y separa el estado
de guía `not available`, `pending`, `building`, `needs review`, `failed` o `ready`. Aprobar no
queda bloqueado por el proveedor y una guía pending/failed no se presenta como
Assessment no aprobado.

## 8. Recovery y seguridad

- commit de approval + crash pre-job: reconciliation crea un solo logical job;
- crash tras claim: retry/recovery conserva binding e identidad lógica;
- output P09 persistido en StageRun + crash pre-projection: resume reutiliza el
  output canónico y no duplica P09/guide;
- approval repetida: no redispacha después de `guide.dispatch_succeeded`;
- floor legacy `GUIDE_BUILD`: reconciliación segura sin conceder autoridad a
  una guía pre-aprobación;
- provider authorization acepta el nuevo job kind sólo con claim exacto; una
  autorización SUBMISSION pre-aprobación no habilita GUIDE_BUILD.

Service/worker ordinario continúan mock. No se resolvió Secret Manager, no se
creó autorización billable, no se construyó transporte real y no se usaron
datos estudiantiles reales.

## 9. Cobertura focal A–T

| Caso | Evidencia automatizada |
|---|---|
| A/B | ASSEMBLE y múltiples acciones pre-aprobación: cero P09/cero guide active |
| C/D/E | aprobación exacta: un job, un P09, materialización READY; replay idempotente |
| F/G | DTO no puede cambiar pregunta/anchor/path; aliases no cruzan evidence question-local |
| H/I/J | core P07 intacto; niveles 0–3/required; output fuera de support falla cerrado |
| K | failure/abstention conserva Assessment APPROVED y no publica partial READY |
| L/M | nueva versión invalida current v1; reapproval v2 crea un solo P09 v2 |
| N/O | recovery pre-job y crash post-P09 usan un logical guide/StageRun |
| P/Q | legacy legible no current; exports requieren binding/version exactos |
| R/S | P05/P08 históricos y P10 disabled |
| T | N preguntas aprobadas: P06=1, P07=N, P09=1, total nominal N+2 |

## 10. Coste y siguiente deuda

Fase 7 no cambia routing, modelo, reasoning ni el total nominal N+2. Elimina
P09 de versiones no aprobadas/descartadas; no se inventa una tasa media de
descarte ni un ahorro medio. La única deuda funcional siguiente autorizada es
integrar el corpus humanamente ratificado y construir un benchmark semántico
nuevo por propiedades/invariantes. Las qualifications históricas siguen como
`HISTORICAL_NON_CANONICAL_EVIDENCE`; esta fase no inicia corpus, benchmark ni
qualification real.
