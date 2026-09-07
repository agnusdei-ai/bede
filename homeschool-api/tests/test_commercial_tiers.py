"""Guards for core/commercial_tiers.py — the Stage A compatibility layer.

Every assertion here is determined by the frozen entitlement contract. Nothing
here encodes an expected result that depends on an unruled commercial policy:
no test asserts what a legacy tier maps to, whether a trial is sold, or what
happens to a household above a cap, because none of those has been decided and
a test asserting one would make it true by implementation.
"""
import pytest

from core import commercial_tiers as ct
from core import licensing


# ── Section C: the tier vocabulary is closed, and fails closed ──────────────


def test_exactly_three_canonical_commercial_tiers():
    assert {t.value for t in ct.CommercialTier} == {"family", "coop", "network"}


@pytest.mark.parametrize("value", ["family", "coop", "network"])
def test_each_canonical_tier_resolves(value):
    assert ct.tier_from_wire(value).value == value


@pytest.mark.parametrize(
    "value", ["enterprise", "core", "trial", "FAMILY", "", "family ", "premium"]
)
def test_an_unknown_tier_fails_closed(value):
    """Never a default, never the cheapest, never the most generous."""
    with pytest.raises(ct.Unrepresentable):
        ct.tier_from_wire(value)


def test_core_and_trial_are_not_commercial_tiers():
    """Section C rule 3 — Stage A must not invent a counterpart for either."""
    for legacy_only in ("core", "trial"):
        assert legacy_only not in {t.value for t in ct.CommercialTier}


# ── Section D: services are closed, and a single unknown fails the whole set ─


def test_exactly_three_entitled_services():
    assert {s.value for s in ct.EntitledService} == {
        "bede_tutor",
        "locuto",
        "family_portal",
    }


def test_a_known_service_set_resolves():
    got = ct.services_from_wire(["bede_tutor", "locuto"])
    assert got == frozenset({ct.EntitledService.BEDE_TUTOR, ct.EntitledService.LOCUTO})


def test_one_unknown_service_fails_the_whole_set():
    """Section D: an unrecognized member is never dropped so the rest can
    proceed. A partially understood entitlement provisioned partially is the
    silent wrong outcome section H forbids."""
    with pytest.raises(ct.Unrepresentable):
        ct.services_from_wire(["bede_tutor", "quantum_tutor"])


# ── Section E: four fields, kept apart ─────────────────────────────────────


def test_limits_carries_four_distinct_fields():
    lim = ct.Limits(max_children=6, max_households=1, max_seats=2, max_organizations=None)
    assert (lim.max_children, lim.max_households, lim.max_seats, lim.max_organizations) \
        == (6, 1, 2, None)


def test_there_is_no_bare_seats_field():
    """Section E: there is no bare `seats` field and there never may be."""
    assert not hasattr(ct.Limits(), "seats")


def test_every_limit_defaults_to_none_not_zero():
    """`None` means this dimension is not constrained by this field. It never
    means zero and never means unlimited-by-default."""
    lim = ct.Limits()
    assert lim.max_children is None and lim.max_households is None
    assert lim.max_seats is None and lim.max_organizations is None


# ── Section C rule 6: seats is children, and never administrators ───────────


def test_signed_seats_maps_to_max_children():
    assert ct.children_limit_from_signed_seats(6).max_children == 6


def test_signed_seats_never_reaches_max_seats():
    """The sharper of the two collisions. `seats` counts children; `max_seats`
    counts adult or administrative accounts. The name-matching mapping would
    leave a family entitlement with no child limit at all."""
    lim = ct.children_limit_from_signed_seats(6)
    assert lim.max_seats is None


def test_seats_invents_no_other_dimension():
    lim = ct.children_limit_from_signed_seats(10)
    assert lim.max_households is None and lim.max_organizations is None


# ── Section J item 5: a disagreement is detected and surfaced, not resolved ──


def test_agreement_is_silent():
    assert ct.compare_children_limit(6, ct.Limits(max_children=6)) is None


def test_an_unconstrained_commercial_limit_is_silent():
    assert ct.compare_children_limit(6, ct.Limits()) is None


def test_a_disagreement_is_reported_as_manual_review():
    msg = ct.compare_children_limit(6, ct.Limits(max_children=10))
    assert msg is not None
    assert "manual_review" in msg
    assert "signed license governs" in msg


def test_comparing_changes_nothing_that_is_enforced():
    """Rule 4's direction of authority is not reopened here: the function
    returns a description and has no other effect."""
    before = licensing._VALID_TIERS.copy()
    ct.compare_children_limit(6, ct.Limits(max_children=99))
    assert licensing._VALID_TIERS == before


# ── What must stay absent until D-1, D-2 and D-3 are ruled ─────────────────


def test_no_legacy_to_commercial_mapping_exists():
    """Section C rule 2 forbids inferring a mapping from a shared spelling, and
    no mapping has been ruled. A function that returned one would make an
    unruled policy true by implementation."""
    forbidden = [
        n for n in dir(ct)
        if any(k in n.lower() for k in ("map", "equivalent", "upgrade", "migrate"))
    ]
    assert forbidden == [], f"a mapping-shaped symbol appeared: {forbidden}"


def test_the_legacy_describer_returns_prose_and_not_a_tier():
    """It must be impossible to mistake this for a mapping, or to grow one."""
    out = ct.describe_legacy_tier("coop")
    assert isinstance(out, str)
    assert not isinstance(out, ct.CommercialTier)
    assert "no commercial equivalent" in out


def test_no_cap_policy_is_embedded():
    """No number in this module decides what happens above a cap. Six is a
    price-list figure, not a constant here, until someone rules on it."""
    src = open(ct.__file__).read()
    body = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith(("#", "*"))
    )
    assert " = 6" not in body and "MAX_CHILDREN" not in body
