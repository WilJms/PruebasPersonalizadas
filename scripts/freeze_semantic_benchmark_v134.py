"""Write and verify the semantic-benchmark/1.3.4 pre-execution package."""

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
from comprehension_verification.semantic_benchmark_v134 import (  # noqa: E402
    REPORT_ROOT,
    REPUBLISHED_FROM_V133,
    SELF_MATERIAL_HASH_FIELD,
    SEMANTIC_BENCHMARK_V133_VERSION,
    SEMANTIC_BENCHMARK_V134_VERSION,
    build_v134,
    self_material_hash,
    v134_package,
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
    build = build_v134(DEFAULT_CORPUS_ROOT)
    package = v134_package(build)
    if serialize(package) != serialize(v134_package(build)):
        print("V134_PACKAGE_NOT_DETERMINISTIC_WITHIN_A_BUILD")
        return 1
    rebuilt = v134_package(build_v134(DEFAULT_CORPUS_ROOT))
    drifted = sorted(
        path for path in package if serialize(package[path]) != serialize(rebuilt[path])
    )
    if drifted:
        print(f"V134_PACKAGE_NOT_DETERMINISTIC_ACROSS_BUILDS: {drifted}")
        return 1

    unregistered = sorted(set(package) - set(SELF_MATERIAL_HASH_FIELD))
    orphaned = sorted(set(SELF_MATERIAL_HASH_FIELD) - set(package))
    if unregistered or orphaned:
        print(
            "V134_SELF_HASH_REGISTRY_OUT_OF_SYNC: "
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
                SEMANTIC_BENCHMARK_V133_VERSION
                if relative in REPUBLISHED_FROM_V133
                else None
            ),
            "file_sha256": file_sha256(data),
            "git_blob_sha": git_blob_sha(data),
            "bytes": len(data),
        }
        for relative, data in sorted(written.items())
    ]
    manifest_material = {
        "schema_version": "phase9-freeze-hash-manifest/1.3.4",
        "benchmark_version": SEMANTIC_BENCHMARK_V134_VERSION,
        "hash_kinds": dict(HASH_KINDS),
        "never_conflate": (
            "INTERNAL_MATERIAL_HASH, FILE_SHA256 and GIT_BLOB_SHA cover different "
            "inputs and are reported separately."
        ),
        "self_material_hash_rule": (
            "Every artifact is registered explicitly as path -> self hash field; "
            "canonical_hash(document minus that exact field) must equal its value."
        ),
        "supersedes": "phase9-freeze-hash-manifest/1.3.3",
        "manifest_excludes_itself": True,
        "manifest_self_exclusion_reason": (
            "The manifest is written after the artifacts it describes. Its own "
            "file and Git-blob hashes are printed by this script."
        ),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "artifacts_without_a_self_material_hash": [
            row["path"] for row in artifacts if not row["has_self_material_hash"]
        ],
        "republished_unchanged_artifact_count": sum(
            1 for row in artifacts if row["republished_unchanged_from"]
        ),
        "freeze_artifact_path": FREEZE_RELATIVE,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "billable_authorizations": 0,
        "credentials_resolved": 0,
        "real_provider_transport": False,
        "pricing_refreshed": False,
        "high_smoke_executed": False,
        "authorization": "NONE",
    }
    manifest_path = REPOSITORY_ROOT / MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = serialize(manifest_material)
    manifest_path.write_bytes(manifest_bytes)

    freeze = package[FREEZE_RELATIVE]
    freeze_bytes = written[FREEZE_RELATIVE]
    print("SEMANTIC_BENCHMARK_V1_3_4_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT")
    print(f"benchmark_version              {SEMANTIC_BENCHMARK_V134_VERSION}")
    print(f"global_benchmark_boundary_hash {freeze['global_benchmark_boundary_hash']}")
    print(f"n3_protocol_source_hash        {freeze['n3_protocol_source_hash']}")
    print(f"n3_axis_hash                   {freeze['n3_axis_hash']}")
    print(f"protocol_boundary_hash         {freeze['protocol_boundary_hash']}")
    print(f"candidate_matrix_hash          {freeze['candidate_matrix_hash']}")
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
