"""How far a long reading has got, so the screen can show a progress bar.

Reading a quiz is one request that can take minutes: every group of six pages
is a model call. The browser names the request with a random `progress_id` and
asks `GET .../progress/{id}` about once a second while it waits. This module
holds the answer: how many pages the upload has, how many are read, and what
is happening now.

In memory only, per process, and tiny (four numbers and a word per reading).
Nothing about the pages is kept: no text, no image, no name. An entry is keyed
by who asked as well as the id, so one family cannot read another's progress
even with the id, and it expires a few minutes after its last update. On a
deployment with more than one API process a poll can reach a process that is
not doing the reading; it then answers "unknown", and the screen keeps the
last figure it had rather than going backwards.
"""
from __future__ import annotations

import re
import time
from collections import OrderedDict

TTL_SECONDS = 600
MAX_ENTRIES = 2000
_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_entries: "OrderedDict[tuple[str, str], dict]" = OrderedDict()


def valid_id(progress_id: str | None) -> bool:
    return bool(progress_id) and bool(_ID.match(progress_id))


def owner_of(auth: dict) -> str:
    """Who is asking, from the session, so progress is never shared."""
    who = auth.get("code") or auth.get("sub") or auth.get("principal_id") or ""
    return f"{auth.get('role', '')}:{who}"


def _sweep(now: float) -> None:
    for key in [k for k, v in _entries.items() if now - v["updated"] > TTL_SECONDS]:
        _entries.pop(key, None)
    while len(_entries) > MAX_ENTRIES:
        _entries.popitem(last=False)


def update(owner: str, progress_id: str | None, *, stage: str, done: int = 0, total: int | None = None) -> None:
    if not valid_id(progress_id):
        return
    now = time.monotonic()
    key = (owner, progress_id)
    entry = _entries.get(key) or {"total": None, "done": 0}
    entry.update(stage=stage, done=done, updated=now)
    if total is not None:
        entry["total"] = total
    _entries[key] = entry
    _entries.move_to_end(key)
    _sweep(now)


def read(owner: str, progress_id: str) -> dict | None:
    entry = _entries.get((owner, progress_id))
    if entry is None or time.monotonic() - entry["updated"] > TTL_SECONDS:
        return None
    return {"stage": entry["stage"], "done": entry["done"], "total": entry["total"]}


def reporter(owner: str, progress_id: str | None):
    """A callback for the reader: report(stage, done, total)."""
    if not valid_id(progress_id):
        return None

    def report(stage: str, done: int = 0, total: int | None = None) -> None:
        update(owner, progress_id, stage=stage, done=done, total=total)

    return report


def clear() -> None:
    _entries.clear()


__all__ = ["clear", "owner_of", "read", "reporter", "update", "valid_id"]
