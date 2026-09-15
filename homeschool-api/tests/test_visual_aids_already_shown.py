"""
Real check for _get_visual_aids_context's "already shown this session"
marking — the deeper cause behind repeated Art & Music images surviving
the earlier history-amnesia fix (getApiMessages/toApiMessage folding
visual-aid mentions back into conversation history). That fix gave Bede
textual memory that it showed a picture, but _get_visual_aids_context
itself listed the same catalog identically on every single turn with no
indication of what had already been used — a soft signal (one line of
prose to infer from) rather than a hard one, which matters a lot more
against a catalog this small.

_get_visual_aids_context also requires a SessionConfig to determine which
single artist's works are in scope — and since the grade+term rotation
(_term_rotation_index), WHICH artist depends on the grade as well as the
term: grade K walks _TERM_ARTISTS from entry 0 exactly as every grade
used to, so the tests below pin grade "K" wherever they need a specific
artist by name, and pin a fixed `today` wherever they need a specific
week's pick (the featured picture rotates on the ISO calendar week, the
same clock the composer/poetry/prayer catalogs use).

The "already shown" tests use quarterly term 4 at grade K, which is
Raphael: seven catalog entries, so "one shown, one not" and "two shown,
one not" both have something to assert against.
"""
from datetime import date, timedelta

from models.schemas import VALID_GRADES, ChatMessage, GradeStage, SessionConfig, Subject, TermSchedule
from services.ai_service import (
    _TERM_ARTISTS,
    _THIS_WEEK_MARK,
    _get_visual_aids_context,
    _term_artist,
)
from services.catalog_service import get_visual_aids

# A Tuesday; ISO week 2. Any fixed date works — what matters is that a
# test asserting a specific week's pick is not at the mercy of the day
# it runs on.
_TODAY = date(2026, 1, 6)


def _config(**overrides) -> SessionConfig:
    defaults = dict(
        student_name="Emma", grade="K", grade_stage=GradeStage.foundations,
        term_schedule=TermSchedule.quarterly, current_term=4,
    )
    defaults.update(overrides)
    return SessionConfig(**defaults)


def _ctx(config: SessionConfig | None = None, history=None, today: date = _TODAY, subject=Subject.art_music) -> str:
    return _get_visual_aids_context(subject, config or _config(), history, today=today)


def _ids_in(text: str) -> list[str]:
    return [line.split(":")[0][2:] for line in text.splitlines() if line.startswith("- ")]


# ── Already-shown marking (between turns) ────────────────────────────────

def test_no_history_lists_every_aid_with_no_marker():
    text = _ctx()
    assert "raphael_school_of_athens" in text
    assert "raphael_sistine_madonna" in text
    assert "ALREADY SHOWN" not in text


def test_a_shown_aid_gets_marked_and_others_do_not():
    history = [
        ChatMessage(role="assistant", content="Here it is properly: [Showed a picture: \"The School of Athens\" by Raphael (1511)]"),
        ChatMessage(role="user", content="I see the picture"),
    ]
    text = _ctx(history=history)
    assert "raphael_school_of_athens: \"The School of Athens\" (Raphael) — " in text
    # The marked line specifically
    marked_line = next(line for line in text.splitlines() if "raphael_school_of_athens" in line)
    assert "[ALREADY SHOWN this session]" in marked_line
    # A different aid (same artist, different painting) must NOT be marked
    unmarked_line = next(line for line in text.splitlines() if "raphael_sistine_madonna" in line)
    assert "[ALREADY SHOWN this session]" not in unmarked_line
    assert "pick a different one" in text


def test_only_assistant_turns_are_scanned_not_the_child_repeating_a_title():
    """A child echoing a title back ("I liked the School of Athens!") must
    not itself count as Bede having shown it — only Bede's OWN turns are
    the record of what it actually displayed."""
    history = [
        ChatMessage(role="user", content="I heard about \"The School of Athens\" from a friend"),
    ]
    assert "ALREADY SHOWN" not in _ctx(history=history)


def test_multiple_shown_aids_are_all_marked():
    history = [
        ChatMessage(role="assistant", content="[Showed a picture: \"The School of Athens\" by Raphael (1511)]"),
        ChatMessage(role="user", content="Neat!"),
        ChatMessage(role="assistant", content="[Showed a picture: \"The Sistine Madonna\" by Raphael (1512)]"),
    ]
    text = _ctx(history=history)
    for aid_id in ("raphael_school_of_athens", "raphael_sistine_madonna"):
        line = next(line for line in text.splitlines() if aid_id in line)
        assert "[ALREADY SHOWN this session]" in line
    unmarked_line = next(line for line in text.splitlines() if "raphael_transfiguration" in line)
    assert "[ALREADY SHOWN this session]" not in unmarked_line


def test_empty_history_is_the_same_as_no_history():
    config = _config()
    assert _ctx(config, []) == _ctx(config, None)


def test_non_curated_subject_still_returns_empty_regardless_of_history():
    history = [ChatMessage(role="assistant", content="[Showed a picture: \"The School of Athens\" by Raphael (1511)]")]
    assert _ctx(history=history, subject=Subject.mathematics) == ""


# ── Artist rotation (picture-study lives with one artist per term) ────────

def test_grade_k_trimester_walks_the_first_three_artists_in_order():
    """Grade K is where the rotation starts, so it walks the list from
    entry 0 exactly as every grade did before the grade entered into it."""
    aids_by_term = {
        term: _ctx(_config(term_schedule=TermSchedule.trimester, current_term=term)).lower()
        for term in (1, 2, 3)
    }
    assert "millet" in aids_by_term[1]
    assert "fra_angelico" in aids_by_term[2]
    assert "constable" in aids_by_term[3]
    for text in aids_by_term.values():
        assert "raphael" not in text
        assert "rodin" not in text


def test_grade_k_quarterly_walks_the_first_four_artists_in_order():
    aids_by_term = {
        term: _ctx(_config(term_schedule=TermSchedule.quarterly, current_term=term)).lower()
        for term in (1, 2, 3, 4)
    }
    assert "millet" in aids_by_term[1]
    assert "fra_angelico" in aids_by_term[2]
    assert "constable" in aids_by_term[3]
    assert "raphael" in aids_by_term[4]


def test_rotation_only_lists_the_current_terms_artist():
    text = _ctx(_config(term_schedule=TermSchedule.quarterly, current_term=1)).lower()
    assert "millet" in text
    assert "raphael" not in text
    assert "vermeer" not in text
    assert "rodin" not in text


def test_the_next_grade_picks_up_where_the_last_left_off():
    """Before the grade entered the rotation, term 1 was Millet for every
    child every year. Now grade 1's term 1 continues from where grade K's
    last term stopped, so a child who advances a grade meets a new artist
    rather than the same four again in the same order."""
    for schedule, terms in ((TermSchedule.trimester, 3), (TermSchedule.quarterly, 4)):
        k_last = _term_artist(_config(grade="K", term_schedule=schedule, current_term=terms))
        g1_first = _term_artist(_config(grade="1", term_schedule=schedule, current_term=1))
        k_last_index = _TERM_ARTISTS.index(k_last)
        assert _TERM_ARTISTS[(k_last_index + 1) % len(_TERM_ARTISTS)] == g1_first
        # And consecutive grades never see the identical set.
        k_set = {_term_artist(_config(grade="K", term_schedule=schedule, current_term=t)) for t in range(1, terms + 1)}
        g1_set = {_term_artist(_config(grade="1", term_schedule=schedule, current_term=t)) for t in range(1, terms + 1)}
        assert k_set != g1_set


def test_within_one_grade_no_term_repeats_an_artist():
    for grade in VALID_GRADES:
        for schedule, terms in ((TermSchedule.trimester, 3), (TermSchedule.quarterly, 4)):
            artists = [_term_artist(_config(grade=grade, term_schedule=schedule, current_term=t)) for t in range(1, terms + 1)]
            assert len(set(artists)) == terms, (grade, schedule, artists)


def test_every_rotation_artist_is_reachable_by_some_grade_and_term():
    """Rodin is the fifth entry of a list a single year only ever walks
    three or four of — reachable at all ONLY because the grade advances
    the rotation. A list entry no grade+term combination lands on is a
    catalog nobody sees."""
    reached = {
        _term_artist(_config(grade=grade, term_schedule=schedule, current_term=t))
        for grade in VALID_GRADES
        for schedule, terms in ((TermSchedule.trimester, 3), (TermSchedule.quarterly, 4))
        for t in range(1, terms + 1)
    }
    assert reached == set(_TERM_ARTISTS)
    assert "Auguste Rodin" in reached


def test_rodin_term_lists_only_sculpture_and_says_so():
    """The first non-painting artist: the catalog descriptions carry the
    word so Bede can't call a statue a painting, and only Rodin's works
    are listed for a Rodin term."""
    config = next(
        _config(grade=g, term_schedule=TermSchedule.quarterly, current_term=t)
        for g in VALID_GRADES for t in (1, 2, 3, 4)
        if _term_artist(_config(grade=g, term_schedule=TermSchedule.quarterly, current_term=t)) == "Auguste Rodin"
    )
    text = _ctx(config)
    assert "This quarter's artist is Auguste Rodin" in text
    assert "rodin_thinker" in text
    assert all(i.startswith("rodin_") for i in _ids_in(text))


def test_an_unknown_grade_falls_back_to_the_start_of_the_rotation_rather_than_raising():
    """SessionConfig validates grade, so this is defence in depth for the
    helper itself — a config built with model_construct or a future grade
    value must degrade to grade K's rotation, never to an exception that
    empties picture study."""
    config = _config().model_copy(update={"grade": "13"})
    assert _term_artist(config) == _term_artist(_config(grade="K"))


def test_history_subject_is_unaffected_by_artist_rotation():
    """The rotation is specific to art_music (Mater Amabilis picture study)
    — history's visual aids (maps, artifacts) have no creator-based rotation
    and must keep listing everything regardless of term, and no weekly
    featured mark either."""
    text = _ctx(_config(term_schedule=TermSchedule.quarterly, current_term=1), subject=Subject.history)
    assert "map_roman_empire" in text
    assert "bayeux_tapestry" in text
    assert _THIS_WEEK_MARK not in text


# ── Weekly featured picture (one artist per term, one picture per week) ──

def _raphael_ids() -> list[str]:
    return [a["id"] for a in get_visual_aids("art_music") if a.get("creator") == "Raphael"]


def test_exactly_one_picture_is_marked_as_this_weeks():
    text = _ctx()
    assert text.count(_THIS_WEEK_MARK) == 2  # once in the guidance line, once on the entry
    marked = [line for line in text.splitlines() if line.startswith("- ") and _THIS_WEEK_MARK in line]
    assert len(marked) == 1


def test_this_weeks_picture_is_listed_first_and_named_in_the_guidance():
    text = _ctx()
    first_line = next(line for line in text.splitlines() if line.startswith("- "))
    assert _THIS_WEEK_MARK in first_line
    title = first_line.split('"')[1]
    assert f'This week\'s picture is "{title}"' in text
    assert "open picture study with it" in text


def test_the_featured_picture_changes_from_week_to_week_and_stays_with_the_artist():
    """Seven Raphael entries: seven consecutive weeks must feature seven
    different pictures, all Raphael's, and then the eighth week wraps."""
    config = _config()
    seen = []
    for offset in range(7):
        text = _ctx(config, today=_TODAY + timedelta(weeks=offset))
        featured = next(line for line in text.splitlines() if line.startswith("- ") and _THIS_WEEK_MARK in line)
        featured_id = featured.split(":")[0][2:]
        assert featured_id.startswith("raphael_")
        seen.append(featured_id)
    assert len(set(seen)) == 7 == len(_raphael_ids())
    wrapped = _ctx(config, today=_TODAY + timedelta(weeks=7))
    assert seen[0] in next(line for line in wrapped.splitlines() if line.startswith("- ") and _THIS_WEEK_MARK in line)


def test_the_whole_term_is_still_listed_behind_the_featured_picture():
    """The featured picture is where the week OPENS, not the only picture
    Bede may show: last week's is still there to compare against, and a
    child who asks for it must still be able to see it."""
    assert set(_ids_in(_ctx())) == set(_raphael_ids())


def test_two_days_in_the_same_iso_week_feature_the_same_picture():
    monday, friday = date(2026, 1, 5), date(2026, 1, 9)
    assert _ctx(today=monday) == _ctx(today=friday)


def test_different_terms_are_salted_so_they_do_not_all_start_on_the_same_entry():
    """current_term salts the week the same way it salts poetry/prayer/
    composer study, so two families on different terms in the same
    calendar week aren't both on entry k."""
    # Both Raphael: grade K quarterly term 4, and grade 1 quarterly term 3
    # (index (4 + 2) % 5 == 1 is Fra Angelico — so use the trimester
    # schedule instead: grade 1 trimester term 1 is index 3, Raphael).
    a = _ctx(_config(grade="K", term_schedule=TermSchedule.quarterly, current_term=4))
    b = _ctx(_config(grade="1", term_schedule=TermSchedule.trimester, current_term=1))
    assert "Raphael" in a and "Raphael" in b
    first = lambda t: next(line for line in t.splitlines() if line.startswith("- "))  # noqa: E731
    assert first(a) != first(b)


def test_the_already_shown_marker_and_the_weekly_mark_can_share_a_line():
    """Showing this week's picture once does not demote it: the two
    markers answer different questions (which picture is the week's, and
    which has this session already displayed)."""
    text = _ctx()
    featured_title = next(line for line in text.splitlines() if line.startswith("- ")).split('"')[1]
    history = [ChatMessage(role="assistant", content=f'[Showed a picture: "{featured_title}" by Raphael (1512)]')]
    marked = _ctx(history=history)
    first_line = next(line for line in marked.splitlines() if line.startswith("- "))
    assert _THIS_WEEK_MARK in first_line
    assert "[ALREADY SHOWN this session]" in first_line
