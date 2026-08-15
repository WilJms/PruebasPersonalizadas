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
from comprehension_verification.model_gateway.registry import (
    PROMPT_SPECS,
    PromptSpec,
)
from comprehension_verification.model_gateway.openai_schema import (
    structured_output_format,
)


SOL_MODEL_ID: Final = "gpt-5.6-sol"
TERRA_MODEL_ID: Final = "gpt-5.6-terra"
LUNA_MODEL_ID: Final = "gpt-5.6-luna"
OPENAI_APPROVED_MODEL_IDS: Final = frozenset(
    {LUNA_MODEL_ID, SOL_MODEL_ID, TERRA_MODEL_ID}
)
OPENAI_PROVIDER_ID: Final = "openai"
OPENAI_ROUTE_PROFILE_ID: Final = "LUNA_BASELINE_V1"
OPENAI_XHIGH_ROUTE_PROFILE_ID: Final = "LUNA_XHIGH_V1"
OPENAI_XHIGH_PROMPT_IDS: Final = frozenset(
    {
        "P04_BLUEPRINT_BUILD_V1",
        "P05_BLUEPRINT_REVIEW_V1",
        "P06_EVIDENCE_MAP_V1",
        "P07_QUESTION_BUILD_V1",
        "P08_QUESTION_REVIEW_V1",
        "P09_GUIDE_BUILD_V1",
    }
)
OPENAI_MAX_ROUTE_PROFILE_ID: Final = "LUNA_MAX_V1"
OPENAI_MAX_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID: Final = "TERRA_MEDIUM_V1"
OPENAI_TERRA_MEDIUM_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID: Final = "TERRA_HIGH_V1"
OPENAI_TERRA_HIGH_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID: Final = "TERRA_XHIGH_V1"
OPENAI_TERRA_XHIGH_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID: Final = "SOL_MEDIUM_V1"
OPENAI_SOL_MEDIUM_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
OPENAI_SOL_HIGH_ROUTE_PROFILE_ID: Final = "SOL_HIGH_V1"
OPENAI_SOL_HIGH_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID: Final = "SOL_XHIGH_V1"
OPENAI_SOL_XHIGH_PROMPT_IDS: Final = OPENAI_XHIGH_PROMPT_IDS
REQUEST_FRAMING_TOKEN_ALLOWANCE: Final = 1_024
OPENAI_MAX_INPUT_TOKENS: Final = 250_000
# The first manual-evaluation profile buys no automatic transport retry. A
# durable teacher retry remains available at the application boundary.
OPENAI_ROUTE_PROFILE_MAX_TRANSIENT_RETRIES: Final = 0
# Qualification v1.1.4 measured a 76,482-token P11 worst-case reservation.
# Inputs above this explicit headroom fail before transport instead of turning
# structural repair into an open-ended cost surface.
OPENAI_P11_MAX_INPUT_TOKENS: Final = 80_000


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
OPENAI_XHIGH_ROUTE_PROFILE: Final[Mapping[str, ApprovedOpenAIRoute]] = (
    MappingProxyType(
        {
            prompt_id: ApprovedOpenAIRoute(
                approved.model,
                (
                    models.ReasoningEffort.XHIGH
                    if prompt_id in OPENAI_XHIGH_PROMPT_IDS
                    else approved.reasoning_effort
                ),
            )
            for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
        }
    )
)
OPENAI_MAX_ROUTE_PROFILE: Final[Mapping[str, ApprovedOpenAIRoute]] = (
    MappingProxyType(
        {
            prompt_id: ApprovedOpenAIRoute(
                approved.model,
                (
                    models.ReasoningEffort.MAX
                    if prompt_id in OPENAI_MAX_PROMPT_IDS
                    else approved.reasoning_effort
                ),
            )
            for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
        }
    )
)
OPENAI_TERRA_MEDIUM_ROUTE_PROFILE: Final[
    Mapping[str, ApprovedOpenAIRoute]
] = MappingProxyType(
    {
        prompt_id: ApprovedOpenAIRoute(
            TERRA_MODEL_ID,
            (
                models.ReasoningEffort.MEDIUM
                if prompt_id in OPENAI_TERRA_MEDIUM_PROMPT_IDS
                else approved.reasoning_effort
            ),
        )
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)
OPENAI_TERRA_HIGH_ROUTE_PROFILE: Final[
    Mapping[str, ApprovedOpenAIRoute]
] = MappingProxyType(
    {
        prompt_id: ApprovedOpenAIRoute(
            TERRA_MODEL_ID,
            (
                models.ReasoningEffort.HIGH
                if prompt_id in OPENAI_TERRA_HIGH_PROMPT_IDS
                else approved.reasoning_effort
            ),
        )
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)
OPENAI_TERRA_XHIGH_ROUTE_PROFILE: Final[
    Mapping[str, ApprovedOpenAIRoute]
] = MappingProxyType(
    {
        prompt_id: ApprovedOpenAIRoute(
            TERRA_MODEL_ID,
            (
                models.ReasoningEffort.XHIGH
                if prompt_id in OPENAI_TERRA_XHIGH_PROMPT_IDS
                else approved.reasoning_effort
            ),
        )
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)
OPENAI_SOL_MEDIUM_ROUTE_PROFILE: Final[
    Mapping[str, ApprovedOpenAIRoute]
] = MappingProxyType(
    {
        prompt_id: ApprovedOpenAIRoute(
            SOL_MODEL_ID,
            (
                models.ReasoningEffort.MEDIUM
                if prompt_id in OPENAI_SOL_MEDIUM_PROMPT_IDS
                else approved.reasoning_effort
            ),
        )
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)
OPENAI_SOL_HIGH_ROUTE_PROFILE: Final[
    Mapping[str, ApprovedOpenAIRoute]
] = MappingProxyType(
    {
        prompt_id: ApprovedOpenAIRoute(SOL_MODEL_ID, approved.reasoning_effort)
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)
OPENAI_SOL_XHIGH_ROUTE_PROFILE: Final[
    Mapping[str, ApprovedOpenAIRoute]
] = MappingProxyType(
    {
        prompt_id: ApprovedOpenAIRoute(
            SOL_MODEL_ID,
            (
                models.ReasoningEffort.XHIGH
                if prompt_id in OPENAI_SOL_XHIGH_PROMPT_IDS
                else approved.reasoning_effort
            ),
        )
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)
OPENAI_ROUTE_PROFILES: Final[
    Mapping[str, Mapping[str, ApprovedOpenAIRoute]]
] = MappingProxyType(
    {
        OPENAI_ROUTE_PROFILE_ID: OPENAI_ROUTE_PROFILE,
        OPENAI_XHIGH_ROUTE_PROFILE_ID: OPENAI_XHIGH_ROUTE_PROFILE,
        OPENAI_MAX_ROUTE_PROFILE_ID: OPENAI_MAX_ROUTE_PROFILE,
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID: (
            OPENAI_TERRA_MEDIUM_ROUTE_PROFILE
        ),
        OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID: OPENAI_TERRA_HIGH_ROUTE_PROFILE,
        OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID: (
            OPENAI_TERRA_XHIGH_ROUTE_PROFILE
        ),
        OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID: OPENAI_SOL_MEDIUM_ROUTE_PROFILE,
        OPENAI_SOL_HIGH_ROUTE_PROFILE_ID: OPENAI_SOL_HIGH_ROUTE_PROFILE,
        OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID: OPENAI_SOL_XHIGH_ROUTE_PROFILE,
    }
)
OPENAI_ROUTE_PROFILE_REASON_CODE: Final[Mapping[str, str]] = MappingProxyType(
    {
        OPENAI_ROUTE_PROFILE_ID: "LUNA_ONLY_EXPERIMENTAL_BASELINE",
        OPENAI_XHIGH_ROUTE_PROFILE_ID: (
            "LUNA_ONLY_EXPERIMENTAL_XHIGH_QUALIFICATION"
        ),
        OPENAI_MAX_ROUTE_PROFILE_ID: "LUNA_ONLY_EXPERIMENTAL_MAX_QUALIFICATION",
        OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID: (
            "TERRA_ONLY_EXPERIMENTAL_MEDIUM_QUALIFICATION"
        ),
        OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID: (
            "TERRA_ONLY_EXPERIMENTAL_HIGH_QUALIFICATION"
        ),
        OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID: (
            "TERRA_ONLY_EXPERIMENTAL_XHIGH_QUALIFICATION"
        ),
        OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID: (
            "SOL_ONLY_EXPERIMENTAL_MEDIUM_QUALIFICATION"
        ),
        OPENAI_SOL_HIGH_ROUTE_PROFILE_ID: (
            "SOL_ONLY_EXPERIMENTAL_HIGH_QUALIFICATION"
        ),
        OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID: (
            "SOL_ONLY_EXPERIMENTAL_XHIGH_QUALIFICATION"
        ),
    }
)
OPENAI_MODEL_BY_PROMPT: Final[Mapping[str, str]] = MappingProxyType(
    {
        prompt_id: approved.model
        for prompt_id, approved in OPENAI_ROUTE_PROFILE.items()
    }
)


def _route_id(route_profile_id: str, prompt_id: str) -> str:
    return f"route_openai_{route_profile_id.lower()}_{prompt_id.lower()}"


def openai_route_matches_profile(
    prompt_id: str,
    route: models.ModelRoute,
) -> bool:
    """Accept only an exact, explicitly named profile entry.

    The XHIGH, MAX, Terra, and Sol qualifications deliberately leave the
    canonical prompt registry at HIGH so its executable prompt hashes remain
    unchanged. These profile checks are the sole authorized routing exceptions.
    """

    spec = PROMPT_SPECS.get(prompt_id)
    if spec is None:
        return False
    profile_codes = {
        code
        for code in route.reason_codes
        if code.startswith("ROUTE_PROFILE_")
    }
    for route_profile_id, profile in OPENAI_ROUTE_PROFILES.items():
        approved = profile.get(prompt_id)
        if approved is None:
            continue
        if (
            route.route_id == _route_id(route_profile_id, prompt_id)
            and profile_codes == {f"ROUTE_PROFILE_{route_profile_id}"}
            and route.provider == OPENAI_PROVIDER_ID
            and route.model == approved.model
            and route.model_snapshot == approved.model
            and route.reasoning_effort == approved.reasoning_effort
            and route.task == spec.task
            and route.temperature == spec.temperature
            and route.max_output_tokens == spec.max_output_tokens
            and route.fallback_route_id is None
        ):
            return True
    return False


def build_openai_routes(
    *,
    max_call_cost_usd: float,
    route_profile_id: str = OPENAI_ROUTE_PROFILE_ID,
) -> Mapping[str, models.ModelRoute]:
    if max_call_cost_usd <= 0:
        raise ValueError("max_call_cost_usd must be positive")
    try:
        route_profile = OPENAI_ROUTE_PROFILES[route_profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown OpenAI route profile: {route_profile_id}") from exc
    expected_prompt_ids = set(PROMPT_SPECS) - {"P10_ENRICHED_CONTEXT_V1"}
    if set(route_profile) != expected_prompt_ids:
        raise AssertionError(
            f"{route_profile_id} must cover exactly P01-P09 and P11"
        )
    expected_model = (
        TERRA_MODEL_ID
        if route_profile_id
        in {
            OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID,
            OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
        }
        else SOL_MODEL_ID
        if route_profile_id
        in {
            OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
            OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
        }
        else LUNA_MODEL_ID
    )
    if any(approved.model != expected_model for approved in route_profile.values()):
        raise AssertionError(
            f"{route_profile_id} cannot route silently to another model"
        )
    expected_xhigh_prompts = (
        OPENAI_XHIGH_PROMPT_IDS
        if route_profile_id
        in {
            OPENAI_XHIGH_ROUTE_PROFILE_ID,
            OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
            OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
        }
        else frozenset()
    )
    actual_xhigh_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if approved.reasoning_effort == models.ReasoningEffort.XHIGH
    )
    if actual_xhigh_prompts != expected_xhigh_prompts:
        raise AssertionError(
            f"Unexpected XHIGH route surface for {route_profile_id}: "
            f"{sorted(actual_xhigh_prompts)}"
        )
    expected_max_prompts = (
        OPENAI_MAX_PROMPT_IDS
        if route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
        else frozenset()
    )
    actual_max_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if approved.reasoning_effort == models.ReasoningEffort.MAX
    )
    if actual_max_prompts != expected_max_prompts:
        raise AssertionError(
            f"Unexpected MAX route surface for {route_profile_id}: "
            f"{sorted(actual_max_prompts)}"
        )
    actual_terra_medium_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if (
            prompt_id in OPENAI_TERRA_MEDIUM_PROMPT_IDS
            and approved.model == TERRA_MODEL_ID
            and approved.reasoning_effort == models.ReasoningEffort.MEDIUM
        )
    )
    expected_terra_medium_prompts = (
        OPENAI_TERRA_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
        else frozenset()
    )
    if actual_terra_medium_prompts != expected_terra_medium_prompts:
        raise AssertionError(
            f"Unexpected Terra MEDIUM route surface for {route_profile_id}: "
            f"{sorted(actual_terra_medium_prompts)}"
        )
    actual_terra_high_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if (
            prompt_id in OPENAI_TERRA_HIGH_PROMPT_IDS
            and approved.model == TERRA_MODEL_ID
            and approved.reasoning_effort == models.ReasoningEffort.HIGH
        )
    )
    expected_terra_high_prompts = (
        OPENAI_TERRA_HIGH_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_HIGH_ROUTE_PROFILE_ID
        else frozenset()
    )
    if actual_terra_high_prompts != expected_terra_high_prompts:
        raise AssertionError(
            f"Unexpected Terra HIGH route surface for {route_profile_id}: "
            f"{sorted(actual_terra_high_prompts)}"
        )
    actual_terra_xhigh_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if (
            prompt_id in OPENAI_TERRA_XHIGH_PROMPT_IDS
            and approved.model == TERRA_MODEL_ID
            and approved.reasoning_effort == models.ReasoningEffort.XHIGH
        )
    )
    expected_terra_xhigh_prompts = (
        OPENAI_TERRA_XHIGH_PROMPT_IDS
        if route_profile_id == OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID
        else frozenset()
    )
    if actual_terra_xhigh_prompts != expected_terra_xhigh_prompts:
        raise AssertionError(
            f"Unexpected Terra XHIGH route surface for {route_profile_id}: "
            f"{sorted(actual_terra_xhigh_prompts)}"
        )
    actual_sol_medium_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if (
            prompt_id in OPENAI_SOL_MEDIUM_PROMPT_IDS
            and approved.model == SOL_MODEL_ID
            and approved.reasoning_effort == models.ReasoningEffort.MEDIUM
        )
    )
    expected_sol_medium_prompts = (
        OPENAI_SOL_MEDIUM_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
        else frozenset()
    )
    if actual_sol_medium_prompts != expected_sol_medium_prompts:
        raise AssertionError(
            f"Unexpected Sol MEDIUM route surface for {route_profile_id}: "
            f"{sorted(actual_sol_medium_prompts)}"
        )
    actual_sol_high_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if (
            prompt_id in OPENAI_SOL_HIGH_PROMPT_IDS
            and approved.model == SOL_MODEL_ID
            and approved.reasoning_effort == models.ReasoningEffort.HIGH
        )
    )
    expected_sol_high_prompts = (
        OPENAI_SOL_HIGH_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_HIGH_ROUTE_PROFILE_ID
        else frozenset()
    )
    if actual_sol_high_prompts != expected_sol_high_prompts:
        raise AssertionError(
            f"Unexpected Sol HIGH route surface for {route_profile_id}: "
            f"{sorted(actual_sol_high_prompts)}"
        )
    actual_sol_xhigh_prompts = frozenset(
        prompt_id
        for prompt_id, approved in route_profile.items()
        if (
            prompt_id in OPENAI_SOL_XHIGH_PROMPT_IDS
            and approved.model == SOL_MODEL_ID
            and approved.reasoning_effort == models.ReasoningEffort.XHIGH
        )
    )
    expected_sol_xhigh_prompts = (
        OPENAI_SOL_XHIGH_PROMPT_IDS
        if route_profile_id == OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID
        else frozenset()
    )
    if actual_sol_xhigh_prompts != expected_sol_xhigh_prompts:
        raise AssertionError(
            f"Unexpected Sol XHIGH route surface for {route_profile_id}: "
            f"{sorted(actual_sol_xhigh_prompts)}"
        )
    capabilities = models.ModelCapabilities(
        # Every document is parsed and normalized before the gateway. The
        # adapter serializes only the validated envelope; it does not send
        # provider-native images or PDFs.
        input_modalities=[models.ModelInputModality.TEXT],
        output_modalities=[models.ModelOutputModality.STRUCTURED_JSON],
        structured_outputs=True,
        max_context_tokens=1_050_000,
        supported_reasoning_efforts=[
            models.ReasoningEffort.LOW,
            models.ReasoningEffort.MEDIUM,
            models.ReasoningEffort.HIGH,
            models.ReasoningEffort.XHIGH,
            models.ReasoningEffort.MAX,
        ],
        # No project-level ZDR approval has been verified. store=false is not
        # represented as ZDR and the route therefore remains DEFAULT retention.
        supports_zero_data_retention=False,
        supported_regions=[],
    )
    routes: dict[str, models.ModelRoute] = {}
    for prompt_id, approved in route_profile.items():
        spec = PROMPT_SPECS[prompt_id]
        is_authorized_xhigh_override = (
            route_profile_id
            in {
                OPENAI_XHIGH_ROUTE_PROFILE_ID,
                OPENAI_TERRA_XHIGH_ROUTE_PROFILE_ID,
                OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
            }
            and prompt_id in OPENAI_XHIGH_PROMPT_IDS
            and spec.reasoning_effort == models.ReasoningEffort.HIGH
            and approved.reasoning_effort == models.ReasoningEffort.XHIGH
        )
        is_authorized_max_override = (
            route_profile_id == OPENAI_MAX_ROUTE_PROFILE_ID
            and prompt_id in OPENAI_MAX_PROMPT_IDS
            and spec.reasoning_effort == models.ReasoningEffort.HIGH
            and approved.reasoning_effort == models.ReasoningEffort.MAX
        )
        is_authorized_terra_medium_override = (
            route_profile_id == OPENAI_TERRA_MEDIUM_ROUTE_PROFILE_ID
            and prompt_id in OPENAI_TERRA_MEDIUM_PROMPT_IDS
            and spec.reasoning_effort == models.ReasoningEffort.HIGH
            and approved.reasoning_effort == models.ReasoningEffort.MEDIUM
        )
        is_authorized_sol_medium_override = (
            route_profile_id == OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID
            and prompt_id in OPENAI_SOL_MEDIUM_PROMPT_IDS
            and spec.reasoning_effort == models.ReasoningEffort.HIGH
            and approved.reasoning_effort == models.ReasoningEffort.MEDIUM
        )
        if (
            spec.reasoning_effort != approved.reasoning_effort
            and not is_authorized_xhigh_override
            and not is_authorized_max_override
            and not is_authorized_terra_medium_override
            and not is_authorized_sol_medium_override
        ):
            raise AssertionError(
                f"Prompt/profile reasoning drift for {prompt_id}: "
                f"{spec.reasoning_effort} != {approved.reasoning_effort}"
            )
        routes[prompt_id] = models.ModelRoute(
            route_id=_route_id(route_profile_id, prompt_id),
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
            max_input_tokens=(
                OPENAI_P11_MAX_INPUT_TOKENS
                if prompt_id == "P11_SCHEMA_REPAIR_V1"
                else OPENAI_MAX_INPUT_TOKENS
            ),
            max_output_tokens=spec.max_output_tokens,
            fallback_route_id=None,
            reason_codes=[
                f"ROUTE_PROFILE_{route_profile_id}",
                OPENAI_ROUTE_PROFILE_REASON_CODE[route_profile_id],
                *(
                    ["REASONING_EFFORT_OVERRIDE_HIGH_TO_XHIGH"]
                    if is_authorized_xhigh_override
                    else []
                ),
                *(
                    ["REASONING_EFFORT_OVERRIDE_HIGH_TO_MAX"]
                    if is_authorized_max_override
                    else []
                ),
                *(
                    ["REASONING_EFFORT_OVERRIDE_HIGH_TO_MEDIUM"]
                    if (
                        is_authorized_terra_medium_override
                        or is_authorized_sol_medium_override
                    )
                    else []
                ),
                "EXPLICIT_APPROVED_MODEL_ID",
                "NO_DYNAMIC_MODEL_SELECTION",
                "NO_MODEL_FALLBACK",
                "GATEWAY_RETRIES_0_MANUAL_EVAL",
                "FULL_CACHE_WRITE_BUDGET_RESERVATION",
                *(
                    ["P11_INPUT_LIMIT_80000"]
                    if prompt_id == "P11_SCHEMA_REPAIR_V1"
                    else []
                ),
                *(
                    ["SOL_ADAPTIVE_REASONING_LADDER_AUTHORIZED"]
                    if route_profile_id
                    in {
                        OPENAI_SOL_MEDIUM_ROUTE_PROFILE_ID,
                        OPENAI_SOL_HIGH_ROUTE_PROFILE_ID,
                        OPENAI_SOL_XHIGH_ROUTE_PROFILE_ID,
                    }
                    else ["SOL_COMPARISON_REQUIRES_FUTURE_HUMAN_AUTHORIZATION"]
                ),
                "NO_DATED_SNAPSHOT_PUBLISHED_MODEL_ID_RECORDED",
                "RESPONSES_API_STRUCTURED_OUTPUTS",
                "PARSED_TEXT_ONLY_NO_PROVIDER_IMAGE_OR_PDF",
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
    """Reserve max output and full cache-write input before routing.

    Observed Responses usage can classify almost the complete request input as
    cache-write input, whose current price is 1.25 times ordinary input.  The
    transport has not happened when this estimate is evaluated, so treating
    every estimated input token as a cache write is the only fail-closed choice.
    """

    def estimate(spec: PromptSpec, input_tokens: int) -> float:
        try:
            route = routes[spec.prompt_id]
        except KeyError as exc:
            raise ValueError(f"No approved real route for {spec.prompt_id}") from exc
        return estimate_cost_usd(
            model=route.model,
            input_tokens=input_tokens,
            output_tokens=spec.max_output_tokens,
            cache_write_tokens=input_tokens,
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
        "schema_name": spec.provider_output_schema_name,
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
    *,
    reasoning_effort: models.ReasoningEffort | None = None,
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
        "reasoning": {
            "effort": (reasoning_effort or spec.reasoning_effort).value.lower()
        },
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


def build_openai_input_token_estimator(
    routes: Mapping[str, models.ModelRoute],
) -> Callable[[PromptSpec, BaseModel, models.ModelTaskEnvelope], int]:
    """Bind conservative request serialization to the effective route effort."""

    def estimate(
        spec: PromptSpec,
        request: BaseModel,
        envelope: models.ModelTaskEnvelope,
    ) -> int:
        try:
            route = routes[spec.prompt_id]
        except KeyError as exc:
            raise ValueError(f"No approved real route for {spec.prompt_id}") from exc
        return estimate_openai_input_tokens(
            spec,
            request,
            envelope,
            reasoning_effort=route.reasoning_effort,
        )

    return estimate
