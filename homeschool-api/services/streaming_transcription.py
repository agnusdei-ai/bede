"""
In-memory session state for chunked, server-side streaming transcription —
see routers/voice.py's POST/GET /voice/stream/* endpoints and
docs/VOICE_SETUP.md's "server-side streaming transcription" section.

Replaces browser-native SpeechRecognition as the primary voice-input path.
The client always captures raw mic audio locally (services/transcription.py's
existing faster-whisper backend, already proven reliable — see
useVoiceRecorder.ts) and periodically POSTs only what it captured since its
last upload — a delta, as raw headerless PCM, not the whole growing buffer
(that was the original design; see push_chunk's own docstring for why it
changed and how an older client uploading the whole buffer still works
against this server). Each push re-transcribes the accumulated audio and the
result is pushed onto a per-session queue the SSE endpoint drains. This
sidesteps WebKit's SpeechRecognition entirely — the source of essentially
every voice-pipeline bug fought this session (audio session races, instant
native failures, stall detection) — at the cost of periodic (not true
word-by-word) partial results, since faster-whisper has no native
incremental-streaming mode, and every pass re-transcribes the accumulated
audio from the start rather than resuming (see VOICE_PARTIAL_MAX_SECONDS in
core/config.py for how that cost is bounded on a long hold).

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

from core.config import settings
from services.transcription import partial_passes_are_affordable, transcribe_audio

log = logging.getLogger(__name__)

# Generous relative to HOLD_SAFETY_TIMEOUT_MS's 120s client-side hold ceiling
# (useHybridVoiceInput.ts) — this is a backstop for a session that never
# calls /finish at all (a crashed tab, a dropped connection), not a normal
# turn's own timing.
# The delta protocol carries bare int16 samples with no container, so this
# module owns the one place that gives them one. Fixed at 16kHz mono because
# useVoiceRecorder.ts resamples to exactly that before uploading, and
# services/transcription.py reads via soundfile, which needs a real container
# rather than loose samples.
_PCM_SAMPLE_RATE = 16000
_PCM_BYTES_PER_SAMPLE = 2


def _wav_from_pcm16(pcm: bytes) -> bytes:
    """Wrap raw 16kHz mono int16 PCM in a minimal 44-byte WAV header."""
    import struct

    byte_rate = _PCM_SAMPLE_RATE * _PCM_BYTES_PER_SAMPLE
    return b"".join((
        b"RIFF", struct.pack("<I", 36 + len(pcm)), b"WAVEfmt ",
        struct.pack("<IHHIIHH", 16, 1, 1, _PCM_SAMPLE_RATE, byte_rate,
                    _PCM_BYTES_PER_SAMPLE, 8 * _PCM_BYTES_PER_SAMPLE),
        b"data", struct.pack("<I", len(pcm)), pcm,
    ))


_SESSION_TTL_SECONDS = 180.0
_SWEEP_INTERVAL_SECONDS = 60.0


@dataclass
class _Session:
    language: str = "en"
    # Which authenticated identity started this session (routers/voice.py's
    # _stream_owner — auth["code"] for a demo visitor, auth["role"]
    # otherwise). session_id is already a random 122-bit token, but nothing
    # previously stopped a second authenticated caller who somehow learned
    # another session's id from reading its chunks or transcript — matters
    # most for the demo, where many independent concurrent visitors share
    # one role and instance. Defaults to "" so every pre-existing caller
    # that never passed an owner (this file's own test suite) keeps working
    # unchanged — "" on both sides still compares equal.
    owner: str = ""
    # Legacy path: a complete WAV of everything captured so far, replaced on
    # every push. Still supported so an older client keeps working — see
    # push_chunk.
    audio: bytes = b""
    # Delta path: raw 16kHz mono int16 PCM, APPENDED to on every push. The
    # client sends only what it captured since its last upload, which is what
    # keeps a long hold from re-uploading the whole recording over and over.
    pcm: bytearray = field(default_factory=bytearray)
    finished: bool = False
    last_touched: float = field(default_factory=time.monotonic)
    # Set whenever push_chunk/finish_session update state the worker loop
    # hasn't picked up yet — coalesces rapid chunk uploads into "there's
    # newer audio once the current transcription pass finishes" rather than
    # queueing up redundant overlapping whisper calls.
    new_audio: asyncio.Event = field(default_factory=asyncio.Event)
    queue: "asyncio.Queue[dict]" = field(default_factory=asyncio.Queue)
    worker: Optional[asyncio.Task] = None
    # True from the moment one events() call attaches until it detaches (see
    # events() below). Guards against a SECOND concurrent events() call for
    # the same session — reported live from the demo under real mobile
    # network conditions: a client that has already sent its final chunk and
    # a successful /finish still sees its own, still-open events() stream
    # come back with "unknown or expired session" moments later, even though
    # the session plainly still existed (finish_session() just found it).
    # Deployment was confirmed pinned to a single instance, which rules out
    # cross-instance session loss (the previously-diagnosed cause this
    # module's docstring and CLAUDE.md describe). The only other way
    # _discard() can run out from under a session that's still mid-turn is a
    # SECOND events() attach for the same id racing the first on the same
    # asyncio.Queue — whichever of the two consumers happens to receive the
    # queue's "done" item tears the session down in its own finally block,
    # discarding it out from under the other. A retried HTTP request for the
    # same logical GET (a mobile network/proxy retrying what looks like a
    # stalled connection under poor signal — exactly the conditions in the
    # reported trace) is the most likely way a second attach happens; this
    # guards the outcome regardless of what triggers it.
    active_reader: bool = False


_sessions: dict[str, _Session] = {}
_sweep_task: Optional[asyncio.Task] = None


def start_session(language: str = "en", owner: str = "") -> str:
    session_id = uuid.uuid4().hex
    session = _Session(language=language, owner=owner)
    session.worker = asyncio.create_task(_worker_loop(session_id, session))
    _sessions[session_id] = session
    _ensure_sweeper()
    return session_id


def push_chunk(session_id: str, audio_bytes: bytes, owner: str = "") -> bool:
    """Fast and synchronous — never blocks on transcription itself, so chunk
    upload cadence never gets throttled by whisper's own latency. Returns
    False for an unknown or already-finished session, OR a real session
    started by a DIFFERENT owner (caller 404s either way — an ownership
    mismatch must never be distinguishable from the session simply not
    existing, or it becomes an oracle for probing valid session ids)."""
    session = _sessions.get(session_id)
    if session is None or session.finished or session.owner != owner:
        return False
    # Two wire protocols, told apart by the container rather than by a flag,
    # so an older client and a newer one can both talk to this server.
    #
    # A RIFF header means the legacy whole-buffer upload: the client re-sent
    # everything it has captured so far, so replace. That is O(N^2) bandwidth
    # over a hold — 8.3MB of upload for a 40-second answer — which is exactly
    # what the delta path below exists to stop.
    #
    # No header means raw int16 PCM at _PCM_SAMPLE_RATE: only what was
    # captured since the client's last upload, so append.
    if audio_bytes[:4] == b"RIFF":
        session.audio = audio_bytes
    else:
        session.pcm.extend(audio_bytes)
    session.last_touched = time.monotonic()
    session.new_audio.set()
    return True


def finish_session(session_id: str, owner: str = "") -> bool:
    session = _sessions.get(session_id)
    if session is None or session.finished or session.owner != owner:
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
        is_finished = session.finished
        if not is_finished and not partial_passes_are_affordable():
            # A metered transcription backend bills per pass and re-uploads
            # the whole growing buffer each time, so a preview that is
            # discarded the moment the final pass lands is not worth several
            # extra billed requests per turn — see that helper's own comment.
            #
            # Checked BEFORE building the snapshot below, deliberately.
            # _wav_from_pcm16(bytes(session.pcm)) copies the entire growing
            # buffer — at 16kHz 16-bit that is ~32KB per second of audio,
            # twice over (the bytes() copy and the WAV it wraps), on every
            # chunk tick. Doing that and then discarding it would cost, at a
            # roomful of concurrent sessions, tens of megabytes of pure
            # allocation churn every few seconds on an instance chosen for
            # having little memory to spare. Skipping the pass has to mean
            # skipping the work that feeds it, not just the request.
            #
            # The FINAL pass is untouched, here as below: what actually
            # reaches Bede never depends on this.
            log.debug(
                "streaming_transcription: session=%s skipping partial (metered backend)",
                session_id,
            )
            continue
        # Whichever protocol this session's client is speaking. The delta
        # path is preferred when there is any PCM at all; a session only ever
        # uses one, since the client does not mix them.
        audio_snapshot = _wav_from_pcm16(bytes(session.pcm)) if session.pcm else session.audio
        text = ""
        # faster-whisper has no incremental mode, so EVERY pass re-transcribes
        # the whole buffer from the start. Across a long hold that is O(N^2)
        # decode work — a 40-second answer costs roughly 220 seconds of audio
        # decoded — and it is the dominant reason a long answer feels slow to
        # transcribe. (The delta-upload change fixed the same shape on the
        # network, not this.)
        #
        # Partials exist only to show the child a live "we heard you" preview,
        # and a partial computed over 60 seconds of audio is both expensive and
        # stale by the time it lands. So past a threshold, stop paying for them
        # and let the buffer ride to the final pass. The FINAL pass is never
        # skipped — correctness of what actually reaches Bede never depends on
        # this.
        if audio_snapshot and not is_finished and settings.voice_partial_max_seconds > 0:
            # Correct for BOTH wire protocols a session might be running —
            # len(session.pcm) alone is only right for the delta path. A
            # legacy whole-buffer (RIFF) client never touches session.pcm at
            # all (see push_chunk above), so that length is always 0 on that
            # path, which silently disabled this cap for exactly the client
            # this module's own docstring promises stays fully supported —
            # a stale browser tab still running the pre-delta bundle during
            # or just after a rolling deploy. Both protocols produce 16kHz
            # mono 16-bit PCM (useVoiceRecorder.ts resamples to this before
            # encoding either way — see _wav_from_pcm16's own comment), so a
            # plain 44-byte WAV header subtraction is valid for the legacy
            # path too.
            pcm_len = len(session.pcm) if session.pcm else max(0, len(session.audio) - 44)
            seconds = pcm_len / (_PCM_SAMPLE_RATE * _PCM_BYTES_PER_SAMPLE)
            if seconds > settings.voice_partial_max_seconds:
                log.debug(
                    "streaming_transcription: session=%s skipping partial at %.1fs of audio",
                    session_id, seconds,
                )
                continue
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


async def events(session_id: str, owner: str = "") -> AsyncIterator[dict]:
    """Drained by the SSE endpoint. Self-cleans on normal completion (a
    'done' item) or the consumer disconnecting early (the finally block) —
    the periodic sweep below is only the backstop for a session nobody ever
    reads from at all. A session owned by someone else reports the same
    "unknown or expired" message a truly-missing session would — see
    push_chunk's docstring for why an ownership mismatch must never read
    differently from a 404."""
    session = _sessions.get(session_id)
    if session is None or session.owner != owner:
        yield {"type": "error", "message": "unknown or expired session"}
        return
    if session.active_reader:
        # A second, concurrent events() attach for a session that already has
        # one — see _Session.active_reader's own comment for what this
        # guards against. Ending here, without touching the queue or calling
        # _discard, leaves the FIRST (real) reader entirely undisturbed: it
        # keeps consuming the queue on its own and remains the one that
        # eventually tears the session down normally, via 'done' or its own
        # disconnect.
        return
    session.active_reader = True
    attached_at = time.monotonic()
    items_yielded = 0
    completed_normally = False
    try:
        while True:
            item = await session.queue.get()
            items_yielded += 1
            yield item
            if item.get("type") == "done":
                completed_normally = True
                break
    finally:
        if not completed_normally:
            # This generator is being torn down WITHOUT ever seeing "done" —
            # either the consumer genuinely disconnected (navigation, a
            # dropped connection) or something cancelled this coroutine out
            # from under it (server shutdown, or — the pattern actually
            # reported live from the demo, same X-Bede-Instance value on
            # every call in the trace, which already rules out cross-instance
            # routing — an intermediary proxy deciding a fully idle
            # connection is dead during the silent gap before any chunk has
            # ever uploaded). Logged unconditionally, not just past some
            # threshold: a session this young tearing itself down is exactly
            # the signature a family's screenshot can't tell apart from "the
            # session simply expired" without this. See
            # docs/VOICE_SETUP.md's cross-instance section for the identical
            # "observe before fix" reasoning behind core/instance_id.py.
            log.warning(
                "streaming_transcription: session=%s events() torn down early "
                "after %.2fs, %d item(s) delivered, without a 'done'",
                session_id, time.monotonic() - attached_at, items_yielded,
            )
        _discard(session_id)


def _discard(session_id: str) -> None:
    """Drop a session AND stop the worker that belongs to it.

    Popping the dict alone is not enough, and that was a real leak. A worker
    parked on `new_audio.wait()` is referenced by the event loop and holds
    `session` as an argument, so removing the dict entry collects nothing:
    the task waits forever and the whole PCM buffer stays reachable through
    it. At 16kHz 16-bit that is ~32KB per second of audio pinned per
    abandoned turn, for the life of the process.

    The completion path was always fine — `_worker_loop` returns after
    queuing `done`. What leaked was every session that ended any OTHER way:
    a consumer disconnecting mid-turn (a child navigating away, a tablet
    dropping the SSE connection — routine even on good WiFi) and anything
    the sweeper reclaimed. Reported from the demo as voice becoming
    unreliable after roughly ten turns.
    """
    session = _sessions.pop(session_id, None)
    if session is None:
        return
    worker = session.worker
    if worker is not None and not worker.done():
        worker.cancel()


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
            # Via _discard, not a bare pop: the worker has to go with it.
            _discard(sid)
