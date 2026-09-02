"""
A celebration's follow-up question must fit what the child actually just did.

## The report

From a real session, by the repository owner: Bede kept asking *"How did you
figure that out?"* after the child told a story back in their own words —
"it didn't relate to a problem or challenge."

## What was actually happening

`celebrate_discovery` is `questionless=True`: its card names something worth
celebrating and, on its own, gives the child nothing to answer. So
`stream_tutor_response` guarantees a follow-up — if no text streams after the
card, it appends one from `_CELEBRATION_FALLBACK_QUESTIONS`. That text is
emitted **with no model in the loop at all**, so it cannot know what the moment
was.

Two things made that land badly, and both are fixed here:

1. **Every question in the list presupposed a solved problem.** "What was the
   first clue that helped you notice that?", "How did you figure that out?",
   "What do you want to try next?" — all of them assert that something was
   worked out. But the most ordinary thing to celebrate in this pedagogy is a
   **narration**: telling a story or a passage back in the child's own words.
   That is the central act of Mater Amabilis and it is not a puzzle.

2. **The model had no way to write its own question for this tool.**
   `connect_to_faith` has an optional `reflection_question`, and supplying it
   suppresses the fallback. `celebrate_discovery` had no question field at
   all — and the loop nevertheless tested `tool_input.get("reflection_question")`,
   the *other* tool's field name, for every questionless tool. That lookup
   could never succeed for a celebration, so **every** turn ending on one took
   the canned path.

The real fix is (2): the model knows whether the child solved something or told
a story, and this list never can. `next_question` lets it say so. The list
stays as the guaranteed backstop, and now has to fit either moment.
"""
import json
import re

import pytest

from services import ai_service, tool_registry

from test_ai_service_streaming import _run_stream, _text_events, _tool_use_events


# ── The backstop may not assert that a problem was solved ───────────────────
#
# Phrasings that only make sense if the child worked something out. Each was
# in the shipped list, or is the same move in different words. Matched against
# the whole question, case-insensitively.
_ASSERTS_A_SOLVED_PROBLEM = {
    "en": [
        r"\bfigure[d]? (?:that|it|this) out\b",
        r"\bwork(?:ed)? (?:that|it|this) out\b",
        r"\bfirst clue\b",
        r"\bsolve\b",
        r"\bhow did you (?:get|know|do)\b",
        r"\bwant to try next\b",
        r"\btry (?:that )?again\b",
    ],
    "es": [
        r"\blo descubriste\b",
        r"\blo resolviste\b",
        r"\bprimera pista\b",
        r"\bc[óo]mo lo (?:supiste|hiciste|lograste)\b",
        r"\bintentar despu[ée]s\b",
    ],
}


@pytest.mark.parametrize("locale", sorted(ai_service._CELEBRATION_FALLBACK_QUESTIONS))
def test_no_celebration_fallback_asserts_the_child_solved_something(locale):
    """The whole reported defect, pinned in both locales.

    A narration is not a puzzle. This text is chosen by the server with no
    knowledge of the turn, so it has to be true of every moment a celebration
    can follow — which means it may presuppose nothing about HOW the child
    arrived at what is being celebrated.
    """
    for question in ai_service._CELEBRATION_FALLBACK_QUESTIONS[locale]:
        for pattern in _ASSERTS_A_SOLVED_PROBLEM[locale]:
            assert not re.search(pattern, question, re.IGNORECASE), (
                f"{locale!r} fallback {question!r} presupposes the child solved "
                f"something (matched {pattern!r}). celebrate_discovery fires after "
                "a narration at least as often as after a worked-out problem, and "
                "this text is picked with no model in the loop to tell them apart."
            )


@pytest.mark.parametrize("locale", sorted(ai_service._CELEBRATION_FALLBACK_QUESTIONS))
def test_the_backstop_is_still_a_real_question(locale):
    """Neutral must not become empty. The fallback exists so the conversation
    never stalls on a card with nothing to answer — that guarantee is the
    reason to keep the list at all."""
    questions = ai_service._CELEBRATION_FALLBACK_QUESTIONS[locale]
    assert len(questions) >= 3, "too few to avoid sounding like a stock phrase"
    assert len(set(questions)) == len(questions)
    for question in questions:
        assert question.strip().endswith("?")
        assert len(question.split()) >= 3


# ── The model's own question wins ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_model_supplied_next_question_suppresses_the_fallback():
    """The fix for the report. Verified to FAIL before this change: the loop
    asked every questionless tool for `reflection_question`, so a celebration's
    own question was invisible to it and the canned question was appended on
    top of it regardless."""
    events = list(_tool_use_events(
        "toolu_1", "celebrate_discovery",
        {
            "specific_insight": "you remembered the part about the flood",
            "encouragement": "You told that beautifully.",
            "next_question": "Which part of the story stayed with you most?",
        },
    ))
    parsed = await _run_stream(events)

    trailing_text = [p["content"].strip() for p in parsed if p["type"] == "text"]
    for text in trailing_text:
        assert text not in ai_service._CELEBRATION_FALLBACK_QUESTIONS["en"], (
            "a canned question was appended even though the model wrote its own"
        )

    tool_cards = [p for p in parsed if p["type"] == "tool"]
    assert tool_cards, "the celebration card was not emitted at all"
    assert "Which part of the story stayed with you most?" in tool_cards[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   "])
async def test_a_blank_next_question_still_gets_the_backstop(blank):
    """The guarantee must not be defeatable by an empty string — that would
    leave the child with a celebration and nothing to answer, which is the
    outage the fallback was written for."""
    events = list(_tool_use_events(
        "toolu_1", "celebrate_discovery",
        {
            "specific_insight": "you remembered the part about the flood",
            "encouragement": "You told that beautifully.",
            "next_question": blank,
        },
    ))
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "no fallback question was appended"
    assert text_chunks[-1]["content"].strip() in ai_service._CELEBRATION_FALLBACK_QUESTIONS["en"]


@pytest.mark.asyncio
async def test_connect_to_faith_still_reads_its_own_field():
    """Generalising the lookup must not have broken the tool it was written
    for."""
    events = list(_tool_use_events(
        "toolu_1", "connect_to_faith",
        {
            "connection": "The river keeps giving without being asked.",
            "reflection_question": "Where have you seen that kind of giving?",
        },
    ))
    parsed = await _run_stream(events)

    for chunk in (p for p in parsed if p["type"] == "text"):
        assert chunk["content"].strip() not in ai_service._FAITH_FALLBACK_QUESTIONS["en"]


@pytest.mark.asyncio
async def test_real_text_after_the_card_still_wins_over_both():
    """Unchanged behaviour, asserted because this change touched the branch it
    lives in: the model's own streamed text has always suppressed the
    fallback, and still must."""
    events = [
        *_tool_use_events(
            "toolu_1", "celebrate_discovery",
            {"specific_insight": "you saw the pattern", "encouragement": "Lovely."},
            index=0,
        ),
        *_text_events(" What made you look there first?", index=1),
    ]
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks[-1]["content"].strip() not in ai_service._CELEBRATION_FALLBACK_QUESTIONS["en"]


# ── The registry ────────────────────────────────────────────────────────────

def test_every_questionless_tool_declares_which_field_carries_its_question():
    """A questionless tool with no `question_field` is a tool whose card can
    never carry its own question — exactly the state `celebrate_discovery` was
    in, and the reason the model could not fix the mismatch itself."""
    for name in tool_registry.QUESTIONLESS_TOOLS:
        spec = tool_registry.get_spec(name)
        assert spec.question_field, (
            f"{name} is questionless but declares no question_field, so nothing "
            "the model writes can suppress the server's canned follow-up."
        )


def test_every_declared_question_field_exists_in_the_tools_own_schema():
    """The field name in the registry and the field name the model is offered
    are the same fact in two files. When they disagreed, the disagreement was
    silent: the lookup simply never matched."""
    schemas = {t["name"]: t for t in ai_service.TUTOR_TOOLS}
    for name in tool_registry.QUESTIONLESS_TOOLS:
        field = tool_registry.get_spec(name).question_field
        properties = schemas[name]["input_schema"]["properties"]
        assert field in properties, (
            f"{name}'s registry declares question_field={field!r}, which is not a "
            "property of its own input_schema — the model can never send it."
        )
        assert field not in schemas[name]["input_schema"].get("required", []), (
            f"{name}'s {field!r} must stay optional; the fallback is what covers "
            "the turns where the model omits it."
        )


def test_carries_own_question_reports_false_for_anything_it_cannot_vouch_for():
    assert not tool_registry.carries_own_question("definitely_not_a_tool", {"next_question": "?"})
    assert not tool_registry.carries_own_question("request_narration", {"next_question": "?"})
    assert not tool_registry.carries_own_question("celebrate_discovery", {})
    assert not tool_registry.carries_own_question("celebrate_discovery", {"next_question": None})
    assert not tool_registry.carries_own_question("celebrate_discovery", {"reflection_question": "?"})
    assert tool_registry.carries_own_question("celebrate_discovery", {"next_question": "What next?"})


# ── The card, and what the model is told ────────────────────────────────────

def test_the_celebration_card_renders_a_supplied_question_after_the_praise():
    rendered = ai_service._process_tool_use("celebrate_discovery", {
        "specific_insight": "you remembered the flood",
        "encouragement": "You told that beautifully.",
        "next_question": "Which part stayed with you most?",
    })
    assert rendered.endswith("Which part stayed with you most?")
    assert "You told that beautifully." in rendered

    without = ai_service._process_tool_use("celebrate_discovery", {
        "specific_insight": "you remembered the flood",
        "encouragement": "You told that beautifully.",
    })
    assert without.endswith(".")
    assert "?" not in without


def test_the_prompt_tells_the_model_to_fit_the_question_to_a_narration():
    """The prompt used to state, as a fact, that celebrate_discovery "has no
    question field at all". That is now false, and a stale instruction is worse
    than none — it would keep the model from using the field that fixes this."""
    from models.schemas import GradeStage, SessionConfig

    prompt = ai_service._build_static_prompt(
        SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)
    )
    assert "celebrate_discovery` has no question field" not in prompt
    assert "next_question" in prompt
    assert "narration" in prompt
    assert re.search(r"figured? something out when nothing was figured out", prompt), (
        "the prompt no longer names the specific mismatch this change was reported for"
    )
