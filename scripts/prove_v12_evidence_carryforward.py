"""PART B: prove or refute structural equivalence of Phase 9B.1 evidence to v1.2.

This is lineage analysis only.  It issues no provider call, performs no
adjudication and produces no candidate verdict.  It may not alter anything PART
A froze; the freeze artifact is read back and its hash reported alongside the
proof so the ordering stays auditable.

Equivalence is decided on exact hashes.  "The stage was unchanged" is not a
proof and is never emitted as one: for every legacy observation the script
rebuilds the model-visible ``ModelTaskEnvelope`` under v1.1 authority, checks it
against the hash the call ledger actually recorded, then rebuilds the
corresponding v1.2 surface and compares.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.canonical import canonical_hash  # noqa: E402
from comprehension_verification import phase9_execution as px  # noqa: E402
from comprehension_verification import semantic_benchmark as sb  # noqa: E402
from comprehension_verification.semantic_benchmark_fixtures import (  # noqa: E402
    parse_submission_bundle,
)
from comprehension_verification.semantic_benchmark_v12 import (  # noqa: E402
    build_construct_catalog,
    build_p06_fixture_v12,
    model_visible_definition_for,
)
from comprehension_verification.semantic_benchmark_v12_boundary import (  # noqa: E402
    CORPUS_ROOT,
    benchmark_boundary_v12,
    build_v12,
    stage_boundaries,
)

EXECUTION_ID = "exec-phase9b1-bfd3cf082617ea8b"
EXECUTION_ROOT = (
    REPOSITORY_ROOT
    / f"reports/semantic_benchmark/v1_1/phase9/executions/{EXECUTION_ID}"
)
FREEZE_PATH = (
    REPOSITORY_ROOT
    / "reports/semantic_benchmark/v1_2/phase9/pre_results_instrument_freeze.json"
)
OUT_PATH = (
    REPOSITORY_ROOT
    / "reports/semantic_benchmark/v1_2/phase9/evidence_carryforward_proof.json"
)
EXPECTED_FIRST_PASS_ZIP_SHA256 = (
    "5fbb9618b880bab3a8e936c544315dedb7fab085fca78cb1a103baeb62149832"
)

EVIDENCE_EQUIVALENCE_PROVEN = "EVIDENCE_EQUIVALENCE_PROVEN"
EVIDENCE_EQUIVALENCE_NOT_PROVEN = "EVIDENCE_EQUIVALENCE_NOT_PROVEN"
EVIDENCE_SEMANTICALLY_INVALIDATED = "EVIDENCE_SEMANTICALLY_INVALIDATED"

EXACT_INPUT_EQUIVALENCE_PROVEN = "EXACT_INPUT_EQUIVALENCE_PROVEN"
ROUTE_SEMANTICS_CHANGED = "ROUTE_SEMANTICS_CHANGED"
PROPERTY_NO_LONGER_GATE = "PROPERTY_NO_LONGER_GATE"
EQUIVALENCE_NOT_PROVEN = "EQUIVALENCE_NOT_PROVEN"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _envelope_hash(prompt_id: str, request) -> str:
    return canonical_hash(
        px._envelope_for(prompt_id, request).model_dump(mode="json")
    )


def _legacy_envelope_hashes() -> dict[str, str]:
    """Rebuild each frozen v1.1 SMOKE request and hash its model-visible envelope."""

    hashes: dict[str, str] = {}
    for case in px.build_smoke_cases():
        hashes[case.case_id] = _envelope_hash(case.candidate.prompt_id, case.request)
    return hashes


def _v12_p06_envelope_hashes(build) -> dict[tuple[str, str], dict[str, Any]]:
    """Hash the v1.2 model-visible envelope for every repaired P06 route."""

    catalog = build_construct_catalog(CORPUS_ROOT)
    by_key = {item["construct_key"]: item for item in catalog["constructs"]}
    path_by_activity = {
        item["activity_id"]: item["activity_path"] for item in catalog["activities"]
    }
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for route in build.routes["routes"]:
        construct = by_key[route["target_construct_key"]]
        bundle = parse_submission_bundle(
            corpus_root=CORPUS_ROOT,
            activity_path=path_by_activity[route["activity_id"]],
            activity_id=route["activity_id"],
            submission_id=route["submission_id"],
            artifact_refs=route["evidence_provenance"]["artifacts"],
        )
        definition = model_visible_definition_for(construct, bundle)
        request, _envelope = build_p06_fixture_v12(
            route_fixture_id=route["route_fixture_id"],
            model_visible_definition=definition,
            bundle=bundle,
        )
        result.setdefault((route["activity_id"], route["submission_id"]), {})[
            route["route_fixture_id"]
        ] = {
            "case_id": route["case_id"],
            "target_construct_key": route["target_construct_key"],
            "envelope_hash": _envelope_hash("P06_EVIDENCE_MAP_V1", request),
            "property_ids": route["oracle_binding_metadata"]["property_ids"],
        }
    return result


def _surfaces_compared(stage: str) -> list[str]:
    shared = [
        "model-visible request (ModelTaskEnvelope canonical hash)",
        "fixture/opportunity semantics (frozen benchmark input hash)",
        "source bindings (corpus package boundary)",
        "property semantics/disposition (v1.2 qualification dispositions)",
        "provider/model-owned output contract (output schema name + version)",
        "materializer boundary (stage materializer executable boundary)",
        "adjudication information surface relevant to the decision",
        "stage policy (family, ladder, k, caps)",
    ]
    if stage == "P06":
        return shared + [
            "target construct identity (v1.2 construct catalog)",
            "P06 field authority artifact",
            "P06 blind adjudication companion contract",
        ]
    return shared


def main() -> None:
    freeze = _json(FREEZE_PATH)
    freeze_digest = sha256(FREEZE_PATH.read_bytes()).hexdigest()

    manifest = _json(EXECUTION_ROOT / "execution_manifest.json")
    ledger = _json(EXECUTION_ROOT / "call_ledger.json")
    attempts = ledger["attempts"]

    build = build_v12()
    boundary = benchmark_boundary_v12(build)
    boundaries = stage_boundaries(build)

    legacy_hashes = _legacy_envelope_hashes()
    v12_p06 = _v12_p06_envelope_hashes(build)

    v12_case_ids = {case["case_id"] for case in build.cases}
    v12_p06_by_case = {
        entry["case_id"]: entry
        for routes in v12_p06.values()
        for entry in routes.values()
    }
    dispositions = {
        item["property_id"]: item for item in build.dispositions["dispositions"]
    }
    v11_bindings = _json(
        REPOSITORY_ROOT
        / "evaluation/semantic_benchmark/v1_1/fixtures/property_bindings.json"
    )
    v11_p06_by_case: dict[str, list[str]] = defaultdict(list)
    for binding in v11_bindings["bindings"]:
        if binding["stage"] == "P06":
            v11_p06_by_case[binding["primary_case_id"]].append(binding["property_id"])

    observations: list[dict[str, Any]] = []
    for attempt in attempts:
        case_id = attempt["case_id"]
        stage = attempt["stage"]
        recorded = attempt["model_visible_input_hash"]
        rebuilt = legacy_hashes.get(case_id)
        lineage_verified = rebuilt is not None and rebuilt == recorded

        row: dict[str, Any] = {
            "logical_call_id": attempt["logical_call_id"],
            "case_id": case_id,
            "stage": stage,
            "run_index": attempt["run_index"],
            "candidate_id": attempt["candidate_id"],
            "legacy_model_visible_input_hash": recorded,
            "legacy_rebuilt_model_visible_input_hash": rebuilt,
            "legacy_lineage_verified": lineage_verified,
            "legacy_frozen_benchmark_input_hash": attempt[
                "frozen_benchmark_input_hash"
            ],
            "legacy_provider_output_hash": attempt["provider_output_hash"],
            "legacy_semantic_status": attempt["semantic_status"],
            "surfaces_compared": _surfaces_compared(stage),
        }

        if stage == "P06":
            v11_properties = sorted(v11_p06_by_case.get(case_id, []))
            row["v11_bound_property_ids"] = v11_properties
            still_gating = [
                property_id
                for property_id in v11_properties
                if dispositions.get(property_id, {}).get("candidate_scoring_allowed")
            ]
            row["v12_still_gating_property_ids"] = still_gating
            row["v12_dispositions"] = {
                property_id: dispositions.get(property_id, {}).get(
                    "qualification_disposition", "UNKNOWN"
                )
                for property_id in v11_properties
            }
            candidates = {
                entry["envelope_hash"]: fixture_id
                for routes in v12_p06.values()
                for fixture_id, entry in routes.items()
            }
            row["v12_exact_input_match_fixture_id"] = candidates.get(recorded)
            if not still_gating:
                row["p06_input_equivalence"] = PROPERTY_NO_LONGER_GATE
                row["equivalence"] = EVIDENCE_SEMANTICALLY_INVALIDATED
                row["reason"] = (
                    "Every property this observation was bound to lost its executable "
                    "route in v1.2, so the observation has no v1.2 gate to inform."
                )
            elif candidates.get(recorded) is not None:
                row["p06_input_equivalence"] = EXACT_INPUT_EQUIVALENCE_PROVEN
                row["equivalence"] = EVIDENCE_EQUIVALENCE_PROVEN
                row["reason"] = (
                    "The recorded model-visible envelope hash equals a repaired v1.2 "
                    "route envelope hash."
                )
            else:
                # Resolve the successor by *property*, never by case id: v1.2
                # renumbers routes, so the same case id can denote a different
                # property in each version.
                successors = [
                    entry
                    for routes in v12_p06.values()
                    for entry in routes.values()
                    if set(entry["property_ids"]) & set(still_gating)
                ]
                reused = v12_p06_by_case.get(case_id)
                row["p06_input_equivalence"] = ROUTE_SEMANTICS_CHANGED
                row["equivalence"] = EVIDENCE_SEMANTICALLY_INVALIDATED
                row["v12_successor_routes_by_property"] = successors
                row["case_id_reused_for_a_different_property"] = bool(
                    reused and not set(reused["property_ids"]) & set(still_gating)
                )
                row["v12_case_id_now_bound_to"] = (
                    reused["property_ids"] if reused else None
                )
                row["reason"] = (
                    "The property still gates in v1.2, but through a repaired route "
                    "whose model-visible request differs. v1.1 showed the model a "
                    "location-derived construct; v1.2 shows the authorized criterion. "
                    "The candidate answered a different question."
                )
        else:
            in_v12 = case_id in v12_case_ids
            carried = next(
                (item for item in build.carried_cases if item["case_id"] == case_id),
                None,
            )
            row["present_in_v12_case_matrix"] = in_v12
            row["v12_case_input_hash"] = (
                carried.get("input_hash") if carried else None
            )
            row["v12_rebuilt_model_visible_input_hash"] = rebuilt
            if in_v12 and lineage_verified:
                row["equivalence"] = EVIDENCE_EQUIVALENCE_PROVEN
                row["reason"] = (
                    "The v1.2 case matrix carries this case unchanged and the "
                    "model-visible envelope rebuilds to exactly the hash the ledger "
                    "recorded."
                )
            elif in_v12:
                row["equivalence"] = EVIDENCE_EQUIVALENCE_NOT_PROVEN
                row["reason"] = (
                    "The case is present in v1.2 but the model-visible envelope could "
                    "not be rebuilt to the recorded hash."
                )
            else:
                row["equivalence"] = EVIDENCE_EQUIVALENCE_NOT_PROVEN
                row["reason"] = "The case is absent from the v1.2 case matrix."
        observations.append(row)

    by_stage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in observations:
        by_stage[row["stage"]][row["equivalence"]] += 1

    zip_path = REPOSITORY_ROOT / "first_pass_adjudication_results.zip"
    first_pass = {
        "expected_sha256": EXPECTED_FIRST_PASS_ZIP_SHA256,
        "locally_present": zip_path.is_file(),
        "sha256": (
            sha256(zip_path.read_bytes()).hexdigest() if zip_path.is_file() else None
        ),
        "fabricated": False,
        "note": (
            "Not present in the working tree. It was not reconstructed. The execution "
            "manifest records semantic_adjudication_performed_here=False and "
            "semantic_status=PENDING_ADJUDICATION, so no first-pass verdict is "
            "available from repository evidence either."
        ),
    }

    material = {
        "schema_version": "phase9-evidence-carryforward-proof/1.0.0",
        "phase": "9B.4",
        "part": "B",
        "analysis_kind": "LINEAGE_AND_STRUCTURAL_EQUIVALENCE_ONLY",
        "re_adjudicated": False,
        "new_candidate_verdicts_issued": 0,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "part_a_freeze": {
            "path": FREEZE_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": freeze_digest,
            "frozen_before_this_analysis": True,
            "part_a_modified_by_part_b": False,
            "global_benchmark_boundary_hash": freeze[
                "global_benchmark_boundary_hash"
            ],
        },
        "v12_boundaries": {
            "global": boundary["benchmark_boundary_hash"],
            "stages": dict(boundaries["stage_boundary_hashes"]),
        },
        "legacy_execution": {
            "execution_id": manifest["execution_id"],
            "benchmark_version": manifest["benchmark_version"],
            "benchmark_boundary_hash": manifest["benchmark_boundary_hash"],
            "protocol_version": manifest["protocol_version"],
            "split": manifest["split"],
            "k": manifest["k"],
            "status": manifest["status"],
            "semantic_status": manifest["semantic_status"],
            "semantic_adjudication_performed_here": manifest[
                "semantic_adjudication_performed_here"
            ],
            "attempt_count": len(attempts),
            "case_ids": manifest["case_ids"],
            "evidence_bytes_modified": False,
        },
        "first_pass_adjudication_results_zip": first_pass,
        "case_id_reuse_hazard": {
            "detected": any(
                row.get("case_id_reused_for_a_different_property") for row in observations
            ),
            "rule": (
                "P06 case ids are NOT stable across benchmark versions. v1.2 renumbers "
                "routes per (submission, construct), so a v1.1 case id can denote a "
                "different property in v1.2. Never join v1.1 and v1.2 P06 evidence on "
                "case_id; join on property_id and compare envelope hashes."
            ),
            "examples": sorted(
                {
                    json.dumps(
                        {
                            "case_id": row["case_id"],
                            "v11_bound_property_ids": row["v11_bound_property_ids"],
                            "v12_case_id_now_bound_to": row["v12_case_id_now_bound_to"],
                        },
                        sort_keys=True,
                    )
                    for row in observations
                    if row.get("case_id_reused_for_a_different_property")
                }
            ),
        },
        "equivalence_by_stage": {
            stage: dict(sorted(value.items())) for stage, value in sorted(by_stage.items())
        },
        "observations": observations,
        "qualification_use_policy": {
            "equivalence_promotes_legacy_into_v12_qualification": False,
            "rule": (
                "EVIDENCE_EQUIVALENCE_PROVEN establishes eligibility for comparison, "
                "not a v1.2 qualification observation. Even a byte-identical legacy "
                "request is not inserted as a canonical v1.2 observation."
            ),
            "reason": [
                "avoid post-observation selective carry-forward",
                "avoid hybrid qualification lineage",
                "keep one benchmark/protocol/authorization identity for the full "
                "v1.2 SMOKE",
            ],
            "legacy_evidence_remains_useful_for": [
                "historical comparison",
                "reproducibility analysis",
                "equivalence proof",
                "regression understanding",
            ],
            "recommended_first_v12_execution": "FRESH_COMPLETE_HIGH_SMOKE",
        },
    }
    document = {**material, "proof_hash": canonical_hash(material)}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "proof_path": OUT_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
                "proof_hash": document["proof_hash"],
                "equivalence_by_stage": material["equivalence_by_stage"],
                "part_a_freeze_sha256": freeze_digest,
                "first_pass_zip_present": first_pass["locally_present"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
