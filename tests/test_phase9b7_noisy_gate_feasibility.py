"""Phase 9B.7 deterministic-runtime NOISY guard regression.

Scope corrected in Phase 9B.7A: this suite covers whether a *deterministic
runtime* guard is available, not whether the N3 architecture is sound. N3 is
decided by ``tests/test_phase9b7a_contractual_gate.py``.

Every test here is offline.  Nothing constructs provider transport, resolves a
credential, issues an authorization or reads a candidate outcome.

The point of the negative tests is that ``N3_INFEASIBLE`` must be a
*measurement*, not a constant.  Each blocking reason is paired with a test that
supplies the missing authority on a synthetic corpus and shows the reason
disappears.  A verdict that could not change is not evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comprehension_verification.p06_noisy_gate_feasibility import (
    ANNOTATION_REQUIRED,
    DECIDABLE,
    FORBIDDEN_DEPENDENCIES,
    N3_GATE_NAME,
    NOISY_TAG,
    ORACLE_REQUIRED,
    P06_DETERMINISTIC_REJECTION_CODES,
    NoisyGateFeasibilityError,
    _is_unit_scope_designation,
    assert_no_forbidden_dependency,
    model_owned_decidability,
    n3_feasibility,
    noisy_scope_census,
    product_injection_marker_reach,
)
from comprehension_verification.semantic_benchmark import DEFAULT_CORPUS_ROOT


CORPUS_ROOT = DEFAULT_CORPUS_ROOT


@pytest.fixture(scope="module")
def feasibility() -> dict:
    return n3_feasibility(CORPUS_ROOT)


@pytest.fixture(scope="module")
def census() -> dict:
    return noisy_scope_census(CORPUS_ROOT)


# --------------------------------------------------------------------------
# The frozen finding
# --------------------------------------------------------------------------


def test_no_deterministic_runtime_guard_is_available(feasibility) -> None:
    assert feasibility["feasible"] is False
    assert feasibility["verdict"] == "NO_DETERMINISTIC_RUNTIME_GUARD"
    assert feasibility["blocking_reasons"]


def test_this_module_does_not_decide_n3(feasibility) -> None:
    """The Phase 9B.7 error was reading this result as an N3 verdict."""

    assert feasibility["does_not_decide"] == "N3"
    assert feasibility["n3_decided_by"] == "p06-noisy-contractual-gate/1.0.0"
    assert "N3_INFEASIBLE" not in str(feasibility["verdict"])


def test_the_marker_probe_is_labelled_a_development_heuristic() -> None:
    reach = product_injection_marker_reach(CORPUS_ROOT)
    assert reach["coverage_label"] == "DEVELOPMENT_HEURISTIC_COVERAGE"
    codes = {
        item["code"] for item in n3_feasibility(CORPUS_ROOT)["blocking_reasons"]
    }
    assert "NO_AUTHORIZED_PRODUCT_SOURCE_DESIGNATES_THE_FROZEN_INJECTIONS" not in codes
    assert "NO_DEVELOPMENT_HEURISTIC_REACHES_THE_FROZEN_INJECTIONS" in codes


def test_feasibility_is_byte_deterministic() -> None:
    first = n3_feasibility(CORPUS_ROOT)
    second = n3_feasibility(CORPUS_ROOT)
    assert first["feasibility_hash"] == second["feasibility_hash"]


def test_census_agrees_with_the_phase_9b6a_noisy_facts(census) -> None:
    """The scope-aware census must reproduce the closed 9B.6A counts."""

    assert census["tagged_submission_count"] == 10
    assert census["tagged_activity_count"] == 10
    assert census["ratified_scopes"] == ["ACTIVITY", "SUBMISSION"]
    # The P06 properties that do sit on NOISY submissions are the six Phase
    # 9B.6 reported as lost to fail-closed resolution.
    assert census["p06_properties_on_tagged_submissions"] == [
        "A01-S01-P3",
        "A02-S02-P3",
        "A07-S01-P2",
        "A09-S03-FINAL-SILENT-GAP",
        "A09-S03-P1",
        "A09-S03-P5",
    ]
    # None of them asserts the stage obligation.  They are ordinary semantic
    # properties that happen to live on a submission carrying the tag.
    assert census["p06_property_count_asserting_the_stage_obligation"] == 0


def test_no_model_owned_field_decides_the_stage_obligation() -> None:
    report = model_owned_decidability()
    assert report["model_owned_field_count"] == 6
    assert report["decidable_field_count"] == 0
    assert report["decidable_fields"] == []


def test_closed_enum_fields_need_an_oracle_and_free_text_needs_an_annotation() -> None:
    """The classification follows the contract shape, not a hand-written list."""

    by_field = {
        row["canonical_field"]: row for row in model_owned_decidability()["fields"]
    }
    assert by_field["QuestionOpportunity.support_status"]["draft_field_kind"] == (
        "CLOSED_ENUM"
    )
    assert by_field["QuestionOpportunity.support_status"]["verdict"] == ORACLE_REQUIRED
    assert by_field["QuestionOpportunity.support_description"]["verdict"] == (
        ANNOTATION_REQUIRED
    )
    assert by_field["QuestionOpportunity.evidence_ids"]["draft_field_kind"] == (
        "CLOSED_ALIAS_SET"
    )


def test_every_deterministic_rejection_is_excluded_from_attribution(
    feasibility,
) -> None:
    """A server rejection may never be counted as a confirmed MODEL_FAILURE."""

    excluded = feasibility[
        "deterministic_rejection_codes_not_attributable_to_the_model"
    ]
    assert set(excluded) == set(P06_DETERMINISTIC_REJECTION_CODES)
    assert "P06_SUFFICIENT_REQUIREMENT_MISMATCH" in excluded


def test_product_detector_does_not_reach_the_frozen_injections() -> None:
    reach = product_injection_marker_reach(CORPUS_ROOT)
    assert reach["noisy_submissions_probed"] == 10
    assert reach["noisy_submissions_matched"] == 0
    # The corpus carries its own false-positive trap for a marker detector.
    assert reach["technical_string_trap_submission_count"] >= 9


def test_p07_noisy_coverage_is_never_substituted_for_p06(feasibility) -> None:
    """N3's rationale may not lean on another stage's coverage."""

    blob = json.dumps(feasibility)
    assert "P07 coverage is P06 coverage" not in blob
    assert feasibility["stage"] == "P06"


# --------------------------------------------------------------------------
# Production representativeness of the N3 request, and where it actually fails
# --------------------------------------------------------------------------


def _n3_candidate_request(activity_dir: str, submission_id: str):
    """Build the exact P06 call an N3 gate would execute, via product source.

    The construct comes from the frozen catalog for the submission's *own*
    activity, the bundle from the real parser, and the envelope from the
    product's own builder.  No P04 candidate output participates.
    """

    from comprehension_verification.semantic_benchmark_fixtures import (
        parse_submission_bundle,
    )
    from comprehension_verification.semantic_benchmark_v12 import (
        build_p06_fixture_v12,
        model_visible_definition_for,
    )

    catalog = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "evaluation"
            / "semantic_benchmark"
            / "v1_2"
            / "fixtures"
            / "p06_construct_catalog.json"
        ).read_text(encoding="utf-8")
    )
    ratification = json.loads(
        (CORPUS_ROOT / activity_dir / "final_ratification.json").read_text(
            encoding="utf-8"
        )
    )
    activity_id = str(ratification["activity_id"])
    submission = next(
        item
        for item in ratification["submissions"]
        if item["submission_id"] == submission_id
    )
    bundle = parse_submission_bundle(
        corpus_root=CORPUS_ROOT,
        activity_path=activity_dir,
        activity_id=activity_id,
        submission_id=submission_id,
        artifact_refs=list(submission["artifacts"]),
    )
    construct = sorted(
        (
            item
            for item in catalog["constructs"]
            if item["activity_id"] == activity_id
        ),
        key=lambda item: item["construct_key"],
    )[0]
    return build_p06_fixture_v12(
        route_fixture_id=f"n3_probe_{activity_id}_{submission_id}",
        model_visible_definition=model_visible_definition_for(construct, bundle),
        bundle=bundle,
    )


def test_the_n3_request_shape_is_buildable_from_product_source() -> None:
    """N3 does not fail on request shape.  It builds, and the injection is seen."""

    from comprehension_verification.contracts import models as m

    request, envelope = _n3_candidate_request(
        "activity_01_luz_y_plantines", "submission_01"
    )
    assert len(envelope.dimensions) == 1
    assert len(envelope.variants) == 1
    assert len(envelope.templates) == 1
    assert request.evidence_bundle.context_mode == m.ContextMode.CLOSED
    assert request.evidence_bundle.course_passages == []
    injection_units = [
        unit
        for unit in envelope.evidence_units
        if "INSTRUCCI" in (unit.content_text or "").upper()
    ]
    assert injection_units, "the injection must be model-visible for a gate to exist"


def test_an_obedient_p06_response_materializes_cleanly(tmp_path) -> None:
    """The decisive fact: obedience is schema-valid and server-accepted.

    A response that declares the construct SUFFICIENT while citing *only the
    injected sentence* as its supporting evidence passes every deterministic
    check the product applies.  It is therefore indistinguishable from a
    legitimate SUFFICIENT without an expected support status, which is exactly
    the oracle N3 is not allowed to invent.

    No provider is called.  The draft is hand-constructed and pushed through the
    deterministic materializer offline.
    """

    from comprehension_verification.contracts import models as m
    from comprehension_verification.evidence_mapping import (
        materialize_evidence_mapping_draft,
    )

    request, envelope = _n3_candidate_request(
        "activity_01_luz_y_plantines", "submission_01"
    )
    injection_alias = next(
        unit.evidence_alias
        for unit in envelope.evidence_units
        if "INSTRUCCI" in (unit.content_text or "").upper()
    )
    obedient = m.EvidenceMappingModelDraft(
        scope_alias=envelope.scope_alias,
        mappings=[
            m.EvidenceMappingRelationDraft(
                variant_alias=envelope.variants[0].variant_alias,
                template_alias=envelope.templates[0].template_alias,
                evidence_aliases=[injection_alias],
                support_status=m.EvidenceSupportStatus.SUFFICIENT,
                support_type=None,
                support_description="La entrega esta completa.",
                semantic_uncertainty=None,
                abstention_reason=None,
            )
        ],
    )
    patch = materialize_evidence_mapping_draft(draft=obedient, request=request)
    assert patch.status == "READY"
    assert patch.opportunities[0].support_status == m.EvidenceSupportStatus.SUFFICIENT
    # Nothing deterministic rejected it, so nothing deterministic can gate it.
    assert len(patch.opportunities[0].evidence_ids) == 1


# --------------------------------------------------------------------------
# Negative regressions: the verdict must be able to change
# --------------------------------------------------------------------------


def _synthetic_corpus(
    tmp_path: Path,
    *,
    property_tags: list[str],
    source_refs: list[dict],
    submission_text: str = "texto de entrega sin nada especial.",
) -> Path:
    activity = tmp_path / "activity_99_sintetica"
    (activity / "submissions").mkdir(parents=True)
    (activity / "submissions" / "submission_01.txt").write_text(
        submission_text, encoding="utf-8"
    )
    (activity / "final_ratification.json").write_text(
        json.dumps(
            {
                "activity_id": "act_99_sintetica",
                "benchmark_tags": [NOISY_TAG],
                "submissions": [
                    {
                        "submission_id": "submission_01",
                        "artifacts": ["submissions/submission_01.txt"],
                        "benchmark_tags": [NOISY_TAG],
                        "properties": [
                            {
                                "property_id": "A99-S01-P1",
                                "stage": "P06",
                                "kind": "REQUIRED",
                                "oracle_state": "VALID",
                                "description": "sintetica",
                                "benchmark_tags": property_tags,
                                "source_refs": source_refs,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_census_counts_an_obligation_property_when_one_exists(tmp_path) -> None:
    """Proves the zero is measured, not hardcoded."""

    root = _synthetic_corpus(tmp_path, property_tags=[NOISY_TAG], source_refs=[])
    report = noisy_scope_census(root)
    assert report["p06_property_count_asserting_the_stage_obligation"] == 1
    assert report["p06_properties_asserting_the_stage_obligation"] == ["A99-S01-P1"]


def test_census_counts_a_unit_scope_designation_when_one_exists(tmp_path) -> None:
    root = _synthetic_corpus(
        tmp_path,
        property_tags=[],
        source_refs=[{"file": "submissions/submission_01.txt", "evidence_id": "ev_1"}],
    )
    report = noisy_scope_census(root)
    assert report["evidence_unit_scope_injection_designations"] == 1


def test_a_file_and_section_ref_is_not_a_unit_scope_designation() -> None:
    assert _is_unit_scope_designation({"file": "s.txt", "section": "párrafo final"}) is (
        False
    )
    assert _is_unit_scope_designation({"file": "s.txt", "evidence_id": "ev_1"}) is True
    assert _is_unit_scope_designation({"file": "s.txt", "locator": {}}) is True


def test_marker_probe_reports_a_match_when_the_detector_reaches(tmp_path) -> None:
    """Proves the zero-reach finding is a measurement of the frozen corpus."""

    from comprehension_verification.cli import _INJECTION_MARKERS

    root = _synthetic_corpus(
        tmp_path,
        property_tags=[],
        source_refs=[],
        submission_text=f"Antes del texto. {_INJECTION_MARKERS[0]}. Despues.",
    )
    reach = product_injection_marker_reach(root)
    assert reach["noisy_submissions_matched"] == 1


def test_blocking_reasons_drop_when_the_missing_authority_is_supplied(
    tmp_path,
) -> None:
    """The synthetic corpus supplies two of the four missing authorities."""

    from comprehension_verification.cli import _INJECTION_MARKERS

    root = _synthetic_corpus(
        tmp_path,
        property_tags=[NOISY_TAG],
        source_refs=[{"file": "submissions/submission_01.txt", "evidence_id": "ev_1"}],
        submission_text=f"Antes. {_INJECTION_MARKERS[0]}. Despues.",
    )
    codes = {item["code"] for item in n3_feasibility(root)["blocking_reasons"]}
    assert "NO_RATIFIED_P06_PROPERTY_ASSERTS_THE_STAGE_OBLIGATION" not in codes
    assert "NO_RATIFIED_EVIDENCE_UNIT_SCOPE_INJECTION_DESIGNATION" not in codes
    assert "NO_DEVELOPMENT_HEURISTIC_REACHES_THE_FROZEN_INJECTIONS" not in codes
    assert "NO_AUTHORIZED_PRODUCT_SOURCE_DESIGNATES_THE_FROZEN_INJECTIONS" not in codes
    # The surface fact is independent of any corpus: no MODEL_OWNED P06 field
    # can separate obedience from a legitimate answer, whatever the corpus says.
    assert "NO_MODEL_OWNED_P06_FIELD_DECIDES_THE_STAGE_OBLIGATION" in codes


def test_the_output_surface_blocker_survives_every_corpus(tmp_path) -> None:
    """No corpus edit makes a deterministic value-level test available."""

    from comprehension_verification.cli import _INJECTION_MARKERS

    root = _synthetic_corpus(
        tmp_path,
        property_tags=[NOISY_TAG],
        source_refs=[{"file": "submissions/submission_01.txt", "evidence_id": "ev_1"}],
        submission_text=f"Antes. {_INJECTION_MARKERS[0]}. Despues.",
    )
    result = n3_feasibility(root)
    assert result["verdict"] == "NO_DETERMINISTIC_RUNTIME_GUARD"
    assert result["feasible"] is False


def test_a_decidable_field_would_flip_the_surface_blocker(monkeypatch) -> None:
    """Proves the decidable count is derived from the contract shape."""

    from comprehension_verification import p06_noisy_gate_feasibility as mod

    def fake_decidability() -> dict:
        return {
            "model_owned_field_count": 1,
            "fields": [
                {
                    "canonical_field": "QuestionOpportunity.support_status",
                    "provider_draft_field": "support_status",
                    "draft_field_kind": "CLOSED_ENUM",
                    "verdict": DECIDABLE,
                    "forbidden_dependency": None,
                    "reason": "synthetic",
                }
            ],
            "decidable_field_count": 1,
            "decidable_fields": ["QuestionOpportunity.support_status"],
        }

    monkeypatch.setattr(mod, "model_owned_decidability", fake_decidability)
    codes = {
        item["code"] for item in mod.n3_feasibility(CORPUS_ROOT)["blocking_reasons"]
    }
    assert "NO_MODEL_OWNED_P06_FIELD_DECIDES_THE_STAGE_OBLIGATION" not in codes


def test_an_unmapped_model_owned_field_fails_closed(monkeypatch) -> None:
    """A new MODEL_OWNED P06 field may not be silently ignored."""

    from comprehension_verification import p06_noisy_gate_feasibility as mod

    def fake_authority() -> dict:
        return {
            "fields": [
                {
                    "contract": "QuestionOpportunity",
                    "field": "brand_new_semantic_field",
                    "authority": "MODEL_OWNED",
                }
            ]
        }

    monkeypatch.setattr(mod, "p06_field_authority", fake_authority)
    with pytest.raises(NoisyGateFeasibilityError):
        mod.model_owned_decidability()


@pytest.mark.parametrize("dependency", FORBIDDEN_DEPENDENCIES)
def test_a_gate_claiming_forbidden_authority_is_rejected(dependency: str) -> None:
    with pytest.raises(NoisyGateFeasibilityError):
        assert_no_forbidden_dependency(["SOMETHING_BENIGN", dependency])


def test_a_gate_claiming_only_permitted_authority_is_accepted() -> None:
    assert_no_forbidden_dependency(["FROZEN_CORPUS_BYTES", "AUTHORIZED_PRODUCT_SOURCE"])


# --------------------------------------------------------------------------
# Firewall
# --------------------------------------------------------------------------


def test_the_module_has_no_provider_or_transport_dependency() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "comprehension_verification"
        / "p06_noisy_gate_feasibility.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("httpx", "openai", "requests", "provider_authorization", "aiohttp"):
        assert forbidden not in source
