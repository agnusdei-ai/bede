"""Guards for core/tier_display.py — what a customer is told their licence is.

The defect these were written after: under the self-serve launch catalog
(register entry 35) every annual Family Membership mints `tier: "core"`, and
five surfaces interpolated that raw signed string into text a parent reads. A
family who had just paid for a Family Membership was told they held a "Core
license" — a product on no price list.

What these guards protect is narrower than "the labels are nice": a label map
is one step away from the legacy-to-commercial mapping entry 28 forbids, and
the way that mapping arrives is by someone widening a display helper until it
returns a `CommercialTier`. So coverage and non-commercial-ness are both
asserted, and the second matters more than the first.
"""
from __future__ import annotations

import pytest

from core import commercial_tiers as ct
from core import tier_display
from core.licensing import _VALID_TIERS


def test_every_signed_tier_has_a_customer_facing_label():
    """A signed tier with no label renders raw to a paying customer.

    Read from `_VALID_TIERS` rather than restated, so adding a signed tier
    fails here until someone decides what a customer is told it is called.
    """
    assert tier_display.covered_tiers() == frozenset(_VALID_TIERS)


@pytest.mark.parametrize("tier", sorted(_VALID_TIERS))
def test_no_label_is_the_raw_signed_string(tier: str):
    """With one exemption, stated with its reason.

    `trial` is labelled "Trial", which matches the signed string and is
    nonetheless correct: the free 30-day trial is called a trial on the
    storefront, so the spelling match is a coincidence rather than an internal
    name leaking out. `core` and `coop` have no such excuse — neither word
    appears on any price list.
    """
    label = tier_display.label_for(tier)
    if tier == "trial":
        assert label == "Trial"
        return
    assert label != tier
    assert tier not in label.lower()


def test_the_trial_exemption_still_names_a_real_tier():
    """An exemption must not outlive the thing it excuses."""
    assert "trial" in _VALID_TIERS


@pytest.mark.parametrize("tier", sorted(_VALID_TIERS))
def test_a_label_is_never_a_commercial_tier_value(tier: str):
    """The guard that keeps this from becoming entry 28's forbidden mapping.

    Entry 28 ruled there is no implicit legacy-to-commercial mapping, and
    contract §C rule 2 forbids inferring one from a shared spelling. A display
    label is prose for a human and must never BE a `CommercialTier` value, or
    a call site could start reading one out of it.
    """
    commercial_values = {member.value for member in ct.CommercialTier}
    assert tier_display.label_for(tier) not in commercial_values


def test_an_unknown_tier_degrades_rather_than_raising():
    """Every call site is composing a message a parent is about to read.

    A seat-cap refusal or an expiry notice must not fail closed over a naming
    gap; the coverage guard above is where a missing label is meant to be loud.
    """
    assert tier_display.label_for("some_future_tier") == "some_future_tier"


def test_coop_is_not_claimed_to_be_one_product():
    """`docs/SELLING_BEDE.md` maps `coop` to a Co-op OR a Network, sized by
    seats, and the signed payload carries nothing that distinguishes them, so
    naming one would render a guess to a customer as a fact."""
    label = tier_display.label_for("coop").lower()
    assert "co-op" in label and "network" in label


def test_the_label_module_needs_no_cryptography_to_import():
    """`core/licensing.py` pulls in an elliptic-curve library. A module whose
    job is naming three strings should not drag that into every process that
    wants a label, so the import is deliberately absent and stays absent."""
    source = (tier_display.__file__ or "")
    assert source
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "from core.licensing import" not in text
    assert "import licensing" not in text
