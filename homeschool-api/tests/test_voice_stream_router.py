"""
Router-level tests for POST/GET /voice/stream/* (routers/voice.py) — called
directly rather than through a full TestClient, same pattern as
tests/test_extract_narration_router.py, since require_auth's JWT/fingerprint
plumbing isn't what's under test here. Session-coordination logic itself is
covered in tests/test_streaming_transcription.py; these confirm the HTTP
layer wires it up correctly (404s, audio validation, SSE framing).
"""
import asyncio
import io
import json

import pytest
from fastapi import HTTPException, UploadFile

import services.streaming_transcription as st
from routers.voice import (
    StreamStartRequest,
    stream_chunk,
    stream_events_endpoint,
    stream_finish,
    stream_start,
)


@pytest.fixture(autouse=True)
def _reset_sessions():
    st._sessions.clear()
    yield
    st._sessions.clear()


def _wav_upload(data: bytes = b"RIFFxxxxWAVEfake") -> UploadFile:
    return UploadFile(io.BytesIO(data), filename="chunk.wav")


@pytest.mark.asyncio
async def test_stream_start_returns_a_session_id():
    result = await stream_start(StreamStartRequest(language="en"), auth={"role": "parent"})
    assert result["session_id"] in st._sessions


@pytest.mark.asyncio
async def test_stream_chunk_accepts_valid_audio_for_a_known_session(monkeypatch):
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "ok", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    start_result = await stream_start(StreamStartRequest(language="en"), auth={"role": "parent"})
    session_id = start_result["session_id"]

    result = await stream_chunk(session_id, audio=_wav_upload(), auth={"role": "parent"})
    assert result == {"accepted": True}


@pytest.mark.asyncio
async def test_stream_chunk_404s_for_an_unknown_session():
    with pytest.raises(HTTPException) as exc_info:
        await stream_chunk("never-started", audio=_wav_upload(), auth={"role": "parent"})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_stream_chunk_rejects_non_audio_data():
    start_result = await stream_start(StreamStartRequest(language="en"), auth={"role": "parent"})
    session_id = start_result["session_id"]

    bogus = UploadFile(io.BytesIO(b"not audio at all"), filename="chunk.txt")
    with pytest.raises(HTTPException) as exc_info:
        await stream_chunk(session_id, audio=bogus, auth={"role": "parent"})
    assert exc_info.value.status_code == 415


@pytest.mark.asyncio
async def test_stream_finish_404s_for_an_unknown_session():
    with pytest.raises(HTTPException) as exc_info:
        await stream_finish("never-started", auth={"role": "parent"})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_stream_finish_succeeds_for_a_known_session():
    start_result = await stream_start(StreamStartRequest(language="en"), auth={"role": "parent"})
    session_id = start_result["session_id"]

    result = await stream_finish(session_id, auth={"role": "parent"})
    assert result == {"accepted": True}


@pytest.mark.asyncio
async def test_stream_events_endpoint_yields_plain_json_sse_chunks(monkeypatch):
    """Same 'no pre-formatted data: framing' contract as /tutor/chat's own
    event_generator — EventSourceResponse owns that, a chunk that already
    contains 'data: ' would come out double-wrapped and unparseable
    client-side (see tests/test_ai_service_streaming.py's own comment)."""
    async def fake_transcribe(audio_bytes, language="en"):
        return {"text": "hello Bede", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)

    start_result = await stream_start(StreamStartRequest(language="en"), auth={"role": "parent"})
    session_id = start_result["session_id"]
    await stream_chunk(session_id, audio=_wav_upload(), auth={"role": "parent"})
    # A real gap, like an actual hold (upload, then keep talking, then
    # release) — calling finish immediately with zero elapsed time is a
    # synthetic race the worker correctly coalesces into a single final
    # pass (proven separately by test_streaming_transcription.py's own
    # coalescing test); this test wants to see partial and final as two
    # distinct events, so it needs to give the worker a chance to process
    # the chunk first.
    await asyncio.sleep(0.05)
    await stream_finish(session_id, auth={"role": "parent"})

    response = await stream_events_endpoint(session_id, auth={"role": "parent"})
    chunks = [chunk async for chunk in response.body_iterator]
    parsed = [json.loads(c) for c in chunks]

    assert not any(str(c).startswith("data: ") for c in chunks)
    assert parsed[0] == {"type": "partial", "text": "hello Bede"}
    assert parsed[1] == {"type": "final", "text": "hello Bede"}
    assert parsed[2] == {"type": "done"}
