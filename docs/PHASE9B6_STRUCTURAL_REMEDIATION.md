# Phase 9B.6 — pre-results structural remediation

**Verdict: `PHASE9B6_PRODUCT_DECISION_REQUIRED`**

Machine artifact:
`reports/semantic_benchmark/phase9b6/structural_remediation_findings.json`

- provider calls: **0**
- adjudicator calls: **0**
- billable authorizations: **0**
- OpenAI credentials resolved: **0**
- real transport constructed: **false**
- corpus bytes modified: **no**
- `semantic-benchmark/1.2.0` frozen authority rewritten: **no**
- new benchmark version created: **none** (blocked — see below)

`semantic-benchmark/1.2.0` is historical after the Phase 9B.5 audit. Its frozen
bytes, and every source file hashed into its boundaries, are untouched, so the
v1.2 PART A instrument freeze still reproduces exactly.

## Phase A — every blocker reproduced

| Blocker | Reproduced from |
|---|---|
| `A04-S03-P1` bound to `RUBRIC::A04::NO_MUTA_SOLICITUDES_NI_CUPOS_POR_GRUPO` | frozen v1.2 bindings — matched reference `"no"`, rule `UNIQUE_NAME_PREFIX` |
| `A04-S05-P5` asserts two verifications, routed as one | frozen corpus property + v1.2 binding with a single match |
| bare `'No'` resolves by prefix | A04 has exactly one criterion beginning `No …` |
| `D1`/`D10` label defect | `\b([A-Z]\d)\b` yields nothing for `D10`, and only `D1` for `D1 y D10` |
| copied-key alignment is tautological | both keys written from one resolver variable; 77/77 rows equal by construction |
| `PROMPT_INJECTION_NOISY` 6 → 0 | v1.1 route tags vs v1.2 route tags |
| P07 has no field authority or companion | no `p07_*` module existed; generic packet carries output + opaque id |

Nothing contradicted the stated findings, so remediation proceeded.

## What was repaired

**Resolver** (`p06_construct_resolution.py`) — `UNIQUE_NAME_PREFIX` removed
entirely. Two match rules remain: exact authorized name and exact authorized
label. Labels accept `[A-Z]\d{1,3}`, so `D10` is representable and `D1 y D10`
fails closed as multi-construct instead of collapsing to `D1`. Every reference
the resolver sees is now *accounted for*: an unmatched reference that resembles
a catalog name blocks resolution rather than vanishing. Result: **77 → 71**
routes, 6 removed, **0 added, 0 retargeted**. Route count is not a target.

**Alignment** (`p06_alignment_verification.py`) — alignment is decided by
re-deriving the construct from the frozen property text plus the catalog. The
declared keys are checked against that derivation, never its evidence. Applied
to the frozen v1.2 bindings, which v1.2 reported as 77/77 aligned, the
independent verifier reports **6 misaligned**, including `A04-S03-P1`. That
disagreement is the evidence it is not the same tautology.

**Rare coverage** (`p06_rare_coverage.py`) — every required family gets a row,
zeros included, each with a *diagnosed cause* separating "the corpus never had
it" from "the instrument dropped it". `PROMPT_INJECTION_NOISY` is now its own
family. Silent and noisy injection are declared non-substitutable. Hard safety
stays at 0 permitted confirmed `MODEL_FAILURE`s.

**Support status** (`p06_support_status_coverage.py`) — coverage derived from
oracle property text and activity 04's authorized `Sí / No / No verificable`
scale, not from benchmark tags (the corpus declares no `P06_UNCERTAIN` tag at
any scope, so a tag-derived answer would be circular). `uncertain_scope_census()`
counts the UNCERTAIN-bearing properties with the scope always explicit, and the
prose below is generated from those counts rather than restated beside them.

**P07 authority** (`p07_field_authority.py`, `p07_adjudication_context.py`) —
10 `MODEL_OWNED`, 24 `SERVER_OWNED`, 9 `SERVER_DERIVED_FROM_MODEL_INPUT` fields
traced through `QuestionAliasEnvelope → QuestionModelDraft →
materialize_question_draft() → QuestionGenerationResult / QuestionCandidate`.
The blind companion binds packet hash, opportunity identity, case id, stage
boundary and field-authority hash; added fields, tampering and cross-packet
attachment all fail closed, and an allow-list defeats a recomputed hash. Generic
P04/P06/P09 packet bytes were not touched.

> The sharpest P07 risk: `QuestionGenerationResult.status` is **server-derived**.
> `REPLACEMENT_REQUIRED` is also returned for blocked answer leakage, a repeated
> question fingerprint and a choice/format mismatch. Reading it as the model
> confessing failure is exactly the misattribution
> `NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE` exists to prevent.

**Claim accuracy** — the rubric column `Dónde debería poder comprobarse` is part
of a criterion's authorized definition and does reach the model-visible route.
It is **not** removed and **not** called oracle leakage; the blanket claim "no
location is projected into the route" was corrected to the narrower true one
about *submission* evidence location. Activities 05 and 12 each **do** obtain
four `ASSIGNMENT_REQUIREMENT` constructs; their zero routes are a resolution
outcome, not an absent catalog. No inferred routes were created for them.

## Why this stops

### 1. `P06_UNCERTAIN` semantic coverage is zero

Every count below is derived by `uncertain_scope_census()` from frozen oracle
property text, and this table is emitted verbatim by the findings builder. A
submission-level property is the only kind that can become a candidate gate; an
activity-level property is a coverage index over its activity's submissions and
is never a gate, so the two are counted separately and never silently summed.

| Population | Count |
|---|---|
| submission-level P06 properties whose text asserts UNCERTAIN | 9 |
| ... of those, `oracle_state VALID` | 8 |
| ... of those, kind `REQUIRED` | 8 |
| activity-level P06 properties describing UNCERTAIN (coverage-index statements, never candidate gates) | 2 |
| combined across both scopes (submission-level + activity-level) | 11 |
| candidate-scoring executable P06 properties asserting UNCERTAIN | 0 |

The frozen corpus asserts UNCERTAIN in 9 submission-level P06 properties across 6 activities, 8 of them with oracle_state VALID and kind REQUIRED. A further 2 activity-level P06 properties describe UNCERTAIN as a coverage index over their activity's submissions, which is not a candidate gate; both scopes together are 11 properties. Of the submission-level population, 0 reach an executable candidate-scoring route. The material exists; it cannot be routed.

The production contract expresses UNCERTAIN (`EvidenceSupportStatus`,
`semantic_uncertainty`, `abstention_reason`).

The last row is the blocking readiness fact. It is derived, not declared: if a
future change made it non-zero, the gate would open on its own rather than
needing this document edited.

Diagnosis — **cause A only** (existing-corpus fixture/binding form). Not B: the
semantics exist. Not C: the contract is expressive enough. Every such property
fails the *one-construct gate*: most name no rubric criterion because they
assert UNCERTAIN about the submission as a whole or about everything depending
on an absent artifact; `A07-S02-P2` names two criteria exactly; `A04-S03-P1`
asserts over all four rows of the `Nota técnica` section at once.

### 2. `PROMPT_INJECTION_NOISY` executable coverage is zero

Not one of the **10** NOISY-tagged submissions has a single resolvable P06
property. Injection-resistance properties assert a cross-cutting stage
obligation — do not obey instruction-shaped text inside a submission — rather
than a claim about a named rubric criterion. A construct-named P06 gate cannot
carry them at all. **No resolver change closes this.** P07 carries 17
NOISY-tagged opportunities, which narrows the residual risk but is a different
stage and is never reported as P06 coverage.

## Alternatives requiring a decision

| # | Gap | Option | Corpus change | Key consequence |
|---|---|---|---|---|
| U1 | UNCERTAIN | construct-set route form | no | redefines what a candidate gate spans; needs a partial-satisfaction scoring rule and a fresh representativeness proof |
| U2 | UNCERTAIN | artifact-absence route form | no | highest risk of reintroducing v1.1 location-derived semantics under a new name |
| U3 | UNCERTAIN | narrow the qualification claim | no | cheapest and most honest, but leaves the abstention status unexercised |
| U4 | UNCERTAIN | extend the corpus | **yes** | **explicit user authorization required**; legitimate only as genuine reviewer curation |
| N1 | NOISY | accept zero P06 exposure, reported explicitly | no | hard-safety policy enforced over a stage that cannot observe the family |
| N2 | NOISY | stage-obligation route form | no | the only option that restores coverage; introduces a second kind of P06 target |

Each option needs `semantic-benchmark/1.3.0`,
`phase9-qualification-protocol/1.3.0`, a new global boundary, a new candidate
matrix hash and — for every option, including the ones that change no corpus
byte — **new P06 *and* P07 stage boundaries**. Why P07 is mandatory is the next
section. U4 additionally changes corpus bytes, so it recomputes every
corpus-dependent stage boundary: P04, P06, PLANNER, P07, P09. Routing, candidate
families, reasoning rungs, caps, the 0.80/0.95/0.95 bars, k=3 semantic / k=1
planner and the held-out partition are unchanged, and cross-family fallback
stays forbidden.

## The future P07 stage boundary

Phase 9B.6 introduced `p07-field-authority/1.0.0` and
`p07-adjudication-context/1.0.0`. The v1.2 P07 stage boundary is the **generic**
one: it binds the corpus package, P07 case definitions, P07 property bindings,
P07 split assignments and the v1.1 opportunity fixture file — and nothing else.
It binds no materializer, no schema and neither companion artifact, so changing
P07 field authority or the blind companion cannot invalidate its hash. That is
exactly the property a stage boundary exists to provide, and it is absent.

**Therefore any future `semantic-benchmark/1.3.0` that adopts the Phase 9B.6 P07
repair must publish a new P07 stage boundary.** For a no-corpus-change v1.3 the
minimum changed set is `{P06, P07}`. A new P07 boundary must bind at least:

- P07 case definitions
- P07 property bindings
- P07 fixture/opportunity definitions
- P07 split assignments
- P07 materializer executable boundary
- `QuestionAliasEnvelope` schema boundary
- `QuestionModelDraft` schema
- P07 field-authority hash and its executable source hash
- P07 adjudication-context schema version and its executable source hash
- the opportunity-context generation dependency blind attribution requires

`future_stage_boundary_plan.py` enforces this: a plan that adopts a P07
companion artifact and omits `P07` from `new_stage_boundaries` is rejected with
`P07_COMPANION_ADOPTED_WITHOUT_NEW_P07_STAGE_BOUNDARY`, and a no-corpus-change
plan below `{P06, P07}` with
`BELOW_MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARY_SET`. **No v1.3 boundary is
calculated or published here** — this is the dependency plan only, because which
alternative is adopted is still an open product decision.

## Change-set bookkeeping

The Phase 9B.6 delivery is the compare
`c4fcd5227f56560f840fd4bd8616e7df2e3b1099 → 6cabd50bdf7573dfb2e981ff9d9df76a6ebe9f96`.
It contains **12** changed tracked files. An earlier report of 14 was wrong.

This number is human-readable bookkeeping, not a semantic invariant: it is not
hashed into the findings artifact and no boundary depends on it. It is derived
from the commit comparison, and a regression re-derives it rather than trusting
the figure above:

```bash
git diff --name-only c4fcd5227f56560f840fd4bd8616e7df2e3b1099 6cabd50bdf7573dfb2e981ff9d9df76a6ebe9f96 | wc -l
```

Later Phase 9B.6A consistency corrections are separate commits and are not part
of that compare.

## Reproducing

```bash
.venv/bin/python scripts/build_phase9b6_findings.py
```

The artifact is byte-deterministic from frozen source. A fresh independent
pre-execution re-audit remains mandatory before any authorization or HIGH SMOKE.
