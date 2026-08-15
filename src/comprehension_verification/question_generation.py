"""Deterministic P07 alias envelope and canonical question materialization."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

from .canonical import canonical_hash, stable_id
from .contracts import models as m


P07_ALIAS_ENVELOPE_VERSION = "p07-alias-envelope/1.0.0"
P07_MATERIALIZER_VERSION = "p07-question-materializer/1.0.0"
P07_MATERIALIZER_BOUNDARY_FORMAT = "p07-materializer-boundary/1.0.0"
P07_LEAKAGE_POLICY_VERSION = "p07-answer-leakage/1.0.0"

_LITERAL_MIN_TOKENS = 4
_LITERAL_MIN_CHARACTERS = 24
_OVERLAP_NGRAM_SIZE = 4
_BLOCKING_NGRAM_COVERAGE = 0.90
_WARNING_NGRAM_COVERAGE = 0.65
_GENERATED_SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)
_GENERATED_PROHIBITED_CLAIMS = re.compile(
    r"\b(detector de ia|hecho por ia|autor(?:ía)?|fraude|culpable|"
    r"otro estudiante|system prompt|ignore (?:all |previous )?instructions)\b",
    flags=re.IGNORECASE,
)


class QuestionGenerationCompilationError(ValueError):
    """Content-free deterministic rejection of a P07 provider draft/cache."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise QuestionGenerationCompilationError(code, message)


def _source_file_hash(path: str | Path) -> str:
    return f"sha256:{sha256(Path(path).read_bytes()).hexdigest()}"


def _schema_hash(model: type[m.StrictModel]) -> str:
    return canonical_hash(model.model_json_schema(mode="validation"))


def p07_alias_envelope_schema_boundary() -> dict[str, str]:
    material = {
        "format": "p07-alias-envelope-schema-boundary/1.0.0",
        "version": P07_ALIAS_ENVELOPE_VERSION,
        "schema_name": "QuestionAliasEnvelope",
        "schema_hash": _schema_hash(m.QuestionAliasEnvelope),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def answer_leakage_policy_boundary() -> dict[str, object]:
    material: dict[str, object] = {
        "format": "p07-answer-leakage-boundary/1.0.0",
        "version": P07_LEAKAGE_POLICY_VERSION,
        "literal_min_tokens": _LITERAL_MIN_TOKENS,
        "literal_min_characters": _LITERAL_MIN_CHARACTERS,
        "ngram_size": _OVERLAP_NGRAM_SIZE,
        "blocking_ngram_coverage": _BLOCKING_NGRAM_COVERAGE,
        "warning_ngram_coverage": _WARNING_NGRAM_COVERAGE,
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def question_generation_materializer_boundary() -> dict[str, object]:
    """Bind every executable dependency that can affect canonical P07 output."""

    material: dict[str, object] = {
        "format": P07_MATERIALIZER_BOUNDARY_FORMAT,
        "version": P07_MATERIALIZER_VERSION,
        "materializer_source_hash": _source_file_hash(__file__),
        "canonical_contracts_source_hash": _source_file_hash(m.__file__),
        "canonical_identity_source_hash": _source_file_hash(
            stable_id.__code__.co_filename
        ),
        "alias_envelope_schema": p07_alias_envelope_schema_boundary(),
        "answer_leakage_policy": answer_leakage_policy_boundary(),
    }
    return {**material, "boundary_hash": canonical_hash(material)}


def _scope_hash(request: m.QuestionBuildRequest) -> str:
    return canonical_hash(request.model_dump(mode="json"))


def _scope_alias(request: m.QuestionBuildRequest) -> str:
    return "S" + _scope_hash(request).removeprefix("sha256:")[:24]


def _support_indexes(
    request: m.QuestionBuildRequest,
) -> tuple[dict[str, m.EvidenceUnit], dict[str, str]]:
    bundle_by_id = {
        unit.evidence_id: unit for unit in request.evidence_bundle.evidence_units
    }
    support_by_alias: dict[str, m.EvidenceUnit] = {}
    alias_by_id: dict[str, str] = {}
    for index, evidence_id in enumerate(
        request.opportunity.evidence_ids, start=1
    ):
        unit = bundle_by_id.get(evidence_id)
        if unit is None:
            _fail(
                "P07_SUPPORT_EVIDENCE_UNKNOWN",
                "opportunity support evidence is absent from the request bundle",
            )
        alias = f"E{index}"
        support_by_alias[alias] = unit
        alias_by_id[evidence_id] = alias
    return support_by_alias, alias_by_id


def build_question_alias_envelope(
    request: m.QuestionBuildRequest,
) -> m.QuestionAliasEnvelope:
    """Project one canonical P07 request into a closed support namespace."""

    support_by_alias, _alias_by_id = _support_indexes(request)
    artifact_alias_by_id: dict[str, str] = {}
    for evidence in support_by_alias.values():
        artifact_alias_by_id.setdefault(
            evidence.artifact_id, f"A{len(artifact_alias_by_id) + 1}"
        )
    opportunity = request.opportunity
    return m.QuestionAliasEnvelope(
        alias_schema_version=P07_ALIAS_ENVELOPE_VERSION,
        scope_alias=_scope_alias(request),
        source_scope_hash=_scope_hash(request),
        opportunity=m.QuestionOpportunityContext(
            cognitive_operation=opportunity.cognitive_operation,
            focus=opportunity.focus,
            observable=opportunity.observable,
            response_format=opportunity.allowed_response_formats[0],
            difficulty=opportunity.difficulty,
            target_minutes=opportunity.target_minutes,
            allowed_anchor_structures=list(
                opportunity.allowed_anchor_structures
            ),
            student_justification_required=(
                opportunity.student_justification_required
            ),
        ),
        support_evidence=[
            m.QuestionEvidenceContext(
                evidence_alias=alias,
                artifact_alias=artifact_alias_by_id[evidence.artifact_id],
                modality=evidence.modality,
                content_text=evidence.content_text,
                structured_content=evidence.structured_content,
                language=evidence.language,
                extraction_confidence=evidence.extraction_confidence,
            )
            for alias, evidence in support_by_alias.items()
        ],
        generation_constraints=m.QuestionGenerationConstraints(
            max_visible_anchor_fragments=(
                request.generation_policy.max_anchor_fragments
            ),
            require_accessible_alternative=(
                request.generation_policy.require_accessible_alternative
            ),
            avoid_fingerprints=[
                m.QuestionAvoidFingerprintContext(
                    fingerprint_alias=f"F{index}",
                    normalized_question_hash=item.normalized_question_hash,
                )
                for index, item in enumerate(request.avoid, start=1)
            ],
        ),
    )


def p07_alias_envelope_boundary(
    request: m.QuestionBuildRequest,
) -> dict[str, object]:
    envelope = build_question_alias_envelope(request)
    support_by_alias, _alias_by_id = _support_indexes(request)
    bundle = request.evidence_bundle
    material: dict[str, object] = {
        **p07_alias_envelope_schema_boundary(),
        "envelope_hash": canonical_hash(envelope.model_dump(mode="json")),
        "source_scope_hash": envelope.source_scope_hash,
        "opportunity_hash": canonical_hash(
            request.opportunity.model_dump(mode="json")
        ),
        "support_evidence_hash": canonical_hash(
            [item.model_dump(mode="json") for item in support_by_alias.values()]
        ),
        "evidence_bundle_hash": canonical_hash(bundle.model_dump(mode="json")),
        "generation_policy_hash": canonical_hash(
            request.generation_policy.model_dump(mode="json")
        ),
        "avoid_fingerprints_hash": canonical_hash(
            [item.model_dump(mode="json") for item in request.avoid]
        ),
        "submission_scope_hash": canonical_hash(
            {
                "tenant_id": bundle.tenant_id,
                "activity_id": bundle.activity_id,
                "submission_id": bundle.submission_id,
            }
        ),
    }
    return {**material, "request_boundary_hash": canonical_hash(material)}


def anchor_transformation(evidence: m.EvidenceUnit) -> str:
    if evidence.structured_content is not None and evidence.modality in {
        m.EvidenceModality.TABLE,
        m.EvidenceModality.CELL_RANGE,
        m.EvidenceModality.FORMULA,
    }:
        return "TABLE_SLICE"
    if evidence.modality in {
        m.EvidenceModality.CODE_SYMBOL,
        m.EvidenceModality.CODE_SPAN,
        m.EvidenceModality.NOTEBOOK_CELL,
    }:
        return "CODE_CONTEXT"
    if evidence.modality in {
        m.EvidenceModality.IMAGE_REGION,
        m.EvidenceModality.CHART,
    }:
        return "ALT_TEXT"
    if evidence.content_text and len(evidence.content_text) > 20_000:
        return "CROP"
    if evidence.content_text:
        return "LITERAL"
    return "TABLE_SLICE"


def anchor_display_text(evidence: m.EvidenceUnit) -> str:
    if evidence.content_text:
        return evidence.content_text[:20_000]
    return json.dumps(
        evidence.structured_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )[:20_000]


def anchor_fragment_for_evidence(evidence: m.EvidenceUnit) -> m.AnchorFragment:
    return m.AnchorFragment(
        evidence_id=evidence.evidence_id,
        display_text=anchor_display_text(evidence),
        transformation=anchor_transformation(evidence),
        locator=evidence.locator.model_copy(deep=True),
    )


def _structure_is_compatible(
    structure: m.AnchorStructure, evidence: list[m.EvidenceUnit]
) -> bool:
    count = len(evidence)
    modalities = {item.modality for item in evidence}
    if structure == m.AnchorStructure.SINGLE_FRAGMENT:
        return count == 1
    if structure == m.AnchorStructure.PAIRED_FRAGMENTS:
        return count == 2
    if structure == m.AnchorStructure.TABLE_OR_RANGE:
        return count >= 1 and bool(
            modalities
            & {
                m.EvidenceModality.TABLE,
                m.EvidenceModality.CELL_RANGE,
                m.EvidenceModality.FORMULA,
            }
        )
    if structure == m.AnchorStructure.CODE_CONTEXT:
        return count >= 1 and bool(
            modalities
            & {
                m.EvidenceModality.CODE_SYMBOL,
                m.EvidenceModality.CODE_SPAN,
                m.EvidenceModality.NOTEBOOK_CELL,
            }
        )
    if structure == m.AnchorStructure.FIGURE_WITH_CONTEXT:
        return count >= 1 and bool(
            modalities
            & {m.EvidenceModality.IMAGE_REGION, m.EvidenceModality.CHART}
        )
    if structure == m.AnchorStructure.SEQUENCE:
        return count >= 2
    if structure == m.AnchorStructure.CROSS_ARTIFACT:
        return count >= 2 and len({item.artifact_id for item in evidence}) >= 2
    return False


def derive_anchor_structure(
    evidence: list[m.EvidenceUnit],
    allowed: list[m.AnchorStructure],
) -> m.AnchorStructure:
    if not evidence:
        _fail("P07_VISIBLE_ANCHOR_EMPTY", "visible anchor cannot be empty")
    preferred: list[m.AnchorStructure] = []
    if len({item.artifact_id for item in evidence}) >= 2:
        preferred.append(m.AnchorStructure.CROSS_ARTIFACT)
    if len(evidence) == 1:
        modality = evidence[0].modality
        if modality in {
            m.EvidenceModality.TABLE,
            m.EvidenceModality.CELL_RANGE,
            m.EvidenceModality.FORMULA,
        }:
            preferred.append(m.AnchorStructure.TABLE_OR_RANGE)
        elif modality in {
            m.EvidenceModality.CODE_SYMBOL,
            m.EvidenceModality.CODE_SPAN,
            m.EvidenceModality.NOTEBOOK_CELL,
        }:
            preferred.append(m.AnchorStructure.CODE_CONTEXT)
        elif modality in {
            m.EvidenceModality.IMAGE_REGION,
            m.EvidenceModality.CHART,
        }:
            preferred.append(m.AnchorStructure.FIGURE_WITH_CONTEXT)
        preferred.append(m.AnchorStructure.SINGLE_FRAGMENT)
    elif len(evidence) == 2:
        preferred.append(m.AnchorStructure.PAIRED_FRAGMENTS)
        preferred.append(m.AnchorStructure.SEQUENCE)
    else:
        preferred.append(m.AnchorStructure.SEQUENCE)
    for structure in [*preferred, *allowed]:
        if structure in allowed and _structure_is_compatible(structure, evidence):
            return structure
    _fail(
        "P07_ANCHOR_STRUCTURE_INCOMPATIBLE",
        "selected visible evidence cannot form an allowed anchor structure",
    )


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def generated_text_safety_code(text: str) -> str | None:
    """Classify generated PII/secrets or prohibited claims content-free."""

    claim_scan = re.sub(
        r"\bno (?:permite|se puede|debe) inferir (?:la )?autor(?:ía)?\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if _GENERATED_PROHIBITED_CLAIMS.search(claim_scan):
        return "QUESTION_SECURITY_FAIL"
    if any(pattern.search(text) for pattern in _GENERATED_SECRET_PATTERNS):
        return "QUESTION_PII"
    return None


def _draft_generated_strings(draft: m.QuestionModelDraft) -> list[str]:
    values = [
        draft.question_text,
        draft.replacement_reason,
        *draft.acceptable_alternatives,
        *draft.misconceptions,
        *draft.semantic_uncertainties,
        *(item.description for item in draft.expected_observables),
        *(item.text for item in draft.choices),
        *(item.evaluator_rationale for item in draft.choices),
        *(item.misconception for item in draft.choices),
    ]
    return [item for item in values if item is not None]


def _tokens(text: str) -> list[str]:
    return _normalize_text(text).split()


def _ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return set()
    return {
        tuple(tokens[index : index + size])
        for index in range(len(tokens) - size + 1)
    }


def _literal_contains(container: str, answer: str) -> bool:
    normalized_answer = _normalize_text(answer)
    return (
        len(normalized_answer) >= _LITERAL_MIN_CHARACTERS
        and len(normalized_answer.split()) >= _LITERAL_MIN_TOKENS
        and normalized_answer in _normalize_text(container)
    )


def _ngram_coverage(container: str, answer: str) -> float:
    answer_ngrams = _ngrams(_tokens(answer), _OVERLAP_NGRAM_SIZE)
    if not answer_ngrams:
        return 0.0
    container_ngrams = _ngrams(_tokens(container), _OVERLAP_NGRAM_SIZE)
    return len(answer_ngrams & container_ngrams) / len(answer_ngrams)


@dataclass(frozen=True, slots=True)
class AnswerLeakageAssessment:
    blocking_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.blocking_codes)

    @property
    def risk_score(self) -> float:
        if self.blocking_codes:
            return 1.0
        if self.warning_codes:
            return 0.5
        return 0.0


def assess_answer_leakage(
    *,
    visible_anchor_text: str,
    question_text: str,
    expected_observables: list[str],
    choices: list[m.QuestionChoiceDraft] | None = None,
) -> AnswerLeakageAssessment:
    """Detect only literal or near-literal operational leakage.

    This deliberately does not decide semantic equivalence, pedagogical
    sufficiency, or whether visible premises make a question too easy.
    """

    blocking: list[str] = []
    warnings: list[str] = []
    for observable in expected_observables:
        if _literal_contains(visible_anchor_text, observable):
            blocking.append("VISIBLE_ANCHOR_EXPECTED_OBSERVABLE_LITERAL")
        else:
            coverage = _ngram_coverage(visible_anchor_text, observable)
            if coverage >= _BLOCKING_NGRAM_COVERAGE:
                blocking.append("VISIBLE_ANCHOR_EXPECTED_OBSERVABLE_OVERLAP")
            elif coverage >= _WARNING_NGRAM_COVERAGE:
                warnings.append("VISIBLE_ANCHOR_EXPECTED_OBSERVABLE_RISK")
        if _literal_contains(question_text, observable):
            blocking.append("QUESTION_EXPECTED_OBSERVABLE_LITERAL")
        else:
            coverage = _ngram_coverage(question_text, observable)
            if coverage >= _BLOCKING_NGRAM_COVERAGE:
                blocking.append("QUESTION_EXPECTED_OBSERVABLE_OVERLAP")
            elif coverage >= _WARNING_NGRAM_COVERAGE:
                warnings.append("QUESTION_EXPECTED_OBSERVABLE_RISK")
    best_answers = [
        choice.text for choice in choices or [] if choice.is_best_answer
    ]
    if any(_literal_contains(visible_anchor_text, text) for text in best_answers):
        blocking.append("VISIBLE_ANCHOR_CORRECT_CHOICE_LITERAL")
    return AnswerLeakageAssessment(
        blocking_codes=tuple(dict.fromkeys(blocking)),
        warning_codes=tuple(dict.fromkeys(warnings)),
    )


def _replacement_result(
    request: m.QuestionBuildRequest, message: str
) -> m.QuestionGenerationResult:
    return m.QuestionGenerationResult(
        submission_id=request.plan.submission_id,
        opportunity_id=request.opportunity.opportunity_id,
        context_mode=request.evidence_bundle.context_mode,
        status="REPLACEMENT_REQUIRED",
        candidate=None,
        diagnostics=[
            m.Diagnostic(
                code="QUESTION_REPLACEMENT_REQUIRED",
                severity=m.Severity.ERROR,
                message=message,
                evidence_ids=list(request.opportunity.evidence_ids),
                source_ids=[],
                retryable=False,
                details={},
            )
        ],
    )


def _question_fingerprint_hashes(question_text: str) -> set[str]:
    return {
        canonical_hash(_normalize_text(question_text)),
        canonical_hash(question_text.strip().lower()),
    }


def materialize_question_draft(
    *,
    draft: m.QuestionModelDraft,
    request: m.QuestionBuildRequest,
) -> m.QuestionGenerationResult:
    """Resolve aliases and copy trusted fields into the canonical P07 result."""

    if request.evidence_bundle.context_mode != m.ContextMode.CLOSED:
        _fail("P07_CONTEXT_MODE_INVALID", "P07 requires CLOSED context")
    if draft.scope_alias != _scope_alias(request):
        _fail(
            "P07_SCOPE_ALIAS_MISMATCH",
            "provider output belongs to another P07 alias envelope",
        )
    for text in _draft_generated_strings(draft):
        code = generated_text_safety_code(text)
        if code is not None:
            _fail(code, "provider question draft failed generated-text safety")
    support_by_alias, _alias_by_id = _support_indexes(request)
    if draft.status == "REPLACEMENT_REQUIRED":
        assert draft.replacement_reason is not None
        return _replacement_result(request, draft.replacement_reason)

    visible: list[m.EvidenceUnit] = []
    for alias in draft.visible_anchor_aliases:
        evidence = support_by_alias.get(alias)
        if evidence is None:
            _fail(
                "P07_ALIAS_REFERENCE_UNKNOWN",
                "provider output references an unknown visible-anchor alias",
            )
        visible.append(evidence)
    if len(visible) > request.generation_policy.max_anchor_fragments:
        _fail(
            "P07_VISIBLE_ANCHOR_LIMIT_EXCEEDED",
            "visible anchor exceeds the trusted generation policy",
        )

    observable_rows: list[tuple[m.QuestionObservableDraft, list[m.EvidenceUnit]]] = []
    normalized_observables: set[str] = set()
    for observable in draft.expected_observables:
        normalized = _normalize_text(observable.description)
        if normalized in normalized_observables:
            _fail(
                "P07_OBSERVABLE_DUPLICATE",
                "provider output contains duplicate expected observables",
            )
        normalized_observables.add(normalized)
        evidence: list[m.EvidenceUnit] = []
        for alias in observable.support_evidence_aliases:
            unit = support_by_alias.get(alias)
            if unit is None:
                _fail(
                    "P07_ALIAS_REFERENCE_UNKNOWN",
                    "expected observable references an unknown support alias",
                )
            evidence.append(unit)
        observable_rows.append((observable, evidence))

    response_format = request.opportunity.allowed_response_formats[0]
    if response_format == m.ResponseFormat.CHOICE and not draft.choices:
        return _replacement_result(
            request,
            "La oportunidad de selección no produjo opciones evaluables completas.",
        )
    if response_format != m.ResponseFormat.CHOICE and draft.choices:
        return _replacement_result(
            request,
            "La redacción propuso opciones para un formato que no es de selección.",
        )

    assert draft.question_text is not None
    if _question_fingerprint_hashes(draft.question_text).intersection(
        {item.normalized_question_hash for item in request.avoid}
    ):
        return _replacement_result(
            request,
            "La redacción repite un fingerprint rechazado dentro del scope actual.",
        )

    visible_text = "\n".join(anchor_display_text(item) for item in visible)
    leakage = assess_answer_leakage(
        visible_anchor_text=visible_text,
        question_text=draft.question_text,
        expected_observables=[
            item.description for item in draft.expected_observables
        ],
        choices=draft.choices,
    )
    if leakage.blocked:
        return _replacement_result(
            request,
            "La redacción o el ancla visible contiene una respuesta esperada de forma literal o casi literal.",
        )

    candidate_id = request.target_candidate_id
    visible_ids = [item.evidence_id for item in visible]
    structure = derive_anchor_structure(
        visible, list(request.opportunity.allowed_anchor_structures)
    )
    candidate = m.QuestionCandidate(
        candidate_id=candidate_id,
        submission_id=request.plan.submission_id,
        opportunity_id=request.opportunity.opportunity_id,
        opportunity_template_id=(
            request.opportunity.opportunity_template_id
        ),
        dimension_id=request.opportunity.dimension_id,
        variant_id=request.opportunity.variant_id,
        cognitive_operation=request.opportunity.cognitive_operation,
        response_format=response_format,
        difficulty=request.opportunity.difficulty,
        estimated_minutes=request.opportunity.target_minutes,
        question_text=draft.question_text,
        anchor=m.Anchor(
            anchor_id=stable_id(
                "anchor", candidate_id, visible_ids, P07_MATERIALIZER_VERSION
            ),
            structure=structure,
            fragments=[anchor_fragment_for_evidence(item) for item in visible],
            student_facing_label=None,
            self_containment_score=1.0,
            answer_leakage_risk=leakage.risk_score,
        ),
        evidence_ids=list(request.opportunity.evidence_ids),
        course_source_ids=[],
        citations=[],
        choices=[
            m.ChoiceOption(
                option_id=stable_id(
                    "option", candidate_id, index, P07_MATERIALIZER_VERSION
                ),
                text=item.text,
                is_best_answer=item.is_best_answer,
                evaluator_rationale=item.evaluator_rationale,
                misconception=item.misconception,
            )
            for index, item in enumerate(draft.choices, start=1)
        ],
        student_justification_required=(
            request.opportunity.student_justification_required
        ),
        preliminary_guide=m.GuideDraft(
            purpose=request.opportunity.observable,
            observable_elements=[
                m.ObservableElement(
                    element_id=stable_id(
                        "observable",
                        candidate_id,
                        index,
                        item.description,
                        [unit.evidence_id for unit in evidence],
                        P07_MATERIALIZER_VERSION,
                    ),
                    description=item.description,
                    evidence_ids=[unit.evidence_id for unit in evidence],
                    source_ids=[],
                    required_for_level_2=item.required_for_level_2,
                )
                for index, (item, evidence) in enumerate(
                    observable_rows, start=1
                )
            ],
            acceptable_alternatives=list(draft.acceptable_alternatives),
            misconceptions=list(draft.misconceptions),
            levels=[],
            cannot_infer=[],
        ),
        uncertainties=list(draft.semantic_uncertainties),
    )
    diagnostics = [
        m.Diagnostic(
            code="QUESTION_ANSWER_LEAKAGE_RISK",
            severity=m.Severity.WARNING,
            message=(
                "La heurística operacional detectó overlap no concluyente; P08 y la revisión docente permanecen activas."
            ),
            evidence_ids=visible_ids,
            source_ids=[],
            retryable=False,
            details={"policy_version": P07_LEAKAGE_POLICY_VERSION},
        )
        for _code in leakage.warning_codes[:1]
    ]
    return m.QuestionGenerationResult(
        submission_id=request.plan.submission_id,
        opportunity_id=request.opportunity.opportunity_id,
        context_mode=request.evidence_bundle.context_mode,
        status="READY",
        candidate=candidate,
        diagnostics=diagnostics,
    )


def _draft_from_materialized_result(
    *,
    result: m.QuestionGenerationResult,
    request: m.QuestionBuildRequest,
) -> m.QuestionModelDraft:
    support_by_alias, alias_by_id = _support_indexes(request)
    del support_by_alias
    if result.status == "REPLACEMENT_REQUIRED":
        if len(result.diagnostics) != 1 or result.candidate is not None:
            _fail(
                "P07_CANONICAL_REPLAY_MISMATCH",
                "replacement result is not a current materializer output",
            )
        diagnostic = result.diagnostics[0]
        if (
            diagnostic.code != "QUESTION_REPLACEMENT_REQUIRED"
            or diagnostic.severity != m.Severity.ERROR
            or diagnostic.evidence_ids != request.opportunity.evidence_ids
            or diagnostic.source_ids
            or diagnostic.retryable
            or diagnostic.details
        ):
            _fail(
                "P07_CANONICAL_REPLAY_MISMATCH",
                "replacement diagnostic differs from the current materializer",
            )
        return m.QuestionModelDraft(
            scope_alias=_scope_alias(request),
            status="REPLACEMENT_REQUIRED",
            semantic_uncertainties=[],
            replacement_reason=diagnostic.message,
        )
    if result.status != "READY" or result.candidate is None:
        _fail(
            "P07_CANONICAL_REPLAY_MISMATCH",
            "canonical result is not a current READY or replacement output",
        )
    candidate = result.candidate
    try:
        visible_aliases = [
            alias_by_id[item.evidence_id] for item in candidate.anchor.fragments
        ]
        observables = [
            m.QuestionObservableDraft(
                description=item.description,
                support_evidence_aliases=[
                    alias_by_id[evidence_id]
                    for evidence_id in item.evidence_ids
                ],
                required_for_level_2=item.required_for_level_2,
            )
            for item in candidate.preliminary_guide.observable_elements
        ]
    except KeyError:
        _fail(
            "P07_CANONICAL_REPLAY_MISMATCH",
            "canonical result references evidence outside current support",
        )
    return m.QuestionModelDraft(
        scope_alias=_scope_alias(request),
        status="READY",
        question_text=candidate.question_text,
        visible_anchor_aliases=visible_aliases,
        expected_observables=observables,
        acceptable_alternatives=list(
            candidate.preliminary_guide.acceptable_alternatives
        ),
        misconceptions=list(candidate.preliminary_guide.misconceptions),
        choices=[
            m.QuestionChoiceDraft(
                text=item.text,
                is_best_answer=item.is_best_answer,
                evaluator_rationale=item.evaluator_rationale,
                misconception=item.misconception,
            )
            for item in candidate.choices
        ],
        semantic_uncertainties=list(candidate.uncertainties),
        replacement_reason=None,
    )


def validate_materialized_question_result(
    *,
    result: m.QuestionGenerationResult,
    request: m.QuestionBuildRequest,
) -> None:
    """Recompile a current canonical cache entry and require exact equality."""

    if (
        result.submission_id != request.plan.submission_id
        or result.opportunity_id != request.opportunity.opportunity_id
        or result.context_mode != request.evidence_bundle.context_mode
    ):
        _fail(
            "P07_SCOPE_MISMATCH",
            "canonical question result belongs to another request scope",
        )
    draft = _draft_from_materialized_result(result=result, request=request)
    replayed = materialize_question_draft(draft=draft, request=request)
    if replayed != result:
        _fail(
            "P07_CANONICAL_REPLAY_MISMATCH",
            "canonical question result is not the exact current materializer output",
        )
