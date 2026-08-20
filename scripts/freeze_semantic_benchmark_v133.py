"""Write the semantic-benchmark/1.3.3 pre-execution package.

1.3.3 resolves the state the pre-U3 UNCERTAIN coverage gate left in the active
claim, and changes nothing else.  ``semantic-benchmark/1.3.2`` is not edited; no
provider or adjudicator ever ran against it, so superseding it is an
authority-binding repair rather than result-driven tuning.

Seven artifacts are republished byte-identically from 1.3.2 -- the N3 provider
fixtures, the N3 axis, the construct-selection semantics, the call budget and
the three N3 proofs.  Their material did not change, so their hashes must not:
they are copied rather than regenerated with a new version stamp, and the
lineage and both scans record that they are republished.

Three kinds of hash are reported and never conflated: the **internal material
hash** each document carries, the **file SHA-256** of the bytes written, and the
**Git blob SHA**.  The manifest does not list itself, and says why.

No provider call, no adjudicator call, no credential, no pricing refresh and no
authorization.
"""

from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from comprehension_verification.semantic_benchmark import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
)
from comprehension_verification.semantic_benchmark_v13_protocol import (  # noqa: E402
    HASH_KINDS,
)
from comprehension_verification.semantic_benchmark_v133 import (  # noqa: E402
    REPORT_ROOT,
    REPUBLISHED_FROM_V132,
    SELF_MATERIAL_HASH_FIELD,
    SEMANTIC_BENCHMARK_V132_VERSION,
    SEMANTIC_BENCHMARK_V133_VERSION,
    build_v133,
    self_material_hash,
    v133_package,
)

FREEZE_RELATIVE = f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
MANIFEST_RELATIVE = f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"


def serialize(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def file_sha256(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def git_blob_sha(data: bytes) -> str:
    return sha1(b"blob %d\0" % len(data) + data).hexdigest()


def main() -> int:
    build = build_v133(DEFAULT_CORPUS_ROOT)
    package = v133_package(build)

    if serialize(package) != serialize(v133_package(build)):  # pragma: no cover
        print("V133_PACKAGE_NOT_DETERMINISTIC_WITHIN_A_BUILD")
        return 1
    rebuilt = v133_package(build_v133(DEFAULT_CORPUS_ROOT))
    drifted = sorted(
        path for path in package if serialize(package[path]) != serialize(rebuilt[path])
    )
    if drifted:
        print(f"V133_PACKAGE_NOT_DETERMINISTIC_ACROSS_BUILDS: {drifted}")
        return 1

    unregistered = sorted(set(package) - set(SELF_MATERIAL_HASH_FIELD))
    orphaned = sorted(set(SELF_MATERIAL_HASH_FIELD) - set(package))
    if unregistered or orphaned:
        print(
            "V133_SELF_HASH_REGISTRY_OUT_OF_SYNC: "
            f"unregistered={unregistered} orphaned={orphaned}"
        )
        return 1

    written: dict[str, bytes] = {}
    for relative, payload in sorted(package.items()):
        path = REPOSITORY_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = serialize(payload)
        path.write_bytes(data)
        written[relative] = data

    artifacts = [
        {
            "path": relative,
            "self_material_hash_field": SELF_MATERIAL_HASH_FIELD[relative],
            "internal_material_hash": self_material_hash(relative, package[relative]),
            "has_self_material_hash": SELF_MATERIAL_HASH_FIELD[relative] is not None,
            "republished_unchanged_from": (
                SEMANTIC_BENCHMARK_V132_VERSION
                if relative in REPUBLISHED_FROM_V132
                else None
            ),
            "file_sha256": file_sha256(data),
            "git_blob_sha": git_blob_sha(data),
            "bytes": len(data),
        }
        for relative, data in sorted(written.items())
    ]

    manifest_material = {
        "schema_version": "phase9-freeze-hash-manifest/1.3.3",
        "benchmark_version": SEMANTIC_BENCHMARK_V133_VERSION,
        "hash_kinds": dict(HASH_KINDS),
        "never_conflate": (
            "An internal material hash, a file SHA-256 and a Git blob SHA are "
            "three values over three different inputs. They are listed side by "
            "side so no reader has to guess which one a number is."
        ),
        "self_material_hash_rule": (
            "Each artifact declares which field carries its own material hash, "
            "and the declaration is verified: canonical_hash(document minus that "
            "field) must equal the field's value. A dependency hash copied from "
            "another artifact cannot satisfy that."
        ),
        "supersedes": "phase9-freeze-hash-manifest/1.3.2",
        "manifest_excludes_itself": True,
        "manifest_self_exclusion_reason": (
            "The manifest is written after the artifacts it describes, so an "
            "entry for its own bytes could not exist when it is built. Its own "
            "file SHA-256 and Git blob SHA are reported by this script's output "
            "and are recoverable with sha256sum and git hash-object."
        ),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "artifacts_without_a_self_material_hash": [
            item["path"] for item in artifacts if not item["has_self_material_hash"]
        ],
        "republished_unchanged_artifact_count": sum(
            1 for item in artifacts if item["republished_unchanged_from"]
        ),
        "freeze_artifact_path": FREEZE_RELATIVE,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "billable_authorizations": 0,
        "credentials_resolved": 0,
        "pricing_refreshed": False,
        "authorization": "NONE",
    }
    manifest_path = REPOSITORY_ROOT / MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = serialize(manifest_material)
    manifest_path.write_bytes(manifest_bytes)

    freeze = package[FREEZE_RELATIVE]
    freeze_bytes = written[FREEZE_RELATIVE]
    print("SEMANTIC_BENCHMARK_V1_3_3_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT")
    print(f"benchmark_version              {SEMANTIC_BENCHMARK_V133_VERSION}")
    print(f"semantic_qualification_claim   {freeze['semantic_qualification_claim_hash']}")
    print(
        "uncertain_coverage_disposition "
        f"{freeze['uncertain_coverage_disposition_hash']}"
    )
    print(f"product_decision               {freeze['uncertain_coverage_product_decision']}")
    print(
        "product_decision_status        "
        f"{freeze['uncertain_coverage_product_decision_status']}"
    )
    print(
        "product_decision_hash          "
        f"{freeze['uncertain_coverage_product_decision_hash']}"
    )
    print(f"global_benchmark_boundary_hash {freeze['global_benchmark_boundary_hash']}")
    print(f"stage_boundaries_hash          {freeze['stage_boundaries_hash']}")
    print(f"protocol_boundary_hash         {freeze['protocol_boundary_hash']}")
    print(f"candidate_matrix_hash          {freeze['candidate_matrix_hash']}")
    print(f"call_budget_hash               {freeze['call_budget_hash']}")
    print(f"n3_provider_fixture_set_hash   {freeze['n3_provider_fixture_set_hash']}")
    print(
        "semantic_invariant_proof_hash  "
        f"{freeze['semantic_invariant_equality_proof_hash']}"
    )
    print(f"n3_fixture_equality_proof_hash {freeze['n3_fixture_equality_proof_hash']}")
    print(f"stale_claim_scan_hash          {freeze['stale_claim_scan_hash']}")
    print(
        "product_decision_scan_hash     "
        f"{freeze['product_decision_state_scan_hash']}"
    )
    print(f"lineage_hash                   {freeze['lineage_hash']}")
    print(f"freeze internal material hash  {freeze['freeze_material_hash']}")
    print(f"freeze file sha256             {file_sha256(freeze_bytes)}")
    print(f"freeze git blob sha            {git_blob_sha(freeze_bytes)}")
    print(f"manifest file sha256           {file_sha256(manifest_bytes)}")
    print(f"manifest git blob sha          {git_blob_sha(manifest_bytes)}")
    print(f"artifacts written              {len(written) + 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
