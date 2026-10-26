"""The celebration card says what the child did in a sentence a person would say.

Reported from real sessions: children read "I noticed that you saw that you
noticed..." The server used to wrap the model's clause in a fixed frame,
"I noticed you saw that ___", and the model naturally starts that clause
with a noticing verb of its own, so the two stacked on every celebration.
The frame is gone: specific_insight is now the whole sentence, and the
server only tidies its capital letter and full stop.
"""
import re

import pytest

from services.ai_service import _CARD_PHRASES, TUTOR_TOOLS, _process_tool_use

NOTICING = r"\b(?:noticed|notice|saw|see|spotted|vi|viste|di cuenta)\b"


@pytest.mark.parametrize("locale", sorted(_CARD_PHRASES))
def test_the_server_adds_no_noticing_frame_of_its_own(locale):
    assert "celebration" not in _CARD_PHRASES[locale], (
        "a server-composed celebration frame is back; it stacks on the model's own noticing verb"
    )
    card = _process_tool_use(
        "celebrate_discovery", {"specific_insight": "x", "encouragement": "y"}, locale,
    )
    assert not re.search(NOTICING, card, re.IGNORECASE), card


@pytest.mark.parametrize("locale", ["en", "es"])
def test_the_reported_phrase_cannot_be_produced_by_the_server(locale):
    card = _process_tool_use(
        "celebrate_discovery",
        {"specific_insight": "you noticed the pattern repeats", "encouragement": "Well done!"},
        locale,
    )
    assert len(re.findall(NOTICING, card, re.IGNORECASE)) == 1, card
    assert "you saw that" not in card.lower()


def test_a_clause_is_rendered_as_its_own_sentence():
    card = _process_tool_use(
        "celebrate_discovery",
        {"specific_insight": "you spotted that the water rises", "encouragement": "Well done!"},
    )
    assert card == "✨ Well done! You spotted that the water rises."


def test_existing_punctuation_and_a_follow_up_question_are_kept():
    card = _process_tool_use(
        "celebrate_discovery",
        {
            "specific_insight": "You tied the storm back to the start of the story!",
            "encouragement": "Lovely.",
            "next_question": "What happens next?",
        },
    )
    assert card == "✨ Lovely. You tied the storm back to the start of the story! What happens next?"


def test_the_schema_asks_for_one_natural_sentence_with_no_stacked_noticing():
    tool = next(t for t in TUTOR_TOOLS if t["name"] == "celebrate_discovery")
    description = tool["input_schema"]["properties"]["specific_insight"]["description"]
    assert "complete sentence" in description
    assert "never one stacked on another" in description
    assert "vary the wording" in description
    assert "I noticed you saw" not in description
