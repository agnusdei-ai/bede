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
async def test_events_torn_down_early_logs_a_warning_naming_the_session(monkeypatch, caplog):
    """Regression for a real reported bug: a voice session opened, then its
    own very first chunk/finish calls both 404'd ("Unknown or finished
    streaming session") a few seconds later, on the SAME X-Bede-Instance the
    whole time — which rules out cross-instance routing (see
    docs/VOICE_SETUP.md). The only server-side path that removes a session
    that young is this generator's own finally block running before a
    'done' ever arrived — and until now nothing logged that distinction, so
    a genuinely early teardown was indistinguishable, from server logs
    alone, from ordinary cleanup after a normal completion."""
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "partial text", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"audio")

    with caplog.at_level("WARNING", logger="services.streaming_transcription"):
        gen = st.events(session_id)
        await asyncio.wait_for(gen.__anext__(), timeout=2)  # the one partial — attaches active_reader
        await gen.aclose()  # torn down here, before 'finish'/'done' ever arrives

    assert session_id not in st._sessions
    warnings = [r for r in caplog.records if "torn down early" in r.message]
    assert len(warnings) == 1
    assert f"session={session_id}" in warnings[0].message
    assert "without a 'done'" in warnings[0].message


@pytest.mark.asyncio
async def test_events_completing_normally_logs_no_early_teardown_warning(monkeypatch, caplog):
    """The new warning above must fire ONLY on an early teardown — an
    ordinary turn that runs all the way to 'done' is not the failure this
    guards, and must never be confused for one in server logs."""
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"some-audio-bytes")
    st.finish_session(session_id)

    with caplog.at_level("WARNING", logger="services.streaming_transcription"):
        events_seen = [item async for item in st.events(session_id)]

    assert events_seen[-1] == {"type": "done"}
    assert not any("torn down early" in r.message for r in caplog.records)


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


# ── Concurrent readers ────────────────────────────────────────────────────
# Reported live from the demo on a real, poor mobile connection: a client
# that had already sent its final chunk and a successful /finish still saw
# its own, still-open events() stream come back "unknown or expired session"
# moments later — on a deployment confirmed pinned to a single instance, so
# cross-instance session loss is ruled out. The only other way _discard()
# can run out from under a session still mid-turn is a second, concurrent
# events() attach for the same id racing the first on the same queue.

@pytest.mark.asyncio
async def test_a_second_concurrent_reader_does_not_steal_or_discard_the_first(monkeypatch):
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"audio")

    first = st.events(session_id)
    # Attach the first reader and let it actually consume the partial —
    # this is what sets active_reader=True.
    first_item = await asyncio.wait_for(first.__anext__(), timeout=2)
    assert first_item == {"type": "partial", "text": "hello"}

    # A second, concurrent attach for the SAME session — must end quietly,
    # never touching the queue or discarding the session out from under the
    # first reader.
    second_items = [item async for item in st.events(session_id)]
    assert second_items == []
    assert session_id in st._sessions, "the second attach must not discard the session"

    # The FIRST reader is still the one driving this session to completion —
    # finishing it now must still deliver normally through the original
    # connection.
    st.finish_session(session_id)
    remaining = [item async for item in first]
    assert [e["type"] for e in remaining] == ["final", "done"]
    assert session_id not in st._sessions


@pytest.mark.asyncio
async def test_a_second_reader_after_the_first_finishes_gets_unknown_session():
    """Once the real reader has driven the session to completion (and
    _discard has run), a LATER duplicate attach is indistinguishable from any
    other truly-gone session — the existing, unchanged behavior."""
    session_id = st.start_session(language="en")
    st.finish_session(session_id)
    # No early break — the generator must run to its own natural
    # StopAsyncIteration so its finally block (and _discard) fires
    # synchronously here rather than at some later, non-deterministic GC.
    async for _ in st.events(session_id):
        pass

    assert session_id not in st._sessions
    late_items = [item async for item in st.events(session_id)]
    assert late_items == [{"type": "error", "message": "unknown or expired session"}]


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
async def test_partials_stop_past_the_cap_for_a_legacy_riff_client_too(monkeypatch):
    """The cap above is proven against the delta (raw PCM) protocol. A stale
    browser tab still running the pre-delta bundle during/after a rolling
    deploy speaks the OLD whole-buffer (RIFF) protocol instead — push_chunk
    routes that to session.audio, never session.pcm. The cap check used to
    read len(session.pcm) unconditionally, which is always 0 on that path,
    silently disabling the cap this test's sibling just confirmed works for
    the other one. Same assertions, RIFF-framed input this time."""
    calls = []

    async def fake_transcribe(audio_bytes, language="en"):
        calls.append(len(audio_bytes))
        return {"text": "x", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(st.settings, "voice_partial_max_seconds", 1.0)

    session_id = st.start_session(language="en")
    # A full legacy WAV upload — 2 seconds of 16kHz mono int16, past the 1s
    # cap, wrapped exactly as the pre-delta client would have encoded it.
    st.push_chunk(session_id, st._wav_from_pcm16(b"\x00\x10" * 32000))
    await asyncio.sleep(0.05)
    assert calls == [], "a partial was computed despite exceeding the cap (legacy RIFF path)"

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


# ── Worker-task lifetime ────────────────────────────────────────────────
#
# Reported from the demo: "voice reliability after a few turns... it couldn't
# hear me after 20 minutes and about 10 turns", on a stable WiFi network.
# Degradation proportional to TURNS rather than to network conditions points
# at something accumulating per turn, and this is it.


@pytest.mark.asyncio
async def test_the_worker_task_does_not_outlive_its_session(monkeypatch):
    """Every turn starts a worker task. If it never returns, every turn leaks
    one task AND the entire PCM buffer it holds a reference to — popping the
    session from _sessions does not collect it, because the task's own frame
    keeps the session object alive."""

    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    session = st._sessions[session_id]
    st.push_chunk(session_id, b"audio")
    st.finish_session(session_id)

    async for item in st.events(session_id):
        if item["type"] == "done":
            break

    # Let the worker settle after the 'done' it just queued.
    await asyncio.sleep(0)
    assert session.worker is not None
    assert session.worker.done(), (
        "worker task is still running after the session ended — it and the "
        "audio buffer it holds are leaked for the life of the process"
    )


@pytest.mark.asyncio
async def test_an_abandoned_sessions_worker_is_stopped_too(monkeypatch):
    """The consumer disconnecting early is the ordinary case on a tablet — a
    child navigates away mid-turn. events() already drops the session from the
    dict there; the task has to go with it."""

    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    session_id = st.start_session(language="en")
    session = st._sessions[session_id]
    st.push_chunk(session_id, b"audio")

    # aclose(), not a bare `break`. Breaking out of an `async for` does not
    # close an async generator — its finally block runs only at GC, which is
    # not deterministic. sse_starlette closes the iterator when the client
    # disconnects, so aclose() is what actually models a dropped connection.
    stream = st.events(session_id)
    async for item in stream:
        break
    await stream.aclose()

    await asyncio.sleep(0)
    assert session.worker.done() or session.worker.cancelled(), (
        "worker task survived a consumer that disconnected"
    )


@pytest.mark.asyncio
async def test_many_turns_leave_nothing_running(monkeypatch):
    """The reported shape, directly: ten turns in a row must leave ten
    finished tasks, not ten parked ones."""

    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    workers = []
    for turn in range(10):
        session_id = st.start_session(language="en")
        workers.append(st._sessions[session_id].worker)
        st.push_chunk(session_id, b"audio")

        # Alternate the two ways a turn really ends. Only the completed half
        # ever worked; the abandoned half is what leaked, and a session mix
        # is what a twenty-minute sitting actually looks like.
        if turn % 2 == 0:
            st.finish_session(session_id)
            async for item in st.events(session_id):
                if item["type"] == "done":
                    break
        else:
            stream = st.events(session_id)
            async for item in stream:
                break
            await stream.aclose()

    await asyncio.sleep(0)
    still_running = [w for w in workers if not (w.done() or w.cancelled())]
    assert not still_running, f"{len(still_running)} of 10 worker tasks leaked"
    assert st._sessions == {}
