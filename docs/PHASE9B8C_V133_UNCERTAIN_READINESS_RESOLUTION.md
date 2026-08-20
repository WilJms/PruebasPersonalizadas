# Phase 9B.8C — semantic-benchmark/1.3.3

**Status: `SEMANTIC_BENCHMARK_V1_3_3_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT`**

Provider calls 0, adjudicator calls 0, billable authorizations 0, credentials
resolved 0, real transport false, candidate outcomes read false, pricing
refresh false. HIGH SMOKE not authorized.

`semantic-benchmark/1.3.2` is marked
`SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED` and its bytes are
untouched. Nothing ever ran against it, so this is a pre-execution
authority-binding repair — not result-driven tuning, not a corpus change, and
not a change to any accepted product decision. U3 and N3 are reaffirmed, not
reopened.

Every number below is checked against the machine by
`tests/test_phase9b8c_document.py`.

## What was wrong

1.3.2 says the right things about coverage. Its qualified statuses are
`SUFFICIENT` / `PARTIAL` / `INSUFFICIENT`, `UNCERTAIN` is excluded, `UNCERTAIN`
remains residual risk, and Phase 9 alone is not full P06 contract coverage.

But its *active* qualification claim still embedded the pre-decision gate
verbatim:

```
uncertain_coverage_gate.readiness_blocked = true
uncertain_coverage_gate.stop_code = P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED
```

`uncertain_coverage_gate()` defines that state as stopping the readiness path
*until a product decision is made*. In Phase 9B.6 that was exactly right: every
way of closing the gap — a construct-set route, an artifact-absence route, new
corpus properties, or narrowing the claim — is a product decision, and none had
been made.

Phase 9B.7 then made one. `reports/semantic_benchmark/phase9b7/product_decision.json`
records `uncertain_recommendation: U3` under verdict
`PHASE9B7C_U3_N3_READY_FOR_PUBLICATION`, decision hash
`sha256:160d3ae781e41606f711d9a0b98f1e494b83128188fb2825db2c08e10580f7ea`. U3 is
*narrow the qualification claim; carry UNCERTAIN as residual risk*. So from
9B.7 onward, an active 1.3.2 field was demanding a decision that already
existed.

## UNCOVERED is not UNRESOLVED

The whole repair rests on one distinction, and 1.3.3 states it in the artifact
rather than leaving it to a reader:

- **UNCOVERED** is a fact about the instrument. No candidate-scoring P06
  property asserts `UNCERTAIN`, so a qualification run cannot observe that
  behaviour. U3 does not change this and must not appear to.
- **UNRESOLVED** was a fact about the product. Nobody had decided what to do
  about the uncovered status. U3 decides exactly this, and only this.

So the coverage fact survives untouched and the disposition moves.

## The coverage fact, unchanged

| Field | Value |
|---|---|
| `coverage_status` | `UNCOVERED` |
| `candidate_scoring_property_count` | 0 |
| `uncertain_qualification_claimed` | false |
| `uncertain_removed_from_production_contract` | false |
| `residual_risk` | true |
| `semantic_routes_added` | 0 |
| `semantic_properties_added` | 0 |

No route, property or corpus byte was added. `UNCERTAIN` remains a first-class
member of the P06 support-status contract.

## The resolved disposition

Published as `evaluation/semantic_benchmark/v1_3_3/phase9/uncertain_coverage_disposition.json`,
hash `sha256:89d39833688d80ebb002ada3660a1bf60de2c4ae6f57ecbe4cc802c08992625c`.

| Field | Value |
|---|---|
| `decision_gap` | `P06_UNCERTAIN_SEMANTIC_COVERAGE` |
| `pre_decision_status` | `PRODUCT_DECISION_REQUIRED` |
| `product_decision` | `U3` |
| `product_decision_source` | `reports/semantic_benchmark/phase9b7/product_decision.json` |
| `product_decision_status` | `RESOLVED` |
| `resolution` | `NARROW_QUALIFICATION_CLAIM_AND_CARRY_RESIDUAL_RISK` |

with active semantics:

| Field | Value |
|---|---|
| `requires_product_decision` | false |
| `blocks_phase9_qualification` | false |
| `blocks_candidate_rung_selection` | false |
| `blocks_full_p06_contract_coverage_claim` | true |
| `uncertain_remains_unqualified` | true |
| `readiness_blocked` | false |
| `active_stop_code` | null |

## The pre-U3 gate is retained as history

`uncertain_coverage_gate()` itself is not edited. It is still the correct answer
to the question it asks, it is bound into published 1.3.0 / 1.3.1 / 1.3.2
authority, and Phase 9B.6's findings quote it. What 1.3.3 adds is the second
question the gate never asked — *the status is uncovered; what has been decided
about that?*

The gate result is carried verbatim inside
`pre_u3_uncertain_coverage_gate`, labelled `HISTORICAL_PRE_DECISION_EVIDENCE`,
with `is_the_active_state: false`, `was_the_active_state_in_phase: 9B.6`,
`triggered: PHASE_9B7_UNCERTAIN_PRODUCT_DECISION` and
`superseded_for_readiness_by: U3`. Deleting it would make U3 look like a
default rather than a decision.

`product_decision_state_scan.json`
(`sha256:7b4c9fbb5cb845fdc4be105dc402fe50ad58be9bad5c9b17abe360a0f3fe5699`) is
the executed proof of the rule. It walks every string and every boolean in the
package looking for `PRODUCT_DECISION_REQUIRED`, and for a true
`readiness_blocked` or `requires_product_decision`. Occurrences: 10.
Violations: 0. Each permitted occurrence is labelled with why —
`EXPLICIT_HISTORICAL_RECORD`, `SCAN_SELF_EVIDENCE_FIELD` or
`REPUBLISHED_UNCHANGED_FROM_semantic-benchmark/1.3.2`. Anything else raises and
the build cannot publish.

## The readiness release is bound to U3, not general

The disposition is derived from the recorded decision, not declared alongside
it. It releases the readiness block only while the decision is `U3` and its
status is `RESOLVED`. Otherwise it reproduces the original stop code as the
active state:

| Recorded decision | `readiness_blocked` | `active_stop_code` |
|---|---|---|
| U3 / RESOLVED | false | null |
| U3 / not RESOLVED | true | `P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED` |
| U1, U2 or U4 | true | `P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED` |

U1, U2 and U4 are enumerated in the artifact with what each would have required,
so a substitution is an explicit rejection rather than an unrecognised value
falling through to a permissive default. The Phase 9B.7 document is also *read*
rather than assumed: if it stops recording U3, the build raises.

## The active claim

> semantic-benchmark/1.3.3 qualifies P06 candidate behaviour on the support
> statuses SUFFICIENT, PARTIAL and INSUFFICIENT.

Claim hash `sha256:49dd08d561ee453b1e9652b4fd1c4c35a293556a2138e9184d036228a6112d36`,
applicable to `semantic-benchmark/1.3.3`, superseding the binding from
`semantic-benchmark/1.3.2`. The limitations are unchanged in meaning:

> semantic-benchmark/1.3.3 does NOT qualify P06 UNCERTAIN behaviour.
> P06 model-selection claims are limited to SUFFICIENT / PARTIAL / INSUFFICIENT.
> UNCERTAIN remains an explicit residual risk.
> Phase 9 alone does not establish full P06 contract coverage.

The exclusion is still derived, not declared: a status is listed as qualified
only when the frozen instrument actually carries candidate-scoring properties
asserting it.

## What the protocol now states mechanically

`phase9-qualification-protocol/1.3.3`
(`sha256:9a80dd3c76ff5dbccfb2bfb6295da75d5afcc5d16e52827606543aeb5b1301cd`)
carries an `uncertain_coverage_readiness` block:

| Field | Value |
|---|---|
| `zero_uncertain_coverage_blocks_execution` | false |
| `zero_uncertain_coverage_blocks_full_p06_contract_coverage_claim` | true |
| `additional_product_decision_pending_for_this_gap` | false |
| `qualification_may_proceed_only_within_the_narrowed_claim` | true |
| `uncertain_may_enter_accepted_semantic_rate` | false |
| `uncertain_is_claimed_qualified` | false |
| `readiness_release_is_generic` | false |

## Nothing mechanical moved

`semantic_invariant_equality_proof.json`
(`sha256:bbbe227c0ca838f11c63882069bd2eb68aa2e7f03c9e42e383b28bc3a35ebfaf`)
reconstructs 28 invariants from 1.3.3 authority and compares each with the
value 1.3.2 published. A difference raises; nothing is reported as an
acceptable delta.

| Invariant | 1.3.3 |
|---|---|
| candidate-scoring properties | 69, hash identical |
| semantic denominators | CORE 41, HELD_OUT_CONFIRMATION 27, SMOKE 1 |
| accepted-rate bars | 0.80 SMOKE / 0.95 CORE / 0.95 HELD_OUT, identical |
| max confirmed hard-safety model failures | 0, identical |
| routes, cases, bindings, splits | hashes identical |
| N3 axis | `sha256:a3a3118ff3e02d918b16d1c312493a2beaffabd1951d98b6de52fa40c5d0fc67` |
| N3 fixture set | `sha256:f53ec77ae4c26732644083d10497e65e1a1bc34f830e675aa4848669d106c62d` |
| N3 fixtures and request hashes | all 10 identical, field by field |
| N3 split sequencing | 1 SAFETY_SMOKE / 6 CORE / 3 HELD_OUT |
| candidate identities, rungs, families | identical |
| adjudication semantics | hash identical |
| call budget | `sha256:6fdc5eed1e2175abd89fe6c17df2d4ff2cd84503f4acdef18fb8eaae54fddfa7`, unmoved |

The N3 fixtures are proved separately and field by field by
`n3_fixture_equality_proof.json`
(`sha256:c8eb66d84ddb823d289372ceb880f1705676188642558a19bceda326e3a35a15`) —
the aggregate hash alone is not the proof.

The call budget binds no claim, no protocol and no global value, so its complete
material is unchanged and its hash is *not* forced to move.

## Boundaries

| Stage | Status | Hash |
|---|---|---|
| P04 | carried forward from 1.3.2 | `sha256:b0ade4a135d1a5d5fb63570953746715e111840b854411b2a79d4b3e8d3f5417` |
| P06 | new in 1.3.3 | `sha256:607e7f0037add9bca6fc7d446480978620c6db09fd9bfacd1df5bb8c4a3e13a6` |
| P07 | carried forward from 1.3.2 | `sha256:889a2498ddd0194a641f796ed4c82686318602a29a0f5bb2729686dc7690854f` |
| P09 | carried forward from 1.3.2 | `sha256:090b17302b711c19ce1067e0c0c041ec29d5d337b4cb462c5a476bb84c5fb926` |
| PLANNER | carried forward from 1.3.2 | `sha256:961384f7f9c25601b5aea91217849be79400517d7b5960924c79789c93687376` |

P06 is new because the active claim and the UNCERTAIN disposition both changed.
It binds the new claim hash, the U3 disposition hash, the Phase 9B.7 decision
source, its decision hash and its file SHA-256
(`sha256:1b06a7028c5ecfeafd93f0827c2b117a7f72ca1970c2e5598bd467cbe7d92eb6`), the
unchanged semantic scoring authority and the unchanged N3 fixture-set authority.

P04, P07, P09 and PLANNER carry forward only on a passing equality proof:
every component of the 1.3.2 boundary is reconstructed from 1.3.3 authority and
must reproduce the frozen hash exactly. A carry-forward whose hash moved, or a
new boundary that reproduced the old hash, raises.

Aggregates:

| Artifact | Hash |
|---|---|
| stage boundaries | `sha256:6fbc2559e7d4efcc6629cc8403073a809ecf641e0d7150ced7beaf8c36a3484d` |
| global benchmark boundary | `sha256:aecac8a57971258bea740497912f145395c42c250c5fdb55f4a2e723abc92d44` |
| candidate matrix | `sha256:34e3baee99acedc4006f82a2235a66711a137de050eca776d2d826bd907b48a5` |
| lineage | `sha256:8bd2980e16ae3749a317a64157b6f9281176fa73f97037989c39a68d92603671` |
| pre-results freeze | `sha256:bbbb409522b68815eb767a41b859eccfc9b9d64560327ff912b886918112cf4b` |

The candidate matrix hash moves because it binds the 1.3.3 protocol and the
1.3.3 global boundary. Its candidate identities are proved byte-identical to
1.3.2.

## The stale-claim scan

`stale_claim_scan.json`
(`sha256:d32862ed19b4a63de92683468908c9e7c3951ff3bda31c4b5bf530edb1ec4ec2`)
walks every string in the package for `semantic-benchmark/1.3.0`, `1.3.1` and
`1.3.2`. Mentions found: 58. Violations: 0. A superseded version may appear only
in a history or provenance field, in a carried-forward stage subtree, or in an
artifact republished byte-identically and declared as such.

The scan report and the freeze cannot appear in their own scan without
self-reference, so both are listed in `deferred_to_closing_pass` and covered by
a closing pass over the complete package, run after both exist. The same holds
for the product-decision state scan. The build cannot publish while either
closing pass fails.

## Republished unchanged

Seven artifacts are republished byte-identically from 1.3.2 — the N3 provider
fixtures, the N3 contractual safety axis, the construct-selection semantics
(`sha256:21a535de03c51fc44a84047fc9a4ac7d4df88a9c0b70cc57b6718362cede6e8f`), the
call budget and the three N3 proofs. Their complete material is unchanged, so
republishing them with a new version stamp would move a hash without moving a
meaning.

## Rebuilding

```bash
python scripts/freeze_semantic_benchmark_v133.py
```

The script refuses to write if two builds disagree, if the self-hash registry is
out of sync with the package, or if either closing scan finds anything.
