"""
The home page's video and the site's referrer policy are one fact in two
files, and when they disagree the video simply refuses to play.

`site/_headers` sets `Referrer-Policy: no-referrer` for the whole domain —
deliberately, mirroring what `core/middleware.py` and `nginx.conf` already
enforce for the product itself. Since late 2025 YouTube's embedded player
requires an HTTP `Referer` identifying the embedding host, and shows
"Error 153 — Video player configuration error" in place of the video when
it does not get one. A domain-wide `no-referrer` therefore breaks every
YouTube embed under it, including this one, which is how it reached us: a
screenshot of error 153 on agnusdei.ai.

The fix is an element-level override — an element's `referrerpolicy`
attribute wins over the document policy for that element's own request —
so `site/assets/video.js` grants the exception to this single iframe and
every other request on the site keeps sending nothing.

Two ways to get this wrong, both pinned below:

  * Dropping the attribute (or a rewrite of video.js that forgets it)
    silently restores error 153, and nothing else on the page changes.
  * "Fixing" it with `unsafe-url` or `no-referrer-when-downgrade` also
    works — and leaks the full page URL to YouTube on every play, which
    `site/privacy/index.html` promises does not happen.

Verified live, not only as a string match: pressing the real click-to-play
button in Chromium against a server sending the real `_headers` values sent
NO referer before this attribute and `https://<origin>/` after it — origin
only, with the page's own query string withheld. jsdom evaluates no
referrer policy at all, so that check cannot live in a component test; this
file pins the two files against each other, and the live check is recorded
in the PR that introduced it.

Same "two copies of one fact, checked rather than trusted" pattern as
tests/test_picture_study_csp.py and tests/test_compose_settings_passthrough.py.
"""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HEADERS = _REPO / "site" / "_headers"
_VIDEO = _REPO / "site" / "assets" / "video.js"

# Document-level policies under which a cross-origin request carries no
# `Referer` at all — i.e. those that break a YouTube embed on their own.
_STRIPPING_POLICIES = {"no-referrer", "same-origin"}

# Values that satisfy YouTube while sending only the origin. Anything else
# either withholds the referer (error 153 again) or sends the full URL.
_ORIGIN_ONLY_POLICIES = {
    "strict-origin",
    "strict-origin-when-cross-origin",
    "origin",
    "origin-when-cross-origin",
}


def _document_referrer_policy() -> str | None:
    """The policy a browser would actually apply.

    Deliberately not `(\\S+)$`: `Referrer-Policy` legally takes a
    comma-separated fallback list (`no-referrer, strict-origin-when-cross-origin`),
    and a browser uses the LAST token it recognises. A single-token regex
    returns nothing for that perfectly ordinary value — which would make
    every test below return early and pass green with the iframe's
    referrerpolicy deleted, i.e. the guard would go quiet at exactly the
    moment the Error 153 regression came back.
    """
    match = re.search(r"^\s+Referrer-Policy:\s*(.+?)\s*$", _HEADERS.read_text(), re.M)
    if not match:
        return None  # No header: the browser default already sends an origin.
    tokens = [t.strip() for t in match.group(1).split(",") if t.strip()]
    return tokens[-1] if tokens else None


def _iframe_referrer_policy() -> str | None:
    """Read off the iframe video.js actually builds, not a restated copy."""
    source = _VIDEO.read_text()
    iframe = re.search(r"<iframe\b.*?>", source, re.S)
    assert iframe, "no <iframe> found in video.js"
    match = re.search(r'referrerpolicy="([^"]+)"', iframe.group(0))
    return match.group(1) if match else None


def test_the_embed_overrides_the_domains_referrer_policy():
    """The regression itself: a stripping document policy with no override
    on the iframe is error 153, every time, for every visitor."""
    document = _document_referrer_policy()
    if document not in _STRIPPING_POLICIES:
        return  # A permissive domain policy already satisfies YouTube.
    assert _iframe_referrer_policy() is not None, (
        f"site/_headers sets Referrer-Policy: {document}, so the YouTube "
        f"iframe in site/assets/video.js gets no Referer and the player "
        f"shows 'Error 153 - Video player configuration error' instead of "
        f"the video. It needs its own referrerpolicy attribute."
    )


def test_the_override_actually_sends_something_youtube_accepts():
    """An override set to a stripping value is the same bug wearing the
    attribute that is supposed to fix it."""
    iframe = _iframe_referrer_policy()
    if iframe is None:
        return  # Covered by the test above.
    assert iframe not in _STRIPPING_POLICIES, (
        f"the iframe's referrerpolicy is {iframe}, which sends no Referer "
        f"cross-origin — the player will still show error 153."
    )


def test_the_override_sends_the_origin_and_not_the_page_url():
    """site/privacy/index.html tells visitors what pressing play sends.
    `unsafe-url` (or `no-referrer-when-downgrade`) would also clear
    error 153, and would hand YouTube the full URL including any query
    string, making that page's stated inventory wrong."""
    iframe = _iframe_referrer_policy()
    if iframe is None:
        return
    assert iframe in _ORIGIN_ONLY_POLICIES, (
        f"the iframe's referrerpolicy is {iframe}, which sends more than "
        f"the bare origin to YouTube. site/privacy/index.html states that "
        f"only the site's address is sent; keep them in agreement."
    )


def test_the_frame_src_still_permits_the_player():
    """Referrer aside, the CSP has to allow the frame at all — the other
    way this same video renders nothing. Checked against `frame-src`
    specifically, not against the policy string: the origin appearing in
    some other directive (a future script-src entry for YouTube's IFrame
    API, say) says nothing about whether the frame itself is allowed."""
    policy = re.search(r"Content-Security-Policy:\s*(.+)$", _HEADERS.read_text(), re.M)
    assert policy, "no Content-Security-Policy in site/_headers"
    frame_src = next(
        (
            part.strip()
            for part in policy.group(1).split(";")
            if part.strip().startswith("frame-src ")
        ),
        None,
    )
    assert frame_src, f"no frame-src directive in policy: {policy.group(1)}"
    src = re.search(r"src=\"(https://[^/\"]+)", _VIDEO.read_text())
    assert src, "no iframe src origin found in video.js"
    assert src.group(1) in frame_src, (
        f"site/_headers' frame-src does not permit {src.group(1)}, which "
        f"video.js embeds: {frame_src}"
    )
