"""Declarative registry of Bede's agentic tools.

## Why this exists

Every fact about a tool used to be encoded in a `tc["name"] == "..."` check
somewhere inside `stream_tutor_response`'s streaming loop — whether it ends
the loop, whether its result is worth another model round-trip, whether it
renders a card with no question of its own. That worked while the tool set
was small and entirely ours, but it made three things impossible to see and
easy to get wrong:

* **What a tool actually is** was spread across five places (the schema in
  `TUTOR_TOOLS`, a membership set at module top, and three separate name
  comparisons buried ~1200 lines further down inside a nested generator).
* **Whether the set was complete** could not be checked — a tool added to
  `TUTOR_TOOLS` with no matching branch fell through to `_process_tool_use`,
  returned `""`, and silently emitted nothing. No test could catch that.
* **Where a tool's result came from** was never written down at all, because
  until now there was only ever one answer.

That last one is the reason this module exists now rather than later. See
"The trust tier" below.

## The trust tier

`services/ai_service.py`'s tool_result loop rests on an invariant stated in
CLAUDE.md: tool_result content is *"always fixed, server-computed structured
data — never raw free text, never anything sourced from outside this
process."* That is what makes the loop safe to feed back into the model: no
tool can carry an instruction, because no tool's output originates anywhere
an instruction could be authored.

`ToolSpec.trust` writes that invariant down as data instead of leaving it as
a property nobody declared:

* ``internal`` — the result is computed by this process from its own state
  (a catalog lookup, an already-persisted rubric, a fixed acknowledgment).
  Every tool in `TUTOR_TOOLS` is internal, and
  `tests/test_tool_registry.py::test_every_tutor_tool_is_internal` fails if
  that ever stops being true.
* ``external`` — the result comes from outside this process (an MCP server
  the parent connected). Such a tool is **structurally barred from the tutor
  loop**: `TUTOR_TOOL_SPECS` contains only internal specs, so a child's
  session cannot dispatch an external tool even if one is registered
  elsewhere in the process. External tools live in the parent sandbox's own
  separate loop (`stream_sandbox_response`), which applies its own
  sanitization and envelope. This is a structural guarantee rather than a
  policy one, which is the only kind worth having here.

## What this module deliberately does NOT do

It holds no handlers. The dispatch bodies stay in `ai_service.py` because
they close over that turn's `db`, `config`, `subject`, `demo_code`, and
`session_id`, and hoisting them here would either thread six arguments
through every call or invent a context object whose only purpose is to
satisfy this file. The registry owns *what a tool is*; `ai_service.py`
keeps owning *what a tool does*. `test_tool_registry.py` pins the two
together by asserting that every registered name has a real branch and
every branch has a registered name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Tuple

TrustTier = Literal["internal", "external"]


@dataclass(frozen=True)
class ToolSpec:
    """Everything the agentic loop needs to know about one tool, apart from
    its JSON schema (which stays inline in `TUTOR_TOOLS`, where it is read
    alongside the prose description the model actually sees) and its handler
    (see this module's docstring)."""

    name: str

    #: Where this tool's tool_result content originates. See the module
    #: docstring — this is the field the sandbox's external-tool boundary is
    #: built on, and the one a reviewer should look at first when adding a
    #: tool.
    trust: TrustTier = "internal"

    #: Does this tool's result carry a genuinely dynamic outcome — something
    #: the model could not have known when it made the call, and might
    #: reasonably want to react to in the same turn? Only these extend the
    #: tool_result loop past round 1. Everything else resolves to
    #: `_TRIVIAL_TOOL_RESULT`, so an ordinary turn stays a single round-trip.
    reactable: bool = False

    #: Does firing this tool end the loop outright, regardless of what else
    #: happened in the same round? True only for terminal UI transitions the
    #: frontend is already navigating away from.
    terminal: bool = False

    #: Does this tool emit nothing at all to the SSE stream? The silent
    #: diagnostic writes have an explicit, tested contract of returning
    #: nothing and rendering nothing; marking them here is what lets a test
    #: assert that contract against the registry rather than against a
    #: hand-maintained list in the test file.
    silent: bool = False

    #: Does this tool render a card carrying no question of its own, so the
    #: turn needs a deterministic follow-up question appended if no real text
    #: follows it? See `_QUESTIONLESS_TOOLS`' own comment in ai_service.py for
    #: why a prompt instruction alone is not sufficient here.
    questionless: bool = False

    #: The name of the OPTIONAL input field which, when the model fills it in,
    #: means this card carried its own question after all — so the fallback
    #: must not fire. Only meaningful alongside `questionless`.
    #:
    #: This is here rather than as a literal string in `ai_service.py` because
    #: it was one there, and it was the WRONG one: the loop asked every
    #: questionless tool for `reflection_question`, which is
    #: `connect_to_faith`'s field name. `celebrate_discovery` had no question
    #: field at all, so that lookup could never succeed for it and every turn
    #: ending on a celebration took the canned-question path — including after
    #: a narration, where the canned questions asked how the child had figured
    #: something out when nothing had been figured out. Declaring the field per
    #: tool is what makes a second question field impossible to add without
    #: wiring it up.
    question_field: str | None = None


# Order mirrors TUTOR_TOOLS in services/ai_service.py. Keeping the two in the
# same order is a readability convention, not a correctness requirement —
# test_tool_registry.py checks set equality, not sequence.
_SPECS: Tuple[ToolSpec, ...] = (
    ToolSpec("request_narration"),
    ToolSpec("invite_handwriting"),
    ToolSpec("offer_socratic_hint"),
    # celebrate_discovery/connect_to_faith render a card and may legitimately
    # carry no question, hence questionless. They are NOT reactable: nothing
    # about the outcome is dynamic, so they never earn a second round-trip.
    ToolSpec("celebrate_discovery", questionless=True, question_field="next_question"),
    ToolSpec("connect_to_faith", questionless=True, question_field="reflection_question"),
    # The two genuinely reactable tools, and the whole reason the tool_result
    # loop exists. show_visual_aid can miss (a hallucinated visual_aid_id was
    # previously a silent no-op the model never learned about);
    # assess_narration returns a rubric summary this code has already computed.
    ToolSpec("show_visual_aid", reactable=True),
    ToolSpec("assess_narration", reactable=True),
    # Terminal: the frontend is already navigating away from this subject, so
    # the model never gets a further round to keep reasoning about it.
    ToolSpec("suggest_next_subject", terminal=True),
    # The four silent diagnostic writes. No SSE chunk, no return value, no
    # model-visible surface — deliberately excluded from the reactable set so
    # they keep exactly the contract their own test suites already pin.
    ToolSpec("record_skill_evidence", silent=True),
    ToolSpec("record_literacy_evidence", silent=True),
    ToolSpec("record_phonics_evidence", silent=True),
    ToolSpec("record_language_evidence", silent=True),
)

TUTOR_TOOL_SPECS: Dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}

# Convenience projections. Derived rather than hand-listed so they cannot
# drift from the specs above — this is the entire point of the module.
REACTABLE_TOOLS = frozenset(s.name for s in _SPECS if s.reactable)
TERMINAL_TOOLS = frozenset(s.name for s in _SPECS if s.terminal)
SILENT_TOOLS = frozenset(s.name for s in _SPECS if s.silent)
QUESTIONLESS_TOOLS = frozenset(s.name for s in _SPECS if s.questionless)


def get_spec(name: str) -> ToolSpec | None:
    """The spec for a tool the model asked for, or None if it named something
    that isn't a tutor tool at all.

    Returning None rather than raising is deliberate: a model can emit a
    hallucinated tool name, and the loop's existing posture for anything it
    can't act on is to drop it quietly rather than fail the child's turn. The
    caller decides; this function only reports.
    """
    return TUTOR_TOOL_SPECS.get(name)


def is_reactable(name: str) -> bool:
    """Whether this tool's result should extend the tool_result loop.

    Note the default for an unknown name is False — an unrecognized tool
    must never be able to buy itself extra model round-trips.
    """
    spec = TUTOR_TOOL_SPECS.get(name)
    return bool(spec and spec.reactable)


def is_terminal(name: str) -> bool:
    """Whether firing this tool ends the loop outright."""
    spec = TUTOR_TOOL_SPECS.get(name)
    return bool(spec and spec.terminal)


def is_questionless(name: str) -> bool:
    """Whether this tool renders a card that may carry no question of its own."""
    spec = TUTOR_TOOL_SPECS.get(name)
    return bool(spec and spec.questionless)


def carries_own_question(name: str, tool_input: dict) -> bool:
    """Whether THIS call actually filled in its own follow-up question.

    A question the model wrote knows what the child just did; the fallback in
    `ai_service.py` does not, and cannot — it is emitted with no model in the
    loop at all. So whenever the model supplies one, it wins and the fallback
    stays silent.

    False for a tool with no question field, for an unknown name, and for a
    field present but blank or whitespace — an empty string must leave the
    child with the guaranteed fallback rather than with nothing.
    """
    spec = TUTOR_TOOL_SPECS.get(name)
    if spec is None or spec.question_field is None:
        return False
    value = tool_input.get(spec.question_field)
    return isinstance(value, str) and bool(value.strip())
