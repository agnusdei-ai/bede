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
"""
from models.schemas import ChatMessage, Subject
from services.ai_service import _get_visual_aids_context


def test_no_history_lists_every_aid_with_no_marker():
    text = _get_visual_aids_context(Subject.art_music)
    assert "raphael_school_of_athens" in text
    assert "vermeer_girl_pearl" in text
    assert "ALREADY SHOWN" not in text


def test_a_shown_aid_gets_marked_and_others_do_not():
    history = [
        ChatMessage(role="assistant", content="Here it is properly: [Showed a picture: \"The School of Athens\" by Raphael (1511)]"),
        ChatMessage(role="user", content="I see the picture"),
    ]
    text = _get_visual_aids_context(Subject.art_music, history)
    assert "raphael_school_of_athens: \"The School of Athens\" (Raphael) — " in text
    # The marked line specifically
    marked_line = next(line for line in text.splitlines() if "raphael_school_of_athens" in line)
    assert "[ALREADY SHOWN this session]" in marked_line
    # A different aid must NOT be marked
    unmarked_line = next(line for line in text.splitlines() if "vermeer_girl_pearl" in line)
    assert "[ALREADY SHOWN this session]" not in unmarked_line
    assert "pick a different one" in text


def test_only_assistant_turns_are_scanned_not_the_child_repeating_a_title():
    """A child echoing a title back ("I liked the School of Athens!") must
    not itself count as Bede having shown it — only Bede's OWN turns are
    the record of what it actually displayed."""
    history = [
        ChatMessage(role="user", content="I heard about \"The School of Athens\" from a friend"),
    ]
    text = _get_visual_aids_context(Subject.art_music, history)
    assert "ALREADY SHOWN" not in text


def test_multiple_shown_aids_are_all_marked():
    history = [
        ChatMessage(role="assistant", content="[Showed a picture: \"The School of Athens\" by Raphael (1511)]"),
        ChatMessage(role="user", content="Neat!"),
        ChatMessage(role="assistant", content="[Showed a picture: \"The Starry Night\" by Vincent van Gogh (1889)]"),
    ]
    text = _get_visual_aids_context(Subject.art_music, history)
    for aid_id in ("raphael_school_of_athens", "van_gogh_starry_night"):
        line = next(line for line in text.splitlines() if aid_id in line)
        assert "[ALREADY SHOWN this session]" in line
    unmarked_line = next(line for line in text.splitlines() if "davinci_mona_lisa" in line)
    assert "[ALREADY SHOWN this session]" not in unmarked_line


def test_empty_history_is_the_same_as_no_history():
    assert _get_visual_aids_context(Subject.art_music, []) == _get_visual_aids_context(Subject.art_music, None)


def test_non_curated_subject_still_returns_empty_regardless_of_history():
    history = [ChatMessage(role="assistant", content="[Showed a picture: \"The School of Athens\" by Raphael (1511)]")]
    assert _get_visual_aids_context(Subject.mathematics, history) == ""
