"""One lesson turn records each piece of the child's work once, however many
times the tablet sends it.

``homeschool-tutor/src/services/api.ts``'s ``streamTutorChat`` retries a turn
whose connection failed before any of Bede's reply reached the tablet (up to
six attempts over about 25 seconds). That is right for the child, who would
otherwise lose their answer. It was not right for the record. The server saves
the child's work WHILE it builds the reply: skill evidence, the work ledger, a
narration's rubric scores, the learning-style counter. A retry that reached the
server after an earlier attempt had already saved something saved it again, and
the parent's Progress page showed work done once as work done twice.

So the client sends a ``turn_id``, minted once per turn and reused by every
retry, and every save in the turn goes through an ``EvidenceGate``:

* **Per effect, not per turn.** Each save is named for what it records: one
  skill's evidence, the narration's scores, the learning-style counter. A turn
  that saved the skill evidence and then dropped before saving the narration
  leaves the narration open: the retry saves it. The first version of this
  claimed the whole turn at the first save, so that narration was silently
  lost.
* **Marked only once it actually saved.** A save that failed (the save
  functions report it) or never ran leaves its effect open for the retry.
* **Overlapping attempts take turns.** If another attempt is in the middle of
  the same save, a retry waits for it to finish (up to ``WAIT_SECONDS``) and
  then skips it if it saved, or saves it if it did not. Without the wait, two
  attempts racing on one save would both write.
* **A retry reports what was saved, never something new.** A skipped narration
  hands back the summary the earlier attempt actually saved, so neither the
  screen nor the model is told about scores that were never stored.

What a retry does NOT do: an effect already saved by an earlier attempt is not
saved again even if the retry's model produced a different value for it (the
same skill, a different outcome). The first saved observation stands, since the
child answered once. A different skill in the retry is a different effect, and
is saved.

No turn id (older clients, the sandbox, scripts, the public demo) means no
gate: every attempt saves, exactly as before. The key includes who is speaking,
so one caller cannot suppress another's record by sending their turn id.

Like ``services/streaming_transcription.py``'s voice sessions, this is held in
this process's memory for ``CLAIM_TTL_SECONDS``. A retry that reaches a
different process, or arrives after a restart, is not recognised and saves
again: the old behavior, not a new failure. Both supported deployments run one
process. See docs/RELIABILITY.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# Long enough to outlast the client's whole retry budget (~25 seconds) many
# times over; short enough that the table holds only minutes of turns.
CLAIM_TTL_SECONDS = 600
# Bounds memory if something sends turn ids in a loop; far above real use.
MAX_TURNS = 5000
# How long a retry waits for another attempt that is mid-save. A save is a few
# database writes; this is generous.
WAIT_SECONDS = 15.0


@dataclass
class _Effect:
    token: str
    saved: bool = False
    result: Any = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class _Turn:
    expiry: float
    effects: dict[str, _Effect] = field(default_factory=dict)


_turns: "OrderedDict[str, _Turn]" = OrderedDict()


def _sweep(now: float) -> None:
    while _turns:
        key, turn = next(iter(_turns.items()))
        if turn.expiry > now and len(_turns) <= MAX_TURNS:
            break
        _turns.popitem(last=False)


def effect_name(tool_name: str, tool_input: Optional[dict] = None) -> str:
    """The name of what a save records. One skill, domain or language is one
    effect; the narration's scores and the learning-style counter are one each
    per turn."""
    ti = tool_input or {}
    for field_name in ("probe_id", "domain", "language"):
        value = ti.get(field_name)
        if isinstance(value, str) and value:
            return f"{tool_name}:{value}"
    return tool_name


class Claim:
    """One attempt's right to perform one save, or the record that another
    attempt already did. Always ``finish()`` it."""

    def __init__(self, gate: "EvidenceGate", name: str, allowed: bool, prior: Any = None):
        self._gate = gate
        self._name = name
        self.allowed = allowed
        #: For a skipped save: what the attempt that saved it returned.
        self.prior = prior
        self._finished = not allowed

    def finish(self, saved: bool, result: Any = None) -> None:
        if self._finished:
            return
        self._finished = True
        self._gate._finish(self._name, saved, result)


class EvidenceGate:
    """Decides, for one attempt of one turn, which saves it may perform."""

    def __init__(self, key: Optional[str]) -> None:
        self._key = key
        self._token = secrets.token_hex(8)

    @property
    def tracked(self) -> bool:
        return self._key is not None

    def _turn(self) -> _Turn:
        now = time.monotonic()
        _sweep(now)
        turn = _turns.get(self._key)
        if turn is None:
            turn = _Turn(expiry=now + CLAIM_TTL_SECONDS)
            _turns[self._key] = turn
        return turn

    async def claim(self, name: str) -> Claim:
        if self._key is None:
            return Claim(self, name, allowed=True)
        turn = self._turn()
        held = turn.effects.get(name)
        if held is not None and held.token != self._token and not held.done.is_set():
            # Another attempt is mid-save. Wait for it to finish, then decide.
            try:
                await asyncio.wait_for(held.done.wait(), timeout=WAIT_SECONDS)
            except asyncio.TimeoutError:
                log.warning("turn_replay: another attempt is still saving %s; skipping it here", name.split(":")[0])
                return Claim(self, name, allowed=False)
            held = turn.effects.get(name)
        if held is not None and held.saved and held.token != self._token:
            return Claim(self, name, allowed=False, prior=held.result)
        if held is not None and held.token == self._token:
            # This attempt saving the same thing again within its own turn
            # (one skill observed twice): allowed, and a failure the second
            # time must not erase the record that the first one saved.
            return Claim(self, name, allowed=True)
        # Free: never claimed, or the earlier attempt's save failed.
        turn.effects[name] = _Effect(token=self._token)
        return Claim(self, name, allowed=True)

    def _finish(self, name: str, saved: bool, result: Any) -> None:
        if self._key is None:
            return
        turn = _turns.get(self._key)
        effect = turn.effects.get(name) if turn else None
        if effect is None or effect.token != self._token:
            return
        if saved:
            effect.saved = True
            effect.result = result
        elif not effect.saved:
            del turn.effects[name]
        effect.done.set()


def gate_for(owner: str, turn_id: Optional[str]) -> EvidenceGate:
    """The gate for one attempt. ``owner`` names who is speaking (role plus
    student or demo code); ``turn_id`` is the client's id for the turn."""
    if not turn_id:
        return EvidenceGate(None)
    return EvidenceGate(json.dumps([owner, turn_id]))


def always_record() -> EvidenceGate:
    """For callers that have no turn id at all."""
    return EvidenceGate(None)


def _reset_for_tests() -> None:
    _turns.clear()
