"""
Real check for services/ai_service.py's _normalize_alternating_roles — the
Messages API rejects two consecutive same-role turns outright. Found via
homeschool-tutor/scripts/bugcatcher.mts's S5 scenario: the idle-continue
"[CONTINUE]" sentinel is deliberately never stored as a visible user turn
client-side (both apps), so the assistant reply that answered it ends up
sitting directly next to the assistant turn before it once that history is
replayed on the child's next real message — sending the API two assistant
turns in a row, which it would reject with a 400.
"""
from services.ai_service import _normalize_alternating_roles


def test_empty_list_is_a_no_op():
    assert _normalize_alternating_roles([]) == []


def test_already_alternating_messages_are_unchanged():
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Bye"},
    ]
    assert _normalize_alternating_roles(messages) == messages


def test_merges_two_consecutive_assistant_turns():
    """The exact shape the [CONTINUE] gap produces: Bede's subject-complete
    line, then Bede's own reply to the invisible [CONTINUE] sentinel,
    with no real user turn recorded in between."""
    messages = [
        {"role": "user", "content": "12!"},
        {"role": "assistant", "content": "Exactly right, 12."},
        {"role": "assistant", "content": "Are you still there? Here's an easier way to think about it."},
        {"role": "user", "content": "Sorry, I'm back!"},
    ]
    result = _normalize_alternating_roles(messages)
    assert result == [
        {"role": "user", "content": "12!"},
        {"role": "assistant", "content": "Exactly right, 12.\n\nAre you still there? Here's an easier way to think about it."},
        {"role": "user", "content": "Sorry, I'm back!"},
    ]
    # Every remaining entry strictly alternates
    for prev, nxt in zip(result, result[1:]):
        assert prev["role"] != nxt["role"]


def test_merges_three_or_more_consecutive_same_role_turns():
    messages = [
        {"role": "assistant", "content": "A"},
        {"role": "assistant", "content": "B"},
        {"role": "assistant", "content": "C"},
        {"role": "user", "content": "D"},
    ]
    result = _normalize_alternating_roles(messages)
    assert result == [
        {"role": "assistant", "content": "A\n\nB\n\nC"},
        {"role": "user", "content": "D"},
    ]


def test_does_not_mutate_the_input_list():
    messages = [
        {"role": "assistant", "content": "A"},
        {"role": "assistant", "content": "B"},
    ]
    original = [dict(m) for m in messages]
    _normalize_alternating_roles(messages)
    assert messages == original


def test_multimodal_list_content_is_left_unmerged_not_dropped():
    """A drawing turn's content is a list (image + text blocks), not a str
    — merge logic only ever combines plain text, per the function's own
    docstring. Confirms the multimodal entry survives untouched rather than
    being silently merged/corrupted if it ever ends up adjacent to another
    same-role turn."""
    image_block = [{"type": "image", "source": {}}, {"type": "text", "text": "look"}]
    messages = [
        {"role": "user", "content": "before"},
        {"role": "user", "content": image_block},
    ]
    result = _normalize_alternating_roles(messages)
    assert result == messages
