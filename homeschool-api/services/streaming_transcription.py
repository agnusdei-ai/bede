"""
In-memory session state for chunked, server-side streaming transcription —
see routers/voice.py's POST/GET /voice/stream/* endpoints and
docs/VOICE_SETUP.md's "server-side streaming transcription" section.

Replaces browser-native SpeechRecognition as the primary voice-input path.
The client always captures raw mic audio locally (services/transcription.py's
existing faster-whisper backend, already proven reliable — see
useVoiceRecorder.ts) and periodically POSTs the growing buffer here; each
push re-transcribes it and the result is pushed onto a per-session queue the
SSE endpoint drains. This sidesteps WebKit's SpeechRecognition entirely — the
source of essentially every voice-pipeline bug fought this session (audio
session races, instant native failures, stall detection) — at the cost of
periodic (not true word-by-word) partial results, since faster-whisper has no
native incremental-streaming mode.

Sessions are per-process, in-memory only, never persisted to disk or a
database — same "never stored anywhere" privacy property as the one-shot
/transcribe endpoint this augments. Same single-process caveat already
accepted elsewhere in this codebase (see services/voice_synthesis.py's shared
client) — fine for a self-hosted single-family deployment or a modest public
demo; would need a shared store (Redis, etc.) behind a multi-worker/multi-
replica deployment, which this app doesn't run today.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from services.transcription import transcribe_audio

log = logging.getLogger(__name__)

# Generous relative to HOLD_SAFETY_TIMEOUT_MS's 120s client-side hold ceiling
# (useHybridVoiceInput.ts) — this is a backstop for a session that never
# calls /finish at all (a crashed tab, a dropped connection), not a normal
# turn's own timing.
_SESSION_TTL_SECONDS = 180.0
_SWEEP_INTERVAL_SECONDS = 60.0


@dataclass
class _Session:
    language: str = "en"
    audio: bytes = b""
    finished: bool = False
    last_touched: float = field(default_factory=time.monotonic)
    # Set whenever push_chunk/finish_session update state the worker loop
    # hasn't picked up yet — coalesces rapid chunk uploads into "there's
    # newer audio once the current transcription pass finishes" rather than
    # queueing up redundant overlapping whisper calls.
    new_audio: asyncio.Event = field(default_factory=asyncio.Event)
    queue: "asyncio.Queue[dict]" = field(default_factory=asyncio.Queue)
    worker: Optional[asyncio.Task] = None


_sessions: dict[str, _Session] = {}
_sweep_task: Optional[asyncio.Task] = None


def start_session(language: str = "en") -> str:
    session_id = uuid.uuid4().hex
    session = _Session(language=language)
    session.worker = asyncio.create_task(_worker_loop(session_id, session))
    _sessions[session_id] = session
    _ensure_sweeper()
    return session_id


def push_chunk(session_id: str, audio_bytes: bytes) -> bool:
    """Fast and synchronous — never blocks on transcription itself, so chunk
    upload cadence never gets throttled by whisper's own latency. Returns
    False for an unknown or already-finished session (caller 404s)."""
    session = _sessions.get(session_id)
    if session is None or session.finished:
        return False
    session.audio = audio_bytes
    session.last_touched = time.monotonic()
    session.new_audio.set()
    return True


def finish_session(session_id: str) -> bool:
    session = _sessions.get(session_id)
    if session is None or session.finished:
        return False
    session.finished = True
    session.last_touched = time.monotonic()
    session.new_audio.set()
    return True


async def _worker_loop(session_id: str, session: _Session) -> None:
    """One long-running task per session — the only place transcribe_audio()
    is ever called for it, so results can never arrive out of order even
    when chunks upload faster than whisper can keep up."""
    while True:
        await session.new_audio.wait()
        session.new_audio.clear()
        audio_snapshot = session.audio
        is_finished = session.finished
        text = ""
        if audio_snapshot:
            # Elapsed-time log — previously the only visibility into this
            # pipeline was client-side (DebugOverlay), which can show a
            # "Transcribing…" spinner sitting for a long time after release()
            # but has no way to say WHY: whether the final pass itself is
            # just slow on this host's CPU (every pass re-transcribes the
            # WHOLE buffer — see this file's own docstring), or it's queued
            # behind an in-flight partial pass the coalescing design can't
            # cancel. This is the one number that distinguishes the two.
            started_at = time.monotonic()
            try:
                result = await transcribe_audio(audio_snapshot, language=session.language)
                text = result.get("text", "")
            except Exception:
                log.exception("streaming_transcription worker failed for session %s", session_id)
            finally:
                log.info(
                    "streaming_transcription: session=%s pass=%s audio_bytes=%d elapsed=%.2fs",
                    session_id, "final" if is_finished else "partial", len(audio_snapshot),
                    time.monotonic() - started_at,
                )
        await session.queue.put({"type": "final" if is_finished else "partial", "text": text})
        if is_finished:
            await session.queue.put({"type": "done"})
            return


async def events(session_id: str) -> AsyncIterator[dict]:
    """Drained by the SSE endpoint. Self-cleans on normal completion (a
    'done' item) or the consumer disconnecting early (the finally block) —
    the periodic sweep below is only the backstop for a session nobody ever
    reads from at all."""
    session = _sessions.get(session_id)
    if session is None:
        yield {"type": "error", "message": "unknown or expired session"}
        return
    try:
        while True:
            item = await session.queue.get()
            yield item
            if item.get("type") == "done":
                break
    finally:
        _sessions.pop(session_id, None)


def _ensure_sweeper() -> None:
    global _sweep_task
    if _sweep_task is None or _sweep_task.done():
        _sweep_task = asyncio.create_task(_sweep_loop())


async def _sweep_loop() -> None:
    # Exits once idle rather than running forever — start_session restarts
    # it on the next new session, so there's no background task lingering
    # across a quiet stretch with nothing to sweep.
    while _sessions:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        now = time.monotonic()
        stale_ids = [sid for sid, s in _sessions.items() if now - s.last_touched > _SESSION_TTL_SECONDS]
        for sid in stale_ids:
            log.warning("streaming_transcription: sweeping abandoned session %s", sid)
            _sessions.pop(sid, None)
