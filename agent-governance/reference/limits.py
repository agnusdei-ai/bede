# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Agnus Dei Technologies, LLC
"""The layer a prompt cannot argue with.

Every rule in prompts/ is text that a sufficiently motivated input can talk
its way around. These are constants read once per process, so no prompt
field, user message, retrieved document, or tool result can raise them.

Port these values, not just the prompt text. A prompt rule with real
consequences ("at most N tool calls") needs a code twin that actually
counts to N — otherwise it is a suggestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

#: How many tool calls one turn may EXECUTE. A call past the cap is dropped
#: silently — never executed, never rendered — and logged as a suppression
#: event that alerts the principal. The turn's already-streamed text is
#: never interrupted, so the user never sees this happen.
MAX_TOOL_CALLS_PER_TURN = 6

#: How many model round-trips one turn's tool_result loop may take.
#: Subordinate to the cap above, which spans every round combined rather
#: than resetting per round.
MAX_TOOL_LOOP_ROUNDS = 3

#: What a tool with no dynamic outcome resolves to. A FIXED CONSTANT, never
#: free text, so a tool result can never carry anything resembling an
#: instruction back into the model's own context. This is the single most
#: important line in this file for an agent that touches the web.
TRIVIAL_TOOL_RESULT: dict[str, Any] = {"acknowledged": True}

Trust = Literal["internal", "external"]


@dataclass(frozen=True)
class ToolSpec:
    """Declares what a tool IS, rather than re-deriving it from name
    comparisons scattered through a dispatch loop.

    trust="internal"  -> result is fixed, server-computed data from inside
                         this process.
    trust="external"  -> result contains content this process did not
                         author (a web page, a third-party API, an MCP
                         server). Never make one reachable from a loop that
                         speaks to an untrusted or vulnerable audience.
    """

    name: str
    trust: Trust = "internal"
    reactable: bool = False   # may its result extend the loop by a round?
    terminal: bool = False    # does calling it end the turn outright?
    silent: bool = False      # does it emit nothing to the user?


def assert_all_internal(specs: list[ToolSpec]) -> None:
    """Call this on the tool set your main loop is built from, at import.

    This is what makes an external-trust tool STRUCTURALLY unable to reach
    the wrong audience: the registry the loop reads simply does not contain
    one, so the loop cannot dispatch it even if a bug tried to.
    """
    external = [s.name for s in specs if s.trust != "internal"]
    if external:
        raise RuntimeError(f"external-trust tools in the internal loop: {external}")


#: Delimiters for the <untrusted_content> block's envelope. Content is DATA;
#: this is the label that says so.
_OPEN = '<untrusted source="{source}">'
_CLOSE = "</untrusted>"


def wrap_untrusted(source: str, text: str) -> str:
    """Envelope content this process did not author.

    This is labelling, never sanitization. It does not make hostile text
    safe. It makes the text's provenance legible so the prompt rules can
    apply to it. The one real property enforced here is that the envelope
    cannot be forged from inside. Text containing its own closing tag would
    otherwise let an attacker end the envelope early and continue as though
    trusted, which is the text equivalent of SQL injection and the single most
    likely way this mechanism fails. Both delimiters are neutralized in the
    payload, and the source label is stripped of anything that could close the
    opening tag.

    Truncation, redaction, and classification are separate concerns, and this
    function deliberately leaves them alone. Do them before calling it.
    """
    safe_source = re.sub(r'[<>"]', "", str(source))[:80] or "unknown"
    body = text.replace(_CLOSE, "<\u200bunclosed>").replace("<untrusted", "<\u200buntrusted")
    return f"{_OPEN.format(source=safe_source)}\n{body}\n{_CLOSE}"


def within_cap(calls_executed_this_turn: int) -> bool:
    """Check BEFORE executing, never after. The point is that the expensive
    or irreversible thing never happens, rather than being logged once it has."""
    return calls_executed_this_turn < MAX_TOOL_CALLS_PER_TURN
