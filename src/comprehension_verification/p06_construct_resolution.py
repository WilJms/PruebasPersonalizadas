"""Fail-closed P06 construct resolution (Phase 9B.6 remediation).

Phase 9B.5 falsified the ``semantic-benchmark/1.2.0`` resolver
(``semantic_benchmark_v12.resolve_target_construct``) before any v1.2 provider
execution.  Four defects made it fail *open*:

``1``
    Quoted spans as short as two characters were accepted as construct
    references, so the bare rubric token ``'No'`` was treated as a declaration.

``2``
    ``UNIQUE_NAME_PREFIX`` resolved any reference that was a word-boundary
    prefix of exactly one catalog name.  Combined with ``1`` this bound
    ``A04-S03-P1`` -- a property about the rubric distinction *No verificable*
    vs *No* -- to ``RUBRIC::A04::NO_MUTA_SOLICITUDES_NI_CUPOS_POR_GRUPO``,
    the single A04 criterion whose name begins ``No ...``.

``3``
    ``_LABEL_TOKEN = \\b([A-Z]\\d)\\b`` cannot represent a two-digit label.
    ``D10`` produced *no* reference at all, and ``D1 y D10`` produced only
    ``D1``, so a multi-digit label silently disappeared while its neighbour
    resolved.

``4``
    An unmatched reference was discarded in silence.  A property naming one
    criterion exactly and a second one in paraphrase (``A04-S05-P5``) became a
    one-construct candidate gate that verifies strictly less than it asserts.

The repair here is deliberately *smaller* than the instrument it replaces.
There are exactly two ways to match -- exact folded name and exact label -- and
``UNIQUE_NAME_PREFIX`` is gone.  What the resolver gains is not matching power
but the obligation to account for every reference it saw: an unmatched
reference that is shaped like a construct name blocks resolution instead of
vanishing.  Coverage therefore shrinks where the corpus is ambiguous, which is
the intended direction.  Route count is not a target.

Nothing in this module reads candidate output, adjudication results or
execution ledgers.  Its only inputs are the frozen oracle property text and the
authorized construct catalog derived from the activity's own rubric/assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

from .semantic_benchmark_v12 import _fold


P06_CONSTRUCT_RESOLUTION_VERSION = "p06-construct-resolution/1.3.0"

#: A quoted span of any length is *extracted*; length is a classification input,
#: never a silent filter.  v1.2 used ``{2,90}``, which both admitted ``'No'`` as
#: a reference and truncated long quotations out of the accounting entirely.
_QUOTED_SPAN = re.compile(r"[‘'\"“«]([^'’\"”»‘“«]{1,300})[’'\"”»]")

#: Label references.  ``\\d{1,3}`` is what makes ``D10`` representable; the
#: trailing ``(?!\\d)`` keeps ``D1`` from matching inside ``D10``.
_LABEL_REFERENCE = re.compile(r"\b([A-Z]\d{1,3})(?!\d)\b")

#: Leading label of an authorized construct name, e.g. ``D10. Sintesis``.
_LEADING_LABEL = re.compile(r"^([A-Za-z]?\d+)[.)]\s")

#: A reference must carry at least this many content tokens before it can be
#: judged a *near miss* on a catalog name.  One-token spans such as ``'No'``,
#: ``'marca'`` or ``':1,'`` name nothing on their own: they are neither a match
#: nor evidence of a second construct, so they are recorded and ignored.
MIN_NEAR_MISS_TOKENS = 2

#: Share of a reference's own tokens that must appear in a catalog name before
#: the reference counts as a near miss on that name.  Containment is measured
#: against the *reference*, not the name, so a short paraphrase of a long
#: criterion is still caught.
NEAR_MISS_CONTAINMENT = 0.5

# Match rules.
EXACT_NAME = "EXACT_AUTHORIZED_NAME"
EXACT_LABEL = "EXACT_AUTHORIZED_LABEL"

# Reference classifications for unmatched references.
NEAR_MISS = "NEAR_MISS_ON_AUTHORIZED_NAME"
UNRELATED = "UNRELATED_TO_ANY_AUTHORIZED_NAME"
TOO_UNSPECIFIC = "TOO_UNSPECIFIC_TO_NAME_A_CONSTRUCT"

# Fail-closed dispositions.
RESOLVED = "SINGLE_DECLARED_AUTHORIZED_CONSTRUCT"
AMBIGUOUS_REFERENCE = "AMBIGUOUS_AUTHORIZED_CONSTRUCT_REFERENCE"
MULTIPLE_CONSTRUCTS = "MULTIPLE_DECLARED_AUTHORIZED_CONSTRUCTS"
NO_DECLARED_CONSTRUCT = "NO_DECLARED_AUTHORIZED_CONSTRUCT"
NO_AUTHORIZED_CONSTRUCT = "NO_AUTHORIZED_CONSTRUCT_IN_ACTIVITY"


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _fold(value).split() if token)


@dataclass(frozen=True)
class ReferenceObservation:
    """One reference the resolver saw, and what it decided about it.

    Every extracted reference produces exactly one of these, matched or not.
    That total accounting is the property v1.2 lacked: a reference could be
    seen, fail to match and leave no trace.
    """

    reference: str
    kind: str
    matched: bool
    classification: str
    construct_key: str | None = None
    nearest_name: str | None = None
    containment: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "reference": self.reference,
            "reference_kind": self.kind,
            "matched": self.matched,
            "classification": self.classification,
        }
        if self.construct_key is not None:
            row["construct_key"] = self.construct_key
        if self.nearest_name is not None:
            row["nearest_authorized_name"] = self.nearest_name
            row["containment"] = round(self.containment, 4)
        return row


@dataclass(frozen=True)
class ConstructResolution:
    """The outcome of resolving one property against one activity catalog."""

    resolved: bool
    disposition: str
    reason: str
    construct_key: str | None = None
    construct: Mapping[str, Any] | None = None
    observations: tuple[ReferenceObservation, ...] = ()
    candidate_construct_keys: tuple[str, ...] = ()
    blocking_references: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "resolver_version": P06_CONSTRUCT_RESOLUTION_VERSION,
            "resolved": self.resolved,
            "disposition": self.disposition,
            "reason": self.reason,
            "reference_observations": [item.as_dict() for item in self.observations],
            "candidate_construct_keys": list(self.candidate_construct_keys),
            "blocking_references": list(self.blocking_references),
        }
        if self.construct_key is not None:
            row["construct_key"] = self.construct_key
        return row


def extract_references(description: str) -> tuple[tuple[str, str], ...]:
    """Pull every construct reference out of a property description.

    Returns ``(reference, kind)`` pairs.  Quoted spans keep their original text
    so the accounting is auditable against the frozen property bytes.
    """

    references: list[tuple[str, str]] = []
    for span in _QUOTED_SPAN.findall(description):
        references.append((span, "QUOTED_SPAN"))
    for label in _LABEL_REFERENCE.findall(description):
        references.append((label, "LABEL"))
    return tuple(references)


def _nearest(reference: str, names: Mapping[str, Any]) -> tuple[str | None, float]:
    reference_tokens = set(_tokens(reference))
    if not reference_tokens:
        return None, 0.0
    best_name: str | None = None
    best_ratio = 0.0
    for name in names:
        shared = reference_tokens & set(_tokens(name))
        ratio = len(shared) / len(reference_tokens)
        if ratio > best_ratio:
            best_name, best_ratio = name, ratio
    return best_name, best_ratio


def resolve_declared_construct(
    description: str, constructs: Sequence[Mapping[str, Any]]
) -> ConstructResolution:
    """Resolve which single authorized construct a P06 property declares.

    Resolution succeeds only when the property names exactly one catalog
    construct *and* every other reference it makes is accounted for as
    unrelated.  A paraphrase, a second criterion, or an ambiguous fragment all
    block, because a route built from a partial reading would verify less than
    the property asserts while still scoring the candidate as though it
    verified all of it.
    """

    by_name: dict[str, Mapping[str, Any]] = {
        _fold(item["canonical_source_name"]): item for item in constructs
    }
    by_label: dict[str, Mapping[str, Any]] = {}
    for item in constructs:
        match = _LEADING_LABEL.match(item["canonical_source_name"])
        if match is not None:
            by_label[_fold(match.group(1))] = item

    observations: list[ReferenceObservation] = []
    matched: dict[str, Mapping[str, Any]] = {}
    blocking: list[str] = []

    for reference, kind in extract_references(description):
        folded = _fold(reference)
        if not folded:
            observations.append(
                ReferenceObservation(reference, kind, False, TOO_UNSPECIFIC)
            )
            continue
        hit = by_name.get(folded)
        rule = EXACT_NAME
        if hit is None:
            hit = by_label.get(folded)
            rule = EXACT_LABEL
        if hit is not None:
            matched[hit["construct_key"]] = hit
            observations.append(
                ReferenceObservation(
                    reference, kind, True, rule, construct_key=hit["construct_key"]
                )
            )
            continue

        nearest_name, containment = _nearest(reference, by_name)
        if len(_tokens(reference)) < MIN_NEAR_MISS_TOKENS:
            # Too unspecific to name a construct.  Recorded, never matched, and
            # never a blocker: `'No'` is rubric vocabulary, not a declaration.
            observations.append(
                ReferenceObservation(
                    reference,
                    kind,
                    False,
                    TOO_UNSPECIFIC,
                    nearest_name=nearest_name,
                    containment=containment,
                )
            )
            continue
        if containment >= NEAR_MISS_CONTAINMENT:
            observations.append(
                ReferenceObservation(
                    reference,
                    kind,
                    False,
                    NEAR_MISS,
                    nearest_name=nearest_name,
                    containment=containment,
                )
            )
            blocking.append(reference)
            continue
        observations.append(
            ReferenceObservation(
                reference,
                kind,
                False,
                UNRELATED,
                nearest_name=nearest_name,
                containment=containment,
            )
        )

    frozen_observations = tuple(observations)
    frozen_blocking = tuple(blocking)

    if not constructs:
        return ConstructResolution(
            resolved=False,
            disposition=NO_AUTHORIZED_CONSTRUCT,
            reason=(
                "The activity exposes no structured authorized construct, so no "
                "P06 route can be grounded in its own source."
            ),
            observations=frozen_observations,
        )
    if len(matched) > 1:
        return ConstructResolution(
            resolved=False,
            disposition=MULTIPLE_CONSTRUCTS,
            reason=(
                "The property declares more than one authorized construct. A single "
                "P06 call is scoped to one construct, so no one call can demonstrate "
                "or refute the property as a whole."
            ),
            observations=frozen_observations,
            candidate_construct_keys=tuple(sorted(matched)),
            blocking_references=frozen_blocking,
        )
    if frozen_blocking:
        return ConstructResolution(
            resolved=False,
            disposition=AMBIGUOUS_REFERENCE,
            reason=(
                "The property makes a reference that resembles an authorized "
                "construct without naming one. Treating the resolved reference as "
                "the whole target would score the candidate on a construct the "
                "property only partly asserts."
            ),
            observations=frozen_observations,
            candidate_construct_keys=tuple(sorted(matched)),
            blocking_references=frozen_blocking,
        )
    if len(matched) == 1:
        key, construct = next(iter(matched.items()))
        return ConstructResolution(
            resolved=True,
            disposition=RESOLVED,
            reason=(
                "The property names exactly one authorized construct, and every "
                "other reference it makes is unrelated to the catalog."
            ),
            construct_key=key,
            construct=construct,
            observations=frozen_observations,
            candidate_construct_keys=(key,),
        )
    return ConstructResolution(
        resolved=False,
        disposition=NO_DECLARED_CONSTRUCT,
        reason=(
            "The property names no authorized construct, so its target would have "
            "to be inferred. v1.1 inferred it from the evidence location; the "
            "repaired resolver fails closed instead."
        ),
        observations=frozen_observations,
    )
