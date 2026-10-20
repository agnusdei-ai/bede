"""The curriculum cards' hover facts are claims about the product.

Each subject card on `site/index.html` unfolds three facts: how long a
session is, which grades it serves, and what is recorded. A static page is
where such a copy goes stale silently, so each one is checked against the
code that decides it.
"""
import html
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "homeschool-api"))
from models.schemas import SUBJECT_DURATIONS, SUBJECT_LABELS, Subject  # noqa: E402

SITE = (ROOT / "site/index.html").read_text()
CURRICULUM = SITE[SITE.index('<section class="curriculum band-curriculum">'):]
CURRICULUM = CURRICULUM[: CURRICULUM.index("</section>")]

# The five the learner's guarantee tracks, as the page's own lede names them.
GUARANTEE = {Subject.mathematics, Subject.language_arts, Subject.living_books, Subject.science, Subject.nature_study}
FAITH = {Subject.saints, Subject.scripture}
STAGE_GATED_FROM_GRADE_3 = {Subject.logic}


def _cards() -> dict[str, dict[str, str]]:
    out = {}
    for m in re.finditer(r'<li class="bede-curriculum-entry">\s*<h3>(.*?)</h3>.*?<ul class="subject-facts">(.*?)</ul>', CURRICULUM, re.S):
        facts = dict(re.findall(r'<span class="fact-k">(\w+)</span>\s*([^<]*)</li>', m.group(2)))
        out[html.unescape(m.group(1))] = {k: html.unescape(v).strip() for k, v in facts.items()}
    return out


CARDS = _cards()
BY_SUBJECT = {s: CARDS.get(SUBJECT_LABELS[s]) for s in Subject}


def test_every_subject_has_a_card_with_all_three_facts():
    assert len(CARDS) == len(Subject)
    for subject, facts in BY_SUBJECT.items():
        assert facts is not None, f"no card for {SUBJECT_LABELS[subject]}"
        assert set(facts) == {"Session", "Grades", "Record"}, SUBJECT_LABELS[subject]


@pytest.mark.parametrize("subject", list(Subject), ids=lambda s: s.value)
def test_session_length_is_the_planned_one(subject):
    assert BY_SUBJECT[subject]["Session"] == f"{SUBJECT_DURATIONS[subject]} minutes"


@pytest.mark.parametrize("subject", list(Subject), ids=lambda s: s.value)
def test_grades(subject):
    want = "3–8" if subject in STAGE_GATED_FROM_GRADE_3 else "K–8"
    assert BY_SUBJECT[subject]["Grades"] == want


def test_logic_is_really_gated_from_grade_3():
    """The card's '3–8' rests on SessionConfig dropping Logic for K-2."""
    from models.schemas import GradeStage, SessionConfig  # noqa: E402
    cfg = SessionConfig(student_name="A", grade="1", grade_stage=GradeStage.foundations, subjects=[Subject.logic, Subject.mathematics])
    assert Subject.logic not in cfg.subjects
    cfg = SessionConfig(student_name="A", grade="4", grade_stage=GradeStage.core_mastery, subjects=[Subject.logic, Subject.mathematics])
    assert Subject.logic in cfg.subjects


@pytest.mark.parametrize("subject", list(Subject), ids=lambda s: s.value)
def test_record_line_says_the_right_kind_of_thing(subject):
    line = BY_SUBJECT[subject]["Record"]
    tracked = "One of the five subjects tracked" in line
    assert tracked == (subject in GUARANTEE), f"{subject.value}: {line!r}"
    if subject in FAITH:
        assert "never scored" in line
    else:
        assert "never scored" not in line


def test_the_five_named_in_the_lede_are_the_five_marked_tracked():
    lede = re.search(r"The\s+five core subjects with tracked mastery outcomes are(.*?)\.\s*</p>", CURRICULUM, re.S).group(1)
    named = {s for s in Subject if html.unescape(SUBJECT_LABELS[s]) in html.unescape(re.sub(r"\s+", " ", lede))}
    assert named == GUARANTEE


def test_no_record_line_claims_a_score_for_a_child():
    for facts in CARDS.values():
        assert not re.search(r"\b(score[sd]?|grade[sd] the child|ranked)\b", facts["Record"].replace("never scored", ""), re.I)


def test_the_change_filter_covers_this_guard():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    line = next(l for l in workflow.splitlines() if "grep -qE" in l)
    alternatives = line.split("'")[1].strip("^()").split("|")
    assert r"site/index\.html" in alternatives and "homeschool-api/" in alternatives
