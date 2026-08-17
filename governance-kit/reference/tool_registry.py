"""Declarative registry of an agent's tools, and the trust boundary.

Supports prompts/G06-tool-use-discipline.md.

WHY A REGISTRY
--------------
Without one, every fact about a tool lives as a `name == "..."` check somewhere
inside a streaming loop, far from the tool's schema. Three consequences, all of
which bite eventually:

  * What a tool IS is spread across several places and cannot be read in one go.
  * Whether the set is COMPLETE cannot be checked -- a tool added to the schema
    list with no matching dispatch branch silently does nothing, and no test can
    catch it.
  * Where a tool's result COMES FROM is written down nowhere, because until you
    add your first external tool there is only ever one answer.

That last one is why this exists before you need it.

THE TRUST TIER
--------------
The agentic loop rests on an invariant: tool_result content is always fixed,
server-computed structured data -- never raw free text, never anything sourced
from outside this process. That is what makes results safe to feed back to the
model. No tool can carry an instruction, because no tool's output originates
anywhere an instruction could be authored.

`trust` writes that invariant down as data instead of leaving it as a property
nobody declared:

  * ``internal`` -- computed by this process from its own state (a lookup hit or
    miss, an already-persisted record, a fixed acknowledgment).
  * ``external`` -- from outside this process (an MCP server, a web fetch, a
    user-populated database field). STRUCTURALLY BARRED from the untrusted loop:
    the registry that loop dispatches from contains only internal specs, so it
    cannot dispatch an external tool even if the model asks for one, and even if
    an injection succeeds completely. External tools belong to a separate loop
    with a different audience -- see external_content.py.

Pair this with `test_every_tool_is_internal`. The test is the control; the field
is only how you express it.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It holds no handlers. Dispatch bodies stay where they can close over the
request's own state; hoisting them here would mean threading six arguments
through every call or inventing a context object whose only purpose is to
satisfy this file. The registry owns WHAT A TOOL IS; the loop owns WHAT IT DOES.
A test pins the two together by asserting every registered name has a real
branch and every branch has a registered name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Tuple

TrustTier = Literal["internal", "external"]


@dataclass(frozen=True)
class ToolSpec:
    """Everything the loop needs to know about a tool, apart from its JSON
    schema (which belongs next to the prose description the model reads) and its
    handler."""

    name: str

    #: Where this tool's result originates. The field a reviewer should look at
    #: first when a tool is added.
    trust: TrustTier = "internal"

    #: Does the result carry a genuinely dynamic outcome -- something the model
    #: could not have known when it made the call and might reasonably react to
    #: in the same turn? Only these extend the loop past round 1. Everything
    #: else resolves to a fixed acknowledgment, so an ordinary turn stays a
    #: single round-trip, byte-identical to pre-loop behavior.
    reactable: bool = False

    #: Does firing this end the loop outright, regardless of what else happened
    #: in the same round? True only for terminal handoffs.
    terminal: bool = False

    #: Does this emit nothing at all to the user? Silent writes have an explicit,
    #: tested contract of returning nothing and rendering nothing. Marking them
    #: here lets a test assert that contract against the registry rather than
    #: against a hand-maintained list in the test file.
    silent: bool = False

    #: Does this render output carrying no next step of its own, so the turn
    #: needs a follow-up appended if no real text follows it?
    questionless: bool = False


# ---------------------------------------------------------------------------
# Replace with your own tools. Keep the order matching your schema list -- a
# readability convention, not a correctness requirement.
# ---------------------------------------------------------------------------
_SPECS: Tuple[ToolSpec, ...] = (
    ToolSpec("request_summary"),
    ToolSpec("offer_hint"),
    # Renders output that may carry no next step: needs a follow-up appended.
    # NOT reactable -- nothing about the outcome is dynamic, so it never earns a
    # second round-trip.
    ToolSpec("acknowledge_progress", questionless=True),
    # Genuinely reactable, and the whole reason a loop exists: this can MISS.
    # A hallucinated id used to be a silent no-op the model never learned about.
    ToolSpec("lookup_reference", reactable=True),
    # Terminal: the caller is already handing off, so no further reasoning round.
    ToolSpec("hand_off", terminal=True),
    # Silent write: no output, no return value, no model-visible surface.
    ToolSpec("record_observation", silent=True),
)

TOOL_SPECS: Dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}

# Derived rather than hand-listed, so they cannot drift from the specs above.
# That is the entire point of the module.
REACTABLE_TOOLS = frozenset(s.name for s in _SPECS if s.reactable)
TERMINAL_TOOLS = frozenset(s.name for s in _SPECS if s.terminal)
SILENT_TOOLS = frozenset(s.name for s in _SPECS if s.silent)
QUESTIONLESS_TOOLS = frozenset(s.name for s in _SPECS if s.questionless)

# ---------------------------------------------------------------------------
# Loop bounds. See G06.
# ---------------------------------------------------------------------------

#: Spans every round COMBINED -- never resets per round. A call past this is
#: dropped silently: never executed, never rendered, the turn never interrupted.
#: Log it as its own audit event and alert on it; hitting this is a bug or an
#: attack, never routine.
MAX_TOOL_CALLS_PER_TURN = 6

#: How many model round-trips one response may take. Independent of, and always
#: subordinate to, the call cap above.
MAX_TOOL_LOOP_ROUNDS = 3

#: The fixed result every non-reactable tool resolves to.
TRIVIAL_TOOL_RESULT = {"acknowledged": True}


def get_spec(name: str) -> ToolSpec | None:
    """The spec for a tool the model asked for, or None if it named something
    that is not a registered tool at all.

    Returning None rather than raising is deliberate: a model can emit a
    hallucinated name, and the loop's posture for anything it cannot act on
    should be to drop it quietly rather than fail a real turn. The caller
    decides; this only reports.
    """
    return TOOL_SPECS.get(name)


def is_reactable(name: str) -> bool:
    """Whether this result should extend the loop.

    The default for an unknown name is False. This matters: an unrecognized tool
    must never be able to buy itself extra model round-trips, or the model can
    extend its own budget by inventing a callee.
    """
    spec = TOOL_SPECS.get(name)
    return bool(spec and spec.reactable)


def is_terminal(name: str) -> bool:
    """Whether firing this ends the loop outright. False for unknown names."""
    spec = TOOL_SPECS.get(name)
    return bool(spec and spec.terminal)


def is_silent(name: str) -> bool:
    """Whether this emits nothing to the user. False for unknown names."""
    spec = TOOL_SPECS.get(name)
    return bool(spec and spec.silent)


def is_questionless(name: str) -> bool:
    """Whether this renders output that may carry no next step of its own."""
    spec = TOOL_SPECS.get(name)
    return bool(spec and spec.questionless)


def should_continue_loop(round_number: int, calls_used: int, called_names: list[str]) -> bool:
    """Whether the loop may make another model request.

    Note the third condition, which is easy to get wrong and produces an API
    error rather than a soft failure: if you suppressed a tool_use block for
    exceeding the call cap, you can never send a matching tool_result -- and the
    API requires every tool_use in a turn to be answered before the next
    request. So hitting the call cap must ALSO end the loop.
    """
    if round_number >= MAX_TOOL_LOOP_ROUNDS:
        return False
    if calls_used >= MAX_TOOL_CALLS_PER_TURN:
        return False
    if any(is_terminal(name) for name in called_names):
        return False
    return any(is_reactable(name) for name in called_names)
