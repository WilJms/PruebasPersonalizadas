"""``semantic-benchmark/1.3.4`` -- fail-closed N3 population repair.

1.3.3 remains immutable historical evidence.  This version repairs the two
pre-execution defects in the executable N3 collection consumers: selection-side
aggregation and held-out confirmation now validate a closed verdict vocabulary
and an exact one-row-per-preregistered-exposure population before deriving any
clearance, promotion or qualification result.

No provider or adjudicator result informed this repair.  The corpus, semantic
routes/properties/bars, candidate identities, provider fixtures, call budget,
construct-selection rule and U3 disposition are unchanged.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import canonical_hash
from .n3_provider_fixtures import n3_provider_fixture_authority
from .p06_n3_protocol import (
    N3_ADJUDICATION_COLLECTION_REQUIREMENTS,
    N3_ADJUDICATION_POPULATION_CONTRACT,
    N3_CORE,
    N3_HELD_OUT_CONFIRMATION,
    N3_PROTOCOL_VERSION,
    N3_SAFETY_SMOKE,
    N3_SAFETY_VERDICTS,
)
from .p06_support_status_coverage import CONTRACT_SUPPORT_STATUSES
from .semantic_benchmark import DEFAULT_CORPUS_ROOT
from .semantic_benchmark_v13 import (
    REPOSITORY_ROOT,
    V13Build,
    V13BuildError,
    build_v13,
)
from .semantic_benchmark_v13_boundary import n3_axis_authority
from .semantic_benchmark_v131 import HashManifestError
from .semantic_benchmark_v133 import (
    SEMANTIC_BENCHMARK_V133_VERSION,
)


SEMANTIC_BENCHMARK_V134_VERSION = "semantic-benchmark/1.3.4"
BENCHMARK_BOUNDARY_FORMAT_V134 = "semantic-benchmark-boundary/1.3.4"
PROTOCOL_VERSION_V134 = "phase9-qualification-protocol/1.3.4"
CANDIDATE_MATRIX_VERSION_V134 = "phase9-candidate-matrix/1.3.4"
CLAIM_VERSION_V134 = "p06-semantic-qualification-claim/1.3.4"

V133_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_3"
V133_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_3"
DEFINITION_ROOT = "evaluation/semantic_benchmark/v1_3_4"
REPORT_ROOT = "reports/semantic_benchmark/v1_3_4"

V133_SUPERSEDED_STATUS = (
    "SUPERSEDED_PREEXECUTION_FREEZE_CANDIDATE_NO_RESULTS_EXECUTED"
)
V134_STATUS = "PREEXECUTION_FREEZE_CANDIDATE"

SEMANTIC_QUALIFICATION_CLAIM_V134 = (
    f"{SEMANTIC_BENCHMARK_V134_VERSION} qualifies P06 candidate behaviour on the "
    "support statuses SUFFICIENT, PARTIAL and INSUFFICIENT."
)
U3_LIMITATIONS_V134: tuple[str, ...] = (
    f"{SEMANTIC_BENCHMARK_V134_VERSION} does NOT qualify P06 UNCERTAIN behaviour.",
    "P06 model-selection claims are limited to SUFFICIENT / PARTIAL / INSUFFICIENT.",
    "UNCERTAIN remains an explicit residual risk.",
    "Phase 9 alone does not establish full P06 contract coverage.",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialize(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def build_v134(corpus_root: Path = DEFAULT_CORPUS_ROOT) -> V13Build:
    """Reuse the frozen semantic instrument; only N3 collection handling moves."""

    return build_v13(corpus_root)


# Complete documents whose bytes remain valid authority in 1.3.4.  Their old
# version stamps are provenance, not active claims inferred from lineage.
REPUBLISHED_FROM_V133: Mapping[str, tuple[str, str]] = {
    f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json": (
        "definition",
        "phase9/uncertain_coverage_disposition.json",
    ),
    f"{DEFINITION_ROOT}/phase9/construct_selection_semantics.json": (
        "definition",
        "phase9/construct_selection_semantics.json",
    ),
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": (
        "definition",
        "phase9/n3_provider_fixtures.json",
    ),
    f"{REPORT_ROOT}/phase9/call_budget.json": ("report", "phase9/call_budget.json"),
    f"{REPORT_ROOT}/phase9/noisy_disposition_census.json": (
        "report",
        "phase9/noisy_disposition_census.json",
    ),
    f"{REPORT_ROOT}/phase9/construct_selection_independence.json": (
        "report",
        "phase9/construct_selection_independence.json",
    ),
    f"{REPORT_ROOT}/phase9/n3_production_representativeness.json": (
        "report",
        "phase9/n3_production_representativeness.json",
    ),
    f"{REPORT_ROOT}/phase9/n3_fixture_equality_proof.json": (
        "report",
        "phase9/n3_fixture_equality_proof.json",
    ),
}


def _v133_source(relative: str) -> Path:
    kind, tail = REPUBLISHED_FROM_V133[relative]
    root = V133_DEFINITION_ROOT if kind == "definition" else V133_REPORT_ROOT
    return root / tail


def republished_documents() -> dict[str, dict[str, Any]]:
    return {
        relative: _json(_v133_source(relative))
        for relative in sorted(REPUBLISHED_FROM_V133)
    }


def _assert_provider_fixtures_unchanged(fixtures: Mapping[str, Any]) -> None:
    relative = f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json"
    source = _v133_source(relative)
    if _serialize(fixtures) != source.read_bytes():
        raise V13BuildError(
            "the N3 provider fixture population changed during the collection-only "
            "1.3.4 repair"
        )


def n3_axis_v134(build: V13Build) -> dict[str, Any]:
    """Publish the repaired executable N3 axis and bind its new source hash."""

    derived = n3_axis_authority(build)
    previous = _json(
        V133_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    )
    for key in (
        "verdicts",
        "exposure_population",
        "selectors",
        "stage_plan",
        "lifecycle",
        "held_out_lock",
        "census",
        "contractual_policy_authority",
        "violation_classes",
        "field_authority",
        "packet",
        "confirmation_requirements",
        "forbidden_confirmation_dependencies",
        "two_pass",
    ):
        if derived[key] != previous[key]:
            raise V13BuildError(
                f"1.3.4 may not change frozen N3 authority outside collection "
                f"validation: {key}"
            )
    if derived["protocol_source_hash"] == previous["protocol_source_hash"]:
        raise V13BuildError(
            "the repaired N3 source reproduced the defective 1.3.3 source hash"
        )

    material = {
        key: value for key, value in derived.items() if key != "n3_axis_hash"
    }
    material.update(
        {
            "schema_version": "semantic-benchmark-n3-axis/1.3.4",
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "supersedes_n3_axis_hash": previous["n3_axis_hash"],
            "repair_scope": "N3_ADJUDICATION_COLLECTION_FAIL_CLOSED_VALIDATION",
            "repaired_defects": [
                "SELECTION_SIDE_ACCEPTED_NON_BIJECTIVE_OR_UNKNOWN_VERDICT_ROWS",
                "HELD_OUT_ACCEPTED_UNKNOWN_VERDICTS_AS_CLEARANCE",
            ],
            "adjudication_population_validation": {
                "contract": N3_ADJUDICATION_POPULATION_CONTRACT,
                "requirements": list(N3_ADJUDICATION_COLLECTION_REQUIREMENTS),
                "closed_verdict_vocabulary": list(N3_SAFETY_VERDICTS),
                "validation_precedes_clearance_promotion_or_qualification": True,
                "selection_expected_population_authority": (
                    "FROZEN_N3_STAGE_PLAN_FOR_N3_SAFETY_SMOKE_AND_N3_CORE"
                ),
                "held_out_expected_population_authority": (
                    "ALL_AND_ONLY_FROZEN_HELD_OUT_EXPOSURES"
                ),
                "malformed_collection_consequence": "RAISE_N3_PROTOCOL_ERROR",
            },
        }
    )
    return {**material, "n3_axis_hash": canonical_hash(material)}


def semantic_qualification_claim_v134(build: V13Build) -> dict[str, Any]:
    """Rebind the unchanged narrowed U3 claim to the active benchmark version."""

    previous = _json(
        V133_DEFINITION_ROOT / "phase9/semantic_qualification_claim.json"
    )
    current_counts = {
        status: build.support_status_coverage["statuses"][status][
            "candidate_scoring_property_count"
        ]
        for status in CONTRACT_SUPPORT_STATUSES
    }
    if current_counts != previous["candidate_scoring_property_count_by_status"]:
        raise V13BuildError("the P06 support-status scoring census changed in 1.3.4")

    material = {key: value for key, value in previous.items() if key != "claim_hash"}
    history = [*material["historical_claim_lineage"]]
    history.append(
        {
            "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "status": V133_SUPERSEDED_STATUS,
            "claim_named_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "uncertain_gap_state": "RESOLVED",
            "correct_when_published": True,
            "superseded_because": (
                "fresh pre-execution falsification found two fail-open N3 "
                "adjudication-population consumers outside the semantic claim"
            ),
        }
    )
    material.update(
        {
            "schema_version": CLAIM_VERSION_V134,
            "applicable_benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "supersedes_claim_binding_from": SEMANTIC_BENCHMARK_V133_VERSION,
            "claim_semantics_changed_from_v133": False,
            "what_changed": (
                "Only the claim's explicit benchmark applicability advances to "
                "1.3.4. The N3 executable repair does not change which semantic "
                "support-status behaviour is qualified."
            ),
            "why_a_new_hash": (
                "The claim text names the benchmark version it applies to; 1.3.4 "
                "may not publish a current claim naming superseded 1.3.3."
            ),
            "claim": SEMANTIC_QUALIFICATION_CLAIM_V134,
            "limitations": list(U3_LIMITATIONS_V134),
            "limitation_count": len(U3_LIMITATIONS_V134),
            "production_contract_note": (
                "UNCERTAIN remains a first-class member of the P06 support-status "
                "contract. 1.3.4 changes no production prompt, DTO, materializer "
                "or planner semantics; it repairs only N3 adjudication collection "
                "validation and preserves the narrowed U3 claim."
            ),
            "historical_claim_lineage": history,
        }
    )
    return {**material, "claim_hash": canonical_hash(material)}


def p06_stage_boundary_v134(
    n3_axis: Mapping[str, Any], claim: Mapping[str, Any]
) -> dict[str, Any]:
    previous_doc = _json(V133_REPORT_ROOT / "stage_boundaries.json")
    previous = previous_doc["stages"]["P06"]
    material = {
        key: value
        for key, value in previous.items()
        if key
        not in {
            "stage_boundary_hash",
            "supersedes_v132_p06_boundary",
        }
    }
    material.update(
        {
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "boundary_status": "NEW_IN_V134",
            "new_because": (
                "The N3 executable source and axis now bind exact adjudication "
                "population validation before selection-side promotion and "
                "held-out confirmation. The version-bound semantic claim also "
                "advances to 1.3.4 without changing its semantics."
            ),
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_claim_version": claim["schema_version"],
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed": False,
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "n3_protocol_version": n3_axis["protocol_version"],
            "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
            "n3_aggregation_rules": dict(n3_axis["aggregation"]),
            "n3_promotion_rules": dict(n3_axis["promotion_gates"]),
            "n3_provider_fixture_set_hash_unchanged_from_v133": True,
            "supersedes_v133_p06_boundary": previous["stage_boundary_hash"],
        }
    )
    material.pop("n3_provider_fixture_set_hash_unchanged_from_v132", None)
    dependency = "N3 exact adjudication-population validation and closed verdict vocabulary"
    if dependency not in material["dependency_inventory"]:
        material["dependency_inventory"] = [
            *material["dependency_inventory"],
            dependency,
        ]
    boundary = {**material, "stage_boundary_hash": canonical_hash(material)}
    if boundary["stage_boundary_hash"] == previous["stage_boundary_hash"]:
        raise V13BuildError("the repaired P06 boundary reproduced the 1.3.3 hash")
    return boundary


def stage_boundaries_v134(
    n3_axis: Mapping[str, Any], claim: Mapping[str, Any]
) -> dict[str, Any]:
    previous = _json(V133_REPORT_ROOT / "stage_boundaries.json")
    stages: dict[str, dict[str, Any]] = {
        "P06": p06_stage_boundary_v134(n3_axis, claim)
    }
    for stage in ("P04", "P07", "P09", "PLANNER"):
        old = previous["stages"][stage]
        carried = dict(old)
        carried.update(
            {
                "boundary_status": "CARRIED_FORWARD_FROM_V133",
                "carried_forward_from_benchmark_version": (
                    SEMANTIC_BENCHMARK_V133_VERSION
                ),
                "carry_forward_is_valid_because": (
                    "The 1.3.4 repair touches only P06 N3 adjudication collection "
                    "validation. This stage binds no N3 aggregation or held-out "
                    "confirmation consumer, and its frozen stage hash is unchanged."
                ),
                "v134_change_proof": {
                    "from_version": SEMANTIC_BENCHMARK_V133_VERSION,
                    "to_version": SEMANTIC_BENCHMARK_V134_VERSION,
                    "stage_local_material_changed": False,
                    "v133_frozen_boundary_hash": old["stage_boundary_hash"],
                    "v134_carried_boundary_hash": old["stage_boundary_hash"],
                    "equal": True,
                },
            }
        )
        stages[stage] = carried

    hashes = {stage: row["stage_boundary_hash"] for stage, row in stages.items()}
    statuses = {stage: row["boundary_status"] for stage, row in stages.items()}
    material = {
        "schema_version": "semantic-benchmark-stage-boundaries/1.3.4",
        "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
        "previous_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "previous_version_status": V133_SUPERSEDED_STATUS,
        "stages": stages,
        "stage_boundary_hashes": hashes,
        "boundary_status_by_stage": statuses,
        "new_boundary_stages": ["P06"],
        "carried_forward_stages": ["P04", "P07", "P09", "PLANNER"],
        "v133_stage_boundary_hashes": dict(previous["stage_boundary_hashes"]),
    }
    return {**material, "stage_boundaries_hash": canonical_hash(material)}


def benchmark_boundary_v134(
    n3_axis: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(V133_REPORT_ROOT / "benchmark_boundary.json")
    material = {
        key: value for key, value in previous.items() if key != "benchmark_boundary_hash"
    }
    shared = dict(material["shared_benchmark_authority"])
    shared.update(
        {
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "accepted_rate_bars_changed_from_v133": False,
        }
    )
    shared.pop("accepted_rate_bars_changed_from_v132", None)
    aggregation = dict(material["cross_stage_aggregation_authority"])
    aggregation["benchmark_version"] = SEMANTIC_BENCHMARK_V134_VERSION
    material.update(
        {
            "boundary_format": BENCHMARK_BOUNDARY_FORMAT_V134,
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "previous_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "previous_version_status": V133_SUPERSEDED_STATUS,
            "shared_benchmark_authority": shared,
            "cross_stage_aggregation_authority": aggregation,
            "stage_boundaries_hash": stage_boundaries["stage_boundaries_hash"],
            "stage_boundary_hashes": dict(stage_boundaries["stage_boundary_hashes"]),
            "boundary_status_by_stage": dict(
                stage_boundaries["boundary_status_by_stage"]
            ),
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "uncertain_coverage_disposition_hash": disposition["disposition_hash"],
        }
    )
    dependency = "N3 exact adjudication-population validation"
    if dependency not in material["documented_dependencies"]:
        material["documented_dependencies"] = [
            *material["documented_dependencies"],
            dependency,
        ]
    return {**material, "benchmark_boundary_hash": canonical_hash(material)}


def candidate_matrix_v134(
    *, benchmark_boundary_hash: str
) -> dict[str, Any]:
    previous = _json(V133_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    material = {
        key: value for key, value in previous.items() if key != "candidate_matrix_hash"
    }
    material.update(
        {
            "schema_version": CANDIDATE_MATRIX_VERSION_V134,
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "protocol_version": PROTOCOL_VERSION_V134,
            "benchmark_boundary_hash": benchmark_boundary_hash,
            "candidate_identities_changed_from_v133": False,
            "carried_candidate_identity_hash": canonical_hash(previous["candidates"]),
            "new_hash_reason": (
                "Candidate identities, rungs and families are byte-identical to "
                "1.3.3. The matrix hash moves because it binds the 1.3.4 protocol "
                "and global boundary after the N3 fail-closed repair."
            ),
        }
    )
    material.pop("candidate_identities_changed_from_v132", None)
    return {**material, "candidate_matrix_hash": canonical_hash(material)}


def qualification_protocol_v134(
    n3_axis: Mapping[str, Any],
    claim: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(V133_DEFINITION_ROOT / "phase9/qualification_protocol.json")
    material = {
        key: value
        for key, value in previous.items()
        if key != "protocol_boundary_hash"
    }
    gates = dict(material["n3_gates"])
    gates.update(
        {
            "adjudication_population_contract": N3_ADJUDICATION_POPULATION_CONTRACT,
            "adjudication_collection_requirements": list(
                N3_ADJUDICATION_COLLECTION_REQUIREMENTS
            ),
            "closed_verdict_vocabulary": list(N3_SAFETY_VERDICTS),
            "validation_precedes_clearance_promotion_or_qualification": True,
            "exactly_one_row_per_expected_stage_exposure": True,
            "unknown_duplicate_foreign_or_missing_rows_fail_closed": True,
        }
    )
    expected = {
        N3_SAFETY_SMOKE: list(
            n3_axis["selectors"]["safety_smoke"]["exposure_ids"]
        ),
        N3_CORE: list(n3_axis["selectors"]["core_exposure_ids"]),
        N3_HELD_OUT_CONFIRMATION: list(
            n3_axis["selectors"]["held_out_exposure_ids"]
        ),
    }
    material.update(
        {
            "schema_version": PROTOCOL_VERSION_V134,
            "protocol_version": PROTOCOL_VERSION_V134,
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "previous_protocol_version": previous["protocol_version"],
            "reason_for_new_version": [
                "selection-side N3 aggregation now validates the exact frozen "
                "stage population and closed verdict vocabulary before promotion",
                "held-out N3 confirmation now validates exactly one valid row for "
                "every frozen held-out exposure before qualification",
                "the P06 and global benchmark boundaries changed transitively",
            ],
            "benchmark_boundary_hash": benchmark_boundary[
                "benchmark_boundary_hash"
            ],
            "candidate_matrix_hash": candidate_matrix["candidate_matrix_hash"],
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_limitations": list(claim["limitations"]),
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_claim_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed_from_v133": False,
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "n3_protocol_version": n3_axis["protocol_version"],
            "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
            "n3_expected_exposure_ids_by_stage": expected,
            "n3_gates": gates,
        }
    )
    return {**material, "protocol_boundary_hash": canonical_hash(material)}


def carry_forward_equality_proof_v134(
    build: V13Build,
    n3_axis: Mapping[str, Any],
    claim: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove unchanged bytes/material and enumerate the expected transitive delta."""

    carried_rows: list[dict[str, Any]] = []
    for relative in sorted(REPUBLISHED_FROM_V133):
        source = _v133_source(relative)
        reproduced = _serialize(_json(source))
        identical = reproduced == source.read_bytes()
        if not identical:
            raise V13BuildError(f"{relative} is not byte-identical to 1.3.3")
        carried_rows.append(
            {
                "v134_path": relative,
                "v133_source_path": source.relative_to(REPOSITORY_ROOT).as_posix(),
                "v133_file_sha256": _sha256_file(source),
                "v134_reproduced_file_sha256": _sha256_bytes(reproduced),
                "bytes_identical": True,
            }
        )

    previous_axis = _json(
        V133_DEFINITION_ROOT / "phase9/n3_contractual_safety_axis.json"
    )
    previous_matrix = _json(V133_DEFINITION_ROOT / "phase9/candidate_matrix.json")
    previous_claim = _json(
        V133_DEFINITION_ROOT / "phase9/semantic_qualification_claim.json"
    )
    previous_boundaries = _json(V133_REPORT_ROOT / "stage_boundaries.json")
    equalities = {
        "corpus_package_hash": build.package_hash
        == "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1",
        "p06_route_count": len(build.derivation.routes) == 71,
        "p06_candidate_scoring_property_count": len(
            build.derivation.scoring_property_ids
        )
        == 69,
        "n3_verdict_vocabulary": n3_axis["verdicts"] == previous_axis["verdicts"],
        "n3_exposure_population": n3_axis["exposure_population"]
        == previous_axis["exposure_population"],
        "n3_selectors": n3_axis["selectors"] == previous_axis["selectors"],
        "n3_stage_plan": n3_axis["stage_plan"] == previous_axis["stage_plan"],
        "candidate_identities": candidate_matrix["candidates"]
        == previous_matrix["candidates"],
        "semantic_claim_status_sets": claim["qualified_support_statuses"]
        == previous_claim["qualified_support_statuses"]
        and claim["excluded_support_statuses"]
        == previous_claim["excluded_support_statuses"],
        "non_p06_stage_hashes": all(
            stage_boundaries["stage_boundary_hashes"][stage]
            == previous_boundaries["stage_boundary_hashes"][stage]
            for stage in ("P04", "P07", "P09", "PLANNER")
        ),
    }
    failed = sorted(name for name, equal in equalities.items() if not equal)
    if failed:
        raise V13BuildError(f"1.3.4 carry-forward equality failed: {failed}")
    material = {
        "schema_version": "semantic-carry-forward-equality-proof/1.3.4",
        "from_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V134_VERSION,
        "carried_forward_artifacts": carried_rows,
        "carried_forward_artifact_count": len(carried_rows),
        "material_equalities": equalities,
        "all_required_equalities_hold": True,
        "changed_components": [
            "p06_n3_protocol.py FILE_SHA256",
            "N3 axis hash",
            "P06 stage boundary hash",
            "stage-boundaries document hash",
            "global benchmark boundary hash",
            "version-bound semantic claim hash",
            "qualification protocol hash",
            "candidate matrix hash",
            "lineage/scans/freeze/manifest hashes",
        ],
        "unchanged_semantics": [
            "71 P06 executable routes",
            "69 P06 candidate-scoring properties",
            "SUFFICIENT/PARTIAL/INSUFFICIENT qualified; UNCERTAIN uncovered",
            "0.80 SMOKE and 0.95 CORE/HELD_OUT accepted-rate bars",
            "N3 1 SAFETY_SMOKE / 6 CORE / 3 HELD_OUT population",
            "FIRST_AUTHORIZED_CONSTRUCT_IN_CANONICAL_SOURCE_ORDER",
            "candidate identities and reasoning rungs",
            "provider fixture inputs and call budget",
        ],
    }
    return {**material, "proof_hash": canonical_hash(material)}


def lineage_v134() -> dict[str, Any]:
    previous = _json(V133_REPORT_ROOT / "lineage.json")
    carried = {
        relative: {
            "originating_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "source_path": _v133_source(relative)
            .relative_to(REPOSITORY_ROOT)
            .as_posix(),
            "bytes_identical": True,
        }
        for relative in sorted(REPUBLISHED_FROM_V133)
    }
    material = {
        "schema_version": "semantic-benchmark-lineage/1.3.4",
        "from_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "to_version": SEMANTIC_BENCHMARK_V134_VERSION,
        "chain": [
            *previous["chain"][:-1],
            {
                **previous["chain"][-1],
                "status": V133_SUPERSEDED_STATUS,
                "superseded_because": [
                    "qualification-side N3 aggregation did not reject unknown "
                    "verdicts, duplicate identities, foreign identities or a "
                    "same-count malformed preregistered population",
                    "held-out N3 confirmation could pass exact held-out identities "
                    "whose verdicts were outside the closed N3 vocabulary",
                ],
                "bytes_modified_by_v134": False,
            },
            {
                "version": SEMANTIC_BENCHMARK_V134_VERSION,
                "status": V134_STATUS,
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
            },
        ],
        "v133_lineage_hash": previous["lineage_hash"],
        "v133_bytes_modified": False,
        "v133_preserved_as_historical_evidence": True,
        "is_a_corpus_change": False,
        "is_a_semantic_product_decision_change": False,
        "is_a_pre_execution_n3_fail_closed_repair": True,
        "no_provider_or_adjudicator_outcome_informed_the_repair": True,
        "repair_scope": [
            "n3_rung_aggregate exact adjudication collection validation",
            "n3_held_out_confirmation exact adjudication collection validation",
        ],
        "replaced": {
            "phase9/n3_contractual_safety_axis.json": (
                "binds the repaired executable source and exact collection contract"
            ),
            "P06 stage boundary": "moves with the repaired N3 axis",
            "global benchmark boundary": "moves with the P06 boundary",
            "phase9/qualification_protocol.json": (
                "makes the closed vocabulary and exact stage populations explicit"
            ),
            "phase9/candidate_matrix.json": (
                "candidate identities unchanged; binds the new protocol/boundary"
            ),
        },
        "carried_forward_artifacts": carried,
        "carried_forward_artifact_count": len(carried),
        "silent_carry_forward_permitted": False,
    }
    return {**material, "lineage_hash": canonical_hash(material)}


def _walk_values(
    node: Any, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _walk_values(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_values(value, (*path, f"[{index}]"))
    else:
        yield path, node


_ACTIVE_CLAIM_FIELDS = frozenset(
    {
        "claim",
        "semantic_qualification_claim",
        "limitations",
        "semantic_qualification_limitations",
        "semantic_claim_limitations",
    }
)
_HISTORICAL_FIELDS = frozenset(
    {
        "chain",
        "historical_claim_lineage",
        "previous_version",
        "previous_version_status",
        "from_version",
        "supersedes_claim_binding_from",
        "supersedes_v133_p06_boundary",
        "carried_forward_from_benchmark_version",
        "carry_forward_is_valid_because",
        "v134_change_proof",
        "reason_for_new_version",
        "new_because",
        "new_hash_reason",
        "replaced",
        "changed_components",
        "carried_forward_artifacts",
        "results_firewall",
    }
)


def stale_claim_scan_v134(
    package: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    violations: list[str] = []
    checked = 0
    for relative, document in sorted(package.items()):
        if relative in REPUBLISHED_FROM_V133:
            continue
        for path, value in _walk_values(document):
            if not isinstance(value, str) or SEMANTIC_BENCHMARK_V133_VERSION not in value:
                continue
            if any(segment in _HISTORICAL_FIELDS for segment in path):
                continue
            if any(segment in _ACTIVE_CLAIM_FIELDS for segment in path):
                violations.append(f"{relative}::{'.'.join(path)}")
            checked += 1
    if violations:
        raise V13BuildError(f"active 1.3.4 claims still name 1.3.3: {violations}")
    material = {
        "schema_version": "semantic-benchmark-stale-claim-scan/1.3.4",
        "active_benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
        "superseded_version_scanned_for": SEMANTIC_BENCHMARK_V133_VERSION,
        "active_claim_occurrences_checked": checked,
        "violations": [],
        "violation_count": 0,
        "republished_unchanged_artifacts": sorted(REPUBLISHED_FROM_V133),
    }
    return {**material, "scan_hash": canonical_hash(material)}


def product_decision_state_scan_v134(
    package: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    violations: list[str] = []
    for relative, document in sorted(package.items()):
        if relative in REPUBLISHED_FROM_V133:
            continue
        for path, value in _walk_values(document):
            if any(segment in _HISTORICAL_FIELDS for segment in path):
                continue
            if path and path[-1] in {
                "readiness_blocked",
                "requires_product_decision",
                "uncertain_coverage_requires_product_decision",
            } and value is True:
                violations.append(f"{relative}::{'.'.join(path)}")
    if violations:
        raise V13BuildError(
            f"active 1.3.4 authority reopens the resolved U3 decision: {violations}"
        )
    material = {
        "schema_version": "p06-uncertain-product-decision-state-scan/1.3.4",
        "active_benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
        "violations": [],
        "violation_count": 0,
        "active_requires_product_decision": False,
        "active_readiness_blocked": False,
    }
    return {**material, "scan_hash": canonical_hash(material)}


def pre_results_freeze_v134(
    n3_axis: Mapping[str, Any],
    claim: Mapping[str, Any],
    disposition: Mapping[str, Any],
    *,
    benchmark_boundary: Mapping[str, Any],
    stage_boundaries: Mapping[str, Any],
    qualification_protocol: Mapping[str, Any],
    candidate_matrix: Mapping[str, Any],
    lineage: Mapping[str, Any],
    equality_proof: Mapping[str, Any],
    stale_scan: Mapping[str, Any],
    decision_scan: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _json(
        V133_REPORT_ROOT / "phase9/pre_results_instrument_freeze.json"
    )
    material = {
        key: value for key, value in previous.items() if key != "freeze_material_hash"
    }
    material.update(
        {
            "schema_version": "phase9-pre-results-instrument-freeze/1.3.4",
            "phase": "9B.8D",
            "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
            "previous_version": SEMANTIC_BENCHMARK_V133_VERSION,
            "previous_version_status": V133_SUPERSEDED_STATUS,
            "status": V134_STATUS,
            "purpose": (
                "Freeze the minimal pre-execution N3 fail-closed collection repair "
                "before any provider or adjudicator execution."
            ),
            "file_sha256_and_git_blob_sha_live_in": (
                f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
            ),
            "global_benchmark_boundary_hash": benchmark_boundary[
                "benchmark_boundary_hash"
            ],
            "stage_boundaries_hash": stage_boundaries["stage_boundaries_hash"],
            "stage_boundary_hashes": dict(stage_boundaries["stage_boundary_hashes"]),
            "boundary_status_by_stage": dict(
                stage_boundaries["boundary_status_by_stage"]
            ),
            "protocol_version": qualification_protocol["protocol_version"],
            "protocol_boundary_hash": qualification_protocol[
                "protocol_boundary_hash"
            ],
            "candidate_matrix_hash": candidate_matrix["candidate_matrix_hash"],
            "n3_axis_hash": n3_axis["n3_axis_hash"],
            "n3_protocol_version": N3_PROTOCOL_VERSION,
            "n3_protocol_source_hash": n3_axis["protocol_source_hash"],
            "n3_promotion_gates": dict(n3_axis["promotion_gates"]),
            "n3_adjudication_population_contract": (
                N3_ADJUDICATION_POPULATION_CONTRACT
            ),
            "n3_adjudication_collection_requirements": list(
                N3_ADJUDICATION_COLLECTION_REQUIREMENTS
            ),
            "n3_closed_verdict_vocabulary": list(N3_SAFETY_VERDICTS),
            "n3_expected_exposure_ids_by_stage": qualification_protocol[
                "n3_expected_exposure_ids_by_stage"
            ],
            "n3_provider_fixture_set_hash_unchanged_from_v133": True,
            "semantic_qualification_claim": claim["claim"],
            "semantic_qualification_claim_hash": claim["claim_hash"],
            "semantic_claim_limitations": list(claim["limitations"]),
            "semantic_qualification_applicable_benchmark_version": claim[
                "applicable_benchmark_version"
            ],
            "semantic_qualification_supersedes_claim_binding_from": claim[
                "supersedes_claim_binding_from"
            ],
            "semantic_qualification_semantics_changed_from_v133": False,
            "uncertain_coverage_disposition_hash": disposition["disposition_hash"],
            "semantic_carry_forward_equality_proof_hash": equality_proof[
                "proof_hash"
            ],
            "stale_claim_scan_hash": stale_scan["scan_hash"],
            "stale_claim_violation_count": stale_scan["violation_count"],
            "product_decision_state_scan_hash": decision_scan["scan_hash"],
            "product_decision_state_violation_count": decision_scan[
                "violation_count"
            ],
            "lineage_hash": lineage["lineage_hash"],
            "v133_preserved": {
                "v133_bytes_modified": False,
                "status": V133_SUPERSEDED_STATUS,
            },
            "results_firewall": {
                "candidate_outcomes_read": False,
                "first_pass_adjudication_results_read": False,
                "provider_outputs_read": False,
                "historical_qualification_results_used_as_construction_authority": (
                    False
                ),
                "note": (
                    "No provider or adjudicator outcome informed 1.3.4. The repair "
                    "was derived solely from offline executable falsification."
                ),
            },
            "execution_counters": {
                "provider_calls": 0,
                "adjudicator_calls": 0,
                "credentials_resolved": 0,
                "real_transport_constructed": False,
                "pricing_refreshed": False,
                "high_smoke_authorized": False,
                "billable_authorizations": 0,
                "spend_authorized": False,
                "candidate_outcomes_read": False,
                "authorization": "NONE",
            },
            "qualification_run": False,
            "high_smoke_authorized": False,
            "corpus_bytes_modified": False,
            "stop_condition": (
                "SEMANTIC_BENCHMARK_V1_3_4_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT"
            ),
        }
    )
    material.pop("n3_provider_fixture_set_hash_unchanged_from_v132", None)
    material.pop("semantic_invariant_equality_proof_hash", None)
    material.pop("semantic_qualification_semantics_changed_from_v132", None)
    return {**material, "freeze_material_hash": canonical_hash(material)}


SELF_MATERIAL_HASH_FIELD: Mapping[str, str | None] = {
    f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": "protocol_boundary_hash",
    f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": "candidate_matrix_hash",
    f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": "claim_hash",
    f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json": "disposition_hash",
    f"{DEFINITION_ROOT}/phase9/construct_selection_semantics.json": "semantics_hash",
    f"{DEFINITION_ROOT}/phase9/n3_provider_fixtures.json": "fixture_set_hash",
    f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": "n3_axis_hash",
    f"{REPORT_ROOT}/lineage.json": "lineage_hash",
    f"{REPORT_ROOT}/stage_boundaries.json": "stage_boundaries_hash",
    f"{REPORT_ROOT}/benchmark_boundary.json": "benchmark_boundary_hash",
    f"{REPORT_ROOT}/phase9/call_budget.json": "call_budget_hash",
    f"{REPORT_ROOT}/phase9/noisy_disposition_census.json": "census_hash",
    f"{REPORT_ROOT}/phase9/construct_selection_independence.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/n3_production_representativeness.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/n3_fixture_equality_proof.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/semantic_carry_forward_equality_proof.json": "proof_hash",
    f"{REPORT_ROOT}/phase9/stale_claim_scan.json": "scan_hash",
    f"{REPORT_ROOT}/phase9/product_decision_state_scan.json": "scan_hash",
    f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json": "freeze_material_hash",
}


def self_material_hash(path: str, document: Mapping[str, Any]) -> str | None:
    if path not in SELF_MATERIAL_HASH_FIELD:
        raise HashManifestError(f"{path} has no explicit self-hash registry entry")
    field = SELF_MATERIAL_HASH_FIELD[path]
    if field is None:
        return None
    if field not in document:
        raise HashManifestError(f"{path} declares absent self hash field {field!r}")
    declared = document[field]
    recomputed = canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )
    if declared != recomputed:
        raise HashManifestError(
            f"{path}.{field} declares {declared} but its material hashes to "
            f"{recomputed}"
        )
    return declared


def v134_package(build: V13Build) -> dict[str, dict[str, Any]]:
    """Return every generated 1.3.4 document without writing any file."""

    carried = republished_documents()
    fixtures = n3_provider_fixture_authority(build.corpus_root)
    _assert_provider_fixtures_unchanged(fixtures)
    n3_axis = n3_axis_v134(build)
    disposition = carried[
        f"{DEFINITION_ROOT}/phase9/uncertain_coverage_disposition.json"
    ]
    claim = semantic_qualification_claim_v134(build)
    boundaries = stage_boundaries_v134(n3_axis, claim)
    global_boundary = benchmark_boundary_v134(
        n3_axis, claim, disposition, boundaries
    )
    matrix = candidate_matrix_v134(
        benchmark_boundary_hash=global_boundary["benchmark_boundary_hash"]
    )
    protocol = qualification_protocol_v134(
        n3_axis,
        claim,
        benchmark_boundary=global_boundary,
        candidate_matrix=matrix,
    )
    equality = carry_forward_equality_proof_v134(
        build, n3_axis, claim, matrix, boundaries
    )
    lineage = lineage_v134()

    package: dict[str, dict[str, Any]] = {
        **carried,
        f"{DEFINITION_ROOT}/phase9/n3_contractual_safety_axis.json": n3_axis,
        f"{DEFINITION_ROOT}/phase9/semantic_qualification_claim.json": claim,
        f"{DEFINITION_ROOT}/phase9/qualification_protocol.json": protocol,
        f"{DEFINITION_ROOT}/phase9/candidate_matrix.json": matrix,
        f"{REPORT_ROOT}/lineage.json": lineage,
        f"{REPORT_ROOT}/stage_boundaries.json": boundaries,
        f"{REPORT_ROOT}/benchmark_boundary.json": global_boundary,
        f"{REPORT_ROOT}/phase9/semantic_carry_forward_equality_proof.json": equality,
    }
    stale = stale_claim_scan_v134(package)
    decision = product_decision_state_scan_v134(package)
    freeze = pre_results_freeze_v134(
        n3_axis,
        claim,
        disposition,
        benchmark_boundary=global_boundary,
        stage_boundaries=boundaries,
        qualification_protocol=protocol,
        candidate_matrix=matrix,
        lineage=lineage,
        equality_proof=equality,
        stale_scan=stale,
        decision_scan=decision,
    )
    package[f"{REPORT_ROOT}/phase9/stale_claim_scan.json"] = stale
    package[f"{REPORT_ROOT}/phase9/product_decision_state_scan.json"] = decision
    package[f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"] = freeze

    # Closing validation covers the freeze as an active authority without
    # inserting self-referential output into either scan artifact.
    stale_claim_scan_v134(package)
    product_decision_state_scan_v134(package)
    return package
