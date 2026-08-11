"""Immutable registry for the P01-P11 model boundary.

The registry deliberately contains no provider credentials and no executable
student content.  It records only the versioned contract boundary and the
parameters needed by the deterministic route resolver.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Final, Mapping

from comprehension_verification.contracts import SCHEMA_VERSION, model_by_name, models
from comprehension_verification.model_gateway.prompt_text import (
    P11_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    TASK_INSTRUCTIONS,
)


PROMPT_VERSION: Final = "1.1.6"
SYSTEM_PROMPT_ID: Final = "SYS_EVIDENCE_BOUND_V1"
P11_SYSTEM_PROMPT_ID: Final = "SYS_SCHEMA_REPAIR_V1"
PROMPT_ENTRY_VERSIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        # Accepted entries retain their observed boundary. P05 and P11 advance
        # after the stopped 1.1.3 continuation exposed an ambiguous root-level
        # BlueprintReview invariant and an unsafe repair guess. P09 advances
        # after the stopped 1.1.4 continuation exposed a contextual relationship
        # failure. P04 advances after the first product E2E exposed a canonical
        # cross-field invariant that provider JSON Schema cannot express.
        "P02_RUBRIC_NORMALIZE_V1": "1.1.3",
        "P04_BLUEPRINT_BUILD_V1": "1.1.6",
        "P05_BLUEPRINT_REVIEW_V1": "1.1.4",
        "P09_GUIDE_BUILD_V1": "1.1.5",
        "P11_SCHEMA_REPAIR_V1": "1.1.4",
    }
)
PROMPT_SCHEMA_COMPATIBILITY: Final = frozenset(
    {
        ("1.1.2", "1.1.0"),
        ("1.1.3", "1.1.0"),
        ("1.1.4", "1.1.0"),
        ("1.1.5", "1.1.0"),
        ("1.1.6", "1.1.0"),
    }
)

# This mapping is intentionally written out instead of inferred from prose.
# It is the executable version of VALIDACION_CONTRATOS section 5.4.
PROMPT_CONTRACTS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "P01_ACTIVITY_SPEC_V1": ("ActivitySpecRequest", "ActivitySpec"),
        "P02_RUBRIC_NORMALIZE_V1": ("RubricNormalizeRequest", "RubricSpec"),
        "P03_AMBIGUITY_TRIAGE_V1": ("AmbiguityTriageRequest", "AmbiguityReport"),
        "P04_BLUEPRINT_BUILD_V1": ("BlueprintBuildRequest", "AssessmentBlueprint"),
        "P05_BLUEPRINT_REVIEW_V1": ("BlueprintReviewRequest", "BlueprintReview"),
        "P06_EVIDENCE_MAP_V1": ("EvidenceMapRequest", "EvidenceMapPatch"),
        "P07_QUESTION_BUILD_V1": ("QuestionBuildRequest", "QuestionGenerationResult"),
        "P08_QUESTION_REVIEW_V1": ("QuestionReviewRequest", "QuestionReviewResult"),
        "P09_GUIDE_BUILD_V1": ("GuideBuildRequest", "EvaluationGuide"),
        "P10_ENRICHED_CONTEXT_V1": ("QuestionBuildRequest", "QuestionGenerationResult"),
        "P11_SCHEMA_REPAIR_V1": ("SchemaRepairRequest", "SchemaRepairResult"),
    }
)


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """Immutable prompt registry entry.

    ``prompt_hash`` fingerprints the complete executable prompt and registry
    material. A real call is blocked unless an explicit route and adapter are
    installed.
    """

    prompt_id: str
    prompt_version: str
    system_prompt_id: str
    task: str
    input_schema_name: str
    output_schema_name: str
    system_instruction: str
    developer_instruction: str
    reasoning_effort: models.ReasoningEffort
    temperature: float
    max_output_tokens: int
    max_transient_retries: int = 2

    @property
    def prompt_hash(self) -> str:
        material = json.dumps(
            asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"sha256:{sha256(material).hexdigest()}"


def _spec(
    prompt_id: str,
    *,
    task: str,
    effort: models.ReasoningEffort,
    temperature: float = 0.1,
    max_output_tokens: int = 8_000,
    max_transient_retries: int = 2,
) -> PromptSpec:
    input_root, output_root = PROMPT_CONTRACTS[prompt_id]
    # Fail at import time if documentation and canonical roots ever diverge.
    model_by_name(input_root)
    model_by_name(output_root)
    return PromptSpec(
        prompt_id=prompt_id,
        prompt_version=PROMPT_ENTRY_VERSIONS.get(prompt_id, "1.1.2"),
        system_prompt_id=(
            P11_SYSTEM_PROMPT_ID
            if prompt_id == "P11_SCHEMA_REPAIR_V1"
            else SYSTEM_PROMPT_ID
        ),
        task=task,
        input_schema_name=input_root,
        output_schema_name=output_root,
        system_instruction=(
            P11_SYSTEM_INSTRUCTION
            if prompt_id == "P11_SCHEMA_REPAIR_V1"
            else SYSTEM_INSTRUCTION
        ),
        developer_instruction=TASK_INSTRUCTIONS[prompt_id],
        reasoning_effort=effort,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_transient_retries=max_transient_retries,
    )


PROMPT_SPECS: Final[Mapping[str, PromptSpec]] = MappingProxyType(
    {
        "P01_ACTIVITY_SPEC_V1": _spec(
            "P01_ACTIVITY_SPEC_V1",
            task="activity_specification",
            effort=models.ReasoningEffort.MEDIUM,
        ),
        "P02_RUBRIC_NORMALIZE_V1": _spec(
            "P02_RUBRIC_NORMALIZE_V1",
            task="rubric_normalization",
            effort=models.ReasoningEffort.MEDIUM,
        ),
        "P03_AMBIGUITY_TRIAGE_V1": _spec(
            "P03_AMBIGUITY_TRIAGE_V1",
            task="ambiguity_triage",
            effort=models.ReasoningEffort.HIGH,
        ),
        "P04_BLUEPRINT_BUILD_V1": _spec(
            "P04_BLUEPRINT_BUILD_V1",
            task="blueprint_build",
            effort=models.ReasoningEffort.HIGH,
            max_output_tokens=16_000,
        ),
        "P05_BLUEPRINT_REVIEW_V1": _spec(
            "P05_BLUEPRINT_REVIEW_V1",
            task="blueprint_review",
            effort=models.ReasoningEffort.HIGH,
            max_output_tokens=16_000,
        ),
        "P06_EVIDENCE_MAP_V1": _spec(
            "P06_EVIDENCE_MAP_V1",
            task="evidence_mapping",
            effort=models.ReasoningEffort.HIGH,
            max_output_tokens=16_000,
        ),
        "P07_QUESTION_BUILD_V1": _spec(
            "P07_QUESTION_BUILD_V1",
            task="question_generation",
            effort=models.ReasoningEffort.HIGH,
            max_output_tokens=10_000,
        ),
        "P08_QUESTION_REVIEW_V1": _spec(
            "P08_QUESTION_REVIEW_V1",
            task="question_review",
            effort=models.ReasoningEffort.HIGH,
        ),
        "P09_GUIDE_BUILD_V1": _spec(
            "P09_GUIDE_BUILD_V1",
            task="guide_build",
            effort=models.ReasoningEffort.HIGH,
            max_output_tokens=10_000,
        ),
        "P10_ENRICHED_CONTEXT_V1": _spec(
            "P10_ENRICHED_CONTEXT_V1",
            task="enriched_question_generation",
            effort=models.ReasoningEffort.HIGH,
            max_output_tokens=10_000,
        ),
        "P11_SCHEMA_REPAIR_V1": _spec(
            "P11_SCHEMA_REPAIR_V1",
            task="schema_repair",
            effort=models.ReasoningEffort.LOW,
            temperature=0.0,
            max_transient_retries=0,
        ),
    }
)


def prompt_spec(prompt_id: str) -> PromptSpec:
    try:
        return PROMPT_SPECS[prompt_id]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt_id: {prompt_id}") from exc


def assert_registry_complete() -> None:
    """Raise immediately if a root or registry entry drifts."""

    if set(PROMPT_SPECS) != set(PROMPT_CONTRACTS):
        raise RuntimeError("P01-P11 prompt registry is incomplete")
    for prompt_id, (input_root, output_root) in PROMPT_CONTRACTS.items():
        spec = PROMPT_SPECS[prompt_id]
        if (spec.input_schema_name, spec.output_schema_name) != (
            input_root,
            output_root,
        ):
            raise RuntimeError(f"Contract drift for {prompt_id}")
        if (spec.prompt_version, SCHEMA_VERSION) not in PROMPT_SCHEMA_COMPATIBILITY:
            raise RuntimeError(f"Unsupported prompt/schema compatibility for {prompt_id}")
        if not spec.system_instruction or not spec.developer_instruction:
            raise RuntimeError(f"Executable prompt material is missing for {prompt_id}")


assert_registry_complete()
