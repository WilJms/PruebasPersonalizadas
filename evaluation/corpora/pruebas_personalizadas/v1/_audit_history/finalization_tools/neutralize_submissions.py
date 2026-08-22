#!/usr/bin/env python3
"""Apply deterministic activity-local ID permutations and neutral filenames."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTANT = "corpus-final-v1"
ACTIVITY_RE = re.compile(r"activity_(\d{2})_")
SUBMISSION_RE = re.compile(r"submission_(\d{2})(?:_|\.)")


def permutation(activity_dir: Path) -> dict[int, int]:
    match = ACTIVITY_RE.match(activity_dir.name)
    if not match:
        raise ValueError(f"Unexpected activity directory: {activity_dir}")
    activity_number = int(match.group(1))
    activity_id = f"activity_{activity_number:02d}"
    target_for_six = ((activity_number - 1) % 6) + 1
    remaining = [value for value in range(1, 7) if value != target_for_six]
    seed = int.from_bytes(
        hashlib.sha256(f"{activity_id}|{CONSTANT}".encode("utf-8")).digest(),
        "big",
    )
    random.Random(seed).shuffle(remaining)
    assigned = remaining + [target_for_six]
    return {old: new for old, new in enumerate(assigned, start=1)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    activities = sorted(path for path in ROOT.glob("activity_*") if path.is_dir())
    all_permutations: set[tuple[int, ...]] = set()
    activity_entries = []
    pending_renames: list[tuple[Path, Path, Path]] = []

    for activity in activities:
        mapping = permutation(activity)
        signature = tuple(mapping[index] for index in range(1, 7))
        if signature in all_permutations:
            raise RuntimeError(f"Duplicate permutation generated for {activity.name}")
        all_permutations.add(signature)

        submissions_dir = activity / "submissions"
        grouped: dict[int, list[Path]] = {index: [] for index in range(1, 7)}
        for path in sorted(submissions_dir.iterdir()):
            if not path.is_file():
                continue
            match = SUBMISSION_RE.match(path.name)
            if not match:
                raise RuntimeError(f"Non-submission artifact in {submissions_dir}: {path.name}")
            grouped[int(match.group(1))].append(path)

        if any(not grouped[index] for index in range(1, 7)):
            raise RuntimeError(f"Missing original submission group in {activity.name}")

        submission_entries = []
        for old_id in range(1, 7):
            new_id = mapping[old_id]
            artifacts = grouped[old_id]
            artifact_entries = []
            for artifact_index, source in enumerate(artifacts, start=1):
                if len(artifacts) == 1:
                    final_name = f"submission_{new_id:02d}{source.suffix.lower()}"
                else:
                    final_name = (
                        f"submission_{new_id:02d}_artifact_{artifact_index:02d}"
                        f"{source.suffix.lower()}"
                    )
                destination = submissions_dir / final_name
                temporary = submissions_dir / (
                    f".neutralizing-{old_id:02d}-{artifact_index:02d}{source.suffix.lower()}"
                )
                if destination.exists() and destination not in artifacts:
                    raise FileExistsError(destination)
                artifact_entries.append(
                    {
                        "old_path": source.relative_to(ROOT).as_posix(),
                        "new_path": destination.relative_to(ROOT).as_posix(),
                        "sha256_before_rename": sha256(source),
                        "bytes": source.stat().st_size,
                    }
                )
                pending_renames.append((source, temporary, destination))
            submission_entries.append(
                {
                    "old_submission_id": f"submission_{old_id:02d}",
                    "new_submission_id": f"submission_{new_id:02d}",
                    "artifacts": artifact_entries,
                }
            )

        activity_entries.append(
            {
                "activity": activity.name,
                "permutation_signature_old_01_through_06": [mapping[i] for i in range(1, 7)],
                "submissions": submission_entries,
            }
        )

    for source, temporary, _ in pending_renames:
        os.replace(source, temporary)
    for _, temporary, destination in pending_renames:
        os.replace(temporary, destination)

    for activity_entry in activity_entries:
        for submission_entry in activity_entry["submissions"]:
            for artifact_entry in submission_entry["artifacts"]:
                path = ROOT / artifact_entry["new_path"]
                artifact_entry["sha256_after_rename"] = sha256(path)
                artifact_entry["hash_match"] = (
                    artifact_entry["sha256_before_rename"]
                    == artifact_entry["sha256_after_rename"]
                )

    distribution = {f"submission_{index:02d}": 0 for index in range(1, 7)}
    for activity_entry in activity_entries:
        adversarial_old_group = activity_entry["submissions"][5]
        distribution[adversarial_old_group["new_submission_id"]] += 1

    output = {
        "schema_version": "submission-id-mapping/1.0.0",
        "role": "NON_BENCHMARK",
        "model_input": False,
        "constant": CONSTANT,
        "algorithm": (
            "old submission 06 is rotated evenly by the numeric activity id; "
            "remaining targets are shuffled from sha256(activity_id + constant)"
        ),
        "all_activity_permutations_distinct": len(all_permutations) == len(activities),
        "all_artifact_hashes_preserved": all(
            artifact["hash_match"]
            for activity in activity_entries
            for submission in activity["submissions"]
            for artifact in submission["artifacts"]
        ),
        "old_submission_06_post_permutation_distribution": distribution,
        "activities": activity_entries,
    }
    target = ROOT / "_audit_history/submission_id_mapping.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
