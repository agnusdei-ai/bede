"""Validate beta-survey category integrity without inventing public submission forms.

The active Bede website is inquiry-only. /survey/ and /educators/ must not
expose form fields or a POST workflow; interviews use explicit email links.
The in-app survey remains an authorized POST /feedback client and must use
the category accepted by the API and rendered by the email service.

If public survey forms are restored later, update the offer and tests
together rather than adding unused data-category attributes to static pages.
"""
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.schemas import FeedbackRequest
from services.email_service import _CATEGORY_LABELS, _feedback_prefix

REPO_ROOT = Path(__file__).resolve().parents[2]
SURVEY_CATEGORY = "beta_survey"

# Former survey pages: currently inquiry-only, not active submission channels.
HOSTED_PAGES = [
    REPO_ROOT / "site" / "survey" / "index.html",
    REPO_ROOT / "site" / "educators" / "index.html",
]
IN_APP_MODAL = REPO_ROOT / "homeschool-tutor" / "src" / "components" / "BetaSurveyModal.tsx"


def test_the_survey_category_is_accepted():
    req = FeedbackRequest(category=SURVEY_CATEGORY, message="answers")
    assert req.category == SURVEY_CATEGORY


def test_an_unknown_category_is_still_rejected():
    """The Literal is the guard the channels below are checked against, so
    it has to actually reject something for that check to mean anything."""
    with pytest.raises(ValidationError):
        FeedbackRequest(category="beta-survey", message="answers")


def test_the_survey_gets_its_own_subject_line():
    """A whole instrument reads oddly filed under "beta feedback" alongside
    one-line remarks, which is the same reasoning "plans" and "onboarding"
    already have their own prefixes for."""
    assert _feedback_prefix(SURVEY_CATEGORY) == "Bede beta survey"
    assert _feedback_prefix(SURVEY_CATEGORY) != _feedback_prefix("cx")


def test_the_survey_has_a_readable_label_in_the_email_body():
    """_CATEGORY_LABELS falls back to the raw category string, so a missing
    row here degrades to "beta_survey" in the email rather than erroring."""
    assert SURVEY_CATEGORY in _CATEGORY_LABELS
    assert _CATEGORY_LABELS[SURVEY_CATEGORY] != SURVEY_CATEGORY


@pytest.mark.parametrize("page", HOSTED_PAGES, ids=lambda p: p.parent.name)
def test_public_survey_pages_are_inquiry_only(page):
    """Fail if a hosted survey silently reappears without authorization.

    Do not add dummy data-category attributes to make an obsolete test pass.
    No learner or family responses should be collected by these public pages.
    """
    assert page.exists(), f"{page} is missing"
    html = page.read_text(encoding="utf-8")
    assert not re.search(r"<form\\b", html, re.IGNORECASE), (
        f"{page} must remain inquiry-only; public survey form found"
    )
    assert not re.search(r"\\bdata-category\\s*=", html), (
        f"{page} declares an unused feedback submission category"
    )
    assert not re.search(
        r'<script[^>]+src=["\\\']/assets/feedback-form\\.js', html, re.IGNORECASE
    ), f"{page} must not load the public feedback form submission script"
    assert "mailto:info@agnusdei.ai?" in html, (
        f"{page} needs a working inquiry contact"
    )


def test_the_in_app_prompt_posts_the_accepted_survey_category():
    """Pooling only works if all three agree. The modal calls
    submitFeedback(token, '<category>', ...), so the string is a literal in
    that file and can be read out of it directly."""
    assert IN_APP_MODAL.exists(), f"{IN_APP_MODAL} is missing"
    source = IN_APP_MODAL.read_text(encoding="utf-8")
    assert f"'{SURVEY_CATEGORY}'" in source


def test_the_survey_never_asks_about_a_childs_faith():
    """The constitution's faith dimension is governed qualitatively, by
    rule, and never measured or scored (CLAUDE.md's standing rule). A
    survey is not exempt: asking a parent to rate their child's spiritual
    engagement would be that metric, collected by hand.

    Asking whether the faith *modules* fit a family's tradition is a
    question about our software and stays allowed, which is why this looks
    for the scoring vocabulary rather than for the word "faith".
    """
    forbidden = re.compile(
        r"(faith|spiritual|prayer|devotion)\w*[^.?]{0,60}"
        r"(score|scored|rating|rate|measure|progress|growth|level|engagement)",
        re.IGNORECASE,
    )
    for page in HOSTED_PAGES + [IN_APP_MODAL]:
        text = page.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{page} appears to score a child's faith"
