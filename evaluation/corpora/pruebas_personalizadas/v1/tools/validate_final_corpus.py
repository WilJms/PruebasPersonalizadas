#!/usr/bin/env python3
"""Offline, deterministic validator for the frozen semantic corpus.

The validator intentionally uses only Python's standard library.  It checks the
portable schemas' corpus-specific invariants directly, so no package download
or network access is required.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
ZERO_SHA256 = "0" * 64
ACTIVITY_RE = re.compile(r"^activity_(\d{2})_([a-z0-9_]+)$")
ACTIVITY_ID_RE = re.compile(r"^act_(\d{2})_([a-z0-9_]+)$")
SUBMISSION_FILE_RE = re.compile(
    r"^submission_(0[1-6])(?:_artifact_(\d{2}))?\.(docx|md|pdf|txt)$"
)
SEMANTIC_FILENAME_RE = re.compile(
    r"(?:strong|adequate|partial|superficial|contradict|adversarial|"
    r"insufficient|polished|keyword|silent[_-]?gap|quality)",
    re.IGNORECASE,
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPORT_PACKAGE_RE = re.compile(
    rb"(?m)^(corpus_package_boundary_hash:\s*)[0-9a-f]{64}(\s*)$"
)
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class CorpusValidationError(RuntimeError):
    """Raised after collecting deterministic validation failures."""


class CheckLog:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(message)

    def passed(self, message: str) -> None:
        self.passes.append(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def boundary_hash(entries: Iterable[tuple[str, str, int]]) -> str:
    rows = [f"{path}\0{digest}\0{size}\n" for path, digest, size in entries]
    return sha256_bytes("".join(sorted(rows)).encode("utf-8"))


def ratification_submission_boundary(paths: Iterable[Path], activity_dir: Path) -> str:
    rows = []
    for path in sorted(paths, key=lambda item: item.relative_to(activity_dir).as_posix()):
        relative = path.relative_to(activity_dir).as_posix()
        rows.append(f"{relative}\0{sha256_file(path)}\0{path.stat().st_size}")
    return sha256_bytes("\n".join(rows).encode("utf-8"))


def normalized_report_sha256(path: Path) -> str:
    data = path.read_bytes()
    normalized, count = REPORT_PACKAGE_RE.subn(
        rb"\g<1>" + ZERO_SHA256.encode("ascii") + rb"\g<2>", data
    )
    if count != 1:
        raise CorpusValidationError(
            "corpus_finalization_report.md must contain exactly one package hash line"
        )
    return sha256_bytes(normalized)


def normalized_manifest_sha256(manifest: dict[str, Any]) -> str:
    normalized = copy.deepcopy(manifest)
    normalized["boundary_hashes"]["corpus_package_boundary_hash"] = ZERO_SHA256
    report_seen = 0
    self_seen = 0
    for entry in normalized["files"]:
        if entry["path"] == "corpus_finalization_report.md":
            entry["sha256"] = ZERO_SHA256
            report_seen += 1
        elif entry["path"] == "corpus_final_manifest.json":
            entry["sha256"] = ZERO_SHA256
            self_seen += 1
    if report_seen != 1 or self_seen != 1:
        raise CorpusValidationError("manifest normalization members are incomplete")
    return sha256_bytes(canonical_json_bytes(normalized))


def actual_paths() -> set[str]:
    ignored_parts = {"__pycache__"}
    result = set()
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue
        if path.suffix == ".pyc":
            continue
        result.add(path.relative_to(ROOT).as_posix())
    return result


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "word/document.xml"}
        if not required.issubset(names):
            raise CorpusValidationError(f"DOCX missing required members: {path}")
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(WORD_NS + "p"):
        paragraphs.append(
            "".join(node.text or "" for node in paragraph.iter(WORD_NS + "t"))
        )
    return "\n".join(paragraphs)


def validate_manifest(log: CheckLog) -> dict[str, Any] | None:
    path = ROOT / "corpus_final_manifest.json"
    if not path.exists():
        log.require(False, "missing corpus_final_manifest.json")
        return None
    manifest = json_load(path)
    required = {
        "schema_version",
        "created_utc",
        "readiness",
        "hash_algorithm",
        "path_encoding",
        "boundary_serialization",
        "normalization_rules",
        "source_input_file_count",
        "benchmark_authority_file_count",
        "p09_stage_fixture_file_count",
        "audit_history_file_count",
        "total_package_file_count",
        "files",
        "boundary_hashes",
    }
    log.require(set(manifest) == required, "manifest root keys do not match strict schema")
    log.require(
        manifest.get("schema_version") == "corpus-final-manifest/1.0.0",
        "wrong manifest schema_version",
    )
    log.require(
        manifest.get("readiness") == "CORPUS_READY_FOR_SEMANTIC_BENCHMARK",
        "manifest does not declare READY",
    )
    log.require(manifest.get("hash_algorithm") == "SHA-256", "wrong hash algorithm")
    entries = manifest.get("files", [])
    paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    log.require(paths == sorted(paths), "manifest file entries are not path-sorted")
    log.require(len(paths) == len(set(paths)), "duplicate paths in manifest")
    log.require(set(paths) == actual_paths(), "manifest inventory differs from filesystem")

    role_counts = Counter(entry.get("role") for entry in entries)
    expected_counts = {
        "SOURCE_INPUT": manifest.get("source_input_file_count"),
        "BENCHMARK_AUTHORITY": manifest.get("benchmark_authority_file_count"),
        "P09_STAGE_FIXTURE": manifest.get("p09_stage_fixture_file_count"),
        "AUDIT_HISTORY": manifest.get("audit_history_file_count"),
    }
    log.require(role_counts == Counter(expected_counts), "manifest role counts are inconsistent")
    log.require(
        manifest.get("total_package_file_count") == len(entries),
        "total_package_file_count is inconsistent",
    )
    log.require(role_counts["P09_STAGE_FIXTURE"] == 4, "expected exactly four P09 fixtures")

    source_rows: list[tuple[str, str, int]] = []
    oracle_rows: list[tuple[str, str, int]] = []
    fixture_rows: list[tuple[str, str, int]] = []
    package_rows: list[tuple[str, str, int]] = []
    for entry in entries:
        entry_path = ROOT / entry["path"]
        digest = entry.get("sha256", "")
        log.require(bool(SHA256_RE.fullmatch(digest)), f"bad SHA-256 syntax: {entry['path']}")
        log.require(entry.get("bytes") == entry_path.stat().st_size, f"byte mismatch: {entry['path']}")
        if entry["path"] == "corpus_final_manifest.json":
            log.require(
                entry.get("hash_mode") == "NORMALIZED_JSON_SELF_SHA256",
                "manifest self entry must use normalized hash mode",
            )
            expected = normalized_manifest_sha256(manifest)
        else:
            log.require(
                entry.get("hash_mode") == "ACTUAL_SHA256",
                f"non-manifest entry must use actual hash mode: {entry['path']}",
            )
            expected = sha256_file(entry_path)
        log.require(digest == expected, f"hash mismatch: {entry['path']}")
        log.require(
            entry.get("model_visible") is (entry.get("role") == "SOURCE_INPUT"),
            f"model_visible/role mismatch: {entry['path']}",
        )

        row_digest = digest
        if entry["path"] == "corpus_finalization_report.md":
            row_digest = normalized_report_sha256(entry_path)
        row = (entry["path"], row_digest, entry["bytes"])
        if entry["role"] == "SOURCE_INPUT":
            source_rows.append((entry["path"], sha256_file(entry_path), entry["bytes"]))
        if entry["path"].endswith("/final_ratification.json"):
            oracle_rows.append((entry["path"], sha256_file(entry_path), entry["bytes"]))
        if entry["role"] == "P09_STAGE_FIXTURE":
            fixture_rows.append((entry["path"], sha256_file(entry_path), entry["bytes"]))
        if entry["role"] != "AUDIT_HISTORY":
            package_rows.append(row)

    boundaries = manifest.get("boundary_hashes", {})
    computed = {
        "source_corpus_boundary_hash": boundary_hash(source_rows),
        "semantic_oracle_boundary_hash": boundary_hash(oracle_rows),
        "p09_fixture_boundary_hash": boundary_hash(fixture_rows),
        "corpus_package_boundary_hash": boundary_hash(package_rows),
    }
    log.require(boundaries == computed, "one or more boundary hashes are not reproducible")
    if not log.failures:
        log.passed("machine manifest, inventory, file hashes, and four boundaries")
    return manifest


def validate_activities(log: CheckLog) -> tuple[list[Path], set[str]]:
    activities = sorted(path for path in ROOT.glob("activity_*") if path.is_dir())
    log.require(len(activities) == 12, f"expected 12 activities, found {len(activities)}")
    activity_ids: set[str] = set()
    all_property_ids: set[str] = set()
    all_submission_case_ids: set[str] = set()
    rat_schema = json_load(ROOT / "_schemas/final_ratification.schema.json")
    root_keys = set(rat_schema["properties"])
    root_required = set(rat_schema["required"])
    property_keys = set(rat_schema["$defs"]["oracle_property"]["properties"])
    property_required = set(rat_schema["$defs"]["oracle_property"]["required"])
    submission_keys = set(rat_schema["$defs"]["submission"]["properties"])
    submission_required = set(rat_schema["$defs"]["submission"]["required"])

    for activity in activities:
        match = ACTIVITY_RE.fullmatch(activity.name)
        log.require(bool(match), f"bad activity directory name: {activity.name}")
        if not match:
            continue
        activity_id = f"act_{match.group(1)}_{match.group(2)}"
        log.require(activity_id not in activity_ids, f"duplicate activity id: {activity_id}")
        activity_ids.add(activity_id)
        assignment = activity / "01_assignment.docx"
        rubric = activity / "02_rubric.docx"
        rat_path = activity / "final_ratification.json"
        log.require(assignment.exists(), f"missing assignment: {activity.name}")
        log.require(rubric.exists(), f"missing rubric: {activity.name}")
        log.require(rat_path.exists(), f"missing final ratification: {activity.name}")

        submission_dir = activity / "submissions"
        artifacts = sorted(path for path in submission_dir.iterdir() if path.is_file())
        groups: dict[str, list[Path]] = {}
        for artifact in artifacts:
            filename_match = SUBMISSION_FILE_RE.fullmatch(artifact.name)
            log.require(bool(filename_match), f"non-neutral submission filename: {artifact}")
            log.require(not SEMANTIC_FILENAME_RE.search(artifact.name), f"semantic label in filename: {artifact}")
            if not filename_match:
                continue
            submission_id = f"submission_{filename_match.group(1)}"
            groups.setdefault(submission_id, []).append(artifact)
            if filename_match.group(2) is not None:
                expected_indices = list(range(1, len(groups[submission_id]) + 1))
                actual_indices = sorted(
                    int(SUBMISSION_FILE_RE.fullmatch(item.name).group(2))
                    for item in groups[submission_id]
                )
                log.require(actual_indices == expected_indices, f"artifact numbering gap: {activity.name}/{submission_id}")
        log.require(
            set(groups) == {f"submission_{number:02d}" for number in range(1, 7)},
            f"submission grouping is not exactly 01..06: {activity.name}",
        )

        if not rat_path.exists():
            continue
        rat = json_load(rat_path)
        log.require(root_required.issubset(rat), f"ratification missing root fields: {activity.name}")
        log.require(set(rat) == root_keys, f"ratification has unknown/missing root fields: {activity.name}")
        log.require(rat.get("schema_version") == "corpus-final-ratification/1.0.0", f"wrong ratification schema: {activity.name}")
        log.require(rat.get("ratification_type") == "INDEPENDENT_MODEL_RATIFICATION_DERIVED_FROM_OPUS5", f"wrong ratification type: {activity.name}")
        log.require(rat.get("curation_role") == "CORPUS_FINALIZATION", f"wrong curation role: {activity.name}")
        log.require(rat.get("activity_id") == activity_id, f"activity id mismatch: {activity.name}")
        log.require(rat.get("activity_path") == activity.name, f"activity path mismatch: {activity.name}")
        log.require(rat.get("ratification_status") in {"RATIFIED", "RATIFIED_WITH_CAVEATS"}, f"blocking ratification status: {activity.name}")
        log.require(rat.get("difficulty_declared") in {"simple", "intermedia", "dificil"}, f"bad difficulty: {activity.name}")
        if activity.name.startswith("activity_03_"):
            log.require(rat.get("difficulty_declared") == "simple", "act03 declared difficulty changed")
            log.require(rat.get("difficulty_caveat") == "upper_simple / borderline_intermediate", "act03 difficulty caveat missing")

        snapshots = rat.get("source_snapshot_hashes", {})
        log.require(snapshots.get("assignment_sha256") == sha256_file(assignment), f"assignment snapshot hash mismatch: {activity.name}")
        log.require(snapshots.get("rubric_sha256") == sha256_file(rubric), f"rubric snapshot hash mismatch: {activity.name}")
        log.require(
            snapshots.get("submissions_boundary_sha256") == ratification_submission_boundary(artifacts, activity),
            f"submission snapshot boundary mismatch: {activity.name}",
        )

        rat_submissions = rat.get("submissions", [])
        rat_submission_ids = {item.get("submission_id") for item in rat_submissions}
        log.require(rat_submission_ids == set(groups), f"ratification submission ids mismatch: {activity.name}")
        property_counter: Counter[str] = Counter()
        activity_properties = list(rat.get("activity_level_properties", []))
        all_properties = activity_properties[:]

        for submission in rat_submissions:
            log.require(submission_required.issubset(submission), f"submission oracle missing fields: {activity.name}")
            log.require(set(submission) == submission_keys, f"submission oracle has unknown fields: {activity.name}")
            submission_id = submission.get("submission_id")
            case_id = f"{activity_id}/{submission_id}"
            log.require(case_id not in all_submission_case_ids, f"duplicate canonical case id: {case_id}")
            all_submission_case_ids.add(case_id)
            expected_artifacts = [path.relative_to(activity).as_posix() for path in groups.get(submission_id, [])]
            log.require(submission.get("artifacts") == expected_artifacts, f"artifact list mismatch: {case_id}")
            source_hashes = submission.get("source_snapshot_hashes", {})
            log.require(set(source_hashes) == set(expected_artifacts), f"artifact hash keys mismatch: {case_id}")
            for relative in expected_artifacts:
                log.require(source_hashes.get(relative) == sha256_file(activity / relative), f"artifact snapshot hash mismatch: {case_id}/{relative}")
            for prop in submission.get("properties", []):
                for source_ref in prop.get("source_refs", []):
                    relative = source_ref.get("file", "")
                    if relative.startswith("submissions/"):
                        referenced_name = Path(relative).name
                        referenced_match = SUBMISSION_FILE_RE.fullmatch(referenced_name)
                        referenced_id = (
                            f"submission_{referenced_match.group(1)}"
                            if referenced_match
                            else None
                        )
                        log.require(
                            referenced_id == submission_id,
                            f"wrong-submission source_ref {relative}: {prop.get('property_id')}",
                        )
            all_properties.extend(submission.get("properties", []))

        for prop in all_properties:
            log.require(property_required.issubset(prop), f"oracle property missing fields: {activity.name}")
            log.require(set(prop) == property_keys, f"oracle property has unknown fields: {activity.name}")
            property_id = prop.get("property_id")
            log.require(isinstance(property_id, str) and property_id, f"bad property id: {activity.name}")
            log.require(property_id not in all_property_ids, f"duplicate property id: {property_id}")
            all_property_ids.add(property_id)
            state = prop.get("oracle_state")
            log.require(state in {"VALID", "ORACLE_SUSPECT", "NOT_APPLICABLE"}, f"forbidden oracle state {state}: {property_id}")
            property_counter[state] += 1
            for source_ref in prop.get("source_refs", []):
                relative = source_ref.get("file", "")
                log.require(isinstance(relative, str) and relative, f"empty source_ref: {property_id}")
                log.require(not relative.startswith("/") and ".." not in Path(relative).parts, f"unsafe source_ref: {property_id}")
                log.require(not relative.startswith("activity_"), f"cross-activity source_ref: {property_id}")
                log.require((activity / relative).is_file(), f"unresolvable source_ref {relative}: {property_id}")

        declared_counts = rat.get("property_counts", {})
        log.require(
            declared_counts == {
                "total": sum(property_counter.values()),
                "VALID": property_counter["VALID"],
                "ORACLE_SUSPECT": property_counter["ORACLE_SUSPECT"],
                "NOT_APPLICABLE": property_counter["NOT_APPLICABLE"],
            },
            f"property counts mismatch: {activity.name}",
        )
        expected_rr = {item["revision_id"] for item in json_load(ROOT / "finalization_resolution_plan.json")["items"] if item["activity"] == activity.name}
        actual_rr = {item.get("revision_id") for item in rat.get("resolved_findings", [])}
        log.require(actual_rr == expected_rr, f"required revisions not exactly resolved: {activity.name}")

    log.require(len(all_submission_case_ids) == 72, "expected 72 unique canonical submission cases")
    if not log.failures:
        log.passed("12 activities, 72 neutral cases, strict ratifications, source refs, and snapshot hashes")
    return activities, activity_ids


def validate_fixtures(log: CheckLog, activity_ids: set[str]) -> None:
    fixture_paths = sorted((ROOT / "benchmark_fixtures/p09").glob("*.json"))
    log.require(len(fixture_paths) == 4, f"expected four P09 fixtures, found {len(fixture_paths)}")
    schema = json_load(ROOT / "_schemas/p09_approved_fixture.schema.json")
    root_keys = set(schema["properties"])
    root_required = set(schema["required"])
    question_keys = set(schema["$defs"]["question"]["properties"])
    question_required = set(schema["$defs"]["question"]["required"])
    fixture_ids: set[str] = set()
    question_ids: set[str] = set()
    covered = set()
    for path in fixture_paths:
        fixture = json_load(path)
        log.require(root_required.issubset(fixture), f"P09 fixture missing fields: {path.name}")
        log.require(set(fixture) == root_keys, f"P09 fixture has unknown fields: {path.name}")
        log.require(fixture.get("schema_version") == "p09-stage-fixture/1.0.0", f"wrong P09 schema: {path.name}")
        log.require(fixture.get("fixture_role") == "P09_STAGE_LOCAL_INPUT", f"wrong P09 role: {path.name}")
        log.require(fixture.get("question_role") == "FIXED_INPUT_FOR_P09_NOT_QUESTION_GOLDEN_FOR_P07", f"P09 question role is not stage-local: {path.name}")
        fixture_id = fixture.get("fixture_id")
        log.require(fixture_id not in fixture_ids, f"duplicate P09 fixture id: {fixture_id}")
        fixture_ids.add(fixture_id)
        activity_id = fixture.get("activity_id")
        log.require(activity_id in activity_ids, f"P09 references unknown activity: {path.name}")
        covered.add(activity_id[:6])
        match = ACTIVITY_ID_RE.fullmatch(activity_id or "")
        activity = ROOT / f"activity_{match.group(1)}_{match.group(2)}" if match else ROOT / "__missing__"
        submission_id = fixture.get("submission_id")
        source_group = sorted((activity / "submissions").glob(f"{submission_id}.*")) + sorted((activity / "submissions").glob(f"{submission_id}_artifact_*.*"))
        log.require(bool(source_group), f"P09 references unknown submission: {path.name}")
        questions = fixture.get("questions", [])
        log.require(len(questions) == 3, f"P09 fixture must contain three supported questions: {path.name}")
        for question in questions:
            log.require(question_required.issubset(question), f"P09 question missing fields: {path.name}")
            log.require(set(question) == question_keys, f"P09 question has unknown fields: {path.name}")
            question_id = question.get("question_fixture_id")
            log.require(question_id not in question_ids, f"duplicate P09 question id: {question_id}")
            question_ids.add(question_id)
            support = question.get("support_refs", [])
            visible = question.get("visible_anchor_refs", [])
            log.require(set(visible).issubset(set(support)), f"visible refs are not a support subset: {question_id}")
            log.require(bool(support) and bool(question.get("core_observables")), f"ungrounded P09 question: {question_id}")
            for reference in support:
                relative = reference.split("#", 1)[0]
                log.require(not relative.startswith("activity_") and ".." not in Path(relative).parts, f"cross-activity P09 ref: {question_id}")
                log.require((activity / relative).is_file(), f"unresolvable P09 source ref {relative}: {question_id}")
                if relative.startswith("submissions/"):
                    referenced_match = SUBMISSION_FILE_RE.fullmatch(Path(relative).name)
                    referenced_id = (
                        f"submission_{referenced_match.group(1)}"
                        if referenced_match
                        else None
                    )
                    log.require(
                        referenced_id == submission_id,
                        f"P09 source_ref points to wrong submission: {question_id}/{relative}",
                    )
    log.require(covered == {"act_03", "act_04", "act_09", "act_12"}, "P09 discipline coverage differs from required activities")
    if not log.failures:
        log.passed("four stage-local P09 fixtures and visible_anchor subset relation")


def validate_history(log: CheckLog) -> None:
    preservation = json_load(ROOT / "_audit_history/opus5/preservation_manifest.json")
    artifacts = preservation.get("artifacts", [])
    log.require(len(artifacts) == 14, "Opus preservation manifest must contain 14 artifacts")
    for item in artifacts:
        archive = ROOT / item["archive_path"]
        actual = sha256_file(archive) if archive.exists() else None
        log.require(item.get("before_sha256") == item.get("after_sha256") == actual, f"Opus history hash mismatch: {item.get('archive_path')}")
        log.require(item.get("hash_match") is True, f"Opus preservation flag is false: {item.get('archive_path')}")
    log.require(preservation.get("all_hashes_match") is True, "Opus preservation summary is false")
    old_mapping_markers = (
        "old_" + "submission_id",
        "new_" + "submission_id",
        "permutation_signature_" + "old_01_through_06",
    )
    for path in actual_paths():
        if path.startswith("_audit_history/"):
            continue
        candidate = ROOT / path
        if candidate.suffix.lower() not in {".json", ".md", ".txt", ".py"}:
            continue
        text = candidate.read_text(encoding="utf-8")
        for marker in old_mapping_markers:
            log.require(marker not in text, f"old id mapping leaked outside audit history: {path}")
    mapping = json_load(ROOT / "_audit_history/submission_id_mapping.json")
    log.require(mapping.get("all_activity_permutations_distinct") is True, "permutations are not all distinct")
    log.require(mapping.get("all_artifact_hashes_preserved") is True, "rename preservation summary is false")
    log.require(mapping.get("old_submission_06_post_permutation_distribution") == {f"submission_{n:02d}": 2 for n in range(1, 7)}, "post-permutation distribution is not uniform")
    if not log.failures:
        log.passed("Opus history byte preservation and mapping confinement")


def validate_integrity_and_corrections(log: CheckLog, activities: list[Path]) -> None:
    docx_paths = sorted(path for activity in activities for path in activity.glob("*.docx"))
    pdf_paths = sorted(path for activity in activities for path in (activity / "submissions").glob("*.pdf"))
    text_paths = sorted(
        path
        for activity in activities
        for path in (activity / "submissions").iterdir()
        if path.suffix.lower() in {".md", ".txt"}
    )
    extracted_docx: dict[str, str] = {}
    for path in docx_paths:
        try:
            extracted = docx_text(path)
            extracted_docx[path.relative_to(ROOT).as_posix()] = extracted
            log.require(bool(extracted.strip()), f"empty DOCX text: {path}")
        except Exception as error:
            log.require(False, f"unreadable DOCX {path}: {error}")
    for path in pdf_paths:
        data = path.read_bytes()
        log.require(data.startswith(b"%PDF-"), f"bad PDF header: {path}")
        log.require(b"%%EOF" in data[-2048:], f"missing PDF EOF marker: {path}")
        log.require(len(re.findall(rb"/Type\s*/Page\b", data)) >= 1, f"PDF has no page object: {path}")
    for path in text_paths:
        try:
            text = path.read_text(encoding="utf-8")
            log.require(bool(text.strip()), f"empty text artifact: {path}")
        except UnicodeDecodeError:
            log.require(False, f"non-UTF-8 artifact: {path}")

    clarification = (
        "La extensión indicada es una guía de formato. No constituye por sí misma "
        "un criterio de evaluación; el trabajo se evalúa por la evidencia y el razonamiento solicitados."
    )
    for number in (5, 6, 7, 9, 10, 11, 12):
        key = next(key for key in extracted_docx if key.startswith(f"activity_{number:02d}_") and key.endswith("01_assignment.docx"))
        log.require(clarification in extracted_docx[key], f"extension policy missing from activity {number:02d}")
    act08_key = next(key for key in extracted_docx if key.startswith("activity_08_") and key.endswith("01_assignment.docx"))
    superseded_private_ip = "10" + ".1.4.22"
    log.require("192.0.2.44" in extracted_docx[act08_key] and superseded_private_ip not in extracted_docx[act08_key], "activity 08 documentation IP correction failed")

    non_audit_text = []
    for path_string in actual_paths():
        if path_string.startswith("_audit_history/"):
            continue
        path = ROOT / path_string
        if path.suffix.lower() in {".json", ".md", ".txt", ".py"}:
            non_audit_text.append(path.read_text(encoding="utf-8"))
    non_audit_text.extend(extracted_docx.values())
    canonical_text = "\n".join(non_audit_text)
    forbidden_formulations = {
        "superseded band distribution": re.compile(r"15\s*/\s*7\s*/\s*4"),
        "superseded length range": re.compile(r"700\s*[–-]\s*1[.]?100"),
        "obsolete Barrio transition": re.compile(r"660\s*(?:→|->)\s*690"),
        "old private IP": re.compile(r"\b10[.]" + r"1[.]4[.]22\b"),
        "old LAB identifier": re.compile("LAB-12H-4H-" + "7F3A9C"),
    }
    for label, pattern in forbidden_formulations.items():
        log.require(not pattern.search(canonical_text), f"obsolete canonical formulation remains: {label}")
    retained_identity = "Camila" + " Paredes"
    log.require(canonical_text.count(retained_identity) == 1, "simulated identity was not diversified exactly once")
    log.require("Lucía Torres" in canonical_text and "CLIN-SIM-0178" in canonical_text, "replacement simulated identity is missing")

    resolution_log = json_load(ROOT / "corpus_finalization_resolution_log.json")
    log.require(len(resolution_log.get("cluster_findings", [])) == 10, "resolution ledger does not contain CL-01..CL-10")
    log.require(len(resolution_log.get("required_revisions", [])) == 40, "resolution ledger does not contain 40 required revisions")
    log.require("UNRESOLVED" not in json.dumps(resolution_log), "resolution ledger contains UNRESOLVED")
    log.require(resolution_log.get("readiness") == "CORPUS_READY_FOR_SEMANTIC_BENCHMARK", "resolution ledger is not READY")
    if not log.failures:
        log.passed(f"integrity: {len(docx_paths)} DOCX, {len(pdf_paths)} PDF, {len(text_paths)} UTF-8 source artifacts")


def validate_security(log: CheckLog, activities: list[Path]) -> None:
    text_parts: list[str] = []
    for activity in activities:
        for path in [activity / "01_assignment.docx", activity / "02_rubric.docx"]:
            text_parts.append(docx_text(path))
        for path in (activity / "submissions").iterdir():
            if path.suffix.lower() in {".md", ".txt"}:
                text_parts.append(path.read_text(encoding="utf-8"))
    corpus_text = "\n".join(text_parts)
    emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", corpus_text)
    log.require(all(email.lower().endswith(".invalid") for email in emails), "non-.invalid email domain found")
    ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", corpus_text)
    allowed_ip_prefixes = ("192.0.2.", "198.51.100.", "203.0.113.")
    log.require(all(ip.startswith(allowed_ip_prefixes) for ip in ips), "non-documentation IPv4 address found")
    suspicious_tokens = re.findall(r"\b(?:sk|pk|api)[_-][A-Za-z0-9_-]{8,}\b", corpus_text, flags=re.IGNORECASE)
    log.require(all(token == "sk_test_NOT_REAL_0042" for token in suspicious_tokens), "unapproved secret-like token found")
    phone_matches = re.findall(r"\+56\s+9\s+[0-9 ]{8,}", corpus_text)
    log.require(all("0000" in phone for phone in phone_matches), "non-fictitious-looking phone found")
    log.require("SYNTHETIC_ONLY_NO_STUDENT_DATA" in (ROOT / "corpus_manifest.md").read_text(encoding="utf-8"), "synthetic-only classification missing")
    if not log.failures:
        log.passed("security scan: reserved domains/IPs, fictitious phones/IDs, and known dummy token only")


def validate_arithmetic(log: CheckLog) -> None:
    checks = {
        "act01_height_12h_mean": math.isclose(sum([5.2, 5.8, 5.5]) / 3, 5.5),
        "act01_height_4h_mean": math.isclose(sum([3.0, 3.5, 3.2]) / 3, 3.2333333333333334),
        "act03_cost_80": math.isclose(18 + 14 + 80 * 0.46, 68.80),
        "act03_cost_75": math.isclose(18 + 14 + 75 * 0.46, 66.50),
        "act03_budget_max": math.floor((70 - 18 - 14) / 0.46) == 82 and 18 + 14 + 83 * 0.46 > 70,
        "act05_daily_rates": [880 / 22, 800 / 20, 1150 / 23, 1050 / 21, 660 / 22, 600 / 20, 690 / 23, 630 / 21] == [40, 40, 50, 50, 30, 30, 30, 30],
        "act06_row_and_support_totals": [14 + 4 + 2, 5 + 15 + 5, 1 + 9 + 5] == [20, 25, 15] and sum([15, 8, 3]) == 26,
        "act07_drop_order": sorted({"papel": 13, "lana": 15, "aluminio": 18}.items(), key=lambda item: item[1])[0][0] == "papel",
        "act09_quantitative_relations": math.isclose(27 / 18, 1.5) and math.isclose((27 - 18) / 18, 0.5) and 118 - 76 == 42 and 22 - 18 == 4,
        "act10_segment_and_global_rates": [720 / 800, 660 / 1200, 1020 / 1200, 480 / 800, (720 + 660) / 2000, (1020 + 480) / 2000] == [0.90, 0.55, 0.85, 0.60, 0.69, 0.75],
        "act12_capacity_and_denominators": sum([42, 60, 35]) == 137 and sum([12, 18, 20]) == 50 and 2 * 24 == 48 and 60 - 48 == 12,
        "act12_five_alternatives": [(18 + 20, 60 + 35 - 48), (18 + 12, 60 + 42 - 48), (20 + 12, 35 + 42 - 48), (18, 60 - 48), (20, 48 - 35)] == [(38, 47), (30, 54), (32, 29), (18, 12), (20, 13)],
    }
    for name, result in checks.items():
        log.require(result, f"arithmetic regression failed: {name}")
    if not log.failures:
        log.passed("deterministic arithmetic regressions for activities 01, 03, 05, 06, 07, 09, 10, and 12")


def validate_activity04_code(log: CheckLog) -> None:
    directory = ROOT / "activity_04_asignador_de_turnos/submissions"
    code_files = sorted(path for path in directory.glob("*.md") if "```python" in path.read_text(encoding="utf-8"))
    expected = {
        "submission_01_artifact_01.md": {"exception": None, "mutated": False, "result": {"asignadas": ["b", "d"], "espera": []}},
        "submission_02_artifact_01.md": {"exception": None, "mutated": False, "result": {"asignadas": ["b", "d"], "espera": []}},
        "submission_03.md": {"exception": None, "mutated": False, "result": {"asignadas": ["d", "b"], "espera": ["d", "x", None]}},
        "submission_04_artifact_01.md": {"exception": None, "mutated": False, "result": {"asignadas": ["VIP"], "espera": []}},
        "submission_05_artifact_01.md": {"exception": None, "mutated": False, "result": {"asignadas": ["b", "d"], "espera": []}},
        "submission_06_artifact_01.md": {"exception": "KeyError", "mutated": False, "result": None},
    }
    log.require({path.name for path in code_files} == set(expected), "activity 04 code artifact set changed")
    safe_builtins = {
        "all": all,
        "dict": dict,
        "enumerate": enumerate,
        "Exception": Exception,
        "KeyError": KeyError,
        "list": list,
        "set": set,
        "sorted": sorted,
        "sum": sum,
        "TypeError": TypeError,
    }
    for path in code_files:
        block_match = re.search(r"```python\s*\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL)
        log.require(bool(block_match), f"missing Python fence: {path.name}")
        if not block_match:
            continue
        namespace: dict[str, Any] = {"__builtins__": safe_builtins}
        try:
            exec(compile(block_match.group(1), path.name, "exec"), namespace)
            function = namespace["asignar_turnos"]
            sample = [
                {"id": "d", "grupo": "A", "prioridad": 2, "marca": "09:02"},
                {"id": "d", "grupo": "A", "prioridad": 1, "marca": "09:01"},
                {"id": "b", "grupo": "B", "prioridad": 1, "marca": "09:00"},
                {"id": "x", "grupo": "A", "prioridad": 4, "marca": "09:03"},
                {},
            ]
            before = copy.deepcopy(sample)
            try:
                result = function(sample, {"A": 1, "B": 1})
                signature = {"exception": None, "mutated": sample != before, "result": result}
            except Exception as error:  # deliberate student defects are part of the signature
                signature = {"exception": type(error).__name__, "mutated": sample != before, "result": None}
            log.require(signature == expected[path.name], f"activity 04 semantic signature changed: {path.name}")
        except Exception as error:
            log.require(False, f"activity 04 code could not be executed safely: {path.name}: {error}")
    if not log.failures:
        log.passed("six activity 04 code artifacts retain their pre-freeze semantic signatures")


def main() -> int:
    log = CheckLog()
    validate_manifest(log)
    activities, activity_ids = validate_activities(log)
    validate_fixtures(log, activity_ids)
    validate_history(log)
    validate_integrity_and_corrections(log, activities)
    validate_security(log, activities)
    validate_arithmetic(log)
    validate_activity04_code(log)

    if log.failures:
        print("FINAL CORPUS VALIDATION: FAIL")
        for failure in log.failures:
            print(f"FAIL: {failure}")
        return 1
    print("FINAL CORPUS VALIDATION: PASS")
    for passed in log.passes:
        print(f"PASS: {passed}")
    print("CORPUS_READY_FOR_SEMANTIC_BENCHMARK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
