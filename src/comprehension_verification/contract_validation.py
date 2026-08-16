"""Executable validation gate for the canonical v1.1 contracts.

The Pydantic module under :mod:`specification` is the source of truth.  This
module never rewrites it or the committed JSON Schema.  It provides the checks
needed to prove that the generated artifact, the documented fixtures, and JSON
received at a boundary all agree with that source.
"""

from __future__ import annotations

import hashlib
import json
import py_compile
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError

from .contracts import (
    CANONICAL_MODELS_PATH,
    CANONICAL_SCHEMA_PATH,
    CONTRACT_MODELS,
    REPOSITORY_ROOT,
    embedded_model_by_name,
    models,
)


EXPECTED_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
EXPECTED_CONTRACT_ROOT_COUNT = 60
EXPECTED_DOCUMENTED_FIXTURE_COUNT = 8

_FIXTURE_TAG = re.compile(
    r"^\s*<!--\s*contract-fixture:\s*([A-Za-z_][A-Za-z0-9_]*)\s*-->\s*$"
)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")


class ContractValidationError(ValueError):
    """A stable, content-safe failure raised by the contract gate."""


@dataclass(frozen=True, slots=True)
class ContractFixture:
    """A JSON fixture explicitly tagged in canonical Markdown."""

    source_path: Path
    tag_line: int
    schema_name: str
    raw_json: str


@dataclass(frozen=True, slots=True)
class SchemaBundleReport:
    root_names: tuple[str, ...]
    definition_count: int
    reference_count: int


@dataclass(frozen=True, slots=True)
class ContractGateReport:
    schema_version: str
    root_count: int
    definition_count: int
    reference_count: int
    fixture_count: int
    models_sha256: str
    schema_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compile_canonical_models() -> None:
    """Compile the canonical module without creating a canonical ``__pycache__``."""

    if not CANONICAL_MODELS_PATH.is_file():
        raise ContractValidationError(
            f"Canonical model artifact is missing: {CANONICAL_MODELS_PATH}"
        )
    try:
        with tempfile.TemporaryDirectory(prefix="cv-contract-compile-") as temp_dir:
            compiled_path = Path(temp_dir) / "models_v1_1.pyc"
            py_compile.compile(
                str(CANONICAL_MODELS_PATH),
                cfile=str(compiled_path),
                doraise=True,
            )
            if not compiled_path.is_file():
                raise ContractValidationError("py_compile did not produce bytecode")
    except py_compile.PyCompileError as exc:
        raise ContractValidationError("Canonical models failed py_compile") from exc


def load_schema_bundle() -> dict[str, Any]:
    """Load the committed generated schema as a JSON object."""

    try:
        raw = CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractValidationError(
            f"Canonical schema artifact is unavailable: {CANONICAL_SCHEMA_PATH}"
        ) from exc
    try:
        bundle = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractValidationError("Canonical schema is not strict JSON") from exc
    if not isinstance(bundle, dict):
        raise ContractValidationError("Canonical schema must be a JSON object")
    return bundle


def assert_schema_has_no_drift() -> None:
    """Regenerate to a temporary file and require exact byte equality."""

    committed = CANONICAL_SCHEMA_PATH.read_bytes()
    with tempfile.TemporaryDirectory(prefix="cv-contract-schema-") as temp_dir:
        generated_path = Path(temp_dir) / CANONICAL_SCHEMA_PATH.name
        models.export_schema(str(generated_path))
        generated = generated_path.read_bytes()
    if generated != committed:
        committed_hash = hashlib.sha256(committed).hexdigest()
        generated_hash = hashlib.sha256(generated).hexdigest()
        raise ContractValidationError(
            "Canonical JSON Schema drift detected "
            f"(committed sha256={committed_hash}, generated sha256={generated_hash})"
        )


def _walk_references(value: Any, path: str = "$") -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            if key == "$ref":
                if not isinstance(child, str):
                    raise ContractValidationError(f"Non-string $ref at {child_path}")
                references.append((child_path, child))
            references.extend(_walk_references(child, child_path))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            references.extend(_walk_references(child, f"{path}/{index}"))
    return references


def _resolve_local_json_pointer(document: Any, reference: str) -> Any:
    if reference == "#":
        return document
    if not reference.startswith("#/"):
        raise ContractValidationError(
            f"Canonical schema contains a non-local $ref: {reference}"
        )
    current = document
    for encoded_part in reference[2:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, Sequence) and not isinstance(current, str):
            try:
                current = current[int(part)]
                continue
            except (IndexError, TypeError, ValueError):
                pass
        raise ContractValidationError(f"Unresolvable JSON Schema $ref: {reference}")
    return current


def crawl_schema_references(bundle: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return every reference after proving that each local target exists."""

    references = tuple(_walk_references(bundle))
    for _, reference in references:
        _resolve_local_json_pointer(bundle, reference)
    return references


def _contract_schema(
    bundle: Mapping[str, Any], schema_name: str
) -> dict[str, Any]:
    definitions = bundle.get("$defs")
    roots = bundle.get("roots")
    if not isinstance(definitions, Mapping) or not isinstance(roots, Mapping):
        raise ContractValidationError("Schema bundle lacks roots or $defs")
    if schema_name in roots:
        selected = roots[schema_name]
    elif schema_name in definitions:
        selected = {"$ref": f"#/$defs/{schema_name}"}
    else:
        raise ContractValidationError(f"Unknown contract schema: {schema_name}")
    if not isinstance(selected, Mapping):
        raise ContractValidationError(f"Invalid schema selector for {schema_name}")
    return {
        "$schema": EXPECTED_SCHEMA_DIALECT,
        "$defs": definitions,
        **selected,
    }


def validate_schema_bundle(
    bundle: Mapping[str, Any] | None = None,
) -> SchemaBundleReport:
    """Validate dialect, roots, definitions, and all references."""

    selected_bundle = load_schema_bundle() if bundle is None else dict(bundle)
    if selected_bundle.get("$schema") != EXPECTED_SCHEMA_DIALECT:
        raise ContractValidationError("Canonical schema is not Draft 2020-12")
    contract_version = models.CONTRACT_VERSION
    if selected_bundle.get("version") != contract_version:
        raise ContractValidationError("Canonical schema version does not match Pydantic")
    expected_id = (
        "https://schemas.evaluaciones-personalizadas.local/"
        f"assessment-contracts/{contract_version}"
    )
    if selected_bundle.get("$id") != expected_id:
        raise ContractValidationError("Canonical schema $id does not match its version")

    try:
        Draft202012Validator.check_schema(selected_bundle)
    except Exception as exc:  # jsonschema has several version-specific subclasses
        raise ContractValidationError("Canonical Draft 2020-12 schema is invalid") from exc

    roots = selected_bundle.get("roots")
    definitions = selected_bundle.get("$defs")
    if not isinstance(roots, Mapping) or not isinstance(definitions, Mapping):
        raise ContractValidationError("Canonical schema lacks roots or $defs")

    expected_names = tuple(model.__name__ for model in CONTRACT_MODELS)
    actual_names = tuple(roots)
    if len(expected_names) != EXPECTED_CONTRACT_ROOT_COUNT:
        raise ContractValidationError(
            "CONTRACT_MODELS no longer contains the audited 60 v1.2 roots"
        )
    if actual_names != expected_names:
        raise ContractValidationError("Schema roots drifted from CONTRACT_MODELS")
    for root_name in expected_names:
        expected_ref = {"$ref": f"#/$defs/{root_name}"}
        if roots[root_name] != expected_ref or root_name not in definitions:
            raise ContractValidationError(f"Invalid root mapping: {root_name}")
        try:
            Draft202012Validator.check_schema(
                _contract_schema(selected_bundle, root_name)
            )
        except Exception as exc:
            raise ContractValidationError(
                f"Invalid Draft 2020-12 root schema: {root_name}"
            ) from exc

    references = crawl_schema_references(selected_bundle)
    return SchemaBundleReport(
        root_names=actual_names,
        definition_count=len(definitions),
        reference_count=len(references),
    )


def _opening_fence(line: str) -> tuple[str, int, str] | None:
    match = _FENCE_OPEN.fullmatch(line)
    if match is None:
        return None
    marker = match.group(1)
    info = match.group(2).strip()
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker), info


def _is_closing_fence(line: str, marker: str, minimum_length: int) -> bool:
    closing = re.fullmatch(rf" {{0,3}}{re.escape(marker)}{{{minimum_length},}}\s*", line)
    return closing is not None


def _find_fence_end(
    lines: Sequence[str], start: int, marker: str, minimum_length: int
) -> int:
    for index in range(start + 1, len(lines)):
        if _is_closing_fence(lines[index], marker, minimum_length):
            return index
    raise ContractValidationError(f"Unclosed Markdown fence starting at line {start + 1}")


def extract_markdown_contract_fixtures(path: Path) -> tuple[ContractFixture, ...]:
    """Extract tagged JSON blocks while ignoring tags inside fenced examples."""

    lines = path.read_text(encoding="utf-8").splitlines()
    fixtures: list[ContractFixture] = []
    index = 0
    while index < len(lines):
        fence = _opening_fence(lines[index])
        if fence is not None:
            marker, minimum_length, _ = fence
            index = _find_fence_end(lines, index, marker, minimum_length) + 1
            continue

        tag = _FIXTURE_TAG.fullmatch(lines[index])
        if tag is None:
            index += 1
            continue

        schema_name = tag.group(1)
        block_start = index + 1
        while block_start < len(lines) and not lines[block_start].strip():
            block_start += 1
        json_fence = (
            _opening_fence(lines[block_start]) if block_start < len(lines) else None
        )
        if json_fence is None or json_fence[2].casefold() != "json":
            raise ContractValidationError(
                f"Fixture tag at {path}:{index + 1} is not followed by a JSON fence"
            )
        marker, minimum_length, _ = json_fence
        block_end = _find_fence_end(
            lines, block_start, marker, minimum_length
        )
        raw_json = "\n".join(lines[block_start + 1 : block_end])
        _parse_json_object(raw_json, source=f"{path}:{index + 1}")
        fixtures.append(
            ContractFixture(
                source_path=path,
                tag_line=index + 1,
                schema_name=schema_name,
                raw_json=raw_json,
            )
        )
        index = block_end + 1
    return tuple(fixtures)


def documented_fixture_paths() -> tuple[Path, ...]:
    specification_dir = REPOSITORY_ROOT / "specification"
    return tuple(sorted(specification_dir.glob("*.md"), key=lambda item: item.name))


def extract_documented_contract_fixtures(
    paths: Iterable[Path] | None = None,
) -> tuple[ContractFixture, ...]:
    selected_paths = documented_fixture_paths() if paths is None else tuple(paths)
    fixtures = tuple(
        fixture
        for path in selected_paths
        for fixture in extract_markdown_contract_fixtures(path)
    )
    if paths is None and len(fixtures) != EXPECTED_DOCUMENTED_FIXTURE_COUNT:
        raise ContractValidationError(
            "Documented fixture count drifted from the audited set of eight"
        )
    return fixtures


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> None:
    raise ContractValidationError(f"Non-finite JSON number is forbidden: {value}")


def _parse_json_object(raw_json: str | bytes, *, source: str) -> dict[str, Any]:
    if isinstance(raw_json, bytes):
        try:
            text = raw_json.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractValidationError(f"{source} is not UTF-8 JSON") from exc
    else:
        text = raw_json
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite_constant,
        )
    except ContractValidationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"{source} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ContractValidationError(f"{source} must be a JSON object")
    return value


def _requires_explicit_schema_version(
    bundle: Mapping[str, Any], schema_name: str
) -> bool:
    definitions = bundle.get("$defs")
    if not isinstance(definitions, Mapping):
        raise ContractValidationError("Schema bundle lacks $defs")
    target = definitions.get(schema_name)
    if not isinstance(target, Mapping):
        raise ContractValidationError(f"Unknown contract schema: {schema_name}")
    properties = target.get("properties", {})
    return isinstance(properties, Mapping) and "schema_version" in properties


def validate_json_boundary(
    schema_name: str,
    raw_json: str | bytes,
    *,
    bundle: Mapping[str, Any] | None = None,
    require_explicit_schema_version: bool = True,
) -> BaseModel:
    """Validate untrusted JSON without Pydantic's normal coercions.

    Validation deliberately occurs in this order: strict JSON parsing, explicit
    version presence, independent JSON Schema validation, then canonical
    Pydantic validation (including its cross-field validators).
    """

    selected_bundle = load_schema_bundle() if bundle is None else bundle
    value = _parse_json_object(raw_json, source=schema_name)
    if (
        require_explicit_schema_version
        and _requires_explicit_schema_version(selected_bundle, schema_name)
        and "schema_version" not in value
    ):
        raise ContractValidationError(
            f"{schema_name} requires an explicit schema_version at the JSON boundary"
        )

    schema = _contract_schema(selected_bundle, schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    first_error = next(validator.iter_errors(value), None)
    if first_error is not None:
        location = "/".join(str(part) for part in first_error.absolute_path) or "$"
        rule = first_error.validator or "schema"
        raise ContractValidationError(
            f"JSON Schema validation failed for {schema_name} at {location} ({rule})"
        )

    model_type = embedded_model_by_name(schema_name)
    text = raw_json.decode("utf-8") if isinstance(raw_json, bytes) else raw_json
    try:
        return model_type.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise ContractValidationError(
            f"Pydantic contract validation failed for {schema_name}"
        ) from exc


def validate_documented_contract_fixtures(
    paths: Iterable[Path] | None = None,
    *,
    bundle: Mapping[str, Any] | None = None,
) -> tuple[BaseModel, ...]:
    selected_bundle = load_schema_bundle() if bundle is None else bundle
    fixtures = extract_documented_contract_fixtures(paths)
    return tuple(
        validate_json_boundary(
            fixture.schema_name,
            fixture.raw_json,
            bundle=selected_bundle,
        )
        for fixture in fixtures
    )


def run_contract_validation_gate() -> ContractGateReport:
    """Run the complete E0-01 contract gate without modifying canonical files."""

    compile_canonical_models()
    assert_schema_has_no_drift()
    bundle = load_schema_bundle()
    schema_report = validate_schema_bundle(bundle)
    fixtures = validate_documented_contract_fixtures(bundle=bundle)
    return ContractGateReport(
        schema_version=models.CONTRACT_VERSION,
        root_count=len(schema_report.root_names),
        definition_count=schema_report.definition_count,
        reference_count=schema_report.reference_count,
        fixture_count=len(fixtures),
        models_sha256=_sha256(CANONICAL_MODELS_PATH),
        schema_sha256=_sha256(CANONICAL_SCHEMA_PATH),
    )
