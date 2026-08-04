"""
`site/_headers` carries the security headers for the public deployment
(marketing site at the root, the demo under /bede/). It arrived on main with
no test at all, one day after the mutation audit in docs/GUARD_AUDIT.md found
that the API's own CSP could be changed to `frame-ancestors *` — removing
clickjacking protection outright — with every test still green, because the
only assertion was that the header was *present*.

Same standard applies here, and one more besides: the file's own comment says
it "mirrors, as closely as a static file allows, the header set the actual
product already enforces" in `core/middleware.py` and
`homeschool-tutor/nginx.conf`. That makes it a third copy of one security
posture with nothing checking the three agree — the drift CLAUDE.md's standing
rule says to pin rather than trust someone to remember.

A static file cannot be probed by mutation the way running code can, so these
assert its content directly.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_HEADERS = REPO_ROOT / "site" / "_headers"

# The one place a wildcard is legitimate, with the reason. The demo's backend
# subdomain is set per-deployment by VITE_DEMO_API_BASE and cannot be pinned in
# this repo, so it is scoped to Render rather than opened up. Anything else
# wildcarded is a finding.
ALLOWED_WILDCARDS = {("/bede/*", "connect-src"): "https://*.onrender.com"}

# Third-party origins the site is allowed to frame, and why. The home page has
# a click-to-play YouTube embed; nothing else may be framed.
ALLOWED_FRAME_SRC = {"https://www.youtube-nocookie.com"}


def _blocks() -> dict[str, dict[str, str]]:
    """Parse _headers into {path_pattern: {header_name: value}}."""
    blocks: dict[str, dict[str, str]] = {}
    current = None
    for raw in SITE_HEADERS.read_text().splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")):
            current = line.strip()
            blocks[current] = {}
        elif current is not None:
            name, _, value = line.strip().partition(":")
            blocks[current][name.strip()] = value.strip()
    return blocks


def _csp(value: str) -> dict[str, str]:
    out = {}
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, val = part.partition(" ")
        out[name] = val.strip()
    return out


ALL_PATHS = ["/*", "/bede/*"]


def test_both_path_blocks_exist():
    blocks = _blocks()
    for path in ALL_PATHS:
        assert path in blocks, f"{path} block missing from site/_headers"


@pytest.mark.parametrize("path", ALL_PATHS)
def test_every_block_denies_framing_outright(path):
    """The assertion the API's CSP was missing. 'none' is the whole point —
    anything else lets some origin frame the site or a live demo session."""
    csp = _csp(_blocks()[path]["Content-Security-Policy"])
    assert csp.get("frame-ancestors") == "'none'"


@pytest.mark.parametrize("path", ALL_PATHS)
def test_every_block_confines_the_directives_that_matter_to_self(path):
    csp = _csp(_blocks()[path]["Content-Security-Policy"])
    for name in ("default-src", "script-src", "base-uri", "form-action"):
        assert csp.get(name) == "'self'", (
            f"{path}: CSP {name} is {csp.get(name)!r}, not 'self'"
        )


@pytest.mark.parametrize("path", ALL_PATHS)
def test_no_unsafe_eval_and_unsafe_inline_only_for_styles(path):
    """unsafe-inline is deliberately allowed for style-src (Tailwind). Anywhere
    else, and unsafe-eval anywhere at all, is a loosening that must be
    deliberate rather than accidental."""
    for name, value in _csp(_blocks()[path]["Content-Security-Policy"]).items():
        assert "unsafe-eval" not in value, f"{path}: CSP {name} permits unsafe-eval"
        if name != "style-src":
            assert "unsafe-inline" not in value, f"{path}: CSP {name} permits unsafe-inline"


@pytest.mark.parametrize("path", ALL_PATHS)
def test_wildcards_only_where_documented(path):
    """A single '*' undoes whichever directive it appears in. One is
    legitimate (see ALLOWED_WILDCARDS); a second must not slip in unnoticed."""
    for name, value in _csp(_blocks()[path]["Content-Security-Policy"]).items():
        if "*" not in value:
            continue
        expected = ALLOWED_WILDCARDS.get((path, name))
        assert expected is not None, (
            f"{path}: CSP {name} contains an undocumented wildcard: {value!r}"
        )
        assert value == f"'self' {expected}" or value == expected, (
            f"{path}: CSP {name} wildcard widened from {expected!r} to {value!r}"
        )


def test_only_the_youtube_embed_may_be_framed():
    csp = _csp(_blocks()["/*"]["Content-Security-Policy"])
    frame_src = csp.get("frame-src")
    if frame_src is None:
        return  # framing nothing is stricter, and fine
    assert set(frame_src.split()) <= ALLOWED_FRAME_SRC, (
        f"frame-src permits more than the click-to-play embed: {frame_src!r}"
    )


@pytest.mark.parametrize("path", ALL_PATHS)
def test_the_non_csp_headers_are_present_and_strict(path):
    headers = _blocks()[path] if path == "/*" else {**_blocks()["/*"], **_blocks()[path]}
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "max-age=" in headers["Strict-Transport-Security"]


def test_the_microphone_is_granted_only_to_the_demo():
    """The one Permissions-Policy difference between the two blocks, and it is
    load-bearing: the marketing pages must never be able to open a mic."""
    blocks = _blocks()
    assert "microphone=()" in blocks["/*"]["Permissions-Policy"]
    assert "microphone=(self)" in blocks["/bede/*"]["Permissions-Policy"]


def test_the_site_csp_agrees_with_the_api_on_framing():
    """The mirror claim in this file's own comment, checked rather than
    trusted. If SecurityHeadersMiddleware's framing policy is ever relaxed,
    this fails alongside it rather than leaving the static copy silently
    stricter or looser than the product."""
    from core.middleware import SecurityHeadersMiddleware

    api_csp = _csp(SecurityHeadersMiddleware._CSP)
    for path in ALL_PATHS:
        site_csp = _csp(_blocks()[path]["Content-Security-Policy"])
        assert site_csp["frame-ancestors"] == api_csp["frame-ancestors"], (
            f"{path} and core/middleware.py disagree on frame-ancestors"
        )


def test_the_header_comment_names_the_canonical_domain():
    """agnusdei.ai became canonical in #377/#378; this file's own comment still
    described the deployment as agnusdei.io. Cheap to pin, and exactly the
    class of drift that survives a clean merge."""
    text = SITE_HEADERS.read_text()
    assert "agnusdei.ai" in text
