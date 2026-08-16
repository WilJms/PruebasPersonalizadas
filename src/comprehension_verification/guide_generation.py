"""Deterministic post-approval P09 alias boundary and guide materializer."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

from .canonical import canonical_hash, stable_id
from .contracts import models as m
from .question_generation import generated_text_safety_code


P09_ALIAS_ENVELOPE_VERSION = "p09-alias-envelope/1.0.0"
P09_MATERIALIZER_VERSION = "p09-guide-materializer/1.0.0"
P09_MATERIALIZER_BOUNDARY_FORMAT = "p09-materializer-boundary/1.0.0"
P09_GUIDE_POLICY_VERSION = "p09-guide-enrichment-policy/1.0.0"
_P09_GLOBAL_POLICY_NOTICE = re.compile(
    r"\b(autor(?:ía)?|uso de ia|hecho por ia|fraude|historial del proceso|"
    r"proceso histórico|system prompt|prompt del sistema)\b",
    flags=re.IGNORECASE,
)


class GuideGenerationCompilationError(ValueError):
    """Content-free deterministic rejection of a P09 draft or cache."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise GuideGenerationCompilationError(code, message)


def _source_file_hash(path: str | Path) -> str:
    return f"sha256:{sha256(Path(path).read_bytes()).hexdigest()}"


def _schema_hash(model: type[m.StrictModel]) -> str:
    return canonical_hash(model.model_json_schema(mode="validation"))


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _dedupe_text(values: list[str], *, limit: int = 20) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) == limit:
            break
    return result


def p09_alias_envelope_schema_boundary() -> dict[str, str]:
    material = {
        "format": "p09-alias-envelope-schema-boundary/1.0.0",
        "version": P09_ALIAS_ENVELOPE_VERSION,
        "schema_name": "GuideAliasEnvelope",
        "schema_hash": _schema_hash(m.GuideAliasEnvelope),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def guide_enrichment_policy_boundary() -> dict[str, object]:
    material: dict[str, object] = {
        "format": "p09-guide-enrichment-policy-boundary/1.0.0",
        "version": P09_GUIDE_POLICY_VERSION,
        "context_mode": "CLOSED",
        "enrichment_only": True,
        "preserve_p07_core_observables": True,
        "minimum_observables": 2,
        "maximum_observables": 5,
        "required_levels": [0, 1, 2, 3],
        "partial_guides_allowed": False,
        "external_sources_allowed": False,
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def guide_generation_materializer_boundary() -> dict[str, object]:
    """Bind every executable dependency affecting canonical P09 output."""

    material: dict[str, object] = {
        "format": P09_MATERIALIZER_BOUNDARY_FORMAT,
        "version": P09_MATERIALIZER_VERSION,
        "materializer_source_hash": _source_file_hash(__file__),
        "canonical_contracts_source_hash": _source_file_hash(m.__file__),
        "canonical_identity_source_hash": _source_file_hash(
            stable_id.__code__.co_filename
        ),
        "alias_envelope_schema": p09_alias_envelope_schema_boundary(),
        "guide_policy": guide_enrichment_policy_boundary(),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def build_guide_approval_binding(
    *,
    assessment: m.Assessment,
    assessment_version: int,
    assessment_etag: str,
    approval_event_id: str,
) -> m.GuideApprovalBinding:
    """Create the immutable server-owned binding after approval persisted."""

    if (
        assessment.status != m.WorkflowStatus.APPROVED
        or assessment.approved_by is None
        or assessment.approved_at is None
    ):
        _fail("P09_APPROVAL_REQUIRED", "guide binding requires human approval")
    assessment_snapshot_hash = canonical_hash(assessment.model_dump(mode="json"))
    question_set_hash = canonical_hash(
        [item.model_dump(mode="json") for item in assessment.questions]
    )
    policy_hash = str(guide_enrichment_policy_boundary()["boundary_hash"])
    materializer_hash = str(
        guide_generation_materializer_boundary()["boundary_hash"]
    )
    approval_snapshot_hash = canonical_hash(
        {
            "assessment_version": assessment_version,
            "assessment_etag": assessment_etag,
            "assessment_snapshot_hash": assessment_snapshot_hash,
            "question_set_hash": question_set_hash,
            "approval_event_id": approval_event_id,
            "approved_by": assessment.approved_by,
            "approved_at": assessment.approved_at,
            "guide_policy_hash": policy_hash,
            "materializer_boundary_hash": materializer_hash,
        }
    )
    return m.GuideApprovalBinding(
        tenant_id=assessment.tenant_id,
        assessment_id=assessment.assessment_id,
        submission_id=assessment.submission_id,
        assessment_version=assessment_version,
        assessment_etag=assessment_etag,
        assessment_snapshot_hash=assessment_snapshot_hash,
        question_set_hash=question_set_hash,
        approval_event_id=approval_event_id,
        approval_snapshot_hash=approval_snapshot_hash,
        approved_by=assessment.approved_by,
        approved_at=assessment.approved_at,
        guide_policy_hash=policy_hash,
        materializer_boundary_hash=materializer_hash,
    )


def guide_id_for_binding(binding: m.GuideApprovalBinding) -> str:
    return stable_id(
        "guide",
        binding.tenant_id,
        binding.assessment_id,
        binding.assessment_version,
        binding.assessment_etag,
        binding.approval_snapshot_hash,
        binding.materializer_boundary_hash,
    )


def _assert_binding(request: m.GuideBuildRequest) -> None:
    binding = request.binding
    assessment = request.assessment
    expected = build_guide_approval_binding(
        assessment=assessment,
        assessment_version=binding.assessment_version,
        assessment_etag=binding.assessment_etag,
        approval_event_id=binding.approval_event_id,
    )
    if binding != expected:
        _fail(
            "P09_APPROVAL_BINDING_MISMATCH",
            "guide request does not match its exact approval snapshot",
        )
    if request.guide_id != guide_id_for_binding(binding):
        _fail("P09_GUIDE_ID_MISMATCH", "guide identity is not binding-derived")


def _question_indexes(
    request: m.GuideBuildRequest,
) -> tuple[
    dict[str, m.SelectedQuestion],
    dict[str, str],
    dict[str, dict[str, m.EvidenceUnit]],
    dict[str, dict[str, str]],
    dict[str, dict[str, m.ObservableElement]],
    dict[str, dict[str, str]],
]:
    bundle_by_id = {
        item.evidence_id: item for item in request.evidence_bundle.evidence_units
    }
    question_by_alias: dict[str, m.SelectedQuestion] = {}
    alias_by_question_id: dict[str, str] = {}
    evidence_by_question_alias: dict[str, dict[str, m.EvidenceUnit]] = {}
    evidence_alias_by_id: dict[str, dict[str, str]] = {}
    observable_by_question_alias: dict[str, dict[str, m.ObservableElement]] = {}
    observable_alias_by_id: dict[str, dict[str, str]] = {}
    for question_index, question in enumerate(request.assessment.questions, start=1):
        question_alias = f"Q{question_index}"
        question_by_alias[question_alias] = question
        alias_by_question_id[question.question_id] = question_alias
        local_evidence: dict[str, m.EvidenceUnit] = {}
        local_alias_by_id: dict[str, str] = {}
        for evidence_index, evidence_id in enumerate(question.evidence_ids, start=1):
            evidence = bundle_by_id.get(evidence_id)
            if evidence is None:
                _fail(
                    "P09_SUPPORT_EVIDENCE_UNKNOWN",
                    "question support evidence is absent from the request bundle",
                )
            evidence_alias = f"E{evidence_index}"
            local_evidence[evidence_alias] = evidence
            local_alias_by_id[evidence_id] = evidence_alias
        evidence_by_question_alias[question_alias] = local_evidence
        evidence_alias_by_id[question_alias] = local_alias_by_id
        local_observables: dict[str, m.ObservableElement] = {}
        local_observable_alias_by_id: dict[str, str] = {}
        for observable_index, observable in enumerate(
            question.preliminary_guide.observable_elements, start=1
        ):
            if not set(observable.evidence_ids).issubset(question.evidence_ids):
                _fail(
                    "P09_CORE_EVIDENCE_SCOPE_WIDENED",
                    "P07 core observable exceeds question support evidence",
                )
            observable_alias = f"O{observable_index}"
            local_observables[observable_alias] = observable
            local_observable_alias_by_id[observable.element_id] = observable_alias
        if not local_observables:
            _fail(
                "P09_CORE_OBSERVABLES_EMPTY",
                "P09 requires P07-owned core observables",
            )
        observable_by_question_alias[question_alias] = local_observables
        observable_alias_by_id[question_alias] = local_observable_alias_by_id
    return (
        question_by_alias,
        alias_by_question_id,
        evidence_by_question_alias,
        evidence_alias_by_id,
        observable_by_question_alias,
        observable_alias_by_id,
    )


def build_guide_alias_envelope(
    request: m.GuideBuildRequest,
) -> m.GuideAliasEnvelope:
    """Project only each approved question and its authorized support."""

    _assert_binding(request)
    if request.evidence_bundle.context_mode != m.ContextMode.CLOSED:
        _fail("P09_CONTEXT_MODE_INVALID", "P09 requires CLOSED context")
    (
        question_by_alias,
        _alias_by_question_id,
        evidence_by_question_alias,
        evidence_alias_by_id,
        observable_by_question_alias,
        _observable_alias_by_id,
    ) = _question_indexes(request)
    rows: list[m.GuideQuestionContext] = []
    for question_alias, question in question_by_alias.items():
        local_evidence = evidence_by_question_alias[question_alias]
        artifact_alias_by_id: dict[str, str] = {}
        for evidence in local_evidence.values():
            artifact_alias_by_id.setdefault(
                evidence.artifact_id, f"A{len(artifact_alias_by_id) + 1}"
            )
        visible_anchor_texts = [
            fragment.display_text
            or json.dumps(
                local_evidence[
                    evidence_alias_by_id[question_alias][fragment.evidence_id]
                ].structured_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )[:20_000]
            for fragment in question.anchor.fragments
        ]
        rows.append(
            m.GuideQuestionContext(
                question_alias=question_alias,
                cognitive_operation=question.cognitive_operation,
                response_format=question.response_format,
                difficulty=question.difficulty,
                question_text=question.question_text,
                visible_anchor_texts=visible_anchor_texts,
                support_evidence=[
                    m.GuideEvidenceContext(
                        evidence_alias=alias,
                        artifact_alias=artifact_alias_by_id[evidence.artifact_id],
                        modality=evidence.modality,
                        content_text=evidence.content_text,
                        structured_content=evidence.structured_content,
                        language=evidence.language,
                    )
                    for alias, evidence in local_evidence.items()
                ],
                purpose=question.preliminary_guide.purpose,
                core_observables=[
                    m.GuideCoreObservableContext(
                        observable_alias=alias,
                        description=observable.description,
                        support_evidence_aliases=[
                            evidence_alias_by_id[question_alias][evidence_id]
                            for evidence_id in observable.evidence_ids
                        ],
                        required_for_level_2=observable.required_for_level_2,
                    )
                    for alias, observable in observable_by_question_alias[
                        question_alias
                    ].items()
                ],
                acceptable_alternatives=list(
                    question.preliminary_guide.acceptable_alternatives
                ),
                misconceptions=list(question.preliminary_guide.misconceptions),
                choices=[
                    m.GuideChoiceContext(
                        text=choice.text,
                        is_best_answer=choice.is_best_answer,
                        evaluator_rationale=choice.evaluator_rationale,
                        misconception=choice.misconception,
                    )
                    for choice in question.choices
                ],
                semantic_uncertainties=list(question.semantic_uncertainties),
                student_justification_required=(
                    question.student_justification_required
                ),
            )
        )
    source_scope_hash = canonical_hash(request.model_dump(mode="json"))
    return m.GuideAliasEnvelope(
        alias_schema_version=P09_ALIAS_ENVELOPE_VERSION,
        scope_alias="S" + source_scope_hash.removeprefix("sha256:")[:24],
        source_scope_hash=source_scope_hash,
        context_mode=m.ContextMode.CLOSED,
        questions=rows,
    )


def p09_alias_envelope_boundary(
    request: m.GuideBuildRequest,
) -> dict[str, object]:
    envelope = build_guide_alias_envelope(request)
    material: dict[str, object] = {
        **p09_alias_envelope_schema_boundary(),
        "envelope_hash": canonical_hash(envelope.model_dump(mode="json")),
        "source_scope_hash": envelope.source_scope_hash,
        "assessment_snapshot_hash": request.binding.assessment_snapshot_hash,
        "question_set_hash": request.binding.question_set_hash,
        "approval_snapshot_hash": request.binding.approval_snapshot_hash,
        "evidence_bundle_hash": canonical_hash(
            request.evidence_bundle.model_dump(mode="json")
        ),
        "materializer_boundary_hash": request.binding.materializer_boundary_hash,
        "guide_policy_hash": request.binding.guide_policy_hash,
    }
    return {**material, "request_boundary_hash": canonical_hash(material)}


def _scope_alias(request: m.GuideBuildRequest) -> str:
    return build_guide_alias_envelope(request).scope_alias


def _generated_strings(draft: m.GuideModelDraft) -> list[str]:
    result: list[str] = []
    if draft.abstention_reason:
        result.append(draft.abstention_reason)
    for item in draft.items:
        result.extend(item.acceptance_conditions)
        result.extend(item.acceptable_alternative_additions)
        result.extend(item.misconception_additions)
        result.extend(item.cannot_infer)
        result.extend(item.semantic_uncertainties)
        result.extend(value.description for value in item.additional_observables)
        for level in item.levels:
            result.extend((level.label, level.descriptor))
    return result


def materialize_guide_draft(
    *,
    draft: m.GuideModelDraft,
    request: m.GuideBuildRequest,
) -> m.EvaluationGuide:
    """Enrich P07 guide cores while preserving all question semantics."""

    _assert_binding(request)
    if draft.scope_alias != _scope_alias(request):
        _fail(
            "P09_SCOPE_ALIAS_MISMATCH",
            "provider output belongs to another P09 alias envelope",
        )
    for value in _generated_strings(draft):
        if _P09_GLOBAL_POLICY_NOTICE.search(value):
            _fail(
                "P09_GLOBAL_NOTICE_FORBIDDEN",
                "question-specific guide output cannot contain global policy notices",
            )
        code = generated_text_safety_code(value)
        if code is not None:
            _fail(code, "provider guide draft failed generated-text safety")
    (
        question_by_alias,
        _alias_by_question_id,
        evidence_by_question_alias,
        _evidence_alias_by_id,
        observable_by_question_alias,
        _observable_alias_by_id,
    ) = _question_indexes(request)
    if draft.status == "NEEDS_REVIEW":
        assert draft.abstention_reason is not None
        return m.EvaluationGuide(
            guide_id=request.guide_id,
            assessment_id=request.assessment.assessment_id,
            submission_id=request.assessment.submission_id,
            binding=request.binding,
            status="NEEDS_REVIEW",
            items=[],
            diagnostics=[
                m.Diagnostic(
                    code="GUIDE_NEEDS_REVIEW",
                    severity=m.Severity.ERROR,
                    message=draft.abstention_reason,
                    evidence_ids=[],
                    source_ids=[],
                    retryable=False,
                    details={"policy_version": P09_GUIDE_POLICY_VERSION},
                )
            ],
            created_at=request.binding.approved_at,
        )
    draft_by_alias = {item.question_alias: item for item in draft.items}
    if set(draft_by_alias) != set(question_by_alias):
        _fail(
            "P09_QUESTION_COVERAGE_MISMATCH",
            "READY P09 output must cover every approved question exactly once",
        )
    items: list[m.EvaluationGuideItem] = []
    for question_alias, question in question_by_alias.items():
        item = draft_by_alias[question_alias]
        local_evidence = evidence_by_question_alias[question_alias]
        core = observable_by_question_alias[question_alias]
        all_by_alias: dict[str, m.ObservableElement] = {
            alias: observable.model_copy(deep=True)
            for alias, observable in core.items()
        }
        normalized = {
            _normalize_text(value.description) for value in all_by_alias.values()
        }
        for additional in item.additional_observables:
            if additional.observable_alias in all_by_alias:
                _fail(
                    "P09_OBSERVABLE_ALIAS_COLLISION",
                    "additional observable collides with a P07 core alias",
                )
            description_key = _normalize_text(additional.description)
            if description_key in normalized:
                _fail(
                    "P09_OBSERVABLE_DUPLICATE",
                    "P09 cannot duplicate a P07 core observable",
                )
            normalized.add(description_key)
            evidence_ids: list[str] = []
            for evidence_alias in additional.support_evidence_aliases:
                evidence = local_evidence.get(evidence_alias)
                if evidence is None:
                    _fail(
                        "P09_ALIAS_REFERENCE_UNKNOWN",
                        "additional observable references evidence outside its question",
                    )
                evidence_ids.append(evidence.evidence_id)
            all_by_alias[additional.observable_alias] = m.ObservableElement(
                element_id=stable_id(
                    "observable",
                    request.guide_id,
                    question.question_id,
                    additional.observable_alias,
                    additional.description,
                    evidence_ids,
                    P09_MATERIALIZER_VERSION,
                ),
                description=additional.description,
                evidence_ids=evidence_ids,
                source_ids=[],
                required_for_level_2=additional.required_for_level_2,
            )
        if not 2 <= len(all_by_alias) <= 5:
            _fail(
                "P09_OBSERVABLE_COUNT_INVALID",
                "guide enrichment must leave two to five observables",
            )
        levels: list[m.GuideLevel] = []
        for level in item.levels:
            unknown = set(level.observable_aliases) - set(all_by_alias)
            if unknown:
                _fail(
                    "P09_ALIAS_REFERENCE_UNKNOWN",
                    "guide scale references an unknown observable alias",
                )
            levels.append(
                m.GuideLevel(
                    level=level.level,
                    label=level.label,
                    descriptor=level.descriptor,
                    observable_element_ids=[
                        all_by_alias[alias].element_id
                        for alias in level.observable_aliases
                    ],
                )
            )
        required_ids = {
            value.element_id
            for value in all_by_alias.values()
            if value.required_for_level_2
        }
        if not required_ids.issubset(set(levels[2].observable_element_ids)):
            _fail(
                "P09_LEVEL_TWO_REQUIRED_OBSERVABLES_MISSING",
                "level 2 must include every required observable",
            )
        base = question.preliminary_guide
        items.append(
            m.EvaluationGuideItem(
                question_id=question.question_id,
                guide=m.GuideDraft(
                    purpose=base.purpose,
                    observable_elements=list(all_by_alias.values()),
                    acceptance_conditions=_dedupe_text(
                        list(item.acceptance_conditions)
                    ),
                    acceptable_alternatives=_dedupe_text(
                        [
                            *base.acceptable_alternatives,
                            *item.acceptable_alternative_additions,
                        ]
                    ),
                    misconceptions=_dedupe_text(
                        [*base.misconceptions, *item.misconception_additions]
                    ),
                    levels=levels,
                    cannot_infer=_dedupe_text(list(item.cannot_infer)),
                    semantic_uncertainties=_dedupe_text(
                        list(item.semantic_uncertainties)
                    ),
                ),
            )
        )
    return m.EvaluationGuide(
        guide_id=request.guide_id,
        assessment_id=request.assessment.assessment_id,
        submission_id=request.assessment.submission_id,
        binding=request.binding,
        status="READY",
        items=items,
        diagnostics=[],
        created_at=request.binding.approved_at,
    )


def guide_model_draft_from_materialized_guide(
    *,
    guide: m.EvaluationGuide,
    request: m.GuideBuildRequest,
) -> m.GuideModelDraft:
    _assert_binding(request)
    if guide.status == "NEEDS_REVIEW":
        if (
            guide.items
            or len(guide.diagnostics) != 1
            or guide.diagnostics[0].code != "GUIDE_NEEDS_REVIEW"
        ):
            _fail(
                "P09_CANONICAL_REPLAY_MISMATCH",
                "non-ready guide is not a current materializer output",
            )
        return m.GuideModelDraft(
            scope_alias=_scope_alias(request),
            status="NEEDS_REVIEW",
            items=[],
            abstention_reason=guide.diagnostics[0].message,
        )
    if guide.status != "READY":
        _fail(
            "P09_CANONICAL_REPLAY_MISMATCH",
            "technical failures are not materialized guide outputs",
        )
    (
        question_by_alias,
        alias_by_question_id,
        _evidence_by_question_alias,
        evidence_alias_by_id,
        observable_by_question_alias,
        observable_alias_by_id,
    ) = _question_indexes(request)
    guide_by_question_id = {item.question_id: item for item in guide.items}
    if set(guide_by_question_id) != set(alias_by_question_id):
        _fail("P09_CANONICAL_REPLAY_MISMATCH", "guide question coverage differs")
    draft_items: list[m.GuideQuestionModelDraft] = []
    for question_alias, question in question_by_alias.items():
        materialized = guide_by_question_id[question.question_id].guide
        core = list(observable_by_question_alias[question_alias].values())
        if materialized.purpose != question.preliminary_guide.purpose:
            _fail("P09_CORE_MUTATED", "P09 changed the P07 guide purpose")
        if materialized.observable_elements[: len(core)] != core:
            _fail("P09_CORE_MUTATED", "P09 changed a P07 core observable")
        additional_values = materialized.observable_elements[len(core) :]
        additional_alias_by_id: dict[str, str] = {}
        additions: list[m.GuideAdditionalObservableDraft] = []
        for index, observable in enumerate(additional_values, start=1):
            alias = f"N{index}"
            additional_alias_by_id[observable.element_id] = alias
            try:
                aliases = [
                    evidence_alias_by_id[question_alias][evidence_id]
                    for evidence_id in observable.evidence_ids
                ]
            except KeyError:
                _fail(
                    "P09_EVIDENCE_SCOPE_WIDENED",
                    "materialized guide references evidence outside its question",
                )
            if observable.source_ids:
                _fail(
                    "P09_EXTERNAL_SOURCE_FORBIDDEN",
                    "CLOSED guide cannot contain course sources",
                )
            additions.append(
                m.GuideAdditionalObservableDraft(
                    observable_alias=alias,
                    description=observable.description,
                    support_evidence_aliases=aliases,
                    required_for_level_2=observable.required_for_level_2,
                )
            )
        alias_by_element_id = {
            **observable_alias_by_id[question_alias],
            **additional_alias_by_id,
        }
        try:
            levels = [
                m.GuideLevelDraft(
                    level=level.level,
                    label=level.label,
                    descriptor=level.descriptor,
                    observable_aliases=[
                        alias_by_element_id[element_id]
                        for element_id in level.observable_element_ids
                    ],
                )
                for level in materialized.levels
            ]
        except KeyError:
            _fail(
                "P09_CANONICAL_REPLAY_MISMATCH",
                "materialized scale references an unknown observable",
            )
        base_alternatives = _dedupe_text(
            list(question.preliminary_guide.acceptable_alternatives)
        )
        base_misconceptions = _dedupe_text(
            list(question.preliminary_guide.misconceptions)
        )
        if materialized.acceptable_alternatives[: len(base_alternatives)] != base_alternatives:
            _fail("P09_CORE_MUTATED", "P09 changed P07 acceptable alternatives")
        if materialized.misconceptions[: len(base_misconceptions)] != base_misconceptions:
            _fail("P09_CORE_MUTATED", "P09 changed P07 misconceptions")
        draft_items.append(
            m.GuideQuestionModelDraft(
                question_alias=question_alias,
                additional_observables=additions,
                acceptance_conditions=list(materialized.acceptance_conditions),
                acceptable_alternative_additions=list(
                    materialized.acceptable_alternatives[len(base_alternatives) :]
                ),
                misconception_additions=list(
                    materialized.misconceptions[len(base_misconceptions) :]
                ),
                levels=levels,
                cannot_infer=list(materialized.cannot_infer),
                semantic_uncertainties=list(materialized.semantic_uncertainties),
            )
        )
    return m.GuideModelDraft(
        scope_alias=_scope_alias(request),
        status="READY",
        items=draft_items,
    )


def validate_materialized_guide(
    *,
    guide: m.EvaluationGuide,
    request: m.GuideBuildRequest,
) -> None:
    """Require exact replay through the current P09 deterministic boundary."""

    if any(
        (
            guide.guide_id != request.guide_id,
            guide.assessment_id != request.assessment.assessment_id,
            guide.submission_id != request.assessment.submission_id,
            guide.binding != request.binding,
            guide.created_at != request.binding.approved_at,
        )
    ):
        _fail(
            "P09_APPROVAL_BINDING_MISMATCH",
            "guide identity does not match the exact approved request",
        )
    draft = guide_model_draft_from_materialized_guide(
        guide=guide, request=request
    )
    replayed = materialize_guide_draft(draft=draft, request=request)
    if replayed != guide:
        _fail(
            "P09_CANONICAL_REPLAY_MISMATCH",
            "guide cannot be replayed through the current materializer",
        )
