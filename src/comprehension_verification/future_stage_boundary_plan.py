"""Future stage-boundary requirements for a benchmark version after v1.2.

Phase 9B.6 introduced two P07 artifacts that did not exist when
``semantic-benchmark/1.2.0`` was frozen:

* :mod:`p07_field_authority` -- which canonical P07 fields are ``MODEL_OWNED``,
  ``SERVER_OWNED`` and ``SERVER_DERIVED_FROM_MODEL_INPUT``;
* :mod:`p07_adjudication_context` -- the blind companion that carries the
  opportunity context and that field authority to a P07 reviewer.

The v1.2 P07 stage boundary is the *generic* one.  It binds the corpus package,
the P07 case definitions, the P07 property bindings, the split assignments and
the v1.1 opportunity fixture file, and nothing else.  It binds no materializer,
no schema and neither companion artifact.  So a change to the P07 field
authority or to the companion cannot invalidate a v1.2 P07 stage boundary hash,
which is precisely the property a stage boundary exists to provide.

Consequence, and the whole point of this module: **any future benchmark version
that adopts the Phase 9B.6 P07 repair must publish a new P07 stage boundary.**
A plan that adopts the companion and leaves P07 out of its changed-boundary set
is rejected here rather than discovered after a freeze.

This module states the requirement and validates a plan against it.  It does
**not** compute a v1.3 boundary and does not create one: which alternative is
adopted is a product decision that Phase 9B.6 explicitly refuses to make.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_hash
from .p07_adjudication_context import P07_ADJUDICATION_CONTEXT_VERSION
from .p07_field_authority import P07_FIELD_AUTHORITY_VERSION
from .semantic_benchmark import ACTIVE_BENCHMARK_STAGES


FUTURE_STAGE_BOUNDARY_PLAN_VERSION = "future-stage-boundary-plan/1.0.0"

#: The Phase 9B.6 P07 companion artifacts.  Adopting either one obliges a new
#: P07 stage boundary, because neither is bound by the v1.2 one.
P07_COMPANION_ARTIFACTS: tuple[str, ...] = (
    P07_FIELD_AUTHORITY_VERSION,
    P07_ADJUDICATION_CONTEXT_VERSION,
)

#: The minimum a future P07 stage boundary must bind.  Every entry is something
#: that can change what a P07 candidate was asked for, what it produced, or what
#: a blind reviewer is shown -- which is the definition of a stage-boundary
#: dependency.
P07_FUTURE_STAGE_BOUNDARY_DEPENDENCIES: tuple[str, ...] = (
    "P07 case definitions",
    "P07 property bindings",
    "P07 fixture/opportunity definitions",
    "P07 split assignments",
    "P07 materializer executable boundary",
    "QuestionAliasEnvelope schema boundary",
    "QuestionModelDraft schema",
    "P07 field authority hash",
    "P07 field authority executable source hash",
    "P07 adjudication context schema version",
    "P07 adjudication context executable source hash",
    "P07 opportunity-context generation dependency required for blind attribution",
)

#: Stages whose boundary is a function of corpus bytes.  Every active stage is,
#: because every stage boundary binds ``corpus_package_boundary_hash``.
CORPUS_DEPENDENT_STAGES: tuple[str, ...] = tuple(ACTIVE_BENCHMARK_STAGES)

#: The floor for a future version that changes no corpus byte.  P06 because
#: every open alternative changes the P06 gate; P07 because the Phase 9B.6 P07
#: repair is unbound by the v1.2 P07 boundary.
MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARIES: tuple[str, ...] = ("P06", "P07")


class FutureStageBoundaryPlanError(ValueError):
    """Raised when a future boundary plan is internally unsound."""


def p07_future_stage_boundary_requirement() -> dict[str, Any]:
    """State why a new P07 stage boundary is mandatory, and what it must bind."""

    material = {
        "schema_version": FUTURE_STAGE_BOUNDARY_PLAN_VERSION,
        "stage": "P07",
        "v12_p07_boundary_kind": "GENERIC_CARRIED_FORWARD_FROM_V11",
        "v12_p07_boundary_binds": [
            "corpus package boundary",
            "P07 case definitions",
            "P07 property bindings",
            "P07 split assignments",
            "v1.1 P07 opportunity fixture file hash",
        ],
        "v12_p07_boundary_does_not_bind": list(
            P07_FUTURE_STAGE_BOUNDARY_DEPENDENCIES[4:]
        ),
        "introduced_by_phase_9b6": list(P07_COMPANION_ARTIFACTS),
        "new_p07_stage_boundary_required": True,
        "reason": (
            "The v1.2 P07 stage boundary is the generic one. It binds no "
            "materializer, no schema and neither Phase 9B.6 companion artifact, "
            "so a change to P07 field authority or to the blind companion cannot "
            "invalidate its hash. Any version adopting the P07 repair must "
            "therefore publish a new P07 stage boundary that binds them."
        ),
        "minimum_dependency_inventory": list(
            P07_FUTURE_STAGE_BOUNDARY_DEPENDENCIES
        ),
        "computed_here": False,
        "computation_rule": (
            "This is the dependency plan only. No v1.3 boundary is calculated or "
            "published, because which alternative is adopted is an open product "
            "decision."
        ),
    }
    return {**material, "requirement_hash": canonical_hash(material)}


def _adopts_p07_companion(plan: Mapping[str, Any]) -> bool:
    adopted = plan.get("adopts_phase9b6_artifacts") or []
    return bool(set(adopted) & set(P07_COMPANION_ARTIFACTS))


def validate_future_boundary_plan(plan: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return every violation in a future boundary plan; empty means sound."""

    violations: list[dict[str, str]] = []
    stages = list(plan.get("new_stage_boundaries") or [])
    unknown = sorted(set(stages) - set(ACTIVE_BENCHMARK_STAGES))
    if unknown:
        violations.append(
            {
                "code": "UNKNOWN_STAGE_IN_BOUNDARY_PLAN",
                "detail": f"not active benchmark stages: {', '.join(unknown)}",
            }
        )

    if _adopts_p07_companion(plan) and "P07" not in stages:
        violations.append(
            {
                "code": "P07_COMPANION_ADOPTED_WITHOUT_NEW_P07_STAGE_BOUNDARY",
                "detail": (
                    "The plan adopts a Phase 9B.6 P07 artifact that the v1.2 P07 "
                    "stage boundary does not bind, so P07 must appear in "
                    "new_stage_boundaries."
                ),
            }
        )

    corpus_change = bool(plan.get("corpus_version_change"))
    if not corpus_change:
        missing = [
            stage
            for stage in MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARIES
            if stage not in stages
        ]
        if missing:
            violations.append(
                {
                    "code": "BELOW_MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARY_SET",
                    "detail": (
                        "a no-corpus-change version must recompute at least "
                        f"{', '.join(MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARIES)}; "
                        f"missing {', '.join(missing)}"
                    ),
                }
            )
    else:
        missing = [stage for stage in CORPUS_DEPENDENT_STAGES if stage not in stages]
        if missing:
            violations.append(
                {
                    "code": "CORPUS_CHANGE_WITHOUT_ALL_CORPUS_DEPENDENT_BOUNDARIES",
                    "detail": (
                        "every stage boundary binds the corpus package hash, so a "
                        "corpus version change must recompute all of them; missing "
                        f"{', '.join(missing)}"
                    ),
                }
            )

    if "P07" in stages:
        inventory = list(plan.get("p07_boundary_dependency_inventory") or [])
        missing_dependencies = [
            item
            for item in P07_FUTURE_STAGE_BOUNDARY_DEPENDENCIES
            if item not in inventory
        ]
        if missing_dependencies:
            violations.append(
                {
                    "code": "P07_BOUNDARY_DEPENDENCY_INVENTORY_INCOMPLETE",
                    "detail": (
                        "a new P07 stage boundary must bind at minimum: "
                        f"{'; '.join(missing_dependencies)}"
                    ),
                }
            )

    if not plan.get("new_global_boundary"):
        violations.append(
            {
                "code": "STAGE_BOUNDARY_CHANGE_WITHOUT_NEW_GLOBAL_BOUNDARY",
                "detail": (
                    "the global benchmark boundary binds every stage boundary "
                    "hash, so it cannot stay unchanged"
                ),
            }
        )
    return violations


def assert_future_boundary_plan(plan: Mapping[str, Any]) -> None:
    """Raise unless the plan satisfies every future-boundary requirement."""

    violations = validate_future_boundary_plan(plan)
    if violations:
        rendered = "; ".join(
            f"{item['code']}: {item['detail']}" for item in violations
        )
        raise FutureStageBoundaryPlanError(rendered)


def future_boundary_plan_report(plans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate every alternative's boundary plan and report the outcome."""

    rows = []
    for plan in plans:
        violations = validate_future_boundary_plan(plan)
        rows.append(
            {
                "alternative_id": plan.get("alternative_id"),
                "new_stage_boundaries": list(plan.get("new_stage_boundaries") or []),
                "corpus_version_change": bool(plan.get("corpus_version_change")),
                "violations": violations,
                "sound": not violations,
            }
        )
    material = {
        "schema_version": FUTURE_STAGE_BOUNDARY_PLAN_VERSION,
        "p07_requirement": p07_future_stage_boundary_requirement(),
        "minimum_no_corpus_change_stage_boundaries": list(
            MINIMUM_NO_CORPUS_CHANGE_STAGE_BOUNDARIES
        ),
        "corpus_dependent_stages": list(CORPUS_DEPENDENT_STAGES),
        "plans": rows,
        "all_plans_sound": all(row["sound"] for row in rows),
        "v13_boundary_computed": False,
    }
    return {**material, "report_hash": canonical_hash(material)}


def stages_touched(plans: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return the union of stages every plan would have to recompute."""

    touched: set[str] = set()
    for plan in plans:
        touched.update(plan.get("new_stage_boundaries") or [])
    return tuple(stage for stage in ACTIVE_BENCHMARK_STAGES if stage in touched)
