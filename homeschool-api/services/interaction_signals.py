"""
Aggregated, anonymized interaction-pattern signals from demo sessions only
(services/diagnostic_demo.py's counterpart for tutoring-flow structure,
not skill mastery) — recorded so a human can periodically export and
review which teaching patterns (tool usage, turn counts, subject
completions) correlate with longer or more productive sessions, per the
user's own request. Never touches parent/child production sessions.

Privacy design, matching this codebase's established conventions:
  - Structural signals only — which tool fired, how many turns, whether a
    subject was completed. NEVER the conversation content itself (not the
    child's words, not Bede's replies, not probe text).
  - The row key is a keyed HMAC-SHA256 of the demo code (see _session_token
    below), not the code itself — same reasoning as
    core/diagnostic_preview_quota.py's _hash_ip: equality-filterable (the
    same code always hashes the same, so counts accumulate correctly
    within one session) but unreversible, and unjoinable to
    DemoCodeSession's optional student_name/grade columns.
  - Gated by settings.interaction_signal_logging_enabled (on by default for
    demo sessions, disclosed in the demo's own consent copy) so an operator
    can turn it off entirely.
  - Best-effort throughout: every public function catches and logs its own
    exceptions rather than raising — a signal-recording hiccup must never
    break a child's tutoring turn, matching _record_skill_evidence's own
    defensive convention.
"""

import hashlib
import hmac as hmac_module
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)

# Hygiene only, not a security boundary — bounds how long aggregated
# signal rows live before scripts/export_interaction_signals.py's periodic
# purge removes them. Independent of (and much longer than)
# DemoCodeSession's own _CODE_TTL_SECONDS, since this table exists
# specifically to survive past one session so patterns can be compared
# across many of them later.
_RETENTION_DAYS = 30

_EMPTY_SIGNALS = {
    "tool_counts": {},
    "subjects_visited": [],
    "subjects_completed": [],
    "turn_count": 0,
    "silence_continues_fired": 0,
    "first_event_at": None,
    "last_event_at": None,
}


def _session_token(demo_code: str) -> str:
    """Keyed HMAC-SHA256 of the demo code, domain-separated with a fixed
    prefix so this can never collide with core/diagnostic_preview_quota.py's
    _hash_ip tokens even though both key on the same settings.secret_key.
    Same code always produces the same token (so a session's counts
    accumulate correctly across multiple calls), but the token can't be
    reversed back to the code without the server's own secret."""
    return hmac_module.new(
        settings.secret_key.encode("utf-8"),
        f"interaction_signal:{demo_code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def record_signal(
    demo_code: Optional[str],
    event_type: str,
    subject_area: Optional[str] = None,
) -> None:
    """
    Increment one structural signal for this demo session. event_type is
    one of: "turn" (once per tutoring turn), a tool name (e.g.
    "offer_socratic_hint", "celebrate_discovery"), "silence_continue" (the
    [CONTINUE] sentinel fired), or "subject_complete". No-op when
    demo_code is None (parent/child sessions never reach this — every
    call site gates on demo_code being set) or when logging is disabled.

    Best-effort: any failure (DB hiccup, encryption error) is logged and
    swallowed, never raised — this must never interrupt a child's turn.
    """
    if not demo_code or not settings.interaction_signal_logging_enabled:
        return
    try:
        await _record_signal_unsafe(demo_code, event_type, subject_area)
    except Exception as exc:
        log.warning("Interaction-signal record failed (event=%s): %s", event_type, exc)


async def _record_signal_unsafe(demo_code: str, event_type: str, subject_area: Optional[str]) -> None:
    from sqlalchemy import select

    from core.database import AsyncSessionLocal, DemoInteractionSignal
    from core.encryption import decrypt_json, encrypt_json

    token = _session_token(demo_code)
    now_iso = datetime.now(timezone.utc).isoformat()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DemoInteractionSignal).where(DemoInteractionSignal.session_token == token)
        )
        row = result.scalar_one_or_none()

        try:
            signals = dict(_EMPTY_SIGNALS) if row is None else decrypt_json(row.signals_enc)
        except Exception:
            # A corrupted row degrades to a fresh one rather than blocking
            # this session's signals forever — same convention as
            # process_evidence's own corrupted-row handling.
            signals = dict(_EMPTY_SIGNALS)

        signals.setdefault("tool_counts", {})
        signals.setdefault("subjects_visited", [])
        signals.setdefault("subjects_completed", [])
        signals.setdefault("turn_count", 0)
        signals.setdefault("silence_continues_fired", 0)

        if event_type == "turn":
            signals["turn_count"] += 1
        elif event_type == "silence_continue":
            signals["silence_continues_fired"] += 1
        elif event_type == "subject_complete":
            if subject_area and subject_area not in signals["subjects_completed"]:
                signals["subjects_completed"].append(subject_area)
        else:
            # A tool name — request_narration, offer_socratic_hint,
            # celebrate_discovery, invite_handwriting, connect_to_faith,
            # show_visual_aid, suggest_next_subject. Never record_skill_evidence
            # or assess_narration's own inputs — only that a tool fired.
            signals["tool_counts"][event_type] = signals["tool_counts"].get(event_type, 0) + 1

        if subject_area and subject_area not in signals["subjects_visited"]:
            signals["subjects_visited"].append(subject_area)

        if signals.get("first_event_at") is None:
            signals["first_event_at"] = now_iso
        signals["last_event_at"] = now_iso

        signals_enc = encrypt_json(signals)
        if row is None:
            db.add(DemoInteractionSignal(session_token=token, signals_enc=signals_enc))
        else:
            row.signals_enc = signals_enc

        await db.commit()


async def purge_old_signals() -> int:
    """Deletes signal rows older than _RETENTION_DAYS. Meant to be called
    periodically by scripts/export_interaction_signals.py, not on the hot
    tutoring path. Returns the number of rows deleted."""
    from sqlalchemy import delete

    from core.database import AsyncSessionLocal, DemoInteractionSignal

    cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(DemoInteractionSignal).where(DemoInteractionSignal.created_at < cutoff)
        )
        await db.commit()
        return result.rowcount
