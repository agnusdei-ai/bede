"""
Picture study spans five files that must agree, and nothing checked them.

`data/visual_aids.json` stores a Wikipedia article title, never an image
URL — deliberately, so the catalog survives Wikimedia path changes and this
project hosts no artwork. The consequence is that `VisualAidCard.tsx`
resolves the picture live, from the browser, across TWO origins in TWO
different CSP directives:

    fetch(en.wikipedia.org/api/rest_v1/...)   -> connect-src
    <img src=upload.wikimedia.org/...>        -> img-src

and there are two policies to satisfy, for two deployments: `site/_headers`
(the public demo on Cloudflare) and `homeschool-tutor/nginx.conf` (a
family's own LAN). Four places, one fact.

Before this, every one of them was wrong: neither policy allowed either
origin, so every picture-study card on the demo showed "Picture unavailable
right now" — silently, because `VisualAidCard.tsx` degrades to a captioned
card by design and a CSP refusal produces the same bare TypeError as any
other failed fetch. The feature looked implemented and was not reachable.

The half-fix is the trap worth pinning against. Allowing only
`connect-src` makes the lookup succeed and the image still fail, which
renders the *identical* "Picture unavailable" card — so the obvious fix,
applied to the obvious directive, changes nothing a visitor can see and
reads as "still broken" rather than "half done".

This is the `tests/test_compose_settings_passthrough.py` pattern: two (here
four) copies of one fact, checked rather than trusted.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_HEADERS = _REPO / "site" / "_headers"
_NGINX = _REPO / "homeschool-tutor" / "nginx.conf"
_CARD = _REPO / "homeschool-tutor" / "src" / "components" / "VisualAidCard.tsx"
_DEMO_CARD = _REPO / "demo" / "src" / "VisualAidCard.tsx"

# The image host cannot be derived from source the way the lookup host can:
# it arrives at runtime in the API response (`thumbnail.source`), so it
# appears in no file here. Wikimedia serves every file from this single
# host — the article host never serves the image itself.
_IMAGE_HOST = "https://upload.wikimedia.org"


def _policy(text: str) -> str:
    """The Content-Security-Policy value from either file's own syntax."""
    match = re.search(
        r"Content-Security-Policy[:\s]+\"?(default-src[^\"]*?)\"?\s*(?:always)?;?\s*$",
        text,
        re.MULTILINE,
    )
    assert match, "no Content-Security-Policy found"
    return " ".join(match.group(1).split())


def _directive(policy: str, name: str) -> str:
    for part in policy.split(";"):
        part = part.strip()
        if part.startswith(name + " "):
            return part
    raise AssertionError(f"{name} missing from policy: {policy}")


def _lookup_host_from_source(card: Path) -> str:
    """The origin VisualAidCard actually fetches, read from the component
    rather than restated here — if someone repoints it at a different
    Wikimedia endpoint, this test must follow them, not keep asserting the
    old one."""
    source = card.read_text()
    match = re.search(r"fetch\(\s*`(https://[^/`]+)", source)
    assert match, f"no cross-origin fetch found in {card.name}"
    return match.group(1)


ALL_POLICIES = [
    pytest.param(_HEADERS, id="site/_headers (public demo)"),
    pytest.param(_NGINX, id="nginx.conf (self-hosted)"),
]


@pytest.mark.parametrize("path", ALL_POLICIES)
def test_connect_src_allows_the_lookup_the_component_actually_makes(path):
    host = _lookup_host_from_source(_CARD)
    connect = _directive(_policy(path.read_text()), "connect-src")
    assert host in connect, (
        f"{path.name}'s connect-src does not permit {host}, which "
        f"VisualAidCard.tsx fetches. The lookup is refused before it is "
        f"sent and every picture-study card renders 'Picture unavailable'."
    )


@pytest.mark.parametrize("path", ALL_POLICIES)
def test_img_src_allows_the_image_that_lookup_returns(path):
    """The half-fix guard. connect-src alone leaves a card that resolves
    and then cannot paint — visually identical to the bug."""
    img = _directive(_policy(path.read_text()), "img-src")
    assert _IMAGE_HOST in img, (
        f"{path.name}'s img-src does not permit {_IMAGE_HOST}. The lookup "
        f"will succeed and the thumbnail will still be blocked, which "
        f"renders the same 'Picture unavailable' card as no fix at all."
    )


def test_both_frontends_resolve_from_the_same_origin():
    """demo/ mirrors the app's component (same convention as
    demo/src/holdGesture.ts). Two copies pointing at different origins
    would need two different CSP entries, and only one would get one."""
    assert _lookup_host_from_source(_CARD) == _lookup_host_from_source(_DEMO_CARD)


@pytest.mark.parametrize("path", ALL_POLICIES)
def test_no_policy_opens_these_directives_to_everything(path):
    """Allowing the two origins must not turn into allowing any origin.
    A wildcard here would silently undo the reason the hosts are named."""
    policy = _policy(path.read_text())
    for name in ("connect-src", "img-src"):
        directive = _directive(policy, name)
        assert " *" not in directive and not directive.endswith(" *"), (
            f"{path.name}'s {name} contains a bare wildcard: {directive}"
        )
        assert "https://*" not in directive.replace("https://*.onrender.com", ""), (
            f"{path.name}'s {name} contains an unexpected wildcard host: {directive}"
        )


@pytest.mark.parametrize(
    "card", [pytest.param(_CARD, id="app"), pytest.param(_DEMO_CARD, id="demo")]
)
def test_the_captioned_fallback_still_exists(card):
    """What makes allowing these origins a CHOICE rather than a condition
    of using Bede: a family that strips them from their own CSP gets a
    captioned card, not a broken feature. docs/VENDOR_DATA_FLOW.md tells
    them so, which is only honest while this fallback is real."""
    source = card.read_text()
    assert "setFailed(true)" in source
    assert "failed" in source
