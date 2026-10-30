"""
Keeps a child's name and a child's own words out of application logs.

COPPA readiness C-15 / C-16. Operational logs are written by the container
runtime and often shipped off-host and kept for longer than the data they
describe, so a first name or a message fragment written there outlives the
deletion the parent asked for. The rule is:

* A learner is referred to by `learner_ref()`: a keyed HMAC of the name,
  stable for the life of one deployment's SECRET_KEY, so an operator can see
  that two log lines concern the same learner without seeing who it is.
* An exception is logged as `exc_text()` (its type, with any learner name it
  carries scrubbed) or, on a child-facing path where the exception may carry
  the child's own words, as `exc_summary()`: type and location only, never
  the message and never a traceback.

Deliberately not a blunt logging filter. A filter cannot know which
fragments of a message are a child's, and a filter that tries to recognise
them is a second, weaker copy of the call-site discipline. The static guard
in tests/test_log_redaction.py enforces the call-site discipline instead.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import traceback
from typing import Iterable, Optional

_LABEL = "bede/log-redaction/v1/learner"
_MIN_SECRET_LENGTH = 2
_EXC_TEXT_LIMIT = 300


def _key() -> bytes:
    from core.config import settings

    return hmac.new(
        settings.secret_key.encode("utf-8"), _LABEL.encode("utf-8"), hashlib.sha256
    ).digest()


def learner_ref(name: Optional[str]) -> str:
    """A stable, non-reversible reference to one learner for log lines."""
    if not name:
        return "learner:none"
    digest = hmac.new(_key(), name.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    return f"learner:{digest}"


def scrub(text: str, secrets: Iterable[Optional[str]]) -> str:
    """Replace every occurrence of each secret (case-insensitively) with its
    learner reference. Longest secrets first, so a name inside a longer
    string is not half-replaced."""
    found = {s for s in secrets if s and len(s) >= _MIN_SECRET_LENGTH}
    out = text
    for secret in sorted(found, key=len, reverse=True):
        out = re.sub(re.escape(secret), learner_ref(secret), out, flags=re.IGNORECASE)
    return out


def exc_text(exc: BaseException, *secrets: Optional[str]) -> str:
    """The exception's type and message, with the given learner names
    scrubbed. For paths where the message cannot carry child-supplied text
    but may carry a learner's name (for example a SQL parameter)."""
    text = f"{type(exc).__name__}: {scrub(str(exc), secrets)}"
    return text[:_EXC_TEXT_LIMIT]


def exc_summary(exc: BaseException) -> str:
    """The exception's type and the innermost frame where it was raised.
    No message, no traceback. For child-facing paths, where the message may
    contain the child's own words (an echoed model reply, a parsed field)."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return type(exc).__name__
    last = frames[-1]
    return f"{type(exc).__name__} at {os.path.basename(last.filename)}:{last.lineno} in {last.name}"
