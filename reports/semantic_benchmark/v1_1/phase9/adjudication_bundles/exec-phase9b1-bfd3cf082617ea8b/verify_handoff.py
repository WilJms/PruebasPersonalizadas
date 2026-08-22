#!/usr/bin/env python3
"""Verify this blind adjudication handoff is complete, using only the stdlib.

Run it from inside the handoff directory:

    python3 verify_handoff.py

It reads nothing outside this directory. Every packet hash, every source
artifact, every parser projection and every locator binding is checked against
the manifests shipped here, so a reader with no access to the originating
repository can still confirm the material is intact before reading it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(root: Path, name: str) -> object:
    return json.loads((root / name).read_text(encoding="utf-8"))


def main() -> int:
    root = Path(__file__).resolve().parent
    failures: list[str] = []

    handoff = load(root, "blind_handoff_manifest.json")
    bundle = load(root, "bundle_manifest.json")
    sources = load(root, "source_material_manifest.json")
    bindings = load(root, "locator_bindings.json")

    packets = 0
    for entry in bundle["packets"]:
        path = root / entry["file"]
        if not path.is_file():
            failures.append(f"missing packet {entry['file']}")
            continue
        packet = json.loads(path.read_text(encoding="utf-8"))
        if canonical_hash(packet) != entry["packet_hash"]:
            failures.append(f"packet hash drift {entry['packet_id']}")
            continue
        if handoff["packet_hashes"].get(entry["packet_id"]) != entry["packet_hash"]:
            failures.append(f"packet hash disagrees with handoff {entry['packet_id']}")
            continue
        packets += 1

    blobs = 0
    for row in sources["sources"]:
        blob = root / row["source_blob_path"]
        projection = root / row["projection_path"]
        if not blob.is_file():
            failures.append(f"missing source {row['source_blob_path']}")
            continue
        if file_hash(blob) != row["source_blob_hash"]:
            failures.append(f"source byte drift {row['source_blob_path']}")
            continue
        if not projection.is_file():
            failures.append(f"missing projection {row['projection_path']}")
            continue
        if canonical_hash(
            json.loads(projection.read_text(encoding="utf-8"))
        ) != row["projection_hash"]:
            failures.append(f"projection drift {row['projection_path']}")
            continue
        blobs += 1

    # Every source hash a packet declares must be present as a real artifact.
    present = {row["source_blob_hash"] for row in sources["sources"]}
    for relation in sources["packet_sources"]:
        if relation["source_blob_hash"] not in present:
            failures.append(
                f"{relation['packet_id']} declares an absent source artifact"
            )

    resolved = 0
    covered: set[str] = set()
    for row in bindings["bindings"]:
        blob = root / row["source_blob_path"]
        projection = root / row["projection_path"]
        if not blob.is_file() or not projection.is_file():
            failures.append(f"unfollowable ref {row['packet_id']} {row['declared_ref']}")
            continue
        units = json.loads(projection.read_text(encoding="utf-8"))["units"]
        known = {unit["evidence_id"] for unit in units}
        if not set(row["matched_evidence_ids"]) <= known:
            failures.append(f"binding names an unknown unit {row['packet_id']}")
            continue
        resolved += 1
        covered.add(row["packet_id"])

    report = {
        "packets_verified": packets,
        "packets_expected": handoff["packet_count"],
        "source_artifacts_verified": blobs,
        "declared_refs_resolved": resolved,
        "declared_refs_expected": handoff["declared_source_refs"],
        "packets_with_resolvable_sources": len(covered),
        "failures": failures,
        "SELF_CONTAINED_SOURCE_RESOLUTION": (
            not failures
            and packets == handoff["packet_count"]
            and len(covered) == handoff["packet_count"]
            and resolved == handoff["declared_source_refs"]
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["SELF_CONTAINED_SOURCE_RESOLUTION"] else 1


if __name__ == "__main__":
    sys.exit(main())
