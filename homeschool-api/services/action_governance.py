"""
Action governance — the one place a proposed tool call is checked against
this turn's own budget before it executes.

## Why this is its own module

`routers/tutor.py`'s `chat()` implements the documented controller loop
(CLAUDE.md's "Bede's turn controller"), and its **Action Validator** stage
is the last gate between what the model proposed and what the child
actually sees. Before this module that stage existed, and worked, but as
inline `if` statements roughly 1200 lines from the tool schemas they
governed — so it could not be read as a policy, could not be tested
without driving a whole stream, and had no name to add a rule to.

`services/policy_engine.py` is the precedent, deliberately: a pure
function, no I/O, taking everything it needs as arguments and returning
one decision. Same reasoning here. A gate that needs a database, a clock,
or a network call belongs at its own dispatch site, not in this file.

## What this module owns, and what it does not

Owns the **cross-cutting** rules — the ones that apply to any tool
regardless of what that tool does:

* `allowed_tools` — is this a tool the tutor loop may dispatch at all.
  Reads `services/tool_registry.py`, so a hallucinated name, or an
  `external` tool that only the parent sandbox may reach, is refused here
  rather than falling through to a handler.
* the per-turn call cap (`_MAX_TOOL_CALLS_PER_TURN`'s value, passed in) —
  defense in depth against a turn that keeps firing tools.
* `time_remaining_seconds` — see `MIN_SECONDS_FOR_LONG_FORM_TASK` below.

Does NOT own the **per-tool** semantics, and deliberately: the
subject/stage gate on `record_phonics_evidence`, the own-language-only
gate on `record_language_evidence`, `shown_aid_ids`' within-turn repeat
guard. Those are facts about one tool's meaning, they live at that tool's
own dispatch branch where a reader meets them beside the code they
constrain, and folding them in here would trade a local rule for a
distant one. This module is the policy every tool passes through; those
are the tools' own definitions.

## The time rule, and why it is a governance rule rather than only a prompt

`SUBJECT_DURATIONS` gives a subject its block, and `gradeTimer.ts` hard
stops the session when the clock runs out. Nothing connected the two:
the server never knew how much of the block was left, so Bede could open
a narration — the longest task in the pedagogy, and its central act —
with ninety seconds on the clock, and the timer would stop the child
mid-sentence. Being cut off mid-narration is the exact failure
`_WORK_SCORING_NOTE`'s standing "never hurry a child" rule exists to
prevent, and it arrived through the one path that rule did not cover:
not Bede hurrying the child in words, but Bede starting something the
clock could not hold.

`_time_remaining_note` (services/ai_service.py) is the prompt half and
does the graceful work — Bede chooses not to start a long task, and winds
the thread up instead. This is the backstop, and it is the half that
holds when the model proposes one anyway. Both are wanted: the prompt
alone is guidance a turn can drift past, and the backstop alone would
suppress a card with no accompanying change in what Bede says.

`time_remaining_seconds` is `None` for any caller that does not know it —
older clients, the sandbox, every test that does not pass one — and a
`None` budget disables the rule rather than assuming the worst. A
deployment that never sends it behaves exactly as it did before this
module existed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.tool_registry import is_dispatchable_by_tutor

#: Below this much time left in the subject block, a long-form task is not
#: started. Narration and a handwriting/drawing invitation are both tasks
#: the CHILD then spends minutes on, so the floor is about their working
#: time and not about Bede's own latency.
#:
#: Three minutes is deliberately modest. The point is to refuse the clearly
#: doomed case (a multi-minute task with seconds left), not to reserve a
#: comfortable margin — a floor set generously would start suppressing
#: invitations a child had time for, which costs real practice to prevent
#: a rarer bad ending.
MIN_SECONDS_FOR_LONG_FORM_TASK = 180

#: The tools whose cards hand the child a task to go and do, rather than
#: something to read and answer in the next breath. `request_narration` is
#: telling a passage back from memory; `invite_handwriting` opens the
#: full-screen canvas. Everything else (a hint, a celebration, a picture,
#: a faith connection) is read in place and costs no working time.
LONG_FORM_TOOLS = frozenset({"request_narration", "invite_handwriting"})


@dataclass(frozen=True)
class ActionDecision:
    """One verdict on one proposed tool call.

    `reason` is always set, including when allowed, because it is what the
    audit detail and the log line are written from — a suppression whose
    record does not say which rule fired is a suppression nobody can
    debug later.
    """

    allowed: bool
    reason: str

    #: Should the tool_result loop stop after this call, rather than asking
    #: the model for another round? True for every refusal: a suppressed
    #: `tool_use` block never receives a matching `tool_result`, and the
    #: Anthropic API requires every `tool_use` in a turn to be answered
    #: before the next request — so once a call is refused, continuing is
    #: a promise this code can no longer keep. (The same reasoning the
    #: per-turn cap already carried at its own call site.)
    end_loop: bool = False


_ALLOWED = ActionDecision(allowed=True, reason="ok")


def validate(
    tool_name: str,
    *,
    calls_this_turn: int,
    max_calls_per_turn: int,
    time_remaining_seconds: Optional[int] = None,
) -> ActionDecision:
    """Check one proposed tool call against this turn's budget.

    Pure: no I/O, no clock, no database. Everything the decision depends on
    is an argument, so a test states a situation rather than building one.

    Order matters and is from cheapest to most specific. An unknown tool is
    refused before its call is counted against the cap, so a hallucinated
    name cannot consume a real tool's budget.
    """
    if not is_dispatchable_by_tutor(tool_name):
        # Neither a real tutor tool nor one this loop may reach. Ending the
        # loop here is not strictly required — the model could recover —
        # but a turn proposing tools that do not exist is not a turn worth
        # buying more rounds for.
        return ActionDecision(
            allowed=False,
            reason=f"tool={tool_name} not_dispatchable_by_tutor",
            end_loop=True,
        )

    if calls_this_turn >= max_calls_per_turn:
        return ActionDecision(
            allowed=False,
            reason=f"tool={tool_name} cap={max_calls_per_turn}",
            end_loop=True,
        )

    if (
        tool_name in LONG_FORM_TOOLS
        and time_remaining_seconds is not None
        and time_remaining_seconds < MIN_SECONDS_FOR_LONG_FORM_TASK
    ):
        return ActionDecision(
            allowed=False,
            reason=(
                f"tool={tool_name} time_remaining={time_remaining_seconds}s "
                f"floor={MIN_SECONDS_FOR_LONG_FORM_TASK}s"
            ),
            end_loop=True,
        )

    return _ALLOWED
