"""The public demo's Practice Coach workspace: in memory, per demo code, gone
with the session. NO DATABASE, no file.

The real feature stores a reading and a practice set in two encrypted,
student-keyed tables (services/practice/store.py). A demo visitor has no
student, and the demo's retention promise is that nothing outlives the
session, so none of that is reused: the reading, the diagnosis's inputs and
the draft practice set live in the dict below, keyed by the demo code, and
nowhere else. Photos are never held at all, here or anywhere (the request
that carries them ends when the response does).

Eviction, three ways, all pinned by tests/test_practice_demo.py:

* **Logout.** `core/demo_code_session.py`'s `end_session()` calls `discard()`.
* **Code expiry sweep.** `generate_code()` calls `sweep()` beside the SQL
  deletes it already runs, and every access sweeps opportunistically as
  well, the same lazy shape `services/diagnostic_session.py` uses.
* **TTL.** A workspace older than `TTL_SECONDS` (the same six hours a demo
  code lives, asserted equal to `core/demo_code_session.py`'s) is treated as
  absent and removed, whichever of the above reaches it first.

Single process, in memory: this does not survive a restart and is not shared
between instances under horizontal scaling, the same stated limitation as
`services/streaming_transcription.py` and `services/diagnostic_session.py`.
The visible consequence is benign (a restart empties the workspace and
resets that code's upload count), and the per-IP rate limiter plus the
process-wide hourly ceiling below still bound spend.

The upload counters live here too, and that is a deliberate choice rather
than an omission: a counter column on `demo_code_sessions` would need an
`ALTER TABLE` this codebase has no path for, and a new table is exactly
what this feature promised not to add. What a restart costs is covered by
the global ceiling, which is the denial-of-wallet backstop.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from models.practice import GradedAssessment, PracticeSet

TTL_SECONDS = 6 * 60 * 60

# Per demo code. A preview, not a free substitute for the product: three
# uploads is enough to read a quiz, correct a misreading and try a second
# subject, and the page cap keeps each one's model cost small.
MAX_UPLOADS_PER_CODE = 3
MAX_PAGES_PER_UPLOAD = 3
MAX_SETS_PER_CODE = 6

# Process-wide, across every code: the backstop for a visitor who mints many
# codes (each gets its own three) or for a restart that resets a count.
MAX_UPLOADS_PER_HOUR_GLOBAL = 60
_GLOBAL_WINDOW_SECONDS = 60 * 60

# Same ceiling core/demo_code_session.py puts on live codes; a bug that keyed
# the store by something else degrades into eviction, not unbounded growth.
_MAX_WORKSPACES = 500


@dataclass
class _Reading:
    assessment: GradedAssessment
    status: str  # needs_review | confirmed


@dataclass
class _Set:
    practice_set: PracticeSet
    summary: str
    status: str = "draft"  # draft | approved | discarded


@dataclass
class _Workspace:
    created_at: float
    uploads_used: int = 0
    next_id: int = 1
    readings: dict[int, _Reading] = field(default_factory=dict)
    sets: dict[int, _Set] = field(default_factory=dict)

    def take_id(self) -> int:
        n, self.next_id = self.next_id, self.next_id + 1
        return n


_workspaces: dict[str, _Workspace] = {}
_global_uploads: deque[float] = deque()


def _expired(ws: _Workspace, now: float) -> bool:
    return now - ws.created_at > TTL_SECONDS


def sweep(now: Optional[float] = None) -> int:
    """Drop every workspace past its TTL. Returns how many went."""
    now = time.monotonic() if now is None else now
    stale = [code for code, ws in _workspaces.items() if _expired(ws, now)]
    for code in stale:
        del _workspaces[code]
    return len(stale)


def discard(code: str) -> None:
    """Logout: forget everything held for this code. Safe for an unknown one."""
    _workspaces.pop(code, None)


def clear_all() -> None:
    """Test hook and shutdown helper: forget every workspace and the global window."""
    _workspaces.clear()
    _global_uploads.clear()


def has_workspace(code: str) -> bool:
    return code in _workspaces and not _expired(_workspaces[code], time.monotonic())


def _workspace(code: str, *, create: bool) -> Optional[_Workspace]:
    now = time.monotonic()
    sweep(now)
    ws = _workspaces.get(code)
    if ws is None and create:
        if len(_workspaces) >= _MAX_WORKSPACES:
            oldest = min(_workspaces, key=lambda c: _workspaces[c].created_at)
            del _workspaces[oldest]
        ws = _workspaces[code] = _Workspace(created_at=now)
    return ws


# ── Quota ─────────────────────────────────────────────────────────────────────

def uploads_remaining(code: str) -> int:
    ws = _workspace(code, create=False)
    return MAX_UPLOADS_PER_CODE - (ws.uploads_used if ws else 0)


def _global_room(now: float) -> bool:
    while _global_uploads and now - _global_uploads[0] > _GLOBAL_WINDOW_SECONDS:
        _global_uploads.popleft()
    return len(_global_uploads) < MAX_UPLOADS_PER_HOUR_GLOBAL


def reserve_upload(code: str) -> Optional[str]:
    """Claim one upload BEFORE any model call. Returns None on success, or the
    reason it was refused: "code" (this demo code has used its uploads) or
    "global" (the whole demo is at its hourly ceiling).

    Synchronous with no await between the check and the increment, so two
    concurrent requests cannot both take the last slot."""
    ws = _workspace(code, create=True)
    now = time.monotonic()
    if ws.uploads_used >= MAX_UPLOADS_PER_CODE:
        return "code"
    if not _global_room(now):
        return "global"
    ws.uploads_used += 1
    _global_uploads.append(now)
    return None


def release_upload(code: str) -> None:
    """Give a slot back when the request ended before any model was called
    (a refused file, no provider): the visitor should not pay for our refusal."""
    ws = _workspaces.get(code)
    if ws is not None and ws.uploads_used > 0:
        ws.uploads_used -= 1
        if _global_uploads:
            _global_uploads.pop()


# ── Readings and sets ─────────────────────────────────────────────────────────

class LimitReached(Exception):
    pass


def save_reading(code: str, assessment: GradedAssessment, status: str) -> int:
    ws = _workspace(code, create=True)
    rid = ws.take_id()
    ws.readings[rid] = _Reading(assessment, status)
    return rid


def load_reading(code: str, reading_id: int) -> Optional[_Reading]:
    ws = _workspace(code, create=False)
    return ws.readings.get(reading_id) if ws else None


def replace_reading(code: str, reading_id: int, assessment: GradedAssessment, status: str) -> None:
    ws = _workspace(code, create=False)
    if ws is not None and reading_id in ws.readings:
        ws.readings[reading_id] = _Reading(assessment, status)


def save_set(code: str, practice: PracticeSet, summary: str) -> int:
    ws = _workspace(code, create=True)
    if len(ws.sets) >= MAX_SETS_PER_CODE:
        raise LimitReached("This demo keeps a few practice sets at a time.")
    sid = ws.take_id()
    ws.sets[sid] = _Set(practice, summary)
    return sid


def load_set(code: str, set_id: int) -> Optional[_Set]:
    ws = _workspace(code, create=False)
    return ws.sets.get(set_id) if ws else None


def decide_set(code: str, set_id: int, status: str, practice: Optional[PracticeSet] = None) -> None:
    found = load_set(code, set_id)
    if found is None:
        return
    if practice is not None:
        found.practice_set = practice
    found.status = status
