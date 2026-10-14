"""What a customer is told their licence is called.

A signed tier (`core/licensing.py`'s `_VALID_TIERS`) is a frozen provenance
label on an Ed25519-signed artifact. It is **not** the name of anything on the
price list, and under the self-serve launch catalog (decision register entry
35) every annual Family Membership mints `tier: "core"` on purpose — the
indirection is deliberate and documented in `docs/SELLING_BEDE.md`.

What was missing is the other half of a deliberate indirection: rendering the
outward name. Five surfaces interpolated the raw signed string into text a
parent reads, so a family who had just paid for a **Family Membership** was
told they held a "Core license" — a product that appears in no price list, and
whose Spanish rendering ("Licencia principal") additionally implies a ladder
with a lesser tier beneath it, which register entry 10 abolished.

**This is not the mapping entry 28 forbids, and the distinction is exact.**
Entry 28 forbids inferring a *commercial tier* from a signed one. Nothing here
returns a `core/commercial_tiers.py` value, nothing decides access, and the
contract's §C rule 4 direction of authority is untouched: the signed license
still governs. This returns prose for a human, following
`commercial_tiers.describe_legacy_tier`'s own precedent.

**Deliberately not in `core/commercial_tiers.py`.** That module's guard
(`tests/test_commercial_tiers.py::test_no_legacy_to_commercial_mapping_exists`)
scans its namespace for any symbol containing `map`/`equivalent`/`upgrade`/
`migrate`, which is entry 28's implementation. A display map placed there would
either fail that guard or force it to be weakened, and weakening it to make
room for a label is how the forbidden mapping arrives by drift.

**`coop` carries two products and the label says so.** `docs/SELLING_BEDE.md`
maps `coop` to a Co-op **or** a Network membership, sized by seats, so the
signed payload cannot distinguish them and no honest single product name
exists. Naming one would be a guess rendered to a customer as a fact.
"""
from __future__ import annotations

#: Signed tier -> the name a customer actually bought. Keys are checked
#: against `_VALID_TIERS` by test, so a newly accepted signed tier fails CI
#: until someone decides what a customer is told it is called.
_TIER_LABELS = {
    "trial": "Trial",
    "core": "Family Membership",
    "coop": "Co-op or Network Membership",
    "campus_location": "Campus Location Subscription",
}


def label_for(tier: str) -> str:
    """The customer-facing name for a signed tier.

    Falls back to the raw string for an unrecognized tier rather than raising:
    every call site is composing a message a parent is about to read (a seat
    cap refusal, an expiry notice), and failing one of those closed would turn
    a naming gap into a broken page. The coverage guard lives in the test
    suite, where a missing label is loud and costs nobody a lesson.
    """
    return _TIER_LABELS.get(tier, tier)


def covered_tiers() -> frozenset[str]:
    """The signed tiers this module can name — read by the coverage guard.

    `core/licensing.py` is deliberately NOT imported here: it pulls in an
    elliptic-curve library, and a module whose entire job is to name three
    strings should not drag cryptography into every process that wants a
    label. The guard reads `_VALID_TIERS` from `licensing` itself and compares
    it to this set, so the two still cannot drift apart.
    """
    return frozenset(_TIER_LABELS)

