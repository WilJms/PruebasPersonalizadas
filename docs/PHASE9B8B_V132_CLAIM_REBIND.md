# Phase 9B.8B — semantic-benchmark/1.3.2

**Status: `SEMANTIC_BENCHMARK_V1_3_2_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT`**

Provider calls 0, adjudicator calls 0, billable authorizations 0, credentials
resolved 0, real transport false, candidate outcomes read false, pricing
refresh false. HIGH SMOKE not authorized.

`semantic-benchmark/1.3.1` is marked
`SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED` and its bytes are
untouched. Nothing ever ran against it, so this is a pre-execution
authority-binding repair — not result-driven tuning, not a corpus change, not a
change to any accepted product decision.

Every number below is checked against the machine by
`tests/test_phase9b8b_document.py`.

## What was wrong

1.3.1 was the active pre-execution candidate, but the qualification text it
carried forward still said:

> semantic-benchmark/1.3.0 qualifies P06 candidate behaviour …
> semantic-benchmark/1.3.0 does NOT qualify P06 UNCERTAIN behaviour.

Those sentences were written for 1.3.0 and were correct then. Carried into 1.3.1
verbatim they became a *current* claim about a superseded version, in four
places: the qualification protocol's claim and first limitation, the global
benchmark boundary's limitations, the pre-results freeze's limitations, and the
P06 stage boundary's copy of them. A reader was left to infer applicability from
version lineage, which is exactly what an authority artifact exists to remove.

The mechanical policy was never wrong: `SUFFICIENT` / `PARTIAL` /
`INSUFFICIENT` qualified, `UNCERTAIN` excluded and still in the production
contract, Phase 9 alone not full contract coverage.

## The rebound claim

> semantic-benchmark/1.3.2 qualifies P06 candidate behaviour on the support
> statuses SUFFICIENT, PARTIAL and INSUFFICIENT.

Limitations:

- semantic-benchmark/1.3.2 does NOT qualify P06 UNCERTAIN behaviour.
- P06 model-selection claims are limited to SUFFICIENT / PARTIAL / INSUFFICIENT.
- UNCERTAIN remains an explicit residual risk.
- Phase 9 alone does not establish full P06 contract coverage.

Claim hash
`sha256:1812472f3ebe1f04d82a60e5200da172863fb23035c7fcd50953ff391d112d2d`.

Applicability is stated, not inferred: `applicable_benchmark_version`
semantic-benchmark/1.3.2, `supersedes_claim_binding_from`
semantic-benchmark/1.3.1, `claim_semantics_changed_from_v131` false. The
artifact also carries the historical claim lineage — including the fact that
1.3.1's claim named 1.3.0 and why that was a defect — under fields explicitly
labelled as history.

The exclusion stays derived, not declared: a status is listed as qualified only
where the frozen instrument actually carries candidate-scoring properties
asserting it, and `UNCERTAIN` has none. The build refuses to publish if the
derived set stops matching the accepted U3 decision.

## Nothing mechanical moved

| | |
| --- | --- |
| candidate-scoring properties | 69, hash identical to 1.3.1 |
| routes, cases, bindings, splits, catalog, coverage debt | hashes identical to 1.3.1 |
| denominators | CORE 41, HELD_OUT_CONFIRMATION 27, SMOKE 1 |
| bars, N3 gates, ordering, adjudication protocol | identical to 1.3.1 |
| N3 fixture-set hash | `sha256:f53ec77ae4c26732644083d10497e65e1a1bc34f830e675aa4848669d106c62d` |
| N3 splits | 1 SAFETY_SMOKE / 6 CORE / 3 HELD_OUT |
| call-budget hash | `sha256:6fdc5eed1e2175abd89fe6c17df2d4ff2cd84503f4acdef18fb8eaae54fddfa7` — **unchanged** |

The N3 equality proof is field-by-field, not an aggregate comparison: the
derived fixture authority is compared with the published 1.3.1 document key by
key and every one of the ten request hashes individually, so a change that
happened to preserve the set hash would still be caught.

The call budget binds no claim, protocol or global value, so its material did
not change and its hash was not forced to. Six artifacts are republished
byte-identically from 1.3.1 — the fixtures, the N3 axis, the budget and the
three N3 proofs — and the protocol refuses to publish if the budget hash moves.

## Boundaries

| Stage | Status | Hash |
| --- | --- | --- |
| P04 | carried forward from 1.3.1 | `sha256:b0ade4a135d1a5d5fb63570953746715e111840b854411b2a79d4b3e8d3f5417` |
| P06 | new in 1.3.2 | `sha256:d131900ff7bbed00fd933a1004ccfa457cb5651e0b04b284efb8e0aeff77a3ff` |
| P07 | carried forward from 1.3.1 | `sha256:889a2498ddd0194a641f796ed4c82686318602a29a0f5bb2729686dc7690854f` |
| P09 | carried forward from 1.3.1 | `sha256:090b17302b711c19ce1067e0c0c041ec29d5d337b4cb462c5a476bb84c5fb926` |
| PLANNER | carried forward from 1.3.1 | `sha256:961384f7f9c25601b5aea91217849be79400517d7b5960924c79789c93687376` |

P06 is new because it binds the claim hash, which changed. The other four bind
no semantic qualification claim, so rebinding it cannot reach them — and that is
proved by reconstructing each one's complete 1.3.1 material component by
component.

Global `sha256:4951cc243ff69a534378388fe07a61c41df7fcd83b3869673d06ba38db5cacf1` ·
protocol `sha256:f2150f35bc13934a4179ee14dcff340fbd5a4c886e9754ebfb29eddaa6b6c17d` ·
matrix `sha256:90459eda031efd54981c1aa791521f469d634a843891ea4b7bc812155384d0c5`
(candidate identities byte-identical to 1.3.1).

## The stale-claim scan

Every 1.3.2 artifact is walked and every mention of a superseded version is
classified. A mention is permitted only inside a field that records history or
provenance, inside a carried-forward stage subtree, or inside an artifact
republished byte-identically and declared as such. Everything else is a current
statement and must name 1.3.2. Violations: 0.

Two artifacts cannot appear in their own scan — the report would have to contain
its own hash, and the freeze binds the report's hash. They are named in
`deferred_to_closing_pass` and covered by a closing pass over the complete
package, which raises on any violation before anything is written. A regression
poisons the freeze and confirms the closing pass rejects it, so the deferral is
coverage rather than an excuse.

The scan report's own evidence fields quote the strings it searches for, so they
are exempt by construction and the artifact says so.

## What the construct-selection rule asserts

`FIRST_AUTHORIZED_CONSTRUCT_IN_CANONICAL_SOURCE_ORDER` is a **pre-registered
sampling rule** grounded in authorized source structure. N3 needs exactly one
authorized, deterministic, outcome-independent construct per exposure to
instantiate a production-valid P06 call, and source order supplies that choice
without consulting anything a result could influence.

It does **not** assert that the instructor academically prioritized the first
criterion, that the first construct is more important, or that source position
changes a semantic expected answer. The nine contractual obligations N3
adjudicates are construct-independent — they govern how the model treats
instruction-shaped text in untrusted evidence, not which criterion it is scoring
— so any authorized construct instantiates the call equally well.

This clarification is published as its own artifact
(`sha256:21a535de03c51fc44a84047fc9a4ac7d4df88a9c0b70cc57b6718362cede6e8f`) and
bound by the P06 boundary. It is deliberately *not* written into
`n3_provider_fixtures.py`: the fixture set binds that module's source hash, so
even a docstring edit would move `fixture_set_hash` and force a rebuild of
authority that has not changed. No fixture byte moved to change prose.

## Rebuilding

```bash
python scripts/freeze_semantic_benchmark_v132.py
```

The script refuses to write if two builds disagree, if the self-hash registry is
out of sync with the package, or if the closing stale-claim pass finds anything.
