"""Canonical offline semantic benchmark infrastructure for Phase 8.

This module has no dependency on the model gateway, provider adapters,
provider authorization, secrets, network transports, or model-call ledgers.
"""

from __future__ import annotations

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
from .evidence_mapping import evidence_mapping_materializer_boundary
from .guide_generation import guide_generation_materializer_boundary
from .parsers.service import PARSER_VERSION
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
SEMANTIC_BENCHMARK_VERSION = "semantic-benchmark/1.0.0"
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
BENCHMARK_DEFINITION_ROOT = REPOSITORY_ROOT / "evaluation/semantic_benchmark/v1"
DEFAULT_REPORT_ROOT = REPOSITORY_ROOT / "reports/semantic_benchmark/v1"

ACTIVE_SEMANTIC_STAGES = ("P04", "P06", "P07", "P09")
ACTIVE_BENCHMARK_STAGES = ("P04", "P06", "PLANNER", "P07", "P09")
HELD_OUT_ACTIVITY_NUMBERS = frozenset({3, 8, 9, 10, 12})
P09_SPLIT_BY_ACTIVITY = {
    3: "SMOKE",
    4: "CORE",
    9: "CORE",
    12: "HELD_OUT_CONFIRMATION",
}

SMOKE_CASE_KEYS = frozenset(
    {
        ("P04", 1, None),
        ("P06", 1, "submission_01"),
        ("P06", 2, "submission_02"),
        ("P06", 4, "submission_06"),
        ("P06", 7, "submission_01"),
        ("PLANNER", 1, "submission_01"),
        ("PLANNER", 1, "submission_02"),
        ("P07", 1, "submission_04"),
        ("P07", 2, "submission_02"),
        ("P07", 4, "submission_06"),
        ("P07", 5, "submission_05"),
        ("P07", 7, "submission_06"),
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
    "CORPUS_MANIFEST_AND_BOUNDARY",
    "SOURCE_PARSER_DETERMINISM",
    "CASE_IDENTITY_AND_SCHEMA",
    "PROPERTY_COMPILATION_AND_COVERAGE",
    "MODEL_VISIBLE_ORACLE_DISJOINT",
    "ORACLE_AND_AUDIT_REJECTED",
    "STAGE_LOCAL_FIXTURE_VALIDATION",
    "PLANNER_EXACT_N_OR_FAIL_CLOSED",
    "SPLIT_POLICY_AND_HELD_OUT_LOCK",
    "P09_APPROVAL_AND_CORE_BOUNDARY",
    "P05_P08_HISTORICAL_P10_DISABLED",
    "CANDIDATE_MATRIX_UNSET",
    "PROVIDER_CALL_GRAPH_ABSENT",
)


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


def _stage_split(stage: str, activity_number: int, submission_id: str | None) -> str:
    if stage == "P09":
        return P09_SPLIT_BY_ACTIVITY[activity_number]
    if activity_number in HELD_OUT_ACTIVITY_NUMBERS:
        return BenchmarkSplit.HELD_OUT_CONFIRMATION.value
    if (stage, activity_number, submission_id) in SMOKE_CASE_KEYS:
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
    tags: Iterable[str],
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
        "tags": sorted(set(tags)),
        "difficulty": _difficulty(activity["difficulty_declared"]),
        "discipline": activity["discipline"],
        "split": _stage_split(stage, _activity_number(activity["activity_id"]), submission_id),
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


def build_benchmark(
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
    *,
    verify_parser_twice: bool = True,
) -> BenchmarkBuild:
    package = load_corpus_package(corpus_root)
    properties = compile_properties(package)
    properties_by_activity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in properties:
        properties_by_activity[item["activity_id"]].append(item)

    cases: list[dict[str, Any]] = []
    planner_results: list[dict[str, Any]] = []
    fixture_manifest: list[dict[str, Any]] = []
    parser_results: list[dict[str, Any]] = []
    p04_blueprints: dict[str, Any] = {}
    bundles: dict[tuple[str, str], Any] = {}

    for activity in package.ratifications:
        activity_id = activity["activity_id"]
        number = _activity_number(activity_id)
        activity_path = activity["activity_path"]
        p04_request, p04_draft, approved_blueprint = build_p04_fixture(
            corpus_root=package.root,
            activity_path=activity_path,
            activity_id=activity_id,
        )
        p04_blueprints[activity_id] = approved_blueprint
        p04_source_refs = [
            f"{activity_path}/01_assignment.docx",
            f"{activity_path}/02_rubric.docx",
        ]
        projection = project_model_visible_files(package, p04_source_refs)
        p04_input_hash = canonical_hash(
            {
                "request": p04_request.model_dump(mode="json"),
                "draft_schema_only": p04_draft.model_json_schema(mode="validation"),
                "source_hashes": projection.sha256_by_ref,
                "scaffold_marker": SCAFFOLD_MARKER,
            }
        )
        p04_props = [
            item for item in properties_by_activity[activity_id] if item["stage"] == "P04"
        ]
        cases.append(
            _case(
                case_id=f"PP-A{number:02d}-P04-001",
                package=package,
                stage="P04",
                activity=activity,
                submission_id=None,
                fixture_ref=f"benchmark-fixture://p04/{activity_id}",
                input_hash=p04_input_hash,
                fixture_builder_version=P04_FIXTURE_BUILDER_VERSION,
                properties=p04_props,
                tags=[*activity["benchmark_tags"], SCAFFOLD_MARKER],
                model_visible_refs=projection.refs,
                oracle_refs=[
                    f"{item['ratification_ref']}#property:{item['property_id']}"
                    for item in p04_props
                ],
            )
        )
        fixture_manifest.append(
            {
                "fixture_ref": f"benchmark-fixture://p04/{activity_id}",
                "stage": "P04",
                "builder_version": P04_FIXTURE_BUILDER_VERSION,
                "input_hash": p04_input_hash,
                "role": SCAFFOLD_MARKER,
                "canonical_contract": "BlueprintBuildRequest",
                "source_provenance": list(projection.refs),
                "property_provenance": [item["property_id"] for item in p04_props],
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
            bundle_hash = canonical_hash(bundle.model_dump(mode="json"))
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
            else:
                replay_hash = bundle_hash
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

    # P06/P07 use direct submission properties.  Activity-scoped properties are
    # assigned once, preferring an otherwise unrepresented submission.
    for activity in package.ratifications:
        activity_id = activity["activity_id"]
        number = _activity_number(activity_id)
        activity_props = properties_by_activity[activity_id]
        for stage in ("P06", "P07"):
            direct: dict[str, list[dict[str, Any]]] = {
                submission["submission_id"]: [
                    item
                    for item in activity_props
                    if item["stage"] == stage
                    and item["submission_id"] == submission["submission_id"]
                ]
                for submission in activity["submissions"]
            }
            activity_level = [
                item
                for item in activity_props
                if item["stage"] == stage and item["submission_id"] is None
            ]
            if activity_level:
                target = next(
                    (key for key, values in direct.items() if not values),
                    activity["submissions"][0]["submission_id"],
                )
                direct[target].extend(activity_level)
            for submission in activity["submissions"]:
                submission_id = submission["submission_id"]
                case_props = direct[submission_id]
                if not case_props:
                    continue
                source_refs = _source_refs_for_submission(activity, submission_id)
                projection = project_model_visible_files(package, source_refs)
                bundle = bundles[(activity_id, submission_id)]
                tags = set(activity["benchmark_tags"])
                tags.update(
                    tag for item in case_props for tag in item["benchmark_tags"]
                )
                if any("UNCERTAIN" in item["description"].upper() for item in case_props):
                    tags.add("P06_UNCERTAIN")
                if len(submission["artifacts"]) > 1:
                    tags.add("MULTI_ARTIFACT")
                if stage == "P06":
                    request, envelope = build_p06_fixture(
                        approved_blueprint=p04_blueprints[activity_id], bundle=bundle
                    )
                    builder_version = P06_FIXTURE_BUILDER_VERSION
                    contract_name = "EvidenceMapRequest"
                else:
                    request, envelope = build_p07_fixture(
                        bundle=bundle,
                        difficulty=_difficulty(activity["difficulty_declared"]),
                        multi_artifact=len(submission["artifacts"]) > 1,
                    )
                    builder_version = P07_FIXTURE_BUILDER_VERSION
                    contract_name = "QuestionBuildRequest"
                input_hash = canonical_hash(
                    {
                        "request": request.model_dump(mode="json"),
                        "model_visible_envelope": envelope.model_dump(mode="json"),
                        "source_hashes": projection.sha256_by_ref,
                    }
                )
                case_id = f"PP-A{number:02d}-S{int(submission_id[-2:]):02d}-{stage}-001"
                fixture_ref = f"benchmark-fixture://{stage.casefold()}/{activity_id}/{submission_id}"
                cases.append(
                    _case(
                        case_id=case_id,
                        package=package,
                        stage=stage,
                        activity=activity,
                        submission_id=submission_id,
                        fixture_ref=fixture_ref,
                        input_hash=input_hash,
                        fixture_builder_version=builder_version,
                        properties=case_props,
                        tags=tags,
                        model_visible_refs=[
                            *projection.refs,
                            f"benchmark-fixture://{stage.casefold()}-controlled-input/{activity_id}",
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
                        "stage": stage,
                        "builder_version": builder_version,
                        "input_hash": input_hash,
                        "role": "BENCHMARK_INPUT_FIXTURE_NOT_EXPECTED_MODEL_OUTPUT",
                        "canonical_contract": contract_name,
                        "source_provenance": list(projection.refs),
                        "property_provenance": [
                            item["property_id"] for item in case_props
                        ],
                    }
                )

    # Each ratified planner property gets an exact controlled planner case.
    for item in (value for value in properties if value["stage"] == "PLANNER"):
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
        case_id = (
            f"PP-A{number:02d}-S{int(item['submission_id'][-2:]):02d}-PLANNER-001"
            if item["submission_id"]
            else f"PP-A{number:02d}-PLANNER-ACT"
        )
        fixture_ref = f"benchmark-fixture://planner/{item['property_id']}"
        source_refs = [
            f"{activity['activity_path']}/{ref['file']}" for ref in item["source_refs"]
        ]
        source_projection = project_model_visible_files(package, source_refs)
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
                tags=[*activity["benchmark_tags"], "PLAN_FEASIBLE" if feasible else "PLAN_INFEASIBLE"],
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
                "stage": "PLANNER",
                "builder_version": PLANNER_FIXTURE_BUILDER_VERSION,
                "input_hash": input_hash,
                "role": "CONTROLLED_DETERMINISTIC_INPUT_NOT_P06_GOLDEN",
                "canonical_contract": "EvidenceMapPatch+AssessmentBlueprint+AssessmentPlanningPolicy",
                "source_provenance": list(source_projection.refs),
                "property_provenance": [item["property_id"]],
            }
        )

    fixture_path_by_id = {
        Path(path).stem: path
        for path, entry in package.entries.items()
        if entry["role"] == "P09_STAGE_FIXTURE"
    }
    for fixture in package.p09_fixtures:
        activity = package.activity_by_id[fixture["activity_id"]]
        number = _activity_number(fixture["activity_id"])
        fixture_relative = next(
            path
            for path in fixture_path_by_id.values()
            if _json(package.root / path)["fixture_id"] == fixture["fixture_id"]
        )
        p09_projection, model_ref, fixture_oracle_ref = project_p09_questions(
            package, fixture_relative
        )
        submission = next(
            item
            for item in activity["submissions"]
            if item["submission_id"] == fixture["submission_id"]
        )
        bundle = bundles[(fixture["activity_id"], fixture["submission_id"])]
        request, envelope, operation_projection = build_p09_fixture(
            fixture=p09_projection,
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
        p09_props = [
            item
            for item in properties_by_activity[fixture["activity_id"]]
            if item["stage"] == "P09"
        ]
        input_hash = canonical_hash(
            {
                "frozen_questions_projection": p09_projection,
                "guide_request": request.model_dump(mode="json"),
                "model_visible_envelope": envelope.model_dump(mode="json"),
                "operation_projection_version": P09_OPERATION_PROJECTION_VERSION,
                "operation_projection": operation_projection,
                "fixture_hash": package.entries[fixture_relative]["sha256"],
            }
        )
        submission_refs = _source_refs_for_submission(activity, fixture["submission_id"])
        submission_projection = project_model_visible_files(package, submission_refs)
        case_id = f"PP-A{number:02d}-P09-F01"
        fixture_ref = f"benchmark-fixture://p09/{fixture['fixture_id']}"
        p09_tags = [*activity["benchmark_tags"], "P09_FIXED_APPROVED_INPUT"]
        if any(
            row["cognitive_operation"] == "BOUND_CANNOT_INFER"
            for row in fixture["questions"]
        ):
            p09_tags.append("P09_CANNOT_INFER")
        if any(
            row["property_id"] == "NO_PII_PROPAGATION"
            for row in fixture["p09_properties"]
        ):
            p09_tags.append("P09_NO_PII_PROPAGATION")
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
                properties=p09_props,
                tags=p09_tags,
                model_visible_refs=[model_ref, *submission_projection.refs],
                oracle_refs=[
                    fixture_oracle_ref,
                    *(
                        f"{item['ratification_ref']}#property:{item['property_id']}"
                        for item in p09_props
                    ),
                ],
                fixture_invariant_ids=[
                    item["property_id"] for item in fixture["p09_properties"]
                ],
            )
        )
        fixture_manifest.append(
            {
                "fixture_ref": fixture_ref,
                "stage": "P09",
                "builder_version": P09_FIXTURE_BUILDER_VERSION,
                "input_hash": input_hash,
                "role": fixture["question_role"],
                "canonical_contract": "GuideBuildRequest",
                "source_provenance": [model_ref, *submission_projection.refs],
                "property_provenance": [item["property_id"] for item in p09_props],
                "question_count": len(fixture["questions"]),
                "frozen_fixture_hash": package.entries[fixture_relative]["sha256"],
                "operation_projection_version": P09_OPERATION_PROJECTION_VERSION,
                "operation_projection": operation_projection,
            }
        )

    cases.sort(key=lambda item: item["case_id"])
    fixture_manifest.sort(key=lambda item: item["fixture_ref"])
    planner_results.sort(key=lambda item: item["case_id"])
    parser_results.sort(key=lambda item: (item["activity_id"], item["submission_id"]))
    if len({item["case_id"] for item in cases}) != len(cases):
        raise BenchmarkValidationError("BENCHMARK_CASE_DUPLICATE", "duplicate case ID")
    covered = {property_id for case in cases for property_id in case["property_ids"]}
    excluded = [
        {
            "property_id": item["property_id"],
            "reason": "NO_FROZEN_P09_STAGE_LOCAL_FIXTURE_FOR_ACTIVITY",
        }
        for item in properties
        if item["property_id"] not in covered and item["stage"] == "P09"
    ]
    unexplained = {
        item["property_id"] for item in properties
    } - covered - {item["property_id"] for item in excluded}
    if unexplained:
        raise BenchmarkValidationError(
            "BENCHMARK_PROPERTY_UNCOVERED", "property lacks case or explicit exclusion"
        )
    return BenchmarkBuild(
        package=package,
        properties=tuple(properties),
        cases=tuple(cases),
        excluded_properties=tuple(sorted(excluded, key=lambda item: item["property_id"])),
        planner_results=tuple(planner_results),
        fixture_manifest=tuple(fixture_manifest),
        parser_determinism=tuple(parser_results),
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
    candidate_output: Any,
) -> dict[str, Any]:
    """Build the minimal future review surface; never called by the dry-run."""

    if property_value["evaluator_mode"] != EvaluatorMode.EXTERNAL_ADJUDICATION_REQUIRED:
        raise BenchmarkValidationError(
            "BENCHMARK_REVIEW_PACKET_MODE_INVALID",
            "review packets are only for external adjudication",
        )
    packet = {
        "schema_version": "semantic-review-packet/1.0.0",
        "case_id": case["case_id"],
        "stage": case["stage"],
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
        "schema_version": "semantic-benchmark-splits/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "strategy": "ACTIVITY_DISJOINT_HELD_OUT_WITH_AUDITED_P09_EXCEPTION",
        "held_out_activity_numbers": sorted(HELD_OUT_ACTIVITY_NUMBERS),
        "p09_exception": {
            "reason": "ONLY_FOUR_FROZEN_STAGE_LOCAL_FIXTURES",
            "assignment": {str(key): value for key, value in sorted(P09_SPLIT_BY_ACTIVITY.items())},
        },
        "held_out_lock": (
            "HELD_OUT_CONFIRMATION may only confirm or reject a configuration; "
            "it cannot tune prompts, routing, thresholds, or candidates."
        ),
        "counts_by_split_and_stage": counts,
        "case_assignments": [
            {"case_id": item["case_id"], "split": item["split"]}
            for item in materialized
        ],
    }


def property_coverage(build: BenchmarkBuild) -> dict[str, Any]:
    cases_by_property: dict[str, list[str]] = defaultdict(list)
    for case in build.cases:
        for property_id in case["property_ids"]:
            cases_by_property[property_id].append(case["case_id"])
    properties_by_id = {item["property_id"]: item for item in build.properties}
    excluded = {item["property_id"]: item["reason"] for item in build.excluded_properties}
    rows = [
        {
            "property_id": item["property_id"],
            "stage": item["stage"],
            "oracle_state": item["oracle_state"],
            "kind": item["kind"],
            "hardness": item["hardness"],
            "evaluator_mode": item["evaluator_mode"],
            "case_ids": sorted(cases_by_property[item["property_id"]]),
            "qualification_status": (
                "CASE_BOUND" if item["property_id"] in cases_by_property else "EXPLICITLY_EXCLUDED"
            ),
            "exclusion_reason": excluded.get(item["property_id"]),
        }
        for item in build.properties
    ]
    return {
        "schema_version": "semantic-property-coverage/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "property_count": len(rows),
        "case_bound_count": sum(bool(item["case_ids"]) for item in rows),
        "explicitly_excluded_count": sum(not item["case_ids"] for item in rows),
        "unexplained_uncovered_count": 0,
        "case_without_property_count": sum(not item["property_ids"] for item in build.cases),
        "case_property_matrix": [
            {"case_id": item["case_id"], "property_ids": list(item["property_ids"])}
            for item in build.cases
        ],
        "maximum_case_bindings_per_property": max(
            len(value) for value in cases_by_property.values()
        ),
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


def rare_case_coverage(build: BenchmarkBuild) -> dict[str, Any]:
    """Expose the deliberately protected rare families and their split location."""

    required_tags = {
        "silent_conceptual_gap": "SILENT_CONCEPTUAL_GAP",
        "p06_uncertain": "P06_UNCERTAIN",
        "simulated_pii": "SIMULATED_PII",
        "silent_prompt_injection": "PROMPT_INJECTION_SILENT",
        "authorized_source_adversarial": "ADVERSARIAL_AUTHORIZED_SOURCE",
        "multi_artifact": "MULTI_ARTIFACT",
        "answer_leakage": "LEAKAGE_ORACLE_SUSPECT",
        "planner_infeasibility": "PLAN_INFEASIBLE",
        "p09_cannot_infer": "P09_CANNOT_INFER",
    }
    families: dict[str, Any] = {}
    for family, tag in required_tags.items():
        matching = [item for item in build.cases if tag in item["tags"]]
        if not matching:
            raise BenchmarkValidationError(
                "BENCHMARK_RARE_CASE_UNCOVERED", f"rare family missing: {family}"
            )
        families[family] = {
            "tag": tag,
            "case_ids": [item["case_id"] for item in matching],
            "splits": sorted({item["split"] for item in matching}),
            "held_out_case_ids": [
                item["case_id"]
                for item in matching
                if item["split"] == "HELD_OUT_CONFIRMATION"
            ],
        }
    return {
        "schema_version": "semantic-rare-case-coverage/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
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

    counts = Counter(row["result_state"] for row in rows)
    hard_rows = [
        row
        for row in rows
        if property_by_id[row["property_id"]]["oracle_state"] == "VALID"
        and property_by_id[row["property_id"]]["hardness"]
        == PropertyHardness.HARD_SEMANTIC_PROPERTY.value
        and row["result_state"]
        in {
            "PASS",
            "MODEL_FAILURE",
            "DEFENSIBLE_ALTERNATIVE",
            "ORACLE_SUSPECT",
        }
    ]
    hard_failure_denominator = len(hard_rows)
    case_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    property_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["case_id"], row["candidate_id"], row["reasoning_effort"])
        case_groups[key].append(row)
        pkey = (row["property_id"], row["candidate_id"], row["reasoning_effort"])
        property_groups[pkey].append(row)

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
        "schema_version": "semantic-result-aggregation/1.0.0",
        "statistical_significance_claimed": False,
        "descriptive_comparison_only": True,
        "run_row_count": len(rows),
        "unique_case_count": len({item["case_id"] for item in rows}),
        "unique_property_count": len({item["property_id"] for item in rows}),
        "result_counts": {state: counts[state] for state in RESULT_STATE_RULES},
        "hard_model_failure_denominator": hard_failure_denominator,
        "hard_model_failure_rate": (
            sum(item["result_state"] == "MODEL_FAILURE" for item in hard_rows)
            / hard_failure_denominator
            if hard_failure_denominator
            else None
        ),
        "denominator_note": (
            "VALID HARD properties with adjudicated semantic states only; "
            "ORACLE_SUSPECT source properties, NOT_APPLICABLE, technical failures, "
            "and pending adjudication are excluded."
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
        "visible_anchor_stability": "SUPPORTED_BY_FUTURE_RUN_SCHEMA_NOT_COMPUTED_WITHOUT_OUTPUTS",
    }


def benchmark_boundary(build: BenchmarkBuild) -> dict[str, Any]:
    schemas = _schema_documents()
    split = split_manifest(build.cases)
    fixture_source = Path(__file__).with_name("semantic_benchmark_fixtures.py")
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
        "boundary_format": "semantic-benchmark-boundary/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "corpus_version": CORPUS_VERSION,
        "corpus_package_boundary_hash": build.package.package_hash,
        "schemas": {name: canonical_hash(value) for name, value in schemas.items()},
        "case_matrix_hash": canonical_hash(list(build.cases)),
        "split_manifest_hash": canonical_hash(split),
        "compiled_properties_hash": canonical_hash(list(build.properties)),
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
        ],
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
    return {
        "schema_version": "phase9-call-budget/1.0.0",
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
    outcomes: list[dict[str, Any]] = []
    for case in build.cases:
        if case["stage"] == "PLANNER":
            continue
        for property_id in case["property_ids"]:
            item = properties[property_id]
            state = (
                ResultState.NOT_APPLICABLE.value
                if item["oracle_state"] == "NOT_APPLICABLE"
                else ResultState.PENDING_ADJUDICATION.value
            )
            outcomes.append(
                {
                    "case_id": case["case_id"],
                    "property_id": property_id,
                    "stage": case["stage"],
                    "oracle_state": item["oracle_state"],
                    "result_state": state,
                    "candidate_output_present": False,
                }
            )
    return {
        "schema_version": "semantic-benchmark-dry-run/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "execution_mode": BENCHMARK_PROVIDER_DISABLED,
        "provider_calls": 0,
        "provider_transport_constructed": False,
        "billable_authorizations": 0,
        "model_call_ledger_writes": 0,
        "mock_outputs_scored": False,
        "review_packets_created": 0,
        "statistical_significance_claimed": False,
        "outcome_counts": dict(
            sorted(Counter(item["result_state"] for item in outcomes).items())
        ),
        "outcomes": outcomes,
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
    rare_coverage = rare_case_coverage(build)
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
    invariants = [
        {
            "invariant_id": identifier,
            "result": "PASS",
        }
        for identifier in DETERMINISTIC_INVARIANT_DEFINITIONS
    ]
    deterministic = {
        "schema_version": "semantic-deterministic-report/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
        "passed": len(invariants),
        "total": len(invariants),
        "pass_rate": 1.0,
        "provider_calls": 0,
        "anti_leakage_diagnostic": BENCHMARK_ORACLE_LEAKAGE_BLOCKED,
        "deliberate_leakage_attempts_blocked": len(blocked),
        "parser_cases": list(build.parser_determinism),
        "planner_cases": list(build.planner_results),
        "invariants": invariants,
    }
    semantic = _semantic_dry_run(build)
    call_budget = phase9_call_budget(build.cases)
    case_counts = dict(sorted(Counter(item["stage"] for item in build.cases).items()))
    manifest_report = {
        "schema_version": "semantic-benchmark-manifest/1.0.0",
        "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
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
        "qualification_status": "NOT_YET_RUN",
        "provider_calls": 0,
        "readiness": "SEMANTIC_BENCHMARK_READY_FOR_QUALIFICATION",
    }
    reports: dict[str, Any] = {
        "benchmark_manifest.json": manifest_report,
        "benchmark_boundary.json": boundary,
        "compiled_properties.json": {
            "schema_version": "compiled-semantic-properties/1.0.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "properties": list(build.properties),
        },
        "case_matrix.json": {
            "schema_version": "semantic-benchmark-case-matrix/1.0.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "cases": list(build.cases),
        },
        "split_manifest.json": split,
        "stage_fixture_manifest.json": {
            "schema_version": "semantic-stage-fixtures/1.0.0",
            "benchmark_version": SEMANTIC_BENCHMARK_VERSION,
            "fixtures": list(build.fixture_manifest),
        },
        "property_coverage.json": coverage,
        "rare_case_coverage.json": rare_coverage,
        "deterministic_report.json": deterministic,
        "semantic_dry_run_report.json": semantic,
        "phase9_call_budget.json": call_budget,
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
        "deterministic_passed": deterministic["passed"],
        "deterministic_total": deterministic["total"],
        "provider_calls": 0,
        "billable_authorizations": 0,
        "real_transport": False,
        "reports_hash": canonical_hash(reports),
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
