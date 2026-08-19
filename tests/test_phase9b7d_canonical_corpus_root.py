"""Phase 9B.7D — the Phase 9B.7 package reads the canonical tracked corpus.

Phase 9B.7C published green locally and failed CI because its builders and
tests pointed at ``pruebas_personalizadas_corpus``: a protected, untracked
working-copy directory that exists on a developer machine and never in a fresh
checkout.  The benchmark corpus authority is
``semantic_benchmark.DEFAULT_CORPUS_ROOT``.

These regressions pin the wiring, not the product decision.  U3, N3, split
sequencing, contractual-gate semantics and held-out policy are closed and are
asserted here only to prove the path repair moved no semantic material.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from comprehension_verification.p06_n3_protocol import (
    P06_SMOKE_ACTIVITY_IDS,
    N3ProtocolError,
    n3_exposure_population,
    n3_safety_smoke_selector,
)
from comprehension_verification.phase9b7_decision import phase9b7_decision
from comprehension_verification.semantic_benchmark import (
    BenchmarkValidationError,
    DEFAULT_CORPUS_ROOT,
    EXPECTED_CORPUS_PACKAGE_HASH,
    load_corpus_package,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_RELATIVE = "tests/test_phase9b7d_canonical_corpus_root.py"
CANONICAL_RELATIVE = Path("evaluation/corpora/pruebas_personalizadas/v1")
PROTECTED_LOCAL_DIRNAME = "pruebas_personalizadas_corpus"
SPLIT_PARTITION = (
    REPO_ROOT / "reports" / "semantic_benchmark" / "v1_2" / "split_partition.json"
)

#: Files whose corpus dependency must resolve in a fresh checkout.
PHASE9B7_EXECUTABLE_SOURCES = (
    "scripts/build_phase9b7_decision.py",
    "src/comprehension_verification/p06_n3_protocol.py",
    "src/comprehension_verification/p06_noisy_contractual_gate.py",
    "src/comprehension_verification/p06_noisy_gate_feasibility.py",
    "src/comprehension_verification/phase9b7_decision.py",
    "tests/test_phase9b7_decision.py",
    "tests/test_phase9b7_noisy_gate_feasibility.py",
    "tests/test_phase9b7a_contractual_gate.py",
    "tests/test_phase9b7b_n3_protocol.py",
    "tests/test_phase9b7c_split_sequencing.py",
    "tests/test_phase9b7d_canonical_corpus_root.py",
)


def _load_module(path: Path):
    """Import a builder/test module from its path, without packaging it."""

    spec = importlib.util.spec_from_file_location(f"_9b7d_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def population() -> dict:
    return n3_exposure_population(DEFAULT_CORPUS_ROOT, SPLIT_PARTITION)


# --------------------------------------------------------------------------
# 1-3: the canonical authority is the one the package uses, and it ships
# --------------------------------------------------------------------------


def test_phase9b7_corpus_authority_is_default_corpus_root() -> None:
    """The package consumes the existing authority, not a private constant."""

    from comprehension_verification import semantic_benchmark

    for relative in (
        "scripts/build_phase9b7_decision.py",
        "tests/test_phase9b7_decision.py",
        "tests/test_phase9b7_noisy_gate_feasibility.py",
        "tests/test_phase9b7a_contractual_gate.py",
        "tests/test_phase9b7b_n3_protocol.py",
        "tests/test_phase9b7c_split_sequencing.py",
    ):
        module = _load_module(REPO_ROOT / relative)
        assert module.CORPUS_ROOT == semantic_benchmark.DEFAULT_CORPUS_ROOT, relative


def test_default_corpus_root_resolves_under_the_canonical_evaluation_path() -> None:
    assert DEFAULT_CORPUS_ROOT == REPO_ROOT / CANONICAL_RELATIVE
    assert DEFAULT_CORPUS_ROOT.is_dir()
    assert PROTECTED_LOCAL_DIRNAME not in DEFAULT_CORPUS_ROOT.parts


def test_the_canonical_manifest_is_tracked_and_present_in_a_clean_checkout() -> None:
    """`git ls-files` is the clean-checkout oracle: untracked files are absent."""

    manifest = DEFAULT_CORPUS_ROOT / "corpus_final_manifest.json"
    assert manifest.is_file()

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(manifest.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stderr

    ratifications = subprocess.run(
        [
            "git",
            "ls-files",
            f"{CANONICAL_RELATIVE.as_posix()}/*/final_ratification.json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert len(ratifications.stdout.split()) == 12


# --------------------------------------------------------------------------
# 4-6: the canonical authority yields the same N3 material
# --------------------------------------------------------------------------


def test_the_n3_population_from_canonical_authority_is_ten(population) -> None:
    exposures = [item["exposure_id"] for item in population["exposures"]]
    assert population["total_exposure_count"] == 10
    assert len(exposures) == 10
    assert len(set(exposures)) == 10
    assert set(exposures) == set(population["qualification_side_exposure_ids"]) | set(
        population["held_out_exposure_ids"]
    )


def test_the_split_remains_seven_qualification_and_three_held_out(population) -> None:
    assert population["qualification_side_count"] == 7
    assert population["held_out_count"] == 3
    assert population["qualification_side_count"] + population["held_out_count"] == 10
    assert population["held_out_activity_numbers"] == [3, 7, 9, 10, 12]


def test_safety_smoke_remains_the_accepted_qualification_side_exposure(
    population,
) -> None:
    selector = n3_safety_smoke_selector(
        population, smoke_activity_ids=P06_SMOKE_ACTIVITY_IDS
    )
    assert selector["held_out_members"] == 0
    assert not set(selector["exposure_ids"]) & set(population["held_out_exposure_ids"])
    assert [
        exposure_id
        for exposure_id in selector["exposure_ids"]
        if "act_01_luz_y_plantines" in exposure_id
    ] == list(selector["exposure_ids"])


# --------------------------------------------------------------------------
# 7-8: nothing points at, or falls back to, the protected local directory
# --------------------------------------------------------------------------


def test_no_phase9b7_executable_source_references_the_protected_local_corpus() -> None:
    """An absence property: zero references, at any count of source lines."""

    offenders = []
    for relative in PHASE9B7_EXECUTABLE_SOURCES:
        if relative == SELF_RELATIVE:
            # This module is the one file that must spell the forbidden path
            # out, because naming it is how the scan is defined.
            continue
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if PROTECTED_LOCAL_DIRNAME in line:
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == [], offenders


def test_no_fallback_from_canonical_to_the_protected_local_corpus_exists(
    tmp_path, monkeypatch
) -> None:
    """A missing canonical authority must fail closed, never silently degrade.

    The protected local directory is left untouched; a decoy canonical root is
    used so the failure cannot be satisfied by any other corpus on disk.
    """

    decoy = tmp_path / "canonical-absent"
    decoy.mkdir()
    (tmp_path / PROTECTED_LOCAL_DIRNAME).mkdir()

    monkeypatch.chdir(tmp_path)
    with pytest.raises(
        (N3ProtocolError, BenchmarkValidationError, FileNotFoundError, OSError)
    ):
        phase9b7_decision(decoy)


# --------------------------------------------------------------------------
# 9: the protected local directory is irrelevant to every 9B.7 result
# --------------------------------------------------------------------------


def test_hiding_the_local_protected_corpus_does_not_change_any_result(
    tmp_path, monkeypatch
) -> None:
    """Derivation is anchored to the tracked authority, not to the process cwd.

    Running from a directory that has no ``pruebas_personalizadas_corpus`` must
    reproduce the decision exactly. The real protected directory is never
    touched, moved or deleted.
    """

    baseline = phase9b7_decision(DEFAULT_CORPUS_ROOT)

    monkeypatch.chdir(tmp_path)
    assert not (Path.cwd() / PROTECTED_LOCAL_DIRNAME).exists()
    hidden = phase9b7_decision(DEFAULT_CORPUS_ROOT)

    assert hidden["decision_hash"] == baseline["decision_hash"]
    assert hidden["verdict"] == baseline["verdict"]
    assert hidden["uncertain_recommendation"] == baseline["uncertain_recommendation"]
    assert hidden["noisy_decision"] == baseline["noisy_decision"]
    assert hidden == baseline


def test_the_published_artifact_matches_the_canonical_derivation() -> None:
    artifact = json.loads(
        (
            REPO_ROOT
            / "reports"
            / "semantic_benchmark"
            / "phase9b7"
            / "product_decision.json"
        ).read_text(encoding="utf-8")
    )
    assert artifact == phase9b7_decision(DEFAULT_CORPUS_ROOT)


# --------------------------------------------------------------------------
# 10: canonical boundary verification fails closed on real corpus drift
# --------------------------------------------------------------------------


def test_the_canonical_corpus_boundary_is_verified_at_its_frozen_hash() -> None:
    package = load_corpus_package(DEFAULT_CORPUS_ROOT)
    assert package.package_hash == EXPECTED_CORPUS_PACKAGE_HASH


@pytest.mark.parametrize("drift", ["mutated_byte", "removed_file", "added_file"])
def test_canonical_boundary_verification_fails_closed_on_corpus_drift(
    tmp_path, drift
) -> None:
    """Drift is detected on a copy; the tracked corpus is never modified."""

    replica = tmp_path / "v1"
    shutil.copytree(DEFAULT_CORPUS_ROOT, replica)
    assert load_corpus_package(replica).package_hash == EXPECTED_CORPUS_PACKAGE_HASH

    ratification = next(replica.glob("activity_*/final_ratification.json"))
    if drift == "mutated_byte":
        payload = ratification.read_bytes()
        ratification.write_bytes(payload[:-1] + bytes([payload[-1] ^ 0x01]))
    elif drift == "removed_file":
        ratification.unlink()
    else:
        (replica / "unexpected_extra_file.json").write_text("{}", encoding="utf-8")

    with pytest.raises(BenchmarkValidationError):
        load_corpus_package(replica)


def test_the_frozen_hash_constant_is_not_recomputed_from_whatever_is_on_disk(
    tmp_path,
) -> None:
    """An expected-hash mismatch must raise, not adopt the observed value."""

    replica = tmp_path / "v1"
    shutil.copytree(DEFAULT_CORPUS_ROOT, replica)

    with pytest.raises(BenchmarkValidationError):
        load_corpus_package(replica, expected_hash="sha256:" + "0" * 64)
