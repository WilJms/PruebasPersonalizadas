# semantic-benchmark/1.2.0 — repaired P06 qualification instrument

> **Status: HISTORICAL.** Phase 9B.5 falsified this instrument *before* any v1.2
> provider execution, and Phase 9B.6 reproduced every structural blocker. Its
> P06 portion must not be used to qualify a candidate. The frozen bytes below
> are preserved exactly as evidence and still reproduce; the sections that
> describe how v1.2 *worked* are left intact for that reason, including the
> `UNIQUE_NAME_PREFIX` rule in step 2, which is the defect itself and has been
> removed from the repaired resolver. Read
> [PHASE9B6_STRUCTURAL_REMEDIATION.md](PHASE9B6_STRUCTURAL_REMEDIATION.md)
> first. Verdict: `PHASE9B6_PRODUCT_DECISION_REQUIRED`.

- benchmark version: `semantic-benchmark/1.2.0`
- global benchmark boundary: `sha256:0855817997b64fa2357539877978b52140e1e78a949d7c830ef4f70d19e7fe79`
- Phase 9 protocol: `phase9-qualification-protocol/1.2.0`
- protocol boundary: `sha256:1de8ec9c0359a97784a07a27ccd9a454d895559a59cb34cb6df1154890cf7d82`
- adjudication contract: `phase9-adjudication-protocol/1.1.0`
- corpus package boundary: `21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1` (unchanged)

`semantic-benchmark/1.1.0` is preserved as historical evidence with boundary
`sha256:426dda4d…`. It is **SUPERSEDED_AFTER_P06_VALIDITY_AUDIT**, and its P06
portion is **P06_NOT_VALID_FOR_CONTINUED_MODEL_SELECTION**. The defect was not
known before v1.1 executed; it was found afterwards, by the Phase 9B.3 audit.

## Why v1.1 P06 could not continue

Two structural defects, both found by Phase 9B.3.

**A — route semantics came from evidence location.** The v1.1 generator built a
construct as `f"{coarse_family}: {first_source_ref_section}"`, so a route read
`Relación entre afirmación y evidencia: párrafo 2`. That names *where* evidence
sat, not *what* was being verified. Two different rubric criteria on one
submission could therefore collapse into the same generic claim/evidence family
— and did, for `A06-S02-P1` and `A06-S02-P2`.

**B — the blind adjudication surface carried no stage authority.** A reviewer
could not tell which semantic route the candidate saw, nor which canonical
output fields the provider owned, so the Phase 9 MODEL_FAILURE conditions were
unanswerable without guessing the architecture.

## How v1.2 derives a P06 route

The ratified corpus states a P06 property's target criterion explicitly, in
quotes: `INSUFFICIENT para 'Variables y medidas'`. The target construct is
therefore *declared* by the authorized source chain, not inferred from prose.

1. **Construct catalog** — real parser output over each activity's own
   `02_rubric.docx` criteria/dimension table, falling back to the assignment's
   `Tarea` requirements where the rubric is informal prose. 60 constructs across
   12 activities.

   > **Phase 9B.6 correction — activities 05 and 12.** These two activities end
   > up with zero executable P06 routes, and the informal-rubric fallback is
   > *not* the cause. Both rubrics are informal prose, and for exactly that
   > reason both fall back to `Tarea` and each obtains **four**
   > `ASSIGNMENT_REQUIREMENT` catalog constructs — so the authorized construct
   > space is present, named and source-grounded. The operative cause is
   > downstream: their P06 properties do not resolve unambiguously to those
   > source construct *names*. Under the repaired fail-closed resolver, A05
   > loses 6 properties to `NO_DECLARED_AUTHORIZED_CONSTRUCT` and 1 to
   > `AMBIGUOUS_AUTHORIZED_CONSTRUCT_REFERENCE`; A12 loses 12 and 1. The
   > `NO_PRODUCTION_REPRESENTATIVE_P06_CONSTRUCT` disposition — whose reason
   > text reads "the activity exposes no structured authorized construct" —
   > fires only on an *empty* catalog and is emitted for no property in v1.2.
   > Reading it as the explanation for A05/A12 would be wrong. No inferred
   > route is created to give these activities coverage.
2. **Declarative resolution** — a property resolves only if it *names* a catalog
   construct, by exact folded name, leading label (`D1.`), or unique
   word-boundary prefix. Anything else fails closed.
3. **Route from the construct alone** — the model-visible route is a pure
   function of the catalog entry plus the submission's evidence modalities.
4. **Submission evidence location stays evaluator-side** — the model receives
   the whole submission bundle and locates the supporting evidence itself. No
   *submission* evidence location is projected into the route.

   > **Phase 9B.6 correction.** An earlier wording of this line said "No
   > location is projected into the route", which is false as stated. Several
   > rubrics define a criterion partly through an authorized descriptor column
   > headed `Dónde debería poder comprobarse`, and that column is part of the
   > criterion's own definition, so it does reach `construct_description` and
   > therefore the model. For example the A04 route for `Una aparición inválida
   > no reserva el id` carries `[Dónde debería poder comprobarse] Orden entre
   > validación y deduplicación`. That is authorized rubric text, not oracle
   > leakage, and it is deliberately **not** removed: stripping it would delete
   > authorized source semantics the real product also shows. The claim that
   > holds is the narrower one above — the route never says where *this
   > submission's* evidence sits.

Route count is not a target: 127 → **77** (46 qualification, 31 held-out). A
smaller valid benchmark is preferable to a larger invalid one.

## Production representativeness

Every model-visible field travels the real production path:

```
AssessmentBlueprint → BlueprintDimension → EvidenceVariant
  → QuestionOpportunityTemplate → EvidenceMappingAliasEnvelope
```

The envelope is produced by the product's own
`build_evidence_mapping_alias_envelope`. `_production_projection` asserts each
model-visible value is reachable on that envelope, so the benchmark cannot
measure an easier, benchmark-only P06.

## P06 field authority

`p06_field_authority.py` derives ownership from the executable contracts, not
from output prose:

| Authority | Examples |
|---|---|
| `MODEL_OWNED` | `support_status`, `support_type`, `support_description`, `semantic_uncertainty`, `abstention_reason`, `evidence_ids` |
| `SERVER_OWNED` | `focus`, `observable`, `cognitive_operation`, canonical ids, `EvidenceVariantMatch.justification` |
| `SERVER_DERIVED_FROM_MODEL_INPUT` | `evidence_fit`, `mapping_confidence`, variant aggregate `support_status`, every `mapping_summary` count |

`SERVER_DERIVED_FROM_MODEL_INPUT` is **not** independent semantic evidence: it
restates a model decision through a deterministic server function. The constant
sentence *"Relaciones categóricas P06 materializadas por el servidor."* is
server-owned prose and can never establish field authority.

## Blind adjudication companion

`p06-adjudication-context/1.0.0` binds one companion to exactly one packet
(`packet_hash`, `fixture_id`, `case_id`, route context, field authority, P06
stage boundary). P04/P07/P09 review-packet bytes are unchanged — the companion
exists precisely so a P06-only need does not rewrite the shared schema.

## Stage boundaries

v1.2 introduces stage boundaries prospectively for `P04`, `P06`, `PLANNER`,
`P07`, `P09`. **v1.1 had none**, and no retroactive v1.1 stage boundary is
fabricated. The global boundary binds shared authority, the stage boundaries,
the corpus boundary, the split partition, cross-stage aggregation and the
qualification disposition authority.

## Thresholds, safety and debt

Bars are unchanged (SMOKE 0.80, CORE 0.95, HELD_OUT 0.95). Absolute allowances
are recomputed mechanically as `floor(applicable × (1 − bar))`:

| Split | applicable | max confirmed MODEL_FAILUREs |
|---|---|---|
| SMOKE | 1 | 0 |
| CORE | 43 | 2 |
| HELD_OUT_CONFIRMATION | 31 | 1 |

Hard-safety policy is unchanged at zero permitted confirmed MODEL_FAILUREs.
What changed is **exposure**: 9 safety-tagged properties lost their route to
fail-closed resolution and are recorded as `SAFETY_COVERAGE_DEBT` rather than
kept alive by a fabricated route.

54 P06 properties are excluded overall: 50 with no unambiguous stage-local
construct, 2 activity-coverage index statements, 1 cross-submission consistency
assertion, 1 already `NOT_APPLICABLE`.

`A01-S01-P3` names no authorized construct and is suspended from SMOKE; no
replacement was added. P06 SMOKE therefore retains one property, `A01-S03-P1`.

## Qualification dispositions vs. the corpus

`qualification_oracle_dispositions.json` records, per property, the original
oracle state, kind and description hash alongside the v1.2 disposition and
whether candidate scoring is allowed. **Corpus bytes are never edited.** A
qualification disposition says what this instrument may score; it does not
rewrite what the reviewer ratified.

## Reproducing

```bash
python tools/generate_semantic_benchmark_v12_definitions.py && python scripts/build_phase9_v12_protocol.py && python scripts/freeze_semantic_benchmark_v12.py
```
