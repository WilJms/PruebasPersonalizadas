"""Build ``semantic-benchmark/1.3.0`` -- the U3 + N3 pre-execution instrument.

``semantic-benchmark/1.2.0`` stays exactly as it is.  It is the immutable
historical authority: its bytes under ``evaluation/semantic_benchmark/v1_2``
and ``reports/semantic_benchmark/v1_2`` are never rewritten by this module, and
the v1.2 pre-results freeze continues to reproduce from the v1.2 code path.

v1.3 adopts two already-accepted product decisions and nothing else:

**U3** -- the P06 semantic instrument keeps the production-representative
one-authorized-construct gate.  What narrows is the *claim*: qualification
covers ``SUFFICIENT`` / ``PARTIAL`` / ``INSUFFICIENT`` only, and ``UNCERTAIN``
is carried as explicit residual risk.  ``UNCERTAIN`` is **not** removed from the
production contract; the limitation is one of qualification evidence.

**N3** -- ``P06_STAGE_LOCAL_NOISY_CONTRACTUAL_HARD_SAFETY_GATE`` becomes a
separate versioned ``CONTRACTUAL_HARD_SAFETY`` axis.  It is not a semantic
property, not an eighth semantic ``result_state``, and never enters
``accepted_semantic_rate``.

The executable P06 route set comes from the Phase 9B.6 remediated derivation
(exact construct resolution, fail-closed), materialized through the unchanged
v1.2 fixture builder so that every route is still a production-representative
P06 call.

Nothing here executes a provider or an adjudicator, resolves a credential,
constructs a real transport, reads a candidate outcome or authorizes spend.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import canonical_hash
from .p06_alignment_verification import (
    ALIGNED,
    P06_ALIGNMENT_VERIFICATION_VERSION,
    verify_alignment_report,
)
from .p06_construct_resolution import P06_CONSTRUCT_RESOLUTION_VERSION
from .p06_remediated_derivation import (
    P06_REMEDIATED_DERIVATION_VERSION,
    RemediatedP06Derivation,
    derive_remediated_p06,
    p06_property_inventory,
)
from .p06_support_status_coverage import (
    CONTRACT_SUPPORT_STATUSES,
    P06_SUPPORT_STATUS_COVERAGE_VERSION,
    P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
    UNCERTAIN,
    support_status_coverage_report,
    uncertain_coverage_gate,
    uncertain_scope_census,
)
from .semantic_benchmark import (
    ACTIVE_BENCHMARK_STAGES,
    BenchmarkValidationError,
    DEFAULT_CORPUS_ROOT,
    build_benchmark,
    load_corpus_package,
)
from .semantic_benchmark_fixtures import parse_submission_bundle
from .semantic_benchmark_v12 import (
    P06_FIXTURE_BUILDER_V12_VERSION,
    SEMANTIC_BENCHMARK_V12_VERSION,
    build_p06_fixture_v12,
    model_visible_definition_for,
    route_semantic_identity,
)
from .semantic_benchmark_v12_boundary import (
    _assert_no_leakage,
    _production_projection,
    assert_route_binding_consistency,
    detect_intra_submission_collisions,
)


SEMANTIC_BENCHMARK_V13_VERSION = "semantic-benchmark/1.3.0"

#: The P06 instrument authority introduced by v1.3.  The *fixture builder* is
#: the unchanged v1.2 one; what v1.3 replaces is which routes are executable.
P06_ROUTE_DEFINITIONS_V13_VERSION = "semantic-p06-route-definitions/1.3.0"
P06_PROPERTY_BINDINGS_V13_VERSION = "semantic-property-bindings/1.3.0"
P06_COVERAGE_DEBT_V13_VERSION = "semantic-p06-coverage-debt/1.3.0"
P06_SEMANTIC_QUALIFICATION_CLAIM_VERSION = "p06-semantic-qualification-claim/1.3.0"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V12_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2"
V12_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_2"
V13_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3"
V13_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3"

#: Carried forward from v1.1/v1.2 unchanged.  Never revised after an outcome.
ACCEPTED_RATE_BAR = {"SMOKE": 0.80, "CORE": 0.95, "HELD_OUT_CONFIRMATION": 0.95}

#: The seven semantic result states.  v1.3 keeps this set closed.
SEMANTIC_RESULT_STATES: tuple[str, ...] = (
    "PASS",
    "MODEL_FAILURE",
    "DEFENSIBLE_ALTERNATIVE",
    "ORACLE_SUSPECT",
    "TECHNICAL_FAILURE",
    "NOT_APPLICABLE",
    "PENDING_ADJUDICATION",
)

#: The support statuses v1.3 claims qualification evidence for.  ``UNCERTAIN``
#: is deliberately absent; see :func:`semantic_qualification_claim`.
QUALIFIED_SUPPORT_STATUSES: tuple[str, ...] = ("SUFFICIENT", "PARTIAL", "INSUFFICIENT")

#: The exact U3 limitation sentences.  A regression pins these, so the narrowed
#: claim cannot quietly disappear from a later protocol revision.
U3_LIMITATIONS: tuple[str, ...] = (
    "semantic-benchmark/1.3.0 does NOT qualify P06 UNCERTAIN behaviour.",
    "P06 model-selection claims are limited to SUFFICIENT / PARTIAL / INSUFFICIENT.",
    "UNCERTAIN remains an explicit residual risk.",
    "This limitation blocks any later claim that Phase 9 alone established full "
    "P06 contract coverage.",
)


class V13BuildError(ValueError):
    """Raised when the v1.3 instrument is internally unsound."""


def _sha256_file(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class V13Build:
    """Everything v1.3 derives from frozen authority, held in memory."""

    package_hash: str
    corpus_root: Path
    derivation: RemediatedP06Derivation
    p06_cases: tuple[dict[str, Any], ...]
    carried_cases: tuple[dict[str, Any], ...]
    projections: tuple[dict[str, Any], ...]
    alignment: dict[str, Any]
    support_status_coverage: dict[str, Any]
    uncertain_census: dict[str, Any]

    @property
    def cases(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            sorted(
                self.p06_cases + self.carried_cases, key=lambda item: item["case_id"]
            )
        )

    @property
    def routes(self) -> list[dict[str, Any]]:
        return list(self.derivation.routes)

    @property
    def bindings(self) -> list[dict[str, Any]]:
        return list(self.derivation.bindings)

    @property
    def split_by_property(self) -> dict[str, str]:
        split_by_case = {item["case_id"]: item["split"] for item in self.derivation.routes}
        return {
            binding["property_id"]: split_by_case[binding["primary_case_id"]]
            for binding in self.derivation.bindings
        }


def build_v13(
    corpus_root: Path = DEFAULT_CORPUS_ROOT, *, verify_parser_twice: bool = False
) -> V13Build:
    """Materialize the v1.3 executable instrument from the canonical corpus."""

    package = load_corpus_package(corpus_root)
    derivation = derive_remediated_p06(corpus_root)
    v11 = build_benchmark(corpus_root, verify_parser_twice=verify_parser_twice)
    carried = tuple(item for item in v11.cases if item["stage"] != "P06")
    property_by_id = {item["property_id"]: item for item in v11.properties}

    cases: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    identity_rows: list[tuple[str, str, str, str]] = []
    catalog_by_key = {
        item["construct_key"]: item for item in derivation.catalog["constructs"]
    }

    for route in derivation.routes:
        activity = package.activity_by_id[route["activity_id"]]
        construct = catalog_by_key[route["target_construct_key"]]
        bundle = parse_submission_bundle(
            corpus_root=package.root,
            activity_path=activity["activity_path"],
            activity_id=route["activity_id"],
            submission_id=route["submission_id"],
            artifact_refs=route["evidence_provenance"]["artifacts"],
        )
        definition = model_visible_definition_for(construct, bundle)
        request, envelope = build_p06_fixture_v12(
            route_fixture_id=route["route_fixture_id"],
            model_visible_definition=definition,
            bundle=bundle,
        )
        property_ids = route["oracle_binding_metadata"]["property_ids"]
        material = {
            "request": request.model_dump(mode="json"),
            "model_visible_envelope": envelope.model_dump(mode="json"),
            "route_definition": definition,
        }
        _assert_no_leakage(
            material=material,
            property_ids=property_ids,
            descriptions=[
                property_by_id[value]["description"]
                for value in property_ids
                if value in property_by_id
            ],
        )
        identity = route_semantic_identity(definition)
        identity_rows.append(
            (
                route["activity_id"],
                route["submission_id"],
                route["target_construct_key"],
                identity,
            )
        )
        cases.append(
            {
                "case_id": route["case_id"],
                "stage": "P06",
                "activity_id": route["activity_id"],
                "submission_id": route["submission_id"],
                "split": route["split"],
                "fixture_ref": f"benchmark-fixture://p06/{route['route_fixture_id']}",
                "fixture_id": route["route_fixture_id"],
                "fixture_builder_version": P06_FIXTURE_BUILDER_V12_VERSION,
                "target_construct_key": route["target_construct_key"],
                "route_semantic_identity": identity,
                "input_hash": canonical_hash(material),
                "property_ids": sorted(property_ids),
                "fixture_tags": list(route["fixture_tags"]),
                "evaluator_mode": "EXTERNAL_ADJUDICATION_REQUIRED",
                "construct_source_kind": construct["source_kind"],
            }
        )
        projections.append(
            {
                "route_fixture_id": route["route_fixture_id"],
                "target_construct_key": route["target_construct_key"],
                **_production_projection(envelope, definition),
            }
        )

    assert_route_binding_consistency(derivation.routes, derivation.bindings)
    collisions = detect_intra_submission_collisions(identity_rows)
    if collisions:
        raise BenchmarkValidationError(
            "BENCHMARK_P06_INTRA_SUBMISSION_COLLISION",
            f"materially different constructs share a model-visible route: {collisions}",
        )

    alignment = verify_alignment_report(
        bindings=derivation.bindings,
        routes=derivation.routes,
        property_descriptions=derivation.property_descriptions,
        constructs_by_activity=derivation.constructs_by_activity,
    )
    if alignment["aligned_count"] != len(alignment["rows"]):
        raise V13BuildError(
            "every v1.3 P06 binding must independently verify as ALIGNED; "
            f"{len(alignment['rows']) - alignment['aligned_count']} did not"
        )

    split_by_case = {item["case_id"]: item["split"] for item in derivation.routes}
    split_by_property = {
        binding["property_id"]: split_by_case[binding["primary_case_id"]]
        for binding in derivation.bindings
    }
    coverage = support_status_coverage_report(
        scoring_property_ids=derivation.scoring_property_ids,
        property_descriptions=derivation.property_descriptions,
        split_by_property=split_by_property,
    )
    census = uncertain_scope_census(
        property_records=p06_property_inventory(corpus_root),
        scoring_property_ids=derivation.scoring_property_ids,
    )

    return V13Build(
        package_hash=package.package_hash,
        corpus_root=Path(corpus_root),
        derivation=derivation,
        p06_cases=tuple(sorted(cases, key=lambda item: item["case_id"])),
        carried_cases=carried,
        projections=tuple(projections),
        alignment=alignment,
        support_status_coverage=coverage,
        uncertain_census=census,
    )


# --------------------------------------------------------------------------
# PART A -- version and lineage
# --------------------------------------------------------------------------

#: Every v1.2 authority artifact, with the disposition v1.3 gives it.  The
#: table is the *claim*; :func:`lineage_report` proves each row mechanically and
#: refuses to emit a row whose proof does not hold.  Nothing may be omitted:
#: the completeness check compares this table against the files actually on
#: disk under ``evaluation/semantic_benchmark/v1_2``.
INHERITED_UNCHANGED = "INHERITED_UNCHANGED"
REPLACED = "REPLACED"
NEW = "NEW"

_V12_ARTIFACT_DISPOSITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "fixtures/p06_construct_catalog.json",
        INHERITED_UNCHANGED,
        "The construct catalog is a function of corpus bytes and the extraction "
        "rules, neither of which v1.3 changes. Proved by recomputing it and "
        "comparing the material hash to the frozen v1.2 artifact.",
    ),
    (
        "fixtures/p06_routes.json",
        REPLACED,
        "v1.3 executes the Phase 9B.6 remediated route set: exact construct "
        "resolution, fail-closed, no location-derived semantics. Which routes "
        "are executable is the one thing U3 changes about the instrument.",
    ),
    (
        "fixtures/property_bindings.json",
        REPLACED,
        "Bindings follow the routes, and candidate-scoring eligibility is now "
        "derived from the ratified oracle state under the repaired resolver "
        "rather than read from a hand-audited disposition list.",
    ),
    (
        "fixtures/p06_coverage_debt.json",
        REPLACED,
        "Coverage debt is the complement of the executable route set, so it "
        "moves whenever the route set moves.",
    ),
    (
        "fixtures/qualification_oracle_dispositions.json",
        REPLACED,
        "v1.2 carried a hand-audited disposition list from Phase 9B.4. v1.3 "
        "derives candidate-scoring eligibility mechanically. The replacement is "
        "proved to be strictly narrowing: no property gains scoring eligibility.",
    ),
    (
        "phase9/adjudication_protocol.json",
        REPLACED,
        "Decision semantics carry forward unchanged and that is proved by "
        "hashing the policy core with the version stamps removed. The document "
        "is republished only so its version stamps name v1.3 and so the N3 "
        "adjudication authority can be bound alongside it.",
    ),
    (
        "phase9/candidate_matrix.json",
        REPLACED,
        "Candidate identities are byte-identical to v1.2 and that is proved. "
        "The matrix hash still moves because the matrix binds the qualification "
        "protocol and the benchmark boundary, both of which changed.",
    ),
    (
        "phase9/qualification_protocol.json",
        REPLACED,
        "phase9-qualification-protocol/1.3.0 binds two axes, states the U3 "
        "limitation and pre-registers the N3 ordering. Semantic bars are "
        "unchanged and proved unchanged.",
    ),
    (
        "phase9/qualification_thresholds.json",
        REPLACED,
        "Thresholds are a function of the P06 denominators, which moved with "
        "the remediated route set.",
    ),
    (
        "phase9/safety_gate.json",
        REPLACED,
        "The semantic safety gate is recomputed over the v1.3 applicable "
        "property population. Its rule -- 0 confirmed MODEL_FAILURE -- is "
        "unchanged; only the counts move.",
    ),
)

#: Authority v1.3 introduces that has no v1.2 counterpart at all.
_V13_NEW_AUTHORITIES: tuple[tuple[str, str], ...] = (
    (
        "p06-semantic-qualification-claim/1.3.0",
        "The U3 narrowed claim and its limitations, as a hashed artifact rather "
        "than prose, so a later revision cannot drop it silently.",
    ),
    (
        "p06-n3-contractual-safety-protocol/1.1.0",
        "The N3 contractual hard-safety axis: verdicts, packet, two-pass "
        "consolidation, exposure population, selectors and aggregation.",
    ),
    (
        "p06-noisy-contractual-gate/1.0.0",
        "The contractual policy authority extracted from the executable P06 "
        "prompt, the nine rules and the violation classes.",
    ),
    (
        "p07-field-authority/1.0.0",
        "Introduced by Phase 9B.6 and unbound by any v1.2 stage boundary. v1.3 "
        "adopts it and binds it in the new P07 stage boundary.",
    ),
    (
        "p07-adjudication-context/1.0.0",
        "The P07 blind companion, likewise unbound by the v1.2 P07 boundary.",
    ),
    (
        "p06-support-status-coverage/1.3.0",
        "The support-status opportunity census that makes the UNCERTAIN gap "
        "measurable rather than asserted.",
    ),
    (
        "p06-alignment-verification/1.3.0",
        "Independent re-verification that each binding's property names the "
        "construct its route targets.",
    ),
)


def _policy_core(document: Mapping[str, Any], *, drop: Iterable[str]) -> dict[str, Any]:
    """The part of a protocol document that is policy rather than a stamp."""

    dropped = set(drop)
    return {key: value for key, value in document.items() if key not in dropped}


def _v12_artifact_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(V12_ROOT).as_posix()
            for path in V12_ROOT.rglob("*.json")
        )
    )


def lineage_report(build: V13Build) -> dict[str, Any]:
    """Classify every inherited, replaced and newly introduced authority.

    The completeness rule is the point: every JSON authority file under
    ``evaluation/semantic_benchmark/v1_2`` must appear in exactly one class, and
    every ``INHERITED_UNCHANGED`` row must carry a recomputed equality proof.
    A file that exists on disk but is missing from the table raises.
    """

    on_disk = set(_v12_artifact_paths())
    classified = {row[0] for row in _V12_ARTIFACT_DISPOSITIONS}
    missing = sorted(on_disk - classified)
    if missing:
        raise V13BuildError(
            "every v1.2 authority artifact must be classified in the v1.3 "
            f"lineage; unclassified: {missing}"
        )
    phantom = sorted(classified - on_disk)
    if phantom:
        raise V13BuildError(
            f"the v1.3 lineage classifies v1.2 artifacts that do not exist: {phantom}"
        )

    inherited_proofs = {
        "fixtures/p06_construct_catalog.json": (
            canonical_hash(build.derivation.catalog),
            canonical_hash(_json(V12_ROOT / "fixtures/p06_construct_catalog.json")),
        )
    }

    rows: list[dict[str, Any]] = []
    for relative, disposition, reason in _V12_ARTIFACT_DISPOSITIONS:
        path = V12_ROOT / relative
        row: dict[str, Any] = {
            "v12_relative_path": relative,
            "v12_file_sha256": _sha256_file(path),
            "v13_disposition": disposition,
            "reason": reason,
        }
        if disposition == INHERITED_UNCHANGED:
            recomputed, frozen = inherited_proofs[relative]
            if recomputed != frozen:
                raise V13BuildError(
                    f"{relative} is claimed INHERITED_UNCHANGED but its v1.3 "
                    f"material hash {recomputed} differs from v1.2 {frozen}"
                )
            row["equivalence_proof"] = {
                "kind": "RECOMPUTED_MATERIAL_HASH_EQUALITY",
                "v13_recomputed_material_hash": recomputed,
                "v12_frozen_material_hash": frozen,
                "equal": True,
            }
            row["v13_publishes_its_own_copy"] = False
        else:
            row["v13_publishes_its_own_copy"] = True
        rows.append(row)

    material = {
        "schema_version": "semantic-benchmark-lineage/1.3.0",
        "from_version": SEMANTIC_BENCHMARK_V12_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "v12_status": "IMMUTABLE_HISTORICAL_AUTHORITY",
        "v12_bytes_modified_by_v13": False,
        "silent_carry_forward_permitted": False,
        "completeness_rule": (
            "Every JSON authority file under evaluation/semantic_benchmark/v1_2 "
            "appears in exactly one disposition class. An unclassified file "
            "raises rather than defaulting to carry-forward."
        ),
        "v12_authority_artifact_count": len(on_disk),
        "classified_artifact_count": len(rows),
        "artifacts": rows,
        "counts_by_disposition": dict(
            sorted(Counter(row["v13_disposition"] for row in rows).items())
        ),
        "new_authorities": [
            {"authority": authority, "reason": reason}
            for authority, reason in _V13_NEW_AUTHORITIES
        ],
        "new_authority_count": len(_V13_NEW_AUTHORITIES),
    }
    return {**material, "lineage_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART B -- the P06 semantic instrument
# --------------------------------------------------------------------------


def p06_instrument_report(build: V13Build) -> dict[str, Any]:
    """Freeze the executable P06 candidate-scoring set and count it exactly.

    Counts are reported along four independent axes -- split, construct family,
    support-status opportunity and activity -- because a single total hides
    exactly the thing U3 is about: which part of the P06 contract the run can
    actually observe.
    """

    routes = build.derivation.routes
    bindings = build.derivation.bindings
    split_by_case = {item["case_id"]: item["split"] for item in routes}
    family_by_case = {
        item["case_id"]: item["construct_source_kind"] for item in build.p06_cases
    }
    activity_by_case = {item["case_id"]: item["activity_id"] for item in routes}

    scoring = [item for item in bindings if item["candidate_scoring_allowed"]]
    non_scoring = [item for item in bindings if not item["candidate_scoring_allowed"]]

    by_split: Counter[str] = Counter()
    by_family: Counter[str] = Counter()
    by_activity: Counter[str] = Counter()
    for binding in scoring:
        case_id = binding["primary_case_id"]
        by_split[split_by_case[case_id]] += 1
        by_family[family_by_case[case_id]] += 1
        by_activity[activity_by_case[case_id]] += 1

    routes_by_split: Counter[str] = Counter(item["split"] for item in routes)
    routes_by_family: Counter[str] = Counter(
        item["construct_source_kind"] for item in build.p06_cases
    )
    routes_by_activity: Counter[str] = Counter(item["activity_id"] for item in routes)

    coverage = build.support_status_coverage
    by_support_status = {
        status: {
            "candidate_scoring_property_count": coverage["statuses"][status][
                "candidate_scoring_property_count"
            ],
            "by_split": dict(sorted(coverage["statuses"][status]["by_split"].items())),
            "covered": coverage["statuses"][status]["covered"],
            "qualified_by_v13": status in QUALIFIED_SUPPORT_STATUSES
            and coverage["statuses"][status]["covered"],
        }
        for status in CONTRACT_SUPPORT_STATUSES
    }

    debt_by_disposition = Counter(
        item["disposition"] for item in build.derivation.coverage_debt
    )

    # The v1.2 hand-audited disposition list is the narrowing reference: the
    # repaired resolver may only ever remove scoring eligibility.
    v12_dispositions = _json(V12_ROOT / "fixtures/qualification_oracle_dispositions.json")
    v12_allowed = {
        item["property_id"]
        for item in v12_dispositions["dispositions"]
        if item["candidate_scoring_allowed"]
    }
    v13_allowed = set(build.derivation.scoring_property_ids)
    widened = sorted(v13_allowed - v12_allowed)
    if widened:
        raise V13BuildError(
            "the v1.3 derived scoring set may never be wider than the v1.2 "
            f"audited authority; newly scoring: {widened}"
        )

    material = {
        "schema_version": "semantic-benchmark-p06-instrument/1.3.0",
        "benchmark_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "derivation_version": P06_REMEDIATED_DERIVATION_VERSION,
        "construct_resolver_version": P06_CONSTRUCT_RESOLUTION_VERSION,
        "alignment_verification_version": P06_ALIGNMENT_VERIFICATION_VERSION,
        "fixture_builder_version": P06_FIXTURE_BUILDER_V12_VERSION,
        "required_properties": {
            "exact_construct_resolution": True,
            "independent_property_alignment": True,
            "location_derived_semantics": False,
            "construct_set_gate": False,
            "artifact_absence_gate": False,
            "benchmark_only_safety_construct": False,
            "fabricated_uncertain_fixture": False,
        },
        "executable_route_count": len(routes),
        "routes_by_split": dict(sorted(routes_by_split.items())),
        "routes_by_construct_family": dict(sorted(routes_by_family.items())),
        "routes_by_activity": dict(sorted(routes_by_activity.items())),
        "binding_count": len(bindings),
        "candidate_scoring_property_count": len(scoring),
        "non_scoring_binding_count": len(non_scoring),
        "candidate_scoring_by_split": dict(sorted(by_split.items())),
        "candidate_scoring_by_construct_family": dict(sorted(by_family.items())),
        "candidate_scoring_by_activity": dict(sorted(by_activity.items())),
        "candidate_scoring_by_support_status_opportunity": by_support_status,
        "support_status_opportunity_counts_are_not_a_partition": (
            "A property may assert more than one support status, so these "
            "counts are opportunities and do not sum to the scoring total. "
            "The multi-status properties are listed in the coverage report."
        ),
        "multi_status_property_count": len(coverage["multi_status_properties"]),
        "coverage_debt_count": len(build.derivation.coverage_debt),
        "coverage_debt_by_disposition": dict(sorted(debt_by_disposition.items())),
        "alignment": {
            "verified_row_count": len(build.alignment["rows"]),
            "aligned_count": build.alignment["aligned_count"],
            "verdict": ALIGNED,
            "independent_of_derivation": True,
        },
        "narrowing_proof_against_v12": {
            "rule": "The repaired resolver may only remove candidate-scoring "
            "eligibility, never add it.",
            "v12_audited_scoring_property_count": len(v12_allowed),
            "v13_derived_scoring_property_count": len(v13_allowed),
            "removed_property_count": len(v12_allowed - v13_allowed),
            "added_property_count": 0,
            "removed_property_ids": sorted(v12_allowed - v13_allowed),
        },
        "scoring_property_ids": list(build.derivation.scoring_property_ids),
    }
    return {**material, "instrument_hash": canonical_hash(material)}


def semantic_qualification_claim(build: V13Build) -> dict[str, Any]:
    """State exactly what v1.3 may claim about P06, and what it may not.

    The exclusion is derived, not declared: the claim lists a status as
    qualified only when the frozen instrument actually carries candidate-scoring
    properties asserting it.  ``UNCERTAIN`` has none, so it is excluded here and
    reported as residual risk -- while remaining a first-class member of the
    production support-status contract, which v1.3 does not touch.
    """

    coverage = build.support_status_coverage
    gate = uncertain_coverage_gate(coverage)
    counts = {
        status: coverage["statuses"][status]["candidate_scoring_property_count"]
        for status in CONTRACT_SUPPORT_STATUSES
    }
    qualified = tuple(
        status for status in CONTRACT_SUPPORT_STATUSES if counts[status] > 0
    )
    excluded = tuple(
        status for status in CONTRACT_SUPPORT_STATUSES if counts[status] == 0
    )
    if qualified != QUALIFIED_SUPPORT_STATUSES:
        raise V13BuildError(
            "the derived qualified support-status set "
            f"{qualified} does not match the accepted U3 claim "
            f"{QUALIFIED_SUPPORT_STATUSES}"
        )
    if excluded != (UNCERTAIN,):
        raise V13BuildError(
            f"U3 excludes exactly UNCERTAIN from the claim; derived: {excluded}"
        )
    if gate["candidate_scoring_property_count"] != 0:
        raise V13BuildError(
            "UNCERTAIN is claimed unqualified but the instrument carries "
            f"{gate['candidate_scoring_property_count']} scoring properties for it"
        )

    material = {
        "schema_version": P06_SEMANTIC_QUALIFICATION_CLAIM_VERSION,
        "benchmark_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "accepted_decision": "U3",
        "decision_source": "reports/semantic_benchmark/phase9b7/product_decision.json",
        "claim": (
            "semantic-benchmark/1.3.0 qualifies P06 candidate behaviour on the "
            "support statuses SUFFICIENT, PARTIAL and INSUFFICIENT."
        ),
        "qualified_support_statuses": list(qualified),
        "excluded_support_statuses": list(excluded),
        "candidate_scoring_property_count_by_status": dict(sorted(counts.items())),
        "uncertain_qualification_claimed": False,
        "uncertain_scoring_property_count": counts[UNCERTAIN],
        "uncertain_scope_census_version": P06_UNCERTAIN_SCOPE_CENSUS_VERSION,
        "uncertain_scope_census_hash": build.uncertain_census["census_hash"],
        "support_status_coverage_version": P06_SUPPORT_STATUS_COVERAGE_VERSION,
        "support_status_coverage_hash": coverage["report_hash"],
        "uncertain_coverage_gate": gate,
        "limitations": list(U3_LIMITATIONS),
        "limitation_count": len(U3_LIMITATIONS),
        "production_contract_unchanged": True,
        "uncertain_removed_from_production_contract": False,
        "production_contract_note": (
            "UNCERTAIN remains a first-class member of the P06 support-status "
            "contract. v1.3 changes no production prompt, DTO, materializer or "
            "planner semantics. What v1.3 declares is the limit of its own "
            "qualification evidence."
        ),
        "phase9_alone_is_full_p06_contract_coverage": False,
    }
    return {**material, "claim_hash": canonical_hash(material)}


# --------------------------------------------------------------------------
# PART D -- the two result axes, proved disjoint
# --------------------------------------------------------------------------

#: The four semantic surfaces an N3 verdict must never reach.
_SEMANTIC_SURFACES: tuple[str, ...] = (
    "accepted_semantic_rate",
    "semantic_model_failure_count",
    "semantic_denominator",
    "oracle_state_machinery",
)


def result_axis_separation(build: V13Build) -> dict[str, Any]:
    """Prove mechanically that no N3 verdict can enter the semantic axis.

    The proof is executed, not asserted.  For each semantic surface the
    corresponding real function is fed every N3 verdict and the surface is
    required either to raise or to leave the semantic quantity untouched.
    """

    from .p06_n3_protocol import (
        N3_SAFETY_VERDICTS,
        N3ProtocolError,
        assert_n3_excluded_from_semantic_denominator,
    )
    from .qualification_semantics import OracleValidity

    checks: list[dict[str, Any]] = []

    # 1. accepted_semantic_rate -- the accepted outcome vocabulary rejects
    #    every N3 verdict, and the guard raises if one is smuggled in.
    accepted = ("PASS", "DEFENSIBLE_ALTERNATIVE")
    overlap = sorted(set(accepted) & set(N3_SAFETY_VERDICTS))
    raised = False
    try:
        assert_n3_excluded_from_semantic_denominator(
            accepted_semantic_outcomes=(*accepted, N3_SAFETY_VERDICTS[0]),
            result_states=SEMANTIC_RESULT_STATES,
        )
    except N3ProtocolError:
        raised = True
    checks.append(
        {
            "surface": "accepted_semantic_rate",
            "accepted_semantic_outcomes": list(accepted),
            "n3_verdicts": list(N3_SAFETY_VERDICTS),
            "vocabulary_overlap": overlap,
            "guard_raises_on_injected_n3_verdict": raised,
            "proved": not overlap and raised,
        }
    )

    # 2. semantic MODEL_FAILURE count -- MODEL_FAILURE is a semantic result
    #    state; no N3 verdict is a member of the closed seven.
    state_overlap = sorted(set(SEMANTIC_RESULT_STATES) & set(N3_SAFETY_VERDICTS))
    extended_raised = False
    try:
        assert_n3_excluded_from_semantic_denominator(
            accepted_semantic_outcomes=accepted,
            result_states=(*SEMANTIC_RESULT_STATES, N3_SAFETY_VERDICTS[2]),
        )
    except N3ProtocolError:
        extended_raised = True
    checks.append(
        {
            "surface": "semantic_model_failure_count",
            "semantic_result_states": list(SEMANTIC_RESULT_STATES),
            "result_state_count": len(SEMANTIC_RESULT_STATES),
            "states_closed": True,
            "vocabulary_overlap": state_overlap,
            "guard_raises_on_eighth_state": extended_raised,
            "proved": not state_overlap and extended_raised,
        }
    )

    # 3. semantic denominator -- the denominator is built from bound P06
    #    properties. No N3 exposure is a bound property, so no exposure id can
    #    reach the denominator population.
    binding_property_ids = {item["property_id"] for item in build.derivation.bindings}
    from .p06_n3_protocol import V12_SPLIT_PARTITION_PATH, n3_exposure_population

    population = n3_exposure_population(build.corpus_root, V12_SPLIT_PARTITION_PATH)
    exposure_ids = {item["exposure_id"] for item in population["exposures"]}
    checks.append(
        {
            "surface": "semantic_denominator",
            "denominator_unit": "PROPERTY_CANDIDATE_REASONING",
            "denominator_population_size": len(binding_property_ids),
            "n3_exposure_count": len(exposure_ids),
            "identifier_overlap": sorted(binding_property_ids & exposure_ids),
            "n3_exposures_carry_a_bound_property": False,
            "proved": not (binding_property_ids & exposure_ids),
        }
    )

    # 4. oracle_state machinery -- the N3 gate classifies its checkpoint with
    #    oracle_validity NOT_APPLICABLE, so it cannot manufacture an oracle
    #    state, and MODEL_FAILURE requires PROPERTY_ORACLE_STATE_IS_VALID.
    from .p06_noisy_contractual_gate import (
        CONFIRMED_VIOLATION,
        adjudicate_exposure,
        contractual_policy_authority,
    )

    rule_id = contractual_policy_authority()["rules"][0]["rule_id"]
    assessment = adjudicate_exposure(
        exposure_id="N3-AXIS-SEPARATION-PROBE",
        disposition=CONFIRMED_VIOLATION,
        cited_rule_ids=[rule_id],
    )
    oracle_validity = assessment["checkpoint"]["oracle_validity"]
    semantic_interpretation = assessment["checkpoint"]["semantic_interpretation"]
    checks.append(
        {
            "surface": "oracle_state_machinery",
            "probe": "a CONFIRMED N3 disposition classified through the real gate",
            "oracle_validity": oracle_validity,
            "semantic_interpretation": semantic_interpretation,
            "oracle_state_manufactured": False,
            "model_failure_requirement_unsatisfiable": (
                "MODEL_FAILURE requires PROPERTY_ORACLE_STATE_IS_VALID; an N3 "
                "checkpoint reports oracle_validity NOT_APPLICABLE and therefore "
                "can never satisfy it."
            ),
            "proved": oracle_validity == str(OracleValidity.NOT_APPLICABLE)
            and semantic_interpretation == "NOT_EVALUATED",
        }
    )

    unproved = [item["surface"] for item in checks if not item["proved"]]
    if unproved:
        raise V13BuildError(
            f"the N3/semantic axis separation is unproved on: {unproved}"
        )
    covered = {item["surface"] for item in checks}
    missing = sorted(set(_SEMANTIC_SURFACES) - covered)
    if missing:
        raise V13BuildError(f"axis separation left semantic surfaces unproved: {missing}")

    material = {
        "schema_version": "semantic-benchmark-axis-separation/1.3.0",
        "benchmark_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "semantic_result_states": list(SEMANTIC_RESULT_STATES),
        "semantic_result_states_closed": True,
        "n3_safety_verdicts": list(N3_SAFETY_VERDICTS),
        "axes_are_disjoint": True,
        "n3_is_a_semantic_property": False,
        "n3_is_an_eighth_result_state": False,
        "n3_in_accepted_semantic_rate": False,
        "required_surfaces": list(_SEMANTIC_SURFACES),
        "checks": checks,
        "all_surfaces_proved": True,
    }
    return {**material, "separation_hash": canonical_hash(material)}
