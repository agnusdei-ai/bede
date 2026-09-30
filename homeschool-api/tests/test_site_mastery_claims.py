"""agnusdei.ai's "keeps a real record" claim names every area Bede records.

The home page tells a prospective family, in one sentence, which mastery
areas Bede actually keeps a record of. That sentence is a promise about
the product made on the page a family reads before they ever install it,
and it is prose: a new diagnostic engine ships, the sentence stays as it
was, and nothing anywhere errors. It had gone stale twice over by the time
this guard was written — `phonics` had been shipping for months and
`music_knowledge` had just landed, and the page named neither.

That is the same failure `docs/DECISIONS.md`'s own register guard and
`tests/test_catalog_coverage.py` exist for, and the one CLAUDE.md records
under "Carry Out the Decision, Don't Just Record It": the site said
"Eleven subjects" for three shipped subjects, because the decision to add
them stopped at the app.

`routers/diagnostic.py`'s `_SUMMARY_BUILDERS` is the source of truth for
WHICH areas exist — it is the dict that decides what
`GET /diagnostic/{student}/summary` will actually serve, so an area in it
IS an area a parent can open. The app's own `mastery.area*` labels are the
source of truth for WHAT EACH IS CALLED, which is the half a first draft of
this guard got wrong: it let the page say "composition" and "phonics" while
the Progress page a parent actually opens says "Writing" and "Reading
foundations". A marketing claim naming a thing the product does not call
that is a small lie of exactly the kind nobody notices, so the two are
pinned together rather than left to agree by habit.

The subject_area -> i18n key map is hand-written because it is a real
mapping and not a transformation ("literacy" -> "areaLiteracy" but
"language_exposure" -> "areaLanguage"). An area with no entry fails, which
is the point — adding an engine makes someone decide, in one line, what a
family is told it measures.
"""

import json
from pathlib import Path

import pytest

from routers.diagnostic import _SUMMARY_BUILDERS

REPO = Path(__file__).resolve().parents[2]
SITE_INDEX = REPO / "site" / "index.html"
EN_LOCALE = REPO / "homeschool-tutor" / "src" / "i18n" / "locales" / "en.json"

# subject_area -> the i18n key whose label the Progress page shows a parent.
AREA_LABEL_KEY = {
    "mathematics": "areaMathematics",
    "composition": "areaComposition",
    "phonics": "areaPhonics",
    "literacy": "areaLiteracy",
    "language_exposure": "areaLanguage",
    "music_knowledge": "areaMusic",
}


def _parent_facing_label(area: str) -> str:
    """What the Progress page calls this area, in the app's own words."""
    labels = json.loads(EN_LOCALE.read_text(encoding="utf-8"))["mastery"]
    key = AREA_LABEL_KEY[area]
    assert key in labels, f"en.json has no mastery.{key} for {area!r}"
    return labels[key]


def _record_claim() -> str:
    """The "Keeps a real record" bullet, or a failure that says so."""
    html = SITE_INDEX.read_text(encoding="utf-8")
    marker = "<strong>Keeps a real record.</strong>"
    assert marker in html, (
        "site/index.html no longer carries the 'Keeps a real record' bullet. "
        "If the claim moved, move this guard with it rather than deleting it: "
        "the point is that some page states which areas Bede records, and that "
        "the statement is checked against the code."
    )
    start = html.index(marker) + len(marker)
    end = html.index("</li>", start)
    return html[start:end]


def test_every_recorded_area_has_wording_for_a_parent():
    """A new engine must not reach production with nothing to call it."""
    missing = sorted(set(_SUMMARY_BUILDERS) - set(AREA_LABEL_KEY))
    assert not missing, (
        f"{missing} can be opened on the Progress page and this test does not "
        "know what to call them on the marketing site. Add the words a parent "
        "should read, then put them in site/index.html's record claim."
    )


def test_the_wording_map_has_not_outlived_its_areas():
    """The mirror of the above: a removed engine must not leave a claim behind."""
    stale = sorted(set(AREA_LABEL_KEY) - set(_SUMMARY_BUILDERS))
    assert not stale, (
        f"{stale} are named here but are no longer in _SUMMARY_BUILDERS. The "
        "site may be claiming a record Bede no longer keeps."
    )


@pytest.mark.parametrize("area", sorted(_SUMMARY_BUILDERS))
def test_the_site_names_this_area_in_the_words_the_app_uses(area):
    """Named at all, and named the way the Progress page names it.

    Compared case-insensitively and with the page's own HTML entity for an
    ampersand resolved: the label is Title Case in a card heading and runs
    lower-case mid-sentence in prose, which is ordinary English, not drift.
    """
    label = _parent_facing_label(area)
    claim = _record_claim().replace("&amp;", "&")
    assert label.lower() in claim.lower(), (
        f"site/index.html's 'Keeps a real record' bullet does not name "
        f"{area!r} as the app does ({label!r}). A family reading that sentence "
        "is being told less than Bede records, or told it under a name the "
        "Progress page never shows them."
    )


def test_ci_runs_this_guard_when_the_page_changes():
    """site/index.html is outside homeschool-api/, so the filter must name it.

    Asserted against the `grep -qE` line itself rather than the filename
    appearing anywhere in the workflow: an earlier version of the equivalent
    guard in test_decision_register.py passed on a comment beside the filter,
    which is a pass that checks nothing.
    """
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "test.yml"
    ).read_text(encoding="utf-8")
    filter_line = next(
        (line for line in workflow.splitlines() if "grep -qE" in line), None
    )
    assert filter_line is not None, "test.yml no longer has a grep -qE filter line"
    assert r"site/index\.html" in filter_line, (
        "site/index.html is not in test.yml's change filter, so editing the "
        "page alone computes relevant=false, skips api-tests, and never runs "
        "the guard written for exactly that change."
    )
