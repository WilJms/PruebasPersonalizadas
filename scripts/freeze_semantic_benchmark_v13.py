"""Write the semantic-benchmark/1.3.0 pre-execution package.

Everything this script emits is a pure function of frozen authority: the
canonical corpus, the executable product source and the immutable v1.2 bytes.
Run it twice and the files are byte-identical; that is checked here rather than
hoped for.

Three kinds of hash are reported and never conflated:

* the **internal material hash** each document carries, computed over canonical
  JSON before any file exists;
* the **file SHA-256** of the bytes actually written;
* the **Git blob SHA**, which is sha1 over ``blob <len>\\0`` plus those bytes --
  what ``git hash-object`` reports, and not comparable with a sha256.

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
from comprehension_verification.semantic_benchmark_v13 import (  # noqa: E402
    SEMANTIC_BENCHMARK_V13_VERSION,
    build_v13,
)
from comprehension_verification.semantic_benchmark_v13_protocol import (  # noqa: E402
    HASH_KINDS,
    REPORT_ROOT,
    v13_package,
)

FREEZE_RELATIVE = f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
MANIFEST_RELATIVE = f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"


def serialize(payload: dict[str, Any]) -> bytes:
    """The one serialization used for every generated file."""

    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def file_sha256(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def git_blob_sha(data: bytes) -> str:
    """Git's object id for a blob: sha1 over the object header plus content."""

    return sha1(b"blob %d\0" % len(data) + data).hexdigest()


def main() -> int:
    build = build_v13(DEFAULT_CORPUS_ROOT)
    package = v13_package(build)

    # Determinism: the same build must serialize identically twice, and a
    # second independent build must agree with the first.
    if serialize(package) != serialize(v13_package(build)):  # pragma: no cover
        print("V13_PACKAGE_NOT_DETERMINISTIC_WITHIN_A_BUILD")
        return 1
    rebuilt = v13_package(build_v13(DEFAULT_CORPUS_ROOT))
    drifted = sorted(
        path
        for path in package
        if serialize(package[path]) != serialize(rebuilt[path])
    )
    if drifted:
        print(f"V13_PACKAGE_NOT_DETERMINISTIC_ACROSS_BUILDS: {drifted}")
        return 1

    written: dict[str, bytes] = {}
    for relative, payload in sorted(package.items()):
        path = REPOSITORY_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = serialize(payload)
        path.write_bytes(data)
        written[relative] = data

    manifest_material = {
        "schema_version": "phase9-freeze-hash-manifest/1.3.0",
        "benchmark_version": SEMANTIC_BENCHMARK_V13_VERSION,
        "hash_kinds": dict(HASH_KINDS),
        "never_conflate": (
            "An internal material hash, a file SHA-256 and a Git blob SHA are "
            "three different values over three different inputs. They are "
            "listed side by side here so no reader has to guess which one a "
            "number is."
        ),
        "artifacts": [
            {
                "path": relative,
                "internal_material_hash": _material_hash(package[relative]),
                "file_sha256": file_sha256(data),
                "git_blob_sha": git_blob_sha(data),
                "bytes": len(data),
            }
            for relative, data in sorted(written.items())
        ],
        "artifact_count": len(written),
        "freeze_artifact_path": FREEZE_RELATIVE,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "billable_authorizations": 0,
        "credentials_resolved": 0,
        "authorization": "NONE",
    }
    manifest_path = REPOSITORY_ROOT / MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(serialize(manifest_material))

    freeze = package[FREEZE_RELATIVE]
    freeze_bytes = written[FREEZE_RELATIVE]
    print("SEMANTIC_BENCHMARK_V1_3_PREEXECUTION_FREEZE_READY_FOR_FRESH_AUDIT")
    print(f"benchmark_version              {SEMANTIC_BENCHMARK_V13_VERSION}")
    print(f"global_benchmark_boundary_hash {freeze['global_benchmark_boundary_hash']}")
    print(f"protocol_boundary_hash         {freeze['protocol_boundary_hash']}")
    print(f"candidate_matrix_hash          {freeze['candidate_matrix_hash']}")
    print(f"freeze internal material hash  {freeze['freeze_material_hash']}")
    print(f"freeze file sha256             {file_sha256(freeze_bytes)}")
    print(f"freeze git blob sha            {git_blob_sha(freeze_bytes)}")
    print(f"artifacts written              {len(written) + 1}")
    return 0


def _material_hash(payload: dict[str, Any]) -> str:
    for key in (
        "freeze_material_hash",
        "benchmark_boundary_hash",
        "stage_boundaries_hash",
        "protocol_boundary_hash",
        "candidate_matrix_hash",
        "call_budget_hash",
        "adjudication_protocol_hash",
        "n3_axis_hash",
        "claim_hash",
        "instrument_hash",
        "lineage_hash",
        "separation_hash",
        "proof_hash",
        "split_partition_hash",
        "census_hash",
        "field_authority_hash",
        "alignment_hash",
        "report_hash",
    ):
        if key in payload:
            return payload[key]
    raise KeyError("document carries no internal material hash")


if __name__ == "__main__":
    raise SystemExit(main())
