"""Write and verify the semantic-benchmark/1.3.5 pre-execution package."""

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
from comprehension_verification.semantic_benchmark_v135 import (  # noqa: E402
    REPORT_ROOT,
    SELF_MATERIAL_HASH_FIELD,
    SEMANTIC_BENCHMARK_V135_VERSION,
    build_v135,
    self_material_hash,
    v135_package,
    validate_v135_package_for_publication,
)


FREEZE_RELATIVE = f"{REPORT_ROOT}/phase9/pre_results_instrument_freeze.json"
MANIFEST_RELATIVE = f"{REPORT_ROOT}/phase9/freeze_hash_manifest.json"
V134_ROOTS = (
    REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_3_4",
    REPOSITORY_ROOT / "reports/semantic_benchmark/v1_3_4",
)


def serialize(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def file_sha256(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def git_blob_sha(data: bytes) -> str:
    return sha1(b"blob %d\0" % len(data) + data).hexdigest()


def v134_file_hashes() -> dict[str, str]:
    return {
        path.relative_to(REPOSITORY_ROOT).as_posix(): file_sha256(path.read_bytes())
        for root in V134_ROOTS
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    v134_before = v134_file_hashes()
    build = build_v135(DEFAULT_CORPUS_ROOT)
    package = v135_package(build)
    validate_v135_package_for_publication(package)
    if serialize(package) != serialize(v135_package(build)):
        print("V135_PACKAGE_NOT_DETERMINISTIC_WITHIN_A_BUILD")
        return 1
    rebuilt = v135_package(build_v135(DEFAULT_CORPUS_ROOT))
    drifted = sorted(
        path for path in package if serialize(package[path]) != serialize(rebuilt[path])
    )
    if drifted:
        print(f"V135_PACKAGE_NOT_DETERMINISTIC_ACROSS_BUILDS: {drifted}")
        return 1
    if set(package) != set(SELF_MATERIAL_HASH_FIELD):
        print("V135_SELF_HASH_REGISTRY_OUT_OF_SYNC")
        return 1

    written: dict[str, bytes] = {}
    for relative, payload in sorted(package.items()):
        path = REPOSITORY_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = serialize(payload)
        path.write_bytes(data)
        written[relative] = data

    if v134_file_hashes() != v134_before:
        print("V134_IMMUTABLE_HISTORICAL_EVIDENCE_CHANGED")
        return 1

    artifacts = [
        {
            "path": relative,
            "self_material_hash_field": SELF_MATERIAL_HASH_FIELD[relative],
            "internal_material_hash": self_material_hash(relative, package[relative]),
            "file_sha256": file_sha256(data),
            "git_blob_sha": git_blob_sha(data),
            "bytes": len(data),
        }
        for relative, data in sorted(written.items())
    ]
    manifest = {
        "schema_version": "phase9-freeze-hash-manifest/1.3.5",
        "benchmark_version": SEMANTIC_BENCHMARK_V135_VERSION,
        "hash_kinds": dict(HASH_KINDS),
        "never_conflate": (
            "INTERNAL_MATERIAL_HASH, FILE_SHA256 and GIT_BLOB_SHA cover "
            "different inputs and remain separate."
        ),
        "manifest_excludes_itself": True,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "freeze_artifact_path": FREEZE_RELATIVE,
        "v134_file_count_verified_unchanged": len(v134_before),
        "v134_bytes_modified": False,
        "provider_calls": 0,
        "adjudicator_calls": 0,
        "credential_resolutions": 0,
        "real_provider_transport": False,
        "pricing_refresh": "NOT_PERFORMED",
        "high_smoke": "NOT_EXECUTED",
        "billable_authorization": "NONE",
    }
    manifest_path = REPOSITORY_ROOT / MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = serialize(manifest)
    manifest_path.write_bytes(manifest_bytes)

    freeze = package[FREEZE_RELATIVE]
    freeze_bytes = written[FREEZE_RELATIVE]
    print("SEMANTIC_BENCHMARK_V1_3_5_PREEXECUTION_FREEZE_READY_FOR_FINAL_FRESH_AUDIT")
    print(f"benchmark_version              {SEMANTIC_BENCHMARK_V135_VERSION}")
    print(f"global_benchmark_boundary_hash {freeze['global_benchmark_boundary_hash']}")
    print(f"n3_axis_hash                   {freeze['n3_axis_hash']}")
    print(f"prompt_authority_hash          {freeze['prompt_authority_hash']}")
    print(f"candidate_execution_contract  {freeze['candidate_execution_contract_hash']}")
    print(f"call_budget_hash               {freeze['call_budget_hash']}")
    print(f"protocol_boundary_hash         {freeze['protocol_boundary_hash']}")
    print(f"freeze internal material hash  {freeze['freeze_material_hash']}")
    print(f"freeze file sha256             {file_sha256(freeze_bytes)}")
    print(f"freeze git blob sha            {git_blob_sha(freeze_bytes)}")
    print(f"manifest file sha256           {file_sha256(manifest_bytes)}")
    print(f"manifest git blob sha          {git_blob_sha(manifest_bytes)}")
    print(f"artifacts written              {len(written) + 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
