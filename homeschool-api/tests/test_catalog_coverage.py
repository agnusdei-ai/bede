"""
Catalog coverage: every teachable subject must give Bede something
year-specific, in every year.

The gap this pins closed: `_get_catalog_context` routed four subjects to
`get_subject_plan` and everything else to `get_catalog_note` (book
entries). A subject with no books for a given year therefore got NOTHING
year-specific — only the grade-agnostic `_SUBJECT_CONTEXT` blurb. Measured
before the fix:

    scripture      0 books in ALL 8 years   (added as a subject in #317)
    science        0 books in years 1, 2, 8
    nature_study   0 books in year 8
    saints         0 books in year 8

`free_study` is deliberately excluded from every assertion here: it is
child-directed exploration by design, and prescribing a scope for it would
contradict the point of the subject.
"""

import json
import pathlib

import pytest

from models.schemas import Subject
from services.catalog_service import get_catalog_note, get_subject_plan

CATALOG_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "catalog"
YEARS = list(range(1, 9))

# Subjects that route to get_subject_plan unconditionally in
# _get_catalog_context — they never had book lists.
PLAN_ONLY = {"mathematics", "art_music", "language_arts", "morning_time"}

# Deliberately open-ended — see this module's docstring.
EXCLUDED = {"free_study"}

# Years 1-2 map to grades K-2 (see _infer_year in services/ai_service.py),
# and Logic is deliberately not a K-2 subject — formal reasoning before the
# Logic stage is the premature abstraction classical education warns
# against. So `logic` is expected to have NO plan in those two years and a
# plan in every year from 3 on, which is asserted directly below rather
# than waived.
STAGE_GATED = {"logic": {1, 2}}

COVERED_SUBJECTS = sorted({s.value for s in Subject} - EXCLUDED)


def _catalog(year: int) -> dict:
    return json.loads((CATALOG_DIR / f"year{year}.json").read_text())


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("subject", COVERED_SUBJECTS)
def test_every_subject_has_year_specific_content(year, subject):
    """
    The real contract: for any (year, subject) a family can actually land
    on, Bede gets either a book list or a plan — never nothing.
    """
    if year in STAGE_GATED.get(subject, set()):
        pytest.skip(f"{subject} is deliberately not taught in year {year} — see STAGE_GATED")
    note = get_catalog_note(year, subject)
    plan = get_subject_plan(year, subject)
    assert note or plan, (
        f"Year {year} / {subject} has neither catalog books nor a subject plan — "
        f"Bede would fall back to grade-agnostic guidance only."
    )


@pytest.mark.parametrize("year", sorted(STAGE_GATED["logic"]))
def test_logic_is_absent_from_the_k2_years(year):
    """
    The gate, asserted rather than assumed. A logic plan appearing in Year
    1 or 2 would mean a K-2 child could be taught formal reasoning, which
    three separate mechanisms exist to prevent (SessionConfig.
    _validate_logic_stage, the UI's subject list, and logic_catalog.
    logic_note returning "" for that stage). This is the fourth, and the
    one that fails loudest in CI.
    """
    assert not get_subject_plan(year, "logic"), (
        f"Year {year} gained a logic plan — Logic is deliberately a 3-8 subject."
    )


@pytest.mark.parametrize("year", [3, 4, 5, 6, 7, 8])
def test_logic_plan_states_the_charity_guardrail(year):
    """
    The guardrail that matters most in this subject travels with the
    content, exactly as scripture's neutrality and the classical
    languages' inclusivity guarantees do. A child newly able to name a
    fallacy has been handed a weapon, and the obvious first target is
    their own parents.
    """
    lowered = get_subject_plan(year, "logic").lower()
    assert "never winning" in lowered or "never for winning" in lowered, (
        f"Year {year} logic plan does not state that logic serves truth, not winning"
    )
    assert "parents" in lowered, (
        f"Year {year} logic plan does not protect the parents' own authority"
    )
    assert "never invent" in lowered, (
        f"Year {year} logic plan does not carry the no-improvised-arguments rule"
    )


@pytest.mark.parametrize("year", YEARS)
def test_scripture_has_a_plan_in_every_year(year):
    """
    scripture shipped in #317 with no catalog content in any year at all —
    the single largest gap. It is plan-based rather than book-based on
    purpose: naming a canonical reading list would take a denominational
    side, which this subject exists specifically to avoid.
    """
    assert get_subject_plan(year, "scripture"), f"Year {year} scripture plan missing"


@pytest.mark.parametrize("year", YEARS)
def test_scripture_plan_states_the_neutrality_guarantee(year):
    """
    Every scripture plan must carry the canon/translation neutrality note.
    This is the subject's whole reason for existing separately from
    `saints` (which IS explicitly Catholic, via Faith and Life), so it
    cannot be left to a single shared prompt line that a future edit might
    drop — it travels with the content itself.
    """
    plan = get_subject_plan(year, "scripture")
    lowered = plan.lower()
    assert "canon" in lowered, f"Year {year} scripture plan does not mention canon"
    assert "translation" in lowered, f"Year {year} scripture plan does not mention translation"
    # Must defer denomination-specific doctrine to the family's own clergy.
    assert any(w in lowered for w in ("pastor", "priest", "minister")), (
        f"Year {year} scripture plan does not defer doctrine to the family's own clergy"
    )


@pytest.mark.parametrize("year", YEARS)
def test_plans_never_shadow_a_year_that_has_books(year):
    """
    A plan for a subject that also has books in that year would be dead
    code — `_get_catalog_context` prefers the book note and never reaches
    the plan. Catching it here keeps the catalog honest about which
    mechanism is actually feeding each subject.
    """
    data = _catalog(year)
    book_subjects = {b.get("subject") for b in data["books"]}
    for subject in data["subject_plans"]:
        if subject in PLAN_ONLY:
            continue
        assert subject not in book_subjects, (
            f"Year {year}: '{subject}' has BOTH books and a plan — the plan is unreachable."
        )


@pytest.mark.parametrize("year", YEARS)
def test_authored_plans_are_not_attributed_to_mater_amabilis(year):
    """
    `get_catalog_note` labels book listings "Mater Amabilis Year N" because
    those entries come from that published curriculum. The plans added for
    the gaps above are written for this project, so they must never claim
    that provenance — presenting our own scope note to a parent as though a
    real third-party curriculum published it is a factual misattribution.

    The four PLAN_ONLY subjects predate this rule and do reference the
    approach by name, so they are exempt.
    """
    data = _catalog(year)
    for subject, plan in data["subject_plans"].items():
        if subject in PLAN_ONLY:
            continue
        assert "mater amabilis" not in plan.lower(), (
            f"Year {year} '{subject}' plan attributes itself to Mater Amabilis"
        )


@pytest.mark.parametrize("year", YEARS)
def test_plans_are_substantive(year):
    """
    A stub plan is worse than none — it looks like coverage and isn't.

    The floor is 150 rather than something higher because Morning Time is
    deliberately the shortest plan in the catalog (its Year 2 entry is 173
    characters): the subject is a few brief warm elements, and padding its
    scope note to match Mathematics' would misrepresent how it's meant to
    be taught. 150 still catches an actual stub.
    """
    for subject, plan in _catalog(year)["subject_plans"].items():
        assert len(plan) > 150, f"Year {year} '{subject}' plan is too thin to guide a session"


def test_free_study_is_deliberately_uncovered():
    """
    Guards the exclusion itself. If someone later adds a free_study plan,
    this fails loudly and forces the design decision to be made on purpose
    rather than by drift.
    """
    for year in YEARS:
        assert not get_subject_plan(year, "free_study"), (
            f"Year {year} gained a free_study plan — free_study is child-directed "
            f"by design; prescribing a scope contradicts the subject."
        )


# Both classical-language subjects are plan-based for the same reason
# `scripture` is: they have no book list, and naming one publisher's primer
# as canonical would be a curriculum endorsement this project has no basis
# to make.
CLASSICAL_LANGUAGES = ["latin", "greek"]


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("language", CLASSICAL_LANGUAGES)
def test_classical_language_has_a_plan_in_every_year(year, language):
    assert get_subject_plan(year, language), f"Year {year} {language} plan missing"


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("language", CLASSICAL_LANGUAGES)
def test_classical_language_plan_states_the_inclusivity_guarantee(year, language):
    """
    The guarantee that makes these subjects teachable by a family of any
    Christian tradition travels with the content, exactly as scripture's
    canon/translation neutrality does above — not only in the catalog
    module's prompt block, which a future edit could soften independently.
    """
    plan = get_subject_plan(year, language)
    lowered = plan.lower()
    assert "shared inheritance" in lowered, (
        f"Year {year} {language} plan does not state that its content is shared across traditions"
    )
    assert any(w in lowered for w in ("pastor", "priest", "minister")), (
        f"Year {year} {language} plan does not defer dividing doctrine to the family's own clergy"
    )
    assert "never recited from memory" in lowered, (
        f"Year {year} {language} plan does not carry the quote-never-recall rule"
    )


@pytest.mark.parametrize("year", YEARS)
def test_greek_plan_refuses_to_pick_a_manuscript_tradition(year):
    """
    Specific to Greek: the Textus Receptus / critical-text divide is live
    and denominationally charged in a way the Vulgate's edition variants
    are not. Every year's plan must say the subject takes no side.
    """
    lowered = get_subject_plan(year, "greek").lower()
    assert "manuscript tradition" in lowered, (
        f"Year {year} greek plan does not address the manuscript question"
    )


@pytest.mark.parametrize("year", YEARS)
def test_latin_has_a_plan_in_every_year(year):
    """
    Latin & Christian Foundations is plan-based for the same reason
    `scripture` is: it has no book list, and inventing one would mean
    picking a publisher's Latin primer as canonical.
    """
    assert get_subject_plan(year, "latin"), f"Year {year} latin plan missing"


@pytest.mark.parametrize("year", YEARS)
def test_latin_plan_states_the_inclusivity_guarantee(year):
    """
    The guarantee that makes this subject teachable by a family of any
    Christian tradition has to travel with the content, exactly as
    scripture's canon/translation neutrality does above — not live only in
    services/latin_catalog.py's prompt block, which a future edit could
    soften independently of these plans.
    """
    plan = get_subject_plan(year, "latin")
    lowered = plan.lower()
    assert "shared inheritance" in lowered, (
        f"Year {year} latin plan does not state that its content is shared across traditions"
    )
    assert any(w in lowered for w in ("pastor", "priest", "minister")), (
        f"Year {year} latin plan does not defer dividing doctrine to the family's own clergy"
    )
    # And the verbatim rule, which is what keeps Bede from inventing Latin.
    assert "never recited from memory" in lowered, (
        f"Year {year} latin plan does not carry the quote-never-recall rule"
    )
