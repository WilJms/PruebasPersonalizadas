"""Frozen provider-facing P06 fixtures for the ten N3 exposures (Phase 9B.8A).

Phase 9B.8 established that the N3 contractual hard-safety gate cannot ride an
existing candidate call: not one of the ten ratified ``PROMPT_INJECTION_NOISY``
submissions carries an executable v1.3 P06 semantic route.  N3 therefore buys
its own P06 provider calls -- and the moment that is true, *what those calls
send* stops being an implementation detail and becomes qualification authority.
A gate whose request shape is decided at run time is a gate whose exposure can
be changed after seeing a result.

So this module freezes, per exposure, the exact provider-facing request: the
authorized construct it targets, that construct's provenance back to the
assignment or rubric the instructor wrote, the model-visible alias envelope, the
canonical request hash, the prompt identity and the production-projection proof.

**The selection rule.**  Each exposure needs one authorized construct.  Choosing
"the first" by ``construct_key`` would be a lexical accident, not authority, so
the rule here is *canonical source order*: the earliest construct in the
activity's authorized construct source document, keyed by that document's own
structure -- table index, then row, then list-unit index.  Every component comes
from the product source.  Each of the ten NOISY activities draws its constructs
from exactly one source document, so no cross-document precedence has to be
invented, and the order is total: no ties are possible or tolerated.

The rule reads ``source_refs`` and ``provenance`` and nothing else.  It never
looks at where an injection sits, what it says, how a candidate answered, what
the oracle expects, or any historical benchmark result -- and
:func:`selection_independence_proof` demonstrates that by perturbing exactly
those inputs and showing the selection does not move.

Nothing here executes a provider or an adjudicator, resolves a credential,
constructs a real transport or reads a candidate outcome.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_hash
from .contracts import models as m
from .evidence_mapping import (
    evidence_mapping_materializer_boundary,
    p06_alias_envelope_schema_boundary,
)
from .p06_noisy_contractual_gate import P06_PROMPT_ID
from .p06_n3_protocol import (
    HELD_OUT_SIDE,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_RUNS_PER_EXPOSURE,
    N3_SAFETY_SMOKE,
    P06_SMOKE_ACTIVITY_IDS,
    QUALIFICATION_SIDE,
    V12_SPLIT_PARTITION_PATH,
    n3_exposure_population,
    n3_safety_smoke_selector,
    n3_stage_plan,
)
from .model_gateway.registry import prompt_spec
from .semantic_benchmark import DEFAULT_CORPUS_ROOT, load_corpus_package
from .semantic_benchmark_fixtures import parse_submission_bundle
from .semantic_benchmark_v12 import (
    P06_FIXTURE_BUILDER_V12_VERSION,
    build_construct_catalog,
    build_p06_fixture_v12,
    model_visible_definition_for,
)
from .semantic_benchmark_v12_boundary import _production_projection


N3_PROVIDER_FIXTURES_VERSION = "n3-provider-fixtures/1.3.1"
N3_PROVIDER_FIXTURES_V135_VERSION = "n3-provider-fixtures/1.3.5"

#: The construct-selection rule, named so a reader can check the code against
#: the claim rather than against a comment.
N3_CONSTRUCT_SELECTION_RULE = "FIRST_AUTHORIZED_CONSTRUCT_IN_CANONICAL_SOURCE_ORDER"

#: What the selection rule is forbidden to consult.  Each entry is exercised by
#: :func:`selection_independence_proof`.
N3_SELECTION_FORBIDDEN_INPUTS: tuple[str, ...] = (
    "INJECTION_LOCATION",
    "INJECTION_TEXT",
    "SUBMISSION_EVIDENCE_TEXT",
    "NOISY_OUTCOME",
    "CANDIDATE_OUTPUT",
    "ORACLE_PROPERTY_OR_EXPECTED_SUPPORT_STATUS",
    "HISTORICAL_BENCHMARK_RESULT",
    "P04_CANDIDATE_OUTPUT",
)

#: The candidate family the P06 side is assigned.  Stated for the fixture row;
#: no candidate is executed here.
N3_EXPECTED_CANDIDATE_FAMILY = "gpt-5.6-luna"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class N3ProviderFixtureError(ValueError):
    """Raised when the frozen N3 provider fixture set is unsound."""


# --------------------------------------------------------------------------
# The selection rule
# --------------------------------------------------------------------------


def source_order_key(construct: Mapping[str, Any]) -> tuple[str, int, int, int]:
    """Position of a construct inside its authorized source document.

    Derived entirely from the document the instructor wrote: which file it came
    from, which table, which row, which list item.  Nothing about a submission,
    an injection or a result contributes.
    """

    refs = construct["source_refs"]
    if not refs:
        raise N3ProviderFixtureError(
            f"{construct['construct_key']} has no authorized source reference"
        )
    document = refs[0].split("#", 1)[0].split("/")[-1]
    provenance = construct["provenance"]
    return (
        document,
        int(provenance.get("table_index", 0)),
        int(provenance.get("row", 0)),
        int(provenance.get("unit_index", 0)),
    )


def select_construct(
    constructs: Sequence[Mapping[str, Any]], *, activity_id: str
) -> dict[str, Any]:
    """Return the activity's first authorized construct in source order.

    Fails closed on an empty catalog and on any tie: a tie would mean the source
    document does not in fact order the two constructs, and the rule would be
    completing that order by accident rather than reading it.
    """

    rows = [item for item in constructs if item["activity_id"] == activity_id]
    if not rows:
        raise N3ProviderFixtureError(
            f"{activity_id} declares no authorized construct; no N3 provider "
            "request can be built without inventing one"
        )
    keys = [source_order_key(item) for item in rows]
    if len(set(keys)) != len(keys):
        duplicated = sorted(key for key, count in Counter(keys).items() if count > 1)
        raise N3ProviderFixtureError(
            f"{activity_id} has constructs the authorized source does not order: "
            f"{duplicated}"
        )
    documents = {key[0] for key in keys}
    return {
        **dict(min(rows, key=source_order_key)),
        "_selection": {
            "rule": N3_CONSTRUCT_SELECTION_RULE,
            "candidate_construct_count": len(rows),
            "source_documents": sorted(documents),
            "single_source_document": len(documents) == 1,
            "order_key_fields": [
                "source_document",
                "table_index",
                "row",
                "unit_index",
            ],
            "order_is_total": True,
        },
    }


# --------------------------------------------------------------------------
# The frozen fixtures
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class N3FixtureBuild:
    fixtures: tuple[dict[str, Any], ...]
    requests: tuple[Any, ...]
    envelopes: tuple[Any, ...]
    population: dict[str, Any]
    stage_plan: dict[str, Any]


def _n3_split_for(exposure: Mapping[str, Any], smoke_ids: set[str]) -> str:
    if exposure["side"] == HELD_OUT_SIDE:
        return N3_HELD_OUT_CONFIRMATION
    return N3_SAFETY_SMOKE if exposure["exposure_id"] in smoke_ids else N3_CORE


def build_n3_provider_fixtures(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
) -> N3FixtureBuild:
    """Construct the provider-facing P06 request for every N3 exposure."""

    package = load_corpus_package(corpus_root)
    catalog = build_construct_catalog(corpus_root)
    population = n3_exposure_population(corpus_root, V12_SPLIT_PARTITION_PATH)
    safety_smoke = n3_safety_smoke_selector(
        population, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    stage_plan = n3_stage_plan(population, safety_smoke)
    smoke_ids = set(safety_smoke["exposure_ids"])

    spec = prompt_spec(P06_PROMPT_ID)
    materializer = evidence_mapping_materializer_boundary()
    alias_schema = p06_alias_envelope_schema_boundary()

    fixtures: list[dict[str, Any]] = []
    requests: list[Any] = []
    envelopes: list[Any] = []

    for exposure in sorted(
        population["exposures"], key=lambda item: item["exposure_id"]
    ):
        activity_id = exposure["activity_id"]
        submission_id = exposure["submission_id"]
        activity = package.activity_by_id[activity_id]
        selected = select_construct(catalog["constructs"], activity_id=activity_id)
        selection = selected.pop("_selection")

        bundle = parse_submission_bundle(
            corpus_root=package.root,
            activity_path=activity["activity_path"],
            activity_id=activity_id,
            submission_id=submission_id,
            artifact_refs=list(exposure["artifacts"])
            if exposure.get("artifacts")
            else list(_artifacts_for(corpus_root, activity, submission_id)),
        )
        definition = model_visible_definition_for(selected, bundle)
        fixture_id = f"N3F-{activity_id}-{submission_id}"
        request, envelope = build_p06_fixture_v12(
            route_fixture_id=fixture_id,
            model_visible_definition=definition,
            bundle=bundle,
        )
        projection = _production_projection(envelope, definition)
        request_payload = request.model_dump(mode="json")
        envelope_payload = envelope.model_dump(mode="json")

        fixtures.append(
            {
                "n3_provider_fixture_id": fixture_id,
                "exposure_id": exposure["exposure_id"],
                "activity_id": activity_id,
                "submission_id": submission_id,
                "side": exposure["side"],
                "n3_split": _n3_split_for(exposure, smoke_ids),
                # --- the authorized construct and where it comes from
                "target_construct_key": selected["construct_key"],
                "construct_source_kind": selected["source_kind"],
                "construct_canonical_source_name": selected["canonical_source_name"],
                "construct_source_refs": list(selected["source_refs"]),
                "construct_source_hashes": dict(selected["source_hashes"]),
                "construct_provenance": dict(selected["provenance"]),
                "construct_selection": {
                    **selection,
                    "selected_order_key": list(source_order_key(selected)),
                    "depends_on_outcomes": False,
                    "forbidden_inputs": list(N3_SELECTION_FORBIDDEN_INPUTS),
                },
                # --- how the request is built
                "fixture_builder_version": P06_FIXTURE_BUILDER_V12_VERSION,
                "fixture_builder_source_hash": _source_hash("semantic_benchmark_v12.py"),
                "materializer_boundary": materializer,
                "alias_envelope_schema_boundary": alias_schema,
                "alias_envelope_hash": canonical_hash(envelope_payload),
                "model_draft_schema_hash": canonical_hash(
                    m.EvidenceMappingModelDraft.model_json_schema(mode="validation")
                ),
                # --- prompt identity
                "prompt_id": spec.prompt_id,
                "prompt_version": spec.prompt_version,
                "system_prompt_id": spec.system_prompt_id,
                "prompt_hash": spec.prompt_hash,
                # --- the request itself
                "provider_request_schema": request_payload.get("schema_version"),
                "provider_request_hash": canonical_hash(request_payload),
                "model_visible_input_identity_hash": exposure[
                    "model_visible_input_identity_hash"
                ],
                "model_visible_evidence_identity_hash": canonical_hash(
                    [
                        {
                            "evidence_alias": unit.evidence_alias,
                            "content_hash": canonical_hash(
                                {
                                    "content_text": unit.content_text,
                                    "structured_content": unit.structured_content,
                                    "artifact_alias": unit.artifact_alias,
                                    "modality": str(unit.modality),
                                }
                            ),
                        }
                        for unit in envelope.evidence_units
                    ]
                ),
                "model_visible_evidence_unit_count": len(envelope.evidence_units),
                # --- production representativeness
                "production_projection": projection,
                "route_definition_hash": canonical_hash(definition),
                # --- what a fixture may never carry
                "expected_candidate_family": N3_EXPECTED_CANDIDATE_FAMILY,
                "expected_semantic_answer": None,
                "expected_support_status": None,
                "oracle_property_id": None,
                "candidate_outcome": None,
                "consumes_p04_candidate_output": False,
                "requires_semantic_golden": False,
            }
        )
        requests.append(request)
        envelopes.append(envelope)

    return N3FixtureBuild(
        fixtures=tuple(fixtures),
        requests=tuple(requests),
        envelopes=tuple(envelopes),
        population=population,
        stage_plan=stage_plan,
    )


def _artifacts_for(
    corpus_root: Path, activity: Mapping[str, Any], submission_id: str
) -> Iterable[str]:
    ratification = json.loads(
        (Path(corpus_root) / activity["activity_path"] / "final_ratification.json").read_text(
            encoding="utf-8"
        )
    )
    for submission in ratification["submissions"]:
        if str(submission["submission_id"]) == submission_id:
            return list(submission["artifacts"])
    raise N3ProviderFixtureError(f"{submission_id} is not in the ratified corpus")


def _source_hash(name: str) -> str:
    path = Path(__file__).with_name(name)
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


# --------------------------------------------------------------------------
# PART C -- the production-representativeness standard
# --------------------------------------------------------------------------

#: The ten conditions a frozen N3 provider fixture set must satisfy.  Each maps
#: to a check executed in :func:`production_representativeness_proof`.
PRODUCTION_REPRESENTATIVENESS_CONDITIONS: tuple[str, ...] = (
    "REQUEST_VALIDATES_UNDER_THE_REAL_P06_INPUT_CONTRACT",
    "USES_THE_REAL_P06_PROMPT_AND_OUTPUT_SCHEMA",
    "EVERY_CONSTRUCT_IS_AN_AUTHORIZED_ACTIVITY_CONSTRUCT",
    "NO_BENCHMARK_ONLY_CONSTRUCT_IS_CREATED",
    "NO_SEMANTIC_GOLDEN_IS_REQUIRED",
    "NO_P04_CANDIDATE_OUTPUT_IS_CONSUMED",
    "COMPLETE_SUBMISSION_EVIDENCE_VIA_THE_PRODUCTION_PROJECTION",
    "NOISY_CONTENT_IS_MODEL_VISIBLE_WITHOUT_ADDING_OR_REWRITING_CORPUS_TEXT",
    "A_SCHEMA_VALID_RESPONSE_MATERIALIZES_THROUGH_THE_REAL_MATERIALIZER",
    "REQUEST_CONSTRUCTION_IS_OUTCOME_INDEPENDENT_AND_DETERMINISTIC",
)

#: Keys that would mean a golden or a candidate outcome leaked into a fixture.
_FORBIDDEN_FIXTURE_VALUES: tuple[str, ...] = (
    "expected_semantic_answer",
    "expected_support_status",
    "oracle_property_id",
    "candidate_outcome",
)


def _schema_valid_draft(envelope: Any) -> Any:
    """A minimally schema-valid model draft, used only to exercise the
    materializer.  It asserts no semantic answer: the status carried here is a
    structural placeholder, never a golden, and is discarded."""

    return m.EvidenceMappingModelDraft(
        scope_alias=envelope.scope_alias,
        mappings=[
            m.EvidenceMappingRelationDraft(
                variant_alias=envelope.variants[0].variant_alias,
                template_alias=envelope.templates[0].template_alias,
                evidence_aliases=[envelope.evidence_units[0].evidence_alias],
                support_status=m.EvidenceSupportStatus.PARTIAL,
                support_type=None,
                support_description="estructural",
                semantic_uncertainty=None,
                abstention_reason=None,
            )
        ],
    )


def production_representativeness_proof(
    build: N3FixtureBuild, corpus_root: Path = DEFAULT_CORPUS_ROOT
) -> dict[str, Any]:
    """Execute all ten conditions against the frozen fixtures.

    Nothing here is asserted from a comment.  Each condition runs the real
    product code -- the request contract, the prompt registry, the alias
    envelope builder, the materializer -- against every one of the ten
    fixtures, and the proof refuses to be published if one of them fails.
    """

    from .evidence_mapping import (
        materialize_evidence_mapping_draft,
        validate_materialized_evidence_mapping,
    )

    catalog = build_construct_catalog(corpus_root)
    catalog_keys = {item["construct_key"] for item in catalog["constructs"]}
    spec = prompt_spec(P06_PROMPT_ID)
    draft_schema_hash = canonical_hash(
        m.EvidenceMappingModelDraft.model_json_schema(mode="validation")
    )
    package = load_corpus_package(corpus_root)

    results: dict[str, list[str]] = {name: [] for name in PRODUCTION_REPRESENTATIVENESS_CONDITIONS}
    per_fixture: list[dict[str, Any]] = []

    for fixture, request, envelope in zip(
        build.fixtures, build.requests, build.envelopes, strict=True
    ):
        fixture_id = fixture["n3_provider_fixture_id"]
        row: dict[str, Any] = {"n3_provider_fixture_id": fixture_id}

        # 1. the real request contract, re-validated from the serialized payload
        payload = request.model_dump(mode="json")
        revalidated = m.EvidenceMapRequest.model_validate(payload)
        row["request_contract"] = type(revalidated).__name__
        ok = canonical_hash(revalidated.model_dump(mode="json")) == fixture[
            "provider_request_hash"
        ]
        _record(results, "REQUEST_VALIDATES_UNDER_THE_REAL_P06_INPUT_CONTRACT", fixture_id, ok)

        # 2. the real prompt and the real output schema
        ok = (
            fixture["prompt_id"] == spec.prompt_id
            and fixture["prompt_version"] == spec.prompt_version
            and fixture["prompt_hash"] == spec.prompt_hash
            and fixture["model_draft_schema_hash"] == draft_schema_hash
        )
        _record(results, "USES_THE_REAL_P06_PROMPT_AND_OUTPUT_SCHEMA", fixture_id, ok)

        # 3 & 4. the construct is authorized, and nothing was invented
        supplied = {fixture["target_construct_key"]}
        ok = supplied <= catalog_keys
        _record(results, "EVERY_CONSTRUCT_IS_AN_AUTHORIZED_ACTIVITY_CONSTRUCT", fixture_id, ok)
        invented = [
            ref
            for ref in fixture["construct_source_refs"]
            if not ref.startswith(f"{package.activity_by_id[fixture['activity_id']]['activity_path']}/")
        ]
        _record(
            results,
            "NO_BENCHMARK_ONLY_CONSTRUCT_IS_CREATED",
            fixture_id,
            not invented and bool(fixture["construct_source_hashes"]),
        )

        # 5. no golden
        ok = all(fixture[key] is None for key in _FORBIDDEN_FIXTURE_VALUES) and not fixture[
            "requires_semantic_golden"
        ]
        _record(results, "NO_SEMANTIC_GOLDEN_IS_REQUIRED", fixture_id, ok)

        # 6. no P04 candidate output is consumed.
        #
        # The request legitimately carries a ``blueprint`` -- that is the
        # production P06 input DTO. What matters is where it came from: a
        # P04 *candidate output* would be a model artifact, while this one is
        # synthesized from the authorized construct and the corpus bundle
        # alone. Two things establish that. The blueprint's identifiers are
        # derived from the route scope rather than from any P04 artifact id,
        # and the whole request reproduces from (construct, bundle) with no
        # P04 input available -- which condition 10 re-derives independently.
        blueprint = payload["blueprint"]
        derived_ids = [
            blueprint["blueprint_id"],
            *[item["dimension_id"] for item in blueprint["dimensions"]],
        ]
        ok = (
            not fixture["consumes_p04_candidate_output"]
            and blueprint["activity_id"] == fixture["activity_id"]
            and all(item.startswith("blueprint_p06_route") or "p06_route" in item for item in derived_ids)
            and not _references_p04_artifact(payload)
        )
        row["blueprint_id"] = blueprint["blueprint_id"]
        row["blueprint_is_route_derived_not_p04_output"] = ok
        _record(results, "NO_P04_CANDIDATE_OUTPUT_IS_CONSUMED", fixture_id, ok)

        # 7. the whole submission bundle, through the production projection
        activity = package.activity_by_id[fixture["activity_id"]]
        bundle = parse_submission_bundle(
            corpus_root=package.root,
            activity_path=activity["activity_path"],
            activity_id=fixture["activity_id"],
            submission_id=fixture["submission_id"],
            artifact_refs=list(_artifacts_for(corpus_root, activity, fixture["submission_id"])),
        )
        projected = len(envelope.evidence_units)
        available = len(bundle.evidence_units)
        # _production_projection raises unless every model-visible value is
        # reachable on the real alias envelope, so a returned projection with
        # all seven surfaces represented *is* the no-benchmark-channel proof.
        ok = (
            projected == available
            and len(fixture["production_projection"]["represented_surfaces"]) == 7
        )
        row["evidence_units_projected"] = projected
        row["evidence_units_in_bundle"] = available
        _record(
            results,
            "COMPLETE_SUBMISSION_EVIDENCE_VIA_THE_PRODUCTION_PROJECTION",
            fixture_id,
            ok,
        )

        # 8. the corpus text is projected verbatim -- nothing added or rewritten
        corpus_text = {
            unit.content_text for unit in bundle.evidence_units if unit.content_text
        }
        projected_text = {
            unit.content_text for unit in envelope.evidence_units if unit.content_text
        }
        ok = projected_text <= corpus_text
        row["projected_text_is_verbatim_corpus"] = ok
        _record(
            results,
            "NOISY_CONTENT_IS_MODEL_VISIBLE_WITHOUT_ADDING_OR_REWRITING_CORPUS_TEXT",
            fixture_id,
            ok,
        )

        # 9. a schema-valid response materializes through the real materializer
        draft = _schema_valid_draft(envelope)
        mapping = materialize_evidence_mapping_draft(draft=draft, request=revalidated)
        validate_materialized_evidence_mapping(mapping=mapping, request=revalidated)
        row["materializer_version"] = fixture["materializer_boundary"]["version"]
        _record(
            results,
            "A_SCHEMA_VALID_RESPONSE_MATERIALIZES_THROUGH_THE_REAL_MATERIALIZER",
            fixture_id,
            True,
        )

        # 10. deterministic and outcome-independent
        _, rebuilt_envelope = build_p06_fixture_v12(
            route_fixture_id=fixture_id,
            model_visible_definition=model_visible_definition_for(
                next(
                    item
                    for item in catalog["constructs"]
                    if item["construct_key"] == fixture["target_construct_key"]
                ),
                bundle,
            ),
            bundle=bundle,
        )
        ok = canonical_hash(rebuilt_envelope.model_dump(mode="json")) == fixture[
            "alias_envelope_hash"
        ]
        _record(
            results,
            "REQUEST_CONSTRUCTION_IS_OUTCOME_INDEPENDENT_AND_DETERMINISTIC",
            fixture_id,
            ok,
        )
        per_fixture.append(row)

    failures = {name: rows for name, rows in results.items() if rows}
    if failures:
        raise N3ProviderFixtureError(
            f"the N3 provider fixture set is not production-representative: {failures}"
        )

    material = {
        "schema_version": "n3-provider-production-representativeness/1.3.1",
        "conditions": list(PRODUCTION_REPRESENTATIVENESS_CONDITIONS),
        "condition_count": len(PRODUCTION_REPRESENTATIVENESS_CONDITIONS),
        "fixture_count": len(build.fixtures),
        "all_conditions_hold_for_every_fixture": True,
        "failing_fixtures_by_condition": {},
        "per_fixture": per_fixture,
        "note": (
            "Every condition runs the real product code against every fixture. "
            "The placeholder draft used to exercise the materializer asserts no "
            "semantic answer and is discarded; it exists to prove the response "
            "path is real, not to encode an expectation."
        ),
    }
    return {**material, "proof_hash": canonical_hash(material)}


def _record(results: dict[str, list[str]], condition: str, fixture_id: str, ok: bool) -> None:
    if not ok:
        results[condition].append(fixture_id)


# --------------------------------------------------------------------------
# The selection rule is independent of everything it may not read
# --------------------------------------------------------------------------


def selection_independence_proof(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
) -> dict[str, Any]:
    """Perturb every forbidden input and show the selection does not move."""

    catalog = build_construct_catalog(corpus_root)
    population = n3_exposure_population(corpus_root, V12_SPLIT_PARTITION_PATH)
    activities = sorted({item["activity_id"] for item in population["exposures"]})
    baseline = {
        activity: select_construct(catalog["constructs"], activity_id=activity)[
            "construct_key"
        ]
        for activity in activities
    }

    probes: list[dict[str, Any]] = []

    # Catalog input order: the rule must not depend on how the list arrives.
    reversed_catalog = list(reversed(catalog["constructs"]))
    probes.append(
        {
            "probe": "CATALOG_INPUT_ORDER_REVERSED",
            "stable": all(
                select_construct(reversed_catalog, activity_id=activity)["construct_key"]
                == baseline[activity]
                for activity in activities
            ),
        }
    )

    # Every forbidden field, mutated on an in-memory copy of the catalog rows.
    forbidden_fields = (
        ("INJECTION_TEXT", "neutral_description"),
        ("SUBMISSION_EVIDENCE_TEXT", "neutral_observable"),
        ("NOISY_OUTCOME", "authorized_operations"),
        ("ORACLE_PROPERTY_OR_EXPECTED_SUPPORT_STATUS", "contains_expected_support_status"),
        ("CANDIDATE_OUTPUT", "contains_oracle_verdict"),
    )
    for label, field in forbidden_fields:
        mutated = json.loads(json.dumps(catalog["constructs"]))
        for item in mutated:
            current = item.get(field)
            if isinstance(current, str):
                item[field] = "MUTATED::" + current
            elif isinstance(current, bool):
                item[field] = not current
            elif isinstance(current, list):
                item[field] = list(reversed(current)) + ["MUTATED"]
        probes.append(
            {
                "probe": f"{label}_VIA_{field}",
                "stable": all(
                    select_construct(mutated, activity_id=activity)["construct_key"]
                    == baseline[activity]
                    for activity in activities
                ),
            }
        )

    # And the converse: perturbing the *source order* must move the selection,
    # or the rule would not be reading source order at all.
    moved = json.loads(json.dumps(catalog["constructs"]))
    for item in moved:
        item["provenance"]["row"] = -int(item["provenance"].get("row", 0))
        item["provenance"]["unit_index"] = -int(item["provenance"].get("unit_index", 0))
    changed = sum(
        select_construct(moved, activity_id=activity)["construct_key"]
        != baseline[activity]
        for activity in activities
    )

    unstable = [item["probe"] for item in probes if not item["stable"]]
    if unstable:
        raise N3ProviderFixtureError(
            f"construct selection depends on material it may not read: {unstable}"
        )
    if changed == 0:
        raise N3ProviderFixtureError(
            "reversing source order changed no selection; the rule is not "
            "reading canonical source order"
        )

    material = {
        "schema_version": "n3-construct-selection-independence/1.3.1",
        "rule": N3_CONSTRUCT_SELECTION_RULE,
        "order_key_fields": ["source_document", "table_index", "row", "unit_index"],
        "reads_only": ["construct.source_refs", "construct.provenance"],
        "forbidden_inputs": list(N3_SELECTION_FORBIDDEN_INPUTS),
        "baseline_selection": baseline,
        "probes": probes,
        "all_forbidden_inputs_are_inert": True,
        "activities_whose_selection_moves_when_source_order_is_reversed": changed,
        "rule_actually_reads_source_order": True,
    }
    return {**material, "proof_hash": canonical_hash(material)}


#: Identifier prefixes a real P04 candidate artifact would carry.  A request
#: naming one would mean the N3 fixture consumed a model output rather than
#: being synthesized from authorized source.
_P04_ARTIFACT_MARKERS: tuple[str, ...] = (
    "p04_candidate",
    "candidate_blueprint",
    "blueprint_candidate",
    "p04_output",
    "PP-A",
)


def _references_p04_artifact(payload: Mapping[str, Any]) -> bool:
    """True if the request names a P04 candidate artifact anywhere."""

    serialized = json.dumps(payload, ensure_ascii=False)
    return any(marker in serialized for marker in _P04_ARTIFACT_MARKERS)


# --------------------------------------------------------------------------
# PART E -- the NOISY disposition census, derived rather than written down
# --------------------------------------------------------------------------


def noisy_disposition_census(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
) -> dict[str, Any]:
    """Partition the ten NOISY exposures by why they carry no P06 route.

    Phase 9B.8 stated "four excluded, six state no P06 property" in prose. The
    numbers were right and the method was not: they were written beside the
    machine rather than produced by it. Here every count is derived, the three
    classes are required to partition the population exactly, and the prose is
    generated from the result.
    """

    from .p06_remediated_derivation import derive_remediated_p06

    population = n3_exposure_population(corpus_root, V12_SPLIT_PARTITION_PATH)
    derivation = derive_remediated_p06(corpus_root)

    routed = {
        (item["activity_id"], item["submission_id"]) for item in derivation.routes
    }
    debt_by_submission: dict[tuple[str, str], list[str]] = {}
    for entry in derivation.coverage_debt:
        key = (entry["activity_id"], entry["submission_id"])
        debt_by_submission.setdefault(key, []).append(entry["disposition"])

    ratified_p06: dict[tuple[str, str], int] = {}
    for activity_dir in sorted(Path(corpus_root).glob("activity_*")):
        ratification = json.loads(
            (activity_dir / "final_ratification.json").read_text(encoding="utf-8")
        )
        activity_id = str(ratification["activity_id"])
        for submission in ratification.get("submissions", []):
            key = (activity_id, str(submission["submission_id"]))
            ratified_p06[key] = sum(
                1 for prop in submission["properties"] if prop["stage"] == "P06"
            )

    rows: list[dict[str, Any]] = []
    for exposure in sorted(
        population["exposures"], key=lambda item: item["exposure_id"]
    ):
        key = (exposure["activity_id"], exposure["submission_id"])
        p06_properties = ratified_p06.get(key, 0)
        if key in routed:
            disposition = "HAS_EXECUTABLE_SEMANTIC_ROUTE"
        elif p06_properties:
            disposition = "P06_PROPERTY_EXCLUDED_BY_FAIL_CLOSED_RESOLUTION"
        else:
            disposition = "NO_RATIFIED_P06_PROPERTY"
        rows.append(
            {
                "exposure_id": exposure["exposure_id"],
                "activity_id": exposure["activity_id"],
                "submission_id": exposure["submission_id"],
                "ratified_p06_property_count": p06_properties,
                "coverage_debt_dispositions": sorted(debt_by_submission.get(key, [])),
                "disposition": disposition,
            }
        )

    counts = Counter(row["disposition"] for row in rows)
    census = {
        "noisy_exposure_count": len(rows),
        "noisy_with_executable_semantic_route_count": counts[
            "HAS_EXECUTABLE_SEMANTIC_ROUTE"
        ],
        "noisy_with_p06_property_but_excluded_count": counts[
            "P06_PROPERTY_EXCLUDED_BY_FAIL_CLOSED_RESOLUTION"
        ],
        "noisy_with_no_p06_property_count": counts["NO_RATIFIED_P06_PROPERTY"],
    }
    total = (
        census["noisy_with_executable_semantic_route_count"]
        + census["noisy_with_p06_property_but_excluded_count"]
        + census["noisy_with_no_p06_property_count"]
    )
    if total != census["noisy_exposure_count"]:
        raise N3ProviderFixtureError(
            "the NOISY disposition classes do not partition the population: "
            f"{total} classified vs {census['noisy_exposure_count']} exposures"
        )
    if census["noisy_exposure_count"] != population["total_exposure_count"]:
        raise N3ProviderFixtureError(
            "the census population disagrees with the frozen N3 exposure population"
        )

    material = {
        "schema_version": "n3-noisy-disposition-census/1.3.1",
        "derived_not_asserted": True,
        **census,
        "classes_partition_the_population": True,
        "rows": rows,
        "prose": noisy_disposition_prose(census),
    }
    return {**material, "census_hash": canonical_hash(material)}


def noisy_disposition_prose(census: Mapping[str, int]) -> str:
    """Generate the sentence, so no reader ever meets a hand-typed count."""

    return (
        f"None of the {census['noisy_exposure_count']} ratified "
        "PROMPT_INJECTION_NOISY submissions carries an executable P06 semantic "
        f"route: {census['noisy_with_p06_property_but_excluded_count']} had their "
        "P06 properties excluded by the fail-closed construct resolver and "
        f"{census['noisy_with_no_p06_property_count']} state no P06 property at "
        f"all, leaving {census['noisy_with_executable_semantic_route_count']} that "
        "could ride an existing candidate call."
    )


# --------------------------------------------------------------------------
# PART D -- the frozen fixture-set authority
# --------------------------------------------------------------------------


def n3_provider_fixture_authority_current(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
) -> dict[str, Any]:
    """The current run-aware N3 provider fixture set, with derived counts."""

    build = build_n3_provider_fixtures(corpus_root)
    representativeness = production_representativeness_proof(build, corpus_root)
    independence = selection_independence_proof(corpus_root)
    census = noisy_disposition_census(corpus_root)

    by_split = Counter(item["n3_split"] for item in build.fixtures)
    by_side = Counter(item["side"] for item in build.fixtures)
    plan = {item["stage"]: item for item in build.stage_plan["stages"]}

    # The fixture set must cover the frozen exposure population exactly, and
    # its split membership must agree with the frozen stage plan.
    fixture_exposures = {item["exposure_id"] for item in build.fixtures}
    population_exposures = {
        item["exposure_id"] for item in build.population["exposures"]
    }
    if fixture_exposures != population_exposures:
        raise N3ProviderFixtureError(
            "the fixture set does not cover the frozen exposure population: "
            f"missing {sorted(population_exposures - fixture_exposures)}, "
            f"extra {sorted(fixture_exposures - population_exposures)}"
        )
    for stage, row in plan.items():
        expected = set(row["exposure_ids"])
        actual = {
            item["exposure_id"]
            for item in build.fixtures
            if item["n3_split"] == stage
        }
        if expected != actual:
            raise N3ProviderFixtureError(
                f"{stage} fixture membership disagrees with the frozen stage plan"
            )

    input_hashes = {
        item["n3_provider_fixture_id"]: item["provider_request_hash"]
        for item in build.fixtures
    }
    if len(set(input_hashes.values())) != len(input_hashes):
        raise N3ProviderFixtureError(
            "two N3 provider fixtures share a request hash; the exposures would "
            "not be distinguishable"
        )

    material = {
        "schema_version": N3_PROVIDER_FIXTURES_V135_VERSION,
        "benchmark_version": "semantic-benchmark/1.3.5",
        "gate": "P06_STAGE_LOCAL_NOISY_CONTRACTUAL_HARD_SAFETY_GATE",
        "stage": "P06",
        "purpose": (
            "N3 buys its own P06 provider calls, so the request shape is "
            "qualification authority and is frozen here before anything runs."
        ),
        # --- selection authority
        "construct_selection_rule": N3_CONSTRUCT_SELECTION_RULE,
        "construct_selection_order_key": [
            "source_document",
            "table_index",
            "row",
            "unit_index",
        ],
        "construct_selection_authority": (
            "The authorized construct source document the instructor wrote. The "
            "rule reads a construct's source_refs and provenance and nothing "
            "else; each NOISY activity draws its constructs from exactly one "
            "source document, so no cross-document precedence is invented."
        ),
        "construct_selection_independence_hash": independence["proof_hash"],
        "construct_selection_forbidden_inputs": list(N3_SELECTION_FORBIDDEN_INPUTS),
        # --- fixtures
        "fixtures": list(build.fixtures),
        "fixture_count": len(build.fixtures),
        "fixture_input_hashes": input_hashes,
        "fixture_ids": sorted(input_hashes),
        "provider_unit": "EXPOSURE_RUN",
        "run_identity_fields": ["exposure_pseudonym", "run_index"],
        "runs_per_exposure": N3_RUNS_PER_EXPOSURE,
        "run_cardinality_authority": "phase9_protocol.SEMANTIC_K",
        "caller_may_define_k": False,
        "fixture_run_identities": {
            item["n3_provider_fixture_id"]: [
                {
                    "exposure_pseudonym": item["exposure_id"],
                    "run_index": run_index,
                }
                for run_index in range(1, N3_RUNS_PER_EXPOSURE + 1)
            ]
            for item in build.fixtures
        },
        # --- derived counts
        "counts_by_n3_split": dict(sorted(by_split.items())),
        "counts_by_side": dict(sorted(by_side.items())),
        "safety_smoke_fixture_count": by_split[N3_SAFETY_SMOKE],
        "core_fixture_count": by_split[N3_CORE],
        "held_out_fixture_count": by_split[N3_HELD_OUT_CONFIRMATION],
        "qualification_side_fixture_count": by_side[QUALIFICATION_SIDE],
        "counts_derived_from_the_fixture_set": True,
        "required_provider_calls_by_n3_split": {
            split: count * N3_RUNS_PER_EXPOSURE
            for split, count in sorted(by_split.items())
        },
        # --- bindings
        "exposure_population_hash": build.population["population_hash"],
        "stage_plan_hash": build.stage_plan["stage_plan_hash"],
        "split_partition_hash": build.population["split_partition_hash"],
        "fixture_builder_version": P06_FIXTURE_BUILDER_V12_VERSION,
        "fixture_builder_source_hash": _source_hash("semantic_benchmark_v12.py"),
        "request_construction_source_hash": _source_hash("n3_provider_fixtures.py"),
        "materializer_boundary": evidence_mapping_materializer_boundary(),
        "alias_envelope_schema_boundary": p06_alias_envelope_schema_boundary(),
        # --- proofs
        "production_representativeness_hash": representativeness["proof_hash"],
        "production_representativeness_conditions": list(
            PRODUCTION_REPRESENTATIVENESS_CONDITIONS
        ),
        "noisy_disposition_census_hash": census["census_hash"],
        # --- what this authority never carries
        "expected_candidate_family": N3_EXPECTED_CANDIDATE_FAMILY,
        "carries_a_semantic_golden": False,
        "carries_an_oracle_property": False,
        "carries_a_candidate_outcome": False,
        "provider_calls": 0,
        "adjudicator_calls": 0,
    }
    return {**material, "fixture_set_hash": canonical_hash(material)}


def n3_provider_fixture_authority(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
) -> dict[str, Any]:
    """Return immutable historical v1.3.1 fixture authority.

    Successor benchmark builders must call
    :func:`n3_provider_fixture_authority_current` explicitly.  This public
    historical accessor preserves every already-published v1.3.1--v1.3.4
    equality proof after the live N3 stage plan advances to exposure/run rows.
    """

    if Path(corpus_root).resolve() != Path(DEFAULT_CORPUS_ROOT).resolve():
        raise N3ProviderFixtureError(
            "historical N3 fixture authority requires the canonical corpus"
        )
    return json.loads(
        (
            REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_3_1/phase9/n3_provider_fixtures.json"
        ).read_text(encoding="utf-8")
    )
