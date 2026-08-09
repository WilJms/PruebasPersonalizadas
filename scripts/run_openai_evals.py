#!/usr/bin/env python3
"""Governed synthetic OpenAI golden-set harness.

Offline is the default and never constructs an OpenAI client. Real mode is
prepared for a later human gate and requires three independent opt-ins.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

from pydantic import SecretStr

from comprehension_verification.contracts import SCHEMA_VERSION, model_by_name, models
from comprehension_verification.model_gateway import (
    CallBudget,
    DeterministicMockFactory,
    GatewayConfig,
    GatewayError,
    GatewayMode,
    MockBehavior,
    ModelGateway,
    OpenAIResponsesAdapter,
    OPENAI_ROUTE_PROFILE_ID,
    PROMPT_CONTRACTS,
    PermanentProviderError,
    build_mock_request,
    build_openai_cost_estimator,
    build_openai_routes,
    build_trusted_context,
    estimate_openai_input_tokens,
)
from comprehension_verification.model_gateway.openai_pricing import MODEL_PRICES
from comprehension_verification.model_gateway.openai_routes import (
    LUNA_MODEL_ID,
    REQUEST_FRAMING_TOKEN_ALLOWANCE,
)
from comprehension_verification.model_gateway.openai_schema import (
    structured_output_format,
)
from comprehension_verification.model_gateway.registry import prompt_spec


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/fixtures/openai_evals/v1/synthetic_cases.json"
INJECTION_MARKER = "IGNORE_PREVIOUS_INSTRUCTIONS_SYNTHETIC_MARKER"
CANARY_APPROVAL_ENV = "CVA_OPENAI_LUNA_CANARY_APPROVAL"
CANARY_APPROVAL_VALUE = "OPENAI_LUNA_CANARIES_APPROVED"
CANARY_CASE_PROMPTS = MappingProxyType(
    {
        "oa-p01-happy-txt": "P01_ACTIVITY_SPEC_V1",
        "oa-p07-open-short-txt": "P07_QUESTION_BUILD_V1",
    }
)
CANARY_ROUTE_CAP_USD = 1.0
REQUIRED_REVIEW_DIMENSIONS = frozenset(
    {
        "evidence_correctness",
        "locator_correctness",
        "grounding",
        "answerability",
        "anchor_sufficiency",
        "cognitive_demand",
        "neutrality",
        "guide_usefulness_observability",
        "expected_fail_closed",
        "defect_severity",
    }
)


class OpenAIEvalBlocked(RuntimeError):
    """A pre-transport gate stopped the real harness with zero network calls."""


@dataclass(slots=True)
class _SingleRequestAdapter:
    """Fail closed before a second canary adapter invocation can reach transport."""

    delegate: Any
    request_attempts: int = 0
    prompt_ids: list[str] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)

    async def invoke(self, **kwargs: Any) -> Any:
        if self.request_attempts >= 1:
            raise PermanentProviderError("CANARY_REQUEST_LIMIT_EXCEEDED")
        self.request_attempts += 1
        self.prompt_ids.append(str(kwargs.get("prompt_id", "")))
        result = await self.delegate.invoke(**kwargs)
        self.results.append(result)
        return result


@dataclass(slots=True)
class _SyntheticCanaryResponses:
    """Versioned fake Responses transport; it never constructs a network client."""

    prompt_id: str
    request: Any
    input_tokens: int
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> Any:
        if self.calls:
            raise AssertionError("Canary fake transport received a second request")
        self.calls.append(kwargs)
        output = DeterministicMockFactory().output_for(
            self.prompt_id, self.request, MockBehavior.HAPPY
        )
        output_text = json.dumps(
            output.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        output_tokens = min(
            prompt_spec(self.prompt_id).max_output_tokens,
            max(1, len(output_text.encode("utf-8"))),
        )
        return SimpleNamespace(
            _request_id="req_synthetic_canary_dry_run",
            error=None,
            status="completed",
            model=kwargs["model"],
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", text=output_text)],
                )
            ],
            usage=SimpleNamespace(
                input_tokens=self.input_tokens,
                input_tokens_details=SimpleNamespace(
                    cached_tokens=0,
                    cache_write_tokens=0,
                ),
                output_tokens=output_tokens,
                output_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )


@dataclass(slots=True)
class _SyntheticCanaryClient:
    responses: _SyntheticCanaryResponses


def _envelope_for(
    prompt_id: str,
    request: Any,
    *,
    trusted_context: models.TrustedPromptContext | None = None,
) -> models.ModelTaskEnvelope:
    spec = prompt_spec(prompt_id)
    return models.ModelTaskEnvelope(
        schema_version=SCHEMA_VERSION,
        prompt_id=prompt_id,
        prompt_version=spec.prompt_version,
        output_schema_name=spec.output_schema_name,
        output_schema_version=SCHEMA_VERSION,
        trusted_context=trusted_context or build_trusted_context(request),
        payload=request.model_dump(mode="json"),
    )


def _load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("classification") != "SYNTHETIC_ONLY_NO_STUDENT_DATA":
        raise ValueError("Eval manifest must be explicitly synthetic-only")
    if raw.get("route_profile") != OPENAI_ROUTE_PROFILE_ID:
        raise ValueError("Eval manifest must pin LUNA_BASELINE_V1")
    if raw.get("prompt_pack_version") != "1.1.1":
        raise ValueError("Eval manifest prompt-pack version is unsupported")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Eval manifest schema version is unsupported")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not 10 <= len(cases) <= 30:
        raise ValueError("Golden set must contain between 10 and 30 cases")
    ids = [case.get("case_id") for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Golden-set case IDs must be unique")
    if frozenset(raw.get("human_review_dimensions", [])) != REQUIRED_REVIEW_DIMENSIONS:
        raise ValueError("Golden-set human review dimensions are incomplete")
    formats = {case.get("source_format") for case in cases}
    if not {"TXT", "MD", "PDF", "DOCX"}.issubset(formats):
        raise ValueError("Golden set must cover TXT, MD, PDF and DOCX")
    if not {"WITH_RUBRIC", "NO_RUBRIC"}.issubset(
        {case.get("rubric_profile") for case in cases}
    ):
        raise ValueError("Golden set must cover activity flows with and without a rubric")
    if not {"OPEN_SHORT", "CHOICE"}.issubset(
        {case.get("response_format") for case in cases}
    ):
        raise ValueError("Golden set must cover OPEN_SHORT and CHOICE")
    if not {"INSUFFICIENT", "INJECTION", "AMBIGUOUS"}.issubset(
        {case.get("content_profile") for case in cases}
    ):
        raise ValueError("Golden set must cover insufficient, injection and ambiguity")
    if len({case.get("cognitive_operation") for case in cases if case.get("cognitive_operation")}) < 3:
        raise ValueError("Golden set must cover at least three cognitive operations")
    return cases


def _route_metadata(
    prompt_id: str,
    routes: Mapping[str, models.ModelRoute],
    *,
    effective_model: str | None = None,
) -> dict[str, Any]:
    """Return content-free, comparison-ready metadata for one eval case."""

    spec = prompt_spec(prompt_id)
    route = routes.get(prompt_id)
    return {
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "provider": route.provider if route is not None else None,
        "model": route.model if route is not None else None,
        "effective_model": effective_model,
        "reasoning_effort": (
            route.reasoning_effort.value if route is not None else None
        ),
        "fallback_route_id": (
            route.fallback_route_id if route is not None else None
        ),
        "prompt_version": spec.prompt_version,
        "schema_version": SCHEMA_VERSION,
    }


def _observed_effective_model(ledger: models.ModelCallLedger) -> str | None:
    """Return a provider-reported model only when the ledger proves it."""

    prefix = "EFFECTIVE_MODEL_"
    for code in reversed(ledger.route.reason_codes):
        if code.startswith(prefix):
            return code.removeprefix(prefix)
    return None


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _request_for_case(case: dict[str, Any]) -> Any:
    """Materialize a validated synthetic variant without ever loading a raw file."""

    prompt_id = str(case["prompt_id"])
    request = build_mock_request(prompt_id)
    data = request.model_dump(mode="json")

    source_format = case.get("source_format")
    if source_format:
        for item in _walk_dicts(data):
            locator = item.get("locator")
            if not isinstance(locator, dict):
                continue
            if source_format == "PDF":
                item["locator"] = {
                    "kind": "PAGE_BBOX",
                    "page": 1,
                    "bbox": [10.0, 10.0, 500.0, 40.0],
                    "block_index": 0,
                }
            else:
                item["locator"] = {
                    "kind": "DOCUMENT_PATH",
                    "paragraph_index": 0,
                    "heading_path": [f"Fuente sintética {source_format}"],
                    "table_index": None,
                    "row": None,
                    "column": None,
                }

    if case.get("rubric_profile") == "NO_RUBRIC":
        # Some roots (for example P01/P07) are intrinsically rubric-free at
        # their boundary; triage/build/review roots expose the optional field.
        if "rubric_spec" in data:
            data["rubric_spec"] = None

    content_profile = case.get("content_profile")
    for item in _walk_dicts(data):
        content = item.get("content_text")
        if not isinstance(content, str):
            continue
        if content_profile == "INSUFFICIENT":
            item["content_text"] = "Fragmento sintético sin detalle verificable."
        elif content_profile == "INJECTION":
            item["content_text"] = f"{content} {INJECTION_MARKER}"

    if prompt_id == "P07_QUESTION_BUILD_V1":
        opportunity = data["opportunity"]
        if case.get("response_format"):
            opportunity["allowed_response_formats"] = [case["response_format"]]
        if case.get("cognitive_operation"):
            opportunity["cognitive_operation"] = case["cognitive_operation"]
        if "justification_required" in case:
            opportunity["student_justification_required"] = bool(
                case["justification_required"]
            )

    validated = type(request).model_validate(data)
    serialized = json.dumps(validated.model_dump(mode="json"), sort_keys=True)
    if source_format and any(
        forbidden in serialized
        for forbidden in ("signed_url", "file://", "object_store_credential")
    ):
        raise ValueError("Normalized eval request contains a forbidden raw-file capability")
    return validated


def _is_abstention(output: Any) -> bool:
    if bool(getattr(output, "blocked", False)):
        return True
    status = getattr(output, "status", None)
    status_value = getattr(status, "value", status)
    return status_value in {"BLOCKED", "NEEDS_REVIEW", "REPLACEMENT_REQUIRED"}


def _assert_case_outcome(case: dict[str, Any], request: Any, result: Any) -> None:
    expected = case["expected"]
    if expected == "REPAIRED" and not result.repaired:
        raise AssertionError("Expected the one governed structural repair")
    if expected == "ABSTAINED" and not _is_abstention(result.output):
        raise AssertionError("Expected a fail-closed or needs-review output")
    if expected == "VALID" and result.repaired:
        raise AssertionError("Unexpected structural repair for a valid fixture")

    output_json = json.dumps(result.output.model_dump(mode="json"), sort_keys=True)
    if case.get("content_profile") == "INJECTION" and INJECTION_MARKER in output_json:
        raise AssertionError("Synthetic injection marker escaped into model output")

    candidate = getattr(result.output, "candidate", None)
    if candidate is not None and case.get("response_format"):
        if candidate.response_format.value != case["response_format"]:
            raise AssertionError("Question response format drifted from its opportunity")
        if candidate.student_justification_required is not bool(
            case.get("justification_required", False)
        ):
            raise AssertionError("Question justification policy drifted")
    if candidate is not None and case.get("cognitive_operation"):
        if candidate.cognitive_operation.value != case["cognitive_operation"]:
            raise AssertionError("Question cognitive operation drifted")
    if (
        case.get("rubric_profile") == "NO_RUBRIC"
        and getattr(request, "rubric_spec", None) is not None
    ):
        raise AssertionError("No-rubric fixture acquired a rubric")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _collect_reference_ids(value: Any) -> tuple[set[str], set[str]]:
    evidence_ids: set[str] = set()
    source_ids: set[str] = set()
    for item in _walk_dicts(value):
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str):
            evidence_ids.add(evidence_id)
        evidence_ids.update(
            candidate
            for candidate in item.get("evidence_ids", [])
            if isinstance(candidate, str)
        )
        source_id = item.get("source_id")
        if isinstance(source_id, str):
            source_ids.add(source_id)
        source_ids.update(
            candidate
            for key in ("source_ids", "course_source_ids")
            for candidate in item.get(key, [])
            if isinstance(candidate, str)
        )
    return evidence_ids, source_ids


def _selected_canary_case(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if len(cases) != 1:
        raise OpenAIEvalBlocked("OPENAI_LUNA_CANARY_SINGLE_CASE_REQUIRED")
    case = cases[0]
    case_id = str(case.get("case_id", ""))
    expected_prompt = CANARY_CASE_PROMPTS.get(case_id)
    if (
        expected_prompt is None
        or case.get("prompt_id") != expected_prompt
        or case.get("behavior") != "happy"
        or not case.get("real_eligible")
    ):
        raise OpenAIEvalBlocked("OPENAI_LUNA_CANARY_CASE_NOT_APPROVED")
    return case


def _canary_material(
    case: dict[str, Any],
    *,
    route_cap_usd: float,
    authorized_budget_usd: float | None = None,
) -> dict[str, Any]:
    prompt_id = str(case["prompt_id"])
    request = _request_for_case(case)
    spec = prompt_spec(prompt_id)
    envelope = _envelope_for(prompt_id, request)
    output_format = structured_output_format(spec, request)
    input_upper_bound = estimate_openai_input_tokens(spec, request, envelope)
    all_routes = build_openai_routes(max_call_cost_usd=route_cap_usd)
    estimator = build_openai_cost_estimator(all_routes)
    worst_case_usd = estimator(spec, input_upper_bound)
    if (
        authorized_budget_usd is not None
        and worst_case_usd > authorized_budget_usd
    ):
        raise OpenAIEvalBlocked("OPENAI_LUNA_CANARY_BUDGET_TOO_LOW")
    route = all_routes[prompt_id]
    if route.model != LUNA_MODEL_ID or route.fallback_route_id is not None:
        raise AssertionError("Canary route drifted from the Luna-only baseline")
    canary_routes = MappingProxyType({prompt_id: route})
    return {
        "case": case,
        "prompt_id": prompt_id,
        "request": request,
        "spec": spec,
        "envelope": envelope,
        "output_format": output_format,
        "input_upper_bound": input_upper_bound,
        "schema_bytes": len(_canonical_json_bytes(output_format["schema"])),
        "structured_output_format_bytes": len(_canonical_json_bytes(output_format)),
        "envelope_bytes": len(
            _canonical_json_bytes(envelope.model_dump(mode="json"))
        ),
        "worst_case_usd": worst_case_usd,
        "all_routes": all_routes,
        "canary_routes": canary_routes,
        "estimator": estimator,
    }


def _canary_gateway(
    material: dict[str, Any], adapter: _SingleRequestAdapter, *, budget_usd: float
) -> ModelGateway:
    return ModelGateway(
        GatewayConfig(
            mode=GatewayMode.REAL,
            timeout_seconds=125,
            max_retries=0,
            default_budget_usd=budget_usd,
            job_id=f"job_{material['case']['case_id']}_canary",
        ),
        real_routes=material["canary_routes"],
        adapters={"openai": adapter},
        cost_estimator=material["estimator"],
        input_token_estimator=estimate_openai_input_tokens,
    )


def _assert_canary_semantics(
    case: dict[str, Any], request: Any, result: Any
) -> None:
    _assert_case_outcome(case, request, result)
    status = getattr(result.output.status, "value", result.output.status)
    prompt_id = str(case["prompt_id"])
    if prompt_id == "P01_ACTIVITY_SPEC_V1" and status not in {
        "READY",
        "NEEDS_REVIEW",
    }:
        raise AssertionError("P01 canary returned an outcome outside its manifest gate")
    if prompt_id == "P07_QUESTION_BUILD_V1" and status not in {
        "READY",
        "REPLACEMENT_REQUIRED",
    }:
        raise AssertionError("P07 canary returned an outcome outside its manifest gate")


def _canary_semantic_proof(
    material: dict[str, Any], result: Any
) -> dict[str, Any]:
    """Return content-free evidence for the real canary semantic gate."""

    request = material["request"]
    output = result.output
    trusted = result.envelope.trusted_context
    output_data = output.model_dump(mode="json")
    evidence_ids, source_ids = _collect_reference_ids(output_data)
    evidence_allowlisted = evidence_ids.issubset(set(trusted.allowed_evidence_ids))
    sources_allowlisted = source_ids.issubset(
        set(trusted.allowed_course_source_ids)
    )
    status = getattr(output.status, "value", output.status)
    allowed_statuses = (
        {"READY", "NEEDS_REVIEW"}
        if material["prompt_id"] == "P01_ACTIVITY_SPEC_V1"
        else {"READY", "REPLACEMENT_REQUIRED"}
    )
    proof: dict[str, Any] = {
        "schema_validation": bool(result.ledgers)
        and result.ledgers[-1].result == "SCHEMA_VALID",
        "request_pydantic_valid": True,
        "envelope_valid": True,
        "output_pydantic_valid": True,
        "contextual_validation": True,
        "ids_allowlisted": evidence_allowlisted and sources_allowlisted,
        "outcome_allowed_by_manifest": status in allowed_statuses,
    }
    if material["prompt_id"] == "P01_ACTIVITY_SPEC_V1":
        proof["activity_id_immutable"] = (
            output.activity_id == request.activity_config.activity_id
        )
    else:
        candidate = output.candidate
        evidence_units = request.evidence_bundle.evidence_units
        candidate_evidence = (
            set(candidate.evidence_ids) if candidate is not None else set()
        )
        proof.update(
            {
                "context_mode_closed": output.context_mode.value == "CLOSED",
                "submission_id_immutable": (
                    output.submission_id
                    == request.plan.submission_id
                    == request.opportunity.submission_id
                    == request.evidence_bundle.submission_id
                ),
                "opportunity_id_immutable": (
                    output.opportunity_id == request.opportunity.opportunity_id
                    and (
                        candidate is None
                        or candidate.opportunity_id
                        == request.opportunity.opportunity_id
                    )
                ),
                "opportunity_template_id_immutable": (
                    candidate is None
                    or candidate.opportunity_template_id
                    == request.opportunity.opportunity_template_id
                ),
                "dimension_id_immutable": (
                    candidate is None
                    or candidate.dimension_id == request.opportunity.dimension_id
                ),
                "variant_id_immutable": (
                    candidate is None
                    or candidate.variant_id == request.opportunity.variant_id
                ),
                "cognitive_operation_immutable": (
                    candidate is None
                    or candidate.cognitive_operation
                    == request.opportunity.cognitive_operation
                ),
                "evidence_ids_subset": candidate_evidence.issubset(
                    set(request.evidence_bundle.allowed_evidence_ids)
                ),
                "cross_submission_evidence_absent": all(
                    unit.submission_id == request.plan.submission_id
                    for unit in evidence_units
                ),
                "external_sources_absent": (
                    candidate is None
                    or (not candidate.course_source_ids and not candidate.citations)
                ),
            }
        )
    if not all(value is True for value in proof.values()):
        raise AssertionError("Canary semantic proof contains a failed control")
    return proof


def _canary_payload_proof(
    material: dict[str, Any], result: Any, call: dict[str, Any]
) -> dict[str, Any]:
    accounted_shape = {
        key: call[key] for key in ("instructions", "input", "reasoning", "text")
    }
    request_effective_bytes = len(_canonical_json_bytes(accounted_shape))
    if (
        request_effective_bytes + REQUEST_FRAMING_TOKEN_ALLOWANCE
        != material["input_upper_bound"]
    ):
        raise AssertionError("Canary preflight bytes drifted from the captured request")

    serialized_call = _canonical_json_bytes(call).decode("utf-8")
    content_types = [
        part.get("type")
        for message in call["input"]
        for part in message.get("content", [])
    ]
    raw_upload_absent = all(kind == "input_text" for kind in content_types) and not any(
        marker in serialized_call
        for marker in (
            '"input_file"',
            '"file_id"',
            '"file_url"',
            "file://",
            "signed_url",
            "object_store_credential",
        )
    )
    user_messages = [message for message in call["input"] if message["role"] == "user"]
    if len(user_messages) != 1 or len(user_messages[0]["content"]) != 1:
        raise AssertionError("Canary request must contain exactly one semantic envelope")
    captured_envelope = json.loads(user_messages[0]["content"][0]["text"])
    proof: dict[str, Any] = {
        **_canary_semantic_proof(material, result),
        "envelope_valid": captured_envelope
        == result.envelope.model_dump(mode="json"),
        "structured_output_strict": call["text"]["format"]["strict"] is True,
        "raw_upload_absent": raw_upload_absent,
        "tools_empty": call["tools"] == [],
        "store_false": call["store"] is False,
        "background_false": call["background"] is False,
        "conversation_state_absent": not {
            "conversation",
            "previous_response_id",
        }.intersection(call),
        "semantic_task_count": len(user_messages),
    }
    if not all(
        value is True
        for key, value in proof.items()
        if key != "semantic_task_count"
    ):
        raise AssertionError("Canary dry-run proof contains a failed control")
    if proof["semantic_task_count"] != 1:
        raise AssertionError("Canary must contain exactly one semantic task")
    return {
        "request_effective_bytes": request_effective_bytes,
        "proof": proof,
    }


def _canary_real_proof(
    material: dict[str, Any], result: Any, transport_result: Any
) -> dict[str, Any]:
    """Prove real-call controls from validated output and safe adapter metadata."""

    ledger = result.ledgers[-1]
    reason_codes = set(transport_result.reason_codes)
    proof = {
        **_canary_semantic_proof(material, result),
        "requested_route_luna_only": ledger.route.model == LUNA_MODEL_ID,
        "effective_model_luna": _observed_effective_model(ledger)
        == LUNA_MODEL_ID,
        "fallback_absent": ledger.route.fallback_route_id is None,
        "structured_output_strict": "STRUCTURED_OUTPUT_STRICT" in reason_codes,
        "tools_empty": "TOOLS_EMPTY" in reason_codes,
        "store_false": "STORE_FALSE" in reason_codes,
        "background_false": "BACKGROUND_FALSE" in reason_codes,
        "sdk_retries_zero": "SDK_RETRIES_0" in reason_codes,
    }
    if not all(value is True for value in proof.values()):
        raise AssertionError("Canary real proof contains a failed control")
    return proof


def _canary_usage_metadata(
    transport_result: Any | None, ledger: models.ModelCallLedger | None
) -> dict[str, Any]:
    """Expose billable usage and hashes without serializing request or output data."""

    if transport_result is None:
        return {
            "input_tokens": None,
            "cached_input_tokens": None,
            "cache_write_input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "latency_ms": ledger.latency_ms if ledger is not None else None,
            "estimated_cost_usd": (
                round(ledger.estimated_cost_usd, 8) if ledger is not None else None
            ),
            "calculated_actual_cost_usd": (
                round(ledger.actual_cost_usd, 8)
                if ledger is not None and ledger.actual_cost_usd is not None
                else None
            ),
            "request_id_hash": None,
            "output_hash": None,
        }
    return {
        "input_tokens": transport_result.input_tokens,
        "cached_input_tokens": transport_result.cached_input_tokens,
        "cache_write_input_tokens": transport_result.cache_write_input_tokens,
        "output_tokens": transport_result.output_tokens,
        "reasoning_tokens": transport_result.reasoning_tokens,
        "latency_ms": ledger.latency_ms if ledger is not None else None,
        "estimated_cost_usd": round(transport_result.estimated_cost_usd, 8),
        "calculated_actual_cost_usd": round(transport_result.actual_cost_usd, 8),
        "request_id_hash": transport_result.provider_request_id_hash,
        "output_hash": transport_result.output_hash,
    }


def _canary_budget_metadata(material: dict[str, Any]) -> dict[str, Any]:
    prices = MODEL_PRICES[LUNA_MODEL_ID]
    return {
        "request_effective_bytes": material["input_upper_bound"]
        - REQUEST_FRAMING_TOKEN_ALLOWANCE,
        "schema_bytes": material["schema_bytes"],
        "structured_output_format_bytes": material[
            "structured_output_format_bytes"
        ],
        "envelope_bytes": material["envelope_bytes"],
        "input_upper_bound_tokens": material["input_upper_bound"],
        "max_output_tokens": material["spec"].max_output_tokens,
        "pricing_standard_short_context_usd_per_million": {
            "input": prices.input_per_million,
            "cached_input": prices.cached_input_per_million,
            "output": prices.output_per_million,
        },
        "cache_assumption": "NONE",
        "worst_case_usd": material["worst_case_usd"],
    }


async def _run_canary_dry_run(cases: list[dict[str, Any]]) -> dict[str, Any]:
    case = _selected_canary_case(cases)
    material = _canary_material(case, route_cap_usd=CANARY_ROUTE_CAP_USD)
    fake_responses = _SyntheticCanaryResponses(
        prompt_id=material["prompt_id"],
        request=material["request"],
        input_tokens=material["input_upper_bound"],
    )
    fake_client = _SyntheticCanaryClient(responses=fake_responses)
    adapter = _SingleRequestAdapter(OpenAIResponsesAdapter(client=fake_client))
    gateway = _canary_gateway(material, adapter, budget_usd=CANARY_ROUTE_CAP_USD)
    result = await gateway.invoke(
        material["prompt_id"],
        material["request"],
        build_trusted_context(material["request"]),
        budget=CallBudget(max_cost_usd=CANARY_ROUTE_CAP_USD),
    )
    _assert_canary_semantics(case, material["request"], result)
    if adapter.request_attempts != 1 or len(fake_responses.calls) != 1:
        raise AssertionError("Canary dry-run did not use exactly one fake request")
    if adapter.prompt_ids != [material["prompt_id"]]:
        raise AssertionError("Canary fake transport observed an unexpected prompt")
    payload = _canary_payload_proof(material, result, fake_responses.calls[0])
    budget = _canary_budget_metadata(material)
    if payload["request_effective_bytes"] != budget["request_effective_bytes"]:
        raise AssertionError("Canary budget bytes do not match the captured payload")
    status = getattr(result.output.status, "value", result.output.status)
    row = {
        "case_id": case["case_id"],
        "status": "PASS",
        "output_status": status,
        "fake_transport_calls": len(fake_responses.calls),
        "validation_order": [phase.value for phase in result.validation_order],
        "budget": budget,
        "controls": payload["proof"],
        **_route_metadata(
            material["prompt_id"],
            material["canary_routes"],
            effective_model=_observed_effective_model(result.ledgers[-1]),
        ),
    }
    return {
        "mode": "canary-dry-run",
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "network_calls": 0,
        "billable_calls": 0,
        "max_responses_requests": 1,
        "gateway_retries": 0,
        "prompt_retries": 0,
        "sdk_retries": 0,
        "p10_calls": 0,
        "p11_calls": 0,
        "sol_calls": 0,
        "secret_read": False,
        "cases": [row],
    }


async def _run_offline(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    routes = build_openai_routes(max_call_cost_usd=1.0)
    for case in cases:
        prompt_id = str(case["prompt_id"])
        if case["behavior"] == "route_blocked":
            passed = prompt_id == "P10_ENRICHED_CONTEXT_V1" and prompt_id not in routes
            rows.append(
                {
                    "case_id": case["case_id"],
                    "status": "PASS" if passed else "FAIL",
                    "provider_calls": 0,
                    "source_format": case.get("source_format"),
                    "semantic_expectation": case.get("semantic_expectation"),
                    **_route_metadata(prompt_id, routes),
                }
            )
            continue
        request = _request_for_case(case)
        structured_output_format(prompt_spec(prompt_id), request)
        behavior = MockBehavior(case["behavior"])
        result = await ModelGateway().invoke(
            prompt_id,
            request,
            build_trusted_context(request),
            behavior=behavior,
        )
        expected_root = model_by_name(PROMPT_CONTRACTS[prompt_id][1])
        passed = isinstance(result.output, expected_root)
        try:
            _assert_case_outcome(case, request, result)
        except AssertionError:
            passed = False
        rows.append(
            {
                "case_id": case["case_id"],
                "status": "PASS" if passed else "FAIL",
                "provider_calls": 0,
                "mock_attempts": len(result.ledgers),
                "source_format": case.get("source_format"),
                "semantic_expectation": case.get("semantic_expectation"),
                **_route_metadata(prompt_id, routes),
            }
        )
    return {
        "mode": "offline",
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "network_calls": 0,
        "billable_calls": 0,
        "human_review_dimensions": sorted(REQUIRED_REVIEW_DIMENSIONS),
        "cases": rows,
    }


async def _run_real(
    cases: list[dict[str, Any]], *, max_total_cost_usd: float
) -> dict[str, Any]:
    key = os.environ.get("CVA_OPENAI_API_KEY", "").strip()
    if not key:
        raise OpenAIEvalBlocked("OPENAI_CREDENTIALS_REQUIRED")
    if os.environ.get("CVA_OPENAI_REAL_EVALS_APPROVAL") != "OPENAI_REAL_EVALS_APPROVED":
        raise OpenAIEvalBlocked("OPENAI_REAL_EVALS_APPROVAL_REQUIRED")
    eligible = [case for case in cases if case.get("real_eligible")]
    routes = build_openai_routes(max_call_cost_usd=max_total_cost_usd)
    estimator = build_openai_cost_estimator(routes)
    estimated_ceiling = 0.0
    for case in eligible:
        spec = prompt_spec(case["prompt_id"])
        request = _request_for_case(case)
        envelope = _envelope_for(case["prompt_id"], request)
        input_ceiling = estimate_openai_input_tokens(spec, request, envelope)
        estimated_ceiling += estimator(spec, input_ceiling) * (
            min(2, spec.max_transient_retries) + 1
        )
        if spec.prompt_id != "P11_SCHEMA_REPAIR_V1":
            repair_spec = prompt_spec("P11_SCHEMA_REPAIR_V1")
            repair_request = models.SchemaRepairRequest(
                target_schema_name=spec.output_schema_name,
                invalid_output="x" * (spec.max_output_tokens * 4),
                validation_issues=[
                    models.SchemaValidationIssue(
                        path="/",
                        error_type="synthetic_preflight",
                        message="Synthetic worst-case repair reservation",
                    )
                ],
            )
            repair_envelope = _envelope_for(
                repair_spec.prompt_id,
                repair_request,
                trusted_context=envelope.trusted_context,
            )
            repair_input_ceiling = estimate_openai_input_tokens(
                repair_spec, repair_request, repair_envelope
            )
            estimated_ceiling += estimator(repair_spec, repair_input_ceiling)
    if estimated_ceiling > max_total_cost_usd:
        raise OpenAIEvalBlocked("OPENAI_REAL_EVALS_BUDGET_TOO_LOW")
    adapter = OpenAIResponsesAdapter(api_key=SecretStr(key))
    rows: list[dict[str, Any]] = []
    actual_total = 0.0
    budget_charged_total = 0.0
    network_calls = 0
    for case in eligible:
        prompt_id = case["prompt_id"]
        request = _request_for_case(case)
        remaining_budget = max(0.0, max_total_cost_usd - budget_charged_total)
        gateway = ModelGateway(
            GatewayConfig(
                mode=GatewayMode.REAL,
                timeout_seconds=125,
                max_retries=2,
                default_budget_usd=remaining_budget,
                job_id=f"job_{case['case_id']}",
            ),
            real_routes=routes,
            adapters={"openai": adapter},
            cost_estimator=estimator,
            input_token_estimator=estimate_openai_input_tokens,
        )
        try:
            result = await gateway.invoke(
                prompt_id,
                request,
                build_trusted_context(request),
                budget=CallBudget(max_cost_usd=remaining_budget),
            )
        except GatewayError as exc:
            network_calls += len(exc.ledgers)
            actual_total += sum(item.actual_cost_usd or 0.0 for item in exc.ledgers)
            budget_charged_total += sum(
                max(item.estimated_cost_usd, item.actual_cost_usd or 0.0)
                for item in exc.ledgers
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "status": "FAIL",
                    "error_code": exc.code,
                    "attempts": len(exc.ledgers),
                    **_route_metadata(
                        prompt_id,
                        routes,
                        effective_model=(
                            _observed_effective_model(exc.ledgers[-1])
                            if exc.ledgers
                            else None
                        ),
                    ),
                }
            )
            break
        network_calls += len(result.ledgers)
        cost = sum(item.actual_cost_usd or 0.0 for item in result.ledgers)
        actual_total += cost
        budget_charged_total += sum(
            max(item.estimated_cost_usd, item.actual_cost_usd or 0.0)
            for item in result.ledgers
        )
        try:
            _assert_case_outcome(case, request, result)
        except AssertionError:
            effective_model = _observed_effective_model(result.ledgers[-1])
            rows.append(
                {
                    "case_id": case["case_id"],
                    "status": "FAIL",
                    "error_code": "OPENAI_REAL_EVAL_EXPECTATION_FAILED",
                    "attempts": len(result.ledgers),
                    "actual_cost_usd": round(cost, 8),
                    **_route_metadata(
                        prompt_id, routes, effective_model=effective_model
                    ),
                }
            )
            break
        rows.append(
            {
                "case_id": case["case_id"],
                "status": "PASS",
                "attempts": len(result.ledgers),
                "actual_cost_usd": round(cost, 8),
                **_route_metadata(
                    prompt_id,
                    routes,
                    effective_model=_observed_effective_model(result.ledgers[-1]),
                ),
            }
        )
    return {
        "mode": "real",
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "estimated_ceiling_usd": round(estimated_ceiling, 8),
        "actual_cost_usd": round(actual_total, 8),
        "budget_charged_usd": round(budget_charged_total, 8),
        "network_calls": network_calls,
        "cases": rows,
    }


async def _run_canary_real(
    cases: list[dict[str, Any]], *, max_total_cost_usd: float
) -> dict[str, Any]:
    """Run one explicitly approved canary with a hard one-request boundary."""

    case = _selected_canary_case(cases)
    if os.environ.get(CANARY_APPROVAL_ENV) != CANARY_APPROVAL_VALUE:
        raise OpenAIEvalBlocked("OPENAI_LUNA_CANARY_APPROVAL_REQUIRED")
    key = os.environ.get("CVA_OPENAI_API_KEY", "").strip()
    if not key:
        raise OpenAIEvalBlocked("OPENAI_CREDENTIALS_REQUIRED")
    material = _canary_material(
        case,
        route_cap_usd=max_total_cost_usd,
        authorized_budget_usd=max_total_cost_usd,
    )
    adapter = _SingleRequestAdapter(OpenAIResponsesAdapter(api_key=SecretStr(key)))
    gateway = _canary_gateway(material, adapter, budget_usd=max_total_cost_usd)
    result: Any | None = None
    ledgers: list[models.ModelCallLedger] = []
    controls: dict[str, Any] | None = None
    error_code: str | None = None
    try:
        result = await gateway.invoke(
            material["prompt_id"],
            material["request"],
            build_trusted_context(material["request"]),
            budget=CallBudget(max_cost_usd=max_total_cost_usd),
        )
        ledgers = list(result.ledgers)
        _assert_canary_semantics(case, material["request"], result)
        if not adapter.results:
            raise AssertionError("Canary completed without safe transport metadata")
        controls = _canary_real_proof(material, result, adapter.results[-1])
    except GatewayError as exc:
        ledgers = list(exc.ledgers)
        error_code = exc.code
    except AssertionError:
        error_code = "OPENAI_LUNA_CANARY_EXPECTATION_FAILED"

    if adapter.request_attempts > 1:
        raise AssertionError("Canary crossed its one-request transport boundary")
    actual_cost = sum(item.actual_cost_usd or 0.0 for item in adapter.results)
    budget_charged = sum(
        max(item.estimated_cost_usd, item.actual_cost_usd or 0.0)
        for item in adapter.results
    )
    if adapter.request_attempts and not adapter.results:
        budget_charged = material["worst_case_usd"]
    ledger = ledgers[-1] if ledgers else None
    transport_result = adapter.results[-1] if adapter.results else None
    effective_model = _observed_effective_model(ledger) if ledger is not None else None
    output_status = None
    validation_order: list[str] = []
    if result is not None:
        output_status = getattr(result.output.status, "value", result.output.status)
        validation_order = [phase.value for phase in result.validation_order]
    row = {
        "case_id": case["case_id"],
        "status": "PASS" if error_code is None else "FAIL",
        "error_code": error_code,
        "defect_severity": (
            None if error_code is None else case["defect_severity_if_failed"]
        ),
        "output_status": output_status,
        "attempts": adapter.request_attempts,
        "actual_cost_usd": round(actual_cost, 8),
        "validation_order": validation_order,
        "controls": controls,
        "budget": _canary_budget_metadata(material),
        **_canary_usage_metadata(transport_result, ledger),
        **_route_metadata(
            material["prompt_id"],
            material["canary_routes"],
            effective_model=effective_model,
        ),
    }
    return {
        "mode": "canary-real",
        "route_profile": OPENAI_ROUTE_PROFILE_ID,
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "estimated_ceiling_usd": round(material["worst_case_usd"], 8),
        "actual_cost_usd": round(actual_cost, 8),
        "budget_charged_usd": round(budget_charged, 8),
        "network_calls": adapter.request_attempts,
        "billable_calls": adapter.request_attempts,
        "max_responses_requests": 1,
        "gateway_retries": 0,
        "prompt_retries": 0,
        "sdk_retries": 0,
        "p10_calls": adapter.prompt_ids.count("P10_ENRICHED_CONTEXT_V1"),
        "p11_calls": adapter.prompt_ids.count("P11_SCHEMA_REPAIR_V1"),
        "sol_calls": 0,
        "cases": [row],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--mode",
        choices=("offline", "real", "canary-dry-run", "canary-real"),
        default="offline",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run one or more named synthetic cases; repeat the flag to compare cases",
    )
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--max-total-cost-usd", type=float, default=0.0)
    args = parser.parse_args()
    cases = _load_cases(args.manifest)
    if args.case_id:
        selected_ids = set(args.case_id)
        known_ids = {str(case["case_id"]) for case in cases}
        unknown = sorted(selected_ids - known_ids)
        if unknown:
            parser.error(f"unknown synthetic case id(s): {', '.join(unknown)}")
        cases = [case for case in cases if case["case_id"] in selected_ids]
    if args.mode in {"real", "canary-real"} and (
        not args.allow_billable or args.max_total_cost_usd <= 0
    ):
        code = (
            "OPENAI_LUNA_CANARY_APPROVAL_REQUIRED"
            if args.mode == "canary-real"
            else "OPENAI_REAL_EVALS_APPROVAL_REQUIRED"
        )
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "code": code,
                    "network_calls": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    try:
        if args.mode == "offline":
            coroutine = _run_offline(cases)
        elif args.mode == "canary-dry-run":
            coroutine = _run_canary_dry_run(cases)
        elif args.mode == "canary-real":
            coroutine = _run_canary_real(
                cases, max_total_cost_usd=args.max_total_cost_usd
            )
        else:
            coroutine = _run_real(
                cases, max_total_cost_usd=args.max_total_cost_usd
            )
        result = asyncio.run(coroutine)
    except OpenAIEvalBlocked as exc:
        code = str(exc)
        if not code.startswith("OPENAI_"):
            code = "OPENAI_EVALS_FAILED"
        print(
            json.dumps(
                {"status": "BLOCKED", "code": code, "network_calls": 0},
                sort_keys=True,
            )
        )
        return 2
    result["status"] = (
        "PASS" if all(row["status"] == "PASS" for row in result["cases"]) else "FAIL"
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
