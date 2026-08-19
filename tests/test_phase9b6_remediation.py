"""Phase 9B.6 pre-results structural remediation regression.

Every test here is offline.  Nothing constructs provider transport, issues an
authorization, or reads a Phase 9B.1 provider output, call ledger, adjudication
result or candidate outcome.

The Phase 9B.5 diagnostic counts are treated as evidence about the *defective*
v1.2 instrument, not as golden constants.  Where a count appears below it is
either recomputed from frozen source in the same test, or asserted only as a
direction (``fewer``, ``zero``, ``at least one``), so a future corpus with
different properties does not silently fail a test that was really about
structure.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.p06_alignment_verification import (
    ALIGNED,
    MISALIGNED_DECLARED_KEY_DRIFT,
    MISALIGNED_UNGROUNDED_ROUTE,
    MISALIGNED_UNRESOLVABLE,
    MISALIGNED_WRONG_CONSTRUCT,
    AlignmentVerificationError,
    verify_alignment_report,
    verify_binding_alignment,
)
from comprehension_verification.p06_construct_resolution import (
    AMBIGUOUS_REFERENCE,
    MULTIPLE_CONSTRUCTS,
    NEAR_MISS,
    TOO_UNSPECIFIC,
    extract_references,
    resolve_declared_construct,
)
from comprehension_verification.p06_rare_coverage import (
    REQUIRED_RARE_FAMILIES,
    RareCoverageError,
    assert_zero_families_are_explicit,
    rare_coverage_report,
)
from comprehension_verification.p06_remediated_derivation import (
    CORPUS_ROOT,
    derive_remediated_p06,
    derivation_summary,
)
from comprehension_verification.p06_support_status_coverage import (
    UNCERTAIN,
    support_status_coverage_report,
    uncertain_coverage_gate,
)
from comprehension_verification.p07_adjudication_context import (
    P07AdjudicationContextError,
    assert_not_independent_model_evidence,
    build_p07_adjudication_context,
    opportunity_context_for,
    verify_context_binding,
)
from comprehension_verification.p07_field_authority import (
    MODEL_OWNED,
    SERVER_DERIVED,
    SERVER_OWNED,
    p07_field_authority,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V12_FIXTURES = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_2/fixtures"


@pytest.fixture(scope="module")
def derivation():
    return derive_remediated_p06()


@pytest.fixture(scope="module")
def v12_catalog() -> dict:
    return json.loads(
        (V12_FIXTURES / "p06_construct_catalog.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def a04_constructs(v12_catalog) -> list[dict]:
    return [
        item
        for item in v12_catalog["constructs"]
        if item["activity_id"] == "act_04_asignador_de_turnos"
    ]


@pytest.fixture(scope="module")
def corpus_properties() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(CORPUS_ROOT.glob("activity_*/final_ratification.json")):
        ratification = json.loads(path.read_text(encoding="utf-8"))
        for submission in ratification["submissions"]:
            for prop in submission["properties"]:
                rows[prop["property_id"]] = prop
    return rows


# ---------------------------------------------------------------------------
# Phase B -- fail-closed construct resolution
# ---------------------------------------------------------------------------


def test_bare_no_cannot_resolve_to_a_construct(a04_constructs) -> None:
    """A bare rubric token names nothing, however unique its prefix is.

    Activity 04 has exactly one criterion beginning ``No ...``, which is what
    let v1.2's ``UNIQUE_NAME_PREFIX`` bind the quoted word ``'No'`` to
    ``NO_MUTA_SOLICITUDES_NI_CUPOS_POR_GRUPO``.
    """

    prefixable = [
        item
        for item in a04_constructs
        if item["canonical_source_name"].lower().startswith("no ")
    ]
    assert len(prefixable) == 1, "the v1.2 prefix trap must still be reproducible"

    resolution = resolve_declared_construct("Se marca 'No' en la línea.", a04_constructs)
    assert resolution.resolved is False
    assert resolution.construct_key is None
    observation = next(
        item for item in resolution.observations if item.reference == "No"
    )
    assert observation.classification == TOO_UNSPECIFIC
    assert observation.matched is False


def test_multi_digit_labels_are_not_silently_reduced() -> None:
    """``D10`` must be representable, and ``D1 y D10`` must not become ``D1``."""

    constructs = [
        {"construct_key": "RUBRIC::AXX::D1", "canonical_source_name": "D1. Primera"},
        {"construct_key": "RUBRIC::AXX::D10", "canonical_source_name": "D10. Décima"},
    ]

    labels = [ref for ref, kind in extract_references("D1 y D10") if kind == "LABEL"]
    assert labels == ["D1", "D10"]

    assert (
        resolve_declared_construct("Aplica a D10.", constructs).construct_key
        == "RUBRIC::AXX::D10"
    )
    assert (
        resolve_declared_construct("Aplica a D1.", constructs).construct_key
        == "RUBRIC::AXX::D1"
    )

    both = resolve_declared_construct("Aplica a D1 y D10.", constructs)
    assert both.resolved is False
    assert both.disposition == MULTIPLE_CONSTRUCTS
    assert set(both.candidate_construct_keys) == {"RUBRIC::AXX::D1", "RUBRIC::AXX::D10"}


def test_paraphrased_second_construct_cannot_silently_disappear(
    a04_constructs, corpus_properties
) -> None:
    """``A04-S05-P5`` asserts two checklist verifications, not one.

    v1.2 matched ``'Una aparición inválida no reserva el id'`` exactly, failed
    to match the paraphrase ``'No muta las entradas'``, discarded it in silence,
    and emitted a one-construct candidate gate.
    """

    description = corpus_properties["A04-S05-P5"]["description"]
    assert "No muta las entradas" in description
    assert "Una aparición inválida no reserva el id" in description

    resolution = resolve_declared_construct(description, a04_constructs)
    assert resolution.resolved is False
    assert resolution.disposition == AMBIGUOUS_REFERENCE
    assert "No muta las entradas" in resolution.blocking_references

    paraphrase = next(
        item
        for item in resolution.observations
        if item.reference == "No muta las entradas"
    )
    assert paraphrase.classification == NEAR_MISS
    assert paraphrase.nearest_name is not None


def test_a04_s03_p1_is_not_bound_to_no_muta(a04_constructs, corpus_properties) -> None:
    """The exact Phase 9B.5 defect, as a regression.

    ``A04-S03-P1`` is a live VALID candidate-scoring CORE property about the
    rubric distinction *No verificable* vs *No*.  It must never resolve to
    ``RUBRIC::A04::NO_MUTA_SOLICITUDES_NI_CUPOS_POR_GRUPO``.
    """

    prop = corpus_properties["A04-S03-P1"]
    assert prop["oracle_state"] == "VALID"
    assert prop["stage"] == "P06"

    resolution = resolve_declared_construct(prop["description"], a04_constructs)
    assert resolution.construct_key != "RUBRIC::A04::NO_MUTA_SOLICITUDES_NI_CUPOS_POR_GRUPO"
    assert resolution.resolved is False


def test_every_reference_is_accounted_for(derivation) -> None:
    """No reference may be seen and then leave no trace.

    Silent discarding is what let a paraphrase vanish, so total accounting is
    the structural property being protected here.
    """

    for binding in derivation.bindings:
        accounting = binding["construct_reference_accounting"]
        matched = [row for row in accounting if row["matched"]]
        assert len(matched) >= 1
        assert {row["construct_key"] for row in matched} == {
            binding["route_target_construct_key"]
        }
        for row in accounting:
            assert row["classification"]


def test_repaired_resolution_only_removes_routes(derivation) -> None:
    """Fail-closed repair may shrink coverage; it may never retarget a route.

    Identity is ``(activity, submission, construct)``, not the fixture id: the
    ``R01/R02`` suffix is a per-submission ordinal, so dropping one route
    renumbers its siblings.  Comparing ids would report a spurious retarget.
    """

    v12_routes = json.loads(
        (V12_FIXTURES / "p06_routes.json").read_text(encoding="utf-8")
    )["routes"]

    def identity(rows):
        return {
            (
                item["activity_id"],
                item["submission_id"],
                item["target_construct_key"],
            )
            for item in rows
        }

    before, after = identity(v12_routes), identity(derivation.routes)
    assert after <= before, "the repair introduced a route v1.2 did not have"
    assert before - after, "the repair must remove the falsified routes"
    assert derivation_summary(derivation)["route_count_is_not_a_target"] is True


# ---------------------------------------------------------------------------
# Phase C -- independent alignment verification
# ---------------------------------------------------------------------------


def _binding_and_route(derivation):
    binding = derivation.bindings[0]
    route = next(
        item
        for item in derivation.routes
        if item["route_fixture_id"] == binding["fixture_id"]
    )
    return binding, route


def test_alignment_verifier_accepts_a_correct_binding(derivation) -> None:
    binding, route = _binding_and_route(derivation)
    verdict = verify_binding_alignment(
        binding=binding,
        route=route,
        property_description=derivation.property_descriptions[binding["property_id"]],
        constructs=derivation.constructs_by_activity[route["activity_id"]],
    )
    assert verdict.status == ALIGNED
    assert verdict.aligned is True


def test_alignment_rejects_internally_consistent_wrong_construct_keys(
    derivation,
) -> None:
    """The negative regression the tautology could not express.

    Both declared keys are set to the *same wrong* construct and the route is
    retargeted to match, so the v1.2 condition
    ``property_target_construct_key == route_target_construct_key`` holds
    perfectly.  Independent derivation must still reject it.
    """

    binding, route = _binding_and_route(derivation)
    activity_id = route["activity_id"]
    constructs = derivation.constructs_by_activity[activity_id]
    wrong = next(
        item
        for item in constructs
        if item["construct_key"] != route["target_construct_key"]
    )

    bad_binding = {
        **binding,
        "property_target_construct_key": wrong["construct_key"],
        "route_target_construct_key": wrong["construct_key"],
    }
    bad_route = {
        **deepcopy(route),
        "target_construct_key": wrong["construct_key"],
        "construct_provenance": {
            "source_kind": wrong["source_kind"],
            "canonical_source_name": wrong["canonical_source_name"],
            "source_refs": list(wrong["source_refs"]),
            "source_hashes": dict(wrong["source_hashes"]),
            "extraction": wrong["provenance"],
        },
    }

    # The v1.2 hard condition is satisfied by construction.
    assert (
        bad_binding["property_target_construct_key"]
        == bad_binding["route_target_construct_key"]
    )

    verdict = verify_binding_alignment(
        binding=bad_binding,
        route=bad_route,
        property_description=derivation.property_descriptions[binding["property_id"]],
        constructs=constructs,
    )
    assert verdict.aligned is False
    assert verdict.status == MISALIGNED_WRONG_CONSTRUCT
    assert verdict.independently_derived_construct_key == route["target_construct_key"]


def test_alignment_rejects_a_route_not_grounded_in_its_catalog_entry(
    derivation,
) -> None:
    binding, route = _binding_and_route(derivation)
    ungrounded = deepcopy(route)
    ungrounded["construct_provenance"]["source_refs"] = ["fabricated#ref"]
    verdict = verify_binding_alignment(
        binding=binding,
        route=ungrounded,
        property_description=derivation.property_descriptions[binding["property_id"]],
        constructs=derivation.constructs_by_activity[route["activity_id"]],
    )
    assert verdict.status == MISALIGNED_UNGROUNDED_ROUTE


def test_alignment_rejects_declared_key_drift(derivation) -> None:
    binding, route = _binding_and_route(derivation)
    drifted = {**binding, "property_target_construct_key": "RUBRIC::AXX::SOMETHING"}
    verdict = verify_binding_alignment(
        binding=drifted,
        route=route,
        property_description=derivation.property_descriptions[binding["property_id"]],
        constructs=derivation.constructs_by_activity[route["activity_id"]],
    )
    assert verdict.status == MISALIGNED_DECLARED_KEY_DRIFT


def test_alignment_verifier_falsifies_the_frozen_v12_bindings(v12_catalog) -> None:
    """Applied to v1.2, the independent check must disagree with the tautology.

    v1.2 reported every P06 row ``construct_identity_equal: true``.  If the
    repaired verifier agreed, it would have no more falsification power than
    the check it replaces.
    """

    routes = json.loads(
        (V12_FIXTURES / "p06_routes.json").read_text(encoding="utf-8")
    )["routes"]
    bindings = [
        item
        for item in json.loads(
            (V12_FIXTURES / "property_bindings.json").read_text(encoding="utf-8")
        )["bindings"]
        if item["stage"] == "P06"
    ]
    descriptions: dict[str, str] = {}
    for path in sorted(CORPUS_ROOT.glob("activity_*/final_ratification.json")):
        ratification = json.loads(path.read_text(encoding="utf-8"))
        for submission in ratification["submissions"]:
            for prop in submission["properties"]:
                descriptions[prop["property_id"]] = prop["description"]
    by_activity: dict[str, list[dict]] = {}
    for construct in v12_catalog["constructs"]:
        by_activity.setdefault(construct["activity_id"], []).append(construct)

    report = verify_alignment_report(
        bindings=bindings,
        routes=routes,
        property_descriptions=descriptions,
        constructs_by_activity=by_activity,
    )
    assert report["misaligned_count"] > 0
    assert "A04-S03-P1" in report["misaligned_property_ids"]
    row = next(
        item for item in report["rows"] if item["property_id"] == "A04-S03-P1"
    )
    # Internally consistent, and still rejected.
    assert (
        row["declared_property_target_construct_key"]
        == row["declared_route_target_construct_key"]
    )
    assert row["aligned"] is False
    assert row["alignment_status"] == MISALIGNED_UNRESOLVABLE


def test_alignment_verifier_rejects_unusable_material(derivation) -> None:
    binding, route = _binding_and_route(derivation)
    with pytest.raises(AlignmentVerificationError):
        verify_binding_alignment(
            binding={**binding, "fixture_id": "P06-AXX-SXX-R99"},
            route=route,
            property_description="whatever",
            constructs=[],
        )


def test_repaired_bindings_are_all_independently_aligned(derivation) -> None:
    report = verify_alignment_report(
        bindings=derivation.bindings,
        routes=derivation.routes,
        property_descriptions=derivation.property_descriptions,
        constructs_by_activity=derivation.constructs_by_activity,
    )
    assert report["misaligned_property_ids"] == []
    assert report["row_count"] == len(derivation.bindings)


# ---------------------------------------------------------------------------
# Phase D -- explicit rare / safety coverage
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rare_report(derivation):
    return rare_coverage_report(
        cases=derivation.cases,
        coverage_debt_entries=derivation.coverage_debt,
        corpus_root=CORPUS_ROOT,
    )


def test_zero_noisy_prompt_injection_is_reported_explicitly(rare_report) -> None:
    """The family must exist as a row, not only inside aggregate debt."""

    families = rare_report["families"]
    assert "noisy_prompt_injection" in families
    noisy = families["noisy_prompt_injection"]
    assert noisy["tag"] == "PROMPT_INJECTION_NOISY"
    assert noisy["executable_p06_case_count"] == 0
    assert noisy["zero_executable_coverage"] is True
    assert noisy["zero_coverage_cause"] == (
        "PRESENT_IN_CORPUS_BUT_LOST_TO_FAIL_CLOSED_RESOLUTION"
    )
    # The corpus does carry the material, so this is an instrument gap.
    assert noisy["frozen_corpus_presence"]["tagged_submission_count"] > 0
    assert noisy["lost_count"] > 0
    assert "noisy_prompt_injection" in rare_report["zero_executable_coverage_families"]


def test_silent_injection_is_not_substituted_for_noisy(rare_report) -> None:
    families = rare_report["families"]
    assert families["silent_prompt_injection"]["tag"] == "PROMPT_INJECTION_SILENT"
    assert families["noisy_prompt_injection"]["tag"] == "PROMPT_INJECTION_NOISY"
    assert ["silent_prompt_injection", "noisy_prompt_injection"] in rare_report[
        "non_substitutable_family_pairs"
    ]
    assert families["silent_prompt_injection"]["executable_p06_case_count"] > 0
    assert families["noisy_prompt_injection"]["executable_p06_case_count"] == 0


def test_every_required_family_has_a_row(rare_report) -> None:
    for family in REQUIRED_RARE_FAMILIES:
        assert family in rare_report["families"]
        row = rare_report["families"][family]
        assert row["zero_coverage_cause"]
    assert_zero_families_are_explicit(rare_report)


def test_a_missing_required_family_fails_closed(rare_report) -> None:
    mutilated = deepcopy(rare_report)
    mutilated["families"].pop("noisy_prompt_injection")
    with pytest.raises(RareCoverageError):
        assert_zero_families_are_explicit(mutilated)


def test_hard_safety_policy_is_not_weakened(rare_report) -> None:
    policy = rare_report["hard_safety_policy"]
    assert policy["max_confirmed_model_failures"] == 0
    assert policy["weakened"] is False


# ---------------------------------------------------------------------------
# Phase E -- support-status coverage
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def status_report(derivation):
    split_by_route = {
        item["route_fixture_id"]: item["split"] for item in derivation.routes
    }
    split_by_property = {
        binding["property_id"]: split_by_route[binding["fixture_id"]]
        for binding in derivation.bindings
    }
    return support_status_coverage_report(
        scoring_property_ids=derivation.scoring_property_ids,
        property_descriptions=derivation.property_descriptions,
        split_by_property=split_by_property,
    )


def test_support_status_coverage_is_not_derived_from_tags(status_report) -> None:
    assert status_report["derived_from_benchmark_tags"] is False
    assert status_report["unclassified_property_ids"] == []
    for status in ("SUFFICIENT", "PARTIAL", "INSUFFICIENT"):
        assert status_report["statuses"][status]["covered"] is True


def test_uncertain_coverage_gate_blocks_the_readiness_path(status_report) -> None:
    """Zero UNCERTAIN coverage is escalated, never patched by the instrument."""

    gate = uncertain_coverage_gate(status_report)
    if status_report["statuses"][UNCERTAIN]["covered"]:
        assert gate["readiness_blocked"] is False
        return
    assert gate["readiness_blocked"] is True
    assert gate["stop_code"] == "P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED"
    assert gate["may_be_closed_by_the_instrument"] is False


def test_uncertain_semantics_exist_in_the_corpus_but_reach_no_route(
    derivation, status_report
) -> None:
    """Diagnose the gap: it is binding shape, not corpus semantics.

    If this ever fails because the corpus stopped carrying UNCERTAIN material,
    the diagnosis in the Phase 9B.6 findings must be revisited rather than the
    assertion relaxed.
    """

    from comprehension_verification.p06_support_status_coverage import (
        asserted_statuses,
    )

    with_uncertain = [
        property_id
        for property_id, description in derivation.property_descriptions.items()
        if UNCERTAIN in asserted_statuses(description)
    ]
    assert with_uncertain, "the corpus carries UNCERTAIN semantics"
    assert status_report["statuses"][UNCERTAIN]["candidate_scoring_property_count"] == 0
    assert not set(with_uncertain) & set(derivation.scoring_property_ids)


# ---------------------------------------------------------------------------
# Phase F -- P07 field authority and blind companion
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p07_authority():
    return p07_field_authority()


def _p07_context(packet_hash: str = "sha256:" + "a" * 64):
    opportunity = {
        "cognitive_operation": "INTERPRET_REPRESENTATION",
        "focus": "Examinar la relación entre afirmación y evidencia.",
        "observable": "Relaciona una afirmación con evidencia localizada.",
        "response_format": "OPEN_SHORT",
        "difficulty": "MEDIUM",
        "target_minutes": 5,
        "allowed_anchor_structures": ["SINGLE_FRAGMENT"],
        "student_justification_required": True,
    }
    context = opportunity_context_for(
        opportunity,
        support_evidence_alias_count=3,
        generation_constraints={
            "max_visible_anchor_fragments": 2,
            "require_accessible_alternative": True,
        },
        avoid_fingerprint_count=0,
    )
    packet = {
        "stage": "P07",
        "fixture_id": "P07-A01-S01-O01",
        "case_id": "PP-A01-S01-P07-O01",
    }
    stage_hash = "sha256:" + "b" * 64
    document = build_p07_adjudication_context(
        packet=packet,
        packet_hash=packet_hash,
        opportunity_fixture_id="P07-A01-S01-O01",
        opportunity_context=context,
        stage_boundary_hash=stage_hash,
        opportunity_context_hash=canonical_hash(context),
    )
    return document, packet, packet_hash, stage_hash


def test_p07_field_authority_classifies_the_whole_draft_surface(p07_authority) -> None:
    surface = p07_authority["provider_draft_surface"]
    classified = set(surface["semantic_fields"]) | set(surface["routing_fields"]) | set(
        surface["control_fields"]
    )
    assert classified == set(surface["draft_fields"])
    assert "QuestionCandidate.question_text" in p07_authority["fields_by_authority"][
        MODEL_OWNED
    ]
    assert p07_authority["executable_source_hashes"]["question_generation"].startswith(
        "sha256:"
    )


def test_p07_status_is_server_derived_not_a_model_confession(p07_authority) -> None:
    """``REPLACEMENT_REQUIRED`` is often the materializer's own decision."""

    assert (
        "QuestionGenerationResult.status"
        in p07_authority["fields_by_authority"][SERVER_DERIVED]
    )
    row = next(
        item
        for item in p07_authority["fields"]
        if item["contract"] == "QuestionGenerationResult" and item["field"] == "status"
    )
    assert row["independent_semantic_evidence"] is False


def test_p07_companion_supports_the_model_failure_questions() -> None:
    document, packet, packet_hash, stage_hash = _p07_context()
    questions = document["field_authority_context"][
        "model_failure_questions_answerable"
    ]
    assert set(questions) == {
        "VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE",
        "NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE",
        "FIXTURE_IS_VALID",
    }
    surface = document["deterministic_failure_surface"]
    owners = {row["condition"]: row["owner"] for row in surface["replacement_conditions"]}
    assert owners["ANSWER_LEAKAGE_BLOCKED"] == "SERVER"
    assert owners["REPEATED_QUESTION_FINGERPRINT"] == "SERVER"
    assert owners["PROVIDER_REQUESTED_REPLACEMENT"] == "MODEL"
    verify_context_binding(
        document,
        packet=packet,
        packet_hash=packet_hash,
        stage_boundary_hash=stage_hash,
        field_authority_hash=p07_field_authority()["field_authority_hash"],
    )


def test_p07_companion_is_blind_to_candidate_and_answer() -> None:
    """Blindness is about keys carrying values, not about words appearing.

    ``QuestionCandidate.candidate_id`` legitimately appears as a *field label*
    in the authority classification -- that is the companion telling the
    reviewer the field is SERVER_OWNED, not disclosing a candidate.  So the
    check walks keys rather than grepping the serialized document.
    """

    from comprehension_verification.p07_adjudication_context import (
        FORBIDDEN_CONTEXT_KEYS,
        _walk,
    )

    document, _packet, _packet_hash, _stage = _p07_context()
    keys = {key for _path, key, _value in _walk(document)}
    assert not keys & FORBIDDEN_CONTEXT_KEYS

    values = json.dumps(
        {
            key: value
            for key, value in document.items()
            if key != "field_authority_context"
        },
        ensure_ascii=False,
    )
    for forbidden in ("candidate_id", "oracle", "expected_answer", "reasoning_effort"):
        assert forbidden not in values


def test_p07_companion_rejects_added_and_tampered_fields() -> None:
    document, packet, packet_hash, stage_hash = _p07_context()
    authority = p07_field_authority()["field_authority_hash"]

    smuggled = {**document, "harmless_looking_extra": "anything"}
    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            smuggled,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )

    # Even recomputing the hash must not help: the shape is an allow-list.
    resealed = {key: value for key, value in smuggled.items() if key != "context_hash"}
    resealed["context_hash"] = canonical_hash(resealed)
    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            resealed,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )

    tampered = deepcopy(document)
    tampered["opportunity_context"]["focus"] = "a different task"
    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            tampered,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )


def test_p07_companion_rejects_cross_packet_binding() -> None:
    document, packet, packet_hash, stage_hash = _p07_context()
    authority = p07_field_authority()["field_authority_hash"]

    other_packet = {**packet, "fixture_id": "P07-A02-S01-O01"}
    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            document,
            packet=other_packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )

    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            document,
            packet=packet,
            packet_hash="sha256:" + "c" * 64,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )

    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            document,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash="sha256:" + "d" * 64,
            field_authority_hash=authority,
        )

    with pytest.raises(P07AdjudicationContextError):
        verify_context_binding(
            document,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash="sha256:" + "e" * 64,
        )


def test_p07_companion_rejects_a_non_p07_packet() -> None:
    context = opportunity_context_for(
        {
            "cognitive_operation": "INTERPRET_REPRESENTATION",
            "focus": "f",
            "observable": "o",
            "response_format": "OPEN_SHORT",
            "difficulty": "MEDIUM",
            "target_minutes": 5,
            "allowed_anchor_structures": ["SINGLE_FRAGMENT"],
            "student_justification_required": True,
        },
        support_evidence_alias_count=1,
        generation_constraints={
            "max_visible_anchor_fragments": 1,
            "require_accessible_alternative": False,
        },
    )
    with pytest.raises(P07AdjudicationContextError):
        build_p07_adjudication_context(
            packet={"stage": "P06", "fixture_id": "X", "case_id": "Y"},
            packet_hash="sha256:" + "a" * 64,
            opportunity_fixture_id="X",
            opportunity_context=context,
            stage_boundary_hash="sha256:" + "b" * 64,
            opportunity_context_hash=canonical_hash(context),
        )


def test_p07_server_fields_cannot_be_presented_as_model_evidence(
    p07_authority,
) -> None:
    """A blind attribution may rest only on MODEL_OWNED fields."""

    assert_not_independent_model_evidence(["QuestionCandidate.question_text"])

    for label in (
        "QuestionGenerationResult.status",
        "QuestionCandidate.anchor.structure",
        "QuestionCandidate.anchor.answer_leakage_risk",
        "QuestionCandidate.preliminary_guide.observable_elements[].evidence_ids",
    ):
        assert label in p07_authority["fields_by_authority"][SERVER_DERIVED]
        with pytest.raises(P07AdjudicationContextError):
            assert_not_independent_model_evidence([label])

    for label in ("QuestionCandidate.dimension_id", "QuestionCandidate.evidence_ids"):
        assert label in p07_authority["fields_by_authority"][SERVER_OWNED]
        with pytest.raises(P07AdjudicationContextError):
            assert_not_independent_model_evidence([label])

    with pytest.raises(P07AdjudicationContextError):
        assert_not_independent_model_evidence(["QuestionCandidate.not_a_real_field"])


# ---------------------------------------------------------------------------
# Phase G / H -- claim accuracy
# ---------------------------------------------------------------------------


def test_authorized_rubric_descriptor_text_reaches_the_route(v12_catalog) -> None:
    """Authorized rubric descriptor text is source semantics, not leakage.

    The A04 rubric defines each criterion partly through a column headed
    ``Dónde debería poder comprobarse``.  It legitimately reaches the
    model-visible construct description, so any claim that *no* location
    reaches the route is false.  It must not be stripped.
    """

    construct = next(
        item
        for item in v12_catalog["constructs"]
        if item["construct_key"] == "RUBRIC::A04::UNA_APARICION_INVALIDA_NO_RESERVA_EL_ID"
    )
    assert "Dónde debería poder comprobarse" in construct["neutral_description"]

    doc = " ".join(
        (REPOSITORY_ROOT / "docs/SEMANTIC_BENCHMARK_V1_2.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "No *submission* evidence location is projected into the route." in doc
    assert "bundle and locates evidence itself. No location is projected" not in doc
    assert "Dónde debería poder comprobarse" in doc


def test_submission_evidence_location_stays_evaluator_only(derivation) -> None:
    for route in derivation.routes:
        evidence = route["evidence_provenance"]
        assert evidence["model_visible"] is False
        assert evidence["oracle_declared_locations"]


def test_activities_05_and_12_do_obtain_assignment_constructs(derivation) -> None:
    """Their rubrics are informal; the catalog fallback still works.

    The operative cause of zero routes is that their P06 properties do not
    resolve unambiguously to those source construct names.
    """

    for activity_id in ("act_05_visitas_a_bibliotecas", "act_12_clinica_movil"):
        constructs = derivation.constructs_by_activity[activity_id]
        assert len(constructs) == 4
        assert {item["source_kind"] for item in constructs} == {
            "ASSIGNMENT_REQUIREMENT"
        }
        assert not [
            route for route in derivation.routes if route["activity_id"] == activity_id
        ]
        debt = [
            entry
            for entry in derivation.coverage_debt
            if entry["activity_id"] == activity_id
        ]
        assert debt
        assert all(
            entry["disposition"]
            in {
                "NO_DECLARED_AUTHORIZED_CONSTRUCT",
                "AMBIGUOUS_AUTHORIZED_CONSTRUCT_REFERENCE",
                "MULTIPLE_DECLARED_AUTHORIZED_CONSTRUCTS",
            }
            for entry in debt
        ), "zero coverage here is a resolution outcome, not an absent catalog"


# ---------------------------------------------------------------------------
# Frozen v1.2 authority is not disturbed
# ---------------------------------------------------------------------------


def test_v12_frozen_authority_bytes_are_untouched() -> None:
    """v1.2 is historical. The remediation must not rewrite its authority."""

    freeze = json.loads(
        (
            REPOSITORY_ROOT
            / "reports/semantic_benchmark/v1_2/phase9/pre_results_instrument_freeze.json"
        ).read_text(encoding="utf-8")
    )
    from hashlib import sha256

    for name, expected in freeze["fixture_file_hashes"].items():
        actual = "sha256:" + sha256((V12_FIXTURES / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} drifted from the PART A freeze"


def test_remediation_is_offline_and_authorizes_nothing() -> None:
    """No module added by Phase 9B.6 may reach a provider."""

    package = REPOSITORY_ROOT / "src/comprehension_verification"
    for name in (
        "p06_construct_resolution.py",
        "p06_alignment_verification.py",
        "p06_rare_coverage.py",
        "p06_remediated_derivation.py",
        "p06_support_status_coverage.py",
        "p07_field_authority.py",
        "p07_adjudication_context.py",
    ):
        source = (package / name).read_text(encoding="utf-8")
        for forbidden in (
            "import httpx",
            "import requests",
            "openai",
            "OPENAI_API_KEY",
            "authorize_",
        ):
            assert forbidden not in source, f"{name} references {forbidden}"


# ---------------------------------------------------------------------------
# Findings artifact and verdict
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def findings() -> dict:
    path = (
        REPOSITORY_ROOT
        / "reports/semantic_benchmark/phase9b6/structural_remediation_findings.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_findings_artifact_is_deterministic() -> None:
    """The findings must be reproducible from frozen source alone."""

    import subprocess
    import sys as _sys

    path = (
        REPOSITORY_ROOT
        / "reports/semantic_benchmark/phase9b6/structural_remediation_findings.json"
    )
    before = path.read_bytes()
    result = subprocess.run(
        [_sys.executable, "scripts/build_phase9b6_findings.py"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert path.read_bytes() == before, "the findings artifact is not deterministic"
    assert "PHASE9B6_PRODUCT_DECISION_REQUIRED" in result.stdout


def test_findings_record_the_stop_verdict_and_zero_cost(findings) -> None:
    assert findings["verdict"] == "PHASE9B6_PRODUCT_DECISION_REQUIRED"
    assert findings["provider_calls"] == 0
    assert findings["adjudicator_calls"] == 0
    assert findings["billable_authorizations"] == 0
    assert findings["openai_credentials_resolved"] == 0
    assert findings["real_transport_constructed"] is False
    assert findings["candidate_outcomes_read"] is False
    assert findings["corpus_bytes_modified"] is False
    assert findings["frozen_v12_authority_rewritten"] is False
    assert findings["new_benchmark_version_created"] is None


def test_findings_do_not_declare_readiness(findings) -> None:
    """No path through this phase may output provider-execution readiness."""

    serialized = json.dumps(findings, ensure_ascii=False)
    assert "READY_FOR_PROVIDER_EXECUTION" not in serialized
    assert findings["readiness"] == "NOT_READY_FOR_A_NEW_BENCHMARK_FREEZE"
    assert set(findings["blocking_product_decisions"]) == {
        "P06_UNCERTAIN_COVERAGE_PRODUCT_DECISION_REQUIRED",
        "PROMPT_INJECTION_NOISY_COVERAGE_PRODUCT_DECISION_REQUIRED",
    }


def test_findings_keep_routing_and_bars_unchanged(findings) -> None:
    unchanged = findings["unchanged_by_this_phase"]
    assert unchanged["accepted_rate_bars"] == {
        "SMOKE": 0.80,
        "CORE": 0.95,
        "HELD_OUT": 0.95,
    }
    assert unchanged["k_semantic"] == 3
    assert unchanged["k_planner"] == 1
    assert unchanged["cross_family_fallback"] == "FORBIDDEN"
    assert unchanged["hard_safety_max_confirmed_model_failures"] == 0
    for key in ("routing", "candidate_families", "reasoning_rungs", "caps"):
        assert unchanged[key] is True


def test_findings_reproduce_every_phase_a_blocker(findings) -> None:
    reproduction = findings["phase_a_blocker_reproduction"]
    assert reproduction["A04_S03_P1_bound_to_wrong_construct"]["reproduced"] is True
    assert (
        reproduction["A04_S03_P1_bound_to_wrong_construct"]["v12_match_rule"]
        == "UNIQUE_NAME_PREFIX"
    )
    assert reproduction["A04_S05_P5_multi_verification_mismatch"]["reproduced"] is True
    assert reproduction["bare_no_resolves_by_prefix"]["reproduced"] is True
    assert reproduction["copied_key_alignment_is_tautological"]["reproduced"] is True
    noisy = reproduction["prompt_injection_noisy_lost"]
    assert noisy["v11_p06_routes_with_tag"] == 6
    assert noisy["v12_p06_routes_with_tag"] == 0


def test_findings_diagnose_the_uncertain_gap_as_binding_shape(findings) -> None:
    diagnosis = findings["phase_e_support_status_coverage"]["diagnosis"]
    taxonomy = diagnosis["cause_taxonomy"]
    assert diagnosis["diagnosis"] == "A_ONLY_FIXTURE_AND_BINDING_FORM"
    assert taxonomy["A_existing_corpus_fixture_or_binding_coverage"]["applies"] is True
    assert taxonomy["B_corpus_semantic_coverage"]["applies"] is False
    assert taxonomy["C_production_contract_expressiveness"]["applies"] is False
    assert diagnosis["corpus_count"] > 0
    assert diagnosis["candidate_scoring_count"] == 0


def test_findings_offer_alternatives_for_both_blocking_gaps(findings) -> None:
    alternatives = findings["alternatives"]
    gaps = {item["gap"] for item in alternatives}
    assert gaps == {"P06_UNCERTAIN", "PROMPT_INJECTION_NOISY"}
    for item in alternatives:
        assert item["methodological_consequences"]
        assert item["requires"]["user_decision"]
        assert "benchmark_version" in item["requires"]
    corpus_changing = [
        item for item in alternatives if item["requires"]["corpus_version_change"]
    ]
    for item in corpus_changing:
        assert "EXPLICIT AUTHORIZATION REQUIRED" in item["requires"]["user_decision"]
