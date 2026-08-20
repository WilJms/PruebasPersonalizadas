# Phase 9B.8D — semantic-benchmark/1.3.4

**Status: `PREEXECUTION_FREEZE_CANDIDATE`**

`semantic-benchmark/1.3.3` remains byte-preserved historical evidence and is
superseded for pre-execution qualification. No provider or adjudicator ran
against it. A fresh offline audit found two executable N3 collection defects:

1. selection-side aggregation could treat unknown verdicts, repeated IDs or
   foreign IDs as a complete population when the row count happened to match;
2. held-out confirmation could pass the exact held-out ID set when its verdicts
   were outside the closed N3 vocabulary.

## Minimal repair

Both `n3_rung_aggregate()` and `n3_held_out_confirmation()` now pass their rows
through one validation concept before any count, clearance, promotion or
qualification is derived:

`EXACTLY_ONE_VALID_ADJUDICATION_ROW_PER_EXPECTED_STAGE_EXPOSURE`

It requires the identity and verdict fields, the existing three-value verdict
vocabulary, no duplicates, no foreign IDs, no missing IDs, exact observed-set
equality, and exactly one row per expected exposure. Malformed collections
raise `N3ProtocolError`; they are not normalized into an outcome.

The expected IDs come from the frozen stage authority, not merely a caller
count:

| Stage | Frozen exposure count | Role |
| --- | ---: | --- |
| `N3_SAFETY_SMOKE` | 1 | selection-side preregistered subset |
| `N3_CORE` | 6 | all remaining qualification-side exposures |
| `N3_HELD_OUT_CONFIRMATION` | 3 | all and only held-out exposures |

The three contractual verdicts remain unchanged. N3 remains outside
`accepted_semantic_rate` and does not create an eighth semantic result state.

## Carry-forward and transitive change

The corpus package hash remains
`21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1`.
The 71 P06 routes, 69 candidate-scoring properties, U3 status scope, semantic
bars, candidate identities, provider fixture inputs, call budget and construct
sampling rule remain unchanged. Eight complete artifacts are republished
byte-identically from 1.3.3 and are verified in
`semantic_carry_forward_equality_proof.json`.

The executable N3 source hash and N3 axis move. Consequently the P06 stage
boundary, stage-boundaries document, global boundary, qualification protocol,
version-bound semantic claim, candidate matrix, lineage, scans, freeze and
manifest move. P04, P07, P09 and PLANNER stage hashes remain unchanged.

## Frozen hashes

| Kind | Value |
| --- | --- |
| Global benchmark boundary internal material hash | `sha256:935af3730da45a358ef360deb45f41c172aed847d5df9b81c0889178c9d2ef4d` |
| N3 executable source file SHA-256 | `sha256:3ddf72ad2f6fa22c521680c55ee617b0b0d8496d9d4595b49a72ad766eea94c5` |
| N3 axis internal material hash | `sha256:2a2ae98be319ef12b6adc821ce6c86ea5895021d1dac441a92d285793976ea70` |
| Qualification protocol internal material hash | `sha256:f01803673b46318a8dc0c493c5c76587d73d91421cd87bfaa64f9805650c3f39` |
| Pre-results freeze internal material hash | `sha256:c6b1d55f11352bf51276f5d7ea3ec416baa201c12b5b5778c27e99f94ff12eaf` |
| Pre-results freeze file SHA-256 | `sha256:208a39fc65826de1d99fab94e5fd52890ce318c30409d67c40f4abe4495640ec` |
| Pre-results freeze Git blob SHA | `4f3cc31059d2b72741dabb60209cd8b687cf9817` |

The manifest uses an explicit `path -> self_material_hash_field` registry. It
never infers a self hash from the first field ending in `_hash` and reports
internal material hashes, exact-file SHA-256 values and Git blob SHAs as three
distinct kinds.

## Offline reproduction

```bash
.venv/bin/pytest -q \
  tests/test_phase9b8d_n3_fail_closed.py \
  tests/test_phase9b8d_v134.py \
  tests/test_phase9b8c_v133.py
.venv/bin/python scripts/freeze_semantic_benchmark_v134.py
```

Provider calls, adjudicator calls and credential resolutions remain zero. Real
provider transport is false; pricing refresh and HIGH SMOKE were not performed;
billable authorization is `NONE`.

## Deferred debt

This repair does not address U3 readiness-binding hardening, the
polarity-insensitive P06 support-status census, or the offline provider SDK
import surface.
