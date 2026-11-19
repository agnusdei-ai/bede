"""The site's kindergarten-to-grade-2 practice copy is a claim about the product.

`site/homeschool/index.html` and `site/faq/index.html` tell a family what
Sound Time, Number Time and Map Practice are, when Bede offers them, what an
adult controls and what is kept. A static page is where such text goes stale
silently, so each claim is held against the code that decides it.

What is enforced is agreement between the copy and the code, never whether the
copy is persuasive. It also refuses the two ways this copy can overreach: naming
a practice area that is not built, and saying the product serves grades it does
not (it is kindergarten to grade 8).
"""
import html
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "homeschool-api"))

from models.schemas import Subject, SUBJECT_LABELS  # noqa: E402
from routers import k2_practice as k2_router  # noqa: E402
from services import ai_service  # noqa: E402
from services.k2_practice import AREA_SUBJECTS, ENABLED_AREAS  # noqa: E402

FAMILY = (ROOT / "site/homeschool/index.html").read_text()
FAQ = (ROOT / "site/faq/index.html").read_text()


def _text(markup: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup))).strip()


def _block(page: str, start: str, end: str) -> str:
    chunk = page[page.index(start):]
    return chunk[: chunk.index(end)]


EARLY_YEARS = _text(_block(FAMILY, '<section class="classical-section" id="early-years"', "</section>"))
PRACTICE_FAQ = _text(_block(FAQ, '<details id="early-years-practice"', "</details>"))
BOTH = EARLY_YEARS + " " + PRACTICE_FAQ


def test_the_copy_names_exactly_the_three_areas_that_are_built():
    # Phonics and math are the only enabled areas of the shared invitation;
    # map practice is the third, with its own tool.
    assert ENABLED_AREAS == {"phonics", "math"}
    for name in ("Sound Time", "Number Time", "Map Practice"):
        assert name in EARLY_YEARS and name in PRACTICE_FAQ, name


def test_the_copy_names_no_practice_area_that_is_not_built():
    # handwriting, spelling and copy-a-sentence are specified, not built.
    for unbuilt in ("handwriting", "spelling", "copy a sentence", "copying a sentence", "recitation"):
        assert unbuilt not in BOTH.lower(), f"the K-2 copy names {unbuilt!r}, which is not built"


def test_each_area_is_offered_in_the_subjects_the_copy_says():
    def label_list(subjects):
        return {SUBJECT_LABELS[s] for s in subjects}

    sound = PRACTICE_FAQ[PRACTICE_FAQ.index("Sound Time (phonics)"):]
    sound = sound[: sound.index("Number Time (math)")]
    for label in label_list(AREA_SUBJECTS["phonics"]):
        assert label in sound, label

    number = PRACTICE_FAQ[PRACTICE_FAQ.index("Number Time (math)"):]
    number = number[: number.index("Map Practice.")]
    for label in label_list(AREA_SUBJECTS["math"]):
        assert label in number, label

    maps = PRACTICE_FAQ[PRACTICE_FAQ.index("Map Practice."):]
    maps = maps[: maps.index("The shape of a round")]
    for label in label_list(ai_service._MAP_PRACTICE_SUBJECTS):
        assert label in maps, label


def test_the_recorded_answer_limit_is_the_one_in_the_code():
    assert k2_router.MAX_RECORDED_ANSWERS == 3
    assert "at most three answers" in PRACTICE_FAQ


def test_map_practice_has_no_parent_setting_as_the_faq_says():
    """The adult setting (`practice_offers`) governs Sound Time and Number
    Time. If map practice ever reads it, the FAQ's "no setting of its own"
    and the family page's wording must change with it."""
    assert "Map Practice has no setting of its own" in PRACTICE_FAQ
    assert "practice_offers" not in inspect.getsource(ai_service._map_practice_allowed)
    assert "Sound Time and Number Time" in EARLY_YEARS


def test_the_adult_setting_choices_are_the_ones_the_copy_lists():
    from models.schemas import SessionConfig

    default = SessionConfig.model_fields["practice_offers"].default
    assert default == "todays_subjects"
    assert "(the default)" in PRACTICE_FAQ
    # off, only approved sets, today's subjects: the three the copy lists.
    for choice in ("no practice", "only practice you approved", "today’s subjects too"):
        assert choice in PRACTICE_FAQ, choice


def test_the_copy_makes_no_score_or_placement_claim_it_cannot_keep():
    lowered = BOTH.lower()
    assert "no score" in lowered
    # Two right first tries can mark a phonics step secure, so the copy must
    # not promise that practice never does. It says what the record is not.
    assert "does not mark a skill secure" not in lowered
    assert "never mark" not in lowered
    assert "not a placement, a level, or a test result" in lowered


def test_the_copy_says_nothing_about_narration():
    """How a round is spoken is changing (docs/DECISIONS.md entry 46), so no
    page promises a voice. Every Number Time question works from the picture."""
    for word in ("spoken", "narrat", "voice", "aloud", "hear "):
        assert word not in BOTH.lower(), f"the K-2 copy mentions {word!r}"


def test_the_product_is_kindergarten_to_grade_8_never_k_12():
    for page in ("site/index.html", "site/homeschool/index.html", "site/faq/index.html",
                 "site/educators/index.html", "site/schools/index.html", "site/llms.txt"):
        text = (ROOT / page).read_text()
        assert not re.search(r"\bK[-–]?12\b", text), f"{page} says K-12; Bede serves kindergarten to grade 8"


def test_the_demo_claim_matches_the_demo():
    """The FAQ says Number Time is in the public demo for kindergarten, grade
    1 or grade 2. The demo's own button is shown only for those grades."""
    demo = (ROOT / "demo/src/App.tsx").read_text()
    assert "['K', '1', '2'].includes(grade)" in demo
    assert "setShowNumberTime(true)" in demo
    assert "kindergarten, grade 1, or grade 2" in PRACTICE_FAQ
    # and only Number Time: the demo has no phonics or map round.
    assert "Sound Time" not in demo and "Map Practice" not in demo


def test_the_site_links_resolve_to_the_new_detail():
    assert 'id="early-years-practice"' in FAQ
    for page in ("site/index.html", "site/homeschool/index.html"):
        assert "/faq/#early-years-practice" in (ROOT / page).read_text(), page
