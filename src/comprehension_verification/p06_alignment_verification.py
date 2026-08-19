"""Independent property/route alignment verification (Phase 9B.6 remediation).

``semantic-benchmark/1.2.0`` reported alignment like this::

    "property_target_construct_key": construct_key,
    "route_target_construct_key":    construct_key,

and then asserted validity with
``property_target_construct_key == route_target_construct_key``.  Both fields
were written from the *same* resolver variable in the same loop iteration, so
the equality held by construction.  Phase 9B.5 recorded 77 of 77 rows
``construct_identity_equal: true`` -- a number that could not have come out any
other way, and therefore carried no falsification power.  A binding that named
the wrong construct consistently in both fields passed.

This module removes the tautology.  Alignment is decided by *re-deriving* the
target construct from material the binding does not control:

* the frozen oracle property description, read from the corpus ratification;
* the authorized construct catalog, derived from the activity's own
  rubric/assignment source.

The declared keys become claims to be checked against that derivation rather
than the evidence for it.  Concretely, a row is ``ALIGNED`` only when

1. the independent resolver resolves the property to exactly one construct;
2. that construct is the one the route actually targets;
3. the route's own construct provenance matches the catalog entry for that
   construct, so the route cannot name a construct it did not come from; and
4. the binding's declared keys agree with the derivation -- checked last, and
   never sufficient on its own.

Counts produced here are evidence about the corpus, not golden constants.  A
future corpus with different properties will produce different counts, and the
verifier is expected to keep working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .canonical import canonical_hash
from .p06_construct_resolution import (
    P06_CONSTRUCT_RESOLUTION_VERSION,
    resolve_declared_construct,
)


P06_ALIGNMENT_VERIFICATION_VERSION = "p06-alignment-verification/1.3.0"

ALIGNED = "ALIGNED"
MISALIGNED_WRONG_CONSTRUCT = "MISALIGNED_ROUTE_TARGETS_A_DIFFERENT_CONSTRUCT"
MISALIGNED_UNRESOLVABLE = "MISALIGNED_PROPERTY_DOES_NOT_DECLARE_ONE_CONSTRUCT"
MISALIGNED_UNGROUNDED_ROUTE = "MISALIGNED_ROUTE_CONSTRUCT_NOT_GROUNDED_IN_CATALOG"
MISALIGNED_DECLARED_KEY_DRIFT = "MISALIGNED_DECLARED_KEY_CONTRADICTS_DERIVATION"


class AlignmentVerificationError(ValueError):
    """Raised when the verifier is given material it cannot check."""


@dataclass(frozen=True)
class AlignmentVerdict:
    property_id: str
    fixture_id: str
    status: str
    independently_derived_construct_key: str | None
    route_target_construct_key: str
    declared_property_construct_key: str | None
    declared_route_construct_key: str | None
    derivation_disposition: str
    reason: str

    @property
    def aligned(self) -> bool:
        return self.status == ALIGNED

    def as_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "fixture_id": self.fixture_id,
            "alignment_status": self.status,
            "aligned": self.aligned,
            "independently_derived_construct_key": (
                self.independently_derived_construct_key
            ),
            "route_target_construct_key": self.route_target_construct_key,
            "declared_property_target_construct_key": (
                self.declared_property_construct_key
            ),
            "declared_route_target_construct_key": self.declared_route_construct_key,
            "derivation_disposition": self.derivation_disposition,
            "reason": self.reason,
        }


def _catalog_index(constructs: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {item["construct_key"]: item for item in constructs}


def _route_is_grounded(
    route: Mapping[str, Any], construct: Mapping[str, Any]
) -> tuple[bool, str]:
    """Check the route's provenance really came from this catalog entry.

    Without this, a fabricated route could name any construct key it liked and
    the derivation comparison would be checking a label rather than a route.
    """

    provenance = route.get("construct_provenance") or {}
    if provenance.get("canonical_source_name") != construct["canonical_source_name"]:
        return False, "route provenance names a different canonical source name"
    if list(provenance.get("source_refs") or []) != list(construct["source_refs"]):
        return False, "route provenance cites different authorized source refs"
    if dict(provenance.get("source_hashes") or {}) != dict(construct["source_hashes"]):
        return False, "route provenance carries different authorized source hashes"
    if provenance.get("source_kind") != construct["source_kind"]:
        return False, "route provenance declares a different authorized source kind"
    return True, ""


def verify_binding_alignment(
    *,
    binding: Mapping[str, Any],
    route: Mapping[str, Any],
    property_description: str,
    constructs: Sequence[Mapping[str, Any]],
) -> AlignmentVerdict:
    """Decide alignment from frozen source, not from the binding's own claim."""

    property_id = str(binding["property_id"])
    fixture_id = str(route["route_fixture_id"])
    if binding.get("fixture_id") != fixture_id:
        raise AlignmentVerificationError(
            f"{property_id}: binding and route describe different fixtures"
        )
    route_key = str(route["target_construct_key"])
    declared_property_key = binding.get("property_target_construct_key")
    declared_route_key = binding.get("route_target_construct_key")

    resolution = resolve_declared_construct(property_description, constructs)
    derived_key = resolution.construct_key

    def verdict(status: str, reason: str) -> AlignmentVerdict:
        return AlignmentVerdict(
            property_id=property_id,
            fixture_id=fixture_id,
            status=status,
            independently_derived_construct_key=derived_key,
            route_target_construct_key=route_key,
            declared_property_construct_key=declared_property_key,
            declared_route_construct_key=declared_route_key,
            derivation_disposition=resolution.disposition,
            reason=reason,
        )

    if not resolution.resolved:
        return verdict(
            MISALIGNED_UNRESOLVABLE,
            (
                "Re-deriving the target from the frozen property text does not yield "
                f"exactly one authorized construct ({resolution.disposition}), so no "
                "route may score a candidate against it."
            ),
        )

    catalog = _catalog_index(constructs)
    construct = catalog.get(route_key)
    if construct is None:
        return verdict(
            MISALIGNED_UNGROUNDED_ROUTE,
            "The route targets a construct key that is absent from the authorized "
            "catalog for this activity.",
        )
    grounded, why = _route_is_grounded(route, construct)
    if not grounded:
        return verdict(
            MISALIGNED_UNGROUNDED_ROUTE,
            f"The route is not grounded in its declared catalog entry: {why}.",
        )

    if derived_key != route_key:
        return verdict(
            MISALIGNED_WRONG_CONSTRUCT,
            (
                "The property independently resolves to "
                f"{derived_key!r}, but the route targets {route_key!r}. The route "
                "would score the candidate on a construct the property does not "
                "assert."
            ),
        )

    if declared_property_key != derived_key or declared_route_key != route_key:
        return verdict(
            MISALIGNED_DECLARED_KEY_DRIFT,
            (
                "The binding's declared construct keys contradict the independent "
                "derivation. Declared keys are checked against the derivation; they "
                "are never its evidence."
            ),
        )

    return verdict(
        ALIGNED,
        (
            "The frozen property text independently resolves to the construct the "
            "route targets, and the route's provenance matches that catalog entry."
        ),
    )


def verify_alignment_report(
    *,
    bindings: Sequence[Mapping[str, Any]],
    routes: Sequence[Mapping[str, Any]],
    property_descriptions: Mapping[str, str],
    constructs_by_activity: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Verify every P06 binding and report the verdicts.

    ``aligned_count`` here is a measurement.  It is deliberately *not* asserted
    to equal the row count anywhere in this module: the whole point is that a
    misaligned row can exist and be seen.
    """

    routes_by_id = {str(item["route_fixture_id"]): item for item in routes}
    verdicts: list[AlignmentVerdict] = []
    for binding in bindings:
        if binding.get("stage") != "P06":
            continue
        property_id = str(binding["property_id"])
        fixture_id = str(binding["fixture_id"])
        route = routes_by_id.get(fixture_id)
        if route is None:
            raise AlignmentVerificationError(
                f"{property_id}: binding names an unknown route {fixture_id}"
            )
        description = property_descriptions.get(property_id)
        if description is None:
            raise AlignmentVerificationError(
                f"{property_id}: no frozen property description to derive from"
            )
        constructs = constructs_by_activity.get(str(route["activity_id"]), ())
        verdicts.append(
            verify_binding_alignment(
                binding=binding,
                route=route,
                property_description=description,
                constructs=constructs,
            )
        )

    rows = [item.as_dict() for item in sorted(verdicts, key=lambda v: v.property_id)]
    misaligned = [row for row in rows if not row["aligned"]]
    material = {
        "schema_version": P06_ALIGNMENT_VERIFICATION_VERSION,
        "resolver_version": P06_CONSTRUCT_RESOLUTION_VERSION,
        "derivation_authority": (
            "FROZEN_ORACLE_PROPERTY_TEXT_AND_AUTHORIZED_CONSTRUCT_CATALOG"
        ),
        "declared_keys_are_checked_not_trusted": True,
        "rows": rows,
        "row_count": len(rows),
        "aligned_count": len(rows) - len(misaligned),
        "misaligned_count": len(misaligned),
        "misaligned_property_ids": sorted(row["property_id"] for row in misaligned),
    }
    return {**material, "report_hash": canonical_hash(material)}
