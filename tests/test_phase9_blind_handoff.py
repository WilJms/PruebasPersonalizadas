"""Phase 9B.2 handoff tests. Nothing here calls a provider or adjudicates."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

from comprehension_verification import phase9_blind_handoff as bh
from comprehension_verification import phase9_execution as px


BUNDLE = bh.bundle_root()
EXECUTION_DIR = (
    px.BENCHMARK_REPORT_ROOT / "phase9/executions/exec-phase9b1-bfd3cf082617ea8b"
)

pytestmark = pytest.mark.skipif(
    not (BUNDLE / "blind_handoff_manifest.json").is_file(),
    reason="no completed Phase 9B blind handoff in this checkout",
)


@pytest.fixture(scope="module")
def handoff() -> dict[str, Any]:
    return json.loads((BUNDLE / "blind_handoff_manifest.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def bundle_manifest() -> dict[str, Any]:
    return json.loads((BUNDLE / "bundle_manifest.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def sources() -> dict[str, Any]:
    return json.loads((BUNDLE / "source_material_manifest.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def bindings() -> dict[str, Any]:
    return json.loads((BUNDLE / "locator_bindings.json").read_text("utf-8"))


def test_all_thirty_eight_packets_keep_their_hashes(
    bundle_manifest: dict[str, Any], handoff: dict[str, Any]
) -> None:
    assert bundle_manifest["packet_count"] == 38
    assert handoff["packet_count"] == 38
    for entry in bundle_manifest["packets"]:
        packet = json.loads((BUNDLE / entry["file"]).read_text("utf-8"))
        assert bh.canonical_hash(packet) == entry["packet_hash"]
        assert handoff["packet_hashes"][entry["packet_id"]] == entry["packet_hash"]


def test_packets_gained_no_fields(bundle_manifest: dict[str, Any]) -> None:
    """Source material is a separate surface; it is never injected into packets."""

    allowed = set(
        json.loads(
            (px.PHASE9_DEFINITION_ROOT / "adjudication_protocol.json").read_text(
                "utf-8"
            )
        )["blinding"]["allowed_packet_fields"]
    )
    for entry in bundle_manifest["packets"]:
        packet = json.loads((BUNDLE / entry["file"]).read_text("utf-8"))
        assert set(packet) <= allowed


def test_every_declared_source_ref_resolves(
    handoff: dict[str, Any], bindings: dict[str, Any]
) -> None:
    assert handoff["declared_source_refs"] == 54
    assert handoff["declared_source_refs_resolvable"] == 54
    assert len(bindings["bindings"]) == 54
    for row in bindings["bindings"]:
        assert row["resolution_status"].startswith("RESOLVED")
        assert (BUNDLE / row["source_blob_path"]).is_file()
        assert (BUNDLE / row["projection_path"]).is_file()


def test_raw_source_bytes_match_the_declared_packet_hashes(
    sources: dict[str, Any], bundle_manifest: dict[str, Any]
) -> None:
    declared: dict[str, str] = {}
    for entry in bundle_manifest["packets"]:
        packet = json.loads((BUNDLE / entry["file"]).read_text("utf-8"))
        declared.update(packet.get("source_hashes") or {})
    stored = {row["source_blob_hash"] for row in sources["sources"]}
    assert set(declared.values()) <= stored
    for row in sources["sources"]:
        blob = BUNDLE / row["source_blob_path"]
        assert bh._sha256_file(blob) == row["source_blob_hash"]


def test_only_authorized_source_roles_were_copied(sources: dict[str, Any]) -> None:
    assert {row["role"] for row in sources["sources"]} <= {
        "ASSIGNMENT_PROMPT",
        "RUBRIC",
        "SUBMISSION",
    }
    for row in sources["sources"]:
        ref = row["declared_ref"]
        assert ref in bh.PERMITTED_SOURCE_FILENAMES or ref.startswith(
            bh.PERMITTED_SOURCE_PREFIXES
        )


def test_no_oracle_or_authority_material_entered_the_bundle() -> None:
    """Ratifications, audit history and corpus authority stay out by construction."""

    for path in BUNDLE.rglob("*"):
        if not path.is_file():
            continue
        name = str(path.relative_to(BUNDLE))
        for marker in bh.FORBIDDEN_SOURCE_MARKERS:
            assert marker not in name
    for marker in ("final_ratification", "_audit_history", "compiled_properties"):
        assert not list(BUNDLE.rglob(f"*{marker}*"))


def test_forbidden_source_refs_are_rejected() -> None:
    for ref in (
        "final_ratification.json",
        "_audit_history/opus.json",
        "../candidate_matrix.json",
    ):
        with pytest.raises(bh.BlindHandoffError) as exc:
            bh._assert_permitted(ref)
        assert exc.value.code == "BLIND_SOURCE_REF_FORBIDDEN"


def test_projections_are_deterministic(sources: dict[str, Any]) -> None:
    audit = bh.audit_existing_bundle(BUNDLE)
    resolved = bh.resolve_sources(audit)
    for row in sources["sources"]:
        source = resolved[row["source_blob_hash"]]
        first = bh.project_source(source)
        second = bh.project_source(source)
        assert bh.canonical_hash(first) == bh.canonical_hash(second)
        stored = json.loads((BUNDLE / row["projection_path"]).read_text("utf-8"))
        assert bh.canonical_hash(first) == bh.canonical_hash(stored)
        assert bh.canonical_hash(stored) == row["projection_hash"]


def test_projections_carry_only_source_derived_fields(
    sources: dict[str, Any],
) -> None:
    for row in sources["sources"]:
        projection = json.loads((BUNDLE / row["projection_path"]).read_text("utf-8"))
        assert set(projection) == {
            "schema_version",
            "source_content_hash",
            "media_type",
            "parser_id",
            "parser_version",
            "byte_size",
            "unit_count",
            "units",
        }
        for unit in projection["units"]:
            assert set(unit) == {
                "source_order",
                "evidence_id",
                "locator",
                "modality",
                "content_text",
                "normalized_hash",
            }


def test_locator_bindings_name_units_that_exist(bindings: dict[str, Any]) -> None:
    for row in bindings["bindings"]:
        units = json.loads((BUNDLE / row["projection_path"]).read_text("utf-8"))[
            "units"
        ]
        known = {unit["evidence_id"] for unit in units}
        assert set(row["matched_evidence_ids"]) <= known
        assert row["matched_unit_count"] == len(row["matched_evidence_ids"])


def test_no_cross_submission_source_resolution(
    bindings: dict[str, Any], sources: dict[str, Any]
) -> None:
    """A packet's ref may only resolve to the artifact its own hash names."""

    by_blob = {row["source_blob_hash"]: row for row in sources["sources"]}
    manifest = json.loads((BUNDLE / "bundle_manifest.json").read_text("utf-8"))
    declared: dict[str, dict[str, str]] = {}
    for entry in manifest["packets"]:
        packet = json.loads((BUNDLE / entry["file"]).read_text("utf-8"))
        declared[entry["packet_id"]] = packet.get("source_hashes") or {}
    for row in bindings["bindings"]:
        expected = declared[row["packet_id"]][row["declared_ref"]]
        assert row["source_blob_hash"] == expected
        assert by_blob[expected]["declared_ref"] == row["declared_ref"]


def test_handoff_reports_zero_metadata_leaks() -> None:
    audit = json.loads((BUNDLE / "handoff_leakage_audit.json").read_text("utf-8"))
    assert audit["metadata_leak_count"] == 0
    assert audit["result"] == "PASS"
    assert audit["source_content_occurrences"] > 0


def test_leakage_scan_catches_an_injected_metadata_leak(tmp_path: Path) -> None:
    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy)
    (copy / "injected.json").write_text(
        json.dumps({"route_profile": "LUNA_BASELINE_V1"}), encoding="utf-8"
    )
    scan = bh.scan_handoff_for_leakage(copy)
    assert scan["result"] == "BLOCKED"
    # Caught twice over: by the field name and by the route profile value.
    kinds = {item["kind"] for item in scan["metadata_leaks"]}
    assert "METADATA_FIELD_NAME" in kinds
    assert any(item["token"] == "route_profile" for item in scan["metadata_leaks"])
    assert any(item["token"] == "LUNA_BASELINE_V1" for item in scan["metadata_leaks"])


def test_leakage_scan_catches_a_leak_hidden_in_a_field_name_alone(
    tmp_path: Path,
) -> None:
    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy)
    (copy / "injected.json").write_text(
        json.dumps({"reasoning_effort": "unremarkable"}), encoding="utf-8"
    )
    scan = bh.scan_handoff_for_leakage(copy)
    assert scan["result"] == "BLOCKED"
    assert any(
        item["kind"] == "METADATA_FIELD_NAME" and item["token"] == "reasoning_effort"
        for item in scan["metadata_leaks"]
    )


def test_word_boundary_matching_does_not_flag_resolved() -> None:
    """"sol" lives inside "RESOLVED"; only the standalone word is a signal."""

    assert not bh._word_present("sol", "RESOLVED_FILE_SCOPE")
    assert bh._word_present("sol", "la luz del sol")
    assert not bh._word_present("core", "scoreboard")


def test_no_model_identity_string_anywhere_in_the_bundle() -> None:
    for path in BUNDLE.rglob("*.json"):
        text = path.read_text("utf-8").casefold()
        for token in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6"):
            assert token not in text


def test_shipped_verifier_confirms_self_containment_in_an_empty_directory(
    tmp_path: Path,
) -> None:
    """The handoff must verify with no repository present at all."""

    isolated = tmp_path / "handoff"
    shutil.copytree(BUNDLE, isolated)
    result = subprocess.run(
        [sys.executable, "verify_handoff.py"],
        cwd=isolated,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["SELF_CONTAINED_SOURCE_RESOLUTION"] is True
    assert report["packets_verified"] == 38
    assert report["packets_with_resolvable_sources"] == 38
    assert report["declared_refs_resolved"] == 54
    assert report["source_artifacts_verified"] == 14
    assert report["failures"] == []


def test_isolated_verification_fails_when_a_source_is_missing(
    tmp_path: Path,
) -> None:
    isolated = tmp_path / "handoff"
    shutil.copytree(BUNDLE, isolated)
    victim = next((isolated / "sources").iterdir())
    victim.unlink()
    result = subprocess.run(
        [sys.executable, "verify_handoff.py"],
        cwd=isolated,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["SELF_CONTAINED_SOURCE_RESOLUTION"] is False


def test_in_repo_verifier_agrees_with_the_shipped_one() -> None:
    report = bh.verify_self_contained(BUNDLE)
    assert report["self_contained"] is True
    assert report["packets_verified"] == 38
    assert report["packets_with_resolved_sources"] == 38
    assert report["bindings_verified"] == 54


def test_handoff_declares_no_candidate_or_execution_metadata(
    handoff: dict[str, Any]
) -> None:
    assert handoff["contains_candidate_metadata"] is False
    assert handoff["contains_execution_metadata"] is False
    assert handoff["SELF_CONTAINED_FOR_SOURCE_FIRST_ADJUDICATION"] is True
    assert handoff["semantic_status"] == "PENDING_ADJUDICATION"
    assert handoff["adjudication_performed_here"] is False


def test_no_semantic_verdict_appears_anywhere_in_the_bundle() -> None:
    for path in BUNDLE.rglob("*.json"):
        if path.name in {"handoff_leakage_audit.json", "leakage_audit.json"}:
            continue
        payload = json.loads(path.read_text("utf-8"))
        text = json.dumps(payload, ensure_ascii=False)
        for verdict in ("MODEL_FAILURE", "DEFENSIBLE_ALTERNATIVE"):
            assert f'"{verdict}"' not in text or "defensible_alternatives" in text


def test_accounting_amendment_remains_the_effective_authority() -> None:
    if not EXECUTION_DIR.exists():  # pragma: no cover - evidence absent in a fork
        pytest.skip("no recorded Phase 9B.1 execution")
    effective = px.effective_accounting(EXECUTION_DIR)
    assert effective["rule"] == "ACCOUNTING_AMENDMENT_WHEN_PRESENT"
    assert effective["source"] == "accounting_amendment.json"
    assert effective["superseded"] == "execution_manifest.json#accounting"
    assert effective["accounting"]["provider_technical_failures"] == 0
    assert effective["accounting"]["deterministic_validation_failures"] == 4
    assert effective["technical_failure_rate"] == 0.0


def test_historical_execution_manifest_is_not_rewritten() -> None:
    if not EXECUTION_DIR.exists():  # pragma: no cover - evidence absent in a fork
        pytest.skip("no recorded Phase 9B.1 execution")
    manifest = json.loads((EXECUTION_DIR / "execution_manifest.json").read_text("utf-8"))
    # The original, superseded field stays exactly as it was recorded.
    assert manifest["accounting"]["primary_logical_calls_completed"] == 26
    assert "technical_failures" in manifest["accounting"]


def test_deterministic_non_completions_are_not_semantic_packets(
    bundle_manifest: dict[str, Any]
) -> None:
    """The four deterministic rejections stay execution evidence, not packets."""

    if not EXECUTION_DIR.exists():  # pragma: no cover - evidence absent in a fork
        pytest.skip("no recorded Phase 9B.1 execution")
    ledger = json.loads((EXECUTION_DIR / "call_ledger.json").read_text("utf-8"))
    failed = [
        item for item in ledger["attempts"] if item["response_status"] == "FAILED"
    ]
    assert len(failed) == 4
    completed = {
        item["logical_call_id"]
        for item in ledger["attempts"]
        if item["response_status"] == "COMPLETED"
    }
    assert len(completed) == 26
    # 38 packets come from completed runs only; a rejected draft never became one.
    assert bundle_manifest["packet_count"] == 38
