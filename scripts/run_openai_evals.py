#!/usr/bin/env python3
"""Governed synthetic OpenAI golden-set harness.

Offline is the default and never constructs an OpenAI client. Real mode is
prepared for a later human gate and requires three independent opt-ins.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from comprehension_verification.contracts import SCHEMA_VERSION, model_by_name, models
from comprehension_verification.model_gateway import (
    CallBudget,
    GatewayConfig,
    GatewayError,
    GatewayMode,
    MockBehavior,
    ModelGateway,
    OpenAIResponsesAdapter,
    PROMPT_CONTRACTS,
    build_mock_request,
    build_openai_cost_estimator,
    build_openai_routes,
    build_trusted_context,
    estimate_openai_input_tokens,
)
from comprehension_verification.model_gateway.openai_schema import (
    structured_output_format,
)
from comprehension_verification.model_gateway.registry import prompt_spec


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/fixtures/openai_evals/v1/synthetic_cases.json"
INJECTION_MARKER = "IGNORE_PREVIOUS_INSTRUCTIONS_SYNTHETIC_MARKER"
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
            }
        )
    return {
        "mode": "offline",
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
            rows.append(
                {
                    "case_id": case["case_id"],
                    "status": "FAIL",
                    "error_code": "OPENAI_REAL_EVAL_EXPECTATION_FAILED",
                    "attempts": len(result.ledgers),
                    "model": result.ledgers[-1].route.model,
                    "actual_cost_usd": round(cost, 8),
                }
            )
            break
        rows.append(
            {
                "case_id": case["case_id"],
                "status": "PASS",
                "attempts": len(result.ledgers),
                "model": result.ledgers[-1].route.model,
                "actual_cost_usd": round(cost, 8),
            }
        )
    return {
        "mode": "real",
        "classification": "SYNTHETIC_ONLY_NO_STUDENT_DATA",
        "estimated_ceiling_usd": round(estimated_ceiling, 8),
        "actual_cost_usd": round(actual_total, 8),
        "budget_charged_usd": round(budget_charged_total, 8),
        "network_calls": network_calls,
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mode", choices=("offline", "real"), default="offline")
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
    if args.mode == "real" and (
        not args.allow_billable or args.max_total_cost_usd <= 0
    ):
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "code": "OPENAI_REAL_EVALS_APPROVAL_REQUIRED",
                    "network_calls": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    try:
        result = asyncio.run(
            _run_offline(cases)
            if args.mode == "offline"
            else _run_real(cases, max_total_cost_usd=args.max_total_cost_usd)
        )
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
