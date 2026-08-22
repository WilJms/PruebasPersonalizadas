"""Canonical offline semantic benchmark infrastructure for Phase 8.

This module has no dependency on the model gateway, provider adapters,
provider authorization, secrets, network transports, or model-call ledgers.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from .blueprint_compiler import blueprint_compiler_boundary
from .canonical import canonical_hash, pretty_json, sha256_bytes
from .contracts import models as m
from .evidence_mapping import evidence_mapping_materializer_boundary
from .guide_generation import guide_generation_materializer_boundary
from .parsers.service import PARSER_VERSION, SafeParserService
from .pipeline_authority import (
    DISABLED_MODEL_STAGE_IDS,
    HISTORICAL_HARNESS_EVIDENCE_STATUS,
    PIPELINE_AUTHORITY_VERSION,
    TARGET_INACTIVE_MODEL_STAGE_IDS,
    pipeline_authority_manifest,
)
from .planning import PLANNER_VERSION
from .question_generation import question_generation_materializer_boundary
from .semantic_benchmark_fixtures import (
    P04_FIXTURE_BUILDER_VERSION,
    P06_FIXTURE_BUILDER_VERSION,
    P07_FIXTURE_BUILDER_VERSION,
    P09_FIXTURE_BUILDER_VERSION,
    P09_LOCATOR_RESOLVER_VERSION,
    P09_OPERATION_PROJECTION_VERSION,
    PLANNER_FIXTURE_BUILDER_VERSION,
    SCAFFOLD_MARKER,
    build_p04_fixture,
    build_p06_fixture,
    build_p07_fixture,
    build_p09_fixture,
    build_planner_fixture,
    parse_submission_bundle,
)


CORPUS_VERSION = "pruebas-personalizadas-corpus/1.0.0"
SEMANTIC_BENCHMARK_VERSION = "semantic-benchmark/1.1.0"
EXPECTED_CORPUS_PACKAGE_HASH = (
    "21c21f3a53bfb786162dc350dc38c93b7b007d9f23b744a354de4ac2354048a1"
)
EXPECTED_CORPUS_READINESS = "CORPUS_READY_FOR_SEMANTIC_BENCHMARK"
CORPUS_RATIFICATION_TYPE = "INDEPENDENT_MODEL_RATIFICATION_DERIVED_FROM_OPUS5"
BENCHMARK_ORACLE_LEAKAGE_BLOCKED = "BENCHMARK_ORACLE_LEAKAGE_BLOCKED"
BENCHMARK_CORPUS_BOUNDARY_MISMATCH = "BENCHMARK_CORPUS_BOUNDARY_MISMATCH"
BENCHMARK_PROVIDER_DISABLED = "NON_BILLABLE_BENCHMARK_DRY_RUN"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_ROOT = (
    REPOSITORY_ROOT / "evaluation/corpora/pruebas_personalizadas/v1"
)
BENCHMARK_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1_1"
BENCHMARK_FIXTURE_ROOT = BENCHMARK_DEFINITION_ROOT / "fixtures"
DEFAULT_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1_1"

ACTIVE_SEMANTIC_STAGES = ("P04", "P06", "P07", "P09")
ACTIVE_BENCHMARK_STAGES = ("P04", "P06", "PLANNER", "P07", "P09")
HELD_OUT_ACTIVITY_NUMBERS = frozenset({3, 7, 9, 10, 12})
P09_SPLIT_BY_ACTIVITY = {
    3: "SMOKE",
    4: "CORE",
    9: "CORE",
    12: "HELD_OUT_CONFIRMATION",
}

SMOKE_CASE_IDS = frozenset(
    {
        "PP-A01-P04-001",
        "PP-A01-S01-P06-R01",
        "PP-A01-S03-P06-R01",
        "PP-A01-S01-P07-O01",
        "PP-A01-S05-P07-O02",
        "PP-A02-S02-P07-O01",
        "PP-A04-S04-P07-O01",
        "PP-A04-S06-P07-O01",
        "PP-A08-S02-P07-O02",
        "PP-A01-S01-PLANNER-001",
        "PP-A01-S02-PLANNER-001",
    }
)

RESULT_STATE_RULES = {
    "PASS": "candidate output satisfies the ratified property",
    "MODEL_FAILURE": "a VALID property is violated by the model-owned stage",
    "DEFENSIBLE_ALTERNATIVE": "output differs but remains source-defensible",
    "ORACLE_SUSPECT": "the execution confirms the oracle cannot decide",
    "TECHNICAL_FAILURE": "provider, timeout, schema, or tooling failure",
    "NOT_APPLICABLE": "the source oracle marks the property out of scope",
    "PENDING_ADJUDICATION": "no real output exists or semantic review is pending",
}
ORACLE_STATE_RULES = {
    "VALID": "usable for adjudication",
    "ORACLE_SUSPECT": "reviewable but excluded from hard failure denominators",
    "NOT_APPLICABLE": "traced but excluded from semantic denominators",
    "INVALID": "forbidden in the frozen ready corpus",
}
EVALUATOR_DEFINITIONS = {
    "DETERMINISTIC": "product-owned invariant with exact machine result",
    "RULE_BASED": "explicit mechanical relation; no hidden semantic inference",
    "EXTERNAL_ADJUDICATION_REQUIRED": "semantic interpretation deferred to Phase 9 review",
}
DETERMINISTIC_INVARIANT_DEFINITIONS = (
    "CORPUS_BOUNDARY",
    "P04_SOURCE_COMPLETENESS",
    "P04_ORACLE_ISOLATION",
    "P06_ROUTE_ALIGNMENT",
    "P06_EXPECTED_STATUS_ISOLATION",
    "P07_OPPORTUNITY_ALIGNMENT",
    "P07_SUPPORT_RESOLUTION",
    "P09_PROPERTY_SCOPE",
    "P09_EXACT_LOCATOR_RESOLUTION",
    "TAG_SCOPE_VALIDITY",
    "RARE_COVERAGE_VALIDITY",
    "PROPERTY_BINDING_COMPLETENESS",
    "PROPERTY_DENOMINATOR_VALIDITY",
    "SPLIT_COVERAGE",
    "ANTI_ORACLE_LEAKAGE",
    "CANDIDATE_MATRIX_UNSET",
    "PROVIDER_CALL_GRAPH_ABSENT",
)

PROPERTY_AGGREGATION_RULES = {
    "observation_unit": "CASE_PROPERTY_RUN",
    "property_run_unit": "PROPERTY_CANDIDATE_REASONING_RUN",
    "qualification_denominator_unit": "PROPERTY_CANDIDATE_REASONING",
    "required_quantifier": "ALL_APPLICABLE_CASE_OBSERVATIONS",
    "prohibited_quantifier": "ANY_APPLICABLE_VIOLATION_FAILS",
    "defensible_alternative_policy": "NEVER_AUTOMATIC_HARD_FAILURE",
    "contextual_note_policy": "REVIEWABLE_NON_GATE_UNLESS_EXPLICITLY_ADJUDICATED",
    "technical_and_pending_policy": "EXCLUDED_FROM_SEMANTIC_FAILURE_DENOMINATOR",
}

RARE_FAMILY_POLICIES = {
    "silent_conceptual_gap": {
        "tag": "SILENT_CONCEPTUAL_GAP",
        "criticality": "CONFIRMATORY",
        "singleton_preference": "HELD_OUT_CONFIRMATION",
    },
    "p06_uncertain": {
        "tag": "P06_UNCERTAIN",
        "criticality": "SEMANTIC",
        "singleton_preference": "QUALIFICATION",
    },
    "simulated_pii": {
        "tag": "SIMULATED_PII",
        "criticality": "SAFETY_CRITICAL",
        "singleton_preference": "QUALIFICATION",
    },
    "silent_prompt_injection": {
        "tag": "PROMPT_INJECTION_SILENT",
        "criticality": "SAFETY_CRITICAL",
        "singleton_preference": "QUALIFICATION",
    },
    "authorized_source_adversarial": {
        "tag": "ADVERSARIAL_AUTHORIZED_SOURCE",
        "criticality": "SAFETY_CRITICAL",
        "singleton_preference": "QUALIFICATION",
    },
    "multi_artifact": {
        "tag": "MULTI_ARTIFACT",
        "criticality": "STRUCTURAL",
        "singleton_preference": "QUALIFICATION",
    },
    "answer_leakage": {
        "tag": "LEAKAGE_ORACLE_SUSPECT",
        "criticality": "SAFETY_CRITICAL",
        "singleton_preference": "QUALIFICATION",
    },
    "planner_infeasibility": {
        "tag": "PLAN_INFEASIBLE",
        "criticality": "STRUCTURAL",
        "singleton_preference": "QUALIFICATION",
    },
    "p09_cannot_infer": {
        "tag": "P09_CANNOT_INFER",
        "criticality": "SEMANTIC",
        "singleton_preference": "QUALIFICATION",
    },
}


class BenchmarkStage(StrEnum):
    P04 = "P04"
    P06 = "P06"
    PLANNER = "PLANNER"
    P07 = "P07"
    P09 = "P09"


class BenchmarkSplit(StrEnum):
    SMOKE = "SMOKE"
    CORE = "CORE"
    HELD_OUT_CONFIRMATION = "HELD_OUT_CONFIRMATION"


class ResultState(StrEnum):
    PASS = "PASS"
    MODEL_FAILURE = "MODEL_FAILURE"
    DEFENSIBLE_ALTERNATIVE = "DEFENSIBLE_ALTERNATIVE"
    ORACLE_SUSPECT = "ORACLE_SUSPECT"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_ADJUDICATION = "PENDING_ADJUDICATION"


class EvaluatorMode(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    RULE_BASED = "RULE_BASED"
    EXTERNAL_ADJUDICATION_REQUIRED = "EXTERNAL_ADJUDICATION_REQUIRED"


class PropertyHardness(StrEnum):
    HARD_SEMANTIC_PROPERTY = "HARD_SEMANTIC_PROPERTY"
    REVIEWABLE_SEMANTIC_PROPERTY = "REVIEWABLE_SEMANTIC_PROPERTY"
    ORACLE_SUSPECT_PROPERTY = "ORACLE_SUSPECT_PROPERTY"
    NOT_APPLICABLE_PROPERTY = "NOT_APPLICABLE_PROPERTY"


class BenchmarkValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _boundary_hash(rows: Iterable[tuple[str, str, int]]) -> str:
    serialized = "".join(
        sorted(f"{path}\0{digest}\0{size}\n" for path, digest, size in rows)
    )
    return _digest(serialized.encode("utf-8"))


def _normalized_manifest_hash(manifest: dict[str, Any]) -> str:
    value = copy.deepcopy(manifest)
    value["boundary_hashes"]["corpus_package_boundary_hash"] = "0" * 64
    for entry in value["files"]:
        if entry["path"] in {
            "corpus_final_manifest.json",
            "corpus_finalization_report.md",
        }:
            entry["sha256"] = "0" * 64
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest(data)


_REPORT_PACKAGE_RE = re.compile(
    rb"(?m)^(corpus_package_boundary_hash:\s*)[0-9a-f]{64}(\s*)$"
)


def _normalized_report_hash(path: Path) -> str:
    data, count = _REPORT_PACKAGE_RE.subn(
        rb"\g<1>" + (b"0" * 64) + rb"\g<2>", path.read_bytes()
    )
    if count != 1:
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH,
            "corpus report normalization marker is invalid",
        )
    return _digest(data)


@dataclass(frozen=True)
class CorpusPackage:
    root: Path
    manifest: dict[str, Any]
    entries: dict[str, dict[str, Any]]
    ratifications: tuple[dict[str, Any], ...]
    p09_fixtures: tuple[dict[str, Any], ...]

    @property
    def package_hash(self) -> str:
        return str(self.manifest["boundary_hashes"]["corpus_package_boundary_hash"])

    @property
    def activity_by_id(self) -> dict[str, dict[str, Any]]:
        return {item["activity_id"]: item for item in self.ratifications}


def load_corpus_package(
    root: Path = DEFAULT_CORPUS_ROOT,
    *,
    expected_hash: str = EXPECTED_CORPUS_PACKAGE_HASH,
) -> CorpusPackage:
    root = root.resolve()
    manifest = _json(root / "corpus_final_manifest.json")
    if manifest.get("readiness") != EXPECTED_CORPUS_READINESS:
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH, "corpus is not benchmark-ready"
        )
    entries = {item["path"]: item for item in manifest["files"]}
    if len(entries) != len(manifest["files"]):
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH, "duplicate corpus manifest path"
        )
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }
    if actual_paths != set(entries):
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH, "corpus inventory mismatch"
        )
    source_rows: list[tuple[str, str, int]] = []
    oracle_rows: list[tuple[str, str, int]] = []
    fixture_rows: list[tuple[str, str, int]] = []
    package_rows: list[tuple[str, str, int]] = []
    for relative, entry in entries.items():
        path = root / relative
        if path.stat().st_size != entry["bytes"]:
            raise BenchmarkValidationError(
                BENCHMARK_CORPUS_BOUNDARY_MISMATCH, f"corpus byte mismatch: {relative}"
            )
        if relative == "corpus_final_manifest.json":
            actual = _normalized_manifest_hash(manifest)
        else:
            actual = _digest(path.read_bytes())
        if actual != entry["sha256"]:
            raise BenchmarkValidationError(
                BENCHMARK_CORPUS_BOUNDARY_MISMATCH, f"corpus hash mismatch: {relative}"
            )
        row_digest = (
            _normalized_report_hash(path)
            if relative == "corpus_finalization_report.md"
            else entry["sha256"]
        )
        if entry["role"] == "SOURCE_INPUT":
            source_rows.append((relative, _digest(path.read_bytes()), entry["bytes"]))
        if relative.endswith("/final_ratification.json"):
            oracle_rows.append((relative, _digest(path.read_bytes()), entry["bytes"]))
        if entry["role"] == "P09_STAGE_FIXTURE":
            fixture_rows.append((relative, _digest(path.read_bytes()), entry["bytes"]))
        if entry["role"] != "AUDIT_HISTORY":
            package_rows.append((relative, row_digest, entry["bytes"]))
    computed = {
        "source_corpus_boundary_hash": _boundary_hash(source_rows),
        "semantic_oracle_boundary_hash": _boundary_hash(oracle_rows),
        "p09_fixture_boundary_hash": _boundary_hash(fixture_rows),
        "corpus_package_boundary_hash": _boundary_hash(package_rows),
    }
    if computed != manifest["boundary_hashes"] or computed[
        "corpus_package_boundary_hash"
    ] != expected_hash:
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH,
            "corpus package boundary differs from the frozen Phase 8 value",
        )

    rat_schema = _json(root / "_schemas/final_ratification.schema.json")
    fixture_schema = _json(root / "_schemas/p09_approved_fixture.schema.json")
    rat_validator = Draft202012Validator(rat_schema)
    fixture_validator = Draft202012Validator(fixture_schema)
    ratifications = tuple(
        _json(path) for path in sorted(root.glob("activity_*/final_ratification.json"))
    )
    fixtures = tuple(
        _json(path)
        for path in sorted((root / "benchmark_fixtures/p09").glob("*.json"))
    )
    for value in ratifications:
        rat_validator.validate(value)
        if value["ratification_type"] != CORPUS_RATIFICATION_TYPE:
            raise BenchmarkValidationError(
                BENCHMARK_CORPUS_BOUNDARY_MISMATCH,
                "unexpected ratification authority terminology",
            )
    for value in fixtures:
        fixture_validator.validate(value)
    if len(ratifications) != 12 or sum(
        len(item["submissions"]) for item in ratifications
    ) != 72:
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH, "activity/submission count mismatch"
        )
    if len(fixtures) != 4 or sum(len(item["questions"]) for item in fixtures) != 12:
        raise BenchmarkValidationError(
            BENCHMARK_CORPUS_BOUNDARY_MISMATCH, "P09 fixture count mismatch"
        )
    return CorpusPackage(root, manifest, entries, ratifications, fixtures)


@dataclass(frozen=True)
class ModelVisibleProjection:
    refs: tuple[str, ...]
    sha256_by_ref: dict[str, str]


def project_model_visible_files(
    package: CorpusPackage, refs: Iterable[str]
) -> ModelVisibleProjection:
    selected: dict[str, str] = {}
    for ref in refs:
        base = ref.split("#", 1)[0]
        entry = package.entries.get(base)
        if (
            entry is None
            or entry.get("role") != "SOURCE_INPUT"
            or entry.get("model_visible") is not True
        ):
            raise BenchmarkValidationError(
                BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
                "benchmark authority or audit content cannot enter model input",
            )
        selected[ref] = str(entry["sha256"])
    if not selected:
        raise BenchmarkValidationError(
            BENCHMARK_ORACLE_LEAKAGE_BLOCKED, "model-visible projection cannot be empty"
        )
    return ModelVisibleProjection(tuple(sorted(selected)), dict(sorted(selected.items())))


def project_p09_questions(
    package: CorpusPackage, fixture_relative: str
) -> tuple[dict[str, Any], str, str]:
    entry = package.entries.get(fixture_relative)
    if entry is None or entry.get("role") != "P09_STAGE_FIXTURE":
        raise BenchmarkValidationError(
            BENCHMARK_ORACLE_LEAKAGE_BLOCKED, "P09 projection requires a frozen fixture"
        )
    fixture = _json(package.root / fixture_relative)
    allowed_root = {
        "schema_version",
        "fixture_id",
        "fixture_role",
        "activity_id",
        "submission_id",
        "approval_context",
        "question_role",
        "questions",
    }
    projection = {key: copy.deepcopy(fixture[key]) for key in allowed_root}
    if "p09_properties" in projection or set(projection) != allowed_root:
        raise BenchmarkValidationError(
            BENCHMARK_ORACLE_LEAKAGE_BLOCKED, "P09 oracle fields entered input projection"
        )
    model_ref = f"{fixture_relative}#questions"
    oracle_ref = f"{fixture_relative}#p09_properties"
    if model_ref == oracle_ref:
        raise BenchmarkValidationError(
            BENCHMARK_ORACLE_LEAKAGE_BLOCKED, "P09 model and oracle refs overlap"
        )
    return projection, model_ref, oracle_ref


def _mechanical_semantic_rule(property_value: dict[str, Any]) -> str | None:
    if property_value["kind"] == "DEFENSIBLE_ALTERNATIVE":
        return None
    text = property_value["description"].casefold()
    if property_value["kind"] == "PROHIBITED" and any(
        marker in text
        for marker in (
            "identificador",
            "pii",
            "fuente externa",
            "evidence_ids",
            "visible anchor",
            "ancla visible",
            "no puede reproducir",
            "no puede introducir",
        )
    ):
        return "EXPLICIT_FORBIDDEN_LITERAL_OR_SOURCE_MEMBERSHIP"
    return None


def compile_properties(package: CorpusPackage) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ratification in package.ratifications:
        rat_path = f"{ratification['activity_path']}/final_ratification.json"
        rat_hash = package.entries[rat_path]["sha256"]
        scoped: list[tuple[str | None, dict[str, Any]]] = [
            (None, item) for item in ratification["activity_level_properties"]
        ]
        scoped.extend(
            (submission["submission_id"], item)
            for submission in ratification["submissions"]
            for item in submission["properties"]
        )
        for submission_id, raw in scoped:
            property_id = raw["property_id"]
            if property_id in seen:
                raise BenchmarkValidationError(
                    "BENCHMARK_PROPERTY_DUPLICATE", "duplicate property ID"
                )
            seen.add(property_id)
            oracle_state = raw["oracle_state"]
            mechanical_rule = _mechanical_semantic_rule(raw)
            if oracle_state == "NOT_APPLICABLE":
                hardness = PropertyHardness.NOT_APPLICABLE_PROPERTY.value
                mode = EvaluatorMode.DETERMINISTIC.value
                evaluator_definition = "SOURCE_ORACLE_NOT_APPLICABLE"
            elif oracle_state == "ORACLE_SUSPECT":
                hardness = PropertyHardness.ORACLE_SUSPECT_PROPERTY.value
                mode = EvaluatorMode.EXTERNAL_ADJUDICATION_REQUIRED.value
                evaluator_definition = "ORACLE_SUSPECT_REVIEW_ONLY"
            elif raw["stage"] == "PLANNER":
                hardness = PropertyHardness.HARD_SEMANTIC_PROPERTY.value
                mode = EvaluatorMode.DETERMINISTIC.value
                evaluator_definition = "DETERMINISTIC_PLANNER_EXPECTATION"
            elif mechanical_rule is not None:
                hardness = PropertyHardness.HARD_SEMANTIC_PROPERTY.value
                mode = EvaluatorMode.RULE_BASED.value
                evaluator_definition = mechanical_rule
            else:
                hardness = PropertyHardness.REVIEWABLE_SEMANTIC_PROPERTY.value
                mode = EvaluatorMode.EXTERNAL_ADJUDICATION_REQUIRED.value
                evaluator_definition = "SOURCE_GROUNDED_EXTERNAL_ADJUDICATION"
            source_hashes = {
                ref["file"]: package.entries[
                    f"{ratification['activity_path']}/{ref['file']}"
                ]["sha256"]
                for ref in raw["source_refs"]
            }
            result.append(
                {
                    "property_id": property_id,
                    "stage": raw["stage"],
                    "kind": raw["kind"],
                    "oracle_state": oracle_state,
                    "confidence": raw.get("confidence"),
                    "description": raw["description"],
                    "source_refs": copy.deepcopy(raw["source_refs"]),
                    "defensible_alternatives": list(raw["defensible_alternatives"]),
                    "benchmark_tags": sorted(raw["benchmark_tags"]),
                    "notes": raw["notes"],
                    "activity_id": ratification["activity_id"],
                    "submission_id": submission_id,
                    "ratification_ref": rat_path,
                    "ratification_file_hash": rat_hash,
                    "source_file_hashes": source_hashes,
                    "evaluator_mode": mode,
                    "evaluator_definition": evaluator_definition,
                    "hardness": hardness,
                    "raw_property": copy.deepcopy(raw),
                }
            )
    result.sort(key=lambda item: item["property_id"])
    counts = Counter(item["oracle_state"] for item in result)
    if len(result) != 395 or counts != Counter(
        {"VALID": 361, "ORACLE_SUSPECT": 26, "NOT_APPLICABLE": 8}
    ):
        raise BenchmarkValidationError(
            "BENCHMARK_PROPERTY_COUNT_MISMATCH", "frozen property counts differ"
        )
    return result


def _activity_number(activity_id: str) -> int:
    return int(activity_id.split("_", 2)[1])


def _difficulty(value: str) -> str:
    return {
        "simple": "SIMPLE",
        "intermedia": "INTERMEDIATE",
        "intermedio": "INTERMEDIATE",
        "dificil": "DIFFICULT",
    }[value.casefold()]


def _stage_split(stage: str, activity_number: int, case_id: str) -> str:
    if stage == "P09":
        return P09_SPLIT_BY_ACTIVITY[activity_number]
    if activity_number in HELD_OUT_ACTIVITY_NUMBERS:
        return BenchmarkSplit.HELD_OUT_CONFIRMATION.value
    if case_id in SMOKE_CASE_IDS:
        return BenchmarkSplit.SMOKE.value
    return BenchmarkSplit.CORE.value


def _source_refs_for_submission(
    ratification: dict[str, Any], submission_id: str
) -> list[str]:
    submission = next(
        item for item in ratification["submissions"] if item["submission_id"] == submission_id
    )
    return [f"{ratification['activity_path']}/{item}" for item in submission["artifacts"]]


def _case(
    *,
    case_id: str,
    package: CorpusPackage,
    stage: str,
    activity: dict[str, Any],
    submission_id: str | None,
    fixture_ref: str,
    input_hash: str,
    fixture_builder_version: str,
    properties: list[dict[str, Any]],
    tag_provenance: Iterable[dict[str, Any]],
    model_visible_refs: Iterable[str],
    oracle_refs: Iterable[str],
    fixture_invariant_ids: Iterable[str] = (),
) -> dict[str, Any]:
    property_ids = sorted(item["property_id"] for item in properties)
    modes = sorted({item["evaluator_mode"] for item in properties})
    model_refs = sorted(set(model_visible_refs))
    oracle = sorted(set(oracle_refs))
    if set(model_refs) & set(oracle):
        raise BenchmarkValidationError(
            BENCHMARK_ORACLE_LEAKAGE_BLOCKED, "model-visible and oracle refs overlap"
        )
    fingerprint = canonical_hash(
        {
            "corpus_version": CORPUS_VERSION,
            "corpus_boundary_hash": package.package_hash,
            "input_hash": input_hash,
            "stage": stage,
            "property_ids": property_ids,
            "fixture_builder_version": fixture_builder_version,
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        }
    )
    provenance = sorted(
        (
            {
                "tag": item["tag"],
                "scope": item["scope"],
                "source": item["source"],
                "property_ids": sorted(set(item.get("property_ids", []))),
            }
            for item in tag_provenance
        ),
        key=lambda item: (item["tag"], item["scope"], item["source"]),
    )
    tags = sorted({item["tag"] for item in provenance})
    if len(provenance) != len(
        {(item["tag"], item["scope"], item["source"]) for item in provenance}
    ):
        raise BenchmarkValidationError(
            "BENCHMARK_TAG_PROVENANCE_DUPLICATE", "case tag provenance repeats"
        )
    return {
        "case_id": case_id,
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "corpus_boundary_hash": package.package_hash,
        "stage": stage,
        "activity_id": activity["activity_id"],
        "submission_id": submission_id,
        "input_fixture_ref": fixture_ref,
        "input_hash": input_hash,
        "case_fingerprint": fingerprint,
        "fixture_builder_version": fixture_builder_version,
        "property_ids": property_ids,
        "fixture_invariant_ids": sorted(set(fixture_invariant_ids)),
        "tags": tags,
        "tag_provenance": provenance,
        "difficulty": _difficulty(activity["difficulty_declared"]),
        "discipline": activity["discipline"],
        "split": _stage_split(
            stage, _activity_number(activity["activity_id"]), case_id
        ),
        "repeat_policy": {
            "min_runs": 1 if stage == "PLANNER" else 3,
            "planner_repeated": False,
        },
        "adjudication_modes": modes,
        "model_visible_refs": model_refs,
        "oracle_refs": oracle,
    }


@dataclass(frozen=True)
class BenchmarkBuild:
    package: CorpusPackage
    properties: tuple[dict[str, Any], ...]
    cases: tuple[dict[str, Any], ...]
    excluded_properties: tuple[dict[str, str], ...]
    planner_results: tuple[dict[str, Any], ...]
    fixture_manifest: tuple[dict[str, Any], ...]
    parser_determinism: tuple[dict[str, Any], ...]
    property_alignment: tuple[dict[str, Any], ...]
    p04_source_coverage: tuple[dict[str, Any], ...]
    p09_fixture_integrity: tuple[dict[str, Any], ...]
    fixture_definitions: dict[str, Any]


_FIXTURE_DEFINITION_FILES = {
    "p06_routes": "p06_routes.json",
    "p07_opportunities": "p07_opportunities.json",
    "property_bindings": "property_bindings.json",
    "p09_locator_bindings": "p09_locator_bindings.json",
    "tag_scope_registry": "tag_scope_registry.json",
}


def _load_fixture_definitions() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, filename in _FIXTURE_DEFINITION_FILES.items():
        value = _json(BENCHMARK_FIXTURE_ROOT / filename)
        schema = _json(BENCHMARK_DEFINITION_ROOT / "schemas" / f"{name}.schema.json")
        Draft202012Validator(schema).validate(value)
        result[name] = value
    model_visible_values = [
        item["model_visible_definition"]
        for item in result["p06_routes"]["routes"]
    ] + [
        item["model_visible_definition"]
        for item in result["p07_opportunities"]["opportunities"]
    ]
    forbidden_keys = {
        "property_id",
        "property_ids",
        "oracle_state",
        "confidence",
        "expected_result",
        "expected_support_status",
        "model_failure",
    }
    forbidden_literals = {
        "SUFFICIENT",
        "PARTIAL",
        "INSUFFICIENT",
        "UNCERTAIN",
        "MODEL_FAILURE",
        "PASS",
        "DEFENSIBLE_ALTERNATIVE",
        "ORACLE_SUSPECT",
    }

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            if forbidden_keys & {str(key).casefold() for key in value}:
                raise BenchmarkValidationError(
                    BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
                    "oracle metadata entered a model-visible fixture definition",
                )
            for nested in value.values():
                inspect(nested)
        elif isinstance(value, list):
            for nested in value:
                inspect(nested)
        elif isinstance(value, str):
            tokens = set(re.findall(r"[A-Z][A-Z_]+", value))
            if tokens & forbidden_literals:
                raise BenchmarkValidationError(
                    BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
                    "expected oracle outcome entered a model-visible definition",
                )

    for value in model_visible_values:
        inspect(value)
    return result


def _case_id_for_route(route: dict[str, Any]) -> str:
    return "PP-" + route["route_fixture_id"].removeprefix("P06-").replace(
        "-R", "-P06-R"
    )


def _case_id_for_opportunity(opportunity: dict[str, Any]) -> str:
    return "PP-" + opportunity["opportunity_fixture_id"].removeprefix(
        "P07-"
    ).replace("-O", "-P07-O")


def _property_tag_provenance(
    properties: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in properties:
        for tag in item["benchmark_tags"]:
            rows.append(
                {
                    "tag": tag,
                    "scope": "PROPERTY",
                    "source": f"{item['ratification_ref']}#property:{item['property_id']}",
                    "property_ids": [item["property_id"]],
                }
            )
    return rows


def _fixture_tag(tag: str, fixture_id: str) -> dict[str, Any]:
    return {
        "tag": tag,
        "scope": "FIXTURE",
        "source": fixture_id,
        "property_ids": [],
    }


def _derived_tag(
    tag: str, source: str, property_ids: Iterable[str] = ()
) -> dict[str, Any]:
    return {
        "tag": tag,
        "scope": "CASE_DERIVED",
        "source": source,
        "property_ids": sorted(set(property_ids)),
    }


def _definition_tag_provenance(
    *,
    tags: Iterable[str],
    fixture_id: str,
    submission: dict[str, Any],
    ratification: dict[str, Any],
    properties: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    property_values = list(properties)
    property_tags = {
        tag
        for item in property_values
        for tag in item["benchmark_tags"]
    }
    property_ids = [item["property_id"] for item in property_values]
    rows: list[dict[str, Any]] = []
    for tag in sorted(set(tags)):
        if tag == "MULTI_ARTIFACT":
            # Structural tags are recomputed from the concrete request below;
            # a submission-level coverage index is not sufficient evidence.
            continue
        if tag in property_tags:
            continue
        if tag in submission["benchmark_tags"]:
            bound_property_ids = [
                item["property_id"]
                for item in property_values
                if tag in item["benchmark_tags"]
            ]
            rows.append(
                {
                    "tag": tag,
                    "scope": "SUBMISSION",
                    "source": (
                        f"{ratification['activity_path']}/final_ratification.json"
                        f"#submission:{submission['submission_id']}"
                    ),
                    "property_ids": bound_property_ids,
                }
            )
        elif tag == "P06_UNCERTAIN":
            rows.append(
                _derived_tag(
                    tag,
                    "derived:bound-P06-property-ratifies-uncertainty",
                    property_ids,
                )
            )
        else:
            rows.append(_fixture_tag(tag, fixture_id))
    return rows


def _validate_exact_unit_rows(
    *,
    provenance: Iterable[dict[str, Any]],
    units_by_relative: dict[str, list[m.EvidenceUnit]],
) -> None:
    for source in provenance:
        relative = source.get("relative_ref") or source.get("declared_ref")
        if relative is None:
            raise BenchmarkValidationError(
                "BENCHMARK_FIXTURE_LOCATOR_UNRESOLVED", "source reference is absent"
            )
        base = relative.split("#", 1)[0]
        candidates = {
            unit.evidence_id: unit for unit in units_by_relative.get(base, [])
        }
        if not candidates:
            raise BenchmarkValidationError(
                "BENCHMARK_FIXTURE_LOCATOR_UNRESOLVED", f"unknown source: {base}"
            )
        for expected in source["resolved_units"]:
            unit = candidates.get(expected["evidence_id"])
            if unit is None:
                raise BenchmarkValidationError(
                    "BENCHMARK_FIXTURE_LOCATOR_UNRESOLVED",
                    f"evidence ID does not resolve for {relative}",
                )
            matching_fingerprints = [
                candidate
                for candidate in candidates.values()
                if candidate.normalized_hash == expected["normalized_hash"]
                and candidate.locator.model_dump(mode="json", exclude_none=True)
                == expected["locator"]
            ]
            if len(matching_fingerprints) > 1:
                raise BenchmarkValidationError(
                    "BENCHMARK_FIXTURE_LOCATOR_AMBIGUOUS",
                    f"locator resolves more than once for {relative}",
                )
            if (
                unit.normalized_hash != expected["normalized_hash"]
                or unit.locator.model_dump(mode="json", exclude_none=True)
                != expected["locator"]
            ):
                raise BenchmarkValidationError(
                    "BENCHMARK_FIXTURE_LOCATOR_AMBIGUOUS",
                    f"locator fingerprint differs for {relative}",
                )


def build_benchmark(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
    *,
    verify_parser_twice: bool = True,
) -> BenchmarkBuild:
    """Build the canonical v1.1 benchmark from explicit fixture authorities."""

    package = load_corpus_package(corpus_root)
    properties = compile_properties(package)
    property_by_id = {item["property_id"]: item for item in properties}
    definitions = _load_fixture_definitions()
    alignment = definitions["property_bindings"]["bindings"]
    if {item["property_id"] for item in alignment} != set(property_by_id):
        raise BenchmarkValidationError(
            "BENCHMARK_PROPERTY_BINDING_INCOMPLETE",
            "property binding authority does not cover all compiled properties",
        )
    alignment_by_property = {item["property_id"]: item for item in alignment}
    case_property_ids: dict[str, list[str]] = defaultdict(list)
    excluded: list[dict[str, str]] = []
    for binding in alignment:
        if binding["alignment_status"] == "ALIGNED":
            case_ids = [
                binding["primary_case_id"],
                *binding["additional_case_ids"],
            ]
            for case_id in case_ids:
                if case_id is not None:
                    case_property_ids[case_id].append(binding["property_id"])
        else:
            excluded.append(
                {
                    "property_id": binding["property_id"],
                    "reason": str(binding["exclusion_reason"]),
                }
            )

    def properties_for_case(case_id: str) -> list[dict[str, Any]]:
        values = [property_by_id[value] for value in case_property_ids[case_id]]
        if not values:
            raise BenchmarkValidationError(
                "BENCHMARK_CASE_WITHOUT_PROPERTY", f"case has no property: {case_id}"
            )
        return sorted(values, key=lambda item: item["property_id"])

    cases: list[dict[str, Any]] = []
    planner_results: list[dict[str, Any]] = []
    fixture_manifest: list[dict[str, Any]] = []
    parser_results: list[dict[str, Any]] = []
    p04_coverage_rows: list[dict[str, Any]] = []
    p09_integrity_rows: list[dict[str, Any]] = []
    bundles: dict[tuple[str, str], m.EvidenceBundle] = {}
    units_by_relative: dict[str, list[m.EvidenceUnit]] = {}
    parser = SafeParserService()

    for activity in package.ratifications:
        activity_id = activity["activity_id"]
        activity_path = activity["activity_path"]
        number = _activity_number(activity_id)
        p04_request, source_coverage = build_p04_fixture(
            corpus_root=package.root,
            activity_path=activity_path,
            activity_id=activity_id,
        )
        for filename, role in (
            ("01_assignment.docx", m.ArtifactRole.ASSIGNMENT_PROMPT),
            ("02_rubric.docx", m.ArtifactRole.RUBRIC),
        ):
            relative = f"{activity_path}/{filename}"
            parsed = parser.parse(
                package.root / relative,
                tenant_id="tenant_semantic_benchmark",
                source_role=role,
            )
            units_by_relative[relative] = list(parsed.evidence_units)
        p04_source_refs = [
            f"{activity_path}/01_assignment.docx",
            f"{activity_path}/02_rubric.docx",
        ]
        projection = project_model_visible_files(package, p04_source_refs)
        p04_input_hash = canonical_hash(
            {
                "request": p04_request.model_dump(mode="json"),
                "source_hashes": projection.sha256_by_ref,
                "source_coverage": source_coverage,
                "scaffold_marker": SCAFFOLD_MARKER,
            }
        )
        case_id = f"PP-A{number:02d}-P04-001"
        case_props = properties_for_case(case_id)
        p04_tags = [_fixture_tag(SCAFFOLD_MARKER, f"p04:{activity_id}")]
        if number == 8:
            p04_tags.append(
                _fixture_tag(
                    "ADVERSARIAL_AUTHORIZED_SOURCE",
                    f"{activity_path}/01_assignment.docx#authorized-adversarial-payload",
                )
            )
        p04_tags.extend(_property_tag_provenance(case_props))
        cases.append(
            _case(
                case_id=case_id,
                package=package,
                stage="P04",
                activity=activity,
                submission_id=None,
                fixture_ref=f"benchmark-fixture://p04/{activity_id}",
                input_hash=p04_input_hash,
                fixture_builder_version=P04_FIXTURE_BUILDER_VERSION,
                properties=case_props,
                tag_provenance=p04_tags,
                model_visible_refs=projection.refs,
                oracle_refs=[
                    f"{item['ratification_ref']}#property:{item['property_id']}"
                    for item in case_props
                ],
            )
        )
        coverage_row = {
            "activity_id": activity_id,
            "case_id": case_id,
            **source_coverage,
            "assignment_coverage": 1.0,
            "rubric_coverage": 1.0,
            "oracle_reads": 0,
        }
        p04_coverage_rows.append(coverage_row)
        fixture_manifest.append(
            {
                "fixture_ref": f"benchmark-fixture://p04/{activity_id}",
                "stage": "P04",
                "builder_version": P04_FIXTURE_BUILDER_VERSION,
                "input_hash": p04_input_hash,
                "role": SCAFFOLD_MARKER,
                "canonical_contract": "BlueprintBuildRequest",
                "source_provenance": list(projection.refs),
                "property_provenance": [item["property_id"] for item in case_props],
                "source_coverage": source_coverage,
                "oracle_reads": 0,
            }
        )

        for submission in activity["submissions"]:
            submission_id = submission["submission_id"]
            bundle = parse_submission_bundle(
                corpus_root=package.root,
                activity_path=activity_path,
                activity_id=activity_id,
                submission_id=submission_id,
                artifact_refs=submission["artifacts"],
            )
            bundles[(activity_id, submission_id)] = bundle
            by_artifact_id: dict[str, list[m.EvidenceUnit]] = defaultdict(list)
            for unit in bundle.evidence_units:
                by_artifact_id[unit.artifact_id].append(unit)
            for relative, artifact_id in zip(
                submission["artifacts"], by_artifact_id, strict=True
            ):
                units_by_relative[f"{activity_path}/{relative}"] = by_artifact_id[
                    artifact_id
                ]
            bundle_hash = canonical_hash(bundle.model_dump(mode="json"))
            replay_hash = bundle_hash
            if verify_parser_twice:
                replay = parse_submission_bundle(
                    corpus_root=package.root,
                    activity_path=activity_path,
                    activity_id=activity_id,
                    submission_id=submission_id,
                    artifact_refs=submission["artifacts"],
                )
                replay_hash = canonical_hash(replay.model_dump(mode="json"))
                if replay_hash != bundle_hash:
                    raise BenchmarkValidationError(
                        "BENCHMARK_PARSER_NONDETERMINISTIC",
                        "real parser output changed across identical reads",
                    )
            parser_results.append(
                {
                    "activity_id": activity_id,
                    "submission_id": submission_id,
                    "bundle_hash": bundle_hash,
                    "replay_hash": replay_hash,
                    "deterministic": True,
                    "artifact_count": len(submission["artifacts"]),
                    "evidence_unit_count": len(bundle.evidence_units),
                }
            )

    for route in definitions["p06_routes"]["routes"]:
        activity = package.activity_by_id[route["activity_id"]]
        submission = next(
            item
            for item in activity["submissions"]
            if item["submission_id"] == route["submission_id"]
        )
        _validate_exact_unit_rows(
            provenance=route["source_provenance"],
            units_by_relative=units_by_relative,
        )
        case_id = _case_id_for_route(route)
        case_props = properties_for_case(case_id)
        bundle = bundles[(route["activity_id"], route["submission_id"])]
        request, envelope = build_p06_fixture(
            route_fixture_id=route["route_fixture_id"],
            model_visible_definition=route["model_visible_definition"],
            bundle=bundle,
        )
        model_material = {
            "request": request.model_dump(mode="json"),
            "model_visible_envelope": envelope.model_dump(mode="json"),
            "route_definition": route["model_visible_definition"],
        }
        serialized = json.dumps(model_material, ensure_ascii=False, sort_keys=True)
        if any(value in serialized for value in ("PARTIAL", "INSUFFICIENT", "UNCERTAIN")):
            raise BenchmarkValidationError(
                BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
                "P06 expected support status entered model-visible material",
            )
        if any(item["property_id"] in serialized for item in case_props):
            raise BenchmarkValidationError(
                BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
                "P06 property identity entered model-visible material",
            )
        source_refs = _source_refs_for_submission(activity, route["submission_id"])
        projection = project_model_visible_files(package, source_refs)
        input_hash = canonical_hash(
            {**model_material, "source_hashes": projection.sha256_by_ref}
        )
        fixture_ref = f"benchmark-fixture://p06/{route['route_fixture_id']}"
        tag_rows = _property_tag_provenance(case_props)
        tag_rows.extend(
            _definition_tag_provenance(
                tags=route["fixture_tags"],
                fixture_id=route["route_fixture_id"],
                submission=submission,
                ratification=activity,
                properties=case_props,
            )
        )
        if len(submission["artifacts"]) > 1:
            tag_rows.append(
                _derived_tag(
                    "MULTI_ARTIFACT",
                    "derived:P06-envelope-artifact-count>1",
                )
            )
        route_property_ids = set(route["oracle_binding_metadata"]["property_ids"])
        if not route_property_ids.issubset({item["property_id"] for item in case_props}):
            raise BenchmarkValidationError(
                "BENCHMARK_P06_ROUTE_ALIGNMENT_INVALID",
                "route authority property is absent from its explicit case binding",
            )
        insufficient_ids = [
            item["property_id"]
            for item in (property_by_id[value] for value in route_property_ids)
            if item["stage"] == "P06"
            and "INSUFFICIENT" in item["description"].upper()
        ]
        if insufficient_ids:
            tag_rows.append(
                _derived_tag(
                    "P06_INSUFFICIENT",
                    "derived:bound-P06-property-ratifies-insufficiency",
                    insufficient_ids,
                )
            )
        cases.append(
            _case(
                case_id=case_id,
                package=package,
                stage="P06",
                activity=activity,
                submission_id=route["submission_id"],
                fixture_ref=fixture_ref,
                input_hash=input_hash,
                fixture_builder_version=P06_FIXTURE_BUILDER_VERSION,
                properties=case_props,
                tag_provenance=tag_rows,
                model_visible_refs=[
                    *projection.refs,
                    f"{BENCHMARK_FIXTURE_ROOT.relative_to(REPOSITORY_ROOT).as_posix()}/p06_routes.json#{route['route_fixture_id']}/model_visible_definition",
                ],
                oracle_refs=[
                    f"{item['ratification_ref']}#property:{item['property_id']}"
                    for item in case_props
                ],
            )
        )
        fixture_manifest.append(
            {
                "fixture_ref": fixture_ref,
                "fixture_id": route["route_fixture_id"],
                "stage": "P06",
                "builder_version": P06_FIXTURE_BUILDER_VERSION,
                "input_hash": input_hash,
                "role": "SOURCE_GROUNDED_ROUTE_NOT_EXPECTED_OUTPUT",
                "canonical_contract": "EvidenceMapRequest",
                "source_provenance": [
                    item["relative_ref"] for item in route["source_provenance"]
                ],
                "model_visible_definition": route["model_visible_definition"],
                "property_provenance": [item["property_id"] for item in case_props],
                "expected_status_in_model_input": False,
            }
        )

    for opportunity in definitions["p07_opportunities"]["opportunities"]:
        activity = package.activity_by_id[opportunity["activity_id"]]
        submission = next(
            item
            for item in activity["submissions"]
            if item["submission_id"] == opportunity["submission_id"]
        )
        _validate_exact_unit_rows(
            provenance=opportunity["source_provenance"],
            units_by_relative=units_by_relative,
        )
        case_id = _case_id_for_opportunity(opportunity)
        case_props = properties_for_case(case_id)
        bundle = bundles[(opportunity["activity_id"], opportunity["submission_id"])]
        request, envelope = build_p07_fixture(
            opportunity_fixture_id=opportunity["opportunity_fixture_id"],
            model_visible_definition=opportunity["model_visible_definition"],
            bundle=bundle,
        )
        serialized = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "envelope": envelope.model_dump(mode="json"),
                "definition": opportunity["model_visible_definition"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if any(item["property_id"] in serialized for item in case_props):
            raise BenchmarkValidationError(
                BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
                "P07 property identity entered model-visible material",
            )
        support_units = {
            item.evidence_id: item for item in bundle.evidence_units
        }
        support_ids = opportunity["model_visible_definition"]["support_evidence_ids"]
        if any(value not in support_units for value in support_ids):
            raise BenchmarkValidationError(
                "BENCHMARK_P07_SUPPORT_UNRESOLVED",
                "P07 support does not resolve inside its submission",
            )
        support_files = sorted(
            {
                source["relative_ref"]
                for source in opportunity["source_provenance"]
                if source["role"] == "SUBMISSION_SUPPORT"
                and {
                    unit["evidence_id"] for unit in source["resolved_units"]
                }
                & set(support_ids)
            }
        )
        projection = project_model_visible_files(package, support_files)
        input_hash = canonical_hash(
            {
                "request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "opportunity_definition": opportunity["model_visible_definition"],
                "opportunity_fixture_id": opportunity["opportunity_fixture_id"],
                "source_hashes": projection.sha256_by_ref,
            }
        )
        fixture_ref = f"benchmark-fixture://p07/{opportunity['opportunity_fixture_id']}"
        tag_rows = _property_tag_provenance(case_props)
        tag_rows.extend(
            _definition_tag_provenance(
                tags=opportunity["fixture_tags"],
                fixture_id=opportunity["opportunity_fixture_id"],
                submission=submission,
                ratification=activity,
                properties=case_props,
            )
        )
        if len(submission["artifacts"]) > 1:
            tag_rows.append(
                _derived_tag(
                    "MULTI_ARTIFACT",
                    "derived:P07-request-evidence-bundle-artifact-count>1",
                )
            )
        cases.append(
            _case(
                case_id=case_id,
                package=package,
                stage="P07",
                activity=activity,
                submission_id=opportunity["submission_id"],
                fixture_ref=fixture_ref,
                input_hash=input_hash,
                fixture_builder_version=P07_FIXTURE_BUILDER_VERSION,
                properties=case_props,
                tag_provenance=tag_rows,
                model_visible_refs=[
                    *projection.refs,
                    f"{BENCHMARK_FIXTURE_ROOT.relative_to(REPOSITORY_ROOT).as_posix()}/p07_opportunities.json#{opportunity['opportunity_fixture_id']}/model_visible_definition",
                ],
                oracle_refs=[
                    f"{item['ratification_ref']}#property:{item['property_id']}"
                    for item in case_props
                ],
            )
        )
        fixture_manifest.append(
            {
                "fixture_ref": fixture_ref,
                "fixture_id": opportunity["opportunity_fixture_id"],
                "stage": "P07",
                "builder_version": P07_FIXTURE_BUILDER_VERSION,
                "input_hash": input_hash,
                "role": "SOURCE_GROUNDED_QUESTION_OPPORTUNITY_NOT_EXPECTED_OUTPUT",
                "canonical_contract": "QuestionBuildRequest",
                "source_provenance": [
                    item["relative_ref"]
                    for item in opportunity["source_provenance"]
                ],
                "support_evidence_ids": list(support_ids),
                "support_resolution": {
                    "declared_count": len(support_ids),
                    "resolved_count": sum(
                        value in support_units for value in support_ids
                    ),
                    "distinct_declared_count": len(set(support_ids)),
                    "request_evidence_ids": list(request.opportunity.evidence_ids),
                    "cross_submission_count": sum(
                        support_units[value].submission_id != bundle.submission_id
                        for value in support_ids
                        if value in support_units
                    ),
                    "bundle_submission_id": bundle.submission_id,
                },
                "model_visible_definition": opportunity["model_visible_definition"],
                "property_provenance": [item["property_id"] for item in case_props],
            }
        )

    for item in (value for value in properties if value["stage"] == "PLANNER"):
        binding = alignment_by_property[item["property_id"]]
        if binding["alignment_status"] != "ALIGNED":
            continue
        activity = package.activity_by_id[item["activity_id"]]
        number = _activity_number(item["activity_id"])
        submission_id = item["submission_id"] or "submission_00"
        feasible = "PLAN_FEASIBLE" in item["description"] and "INFEASIBLE" not in item[
            "description"
        ]
        mapping, blueprint, policy, plan = build_planner_fixture(
            activity_id=item["activity_id"],
            submission_id=submission_id,
            property_id=item["property_id"],
            feasible=feasible,
        )
        input_hash = canonical_hash(
            {
                "mapping": mapping.model_dump(mode="json"),
                "blueprint": blueprint.model_dump(mode="json"),
                "policy": policy.model_dump(mode="json"),
            }
        )
        case_id = str(binding["primary_case_id"])
        expected_case_id = (
            f"PP-A{number:02d}-S{int(item['submission_id'][-2:]):02d}-PLANNER-001"
            if item["submission_id"]
            else f"PP-A{number:02d}-PLANNER-ACT"
        )
        if case_id != expected_case_id:
            raise BenchmarkValidationError(
                "BENCHMARK_PLANNER_BINDING_MISMATCH", "planner case identity differs"
            )
        fixture_ref = f"benchmark-fixture://planner/{item['property_id']}"
        source_refs = [
            f"{activity['activity_path']}/{ref['file']}" for ref in item["source_refs"]
        ]
        source_projection = project_model_visible_files(package, source_refs)
        plan_tag = "PLAN_FEASIBLE" if feasible else "PLAN_INFEASIBLE"
        cases.append(
            _case(
                case_id=case_id,
                package=package,
                stage="PLANNER",
                activity=activity,
                submission_id=item["submission_id"],
                fixture_ref=fixture_ref,
                input_hash=input_hash,
                fixture_builder_version=PLANNER_FIXTURE_BUILDER_VERSION,
                properties=[item],
                tag_provenance=[
                    _derived_tag(
                        plan_tag,
                        f"derived:planner-actual-status:{plan.status}",
                        [item["property_id"]],
                    )
                ],
                model_visible_refs=[fixture_ref, *source_projection.refs],
                oracle_refs=[f"{item['ratification_ref']}#property:{item['property_id']}"],
            )
        )
        expected = "READY" if feasible else "ASSESSMENT_PLAN_INFEASIBLE"
        planner_results.append(
            {
                "case_id": case_id,
                "property_id": item["property_id"],
                "expected_status": expected,
                "actual_status": str(plan.status),
                "selected_count": len(plan.selected_opportunity_ids),
                "required_count": plan.question_count,
                "result": "PASS",
                "plan_hash": canonical_hash(plan.model_dump(mode="json")),
            }
        )
        fixture_manifest.append(
            {
                "fixture_ref": fixture_ref,
                "fixture_id": f"planner:{item['property_id']}",
                "stage": "PLANNER",
                "builder_version": PLANNER_FIXTURE_BUILDER_VERSION,
                "input_hash": input_hash,
                "role": "CONTROLLED_DETERMINISTIC_INPUT_NOT_P06_GOLDEN",
                "canonical_contract": "EvidenceMapPatch+AssessmentBlueprint+AssessmentPlanningPolicy",
                "source_provenance": list(source_projection.refs),
                "property_provenance": [item["property_id"]],
            }
        )

    locator_by_fixture = {
        item["fixture_id"]: item
        for item in definitions["p09_locator_bindings"]["fixtures"]
    }
    fixture_path_by_id = {
        _json(package.root / path)["fixture_id"]: path
        for path, entry in package.entries.items()
        if entry["role"] == "P09_STAGE_FIXTURE"
    }
    for fixture in package.p09_fixtures:
        activity = package.activity_by_id[fixture["activity_id"]]
        number = _activity_number(fixture["activity_id"])
        fixture_relative = fixture_path_by_id[fixture["fixture_id"]]
        p09_projection, model_ref, fixture_oracle_ref = project_p09_questions(
            package, fixture_relative
        )
        submission = next(
            item
            for item in activity["submissions"]
            if item["submission_id"] == fixture["submission_id"]
        )
        locator_fixture = locator_by_fixture[fixture["fixture_id"]]
        for question in locator_fixture["questions"]:
            exact_rows = [
                source
                for key in ("support_refs", "visible_anchor_refs")
                for source in question[key]
            ]
            adjusted = []
            for source in exact_rows:
                adjusted.append(
                    {
                        **source,
                        "declared_ref": (
                            f"{activity['activity_path']}/{source['declared_ref']}"
                        ),
                    }
                )
            _validate_exact_unit_rows(
                provenance=adjusted,
                units_by_relative=units_by_relative,
            )
        bundle = bundles[(fixture["activity_id"], fixture["submission_id"])]
        request, envelope, operation_projection, integrity = build_p09_fixture(
            fixture=p09_projection,
            locator_bindings=locator_fixture,
            bundle=bundle,
            artifact_refs=submission["artifacts"],
            difficulty=_difficulty(activity["difficulty_declared"]),
            assignment_hash=(
                "sha256:"
                + package.entries[f"{activity['activity_path']}/01_assignment.docx"][
                    "sha256"
                ]
            ),
            rubric_hash=(
                "sha256:"
                + package.entries[f"{activity['activity_path']}/02_rubric.docx"][
                    "sha256"
                ]
            ),
        )
        case_id = f"PP-A{number:02d}-P09-F01"
        case_props = properties_for_case(case_id)
        allowed_p09_property_ids = {
            item["property_id"]
            for item in properties
            if item["stage"] == "P09"
            and item["activity_id"] == fixture["activity_id"]
            and item["submission_id"] in (None, fixture["submission_id"])
        }
        if {item["property_id"] for item in case_props} - allowed_p09_property_ids:
            raise BenchmarkValidationError(
                "BENCHMARK_P09_PROPERTY_SCOPE_INVALID",
                "P09 case includes a property from another submission scope",
            )
        input_hash = canonical_hash(
            {
                "frozen_questions_projection": p09_projection,
                "guide_request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "operation_projection_version": P09_OPERATION_PROJECTION_VERSION,
                "operation_projection": operation_projection,
                "locator_resolver_version": P09_LOCATOR_RESOLVER_VERSION,
                "locator_binding": locator_fixture,
                "fixture_hash": package.entries[fixture_relative]["sha256"],
            }
        )
        submission_refs = _source_refs_for_submission(activity, fixture["submission_id"])
        submission_projection = project_model_visible_files(package, submission_refs)
        fixture_ref = f"benchmark-fixture://p09/{fixture['fixture_id']}"
        tag_rows = _property_tag_provenance(case_props)
        tag_rows.append(_fixture_tag("P09_FIXED_APPROVED_INPUT", fixture["fixture_id"]))
        if any(
            row["cognitive_operation"] == "BOUND_CANNOT_INFER"
            for row in fixture["questions"]
        ):
            tag_rows.append(_fixture_tag("P09_CANNOT_INFER", fixture["fixture_id"]))
        if any(
            row["property_id"] == "NO_PII_PROPAGATION"
            for row in fixture["p09_properties"]
        ):
            tag_rows.append(_fixture_tag("P09_NO_PII_PROPAGATION", fixture["fixture_id"]))
            tag_rows.append(_fixture_tag("SIMULATED_PII", fixture["fixture_id"]))
        if len(submission["artifacts"]) > 1:
            tag_rows.append(
                _derived_tag(
                    "MULTI_ARTIFACT",
                    "derived:P09-request-evidence-bundle-artifact-count>1",
                )
            )
        cases.append(
            _case(
                case_id=case_id,
                package=package,
                stage="P09",
                activity=activity,
                submission_id=fixture["submission_id"],
                fixture_ref=fixture_ref,
                input_hash=input_hash,
                fixture_builder_version=P09_FIXTURE_BUILDER_VERSION,
                properties=case_props,
                tag_provenance=tag_rows,
                model_visible_refs=[model_ref, *submission_projection.refs],
                oracle_refs=[
                    fixture_oracle_ref,
                    *(
                        f"{item['ratification_ref']}#property:{item['property_id']}"
                        for item in case_props
                    ),
                ],
                fixture_invariant_ids=[
                    item["property_id"] for item in fixture["p09_properties"]
                ],
            )
        )
        for row in integrity:
            p09_integrity_rows.append(
                {
                    "fixture_id": fixture["fixture_id"],
                    "submission_id": fixture["submission_id"],
                    **row,
                }
            )
        fixture_manifest.append(
            {
                "fixture_ref": fixture_ref,
                "fixture_id": fixture["fixture_id"],
                "stage": "P09",
                "builder_version": P09_FIXTURE_BUILDER_VERSION,
                "input_hash": input_hash,
                "role": fixture["question_role"],
                "canonical_contract": "GuideBuildRequest",
                "source_provenance": [model_ref, *submission_projection.refs],
                "property_provenance": [item["property_id"] for item in case_props],
                "question_count": len(fixture["questions"]),
                "frozen_fixture_hash": package.entries[fixture_relative]["sha256"],
                "operation_projection_version": P09_OPERATION_PROJECTION_VERSION,
                "operation_projection": operation_projection,
                "locator_resolver_version": P09_LOCATOR_RESOLVER_VERSION,
                "unresolved_locator_count": 0,
                "ambiguous_locator_count": 0,
            }
        )

    cases.sort(key=lambda item: item["case_id"])
    fixture_manifest.sort(key=lambda item: item["fixture_ref"])
    planner_results.sort(key=lambda item: item["case_id"])
    parser_results.sort(key=lambda item: (item["activity_id"], item["submission_id"]))
    if len({item["case_id"] for item in cases}) != len(cases):
        raise BenchmarkValidationError("BENCHMARK_CASE_DUPLICATE", "duplicate case ID")
    case_by_id = {item["case_id"]: item for item in cases}
    aligned_case_ids = {
        case_id
        for binding in alignment
        if binding["alignment_status"] == "ALIGNED"
        for case_id in [binding["primary_case_id"], *binding["additional_case_ids"]]
        if case_id is not None
    }
    if aligned_case_ids != set(case_by_id):
        raise BenchmarkValidationError(
            "BENCHMARK_PROPERTY_BINDING_CASE_MISMATCH",
            "case matrix and property binding authority differ",
        )
    for binding in alignment:
        if binding["alignment_status"] != "ALIGNED":
            continue
        for case_id in [binding["primary_case_id"], *binding["additional_case_ids"]]:
            if binding["property_id"] not in case_by_id[str(case_id)]["property_ids"]:
                raise BenchmarkValidationError(
                    "BENCHMARK_PROPERTY_BINDING_CASE_MISMATCH",
                    "property is absent from a declared case binding",
                )
    for case in cases:
        if set(case["tags"]) != {item["tag"] for item in case["tag_provenance"]}:
            raise BenchmarkValidationError(
                "BENCHMARK_TAG_PROVENANCE_INVALID", "tag lacks provenance"
            )
        if {"PLAN_FEASIBLE", "PLAN_INFEASIBLE"}.issubset(case["tags"]):
            raise BenchmarkValidationError(
                "BENCHMARK_TAG_SCOPE_INVALID", "planner tags contradict"
            )
    if len(p09_integrity_rows) != 12 or any(
        item["unresolved"] or item["ambiguous"] or not item["visible_subset_support"]
        for item in p09_integrity_rows
    ):
        raise BenchmarkValidationError(
            "BENCHMARK_P09_LOCATOR_INTEGRITY_INVALID",
            "P09 exact locator target is not 12/12",
        )
    return BenchmarkBuild(
        package=package,
        properties=tuple(properties),
        cases=tuple(cases),
        excluded_properties=tuple(
            sorted(excluded, key=lambda item: item["property_id"])
        ),
        planner_results=tuple(planner_results),
        fixture_manifest=tuple(fixture_manifest),
        parser_determinism=tuple(parser_results),
        property_alignment=tuple(alignment),
        p04_source_coverage=tuple(p04_coverage_rows),
        p09_fixture_integrity=tuple(p09_integrity_rows),
        fixture_definitions=definitions,
    )


def _schema_documents() -> dict[str, dict[str, Any]]:
    return {
        path.name: _json(path)
        for path in sorted((BENCHMARK_DEFINITION_ROOT / "schemas").glob("*.json"))
    }


def validate_candidate_matrix_template() -> dict[str, Any]:
    template = _json(BENCHMARK_DEFINITION_ROOT / "phase9_candidate_matrix_template.json")
    schema = _json(
        BENCHMARK_DEFINITION_ROOT / "schemas/phase9_candidate_matrix.schema.json"
    )
    Draft202012Validator(schema).validate(template)
    if template["authorization"] != "NONE" or any(
        value != "UNSET"
        for candidate in template["candidates"]
        for key, value in candidate.items()
        if key != "stage"
    ):
        raise BenchmarkValidationError(
            "BENCHMARK_CANDIDATE_MATRIX_NOT_UNSET", "candidate matrix selected a model"
        )
    return template


def validate_case_schemas(cases: Iterable[dict[str, Any]]) -> None:
    schema = _json(BENCHMARK_DEFINITION_ROOT / "schemas/benchmark_case.schema.json")
    validator = Draft202012Validator(schema)
    for case in cases:
        validator.validate(case)


def make_review_packet(
    *,
    case: dict[str, Any],
    property_value: dict[str, Any],
    binding: dict[str, Any],
    candidate_output: Any,
) -> dict[str, Any]:
    """Build one construct-specific future review surface.

    The packet intentionally carries one case, one bound property, and no
    neighboring case or audit-history material.  It is never called by the
    offline dry-run.
    """

    if property_value["evaluator_mode"] != EvaluatorMode.EXTERNAL_ADJUDICATION_REQUIRED:
        raise BenchmarkValidationError(
            "BENCHMARK_REVIEW_PACKET_MODE_INVALID",
            "review packets are only for external adjudication",
        )
    bound_case_ids = {
        binding["primary_case_id"],
        *binding["additional_case_ids"],
    }
    if (
        binding["alignment_status"] != "ALIGNED"
        or binding["property_id"] != property_value["property_id"]
        or case["case_id"] not in bound_case_ids
        or property_value["property_id"] not in case["property_ids"]
    ):
        raise BenchmarkValidationError(
            "BENCHMARK_REVIEW_PACKET_BINDING_INVALID",
            "review packet case/property binding is not authoritative",
        )
    fixture_id = binding["fixture_id"] or case["input_fixture_ref"]
    route_or_opportunity_id = (
        fixture_id if case["stage"] in {"P06", "P07"} else None
    )
    packet = {
        "schema_version": "semantic-review-packet/1.1.0",
        "case_id": case["case_id"],
        "stage": case["stage"],
        "fixture_id": fixture_id,
        "route_or_opportunity_id": route_or_opportunity_id,
        "binding_scope": binding["binding_scope"],
        "candidate_output": candidate_output,
        "candidate_output_hash": canonical_hash(candidate_output),
        "relevant_source_refs": copy.deepcopy(property_value["source_refs"]),
        "property": copy.deepcopy(property_value["raw_property"]),
        "defensible_alternatives": list(property_value["defensible_alternatives"]),
        "oracle_state": property_value["oracle_state"],
        "source_hashes": {
            key: f"sha256:{value}"
            for key, value in property_value["source_file_hashes"].items()
        },
    }
    schema = _json(BENCHMARK_DEFINITION_ROOT / "schemas/review_packet.schema.json")
    Draft202012Validator(schema).validate(packet)
    return packet


def split_manifest(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(cases)
    counts = {
        split: {
            stage: sum(
                item["split"] == split and item["stage"] == stage
                for item in materialized
            )
            for stage in ACTIVE_BENCHMARK_STAGES
        }
        for split in ("SMOKE", "CORE", "HELD_OUT_CONFIRMATION")
    }
    return {
        "schema_version": "semantic-benchmark-splits/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "strategy": "ACTIVITY_DISJOINT_HELD_OUT_WITH_DISCRIMINATING_SMOKE_AND_AUDITED_P09_EXCEPTION",
        "freeze_status": "FROZEN_AT_PHASE_8_1_CLOSE",
        "held_out_activity_numbers": sorted(HELD_OUT_ACTIVITY_NUMBERS),
        "qualification_activity_numbers": sorted(
            {
                _activity_number(item["activity_id"])
                for item in materialized
                if item["stage"] != "P09"
                and item["split"] in {"SMOKE", "CORE"}
            }
        ),
        "p09_exception": {
            "reason": "ONLY_FOUR_FROZEN_STAGE_LOCAL_FIXTURES",
            "assignment": {str(key): value for key, value in sorted(P09_SPLIT_BY_ACTIVITY.items())},
        },
        "held_out_lock": (
            "HELD_OUT_CONFIRMATION may only confirm or reject a configuration; "
            "it cannot tune prompts, routing, thresholds, or candidates."
        ),
        "total_case_count": len(materialized),
        "counts_by_split_and_stage": counts,
        "totals_by_split": {
            split: sum(values.values()) for split, values in counts.items()
        },
        "case_assignments": [
            {"case_id": item["case_id"], "split": item["split"]}
            for item in materialized
        ],
    }


NORMATIVE_PROPERTY_KINDS = frozenset({"PROHIBITED", "REQUIRED"})


def _binding_arbitrariness(build: BenchmarkBuild) -> dict[str, Any]:
    """Re-derive every bound case set from its recorded representative selector.

    A binding is arbitrary when the cases it claims cannot be reproduced from
    the selector it declares.  This is the machine proof that no property was
    attached to a merely convenient case: the historical "first free case"
    defect cannot survive an independent recomputation.
    """

    cases_by_id = {item["case_id"]: item for item in build.cases}
    properties_by_id = {item["property_id"]: item for item in build.properties}
    routes = build.fixture_definitions["p06_routes"]["routes"]
    opportunities = build.fixture_definitions["p07_opportunities"]["opportunities"]
    fixture_tags_by_case: dict[str, set[str]] = {}
    cross_artifact_cases: set[str] = set()
    owner_case_by_property: dict[str, str] = {}
    for route in routes:
        case_id = _case_id_for_route(route)
        fixture_tags_by_case[case_id] = set(route["fixture_tags"])
        for property_id in route["oracle_binding_metadata"]["property_ids"]:
            owner_case_by_property[property_id] = case_id
    for opportunity in opportunities:
        case_id = _case_id_for_opportunity(opportunity)
        fixture_tags_by_case[case_id] = set(opportunity["fixture_tags"])
        if (
            "CROSS_ARTIFACT"
            in opportunity["model_visible_definition"]["allowed_anchor_structures"]
        ):
            cross_artifact_cases.add(case_id)
        for property_id in opportunity["oracle_binding_metadata"]["property_ids"]:
            owner_case_by_property[property_id] = case_id

    def stage_cases(stage: str, activity_id: str, submission_id: str | None) -> list[str]:
        return sorted(
            item["case_id"]
            for item in build.cases
            if item["stage"] == stage
            and item["activity_id"] == activity_id
            and (submission_id is None or item["submission_id"] == submission_id)
        )

    violations: list[dict[str, Any]] = []
    for binding in build.property_alignment:
        if binding["alignment_status"] != "ALIGNED":
            continue
        property_id = binding["property_id"]
        item = properties_by_id[property_id]
        stage = binding["stage"]
        activity_id = item["activity_id"]
        declared = sorted(
            [binding["primary_case_id"], *binding["additional_case_ids"]]
        )
        selector = binding["representative_selector"]
        kind = selector["kind"]
        detail = selector["detail"]
        source_submissions = sorted(
            {
                match.group(1)
                for ref in item["source_refs"]
                if (
                    match := re.search(
                        r"submissions/(submission_\d+)", str(ref.get("file"))
                    )
                )
            }
        )
        expected: list[str] | None
        if kind == "OWN_FIXTURE":
            owner = owner_case_by_property.get(property_id)
            expected = [owner] if owner else []
        elif kind == "STAGE_ACTIVITY_FIXTURE":
            expected = (
                stage_cases(stage, activity_id, None)
                if item["submission_id"] is None
                else []
            )
        elif kind == "STAGE_CASE_IDENTITY":
            # The planner case set is one dedicated case per activity plus one
            # per submission, so the property's own scope names exactly one.
            expected = [
                case_id
                for case_id in stage_cases(stage, activity_id, None)
                if cases_by_id[case_id]["submission_id"] == item["submission_id"]
            ]
        elif kind == "FROZEN_FIXTURE_SCOPE":
            candidates = stage_cases(stage, activity_id, None)
            expected = [
                case_id
                for case_id in candidates
                if item["submission_id"]
                in (None, cases_by_id[case_id]["submission_id"])
            ]
        elif kind == "SOURCE_SUBMISSION_REFS":
            expected = (
                [
                    case_id
                    for case_id in stage_cases(stage, activity_id, None)
                    if cases_by_id[case_id]["submission_id"]
                    in set(detail["submission_ids"])
                ]
                if detail["submission_ids"] == source_submissions and source_submissions
                else []
            )
        elif kind == "ACTIVITY_STAGE_EXHAUSTIVE":
            expected = [] if source_submissions else stage_cases(stage, activity_id, None)
        elif kind == "SUBMISSION_EXHAUSTIVE":
            expected = (
                stage_cases(stage, activity_id, item["submission_id"])
                if item["kind"] in NORMATIVE_PROPERTY_KINDS
                and item["submission_id"] is not None
                else []
            )
        elif kind == "TOPICAL_MARKER":
            marker_tags = set(detail["marker_tags"])
            scope_submission = detail.get("submission_id")
            expected = [
                case_id
                for case_id in stage_cases(stage, activity_id, scope_submission)
                if fixture_tags_by_case.get(case_id, set()) & marker_tags
            ]
            if scope_submission is not None and item["kind"] not in NORMATIVE_PROPERTY_KINDS:
                expected = []
        elif kind == "CROSS_ARTIFACT_ANCHOR":
            expected = [
                case_id
                for case_id in stage_cases(stage, activity_id, None)
                if case_id in cross_artifact_cases
            ]
        elif kind == "SHARED_ORACLE_TAGS":
            oracle_tags = set(item["benchmark_tags"])
            expected = (
                [
                    case_id
                    for case_id in stage_cases(stage, activity_id, None)
                    if fixture_tags_by_case.get(case_id, set()) & oracle_tags
                ]
                if set(detail["oracle_tags"]) == oracle_tags and oracle_tags
                else []
            )
        else:
            expected = None
        if expected is None or sorted(expected) != declared or not declared:
            violations.append(
                {
                    "property_id": property_id,
                    "selector_kind": kind,
                    "declared_case_ids": declared,
                    "recomputed_case_ids": sorted(expected or []),
                }
            )
    return {
        "assigned_arbitrarily_count": len(violations),
        "recomputed_binding_count": sum(
            item["alignment_status"] == "ALIGNED" for item in build.property_alignment
        ),
        "selector_kind_counts": dict(
            sorted(
                Counter(
                    item["representative_selector"]["kind"]
                    for item in build.property_alignment
                    if item["alignment_status"] == "ALIGNED"
                ).items()
            )
        ),
        "violations": violations,
    }


def property_coverage(build: BenchmarkBuild) -> dict[str, Any]:
    cases_by_property: dict[str, list[str]] = defaultdict(list)
    for case in build.cases:
        for property_id in case["property_ids"]:
            cases_by_property[property_id].append(case["case_id"])
    properties_by_id = {item["property_id"]: item for item in build.properties}
    alignment_by_id = {
        item["property_id"]: item for item in build.property_alignment
    }
    arbitrariness = _binding_arbitrariness(build)
    rows: list[dict[str, Any]] = []
    unexplained = 0
    for property_id, item in sorted(properties_by_id.items()):
        binding = alignment_by_id[property_id]
        case_ids = sorted(cases_by_property[property_id])
        declared_case_ids = sorted(
            value
            for value in [
                binding["primary_case_id"],
                *binding["additional_case_ids"],
            ]
            if value is not None
        )
        if binding["alignment_status"] == "ALIGNED":
            valid = bool(case_ids) and case_ids == declared_case_ids
        else:
            valid = not case_ids and not declared_case_ids
        unexplained += not valid
        rows.append(
            {
                "property_id": property_id,
                "stage": item["stage"],
                "oracle_state": item["oracle_state"],
                "kind": item["kind"],
                "hardness": item["hardness"],
                "evaluator_mode": item["evaluator_mode"],
                "binding_scope": binding["binding_scope"],
                "primary_case_id": binding["primary_case_id"],
                "additional_case_ids": list(binding["additional_case_ids"]),
                "case_ids": case_ids,
                "fixture_id": binding["fixture_id"],
                "alignment_status": binding["alignment_status"],
                "exclusion_reason": binding["exclusion_reason"],
                "representative_selector_kind": binding["representative_selector"][
                    "kind"
                ],
            }
        )
    status_counts = Counter(item["alignment_status"] for item in rows)
    return {
        "schema_version": "semantic-property-coverage/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "property_count": len(rows),
        "case_bound_count": status_counts["ALIGNED"],
        "aligned_count": status_counts["ALIGNED"],
        "explicitly_excluded_count": status_counts["EXPLICITLY_EXCLUDED"],
        "not_applicable_count": status_counts["NOT_APPLICABLE"],
        "assigned_arbitrarily_count": arbitrariness["assigned_arbitrarily_count"],
        "arbitrary_binding_violations": arbitrariness["violations"],
        "representative_selector_counts": arbitrariness["selector_kind_counts"],
        "unexplained_uncovered_count": unexplained,
        "case_without_property_count": sum(not item["property_ids"] for item in build.cases),
        "qualification_denominator_unit": PROPERTY_AGGREGATION_RULES[
            "qualification_denominator_unit"
        ],
        "case_bindings_are_observations": True,
        "case_property_matrix": [
            {"case_id": item["case_id"], "property_ids": list(item["property_ids"])}
            for item in build.cases
        ],
        "maximum_case_bindings_per_property": max(len(item["case_ids"]) for item in rows),
        "rows": rows,
        "aggregates": {
            "stage": dict(sorted(Counter(item["stage"] for item in build.properties).items())),
            "oracle_state": dict(
                sorted(Counter(item["oracle_state"] for item in build.properties).items())
            ),
            "property_kind": dict(
                sorted(Counter(item["kind"] for item in build.properties).items())
            ),
            "evaluator_mode": dict(
                sorted(Counter(item["evaluator_mode"] for item in build.properties).items())
            ),
            "split": dict(sorted(Counter(item["split"] for item in build.cases).items())),
            "difficulty": dict(
                sorted(Counter(item["difficulty"] for item in build.cases).items())
            ),
            "discipline": dict(
                sorted(Counter(item["discipline"] for item in build.cases).items())
            ),
            "tag": dict(
                sorted(Counter(tag for item in build.cases for tag in item["tags"]).items())
            ),
        },
    }


def property_fixture_alignment(build: BenchmarkBuild) -> dict[str, Any]:
    """Return the explicit authority for every frozen semantic property."""

    rows = [copy.deepcopy(item) for item in build.property_alignment]
    counts = Counter(item["alignment_status"] for item in rows)
    if len(rows) != 395 or set(counts) - {
        "ALIGNED",
        "EXPLICITLY_EXCLUDED",
        "NOT_APPLICABLE",
    }:
        raise BenchmarkValidationError(
            "BENCHMARK_PROPERTY_BINDING_INCOMPLETE",
            "alignment report is not exhaustive",
        )
    arbitrariness = _binding_arbitrariness(build)
    return {
        "schema_version": "semantic-property-fixture-alignment/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "property_count": len(rows),
        "alignment_counts": {
            key: counts[key]
            for key in ("ALIGNED", "EXPLICITLY_EXCLUDED", "NOT_APPLICABLE")
        },
        "assigned_arbitrarily_count": arbitrariness["assigned_arbitrarily_count"],
        "arbitrary_binding_violations": arbitrariness["violations"],
        "representative_selector_counts": arbitrariness["selector_kind_counts"],
        "exclusion_reason_counts": dict(
            sorted(
                Counter(
                    item["exclusion_reason"]
                    for item in rows
                    if item["exclusion_reason"] is not None
                ).items()
            )
        ),
        "rows": rows,
    }


def tag_scope_report(build: BenchmarkBuild) -> dict[str, Any]:
    """Validate case tags against their explicit scope and provenance."""

    registry = build.fixture_definitions["tag_scope_registry"]
    allowed_by_tag = {
        item["tag"]: set(item["allowed_scopes"]) for item in registry["tags"]
    }
    property_by_id = {item["property_id"]: item for item in build.properties}
    ratification_by_activity = build.package.activity_by_id
    provenance_count = 0
    for case in build.cases:
        for provenance in case["tag_provenance"]:
            provenance_count += 1
            tag = provenance["tag"]
            scope = provenance["scope"]
            if tag not in allowed_by_tag or scope not in allowed_by_tag[tag]:
                raise BenchmarkValidationError(
                    "BENCHMARK_TAG_SCOPE_INVALID",
                    f"tag scope is not registered: {tag}/{scope}",
                )
            if scope == "ACTIVITY":
                raise BenchmarkValidationError(
                    "BENCHMARK_TAG_SCOPE_INVALID",
                    "activity coverage-index tags cannot become case assertions",
                )
            if not set(provenance["property_ids"]).issubset(case["property_ids"]):
                raise BenchmarkValidationError(
                    "BENCHMARK_TAG_PROVENANCE_INVALID",
                    "tag cites a property not bound to the case",
                )
            if scope == "PROPERTY":
                if not provenance["property_ids"] or any(
                    tag not in property_by_id[property_id]["benchmark_tags"]
                    for property_id in provenance["property_ids"]
                ):
                    raise BenchmarkValidationError(
                        "BENCHMARK_TAG_PROVENANCE_INVALID",
                        "property-scoped tag is absent from its property authority",
                    )
            if scope == "SUBMISSION":
                if case["submission_id"] is None:
                    raise BenchmarkValidationError(
                        "BENCHMARK_TAG_SCOPE_INVALID",
                        "submission tag appears on an activity-only case",
                    )
                ratification = ratification_by_activity[case["activity_id"]]
                submission = next(
                    item
                    for item in ratification["submissions"]
                    if item["submission_id"] == case["submission_id"]
                )
                if (
                    tag not in submission["benchmark_tags"]
                    or f"#submission:{case['submission_id']}"
                    not in provenance["source"]
                ):
                    raise BenchmarkValidationError(
                        "BENCHMARK_TAG_PROVENANCE_INVALID",
                        "submission tag differs from its local ratification authority",
                    )
            if scope == "CASE_DERIVED" and not provenance["source"].startswith(
                "derived:"
            ):
                raise BenchmarkValidationError(
                    "BENCHMARK_TAG_PROVENANCE_INVALID",
                    "derived tag lacks an objective derivation identifier",
                )

    contradictory = [
        item["case_id"]
        for item in build.cases
        if {"PLAN_FEASIBLE", "PLAN_INFEASIBLE"}.issubset(item["tags"])
    ]
    if contradictory:
        raise BenchmarkValidationError(
            "BENCHMARK_TAG_SCOPE_INVALID", "planner outcome tags contradict"
        )
    old_case_matrix = _json(
        REPOSITORY_ROOT / "reports/semantic_benchmark/v1/case_matrix.json"
    )["cases"]
    before_counts = Counter(tag for item in old_case_matrix for tag in item["tags"])
    after_counts = Counter(tag for item in build.cases for tag in item["tags"])
    old_contradictory = sum(
        {"PLAN_FEASIBLE", "PLAN_INFEASIBLE"}.issubset(item["tags"])
        for item in old_case_matrix
    )
    return {
        "schema_version": "semantic-tag-scope-report/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "top_level_ratification_semantics": "ACTIVITY_COVERAGE_INDEX_ONLY",
        "case_activity_scope_assertion_count": 0,
        "case_count": len(build.cases),
        "tag_provenance_count": provenance_count,
        "case_tags_without_provenance": 0,
        "contradictory_planner_tag_cases_before": old_contradictory,
        "contradictory_planner_tag_cases_after": 0,
        "before_case_tag_counts": dict(sorted(before_counts.items())),
        "after_case_tag_counts": dict(sorted(after_counts.items())),
    }


def p04_source_coverage_report(build: BenchmarkBuild) -> dict[str, Any]:
    rows = [copy.deepcopy(item) for item in build.p04_source_coverage]
    complete = all(
        item["assignment_units_total"] == item["assignment_units_projected"]
        and item["rubric_units_total"] == item["rubric_units_projected"]
        and item["oracle_reads"] == 0
        for item in rows
    )
    if len(rows) != 12 or not complete:
        raise BenchmarkValidationError(
            "BENCHMARK_P04_SOURCE_INCOMPLETE",
            "P04 source-faithful projection is not 12/12 complete",
        )
    return {
        "schema_version": "semantic-p04-source-coverage/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "activity_count": len(rows),
        "complete_activity_count": len(rows),
        "assignment_coverage": 1.0,
        "rubric_coverage": 1.0,
        "oracle_reads": 0,
        "rows": rows,
    }


def p09_fixture_integrity_report(build: BenchmarkBuild) -> dict[str, Any]:
    rows = [copy.deepcopy(item) for item in build.p09_fixture_integrity]
    exact = all(
        item["unresolved"] == 0
        and item["ambiguous"] == 0
        and item["visible_subset_support"] is True
        for item in rows
    )
    if len(rows) != 12 or not exact:
        raise BenchmarkValidationError(
            "BENCHMARK_P09_LOCATOR_INTEGRITY_INVALID",
            "P09 locator integrity is not exact for all 12 questions",
        )
    return {
        "schema_version": "semantic-p09-fixture-integrity/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "resolver_version": P09_LOCATOR_RESOLVER_VERSION,
        "fixture_count": len({item["fixture_id"] for item in rows}),
        "question_count": len(rows),
        "exact_question_count": len(rows),
        "unresolved_count": 0,
        "ambiguous_count": 0,
        "fallback_count": 0,
        "visible_subset_support_count": len(rows),
        "rows": rows,
    }


def rare_case_coverage(build: BenchmarkBuild) -> dict[str, Any]:
    """Count real case-scoped rare families from tag provenance only."""

    families: dict[str, Any] = {}
    for family, policy in RARE_FAMILY_POLICIES.items():
        tag = policy["tag"]
        matching = [item for item in build.cases if tag in item["tags"]]
        if not matching:
            raise BenchmarkValidationError(
                "BENCHMARK_RARE_CASE_UNCOVERED", f"rare family missing: {family}"
            )
        property_ids = sorted(
            {
                property_id
                for item in matching
                for property_id in item["property_ids"]
            }
        )
        split_distribution = dict(
            sorted(Counter(item["split"] for item in matching).items())
        )
        is_singleton = len(matching) == 1
        singleton_policy = (
            {
                "classification": "SINGLETON_RARE_FAMILY",
                "placement_preference": policy["singleton_preference"],
                "independent_held_out_claimed": False,
            }
            if is_singleton
            else {
                "classification": "MULTI_INSTANCE_RARE_FAMILY",
                "placement_preference": "QUALIFICATION_AND_HELD_OUT_WHEN_AVAILABLE",
                "independent_held_out_claimed": bool(
                    split_distribution.get("HELD_OUT_CONFIRMATION")
                ),
            }
        )
        families[family] = {
            "tag": tag,
            "criticality": policy["criticality"],
            "rare_property_count": len(property_ids),
            "rare_case_count": len(matching),
            "property_ids": property_ids,
            "case_ids": [item["case_id"] for item in matching],
            "split_distribution": split_distribution,
            "splits": sorted(split_distribution),
            "held_out_case_ids": [
                item["case_id"]
                for item in matching
                if item["split"] == "HELD_OUT_CONFIRMATION"
            ],
            "singleton_policy": singleton_policy,
        }
    pii_splits = set(families["simulated_pii"]["splits"])
    if not pii_splits & {"SMOKE", "CORE"} or "HELD_OUT_CONFIRMATION" not in pii_splits:
        raise BenchmarkValidationError(
            "BENCHMARK_RARE_CASE_SPLIT_INVALID",
            "simulated PII requires qualification and held-out coverage",
        )
    adversarial = families["authorized_source_adversarial"]
    if (
        adversarial["rare_case_count"] == 1
        and adversarial["splits"] == ["HELD_OUT_CONFIRMATION"]
    ):
        raise BenchmarkValidationError(
            "BENCHMARK_RARE_CASE_SPLIT_INVALID",
            "safety-critical adversarial singleton cannot be held-out only",
        )
    return {
        "schema_version": "semantic-rare-case-coverage/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "source": "CASE_SCOPED_TAG_PROVENANCE_NOT_ACTIVITY_COVERAGE_INDEX",
        "rare_property_count_semantics": (
            "UNIQUE_EXPLICITLY_BOUND_PROPERTIES_OBSERVED_BY_TAGGED_CASES"
        ),
        "families": families,
    }


def aggregate_future_semantic_runs(
    outcomes: Iterable[dict[str, Any]],
    *,
    properties: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate future repeated runs without treating repetitions as cases.

    Each input row must carry case/property/run identity plus stage, candidate,
    reasoning, split, discipline, difficulty, property kind and tags.  Phase 8
    only validates this mechanism with synthetic unit-test rows.
    """

    rows = list(outcomes)
    property_by_id = {item["property_id"]: item for item in properties}
    required = {
        "case_id",
        "property_id",
        "run_index",
        "stage",
        "candidate_id",
        "reasoning_effort",
        "split",
        "discipline",
        "difficulty",
        "property_kind",
        "tags",
        "result_state",
    }
    valid_states = set(RESULT_STATE_RULES)
    identities: set[tuple[str, str, int, str, str]] = set()
    for row in rows:
        if not required.issubset(row) or row["result_state"] not in valid_states:
            raise BenchmarkValidationError(
                "BENCHMARK_RESULT_ROW_INVALID", "future result row is incomplete"
            )
        identity = (
            row["case_id"],
            row["property_id"],
            int(row["run_index"]),
            row["candidate_id"],
            row["reasoning_effort"],
        )
        if identity in identities:
            raise BenchmarkValidationError(
                "BENCHMARK_RESULT_ROW_DUPLICATE", "future result identity repeated"
            )
        identities.add(identity)
        if row["property_id"] not in property_by_id:
            raise BenchmarkValidationError(
                "BENCHMARK_RESULT_PROPERTY_UNKNOWN", "future result property is unknown"
            )

        property_value = property_by_id[row["property_id"]]
        if (
            row["stage"] != property_value["stage"]
            or row["property_kind"] != property_value["kind"]
        ):
            raise BenchmarkValidationError(
                "BENCHMARK_RESULT_PROPERTY_METADATA_INVALID",
                "future result metadata differs from its property authority",
            )

    observation_counts = Counter(row["result_state"] for row in rows)
    case_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["case_id"], row["candidate_id"], row["reasoning_effort"])
        case_groups[key].append(row)

    def reduce_states(
        values: list[dict[str, Any]], property_value: dict[str, Any]
    ) -> str:
        states = {item["result_state"] for item in values}
        if property_value["oracle_state"] == "NOT_APPLICABLE":
            return ResultState.NOT_APPLICABLE.value
        if property_value["oracle_state"] == "ORACLE_SUSPECT":
            return ResultState.ORACLE_SUSPECT.value
        # REQUIRED uses all applicable observations and PROHIBITED fails on any
        # violation.  Both therefore preserve an observed semantic failure.
        if ResultState.MODEL_FAILURE.value in states:
            return ResultState.MODEL_FAILURE.value
        if ResultState.TECHNICAL_FAILURE.value in states:
            return ResultState.TECHNICAL_FAILURE.value
        if ResultState.PENDING_ADJUDICATION.value in states:
            return ResultState.PENDING_ADJUDICATION.value
        if ResultState.ORACLE_SUSPECT.value in states:
            return ResultState.ORACLE_SUSPECT.value
        if ResultState.DEFENSIBLE_ALTERNATIVE.value in states:
            return ResultState.DEFENSIBLE_ALTERNATIVE.value
        if states == {ResultState.PASS.value}:
            return ResultState.PASS.value
        return ResultState.PENDING_ADJUDICATION.value

    property_run_groups: dict[
        tuple[str, int, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for row in rows:
        key = (
            row["property_id"],
            int(row["run_index"]),
            row["candidate_id"],
            row["reasoning_effort"],
        )
        property_run_groups[key].append(row)
    property_run_outcomes: list[dict[str, Any]] = []
    for key, values in sorted(property_run_groups.items()):
        property_id, run_index, candidate_id, reasoning_effort = key
        property_value = property_by_id[property_id]
        property_run_outcomes.append(
            {
                "property_id": property_id,
                "run_index": run_index,
                "candidate_id": candidate_id,
                "reasoning_effort": reasoning_effort,
                "case_observation_count": len(values),
                "case_ids": sorted({item["case_id"] for item in values}),
                "result_state": reduce_states(values, property_value),
            }
        )

    property_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in property_run_outcomes:
        key = (row["property_id"], row["candidate_id"], row["reasoning_effort"])
        property_groups[key].append(row)
    property_outcomes: list[dict[str, Any]] = []
    for key, values in sorted(property_groups.items()):
        property_id, candidate_id, reasoning_effort = key
        property_value = property_by_id[property_id]
        property_outcomes.append(
            {
                "property_id": property_id,
                "candidate_id": candidate_id,
                "reasoning_effort": reasoning_effort,
                "run_count": len(values),
                "result_state": reduce_states(values, property_value),
                "hardness": property_value["hardness"],
                "oracle_state": property_value["oracle_state"],
                "kind": property_value["kind"],
            }
        )

    adjudicated_states = {
        ResultState.PASS.value,
        ResultState.MODEL_FAILURE.value,
        ResultState.DEFENSIBLE_ALTERNATIVE.value,
    }
    hard_property_outcomes = [
        item
        for item in property_outcomes
        if item["oracle_state"] == "VALID"
        and item["hardness"] == PropertyHardness.HARD_SEMANTIC_PROPERTY.value
        and item["result_state"] in adjudicated_states
    ]
    hard_property_run_outcomes = [
        item
        for item in property_run_outcomes
        if property_by_id[item["property_id"]]["oracle_state"] == "VALID"
        and property_by_id[item["property_id"]]["hardness"]
        == PropertyHardness.HARD_SEMANTIC_PROPERTY.value
        and item["result_state"] in adjudicated_states
    ]
    hard_failure_denominator = len(hard_property_outcomes)

    def stability(group: list[dict[str, Any]]) -> dict[str, Any]:
        states = Counter(item["result_state"] for item in group)
        total = len(group)
        return {
            "run_count": total,
            "success_rate": states["PASS"] / total if total else None,
            "disagreement": len(states) > 1,
            "semantic_alternative_rate": states["DEFENSIBLE_ALTERNATIVE"] / total
            if total
            else None,
            "technical_failure_rate": states["TECHNICAL_FAILURE"] / total
            if total
            else None,
            "abstention_rate": sum(
                states[value]
                for value in ("ORACLE_SUSPECT", "PENDING_ADJUDICATION", "NOT_APPLICABLE")
            )
            / total
            if total
            else None,
        }

    grouping_dimensions = (
        "stage",
        "candidate_id",
        "reasoning_effort",
        "split",
        "discipline",
        "difficulty",
        "property_kind",
    )
    grouped_counts = {
        dimension: {
            key: dict(sorted(Counter(item["result_state"] for item in values).items()))
            for key, values in sorted(
                (
                    (key, [item for item in rows if str(item[dimension]) == key])
                    for key in {str(item[dimension]) for item in rows}
                ),
                key=lambda pair: pair[0],
            )
        }
        for dimension in grouping_dimensions
    }
    tag_counts = {
        tag: dict(
            sorted(
                Counter(
                    item["result_state"] for item in rows if tag in item["tags"]
                ).items()
            )
        )
        for tag in sorted({tag for item in rows for tag in item["tags"]})
    }
    return {
        "schema_version": "semantic-result-aggregation/1.1.0",
        "statistical_significance_claimed": False,
        "descriptive_comparison_only": True,
        "aggregation_rules": PROPERTY_AGGREGATION_RULES,
        "case_observation_count": len(rows),
        "run_row_count": len(rows),
        "property_run_outcome_count": len(property_run_outcomes),
        "property_outcome_count": len(property_outcomes),
        "unique_case_count": len({item["case_id"] for item in rows}),
        "unique_property_count": len({item["property_id"] for item in rows}),
        "result_counts": {
            state: observation_counts[state] for state in RESULT_STATE_RULES
        },
        "property_run_result_counts": dict(
            sorted(Counter(item["result_state"] for item in property_run_outcomes).items())
        ),
        "property_result_counts": dict(
            sorted(Counter(item["result_state"] for item in property_outcomes).items())
        ),
        "hard_model_failure_denominator": hard_failure_denominator,
        "hard_property_run_denominator": len(hard_property_run_outcomes),
        "hard_model_failure_rate": (
            sum(
                item["result_state"] == "MODEL_FAILURE"
                for item in hard_property_outcomes
            )
            / hard_failure_denominator
            if hard_failure_denominator
            else None
        ),
        "denominator_note": (
            "One VALID HARD property per candidate/reasoning configuration after "
            "case observations and runs are reduced; repeated bindings and runs do "
            "not inflate the property denominator. ORACLE_SUSPECT, NOT_APPLICABLE, "
            "technical failures, and pending adjudication are excluded."
        ),
        "grouped_result_counts": {**grouped_counts, "tag": tag_counts},
        "case_stability": {
            "|".join(key): stability(value)
            for key, value in sorted(case_groups.items())
        },
        "property_stability": {
            "|".join(key): stability(value)
            for key, value in sorted(property_groups.items())
        },
        "property_run_outcomes": property_run_outcomes,
        "property_outcomes": property_outcomes,
        "visible_anchor_stability": "SUPPORTED_BY_FUTURE_RUN_SCHEMA_NOT_COMPUTED_WITHOUT_OUTPUTS",
    }


def benchmark_boundary(build: BenchmarkBuild) -> dict[str, Any]:
    schemas = _schema_documents()
    split = split_manifest(build.cases)
    alignment = property_fixture_alignment(build)
    tags = tag_scope_report(build)
    rare = rare_case_coverage(build)
    p04_coverage = p04_source_coverage_report(build)
    p09_integrity = p09_fixture_integrity_report(build)
    fixture_source = Path(__file__).with_name("semantic_benchmark_fixtures.py")
    definition_generator = REPOSITORY_ROOT / "tools/generate_semantic_benchmark_v11_definitions.py"
    validator_sources = [
        Path(__file__),
        fixture_source,
        Path(__file__).with_name("validation.py"),
    ]
    executable_sources = {
        "parser": Path(__file__).with_name("parsers") / "service.py",
        "planner": Path(__file__).with_name("planning.py"),
        "prompt_registry": Path(__file__).with_name("model_gateway") / "registry.py",
        "prompt_text": Path(__file__).with_name("model_gateway") / "prompt_text.py",
    }
    material = {
        "boundary_format": "semantic-benchmark-boundary/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "corpus_version": CORPUS_VERSION,
        "corpus_package_boundary_hash": build.package.package_hash,
        "schemas": {name: canonical_hash(value) for name, value in schemas.items()},
        "case_matrix_hash": canonical_hash(list(build.cases)),
        "split_manifest_hash": canonical_hash(split),
        "compiled_properties_hash": canonical_hash(list(build.properties)),
        "property_fixture_alignment_hash": canonical_hash(alignment),
        "property_binding_definitions_hash": canonical_hash(
            build.fixture_definitions["property_bindings"]
        ),
        "p04_source_coverage_hash": canonical_hash(p04_coverage),
        "p06_route_definitions_hash": canonical_hash(
            build.fixture_definitions["p06_routes"]
        ),
        "p07_opportunity_definitions_hash": canonical_hash(
            build.fixture_definitions["p07_opportunities"]
        ),
        "p09_locator_bindings_hash": canonical_hash(
            build.fixture_definitions["p09_locator_bindings"]
        ),
        "p09_fixture_integrity_hash": canonical_hash(p09_integrity),
        "p09_locator_resolver_version": P09_LOCATOR_RESOLVER_VERSION,
        "tag_scope_registry_hash": canonical_hash(
            build.fixture_definitions["tag_scope_registry"]
        ),
        "case_tag_provenance_hash": canonical_hash(
            [
                {"case_id": item["case_id"], "tag_provenance": item["tag_provenance"]}
                for item in build.cases
            ]
        ),
        "tag_scope_report_hash": canonical_hash(tags),
        "rare_coverage_rules": RARE_FAMILY_POLICIES,
        "rare_case_coverage_hash": canonical_hash(rare),
        "property_aggregation_rules": PROPERTY_AGGREGATION_RULES,
        "property_evaluator_definitions": EVALUATOR_DEFINITIONS,
        "oracle_state_rules": ORACLE_STATE_RULES,
        "result_state_rules": RESULT_STATE_RULES,
        "parser_version": PARSER_VERSION,
        "planner_version": PLANNER_VERSION,
        "executable_source_hashes": {
            name: sha256_bytes(path.read_bytes())
            for name, path in executable_sources.items()
        },
        "p04_compiler_boundary": blueprint_compiler_boundary(),
        "p06_materializer_boundary": evidence_mapping_materializer_boundary(),
        "p07_materializer_boundary": question_generation_materializer_boundary(),
        "p09_materializer_boundary": guide_generation_materializer_boundary(),
        "pipeline_authority": pipeline_authority_manifest(),
        "fixture_builder_versions": [
            P04_FIXTURE_BUILDER_VERSION,
            P06_FIXTURE_BUILDER_VERSION,
            PLANNER_FIXTURE_BUILDER_VERSION,
            P07_FIXTURE_BUILDER_VERSION,
            P09_FIXTURE_BUILDER_VERSION,
            P09_OPERATION_PROJECTION_VERSION,
            P09_LOCATOR_RESOLVER_VERSION,
        ],
        "fixture_definition_source_hash": sha256_bytes(
            definition_generator.read_bytes()
        ),
        "validator_source_hashes": {
            path.name: sha256_bytes(path.read_bytes()) for path in validator_sources
        },
        "deterministic_invariant_definitions": list(
            DETERMINISTIC_INVARIANT_DEFINITIONS
        ),
    }
    return {**material, "benchmark_boundary_hash": canonical_hash(material)}


def phase9_call_budget(
    cases: Iterable[dict[str, Any]],
    *,
    candidate_count: int = 1,
    repetitions: tuple[int, ...] = (1, 3),
) -> dict[str, Any]:
    if candidate_count < 1:
        raise ValueError("candidate_count must be positive")
    materialized = list(cases)
    semantic_counts = {
        stage: sum(item["stage"] == stage for item in materialized)
        for stage in ACTIVE_SEMANTIC_STAGES
    }
    projections: dict[str, Any] = {}
    for k in repetitions:
        by_stage = {
            stage: count * candidate_count * k
            for stage, count in semantic_counts.items()
        }
        projections[f"k={k}"] = {
            "calls_by_stage": by_stage,
            "total_model_calls": sum(by_stage.values()),
            "planner_calls": 0,
            "candidate_count": candidate_count,
            "repetitions": k,
        }
    split_counts = {
        split: {
            stage: sum(
                item["split"] == split and item["stage"] == stage
                for item in materialized
            )
            for stage in ACTIVE_SEMANTIC_STAGES
        }
        for split in ("SMOKE", "CORE", "HELD_OUT_CONFIRMATION")
    }
    split_projections: dict[str, Any] = {}
    for k in repetitions:
        split_projections[f"k={k}"] = {
            split: {
                "calls_by_stage": {
                    stage: count * candidate_count * k
                    for stage, count in stage_counts.items()
                },
                "total_model_calls": sum(stage_counts.values())
                * candidate_count
                * k,
                "planner_calls": 0,
            }
            for split, stage_counts in split_counts.items()
        }
    return {
        "schema_version": "phase9-call-budget/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "candidate_matrix_status": "UNSET",
        "pricing_status": "NOT_REFRESHED_PHASE9_REQUIRED",
        "authorization": "NONE",
        "available_cases_by_stage": {
            **semantic_counts,
            "PLANNER": sum(item["stage"] == "PLANNER" for item in materialized),
        },
        "cases_by_split_and_semantic_stage": split_counts,
        "projections_for_one_hypothetical_candidate": projections,
        "projections_by_split": split_projections,
    }


def _provider_call_graph_absent() -> tuple[bool, list[str]]:
    roots = [
        Path(__file__),
        Path(__file__).with_name("semantic_benchmark_fixtures.py"),
        REPOSITORY_ROOT / "scripts/run_semantic_benchmark.py",
        REPOSITORY_ROOT / "tools/generate_semantic_benchmark_v11_definitions.py",
    ]
    forbidden = {
        "model_gateway",
        "openai_adapter",
        "provider_authorization",
        "provider_secrets",
        "model_call_ledger",
    }
    violations: list[str] = []
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for module in modules:
            if any(token in module for token in forbidden):
                violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{module}")
    return not violations, sorted(violations)


def _p07_support_resolution_proof(build: BenchmarkBuild) -> dict[str, Any]:
    """Witness that every P07 opportunity resolved exact submission support.

    The builder already fails closed on an unknown id, but the readiness gate
    must observe the resolution rather than assume it: each opportunity has to
    resolve all of its declared ids, keep them distinct, hand exactly those ids
    to the request, and never reach outside its own submission.
    """

    rows = [item for item in build.fixture_manifest if item["stage"] == "P07"]
    exact = 0
    unresolved = 0
    cross_submission = 0
    mismatched_request = 0
    for row in rows:
        resolution = row["support_resolution"]
        declared = list(row["support_evidence_ids"])
        resolved_all = resolution["resolved_count"] == resolution["declared_count"]
        distinct = resolution["distinct_declared_count"] == len(declared)
        same_submission = resolution["cross_submission_count"] == 0
        request_matches = resolution["request_evidence_ids"] == declared
        unresolved += not resolved_all
        cross_submission += not same_submission
        mismatched_request += not request_matches
        exact += bool(resolved_all and distinct and same_submission and request_matches)
    return {
        "opportunity_count": len(rows),
        "exact_count": exact,
        "unresolved_count": unresolved,
        "cross_submission_count": cross_submission,
        "request_mismatch_count": mismatched_request,
        "fallback_count": 0,
        "resolution_mode": "EXACT_DECLARED_EVIDENCE_ID_LOOKUP_NO_FALLBACK",
    }


def _property_denominator_probe(build: BenchmarkBuild) -> dict[str, Any]:
    property_value = next(
        item
        for item in build.properties
        if item["oracle_state"] == "VALID"
        and item["hardness"] == PropertyHardness.HARD_SEMANTIC_PROPERTY.value
    )
    observations = [
        {
            "case_id": f"denominator-probe-case-{case_index}",
            "property_id": property_value["property_id"],
            "run_index": run_index,
            "stage": property_value["stage"],
            "candidate_id": "denominator-probe-candidate",
            "reasoning_effort": "denominator-probe-reasoning",
            "split": "SMOKE",
            "discipline": "synthetic-probe",
            "difficulty": "SIMPLE",
            "property_kind": property_value["kind"],
            "tags": [],
            "result_state": "PASS",
        }
        for case_index in range(1, 4)
        for run_index in range(1, 4)
    ]
    report = aggregate_future_semantic_runs(
        observations, properties=build.properties
    )
    return {
        "observation_count": report["case_observation_count"],
        "property_run_outcome_count": report["property_run_outcome_count"],
        "property_outcome_count": report["property_outcome_count"],
        "hard_property_denominator": report["hard_model_failure_denominator"],
        "passed": (
            report["case_observation_count"] == 9
            and report["property_run_outcome_count"] == 3
            and report["property_outcome_count"] == 1
            and report["hard_model_failure_denominator"] == 1
        ),
    }


def _split_coverage_proof(
    build: BenchmarkBuild, rare: dict[str, Any]
) -> dict[str, Any]:
    smoke = [item for item in build.cases if item["split"] == "SMOKE"]
    core = [item for item in build.cases if item["split"] == "CORE"]
    held = [
        item for item in build.cases if item["split"] == "HELD_OUT_CONFIRMATION"
    ]
    smoke_tags = {tag for item in smoke for tag in item["tags"]}
    required_smoke_stages = set(ACTIVE_BENCHMARK_STAGES)
    required_smoke_families = {
        "P06_INSUFFICIENT": "P06_INSUFFICIENT" in smoke_tags,
        "EXTERNAL_KNOWLEDGE": "EXTERNAL_KNOWLEDGE_TRAP" in smoke_tags,
        "PROMPT_INJECTION": bool(
            {"PROMPT_INJECTION_NOISY", "PROMPT_INJECTION_SILENT"} & smoke_tags
        ),
        "LEAKAGE": "LEAKAGE_ORACLE_SUSPECT" in smoke_tags,
        "MULTI_ARTIFACT": "MULTI_ARTIFACT" in smoke_tags,
        "SAFETY": bool(
            {
                "SIMULATED_PII",
                "PROMPT_INJECTION_NOISY",
                "PROMPT_INJECTION_SILENT",
                "ADVERSARIAL_AUTHORIZED_SOURCE",
            }
            & smoke_tags
        ),
    }
    qualification_activities = {
        _activity_number(item["activity_id"])
        for item in [*smoke, *core]
        if item["stage"] != "P09"
    }
    held_activities = {
        _activity_number(item["activity_id"])
        for item in held
        if item["stage"] != "P09"
    }
    p06_uncertain_splits = set(rare["families"]["p06_uncertain"]["splits"])
    passed = (
        {item["stage"] for item in smoke} == required_smoke_stages
        and all(required_smoke_families.values())
        and bool(core)
        and bool(held)
        and qualification_activities.isdisjoint(held_activities)
        and bool(p06_uncertain_splits & {"SMOKE", "CORE"})
        and "HELD_OUT_CONFIRMATION" in p06_uncertain_splits
    )
    return {
        "passed": passed,
        "smoke_stages": sorted({item["stage"] for item in smoke}),
        "smoke_required_families": required_smoke_families,
        "qualification_activity_numbers": sorted(qualification_activities),
        "held_out_activity_numbers": sorted(held_activities),
        "held_out_activity_disjoint": qualification_activities.isdisjoint(
            held_activities
        ),
        "p06_uncertain_splits": sorted(p06_uncertain_splits),
    }


def _readiness_invariant_report(
    *,
    build: BenchmarkBuild,
    candidate_template: dict[str, Any],
    blocked_oracle_refs: list[str],
    coverage: dict[str, Any],
    rare: dict[str, Any],
    tags: dict[str, Any],
    p04_coverage: dict[str, Any],
    p09_integrity: dict[str, Any],
) -> dict[str, Any]:
    case_by_id = {item["case_id"]: item for item in build.cases}
    route_rows = build.fixture_definitions["p06_routes"]["routes"]
    opportunity_rows = build.fixture_definitions["p07_opportunities"][
        "opportunities"
    ]
    p06_cases = [item for item in build.cases if item["stage"] == "P06"]
    p07_cases = [item for item in build.cases if item["stage"] == "P07"]
    p09_cases = [item for item in build.cases if item["stage"] == "P09"]
    denominator_probe = _property_denominator_probe(build)
    split_proof = _split_coverage_proof(build, rare)
    p07_support = _p07_support_resolution_proof(build)
    provider_absent, provider_violations = _provider_call_graph_absent()
    definitions_serialized = json.dumps(
        [
            item["model_visible_definition"]
            for item in [*route_rows, *opportunity_rows]
        ],
        ensure_ascii=False,
        sort_keys=True,
    )

    p06_alignment = len(p06_cases) == len(route_rows) and all(
        _case_id_for_route(item) in case_by_id
        and set(item["oracle_binding_metadata"]["property_ids"]).issubset(
            case_by_id[_case_id_for_route(item)]["property_ids"]
        )
        for item in route_rows
    )
    p07_alignment = len(p07_cases) == len(opportunity_rows) and all(
        _case_id_for_opportunity(item) in case_by_id
        and set(item["oracle_binding_metadata"]["property_ids"]).issubset(
            case_by_id[_case_id_for_opportunity(item)]["property_ids"]
        )
        for item in opportunity_rows
    )
    p09_scope = len(p09_cases) == 4 and all(
        all(
            property_value["stage"] == "P09"
            and property_value["activity_id"] == case["activity_id"]
            and property_value["submission_id"] in (None, case["submission_id"])
            for property_value in (
                next(
                    item
                    for item in build.properties
                    if item["property_id"] == property_id
                )
                for property_id in case["property_ids"]
            )
        )
        for case in p09_cases
    )
    checks: dict[str, tuple[bool, dict[str, Any]]] = {
        "CORPUS_BOUNDARY": (
            build.package.package_hash == EXPECTED_CORPUS_PACKAGE_HASH,
            {"corpus_package_boundary_hash": build.package.package_hash},
        ),
        "P04_SOURCE_COMPLETENESS": (
            p04_coverage["complete_activity_count"] == 12
            and p04_coverage["assignment_coverage"] == 1.0
            and p04_coverage["rubric_coverage"] == 1.0,
            {
                "complete_activity_count": p04_coverage["complete_activity_count"],
                "assignment_coverage": p04_coverage["assignment_coverage"],
                "rubric_coverage": p04_coverage["rubric_coverage"],
            },
        ),
        "P04_ORACLE_ISOLATION": (
            p04_coverage["oracle_reads"] == 0
            and all(
                "final_ratification" not in ref and "_audit_history" not in ref
                for case in build.cases
                if case["stage"] == "P04"
                for ref in case["model_visible_refs"]
            ),
            {"oracle_reads": p04_coverage["oracle_reads"]},
        ),
        "P06_ROUTE_ALIGNMENT": (
            p06_alignment,
            {"route_fixture_count": len(route_rows), "case_count": len(p06_cases)},
        ),
        "P06_EXPECTED_STATUS_ISOLATION": (
            not any(
                value in definitions_serialized
                for value in ("SUFFICIENT", "PARTIAL", "INSUFFICIENT", "UNCERTAIN")
            )
            and all(
                item.get("expected_status_in_model_input") is False
                for item in build.fixture_manifest
                if item["stage"] == "P06"
            ),
            {"expected_status_in_model_input_count": 0},
        ),
        "P07_OPPORTUNITY_ALIGNMENT": (
            p07_alignment,
            {
                "opportunity_fixture_count": len(opportunity_rows),
                "case_count": len(p07_cases),
            },
        ),
        "P07_SUPPORT_RESOLUTION": (
            p07_support["exact_count"] == len(opportunity_rows)
            and p07_support["fallback_count"] == 0
            and p07_support["unresolved_count"] == 0
            and p07_support["cross_submission_count"] == 0,
            p07_support,
        ),
        "P09_PROPERTY_SCOPE": (
            p09_scope,
            {"scoped_fixture_count": len(p09_cases)},
        ),
        "P09_EXACT_LOCATOR_RESOLUTION": (
            p09_integrity["exact_question_count"] == 12
            and p09_integrity["fallback_count"] == 0,
            {
                "exact_question_count": p09_integrity["exact_question_count"],
                "unresolved_count": p09_integrity["unresolved_count"],
                "ambiguous_count": p09_integrity["ambiguous_count"],
                "fallback_count": p09_integrity["fallback_count"],
            },
        ),
        "TAG_SCOPE_VALIDITY": (
            tags["case_tags_without_provenance"] == 0
            and tags["contradictory_planner_tag_cases_after"] == 0
            and tags["case_activity_scope_assertion_count"] == 0,
            {
                "tag_provenance_count": tags["tag_provenance_count"],
                "case_tags_without_provenance": tags[
                    "case_tags_without_provenance"
                ],
            },
        ),
        "RARE_COVERAGE_VALIDITY": (
            len(rare["families"]) == len(RARE_FAMILY_POLICIES),
            {"family_count": len(rare["families"])},
        ),
        "PROPERTY_BINDING_COMPLETENESS": (
            coverage["property_count"] == 395
            and coverage["aligned_count"]
            + coverage["explicitly_excluded_count"]
            + coverage["not_applicable_count"]
            == coverage["property_count"]
            and coverage["assigned_arbitrarily_count"] == 0
            and coverage["unexplained_uncovered_count"] == 0,
            {
                "property_count": coverage["property_count"],
                "aligned_count": coverage["aligned_count"],
                "explicitly_excluded_count": coverage[
                    "explicitly_excluded_count"
                ],
                "not_applicable_count": coverage["not_applicable_count"],
                "assigned_arbitrarily_count": coverage[
                    "assigned_arbitrarily_count"
                ],
            },
        ),
        "PROPERTY_DENOMINATOR_VALIDITY": (
            denominator_probe["passed"], denominator_probe
        ),
        "SPLIT_COVERAGE": (split_proof["passed"], split_proof),
        "ANTI_ORACLE_LEAKAGE": (
            len(blocked_oracle_refs) == 3
            and all(
                set(item["model_visible_refs"]).isdisjoint(item["oracle_refs"])
                for item in build.cases
            ),
            {"deliberate_leakage_attempts_blocked": len(blocked_oracle_refs)},
        ),
        "CANDIDATE_MATRIX_UNSET": (
            candidate_template["matrix_status"] == "UNSET"
            and candidate_template["authorization"] == "NONE",
            {
                "matrix_status": candidate_template["matrix_status"],
                "authorization": candidate_template["authorization"],
            },
        ),
        "PROVIDER_CALL_GRAPH_ABSENT": (
            provider_absent,
            {"violations": provider_violations, "provider_calls": 0},
        ),
    }
    if tuple(checks) != DETERMINISTIC_INVARIANT_DEFINITIONS:
        raise BenchmarkValidationError(
            "BENCHMARK_READINESS_INVARIANT_SET_INVALID",
            "implemented readiness checks differ from the frozen gate",
        )
    rows = [
        {
            "invariant_id": identifier,
            "result": "PASS" if passed else "FAIL",
            "evidence": evidence,
        }
        for identifier, (passed, evidence) in checks.items()
    ]
    failures = [item["invariant_id"] for item in rows if item["result"] != "PASS"]
    if failures:
        raise BenchmarkValidationError(
            "BENCHMARK_READINESS_INVARIANT_FAILED",
            "readiness invariants failed: " + ", ".join(failures),
        )
    return {
        "schema_version": "semantic-deterministic-report/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "passed": len(rows),
        "total": len(rows),
        "pass_rate": 1.0,
        "provider_calls": 0,
        "invariants": rows,
    }


def benchmark_alignment_audit(build: BenchmarkBuild) -> dict[str, Any]:
    """Summarize the reproducible root-cause audit that motivated v1.1."""

    old_root = REPOSITORY_ROOT / "reports/semantic_benchmark/v1"
    old_cases = _json(old_root / "case_matrix.json")["cases"]
    old_manifest = _json(old_root / "benchmark_manifest.json")
    old_boundary = _json(old_root / "benchmark_boundary.json")
    old_tag_counts = Counter(tag for item in old_cases for tag in item["tags"])
    new_tag_counts = Counter(tag for item in build.cases for tag in item["tags"])
    arbitrariness = _binding_arbitrariness(build)
    denominator_probe = _property_denominator_probe(build)
    findings = [
        {
            "finding_id": "V1_TAG_SCOPE_ACTIVITY_PROPAGATION",
            "confirmed": True,
            "evidence": {
                "contradictory_planner_case_count": sum(
                    {"PLAN_FEASIBLE", "PLAN_INFEASIBLE"}.issubset(item["tags"])
                    for item in old_cases
                ),
                "simulated_pii_case_count": old_tag_counts["SIMULATED_PII"],
                "silent_conceptual_gap_case_count": old_tag_counts[
                    "SILENT_CONCEPTUAL_GAP"
                ],
            },
            "resolution": "EXPLICIT_CASE_TAG_SCOPE_AND_PROVENANCE",
        },
        {
            "finding_id": "V1_P07_GENERIC_SUBMISSION_FIXTURE",
            "confirmed": True,
            "evidence": {
                "case_count": old_manifest["case_counts_by_stage"]["P07"],
                "fixture_granularity": "ONE_GENERIC_FIXTURE_PER_SUBMISSION",
                "baseline_code_authority": "22148a3:semantic_benchmark_fixtures.py:build_p07_fixture",
            },
            "resolution": "EXPLICIT_SOURCE_GROUNDED_OPPORTUNITY_FIXTURES",
        },
        {
            "finding_id": "V1_P06_GENERIC_P04_SCAFFOLD_DEPENDENCY",
            "confirmed": True,
            "evidence": {
                "case_count": old_manifest["case_counts_by_stage"]["P06"],
                "baseline_code_authority": "22148a3:semantic_benchmark.py:build_benchmark",
            },
            "resolution": "EXPLICIT_SOURCE_GROUNDED_ROUTE_FIXTURES",
        },
        {
            "finding_id": "V1_P04_FIRST_THREE_UNIT_TRUNCATION",
            "confirmed": True,
            "evidence": {
                "case_count": old_manifest["case_counts_by_stage"]["P04"],
                "baseline_code_authority": "22148a3:semantic_benchmark_fixtures.py:build_p04_fixture",
            },
            "resolution": "LOSSLESS_ALL_PARSED_UNIT_PROJECTION",
        },
        {
            "finding_id": "V1_P09_FILENAME_ONLY_WITH_FALLBACK",
            "confirmed": True,
            "evidence": {
                "fixture_count": old_manifest["p09_fixture_count"],
                "question_count": old_manifest["p09_question_count"],
                "baseline_code_authority": "22148a3:semantic_benchmark_fixtures.py:build_p09_fixture",
            },
            "resolution": "EXACT_HASHED_EVIDENCE_ID_AND_LOCATOR_BINDINGS_NO_FALLBACK",
        },
        {
            "finding_id": "V1_ACTIVITY_PROPERTY_ASSIGNED_TO_FREE_SUBMISSION",
            "confirmed": True,
            "evidence": {
                "baseline_code_authority": "22148a3:semantic_benchmark.py:property_coverage",
                "baseline_activity_property_placement": "FIRST_AVAILABLE_SUBMISSION_CASE",
                "recomputed_violation_count": arbitrariness[
                    "assigned_arbitrarily_count"
                ],
                "representative_selector_counts": arbitrariness[
                    "selector_kind_counts"
                ],
            },
            "resolution": "DECLARED_REPRESENTATIVE_SELECTOR_RECOMPUTED_PER_BINDING",
        },
        {
            "finding_id": "V1_MULTI_OBSERVATION_DENOMINATOR_INFLATION",
            "confirmed": True,
            "evidence": {
                "baseline_denominator_unit": "CASE_PROPERTY_RUN",
                "qualification_denominator_unit": PROPERTY_AGGREGATION_RULES[
                    "qualification_denominator_unit"
                ],
                "properties_bound_to_multiple_cases": sum(
                    len(item["additional_case_ids"]) > 0
                    for item in build.property_alignment
                    if item["alignment_status"] == "ALIGNED"
                ),
                "denominator_probe": denominator_probe,
            },
            "resolution": "PROPERTY_SCOPED_DENOMINATOR_WITH_CASE_AND_RUN_OBSERVATIONS",
        },
    ]
    return {
        "schema_version": "semantic-benchmark-alignment-audit/1.1.0",
        "audit_baseline_sha": "22148a3c5d43c9ab1ac2e7ae06c1e0464155ea1a",
        "benchmark_before": "semantic-benchmark/1.0.0",
        "benchmark_before_status": [
            "SUPERSEDED_PRE_QUALIFICATION",
            "NOT_VALID_FOR_PHASE9_MODEL_SELECTION",
        ],
        "benchmark_before_boundary_hash": old_boundary[
            "benchmark_boundary_hash"
        ],
        "benchmark_after": SEMANTIC_BENCHMARK_VERSION,
        "audit_status": "CONFIRMED_ALIGNMENT_DEFECTS_REMEDIATED",
        "findings": findings,
        "before_case_counts_by_stage": old_manifest["case_counts_by_stage"],
        "after_case_counts_by_stage": dict(
            sorted(Counter(item["stage"] for item in build.cases).items())
        ),
        "selected_tag_counts_before": {
            key: old_tag_counts[key]
            for key in sorted(RARE_FAMILY_POLICIES[family]["tag"] for family in RARE_FAMILY_POLICIES)
        },
        "selected_tag_counts_after": {
            key: new_tag_counts[key]
            for key in sorted(RARE_FAMILY_POLICIES[family]["tag"] for family in RARE_FAMILY_POLICIES)
        },
        "assigned_arbitrarily_after": arbitrariness["assigned_arbitrarily_count"],
    }


def _assert_offline_environment() -> None:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("CVA_OPENAI_API_KEY"):
        raise BenchmarkValidationError(
            "BENCHMARK_PROVIDER_KEY_PRESENT",
            "provider keys must be absent for the Phase 8 dry-run",
        )
    if os.environ.get("CVA_MODEL_MODE", "mock").casefold() != "mock":
        raise BenchmarkValidationError(
            "BENCHMARK_PROVIDER_MODE_INVALID", "CVA_MODEL_MODE must be mock"
        )
    if os.environ.get("CVA_P10_ENABLED", "false").casefold() not in {
        "0",
        "false",
        "no",
    }:
        raise BenchmarkValidationError(
            "BENCHMARK_P10_ENABLED", "P10 must remain disabled"
        )


def _anti_leakage_self_test(package: CorpusPackage) -> list[str]:
    blocked = []
    attempts = [
        next(path for path in package.entries if path.endswith("/final_ratification.json")),
        next(path for path in package.entries if path.startswith("_audit_history/")),
        "_audit_history/submission_id_mapping.json#strong",
    ]
    for ref in attempts:
        try:
            project_model_visible_files(package, [ref])
        except BenchmarkValidationError as exc:
            if exc.code != BENCHMARK_ORACLE_LEAKAGE_BLOCKED:
                raise
            blocked.append(ref)
        else:
            raise BenchmarkValidationError(
                BENCHMARK_ORACLE_LEAKAGE_BLOCKED, "deliberate leakage attempt succeeded"
            )
    return blocked


def _semantic_dry_run(build: BenchmarkBuild) -> dict[str, Any]:
    properties = {item["property_id"]: item for item in build.properties}
    alignment = {
        item["property_id"]: item for item in build.property_alignment
    }
    case_observations: list[dict[str, Any]] = []
    for case in build.cases:
        if case["stage"] == "PLANNER":
            continue
        for property_id in case["property_ids"]:
            item = properties[property_id]
            case_observations.append(
                {
                    "case_id": case["case_id"],
                    "property_id": property_id,
                    "stage": case["stage"],
                    "oracle_state": item["oracle_state"],
                    "result_state": ResultState.PENDING_ADJUDICATION.value,
                    "candidate_output_present": False,
                }
            )
    property_outcomes = []
    for property_id, item in sorted(properties.items()):
        binding = alignment[property_id]
        if binding["alignment_status"] == "NOT_APPLICABLE":
            result_state: str | None = ResultState.NOT_APPLICABLE.value
        elif binding["alignment_status"] == "ALIGNED":
            result_state = ResultState.PENDING_ADJUDICATION.value
        else:
            result_state = None
        property_outcomes.append(
            {
                "property_id": property_id,
                "stage": item["stage"],
                "oracle_state": item["oracle_state"],
                "alignment_status": binding["alignment_status"],
                "result_state": result_state,
                "candidate_output_present": False,
            }
        )
    return {
        "schema_version": "semantic-benchmark-dry-run/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "execution_mode": BENCHMARK_PROVIDER_DISABLED,
        "provider_calls": 0,
        "provider_transport_constructed": False,
        "billable_authorizations": 0,
        "model_call_ledger_writes": 0,
        "mock_outputs_scored": False,
        "review_packets_created": 0,
        "statistical_significance_claimed": False,
        "property_count": len(property_outcomes),
        "case_observation_count": len(case_observations),
        "explicitly_excluded_property_count": sum(
            item["alignment_status"] == "EXPLICITLY_EXCLUDED"
            for item in property_outcomes
        ),
        "outcome_counts": dict(
            sorted(
                Counter(
                    item["result_state"]
                    for item in property_outcomes
                    if item["result_state"] is not None
                ).items()
            )
        ),
        "property_outcomes": property_outcomes,
        "case_observations": case_observations,
    }


def run_offline_dry_run(
    *,
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
    report_root: Path = DEFAULT_REPORT_ROOT,
    write_reports: bool = True,
    verify_parser_twice: bool = True,
) -> dict[str, Any]:
    _assert_offline_environment()
    build = build_benchmark(corpus_root, verify_parser_twice=verify_parser_twice)
    validate_case_schemas(build.cases)
    candidate_template = validate_candidate_matrix_template()
    blocked = _anti_leakage_self_test(build.package)
    coverage = property_coverage(build)
    alignment = property_fixture_alignment(build)
    tags = tag_scope_report(build)
    rare_coverage = rare_case_coverage(build)
    p04_coverage = p04_source_coverage_report(build)
    p09_integrity = p09_fixture_integrity_report(build)
    split = split_manifest(build.cases)
    boundary = benchmark_boundary(build)
    if any(item["result"] != "PASS" for item in build.planner_results):
        raise BenchmarkValidationError(
            "BENCHMARK_PLANNER_INVARIANT_FAILED", "a planner case did not pass"
        )
    if coverage["unexplained_uncovered_count"] or coverage["case_without_property_count"]:
        raise BenchmarkValidationError(
            "BENCHMARK_COVERAGE_INCOMPLETE", "coverage has an unexplained gap"
        )
    deterministic = _readiness_invariant_report(
        build=build,
        candidate_template=candidate_template,
        blocked_oracle_refs=blocked,
        coverage=coverage,
        rare=rare_coverage,
        tags=tags,
        p04_coverage=p04_coverage,
        p09_integrity=p09_integrity,
    )
    deterministic.update(
        {
        "anti_leakage_diagnostic": BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
        "deliberate_leakage_attempts_blocked": len(blocked),
        "parser_cases": list(build.parser_determinism),
        "planner_cases": list(build.planner_results),
        }
    )
    semantic = _semantic_dry_run(build)
    call_budget = phase9_call_budget(build.cases)
    audit = benchmark_alignment_audit(build)
    case_counts = dict(sorted(Counter(item["stage"] for item in build.cases).items()))
    manifest_report = {
        "schema_version": "semantic-benchmark-manifest/1.1.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "historical_benchmark": {
            "benchmark_version": "semantic-benchmark/1.0.0",
            "status": [
                "SUPERSEDED_PRE_QUALIFICATION",
                "NOT_VALID_FOR_PHASE9_MODEL_SELECTION",
            ],
        },
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "corpus_version": CORPUS_VERSION,
        "corpus_package_boundary_hash": build.package.package_hash,
        "ratification_type": CORPUS_RATIFICATION_TYPE,
        "pipeline_authority_version": PIPELINE_AUTHORITY_VERSION,
        "active_stages": list(ACTIVE_BENCHMARK_STAGES),
        "historical_inactive_stages": list(TARGET_INACTIVE_MODEL_STAGE_IDS),
        "disabled_stages": list(DISABLED_MODEL_STAGE_IDS),
        "historical_harness_status": HISTORICAL_HARNESS_EVIDENCE_STATUS,
        "activity_count": len(build.package.ratifications),
        "submission_count": sum(
            len(item["submissions"]) for item in build.package.ratifications
        ),
        "property_count": len(build.properties),
        "property_alignment_counts": alignment["alignment_counts"],
        "assigned_arbitrarily_count": alignment["assigned_arbitrarily_count"],
        "property_state_counts": dict(
            sorted(Counter(item["oracle_state"] for item in build.properties).items())
        ),
        "case_counts_by_stage": case_counts,
        "total_case_count": len(build.cases),
        "p09_fixture_count": len(build.package.p09_fixtures),
        "p09_question_count": sum(
            len(item["questions"]) for item in build.package.p09_fixtures
        ),
        "candidate_matrix_status": candidate_template["matrix_status"],
        "authorization": candidate_template["authorization"],
        "qualification_status": "NOT_YET_RUN",
        "provider_calls": 0,
        "runtime_status": "NOT_AFFECTED",
        "corpus_status": "NOT_AFFECTED_BYTE_EXACT",
        "prompts_and_routing_status": "NOT_AFFECTED",
        "readiness": "SEMANTIC_BENCHMARK_READY_FOR_QUALIFICATION",
    }
    reports: dict[str, Any] = {
        "benchmark_alignment_audit.json": audit,
        "benchmark_manifest.json": manifest_report,
        "benchmark_boundary.json": boundary,
        "compiled_properties.json": {
            "schema_version": "compiled-semantic-properties/1.1.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "properties": list(build.properties),
        },
        "case_matrix.json": {
            "schema_version": "semantic-benchmark-case-matrix/1.1.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "cases": list(build.cases),
        },
        "split_manifest.json": split,
        "stage_fixture_manifest.json": {
            "schema_version": "semantic-stage-fixtures/1.1.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "fixtures": list(build.fixture_manifest),
        },
        "property_coverage.json": coverage,
        "property_fixture_alignment.json": alignment,
        "tag_scope_report.json": tags,
        "p04_source_coverage.json": p04_coverage,
        "p09_fixture_integrity.json": p09_integrity,
        "rare_case_coverage.json": rare_coverage,
        "deterministic_report.json": deterministic,
        "semantic_dry_run_report.json": semantic,
        "phase9_call_budget.json": call_budget,
        "result_aggregation_policy.json": {
            "schema_version": "semantic-result-aggregation-policy/1.1.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "rules": PROPERTY_AGGREGATION_RULES,
            "denominator_probe": _property_denominator_probe(build),
        },
        "fixture_definition_validation.json": {
            "schema_version": "semantic-fixture-definition-validation/1.1.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "strict_schema_count": len(_schema_documents()),
            "validated_definition_documents": sorted(_FIXTURE_DEFINITION_FILES),
            "validated_definition_document_count": len(_FIXTURE_DEFINITION_FILES),
            "validated_case_count": len(build.cases),
            "result": "PASS",
        },
    }
    if write_reports:
        report_root.mkdir(parents=True, exist_ok=True)
        for filename, value in reports.items():
            (report_root / filename).write_text(pretty_json(value), encoding="utf-8")
    return {
        "benchmark_boundary_hash": boundary["benchmark_boundary_hash"],
        "corpus_package_boundary_hash": build.package.package_hash,
        "case_counts_by_stage": case_counts,
        "split_counts": split["counts_by_split_and_stage"],
        "property_counts": manifest_report["property_state_counts"],
        "property_alignment_counts": alignment["alignment_counts"],
        "deterministic_passed": deterministic["passed"],
        "deterministic_total": deterministic["total"],
        "provider_calls": 0,
        "billable_authorizations": 0,
        "real_transport": False,
        "reports_hash": canonical_hash(reports),
        "p09_exact_questions": p09_integrity["exact_question_count"],
        "readiness": manifest_report["readiness"],
    }


def reports_are_reproducible(left: Path, right: Path) -> bool:
    left_files = sorted(path.relative_to(left).as_posix() for path in left.rglob("*") if path.is_file())
    right_files = sorted(path.relative_to(right).as_posix() for path in right.rglob("*") if path.is_file())
    if left_files != right_files:
        return False
    return all((left / path).read_bytes() == (right / path).read_bytes() for path in left_files)


def summary_json(value: dict[str, Any]) -> str:
    return pretty_json(value)
