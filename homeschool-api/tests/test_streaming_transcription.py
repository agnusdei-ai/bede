"""
Tests for services/streaming_transcription.py — the in-memory session
coordination behind POST/GET /voice/stream/* (routers/voice.py). See that
module's docstring for the full design rationale: this replaces browser-
native SpeechRecognition as the primary voice-input path.

transcribe_audio() itself (faster-whisper) is mocked throughout — these
tests are about the session/queue coordination, not Whisper's own accuracy.
"""
import asyncio

import pytest

import services.streaming_transcription as st


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Module-level _sessions dict persists across tests otherwise — start
    each test from a clean slate."""
    st._sessions.clear()
    yield
    st._sessions.clear()




@pytest.mark.asyncio
async def test_start_session_creates_a_unique_id_with_a_live_worker():
    session_id = st.start_session(language="en")
    assert session_id in st._sessions
    assert st._sessions[session_id].worker is not None
    assert not st._sessions[session_id].worker.done()

    other_id = st.start_session(language="en")
    assert other_id != session_id


@pytest.mark.asyncio
async def test_push_chunk_on_unknown_session_returns_false():
    assert st.push_chunk("does-not-exist", b"audio") is False


@pytest.mark.asyncio
async def test_finish_session_on_unknown_session_returns_false():
    assert st.finish_session("does-not-exist") is False


@pytest.mark.asyncio
async def test_push_chunk_transcribes_and_emits_a_partial_event(monkeypatch):
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    assert st.push_chunk(session_id, b"fake-wav-bytes") is True

    # Held in this scope (not a helper that returns and lets the generator
    # go out of scope) — an abandoned, still-suspended async generator gets
    # garbage-collected and its `finally` cleanup runs, which would pop the
    # session prematurely and defeat the "still tracked" assertion below.
    gen = st.events(session_id)
    item = await asyncio.wait_for(gen.__anext__(), timeout=2)
    assert item == {"type": "partial", "text": "hello"}
    # Not finished — the session must still be tracked for further chunks.
    assert session_id in st._sessions


@pytest.mark.asyncio
async def test_finish_without_any_prior_chunk_emits_an_empty_final_then_done():
    session_id = st.start_session(language="en")
    assert st.finish_session(session_id) is True

    gen = st.events(session_id)
    first = await asyncio.wait_for(gen.__anext__(), timeout=2)
    second = await asyncio.wait_for(gen.__anext__(), timeout=2)
    await gen.aclose()

    assert first == {"type": "final", "text": ""}
    assert second == {"type": "done"}


@pytest.mark.asyncio
async def test_finish_after_a_chunk_transcribes_the_final_buffer_and_cleans_up(monkeypatch):
    calls = []

    async def fake_transcribe(audio_bytes, language="en"):
        calls.append(audio_bytes)
        return {"text": f"transcript for {len(audio_bytes)} bytes", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"short")

    events_seen = []
    async for item in st.events(session_id):
        events_seen.append(item)
        if item["type"] == "partial":
            # Simulate the child releasing right after the first partial result.
            st.finish_session(session_id)

    assert [e["type"] for e in events_seen] == ["partial", "final", "done"]
    # A raw (non-RIFF) push is a PCM delta now, so what reaches the
    # transcriber is those bytes plus the 44-byte WAV header the worker wraps
    # them in — see push_chunk and _wav_from_pcm16.
    wrapped = len(b"short") + 44
    assert events_seen[0]["text"] == f"transcript for {wrapped} bytes"
    assert events_seen[1]["text"] == f"transcript for {wrapped} bytes"
    # events() cleans up the session on its own 'done' exit.
    assert session_id not in st._sessions


@pytest.mark.asyncio
async def test_push_chunk_after_finish_is_rejected():
    session_id = st.start_session(language="en")
    st.finish_session(session_id)
    # Drain the final+done so the session is still resolvable for this
    # assertion's own push_chunk call (finished flips synchronously in
    # finish_session, independent of whether events() has drained yet).
    assert st.push_chunk(session_id, b"too-late") is False


@pytest.mark.asyncio
async def test_rapid_pushes_coalesce_into_the_latest_buffer_only(monkeypatch):
    """Real design goal: chunk upload cadence must never be throttled by
    transcription latency, and the worker must never run two overlapping
    whisper calls for the same session. A slow fake transcribe() proves
    both — pushes that land while a transcription is already in flight
    must be coalesced into one more pass on the latest buffer, not queued
    up as separate redundant calls."""
    call_count = 0

    async def slow_transcribe(audio_bytes, language="en"):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"text": f"len={len(audio_bytes)}", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", slow_transcribe)

    session_id = st.start_session(language="en")
    # Fire several pushes faster than slow_transcribe can process them.
    for i in range(5):
        st.push_chunk(session_id, b"x" * (i + 1))
        await asyncio.sleep(0.005)
    st.finish_session(session_id)

    events_seen = []
    async for item in st.events(session_id):
        events_seen.append(item)

    assert events_seen[-1] == {"type": "done"}
    assert events_seen[-2]["type"] == "final"
    # Far fewer whisper calls than pushes — proof of coalescing, not a
    # brittle exact count (timing-sensitive across machines).
    assert call_count < 5
    assert session_id not in st._sessions


@pytest.mark.asyncio
async def test_events_on_a_completely_unknown_session_yields_an_error_immediately():
    events_seen = [item async for item in st.events("never-started")]
    assert events_seen == [{"type": "error", "message": "unknown or expired session"}]


@pytest.mark.asyncio
async def test_events_disconnecting_early_still_removes_the_session(monkeypatch):
    """The consumer (SSE endpoint) can stop iterating before 'done' — a
    client disconnect, not just normal completion. The generator's own
    finally block must still clean up rather than leaking the session."""
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "partial text", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"audio")

    gen = st.events(session_id)
    await asyncio.wait_for(gen.__anext__(), timeout=2)
    await gen.aclose()  # early disconnect, before 'done'

    assert session_id not in st._sessions


@pytest.mark.asyncio
async def test_sweep_loop_evicts_sessions_idle_past_the_ttl(monkeypatch):
    session_id = st.start_session(language="en")
    # Backdate last_touched past the TTL without waiting the real 180s.
    st._sessions[session_id].last_touched -= (st._SESSION_TTL_SECONDS + 1)

    monkeypatch.setattr(st, "_SWEEP_INTERVAL_SECONDS", 0.01)
    await st._sweep_loop()

    assert session_id not in st._sessions


@pytest.mark.asyncio
async def test_each_transcription_pass_logs_its_own_elapsed_time(monkeypatch, caplog):
    """Regression for a real reported delay: a child released the mic and
    the UI sat on "Transcribing…" for a while, with no way to tell from a
    client-side DebugOverlay trace alone whether that was the final pass
    itself being slow (every pass re-transcribes the WHOLE growing buffer)
    or it queued up behind an in-flight partial pass the coalescing design
    can't cancel. This is the one number that tells them apart — see
    docs/VOICE_SETUP.md's transcription-delay section."""
    async def fake_transcribe(audio_bytes, language="en"):
        await asyncio.sleep(0.01)
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    with caplog.at_level("INFO", logger="services.streaming_transcription"):
        session_id = st.start_session(language="en")
        st.push_chunk(session_id, b"some-audio-bytes")
        st.finish_session(session_id)

        events_seen = [item async for item in st.events(session_id)]

    assert [e["type"] for e in events_seen] == ["final", "done"]
    pass_logs = [r for r in caplog.records if "streaming_transcription: session=" in r.message]
    assert pass_logs, "no per-pass timing log was emitted"
    assert f"session={session_id}" in pass_logs[-1].message
    assert "pass=final" in pass_logs[-1].message
    # b"some-audio-bytes" is a raw PCM delta now, so the logged size is
    # those 16 bytes plus the 44-byte WAV header the worker wraps them in.
    assert f"audio_bytes={len(b'some-audio-bytes') + 44}" in pass_logs[-1].message
    assert "elapsed=" in pass_logs[-1].message


# ── Ownership (IDOR guard) ───────────────────────────────────────────────────
# routers/voice.py's _stream_owner() passes this through so a session
# started by one authenticated identity can't be pushed to, finished, or
# read by another — see push_chunk's own docstring for why a mismatch must
# read identically to "unknown session".

@pytest.mark.asyncio
async def test_push_chunk_rejects_a_different_owner():
    session_id = st.start_session(language="en", owner="AAA111")
    assert st.push_chunk(session_id, b"audio", owner="BBB222") is False


@pytest.mark.asyncio
async def test_push_chunk_accepts_the_matching_owner():
    session_id = st.start_session(language="en", owner="AAA111")
    assert st.push_chunk(session_id, b"audio", owner="AAA111") is True


@pytest.mark.asyncio
async def test_finish_session_rejects_a_different_owner():
    session_id = st.start_session(language="en", owner="parent")
    assert st.finish_session(session_id, owner="child") is False
    # The real owner can still finish it — the mismatch didn't corrupt state.
    assert st.finish_session(session_id, owner="parent") is True


@pytest.mark.asyncio
async def test_events_reports_unknown_for_a_different_owner():
    session_id = st.start_session(language="en", owner="AAA111")
    events_seen = [item async for item in st.events(session_id, owner="BBB222")]
    assert events_seen == [{"type": "error", "message": "unknown or expired session"}]
    # Unlike a real "unknown session" read, this must NOT tear down the
    # session — it genuinely exists, just not for this caller.
    assert session_id in st._sessions


@pytest.mark.asyncio
async def test_default_empty_owner_preserves_prior_no_owner_behavior():
    """Every call in this file above this section never passes owner= at
    all — the default "" on both start and later calls must keep comparing
    equal, so none of that existing coverage silently started exercising
    the ownership check instead of what it was written to test."""
    session_id = st.start_session(language="en")
    assert st.push_chunk(session_id, b"audio") is True
    assert st.finish_session(session_id) is True


# ── Delta upload protocol ────────────────────────────────────────────────────
#
# The client used to re-upload the whole growing buffer on every tick, which
# is O(N^2) bandwidth over a hold — 8.3MB of upload for a 40-second answer and
# 63MB at the 120s safety cap. It now sends only what it captured since its
# last upload. push_chunk tells the two apart by looking for a RIFF header, so
# an older client keeps working against a newer server.

@pytest.mark.asyncio
async def test_raw_pcm_chunks_append_rather_than_replace():
    session_id = st.start_session()
    session = st._sessions[session_id]

    assert st.push_chunk(session_id, b"\x01\x02" * 100) is True
    assert st.push_chunk(session_id, b"\x03\x04" * 100) is True

    assert len(session.pcm) == 400
    assert session.pcm[:2] == b"\x01\x02"
    assert session.pcm[200:202] == b"\x03\x04"
    # The legacy whole-buffer field is untouched on this path.
    assert session.audio == b""


@pytest.mark.asyncio
async def test_a_riff_chunk_still_replaces_for_an_older_client():
    session_id = st.start_session()
    session = st._sessions[session_id]

    first = st._wav_from_pcm16(b"\x01\x02" * 100)
    second = st._wav_from_pcm16(b"\x03\x04" * 200)
    st.push_chunk(session_id, first)
    st.push_chunk(session_id, second)

    # Replaced, not concatenated — that is what the old protocol expects.
    assert session.audio == second
    assert len(session.pcm) == 0


def test_wrapped_pcm_is_a_readable_wav_at_16k_mono():
    """The worker hands this to services/transcription.py, which decodes via
    soundfile — loose samples with no container would fail to read at all."""
    import io

    import soundfile as sf

    wav = st._wav_from_pcm16(b"\x00\x10" * 8000)
    data, rate = sf.read(io.BytesIO(wav), dtype="float32", always_2d=False)
    assert rate == 16000
    assert data.ndim == 1
    assert len(data) == 8000


# ── Partial-pass cost ────────────────────────────────────────────────────────
#
# faster-whisper has no incremental mode, so every pass re-transcribes the
# whole buffer — O(N^2) decode work across a long hold, and the dominant
# reason a long answer feels slow. Partials are only a live preview, so they
# stop past a threshold. The final pass never does.

@pytest.mark.asyncio
async def test_partials_stop_once_the_buffer_grows_past_the_cap(monkeypatch):
    calls = []

    async def fake_transcribe(audio_bytes, language="en"):
        calls.append(len(audio_bytes))
        return {"text": "x", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(st.settings, "voice_partial_max_seconds", 1.0)

    session_id = st.start_session(language="en")
    # 2 seconds of 16kHz mono int16 — past the 1s cap.
    st.push_chunk(session_id, b"\x00\x10" * 32000)
    await asyncio.sleep(0.05)
    assert calls == [], "a partial was computed despite exceeding the cap"

    # The final pass must still run, over everything captured.
    st.finish_session(session_id)
    events = [item async for item in st.events(session_id)]
    assert [e["type"] for e in events] == ["final", "done"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_partials_still_run_under_the_cap(monkeypatch):
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "heard you", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(st.settings, "voice_partial_max_seconds", 30.0)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"\x00\x10" * 8000)  # 0.5s, well under

    gen = st.events(session_id)
    item = await asyncio.wait_for(gen.__anext__(), timeout=2)
    await gen.aclose()
    assert item == {"type": "partial", "text": "heard you"}
