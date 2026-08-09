"""Explicit, non-heuristic OpenAI route profile for P01-P09 and P11."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Final, Mapping

from pydantic import BaseModel

from comprehension_verification.contracts import models
from comprehension_verification.model_gateway.openai_pricing import (
    PRICING_OBSERVED_DATE,
    estimate_cost_usd,
)
from comprehension_verification.model_gateway.registry import PROMPT_SPECS, PromptSpec
from comprehension_verification.model_gateway.openai_schema import (
    structured_output_format,
)


SOL_MODEL_ID: Final = "gpt-5.6-sol"
LUNA_MODEL_ID: Final = "gpt-5.6-luna"
OPENAI_PROVIDER_ID: Final = "openai"
OPENAI_ROUTE_PROFILE_ID: Final = "LUNA_BASELINE_V1"
REQUEST_FRAMING_TOKEN_ALLOWANCE: Final = 1_024


@dataclass(frozen=True, slots=True)
class ApprovedOpenAIRoute:
    """One immutable entry in the human-authorized experimental profile."""

    model: str
    reasoning_effort: models.ReasoningEffort


OPENAI_ROUTE_PROFILE: Final[Mapping[str, ApprovedOpenAIRoute]] = MappingProxyType(
    {
        "P01_ACTIVITY_SPEC_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.MEDIUM
        ),
        "P02_RUBRIC_NORMALIZE_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.MEDIUM
        ),
        "P03_AMBIGUITY_TRIAGE_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P04_BLUEPRINT_BUILD_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P05_BLUEPRINT_REVIEW_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P06_EVIDENCE_MAP_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P07_QUESTION_BUILD_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P08_QUESTION_REVIEW_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P09_GUIDE_BUILD_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.HIGH
        ),
        "P11_SCHEMA_REPAIR_V1": ApprovedOpenAIRoute(
            LUNA_MODEL_ID, models.ReasoningEffort.LOW
        ),
    }
)
OPENAI_MODEL_BY_PROMPT: Final[Mapping[str, str]] = MappingProxyType(
    {
        prompt_id: approved.model
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)


def build_openai_routes(*, max_call_cost_usd: float) -> Mapping[str, models.ModelRoute]:
    if max_call_cost_usd <= 0:
        raise ValueError("max_call_cost_usd must be positive")
    expected_prompt_ids = set(PROMPT_SPECS) - {"P10_ENRICHED_CONTEXT_V1"}
    if set(OPENAI_ROUTE_PROFILE) != expected_prompt_ids:
        raise AssertionError("LUNA_BASELINE_V1 must cover exactly P01-P09 and P11")
    if any(
        approved.model != LUNA_MODEL_ID
        for approved in OPENAI_ROUTE_PROFILE.values()
    ):
        raise AssertionError("LUNA_BASELINE_V1 cannot route silently to another model")
    capabilities = models.ModelCapabilities(
        input_modalities=[
            models.ModelInputModality.TEXT,
            models.ModelInputModality.IMAGE,
        ],
        output_modalities=[models.ModelOutputModality.STRUCTURED_JSON],
        structured_outputs=True,
        max_context_tokens=1_050_000,
        supported_reasoning_efforts=[
            models.ReasoningEffort.LOW,
            models.ReasoningEffort.MEDIUM,
            models.ReasoningEffort.HIGH,
        ],
        # No project-level ZDR approval has been verified. store=false is not
        # represented as ZDR and the route therefore remains DEFAULT retention.
        supports_zero_data_retention=False,
        supported_regions=[],
    )
    routes: dict[str, models.ModelRoute] = {}
    for prompt_id, approved in OPENAI_ROUTE_PROFILE.items():
        spec = PROMPT_SPECS[prompt_id]
        if spec.reasoning_effort != approved.reasoning_effort:
            raise AssertionError(
                f"Prompt/profile reasoning drift for {prompt_id}: "
                f"{spec.reasoning_effort} != {approved.reasoning_effort}"
            )
        routes[prompt_id] = models.ModelRoute(
            route_id=(
                f"route_openai_{OPENAI_ROUTE_PROFILE_ID.lower()}_"
                f"{prompt_id.lower()}"
            ),
            task=spec.task,
            provider=OPENAI_PROVIDER_ID,
            model=approved.model,
            # Official pages publish these explicit model IDs but no dated
            # snapshot ID. Record the observed callable ID without inventing one.
            model_snapshot=approved.model,
            reasoning_effort=approved.reasoning_effort,
            temperature=spec.temperature,
            capabilities=capabilities,
            retention_mode="DEFAULT",
            region=None,
            max_cost_usd=max_call_cost_usd,
            # Keep normal calls below the documented long-context price tier.
            max_input_tokens=250_000,
            max_output_tokens=spec.max_output_tokens,
            fallback_route_id=None,
            reason_codes=[
                f"ROUTE_PROFILE_{OPENAI_ROUTE_PROFILE_ID}",
                "LUNA_ONLY_EXPERIMENTAL_BASELINE",
                "EXPLICIT_APPROVED_MODEL_ID",
                "NO_DYNAMIC_MODEL_SELECTION",
                "NO_MODEL_FALLBACK",
                "SOL_COMPARISON_REQUIRES_FUTURE_HUMAN_AUTHORIZATION",
                "NO_DATED_SNAPSHOT_PUBLISHED_MODEL_ID_RECORDED",
                "RESPONSES_API_STRUCTURED_OUTPUTS",
                "STORE_FALSE_NOT_ZDR",
                "BACKGROUND_FALSE",
                "TOOLS_EMPTY",
                "TRUNCATION_DISABLED",
                "TEMPERATURE_NOT_SENT_UNDOCUMENTED_WITH_REASONING",
                f"CONSERVATIVE_PRICE_OBSERVED_{PRICING_OBSERVED_DATE.replace('-', '')}",
            ],
        )
    if "P10_ENRICHED_CONTEXT_V1" in routes:
        raise AssertionError("P10 must not have a callable OpenAI route")
    return MappingProxyType(routes)


def build_openai_cost_estimator(
    routes: Mapping[str, models.ModelRoute],
) -> Callable[[PromptSpec, int], float]:
    """Estimate against max output before routing; fail if a route is absent."""

    def estimate(spec: PromptSpec, input_tokens: int) -> float:
        try:
            route = routes[spec.prompt_id]
        except KeyError as exc:
            raise ValueError(f"No approved real route for {spec.prompt_id}") from exc
        return estimate_cost_usd(
            model=route.model,
            input_tokens=input_tokens,
            output_tokens=spec.max_output_tokens,
        )

    return estimate


def openai_developer_instruction(
    spec: PromptSpec, envelope: models.ModelTaskEnvelope
) -> str:
    """Bind the canonical prompt template to trusted, non-content call controls."""

    controls = {
        "task_name": spec.task,
        "output_language": envelope.trusted_context.output_language,
        "context_mode": envelope.trusted_context.context_mode,
        "schema_name": spec.output_schema_name,
        "schema_version": envelope.output_schema_version,
        "prompt_id": spec.prompt_id,
        "prompt_version": spec.prompt_version,
        "policy_location": "validated envelope payload fields",
    }
    return (
        spec.developer_instruction
        + "\nCALL_CONTROLS_JSON (trusted metadata, not student content):\n"
        + json.dumps(
            controls,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\nResolve only this task. Do not generate objects for another stage."
    )


def estimate_openai_input_tokens(
    spec: PromptSpec,
    request: BaseModel,
    envelope: models.ModelTaskEnvelope,
) -> int:
    """Conservatively account for instructions, envelope, and strict schema."""

    request_shape = {
        "instructions": spec.system_instruction,
        "input": [
            {
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": openai_developer_instruction(spec, envelope),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            envelope.model_dump(mode="json"),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                ],
            },
        ],
        "reasoning": {"effort": spec.reasoning_effort.value.lower()},
        "text": {"format": structured_output_format(spec, request)},
    }
    serialized = json.dumps(
        request_shape,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    # A byte-per-token ceiling is deliberately stricter than the common
    # chars/4 estimate. The fixed allowance covers provider message framing
    # that is not represented by the JSON serialization.
    return max(1, len(serialized) + REQUEST_FRAMING_TOKEN_ALLOWANCE)
