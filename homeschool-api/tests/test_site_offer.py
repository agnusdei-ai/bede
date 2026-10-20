"""The home page's membership chooser states facts that live elsewhere.

The retired chooser fixture records prices, trial length, seats, and checkout
routes. Keep checking those against the licensing implementation. The live
marketing pages now use email inquiries and do not publish plan pricing.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# The chooser is retired from the inquiry-only website. Preserve the existing
# licensing/price consistency checks against its frozen pre-retirement fixture.
# The live-site contract is checked by scripts/bede-production.test.mjs.
LEGACY = ROOT / "tests/fixtures/marketing-before-inquiry"
SITE = (LEGACY / "index.html").read_text()
LAUNCH = (ROOT / "demo/public/launch.html").read_text()
OFFER_JS = ROOT / "site/assets/offer.js"
LS = ROOT / "license-server/src"
ROUTER = (LS / "index.ts").read_text()
STOREFRONT = (LS / "routes/storefront.ts").read_text()
ISSUE = (LS / "license/issue.ts").read_text()
ENTITLEMENTS = (LS / "license/entitlements.ts").read_text()


def _section() -> str:
    m = re.search(r'<section class="offer" id="membership".*?</section>', SITE, re.S)
    assert m, "the #membership section is missing from site/index.html"
    return m.group(0)


OFFER = _section()


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


def _storefront_origins(html: str) -> set[str]:
    return {m.group(1) for h in _hrefs(html) if (m := re.match(r"(https://[^/]*license-server[^/]*)", h))}


def test_launch_uses_pricing_inquiries_instead_of_public_checkout():
    assert not _storefront_origins(LAUNCH)
    for plan in ("family", "co-op", "school"):
        assert f"mailto:info@agnusdei.ai?subject=Bede%20{plan}%20pricing%20request" in LAUNCH


def test_the_annual_button_goes_to_a_real_checkout_route():
    origin = next(iter(_storefront_origins(OFFER)))
    paths = {h[len(origin):] for h in _hrefs(OFFER) if h.startswith(origin)}
    assert "/checkout/family-annual" in paths
    assert 'case "/checkout/family-annual":' in ROUTER, "the License Server no longer serves that route"


def test_the_trial_button_lands_on_the_storefronts_trial_form():
    origin = next(iter(_storefront_origins(OFFER)))
    assert f"{origin}/#trial-form" in _hrefs(OFFER)
    assert 'id="trial-form"' in STOREFRONT and 'case "/":' in ROUTER


def test_the_trial_length_is_the_signed_one():
    days = int(re.search(r"export const TRIAL_DAYS = (\d+);", ISSUE).group(1))
    assert f"{days} days" in OFFER and f"{days}-day trial" in OFFER
    assert not re.search(r"\b(?!%d\b)\d+[- ]day" % days, re.sub(r"<!--.*?-->", "", OFFER, flags=re.S)), \
        "the chooser names a trial length other than TRIAL_DAYS"


@pytest.mark.parametrize("figure", ["$2,149", "$199", "$239"])
def test_legacy_prices_remain_consistent_with_the_storefront(figure):
    assert figure in OFFER, f"{figure} is missing from the chooser"
    assert figure in STOREFRONT, f"{figure} is missing from the licensing storefront"
    assert figure not in LAUNCH, f"{figure} must not be published on the marketing page"

def test_legacy_coop_price_is_not_a_public_marketing_offer():
    assert "$149" in OFFER
    assert "$149" not in LAUNCH


def test_no_other_dollar_figure_appears():
    published = {"$2,149", "$199", "$239", "$149"}
    shown = set(re.findall(r"\$[\d,]+(?:\.\d\d)?", re.sub(r"<!--.*?-->", "", OFFER, flags=re.S)))
    per_child = {f for f in shown if "." in f}
    assert shown - per_child <= published, f"unpublished figures: {shown - per_child - published}"


def test_the_annual_price_is_the_storefronts():
    assert "$2,149" in STOREFRONT and 'data-annual="2149"' in OFFER


def test_six_children_matches_the_seats_signed_into_the_licence():
    seats = int(re.search(r"ANNUAL_FAMILY_ENTITLEMENT[^}]*seats: (\d+)", ENTITLEMENTS, re.S).group(1))
    words = dict(enumerate("zero one two three four five six seven eight nine ten eleven twelve".split()))
    assert seats in words, f"the licence signs {seats} seats; spell it out here and on the page"
    assert f"Up to {words[seats]} children" in OFFER, f"the licence signs {seats} seats; the chooser says otherwise"
    assert f'max="{seats}"' in OFFER, "the per-child slider's ceiling should be the seat count"


def test_the_printed_per_child_figure_matches_the_pages_own_inputs():
    """The figure printed before the script runs must equal what the script
    prints for the slider's starting value. The script's own arithmetic is
    exercised in a real DOM by demo/src/siteOffer.test.ts."""
    from decimal import Decimal, ROUND_HALF_UP
    annual = int(re.search(r'data-annual="(\d+)"', OFFER).group(1))
    assert f"${annual:,}" in OFFER, "data-annual must be the price the chooser prints"
    n = int(re.search(r'type="range"[^>]*value="(\d+)"', OFFER).group(1))
    expected = Decimal(annual) / 12 / n
    expected = f"${expected.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
    printed = re.search(r'class="per-child-amount">([^<]+)<', OFFER).group(1)
    assert printed == expected, f"with {n} children the page prints {printed}, the script would print {expected}"


def test_the_chooser_works_without_javascript():
    radios = re.findall(r'<input class="plan-radio" type="radio" name="plan"[^>]*>', OFFER)
    assert len(radios) == 3 and sum("checked" in r for r in radios) == 1
    for pid in ("annual", "trial", "coop"):
        assert f'<label class="plan-head" for="plan-{pid}">' in OFFER


def test_no_label_wraps_a_link_or_a_slider():
    for label in re.findall(r"<label\b.*?</label>", OFFER, re.S):
        assert "<a " not in label and 'type="range"' not in label, label[:80]


def test_the_script_is_loaded_and_is_not_inline():
    assert '<script src="/assets/offer.js"></script>' in SITE
    assert OFFER_JS.exists()


def test_no_retired_tier_reappears():
    for name in ("Concierge", "Metered", "Custom annual quote", "self-checkout"):
        assert name not in SITE, f"{name!r} was retired by docs/DECISIONS.md entries 10 and 38"


def test_the_privacy_inventory_names_the_same_trial_and_storefront():
    privacy = (LEGACY / "privacy/index.html").read_text()
    days = int(re.search(r"export const TRIAL_DAYS = (\d+);", ISSUE).group(1))
    host = next(iter(_storefront_origins(OFFER))).removeprefix("https://")
    row = re.search(r"<td>Membership buttons \(home page\)</td>.*?</tr>", privacy, re.S)
    assert row, "site/privacy/index.html has no row for the membership buttons"
    assert f"{days}-day trial" in row.group(0) and host in row.group(0)
    assert not re.search(r"\b(?!%d\b)\d+-day trial" % days, row.group(0))


def test_the_change_filter_names_every_source_this_reads():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    line = next(l for l in workflow.splitlines() if "grep -qE" in l)
    alternatives = line.split("'")[1].strip("^()").split("|")
    for needed in (r"site/index\.html", r"site/assets/offer\.js", r"site/privacy/index\.html", r"demo/public/launch\.html",
                   r"license-server/src/index\.ts", r"license-server/src/routes/storefront\.ts",
                   r"license-server/src/license/issue\.ts", r"license-server/src/license/entitlements\.ts"):
        assert needed in alternatives, f"{needed} is not in test.yml's change filter"
