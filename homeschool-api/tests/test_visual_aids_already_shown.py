"""
Real check for _get_visual_aids_context's "already shown this session"
marking — the deeper cause behind repeated Art & Music images surviving
the earlier history-amnesia fix (getApiMessages/toApiMessage folding
visual-aid mentions back into conversation history). That fix gave Bede
textual memory that it showed a picture, but _get_visual_aids_context
itself listed the same catalog identically on every single turn with no
indication of what had already been used — a soft signal (one line of
prose to infer from) rather than a hard one, which matters a lot more
against a catalog this small (6 entries for art_music).

_get_visual_aids_context now also requires a SessionConfig (added by the
picture-study artist-rotation feature — see _TERM_ARTISTS) to determine
which single artist's works are in scope for the current term/quarter;
every test below uses a quarterly, term-4 config specifically because
Raphael (_TERM_ARTISTS[3]) is the only rotation artist with more than one
catalog entry that overlaps what these tests need to exercise (three
paintings, so "one shown, one not" and "two shown, one not" both have
something to assert against).
"""
from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject, TermSchedule
from services.ai_service import _get_visual_aids_context


def _config(**overrides) -> SessionConfig:
    defaults = dict(
        student_name="Emma", grade="6", grade_stage=GradeStage.independent,
        term_schedule=TermSchedule.quarterly, current_term=4,
    )
    defaults.update(overrides)
    return SessionConfig(**defaults)


def test_no_history_lists_every_aid_with_no_marker():
    text = _get_visual_aids_context(Subject.art_music, _config())
    assert "raphael_school_of_athens" in text
    assert "raphael_sistine_madonna" in text
    assert "ALREADY SHOWN" not in text


def test_a_shown_aid_gets_marked_and_others_do_not():
    history = [
        ChatMessage(role="assistant", content="Here it is properly: [Showed a picture: \"The School of Athens\" by Raphael (1511)]"),
        ChatMessage(role="user", content="I see the picture"),
    ]
    text = _get_visual_aids_context(Subject.art_music, _config(), history)
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
    text = _get_visual_aids_context(Subject.art_music, _config(), history)
    assert "ALREADY SHOWN" not in text


def test_multiple_shown_aids_are_all_marked():
    history = [
        ChatMessage(role="assistant", content="[Showed a picture: \"The School of Athens\" by Raphael (1511)]"),
        ChatMessage(role="user", content="Neat!"),
        ChatMessage(role="assistant", content="[Showed a picture: \"The Sistine Madonna\" by Raphael (1512)]"),
    ]
    text = _get_visual_aids_context(Subject.art_music, _config(), history)
    for aid_id in ("raphael_school_of_athens", "raphael_sistine_madonna"):
        line = next(line for line in text.splitlines() if aid_id in line)
        assert "[ALREADY SHOWN this session]" in line
    unmarked_line = next(line for line in text.splitlines() if "raphael_transfiguration" in line)
    assert "[ALREADY SHOWN this session]" not in unmarked_line


def test_empty_history_is_the_same_as_no_history():
    config = _config()
    assert _get_visual_aids_context(Subject.art_music, config, []) == _get_visual_aids_context(Subject.art_music, config, None)


def test_non_curated_subject_still_returns_empty_regardless_of_history():
    history = [ChatMessage(role="assistant", content="[Showed a picture: \"The School of Athens\" by Raphael (1511)]")]
    assert _get_visual_aids_context(Subject.mathematics, _config(), history) == ""


# ── Artist rotation (picture-study lives with one artist per term) ────────

def test_trimester_rotation_cycles_through_the_first_three_artists():
    aids_by_term = {
        term: _get_visual_aids_context(Subject.art_music, _config(term_schedule=TermSchedule.trimester, current_term=term))
        for term in (1, 2, 3)
    }
    assert "millet" in aids_by_term[1].lower()
    assert "fra_angelico" in aids_by_term[2].lower()
    assert "constable" in aids_by_term[3].lower()
    # Trimester years never reach Raphael (index 3 of a 4-artist rotation) —
    # the rotation length is 3 for trimester, so it wraps before getting there.
    assert "raphael" not in aids_by_term[1].lower()
    assert "raphael" not in aids_by_term[2].lower()
    assert "raphael" not in aids_by_term[3].lower()


def test_quarterly_rotation_reaches_all_four_artists():
    aids_by_term = {
        term: _get_visual_aids_context(Subject.art_music, _config(term_schedule=TermSchedule.quarterly, current_term=term))
        for term in (1, 2, 3, 4)
    }
    assert "millet" in aids_by_term[1].lower()
    assert "fra_angelico" in aids_by_term[2].lower()
    assert "constable" in aids_by_term[3].lower()
    assert "raphael" in aids_by_term[4].lower()


def test_rotation_only_lists_the_current_terms_artist():
    text = _get_visual_aids_context(Subject.art_music, _config(term_schedule=TermSchedule.quarterly, current_term=1))
    assert "millet" in text.lower()
    assert "raphael" not in text.lower()
    assert "vermeer" not in text.lower()


def test_history_subject_is_unaffected_by_artist_rotation():
    """The rotation is specific to art_music (Mater Amabilis picture study)
    — history's visual aids (maps, artifacts) have no creator-based rotation
    and must keep listing everything regardless of term."""
    text = _get_visual_aids_context(Subject.history, _config(term_schedule=TermSchedule.quarterly, current_term=1))
    assert "map_roman_empire" in text
    assert "bayeux_tapestry" in text
