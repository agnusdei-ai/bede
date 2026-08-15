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


def test_object_src_is_named_rather_than_left_to_default_src():
    """`<object>`/`<embed>` are the one legacy class that can sidestep
    script-src in some engines, which is why strict-CSP guidance treats
    naming object-src as mandatory even where — as here — there is no
    upload path and no user-controlled same-origin content to point one
    at. Inheriting 'self' from default-src is not the same statement."""
    for pattern, headers in RULES:
        policy = headers.get("content-security-policy")
        if not policy:
            continue
        directives = [d.strip() for d in policy.split(";") if d.strip()]
        assert "object-src 'none'" in directives, (
            f"{pattern}'s policy does not set object-src 'none'."
        )


def test_the_opener_policy_is_set_and_not_paired_with_require_corp():
    """COOP costs nothing here (no window.open, no target="_blank" anywhere
    in site/) and closes opener-tampering ahead of the first link that
    needs it. COEP: require-corp is the trap that travels with it — it
    would break BOTH cross-origin things this deployment depends on, the
    youtube-nocookie iframe and the Wikimedia picture-study thumbnails, to
    buy an isolation nothing here uses."""
    for pattern, headers in RULES:
        if "content-security-policy" not in headers:
            continue  # not a security-policy-bearing rule
        assert headers.get("cross-origin-opener-policy") == "same-origin", (
            f"{pattern} does not set Cross-Origin-Opener-Policy: same-origin"
        )
        assert "require-corp" not in headers.get("cross-origin-embedder-policy", ""), (
            f"{pattern} sets COEP: require-corp, which blocks the YouTube "
            f"embed and the Wikimedia picture-study images."
        )


# ── Presence, not just consistency ───────────────────────────────────────
#
# Everything above asserts the file's policies do not CONFLICT. None of it
# asserts the headers are there at all, that a live deployment still applies
# them, or that they survive the build — so the whole set could go missing
# and this suite would stay green. That gap was found while investigating a
# report that the public site had lost its security headers.

_MIDDLEWARE = _REPO / "homeschool-api" / "core" / "middleware.py"
_BUILD_SCRIPT = _REPO / "scripts" / "build_pages_site.sh"
_WRANGLER = _REPO / "wrangler.jsonc"

# Set by SecurityHeadersMiddleware on every API response. Caching headers
# (Cache-Control, Pragma) are deliberately excluded: they are correct for an
# API and wrong for a static site that wants its assets cached.
_CACHING = {"cache-control", "pragma"}


def _headers_the_product_enforces():
    """Header names SecurityHeadersMiddleware actually assigns, read from the
    source rather than restated here — two copies of one fact is what this
    repo keeps getting bitten by."""
    body = _MIDDLEWARE.read_text().split("class SecurityHeadersMiddleware")[1]
    names = set(re.findall(r'h\["([A-Za-z-]+)"\]\s*=', body))
    assert names, "could not read any header assignments out of middleware.py"
    return {n.lower() for n in names} - _CACHING


def test_the_site_declares_every_security_header_the_product_enforces():
    """The marketing/demo surface must not be held to a lower bar than the
    self-hosted app, which is the promise site/_headers' own comment makes.
    Read from middleware.py so adding a header there fails here until the
    public site gets it too."""
    site_headers = {h for _, hs in RULES for h in hs}
    missing = sorted(_headers_the_product_enforces() - site_headers)
    assert not missing, (
        f"site/_headers is missing {missing}, which core/middleware.py's "
        f"SecurityHeadersMiddleware sets on every API response."
    )


def test_the_worker_config_keeps_the_headers_file_applicable():
    """The documented way to silently lose every one of these headers on a
    live deployment without touching site/_headers at all.

    Cloudflare applies `_headers` to STATIC ASSET responses only: "Custom
    headers defined in the _headers file are not applied to responses
    generated by your Worker code, even if the request URL matches a rule
    defined in _headers." So adding a `main` script, or setting
    `assets.run_worker_first`, moves responses out of the static-asset path
    and the entire header set stops being served — while this file's every
    other test still passes, because the file itself is untouched.

    https://developers.cloudflare.com/workers/static-assets/headers/
    """
    config = _WRANGLER.read_text()
    # Strip // comments so the prose above the config can discuss `main`.
    code = "\n".join(
        line for line in config.splitlines() if not line.strip().startswith("//")
    )
    assert '"main"' not in code, (
        "wrangler.jsonc now declares a `main` Worker script. Responses it "
        "generates do NOT get site/_headers applied — the security headers "
        "must be set inside that script instead, and this test updated to "
        "check them there."
    )
    assert "run_worker_first" not in code, (
        "assets.run_worker_first routes requests through Worker code first, "
        "which bypasses site/_headers entirely."
    )
    assert '"directory"' in code, "wrangler.jsonc no longer points at an assets directory"


def test_the_headers_file_survives_the_build_into_publish():
    """`_headers` only works if it lands in the deployed assets directory.
    The build assembles publish/ with a glob, and a glob is exactly the kind
    of thing that quietly stops matching a file whose name starts with an
    underscore if the copy is ever narrowed (`site/*.html`) or swapped for a
    tool with different defaults. Runs the real copy step rather than
    trusting it."""
    import subprocess
    import tempfile

    script = _BUILD_SCRIPT.read_text()
    copy_lines = [
        l.strip() for l in script.splitlines()
        if l.strip().startswith("cp ") and "site/" in l and "publish/" in l
    ]
    assert copy_lines, (
        "could not find the step that copies site/ into publish/ in "
        "build_pages_site.sh — if the build changed, update this test."
    )

    with tempfile.TemporaryDirectory() as tmp:
        publish = Path(tmp) / "publish"
        publish.mkdir()
        for line in copy_lines:
            subprocess.run(
                line.replace("publish/", f"{publish}/"),
                shell=True, cwd=_REPO, check=True,
            )
        assert (publish / "_headers").is_file(), (
            f"site/_headers did not reach publish/ via {copy_lines!r}. "
            f"The deployed site would serve no security headers at all."
        )


@pytest.mark.parametrize("path", ["site/_headers", r"wrangler\.jsonc"])
def test_ci_runs_this_suite_when_the_files_it_guards_change(path):
    """Every test in this file reads something outside homeschool-api/, and
    test.yml's change filter decides whether this suite runs at all. It is a
    PR-only skip, so a change touching ONLY site/_headers — deleting
    Strict-Transport-Security, say — or only wrangler.jsonc — adding a `main`
    script, which stops _headers being applied at all — would compute
    relevant=false and never run the guard written for exactly that edit.

    Asserted against the `grep -qE` line itself rather than the filename
    appearing anywhere in the workflow: an earlier version of the equivalent
    guard in test_decision_register.py passed on a comment beside the filter,
    which is the vacuous pass this repo keeps rediscovering."""
    workflow = (_REPO / ".github" / "workflows" / "test.yml").read_text()
    filter_line = next(
        (l for l in workflow.splitlines() if "grep -qE" in l), None
    )
    assert filter_line, "test.yml no longer has a grep -qE change-filter line"
    assert path in filter_line, (
        f"{path} is not in test.yml's change filter, so a change touching "
        f"only that file skips this entire suite."
    )
