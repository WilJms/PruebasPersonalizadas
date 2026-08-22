# Phase 9B.8E — semantic-benchmark/1.3.5

**Status: `PREEXECUTION_FREEZE_CANDIDATE` — construction only; not a fresh audit or PASS.**

This successor preserves every byte of `semantic-benchmark/1.3.4` and closes
only the five reconciled pre-execution convergence blockers. No provider or
adjudicator outcome informed the construction, and this freeze grants no
authorization to execute either one.

## Closed blocker classes

1. **N3 exposure/run identity.** The consolidated verdict and blind packet now
   carry `(exposure_pseudonym, run_index)`. `run_index` is an integer in the
   frozen range `1..SEMANTIC_K`; callers cannot supply `k`. The exact required
   populations are 3 rows for `N3_SAFETY_SMOKE`, 18 for `N3_CORE`, and 9 for
   `N3_HELD_OUT_CONFIRMATION`. Any confirmed run dominates, otherwise any
   indeterminate run blocks, and only an all-clear Cartesian population clears.
2. **One N3 authority.** Every active `n3_axis_hash` is derived from the same
   current axis object. Publication recursively verifies all active occurrences
   before checking document self-hashes, so a stale nested protocol binding
   fails closed.
3. **Complete executable prompt binding.** P04, P06, P07 and P09 each bind the
   complete live `PromptSpec.prompt_hash`, prompt/system identities, input and
   output contract names, and the strict provider-output schema hash. The prompt
   set is transitive through stage boundaries, the global boundary, the
   candidate execution contract, matrix, protocol and freeze. The authoritative
   pre-call guard validates both frozen self-hashes and live registry equality
   before it may invoke a transport factory.
4. **Production-shaped P06 requests.** The 71 executable routes are grouped
   into 45 submission requests through the real `EvidenceMapRequest`, approved
   `AssessmentBlueprint`, alias-envelope builder and materializer: 23 groups
   have one route and 22 have multiple routes. D/V/T counts share the exact
   distribution `{1: 23, 2: 18, 3: 4}`. The qualification denominator remains
   71 property observations, of which the same 69 are candidate-scoring. Each
   evaluator-only observation points back to its route inside a shared provider
   request, so a structurally omitted expected route can become `MODEL_FAILURE`
   without exposing an expected status or oracle to the model.
5. **Fail-closed rung collections.** Selection validates known unique rung IDs,
   a contiguous frozen-ladder prefix and predecessor rejection before any
   deeper rung can exist. Input order is irrelevant; held-out material remains
   outside selection.

## Frozen counts and boundaries

- P06 submission groups by split: `SMOKE=1`, `CORE=26`,
  `HELD_OUT_CONFIRMATION=18`.
- P06 property observation units by split: `SMOKE=2`, `CORE=42`,
  `HELD_OUT_CONFIRMATION=27`.
- N3 provider/adjudicator unit: `EXPOSURE_RUN`; ten fixture requests bind thirty
  preregistered run identities. Provider request hashes themselves are unchanged
  from v1.3.4.
- Global benchmark boundary:
  `sha256:ff6988324a9bd5cd1c4167b0589f8700f19985fca7ef021d0eb5dcfb875fffe5`.
- N3 axis:
  `sha256:0add76d694432b3a8cc7f53a2f6e0d4cef10aa69e893121a638d7d8ffa8c6eec`.
- Executable prompt authority:
  `sha256:820396b80101c79478e6cd1b9914a6cae6931dc055c1199e9e533bc3c6e2c3e9`.
- Candidate execution contract:
  `sha256:ae260e18b6b0a6918d923ce304ead3869afd767d553828591aa33f1d283d04a5`.
- Call budget:
  `sha256:f0ed55246d56362b170aa0b2e29f99f4d1f1660f5f16b90751cc298d18b69dde`.
- Qualification protocol:
  `sha256:711e8f42c13cadab4707b153bb5e987c56330fc9b112a349eaf8330d2dab41cc`.

The hash manifest keeps `INTERNAL_MATERIAL_HASH`, `FILE_SHA256` and
`GIT_BLOB_SHA` separate. The pre-results freeze's three corresponding values
are:

- internal material:
  `sha256:c2c2a552780c0cea7af5f7b3097da115de6fc6ee84cdbdfd9ad9943f8d655126`;
- serialized file:
  `sha256:92a8bc58411943afeefdbd26ee3b8c67aedf98428780af95cc98052ad7bd3880`;
- Git blob: `5d3ebbf68a66209614654f136ba7253801e97a1c`.

## Safety state

`provider_calls=0`, `adjudicator_calls=0`, `credentials_resolved=0`, real
transport is false, pricing refresh is `NOT_PERFORMED`, HIGH SMOKE is
`NOT_EXECUTED`, and billable authorization is `NONE`. A separate fresh audit is
still required before any qualification decision; this construction is not
such an audit.
