"""The commercial entitlement vocabulary, and nothing that decides access.

This module is the Stage A compatibility layer named in
`docs/BEDE_LOCUTO_ENTITLEMENT_CONTRACT.md` sections C, D and E. It holds the
three canonical commercial tiers, the three service values, the four
separately-represented limit fields, and the fail-closed answer for anything
outside them.

**It decides nothing.** A commercial tier is what a customer bought. Section C:
it "is not a feature flag, not a permission, not a capability grant, and not a
license field." Access in this codebase is decided by `core/licensing.py`'s
Ed25519-signed payload and by nothing here — section C rule 4 makes that one
way: a commercial entitlement may inform what an operator provisions, and may
never override, relax, or substitute for what a signed license verifies. Where
the two disagree the signed license governs and the disagreement is a
`manual_review` condition, which `compare_children_limit` below reports and
does not resolve.

**What is deliberately absent, and must stay absent until ruled.** Three
questions block the rest of Stage A and none of them is answered here, because
answering one by implementation is how an unruled policy becomes a fact nobody
decided:

* **No legacy-to-commercial mapping of any kind.** `legacy_equivalent_of` does
  not exist. Section C rule 2 says legacy signed `coop` and commercial `coop`
  are different values that happen to be spelled the same, and that a mapping,
  if one is wanted, is an explicit table written down rather than an equality
  test. Nobody has said one is wanted. Until they do, the honest state is no
  correspondence at all, and `describe_legacy_tier` returns exactly that.
* **No commercial trial.** Section C rule 3: `core` and `trial` have no
  commercial counterpart, and Stage A must not invent one. Whether a trial
  precedes the Family Membership is unruled (Bede decision register entry 10
  lists it under "Not decided here"), and minting a fourth `CommercialTier`
  member would be a contract amendment rather than an implementation detail.
* **No cap policy.** What happens to a household above the Family child limit
  is unruled. This module represents `max_children` and can report that a
  signed license disagrees with it; it does not price an overage, warn, widen a
  cap, or upgrade anyone.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CommercialTier(str, Enum):
    """The canonical commercial tiers. Exactly three, closed by construction.

    Section C fixes these values. `from_wire` is the only way in, so an
    unrecognized string cannot become a member by any route.
    """

    FAMILY = "family"
    COOP = "coop"
    NETWORK = "network"


class EntitledService(str, Enum):
    """The service vocabulary of section D. Exactly three, closed.

    Section D, for every one of them without exception: **entitlement is not
    provisioning.** Membership here states that a customer bought the right to
    a service. It states nothing about whether that service is installed,
    reachable, configured, licensed, or built.
    """

    BEDE_TUTOR = "bede_tutor"
    LOCUTO = "locuto"
    FAMILY_PORTAL = "family_portal"


class Unrepresentable(Exception):
    """A value or comparison this layer refuses to resolve on its own.

    Always a `manual_review` condition rather than a default. Sections C rule 5
    and D say the same thing about an unknown tier and an unknown service: do
    not guess, do not fall back to the cheapest or the most generous, do not
    ignore the unrecognized member and proceed with the rest. Record it, set
    `manual_review`, stop.
    """


@dataclass(frozen=True)
class Limits:
    """Section E's four fields, kept apart on purpose.

    There is no bare `seats` field and there never may be, because the word
    means children to one product, households to another and administrators to
    a third, and one number carrying all three is how a co-op comes to be
    provisioned as a family.

    `None` means **this dimension is not constrained by this field**. It never
    means zero and never means unlimited-by-default. A consumer that cannot
    determine a limit it needs in order to provision safely does not assume a
    generous value; it sets `manual_review`.
    """

    max_children: Optional[int] = None
    max_households: Optional[int] = None
    max_seats: Optional[int] = None
    max_organizations: Optional[int] = None


def tier_from_wire(value: str) -> CommercialTier:
    """The only way a string becomes a `CommercialTier`. Unknown fails closed."""
    try:
        return CommercialTier(value)
    except ValueError:
        raise Unrepresentable(
            f"unknown commercial_tier {value!r} — manual_review, never a default"
        ) from None


def services_from_wire(values: list[str]) -> frozenset[EntitledService]:
    """Resolve a service set, all or nothing.

    A single unrecognized member fails the whole set rather than being dropped,
    because section D says a partially understood entitlement provisioned
    partially is exactly the silent wrong outcome section H forbids.
    """
    try:
        return frozenset(EntitledService(v) for v in values)
    except ValueError:
        known = sorted(s.value for s in EntitledService)
        raise Unrepresentable(
            f"unknown entitled_service in {values!r} (known: {known}) — "
            "manual_review; the recognized members are not provisioned without it"
        ) from None


def children_limit_from_signed_seats(seats: int) -> Limits:
    """A signed license's `seats` is a count of CHILDREN, and maps to
    `max_children` — never to `max_seats`, however closely the names read.

    Section C rule 6 is explicit, and calls this the sharper of the section's
    two string collisions: `coop` and `coop` at least denote the same kind of
    thing, while `seats` and `max_seats` denote opposite populations — children
    against adult or administrative accounts. The obvious name-matching mapping
    would leave a family entitlement with no child limit at all.

    Every other field is left `None`: a signed license says nothing about
    households, administrators or sub-organizations, and inventing a value for
    a dimension the source never carried is the assumption section E forbids.
    """
    return Limits(max_children=seats)


def compare_children_limit(signed_seats: int, commercial: Limits) -> Optional[str]:
    """Detect and describe a disagreement. Never resolve one.

    Section J Stage A item 5 asks for the mechanism by which a disagreement
    between a signed license and a commercial entitlement is **detected and
    surfaced**, and states that nothing in Stage A may reopen rule 4's
    direction of authority. So this returns a description for an operator and
    changes nothing: the signed license still governs what the software does.

    Returns `None` when there is nothing to say — either the commercial side
    does not constrain children, or the two agree. Returns a sentence when they
    disagree, which the caller records as a `manual_review` condition.
    """
    if commercial.max_children is None:
        return None
    if commercial.max_children == signed_seats:
        return None
    return (
        f"signed license allows {signed_seats} children; commercial entitlement "
        f"records max_children={commercial.max_children}. The signed license "
        "governs (contract section C rule 4) — this is a manual_review "
        "condition, not a change to what is enforced."
    )


def describe_legacy_tier(legacy_tier: str) -> str:
    """State plainly that no legacy-to-commercial correspondence exists.

    Deliberately returns prose for an operator rather than a `CommercialTier`,
    so that no call site can mistake this for a mapping function or grow one by
    accident. See this module's docstring for why the mapping is absent.
    """
    return (
        f"legacy signed tier {legacy_tier!r} has no commercial equivalent in this "
        "codebase. No legacy-to-commercial mapping has been ruled, and section C "
        "rule 2 forbids inferring one from a shared spelling."
    )
