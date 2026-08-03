"""
Session-scoped mastery estimates, held in memory and never written down.

This is the third diagnostic backend, alongside the persistent one
(services/diagnostic/, real families) and the demo's own
(services/diagnostic_demo.py, public preview). It exists so a deployment
can run the full diagnostic and report what it found WITHOUT keeping a
psychometric claim about a child on disk — see
docs/diagnostic/EPHEMERAL_DIAGNOSTIC_SPEC.md for the position and its
cost, and core/config.py's `retain_mastery_profiles` for the switch.

WHY A SESSION KEY AND NOT A STUDENT NAME. Keying by student_name would be
easier and would quietly recreate exactly what this module removes: a
record that outlives the sitting and accumulates into a profile of the
child. The key is the session, it is minted client-side at startSession(),
and it is deliberately not persisted across a page reload — a reload
starts a new session and a fresh cold-start estimate rather than
resurrecting the old one.

SINGLE PROCESS, IN MEMORY. Same posture and same limitation as
services/streaming_transcription.py, which says so in its own docstring:
this does not survive routing to a different instance under horizontal
scaling. Acceptable for the same reason — a tutoring session is already
pinned to one process by its SSE stream — but stated here rather than
discovered later.

WHY THE TTL IS HOURS AND NOT MINUTES. The parent-facing summary is read
after the session ends, sometimes hours later ("I'll look after lunch").
A 180-second sweep like streaming_transcription's would delete the
estimate before the person it was computed for could read it. Six hours
covers a school day and is gone by the next one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from services.diagnostic import apply_evidence
from services.diagnostic.mastery import (
    CALIBRATION_THRESHOLD,
    MasteryVector,
    build_summary_view,
    calibration_weight_for,
    new_vector,
)

log = logging.getLogger(__name__)

# How long an estimate outlives its session. See the module docstring.
_TTL_SECONDS = 6 * 60 * 60

# A hard ceiling on concurrent sessions held in memory. A pod is at most
# ten students and a household runs one sitting at a time, so this is
# orders of magnitude above any real deployment; it exists so a bug in the
# caller (a new key per turn, say) degrades into eviction rather than
# unbounded growth.
_MAX_SESSIONS = 500

# Per-session ceiling on evidence points. Well above what a two-hour
# sitting produces (see the spec's efficacy section), and again a backstop
# rather than a tuned limit.
_MAX_EVIDENCE_PER_SESSION = 2000


@dataclass
class _SessionEstimate:
    vector: MasteryVector
    evidence_count: int = 0
    subject_area: str = "mathematics"
    touched_at: float = field(default_factory=time.monotonic)


# key: (session_id, subject_area)
_sessions: dict[tuple[str, str], _SessionEstimate] = {}


def _sweep(now: float | None = None) -> int:
    """Drop estimates whose session has gone quiet. Called opportunistically
    on write rather than from a timer, same as core/demo_code_session.py's
    own cleanup — no background task to supervise, and a deployment with no
    traffic has nothing to sweep anyway."""
    now = time.monotonic() if now is None else now
    stale = [k for k, v in _sessions.items() if now - v.touched_at > _TTL_SECONDS]
    for k in stale:
        del _sessions[k]
    return len(stale)


async def record(
    session_id: str,
    grade_band: str,
    probe_id: str,
    outcome: str,
    confidence: float = 1.0,
    subject_area: str = "mathematics",
) -> None:
    """
    Fold one piece of evidence into this session's estimate.

    Cold-starts the vector on first evidence, which is the honest default
    here: with nothing retained there is no prior to load, so every session
    begins from what is typical for the grade band.
    """
    _sweep()
    key = (session_id, subject_area)
    est = _sessions.get(key)
    if est is None:
        if len(_sessions) >= _MAX_SESSIONS:
            # Evict the least recently touched rather than refusing to
            # record — a diagnostic hiccup must never affect the lesson.
            oldest = min(_sessions, key=lambda k: _sessions[k].touched_at)
            del _sessions[oldest]
            log.warning("diagnostic_session: at capacity, evicted the least recent estimate")
        est = _SessionEstimate(vector=new_vector(grade_band), subject_area=subject_area)
        _sessions[key] = est

    if est.evidence_count >= _MAX_EVIDENCE_PER_SESSION:
        log.warning("diagnostic_session: evidence ceiling reached for this session, ignoring further evidence")
        return

    # calibration_weight_for damps early evidence exactly as the
    # persistent path does, so a session-scoped estimate is not more
    # confident than a stored one would have been on the same evidence.
    est.vector, _updates = await apply_evidence(
        est.vector, probe_id, outcome, confidence,
        calibration_weight=calibration_weight_for(est.evidence_count),
    )
    est.evidence_count += 1
    est.touched_at = time.monotonic()


async def summary(session_id: str, student_name: str, subject_area: str = "mathematics") -> dict | None:
    """The parent-facing view of this session's estimate, or None when this
    session produced no evidence for this subject. None is meaningfully
    different from an empty summary: it means nothing was observed, not
    that nothing was mastered."""
    _sweep()
    est = _sessions.get((session_id, subject_area))
    if est is None:
        return None
    return build_summary_view(
        est.vector,
        student_name,
        subject_area,
        est.evidence_count,
        CALIBRATION_THRESHOLD,
        "",  # No stored timestamp: this estimate covers the current session only.
    )


def live_vector(session_id: str, subject_area: str = "mathematics") -> tuple[dict | None, int]:
    """The raw vector and evidence count for prompt injection, shaped to
    match _load_mastery_vector_readonly's return so the two are drop-in
    alternatives at the call site. (None, 0) for a session with no evidence
    yet, which is a genuine cold start rather than an error."""
    _sweep()
    est = _sessions.get((session_id, subject_area))
    if est is None:
        return None, 0
    return dict(est.vector), est.evidence_count


def discard(session_id: str) -> int:
    """Drop every estimate for a session. Called when a session ends, so the
    estimate goes at the moment it stops being needed rather than waiting
    out the TTL."""
    keys = [k for k in _sessions if k[0] == session_id]
    for k in keys:
        del _sessions[k]
    return len(keys)


def active_session_count() -> int:
    """Introspection for tests and diagnostics. Deliberately returns a count
    and never the estimates themselves: nothing outside this module should
    be able to enumerate what is being held."""
    _sweep()
    return len(_sessions)


def _reset_for_tests() -> None:
    _sessions.clear()
