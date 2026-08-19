# Phase 9B.8A — semantic-benchmark/1.3.1

**Status: `SEMANTIC_BENCHMARK_V1_3_1_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT`**

Provider calls 0, adjudicator calls 0, billable authorizations 0, credentials
resolved 0, real transport false, candidate outcomes read false, pricing
refresh false. HIGH SMOKE not authorized.

`semantic-benchmark/1.3.0` is marked
`SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED` and its bytes are
untouched. No provider or adjudicator ever ran against it, so this is a
pre-execution instrumentation repair — not result-driven tuning, not a corpus
change, and not a change to any accepted product decision. U3, the N3
architecture, N3's exclusion from `accepted_semantic_rate`, UNCERTAIN as
residual risk, held-out as confirmation-only and the no-cross-family-fallback
rule all stand exactly as accepted.

Every number below is checked against the machine by
`tests/test_phase9b8a_document.py`.

## What was wrong with 1.3.0

**The N3 provider call had no frozen shape.** 1.3.0 correctly derived that N3
needs its own P06 provider calls — no NOISY submission carries an executable
semantic route — but froze no request for them. Nothing defined which construct
each call targets, what the model-visible envelope contains, or what the request
hashes to. A gate whose request is decided at run time is a gate whose exposure
can be changed after a result is seen.

**The hash manifest reported dependency hashes as self hashes.** It picked an
artifact's "internal material hash" by scanning for the first field whose name
ended in `_hash`. For the candidate matrix and the qualification protocol that
found `benchmark_boundary_hash` — a dependency — and printed it as the
document's own hash. Two of twenty-five entries were wrong, and both wrong
values were the same global boundary hash.

## The construct-selection rule

Each exposure needs one authorized construct. The rule is
`FIRST_AUTHORIZED_CONSTRUCT_IN_CANONICAL_SOURCE_ORDER`: the earliest construct
in the activity's authorized construct source document, ordered by that
document's own structure — source document, then table index, then row, then
list-unit index.

Every component comes from the assignment or rubric the instructor wrote. Each
of the ten NOISY activities draws its constructs from exactly one source
document, so no cross-document precedence had to be invented, and the order is
total — a tie raises rather than being broken by accident.

This is deliberately **not** "the first construct by key". That would be a
lexical accident, and the two rules disagree for 6 of the 10 activities.

Independence is executed, not asserted:
`reports/semantic_benchmark/v1_3_1/phase9/construct_selection_independence.json`
perturbs injection text, submission evidence text, NOISY outcome markers,
oracle/expected-status flags and candidate-verdict flags, and reverses the
catalog input order — the selection does not move under any of them. The
converse probe reverses source order and all 10 selections move, so the rule
demonstrably reads what it claims to read.

## The ten frozen fixtures

| Fixture | Split | Construct | Evidence units |
| --- | --- | --- | --- |
| N3F-act_01_luz_y_plantines-submission_01 | N3_SAFETY_SMOKE | AFIRMACION_Y_ALCANCE | 6 |
| N3F-act_02_voz_en_un_microcuento-submission_02 | N3_CORE | TESIS_INTERPRETATIVA | 6 |
| N3F-act_04_asignador_de_turnos-submission_04 | N3_CORE | DESCARTA_REGISTROS_CON_CAMPO_FALTANTE | 11 |
| N3F-act_05_visitas_a_bibliotecas-submission_05 | N3_CORE | CALCULA_VISITAS_POR_DIA_ABIERTO… | 55 |
| N3F-act_06_movilidad_estudiantil-submission_06 | N3_CORE | TESIS_Y_OBJETIVO | 6 |
| N3F-act_07_aislamiento_termico-submission_01 | N3_HELD_OUT_CONFIRMATION | CRITERIO_DE_COMPARACION | 16 |
| N3F-act_08_triage_de_logs-submission_02 | N3_CORE | LINEA_TEMPORAL_Y_CORRELACION | 12 |
| N3F-act_09_renovacion_y_desplazamiento-submission_03 | N3_HELD_OUT_CONFIRMATION | TESIS_EXPLICATIVA | 44 |
| N3F-act_11_duplicados_en_pagos-submission_05 | N3_CORE | CADENA_CAUSAL | 15 |
| N3F-act_12_clinica_movil-submission_06 | N3_HELD_OUT_CONFIRMATION | ASIGNA_LAS_DOS_JORNADAS… | 13 |

Derived counts: 10 total, 1 SAFETY_SMOKE, 6 CORE, 3 HELD_OUT_CONFIRMATION —
taken from the fixture set and cross-checked against the frozen stage plan, not
written down.

Fixture-set hash
`sha256:f53ec77ae4c26732644083d10497e65e1a1bc34f830e675aa4848669d106c62d`.

All ten conditions of the production-representativeness standard are executed
against every fixture using the real product code: the request re-validates as
an `EvidenceMapRequest`, the prompt is `P06_EVIDENCE_MAP_V1@1.1.6`, the
construct is in the authorized catalog, no benchmark-only construct is created,
no golden is required, no P04 candidate output is consumed, the whole submission
bundle projects through the production alias envelope with all seven surfaces
represented, every projected text is verbatim corpus text, a schema-valid
response materializes through the real materializer, and the request rebuilds
identically.

The request does carry a `blueprint` — that is the production P06 input DTO, not
a P04 output. It is synthesized from the authorized construct and the corpus
bundle, its identifiers are route-derived, and no P04 artifact is named anywhere
in it.

## The 4 / 6 disposition, now derived

`noisy_exposure_count` 10, `noisy_with_executable_semantic_route_count` 0,
`noisy_with_p06_property_but_excluded_count` 4,
`noisy_with_no_p06_property_count` 6. The three classes are required to
partition the population exactly, and the sentence that used to be typed by hand
is generated from those fields.

## Boundaries

| Stage | Status | Hash |
| --- | --- | --- |
| P04 | carried forward from 1.3.0 | `sha256:b0ade4a135d1a5d5fb63570953746715e111840b854411b2a79d4b3e8d3f5417` |
| P06 | new in 1.3.1 | `sha256:46c86246a11b73ed6f2c9ea6e84bd68150393c356cc77e2f06018b1c0e332804` |
| P07 | carried forward from 1.3.0 | `sha256:889a2498ddd0194a641f796ed4c82686318602a29a0f5bb2729686dc7690854f` |
| P09 | carried forward from 1.3.0 | `sha256:090b17302b711c19ce1067e0c0c041ec29d5d337b4cb462c5a476bb84c5fb926` |
| PLANNER | carried forward from 1.3.0 | `sha256:961384f7f9c25601b5aea91217849be79400517d7b5960924c79789c93687376` |

P06 is new because it now binds the fixture-set hash, the per-exposure request
hashes, the selection authority and its independence proof, the request
construction source, the fixture builder and the representativeness proof. The
other four are carried forward only after their complete 1.3.0 material is
reconstructed component by component and reproduces the frozen hash — P07's
1.3.0 boundary is recomputed in full, and P04/P09/PLANNER's carried v1.2
material is reconstructed.

Global boundary
`sha256:981ee8f47928b653a5cf62cb6c305cc767cb37ae88f5611de106bee039212976`.

## Budget

N3 provider calls are now `executable frozen fixtures × k` per rung and split —
not `exposure_count × k`. The distinction is the point: an exposure whose
request does not build would otherwise cost nothing.

Provider: semantic 345 at HIGH / 1014 worst case / 240 held-out; N3 21 at HIGH /
63 worst case / 9 held-out. Adjudicator, kept separate: semantic first-pass 516
at HIGH / 1473 worst case / 378 held-out; N3 21 / 63 / 9. No pricing refresh.

## The repaired manifest

`SELF_MATERIAL_HASH_FIELD` names each artifact's self-hash field explicitly, and
`self_material_hash()` then *verifies* the claim:
`canonical_hash(document minus that field)` must equal the field's value. A
dependency hash copied in from another artifact cannot satisfy that. Every
generated path must be registered and every registered path generated; a
mismatch in either direction stops the build.

All 12 entries now carry the document's own hash, including the two that
were wrong:

- `manifest(candidate_matrix).internal_material_hash == candidate_matrix.candidate_matrix_hash`
- `manifest(qualification_protocol).internal_material_hash == qualification_protocol.protocol_boundary_hash`
- `manifest(call_budget).internal_material_hash == call_budget.call_budget_hash`
- `manifest(n3_axis).internal_material_hash == n3_axis.n3_axis_hash`
- `manifest(pre_results_freeze).internal_material_hash == pre_results_freeze.freeze_material_hash`

The manifest excludes itself, and says so in `manifest_excludes_itself` with the
reason: it is written after the artifacts it describes, so an entry for its own
bytes could not exist when it is built. Its own file SHA-256 and Git blob SHA are
printed by the freeze script and recoverable with `sha256sum` and
`git hash-object`.

## Rebuilding

```bash
python scripts/freeze_semantic_benchmark_v131.py
```

The script refuses to write if two builds disagree or if the self-hash registry
is out of sync with the generated package. It depends on no working directory,
no untracked file and no previously generated output.
