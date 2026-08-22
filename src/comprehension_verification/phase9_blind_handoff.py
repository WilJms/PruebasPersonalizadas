"""Make the Phase 9B blind bundle self-contained for an isolated adjudicator.

Phase 9B.1 produced 38 review packets that name their authorized sources by
reference and hash, which is enough for a reader who already has the repository
and is exactly wrong for the reader this bundle is meant for: a fresh context
with no repository, no candidate matrix, no execution evidence and no prior
conversation.

This module adds the missing surface without touching the packets. It resolves
every declared source reference to one frozen artifact, copies those artifacts
in byte-exact content-addressed form, projects each through the real product
parser so a reader without DOCX tooling can still follow a locator, and binds
each declared reference to the units it names.

Two rules shape the whole thing:

* The packets are canonical and immutable. Source material is a separate
  hash-bound surface; packet bytes and packet hashes must come out identical.
* Nothing here adjudicates. Reference resolution is exact and mechanical — a
  section label that does not equal a parser heading is reported as advisory
  rather than matched by similarity, because guessing which heading was meant
  is the adjudicator's reading to do, not this module's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Final

from .canonical import canonical_hash
from .contracts import models as m
from .parsers.service import SafeParserService


BLIND_HANDOFF_VERSION: Final = "phase9-blind-handoff/1.0.0"
BENCHMARK_TENANT_ID: Final = "tenant_semantic_benchmark"

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
CORPUS_ROOT: Final = REPOSITORY_ROOT / "evaluation/corpora/pruebas_personalizadas/v1"
ADJUDICATION_BUNDLE_ROOT: Final = (
    REPOSITORY_ROOT / "reports/semantic_benchmark/v1_1/phase9/adjudication_bundles"
)
PHASE9B1_EXECUTION_ID: Final = "exec-phase9b1-bfd3cf082617ea8b"

EXPECTED_PACKET_COUNT: Final = 38

# Only these corpus roles may enter the handoff. Ratifications, audit history,
# compiled properties and corpus authority reports are oracle-side material and
# are excluded by construction, not by filtering after the fact.
PERMITTED_SOURCE_FILENAMES: Final = ("01_assignment.docx", "02_rubric.docx")
PERMITTED_SOURCE_PREFIXES: Final = ("submissions/",)
FORBIDDEN_SOURCE_MARKERS: Final = (
    "final_ratification",
    "_audit_history",
    "_schemas",
    "corpus_final_manifest",
    "corpus_finalization",
    "corpus_manifest",
    "CORPUS_AUTHORITY",
    "benchmark_fixtures",
    "finalization_resolution",
    "future_corpus_extensions",
)


class BlindHandoffError(RuntimeError):
    """Fail-closed stop while packaging the blind adjudication handoff."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """One frozen source artifact required by at least one packet."""

    declared_ref: str
    corpus_relative_path: str
    sha256: str
    media_type: str
    role: str
    blob_name: str


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return canonical_hash(payload)


def bundle_root(execution_id: str = PHASE9B1_EXECUTION_ID) -> Path:
    return ADJUDICATION_BUNDLE_ROOT / execution_id


# ---------------------------------------------------------------------------
# Existing bundle audit
# ---------------------------------------------------------------------------


def audit_existing_bundle(root: Path) -> dict[str, Any]:
    """Inventory the untouched packet surface before anything is added."""

    manifest = json.loads((root / "bundle_manifest.json").read_text("utf-8"))
    rows: list[dict[str, Any]] = []
    for entry in manifest["packets"]:
        path = root / entry["file"]
        packet = json.loads(path.read_text("utf-8"))
        observed = canonical_hash(packet)
        if observed != entry["packet_hash"]:
            raise BlindHandoffError(
                "BLIND_PACKET_HASH_MISMATCH",
                f"{entry['packet_id']} does not match its manifest hash",
            )
        rows.append(
            {
                "packet_id": entry["packet_id"],
                "packet_hash": entry["packet_hash"],
                "file_sha256": _sha256_file(path),
                "case_id": packet["case_id"],
                "stage": packet["stage"],
                "relevant_source_refs": packet.get("relevant_source_refs") or [],
                "source_hashes": packet.get("source_hashes") or {},
            }
        )
    if len(rows) != EXPECTED_PACKET_COUNT:
        raise BlindHandoffError(
            "BLIND_PACKET_COUNT_UNEXPECTED",
            f"expected {EXPECTED_PACKET_COUNT} packets, found {len(rows)}",
        )
    return {
        "packet_count": len(rows),
        "bundle_manifest_hash": canonical_hash(manifest),
        "packet_schema": manifest["packet_schema"],
        "packet_schema_hash": manifest["packet_schema_hash"],
        "leakage_scan": manifest["leakage_scan"],
        "packets": rows,
    }


# ---------------------------------------------------------------------------
# Exact source resolution
# ---------------------------------------------------------------------------


_ACTIVITY_PREFIX = re.compile(r"^PP-A(\d+)-")
_SUBMISSION_ID = re.compile(r"(submission_\d+)")


def _activity_directories() -> dict[int, str]:
    return {
        int(item.name.split("_")[1]): item.name
        for item in CORPUS_ROOT.iterdir()
        if item.is_dir() and item.name.startswith("activity_")
    }


def _role_for(declared_ref: str) -> m.ArtifactRole:
    if declared_ref == "01_assignment.docx":
        return m.ArtifactRole.ASSIGNMENT_PROMPT
    if declared_ref == "02_rubric.docx":
        return m.ArtifactRole.RUBRIC
    return m.ArtifactRole.SUBMISSION


def _assert_permitted(declared_ref: str) -> None:
    """Refuse anything outside assignment, rubric and submission material."""

    if any(marker in declared_ref for marker in FORBIDDEN_SOURCE_MARKERS):
        raise BlindHandoffError(
            "BLIND_SOURCE_REF_FORBIDDEN",
            f"{declared_ref} names oracle-side or authority material",
        )
    permitted = declared_ref in PERMITTED_SOURCE_FILENAMES or declared_ref.startswith(
        PERMITTED_SOURCE_PREFIXES
    )
    if not permitted:
        raise BlindHandoffError(
            "BLIND_SOURCE_REF_FORBIDDEN",
            f"{declared_ref} is not authorized source input",
        )


def _blob_name(sha256: str, declared_ref: str) -> str:
    suffix = Path(declared_ref).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix or ""):
        suffix = ".bin"
    return f"{sha256.replace(':', '-')}{suffix}"


def resolve_sources(audit: Mapping[str, Any]) -> dict[str, ResolvedSource]:
    """Resolve every declared reference to exactly one frozen artifact.

    The activity comes from the packet's own ``case_id`` — a field the
    adjudicator already sees — and the declared hash then has to match the bytes
    at that path. Both directions must agree; there is no filename search, no
    first-match fallback and no cross-activity substitution.
    """

    activities = _activity_directories()
    resolved: dict[str, ResolvedSource] = {}
    parser = SafeParserService()
    for packet in audit["packets"]:
        match = _ACTIVITY_PREFIX.match(packet["case_id"])
        if match is None:
            raise BlindHandoffError(
                "BLIND_SOURCE_REF_UNRESOLVED",
                f"{packet['packet_id']} carries an unparseable case id",
            )
        activity = activities.get(int(match.group(1)))
        if activity is None:
            raise BlindHandoffError(
                "BLIND_SOURCE_REF_UNRESOLVED",
                f"{packet['packet_id']} names an unknown activity",
            )
        for declared_ref, declared_hash in packet["source_hashes"].items():
            _assert_permitted(declared_ref)
            path = CORPUS_ROOT / activity / declared_ref
            if not path.is_file():
                raise BlindHandoffError(
                    "BLIND_SOURCE_REF_UNRESOLVED",
                    f"{declared_ref} does not exist under {activity}",
                )
            actual = _sha256_file(path)
            if actual != declared_hash:
                raise BlindHandoffError(
                    "BLIND_SOURCE_REF_UNRESOLVED",
                    f"{activity}/{declared_ref} does not match its declared hash",
                )
            siblings = [
                candidate
                for candidate in CORPUS_ROOT.rglob(Path(declared_ref).name)
                if candidate.is_file() and _sha256_file(candidate) == declared_hash
            ]
            if len({candidate.read_bytes() for candidate in siblings}) > 1:
                raise BlindHandoffError(
                    "BLIND_SOURCE_REF_AMBIGUOUS",
                    f"{declared_ref} resolves to differing bytes at {declared_hash}",
                )
            role = _role_for(declared_ref)
            kwargs: dict[str, Any] = {}
            if role is m.ArtifactRole.SUBMISSION:
                found = _SUBMISSION_ID.search(declared_ref)
                if found is None:
                    raise BlindHandoffError(
                        "BLIND_SOURCE_REF_UNRESOLVED",
                        f"{declared_ref} carries no submission identity",
                    )
                kwargs["submission_id"] = found.group(1)
            parsed = parser.parse(
                path,
                tenant_id=BENCHMARK_TENANT_ID,
                source_role=role,
                **kwargs,
            )
            if parsed.artifact.sha256 != declared_hash:
                raise BlindHandoffError(
                    "BLIND_SOURCE_REF_UNRESOLVED",
                    f"{declared_ref} parsed to a different artifact hash",
                )
            record = ResolvedSource(
                declared_ref=declared_ref,
                corpus_relative_path=f"{activity}/{declared_ref}",
                sha256=declared_hash,
                media_type=parsed.artifact.media_type,
                role=role.value,
                blob_name=_blob_name(declared_hash, declared_ref),
            )
            existing = resolved.get(declared_hash)
            if existing is not None and existing.corpus_relative_path != (
                record.corpus_relative_path
            ):
                raise BlindHandoffError(
                    "BLIND_SOURCE_REF_AMBIGUOUS",
                    f"{declared_hash} maps to two corpus paths",
                )
            resolved[declared_hash] = record
    return resolved


def project_source(source: ResolvedSource) -> dict[str, Any]:
    """Project one artifact through the real parser, source-derived fields only.

    No labels, no summary, no rewriting, no inference — just the units the
    product's own parser produces, in source order, so a reader without DOCX or
    PDF tooling can still follow a locator. The raw artifact stays authoritative
    if a projection ever looks like it disagrees with it.
    """

    path = CORPUS_ROOT / source.corpus_relative_path
    role = m.ArtifactRole(source.role)
    kwargs: dict[str, Any] = {}
    if role is m.ArtifactRole.SUBMISSION:
        found = _SUBMISSION_ID.search(source.declared_ref)
        if found is not None:
            kwargs["submission_id"] = found.group(1)
    parsed = SafeParserService().parse(
        path, tenant_id=BENCHMARK_TENANT_ID, source_role=role, **kwargs
    )
    units = []
    for order, unit in enumerate(parsed.evidence_units):
        locator = unit.locator.model_dump(mode="json")
        units.append(
            {
                "source_order": order,
                "evidence_id": unit.evidence_id,
                "locator": locator,
                "modality": unit.modality.value
                if hasattr(unit.modality, "value")
                else str(unit.modality),
                "content_text": unit.content_text,
                "normalized_hash": unit.normalized_hash,
            }
        )
    return {
        "schema_version": "phase9-blind-source-projection/1.0.0",
        "source_content_hash": source.sha256,
        "media_type": source.media_type,
        "parser_id": parsed.artifact.parser_id,
        "parser_version": parsed.artifact.parser_version,
        "byte_size": parsed.artifact.byte_size,
        "unit_count": len(units),
        "units": units,
    }


# ---------------------------------------------------------------------------
# Locator bindings
# ---------------------------------------------------------------------------


def bind_locators(
    audit: Mapping[str, Any],
    resolved: Mapping[str, ResolvedSource],
    projections: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind each declared reference to its artifact and, exactly, its units.

    File resolution is exact and hash-verified for every reference. A ``section``
    hint binds only when it equals a parser heading; otherwise it is reported as
    advisory with the full ordered unit list, because choosing which heading a
    descriptive label "really means" is reading, and reading is the
    adjudicator's job. Plain-text sources carry no headings at all, so most
    advisory cases are simply that.
    """

    bindings: list[dict[str, Any]] = []
    for packet in audit["packets"]:
        for ref in packet["relevant_source_refs"]:
            declared_ref = ref["file"] if isinstance(ref, Mapping) else str(ref)
            section = ref.get("section") if isinstance(ref, Mapping) else None
            declared_hash = packet["source_hashes"].get(declared_ref)
            if declared_hash is None:
                raise BlindHandoffError(
                    "BLIND_SOURCE_REF_UNRESOLVED",
                    f"{declared_ref} has no hash in {packet['packet_id']}",
                )
            source = resolved[declared_hash]
            projection = projections[declared_hash]
            headings = {
                heading
                for unit in projection["units"]
                for heading in (unit["locator"].get("heading_path") or [])
            }
            if section is None:
                status = "RESOLVED_FILE_SCOPE"
                matched = [unit["evidence_id"] for unit in projection["units"]]
            elif section in headings:
                status = "RESOLVED_EXACT_SECTION"
                matched = [
                    unit["evidence_id"]
                    for unit in projection["units"]
                    if section in (unit["locator"].get("heading_path") or [])
                ]
            else:
                status = "RESOLVED_FILE_SCOPE_SECTION_ADVISORY"
                matched = [unit["evidence_id"] for unit in projection["units"]]
            bindings.append(
                {
                    "packet_id": packet["packet_id"],
                    "declared_ref": declared_ref,
                    "declared_section": section,
                    "source_blob_hash": declared_hash,
                    "source_blob_path": f"sources/{source.blob_name}",
                    "projection_path": f"projections/{source.blob_name}.json",
                    "available_headings": sorted(headings),
                    "matched_evidence_ids": matched,
                    "matched_unit_count": len(matched),
                    "resolution_status": status,
                }
            )
    return bindings


# ---------------------------------------------------------------------------
# Leakage audit over the whole handoff
# ---------------------------------------------------------------------------

METADATA_LEAK_TOKENS: Final = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.6",
    "reasoning_effort",
    "route_profile",
    "LUNA_BASELINE_V1",
    "TERRA_HIGH_V1",
    "LUNA_XHIGH_V1",
    "LUNA_MAX_V1",
    "TERRA_XHIGH_V1",
    "promotion_order",
    "candidate_id",
    "candidate_model",
    "authorization_id",
    "authorization_hash",
    "HELD_OUT",
    "SMOKE",
    "actual_cost_usd",
    "latency_ms",
    "attempt_index",
    "logical_call_id",
    "exec-phase9b1",
)

# Bare words that occur naturally in Spanish source text ("sol" = sun) or in the
# product's own domain contracts. They are only leaks in a metadata position.
CONTEXT_SENSITIVE_TOKENS: Final = (
    "luna",
    "terra",
    "sol",
    "candidate",
    "cost",
    "USD",
    "CORE",
    "MAX",
    "XHIGH",
    "HIGH",
)

SOURCE_CONTENT_KEYS: Final = (
    "content_text",
    "candidate_output",
    "property",
    "defensible_alternatives",
    "relevant_source_refs",
    "available_headings",
    "declared_section",
)

# Audit files quote the very strings they scanned, so their finding records are
# quotation, not metadata. Scanning them as ordinary content would also make the
# audit grow on every re-run by rediscovering its own previous findings.
AUDIT_RECORD_KEYS: Final = (
    "scans",
    "leaks",
    "metadata_leaks",
    "documented_exceptions",
)
SELF_AUDIT_FILENAMES: Final = ("handoff_leakage_audit.json",)


def _iter_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            out.extend(_iter_strings(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            out.extend(_iter_strings(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        out.append((path, value))
    return out


def _iter_keys(value: Any, path: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            out.append((child, str(key)))
            out.extend(_iter_keys(item, child))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            out.extend(_iter_keys(item, f"{path}[{index}]"))
    return out


def _in_source_content(path: str) -> bool:
    """True when a field path sits inside authorized source or quoted material."""

    permitted = SOURCE_CONTENT_KEYS + AUDIT_RECORD_KEYS
    return any(segment.split("[")[0] in permitted for segment in path.split("."))


def _word_present(token: str, text: str) -> bool:
    """Match a bare word, not a substring.

    ``sol`` is the Spanish word for sun and also lives inside ``RESOLVED``;
    treating it as a substring made every resolution status look like a model
    name. Full model identifiers stay substring-matched because they are
    specific enough to never appear by accident.
    """

    return re.search(rf"(?<![0-9A-Za-z_]){re.escape(token)}(?![0-9A-Za-z_])",
                     text, flags=re.IGNORECASE) is not None


def scan_handoff_for_leakage(root: Path) -> dict[str, Any]:
    """Scan every handoff file, and its own path, for run metadata."""

    leaks: list[dict[str, Any]] = []
    source_occurrences = 0
    scanned = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        scanned += 1
        relative = str(path.relative_to(root))
        for token in METADATA_LEAK_TOKENS:
            if token.casefold() in relative.casefold():
                leaks.append(
                    {"kind": "FILENAME", "path": relative, "token": token}
                )
        for token in CONTEXT_SENSITIVE_TOKENS:
            if _word_present(token, relative):
                leaks.append(
                    {"kind": "FILENAME", "path": relative, "token": token}
                )
        if path.suffix != ".json" or path.name in SELF_AUDIT_FILENAMES:
            continue
        payload = json.loads(path.read_text("utf-8"))
        # A leak can hide in a field name as easily as in a value.
        for field_path, key in _iter_keys(payload):
            if _in_source_content(field_path):
                continue
            for token in METADATA_LEAK_TOKENS:
                if token.casefold() in key.casefold():
                    leaks.append(
                        {
                            "kind": "METADATA_FIELD_NAME",
                            "path": relative,
                            "field": field_path,
                            "token": token,
                        }
                    )
        for field_path, text in _iter_strings(payload):
            quoted = _in_source_content(field_path)
            for token in METADATA_LEAK_TOKENS:
                if token.casefold() not in text.casefold():
                    continue
                if quoted:
                    source_occurrences += 1
                else:
                    leaks.append(
                        {
                            "kind": "METADATA_LEAK",
                            "path": relative,
                            "field": field_path,
                            "token": token,
                        }
                    )
            for token in CONTEXT_SENSITIVE_TOKENS:
                if not _word_present(token, text):
                    continue
                if quoted:
                    source_occurrences += 1
                else:
                    leaks.append(
                        {
                            "kind": "METADATA_LEAK",
                            "path": relative,
                            "field": field_path,
                            "token": token,
                        }
                    )
    return {
        "schema_version": "phase9-blind-handoff-leakage-audit/1.0.0",
        "files_scanned": scanned,
        "metadata_leaks": leaks,
        "metadata_leak_count": len(leaks),
        "source_content_occurrences": source_occurrences,
        "result": "PASS" if not leaks else "BLOCKED",
    }


# ---------------------------------------------------------------------------
# Build and verify
# ---------------------------------------------------------------------------


STANDALONE_VERIFIER_FILENAME: Final = "verify_handoff.py"
STANDALONE_VERIFIER_SOURCE: Final = '#!/usr/bin/env python3\n"""Verify this blind adjudication handoff is complete, using only the stdlib.\n\nRun it from inside the handoff directory:\n\n    python3 verify_handoff.py\n\nIt reads nothing outside this directory. Every packet hash, every source\nartifact, every parser projection and every locator binding is checked against\nthe manifests shipped here, so a reader with no access to the originating\nrepository can still confirm the material is intact before reading it.\n"""\n\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nfrom pathlib import Path\nimport sys\n\n\ndef canonical_hash(value: object) -> str:\n    encoded = json.dumps(\n        value,\n        ensure_ascii=False,\n        sort_keys=True,\n        separators=(",", ":"),\n        allow_nan=False,\n    ).encode("utf-8")\n    return "sha256:" + hashlib.sha256(encoded).hexdigest()\n\n\ndef file_hash(path: Path) -> str:\n    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()\n\n\ndef load(root: Path, name: str) -> object:\n    return json.loads((root / name).read_text(encoding="utf-8"))\n\n\ndef main() -> int:\n    root = Path(__file__).resolve().parent\n    failures: list[str] = []\n\n    handoff = load(root, "blind_handoff_manifest.json")\n    bundle = load(root, "bundle_manifest.json")\n    sources = load(root, "source_material_manifest.json")\n    bindings = load(root, "locator_bindings.json")\n\n    packets = 0\n    for entry in bundle["packets"]:\n        path = root / entry["file"]\n        if not path.is_file():\n            failures.append(f"missing packet {entry[\'file\']}")\n            continue\n        packet = json.loads(path.read_text(encoding="utf-8"))\n        if canonical_hash(packet) != entry["packet_hash"]:\n            failures.append(f"packet hash drift {entry[\'packet_id\']}")\n            continue\n        if handoff["packet_hashes"].get(entry["packet_id"]) != entry["packet_hash"]:\n            failures.append(f"packet hash disagrees with handoff {entry[\'packet_id\']}")\n            continue\n        packets += 1\n\n    blobs = 0\n    for row in sources["sources"]:\n        blob = root / row["source_blob_path"]\n        projection = root / row["projection_path"]\n        if not blob.is_file():\n            failures.append(f"missing source {row[\'source_blob_path\']}")\n            continue\n        if file_hash(blob) != row["source_blob_hash"]:\n            failures.append(f"source byte drift {row[\'source_blob_path\']}")\n            continue\n        if not projection.is_file():\n            failures.append(f"missing projection {row[\'projection_path\']}")\n            continue\n        if canonical_hash(\n            json.loads(projection.read_text(encoding="utf-8"))\n        ) != row["projection_hash"]:\n            failures.append(f"projection drift {row[\'projection_path\']}")\n            continue\n        blobs += 1\n\n    # Every source hash a packet declares must be present as a real artifact.\n    present = {row["source_blob_hash"] for row in sources["sources"]}\n    for relation in sources["packet_sources"]:\n        if relation["source_blob_hash"] not in present:\n            failures.append(\n                f"{relation[\'packet_id\']} declares an absent source artifact"\n            )\n\n    resolved = 0\n    covered: set[str] = set()\n    for row in bindings["bindings"]:\n        blob = root / row["source_blob_path"]\n        projection = root / row["projection_path"]\n        if not blob.is_file() or not projection.is_file():\n            failures.append(f"unfollowable ref {row[\'packet_id\']} {row[\'declared_ref\']}")\n            continue\n        units = json.loads(projection.read_text(encoding="utf-8"))["units"]\n        known = {unit["evidence_id"] for unit in units}\n        if not set(row["matched_evidence_ids"]) <= known:\n            failures.append(f"binding names an unknown unit {row[\'packet_id\']}")\n            continue\n        resolved += 1\n        covered.add(row["packet_id"])\n\n    report = {\n        "packets_verified": packets,\n        "packets_expected": handoff["packet_count"],\n        "source_artifacts_verified": blobs,\n        "declared_refs_resolved": resolved,\n        "declared_refs_expected": handoff["declared_source_refs"],\n        "packets_with_resolvable_sources": len(covered),\n        "failures": failures,\n        "SELF_CONTAINED_SOURCE_RESOLUTION": (\n            not failures\n            and packets == handoff["packet_count"]\n            and len(covered) == handoff["packet_count"]\n            and resolved == handoff["declared_source_refs"]\n        ),\n    }\n    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))\n    return 0 if report["SELF_CONTAINED_SOURCE_RESOLUTION"] else 1\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'


def build_blind_handoff(
    *, execution_id: str = PHASE9B1_EXECUTION_ID, root: Path | None = None
) -> dict[str, Any]:
    """Add the source surface to an existing bundle without touching packets."""

    root = root if root is not None else bundle_root(execution_id)
    if not (root / "bundle_manifest.json").is_file():
        raise BlindHandoffError(
            "BLIND_BUNDLE_MISSING", f"no bundle manifest under {root}"
        )
    audit = audit_existing_bundle(root)
    before = {row["packet_id"]: row["file_sha256"] for row in audit["packets"]}

    resolved = resolve_sources(audit)
    projections = {
        digest: project_source(source) for digest, source in resolved.items()
    }

    sources_dir = root / "sources"
    projections_dir = root / "projections"
    sources_dir.mkdir(parents=True, exist_ok=True)
    projections_dir.mkdir(parents=True, exist_ok=True)

    source_rows: list[dict[str, Any]] = []
    for digest, source in sorted(resolved.items()):
        blob = sources_dir / source.blob_name
        shutil.copyfile(CORPUS_ROOT / source.corpus_relative_path, blob)
        copied = _sha256_file(blob)
        if copied != digest:
            raise BlindHandoffError(
                "BLIND_SOURCE_COPY_MISMATCH",
                f"copied bytes for {source.blob_name} do not match the frozen hash",
            )
        projection_hash = _write_json(
            projections_dir / f"{source.blob_name}.json", projections[digest]
        )
        source_rows.append(
            {
                "source_blob_hash": digest,
                "source_blob_path": f"sources/{source.blob_name}",
                "projection_path": f"projections/{source.blob_name}.json",
                "projection_hash": projection_hash,
                "declared_ref": source.declared_ref,
                "media_type": source.media_type,
                "role": source.role,
                "unit_count": projections[digest]["unit_count"],
            }
        )

    bindings = bind_locators(audit, resolved, projections)
    bindings_hash = _write_json(
        root / "locator_bindings.json",
        {
            "schema_version": "phase9-blind-locator-bindings/1.0.0",
            "binding_count": len(bindings),
            "bindings": bindings,
        },
    )

    packet_source_rows = []
    for packet in audit["packets"]:
        for declared_ref, digest in sorted(packet["source_hashes"].items()):
            source = resolved[digest]
            packet_source_rows.append(
                {
                    "packet_id": packet["packet_id"],
                    "packet_hash": packet["packet_hash"],
                    "declared_ref": declared_ref,
                    "source_blob_hash": digest,
                    "source_blob_path": f"sources/{source.blob_name}",
                    "projection_path": f"projections/{source.blob_name}.json",
                    "resolution_status": "RESOLVED_EXACT_HASH",
                }
            )
    source_manifest_hash = _write_json(
        root / "source_material_manifest.json",
        {
            "schema_version": "phase9-blind-source-material/1.0.0",
            "unique_source_count": len(source_rows),
            "packet_source_relations": len(packet_source_rows),
            "sources": source_rows,
            "packet_sources": packet_source_rows,
            "source_authority": "RAW_ARTIFACT_BYTES_ARE_AUTHORITATIVE",
            "projection_note": (
                "Projections are produced by the product parser for readability. "
                "Where a projection and the raw artifact appear to disagree, the "
                "raw artifact governs."
            ),
        },
    )

    # A stdlib-only verifier ships with the bundle so the self-containment
    # claim can be checked by a reader who has none of this repository.
    verifier_path = root / STANDALONE_VERIFIER_FILENAME
    verifier_path.write_text(STANDALONE_VERIFIER_SOURCE, encoding="utf-8")
    verifier_hash = _sha256_file(verifier_path)

    leakage = scan_handoff_for_leakage(root)
    leakage_hash = _write_json(root / "handoff_leakage_audit.json", leakage)

    after = {
        row["packet_id"]: _sha256_file(root / f"packets/{row['packet_id']}.json")
        for row in audit["packets"]
    }
    if before != after:
        raise BlindHandoffError(
            "BLIND_PACKET_BYTES_MUTATED", "packet bytes changed during packaging"
        )

    resolvable = sum(
        1
        for row in bindings
        if row["resolution_status"].startswith("RESOLVED")
    )
    handoff = {
        "schema_version": BLIND_HANDOFF_VERSION,
        "generated_at": _utc_now(),
        "adjudication_protocol": "phase9-adjudication-protocol/1.0.0",
        "packet_schema": audit["packet_schema"],
        "packet_schema_hash": audit["packet_schema_hash"],
        "bundle_manifest_hash": audit["bundle_manifest_hash"],
        "packet_count": audit["packet_count"],
        "packet_hashes": {
            row["packet_id"]: row["packet_hash"] for row in audit["packets"]
        },
        "source_material_manifest_hash": source_manifest_hash,
        "locator_bindings_hash": bindings_hash,
        "leakage_audit_hash": leakage_hash,
        "standalone_verifier": STANDALONE_VERIFIER_FILENAME,
        "standalone_verifier_sha256": verifier_hash,
        "raw_source_hashes": sorted(resolved),
        "projection_hashes": {
            row["source_blob_path"]: row["projection_hash"] for row in source_rows
        },
        "declared_source_refs": len(bindings),
        "declared_source_refs_resolvable": resolvable,
        "layout": {
            "packets/": "one blind review packet per file, canonical and immutable",
            "sources/": "byte-exact authorized source artifacts, content-addressed",
            "projections/": "parser text projection per source artifact",
            "locator_bindings.json": "declared reference to artifact and units",
            "source_material_manifest.json": "packet to source relations",
            "bundle_manifest.json": "packet inventory and hashes",
            "verify_handoff.py": (
                "stdlib-only integrity check; run it inside this directory"
            ),
        },
        "SELF_CONTAINED_FOR_SOURCE_FIRST_ADJUDICATION": (
            leakage["result"] == "PASS" and resolvable == len(bindings)
        ),
        "contains_candidate_metadata": False,
        "contains_execution_metadata": False,
        "semantic_status": "PENDING_ADJUDICATION",
        "adjudication_performed_here": False,
    }
    handoff_hash = _write_json(root / "blind_handoff_manifest.json", handoff)
    return {
        "root": str(root),
        "handoff_manifest_hash": handoff_hash,
        "packet_count": audit["packet_count"],
        "unique_source_count": len(source_rows),
        "declared_source_refs": len(bindings),
        "declared_source_refs_resolvable": resolvable,
        "leakage": leakage,
        "packet_hashes_unchanged": before == after,
        "self_contained": handoff["SELF_CONTAINED_FOR_SOURCE_FIRST_ADJUDICATION"],
    }


def verify_self_contained(root: Path) -> dict[str, Any]:
    """Verify a copied handoff resolves everything without leaving its directory.

    Every path used here is derived from files inside ``root``; nothing consults
    the repository, the corpus, or the execution evidence. That is the whole
    point of the check, so it is written to fail if a required file is absent
    rather than to fall back to a repository copy.
    """

    handoff = json.loads((root / "blind_handoff_manifest.json").read_text("utf-8"))
    manifest = json.loads((root / "bundle_manifest.json").read_text("utf-8"))
    sources = json.loads((root / "source_material_manifest.json").read_text("utf-8"))
    bindings = json.loads((root / "locator_bindings.json").read_text("utf-8"))

    packets_ok = 0
    for entry in manifest["packets"]:
        packet = json.loads((root / entry["file"]).read_text("utf-8"))
        if canonical_hash(packet) != entry["packet_hash"]:
            raise BlindHandoffError(
                "BLIND_PACKET_HASH_MISMATCH", f"{entry['packet_id']} drifted"
            )
        packets_ok += 1

    for row in sources["sources"]:
        blob = root / row["source_blob_path"]
        if not blob.is_file():
            raise BlindHandoffError(
                "BLIND_HANDOFF_NOT_SELF_CONTAINED",
                f"{row['source_blob_path']} is missing from the copied handoff",
            )
        if _sha256_file(blob) != row["source_blob_hash"]:
            raise BlindHandoffError(
                "BLIND_SOURCE_COPY_MISMATCH", f"{row['source_blob_path']} drifted"
            )
        projection = root / row["projection_path"]
        if not projection.is_file():
            raise BlindHandoffError(
                "BLIND_HANDOFF_NOT_SELF_CONTAINED",
                f"{row['projection_path']} is missing from the copied handoff",
            )
        if canonical_hash(
            json.loads(projection.read_text("utf-8"))
        ) != row["projection_hash"]:
            raise BlindHandoffError(
                "BLIND_PROJECTION_MISMATCH", f"{row['projection_path']} drifted"
            )

    packets_with_sources: set[str] = set()
    for row in bindings["bindings"]:
        blob = root / row["source_blob_path"]
        projection = root / row["projection_path"]
        if not blob.is_file() or not projection.is_file():
            raise BlindHandoffError(
                "BLIND_HANDOFF_NOT_SELF_CONTAINED",
                f"{row['packet_id']} cannot follow {row['declared_ref']}",
            )
        known = {
            unit["evidence_id"]
            for unit in json.loads(projection.read_text("utf-8"))["units"]
        }
        if not set(row["matched_evidence_ids"]) <= known:
            raise BlindHandoffError(
                "BLIND_LOCATOR_BINDING_INVALID",
                f"{row['packet_id']} binds a unit absent from its projection",
            )
        packets_with_sources.add(row["packet_id"])

    return {
        "packets_verified": packets_ok,
        "packets_with_resolved_sources": len(packets_with_sources),
        "sources_verified": len(sources["sources"]),
        "bindings_verified": len(bindings["bindings"]),
        "handoff_manifest_hash": canonical_hash(handoff),
        "self_contained": (
            packets_ok == handoff["packet_count"]
            and len(packets_with_sources) == handoff["packet_count"]
        ),
    }
