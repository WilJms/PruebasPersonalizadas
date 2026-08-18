"""semantic-benchmark/1.2.0 P06 repair regression.

Every test here is offline.  Nothing constructs provider transport, issues an
authorization, or reads a Phase 9B.1 provider output, call ledger or
adjudication result.

The Phase 9B.3 counts (35 ALIGNED / 23 PARTIALLY_ALIGNED / 47 MISALIGNED /
11 ORACLE_SUSPECT / 11 UNRESOLVED) describe the *defective* v1.1 instrument.
They are deliberately not asserted anywhere: reproducing them would freeze the
defect into the repaired benchmark.
"""

from __future__ import annotations

from copy import deepcopy
import dataclasses
import json
from pathlib import Path
import subprocess
import sys

import pytest

from comprehension_verification.canonical import canonical_hash
from comprehension_verification.p06_adjudication_context import (
    AdjudicationContextError,
    P06_ADJUDICATION_CONTEXT_VERSION,
    build_p06_adjudication_context,
    companion_index,
    field_authority_context,
    route_context_for,
    verify_context_binding,
)
from comprehension_verification.p06_field_authority import (
    MODEL_OWNED,
    SERVER_DERIVED,
    SERVER_OWNED,
    p06_field_authority,
)
from comprehension_verification.semantic_benchmark import BenchmarkValidationError
from comprehension_verification.semantic_benchmark_fixtures import (
    parse_submission_bundle,
)
from comprehension_verification.semantic_benchmark_v12 import (
    NO_UNAMBIGUOUS_CONSTRUCT,
    build_construct_catalog,
    build_p06_fixture_v12,
    model_visible_definition_for,
    resolve_target_construct,
    route_semantic_identity,
)
from comprehension_verification.semantic_benchmark_v12_boundary import (
    ACCEPTED_RATE_BAR,
    CORPUS_ROOT,
    EXPECTED_STATUS_TOKENS,
    all_reports,
    assert_route_binding_consistency,
    benchmark_boundary_v12,
    build_v12,
    detect_intra_submission_collisions,
    p06_stage_boundary,
    property_alignment_report,
    stage_boundaries,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

V11_BENCHMARK_BOUNDARY = (
    "sha256:426dda4d560a8d7d53639dfbaa0773c28565450f06e8ff62d51a8cd1bd6f62ff"
)
V11_PROTOCOL_BOUNDARY = (
    "sha256:daa79023de4e3b72a73f31879d481fbedb75492cc5fb4642c7fd2b4a4dbaa540"
)
CORPUS_PACKAGE_BOUNDARY = (
    "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1"
)


@pytest.fixture(scope="module")
def build():
    return build_v12()


@pytest.fixture(scope="module")
def catalog():
    return build_construct_catalog(CORPUS_ROOT)


def _route(build, fixture_id: str) -> dict:
    return next(
        item for item in build.routes["routes"] if item["route_fixture_id"] == fixture_id
    )


def _definition(build, catalog, route: dict) -> dict:
    construct = next(
        item
        for item in catalog["constructs"]
        if item["construct_key"] == route["target_construct_key"]
    )
    activity_path = next(
        item["activity_path"]
        for item in catalog["activities"]
        if item["activity_id"] == route["activity_id"]
    )
    bundle = parse_submission_bundle(
        corpus_root=CORPUS_ROOT,
        activity_path=activity_path,
        activity_id=route["activity_id"],
        submission_id=route["submission_id"],
        artifact_refs=route["evidence_provenance"]["artifacts"],
    )
    return model_visible_definition_for(construct, bundle), bundle


# --- A: P06 route validity -------------------------------------------------


def test_a_every_executable_route_has_one_explicit_target_construct(build) -> None:
    for route in build.routes["routes"]:
        key = route["target_construct_key"]
        assert isinstance(key, str) and key
    keys = [item["target_construct_key"] for item in build.routes["routes"]]
    assert len(keys) == len(build.routes["routes"])
    for case in build.p06_cases:
        assert case["target_construct_key"]


def test_b_target_construct_resolves_to_authorized_activity_source(build, catalog) -> None:
    by_key = {item["construct_key"]: item for item in catalog["constructs"]}
    for route in build.routes["routes"]:
        construct = by_key[route["target_construct_key"]]
        assert construct["activity_id"] == route["activity_id"]
        assert construct["source_kind"] in {
            "RUBRIC_CRITERION",
            "ASSIGNMENT_REQUIREMENT",
        }
        assert construct["source_refs"]
        assert construct["source_hashes"]


def test_c_route_construct_matches_property_target_construct(build) -> None:
    report = property_alignment_report(build)
    assert report["rows"]
    for row in report["rows"]:
        assert row["property_target_construct_key"] == row["route_target_construct_key"]
    assert report["aligned_count"] == len(report["rows"])


def test_d_source_location_and_target_construct_are_separate_authorities(
    build, catalog
) -> None:
    """Construct authority and evidence location must be different authorities.

    A coincidental substring match is not the thing to test: activity 02's rubric
    criterion is legitimately called "Tesis interpretativa" while a submission
    happens to carry a "Tesis" heading.  What must hold is that the construct is
    *sourced* from the rubric/assignment and never from a submission, and that
    the model-visible route is exactly the deterministic projection of the
    catalog entry -- so no location can have contributed to it.
    """

    by_key = {item["construct_key"]: item for item in catalog["constructs"]}
    for route in build.routes["routes"]:
        construct = by_key[route["target_construct_key"]]
        for ref in construct["source_refs"]:
            assert "submissions/" not in ref, (
                f"{route['route_fixture_id']} sources its construct from a submission"
            )
            assert ref.split("#", 1)[0].endswith(
                ("02_rubric.docx", "01_assignment.docx")
            )
        for relative in construct["source_hashes"]:
            assert relative in {"02_rubric.docx", "01_assignment.docx"}

        definition, bundle = _definition(build, catalog, route)
        assert definition == model_visible_definition_for(construct, bundle)
        assert definition["construct"] == construct["canonical_source_name"]
        assert definition["construct_description"] == construct["neutral_description"]
        assert route["evidence_provenance"]["model_visible"] is False
        assert route["derivation_method"] == (
            "DECLARED_AUTHORIZED_CONSTRUCT_THEN_SUBMISSION_EVIDENCE"
        )


def test_d2_v11_location_derived_construct_shape_is_gone(build) -> None:
    """v1.1 constructs looked like 'family: parrafo 2'. None may survive."""

    location_markers = (
        "parrafo",
        "párrafo",
        "ultima linea",
        "última línea",
        "encabezado",
        "section",
    )
    for case in build.p06_cases:
        construct = case["model_visible_definition"]["construct"].casefold()
        for marker in location_markers:
            assert marker not in construct, (
                f"{case['case_id']} still names an evidence location: {construct!r}"
            )


def test_e_expected_support_classification_absent_from_model_visible_input(
    build, catalog
) -> None:
    for route in build.routes["routes"]:
        definition, bundle = _definition(build, catalog, route)
        request, envelope = build_p06_fixture_v12(
            route_fixture_id=route["route_fixture_id"],
            model_visible_definition=definition,
            bundle=bundle,
        )
        serialized = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "envelope": envelope.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        for token in EXPECTED_STATUS_TOKENS:
            assert token not in serialized


def test_f_oracle_identity_and_verdicts_absent_from_model_visible_input(
    build, catalog
) -> None:
    for route in build.routes["routes"]:
        definition, _ = _definition(build, catalog, route)
        serialized = json.dumps(definition, ensure_ascii=False)
        for property_id in route["oracle_binding_metadata"]["property_ids"]:
            assert property_id not in serialized
        for token in ("ORACLE_SUSPECT", "RATIFIED", "oracle_state"):
            assert token not in serialized


def test_g_same_submission_constructs_cannot_collapse_into_one_route(build) -> None:
    rows = [
        (
            item["activity_id"],
            item["submission_id"],
            item["target_construct_key"],
            item["route_semantic_identity"],
        )
        for item in build.p06_cases
    ]
    assert detect_intra_submission_collisions(rows) == []

    # Adversarial regression derived from the v1.1 structural pattern: a
    # location-derived family name made two different criteria indistinguishable.
    collapsed = "sha256:" + "0" * 64
    adversarial = [
        ("act_x", "submission_01", "RUBRIC::AX::USO_DE_EVIDENCIA", collapsed),
        ("act_x", "submission_01", "RUBRIC::AX::VARIABLES_Y_MEDIDAS", collapsed),
    ]
    collisions = detect_intra_submission_collisions(adversarial)
    assert len(collisions) == 1
    assert collisions[0]["construct_a"] != collisions[0]["construct_b"]


def test_g2_two_criteria_on_one_submission_stay_distinguishable(build, catalog) -> None:
    by_submission: dict[tuple[str, str], list[dict]] = {}
    for route in build.routes["routes"]:
        by_submission.setdefault(
            (route["activity_id"], route["submission_id"]), []
        ).append(route)
    multi = [value for value in by_submission.values() if len(value) > 1]
    assert multi, "expected at least one submission carrying two distinct constructs"
    for routes in multi:
        identities = set()
        for route in routes:
            definition, _ = _definition(build, catalog, route)
            identities.add(route_semantic_identity(definition))
        assert len(identities) == len(routes)


def test_h_ambiguous_constructs_fail_closed(catalog) -> None:
    constructs = [
        item for item in catalog["constructs"] if item["activity_id"] == "act_01_luz_y_plantines"
    ]
    multi = resolve_target_construct(
        "SUFFICIENT para 'Uso de evidencia' y simultaneamente INSUFFICIENT para "
        "'Afirmación y alcance'.",
        constructs,
    )
    assert multi["resolved"] is False
    assert multi["disposition"] == NO_UNAMBIGUOUS_CONSTRUCT

    silent = resolve_target_construct(
        "El párrafo final declara una ambigüedad genuina del propio documento.",
        constructs,
    )
    assert silent["resolved"] is False
    assert silent["disposition"] == NO_UNAMBIGUOUS_CONSTRUCT

    single = resolve_target_construct(
        "INSUFFICIENT para 'Variables y medidas': el documento no distingue.",
        constructs,
    )
    assert single["resolved"] is True
    assert single["construct_key"].endswith("VARIABLES_Y_MEDIDAS")


def test_i_construct_or_source_change_alters_the_stage_boundary(build, catalog) -> None:
    before = p06_stage_boundary(build)["stage_boundary_hash"]

    mutated_catalog = deepcopy(build.catalog)
    mutated_catalog["constructs"][0]["neutral_description"] += " (mutated)"
    mutated = dataclasses.replace(build, catalog=mutated_catalog)
    assert p06_stage_boundary(mutated)["stage_boundary_hash"] != before

    mutated_routes = deepcopy(build.routes)
    mutated_routes["routes"][0]["construct_provenance"]["source_refs"] = ["other#ref"]
    assert (
        p06_stage_boundary(
            dataclasses.replace(build, routes=mutated_routes)
        )["stage_boundary_hash"]
        != before
    )


def test_j_assigned_arbitrarily_count_is_derived_and_zero(build) -> None:
    report = property_alignment_report(build)
    assert report["assigned_arbitrarily_count"] == 0
    assert build.bindings["assigned_arbitrarily_count"] == 0
    for binding in build.bindings["bindings"]:
        if binding["stage"] != "P06":
            continue
        assert binding["selection_rule"] == "SINGLE_DECLARED_AUTHORIZED_CONSTRUCT"


def test_k_route_and_property_metadata_are_bidirectionally_consistent(build) -> None:
    bindings = {
        item["property_id"]: item
        for item in build.bindings["bindings"]
        if item["stage"] == "P06"
    }
    bound_from_routes = set()
    for route in build.routes["routes"]:
        for property_id in route["oracle_binding_metadata"]["property_ids"]:
            bound_from_routes.add(property_id)
            binding = bindings[property_id]
            assert binding["fixture_id"] == route["route_fixture_id"]
            assert binding["primary_case_id"] == route["case_id"]
            assert (
                binding["route_target_construct_key"] == route["target_construct_key"]
            )
    assert bound_from_routes == set(bindings)


def test_k2_one_way_hidden_association_fails_closed(build) -> None:
    routes = build.routes["routes"]
    bindings = [
        item for item in build.bindings["bindings"] if item["stage"] == "P06"
    ]
    assert_route_binding_consistency(routes, bindings)

    renamed = deepcopy(bindings)
    renamed[0]["fixture_id"] = "P06-SOMETHING-ELSE"
    with pytest.raises(BenchmarkValidationError):
        assert_route_binding_consistency(routes, renamed)

    reconstrued = deepcopy(bindings)
    reconstrued[0]["route_target_construct_key"] = "RUBRIC::A99::OTHER"
    with pytest.raises(BenchmarkValidationError):
        assert_route_binding_consistency(routes, reconstrued)

    misaligned = deepcopy(bindings)
    misaligned[0]["property_target_construct_key"] = "RUBRIC::A99::OTHER"
    with pytest.raises(BenchmarkValidationError):
        assert_route_binding_consistency(routes, misaligned)

    orphaned = deepcopy(bindings)
    orphaned.append({**orphaned[0], "property_id": "A99-S01-P1"})
    with pytest.raises(BenchmarkValidationError):
        assert_route_binding_consistency(routes, orphaned)


# --- L: production representativeness --------------------------------------


def test_l_every_route_is_production_representative(build) -> None:
    report = all_reports(build)["production_representativeness"]
    assert report["benchmark_only_semantic_channel"] is False
    assert report["route_count"] == len(build.p06_cases)
    for row in report["routes"]:
        assert "EvidenceMappingVariantContext.name" in row["represented_surfaces"]
        assert (
            "EvidenceMappingTemplateContext.cognitive_operation"
            in row["represented_surfaces"]
        )
        assert row["envelope_schema_version"] == "p06-alias-envelope/1.0.0"


def test_l2_benchmark_only_semantics_cannot_bypass_the_production_envelope(
    build, catalog
) -> None:
    """A benchmark-only construct description must not survive the projection."""

    from comprehension_verification.semantic_benchmark_v12_boundary import (
        _production_projection,
    )

    route = build.routes["routes"][0]
    definition, bundle = _definition(build, catalog, route)
    _request, envelope = build_p06_fixture_v12(
        route_fixture_id=route["route_fixture_id"],
        model_visible_definition=definition,
        bundle=bundle,
    )
    smuggled = {**definition, "construct_description": "benchmark-only hint"}
    with pytest.raises(BenchmarkValidationError):
        _production_projection(envelope, smuggled)


def test_l3_property_text_never_reaches_model_visible_input(build, catalog) -> None:
    ratifications = {
        json.loads(path.read_text(encoding="utf-8"))["activity_id"]: json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(CORPUS_ROOT.glob("activity_*/final_ratification.json"))
    }
    for route in build.routes["routes"][:12]:
        definition, _ = _definition(build, catalog, route)
        serialized = json.dumps(definition, ensure_ascii=False)
        ratification = ratifications[route["activity_id"]]
        for submission in ratification["submissions"]:
            for prop in submission["properties"]:
                if prop["property_id"] in route["oracle_binding_metadata"]["property_ids"]:
                    assert prop["description"][:60] not in serialized


# --- P06 blind adjudication context ---------------------------------------


def _packet(route: dict) -> dict:
    return {
        "schema_version": "semantic-review-packet/1.1.0",
        "case_id": route["case_id"],
        "stage": "P06",
        "fixture_id": route["route_fixture_id"],
        "binding_scope": "CASE_SPECIFIC",
    }


def _context_for(build, catalog, route: dict) -> tuple[dict, dict, str, str]:
    definition, _ = _definition(build, catalog, route)
    packet = _packet(route)
    packet_hash = canonical_hash(packet)
    stage_hash = p06_stage_boundary(build)["stage_boundary_hash"]
    context = build_p06_adjudication_context(
        packet=packet,
        packet_hash=packet_hash,
        route=route,
        model_visible_definition=definition,
        stage_boundary_hash=stage_hash,
        route_context_hash=canonical_hash(route_context_for(route, definition)),
    )
    return context, packet, packet_hash, stage_hash


def test_ctx_a_every_adjudicable_packet_has_exactly_one_companion(build, catalog) -> None:
    contexts = [
        _context_for(build, catalog, route)[0] for route in build.routes["routes"][:8]
    ]
    index = companion_index(contexts)
    assert index["context_count"] == len(contexts)
    assert len(index["packet_hashes"]) == len(contexts)
    with pytest.raises(AdjudicationContextError):
        companion_index(contexts + [contexts[0]])


def test_ctx_b_c_packet_and_fixture_binding_is_exact(build, catalog) -> None:
    route = build.routes["routes"][0]
    context, packet, packet_hash, stage_hash = _context_for(build, catalog, route)
    authority = p06_field_authority()["field_authority_hash"]
    verify_context_binding(
        context,
        packet=packet,
        packet_hash=packet_hash,
        stage_boundary_hash=stage_hash,
        field_authority_hash=authority,
    )
    with pytest.raises(AdjudicationContextError):
        verify_context_binding(
            context,
            packet=packet,
            packet_hash="sha256:" + "1" * 64,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )


def test_ctx_d_route_context_matches_the_frozen_model_visible_task(
    build, catalog
) -> None:
    route = build.routes["routes"][0]
    definition, _ = _definition(build, catalog, route)
    context, *_ = _context_for(build, catalog, route)
    assert context["route_context"]["target_construct_label"] == definition["construct"]
    assert context["route_context"]["focus"] == definition["focus"]
    assert context["route_context"]["observable"] == definition["observable"]
    assert context["route_context_hash"] == canonical_hash(
        route_context_for(route, definition)
    )
    with pytest.raises(AdjudicationContextError):
        build_p06_adjudication_context(
            packet=_packet(route),
            packet_hash=canonical_hash(_packet(route)),
            route=route,
            model_visible_definition=definition,
            stage_boundary_hash="sha256:" + "2" * 64,
            route_context_hash="sha256:" + "3" * 64,
        )


def test_ctx_e_f_g_field_authority_is_executable_and_correct() -> None:
    authority = p06_field_authority()
    by_authority = authority["fields_by_authority"]
    assert "QuestionOpportunity.support_status" in by_authority[MODEL_OWNED]
    assert "QuestionOpportunity.support_description" in by_authority[MODEL_OWNED]
    assert "QuestionOpportunity.evidence_fit" in by_authority[SERVER_DERIVED]
    assert "EvidenceVariantMatch.mapping_confidence" in by_authority[SERVER_DERIVED]
    assert "EvidenceVariantMatch.support_status" in by_authority[SERVER_DERIVED]
    assert "QuestionOpportunity.focus" in by_authority[SERVER_OWNED]
    for row in authority["fields"]:
        if row["authority"] == SERVER_DERIVED:
            assert row["independent_semantic_evidence"] is False
    assert authority["materializer_boundary"]["boundary_hash"]
    assert authority["executable_source_hashes"]["evidence_mapping"].startswith("sha256:")


def test_ctx_h_server_justification_prose_cannot_override_field_authority() -> None:
    """The constant server sentence must not make a model-owned field look server-owned."""

    authority = p06_field_authority()
    justification = next(
        row
        for row in authority["fields"]
        if row["contract"] == "EvidenceVariantMatch" and row["field"] == "justification"
    )
    assert justification["authority"] == SERVER_OWNED
    assert justification["independent_semantic_evidence"] is False
    assert "constant" in justification["note"].lower()

    context = field_authority_context(authority)
    # The neighbouring aggregate is server-derived, but support_status on the
    # opportunity - the field an adjudicator scores - stays model-owned.
    assert "QuestionOpportunity.support_status" in context["model_owned"]
    assert "EvidenceVariantMatch.support_status" in context[
        "server_derived_from_model_input"
    ]
    assert "never establishes field authority" in context["server_prose_rule"]


def test_ctx_i_j_k_no_candidate_or_outcome_metadata_leaks(build, catalog) -> None:
    route = build.routes["routes"][0]
    context, *_ = _context_for(build, catalog, route)
    serialized = json.dumps(context, ensure_ascii=False)
    for token in (
        "candidate_id",
        "reasoning_effort",
        "promotion_order",
        "latency_ms",
        "cost_usd",
        "qualification_result",
        "oracle_verdict",
        "expected_support_status",
    ):
        assert token not in serialized
    assert "split" not in context
    assert "rung" not in context
    for property_id in route["oracle_binding_metadata"]["property_ids"]:
        assert property_id not in serialized


def test_ctx_l_context_cannot_attach_to_another_packet(build, catalog) -> None:
    first, second = build.routes["routes"][0], build.routes["routes"][1]
    context, *_ = _context_for(build, catalog, first)
    other_packet = _packet(second)
    with pytest.raises(AdjudicationContextError):
        verify_context_binding(
            context,
            packet=other_packet,
            packet_hash=canonical_hash(other_packet),
            stage_boundary_hash=p06_stage_boundary(build)["stage_boundary_hash"],
            field_authority_hash=p06_field_authority()["field_authority_hash"],
        )


def test_ctx_strict_contract_rejects_any_added_field(build, catalog) -> None:
    """Equivalent-or-stronger than additionalProperties=false.

    The context hash covers every key except itself, so smuggling a field in --
    forbidden name or not -- invalidates the binding cryptographically rather
    than relying on a schema keyword.
    """

    route = build.routes["routes"][0]
    context, packet, packet_hash, stage_hash = _context_for(build, catalog, route)
    authority = p06_field_authority()["field_authority_hash"]

    smuggled = {**context, "harmless_looking_extra": "anything"}
    with pytest.raises(AdjudicationContextError):
        verify_context_binding(
            smuggled,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )

    tampered = deepcopy(context)
    tampered["route_context"]["focus"] = "a different task"
    with pytest.raises(AdjudicationContextError):
        verify_context_binding(
            tampered,
            packet=packet,
            packet_hash=packet_hash,
            stage_boundary_hash=stage_hash,
            field_authority_hash=authority,
        )


def test_ctx_m_blind_handoff_remains_self_contained(build, catalog) -> None:
    context, *_ = _context_for(build, catalog, build.routes["routes"][0])
    assert context["self_contained"] is True
    assert context["schema_version"] == P06_ADJUDICATION_CONTEXT_VERSION
    required = {
        "packet_hash",
        "fixture_id",
        "route_context",
        "field_authority_context",
        "p06_stage_boundary_hash",
        "context_hash",
    }
    assert required.issubset(context)
    answerable = context["field_authority_context"][
        "model_failure_questions_answerable"
    ]
    assert "VIOLATION_ATTRIBUTABLE_TO_THE_MODEL_OWNED_STAGE" in answerable
    assert "NOT_A_DETERMINISTIC_MATERIALIZER_PARSER_OR_PLANNER_FAILURE" in answerable
    assert "FIXTURE_IS_VALID" in answerable


# --- stage boundaries ------------------------------------------------------


def test_stage_boundaries_are_deterministic_in_process(build) -> None:
    assert stage_boundaries(build) == stage_boundaries(build)
    assert benchmark_boundary_v12(build) == benchmark_boundary_v12(build)


def test_stage_boundaries_are_deterministic_across_processes() -> None:
    command = [
        sys.executable,
        "-c",
        "import json,sys;sys.path.insert(0,'src');"
        "from comprehension_verification.semantic_benchmark_v12_boundary import "
        "build_v12,benchmark_boundary_v12,stage_boundaries;"
        "b=build_v12();"
        "print(json.dumps({'global':benchmark_boundary_v12(b)['benchmark_boundary_hash'],"
        "'stages':stage_boundaries(b)['stage_boundary_hashes']}))",
    ]
    env = {"CVA_MODEL_MODE": "mock", "CVA_P10_ENABLED": "false", "PATH": "/usr/bin:/bin"}
    outputs = [
        json.loads(
            subprocess.run(
                command,
                cwd=REPOSITORY_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        for _ in range(2)
    ]
    assert outputs[0] == outputs[1]


def test_p06_mutation_changes_only_the_p06_stage_boundary(build) -> None:
    before = stage_boundaries(build)["stage_boundary_hashes"]
    mutated_cases = tuple(deepcopy(item) for item in build.p06_cases)
    mutated_cases[0]["input_hash"] = "sha256:" + "4" * 64
    mutated = dataclasses.replace(build, p06_cases=mutated_cases)
    after = stage_boundaries(mutated)["stage_boundary_hashes"]
    assert after["P06"] != before["P06"]
    for stage in ("P04", "PLANNER", "P07", "P09"):
        assert after[stage] == before[stage]


def test_field_authority_mutation_changes_the_p06_boundary(build, monkeypatch) -> None:
    before = p06_stage_boundary(build)["stage_boundary_hash"]
    import comprehension_verification.semantic_benchmark_v12_boundary as module

    monkeypatch.setattr(
        module,
        "p06_field_authority",
        lambda: {**p06_field_authority(), "field_authority_hash": "sha256:" + "5" * 64},
    )
    assert p06_stage_boundary(build)["stage_boundary_hash"] != before


def test_adjudication_context_mutation_changes_the_p06_boundary(build, monkeypatch) -> None:
    before = p06_stage_boundary(build)["stage_boundary_hash"]
    import comprehension_verification.semantic_benchmark_v12_boundary as module

    monkeypatch.setattr(module, "P06_ADJUDICATION_CONTEXT_VERSION", "p06-x/9.9.9")
    assert p06_stage_boundary(build)["stage_boundary_hash"] != before


def test_shared_authority_mutation_changes_all_affected_boundaries(build) -> None:
    before = benchmark_boundary_v12(build)["benchmark_boundary_hash"]
    mutated = dataclasses.replace(build, package_hash="sha256:" + "6" * 64)
    after = benchmark_boundary_v12(mutated)
    assert after["benchmark_boundary_hash"] != before
    assert (
        after["stage_boundary_hashes"]["P06"]
        != stage_boundaries(build)["stage_boundary_hashes"]["P06"]
    )
    assert (
        after["stage_boundary_hashes"]["P07"]
        != stage_boundaries(build)["stage_boundary_hashes"]["P07"]
    )


def test_global_boundary_binds_the_stage_boundaries(build) -> None:
    boundary = benchmark_boundary_v12(build)
    boundaries = stage_boundaries(build)
    assert boundary["stage_boundaries_hash"] == boundaries["stage_boundaries_hash"]
    assert boundary["stage_boundary_hashes"] == boundaries["stage_boundary_hashes"]
    for dependency in (
        "shared benchmark authority",
        "stage boundaries",
        "corpus boundary",
        "split partition authority",
        "cross-stage aggregation/version authority",
        "qualification property disposition authority",
    ):
        assert dependency in boundary["documented_dependencies"]


def test_v11_had_no_stage_boundaries(build) -> None:
    assert stage_boundaries(build)["v11_had_stage_boundaries"] is False


# --- versioning ------------------------------------------------------------


def test_v11_artifacts_and_corpus_remain_unchanged(build) -> None:
    v11_boundary = json.loads(
        (
            REPOSITORY_ROOT / "reports/semantic_benchmark/v1_1/benchmark_boundary.json"
        ).read_text(encoding="utf-8")
    )
    assert v11_boundary["benchmark_boundary_hash"] == V11_BENCHMARK_BOUNDARY
    v11_protocol = json.loads(
        (
            REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_1/phase9/qualification_protocol.json"
        ).read_text(encoding="utf-8")
    )
    assert v11_protocol["benchmark_boundary_hash"] == V11_BENCHMARK_BOUNDARY
    v11_freeze = json.loads(
        (
            REPOSITORY_ROOT
            / "reports/semantic_benchmark/v1_1/phase9/protocol_freeze_report.json"
        ).read_text(encoding="utf-8")
    )
    assert v11_freeze["phase9_protocol_boundary_hash"] == V11_PROTOCOL_BOUNDARY
    assert build.package_hash == CORPUS_PACKAGE_BOUNDARY


def test_v12_boundary_differs_from_v11(build) -> None:
    assert (
        benchmark_boundary_v12(build)["benchmark_boundary_hash"]
        != V11_BENCHMARK_BOUNDARY
    )


def test_v12_protocol_has_a_new_boundary_and_keeps_policy(build) -> None:
    protocol = json.loads(
        (
            REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_2/phase9/qualification_protocol.json"
        ).read_text(encoding="utf-8")
    )
    assert protocol["protocol_version"] == "phase9-qualification-protocol/1.2.0"
    assert protocol["protocol_boundary_hash"] != V11_PROTOCOL_BOUNDARY
    assert protocol["supersedes"]["never_executed"] is False
    assert (
        protocol["supersedes"]["status"]
        == "SUPERSEDED_AFTER_P06_INSTRUMENT_VALIDITY_FAILURE"
    )
    carried = protocol["carried_forward_unchanged"]
    assert carried["cross_family_fallback"] == "FORBIDDEN"
    assert carried["semantic_k"] == 3
    assert carried["planner_deterministic_k"] == 1
    assert carried["pass_qa_sample_percent"] == 15
    assert carried["accepted_rate_bar_by_split"] == ACCEPTED_RATE_BAR
    assert carried["stage_reasoning_ladder"]["P04"] == ["HIGH", "XHIGH"]
    assert carried["stage_reasoning_ladder"]["P06"] == ["HIGH", "XHIGH", "MAX"]
    assert protocol["model_selection_policy_changed_by_v11_outcomes"] is False
    assert protocol["provider_calls"] == 0
    assert protocol["adjudicator_calls"] == 0


def test_v12_candidate_matrix_is_semantically_unchanged() -> None:
    v11 = json.loads(
        (
            REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_1/phase9/candidate_matrix.json"
        ).read_text(encoding="utf-8")
    )
    v12 = json.loads(
        (
            REPOSITORY_ROOT
            / "evaluation/semantic_benchmark/v1_2/phase9/candidate_matrix.json"
        ).read_text(encoding="utf-8")
    )
    assert v12["candidates"] == v11["candidates"]
    assert v12["stage_model_family"] == v11["stage_model_family"]
    assert v12["stage_reasoning_ladder"] == v11["stage_reasoning_ladder"]
    assert v12["cross_family_fallback"] == v11["cross_family_fallback"]
    assert v12["excluded_model_families"] == v11["excluded_model_families"]
    assert v12["authorization"] == "NONE"
    assert {item["model"] for item in v12["candidates"]} == {
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    }


# --- thresholds, safety, splits, debt --------------------------------------


def test_thresholds_are_recomputed_mechanically(build) -> None:
    from math import floor

    reports = all_reports(build)
    for row in reports["thresholds"]["p06_thresholds"]:
        expected = floor(
            row["applicable_property_count"] * (1 - row["accepted_semantic_rate_bar"])
        )
        assert row["max_confirmed_model_failures"] == expected
        assert row["max_hard_safety_failures"] == 0
    assert reports["thresholds"]["accepted_rate_bar_by_split"] == ACCEPTED_RATE_BAR
    assert reports["thresholds"]["derived_from_historical_qualifications"] is False


def test_safety_policy_is_not_weakened_and_debt_is_explicit(build) -> None:
    safety = all_reports(build)["safety_gate"]
    assert safety["policy_weakened"] is False
    for row in safety["rows"]:
        assert row["max_confirmed_model_failures"] == 0
    debt = safety["SAFETY_COVERAGE_DEBT"]
    assert debt["count"] >= 1
    assert debt["entries"]
    for entry in debt["entries"]:
        assert entry["lost_tags"]


def test_held_out_partition_is_unchanged(build) -> None:
    partition = all_reports(build)["split_partition"]
    assert partition["held_out_activity_numbers"] == [3, 7, 9, 10, 12]
    assert partition["held_out_partition_changed"] is False
    for case in build.p06_cases:
        number = int(case["case_id"].split("-")[1].removeprefix("A"))
        if number in {3, 7, 9, 10, 12}:
            assert case["split"] == "HELD_OUT_CONFIRMATION"
        else:
            assert case["split"] in {"SMOKE", "CORE"}


def test_activity_wide_properties_are_not_candidate_gates(build) -> None:
    activity_wide = [
        item
        for item in build.dispositions["dispositions"]
        if item["scope"] == "ACTIVITY_WIDE"
    ]
    assert activity_wide
    for item in activity_wide:
        assert item["candidate_scoring_allowed"] is False
        assert item["qualification_disposition"] in {
            "ACTIVITY_COVERAGE_INDEX_ONLY",
            "CONTEXTUAL_NON_GATE",
            "NO_VALID_STAGE_LOCAL_FIXTURE",
            "NOT_APPLICABLE",
        }
    bound = {
        binding["property_id"]
        for binding in build.bindings["bindings"]
        if binding["stage"] == "P06"
    }
    assert not bound & {item["property_id"] for item in activity_wide}


def test_dispositions_do_not_rewrite_corpus_history(build) -> None:
    assert build.dispositions["corpus_history_rewritten"] is False
    assert build.dispositions["scope"] == "QUALIFICATION_LEVEL_ONLY"
    for item in build.dispositions["dispositions"]:
        assert item["original_oracle_state"] in {
            "VALID",
            "ORACLE_SUSPECT",
            "NOT_APPLICABLE",
        }
        assert item["original_description_hash"].startswith("sha256:")


def test_coverage_debt_and_smoke_membership_are_explicit(build) -> None:
    debt = all_reports(build)["coverage_debt"]
    assert debt["v11_p06_route_count"] == 127
    assert debt["v12_p06_route_count"] == len(build.p06_cases)
    assert debt["route_count_is_not_a_target"] is True
    smoke = debt["smoke_membership"]
    assert smoke["replacement_added_after_observation"] is False
    assert set(smoke["retained"]) | set(smoke["suspended"]) == set(
        smoke["pre_registered_p06_properties"]
    )
