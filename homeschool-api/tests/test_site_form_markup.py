"""
Two things about the static site's markup that fail silently in public.

**1. A form with no method degrades into a GET that publishes its answers.**
None of the four forms on this site has an `action`; `feedback-form.js`
intercepts submit and sends the answers itself. But the buttons are real
`type="submit"` buttons, so if that one script ever fails to load or parse —
a blocked request, a bad deploy, a syntax error — the browser performs a
NATIVE submit. Without `method`, that is a GET to the same static page, which
puts every answered field into the query string: name, email, and on the two
survey pages several paragraphs of free text, landing in browser history and
in any URL-logging intermediary between the visitor and Cloudflare. CSP's
`form-action 'self'` keeps it on this origin; it does not stop it being
written down. As a POST the same failure loses the answers instead of
publishing them, and every one of these forms already shows a mailto address
in its own note as the way to send them.

`type="submit"` is kept deliberately (Enter-to-submit, and the browser's own
`required` validation on the email field), which is exactly why the method
matters — the fallback path stays reachable by design.

**2. An HTML comment inside an opening tag is not a comment.**
This is not hypothetical: adding the comment explaining point 1 *inside* the
`<form ...>` tag is how this file came to exist. `-->` contains the `>` that
closes the tag, so the parser ends the element there and renders the
remaining attributes as body text — `method="post" data-category="cx" ...`
appeared as a visible line above the feedback form. Nothing errors, nothing
fails to build, and every automated check this repo had still passed; it is
only visible to someone looking at the page.

Both are static checks over the real files, no browser needed. The rendered
result was additionally confirmed in Chromium (every page's `innerText`
scanned for leaked attribute text, every form's `method` read from the DOM)
at the time this landed.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SITE = _REPO / "site"

_PAGES = sorted(_SITE.rglob("*.html"))

# Every opening tag, captured whole: `<` name, then attributes up to the
# first `>`. Comments and closing tags are excluded by the name pattern.
_OPEN_TAG = re.compile(r"<[a-zA-Z][a-zA-Z0-9-]*(?:\s[^>]*)?>", re.S)


def _pages_with_forms():
    return [p for p in _PAGES if "<form" in p.read_text()]


def test_the_site_still_has_the_forms_this_file_is_about():
    """A guard on the guard: if the forms move or are renamed, the test
    below would pass by vacuously finding nothing to check. Deliberately
    not a count — adding a fifth form page is ordinary work that the
    parametrized test already covers, and a hardcoded number would fail
    that change while proving nothing."""
    assert _pages_with_forms(), "no page under site/ contains a <form>"


@pytest.mark.parametrize(
    "page", _pages_with_forms(), ids=lambda p: str(p.relative_to(_SITE))
)
def test_every_form_posts_so_a_js_failure_cannot_put_answers_in_the_url(page):
    text = page.read_text()
    for tag in _OPEN_TAG.findall(text):
        if not tag.startswith("<form"):
            continue
        assert re.search(r'\bmethod\s*=\s*"post"', tag, re.I), (
            f"{page.relative_to(_SITE)} has a form with no method=\"post\". "
            f"If feedback-form.js fails to load, this form submits as a GET "
            f"and every answer lands in the query string and browser "
            f"history.\n  {tag[:120]}..."
        )


@pytest.mark.parametrize(
    "page", _PAGES, ids=lambda p: str(p.relative_to(_SITE))
)
def test_no_html_comment_is_opened_inside_a_tag(page):
    """`<form class="x" <!-- why --> method="post">` renders the attributes
    after the comment as visible page text. Checked over every page rather
    than only the ones with forms: the mistake is available anywhere, and
    it never announces itself."""
    text = page.read_text()
    for tag in _OPEN_TAG.findall(text):
        assert "<!--" not in tag, (
            f"{page.relative_to(_SITE)} opens an HTML comment inside a tag. "
            f"The `>` in `-->` closes the tag, so everything after it is "
            f"rendered as text on the page. Move the comment above the "
            f"element.\n  {tag[:160]}..."
        )
