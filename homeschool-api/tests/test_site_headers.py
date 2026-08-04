"""
site/_headers must not deliver two conflicting policies to one path.

This file exists because the original version of site/_headers did exactly
that and took the public demo offline. It had a general `/*` block and a
narrower `/bede/*` block that "overrode" connect-src so the demo could reach
its Render backend:

    /*        connect-src 'self'
    /bede/*   connect-src 'self' https://*.onrender.com

Both patterns match `/bede/`. When a browser receives more than one
Content-Security-Policy it enforces ALL of them — a resource must be allowed
by every policy delivered — so the effective rule is the INTERSECTION, and
that is plain `'self'`. The narrower block could not widen anything. The
demo's fetch was refused in the browser and never sent: Render's logs showed
only /health probes, and the demo showed its generic "Could not reach the
server" message, which fires on the bare TypeError a blocked fetch produces.

The bug was invisible to the check that was supposed to catch it. A local
harness simulated Cloudflare's `_headers` handling, initially emitted both
headers (the real risk), and was then "fixed" to merge them into one —
encoding an assumption about Cloudflare's precedence rather than testing the
danger. The test was changed to match the belief.

So this file asserts the property that holds regardless of what Cloudflare
does with overlapping rules: no path is matched by two blocks that both set
the same security-critical header. That is what makes the file safe under
either behaviour, without needing to know which one is real — and the
sandbox cannot reach the deployment to find out.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_HEADERS_FILE = _REPO / "site" / "_headers"

# Headers where two overlapping declarations change what the browser
# actually enforces, rather than being cosmetic.
_CONFLICT_SENSITIVE = {
    "content-security-policy",
    "permissions-policy",
}


def _parse(text):
    """Return [(path_pattern, {header_name_lower: value})] in file order."""
    rules = []
    pattern, headers = None, {}
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if not raw[:1].isspace():
            if pattern is not None:
                rules.append((pattern, headers))
            pattern, headers = raw.strip(), {}
        elif ":" in raw:
            name, _, value = raw.strip().partition(":")
            headers[name.strip().lower()] = value.strip()
    if pattern is not None:
        rules.append((pattern, headers))
    return rules


def _matches(pattern, path):
    """Cloudflare _headers globbing, narrowed to the forms this file uses."""
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), path) is not None


RULES = _parse(_HEADERS_FILE.read_text())

# Paths that must each resolve to exactly one policy. `/bede/` is the one
# that actually broke; the others guard the marketing pages and the assets
# the demo loads.
_PATHS = [
    "/",
    "/faq/",
    "/feedback/",
    "/privacy/",
    "/bede/",
    "/bede/index.html",
    "/bede/assets/index-abc123.js",
    "/assets/site.css",
]


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("header", sorted(_CONFLICT_SENSITIVE))
def test_no_path_receives_two_declarations_of_a_conflict_sensitive_header(path, header):
    """The regression itself.

    Not "the /bede/ policy is correct" — the old file's /bede/ policy was
    correct in isolation and still produced a broken site, because a second
    policy was delivered alongside it. The property that matters is that
    only one is delivered at all.
    """
    setters = [p for p, h in RULES if header in h and _matches(p, path)]
    assert len(setters) <= 1, (
        f"{path} is matched by {len(setters)} blocks that each set "
        f"{header}: {setters}. A browser enforces every policy it receives, "
        f"so the effective result is their INTERSECTION — a later block can "
        f"never widen an earlier one, only narrow it. This is the exact "
        f"shape that blocked the demo's API call and took it offline."
    )


def test_the_demo_backend_is_reachable_under_the_policy_that_actually_applies():
    """Guards the specific allowance whose absence broke the demo.

    Asserted against the intersection of every matching policy rather than
    against one block's text, so it stays true no matter how the file is
    later restructured.
    """
    policies = [
        h["content-security-policy"]
        for p, h in RULES
        if "content-security-policy" in h and _matches(p, "/bede/")
    ]
    assert policies, "no CSP applies to /bede/"

    for policy in policies:
        directives = dict(
            (d.strip().split(None, 1) + [""])[:2]
            for d in policy.split(";")
            if d.strip()
        )
        connect = directives.get("connect-src", "")
        assert "onrender.com" in connect, (
            "A CSP applying to /bede/ omits the demo's Render backend from "
            f"connect-src ({connect!r}). Every delivered policy must allow "
            "it — one that does not will block the request no matter what "
            "the others permit."
        )
        # blob: is how the demo hands recorded microphone audio to the
        # player and the upload; without it, voice input fails the same
        # silent way the API call did.
        media = directives.get("media-src", "")
        assert "blob:" in media, "media-src must allow blob: for voice"
        # data: is the iOS audio unlock, and it is the one most likely to
        # be dropped as "obviously unnecessary". useTextToSpeech.ts plays a
        # tiny silent WAV as a data: URI on a user gesture, which is what
        # blesses the shared <audio> element so Bede can speak later without
        # one. Block it and Bede is simply mute on iPad — silently, with no
        # error a parent could report usefully. Caught by
        # scripts/synthetic_journey.mjs against a policy that had shipped.
        assert "data:" in media, (
            "media-src must allow data: — it is the iOS audio-unlock path "
            "(useTextToSpeech.ts's SILENT_WAV_DATA_URI). Without it Bede "
            "goes mute on iPad."
        )


def test_no_unsafe_inline_script_crept_back_in():
    """The reason the inline <script> blocks were extracted to files in the
    first place. Re-adding 'unsafe-inline' to script-src would make that
    work pointless and is the easiest way to "fix" a CSP error wrongly."""
    for pattern, headers in RULES:
        policy = headers.get("content-security-policy")
        if not policy:
            continue
        script_src = next(
            (d for d in policy.split(";") if d.strip().startswith("script-src")), ""
        )
        assert "unsafe-inline" not in script_src, (
            f"{pattern} allows 'unsafe-inline' in script-src. Extract the "
            f"inline script to a file under site/assets/ instead."
        )
