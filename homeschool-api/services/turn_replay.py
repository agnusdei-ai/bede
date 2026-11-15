"""One lesson turn records the child's work once, however many times it is sent.

``homeschool-tutor/src/services/api.ts``'s ``streamTutorChat`` retries a turn
whose connection failed before any of Bede's reply reached the tablet (up to
six attempts over about 25 seconds). That retry is right for the child, who
would otherwise lose their answer. It was not right for the record. The
server saves the child's work WHILE it builds the reply: skill evidence, the
work ledger, a narration's rubric scores, the learning-style counters. A
connection that dropped after the first attempt had saved something, but
before any of the reply reached the tablet, sent the same turn again, and the
second attempt saved it all a second time. Nothing errored; the parent's
Progress page simply showed work the child did once as work done twice.

So the client now sends a ``turn_id``, minted once per turn and reused by
every retry of it, and the server lets exactly ONE attempt of a turn record
anything. The first attempt that reaches a write claims the turn; any other
attempt of the same turn still answers the child in full and records
nothing. Claiming at the first WRITE, rather than when the request arrives,
is deliberate: an attempt that failed before it saved anything (the model
errored, the stream stalled) must not stop the retry from saving the work.

Three properties, each pinned by ``tests/test_turn_replay.py``:

* **No turn id, no change.** An older client, the sandbox, a script, and
  the public demo send none, and every attempt records exactly as before.
* **Keyed by who is speaking as well as the turn id.** A turn id is a random
  value from the client, so one caller cannot suppress another's record by
  sending their id.
* **Claim and check are one step.** There is no ``await`` between them, so
  two attempts of one turn interleaving on the event loop cannot both win.

Like ``services/streaming_transcription.py``'s voice sessions, the claims are
held in this process's memory. A retry that reaches a different replica, or
arrives after a restart, is not recognised and records again, which is the
old behaviour rather than a new failure. Both supported deployments run a
single process.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from typing import Optional

# Long enough to outlast the client's whole retry budget
# (TUTOR_RETRY_BUDGET_MS, ~25 seconds) many times over; short enough that the
# table never holds more than a few minutes of turns.
CLAIM_TTL_SECONDS = 600
# A household sends a turn every few seconds at most, so this is far above any
# real load; it only bounds memory if something sends turn ids in a loop.
MAX_CLAIMS = 5000

# key -> (attempt token that owns the turn, expiry on the monotonic clock)
_claims: "OrderedDict[str, tuple[str, float]]" = OrderedDict()


def _sweep(now: float) -> None:
    while _claims:
        key, (_, expiry) = next(iter(_claims.items()))
        if expiry > now and len(_claims) <= MAX_CLAIMS:
            break
        _claims.popitem(last=False)


class EvidenceGate:
    """Decides, for one attempt of one turn, whether it may record anything.

    Created once per request. ``may_record()`` is asked before every write;
    the first time it is asked on a turn nobody has claimed, it claims the
    turn for this attempt and answers True from then on.
    """

    def __init__(self, key: Optional[str]) -> None:
        self._key = key
        self._token = secrets.token_hex(8)

    @property
    def tracked(self) -> bool:
        return self._key is not None

    def may_record(self) -> bool:
        if self._key is None:
            return True
        now = time.monotonic()
        _sweep(now)
        held = _claims.get(self._key)
        if held is None:
            _claims[self._key] = (self._token, now + CLAIM_TTL_SECONDS)
            return True
        return held[0] == self._token


def gate_for(owner: str, turn_id: Optional[str]) -> EvidenceGate:
    """The gate for one attempt. ``owner`` names who is speaking (role plus
    student or demo code); ``turn_id`` is the client's id for the turn."""
    if not turn_id:
        return EvidenceGate(None)
    return EvidenceGate(f"{owner}\x1f{turn_id}")


def always_record() -> EvidenceGate:
    """For callers that have no turn id at all."""
    return EvidenceGate(None)


def _reset_for_tests() -> None:
    _claims.clear()
