"""Deterministic canonical-Pydantic to OpenAI Structured Outputs boundary."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel

from comprehension_verification.contracts import model_by_name
from comprehension_verification.model_gateway.registry import PromptSpec


class OpenAISchemaError(ValueError):
    """The canonical schema cannot be represented without semantic invention."""


_MAX_SAFE_SCHEMA_ISSUES = 32
_SAFE_ERROR_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")


def _schema_property_names(schema: dict[str, Any]) -> frozenset[str]:
    """Return provider-controlled property names usable in content-free paths."""

    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                walk(child)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(str(name) for name in properties)
        for child in value.values():
            walk(child)

    walk(schema)
    return frozenset(names)


def _safe_schema_path(parts: Any, *, allowed_names: frozenset[str]) -> str:
    safe_parts: list[str] = []
    for part in parts:
        if isinstance(part, int) and 0 <= part <= 9_999:
            safe_parts.append(str(part))
        elif isinstance(part, str) and part in allowed_names:
            safe_parts.append(part.replace("~", "~0").replace("/", "~1"))
        else:
            # Unknown keys may be model-generated content. Never retain them.
            safe_parts.append("*")
    return "/" + "/".join(safe_parts) if safe_parts else "/"


def provider_schema_validation_issues(
    schema: dict[str, Any], instance: Any
) -> tuple[tuple[str, str], ...]:
    """Return bounded ``(error_type, path)`` pairs without values or messages."""

    allowed_names = _schema_property_names(schema)
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
        ),
    )
    issues: list[tuple[str, str]] = []
    for error in errors:
        raw_type = str(error.validator or "schema_error")
        error_type = (
            raw_type if _SAFE_ERROR_TYPE.fullmatch(raw_type) else "schema_error"
        )
        issue = (
            error_type,
            _safe_schema_path(error.absolute_path, allowed_names=allowed_names),
        )
        if issue not in issues:
            issues.append(issue)
        if len(issues) >= _MAX_SAFE_SCHEMA_ISSUES:
            break
    return tuple(issues)


def _merge_defs(target: dict[str, Any], source: dict[str, Any]) -> None:
    target_defs = target.setdefault("$defs", {})
    for name, definition in source.get("$defs", {}).items():
        existing = target_defs.get(name)
        if existing is not None and existing != definition:
            raise OpenAISchemaError(f"Conflicting canonical $defs entry: {name}")
        target_defs[name] = definition


def _specialize_schema_repair(
    raw_schema: dict[str, Any], request: BaseModel
) -> dict[str, Any]:
    target_name = getattr(request, "target_schema_name", None)
    if not isinstance(target_name, str):
        raise OpenAISchemaError("P11 requires a canonical target_schema_name")
    target_schema = model_by_name(target_name).model_json_schema(mode="validation")
    _merge_defs(raw_schema, target_schema)
    target_root = deepcopy(target_schema)
    target_root.pop("$defs", None)
    try:
        repaired = raw_schema["properties"]["repaired_output"]
        repaired["anyOf"] = [target_root, {"type": "null"}]
        repaired.pop("default", None)
    except (KeyError, TypeError) as exc:
        raise OpenAISchemaError("Canonical SchemaRepairResult shape changed") from exc
    return raw_schema


def _strict_transform(value: Any, *, path: str = "$") -> Any:
    if isinstance(value, list):
        return [_strict_transform(item, path=f"{path}[]") for item in value]
    if not isinstance(value, dict):
        return value

    result: dict[str, Any] = {}
    for key, child in value.items():
        if key in {"default", "discriminator"}:
            continue
        normalized_key = "anyOf" if key == "oneOf" else key
        result[normalized_key] = _strict_transform(
            child, path=f"{path}/{normalized_key}"
        )

    if result.get("type") == "object":
        properties = result.get("properties")
        additional = result.get("additionalProperties")
        if additional is True or (properties is None and additional is not False):
            # Canonical Diagnostic.details is intentionally free-form. OpenAI's
            # strict subset cannot express an arbitrary object, so the provider
            # boundary narrows it to an empty metadata object. Diagnostics keep
            # their stable code/message/IDs and application validation remains
            # authoritative after the call.
            if path.endswith("/details"):
                result["properties"] = {}
                result["required"] = []
                result["additionalProperties"] = False
            else:
                raise OpenAISchemaError(
                    f"Unbounded object is unsupported at provider boundary: {path}"
                )
        else:
            result["additionalProperties"] = False
            if isinstance(properties, dict):
                result["required"] = list(properties)

    return result


def _validate_boundary_schema(schema: dict[str, Any]) -> None:
    if schema.get("type") != "object":
        raise OpenAISchemaError("Structured output root must be an object")

    property_count = 0
    maximum_depth = 0
    schema_string_length = 0
    enum_value_count = 0

    def walk(
        value: Any,
        *,
        depth: int = 0,
        path: str = "$",
        followed_refs: tuple[str, ...] = (),
    ) -> None:
        nonlocal property_count, maximum_depth, schema_string_length, enum_value_count
        maximum_depth = max(maximum_depth, depth)
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, depth=depth, path=f"{path}/{index}")
            return
        if not isinstance(value, dict):
            return
        forbidden = {
            "oneOf",
            "discriminator",
            "default",
            "allOf",
            "not",
            "dependentRequired",
            "dependentSchemas",
            "if",
            "then",
            "else",
        }.intersection(value)
        if forbidden:
            raise OpenAISchemaError(
                f"Unsupported keyword(s) {sorted(forbidden)} at {path}"
            )
        if value.get("type") == "object":
            if value.get("additionalProperties") is not False:
                raise OpenAISchemaError(
                    f"additionalProperties must be false at {path}"
                )
            properties = value.get("properties", {})
            if set(value.get("required", [])) != set(properties):
                raise OpenAISchemaError(f"All properties must be required at {path}")
            property_count += len(properties)
            depth += 1
        for names_key in ("properties", "$defs"):
            names = value.get(names_key)
            if isinstance(names, dict):
                schema_string_length += sum(len(str(name)) for name in names)
        enum_values = value.get("enum")
        if isinstance(enum_values, list):
            enum_value_count += len(enum_values)
            enum_string_length = sum(
                len(item) for item in enum_values if isinstance(item, str)
            )
            schema_string_length += enum_string_length
            if len(enum_values) > 250 and enum_string_length > 15_000:
                raise OpenAISchemaError(
                    f"Large enum exceeds the 15,000-character limit at {path}"
                )
        constant = value.get("const")
        if isinstance(constant, str):
            schema_string_length += len(constant)
        reference = value.get("$ref")
        if (
            isinstance(reference, str)
            and reference.startswith("#/$defs/")
            and reference not in followed_refs
        ):
            definition = schema.get("$defs", {}).get(reference.removeprefix("#/$defs/"))
            if isinstance(definition, dict):
                walk(
                    definition,
                    depth=depth,
                    path=reference,
                    followed_refs=(*followed_refs, reference),
                )
        for key, child in value.items():
            walk(
                child,
                depth=depth,
                path=f"{path}/{key}",
                followed_refs=followed_refs,
            )

    walk(schema)
    # The property guard is intentionally stricter than the current documented
    # provider ceiling of 5,000. Other guards mirror the current provider subset.
    if property_count > 1_000:
        raise OpenAISchemaError("Structured output has more than 1,000 properties")
    if maximum_depth > 10:
        raise OpenAISchemaError("Structured output nesting exceeds 10 object levels")
    if schema_string_length > 120_000:
        raise OpenAISchemaError("Structured output schema strings exceed 120,000 characters")
    if enum_value_count > 1_000:
        raise OpenAISchemaError("Structured output has more than 1,000 enum values")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise OpenAISchemaError(
            "Generated provider boundary is not a valid JSON Schema"
        ) from exc


def provider_output_json_schema(
    spec: PromptSpec, request: BaseModel | None = None
) -> dict[str, Any]:
    """Return the exact strict JSON Schema sent to the provider."""

    output_model = model_by_name(spec.provider_output_schema_name)
    raw_schema = output_model.model_json_schema(mode="validation")
    if spec.prompt_id == "P11_SCHEMA_REPAIR_V1":
        if request is None:
            raise OpenAISchemaError("P11 provider schema requires its repair request")
        raw_schema = _specialize_schema_repair(raw_schema, request)
    schema = _strict_transform(deepcopy(raw_schema))
    _validate_boundary_schema(schema)
    return schema


def structured_output_format(
    spec: PromptSpec, request: BaseModel
) -> dict[str, Any]:
    """Return the Responses API ``text.format`` payload for one prompt call."""

    schema = provider_output_json_schema(spec, request)
    name = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        f"cva_{spec.provider_output_schema_name}_{spec.prompt_version}",
    )[:64]
    return {
        "type": "json_schema",
        "name": name,
        "schema": schema,
        "strict": True,
    }
