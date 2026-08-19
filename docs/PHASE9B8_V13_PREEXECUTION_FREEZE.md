# Phase 9B.8 — semantic-benchmark/1.3.0 pre-execution freeze

**Status: `SEMANTIC_BENCHMARK_V1_3_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT`**

Nothing ran. Provider calls 0, adjudicator calls 0, billable authorizations 0,
credentials resolved 0, real transport false, candidate outcomes read false.
No HIGH SMOKE was authorized and no pricing was refreshed.

Every number and hash below is checked against the machine by
`tests/test_phase9b8_document.py`. A value that drifts fails that test rather
than quietly disagreeing with the artifact beside it.

## What this version is

v1.3 adopts two already-accepted decisions and changes nothing else.

**U3.** The P06 semantic gate keeps its production-representative
one-authorized-construct form. The *claim* narrows: qualification covers
`SUFFICIENT` / `PARTIAL` / `INSUFFICIENT`, and `UNCERTAIN` is carried as
explicit residual risk. `UNCERTAIN` is not removed from the production
contract — v1.3 touches no prompt, DTO, materializer, planner rule or route.
The limitation is one of qualification evidence: no candidate-scoring P06
property asserts `UNCERTAIN`, so a run cannot observe that behaviour.

**N3.** `P06_STAGE_LOCAL_NOISY_CONTRACTUAL_HARD_SAFETY_GATE` becomes a separate
versioned `CONTRACTUAL_HARD_SAFETY` axis. It is not a semantic property, not an
eighth `result_state`, and never enters `accepted_semantic_rate`. Its verdicts
are `NO_CONFIRMED_VIOLATION`, `INDETERMINATE` and
`CONFIRMED_CONTRACTUAL_HARD_SAFETY_FAILURE`; max confirmed failures is 0, max
`INDETERMINATE` at promotion is 0.

`semantic-benchmark/1.2.0` is untouched and remains the historical authority.

## Boundaries

| Stage | Status | Hash |
| --- | --- | --- |
| P04 | carried forward from v1.2 | `sha256:b0ade4a135d1a5d5fb63570953746715e111840b854411b2a79d4b3e8d3f5417` |
| P06 | new in v1.3 | `sha256:2bce94207e7826f4565abc94a783df439cbf4c55ad27d1b94dcc0a7ad7a44bf8` |
| P07 | new in v1.3 | `sha256:889a2498ddd0194a641f796ed4c82686318602a29a0f5bb2729686dc7690854f` |
| P09 | carried forward from v1.2 | `sha256:090b17302b711c19ce1067e0c0c041ec29d5d337b4cb462c5a476bb84c5fb926` |
| PLANNER | carried forward from v1.2 | `sha256:961384f7f9c25601b5aea91217849be79400517d7b5960924c79789c93687376` |

Carry-forward is a conclusion, not a policy. For each of P04, P09 and PLANNER
the complete v1.2 stage-local material is reconstructed from v1.3 authority and
compared component by component; the boundary is carried forward only because
the reconstruction reproduces the frozen hash exactly. Recomputing a boundary
whose meaning did not change would be as much a defect as carrying one forward
silently.

P07 is the interesting case. Its own case, binding, fixture and split material
is *unchanged* — the same proof shows that. It gets a new boundary because the
v1.2 P07 boundary was the generic one: it bound no materializer, no schema and
neither Phase 9B.6 companion artifact, so a change to P07 field authority could
not invalidate it. v1.3 adopts both companions and binds them.

Global benchmark boundary:
`sha256:d0093979d4db2f65b2442ad94ccea67b959e06af035651e2b951ad2466d4b363`

## The P06 instrument

71 executable routes (43 CORE, 27 HELD_OUT_CONFIRMATION, 1 SMOKE) over 69
candidate-scoring properties, with 56 coverage-debt exclusions. Every route
resolves to exactly one declared authorized construct under the fail-closed
resolver, and every binding independently re-verifies as `ALIGNED`.

The derived scoring set is a strict subset of the v1.2 hand-audited one: 69 of
75, 6 removed and none added. The repaired resolver can only ever narrow
scoring eligibility.

Semantic denominators and the failures each split tolerates:

| Split | Applicable properties | Max confirmed MODEL_FAILURE | Bar |
| --- | --- | --- | --- |
| SMOKE | 1 | 0 | 0.80 |
| CORE | 41 | 2 | 0.95 |
| HELD_OUT_CONFIRMATION | 27 | 1 | 0.95 |

Support-status opportunities among the 69 scoring properties: `SUFFICIENT` 31,
`PARTIAL` 5, `INSUFFICIENT` 38, `UNCERTAIN` 0. These are opportunities, not a
partition — 5 properties assert more than one status.

## The N3 axis

Census, derived from the ratified `PROMPT_INJECTION_NOISY` tag and the frozen
held-out partition: 10 exposures total, 7 on the qualification side, 3 held
out. `N3_SAFETY_SMOKE` takes 1 (qualification-side only), `N3_CORE` the
remaining 6, `N3_HELD_OUT_CONFIRMATION` all 3 held-out exposures and nothing
else.

9 contractual rules are extracted from the live executable prompt
`P06_EVIDENCE_MAP_V1@1.1.6`; a prompt revision that drops a clause fails rule
extraction rather than citing an obligation the product stopped stating.

**A finding worth stating plainly.** None of the ten NOISY submissions carries
an executable v1.3 P06 semantic route — four had their P06 properties excluded
by the fail-closed resolver and six state no P06 property at all. So the N3
gate cannot ride an existing candidate call: it needs its own P06 provider
calls, budgeted separately. The Phase 9B.7 decision-matrix cell that read "No
provider-call change" was prose about the semantic budget; it is not true of
the total.

## Ordering

1. semantic SMOKE and the qualification-side checks
2. `N3_SAFETY_SMOKE`
3. semantic CORE and `N3_CORE`
4. select the lowest qualifying rung — reading only stages 1–3
5. held-out confirmation, for that one already-selected configuration
6. record the confirmation outcome

Held-out may confirm, reject or block. It may not select a rung or a candidate.
`rung_escalation_proof()` executes this: selection returns the same rung whether
or not a held-out failure exists, passing held-out material into selection
raises, the N3 selection-side aggregator refuses a held-out exposure, and
held-out confirmation reports `may_fall_back_to_another_rung: false`. A confirmed
held-out failure requires a new pre-execution cycle, never an escalation to
XHIGH or MAX.

## Candidates

Unchanged from v1.2 and proved byte-identical: P04 on `gpt-5.6-terra`
HIGH → XHIGH; P06, P07 and P09 on `gpt-5.6-luna` HIGH → XHIGH → MAX. No
cross-family fallback, no Sol. The matrix hash still moves —
`sha256:ee4efdbe7469c70ae1c61498f49dc60cfd670275253fdbb6b91d72a6c7ca3d19` —
because the matrix binds the qualification protocol and the global boundary and
both changed.

## Hashes an auditor will want

| Artifact | Internal material hash |
| --- | --- |
| qualification protocol 1.3.0 | `sha256:03f8c7400d2d465d9f717cbee4c327aa1c0cf3c7c65edc8c340d34f62efc73b2` |
| adjudication protocol 1.3.0 | `sha256:7bc7532e602ba525e3260e4bc74cad42e03cbc30e8aed086be38f24d7ca36465` |
| N3 contractual hard-safety axis | `sha256:a3a3118ff3e02d918b16d1c312493a2beaffabd1951d98b6de52fa40c5d0fc67` |
| N3 contractual policy authority | `sha256:ab909f23ed43e61a727c19735583ce64daf46ab78134cf57dabc6695df2f0947` |
| P06 field authority | `sha256:8491038d70480afa06621917b126f26825797c0ab6f4220c7c77685d99988d57` |
| P07 field authority | `sha256:991509f72917a515bdea0f8da0b2d7aeacce5cc71d0b774516a72205a48b0b7d` |
| stage boundaries | `sha256:9f932e1771a9312d4f4d42c1a9c40e9c6a0018f940cf0f838ecfd0d8750b95b2` |
| pre-results freeze (material) | `sha256:efd0c4c41b449f86395a82a6750e10d80f86870499c74d362a6b8612ff95d7e5` |

Three kinds of hash appear in this package and are never conflated: the
**internal material hash** over canonical JSON (what a boundary compares), the
**file SHA-256** over the bytes on disk, and the **Git blob SHA** — sha1 over
`blob <len>\0` plus those bytes. `reports/semantic_benchmark/v1_3/phase9/freeze_hash_manifest.json`
lists all three side by side for every generated file.

## Rebuilding

```bash
python scripts/freeze_semantic_benchmark_v13.py
```

The script refuses to write if two builds disagree. It depends on no process
working directory, no untracked file and no previously generated output.
